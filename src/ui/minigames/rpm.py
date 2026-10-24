"""The iC's rhythm charge: recent RPM and independently earned bars.

Six seconds of button input follow READY, then three seconds of blinking and
one second held for readability. Scoring lives in rpm_rhythm; its timing rules
approximate the owner's recordings and are documented in utilities/claude/docs/design/ic_rpm.md.
All positions below use the 240x240 layout at 1x.
"""
import pygame

from battle.sim.battle_utils import ic_rpm_target
from core import runtime_globals
from ui.minigames.rpm_rhythm import CHARGE_MS, MAX_RPM, RPMRhythm
from ui.ui_constants import TITLE_FONT
from utils.asset_utils import font_load
from utils.pygame_utils import blit_with_cache


#: How long the player has to keep the rate up.
DURATION_MS = CHARGE_MS
#: Then the counter blinks, and then it holds steady so it can be read.
BLINK_MS = 3000
HOLD_MS = 1000
#: A full on-off cycle of the blink.
BLINK_PERIOD_MS = 400

BAR_COUNT = 10

BACKGROUND_PATH = "assets/RPM.png"
#: The counter sits in the sprite's top row, over the marks: "XX ||||" above
#: "|||| RPM". Its digits start on the lower row's marks (x 107) and are
#: centred on the height of the marks beside them (rows 43-62). Placed by the
#: digits' own ink, not the font's padded box, so the font's leading cannot
#: push them off the marks. Unchanged from where the Mini's charge drew it,
#: because this is the screen that number always belonged to.
LABEL_LEFT = 107
LABEL_CENTER_Y = 53
#: DigimonBasic is a 12-pixel font whose digits are 8 pixels tall, so 36
#: (three times its pixel grid) draws them 24 tall with even strokes --
#: taller than the RPM text, as the design has them. 48 would run three
#: digits into the marks beside them.
LABEL_FONT_SIZE = 36
#: What every reading's vertical extent is measured against, so the number
#: does not bob a pixel as its digits change.
LABEL_REFERENCE = "0123456789"
#: **The device's own geometry**, in its 32 pixels, scaled onto the 240-wide
#: layout: a 2-pixel border on the left, then ten 2-pixel bars a pixel apart,
#: which fills 31 of the 32 and leaves the last pixel as the right border.
DEVICE_WIDTH = 32
DEVICE_BORDER = 2
DEVICE_BAR = 2
DEVICE_GAP = 1
LAYOUT_WIDTH = 240
#: 7.5 layout pixels to the device's one.
DEVICE_SCALE = LAYOUT_WIDTH / DEVICE_WIDTH

#: Every bar is the same height, and it is the tallest the Mini's stepped
#: row reaches -- eight steps of eight -- so the two charges sit on the same
#: baseline and fill the same band of the screen.
BAR_HEIGHT = 64
BAR_BOTTOM = 230
BAR_FIRST_COLOR = (255, 210, 0)
BAR_LAST_COLOR = (255, 0, 0)
#: How bright a bar not yet reached is drawn, against its lit colour.
UNLIT_BRIGHTNESS = 0.25


def bar_rect(index):
    """Bar *index*'s rect on the 240x240 layout, left to right.

    Derived from the device's own pixels rather than written out, so the
    spacing stays the device's if the layout width ever changes.
    """
    left = (DEVICE_BORDER + index * (DEVICE_BAR + DEVICE_GAP)) * DEVICE_SCALE
    return pygame.Rect(round(left), BAR_BOTTOM - BAR_HEIGHT,
                       round(DEVICE_BAR * DEVICE_SCALE), BAR_HEIGHT)


def bar_color(index):
    """Bar *index*'s colour, running evenly from yellow to pure red."""
    t = index / (BAR_COUNT - 1)
    return tuple(round(a + (b - a) * t) for a, b in zip(BAR_FIRST_COLOR, BAR_LAST_COLOR))


def label_color(bars):
    """The counter wears the colour of the highest bar it has lit."""
    return bar_color(max(0, min(BAR_COUNT - 1, int(bars) - 1)))


