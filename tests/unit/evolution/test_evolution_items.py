"""Evolution items (owner, 2026-10-15): one `item` field and an amount on a
route, used from the Armor / Item menu, which also offers the evolving items
(item.json effect evolve / random_evolve).

    item + item_amount     each use counts; the route is taken once the count
                           reaches the amount (1 when absent): a D-3 DigiMental
                           at once, the Twin's Digitamamon after five Bombs
    item_use (+ _amount)   the old shape, migrated on load into the above;
                           nothing counted uses before, so it never fired
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SRC = os.path.join(REPO_ROOT, "src")
for path in (SRC, REPO_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from models.game_pet import GamePet  # noqa: E402
from utils import evolution_items  # noqa: E402
from utils.jogress_utils import normalize_evolutions  # noqa: E402


def _module(*forms):
    records = {(f, 1): {"name": f, "version": 1, "stage": 4} for f in forms}
    return SimpleNamespace(name="Test", get_monster=lambda name, version: records.get((name, version)))


def _pet(routes):
    pet = GamePet.__new__(GamePet)
    pet.module, pet.name, pet.version, pet.stage = "Test", "Gabumon", 1, 3
    pet.evolve = normalize_evolutions(routes)
    pet.item_uses = {}

    def apply(evo):
        pet.name = evo["to"]
    pet._apply_evolution = Mock(side_effect=apply)
    return pet


class Migration(unittest.TestCase):
    def test_the_old_use_count_shape(self):
        routes = normalize_evolutions([{"to": "Digitamamon", "item_use": "Bomb", "item_use_amount": 5},
                                       {"to": "Flamedramon", "item": "Courage DigiMental"}])
        self.assertEqual(routes[0], {"to": "Digitamamon", "item": "Bomb", "item_amount": 5})
        self.assertEqual(routes[1], {"to": "Flamedramon", "item": "Courage DigiMental"})


class Using(unittest.TestCase):
    def test_counted_until_the_amount(self):
        pet = _pet([{"to": "Digitamamon", "item_use": "Bomb", "item_use_amount": 5}])
        with patch("models.game_pet.get_module", return_value=_module("Digitamamon")), \
                patch("models.game_pet.runtime_globals"):
            for use in range(4):
                self.assertIsNone(pet.use_evolution_item("Bomb"))
            self.assertEqual(pet.item_uses["Bomb"], 4)
            self.assertEqual(pet.use_evolution_item("Bomb"), "Digitamamon")
        self.assertEqual(pet.name, "Digitamamon")

    def test_a_digimental_evolves_at_once(self):
        pet = _pet([{"to": "Flamedramon", "item": "Courage DigiMental"},
                    {"to": "Raidramon", "item": "Friendship DigiMental"}])
        with patch("models.game_pet.get_module", return_value=_module("Flamedramon", "Raidramon")), \
                patch("models.game_pet.runtime_globals"):
            self.assertEqual(pet.armor_evolve("Friendship DigiMental"), "Raidramon")

    def test_a_missing_target_is_passed_over(self):
        pet = _pet([{"to": "Nowhere", "item": "Courage DigiMental"}])
        with patch("models.game_pet.get_module", return_value=_module()), \
                patch("models.game_pet.runtime_globals"):
            self.assertIsNone(pet.use_evolution_item("Courage DigiMental"))
        pet._apply_evolution.assert_not_called()


class Menu(unittest.TestCase):
    def test_what_the_armor_item_menu_offers(self):
        pet = _pet([{"to": "Digitamamon", "item": "Bomb", "item_amount": 5}])
        bomb = SimpleNamespace(name="Bomb", effect="status_change")
        digimental = SimpleNamespace(name="Courage DigiMental", effect="digimental")
        ouryujin = SimpleNamespace(name="Ouryujin", effect="evolve")
        meat = SimpleNamespace(name="Meat", effect="status_change")
        self.assertTrue(evolution_items.is_evolution_item(bomb, [pet]))      # a route names it
        self.assertTrue(evolution_items.is_evolution_item(digimental))
        self.assertTrue(evolution_items.is_evolution_item(ouryujin))
        self.assertFalse(evolution_items.is_evolution_item(meat, [pet]))
        self.assertTrue(evolution_items.can_use(pet, bomb))
        self.assertFalse(evolution_items.can_use(pet, digimental))

    def test_an_evolving_item_uses_its_own_target(self):
        pet = _pet([])
        item = SimpleNamespace(name="Ouryujin", effect="evolve", module="Test")
        with patch("utils.evolution_items.item_effects.fits", return_value=True) as fits, \
                patch("utils.evolution_items.item_effects.apply_pet_effect", return_value=True):
            self.assertTrue(evolution_items.can_use(pet, item))
            self.assertEqual(evolution_items.use(pet, item), (True, True))
        fits.assert_called_once()


if __name__ == "__main__":
    unittest.main()
