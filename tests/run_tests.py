#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Run every test file in its own process, a few at a time.

    python -B tests/run_tests.py [-j N] [--json PATH] [--only unit|game|SUBSTRING ...] [FILE ...]

Collects tests/unit/**/test_*.py and tests/game/**/test_*.py, plus any file
still waiting in the legacy folder utilities/claude/tests/ that has not moved
yet (same file name in tests/ wins). One pytest process for everything
crashes (a test that quits pygame's font module leaves a cached Font behind
for the next), so each file gets its own interpreter. `-j` defaults to 4:
the game tests boot pygame and load every module, so more processes than
that mostly fight over the disk. Files listed in SCRIPT_TESTS also run as a
script (their own runner prints its counts). Exit 1 if any file failed or
crashed.
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.stdout.reconfigure(encoding="utf-8")
TESTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS)
LEGACY = os.path.join(ROOT, "utilities", "claude", "tests")
SCRIPT_TESTS = ("test_battle_protocols.py",)
SUMMARY = re.compile(r"(\d+) (passed|failed|error|errors|skipped|xfailed|xpassed)")
ENV = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy", PYTHONIOENCODING="utf-8")


def discover():
    found = {}
    for area in ("unit", "game"):
        for path in sorted(glob.glob(os.path.join(TESTS, area, "**", "test_*.py"), recursive=True)):
            found.setdefault(os.path.basename(path), path)
    for path in sorted(glob.glob(os.path.join(LEGACY, "test_*.py"))):
        found.setdefault(os.path.basename(path), path)        # not moved yet
    return sorted(found.values())


def rel(path):
    return os.path.relpath(path, ROOT).replace("\\", "/")


def run_pytest(path):
    start = time.time()
    proc = subprocess.run(
        [sys.executable, "-B", "-X", "faulthandler", "-m", "pytest", "-q", "-p", "no:cacheprovider", path],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", env=ENV)
    counts = {}
    for n, kind in SUMMARY.findall(proc.stdout.splitlines()[-1] if proc.stdout.strip() else ""):
        counts["error" if kind == "errors" else kind] = int(n)
    failures = re.findall(r"^FAILED (\S+)", proc.stdout, re.M) + re.findall(r"^ERROR (\S+)", proc.stdout, re.M)
    crashed = "Windows fatal exception" in proc.stderr + proc.stdout or proc.returncode not in (0, 1, 5)
    return {"file": rel(path), "kind": "pytest", "returncode": proc.returncode, "counts": counts,
            "failures": failures, "crashed": crashed, "seconds": round(time.time() - start, 1),
            "tail": "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-25:])}


def run_script(path):
    start = time.time()
    proc = subprocess.run([sys.executable, "-B", path], cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=ENV)
    return {"file": rel(path) + " (script)", "kind": "script", "returncode": proc.returncode, "counts": {},
            "failures": [], "crashed": proc.returncode not in (0, 1), "seconds": round(time.time() - start, 1),
            "tail": "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-25:])}


def ok(r):
    return r["returncode"] in (0, 5) and not r["crashed"] and not r["failures"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("-j", type=int, default=min(4, max(1, (os.cpu_count() or 2) - 2)))
    ap.add_argument("--only", nargs="*", help="keep files whose path contains any of these (unit, game, battle ...)")
    ap.add_argument("--json")
    args = ap.parse_args()
    files = [os.path.abspath(f) for f in args.files] or discover()
    if args.only:
        files = [f for f in files if any(o in rel(f) for o in args.only)]
    jobs = [(run_pytest, f) for f in files]
    jobs += [(run_script, f) for f in files if os.path.basename(f) in SCRIPT_TESTS]
    with ThreadPoolExecutor(args.j) as pool:
        results = list(pool.map(lambda j: j[0](j[1]), jobs))
    bad = 0
    for r in sorted(results, key=lambda r: (ok(r), r["file"])):
        status = "ok" if ok(r) else ("CRASH" if r["crashed"] else "FAIL")
        bad += status != "ok"
        counts = ", ".join(f"{v} {k}" for k, v in r["counts"].items()) or f"exit {r['returncode']}"
        print(f"{status:5} {r['file']:62} {counts:26} {r['seconds']:6.1f}s")
        for f in r["failures"]:
            print(f"      - {f}")
        if status != "ok" and not r["failures"]:
            print("      " + r["tail"].replace("\n", "\n      "))
    total = {}
    for r in results:
        for k, v in r["counts"].items():
            total[k] = total.get(k, 0) + v
    legacy = sum(1 for r in results if r["file"].startswith("utilities/"))
    print(f"\n{len(results)} runs ({legacy} from the legacy folder), {bad} not ok; "
          + ", ".join(f"{v} {k}" for k, v in total.items()))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=1)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
