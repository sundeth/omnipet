"""First-run Setup on Android skips the input steps unless a controller is connected.

Owner, 2026-10-17 (release decision 11): the input-detection steps configure
physical controls, so a phone without a gamepad has nothing to map there and
goes straight on; with a controller attached the steps are shown, as on
desktop. `SceneSetup.start_input_intro` decides it (`_is_touch_mode`, which
is true on Android, and `_has_mappable_input_device`, the joystick count).
"""
import os
import sys
import unittest
from unittest.mock import patch

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "support"))
MODULES = os.path.join(REPO_ROOT, "modules")


@unittest.skipUnless(os.path.isdir(MODULES), "modules folder not present")
class AndroidSetupInput(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness import Env
        cls.env = Env("240x240")

    def setUp(self):
        self.env.reset()

    def start_input_intro(self, joysticks):
        import pygame
        from harness import quiet
        game = self.env.game("setup")
        scene = game.scene
        with quiet(), patch.object(self.env.rg, "IS_ANDROID", True), \
                patch.object(pygame.joystick, "get_count", lambda: joysticks), \
                patch.object(type(scene), "skip_input_setup") as skipped:
            scene.start_input_intro()
        return scene, skipped

    def test_a_phone_without_a_controller_skips_the_input_steps(self):
        scene, skipped = self.start_input_intro(joysticks=0)
        skipped.assert_called_once()
        self.assertNotEqual(scene.phase, "input_intro")

    def test_a_phone_with_a_controller_shows_them(self):
        scene, skipped = self.start_input_intro(joysticks=1)
        skipped.assert_not_called()
        self.assertEqual(scene.phase, "input_intro")


if __name__ == "__main__":
    unittest.main()
