# -*- coding: utf-8 -*-
"""ICX-10 / ICX-01 in the running game: the iC rules that need a scene.

The real game, headless (tests/support/harness.py), the harness party with
its iC Digimon (Agumon, 10X). A minute passes for the iC pet by moving its
minute clock back 60 s and running a frame of the main scene, which updates
every pet as the game loop does.

    death save by B (60)    at 30 injuries the pet is dying; 60 B presses, or
                            60 taps in the pet area, within 30 seconds save
                            it if its 1-in-20 roll comes up (held here); 59
                            do not (scenes.scene_maingame)
    flush disturbs sleep    cleaning the screen wakes the napping pet: a
                            sleep disturbance and its ten minutes back to
                            sleep (care_flush_disturbance_sleep)
    lights off answers      putting the pet to bed from the sleep scene during
    the bedtime call        its bedtime call is Reliability +1 (ICX-01)
    no Strength meter       the Status screen shows Reliability in Strength's
                            slot for the iC pet, Strength for the DMC pet
    stomach tooltip         the iC pet's hunger tooltip reads hunger/stomach
                            ("Stomach" in visible_stats); the DMC pet's does not

Checklist: ICX-10, ICX-01 (release-1.0.md).
"""
import os
import sys
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "support"))
MODULES = os.path.join(REPO_ROOT, "modules")


