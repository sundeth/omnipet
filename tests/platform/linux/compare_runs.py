#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Which test files fail on Linux but pass on Windows (and the reverse).

    python -B tests/platform/linux/compare_runs.py LINUX_RUN.json WINDOWS_RUN.json

Both files are tests/run_tests.py --json outputs: the Linux one from
run_suite.sh (tmp/platform/linux/run_tests_<mode>.json), the Windows one from
`python -B tests/run_tests.py --json tmp/platform/windows_run.json` on the PC.
A file only failing on Linux is a platform finding (tests/findings/platform.md);
rerun it on both sides first: other work may have changed it between runs.
Exit 1 when a file fails only on Linux.
"""
import json
import sys


def load(path):
    with open(path, encoding="utf-8") as fh:
        rows = json.load(fh)
    out = {}
    for r in rows:
        ok = r["returncode"] in (0, 5) and not r["crashed"] and not r["failures"]
        out[r["file"]] = (ok, r)
    return out


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    linux, windows = load(sys.argv[1]), load(sys.argv[2])
    only_linux = sorted(f for f, (ok, _) in linux.items() if not ok and windows.get(f, (False,))[0])
    only_windows = sorted(f for f, (ok, _) in windows.items() if not ok and linux.get(f, (False,))[0])
    both = sorted(f for f, (ok, _) in linux.items() if not ok and f in windows and not windows[f][0])
    missing = sorted(set(linux) ^ set(windows))
    print(f"[compare] {len(linux)} Linux runs, {len(windows)} Windows runs")
    for label, files in (("FAILS ONLY ON LINUX", only_linux), ("fails only on Windows", only_windows),
                         ("fails on both", both)):
        print(f"[compare] {label}: {len(files)}")
        for f in files:
            r = linux.get(f, windows.get(f))[1]
            print(f"    {f}")
            for name in r["failures"][:8]:
                print(f"        - {name}")
    if missing:
        print(f"[compare] run in only one of the two: {', '.join(missing[:10])}")
    sys.exit(1 if only_linux else 0)


if __name__ == "__main__":
    main()
