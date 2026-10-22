"""The death save (owner, 2026-10-20): a module names how a dying pet is
saved (`death_save_by`: "B Press", "Shake" or "Nothing"), how many presses or
shakes (`death_save_amount`), the seconds to make them in
(`death_save_seconds`) and the chance it then lives (`death_save_chance`).
A module from before names a count under death_save_by_b_press or
death_save_by_shake: that method, in the old minute, always saved.

Checked on the loader (models.game_module), on GamePet and its Android copy
(services.android_pet_rules), which must agree, and on every module.json.
The iC's own save, through its module and the main scene, is in
tests/unit/ic/test_ic_care_rules.py and tests/game/ic/test_ic_care_in_game.py.
"""

import ast
import glob
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SRC = os.path.join(REPO_ROOT, "src")
MODULES = os.path.join(REPO_ROOT, "modules")
for path in (SRC, REPO_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from core import runtime_globals  # noqa: E402
from models.game_module import DEATH_SAVE_METHODS, _death_save  # noqa: E402
from models.game_pet import GamePet  # noqa: E402
from services.android_pet_rules import AndroidPetRules  # noqa: E402

LEGACY = ("death_save_by_b_press", "death_save_by_shake")


class Loader(unittest.TestCase):
    def test_the_fields(self):
        self.assertEqual(_death_save({"death_save_by": "B Press", "death_save_amount": 60,
                                      "death_save_seconds": 30, "death_save_chance": 5}),
                         ("B Press", 60, 30, 5))

    def test_a_module_from_before_keeps_its_minute(self):
        self.assertEqual(_death_save({"death_save_by_b_press": 0, "death_save_by_shake": 100}),
                         ("Shake", 100, 60, 100))
        self.assertEqual(_death_save({"death_save_by_b_press": 60, "death_save_by_shake": 0}),
                         ("B Press", 60, 60, 100))

    def test_the_new_fields_win(self):
        self.assertEqual(_death_save({"death_save_by": "Shake", "death_save_amount": 50,
                                      "death_save_by_b_press": 60}),
                         ("Shake", 50, 60, 100))

    def test_no_method_or_no_amount_is_no_save(self):
        for data in ({}, {"death_save_by_b_press": 0, "death_save_by_shake": 0},
                     {"death_save_by": "Shake", "death_save_amount": 0},
                     {"death_save_by": "Wave", "death_save_amount": 5}):
            with self.subTest(data=data):
                self.assertEqual(_death_save(data), ("Nothing", 0, 60, 100))

    def test_the_chance_is_a_percentage(self):
        base = {"death_save_by": "Shake", "death_save_amount": 1}
        self.assertEqual(_death_save(dict(base, death_save_chance=150))[3], 100)
        self.assertEqual(_death_save(dict(base, death_save_chance=-5))[3], 0)
        self.assertEqual(_death_save(dict(base, death_save_chance=0))[3], 0)


#: The iC's save: 60 presses in 30 seconds, then 5%.
IC = SimpleNamespace(death_save_by="B Press", death_save_amount=60, death_save_seconds=30,
                     death_save_chance=5)


class Pets(unittest.TestCase):
    """update_death_save on both classes: the draw is random.random() for
    GamePet and the offline world's rng for its Android copy."""
    CLASSES = (GamePet, AndroidPetRules)

    def run_save(self, cls, seconds, draw=0.99, module=IC, **fields):
        pet = cls.__new__(cls)
        pet.name, pet.module = "Testmon", "TEST"
        pet.dying = True
        pet.death_save_b_counter, pet.death_save_shake_counter = 60, 0
        pet.death_save_elapsed = 0.0
        pet.__dict__.update(fields)
        died, saved = Mock(), Mock()
        pet._death_saved = saved
        if cls is GamePet:
            pet._die = died
            with patch("models.game_pet.get_module", return_value=module), \
                    patch("models.game_pet.random.random", return_value=draw), \
                    patch.object(runtime_globals, "game_console", Mock(), create=True):
                for s in seconds:
                    pet.update_death_save(s)
        else:
            pet.die = died
            pet.world = SimpleNamespace(get_module=lambda _name: module, log=Mock(),
                                        rng=SimpleNamespace(random=lambda: draw))
            for s in seconds:
                pet.update_death_save(s)
        return pet, died, saved

    def test_thirty_seconds_and_no_more(self):
        for cls in self.CLASSES:
            with self.subTest(cls=cls.__name__):
                pet, died, saved = self.run_save(cls, [10, 19.5])
                died.assert_not_called()
                self.assertEqual(pet.death_save_elapsed, 29.5)
                pet, died, saved = self.run_save(cls, [10, 19.5, 1.5])
                # It died when the 30 seconds ran out, a second before this
                # call found it: its removal five minutes on counts from then.
                died.assert_called_once_with(late=1.0)
                saved.assert_not_called()

    def test_made_in_time_the_chance_decides(self):
        for cls in self.CLASSES:
            with self.subTest(cls=cls.__name__):
                _pet, died, saved = self.run_save(cls, [0.5], draw=0.049, death_save_b_counter=0)
                saved.assert_called_once()
                died.assert_not_called()
                _pet, died, saved = self.run_save(cls, [0.5], draw=0.05, death_save_b_counter=0)
                died.assert_called_once()
                saved.assert_not_called()

    def test_shakes_count_the_same(self):
        shake = SimpleNamespace(death_save_by="Shake", death_save_amount=50, death_save_seconds=30,
                                death_save_chance=100)
        for cls in self.CLASSES:
            with self.subTest(cls=cls.__name__):
                _pet, died, saved = self.run_save(cls, [0.5], module=shake, death_save_b_counter=0,
                                                  death_save_shake_counter=0)
                saved.assert_called_once()

    def test_a_pet_that_is_not_dying_is_left_alone(self):
        for cls in self.CLASSES:
            with self.subTest(cls=cls.__name__):
                pet, died, saved = self.run_save(cls, [60], dying=False)
                died.assert_not_called()
                saved.assert_not_called()

    def test_no_save_left_means_death(self):
        none = SimpleNamespace(death_save_by="Nothing", death_save_amount=0, death_save_seconds=60,
                               death_save_chance=100)
        for cls in self.CLASSES:
            with self.subTest(cls=cls.__name__):
                _pet, died, _saved = self.run_save(cls, [0.5], module=none)
                died.assert_called_once()


class OpenGameClock(unittest.TestCase):
    """The open game advances a save every 0.5 s from update()'s last sleep
    check. Its first step must count from the save's start, or an unsaved
    pet dies up to half a second before the Android copy's (the day
    harness, 2026-10-21)."""

    def test_the_first_step_counts_from_the_onset(self):
        pet = GamePet.__new__(GamePet)
        pet.name, pet.module, pet.state = "Testmon", "TEST", "idle"
        pet.dying, pet.death_save_immunity = False, 0
        pet._rt_last_sleep_check = 100.0

        def start(self_):
            self_.dying = True
            return False
        with patch.object(GamePet, "check_death_conditions", start):
            pet.update_death_check(now=100.4)
        self.assertEqual(pet._rt_last_sleep_check, 100.4)

    def test_an_ongoing_save_leaves_the_clock_alone(self):
        pet = GamePet.__new__(GamePet)
        pet.name, pet.module, pet.state = "Testmon", "TEST", "idle"
        pet.dying, pet.death_save_immunity = True, 0
        pet._rt_last_sleep_check = 100.0
        with patch.object(GamePet, "check_death_conditions", return_value=False):
            pet.update_death_check(now=100.4)
        self.assertEqual(pet._rt_last_sleep_check, 100.0)


def _set_data_fields(path, cls):
    """The attributes *cls*.set_data assigns on self."""
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls:
            for f in node.body:
                if isinstance(f, ast.FunctionDef) and f.name == "set_data":
                    return {n.attr for n in ast.walk(f)
                            if isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Store)
                            and isinstance(n.value, ast.Name) and n.value.id == "self"}
    raise AssertionError("%s.set_data not found" % cls)


