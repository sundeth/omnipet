#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Tutorial crawler: the tutorial played as a player plays it (UI-11).

Every run starts the tutorial the way a player meets it and plays it with
one input family:

    keyboard  arrows to the highlighted icon or button, A to press it and
              to read on (keyboard, joystick and GPIO arrive alike)
    mouse     the pointer moved onto the highlight, then a click (MOUSE
              mode: the main game selects its icons by hover)
    touch     taps only: in the highlight, on the dialog to read on (TOUCH
              mode, as Android)

from one of these starts (fixtures):

    replay    a party of four: Settings' Replay Tutorial; ends in the game
    first     no pets: a first run; ends in egg selection
    shop      no pets, no modules, Progress Mode logged in to a fake
              Omninet that sells DMOG: the first run of a fresh build,
              which ends in the Connect shop; ends in egg selection with
              the module bought and installed
    shop-free the same in Free Mode (downloads, never buys)

The player does what the screen shows: it reads on when a dialog waits;
acts on the highlight (what the overlay leaves undimmed, as drawn) once
it has faded in: the keyboard player walks its cursor there with the
arrows; where nothing is shown it waits, then, in a minigame or battle,
presses or taps as the dialog asked ("smash A"); where the tutorial lets it
choose (the first module) it takes the first row and the detail's action
button. A press that shows no effect is tried once more about 7 s later;
then the step is stuck: it is reported and the run is helped past it (the
action the step waits for is notified), so one broken step does not hide
the ones after it.

