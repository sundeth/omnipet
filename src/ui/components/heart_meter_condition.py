"""
Heart Meter Condition Component - Shows condition hearts without icon, spread across full width
"""

import pygame
from ui.components.component import UIComponent
from utils.pygame_utils import blit_with_cache


class HeartMeterCondition(UIComponent):
    def __init__(self, x, y, width, height, value, max_value):
        super().__init__(x, y, width, height)
        self.value = value
        self.max_value = min(max(max_value, 1), 4)  # Clamp between 1 and 4
        self.focusable = False
        self.heart_images = {}

    def load_images(self):
        """Load heart images using unified sprite loading methods"""
        if not self.manager:
            return
        
        # Load heart images using integer scaling method
        self.heart_images = {
            "empty": self.manager.load_sprite_integer_scaling("Status", "Heart", "Empty"),
            "half": self.manager.load_sprite_integer_scaling("Status", "Heart", "Half"), 
            "full": self.manager.load_sprite_integer_scaling("Status", "Heart", "Full")
        }

        
    def set_value(self, value, max_value=None):
        """Update the meter value and optionally max_value"""
        value_changed = self.value != value
        if max_value is not None:
            max_value = min(max(max_value, 1), 4)  # Clamp between 1 and 4
            max_changed = self.max_value != max_value
            self.max_value = max_value
        else:
            max_changed = False
            
        if value_changed or max_changed:
            self.value = value
            self.needs_redraw = True
        
    def render(self):
        # Use screen dimensions for surface
        surface = pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
        
        # Load images if not already loaded
        if not self.heart_images:
            self.load_images()
        
        # Get colors
        colors = self.manager.get_theme_colors()
        bg_color = colors["black"]
        fg_color = colors["bg"]
        
        # Calculate background rectangle dimensions (full width since no icon)
        rect_padding = self.manager.scale_value(2)  # Scale base padding
        
        # Draw background rounded rectangle behind hearts
        border_radius = self.manager.get_border_size()
        pygame.draw.rect(
            surface,
            bg_color,
            (0, rect_padding, self.rect.width, self.rect.height - 2 * rect_padding),
            border_radius=border_radius
        )

        # Draw border with same rounded corners
        pygame.draw.rect(
            surface,
            fg_color,
            (0, rect_padding, self.rect.width, self.rect.height - 2 * rect_padding),
            width=self.manager.get_border_size(),
            border_radius=border_radius
        )

        # Calculate heart positions - spread across full width
        heart_width = self.heart_images["empty"].get_width()
        available_width = self.rect.width - 2 * self.manager.scale_value(7)  # Scale base padding on both sides
        
        # Calculate spacing to distribute hearts evenly
        if self.max_value > 1:
            heart_spacing = (available_width - self.max_value * heart_width) // (self.max_value - 1)
            heart_spacing = max(1, heart_spacing)  # Minimum 1 pixel spacing
        else:
            heart_spacing = 0
        
        # Center the hearts if there's extra space
        total_hearts_width = self.max_value * heart_width + (self.max_value - 1) * heart_spacing
        heart_start_x = (self.rect.width - total_hearts_width) // 2
        
        # Draw hearts
        for i in range(self.max_value):
            heart_x = heart_start_x + i * (heart_width + heart_spacing)
            heart_y = (self.rect.height - self.heart_images["empty"].get_height()) // 2
            
            # Determine heart type based on value (1 point = 1 full heart, no half hearts for condition)
            if self.value >= i + 1:
                heart = self.heart_images["full"]
            else:
                heart = self.heart_images["empty"]
                
            blit_with_cache(surface, heart, (heart_x, heart_y))

        if self.focus_visible():
            colors = self.manager.get_theme_colors()
            highlight_color = colors.get("highlight", colors["fg"])  # Safe fallback
            pygame.draw.rect(surface, highlight_color, surface.get_rect(), 2)
            
            
        return surface