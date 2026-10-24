"""Every stroke of a pixel font is drawn the same width (owner, 2026-10-20).

The game's fonts are pixel fonts: vpet_font is 13 pixels to the em, ProggySmall
16 and DigimonBasic 12. Drawn at any other size, FreeType rounds each pixel of
the design to a different whole number of canvas pixels, so one letter gets a
2-pixel stroke beside a 1-pixel one -- the owner's report was the "n" of
"#1  not obtained" on the card screen, get_font(FONT_SIZE_SMALL) = vpet_font
at 24 on a 240 canvas. font_load now draws a pixel font at its native size
and enlarges the text by a whole number, so each design pixel is one same-size
block, at every resolution the game supports.

Also covered: vpet_font's outlines are on its grid (1-3 font units of noise
used to give some letters a 6-pixel advance instead of 5, "obtaine d"), and
the measurements (size, get_height) describe what render draws.
"""

import os
import string
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SRC = os.path.join(REPO_ROOT, "src")
for path in (SRC, REPO_ROOT, os.path.join(REPO_ROOT, "tests", "release")):
    if path not in sys.path:
        sys.path.insert(0, path)

import pygame  # noqa: E402

from core import constants, runtime_globals  # noqa: E402
from ui.ui_constants import TEXT_FONT, TITLE_FONT  # noqa: E402
from utils import asset_utils  # noqa: E402
from utils.asset_utils import font_load, pixel_font_size  # noqa: E402
from scene_sweep import RESOLUTIONS  # noqa: E402

#: The owner's examples, and every printable character the game writes.
SAMPLES = ["#1  not obtained", "Modules", "Module: DMC, Version: 1",
           "COLLECTION 0123456789", string.printable[:95]]

_saved_globals = {}


def setUpModule():
    _saved_globals.update({name: value for name, value in vars(runtime_globals).items()
                           if name.isupper() and isinstance(value, (int, float))})
    os.chdir(REPO_ROOT)  # fonts load from repo-relative paths
    pygame.init()
    pygame.display.set_mode((240, 240))
    # Fonts cached before another module's pygame.quit() are dangling, and
    # rendering through one is an access violation (see test_rpm).
    asset_utils._font_cache.clear()


def tearDownModule():
    for name, value in _saved_globals.items():
        setattr(runtime_globals, name, value)
    asset_utils._font_cache.clear()
    pygame.quit()


def rgb(surface):
    """The surface's pixels as bytes, ink white on black."""
    flat = pygame.Surface(surface.get_size(), depth=24)
    flat.fill((0, 0, 0))
    flat.blit(surface, (0, 0))
    return pygame.image.tostring(flat, "RGB")


