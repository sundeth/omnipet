"""
TextInput Component
====================

A text input field supporting both on-screen virtual keyboard and
native Android keyboard input.

Platform behaviour:
    - **Android** (``runtime_globals.IS_ANDROID``):  Tapping the field opens
      the device's native soft keyboard via ``pygame.key.start_text_input()``.
      Characters arrive through ``pygame.TEXTINPUT`` events which are forwarded
      by the UI manager.
    - **Desktop / Embedded** (non-Android):  An on-screen virtual keyboard
      is rendered below the input field.  Navigable via mouse, touch,
      joystick d-pad, or physical keyboard.

Usage::

    text_input = TextInput(x, y, width, placeholder="Email",
                           max_length=64, keyboard_type="email")
    ui_manager.add_component(text_input)

    # Retrieve current value
    value = text_input.get_text()

Controls (virtual keyboard):
    - Mouse/Touch: Click keys
    - D-pad LEFT/RIGHT/UP/DOWN: Navigate keys
    - A / ENTER: Press selected key
    - B / CANCEL: Backspace
    - START: Confirm (triggers callback, or toggle keyboard if none)
"""

import pygame
import string
from ui.components.component import UIComponent
from core import runtime_globals


# ── Keyboard layouts ──────────────────────────────────────────────────
# Each layout is a list of rows.  Each row is a list of
# (label, action, col_span) tuples.
# - label:     Display text on the key cap.
# - action:    "char:<c>" to type character c,
#              "backspace", "shift", "symbols", "abc", "space",
#              "confirm", or "cancel".
# - col_span:  How many columns this key occupies (default 1).

def _alpha_layout():
    """Lower-case QWERTY layout."""
    return [
        [("q", "char:q", 1), ("w", "char:w", 1), ("e", "char:e", 1),
         ("r", "char:r", 1), ("t", "char:t", 1), ("y", "char:y", 1),
         ("u", "char:u", 1), ("i", "char:i", 1), ("o", "char:o", 1),
         ("p", "char:p", 1)],
        [("a", "char:a", 1), ("s", "char:s", 1), ("d", "char:d", 1),
         ("f", "char:f", 1), ("g", "char:g", 1), ("h", "char:h", 1),
         ("j", "char:j", 1), ("k", "char:k", 1), ("l", "char:l", 1)],
        [("^", "shift", 1.5), ("z", "char:z", 1), ("x", "char:x", 1),
         ("c", "char:c", 1), ("v", "char:v", 1), ("b", "char:b", 1),
         ("n", "char:n", 1), ("m", "char:m", 1), ("<", "backspace", 1.5)],
        [("123", "symbols", 2), ("_", "char:_", 1), (" ", "space", 4),
         (".", "char:.", 1), ("OK", "confirm", 2)],
    ]

def _alpha_upper_layout():
    """Upper-case QWERTY layout."""
    return [
        [("Q", "char:Q", 1), ("W", "char:W", 1), ("E", "char:E", 1),
         ("R", "char:R", 1), ("T", "char:T", 1), ("Y", "char:Y", 1),
         ("U", "char:U", 1), ("I", "char:I", 1), ("O", "char:O", 1),
         ("P", "char:P", 1)],
        [("A", "char:A", 1), ("S", "char:S", 1), ("D", "char:D", 1),
         ("F", "char:F", 1), ("G", "char:G", 1), ("H", "char:H", 1),
         ("J", "char:J", 1), ("K", "char:K", 1), ("L", "char:L", 1)],
        [("^", "shift", 1.5), ("Z", "char:Z", 1), ("X", "char:X", 1),
         ("C", "char:C", 1), ("V", "char:V", 1), ("B", "char:B", 1),
         ("N", "char:N", 1), ("M", "char:M", 1), ("<", "backspace", 1.5)],
        [("123", "symbols", 2), ("_", "char:_", 1), (" ", "space", 4),
         (".", "char:.", 1), ("OK", "confirm", 2)],
    ]

