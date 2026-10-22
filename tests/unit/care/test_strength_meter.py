"""A device without a Strength meter (the iC, DW1) ignores Strength.

Strength starts at 0 and only protein or training fills it; on a device that
never shows the meter it stays 0. That 0 used to make need_care() true for
good, so update_evolution() never tried a route (found on an iC Agumon,
2026-10-13). Strength now counts only where "Strength" is in visible_stats,
in GamePet and in the Android copy alike.
"""
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'src'))
from core import pet_stats, runtime_globals  # noqa: E402
from models.game_pet import GamePet  # noqa: E402
from services.android_offline import OfflineWorld  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_android_offline import module, pet, snapshot  # noqa: E402

WITH_METER = ["Age", "Hunger", "Strength", "Effort"]
WITHOUT_METER = ["Age", "Hunger", "Effort", "Reliability"]


class StrengthMeterTests(unittest.TestCase):
    def setUp(self):
        for target, value in (('game_console', SimpleNamespace(log=lambda *_: None)),
                              ('game_sound', SimpleNamespace(play=lambda *_: None))):
            p = patch.object(runtime_globals, target, value)
            p.start()
            self.addCleanup(p.stop)

    def make(self, stats, **overrides):
        mod = module(visible_stats=stats, protein_strengh_gain=1, protein_weight_gain=0,
                     meat_weight_gain=1, can_eat_sleeping=True, protein_overdose_max=0,
                     protein_dp_gain=0, care_block_actions_when_sleeping=False)
        overrides.setdefault('strength', 0)
        p = pet(mod, **overrides)
        return mod, p

    def test_the_meter_is_read_from_visible_stats(self):
        self.assertTrue(pet_stats.tracks_strength(WITH_METER))
        self.assertFalse(pet_stats.tracks_strength(WITHOUT_METER))
        self.assertFalse(pet_stats.tracks_strength([]))

    def test_strength_zero_needs_care_only_where_the_meter_exists(self):
        for stats, expected in ((WITH_METER, True), (WITHOUT_METER, False)):
            mod, p = self.make(stats)
            with patch('models.game_pet.get_module', return_value=mod), \
                    patch.object(GamePet, 'should_sleep', return_value=False):
                self.assertEqual(p.need_care(), expected, stats)
                self.assertEqual(p.call_sign(), expected, stats)

    def test_evolution_is_tried_without_the_meter(self):
        mod, p = self.make(WITHOUT_METER, _evol_minutes=10, time=5)
        tried = []
        with patch('models.game_pet.get_module', return_value=mod), \
                patch.object(GamePet, 'should_sleep', return_value=False), \
                patch.object(GamePet, 'find_evolution', side_effect=lambda *a, **k: tried.append(1)), \
                patch('utils.evolution_rules.should_fail', return_value=False):
            p.update_evolution()
        self.assertTrue(tried)

    def test_no_strength_mistake_or_drain_without_the_meter(self):
        mod, p = self.make(WITHOUT_METER, strength=2, _cd_strength=1)
        with patch('models.game_pet.get_module', return_value=mod), \
                patch.object(GamePet, 'should_sleep', return_value=False):
            p.update_needs(5)
            self.assertEqual((p.strength, p._cd_strength), (2, 1))
            p.strength = 0
            for _ in range(30):
                p.update_care_mistakes()
        self.assertEqual((p.mistakes, p.care_strength_mistake_timer), (0, 0))

    def test_protein_is_refused_without_the_meter(self):
        mod, p = self.make(WITHOUT_METER)
        with patch('models.game_pet.get_module', return_value=mod):
            self.assertFalse(p.set_eating("strength", 1))
        self.assertEqual(p.strength, 0)
        mod, p = self.make(WITH_METER)
        with patch('models.game_pet.get_module', return_value=mod):
            self.assertTrue(p.set_eating("strength", 1))
        self.assertEqual(p.strength, 1)

    def test_the_android_copy_agrees(self):
        for stats, expected in ((WITH_METER, True), (WITHOUT_METER, False)):
            mod, p = self.make(stats)
            state = snapshot([p])
            world = OfflineWorld(state, {'Test': mod})
            offline = world.pet_list[0]
            offline.strength = 0
            with patch.object(type(offline), 'should_sleep', return_value=False):
                self.assertEqual(offline.need_care(), expected, stats)
                self.assertEqual(offline.strength_empty(), expected, stats)


def power(rule, strength, stomach=10, strength_max=0, hunger=4, weight=20):
    return pet_stats.power_with_bonus_rule(
        rule, 50, stage=4, strength=strength, stomach=stomach, hunger=hunger,
        weight=weight, level=1, version=1, effort=0, traited=False, shook=False,
        star=0, strength_max=strength_max)


