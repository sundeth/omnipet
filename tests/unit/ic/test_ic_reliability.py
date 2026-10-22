# -*- coding: utf-8 -*-
"""ICX-01: the Digivice iC's Reliability, rule by rule, on the real IC module.

Rules protected (modules/IC/module.json `reliability_*`; the 10X playbook's
table, utilities/IC/IC_RESEARCH_AND_TODO.md "Reliability mechanics"):

    base 15                      a new pet starts at 15
    becoming full        +1      on the meal that fills the stomach, not while full
    answering a call     +1      feeding during a hunger call, lights off during a bedtime call
    ignoring a call      -1      once when the call's three minutes run out
    minigame success     +1      a won training, a cleared iC minigame
    two poops            -1      every second poop since the last flush
    sickness or injury   -1      at the onset only
    battle win           +1      adventure, Versus and connection battles
    hourly               -1      every 60 minutes, asleep or awake, not when dead

and the meter's bounds 0..31 (core.constants.RELIABILITY_MIN/MAX), that the
value survives evolution, that a non-iC module (every field 0) is untouched
by all of it, and that the Android offline copy (services.android_pet_rules)
applies the same rules. Checklist: ICX-01 (release-1.0.md).

Code under test: models.game_pet (add_reliability, _apply_reliability_event,
set_eating, answer_call, update_care_mistakes, poop, add_ailment, finish_training,
finish_battle, finish_versus, update_reliability), training.ic_minigame,
battle.battle_encounter_dcom, scenes.scene_maingame.update_cleaning.
"""
import json
import os
import sys
import time
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ic_fixtures import HAVE_IC, IC_RELIABILITY, MODULES, ICCase, offline_world  # noqa: E402


class ModuleDataTests(unittest.TestCase):
    @unittest.skipUnless(HAVE_IC, "modules/ is gitignored")
    def test_the_ic_declares_the_eight_deltas_and_its_base(self):
        data = json.load(open(os.path.join(MODULES, "IC", "module.json"), encoding="utf-8"))
        self.assertEqual({k: data.get(k) for k in IC_RELIABILITY}, IC_RELIABILITY)

    @unittest.skipUnless(os.path.isdir(MODULES), "modules/ is gitignored")
    def test_no_other_module_uses_reliability(self):
        """Only the iC has the stat; every other device leaves all nine at 0.
        DW1 is skipped: another agent is building it."""
        for folder in sorted(os.listdir(MODULES)):
            path = os.path.join(MODULES, folder, "module.json")
            if folder in ("IC", "DW1") or not os.path.exists(path):
                continue
            data = json.load(open(path, encoding="utf-8"))
            with self.subTest(module=folder):
                self.assertEqual({k: data[k] for k in IC_RELIABILITY if data.get(k)}, {})


class LoaderTests(ICCase):
    def test_the_loader_reads_every_field(self):
        self.assertEqual({k: getattr(self.ic, k) for k in IC_RELIABILITY}, IC_RELIABILITY)
        self.assertEqual({k: getattr(self.dmc, k) for k in IC_RELIABILITY},
                         dict.fromkeys(IC_RELIABILITY, 0))


class BaseAndBoundsTests(ICCase):
    def test_a_new_ic_pet_starts_at_15(self):
        self.assertEqual(self.pet().reliability, 15)
        self.assertEqual(self.pet(stage=1).reliability, 15, "a Baby I too")

    def test_the_meter_runs_from_0_to_31(self):
        pet = self.pet()
        self.assertEqual(pet.add_reliability(99), 16, "the change actually made")
        self.assertEqual(pet.reliability, 31)
        self.assertEqual(pet.add_reliability(-99), -31)
        self.assertEqual(pet.reliability, 0)
        self.assertEqual(pet.add_reliability("x"), 0, "a bad amount changes nothing")

    def test_a_gain_at_31_and_a_loss_at_0_are_clamped(self):
        pet = self.pet(reliability=31)
        with patch("models.game_pet.random.random", return_value=0.99):
            pet.finish_versus(True)
        self.assertEqual(pet.reliability, 31)
        pet.reliability = 0
        pet.update_reliability(60)
        self.assertEqual(pet.reliability, 0)
        pet.add_ailment("sick")
        self.assertEqual(pet.reliability, 0)

    def test_an_old_save_is_clamped_and_a_missing_value_starts_at_the_base(self):
        pet = self.pet(reliability=40)
        pet.patch()
        self.assertEqual(pet.reliability, 31)
        del pet.reliability
        pet.patch()
        self.assertEqual(pet.reliability, 15)

    def test_it_survives_an_evolution_with_its_hourly_countdown(self):
        pet = self.pet(name="Agumon", reliability=27)
        pet.update_reliability(40)
        self.assertTrue(pet.evolve_to("GeoGreymon", 1))
        self.assertEqual((pet.name, pet.reliability), ("GeoGreymon", 27))
        pet.update_reliability(20)
        self.assertEqual(pet.reliability, 26, "the hour begun before evolving ends on time")


