"""
OptionRow Component - A settings row with label, value display, and left/right arrows.

Supports keyboard (LEFT/RIGHT to change value, A to activate) and
mouse/touch (clickable left/right arrow zones, or click label to activate).

For "cycle"/"toggle" options: displays [<] Label: Value [>]
For "action" options: displays Label (click/A activates)
"""
import pygame

from ui.components.component import UIComponent
from core import runtime_globals
from utils.pygame_utils import blit_with_shadow


class OptionRow(UIComponent):
    """A single settings row that handles both keyboard and mouse/touch input.

    Args:
        x, y: Base position (pre-scale).
        width, height: Base dimensions (pre-scale).
        label: Display text prefix (e.g. "Volume").
        option_type: "cycle", "toggle", or "action".
        get_value: Callable returning the current display value string (cycle/toggle).
        set_value: Callable(increase: bool) to change the value (cycle/toggle).
        on_activate: Callable() for action-type rows.
        cut_corners: Dict controlling diagonal corner cuts (same format as Button).
    """

    # Arrow zone width in *base* pixels (pre-scale)
    ARROW_ZONE_WIDTH = 24

    def __init__(self, x, y, width, height, label, option_type="action",
                 get_value=None, set_value=None, on_activate=None,
                 cut_corners=None, enabled=True):
        super().__init__(x, y, width, height)
        self.focusable = True
        self.enabled = enabled
        self.label = label
        self.option_type = option_type  # "cycle", "toggle", "action"
        self.get_value = get_value
        self.set_value = set_value
        self.on_activate = on_activate
        self.cut_corners = cut_corners or {"tl": False, "tr": False, "bl": False, "br": False}

        # Visual click feedback
        self._arrow_clicked = None  # "left", "right", or None
        self._arrow_click_frames = 0
        self._click_hold_frames = 6
        self.shadow_mode = "disabled"
        self.draw_background = True

    # ------------------------------------------------------------------
    # Text helpers
    # ------------------------------------------------------------------

    def _display_text(self):
        """Build the centre label string."""
        if self.option_type in ("cycle", "toggle") and self.get_value:
            return f"{self.label}: {self.get_value()}"
        return self.label

    @property
    def _has_arrows(self):
        return self.option_type in ("cycle", "toggle")

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def handle_event(self, event):
        """Handle keyboard events when this row is focused."""
        if not self.visible or not self.focusable or not self.enabled:
            return False
        event_type, event_data = event
        if event_type in ("LEFT", "RIGHT") and self._has_arrows:
            self._do_change(event_type == "RIGHT")
            return True  # consume so UIManager doesn't move focus
        if event_type == "LCLICK":
            # Route clicks through the position-aware handler so the < zone
            # decreases and the > zone increases (instead of always
            # activating / increasing regardless of where the row was hit).
            if event_data and "pos" in event_data:
                return self.handle_mouse_click(event_data["pos"], "LCLICK")
            return self._do_activate()
        if event_type == "A":
            return self._do_activate()
        return False

    def handle_mouse_click(self, mouse_pos, event_type):
        """Called by UIManager on LCLICK when mouse is over this component."""
        if not self.visible or not self.enabled:
            return False
        if event_type != "LCLICK":
            return False

        # A focused row receives clicks made anywhere on screen (the UI
        # manager dispatches to the focused component first) — only react
        # when the click actually lands on this row, otherwise clicking e.g.
        # the BACK button would re-trigger the last-used option.
        if not self.rect or not self.rect.collidepoint(mouse_pos):
            return False

        scale = self.manager.ui_scale if self.manager else 1
        arrow_w = int(self.ARROW_ZONE_WIDTH * scale)
        local_x = mouse_pos[0] - self.rect.x

        if self._has_arrows:
            if local_x < arrow_w:
                self._arrow_clicked = "left"
                self._arrow_click_frames = self._click_hold_frames
                self._do_change(False)
                return True
            elif local_x > self.rect.width - arrow_w:
                self._arrow_clicked = "right"
                self._arrow_click_frames = self._click_hold_frames
                self._do_change(True)
                return True

        # Click on mid area → activate (for actions) or treat as increase
        return self._do_activate()

    def _do_change(self, increase):
        if self.set_value:
            self.set_value(increase)
        runtime_globals.game_sound.play("menu")
        self.needs_redraw = True

    def _do_activate(self):
        if self.option_type == "action" and self.on_activate:
            self.clicked = True
            self.click_time = pygame.time.get_ticks()
            self.needs_redraw = True
            self.on_activate()
            return True
        # For cycle/toggle, A press → increase
        if self._has_arrows:
            self._do_change(True)
            return True
        return False

    # ------------------------------------------------------------------
    # Update (click feedback timer)
    # ------------------------------------------------------------------

    def update(self):
        self.handle_mouse_hover()
        if self._arrow_click_frames > 0:
            self._arrow_click_frames -= 1
            if self._arrow_click_frames <= 0:
                self._arrow_clicked = None
                self.needs_redraw = True
        # Reset generic click state
        if self.clicked and pygame.time.get_ticks() - self.click_time > 200:
            self.clicked = False
            self.needs_redraw = True

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def get_colors(self):
        """Muted colours when disabled (e.g. Window Size while fullscreen)."""
        colors = super().get_colors()
        if not self.enabled:
            return {
                "bg": tuple(c // 3 for c in colors["bg"]),
                "fg": tuple(c // 2 for c in colors["fg"]),
                "line": tuple(c // 2 for c in colors["line"]),
            }
        return colors

    def render(self):
        scale = self.manager.ui_scale if self.manager else 1
        w, h = self.rect.width, self.rect.height
        target_size = (w, h)

        if not hasattr(self, "_render_surface") or self._render_surface is None or self._render_surface.get_size() != target_size:
            self._render_surface = pygame.Surface(target_size, pygame.SRCALPHA)
        surface = self._render_surface
        surface.fill((0, 0, 0, 0))

        colors = self.get_colors()
        bg_color = colors["bg"]
        fg_color = colors["fg"]
        line_color = colors["line"]

        border_size = self.manager.get_border_size() if self.manager else 2

        # --- background with optional cut corners ---
        if self.draw_background:
            self._draw_background(surface, w, h, bg_color, line_color, border_size, scale)

        font = self.get_font("text")
        arrow_w = int(self.ARROW_ZONE_WIDTH * scale)

        # --- draw arrows ---
        if self._has_arrows:
            self._draw_arrow(surface, "left", arrow_w, h, fg_color, line_color, border_size, scale)
            self._draw_arrow(surface, "right", arrow_w, h, fg_color, line_color, border_size, scale)

        # --- draw text ---
        text = self._display_text()
        text_surface = font.render(text, True, fg_color)
        text_rect = text_surface.get_rect()

        if self._has_arrows:
            text_area_x = arrow_w
            text_area_w = w - arrow_w * 2
        else:
            text_area_x = border_size * 2
            text_area_w = w - border_size * 4

        text_rect.centery = h // 2
        text_rect.centerx = text_area_x + text_area_w // 2
        surface.blit(text_surface, text_rect)

        return surface

    def _draw_background(self, surface, w, h, bg_color, line_color, border_size, scale):
        """Draw the row background with optional cut corners."""
        has_cuts = any(self.cut_corners.values())
        if has_cuts:
            cut = int(12 * scale)
            bi = border_size      # border inset
            bgi = border_size * 2  # bg inset

            for inset, color in ((bi, line_color), (bgi, bg_color)):
                pts = []
                if self.cut_corners.get("tl"):
                    pts.extend([(cut, inset), (inset, cut)])
                else:
                    pts.append((inset, inset))
                if self.cut_corners.get("bl"):
                    pts.extend([(inset, h - cut - inset), (cut, h - inset)])
                else:
                    pts.append((inset, h - inset))
                if self.cut_corners.get("br"):
                    pts.extend([(w - cut - inset, h - inset), (w - inset, h - cut - inset)])
                else:
                    pts.append((w - inset, h - inset))
                if self.cut_corners.get("tr"):
                    pts.extend([(w - inset, cut), (w - cut - inset, inset)])
                else:
                    pts.append((w - inset, inset))
                if len(pts) >= 3:
                    pygame.draw.polygon(surface, color, pts)
        else:
            if border_size > 0:
                pygame.draw.rect(surface, line_color, (0, 0, w, h), width=border_size, border_radius=border_size)
            bo = border_size // 2
            pygame.draw.rect(surface, bg_color, (bo, bo, w - border_size, h - border_size),
                             border_radius=max(0, border_size - bo))

    def _draw_arrow(self, surface, side, arrow_w, h, fg_color, line_color, border_size, scale):
        """Draw a left or right arrow triangle inside its zone."""
        # Determine if this arrow is in clicked state
        clicked = (self._arrow_clicked == side)
        # Use inverted colours when clicked for visual feedback
        color = line_color if clicked else fg_color

        margin_x = int(6 * scale)
        margin_y = int(4 * scale)
        w_total = surface.get_width()

        if side == "left":
            # ◀ triangle pointing left
            x0 = margin_x
            x1 = arrow_w - margin_x
            y_mid = h // 2
            pts = [(x1, margin_y + border_size), (x0, y_mid), (x1, h - margin_y - border_size)]
        else:
            # ▶ triangle pointing right
            x0 = w_total - arrow_w + margin_x
            x1 = w_total - margin_x
            y_mid = h // 2
            pts = [(x0, margin_y + border_size), (x1, y_mid), (x0, h - margin_y - border_size)]

        pygame.draw.polygon(surface, color, pts)

        # Thin divider line between arrow zone and label area
        div_x = arrow_w if side == "left" else w_total - arrow_w
        pygame.draw.line(surface, line_color, (div_x, border_size * 2), (div_x, h - border_size * 2), max(1, border_size // 2))
