"""
Card holo
=========

The holographic finish of a shiny card: a foil whose colours sweep across
the card's artwork, the way a real holo card shimmers as it turns in the
light. Only the art window is covered; the frame and border stay as printed.

The foil is the shard texture `assets/ui/Card_Holo.png` (160x160, scaled down
from the owner's texture, 2026-10-20) with its contrast raised, multiplied by
a diagonal rainbow with one brighter glint band, and added onto the art
(BLEND_RGB_ADD) at HOLO_STRENGTH. Each frame of the sweep is made the first
time it shows, once per art-window size, and kept, so drawing a holo card
costs one additive blit of its window: no per-pixel alpha (the Pi Zero 2W's
pygame has no NEON blitters), no per-frame scaling or numpy. The texture is
scaled by whole UI steps, so its shards keep their pixel size at every
resolution.

A card's art window is where its picture shows inside the frame, kept as a
fraction of the card sprite (ART_WINDOWS): measured on the Database card
maker's iD Plate (205x325, art 166x166 at 32,30) and on Digimon World's
cards (300x360, art 280x306 at 10,10). Any other type keeps a thin margin.
"""

import colorsys
import math
import zlib

import pygame

from core import runtime_globals
from utils.asset_utils import image_load

HOLO_TEXTURE = "assets/ui/Card_Holo.png"
#: Frames in one sweep of the colours, and how long the sweep takes.
HOLO_FRAMES = 24
HOLO_CYCLE_MS = 2400
#: How strongly the foil lights the art (0-1), how saturated its rainbow is,
#: and how bright its glint band.
HOLO_STRENGTH = 0.45
HOLO_SATURATION = 0.7
HOLO_GLINT = 0.8
#: The texture's shards are stretched apart: (pixel - floor) * 2.
HOLO_CONTRAST_FLOOR = 110
#: Crops of the texture (and starts of the sweep), so neighbouring cards
#: never shimmer as one.
HOLO_VARIANTS = 4

#: Card type -> art window (x, y, w, h) on a card of (width, height).
ART_WINDOWS = {
    "iD Plate": ((32, 30, 166, 166), (205, 325)),
    "Collectible": ((10, 10, 280, 306), (300, 360)),
}
#: Any other type: the card less a thin margin (fractions of the card).
DEFAULT_WINDOW = (0.06, 0.05, 0.88, 0.90)

_MAX_CACHED = 24        # window sizes x variants kept
_frames_cache = {}      # (w, h, scale, variant) -> [Surface] * HOLO_FRAMES
_texture_cache = {}     # scale -> the boosted texture at that scale
_texture_failed = False


def card_seed(card) -> int:
    """A stable number for a card (its variant): the same every run."""
    return zlib.crc32(str((card or {}).get("id") or (card or {}).get("name") or "").encode("utf-8"))


def art_window(card, width, height) -> pygame.Rect:
    """The art window of *card* inside its sprite of width x height, as a
    Rect relative to the sprite. Rounded inward, so the scaled frame's edge
    is never covered."""
    spec = ART_WINDOWS.get((card or {}).get("type"))
    if spec:
        (x, y, w, h), (cw, ch) = spec
        fx, fy, fw, fh = x / cw, y / ch, w / cw, h / ch
    else:
        fx, fy, fw, fh = DEFAULT_WINDOW
    left = math.ceil(fx * width - 1e-6)
    top = math.ceil(fy * height - 1e-6)
    right = int((fx + fw) * width + 1e-6)
    bottom = int((fy + fh) * height + 1e-6)
    return pygame.Rect(left, top, max(0, right - left), max(0, bottom - top))


def _texture(scale):
    """The foil texture, its contrast raised, at a whole UI scale."""
    global _texture_failed
    if scale in _texture_cache:
        return _texture_cache[scale]
    if _texture_failed:
        return None
    base = _texture_cache.get(1)
    if base is None:
        try:
            base = image_load(HOLO_TEXTURE).convert()
        except Exception as exc:
            _texture_failed = True
            runtime_globals.game_console.log(f"[CardHolo] {HOLO_TEXTURE} failed to load: {exc}")
            return None
        floor = HOLO_CONTRAST_FLOOR
        base.fill((floor, floor, floor), special_flags=pygame.BLEND_RGB_SUB)
        base.blit(base.copy(), (0, 0), special_flags=pygame.BLEND_RGB_ADD)
        _texture_cache[1] = base
    if scale > 1:
        w, h = base.get_size()
        _texture_cache[scale] = pygame.transform.scale(base, (w * scale, h * scale))
    return _texture_cache[scale]


