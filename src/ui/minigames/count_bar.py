"""
Count Bar Minigame

The Digimon Mini's charge, and **only** the Mini's. The player presses A (or
clicks) as fast as they can for five seconds while a row of eight bars fills
one bar per four presses; then the screen changes and the count it reached is
shown. The count is the whole result -- it picks the attack pattern.

It runs in two steps, as the device does:

  * **COUNT!** -- `CountMatch1.png`, five seconds, the bars filling. No number
    on screen: the player is counting, not reading.
  * **the result** -- `CountMatch2.png`, two seconds, the count shown between
    its brackets. Presses no longer register here; the count is settled.

This used to draw `assets/RPM.png` and a live counter, which is the Digivice
iC's screen and not this one. The two devices charge differently -- the iC
measures a RATE against the Digimon's own RPM target -- and the mixture was
neither. The iC's is `ui.minigames.rpm`.

It has no ready screen of its own; the ordinary animated READY plays first.

Every position is given on the 240x240 layout at 1x and scaled from there.
"""
import pygame

from core import runtime_globals
from ui.ui_constants import TITLE_FONT
from utils.asset_utils import font_load
from utils.pygame_utils import blit_with_cache


#: How long the player has to press.
DURATION_MS = 5000
#: How long the count is then shown for, before the charge is over.
RESULT_MS = 2000

BAR_COUNT = 8
PRESSES_PER_BAR = 4
#: The counter's own limit, which is ours: enough that no player reaches it,
#: and short enough to stay inside the display box.
MAX_COUNT = 99

#: Step 1 says COUNT!; step 2 carries the brackets the number sits in.
COUNTING_PATH = "assets/CountMatch1.png"
RESULT_PATH = "assets/CountMatch2.png"

#: The gap between `CountMatch2.png`'s brackets, measured off the sprite:
#: the left bracket ends at x 83 and the right begins at 156, and the row of
#: marks they sit in runs from y 56 to 97. The count is centred in that
#: space by its own ink, not by the font's padded box, so the font's leading
#: cannot push it off the marks.
LABEL_CENTER_X = 120
LABEL_CENTER_Y = 77
#: DigimonBasic is a 12-pixel font whose digits are 8 pixels tall, so 36
#: (three times its pixel grid) draws them 24 tall with even strokes, which
#: clears the brackets' 42-pixel opening. Off the grid (40 drew them 28 tall)
#: some strokes came out a pixel wider than others.
LABEL_FONT_SIZE = 36
#: What every count's vertical extent is measured against, so the number does
#: not bob a pixel as its digits change.
LABEL_REFERENCE = "0123456789"

#: Bars are 12 wide with 12 between them, bottom-aligned, the first 8 tall and
#: each one 8 taller than the last.
BAR_LEFT = 30
BAR_BOTTOM = 230
BAR_WIDTH = 12
BAR_GAP = 12
BAR_STEP = 8
BAR_FIRST_COLOR = (255, 210, 0)
BAR_LAST_COLOR = (255, 0, 0)
#: How bright a bar not yet reached is drawn, against its lit colour.
UNLIT_BRIGHTNESS = 0.25


