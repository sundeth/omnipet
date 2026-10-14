#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Letter-case check: every file name the game builds, against the disk.

Windows (and WSL's view of the exFAT E: drive) opens a file whatever the
letter case of the name; the Pi, Batocera and Android do not. This lists every
name that only matches in ANOTHER letter case, so it works on any machine and
any file system (it compares exact names from directory listings).

    python -B tests/platform/linux/case_check.py [--root DIR] [--module NAME ...]
           [--json PATH] [--misses CASE_LOG.jsonl [--only-misses]] [--runtime]

Static checks (checklist UI-08, MOD-02):
  modules   for every modules/<NAME>/ with a module.json:
            - the fixed files the game opens (monster.json, Flag.png, logo.png,
              BattleIcon.png, ...) and its sprite/art folders;
            - every monster and enemy sprite set, looked up as the game does
              (tests/support/sprites.py order: module folder, module zip,
              shared folder, shared zip; Color, Dot and HD), reporting where
              Windows and Linux would end up drawing different sets;
            - every background (bg_<name>[_day|_dusk|_night][_high].png),
              device sprite and legacy egg device art;
            - every file name a module JSON value names (item, card, icon,
              pack art ...), searched in the module's art folders.
  code      every "assets/..." path in src/ and main*.py: string literals,
            os.path.join("assets", ...) calls and the static prefix of
            f-strings (the folders before the first {...}).
Runtime:
  --misses  summarise a strict-case log written by strictcase/ during a test
            run (run_suite.sh --mode strict): paths the code really asked for.
  --runtime boot the headless game (tests/support/harness.py) with strict
            letter case and enter every scene of tests/release/scene_sweep.py
            for a few frames; summarise what it asked for in the wrong case.

Exit 1 when any case-only match is found.
"""
import argparse
import ast
import collections
import glob
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(TESTS, "support"))
import paths  # noqa: E402
import sprites  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

#: Files a module folder may hold that the game opens by a fixed name.
FIXED_FILES = ["module.json", "monster.json", "battle.json", "item.json", "devices.json", "codes.json",
               "shop.json", "quests.json", "events.json", "cards.json", "Flag.png", "logo.png", "BattleIcon.png"]
#: Module sub-folders the game opens by a fixed name.
FOLDERS = ["monsters", "monsters_dot", "monsters_hidef", "backgrounds", "items", "atk", "atk_crit",
           "devices", "icons", "cards", "animations"]
#: Folders searched for a file name a module JSON value names.
ART_FOLDERS = ["", "items", "devices", "icons", "cards", "backgrounds", "animations"]
FILE_VALUE = re.compile(r".+\.(png|jpe?g|bmp|gif|wav|ogg|mp3|zip|ttf|otf)$", re.I)


class Tree:
    """Exact-case lookups below a root, with cached directory listings."""

    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.cache = {}

    def names(self, folder):
        if folder not in self.cache:
            try:
                self.cache[folder] = os.listdir(folder)
            except OSError:
                self.cache[folder] = None
        return self.cache[folder]

    def lookup(self, rel):
        """('ok', rel) | ('case', actual rel) | ('missing', None) for a path
        relative to the root ('/' separated)."""
        parts = [p for p in rel.replace("\\", "/").split("/") if p and p != "."]
        cur, actual, case = self.root, [], False
        for part in parts:
            names = self.names(cur)
            if names is None:
                return "missing", None
            if part in names:
                hit = part
            else:
                lower = {n.lower(): n for n in names}
                hit = lower.get(part.lower())
                if hit is None:
                    return "missing", None
                case = True
            actual.append(hit)
            cur = os.path.join(cur, hit)
        return ("case" if case else "ok"), "/".join(actual)


def load_json(path, key=None, default=None):
    try:
        with open(path, encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return default
    if key is None:
        return data
    return data.get(key, default) if isinstance(data, dict) else default


class Report:
    def __init__(self):
        self.rows = []

    def add(self, area, severity, subject, detail, check="UI-08"):
        self.rows.append({"area": area, "check": check, "severity": severity, "subject": subject, "detail": detail})

    def errors(self):
        return [r for r in self.rows if r["severity"] == "error"]


# ---------------------------------------------------------------- modules
def sprite_choice(tree, fmt, module_rel, name):
    """(Linux set, Windows set): the first candidate with frames found by an
    exact name, and by a name in any letter case, in the game's order."""
    folder = sprites.FOLDERS[fmt]
    linux = windows = None
    for base in (f"{module_rel}/{folder}", f"assets/{folder}"):
        for cand, kind in ((name, "dir"), (name + ".zip", "file")):
            rel = f"{base}/{cand}"
            state, actual = tree.lookup(rel)
            if state == "missing":
                continue
            full = os.path.join(tree.root, actual)
            is_kind = os.path.isdir(full) if kind == "dir" else os.path.isfile(full)
            if not is_kind or not sprites.frames_of(full, kind):
                continue
            if windows is None:
                windows = actual
            if state == "ok" and linux is None:
                linux = actual
        if linux and windows:
            break
    return linux, windows


def check_module(tree, rep, name):
    mrel = f"modules/{name}"
    mdir = os.path.join(tree.root, "modules", name)
    meta = load_json(os.path.join(mdir, "module.json"), default={}) or {}
    for f in FIXED_FILES + FOLDERS:
        state, actual = tree.lookup(f"{mrel}/{f}")
        if state == "case":
            rep.add(name, "error", f"{mrel}/{f}", f"only exists as {actual}: the game opens '{f}'")

    # sprite sets
    monsters = load_json(os.path.join(mdir, "monster.json"), "monster", []) or []
    enemies = load_json(os.path.join(mdir, "battle.json"), "enemies", []) or []
    names = list(dict.fromkeys([m.get("name") for m in monsters if m.get("name")] +
                               [e.get("name") for e in enemies if e.get("name")]))
    fmt_str = meta.get("name_format")
    for pet in names:
        sname = sprites.sprite_name(pet, fmt_str)
        for fmt in ("Color", "Dot", "HD"):
            linux, windows = sprite_choice(tree, fmt, mrel, sname)
            if windows and windows != linux:
                if linux is None:
                    rep.add(name, "error", f"{pet} [{fmt}] '{sname}'",
                            f"Windows draws {windows}; Linux finds no set (letter case)", "MOD-02")
                else:
                    rep.add(name, "warn", f"{pet} [{fmt}] '{sname}'",
                            f"Windows draws {windows}; Linux draws {linux} (letter case)", "MOD-02")

    # backgrounds, devices, egg device art
    def need(rel, why, severity="error"):
        state, actual = tree.lookup(rel)
        if state == "case":
            rep.add(name, severity, rel, f"{why}: only exists as {actual}")
        return state
    bgs = meta.get("backgrounds") or []
    for bg in bgs:
        bname = bg.get("name")
        if not bname:
            continue
        slices = ["_day", "_dusk", "_night"] if bg.get("day_night", True) else [""]
        for s in slices:
            for hd in ("", "_high"):
                need(f"{mrel}/backgrounds/bg_{bname}{s}{hd}.png", f"background {bname}")
    devices = load_json(os.path.join(mdir, "devices.json"), "devices", []) or []
    bg_by_name = {b.get("name"): b for b in bgs}
    for d in devices:
        sp = str(d.get("sprite") or "").strip()
        if sp:
            if not sp.lower().endswith(".png"):
                sp += ".png"
            need(f"{mrel}/devices/{sp}", f"device {d.get('name')} sprite")
        b = str(d.get("background") or "").strip()
        if b:
            day_night = (bg_by_name.get(b) or {}).get("day_night")
            need(f"{mrel}/backgrounds/bg_{b}{'_day' if day_night else ''}.png", f"device {d.get('name')} background")
    # scene_eggselection.load_eggs_for_module reads devices/<egg name>.png only
    # when no device was chosen, i.e. for a module without selectable devices
    # (devices.json entries with a background); otherwise the path is dormant.
    selectable = any(str(d.get("background") or "").strip() for d in devices)
    for m in monsters:
        if m.get("stage") == 0 and m.get("name"):
            if selectable:
                need(f"{mrel}/devices/{m['name']}.png",
                     f"egg {m['name']} legacy device art (dormant: the module has selectable devices)", "warn")
            else:
                need(f"{mrel}/devices/{m['name']}.png", f"egg {m['name']} device art")

    # items: sprite_name with or without .png, module items/ then assets/items/
    items = load_json(os.path.join(mdir, "item.json"), "item", []) or []
    for it in items:
        sp = str(it.get("sprite_name") or "").strip()
        if not sp:
            continue
        cands = [sp] if sp.lower().endswith(".png") else [sp, sp + ".png"]
        states = [(rel, tree.lookup(rel)) for c in cands for rel in (f"{mrel}/items/{c}", f"assets/items/{c}")]
        if any(s == "ok" for _, (s, _) in states):
            continue
        hits = [(rel, a) for rel, (s, a) in states if s == "case"]
        if hits:
            rep.add(name, "error", f"item {it.get('name')} sprite '{sp}'", f"only exists as {hits[0][1]}", "MOD-15")

    # any other file name a module JSON value names
    seen = set()
    for jf in sorted(glob.glob(os.path.join(mdir, "*.json"))):
        data = load_json(jf, default=None)
        stack = [data]
        while stack:
            v = stack.pop()
            if isinstance(v, dict):
                stack.extend(v.values())
            elif isinstance(v, list):
                stack.extend(v)
            elif isinstance(v, str) and FILE_VALUE.match(v.strip()) and len(v) < 200:
                val = v.strip().replace("\\", "/")
                if val in seen:
                    continue
                seen.add(val)
                rels = [f"{mrel}/{val}"] if "/" in val else [f"{mrel}/{f}/{val}".replace("//", "/") for f in ART_FOLDERS]
                rels.append(f"assets/{val}")
                states = [tree.lookup(r) for r in rels]
                if any(s == "ok" for s, _ in states):
                    continue
                hits = [a for s, a in states if s == "case"]
                if hits:
                    rep.add(name, "error", f"{os.path.basename(jf)} value '{val}'", f"only exists as {hits[0]}")


# ---------------------------------------------------------------- code
def _const_str(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _docstring_ids(tree):
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and _const_str(body[0].value) is not None:
                ids.add(id(body[0].value))
    for node in ast.walk(tree):          # bare string statements (comments in quotes)
        if isinstance(node, ast.Expr) and _const_str(node.value) is not None:
            ids.add(id(node.value))
    return ids


def _is_join(call):
    f = call.func
    return isinstance(f, ast.Attribute) and f.attr == "join" and (
        (isinstance(f.value, ast.Attribute) and f.value.attr == "path") or
        (isinstance(f.value, ast.Name) and f.value.id in ("path", "osp", "posixpath", "ntpath")))


def code_paths(root):
    """(file, line, path, whole) for every assets path the code names; whole
    is False when only a folder prefix is static."""
    out = []
    files = sorted(glob.glob(os.path.join(root, "src", "**", "*.py"), recursive=True)) + \
        sorted(glob.glob(os.path.join(root, "main*.py")))
    for path in files:
        try:
            with open(path, encoding="utf-8-sig") as fh:
                tree = ast.parse(fh.read(), path)
        except (OSError, SyntaxError, ValueError):
            continue
        rel = os.path.relpath(path, root).replace("\\", "/")
        skip = _docstring_ids(tree)
        in_fstring = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                for v in node.values:
                    in_fstring.add(id(v))
                prefix = ""
                for v in node.values:
                    s = _const_str(v)
                    if s is None:
                        break
                    prefix += s
                prefix = prefix.replace("\\", "/")
                if prefix.startswith("assets/") and "/" in prefix[len("assets/"):]:
                    out.append((rel, node.lineno, prefix.rsplit("/", 1)[0], False))
                elif prefix.startswith("assets/") and len(node.values) == 1:
                    out.append((rel, node.lineno, prefix, True))
            elif isinstance(node, ast.Call) and _is_join(node):
                consts = []
                for a in node.args:
                    s = _const_str(a)
                    if s is None:
                        break
                    consts.append(s)
                if consts and consts[0].replace("\\", "/").strip("/").split("/")[0] == "assets":
                    joined = "/".join(c.replace("\\", "/").strip("/") for c in consts)
                    whole = len(consts) == len(node.args)
                    if whole or "/" in joined:
                        out.append((rel, node.lineno, joined if whole else joined, whole))
        for node in ast.walk(tree):
            s = _const_str(node)
            if s is None or id(node) in skip or id(node) in in_fstring:
                continue
            s = s.replace("\\", "/")
            if not s.startswith("assets/") or "\n" in s or len(s) > 200:
                continue
            for mark in ("{", "%", "*", "$"):
                if mark in s:
                    s = s.split(mark, 1)[0].rsplit("/", 1)[0]
                    out.append((rel, node.lineno, s, False))
                    break
            else:
                out.append((rel, node.lineno, s.rstrip("/"), True))
    return out


def check_code(tree, rep):
    missing = []
    seen = set()
    for rel, line, p, whole in code_paths(tree.root):
        if (p, rel) in seen or p in ("assets", ""):
            continue
        seen.add((p, rel))
        state, actual = tree.lookup(p)
        if state == "case":
            check = "TRN-01" if re.search(r"training|minigame", rel + p) else "UI-08"
            rep.add("code", "error", f"{rel}:{line}", f"'{p}' only exists as '{actual}'", check)
        elif state == "missing" and whole and os.path.splitext(p)[1]:
            missing.append(f"{rel}:{line} {p}")
    return missing


# ---------------------------------------------------------------- runtime logs
def summarise_misses(log_path, root):
    rows = []
    try:
        with open(log_path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    pass
    except OSError:
        return []
    groups = collections.OrderedDict()
    for r in rows:
        key = (r.get("asked"), r.get("found"))
        g = groups.setdefault(key, {"asked": key[0], "found": key[1], "ops": set(), "callers": set(),
                                    "tests": set(), "blocked": False})
        g["ops"].add(r.get("op"))
        if r.get("caller"):
            g["callers"].add(r["caller"])
        if r.get("test"):
            g["tests"].add(r["test"].split(" ")[0])
        g["blocked"] |= bool(r.get("blocked"))
    out = []
    for g in groups.values():
        out.append({"asked": g["asked"], "found": g["found"], "ops": sorted(o for o in g["ops"] if o),
                    "callers": sorted(g["callers"]), "tests": sorted(g["tests"])[:5], "blocked": g["blocked"]})
    return out


def runtime_child(log_path, frames):
    """Boot the headless game with strict letter case, enter every scene."""
    sys.path.insert(0, os.path.join(HERE, "strictcase"))
    import strict_case
    strict_case.install(paths.ROOT, log_path)
    sys.path.insert(0, os.path.join(TESTS, "release"))
    from harness import Env
    from scene_sweep import SCENES
    env = Env("240x240")
    failed = []
    for name in SCENES:
        env.reset()
        try:
            game = env.game(name)
            env.frames(game, frames)
            for action in ("DOWN", "A", "B"):
                with __import__("harness").quiet():
                    game.scene.handle_event((action, None))
                env.frames(game, 2)
        except Exception as exc:
            failed.append(f"{name}: {type(exc).__name__}: {exc}")
    print(json.dumps({"scenes": len(SCENES), "failed": failed}))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=paths.ROOT)
    ap.add_argument("--module", nargs="*")
    ap.add_argument("--json")
    ap.add_argument("--misses", help="strict-case log (JSON lines) to summarise")
    ap.add_argument("--only-misses", action="store_true", help="with --misses: skip the static checks")
    ap.add_argument("--runtime", action="store_true", help="also boot the game and enter every scene")
    ap.add_argument("--runtime-child", help=argparse.SUPPRESS)
    ap.add_argument("--frames", type=int, default=10)
    args = ap.parse_args()
    if args.runtime_child:
        runtime_child(args.runtime_child, args.frames)
        return
    root = os.path.abspath(args.root)
    sprites.ASSETS = os.path.join(root, "assets")
    tree = Tree(root)
    rep = Report()
    result = {"root": root}
    bad = 0

    if not args.only_misses:
        mods_dir = os.path.join(root, "modules")
        names = args.module or sorted(n for n in (os.listdir(mods_dir) if os.path.isdir(mods_dir) else [])
                                      if os.path.isfile(os.path.join(mods_dir, n, "module.json")))
        for n in names:
            check_module(tree, rep, n)
        missing = check_code(tree, rep)
        result.update(modules=names, findings=rep.rows, code_missing=missing)
        errors = rep.errors()
        bad += len(errors)
        print(f"[case] {root}: {len(names)} modules, {len(errors)} case-only matches, "
              f"{len(rep.rows) - len(errors)} warnings")
        for r in sorted(rep.rows, key=lambda r: (r["severity"] != "error", r["area"], r["subject"])):
            print(f"  {r['severity']:5} {r['check']:6} {r['area']:8} {r['subject']}: {r['detail']}"[:260])
        if missing:
            print(f"[case] {len(missing)} literal assets/ paths in the code do not exist in any case "
                  f"(not a case problem; build_checks.py reports the live ones):")
            for m in missing[:15]:
                print("        " + m)

    logs = []
    if args.misses:
        logs.append(("test run", args.misses))
    if args.runtime:
        log = os.path.join(root, "tmp", "platform", "linux", "case_runtime.jsonl")
        os.makedirs(os.path.dirname(log), exist_ok=True)
        open(log, "w").close()
        env = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy", PYTHONIOENCODING="utf-8")
        proc = subprocess.run([sys.executable, "-B", os.path.abspath(__file__), "--runtime-child", log,
                               "--frames", str(args.frames)], cwd=root, env=env, capture_output=True,
                              text=True, encoding="utf-8", errors="replace")
        tail = (proc.stdout.strip().splitlines() or [""])[-1]
        print(f"[case] runtime pass (every scene, strict case): exit {proc.returncode} {tail[:300]}")
        if proc.returncode:
            print("\n".join((proc.stdout + proc.stderr).strip().splitlines()[-15:]))
        logs.append(("runtime pass", log))
    for label, log in logs:
        misses = summarise_misses(log, root)
        result.setdefault("runtime_misses", {})[label] = misses
        bad += len(misses)
        print(f"[case] {label}: {len(misses)} paths asked for in a letter case that does not exist ({log})")
        for m in misses:
            who = ", ".join(m["callers"][:3]) or "caller outside src/"
            print(f"  error  asked {m['asked']!r}, disk has {m['found']!r} ({'/'.join(m['ops'])}; {who})"[:300])
            if m["tests"]:
                print(f"         seen in {', '.join(m['tests'][:3])}"[:300])

    if args.json:
        os.makedirs(os.path.dirname(os.path.abspath(args.json)), exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=1)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
