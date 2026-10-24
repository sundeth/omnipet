"""
Area Selection Component - Horizontal scrollable list for selecting battle areas
"""
import pygame
from ui.components.component import UIComponent
from core import runtime_globals
from ui.ui_constants import GREEN_LIGHT, YELLOW_BRIGHT_LIGHT, YELLOW_BRIGHT_LIGHT
from utils.pygame_utils import blit_with_cache


class AreaSelection(UIComponent):
    def __init__(self, x, y, width, height, module, on_select=None,
                 available_area=None, available_round=None, area_round_limits=None):
        super().__init__(x, y, width, height)
        self.focusable = True
        
        self.module = module
        self.on_select = on_select
        
        # Player's current progress (where they are at)
        from core import game_globals
        self.current_area = game_globals.battle_area.get(module.name, 1)
        self.current_round = game_globals.battle_round.get(module.name, 1)
        
        # Module data (what areas/rounds exist in the module)
        self.area_round_limits = area_round_limits if area_round_limits is not None else {}
        
        # Build list of selectable areas based on module settings
        self.areas = []
        self._build_area_list()

        # Entry fees drawn above an area's first circle: {area: "100P"}.
        self.entry_prices = {}
        
        # Selection state
        self.selected_index = self._get_current_progress_index()
        
        # Visual settings
        self.circle_radius = 12  # Base radius for area circles
        self.circle_spacing = 50  # Base spacing between circles (increased for 1 middle + 1 each side)
        self.line_thickness = 2   # Base thickness for connecting line
        
        # Scroll animation state
        self.target_scroll_offset = 0  # Target for smooth scrolling
        self.scroll_offset = 0  # Current scroll position
        
        # Center on current progress initially (no animation on first load)
        self._center_on_selected_immediately()
        
        # Drag/scroll state (kept for compatibility but not used)
        self.dragging = False
        self.drag_start_x = 0
        self.drag_start_offset = 0
        
        runtime_globals.game_console.log(f"[AreaSelection] Created for module {module.name}: {len(self.areas)} areas, current index {self.selected_index}")
        
    def _build_area_list(self):
        """Build the list of areas to display based on module data and player progress"""
        self.areas = []
        
        if self.module.battle_sequential_rounds:
            # Sequential rounds: only show areas (player fights all rounds in sequence)
            # Iterate through all areas defined in area_round_limits
            for area in sorted(self.area_round_limits.keys()):
                if area < self.current_area:
                    # Completed areas (player has cleared these)
                    status = "completed"
                elif area == self.current_area:
                    # Current area (where player is at)
                    status = "current"
                else:
                    # Locked areas (not yet accessible)
                    status = "locked"
                
                self.areas.append({
                    "area": area,
                    "round": None,  # Sequential mode doesn't select specific rounds
                    "label": f"Area {area}",
                    "status": status
                })
        else:
            # Non-sequential: show area-round combinations (player selects specific rounds)
            # Iterate through all areas and their rounds
            for area in sorted(self.area_round_limits.keys()):
                round_count = self.area_round_limits[area]
                
                for round_num in range(1, round_count + 1):
                    # Determine status based on player progress
                    if area < self.current_area:
                        # All rounds in completed areas are cleared
                        status = "completed"
                    elif area == self.current_area:
                        # In current area, check round progress
                        if round_num < self.current_round:
                            status = "completed"
                        elif round_num == self.current_round:
                            status = "current"
                        else:
                            status = "locked"
                    else:
                        # Future areas are locked
                        status = "locked"
                    
                    self.areas.append({
                        "area": area,
                        "round": round_num,
                        "label": f"{area}-{round_num}",
                        "status": status
                    })
    
    def _get_current_progress_index(self):
        """Get the index of the current progress (should be in the middle)"""
        for i, area_data in enumerate(self.areas):
            if area_data["status"] == "current":
                return i
        return len(self.areas) - 1  # Default to last area
    
    def update(self):
        """Update component state (smooth scrolling animation)"""
        super().update()
        
        # Animate scroll to target position
        if abs(self.scroll_offset - self.target_scroll_offset) > 1:
            diff = self.target_scroll_offset - self.scroll_offset
            self.scroll_offset += diff * 0.2  # Smooth easing
            self.needs_redraw = True
        elif self.scroll_offset != self.target_scroll_offset:
            self.scroll_offset = self.target_scroll_offset
            self.needs_redraw = True
    
    def set_entry_prices(self, prices):
        """Show each area's entry fee ({area: text}) above the circle that
        enters it: the area's own in sequential mode, else its round 1."""
        self.entry_prices = dict(prices or {})
        self.needs_redraw = True

    def get_selected_area_round(self):
        """Get the currently selected area and round"""
        if 0 <= self.selected_index < len(self.areas):
            area_data = self.areas[self.selected_index]
            return area_data["area"], area_data["round"] or 1
        return 1, 1
    
    def handle_event(self, event):
        """Handle keyboard/gamepad input - can only select cleared or current areas"""
        if not self.visible or not self.focusable:
            return False
        
        # Handle tuple-based events
        if not isinstance(event, tuple) or len(event) != 2:
            return False
            
        event_type, event_data = event
        
        if event_type == "LEFT":
            # Move to previous available area (completed or current only)
            new_index = self.selected_index - 1
            while new_index >= 0:
                area_status = self.areas[new_index]["status"]
                if area_status in ["completed", "current"]:
                    self.selected_index = new_index
                    self._adjust_scroll_to_show_selected_smooth()
                    self.needs_redraw = True
                    if runtime_globals.game_sound:
                        runtime_globals.game_sound.play("menu")
                    return True
                new_index -= 1
            runtime_globals.game_sound.play("cancel")
            return True
        elif event_type == "RIGHT":
            # Move to next available area (completed or current only)
            new_index = self.selected_index + 1
            while new_index < len(self.areas):
                area_status = self.areas[new_index]["status"]
                if area_status in ["completed", "current"]:
                    self.selected_index = new_index
                    self._adjust_scroll_to_show_selected_smooth()
                    self.needs_redraw = True
                    if runtime_globals.game_sound:
                        runtime_globals.game_sound.play("menu")
                    return True
                new_index += 1
            runtime_globals.game_sound.play("cancel")
            return True
        elif event_type == "A":
            # Select current area
            if 0 <= self.selected_index < len(self.areas):
                area_data = self.areas[self.selected_index]
                if area_data["status"] in ["completed", "current"]:
                    if self.on_select:
                        self.on_select(area_data["area"], area_data["round"] or 1)
                    if runtime_globals.game_sound:
                        runtime_globals.game_sound.play("menu")
                    return True
        
        return False
    
    def handle_scroll(self, action):
        """Handle scroll wheel input - disabled in favor of keyboard navigation"""
        # Scroll disabled - use LEFT/RIGHT to navigate between areas
        return False
    
    def handle_drag(self, event):
        """Handle mouse drag for horizontal scrolling"""
        if not isinstance(event, tuple) or len(event) != 2:
            return False
        
        event_type, event_data = event
        
        if not (runtime_globals.INPUT_MODE in [runtime_globals.MOUSE_MODE, runtime_globals.TOUCH_MODE]):
            return False
        
        if event_type == "DRAG_START":
            mouse_pos = event_data.get("pos")
            if not mouse_pos:
                return False
                
            relative_x = mouse_pos[0] - self.rect.x
            relative_y = mouse_pos[1] - self.rect.y
            
            # Check if mouse is within component bounds
            if not (0 <= relative_x < self.rect.width and 0 <= relative_y < self.rect.height):
                return False
            
            # Start drag - store last position for incremental updates
            self._drag_last_pos = mouse_pos
            self._is_dragging = True
            runtime_globals.game_console.log("[AreaSelection] Drag started")
            return True
        
        elif event_type == "DRAG_MOTION" and hasattr(self, '_is_dragging') and self._is_dragging:
            current_pos = event_data.get("pos")
            if not current_pos:
                return False
            
            # Calculate incremental movement from last position (horizontal only)
            dx = current_pos[0] - self._drag_last_pos[0]
            
            # Apply horizontal scroll (drag right = scroll right, so negate)
            self.scroll_offset -= dx
            
            # Clamp scroll to valid range
            max_scroll = self._calculate_max_scroll()
            self.scroll_offset = max(0, min(max_scroll, self.scroll_offset))
            
            # Also update target to prevent animation fighting
            self.target_scroll_offset = self.scroll_offset
            
            self.needs_redraw = True
            
            # Update last position for next motion event
            self._drag_last_pos = current_pos
            return True
        
        elif event_type == "DRAG_END":
            if hasattr(self, '_is_dragging') and self._is_dragging:
                self._is_dragging = False
                runtime_globals.game_console.log("[AreaSelection] Drag ended")
                return True
        
        return False
    
    def handle_mouse_click(self, mouse_pos, action):
        """Handle mouse click on areas - can only select cleared or current areas"""
        runtime_globals.game_console.log(f"[AreaSelection] handle_mouse_click called: pos={mouse_pos}, action={action}, visible={self.visible}")
        
        if not self.visible or action != "LCLICK":
            return False
        
        # Note: UIManager already checked that mouse_pos is within self.rect
        
        # Calculate which area was clicked
        if self.manager:
            scaled_radius = self.manager.scale_value(self.circle_radius)
            scaled_spacing = self.manager.scale_value(self.circle_spacing)
            
            # Convert mouse position to component-relative coordinates
            local_x = mouse_pos[0] - self.rect.x
            local_y = mouse_pos[1] - self.rect.y
            
            runtime_globals.game_console.log(f"[AreaSelection] Screen: {mouse_pos}, Local: ({local_x}, {local_y}), Rect: {self.rect}")
            
            # Calculate center line Y
            center_y = self.rect.height // 2
            
            # Check each visible area circle
            start_x = (self.rect.width // 2) - int(self.scroll_offset)
            
            runtime_globals.game_console.log(f"[AreaSelection] start_x={start_x}, scroll_offset={self.scroll_offset}, scaled_radius={scaled_radius}, scaled_spacing={scaled_spacing}")
            
            for i, area_data in enumerate(self.areas):
                circle_x = start_x + (i * (scaled_radius * 2 + scaled_spacing))
                circle_y = center_y
                
                # Check if click is within this circle
                distance = ((local_x - circle_x) ** 2 + (local_y - circle_y) ** 2) ** 0.5
                
                if distance <= scaled_radius * 1.5:  # Log nearby circles too
                    runtime_globals.game_console.log(f"[AreaSelection] Area {i} '{area_data['label']}' status={area_data['status']}: circle_pos=({circle_x:.0f}, {circle_y:.0f}), distance={distance:.1f}, radius={scaled_radius}")
                
                if distance <= scaled_radius:
                    runtime_globals.game_console.log(f"[AreaSelection] HIT! Clicked on area {i} ({area_data['label']}), status: {area_data['status']}")
                    # Clicked on this area - only allow completed or current
                    if area_data["status"] in ["completed", "current"]:
                        runtime_globals.game_console.log(f"[AreaSelection] Selecting area {i}")
                        self.selected_index = i
                        self._adjust_scroll_to_show_selected_smooth()
                        self.needs_redraw = True
                        if self.on_select:
                            self.on_select(area_data["area"], area_data["round"] or 1)
                        if runtime_globals.game_sound:
                            runtime_globals.game_sound.play("menu")
                        return True
                    else:
                        runtime_globals.game_sound.play("cancel")
                        runtime_globals.game_console.log(f"[AreaSelection] Area {i} is locked, cannot select")
                        return False  # Still return False for locked areas
        
        runtime_globals.game_console.log(f"[AreaSelection] No area clicked")
        return False
    
    def _center_on_selected_immediately(self):
        """Immediately center on selected area without animation (for initialization)"""
        if not self.manager:
            return
        
        # Calculate center offset with proper scaling
        scaled_radius = self.manager.scale_value(self.circle_radius)
        scaled_spacing = self.manager.scale_value(self.circle_spacing)
        
        # Calculate scroll offset to center the selected circle
        # Formula: scroll_offset = selected_index * (diameter + spacing)
        # This centers because: start_x + (index * spacing) = center when scroll_offset = index * spacing
        self.scroll_offset = self.selected_index * (scaled_radius * 2 + scaled_spacing)
        self.target_scroll_offset = self.scroll_offset
    
    def on_manager_set(self):
        """Called when component is added to UI manager - recalculate positioning"""
        # Recalculate scroll with proper scaling
        self._center_on_selected_immediately()
    
    def _adjust_scroll_to_show_selected_smooth(self):
        """Smoothly animate scroll to center the selected area"""
        if not self.manager:
            return
        
        scaled_radius = self.manager.scale_value(self.circle_radius)
        scaled_spacing = self.manager.scale_value(self.circle_spacing)
        
        # Calculate target scroll offset to center the selected item
        # Formula: scroll_offset = selected_index * (diameter + spacing)
        self.target_scroll_offset = self.selected_index * (scaled_radius * 2 + scaled_spacing)
        
        # Clamp to valid scroll range
        max_scroll = self._calculate_max_scroll()
        self.target_scroll_offset = max(0, min(max_scroll, self.target_scroll_offset))
    
    def _calculate_max_scroll(self):
        """Calculate maximum scroll offset"""
        if not self.manager:
            return 0
        
        scaled_radius = self.manager.scale_value(self.circle_radius)
        scaled_spacing = self.manager.scale_value(self.circle_spacing)
        
        total_width = len(self.areas) * (scaled_radius * 2 + scaled_spacing)
        return max(0, total_width - self.rect.width)
    
    def render(self):
        """Render the area selection component with timeline"""
        surface = pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
        
        if not self.manager or not self.areas:
            return surface
        
        # Get theme colors
        theme_colors = self.manager.get_theme_colors()
        from ui.ui_constants import GREEN, GREEN_DARK, YELLOW_BRIGHT, YELLOW_BRIGHT_DARK, RED, RED_DARK
        
        # Scale visual elements
        scaled_radius = self.manager.scale_value(self.circle_radius)
        scaled_spacing = self.manager.scale_value(self.circle_spacing)
        scaled_line_thickness = self.manager.scale_value(self.line_thickness)
        
        # Calculate center line position
        center_y = self.rect.height // 2
        
        # Calculate starting position (using smooth scroll offset)
        start_x = (self.rect.width // 2) - int(self.scroll_offset)
        
        # Get fonts
        text_font = self.get_font("text")
        
        # Draw red connecting line behind all circles
        first_circle_x = None
        last_circle_x = None
        
        for i, area_data in enumerate(self.areas):
            circle_x = start_x + (i * (scaled_radius * 2 + scaled_spacing))
            
            # Track first and last circle positions for line
            if first_circle_x is None:
                first_circle_x = circle_x
            last_circle_x = circle_x
        
        # Draw red line connecting all circles
        if first_circle_x is not None and last_circle_x is not None:
            pygame.draw.line(surface, RED, 
                            (int(first_circle_x), center_y), 
                            (int(last_circle_x), center_y), 
                            scaled_line_thickness)
        
        # Draw each area circle
        for i, area_data in enumerate(self.areas):
            circle_x = start_x + (i * (scaled_radius * 2 + scaled_spacing))
            circle_y = center_y
            
            # Skip if way out of viewport (optimization)
            if circle_x < -scaled_radius * 3 or circle_x > self.rect.width + scaled_radius * 3:
                continue
            
            # Determine colors based on status
            status = area_data["status"]
            is_selected = (i == self.selected_index)
            
            if status == "completed":
                # Green for cleared areas
                bg_color = GREEN_DARK
                border_color = GREEN
                # Green highlight when selected
                if is_selected:
                    border_color = GREEN_LIGHT
                    border_thickness = self.manager.get_border_size() * 2
                else:
                    border_thickness = self.manager.get_border_size()
            elif status == "current":
                # Yellow for current area
                bg_color = YELLOW_BRIGHT_DARK
                border_color = YELLOW_BRIGHT
                # Yellow bright highlight when selected
                if is_selected:
                    border_color = YELLOW_BRIGHT_LIGHT
                    border_thickness = self.manager.get_border_size() * 2
                else:
                    border_thickness = self.manager.get_border_size()
            else:  # locked
                # Red for locked areas - cannot be selected/highlighted
                bg_color = RED_DARK
                border_color = RED
                border_thickness = self.manager.get_border_size()
            
            # Draw circle
            pygame.draw.circle(surface, bg_color, (int(circle_x), int(circle_y)), scaled_radius)
            pygame.draw.circle(surface, border_color, (int(circle_x), int(circle_y)), 
                             scaled_radius, border_thickness)
            
            # Draw label below circle
            label_surface = text_font.render(area_data["label"], True, theme_colors["fg"])
            label_rect = label_surface.get_rect()
            label_rect.centerx = int(circle_x)
            label_rect.top = int(circle_y + scaled_radius + self.manager.scale_value(4))
            
            # Only draw label if visible in viewport
            if label_rect.right > 0 and label_rect.left < self.rect.width:
                from utils.pygame_utils import blit_with_cache
                blit_with_cache(surface, label_surface, label_rect.topleft)

            # The entry fee above the circle that enters the area.
            price = self.entry_prices.get(area_data["area"])
            if price and area_data["round"] in (None, 1):
                price_surface = text_font.render(price, True, YELLOW_BRIGHT)
                price_rect = price_surface.get_rect()
                price_rect.centerx = int(circle_x)
                price_rect.bottom = int(circle_y - scaled_radius - self.manager.scale_value(3))
                if price_rect.right > 0 and price_rect.left < self.rect.width:
                    from utils.pygame_utils import blit_with_cache
                    blit_with_cache(surface, price_surface, price_rect.topleft)
        
        return surface
