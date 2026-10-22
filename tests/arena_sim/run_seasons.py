# -*- coding: utf-8 -*-
"""Run whole arena seasons with simulated players and check everything.

    python -B tests/arena_sim/run_seasons.py --server-python <py3.11+ with Omninet deps>
    python -B tests/arena_sim/run_seasons.py --seasons 2 --game-players 1   # a short run

Starts (or reuses) a local Omninet on port 8765 against the database its
.env names, opens each season of ``scenarios.SCENARIOS`` with the dev tools,
and lets 5-10 players play it: API players (``players.SimPlayer``) and up to
three real game instances (``game_player.py``, one process each). Seasons
run on compressed days (``day_minutes``) and are closed by the season clock
when their time is up. Everything a player can see is checked against the
server and against the game's own engine; the findings go to
``tmp/arena_sim/<run>/report.md`` (and report.json, screenshots in shots/).
"""
import argparse
import json
import os
import queue
import random
import statistics
import subprocess
import sys
import threading
import time
import traceback
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import simlib  # noqa: E402
from simlib import Dev, Server, log, parse_time, utcnow, write_json  # noqa: E402
from scenarios import DEFAULT_PROBES, SCENARIOS  # noqa: E402


# ---------------------------------------------------------------------------
# Game instances
# ---------------------------------------------------------------------------

class GameProc:
    """A game_player.py process: one command at a time, JSON lines."""

    def __init__(self, account, run_dir, seed):
        self.account = account
        self.nickname = account["nickname"]
        self.kind = "game"
        self.team = None
        self.history = []
        env = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy",
                   OMNIPET_OMNINET_URL=simlib.URL, ARENA_SIM_URL=simlib.URL,
                   PYTHONIOENCODING="utf-8")
        self.stderr = open(os.path.join(run_dir, f"{self.nickname}.stderr.log"), "w",
                           encoding="utf-8")
        self.proc = subprocess.Popen(
            [sys.executable, "-B", os.path.join(HERE, "game_player.py")],
            cwd=simlib.ROOT, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=self.stderr, text=True, encoding="utf-8", bufsize=1)
        self.lines = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()
        self.lock = threading.Lock()
        self.boot = self.call("boot", device_key=account["device_key"], nickname=self.nickname,
                              seed=seed, shots=os.path.join(run_dir, "shots"), timeout=600)

    def _pump(self):
        for line in self.proc.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def call(self, cmd, timeout=900, **kwargs):
        with self.lock:
            self.proc.stdin.write(json.dumps(dict(kwargs, cmd=cmd)) + "\n")
            self.proc.stdin.flush()
            end = time.monotonic() + timeout
            while True:
                try:
                    line = self.lines.get(timeout=max(1, end - time.monotonic()))
                except queue.Empty:
                    return {"ok": False, "error": f"{cmd} timed out"}
                if line is None:
                    return {"ok": False, "error": f"game process exited during {cmd}"}
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    return json.loads(line)
                except ValueError:
                    continue

    def close(self):
        try:
            self.call("quit", timeout=30)
        except Exception:  # pylint: disable=broad-except
            pass
        try:
            self.proc.wait(20)
        except subprocess.TimeoutExpired:
            self.proc.kill()


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

class Checks:
    """Named pass/fail counters with the first few failures kept."""

    def __init__(self):
        self.passed = Counter()
        self.failed = Counter()
        self.examples = defaultdict(list)
        self.lock = threading.Lock()

    def check(self, name, ok, detail=None):
        with self.lock:
            if ok:
                self.passed[name] += 1
            else:
                self.failed[name] += 1
                if len(self.examples[name]) < 6:
                    self.examples[name].append(detail)
        return ok

    def summary(self):
        names = sorted(set(self.passed) | set(self.failed))
        return [{"check": n, "passed": self.passed[n], "failed": self.failed[n],
                 "examples": self.examples.get(n, [])} for n in names]


#: The engine seeds the global ``random`` module (the server runs every
#: battle in its own process); reruns from several player threads at once
#: must not interleave their draws.
_ENGINE_LOCK = threading.Lock()


