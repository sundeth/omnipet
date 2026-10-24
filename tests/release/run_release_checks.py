#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Run every automated release check and write one dated report.

The automated half of utilities/claude/docs/release-checklist.md:

    tests     tests/unit and tests/game, one process per file (tests/run_tests.py)
    modules   module data audit                             (module_audit.py)
    evolutions  every route of every raisable form, taken by the game  (evolution_crawl.py)
    collection  every item and card: can a player get it, and how  (collection_crawl.py)
    care      lifespan, sickness and injury on the live clock  (care_crawl.py)
    editor    Module Editor load + report, headless          (editor_report.ps1)
    scenes    every scene x 10 resolutions                   (scene_sweep.py)
    crawl     every screen reachable by keyboard and by touch (menu_crawl.py)
    tutorial  the tutorial played by keyboard, mouse and touch; fumbled,
              skipped at every step                         (tutorial_crawl.py)
    validators  per-device module validators, for review     (device_validators.py)
    builds    versions, endpoints, gates, documentation      (build_checks.py)
    production  the production Omninet, read-only: season, arena runtime,
              published release modules                     (production_probe.py)

    python -B tests/release/run_release_checks.py [--only tests modules ...] [--out DIR]

Writes <out>/summary.md plus each stage's raw output; <out> defaults to
tests/release/reports/<YYYY-MM-DD_HHMM>/. Exit 1 when any stage
reports errors. Stages are independent, so --only reruns one.
"""
import argparse
import collections
import datetime
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "support"))
from paths import ROOT, temp_dir, REPORTS  # noqa: E402
STAGES = ["tests", "modules", "evolutions", "collection", "care", "editor", "validators", "scenes", "crawl",
          "tutorial", "builds", "production"]
sys.stdout.reconfigure(encoding="utf-8")


def run(cmd, log):
    start = time.time()
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    with open(log, "w", encoding="utf-8") as fh:
        fh.write(proc.stdout + ("\n--- stderr ---\n" + proc.stderr if proc.stderr.strip() else ""))
    return proc.returncode, round(time.time() - start)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", choices=STAGES)
    ap.add_argument("--out")
    args = ap.parse_args()
    stages = args.only or STAGES
    out = args.out or os.path.join(REPORTS, datetime.datetime.now().strftime("%Y-%m-%d_%H%M"))
    os.makedirs(out, exist_ok=True)
    py = [sys.executable, "-B"]
    rows, sections = [], []

    if "tests" in stages:
        code, secs = run(py + [os.path.join(os.path.dirname(HERE), "run_tests.py"), "--json", os.path.join(out, "tests.json")],
                         os.path.join(out, "tests.log"))
        res = json.load(open(os.path.join(out, "tests.json"), encoding="utf-8"))
        passed = sum(r["counts"].get("passed", 0) for r in res)
        bad = [r for r in res if not (r["returncode"] in (0, 5) and not r["crashed"] and not r["failures"])]
        rows.append(("Automated tests", "pass" if not bad else "FAIL",
                     f"{len(res)} runs, {passed} pytest tests passed, {len(bad)} files not ok", secs))
        sections.append("## Tests\n\n" + ("All test files pass.\n" if not bad else
                        "\n".join(f"- {r['file']}: {', '.join(r['failures']) or 'exit ' + str(r['returncode'])}" for r in bad) + "\n"))

    if "modules" in stages:
        code, secs = run(py + [os.path.join(HERE, "module_audit.py"), "--quiet", "--json", os.path.join(out, "modules.json"),
                               "--md", os.path.join(out, "modules.md")], os.path.join(out, "modules.log"))
        res = json.load(open(os.path.join(out, "modules.json"), encoding="utf-8"))
        err = collections.Counter((f["module"], f["check"]) for f in res if f["severity"] == "error")
        mods = sorted({f["module"] for f in res} | {m for m, _ in err})
        rows.append(("Module data audit", "pass" if not err else "FAIL",
                     f"{sum(err.values())} errors, {sum(f['severity'] == 'warn' for f in res)} warnings", secs))
        checks = sorted({c for _, c in err})
        table = ["| Module | " + " | ".join(checks) + " |", "|---|" + "---|" * len(checks)]
        for m in mods:
            table.append(f"| {m} | " + " | ".join(str(err.get((m, c), "")) or "·" for c in checks) + " |")
        sections.append("## Module audit (errors per check)\n\nDetail: [modules.md](modules.md)\n\n" + "\n".join(table) + "\n")

    if "evolutions" in stages:
        code, secs = run(py + [os.path.join(HERE, "evolution_crawl.py"), "--quiet", "--out", out],
                         os.path.join(out, "evolutions.log"))
        res = json.load(open(os.path.join(out, "evolution_crawl.json"), encoding="utf-8"))
        tally = collections.Counter(r["result"] for r in res)
        bad = tally["impossible"] + tally["not met"] + tally["error"]
        rows.append(("Evolution crawl", "pass" if not bad else "FAIL",
                     f"{len(res)} routes: " + ", ".join(f"{k} {v}" for k, v in sorted(tally.items())), secs))
        sections.append("## Evolution crawl (MOD-19)\n\nDetail: [evolution_crawl.md](evolution_crawl.md)\n\n" +
                        f"{tally['achieved']} of {len(res)} routes taken by the game's own evolution; "
                        f"{tally['impossible']} impossible, {tally['not met']} not met, {tally['shadowed']} shadowed, "
                        f"{tally['partner elsewhere']} with the partner on another device.\n")

    if "collection" in stages:
        code, secs = run(py + [os.path.join(HERE, "collection_crawl.py"), "--quiet", "--out", out],
                         os.path.join(out, "collection.log"))
        res = json.load(open(os.path.join(out, "collection_crawl.json"), encoding="utf-8"))
        ways = collections.Counter(x["way"] for r in res for x in r["items"] + r["cards"])
        none = ways["none"]
        rows.append(("Items and cards", "pass" if not none else "FAIL",
                     ", ".join(f"{k} {v}" for k, v in sorted(ways.items())), secs))
        sections.append("## Items and cards (obtainable)\n\nDetail: [collection_crawl.md](collection_crawl.md)\n\n" +
                        f"{none} item(s) or card(s) nobody can get; {ways['connection']} only with another "
                        f"device, {ways['physical']} only with a physical card, {ways['left out']} left out "
                        "on purpose.\n")

    if "care" in stages:
        code, secs = run(py + [os.path.join(HERE, "care_crawl.py"), "--quiet", "--out", out],
                         os.path.join(out, "care.log"))
        res = json.load(open(os.path.join(out, "care_crawl.json"), encoding="utf-8"))
        tally = collections.Counter(r["result"] for r in res)
        bad = tally["fail"] + tally["error"]
        rows.append(("Care crawl", "pass" if not bad else "FAIL",
                     ", ".join(f"{k} {v}" for k, v in sorted(tally.items()) if k != "info"), secs))
        sections.append("## Care crawl (MOD-21)\n\nDetail: [care_crawl.md](care_crawl.md)\n\n" +
                        ("\n".join(f"- {r['module']} {r['area']} / {r['check']}: {r['detail']}"
                                   for r in res if r["result"] in ("fail", "error"))
                         or "Every module's lifespan rule, sickness and injury behave as it declares.") + "\n")

    if "editor" in stages:
        edir = os.path.join(out, "editor")
        code, secs = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                          os.path.join(HERE, "editor_report.ps1"), "-OutDir", edir], os.path.join(out, "editor.log"))
        try:
            res = json.load(open(os.path.join(edir, "editor_report.json"), encoding="utf-8-sig"))
            res = res if isinstance(res, list) else [res]
        except (OSError, ValueError):
            res = []
        bad = [r for r in res if r["load_errors"] or r["errors"]]
        rows.append(("Module Editor load + report", "pass" if res and not bad else "FAIL",
                     f"{len(res)} modules, {len(bad)} with load or report errors", secs))
        lines = []
        for r in bad:
            lines += [f"- **{r['module']}**: " + "; ".join(r["load_errors"] + [l.strip() for l in r["error_lines"]])]
        sections.append("## Module Editor\n\nReports: `editor/<MODULE>.txt`\n\n" + ("\n".join(lines) or "No errors.") + "\n")

    if "scenes" in stages:
        code, secs = run(py + [os.path.join(HERE, "scene_sweep.py"), "--json", os.path.join(out, "scenes.json"),
                               "--md", os.path.join(out, "scenes.md")], os.path.join(out, "scenes.log"))
        res = json.load(open(os.path.join(out, "scenes.json"), encoding="utf-8"))
        bad = [r for r in res if r["enter"] != "ok" or r["paint"] != "ok" or r.get("error")]
        rows.append(("Scene sweep", "pass" if not bad else "FAIL",
                     f"{len(res)} scene x resolution runs, {len(bad)} failed to enter/paint", secs))
        sections.append("## Scenes\n\nDetail: [scenes.md](scenes.md)\n\n" +
                        ("\n".join(f"- {r['scene']} @ {r['res']}: {r['enter'] if r['enter'] != 'ok' else r['paint']}" for r in bad)
                         or "Every scene enters and paints the whole canvas at every resolution.") + "\n")

    if "crawl" in stages:
        code, secs = run(py + [os.path.join(HERE, "menu_crawl.py"), "--fixture", "all",
                               "--json", os.path.join(out, "crawl.json"),
                               "--md", os.path.join(out, "crawl.md")], os.path.join(out, "crawl.log"))
        res = json.load(open(os.path.join(out, "crawl.json"), encoding="utf-8"))
        kinds = collections.Counter(f["kind"] for r in res for f in r["findings"])
        crashes = kinds.get("crash", 0) + kinds.get("replay", 0)
        modes = sorted({r["mode"] for r in res})
        screens = ", ".join(f"{m} {len({l for r in res if r['mode'] == m for l in r['labels']})}" for m in modes)
        rows.append(("Menu crawl", "pass" if not crashes else "FAIL",
                     f"screens reached: {screens}; {crashes} crashes; review: " +
                     ", ".join(f"{k} {v}" for k, v in sorted(kinds.items()) if k not in ("crash", "replay")), secs))
        dead = sorted({d for r in res for d in r.get("dead_ends", [])})
        sections.append("## Menu crawl\n\nDetail: [crawl.md](crawl.md)\n\n" +
                        (f"Touch dead ends: {', '.join(dead)}\n" if dead else "No touch dead ends.\n"))

    if "tutorial" in stages:
        code, secs = run(py + [os.path.join(HERE, "tutorial_crawl.py"), "--quiet", "--out", out],
                         os.path.join(out, "tutorial.log"))
        res = json.load(open(os.path.join(out, "tutorial_crawl.json"), encoding="utf-8"))
        fail_kinds = ("crash", "stuck", "escape", "end")
        kinds = collections.Counter(f["kind"] for r in res for f in r["findings"])
        played = [r for r in res if r["run"] == "play"]
        clean = sum(r["ended"] == "complete" and not r["assisted"] for r in played)
        rows.append(("Tutorial crawl", "FAIL" if any(kinds[k] for k in fail_kinds) else "pass",
                     f"{clean} of {len(played)} playthroughs unhelped; "
                     + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())), secs))
        where = collections.defaultdict(list)          # (kind, step) -> the runs it happened in
        for r in res:
            for f in r["findings"]:
                if f["kind"] in fail_kinds:
                    where[(f["kind"], f["step"])].append(f"{r['run']} {f['family']} {f['res']} {f['fixture']}")
        fails = [f"- {kind} at {step}: {', '.join(dict.fromkeys(runs))}" for (kind, step), runs in where.items()]
        sections.append("## Tutorial crawl (UI-11)\n\nDetail: [tutorial_crawl.md](tutorial_crawl.md)\n\n" +
                        ("\n".join(fails[:30]) + (f"\n- ... and {len(fails) - 30} more" if len(fails) > 30 else "")
                         if fails else "Every input family plays the tutorial through; fumbles and skips leave "
                         "the game as it was.") + "\n")

    if "validators" in stages:
        code, secs = run(py + [os.path.join(HERE, "device_validators.py"), "--out", os.path.join(out, "validators"),
                               "--json", os.path.join(out, "validators.json")], os.path.join(out, "validators.log"))
        res = json.load(open(os.path.join(out, "validators.json"), encoding="utf-8"))
        broken = [r for r in res if r["status"].startswith(("broken", "timed"))]
        counted = sum(r["findings"] or 0 for r in res)
        rows.append(("Device validators (review)", "pass" if not broken else "FAIL",
                     f"{len(res) - len(broken)} ran ({counted} counted findings to review), {len(broken)} broken", secs))
        sections.append("## Device validators (MOD-16)\n\nOutputs: `validators/<script>.txt`. Findings compare against fan "
                        "sources and are for review.\n\n" +
                        "\n".join(f"- {r['module']} `{r['script']}`: {r['status']}"
                                  + (f", {r['findings']} findings" if r["findings"] is not None else "") for r in res) + "\n")

    if "builds" in stages:
        code, secs = run(py + [os.path.join(HERE, "build_checks.py"), "--json", os.path.join(out, "builds.json")],
                         os.path.join(out, "builds.log"))
        res = json.load(open(os.path.join(out, "builds.json"), encoding="utf-8"))
        errs = [f for f in res["findings"] if f["severity"] == "error"]
        rows.append(("Builds, endpoints, gates, docs", "pass" if not errs else "FAIL",
                     f"version {res['version']}: {len(errs)} errors", secs))
        sections.append("## Builds, endpoints, gates, documentation\n\n" +
                        ("\n".join(f"- {f['check']} {f['subject']}: {f['detail']}" for f in errs) or "No errors.") + "\n")

    if "production" in stages:
        code, secs = run(py + [os.path.join(HERE, "production_probe.py"), "--json", os.path.join(out, "production.json")],
                         os.path.join(out, "production.log"))
        try:
            res = json.load(open(os.path.join(out, "production.json"), encoding="utf-8"))
        except (OSError, ValueError):
            res = {"server": "?", "findings": [{"check": "ARN-09", "severity": "error", "subject": "probe",
                                                "detail": "did not run (see production.log)"}]}
        errs = [f for f in res["findings"] if f["severity"] == "error"]
        rows.append(("Production server (read-only)", "pass" if not errs else "FAIL",
                     f"{res['server']}: {len(errs)} errors", secs))
        sections.append("## Production server (ARN-09, MOD-17)\n\n" +
                        ("\n".join(f"- {f['check']} {f['subject']}: {f['detail']}" for f in errs) or "No errors.") + "\n")

    # Each stage keeps its own row, so a later --only rerun into the same
    # folder updates the summary instead of replacing it.
    names = {"Automated tests": "tests", "Module data audit": "modules", "Evolution crawl": "evolutions",
             "Items and cards": "collection", "Care crawl": "care",
             "Module Editor load + report": "editor", "Device validators (review)": "validators",
             "Scene sweep": "scenes", "Menu crawl": "crawl", "Tutorial crawl": "tutorial",
             "Builds, endpoints, gates, docs": "builds",
             "Production server (read-only)": "production"}
    for row, section in zip(rows, sections):
        with open(os.path.join(out, f"stage_{names[row[0]]}.json"), "w", encoding="utf-8") as fh:
            json.dump({"row": row, "section": section,
                       "when": f"{datetime.datetime.now():%Y-%m-%d %H:%M}"}, fh, ensure_ascii=False)
    rows, sections = [], []
    for stage in STAGES:
        path = os.path.join(out, f"stage_{stage}.json")
        if os.path.isfile(path):
            saved = json.load(open(path, encoding="utf-8"))
            rows.append(tuple(saved["row"]))
            sections.append(saved["section"])
    head = [f"# Release checks {datetime.datetime.now():%Y-%m-%d %H:%M}", "",
            "Automated stages of [the release checklist](../../../docs/release-checklist.md). "
            "Manual items are tracked in the checklist itself.", "",
            "| Stage | Result | Summary | Time |", "|---|---|---|---|"]
    head += [f"| {a} | {'✅ pass' if b == 'pass' else '❌ FAIL'} | {c} | {d}s |" for a, b, c, d in rows]
    with open(os.path.join(out, "summary.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(head) + "\n\n" + "\n".join(sections))
    for a, b, c, d in rows:
        print(f"{b:5} {a:32} {c} ({d}s)")
    print("report:", os.path.join(out, "summary.md"))
    sys.exit(0 if all(b == "pass" for _, b, _, _ in rows) else 1)


if __name__ == "__main__":
    main()
