#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Explore every screen a player can reach, the way a player reaches it.

Checklist UI-01, UI-02, UI-03, UI-05, UI-06, UI-10 and PERF-02, beyond the
entry screens the scene sweep sees. From a start scene (the main game by
default) a breadth-first search replays each path from the fixture save
(harness.Env.reset) and tries every input on the screen it reaches:

    keyboard   UP, DOWN, LEFT, RIGHT, A, B (keyboard, joystick and GPIO all
               arrive as these actions), in keyboard mode
    touch      a tap on every visible focusable component and on the main
               game's menu icons, in touch mode; no keys at all

A screen is the scene, its view and phase, any modal menu and the set of
visible focusable components (keyboard mode adds the focused one, since that
is what arrow keys change). Every step records:

    crash      an exception escaping a handler, update or draw
    logged     an exception caught and logged instead (graceful, but a bug)
    silent     a press or tap that played no sound (every input answers with
               "menu" or "cancel" outside a minigame or battle in play)
    slow       handling the input plus its first frame took over 100 ms
    paint      sentinel pixels left after drawing (UI-05)
    bounds     a component off the canvas or outside the 240 square (UI-03/07)
    focus      a component focused in touch mode on arrival (UI-02)

Comparing the keyboard and touch crawls shows screens one input family
cannot reach (UI-01) and touch dead ends (no tap leaves the screen).

    python -B tests/release/menu_crawl.py [--mode keyboard touch] [--start game] [--res 240x240]
        [--depth 7] [--max-states 300] [--json PATH] [--md PATH]

