# -*- coding: utf-8 -*-
"""Totals of a simulation run: python -B tests/arena_sim/summarize.py [run folder]."""
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))


def main():
    run = sys.argv[1] if len(sys.argv) > 1 else sorted(
        glob.glob(os.path.join(ROOT, "tmp", "arena_sim", "run-*")))[-1]
    path = os.path.join(run, "report.json")
    if not os.path.exists(path):
        path = os.path.join(run, "report.partial.json")
    report = json.load(open(path, encoding="utf-8"))
    seasons = [s for s in report["seasons"] if "error" not in s]
    battles = sum((s.get("fairness") or {}).get("battles", 0) for s in seasons)
    teams = sum(s.get("teams") or 0 for s in seasons)
    replays = hp_ok = 0
    probes = refused = 0
    for s in seasons:
        for days in (s.get("game") or {}).values():
            for d in days:
                for a in ((d.get("attack") or {}).get("result") or {}).get("attacks", []):
                    if a.get("played") is not None:
                        replays += 1
                        hp_ok += bool(a.get("hp_ok"))
                w = ((d.get("history") or {}).get("result") or {}).get("watched") or {}
                if w.get("played") is not None:
                    replays += 1
                    hp_ok += bool(w.get("hp_ok"))
        for r in s.get("registrations", []):
            for p in r.get("probes", []):
                if "skipped" in p:
                    continue
                probes += 1
                refused += bool(p.get("refused"))
    print(f"run {os.path.basename(run)}: {len(seasons)} seasons ({len(report['seasons']) - len(seasons)} failed), "
          f"{teams} teams, {battles} battles")
    print(f"game-instance replays: {replays} played, {hp_ok} on the server's HP")
    print(f"abuse probes: {probes} tried, {refused} refused")
    for s in seasons:
        f = s.get("fairness") or {}
        top = (s.get("winners") or [{}])[0]
        print(f"  {s['name']:<24} teams {s.get('teams'):>2}  battles {f.get('battles'):>4}  "
              f"defences {f.get('defences_min')}-{f.get('defences_max')}  "
              f"rotation misses {f.get('rotation_violations')}  winner {top.get('nickname')} "
              f"({top.get('score')} pts, {top.get('prize_coins')} coins)")
    checks = report.get("checks") or []
    failed = [c for c in checks if c["failed"]]
    print(f"checks: {sum(c['passed'] for c in checks)} passed, {sum(c['failed'] for c in checks)} failed"
          f" over {len(checks)} kinds")
    for c in failed:
        print(f"  FAILED {c['check']}: {c['failed']}x, e.g. {json.dumps(c['examples'][:1], default=str)[:300]}")


if __name__ == "__main__":
    main()
