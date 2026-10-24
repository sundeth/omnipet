#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Enter every game scene at every supported resolution, headless.

The automated part of checklist UI-01..UI-07 and PERF-01. For each resolution
a child process boots the game the way main.py does (SDL dummy drivers, a
throw-away save folder, sockets refused so nothing reaches Omninet), gives it
a small party, then for every scene in vpet's scene map:

    enter     the scene is constructed and runs 20 frames without raising
    paint     every pixel of the canvas is drawn each frame (the canvas is
              pre-filled with a sentinel colour; any left = stale area: UI-05)
    bounds    every visible component lies on the canvas (UI-03) and, unless it
              uses screen coordinates, inside the 240-base square (UI-07)
    touch     in touch mode no component shows focus after entering (UI-02)
    sound     UP/DOWN/LEFT/RIGHT, A, B, a mouse click and a tap on a focusable
              component each play a sound (UI-06); recorded per input
    frame     mean and worst update+draw time (PERF-01 desktop baseline)

    python -B tests/release/scene_sweep.py [--res 240x240 ...] [--scene game ...] [--json PATH] [--md PATH]

Exit 1 when any scene fails to enter or paint. Bounds, touch-focus and sound
are reported as findings (they include deliberate exceptions to review).
"""
import argparse
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "support"))
from paths import ROOT, temp_dir, REPORTS  # noqa: E402
SRC = os.path.join(ROOT, "src")

#: 1x-4x squares, then non-square windows (each at its own integer UI scale).
RESOLUTIONS = ["240x240", "480x480", "720x720", "960x960",
               "320x240", "240x320", "800x480", "1280x720", "1400x640", "1920x1080"]
#: vpet.VirtualPetGame.change_scene's map, plus the boot scene.
SCENES = {
    "boot": ("scenes.scene_boot", "SceneBoot"),
    "setup": ("scenes.scene_setup", "SceneSetup"),
    "login": ("scenes.scene_login", "SceneLogin"),
    "egg": ("scenes.scene_eggselection", "SceneEggSelection"),
    "game": ("scenes.scene_maingame", "SceneMainGame"),
    "settings": ("scenes.scene_settingsmenu", "SceneSettingsMenu"),
    "tutorial": ("scenes.scene_tutorial", "SceneTutorial"),
    "error": ("scenes.scene_error", "SceneError"),
    "status": ("scenes.scene_status", "SceneStatus"),
    "feeding": ("scenes.scene_inventory", "SceneInventory"),
    "training": ("scenes.scene_training", "SceneTraining"),
    "sleepmenu": ("scenes.scene_sleep", "SceneSleep"),
    "healing": ("scenes.scene_healing", "SceneHealing"),
    "battle": ("scenes.scene_battle", "SceneBattle"),
    "battle_pvp": ("scenes.scene_battle_pvp", "SceneBattlePvP"),
    "connect": ("scenes.scene_connect", "SceneConnect"),
    "digidex": ("scenes.scene_digidex", "SceneDigidex"),
    # "evolution": SceneEvolution is reached only from a hard-coded demo in
    # scene_maingame.start_evolution_sequence that nothing triggers
    # (runtime_globals.evolution_pet is never set); see release finding UI-10.
    "freezer": ("scenes.scene_freezerbox", "SceneFreezerBox"),
    "library": ("scenes.scene_library", "SceneLibrary"),
    "collection": ("scenes.scene_collection", "SceneCollection"),
    "debug": ("scenes.scene_debug", "SceneDebug"),
}
#: (module, version) of the party the sweep plays with: one per sprite library.
PARTY = [("DMC", 1), ("PENC", 1), ("IC", 1), ("VB", 1)]
SENTINEL = (255, 0, 254)
FRAMES = 20


# ---------------------------------------------------------------- child process
def child(res, scene_names, out_path):
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    os.environ["SDL_AUDIODRIVER"] = "dummy"
    os.chdir(ROOT)
    for p in (SRC, ROOT):
        if p not in sys.path:
            sys.path.insert(0, p)
    import socket
    def refuse(*a, **k):
        raise OSError("network disabled by scene_sweep")
    socket.create_connection = refuse
    socket.socket.connect = lambda self, *a, **k: refuse()
    w, h = (int(x) for x in res.split("x"))
    results = []
    with contextlib.redirect_stdout(io.StringIO()):
        import pygame
        import main
        from core import game_globals, runtime_globals
        save_root = temp_dir("sweep_save_")
        game_globals._get_base_save_dir = lambda: save_root
        game_globals._can_access_save_dir = lambda: True
        game_globals.game_mode = game_globals.GAME_MODE_FREE
        cfg = game_globals.configuration
        cfg.fullscreen = False
        cfg.screen_width, cfg.screen_height = w, h
        cfg.window_width, cfg.window_height = w, h
        main.setup_pygame()
        main.setup_display()
        from utils.pygame_utils import load_misc_sprites
        from utils.module_utils import load_modules, get_module
        runtime_globals.misc_sprites = load_misc_sprites()
        load_modules()
        from models.game_pet import GamePet
        game_globals.pet_list = []
        for mod_name, version in PARTY:
            mod = get_module(mod_name)
            if not mod:
                continue
            child_stage = next((m for m in mod.get_monsters_by_stage(3) if m.get("version") == version), None)
            if child_stage:
                pet = GamePet(dict(child_stage, module=mod_name))
                pet.hunger = pet.strength = 4
                game_globals.pet_list.append(pet)
        from utils.pet_utils import refresh_pet_sizes
        refresh_pet_sizes()
        game_globals.game_background = "ver1"
        game_globals.background_module_name = "DMC"
        sounds = []
        real_play = runtime_globals.game_sound.play
        def record(name):
            sounds.append(name)
            try:
                return real_play(name)
            except Exception:
                return None
        runtime_globals.game_sound.play = record
        surface = runtime_globals.render_surface

    import importlib

    def managers(scene):
        """Every UIManager reachable from the scene (its views included)."""
        from ui.ui_manager import UIManager
        found, seen, stack = [], set(), [(scene, 0)]
        while stack:
            obj, depth = stack.pop()
            if id(obj) in seen or depth > 3:
                continue
            seen.add(id(obj))
            if isinstance(obj, UIManager):
                found.append(obj)
                continue
            values = []
            if isinstance(obj, dict):
                values = list(obj.values())
            elif isinstance(obj, (list, tuple)):
                values = list(obj)
            elif hasattr(obj, "__dict__") and type(obj).__module__.split(".")[0] in ("scenes", "ui", "battle", "training"):
                values = list(vars(obj).values())
            for v in values:
                if isinstance(v, (int, float, str, bytes, bool)) or v is None:
                    continue
                if hasattr(v, "get_size") and hasattr(v, "blit"):   # a Surface
                    continue
                stack.append((v, depth + 1))
        return found

    from vpet import VirtualPetGame
    shell = VirtualPetGame.__new__(VirtualPetGame)

    def send(scene, event):
        """Input the way the game delivers it (VirtualPetGame.dispatch_input)."""
        shell.scene = scene
        return shell.dispatch_input(event)

    def frame(scene, n=1):
        times = []
        for _ in range(n):
            t = time.perf_counter()
            scene.update()
            surface.fill(SENTINEL)
            scene.draw(surface)
            times.append(time.perf_counter() - t)
            runtime_globals.game_state_update = False
        return times

    def unpainted():
        mask = pygame.mask.from_threshold(surface, SENTINEL, (1, 1, 1, 255))
        return mask.count()

    def fresh(cls, mode):
        runtime_globals.INPUT_MODE = mode
        runtime_globals.game_state_update = False
        runtime_globals.selected_pets = list(game_globals.pet_list[:1])
        with contextlib.redirect_stdout(io.StringIO()):
            return cls()

    def focusables(scene):
        out = []
        for mgr in managers(scene):
            out += [c for c in mgr.focusable_components if getattr(c, "visible", True)]
        return out

    for name in scene_names:
        module_name, class_name = SCENES[name]
        row = {"res": res, "scene": name, "enter": None, "paint": None, "bounds": [], "square": [],
               "touch_focus": [], "silent_inputs": [], "frame_ms": None, "worst_ms": None, "components": 0}
        try:
            cls = getattr(importlib.import_module(module_name), class_name)
            scene = fresh(cls, runtime_globals.KEYBOARD_MODE)
            with contextlib.redirect_stdout(io.StringIO()):
                times = frame(scene, FRAMES)
            row["enter"] = "ok"
            row["frame_ms"] = round(1000 * sum(times[2:]) / max(1, len(times) - 2), 2)
            row["worst_ms"] = round(1000 * max(times[2:] or times), 2)
            left = unpainted()
            row["paint"] = "ok" if left == 0 else f"{left} px ({100 * left / (w * h):.1f}%) never painted"
            # bounds
            for mgr in managers(scene):
                for c in mgr.components:
                    if not getattr(c, "visible", True):
                        continue
                    row["components"] += 1
                    r = c.rect
                    label = f"{type(c).__name__}@{tuple(getattr(c, 'base_rect', r))}"
                    if r.left < 0 or r.top < 0 or r.right > w or r.bottom > h:
                        row["bounds"].append(f"{label} -> {tuple(r)} off a {w}x{h} canvas")
                    b = getattr(c, "base_rect", None)
                    if b is not None and not getattr(c, "use_screen_coordinates", False):
                        if b.left < 0 or b.top < 0 or b.right > 240 or b.bottom > 240:
                            row["square"].append(f"{label} outside the 240 square")
            # keyboard / joystick / GPIO all arrive as these actions
            for action in ("DOWN", "UP", "RIGHT", "LEFT"):
                before = len(sounds)
                with contextlib.redirect_stdout(io.StringIO()):
                    send(scene, (action, None))
                    frame(scene)
                if len(sounds) == before and not shell._scene_plays_own_input_sounds():
                    row["silent_inputs"].append(action)
            for action in ("A", "B"):
                s2 = fresh(cls, runtime_globals.KEYBOARD_MODE)
                with contextlib.redirect_stdout(io.StringIO()):
                    frame(s2, 2)
                    before = len(sounds)
                    send(s2, (action, None))
                    frame(s2)
                if len(sounds) == before:
                    row["silent_inputs"].append(action)
            # mouse: hover then click the first focusable component
            s3 = fresh(cls, runtime_globals.MOUSE_MODE)
            with contextlib.redirect_stdout(io.StringIO()):
                frame(s3, 2)
            targets = focusables(s3)
            if targets:
                pos = targets[0].rect.center
                with contextlib.redirect_stdout(io.StringIO()):
                    runtime_globals.game_input.mouse_position = pos
                    send(s3, ("MOUSE_MOTION", {"pos": pos}))
                    before = len(sounds)
                    send(s3, ("LCLICK", {"pos": pos}))
                    frame(s3)
                if len(sounds) == before:
                    row["silent_inputs"].append(f"LCLICK on {type(targets[0]).__name__}")
            # touch: nothing focused on entry; a tap plays a sound
            s4 = fresh(cls, runtime_globals.TOUCH_MODE)
            with contextlib.redirect_stdout(io.StringIO()):
                frame(s4, 3)
            row["touch_focus"] = sorted({type(c).__name__ for c in focusables(s4) if getattr(c, "focused", False)})
            targets = focusables(s4)
            if targets:
                pos = targets[0].rect.center
                with contextlib.redirect_stdout(io.StringIO()):
                    before = len(sounds)
                    runtime_globals.game_input.mouse_position = pos
                    send(s4, ("LCLICK", {"pos": pos}))
                    frame(s4)
                if len(sounds) == before:
                    row["silent_inputs"].append(f"tap on {type(targets[0]).__name__}")
        except Exception as exc:
            where = "enter" if row["enter"] is None else "input"
            row[where if where == "enter" else "error"] = f"{type(exc).__name__}: {exc}"
            row["traceback"] = traceback.format_exc()[-2500:]
        results.append(row)
        runtime_globals.INPUT_MODE = runtime_globals.KEYBOARD_MODE
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=1)


# ---------------------------------------------------------------- parent
def markdown(rows):
    res_list = sorted({r["res"] for r in rows}, key=lambda s: (int(s.split("x")[0]) * int(s.split("x")[1]), s))
    scenes = list(dict.fromkeys(r["scene"] for r in rows))
    lines = ["# Scene sweep", "", "Cell: frame ms (mean) when entered and fully painted; otherwise the failure.", "",
             "| Scene | " + " | ".join(res_list) + " |", "|---|" + "---|" * len(res_list)]
    for s in scenes:
        cells = []
        for res in res_list:
            r = next((x for x in rows if x["scene"] == s and x["res"] == res), None)
            if r is None:
                cells.append("")
            elif r["enter"] != "ok":
                cells.append("**ENTER**")
            elif r["paint"] != "ok":
                cells.append(f"**paint** {r['frame_ms']}")
            else:
                cells.append(f"{r['frame_ms']}")
        lines.append(f"| {s} | " + " | ".join(cells) + " |")
    lines += ["", "## Failures", ""]
    for r in rows:
        if r["enter"] != "ok" or r.get("error"):
            lines.append(f"- **{r['scene']} @ {r['res']}**: {r['enter'] if r['enter'] != 'ok' else r.get('error')}")
    lines += ["", "## Unpainted canvas (UI-05)", ""]
    for r in rows:
        if r["enter"] == "ok" and r["paint"] != "ok":
            lines.append(f"- {r['scene']} @ {r['res']}: {r['paint']}")
    lines += ["", "## Off-canvas / outside the UI square (UI-03, UI-07)", ""]
    for r in rows:
        for b in r["bounds"][:5]:
            lines.append(f"- {r['scene']} @ {r['res']}: {b}")
        for b in r["square"][:3]:
            lines.append(f"- {r['scene']} @ {r['res']}: {b}")
    lines += ["", "## Focus shown in touch mode (UI-02)", ""]
    seen = set()
    for r in rows:
        if r["touch_focus"] and r["scene"] not in seen:
            seen.add(r["scene"])
            lines.append(f"- {r['scene']}: {', '.join(r['touch_focus'])}")
    lines += ["", "## Inputs that played no sound (UI-06)", ""]
    seen = set()
    for r in rows:
        if r["silent_inputs"] and r["scene"] not in seen:
            seen.add(r["scene"])
            lines.append(f"- {r['scene']}: {', '.join(r['silent_inputs'])}")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--res", nargs="*", default=RESOLUTIONS)
    ap.add_argument("--scene", nargs="*", default=list(SCENES))
    ap.add_argument("--json")
    ap.add_argument("--md")
    ap.add_argument("--child", nargs=2, metavar=("RES", "OUT"))
    ap.add_argument("-j", type=int, default=max(1, min(len(RESOLUTIONS), (os.cpu_count() or 2) - 1)))
    args = ap.parse_args()
    if args.child:
        child(args.child[0], args.scene, args.child[1])
        return
    tmp = temp_dir("sweep_out_")
    procs = []
    pending = list(args.res)
    rows = []
    while pending or procs:
        while pending and len(procs) < args.j:
            res = pending.pop(0)
            out = os.path.join(tmp, f"{res}.json")
            p = subprocess.Popen([sys.executable, "-B", os.path.abspath(__file__), "--child", res, out,
                                  "--scene", *args.scene], cwd=ROOT, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
            procs.append((res, out, p))
        for item in list(procs):
            res, out, p = item
            if p.poll() is None:
                continue
            procs.remove(item)
            log = p.stdout.read()
            if os.path.isfile(out):
                rows += json.load(open(out, encoding="utf-8"))
            else:
                rows.append({"res": res, "scene": "(process)", "enter": f"child crashed: exit {p.returncode}",
                             "paint": None, "bounds": [], "square": [], "touch_focus": [], "silent_inputs": [],
                             "frame_ms": None, "worst_ms": None, "traceback": log[-3000:]})
        time.sleep(0.2)
    rows.sort(key=lambda r: (list(SCENES).index(r["scene"]) if r["scene"] in SCENES else 99, r["res"]))
    bad = 0
    for r in rows:
        ok = r["enter"] == "ok" and r["paint"] == "ok" and not r.get("error")
        bad += not ok
        if not ok:
            print(f"FAIL  {r['scene']:11} {r['res']:9} enter={r['enter']} paint={r['paint']} {r.get('error') or ''}"[:300])
    entered = sum(1 for r in rows if r["enter"] == "ok")
    print(f"\n{len(rows)} scene x resolution runs, {entered} entered, {bad} with enter/paint/input failures")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, indent=1)
    if args.md:
        with open(args.md, "w", encoding="utf-8") as fh:
            fh.write(markdown(rows))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