def verify_battle(checks, battle, my_team_id, config, prev_remaining, remaining):
    """One battle a player just fought: the stored log replays exactly."""
    from battle.arena import engine, replay
    log_ = battle.get("battle_log") or {}
    ok_version = checks.check("battle log is replayable (v2)", log_.get("version") == 2,
                              battle.get("id"))
    if not ok_version:
        return None
    attacker, defender = log_["attacker"]["pets"], log_["defender"]["pets"]
    with _ENGINE_LOCK:
        rerun = engine.run_battle(attacker, defender, log_["seed"], log_.get("rules") or {})
    same = (rerun["winner"] == log_["winner"]
            and rerun["result"]["device1_final"] == log_["result"]["device1_final"]
            and rerun["result"]["device2_final"] == log_["result"]["device2_final"])
    checks.check("server battle == game engine rerun (seed)", same,
                 {"battle": battle.get("id"), "server": log_["winner"], "game": rerun["winner"]})
    for seat in (True, False):
        try:
            replay.viewer_side(log_, seat)
            checks.check("replay opens from both seats", True)
        except Exception as exc:  # pylint: disable=broad-except
            checks.check("replay opens from both seats", False, repr(exc))
    result = battle.get("result")
    expected = {"team1_win": config["win_score"], "team2_win": config["loss_score"],
                "draw": config["draw_score"]}[result]
    checks.check("attacker score change follows the season", battle.get("team1_score_change") == expected,
                 {"result": result, "got": battle.get("team1_score_change"), "want": expected})
    expected2 = {"team1_win": config["loss_score"], "team2_win": config["win_score"],
                 "draw": config["draw_score"]}[result]
    checks.check("defender score change follows the season", battle.get("team2_score_change") == expected2,
                 {"result": result, "got": battle.get("team2_score_change"), "want": expected2})
    checks.check("attacker is team1", str(battle.get("team1_id")) == str(my_team_id))
    if prev_remaining is not None and remaining is not None:
        checks.check("an attack uses one of the day's allowance", remaining == prev_remaining - 1,
                     {"before": prev_remaining, "after": remaining})
    return result


