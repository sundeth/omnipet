# -*- coding: utf-8 -*-
"""Round 1 of every adventure area of every release module fights to a result.

Checklist BAT-03 and BAT-04 (adventure), and the battle contract in
CLAUDE.md: an adventure battle is OMNIPET's, fought on the MODULE's rules.
For each release module with ``adventure_mode`` (DW1 left out while it is
being built) and each of its adventure areas, a Child of the module's own
roster fights the area's first round headless, on the fake clock, mashing
the module's own charge minigame, until the result has been dealt with
(the scene asks for the main game, or a sequential module moves on to its
next round). Every round must:

* load real enemies (no empty slot in the enemy team);
* be simulated once, by GlobalBattleSimulator, with the module's
  ``battle_protocol`` as the pattern table and its damage limit, attribute
  advantage and hit-rate ceiling (module-based patterns, not a wire's);
* play the module's ``battle_minigame`` (a "None" module fights at the flat
  charge 2) and, where the module sets ``battle_global_hit_points``, start
  the pet on that HP;
* end in Victory or Defeat with no exception and no error logged;
* charge the module's ``battle_cost_type`` exactly once;
* pay experience only on a win, and on a loss send the player back to
  round 1 of the module.

The outcome is the battle's own (seeded); test_adventure_rewards.py settles
it to check the rewards on each side. Each module is its own test method so
one module's failure does not hide another's.
"""
import os
import sys
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import battle_flow as bf  # noqa: E402

MODULE_NAMES = bf.adventure_modules() if os.path.isdir(bf.MODULES) else []


@unittest.skipUnless(MODULE_NAMES, "modules folder not present")
class EveryAdventureArea(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness import Env
        cls.env = Env("240x240")

    def sweep(self, module_name):
        from battle.battle_encounter import BattleEncounter
        import battle.battle_encounter as encounter_module
        from harness import quiet
        from utils.module_utils import get_module
        env = self.env
        module = get_module(module_name)
        areas = sorted(module.get_area_round_counts())
        self.assertTrue(areas, f"{module_name} has adventure_mode but no adventure area")
        recorder = bf.RecordingSimulator()
        cost_type = getattr(module, "battle_cost_type", "DP")
        cost = getattr(module, "battle_cost_amount", 1.0)
        global_hp = getattr(module, "battle_global_hit_points", 0)
        with patch.object(encounter_module, "GlobalBattleSimulator", recorder.cls):
            for area in areas:
                with self.subTest(module=module_name, area=area):
                    bf.fresh(env, seed=area)
                    # The record is given by hand: a fresh pet of a module
                    # that keeps its battle counts has none (BAT-F1).
                    pet = bf.ensure_battle_record(bf.battle_pet(module_name))
                    bf.set_party(env, [pet])
                    gg = env.gg
                    before = (pet.battles, pet.win, pet.dp, pet.hunger)
                    calls = len(recorder.calls)
                    logs = len(env.logs)
                    with quiet():
                        encounter = BattleEncounter(module_name, area, 1, 1)
                    enemies = list(encounter.battle_player.team2)
                    self.assertTrue(enemies, "no enemy loaded")
                    self.assertNotIn(None, enemies, "an enemy slot is empty")
                    if global_hp > 0:
                        self.assertEqual(encounter.battle_player.team1_max_hp[:1], [global_hp],
                                         "the pet does not start on the module's global HP")

                    result = bf.run_round(env, encounter, draw_every=5)

                    self.assertIn(result["victory"], ("Victory", "Defeat"),
                                  f"no verdict after {result['frames']} frames: {result['phases']}")
                    self.assertNotEqual(result["outcome"], "timeout", result["phases"])
                    self.assertEqual(bf.battle_errors(env, logs), [])

                    # One simulation, on the module's own rules.
                    self.assertEqual(len(recorder.calls) - calls, 1)
                    call = recorder.calls[-1]
                    self.assertEqual(call.get("battle_format"), getattr(module, "battle_protocol", None))
                    self.assertFalse(call.get("pvp_mode"))
                    self.assertEqual(call.get("damage_limit"), module.battle_damage_limit)
                    self.assertEqual(call.get("attribute_advantage"), module.battle_attribute_advantage)
                    self.assertEqual(call.get("max_hit_rate"), getattr(module, "battle_max_hit_rate", 100))

                    # The module's charge was the one played.
                    minigame = getattr(module, "battle_minigame", "Dummy Bar")
                    if minigame == "None":
                        self.assertEqual(result["snapshot"]["strength"], 2)
                    else:
                        self.assertIsNotNone(result["charge"], f"no {minigame} charge was played")

                    # Fought once, paid for once.
                    battles, wins, dp, hunger = before
                    self.assertEqual(pet.battles, battles + 1)
                    if cost_type == "DP":
                        self.assertEqual((pet.dp, pet.hunger), (max(0, dp - cost), hunger))
                    elif cost_type == "Hunger":
                        self.assertEqual((pet.dp, pet.hunger), (dp, max(0, hunger - cost)))
                    else:
                        self.assertEqual((pet.dp, pet.hunger), (dp, hunger))

                    snapshot = result["snapshot"]
                    if result["victory"] == "Victory":
                        self.assertEqual(pet.win, wins + 1)
                        self.assertGreater(snapshot["xp"], 0, "a win paid no experience")
                    else:
                        self.assertEqual(pet.win, wins)
                        self.assertEqual(snapshot["xp"], 0, "a loss paid experience")
                        self.assertEqual(result["outcome"], "scene", "a loss did not end the run")
                        self.assertEqual(gg.battle_round.get(module_name), 1,
                                         "a loss did not send the player back to round 1")


def _sweep_test(name):
    def test(self):
        self.sweep(name)
    test.__doc__ = f"{name}: round 1 of every adventure area fights to a result on the module's rules."
    return test


for _name in MODULE_NAMES:
    setattr(EveryAdventureArea, f"test_{bf.method_name(_name)}", _sweep_test(_name))


if __name__ == "__main__":
    unittest.main()