def _symbol_layout():
    """Number / symbol layout."""
    return [
        [("1", "char:1", 1), ("2", "char:2", 1), ("3", "char:3", 1),
         ("4", "char:4", 1), ("5", "char:5", 1), ("6", "char:6", 1),
         ("7", "char:7", 1), ("8", "char:8", 1), ("9", "char:9", 1),
         ("0", "char:0", 1)],
        [("@", "char:@", 1), ("#", "char:#", 1), ("$", "char:$", 1),
         ("%", "char:%", 1), ("&", "char:&", 1), ("*", "char:*", 1),
         ("-", "char:-", 1), ("+", "char:+", 1), ("=", "char:=", 1)],
        [("!", "char:!", 1), ("?", "char:?", 1), ("/", "char:/", 1),
         ("(", "char:(", 1), (")", "char:)", 1), ("'", "char:'", 1),
         ("\"", "char:\"", 1), (":", "char::", 1), ("<", "backspace", 1)],
        [("abc", "abc", 2), ("_", "char:_", 1), (" ", "space", 4),
         (".", "char:.", 1), ("OK", "confirm", 2)],
    ]

def _email_layout():
    """Email-optimised alpha layout (adds @ and . to bottom row)."""
    return [
        [("q", "char:q", 1), ("w", "char:w", 1), ("e", "char:e", 1),
         ("r", "char:r", 1), ("t", "char:t", 1), ("y", "char:y", 1),
         ("u", "char:u", 1), ("i", "char:i", 1), ("o", "char:o", 1),
         ("p", "char:p", 1)],
        [("a", "char:a", 1), ("s", "char:s", 1), ("d", "char:d", 1),
         ("f", "char:f", 1), ("g", "char:g", 1), ("h", "char:h", 1),
         ("j", "char:j", 1), ("k", "char:k", 1), ("l", "char:l", 1)],
        [("^", "shift", 1.5), ("z", "char:z", 1), ("x", "char:x", 1),
         ("c", "char:c", 1), ("v", "char:v", 1), ("b", "char:b", 1),
         ("n", "char:n", 1), ("m", "char:m", 1), ("<", "backspace", 1.5)],
        [("123", "symbols", 1.5), ("@", "char:@", 1), ("_", "char:_", 1),
         (" ", "space", 2.5), (".", "char:.", 1), (".com", "char:.com", 1.5),
         ("OK", "confirm", 1.5)],
    ]


# ======================================================================
# TextInput Component
# ======================================================================

