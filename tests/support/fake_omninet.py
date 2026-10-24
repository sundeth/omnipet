# -*- coding: utf-8 -*-
"""A fake Omninet server for the online tests: in memory, on 127.0.0.1.

    with FakeOmninet() as fake:            # a free port, a daemon thread
        acc = fake.add_account("Tester", coins=120)
        code = fake.pairing_code(acc)      # what the Module Editor shows
        ...                                # point the game at fake.url

It answers the endpoints the game's client calls, with the request and
response shapes of the real server (E:/Omninet/omninet/routes/*.py and
schemas/*.py): auth (register, login, codes, pairing, validate-device), the
shop (listings, sprites, purchases, downloads, module zips), rewards, seasons,
teams and battles. Arena teams are validated and battles fought with the
game's own arena engine (src/battle/arena/engine.py), which is the engine the
real server runs, over a catalog of the named local modules.

Faults are injected per path prefix (`fault()`): HTTP 500/502, malformed or
HTML bodies, a reset connection, a slow answer (before or after the request
took effect). `dead_url()` names a local port nobody listens on.

`isolate_client(env, fake)` points a harness Env's game at the server: the
OMNIPET_OMNINET_URL override, the constants the connect menu reads directly
(OMNINET_LOCAL_URL / OMNINET_MAIN_URL, the known bug BLD-04), the Discord bot
URL, the service's credential file (moved into the test save folder), the
shop image cache, and the sprite sync (switched off: it would write into
assets/). Nothing here ever names a real host.
"""
import base64
import contextlib
import copy
import io
import json
import os
import socket
import struct
import threading
import time
import uuid
import zipfile
import zlib
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))

#: Settings of the real server (omninet/config.py) the client sees.
MODULE_FIXED_PRICE = 50
MAX_DAILY_BATTLES = 10
WIN_SCORE, LOSS_SCORE, DRAW_SCORE = 25, -12, 5
PARTICIPATION_COINS = 1
RANK_REWARDS = (50, 25, 10)
REWARD_COINS = {"unlock": 5, "evolution": 2, "new_pet": 3, "adventure": 10, "area_clear": 1}
#: Every emailed verification code (register, login, resend).
EMAIL_CODE = "135790"


def now_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    """A datetime as the real server (pydantic v2) writes it."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def png_bytes(w=8, h=8, rgba=(40, 160, 220, 255)):
    """A small solid-colour PNG, written without pygame."""
    raw = b"".join(b"\x00" + bytes(rgba) * w for _ in range(h))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


def module_zip(module_dir, wrap=True, include_dirs=()):
    """A shop zip of a real module folder: its top-level files (JSON and
    images) plus any *include_dirs*, optionally under one wrapping folder
    as some publishers ship them. Kept small: sprite folders are left out."""
    name = os.path.basename(os.path.normpath(module_dir))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in sorted(os.listdir(module_dir)):
            path = os.path.join(module_dir, entry)
            if os.path.isfile(path):
                zf.write(path, f"{name}/{entry}" if wrap else entry)
        for sub in include_dirs:
            root = os.path.join(module_dir, sub)
            for dirpath, _dirs, files in os.walk(root):
                for f in files:
                    full = os.path.join(dirpath, f)
                    rel = os.path.relpath(full, module_dir).replace(os.sep, "/")
                    zf.write(full, f"{name}/{rel}" if wrap else rel)
    return buf.getvalue()


class _HTTPError(Exception):
    def __init__(self, status, detail):
        super().__init__(detail)
        self.status, self.detail = status, detail


class _Catalog:
    """The arena engine's Catalog over named module folders only."""

    def __init__(self, modules_root, names):
        from battle.arena import engine
        self._modules = {}
        for name in names:
            data = engine._load_module(os.path.join(modules_root, name))
            if data:
                self._modules[data["name"]] = data

    def names(self):
        return sorted(self._modules)

    def module(self, name):
        return self._modules.get(name)

    def summary(self):
        return [{"name": m["name"], "version": m["version"], "monsters": len(m["monsters"])}
                for m in (self._modules[n] for n in self.names())]


