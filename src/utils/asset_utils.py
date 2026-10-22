import os
import pygame
from core import runtime_globals

def image_load(rel_path: str):
    """
    Load an image file, adjusting path for Android environment.
    On Android, builds absolute path from APP_ROOT.
    On desktop, uses relative path as-is.
    
    Args:
        rel_path: Relative path to image (e.g., 'assets/ui/button.png')
    
    Returns:
        pygame.Surface: Loaded image
    """
    if runtime_globals.IS_ANDROID and runtime_globals.APP_ROOT:
        full_path = os.path.join(runtime_globals.APP_ROOT, rel_path)
        return pygame.image.load(full_path)
    else:
        return pygame.image.load(rel_path)

def sound_load(rel_path: str):
    """
    Load a sound file, adjusting path for Android environment.
    On Android, builds absolute path from APP_ROOT.
    On desktop, uses relative path as-is.
    
    Args:
        rel_path: Relative path to sound (e.g., 'assets/dmc_sounds/1.wav')
    
    Returns:
        pygame.mixer.Sound: Loaded sound
    """
    if runtime_globals.IS_ANDROID and runtime_globals.APP_ROOT:
        full_path = os.path.join(runtime_globals.APP_ROOT, rel_path)
        return pygame.mixer.Sound(full_path)
    else:
        return pygame.mixer.Sound(rel_path)

def resolve_path(rel_path: str) -> str:
    """
    Resolve a file path for Android environment.
    On Android, builds absolute path from APP_ROOT.
    On desktop, uses relative path as-is.
    
    Args:
        rel_path: Relative path to file
    
    Returns:
        str: Resolved absolute or relative path
    """
    if runtime_globals.IS_ANDROID and runtime_globals.APP_ROOT:
        return os.path.join(runtime_globals.APP_ROOT, rel_path)
    else:
        return rel_path

#: The game's pixel fonts, by file name: the size (pixels per em) at which one
#: pixel of the font's design is one pixel of the canvas. At any other size
#: FreeType rounds each design pixel to a different whole number of pixels, so
#: the strokes of one letter come out 1 and 2 pixels wide (the "n" of "not" at
#: vpet_font 24: owner report, 2026-10-20). font_load draws these fonts at this
#: size and enlarges the text by a whole number instead.
PIXEL_FONT_SIZES = {
    "vpet_font.ttf": 13,     # 1300 units per em, 100 per pixel
    "proggysmall.ttf": 16,   # 2048 units per em, 128 per pixel
    "digimonbasic.ttf": 12,  # traced outlines, about 87 units per pixel
}


