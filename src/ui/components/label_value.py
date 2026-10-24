"""
Label Value Component - A combined component that shows a label and value together
"""
import pygame
from ui.components.component import UIComponent
from ui.ui_constants import PURPLE, BLACK, GREY, YELLOW
from core import runtime_globals
from utils.pygame_utils import blit_with_cache, blit_with_shadow


class LabelValue(UIComponent):
    def __init__(self, x, y, width, height, label_text, value_text="", 
                 color_override=None, value_color=YELLOW, tooltip_text=None):
        super().__init__(x, y, width, height)
        self.label_text = label_text
        self.value_text = value_text
        self.color_override = color_override
        self.value_color = value_color
        self.tooltip_text = tooltip_text
        self.focusable = tooltip_text is not None  # Only focusable if has tooltip
        self.visible = True
        
        # Visual state
        self.hover_effect = False
        
    def set_label(self, text):
        """Update the label text"""
        if self.label_text != text:
            self.label_text = text
            self.needs_redraw = True
        
    def set_value(self, text):
        """Update the value text"""
        if self.value_text != text:
            self.value_text = text
            self.needs_redraw = True
        
    def set_value_color(self, color):
        """Update the value's colour"""
        if self.value_color != color:
            self.value_color = color
            self.needs_redraw = True

    def set_tooltip(self, text):
        """Set tooltip text and make component focusable"""
        self.tooltip_text = text
        self.focusable = text is not None
        
    def on_click(self):
        """Handle click events"""
        if self.tooltip_text and self.manager:
            self.manager.show_tooltip(self.tooltip_text)
            
    def on_activate(self):
        """Handle activation (A key or click)"""
        if self.tooltip_text and self.manager:
            self.manager.show_tooltip(self.tooltip_text)
        
    def render(self):
        surface = pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
        
        # Get font using centralized method
        font = self.get_font("text")
        
        # Calculate text positions
        label_surface = font.render(self.label_text, True, self.color_override or PURPLE)
        value_surface = font.render(self.value_text, True, self.value_color)
        
        # Position label on the left
        label_x = 0
        label_y = (self.rect.height - label_surface.get_height()) // 2
        
        # Position value on the right
        value_x = self.rect.width - value_surface.get_width()
        value_y = (self.rect.height - value_surface.get_height()) // 2
        
        # Draw texts with shadow support
        use_shadow = self.manager and self.manager.should_render_shadow(self, "text")
        if use_shadow:
            blit_with_shadow(surface, label_surface, (label_x, label_y))
            blit_with_shadow(surface, value_surface, (value_x, value_y))
        else:
            blit_with_cache(surface, label_surface, (label_x, label_y))
            blit_with_cache(surface, value_surface, (value_x, value_y))
        
        # Draw highlight if focused and has tooltip
        # Skip in touch mode - focus highlights are for keyboard/mouse navigation only
        if self.focused and self.tooltip_text and runtime_globals.INPUT_MODE != runtime_globals.TOUCH_MODE:
            colors = self.get_colors()
            highlight_color = colors.get("highlight", colors["fg"])  # Safe fallback
            pygame.draw.rect(surface, highlight_color, surface.get_rect(), 2)
        
        return surface