Each mode runs in its own process. Read-only: the save is a temporary copy and
the network is refused.
"""
import argparse
import collections
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "support"))
from paths import ROOT, temp_dir, REPORTS  # noqa: E402
sys.path.insert(0, HERE)

KEYS = ("UP", "DOWN", "LEFT", "RIGHT", "A", "B")
FRAMES_PER_STEP = 10
#: An input's animation may run this long before the screen it leads to is read (2 s).
SETTLE_MAX = 60
SETTLE_FRAMES = 4
SLOW_MS = 100
#: Frames a touch dead-end candidate is left alone to see whether it ends by itself (~20 s).
IDLE_FRAMES = 600
#: Real time given to request threads per settle step on the online fixture.
ONLINE_WAIT = 0.03
#: Longest real wait for the game's request threads after one input (online fixture).
THREAD_WAIT = 2.0
#: The "input" a battle or minigame in play gets: time (30 s of frames).
WAIT_ACTION = ("wait", 900, "wait 30 s")
#: Longest input sequence tried, whatever the screen count.
MAX_PATH = 16
SIGNATURE_ATTRS = ("current_view_name", "phase", "mode", "current_phase", "stage_name")


# ---------------------------------------------------------------- one crawl
class Crawler:
    def __init__(self, mode, start, res, depth, max_states, time_budget, fixture="default"):
        from harness import Env
        self.online = fixture == "online"
        if self.online:
            self.env = Env(res, network="local")
            start_fake_omninet(self.env)
        else:
            self.env = Env(res, fixture=fixture)
        # threads that outlive any one input (the fake server's, a game
        # poller): never waited for
        self._lasting_threads = set(threading.enumerate())
        self.fixture = fixture
        rg = self.env.rg
        self.mode = mode
        self.input_mode = rg.KEYBOARD_MODE if mode == "keyboard" else rg.TOUCH_MODE
        self.start, self.depth, self.max_states = start, depth, max_states
        self.deadline = time.time() + time_budget
        self.screens = {}            # signature -> {"path", "label", checks...}
        self.edges = collections.defaultdict(set)
        self.findings = []           # dicts
        self._seen_findings = set()
        self.replays = 0

    # .................................................. describing a screen
    def label(self, game):
        scene = game.scene
        parts = [type(scene).__name__]
        for obj in (scene, getattr(scene, "current_view", None)):
            if obj is None:
                continue
            if obj is not scene:
                parts.append(type(obj).__name__)
            for a in SIGNATURE_ATTRS:
                v = getattr(obj, a, None)
                if isinstance(v, (str, int)) and not isinstance(v, bool):
                    parts.append(f"{a}={v}")
        from harness import managers
        for mgr in managers(scene):
            menu = getattr(mgr, "active_menu", None)
            if menu is not None and getattr(menu, "visible", False):
                parts.append(f"menu={type(menu).__name__}")
        return " / ".join(dict.fromkeys(parts))

    def signature(self, game):
        from harness import focusables
        scene = game.scene
        comps = sorted(comp_key(c) for c in focusables(scene))
        sig = [self.label(game), "|".join(comps)]
        # a text field holding focus has its on-screen keyboard open over the screen
        typing = [comp_key(c) for c in focusables(scene)
                  if getattr(c, "sticky_focus", False) and getattr(c, "focused", False)]
        sig.append("typing:" + ",".join(typing) if typing else "")
        # a battle or minigame in play is a new state each time it moves on
        if game._scene_plays_own_input_sounds():
            sig.append("progress:" + "|".join(progress_marker(game)))
        if self.mode == "keyboard":
            focused = [comp_key(c)
                       for c in focusables(scene) if getattr(c, "focused", False)]
            sig.append(",".join(focused))
            if type(scene).__name__ == "SceneMainGame":
                sig.append(f"menu_index={self.env.rg.main_menu_index}")
        return tuple(sig)

    def actions(self, game):
        """Every place worth tapping on this screen (keyboard mode: the six actions)."""
        # A minigame or battle in play moves on by itself: let it run.
        waits = [WAIT_ACTION] if game._scene_plays_own_input_sounds() else []
        if self.mode == "keyboard":
            return [("key", k) for k in KEYS] + waits
        from harness import managers
        w, h = self.env.w, self.env.h
        scale = max(1, int(self.env.rg.UI_SCALE or 1))
        out, cells = [], set()

        def add(pos, name):
            x, y = int(pos[0]), int(pos[1])
            if not (0 <= x < w and 0 <= y < h):
                return
            cell = (x // (4 * scale), y // (4 * scale))      # one tap per 4x4 base pixels
            if cell not in cells:
                cells.add(cell)
                out.append(("tap", (x, y), name))

        scene = game.scene
        view = getattr(scene, "current_view", None)
        comps = []
        for mgr in managers(scene):
            for c in mgr.components:
                if not getattr(c, "visible", True):
                    continue
                if getattr(c, "focusable", False) or callable(getattr(c, "on_click_callback", None)) \
                        or hasattr(c, "handle_mouse_click"):
                    comps.append(c)
        for c in comps:
            add(c.rect.center, comp_name(c))
        # areas drawn inside one component (PetList's EXIT and arrows, grid cells)
        step = 24 * scale
        for c in comps:
            r = c.rect
            nx, ny = max(1, min(10, r.width // step)), max(1, min(4, r.height // step))
            if nx > 1 or ny > 1:
                for i in range(nx):
                    for j in range(ny):
                        add((r.left + (i + 0.5) * r.width / nx, r.top + (j + 0.5) * r.height / ny),
                            f"{comp_name(c)} part {i + 1}/{nx},{j + 1}/{ny}")
        # hit areas a scene draws itself (the main menu's icons, a view's USE /
        # BACK, the touch SKIP pill): Rect attributes and rect getters of the
        # scene, its view and their helper objects
        component_ids = {id(c) for mgr in managers(scene) for c in mgr.components}
        for owner in hit_area_owners(scene, view, component_ids):
            for attr, rect in rects_of(owner):
                add(rect.center, f"{type(owner).__name__}.{attr}")
        # minigames and full-screen scenes take a tap anywhere
        add((w // 2, h // 2), "screen centre")
        add((w // 10, h // 10), "top-left corner")
        return out + waits

    # .................................................. running inputs
    def settle(self, game, first=0):
        """Run frames until the screen stops changing (up to SETTLE_MAX frames).
        Online, a view fills in when its request thread answers: wait for the
        game's threads as a player waits for the screen, then settle again."""
        self._settle_frames(game, first)
        if self.online:
            # also when every thread is done already: one may have answered
            # after the last frame, and only a frame applies its result
            self.await_threads()
            self._settle_frames(game, 0)

    def await_threads(self):
        """Wait (real time, up to THREAD_WAIT) for threads started since the
        crawl began. Returns whether there were any."""
        started = [t for t in threading.enumerate() if t not in self._lasting_threads and t.is_alive()]
        if not started:
            return False
        end = time.time() + THREAD_WAIT
        for t in started:
            t.join(max(0.0, end - time.time()))
        # still running after the wait: a poller, not a request
        self._lasting_threads.update(t for t in started if t.is_alive())
        return True

    def _settle_frames(self, game, first=0):
        env = self.env
        done = first
        last = self.label(game)
        while done < SETTLE_MAX:
            env.frames(game, FRAMES_PER_STEP)
            done += FRAMES_PER_STEP
            if self.online:
                time.sleep(ONLINE_WAIT)       # views update from request threads
            now = self.label(game)
            if now == last and done >= FRAMES_PER_STEP:
                return
            last = now

    def send(self, game, action):
        if action[0] == "key":
            self.env.press(game, action[1])
        elif action[0] == "wait":
            self.env.frames(game, action[1])
        else:
            self.env.tap(game, action[1])

    def replay(self, path):
        """Fresh fixture, start scene, then every action of *path*. Returns the game."""
        env = self.env
        env.reset(input_mode=self.input_mode)
        self.replays += 1
        game = env.game(self.start)
        env.frames(game, SETTLE_FRAMES)
        if self.online:
            # the menu's availability checks run in threads
            self.settle(game)
        for action in path:
            with __import__("harness").quiet():
                self.send(game, action)
            self.settle(game)
        return game

    def finding(self, kind, screen, action, detail, path, trace=None):
        # one slow finding per screen: the same slow load answers every tap on it
        key = (kind, screen) if kind == "slow" else (kind, screen, detail[:120])
        if key in self._seen_findings:
            return
        self._seen_findings.add(key)
        self.findings.append({"mode": self.mode, "kind": kind, "screen": screen, "action": describe(action),
                              "detail": detail, "path": [a if isinstance(a, str) else describe(a) for a in path],
                              "trace": trace})

    def check_screen(self, game, sig, path):
        """Once per new screen: paint, bounds, touch focus."""
        env = self.env
        from harness import managers, focusables
        label = sig[0]
        left = env.unpainted()
        if left:
            self.finding("paint", label, None, f"{left} px never painted", path)
        w, h = env.w, env.h
        for mgr in managers(game.scene):
            for c in mgr.components:
                if not getattr(c, "visible", True):
                    continue
                r, b = c.rect, getattr(c, "base_rect", None)
                name = f"{type(c).__name__}@{tuple(b if b is not None else r)}"
                if r.left < 0 or r.top < 0 or r.right > w or r.bottom > h:
                    self.finding("bounds", label, None, f"{name} -> {tuple(r)} off the {w}x{h} canvas", path)
                if b is not None and not getattr(c, "use_screen_coordinates", False) and \
                        (b.left < 0 or b.top < 0 or b.right > 240 or b.bottom > 240):
                    self.finding("bounds", label, None, f"{name} outside the 240 square", path)
        if self.mode == "touch":
            shown = highlighted_in_touch(self.env, game.scene)
            if shown:
                self.finding("focus", label, None, "focus highlight drawn in touch mode: " + ", ".join(shown), path)

    def step(self, path, action):
        """Replay *path*, try *action*; returns the signature reached (None on a crash)."""
        env = self.env
        try:
            game = self.replay(path)
        except Exception as exc:     # a path that worked before failed on replay
            self.finding("replay", "?", action, f"{type(exc).__name__}: {exc}", path, traceback.format_exc()[-1500:])
            return None, None
        before_sig = self.signature(game)
        if action[0] == "key":
            from harness import focusables
            focused = [comp_name(c) for c in focusables(game.scene) if getattr(c, "focused", False)]
            if focused:
                action = ("key", action[1], focused[0])
        exempt = game._scene_plays_own_input_sounds() or action[0] == "wait"   # play, or just time
        sounds, logs = len(env.sounds), len(env.logs)
        t = time.perf_counter()
        try:
            with __import__("harness").quiet():
                self.send(game, action)
            env.frames(game, 1)
            spent = (time.perf_counter() - t) * 1000
            self.settle(game, first=1)
        except Exception as exc:
            self.finding("crash", before_sig[0], action, f"{type(exc).__name__}: {exc}", path + [action],
                         traceback.format_exc()[-2500:])
            return None, None
        try:
            after_sig = self.signature(game)
        except Exception as exc:
            self.finding("harness", before_sig[0], action, f"could not describe the screen: {exc!r}", path + [action],
                         traceback.format_exc()[-1500:])
            return None, None
        new_path = path + [action]
        for line in env.error_logs(logs):
            self.finding("logged", before_sig[0], action, line[:300], new_path)
        if type(game.scene).__name__ == "SceneError":
            self.finding("crash", before_sig[0], action, "reached the error scene", new_path)
        if spent > SLOW_MS and action[0] != "wait":
            self.finding("slow", before_sig[0], action, f"{spent:.0f} ms to handle and draw", new_path)
        if not exempt and len(env.sounds) == sounds:
            self.finding("silent", before_sig[0], action,
                         "changed the screen or focus without a sound" if after_sig != before_sig
                         else "did nothing and played no sound (expected cancel)", new_path)
        return after_sig, game

    def run(self):
        game = self.replay([])
        root = self.signature(game)
        self.screens[root] = {"path": [], "label": root[0], "path_actions": []}
        self.check_screen(game, root, [])
        queue = collections.deque([(root, [], 0)])
        # Screens whose taps were tried. One at the depth limit never is, so
        # "no tap leaves it" says nothing about it (the replay and online
        # fixtures' shallower depths flagged seven such screens until 2026-10-17).
        explored = set()
        while queue and time.time() < self.deadline and len(self.screens) < self.max_states:
            sig, path, hops = queue.popleft()
            if hops >= self.depth or len(path) >= MAX_PATH:
                continue
            try:
                game = self.replay(path)
                candidates = self.actions(game)
            except Exception:
                continue
            explored.add(sig[0])
            for action in candidates:
                if time.time() > self.deadline or len(self.screens) >= self.max_states:
                    break
                new_sig, game = self.step(path, action)
                if new_sig is None:
                    continue
                self.edges[sig].add(new_sig)
                if new_sig not in self.screens:
                    new_path = path + [action]
                    self.screens[new_sig] = {"path": [describe(a) for a in new_path], "label": new_sig[0],
                                             "path_actions": new_path}
                    self.check_screen(game, new_sig, new_path)
                    # moving focus inside a screen is free; entering another screen costs a hop
                    queue.append((new_sig, new_path, hops + (new_sig[0] != sig[0])))
        complete = not queue
        # touch dead ends: screens no tap leaves, and that do not end on their own
        dead, timed, unexplored = [], [], []
        if self.mode == "touch":
            exits, first = collections.defaultdict(set), {}
            for sig, info in self.screens.items():
                first.setdefault(info["label"], info["path_actions"])
                exits[info["label"]] |= {self.screens[t]["label"] for t in self.edges.get(sig, ()) if t in self.screens}
            for label, path in first.items():
                if not path or exits[label] - {label}:
                    continue
                if label not in explored:
                    unexplored.append(label)
                    continue
                try:
                    game = self.replay(path)
                    marks = {progress_marker(game)}
                    for _ in range(IDLE_FRAMES // 30):                 # does it end by itself?
                        self.env.frames(game, 30)
                        marks.add(progress_marker(game))
                        if self.label(game) != label:
                            break
                    if self.label(game) == label and len(marks) > 2:   # still moving on (rounds of a battle)
                        timed.append(label)
                        continue
                    if self.label(game) == label:
                        centre = ("tap", (self.env.w // 2, self.env.h // 2), "screen centre")
                        for _ in range(2 * IDLE_FRAMES // 30):         # or with a tap a second?
                            with __import__("harness").quiet():
                                self.send(game, centre)
                            self.env.frames(game, 30)
                            if self.label(game) != label:
                                break
                    (timed if self.label(game) != label else dead).append(label)
                except Exception as exc:
                    self.finding("crash", label, ("tap", (0, 0), "waiting / tapping the screen centre"),
                                 f"{type(exc).__name__}: {exc}", [describe(a) for a in path],
                                 traceback.format_exc()[-2500:])
        reached = {v["label"].split(" / ")[0] for v in self.screens.values()}
        import scene_sweep
        never = sorted(n for n, (_, cls) in scene_sweep.SCENES.items() if cls not in reached)
        return {"mode": self.mode, "fixture": self.fixture, "start": self.start, "res": f"{self.env.w}x{self.env.h}",
                "never_reached": never,
                "complete": complete, "replays": self.replays,
                "screens": [{"label": v["label"], "path": v["path"]} for v in self.screens.values()],
                "labels": sorted({v["label"] for v in self.screens.values()}),
                "dead_ends": sorted(set(dead)), "timed_exits": sorted(set(timed)),
                "unexplored": sorted(set(unexplored)), "findings": self.findings}


def highlighted_in_touch(env, scene):
    """Components that draw a focus or hover highlight in touch mode (UI-02).

    Each visible focusable component is rendered unfocused with the pointer
    away, then focused with the pointer on it; different pixels mean the
    highlight shows. Text fields (sticky focus) are exempt: their caret and
    keyboard are the point. A component whose two unfocused renders differ is
    animating and is left out rather than guessed at.
    """
    from harness import focusables, quiet
    rg = env.rg
    pointer = rg.game_input.mouse_position
    shown = []
    for c in focusables(scene):
        if getattr(c, "sticky_focus", False) or not hasattr(c, "render"):
            continue
        was = c.focused
        try:
            with quiet():
                frames = []
                for focused, pos in ((False, (-999, -999)), (False, (-999, -999)), (True, tuple(c.rect.center))):
                    rg.game_input.mouse_position = pos
                    c.focused = focused
                    for attr in ("static_layer", "cached_surface"):
                        if hasattr(c, attr):
                            setattr(c, attr, None)
                    c.needs_redraw = True
                    surf = c.render()
                    frames.append(env.pygame.image.tostring(surf, "RGBA") if surf is not None else b"")
        except Exception:
            continue
        finally:
            c.focused = was
            c.needs_redraw = True
            rg.game_input.mouse_position = pointer
        if frames[0] == frames[1] and frames[2] != frames[0]:
            shown.append(comp_name(c))
    return shown


def start_fake_omninet(env):
    """The `online` fixture: tests/support/fake_omninet.py on 127.0.0.1, an
    account logged in after every reset, something in each shop list and an
    arena season (see tests/game/online/README.md). Nothing leaves the machine."""
    from fake_omninet import FakeOmninet, isolate_client, login_service, module_zip
    from paths import MODULES
    fake = FakeOmninet(arena_modules=["DMC", "PENC", "IC", "VB"]).start()
    isolation = isolate_client(env, fake)
    svc = isolation.__enter__()
    # keep the context manager alive: when it is collected its generator
    # closes and puts the real URLs back
    fake.crawl_isolation = isolation
    account = fake.add_account("Crawler", coins=500)
    if os.path.isdir(os.path.join(MODULES, "DMOG")):
        fake.add_module("DMOG", module_zip(os.path.join(MODULES, "DMOG")), version="1.0.3")
    fake.add_item("Super Meat", price=10, json_data={"status": "hunger", "amount": 1})
    fake.add_cosmetic("Starry Night", price=20)
    fake.start_season("Crawl Season")
    fake.add_opponent_team("Rival", seed=7, modules=["DMC"])

    def log_in():
        login_service(svc, fake, account)
        env.gg.game_mode = env.gg.GAME_MODE_PROGRESS
        env.gg.player_id = account["id"]
        env.gg.coins = fake.account(account)["coins"]
    env.after_reset.append(log_in)
    return fake


def progress_marker(game):
    """The phases of whatever a screen is running (scene, view, minigame, battle):
    a screen whose marker keeps changing is progressing, not stuck."""
    scene = game.scene
    view = getattr(scene, "current_view", None)
    objs = [scene, view, getattr(scene, "mode", None), getattr(view, "battle_encounter", None),
            getattr(scene, "battle_encounter", None)]
    return tuple(str(getattr(o, a, None)) for o in objs if o is not None
                 for a in ("phase", "round", "current_round", "area"))


def comp_name(c):
    """A component as a report names it: its class, its text, where it sits."""
    text = ""
    for attr in ("text", "label", "title"):
        v = getattr(c, attr, None)
        if isinstance(v, str) and v.strip():
            text = " '" + v.strip().replace("\n", " ")[:24] + "'"
            break
    rect = getattr(c, "base_rect", None) or getattr(c, "rect", None)
    try:
        where = f"@{tuple(rect)[:2]}"
    except TypeError:
        where = ""
    return f"{type(c).__name__}{text}{where}"


RECT_NAME = re.compile(r"(^|_)(\w*_)?rects?$")
SKIP_GETTER = re.compile(r"^_?(set|update|rebuild|calc|compute|recalc|draw|render|scale|move)")


def hit_area_owners(scene, view, component_ids):
    """The scene, its view and the helper objects they hold (not UI components)."""
    owners, seen = [], set()
    for root in (scene, view):
        if root is None or id(root) in seen:
            continue
        seen.add(id(root))
        owners.append(root)
        for v in vars(root).values():
            if id(v) in seen or id(v) in component_ids or not hasattr(v, "__dict__"):
                continue
            mod = type(v).__module__.split(".")[0]
            if mod in ("ui", "scenes", "training", "battle") and type(v).__name__ != "UIManager":
                seen.add(id(v))
                owners.append(v)
    return owners


def rects_of(owner):
    """(name, Rect) for each Rect attribute and zero-argument rect getter of *owner*."""
    import inspect
    import pygame
    out = []
    for name in dir(owner):
        if name.startswith("__") or not RECT_NAME.search(name) or SKIP_GETTER.search(name):
            continue
        try:
            value = getattr(owner, name)
            if callable(value):
                params = [p for p in inspect.signature(value).parameters.values()
                          if p.default is p.empty and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
                if params:
                    continue
                with __import__("harness").quiet():
                    value = value()
        except Exception:
            continue
        values = value if isinstance(value, (list, tuple)) else [value]
        for i, v in enumerate(values):
            if isinstance(v, pygame.Rect) and v.width > 0 and v.height > 0:
                out.append((name if len(values) == 1 else f"{name}[{i}]", v))
    return out


def comp_key(c):
    rect = getattr(c, "base_rect", None) or getattr(c, "rect", None)
    try:
        return f"{type(c).__name__}@{tuple(rect)}"
    except TypeError:
        return type(c).__name__


def describe(action):
    if action is None:
        return None
    if action[0] == "key":
        return action[1] + (f" (focus: {action[2]})" if len(action) > 2 else "")
    if action[0] == "wait":
        return action[2]
    return f"tap {action[2]}"


# ---------------------------------------------------------------- report
#: Where each fixture starts when --start is not given: a party plays from
#: the main game; nobody to play with starts where a new player lands.
FIXTURE_START = {"empty": "egg", "boot": "boot", "replay": "battle_pvp", "online": "connect"}
#: Fixtures that exist to reach one place (the boot scene, a replay played
#: out to the arena screens) stop sooner: past it they repeat `default`.
FIXTURE_DEPTH = {"boot": 3, "replay": 3, "online": 4}


def markdown(results):
    lines = ["# Menu crawl", ""]
    for r in results:
        lines.append(f"- **{r['mode']}**, fixture `{r.get('fixture', 'default')}`, from `{r['start']}` at {r['res']}: "
                     f"{len(r['labels'])} distinct screens ({len(r['screens'])} states), {r['replays']} replays, "
                     f"{'complete' if r['complete'] else 'stopped at the depth/state/time limit'}")
    fixtures = list(dict.fromkeys(r.get("fixture", "default") for r in results))
    lines += ["", "## Reachability by input (UI-01)", ""]
    for fx in fixtures:
        by_mode = {r["mode"]: set(r["labels"]) for r in results if r.get("fixture", "default") == fx}
        if "keyboard" in by_mode and "touch" in by_mode:
            only_k = sorted(by_mode["keyboard"] - by_mode["touch"])
            only_t = sorted(by_mode["touch"] - by_mode["keyboard"])
            lines.append(f"- `{fx}`: keyboard only: {', '.join(only_k) or 'none'}; touch only: {', '.join(only_t) or 'none'}")
    reached = set()
    for r in results:
        reached |= {lab.split(" / ")[0] for lab in r["labels"]}
    ran = [r for r in results if r["screens"]]
    never = sorted(set.intersection(*[set(r.get("never_reached", [])) for r in ran])) if ran else ["(no crawl ran)"]
    lines += ["", "Scenes no fixture reached: " + (", ".join(never) or "none")]
    dead = sorted({(r.get("fixture", "default"), d) for r in results for d in r.get("dead_ends", [])})
    if dead:
        lines += ["", "## Touch dead ends: no tap leaves, and it does not end by itself", ""]
        lines += [f"- `{fx}` {d}" for fx, d in dead]
    unexplored = sorted({(r.get("fixture", "default"), d) for r in results for d in r.get("unexplored", [])})
    if unexplored:
        lines += ["", "Reached at the depth limit, taps not tried (not judged as dead ends): "
                  + ", ".join(f"`{fx}` {d}" for fx, d in unexplored)]
    timed = sorted({d for r in results for d in r.get("timed_exits", [])})
    if timed:
        lines += ["", "Screens that end on their own or after repeated taps within 60 s (not dead ends): " + ", ".join(timed)]
    kinds = [("crash", "Crashes (UI-10)"), ("logged", "Exceptions caught and logged (UI-10)"),
             ("replay", "Paths that did not replay"), ("harness", "Harness problems"),
             ("paint", "Unpainted canvas (UI-05)"),
             ("bounds", "Off canvas / outside the square (UI-03, UI-07)"),
             ("focus", "Focus highlight drawn in touch mode (UI-02)"), ("slow", "Slow inputs (PERF-02)"),
             ("silent", "Inputs that changed the screen without a sound (UI-06)")]
    for kind, title in kinds:
        fs, seen = [], set()
        for r in results:
            for f in r["findings"]:
                key = (f["kind"], f["screen"], f["action"], f["detail"][:120])
                if f["kind"] == kind and key not in seen:
                    seen.add(key)
                    fs.append((r.get("fixture", "default"), f))
        if not fs:
            continue
        lines += ["", f"## {title} ({len(fs)})", ""]
        for fx, f in fs:
            lines.append(f"- [{f['mode']}, `{fx}`] **{f['screen']}**{' on ' + f['action'] if f['action'] else ''}: "
                         f"{f['detail']}  \n  path: {' > '.join(f['path']) or '(start)'}")
            if f.get("trace") and kind in ("crash", "replay", "harness"):
                tail = [ln for ln in f["trace"].strip().splitlines() if ln.strip()][-4:]
                lines.append("  ```\n  " + "\n  ".join(tail) + "\n  ```")
    lines += ["", "## Screens reached", ""]
    for r in results:
        lines += [f"### {r['mode']}, `{r.get('fixture', 'default')}`", ""]
        first = {}
        for s in r["screens"]:
            first.setdefault(s["label"], s["path"])
        lines += [f"- {label}: {' > '.join(p) or '(start)'}" for label, p in sorted(first.items())]
        lines.append("")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", nargs="*", default=["keyboard", "touch"], choices=["keyboard", "touch"])
    ap.add_argument("--fixture", nargs="*", default=["default"],
                    help="starting states (harness.FIXTURES), or 'all'")
    ap.add_argument("--start", help="start scene; default: the main game, egg selection for 'empty'")
    ap.add_argument("--res", default="240x240")
    ap.add_argument("--depth", type=int, default=6)
    ap.add_argument("--max-states", type=int, default=800)
    ap.add_argument("--time", type=int, default=1500, help="seconds per crawl")
    ap.add_argument("-j", type=int, default=max(1, min(4, (os.cpu_count() or 2) - 2)),
                    help="crawls at once (default: up to 4; each loads every module)")
    ap.add_argument("--json")
    ap.add_argument("--md")
    ap.add_argument("--child", nargs=3, metavar=("MODE", "FIXTURE", "OUT"))
    args = ap.parse_args()
    if args.child:
        mode, fixture, out = args.child
        start = args.start or FIXTURE_START.get(fixture, "game")
        depth = min(args.depth, FIXTURE_DEPTH.get(fixture, args.depth))
        result = Crawler(mode, start, args.res, depth, args.max_states, args.time, fixture).run()
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=1)
        return
    from harness import FIXTURES
    fixtures = list(FIXTURES) if "all" in args.fixture else args.fixture
    tmp = temp_dir("crawl_")
    jobs = [(fx, mode) for fx in fixtures for mode in args.mode]
    running, results = [], []

    def launch(fx, mode):
        out = os.path.join(tmp, f"{fx}_{mode}.json")
        cmd = [sys.executable, "-B", os.path.abspath(__file__), "--child", mode, fx, out,
               "--res", args.res, "--depth", str(args.depth), "--max-states", str(args.max_states),
               "--time", str(args.time)] + (["--start", args.start] if args.start else [])
        return (fx, mode, out, subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                                text=True, encoding="utf-8", errors="replace"))

    while jobs or running:
        while jobs and len(running) < args.j:
            running.append(launch(*jobs.pop(0)))
        fx, mode, out, p = running.pop(0)
        log = p.communicate()[0]
        if os.path.isfile(out):
            results.append(json.load(open(out, encoding="utf-8")))
        else:
            results.append({"mode": mode, "fixture": fx, "start": args.start or FIXTURE_START.get(fx, "game"),
                            "res": args.res, "complete": False, "replays": 0, "screens": [], "labels": [],
                            "dead_ends": [], "never_reached": [],
                            "findings": [{"mode": mode, "kind": "crash", "screen": "(crawler)", "action": None,
                                          "detail": f"crawler process died: exit {p.returncode}", "path": [],
                                          "trace": log[-3000:]}]})
    results.sort(key=lambda r: (fixtures.index(r.get("fixture", "default")), r["mode"]))
    for r in results:
        counts = collections.Counter(f["kind"] for f in r["findings"])
        print(f"{r.get('fixture', 'default'):8} {r['mode']:8} {len(r['labels']):3} screens, {len(r['screens']):4} states, "
              f"{r['replays']:5} replays, {'complete' if r['complete'] else 'limit hit'}; "
              + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=1)
    if args.md:
        with open(args.md, "w", encoding="utf-8") as fh:
            fh.write(markdown(results))
    bad = sum(1 for r in results for f in r["findings"] if f["kind"] in ("crash", "replay"))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
