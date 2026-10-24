#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Read-only probe of the production Omninet (checklist ARN-09, MOD-17).

Only public GET requests; nothing is written to the server.

    ARN-09  a season is active and runs on an arena runtime (`/seasons/current`
            carries `runtime_version`); `/arena/modules` serves that runtime and
            fields every published release module at its published version;
            the dev tools answer 404 (`/dev/arena/status`, ENVIRONMENT=prd).
    MOD-17  every release module is published at the checkout's version, and no
            file of the checkout changed after the published upload under that
            same version (the server would refuse such pets: arena.md, VBE).

The change check compares file times with the module's `updated_at`; --deep
downloads each published zip (about 1.3 GB in all) and compares the JSON files
themselves, so a file rewritten with the same content is not reported.

    python -B tests/release/production_probe.py [--url URL] [--deep] [--json PATH]
"""
import argparse
import datetime
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "support"))
from paths import ROOT, MODULES  # noqa: E402
sys.path.insert(0, HERE)
from module_audit import RELEASE_MODULES  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
#: the server's proxy refuses urllib's default agent (403)
HEADERS = {"User-Agent": "Omnipet-release-probe/1.0", "Accept": "application/json"}


def production_url():
    text = open(os.path.join(ROOT, "src", "core", "constants.py"), encoding="utf-8").read()
    m = re.search(r'^OMNINET_MAIN_URL\s*=\s*"([^"]+)"', text, re.M)
    return m.group(1).rstrip("/") if m else "https://omnipet.app.br"


def get(url, timeout=30):
    """(status, parsed JSON or None); status 0 when the server cannot be reached."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=timeout) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return 0, str(exc)


def local_version(name):
    try:
        with open(os.path.join(MODULES, name, "module.json"), encoding="utf-8-sig") as fh:
            return json.load(fh).get("version")
    except (OSError, ValueError):
        return None


def files_changed_since(name, when):
    """Files of modules/<name> modified after `when` (a UTC datetime)."""
    root = os.path.join(MODULES, name)
    cutoff = when.timestamp()
    changed = []
    for folder, _, files in os.walk(root):
        for f in files:
            path = os.path.join(folder, f)
            if os.path.getmtime(path) > cutoff:
                changed.append(os.path.relpath(path, root).replace(os.sep, "/"))
    return sorted(changed)


