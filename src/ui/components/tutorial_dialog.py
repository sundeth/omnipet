"""
Tutorial Dialog Component
Displays tutorial messages with fade in/out animations.
Full UI component using the UIManager theme system.
"""

import pygame
from ui.components.component import UIComponent


class TutorialDialog(UIComponent):
    """
    Dialog box for tutorial messages.
    Supports fade in/out, word wrapping, and colored text markers.
    Integrates with UIManager theme and font systems.
    """
    
    # Dialog states
    STATE_HIDDEN = 0
    STATE_FADE_IN = 1
    STATE_VISIBLE = 2
    STATE_FADE_OUT = 3
    STATE_WAITING = 4  # Waiting for input to proceed
    
    def __init__(self, x=10, y=170, width=220, height=60, use_screen_coords=True):
        """Initialize the tutorial dialog.
        
        Args:
            x, y: Position in base 240x240 coordinates (or screen coords if use_screen_coords)
            width, height: Size in base coordinates
            use_screen_coords: If True, position relative to screen edges, not UI area
        """
        super().__init__(x, y, width, height)
        
        # Use screen coordinates for positioning (ignores UI offset)
        self.use_screen_coordinates = use_screen_coords
        
        # Dialog state
        self.state = self.STATE_HIDDEN
        self.messages = []  # Queue of messages to display
        self.current_message = ""
        self.alpha = 0
        self.fade_frames = 30  # Will be updated when manager is set
        self.fade_counter = 0
        
        # Callback when message is complete
        self.on_complete = None
        
        # Text rendering cache
        self.text_surfaces = []
        # The opaque box, rebuilt only when what it shows changes; each frame
        # only its alpha changes (the fade). Re-rendering the wrapped text
        # every frame cost the Pi Zero 2W several ms per frame.
        self._box_surface = None
        self._box_key = None
        
        # Not focusable (controlled by step system)
        self.focusable = False
        
        # Always redraw (handles fade animation)
        self.is_dynamic = True
        
    def show_message(self, message: str, on_complete=None):
        """
        Show a single message with fade in.
        
        Args:
            message: The message to display. Use *word* for red highlighting.
            on_complete: Callback when player dismisses the message.
        """
        self.messages = [message]
        self.on_complete = on_complete
        self._start_next_message()
        
    def show_messages(self, messages: list, on_complete=None):
        """
        Show multiple messages in sequence.
        
        Args:
            messages: List of messages to display.
            on_complete: Callback when all messages are dismissed.
        """
        self.messages = list(messages)
        self.on_complete = on_complete
        self._start_next_message()
        
    def _start_next_message(self):
        """Start displaying the next message in the queue."""
        if self.messages:
            self.current_message = self.messages.pop(0)
            self.state = self.STATE_FADE_IN
            self.fade_counter = 0
            self.alpha = 0
            self.needs_redraw = True
        else:
            self.state = self.STATE_HIDDEN
            if self.on_complete:
                callback = self.on_complete
                self.on_complete = None
                callback()
    
    def _render_wrapped_text(self, text: str, font, max_width: int):
        """Render text with word wrapping and color markers."""
        if not self.manager:
            return []
            
        theme_colors = self.manager.get_theme_colors()
        text_color = theme_colors.get("fg", (255, 255, 255))
        highlight_color = (255, 100, 100)  # Red for *marked* words
        
        words = text.split(' ')
        lines = []
        current_line = []
        current_width = 0
        space_width = font.size(' ')[0]
        
        for word in words:
            # Check for color markers
            if word.startswith('*') and word.endswith('*') and len(word) > 2:
                clean_word = word[1:-1]
                word_surface = font.render(clean_word, True, highlight_color)
            elif word.startswith('*'):
                clean_word = word[1:]
                word_surface = font.render(clean_word, True, highlight_color)
            elif word.endswith('*'):
                clean_word = word[:-1]
                word_surface = font.render(clean_word, True, highlight_color)
            else:
                word_surface = font.render(word, True, text_color)
            
            word_width = word_surface.get_width()
            
            if current_width + word_width > max_width and current_line:
                # Start new line
                lines.append(current_line)
                current_line = [(word, word_surface)]
                current_width = word_width + space_width
            else:
                current_line.append((word, word_surface))
                current_width += word_width + space_width
        
        if current_line:
            lines.append(current_line)
        
        return lines
    
    def update(self):
        """Update dialog animation state."""
        super().update()
        
        if not self.manager:
            return
            
        # Update fade frames based on configuration
        from core import game_globals
        self.fade_frames = game_globals.configuration.frame_rate // 2
        
        if self.state == self.STATE_FADE_IN:
            self.fade_counter += 1
            self.alpha = min(255, int(255 * self.fade_counter / self.fade_frames))
            if self.fade_counter >= self.fade_frames:
                self.state = self.STATE_WAITING
                self.alpha = 255
            self.needs_redraw = True
                
        elif self.state == self.STATE_FADE_OUT:
            self.fade_counter += 1
            self.alpha = max(0, int(255 * (1 - self.fade_counter / self.fade_frames)))
            if self.fade_counter >= self.fade_frames:
                self._start_next_message()
            self.needs_redraw = True
    
    def handle_event(self, event) -> bool:
        """
        Handle input events.
        Returns True if event was consumed.
        """
        if self.state != self.STATE_WAITING:
            return False
            
        event_type, event_data = event
        
        if event_type in ["A", "B", "LCLICK"]:
            # Play menu sound when advancing dialog
            from core import runtime_globals
            if hasattr(runtime_globals, 'game_sound') and runtime_globals.game_sound:
                runtime_globals.game_sound.play("menu")
            
            # Dismiss current message
            self.state = self.STATE_FADE_OUT
            self.fade_counter = 0
            self.needs_redraw = True
            return True
            
        return False
    
    def render(self):
        """Render the dialog box to a surface."""
        if self.state == self.STATE_HIDDEN or not self.manager:
            return None
        
        # Get theme colors
        theme_colors = self.manager.get_theme_colors()
        bg_color = theme_colors.get("bg", (0, 0, 0))
        border_color = theme_colors.get("fg", (255, 255, 255))

        key = (self.current_message, self.rect.size, tuple(bg_color), tuple(border_color),
               self.manager.ui_scale)
        if key != self._box_key or self._box_surface is None:
            self._box_surface = self._render_box(bg_color, border_color)
            self._box_key = key
        surface = self._box_surface
        # Apply alpha to entire surface
        surface.set_alpha(self.alpha if self.alpha < 255 else 255)
        return surface

    def _render_box(self, bg_color, border_color):
        """The dialog box with its text, fully opaque."""
        # Create surface
        surface = pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
        
        # Draw background with border
        border_width = self.manager.get_border_size() if self.manager else 2
        corner_radius = self.manager.scale_value(5) if self.manager else 5
        
        # Background with alpha
        bg_with_alpha = bg_color + (255,)
        pygame.draw.rect(surface, bg_with_alpha, 
                        (0, 0, self.rect.width, self.rect.height), 
                        border_radius=corner_radius)
        pygame.draw.rect(surface, border_color, 
                        (0, 0, self.rect.width, self.rect.height), 
                        width=border_width, border_radius=corner_radius)
        
        # Render text
        if self.current_message:
            font = self.get_font("text")
            padding = self.manager.scale_value(8)
            max_width = self.rect.width - (padding * 2)
            
            self.text_surfaces = self._render_wrapped_text(self.current_message, font, max_width)
            
            # Draw text lines
            text_x = padding
            text_y = padding
            line_height = font.get_height() + self.manager.scale_value(2)
            
            for line in self.text_surfaces:
                x_offset = 0
                for word, word_surface in line:
                    surface.blit(word_surface, (text_x + x_offset, text_y))
                    x_offset += word_surface.get_width() + font.size(' ')[0]
                text_y += line_height

        return surface
    
    def draw(self, surface, ui_local=False):
        """Draw the dialog box."""
        if self.state == self.STATE_HIDDEN:
            return
            
        # Always re-render for fade animation
        self.cached_surface = self.render()
        
        if self.cached_surface:
            # Calculate position based on rendering context and coordinate mode
            if self.use_screen_coordinates and self.manager:
                # Screen coordinates: position relative to screen edges, centered horizontally
                # This matches how TutorialFocus works: scale the coordinates and add UI offset for centering
                ui_scale = self.manager.ui_scale
                screen_width = self.manager.screen_size[0]
                screen_height = self.manager.screen_size[1]
                ui_size = 240 * ui_scale
                ui_offset_x = (screen_width - ui_size) // 2
                ui_offset_y = (screen_height - ui_size) // 2
                
                # Position: UI offset + scaled base coordinates
                pos = (ui_offset_x + int(self.base_rect.x * ui_scale), 
                       ui_offset_y + int(self.base_rect.y * ui_scale))
            elif ui_local and self.manager:
                # When drawing to master UI surface, use UI-relative position
                pos = (self.rect.x - self.manager.ui_offset_x, self.rect.y - self.manager.ui_offset_y)
            else:
                # Direct screen rendering with UI offset
                pos = (self.rect.x, self.rect.y)
            
            surface.blit(self.cached_surface, pos)
    
    def is_active(self) -> bool:
        """Check if dialog is currently showing."""
        return self.state != self.STATE_HIDDEN
    
    def is_waiting(self) -> bool:
        """Check if dialog is waiting for player input."""
        return self.state == self.STATE_WAITING
    
    def skip(self):
        """Skip current message immediately."""
        if self.state == self.STATE_WAITING:
            self.state = self.STATE_FADE_OUT
            self.fade_counter = 0
            self.needs_redraw = True
        elif self.state == self.STATE_FADE_IN:
            self.state = self.STATE_WAITING
            self.alpha = 255
            self.needs_redraw = True
