"""The lifespan rule (owner, 2026-10-21: "we need a combo like we do for
traited eggs"). A module names how a pet's life ends (`lifespan_rule`):

    None           it lives on (most modules; DMM, XWM and TWIN by name)
    Activity Time  the iC: a form that cannot evolve two hours after its
                   evolution time, or at 144 hours without one, goes
                   near-death through the module's death save
    Old Age        DW1: dies `death_old_age` days into its life, unsaveable
    Age 5          DMXW: from 5 days old Hunger and poop twice as fast, and
                   16 care mistakes in one form kill

`life_minutes` is the pet's own clock (asleep and awake, not while dead,
frozen or closed); old saves start it at their age in days. Checked on the
shared rules (utils.lifespan_rules), the loader, GamePet and its Android
copy, and every module.json. The Android day-parity fields are in
tests/unit/android/android_parity.py.
"""

import glob
import json
import os
import random
import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SRC = os.path.join(REPO_ROOT, "src")
MODULES = os.path.join(REPO_ROOT, "modules")
for path in (SRC, REPO_ROOT, os.path.join(REPO_ROOT, "tests", "unit", "android")):
    if path not in sys.path:
        sys.path.insert(0, path)

from core import runtime_globals  # noqa: E402
from models.game_module import GameModule  # noqa: E402
from models.game_pet import GamePet  # noqa: E402
from services.android_offline import OfflineWorld  # noqa: E402
from utils import lifespan_rules  # noqa: E402
from test_android_offline import module, pet, snapshot, species  # noqa: E402

DAY = 24 * 60
#: The iC's save: 60 presses in 30 seconds, then 5%.
IC_SAVE = dict(death_save_by="B Press", death_save_amount=60, death_save_seconds=30,
               death_save_chance=5)


def form(**fields):
    data = dict(stage=4, time=3000, _evol_minutes=0, life_minutes=0, mistakes=0)
    data.update(fields)
    return SimpleNamespace(**data)


class Rules(unittest.TestCase):
    def test_an_unknown_or_missing_rule_is_none(self):
        for mod in (SimpleNamespace(), SimpleNamespace(lifespan_rule="Forever"),
                    SimpleNamespace(lifespan_rule=None)):
            self.assertEqual(lifespan_rules.rule(mod), "None")

    def test_none_never_kills(self):
        mod = SimpleNamespace(lifespan_rule="None", death_old_age=1)
        self.assertEqual(lifespan_rules.death_cause(
            form(_evol_minutes=99999, life_minutes=99999, mistakes=99), mod, lambda: False), "")

    def test_activity_time_two_hours_past_the_evolution_time(self):
        self.assertEqual(lifespan_rules.activity_deadline(form(time=3000)), 3120)
        # The Ultimates have no evolution time: 144 hours.
        self.assertEqual(lifespan_rules.activity_deadline(form(time=0)), 144 * 60)

    def test_activity_time_kills_only_a_pet_that_cannot_evolve(self):
        mod = SimpleNamespace(lifespan_rule="Activity Time")
        asked = Mock(return_value=False)
        self.assertEqual(lifespan_rules.death_cause(form(_evol_minutes=3119), mod, asked), "")
        asked.assert_not_called()  # the routes are read only once the time is up
        self.assertEqual(lifespan_rules.death_cause(form(_evol_minutes=3120), mod, asked), "lifespan")
        self.assertEqual(lifespan_rules.death_cause(form(_evol_minutes=3120), mod, lambda: True), "")
        self.assertEqual(lifespan_rules.death_cause(form(stage=0, _evol_minutes=9999), mod, asked), "")

    def test_old_age_on_the_pets_own_clock(self):
        mod = SimpleNamespace(lifespan_rule="Old Age", death_old_age=15)
        self.assertEqual(lifespan_rules.death_cause(form(life_minutes=15 * DAY - 1), mod, None), "")
        self.assertEqual(lifespan_rules.death_cause(form(life_minutes=15 * DAY), mod, None), "old_age")
        mod.death_old_age = 0
        self.assertEqual(lifespan_rules.death_cause(form(life_minutes=99 * DAY), mod, None), "")

    def test_age_5(self):
        mod = SimpleNamespace(lifespan_rule="Age 5")
        young, old = 5 * DAY - 1, 5 * DAY
        self.assertEqual(lifespan_rules.death_cause(form(life_minutes=young, mistakes=16), mod, None), "")
        self.assertEqual(lifespan_rules.death_cause(form(life_minutes=old, mistakes=15), mod, None), "")
        self.assertEqual(lifespan_rules.death_cause(form(life_minutes=old, mistakes=16), mod, None),
                         "care_mistakes")
        self.assertEqual(lifespan_rules.needs_factor(form(life_minutes=young), mod), 1)
        self.assertEqual(lifespan_rules.needs_factor(form(life_minutes=old), mod), 2)
        self.assertEqual(lifespan_rules.needs_factor(form(life_minutes=old),
                                                     SimpleNamespace(lifespan_rule="Old Age")), 1)


