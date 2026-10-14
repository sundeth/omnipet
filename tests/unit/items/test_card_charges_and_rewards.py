"""Checks for charge-tool routing, exact plate sides, and shiny rewards."""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

# These tests live under utilities/claude/tests/, three folders below
# the repo root, so they are not carried in the git repository.
REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SRC = os.path.join(REPO_ROOT, "src")
for path in (SRC, REPO_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from core import game_globals, runtime_globals  # noqa: E402
from utils import card_utils, utils_unlocks  # noqa: E402


class CardChargeTests(unittest.TestCase):
    def test_tool_and_both_buttons_select_only_one_effect_group(self):
        data = {
            "cards": [],
            "packs": [],
            "effects": [
                {"tool": "DigiSoul Charge", "value": "00110", "lr": "Any",
                 "effects": [{"type": "DNA", "dna": "Machine"}]},
                {"tool": "Plate Charge", "value": "00110", "lr": "L",
                 "effects": [{"type": "DNA", "dna": "Holy"}]},
                {"tool": "Plate Charge", "value": "00110", "lr": "R",
                 "effects": [{"type": "Item", "item": "Fowl Tornado"}]},
                {"tool": "Plate Charge", "value": "00110", "lr": "L/R",
                 "effects": [{"type": "DNA", "dna": "Holy"}]},
            ],
        }
        with patch.object(card_utils, "get_module_cards", return_value=data):
            plate = card_utils.resolve_card_effects(
                "IC", {"type": "iD Plate", "value": "00110", "lr": "L/R"})
            soul = card_utils.resolve_card_effects(
                "IC", {"type": "Soul Plate", "value": "00110", "lr": "L/R"})

        self.assertEqual(plate, [{"type": "DNA", "dna": "Holy"}])
        self.assertEqual(soul, [{"type": "DNA", "dna": "Machine"}])

    def test_dna_effect_targets_only_the_declared_version(self):
        v1 = SimpleNamespace(module="IC", version=1,
                             add_dna=Mock(return_value=1))
        v2 = SimpleNamespace(module="IC", version=2,
                             add_dna=Mock(return_value=1))
        effects = [{"type": "DNA", "dna": "Beast", "amount": 1,
                    "version": 1}]
        with patch("utils.pet_utils.get_selected_pets", return_value=[v1, v2]):
            outcome = card_utils.apply_card_effects("IC", effects)

        v1.add_dna.assert_called_once_with("Beast", 1)
        v2.add_dna.assert_not_called()
        self.assertEqual(outcome["rewards"][0]["reward_value"], "Beast DigiSoul")

    def test_one_of_each_adds_every_canonical_digisoul(self):
        pet = SimpleNamespace(module="IC", version=1,
                              add_dna=Mock(return_value=1))
        effects = [{"type": "DNA", "dna": "X of each", "amount": 1,
                    "version": -1}]
        with patch("utils.pet_utils.get_selected_pets", return_value=[pet]):
            card_utils.apply_card_effects("IC", effects)

        self.assertEqual(
            [call.args[0] for call in pet.add_dna.call_args_list],
            list(card_utils.constants.DIGISOUL_DNA_TYPES))


class CardRewardTests(unittest.TestCase):
    def setUp(self):
        self.old_collection = game_globals.card_collection
        game_globals.card_collection = {}

    def tearDown(self):
        game_globals.card_collection = self.old_collection

    def test_id_plate_can_be_shiny_but_soul_plate_cannot(self):
        data = {"cards": [
            {"id": "id", "type": "iD Plate"},
            {"id": "soul", "type": "Soul Plate"},
        ], "effects": [], "packs": []}
        with patch.object(card_utils, "get_module_cards", return_value=data):
            self.assertTrue(card_utils.add_card_copy("IC", "id", shiny=True))
            self.assertFalse(card_utils.add_card_copy("IC", "soul", shiny=True))

        self.assertEqual(card_utils.get_owned("IC", "id"),
                         {"digital": 1, "physical": 0, "shiny": 1})
        self.assertEqual(card_utils.get_owned("IC", "soul"),
                         {"digital": 1, "physical": 0, "shiny": 0})

    def test_unlock_card_reward_is_given_only_on_first_unlock(self):
        unlock = {"type": "battle", "name": "reward", "label": "Reward",
                  "card": "card-id"}
        module = SimpleNamespace(unlocks=[unlock])
        old_unlocks = game_globals.unlocks
        game_globals.unlocks = {}
        try:
            with patch.dict(runtime_globals.game_modules, {"IC": module}, clear=True), \
                    patch.object(runtime_globals.game_message, "add_slide"), \
                    patch("utils.reward_utils.reward_unlock"), \
                    patch.object(card_utils, "get_module_cards", return_value={
                        "cards": [{"id": "card-id", "type": "iD Plate",
                                   "name": "Reward Card"}],
                        "effects": [], "packs": []
                    }), \
                    patch.object(card_utils, "add_card_copy",
                                 return_value=True) as add_copy:
                utils_unlocks.unlock_item("IC", "battle", "reward")
                utils_unlocks.unlock_item("IC", "battle", "reward")

            add_copy.assert_called_once_with("IC", "card-id", shiny=True)
        finally:
            game_globals.unlocks = old_unlocks


if __name__ == "__main__":
    unittest.main()
