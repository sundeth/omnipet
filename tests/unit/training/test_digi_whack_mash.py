"""Digi Whack and Digi Mash, the iC 20X's minigames (owner, 2026-10-07).

They run every minigame's phases, the 20X's READY and START in place of the
game's READY. Played on a clock the test moves, so the rules read off the
owner's videos (utilities/IC/10.mp4, 11.mp4) -- the pointer's run, the two
presses a hit takes, the stages' hits, the counter's ladder, the prizes --
are checked without waiting for them.
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
from training import digi_mash, digi_whack, ic_minigame, training  # noqa: E402
from training.digi_mash import DigiMash, FORMS, MASH_MS  # noqa: E402
from training.digi_whack import (  # noqa: E402
    HIT_MS, HOLES, OUT, OUT_MS, PEEK, TARGETS, DigiWhack)
from training.ic_minigame import (  # noqa: E402
    CLEAR_20X_MS, READY_20X_MS, START_20X_MS)

FIGHT_MONEY = {"name": "Fight Money", "unit": "P", "cap": 9999}
ASSETS = os.path.join(REPO_ROOT, "assets")
ORIGINALS = os.path.join(REPO_ROOT, "utilities", "IC", "originals")


class FakePet:
    def __init__(self, **fields):
        self.__dict__.update(fields)


def ic_pet(**fields):
    pet = FakePet(module="IC", hunger=3, stage=3, atk_main=1, atk_alt=0, atk_alt_2=0,
                  reliability=15, _apply_reliability_event=mock.Mock())
    pet.__dict__.update(fields)
    return pet


def quiet_sound():
    return SimpleNamespace(play=mock.Mock(return_value=None), get_duration=lambda name: 0,
                           stop=lambda name: None, is_playing=lambda name: False)


class Base(unittest.TestCase):
    GAME = None

    @classmethod
    def setUpClass(cls):
        os.chdir(REPO_ROOT)
        pygame.init()
        pygame.display.set_mode((240, 240))

    def setUp(self):
        self.now = 0
        self.pet = ic_pet()
        self.sound = quiet_sound()
        targets = [self.pet]
        patches = [
            mock.patch.object(pygame.time, "get_ticks", side_effect=lambda: self.now),
            mock.patch.object(training, "get_training_targets", return_value=targets),
            mock.patch.object(ic_minigame, "get_training_targets", return_value=targets),
            mock.patch.object(training, "distribute_pets_evenly", mock.Mock()),
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
        self.game = self.GAME(UIManager("GREEN"))
        self.surface = pygame.Surface((240, 240))

    def tick(self, ms=10):
        self.now += ms
        self.game.update()
        # The minigame's own screens are drawn; the result and currency
        # screens are the shared Training ones (their fonts are cached
        # across test modules, which may have quit pygame since).
        if self.game.phase in ("alert", "charge"):
            self.game.draw(self.surface)

    def played(self):
        return [c.args[0] for c in self.sound.play.call_args_list]

    def start(self):
        for _ in range(10000):
            if self.game.phase != "alert":
                break
            self.tick()
        self.assertEqual(self.game.phase, "charge")

    def run_until(self, step=None, phase=None, limit=30000):
        end = self.now + limit
        while not ((step and self.game.phase == "charge" and self.game.step == step)
                   or (phase and self.game.phase == phase)):
            self.assertLess(self.now, end, f"never reached {step or phase}; at "
                                           f"{self.game.phase}/{self.game.step}")
            self.tick()


class DigiWhackTests(Base):
    GAME = DigiWhack

    def setUp(self):
        super().setUp()
        digi_whack.random.seed(7)

    def wait_for(self, state, limit=20000):
        """The first hole in *state*, waiting for one."""
        end = self.now + limit
        while state not in self.game.holes:
            self.assertLess(self.now, end, f"no hole became {state}")
            self.tick(5)
        return self.game.holes.index(state)

    def point_at(self, k):
        while self.game.pointer != k:
            self.game.handle_event(("RIGHT", None))

    def whack_one(self):
        """Wait for a Digimon out, move the pointer under it and whack it."""
        k = self.wait_for(OUT)
        self.point_at(k)
        hits = self.game.hits
        self.game.handle_event(("A", None))
        self.assertEqual(self.game.hits, hits + 1)
        self.assertEqual(self.game.hit_hole, k)

    def clear_stage(self):
        for _ in range(TARGETS[self.game.stage]):
            self.whack_one()
            self.tick(HIT_MS + 10)

    def test_the_20x_ready_and_start_open_it(self):
        self.assertEqual(self.game.phase, "alert")
        self.start()
        self.assertGreaterEqual(self.now, READY_20X_MS + START_20X_MS)
        self.assertEqual(self.played(), ["ic20_ready", "ic20_start"])
        self.assertEqual((self.game.step, self.game.pointer), ("play", 0))

    def test_the_pointer_moves_only_on_a_key(self):
        self.start()
        self.tick(5000)
        self.assertEqual(self.game.pointer, 0, "it does not run on its own")
        seen = []
        for key in ("RIGHT", "DOWN", "SELECT", "LEFT"):
            self.game.handle_event((key, None))
            seen.append(self.game.pointer)
        self.assertEqual(seen, [1, 2, 0, 2], "top, left, right; LEFT back a hole")

    def test_the_holes_come_out_on_their_own(self):
        self.start()
        seen = set()
        for _ in range(3000):
            self.tick(10)
            seen.update(k for k, state in enumerate(self.game.holes) if state == OUT)
        self.assertEqual(seen, {0, 1, 2})

    def test_an_unhit_digimon_goes_back_in(self):
        self.start()
        k = self.wait_for(OUT)
        self.tick(OUT_MS[0] + 10)
        self.assertNotEqual(self.game.holes[k], OUT)

    def test_a_whack_at_a_peeking_digimon_loses(self):
        self.start()
        self.clear_stage()
        self.run_until("play")
        k = self.wait_for(PEEK)
        self.point_at(k)
        self.game.handle_event(("A", None))
        self.assertEqual(self.game.step, "miss")
        self.run_until(phase="result")
        self.assertEqual(self.game.get_attack_count(), 1, "one stage: GOOD")
        self.assertEqual(self.game.prize, 10)
        self.assertFalse(self.game.succeeded)
        self.assertIn("ic_fail", self.played())

    def test_a_whack_at_an_empty_hole_loses(self):
        self.start()
        self.game.holes = ["empty"] * 3
        self.game.until = [self.now + 10 ** 6] * 3
        self.game.handle_event(("A", None))
        self.run_until(phase="result")
        self.assertEqual((self.game.get_attack_count(), self.game.prize), (0, 0))

    def test_a_cleared_stage_shows_clear_ready_and_start(self):
        self.start()
        self.clear_stage()
        self.assertEqual(self.game.step, "clear")
        self.assertEqual(self.played()[-1], "ic_success")
        self.tick(CLEAR_20X_MS)
        self.assertEqual(self.game.step, "ready")
        self.tick(READY_20X_MS)
        self.assertEqual(self.game.step, "start")
        self.tick(START_20X_MS)
        self.assertEqual((self.game.step, self.game.stage, self.game.hits), ("play", 1, 0))

    def hole_pos(self, k):
        col, row = HOLES[k]
        return self.game.at(col + 4, row + 2)

    def test_the_mouse_points_at_the_hole_it_is_over(self):
        self.start()
        self.game.handle_event(("MOUSE_MOTION", {"pos": self.hole_pos(2)}))
        self.assertEqual(self.game.pointer, 2)
        self.game.handle_event(("MOUSE_MOTION", {"pos": (1, 1)}))
        self.assertEqual(self.game.pointer, 2, "off the holes, it stays")

    def test_a_click_on_a_digimon_out_whacks_it_at_once(self):
        self.start()
        k = self.wait_for(OUT)
        self.game.pointer = (k + 1) % len(HOLES)
        self.game.handle_event(("LCLICK", {"pos": self.hole_pos(k)}))
        self.assertEqual((self.game.pointer, self.game.hits, self.game.hit_hole), (k, 1, k))

    def test_a_click_on_an_empty_hole_loses(self):
        self.start()
        self.game.holes = ["empty"] * 3
        self.game.until = [self.now + 10 ** 6] * 3
        self.game.handle_event(("LCLICK", {"pos": self.hole_pos(1)}))
        self.assertEqual(self.game.step, "miss")

    def test_a_click_off_the_holes_does_nothing(self):
        self.start()
        self.game.handle_event(("LCLICK", {"pos": (1, 1)}))
        self.assertEqual((self.game.step, self.game.hits), ("play", 0))

    def test_three_stages_are_excellent_pay_50_and_raise_reliability(self):
        self.start()
        for stage in range(3):
            self.clear_stage()
            if stage < 2:
                self.run_until("play")
        self.run_until(phase="result")
        self.assertEqual(self.game.get_attack_count(), 3, "EXCELLENT")
        self.assertEqual(self.game.prize, 50)
        self.assertTrue(self.game.succeeded)
        self.run_until(phase="currency")
        self.assertEqual(game_globals.currency, {"IC": {"Fight Money": 50}})
        self.pet._apply_reliability_event.assert_called_once_with("reliability_minigame_success")

    def test_the_stages_take_3_5_7_hits_and_pay_10_30_50(self):
        self.assertEqual(digi_whack.PRIZES, (0, 10, 30, 50))
        self.assertEqual(TARGETS, (3, 5, 7))


class DigiMashTests(Base):
    GAME = DigiMash

    def mash(self, presses):
        for _ in range(presses):
            self.game.handle_event(("A", None))

    def test_the_20x_ready_and_start_open_it(self):
        self.start()
        self.assertEqual(self.played(), ["ic20_ready", "ic20_start"])
        self.assertEqual((self.game.step, self.game.count), ("mash", 0))

    def test_each_press_counts_and_beeps(self):
        self.start()
        self.mash(3)
        self.assertEqual(self.game.count, 3)
        self.assertEqual(self.played()[-3:], ["ic_press"] * 3)

    def test_the_count_is_the_form(self):
        self.start()
        for presses, name in ((15, "Puwamon"), (16, "Falcomon"), (20, "Falcomon"), (21, "Peckmon"),
                              (26, "LoaderLeomon"), (31, "top")):
            self.game.count = presses
            self.assertEqual(FORMS[self.game.form()][1], name, presses)
            self.tick()

    def test_presses_stop_counting_when_time_is_up(self):
        self.start()
        self.tick(MASH_MS)
        self.assertEqual(self.game.step, "hold")
        self.mash(5)
        self.assertEqual(self.game.count, 0)

    def test_the_prizes_follow_the_ladder(self):
        for presses, grade, prize, success in ((5, 0, 0, False), (16, 1, 10, False), (22, 2, 20, False),
                                               (27, 2, 30, False), (31, 3, 50, True)):
            with self.subTest(presses=presses):
                self.setUp()
                self.start()
                self.mash(presses)
                self.run_until(phase="result")
                self.assertEqual((self.game.get_attack_count(), self.game.prize, self.game.succeeded),
                                 (grade, prize, success))
                self.assertIn("ic_fail" if presses < 16 else "ic_success", self.played())

    def test_the_counter_is_two_digits(self):
        self.start()
        self.mash(120)
        self.assertEqual(self.game.count, digi_mash.MAX_COUNT)
        self.tick()


class ArtTests(unittest.TestCase):
    def test_every_sprite_is_in_the_game_and_kept_as_an_original(self):
        files = {"digi_whack": ["hole", "peek", "out", "hit", "cursor"],
                 "digi_mash": ["digits", "puwamon", "falcomon", "peckmon", "loaderleomon"]}
        for game, names in files.items():
            for name in names:
                self.assertTrue(os.path.exists(os.path.join(ASSETS, f"{game}_{name}.png")), name)
                self.assertTrue(os.path.exists(os.path.join(ORIGINALS, game, f"{game}_{name}.png")), name)
        for name in ("ready", "start", "clear"):
            self.assertTrue(os.path.exists(os.path.join(ORIGINALS, "ic20", f"ic20_{name}.png")), name)
            self.assertTrue(os.path.exists(os.path.join(ASSETS, "ui", f"Combat_IC20{name.title()}_1.png")), name)

    def test_the_bonus_list_plays_them(self):
        from scenes.scene_training import BONUS_MODES
        self.assertIs(BONUS_MODES["digi_whack"]["cls"], DigiWhack)
        self.assertIs(BONUS_MODES["digi_mash"]["cls"], DigiMash)


if __name__ == "__main__":
    unittest.main()
