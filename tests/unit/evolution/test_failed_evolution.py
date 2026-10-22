"""Failed evolutions (owner, 2026-10-20): on every module, a pet with a route
that reads the win rate (`win_ratio`, `total_win_ratio`) gets one try when
its evolution timer runs out. If no route is taken (its requirements unmet,
or its % roll lost) it never evolves on the timer again (`evolution_failed`);
items, Level Reverse, jogress and armor still change it, and every new form
starts unfailed. The module's `failed_evolution_double_needs` (PENC, PENGZ)
then doubles its hunger, strength and poop. It replaced the PENGZ's
evolution_fail_on_first_try, which is still read from older modules.

GamePet and its Android copy (services.android_pet_rules) share the rule
through utils.evolution_rules.
"""
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
from core import runtime_globals  # noqa: E402
from models.game_module import _death_save  # noqa: E402,F401  (loads the loader module)
from models.game_pet import GamePet  # noqa: E402
from services.android_pet_rules import AndroidPetRules  # noqa: E402
from utils import evolution_rules  # noqa: E402

sys.path.insert(0, str(ROOT / 'tests' / 'unit' / 'android'))
from test_android_offline import module, pet  # noqa: E402

WIN_RATE = {"to": "MetalGreymon", "battles": [15, 999999], "win_ratio": [80, 100]}
BATTLES = {"to": "SkullGreymon", "battles": [15, 999999]}


class Rule(unittest.TestCase):
    def test_a_win_rate_route_makes_the_try_final(self):
        self.assertTrue(evolution_rules.should_fail([WIN_RATE]))
        self.assertTrue(evolution_rules.should_fail([BATTLES, {"to": "X", "total_win_ratio": [60, 100]}]))

    def test_other_routes_keep_waiting(self):
        self.assertFalse(evolution_rules.should_fail([BATTLES, {"to": "X", "mistakes": [0, 3]}]))
        self.assertFalse(evolution_rules.should_fail([]))

    def test_routes_that_are_not_the_timers_do_not_count(self):
        for route in (dict(WIN_RATE, jogress="Gabumon"), dict(WIN_RATE, item="Crest"),
                      dict(WIN_RATE, at_death=50), dict(WIN_RATE, defeat_tag="boss")):
            with self.subTest(route=route):
                self.assertFalse(evolution_rules.should_fail([route]))

    def test_double_needs_is_the_modules_choice(self):
        failed = SimpleNamespace(evolution_failed=True, stage=4, form_minutes=0)
        on = SimpleNamespace(failed_evolution_double_needs=True)
        off = SimpleNamespace(failed_evolution_double_needs=False)
        self.assertEqual((evolution_rules.needs_factor(failed, on), evolution_rules.poop_factor(failed, on)), (2, 2))
        self.assertEqual((evolution_rules.needs_factor(failed, off), evolution_rules.poop_factor(failed, off)), (1, 1))


class Loader(unittest.TestCase):
    def load(self, data):
        from models.game_module import GameModule
        mod = GameModule.__new__(GameModule)
        # Only the two lines under test, as the loader runs them.
        legacy = bool(data.get("evolution_fail_on_first_try", False))
        mod.traited_egg_rule = data.get("traited_egg_rule")
        mod.failed_evolution_double_needs = bool(data.get("failed_evolution_double_needs", legacy))
        if legacy and mod.traited_egg_rule == "Win Ratio (Stage 5)":
            mod.traited_egg_rule = "Win Ratio (Failed or Aged, Lifetime)"
        return mod

    def test_the_loader_reads_the_old_flag(self):
        src = (ROOT / 'src' / 'models' / 'game_module.py').read_text(encoding='utf-8')
        self.assertIn('data.get("failed_evolution_double_needs", legacy_fail)', src)
        old = self.load({"evolution_fail_on_first_try": True, "traited_egg_rule": "Win Ratio (Stage 5)"})
        self.assertEqual((old.failed_evolution_double_needs, old.traited_egg_rule),
                         (True, "Win Ratio (Failed or Aged, Lifetime)"))
        new = self.load({"failed_evolution_double_needs": False, "traited_egg_rule": "Win Ratio (Stage 5)"})
        self.assertEqual((new.failed_evolution_double_needs, new.traited_egg_rule),
                         (False, "Win Ratio (Stage 5)"))


