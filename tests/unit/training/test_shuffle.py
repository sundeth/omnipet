"""Shuffle, the iC 10X's guessing minigame (owner, 2026-10-06).

Its opening scene -- Chuumon climbing into the left bucket -- stands in for
READY; the charge is the rest of a round (SHUFFLE, the bucket's hop,
SELECT!, the pick, the reveal), and a find starts the next round from
Chuumon climbing in. No finds BAD, one GOOD, two GREAT, three or more
EXCELLENT.
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
from training import ic_minigame, shuffle, training  # noqa: E402
from training.shuffle import (  # noqa: E402
    HOP_MS, INTRO_MS, SELECT_MS, Shuffle, TITLE_MS, prize_for)

FIGHT_MONEY = {"name": "Fight Money", "unit": "P", "cap": 9999}


class FakePet:
    def __init__(self, **fields):
        self.__dict__.update(fields)


class ShuffleTests(unittest.TestCase):
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
        self.places = []        # where Chuumon goes, round by round
        patches = [
            mock.patch.object(pygame.time, "get_ticks", side_effect=lambda: self.now),
            mock.patch.object(training, "get_training_targets", return_value=[self.pet]),
            mock.patch.object(ic_minigame, "get_training_targets", return_value=[self.pet]),
            mock.patch.object(training, "distribute_pets_evenly", mock.Mock()),
            mock.patch.object(shuffle.random, "randrange", side_effect=lambda n: self.places.pop(0)),
            mock.patch.object(runtime_globals, "game_sound", self.sound),
            mock.patch.object(runtime_globals, "game_state", "training"),
            mock.patch.object(runtime_globals, "game_modules", {
                "IC": SimpleNamespace(currencies=[FIGHT_MONEY],
                                      folder_path=os.path.join(REPO_ROOT, "modules", "IC"))}),
            mock.patch.object(game_globals, "currency", {}),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        from ui.ui_manager import UIManager
        self.game = Shuffle(UIManager("GREEN"))

    def tick(self, ms=10):
        self.now += ms
        self.game.update()

    def until(self, phase=None, step=None, limit=60000):
        end = self.now + limit
        while not ((phase and self.game.phase == phase)
                   or (step and self.game.phase == "charge" and self.game.step == step)):
            self.assertLess(self.now, end, f"stuck at {self.game.phase}/{self.game.step}")
            self.tick()

    def play_round(self, where, pick):
        """Chuumon goes into bucket *where*; pick bucket *pick*."""
        self.places.append(where)
        self.until(step="choose")
        self.game.handle_event(("RIGHT" if pick else "LEFT", None))
        self.game.handle_event(("A", None))

    # -- the opening ---------------------------------------------------

    def test_the_opening_scene_stands_in_for_ready(self):
        self.assertEqual(self.game.phase, "alert")
        start = self.now
        self.game.update()
        self.places.append(0)
        self.until(phase="charge")
        self.assertGreaterEqual(self.now - start, INTRO_MS, "the scene runs its whole length")
        self.assertEqual(self.game.step, "title", "the first round's opening was READY")
        played = [c.args[0] for c in self.sound.play.call_args_list]
        self.assertEqual(played, ["ic_shuffle"], "the device opens silently, then its tune")

    def test_the_screens_fill_the_screen_with_their_sounds(self):
        """SHUFFLE to the iC's tune and SELECT! to the READY sound, each its
        two frames taking turns full screen, as the game's other two-frame
        animations are shown."""
        surface = pygame.Surface((240, 240))
        surface.fill((1, 2, 3))
        self.places.append(0)
        self.until(step="title")
        self.assertTrue(self.game.animated_sprite.is_animation_playing())
        self.assertEqual(len(self.game.animated_sprite.sprites), 2)
        self.game.draw(surface)
        corner = tuple(surface.get_at((1, 1)))[:3]
        self.assertEqual(corner, (0xe7, 0xec, 0xff), "the paper fills the screen")
        self.until(step="hop")
        self.assertFalse(self.game.animated_sprite.is_animation_playing())
        self.until(step="select")
        self.sound.play.assert_called_with("training_ready")
        self.assertTrue(self.game.animated_sprite.is_animation_playing())
        self.until(step="choose")
        self.assertFalse(self.game.animated_sprite.is_animation_playing())

    def test_the_screens_are_opaque(self):
        from PIL import Image
        for name in ("ShuffleTitle1", "ShuffleTitle2", "ShuffleSelect1", "ShuffleSelect2"):
            image = Image.open(os.path.join(REPO_ROOT, "assets", "ui", f"Combat_{name}_1.png")).convert("RGBA")
            self.assertEqual(image.size, (240, 240), name)
            self.assertEqual(image.getextrema()[3], (255, 255), name)

    def test_a_round_runs_shuffle_hop_select_then_the_pick(self):
        self.places.append(1)
        self.until(phase="charge")
        for step, ms in (("title", TITLE_MS), ("hop", HOP_MS), ("select", SELECT_MS)):
            self.assertEqual(self.game.step, step)
            self.now += ms - 10
            self.game.update()
            self.assertEqual(self.game.step, step, "not before its time")
            self.tick(10)
        self.assertEqual(self.game.step, "choose")
        self.game.handle_event(("A", None))         # the pointer starts on the left
        self.assertEqual((self.game.step, self.game.hit), ("reveal", False))

    # -- the outcome ---------------------------------------------------

    def test_a_find_starts_over_from_chuumon_climbing_in(self):
        self.play_round(where=0, pick=0)
        self.assertTrue(self.game.hit)
        self.places.append(1)
        self.until(step="intro")
        self.assertEqual(self.game.finds, 1)
        self.game.handle_event(("A", None))
        self.assertEqual(self.game.step, "intro", "no picking until the buckets are shuffled")

    def test_no_finds_is_bad_and_pays_nothing(self):
        self.play_round(where=0, pick=1)
        self.until(phase="result")
        self.assertEqual(self.game.get_attack_count(), 0)
        self.assertEqual(self.game.prize, 0)
        while runtime_globals.game_state != "game":
            self.tick()
        self.assertEqual(game_globals.currency, {})
        self.pet._apply_reliability_event.assert_not_called()
        self.assertIn("ic_fail", [c.args[0] for c in self.sound.play.call_args_list])

    def test_finds_grade_and_pay_the_ladder(self):
        for _ in range(2):
            self.play_round(where=1, pick=1)
        self.play_round(where=1, pick=0)
        self.until(phase="result")
        self.assertEqual(self.game.get_attack_count(), 2, "two finds: GREAT")
        self.assertEqual(self.game.prize, 10)
        self.sound.play.assert_called_with("ic_fail")     # it ended on a miss
        self.until(phase="currency")
        self.assertEqual(game_globals.currency, {"IC": {"Fight Money": 10}})
        self.pet._apply_reliability_event.assert_called_once_with("reliability_minigame_success")

    def test_three_finds_and_more_are_excellent(self):
        for _ in range(4):
            self.play_round(where=0, pick=0)
        self.play_round(where=0, pick=1)
        self.until(phase="result")
        self.assertEqual(self.game.get_attack_count(), 3)
        self.assertEqual(self.game.prize, 40)

    def test_the_ladder(self):
        self.assertEqual([prize_for(n) for n in range(11)],
                         [0, 5, 10, 20, 40, 80, 160, 320, 640, 1280, 2560])

    def test_the_tenth_find_ends_the_game(self):
        for _ in range(10):
            self.play_round(where=1, pick=1)
        self.until(phase="result")
        self.assertEqual((self.game.finds, self.game.prize), (10, 2560))
        self.sound.play.assert_called_with("ic_success")

    # -- input ---------------------------------------------------------

    def test_the_pointer_moves_and_a_tap_picks_a_bucket(self):
        self.places.append(1)
        self.until(step="choose")
        self.game.handle_event(("RIGHT", None))
        self.assertEqual(self.game.choice, 1)
        self.game.handle_event(("LEFT", None))
        self.assertEqual(self.game.choice, 0)
        rect = self.game.lcd_rect()
        self.game.handle_event(("LCLICK", {"pos": (rect.right - 5, rect.bottom - 5)}))
        self.assertEqual((self.game.step, self.game.choice, self.game.hit), ("reveal", 1, True))

    def test_chuumon_rises_out_of_his_bucket(self):
        """The device's reveal: the buckets alone a moment, then Chuumon
        rising row by row from out of sight to peeking over the rim."""
        self.places.append(1)
        self.until(step="choose")
        self.game.handle_event(("A", None))             # left: a miss
        rows = []
        while self.game.phase == "charge" and self.game.step == "reveal":
            rows.append(self.game.reveal_row(self.game.elapsed()))
            self.tick(25)
        self.assertEqual(rows[0], shuffle.CHUUMON_ROWS, "out of sight at first")
        self.assertEqual(rows[-1], shuffle.PEEK_ROW, "peeking at the end")
        self.assertEqual(rows, sorted(rows, reverse=True), "only ever rising")
        self.assertEqual(set(range(shuffle.PEEK_ROW, shuffle.CHUUMON_ROWS + 1)), set(rows),
                         "a row at a time")

    def test_a_found_chuumon_starts_the_next_round_on_his_bucket(self):
        self.play_round(where=1, pick=1)
        self.places.append(0)
        self.until(step="intro")
        self.assertEqual(self.game.home, 1)

    def test_the_mouse_points_and_a_drag_counts_as_a_tap(self):
        self.places.append(1)
        self.until(step="choose")
        rect = self.game.lcd_rect()
        self.game.handle_event(("MOUSE_MOTION", {"pos": (rect.right - 5, rect.centery)}))
        self.assertEqual((self.game.step, self.game.choice), ("choose", 1))
        self.game.handle_event(("DRAG_END", {"pos": (rect.right - 5, rect.bottom - 5),
                                             "start_pos": (rect.right - 9, rect.bottom - 9)}))
        self.assertEqual((self.game.step, self.game.hit), ("reveal", True))

    def test_b_leaves_mid_game(self):
        self.places.append(0)
        self.until(step="hop")
        self.game.handle_event(("B", None))
        self.assertEqual(runtime_globals.game_state, "game")

    def test_every_screen_draws(self):
        surface = pygame.Surface((240, 240))
        seen = set()
        self.places.extend([0, 1])
        self.game.update()
        while self.game.phase != "result":
            seen.add(self.game.step if self.game.phase == "charge" else self.game.phase)
            self.game.draw(surface)
            if self.game.phase == "charge" and self.game.step == "choose":
                self.game.handle_event(("A", None))     # left: a find, then a miss
            self.tick(40)
        self.assertTrue({"alert", "title", "hop", "select", "choose", "reveal", "intro"} <= seen)


if __name__ == "__main__":
    unittest.main()
