"""Every training minigame plays from its menu button to the end, in touch mode.

Found by tests/release/menu_crawl.py (2026-10-13): Count Match
Color crashed when its charge ended, because the Pendulum Color battle rows
run six rounds and the training draws five waves. Each minigame here is
entered by tapping its button and then tapped once a second until the scene
leaves its phase; none may raise.
"""
import os
import sys
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "support"))
MODULES = os.path.join(REPO_ROOT, "modules")


@unittest.skipUnless(os.path.isdir(MODULES), "modules folder not present")
class TrainingPlaysThrough(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness import Env
        cls.env = Env("240x240")

    def play(self, key):
        from harness import quiet
        from scenes.scene_training import TRAINING_MODES
        env = self.env
        env.reset(input_mode=env.rg.TOUCH_MODE)
        need = TRAINING_MODES[key].get("min_targets", 1)
        env.rg.selected_pets = list(env.gg.pet_list[:max(1, need)])
        game = env.game("training")
        env.frames(game, 4)
        scene = game.scene
        button = scene.mode_buttons[key]
        while not button.visible:            # the second page
            with quiet():
                scene.on_more()
            env.frames(game, 2)
        env.tap(game, button.rect.center)
        env.frames(game, 10)
        phase = TRAINING_MODES[key]["phase"]
        self.assertEqual(getattr(game.scene, "phase", None), phase, f"{key} did not start")
        from harness import focusables
        for _ in range(90):                  # up to 90 s of play, a second at a time
            scene = game.scene
            # a tap on the screen, then on each of the minigame's own buttons
            # (Head to Head is played with on-screen UP/DOWN); never EXIT
            taps = [(120, 120)] + [c.rect.center for c in focusables(scene)
                                   if c is not getattr(scene, "training_exit_button", None)]
            for pos in taps:
                env.tap(game, pos)
                env.frames(game, 30 // len(taps) or 1)
            if getattr(game.scene, "phase", None) != phase:
                break
        return getattr(game.scene, "phase", None) != phase

    def test_every_minigame_finishes_without_raising(self):
        """By touch alone each minigame reaches its end and returns to the menu."""
        from scenes.scene_training import TRAINING_MODES
        for key in TRAINING_MODES:
            with self.subTest(minigame=key):
                self.assertTrue(self.play(key), f"{key} never finished within 90 s of play")


if __name__ == "__main__":
    unittest.main()