class RPM:
    """Press A or click steadily; pace and consistency earn the charge."""

    def __init__(self, ui_manager, pet=None) -> None:
        self.ui_manager = ui_manager
        self.pet = pet
        self.presses = 0
        self.rpm = 0
        self.start_ticks = None
        # The pet's preferred pace; hitting it once does not fill the meter.
        self.target = ic_rpm_target(pet)
        self.rhythm = RPMRhythm(self.target)
        self.background = ui_manager.load_sprite_non_integer_scaling(BACKGROUND_PATH)
        self.font = font_load(TITLE_FONT, LABEL_FONT_SIZE * ui_manager.ui_scale)
        self._digit_ink = self.font.render(LABEL_REFERENCE, False, (255, 255, 255)).get_bounding_rect()
        self._label_cache = None

    def start(self):
        """Start the clock. Called when the charge begins, not when READY does."""
        self.presses = 0
        self.rpm = 0
        self.rhythm = RPMRhythm(self.target)
        self._label_cache = None
        self.start_ticks = pygame.time.get_ticks()

    def _elapsed(self):
        if self.start_ticks is None:
            return 0
        return pygame.time.get_ticks() - self.start_ticks

    def is_counting(self):
        """Whether presses still register."""
        return self.start_ticks is not None and self._elapsed() < DURATION_MS

    def is_blinking(self):
        elapsed = self._elapsed()
        return (self.start_ticks is not None
                and DURATION_MS <= elapsed < DURATION_MS + BLINK_MS)

    def is_time_up(self):
        """True once the counter has blinked and then been held steady."""
        return (self.start_ticks is not None
                and self._elapsed() >= DURATION_MS + BLINK_MS + HOLD_MS)

    def update(self):
        """Settle missed beats, including a frame that crosses the deadline."""
        if self.start_ticks is not None:
            self.rhythm.advance(self._elapsed())
            self.rpm = self.rhythm.rpm

    def handle_event(self, event):
        """Count a press. Returns True when the event was one.

        A press after the time is up is swallowed rather than counted: the
        reading on screen is the one the battle will use.
        """
        event_type, _ = event
        if event_type not in ("A", "LCLICK"):
            return False
        if not self.is_counting():
            return True
        if self.rhythm.press(self._elapsed()):
            runtime_globals.game_sound.play("menu")
        self.presses = len(self.rhythm.press_times)
        self.rpm = self.rhythm.rpm
        return True

    def get_rpm(self):
        return self.rpm

    def get_presses(self):
        return self.presses

    def get_bars(self, target=None):
        """Earned charge, or the same press history evaluated for another pet."""
        return self.rhythm.bars_for_target(self.target if target is None else target)

    def _label_visible(self):
        """The counter is solid while counting and while held, and flashes in
        between."""
        if not self.is_blinking():
            return True
        return ((self._elapsed() - DURATION_MS) % BLINK_PERIOD_MS) < BLINK_PERIOD_MS // 2

    def label_position(self, text):
        """Where to blit a rendered reading so its ink lands on the layout.

        The left edge is the reading's own first inked column; the vertical
        centre is the digits' shared one, from LABEL_REFERENCE.
        """
        ui = self.ui_manager
        left, center_y = ui.scale_position(LABEL_LEFT, LABEL_CENTER_Y)
        ink_left = text.get_bounding_rect().left
        ink_middle = self._digit_ink.top + self._digit_ink.height / 2
        return (left - ink_left, round(center_y - ink_middle))

    def draw(self, surface):
        ui = self.ui_manager
        if self.background:
            blit_with_cache(surface, self.background, ui.scale_position(0, 0))

        lit = self.get_bars()
        if self._label_visible():
            key = (self.rpm, lit)
            if self._label_cache is None or self._label_cache[0] != key:
                self._label_cache = (key, self.font.render(
                    str(self.rpm), True, label_color(lit)))
            blit_with_cache(surface, self._label_cache[1],
                            self.label_position(self._label_cache[1]))

        for index in range(BAR_COUNT):
            color = bar_color(index)
            if index >= lit:
                color = tuple(int(c * UNLIT_BRIGHTNESS) for c in color)
            pygame.draw.rect(surface, color, ui.scale_rect(bar_rect(index)))