class StrengthCapAndBandsTests(unittest.TestCase):
    """"Strength Hearts" became "+16", the Mini's banded "+15" joined it, and
    a module can cap Strength itself (`care_strength_max`, owner 2026-10-19).
    """

    def setUp(self):
        StrengthMeterTests.setUp(self)

    def capped(self, strength_max, stomach=10, **overrides):
        mod = module(visible_stats=WITH_METER, protein_strengh_gain=1, protein_weight_gain=3,
                     meat_weight_gain=1, can_eat_sleeping=True, protein_overdose_max=0,
                     protein_dp_gain=0, care_block_actions_when_sleeping=False,
                     strength_max=strength_max, training_effort_gain=[0, 0, 0, 0],
                     training_strength_gain=[0, 2, 3, 4], training_weight_loss=[0, 0, 0, 0],
                     power_bonus_rule="Strength Hearts +15")
        overrides.setdefault('strength', 0)
        p = pet(mod, stomach=stomach, weight=20, **overrides)
        return mod, p

    def test_the_old_name_is_the_plus_16_rule(self):
        self.assertEqual(pet_stats.canonical_power_bonus_rule("Strength Hearts"), "Strength Hearts +16")
        self.assertEqual(pet_stats.resolve_power_bonus_rule({"power_bonus_rule": "Strength Hearts"}),
                         "Strength Hearts +16")
        for strength in range(0, 11):
            self.assertEqual(power("Strength Hearts", strength), power("Strength Hearts +16", strength))
        self.assertEqual(power("Strength Hearts +16", 10), 66)
        # Still withheld at 99 g or with no Hunger Hearts, as the Ver.20th does.
        self.assertEqual(power("Strength Hearts +16", 10, weight=99), 50)
        self.assertEqual(power("Strength Hearts +16", 10, hunger=0), 50)

    def test_plus_15_pays_the_mini_s_bands(self):
        # Centarumon fed up from an empty meter sent 50, 54, 58 and 65.
        expected = {0: 50, 3: 50, 4: 54, 7: 54, 8: 58, 11: 58, 12: 65, 15: 65}
        for strength, value in expected.items():
            self.assertEqual(power("Strength Hearts +15", strength, strength_max=15), value, strength)
        # Agumon at a full meter sent 40 on its base of 25.
        self.assertEqual(pet_stats.power_with_bonus_rule(
            "Strength Hearts +15", 25, stage=3, strength=15, stomach=8, hunger=4, weight=10,
            level=1, version=1, effort=0, traited=False, shook=False, star=0, strength_max=15), 40)

    def test_full_means_the_cap_where_there_is_one(self):
        self.assertEqual(power("Stage Table", 10), 58)
        self.assertEqual(power("Stage Table", 10, strength_max=15), 50)
        self.assertEqual(power("Stage Table", 15, strength_max=15), 58)
        self.assertEqual(power("Strength Hearts +16", 15, strength_max=15), 66)
        self.assertEqual(power("Strength Hearts +16", 4, strength_max=16), 54)

    def test_the_cap_is_the_stomach_unless_the_module_sets_one(self):
        self.assertEqual(pet_stats.strength_cap(0, 10), 10)
        self.assertEqual(pet_stats.strength_cap(15, 10), 15)
        self.assertEqual(pet_stats.strength_cap(15, 4), 15)

    def test_the_drain(self):
        # No cap: past four hearts falls to 4 at once, then one at a time.
        self.assertEqual([pet_stats.drained_strength(s, 0) for s in (10, 5, 4, 1, 0)], [4, 4, 3, 0, 0])
        # A cap: one point a drain all the way down.
        self.assertEqual([pet_stats.drained_strength(s, 15) for s in (15, 10, 5, 1, 0)], [14, 9, 4, 0, 0])

    def test_hearts_show_the_share_of_the_cap(self):
        hearts = [pet_stats.strength_hearts(s, 15) for s in range(16)]
        self.assertEqual(hearts, [0, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4])
        self.assertEqual(pet_stats.strength_hearts(3, 0), 3)

    def test_protein_fills_to_the_cap_and_still_weighs(self):
        mod, p = self.capped(15, stomach=10)
        with patch('models.game_pet.get_module', return_value=mod):
            for _ in range(20):
                self.assertTrue(p.set_eating("strength", 1))
        self.assertEqual(p.strength, 15)
        self.assertEqual(p.weight, 80)
        mod, p = self.capped(0, stomach=10)
        with patch('models.game_pet.get_module', return_value=mod):
            for _ in range(20):
                self.assertTrue(p.set_eating("strength", 1))
        self.assertEqual(p.strength, 10)

    def test_training_stops_at_the_cap_only_where_there_is_one(self):
        mod, p = self.capped(15, strength=14)
        with patch('models.game_pet.get_module', return_value=mod), \
                patch.object(GamePet, 'set_state'):
            p.finish_training(won=True, grade=3)
        self.assertEqual(p.strength, 15)
        mod, p = self.capped(0, strength=10)
        with patch('models.game_pet.get_module', return_value=mod), \
                patch.object(GamePet, 'set_state'):
            p.finish_training(won=True, grade=3)
        self.assertEqual(p.strength, 14)

    def test_a_capped_meter_drains_a_point_a_time_here_and_on_android(self):
        for strength_max, after in ((15, [14, 13, 12]), (0, [4, 3, 2])):
            mod, p = self.capped(strength_max, strength=15 if strength_max else 10, _cd_strength=1)
            p.strength_loss = 10
            with patch('models.game_pet.get_module', return_value=mod), \
                    patch.object(GamePet, 'should_sleep', return_value=False):
                seen = []
                for _ in range(3):
                    p.update_needs(10)
                    seen.append(p.strength)
            self.assertEqual(seen, after, strength_max)

            mod, p = self.capped(strength_max, strength=15 if strength_max else 10, _cd_strength=1)
            p.strength_loss = 10
            world = OfflineWorld(snapshot([p]), {'Test': mod})
            offline = world.pet_list[0]
            offline._cd_strength, offline.strength_loss = 1, 10
            with patch.object(type(offline), 'should_sleep', return_value=False):
                seen = []
                for _ in range(3):
                    offline.update_needs(10)
                    seen.append(offline.strength)
            self.assertEqual(seen, after, strength_max)


if __name__ == '__main__':
    unittest.main()
