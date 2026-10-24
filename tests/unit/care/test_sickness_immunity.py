"""MOD-07 / decision 2 (owner, 2026-10-14): `heal_doses: 0` means the form
cannot fall sick, nor be injured (since 2026-10-21 counted apart:
utils.ailments). Most Baby I are immune; a
form that can battle needs at least one dose. It used to show sick and count
an injury with nothing to cure. (Absent `heal_doses` loads as 1.)

Checked on GamePet and its Android copy (services.android_pet_rules), which
must agree.
"""

import os
import sys
import unittest
from unittest.mock import Mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SRC = os.path.join(REPO_ROOT, "src")
for path in (SRC, REPO_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from models.game_pet import GamePet  # noqa: E402
from services.android_pet_rules import AndroidPetRules  # noqa: E402


def _pet(cls, **fields):
    pet = cls.__new__(cls)
    pet.name = "Testmon"
    pet.state = "idle"
    pet.sick = pet.injury = pet.sick_total = pet.injury_total = 0
    pet.heal_doses = 1
    pet.__dict__.update(fields)
    pet.set_state = Mock()
    pet._apply_reliability_event = Mock()
    return pet


def _state(pet):
    return (pet.sick, pet.injury, pet.sick_total, pet.injury_total)


class SicknessImmunity(unittest.TestCase):
    CLASSES = (GamePet, AndroidPetRules)

    def test_no_heal_doses_means_immune(self):
        for cls in self.CLASSES:
            for kind in ("sick", "injury"):
                with self.subTest(cls=cls.__name__, kind=kind):
                    pet = _pet(cls, heal_doses=0)
                    self.assertFalse(pet.add_ailment(kind))
                    self.assertEqual(_state(pet), (0, 0, 0, 0))
                    pet.set_state.assert_not_called()
                    pet._apply_reliability_event.assert_not_called()

    def test_heal_doses_make_it_sick_or_injured(self):
        for cls in self.CLASSES:
            with self.subTest(cls=cls.__name__):
                pet = _pet(cls, heal_doses=2)
                self.assertTrue(pet.add_ailment("injury"))
                self.assertEqual(_state(pet), (0, 2, 0, 1))
                pet.set_state.assert_called_once_with("sick")
                pet = _pet(cls, heal_doses=2)
                self.assertTrue(pet.add_ailment("sick"))
                self.assertEqual(_state(pet), (2, 0, 1, 0))

    def test_one_ailment_at_a_time(self):
        """A sick pet is not injured on top, nor the other way round."""
        for cls in self.CLASSES:
            with self.subTest(cls=cls.__name__):
                pet = _pet(cls, sick=1, sick_total=3)
                self.assertFalse(pet.add_ailment("sick"))
                self.assertFalse(pet.add_ailment("injury"))
                self.assertEqual(_state(pet), (1, 0, 3, 0))
                pet = _pet(cls, injury=1, injury_total=2)
                self.assertFalse(pet.add_ailment("sick"))
                self.assertEqual(_state(pet), (0, 1, 0, 2))


if __name__ == "__main__":
    unittest.main()