@unittest.skipUnless(os.path.exists(os.path.join(MODULES, "IC", "module.json")), "modules/ is gitignored")
class ICCareInGame(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness import Env
        cls.env = Env("240x240")

    def setUp(self):
        from models.game_pet import GamePet
        env = self.env
        env.reset(input_mode=env.rg.TOUCH_MODE)
        self.gg, self.rg = env.gg, env.rg
        self.ic = next(p for p in self.gg.pet_list if p.module == "IC")
        self.bedtime = set()                  # pets whose bedtime it is
        sleep = patch.object(GamePet, "should_sleep", lambda pet: pet in self.bedtime)
        sleep.start()
        self.addCleanup(sleep.stop)

    def minute(self, game, pet=None):
        """One minute for *pet* (the iC pet), applied by a frame of the scene."""
        pet = pet or self.ic
        pet._rt_origin = time.monotonic() - 60 * (pet._rt_last_minute + 1) - 0.5
        self.env.frames(game, 1)

    def seconds(self, game, seconds=0.5, pet=None):
        """*seconds* on *pet*'s real-time clock (the death save's), applied
        by a frame of the scene."""
        pet = pet or self.ic
        pet._rt_last_sleep_check = time.monotonic() - seconds
        self.env.frames(game, 1)

    def hold(self, pet=None):
        """Stop *pet*'s real-time clock until seconds() moves it, so the
        presses below take no time off the save."""
        (pet or self.ic)._rt_last_sleep_check = time.monotonic() + 3600

    @staticmethod
    def lucky():
        """The death save's survival roll comes up (the iC's 1 in 20)."""
        return patch("models.game_pet.random.random", return_value=0.0)

    def dying_pet(self):
        env = self.env
        self.ic.injury_total = 30
        game = env.game("game")
        env.frames(game, 2)
        self.minute(game)
        self.assertTrue(self.ic.dying)
        self.assertEqual(self.ic.death_save_b_counter, 60)
        self.assertIn("death", env.sounds)
        return game

    def press(self, game, event, times):
        from harness import quiet
        with quiet():
            for _ in range(times):
                game.scene.handle_event(event)
                self.env.frames(game, 1)

    # ------------------------------------------------------------ death save
    def test_sixty_b_presses_save_a_dying_pet(self):
        game = self.dying_pet()
        self.hold()
        self.press(game, ("B", None), 60)
        with self.lucky():
            self.seconds(game)
        self.assertEqual(self.ic.death_save_b_counter, 0)
        self.assertFalse(self.ic.dying)
        self.assertEqual((self.ic.state, self.ic.injury_total), ("happy2", 29))
        self.assertIn("happy", self.env.sounds)
        self.assertEqual(self.env.error_logs(), [])

    def test_fifty_nine_presses_are_not_enough(self):
        game = self.dying_pet()
        self.hold()
        self.press(game, ("B", None), 59)
        self.seconds(game, 30)
        self.assertEqual(self.ic.state, "dead")

    def test_taps_in_the_pet_area_count_as_presses(self):
        import pygame
        game = self.dying_pet()
        pet = self.ic
        spot = (self.rg.SCREEN_WIDTH // 2, pet.y + self.rg.PET_HEIGHT // 2)
        self.assertTrue(game.scene.is_mouse_in_pet_area(spot))
        self.hold()
        for _ in range(60):
            self.env.tap(game, spot)
            self.env.frames(game, 1)
        with self.lucky():
            self.seconds(game)
        self.assertFalse(pet.dying)
        self.assertNotEqual(pet.state, "dead")

    # ------------------------------------------------------------ flush
    def test_flushing_wakes_the_sleeping_pet(self):
        from models.game_poop import GamePoop
        env = self.env
        pet = self.ic
        game = env.game("game")
        env.frames(game, 2)
        pet.set_state("nap")
        pet.nap_until = datetime.now() + timedelta(days=1)   # no natural wake-up
        self.gg.poop_list[:] = [GamePoop(pet.x, pet.y)]
        disturbances = pet.sleep_disturbances
        game.scene.start_cleaning()
        for _ in range(300):
            env.frames(game, 1)
            if not game.scene.cleaning:
                break
        self.assertFalse(game.scene.cleaning, "the wash crossed the screen")
        self.assertEqual(self.gg.poop_list, [])
        self.assertNotEqual(pet.state, "nap")
        self.assertEqual(pet.sleep_disturbances, disturbances + 1)
        self.assertEqual(pet.back_to_sleep, 10)

    # ------------------------------------------------------------ status
    def test_the_status_screen_shows_reliability_in_place_of_strength(self):
        env = self.env
        dmc = next(p for p in self.gg.pet_list if p.module == "DMC")
        self.ic.reliability = 23
        game = env.game("status")
        env.frames(game, 2)
        scene = game.scene
        scene.on_pet_selected(self.ic)
        env.frames(game, 2)
        self.assertTrue(scene.reliability_meter.visible)
        self.assertFalse(scene.strength_meter.visible, "the iC has no Strength meter")
        self.assertEqual(scene.reliability_meter.value, 23)
        scene.on_pet_selected(dmc)
        env.frames(game, 2)
        self.assertFalse(scene.reliability_meter.visible)
        self.assertTrue(scene.strength_meter.visible)
        self.assertEqual(env.error_logs(), [])

    def test_the_hunger_tooltip_gives_the_stomach_fill(self):
        """"Stomach" in the iC's visible_stats (owner, 2026-10-17): four fixed
        hearts hide a stomach of up to 15, so the hunger tooltip gives the
        fill as current/max. A module without it keeps the plain text."""
        from scenes.scene_status import HUNGER_TOOLTIP
        env = self.env
        dmc = next(p for p in self.gg.pet_list if p.module == "DMC")
        self.ic.stomach, self.ic.hunger = 15, 9
        game = env.game("status")
        env.frames(game, 2)
        scene = game.scene
        scene.on_pet_selected(self.ic)
        env.frames(game, 2)
        self.assertTrue(scene.hunger_meter.tooltip_text.startswith("Hunger 9/15"),
                        scene.hunger_meter.tooltip_text)
        scene.on_pet_selected(dmc)
        env.frames(game, 2)
        self.assertEqual(scene.hunger_meter.tooltip_text, HUNGER_TOOLTIP)
        self.assertEqual(env.error_logs(), [])

    # ------------------------------------------------------------ lights off
    def test_lights_off_during_the_bedtime_call_gives_reliability(self):
        env = self.env
        pet = self.ic
        self.rg.selected_pets = [pet]
        self.bedtime.add(pet)
        main = env.game("game")
        env.frames(main, 2)
        self.minute(main)                     # one minute into the call
        self.assertTrue(pet.call_sign())
        before = pet.reliability
        game = env.game("sleepmenu")
        env.frames(game, 3)
        env.tap(game, game.scene.sleep_button.rect.center)
        env.frames(game, 90)                  # the lights-off animation, then back to the game
        self.assertEqual(pet.state, "nap")
        self.assertEqual(pet.reliability, before + 1)
        self.assertEqual(self.rg.game_state, "game")


if __name__ == "__main__":
    unittest.main()
