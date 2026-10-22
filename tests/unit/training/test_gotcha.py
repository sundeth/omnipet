"""Gotcha!, the iC 20X's catch-Chuumon minigame (owner, 2026-10-20).

It runs every minigame's phases, the 20X's READY and START in place of the
game's READY. Played on a clock the test moves, so the rules read off the
owner's video (utilities/IC/10.mp4 at 137-232 s) -- Chuumon's walk and its
speeds, the arrows, the trap's fall, what a catch is, the stages and the
prizes -- are checked without waiting for them.
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
from models.animation import PetFrame  # noqa: E402
from training import gotcha, ic_minigame, training  # noqa: E402
from training.gotcha import (  # noqa: E402
    CATCH_HOLD_MS, CENTRE_COL, DECIDE_ROW, FALL_ROW_MS, HANG_ROW, LAND_ROW, LAST_COL,
    MISS_HOLD_MS, OPENING_SPEED, SPEEDS, TARGETS, TAUNT_MS, Gotcha)
from training.ic_minigame import (  # noqa: E402
    CLEAR_20X_MS, READY_20X_MS, START_20X_MS)

FIGHT_MONEY = {"name": "Fight Money", "unit": "P", "cap": 9999}
ASSETS = os.path.join(REPO_ROOT, "assets")
ORIGINALS = os.path.join(REPO_ROOT, "utilities", "IC", "originals")
SLOW, FAST = FALL_ROW_MS[1], FALL_ROW_MS[0]


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


class GotchaTests(unittest.TestCase):
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
                                      training_uses_battle_cost=True, battle_cost_type="Hunger",
                                      battle_cost_amount=1,  # the iC's heart a play
                                      folder_path=os.path.join(REPO_ROOT, "modules", "IC"))}),
            mock.patch.object(game_globals, "currency", {}),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        gotcha.random.seed(5)
        from ui.ui_manager import UIManager
        self.game = Gotcha(UIManager("GREEN"))
        self.surface = pygame.Surface((240, 240))

    # ------------------------------------------------------------ driving
    def tick(self, ms=10):
        self.now += ms
        self.game.update()
        # The minigame's own screens are drawn; the result and currency
        # screens are the shared Training ones.
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

    def run_until(self, step=None, phase=None, limit=60000):
        end = self.now + limit
        while not ((step and self.game.phase == "charge" and self.game.step == step)
                   or (phase and self.game.phase == phase)):
            self.assertLess(self.now, end, f"never reached {step or phase}; at "
                                           f"{self.game.phase}/{self.game.step}")
            self.tick()

    def hold(self, col):
        """Chuumon stands at *col* and takes no step for a long while."""
        self.game.col = col
        self.game.next_step = self.now + 10 ** 7

    def drop(self, fall=SLOW):
        with mock.patch.object(gotcha.random, "random", return_value=0.0 if fall == FAST else 0.99):
            self.game.handle_event(("A", None))

    def catch_one(self):
        self.run_until("play")
        self.hold(CENTRE_COL)
        self.drop()
        self.run_until("landed")
        self.tick(CATCH_HOLD_MS + 10)

    def clear_stage(self):
        for _ in range(TARGETS[self.game.stage] - self.game.catches):
            self.catch_one()

    # ------------------------------------------------------------ the tests
    def test_the_20x_ready_and_start_open_it(self):
        self.assertEqual(self.game.phase, "alert")
        self.start()
        self.assertGreaterEqual(self.now, READY_20X_MS + START_20X_MS)
        self.assertEqual(self.played(), ["ic20_ready", "ic20_start"])
        self.assertEqual((self.game.step, self.game.col, self.game.facing), ("play", LAST_COL, -1))
        self.assertEqual((self.game.step_ms, self.game.arrows), OPENING_SPEED)
        self.assertEqual(self.game.trap_row, HANG_ROW)

    def test_chuumon_walks_a_column_a_step_at_the_opening_speed(self):
        self.start()
        cols = []
        for _ in range(4):
            self.tick(OPENING_SPEED[0])
            cols.append(self.game.col)
        self.assertEqual(cols, [15, 14, 13, 12])

    def test_at_an_edge_he_turns_in_place_and_takes_a_new_speed(self):
        self.start()
        seen = set()
        for _ in range(6):
            self.game.col, self.game.facing = 0, -1
            self.game.next_step = self.now + 1
            self.tick(5)
            self.assertEqual((self.game.col, self.game.facing), (0, 1), "a turn where he stands")
            self.assertIn((self.game.step_ms, self.game.arrows), SPEEDS)
            seen.add(self.game.arrows)
            self.tick(self.game.step_ms)
            self.assertEqual(self.game.col, 1, "then a step at the new speed")
        self.game.col, self.game.facing = LAST_COL, 1
        self.game.next_step = self.now + 1
        self.tick(5)
        self.assertEqual((self.game.col, self.game.facing), (LAST_COL, -1))
        self.assertGreater(len(seen), 1, "the speed is picked at random")

    def test_the_arrows_show_the_speed(self):
        self.assertEqual([arrows for _, arrows in SPEEDS], [0, 1, 2])
        self.assertEqual([ms for ms, _ in SPEEDS], [360, 250, 125])
        self.assertEqual(OPENING_SPEED, (280, 0))
        self.start()
        for speed in SPEEDS:
            self.game.step_ms, self.game.arrows = speed
            self.tick()     # drawn with 0, 1 and 2 arrows a side

    def test_a_drop_falls_a_row_at_a_time_and_chuumon_walks_on(self):
        self.start()
        self.tick(OPENING_SPEED[0] * 3)
        col = self.game.col
        self.drop(SLOW)
        self.assertEqual(self.game.step, "drop")
        self.assertIn("menu", self.played(), "the key's chirp")
        self.tick(SLOW - 5)
        self.assertEqual(self.game.trap_row, HANG_ROW)
        self.tick(10)
        self.assertEqual(self.game.trap_row, HANG_ROW + 1)
        self.tick(SLOW * 2)
        self.assertEqual(self.game.trap_row, HANG_ROW + 3)
        self.assertLess(self.game.col, col, "he walks on under it")

    def test_the_fall_has_two_rates(self):
        for fall in (FAST, SLOW):
            with self.subTest(fall=fall):
                self.setUp()
                self.start()
                self.hold(CENTRE_COL)
                self.drop(fall)
                self.tick((DECIDE_ROW - HANG_ROW) * fall - 5)
                self.assertEqual(self.game.step, "drop")
                self.tick(10)
                self.assertEqual(self.game.step, "fall")
        self.assertEqual(FALL_ROW_MS, (94, 125))

    def test_under_the_trap_he_is_caught(self):
        for col in (CENTRE_COL - 1, CENTRE_COL, CENTRE_COL + 1):
            with self.subTest(col=col):
                self.setUp()
                self.start()
                self.hold(col)
                self.drop()
                self.run_until("landed")
                self.assertEqual((self.game.trap_row, self.game.catches, self.game.col),
                                 (LAND_ROW, 1, col))
                self.assertEqual(self.played().count("menu"), 2, "the press and the catch")
                self.tick(CATCH_HOLD_MS + 10)
                self.assertEqual((self.game.step, self.game.trap_row), ("play", HANG_ROW))
                self.tick(OPENING_SPEED[0] + 10)
                self.assertEqual(self.game.col, col - 1, "he walks on as he was")

    def test_anywhere_else_the_trap_stops_and_he_taunts(self):
        for col in (CENTRE_COL - 3, CENTRE_COL + 6):
            with self.subTest(col=col):
                self.setUp()
                self.start()
                self.hold(col)
                self.drop()
                self.run_until("missed")
                self.assertEqual(self.game.trap_row, DECIDE_ROW, "it stops over his head")
                self.assertNotIn("ic_fail", self.played())
                self.tick(MISS_HOLD_MS + 10)
                self.assertEqual(self.game.step, "taunt")
                self.assertEqual(self.played()[-1], "ic_fail", "the fail sound as the taunt starts")
                # The player's own Digimon shows its defeat: LOSE, then ANGRY.
                drawn = []
                with mock.patch.object(self.game, "blit_pet",
                                  side_effect=lambda _s, frame, col, row: drawn.append(frame)):
                    self.game.draw_game(pygame.Surface((240, 240)))
                    first = drawn[-1]
                    self.tick(gotcha.TAUNT_FRAME_MS)
                    self.game.draw_game(pygame.Surface((240, 240)))
                self.assertEqual((first, drawn[-1]), (PetFrame.LOSE, PetFrame.ANGRY))
                for _ in range(TAUNT_MS // 250):
                    self.tick(250)
                self.run_until(phase="result")
                self.assertEqual((self.game.get_attack_count(), self.game.prize), (0, 0))
                self.assertFalse(self.game.succeeded)
                self.assertEqual(self.played().count("ic_fail"), 1, "the fail sound once")

    def test_he_is_judged_where_he_stands_as_the_trap_reaches_row_15(self):
        self.start()
        # Walking left at the opening speed from column 11, a slow fall
        # reaches row 15 after 750 ms: two steps (280, 560) -- column 9.
        self.game.col, self.game.facing = 11, -1
        self.game.next_step = self.now + 280
        self.drop(SLOW)
        self.run_until("fall")
        self.assertEqual(self.game.col, 9)

    def test_a_press_while_the_trap_falls_does_nothing(self):
        self.start()
        self.hold(CENTRE_COL)
        self.drop()
        self.tick(SLOW * 2)
        row = self.game.trap_row
        self.game.handle_event(("A", None))
        self.assertEqual((self.game.step, self.game.trap_row), ("drop", row))
        self.assertEqual(self.played().count("menu"), 1)

    def test_a_tap_drops_the_trap(self):
        self.start()
        self.game.handle_event(("LCLICK", {"pos": (120, 120)}))
        self.assertEqual(self.game.step, "drop")

    def test_a_cleared_stage_shows_clear_ready_and_start(self):
        self.start()
        self.game.step_ms, self.game.arrows = SPEEDS[2]
        self.clear_stage()
        self.assertEqual(self.game.step, "clear")
        self.assertEqual(self.played()[-1], "ic_success")
        self.tick(CLEAR_20X_MS)
        self.assertEqual(self.game.step, "ready")
        self.tick(READY_20X_MS)
        self.assertEqual(self.game.step, "start")
        self.tick(START_20X_MS)
        self.assertEqual((self.game.step, self.game.stage, self.game.catches), ("play", 1, 0))
        self.assertEqual((self.game.col, self.game.facing), (LAST_COL, -1), "from the right edge")
        self.assertEqual((self.game.step_ms, self.game.arrows), SPEEDS[2], "at the speed he had")

    def test_a_miss_after_a_stage_is_good_and_pays_10(self):
        self.start()
        self.clear_stage()
        self.run_until("play")
        self.hold(0)
        self.drop()
        self.run_until(phase="result")
        self.assertEqual((self.game.get_attack_count(), self.game.prize), (1, 10))
        self.assertFalse(self.game.succeeded)

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
        self.assertEqual(self.played()[-1], "ic_success")
        self.run_until(phase="currency")
        self.assertEqual(game_globals.currency, {"IC": {"Fight Money": 50}})
        self.pet._apply_reliability_event.assert_called_once_with("reliability_minigame_success")

    def test_the_stages_take_3_5_7_catches_and_pay_10_30_50(self):
        self.assertEqual(gotcha.PRIZES, (0, 10, 30, 50))
        self.assertEqual(TARGETS, (3, 5, 7))


class ArtTests(unittest.TestCase):
    SIZES = {"chuumon": (48, 48), "trap": (48, 42), "arrow": (9, 15)}

    def test_every_sprite_is_in_the_game_and_kept_as_an_original(self):
        from PIL import Image
        for name, size in self.SIZES.items():
            with self.subTest(name=name):
                art = os.path.join(ASSETS, f"gotcha_{name}.png")
                original = os.path.join(ORIGINALS, "gotcha", f"gotcha_{name}.png")
                self.assertEqual(Image.open(art).size, size)
                self.assertEqual(Image.open(original).size, size)

    def test_the_bonus_list_plays_it(self):
        from scenes.scene_training import BONUS_MODES
        self.assertIs(BONUS_MODES["gotcha"]["cls"], Gotcha)


if __name__ == "__main__":
    unittest.main()
