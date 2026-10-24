"""
Code Entry Component
=====================

A component for entering fixed-length alphanumeric codes.
Works like a horizontal list where each position can be edited.

Usage:
    code_entry = CodeEntry(x, y, length=4)
    ui_manager.add_component(code_entry)

Controls:
    Mouse:        LCLICK on a box cycles forward; RCLICK cycles backward.
    Keyboard:     LEFT/RIGHT move between boxes; DOWN cycles forward,
                  UP cycles backward; A also cycles forward.
    Touch mode:   A virtual keyboard overlay is drawn at the bottom of the
                  screen with all 0-9, A-Z keys plus backspace and OK.
                  Tapping a key types it into the selected box and advances.
                  The host scene must call ``draw_keyboard_overlay`` and
                  forward clicks via ``handle_keyboard_click`` (mirroring
                  how TextInput is integrated).
"""

import pygame
import string
from ui.components.component import UIComponent
from core import runtime_globals


class CodeEntry(UIComponent):
    # Virtual keyboard rendering parameters (in base coordinates, scaled by manager)
    VK_HEIGHT = 96
    # Alphanumeric keypad (device pairing / Discord linking codes contain letters)
    VK_ROWS = [
        list("0123456789"),
        list("ABCDEFGHIJ"),
        list("KLMNOPQRST"),
        list("UVWXYZ") + ["BACK", "OK"],
    ]
    # Phone-style digit-only keypad (email verification codes are always numeric)
    VK_ROWS_NUMERIC = [
        list("123"),
        list("456"),
        list("789"),
        ["BACK", "0", "OK"],
    ]

    def __init__(self, x, y, length=4, callback=None, on_focus_callback=None,
                 numeric=False, char_w=40, char_h=50, spacing=10):
        # Size based on length (each char is char_w x char_h, base coordinates)
        self.base_char_w = char_w
        self.base_char_h = char_h
        self.base_spacing = spacing
        total_w = (self.base_char_w * length) + (self.base_spacing * (length - 1))

        super().__init__(x, y, total_w, self.base_char_h)

        self.length = length
        self.callback = callback
        # Optional callback fired when the entry gains focus — used by the
        # scene to clear stale "Invalid code" messages on the next attempt.
        self.on_focus_callback = on_focus_callback

        # Numeric-only mode: the email verification code is always digits, so
        # restrict the charset and use the digit keypad.  Alphanumeric mode
        # stays the default for device-pairing and Discord-link codes which
        # include letters.
        self.numeric = numeric
        self.charset = string.digits if numeric else (string.digits + string.ascii_uppercase)
        self.default_char = '0' if numeric else 'A'
        self.vk_rows = self.VK_ROWS_NUMERIC if numeric else self.VK_ROWS

        # State
        self.chars = [self.default_char] * length  # Default to first charset char
        self.selected_index = 0  # Currently selected character position (for keyboard)
        self.mouse_over_index = -1  # Mouse hover tracking

        self.focusable = True
        self.sticky_focus = True  # Same focus rules as TextInput
        self.shadow_mode = "component"
        # A focus click must not also cycle the selected box; cycling only
        # happens once the entry is already focused.  See the UI manager's
        # click-activation guard (activate_on_click).
        self.activate_on_click = False

        runtime_globals.game_console.log(f"[CodeEntry] Created length={length} numeric={numeric}")

    def reset(self):
        """Reset every box to the default character and select the first one.

        Marks the component for redraw; callers that need the change to appear
        immediately (rather than on the next focus/hover) should also set the
        UI manager's ``master_ui_dirty`` flag so the cached surface rebuilds.
        """
        self.chars = [self.default_char] * self.length
        self.selected_index = 0
        self.mouse_over_index = -1
        self.needs_redraw = True

    def on_focus_gained(self):
        """Notify the host scene so it can clear any prior error state."""
        if self.on_focus_callback:
            try:
                self.on_focus_callback()
            except Exception as exc:
                runtime_globals.game_console.log(
                    f"[CodeEntry] on_focus_callback error: {exc}")

    def get_text(self):
        """Get current code as string."""
        return "".join(self.chars)
    
    def _get_char_rect(self, index):
        """Get the rect for a specific character box (in component local coordinates)."""
        char_x = index * (self.base_char_w + self.base_spacing)
        return pygame.Rect(char_x, 0, self.base_char_w, self.base_char_h)
    
    def _cycle_character(self, index, direction: int = 1):
        """Cycle to the next/previous character in the charset for the given index.

        Args:
            index: Position to cycle.
            direction: +1 = next character (A->B), -1 = previous (B->A).
        """
        if 0 <= index < self.length:
            current_char = self.chars[index]
            char_idx = self.charset.index(current_char)
            new_idx = (char_idx + direction) % len(self.charset)
            self.chars[index] = self.charset[new_idx]
            self.needs_redraw = True
            runtime_globals.game_sound.play("menu")
            runtime_globals.game_console.log(
                f"[CodeEntry] Character {index} cycled to {self.chars[index]}")

    def _set_character(self, index, ch):
        """Set the char at *index* to *ch* (must be in the charset)."""
        if 0 <= index < self.length and ch in self.charset:
            self.chars[index] = ch
            self.needs_redraw = True
            runtime_globals.game_sound.play("menu")

    def _handle_pygame_event(self, event):
        """Capture printable keys and Backspace from a real keyboard.

        Letters and digits set the current box and advance.  Backspace
        clears the current/previous box and steps back.  Enter triggers
        the confirm callback (if set).
        """
        if event.type == pygame.TEXTINPUT:
            ch = (event.text or "").upper()
            if ch and ch[0] in self.charset:
                self._set_character(self.selected_index, ch[0])
                if self.selected_index < self.length - 1:
                    self.selected_index += 1
                return True
            return False
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_BACKSPACE:
                # Clear current box; step back if it was already the default
                if self.chars[self.selected_index] != self.default_char:
                    self._set_character(self.selected_index, self.default_char)
                else:
                    self.selected_index = max(0, self.selected_index - 1)
                    self._set_character(self.selected_index, self.default_char)
                return True
            if event.key == pygame.K_RETURN:
                if self.callback:
                    self.callback(self.get_text())
                return True
            if event.key == pygame.K_LEFT:
                self.selected_index = (self.selected_index - 1) % self.length
                self.needs_redraw = True
                return True
            if event.key == pygame.K_RIGHT:
                self.selected_index = (self.selected_index + 1) % self.length
                self.needs_redraw = True
                return True
        return False

    def update(self):
        """Update component state including mouse hover detection."""
        super().update()
        
        # Handle mouse hover for visual feedback
        if (runtime_globals.INPUT_MODE in [runtime_globals.MOUSE_MODE, runtime_globals.TOUCH_MODE]) and self.focused:
            self._handle_mouse_hover()
    
    def _handle_mouse_hover(self):
        """Track which character box the mouse is over."""
        if not self.rect:
            return
        
        mouse_pos = runtime_globals.game_input.get_mouse_position()
        
        # Check if mouse is within component bounds
        if not self.rect.collidepoint(mouse_pos):
            if self.mouse_over_index != -1:
                self.mouse_over_index = -1
                self.needs_redraw = True
            return
        
        # Calculate which character box is being hovered
        local_x = mouse_pos[0] - self.rect.x
        index = int(local_x // (self.base_char_w + self.base_spacing))
        
        if 0 <= index < self.length:
            if self.mouse_over_index != index:
                self.mouse_over_index = index
                self.needs_redraw = True
        else:
            if self.mouse_over_index != -1:
                self.mouse_over_index = -1
                self.needs_redraw = True

    def handle_event(self, event):
        """Handle input events."""
        if not self.visible or not self.focused:
            return False

        # Raw pygame events for physical-keyboard capture (PC and Android IME).
        # Duck-type on ``type`` rather than isinstance(pygame.event.Event):
        # on some pygame builds Event is a factory function, not a class, and
        # isinstance against it raises TypeError.
        if not isinstance(event, tuple) and hasattr(event, 'type'):
            return self._handle_pygame_event(event)

        # Event is a tuple: (event_type, event_data)
        if not isinstance(event, tuple) or len(event) != 2:
            return False

        event_type, event_data = event
        
        # Mouse/Touch: LCLICK cycles forward, RCLICK cycles backward
        if event_type in ("LCLICK", "RCLICK"):
            if event_data and "pos" in event_data:
                mouse_pos = event_data["pos"]
                if self.rect.collidepoint(mouse_pos):
                    local_x = mouse_pos[0] - self.rect.x
                    clicked_index = int(local_x // (self.base_char_w + self.base_spacing))
                    if 0 <= clicked_index < self.length:
                        direction = 1 if event_type == "LCLICK" else -1
                        runtime_globals.game_console.log(
                            f"[CodeEntry] {event_type} box {clicked_index} dir={direction}")
                        self._cycle_character(clicked_index, direction)
                        self.selected_index = clicked_index
                        return True

        # Keyboard: LEFT/RIGHT navigate boxes
        elif event_type == "LEFT":
            self.selected_index = (self.selected_index - 1) % self.length
            runtime_globals.game_sound.play("menu")
            runtime_globals.game_console.log(f"[CodeEntry] Selected index: {self.selected_index}")
            self.needs_redraw = True
            return True

        elif event_type == "RIGHT":
            self.selected_index = (self.selected_index + 1) % self.length
            runtime_globals.game_sound.play("menu")
            runtime_globals.game_console.log(f"[CodeEntry] Selected index: {self.selected_index}")
            self.needs_redraw = True
            return True

        # DOWN cycles forward, UP cycles backward
        elif event_type == "DOWN":
            self._cycle_character(self.selected_index, 1)
            return True

        elif event_type == "UP":
            self._cycle_character(self.selected_index, -1)
            return True

        # A advances the character (forward)
        elif event_type == "A":
            self._cycle_character(self.selected_index, 1)
            return True

        return False

    def render(self):
        """Render the code entry widgets."""
        surface = pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
        
        colors = self.get_colors()
        font = self.get_font("title", 32)
        
        char_w = self.base_char_w
        char_h = self.base_char_h
        spacing = self.base_spacing
        
        for i in range(self.length):
            char_x = i * (char_w + spacing)
            
            # Draw char box
            box_rect = pygame.Rect(char_x, 0, char_w, char_h)
            
            # Determine if this box should be highlighted
            is_selected = (i == self.selected_index) and self.focused
            is_hovered = (i == self.mouse_over_index) and runtime_globals.INPUT_MODE in [runtime_globals.MOUSE_MODE, runtime_globals.TOUCH_MODE]
            
            # Visual settings based on state
            if is_selected:
                # Selected: White Background, Black Text (for keyboard mode)
                bg_color = (255, 255, 255) 
                text_color = (0, 0, 0)     
                border_color = (255, 255, 255) 
            elif is_hovered:
                # Hovered: Light grey background (for mouse mode)
                bg_color = (100, 100, 100)
                text_color = (255, 255, 255)
                border_color = (200, 200, 200)
            elif self.focused:
                # Focused but not selected: Dark grey
                bg_color = (60, 60, 60)
                text_color = (200, 200, 200)
                border_color = (100, 100, 100)
            else:
                # Unfocused: Very dark
                bg_color = colors.get('bg', (20, 20, 20))
                text_color = colors.get('fg', (150, 150, 150))
                border_color = colors.get('fg', (80, 80, 80))
            
            # Background
            pygame.draw.rect(surface, bg_color, box_rect, border_radius=5)
            # Border
            pygame.draw.rect(surface, border_color, box_rect, 2, border_radius=5)
            
            # Selection indicator underline
            if is_selected:
                pygame.draw.line(surface, text_color, 
                               (char_x + 8, char_h - 8), 
                               (char_x + char_w - 8, char_h - 8), 3)
            
            # Text
            char_surf = font.render(self.chars[i], True, text_color)
            char_rect = char_surf.get_rect(center=(char_x + char_w//2, char_h//2))
            surface.blit(char_surf, char_rect)

        return surface

    # ── Touch-mode virtual keyboard ──────────────────────────────────

    def _keyboard_geometry(self, screen_size):
        """Return (kb_rect, scale, row_h) for the keyboard overlay.

        The keyboard occupies the bottom VK_HEIGHT (in base coords, scaled
        by the manager's ui_scale) of the screen.
        """
        scale = self.manager.ui_scale if self.manager else 1
        sw, sh = screen_size
        kb_h = int(self.VK_HEIGHT * scale)
        kb_rect = pygame.Rect(0, sh - kb_h, sw, kb_h)
        row_h = kb_h / len(self.vk_rows)
        return kb_rect, scale, row_h

    def draw_keyboard_overlay(self, target_surface):
        """Draw a 0-9, A-Z + BACK/OK virtual keyboard at the bottom.

        Mirrors TextInput.draw_keyboard_overlay so the host scene can
        invoke it the same way.  Skipped on Android where the system
        keyboard is used instead.
        """
        if runtime_globals.IS_ANDROID or not self.focused:
            return
        if not runtime_globals.use_virtual_keyboard():
            return

        screen_size = target_surface.get_size()
        kb_rect, scale, row_h = self._keyboard_geometry(screen_size)

        # Backdrop
        backdrop = pygame.Surface((kb_rect.width, kb_rect.height), pygame.SRCALPHA)
        backdrop.fill((20, 20, 20, 230))
        target_surface.blit(backdrop, kb_rect.topleft)

        # ProggySmall at its 16px design grid -- the pygame default font at
        # arbitrary sizes renders ragged with anti-aliasing disabled.
        from utils.asset_utils import font_load
        from ui.ui_constants import TEXT_FONT
        font = font_load(TEXT_FONT, 16 * max(1, int(round(scale))))

        for r, row in enumerate(self.vk_rows):
            key_w = kb_rect.width / len(row)
            y = kb_rect.y + r * row_h
            for c, label in enumerate(row):
                x = kb_rect.x + c * key_w
                key_rect = pygame.Rect(int(x) + 1, int(y) + 1,
                                       int(key_w) - 2, int(row_h) - 2)
                # Highlight OK / BACK distinctly
                if label == "OK":
                    bg = (60, 130, 60)
                elif label == "BACK":
                    bg = (130, 60, 60)
                else:
                    bg = (60, 60, 60)
                pygame.draw.rect(target_surface, bg, key_rect, border_radius=4)
                pygame.draw.rect(target_surface, (180, 180, 180),
                                 key_rect, 1, border_radius=4)
                text_surf = font.render(label, True, (240, 240, 240))
                text_rect = text_surf.get_rect(center=key_rect.center)
                target_surface.blit(text_surf, text_rect)

    def handle_keyboard_click(self, pos, screen_size):
        """Resolve a click at *pos* to a key press on the virtual keyboard.

        Returns True if the click hit a key (and was consumed), False otherwise.
        Mirrors TextInput.handle_keyboard_click.
        """
        if runtime_globals.IS_ANDROID or not self.focused:
            return False
        if not runtime_globals.use_virtual_keyboard():
            return False

        kb_rect, _, row_h = self._keyboard_geometry(screen_size)
        if not kb_rect.collidepoint(pos):
            return False

        local_y = pos[1] - kb_rect.y
        row_idx = int(local_y // row_h)
        if row_idx < 0 or row_idx >= len(self.vk_rows):
            return False
        row = self.vk_rows[row_idx]
        key_w = kb_rect.width / len(row)
        local_x = pos[0] - kb_rect.x
        col_idx = int(local_x // key_w)
        if col_idx < 0 or col_idx >= len(row):
            return False
        label = row[col_idx]

        if label == "OK":
            # Trigger callback / let scene confirm — defocus by leaving as-is
            if self.callback:
                self.callback(self.get_text())
            runtime_globals.game_sound.play("menu")
        elif label == "BACK":
            # Reset selected box back to the default char and step back one
            self._set_character(self.selected_index, self.default_char)
            self.selected_index = max(0, self.selected_index - 1)
        else:
            # Single-letter / digit key
            self._set_character(self.selected_index, label)
            # Auto-advance to the next box
            if self.selected_index < self.length - 1:
                self.selected_index += 1
        return True
