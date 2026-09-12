"""
UI Manager - Core component for handling UI scaling, themes, focus, and event management
"""
import math
import time
import pygame
from ui.ui_constants import *
from core import runtime_globals
import core.constants as constants
from ui.components.background import Background
from utils.asset_utils import image_load
from utils.pygame_utils import blit_with_cache

# UI sprites loaded via load_sprite_integer_scaling, shared across UIManager
# instances and keyed by (filepath, ui_scale) — without this every call hit
# the disk, and some draw paths request sprites per frame.
_integer_sprite_cache = {}

DEBUG_SCALE = False  # Set to True to enable detailed scaling debug logs

class UIManager:
    def __init__(self, theme="PURPLE"):
        # Use runtime globals for screen size so UI manager honors
        # the configured/internal resolution (especially on Android)
        self.screen_size = (runtime_globals.SCREEN_WIDTH, runtime_globals.SCREEN_HEIGHT)
        self.ui_scale = self.determine_scale()
        self.components = []
        self.focusable_components = []
        self.focused_index = -1
        self.theme = theme
        self.animation_components = []
        self.cached_background = None
        
        # Master UI cache - single surface for entire UI to reduce blits
        self.master_ui_surface = None
        self.master_ui_dirty = True  # Track if master surface needs rebuild
        
        # Shadow system configuration
        # Global shadow mode: None (disabled), "component", "background", "full"
        # None: Use component-specific shadow settings
        # "component": Force shadows only on component backgrounds/borders
        # "background": Force shadows only on component backgrounds/borders
        # "full": Force shadows everywhere including text and decorators
        self.global_shadow_mode = None  # Default: disabled, use component settings
        
        # Calculate actual UI dimensions and offset
        self.ui_width, self.ui_height = self.get_scaled_resolution()
        self.ui_offset_x, self.ui_offset_y = self.get_ui_offset()
        
        # Global highlight system removed - components handle their own highlighting
        
        # Mouse tracking
        self.last_mouse_pos = (0, 0)
        self.mouse_over_component = None
        self.mouse_over_sub_rect = None
        
        # Tooltip system
        self.active_tooltip = None
        self.menu_blockers_input = False
        
        # Modal component system (menu, stats panel, etc.)
        self.active_menu = None
        self.active_stats_panel = None
        
        # External border visibility (can be disabled for scenes like tutorial)
        self.show_external_border = True
        
        # Color animation system - smooth interpolation
        self.is_animating_colors = False
        self.color_animation_frame_counter = 0
        self.color_animation_total_frames = constants.FRAME_RATE  # Exactly 1 second worth of frames
        self.color_animation_redraw_interval = max(1, constants.FRAME_RATE // 20)  # Redraw every ~20th of a second for smoothness, considering frame rate
        self.color_animation_source_theme = None
        self.color_animation_target_theme = None
        self.color_animation_callback = None
        self.current_animated_colors = None
        
        if DEBUG_SCALE:
            runtime_globals.game_console.log(f"[UIManager] Initialized with {self.ui_scale}x scale, theme {theme}")
            runtime_globals.game_console.log(f"[UIManager] UI Resolution: {self.get_scaled_resolution()}, Screen: {self.screen_size}")
            runtime_globals.game_console.log(f"[UIManager] UI Offset: {self.get_ui_offset()}")
        
    def determine_scale(self):
        """Determine integer UI scale based on screen resolution"""
        width, height = self.screen_size
        min_dimension = min(width, height)
        
        # Integer scaling: 1x=240, 2x=480, 3x=720, 4x=960, etc.
        ui_scale = max(1, min_dimension // BASE_RESOLUTION)
        
        return ui_scale
    
    def get_scaled_resolution(self):
        """Get the UI resolution (always 240x240 * scale)"""
        scaled_size = BASE_RESOLUTION * self.ui_scale
        return (scaled_size, scaled_size)
    
    def get_ui_offset(self):
        """Get the offset to center the UI on screen"""
        scaled_width, scaled_height = self.get_scaled_resolution()
        offset_x = (self.screen_size[0] - scaled_width) // 2
        offset_y = (self.screen_size[1] - scaled_height) // 2
        return (offset_x, offset_y)
    
    def scale_value(self, base_value):
        """Scale a base value according to current UI scale"""
        scaled_value = base_value * self.ui_scale
        if DEBUG_SCALE:
            runtime_globals.game_console.log(f"[UIManager] scale_value: {base_value} -> {scaled_value} (scale: {self.ui_scale})")
        return scaled_value
        
    def scale_position(self, base_x, base_y):
        """Scale base position coordinates to actual screen positions"""
        scaled_pos = (
            self.ui_offset_x + (base_x * self.ui_scale),
            self.ui_offset_y + (base_y * self.ui_scale)
        )
        if DEBUG_SCALE:
            runtime_globals.game_console.log(f"[UIManager] scale_position: ({base_x}, {base_y}) -> {scaled_pos} (offset: {self.ui_offset_x}, {self.ui_offset_y})")
        return scaled_pos
    
    def scale_size(self, base_width, base_height):
        """Scale base size to actual screen size"""
        scaled_size = (base_width * self.ui_scale, base_height * self.ui_scale)
        if DEBUG_SCALE:
            runtime_globals.game_console.log(f"[UIManager] scale_size: ({base_width}, {base_height}) -> {scaled_size}")
        return scaled_size
    
    def scale_rect(self, base_rect):
        """Scale a base rect to actual screen rect"""
        scaled_x, scaled_y = self.scale_position(base_rect.x, base_rect.y)
        scaled_w, scaled_h = self.scale_size(base_rect.width, base_rect.height)
        scaled_rect = pygame.Rect(scaled_x, scaled_y, scaled_w, scaled_h)
        if DEBUG_SCALE:
            runtime_globals.game_console.log(f"[UIManager] scale_rect: {base_rect} -> {scaled_rect}")
        return scaled_rect
    
    def unscale_position(self, screen_x, screen_y):
        """Convert screen position back to base UI coordinates"""
        base_x = (screen_x - self.ui_offset_x) // self.ui_scale
        base_y = (screen_y - self.ui_offset_y) // self.ui_scale
        return (base_x, base_y)
    
    def screen_to_ui_pos(self, screen_pos):
        """Convert screen position to UI coordinates (base coordinates)"""
        if not screen_pos:
            return None
        ui_x = (screen_pos[0] - self.ui_offset_x) / self.ui_scale
        ui_y = (screen_pos[1] - self.ui_offset_y) / self.ui_scale
        return (ui_x, ui_y)
    
    def ui_to_screen_rect(self, ui_rect):
        """Convert UI rect (base coordinates) to screen rect"""
        if not ui_rect:
            return None
        return self.scale_rect(ui_rect)
            
    def get_border_size(self):
        """Get border size for current UI scale"""
        return BORDER_SIZES.get(self.ui_scale, 2)
        
    def get_title_font_size(self):
        """Get title font size for current UI scale"""
        font_size = TITLE_FONT_SIZES.get(self.ui_scale, 24)
        if DEBUG_SCALE:
            runtime_globals.game_console.log(f"[UIManager] get_title_font_size: {font_size} (scale: {self.ui_scale})")
        return font_size
        
    def get_text_font_size(self):
        """Get text font size for current UI scale"""
        font_size = TEXT_FONT_SIZES.get(self.ui_scale, 16)
        if DEBUG_SCALE:
            runtime_globals.game_console.log(f"[UIManager] get_text_font_size: {font_size} (scale: {self.ui_scale})")
        return font_size
        
    def get_spacing_value(self):
        """Get spacing value for current UI scale"""
        return SPACING_VALUES.get(self.ui_scale, 1)
    
    def get_sprite_scale(self):
        """Get the sprite scale index for current UI scale"""
        sprite_scale = SPRITE_SCALE_MAP.get(self.ui_scale, 1)
        if DEBUG_SCALE:
            runtime_globals.game_console.log(f"[UIManager] get_sprite_scale: {sprite_scale} (ui_scale: {self.ui_scale})")
        return sprite_scale
    
    def set_theme(self, theme):
        self.theme = theme
        # Mark all components for redraw
        for component in self.components:
            component.needs_redraw = True
        
    def get_theme_colors(self):
        """Return background, foreground, and highlight colors for current theme"""
        # If color animation is active, return interpolated colors
        if self.is_animating_colors and self.current_animated_colors:
            return self.current_animated_colors
            
        if self.theme == "PURPLE":
            colors = {"bg": PURPLE_DARK, "fg": PURPLE, "highlight": PURPLE_LIGHT, "black": BLACK, "grey": GREY}
        elif self.theme == "GREEN":
            colors = {"bg": GREEN_DARK, "fg": GREEN, "highlight": GREEN_LIGHT, "black": BLACK, "grey": GREY}
        elif self.theme == "BLUE":
            colors = {"bg": BLUE_DARK, "fg": BLUE, "highlight": BLUE_LIGHT, "black": BLACK, "grey": GREY}
        elif self.theme == "YELLOW":
            colors = {"bg": YELLOW_DARK, "fg": YELLOW, "highlight": YELLOW_LIGHT, "black": BLACK, "grey": GREY}
        elif self.theme == "RED":
            colors = {"bg": RED_DARK, "fg": RED, "highlight": RED_LIGHT, "black": BLACK, "grey": GREY}
        elif self.theme == "GRAY":
            colors = {"bg": GRAY_DARK, "fg": GRAY, "highlight": GRAY_LIGHT, "black": BLACK, "grey": GREY}
        elif self.theme == "YELLOW_BRIGHT":
            colors = {"bg": YELLOW_BRIGHT_DARK, "fg": YELLOW_BRIGHT, "highlight": YELLOW_BRIGHT_LIGHT, "black": BLACK, "grey": GREY}
        elif self.theme == "RED_DARK_VARIANT":
            colors = {"bg": RED_DARK_VARIANT_DARK, "fg": RED_DARK_VARIANT, "highlight": RED_DARK_VARIANT_LIGHT, "black": BLACK, "grey": GREY}
        elif self.theme == "CYAN":
            colors = {"bg": CYAN_DARK, "fg": CYAN, "highlight": CYAN_LIGHT, "black": BLACK, "grey": GREY}
        elif self.theme == "LIME":
            colors = {"bg": LIME_DARK, "fg": LIME, "highlight": LIME_LIGHT, "black": BLACK, "grey": GREY}
        elif self.theme == "VIOLET":
            colors = {"bg": VIOLET_DARK, "fg": VIOLET, "highlight": VIOLET_LIGHT, "black": BLACK, "grey": GREY}
        elif self.theme == "TEAL":
            colors = {"bg": TEAL_DARK, "fg": TEAL, "highlight": TEAL_LIGHT, "black": BLACK, "grey": GREY}
        elif self.theme == "NAVY":
            colors = {"bg": NAVY_DARK, "fg": NAVY, "highlight": NAVY_LIGHT, "black": BLACK, "grey": GREY}
        else:
            colors = {"bg": BLACK, "fg": GREY, "highlight": GREY, "black": BLACK, "grey": GREY}
        
        # Validate that all required keys exist
        if "highlight" not in colors:
            print(f"ERROR: Missing highlight key for theme {self.theme}")
            colors["highlight"] = colors.get("fg", GREY)
            
        return colors
    
    def start_color_animation(self, target_theme, callback=None):
        """Start color animation from current theme to target theme"""
        if self.is_animating_colors:
            # Already animating, finish current animation first
            self.finish_color_animation()
        
        self.is_animating_colors = True
        self.color_animation_frame_counter = 0
        self.color_animation_source_theme = self.theme
        self.color_animation_target_theme = target_theme
        self.color_animation_callback = callback
        
        # Initialize current animated colors to source theme
        self.current_animated_colors = self._get_theme_colors_by_name(self.color_animation_source_theme)
        
        if DEBUG_SCALE:
            runtime_globals.game_console.log(f"[UIManager] Started color animation from {self.theme} to {target_theme}")
    
    def update_color_animation(self):
        """Update color animation progress with smooth color interpolation"""
        if not self.is_animating_colors:
            return False
            
        self.color_animation_frame_counter += 1
        
        # Only update colors every N frames to save performance (but still smooth)
        if self.color_animation_frame_counter % self.color_animation_redraw_interval == 0:
            # Calculate interpolation progress (0.0 to 1.0)
            progress = min(1.0, self.color_animation_frame_counter / self.color_animation_total_frames)
            
            # Get source and target color dictionaries
            source_colors = self._get_theme_colors_by_name(self.color_animation_source_theme)
            target_colors = self._get_theme_colors_by_name(self.color_animation_target_theme)
            
            # Interpolate each color channel
            self.current_animated_colors = {}
            for color_key in source_colors:
                self.current_animated_colors[color_key] = self._interpolate_color(
                    source_colors[color_key], 
                    target_colors[color_key], 
                    progress
                )
            
            # Mark all components for redraw
            for component in self.components:
                component.needs_redraw = True
        
        # Check if animation should end (after exactly 1 second based on frame rate)
        if self.color_animation_frame_counter >= self.color_animation_total_frames:
            self.finish_color_animation()
            return True
            
        return False
    
    def _interpolate_color(self, color1, color2, progress):
        """Interpolate between two RGB colors based on progress (0.0 to 1.0)"""
        if len(color1) >= 3 and len(color2) >= 3:
            r = int(color1[0] + (color2[0] - color1[0]) * progress)
            g = int(color1[1] + (color2[1] - color1[1]) * progress)
            b = int(color1[2] + (color2[2] - color1[2]) * progress)
            
            # Handle alpha channel if present
            if len(color1) >= 4 and len(color2) >= 4:
                a = int(color1[3] + (color2[3] - color1[3]) * progress)
                return (r, g, b, a)
            else:
                return (r, g, b)
        else:
            # Fallback for malformed colors
            return color2 if progress > 0.5 else color1
    
    def finish_color_animation(self):
        """Complete the color animation and switch to target theme"""
        if not self.is_animating_colors:
            return
            
        # Set final theme
        final_theme = self.color_animation_target_theme
        self.set_theme(final_theme)
        
        # Reset animation state
        self.is_animating_colors = False
        self.color_animation_frame_counter = 0
        self.current_animated_colors = None
        
        # Call callback if provided
        if self.color_animation_callback:
            self.color_animation_callback()
            self.color_animation_callback = None
        
        if DEBUG_SCALE:
            runtime_globals.game_console.log(f"[UIManager] Finished color animation, now using theme {final_theme}")
    
    def _get_theme_colors_by_name(self, theme_name):
        """Get theme colors by theme name (internal helper)"""
        if theme_name == "PURPLE":
            return {"bg": PURPLE_DARK, "fg": PURPLE, "highlight": PURPLE_LIGHT, "black": BLACK, "grey": GREY}
        elif theme_name == "GREEN":
            return {"bg": GREEN_DARK, "fg": GREEN, "highlight": GREEN_LIGHT, "black": BLACK, "grey": GREY}
        elif theme_name == "BLUE":
            return {"bg": BLUE_DARK, "fg": BLUE, "highlight": BLUE_LIGHT, "black": BLACK, "grey": GREY}
        elif theme_name == "YELLOW":
            return {"bg": YELLOW_DARK, "fg": YELLOW, "highlight": YELLOW_LIGHT, "black": BLACK, "grey": GREY}
        elif theme_name == "RED":
            return {"bg": RED_DARK, "fg": RED, "highlight": RED_LIGHT, "black": BLACK, "grey": GREY}
        elif theme_name == "GRAY":
            return {"bg": GRAY_DARK, "fg": GRAY, "highlight": GRAY_LIGHT, "black": BLACK, "grey": GREY}
        elif theme_name == "YELLOW_BRIGHT":
            return {"bg": YELLOW_BRIGHT_DARK, "fg": YELLOW_BRIGHT, "highlight": YELLOW_BRIGHT_LIGHT, "black": BLACK, "grey": GREY}
        elif theme_name == "RED_DARK_VARIANT":
            return {"bg": RED_DARK_VARIANT_DARK, "fg": RED_DARK_VARIANT, "highlight": RED_DARK_VARIANT_LIGHT, "black": BLACK, "grey": GREY}
        elif theme_name == "CYAN":
            return {"bg": CYAN_DARK, "fg": CYAN, "highlight": CYAN_LIGHT, "black": BLACK, "grey": GREY}
        elif theme_name == "LIME":
            return {"bg": LIME_DARK, "fg": LIME, "highlight": LIME_LIGHT, "black": BLACK, "grey": GREY}
        return {"bg": BLACK, "fg": GREY, "highlight": GREY, "black": BLACK, "grey": GREY}

    def set_global_shadow_mode(self, mode):
        """Set the global shadow mode for all components
        
        Args:
            mode: None (use component settings), "disabled" (no shadows), 
                  "component" (shadows on backgrounds/borders only), 
                  "full" (shadows on everything)
        """
        self.global_shadow_mode = mode
        # Mark all components for redraw
        for component in self.components:
            component.needs_redraw = True
    
    def get_shadow_mode_for_component(self, component):
        """Get the effective shadow mode for a specific component
        
        Returns:
            "disabled": No shadows
            "component": Shadows on component background/border only  
            "full": Shadows on everything (text, decorators, etc.)
        """
        if self.global_shadow_mode is not None:
            return self.global_shadow_mode
        
        # Use component-specific setting if available
        if hasattr(component, 'shadow_mode'):
            return component.shadow_mode
        
        # Default to disabled
        return "disabled"
    
    def should_render_shadow(self, component, element_type="component"):
        """Check if shadows should be rendered for a specific element
        
        Args:
            component: The UI component
            element_type: "component" (background/border), "text", "decorator", "icon"
            
        Returns:
            bool: True if shadow should be rendered
        """
        shadow_mode = self.get_shadow_mode_for_component(component)
        
        if shadow_mode == "disabled":
            return False
        elif shadow_mode == "component":
            return element_type == "component"
        elif shadow_mode == "full":
            return True
        
        return False

    def add_component(self, component):
        """Add a component to the UI manager and scale its position/size"""
        self.components.append(component)
        component.manager = self
        
        # Handle screen coordinate components differently
        if hasattr(component, 'use_screen_coordinates') and component.use_screen_coordinates:
            # For screen coordinate components, only scale the size (keeping aspect ratio)
            # but apply integer scaling to maintain consistency
            base_rect = component.rect.copy()
            component.base_rect = base_rect  # Store original base coordinates
            
            # Scale only the size using UI scale for consistency
            scaled_width = int(base_rect.width * self.ui_scale)
            scaled_height = int(base_rect.height * self.ui_scale)
            
            # Keep the position as-is (screen coordinates)
            component.rect = pygame.Rect(base_rect.x, base_rect.y, scaled_width, scaled_height)
            
            if DEBUG_SCALE:
                runtime_globals.game_console.log(f"[UIManager] Added {component.__class__.__name__} (screen coords): base={base_rect} -> screen={component.rect}")
        else:
            # Scale the component's position and size from base coordinates to screen coordinates
            base_rect = component.rect.copy()
            component.base_rect = base_rect  # Store original base coordinates
            component.rect = self.scale_rect(base_rect)  # Scale to screen coordinates
            
            if DEBUG_SCALE:
                runtime_globals.game_console.log(f"[UIManager] Added {component.__class__.__name__}: base={base_rect} -> screen={component.rect}")
        
        # Call component's manager set callback if it exists (after base_rect is set)
        if hasattr(component, 'on_manager_set'):
            component.on_manager_set()
        
        # Add to focusable list if the component is focusable
        if hasattr(component, "focusable") and component.focusable:
            self.focusable_components.append(component)
            
            # If we don't have a valid focus, try to set focus to first visible focusable
            if self.focused_index == -1 and self.focusable_components:
                # Find first visible focusable component
                for i, fc in enumerate(self.focusable_components):
                    if not hasattr(fc, 'visible') or fc.visible:
                        self.focused_index = i
                        fc.focused = True
                        fc.needs_redraw = True
                        if hasattr(fc, 'on_focus_gained'):
                            fc.on_focus_gained()
                        break
        
        return component
    
    def remove_component(self, component):
        """Remove a component from the UI manager"""
        if component in self.components:
            self.components.remove(component)
            # Also remove from focusable list if present
            if component in self.focusable_components:
                # Check if this was the focused component
                was_focused = self.focusable_components[self.focused_index] == component if 0 <= self.focused_index < len(self.focusable_components) else False
                old_index = self.focusable_components.index(component)
                
                self.focusable_components.remove(component)
                
                # Reset focus index if it's now invalid or if we removed the focused component
                if self.focused_index >= len(self.focusable_components):
                    self.focused_index = -1
                    # Try to focus a remaining component
                    if self.focusable_components:
                        for i, fc in enumerate(self.focusable_components):
                            if not hasattr(fc, 'visible') or fc.visible:
                                self.focused_index = i
                                fc.focused = True
                                fc.needs_redraw = True
                                if hasattr(fc, 'on_focus_gained'):
                                    fc.on_focus_gained()
                                break
                elif was_focused and self.focusable_components:
                    # We removed the focused component but index is still valid
                    # Try to focus the component at the same index or wrap around
                    new_index = min(old_index, len(self.focusable_components) - 1)
                    self.focused_index = new_index
                    if 0 <= new_index < len(self.focusable_components):
                        fc = self.focusable_components[new_index]
                        fc.focused = True
                        fc.needs_redraw = True
                        if hasattr(fc, 'on_focus_gained'):
                            fc.on_focus_gained()
                    
            component.manager = None
            if DEBUG_SCALE:
                runtime_globals.game_console.log(f"[UIManager] Removed {component.__class__.__name__}")
        
    def get_next_visible_focusable(self, start_index):
        """Get the next visible focusable component index"""
        if not self.focusable_components:
            return -1
            
        total_components = len(self.focusable_components)
        for i in range(1, total_components + 1):
            next_index = (start_index + i) % total_components
            component = self.focusable_components[next_index]
            if not hasattr(component, 'visible') or component.visible:
                return next_index
        return -1
    
    def get_prev_visible_focusable(self, start_index):
        """Get the previous visible focusable component index"""
        if not self.focusable_components:
            return -1
            
        total_components = len(self.focusable_components)
        for i in range(1, total_components + 1):
            prev_index = (start_index - i) % total_components
            component = self.focusable_components[prev_index]
            if not hasattr(component, 'visible') or component.visible:
                return prev_index
        return -1
        
    def focus_next(self):
        if not self.focusable_components:
            return
            
        # Find next visible focusable component
        current_index = self.focused_index if self.focused_index >= 0 else -1
        next_index = self.get_next_visible_focusable(current_index)
        
        if next_index == -1:
            return  # No visible components found
            
        # Unfocus old component
        if self.focused_index >= 0:
            old_component = self.focusable_components[self.focused_index]
            old_component.focused = False
            old_component.needs_redraw = True
            if hasattr(old_component, 'on_focus_lost'):
                old_component.on_focus_lost()
            
        # Focus new component
        self.focused_index = next_index
        new_component = self.focusable_components[self.focused_index]
        new_component.focused = True
        new_component.needs_redraw = True
        if hasattr(new_component, 'on_focus_gained'):
            new_component.on_focus_gained()
            
        # Play navigation sound
        if hasattr(runtime_globals, 'game_sound') and runtime_globals.game_sound:
            runtime_globals.game_sound.play("menu")
        
    def focus_prev(self):
        if not self.focusable_components:
            return
            
        # Find previous visible focusable component
        current_index = self.focused_index if self.focused_index >= 0 else 0
        prev_index = self.get_prev_visible_focusable(current_index)
        
        if prev_index == -1:
            return  # No visible components found
            
        # Unfocus old component
        if self.focused_index >= 0:
            old_component = self.focusable_components[self.focused_index]
            old_component.focused = False
            old_component.needs_redraw = True
            if hasattr(old_component, 'on_focus_lost'):
                old_component.on_focus_lost()
            
        # Focus new component
        self.focused_index = prev_index
        new_component = self.focusable_components[self.focused_index]
        new_component.focused = True
        new_component.needs_redraw = True
        if hasattr(new_component, 'on_focus_gained'):
            new_component.on_focus_gained()
            
        # Play navigation sound
        if hasattr(runtime_globals, 'game_sound') and runtime_globals.game_sound:
            runtime_globals.game_sound.play("menu")
        
    def handle_event(self, event):
        """Handle input events (keyboard, joystick, mouse)"""
        # All events are now tuples: (event_type, event_data)
        event_type, event_data = event

        # Modal components have highest priority (like tooltips)
        # Stats panel blocks all events while visible.  Mouse-wise it only
        # closes on an actual click (LCLICK) — hover/motion, scroll and drags
        # are swallowed without closing.  Keyboard / joystick buttons keep the
        # original close-on-any-press behaviour.
        if self.active_stats_panel and self.active_stats_panel.visible:
            if event_type in ("MOUSE_MOTION", "RCLICK", "SCROLL",
                              "DRAG_START", "DRAG_MOTION", "DRAG_END"):
                return True  # Block, but keep the panel open
            self.remove_component(self.active_stats_panel)
            self.active_stats_panel = None
            runtime_globals.game_sound.play("cancel")
            return True  # Always block events when stats panel is visible
        
        # Menu blocks all events while visible
        if self.active_menu and self.active_menu.visible:
            runtime_globals.game_console.log(f"[UIManager] Menu is visible, handling event")
            self.active_menu.handle_event(event)
            return True  # Always block events when menu is visible

        # Tooltips dismiss on a deliberate press — a button, or a click of
        # either mouse button. Passive pointer traffic (hover, wheel, a drag
        # in progress) is swallowed without closing, so simply moving the
        # mouse no longer snatches the tooltip away before it can be read.
        if self.active_tooltip:
            if event_type in ("MOUSE_MOTION", "SCROLL",
                              "DRAG_START", "DRAG_MOTION", "DRAG_END"):
                return True  # Block, but keep the tooltip open
            self.hide_tooltip()
            return True


        # Handle mouse motion for focus updates
        if event_type == "MOUSE_MOTION" and event_data and "pos" in event_data:
            self.update_mouse_focus(event_data["pos"])
        
        # In touch mode, update focus position when receiving LCLICK (since there's no MOUSE_MOTION)
        if event_type == "LCLICK" and runtime_globals.INPUT_MODE == runtime_globals.TOUCH_MODE:
            if event_data and "pos" in event_data:
                self.update_mouse_focus(event_data["pos"])
        
        # Let focused component handle the event first (priority order).
        # The index is bounds-checked: a view that draws itself and registers
        # no focusable components at all (the temporary-evolution chooser)
        # leaves the list empty while the index still points at 0.
        if 0 <= self.focused_index < len(self.focusable_components):
            focused_component = self.focusable_components[self.focused_index]
            if focused_component.visible and hasattr(focused_component, 'handle_event'):
                if focused_component.handle_event(event):
                    return True
        
        return self.handle_input_action(event)
    
    def update_mouse_focus(self, mouse_pos):
        """Update focus based on mouse position with sub-component support"""
        if runtime_globals.INPUT_MODE not in [runtime_globals.MOUSE_MODE, runtime_globals.TOUCH_MODE]:
            return
        
        self.last_mouse_pos = mouse_pos
        
        # Find which focusable component the mouse is over
        best_component = None
        best_component_index = -1
        best_sub_rect = None
        
        for i, component in enumerate(self.focusable_components):
            # Skip invisible components
            if hasattr(component, 'visible') and not component.visible:
                continue
                
            # Check collision - component.rect is always in screen coordinates
            # Use screen mouse position for collision detection
            if hasattr(component, 'rect') and component.rect.collidepoint(mouse_pos):
                # Mouse is over this component
                best_component = component
                best_component_index = i
                
                # Check if component has sub-component support
                if hasattr(component, 'get_mouse_sub_rect'):
                    # For get_mouse_sub_rect, use appropriate coordinate system
                    if hasattr(component, 'use_screen_coordinates') and component.use_screen_coordinates:
                        # Screen coordinate components expect screen coordinates
                        sub_rect = component.get_mouse_sub_rect(mouse_pos)
                    else:
                        # Regular components expect UI coordinates
                        ui_mouse_x = (mouse_pos[0] - self.ui_offset_x) / self.ui_scale
                        ui_mouse_y = (mouse_pos[1] - self.ui_offset_y) / self.ui_scale
                        ui_mouse_pos = (ui_mouse_x, ui_mouse_y)
                        sub_rect = component.get_mouse_sub_rect(ui_mouse_pos)
                    
                    if sub_rect:
                        best_sub_rect = sub_rect
                        # Mouse is over a valid sub-component
                    else:
                        # Mouse is over component but not over any sub-component - skip this component
                        best_component = None
                        best_component_index = -1
                        continue
                else:
                    # Use the main component rect
                    best_sub_rect = component.rect
                break
        
        # If the currently focused component opted into sticky focus, hover
        # never moves or clears it — focus is only released by an explicit
        # click outside (handled by handle_event) or programmatic action.
        if self.focused_index >= 0:
            current = self.focusable_components[self.focused_index]
            if getattr(current, 'sticky_focus', False):
                self.mouse_over_component = best_component
                self.mouse_over_sub_rect = best_sub_rect
                return

        # If mouse is not over any valid component, clear focus
        if not best_component:
            # Clear focus
            if self.focused_index >= 0:
                old_component = self.focusable_components[self.focused_index]
                old_component.focused = False
                old_component.needs_redraw = True
                if hasattr(old_component, 'on_focus_lost'):
                    old_component.on_focus_lost()
                self.focused_index = -1
            return

        # Update focus if needed
        if best_component and self.focused_index != best_component_index:
            # Update focus
            if self.focused_index >= 0:
                old_component = self.focusable_components[self.focused_index]
                old_component.focused = False
                old_component.needs_redraw = True
                if hasattr(old_component, 'on_focus_lost'):
                    old_component.on_focus_lost()

            self.focused_index = best_component_index
            best_component.focused = True
            best_component.needs_redraw = True
            if hasattr(best_component, 'on_focus_gained'):
                best_component.on_focus_gained()
            
        # Store current state
        self.mouse_over_component = best_component
        self.mouse_over_sub_rect = best_sub_rect
    
    def _rect_to_points(self, rect):
        """Convert a pygame.Rect to a list of corner points (clockwise from top-left)"""
        return [
            (rect.x, rect.y),  # top-left
            (rect.x + rect.width, rect.y),  # top-right
            (rect.x + rect.width, rect.y + rect.height),  # bottom-right
            (rect.x, rect.y + rect.height)  # bottom-left
        ]
    
    def _normalize_polygon_points(self, poly1, poly2):
        """Ensure both polygons have the same number of points for smooth interpolation
        
        If they have different point counts, the polygon with fewer points will be 
        subdivided by adding intermediate points along its edges.
        """
        len1, len2 = len(poly1), len(poly2)
        
        if len1 == len2:
            return poly1, poly2
        
        # Determine which polygon needs more points
        if len1 < len2:
            poly1 = self._subdivide_polygon(poly1, len2)
        else:
            poly2 = self._subdivide_polygon(poly2, len1)
            
        return poly1, poly2
    
    def _subdivide_polygon(self, polygon, target_points):
        """Subdivide a polygon to have the target number of points"""
        current_points = len(polygon)
        if current_points >= target_points:
            return polygon
            
        # Calculate how many points to add
        points_to_add = target_points - current_points
        
        # Add points by subdividing the longest edges
        result = list(polygon)
        
        for _ in range(points_to_add):
            # Find the longest edge
            longest_edge_idx = 0
            longest_edge_length = 0
            
            for i in range(len(result)):
                p1 = result[i]
                p2 = result[(i + 1) % len(result)]
                edge_length = ((p2[0] - p1[0]) ** 2 + (p2[1] - p1[1]) ** 2) ** 0.5
                
                if edge_length > longest_edge_length:
                    longest_edge_length = edge_length
                    longest_edge_idx = i
            
            # Add a midpoint to the longest edge
            p1 = result[longest_edge_idx]
            p2 = result[(longest_edge_idx + 1) % len(result)]
            midpoint = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
            
            # Insert the midpoint
            result.insert(longest_edge_idx + 1, midpoint)
        
        return result
    
    def rects_equal(self, rect1, rect2):
        """Check if two rects are equal (within a small tolerance)"""
        if not rect1 or not rect2:
            return False
        return (abs(rect1.x - rect2.x) < 2 and abs(rect1.y - rect2.y) < 2 and
                abs(rect1.width - rect2.width) < 2 and abs(rect1.height - rect2.height) < 2)
    
    def shapes_equal(self, shape1, shape2):
        """Check if two shapes are equal (can be rects or polygons)"""
        if not shape1 or not shape2:
            return False
            
        # Both are rects
        if isinstance(shape1, pygame.Rect) and isinstance(shape2, pygame.Rect):
            return self.rects_equal(shape1, shape2)
        
        # Both are polygons (lists of points)
        if isinstance(shape1, list) and isinstance(shape2, list):
            if len(shape1) != len(shape2):
                return False
            
            for i in range(len(shape1)):
                p1, p2 = shape1[i], shape2[i]
                if abs(p1[0] - p2[0]) > 2 or abs(p1[1] - p2[1]) > 2:
                    return False
            return True
        
        # Mixed types - convert rect to polygon and compare
        if isinstance(shape1, pygame.Rect):
            shape1 = self._rect_to_points(shape1)
        if isinstance(shape2, pygame.Rect):
            shape2 = self._rect_to_points(shape2)
            
        return self.shapes_equal(shape1, shape2)
    
    def find_nearest_component_in_direction(self, direction):
        """Find the nearest focusable component in the given direction.
        
        Navigation priority:
        - UP: TOP, then TOP-LEFT, then TOP-RIGHT
        - DOWN: DOWN, then DOWN-LEFT, then DOWN-RIGHT  
        - LEFT: LEFT, then LEFT-UP, then LEFT-DOWN
        - RIGHT: RIGHT, then RIGHT-UP, then RIGHT-DOWN
        
        Source anchor points:
        - UP/LEFT: top-left corner
        - RIGHT: bottom-right corner
        - DOWN: bottom-left corner
        
        Target reference point: always top-left corner
        """
        if self.focused_index < 0 or not self.focusable_components:
            return -1
            
        current_component = self.focusable_components[self.focused_index]
        current_rect = current_component.rect
        
        # Get current focus sub-rect if available
        if hasattr(current_component, 'get_focused_sub_rect'):
            current_rect = current_component.get_focused_sub_rect() or current_rect
        
        # Select anchor point based on direction
        if direction == "UP":
            anchor = (current_rect.left, current_rect.top)  # top_left
        elif direction == "LEFT":
            anchor = (current_rect.left, current_rect.top)  # top_left
        elif direction == "RIGHT":
            anchor = (current_rect.right, current_rect.bottom)  # bottom_right
        else:  # DOWN
            # Compare top edges (like UP does) rather than the source's
            # bottom: a tall source whose rect overlaps the next component
            # below made that component unreachable going down while still
            # reachable going up (e.g. Status scene: name -> Stage skipped).
            anchor = (current_rect.left, current_rect.top)  # top_left
        
        candidates = []
        
        for i, component in enumerate(self.focusable_components):
            if i == self.focused_index:
                continue
            
            # Skip invisible or non-focusable components
            if hasattr(component, 'visible') and not component.visible:
                continue
            if hasattr(component, 'focusable') and not component.focusable:
                continue
                
            target_rect = component.rect
            
            # Target reference point is always top-left
            reference = (target_rect.left, target_rect.top)
            
            # Calculate relative position
            dx = reference[0] - anchor[0]
            dy = reference[1] - anchor[1]
            
            # Determine priority based on direction
            # Lower priority value = better match
            priority = None
            
            if direction == "UP":
                if dy < 0:  # Target is above
                    if dx == 0 or (reference[0] >= anchor[0] and reference[0] < anchor[0] + current_rect.width):
                        priority = 0  # Directly above (aligned)
                    elif dx < 0:
                        priority = 1  # Top-left
                    else:
                        priority = 2  # Top-right
                        
            elif direction == "DOWN":
                if dy > 0:  # Target is below
                    if dx == 0 or (reference[0] >= anchor[0] and reference[0] < anchor[0] + current_rect.width):
                        priority = 0  # Directly below (aligned)
                    elif dx < 0:
                        priority = 1  # Down-left
                    else:
                        priority = 2  # Down-right
                        
            elif direction == "LEFT":
                if dx < 0:  # Target is to the left
                    if dy == 0 or (reference[1] >= anchor[1] - current_rect.height and reference[1] < anchor[1]):
                        priority = 0  # Directly left (aligned)
                    elif dy < 0:
                        priority = 1  # Left-up
                    else:
                        priority = 2  # Left-down
                        
            elif direction == "RIGHT":
                if dx > 0:  # Target is to the right
                    if dy == 0 or (reference[1] <= anchor[1] and reference[1] > anchor[1] - current_rect.height):
                        priority = 0  # Directly right (aligned)
                    elif dy < 0:
                        priority = 1  # Right-up
                    else:
                        priority = 2  # Right-down
            
            if priority is not None:
                # Calculate distance for sorting within same priority
                distance = (dx * dx + dy * dy) ** 0.5
                candidates.append({
                    'index': i,
                    'priority': priority,
                    'distance': distance,
                    'dx': abs(dx),
                    'dy': abs(dy)
                })
        
        if not candidates:
            return -1
        
        # Sort by priority first, then by primary-axis distance, then secondary-axis.
        # This ensures DOWN/UP prefers vertically close targets and LEFT/RIGHT
        # prefers horizontally close targets, avoiding diagonal shortcuts.
        if direction in ("DOWN", "UP"):
            candidates.sort(key=lambda c: (c['priority'], c['dy'], c['dx']))
        else:
            candidates.sort(key=lambda c: (c['priority'], c['dx'], c['dy']))
        
        return candidates[0]['index']
    
    def focus_direction(self, direction):
        """Move focus in the specified direction (UP, DOWN, LEFT, RIGHT)"""
        if not self.focusable_components:
            return False
        
        # Check if currently focused component is still visible
        if self.focused_index >= 0:
            current_component = self.focusable_components[self.focused_index]
            if hasattr(current_component, 'visible') and not current_component.visible:
                # Current component is invisible, clear focus and find next visible one
                current_component.focused = False
                current_component.needs_redraw = True
                if hasattr(current_component, 'on_focus_lost'):
                    current_component.on_focus_lost()
                self.focused_index = -1
            
        # If no component is currently focused, focus the first visible one
        if self.focused_index < 0:
            first_visible = self.get_next_visible_focusable(-1)
            if first_visible == -1:
                return False  # No visible components
                
            self.focused_index = first_visible
            component = self.focusable_components[first_visible]
            component.focused = True
            component.needs_redraw = True
            if hasattr(component, 'on_focus_gained'):
                component.on_focus_gained()
            
            # Play navigation sound
            if hasattr(runtime_globals, 'game_sound') and runtime_globals.game_sound:
                runtime_globals.game_sound.play("menu")
            return True
            
        new_index = self.find_nearest_component_in_direction(direction)
        if new_index >= 0 and new_index != self.focused_index:
            # Update focus
            if self.focused_index >= 0:
                old_component = self.focusable_components[self.focused_index]
                old_component.focused = False
                old_component.needs_redraw = True
                if hasattr(old_component, 'on_focus_lost'):
                    old_component.on_focus_lost()
            
            self.focused_index = new_index
            new_component = self.focusable_components[self.focused_index]
            new_component.focused = True
            new_component.needs_redraw = True
            if hasattr(new_component, 'on_focus_gained'):
                new_component.on_focus_gained()
            
            # Play navigation sound
            if hasattr(runtime_globals, 'game_sound') and runtime_globals.game_sound:
                runtime_globals.game_sound.play("menu")
            return True
        
        return False
    
    def rects_equal(self, rect1, rect2):
        """Check if two rects are equal (within a small tolerance)"""
        if not rect1 or not rect2:
            return False
        return (abs(rect1.x - rect2.x) < 2 and abs(rect1.y - rect2.y) < 2 and
                abs(rect1.width - rect2.width) < 2 and abs(rect1.height - rect2.height) < 2)
    
    def handle_input_action(self, event):
        """Handle input actions and route to appropriate components"""
        # Event is a tuple: (event_type, event_data)
        event_type, event_data = event

        # Handle mouse clicks differently from keyboard actions
        if event_type == "LCLICK":
            # For mouse clicks, find the component under the mouse and handle it there
            # Try to get mouse position from input_manager first, then from event_data
            mouse_pos = None
            if hasattr(self, '_input_manager') and self._input_manager:
                mouse_pos = self._input_manager.get_mouse_position()
            elif event_data and "pos" in event_data:
                mouse_pos = event_data["pos"]
            
            if mouse_pos:
                runtime_globals.game_console.log(f"[UIManager] LCLICK at {mouse_pos}, checking {len(self.components)} components")

                # Sticky-focus components: unfocus if the click is outside their
                # rect (the scene has already given the keyboard overlay first
                # crack at the click via handle_keyboard_click, so anything
                # reaching here is genuinely outside both the field and its
                # keyboard).
                if self.focused_index >= 0:
                    fc = self.focusable_components[self.focused_index]
                    if getattr(fc, 'sticky_focus', False):
                        if not (hasattr(fc, 'rect') and fc.rect.collidepoint(mouse_pos)):
                            fc.focused = False
                            fc.needs_redraw = True
                            if hasattr(fc, 'on_focus_lost'):
                                fc.on_focus_lost()
                            self.focused_index = -1

                # Check components in reverse order (top to bottom) for mouse clicks
                for component in reversed(self.components):
                    # Skip invisible components
                    if hasattr(component, 'visible') and not component.visible:
                        runtime_globals.game_console.log(f"[UIManager] Skipping {component.__class__.__name__} (invisible)")
                        continue
                    
                    comp_name = component.__class__.__name__
                    has_rect = hasattr(component, 'rect')
                    if has_rect:
                        collides = component.rect.collidepoint(mouse_pos)
                        runtime_globals.game_console.log(f"[UIManager] Component {comp_name}: rect={component.rect}, collides={collides}")
                    else:
                        runtime_globals.game_console.log(f"[UIManager] Component {comp_name}: no rect")
                        
                    if hasattr(component, 'rect') and component.rect.collidepoint(mouse_pos):
                        # First try explicit mouse click handler
                        if hasattr(component, 'handle_mouse_click'):
                            runtime_globals.game_console.log(f"[UIManager] Calling handle_mouse_click on {comp_name}")
                            result = component.handle_mouse_click(mouse_pos, event_type)
                            runtime_globals.game_console.log(f"[UIManager] handle_mouse_click returned {result}")
                            if result:
                                # Update focus to this component if it's focusable and handled the click
                                if hasattr(component, 'focusable') and component.focusable:
                                    try:
                                        new_focus_index = self.focusable_components.index(component)
                                        if new_focus_index != self.focused_index:
                                            # Update focus
                                            if self.focused_index >= 0:
                                                old_component = self.focusable_components[self.focused_index]
                                                old_component.focused = False
                                                old_component.needs_redraw = True
                                                if hasattr(old_component, 'on_focus_lost'):
                                                    old_component.on_focus_lost()
                                        
                                        self.focused_index = new_focus_index
                                        component.focused = True
                                        component.needs_redraw = True
                                        if hasattr(component, 'on_focus_gained'):
                                            component.on_focus_gained()
                                    except ValueError:
                                        # Component not in focusable list, that's fine
                                        pass
                            return True
                        
                        # If no explicit handler, try standard focus and activation for focusable components
                        elif hasattr(component, 'focusable') and component.focusable:
                            try:
                                new_focus_index = self.focusable_components.index(component)
                                
                                # Update focus if needed
                                if new_focus_index != self.focused_index:
                                    if self.focused_index >= 0:
                                        old_component = self.focusable_components[self.focused_index]
                                        old_component.focused = False
                                        old_component.needs_redraw = True
                                        if hasattr(old_component, 'on_focus_lost'):
                                            old_component.on_focus_lost()
                                    
                                    self.focused_index = new_focus_index
                                    component.focused = True
                                    component.needs_redraw = True
                                    if hasattr(component, 'on_focus_gained'):
                                        component.on_focus_gained()
                                
                                # Activate the component (same as pressing A),
                                # unless it opts out of click-activation.  Text
                                # entry fields (TextInput / CodeEntry) set
                                # activate_on_click = False so a focus click does
                                # not also press their selected virtual key (which
                                # otherwise typed a stray "q" / cycled a letter).
                                if getattr(component, 'activate_on_click', True):
                                    if hasattr(component, 'handle_event'):
                                        component.handle_event(("A", None))
                                    elif hasattr(component, 'activate'):
                                        component.activate()
                                    elif hasattr(component, 'on_activate'):
                                        component.on_activate()

                                # Always return True - we handled the click by focusing and activating
                                return True
                                
                            except ValueError:
                                # Component not in focusable list, continue to next component
                                continue
                
                # If no component handled the mouse click, let it fall through
                return False

        elif event_type == "RCLICK":
            # Similar handling for right clicks
            if event_data and "pos" in event_data:
                mouse_pos = event_data["pos"]
                
                # Check components in reverse order (top to bottom) for mouse clicks
                for component in reversed(self.components):
                    # Skip invisible components
                    if hasattr(component, 'visible') and not component.visible:
                        continue
                        
                    if hasattr(component, 'handle_mouse_click') and hasattr(component, 'rect'):
                        if component.rect.collidepoint(mouse_pos):
                            return component.handle_mouse_click(mouse_pos, event_type)
                    elif hasattr(component, 'rect') and component.rect.collidepoint(mouse_pos):
                        # For right click, just focus without activating
                        if hasattr(component, 'focusable') and component.focusable:
                            try:
                                new_focus_index = self.focusable_components.index(component)
                                if new_focus_index != self.focused_index:
                                    if self.focused_index >= 0:
                                        old_component = self.focusable_components[self.focused_index]
                                        old_component.focused = False
                                        old_component.needs_redraw = True
                                        if hasattr(old_component, 'on_focus_lost'):
                                            old_component.on_focus_lost()
                                    
                                    self.focused_index = new_focus_index
                                    component.focused = True
                                    component.needs_redraw = True
                                    if hasattr(component, 'on_focus_gained'):
                                        component.on_focus_gained()
                            except ValueError:
                                continue
                
                # If no component handled the mouse click, let it fall through
                return False

        # Handle tooltip activation for keyboard A button
        if event_type == "A":
            if self.focused_index >= 0:
                focused_component = self.focusable_components[self.focused_index]
                if hasattr(focused_component, 'tooltip_text') and focused_component.tooltip_text:
                    # Toggle tooltip - hide if showing, show if hidden
                    if self.active_tooltip:
                        self.hide_tooltip()
                    else:
                        self.show_tooltip(focused_component.tooltip_text)
                    return True
            
        # First, let the focused component handle the event
        if self.focused_index >= 0:
            focused_component = self.focusable_components[self.focused_index]
            if hasattr(focused_component, 'handle_event'):
                if focused_component.handle_event(event):
                    return True
    
        # If focused component didn't handle it, try global UI actions
        # Scroll actions
        if event_type == "SCROLL":
            return self.handle_scroll(event)
        
        # Drag actions
        elif event_type in ["DRAG_START", "DRAG_MOTION", "DRAG_END"]:
            return self.handle_drag(event)
        
        # Global navigation actions (only if no component handled them)
        elif event_type == "LEFT":
            return self.focus_direction("LEFT")
        elif event_type == "RIGHT":
            return self.focus_direction("RIGHT")
        elif event_type == "UP":
            return self.focus_direction("UP")
        elif event_type == "DOWN":
            return self.focus_direction("DOWN")
        elif event_type in ["TAB"]:  # TAB for next component
            self.focus_next()
            return True
        elif event_type in ["SHIFT_TAB"]:
            self.focus_prev()
            return True
        
        # These are only fallbacks if no focused component handled them
        elif event_type == "A":
            return self.activate_focused_component()
            
        return False
    
    def handle_mouse_click(self, action):
        """Handle mouse click on components"""
        if not hasattr(self, '_input_manager'):
            return False
            
        mouse_pos = self._input_manager.get_mouse_position()
        
        # Check components in reverse order (top to bottom) using screen coordinates
        for component in reversed(self.components):
            # Skip invisible components
            if hasattr(component, 'visible') and not component.visible:
                continue
                
            if hasattr(component, 'handle_mouse_click') and hasattr(component, 'rect'):
                if component.rect.collidepoint(mouse_pos):
                    return component.handle_mouse_click(mouse_pos, action)
        
        return False
    
    def handle_scroll(self, event):
        """Handle scroll events on focused or hovered components"""
        # First try the focused component
        if self.focused_index >= 0:
            focused_component = self.focusable_components[self.focused_index]
            if hasattr(focused_component, 'handle_scroll'):
                result = focused_component.handle_scroll(event)
                if result:
                    return True
        
        # If no focused component handled it, try mouse hover. Invisible
        # components must be skipped — scenes stack alternative views on the
        # same rect (e.g. the digidex's module/pet/tree lists) and a hidden
        # one would otherwise swallow the scroll meant for the visible one.
        mouse_pos = runtime_globals.game_input.get_mouse_position()
        for component in self.components:
            if hasattr(component, 'visible') and not component.visible:
                continue
            if hasattr(component, 'handle_scroll') and hasattr(component, 'rect'):
                if component.rect.collidepoint(mouse_pos):
                    result = component.handle_scroll(event)
                    if result:
                        return True

        return False

    def handle_drag(self, event):
        """Handle drag events"""
        # Route to components that support dragging
        for component in self.components:
            if component.visible and hasattr(component, 'handle_drag'):
                result = component.handle_drag(event)
                if result:
                    return True
        
        return False
    
    def activate_focused_component(self):
        """Activate the currently focused component"""
        if self.focused_index >= 0:
            focused_component = self.focusable_components[self.focused_index]
            
            # Hide any existing tooltip first
            self.hide_tooltip()
            
            # Check if component has a tooltip and show it
            if hasattr(focused_component, 'tooltip_text') and focused_component.tooltip_text:
                self.show_tooltip(focused_component.tooltip_text)
                return True
            
            # Try the activate method first, then fall back to handle_event
            if hasattr(focused_component, 'activate'):
                return focused_component.activate()
            elif hasattr(focused_component, 'on_activate'):
                return focused_component.on_activate()
            elif hasattr(focused_component, 'handle_event'):
                return focused_component.handle_event(("A", None))
        return False
    
    def set_input_manager(self, input_manager):
        """Set the input manager reference for mouse handling"""
        self._input_manager = input_manager
        
    def show_tooltip(self, text):
        """Show a tooltip with the given text (only if activated)"""
        if not text:
            return
            
        try:
            from ui.components.simple_tooltip import Tooltip
            # Create tooltip component
            screen_size = (runtime_globals.SCREEN_WIDTH, runtime_globals.SCREEN_HEIGHT)
            self.active_tooltip = Tooltip(text, screen_size[0], screen_size[1])
            self.active_tooltip.set_manager(self)  # Use set_manager to trigger scaling
            self.menu_blockers_input = True
            # Play activation sound if available
            runtime_globals.game_sound.play("menu")
        except ImportError as e:
            if DEBUG_SCALE:
                runtime_globals.game_console.log(f"[UIManager] Error importing Tooltip: {e}")
            self.active_tooltip = None
            self.menu_blockers_input = False
        
    def hide_tooltip(self):
        """Hide the current tooltip"""
        if self.active_tooltip:
            runtime_globals.game_sound.play("cancel")
        self.active_tooltip = None
    
    def set_active_menu(self, menu):
        """Set the active menu (modal component)"""
        self.active_menu = menu
        if menu:
            menu.manager = self
            # Set up menu rect scaling if not already done
            if not menu.base_rect:
                menu.base_rect = menu.rect.copy()
            menu.rect = self.scale_rect(menu.base_rect)
    
    def set_active_stats_panel(self, stats_panel):
        """Set the active stats panel (modal component)"""
        self.active_stats_panel = stats_panel
        if stats_panel:
            # Make sure it's in the components list for rendering
            if stats_panel not in self.components:
                self.add_component(stats_panel)
        
    def update(self):
        """Update all components (animations, etc)"""
        # Update color animation
        self.update_color_animation()
        
        # Update tooltip animation
        if self.active_tooltip:
            self.active_tooltip.update()
        
        # Track if any STATIC components need redraw (dynamic components don't affect master cache)
        static_needs_redraw = False
        dirty_components = None
        for component in self.components:
            component.update()
            # Only mark master surface dirty if a static component needs redraw
            # Dynamic components render separately and don't affect the cached master surface
            if not component.is_dynamic and (component.needs_redraw or component.cached_surface is None):
                static_needs_redraw = True
                if dirty_components is None:
                    dirty_components = []
                dirty_components.append(component)

        # Log once per second to avoid spam; the name strings are only built
        # when a log is actually due.
        if static_needs_redraw and hasattr(self, '_last_redraw_log'):
            current_time = time.time()
            if current_time - self._last_redraw_log >= 1.0:
                names = set(
                    f"{c.__class__.__name__}({'needs_redraw' if c.needs_redraw else 'cached_surface_None'})"
                    for c in dirty_components
                )
                runtime_globals.game_console.log(f"[UIManager] Static components needing redraw: {', '.join(names)}")
                self._last_redraw_log = current_time
        elif static_needs_redraw:
            self._last_redraw_log = time.time()
        
        # Only invalidate master cache if static components changed
        if static_needs_redraw:
            self.master_ui_dirty = True
            
    def draw(self, surface):
        """Draw all components using master UI cache for static elements and direct rendering for dynamic elements"""
        # Rebuild master UI surface only if static components changed
        if self.master_ui_dirty or self.master_ui_surface is None:
            self._rebuild_master_ui_surface()
            self.master_ui_dirty = False
        
        # Single blit of entire static UI from cached master surface
        if self.master_ui_surface:
            blit_with_cache(surface, self.master_ui_surface, (self.ui_offset_x, self.ui_offset_y))
        
        # Draw dynamic components separately (not cached in master surface)
        for component in self.components:
            if component.visible and component.is_dynamic:
                component.draw(surface, ui_local=False)
            
        # Draw external border ONLY if screen is bigger than UI (UI doesn't fill screen)
        # Example: 300x300 screen with 240x240 UI = show border
        # Example: 480x480 screen with 480x480 UI = no border
        # Can be disabled with show_external_border = False
        screen_width, screen_height = self.screen_size
        if self.show_external_border and (self.ui_width < screen_width or self.ui_height < screen_height):
            colors = self.get_theme_colors()
            border_color = colors["fg"]  # Use main theme color
            border_size = 2  # Small 2-pixel border

            # Draw border around the entire UI area (external to the UI)
            ui_rect = pygame.Rect(self.ui_offset_x - border_size, self.ui_offset_y - border_size,
                                self.ui_width + 2 * border_size, self.ui_height + 2 * border_size)
            pygame.draw.rect(surface, border_color, ui_rect, width=border_size)
            
        # Draw modal components on top (menu first, then tooltip on top of everything)
        if self.active_menu and self.active_menu.visible:
            menu_surface = self.active_menu.render()
            blit_with_cache(surface, menu_surface, (self.active_menu.rect.x, self.active_menu.rect.y))
        
        # Draw tooltip at scaled position (on top of everything including menu)
        if self.active_tooltip:
            self.active_tooltip.draw(surface)
    
    def _rebuild_master_ui_surface(self):
        """Rebuild the master UI surface by rendering all static components to it."""
        # Create master surface if needed
        if self.master_ui_surface is None:
            self.master_ui_surface = pygame.Surface((self.ui_width, self.ui_height), pygame.SRCALPHA)
        
        # Clear the master surface
        self.master_ui_surface.fill((0, 0, 0, 0))
        
        # Draw only static (non-dynamic) visible components to the master surface
        # Dynamic components will be drawn separately on top
        for component in self.components:
            if component.visible and not component.is_dynamic:
                component.draw(self.master_ui_surface, ui_local=True)
            elif not component.is_dynamic:
                # For invisible static components, clear flags and ensure cached_surface exists
                # This prevents redraw loops when components toggle visibility
                if component.needs_redraw or component.cached_surface is None:
                    component.cached_surface = component.render()
                    component.needs_redraw = False
        
        # Draw border on master surface ONLY if screen is bigger than UI
        # This is the internal border (on the UI surface itself)
        screen_width, screen_height = self.screen_size
        if self.ui_width < screen_width or self.ui_height < screen_height:
            colors = self.get_theme_colors()
            if self.theme != "PURPLE":
                if "border" in colors:
                    border_color = colors["border"]
                    border_size = 2
                    border_rect = pygame.Rect(0, 0, self.ui_width, self.ui_height)
                    pygame.draw.rect(self.master_ui_surface, border_color, border_rect, width=border_size)
            else:
                # For PURPLE theme (default), draw purple border
                if "fg" in colors:
                    border_color = colors["fg"]
                    border_size = 2
                    border_rect = pygame.Rect(0, 0, self.ui_width, self.ui_height)
                    pygame.draw.rect(self.master_ui_surface, border_color, border_rect, width=border_size)
        
        # Mark as clean
        self.master_ui_dirty = False
    
    def set_focused_component(self, component):
        """Set focus to a specific component"""
        if component not in self.focusable_components:
            runtime_globals.game_console.log(f"[UIManager] Cannot focus component not in focusable list")
            return False
            
        component_index = self.focusable_components.index(component)
        
        # Clear focus from current component
        if self.focused_index >= 0:
            old_component = self.focusable_components[self.focused_index]
            old_component.focused = False
            old_component.needs_redraw = True
            old_component.cached_surface = None  # Force regeneration
            if hasattr(old_component, 'on_focus_lost'):
                old_component.on_focus_lost()
        
        # Set focus to new component
        self.focused_index = component_index
        component.focused = True
        component.needs_redraw = True
        component.cached_surface = None  # Force regeneration
        if hasattr(component, 'on_focus_gained'):
            component.on_focus_gained()
            
        # Update highlight
        target_rect = component.rect
        if hasattr(component, 'get_focused_sub_rect'):
            sub_rect = component.get_focused_sub_rect()
            target_rect = sub_rect
            
        # Individual component highlighting - no global highlight system
        component.needs_redraw = True
        return True
        
    def load_sprite_integer_scaling(self, prefix, name, suffix=None):
        """
        Load a sprite that uses integer scaling for UI elements.
        
        Uses pattern: assets/ui/{prefix}_{name}[_{suffix}]_{scale_factor}.png
        Where scale_factor comes from the current sprite scale.
        
        Special handling for 3x UI scale: loads 2x sprite and resizes to 3x.
        
        Args:
            prefix (str): Sprite category (e.g., "Status", "Training", "Battle")
            name (str): Sprite name (e.g., "Heart", "Empty", "Energy")
            suffix (str, optional): Additional suffix (e.g., "Highlight", "Selected")
            
        Returns:
            pygame.Surface: Loaded sprite surface, or None if file not found
        """
        # NEW SYSTEM: Always load _1 sprites and scale them
        sprite_scale = 1  # Always load _1 suffix
        
        # Build filename based on pattern
        if suffix:
            filename = f"{prefix}_{name}_{suffix}_{sprite_scale}.png"
        else:
            filename = f"{prefix}_{name}_{sprite_scale}.png"
            
        filepath = f"assets/ui/{filename}"

        cache_key = (filepath, self.ui_scale)
        cached = _integer_sprite_cache.get(cache_key)
        if cached is not None:
            return cached

        if DEBUG_SCALE:
            runtime_globals.game_console.log(f"[UIManager] Loading _1 sprite: {filepath} (will scale by ui_scale: {self.ui_scale})")

        try:
            sprite = image_load(filepath)

            # Apply integer scaling to match UI scale
            if self.ui_scale > 1:
                original_size = sprite.get_size()
                new_size = (original_size[0] * self.ui_scale, original_size[1] * self.ui_scale)
                sprite = pygame.transform.scale(sprite, new_size)
                if DEBUG_SCALE:
                    runtime_globals.game_console.log(f"[UIManager] Scaled _1 sprite from {original_size} to {new_size} for {self.ui_scale}x UI scale")

            if DEBUG_SCALE:
                runtime_globals.game_console.log(f"[UIManager] Successfully loaded sprite: {filepath}")
            _integer_sprite_cache[cache_key] = sprite
            return sprite
        except pygame.error as e:
            if DEBUG_SCALE:
                runtime_globals.game_console.log(f"[UIManager] Failed to load sprite {filepath}: {e}")
            return None
    
    def load_sprite_non_integer_scaling(self, base_path, scale_factor=None):
        """
        Load a sprite that uses non-integer scaling for pets, flags, and other elements.
        
        Loads the base sprite and scales it by the provided scale factor or current UI scale.
        Used for sprites that don't have pre-scaled versions on disk.
        
        Args:
            base_path (str): Path to the base sprite file (e.g., "assets/pets/agumon.png")
            scale_factor (float, optional): Custom scale factor. If None, uses current UI scale
            
        Returns:
            pygame.Surface: Scaled sprite surface, or None if file not found
        """
        if scale_factor is None:
            scale_factor = self.ui_scale
            
        if DEBUG_SCALE:
            runtime_globals.game_console.log(f"[UIManager] Loading non-integer scaled sprite: {base_path} with scale {scale_factor}")
        
        try:
            # Load base sprite
            base_sprite = image_load(base_path)
            
            # If scale is 1.0, return original
            if scale_factor == 1.0:
                if DEBUG_SCALE:
                    runtime_globals.game_console.log(f"[UIManager] Returning original sprite (scale 1.0): {base_path}")
                return base_sprite
            
            # Scale the sprite
            original_size = base_sprite.get_size()
            new_size = (int(original_size[0] * scale_factor), int(original_size[1] * scale_factor))
            scaled_sprite = pygame.transform.scale(base_sprite, new_size)
            
            if DEBUG_SCALE:
                runtime_globals.game_console.log(f"[UIManager] Successfully scaled sprite from {original_size} to {new_size}: {base_path}")
            return scaled_sprite
            
        except pygame.error as e:
            if DEBUG_SCALE:
                runtime_globals.game_console.log(f"[UIManager] Failed to load sprite {base_path}: {e}")
            return None
    
    # ========================================
    # Centralized Shape Drawing Methods
    # ========================================
    
    def draw_rounded_rectangle(self, surface, color, rect, border_color=None, border_width=None, border_radius=None):
        """
        Draw a rounded rectangle with optional border using scaled values.
        
        Args:
            surface: Pygame surface to draw on
            color: Fill color (RGB tuple)
            rect: Rectangle (x, y, width, height) in base coordinates
            border_color: Border color (RGB tuple), optional
            border_width: Border width in base pixels, optional (auto-scaled)
            border_radius: Border radius in base pixels, optional (auto-scaled)
        """
        # Scale the rectangle
        scaled_rect = self.scale_rect(pygame.Rect(rect))
        
        # Set defaults if not provided
        if border_radius is None:
            border_radius = self.get_border_size()
        else:
            border_radius = self.scale_value(border_radius)
            
        if border_width is None:
            border_width = self.get_border_size()
        else:
            border_width = self.scale_value(border_width)
        
        if DEBUG_SCALE:
            runtime_globals.game_console.log(f"[UIManager] Drawing rounded rectangle: rect={scaled_rect}, radius={border_radius}, border_width={border_width}")
        
        # Draw border if specified
        if border_color and border_width > 0:
            pygame.draw.rect(surface, border_color, scaled_rect, width=border_width, border_radius=border_radius)
        
        # Draw filled rectangle
        if border_width > 0 and border_color:
            # Inset the fill rectangle by border width
            fill_rect = scaled_rect.inflate(-border_width * 2, -border_width * 2)
            fill_radius = max(0, border_radius - border_width)
        else:
            fill_rect = scaled_rect
            fill_radius = border_radius
            
        pygame.draw.rect(surface, color, fill_rect, border_radius=fill_radius)
    
    def draw_cut_corner_polygon(self, surface, color, rect, border_color=None, border_width=None, cut_corners=None, cut_size=None):
        """
        Draw a polygon with cut corners (like buttons) using scaled values.
        
        Args:
            surface: Pygame surface to draw on
            color: Fill color (RGB tuple)
            rect: Rectangle (x, y, width, height) in base coordinates
            border_color: Border color (RGB tuple), optional
            border_width: Border width in base pixels, optional (auto-scaled)
            cut_corners: Dict with keys 'tl', 'tr', 'bl', 'br' indicating which corners to cut
            cut_size: Cut size in base pixels, optional (auto-scaled)
        """
        # Scale the rectangle
        scaled_rect = self.scale_rect(pygame.Rect(rect))
        
        # Set defaults
        if cut_corners is None:
            cut_corners = {'tl': False, 'tr': False, 'bl': False, 'br': False}
        if cut_size is None:
            cut_size = self.scale_value(8)  # 8px base cut size
        else:
            cut_size = self.scale_value(cut_size)
        if border_width is None:
            border_width = self.get_border_size()
        else:
            border_width = self.scale_value(border_width)
        
        x, y, w, h = scaled_rect.x, scaled_rect.y, scaled_rect.width, scaled_rect.height
        
        if DEBUG_SCALE:
            runtime_globals.game_console.log(f"[UIManager] Drawing cut corner polygon: rect={scaled_rect}, cut_size={cut_size}, corners={cut_corners}")
        
        # Build polygon points for border
        border_points = []
        
        # Top-left corner
        if cut_corners.get('tl'):
            border_points.extend([(x + cut_size, y), (x, y + cut_size)])
        else:
            border_points.append((x, y))
        
        # Bottom-left corner
        if cut_corners.get('bl'):
            border_points.extend([(x, y + h - cut_size), (x + cut_size, y + h)])
        else:
            border_points.append((x, y + h))
        
        # Bottom-right corner
        if cut_corners.get('br'):
            border_points.extend([(x + w - cut_size, y + h), (x + w, y + h - cut_size)])
        else:
            border_points.append((x + w, y + h))
        
        # Top-right corner
        if cut_corners.get('tr'):
            border_points.extend([(x + w, y + cut_size), (x + w - cut_size, y)])
        else:
            border_points.append((x + w, y))
        
        # Draw border polygon if specified
        if border_color and border_width > 0 and len(border_points) >= 3:
            pygame.draw.polygon(surface, border_color, border_points)
        
        # Build inset points for fill
        if border_width > 0 and border_color:
            inset = border_width
            fill_points = []
            
            # Top-left corner
            if cut_corners.get('tl'):
                fill_points.extend([(x + cut_size, y + inset), (x + inset, y + cut_size)])
            else:
                fill_points.append((x + inset, y + inset))
            
            # Bottom-left corner
            if cut_corners.get('bl'):
                fill_points.extend([(x + inset, y + h - cut_size - inset), (x + cut_size, y + h - inset)])
            else:
                fill_points.append((x + inset, y + h - inset))
            
            # Bottom-right corner
            if cut_corners.get('br'):
                fill_points.extend([(x + w - cut_size - inset, y + h - inset), (x + w - inset, y + h - cut_size - inset)])
            else:
                fill_points.append((x + w - inset, y + h - inset))
            
            # Top-right corner
            if cut_corners.get('tr'):
                fill_points.extend([(x + w - inset, y + cut_size), (x + w - cut_size - inset, y + inset)])
            else:
                fill_points.append((x + w - inset, y + inset))
            
            if len(fill_points) >= 3:
                pygame.draw.polygon(surface, color, fill_points)
        else:
            # No border, just draw the main polygon
            if len(border_points) >= 3:
                pygame.draw.polygon(surface, color, border_points)
    
    def draw_hexagon(self, surface, color, center, radius, border_color=None, border_width=None):
        """
        Draw a hexagon using scaled values.
        
        Args:
            surface: Pygame surface to draw on
            color: Fill color (RGB tuple)
            center: Center point (x, y) in base coordinates
            radius: Hexagon radius in base pixels (auto-scaled)
            border_color: Border color (RGB tuple), optional
            border_width: Border width in base pixels, optional (auto-scaled)
        """
        # Scale center and radius
        scaled_center = self.scale_position(center[0], center[1])
        scaled_radius = self.scale_value(radius)
        
        if border_width is None:
            border_width = self.get_border_size()
        else:
            border_width = self.scale_value(border_width)
        
        if DEBUG_SCALE:
            runtime_globals.game_console.log(f"[UIManager] Drawing hexagon: center={scaled_center}, radius={scaled_radius}, border_width={border_width}")
        
        # Calculate hexagon points
        points = []
        for i in range(6):
            angle = (math.pi / 3 * i) + (math.pi / 6)  # 60 degrees * i + 30 degrees rotation
            x = scaled_center[0] + scaled_radius * math.cos(angle)
            y = scaled_center[1] + scaled_radius * math.sin(angle)
            points.append((int(x), int(y)))
        
        # Draw filled hexagon
        if len(points) >= 3:
            pygame.draw.polygon(surface, color, points)
        
        # Draw border if specified
        if border_color and border_width > 0 and len(points) >= 3:
            pygame.draw.polygon(surface, border_color, points, border_width)
    
    def draw_hexagon_highlight(self, surface, color, center, radius, border_width=None):
        """
        Draw a hexagon highlight (outline only) using scaled values.
        
        Args:
            surface: Pygame surface to draw on
            color: Outline color (RGB tuple)
            center: Center point (x, y) in base coordinates
            radius: Hexagon radius in base pixels (auto-scaled)
            border_width: Border width in base pixels, optional (auto-scaled)
        """
        # Scale center and radius
        scaled_center = self.scale_position(center[0], center[1])
        scaled_radius = self.scale_value(radius)
        
        if border_width is None:
            border_width = self.get_border_size()
        else:
            border_width = self.scale_value(border_width)
        
        if DEBUG_SCALE:
            runtime_globals.game_console.log(f"[UIManager] Drawing hexagon highlight: center={scaled_center}, radius={scaled_radius}, border_width={border_width}")
        
        # Calculate hexagon points
        points = []
        for i in range(6):
            angle = (math.pi / 3 * i) + (math.pi / 6)  # 60 degrees * i + 30 degrees rotation
            x = scaled_center[0] + scaled_radius * math.cos(angle)
            y = scaled_center[1] + scaled_radius * math.sin(angle)
            points.append((int(x), int(y)))
        
        # Draw outline only
        if len(points) >= 3:
            pygame.draw.polygon(surface, color, points, border_width)
    
    def draw_arrow_polygon(self, surface, color, rect, direction="right", border_color=None, border_width=None):
        """
        Draw an arrow polygon using scaled values.
        
        Args:
            surface: Pygame surface to draw on
            color: Fill color (RGB tuple)
            rect: Rectangle (x, y, width, height) in base coordinates defining arrow bounds
            direction: Arrow direction ("up", "down", "left", "right")
            border_color: Border color (RGB tuple), optional
            border_width: Border width in base pixels, optional (auto-scaled)
        """
        # Scale the rectangle
        scaled_rect = self.scale_rect(pygame.Rect(rect))
        
        if border_width is None:
            border_width = self.get_border_size()
        else:
            border_width = self.scale_value(border_width)
        
        x, y, w, h = scaled_rect.x, scaled_rect.y, scaled_rect.width, scaled_rect.height
        
        if DEBUG_SCALE:
            runtime_globals.game_console.log(f"[UIManager] Drawing arrow polygon: rect={scaled_rect}, direction={direction}")
        
        # Calculate arrow points based on direction
        if direction == "right":
            points = [(x, y), (x + w * 0.7, y), (x + w, y + h // 2), (x + w * 0.7, y + h), (x, y + h)]
        elif direction == "left":
            points = [(x + w, y), (x + w * 0.3, y), (x, y + h // 2), (x + w * 0.3, y + h), (x + w, y + h)]
        elif direction == "up":
            points = [(x, y + h), (x, y + h * 0.3), (x + w // 2, y), (x + w, y + h * 0.3), (x + w, y + h)]
        elif direction == "down":
            points = [(x, y), (x, y + h * 0.7), (x + w // 2, y + h), (x + w, y + h * 0.7), (x + w, y)]
        else:
            # Default to right arrow
            points = [(x, y), (x + w * 0.7, y), (x + w, y + h // 2), (x + w * 0.7, y + h), (x, y + h)]
        
        # Draw filled arrow
        if len(points) >= 3:
            pygame.draw.polygon(surface, color, points)
        
        # Draw border if specified
        if border_color and border_width > 0 and len(points) >= 3:
            pygame.draw.polygon(surface, border_color, points, border_width)
    
    def draw_simple_rectangle(self, surface, color, rect, border_color=None, border_width=None):
        """
        Draw a simple rectangle (no rounded corners) using scaled values.
        
        Args:
            surface: Pygame surface to draw on
            color: Fill color (RGB tuple)
            rect: Rectangle (x, y, width, height) in base coordinates
            border_color: Border color (RGB tuple), optional
            border_width: Border width in base pixels, optional (auto-scaled)
        """
        # Scale the rectangle
        scaled_rect = self.scale_rect(pygame.Rect(rect))
        
        if border_width is None:
            border_width = self.get_border_size()
        else:
            border_width = self.scale_value(border_width)
        
        if DEBUG_SCALE:
            runtime_globals.game_console.log(f"[UIManager] Drawing simple rectangle: rect={scaled_rect}, border_width={border_width}")
        
        # Draw border if specified
        if border_color and border_width > 0:
            pygame.draw.rect(surface, border_color, scaled_rect, width=border_width)
        
        # Draw filled rectangle
        if border_width > 0 and border_color:
            # Inset the fill rectangle by border width
            fill_rect = scaled_rect.inflate(-border_width * 2, -border_width * 2)
        else:
            fill_rect = scaled_rect
            
        pygame.draw.rect(surface, color, fill_rect)
