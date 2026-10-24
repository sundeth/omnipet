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
    training_uses_battle_cost           a training costs the same heart; none, no training
    battle_weight_loss 4                a battle sheds 4G down to the minimum weight
    death_save_by B Press, 60, 30 s, 50% a dying pet needs 60 B presses within 30 seconds,
                                        and then lives 1 time in 2 (owner, 2026-10-23; it
                                        was the playbook's 1 in 20)
    death_max_injuries 30 / death_max_sicknesses 30 / death_sick_timer and
    death_injury_timer 360   what makes it dying (each kind counted apart)
    injury_chance_step 1                a lost battle's injury chance (the form's own, 5-25%)
                                        rises a point after each loss, falls one after each win

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
from ic_fixtures import HAVE_IC, MODULES, ICCase, record  # noqa: E402


class ModuleDataTests(unittest.TestCase):
    @unittest.skipUnless(HAVE_IC, "modules/ is gitignored")
    def test_the_ic_declares_its_rules(self):
        data = json.load(open(os.path.join(MODULES, "IC", "module.json"), encoding="utf-8"))
        expected = dict(
            death_save_by="B Press", death_save_amount=60, death_save_seconds=30, death_save_chance=50,
            injury_chance_step=1, death_max_injuries=30, death_sick_timer=360,
            care_meat_care_mistake_time=3, care_sleep_care_mistake_timer=3,
            care_poop_sickness_count=6, care_poop_sickness_effect="Dots",
            care_disturbance_sickness_count=10, care_disturbance_sickness_effect="Dots",
            care_99g_effect="Dots", care_flush_disturbance_sleep=True,
            care_block_actions_when_sleeping=False,
            battle_global_hit_points=16, battle_cost_type="Hunger", battle_cost_amount=1,
            training_uses_battle_cost=True, battle_weight_loss=4, battle_protocol="IC", care_can_battle_while_sick=False)
        self.assertEqual({k: data.get(k) for k in expected}, expected)
        self.assertNotIn("Strength", [s.strip() for s in data["visible_stats"].split(",")])


class LoaderTests(ICCase):
    def test_the_loader_reads_them(self):
        ic = self.ic
        self.assertEqual(
            ((ic.death_save_by, ic.death_save_amount, ic.death_save_seconds, ic.death_save_chance),
             ic.injury_chance_step, ic.meat_care_mistake_time, ic.sleep_care_mistake_timer,
             ic.care_poop_sickness_count, ic.care_poop_sickness_effect,
             ic.care_disturbance_sickness_count, ic.care_disturbance_sickness_effect,
             ic.care_99g_effect, ic.care_flush_disturbance_sleep, ic.battle_global_hit_points,
             ic.battle_cost_type, ic.battle_cost_amount, ic.back_to_sleep_time),
            (("B Press", 60, 30, 50), 1, 3, 3, 6, "Dots", 10, "Dots", "Dots", True, 16, "Hunger", 1.0, 10))
        self.assertIn("Reliability", ic.visible_stats)
        self.assertNotIn("Strength", ic.visible_stats)
        self.assertTrue(ic.training_uses_battle_cost)
        self.assertFalse(self.dmc.training_uses_battle_cost, "the default: training is free")


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
        self.assertEqual((pet.injury, pet.sick_total, pet.injury_total), (0, 1, 0))

    def test_every_tenth_disturbance_makes_it_sick_with_dots(self):
        pet = self.pet()
        for n in range(1, 11):
            pet.set_state("nap")
            pet.check_disturbed_sleep()
            self.assertEqual(pet.sick > 0, n == 10, f"disturbance {n}")
        self.assertEqual((pet.sleep_disturbances, pet.sick_total), (10, 1))
        self.assertEqual(pet.back_to_sleep, 10, "care_back_to_sleep_time")

    def test_99g_is_dots_once_until_it_drops_below_90(self):
        pet = self.pet(weight=95)
        pet.add_weight(10)
        self.assertEqual((pet.weight, pet.sick > 0, pet.injury), (99, True, 0))
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

    def test_a_training_costs_the_same_heart_and_no_weight(self):
        """Owner, 2026-10-17: the iC spends a hunger heart a battle or a
        training (training_uses_battle_cost); a training sheds its own weight
        (its table), not the battle's 4G."""
        pet = self.pet(hunger=2, weight=20)
        self.assertTrue(pet.can_train())
        self.assertTrue(pet.pay_training_cost())
        self.assertEqual((pet.hunger, pet.weight), (1, 20))
        pet.pay_training_cost()
        self.assertEqual(pet.hunger, 0)
        self.assertFalse(pet.can_train(), "no heart, no training")

    def test_training_stays_free_where_the_module_says_nothing(self):
        dmc = self.pet(self.dmc, name="Agumon", hunger=0, party=False)
        self.assertFalse(dmc.pay_training_cost())
        self.assertEqual(dmc.hunger, 0)
        self.assertTrue(dmc.can_train(), "a hungry DMC pet still trains")

    def test_a_sick_pet_cannot_start_a_battle(self):
        pet = self.pet()
        self.assertIsNone(pet.battle_block_reason())
        pet.add_ailment("sick")
        self.assertTrue(pet.battle_block_reason().startswith("sick"))
        pet.sick = 0
        pet.add_ailment("injury")
        self.assertTrue(pet.battle_block_reason().startswith("injury"))


