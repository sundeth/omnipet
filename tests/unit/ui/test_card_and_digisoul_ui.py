"""Focused checks for collection ordering and DigiSoul status presentation."""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

# These tests live under utilities/claude/tests/, three folders below
# the repo root, so they are not carried in the git repository.
REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SRC = os.path.join(REPO_ROOT, "src")
for path in (SRC, REPO_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

import pygame  # noqa: E402

from core import constants  # noqa: E402
from models.game_pet import GamePet  # noqa: E402
from scenes.scene_status import digisoul_below_flags_available  # noqa: E402
from ui.components.digisoul_icon import (  # noqa: E402
    load_digisoul_sprite,
    normalize_digisoul,
)
from utils.card_utils import ordered_cards  # noqa: E402


class CardOrderingTests(unittest.TestCase):
    def test_id_plates_are_ordered_by_natural_series_then_number(self):
        cards = [
            {"type": "iD Plate", "series": "2", "number": 1,
             "name": "Series 2"},
            {"type": "iD Plate", "series": "1", "number": 2,
             "name": "Series 1 Number 2"},
            {"type": "Soul Plate", "number": 0, "name": "Zeta"},
            {"type": "iD Plate", "series": "Promo 01", "number": 1001,
             "name": "Promo"},
            {"type": "iD Plate", "series": "10", "number": 1,
             "name": "Series 10"},
            {"type": "Soul Plate", "number": 0, "name": "Alpha"},
            {"type": "iD Plate", "series": "1", "number": 1,
             "name": "Series 1 Number 1"},
        ]

        self.assertEqual(
            [card["name"] for card in ordered_cards(cards)],
            ["Alpha", "Zeta", "Series 1 Number 1", "Series 1 Number 2",
             "Series 2", "Series 10", "Promo"],
        )


class DigiSoulStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((1, 1))

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def test_all_canonical_digisoul_sprites_load(self):
        for digisoul in constants.DIGISOUL_DNA_TYPES:
            with self.subTest(digisoul=digisoul):
                self.assertEqual(normalize_digisoul(digisoul.lower()), digisoul)
                self.assertEqual(
                    load_digisoul_sprite(digisoul, 22).get_size(), (22, 22))

    def test_pet_reads_native_digisoul_from_species_data(self):
        pet = GamePet.__new__(GamePet)
        pet.set_data({
            "module": "IC", "name": "Agumon", "stage": 3,
            "version": 1, "special": False, "evolve": [],
            "digisoul": "Dragon",
        })
        self.assertEqual(pet.digisoul, "Dragon")

    def test_below_flags_slot_is_used_only_when_free(self):
        self.assertTrue(digisoul_below_flags_available(
            ["Age", "Weight", "DP", "Power", "Digisoul"]))
        for stat in ("Level", "Experience", "Trophies", "Vital Values"):
            with self.subTest(stat=stat):
                self.assertFalse(digisoul_below_flags_available(
                    ["Digisoul", stat]))
        self.assertFalse(digisoul_below_flags_available(
            ["Digisoul", "Mistakes/Condition Hearts"], True))
        self.assertTrue(digisoul_below_flags_available(
            ["Digisoul", "Mistakes/Condition Hearts"], False))


if __name__ == "__main__":
    unittest.main()
