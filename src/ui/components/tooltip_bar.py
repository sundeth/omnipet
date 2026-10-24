"""
Tooltip Bar Component - Full-width bar pinned to the bottom of the UI area,
showing the focused option's description as a right-to-left marquee.
"""
import pygame

from ui.components.component import UIComponent
from ui.ui_constants import BASE_RESOLUTION
from utils.pygame_utils import blit_with_cache, blit_with_shadow


class TooltipBar(UIComponent):
    """A ticker along the bottom edge of the UI area.

    The bar deliberately reaches past the UI area on the left, right and
    bottom by `overhang` base pixels, so the only edge the player ever sees
    is the top one -- it reads as part of the frame rather than as a panel
    dropped on top of the screen. `draw` clips to the UI area to keep that
    overhang off the letterbox around it.

    Long text scrolls leftwards, but only after `start_delay` milliseconds,
    so there is time to read the beginning before it moves. The scroll is
    circular: the text is followed by a blank run of a third of the bar, then
    repeats. Text short enough to fit is centred and never moves.

    Because the corners sit outside the UI area, this component draws a plain
    rectangle rather than the cut-corner shape the panels use -- a cut corner
    here would never be visible.
    """

    #: Height of the visible band, in base (240x240) pixels.
    DEFAULT_HEIGHT = 20
    #: How far the bar reaches past the UI area on three sides, base pixels.
    DEFAULT_OVERHANG = 4
    #: Base pixels per second the text travels leftwards.
    DEFAULT_SCROLL_SPEED = 32
    #: Milliseconds the text is held still after it changes.
    DEFAULT_START_DELAY = 2000
    #: Blank run between the end of the text and its repeat, as a fraction of
    #: the text area's width.
    GAP_DIVISOR = 3
    #: Gap between the text and the left/right ends of the bar, base pixels.
    PADDING_X = 4

    def __init__(self, text="", height=None, overhang=None, scroll_speed=None,
                 start_delay=None):
        self.bar_height = height if height is not None else self.DEFAULT_HEIGHT
        self.overhang = overhang if overhang is not None else self.DEFAULT_OVERHANG

        # Sits on the bottom edge, wider than the UI on both sides and
        # reaching below it, so only the top border falls inside the UI area.
        super().__init__(
            -self.overhang,
            BASE_RESOLUTION - self.bar_height,
            BASE_RESOLUTION + (2 * self.overhang),
            self.bar_height + self.overhang,
        )

        self.text = text or ""
        self.scroll_speed = (scroll_speed if scroll_speed is not None
                             else self.DEFAULT_SCROLL_SPEED)
        self.start_delay = (start_delay if start_delay is not None
                            else self.DEFAULT_START_DELAY)

        # Nothing here is selectable; it only reports on what is.
        self.focusable = False
        # Animated every frame, so it renders straight to the screen instead
        # of invalidating the manager's cached master surface.
        self.is_dynamic = True

        # When the current text was set. The scroll clock runs from here.
        self._text_set_at = pygame.time.get_ticks()

        # Render caches, rebuilt when the text, theme or scale changes.
        self._text_surface = None
        self._background = None
        self._compose_surface = None
        self._cache_key = None

    # -- text --------------------------------------------------------------

    def set_text(self, text):
        """Set the description to show, restarting the read-then-scroll cycle.

        Setting the same text again is ignored, so a caller that pushes the
        focused option's text every frame does not keep the marquee pinned at
        its start.
        """
        text = text or ""
        if text == self.text:
            return
        self.text = text
        self._text_set_at = pygame.time.get_ticks()
        self._text_surface = None
        self.needs_redraw = True

    # -- geometry ----------------------------------------------------------

    def _scaled(self, base_value):
        """Scale a base-resolution measurement to screen pixels."""
        return self.manager.scale_value(base_value) if self.manager else base_value

    def _text_area(self):
        """The rect the text is clipped to, in component-local coordinates."""
        padding = self._scaled(self.PADDING_X)
        inset = self._scaled(self.overhang) + padding
        return pygame.Rect(
            inset,
            0,
            max(0, self.rect.width - (2 * inset)),
            self._scaled(self.bar_height),
        )

    # -- scrolling ---------------------------------------------------------

    def _cycle_width(self, area_width):
        """Distance from the start of the text to the start of its repeat."""
        if self._text_surface is None:
            return 0
        return self._text_surface.get_width() + max(1, area_width // self.GAP_DIVISOR)

    def _scroll_offset(self, area_width):
        """How far left the text has travelled, in screen pixels.

        Zero until `start_delay` has passed, then time-based so the speed
        holds whatever the frame rate is set to.
        """
        elapsed = pygame.time.get_ticks() - self._text_set_at - self.start_delay
        if elapsed <= 0:
            return 0
        speed = self.scroll_speed * (self.manager.ui_scale if self.manager else 1)
        cycle = self._cycle_width(area_width)
        if cycle <= 0:
            return 0
        return int((elapsed / 1000.0) * speed) % cycle

    # -- rendering ---------------------------------------------------------

    def _ensure_caches(self):
        """Rebuild the text and background surfaces if anything they depend on moved."""
        colors = self.get_colors()
        scale = self.manager.ui_scale if self.manager else 1
        key = (self.text, colors["bg"], colors["fg"], colors["line"],
               scale, self.rect.width, self.rect.height)
        if key == self._cache_key and self._text_surface is not None:
            return
        self._cache_key = key

        # Background: a plain filled rectangle with a border. Only the top
        # edge of that border lands inside the UI area.
        border_size = self.manager.get_border_size() if self.manager else 2
        self._background = pygame.Surface((self.rect.width, self.rect.height),
                                          pygame.SRCALPHA)
        self._background.fill(colors["bg"])
        pygame.draw.rect(self._background, colors["line"],
                         self._background.get_rect(), width=border_size)

        font = self.get_font("text")
        self._text_surface = (font.render(self.text, True, colors["fg"])
                              if (self.text and font) else None)

    def render(self):
        """Compose the bar for this frame: background, then the scrolled text."""
        self._ensure_caches()

        if (self._compose_surface is None
                or self._compose_surface.get_size() != (self.rect.width, self.rect.height)):
            self._compose_surface = pygame.Surface((self.rect.width, self.rect.height),
                                                   pygame.SRCALPHA)
        surface = self._compose_surface
        surface.fill((0, 0, 0, 0))
        surface.blit(self._background, (0, 0))

        if self._text_surface is not None:
            area = self._text_area()
            text_width = self._text_surface.get_width()
            text_y = area.y + (area.height - self._text_surface.get_height()) // 2

            previous_clip = surface.get_clip()
            surface.set_clip(area)
            if text_width <= area.width:
                # It fits: centre it and leave it alone.
                surface.blit(self._text_surface,
                             (area.x + (area.width - text_width) // 2, text_y))
            else:
                offset = self._scroll_offset(area.width)
                cycle = self._cycle_width(area.width)
                # Two copies a full cycle apart cover every offset, so the
                # repeat is already entering as the first copy leaves.
                start_x = area.x - offset
                surface.blit(self._text_surface, (start_x, text_y))
                surface.blit(self._text_surface, (start_x + cycle, text_y))
            surface.set_clip(previous_clip)

        self.needs_redraw = False
        return surface

    def draw(self, surface, ui_local=False):
        """Draw the bar, keeping its overhang inside the UI area.

        Args:
            surface: Target surface to draw on
            ui_local: If True, use UI-local coordinates (for master surface
                     rendering); if False, use screen coordinates
        """
        if not self.visible:
            return

        bar = self.render()

        if ui_local and self.manager:
            # The master surface is already the size of the UI area, so it
            # clips the overhang on its own.
            pos = (self.rect.x - self.manager.ui_offset_x,
                   self.rect.y - self.manager.ui_offset_y)
            blit_with_cache(surface, bar, pos)
            return

        pos = self.rect.topleft
        previous_clip = surface.get_clip()
        if self.manager:
            ui_rect = pygame.Rect(self.manager.ui_offset_x, self.manager.ui_offset_y,
                                  self.manager.ui_width, self.manager.ui_height)
            # Without this the three overhanging sides would paint over the
            # border and letterbox drawn around the UI area.
            surface.set_clip(ui_rect.clip(previous_clip) if previous_clip else ui_rect)

        if self.manager and self.manager.should_render_shadow(self, "component"):
            blit_with_shadow(surface, bar,
                             pygame.Rect(pos[0], pos[1], self.rect.width, self.rect.height))
        else:
            blit_with_cache(surface, bar, pos)

        surface.set_clip(previous_clip)
