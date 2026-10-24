"""Building Smash, the iC 10X's minigame (owner, 2026-10-06).

It runs every minigame's phases: READY, the charge (the minigame itself, in
steps), the result (BAD to EXCELLENT) and the currency screen. Played on a
clock the test moves, so every rule measured off the owner's video -- the
cursor's run, the bar's widths, the stage speeds, the prizes -- is checked
without waiting for it.
"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SRC = os.path.join(REPO_ROOT, "src")
for path in (SRC, REPO_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

import pygame  # noqa: E402

from core import game_globals, runtime_globals  # noqa: E402
from training import building_smash, ic_minigame, training  # noqa: E402
from training.building_smash import (  # noqa: E402
    APEX_MAX, APEX_MIN, BURSTS, BuildingSmash, STEP_MS, TARGETS)

FIGHT_MONEY = {"name": "Fight Money", "unit": "P", "cap": 9999}


class FakePet:
    """Hashable, as a pet is: runtime_globals.pet_sprites is keyed by pet.
    It has no ``finish_training``: a bonus minigame must not train."""

    def __init__(self, **fields):
        self.__dict__.update(fields)


def ic_pet(**fields):
    pet = FakePet(module="IC", hunger=3, stage=3, atk_main=1, atk_alt=0, atk_alt_2=0,
                  reliability=15, _apply_reliability_event=mock.Mock())
    pet.__dict__.update(fields)
    return pet


def quiet_sound():
    """The mixer as the game sees it with sound off: READY runs on time."""
    return SimpleNamespace(play=mock.Mock(return_value=None), get_duration=lambda name: 0,
                           stop=lambda name: None, is_playing=lambda name: False)


class BuildingSmashTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.chdir(REPO_ROOT)         # sprites load from repo-relative paths
        pygame.init()
        pygame.display.set_mode((240, 240))

    def setUp(self):
        self.now = 0
        self.pet = ic_pet()
        self.other = FakePet(module="DMC", hunger=3)
        self.sound = quiet_sound()
        self.distribute = mock.Mock()
        targets = [self.pet, self.other]
        patches = [
            mock.patch.object(pygame.time, "get_ticks", side_effect=lambda: self.now),
            mock.patch.object(training, "get_training_targets", return_value=targets),
            mock.patch.object(ic_minigame, "get_training_targets", return_value=targets),
            mock.patch.object(training, "distribute_pets_evenly", self.distribute),
            mock.patch.object(runtime_globals, "game_sound", self.sound),
            mock.patch.object(runtime_globals, "game_state", "training"),
            mock.patch.object(runtime_globals, "game_modules", {
                "IC": SimpleNamespace(currencies=[FIGHT_MONEY],
                                      training_uses_battle_cost=True, battle_cost_type="Hunger",
                                      battle_cost_amount=1,  # the iC's heart a play
                                      folder_path=os.path.join(REPO_ROOT, "modules", "IC")),
                "DMC": SimpleNamespace(currencies=[],
                                       folder_path=os.path.join(REPO_ROOT, "modules", "DMC"))}),
            mock.patch.object(game_globals, "currency", {}),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        from ui.ui_manager import UIManager
        self.game = BuildingSmash(UIManager("GREEN"))

    # -- driving -------------------------------------------------------

    def tick(self, ms=10):
        self.now += ms
        self.game.update()

    def ready(self):
        """Through READY into the charge."""
        for _ in range(10000):
            if self.game.phase != "alert":
                break
            self.tick()
        self.assertEqual(self.game.phase, "charge")

    def run_until(self, step=None, phase=None, limit=20000):
        end = self.now + limit
        while not ((step and self.game.phase == "charge" and self.game.step == step)
                   or (phase and self.game.phase == phase)):
            self.assertLess(self.now, end, f"never reached {step or phase}; at "
                                           f"{self.game.phase}/{self.game.step}")
            self.tick()

    def stop_at(self, apex):
        """Wait for the cursor to reach *apex* and press A."""
        self.assertEqual((self.game.phase, self.game.step), ("charge", "aim"))
        while self.game.apex() != apex:
            self.now += 1
        self.game.handle_event(("A", None))

    def clear_stage(self):
        for first, last in TARGETS:
            self.stop_at((first + last) // 2)
            self.assertTrue(self.game.hit)
            self.run_until("aim" if self.game.stop < 2 else "pet")
        self.run_until("burst")

    # -- the phases ----------------------------------------------------

    def test_only_ic_digimon_play_and_each_play_costs_a_heart(self):
        self.assertEqual(self.game.pets, [self.pet])
        self.assertEqual(self.pet.hunger, 2)
        self.assertEqual(self.other.hunger, 3)

    def test_it_starts_with_ready(self):
        self.assertEqual(self.game.phase, "alert")
        self.sound.play.assert_not_called()
        self.game.update()
        self.sound.play.assert_called_with(training.TRAINING_READY_SOUND)
        self.game.handle_event(("A", None))
        self.assertEqual(self.game.phase, "alert", "READY cannot be skipped")
        self.ready()
        self.assertEqual(self.game.step, "aim")

    def test_a_miss_ends_the_charge_with_the_stages_cleared(self):
        self.ready()
        self.clear_stage()
        self.run_until("aim")
        self.stop_at(APEX_MIN)
        self.run_until(phase="result")
        self.assertEqual(self.game.get_attack_count(), 1, "one stage: GOOD")
        self.assertEqual(self.game.prize, 10)
        self.assertFalse(self.game.succeeded)

    def test_the_result_then_the_currency_screen(self):
        self.ready()
        self.clear_stage()
        self.run_until("aim")
        self.stop_at(APEX_MIN)
        self.run_until(phase="currency")
        self.assertEqual(self.game.earnings, [("IC", "Fight Money", 10)])
        self.assertEqual(game_globals.currency, {"IC": {"Fight Money": 10}})
        self.pet._apply_reliability_event.assert_not_called()
        self.assertEqual(runtime_globals.game_state, "training")
        for _ in range(training.CURRENCY_SCREEN_FRAMES + 1):
            self.tick()
        self.assertEqual(runtime_globals.game_state, "game")
        self.distribute.assert_called_once()

    def test_a_button_leaves_the_currency_screen(self):
        self.ready()
        self.clear_stage()
        self.run_until("aim")
        self.stop_at(APEX_MIN)
        self.run_until(phase="currency")
        self.game.handle_event(("A", None))
        self.assertEqual(runtime_globals.game_state, "game")

    def test_nothing_earned_skips_the_currency_screen(self):
        self.ready()
        self.stop_at(APEX_MIN)
        self.run_until(phase="result")
        self.assertEqual(self.game.get_attack_count(), 0, "BAD")
        while runtime_globals.game_state != "game":
            self.assertNotEqual(self.game.phase, "currency")
            self.tick()
        self.assertEqual(game_globals.currency, {})
        played = [c.args[0] for c in self.sound.play.call_args_list]
        self.assertIn("ic_fail", played, "the iC's own fail sound")
        self.assertNotIn("ic_success", played)

    def test_three_stages_are_excellent_pay_50_and_raise_reliability(self):
        self.ready()
        for stage in range(3):
            self.clear_stage()
            self.run_until("after" if stage < 2 else "won")
            if stage < 2:
                self.run_until("aim")
        self.run_until(phase="result")
        self.assertEqual(self.game.get_attack_count(), 3, "EXCELLENT")
        self.sound.play.assert_called_with("ic_success")
        self.run_until(phase="currency")
        self.assertEqual(game_globals.currency, {"IC": {"Fight Money": 50}})
        self.pet._apply_reliability_event.assert_called_once_with("reliability_minigame_success")

    def test_b_in_the_charge_leaves_without_pay(self):
        self.ready()
        self.clear_stage()
        self.game.handle_event(("B", None))
        self.assertEqual(runtime_globals.game_state, "game")
        self.assertEqual(game_globals.currency, {})
        self.assertEqual(self.pet.hunger, 2, "the heart stays spent")

    # -- the rules -----------------------------------------------------

    def test_the_cursor_runs_right_and_back(self):
        self.ready()
        start = self.now
        self.assertEqual(self.game.apex(), APEX_MIN)
        span = APEX_MAX - APEX_MIN
        self.now = start + STEP_MS[0] * span
        self.assertEqual(self.game.apex(), APEX_MAX)
        self.now = start + STEP_MS[0] * (span + 1)
        self.assertEqual(self.game.apex(), APEX_MAX - 1)
        self.now = start + STEP_MS[0] * 2 * span
        self.assertEqual(self.game.apex(), APEX_MIN)

    def test_the_bar_narrows_and_a_stop_beside_it_misses(self):
        self.assertEqual(TARGETS, ((13, 18), (14, 17), (15, 16)))
        self.ready()
        self.stop_at(18)
        self.assertTrue(self.game.hit)
        self.run_until("aim")
        self.stop_at(17)
        self.assertTrue(self.game.hit)
        self.run_until("aim")
        self.stop_at(17)                # the video's two misses
        self.assertFalse(self.game.hit)
        self.run_until(phase="result")

    def test_each_stage_is_faster(self):
        self.assertEqual(STEP_MS, (100, 67, 32))
        self.ready()
        self.clear_stage()
        self.run_until("aim")
        self.assertEqual((self.game.stage, self.game.stop), (1, 0))
        self.now += STEP_MS[1] * 5
        self.assertEqual(self.game.apex(), APEX_MIN + 5)

    def test_the_building_breaks_a_stage_at_a_time(self):
        self.ready()
        self.clear_stage()
        self.assertEqual([name for name, _ in BURSTS],
                         ["building_explosion_1", "building_explosion_2"] * 2)
        self.assertNotIn("ic_building_break", [c.args[0] for c in self.sound.play.call_args_list])
        self.run_until("after")
        self.assertEqual(self.game.stage, 0)
        self.assertEqual(self.game.cleared, 1)
        played = [c.args[0] for c in self.sound.play.call_args_list]
        self.assertEqual(played.count("ic_building_break"), 1, "the blast, once a building")

    # -- drawing -------------------------------------------------------

    def test_art_is_drawn_in_its_files_colours(self):
        """Nothing is tinted (owner, 2026-10-06): the buildings and bursts
        are coloured in their files, the cursor screen black."""
        def colours(surface):
            return {tuple(surface.get_at((x, y))) for x in range(surface.get_width())
                    for y in range(surface.get_height()) if surface.get_at((x, y)).a}
        for name in ("building_1", "building_2", "building_3",
                     "building_explosion_1", "building_explosion_2"):
            used = colours(self.game.art(name))
            self.assertGreater(len(used), 3, name)
            self.assertNotIn((0, 0, 0, 255), used, f"{name} is still the black original")
        for name in ("building_bar", "building_target_1", "building_cursor"):
            self.assertEqual(colours(self.game.art(name)), {(0, 0, 0, 255)}, name)

    def test_every_phase_draws(self):
        runtime_globals.pet_sprites[self.pet] = [
            pygame.Surface((48, 48), pygame.SRCALPHA) for _ in range(16)]
        self.addCleanup(runtime_globals.pet_sprites.pop, self.pet, None)
        surface = pygame.Surface((240, 240))
        seen = set()
        with mock.patch.object(building_smash.ic_attacks, "attack_ids", return_value=(1, 0)):
            self.game.update()
            self.game.draw(surface)
            self.ready()
            for stage in range(3):
                for first, last in TARGETS:
                    self.game.draw(surface)
                    self.stop_at((first + last) // 2)
                    while self.game.phase == "charge" and self.game.step != "aim":
                        seen.add(self.game.step)
                        self.game.draw(surface)
                        self.tick(50)
            while runtime_globals.game_state != "game":
                seen.add(self.game.phase)
                self.game.draw(surface)
                self.tick(50)
        self.assertTrue({"hold", "pet", "fire", "approach", "burst", "after", "won",
                         "result", "currency"} <= seen)
        rect = self.game.lcd_rect()
        self.assertEqual((rect.width, rect.x), (192, 24))


if __name__ == "__main__":
    unittest.main()
