"""Poop Dodge, the iC 10X's dodging minigame (owner, 2026-10-06).

Sukamon's opening stands in for READY; the charge is the course, three
stages of the playbook's (p. 54); a hit ends it. A hit in stage 1 BAD, 2
GOOD, 3 GREAT, none EXCELLENT.
"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SRC = os.path.join(REPO_ROOT, "src")
for path in (SRC, REPO_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

import pygame  # noqa: E402

from core import game_globals, runtime_globals  # noqa: E402
from training import ic_minigame, poop_dodge, training  # noqa: E402
from training.poop_dodge import (  # noqa: E402
    COURSES, LANES, PLAYER_COL, PoopDodge, READY_TOTAL_MS, STEP_MS, course_lanes)

FIGHT_MONEY = {"name": "Fight Money", "unit": "P", "cap": 9999}


class FakePet:
    def __init__(self, **fields):
        self.__dict__.update(fields)


class PoopDodgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.chdir(REPO_ROOT)
        pygame.init()
        pygame.display.set_mode((240, 240))

    def setUp(self):
        self.now = 0
        self.pet = FakePet(module="IC", hunger=3, stage=3, atk_main=1,
                           _apply_reliability_event=mock.Mock())
        self.sound = SimpleNamespace(play=mock.Mock(return_value=None), get_duration=lambda n: 0,
                                     stop=lambda n: None, is_playing=lambda n: False)
        patches = [
            mock.patch.object(pygame.time, "get_ticks", side_effect=lambda: self.now),
            mock.patch.object(training, "get_training_targets", return_value=[self.pet]),
            mock.patch.object(ic_minigame, "get_training_targets", return_value=[self.pet]),
            mock.patch.object(training, "distribute_pets_evenly", mock.Mock()),
            mock.patch.object(poop_dodge.random, "choice", side_effect=lambda s: "D"),
            mock.patch.object(runtime_globals, "game_sound", self.sound),
            mock.patch.object(runtime_globals, "game_state", "training"),
            mock.patch.object(runtime_globals, "INPUT_MODE", runtime_globals.KEYBOARD_MODE),
            mock.patch.object(runtime_globals, "game_modules", {
                "IC": SimpleNamespace(currencies=[FIGHT_MONEY],
                                      folder_path=os.path.join(REPO_ROOT, "modules", "IC"))}),
            mock.patch.object(game_globals, "currency", {}),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        from ui.ui_manager import UIManager
        self.game = PoopDodge(UIManager("GREEN"))

    def tick(self, ms=10):
        self.now += ms
        self.game.update()

    def start(self):
        while self.game.phase == "alert":
            self.tick()

    @staticmethod
    def plan(game):
        """The lane to be in at each view, dodging everything, or None.

        A breadth-first search over (view, lane): before the course moves
        from view v to v - 1, the Digimon may step to any lane it reaches
        through lanes free at v, and must be free there at v - 1."""
        end = game.goal_edges[3] - poop_dodge.CLEAR_PAST
        parent = {game.start_view: {poop_dodge.START_LANE: None}}
        for view in range(game.start_view, end, -1):
            nxt = {}
            for lane in parent[view]:
                for step in (-1, 1):
                    target = lane
                    while 0 <= target < LANES and not game.hits(view, target):
                        if not game.hits(view - 1, target):
                            nxt.setdefault(target, lane)
                        target += step
            if not nxt:
                return None
            parent[view - 1] = nxt
        lane = next(iter(parent[end]))
        path = {end: lane}
        for view in range(end, game.start_view):
            lane = parent[view][lane]
            path[view + 1] = lane
        return path

    def test_all_64_combinations_of_courses_can_be_cleared(self):
        from ui.ui_manager import UIManager
        for one in "ABCD":
            for two in "ABCD":
                for three in "ABCD":
                    picks = iter([one, two, three])
                    with mock.patch.object(poop_dodge.random, "choice", side_effect=lambda s: next(picks)):
                        game = PoopDodge(UIManager("GREEN"))
                    self.assertIsNotNone(self.plan(game), (one, two, three))

    def play_safely(self, limit=400000):
        """Dodge everything, following plan()."""
        path = self.plan(self.game)
        self.assertIsNotNone(path, "this course cannot be cleared")
        end = self.now + limit
        while self.game.phase == "charge":
            self.assertLess(self.now, end)
            view = self.game.view_left()
            target = path.get(view - 1, self.game.lane)
            while self.game.step == "run" and self.game.lane != target:
                self.game.handle_event(("UP" if target < self.game.lane else "DOWN", None))
            self.tick(STEP_MS // 3)

    # -- the courses ---------------------------------------------------

    def test_every_course_is_four_lanes_of_whole_screens(self):
        for stage, courses in COURSES.items():
            self.assertEqual(sorted(courses), ["A", "B", "C", "D"])
            for name in courses:
                lanes = course_lanes(stage, name)
                self.assertEqual(len(lanes), LANES)
                self.assertEqual({len(lane) for lane in lanes}, {(6 if stage == 1 else 5) * 4})

    def test_every_course_can_be_dodged(self):
        """Somewhere free in every column, and a way between neighbours."""
        for stage, courses in COURSES.items():
            for name in courses:
                lanes = course_lanes(stage, name)
                for col in range(len(lanes[0])):
                    free = [lane for lane in range(LANES) if lanes[lane][col] == "."]
                    self.assertTrue(free, (stage, name, col))

    # -- the phases ----------------------------------------------------

    def test_sukamons_opening_stands_in_for_ready(self):
        self.assertEqual(self.game.phase, "alert")
        self.start()
        self.assertGreaterEqual(self.now, READY_TOTAL_MS)
        self.assertEqual((self.game.phase, self.game.step), ("charge", "run"))
        self.assertEqual([c.args[0] for c in self.sound.play.call_args_list], ["ic_poop_start"],
                         "a silent opening, then the iC's tune")

    def test_the_course_scrolls_a_dot_every_step(self):
        self.start()
        first = self.game.view_left()
        self.now += STEP_MS * 10
        self.assertEqual(self.game.view_left(), first - 10)

    def test_up_and_down_move_a_lane_within_the_lcd(self):
        self.start()
        self.assertEqual(self.game.lane, 1)
        for _ in range(5):
            self.game.handle_event(("UP", None))
        self.assertEqual(self.game.lane, 0)
        for _ in range(5):
            self.game.handle_event(("DOWN", None))
        self.assertEqual(self.game.lane, 3)

    def test_a_hit_in_stage_1_is_bad(self):
        self.start()
        while self.game.phase == "charge":
            self.tick(STEP_MS)          # never moves: course D walls lane 1? no -- runs into poop
        self.assertEqual(self.game.get_attack_count(), 0)
        self.assertEqual(self.game.prize, 0)
        self.assertIn("ic_fail", [c.args[0] for c in self.sound.play.call_args_list])

    def test_dodging_everything_is_excellent_and_pays_50(self):
        self.start()
        self.play_safely()
        self.assertEqual(self.game.phase, "result")
        self.assertEqual(self.game.cleared, 3)
        self.assertEqual(self.game.get_attack_count(), 3, "EXCELLENT")
        played = [c.args[0] for c in self.sound.play.call_args_list]
        self.assertEqual(played.count("ic_poop_stage"), 2, "a sound at each boundary")
        self.assertEqual(played[-1], "ic_success")
        while self.game.phase != "currency":
            self.tick()
        self.assertEqual(game_globals.currency, {"IC": {"Fight Money": 50}})
        self.pet._apply_reliability_event.assert_called_once_with("reliability_minigame_success")

    def test_a_hit_after_a_stage_grades_by_the_stages_cleared(self):
        self.start()
        # Dodge until the first stage sound, then stand still.
        path = self.plan(self.game)
        while self.game.cleared < 1:
            target = path.get(self.game.view_left() - 1, self.game.lane)
            while self.game.step == "run" and self.game.lane != target:
                self.game.handle_event(("UP" if target < self.game.lane else "DOWN", None))
            self.tick(STEP_MS // 3)
        while self.game.phase == "charge":
            self.tick(STEP_MS)
        self.assertIn(self.game.get_attack_count(), (1, 2))
        self.assertEqual(self.game.prize, (0, 10, 20, 50)[self.game.get_attack_count()])

    def test_moving_into_a_poop_is_a_hit(self):
        self.start()
        view = self.game.view_left()
        while not any(self.game.hits(view, lane) for lane in range(LANES)) or self.game.hits(view):
            self.tick(STEP_MS)
            if self.game.phase != "charge" or self.game.step != "run":
                self.skipTest("the course hit first")
            view = self.game.view_left()
        lane = next(l for l in range(LANES) if self.game.hits(view, l))
        while self.game.lane != lane and self.game.step == "run":
            self.game.handle_event(("UP" if lane < self.game.lane else "DOWN", None))
        self.assertEqual(self.game.step, "hit")

    # -- input and drawing ---------------------------------------------

    def test_the_arrow_buttons_move_the_digimon(self):
        self.start()
        with mock.patch.object(runtime_globals, "INPUT_MODE", runtime_globals.TOUCH_MODE):
            self.game.handle_event(("LCLICK", {"pos": self.game.up_button.rect.center}))
            self.assertEqual(self.game.lane, 0)
            self.game.handle_event(("DRAG_END", {"pos": self.game.down_button.rect.center,
                                                 "start_pos": self.game.down_button.rect.center}))
            self.assertEqual(self.game.lane, 1)

    def test_the_course_is_drawn_once_per_poop_frame(self):
        self.start()
        frames = self.game.poop_frames()
        self.assertEqual(len(frames), 2)
        self.assertIs(self.game.poop_frames(), frames, "drawn once")
        surface = pygame.Surface((240, 240))
        self.game.draw(surface)
        view = self.game._view
        self.game.draw(surface)
        self.assertIs(self.game._view, view, "the scaled window is reused until the course moves")
        self.now += STEP_MS
        self.game.draw(surface)
        self.assertIsNot(self.game._view, view)

    def test_every_phase_draws(self):
        surface = pygame.Surface((240, 240))
        with mock.patch.object(runtime_globals, "INPUT_MODE", runtime_globals.MOUSE_MODE):
            while self.game.phase == "alert":
                self.game.draw(surface)
                self.tick(50)
            for _ in range(200):
                self.game.draw(surface)
                self.tick(50)


if __name__ == "__main__":
    unittest.main()
