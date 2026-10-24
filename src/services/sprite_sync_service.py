"""
Digimon sprite database sync.

Refreshes the player's GLOBAL sprite assets (assets/{monsters, monsters_dot,
monsters_hidef}) against the Digimon Database (https://digimon-db.omnipet.app.br)
for the pet/enemy names used by a module.

For each name + the module's primary/secondary sprite formats it asks the
server's sprite-checksum endpoint for the canonical sheet's hash, computes the
identical hash for the local asset file (md5("stem:size")[:8]), and — when they
differ (or the local file is missing) — downloads the global sheet and overwrites
the local one. The hash uses the server's canonical stem, so the comparison
reduces to a content-size check exactly like the server's own sync model.

Best-effort: if the database is unreachable or there's no internet, callers use
is_available() to skip the whole process.
"""
import hashlib
import json
import os
import re

import requests

from core import runtime_globals
from utils.asset_utils import resolve_path
from utils.sprite_utils import get_sprite_name


class SpriteSyncService:
    BASE_URL = "https://digimon-db.omnipet.app.br"

    # api format -> assets sub-folder (matches the sprite loading flow)
    FMT_FOLDER = {"color": "monsters", "dot": "monsters_dot", "hd": "monsters_hidef"}
    # module sprite-format name -> api format
    FMT_FROM_FORMAT = {"Color": "color", "Dot": "dot", "HD": "hd"}

    # DB name fields, priority order (mirrors the Digimon DB matcher)
    NAME_FIELDS = [
        "name_english", "name_dub", "name_japanese",
        "name_romanization", "name_alternatives",
    ]

    # Names per checksum request when computing a module's server fingerprint.
    # Also the granularity at which changes are detected: only chunks whose
    # aggregate hash changed get a per-name re-check.
    CHUNK_SIZE = 50
    CACHE_NAME = ".sprite_sync_cache.json"

    def __init__(self):
        self._index = None   # norm(name) -> record

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _norm(s: str) -> str:
        if not s:
            return ""
        s = s.replace("（", "(").replace("）", ")").replace("：", ":")
        return re.sub(r"[\s\-\.\'\:\(\)_]", "", s).lower()

    def is_available(self, timeout: float = 4.0) -> bool:
        """True when the Digimon Database API is reachable (implies internet)."""
        try:
            r = requests.get(self.BASE_URL + "/api/levels", timeout=timeout)
            return r.status_code == 200
        except Exception:
            return False

    def _ensure_catalog(self, timeout: float = 15.0) -> bool:
        """Download + index the full catalogue once (name -> record)."""
        if self._index is not None:
            return True
        try:
            records = []
            offset, total = 0, None
            while total is None or offset < total:
                r = requests.get(
                    self.BASE_URL + "/api/digimon",
                    params={"offset": offset, "limit": 216},
                    timeout=timeout,
                )
                if r.status_code != 200:
                    return False
                data = r.json()
                results = data.get("results") or []
                if not results:
                    break
                records.extend(results)
                total = data.get("total", len(records))
                offset += len(results)

            # Build the name index field-by-field (all records' name-english
            # before any name-dub, etc.) so it resolves names identically to the
            # server's resolve_name — required for the local fingerprint to match.
            index = {}
            for field in self.NAME_FIELDS:
                for rec in records:
                    val = rec.get(field)
                    if not val:
                        continue
                    for v in (val if isinstance(val, list) else [val]):
                        key = self._norm(v)
                        if key and key not in index:
                            index[key] = rec
            self._index = index
            return True
        except Exception as e:
            runtime_globals.game_console.log(f"[SpriteSync] catalogue fetch failed: {e}")
            return False

    def _resolve(self, name: str):
        return self._index.get(self._norm(name)) if self._index else None

    # --------------------------------------------------- fingerprint + cache

    def _server_fingerprint(self, names, api_fmts, timeout):
        """Per-format list of chunked aggregate checksum hashes for the names.

        This is what the server currently has for this module. Comparing it to
        the value stored from the last successful sync lets a boot skip a module
        in 1-2 requests when nothing changed server-side. Returns None on any
        request failure (so the caller falls back to a full sync).
        """
        fp = {f: [] for f in api_fmts}
        for i in range(0, len(names), self.CHUNK_SIZE):
            chunk = names[i:i + self.CHUNK_SIZE]
            try:
                params = [("names", n) for n in chunk] + [("fmt", f) for f in api_fmts]
                r = requests.get(self.BASE_URL + "/api/sprites/checksum",
                                 params=params, timeout=timeout)
                if r.status_code != 200:
                    return None
                data = r.json()
            except Exception:
                return None
            for f in api_fmts:
                entry = data.get(f)
                fp[f].append(entry.get("hash") if entry else None)
        return fp

    def _cache_path(self):
        try:
            from utils.module_utils import get_modules_dir
            return os.path.join(get_modules_dir(), self.CACHE_NAME)
        except Exception:
            return None

    def _load_cache(self):
        path = self._cache_path()
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_cache(self, cache):
        path = self._cache_path()
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cache, f)
        except Exception as e:
            runtime_globals.game_console.log(f"[SpriteSync] cache write failed: {e}")

    def _module_formats(self, module):
        """[(api_fmt, folder)] for the module's primary then secondary format."""
        formats = []
        primary = getattr(module, "primary_sprite_format", "Color") or "Color"
        secondary = getattr(module, "secondary_sprite_format", "HD") or "HD"
        for fmt_name in (primary, secondary):
            api = self.FMT_FROM_FORMAT.get(fmt_name)
            if api and not any(api == f[0] for f in formats):
                formats.append((api, self.FMT_FOLDER[api]))
        return formats

    def _module_names(self, module):
        """Distinct pet + enemy names declared by the module."""
        names, seen = [], set()
        folder = getattr(module, "folder_path", None)
        if not folder:
            return names
        for fname, key in (("monster.json", "monster"), ("battle.json", "enemies")):
            path = os.path.join(folder, fname)
            try:
                with open(resolve_path(path), encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            for entry in (data.get(key) or []):
                nm = entry.get("name")
                if nm and nm not in seen:
                    seen.add(nm)
                    names.append(nm)
        return names

    # ----------------------------------------------------------------- update

    def update_module(self, module, progress_cb=None, timeout: float = 15.0) -> int:
        """Update local global sprites for one module. Returns files updated.

        ``progress_cb(text, done, total)`` is called with a human-readable
        status ("DMC: checking Agumon" / "DMC: downloading Agumon") plus, once
        the work can be counted, how far through it is -- so a caller can show
        a name, a percentage, or both. ``done``/``total`` are None while the
        phase has nothing to count. Caller is responsible for the
        is_available() gate.

        **Every phase reports.** The two fingerprint passes and the catalogue
        download all take network time and used to run silently, which left a
        caller showing one frozen word for the whole sync -- and, for a module
        already in sync, for the entire call, since the fast path returns
        before the first name is ever reached.
        """
        def report(text, done=None, total=None):
            if not progress_cb:
                return
            try:
                progress_cb(text, done, total)
            except Exception as exc:
                # A display callback must never be able to break a sync.
                runtime_globals.game_console.log(
                    f"[SpriteSync] progress callback failed: {exc}")

        formats = self._module_formats(module)
        if not formats:
            return 0
        names = self._module_names(module)
        if not names:
            return 0

        module_name = getattr(module, "name", "") or ""
        api_fmts = [f[0] for f in formats]

        # 1) Fast path: compare the server's fingerprint to the one stored after
        # the last sync. This needs no catalogue download, so an up-to-date
        # module costs only a couple of checksum requests.
        report(f"{module_name}: comparing with database")
        fingerprint = self._server_fingerprint(names, api_fmts, timeout)
        cache = self._load_cache()
        cached_fp = cache.get(module_name)
        if fingerprint is not None and fingerprint == cached_fp:
            return 0

        # 2) Server changed (or first run). Resolve the catalogue, then build a
        # LOCAL fingerprint the exact same way the server computes its own and
        # compare chunk-by-chunk. A chunk whose local sprites already match the
        # server is skipped with NO per-name requests and NO downloads — so a
        # module that's already in sync costs only the fingerprint requests.
        report(f"{module_name}: fetching database")
        if not self._ensure_catalog(timeout):
            return 0

        chunks = [names[i:i + self.CHUNK_SIZE] for i in range(0, len(names), self.CHUNK_SIZE)]
        name_format = getattr(module, "name_format", "$_dmc") or "$_dmc"
        report(f"{module_name}: checking local sprites")
        local_fp = self._local_fingerprint(chunks, formats, name_format)

        # Only the chunks that differ are walked name by name, so the count the
        # caller is shown is the work actually left rather than the roster.
        pending = [name
                   for ci, chunk in enumerate(chunks)
                   if self._chunk_differs(fingerprint, local_fp, api_fmts, ci)
                   for name in chunk]

        updated = 0
        total = len(pending)
        # Counted 1-based, so the run ends on 100% rather than one item short:
        # a bar that stops at 80% and then jumps to "Installed" reads as having
        # given up, which is the thing this reporting exists to prevent.
        for position, name in enumerate(pending, 1):
            report(f"{module_name}: checking {name}", position, total)
            updated += self._sync_one(
                name, formats, name_format, module_name,
                lambda text, d=position, t=total: report(text, d, t), timeout)

        # Record the server fingerprint so later boots skip via the fast path.
        if fingerprint is not None:
            cache[module_name] = fingerprint
            self._save_cache(cache)

        return updated

    @staticmethod
    def _chunk_differs(server_fp, local_fp, api_fmts, ci):
        for fmt in api_fmts:
            sv = (server_fp or {}).get(fmt) or []
            lv = (local_fp or {}).get(fmt) or []
            s = sv[ci] if ci < len(sv) else None
            l = lv[ci] if ci < len(lv) else None
            if s != l:
                return True
        return False

    def _local_fingerprint(self, chunks, formats, name_format):
        """Per-format list of chunk hashes for the LOCAL assets, computed the
        same way the server's checksum endpoint does so they can be compared."""
        fp = {f[0]: [] for f in formats}
        for chunk in chunks:
            for api_fmt, folder in formats:
                fp[api_fmt].append(self._local_chunk_hash(chunk, folder, name_format))
        return fp

    def _local_chunk_hash(self, chunk, folder, name_format):
        """md5 of sorted "<stem>:<size>" entries for the local asset files of a
        chunk, keyed by canonical stem and ordered by the server's filename —
        identical to the server's aggregate. None when no local files exist."""
        by_stem = {}
        for name in chunk:
            rec = self._resolve(name)
            if not rec:
                continue
            stem = (rec.get("name_english") or "").replace(":", "_")
            if not stem or stem in by_stem:
                continue
            rel = os.path.join("assets", folder, get_sprite_name(name, name_format) + ".zip")
            abs_path = resolve_path(rel)
            if os.path.exists(abs_path):
                by_stem[stem] = os.path.getsize(abs_path)
        if not by_stem:
            return None
        stems = sorted(by_stem, key=lambda s: s + "_dmc.zip")
        joined = "\n".join(f"{s}:{by_stem[s]}" for s in stems)
        return hashlib.md5(joined.encode()).hexdigest()[:8]

    def _sync_one(self, name, formats, name_format, module_name, report, timeout):
        """Check one name across the formats and download any sheet that differs
        from the local asset. Returns the number of files written.

        ``report(text)`` carries this name's place in the run already bound, so
        a download reports at the same position as the check that found it.
        """
        rec = self._resolve(name)
        if not rec:
            return 0
        stem = (rec.get("name_english") or "").replace(":", "_")
        rid = rec.get("id")
        if not stem or not rid:
            return 0

        try:
            params = [("names", name)] + [("fmt", f[0]) for f in formats]
            r = requests.get(self.BASE_URL + "/api/sprites/checksum",
                             params=params, timeout=timeout)
            if r.status_code != 200:
                return 0
            sums = r.json()
        except Exception:
            return 0

        updated = 0
        for api_fmt, folder in formats:
            entry = sums.get(api_fmt)
            if not entry or not entry.get("hash"):
                continue   # server has no global sheet for this digimon + format

            rel = os.path.join("assets", folder,
                               get_sprite_name(name, name_format) + ".zip")
            abs_path = resolve_path(rel)

            local_hash = None
            if os.path.exists(abs_path):
                size = os.path.getsize(abs_path)
                local_hash = hashlib.md5(f"{stem}:{size}".encode()).hexdigest()[:8]
            if local_hash == entry["hash"]:
                continue   # up to date

            report(f"{module_name}: downloading {name}")
            try:
                dr = requests.get(
                    f"{self.BASE_URL}/api/digimon/{rid}/sheet/{api_fmt}",
                    timeout=timeout,
                )
                if dr.status_code != 200 or not dr.content:
                    continue
                os.makedirs(os.path.dirname(abs_path), exist_ok=True)
                with open(abs_path, "wb") as f:
                    f.write(dr.content)
                updated += 1
            except Exception as e:
                runtime_globals.game_console.log(
                    f"[SpriteSync] write failed for {rel}: {e}")
        return updated


# Singleton used by SceneBoot (all modules) and the module shop (downloads).
sprite_sync_service = SpriteSyncService()
