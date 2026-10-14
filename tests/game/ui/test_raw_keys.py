"""Physical keys reach every scene without errors (UI-01).

Found by the Pi scripts (tests/platform/pi/smoke.py, finding P-02): Backspace
(keyboard START) was handed to the scene as a raw pygame event so a focused
text field could delete a character, and 8 of 21 scenes, which take input
tuples only, raised TypeError - START never arrived from a keyboard there.
VirtualPetGame.handle_event now offers the raw key only while a text field has
focus. Every scene is entered and given real key events through the game's own
event handler.
"""
import os
import sys
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "support"))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "release"))
MODULES = os.path.join(REPO_ROOT, "modules")


@unittest.skipUnless(os.path.isdir(MODULES), "modules folder not present")
class RawKeys(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness import Env
        cls.env = Env("240x240")

    def test_backspace_and_the_arrows_reach_every_scene(self):
        import pygame
        from harness import quiet
        from scene_sweep import SCENES
        keys = (pygame.K_BACKSPACE, pygame.K_UP, pygame.K_RETURN, pygame.K_ESCAPE)
        for name in SCENES:
            with self.subTest(scene=name):
                self.env.reset(input_mode=self.env.rg.KEYBOARD_MODE)
                game = self.env.game(name)
                self.env.frames(game, 3)
                for key in keys:
                    with quiet():
                        game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key, mod=0, unicode=""))
                    self.env.frames(game, 2)
                    if name != "error" and type(game.scene).__name__ == "SceneError":
                        self.fail(f"{name}: key {pygame.key.name(key)} reached the error scene")


if __name__ == "__main__":
    unittest.main()