class Loader(unittest.TestCase):
    """GameModule reads lifespan_rule; a module from before names only
    death_old_age, which was Old Age."""

    def load(self, **fields):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        with open(os.path.join(REPO_ROOT, "assets", "Tutorial", "module.json"), encoding="utf-8-sig") as f:
            data = json.load(f)
        data.pop("lifespan_rule", None)
        data.update(fields)
        with open(os.path.join(folder, "module.json"), "w", encoding="utf-8") as f:
            json.dump(data, f)
        mod = GameModule.__new__(GameModule)
        mod.folder_path = folder
        mod.load_module_data()
        return mod

    def test_the_rule(self):
        self.assertEqual(self.load(lifespan_rule="Activity Time").lifespan_rule, "Activity Time")

    def test_a_module_from_before(self):
        self.assertEqual(self.load(death_old_age=15).lifespan_rule, "Old Age")
        self.assertEqual(self.load(death_old_age=0).lifespan_rule, "None")


class Quiet(unittest.TestCase):
    def setUp(self):
        for target in ("game_console", "game_sound"):
            p = patch.object(runtime_globals, target, SimpleNamespace(log=lambda *_: None,
                                                                     play=lambda *_: None))
            p.start()
            self.addCleanup(p.stop)

    def check(self, mod, p):
        with patch("models.game_pet.get_module", return_value=mod), \
                patch.object(GamePet, "set_state", lambda self, state: setattr(self, "state", state)):
            return p.check_death_conditions()


class ActivityTime(Quiet):
    ADULT = species("Adult", stage=4, time=9999)

    def mod(self, **fields):
        return module(lifespan_rule="Activity Time", get_monster=lambda *_: self.ADULT,
                      **dict(IC_SAVE, **fields))

    def test_a_pet_that_cannot_evolve_goes_near_death(self):
        mod = self.mod()
        p = pet(mod, time=100, _evol_minutes=220, evolve=[])
        self.assertFalse(self.check(mod, p))
        self.assertTrue(p.dying)
        self.assertEqual((p.death_cause, p.death_save_b_counter), ("lifespan", 60))

    def test_not_while_a_route_is_met(self):
        mod = self.mod()
        p = pet(mod, time=100, _evol_minutes=220, evolve=[{"to": "Adult", "chance": 1}])
        self.assertFalse(self.check(mod, p))
        self.assertFalse(p.dying)
        # A failed evolution never comes, so it is near death after all.
        p.evolution_failed = True
        self.check(mod, p)
        self.assertTrue(p.dying)

    def test_saved_it_has_the_hour_then_is_near_death_again(self):
        mod = self.mod()
        p = pet(mod, time=100, _evol_minutes=220, evolve=[])
        self.check(mod, p)
        with patch.object(GamePet, "set_state", lambda self, state: setattr(self, "state", state)):
            p._death_saved()
        self.assertEqual((p.dying, p.death_save_immunity, p._evol_minutes), (False, 60, 220))
        self.check(mod, p)
        self.assertFalse(p.dying)
        p.death_save_immunity = 0
        self.check(mod, p)
        self.assertTrue(p.dying)

    def test_offline_nobody_presses(self):
        """The Android copy: past the deadline the save starts, and with the
        app closed its 30 seconds run out at the next minute."""
        mod = self.mod()
        state = snapshot([pet(mod, time=1, evolve=[])])
        world = OfflineWorld(state, {"Test": mod}).advance(state["at"] + 120 * 60)
        self.assertFalse(world.pet_list[0].dying)
        world.advance(state["at"] + 121 * 60)
        self.assertEqual((world.pet_list[0].dying, world.pet_list[0].death_cause), (True, "lifespan"))
        world.advance(state["at"] + 122 * 60)
        self.assertEqual(world.pet_list[0].state, "dead")

    def test_the_android_check_draws_no_number(self):
        """Its preview counts a chance as met without rolling, as GamePet's,
        so the offline random stream stays the foreground's."""
        mod = self.mod()
        state = snapshot([pet(mod)])
        world = OfflineWorld(state, {"Test": mod})
        android = world.pet_list[0]
        android.evolve = [{"to": "Adult", "chance": 1}]
        before = world.rng.getstate()
        self.assertTrue(android.can_evolve())
        self.assertEqual(world.rng.getstate(), before)
        android.evolve = []
        self.assertFalse(android.can_evolve())


