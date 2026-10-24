"""
GameModeSelector Component - Full-screen split selector for Progression / Free mode.

Two halves (top and bottom) each covering half the entire display surface.
The selected half is highlighted with a border and brighter background.
Uses screen coordinates (dynamic) so it fills the whole window, not just
the UI area.
"""
import pygame
from ui.components.component import UIComponent
from ui.ui_constants import (
    BASE_RESOLUTION, TITLE_FONT, TEXT_FONT,
    GREEN, GREEN_DARK, GREEN_LIGHT,
    CYAN, CYAN_DARK, CYAN_LIGHT,
)
from core import runtime_globals
from utils.asset_utils import font_load


class GameModeSelector(UIComponent):
    """Full-screen selector split into two halves for game mode choice."""

    def __init__(self, x=0, y=0, width=BASE_RESOLUTION, height=BASE_RESOLUTION,
                 on_select_callback=None):
        # Initialize with base coordinates – add_component will scale
        super().__init__(x, y, width, height)
        self.focusable = True
        self.is_dynamic = True  # Draw directly to screen, not master surface
        self.use_screen_coordinates = True  # Bypass UI area – fill whole screen
        self.selected_index = 0  # 0 = Progression (top), 1 = Free (bottom)
        self.on_select_callback = on_select_callback

        # Mode definitions
        self.modes = [
            {
                "name": "Progression Mode",
                "description": (
                    "Allows access to the Arena and the entire Shop, "
                    "accumulate Coins by playing the game and progressing "
                    "through the modules. Perfect for all players!"
                ),
                "colors": {
                    "bg": GREEN_DARK,
                    "border": GREEN,
                    "text": GREEN_LIGHT,
                    "title": (255, 255, 255),
                },
            },
            {
                "name": "Free Mode",
                "description": (
                    "All modules and features unlocked at start, no access "
                    "to the Arena, limited access to the Shop. Great for "
                    "module developers and offline users."
                ),
                "colors": {
                    "bg": CYAN_DARK,
                    "border": CYAN,
                    "text": CYAN_LIGHT,
                    "title": (255, 255, 255),
                },
            },
        ]

    def on_manager_set(self):
        """Called after the manager assigns itself – resize to fill the
        entire screen (not just the UI area)."""
        sw = runtime_globals.SCREEN_WIDTH
        sh = runtime_globals.SCREEN_HEIGHT
        self.rect = pygame.Rect(0, 0, sw, sh)

    # -----------------------------------------------------------------
    # Drawing
    # -----------------------------------------------------------------

    def draw(self, surface: pygame.Surface, ui_local=False):
        """Draw directly to the screen surface – ignores ui_local since we
        always operate in screen coordinates."""
        if not self.visible:
            return

        sw = surface.get_width()
        sh = surface.get_height()
        scale = self.manager.ui_scale if self.manager else 1

        half_h = sh // 2
        gap = max(1, 2 * scale)  # gap between halves

        for i, mode in enumerate(self.modes):
            top_y = i * half_h
            area_h = half_h - gap
            area = pygame.Rect(0, top_y + (gap if i == 1 else 0), sw, area_h)

            colors = mode["colors"]
            is_selected = (i == self.selected_index)

            # Background
            bg_color = colors["bg"] if is_selected else self._dim(colors["bg"], 0.5)
            pygame.draw.rect(surface, bg_color, area)

            # Border (only around selected)
            if is_selected:
                border_w = max(2, 2 * scale)
                pygame.draw.rect(surface, colors["border"], area, border_w)

            # Title
            title_font = self._get_title_font(scale)
            title_color = colors["title"] if is_selected else self._dim(colors["title"], 0.6)
            title_surf = title_font.render(mode["name"], True, title_color)
            title_x = area.x + (area.width - title_surf.get_width()) // 2
            title_y = area.y + (10 * scale)
            surface.blit(title_surf, (title_x, title_y))

            # Description (word-wrapped)
            desc_font = self._get_text_font(scale)
            padding = 12 * scale
            max_text_w = area.width - padding * 2
            desc_y = title_y + title_surf.get_height() + (6 * scale)
            desc_color = colors["text"] if is_selected else self._dim(colors["text"], 0.5)
            self._draw_wrapped_text(surface, mode["description"], desc_font,
                                    desc_color, int(area.x + padding), int(desc_y),
                                    int(max_text_w))

            # Small arrow indicator for selected item
            if is_selected:
                arrow_surf = title_font.render(">", True, colors["border"])
                surface.blit(arrow_surf, (area.x + (4 * scale), title_y))

    # -----------------------------------------------------------------
    # Input – handle keyboard/gamepad AND mouse/touch
    # -----------------------------------------------------------------

    def handle_mouse_click(self, mouse_pos, event_type="LCLICK"):
        """Called by UIManager when a mouse click lands on this component.
        Determines which half was clicked, updates focus, and confirms."""
        if not self.visible:
            return False

        mx, my = mouse_pos
        sh = runtime_globals.SCREEN_HEIGHT
        clicked_idx = 0 if my < sh // 2 else 1

        if clicked_idx != self.selected_index:
            # First click on a different half → just change focus
            self.selected_index = clicked_idx
            runtime_globals.game_sound.play("menu")
            self.needs_redraw = True
            return True

        # Clicked the already-selected half → confirm selection
        runtime_globals.game_sound.play("menu")
        if self.on_select_callback:
            self.on_select_callback(self.selected_index)
        return True

    def _get_half_index_from_y(self, y):
        """Return 0 (top half) or 1 (bottom half) based on screen y."""
        sh = runtime_globals.SCREEN_HEIGHT
        return 0 if y < sh // 2 else 1

    def handle_event(self, event):
        if not self.visible:
            return False

        if not isinstance(event, tuple) or len(event) != 2:
            return False

        event_type, event_data = event

        # Mouse hover → update selection to whichever half the cursor is over
        if event_type == "MOUSE_MOTION":
            if event_data and "pos" in event_data:
                mx, my = event_data["pos"]
                hover_idx = self._get_half_index_from_y(my)
                if hover_idx != self.selected_index:
                    self.selected_index = hover_idx
                    runtime_globals.game_sound.play("menu")
                    self.needs_redraw = True
                return True
            return False

        # Mouse / touch click → switch half or confirm
        if event_type == "LCLICK":
            if event_data and "pos" in event_data:
                mx, my = event_data["pos"]
                clicked_idx = self._get_half_index_from_y(my)
                if clicked_idx != self.selected_index:
                    self.selected_index = clicked_idx
                    runtime_globals.game_sound.play("menu")
                    self.needs_redraw = True
                    return True
                # Already on this half → confirm
                runtime_globals.game_sound.play("menu")
                if self.on_select_callback:
                    self.on_select_callback(self.selected_index)
                return True
            return False

        # Keyboard / gamepad navigation
        if event_type in ("UP", "DOWN"):
            self.selected_index = 1 - self.selected_index
            runtime_globals.game_sound.play("menu")
            self.needs_redraw = True
            return True

        if event_type in ("A", "START"):
            runtime_globals.game_sound.play("menu")
            if self.on_select_callback:
                self.on_select_callback(self.selected_index)
            return True

        return False

    def update(self):
        pass

    def render(self):
        """Not used – we draw directly in draw()."""
        return pygame.Surface((1, 1), pygame.SRCALPHA)

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------

    @staticmethod
    def _dim(color, factor):
        """Dim a color by a factor (0-1)."""
        return tuple(max(0, min(255, int(c * factor))) for c in color)

    @staticmethod
    def _get_title_font(scale):
        size = 16 * scale
        return font_load(TITLE_FONT, int(size))

    @staticmethod
    def _get_text_font(scale):
        # 16 = ProggySmall's pixel-perfect design grid; 12 * scale rendered
        # with mixed 1-2px stems once anti-aliasing was disabled game-wide.
        size = 16 * scale
        return font_load(TEXT_FONT, int(size))

    @staticmethod
    def _draw_wrapped_text(surface, text, font, color, x, y, max_width):
        """Draw word-wrapped text starting at (x, y)."""
        words = text.split()
        lines = []
        current_line = ""

        for word in words:
            test = f"{current_line} {word}".strip()
            if font.size(test)[0] <= max_width:
                current_line = test
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word

        if current_line:
            lines.append(current_line)

        line_h = font.get_linesize()
        for line in lines:
            line_surf = font.render(line, True, color)
            surface.blit(line_surf, (x, y))
            y += line_h
