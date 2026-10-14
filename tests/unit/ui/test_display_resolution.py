"""The render canvas and the scaling constants must never disagree.

The game draws SCREEN_WIDTH x SCREEN_HEIGHT pixels into
``runtime_globals.render_surface`` and the canvas is then scaled onto the
window whole, so a canvas larger than the constants puts the game in the
top-left corner of the screen over the stale remains of the previous frame.

Android is where that bites: the render resolution comes from the device
screen before any save has been read, while the display fields in a save
describe whichever device wrote it.  A login (or a game-mode switch) applies
the save's configuration, and until the configuration was told what Android
actually chose, that call shrank the game into the corner.
"""
import os
import pickle
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'src'))

import pygame

from core import runtime_globals, game_globals
from models.game_configuration import GameConfiguration
from utils import display_utils

DEVICE = (2800, 1280)          # a phone, landscape
GAME = (1400, 640)             # half of it: what main_android renders at


def android_boot(screen):
    """What main_android does once the display is up."""
    width, height = screen.get_size()
    game_width = (width // 2) & ~1
    game_height = (height // 2) & ~1
    cfg = game_globals.configuration
    cfg.fullscreen = True
    cfg.window_width, cfg.window_height = width, height
    cfg.screen_width, cfg.screen_height = game_width, game_height
    cfg.base_resolution_width, cfg.base_resolution_height = game_width, game_height
    cfg.resolution_multiplyer = 1
    runtime_globals.update_resolution_constants(game_width, game_height)
    runtime_globals.render_surface = pygame.Surface((game_width, game_height))
    return game_width, game_height


def write_save(save_root, config):
    folder = os.path.join(save_root, "Default")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "save_data_1.dat"), "wb") as fh:
        pickle.dump({"configuration": config.to_dict(),
                     "pet_list": [], "poop_list": []}, fh)


def desktop_config():
    """A save written on a PC: windowed, 640x640."""
    cfg = GameConfiguration()
    cfg.setup_for_system("PC")
    return cfg


def stale_android_config():
    """A save written before Android recorded its own resolution."""
    cfg = GameConfiguration()
    cfg.setup_for_system("Linux")
    cfg.screen_width, cfg.screen_height = 525, 240
    cfg.window_width, cfg.window_height = 525, 240
    return cfg


class DisplayResolutionTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        pygame.init()
        cls.screen = pygame.display.set_mode(DEVICE)

    def setUp(self):
        self.save_root = tempfile.mkdtemp()
        self._base_dir = game_globals._get_base_save_dir
        self._can_access = game_globals._can_access_save_dir
        self._mode = game_globals.game_mode
        self._android = runtime_globals.IS_ANDROID
        self._configuration = game_globals.configuration
        game_globals._get_base_save_dir = lambda: self.save_root
        game_globals._can_access_save_dir = lambda: True
        game_globals.game_mode = game_globals.GAME_MODE_FREE
        game_globals.configuration = GameConfiguration()

    def tearDown(self):
        game_globals._get_base_save_dir = self._base_dir
        game_globals._can_access_save_dir = self._can_access
        game_globals.game_mode = self._mode
        game_globals.configuration = self._configuration
        runtime_globals.IS_ANDROID = self._android
        shutil.rmtree(self.save_root, ignore_errors=True)

    def assert_canvas_matches(self, expected):
        self.assertEqual(
            (runtime_globals.SCREEN_WIDTH, runtime_globals.SCREEN_HEIGHT), expected,
            "scaling constants left the device resolution")
        self.assertEqual(
            runtime_globals.render_surface.get_size(), expected,
            "the canvas no longer matches what the game draws")

    def test_android_keeps_its_resolution_through_a_foreign_save(self):
        """A login loads a save from another device; the phone's screen wins."""
        runtime_globals.IS_ANDROID = True
        write_save(self.save_root, desktop_config())
        self.assertEqual(android_boot(self.screen), GAME)

        display_utils.load_keeping_device_display()     # boot
        self.assert_canvas_matches(GAME)
        display_utils.load_preserving_display()         # login completes
        self.assert_canvas_matches(GAME)
        display_utils.load_preserving_display()         # game-mode switch
        self.assert_canvas_matches(GAME)
        self.assertTrue(game_globals.configuration.fullscreen,
                        "a windowed save must not take a phone out of fullscreen")

    def test_the_save_keeps_reporting_the_resolution_it_was_written_at(self):
        """Poops hold absolute pixels, so the boot scene needs the old size."""
        runtime_globals.IS_ANDROID = True
        write_save(self.save_root, stale_android_config())
        android_boot(self.screen)
        display_utils.load_keeping_device_display()
        self.assertEqual(runtime_globals.save_render_resolution, (525, 240))
        self.assert_canvas_matches(GAME)

    def test_a_mismatched_canvas_is_rebuilt_rather_than_drawn_into(self):
        runtime_globals.IS_ANDROID = True
        android_boot(self.screen)
        cfg = game_globals.configuration
        cfg.screen_width, cfg.screen_height = 525, 240
        display_utils.ensure_render_surface_matches()
        self.assertEqual(runtime_globals.render_surface.get_size(), (525, 240))

    def test_android_render_multiplier_never_shrinks_as_it_rises(self):
        """1x is the half-native canvas, so 2x must be larger, and capped."""
        runtime_globals.IS_ANDROID = True
        android_boot(self.screen)
        sizes = []
        for multiplier in (1, 2, 3, 4):
            display_utils.apply_render_multiplier(multiplier)
            sizes.append(runtime_globals.render_surface.get_size())
        self.assertEqual(sizes[0], GAME)
        self.assertEqual(sizes[1], DEVICE)
        # Held at the device's own pixels rather than allocating past them.
        self.assertEqual(sizes[2], DEVICE)
        self.assertEqual(sizes[3], DEVICE)
        for smaller, larger in zip(sizes, sizes[1:]):
            self.assertGreaterEqual(larger[0] * larger[1], smaller[0] * smaller[1])

    def test_desktop_multiplier_ladder_is_unchanged(self):
        runtime_globals.IS_ANDROID = False
        cfg = game_globals.configuration
        cfg.fullscreen = True
        cfg.window_width, cfg.window_height = DEVICE
        # In fullscreen the base is always re-derived from the screen, so it
        # is 240-based however large the display is.
        expected_base = cfg.compute_base_resolution(*DEVICE)
        runtime_globals.render_surface = pygame.Surface(expected_base)
        for multiplier in (1, 2, 3, 4):
            display_utils.apply_render_multiplier(multiplier)
            base = (cfg.base_resolution_width, cfg.base_resolution_height)
            self.assertEqual(base, expected_base)
            self.assertEqual((cfg.screen_width, cfg.screen_height),
                             (base[0] * multiplier, base[1] * multiplier))
            self.assert_canvas_matches((cfg.screen_width, cfg.screen_height))


if __name__ == "__main__":
    unittest.main()
