# -*- coding: utf-8 -*-
"""The Digivice iC's generations as a Traited Egg rule (owner, 2026-10-21:
"this is a form of traited egg, just with a different name").

traited_egg_rule "Generation" (modules/IC/module.json): a pet that dies at
Perfect or later always leaves an inherited Digitama, as "Stage V" does, and
it hatches a generation on (game_globals.generations, by "module@version").
From the second generation each Child or later form evolves an hour earlier
and the pet starts with a point more Reliability per generation, up to eight
(the 10X playbook; utils.evolution_rules.generation_bonus). The Android copy
grants the egg the same way.
"""
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ic_fixtures import HAVE_IC, MODULES, ICCase, record  # noqa: E402


class ModuleData(unittest.TestCase):
    @unittest.skipUnless(HAVE_IC, "modules/ is gitignored")
    def test_the_ic_uses_it(self):
        with open(os.path.join(MODULES, "IC", "module.json"), encoding="utf-8-sig") as f:
            self.assertEqual(json.load(f)["traited_egg_rule"], "Generation")


class Generations(ICCase):
    def setUp(self):
        super().setUp()
        for name, value in (("traited", []), ("generations", {})):
            p = patch.object(self.gg, name, value, create=True)
            p.start()
            self.addCleanup(p.stop)

    def test_a_perfect_leaves_the_next_generation(self):
        pet = self.pet(name="RizeGreymon", stage=5)
        pet.generation = 3
        pet.set_traited_egg()
        self.assertEqual((self.gg.traited, self.gg.generations), (["IC@1"], {"IC@1": 4}))

    def test_an_adult_leaves_nothing(self):
        self.pet(name="GeoGreymon", stage=4).set_traited_egg()
        self.assertEqual((self.gg.traited, self.gg.generations), ([], {}))

    def test_the_egg_hatches_with_its_reliability(self):
        egg = self.pet(name=None, stage=0)
        start = egg.reliability
        egg.set_generation(4)
        self.assertEqual((egg.generation, egg.reliability), (4, start + 3))
        egg.set_generation(20)
        self.assertEqual(egg.generation, 20)

    def test_child_and_later_forms_evolve_earlier(self):
        pet = self.pet(name="Koromon", stage=2)
        pet.generation = 4
        baby = record(self.ic, "Koromon", 2, 1)
        pet.set_data(dict(baby, module="IC"))
        self.assertEqual(pet.time, baby["time"], "Baby II keeps its time")
        child = record(self.ic, "Agumon", 3, 1)
        pet.set_data(dict(child, module="IC"))
        self.assertEqual(pet.time, child["time"] - 3 * 60)
        pet.generation = 30
        pet.set_data(dict(child, module="IC"))
        self.assertEqual(pet.time, child["time"] - 8 * 60, "eight hours at most")

    def test_other_rules_have_no_generations(self):
        pet = self.pet(self.dmc, stage=3, generation=5)
        child = record(self.dmc, None, 3, 1)
        pet.set_data(dict(child, module="DMC"))
        self.assertEqual(pet.time, child["time"])

    def test_the_android_copy_grants_it_too(self):
        from services.android_pet_rules import AndroidPetRules
        pet = AndroidPetRules.__new__(AndroidPetRules)
        pet.module, pet.version, pet.name, pet.stage, pet.generation = "IC", 2, "Ravemon", 6, 2
        pet.world = SimpleNamespace(traited=[], generations={}, log=Mock(),
                                    get_module=lambda name: self.ic)
        pet._grant_traited_egg()
        self.assertEqual((pet.world.traited, pet.world.generations), (["IC@2"], {"IC@2": 3}))


if __name__ == "__main__":
    unittest.main()