class DeathSaveTests(ICCase):
    def dying(self, **fields):
        pet = self.pet(**fields)
        self.tick(pet)
        self.assertTrue(pet.dying)
        self.assertEqual((pet.state, pet.death_save_b_counter), ("dying", 60))
        self.sound.play.assert_any_call("death")
        return pet

    def roll(self, value):
        """The survival roll's draw (random.random(); under 0.5 lives)."""
        return patch("models.game_pet.random.random", return_value=value)

    def test_thirty_injuries_call_for_60_presses(self):
        pet = self.dying(injury_total=30)
        self.assertEqual(pet.death_cause, "injuries")

    def test_thirty_sicknesses_too_each_counted_apart(self):
        pet = self.dying(sick_total=30)
        self.assertEqual(pet.death_cause, "sicknesses")
        pet = self.pet(sick_total=29, injury_total=29)
        self.tick(pet)
        self.assertFalse(pet.dying, "29 and 29: neither count reached")

    def test_sixty_presses_in_time_and_the_one_in_two_save_it(self):
        pet = self.dying(injury_total=30)
        self.seconds(pet, 20)
        pet.death_save_b_counter -= 60               # the main scene's B handler
        with self.roll(0.49):
            self.seconds(pet, 1)
        self.assertFalse(pet.dying)
        self.assertEqual((pet.state, pet.injury_total, pet.death_save_immunity), ("happy2", 29, 60))
        self.sound.play.assert_any_call("happy")
        self.tick(pet)
        self.assertEqual(pet.death_save_immunity, 59)

    def test_the_presses_made_it_can_still_die(self):
        pet = self.dying(injury_total=30)
        pet.death_save_b_counter -= 60
        with self.roll(0.5):
            self.seconds(pet, 1)
        self.assertEqual(pet.state, "dead")
        self.sound.play.assert_any_call("fail")

    def test_thirty_seconds_is_all_it_gets(self):
        pet = self.dying(injury_total=30)
        self.seconds(pet, 29.5)
        self.assertTrue(pet.dying)
        self.seconds(pet, 0.5)
        self.assertEqual(pet.state, "dead")

    def test_fifty_nine_are_not_enough(self):
        pet = self.dying(injury_total=30)
        pet.death_save_b_counter -= 59
        self.seconds(pet, 30)
        self.assertEqual(pet.state, "dead")

    def test_six_hours_sick_and_saved_is_cured(self):
        pet = self.pet()
        pet.add_ailment("sick")
        pet.care_sick_mistake_timer = 360
        self.tick(pet)
        self.assertTrue(pet.dying)
        self.assertEqual(pet.death_cause, "sickness")
        pet.death_save_b_counter = 0
        with self.roll(0.0):
            self.seconds(pet, 1)
        self.assertEqual((pet.dying, pet.sick, pet.care_sick_mistake_timer), (False, 0, 0))

    def test_six_hours_injured_has_its_own_timer(self):
        pet = self.pet()
        pet.add_ailment("injury")
        pet.care_injury_mistake_timer = 360
        self.tick(pet)
        self.assertTrue(pet.dying)
        self.assertEqual(pet.death_cause, "injury")
        pet.death_save_b_counter = 0
        with self.roll(0.0):
            self.seconds(pet, 1)
        self.assertEqual((pet.dying, pet.injury, pet.care_injury_mistake_timer), (False, 0, 0))

    def test_the_hour_of_immunity_runs_down(self):
        pet = self.dying(injury_total=30)
        pet.death_save_b_counter = 0
        with self.roll(0.0):
            self.seconds(pet, 1)
        self.tick(pet, 60)
        self.assertEqual(pet.death_save_immunity, 0)
        self.assertNotEqual(pet.state, "dead")


