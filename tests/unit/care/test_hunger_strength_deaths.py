# -*- coding: utf-8 -*-
"""Hunger and Strength deaths as each device's manual gives them (decision 17).

Owner, 2026-10-17: the VB modules have no such death; the others follow their
manuals, and a module whose guide says nothing takes the rule of the one it is
built on. The humulos manuals:

    DMC (DMGZ, DMH)  hearts empty 12 consecutive hours in one form     720 min
    DMOG             hearts empty 6 consecutive hours                  360 min
    PENC, PENGZ      the hunger meter empties 20 times without refilling it
    DMXW             18 in a row for Hunger (Starvation) and for Strength
                     (Debilitation), refilling the meter completely resets it
    DMX, PEN20, PENZ, PENOG, VB, VBE, VH   none

The empty minutes used to be read off the call timers, which stop at the
care mistake (10 minutes), so the timed deaths never came; they are counted
apart now (`hunger_empty_minutes`, awake minutes, paused asleep).
utilities/claude/death_rules_from_manuals_20261017.py set the modules.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "ic"))
from ic_fixtures import ICCase, MODULES  # noqa: E402

NAMES = ("IC", "DMC", "DMOG", "DMXW", "PENC", "VB", "DMX")


@unittest.skipUnless(all(os.path.exists(os.path.join(MODULES, n, "module.json")) for n in NAMES),
                     "modules/ is gitignored")
class HungerStrengthDeaths(ICCase):
    MODULE_NAMES = NAMES

    def make(self, name, **fields):
        pet = self.pet(self.modules[name], party=False, **fields)
        pet._cd_hunger = pet._cd_strength = 10 ** 6      # no drain during the test
        pet.x_range = (0, 200)
        pet.update_death_check = lambda *a, **k: None    # judged by dies_of instead
        return pet

    def dies_of(self, pet):
        """The cause the death check finds, or None. Run with a death save
        on, so the check records it as the dying call does (without one it
        only answers True, and the game clears the cause on death)."""
        from unittest.mock import patch
        module = self.modules[pet.module]
        pet.dying, pet.death_save_immunity, pet.death_cause = False, 0, ""
        with patch.object(module, "death_save_by", "B Press"),                 patch.object(module, "death_save_amount", 60):
            pet.check_death_conditions()
        cause = pet.death_cause if pet.dying else None
        pet.dying, pet.death_cause, pet.death_save_b_counter = False, "", 0
        return cause

    def test_the_modules_carry_their_manuals_rules(self):
        got = {n: (m.death_hunger_timer, m.death_strength_timer, m.death_starvation_count,
                   m.death_debilitation_count) for n, m in self.modules.items()}
        self.assertEqual(got["DMC"], (720, 720, 0, 0))
        self.assertEqual(got["DMOG"], (360, 360, 0, 0))
        self.assertEqual(got["DMXW"], (0, 0, 18, 18))
        self.assertEqual(got["PENC"], (0, 0, 20, 0))
        for none in ("VB", "DMX", "IC"):
            self.assertEqual(got[none][:2], (0, 0), none)

    def test_twelve_empty_hours_kill_a_dmc_pet(self):
        pet = self.make("DMC", hunger=0)
        self.tick(pet, 719)
        self.assertIsNone(self.dies_of(pet))
        self.tick(pet, 1)
        self.assertEqual(self.dies_of(pet), "hunger")

    def test_a_meal_starts_the_twelve_hours_again(self):
        pet = self.make("DMC", hunger=0)
        self.tick(pet, 700)
        pet.set_eating("hunger", 1)
        pet.hunger = 0
        self.tick(pet, 30)
        self.assertEqual(pet.hunger_empty_minutes, 30)
        self.assertIsNone(self.dies_of(pet))

    def test_six_empty_hours_kill_an_original_digital_monster(self):
        pet = self.make("DMOG", strength=0)
        self.tick(pet, 360)
        self.assertEqual(self.dies_of(pet), "strength")

    def test_a_vital_bracelet_does_not_starve(self):
        pet = self.make("VB", hunger=0, strength=0)
        self.tick(pet, 2000)
        self.assertNotIn(self.dies_of(pet), ("hunger", "strength"))

    def test_the_pendulum_color_dies_at_the_twentieth_empty_cycle(self):
        pet = self.make("PENC", hunger=0)
        pet.starvation_counter = 19
        self.assertIsNone(self.dies_of(pet))
        pet.starvation_counter = 20
        self.assertEqual(self.dies_of(pet), "starvation")

    def test_a_full_meter_resets_the_counters(self):
        pet = self.make("DMXW", hunger=0, strength=0)
        pet.starvation_counter = pet.debilitation_counter = 17
        for _ in range(8):
            pet.set_eating("hunger", 1)
        self.assertEqual(pet.starvation_counter, 0)
        self.assertEqual(pet.debilitation_counter, 17, "only the meter that was filled")
        for _ in range(8):
            pet.set_eating("strength", 1)
        self.assertEqual(pet.debilitation_counter, 0)

    def test_the_xros_wars_color_dies_of_debilitation_at_18(self):
        pet = self.make("DMXW", strength=0)
        pet.debilitation_counter = 18
        self.assertEqual(self.dies_of(pet), "debilitation")

    def test_an_empty_strength_drain_adds_to_debilitation(self):
        pet = self.make("DMXW", strength=0)
        pet._cd_strength = 1
        pet.strength_loss = 60
        pet.update_needs(1)
        self.assertEqual(pet.debilitation_counter, 1)


if __name__ == "__main__":
    unittest.main()