class OldAge(Quiet):
    def test_dies_unsaved_on_its_own_clock(self):
        mod = module(lifespan_rule="Old Age", death_old_age=15, **IC_SAVE)
        p = pet(mod, age=30, life_minutes=15 * DAY - 1)
        self.assertFalse(self.check(mod, p))   # 30 calendar days do not count
        p.life_minutes += 1
        self.assertTrue(self.check(mod, p))
        self.assertFalse(p.dying)              # no save

    def test_the_clock_runs_asleep_and_awake_offline(self):
        mod = module()
        p = pet(mod, sleeps="00:00", wakes="23:59", life_minutes=7)
        state = snapshot([p])
        world = OfflineWorld(state, {"Test": mod}).advance(state["at"] + 180)
        self.assertEqual(world.pet_list[0].life_minutes, 10)

    def test_an_old_save_keeps_its_days(self):
        mod = module()
        p = pet(mod, age=3)
        del p.life_minutes
        with patch("models.game_pet.get_module", return_value=mod):
            p.patch()
        self.assertEqual(p.life_minutes, 3 * DAY)


class Age5(Quiet):
    def test_hunger_and_poop_twice_as_fast_from_age_5(self):
        mod = module(lifespan_rule="Age 5", visible_stats=["Strength"])
        for life, hunger, poop in ((5 * DAY - 1, 9, 9), (5 * DAY, 8, 8)):
            with self.subTest(life=life):
                p = pet(mod, life_minutes=life, _cd_hunger=10, _cd_strength=10, _cd_poop=10)
                with patch("models.game_pet.get_module", return_value=mod), \
                        patch.object(GamePet, "should_sleep", return_value=False):
                    p.update_needs(1)
                    p.update_pooping(1)
                # Strength is not named by the manual.
                self.assertEqual((p._cd_hunger, p._cd_strength, p._cd_poop), (hunger, 9, poop))

    def test_the_android_copy_agrees(self):
        mod = module(lifespan_rule="Age 5", visible_stats=["Strength"])
        p = pet(mod, life_minutes=5 * DAY, _cd_hunger=10, _cd_strength=10, _cd_poop=10,
                sleeps="23:59", wakes="00:00")
        state = snapshot([p], at=datetime(2026, 9, 12, 12).timestamp())
        world = OfflineWorld(state, {"Test": mod}).advance(state["at"] + 60)
        android = world.pet_list[0]
        self.assertEqual((android._cd_hunger, android._cd_strength, android._cd_poop), (8, 9, 8))

    def test_sixteen_mistakes_in_a_form_through_the_save(self):
        mod = module(lifespan_rule="Age 5", **IC_SAVE)
        p = pet(mod, life_minutes=5 * DAY, mistakes=16)
        self.assertFalse(self.check(mod, p))
        self.assertEqual((p.dying, p.death_cause), (True, "care_mistakes"))