def fairness(battles, teams_by_id, day_minutes, season_start):
    """Matchmaking spread.

    Rotation (exact): every attack goes to a team the attacker had attacked
    least that day -- one player's attacks are sequential, so nothing can
    race it. Spread (reported): defences per team over the season, and how
    often a pick among the least-attacked was not the least defended that
    day (players attack in parallel, so this one can race).
    """
    battles = sorted(battles, key=lambda b: b["fought_at"])
    violations, spread_misses, examples = 0, 0, []
    attacks_day = defaultdict(Counter)    # (attacker, day) -> Counter(defender)
    defended_day = defaultdict(Counter)   # day -> Counter(defender)
    defended = Counter()

    def day_of(b):
        return int((b["fought_at"] - season_start).total_seconds() // (day_minutes * 60))

    for b in battles:
        att, dfd = b["team1_id"], b["team2_id"]
        day = day_of(b)
        owner = teams_by_id[att]["owner"]
        candidates = [t for t, info in teams_by_id.items()
                      if t != att and info["owner"] != owner
                      and info["registered"] <= b["fought_at"]]
        if candidates:
            mine = attacks_day[(att, day)]
            least = min(mine[c] for c in candidates)
            if mine[dfd] != least:
                violations += 1
                if len(examples) < 5:
                    examples.append({"attacker": teams_by_id[att]["nickname"],
                                     "picked": teams_by_id[dfd]["nickname"],
                                     "attacked_today": mine[dfd], "least": least})
            else:
                tied = [c for c in candidates if mine[c] == least]
                if defended_day[day][dfd] != min(defended_day[day][c] for c in tied):
                    spread_misses += 1
        attacks_day[(att, day)][dfd] += 1
        defended_day[day][dfd] += 1
        defended[dfd] += 1
    defences = [defended[t] for t in teams_by_id]
    return {
        "battles": len(battles),
        "rotation_violations": violations,
        "spread_misses": spread_misses,
        "rotation_examples": examples,
        "defences_min": min(defences) if defences else 0,
        "defences_max": max(defences) if defences else 0,
        "defences_stdev": round(statistics.pstdev(defences), 2) if len(defences) > 1 else 0,
        "defences_by_team": {teams_by_id[t]["nickname"]: defended[t] for t in teams_by_id},
    }


# ---------------------------------------------------------------------------
# The simulation
# ---------------------------------------------------------------------------

class Simulation:
    def __init__(self, args):
        self.args = args
        self.rng = random.Random(args.seed)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.run_dir = os.path.join(simlib.TMP, f"run-{stamp}")
        os.makedirs(os.path.join(self.run_dir, "shots"), exist_ok=True)
        self.checks = Checks()
        self.report = {"started": utcnow().isoformat(), "seasons": [], "args": vars(args)}
        self.dev = Dev()
        self.server = None
        self.players = []
        self.games = []

    # ------------------------------------------------------------ setup
    def setup(self):
        self.server = Server(os.path.join(self.run_dir, "server.log"),
                             python=self.args.server_python).start()
        status = self.dev.status()
        if not status.get("runtime"):
            raise SystemExit("The server has no arena runtime: build one with "
                             "utilities/claude/build_arena_runtime.py --to <storage>/updates")
        self.report["runtime"] = status["runtime"]
        log("runtime", status["runtime"]["version"], "modules", len(status["runtime"]["modules"]))

        from harness import Env
        self.env = Env("240x240", network=simlib.network_mode())
        with __import__("harness").quiet():
            self.env.reset()

        api_accounts = self.dev.accounts(self.args.api_players, "simplayer", coins=100)
        game_accounts = self.dev.accounts(self.args.game_players, "simgame", coins=100)
        from players import SimPlayer, STYLES
        for i, acc in enumerate(api_accounts):
            self.players.append(SimPlayer(acc, random.Random(self.rng.random()), STYLES[i % len(STYLES)]))
        for i, acc in enumerate(game_accounts):
            log("starting game instance", acc["nickname"])
            proc = GameProc(acc, self.run_dir, seed=self.rng.randrange(10 ** 6))
            if not proc.boot.get("ok"):
                raise SystemExit(f"game instance failed to boot: {proc.boot}")
            self.games.append(proc)
        self.coins = {}
        for acc in api_accounts + game_accounts:
            self.coins[acc["nickname"]] = 100
        # Results an earlier run left unclaimed: claim them now so every
        # season's coins start from a known balance.
        for p in self.players:
            ok, data = p.svc.claim_team_rewards()
            if ok and isinstance(data, dict) and data.get("new_balance") is not None:
                self.coins[p.nickname] = int(data["new_balance"])

    def server_modules(self):
        code, data = self.dev.get("/arena/modules")
        return [m["name"] for m in (data or {}).get("modules", [])] if code == 200 else []

    # ------------------------------------------------------------ one season
    def run_season(self, index, sc):
        day_minutes = self.args.day_minutes
        days = sc["days"] if not self.args.quick else 1
        length = days * day_minutes
        config = dict(sc.get("config") or {}, day_minutes=day_minutes)
        log(f"=== season {index + 1}: {sc['name']} ({sc['players']} players, {days} days)")
        started = self.dev.start_season(sc["name"], length, sc.get("restrictions"), config,
                                        sc.get("reward_multiplier", 1.0))
        season = started["season"]
        season_id = season["id"]
        cfg = season["config"]
        rep = {"name": sc["name"], "id": season_id, "restrictions": season.get("restrictions"),
               "config": cfg, "reward_multiplier": season.get("reward_multiplier"),
               "starts_at": season["starts_at"], "ends_at": season["ends_at"],
               "registrations": [], "attacks": Counter(), "results": Counter(),
               "game": defaultdict(list)}
        self.checks.check("season opens with the asked config",
                          all(cfg.get(k) == v for k, v in (sc.get("config") or {}).items()
                              if k != "team_size")
                          and (sc.get("config", {}).get("team_size") is None
                               or cfg["min_team_size"] == cfg["max_team_size"] == sc["config"]["team_size"]),
                          {"asked": sc.get("config"), "got": cfg})
        server_modules = self.server_modules()
        self.checks.check("unpublished modules are not offered", "IC" not in server_modules,
                          server_modules)
        from players import Catalog
        catalog = Catalog(server_modules, unpublished=["IC"])

        n_games = min(len(self.games), max(0, sc["players"] - 2), self.args.games_per_season)
        games = self.games[:n_games]
        api = self.rng.sample(self.players, min(len(self.players), sc["players"] - n_games))
        participants = api + games
        rep["participants"] = [p.nickname for p in participants]

        # -- registration ---------------------------------------------------
        probes = list(DEFAULT_PROBES)
        self.rng.shuffle(probes)

        def register_api(i_p):
            i, p = i_p
            mine = [probes[i]] if i < len(probes) else []
            try:
                return p.register(season, catalog, set(server_modules), mine)
            except Exception as exc:  # pylint: disable=broad-except
                return {"player": p.nickname, "error": repr(exc), "trace": traceback.format_exc()}

        def register_game(g):
            from scenes.connect_views.arena_team_creation_view import team_size_range
            low, high = team_size_range(season)
            size = high if self.rng.random() < 0.7 else self.rng.randint(low, high)
            from players import DRIFTED
            prep = g.call("prepare", season=season, server_modules=server_modules, size=size,
                          exclude=sorted(DRIFTED))
            made = g.call("create_team", size=size)
            res = (made.get("result") or {})
            drifted = []
            for _ in range(2):
                error = str(res.get("error") or "")
                marker = " does not match the server's "
                if res.get("ok") or marker not in error:
                    break
                # The checkout's data for this species is not the server's
                # (an unpublished edit): the player puts the pet away.
                name = error.split(marker)[0].strip()
                module = error.split(marker)[1].split(" data")[0].strip()
                party = (prep.get("result") or {}).get("party_species") or []
                hits = [tuple(x) for x in party if x[0] == module and x[1] == name]
                DRIFTED.update(hits)
                drifted.extend(f"{m}/{n} v{v}" for m, n, v in hits)
                if not hits:
                    break
                prep = g.call("prepare", season=season, server_modules=server_modules,
                              size=size, exclude=sorted(DRIFTED))
                made = g.call("create_team", size=size)
                res = (made.get("result") or {})
            g.team = {"id": None}
            if made.get("ok") and res.get("ok"):
                g.team = {"id": "?"}
            return {"player": g.nickname, "kind": "game", "size": size, "drifted": drifted,
                    "prepare": prep.get("result"), "create": res, "error_logs": made.get("error_logs"),
                    "error": None if (made.get("ok") and res.get("ok")) else (res.get("error") or made.get("error"))}

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(register_api, (i, p)) for i, p in enumerate(api)]
            futures += [pool.submit(register_game, g) for g in games]
            regs = [f.result() for f in futures]
        rep["registrations"] = regs
        for r in regs:
            for probe in r.get("probes", []):
                if "skipped" in probe:
                    continue
                self.checks.check(f"probe refused: {probe['probe']}", probe.get("refused"), probe)
                self.checks.check(f"probe says why: {probe['probe']}", probe.get("matches"), probe)
            self.checks.check("registration succeeds", not r.get("error"),
                              {"player": r.get("player"), "error": r.get("error")})
            if r.get("kind") == "game":
                c = r.get("create") or {}
                if c.get("ok"):
                    self.checks.check("UI: freezer locks the team", all(c.get("locked") or [False]), c)
                    self.checks.check("UI: confirm warns about the lock",
                                      "Locks" in (c.get("confirm_warning") or ""), c.get("confirm_warning"))
                    self.checks.check("UI: hub announces the team",
                                      "Team registered" in (c.get("notice") or ""), c.get("notice"))
                    self.checks.check("UI: team slots follow the season size",
                                      c.get("slots") == cfg["max_team_size"], c.get("slots"))
                    if c.get("refused_tap"):
                        self.checks.check("UI: picker explains a refused pet",
                                          bool(c.get("refused_tap")) and "Pick" not in c["refused_tap"],
                                          c.get("refused_tap"))
                self.checks.check("UI: no error logs", not r.get("error_logs"), r.get("error_logs"))

        # Learn the game instances' team ids from the server.
        for g in games:
            code, teams = self.dev.get("/teams/current", {"X-Device-Key": g.account["device_key"]})
            g.team = teams if code == 200 else None
        registered = [p for p in participants if p.team and p.team.get("id") not in (None, "?")]
        rep["teams"] = len(registered)
        log(f"registered {len(registered)}/{len(participants)} teams")

        # -- days of battles ------------------------------------------------
        season_start = parse_time(season["starts_at"])
        ends_at = parse_time(season["ends_at"])
        for day in range(days):
            day_end = season_start + timedelta(minutes=day_minutes * (day + 1))
            self.play_day(day, day_end, registered, api, games, cfg, rep)
            if day < days - 1:
                self.sleep_until(day_end + timedelta(seconds=1))

        # -- the clock closes the season ----------------------------------------
        self.sleep_until(ends_at + timedelta(milliseconds=300))
        tick = self.dev.tick()
        rep["close_report"] = tick.get("report")
        code, s = self.dev.get(f"/seasons/{season_id}")
        closed_ok = code == 200 and s.get("status") == "completed"
        if not closed_ok:
            for _ in range(10):
                time.sleep(2)
                code, s = self.dev.get(f"/seasons/{season_id}")
                if s and s.get("status") == "completed":
                    closed_ok = True
                    break
        self.checks.check("the clock closes the season at its end", closed_ok, s)
        # The simulation's server (its 5-second clock or the tick above)
        # writes the podium; the deployed dev server's older clock does not.
        code, podium = self.dev.get(f"/seasons/{season_id}/winners")
        code_t, table = self.dev.get(f"/seasons/{season_id}/standings?limit=200")
        anyone_fought = any(r["wins"] + r["losses"] + r["draws"] for r in (table or []))
        rep["closed_by_local_clock"] = bool(podium) or not anyone_fought
        self.verify_close(season, registered, api, games, cfg, rep)
        return rep

    def sleep_until(self, moment):
        while True:
            left = (moment - utcnow()).total_seconds()
            if left <= 0:
                return
            time.sleep(min(left, 5))

    def play_day(self, day, day_end, registered, api, games, cfg, rep):
        allowance = cfg["attacks_per_day"]
        deadline = day_end - timedelta(seconds=8)

        def api_day(p):
            if not p.team or p.team.get("id") in (None, "?"):
                return []
            out = []
            want = allowance if self.rng.random() < 0.6 else self.rng.randint(1, allowance)
            prev = None
            for _ in range(want):
                if utcnow() > deadline:
                    break
                res = p.attack()
                if not res["ok"]:
                    out.append({"player": p.nickname, "fail": res.get("message")})
                    if "No opponent" in str(res.get("message")):
                        break
                    self.checks.check("attack within the allowance is accepted", False,
                                      {"player": p.nickname, "message": res.get("message")})
                    break
                result = verify_battle(self.checks, res["battle"], p.team["id"], cfg, prev,
                                       res.get("remaining"))
                prev = res.get("remaining")
                rep["attacks"][p.nickname] += 1
                rep["results"][result] += 1
                out.append({"player": p.nickname, "result": result})
            if want == allowance and utcnow() < deadline:
                extra = p.attack()
                self.checks.check("an attack past the allowance is refused", not extra["ok"]
                                  and "No attacks left" in str(extra.get("message")), extra.get("message"))
            return out

        def game_day(g):
            if not g.team or g.team.get("id") in (None, "?"):
                return {}
            out = {}
            times = min(self.args.game_attacks, allowance)
            att = g.call("attack", times=times)
            out["attack"] = att
            for a in (att.get("result") or {}).get("attacks", []):
                if not a.get("ok"):
                    self.checks.check("UI: FIND BATTLE plays a battle", False, a)
                    continue
                rep["attacks"][g.nickname] += 1
                self.checks.check("UI: replay reaches the result", a.get("played"), a)
                self.checks.check("UI: replay ends on the server's HP", a.get("hp_ok"), a)
                self.checks.check("UI: replay verdict matches the server", a.get("verdict_ok"), a)
                self.checks.check("UI: replay returns to the hub by itself", a.get("returned_by_itself"), a)
                self.checks.check("UI: hub shows the battle result",
                                  any(w in (a.get("notice") or "") for w in ("WIN", "LOSS", "DRAW")),
                                  a.get("notice"))
            self.checks.check("UI: no error logs", not att.get("error_logs"), att.get("error_logs"))
            if day == 0:
                out["rules"] = g.call("rules")
                out["ranks"] = g.call("ranks")
                r = (out["ranks"].get("result") or {})
                self.checks.check("UI: ranks list the player's own row", bool(r.get("mine")), r)
            hist = g.call("history", watch_role="defense" if day % 2 == 0 else "attack")
            out["history"] = hist
            h = hist.get("result") or {}
            if h.get("watched") and not h["watched"].get("error"):
                w = h["watched"]
                self.checks.check(f"UI: {w.get('role')} replay from history ends on the server's HP",
                                  w.get("hp_ok"), w)
                self.checks.check("UI: replay from history returns to history",
                                  w.get("back_to") == "arena_history", w)
            elif h.get("watched"):
                self.checks.check("UI: history replay opens", False, h["watched"])
            self.checks.check("UI: no error logs", not hist.get("error_logs"), hist.get("error_logs"))
            return out

        with ThreadPoolExecutor(max_workers=self.args.workers) as pool:
            fut_api = [pool.submit(api_day, p) for p in api]
            fut_game = [pool.submit(game_day, g) for g in games]
            api_out = [f.result() for f in fut_api]
            game_out = [f.result() for f in fut_game]
        for g, out in zip(games, game_out):
            rep["game"][g.nickname].append({"day": day, **{k: _trim(v) for k, v in out.items()}})
        log(f"day {day + 1}: {sum(len(o) for o in api_out)} API attacks, "
            f"{sum(len(((o.get('attack') or {}).get('result') or {}).get('attacks', [])) for o in game_out)} game attacks")

    # ------------------------------------------------------------ the close
    def verify_close(self, season, registered, api, games, cfg, rep):
        season_id = season["id"]
        mult = float(season.get("reward_multiplier") or 1.0)
        code, table = self.dev.get(f"/seasons/{season_id}/standings?limit=200")
        table = table if code == 200 else []
        rep["standings"] = table
        ranks = [r["rank"] for r in table]
        self.checks.check("final ranks are 1..N", ranks == list(range(1, len(table) + 1)), ranks)
        fought = [r for r in table if r["wins"] + r["losses"] + r["draws"] > 0]
        self.checks.check("teams that fought rank first",
                          table[:len(fought)] == fought, [r["nickname"] for r in table])
        order_ok = all((a["score"], a["wins"]) >= (b["score"], b["wins"])
                       for a, b in zip(fought, fought[1:]))
        self.checks.check("ranks follow score then wins", order_ok,
                          [(r["nickname"], r["score"], r["wins"]) for r in fought])
        code, winners = self.dev.get(f"/seasons/{season_id}/winners")
        winners = winners if code == 200 else []
        rep["winners"] = winners
        prizes = cfg.get("rank_prizes") or []
        if rep.get("closed_by_local_clock"):
            podium = max(3, len(prizes))
            want = min(podium, len(fought))
            self.checks.check("winners keep the podium", len(winners) == want,
                              {"winners": len(winners), "want": want})
            for w in winners:
                prize = int(round(prizes[w["rank"] - 1] * mult)) if w["rank"] <= len(prizes) else 0
                self.checks.check("winner prize follows the season's rank prizes",
                                  w["prize_coins"] == prize, w)
                self.checks.check("winner rank matches the table",
                                  table[w["rank"] - 1]["nickname"] == w["nickname"], w)
        else:
            rep["note"] = "closed by another server's clock (deployed dev server)"

        # Every player: final team, coins, claim, records.
        battles_by_id = {}
        teams_by_id = {}
        for p in registered:
            key = p.account["device_key"] if hasattr(p, "account") else p.key
            headers = {"X-Device-Key": key}
            code, team = self.dev.get(f"/teams/{p.team['id']}", headers)
            if code != 200:
                self.checks.check("finished team readable", False, team)
                continue
            total = team["wins"] + team["losses"] + team["draws"]
            prize = 0
            if team.get("final_rank") and team["final_rank"] <= len(prizes) and total > 0:
                prize = int(round(prizes[team["final_rank"] - 1] * mult))
            coins_want = total * cfg["participation_coins"] + prize
            if rep.get("closed_by_local_clock"):
                self.checks.check("team coins = participation + rank prize",
                                  team["rewarded_coins"] == coins_want,
                                  {"player": p.nickname, "got": team["rewarded_coins"], "want": coins_want,
                                   "rank": team.get("final_rank"), "battles": total})
            self.checks.check("every pet carries the team's record",
                              all(pet["battles"] == total and pet["wins"] == team["wins"]
                                  and pet["losses"] == team["losses"] for pet in team["pets"]),
                              {"player": p.nickname, "team": [team["wins"], team["losses"], team["draws"]],
                               "pets": [[x["battles"], x["wins"]] for x in team["pets"]]})
            self.checks.check("the full pet JSON stays on the server",
                              all("pet_json" not in (x.get("extra_data") or {}) for x in team["pets"]))
            code, hist = self.dev.get(f"/battles/team/{p.team['id']}/history", headers)
            for b in (hist or {}).get("battles", []):
                pass
            teams_by_id[p.team["id"]] = {"nickname": p.nickname, "owner": p.nickname,
                                         "registered": parse_time(team["created_at"])}
            p.final_team = team

        # All battles of the season (attacks of every team).
        for p in registered:
            key = p.account["device_key"] if hasattr(p, "account") else p.key
            code, hist = self.dev.get(f"/battles/team/{p.team['id']}/history", {"X-Device-Key": key})
            for b in (hist or {}).get("battles", []):
                if b["role"] == "attack":
                    battles_by_id[b["id"]] = {"team1_id": p.team["id"], "team2_id": b["opponent_team_id"],
                                              "fought_at": parse_time(b["fought_at"])}
        known = [b for b in battles_by_id.values() if b["team2_id"] in teams_by_id]
        rep["fairness"] = fairness(known, teams_by_id, cfg["day_minutes"], parse_time(season["starts_at"]))
        f = rep["fairness"]
        self.checks.check("matchmaking: every team attacked once before anyone twice in a day",
                          f["rotation_violations"] == 0, f["rotation_examples"])

        # Claims (API players) and results screens (game instances).
        for p in [x for x in registered if x.kind == "api"]:
            before = self.coins.get(p.nickname, 0)
            # One claim pays every finished season not claimed yet (a season
            # an interrupted earlier run left behind included).
            _ok, past = p.svc.get_user_teams(include_past=True)
            owed = sum(int(t.get("rewarded_coins") or 0) for t in (past or [])
                       if isinstance(t, dict) and t.get("season_status") == "completed"
                       and not t.get("reward_claimed"))
            ok, data = p.svc.claim_team_rewards()
            team = getattr(p, "final_team", {}) or {}
            if ok:
                self.checks.check("claim pays the team's coins",
                                  data.get("coins_claimed") == owed
                                  and owed >= int(team.get("rewarded_coins") or 0),
                                  {"player": p.nickname, "claimed": data.get("coins_claimed"),
                                   "owed": owed, "team": team.get("rewarded_coins")})
                self.checks.check("claim adds to the balance",
                                  data.get("new_balance") == before + int(data.get("coins_claimed") or 0),
                                  {"player": p.nickname, "before": before, "after": data.get("new_balance")})
                self.coins[p.nickname] = int(data.get("new_balance") or 0)
                ok2, again = p.svc.claim_team_rewards()
                self.checks.check("a second claim pays nothing",
                                  ok2 and int(again.get("coins_claimed") or 0) == 0, again)
            else:
                self.checks.check("claim pays the team's coins", False, data)
            applied = p.apply_results(team)
            self.checks.check("season record goes onto the pets",
                              len(applied) == len(team.get("pets") or []) and all(
                                  a["battles"] == team["wins"] + team["losses"] + team["draws"]
                                  for a in applied), applied)
            p.team = None
        for g in [x for x in registered if x.kind == "game"]:
            res = g.call("results")
            r = res.get("result") or {}
            rep["game"][g.nickname].append({"results": _trim(r)})
            team = getattr(g, "final_team", {}) or {}
            self.checks.check("UI: SEASON RESULTS offered", r.get("hub_button") == "SEASON RESULTS", r)
            self.checks.check("UI: results claim the coins",
                              r.get("ok") and r.get("coins_after") == r.get("coins_before", 0)
                              + int(team.get("rewarded_coins") or 0), r)
            self.checks.check("UI: pets released after the season", r.get("ok") and not r.get("still_locked")
                              and not r.get("still_pending"), r)
            total = team.get("wins", 0) + team.get("losses", 0) + team.get("draws", 0)
            added = r.get("records_added") or {}
            self.checks.check("UI: pets get the team's battles",
                              len(added) == len(team.get("pets") or [])
                              and all(v[0] == total and v[1] == team.get("wins") for v in added.values()),
                              {"added": added, "team": [team.get("wins"), total]})
            self.checks.check("UI: results leave the hub ready for a new season",
                              r.get("ok") and r.get("hub_after") != "SEASON RESULTS", r)
            self.checks.check("UI: no error logs", not res.get("error_logs"), res.get("error_logs"))
            g.team = None

        # Between seasons: some veterans evolve, so they may come back.
        evolved = []
        for p in api:
            evolved += p.evolve_some()
        for g in games:
            evolved += (g.call("evolve").get("result") or {}).get("evolved", [])
        rep["evolved"] = evolved

    # ------------------------------------------------------------ report
    def finish(self):
        for g in self.games:
            g.close()
        self.report["finished"] = utcnow().isoformat()
        self.report["checks"] = self.checks.summary()
        write_json(os.path.join(self.run_dir, "report.json"), self.report)
        with open(os.path.join(self.run_dir, "report.md"), "w", encoding="utf-8") as f:
            f.write(markdown(self.report))
        log("report:", os.path.join(self.run_dir, "report.md"))


