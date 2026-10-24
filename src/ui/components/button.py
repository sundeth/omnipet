"""
Button Component - Clickable button with text and optional icon
"""
import pygame
from ui.components.component import UIComponent
from core import runtime_globals
from utils.pygame_utils import blit_with_shadow, blit_with_cache
from utils.asset_utils import image_load


class Button(UIComponent):
    def __init__(self, x, y, width, height, text, callback=None, icon_name=None, icon_prefix="Sleep", cut_corners=None, decorators=None, enabled=True, shadow_mode="disabled", draw_background=True):
        super().__init__(x, y, width, height)
        self.text = text
        self.focusable = True
        self.enabled = enabled  # New enabled property
        self.on_click_callback = callback
        self.icon_name = icon_name
        self.icon_prefix = icon_prefix
        self.icon_sprite = None
        # cut_corners: dict with keys 'tl', 'tr', 'bl', 'br' (True/False)
        self.cut_corners = cut_corners or {'tl': False, 'tr': False, 'bl': False, 'br': False}
        # decorators: list of decorator names (e.g., ["Dummy", "Xai_4"])
        self.decorators = decorators or []
        self.decorator_sprites = {}  # Cache for loaded decorator sprites
        # Visual feedback timing
        self.click_hold_frames = 8  # Number of frames to hold clicked state
        self.click_frame_counter = 0
        self.was_activated = False
        
        # Set shadow mode for this button
        self.shadow_mode = shadow_mode
        
        # Whether to draw the button's background rectangle
        self.draw_background = draw_background
        
    def on_manager_set(self):
        """Called when UI manager is set - load icon and decorators if specified"""
        if self.icon_name and self.manager:
            # NEW SYSTEM: Always load _1 sprites and scale them
            icon_path = f"assets/ui/{self.icon_prefix}_{self.icon_name}_1.png"
            self.icon_sprite = image_load(icon_path).convert_alpha()
            
            # Apply integer scaling if UI scale > 1
            if self.manager.ui_scale > 1:
                original_size = self.icon_sprite.get_size()
                new_size = (original_size[0] * self.manager.ui_scale, original_size[1] * self.manager.ui_scale)
                self.icon_sprite = pygame.transform.scale(self.icon_sprite, new_size)
            
        # Load decorator sprites
        if self.decorators and self.manager:
            # NEW SYSTEM: Always load _1 sprites and scale them
            runtime_globals.game_console.log(f"[Button] Loading decorators for {self.decorators} (using _1 sprites, scaling by {self.manager.ui_scale}x)")
            for decorator in self.decorators:
                try:
                    # Determine prefix based on decorator type
                    if decorator.startswith("Selection_"):
                        prefix = ""  # Selection_ decorators don't need additional prefix
                        decorator_path = decorator
                    elif decorator.startswith("Battle_"):
                        prefix = ""  # Battle_ decorators don't need additional prefix
                        decorator_path = decorator
                    elif decorator.startswith("Settings_"):
                        prefix = ""  # Settings_ decorators don't need additional prefix
                        decorator_path = decorator
                    elif decorator.startswith("Connect_"):
                        prefix = ""  # Connect_ decorators don't need additional prefix
                        decorator_path = decorator
                    elif decorator.startswith("Freezer_"):
                        prefix = ""  # Freezer_ decorators don't need additional prefix
                        decorator_path = decorator
                    elif decorator.startswith("Library_"):
                        prefix = ""  # Library_ decorators don't need additional prefix
                        decorator_path = decorator
                    elif decorator.startswith("Shop_"):
                        prefix = ""  # Shop_ decorators don't need additional prefix
                        decorator_path = decorator
                    else:
                        prefix = "Training_"  # Traditional training decorators
                        decorator_path = decorator
                    
                    # Load standard decorator sprite (_1 version)
                    standard_path = f"assets/ui/{prefix}{decorator_path}_1.png"
                    standard_sprite = image_load(standard_path).convert_alpha()
                    
                    # Apply integer scaling if needed
                    if self.manager.ui_scale > 1:
                        original_size = standard_sprite.get_size()
                        new_size = (original_size[0] * self.manager.ui_scale, original_size[1] * self.manager.ui_scale)
                        standard_sprite = pygame.transform.scale(standard_sprite, new_size)
                    
                    # Try to load highlight decorator sprite, fall back to standard if not found
                    highlight_sprite = standard_sprite  # Default fallback
                    try:
                        highlight_path = f"assets/ui/{prefix}{decorator_path}_Highlight_1.png"
                        highlight_sprite = image_load(highlight_path).convert_alpha()
                        
                        # Apply integer scaling if needed
                        if self.manager.ui_scale > 1:
                            original_size = highlight_sprite.get_size()
                            new_size = (original_size[0] * self.manager.ui_scale, original_size[1] * self.manager.ui_scale)
                            highlight_sprite = pygame.transform.scale(highlight_sprite, new_size)
                        
                        runtime_globals.game_console.log(f"[Button] Loaded highlight decorator: {highlight_path}")
                    except (pygame.error, FileNotFoundError):
                        # No highlight version available, use standard for both
                        runtime_globals.game_console.log(f"[Button] No highlight version for {decorator}, using standard")
                        pass
                    
                    self.decorator_sprites[decorator] = {
                        'standard': standard_sprite,
                        'highlight': highlight_sprite
                    }
                    
                    runtime_globals.game_console.log(f"[Button] Loaded decorator {decorator}: standard={standard_sprite.get_size()}, highlight={highlight_sprite.get_size()}")
                    
                except pygame.error as e:
                    runtime_globals.game_console.log(f"[Button] Could not load decorator {decorator} (sprites may not exist yet): {e}")
                    # Continue without this decorator instead of crashing
    
    def set_decorators(self, decorators):
        """Update the decorators for this button and reload sprites"""
        self.decorators = decorators
        self.decorator_sprites = {}
        if self.manager:
            self.on_manager_set()  # Reload decorator sprites
            self.needs_redraw = True
    
    def set_text(self, text):
        """Update button text and trigger redraw"""
        if self.text != text:
            self.text = text
            self.needs_redraw = True
            
    def get_colors(self):
        """Get colors for button based on current state, including disabled state"""
        if not self.enabled:
            # Disabled state: muted colors
            if not self.manager:
                return {"bg": (64, 64, 64), "fg": (128, 128, 128), "line": (96, 96, 96)}
            
            theme_colors = self.manager.get_theme_colors()
            # Use muted versions of the theme colors
            return {
                "bg": tuple(c // 3 for c in theme_colors["bg"]),  # Much darker background
                "fg": tuple(c // 2 for c in theme_colors["fg"]),  # Darker foreground  
                "line": tuple(c // 2 for c in theme_colors["fg"])  # Darker line
            }
        else:
            # Use normal color logic from base class
            return super().get_colors()
    
    def set_enabled(self, enabled):
        """Enable or disable the button"""
        if self.enabled != enabled:
            self.enabled = enabled
            self.focusable = enabled  # Disabled buttons are not focusable
            self.needs_redraw = True
    
    def get_highlight_shape(self):
        """Return custom highlight shape for buttons with cut corners"""
        # Check if we need cut corners
        has_cuts = any(self.cut_corners.values())
        
        if not has_cuts:
            # Use default rectangular highlight
            return None
            
        # Calculate cut corner polygon points for highlight that exactly match the button's border polygon
        # The button renders its border polygon using these exact calculations, so we need to match them
        
        # Get the button's dimensions and border calculations (same as render method)
        w, h = self.rect.width, self.rect.height
        border_size = self.manager.get_border_size() if self.manager else 2
        cut = int(12 * self.manager.ui_scale) if self.manager else 12
        
        # The button's border polygon uses border_inset = border_size from the edges
        # We want the highlight to be slightly outside this border polygon
        highlight_outset = border_size // 2  # Expand outward by half border size
        
        # Calculate the button's actual border polygon points (in button surface coordinates)
        border_inset = border_size
        button_border_points = []
        
        # Top-left corner (same logic as button's render method)
        if self.cut_corners.get('tl'):
            button_border_points.extend([(cut, border_inset), (border_inset, cut)])
        else:
            button_border_points.append((border_inset, border_inset))
        
        # Bottom-left corner  
        if self.cut_corners.get('bl'):
            button_border_points.extend([(border_inset, h - cut - border_inset), (cut, h - border_inset)])
        else:
            button_border_points.append((border_inset, h - border_inset))
        
        # Bottom-right corner
        if self.cut_corners.get('br'):
            button_border_points.extend([(w - cut - border_inset, h - border_inset), (w - border_inset, h - cut - border_inset)])
        else:
            button_border_points.append((w - border_inset, h - border_inset))
        
        # Top-right corner
        if self.cut_corners.get('tr'):
            button_border_points.extend([(w - border_inset, cut), (w - cut - border_inset, border_inset)])
        else:
            button_border_points.append((w - border_inset, border_inset))
        
        # Convert button surface coordinates to screen coordinates and expand outward
        screen_points = []
        for point in button_border_points:
            # Convert from button surface coords to screen coords
            screen_x = self.rect.x + point[0]
            screen_y = self.rect.y + point[1]
            
            # Expand outward from button center
            button_center_x = self.rect.x + w // 2
            button_center_y = self.rect.y + h // 2
            
            # Calculate direction from center to point
            dx = screen_x - button_center_x
            dy = screen_y - button_center_y
            
            # Normalize and expand
            if dx != 0 or dy != 0:
                length = (dx*dx + dy*dy) ** 0.5
                if length > 0:
                    dx_norm = dx / length
                    dy_norm = dy / length
                    screen_x += dx_norm * highlight_outset
                    screen_y += dy_norm * highlight_outset
            
            screen_points.append((screen_x, screen_y))
        
        return screen_points
    
    def update(self):
        """Update button state, including visual click feedback"""
        # Handle mouse hover detection if input manager is available
        self.handle_mouse_hover()
        
        # Handle visual click feedback timing (custom behavior instead of base class)
        if self.was_activated and self.click_frame_counter > 0:
            self.click_frame_counter -= 1
            if self.click_frame_counter <= 0:
                self.was_activated = False
                self.clicked = False
                self.needs_redraw = True
        else:
            # Only reset click state from base class behavior if we're not in custom animation
            if self.clicked and not self.was_activated and pygame.time.get_ticks() - self.click_time > 200:
                self.clicked = False
                self.needs_redraw = True
        
    def render(self):
        # Reuse a cached render surface to avoid per-frame allocations
        target_size = (self.rect.width, self.rect.height)
        if not hasattr(self, "_render_surface") or self._render_surface is None or self._render_surface.get_size() != target_size:
            self._render_surface = pygame.Surface(target_size, pygame.SRCALPHA)
        surface = self._render_surface
        surface.fill((0, 0, 0, 0))
        
        # Get colors using the centralized color system
        colors = self.get_colors()
        bg_color = colors["bg"]
        fg_color = colors["fg"]
        line_color = colors["line"]
        
        # Only draw background if draw_background is True
        if self.draw_background:
            # Check if we need cut corners
            has_cuts = any(self.cut_corners.values())
            
            if has_cuts:
                # Use centralized cut corner polygon method
                # We need to convert to base coordinates for the method
                button_rect = (0, 0, self.rect.width // self.manager.ui_scale, self.rect.height // self.manager.ui_scale)
                cut_size = 12  # Base cut size
                
                # For the button surface, we need to draw at already-scaled coordinates
                # So we bypass the centralized method and draw directly
                cut = int(12 * self.manager.ui_scale)  # Diagonal cut size
                w, h = self.rect.width, self.rect.height
                border_size = self.manager.get_border_size()
                
                # Calculate border polygon points
                border_inset = border_size
                border_points = []
                
                # Top-left corner
                if self.cut_corners.get('tl'):
                    border_points.extend([(cut, border_inset), (border_inset, cut)])
                else:
                    border_points.append((border_inset, border_inset))
                
                # Bottom-left corner  
                if self.cut_corners.get('bl'):
                    border_points.extend([(border_inset, h - cut - border_inset), (cut, h - border_inset)])
                else:
                    border_points.append((border_inset, h - border_inset))
                
                # Bottom-right corner
                if self.cut_corners.get('br'):
                    border_points.extend([(w - cut - border_inset, h - border_inset), (w - border_inset, h - cut - border_inset)])
                else:
                    border_points.append((w - border_inset, h - border_inset))
                
                # Top-right corner
                if self.cut_corners.get('tr'):
                    border_points.extend([(w - border_inset, cut), (w - cut - border_inset, border_inset)])
                else:
                    border_points.append((w - border_inset, border_inset))
                
                # Calculate background polygon points (further inset)
                bg_inset = border_size * 2
                bg_points = []
                
                # Top-left corner
                if self.cut_corners.get('tl'):
                    bg_points.extend([(cut, bg_inset), (bg_inset, cut)])
                else:
                    bg_points.append((bg_inset, bg_inset))
                
                # Bottom-left corner
                if self.cut_corners.get('bl'):
                    bg_points.extend([(bg_inset, h - cut - bg_inset), (cut, h - bg_inset)])
                else:
                    bg_points.append((bg_inset, h - bg_inset))
                
                # Bottom-right corner
                if self.cut_corners.get('br'):
                    bg_points.extend([(w - cut - bg_inset, h - bg_inset), (w - bg_inset, h - cut - bg_inset)])
                else:
                    bg_points.append((w - bg_inset, h - bg_inset))
                
                # Top-right corner
                if self.cut_corners.get('tr'):
                    bg_points.extend([(w - bg_inset, cut), (w - cut - bg_inset, bg_inset)])
                else:
                    bg_points.append((w - bg_inset, bg_inset))
                
                # Draw border polygon (filled, not outline)
                if len(border_points) >= 3:
                    pygame.draw.polygon(surface, line_color, border_points)
                    
                # Draw background polygon on top
                if len(bg_points) >= 3:
                    pygame.draw.polygon(surface, bg_color, bg_points)
                    
            else:
                # Use centralized rounded rectangle method
                # Convert to base coordinates
                button_rect = (0, 0, self.rect.width // self.manager.ui_scale, self.rect.height // self.manager.ui_scale)
                
                # For button surface, we need to draw at screen coordinates, so draw directly
                border_size = self.manager.get_border_size()
                
                # Draw border first (full size)
                if border_size > 0:
                    pygame.draw.rect(
                        surface, 
                        line_color, 
                        (0, 0, self.rect.width, self.rect.height), 
                        width=border_size,
                        border_radius=border_size
                    )
                
                # Draw background (inset by border)
                border_offset = border_size // 2
                inner_rect = (border_offset, border_offset, 
                             self.rect.width - border_size, self.rect.height - border_size)
                pygame.draw.rect(
                    surface, 
                    bg_color, 
                    inner_rect,
                    border_radius=max(0, border_size - border_offset)
                )
        
        # Draw content (icon + text)
        font = self.get_font("text")
        
        # Prepare text surfaces (if any)
        lines = []
        line_surfaces = []
        line_spacing = int(8 * self.manager.ui_scale)
        total_height = 0
        max_line_width = 0

        if self.text:
            lines = self.text.split("\n")
            line_surfaces = [font.render(line, True, fg_color) for line in lines]
            total_height = sum(s.get_height() for s in line_surfaces) + line_spacing * (len(line_surfaces) - 1)
            max_line_width = max((s.get_width() for s in line_surfaces), default=0)

        icon_w = icon_h = 0
        if self.icon_sprite:
            icon_w, icon_h = self.icon_sprite.get_size()

        # Get border inset for available area
        border_size = self.manager.get_border_size() if self.manager else 0
        padding = int(8 * (self.manager.ui_scale if self.manager else 1))

        # Decide layout: if we have text and enough vertical room, put icon above text;
        # otherwise, try to put icon to the left if width allows. If no text, center icon.
        layout = 'none'
        inner_height = self.rect.height - (border_size * 2)
        inner_width = self.rect.width - (border_size * 2)

        if self.icon_sprite and self.text:
            combined_height = icon_h + padding + total_height
            if combined_height <= inner_height:
                layout = 'above'
            else:
                # try left layout if width allows
                combined_width = icon_w + padding + max_line_width
                if combined_width <= inner_width:
                    layout = 'left'
                else:
                    # fallback to above (may overlap slightly)
                    layout = 'above'
        elif self.icon_sprite and not self.text:
            layout = 'center'
        elif self.text:
            layout = 'text_only'

        # Render according to chosen layout
        use_shadow = self.manager and self.manager.should_render_shadow(self, "text")
        icon_use_shadow = self.manager and self.manager.should_render_shadow(self, "icon")
        
        if layout == 'above':
            # Icon centered above text
            start_y = (self.rect.height - (icon_h + padding + total_height)) // 2
            if self.icon_sprite:
                icon_x = (self.rect.width - icon_w) // 2
                if icon_use_shadow:
                    blit_with_shadow(surface, self.icon_sprite, (icon_x, start_y))
                else:
                    blit_with_cache(surface, self.icon_sprite, (icon_x, start_y))
            text_y = start_y + icon_h + padding
            for s in line_surfaces:
                text_x = (self.rect.width - s.get_width()) // 2
                if use_shadow:
                    blit_with_shadow(surface, s, (text_x, text_y))
                else:
                    blit_with_cache(surface, s, (text_x, text_y))
                text_y += s.get_height() + line_spacing

        elif layout == 'left':
            # Icon to the left, text centered in remaining area vertically
            icon_x = border_size + padding
            icon_y = (self.rect.height - icon_h) // 2
            if self.icon_sprite:
                if icon_use_shadow:
                    blit_with_shadow(surface, self.icon_sprite, (icon_x, icon_y))
                else:
                    blit_with_cache(surface, self.icon_sprite, (icon_x, icon_y))

            text_area_x = icon_x + icon_w + padding
            text_area_width = self.rect.width - text_area_x - border_size
            text_y = (self.rect.height - total_height) // 2
            for s in line_surfaces:
                text_x = text_area_x + (text_area_width - s.get_width()) // 2
                if use_shadow:
                    blit_with_shadow(surface, s, (text_x, text_y))
                else:
                    blit_with_cache(surface, s, (text_x, text_y))
                text_y += s.get_height() + line_spacing

        elif layout == 'center':
            # Icon only, center it
            icon_x = (self.rect.width - icon_w) // 2
            icon_y = (self.rect.height - icon_h) // 2
            if icon_use_shadow:
                blit_with_shadow(surface, self.icon_sprite, (icon_x, icon_y))
            else:
                blit_with_cache(surface, self.icon_sprite, (icon_x, icon_y))

        elif layout == 'text_only':
            # Only text, center vertically and horizontally
            y = (self.rect.height - total_height) // 2
            for s in line_surfaces:
                text_x = (self.rect.width - s.get_width()) // 2
                if use_shadow:
                    blit_with_shadow(surface, s, (text_x, y))
                else:
                    blit_with_cache(surface, s, (text_x, y))
                y += s.get_height() + line_spacing
        
        # Draw decorators on top of everything
        decorator_use_shadow = self.manager and self.manager.should_render_shadow(self, "decorator")
        for decorator in self.decorators:
            if decorator in self.decorator_sprites:
                use_highlight = self.focus_visible() or self.clicked
                sprite_key = 'highlight' if use_highlight else 'standard'
                decorator_sprite = self.decorator_sprites[decorator][sprite_key]
                
                # NEW SYSTEM: Decorators are already scaled in on_manager_set(), just use them directly
                # No additional scaling needed
                
                # Center decorator if smaller than button surface
                sprite_w, sprite_h = decorator_sprite.get_size()
                surf_w, surf_h = surface.get_size()
                offset_x = max(0, (surf_w - sprite_w) // 2)
                offset_y = max(0, (surf_h - sprite_h) // 2)
                if decorator_use_shadow:
                    blit_with_shadow(surface, decorator_sprite, (offset_x, offset_y))
                else:
                    blit_with_cache(surface, decorator_sprite, (offset_x, offset_y))
        
        # Apply transparency for disabled buttons, reset for enabled
        if not self.enabled:
            # Create a semi-transparent version by setting alpha
            surface.set_alpha(128)  # 50% transparency
        else:
            # Reset to fully opaque for enabled buttons
            surface.set_alpha(255)
        
        return surface
    
    def handle_event(self, event):
        """Handle input events for the button"""
        if not self.enabled:
            return False

        event_type, event_data = event

        if event_type in ["A", "LCLICK"]:
            return self.activate()

        return False
    
    def activate(self):
        """Activate the button (call callback)"""
        if not self.enabled:
            return False
            
        # Set visual feedback state
        self.clicked = True
        self.was_activated = True
        self.click_frame_counter = self.click_hold_frames
        self.click_time = pygame.time.get_ticks()  # Set click time to prevent premature reset
        self.needs_redraw = True
        
        if self.on_click_callback:
            self.on_click_callback()
            return True
        return False
