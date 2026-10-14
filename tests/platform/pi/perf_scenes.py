#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Frame rate of every scene on the Pi's own display (checklist PERF-01, BLD-03).

Run through perf_scenes.sh on the Pi (it checks the game is not running and
keeps a copy of the output). Boots the game the way tests/release/scene_sweep.py
does (temp save, network refused, the sweep's party), on the real display,
fullscreen at 240x240 unless told otherwise, then holds every scene for
--seconds at the game's own frame pacing: each frame is the game loop's
update, draw, present and clock.tick(configuration.frame_rate).

    python3 perf_scenes.py [--game DIR] [--seconds 5] [--scene game battle ...]
                           [--res 240x240] [--windowed] [--uncapped] [--driver kmsdrm]
                           [--min-fps 29.5] [--dip-fps 27] [--json PATH] [--dummy]

Per scene: fps avg and the worst 1-second window after the first --warmup
second (loading), the longest frame, and the CPU time of a frame (update +
draw + present, without the tick's wait: the headroom). A scene FAILS PERF-01
when its average is under --min-fps (30 fps, less 0.5 for the timer's
millisecond rounding) and DIPS when a 1-second window falls under --dip-fps.
--uncapped skips the tick to measure the most the Pi can draw.
Then the heavy loads (--load-seconds each, 30 s; every pet selected, fed,
awake and with DP): game_crowded (the main game with every pet and a screen
of poop), training_play (a training, --training, played round after round
by every pet: READY, the mashed charge, the attack animation, the result)
and battle_play (an adventure battle, --battle-module area 1, fought round
after round: the mashed charge, the battle animation, the result), each
with its figures per phase. --load, --no-loads, --loads-only choose.
Exit 1 when any scene or load fails to enter or fails PERF-01.
"""
import argparse
import contextlib
import importlib
import io
import json
import os
import sys
import time
import traceback
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pi_common  # noqa: E402


def window_min(stamps, intervals, warmup, span=1.0):
    """Lowest fps over any `span`-second window of frames after `warmup`."""
    pts = [(t, d) for t, d in zip(stamps, intervals) if t >= warmup]
    if len(pts) < 2:
        return None
    best, j, acc = None, 0, 0.0
    for i in range(len(pts)):
        acc += pts[i][1]
        while acc - pts[j][1] >= span and j < i:
            acc -= pts[j][1]
            j += 1
        if acc >= span * 0.95:
            fps = (i - j + 1) / acc
            best = fps if best is None else min(best, fps)
    return best


PROFILE = None      # set by --profile: (top N functions to print)


def profile_lines(pr, frames, top):
    """The functions that took the most of a frame's own time (ms per frame)."""
    import pstats
    stats = pstats.Stats(pr).stats
    rows = sorted(stats.items(), key=lambda kv: kv[1][2], reverse=True)[:top]
    out = []
    for (file, line, func), (cc, nc, tt, ct, _callers) in rows:
        where = func if file == "~" else f"{os.path.basename(file)}:{line} {func}"
        out.append(f"{1000 * tt / max(frames, 1):6.2f} ms own {1000 * ct / max(frames, 1):6.2f} ms total "
                   f"{nc / max(frames, 1):6.1f}/frame  {where}")
    return out


def measure(game, factory, seconds, warmup, rate, uncapped, log, step=None, phase_of=None, party=1):
    """Hold the scene *factory()* builds for *seconds* at the game's pacing.

    *step(frame, scene)*, when given, runs before each frame's update the way
    a player acts (presses, starting the next round) and returns the scene to
    go on with (a new one to restart). *phase_of(scene)* labels each frame
    for the per-phase figures. *party*: how many pets are selected (the scene
    list uses one; the heavy loads, all)."""
    pg, gg, rg = game.pygame, game.gg, game.rg
    from utils import display_utils
    row = {"enter": None, "errors": 0, "error": None, "switch_requests": []}
    rg.INPUT_MODE = rg.KEYBOARD_MODE
    rg.game_state_update = False
    rg.selected_pets = list(gg.pet_list[:party])
    vp.switches = row["switch_requests"]
    t0 = time.perf_counter()
    try:
        with contextlib.redirect_stdout(log):
            vp.scene = factory()
    except Exception as exc:
        row["enter"] = f"{type(exc).__name__}: {exc}"
        row["traceback"] = traceback.format_exc()[-2000:]
        return row
    row["enter"] = "ok"
    row["enter_ms"] = round(1000 * (time.perf_counter() - t0), 1)
    clock = pg.time.Clock()
    clock.tick()
    stamps, intervals, work, phases, loading = [], [], [], [], []
    start = last = time.perf_counter()
    quit_requested = False
    frame = 0
    profiler = None
    if PROFILE:
        import cProfile
        profiler = cProfile.Profile()
    with contextlib.redirect_stdout(log):
        while time.perf_counter() - start < seconds:
            for ev in pg.event.get():
                if ev.type == pg.QUIT:
                    quit_requested = True
            a = time.perf_counter()
            if profiler is not None and a - start >= warmup:
                profiler.enable()
            try:
                if step is not None:
                    vp.scene = step(frame, vp.scene)
                phases.append(phase_of(vp.scene) if phase_of else None)
                loading.append(is_loading(vp.scene))
                vp.update()                  # scene update, shake sensor, autosave: as the game loop
                vp.draw(rg.render_surface, clock)
                display_utils.present()
            except Exception as exc:
                row["errors"] += 1
                if row["error"] is None:
                    row["error"] = f"{type(exc).__name__}: {exc}"
                    row["traceback"] = traceback.format_exc()[-2000:]
                if len(phases) < len(work) + 1:
                    phases.append(None)
            if profiler is not None:
                profiler.disable()
            b = time.perf_counter()
            work.append(b - a)
            if not uncapped:
                clock.tick(rate)
            now = time.perf_counter()
            stamps.append(now - start)
            intervals.append(now - last)
            last = now
            frame += 1
            if quit_requested:
                break
            if step is None and vp.switches:
                # the game leaves a scene that asks to: measuring on would
                # repeat its hand-over every frame (boot's pet refresh)
                row["left_after_s"] = round(stamps[-1], 1)
                break
    # Loading frames (PERF-01 allows dips there) are reported apart.
    loading = (loading + [False] * len(stamps))[:len(stamps)]
    load_idx = [i for i, flag in enumerate(loading) if flag]
    if load_idx:
        row["loading_frames"] = len(load_idx)
        row["loading_worst_ms"] = round(1000 * max(intervals[i] for i in load_idx), 1)
    keep = [i for i, flag in enumerate(loading) if not flag]
    if load_idx and keep:
        stamps = [stamps[i] for i in keep]
        intervals = [intervals[i] for i in keep]
        work = [work[i] for i in keep]
        phases = [phases[i] for i in keep] if len(phases) >= len(loading) else phases
    elif load_idx:
        row["loading_only"] = True
    row.update(summarize(stamps, intervals, work, warmup, rate))
    m = window_min(stamps, intervals, warmup)
    row["fps_min"] = round(m, 1) if m is not None else None
    row["quit"] = quit_requested
    if profiler is not None:
        counted = sum(1 for t in stamps if t >= warmup)
        try:
            row["profile"] = profile_lines(profiler, counted, PROFILE)
        except Exception as exc:          # an empty profile (no frame after the warmup)
            row["profile"] = [f"no profile: {exc}"]
    if phase_of:
        row["phases"] = {}
        for label in dict.fromkeys(p for p in phases if p):
            sel = [i for i, p in enumerate(phases) if p == label and stamps[i] >= warmup]
            if sel:
                row["phases"][label] = summarize([stamps[i] for i in sel], [intervals[i] for i in sel],
                                                 [work[i] for i in sel], 0, rate)
    return row


def is_loading(scene):
    """Whether *scene* is showing a loading screen this frame: the boot scene
    (it loads behind the logo), a scene with a ``_loading`` flag (the Library
    builds its roster behind Loading n/N)."""
    return type(scene).__name__ == "SceneBoot" or bool(getattr(scene, "_loading", False))


def summarize(stamps, intervals, work, warmup, rate):
    after = [(t, d, w) for t, d, w in zip(stamps, intervals, work) if t >= warmup] or \
        list(zip(stamps, intervals, work))
    total = sum(d for _, d, _ in after)
    ws = sorted(w for _, _, w in after)
    return dict(
        frames=len(stamps),
        fps_avg=round(len(after) / total, 1) if total else None,
        worst_ms=round(1000 * max(d for _, d, _ in after), 1) if after else None,
        work_ms=round(1000 * sum(ws) / len(ws), 1) if ws else None,
        work_p95_ms=round(1000 * ws[int(0.95 * (len(ws) - 1))], 1) if ws else None,
        late_pct=round(100 * sum(1 for _, d, _ in after if d > 1.5 / rate) / len(after), 1) if after else None)


# ---------------------------------------------------------------- heavy loads
#: What a player presses in each charge minigame (tests/game/battle/battle_flow.py).
CHARGE_PRESS = {
    "Dummy Bar": "A", "Count Bar": "A", "RPM": "A", "Xai Roll+Bar": "A", "Xai Bar": "A",
    "Count Match Color": "Y", "Count Match Classic": "Y", "Count Match Z": "Y",
    "Punch": "Y", "Mogera": "Y",
}
#: Frames between two presses: about five a second at 30 fps, a steady mash.
PRESS_EVERY = 6


def ready_party(game):
    """Every pet fed, healthy, awake (no bedtime: the Pi's clock must not
    decide), with DP: all four can train and battle at any hour."""
    for pet in game.gg.pet_list:
        pet.hunger = pet.strength = 4
        pet.dp = max(getattr(pet, "dp", 0) or 0, 4)
        pet.sick = 0
        pet.sleeps = pet.wakes = None
        if pet.state in ("nap", "sick"):
            pet.state = "idle"
        for name in ("win", "battles"):
            if not hasattr(pet, name):
                setattr(pet, name, 0)


def load_crowded_game(game, poops_per_pet=4):
    """The main game with every pet out and a screen full of poop. The pets'
    per-minute work (evolution, needs, poop, care mistakes; it runs for every
    pet on the same frame when they share a clock) and the scene's minute
    tick are brought due 3 s in, so the frame that runs them is measured as
    its own phase."""
    gg = game.gg
    import random
    from scenes.scene_maingame import SceneMainGame
    pets = gg.pet_list

    def start():
        ready_party(game)
        state = random.getstate()
        random.seed(7)
        gg.poop_list = []
        for pet in pets:
            for _ in range(poops_per_pet):
                pet.poop()
        random.setstate(state)
        now = time.monotonic()
        for pet in pets:
            pet._rt_origin = now - 57.0          # the next game minute in 3 s
            pet._rt_last_minute = 0
        scene = SceneMainGame()
        rate = game.gg.configuration.frame_rate
        scene.frame_counter = rate * 60 - rate * 3
        game.load_note = f"{len(pets)} pets, {len(gg.poop_list)} poops, a game minute 3 s in"
        return scene

    def phase_of(scene):
        now = time.monotonic()
        due = any(int((now - pet._rt_origin) / 60) > pet._rt_last_minute for pet in pets)
        return "game:minute tick" if due else "game:frame"
    return start, None, phase_of


def load_training(game, key="dummy"):
    """A training minigame played by every pet, round after round: READY, the
    charge (mashed), the attack animation, the result."""
    from scenes.scene_training import SceneTraining, TRAINING_MODES
    minigames = TRAINING_MODES[key].get("minigames") or ("Dummy Bar",)
    press = CHARGE_PRESS.get(minigames[0], "A")
    game.load_note = f"{key} ({minigames[0]}), mashing {press}"

    def start():
        ready_party(game)
        scene = SceneTraining()
        scene.select_training(key)
        playing = len(getattr(getattr(scene, "mode", None), "pets", None) or [])
        game.load_note = f"{key} ({minigames[0]}), {playing} pets playing, mashing {press}"
        return scene

    def step(frame, scene):
        mode = getattr(scene, "mode", None)
        if mode is None or vp.switches:          # the round is over (menu, or back to the game)
            vp.switches.clear()
            return start()
        if getattr(mode, "phase", None) == "charge" and frame % PRESS_EVERY == 0:
            scene.handle_event((press, None))
        return scene

    def phase_of(scene):
        mode = getattr(scene, "mode", None)
        return f"{key}:{getattr(mode, 'phase', None) or 'menu'}"
    return start, step, phase_of


def load_battle(game, module_name="DM20", area=1):
    """An adventure battle fought by every pet, round after round: the charge
    (mashed), the battle animation, the result."""
    from scenes.scene_battle import SceneBattle
    from utils.module_utils import get_module
    module = get_module(module_name) or get_module(game.modules[0])
    press = CHARGE_PRESS.get(getattr(module, "battle_minigame", "Dummy Bar"), "A")
    game.load_note = f"{module.name} area {area}, mashing {press}"

    def start():
        ready_party(game)
        game.rg.scene_battle_initial_view = ("adventure_battle", {"module": module, "area": area, "round_num": 1})
        return SceneBattle()

    def encounter(scene):
        return getattr(getattr(scene, "current_view", None), "battle_encounter", None)

    def step(frame, scene):
        enc = encounter(scene)
        over = enc is None or vp.switches or (
            getattr(enc, "victory_status", None) in ("Victory", "Defeat")
            and getattr(enc, "phase", None) not in ("battle", "clear", "result"))
        if over:
            vp.switches.clear()
            return start()
        if enc.phase == "charge" and frame % PRESS_EVERY == 0:
            scene.handle_event((press, None))
        team = getattr(getattr(enc, "battle_player", None), "team1", None)
        if team:
            game.load_note = f"{module.name} area {area}, {len(team)} pets fighting, mashing {press}"
        return scene

    def phase_of(scene):
        enc = encounter(scene)
        return f"battle:{getattr(enc, 'phase', None) or 'view'}"
    return start, step, phase_of


#: name -> setup(game) returning (factory, step, phase_of)
LOADS = {
    "game_crowded": load_crowded_game,
    "training_play": load_training,
    "battle_play": load_battle,
}


def main():
    global vp
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--game")
    ap.add_argument("--seconds", type=float, default=5.0)
    ap.add_argument("--warmup", type=float, default=1.0)
    ap.add_argument("--scene", nargs="*")
    ap.add_argument("--res", default="240x240")
    ap.add_argument("--windowed", action="store_true", help="a window instead of fullscreen")
    ap.add_argument("--uncapped", action="store_true", help="no clock.tick: the most the Pi can draw")
    ap.add_argument("--driver", help="SDL video driver (default: the game's choice, kmsdrm on a console)")
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--dummy", action="store_true", help="headless SDL (checking the script off the Pi)")
    ap.add_argument("--min-fps", type=float, default=29.5)
    ap.add_argument("--dip-fps", type=float, default=27.0)
    ap.add_argument("--in-place", action="store_true",
                    help="run in the game folder (save redirected, writes blocked) instead of a symlink sandbox")
    ap.add_argument("--tmp", help="where the throw-away sandbox goes (default: the system temp folder)")
    ap.add_argument("--json")
    ap.add_argument("--load", nargs="*", choices=list(LOADS),
                    help="heavy loads to run after the scenes (default: all of them)")
    ap.add_argument("--no-loads", action="store_true", help="only the scenes")
    ap.add_argument("--loads-only", action="store_true", help="only the heavy loads")
    ap.add_argument("--load-seconds", type=float, default=30.0,
                    help="seconds per heavy load (several rounds of training or battle)")
    ap.add_argument("--training", default="dummy", help="the training the training_play load plays")
    ap.add_argument("--profile", nargs="?", const=12, type=int, metavar="N",
                    help="profile each scene and load (after the warmup) and print its N costliest functions "
                         "per frame (default 12); profiling slows the frames, so read it for where the time "
                         "goes, not for the fps")
    ap.add_argument("--battle-module", default="DM20",
                    help="the module whose area 1 battle_play fights (one with a charge minigame)")
    args = ap.parse_args()
    global PROFILE
    PROFILE = args.profile

    game_dir = pi_common.find_game(args.game)
    video = pi_common.choose_display(args.driver, args.dummy, audio=not args.no_audio)
    net = pi_common.NetworkGuard().install()
    box = pi_common.Sandbox(game_dir, args.tmp, links=not args.in_place)
    out = os.path.abspath(args.json or os.path.join(os.path.expanduser("~"), "omnipet-test-results",
                                                    time.strftime("perf_scenes_%Y%m%d_%H%M%S.json")))
    guard = pi_common.WriteGuard(game_dir, [box.dir, out]).install()
    scenes, source = pi_common.scene_list()
    names = [] if args.loads_only else (args.scene or list(scenes))
    # the heavy loads run by default, unless only some scenes were asked for
    loads = [] if args.no_loads else (args.load if args.load else ([] if args.scene else list(LOADS)))
    unknown = [n for n in names if n not in scenes]
    if unknown:
        raise SystemExit(f"unknown scene(s) {unknown}; known: {', '.join(scenes)}")
    w, h = (int(x) for x in args.res.lower().split("x"))

    print("== Omnipet perf_scenes (PERF-01) ==")
    for line in pi_common.system_lines(game_dir):
        print(line)
    log = io.StringIO()
    try:
        game = pi_common.Game(box, (w, h), fullscreen=not args.windowed, log=log)
    except SystemExit as exc:
        print(f"FAIL     the game could not open a display ({video}): exit {exc.code}")
        print(log.getvalue()[-1500:])
        sys.exit(1)
    rate = game.gg.configuration.frame_rate
    (cw, ch), disp = game.canvas()
    import pygame
    print(f"video    {game.driver()} via {video}; window {disp[0]}x{disp[1]} "
          f"{'windowed' if args.windowed else 'fullscreen'}; canvas {cw}x{ch}")
    print(f"pygame   {pygame.version.ver}, SDL {'.'.join(map(str, pygame.get_sdl_version()))}")
    print(f"pacing   {'uncapped' if args.uncapped else f'clock.tick({rate})'} (configuration.frame_rate, "
          f"system default {game.default_frame_rate}); {args.seconds:g} s per scene, first {args.warmup:g} s not counted")
    print(f"boot     display {game.display_s:.1f} s, sprites+modules {game.modules_s:.1f} s; "
          f"{len(game.modules)} modules; party {', '.join(game.party) or 'none (no module with a child-stage Digimon)'}")
    print(f"save     {box.describe()}")
    print(f"scenes   {len(names)} from {source}; heavy loads: {', '.join(loads) or 'none'}"
          + (f" ({args.load_seconds:g} s each, every pet selected)" if loads else ""))
    extra = pi_common.unlisted_scenes(game_dir, scenes)
    if extra:
        print(f"note     the game has scenes this list does not enter: {', '.join(extra)}")

    vp = game_vp(game)
    rows = []
    print()
    print(f"{'scene':12} {'fps avg':>7} {'fps min':>7} {'worst ms':>8} {'cpu ms':>6} {'p95':>5} {'late%':>5}  result")
    for name in names:
        module_name, class_name = scenes[name]
        try:
            cls = getattr(importlib.import_module(module_name), class_name)
        except Exception as exc:
            row = {"enter": f"import {module_name}: {type(exc).__name__}: {exc}"}
        else:
            row = measure(game, cls, args.seconds, args.warmup, rate, args.uncapped, log)
        row["scene"] = name
        report(row, args)
        rows.append(row)
        if row.get("quit"):
            print("stopped: window closed")
            break

    for name in loads:
        if rows and rows[-1].get("quit"):
            break
        try:
            setup = LOADS[name]
            if name == "training_play":
                factory, step, phase_of = setup(game, args.training)
            elif name == "battle_play":
                factory, step, phase_of = setup(game, args.battle_module)
            else:
                factory, step, phase_of = setup(game)
        except Exception as exc:
            row = {"enter": f"setup: {type(exc).__name__}: {exc}", "traceback": traceback.format_exc()[-2000:]}
        else:
            row = measure(game, factory, args.load_seconds, args.warmup, rate, args.uncapped, log,
                          step=step, phase_of=phase_of, party=len(game.gg.pet_list))
            row["note"] = getattr(game, "load_note", "")
        row["scene"] = name
        report(row, args)
        rows.append(row)
        for label, sub in (row.get("phases") or {}).items():
            print(f"  {label:20.20} {sub['fps_avg'] or 0:7.1f} {'':>7} {sub['worst_ms'] or 0:8.1f} "
                  f"{sub['work_ms'] or 0:6.1f} {sub['work_p95_ms'] or 0:5.1f} {sub['late_pct'] or 0:5.1f}  "
                  f"{sub['frames']} frames", flush=True)

    entered = [r for r in rows if r["enter"] == "ok"]
    slow = [r for r in entered if any(v.startswith("UNDER") for v in r["verdict"])]
    dips = [r for r in entered if any(v.startswith("dip") for v in r["verdict"])]
    broken = [r for r in rows if r["enter"] != "ok"]
    finish(rows, entered, slow, dips, broken, args, guard, net, log, out, rate, cw, ch, game, game_dir)


def report(row, args):
    """Give *row* its verdict and print its line."""
    name = row["scene"]
    verdict = []
    if row["enter"] != "ok":
        verdict.append("ENTER FAILED " + row["enter"][:80])
    else:
        left = row.get("left_after_s")
        judged = not row.get("loading_only") and not (left is not None and left < args.warmup + 1.0)
        if row.get("loading_only"):
            verdict.append(f"loading screen (PERF-01 allows its dips): longest frame {row['loading_worst_ms']:g} ms")
        elif row.get("loading_frames"):
            verdict.append(f"{row['loading_frames']} loading frames not counted (longest {row['loading_worst_ms']:g} ms)")
        if left is not None and not judged and not row.get("loading_only"):
            verdict.append(f"left after {left:g} s, too soon to judge")
        if judged and not args.uncapped and row.get("fps_avg") is not None and row["fps_avg"] < args.min_fps:
            verdict.append(f"UNDER {args.min_fps:g} FPS")
        if judged and not args.uncapped and row.get("fps_min") is not None and row["fps_min"] < args.dip_fps:
            verdict.append(f"dip under {args.dip_fps:g}")
        if row.get("errors"):
            verdict.append(f"{row['errors']} frame errors: {row['error'][:60]}")
        if row.get("switch_requests") and name not in LOADS:
            verdict.append("asked to switch to " + ",".join(dict.fromkeys(row["switch_requests"])))
        if row.get("note"):
            verdict.append(row["note"])
    row["verdict"] = verdict
    if row["enter"] == "ok":
        def cell(key, width):
            v = row.get(key)
            return f"{v:{width}.1f}" if isinstance(v, (int, float)) else f"{'-':>{width}}"
        print(f"{name:12} {cell('fps_avg', 7)} {cell('fps_min', 7)} {cell('worst_ms', 8)} "
              f"{cell('work_ms', 6)} {cell('work_p95_ms', 5)} {cell('late_pct', 5)}  "
              f"{'; '.join(verdict) or 'ok'}", flush=True)
    else:
        print(f"{name:12} {'-':>7} {'-':>7} {'-':>8} {'-':>6} {'-':>5} {'-':>5}  {'; '.join(verdict)}", flush=True)
    for line in row.get("profile") or []:
        print(f"    prof {line}", flush=True)


def finish(rows, entered, slow, dips, broken, args, guard, net, log, out, rate, cw, ch, game, game_dir):
    """The verdict, the problems, the JSON; exits."""
    print()
    if args.uncapped:
        print(f"RESULT   uncapped: slowest {min(entered, key=lambda r: r['fps_avg'] or 0)['scene'] if entered else '-'}; "
              "rerun without --uncapped for the PERF-01 verdict")
    else:
        slow_txt = ", ".join("%s %s" % (r["scene"], r["fps_avg"]) for r in slow)
        dip_txt = ", ".join("%s %s" % (r["scene"], r["fps_min"]) for r in dips)
        print(f"RESULT   PERF-01 {'FAIL' if slow or broken else 'PASS'}: {len(entered)}/{len(rows)} scenes and loads ran, "
              f"{len(slow)} under {args.min_fps:g} fps" + (f" ({slow_txt})" if slow else "")
              + f", {len(dips)} with dips" + (f" ({dip_txt})" if dips else ""))
    for r in broken:
        print(f"ENTER    {r['scene']}: {r['enter']}")
        if r.get("traceback"):
            print("         " + r["traceback"].strip().replace("\n", "\n         ")[-1200:])
    for r in entered:
        if r.get("traceback"):
            print(f"ERROR    {r['scene']}: {r['error']}")
            print("         " + r["traceback"].strip().replace("\n", "\n         ")[-1200:])
    errs = pi_common.error_lines(log.getvalue(), 15)
    if errs:
        print(f"LOG      {len(errs)} error lines in the game's console output (first ones):")
        for e in errs[:15]:
            print("         " + e.replace("\n", "\n         ")[:600])
    if guard.blocked:
        print(f"GUARD    {len(guard.blocked)} writes into the game folder were blocked: " + "; ".join(guard.blocked[:5]))
    if net.refused:
        print(f"NETWORK  refused (expected, nothing leaves the Pi): {net.summary()}")
    try:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            json.dump({"rows": rows, "rate": rate, "canvas": [cw, ch], "driver": game.driver(),
                       "system": pi_common.system_lines(game_dir)}, fh, indent=1)
        print(f"json     {out}")
    except OSError as exc:
        print(f"json     not written: {exc}")
    game.pygame.quit()
    sys.exit(1 if broken or (slow and not args.uncapped) else 0)


def game_vp(game):
    """A VirtualPetGame on the current scene, as tests/support/harness.py builds
    it; its scene switches are recorded instead of followed, so a scene that
    moves on by itself (boot) is still the one measured."""
    from vpet import VirtualPetGame
    v = VirtualPetGame.__new__(VirtualPetGame)
    v.rotated = False
    v.mouse_pointer = None
    v._mouse_pointer_orig = None
    v._mouse_pointer_size = None
    v.stat_font = None
    v.scene = types.SimpleNamespace(update=lambda: None, draw=lambda s: None, handle_event=lambda e: None)
    rg = game.rg
    v.switches = []

    def hold():
        rg.game_state_update = False
        v.switches.append(rg.game_state)
    v.change_scene = hold
    return v


vp = None

if __name__ == "__main__":
    main()