class EvolutionWindow(Quiet):
    """Evolution Window (Stage IV+ the Pendulum Z, Stage V+ the Digital
    Monster X): from that stage the evolution time is the only try; no route
    met then, the form has failed for good (jogress still works)."""
    LEVEL = {"to": "Adult", "level": [5, 10]}

    def test_the_rule_names_its_first_stage(self):
        for rule, stage, closes in (("Evolution Window (Stage IV+)", 4, True),
                                    ("Evolution Window (Stage IV+)", 3, False),
                                    ("Evolution Window (Stage V+)", 4, False),
                                    ("Evolution Window (Stage V+)", 6, True),
                                    ("None", 6, False)):
            with self.subTest(rule=rule, stage=stage):
                pet_ = SimpleNamespace(stage=stage, evolve=[self.LEVEL])
                self.assertEqual(lifespan_rules.closes_evolution(pet_, SimpleNamespace(lifespan_rule=rule)), closes)

    def test_a_last_form_has_nothing_to_fail(self):
        mod = SimpleNamespace(lifespan_rule="Evolution Window (Stage V+)")
        for routes in ([], [{"to": "Omnimon", "jogress": "MetalGarurumon"}], [{"to": "X", "item": "Chip"}]):
            with self.subTest(routes=routes):
                self.assertFalse(lifespan_rules.closes_evolution(SimpleNamespace(stage=7, evolve=routes), mod))

    def check(self, rule, stage, found=None):
        mod = module(lifespan_rule=rule, failed_evolution_double_needs=True)
        p = pet(mod, stage=stage, _evol_minutes=10, time=5, evolve=[self.LEVEL])
        tried = []
        with patch("models.game_pet.get_module", return_value=mod),                 patch.object(GamePet, "need_care", return_value=False),                 patch.object(GamePet, "find_evolution", side_effect=lambda *a, **k: tried.append(1) or found):
            p.update_evolution()
            p.update_evolution()
        return p.evolution_failed, len(tried)

    def test_the_timer_is_the_only_try(self):
        self.assertEqual(self.check("Evolution Window (Stage IV+)", 4), (True, 1))
        self.assertEqual(self.check("Evolution Window (Stage V+)", 5), (True, 1))

    def test_earlier_stages_keep_waiting(self):
        self.assertEqual(self.check("Evolution Window (Stage V+)", 4), (False, 2))
        self.assertEqual(self.check("None", 5), (False, 2))

    def test_the_android_copy_agrees(self):
        from services.android_pet_rules import AndroidPetRules
        mod = SimpleNamespace(lifespan_rule="Evolution Window (Stage IV+)")
        p = AndroidPetRules.__new__(AndroidPetRules)
        p.name, p.module, p.stage, p.evolve = "Agumon", "TEST", 4, [self.LEVEL]
        p._evol_minutes, p.time, p.evolution_failed = 10, 5, False
        p.world = SimpleNamespace(log=Mock(), get_module=lambda _name: mod)
        p.need_care = lambda: False
        p.find_evolution = Mock(return_value=None)
        p.update_evolution()
        p.update_evolution()
        self.assertTrue(p.evolution_failed)
        self.assertEqual(p.find_evolution.call_count, 1)


def _module_files():
    files = sorted(glob.glob(os.path.join(MODULES, "*", "module.json")))
    return files + [os.path.join(REPO_ROOT, "assets", "Tutorial", "module.json")]


@unittest.skipUnless(os.path.isdir(MODULES), "modules/ is gitignored")
class ModuleData(unittest.TestCase):
    #: The owner's rules (lifespan_rule_20261021.py); every other module None.
    RULES = {"IC": "Activity Time", "DW1": "Old Age", "DMXW": "Age 5",
             "DMX": "Evolution Window (Stage V+)", "PENZ": "Evolution Window (Stage IV+)"}

    def test_every_module_names_its_rule(self):
        for path in _module_files():
            name = os.path.basename(os.path.dirname(path))
            with self.subTest(module=name):
                with open(path, encoding="utf-8-sig") as f:
                    data = json.load(f)
                self.assertEqual(data["lifespan_rule"], self.RULES.get(name, "None"))
                # Old Age's days, and only Old Age's.
                self.assertEqual(data.get("death_old_age", 0) > 0, data["lifespan_rule"] == "Old Age")


if __name__ == "__main__":
    unittest.main()