class SetDataParity(unittest.TestCase):
    def test_an_offline_evolution_takes_every_field(self):
        """An evolution while the app is closed runs AndroidPetRules.set_data:
        whatever GamePet.set_data takes from the new form, it must take too
        (it once kept the old form's injury chance and RPM)."""
        game = _set_data_fields(os.path.join(SRC, "models", "game_pet.py"), "GamePet")
        android = _set_data_fields(os.path.join(SRC, "services", "android_pet_rules.py"),
                                   "AndroidPetRules")
        self.assertEqual(sorted(game - android), [])


def _module_files():
    files = sorted(glob.glob(os.path.join(MODULES, "*", "module.json")))
    return files + [os.path.join(REPO_ROOT, "assets", "Tutorial", "module.json")]


@unittest.skipUnless(os.path.isdir(MODULES), "modules/ is gitignored")
class ModuleData(unittest.TestCase):
    #: Where a source gives the save (death_save_fields_20261020.py).
    SOURCED = {"IC": ("B Press", 60, 30, 5), "PENPROG": ("Shake", 100, 30, 50),
               "PENGZ": ("Shake", 50, 30, 100), "PENC": ("Shake", 50, 30, 100),
               "TWIN": ("B Press", 60, 30, 100), "DMM": ("B Press", 100, 60, 100)}

    def test_every_module_names_its_save(self):
        for path in _module_files():
            name = os.path.basename(os.path.dirname(path))
            with self.subTest(module=name):
                with open(path, encoding="utf-8-sig") as f:
                    data = json.load(f)
                self.assertEqual([k for k in LEGACY if k in data], [])
                self.assertIn(data["death_save_by"], DEATH_SAVE_METHODS)
                amount, seconds, chance = (data["death_save_amount"], data["death_save_seconds"],
                                           data["death_save_chance"])
                self.assertTrue(amount >= 0 and seconds >= 1 and 0 <= chance <= 100)
                self.assertEqual(data["death_save_by"] == "Nothing", amount == 0)
                self.assertIn("injury_chance_step", data)
                if name in self.SOURCED:
                    self.assertEqual((data["death_save_by"], amount, seconds, chance), self.SOURCED[name])


if __name__ == "__main__":
    unittest.main()