def _trim(value, depth=0):
    if isinstance(value, dict):
        return {k: _trim(v, depth + 1) for k, v in value.items() if k not in ("trace",)}
    if isinstance(value, list):
        return [_trim(v, depth + 1) for v in value[:30]]
    if isinstance(value, str) and len(value) > 600:
        return value[:600] + "..."
    return value


def markdown(report):
    lines = ["# Arena season simulation", "",
             f"Started {report['started']}, finished {report.get('finished')}. "
             f"Runtime {report.get('runtime', {}).get('version')}.", ""]
    lines += ["## Seasons", "",
              "| # | Season | Rules | Teams | Battles | W/L/D (attacker) | Winner | Fairness (defences min-max, rotation misses) |",
              "|---|---|---|---|---|---|---|---|"]
    for i, s in enumerate(report["seasons"], start=1):
        if "error" in s:
            lines.append(f"| {i} | {s.get('name')} | ERROR | | | | | {s['error'][:120]} |")
            continue
        cfg = s.get("config") or {}
        rules = []
        if s.get("restrictions"):
            rules.append(", ".join(f"{k.replace('allowed_', '')}={v}" for k, v in s["restrictions"].items()))
        rules.append(f"size {cfg.get('min_team_size')}-{cfg.get('max_team_size')}")
        rules.append(f"{cfg.get('attacks_per_day')}/day, charge {cfg.get('charge')}")
        if s.get("reward_multiplier", 1) != 1:
            rules.append(f"x{s['reward_multiplier']} prizes")
        res = s.get("results") or {}
        top = (s.get("winners") or [{}])[0]
        f = s.get("fairness") or {}
        lines.append(
            f"| {i} | {s['name']} | {'; '.join(rules)} | {s.get('teams')} | {f.get('battles')} | "
            f"{res.get('team1_win', 0)}/{res.get('team2_win', 0)}/{res.get('draw', 0)} | "
            f"{top.get('nickname', '-')} ({top.get('score', '-')} pts, {top.get('prize_coins', '-')} c) | "
            f"{f.get('defences_min')}-{f.get('defences_max')}, {f.get('rotation_violations')} "
            f"(spread misses {f.get('spread_misses')}) |")
    lines += ["", "## Checks", "", "| Check | Passed | Failed |", "|---|---|---|"]
    for c in report.get("checks", []):
        lines.append(f"| {c['check']} | {c['passed']} | {c['failed']} |")
    failed = [c for c in report.get("checks", []) if c["failed"]]
    if failed:
        lines += ["", "## Failures (first examples)", ""]
        for c in failed:
            lines.append(f"### {c['check']}")
            for ex in c["examples"]:
                lines.append(f"- `{json.dumps(ex, default=str)[:700]}`")
            lines.append("")
    lines += ["", "## Registrations and probes", ""]
    for s in report["seasons"]:
        lines.append(f"### {s.get('name')}")
        for r in s.get("registrations", []):
            probe = "; ".join(f"{p['probe']}: {'refused' if p.get('refused') else p.get('skipped', 'ACCEPTED')}"
                              f" ({(p.get('answer') or '')[:70]})" for p in r.get("probes", []))
            lines.append(f"- {r.get('player')} ({r.get('kind', 'api')}, {r.get('style', '')}) size "
                         f"{r.get('size')}: {r.get('pets') or (r.get('create') or {}).get('pets')}"
                         f"{' ERROR ' + str(r.get('error')) if r.get('error') else ''}"
                         f"{' | data differs from the server (put away): ' + ', '.join(r['drifted']) if r.get('drifted') else ''}"
                         f"{' | probes: ' + probe if probe else ''}")
        if s.get("evolved"):
            lines.append(f"- evolved afterwards: {', '.join(s['evolved'][:20])}")
        lines.append("")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seasons", type=int, default=len(SCENARIOS))
    parser.add_argument("--first", type=int, default=0, help="first scenario index")
    parser.add_argument("--api-players", type=int, default=10)
    parser.add_argument("--game-players", type=int, default=3)
    parser.add_argument("--games-per-season", type=int, default=3)
    parser.add_argument("--game-attacks", type=int, default=2, help="game-instance attacks per day")
    parser.add_argument("--day-minutes", type=int, default=3)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20261016)
    parser.add_argument("--quick", action="store_true", help="one day per season")
    parser.add_argument("--server-python", default=os.environ.get("OMNINET_PYTHON", ""))
    parser.add_argument("--keep-server", action="store_true")
    parser.add_argument("--url", help="a deployed server instead of the local one, "
                                      "e.g. https://dev.omnipet.app.br")
    parser.add_argument("--admin-key-file", help="file holding an admin device key for the "
                                                 "server's dev tools (when it has no dev token)")
    args = parser.parse_args()
    if args.url:
        simlib.URL = args.url.rstrip("/")
        os.environ["ARENA_SIM_URL"] = simlib.URL
    if args.admin_key_file:
        with open(args.admin_key_file, encoding="utf-8") as f:
            simlib.ADMIN_KEY = f.read().strip()

    sim = Simulation(args)
    try:
        sim.setup()
        for i, sc in enumerate(SCENARIOS[args.first:args.first + args.seasons]):
            try:
                sim.report["seasons"].append(sim.run_season(args.first + i, sc))
            except Exception as exc:  # pylint: disable=broad-except
                log("season failed:", repr(exc))
                traceback.print_exc()
                sim.report["seasons"].append({"name": sc["name"], "error": repr(exc),
                                              "trace": traceback.format_exc()})
            sim.report["checks"] = sim.checks.summary()
            write_json(os.path.join(sim.run_dir, "report.partial.json"), sim.report)
    finally:
        sim.finish()
        if sim.server and not args.keep_server and simlib.is_local():
            sim.server.stop()


if __name__ == "__main__":
    main()