def json_differences(name, base, module_id):
    """JSON files whose content differs between modules/<name> and the published zip."""
    tmp = tempfile.mkdtemp(prefix="omnipet_probe_")
    try:
        zpath = os.path.join(tmp, "module.zip")
        req = urllib.request.Request(f"{base}/api/v1/modules/{module_id}/download", headers=HEADERS)
        with urllib.request.urlopen(req, timeout=600) as resp, open(zpath, "wb") as fh:
            shutil.copyfileobj(resp, fh)
        published = {}
        with zipfile.ZipFile(zpath) as zf:
            for member in zf.namelist():
                if member.lower().endswith(".json"):
                    rel = member.split("/", 1)[1] if member.split("/", 1)[0] == name and "/" in member else member
                    try:
                        published[rel] = json.loads(zf.read(member).decode("utf-8-sig"))
                    except ValueError:
                        published[rel] = None
        root = os.path.join(MODULES, name)
        diffs = []
        for folder, _, files in os.walk(root):
            for f in files:
                if not f.lower().endswith(".json"):
                    continue
                rel = os.path.relpath(os.path.join(folder, f), root).replace(os.sep, "/")
                try:
                    with open(os.path.join(folder, f), encoding="utf-8-sig") as fh:
                        mine = json.load(fh)
                except ValueError:
                    mine = None
                if rel not in published:
                    diffs.append(f"{rel} (not in the published zip)")
                elif published[rel] != mine:
                    diffs.append(rel)
        return diffs
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class Probe:
    def __init__(self, base, deep):
        self.base = base
        self.deep = deep
        self.findings = []

    def add(self, check, severity, subject, detail):
        self.findings.append({"check": check, "severity": severity, "subject": subject, "detail": detail})

    def published_modules(self):
        """{name: item} from the public module list, or None when unreachable."""
        found, page = {}, 1
        while True:
            code, data = get(f"{self.base}/api/v1/modules?page_size=100&page={page}")
            if code != 200 or not isinstance(data, dict):
                self.add("MOD-17", "error", "/modules", f"HTTP {code}: {data if code == 0 else ''}".strip())
                return None
            for item in data.get("items", []):
                found[item["name"]] = item
            if page * 100 >= data.get("total", 0) or not data.get("items"):
                return found
            page += 1

    # ARN-09 -----------------------------------------------------------------
    def arena(self, published):
        code, season = get(f"{self.base}/api/v1/seasons/current")
        if code != 200 or not isinstance(season, dict):
            self.add("ARN-09", "error", "/seasons/current", f"HTTP {code}: no active season")
        else:
            self.add("ARN-09", "info", "/seasons/current", f"{season.get('name')} ({season.get('status')}, "
                     f"{season.get('starts_at') or season.get('start_date')} to {season.get('ends_at') or season.get('end_date')})")
            if season.get("status") != "active":
                self.add("ARN-09", "error", "/seasons/current", f"status {season.get('status')!r}")
            if "runtime_version" not in season:
                self.add("ARN-09", "error", "/seasons/current",
                         "no runtime_version: the server predates the arena seasons rework (deploy Omninet)")
            elif not season.get("runtime_version"):
                self.add("ARN-09", "error", "/seasons/current", "the season runs on no arena runtime")

        code, arena = get(f"{self.base}/api/v1/arena/modules")
        if code != 200 or not isinstance(arena, dict):
            self.add("ARN-09", "error", "/arena/modules", f"HTTP {code}: the arena runtime is not served")
        else:
            fielded = {m["name"]: m for m in arena.get("modules", [])}
            self.add("ARN-09", "info", "/arena/modules",
                     f"runtime {arena.get('runtime_version')}: {len(fielded)} modules")
            for name in RELEASE_MODULES:
                item = (published or {}).get(name)
                if not item:
                    continue                      # reported under MOD-17
                if name not in fielded:
                    self.add("ARN-09", "error", name, "published but not in the season's runtime (updates/sync-published)")
                elif fielded[name].get("version") != item.get("version"):
                    self.add("ARN-09", "error", name, f"runtime has {fielded[name].get('version')}, "
                             f"published is {item.get('version')} (updates/sync-published)")

        code, _ = get(f"{self.base}/api/v1/dev/arena/status")
        if code == 404:
            self.add("ARN-09", "info", "/dev/arena/status", "404 (dev tools off)")
        else:
            self.add("ARN-09", "error", "/dev/arena/status", f"HTTP {code}: the dev tools answer (ENVIRONMENT=dev?)")

    # MOD-17 -----------------------------------------------------------------
    def modules(self, published):
        if published is None:
            return
        for name in RELEASE_MODULES:
            mine = local_version(name)
            item = published.get(name)
            if not item:
                self.add("MOD-17", "error", name, f"not published (checkout {mine})")
                continue
            theirs = item.get("version")
            if theirs != mine:
                self.add("MOD-17", "error", name, f"published {theirs}, checkout {mine}")
                continue
            when = datetime.datetime.fromisoformat(item["updated_at"].replace("Z", "+00:00"))
            changed = files_changed_since(name, when)
            if changed and self.deep:
                changed = json_differences(name, self.base, item["id"])
            if changed:
                shown = ", ".join(changed[:5]) + (f" and {len(changed) - 5} more" if len(changed) > 5 else "")
                self.add("MOD-17", "error", name, f"{theirs} published {when:%Y-%m-%d %H:%M} UTC; changed since "
                         f"under the same version: {shown}")
            else:
                self.add("MOD-17", "info", name, f"{theirs}, unchanged since {when:%Y-%m-%d}")
        extra = sorted(set(published) - set(RELEASE_MODULES))
        if extra:
            self.add("MOD-17", "warn", "/modules", "published, not in the release set: " + ", ".join(extra))

    def run(self):
        published = self.published_modules()
        self.arena(published)
        self.modules(published)
        return self.findings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="server (default: the game's OMNINET_MAIN_URL)")
    ap.add_argument("--deep", action="store_true", help="download the published zips and compare their JSON")
    ap.add_argument("--json")
    args = ap.parse_args()
    base = (args.url or production_url()).rstrip("/")
    findings = Probe(base, args.deep).run()
    print(f"server: {base}")
    for f in findings:
        print(f"{f['severity']:5} {f['check']} {f['subject']}: {f['detail']}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"server": base, "findings": findings}, fh, indent=1)
    sys.exit(1 if any(f["severity"] == "error" for f in findings) else 0)


if __name__ == "__main__":
    main()