Before each run the main game and the adventure module list have been
opened once (they set up the day's quests, the event timer and each
module's area), so the save compared at the end is a player's.

Runs (--runs):

    play      the whole tutorial at every resolution (--res)
    fumble    at every step that waits on the player, first the inputs a
              player gets wrong: B and SELECT, A with the cursor off the
              highlight, taps on other controls, a second press right
              after the right one. Each must leave the tutorial on its
              step or move it on as the right input does, in the tutorial,
              and a refused one must answer "cancel"
    skip      the playthrough replayed to the first stop of every step
              that waits on the player and skipped there: START on replay,
              the SKIP pill on the shop first run (Android's); split into
              PARTS processes

Findings (FAIL: crash, stuck, escape, end; the rest are for review):

    crash     an exception escaped an input, update or draw
    stuck     the input the tutorial shows did not move it on: what was
              pressed or tapped, and what lies under it
    escape    an input left the tutorial, or moved the scene under it on
              without the tutorial (it then waits for something done)
    end       after the last step or a skip: the scene the game routes to,
              the party back, the Tutorial module unloaded, the battle's
              scene exit restored (the tutorial patches it), show_tutorial
              off in the save
    save      the save after the tutorial differs from the save before it
              in something besides show_tutorial (the module bought in
              the shop fixtures excepted); files added to the save folder
    logged    an exception caught and logged
    sound     a refused input played "menu" instead of "cancel"; a press
              in a minigame or battle got the dispatcher's "cancel" (UI-06)
    overlap   the touch SKIP pill lies over a dialog or the highlight, so
              a tap meant for them skips the tutorial
    paint     sentinel pixels left after a frame (UI-05)

    python -B tests/release/tutorial_crawl.py [--runs play fumble skip]
        [--family keyboard mouse touch] [--fixture replay first shop shop-free]
        [--res 240x240 ...] [-j N] [--out DIR] [--quiet]

Writes <out>/tutorial_crawl.json and tutorial_crawl.md (default
tmp/release-reports/tutorial/). Each run is its own process; the save is a
temporary copy and the network is refused (the shop fixtures reach only the
fake server on 127.0.0.1, whose module installs go to a temporary folder).
Exit 1 on any FAIL finding.
"""
import argparse
import collections
import glob
import hashlib
import json
import os
import pickle
import re
import shutil
import subprocess
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
for _p in (os.path.join(TESTS, "support"), os.path.join(TESTS, "game", "online")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from paths import MODULES, REPORTS, ROOT, temp_dir  # noqa: E402

FAMILIES = ("keyboard", "mouse", "touch")
FIXTURES = ("replay", "first", "shop", "shop-free")
RESOLUTIONS = ("240x240", "480x480", "320x240", "800x480")
RUNS = ("play", "fumble", "skip")
#: The scene each start ends in: a party plays on, nobody to play with picks
#: an egg (or, with no module installed, is sent to the shop: SceneConnect).
NEXT_SCENE = {"replay": "SceneMainGame", "first": "SceneEggSelection",
              "shop": "SceneEggSelection", "shop-free": "SceneEggSelection"}
#: Save keys the tutorial may change: show_tutorial (it is done), the
#: Android offline record, and in the shop fixtures what buying a module does.
MAY_CHANGE = {"show_tutorial", "android_offline"}
SHOP_CHANGES = {"purchases", "coins", "shop_items_data", "shop_access", "currency"}
#: Frames a player gives a press or tap before trying it again (about 7 s:
#: longer than the main game's wash, which a second press would restart).
RETRY = 200
#: Tries of the shown input before the step is stuck.
TRIES = 2
#: Frames a step with nothing shown is watched before the player presses anyway (5 s).
PATIENCE = 150
#: Frames with nothing changing and nothing left to try: stuck (20 s).
IDLE_STUCK = 600
#: Arrow presses the keyboard player spends looking for the highlighted control.
MAX_MOVES = 16
#: A run longer than this (about 11 minutes of play) has lost its way.
MAX_FRAMES = 20000
#: Real time a request thread of the shop fixtures is given before a frame.
WORKER_WAIT = 5.0
FAIL_KINDS = ("crash", "stuck", "escape", "end")
ARROWS = ("UP", "DOWN", "LEFT", "RIGHT")


class Stop(Exception):
    """The skip point is reached."""


# ---------------------------------------------------------------- one run
class Player:
    """Plays one tutorial run with one input family (see the module doc)."""

    def __init__(self, env, family, fixture, run, fake=None):
        self.env, self.family, self.fixture, self.run = env, family, fixture, run
        self.fake = fake
        self.rg, self.gg, self.pygame = env.rg, env.gg, env.pygame
        self.findings, self._seen = [], set()

    # .............................................................. start
    def start(self, stop_at=None):
        """A fresh tutorial from the fixture save. *stop_at*: the number of
        the stop (a state that waits on the player) to end the play at."""
        env, rg, gg = self.env, self.rg, self.gg
        mode = {"keyboard": rg.KEYBOARD_MODE, "mouse": rg.MOUSE_MODE, "touch": rg.TOUCH_MODE}[self.family]
        env.reset(input_mode=mode)
        # A skip mid-battle leaves the tutorial's patch on this module global
        # (reported where it happened); the next replay starts without it.
        import battle.battle_encounter as be
        from utils import scene_utils
        be.change_scene = scene_utils.change_scene
        if self.fixture.startswith("shop"):
            self._shop_fixture()
        gg.show_tutorial = True
        from harness import quiet
        with quiet():
            # The main game sets up the day's quests and the event timer the
            # first time it is shown, and the adventure module list gives
            # every loaded module its area 1: the baseline has them, as a
            # player's save has.
            from scenes.scene_maingame import SceneMainGame
            from scenes.scene_battle import SceneBattle
            SceneMainGame()
            SceneBattle()._change_view("adventure_module_selection")
            gg.save()
        self.before_party = [id(p) for p in gg.pet_list]
        self.before_names = [p.name for p in gg.pet_list]
        self.before_save = save_summary(gg)
        self.before_files = folder_snapshot(env.save_root)
        self.stop_at = stop_at
        self.stops = []              # (state, step index, label) of every state that waited on the player
        self.assisted = []
        self.frame = 0
        self.last_text = ""
        self.ended = None
        self.log_mark = 0
        self.last_try = "the shown input"
        self.fumbled_at = None
        self.screens_checked = set()
        self.game = env.game("tutorial")
        self.frames(2)

    def _shop_fixture(self):
        """No modules and no pets (a fresh build); Progress Mode logged in, or Free Mode."""
        from fake_omninet import login_service, modules_dir, reset_service
        from online_ui import progress_mode
        rg, gg, fake = self.rg, self.gg, self.fake
        folder = modules_dir()                 # the module installed by the last run goes
        for name in os.listdir(folder):
            shutil.rmtree(os.path.join(folder, name), ignore_errors=True)
        rg.game_modules = {}
        gg.pet_list = []
        svc = fake.svc
        reset_service(svc)
        if self.fixture == "shop":
            acc = fake.add_account(f"Learner{len(fake.accounts)}", coins=0)
            login_service(svc, fake, acc)
            progress_mode(self.env, acc["id"])
            gg.coins = 0
        else:
            gg.game_mode = gg.GAME_MODE_FREE

    # .............................................................. looking
    def tutorial(self):
        scene = self.game.scene
        return scene if type(scene).__name__ == "SceneTutorial" else None

    def embedded(self, t):
        e = t.embedded_scene
        return (type(e).__name__ if e is not None else None, getattr(e, "current_view_name", None))

    def where(self, t):
        name, view = self.embedded(t)
        return name + (f" / {view}" if view else "") if name else "(no scene)"

    def state_key(self, t):
        d = t.dialog if t.dialog.is_active() else t.dialog_top if t.dialog_top.is_active() else None
        return (t.current_step_index, t.waiting_for_action, d.current_message if d else None,
                bool(d and d.is_waiting()), id(t.embedded_scene), self.embedded(t)[1], self.progress(t))

    def progress(self, t):
        """The phases of what the embedded scene runs (a minigame, a battle, a
        shop list or detail): a wait whose phases move on is not stuck."""
        e = t.embedded_scene
        view = getattr(e, "current_view", None)
        objs = (e, view, getattr(e, "mode", None), getattr(view, "battle_encounter", None))
        return tuple(str(getattr(o, a, None)) for o in objs if o is not None
                     for a in ("phase", "state", "round", "current_round"))

    def step_label(self, t):
        i = t.current_step_index
        kind, data = t.steps[i] if i < len(t.steps) else ("end", None)
        what = t.waiting_for_action or (data.__name__ if callable(data) else data if isinstance(data, (str, int)) else "")
        return f"step {i} {kind}" + (f" {what}" if what not in (None, "") else "")

    def waiting_dialog(self, t):
        for d in (t.dialog, t.dialog_top):
            if d.is_waiting():
                return d
        return None

    def holes(self, t):
        """The highlight as drawn: what the focus overlay leaves undimmed, its
        border included (every pixel that is not the overlay's dimming)."""
        f = t.focus
        if f.state != f.STATE_ACTIVE or f.overlay_surface is None or not f.focus_rects:
            return []
        dim = f.overlay_surface.get_at((0, 0))
        mask = self.pygame.mask.from_threshold(f.overlay_surface, dim, (1, 1, 1, 1))
        mask.invert()
        return [r for r in mask.get_bounding_rects() if r.width > 4 and r.height > 4]

    def near(self, rects, pos):
        """Whether *pos* is on or close to the highlight (a finger's width)."""
        margin = int(8 * (self.rg.UI_SCALE or 1))
        return any(r.inflate(margin, margin).collidepoint(pos) for r in rects)

    def chooser(self, t):
        """Where the tutorial shows nothing but lets the player choose: the
        first module of the shop list, then the detail's action button."""
        e = t.embedded_scene
        view = getattr(e, "current_view", None)
        if t.waiting_for_action != "purchase_module" or getattr(e, "current_view_name", None) != "shop_modules":
            return []
        if getattr(view, "state", None) == "list" and getattr(view, "shop_list", None) and view.shop_list.items:
            r = view.shop_list.get_item_rect(0)
            return [r.move(view.shop_list.rect.topleft)] if r else []
        button = getattr(view, "_action_button", None)
        if getattr(view, "state", None) == "detail" and button is not None and button.visible and button.enabled:
            return [button.rect]
        return []

    def cursor(self, t):
        """Where the keyboard cursor is: the main game's icon, or the focused
        component (the focused row or element of one that draws several)."""
        from harness import managers
        e = t.embedded_scene
        if type(e).__name__ == "TutorialMainGame":
            i = self.rg.main_menu_index
            rects = e.menu.icon_rects
            return rects[i] if 0 <= i < len(rects) else None
        for mgr in managers(e):
            for c in mgr.focusable_components:
                if not (getattr(c, "focused", False) and getattr(c, "visible", True)):
                    continue
                if hasattr(c, "get_focused_sub_rect"):
                    r = c.get_focused_sub_rect()
                    if r is not None:
                        return r
                if hasattr(c, "get_element_rect") and hasattr(c, "selected_index"):
                    r = c.get_element_rect(c.selected_index)
                    if r is not None:
                        return r.move(c.rect.topleft)
                return c.rect
        return None

    def under(self, t, pos):
        """What lies under a point: main game icons, components."""
        from harness import managers
        from menu_crawl import comp_name
        e = t.embedded_scene
        out = []
        if type(e).__name__ == "TutorialMainGame":
            i = e.menu.get_menu_index_at(pos)
            if i >= 0:
                out.append(f"main menu icon {i} (selected index {self.rg.main_menu_index})")
        for mgr in managers(e):
            for c in mgr.components:
                if getattr(c, "visible", True) and c.rect.collidepoint(pos):
                    out.append(comp_name(c))
        return ", ".join(out[:4]) or "nothing"

    # .............................................................. acting
    def frames(self, n):
        for _ in range(n):
            if self.fake is not None:
                from online_ui import busy_workers
                from fake_omninet import wait_for
                wait_for(lambda: not busy_workers(), WORKER_WAIT)
            self.env.frames(self.game, 1)
            self.frame += 1

    def send(self, action):
        """One input: ("key", name), ("tap", pos) or ("move", pos)."""
        env, game = self.env, self.game
        if action[0] == "key":
            env.press(game, action[1])
        elif action[0] == "move":
            self.rg.game_input.mouse_position = tuple(action[1])
            from harness import quiet
            with quiet():
                game.dispatch_input(("MOUSE_MOTION", {"pos": tuple(action[1])}))
        else:
            env.tap(game, action[1])

    def press_at(self, pos):
        """A press where the player looks: a tap, or the pointer moved there first and a click."""
        if self.family == "mouse":
            self.send(("move", pos))
            self.frames(2)
        self.send(("tap", pos))

    def read_on(self, t, dialog):
        if self.family == "keyboard":
            self.send(("key", "A"))
        else:
            self.press_at(dialog.rect.center)

    def mash_input(self):
        return ("key", "A") if self.family == "keyboard" else ("tap", (self.env.w // 2, self.env.h // 2))

    def mash(self):
        self.send(self.mash_input())

    def act_on(self, t, rects):
        """The right input for *rects*. Returns what was done, or None while
        the keyboard cursor is still on its way (an arrow was pressed)."""
        if self.family != "keyboard":
            key = self.state_key(t)
            for r in rects:                    # the item, then USE: a player taps until something happens
                self.press_at(r.center)
                self.frames(3)
                t2 = self.tutorial()
                if t2 is None or self.state_key(t2) != key:
                    return f"tap {r.center}"
            return f"taps at {', '.join(str(r.center) for r in rects)}"
        cur = self.cursor(t)
        if cur is not None and any(r.collidepoint(cur.center) for r in rects):
            self.send(("key", "A"))
            return "A"
        if self.moves >= MAX_MOVES:
            raise LookupError(f"the cursor never reached the highlight at {[tuple(r) for r in rects]} "
                              f"(it was on {tuple(cur) if cur else None})")
        target = min(rects, key=lambda r: abs(r.centerx - cur.centerx) + abs(r.centery - cur.centery)) \
            if cur is not None else rects[0]
        here = tuple(cur) if cur is not None else None
        tried = self.tried.setdefault(here, set())
        if cur is None:
            order = ["DOWN", "RIGHT", "UP", "LEFT"]
        else:
            dx, dy = target.centerx - cur.centerx, target.centery - cur.centery
            score = {"RIGHT": dx, "LEFT": -dx, "DOWN": dy, "UP": -dy}
            order = sorted(ARROWS, key=lambda a: -score[a])
        arrow = next((a for a in order if a not in tried), order[0])
        tried.add(arrow)
        self.send(("key", arrow))
        self.moves += 1
        self.frames(2)
        return None

    # .............................................................. fumbling
    def checked(self, t, action, refusal, wrong=None):
        """Send a wrong (or repeated) input and judge it. *wrong*: what it
        pressed off the highlight (it must not move the tutorial on either).
        Returns False when the run cannot go on (the tutorial was left)."""
        before_step, before_wait = t.current_step_index, t.waiting_for_action
        before_id, before_view = id(t.embedded_scene), self.embedded(t)[1]
        sounds, at = len(self.env.sounds), (self.step_label(t), self.where(t))
        self.send(action)
        self.frames(3)
        t2 = self.tutorial()
        what = describe(action) + (f" on {wrong}" if wrong else "")
        if t2 is None:
            self.finding("escape", t, f"{what} left the tutorial for {type(self.game.scene).__name__}"
                         + self.leftovers(), action=what, at=at)
            self.ended = "escape"
            return False
        moved_on = t2.current_step_index != before_step or t2.waiting_for_action != before_wait
        # The tutorial's own scene switches replace the embedded scene; a view
        # that changes under the same scene was changed by the input. That is
        # right only when the tutorial waited for it and moved on.
        view = self.embedded(t2)[1]
        if id(t2.embedded_scene) == before_id and view != before_view and (before_wait is None or not moved_on):
            self.finding("escape", t, f"{what} moved {self.where(t2)} on (from {before_view}) without the "
                         f"tutorial, which {'waited for nothing' if before_wait is None else 'still waits for ' + before_wait}"
                         f" and now waits for {t2.waiting_for_action or 'its next step'}", action=what, at=at)
        elif wrong and moved_on:
            self.finding("escape", t, f"{what}, off the highlight, moved the tutorial on to "
                         f"{self.step_label(t2)} as if {before_wait or 'its step'} had been done", action=what, at=at)
        elif refusal and not moved_on and view == before_view:
            new = self.env.sounds[sounds:]
            if "cancel" not in new and "menu" in new:
                self.finding("sound", t, f"{what} was refused but answered 'menu'", action=what, at=at)
        return True

    def away(self, t, rects):
        """Places a player might press instead: other controls, the screen centre."""
        from harness import managers
        e, skip = t.embedded_scene, t._skip_overlay._rect() if t._skip_overlay._is_touch() else None
        spots = []
        if type(e).__name__ == "TutorialMainGame":
            spots += [r.center for r in e.menu.icon_rects]
        for mgr in managers(e):
            spots += [c.rect.center for c in mgr.focusable_components if getattr(c, "visible", True)]
        spots.append((self.env.w // 2, self.env.h // 2))
        out = []
        for p in spots:
            if self.near(rects, p) or (skip and skip.collidepoint(p)) or p in out:
                continue
            if 0 <= p[0] < self.env.w and 0 <= p[1] < self.env.h:
                out.append(p)
        return out[:4]

    def fumble(self, t, rects):
        """The wrong inputs before the right one (fumble runs). False: the run is over."""
        if self.family == "keyboard":
            for key in ("B", "SELECT"):
                if not self.checked(t, ("key", key), refusal=True):
                    return False
                t = self.tutorial()
                if self.left_step(t):
                    return True
            # A with the cursor moved off the highlight (when it can be)
            for arrow in ARROWS:
                self.send(("key", arrow))
                self.frames(2)
                cur = self.cursor(t)
                if cur is not None and not self.near(rects, cur.center):
                    return self.checked(t, ("key", "A"), refusal=True, wrong=self.under(t, cur.center))
            return True
        for pos in self.away(t, rects):
            if self.family == "mouse":
                self.send(("move", pos))
                self.frames(2)
            if not self.checked(t, ("tap", pos), refusal=True, wrong=self.under(t, pos)):
                return False
            t = self.tutorial()
            if self.left_step(t):
                return True
        return True

    def left_step(self, t):
        return t is None or self.state_key(t) != self.fumbled_at

    # .............................................................. playing
    def play(self):
        """Play until the tutorial is left (or the stop is reached)."""
        try:
            self._play()
            self.check_logs(self.tutorial())
        except Stop:
            pass
        except Exception as exc:
            t = self.tutorial()
            self.finding("crash", t, f"{type(exc).__name__}: {exc}", trace=traceback.format_exc()[-2500:])
            self.ended = "crash"
        return self

    def _play(self):
        last, since, tries, acted_on, last_act = None, 0, 0, None, -10 ** 9
        self.moves, self.tried = 0, {}
        fumbled = set()                        # highlights already fumbled at (once each)
        seen = None
        while self.frame < MAX_FRAMES:
            t = self.tutorial()
            if t is None:
                # the last step completes the tutorial and routes on in one update
                done = seen is not None and seen.tutorial_complete
                self.ended = self.ended or ("complete" if done else "escape")
                if self.ended == "escape":
                    self.finding("escape", seen, f"the game left the tutorial for {type(self.game.scene).__name__}"
                                 + self.leftovers())
                return
            seen = t
            key = self.state_key(t)
            if key != last:
                last, since, tries = key, self.frame, 0
                self.moves, self.tried = 0, {}
                self.check_logs(t)
                self.check_screen(t)
                d = t.dialog if t.dialog.is_active() else t.dialog_top if t.dialog_top.is_active() else None
                if d is not None:
                    self.last_text = d.current_message
                if self.waiting_dialog(t) or t.waiting_for_action:
                    if not any(s[0] == key for s in self.stops):
                        self.stops.append((key, t.current_step_index, self.stop_label(t)))
                        if self.stop_at is not None and len(self.stops) > self.stop_at:
                            raise Stop()
            idle = self.frame - since
            dialog = self.waiting_dialog(t)
            if dialog is not None:
                if tries >= TRIES:
                    self.stuck(t, f"the dialog did not move on after {TRIES} presses")
                elif tries == 0 or idle >= 30 * tries:
                    if tries == 0 and self.run == "fumble" and self.family == "keyboard":
                        self.fumbled_at = key
                        if not self.checked(t, ("key", "LEFT"), refusal=False):
                            return
                        if self.left_step(self.tutorial()):
                            continue
                    self.read_on(t, dialog)
                    tries += 1
            elif t.waiting_for_action:
                rects = self.holes(t) or self.chooser(t)
                if rects:
                    shown = tuple(tuple(r) for r in rects)
                    if shown != acted_on or self.frame - last_act >= RETRY:
                        if tries >= TRIES:
                            self.stuck(t, f"{self.last_try} did nothing; under it: "
                                       f"{self.under(t, rects[0].center)}")
                            acted_on = None
                            continue
                        if self.run == "fumble" and (t.current_step_index, shown) not in fumbled:
                            fumbled.add((t.current_step_index, shown))
                            self.fumbled_at = key
                            if not self.fumble(t, rects):
                                return
                            if self.left_step(self.tutorial()):
                                continue
                        try:
                            done = self.act_on(t, rects)
                        except LookupError as exc:
                            self.stuck(t, str(exc))
                            continue
                        if done:
                            self.last_try, acted_on, last_act = done, shown, self.frame
                            tries += 1
                            if self.run == "fumble":
                                self.again(done)
                elif idle >= IDLE_STUCK:
                    self.stuck(t, "nothing shown to press, and " + ("pressing as the dialog asked did nothing"
                               if self.in_play(t) else "it does not move on by itself"))
                elif idle >= PATIENCE and idle % 3 == 0 and self.in_play(t):
                    sounds, at = len(self.env.sounds), (self.step_label(t), self.where(t), self.progress(t))
                    self.mash()
                    if "cancel" in self.env.sounds[sounds:]:
                        self.finding("sound", t, f"{describe(self.mash_input())} during {at[1]} (phases "
                                     f"{', '.join(p for p in at[2] if p != 'None')}) answers 'cancel'",
                                     at=at[:2], dedupe=("mash", at[1]))
            elif idle >= IDLE_STUCK:
                self.stuck(t, "the tutorial waits on nothing and does not move on")
            self.frames(1)
        self.finding("stuck", self.tutorial(), f"still in the tutorial after {MAX_FRAMES} frames")
        self.ended = "limit"

    def in_play(self, t):
        """A minigame or battle running in the embedded scene (it reads presses as play)."""
        check = getattr(t.embedded_scene, "plays_own_input_sounds", None)
        try:
            return bool(check()) if callable(check) else False
        except Exception:
            return False

    def again(self, done):
        """A second press right after the right one (fumble runs)."""
        t2 = self.tutorial()
        if t2 is None:
            return
        if done == "A":
            action = ("key", "A")
        else:
            m = re.search(r"\((\d+), (\d+)\)", done)
            if not m:
                return
            action = ("tap", (int(m.group(1)), int(m.group(2))))
        self.checked(t2, action, refusal=False)

    def stuck(self, t, detail):
        """Report the step, then help the run past it."""
        self.finding("stuck", t, detail)
        self.assisted.append(self.step_label(t))
        if self.waiting_dialog(t) or t.dialog.is_active() or t.dialog_top.is_active():
            for d in (t.dialog, t.dialog_top):
                d.skip()
                d.skip()
        elif t.waiting_for_action:
            t.notify_action(t.waiting_for_action)
        else:
            t._advance_step()

    def stop_label(self, t):
        d = self.waiting_dialog(t)
        if d is not None:
            return f"{self.step_label(t)}: “{d.current_message[:60]}”"
        return f"{self.step_label(t)} in {self.where(t)}"

    # .............................................................. skipping
    def skip(self):
        """Skip as the player can: START, or the SKIP pill by touch."""
        t = self.tutorial()
        if t is None:
            return False
        if self.family == "touch":
            self.send(("tap", t._skip_overlay._rect().center))
        else:
            self.send(("key", "START"))
        self.frames(3)
        if self.tutorial() is not None:
            self.finding("end", t, f"skipping ({'SKIP pill' if self.family == 'touch' else 'START'}) "
                         "did not leave the tutorial")
            return False
        self.ended = "skip"
        return True

    # .............................................................. checking
    def check_screen(self, t):
        """Once per screen: paint (UI-05); the SKIP pill over a dialog or the highlight."""
        label = self.where(t)
        if label not in self.screens_checked:
            self.screens_checked.add(label)
            left = self.env.unpainted()
            if left:
                self.finding("paint", t, f"{left} px never painted", dedupe=label)
        pill = t._skip_overlay._rect() if t._skip_overlay._is_touch() else None
        if pill is None:
            return
        for d in (t.dialog, t.dialog_top):
            if d.is_active() and pill.colliderect(d.rect):
                self.finding("overlap", t, f"the SKIP pill {tuple(pill)} covers the dialog {tuple(d.rect)}",
                             dedupe=("dialog", tuple(d.rect)))
        for r in self.holes(t):
            if pill.colliderect(r):
                self.finding("overlap", t, f"the SKIP pill {tuple(pill)} covers the highlight {tuple(r)}",
                             dedupe=("hole", tuple(r)))

    def check_logs(self, t):
        """Exceptions the game caught and logged since the last look."""
        for line in self.env.error_logs(self.log_mark):
            self.finding("logged", t, line[:300], dedupe=("log", line[:120]))
        self.log_mark = len(self.env.logs)

    def leftovers(self):
        """What a tutorial left mid-way leaves behind."""
        gg, rg = self.gg, self.rg
        out = []
        if any(k.lower() == "tutorial" for k in rg.game_modules):
            out.append("the Tutorial module still loaded")
        if [id(p) for p in gg.pet_list] != self.before_party:
            out.append(f"the party is {[p.name for p in gg.pet_list]}")
        return f" ({'; '.join(out)})" if out else ""

    def check_end(self):
        """The game the tutorial hands back (after its end or a skip)."""
        gg, rg = self.gg, self.rg
        if self.ended not in ("complete", "skip"):
            return
        how = "skipping" if self.ended == "skip" else "finishing"
        if self.assisted:
            how += f" (after the crawler helped past {len(self.assisted)} stuck step(s))"
        party = [id(p) for p in gg.pet_list]
        if party != self.before_party:
            self.finding("end", None, f"{how} left the party {[p.name for p in gg.pet_list]}, "
                         f"not {self.before_names}")
        loaded = [k for k in rg.game_modules if k.lower() == "tutorial"]
        if loaded:
            self.finding("end", None, f"{how} left the Tutorial module loaded")
        if self.fixture.startswith("shop") and self.ended == "complete" \
                and not any(k.lower() != "tutorial" for k in rg.game_modules):
            self.finding("end", None, f"{how} left no module installed")
        import battle.battle_encounter as be
        from utils import scene_utils
        if be.change_scene is not scene_utils.change_scene:
            self.finding("end", None, f"{how} left battle_encounter.change_scene patched: the next "
                         "battle's return to the game is swallowed")
        self.frames(3)
        scene = type(self.game.scene).__name__
        want = NEXT_SCENE[self.fixture]
        if not any(k.lower() != "tutorial" for k in rg.game_modules):
            want = "SceneConnect"
        if scene != want:
            self.finding("end", None, f"{how} went to {scene}, not {want}")
        if gg.show_tutorial:
            self.finding("end", None, f"show_tutorial still on after {how}")
        after = save_summary(gg)
        if after is None:
            self.finding("end", None, f"nothing saved after {how}")
            return
        if after.get("show_tutorial") is not False:
            self.finding("end", None, f"the save still has show_tutorial on after {how}")
        allowed = MAY_CHANGE | (SHOP_CHANGES if self.fixture.startswith("shop") else set())
        for k in sorted(set(after) | set(self.before_save or {})):
            if k in allowed:
                continue
            old, new = (self.before_save or {}).get(k), after.get(k)
            if old != new:
                self.finding("save", None, f"{how} changed the save's {k}: {difference(old, new)}",
                             dedupe=f"the save's {k}")
        files = folder_snapshot(self.env.save_root)
        mine = os.path.relpath(gg.get_save_dir(), self.env.save_root).replace(os.sep, "/") + "/"
        for path in sorted(set(files) | set(self.before_files)):
            old, new = self.before_files.get(path), files.get(path)
            if old != new:
                change = "added" if old is None else "removed" if new is None else "changed"
                shown = "<player save>/" + path[len(mine):] if path.startswith(mine) else path
                self.finding("save", None, f"{how} {change} {shown} in the save folder: "
                             f"{difference(old and old[1], new and new[1])}", dedupe=f"{shown} in the save folder")

    def finding(self, kind, t, detail, action=None, trace=None, dedupe=None, at=None):
        """*at*: (step, scene) as they were before the input that found it."""
        step, scene = at or ((self.step_label(t), self.where(t)) if t is not None else
                             ("(after the tutorial)", type(self.game.scene).__name__))
        key = (kind, dedupe if dedupe is not None else (step, detail[:120]))
        if key in self._seen:
            return
        self._seen.add(key)
        self.findings.append({"kind": kind, "run": self.run, "family": self.family, "res": f"{self.env.w}x{self.env.h}",
                              "fixture": self.fixture, "step": step, "scene": scene,
                              "said": self.last_text, "action": action, "detail": detail, "trace": trace,
                              "topic": dedupe if dedupe is None or isinstance(dedupe, str) else str(dedupe)})

    def result(self, started):
        return {"run": self.run, "family": self.family, "res": f"{self.env.w}x{self.env.h}", "fixture": self.fixture,
                "ended": self.ended, "assisted": self.assisted, "frames": self.frame,
                "seconds": round(time.time() - started, 1), "stops": len(self.stops),
                "findings": self.findings}


# ---------------------------------------------------------------- save
def save_summary(gg):
    """The newest save file, each key summarised so two saves compare."""
    files = glob.glob(os.path.join(gg.get_save_dir(), "save_data_*.dat"))
    if not files:
        return None
    newest = max(files, key=lambda p: int(re.search(r"(\d+)\.dat$", p).group(1)))
    with open(newest, "rb") as fh:
        data = pickle.load(fh)
    return {k: summarize(v) for k, v in data.items()}


def summarize(v, depth=0):
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if type(v).__name__ == "GamePet":
        return f"{v.name} ({v.module} v{v.version}, stage {v.stage})"
    if isinstance(v, (list, tuple)):
        return [summarize(x, depth + 1) for x in v]
    if isinstance(v, set):
        return sorted(str(x) for x in v)
    if isinstance(v, dict):
        return {str(k): summarize(x, depth + 1) for k, x in v.items()}
    if hasattr(v, "to_dict"):
        return summarize(v.to_dict(), depth + 1)
    if hasattr(v, "__dict__") and depth < 3:
        return {k: summarize(x, depth + 1) for k, x in vars(v).items() if not k.startswith("_")}
    return type(v).__name__


def folder_snapshot(root):
    """Every file of the save folder but the numbered saves and the device key:
    path -> (digest, its JSON when it is a JSON file)."""
    out = {}
    for folder, _, names in os.walk(root):
        for name in names:
            if re.match(r"save_data_\d+\.dat$", name) or name == "omninet_device.json":
                continue
            path = os.path.join(folder, name)
            with open(path, "rb") as fh:
                raw = fh.read()
            try:
                content = json.loads(raw.decode("utf-8-sig")) if name.endswith(".json") else None
            except ValueError:
                content = None
            out[os.path.relpath(path, root).replace(os.sep, "/")] = (hashlib.sha1(raw).hexdigest(), content)
    return out


def difference(old, new):
    """What changed, briefly: the keys or entries added, removed and changed."""
    if isinstance(old, dict) and isinstance(new, dict):
        parts = [f"+{k}={short(new[k])}" for k in new if k not in old]
        parts += [f"-{k}" for k in old if k not in new]
        parts += [f"{k}: {difference(old[k], new[k])}" for k in old if k in new and old[k] != new[k]]
        return short_text("; ".join(parts))
    if isinstance(old, list) and isinstance(new, list):
        ident = next((k for k in ("id", "name") if all(isinstance(x, dict) and k in x for x in old + new)), None)
        if ident:                              # records (quests): matched by id, each one's change
            before, after = {x[ident]: x for x in old}, {x[ident]: x for x in new}
            parts = [f"+{short(after[k])}" for k in after if k not in before]
            parts += [f"-{k}" for k in before if k not in after]
            parts += [f"{after[k].get('name', k)}: {difference(before[k], after[k])}"
                      for k in after if k in before and before[k] != after[k]]
            return short_text("; ".join(parts))
        added = [x for x in new if x not in old]
        removed = [x for x in old if x not in new]
        if (added or removed) and len(added) + len(removed) <= len(new) + len(old):
            return short_text(", ".join([f"+{short(x)}" for x in added] + [f"-{short(x)}" for x in removed]))
    return f"{short(old)} -> {short(new)}"


def short(v):
    return short_text(json.dumps(v, ensure_ascii=False, default=str))


def short_text(text, limit=300):
    return text if len(text) <= limit else text[:limit - 3] + "..."


def describe(action):
    if action[0] == "key":
        return action[1]
    return f"{action[0]} {tuple(action[1])}"


# ---------------------------------------------------------------- jobs
#: Processes a skip run is split into (each replays every PARTS-th skip point).
PARTS = 4


def default_jobs():
    """(run, family, res, fixture, part) of a full crawl; part is "k/n" for skip runs."""
    jobs = [("play", f, r, "replay") for r in RESOLUTIONS for f in FAMILIES]
    jobs += [("play", f, "240x240", "first") for f in ("keyboard", "touch")]
    jobs += [("play", f, "240x240", "shop") for f in FAMILIES]
    jobs += [("play", f, "240x240", "shop-free") for f in ("keyboard", "touch")]
    jobs += [("fumble", f, "240x240", "replay") for f in FAMILIES]
    jobs += [("fumble", f, "240x240", "shop") for f in ("keyboard", "touch")]
    jobs += [("skip", "keyboard", "240x240", "replay"), ("skip", "touch", "240x240", "shop")]
    return [j + ((f"{k}/{PARTS}",) if j[0] == "skip" else ("-",))
            for j in jobs for k in (range(1, PARTS + 1) if j[0] == "skip" else (1,))]


def child(run, family, res, fixture, part, out):
    """One job in this process."""
    from harness import Env
    started = time.time()
    fake = None
    if fixture.startswith("shop"):
        from fake_omninet import FakeOmninet, isolate_client, module_zip
        env = Env(res, network="local", fixture="empty")
        fake = FakeOmninet().start()
        isolation = isolate_client(env, fake, timeout=2.0)
        fake.svc = isolation.__enter__()
        fake.isolation = isolation            # kept alive: its exit puts the real URLs back
        with open(os.path.join(MODULES, "DMOG", "module.json"), encoding="utf-8-sig") as fh:
            version = json.load(fh)["version"]
        fake.add_module("DMOG", module_zip(os.path.join(MODULES, "DMOG")), version=version,
                        description="The original Digital Monster.")
    else:
        env = Env(res, fixture="empty" if fixture == "first" else "default")
    player = Player(env, family, fixture, run, fake)
    player.start()
    player.play()
    if run != "skip":
        player.check_end()
        result = player.result(started)
    else:
        # The playthrough found the stops (its own findings are the play
        # run's); this part replays to the first stop of every PARTS-th step
        # and skips there.
        k, n = (int(x) for x in part.split("/"))
        firsts, steps = [], set()
        for i, (_, step, label) in enumerate(player.stops):
            if step not in steps:
                steps.add(step)
                firsts.append((i, label))
        findings, skips = [], []
        for i, label in firsts[k - 1::n]:
            p = Player(env, family, fixture, run, fake)
            p.start(stop_at=i)
            p.play()
            if p.tutorial() is None:
                skips.append({"stop": i, "label": label, "ok": False, "detail": "the tutorial ended before"})
                continue
            already = len(p.findings)
            p.skip()
            p.check_end()
            mine = p.findings[already:]
            for f in mine:
                f["points"] = [label]
            skips.append({"stop": i, "label": label, "ok": not any(f["kind"] in FAIL_KINDS for f in mine)})
            findings += mine
        result = player.result(started)
        result["findings"] = merge_points(findings)
        result["skips"] = skips
    result["part"] = part
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1, ensure_ascii=False, default=str)
    if fake is not None:
        fake.isolation.__exit__(None, None, None)
        fake.stop()


HELPED = re.compile(r" [(]after the crawler helped past [0-9]+ stuck step[(]s[)][)]")


def merge_points(findings):
    """One finding per kind and topic (the save key or file it changed) or
    detail, with every skip point it happened at; the first one's detail
    stands for the rest."""
    out = collections.OrderedDict()
    for f in findings:
        key = (f["kind"], f.get("topic") or HELPED.sub("", f["detail"]))
        if key in out:
            out[key]["points"] += [p for p in f["points"] if p not in out[key]["points"]]
        else:
            out[key] = dict(f, detail=HELPED.sub("", f["detail"]), points=list(f["points"]))
    for f in out.values():
        f["step"] = f"skipped at {f['points'][0]}" + (f" and {len(f['points']) - 1} more step(s)"
                                                      if len(f["points"]) > 1 else "")
    return list(out.values())


def merge_parts(results):
    """The parts of each skip run as one result."""
    out, skips = [], collections.OrderedDict()
    for r in results:
        if r["run"] != "skip":
            out.append(r)
            continue
        key = (r["run"], r["family"], r["res"], r["fixture"])
        if key not in skips:
            skips[key] = dict(r, part="-", skips=[], findings=[], seconds=0)
            out.append(skips[key])
        whole = skips[key]
        whole["skips"] += r.get("skips", [])
        whole["findings"] += r["findings"]
        whole["seconds"] = round(whole["seconds"] + r["seconds"], 1)
        if r["ended"] == "crash":
            whole["ended"] = "crash"
    for whole in skips.values():
        whole["skips"].sort(key=lambda s: s["stop"])
        crashes = [f for f in whole["findings"] if "points" not in f]
        whole["findings"] = crashes + merge_points([f for f in whole["findings"] if "points" in f])
    return out


# ---------------------------------------------------------------- report
KIND_TITLES = [("crash", "Crashes"), ("stuck", "Stuck: the shown input does not move the tutorial on"),
               ("escape", "Escapes: an input leaves the tutorial or moves its scene on without it"),
               ("end", "End state after finishing or skipping"),
               ("save", "Save changed by the tutorial"), ("logged", "Exceptions caught and logged"),
               ("sound", "Input sounds (UI-06): a refused input answered 'menu', a press in play answered 'cancel'"),
               ("overlap", "The touch SKIP pill over a dialog or the highlight"),
               ("paint", "Unpainted canvas (UI-05)")]


COORDS = re.compile(r"[(][0-9]+, [0-9]+(, [0-9]+, [0-9]+)?[)]")


def about(f):
    """What a finding is about, alike across runs and resolutions: the save
    key or file it changed, or its step and detail, coordinates left out."""
    if f["kind"] == "save":
        return ("", f.get("topic") or f["detail"])
    return (f["step"], COORDS.sub("(...)", HELPED.sub("", f["detail"])))


def step_order(key):
    m = re.search(r"step ([0-9]+)", key[0])
    return (int(m.group(1)) if m else 10 ** 6, key[1])


def markdown(results):
    lines = ["# Tutorial crawl", "", "| Run | Input | Resolution | Start | Ended | Helped past | Stops | FAIL | Review |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        kinds = collections.Counter(f["kind"] for f in r["findings"])
        fail = sum(v for k, v in kinds.items() if k in FAIL_KINDS)
        review = ", ".join(f"{k} {v}" for k, v in sorted(kinds.items()) if k not in FAIL_KINDS)
        helped = len(r.get("assisted", []))
        ended = r["ended"] + (f", {sum(s['ok'] for s in r['skips'])}/{len(r['skips'])} skips clean"
                              if "skips" in r else "")
        lines.append(f"| {r['run']} | {r['family']} | {r['res']} | {r['fixture']} | {ended} | {helped or ''} | "
                     f"{r['stops']} | {fail or ''} | {review} |")
    for kind, title in KIND_TITLES:
        groups = {}
        for r in results:
            for f in r["findings"]:
                if f["kind"] != kind:
                    continue
                g = groups.setdefault(about(f), {"f": f, "runs": [], "points": []})
                g["runs"].append(f"{f['run']} {f['family']} {f['res']} {f['fixture']}")
                g["points"] += [p for p in f.get("points", []) if p not in g["points"]]
        if not groups:
            continue
        lines += ["", f"## {title} ({len(groups)})", ""]
        for key in sorted(groups, key=step_order):
            g = groups[key]
            f = g["f"]
            said = f" (the tutorial said “{f['said'][:80]}”)" if f.get("said") and kind in ("stuck", "escape") else ""
            head = f"**{key[1]}**: e.g. {HELPED.sub('', f['detail'])}" if kind == "save" else \
                f"**{f['step'] if not g['points'] else 'skipped'}** in {f['scene']}{said}: {HELPED.sub('', f['detail'])}"
            lines.append(f"- {head}  \n  runs: {'; '.join(sorted(set(g['runs'])))}")
            if g["points"]:
                points = sorted(g["points"], key=lambda p: step_order((p, ""))[0])
                lines.append(f"  skip points ({len(points)}): " + "; ".join(points))
            if f.get("trace"):
                tail = [ln for ln in f["trace"].strip().splitlines() if ln.strip()][-4:]
                lines.append("  ```\n  " + "\n  ".join(tail) + "\n  ```")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", nargs="*", choices=RUNS)
    ap.add_argument("--family", nargs="*", choices=FAMILIES)
    ap.add_argument("--fixture", nargs="*", choices=FIXTURES)
    ap.add_argument("--res", nargs="*")
    ap.add_argument("-j", type=int, default=max(1, min(4, (os.cpu_count() or 2) - 2)),
                    help="runs at once (default: up to 4; each loads every module)")
    ap.add_argument("--out", default=os.path.join(REPORTS, "tutorial"))
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--child", nargs=6, metavar=("RUN", "FAMILY", "RES", "FIXTURE", "PART", "OUT"))
    args = ap.parse_args()
    if args.child:
        child(*args.child)
        return 0
    jobs = [j for j in default_jobs()
            if (not args.runs or j[0] in args.runs) and (not args.family or j[1] in args.family)
            and (not args.res or j[2] in args.res) and (not args.fixture or j[3] in args.fixture)]
    if args.res:                               # a resolution asked for is played as replay is
        extra = [("play", f, r, "replay", "-") for r in args.res if r not in RESOLUTIONS
                 for f in (args.family or FAMILIES) if not args.runs or "play" in args.runs]
        jobs += [j for j in extra if not args.fixture or "replay" in args.fixture]
    if not os.path.isdir(os.path.join(MODULES, "DMOG")):
        jobs = [j for j in jobs if not j[3].startswith("shop")]
        print("modules/DMOG not present: the shop fixtures are left out")
    tmp = temp_dir("tutorial_")
    running, results = [], []

    def launch(job):
        out = os.path.join(tmp, "_".join(job).replace("/", "of") + ".json")
        cmd = [sys.executable, "-B", os.path.abspath(__file__), "--child", *job, out]
        return job, out, subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                          text=True, encoding="utf-8", errors="replace")

    pending = list(jobs)
    while pending or running:
        while pending and len(running) < args.j:
            running.append(launch(pending.pop(0)))
        job, out, proc = running.pop(0)
        log = proc.communicate()[0]
        if os.path.isfile(out):
            results.append(json.load(open(out, encoding="utf-8")))
        else:
            run, family, res, fixture, part = job
            results.append({"run": run, "family": family, "res": res, "fixture": fixture, "part": part,
                            "ended": "crash",
                            "assisted": [], "frames": 0, "seconds": 0, "stops": 0,
                            "findings": [{"kind": "crash", "run": run, "family": family, "res": res,
                                          "fixture": fixture, "step": "(crawler)", "scene": "", "said": "",
                                          "action": None, "detail": f"crawler process died: exit {proc.returncode}",
                                          "trace": log[-3000:]}]})
        if not args.quiet:
            r = results[-1]
            kinds = collections.Counter(f["kind"] for f in r["findings"])
            print(f"{r['run']:6} {r['family']:8} {r['res']:8} {r['fixture']:9} {r.get('part', '-'):4} {r['ended']:8} "
                  f"{r['seconds']:6}s  " + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())))
    order = {j[:4]: i for i, j in reversed(list(enumerate(jobs)))}
    results = merge_parts(results)
    results.sort(key=lambda r: order.get((r["run"], r["family"], r["res"], r["fixture"]), 0))
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "tutorial_crawl.json"), "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=1, ensure_ascii=False, default=str)
    with open(os.path.join(args.out, "tutorial_crawl.md"), "w", encoding="utf-8") as fh:
        fh.write(markdown(results))
    tally = collections.Counter(f["kind"] for r in results for f in r["findings"])
    print(f"{len(results)} runs: " + (", ".join(f"{k} {v}" for k, v in sorted(tally.items())) or "no findings"))
    return 1 if any(tally[k] for k in FAIL_KINDS) else 0


if __name__ == "__main__":
    sys.exit(main())