class TextInput(UIComponent):
    """Text input field with virtual keyboard for non-Android platforms.

    The field itself is compact (FIELD_HEIGHT base units).  On non-Android
    platforms, when the field is focused a virtual keyboard is drawn as an
    overlay at the bottom of the screen — it does **not** increase the
    component's own height, so multiple TextInputs can coexist.

    Args:
        x, y:           Base position (240-space).
        width:          Base width of the text field.
        placeholder:    Ghost text shown when field is empty.
        max_length:     Maximum character count.
        keyboard_type:  ``"default"``, ``"email"``, or ``"numeric"``.
        is_password:    If True, display dots instead of characters.
        on_confirm:     Callback invoked when OK / START is pressed.
        on_change:      Callback invoked when text value changes.
    """

    # Virtual keyboard dimensions (base coordinates)
    VK_HEIGHT = 100   # Height of the keyboard overlay
    FIELD_HEIGHT = 18  # Height of the text field itself

    def __init__(self, x, y, width, placeholder="", max_length=64,
                 keyboard_type="default", is_password=False,
                 on_confirm=None, on_change=None):
        # Component height is ONLY the field — keyboard is an overlay
        super().__init__(x, y, width, self.FIELD_HEIGHT)

        self.text = ""
        self.placeholder = placeholder
        self.max_length = max_length
        self.keyboard_type = keyboard_type
        self.is_password = is_password
        self.on_confirm = on_confirm
        self.on_change = on_change
        self.focusable = True
        self.sticky_focus = True  # Hover doesn't steal focus; click outside unfocuses
        self.is_dynamic = True  # Redraw every frame (cursor blink)
        # A click that focuses this field must not also be treated as an "A"
        # activation — otherwise the UI manager would press the currently
        # selected virtual key (row 0, col 0 = "q") and type a stray character.
        self.activate_on_click = False

        # Cursor blink
        self._cursor_visible = True
        self._cursor_timer = 0
        self._cursor_blink_rate = 30  # frames between blinks

        # Virtual keyboard state (non-Android only)
        self._shifted = False        # Caps lock / shift toggle
        self._showing_symbols = False
        self._vk_row = 0             # Currently focused row
        self._vk_col = 0             # Currently focused column
        self._layout = self._get_layout()

        # Android native keyboard
        self._android_active = False

        runtime_globals.game_console.log(
            f"[TextInput] Created: placeholder='{placeholder}', "
            f"type={keyboard_type}, android={runtime_globals.IS_ANDROID}")

    # ── Layout helpers ────────────────────────────────────────────────

    def _get_layout(self):
        """Return the current keyboard layout based on state."""
        if self._showing_symbols:
            return _symbol_layout()
        if self.keyboard_type == "email" and not self._shifted:
            return _email_layout()
        return _alpha_upper_layout() if self._shifted else _alpha_layout()

    def _refresh_layout(self):
        """Recalculate layout and clamp cursor."""
        self._layout = self._get_layout()
        self._vk_row = min(self._vk_row, len(self._layout) - 1)
        row = self._layout[self._vk_row]
        self._vk_col = min(self._vk_col, len(row) - 1)
        self.needs_redraw = True

    # ── Public API ────────────────────────────────────────────────────

    def get_text(self):
        """Return the current input value."""
        return self.text

    def set_text(self, value):
        """Set the input value programmatically."""
        self.text = value[:self.max_length]
        self.needs_redraw = True

    def clear(self):
        """Clear the input field."""
        self.text = ""
        self.needs_redraw = True
        if self.on_change:
            self.on_change(self.text)

    # ── Input handling ────────────────────────────────────────────────

    def _type_char(self, ch):
        """Append character(s) to the text buffer."""
        if len(self.text) + len(ch) <= self.max_length:
            self.text += ch
            self.needs_redraw = True
            runtime_globals.game_sound.play("menu")
            if self.on_change:
                self.on_change(self.text)

    def _backspace(self):
        """Delete the last character."""
        if self.text:
            self.text = self.text[:-1]
            self.needs_redraw = True
            runtime_globals.game_sound.play("cancel")
            if self.on_change:
                self.on_change(self.text)

    def _press_key(self):
        """Execute the action of the currently selected virtual key."""
        if runtime_globals.IS_ANDROID:
            return
        row = self._layout[self._vk_row]
        if self._vk_col >= len(row):
            return
        _, action, _ = row[self._vk_col]
        self._execute_action(action)

    def _execute_action(self, action):
        """Run a virtual key action string."""
        if action.startswith("char:"):
            self._type_char(action[5:])
            # Auto-unshift after typing a character
            if self._shifted and not self._showing_symbols:
                self._shifted = False
                self._refresh_layout()
        elif action == "backspace":
            self._backspace()
        elif action == "shift":
            self._shifted = not self._shifted
            self._showing_symbols = False
            self._refresh_layout()
            runtime_globals.game_sound.play("menu")
        elif action == "symbols":
            self._showing_symbols = True
            self._shifted = False
            self._refresh_layout()
            runtime_globals.game_sound.play("menu")
        elif action == "abc":
            self._showing_symbols = False
            self._refresh_layout()
            runtime_globals.game_sound.play("menu")
        elif action == "space":
            self._type_char(" ")
        elif action == "confirm":
            runtime_globals.game_sound.play("menu")
            if self.on_confirm:
                self.on_confirm(self.text)
        elif action == "cancel":
            self._backspace()

    # ── Android native keyboard ───────────────────────────────────────

    def _activate_android_keyboard(self):
        """Open the native Android keyboard."""
        if runtime_globals.IS_ANDROID and not self._android_active:
            try:
                pygame.key.start_text_input()
                self._android_active = True
                runtime_globals.game_console.log("[TextInput] Android keyboard opened")
            except Exception as e:
                runtime_globals.game_console.log(
                    f"[TextInput] Failed to open Android keyboard: {e}")

    def _deactivate_android_keyboard(self):
        """Close the native Android keyboard."""
        if runtime_globals.IS_ANDROID and self._android_active:
            try:
                pygame.key.stop_text_input()
                self._android_active = False
                runtime_globals.game_console.log("[TextInput] Android keyboard closed")
            except Exception as e:
                runtime_globals.game_console.log(
                    f"[TextInput] Failed to close Android keyboard: {e}")

    # ── Focus callbacks ───────────────────────────────────────────────

    def on_focus_gained(self):
        """Called when this component gains focus."""
        if runtime_globals.IS_ANDROID:
            self._activate_android_keyboard()
        self._cursor_visible = True
        self._cursor_timer = 0
        self.needs_redraw = True

    def on_focus_lost(self):
        """Called when this component loses focus."""
        if runtime_globals.IS_ANDROID:
            self._deactivate_android_keyboard()
        self.needs_redraw = True

    # ── Event handling ────────────────────────────────────────────────

    def handle_event(self, event):
        """Handle input events from the game's event system."""
        if not self.visible or not self.focused:
            return False

        if not isinstance(event, tuple) or len(event) != 2:
            # Raw pygame events (TEXTINPUT / KEYDOWN).  Duck-type on the
            # ``type`` attribute instead of isinstance(pygame.event.Event):
            # on some pygame builds (notably the Android one) Event is a
            # factory function, not a class, so isinstance raises TypeError.
            if hasattr(event, 'type'):
                return self._handle_pygame_event(event)
            return False

        event_type, event_data = event

        # ── Android: only field-level actions ─────────────────────────
        if runtime_globals.IS_ANDROID:
            if event_type in ("A", "CONFIRM", "START"):
                if self.on_confirm:
                    self.on_confirm(self.text)
                return True
            if event_type == "CANCEL":
                self._backspace()
                return True
            return False

        # ── Non-Android: virtual keyboard navigation ──────────────────
        if event_type == "UP":
            self._vk_row = max(0, self._vk_row - 1)
            self._clamp_col()
            self.needs_redraw = True
            runtime_globals.game_sound.play("menu")
            return True

        if event_type == "DOWN":
            self._vk_row = min(len(self._layout) - 1, self._vk_row + 1)
            self._clamp_col()
            self.needs_redraw = True
            runtime_globals.game_sound.play("menu")
            return True

        if event_type == "LEFT":
            row = self._layout[self._vk_row]
            self._vk_col = (self._vk_col - 1) % len(row)
            self.needs_redraw = True
            runtime_globals.game_sound.play("menu")
            return True

        if event_type == "RIGHT":
            row = self._layout[self._vk_row]
            self._vk_col = (self._vk_col + 1) % len(row)
            self.needs_redraw = True
            runtime_globals.game_sound.play("menu")
            return True

        if event_type in ("A", "CONFIRM"):
            self._press_key()
            return True

        if event_type in ("B", "CANCEL"):
            self._backspace()
            return True

        if event_type == "START":
            if self.on_confirm:
                runtime_globals.game_sound.play("menu")
                self.on_confirm(self.text)
            return True

        # ── Mouse / Touch click on virtual key ────────────────────────
        if event_type == "LCLICK" and event_data and "pos" in event_data:
            return self._handle_click(event_data["pos"])

        return False

    def _handle_pygame_event(self, event):
        """Handle raw pygame events (TEXTINPUT for Android keyboard)."""
        if event.type == pygame.TEXTINPUT:
            self._type_char(event.text)
            return True
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_BACKSPACE:
                self._backspace()
                return True
            if event.key == pygame.K_RETURN:
                if self.on_confirm:
                    self.on_confirm(self.text)
                return True
        return False

    def _handle_click(self, pos):
        """Handle a mouse/touch click on the text field itself."""
        if not self.rect or runtime_globals.IS_ANDROID:
            return False

        if not self.rect.collidepoint(pos):
            return False

        # Click on the field — already focused, just consume the event
        return True

    def handle_keyboard_click(self, pos, screen_size):
        """Check if *pos* hits the virtual-keyboard overlay and act on it.

        Call this from the scene's event handler for **all** click
        events when a TextInput is focused.  *screen_size* should be
        ``(width, height)`` of the display surface so the overlay
        position can be calculated.

        Returns True if the click was consumed.
        """
        if not self.focused:
            return False
        if not runtime_globals.use_virtual_keyboard():
            return False

        scale = self.manager.ui_scale if self.manager else 1
        sw, sh = screen_size
        kb_h = int(self.VK_HEIGHT * scale)
        kb_y_start = sh - kb_h

        # Check vertical bounds
        if pos[1] < kb_y_start or pos[1] > sh:
            return False

        local_x = pos[0]
        local_y = pos[1] - kb_y_start

        # Determine which row was clicked
        row_count = len(self._layout)
        row_h = kb_h / row_count
        clicked_row = int(local_y / row_h)
        clicked_row = min(clicked_row, row_count - 1)

        # Determine which column was clicked
        row = self._layout[clicked_row]
        total_span = sum(span for _, _, span in row)
        key_unit_w = sw / total_span
        acc_x = 0.0
        for col_idx, (label, action, span) in enumerate(row):
            key_w = span * key_unit_w
            if local_x < acc_x + key_w:
                self._vk_row = clicked_row
                self._vk_col = col_idx
                self._execute_action(action)
                self.needs_redraw = True
                return True
            acc_x += key_w

        return True

    def _clamp_col(self):
        """Clamp _vk_col to valid range for the current row."""
        row = self._layout[self._vk_row]
        if self._vk_col >= len(row):
            self._vk_col = len(row) - 1

    # ── Update (cursor blink) ─────────────────────────────────────────

    def update(self):
        """Called every frame — blink the cursor."""
        super().update()
        if self.focused:
            self._cursor_timer += 1
            if self._cursor_timer >= self._cursor_blink_rate:
                self._cursor_timer = 0
                self._cursor_visible = not self._cursor_visible
                self.needs_redraw = True

    # ── Rendering ─────────────────────────────────────────────────────

    def render(self):
        """Render the text field only.  The virtual keyboard is drawn
        separately via ``draw_keyboard_overlay()`` which the scene calls
        after the UI manager draw pass."""
        scale = self.manager.ui_scale if self.manager else 1
        surface = pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
        colors = self.get_colors()

        field_h = int(self.FIELD_HEIGHT * scale)
        self._render_field(surface, colors, field_h, scale)

        return surface

    def draw_keyboard_overlay(self, target_surface):
        """Draw the virtual keyboard at the bottom of *target_surface*.

        Call this from the scene's ``draw()`` method **after** the UI
        manager has drawn.  Only draws when focused and the device has no
        physical keyboard (touch / GPIO modes).  PCs with a real keyboard
        and Android (which uses the system IME) skip the overlay.
        """
        if not self.focused:
            return
        if not runtime_globals.use_virtual_keyboard():
            return

        scale = self.manager.ui_scale if self.manager else 1
        colors = self.get_colors()
        kb_h = int(self.VK_HEIGHT * scale)
        kb_w = target_surface.get_width()

        # Create keyboard surface
        kb_surface = pygame.Surface((kb_w, kb_h), pygame.SRCALPHA)
        self._render_keyboard(kb_surface, colors, 0, scale, kb_w)

        # Blit at bottom of target surface
        y = target_surface.get_height() - kb_h
        target_surface.blit(kb_surface, (0, y))

    def _render_field(self, surface, colors, field_h, scale):
        """Draw the text input field at the top."""
        field_rect = pygame.Rect(0, 0, self.rect.width, field_h)
        border_w = max(1, scale)

        # Background
        bg = (40, 40, 40) if self.focused else (25, 25, 25)
        pygame.draw.rect(surface, bg, field_rect, border_radius=max(1, 3 * scale))

        # Border
        border_color = colors.get("fg", (200, 200, 200)) if self.focused else (80, 80, 80)
        pygame.draw.rect(surface, border_color, field_rect, border_w,
                         border_radius=max(1, 3 * scale))

        # Text or placeholder.  ProggySmall renders pixel-perfect only at
        # multiples of 16 (its design grid); off-grid sizes look ragged now
        # that all text is drawn without anti-aliasing.
        font = self.get_font(custom_size=16 * scale)
        if self.text:
            display = "*" * len(self.text) if self.is_password else self.text
            text_color = (255, 255, 255)
        else:
            display = self.placeholder
            text_color = (120, 120, 120)

        # Truncate display to fit width (show rightmost characters)
        padding = int(4 * scale)
        max_text_w = self.rect.width - padding * 2
        while font.size(display)[0] > max_text_w and len(display) > 1:
            display = display[1:]

        text_surf = font.render(display, True, text_color)
        text_y = (field_h - text_surf.get_height()) // 2
        surface.blit(text_surf, (padding, text_y))

        # Cursor
        if self.focused and self._cursor_visible:
            cursor_x = padding + font.size(display)[0] + max(1, scale)
            cursor_h = int(field_h * 0.6)
            cursor_y = (field_h - cursor_h) // 2
            pygame.draw.line(surface, (255, 255, 255),
                             (cursor_x, cursor_y),
                             (cursor_x, cursor_y + cursor_h),
                             max(1, scale))

    def _render_keyboard(self, surface, colors, field_top_h, scale,
                         override_width=None):
        """Draw the virtual keyboard grid below the text field.

        Args:
            override_width: If given, use this pixel width for the keyboard
                            instead of ``self.rect.width``.
        """
        kb_x = 0
        kb_y = field_top_h
        kb_w = override_width if override_width is not None else self.rect.width
        kb_h = int(self.VK_HEIGHT * scale)

        # Keyboard background
        pygame.draw.rect(surface, (20, 20, 20),
                         pygame.Rect(kb_x, kb_y, kb_w, kb_h))

        row_count = len(self._layout)
        row_h = kb_h / row_count
        key_pad = max(1, scale)  # Padding between keys

        # 16 * scale = ProggySmall's pixel-perfect grid (ink is ~8px, so it
        # still fits the 20-base-px key rows).
        font = self.get_font(custom_size=16 * scale)

        for r_idx, row in enumerate(self._layout):
            total_span = sum(span for _, _, span in row)
            key_unit_w = kb_w / total_span
            acc_x = float(kb_x)
            y_top = kb_y + int(r_idx * row_h)
            y_h = int(row_h)

            for c_idx, (label, action, span) in enumerate(row):
                kw = int(span * key_unit_w)
                key_rect = pygame.Rect(int(acc_x) + key_pad,
                                       y_top + key_pad,
                                       kw - key_pad * 2,
                                       y_h - key_pad * 2)

                is_selected = (r_idx == self._vk_row and c_idx == self._vk_col
                               and self.focused)

                # Key colours
                if is_selected:
                    key_bg = (255, 255, 255)
                    key_fg = (0, 0, 0)
                elif action in ("shift", "symbols", "abc"):
                    key_bg = (60, 60, 80)
                    key_fg = (200, 200, 255)
                elif action == "backspace":
                    key_bg = (80, 40, 40)
                    key_fg = (255, 180, 180)
                elif action == "confirm":
                    key_bg = (40, 80, 40)
                    key_fg = (180, 255, 180)
                else:
                    key_bg = (50, 50, 50)
                    key_fg = (200, 200, 200)

                pygame.draw.rect(surface, key_bg, key_rect,
                                 border_radius=max(1, 2 * scale))

                # Label
                lbl_surf = font.render(label, True, key_fg)
                lbl_rect = lbl_surf.get_rect(center=key_rect.center)
                surface.blit(lbl_surf, lbl_rect)

                acc_x += kw
