# -*- coding: utf-8 -*-
"""ICX-10: the Digivice iC's care and battle rules, on the real IC module.

Rules protected (modules/IC/module.json, read by models.game_module and run
by models.game_pet / battle.game_battle):

    care_meat_care_mistake_time 3       a hunger call becomes a care mistake on its third minute
    care_sleep_care_mistake_timer 3     the lights left on at bedtime: a care mistake after three minutes
    care_poop_sickness_count 6, Dots    six poops on screen make a lone pet sick, with Dots
    care_disturbance_sickness_count 10  every tenth sleep disturbance makes it sick, with Dots
    care_99g_effect Dots                reaching 99G is a Dots sickness (once until it drops below 90)
    care_flush_disturbance_sleep        flushing wakes a sleeping pet (a disturbance)
    visible_stats without Strength      no Strength meter: no call, mistake or drain, protein refused
    battle_global_hit_points 16         every fighter has 16 HP whatever its species
    battle_cost_type Hunger, 1          a battle costs a heart of hunger; none, no battle
    battle_weight_loss 4                a battle sheds 4G down to the minimum weight
    death_save_by_b_press 60            a dying pet is saved by 60 B presses within the minute
    death_max_injuries 30 / death_sick_timer 360   what makes it dying

The B presses themselves go through the main scene in
tests/game/ic/test_ic_care_in_game.py. Checklist: ICX-10 (release-1.0.md).
"""
import json
import os
import sys
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ic_fixtures import HAVE_IC, MODULES, ICCase  # noqa: E402


class ModuleDataTests(unittest.TestCase):
    @unittest.skipUnless(HAVE_IC, "modules/ is gitignored")
    def test_the_ic_declares_its_rules(self):
        data = json.load(open(os.path.join(MODULES, "IC", "module.json"), encoding="utf-8"))
        expected = dict(
            death_save_by_b_press=60, death_save_by_shake=0, death_max_injuries=30, death_sick_timer=360,
            care_meat_care_mistake_time=3, care_sleep_care_mistake_timer=3,
            care_poop_sickness_count=6, care_poop_sickness_effect="Dots",
            care_disturbance_sickness_count=10, care_disturbance_sickness_effect="Dots",
            care_99g_effect="Dots", care_flush_disturbance_sleep=True,
            care_block_actions_when_sleeping=False,
            battle_global_hit_points=16, battle_cost_type="Hunger", battle_cost_amount=1,
            battle_weight_loss=4, battle_protocol="IC", care_can_battle_while_sick=False)
        self.assertEqual({k: data.get(k) for k in expected}, expected)
        self.assertNotIn("Strength", [s.strip() for s in data["visible_stats"].split(",")])


class LoaderTests(ICCase):
    def test_the_loader_reads_them(self):
        ic = self.ic
        self.assertEqual(
            (ic.death_save_by_b_press, ic.meat_care_mistake_time, ic.sleep_care_mistake_timer,
             ic.care_poop_sickness_count, ic.care_poop_sickness_effect,
             ic.care_disturbance_sickness_count, ic.care_disturbance_sickness_effect,
             ic.care_99g_effect, ic.care_flush_disturbance_sleep, ic.battle_global_hit_points,
             ic.battle_cost_type, ic.battle_cost_amount, ic.back_to_sleep_time),
            (60, 3, 3, 6, "Dots", 10, "Dots", "Dots", True, 16, "Hunger", 1.0, 10))
        self.assertIn("Reliability", ic.visible_stats)
        self.assertNotIn("Strength", ic.visible_stats)


class CareMistakeTests(ICCase):
    def test_a_hunger_call_is_a_mistake_on_its_third_minute(self):
        pet = self.pet(hunger=0, _cd_hunger=9999)
        self.tick(pet, 2)
        self.assertEqual(pet.mistakes, 0)
        self.assertTrue(pet.call_sign())
        self.assertNotIn("alarm", [c.args[0] for c in self.sound.play.call_args_list])
        self.tick(pet)
        self.assertEqual(pet.mistakes, 1)
        self.assertFalse(pet.call_sign(), "the call is over")
        self.sound.play.assert_any_call("alarm")

    def test_lights_on_at_bedtime_are_a_mistake_after_three_minutes(self):
        pet = self.pet(_test_bedtime=True)
        self.tick(pet, 2)
        self.assertEqual(pet.mistakes, 0)
        self.assertTrue(pet.call_sign())
        self.tick(pet)
        self.assertEqual(pet.mistakes, 1)

    def test_lights_off_in_time_is_no_mistake(self):
        pet = self.pet(_test_bedtime=True)
        self.tick(pet, 2)
        pet.answer_call("sleep")
        pet.set_state("nap")
        pet.nap_until = datetime.now() + timedelta(days=1)    # never the wake minute
        self.tick(pet, 10)
        self.assertEqual((pet.state, pet.mistakes), ("nap", 0))


