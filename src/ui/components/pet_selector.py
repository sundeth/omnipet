"""
Pet Selector Component - Displays pets in hexagonal cells arranged horizontally
"""
import pygame
import math
from ui.components.component import UIComponent
from core import runtime_globals
from models.animation import PetFrame
from utils.pygame_utils import blit_with_cache


class PetSelector(UIComponent):
    def __init__(self, x, y, width, height):
        super().__init__(x, y, width, height)
        
        # Pet data
        self.pets = []
        self.enabled_pets = []  # List of pet indices that are enabled
        self._selected_pets = []  # List of pet indices that are selected (internal)
        #: How many may be held at once, or None for no limit.
        #:
        #: **The cap belongs here and not only in the label.** The view that
        #: owns this knew its own `max_pets` and said so in its instructions
        #: -- "Select 1 pet for DCom battle" -- while the selector happily
        #: took as many as were clicked, and the confirm sent all of them. A
        #: DCom or WiFiCom battle is one pet against one toy, and the packets
        #: only ever describe the first.
        self.max_selection = None
        
        # Custom theme overrides for specific pets {pet_index: theme_name}
        self.pet_custom_themes = {}
        
        # Callback for custom activation behavior
        self.activation_callback = None
        
        # Mouse interaction state
        self._clicked_cell = None  # Stores the cell that was clicked (for mouse activation)
        
        # Base visual settings (will be scaled by manager)
        self.base_cell_size = 48  # Base hexagon size
        self.base_cell_padding = 4  # Base space between hexagons
        self.base_border_width = 2  # Base border width
        
        # Scaled visual settings (set in on_manager_set)
        self.cell_size = self.base_cell_size
        self.cell_padding = self.base_cell_padding
        self.border_width = self.base_border_width
        
        # State
        self.hovered_cell = -1
        self.focused_cell = 0  # Start with first pet focused
        self.is_interactive = False  # Can be toggled for different scenes
        self.focusable = True  # Make component focusable for keyboard navigation
        self.focused = False  # Track focus state for highlighting
        self.armor_mode = False  # Special mode for armor evolution visual feedback
        
        # Layout (positions in base coordinates)
        self.cell_positions = []
        
        # Cache
        self.cached_surface = None
        self.needs_layout_update = True
        
        # Setup initial layout
        self.update_layout()
        
    @property
    def selected_pets(self):
        """Get the list of selected pet indices"""
        return self._selected_pets
        
    @selected_pets.setter
    def selected_pets(self, value):
        """Set the list of selected pet indices and invalidate cache"""
        if self._selected_pets != value:
            self._selected_pets = value[:]  # Make a copy to avoid reference issues
            self.needs_redraw = True
        
    def get_activation_cell(self):
        """Get the cell that should be activated (clicked cell for mouse, focused cell for keyboard)"""
        return self._clicked_cell if self._clicked_cell is not None else self.focused_cell
        
    def get_highlight_shape(self):
        """Return custom hexagonal highlight shape for the focused pet - only when component has focus"""
        if (not self.is_interactive or not self.focused or 
            self.focused_cell < 0 or self.focused_cell >= len(self.cell_positions)):
            return None
            
        # Get the focused cell position and radius
        base_center = self.cell_positions[self.focused_cell]
        radius = (self.calculated_cell_size // 2) if hasattr(self, 'calculated_cell_size') else (self.base_cell_size // 2)
        
        # Convert to screen coordinates
        if self.manager:
            screen_center = self.manager.scale_position(base_center[0], base_center[1])
            screen_center = (screen_center[0] + self.rect.x, screen_center[1] + self.rect.y)
            scaled_radius = self.manager.scale_value(radius)
        else:
            screen_center = (base_center[0] + self.rect.x, base_center[1] + self.rect.y)
            scaled_radius = radius
        
        # Calculate hexagon points for highlight (slightly larger than the pet hexagon)
        highlight_radius = scaled_radius + self.manager.scale_value(4) if self.manager else radius + 4
        points = []
        for i in range(6):
            angle = (math.pi / 3 * i) + (math.pi / 6)  # 60 degrees * i + 30 degrees rotation
            x = screen_center[0] + highlight_radius * math.cos(angle)
            y = screen_center[1] + highlight_radius * math.sin(angle)
            points.append((int(x), int(y)))
        
        return points
        
    def set_pets(self, pets):
        """Set the list of pets to display"""
        self.pets = pets[:]
        self.enabled_pets = list(range(len(pets)))  # All enabled by default
        self._selected_pets = []
        self.needs_layout_update = True
        self.needs_redraw = True
        
    def set_enabled_pets(self, enabled_pet_indices):
        """Set which pets are enabled (others will be shown as disabled)"""
        self.enabled_pets = enabled_pet_indices[:]
        self.needs_redraw = True
        
    def set_interactive(self, interactive):
        """Enable/disable interactivity (mouse hover, selection, etc.)"""
        self.is_interactive = interactive
        if not interactive:
            self.hovered_cell = -1
            # Don't reset focused_cell - preserve it for when interactivity is re-enabled
        else:
            # When re-enabling, ensure we have a valid focused cell
            if self.focused_cell < 0 and self.pets:
                self.focused_cell = 0
        self.needs_redraw = True
            
    def update_layout(self):
        """Calculate positions and sizes for all hexagonal cells in base coordinates"""
        if not self.pets:
            self.cell_positions = []
            self.needs_layout_update = False
            return
            
        # Work in base coordinates - the UI manager will handle scaling
        available_width = self.base_rect.width
        available_height = self.base_rect.height
        num_pets = len(self.pets)
        
        #runtime_globals.game_console.log(f"[PetSelector] update_layout: {num_pets} pets, available_width={available_width}, available_height={available_height}")
        
        if num_pets == 0:
            self.cell_positions = []
            self.needs_layout_update = False
            return
            
        # Step 1: Calculate maximum possible hexagon radius based on height
        # Hexagon height = 2 * radius, leave some padding
        max_radius_from_height = (available_height - 4) // 2  # 2px padding top/bottom
        
        # Step 2: Calculate hexagon spacing for touching hexagons
        # For regular pointy-top hexagons touching side by side, the distance between centers is √3 * radius ≈ 1.732 * radius
        # Total width needed = (num_pets - 1) * √3 * radius + 2 * radius
        # Simplified: total_width = radius * ((num_pets - 1) * √3 + 2)
        
        import math
        sqrt3 = math.sqrt(3)  # ≈ 1.732
        
        # Calculate maximum radius that fits all hexagons horizontally
        if num_pets == 1:
            max_radius_from_width = available_width // 2
        else:
            # total_width = radius * ((num_pets - 1) * √3 + 2)
            # radius = total_width / ((num_pets - 1) * √3 + 2)
            width_factor = (num_pets - 1) * sqrt3 + 2
            max_radius_from_width = int(available_width / width_factor)
        
        # Step 3: Choose the limiting factor (height or width)
        max_radius = min(max_radius_from_height, max_radius_from_width)
        
        # Apply minimum and maximum radius limits
        base_max_radius = 32  # Max radius limit at base scale (64x64 hexagon)
        base_min_radius = 12  # Min radius limit at base scale (24x24 hexagon)
        
        radius = min(max_radius, base_max_radius)
        radius = max(radius, base_min_radius)
        
        #runtime_globals.game_console.log(f"[PetSelector] radius calculation: max_from_height={max_radius_from_height}, max_from_width={max_radius_from_width}, final={radius} (limits: {base_min_radius}-{base_max_radius})")
        
        # Step 4: Calculate actual layout with touching hexagons
        if num_pets == 1:
            total_width = radius * 2
            center_spacing = 0
        else:
            # Use more precise floating point calculation, then round to nearest pixel
            precise_spacing = sqrt3 * radius  # ≈ 1.732 * radius
            center_spacing = round(precise_spacing)
            total_width = (num_pets - 1) * center_spacing + 2 * radius
        
        # Step 5: Calculate starting position to center the hexagon group
        # If total_width exceeds available_width, start from the edge
        if total_width <= available_width:
            start_x = (available_width - total_width) // 2 + radius  # Add radius to get to first center
        else:
            start_x = radius  # Start from left edge plus radius
        center_y = available_height // 2
        
        #runtime_globals.game_console.log(f"[PetSelector] layout: total_width={total_width}, start_x={start_x}, center_y={center_y}, center_spacing={center_spacing}")
        
        # Step 6: Calculate positions for each hexagon center
        self.cell_positions = []
        for i in range(num_pets):
            if num_pets == 1:
                cell_x = available_width // 2  # Center single hexagon
            else:
                cell_x = start_x + (i * center_spacing)
            cell_y = center_y
            self.cell_positions.append((cell_x, cell_y))
            #runtime_globals.game_console.log(f"[PetSelector] cell {i}: base_pos=({cell_x}, {cell_y})")
            
        # Debug: Show final layout bounds
        if self.cell_positions:
            leftmost = min(pos[0] for pos in self.cell_positions) - radius
            rightmost = max(pos[0] for pos in self.cell_positions) + radius
            #runtime_globals.game_console.log(f"[PetSelector] final bounds: left={leftmost}, right={rightmost}, available_width={available_width}")
            
        # Store the calculated radius for this layout (convert to diameter for compatibility)
        self.calculated_cell_size = radius * 2
        
        self.needs_layout_update = False
        self.needs_redraw = True
        

        
    def set_pet_custom_theme(self, pet_index, theme_name):
        """Set a custom theme for a specific pet"""
        if theme_name:
            self.pet_custom_themes[pet_index] = theme_name
        elif pet_index in self.pet_custom_themes:
            del self.pet_custom_themes[pet_index]
        self.needs_redraw = True
    
    def clear_custom_themes(self):
        """Clear all custom pet themes"""
        self.pet_custom_themes.clear()
        self.needs_redraw = True
    
    def set_armor_mode(self, enabled):
        """Enable/disable armor mode for special visual feedback"""
        if self.armor_mode != enabled:
            self.armor_mode = enabled
            self.needs_redraw = True
    
    def is_armor_mode(self):
        """Check if armor mode is enabled"""
        return self.armor_mode
    
    def get_pet_theme_colors(self, pet_index, theme_name=None):
        """Get theme colors for a specific pet"""
        if not self.manager:
            return None
            
        # Use custom theme if specified, otherwise fall back to manager's theme
        if theme_name:
            # Import theme colors from ui_constants
            from ui.ui_constants import (
                GREEN_DARK, GREEN, GREEN_LIGHT,
                BLUE_DARK, BLUE, BLUE_LIGHT,
                BLACK, GREY
            )
            
            if theme_name == "GREEN":
                return {"bg": GREEN_DARK, "fg": GREEN, "highlight": GREEN_LIGHT, "black": BLACK, "grey": GREY}
            elif theme_name == "BLUE":  
                return {"bg": BLUE_DARK, "fg": BLUE, "highlight": BLUE_LIGHT, "black": BLACK, "grey": GREY}
            # Add more themes as needed
        
        return self.manager.get_theme_colors()
    
    def update_colors_from_theme(self):
        """Update colors based on current UI theme"""
        if self.manager:
            theme_colors = self.manager.get_theme_colors()
            # Use theme colors directly
            new_hexagon_color = theme_colors.get("bg", (40, 40, 80))  # Background for non-selected hexagons
            new_enabled_color = theme_colors.get("fg", (255, 255, 255))  # Border for enabled (non-focused) hexagons
            new_disabled_color = theme_colors.get("grey", (128, 128, 128))  # For disabled hexagons
            new_border_color = theme_colors.get("fg", (255, 255, 255))  # Default border color
            new_selected_color = theme_colors.get("bg", (40, 40, 80))  # Background for selected hexagons
            new_highlight_color = theme_colors.get("highlight", (255, 255, 0))  # Border for focused hexagon
            
            # Only mark for redraw if colors actually changed
            if (new_hexagon_color != getattr(self, 'hexagon_color', None) or
                new_enabled_color != getattr(self, 'enabled_color', None) or
                new_disabled_color != getattr(self, 'disabled_color', None) or
                new_border_color != getattr(self, 'border_color', None) or
                new_selected_color != getattr(self, 'selected_color', None) or
                new_highlight_color != getattr(self, 'highlight_color', None)):
                
                self.hexagon_color = new_hexagon_color
                self.enabled_color = new_enabled_color
                self.disabled_color = new_disabled_color
                self.border_color = new_border_color
                self.selected_color = new_selected_color
                self.highlight_color = new_highlight_color
                self.needs_redraw = True
            
    def on_manager_set(self):
        """Called when component is added to UI manager"""
        # Scale visual settings based on UI scale
        if self.manager:
            self.cell_size = self.manager.scale_value(self.base_cell_size)
            self.cell_padding = self.manager.scale_value(self.base_cell_padding)
            self.border_width = self.manager.scale_value(self.base_border_width)
        
        self.update_colors_from_theme()
        self.needs_layout_update = True
        
    def update(self):
        """Update component state"""
        if self.needs_layout_update:
            self.update_layout()
            
        # Update colors if theme changed
        if self.manager:
            self.update_colors_from_theme()
            
    def get_cell_at_position(self, pos):
        """Get the cell index at the given position, or -1 if none"""
        if not self.is_interactive or not self.cell_positions:
            return -1
            
        # Convert to component-relative coordinates using screen coordinates
        # (pos is already in screen coordinates from mouse)
        relative_x = pos[0] - self.rect.x
        relative_y = pos[1] - self.rect.y
        
        # Check if mouse is within component bounds
        if not (0 <= relative_x < self.rect.width and 0 <= relative_y < self.rect.height):
            return -1
        
        # Check each hexagon using distance calculation
        radius = (self.calculated_cell_size // 2) if hasattr(self, 'calculated_cell_size') else (self.base_cell_size // 2)
        if self.manager:
            scaled_radius = self.manager.scale_value(radius)
        else:
            scaled_radius = radius
            
        for i, base_pos in enumerate(self.cell_positions):
            # Scale base position to component-relative scaled coordinates
            # (just scale the values, don't add UI offsets)
            if self.manager:
                scaled_x = self.manager.scale_value(base_pos[0])
                scaled_y = self.manager.scale_value(base_pos[1])
            else:
                scaled_x = base_pos[0]
                scaled_y = base_pos[1]
                
            # Calculate distance from mouse to hexagon center (both in component-relative coordinates)
            dx = relative_x - scaled_x
            dy = relative_y - scaled_y
            distance = (dx * dx + dy * dy) ** 0.5
            
            # Use a slightly smaller radius for better click detection
            if distance <= scaled_radius * 0.9:
                return i
                
        return -1
        

        
    def handle_mouse_motion(self, pos):
        """Handle mouse motion for hover effects"""
        if not self.is_interactive:
            return False
        
        # Disable mouse hover during drag to prevent focus changes
        if hasattr(runtime_globals.game_input, 'is_dragging') and runtime_globals.game_input.is_dragging():
            return False
            
        old_hovered = self.hovered_cell
        self.hovered_cell = self.get_cell_at_position(pos)
        
        # Update focused_cell to match mouse position when component has focus
        if self.focused and self.hovered_cell != -1:
            self.focused_cell = self.hovered_cell
        
        if old_hovered != self.hovered_cell:
            self.needs_redraw = True
            
        return self.hovered_cell != -1
        
    def handle_mouse_click(self, pos, button):
        """Handle mouse clicks for selection"""
        if not self.is_interactive:
            return False
            
        cell = self.get_cell_at_position(pos)       
        if cell != -1 and cell in self.enabled_pets:
            # Set focus to the clicked cell for visual feedback
            self.focused_cell = cell
            
            # Use the same logic as keyboard activation for consistency
            if self.activation_callback:
                # Store the clicked cell and call the callback
                self._clicked_cell = cell
                result = self.activation_callback()
                self._clicked_cell = None  # Clear after use
                # Force cache invalidation to ensure visual update
                self.cached_surface = None
                self.needs_redraw = True
                return result
            else:
                # Default behavior: toggle selection (same as keyboard)
                return self._pick(cell)
            
        return False
        
    def render(self):
        """Render the component using the render-based pattern"""
        if not self.pets or not self.cell_positions:
            return pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
            
        # Create/reuse the surface for this component
        target_size = (self.rect.width, self.rect.height)
        if not hasattr(self, "_render_surface") or self._render_surface is None or self._render_surface.get_size() != target_size:
            self._render_surface = pygame.Surface(target_size, pygame.SRCALPHA)
        surface = self._render_surface
        surface.fill((0, 0, 0, 0))
        
        # Get the radius for hexagons (from calculated size or fallback)
        radius = (self.calculated_cell_size // 2) if hasattr(self, 'calculated_cell_size') else (self.base_cell_size // 2)
        
        # Draw each pet cell
        for pet_index, pet in enumerate(self.pets):
            if pet_index >= len(self.cell_positions):
                continue
                
            base_center = self.cell_positions[pet_index]
            is_enabled = pet_index in self.enabled_pets
            is_selected = pet_index in self._selected_pets
            is_hovered = pet_index == self.hovered_cell and self.is_interactive
            is_focused = pet_index == self.focused_cell and self.is_interactive and self.focused
            
            # Determine visual highlight state - only show highlight when component has focus
            is_highlighted = (pet_index == self.focused_cell and self.focused and self.is_interactive)
            
            # Determine colors based on state priority: disabled -> selected -> highlighted -> enabled
            if not is_enabled:
                # Disabled: grey background, grey border, semi-transparent
                fill_color = self.disabled_color
                border_color = self.disabled_color
                alpha = 128  # Semi-transparent
            elif is_selected and self.armor_mode:
                # Armor mode: selected pets use theme's fg color as background
                if self.manager:
                    theme_colors = self.manager.get_theme_colors()
                    fill_color = theme_colors.get("fg", self.enabled_color)
                    border_color = self.highlight_color if is_highlighted else self.enabled_color
                else:
                    fill_color = self.enabled_color
                    border_color = self.highlight_color if is_highlighted else self.enabled_color
                alpha = 255
            elif is_selected:
                # Selected: use distinct background and highlight border
                if self.manager:
                    theme_colors = self.manager.get_theme_colors()
                    fill_color = theme_colors.get("fg", self.enabled_color)
                else:
                    fill_color = self.enabled_color
                border_color = self.highlight_color
                alpha = 255

                # If this pet has a custom theme, allow it to override colors
                if pet_index in self.pet_custom_themes:
                    custom_theme = self.pet_custom_themes[pet_index]
                    theme_colors = self.get_pet_theme_colors(pet_index, custom_theme)
                    if theme_colors:
                        fill_color = theme_colors.get("fg", fill_color)
                        border_color = theme_colors.get("highlight", border_color)
            elif is_highlighted and runtime_globals.INPUT_MODE != runtime_globals.TOUCH_MODE:
                # Focused/highlighted: highlight border (only when component has focus)
                # Skip in touch mode - focus highlights are for keyboard/mouse navigation only
                fill_color = self.hexagon_color
                border_color = self.highlight_color
                alpha = 255
            else:
                # Default enabled state
                fill_color = self.hexagon_color
                border_color = self.enabled_color
                alpha = 255
                
            # Convert base center to local surface coordinates 
            # (base_center is relative to component, we need scaled coordinates for local surface)
            local_center = (base_center[0], base_center[1])
            
            # Draw hexagon directly on the local surface using scaled values (no offset)
            scaled_center = (
                self.manager.scale_value(local_center[0]) if self.manager else local_center[0],
                self.manager.scale_value(local_center[1]) if self.manager else local_center[1]
            )
            scaled_radius = self.manager.scale_value(radius) if self.manager else radius
            scaled_border_width = self.manager.scale_value(self.base_border_width) if self.manager else self.base_border_width
            
            # Calculate hexagon points for local surface
            points = []
            for j in range(6):
                angle = (math.pi / 3 * j) + (math.pi / 6)  # 60 degrees * j + 30 degrees rotation
                x = scaled_center[0] + scaled_radius * math.cos(angle)
                y = scaled_center[1] + scaled_radius * math.sin(angle)
                points.append((int(x), int(y)))
            
            # Draw filled hexagon on local surface
            if len(points) >= 3:
                # Create a temporary surface for alpha blending if needed
                if alpha < 255:
                    temp_surface = pygame.Surface((scaled_radius * 2 + 4, scaled_radius * 2 + 4), pygame.SRCALPHA)
                    temp_points = [(p[0] - scaled_center[0] + scaled_radius + 2, p[1] - scaled_center[1] + scaled_radius + 2) for p in points]
                    pygame.draw.polygon(temp_surface, fill_color, temp_points)
                    if border_color:
                        pygame.draw.polygon(temp_surface, border_color, temp_points, scaled_border_width)
                    temp_surface.set_alpha(alpha)
                    blit_with_cache(surface, temp_surface, (scaled_center[0] - scaled_radius - 2, scaled_center[1] - scaled_radius - 2))
                else:
                    pygame.draw.polygon(surface, fill_color, points)
                    if border_color:
                        pygame.draw.polygon(surface, border_color, points, scaled_border_width)

            # Draw pet sprite
            if hasattr(pet, 'get_sprite'):
                try:
                    sprite = pet.get_sprite(PetFrame.NAP2.value if pet.state == "nap" else PetFrame.IDLE1.value)
                    if sprite:
                        # Use the same scaled center we calculated for the hexagon (local surface coordinates)
                        sprite_center = scaled_center
                        sprite_radius = scaled_radius
                        
                        sprite_rect = sprite.get_rect()
                        
                        # Calculate sprite padding (leave some space around sprite in hexagon)
                        sprite_padding = max(4, sprite_radius // 8)
                        available_radius = sprite_radius - sprite_padding
                        
                        # Scale sprite to fit in hexagon with padding
                        sprite_scale_factor = min(
                            (available_radius * 2) / sprite_rect.width,
                            (available_radius * 2) / sprite_rect.height
                        )
                        
                        if sprite_scale_factor < 1.0:
                            # Scale down the sprite
                            new_width = max(1, int(sprite_rect.width * sprite_scale_factor))
                            new_height = max(1, int(sprite_rect.height * sprite_scale_factor))
                            sprite = pygame.transform.scale(sprite, (new_width, new_height))
                            sprite_rect = sprite.get_rect()
                            
                        # Center sprite in hexagon
                        sprite_rect.center = sprite_center
                        
                        # Apply transparency for disabled pets
                        if not is_enabled:
                            sprite = sprite.copy()
                            sprite.set_alpha(100)  # Semi-transparent
                            
                        blit_with_cache(surface, sprite, sprite_rect.topleft)
                except Exception as e:
                    # Fallback if sprite loading fails
                    runtime_globals.game_console.log(f"[PetSelector] Failed to load sprite for pet {pet_index}: {e}")
                    pass
                
        return surface
        
    def handle_event(self, event):
        """Handle input events"""
        if not isinstance(event, tuple) or len(event) != 2:
            return False
            
        if not self.is_interactive:
            return False
            
        event_type, event_data = event
        
        # Handle mouse motion for hover
        if event_type == "MOUSE_MOTION":
            if event_data and "pos" in event_data:
                return self.handle_mouse_motion(event_data["pos"])
                
        # Handle directional input
        action = event_type
        """Handle input actions for navigation and selection"""
        if not self.is_interactive or not self.focused:
            return False
            
        if action == "LEFT":
            return self.navigate_left()
        elif action == "RIGHT":
            return self.navigate_right()
        elif action == "A":
            return self.activate_focused_pet()
        elif action in ["UP", "DOWN"]:
            # Allow UP/DOWN to move focus to other components (don't handle it here)
            return False
        return False
    
    def navigate_left(self):
        """Navigate to previous pet"""
        if self.focused_cell > 0:
            self.focused_cell -= 1
            self.needs_redraw = True
            runtime_globals.game_sound.play("menu")
            return True
        return False
    
    def navigate_right(self):
        """Navigate to next pet"""
        if self.focused_cell < len(self.pets) - 1:
            self.focused_cell += 1
            self.needs_redraw = True
            runtime_globals.game_sound.play("menu")
            return True
        return False
    
    def activate_focused_pet(self):
        """Activate (select/deselect) the currently focused pet"""
        if self.focused_cell >= 0 and self.focused_cell < len(self.pets):
            if self.focused_cell in self.enabled_pets:
                # Use custom callback if available
                if self.activation_callback:
                    result = self.activation_callback()
                    self.needs_redraw = True
                    return result
                else:
                    # Default behavior: toggle selection
                    return self._pick(self.focused_cell)
        return False
        
    def _pick(self, cell):
        """Select or deselect *cell*, honouring `max_selection`.

        At a limit of one a new pick **replaces** the old, which is how a
        single choice behaves everywhere else; above one a pick that would
        overflow is refused, so nothing the player already chose disappears
        without them asking.
        """
        if cell in self._selected_pets:
            self._selected_pets.remove(cell)
            runtime_globals.game_sound.play("cancel")
            self.needs_redraw = True
            return True

        limit = self.max_selection
        if limit is not None and len(self._selected_pets) >= limit:
            if limit == 1:
                self._selected_pets = [cell]
                runtime_globals.game_sound.play("menu")
                self.needs_redraw = True
                return True
            runtime_globals.game_sound.play("cancel")
            return True

        self._selected_pets.append(cell)
        runtime_globals.game_sound.play("menu")
        self.needs_redraw = True
        return True

    def get_selected_pets(self):
        """Get list of currently selected pets"""
        return [self.pets[i] for i in self._selected_pets if i < len(self.pets)]
        
    def get_enabled_pets(self):
        """Get list of currently enabled pets"""
        return [self.pets[i] for i in self.enabled_pets if i < len(self.pets)]
        
    def clear_selection(self):
        """Clear all selections"""
        if self._selected_pets:
            self._selected_pets = []
            self.needs_redraw = True
            
    def select_all_enabled(self):
        """Select all enabled pets"""
        old_selection = self._selected_pets[:]
        self._selected_pets = (self.enabled_pets[:self.max_selection]
                               if self.max_selection is not None
                               else self.enabled_pets[:])
        if old_selection != self._selected_pets:
            self.needs_redraw = True
            
    def on_focus_gained(self):
        """Called when component gains focus"""
        self.focused = True
        self.needs_redraw = True
        # Ensure we have a valid focused cell
        if self.focused_cell < 0 or self.focused_cell >= len(self.pets):
            self.focused_cell = 0
        # Clear hover state when gaining keyboard focus
        self.hovered_cell = -1
        
    def on_focus_lost(self):
        """Called when component loses focus"""
        self.focused = False
        self.needs_redraw = True