"""care_allow_below_min_weight: weight may fall below min_weight, down to 1.

Off (the default), a species' min_weight is the floor for every loss: poop,
training, battle and items. On (DW1: Digimon World lets weight fall to 1),
the floor is 1. Evolving still sets the new form's weight.
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_android_offline import module, pet  # noqa: E402


class WeightFloorTests(unittest.TestCase):
    def setUp(self):
        p = patch.object(runtime_globals, 'game_console', SimpleNamespace(log=lambda *_: None))
        p.start()
        self.addCleanup(p.stop)

    def test_the_floor(self):
        self.assertEqual(pet_stats.weight_floor(15, False), 15)
        self.assertEqual(pet_stats.weight_floor(15, True), 1)
        self.assertEqual(pet_stats.weight_floor(0, True), 0)
        self.assertEqual(pet_stats.weight_floor(None, False), 0)

    def test_item_losses_stop_at_the_floor(self):
        for allow, expected in ((False, 10), (True, 1)):
            mod = module(care_allow_below_min_weight=allow)
            p = pet(mod, weight=12, min_weight=10)
            with patch('models.game_pet.get_module', return_value=mod):
                p.add_weight(-99)
            self.assertEqual(p.weight, expected, allow)

    def test_a_module_without_the_field_keeps_min_weight(self):
        mod = module()
        p = pet(mod, weight=12, min_weight=10)
        with patch('models.game_pet.get_module', return_value=mod):
            self.assertEqual(p.weight_floor(), 10)


if __name__ == '__main__':
    unittest.main()