class FeedingTests(ICCase):
    def test_the_meal_that_fills_the_stomach_gives_one(self):
        pet = self.pet(hunger=6)
        self.assertEqual(pet.stomach, 8)
        pet.set_eating("hunger", 1)
        self.assertEqual((pet.hunger, pet.reliability), (7, 15), "not full yet")
        pet.set_eating("hunger", 1)
        self.assertEqual((pet.hunger, pet.reliability), (8, 16))
        self.assertFalse(pet.set_eating("hunger", 1), "a full pet refuses")
        self.assertEqual(pet.reliability, 16, "nothing more while full")

    def test_feeding_during_a_hunger_call_answers_it(self):
        pet = self.pet(hunger=0)
        self.tick(pet, 2)                        # two of the call's three minutes
        self.assertTrue(pet.call_sign())
        pet.set_eating("hunger", 1)
        self.assertEqual(pet.reliability, 16)
        self.assertEqual(pet.mistakes, 0)

    def test_food_with_no_call_pending_answers_nothing(self):
        pet = self.pet(hunger=3)
        self.assertFalse(pet.answer_call("hunger"))
        pet.set_eating("hunger", 1)
        self.assertEqual(pet.reliability, 15)


class CallTests(ICCase):
    def test_an_ignored_hunger_call_costs_one_once(self):
        pet = self.pet(hunger=0, _cd_hunger=9999)
        self.tick(pet, 2)
        self.assertEqual((pet.reliability, pet.mistakes), (15, 0))
        self.tick(pet)                           # the third minute
        self.assertEqual((pet.reliability, pet.mistakes), (14, 1))
        self.tick(pet, 10)
        self.assertEqual((pet.reliability, pet.mistakes), (14, 1), "once per call")
        pet.set_eating("hunger", 1)
        self.assertEqual(pet.reliability, 14, "a call already lost is not answered")

    def test_lights_off_during_the_bedtime_call_answers_it_once(self):
        pet = self.pet(_test_bedtime=True)
        self.tick(pet, 2)
        self.assertTrue(pet.answer_call("sleep"))
        self.assertEqual(pet.reliability, 16)
        self.assertFalse(pet.answer_call("sleep"), "the same bedtime pays once")
        self.assertEqual(pet.reliability, 16)

    def test_lights_off_with_no_bedtime_call_answers_nothing(self):
        pet = self.pet()                         # awake hours
        self.assertFalse(pet.answer_call("sleep"))
        self.assertEqual(pet.reliability, 15)

    def test_an_ignored_bedtime_call_costs_one_each_night(self):
        """A bedtime call left with the lights on costs one care mistake and
        one Reliability, once: it does not repeat (owner, 2026-10-17; it
        repeated every three minutes). The next night is a new call."""
        pet = self.pet(_test_bedtime=True)
        self.tick(pet, 3)
        self.assertEqual((pet.reliability, pet.mistakes), (14, 1))
        self.tick(pet, 30)
        self.assertEqual((pet.reliability, pet.mistakes), (14, 1), "the call does not repeat")
        self.assertFalse(pet.answer_call("sleep"), "too late to answer")
        pet._test_bedtime = False                # morning
        self.tick(pet)
        pet._test_bedtime = True                 # the next night
        self.tick(pet, 3)
        self.assertEqual((pet.reliability, pet.mistakes), (13, 2))

    def test_going_to_sleep_ends_the_call_and_a_new_one_counts_again(self):
        """Lights off ends the call; woken and left with the lights on, the
        pet calls again and that call counts once more (as hunger's does after
        a meal)."""
        pet = self.pet(_test_bedtime=True)
        self.tick(pet, 3)
        self.assertEqual(pet.mistakes, 1)
        pet.set_state("nap")
        self.assertEqual(pet.care_sleep_mistake_timer, 0)
        pet.set_state("idle")                   # woken in the night
        self.tick(pet, 3)
        self.assertEqual(pet.mistakes, 2)


class MinigameTests(ICCase):
    def test_a_won_training_gives_one_and_a_lost_one_nothing(self):
        pet = self.pet()
        pet.finish_training(won=True, grade=2)
        self.assertEqual(pet.reliability, 16)
        pet.finish_training(won=False, grade=0)
        self.assertEqual(pet.reliability, 16)

    def test_a_cleared_ic_minigame_gives_each_player_one(self):
        from training.ic_minigame import ICMinigame
        a, b = self.pet(), self.pet(name="Gaomon")
        game = SimpleNamespace(pets=[a, b], succeeded=True, prize=0)
        ICMinigame.apply_training_results(game)
        self.assertEqual((a.reliability, b.reliability), (16, 16))
        game.succeeded = False
        ICMinigame.apply_training_results(game)
        self.assertEqual((a.reliability, b.reliability), (16, 16))


