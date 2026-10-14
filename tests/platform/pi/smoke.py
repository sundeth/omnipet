#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Boot the real game on the Pi and let it run (checklist BLD-01, BLD-02, BLD-03).

Run through smoke.sh. The game is started through its own entry point,
main.main() (the display set-up, the VirtualPetGame boot path and the real
main loop with its clock), from a sandbox with a temp save: a small party is
written first (in a headless child process) so boot goes straight to the main
game instead of first-run setup. Network is refused and writes into the game
folder are blocked. After --seconds on the main game a QUIT event ends the loop the way closing
the window does (the game saves into the temp folder and exits).

    python3 smoke.py [--game DIR] [--seconds 60] [--tour] [--windowed]
                     [--driver kmsdrm] [--no-audio] [--dummy] [--tmp DIR] [--log PATH]

--tour presses buttons once the main game is up (RIGHT to a main-menu entry,
A to open it, B B B to come back), walking the nine main-menu entries and
then START (settings), so the scenes they open are entered on the Pi too;
about 60 s, so give it --seconds 70 or more. The presses are posted as the
events the GPIO buttons deliver (--tour-input gpio, the default) or as
key presses from the default keyboard map (--tour-input keyboard).

Prints: boot timings, the modules loaded, every scene switch, frames and fps,
every traceback and error line from the game's output, refused network
attempts and blocked writes. Exit 1 when the main game was not reached, the
run ended early or a traceback was printed.
"""
import argparse
import contextlib
import faulthandler
import io
import json
import os
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pi_common  # noqa: E402

T0 = time.perf_counter()


def elapsed():
    return time.perf_counter() - T0


class Tee(io.TextIOBase):
    """Everything the game prints goes to the log (and to the terminal with --verbose)."""

    def __init__(self, fh, echo=None):
        self.fh, self.echo = fh, echo

    def write(self, s):
        self.fh.write(s)
        if self.echo:
            self.echo.write(s)
        return len(s)

    def flush(self):
        self.fh.flush()
        if self.echo:
            self.echo.flush()


# ---------------------------------------------------------------- fixture child
def fixture(root, save, game_dir, windowed):
    """Headless: write a save with the party, as harness.Env does."""
    pi_common.choose_display(dummy=True)
    pi_common.NetworkGuard().install()
    pi_common.WriteGuard(game_dir, [save]).install()
    box = type("Box", (), {"root": root, "save": save})()
    log = io.StringIO()
    game = pi_common.Game(box, (240, 240), fullscreen=False, log=log)
    cfg = game.gg.configuration
    # The save carries the display settings; store the Pi's own defaults
    # (fullscreen 240x240), not the headless window used to write it.
    with contextlib.redirect_stdout(log):
        cfg.fullscreen = not windowed
        cfg.screen_width = cfg.screen_height = 240
        cfg.window_width = cfg.window_height = 240
        cfg.base_resolution_width = cfg.base_resolution_height = 240
        cfg.frame_rate = game.default_frame_rate
        time.sleep(1.1)                     # a newer mtime than the first save: the loader takes the newest
        game.gg.save()
    print(json.dumps({"modules": game.modules, "party": game.party,
                      "errors": pi_common.error_lines(log.getvalue(), 10)}))


# ---------------------------------------------------------------- run
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--game")
    ap.add_argument("--seconds", type=float, default=60.0, help="how long to run once the main game is up")
    ap.add_argument("--boot-timeout", type=float, default=120.0, help="give up if the main game is not up by then")
    ap.add_argument("--tour", action="store_true", help="walk the main menu with button presses")
    ap.add_argument("--tour-input", choices=("gpio", "keyboard"), default="gpio",
                    help="gpio: the events the GPIO buttons post (default); keyboard: the default key map")
    ap.add_argument("--windowed", action="store_true")
    ap.add_argument("--driver")
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--dummy", action="store_true", help="headless SDL (checking the script off the Pi)")
    ap.add_argument("--in-place", action="store_true",
                    help="run in the game folder (save redirected, writes blocked) instead of a symlink sandbox")
    ap.add_argument("--tmp")
    ap.add_argument("--log", help="the game's full output (default ~/omnipet-test-results/smoke_<time>.log)")
    ap.add_argument("--verbose", action="store_true", help="also echo the game's output")
    ap.add_argument("--keep", action="store_true", help="keep the sandbox (temp save) afterwards")
    ap.add_argument("--fixture", nargs=2, metavar=("ROOT", "SAVE"), help=argparse.SUPPRESS)
    args = ap.parse_args()
    game_dir = pi_common.find_game(args.game)
    if args.fixture:
        fixture(args.fixture[0], args.fixture[1], game_dir, args.windowed)
        return

    print("== Omnipet smoke (BLD-01/02/03) ==")
    for line in pi_common.system_lines(game_dir):
        print(line)
    box = pi_common.Sandbox(game_dir, args.tmp, keep=args.keep, links=not args.in_place)
    log_path = os.path.abspath(args.log or os.path.join(os.path.expanduser("~"), "omnipet-test-results",
                                                        time.strftime("smoke_%Y%m%d_%H%M%S.log")))
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    print(f"save     {box.describe()}")

    # 1. the party, written headless in a child process
    t = time.perf_counter()
    env = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    proc = subprocess.run([sys.executable, "-B", os.path.abspath(__file__), "--game", game_dir,
                           "--fixture", box.root, box.save] + (["--windowed"] if args.windowed else []),
                          capture_output=True, text=True, env=env, cwd=HERE)
    try:
        fx = json.loads((proc.stdout.strip().splitlines() or ["{}"])[-1])
    except ValueError:
        fx = {}
    if proc.returncode or not fx:
        print(f"FAIL     could not write the starting save (exit {proc.returncode})")
        print((proc.stdout + proc.stderr)[-2500:])
        sys.exit(1)
    print(f"fixture  {time.perf_counter() - t:.1f} s; {len(fx['modules'])} modules: {', '.join(fx['modules'])}")
    print(f"party    {', '.join(fx['party']) or 'none (no module with a child-stage Digimon)'}")

    # 2. the real game
    video = pi_common.choose_display(args.driver, args.dummy, audio=not args.no_audio)
    net = pi_common.NetworkGuard().install()
    guard = pi_common.WriteGuard(game_dir, [box.dir, log_path]).install()
    log_fh = open(log_path, "w", encoding="utf-8", errors="replace", buffering=1)
    faulthandler.enable(file=log_fh, all_threads=True)
    faulthandler.dump_traceback_later(args.seconds + args.boot_timeout + 60, exit=True, file=log_fh)  # hang watchdog
    os.chdir(box.root)
    for p in (os.path.join(box.root, "src"), box.root):
        if p not in sys.path:
            sys.path.insert(0, p)
    real_out, real_err = sys.stdout, sys.stderr
    sys.stdout = Tee(log_fh, real_out if args.verbose else None)
    sys.stderr = Tee(log_fh, real_err if args.verbose else None)
    marks = {"imported": None, "constructed": None, "first_frame": None, "game": None, "quit_at": None}
    scenes, frames = [], []
    status = {"exc": None}
    try:
        pi_common.patch_save_dir(box.save, free_mode=False)
        import main
        import pygame
        from core import runtime_globals
        import vpet
        from utils import display_utils
        marks["imported"] = elapsed()

        real_change = vpet.VirtualPetGame.change_scene
        real_init = vpet.VirtualPetGame.__init__
        real_present = display_utils.present

        def change_scene(self):
            state = runtime_globals.game_state
            real_change(self)
            scenes.append((round(elapsed(), 1), state, type(self.scene).__name__))
            if state == "game" and marks["game"] is None:
                marks["game"] = elapsed()

        def init(self, *a, **k):
            real_init(self, *a, **k)
            marks["constructed"] = elapsed()
            scenes.append((round(elapsed(), 1), "boot", type(self.scene).__name__))

        def present(display=None):
            real_present(display)
            now = elapsed()
            if marks["first_frame"] is None:
                marks["first_frame"] = now
            frames.append(now)
        vpet.VirtualPetGame.change_scene = change_scene
        vpet.VirtualPetGame.__init__ = init
        display_utils.present = present
        real_log = runtime_globals.game_console.log

        def console(msg, *a, **k):
            log_fh.write(f"[console] {msg}\n")
            return real_log(msg, *a, **k)
        runtime_globals.game_console.log = console

        from input.input_manager import GPIO_PRESS_EVENT, GPIO_RELEASE_EVENT
        from core import game_globals
        keys = {"RIGHT": pygame.K_RIGHT, "UP": pygame.K_UP, "A": pygame.K_RETURN, "B": pygame.K_ESCAPE,
                "START": pygame.K_BACKSPACE}

        def post(action=None, quit_=False):
            try:
                if quit_:
                    marks["quit_at"] = elapsed()
                    pygame.event.post(pygame.event.Event(pygame.QUIT))
                elif args.tour_input == "gpio":
                    # what gpiozero's handlers post for a button (input_manager.make_gpio_handler)
                    pins = {a: p for p, a in game_globals.configuration.gpio_map.items()}
                    pin = pins.get(action, -1)
                    pygame.event.post(pygame.event.Event(GPIO_PRESS_EVENT, action=action, gpio_pin=pin))
                    time.sleep(0.05)
                    pygame.event.post(pygame.event.Event(GPIO_RELEASE_EVENT, action=action, gpio_pin=pin))
                else:
                    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=keys[action], mod=0,
                                                         unicode="", scancode=0))
            except Exception as exc:                      # pygame not up (yet) or gone
                log_fh.write(f"[smoke] could not post an event: {exc}\n")

        def driver():
            boot_deadline = time.perf_counter() + args.boot_timeout
            while marks["game"] is None and time.perf_counter() < boot_deadline:
                time.sleep(0.2)
            deadline = time.perf_counter() + (args.seconds if marks["game"] is not None else 0)
            if args.tour and marks["game"] is not None:
                time.sleep(3)
                # scene_maingame: a 2x5 menu, cursor at -1 after B; the first
                # RIGHT selects 0, RIGHT wraps within its row, UP swaps rows.
                # Entries: 0 status, 1 feeding, 2 training, 3 battle, 4 clean,
                # 5 sleep, 6 heal, 7 library, 8 connect; START opens settings.
                steps = [[("RIGHT", 0.25)] * (i % 5 + 1) + [("UP", 0.25)] * (i // 5) + [("A", 3.0)]
                         for i in range(9)]
                steps.append([("START", 2.5)])
                for step in steps:
                    for action, wait in step + [("B", 0.7)] * 3:
                        if time.perf_counter() >= deadline:
                            break
                        post(action)
                        time.sleep(wait)
            while time.perf_counter() < deadline:
                time.sleep(0.2)
            post(quit_=True)
        threading.Thread(target=driver, daemon=True).start()
        main.main()
    except SystemExit as exc:
        status["exc"] = f"SystemExit({exc.code})"
    except BaseException as exc:                          # noqa: B902 - report whatever ended it
        import traceback
        status["exc"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        faulthandler.cancel_dump_traceback_later()
        sys.stdout, sys.stderr = real_out, real_err
        log_fh.flush()
    end = elapsed()
    log_fh.close()
    text = open(log_path, encoding="utf-8", errors="replace").read()

    # 3. the report
    print(f"video    {video}")
    def mark(k):
        return f"{marks[k]:.1f} s" if marks[k] is not None else "never"
    print(f"boot     import {mark('imported')}, game object {mark('constructed')}, first frame {mark('first_frame')}, "
          f"main game {mark('game')} (from start)")
    try:
        from core import runtime_globals as rg
        mods = sorted(rg.game_modules)
        print(f"modules  {len(mods)} loaded by the game: {', '.join(mods)}")
    except Exception:
        mods = []
    path = " > ".join(f"{name}@{at:g}s" for at, name, _ in scenes)
    print(f"scenes   {path or 'none'}")
    run_frames = [f for f in frames if marks["game"] is not None and f >= marks["game"] + 2]
    if len(run_frames) > 1:
        span = run_frames[-1] - run_frames[0]
        fps = (len(run_frames) - 1) / span if span else 0
        gaps = [b - a for a, b in zip(run_frames, run_frames[1:])]
        worst = max(gaps) if gaps else 0
        windows = []
        j = 0
        for i in range(len(run_frames)):
            while run_frames[i] - run_frames[j] > 1.0:
                j += 1
            if run_frames[i] - run_frames[0] >= 1.0:
                windows.append(i - j)
        print(f"frames   {len(frames)} in total; from 2 s after the main game: {fps:.1f} fps avg, "
              f"{min(windows) if windows else '-'} fps worst second, longest frame {1000 * worst:.0f} ms")
    else:
        print(f"frames   {len(frames)} in total (too few after the main game to time)")
    errors = pi_common.error_lines(text, 40)
    tracebacks = [e for e in errors if e.startswith("Traceback")]
    print(f"errors   {len(tracebacks)} tracebacks, {len(errors) - len(tracebacks)} other error lines")
    for e in errors[:25]:
        print("         " + e.replace("\n", "\n         ")[:1500])
    if net.refused:
        print(f"network  refused (expected, nothing leaves the Pi): {net.summary()}")
    if guard.blocked:
        print(f"guard    {len(guard.blocked)} writes into the game folder were blocked: " + "; ".join(guard.blocked[:6]))
    ran = (marks["game"] is not None and marks["quit_at"] is not None
           and marks["quit_at"] - marks["game"] >= args.seconds - 1 and end >= marks["quit_at"])
    ok = marks["game"] is not None and ran and not tracebacks
    why = []
    if marks["game"] is None:
        why.append("the main game was never reached")
    if not ran:
        why.append(f"the run ended after {end:.0f} s ({status['exc'] or 'game loop exited'})")
    if tracebacks:
        why.append(f"{len(tracebacks)} tracebacks")
    print(f"RESULT   smoke {'PASS' if ok else 'FAIL'}" + (": " + "; ".join(why) if why else
                                                          f": main game for {end - (marks['game'] or 0):.0f} s"))
    print(f"log      {log_path}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