def bars_for_count(count):
    """How many bars a count lights: one per four presses, up to all eight."""
    return max(0, min(BAR_COUNT, int(count) // PRESSES_PER_BAR))


def bar_rect(index):
    """Bar *index*'s rect on the 240x240 layout, 0 being the shortest."""
    height = BAR_STEP * (index + 1)
    return pygame.Rect(BAR_LEFT + index * (BAR_WIDTH + BAR_GAP),
                       BAR_BOTTOM - height, BAR_WIDTH, height)


def bar_color(index):
    """Bar *index*'s colour, running evenly from yellow to pure red."""
    t = index / (BAR_COUNT - 1)
    return tuple(round(a + (b - a) * t) for a, b in zip(BAR_FIRST_COLOR, BAR_LAST_COLOR))


def label_color(count):
    """The counter wears the colour of the bar it is filling: yellow at 0,
    red once the last bar is under way."""
    return bar_color(min(BAR_COUNT - 1, max(0, int(count)) // PRESSES_PER_BAR))


class CountBar:
    """Press A or click as many times as possible before the time runs out."""

    def __init__(self, ui_manager) -> None:
        self.ui_manager = ui_manager
        self.count = 0
        self.start_ticks = None
        # The sprites, the counter and the bars all scale by the same factor
        # -- the UI manager's, which follows the window -- and sit on the same
        # centred 240x240 layout, so they stay in register at any size.
        self.counting_sprite = ui_manager.load_sprite_non_integer_scaling(COUNTING_PATH)
        self.result_sprite = ui_manager.load_sprite_non_integer_scaling(RESULT_PATH)
        self.font = font_load(TITLE_FONT, LABEL_FONT_SIZE * ui_manager.ui_scale)
        self._digit_ink = self.font.render(LABEL_REFERENCE, False, (255, 255, 255)).get_bounding_rect()
        self._label_cache = None

    def start(self):
        """Start the clock. Called when the charge begins, not when READY does."""
        self.count = 0
        self.start_ticks = pygame.time.get_ticks()

    def _elapsed(self):
        if self.start_ticks is None:
            return 0
        return pygame.time.get_ticks() - self.start_ticks

    def is_counting(self):
        """Whether presses still register. False for the whole result step."""
        return self.start_ticks is not None and self._elapsed() < DURATION_MS

    def is_showing_result(self):
        """Whether the count is being shown rather than made."""
        return self.start_ticks is not None and self._elapsed() >= DURATION_MS

    def is_time_up(self):
        """True only once the result has been shown too, so the session does
        not finish the charge the instant the pressing stops."""
        return (self.start_ticks is not None
                and self._elapsed() >= DURATION_MS + RESULT_MS)

    def update(self):
        pass

    def handle_event(self, event):
        """Count a press. Returns True when the event was one.

        A press during the result step is swallowed rather than counted: the
        number on screen is what the battle will use, and letting it climb
        after the bars stopped is how a player ends up with a charge they did
        not see themselves make.
        """
        event_type, _ = event
        if event_type not in ("A", "LCLICK"):
            return False
        if not self.is_counting():
            return True
        runtime_globals.game_sound.play("menu")
        self.count = min(self.count + 1, MAX_COUNT)
        return True

    def get_count(self):
        return self.count

    def get_bars(self):
        return bars_for_count(self.count)

    def label_position(self, text):
        """Where to blit the rendered count so its ink lands between the
        brackets: centred on both axes by the ink itself, the vertical one
        measured against LABEL_REFERENCE so the number does not move as its
        digits change."""
        ui = self.ui_manager
        center_x, center_y = ui.scale_position(LABEL_CENTER_X, LABEL_CENTER_Y)
        ink = text.get_bounding_rect()
        ink_middle = self._digit_ink.top + self._digit_ink.height / 2
        return (round(center_x - ink.left - ink.width / 2),
                round(center_y - ink_middle))

    def draw(self, surface):
        ui = self.ui_manager
        showing = self.is_showing_result()
        sprite = self.result_sprite if showing else self.counting_sprite
        if sprite:
            blit_with_cache(surface, sprite, ui.scale_position(0, 0))

        # The number appears only once the counting is over -- the device
        # shows the bars filling, not a running total.
        if showing:
            if self._label_cache is None or self._label_cache[0] != self.count:
                self._label_cache = (self.count, self.font.render(
                    str(self.count), True, label_color(self.count)))
            blit_with_cache(surface, self._label_cache[1],
                            self.label_position(self._label_cache[1]))

        lit = self.get_bars()
        for index in range(BAR_COUNT):
            color = bar_color(index)
            if index >= lit:
                color = tuple(int(c * UNLIT_BRIGHTNESS) for c in color)
            pygame.draw.rect(surface, color, ui.scale_rect(bar_rect(index)))
