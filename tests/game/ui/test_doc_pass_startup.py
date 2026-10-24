# -*- coding: utf-8 -*-
"""Start-up fixes from the 2026-10-22 documentation pass, in the running game.

43  egg selection: with modules installed but none with an egg the text no
    longer says "No modules installed"; RANDOM picks only a category that has
    a module and, in Progress Mode, only a module the player owns (never the
    Tutorial)
44  NO MODULE DETECTED offers A: Retry, and the error screen's Retry and its
    switch to Free Mode really start the boot again ("boot" was missing from
    the scene map, so both did nothing)
45  setup: at the "Press B" prompt the device's default B maps B instead of
    aborting the mapping; cancelling the graphics result restores the frame
    rate the test raised
46  the tutorial's touch SKIP skips as START does, and finishing the tutorial
    unloads its module
"""
import os
import random
import sys
import unittest
from unittest.mock import patch

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "support"))
MODULES = os.path.join(REPO_ROOT, "modules")


@unittest.skipUnless(os.path.exists(os.path.join(MODULES, "DMC", "module.json")), "modules/ is gitignored")
class DocPassStartup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness import Env
        cls.env = Env("240x240")

    def setUp(self):
        self.env.reset()
        self.gg, self.rg = self.env.gg, self.env.rg

    # ------------------------------------------------------------ 43
    def test_random_picks_only_what_the_player_owns(self):
        from scenes.scene_eggselection import SceneEggSelection
        from utils import navigation_utils
        owned = {"DMC"}
        with patch.object(self.gg, "is_progress_mode", return_value=True), \
                patch.object(self.gg, "is_free_mode", return_value=False), \
                patch.object(self.gg.purchases, "owns_module_name", side_effect=lambda n: n in owned), \
                patch.object(navigation_utils, "has_owned_modules", return_value=True):
            for seed in range(25):
                random.seed(seed)
                scene = self.env.game("egg", SceneEggSelection).scene
                scene.on_random_selection()
                if scene.phase in ("egg_selection", "device_selection"):
                    picked = scene.available_modules[scene.current_module_index]
                    self.assertEqual(picked, "DMC", f"seed {seed}")
                # And the fallback of an empty category lists owned modules only.
                scene.load_available_modules("NoSuchCategory")
                self.assertEqual(set(scene.available_modules), owned)

    def test_no_egg_text_does_not_say_no_modules(self):
        from scenes.scene_eggselection import SceneEggSelection
        with patch.object(SceneEggSelection, "_has_any_modules_with_eggs", return_value=False):
            scene = self.env.game("egg", SceneEggSelection).scene
        self.assertEqual(scene.phase, "no_modules")
        texts = " ".join(str(getattr(c, "text", "")) for c in scene.ui_manager.components)
        self.assertNotIn("No modules installed", texts)
        self.assertIn("No installed module has an egg", texts)

    # ------------------------------------------------------------ 44
    def test_no_module_detected_retries_the_boot(self):
        from scenes import scene_boot
        from scenes.scene_boot import SceneBoot
        from scenes.scene_error import SceneError
        from utils import navigation_utils
        with patch.object(navigation_utils, "has_modules_installed", return_value=False), \
                patch.object(scene_boot, "check_internet_connection", return_value=False), \
                patch.object(self.gg, "has_game_mode_preference", return_value=True), \
                patch.object(self.gg, "is_progress_mode", return_value=False):
            self.gg.setup_input = self.gg.setup_graphics = False
            boot = self.env.game("boot")
            boot.scene.transition_to_next_scene()
        self.assertEqual(SceneError.error_message, "NO MODULE DETECTED")
        self.assertEqual(SceneError.action_a, ("boot", "Retry"))
        game = self.env.game("error")
        self.env.frames(game, 1)
        self.env.press(game, "A")
        self.env.frames(game, 1)
        self.assertIsInstance(game.scene, SceneBoot, "Retry starts the boot again")

    def test_switching_to_free_mode_from_the_error_loads_its_save(self):
        from scenes.scene_boot import SceneBoot
        from scenes.scene_error import SceneError
        from utils import display_utils
        SceneError.set_error(message="SERVER: down", action_a=("boot", "Retry"),
                             action_b=("switch_free", "Free Mode"))
        game = self.env.game("error")
        self.env.frames(game, 1)
        with patch.object(display_utils, "load_preserving_display") as load, \
                patch.object(self.gg, "save_game_mode_preference"), \
                patch.object(self.gg, "migrate_legacy_saves"):
            self.env.press(game, "B")
            self.env.press(game, "A")
            self.env.frames(game, 1)
        self.assertTrue(load.called, "the Free Mode save is loaded")
        self.assertIsInstance(game.scene, SceneBoot)

    # ------------------------------------------------------------ 45
    def setup_scene(self):
        from scenes.scene_setup import SceneSetup
        return self.env.game("setup", SceneSetup).scene

    def test_the_default_b_maps_b_at_its_prompt(self):
        import pygame
        scene = self.setup_scene()
        scene.phase = "input_mapping"
        scene.detected_input_type = "keyboard"
        scene.temp_keyboard_map = {}
        scene.current_button_index = scene.INPUT_BUTTONS.index("B")
        consumed = scene.handle_raw_pygame_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
        self.assertTrue(consumed)
        self.assertEqual(scene.phase, "input_mapping", "the mapping goes on")
        self.assertEqual(scene.temp_keyboard_map.get("B"), "K_ESCAPE")
        # At any other prompt Escape still skips.
        with patch.object(scene, "skip_input_setup") as skip:
            scene.handle_raw_pygame_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
        self.assertTrue(skip.called)

    def test_cancelling_the_graphics_result_restores_the_frame_rate(self):
        scene = self.setup_scene()
        cfg = self.gg.configuration
        cfg.frame_rate = 30
        scene.start_graphics_test()
        cfg.frame_rate = 60                  # what the test raised it to
        scene.complete_graphics_test()
        with patch.object(scene, "complete_setup"):
            scene.reject_graphics_settings()
        self.assertEqual(cfg.frame_rate, 30)

    # ------------------------------------------------------------ 46
    def test_the_tutorial_skip_and_end_clean_up(self):
        from scenes.scene_tutorial import SceneTutorial
        scene = SceneTutorial.__new__(SceneTutorial)
        scene.tutorial_module = type("M", (), {"name": "Tutorial"})()
        scene.original_pet_list = list(self.gg.pet_list)
        scene.original_poop_list = list(self.gg.poop_list or [])
        scene.embedded_scene = None
        self.rg.game_modules["Tutorial"] = scene.tutorial_module
        try:
            with patch("utils.navigation_utils.route_to_next_scene"):
                scene.complete_tutorial()
            self.assertNotIn("Tutorial", self.rg.game_modules, "finishing unloads the module")
        finally:
            self.rg.game_modules.pop("Tutorial", None)
        import inspect
        source = inspect.getsource(SceneTutorial.__init__)
        self.assertIn("SkipOverlay(on_skip=self.skip_tutorial)", source)


if __name__ == "__main__":
    unittest.main()