class FakeOmninet:
    """In-memory Omninet. Thread-safe: one lock around every request."""

    def __init__(self, arena_modules=(), modules_root=None):
        self.lock = threading.RLock()
        self.accounts = {}          # id -> account dict
        self.devices = {}           # secret_key -> {"account", "device_id", "active"}
        self.pairing = {}           # code -> account id
        self.pending_codes = {}     # email -> (purpose, code)
        self.purchases = {}         # account id -> [purchase rows]
        self.reward_keys = {}       # account id -> {key: coins}
        self.catalog = {"module": {}, "item": {}, "cosmetic": {}, "gameplay": {}, "special": {}}
        self.module_files = {}      # module id -> zip bytes
        self.special_files = {}     # special id -> {file name: png bytes}
        self.sprites = {}           # (kind, id) -> png bytes
        #: Downloads (cosmetic, item) carry their pictures: not on Omninet
        #: today, which sends the file names with empty data.
        self.download_pictures = False
        self.seasons = []           # season dicts, newest last
        self.teams = {}             # id -> team dict
        self.battles = {}           # id -> battle dict
        self.requests = []          # (method, path, json body or None, headers)
        self._faults = []
        self._seed = 1000
        self._stop = threading.Event()
        self._modules_root = modules_root or os.path.join(os.path.dirname(os.path.dirname(HERE)), "modules")
        self._arena_names = list(arena_modules)
        self._arena_catalog = None
        self.httpd = None
        self.thread = None

    # ------------------------------------------------------------ lifecycle
    def start(self):
        handler = _make_handler(self)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="fake-omninet",
                                       kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    @staticmethod
    def dead_url():
        """A local URL nobody listens on (connection refused)."""
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        return f"http://127.0.0.1:{port}"

    # ------------------------------------------------------------ faults
    def fault(self, prefix="", mode="500", delay=0.0, times=None, method=None):
        """Make requests whose path starts with *prefix* fail.

        mode: "500" JSON error, "502" HTML gateway page, "404", "malformed"
        (200 with broken JSON), "html" (200 with an HTML page), "empty" (200,
        no body), "reset" (connection closed, no answer), "slow" (answer
        after *delay* s), "slow_after" (the request takes effect, then the
        answer comes after *delay* s). *times* limits how often it fires.
        """
        with self.lock:
            self._faults.append({"prefix": prefix, "mode": mode, "delay": delay,
                                 "times": times, "method": method})

    def clear_faults(self):
        with self.lock:
            self._faults = []

    def _take_fault(self, method, path):
        with self.lock:
            for f in self._faults:
                if not path.startswith(f["prefix"]):
                    continue
                if f["method"] and f["method"] != method:
                    continue
                if f["times"] is not None:
                    if f["times"] <= 0:
                        continue
                    f["times"] -= 1
                return dict(f)
        return None

    def reset_log(self):
        with self.lock:
            del self.requests[:]

    def calls(self, prefix="", method=None):
        with self.lock:
            return [r for r in self.requests
                    if r[1].startswith(prefix) and (method is None or r[0] == method)]

    # ------------------------------------------------------------ accounts
    def add_account(self, nickname="Tester", email=None, password="secret1", coins=100,
                    active=True, contribution_points=0):
        with self.lock:
            acc = {"id": str(uuid.uuid4()), "nickname": nickname,
                   "email": email or f"{nickname.lower()}@example.com", "password": password,
                   "is_active": active, "is_verified": active, "coins": int(coins),
                   # Earned on the Digimon Database; a balance apart from the coins
                   "contribution_points": int(contribution_points),
                   "created_at": now_utc(), "updated_at": now_utc(), "last_login_at": None}
            self.accounts[acc["id"]] = acc
            self.purchases[acc["id"]] = []
            self.reward_keys[acc["id"]] = {}
            return acc

    def pairing_code(self, acc, code=None):
        """A one-use 4-character code for *acc* (generate-pairing-code)."""
        with self.lock:
            code = code or "AB%02d" % (len(self.pairing) + 12)
            self.pairing[code.upper()] = acc["id"]
            return code.upper()

    def add_device(self, acc):
        """A device key for *acc*, as a device that already logged in has."""
        with self.lock:
            key = "dk_" + uuid.uuid4().hex
            self.devices[key] = {"account": acc["id"], "device_id": str(uuid.uuid4()), "active": True}
            return key

    def keys_of(self, acc, active=True):
        with self.lock:
            return [k for k, d in self.devices.items()
                    if d["account"] == acc["id"] and (d["active"] or not active)]

    def account(self, acc_or_id):
        key = acc_or_id["id"] if isinstance(acc_or_id, dict) else acc_or_id
        with self.lock:
            return self.accounts[key]

    def _user_response(self, acc):
        return {"id": acc["id"], "nickname": acc["nickname"], "email": acc["email"],
                "type_name": "Standard", "is_active": acc["is_active"],
                "is_verified": acc["is_verified"], "coins": acc["coins"],
                "contribution_points": acc.get("contribution_points", 0),
                "created_at": iso(acc["created_at"]), "updated_at": iso(acc["updated_at"]),
                "last_login_at": iso(acc["last_login_at"])}

    def _new_device(self, acc, clear=False):
        if clear:
            for d in self.devices.values():
                if d["account"] == acc["id"]:
                    d["active"] = False
        key = "dk_" + uuid.uuid4().hex
        device_id = str(uuid.uuid4())
        self.devices[key] = {"account": acc["id"], "device_id": device_id, "active": True}
        acc["last_login_at"] = now_utc()
        return {"secret_key": key, "device_id": device_id}

    def _by_email(self, email):
        for acc in self.accounts.values():
            if acc["email"].lower() == str(email or "").lower():
                return acc
        return None

    def _user(self, headers, required=True):
        key = headers.get("X-Device-Key")
        if not key:
            if required:
                raise _HTTPError(401, "Device key required")
            return None
        dev = self.devices.get(key)
        if not dev or not dev["active"]:
            if required:
                raise _HTTPError(401, "Invalid or expired device key")
            return None
        acc = self.accounts[dev["account"]]
        if not acc["is_active"]:
            raise _HTTPError(403, "Account is not active")
        return acc

    # ------------------------------------------------------------ catalog
    def _add(self, kind, row, sprite=None):
        with self.lock:
            row = dict(row)
            row.setdefault("id", str(uuid.uuid4()))
            row.setdefault("enabled", True)
            self.catalog[kind][row["id"]] = row
            if sprite is not None:
                self.sprites[(kind, row["id"])] = sprite
            return row

    def add_module(self, name, zip_bytes, version="1.0.0", description="", category="Classics",
                   official=True, icon=None, logo=None, owner="Omnipet"):
        row = self._add("module", {"name": name, "version": str(version),
                                   "description": description, "category": category,
                                   "is_official": official, "owner_nickname": owner})
        with self.lock:
            self.module_files[row["id"]] = zip_bytes
            self.sprites[("module_icon", row["id"])] = icon or png_bytes(16, 16)
            self.sprites[("module_logo", row["id"])] = logo or png_bytes(40, 44, (200, 80, 40, 255))
        return row

    def add_item(self, name, price=10, description="", sprite_name="", json_data=None, sprite=None,
                 item_id=None):
        row = {"name": name, "price": price, "description": description,
               "sprite_name": sprite_name, "json_data": json_data or {}}
        if item_id:                         # Omninet's items.json fixes the ids
            row["id"] = item_id
        return self._add("item", row,
                         sprite if sprite is not None else png_bytes(16, 16, (220, 200, 60, 255)))

    def add_cosmetic(self, name, price=20, sprite_name="", day_night=False, high_res=False,
                     sprite=None, cosmetic_type="background"):
        # Omninet's shop sync (services/shop_sync.py) keeps the background's
        # name in json_data and lists the sprite as "bg_<name>".
        bg_name = sprite_name or name.lower().replace(" ", "_")
        if bg_name.startswith("bg_"):
            bg_name = bg_name[3:]
        return self._add("cosmetic", {"name": name, "price": price, "cosmetic_type": cosmetic_type,
                                      "sprite_name": f"bg_{bg_name}", "day_night": day_night,
                                      "high_res": high_res,
                                      "json_data": {"name": bg_name, "day_night": day_night}},
                         sprite if sprite is not None else png_bytes(240, 240, (90, 30, 120, 255)))

    def add_gameplay(self, name, price=30, description="", json_data=None):
        return self._add("gameplay", {"name": name, "price": price, "description": description,
                                      "json_data": json_data or {}})

    def add_special(self, name, price=40, description="", currency="coins", special_type=None,
                    sprite_name=None, pictures=None, json_data=None):
        """A Special (Omninet storage/specials/specials.json). A background
        one gives *pictures*, {file name: png bytes}, as its download sends
        them; its day picture is the preview, and day_night / high_res come
        from the file names as Omninet reads them from disk."""
        pictures = dict(pictures or {})
        base = sprite_name or ""
        day_night = f"{base}_day.png" in pictures and f"{base}_night.png" in pictures
        high_res = any(f.endswith("_high.png") for f in pictures)
        preview = (pictures.get(f"{base}_day.png") or pictures.get(f"{base}.png")
                   or next(iter(pictures.values()), None))
        row = self._add("special", {"name": name, "price": price, "description": description,
                                    "currency": currency, "special_type": special_type,
                                    "sprite_name": sprite_name, "day_night": day_night,
                                    "high_res": high_res, "json_data": json_data or {},
                                    "start_date": None, "end_date": None}, preview)
        with self.lock:
            self.special_files[row["id"]] = pictures
        return row

    def credit_points(self, acc, points):
        """Contribution points the Digimon Database credited to *acc*."""
        with self.lock:
            acc = self.accounts[acc["id"] if isinstance(acc, dict) else acc]
            acc["contribution_points"] = acc.get("contribution_points", 0) + int(points)
            return acc["contribution_points"]

    def owned(self, acc, kind=None):
        with self.lock:
            return [p for p in self.purchases[acc["id"]] if kind is None or p["purchase_type"] == kind]

    def _owns(self, acc, item_id, kind):
        return any(p["item_id"] == item_id and p["purchase_type"] == kind
                   for p in self.purchases[acc["id"]])

    def _has_module(self, acc):
        return any(p["purchase_type"] == "module" for p in self.purchases[acc["id"]])

    # ------------------------------------------------------------ arena
    @property
    def arena_catalog(self):
        if self._arena_catalog is None:
            self._arena_catalog = _Catalog(self._modules_root, self._arena_names)
        return self._arena_catalog

    def current_season(self):
        with self.lock:
            for s in reversed(self.seasons):
                if s["status"] == "active":
                    return s
        return None

    def start_season(self, name="Season 1", days=7, restrictions=None):
        with self.lock:
            start = now_utc() - timedelta(hours=1)
            season = {"id": str(uuid.uuid4()), "name": name, "description": "",
                      "start_date": start.date().isoformat(),
                      "end_date": (start + timedelta(days=days)).date().isoformat(),
                      "starts_at": start, "ends_at": start + timedelta(days=days),
                      "status": "active", "restrictions": restrictions or {},
                      "config": {"attacks_per_day": MAX_DAILY_BATTLES, "charge": "random",
                                 "win_score": WIN_SCORE, "loss_score": LOSS_SCORE,
                                 "draw_score": DRAW_SCORE,
                                 "participation_coins": PARTICIPATION_COINS},
                      "runtime_version": "fake-1", "reward_multiplier": 1.0,
                      "theme_name": None, "banner_url": None, "created_at": start}
            self.seasons.append(season)
            return season

    def end_season(self, season=None):
        """Close a season the way the real server does: rank every team, pay
        the best three that fought 50/25/10 coins, once."""
        with self.lock:
            season = season or self.current_season()
            season["status"] = "completed"
            season["ends_at"] = min(season["ends_at"], now_utc())
            ranked = sorted((t for t in self.teams.values() if t["season_id"] == season["id"]),
                            key=lambda t: (-t["score"], t["created_at"]))
            paid = 0
            for rank, team in enumerate(ranked, 1):
                team["final_rank"] = rank
                fought = team["wins"] + team["losses"] + team["draws"]
                if fought and paid < len(RANK_REWARDS):
                    team["rewarded_coins"] += RANK_REWARDS[paid]
                    paid += 1
            return season

    def _season_of(self, team):
        return next((s for s in self.seasons if s["id"] == team["season_id"]), None)

    def _create_team(self, acc, pets_data, name=None):
        from battle.arena import engine
        season = self.current_season()
        if not season:
            raise _HTTPError(400, "No arena season is running")
        if any(t["owner"] == acc["id"] and t["season_id"] == season["id"] and t["is_active"]
               for t in self.teams.values()):
            raise _HTTPError(400, "Maximum of 1 team(s) per season")
        if not isinstance(pets_data, list) or len(pets_data) != engine.TEAM_SIZE:
            raise _HTTPError(400, f"A team must have exactly {engine.TEAM_SIZE} Digimon")
        try:
            entries, errors = engine.validate_team(self.arena_catalog, pets_data,
                                                   season.get("restrictions"))
        except engine.ArenaError as exc:
            raise _HTTPError(400, str(exc))
        if errors:
            raise _HTTPError(400, errors[0]["message"])
        team = {"id": str(uuid.uuid4()), "owner": acc["id"], "season_id": season["id"],
                "name": name or f"{acc['nickname']}'s team", "entries": entries,
                "uploads": copy.deepcopy(pets_data), "score": 0, "wins": 0, "losses": 0,
                "draws": 0, "rewarded_coins": 0, "reward_claimed": False, "is_active": True,
                "final_rank": None, "created_at": now_utc(), "attacks_today": 0}
        self.teams[team["id"]] = team
        return team

    def add_opponent_team(self, nickname="Rival", seed=7, modules=None):
        """Another player with a team in the running season (a dev bot)."""
        from battle.arena import engine
        acc = self.add_account(nickname, coins=0)
        with self.lock:
            uploads = engine.random_team(self.arena_catalog, seed,
                                         restrictions=(self.current_season() or {}).get("restrictions"),
                                         modules=modules)
            return acc, self._create_team(acc, uploads)

    def _rank(self, team):
        same = sorted((t for t in self.teams.values() if t["season_id"] == team["season_id"]),
                      key=lambda t: (-t["score"], t["created_at"]))
        return next(i for i, t in enumerate(same, 1) if t["id"] == team["id"])

    def _pet_rows(self, team):
        rows = []
        for slot, e in enumerate(team["entries"]):
            rows.append({"id": f"{team['id']}-{slot}", "name": e["name"],
                         "module_name": e["module"], "module_version": e["module_version"],
                         "pet_version": e["version"], "stage": e["stage"], "level": e["level"],
                         "atk_main": e["atk_main"], "atk_alt": e["atk_alt"],
                         "atk_alt2": e.get("atk_alt_2", 0), "power": e["power"],
                         "attribute": e["attribute"], "hp": e["hp"], "star": 0,
                         "critical_turn": 0, "extra_data": {"slot": slot},
                         "uid": (team["uploads"][slot] if slot < len(team["uploads"]) else {}).get("uid"),
                         "created_at": iso(team["created_at"])})
        return rows

    def _team_common(self, team):
        season = self._season_of(team)
        return {"id": team["id"], "name": team["name"], "score": team["score"],
                "wins": team["wins"], "losses": team["losses"], "draws": team["draws"],
                "rewarded_coins": team["rewarded_coins"], "reward_claimed": team["reward_claimed"],
                "is_active": team["is_active"], "season_id": team["season_id"],
                "season_name": season["name"] if season else None,
                "season_status": season["status"] if season else None,
                "season_ends_at": iso(season["ends_at"]) if season else None,
                "final_rank": team["final_rank"], "created_at": iso(team["created_at"])}

    def _team_response(self, team):
        out = self._team_common(team)
        out.update({"pets": self._pet_rows(team), "updated_at": out["created_at"],
                    "rank": self._rank(team),
                    "daily_battles_remaining": MAX_DAILY_BATTLES - team["attacks_today"]})
        return out

    def _team_list_row(self, team):
        out = self._team_common(team)
        out.update({"pet_count": len(team["entries"]), "rank": self._rank(team)})
        return out

    @staticmethod
    def _snapshot(team, acc):
        keys = ("module", "module_version", "name", "version", "index", "stage", "attribute",
                "level", "power", "hp", "atk_main", "atk_alt", "atk_alt_2", "traited", "shook")
        return {"team_id": team["id"], "nickname": acc["nickname"] if acc else None,
                "pets": [{k: e.get(k) for k in keys} for e in team["entries"]]}

    def fight(self, attacker, defender):
        """One arena battle, scored as the server scores it."""
        from battle.arena import engine
        with self.lock:
            self._seed += 1
            outcome = engine.run_battle(attacker["entries"], defender["entries"], self._seed,
                                        {"charge": "random"})
            winner = outcome["winner"]
            if winner == "device1":
                result, ch1, ch2 = "team1_win", WIN_SCORE, LOSS_SCORE
            elif winner == "device2":
                result, ch1, ch2 = "team2_win", LOSS_SCORE, WIN_SCORE
            else:
                result, ch1, ch2 = "draw", DRAW_SCORE, DRAW_SCORE
            for team, change, won in ((attacker, ch1, result == "team1_win"),
                                      (defender, ch2, result == "team2_win")):
                team["score"] = max(0, team["score"] + change)
                if result == "draw":
                    team["draws"] += 1
                elif won:
                    team["wins"] += 1
                else:
                    team["losses"] += 1
                team["rewarded_coins"] += PARTICIPATION_COINS
            battle = {"id": str(uuid.uuid4()), "team1_id": attacker["id"],
                      "team2_id": defender["id"], "result": result,
                      "winner_id": (attacker["id"] if result == "team1_win" else
                                    defender["id"] if result == "team2_win" else None),
                      "team1_score_change": ch1, "team2_score_change": ch2,
                      "duration_seconds": 3 * len(outcome["result"].get("battle_log", [])),
                      "fought_at": now_utc(),
                      "battle_log": {"version": 2, "engine_version": outcome.get("engine_version"),
                                     "runtime_version": "fake-1", "seed": self._seed,
                                     "rules": outcome.get("rules"), "charges": outcome.get("charges"),
                                     "attacker": self._snapshot(attacker, self.accounts.get(attacker["owner"])),
                                     "defender": self._snapshot(defender, self.accounts.get(defender["owner"])),
                                     "hp": outcome["hp"], "winner": winner,
                                     "result": outcome["result"]}}
            self.battles[battle["id"]] = battle
            return battle

    @staticmethod
    def _battle_response(b):
        return {k: (iso(v) if k == "fought_at" else v) for k, v in b.items()}

    # ------------------------------------------------------------ dispatch
    def handle(self, method, path, query, headers, body):
        """(status, payload, content_type); payload is a dict/list or bytes."""
        p = path.rstrip("/") or "/"
        parts = p.strip("/").split("/")
        if p == "/health":
            return 200, {"status": "healthy", "version": "fake"}
        if not p.startswith("/api/v1/"):
            raise _HTTPError(404, "Not Found")
        route = parts[2:]
        head = route[0] if route else ""
        fn = getattr(self, f"_r_{head.replace('-', '_')}", None)
        if fn is None:
            raise _HTTPError(404, "Not Found")
        return fn(method, route[1:], query, headers, body)

    # /auth/...
    def _r_auth(self, method, rest, query, headers, body):
        op = rest[0] if rest else ""
        body = body if isinstance(body, dict) else {}
        if method != "POST":
            raise _HTTPError(405, "Method Not Allowed")
        if op == "register":
            nick, email, pw = body.get("nickname", ""), body.get("email", ""), body.get("password", "")
            if len(nick) < 3 or "@" not in email or len(pw) < 6:
                raise _HTTPError(422, [{"loc": ["body", "email"], "msg": "value is not valid"}])
            if self._by_email(email):
                raise _HTTPError(400, "Email is already registered")
            if any(a["nickname"].lower() == nick.lower() for a in self.accounts.values()):
                raise _HTTPError(400, "Nickname is already taken")
            acc = self.add_account(nick, email=email, password=pw, coins=0, active=False)
            self.pending_codes[acc["email"].lower()] = ("register", EMAIL_CODE)
            return 200, {"message": "Verification code sent to your email"}
        if op in ("verify-registration", "verify-login"):
            acc = self._by_email(body.get("email"))
            purpose = "register" if op == "verify-registration" else "login"
            pending = self.pending_codes.get(str(body.get("email", "")).lower())
            if not pending or pending[0] != purpose or pending[1] != body.get("code"):
                raise _HTTPError(400, "Invalid or expired verification code")
            if acc is None:
                raise _HTTPError(400, "User not found")
            del self.pending_codes[acc["email"].lower()]
            if purpose == "register":
                acc["is_active"] = acc["is_verified"] = True
            dev = self._new_device(acc, clear=bool(body.get("clear_devices")))
            dev["message"] = "Account verified" if purpose == "register" else "Login verified"
            return 200, dev
        if op == "login":
            acc = self._by_email(body.get("email"))
            if acc is None or acc["password"] != body.get("password"):
                raise _HTTPError(401, "Invalid email or password")
            if not acc["is_active"]:
                raise _HTTPError(401, "Account is not active")
            self.pending_codes[acc["email"].lower()] = ("login", EMAIL_CODE)
            return 200, {"message": "Verification code sent to your email"}
        if op == "resend-code":
            email = (query.get("email") or [""])[0]
            acc = self._by_email(email)
            if acc is None:
                raise _HTTPError(400, "Email not found")
            purpose = "login" if acc["is_active"] else "register"
            self.pending_codes[acc["email"].lower()] = (purpose, EMAIL_CODE)
            return 200, {"message": "Verification code resent"}
        if op == "validate-pairing-code":
            code = str(body.get("code", "")).upper()
            if len(code) != 4:
                raise _HTTPError(422, [{"loc": ["body", "code"], "msg": "length must be 4"}])
            acc_id = self.pairing.pop(code, None)
            if acc_id is None:
                raise _HTTPError(400, "Invalid or expired pairing code")
            dev = self._new_device(self.accounts[acc_id])
            dev["message"] = "Device linked successfully"
            return 200, dev
        if op == "validate-device":
            return 200, self._user_response(self._user(headers))
        # The real server has no /auth/logout route (routes/auth.py).
        raise _HTTPError(404, "Not Found")

    # /shop/...
    # /users/me/devices/{id}: revoking a device's key (routes/users.py)
    def _r_users(self, method, rest, query, headers, body):
        if rest[:2] == ["me", "devices"] and len(rest) == 3 and method == "DELETE":
            user = self._user(headers)
            for key, dev in list(self.devices.items()):
                if dev["device_id"] == rest[2] and dev["account"] == user["id"]:
                    del self.devices[key]
                    return 200, {"message": "Device deleted successfully"}
            raise _HTTPError(404, "Device not found")
        raise _HTTPError(404, "Not Found")

    def _r_shop(self, method, rest, query, headers, body):
        op = rest[0] if rest else ""
        if method == "GET" and op in ("modules", "items", "cosmetics", "gameplay", "specials") and len(rest) == 1:
            kind = {"modules": "module", "items": "item", "cosmetics": "cosmetic",
                    "gameplay": "gameplay", "specials": "special"}[op]
            rows = [r for r in self.catalog[kind].values() if r.get("enabled", True)]
            if kind == "module":
                user = self._user(headers, required=False)
                price = 0 if user is not None and not self._has_module(user) else MODULE_FIXED_PRICE
                cat = (query.get("category") or [None])[0]
                out = [{"id": r["id"], "name": r["name"], "version": r["version"],
                        "description": r["description"], "category": r["category"], "price": price,
                        "owner_nickname": r["owner_nickname"], "is_official": r["is_official"]}
                       for r in rows if not cat or r["category"] == cat]
            elif kind == "item":
                out = [{k: r[k] for k in ("id", "name", "description", "price", "sprite_name")}
                       for r in rows]
            elif kind == "cosmetic":
                out = [{k: r[k] for k in ("id", "name", "cosmetic_type", "price", "sprite_name",
                                          "day_night", "high_res")} for r in rows]
            elif kind == "gameplay":
                out = [{k: r[k] for k in ("id", "name", "description", "price")} for r in rows]
            else:
                out = [{k: r.get(k) for k in ("id", "name", "description", "price", "currency",
                                              "special_type", "sprite_name", "day_night",
                                              "high_res", "json_data", "start_date",
                                              "end_date")} for r in rows]
            return 200, {op: out, "total": len(out)}
        if method == "GET" and len(rest) == 3 and rest[2] == "sprite":
            data = self.sprites.get((rest[0], rest[1]))
            if data is None:
                raise _HTTPError(404, "Sprite not found")
            return 200, data, "image/png"
        if op == "purchase" and method == "POST":
            if not headers.get("X-Device-Key"):
                raise _HTTPError(422, [{"loc": ["header", "x-device-key"], "msg": "Field required"}])
            user = self._user(headers)
            body = body if isinstance(body, dict) else {}
            kind, item_id = body.get("purchase_type"), str(body.get("item_id", ""))
            if kind not in self.catalog:
                raise _HTTPError(400, f"Invalid purchase type: {kind}")
            row = self.catalog[kind].get(item_id)
            fail = lambda msg: (200, {"success": False, "message": msg, "purchase_id": None,
                                      "coins_remaining": None})
            if row is None or not row.get("enabled", True):
                return fail(f"{kind.capitalize()} not found or not available")
            price = row.get("price", 0)
            if kind == "module":
                price = MODULE_FIXED_PRICE if self._has_module(user) else 0
            # Items are consumables bought again and again; the rest are
            # unlocks, bought once (Omninet services/shop.py, 2026-10-17).
            if kind != "item" and self._owns(user, item_id, kind):
                return fail(f"You already own {row['name']}")
            # A Special may be priced in contribution points: paid from them,
            # never from the coins (Omninet services/shop.py purchase_item).
            currency = (row.get("currency") or "coins") if kind == "special" else "coins"
            if currency == "contribution_points":
                have = user.get("contribution_points", 0)
                if have < price:
                    return fail(f"Not enough contribution points. Need {price}, have {have}")
                user["contribution_points"] = have - price
            else:
                if user["coins"] < price:
                    return fail(f"Not enough coins. Need {price}, have {user['coins']}")
                user["coins"] -= price
            purchase = {"id": str(uuid.uuid4()), "item_id": item_id, "purchase_type": kind,
                        "price_paid": price, "currency": currency,
                        "purchased_at": iso(now_utc())}
            self.purchases[user["id"]].append(purchase)
            return 200, {"success": True, "message": f"Successfully purchased {row['name']}",
                         "purchase_id": purchase["id"], "coins_remaining": user["coins"],
                         "currency": currency,
                         "contribution_points_remaining": (user.get("contribution_points", 0)
                                                           if currency == "contribution_points"
                                                           else None)}
        if op == "purchases" and method == "GET":
            user = self._user(headers)
            rows = list(reversed(self.purchases[user["id"]]))
            return 200, {"purchases": rows, "total": len(rows)}
        if op == "download" and method == "GET" and len(rest) == 3:
            user = self._user(headers)
            kind, item_id = rest[1], rest[2]
            row = self.catalog.get(kind, {}).get(item_id)
            if row is None or not self._owns(user, item_id, kind):
                raise _HTTPError(404, f"{kind.capitalize()} not found or not owned")
            if kind == "module":
                return 200, {"id": row["id"], "name": row["name"], "version": row["version"],
                             "file_data": base64.b64encode(self.module_files[item_id]).decode()}
            out = {"id": row["id"], "name": row["name"], "json_data": row.get("json_data")}
            # Omninet names the files of a cosmetic or item download but
            # leaves their pictures empty (services/shop.py, "TODO: Load
            # actual sprite files"); download_pictures=True is a server
            # that sends them.
            def picture(kind_):
                if not self.download_pictures:
                    return ""
                return base64.b64encode(self.sprites.get((kind_, item_id), b"")).decode()
            if kind == "cosmetic":
                out["cosmetic_type"] = row["cosmetic_type"]
                jd = row.get("json_data") or {}
                files = [f"bg_{jd.get('name', row['sprite_name'])}.png"]
                if jd.get("day_night"):
                    files.append(f"bg_{jd.get('name', row['sprite_name'])}_night.png")
                out["sprites"] = {f: picture("cosmetic") for f in files}
            elif kind == "item":
                out["sprites"] = ({f"{row['sprite_name']}.png": picture("item")}
                                  if row.get("sprite_name") else {})
            elif kind == "special":
                # Omninet's download_special: every picture the background has
                out.update({k: row.get(k) for k in ("special_type", "currency", "sprite_name",
                                                    "day_night", "high_res")})
                out["sprites"] = {f: base64.b64encode(data).decode()
                                  for f, data in self.special_files.get(item_id, {}).items()}
            return 200, out
        if op == "claim-free-module" and method == "POST":
            self._user(headers)
            return 200, {"eligible": False, "granted": False, "message": "Not eligible"}
        raise _HTTPError(404, "Not Found")

    # /modules/{id}/download|icon|logo
    def _r_modules(self, method, rest, query, headers, body):
        if method != "GET" or len(rest) != 2:
            raise _HTTPError(404, "Not Found")
        module_id, what = rest
        if what == "download":
            data = self.module_files.get(module_id)
            if data is None:
                raise _HTTPError(404, "Module file not found")
            return 200, data, "application/zip"
        if what in ("icon", "logo"):
            data = self.sprites.get((f"module_{what}", module_id))
            if data is None:
                raise _HTTPError(404, f"Module {what} not found")
            return 200, data, "image/png"
        raise _HTTPError(404, "Not Found")

    # /rewards/claim
    def _r_rewards(self, method, rest, query, headers, body):
        if method != "POST" or rest != ["claim"]:
            raise _HTTPError(404, "Not Found")
        user = self._user(headers)
        body = body if isinstance(body, dict) else {}
        kind, key = body.get("event_type"), body.get("idempotency_key")
        if kind not in REWARD_COINS:
            raise _HTTPError(400, "Unknown event type")
        if not key or len(key) > 256:
            raise _HTTPError(400, "Invalid idempotency key")
        if key in self.reward_keys[user["id"]]:
            raise _HTTPError(400, "Already claimed")
        coins = REWARD_COINS[kind]
        self.reward_keys[user["id"]][key] = coins
        user["coins"] += coins
        return 200, {"success": True, "coins_awarded": coins, "total_coins": user["coins"],
                     "message": f"+{coins} coins"}

    # /seasons/current
    def _r_seasons(self, method, rest, query, headers, body):
        if method == "GET" and rest == ["current"]:
            season = self.current_season()
            if season is None:
                raise _HTTPError(404, "No arena season is running")
            out = {k: (iso(v) if isinstance(v, datetime) else v) for k, v in season.items()}
            return 200, out
        raise _HTTPError(404, "Not Found")

    # /arena/modules
    def _r_arena(self, method, rest, query, headers, body):
        if method == "GET" and rest == ["modules"]:
            return 200, {"runtime_version": "fake-1", "modules": self.arena_catalog.summary()}
        raise _HTTPError(404, "Not Found")

    # /teams...
    def _r_teams(self, method, rest, query, headers, body):
        user = self._user(headers)
        if not rest and method == "GET":
            include_past = (query.get("include_past") or ["false"])[0] == "true"
            season = self.current_season()
            rows = []
            for t in self.teams.values():
                if t["owner"] != user["id"]:
                    continue
                current = season is not None and t["season_id"] == season["id"]
                unclaimed = not t["reward_claimed"]
                if current or include_past or unclaimed:
                    rows.append(self._team_list_row(t))
            return 200, rows
        if not rest and method == "POST":
            body = body if isinstance(body, dict) else {}
            team = self._create_team(user, body.get("pets"), body.get("name"))
            return 200, self._team_response(team)
        if rest == ["current"] and method == "GET":
            season = self.current_season()
            team = next((t for t in self.teams.values() if season and t["owner"] == user["id"]
                         and t["season_id"] == season["id"] and t["is_active"]), None)
            if team is None:
                raise _HTTPError(404, "No active team for current season")
            return 200, self._team_response(team)
        if rest == ["claim-rewards"] and method == "POST":
            claimed, processed = 0, 0
            for t in self.teams.values():
                season = self._season_of(t)
                if (t["owner"] == user["id"] and not t["reward_claimed"]
                        and season and season["status"] == "completed"):
                    claimed += t["rewarded_coins"]
                    t["reward_claimed"] = True
                    processed += 1
            user["coins"] += claimed
            msg = (f"Claimed {claimed} coins from {processed} team(s)" if processed
                   else "No rewards to claim")
            return 200, {"coins_claimed": claimed, "new_balance": user["coins"],
                         "teams_processed": processed, "message": msg}
        if len(rest) == 1 and method == "GET":
            # routes/teams.py get_team: 404 unknown, 403 another player's
            team = self.teams.get(rest[0])
            if team is None:
                raise _HTTPError(404, "Team not found")
            if team["owner"] != user["id"]:
                raise _HTTPError(403, "You don't own this team")
            return 200, self._team_response(team)
        if len(rest) == 1 and method == "DELETE":
            team = self.teams.get(rest[0])
            if team is None or team["owner"] != user["id"]:
                raise _HTTPError(400, "Team not found")
            team["is_active"] = False
            return 200, {"message": "Team deactivated"}
        raise _HTTPError(404, "Not Found")

    # /battles...
    def _r_battles(self, method, rest, query, headers, body):
        user = self._user(headers)
        if method == "POST" and len(rest) == 2 and rest[0] == "find":
            team = self.teams.get(rest[1])
            if team is None or team["owner"] != user["id"]:
                return 200, {"battle_found": False, "message": "Team not found", "battle": None,
                             "daily_battles_remaining": 0}
            remaining = MAX_DAILY_BATTLES - team["attacks_today"]
            if remaining <= 0:
                return 200, {"battle_found": False, "message": "No battles left today",
                             "battle": None, "daily_battles_remaining": 0}
            rivals = [t for t in self.teams.values() if t["season_id"] == team["season_id"]
                      and t["owner"] != user["id"] and t["is_active"]]
            if not rivals:
                return 200, {"battle_found": False, "message": "No opponent found",
                             "battle": None, "daily_battles_remaining": remaining}
            team["attacks_today"] += 1
            battle = self.fight(team, rivals[0])
            return 200, {"battle_found": True, "message": "Battle completed",
                         "battle": self._battle_response(battle),
                         "daily_battles_remaining": remaining - 1}
        if method == "GET" and len(rest) == 3 and rest[0] == "team" and rest[2] == "history":
            team = self.teams.get(rest[1])
            if team is None:
                raise _HTTPError(404, "Team not found")
            if team["owner"] != user["id"]:
                raise _HTTPError(403, "You don't own this team")
            rows = []
            for b in sorted(self.battles.values(), key=lambda b: b["fought_at"], reverse=True):
                if team["id"] not in (b["team1_id"], b["team2_id"]):
                    continue
                is1 = b["team1_id"] == team["id"]
                other = self.teams[b["team2_id"] if is1 else b["team1_id"]]
                rows.append({"id": b["id"], "opponent_team_id": other["id"],
                             "opponent_nickname": self.accounts[other["owner"]]["nickname"],
                             "role": "attack" if is1 else "defense",
                             "won": (b["result"] == "team1_win") == is1 and b["result"] != "draw",
                             "is_draw": b["result"] == "draw",
                             "score_change": b["team1_score_change"] if is1 else b["team2_score_change"],
                             "fought_at": iso(b["fought_at"])})
            return 200, {"team_id": team["id"], "team_name": team["name"], "battles": rows,
                         "total_battles": len(rows)}
        if method == "GET" and len(rest) == 1:
            b = self.battles.get(rest[0])
            if b is None:
                raise _HTTPError(404, "Battle not found")
            owners = {self.teams[b["team1_id"]]["owner"], self.teams[b["team2_id"]]["owner"]}
            if user["id"] not in owners:
                raise _HTTPError(403, "You don't own either team in this battle")
            return 200, self._battle_response(b)
        raise _HTTPError(404, "Not Found")