class TraitedEgg(unittest.TestCase):
    """"Win Ratio (Failed or Aged)": Stage V+, a failed evolution or Stage
    VI+ 48 hours in the form, and 60% wins -- the current ratio (PENC's
    manual), or the lifetime one with ", Lifetime" (the PENGZ as built)."""

    def egg(self, rule, **fields):
        mod = module(traited_egg_rule=rule)
        state = dict(stage=5, evolution_failed=True, battles=10, win=7, totalBattles=10, totalWin=5)
        state.update(fields)
        p = pet(mod, **state)
        granted = []
        with patch('models.game_pet.get_module', return_value=mod), \
                patch.object(GamePet, '_grant_traited_egg', lambda self: granted.append(1)):
            p.set_traited_egg()
        return bool(granted)

    def test_the_current_ratio(self):
        self.assertTrue(self.egg("Win Ratio (Failed or Aged)"))          # 70%
        self.assertFalse(self.egg("Win Ratio (Failed or Aged, Lifetime)"))  # 50%

    def test_only_from_a_failure_or_48_hours_at_vi(self):
        self.assertFalse(self.egg("Win Ratio (Failed or Aged)", evolution_failed=False))
        self.assertTrue(self.egg("Win Ratio (Failed or Aged)", evolution_failed=False, stage=6,
                                 form_minutes=evolution_rules.FORM_48_HOURS))


class Pets(unittest.TestCase):
    def setUp(self):
        for target, value in (('game_console', SimpleNamespace(log=lambda *_: None)),
                              ('game_sound', SimpleNamespace(play=lambda *_: None))):
            p = patch.object(runtime_globals, target, value)
            p.start()
            self.addCleanup(p.stop)

    def check(self, routes, found=None):
        """One timer check of a GamePet whose time is up: (failed, tries)."""
        mod = module(failed_evolution_double_needs=False)
        p = pet(mod, _evol_minutes=10, time=5, evolve=routes)
        tried = []
        with patch('models.game_pet.get_module', return_value=mod), \
                patch.object(GamePet, 'need_care', return_value=False), \
                patch.object(GamePet, 'find_evolution',
                             side_effect=lambda *a, **k: tried.append(1) or found):
            p.update_evolution()
            p.update_evolution()
        return p.evolution_failed, len(tried)

    def test_a_win_rate_pet_tries_once(self):
        self.assertEqual(self.check([WIN_RATE]), (True, 1))

    def test_a_pet_without_one_keeps_trying(self):
        self.assertEqual(self.check([BATTLES]), (False, 2))

    def test_the_android_copy_agrees(self):
        p = AndroidPetRules.__new__(AndroidPetRules)
        p.name, p.module, p.evolve = "Greymon", "TEST", [WIN_RATE]
        p._evol_minutes, p.time, p.evolution_failed = 10, 5, False
        p.world = SimpleNamespace(log=Mock())
        p.need_care = lambda: False
        p.find_evolution = Mock(return_value=None)
        p.update_evolution()
        p.update_evolution()
        self.assertTrue(p.evolution_failed)
        self.assertEqual(p.find_evolution.call_count, 1)

    def test_a_new_form_starts_unfailed(self):
        """evolve_to and devolve run reset_variables: items, Level Reverse,
        jogress and armor all evolve through them."""
        src = (ROOT / 'src' / 'models' / 'game_pet.py').read_text(encoding='utf-8')
        reset = src[src.index("    def reset_variables(self):"):]
        reset = reset[:reset.index("\n    def ", 10)]
        self.assertIn("self.evolution_failed = False", reset)
        for caller in ("    def evolve_to(", "    def devolve("):
            body = src[src.index(caller):]
            body = body[:body.index("\n    def ", 10)]
            self.assertIn("self.reset_variables()", body, caller)


if __name__ == '__main__':
    unittest.main()
