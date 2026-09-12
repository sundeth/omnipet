"""Reliability meter styled after the Digivice iC's 0..31 gauge."""

import pygame

from core import constants, runtime_globals
from ui.components.component import UIComponent
from utils.pygame_utils import blit_with_cache


class ReliabilityMeter(UIComponent):
    """Compact tick gauge with a movable marker for the iC Reliability stat."""

    def __init__(self, x, y, width, height, value=constants.RELIABILITY_MIN):
        super().__init__(x, y, width, height)
        self.value = self._clamp(value)
        self.font = None
        self.focusable = False

    @staticmethod
    def _clamp(value):
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = constants.RELIABILITY_MIN
        return max(constants.RELIABILITY_MIN,
                   min(constants.RELIABILITY_MAX, value))

    def set_value(self, value):
        value = self._clamp(value)
        if self.value != value:
            self.value = value
            self.needs_redraw = True

    def render(self):
        surface = pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
        if not self.manager:
            return surface

        scale = self.manager.ui_scale
        colors = self.manager.get_theme_colors()
        panel_color = colors["bg"]
        ink_color = colors["black"]
        label_color = colors["fg"]

        if self.font is None:
            self.font = self.get_font("text", custom_size=max(8, int(10 * scale)))

        label = self.font.render("REL", True, label_color)
        label_y = (self.rect.height - label.get_height()) // 2
        blit_with_cache(surface, label, (0, label_y))

        padding = max(1, int(scale))
        gauge_left = min(self.rect.width - 8 * padding,
                         label.get_width() + 2 * padding)
        gauge = pygame.Rect(
            gauge_left,
            2 * padding,
            self.rect.width - gauge_left,
            self.rect.height - 4 * padding,
        )
        border = max(1, self.manager.get_border_size())
        pygame.draw.rect(surface, panel_color, gauge)
        pygame.draw.rect(surface, ink_color, gauge, width=border)

        inner_left = gauge.left + border + padding
        inner_right = gauge.right - border - padding - 1
        center_y = gauge.centery
        band_height = max(2, 2 * padding)
        pygame.draw.rect(
            surface,
            ink_color,
            (inner_left, center_y - band_height // 2,
             max(1, inner_right - inner_left + 1), band_height),
        )

        # The device face alternates short/long teeth above and below its
        # central band. Sixteen positions on each side visually encode the
        # full 32-value scale without turning this small component into text.
        span = max(1, inner_right - inner_left)
        tick_width = max(1, padding)
        for index in range(16):
            x = inner_left + round(index * span / 15)
            tick = (3 if index % 4 == 0 else 2) * padding
            pygame.draw.line(surface, ink_color,
                             (x, center_y - band_height // 2),
                             (x, center_y - band_height // 2 - tick),
                             tick_width)
            pygame.draw.line(surface, ink_color,
                             (x, center_y + (band_height - 1) // 2),
                             (x, center_y + (band_height - 1) // 2 + tick),
                             tick_width)

        marker_x = inner_left + round(
            (self.value - constants.RELIABILITY_MIN) * span /
            (constants.RELIABILITY_MAX - constants.RELIABILITY_MIN)
        )
        pygame.draw.line(
            surface,
            ink_color,
            (marker_x, gauge.top + border),
            (marker_x, gauge.bottom - border - 1),
            max(1, 2 * padding),
        )

        if (self.focused and self.tooltip_text and
                runtime_globals.INPUT_MODE != runtime_globals.TOUCH_MODE):
            pygame.draw.rect(surface, colors.get("highlight", label_color),
                             surface.get_rect(), width=max(1, border))

        return surface
