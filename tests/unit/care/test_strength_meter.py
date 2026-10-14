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


if __name__ == '__main__':
    unittest.main()