class SicknessRuleTests(ICCase):
    def poops(self, n):
        from models.game_poop import GamePoop
        self.gg.poop_list[:] = [GamePoop(10 * i, 100) for i in range(n)]

    def test_six_poops_make_a_lone_pet_sick_with_dots(self):
        pet = self.pet()
        self.poops(5)
        self.tick(pet)
        self.assertEqual(pet.sick, 0, "five are not enough")
        self.poops(6)
        self.tick(pet)
        self.assertGreater(pet.sick, 0)
        self.assertEqual((pet.sick_type, pet.injuries), ("dots", 1))

    def test_every_tenth_disturbance_makes_it_sick_with_dots(self):
        pet = self.pet()
        for n in range(1, 11):
            pet.set_state("nap")
            pet.check_disturbed_sleep()
            self.assertEqual(pet.sick > 0, n == 10, f"disturbance {n}")
        self.assertEqual((pet.sleep_disturbances, pet.sick_type), (10, "dots"))
        self.assertEqual(pet.back_to_sleep, 10, "care_back_to_sleep_time")

    def test_99g_is_dots_once_until_it_drops_below_90(self):
        pet = self.pet(weight=95)
        pet.add_weight(10)
        self.assertEqual((pet.weight, pet.sick > 0, pet.sick_type), (99, True, "dots"))
        pet.sick = 0
        pet.add_weight(1)
        self.assertEqual(pet.sick, 0, "still 99: not again")
        pet.weight = 89
        pet.update_99g_effect()
        pet.add_weight(10)
        self.assertGreater(pet.sick, 0, "after dropping below 90 it can happen again")

    def test_a_flush_wakes_a_sleeping_pet(self):
        import pygame
        from scenes.scene_maingame import SceneMainGame
        pet = self.pet(_test_bedtime=True)
        pet.set_state("nap")
        self.poops(1)
        cleaning = SimpleNamespace(cleaning=True, cleaning_x=-1000, cleaning_speed=1)
        with patch.object(self.rg, "misc_sprites", {"Wash": pygame.Surface((8, 8))}):
            SceneMainGame.update_cleaning(cleaning)
        self.assertNotEqual(pet.state, "nap")
        self.assertEqual((pet.sleep_disturbances, pet.back_to_sleep), (1, 10))


class NoStrengthMeterTests(ICCase):
    def test_strength_zero_is_never_a_need(self):
        pet = self.pet(strength=0, _cd_strength=1)
        self.assertFalse(pet.tracks_strength())
        self.assertFalse(pet.need_care())
        self.assertFalse(pet.call_sign())
        self.tick(pet, 30)
        self.assertEqual((pet.strength, pet.mistakes), (0, 0))

    def test_protein_is_refused(self):
        pet = self.pet(strength=0)
        self.assertFalse(pet.set_eating("strength", 1))
        self.assertEqual((pet.strength, pet.state), (0, "nope"))


class BattleRuleTests(ICCase):
    def test_every_fighter_has_16_hit_points(self):
        from battle.game_battle import GameBattle
        agumon, gaomon = self.pet(), self.pet(name="Gaomon")
        enemy = SimpleNamespace(hp=3, stage=3)          # an adventure enemy: no get_hp
        battle = GameBattle([agumon, gaomon], [enemy, enemy], 0, 0, self.ic)
        self.assertEqual((battle.team1_hp, battle.team2_hp), ([16, 16], [16, 16]))
        boosted = GameBattle([agumon], [enemy], 2, 0, self.ic)
        self.assertEqual((boosted.team1_hp, boosted.team2_hp), ([18], [16]),
                         "an HP item adds to the pet only")

    def test_a_battle_costs_a_heart_of_hunger_and_4g(self):
        pet = self.pet(hunger=1, weight=17)
        self.assertTrue(pet._has_battle_resources())
        dp = pet.dp
        with patch("models.game_pet.random.random", return_value=0.99):
            pet.finish_battle(True, SimpleNamespace(stage=3, name="Agumon", version=1), 1)
        self.assertEqual((pet.hunger, pet.dp, pet.weight), (0, dp, 15), "Agumon's minimum is 15G")
        self.assertFalse(pet._has_battle_resources())
        self.assertEqual(pet.battle_block_reason(), "hungry")

    def test_a_sick_pet_cannot_start_a_battle(self):
        pet = self.pet()
        self.assertIsNone(pet.battle_block_reason())
        pet.set_sick("dots")
        self.assertTrue(pet.battle_block_reason().startswith("sick"))


class DeathSaveTests(ICCase):
    def dying(self, **fields):
        pet = self.pet(**fields)
        self.tick(pet)
        self.assertTrue(pet.dying)
        self.assertEqual((pet.state, pet.death_save_b_counter), ("dying", 60))
        self.sound.play.assert_any_call("death")
        return pet

    def test_thirty_injuries_call_for_60_presses(self):
        pet = self.dying(injuries=30)
        self.assertEqual(pet.death_cause, "injuries")

    def test_sixty_presses_within_the_minute_save_it(self):
        pet = self.dying(injuries=30)
        pet.death_save_b_counter -= 60               # the main scene's B handler
        self.tick(pet)
        self.assertFalse(pet.dying)
        self.assertEqual((pet.state, pet.injuries, pet.death_save_immunity), ("happy2", 29, 59))
        self.sound.play.assert_any_call("happy")

    def test_fifty_nine_are_not_enough(self):
        pet = self.dying(injuries=30)
        pet.death_save_b_counter -= 59
        self.tick(pet)
        self.assertEqual(pet.state, "dead")

    def test_six_hours_sick_and_saved_is_cured(self):
        pet = self.pet()
        pet.set_sick("dots")
        pet.care_sick_mistake_timer = 360
        self.tick(pet)
        self.assertTrue(pet.dying)
        self.assertEqual(pet.death_cause, "sickness")
        pet.death_save_b_counter = 0
        self.tick(pet)
        self.assertEqual((pet.dying, pet.sick, pet.care_sick_mistake_timer), (False, 0, 0))

    def test_the_hour_of_immunity_runs_down(self):
        pet = self.dying(injuries=30)
        pet.death_save_b_counter = 0
        self.tick(pet)
        self.tick(pet, 59)
        self.assertEqual(pet.death_save_immunity, 0)
        self.assertNotEqual(pet.state, "dead")


if __name__ == "__main__":
    unittest.main()
