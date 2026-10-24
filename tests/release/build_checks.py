#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Static release checks for builds, endpoints, gates and documentation.

Checklist BLD-04/05, BAT-06/07, DOC-01/03. Read-only.

    python -B tests/release/build_checks.py [--version "1.0.0"] [--json PATH]

Without --version the release version is src/core/version.py's VERSION, and
every other place that names a version must agree with it.
"""
import argparse
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "support"))
from paths import ROOT, temp_dir, REPORTS  # noqa: E402
EDITOR = r"E:/Omnipet Module Editor/OmnipetModuleEditor"
sys.path.insert(0, HERE)
from module_audit import RELEASE_MODULES  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")


def read(path):
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def grab(path, pattern, flags=0):
    text = read(os.path.join(ROOT, path) if not os.path.isabs(path) else path)
    if text is None:
        return None
    m = re.search(pattern, text, flags)
    return m.group(1) if m else None


class Checks:
    def __init__(self, version):
        self.version = version
        self.findings = []

    def add(self, check, severity, subject, detail):
        self.findings.append({"check": check, "severity": severity, "subject": subject, "detail": detail})

    # BLD-05 -----------------------------------------------------------------
    def versions(self):
        # src/core/version.py is the single source: the entry points import it and the
        # build scripts read it, so none of them may write a version of its own.
        for name in ("main.py", "main_profile.py", "main_nuitka.py", "src/vpet.py"):
            v = grab(name, r'^\s*(?:runtime_globals\.)?VERSION\s*=\s*"([^"]+)"', re.M)
            if v:
                self.add("BLD-05", "error", name, f"hard-codes {v!r}; import core.version")
        for script in sorted(glob.glob(os.path.join(ROOT, "build", "build_*.ps1"))):
            v = grab(script, r'\[string\]\$Version\s*=\s*"([^"]*)"')
            if v:
                self.add("BLD-05", "error", f"build/{os.path.basename(script)}",
                         f"defaults -Version to {v!r}; read src/core/version.py")
        if os.path.exists(os.path.join(ROOT, "build", "version.txt")):
            self.add("BLD-05", "error", "build/version.txt", "a second version file")
        sources = {
            "src/core/version.py VERSION": grab(os.path.join("src", "core", "version.py"),
                                                r'^VERSION\s*=\s*"([^"]+)"', re.M),
            "buildozer.spec version (Android versionName)": grab("buildozer.spec", r'^version\s*=\s*(\S+)', re.M),
            "Module Editor AssemblyVersion": grab(os.path.join(EDITOR, "Properties", "AssemblyInfo.cs"),
                                                  r'^\[assembly: AssemblyVersion\("([^"]+)"\)\]', re.M),
        }
        base = re.sub(r"\s.*", "", self.version)            # "1.0.0 Beta 3" -> "1.0.0"
        for name, value in sources.items():
            if value is None:
                self.add("BLD-05", "warn", name, "not found")
            elif value == self.version or (value in (base, base + ".0") and ("buildozer" in name or "Assembly" in name)):
                self.add("BLD-05", "info", name, f"{value}")
            else:
                self.add("BLD-05", "error", name, f"says {value!r}, release is {self.version!r}")

    # BLD-04 -----------------------------------------------------------------
    def endpoints(self):
        const = read(os.path.join(ROOT, "src", "core", "constants.py")) or ""
        main_url = grab("src/core/constants.py", r'OMNINET_MAIN_URL\s*=\s*"([^"]+)"')
        if main_url != "https://omnipet.app.br":
            self.add("BLD-04", "error", "OMNINET_MAIN_URL", f"is {main_url!r}")
        for path in glob.glob(os.path.join(ROOT, "src", "**", "*.py"), recursive=True):
            rel = os.path.relpath(path, ROOT).replace("\\", "/")
            for n, line in enumerate((read(path) or "").splitlines(), 1):
                code = line.split("#", 1)[0]
                if "OMNINET_LOCAL_URL" in code and "constants.py" not in rel:
                    self.add("BLD-04", "error", f"{rel}:{n}", "probes OMNINET_LOCAL_URL (the dev server) before production")
                if re.search(r"https?://(localhost|127\.0\.0\.1|dev\.omnipet)", code) and "constants.py" not in rel \
                        and "omninet_service.py" not in rel:
                    self.add("BLD-04", "error", f"{rel}:{n}", "hard-coded dev/local endpoint: " + code.strip()[:120])
        for name in ("DISCORD_BOT_LOCAL_URL", "DISCORD_BOT_MAIN_URL"):
            v = grab("src/core/constants.py", name + r'\s*=\s*"([^"]+)"')
            if v and re.search(r"localhost|127\.0\.0\.1", v) and re.search(r"DISCORD_ENABLED\s*=\s*True", const):
                self.add("BLD-04", "error", name, f"{v} while DISCORD_ENABLED is True")
        if "DISCORD_BOT_URL" not in const and "DISCORD_BOT_URL" in (read(os.path.join(ROOT, "src", "scenes", "scene_connect.py")) or ""):
            self.add("BLD-04", "error", "scene_connect.py DISCORD_BOT_URL", "constant does not exist; falls back to http://localhost:5000")
        for flag in ("DISCORD_DEBUG", "DEBUG_SCALE"):
            for path in glob.glob(os.path.join(ROOT, "src", "**", "*.py"), recursive=True):
                m = re.search(rf"^{flag}\s*=\s*True", read(path) or "", re.M)
                if m:
                    self.add("BLD-04", "warn", f"{os.path.relpath(path, ROOT)} {flag}", "debug flag on")

    # BAT-06/07 -------------------------------------------------------------
    def gates(self):
        pc = read(os.path.join(ROOT, "src", "battle", "sim", "protocol_constants.py")) or ""
        # What players see: the grid's default entries (debug mode may offer more).
        try:
            sys.path.insert(0, os.path.join(ROOT, "src"))
            from battle.sim import protocol_constants
            offered = [name for name, _, enabled in protocol_constants.menu_entries()
                       if enabled and name not in protocol_constants.BATTLE_FORMATS]
        except Exception as exc:
            offered = []
            self.add("BAT-06", "warn", "protocol_constants", f"could not read the protocol menu: {exc}")
        if offered:
            self.add("BAT-06", "error", "protocol menu",
                     f"{', '.join(offered)} selectable without a battle format; 1.0 holds unfinished lines back")
        menu = read(os.path.join(ROOT, "src", "scenes", "connect_views", "main_menu_view.py")) or ""
        consts = read(os.path.join(ROOT, "src", "core", "constants.py")) or ""
        released = re.search(r"^WIFICOM_BATTLES_RELEASED\s*=\s*(\w+)", consts, re.M)
        if "_on_wificom_selected" in menu:
            if "WIFICOM_BATTLES_RELEASED" not in menu or not released:
                self.add("BAT-07", "error", "main_menu_view WiFiCom button",
                         "no release gate: it appears whenever wificom.dev credentials exist")
            elif released.group(1) != "False":
                self.add("BAT-07", "error", "constants.WIFICOM_BATTLES_RELEASED",
                         f"is {released.group(1)}: 1.0 holds WiFi-Com battles back")

    # DOC-01/03 --------------------------------------------------------------
    def documentation(self):
        cl = read(os.path.join(ROOT, "Documentation", "pages", "changelog.html")) or ""
        # The section's own heading: "Version 1.0.0" alone on its line, so
        # "Version 1.0.0 Beta 3" does not stand in for the release.
        if not re.search(r"^\s*Version\s+" + re.escape(self.version) + r"\s*$", cl, re.M):
            self.add("DOC-03", "error", "Documentation/pages/changelog.html", f"no section for {self.version}")
        # The generated pages live in utilities/<MODULE>/documentation/, out of
        # the published module (owner, 2026-10-24; MOD-18 refuses them there).
        for m in RELEASE_MODULES:
            d = os.path.join(ROOT, "modules", m)
            doc_dir = os.path.join(ROOT, "utilities", m, "documentation")
            if not os.path.isfile(os.path.join(doc_dir, "index.html")):
                self.add("DOC-01", "error", m, "no generated documentation (utilities/%s/documentation/index.html)" % m)
                continue
            data = [os.path.join(d, f) for f in os.listdir(d) if f.endswith(".json")]
            newest = max((os.path.getmtime(p) for p in data), default=0)
            docs = [os.path.join(dp, f) for dp, _, fs in os.walk(doc_dir) for f in fs if f.endswith(".html")]
            built = max((os.path.getmtime(p) for p in docs), default=0)
            if built < newest:
                import datetime
                stale = max(data, key=os.path.getmtime)
                self.add("DOC-01", "error", m, "documentation older than " + os.path.basename(stale) +
                         f" ({datetime.date.fromtimestamp(built)} < {datetime.date.fromtimestamp(newest)})")

    # UI-08 / TRN-01 ---------------------------------------------------------
    def asset_literals(self):
        """Every literal assets/... file the code names exists, in exact letter case.

        Windows forgives a wrong case; the Pi, Batocera and Android do not.
        Paths built at run time (f-strings, joins) are not seen here.
        """
        pat = re.compile(r"""["'](assets/[^"'{}%*]+?\.(?:png|wav|ogg|mp3|ttf|otf|json|gif))["']""", re.I)
        listing = {}

        def exact(rel):
            cur = ROOT
            for part in rel.split("/"):
                if cur not in listing:
                    listing[cur] = os.listdir(cur) if os.path.isdir(cur) else []
                if part not in listing[cur]:
                    lower = {n.lower(): n for n in listing[cur]}
                    return "case" if part.lower() in lower else "missing"
                cur = os.path.join(cur, part)
            return "ok"
        seen = set()
        sources = {p: read(p) or "" for p in glob.glob(os.path.join(ROOT, "src", "**", "*.py"), recursive=True)}
        everything = "\n".join(sources.values())
        for path, text in sources.items():
            rel_src = os.path.relpath(path, ROOT).replace("\\", "/")
            lines = text.splitlines()
            in_doc = False
            for n, line in enumerate(lines, 1):
                quotes = line.count('"""') + line.count("'''")
                if in_doc or (quotes == 1 and not re.match(r"\s*\w+\s*=", line)) or \
                        (quotes >= 2 and re.match(r'\s*[rbu]?("""|\'\'\')', line)):
                    if quotes % 2 == 1:
                        in_doc = not in_doc
                    continue                    # docstring: examples, not loads
                if not re.search(r"\b[A-Z][A-Z0-9_]*\s*=", line):
                    for back in range(n - 2, max(-1, n - 30), -1):      # inside NAME = {...}
                        m = re.match(r"\s*([A-Z][A-Z0-9_]*)\s*=\s*[\[{(]", lines[back])
                        if m:
                            line = f"{m.group(1)} = {line}"
                            break
                        if not lines[back].strip() or re.match(r"\s*[\]})]", lines[back]):
                            break
                for ref in pat.findall(line.split("#", 1)[0]):
                    if (ref, rel_src) in seen:
                        continue
                    seen.add((ref, rel_src))
                    state = exact(ref)
                    if state == "ok":
                        continue
                    what = ref + (" exists only in another letter case (fails on Linux/Android)"
                                  if state == "case" else " does not exist")
                    # a constants.py name nothing else reads is dead, not broken
                    const = re.match(r"\s*([A-Z][A-Z0-9_]*)\s*=", line)
                    users = [p for p, t in sources.items() if p != path and const and
                             re.search(rf"\b{const.group(1)}\b", t)] if const else [path]
                    if const and not users:
                        self.add("UI-08", "warn", f"{rel_src}:{n}", f"unused constant {const.group(1)}: {what}")
                        continue
                    where = ", ".join(sorted({os.path.relpath(p, ROOT).replace(chr(92), '/') for p in users})[:3])
                    check = "TRN-01" if re.search(r"training|minigames", where + rel_src) else "UI-08"
                    self.add(check, "error", f"{rel_src}:{n}", what + (f" (read by {where})" if const else ""))

    # BLD-01 (inventory only) ------------------------------------------------
    def artifacts(self):
        rel = os.path.join(ROOT, "Release")
        names = os.listdir(rel) if os.path.isdir(rel) else []
        apks = glob.glob(os.path.join(ROOT, "bin", "*.apk"))
        for platform in ("Windows", "Python_Desktop", "GamePi", "Batocera", "Module_Editor"):
            hit = [n for n in names if platform in n and self.version in n]
            self.add("BLD-01", "info" if hit else "warn", f"Release/{platform}",
                     ", ".join(hit) if hit else f"no artifact for {self.version}")
        self.add("BLD-01", "info", "Android", ", ".join(os.path.basename(a) for a in apks) or "no apk in bin/")

    # BLD-07 -----------------------------------------------------------------
    #: Trees every build copies whole (build/*.ps1, buildozer.spec, the PyInstaller specs).
    BUILD_TREES = ("assets", "Documentation", "src")
    WORK_DIRS = {"tests", "test", "tmp", "temp", "utilities", "research", "original", "originals",
                 "scratch", "old", "bak", "wip", "unused", ".git", ".svn", ".vscode", ".idea",
                 "__macosx", "release", "logs"}
    WORK_EXT = {".bak", ".orig", ".old", ".tmp", ".temp", ".swp", ".swo", ".part", ".crdownload",
                ".psd", ".ase", ".aseprite", ".xcf", ".kra", ".pdn", ".sai", ".clip",
                ".xls", ".xlsx", ".ods", ".csv", ".log", ".md", ".doc", ".docx", ".rtf"}

    def _work_reason(self, rel, is_dir, referenced):
        """Why a path inside a build is a work file, or None. *referenced*: file
        names the game's code or the documentation pages ask for."""
        from module_files import DUPLICATE, JUNK_NAMES
        name = os.path.basename(rel.rstrip("/"))
        low = name.lower()
        if is_dir:
            if low in self.WORK_DIRS or "backup" in low:
                return "a test, temporary, backup or work folder"
            return None
        ext = os.path.splitext(low)[1]
        if low in JUNK_NAMES:
            return "an operating-system file"
        if DUPLICATE.search(name):
            return "a duplicate left by a copy"
        if ext in self.WORK_EXT:
            return f"a {ext} file (backup, source art, notes or data sheet)"
        if re.fullmatch(r"(test_.+|.+_test|conftest)\.py", low):
            return "a test"
        if ext == ".txt" and low != "license.txt" and name not in referenced:
            return "a .txt nothing in the game reads"
        if ext == ".py" and rel.replace("\\", "/").startswith("Documentation/") and name not in referenced:
            return "a script no documentation page links"
        return None

    def _referenced_names(self):
        """File names written as string literals in src/ or linked from the documentation pages."""
        names = set()
        for base, pattern in (("src", r"[\"']([^\"'\n]*?\.(?:txt|py))[\"']"),
                              ("Documentation", r"(?:href|src)=[\"']([^\"'#?]+)")):
            for root, dirs, files in os.walk(os.path.join(ROOT, base)):
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                for f in files:
                    if f.endswith((".py", ".html", ".htm")):
                        for m in re.finditer(pattern, read(os.path.join(root, f)) or ""):
                            names.add(os.path.basename(m.group(1)))
        return names

    def build_contents(self):
        """BLD-07: a build carries only the game: no test, temporary or work
        folders, backups, research, notes or source art, no modules and no save."""
        referenced = self._referenced_names()
        # what the next build will copy
        for tree in self.BUILD_TREES:
            for root, dirs, files in os.walk(os.path.join(ROOT, tree)):
                dirs.sort()
                for d in list(dirs):
                    if d == "__pycache__":           # every pipeline excludes it
                        dirs.remove(d)
                        continue
                    rel = os.path.relpath(os.path.join(root, d), ROOT).replace("\\", "/") + "/"
                    reason = self._work_reason(rel, True, referenced)
                    if reason:
                        self.add("BLD-07", "error", rel, f"{reason}; every build copies {tree}/ whole")
                        dirs.remove(d)
                for f in sorted(files):
                    rel = os.path.relpath(os.path.join(root, f), ROOT).replace("\\", "/")
                    reason = self._work_reason(rel, False, referenced)
                    if reason:
                        self.add("BLD-07", "error", rel, f"{reason}; every build copies {tree}/ whole")
        # the artifacts of this version already built
        rel_dir = os.path.join(ROOT, "Release")
        released = sorted(os.listdir(rel_dir)) if os.path.isdir(rel_dir) else []
        for name in released:
            if self.version not in name:
                continue
            path = os.path.join(rel_dir, name)
            if os.path.isdir(path) and name + ".zip" in released:
                continue                     # the zip is the artifact; the folder may have been run since
            entries = []
            if os.path.isdir(path):
                for root, dirs, files in os.walk(path):
                    for d in dirs:
                        entries.append((os.path.relpath(os.path.join(root, d), path), True))
                    for f in files:
                        entries.append((os.path.relpath(os.path.join(root, f), path), False))
            elif name.lower().endswith(".zip"):
                import zipfile
                try:
                    with zipfile.ZipFile(path) as z:
                        for n in z.namelist():
                            entries.append((n.rstrip("/"), n.endswith("/")))
                except zipfile.BadZipFile:
                    self.add("BLD-07", "error", f"Release/{name}", "not a readable zip")
                    continue
            else:
                continue
            bad, shipped = [], set()
            entries = [(rel.replace("\\", "/"), is_dir) for rel, is_dir in entries]
            tops = {rel.split("/")[0] for rel, _ in entries}
            # a zip may hold one top folder named after the build
            strip = len(tops) == 1 and name.lower().endswith(".zip") and any("/" in r for r, _ in entries)
            for rel, is_dir in entries:
                inner = rel.split("/", 1)[1] if strip and "/" in rel else ("" if strip else rel)
                if not inner:
                    continue
                parts = inner.split("/")
                if parts[0] in ("modules", "save") and len(parts) > 1:
                    if (parts[0], parts[1]) not in shipped:
                        shipped.add((parts[0], parts[1]))
                        bad.append((f"{parts[0]}/{parts[1]}", f"{parts[0]}/ must ship empty "
                                    "(modules come from the shop; saves are the player's)"))
                    continue
                if "/Module Editor/" in "/" + inner + "/" or "_internal/" in inner:
                    continue                 # the editor's and Python's own runtime files
                work_parent = next((i for i, p in enumerate(parts[:-1])
                                    if p and self._work_reason(p + "/", True, referenced)), None)
                if work_parent is not None:
                    folder = "/".join(parts[:work_parent + 1])
                    if ("dir", folder) not in shipped:      # a zip may list no folder entries
                        shipped.add(("dir", folder))
                        bad.append((folder, self._work_reason(folder + "/", True, referenced)))
                    continue
                if is_dir and ("dir", inner) in shipped:
                    continue
                reason = self._work_reason(inner, is_dir, referenced)
                if reason:
                    bad.append((inner, reason))
            for inner, reason in bad[:40]:
                self.add("BLD-07", "error", f"Release/{name}: {inner}", reason)
            if len(bad) > 40:
                self.add("BLD-07", "error", f"Release/{name}", f"... {len(bad) - 40} more")
        # what the build recipes pull in
        for script in sorted(glob.glob(os.path.join(ROOT, "build", "*.ps1"))):
            text = read(script) or ""
            rel = os.path.relpath(script, ROOT).replace("\\", "/")
            for m in sorted(set(re.findall(r"(?:\.\.\\|[\"'])(utilities\\[^\"'\s)]+)", text))):
                self.add("BLD-07", "warn", rel, f"copies {m.replace(chr(92), '/')} from the gitignored utilities/ "
                                                "folder into the build (a clean checkout cannot build it)")
            # Every literal "..\X" a Copy-Item takes must exist (a failed copy
            # does not stop the script: ModuleEditor.bat, removed 2026-03-28,
            # was missing from two zips until 2026-10-24). dist\ is
            # PyInstaller's own output.
            for m in sorted(set(re.findall(r'Copy-Item\s+(?:-\w+\s+)*"\.\.\\([^"$*]+)"', text))):
                if m.startswith("dist\\"):
                    continue
                if not os.path.exists(os.path.join(ROOT, m.replace("\\", os.sep))):
                    self.add("BLD-07", "error", rel, f"copies {m.replace(chr(92), '/')}, which no longer exists")
        for spec in ("Omnipet.spec", "pyinstall.spec"):
            text = read(os.path.join(ROOT, spec)) or ""
            for bad in ("utilities", "tests", "tmp"):
                if re.search(r"\(\s*['\"]" + bad + r"['\"/\\]", text):
                    self.add("BLD-07", "error", spec, f"bundles {bad}/")
        buildozer = read(os.path.join(ROOT, "buildozer.spec")) or ""
        excluded = set(x.strip() for x in grab("buildozer.spec", r"^source\.exclude_dirs\s*=\s*(.+)$", re.M).split(",")) \
            if grab("buildozer.spec", r"^source\.exclude_dirs\s*=\s*(.+)$", re.M) else set()
        for need in ("tests", "tmp", "utilities", "build", "Release"):
            if buildozer and need not in excluded:
                self.add("BLD-07", "error", "buildozer.spec", f"source.exclude_dirs does not exclude {need}")

    def run(self):
        self.versions()
        self.endpoints()
        self.gates()
        self.documentation()
        self.asset_literals()
        self.artifacts()
        self.build_contents()
        return self.findings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version")
    ap.add_argument("--json")
    args = ap.parse_args()
    version = args.version or grab(os.path.join("src", "core", "version.py"), r'^VERSION\s*=\s*"([^"]+)"', re.M)
    findings = Checks(version).run()
    print(f"release version: {version}")
    for f in sorted(findings, key=lambda f: (f["check"], {"error": 0, "warn": 1, "info": 2}[f["severity"]])):
        if f["severity"] != "info":
            print(f"{f['severity']:5} {f['check']} {f['subject']}: {f['detail']}"[:240])
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"version": version, "findings": findings}, fh, indent=1)
    sys.exit(1 if any(f["severity"] == "error" for f in findings) else 0)


if __name__ == "__main__":
    main()
