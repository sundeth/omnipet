"""
Base UI Component - Foundation for all UI elements
"""
import pygame

from core import runtime_globals
from utils.pygame_utils import blit_with_shadow, blit_with_cache


class UIComponent:
    def __init__(self, x, y, width, height):
        # Store base coordinates (will be scaled by UIManager when added)
        self.rect = pygame.Rect(x, y, width, height)
        self.base_rect = None  # Will be set by UIManager
        self.focused = False
        self.clicked = False
        self.click_time = 0
        self.cached_surface = None
        self.needs_redraw = True
        self.manager = None
        self.focusable = False
        self.visible = True
        self.on_click_callback = None
        self.tooltip_text = None
        self.tooltip_active = False
        
        # Shadow configuration for this component
        # "disabled": No shadows
        # "component": Shadows on component background/border only
        # "full": Shadows on everything (text, decorators, etc.)
        self.shadow_mode = "disabled"  # Default: no shadows
        
        # Screen-wide positioning - when True, component bypasses UI area constraints
        # and can be positioned anywhere on the screen using screen coordinates
        self.use_screen_coordinates = False  # Default: use UI area coordinates
        
        # Dynamic components are not cached in master UI surface and render separately
        # Set to True for animated components like carousels, animated sprites, etc.
        self.is_dynamic = False
        
        runtime_globals.game_console.log(f"[{self.__class__.__name__}] Created with base rect: {self.rect}")
        
    def set_position(self, x, y):
        """Set position in base coordinates"""
        if self.base_rect:
            self.base_rect.x = x
            self.base_rect.y = y
            # Update screen coordinates if manager is available
            if self.manager:
                self.rect = self.manager.scale_rect(self.base_rect)
        else:
            self.rect.x = x
            self.rect.y = y
        self.needs_redraw = True
        
    def set_size(self, width, height):
        """Set size in base coordinates"""
        if self.base_rect:
            self.base_rect.width = width
            self.base_rect.height = height
            # Update screen coordinates if manager is available
            if self.manager:
                self.rect = self.manager.scale_rect(self.base_rect)
        else:
            self.rect.width = width
            self.rect.height = height
        self.needs_redraw = True
        
    def set_shadow_mode(self, mode):
        """Set shadow mode for this component
        
        Args:
            mode: "disabled", "component", or "full"
        """
        if mode in ["disabled", "component", "full"]:
            self.shadow_mode = mode
            self.needs_redraw = True
        else:
            runtime_globals.game_console.log(f"[{self.__class__.__name__}] Invalid shadow mode: {mode}")
    
    def set_screen_coordinates(self, use_screen_coords=True, screen_x=None, screen_y=None):
        """Enable screen-wide positioning for this component
        
        Args:
            use_screen_coords: True to use screen coordinates, False for UI area coordinates
            screen_x: Screen X position (if not provided, keeps current position)
            screen_y: Screen Y position (if not provided, keeps current position)
        """
        self.use_screen_coordinates = use_screen_coords
        
        if use_screen_coords and (screen_x is not None or screen_y is not None):
            # Set screen position directly
            if screen_x is not None:
                self.rect.x = screen_x
            if screen_y is not None:
                self.rect.y = screen_y
            # Clear base_rect when using screen coordinates
            self.base_rect = None
        
        self.needs_redraw = True
        
    def update(self):
        # Handle mouse hover detection only for focusable components
        if self.focusable:
            self.handle_mouse_hover()
        
        # Reset click state after a brief period
        if self.clicked and pygame.time.get_ticks() - self.click_time > 200:
            self.clicked = False
            self.needs_redraw = True
    
    def handle_mouse_hover(self):
        """Handle mouse hover detection using InputManager with screen coordinates"""
        if not runtime_globals or not hasattr(runtime_globals, 'game_input') or not runtime_globals.game_input:
            return
            
        if not (runtime_globals.INPUT_MODE in [runtime_globals.MOUSE_MODE, runtime_globals.TOUCH_MODE]):
            return
            
        # Don't override focus during keyboard navigation mode
        if self.manager and hasattr(self.manager, 'keyboard_navigation_mode') and self.manager.keyboard_navigation_mode:
            return
            
        mouse_pos = runtime_globals.game_input.get_mouse_position()
        was_focused = self.focused
        # Use screen coordinates for collision detection
        self.focused = self.rect.collidepoint(mouse_pos)
        if was_focused != self.focused:
            self.needs_redraw = True
            
    def draw(self, surface, ui_local=False):
        """Draw the component to the surface
        
        Args:
            surface: Target surface to draw on
            ui_local: If True, use UI-local coordinates (for master surface rendering)
                     If False, use screen coordinates (for direct screen rendering)
        """
        if not self.visible:
            return
            
        if self.needs_redraw or self.cached_surface is None:
            self.cached_surface = self.render()
            self.needs_redraw = False
        
        # Calculate position based on rendering context
        if ui_local and self.manager:
            # When drawing to master UI surface, use UI-relative position (subtract offset)
            pos = (self.rect.x - self.manager.ui_offset_x, self.rect.y - self.manager.ui_offset_y)
        else:
            # When drawing directly to screen, use screen position
            pos = self.rect.topleft
            
        # Check if component-level shadows should be applied
        should_shadow = self.manager and self.manager.should_render_shadow(self, "component")
        
        if should_shadow:
            # Blit the entire component surface with shadow
            blit_with_shadow(surface, self.cached_surface, pygame.Rect(pos[0], pos[1], self.rect.width, self.rect.height))
        else:
            # Blit normally without shadow
            blit_with_cache(surface, self.cached_surface, pos)

    def render(self):
        """Create and return the component surface at proper scale - to be implemented by subclasses"""
        # Use screen dimensions for surface creation
        return pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
        
    def handle_event(self, event):
        """Handle input events"""
        if not self.visible or not self.focusable:
            return False
            
        # Handle tuple-based events from the input manager
        event_type, event_data = event
        if event_type in ["A", "LCLICK"]:
            self.on_click()
            return True
                    
        return False
        
    def set_tooltip(self, text):
        """Set tooltip text for this component"""
        self.tooltip_text = text
        if text:
            self.focusable = True  # Make focusable if it has tooltip
        
    def show_tooltip(self):
        """Show tooltip if available"""
        if self.tooltip_text and self.manager:
            self.manager.show_tooltip(self.tooltip_text)
            self.tooltip_active = True
            
    def hide_tooltip(self):
        """Hide tooltip"""
        if self.tooltip_active and self.manager:
            self.manager.hide_tooltip()
            self.tooltip_active = False
        
    def on_focus_gained(self):
        """Called when component gains focus"""
        # Tooltips are now only shown on explicit activation (A key or click)
        pass
        
    def on_focus_lost(self):
        """Called when component loses focus"""
        pass #self.hide_tooltip()
        
    def activate(self):
        """Called when component is activated (A button or click)"""
        if self.tooltip_text:
            self.show_tooltip()
            return True
        return False
        
    def on_click(self):
        self.clicked = True
        self.click_time = pygame.time.get_ticks()
        self.needs_redraw = True
        
        # Show tooltip on click if available
        if self.tooltip_text:
            self.show_tooltip()
        
        if self.on_click_callback:
            self.on_click_callback()
    
    def focus_visible(self):
        """Whether this component draws its focus highlight.

        Touch mode has no cursor: focus there only routes a tap to its
        component, so nothing is drawn as focused (owner rule, 2026-10-13).
        A tap still flashes through ``clicked``.
        """
        return self.focused and runtime_globals.INPUT_MODE != runtime_globals.TOUCH_MODE

    def get_colors(self):
        """
        Get colors for component based on current state (clicked, focused, normal).
        Returns a dictionary with 'bg', 'fg', and 'line' color keys.
        Components can override this method for custom styling behavior.
        """
        if not self.manager:
            # Fallback colors if no manager is available
            return {"bg": (0, 0, 0), "fg": (255, 255, 255), "line": (255, 255, 255), "highlight": (255, 255, 255)}
        
        # Get base theme colors from manager
        theme_colors = self.manager.get_theme_colors()
        
        # Ensure all required color keys exist (fallback for missing keys during animation)
        if "highlight" not in theme_colors:
            theme_colors["highlight"] = theme_colors.get("fg", (255, 255, 255))
        
        # Default state: normal colors
        bg_color = theme_colors["bg"]
        fg_color = theme_colors["fg"]
        line_color = theme_colors["fg"]
        
        # Apply state-based modifications
        if self.clicked:
            # Clicked state: inverted colors for strong visual feedback
            bg_color = theme_colors["highlight"]
            fg_color = theme_colors["bg"]
            line_color = theme_colors["bg"]
        elif self.focus_visible():
            # Focused state: highlighted text/foreground while keeping background
            bg_color = theme_colors["bg"]
            fg_color = theme_colors["highlight"]
            line_color = theme_colors["highlight"]
        
        return {
            "bg": bg_color,
            "fg": fg_color,
            "line": line_color
        }
    
    def get_font(self, font_type="text", custom_size=None):
        """
        Get font for component with consistent handling across the UI system.
        
        Args:
            font_type (str): Type of font - "text", "title", or custom path
            custom_size (int): Optional custom font size, overrides theme sizing
            
        Returns:
            pygame.font.Font: Configured font object
        """
        import pygame
        from ui.ui_constants import TEXT_FONT, TITLE_FONT
        
        # Determine font path
        if font_type == "title":
            font_path = TITLE_FONT
            # Get size from manager or fallback
            if self.manager and custom_size is None:
                font_size = self.manager.get_title_font_size()
            else:
                font_size = custom_size or 24
        elif font_type == "text":
            font_path = TEXT_FONT  
            # Get size from manager or fallback
            if self.manager and custom_size is None:
                font_size = self.manager.get_text_font_size()
            else:
                font_size = custom_size or 16
        else:
            # Custom font path provided
            font_path = font_type
            font_size = custom_size or 16
        
        # Try to load the font with error handling
        from utils.asset_utils import font_load
        return font_load(font_path, font_size)
