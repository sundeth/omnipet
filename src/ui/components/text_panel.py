"""
Text Panel Component - Displays text with cut corners and theme styling
"""
import pygame
from ui.components.component import UIComponent
from utils.pygame_utils import blit_with_cache


class TextPanel(UIComponent):
    def __init__(self, x, y, width, height, text=""):
        super().__init__(x, y, width, height)
        
        # Text properties
        self.text = text
        self.line_spacing = 4  # Space between lines
        
        # Cut corner properties
        self.cut_size = 11  # Size of cut corners
        
        # Cache
        self.cached_surface = None
        self.last_text = ""

        # This component is not focusable
        self.focusable = False

        # Slow vertical auto-scroll for text taller than the panel: scroll
        # down, pause, scroll back up, pause, repeat.  Overflow amount is
        # computed during render; zero disables the animation.
        self.auto_scroll = True
        self._scroll_px = 0.0
        self._scroll_dir = 1
        self._scroll_pause = 60      # initial hold before the first scroll
        self._scroll_overflow = 0
        self._last_scroll_int = 0

    def set_text(self, text):
        """Set the text to display"""
        if text != self.text:
            self.text = text or ""
            self.needs_redraw = True
            self.cached_surface = None
            self._scroll_px = 0.0
            self._scroll_dir = 1
            self._scroll_pause = 60
            self._scroll_overflow = 0

    def update(self):
        super().update()
        if not self.visible or not self.auto_scroll or self._scroll_overflow <= 0:
            return
        if self._scroll_pause > 0:
            self._scroll_pause -= 1
            return
        # ~12 base px/second at 30 FPS, scaled with the UI.
        speed = 0.4 * (self.manager.ui_scale if self.manager else 1)
        self._scroll_px += speed * self._scroll_dir
        if self._scroll_px >= self._scroll_overflow:
            self._scroll_px = float(self._scroll_overflow)
            self._scroll_dir = -1
            self._scroll_pause = 45
        elif self._scroll_px <= 0:
            self._scroll_px = 0.0
            self._scroll_dir = 1
            self._scroll_pause = 45
        if int(self._scroll_px) != self._last_scroll_int:
            self._last_scroll_int = int(self._scroll_px)
            self.needs_redraw = True
        
    def _calculate_cut_rectangle_points(self):
        """Calculate points for rectangle with cut top-left and bottom-right corners"""
        cut = self.manager.scale_value(self.cut_size) if self.manager else self.cut_size
        border_size = self.manager.get_border_size() if self.manager else 2
        
        # Adjust for border to prevent clipping - inset by half the border width
        inset = border_size // 2
        max_x = self.rect.width - 1 - inset
        max_y = self.rect.height - 1 - inset
        min_x = inset
        min_y = inset
        
        # Adjust cut size to account for inset
        adjusted_cut = max(0, cut - inset)
        
        # Define the 6 points of the cut rectangle (clockwise from top-left)
        return [
            (min_x + adjusted_cut, min_y),           # Top edge start (after top-left cut)
            (max_x, min_y),                          # Top-right corner
            (max_x, max_y - adjusted_cut),           # Right edge (before bottom-right cut)
            (max_x - adjusted_cut, max_y),           # Bottom edge (after bottom-right cut)
            (min_x, max_y),                          # Bottom-left corner
            (min_x, min_y + adjusted_cut),           # Left edge (before top-left cut)
        ]
        
    def _wrap_text(self, text, font, max_width):
        """Wrap text to fit within the given width"""
        if not text or not font:
            return []
            
        words = text.split()
        lines = []
        current_line = ""
        
        for word in words:
            # Test if adding this word would exceed width
            test_line = current_line + (" " if current_line else "") + word
            test_surface = font.render(test_line, True, (255, 255, 255))  # Color doesn't matter for size calculation
            
            if test_surface.get_width() <= max_width:
                current_line = test_line
            else:
                # Start new line
                if current_line:
                    lines.append(current_line)
                current_line = word
                
        # Add the last line
        if current_line:
            lines.append(current_line)
            
        return lines
        
    def draw(self, surface, ui_local=False):
        """Draw the text panel component
        
        Args:
            surface: Target surface to draw on
            ui_local: If True, use UI-local coordinates (for master surface rendering)
                     If False, use screen coordinates (for direct screen rendering)
        """
        if self.needs_redraw or not self.cached_surface or self.text != self.last_text:
            self._render_to_cache()
            
        if self.cached_surface:
            # Calculate position based on rendering context
            if ui_local and self.manager:
                # When drawing to master UI surface, use UI-relative position (subtract offset)
                pos = (self.rect.x - self.manager.ui_offset_x, self.rect.y - self.manager.ui_offset_y)
            else:
                # When drawing directly to screen, use screen position
                pos = self.rect.topleft
            
            blit_with_cache(surface, self.cached_surface, pos)
            
    def _render_to_cache(self):
        """Render the component to cached surface"""
        # Allocate once and reuse; only recreate when size changes
        if not hasattr(self, 'cached_surface') or self.cached_surface is None or self.cached_surface.get_size() != (self.rect.width, self.rect.height):
            self.cached_surface = pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
        
        # Get colors using the centralized color system
        colors = self.get_colors()
        bg_color = colors["bg"]
        line_color = colors["line"]
        fg_color = colors["fg"]
        
        # Get border size from manager
        border_size = self.manager.get_border_size() if self.manager else 2
        
        # Calculate cut rectangle points
        points = self._calculate_cut_rectangle_points()
        
        # Draw background
        if len(points) >= 3:
            pygame.draw.polygon(self.cached_surface, bg_color, points)
            pygame.draw.polygon(self.cached_surface, line_color, points, border_size)
            
        # Draw text if available
        if self.text:
            # Get font from manager using proper method
            font = self.get_font("text")
            
            if font:
                # Text area: keep side margins at just a few pixels (the old
                # cut+padding inset wasted ~19px per side and cut text off).
                # The small vertical offset keeps the first line clear of the
                # top-left corner cut diagonal.
                margin_x = self.manager.scale_value(4) if self.manager else 4
                margin_y = self.manager.scale_value(8) if self.manager else 8

                text_x = margin_x
                text_y = margin_y
                text_width = self.rect.width - (margin_x * 2)
                text_height = self.rect.height - (margin_y * 2)
                
                # Wrap text to fit
                lines = self._wrap_text(self.text, font, text_width)
                
                if lines:
                    line_height = font.get_height()
                    total_text_height = len(lines) * line_height + (len(lines) - 1) * self.line_spacing

                    # Center text vertically when it fits; when it's taller
                    # than the panel, top-align and let update() slowly
                    # auto-scroll through the overflow.
                    self._scroll_overflow = max(0, total_text_height - text_height)
                    start_y = text_y + max(0, (text_height - total_text_height) // 2)
                    if self._scroll_overflow > 0:
                        start_y -= int(self._scroll_px)

                    # Clip to the text area so partially-visible lines crop
                    # cleanly while scrolling.
                    prev_clip = self.cached_surface.get_clip()
                    self.cached_surface.set_clip(
                        pygame.Rect(text_x, text_y, text_width, text_height))

                    # Draw each line centered horizontally
                    for i, line in enumerate(lines):
                        line_rect_y = start_y + i * (line_height + self.line_spacing)
                        if line_rect_y + line_height < text_y or line_rect_y > text_y + text_height:
                            continue  # fully outside the visible area
                        line_surface = font.render(line, True, fg_color)
                        line_rect = line_surface.get_rect()
                        line_rect.centerx = text_x + text_width // 2
                        line_rect.y = line_rect_y
                        self.cached_surface.blit(line_surface, line_rect.topleft)

                    self.cached_surface.set_clip(prev_clip)
                        
        self.needs_redraw = False
        self.last_text = self.text