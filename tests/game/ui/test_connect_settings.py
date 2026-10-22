# -*- coding: utf-8 -*-
"""Connect > CONFIG: the Omninet and Discord sections in both game modes.

The owner (2026-10-21) saw both sections "blanked out" in Free Mode: every
shadowed label was drawn as a solid box (utils/pygame_utils.get_shadow on
the pixel font's 8-bit text; tests/unit/ui/test_pixel_text.py). Free Mode
has no Omninet account, so its row says "Free Mode" and the button switches
the game mode; Discord does not need Progress Mode.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "online"))
from online_ui import button, labels, tap_button  # noqa: E402


class ConnectSettings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness import Env
        cls.env = Env("240x240")

    def open_config(self, free):
        env = self.env
        env.reset(input_mode=env.rg.TOUCH_MODE)
        env.gg.game_mode = env.gg.GAME_MODE_FREE if free else env.gg.GAME_MODE_PROGRESS
        game = env.game("connect")
        env.frames(game, 2)
        menu = game.scene.current_view
        menu._on_config_selected()
        env.frames(game, 3)
        return game, menu

    def test_free_mode_names_itself_and_offers_the_switch(self):
        env = self.env
        game, menu = self.open_config(free=True)
        self.assertIn("Free Mode", labels(game))
        switch = button(game, "SWITCH MODE")
        self.assertIsNotNone(switch, "no SWITCH MODE button")
        self.assertTrue(switch.enabled)
        self.assertTrue(button(game, "LINK").enabled, "Discord works in any mode")
        tap_button(env, game, "SWITCH MODE", frames=0)
        self.assertTrue(env.gg.setup_game_mode, "the game-mode choice was not opened")
        self.assertEqual(env.rg.game_state, "setup")
        env.frames(game, 1)
        self.assertEqual(type(game.scene).__name__, "SceneSetup")

    def test_progress_mode_shows_the_account(self):
        game, _menu = self.open_config(free=False)
        self.assertIn("Account: None", labels(game))
        self.assertIsNotNone(button(game, "CONNECT"))
        self.assertIsNone(button(game, "SWITCH MODE"))
        self.assertTrue(button(game, "LINK").enabled)

    def test_the_section_titles_are_text_not_blocks(self):
        for free in (True, False):
            with self.subTest(free=free):
                game, menu = self.open_config(free)
                for label in (menu.config_omninet_title_label, menu.config_discord_title_label,
                              menu.config_discord_status_label):
                    surface = label.cached_surface or label.render()
                    width, height = surface.get_size()
                    inked = sum(1 for x in range(width) for y in range(height)
                                if surface.get_at((x, y)).a)
                    self.assertLess(inked, width * height * 0.6, f"{label.text!r} is a filled box")


if __name__ == "__main__":
    unittest.main()
