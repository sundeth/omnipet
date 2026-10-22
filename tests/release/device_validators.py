#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Run the per-device module validators and summarise them (checklist MOD-16).

The validators live in utilities/claude/ (with the saved sources they compare
against: humulos pages, firmware dumps, BladeSabre's tables); utilities/ is not
in git, so on a checkout without it this stage reports "not available".
Each one prints its own findings; this collects them into
<out>/validators/<script>.txt and a summary: how many findings, or that the
validator itself is broken (a traceback). The findings are for review: the
validators compare against fan sources, and measurements on real hardware win
(CLAUDE.md), so a finding is a question, not a failure.

    python -B tests/release/device_validators.py [--out DIR] [--json PATH]
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "support"))
from paths import ROOT, REPORTS  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
CLAUDE = os.path.join(ROOT, "utilities", "claude")
#: module -> validator script in utilities/claude (owner's validators, 2026)
VALIDATORS = [
    ("DM20", "validate_dm20.py"), ("DMC", "validate_dmc.py"), ("DMH", "validate_dmh.py"),
    ("DMX", "validate_dmx.py"), ("PENOG", "validate_pen.py"), ("PEN20", "validate_pen20.py"),
    ("PENC", "validate_penc.py"), ("PENZ", "validate_penz.py"), ("D-3", "validate_d3.py"),
    ("VB/VBE/VH", "vb_validate.py"),
]
TOTAL = re.compile(r"TOTAL\s+(\d+)\s+findings?", re.I)


def run_one(module, script, out_dir):
    path = os.path.join(CLAUDE, script)
    if not os.path.isfile(path):
        return {"module": module, "script": script, "status": "not available", "findings": None, "seconds": 0}
    start = time.time()
    try:
        proc = subprocess.run([sys.executable, "-B", path], cwd=CLAUDE, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=600,
                              env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        text = proc.stdout + ("\n--- stderr ---\n" + proc.stderr if proc.stderr.strip() else "")
    except subprocess.TimeoutExpired:
        text, proc = "timed out after 600 s", None
    with open(os.path.join(out_dir, script.replace(".py", ".txt")), "w", encoding="utf-8") as fh:
        fh.write(text)
    if proc is None:
        status, findings = "timed out", None
    elif "Traceback (most recent call last)" in text:
        last = [l for l in text.strip().splitlines() if l.strip()][-1]
        status, findings = f"broken: {last[:160]}", None
    else:
        m = TOTAL.search(text)
        findings = int(m.group(1)) if m else None
        status = "ran"
    return {"module": module, "script": script, "status": status, "findings": findings,
            "seconds": round(time.time() - start, 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(REPORTS, "validators"))
    ap.add_argument("--json")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    rows = [run_one(m, s, args.out) for m, s in VALIDATORS]
    for r in rows:
        f = "" if r["findings"] is None else f"{r['findings']} findings"
        print(f"{r['module']:10} {r['script']:20} {r['status'][:90]:40} {f}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, indent=1)
    sys.exit(1 if any(r["status"].startswith(("broken", "timed")) for r in rows) else 0)


if __name__ == "__main__":
    main()