class PoopTests(ICCase):
    def test_every_second_poop_costs_one(self):
        pet = self.pet()
        losses = []
        for _ in range(5):
            pet.poop()
            losses.append(15 - pet.reliability)
        self.assertEqual(losses, [0, 1, 1, 2, 2])
        self.assertEqual(len(self.gg.poop_list), 5, "the iC drops one at a time")

    def test_a_flush_starts_a_new_count(self):
        import pygame
        from scenes.scene_maingame import SceneMainGame
        pet = self.pet()
        pet.poop()
        cleaning = SimpleNamespace(cleaning=True, cleaning_x=-1000, cleaning_speed=1)
        with patch.object(self.rg, "misc_sprites", {"Wash": pygame.Surface((8, 8))}):
            SceneMainGame.update_cleaning(cleaning)
        self.assertEqual((self.gg.poop_list, pet.unflushed_poops), ([], 0))
        pet.poop()
        self.assertEqual(pet.reliability, 15, "the poop before the flush does not pair")
        pet.poop()
        self.assertEqual(pet.reliability, 14)


class SicknessTests(ICCase):
    def test_falling_sick_costs_one_at_the_onset(self):
        pet = self.pet()
        self.assertTrue(pet.add_ailment("sick"))
        self.assertEqual(pet.reliability, 14)
        self.assertFalse(pet.add_ailment("sick"), "already sick")
        self.assertFalse(pet.add_ailment("injury"), "one ailment at a time")
        self.tick(pet, 5)
        self.assertEqual(pet.reliability, 14, "staying sick costs nothing more")

    def test_an_injury_from_a_lost_battle_costs_one(self):
        pet = self.pet()
        enemy = SimpleNamespace(stage=3, name="Agumon", version=1)
        with patch("models.game_pet.random.random", return_value=0.0):   # the form's 10% roll hits
            pet.finish_battle(False, enemy, 1)
        self.assertGreater(pet.injury, 0)
        self.assertEqual(pet.reliability, 14)


class BattleTests(ICCase):
    ENEMY = SimpleNamespace(stage=3, name="Agumon", version=1)

    def test_an_adventure_win_gives_one_and_a_loss_nothing(self):
        pet = self.pet()
        with patch("models.game_pet.random.random", return_value=0.99):  # no sickness roll
            pet.finish_battle(True, self.ENEMY, 1)
            self.assertEqual(pet.reliability, 16)
            pet.finish_battle(False, self.ENEMY, 1)
            self.assertEqual(pet.reliability, 16)

    def test_a_win_never_injures(self):
        """Only a loss rolls the form's injury chance (owner, 2026-10-21: the
        flat 10% the module rolled on a win too had no source): +1, no -1."""
        pet = self.pet()
        with patch("models.game_pet.random.random", return_value=0.0):
            pet.finish_battle(True, self.ENEMY, 1)
        self.assertEqual((pet.win, pet.injury_total, pet.reliability), (1, 0, 16))

    def test_a_versus_win_gives_one(self):
        winner, loser = self.pet(), self.pet(name="Gaomon")
        winner.finish_versus(True, opponent=loser)
        loser.finish_versus(False, opponent=winner)
        self.assertEqual((winner.reliability, loser.reliability), (16, 15))


class ConnectionBattleTests(ICCase):
    """A DCom battle against a real device: the result screen's own path
    (BattleEncounterDCom.update_result) run on a won battle."""

    def result(self, pet, won=True):
        from battle.battle_encounter_dcom import BattleEncounterDCom
        encounter = SimpleNamespace(
            result_timer=10 ** 6, _has_result_rewards=lambda: True,
            victory_status="Victory" if won else "Defeat",
            battle_player=SimpleNamespace(team1=[pet], winners=["team1" if won else "team2"]),
            dcom_simulator=SimpleNamespace(opponent_device_version=0, battle_format="IC"),  # a 10X: wire 0
            module=self.ic, is_oem_mode=False, return_to_main_scene=Mock())
        BattleEncounterDCom.update_result(encounter)
        encounter.return_to_main_scene.assert_called_once()

    def test_the_result_path_counts_the_win(self):
        pet = self.pet(hunger=4)
        before = (pet.battles, pet.win, pet.totalBattles, pet.totalWin)
        self.result(pet)
        self.assertEqual((pet.pvp_wins, pet.pvp_battles, pet.connect_points, pet.hunger), (1, 1, 1, 3))
        # And a battle won like any other (owner, 2026-10-21): the 10X's
        # 20/50-win gates can be met by cable.
        self.assertEqual((pet.battles, pet.win, pet.totalBattles, pet.totalWin),
                         tuple(n + 1 for n in before))
        self.assertIn("DigiShop 1", self.gg.shop_access.get("IC", {}))

    # Bug: a DCom/online win never applies reliability_battle_win
    # (battle_encounter_dcom.py update_result, battle_encounter.py PvP
    # result); see tests/findings/ic.md, 1 "A connection win gives no Reliability".
    # Fixed 2026-10-13; kept as a regression test.
    def test_a_connection_win_gives_one(self):
        pet = self.pet(hunger=4)
        self.result(pet)
        self.assertEqual(pet.reliability, 16)

    def test_a_connection_loss_gives_nothing(self):
        pet = self.pet(hunger=4)
        self.result(pet, won=False)
        self.assertEqual(pet.reliability, 15)


