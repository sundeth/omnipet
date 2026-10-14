"""The currency screen every minigame shows after its result (owner,
2026-10-06): the pets side by side and what each module's currency gained.
A training that earned nothing goes straight back to the game.
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
from training import training  # noqa: E402

FIGHT_MONEY = {"name": "Fight Money", "unit": "P", "cap": 9999, "training_gain": [0, 10, 20, 50]}


class Pet:
    def __init__(self, module):
        self.module = module
        self.finish_training = mock.Mock()


class Graded(training.Training):
    """A training that came out GREAT."""

    def check_victory(self):
        return True

    def get_attack_count(self):
        return 2

    def check_and_award_trophies(self):
        pass


class CurrencyScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.chdir(REPO_ROOT)
        pygame.init()
        pygame.display.set_mode((240, 240))

    def setUp(self):
        self.distribute = mock.Mock()
        patches = [
            mock.patch.object(training, "get_training_targets", return_value=[]),
            mock.patch.object(training, "distribute_pets_evenly", self.distribute),
            mock.patch.object(training, "update_quest_progress", mock.Mock()),
            mock.patch.object(runtime_globals, "game_sound", SimpleNamespace(play=mock.Mock())),
            mock.patch.object(runtime_globals, "game_state", "training"),
            mock.patch.object(runtime_globals, "game_modules", {
                "IC": SimpleNamespace(currencies=[FIGHT_MONEY]),
                "DMC": SimpleNamespace(currencies=[])}),
            mock.patch.object(game_globals, "currency", {}),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        from ui.ui_manager import UIManager
        self.game = Graded(UIManager("GREEN"))

    def test_a_training_that_earned_shows_it_then_leaves(self):
        ic, dmc = Pet("IC"), Pet("DMC")
        self.game.pets = [ic, dmc]
        runtime_globals.pet_sprites[ic] = [pygame.Surface((48, 48)) for _ in range(16)]
        self.addCleanup(runtime_globals.pet_sprites.pop, ic, None)
        self.game.phase = "result"
        self.game.finish_training()
        self.assertEqual(self.game.phase, "currency")
        self.assertEqual(self.game.earnings, [("IC", "Fight Money", 20)])
        self.assertEqual(game_globals.currency, {"IC": {"Fight Money": 20}})
        ic.finish_training.assert_called_once()
        dmc.finish_training.assert_called_once()
        self.assertEqual(runtime_globals.game_state, "training")
        self.game.draw(pygame.Surface((240, 240)))     # both pets, side by side
        self.game.finish_training()
        self.assertEqual(runtime_globals.game_state, "game")
        self.game.finish_training()
        self.distribute.assert_called_once()
        ic.finish_training.assert_called_once()      # applied once only

    def test_the_screen_times_out(self):
        self.game.pets = [Pet("IC")]
        self.game.phase = "result"
        self.game.finish_training()
        for _ in range(training.CURRENCY_SCREEN_FRAMES + 1):
            self.game.update()
        self.assertEqual(runtime_globals.game_state, "game")

    def test_an_ic_module_shows_its_get_panel(self):
        """The iC's money comes up as its own "50P GET!" (ic_get.png and
        ic_digits.png, on the LCD's colour); any other currency as text."""
        from training import ic_minigame
        runtime_globals.game_modules["IC"].name = "IC"
        panel = self.game.currency_panel("IC", "Fight Money", 50)
        self.assertEqual(panel.get_size(), (192, 96))
        self.assertEqual(tuple(panel.get_at((96, 4)))[:3], ic_minigame.LCD_COLOUR)
        self.assertEqual(tuple(panel.get_at((1, 1)))[:3], (0, 0, 0), "the bracket")
        self.assertIsNone(self.game.currency_panel("DMC", "Coins", 50))

    def test_nothing_earned_goes_straight_back(self):
        self.game.pets = [Pet("DMC")]
        self.game.phase = "result"
        self.game.finish_training()
        self.assertEqual(runtime_globals.game_state, "game")
        self.assertEqual(self.game.earnings, [])


if __name__ == "__main__":
    unittest.main()