def pixel_font_size(rel_path, size, floor=0):
    """``(native size, scale)`` a pixel font is drawn at when ``size`` is asked
    for, or None for a font that is not in PIXEL_FONT_SIZES.

    The scale is the whole multiple of the native size nearest to ``size``; a
    tie goes to the smaller one, which is never wider than what was asked
    for. It is at least 1, and at least the largest multiple that fits within
    ``floor`` (min_font_size).
    """
    if not rel_path:
        return None
    native = PIXEL_FONT_SIZES.get(os.path.basename(rel_path).lower())
    if not native:
        return None
    nearest = (2 * int(size) + native - 1) // (2 * native)
    return native, max(1, int(floor) // native, nearest)


class _PixelFont(pygame.font.Font):
    """The game's font: always renders without anti-aliasing.

    Omnipet is pixel-art, so text is drawn with sharp pixels (anti-aliasing
    makes it blurry, especially once the low-res canvas is scaled up).  The
    antialias argument callers pass is ignored.

    A pixel font (PIXEL_FONT_SIZES) is opened at its native size and
    everything it renders or measures is multiplied by ``scale``, so each
    pixel of the design becomes the same ``scale`` x ``scale`` block.

    Only ASCII is on that grid: ProggySmall draws its symbols (the item
    list's infinity, stars, arrows) in half pixels, which the native size
    turns into blobs. Text with any other character is drawn by FreeType at
    the full size instead, as it was before the grid was enforced.
    """

    def __init__(self, path, size, scale=1):
        super().__init__(path, size)
        self.scale = scale
        self._path = path
        self._native_size = size
        self._full_size_font = None

    def _full_size(self, text):
        """The font at ``scale`` times the native size, for text that is not
        all ASCII; None when the native size draws it."""
        if self.scale == 1 or not isinstance(text, (str, bytes)) or text.isascii():
            return None
        if self._full_size_font is None:
            self._full_size_font = pygame.font.Font(self._path, self._native_size * self.scale)
        return self._full_size_font

    def render(self, text, antialias=False, color=(255, 255, 255), bgcolor=None):
        font = self._full_size(text)
        if font is not None:
            if bgcolor is not None:
                return font.render(text, False, color, bgcolor)
            return font.render(text, False, color)
        if bgcolor is not None:
            surface = super().render(text, False, color, bgcolor)
        else:
            surface = super().render(text, False, color)
        if self.scale > 1:
            width, height = surface.get_size()
            surface = pygame.transform.scale(
                surface, (width * self.scale, height * self.scale))
        return surface

    def size(self, text):
        font = self._full_size(text)
        if font is not None:
            return font.size(text)
        width, height = super().size(text)
        return width * self.scale, height * self.scale

    def get_height(self):
        return super().get_height() * self.scale

    def get_linesize(self):
        return super().get_linesize() * self.scale

    def get_ascent(self):
        return super().get_ascent() * self.scale

    def get_descent(self):
        return super().get_descent() * self.scale

    def metrics(self, text):
        font = self._full_size(text)
        if font is not None:
            return font.metrics(text)
        return [m if m is None else tuple(v * self.scale for v in m)
                for m in super().metrics(text)]


_font_cache = {}

#: Text smaller than this is unreadable on the device screen. 16 * UI_SCALE is
#: what a plain Label renders at (ui_constants.TEXT_FONT_SIZES), which is the
#: size the status screen draws "Stage:" and "Age:" at — the smallest type the
#: game is allowed to use. Enforced here because this is the one function every
#: font in the game is built through, so no call site can undercut it.
#: A pixel font only has to reach the largest whole multiple of its native
#: size that fits within the floor (pixel_font_size): at 1x vpet_font's 13 has
#: the same 7-pixel capitals as ProggySmall's 16, and where UI_SCALE is
#: fractional (1400x640: floor 42) a Label stays at the 32 its UI scale lays
#: it out for.
def min_font_size() -> int:
    return max(1, int(16 * runtime_globals.UI_SCALE))


def font_load(rel_path: str, size: int):
    """
    Load a font file, adjusting path for Android environment.
    On Android, builds absolute path from APP_ROOT.
    On desktop, uses relative path as-is.
    Pass None as rel_path to use pygame's default font.

    Sizes below ``min_font_size()`` are raised to it. A pixel font
    (PIXEL_FONT_SIZES) is drawn at the whole multiple of its native size
    nearest to ``size`` instead (pixel_font_size), so every stroke has the
    same width.

    Args:
        rel_path: Relative path to font file (e.g., 'assets/DigimonBasic.ttf') or None for default
        size: Font size in pixels

    Returns:
        pygame.font.Font: Loaded font
    """
    floor = min_font_size()
    if size is None or size <= 0:
        size = floor  # Default size if zero provided
    scale = 1
    grid = pixel_font_size(rel_path, size, floor)
    if grid:
        size, scale = grid
    else:
        size = max(floor, int(size))

    # Fonts are immutable in this codebase (nothing calls set_bold/italic),
    # so share one Font per (path, size, scale) — constructing a Font opens
    # the TTF from disk, and several draw paths request fonts every frame.
    key = (rel_path, size, scale)
    font = _font_cache.get(key)
    if font is not None:
        return font

    if runtime_globals.IS_ANDROID and runtime_globals.APP_ROOT and rel_path:
        full_path = os.path.join(runtime_globals.APP_ROOT, rel_path)
        font = _PixelFont(full_path, size, scale)
    else:
        font = _PixelFont(rel_path, size, scale)
    _font_cache[key] = font
    return font

def open_json(rel_path: str, mode='r', encoding='utf-8'):
    """
    Open a JSON file, adjusting path for Android environment.
    On Android, builds absolute path from APP_ROOT.
    On desktop, uses relative path as-is.
    
    Args:
        rel_path: Relative path to JSON file
        mode: File open mode (default 'r')
        encoding: File encoding (default 'utf-8')
    
    Returns:
        File handle
    """
    resolved_path = resolve_path(rel_path)
    return open(resolved_path, mode, encoding=encoding)
