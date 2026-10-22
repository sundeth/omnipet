"""Care rules a device declares: training while sick, and disturbance sickness."""

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

from models.game_pet import GamePet  # noqa: E402


def _pet(**fields):
    pet = GamePet.__new__(GamePet)
    pet.module = "Test"
    pet.name = "Testmon"
    pet.state = "idle"
    pet.stage = 3
    pet.sick = pet.injury = pet.sick_total = pet.injury_total = 0
    pet.heal_doses = 1
    pet.atk_main = 1
    pet.sleep_disturbances = 0
    pet.disturbance_penalty = 0
    pet.__dict__.update(fields)
    pet.set_state = Mock()
    pet._apply_reliability_event = Mock()
    pet._is_blocked_by_sleep = Mock(return_value=False)
    return pet


def _module(**fields):
    base = dict(care_can_train_while_sick=False, back_to_sleep_time=0,
                care_disturbance_sickness_count=0,
                care_disturbance_sickness_effect="Dots")
    base.update(fields)
    return SimpleNamespace(**base)


class TrainingWhileSickTests(unittest.TestCase):
    def can_train(self, pet, module):
        with patch("models.game_pet.get_module", return_value=module):
            return pet.can_train()

    def test_a_sick_pet_is_refused_by_default(self):
        self.assertFalse(self.can_train(_pet(sick=1), _module()))
        self.assertTrue(self.can_train(_pet(sick=0), _module()))

    def test_a_device_may_allow_it(self):
        module = _module(care_can_train_while_sick=True)
        self.assertTrue(self.can_train(_pet(sick=1), module))

    def test_the_other_refusals_still_stand(self):
        module = _module(care_can_train_while_sick=True)
        self.assertFalse(self.can_train(_pet(stage=0), module))
        self.assertFalse(self.can_train(_pet(state="dead"), module))
        self.assertFalse(self.can_train(_pet(atk_main=0), module))


class DisturbanceSicknessTests(unittest.TestCase):
    def disturb(self, module, times, **pet_fields):
        pet = _pet(state="nap", **pet_fields)
        with patch("models.game_pet.get_module", return_value=module):
            for _ in range(times):
                pet.state = "nap"
                pet.check_disturbed_sleep()
        return pet

    def test_off_by_default(self):
        pet = self.disturb(_module(), 20)
        self.assertEqual(pet.sleep_disturbances, 20)
        self.assertEqual(pet.sick, 0)

    def test_every_tenth_disturbance_makes_the_pet_sick(self):
        module = _module(care_disturbance_sickness_count=10)
        pet = self.disturb(module, 9)
        self.assertEqual(pet.sick, 0)
        pet = self.disturb(module, 10)
        # Dots: a sickness, counted as one
        self.assertEqual((pet.sick, pet.injury), (pet.heal_doses, 0))
        self.assertEqual((pet.sick_total, pet.injury_total), (1, 0))

    def test_it_lands_again_once_healed(self):
        module = _module(care_disturbance_sickness_count=10)
        pet = self.disturb(module, 10)
        pet.sick = 0          # treated
        with patch("models.game_pet.get_module", return_value=module):
            for _ in range(10):
                pet.state = "nap"
                pet.check_disturbed_sleep()
        self.assertEqual(pet.sleep_disturbances, 20)
        self.assertEqual(pet.sick, pet.heal_doses)

    def test_the_effect_is_the_devices(self):
        skull = self.disturb(_module(care_disturbance_sickness_count=2,
                                     care_disturbance_sickness_effect="Skull"), 2)
        # Skull: an injury
        self.assertEqual((skull.sick, skull.injury), (0, skull.heal_doses))
        self.assertEqual((skull.sick_total, skull.injury_total), (0, 1))
        nothing = self.disturb(_module(care_disturbance_sickness_count=2,
                                       care_disturbance_sickness_effect="Nothing"), 2)
        self.assertEqual(nothing.sick, 0)

    def test_an_awake_pet_is_not_disturbed(self):
        module = _module(care_disturbance_sickness_count=1)
        pet = _pet(state="idle")
        with patch("models.game_pet.get_module", return_value=module):
            pet.check_disturbed_sleep()
        self.assertEqual(pet.sleep_disturbances, 0)
        self.assertEqual(pet.sick, 0)


class ModuleSettingsTests(unittest.TestCase):
    def test_the_mini_declares_both(self):
        import json
        path = os.path.join(REPO_ROOT, "modules", "DMM", "module.json")
        if not os.path.exists(path):
            self.skipTest("DMM module not installed")
        module = json.load(open(path, encoding="utf-8"))
        self.assertIs(module["care_can_train_while_sick"], False)
        self.assertEqual(module["care_disturbance_sickness_count"], 10)
        self.assertEqual(module["care_disturbance_sickness_effect"], "Dots")


if __name__ == "__main__":
    unittest.main()