def _sweep(width, height, period):
    """A diagonal rainbow one period wider than the window: every frame of
    the sweep is this strip, shifted left."""
    strip = pygame.Surface((width + period, height))
    for i in range(-height, width + period + 1):
        pos = (i % period) / period
        r, g, b = colorsys.hsv_to_rgb(pos, HOLO_SATURATION, 1.0)
        light = 0.70 + HOLO_GLINT * max(0.0, math.cos((pos - 0.5) * 2 * math.pi)) ** 8
        colour = tuple(min(255, int(c * 255 * light)) for c in (r, g, b))
        # A 45-degree line holds exactly the pixels with x - y == i.
        pygame.draw.line(strip, colour, (i, 0), (i + height, height))
    return strip


class _Sweep:
    """One window's foil and rainbow strip, and the frames of its sweep,
    each made the first time it is shown (so a card coming into view costs
    one frame's making, not the whole sweep's, on the Pi)."""

    def __init__(self, foil, strip, period):
        self.foil, self.strip, self.period = foil, strip, period
        self.frames = [None] * HOLO_FRAMES

    def __len__(self):
        return HOLO_FRAMES

    def __getitem__(self, n):
        frame = self.frames[n]
        if frame is None:
            frame = self.foil.copy()
            frame.blit(self.strip, (-(n * self.period // HOLO_FRAMES), 0),
                       special_flags=pygame.BLEND_RGB_MULT)
            level = int(255 * HOLO_STRENGTH)
            frame.fill((level, level, level), special_flags=pygame.BLEND_RGB_MULT)
            self.frames[n] = frame
        return frame


def holo_frames(width, height, scale=1, variant=0):
    """The HOLO_FRAMES frames of a window's sweep (each made once, then
    kept), or None when the texture is missing."""
    key = (width, height, scale, variant)
    frames = _frames_cache.get(key)
    if frames is not None:
        return frames
    texture = _texture(scale)
    if texture is None or width <= 0 or height <= 0:
        return None
    # The foil: the texture tiled from this variant's corner.
    tw, th = texture.get_size()
    ox, oy = (variant % 2) * tw // 2, (variant // 2 % 2) * th // 2
    foil = pygame.Surface((width, height))
    for ty in range(-oy, height, th):
        for tx in range(-ox, width, tw):
            foil.blit(texture, (tx, ty))
    # The variants of one window share its rainbow.
    period = max(8, int((width + height) * 0.9))
    strip = next((s.strip for (w, h, _s, _v), s in _frames_cache.items()
                  if (w, h) == (width, height)), None) or _sweep(width, height, period)
    frames = _Sweep(foil, strip, period)
    if len(_frames_cache) >= _MAX_CACHED:
        _frames_cache.pop(next(iter(_frames_cache)))
    _frames_cache[key] = frames
    return frames


def draw_holo(surface, card, rect, scale=1, ticks=None):
    """Draw *card*'s holo over its art: *rect* is where its sprite was drawn,
    *scale* the whole UI scale (the texture's pixel size)."""
    window = art_window(card, rect.width, rect.height).move(rect.topleft)
    if window.width < 2 or window.height < 2:
        return
    variant = card_seed(card) % HOLO_VARIANTS
    frames = holo_frames(window.width, window.height, max(1, int(scale)), variant)
    if not frames:
        return
    if ticks is None:
        ticks = pygame.time.get_ticks()
    step = max(1, HOLO_CYCLE_MS // HOLO_FRAMES)
    index = (ticks // step + variant * HOLO_FRAMES // HOLO_VARIANTS) % HOLO_FRAMES
    surface.blit(frames[index], window.topleft, special_flags=pygame.BLEND_RGB_ADD)


def clear_cache():
    """Drop the made frames (e.g. after a resolution change)."""
    _frames_cache.clear()
    _texture_cache.clear()