class InjuryChanceTests(ICCase):
    """injury_chance_step 1: a lost battle injures at the form's own chance
    (Baby II 5% to Ultimate 25%), a point more after every loss, a point
    less after every win."""
    ENEMY = SimpleNamespace(stage=3, name="Agumon", version=1)

    def battle(self, pet, won, draw=0.99):
        with patch("models.game_pet.random.random", return_value=draw):
            pet.finish_battle(won, self.ENEMY, 1)

    def test_a_child_starts_at_its_own_ten(self):
        self.assertEqual(self.pet().injury_chance(), 10)

    def test_losses_raise_it_and_wins_lower_it(self):
        pet = self.pet()
        for _ in range(3):
            self.battle(pet, False)
        self.assertEqual(pet.injury_chance(), 13)
        self.battle(pet, True)
        self.assertEqual(pet.injury_chance(), 12)

    def test_the_loss_rolls_before_it_rises(self):
        pet = self.pet()
        self.battle(pet, False, draw=0.105)          # 10.5 misses 10%
        self.assertEqual((pet.injury, pet.injury_chance()), (0, 11))
        self.battle(pet, False, draw=0.105)          # and hits 11%
        self.assertGreater(pet.injury, 0)
        self.assertEqual(pet.sick, 0, "a battle injures, it never makes sick")

    def test_it_stays_between_0_and_100(self):
        pet = self.pet()
        for _ in range(15):
            self.battle(pet, True)
        self.assertEqual(pet.injury_chance(), 0)
        self.battle(pet, False)
        self.assertEqual(pet.injury_chance(), 1, "a step from 0, not from the wins banked")

    def test_a_new_form_starts_from_its_own(self):
        pet = self.pet()
        self.battle(pet, False)
        self.battle(pet, False)
        pet.set_data(dict(record(self.ic, "GeoGreymon", 4, 1), module="IC"))
        self.assertEqual(pet.injury_chance(), 15)

    def test_every_battle_but_the_arena_counts(self):
        """Owner, 2026-10-20: "the injury logic should be global". A Versus
        (and a DCom or online battle, through the same _battle_health)
        injures and moves the chance as an adventure battle does."""
        winner, loser = self.pet(), self.pet(name="Gaomon")
        with patch("models.game_pet.random.random", return_value=0.0):
            loser.finish_versus(False, opponent=winner)
        self.assertGreater(loser.injury, 0, "the loss injured it")
        self.assertEqual(loser.injury_chance(), 11)
        with patch("models.game_pet.random.random", return_value=0.99):
            winner.finish_versus(True, opponent=loser)
        self.assertEqual((winner.injury, winner.injury_chance()), (0, 9))

    def test_a_module_without_a_step_keeps_it_fixed(self):
        pet = self.pet(self.dmc, injury_probability=10)
        self.battle(pet, False)
        self.assertEqual(pet.injury_chance(), 10)


if __name__ == "__main__":
    unittest.main()
