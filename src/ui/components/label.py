"""
Label Component - Text display with optional color override
"""
import pygame
from ui.components.component import UIComponent
from core import runtime_globals
from utils.pygame_utils import blit_with_cache, blit_with_shadow

class Label(UIComponent):
    def __init__(self, x, y, text, is_title=False, color_override=None, align_right=False, fixed_width=None, tooltip_text=None, scroll_text=False, shadow_mode="disabled", custom_size=None, word_wrap=False, max_width=None, center=False, center_lines=False):
        super().__init__(x, y, 1, 1)  # Width/height will be set after rendering
        self.text = text
        self.is_title = is_title
        self.color_override = color_override
        self.align_right = align_right
        self.fixed_width = fixed_width
        self.tooltip_text = tooltip_text
        self.scroll_text = scroll_text
        self.shadow_mode = shadow_mode  # Use consistent shadow system
        self.focusable = bool(tooltip_text)  # Only focusable if it has a tooltip
        self.needs_redraw = True
        self.custom_size = custom_size
        self.word_wrap = word_wrap
        self.max_width = max_width
        self.center = center  # If True, x position will be treated as center point
        # Centre each wrapped line inside the wrap width.  Opt-in and off by
        # default: `center` on its own centres the wrapped BLOCK, whose width
        # is always max_width, and existing callers are laid out around that.
        self.center_lines = center_lines
        self._center_adjusted = False  # Track if center adjustment has been applied
        self._center_origin = None  # Remembered centre point (base x) for re-centering
        
        # Scrolling animation variables
        self.scroll_offset = 0
        self.scroll_direction = 1  # 1 for right, -1 for left
        self.scroll_speed = 1  # pixels per frame
        self.scroll_pause_timer = 0
        self.scroll_pause_duration = 60  # frames to pause at each end
        self.last_update_time = 0
        
    def on_manager_set(self):
        """Called when component is added to a UIManager"""
        if self.center and self.base_rect is not None:
            # Remember the centre point (the original base x) so the label can
            # be re-centred whenever its text changes.
            if self._center_origin is None:
                self._center_origin = self.base_rect.x
            self._apply_center()

    def _apply_center(self):
        """Re-position base_rect.x so the rendered text is centred on the
        remembered centre point.  Safe to call repeatedly (e.g. after
        set_text changes the text width)."""
        if not (self.center and self.manager and self.base_rect is not None):
            return
        temp_surface = self.render()
        if not temp_surface:
            return
        base_text_width = temp_surface.get_width() // self.manager.ui_scale
        origin = self._center_origin if self._center_origin is not None else self.base_rect.x
        self.base_rect.x = origin - base_text_width // 2
        self.rect = self.manager.scale_rect(self.base_rect)
        self._center_adjusted = True
        self.needs_redraw = True

    def set_text(self, text):
        """Update the label text"""
        if self.text != text:
            self.text = text
            self.needs_redraw = True
            # Reset scrolling when text changes
            self.scroll_offset = 0
            self.scroll_direction = 1
            self.scroll_pause_timer = 0
            # Keep centred labels centred when the text width changes.
            if self.center and self.manager:
                self._apply_center()
    
    def set_tooltip(self, tooltip_text):
        """Set or update the tooltip text"""
        self.tooltip_text = tooltip_text
        self.focusable = bool(tooltip_text)
    
    def on_click(self):
        """Handle click events"""
        if self.tooltip_text and self.manager:
            self.manager.show_tooltip(self.tooltip_text)
            
    def on_activate(self):
        """Handle activation (A key or click)"""
        if self.tooltip_text and self.manager:
            self.manager.show_tooltip(self.tooltip_text)
            return True
        return False
    
    def update(self):
        """Update scrolling animation if enabled"""
        super().update()
        
        if self.scroll_text and self.fixed_width:
            current_time = pygame.time.get_ticks()
            
            # Only update scrolling if enough time has passed (smoother animation)
            if current_time - self.last_update_time >= 16:  # ~60 FPS
                self.last_update_time = current_time
                
                # Get text width to determine if scrolling is needed
                if self.custom_size:
                    if self.is_title:
                        font = self.get_font("title", custom_size=self.custom_size)
                    else:
                        font = self.get_font("text", custom_size=self.custom_size)
                else:
                    if self.is_title:
                        font = self.get_font("title")
                    else:
                        font = self.get_font("text")
                
                text_surface = font.render(self.text, True, (255, 255, 255))  # Color doesn't matter for width
                text_width = text_surface.get_width()
                display_width = self.manager.scale_value(self.fixed_width)
                
                # Only scroll if text is wider than display area
                if text_width > display_width:
                    if self.scroll_pause_timer > 0:
                        # Pausing at one end
                        self.scroll_pause_timer -= 1
                    else:
                        # Update scroll position
                        old_offset = self.scroll_offset
                        self.scroll_offset += self.scroll_direction * self.scroll_speed
                        
                        # Check boundaries and reverse direction
                        max_offset = text_width - display_width
                        if self.scroll_offset >= max_offset:
                            self.scroll_offset = max_offset
                            self.scroll_direction = -1
                            self.scroll_pause_timer = self.scroll_pause_duration
                        elif self.scroll_offset <= 0:
                            self.scroll_offset = 0
                            self.scroll_direction = 1
                            self.scroll_pause_timer = self.scroll_pause_duration
                        
                        # Only mark for redraw if scroll position actually changed
                        if old_offset != self.scroll_offset:
                            self.needs_redraw = True
                else:
                    # Reset scrolling if text fits
                    if self.scroll_offset != 0:
                        self.scroll_offset = 0
                        self.needs_redraw = True
        
    def render(self):
        # Choose font based on type using centralized font method
        if self.custom_size:
            if self.is_title:
                font = self.get_font("title", custom_size=self.custom_size)
            else:
                font = self.get_font("text", custom_size=self.custom_size)
        else:
            if self.is_title:
                font = self.get_font("title")
            else:
                font = self.get_font("text")
        
        # Get color
        if self.color_override:
            color = self.color_override
        else:
            colors = self.get_colors()
            color = colors["fg"]

        # Handle word wrapping
        if self.word_wrap and (self.max_width or self.fixed_width):
            wrap_width = self.max_width or self.fixed_width
            scaled_width = self.manager.scale_value(wrap_width) if self.manager else wrap_width
            
            # Split text into lines that fit within max_width
            words = self.text.split(' ')
            lines = []
            current_line = ""
            
            for word in words:
                # Add space before word if current_line is not empty
                test_line = (current_line + " " + word) if current_line else word
                test_surface = font.render(test_line, True, color)
                
                if test_surface.get_width() <= scaled_width:
                    current_line = test_line
                else:
                    if current_line:
                        lines.append(current_line)
                        current_line = word
                    else:
                        # Single word is too long, add it anyway
                        lines.append(word)
                        current_line = ""
            
            if current_line:
                lines.append(current_line)
            
            # Render each line
            line_height = font.get_height()
            total_height = line_height * len(lines)
            wrapped_surface = pygame.Surface((scaled_width, total_height), pygame.SRCALPHA)
            
            for i, line in enumerate(lines):
                line_surface = font.render(line, True, color)
                y_pos = i * line_height
                x_pos = 0
                if self.center_lines:
                    x_pos = (scaled_width - line_surface.get_width()) // 2
                
                if self.manager and self.manager.should_render_shadow(self, "text"):
                    blit_with_shadow(wrapped_surface, line_surface, (x_pos, y_pos))
                else:
                    blit_with_cache(wrapped_surface, line_surface, (x_pos, y_pos))
            
            # Update component screen size
            self.rect.width = scaled_width
            self.rect.height = total_height
            return wrapped_surface
            
        # Render text at proper scale
        text_surface = font.render(self.text, True, color)

        # Auto-shrink: if max_width is set and text overflows (no word_wrap, no scroll),
        # reduce font size until the text fits.
        if self.max_width and not self.word_wrap and not self.scroll_text:
            scaled_max = self.manager.scale_value(self.max_width) if self.manager else self.max_width
            if text_surface.get_width() > scaled_max:
                # Use font height as a proxy for the current point size
                current_size = font.get_height()
                min_size = max(6, current_size - 20)
                shrunk_surface = text_surface
                for shrunk_size in range(current_size - 1, min_size - 1, -1):
                    if self.is_title:
                        shrunk_font = self.get_font("title", custom_size=shrunk_size)
                    else:
                        shrunk_font = self.get_font("text", custom_size=shrunk_size)
                    shrunk_surface = shrunk_font.render(self.text, True, color)
                    if shrunk_surface.get_width() <= scaled_max:
                        break
                text_surface = shrunk_surface
        
        # Handle scrolling text
        if self.scroll_text and self.fixed_width:
            scaled_width = self.manager.scale_value(self.fixed_width)
            
            # Create a surface with fixed width for scrolling
            scroll_surface = pygame.Surface((scaled_width, text_surface.get_height()), pygame.SRCALPHA)
            
            # If text is wider than display area, apply scrolling offset
            if text_surface.get_width() > scaled_width:
                # Create a subsurface or blit with offset
                text_rect = pygame.Rect(-self.scroll_offset, 0, text_surface.get_width(), text_surface.get_height())
                # Use shadow-aware blitting
                if self.manager and self.manager.should_render_shadow(self, "text"):
                    blit_with_shadow(scroll_surface, text_surface, text_rect)
                else:
                    blit_with_cache(scroll_surface, text_surface, text_rect)
            else:
                # Text fits, center it or align as normal
                if self.align_right:
                    text_rect = text_surface.get_rect()
                    text_rect.right = scaled_width
                    if self.manager and self.manager.should_render_shadow(self, "text"):
                        blit_with_shadow(scroll_surface, text_surface, text_rect)
                    else:
                        blit_with_cache(scroll_surface, text_surface, text_rect)
                else:
                    if self.manager and self.manager.should_render_shadow(self, "text"):
                        blit_with_shadow(scroll_surface, text_surface, (0, 0))
                    else:
                        blit_with_cache(scroll_surface, text_surface, (0, 0))
            
            # Draw highlight if focused and has tooltip
            # Skip in touch mode - focus highlights are for keyboard/mouse navigation only
            if self.focused and self.tooltip_text and runtime_globals.INPUT_MODE != runtime_globals.TOUCH_MODE:
                colors = self.get_colors()
                highlight_color = colors.get("highlight", colors["fg"])  # Safe fallback
                pygame.draw.rect(scroll_surface, highlight_color, scroll_surface.get_rect(), 2)
            
            # Update component screen size
            self.rect.width = scaled_width
            self.rect.height = text_surface.get_height()
            return scroll_surface
            
        # Handle right alignment (non-scrolling)
        elif self.align_right and self.fixed_width:
            # Create a surface with fixed width for right alignment (scaled)
            scaled_width = self.manager.scale_value(self.fixed_width)
            aligned_surface = pygame.Surface((scaled_width, text_surface.get_height()), pygame.SRCALPHA)
            
            # Truncate text if it's too wide and not scrolling
            if text_surface.get_width() > scaled_width:
                # Create truncated version
                truncated_surface = pygame.Surface((scaled_width, text_surface.get_height()), pygame.SRCALPHA)
                if self.manager and self.manager.should_render_shadow(self, "text"):
                    blit_with_shadow(truncated_surface, text_surface, (0, 0))
                else:
                    blit_with_cache(truncated_surface, text_surface, (0, 0))
                text_surface = truncated_surface
            
            # Blit text surface to the right side
            text_rect = text_surface.get_rect()
            text_rect.right = scaled_width
            if self.manager and self.manager.should_render_shadow(self, "text"):
                blit_with_shadow(aligned_surface, text_surface, text_rect)
            else:
                blit_with_cache(aligned_surface, text_surface, text_rect)
            
            # Draw highlight if focused and has tooltip
            # Skip in touch mode - focus highlights are for keyboard/mouse navigation only
            if self.focused and self.tooltip_text and runtime_globals.INPUT_MODE != runtime_globals.TOUCH_MODE:
                colors = self.get_colors()
                highlight_color = colors.get("highlight", colors["fg"])  # Safe fallback
                pygame.draw.rect(aligned_surface, highlight_color, aligned_surface.get_rect(), 2)
            
            # Update component screen size (don't modify base_rect)
            self.rect.width = scaled_width
            self.rect.height = text_surface.get_height()
            return aligned_surface
        else:
            # Handle truncation for fixed width without scrolling
            if self.fixed_width and not self.scroll_text:
                scaled_width = self.manager.scale_value(self.fixed_width) if self.manager else self.fixed_width
                if text_surface.get_width() > scaled_width:
                    # Truncate the text
                    truncated_surface = pygame.Surface((scaled_width, text_surface.get_height()), pygame.SRCALPHA)
                    if self.manager and self.manager.should_render_shadow(self, "text"):
                        blit_with_shadow(truncated_surface, text_surface, (0, 0))
                    else:
                        blit_with_cache(truncated_surface, text_surface, (0, 0))
                    text_surface = truncated_surface
                
                # Update component screen size
                self.rect.width = scaled_width
                self.rect.height = text_surface.get_height()
            else:
                # Check if we should render with shadow
                if self.manager and self.manager.should_render_shadow(self, "text"):
                    # Create a surface with extra space for shadow
                    shadow_offset = (2, 2)
                    shadow_surface = pygame.Surface(
                        (text_surface.get_width() + shadow_offset[0], 
                         text_surface.get_height() + shadow_offset[1]), 
                        pygame.SRCALPHA
                    )
                    blit_with_shadow(shadow_surface, text_surface, (0, 0), offset=shadow_offset)
                    text_surface = shadow_surface
                
                # Update component screen size (don't modify base_rect)
                self.rect.width = text_surface.get_width()
                self.rect.height = text_surface.get_height()
            
            # Draw highlight if focused and has tooltip
            # Skip in touch mode - focus highlights are for keyboard/mouse navigation only
            if self.focused and self.tooltip_text and runtime_globals.INPUT_MODE != runtime_globals.TOUCH_MODE:
                # Draw the border on a same-size surface (like the scroll and
                # align branches do): enlarging the surface and blitting the
                # text at (2, 2) visibly nudged the label whenever hovered.
                highlight_surface = text_surface.copy()
                colors = self.get_colors()
                highlight_color = colors.get("highlight", colors["fg"])  # Safe fallback
                pygame.draw.rect(highlight_surface, highlight_color, highlight_surface.get_rect(), 2)
                return highlight_surface
            
            return text_surface
