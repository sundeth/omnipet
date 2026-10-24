"""
Numeric Meter Component - Shows icon and numeric value for stats like trophies, vital values
"""
import pygame
from ui.components.component import UIComponent
from utils.pygame_utils import blit_with_cache


class NumericMeter(UIComponent):
    def __init__(self, x, y, width, height, icon_name, value, max_digits=3):
        super().__init__(x, y, width, height)
        self.icon_name = icon_name  # e.g., "Trophies", "VitalValues"
        self.value = value
        self.max_digits = max_digits  # Maximum number of digits to display
        self.focusable = False
        self.icon = None
        self.font = None
        
    def load_images(self):
        """Load icon image based on UI scale with fallback and scaling"""
        if not self.manager:
            return
        self.icon = self.manager.load_sprite_integer_scaling("Status", self.icon_name, "")
        
    def set_value(self, value):
        """Update the meter value"""
        if self.value != value:
            self.value = value
            self.needs_redraw = True
        
    def display_text(self):
        """The number as drawn: a value with more digits than the meter
        holds shows its top value (999) instead of its first digits (1234
        read "123")."""
        value_str = str(self.value)
        if len(value_str) > self.max_digits:
            value_str = "9" * self.max_digits
        return value_str

    def render(self):
        # Use screen dimensions for surface
        surface = pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
        
        # Load images/fonts if not already loaded
        if self.icon is None:
            self.load_images()
        if self.font is None:
            self.font = self.get_font()
        
        # Get colors
        colors = self.manager.get_theme_colors()
        bg_color = colors["black"]
        fg_color = colors["bg"]
        text_color = colors["fg"]  # Use foreground color for text
        
        # Draw icon
        icon_width = self.icon.get_width()
        icon_rect = self.icon.get_rect(centery=self.rect.height//2)
        
        # Calculate background rectangle dimensions (using scaled values)
        rect_start_x = icon_width // 2  # Start from middle of icon
        rect_width = self.rect.width - rect_start_x
        rect_padding = self.manager.scale_value(2)  # Scale base padding
        
        # Draw background rounded rectangle behind text
        border_radius = self.manager.get_border_size()
        pygame.draw.rect(
            surface,
            bg_color,
            (rect_start_x, rect_padding, rect_width, self.rect.height - 2 * rect_padding),
            border_radius=border_radius
        )

        # Draw border with same rounded corners
        pygame.draw.rect(
            surface,
            fg_color,
            (rect_start_x, rect_padding, rect_width, self.rect.height - 2 * rect_padding),
            width=self.manager.get_border_size(),
            border_radius=border_radius
        )

        blit_with_cache(surface, self.icon, icon_rect)
        
        # Format and render numeric value
        value_str = self.display_text()
        
        # Render text
        text_surface = self.font.render(value_str, True, text_color)
        
        # Calculate text position - center it in the available space
        text_padding = self.manager.scale_value(6)  # Scale base padding
        available_width = rect_width - 2 * text_padding
        text_x = rect_start_x + text_padding + (available_width - text_surface.get_width()) // 2
        text_y = (self.rect.height - text_surface.get_height()) // 2
        
        blit_with_cache(surface, text_surface, (text_x, text_y))
            
        return surface