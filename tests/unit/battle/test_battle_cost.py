"""The battle cost gates who may battle, as well as what a battle spends."""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

# These tests live under utilities/claude/tests/, three folders below
# the repo root, so they are not carried in the git repository.
REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SRC = os.path.join(REPO_ROOT, "src")
for path in (SRC, REPO_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from models.game_pet import GamePet  # noqa: E402


def _pet(hunger, dp=0):
    pet = GamePet.__new__(GamePet)
    pet.module = "Test"
    pet.name = "Testmon"
    pet.state = "idle"
    pet.hunger = hunger
    pet.dp = dp
    pet.sick = pet.injury = 0
    pet.stage = 3
    pet.power = 20
    pet.atk_main = 1
    return pet


def _module(cost_type, amount):
    return SimpleNamespace(battle_cost_type=cost_type, battle_cost_amount=amount,
                           care_can_battle_while_sick=True,
                           care_block_actions_when_sleeping=False)


class BattleCostTests(unittest.TestCase):
    def reason(self, pet, module):
        with patch("models.game_pet.get_module", return_value=module):
            return pet.battle_block_reason()

    def test_a_hunger_cost_of_zero_refuses_a_hungry_pet(self):
        # DMM, DMRV and PENZ: battles are free, but not on an empty stomach.
        module = _module("Hunger", 0)
        self.assertEqual(self.reason(_pet(hunger=0), module), "hungry")
        self.assertIsNone(self.reason(_pet(hunger=1), module))

    def test_a_hunger_cost_still_needs_the_amount(self):
        module = _module("Hunger", 2)
        self.assertEqual(self.reason(_pet(hunger=1), module), "hunger=1 < 2")
        self.assertIsNone(self.reason(_pet(hunger=2), module))

    def test_a_fractional_hunger_cost_is_unchanged(self):
        # DMX spends a quarter heart a battle.
        module = _module("Hunger", 0.25)
        self.assertEqual(self.reason(_pet(hunger=0), module), "hungry")
        self.assertIsNone(self.reason(_pet(hunger=0.25), module))

    def test_nothing_never_refuses(self):
        self.assertIsNone(self.reason(_pet(hunger=0), _module("Nothing", 0)))


if __name__ == "__main__":
    unittest.main()