def blocky(surface, scale):
    """Whether the ink is made of whole ``scale`` x ``scale`` blocks: every
    stroke of every glyph is then a whole number of design pixels wide."""
    ink = surface.get_bounding_rect()
    if not ink.width:
        return True
    if ink.width % scale or ink.height % scale:
        return False
    cropped = surface.subsurface(ink)
    small = pygame.transform.scale(cropped, (ink.width // scale, ink.height // scale))
    return rgb(pygame.transform.scale(small, ink.size)) == rgb(cropped)


def design_scale(path, font):
    """How many canvas pixels one design pixel of ``font`` should be: its
    line size over the font's own at its native size. Measured, so the check
    holds whatever way the text is drawn."""
    native = asset_utils.PIXEL_FONT_SIZES[os.path.basename(path).lower()]
    base = pygame.font.Font(path, native).get_linesize()
    return max(1, round(font.get_linesize() / base))


def game_fonts():
    """(what, path, size asked) for the text the game draws at the current
    resolution, as the call sites ask for it."""
    from ui.ui_manager import UIManager
    from ui.minigames import count_bar
    ui = UIManager("GREEN")
    scale = runtime_globals.UI_SCALE
    return [
        ("get_font SMALL", constants.FONT_TTF_PATH, runtime_globals.FONT_SIZE_SMALL),
        ("get_font MEDIUM", constants.FONT_TTF_PATH, runtime_globals.FONT_SIZE_MEDIUM),
        ("get_font MEDIUM_LARGE", constants.FONT_TTF_PATH, runtime_globals.FONT_SIZE_MEDIUM_LARGE),
        ("get_font LARGE", constants.FONT_TTF_PATH, runtime_globals.FONT_SIZE_LARGE),
        ("get_font 16 * UI_SCALE", constants.FONT_TTF_PATH, int(16 * scale)),
        ("Label text", TEXT_FONT, ui.get_text_font_size()),
        ("TitleScene", TEXT_FONT, ui.scale_value(24)),
        ("text 24 * UI_SCALE", TEXT_FONT, int(24 * scale)),
        ("Label title", TITLE_FONT, ui.get_title_font_size()),
        ("count bar", TITLE_FONT, count_bar.LABEL_FONT_SIZE * ui.ui_scale),
    ]


class EvenStrokesTests(unittest.TestCase):

    def test_every_text_path_at_every_resolution(self):
        for res in RESOLUTIONS:
            width, height = (int(v) for v in res.split("x"))
            runtime_globals.update_resolution_constants(width, height)
            for what, path, size in game_fonts():
                font = font_load(path, size)
                scale = design_scale(path, font)
                for text in SAMPLES:
                    with self.subTest(res=res, font=what, size=size, text=text):
                        self.assertTrue(blocky(font.render(text, False, (255, 255, 255)), scale),
                                        "strokes of different widths")

    def test_the_owner_s_example(self):
        """The card screen's line on a 240 canvas: the "n" has two strokes and
        a top of one width, 2 pixels (vpet_font's 13 doubled)."""
        runtime_globals.update_resolution_constants(240, 240)
        font = font_load(constants.FONT_TTF_PATH, runtime_globals.FONT_SIZE_SMALL)
        self.assertEqual((font.get_height() // font.scale, font.scale), (14, 2))
        line = font.render("#1  not obtained", False, (255, 255, 255))
        self.assertTrue(blocky(line, 2))
        n = font.render("n", False, (255, 255, 255), (0, 0, 0))
        rows = ["".join("#" if n.get_at((x, y))[0] else "." for x in range(n.get_width()))
                for y in range(n.get_height())]
        inked = [row for row in rows if "#" in row]
        top, legs = inked[0], inked[-1]
        self.assertEqual([len(run) for run in legs.split(".") if run], [2, 2], "the n's two legs")
        self.assertEqual(sum(1 for row in inked if row == top), 2, "the n's top")


class FontLoadTests(unittest.TestCase):

    def setUp(self):
        runtime_globals.update_resolution_constants(240, 240)

    def test_sizes_snap_to_the_nearest_whole_multiple(self):
        cases = [
            (constants.FONT_TTF_PATH, 24, (13, 2)),
            (constants.FONT_TTF_PATH, 28, (13, 2)),
            (constants.FONT_TTF_PATH, 40, (13, 3)),
            (TEXT_FONT, 16, (16, 1)),
            (TEXT_FONT, 24, (16, 1)),   # a tie goes to the smaller: never wider
            (TEXT_FONT, 25, (16, 2)),
            (TEXT_FONT, 48, (16, 3)),
            (TITLE_FONT, 24, (12, 2)),
            (TITLE_FONT, 36, (12, 3)),
        ]
        for path, size, expected in cases:
            with self.subTest(path=path, size=size):
                self.assertEqual(pixel_font_size(path, size), expected)
        self.assertIsNone(pixel_font_size(None, 24))
        self.assertIsNone(pixel_font_size("assets/some_other_font.ttf", 24))

    def test_the_floor_holds_in_whole_multiples(self):
        """min_font_size() is 16 * UI_SCALE; a pixel font keeps the whole
        multiples of its native size that holds."""
        self.assertEqual(pixel_font_size(TEXT_FONT, 8, floor=32), (16, 2))
        self.assertEqual(pixel_font_size(TEXT_FONT, 32, floor=42), (16, 2))
        runtime_globals.update_resolution_constants(480, 480)
        self.assertEqual(font_load(TEXT_FONT, 8).scale, 2)
        self.assertEqual(font_load(constants.FONT_TTF_PATH, 8).scale, 2)

    def test_measurements_describe_the_rendered_text(self):
        for path in (constants.FONT_TTF_PATH, TEXT_FONT, TITLE_FONT):
            for size in (16, 24, 48):
                font = font_load(path, size)
                for text in SAMPLES:
                    with self.subTest(path=path, size=size, text=text):
                        surface = font.render(text, False, (255, 255, 255))
                        self.assertEqual(font.size(text), surface.get_size())
                        # SDL_ttf draws some DigimonBasic lines a pixel
                        # taller than get_height (its line size): enlarged.
                        self.assertIn(surface.get_height(),
                                      (font.get_height(), font.get_linesize()))
                        self.assertEqual(font.get_linesize() % font.scale, 0)

    def test_symbols_keep_their_half_pixel_detail(self):
        """ProggySmall draws its symbols in half pixels: the item list's
        infinity, stars, arrows. Drawn at the native 16 and enlarged they
        became blobs, so text with any of them is drawn at the full size."""
        font = font_load(TEXT_FONT, 48)
        self.assertEqual(font.scale, 3)
        for text in ("\u221e", "\u2605 Lv 3", "\u2191\u2193 Select"):
            with self.subTest(text=text):
                full = pygame.font.Font(TEXT_FONT, 48).render(text, False, (255, 255, 255))
                drawn = font.render(text, False, (255, 255, 255))
                self.assertEqual(rgb(drawn), rgb(full))
                self.assertEqual(font.size(text), drawn.get_size())

    def test_vpet_font_letters_keep_their_design_advance(self):
        """These letters are 5 design pixels wide, spacing included. Off-grid
        outline points gave many of them 6 (an extra gap before "d")."""
        font = font_load(constants.FONT_TTF_PATH, 13)
        self.assertEqual(font.scale, 1)
        for word in ("abcdefghknopqrsuvyz", "ABCDEFGHJKLPQRSU", "023456789"):
            with self.subTest(word=word):
                self.assertEqual(font.size(word)[0], 5 * len(word))


class MissingGlyphTests(unittest.TestCase):
    """The title font (DigimonBasic) has no ' ` [ ] |: they drew as a box, so
    a team named "Tamer's Team" read "TAMER[box]S TEAM" (2026-10-22 doc
    pass). Such characters are substituted; fonts that have them keep them."""

    def test_the_title_font_drops_what_it_cannot_draw(self):
        font = font_load(TITLE_FONT, 22)
        self.assertEqual(font.size("TAMER'S TEAM"), font.size("TAMERS TEAM"))
        self.assertEqual(font.size("[A|B]"), font.size("(A/B)"))

    def test_fonts_that_have_them_keep_them(self):
        for path in (TEXT_FONT, constants.FONT_TTF_PATH):
            with self.subTest(font=os.path.basename(path)):
                font = font_load(path, 16)
                self.assertNotEqual(font.size("A'B"), font.size("AB"))


class ShadowTests(unittest.TestCase):
    """Pixel-font text is an 8-bit surface whose background is a colour key.
    Its drop shadow was a solid box in the text's colour (owner, 2026-10-21:
    the connect scene's Omninet and Discord sections "blanked out")."""

    def test_a_text_shadow_is_the_text_shape(self):
        from utils.pygame_utils import blit_with_shadow, get_shadow
        text = font_load(constants.FONT_TTF_PATH, 26).render("Discord", False, (226, 49, 49))
        self.assertEqual(text.get_bitsize(), 8)
        shadow = get_shadow(text)
        self.assertEqual(shadow.get_at((0, 0)).a, 0, "the background stays transparent")
        inked = [(x, y) for x in range(text.get_width()) for y in range(text.get_height())
                 if text.get_at((x, y))[:3] == (226, 49, 49)]
        self.assertTrue(inked)
        self.assertTrue(all(shadow.get_at(p)[:3] == (0, 0, 0) and shadow.get_at(p).a for p in inked))

        canvas = pygame.Surface((text.get_width() + 2, text.get_height() + 2), pygame.SRCALPHA)
        blit_with_shadow(canvas, text, (0, 0))
        covered = sum(1 for x in range(canvas.get_width()) for y in range(canvas.get_height())
                      if canvas.get_at((x, y)).a)
        self.assertLess(covered, canvas.get_width() * canvas.get_height() // 2,
                        "the label is text, not a filled box")


if __name__ == "__main__":
    unittest.main()
