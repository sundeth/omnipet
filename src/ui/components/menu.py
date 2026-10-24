"""
Menu Component - A themed popup menu with options
"""
import pygame
from ui.components.component import UIComponent
from core import runtime_globals


class Menu(UIComponent):
    """A popup menu component with themed styling"""
    
    def __init__(self, width=120, height=100):
        # Center on screen (will be positioned by manager)
        x = (240 - width) // 2
        y = (240 - height) // 2
        super().__init__(x, y, width, height)
        
        self.options = []
        self.selected_index = 0
        self.visible = False
        self.focusable = False  # Not focusable when not visible
        self.use_screen_coordinates = True  # Menu uses screen coordinates for centering
        
        # Callbacks
        self.on_select = None  # Called when an option is selected (option_index)
        self.on_cancel = None  # Called when menu is cancelled
        
        # Visual properties
        self.padding = 8
        self.option_height = 20
        self.border_size = 2

        # A list longer than max_visible scrolls inside a fixed window instead
        # of growing a menu taller than the screen. None keeps the original
        # "one row per option" sizing.
        self.max_visible = None
        self.scroll_offset = 0

    def open(self, options, on_select=None, on_cancel=None, auto_center=True, max_visible=None):
        """Open the menu with the given options

        auto_center controls whether the menu recenters vertically based
        on the number of options, matching the Omnimon-Online behavior
        while defaulting to True for backward compatibility.

        max_visible caps how many options are drawn at once; the rest are
        reached by scrolling.
        """
        self.options = options
        self.selected_index = 0
        self.max_visible = max_visible
        self.scroll_offset = 0
        self.visible = True
        self.focusable = True

        if on_select:
            self.on_select = on_select
        if on_cancel:
            self.on_cancel = on_cancel

        self._apply_size(auto_center)

        runtime_globals.game_console.log(f"[Menu] Opened with {len(options)} options")

    def update_options(self, options, auto_center=True):
        """Update menu options dynamically."""
        self.options = options
        self.scroll_offset = 0
        self._apply_size(auto_center)

    def set_selected_index(self, index):
        """Move the cursor, scrolling the window so it stays visible."""
        if 0 <= index < len(self.options):
            self.selected_index = index
            self._ensure_visible()
            self.needs_redraw = True

    def _visible_count(self):
        """How many options are drawn at once."""
        if not self.options:
            return 0
        if self.max_visible is None:
            return len(self.options)
        return min(len(self.options), max(1, self.max_visible))

    def _apply_size(self, auto_center=True):
        """Resize (and optionally recenter) the menu for its option window."""
        required_height = (self._visible_count() * self.option_height) + (self.padding * 2)

        if self.manager:
            # Use base coordinates
            self.base_rect.height = required_height
            if auto_center:
                self.base_rect.y = (240 - required_height) // 2
            # Update screen rect
            self.rect = self.manager.scale_rect(self.base_rect)
        else:
            self.rect.height = required_height
            if auto_center:
                self.rect.y = (240 - required_height) // 2

        self.needs_redraw = True

    def _ensure_visible(self):
        """Scroll the window so the selected option sits inside it."""
        visible = self._visible_count()
        if visible >= len(self.options):
            self.scroll_offset = 0
            return
        if self.selected_index < self.scroll_offset:
            self.scroll_offset = self.selected_index
        elif self.selected_index >= self.scroll_offset + visible:
            self.scroll_offset = self.selected_index - visible + 1
        self.scroll_offset = max(0, min(self.scroll_offset, len(self.options) - visible))

    def close(self):
        """Close the menu"""
        runtime_globals.game_console.log(f"[Menu] close() called - visible={self.visible}, manager.active_menu={self.manager.active_menu if self.manager else 'NO MANAGER'}")
        self.visible = False
        self.focusable = False
        self.options = []
        self.selected_index = 0
        self.scroll_offset = 0

        # Clear from UI manager's active menu
        if self.manager and self.manager.active_menu == self:
            runtime_globals.game_console.log("[Menu] Clearing active_menu from manager")
            self.manager.active_menu = None
        
        runtime_globals.game_console.log(f"[Menu] Closed - visible={self.visible}, manager.active_menu={self.manager.active_menu if self.manager else 'NO MANAGER'}")
        
    def handle_event(self, event):
        """Handle input events for the menu - blocks all events while visible"""
        if not self.visible:
            return False
        
        # Handle tuple-based events
        if not isinstance(event, tuple) or len(event) != 2:
            return False
            
        event_type, event_data = event
        
        if event_type == "UP":
            runtime_globals.game_sound.play("menu")
            self.selected_index = (self.selected_index - 1) % len(self.options)
            self._ensure_visible()
            self.needs_redraw = True
            return True
        elif event_type == "DOWN":
            runtime_globals.game_sound.play("menu")
            self.selected_index = (self.selected_index + 1) % len(self.options)
            self._ensure_visible()
            self.needs_redraw = True
            return True
        elif event_type == "SCROLL":
            # The wheel moves the window; the cursor is dragged along so the
            # option A would pick is always one of the visible ones.
            visible = self._visible_count()
            if event_data and visible < len(self.options):
                amount = int(event_data.get("amount", 1) or 1)
                step = -amount if event_data.get("direction") == "UP" else amount
                self.scroll_offset = max(0, min(self.scroll_offset + step,
                                                len(self.options) - visible))
                self.selected_index = min(max(self.selected_index, self.scroll_offset),
                                          self.scroll_offset + visible - 1)
                self.needs_redraw = True
            return True
        elif event_type == "LCLICK":
            # For mouse / touch clicks, check if click is inside menu and
            # which option was tapped (touch has no MOUSE_MOTION pre-select).
            if event_data and "pos" in event_data:
                mouse_pos = event_data["pos"]
                if self.rect.collidepoint(mouse_pos):
                    tapped_index = self._option_index_at(mouse_pos)
                    if tapped_index is not None:
                        self.selected_index = tapped_index
                        runtime_globals.game_sound.play("menu")
                        if self.on_select:
                            self.on_select(self.selected_index)
                        self.close()
                else:
                    # Click outside menu - cancel
                    runtime_globals.game_sound.play("cancel")
                    if self.on_cancel:
                        self.on_cancel()
                    self.close()
            return True
        elif event_type == "A":
            runtime_globals.game_sound.play("menu")
            if self.on_select:
                self.on_select(self.selected_index)
            self.close()
            return True
        elif event_type == "B":  # B button cancels
            runtime_globals.game_sound.play("cancel")
            if self.on_cancel:
                self.on_cancel()
            self.close()
            return True
        elif event_type == "MOUSE_MOTION":
            # Mouse movement inside menu updates selection
            if event_data and "pos" in event_data and self.rect.collidepoint(event_data["pos"]):
                option_index = self._option_index_at(event_data["pos"])
                if option_index is not None and option_index != self.selected_index:
                    self.selected_index = option_index
                    self.needs_redraw = True
            return True

        # Block all other events while menu is visible
        return True

    def _option_index_at(self, pos):
        """Return the option index at a screen-coord position, or None."""
        if not self.manager:
            return None
        relative_y = pos[1] - self.rect.y
        padding = int(self.padding * self.manager.ui_scale)
        option_height = int(self.option_height * self.manager.ui_scale)
        if option_height <= 0:
            return None
        option_y = relative_y - padding
        if option_y < 0:
            return None
        row = int(option_y // option_height)
        if not 0 <= row < self._visible_count():
            return None
        idx = row + self.scroll_offset
        if 0 <= idx < len(self.options):
            return idx
        return None

    def _is_touch_mode(self):
        """True when the player is using touch / mouse input."""
        return runtime_globals.INPUT_MODE in (
            runtime_globals.TOUCH_MODE, runtime_globals.MOUSE_MODE,
        ) or getattr(runtime_globals, "IS_ANDROID", False)

    def render(self):
        """Render the menu using UI theme colors"""
        if getattr(self, 'cached_surface', None) is None or self.cached_surface.get_size() != (self.rect.width, self.rect.height):
            self.cached_surface = pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
        surface = self.cached_surface
        
        if not self.manager:
            return surface
            
        # Get theme colors
        colors = self.manager.get_theme_colors()
        bg_color = colors.get("bg", (0, 0, 0))
        fg_color = colors.get("fg", (255, 255, 255))
        highlight_color = colors.get("highlight", (255, 255, 255))
        
        # Get font using component's method
        font = self.get_font("text")
        
        # Draw background
        surface.fill(bg_color)
        
        # Draw border
        border_width = int(self.border_size * self.manager.ui_scale)
        pygame.draw.rect(surface, fg_color, surface.get_rect(), border_width)
        
        # Draw options
        padding = int(self.padding * self.manager.ui_scale)
        option_height = int(self.option_height * self.manager.ui_scale)
        
        touch_mode = self._is_touch_mode()
        visible = self._visible_count()
        start = self.scroll_offset

        for row, option in enumerate(self.options[start:start + visible]):
            i = start + row
            y_pos = padding + (row * option_height)

            is_selected = (i == self.selected_index)
            # In touch mode, every option gets a tappable highlight; the
            # selected one is rendered more strongly.
            draw_highlight = is_selected or touch_mode
            if draw_highlight:
                text_color = highlight_color if is_selected else fg_color
                highlight_rect = pygame.Rect(
                    padding // 2,
                    y_pos,
                    self.rect.width - padding,
                    option_height
                )
                alpha = 50 if is_selected else 25
                highlight_surface = pygame.Surface((highlight_rect.width, highlight_rect.height), pygame.SRCALPHA)
                highlight_surface.fill((*highlight_color, alpha))
                from utils.pygame_utils import blit_with_cache
                blit_with_cache(surface, highlight_surface, (highlight_rect.x, highlight_rect.y))
            else:
                text_color = fg_color
            
            # Render text
            text_surface = font.render(option, True, text_color)
            text_x = self.rect.width // 2 - text_surface.get_width() // 2
            text_y = y_pos + (option_height // 2) - (text_surface.get_height() // 2)
            from utils.pygame_utils import blit_with_cache
            blit_with_cache(surface, text_surface, (text_x, text_y))

        if visible < len(self.options):
            self._draw_scroll_arrows(surface, padding, option_height, visible, fg_color)

        return surface

    def _draw_scroll_arrows(self, surface, padding, option_height, visible, color):
        """Mark that the list continues above / below the visible window."""
        size = max(2, option_height // 5)
        x = self.rect.width - padding
        if self.scroll_offset > 0:
            top = padding + size
            pygame.draw.polygon(surface, color,
                                [(x - size, top), (x + size, top), (x, top - size)])
        if self.scroll_offset + visible < len(self.options):
            bottom = padding + (visible * option_height) - size
            pygame.draw.polygon(surface, color,
                                [(x - size, bottom), (x + size, bottom), (x, bottom + size)])