def _make_handler(server):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, *a):          # quiet
            pass

        def _send(self, status, payload, content_type="application/json"):
            if isinstance(payload, (bytes, bytearray)):
                data = bytes(payload)
            else:
                data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if data:
                self.wfile.write(data)

        def _serve(self, method):
            parts = urlsplit(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                body = json.loads(raw) if raw else None
            except ValueError:
                body = None
            headers = {k: v for k, v in self.headers.items()}
            # header names: keep the client's case, and a canonical copy
            for k in list(headers):
                if k.lower() == "x-device-key":
                    headers["X-Device-Key"] = headers[k]
            with server.lock:
                server.requests.append((method, parts.path, body, headers))
            fault = server._take_fault(method, parts.path)
            if fault:
                mode = fault["mode"]
                if mode == "slow":
                    server._stop.wait(fault["delay"])
                elif mode == "reset":
                    try:
                        self.connection.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    self.close_connection = True
                    return
                elif mode == "500":
                    return self._send(500, {"detail": "Internal Server Error"})
                elif mode == "502":
                    return self._send(502, b"<html><body><h1>502 Bad Gateway</h1></body></html>",
                                      "text/html")
                elif mode == "404":
                    return self._send(404, {"detail": "Not Found"})
                elif mode == "malformed":
                    return self._send(200, b'{"detail": "half a respon', "application/json")
                elif mode == "html":
                    return self._send(200, b"<html><body>Sign in to the Wi-Fi</body></html>",
                                      "text/html")
                elif mode == "empty":
                    return self._send(200, b"", "application/json")
            try:
                with server.lock:
                    out = server.handle(method, parts.path, parse_qs(parts.query), headers, body)
            except _HTTPError as exc:
                out = (exc.status, {"detail": exc.detail})
            except Exception as exc:  # a bug in the fake: answer like FastAPI would
                out = (500, {"detail": f"fake server error: {exc!r}"})
            if fault and fault["mode"] == "slow_after":
                server._stop.wait(fault["delay"])
            try:
                self._send(*out)
            except OSError:
                pass

        def do_GET(self):
            self._serve("GET")

        def do_POST(self):
            self._serve("POST")

        def do_DELETE(self):
            self._serve("DELETE")
    return Handler


# ---------------------------------------------------------------------- client side
@contextlib.contextmanager
def isolate_client(env, fake_or_url, timeout=None):
    """Point the headless game in *env* at a fake server for the duration.

    *fake_or_url* is a FakeOmninet or a URL (e.g. `FakeOmninet.dead_url()`).
    The service singleton is logged out on entry and exit, its credentials
    file lives in the test's save folder, and every URL the game reads
    resolves to the fake. *timeout* shortens the service's request timeout.
    """
    url = fake_or_url.url if isinstance(fake_or_url, FakeOmninet) else str(fake_or_url)
    save_root = env if isinstance(env, str) else env.save_root
    from core import constants
    from services.omninet_service import omninet_service as svc
    from services.shop_image_cache import shop_image_cache
    from services.sprite_sync_service import sprite_sync_service
    saved = {
        "env": os.environ.get("OMNIPET_OMNINET_URL"),
        "local": getattr(constants, "OMNINET_LOCAL_URL", None),
        "main": getattr(constants, "OMNINET_MAIN_URL", None),
        "discord": getattr(constants, "DISCORD_BOT_URL", None),
        "has_discord": hasattr(constants, "DISCORD_BOT_URL"),
        "cred": svc._credentials_path,
        "timeout": svc._timeout,
        "sync": sprite_sync_service.__dict__.get("is_available"),
    }
    # Downloaded modules (shop install, owned-module sync) land in a temp
    # folder; load_modules() then reads that folder. Env.reset() puts the
    # real module registry back.
    import sys as _sys
    from utils import module_utils
    shop_view = _sys.modules.get("scenes.connect_views.shop_modules_view")
    from paths import temp_dir
    modules_tmp = temp_dir("modules_")
    saved["modules_dir"] = (module_utils.get_modules_dir,
                            getattr(shop_view, "get_modules_dir", None))
    module_utils.get_modules_dir = lambda: modules_tmp
    if shop_view is not None:
        shop_view.get_modules_dir = lambda: modules_tmp
    os.environ["OMNIPET_OMNINET_URL"] = url
    constants.OMNINET_LOCAL_URL = url + "/"
    constants.OMNINET_MAIN_URL = url
    constants.DISCORD_BOT_URL = url + "/discord"
    svc._credentials_path = os.path.join(save_root, "omninet_device.json")
    if timeout is not None:
        svc._timeout = timeout
    reset_service(svc)
    shop_image_cache.clear()
    sprite_sync_service.is_available = lambda *a, **k: False
    try:
        yield svc
    finally:
        reset_service(svc)
        module_utils.get_modules_dir = saved["modules_dir"][0]
        if shop_view is not None and saved["modules_dir"][1] is not None:
            shop_view.get_modules_dir = saved["modules_dir"][1]
        svc._credentials_path = saved["cred"]
        svc._timeout = saved["timeout"]
        if saved["env"] is None:
            os.environ.pop("OMNIPET_OMNINET_URL", None)
        else:
            os.environ["OMNIPET_OMNINET_URL"] = saved["env"]
        constants.OMNINET_LOCAL_URL = saved["local"]
        constants.OMNINET_MAIN_URL = saved["main"]
        if saved["has_discord"]:
            constants.DISCORD_BOT_URL = saved["discord"]
        else:
            with contextlib.suppress(AttributeError):
                delattr(constants, "DISCORD_BOT_URL")
        if saved["sync"] is None:
            sprite_sync_service.__dict__.pop("is_available", None)
        else:
            sprite_sync_service.is_available = saved["sync"]
        shop_image_cache.clear()


def modules_dir():
    """The folder isolate_client() sends module installs to."""
    from utils import module_utils
    return module_utils.get_modules_dir()


@contextlib.contextmanager
def redirect_relative_save(target):
    """Rewrite writes to the cwd-relative ``save/...`` (the repository's own
    save folder while the harness runs) into *target*, and record them.

    For game code that builds paths from a literal "save" instead of the
    player's save folder (the cosmetics download). Yields the list of
    (original, redirected) paths written."""
    import builtins
    written = []
    real_open, real_makedirs = builtins.open, os.makedirs

    def mapped(path):
        if isinstance(path, (str, os.PathLike)):
            p = os.fspath(path)
            if not os.path.isabs(p):
                norm = os.path.normpath(p)
                head = norm.split(os.sep, 1)
                if head[0] == "save":
                    new = os.path.join(target, *(head[1:] or []))
                    return p, new
        return None

    def _open(file, mode="r", *a, **k):
        m = mapped(file)
        if m:
            if any(c in mode for c in "wax+"):
                written.append(m)
            file = m[1]
        return real_open(file, mode, *a, **k)

    def _makedirs(name, *a, **k):
        m = mapped(name)
        return real_makedirs(m[1] if m else name, *a, **k)

    builtins.open, os.makedirs = _open, _makedirs
    try:
        yield written
    finally:
        builtins.open, os.makedirs = real_open, real_makedirs


@contextlib.contextmanager
def isolate_saves(save_root):
    """Without a harness Env: every save the game writes goes to *save_root*
    (a paths.temp_dir()), never to the repository's save/ folder."""
    from core import game_globals as gg
    saved = (gg._get_base_save_dir, gg._can_access_save_dir, gg.game_mode, gg.player_id, gg.coins,
             gg.android_offline)
    gg._get_base_save_dir = lambda: save_root
    gg._can_access_save_dir = lambda: True
    try:
        yield gg
    finally:
        (gg._get_base_save_dir, gg._can_access_save_dir, gg.game_mode, gg.player_id,
         gg.coins, gg.android_offline) = saved


def reset_service(svc):
    """Forget the service's login in memory (the credentials file is the
    test's own; it is removed too)."""
    svc._device_key = svc._device_id = svc._player_id = None
    svc._user_info = None
    with contextlib.suppress(OSError):
        if svc._credentials_path and os.path.exists(svc._credentials_path) \
                and os.path.dirname(os.path.abspath(svc._credentials_path)).startswith(
                    os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(HERE)), "tmp"))):
            os.remove(svc._credentials_path)


def login_service(svc, fake, acc):
    """Log the service in as *acc* through a pairing code (the real calls)."""
    ok, msg, info = svc.validate_pairing_code(fake.pairing_code(acc))
    if not ok:
        raise AssertionError(f"login failed: {msg}")
    return info


def wait_for(cond, timeout=10.0, step=0.01):
    """Poll *cond* until true (bounded wall-clock wait for a worker thread)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(step)
    return bool(cond())
