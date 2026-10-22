"""The holo foil of a shiny card (`ui.card_holo`, owner 2026-10-20): "a
holographic effect on the artwork only (a mask so the card frame/border is
untouched): a semi-transparent texture whose colour shifts over time, like a
real holo card", cheap enough for the Pi Zero 2W (no per-pixel alpha, no
per-frame numpy or smoothscale; frames made once per card size and kept).
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SRC = os.path.join(REPO_ROOT, "src")
for path in (SRC, REPO_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

import pygame  # noqa: E402

from core import runtime_globals  # noqa: E402
from ui import card_holo  # noqa: E402

TEXTURE = os.path.join(REPO_ROOT, card_holo.HOLO_TEXTURE)
ID_PLATE = {"id": "a", "type": "iD Plate"}


def setUpModule():
    pygame.display.init()
    pygame.display.set_mode((8, 8))


class HoloTests(unittest.TestCase):
    def setUp(self):
        card_holo.clear_cache()
        card_holo._texture_failed = False
        for patcher in (patch.object(card_holo, "HOLO_TEXTURE", TEXTURE),
                        patch.object(runtime_globals, "game_console", SimpleNamespace(log=Mock()),
                                     create=True)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(card_holo.clear_cache)

    def card_on_screen(self, size=(51, 81)):
        """A grey 'card' on a black screen, drawn at (10, 10)."""
        screen = pygame.Surface((80, 110))
        screen.fill((0, 0, 0))
        screen.fill((90, 90, 90), pygame.Rect((10, 10), size))
        return screen, pygame.Rect((10, 10), size)

    def test_the_art_window_of_each_card_layout(self):
        self.assertEqual(card_holo.art_window(ID_PLATE, 205, 325), pygame.Rect(32, 30, 166, 166))
        self.assertEqual(card_holo.art_window({"type": "Collectible"}, 300, 360),
                         pygame.Rect(10, 10, 280, 306))
        # Scaled down, the window is rounded inward: never onto the frame.
        small = card_holo.art_window(ID_PLATE, 51, 81)
        self.assertGreaterEqual(small.left, 32 * 51 / 205)
        self.assertLessEqual(small.right, (32 + 166) * 51 / 205)
        self.assertGreaterEqual(small.top, 30 * 81 / 325)
        self.assertLessEqual(small.bottom, (30 + 166) * 81 / 325)
        other = card_holo.art_window({"type": "Custom"}, 100, 100)
        self.assertTrue(pygame.Rect(0, 0, 100, 100).contains(other))
        self.assertGreater(other.left, 0)

    def test_only_the_art_changes(self):
        screen, rect = self.card_on_screen()
        before = screen.copy()
        card_holo.draw_holo(screen, ID_PLATE, rect, ticks=0)
        window = card_holo.art_window(ID_PLATE, rect.width, rect.height).move(rect.topleft)
        changed = 0
        for x in range(screen.get_width()):
            for y in range(screen.get_height()):
                if screen.get_at((x, y)) != before.get_at((x, y)):
                    self.assertTrue(window.collidepoint(x, y), f"the holo touched ({x}, {y})")
                    changed += 1
        self.assertGreater(changed, window.width * window.height // 2, "the art shimmers")

    def test_the_colours_shift_over_time(self):
        pictures = []
        for ticks in (0, card_holo.HOLO_CYCLE_MS // 3, card_holo.HOLO_CYCLE_MS):
            screen, rect = self.card_on_screen()
            card_holo.draw_holo(screen, ID_PLATE, rect, ticks=ticks)
            pictures.append(pygame.image.tostring(screen, "RGB"))
        self.assertNotEqual(pictures[0], pictures[1], "the foil moves")
        self.assertEqual(pictures[0], pictures[2], "and comes round again")

    def test_frames_are_made_once_and_cheap_to_draw(self):
        screen, rect = self.card_on_screen()
        window = card_holo.art_window(ID_PLATE, rect.width, rect.height)
        variant = card_holo.card_seed(ID_PLATE) % card_holo.HOLO_VARIANTS
        card_holo.draw_holo(screen, ID_PLATE, rect, ticks=0)
        frames = card_holo.holo_frames(window.width, window.height, 1, variant)
        self.assertIs(card_holo.holo_frames(window.width, window.height, 1, variant), frames)
        frame = frames[0]
        self.assertEqual(frame.get_size(), window.size)
        self.assertFalse(frame.get_flags() & pygame.SRCALPHA, "no per-pixel alpha to blend")
        with patch.object(pygame.transform, "smoothscale", side_effect=AssertionError("scaled")), \
                patch.object(pygame.transform, "scale", side_effect=AssertionError("scaled")):
            card_holo.draw_holo(screen, ID_PLATE, rect, ticks=0)
        self.assertIs(frames[0], frame, "the frame is kept")

    def test_the_texture_keeps_its_pixel_size_at_each_ui_scale(self):
        one, two = card_holo._texture(1), card_holo._texture(2)
        self.assertEqual(two.get_width(), one.get_width() * 2)
        self.assertEqual(two.get_at((3, 5)), one.get_at((1, 2)))

    def test_a_missing_texture_draws_nothing(self):
        with patch.object(card_holo, "HOLO_TEXTURE", os.path.join(REPO_ROOT, "missing.png")):
            screen, rect = self.card_on_screen()
            before = pygame.image.tostring(screen, "RGB")
            card_holo.draw_holo(screen, ID_PLATE, rect, ticks=0)
            card_holo.draw_holo(screen, ID_PLATE, rect, ticks=0)
        self.assertEqual(pygame.image.tostring(screen, "RGB"), before)
        self.assertEqual(runtime_globals.game_console.log.call_count, 1, "logged once")


if __name__ == "__main__":
    unittest.main()