class HourlyTests(ICCase):
    def test_every_hour_costs_one(self):
        pet = self.pet()
        pet.update_reliability(59)
        self.assertEqual(pet.reliability, 15)
        pet.update_reliability(1)
        self.assertEqual(pet.reliability, 14)
        pet.update_reliability(150)                  # a long batch: two more hours
        self.assertEqual(pet.reliability, 12)

    def test_it_runs_through_the_game_loop_asleep_too(self):
        pet = self.pet(_test_bedtime=True)
        pet.set_state("nap")
        pet.nap_until = datetime.now() + timedelta(days=1)    # stays asleep
        self.tick(pet, 60, batch=True)
        self.assertEqual((pet.state, pet.reliability), ("nap", 14))

    def test_a_dead_pet_keeps_its_value(self):
        pet = self.pet()
        pet.state = "dead"
        self.tick(pet, 120, batch=True)
        self.assertEqual(pet.reliability, 15)


class NonICTests(ICCase):
    """A DMC pet goes through every event and keeps Reliability 0."""

    def test_no_event_moves_a_module_without_the_fields(self):
        pet = self.pet(self.dmc)
        self.assertEqual(pet.reliability, 0)
        pet.hunger = pet.stomach - 1
        pet.set_eating("hunger", 1)                  # becoming full
        pet.hunger = 0
        self.assertFalse(pet.answer_call("hunger"), "no call to answer")
        pet._cd_hunger = 9999
        self.tick(pet, 30)                           # an ignored call
        for _ in range(4):
            pet.poop()
        pet.finish_training(won=True, grade=3)
        with patch("models.game_pet.random.random", return_value=0.99):
            pet.finish_battle(True, SimpleNamespace(stage=3, name="Agumon", version=1), 1)
        pet.finish_versus(True)
        pet.add_ailment("injury")
        pet.update_reliability(600)
        self.assertGreater(pet.mistakes, 0, "the care rules did run")
        self.assertEqual(pet.reliability, 0)


class AndroidParityTests(ICCase):
    """The offline copy of the minute rules (services.android_pet_rules)
    applies the same iC Reliability as the game loop."""

    def test_an_ignored_call_and_two_hours_match_the_game_loop(self):
        live = self.pet(hunger=0, _cd_hunger=9999, _cd_poop=9999)
        world, start = offline_world([live], {"IC": self.ic})
        world.advance(start + 125 * 60)
        self.tick(live, 125)
        offline = world.pet_list[0]
        self.assertEqual(live.reliability, 15 - 1 - 2)
        for field in ("reliability", "mistakes", "care_food_mistake_timer", "_cd_reliability"):
            self.assertEqual(getattr(offline, field), getattr(live, field), field)

    def test_a_night_with_the_lights_on_matches_the_game_loop(self):
        """20:00 is the iC Child's bedtime: lights left on for ten minutes."""
        live = self.pet(_cd_poop=9999, _test_bedtime=True)
        world, start = offline_world([live], {"IC": self.ic},
                                     at=datetime(2026, 9, 12, 20, 0, 30).timestamp())
        world.advance(start + 10 * 60)
        self.tick(live, 10)
        offline = world.pet_list[0]
        self.assertEqual((live.reliability, live.mistakes), (14, 1))
        for field in ("reliability", "mistakes", "care_sleep_mistake_timer"):
            self.assertEqual(getattr(offline, field), getattr(live, field), field)

    def test_offline_poops_sickness_and_bounds(self):
        live = self.pet(_cd_poop=9999)
        world, _start = offline_world([live], {"IC": self.ic})
        offline = world.pet_list[0]
        offline.poop()
        offline.poop()
        self.assertEqual(offline.reliability, 14, "two poops")
        offline.add_ailment("sick")
        self.assertEqual(offline.reliability, 13, "sickness")
        self.assertEqual(offline.add_reliability(99), 18)
        self.assertEqual(offline.reliability, 31, "the same bounds")


if __name__ == "__main__":
    unittest.main()
