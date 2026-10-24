#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""A module folder holds only what the game loads (checklist MOD-18).

A module is published as its whole folder (the editor zips it), so anything
else in it reaches every player who installs it: research notes, reference or
original art, backups, scratch, editor source files, scripts. Those belong in
utilities/<MODULE>/ (CLAUDE.md, "Workspace and preservation").

Rules, each finding (level, path inside the module, reason):

* top level: the files and folders the game reads (TOP_FILES, TOP_DIRS);
* anywhere: no backup, temporary, OS, editor-source, script, spreadsheet or
  note file, and no folder named like one (backup, tmp, research, originals...);
* monsters, monsters_dot, monsters_hidef: each sprite set (a zip, or a folder)
  is named after a Digimon or enemy of the module through its `name_format`
  and holds only frame images (<n>.png, <n>R.png);
* atk, atk_crit: `<id>.png` / `<id>_dot.png` (the loader keys sprites by file
  stem and is asked for numeric ids);
* backgrounds, items, devices, cards, icons, animations: the file's name is
  mentioned in the module's JSON, after the game's own naming (the bg_
  prefix, day/dusk/night slices and _high, an item's _anim, the _1.._5
  frames of a DigiXros animation, an egg's name for legacy device art), or
  the code asks for it by name (CODE_NAMES). Any mention counts, so a file
  this reports is one nothing names;
* documentation: never (owner, 2026-10-24: "modules should only contain data
  used in game/module editor, no backups, documentation"). The editor's
  generated pages live in utilities/<MODULE>/documentation/
  (utilities/claude/relocate_module_docs.py moves them there).

A background named ver<N> after one of the module's versions that the module
does not declare is a warning, not an error: before 2026-10-14 the first pet's
background was always `ver<version>`, so an old save may still draw it.

    python -B tests/release/module_files.py [MODULE ...] [--all] [--json PATH]
"""
import argparse
import json
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "support"))
from paths import ROOT  # noqa: E402

MODULES = os.path.join(ROOT, "modules")

TOP_FILES = {"module.json", "monster.json", "battle.json", "devices.json", "item.json", "codes.json",
             "shop.json", "quests.json", "events.json", "cards.json", "Flag.png", "logo.png",
             "BattleIcon.png"}
SPRITE_DIRS = {"monsters", "monsters_dot", "monsters_hidef"}
ATTACK_DIRS = {"atk", "atk_crit"}
NAMED_DIRS = {"backgrounds", "items", "devices", "cards", "icons", "animations"}
TOP_DIRS = SPRITE_DIRS | ATTACK_DIRS | NAMED_DIRS

#: Never part of a module (or a build): backups, temporary files, OS files,
#: editor sources, scripts, spreadsheets and notes.
JUNK_EXT = {".bak", ".orig", ".old", ".tmp", ".temp", ".swp", ".swo", ".part", ".crdownload",
            ".py", ".pyc", ".pyo", ".ps1", ".sh", ".bat",
            ".psd", ".ase", ".aseprite", ".xcf", ".kra", ".pdn", ".sai", ".clip",
            ".xls", ".xlsx", ".ods", ".csv", ".log", ".md", ".txt", ".doc", ".docx", ".pdf", ".rtf"}
JUNK_NAMES = {"thumbs.db", "desktop.ini", ".ds_store"}
JUNK_DIRS = {"backup", "backups", "bak", "old", "tmp", "temp", "scratch", "research", "original",
             "originals", "source", "sources", "unused", "wip", "test", "tests", "__pycache__",
             ".git", ".svn", ".vscode", ".idea", "__macosx"}
#: Windows / file-manager duplicates: "name - Copy.png", "name (2).png", "name~".
DUPLICATE = re.compile(r"( - (copy|copia|cópia)( \(\d+\))?| \(\d+\))(\.[^.]+)?$|~$", re.I)
#: Names the code asks a module folder for directly (not named in any JSON).
CODE_NAMES = {
    "icons": {"minigames"},          # specials_utils: the iC's Minigames special
}
FRAME = re.compile(r"\d+R?\.png")
ATTACK = re.compile(r"\d+(_dot)?\.png")
SUFFIXES = re.compile(r"(_high|_day|_dusk|_night|_anim|_dot|_[1-5])$")


def junk_reason(name, is_dir):
    low = name.lower()
    if is_dir:
        return "a backup, temporary or work folder" if low in JUNK_DIRS else None
    if low in JUNK_NAMES or low.startswith(".~lock"):
        return "an operating-system or editor file"
    if DUPLICATE.search(name):
        return "a duplicate left by a copy"
    ext = os.path.splitext(low)[1]
    if ext in JUNK_EXT:
        return f"a {ext} file: backups, sources, scripts and notes stay out of the module"
    return None


def json_strings(module_dir):
    """Every string in the module's top-level JSON files (keys and values)."""
    out = set()

    def walk(v):
        if isinstance(v, str):
            out.add(v)
        elif isinstance(v, dict):
            for k, x in v.items():
                out.add(k)
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    for name in os.listdir(module_dir):
        if name.lower().endswith(".json"):
            try:
                with open(os.path.join(module_dir, name), encoding="utf-8-sig") as fh:
                    walk(json.load(fh))
            except (OSError, ValueError):
                pass
    # a JSON value may be a path, a file name or a bare name
    for s in list(out):
        base = os.path.basename(s.replace("\\", "/"))
        out.add(base)
        out.add(os.path.splitext(base)[0])
    return out


def name_keys(folder, filename):
    """The names a file in a named folder can be asked for under, per the game's naming."""
    stem = os.path.splitext(filename)[0]
    keys = {filename, stem, f"{folder}/{filename}"}
    s = stem
    while True:
        keys.add(s)
        if s.startswith("bg_"):
            keys.add(s[3:])
        m = SUFFIXES.search(s)
        if not m:
            break
        s = s[:m.start()]
    return keys


def check_module(module_dir):
    """Findings for one module folder: [(level, path, reason)]."""
    findings = []
    add = lambda level, path, reason: findings.append((level, path.replace(os.sep, "/"), reason))  # noqa: E731
    try:
        with open(os.path.join(module_dir, "module.json"), encoding="utf-8-sig") as fh:
            meta = json.load(fh)
    except (OSError, ValueError):
        meta = {}
    name_format = meta.get("name_format") or "$_dmc"
    strings = json_strings(module_dir)
    sprite_names = {name_format.replace("$", s).replace(":", "_") for s in strings}
    versions = set()
    try:
        with open(os.path.join(module_dir, "monster.json"), encoding="utf-8-sig") as fh:
            versions = {m.get("version") for m in json.load(fh).get("monster", []) if isinstance(m, dict)}
    except (OSError, ValueError, AttributeError):
        pass
    legacy_bg = {f"ver{v}" for v in versions if v is not None}

    # every entry: junk anywhere
    for root, dirs, files in os.walk(module_dir):
        rel_root = os.path.relpath(root, module_dir)
        for d in list(dirs):
            reason = junk_reason(d, True)
            if reason:
                add("error", os.path.join(rel_root, d) + "/", reason)
                dirs.remove(d)          # its content is reported with it
        for f in files:
            reason = junk_reason(f, False)
            if reason:
                add("error", os.path.normpath(os.path.join(rel_root, f)), reason)

    for entry in sorted(os.listdir(module_dir)):
        path = os.path.join(module_dir, entry)
        if os.path.isfile(path):
            if entry not in TOP_FILES and not junk_reason(entry, False):
                add("error", entry, "not a file the game reads from a module")
            continue
        if entry == "documentation":
            add("error", entry + "/", "generated documentation: move it to utilities/<MODULE>/documentation/ "
                                      "(utilities/claude/relocate_module_docs.py)")
            continue
        if entry not in TOP_DIRS:
            if not junk_reason(entry, True):
                add("error", entry + "/", "not a folder the game reads from a module")
            continue
        for child in sorted(os.listdir(path)):
            child_path = os.path.join(path, child)
            rel = f"{entry}/{child}"
            if junk_reason(child, os.path.isdir(child_path)):
                continue                                     # already reported
            if entry in SPRITE_DIRS:
                base = child[:-4] if child.lower().endswith(".zip") and os.path.isfile(child_path) else child
                if base not in sprite_names:
                    add("error", rel, "sprite set for no Digimon or enemy of the module")
                    continue
                for member in _sprite_members(child_path):
                    if not FRAME.fullmatch(os.path.basename(member)):
                        add("error", f"{rel}/{member}", "not a frame image (<n>.png)")
            elif entry in ATTACK_DIRS:
                if os.path.isdir(child_path) or not ATTACK.fullmatch(child):
                    add("error", rel, "attack sprites are <id>.png or <id>_dot.png; this one is never asked for")
            elif entry in NAMED_DIRS:
                if os.path.isdir(child_path):
                    if entry != "cards":
                        add("error", rel + "/", f"the game reads no subfolder of {entry}/")
                    continue
                keys = name_keys(entry, child)
                if keys & (strings | CODE_NAMES.get(entry, set())):
                    continue
                if entry == "backgrounds" and keys & legacy_bg:
                    add("warn", rel, "background not declared in module.json: only an old save "
                                     "(first background ver<version>) draws it")
                    continue
                add("error", rel, "named nowhere in the module's JSON: the game never loads it")
    return findings


def _sprite_members(path):
    if os.path.isdir(path):
        return sorted(os.listdir(path))
    try:
        with zipfile.ZipFile(path) as z:
            return sorted(n for n in z.namelist() if not n.endswith("/"))
    except zipfile.BadZipFile:
        return ["(not a readable zip)"]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("modules", nargs="*")
    ap.add_argument("--all", action="store_true", help="every module folder, not only the release set")
    ap.add_argument("--root", default=MODULES, help="the modules folder (default: the repo's)")
    ap.add_argument("--json")
    args = ap.parse_args()
    from module_audit import RELEASE_MODULES
    names = args.modules or (sorted(os.listdir(args.root)) if args.all else RELEASE_MODULES)
    report, errors = {}, 0
    for name in names:
        folder = os.path.join(args.root, name)
        if not os.path.isdir(folder):
            continue
        found = check_module(folder)
        report[name] = [{"level": lv, "path": p, "reason": r} for lv, p, r in found]
        n_err = sum(1 for lv, _, _ in found if lv == "error")
        errors += n_err
        print(f"{name:7} {n_err:4} errors {len(found) - n_err:4} warnings")
        for lv, p, r in found[:8]:
            print(f"   {lv:5} {p}: {r}")
        if len(found) > 8:
            print(f"   ... {len(found) - 8} more")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=1, ensure_ascii=False)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
