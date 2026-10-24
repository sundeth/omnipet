"""
Simple Tooltip Component - Displays tooltip text without inheritance issues
"""
import pygame
from ui.ui_constants import PURPLE, TEXT_FONT, BLACK, PURPLE_LIGHT, PURPLE_DARK
from utils.pygame_utils import blit_with_cache


class Tooltip:
    def __init__(self, text, screen_width, screen_height):
        # Base values - these will be scaled
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.text = text
        # Matches the ordinary text size (ui_constants.TEXT_FONT_SIZES); a
        # tooltip exists to be read, so it never goes below it.
        self.base_font_size = 16  # Base font size that will be scaled
        self.base_padding = 10    # Base padding that will be scaled
        self.base_line_spacing = 2  # Base line spacing that will be scaled
        self.base_max_width = 200   # Base max width that will be scaled
        self.manager = None
        
        # Scaled values (will be updated when manager is set)
        self.font_size = self.base_font_size
        self.padding = self.base_padding
        self.line_spacing = self.base_line_spacing
        self.max_width = min(screen_width - 40, self.base_max_width)
        
        # Will be calculated after scaling is set up
        self.text_lines = []
        self.rect = pygame.Rect(0, 0, 0, 0)
        self.visible = True
        
        # Animation properties
        self.alpha = 0
        self.fade_start_time = pygame.time.get_ticks()
        self.fade_duration = 150  # ms
        
        # Setup initial layout (will be updated when manager is available)
        self.setup_layout()
        
    def set_manager(self, manager):
        """Set the UI manager and update scaling"""
        self.manager = manager
        self.update_scaling()
        self.setup_layout()
        
    def update_scaling(self):
        """Update scaled values based on UI manager scale"""
        if self.manager:
            scale = self.manager.ui_scale
        else:
            scale = 1.0
            
        # Scale all dimensions
        self.font_size = max(8, int(self.base_font_size * scale))
        self.padding = int(self.base_padding * scale)
        self.line_spacing = int(self.base_line_spacing * scale)
        self.max_width = min(self.screen_width - int(40 * scale), int(self.base_max_width * scale))
        
    def setup_layout(self):
        """Calculate tooltip size and position based on current scaling"""
        # Calculate tooltip size based on wrapped text
        self.text_lines = self.wrap_text(self.text, self.max_width - self.padding * 2)
        
        # Calculate dimensions
        from utils.asset_utils import font_load
        font = font_load(TEXT_FONT, self.font_size)
        line_height = font.get_height()
        
        if self.text_lines:
            max_line_width = max(font.render(line, True, PURPLE).get_width() for line in self.text_lines)
            width = min(self.max_width, max_line_width + self.padding * 2)
            height = len(self.text_lines) * line_height + (len(self.text_lines) - 1) * self.line_spacing + self.padding * 2
        else:
            width = self.padding * 2
            height = self.padding * 2
        
        # Center on screen
        x = (self.screen_width - width) // 2
        y = (self.screen_height - height) // 2
        
        self.rect = pygame.Rect(x, y, width, height)
        
    def wrap_text(self, text, max_width):
        """Wrap text to fit within the given width"""
        if not text:
            return []
        
        from utils.asset_utils import font_load
        font = font_load(TEXT_FONT, self.font_size)
        words = text.split(' ')
        lines = []
        current_line = []
        
        for word in words:
            # Test if adding this word would exceed the width
            test_line = ' '.join(current_line + [word])
            test_surface = font.render(test_line, True, BLACK)
            
            if test_surface.get_width() <= max_width:
                current_line.append(word)
            else:
                # If current line is not empty, finish it and start a new one
                if current_line:
                    lines.append(' '.join(current_line))
                    current_line = [word]
                else:
                    # Single word is too long, force it on its own line
                    lines.append(word)
        
        # Add the last line if it has content
        if current_line:
            lines.append(' '.join(current_line))
        
        return lines
        
    def update(self):
        """Update tooltip animation"""
        current_time = pygame.time.get_ticks()
        
        # Handle fade in animation
        if self.fade_start_time > 0:
            elapsed = current_time - self.fade_start_time
            if elapsed < self.fade_duration:
                # Fade in
                self.alpha = int((elapsed / self.fade_duration) * 255)
            else:
                # Fade complete
                self.alpha = 255
                self.fade_start_time = 0
        
    def render(self):
        # Reuse a cached render surface to avoid per-frame allocations
        target_size = (self.rect.width, self.rect.height)
        if not hasattr(self, "_render_surface") or self._render_surface is None or self._render_surface.get_size() != target_size:
            self._render_surface = pygame.Surface(target_size, pygame.SRCALPHA)
        surface = self._render_surface
        surface.fill((0, 0, 0, 0))
        
        # Use the scaled font size and border size
        from utils.asset_utils import font_load
        font = font_load(TEXT_FONT, self.font_size)
        line_height = font.get_height()
        
        # Get border size from manager or use scaled default
        if self.manager:
            border_size = self.manager.get_border_size()
        else:
            border_size = max(1, int(2 * (self.font_size / self.base_font_size)))
        
        # Draw background with alpha
        bg_surface = pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
        bg_color = (*PURPLE_LIGHT, self.alpha)
        border_radius = max(2, border_size * 2)
        pygame.draw.rect(bg_surface, bg_color, (0, 0, self.rect.width, self.rect.height), 
                border_radius=border_radius)
        blit_with_cache(surface, bg_surface, (0, 0))
        
        # Draw border with alpha
        border_surface = pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
        border_color = (*PURPLE_DARK, self.alpha)
        pygame.draw.rect(border_surface, border_color, (0, 0, self.rect.width, self.rect.height), 
                width=border_size, border_radius=border_radius)
        blit_with_cache(surface, border_surface, (0, 0))
        
        # Draw text lines with alpha
        text_y = self.padding
        for line in self.text_lines:
            text_surface = font.render(line, True, BLACK)
            text_surface.set_alpha(self.alpha)
            text_x = (self.rect.width - text_surface.get_width()) // 2
            blit_with_cache(surface, text_surface, (text_x, text_y))
            text_y += line_height + self.line_spacing
        
        return surface
        
    def draw(self, surface, ui_local=False):
        """Draw the tooltip
        
        Args:
            surface: Target surface to draw on
            ui_local: If True, use UI-local coordinates (ignored for modal tooltip)
        """
        if self.visible:
            rendered = self.render()
            blit_with_cache(surface, rendered, self.rect.topleft)
