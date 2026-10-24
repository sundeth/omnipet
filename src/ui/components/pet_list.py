"""
Horizontal Pet List Component - Scrollable horizontal list for pet selection
"""
import pygame
import os
from ui.components.component import UIComponent
from ui.ui_constants import TEXT_FONT
from core import runtime_globals
from models.animation import PetFrame
from utils.pygame_utils import blit_with_cache
from utils.scene_utils import change_scene


def safe_font_load(font_path, size):
    """Safely load a font with case-sensitive file checking"""
    from utils.asset_utils import font_load, resolve_path
    try:
        # Use resolve_path for Android compatibility
        resolved_path = resolve_path(font_path)
        
        # Check if exact path exists
        if os.path.exists(resolved_path):
            return font_load(font_path, size)
        
        # If not found, try to find case variations
        base_dir = os.path.dirname(resolved_path)
        filename = os.path.basename(font_path)
        
        if os.path.exists(base_dir):
            for file in os.listdir(base_dir):
                if file.lower() == filename.lower():
                    corrected_rel = os.path.join(os.path.dirname(font_path), file)
                    runtime_globals.game_console.log(f"[PetList] Font case corrected: {font_path} -> {corrected_rel}")
                    return font_load(corrected_rel, size)
        
        # Fallback to default font
        runtime_globals.game_console.log(f"[PetList] Font not found: {font_path}, using default")
        return font_load(TEXT_FONT, size)
        
    except Exception as e:
        runtime_globals.game_console.log(f"[PetList] Error loading font {font_path}: {e}")
        return font_load(TEXT_FONT, size)
import core.constants as constants


class PetList(UIComponent):
    def __init__(self, x, y, width, height, pets, on_select_callback=None):
        super().__init__(x, y, width, height)
        self.pets = pets
        self.selected_index = 0  # Currently focused item (for navigation)
        self.active_index = 0    # Currently selected item (for showing stats)
        self.focusable = True
        self.is_dynamic = True  # Pet list animates sprites, so it's dynamic
        self.scroll_anim_start = 0
        self.scroll_anim_duration = 300  # ms
        self.scrolling = False
        self.target_scroll_offset = 0
        self.current_scroll_offset = 0
        self.on_select_callback = on_select_callback
        self.on_item_click = on_select_callback  # Alias for consistency
        self.on_exit_click = lambda: change_scene("game")  # Default EXIT behavior
        self.last_frame_switch = pygame.time.get_ticks()
        self.current_frame = 0  # For selected pet animation (0=IDLE1, 1=IDLE2)
        
        # Navigation state
        self.left_arrow_pressed = False
        self.right_arrow_pressed = False
        self.arrow_press_time = 0
        
        # Calculate layout using adaptive scaling for better proportions
        # Use actual screen width for scaling calculations, not just component width
        
        # Base button sizes for 240x240 design
        self.base_arrow_width = 24
        self.base_exit_width = 40
        self.base_margin = 2
        
        # Get actual screen width for proper scaling calculations
        # Start with component width as fallback, will be updated when manager is set
        actual_screen_width = width
        
        # Calculate visible pets based on exact UI scale requirements:
        # 1x = 4 pets, 2x = 6 pets, 3x = 8 pets, 4x = 10 pets
        # When fewer pets exist, spread boxes to fill width but maintain minimum slots
        
        # Get UI scale factor from manager if available, otherwise estimate from width
        # This will be updated in on_manager_set() with correct scale
        ui_scale = actual_screen_width / 240 if actual_screen_width > 0 else 1
        
        # Define exact pet counts for each scale level
        if ui_scale <= 1.5:      # 1x scale
            target_visible_pets = 4
        elif ui_scale <= 2.5:    # 2x scale  
            target_visible_pets = 6
        elif ui_scale <= 3.5:    # 3x scale
            target_visible_pets = 8
        else:                    # 4x scale and above
            target_visible_pets = 10
            
        # Cap at maximum pets if needed
        if target_visible_pets > constants.MAX_PETS:
            target_visible_pets = constants.MAX_PETS
        
        # Calculate available space for pets (in base coordinates)
        available_width = width - (2 * self.base_arrow_width) - self.base_exit_width - (3 * self.base_margin)
        
        # Get actual pet count
        actual_pet_count = len(pets)
        
        # Determine how many slots to actually use
        if actual_pet_count >= target_visible_pets:
            # Use target visible pets when we have enough pets
            slots_to_use = target_visible_pets
        elif actual_pet_count >= 4:
            # Use actual pet count when between 4 and target (spread to fill width)
            slots_to_use = actual_pet_count
        else:
            # Always use minimum 4 slots even with fewer pets
            slots_to_use = 4
            
        # Calculate item width to fit the slots evenly across available width
        self.item_width = available_width // slots_to_use
        self.visible_pets = slots_to_use
        
        # Set reasonable minimum width to ensure pet sprites are visible
        min_item_width = max(12, min(20, height - 4))
        
        # Ensure item width isn't too small
        if self.item_width < min_item_width:
            self.item_width = min_item_width
            # Recalculate how many actually fit with minimum width
            self.visible_pets = max(1, available_width // self.item_width)
        
        # Debug the width calculations
        runtime_globals.game_console.log(f"[PetList] UI Scale: {ui_scale:.1f}x, Target slots: {target_visible_pets}, Actual pets: {actual_pet_count}")
        runtime_globals.game_console.log(f"[PetList] Using {slots_to_use} slots, Available width: {available_width}px")
        runtime_globals.game_console.log(f"[PetList] Item width: {self.item_width}px, Min width: {min_item_width}px")
        runtime_globals.game_console.log(f"[PetList] Final visible pets: {self.visible_pets}")
            
        # Store screen width for sprite scaling calculations
        self.actual_screen_width = actual_screen_width

        # Layout positions in base coordinates (will be scaled by UI manager)
        self.left_arrow_rect = pygame.Rect(0, 0, self.base_arrow_width, height)
        self.right_arrow_rect = pygame.Rect(width - self.base_arrow_width, 0, self.base_arrow_width, height)
        self.exit_rect = pygame.Rect(width - self.base_arrow_width - self.base_exit_width - self.base_margin, 
                                   0, self.base_exit_width, height)
        self.pets_start_x = self.base_arrow_width + self.base_margin
        self.pets_width = available_width
        
        # Scroll state
        self.first_visible_pet = 0
        
        # Rendering layers
        self.static_layer = None
        self.clicked = False
        
        # Highlight animation system
        self.highlight_anim_start = 0
        self.highlight_anim_duration = 150  # ms - fast animation
        self.highlight_animating = False
        self.highlight_start_rect = None
        self.highlight_target_rect = None
        self.highlight_current_rect = None
        
        # Mouse hover state tracking (separate from keyboard selection)
        self.hover_index = -1  # Which element is being hovered (-1 = none, len(pets) = exit button)
        self.hover_left_arrow = False   # Left arrow hover state
        self.hover_right_arrow = False  # Right arrow hover state
        self.last_selected_index = 0  # Track previous selection for animation
        
        # Load pet sprites
        self.pet_sprites = {}
        self.load_pet_sprites()
        
    def on_manager_set(self):
        """Called when the UI manager is set - recalculate scaling with proper UI scale info"""
        if self.manager:
            # Get actual UI scale from manager
            ui_scale = self.manager.ui_scale
            
            # Get actual screen dimensions from multiple sources
            screen_width = runtime_globals.SCREEN_WIDTH
            # Recalculate if we have better screen information now or UI scale changed
            if screen_width != self.actual_screen_width and screen_width > 240:
                old_width = self.actual_screen_width
                self.actual_screen_width = screen_width
                
                # Use exact pet counts for each UI scale level (same as constructor)
                if ui_scale <= 1.5:      # 1x scale
                    target_visible_pets = 4
                elif ui_scale <= 2.5:    # 2x scale  
                    target_visible_pets = 6
                elif ui_scale <= 3.5:    # 3x scale
                    target_visible_pets = 8
                else:                    # 4x scale and above
                    target_visible_pets = 10
                    
                # Cap at maximum pets if needed
                if target_visible_pets > constants.MAX_PETS:
                    target_visible_pets = constants.MAX_PETS
                
                # Calculate available width
                available_width = self.base_rect.width - (2 * self.base_arrow_width) - self.base_exit_width - (3 * self.base_margin)
                
                # Get actual pet count
                actual_pet_count = len(self.pets)
                
                # Determine how many slots to actually use
                if actual_pet_count >= target_visible_pets:
                    # Use target visible pets when we have enough pets
                    slots_to_use = target_visible_pets
                elif actual_pet_count >= 4:
                    # Use actual pet count when between 4 and target (spread to fill width)
                    slots_to_use = actual_pet_count
                else:
                    # Always use minimum 4 slots even with fewer pets
                    slots_to_use = 4
                    
                # Calculate item width to fit the slots evenly across available width
                self.item_width = available_width // slots_to_use
                self.visible_pets = slots_to_use
                
                # Set reasonable minimum width to ensure pet sprites are visible
                min_item_width = max(12, min(20, self.base_rect.height - 4))
                
                # Ensure item width isn't too small
                if self.item_width < min_item_width:
                    self.item_width = min_item_width
                    # Recalculate how many actually fit with minimum width
                    self.visible_pets = max(1, available_width // self.item_width)
                
                runtime_globals.game_console.log(f"[PetList] Updated scaling - Screen: {screen_width}px (was {old_width}px)")
                runtime_globals.game_console.log(f"[PetList] UI Scale: {ui_scale:.1f}x, Target slots: {target_visible_pets}, Actual pets: {actual_pet_count}")
                runtime_globals.game_console.log(f"[PetList] Using {slots_to_use} slots, Item width: {self.item_width}px")
                runtime_globals.game_console.log(f"[PetList] Final visible pets: {self.visible_pets}")
                
                # Reload sprites with new dimensions
                self.load_pet_sprites()
                self.static_layer = None  # Force redraw

    def set_active_pet(self, index):
        """Set the active pet (the one we're showing stats for)"""
        if 0 <= index < len(self.pets):
            self.active_index = index
            self.static_layer = None  # Force redraw
            self.needs_redraw = True
    
    def get_element_rect(self, index):
        """Get the rect for a given element (pet slot, exit button, or arrow button)"""
        # Get scaled dimensions
        scaled_arrow_width = self.manager.scale_value(self.base_arrow_width) if self.manager else self.base_arrow_width
        scaled_exit_width = self.manager.scale_value(self.base_exit_width) if self.manager else self.base_exit_width
        scaled_margin = self.manager.scale_value(self.base_margin) if self.manager else self.base_margin
        scaled_item_width = self.manager.scale_value(self.item_width) if self.manager else self.item_width
        scaled_pets_start_x = scaled_arrow_width + scaled_margin
        
        if index < len(self.pets):
            # Pet slot
            if self.first_visible_pet <= index < self.first_visible_pet + self.visible_pets:
                x_pos = scaled_pets_start_x + (index - self.first_visible_pet) * scaled_item_width - self.current_scroll_offset
                return pygame.Rect(x_pos, 0, scaled_item_width, self.rect.height)
            else:
                return None  # Not visible
        elif index == len(self.pets):
            # Exit button
            exit_x = self.rect.width - scaled_arrow_width - scaled_exit_width - scaled_margin
            return pygame.Rect(exit_x, 0, scaled_exit_width, self.rect.height)
        elif index == -1:
            # Left arrow
            return pygame.Rect(0, 0, scaled_arrow_width, self.rect.height)
        elif index == -2:
            # Right arrow
            return pygame.Rect(self.rect.width - scaled_arrow_width, 0, scaled_arrow_width, self.rect.height)
        return None
    
    def start_highlight_animation(self, from_index, to_index):
        """Start highlight animation from one element to another"""
        start_rect = self.get_element_rect(from_index)
        target_rect = self.get_element_rect(to_index)
        
        if start_rect and target_rect:
            self.highlight_start_rect = start_rect.copy()
            self.highlight_target_rect = target_rect.copy()
            self.highlight_current_rect = start_rect.copy()
            self.highlight_animating = True
            self.highlight_anim_start = pygame.time.get_ticks()
        elif target_rect:
            # If we don't have a start rect (element not visible), just snap to target
            self.highlight_current_rect = target_rect.copy()
            self.highlight_animating = False
        else:
            # Target not visible, disable highlight
            self.highlight_animating = False
            self.highlight_current_rect = None
    
    def update_highlight_animation(self):
        """Update the highlight animation"""
        if not self.highlight_animating:
            return
            
        now = pygame.time.get_ticks()
        progress = min(1.0, (now - self.highlight_anim_start) / self.highlight_anim_duration)
        
        # Use smooth easing
        progress = progress * progress * (3.0 - 2.0 * progress)
        
        if progress >= 1.0:
            # Animation complete
            self.highlight_animating = False
            self.highlight_current_rect = self.highlight_target_rect.copy() if self.highlight_target_rect else None
        else:
            # Interpolate rect
            if self.highlight_start_rect and self.highlight_target_rect:
                start = self.highlight_start_rect
                target = self.highlight_target_rect
                
                x = start.x + (target.x - start.x) * progress
                y = start.y + (target.y - start.y) * progress
                width = start.width + (target.width - start.width) * progress
                height = start.height + (target.height - start.height) * progress
                
                self.highlight_current_rect = pygame.Rect(x, y, width, height)
        
        self.needs_redraw = True
        
    def load_pet_sprites(self):
        """Load pet sprites for display"""
        try:
            for i, pet in enumerate(self.pets):
                try:
                    # Validate frame indices exist
                    idle1_index = PetFrame.IDLE1.value
                    idle2_index = PetFrame.IDLE2.value
                    
                    if pet not in runtime_globals.pet_sprites:
                        raise KeyError(f"Pet {pet.name if hasattr(pet, 'name') else 'unknown'} not found in pet_sprites")
                    
                    pet_sprite_list = runtime_globals.pet_sprites[pet]
                    if not isinstance(pet_sprite_list, list) or len(pet_sprite_list) <= max(idle1_index, idle2_index):
                        raise IndexError(f"Pet {pet.name if hasattr(pet, 'name') else 'unknown'} sprite list has insufficient frames: {len(pet_sprite_list) if isinstance(pet_sprite_list, list) else 'not a list'}")
                    
                    frames = [
                        pet_sprite_list[idle1_index],
                        pet_sprite_list[idle2_index],
                    ]
                    
                    # Validate frames are actual surfaces
                    for idx, frame in enumerate(frames):
                        if not isinstance(frame, pygame.Surface):
                            raise TypeError(f"Frame {idx} for pet {pet.name if hasattr(pet, 'name') else 'unknown'} is not a pygame.Surface: {type(frame)}")
                    
                    # Calculate proper sprite size based on actual screen size and UI scale
                    # Use actual screen dimensions for better sprite scaling
                    screen_scale_factor = self.actual_screen_width / 240  # Scale factor from base resolution
                    
                    if self.manager:
                        # Get the actual screen size of the pet slot with proper scaling
                        ui_scale = self.manager.ui_scale
                        scaled_item_width = self.manager.scale_value(self.item_width)
                        scaled_height = self.manager.scale_value(self.base_rect.height if hasattr(self, 'base_rect') else self.rect.height)
                        
                        # Calculate sprite size based on actual screen resolution for better scaling
                        # Use screen width ratio to determine appropriate sprite size
                        base_sprite_size = max(24, min(self.item_width - 4, 48))  # Base sprite size range
                        target_sprite_size = int(base_sprite_size * min(screen_scale_factor, 3.0))  # Limit max scaling
                        
                        # Ensure sprite fits in slot with padding
                        slot_padding = 4
                        max_sprite_size = min(scaled_item_width - slot_padding, scaled_height - slot_padding)
                        sprite_size = min(target_sprite_size, max_sprite_size)
                        sprite_size = max(20, sprite_size)  # Minimum 20px for visibility
                    else:
                        # Fallback without manager - use simpler calculation
                        base_sprite_size = max(20, self.item_width - 4)
                        target_sprite_size = int(base_sprite_size * min(screen_scale_factor, 2.0))  # Define target_sprite_size here too
                        sprite_size = max(20, target_sprite_size)
                    
                    # Scale frames to the calculated size, maintaining aspect ratio.
                    # Nearest-neighbor keeps the pixel art sharp; smoothscale
                    # smears the edges into blurry artifacts.
                    scaled_frames = []
                    for frame in frames:
                        # Always scale to ensure consistent sizing
                        scaled_frame = pygame.transform.scale(frame.copy(), (sprite_size, sprite_size))
                        scaled_frames.append(scaled_frame)
                    
                    self.pet_sprites[i] = scaled_frames
                    
                    # Debug logging for sprite scaling (only for first pet to avoid spam)
                    if i == 0:
                        runtime_globals.game_console.log(f"[PetList] First pet sprite size: {sprite_size}px (screen scale: {screen_scale_factor:.2f}x)")
                        runtime_globals.game_console.log(f"[PetList] Base sprite size: {base_sprite_size}px, Target: {target_sprite_size}px, Final: {sprite_size}px")
                except Exception as e:
                    runtime_globals.game_console.log(f"[PetList] Error loading sprites for pet {i} ({pet.name if hasattr(pet, 'name') else 'unknown'}): {e}")
                    # Create placeholder sprites if loading fails
                    sprite_size = max(16, self.item_width - 6) if hasattr(self, 'item_width') else 32
                    placeholder = pygame.Surface((sprite_size, sprite_size), pygame.SRCALPHA)
                    placeholder.fill((255, 0, 255, 128))  # Pink placeholder
                    self.pet_sprites[i] = [placeholder, placeholder]
        except Exception as e:
            runtime_globals.game_console.log(f"[PetList] Critical error in load_pet_sprites: {e}")
            import traceback
            runtime_globals.game_console.log(f"[PetList] Traceback: {traceback.format_exc()}")
            
    def update(self):
        super().update()
        now = pygame.time.get_ticks()
        
        # Check if selection changed to trigger highlight animation
        if self.selected_index != self.last_selected_index:
            self.start_highlight_animation(self.last_selected_index, self.selected_index)
            self.last_selected_index = self.selected_index
        
        # Update highlight animation
        self.update_highlight_animation()
        
        # Animate active pet (IDLE1/IDLE2 every 500ms)
        if now - self.last_frame_switch > 500:
            self.last_frame_switch = now
            self.current_frame = 1 - self.current_frame  # Toggle between 0 and 1
            self.needs_redraw = True
            
        # Reset arrow press states
        if self.left_arrow_pressed and now - self.arrow_press_time > 100:
            self.left_arrow_pressed = False
            self.static_layer = None
            self.needs_redraw = True
        if self.right_arrow_pressed and now - self.arrow_press_time > 100:
            self.right_arrow_pressed = False
            self.static_layer = None
            self.needs_redraw = True
            
        # Handle scrolling animation
        if self.scrolling:
            progress = min(1.0, (now - self.scroll_anim_start) / self.scroll_anim_duration)
            progress = progress * progress * (3.0 - 2.0 * progress)  # Smooth easing
            self.current_scroll_offset = self.target_scroll_offset * progress
            if progress >= 1.0:
                self.scrolling = False
                self.current_scroll_offset = 0
                self.static_layer = None
            self.needs_redraw = True
            
        # Handle mouse hover for selection changes
        self.handle_mouse_hover()
    
    def handle_mouse_hover(self):
        """Handle mouse hover for highlighting (separate from selection)"""
        if not (runtime_globals.INPUT_MODE in [runtime_globals.MOUSE_MODE, runtime_globals.TOUCH_MODE]):
            old_hover_index = getattr(self, 'hover_index', -1)
            old_hover_left = getattr(self, 'hover_left_arrow', False)
            old_hover_right = getattr(self, 'hover_right_arrow', False)
            self.hover_index = -1
            self.hover_left_arrow = False
            self.hover_right_arrow = False
            if old_hover_left or old_hover_right or old_hover_index != -1:
                self.needs_redraw = True
            return
        
        # Disable mouse hover during drag to prevent focus changes
        if hasattr(self, '_is_dragging') and self._is_dragging:
            old_hover_index = getattr(self, 'hover_index', -1)
            old_hover_left = getattr(self, 'hover_left_arrow', False)
            old_hover_right = getattr(self, 'hover_right_arrow', False)
            self.hover_index = -1
            self.hover_left_arrow = False
            self.hover_right_arrow = False
            if old_hover_left or old_hover_right or old_hover_index != -1:
                self.needs_redraw = True
            return
        
        # Also check if InputManager is currently dragging
        if hasattr(runtime_globals.game_input, 'is_dragging') and runtime_globals.game_input.is_dragging():
            old_hover_index = getattr(self, 'hover_index', -1)
            old_hover_left = getattr(self, 'hover_left_arrow', False)
            old_hover_right = getattr(self, 'hover_right_arrow', False)
            self.hover_index = -1
            self.hover_left_arrow = False
            self.hover_right_arrow = False
            if old_hover_left or old_hover_right or old_hover_index != -1:
                self.needs_redraw = True
            return

        mouse_pos = runtime_globals.game_input.get_mouse_position()

        # Convert to component-relative coordinates using screen coordinates
        relative_x = mouse_pos[0] - self.rect.x
        relative_y = mouse_pos[1] - self.rect.y

        # Store old states before any changes
        old_hover_index = getattr(self, 'hover_index', -1)
        old_hover_left = getattr(self, 'hover_left_arrow', False)
        old_hover_right = getattr(self, 'hover_right_arrow', False)

        # Check if mouse is within component bounds
        if not (0 <= relative_x < self.rect.width and 0 <= relative_y < self.rect.height):
            self.hover_index = -1
            self.hover_left_arrow = False
            self.hover_right_arrow = False
            if old_hover_left or old_hover_right or old_hover_index != -1:
                self.needs_redraw = True
            return

        # Get scaled dimensions for proper hit detection
        scaled_arrow_width = self.manager.scale_value(self.base_arrow_width)
        scaled_exit_width = self.manager.scale_value(self.base_exit_width)
        scaled_margin = self.manager.scale_value(self.base_margin)
        
        # Reset hover states
        self.hover_index = -1
        self.hover_left_arrow = False
        self.hover_right_arrow = False

        # Check left arrow hover
        if relative_x < scaled_arrow_width:
            self.hover_left_arrow = True
        # Check right arrow hover  
        elif relative_x >= self.rect.width - scaled_arrow_width:
            self.hover_right_arrow = True
        else:
            # Check if hovering over pet slots or EXIT button
            pets_area_start = scaled_arrow_width + scaled_margin
            pets_area_end = self.rect.width - scaled_arrow_width - scaled_exit_width - scaled_margin
            scaled_item_width = self.manager.scale_value(self.item_width)
            
            # Only check pet slots if we're in the pets area
            if pets_area_start <= relative_x < pets_area_end:
                for i in range(self.visible_pets):
                    pet_index = self.first_visible_pet + i
                    if pet_index < len(self.pets):
                        x_pos = pets_area_start + i * scaled_item_width - self.current_scroll_offset
                        if x_pos <= relative_x < x_pos + scaled_item_width:
                            self.hover_index = pet_index
                            break

            # Check if hovering over EXIT button (separate check)
            if self.hover_index == -1:
                exit_area_x = self.rect.width - scaled_arrow_width - scaled_exit_width - scaled_margin
                if exit_area_x <= relative_x < exit_area_x + scaled_exit_width:
                    self.hover_index = len(self.pets)  # Exit button index
        
        # Trigger redraw if any hover state changed
        if (old_hover_index != self.hover_index or 
            old_hover_left != self.hover_left_arrow or 
            old_hover_right != self.hover_right_arrow):
            self.needs_redraw = True
            # If arrow or EXIT hover state changed, rebuild static layer since they are drawn there
            exit_hover_changed = ((old_hover_index == len(self.pets)) != (self.hover_index == len(self.pets)))
            if exit_hover_changed or (old_hover_left != self.hover_left_arrow) or (old_hover_right != self.hover_right_arrow):
                self.static_layer = None

    def render_static_layer(self):
        """Render the static layer with arrows, exit button, and non-selected pets"""
        # Use screen dimensions for surface
        surface = pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
        colors = self.manager.get_theme_colors()
        
        # Get scaled dimensions
        scaled_arrow_width = self.manager.scale_value(self.base_arrow_width)
        scaled_exit_width = self.manager.scale_value(self.base_exit_width)
        scaled_margin = self.manager.scale_value(self.base_margin)
        
        # Create scaled rects for drawing (relative to this surface)
        left_arrow_rect = pygame.Rect(0, 0, scaled_arrow_width, self.rect.height)
        right_arrow_rect = pygame.Rect(self.rect.width - scaled_arrow_width, 0, scaled_arrow_width, self.rect.height)
        exit_rect = pygame.Rect(self.rect.width - scaled_arrow_width - scaled_exit_width - scaled_margin, 
                               0, scaled_exit_width, self.rect.height)
        
        # Draw left arrow
        self.draw_arrow(surface, left_arrow_rect, "left", self.left_arrow_pressed)
        
        # Draw right arrow  
        self.draw_arrow(surface, right_arrow_rect, "right", self.right_arrow_pressed)
        
        # Draw EXIT button
        self.draw_exit_button(surface, exit_rect)
        
        # Draw visible pets (static for non-focused AND non-active)
        scaled_pets_start_x = scaled_arrow_width + scaled_margin
        scaled_item_width = self.manager.scale_value(self.item_width)
        
        for i in range(self.visible_pets):
            pet_index = self.first_visible_pet + i
            if pet_index < len(self.pets):
                x_pos = scaled_pets_start_x + i * scaled_item_width - self.current_scroll_offset
                is_focused = (pet_index == self.selected_index)
                is_active = (pet_index == self.active_index)
                # Draw all pets in static layer - dynamic layer will overdraw focused/active ones with special effects
                self.draw_pet_slot(surface, x_pos, pet_index, scaled_item_width, is_focused=False)
                
        return surface
        
    def draw_arrow(self, surface, rect, direction, pressed):
        """Draw navigation arrow with consistent color logic"""
        from ui.ui_constants import PURPLE  # Import here to avoid circular imports
        
        colors = self.manager.get_theme_colors()
        
        # Use the rect as-is since it's already relative to the surface
        relative_rect = rect
        
        # Check if this arrow is being hovered
        is_hovered = ((direction == "left" and self.hover_left_arrow) or 
                     (direction == "right" and self.hover_right_arrow))
        
        # Arrows are never selected (selection state), only have focus highlighting
        bg_color = colors["bg"]
        fg_color = colors["fg"]
        line_color = colors.get("black", colors["fg"])  # Use black for borders, fallback to fg
        
        # Focus state: highlight border when hovered
        # Skip in touch mode - focus highlights are for keyboard/mouse navigation only
        if is_hovered and runtime_globals.INPUT_MODE != runtime_globals.TOUCH_MODE:
            line_color = colors["highlight"]
            fg_color = colors["highlight"]
        
        # Pressed state: brief visual feedback (color flip like the standard
        # Button). Keyed on the arrow's own pressed flag — the component-wide
        # self.clicked is never set on the arrow click path.
        if pressed:
            bg_color = colors["highlight"]
            fg_color = colors["bg"]
            line_color = colors["bg"]
        
        # Draw background using relative coordinates
        pygame.draw.rect(surface, bg_color, relative_rect, border_radius=self.manager.get_border_size())
        pygame.draw.rect(surface, line_color, relative_rect, width=self.manager.get_border_size(), 
                        border_radius=self.manager.get_border_size())
        
        # Draw triangle using relative coordinates
        center_x = relative_rect.centerx
        center_y = relative_rect.centery
        size = min(relative_rect.width, relative_rect.height) // 4
        
        if direction == "left":
            points = [
                (center_x + size//2, center_y - size),
                (center_x + size//2, center_y + size),
                (center_x - size//2, center_y)
            ]
        else:  # right
            points = [
                (center_x - size//2, center_y - size),
                (center_x - size//2, center_y + size),
                (center_x + size//2, center_y)
            ]
            
        pygame.draw.polygon(surface, fg_color, points)
        
    def draw_exit_button(self, surface, rect):
        """Draw EXIT button with consistent color logic"""
        from ui.ui_constants import PURPLE  # Import here to avoid circular imports
        
        colors = self.manager.get_theme_colors()
        is_selected = self.selected_index == len(self.pets)  # EXIT is selected for navigation
        is_hovered = self.hover_index == len(self.pets)  # Check hover state
        
        # Use the rect as-is since it's already relative to the surface
        relative_rect = rect
        
        # EXIT button can be selected (for keyboard navigation) but has no persistent selection state
        # Color logic: normal bg/fg, with focus highlighting
        bg_color = colors["bg"]
        fg_color = colors["fg"]
        line_color = colors["fg"]
        
        # Focus state: highlight border and text when hovered or keyboard focused
        # Skip in touch mode - focus highlights are for keyboard/mouse navigation only
        if (is_hovered or (is_selected and self.focused)) and runtime_globals.INPUT_MODE != runtime_globals.TOUCH_MODE:
            line_color = colors["highlight"]
            fg_color = colors["highlight"]
        
        # Pressed state: brief visual feedback
        if is_selected and self.clicked:
            bg_color = colors["highlight"]
            fg_color = colors["bg"]
            line_color = colors["bg"]

        # Draw using relative coordinates
        pygame.draw.rect(surface, bg_color, relative_rect, border_radius=self.manager.get_border_size())
        pygame.draw.rect(surface, line_color, relative_rect, width=self.manager.get_border_size(),
                        border_radius=self.manager.get_border_size())
        
        # Use centralized font method
        font = self.get_font("text")
        text_surface = font.render("EXIT", True, fg_color)
        text_rect = text_surface.get_rect(center=relative_rect.center)
        blit_with_cache(surface, text_surface, text_rect)
        
    def draw_pet_slot(self, surface, x_pos, pet_index, slot_width, is_focused=False):
        """Draw a pet slot with proper state colors"""
        
        colors = self.manager.get_theme_colors()
        slot_rect = pygame.Rect(x_pos, 0, slot_width, self.rect.height)
        
        is_selected = (pet_index == self.active_index)  # Currently selected for stats (persistent selection)
        is_hovered = (pet_index == self.hover_index)  # Mouse hover state
        # Focus: keyboard focus OR mouse hover
        # Skip in touch mode - focus highlights are for keyboard/mouse navigation only
        is_focus_highlighted = (is_focused or is_hovered) and runtime_globals.INPUT_MODE != runtime_globals.TOUCH_MODE
        
        # Color logic according to specifications:
        # Selection: swap bg/fg colors (persistent state)
        # Focus: highlight border and text (temporary highlight)
        
        if is_selected:
            # Selected state: swap bg and fg colors
            bg_color = colors["fg"]
            fg_color = colors["bg"]
            line_color = colors["black"]
        else:
            # Unselected state: normal bg and fg colors
            bg_color = colors["bg"]
            fg_color = colors["fg"]
            line_color = colors["black"]
            
        # Focus state: override border and text color with highlight
        if is_focus_highlighted:
            line_color = colors["highlight"]
            # Don't change text color to highlight for pets, keep it readable
            
        pygame.draw.rect(surface, bg_color, slot_rect, border_radius=self.manager.get_border_size())
        pygame.draw.rect(surface, line_color, slot_rect, width=self.manager.get_border_size(),
                        border_radius=self.manager.get_border_size())
        
        # Draw pet sprite (IDLE1 for non-active, current frame for active)
        if pet_index < len(self.pets) and pet_index in self.pet_sprites:
            try:
                is_animating = (pet_index == self.active_index)  # Only active pet animates
                frame_idx = self.current_frame if is_animating else 0
                sprite = self.pet_sprites[pet_index][frame_idx]
                sprite_rect = sprite.get_rect(center=slot_rect.center)
                blit_with_cache(surface, sprite, sprite_rect)
                
                # Draw module flag over the pet sprite
                if pet_index < len(self.pets):
                    pet = self.pets[pet_index]
                    flag_sprite = runtime_globals.game_module_flag.get(pet.module)
                    if flag_sprite:
                        try:
                            # Scale flag to match pet sprite size (nearest-neighbor for sharp pixels)
                            flag_size = sprite.get_size()
                            scaled_flag = pygame.transform.scale(flag_sprite, flag_size)
                            blit_with_cache(surface, scaled_flag, sprite_rect.topleft)
                        except Exception as e:
                            runtime_globals.game_console.log(f"[PetList] Error drawing module flag for pet {pet_index}: {e}")
            except Exception as e:
                runtime_globals.game_console.log(f"[PetList] Error drawing pet sprite {pet_index}: {e}")
                # Draw error placeholder
                pygame.draw.rect(surface, (255, 0, 0), slot_rect.inflate(-4, -4))
                font = self.get_font("text")
                error_text = font.render("ERR", True, (255, 255, 255))
                error_rect = error_text.get_rect(center=slot_rect.center)
                blit_with_cache(surface, error_text, error_rect)
    
    def draw_animated_highlight(self, surface):
        """Draw the animated highlight rectangle"""
        if not self.highlight_current_rect:
            return
            
        colors = self.manager.get_theme_colors()

        # Use a bright highlight color for the animation
        highlight_color = colors["highlight"]
        border_width = self.manager.get_border_size()
        border_radius = self.manager.get_border_size()

        # Draw only the border (no fill)
        pygame.draw.rect(
            surface,
            highlight_color,
            pygame.Rect(
                int(self.highlight_current_rect.x),
                int(self.highlight_current_rect.y),
                int(self.highlight_current_rect.width),
                int(self.highlight_current_rect.height)
            ),
            width=border_width,
            border_radius=border_radius
        )
    
    def render(self):
        """Render the PetList with static/dynamic layer optimization"""
        # Get static layer (cached)
        if self.static_layer is None:
            self.static_layer = self.render_static_layer()
            
        # Start with static layer
        surface = self.static_layer.copy()
        
        # Get scaled dimensions
        scaled_pets_start_x = self.manager.scale_value(self.base_arrow_width + self.base_margin)
        scaled_item_width = self.manager.scale_value(self.item_width)
        
        # Dynamic layer: Collect unique pet indices that need special rendering
        # Use a set to avoid drawing the same pet multiple times
        pets_to_redraw = set()
        
        # Add active pet (persistent selection with swapped colors)
        if 0 <= self.active_index < len(self.pets):
            pets_to_redraw.add(self.active_index)
        
        # Add selected pet (keyboard navigation position)
        if 0 <= self.selected_index < len(self.pets):
            pets_to_redraw.add(self.selected_index)
        
        # Add hovered pet (mouse hover)
        if 0 <= self.hover_index < len(self.pets):
            pets_to_redraw.add(self.hover_index)
        
        # Draw each collected pet only once, with all states combined
        for pet_index in pets_to_redraw:
            if self.first_visible_pet <= pet_index < self.first_visible_pet + self.visible_pets:
                x_pos = scaled_pets_start_x + (pet_index - self.first_visible_pet) * scaled_item_width - self.current_scroll_offset
                # draw_pet_slot will check all states internally (active, selected, hovered)
                # Pass keyboard focus state for selected index ONLY if not currently hovering with mouse
                # This prevents showing keyboard highlight when mouse is active elsewhere
                is_keyboard_focused = (self.focused and pet_index == self.selected_index and self.hover_index == -1)
                self.draw_pet_slot(surface, x_pos, pet_index, scaled_item_width, is_focused=is_keyboard_focused)
        
        # Redraw EXIT button if selected
        if self.selected_index == len(self.pets):
            scaled_arrow_width = self.manager.scale_value(self.base_arrow_width)
            scaled_exit_width = self.manager.scale_value(self.base_exit_width)
            scaled_margin = self.manager.scale_value(self.base_margin)
            exit_rect = pygame.Rect(self.rect.width - scaled_arrow_width - scaled_exit_width - scaled_margin, 
                                   0, scaled_exit_width, self.rect.height)
            self.draw_exit_button(surface, exit_rect)
        
        return surface
        
    def select_item(self):
        """Select the current item"""
        if self.selected_index == len(self.pets):
            # EXIT selected
            if self.on_exit_click:
                self.on_exit_click()
        elif self.selected_index < len(self.pets):
            # Pet selected - make it active and call callback
            self.set_active_pet(self.selected_index)
            if self.on_item_click:
                self.on_item_click(self.pets[self.selected_index])

    def handle_event(self, event):
        """Handle input events"""
        if not self.focused:
            return False
        
        # Handle tuple-based events
        if not isinstance(event, tuple) or len(event) != 2:
            return False
            
        event_type, event_data = event
            
        if event_type == "LEFT":
            self.select_previous()
            # Play sound only once for navigation
            runtime_globals.game_sound.play("menu")
            # For keyboard navigation, immediately activate the newly selected pet (original behavior)
            if self.selected_index < len(self.pets):
                self.set_active_pet(self.selected_index)
                if self.on_item_click:
                    self.on_item_click(self.pets[self.selected_index])
            self.needs_redraw = True
            return True
        elif event_type == "RIGHT":
            self.select_next()
            runtime_globals.game_sound.play("menu")
            # For keyboard navigation, immediately activate the newly selected pet (original behavior)
            if self.selected_index < len(self.pets):
                self.set_active_pet(self.selected_index)
                if self.on_item_click:
                    self.on_item_click(self.pets[self.selected_index])
            self.needs_redraw = True
            return True
        elif event_type == "DOWN":
            # Allow DOWN to move focus to next component (don't handle it here)
            return False
        elif event_type == "UP":
            # Allow UP to move focus to previous component (don't handle it here)
            return False
        elif event_type == "A":
            # Keyboard activation: set both active_index and selected_index (like LEFT/RIGHT do)
            self.clicked = True
            self.click_time = pygame.time.get_ticks()
            runtime_globals.game_sound.play("menu")
            
            if self.selected_index < len(self.pets):
                # Set both indices (matching BaseList behavior and LEFT/RIGHT handling)
                old_active = self.active_index
                self.active_index = self.selected_index  # Set selection state (persistent)
                self.static_layer = None  # Rebuild static layer
                self.needs_redraw = True
                
                # Notify callback if selection changed
                if old_active != self.active_index and self.on_item_click:
                    self.on_item_click(self.pets[self.selected_index])
            else:
                # EXIT button selected
                self.select_item()
                
            return True
        elif event == "B" or event == "RCLICK":
            runtime_globals.game_sound.play("cancel")
            # Handle back/cancel if needed
            return False
                
        return False
    
    def handle_mouse_click(self, mouse_pos, action):
        """Handle direct mouse clicks on specific positions"""
        if not (runtime_globals.INPUT_MODE in [runtime_globals.MOUSE_MODE, runtime_globals.TOUCH_MODE]):
            return False
        
        # Don't handle clicks during drag or if InputManager is dragging
        if hasattr(self, '_is_dragging') and self._is_dragging:
            return False
        
        if hasattr(runtime_globals.game_input, 'is_dragging') and runtime_globals.game_input.is_dragging():
            return False
        
        # Convert to component-relative coordinates using screen coordinates
        relative_x = mouse_pos[0] - self.rect.x
        relative_y = mouse_pos[1] - self.rect.y
        
        # Check if click is within component bounds
        if not (0 <= relative_x < self.rect.width and 0 <= relative_y < self.rect.height):
            return False
        
        # Get scaled dimensions
        scaled_arrow_width = self.manager.scale_value(self.base_arrow_width)
        scaled_exit_width = self.manager.scale_value(self.base_exit_width)
        scaled_margin = self.manager.scale_value(self.base_margin)
        
        # Check arrow clicks - behave like LEFT/RIGHT keys but also set selection for mouse
        if relative_x < scaled_arrow_width:  # Left arrow
            self.select_previous()
            self.left_arrow_pressed = True
            self.arrow_press_time = pygame.time.get_ticks()
            self.static_layer = None
            self.needs_redraw = True
            runtime_globals.game_sound.play("menu")
            # For mouse clicks on arrows, also set selection to the newly focused item
            if self.selected_index < len(self.pets):
                self.set_active_pet(self.selected_index)
                if self.on_item_click:
                    self.on_item_click(self.pets[self.selected_index])
            return True
            
        elif relative_x >= self.rect.width - scaled_arrow_width:  # Right arrow
            self.select_next()
            self.right_arrow_pressed = True
            self.arrow_press_time = pygame.time.get_ticks()
            self.static_layer = None
            self.needs_redraw = True
            runtime_globals.game_sound.play("menu")
            # For mouse clicks on arrows, also set selection to the newly focused item
            if self.selected_index < len(self.pets):
                self.set_active_pet(self.selected_index)
                if self.on_item_click:
                    self.on_item_click(self.pets[self.selected_index])
            return True
        
        # Check exit button click
        exit_area_x = self.rect.width - scaled_arrow_width - scaled_exit_width - scaled_margin
        if relative_x >= exit_area_x and relative_x < exit_area_x + scaled_exit_width:
            self.selected_index = len(self.pets)  # Select exit button
            self.needs_redraw = True
            if action == "LCLICK":
                self.select_item()  # Trigger exit
            runtime_globals.game_sound.play("menu")
            return True
        
        # Check pet slot clicks
        pets_area_x = scaled_arrow_width + scaled_margin
        scaled_pets_width = self.manager.scale_value(self.pets_width)
        
        if relative_x >= pets_area_x and relative_x < pets_area_x + scaled_pets_width:
            # Calculate which pet slot was clicked
            scaled_item_width = self.manager.scale_value(self.item_width)
            slot_x = relative_x - pets_area_x + self.current_scroll_offset
            pet_index = int(slot_x // scaled_item_width)
            
            # Adjust for first visible pet
            actual_pet_index = self.first_visible_pet + pet_index
            
            if 0 <= actual_pet_index < len(self.pets):
                self.selected_index = actual_pet_index
                self.needs_redraw = True
                runtime_globals.game_sound.play("menu")
                
                if action == "LCLICK":
                    self.set_active_pet(actual_pet_index)
                    if self.on_item_click:
                        self.on_item_click(self.pets[actual_pet_index])
                return True
        
        return False
    
    def handle_scroll(self, action):
        """Handle scroll wheel events - behave like LEFT/RIGHT keys"""
        if not (runtime_globals.INPUT_MODE == runtime_globals.MOUSE_MODE):
            return False

        # The UI manager hands on the whole ("SCROLL", {"direction": ...})
        # event; this compared it to "SCROLL_UP"/"SCROLL_DOWN" only, so the
        # wheel did nothing on the pet row.
        if isinstance(action, tuple) and len(action) == 2 and action[0] == "SCROLL":
            action = "SCROLL_" + str((action[1] or {}).get("direction", ""))

        if action == "SCROLL_UP":
            self.select_previous()
            self.needs_redraw = True
            runtime_globals.game_sound.play("menu")
            return True
        elif action == "SCROLL_DOWN":
            self.select_next()
            self.needs_redraw = True
            runtime_globals.game_sound.play("menu")
            return True
        
        return False
    
    def handle_drag(self, event):
        """Handle drag events for touch scrolling"""
        if not isinstance(event, tuple) or len(event) != 2:
            return False
        
        event_type, event_data = event
        
        if not (runtime_globals.INPUT_MODE in [runtime_globals.MOUSE_MODE, runtime_globals.TOUCH_MODE]):
            return False
        
        if event_type == "DRAG_START":
            # Store initial position for drag scrolling
            self._drag_start_scroll = self.first_visible_pet
            self._drag_start_selected = self.selected_index
            self._is_dragging = True
            # Store the initial drag position for threshold calculation
            mouse_pos = event_data.get("pos")
            if not mouse_pos:
                return False
            self._drag_start_pos = mouse_pos
            self._drag_accumulated = 0  # Track accumulated drag distance
            return True
            
        elif event_type == "DRAG_MOTION":
            # Calculate drag distance for scrolling only (no selection changes)
            if hasattr(self, '_drag_start_pos') and hasattr(self, '_is_dragging'):
                current_pos = event_data.get("pos")
                if not current_pos:
                    return False
                
                # Horizontal drag for scrolling
                dx = current_pos[0] - self._drag_start_pos[0]
                
                # Accumulate drag distance
                if not hasattr(self, '_drag_accumulated'):
                    self._drag_accumulated = 0
                self._drag_accumulated += dx
                
                # Convert drag distance to scroll movement
                scaled_item_width = self.manager.scale_value(self.item_width)
                if scaled_item_width > 0:
                    scroll_threshold = scaled_item_width  # Full pet width for scroll
                    
                    if abs(self._drag_accumulated) > scroll_threshold:
                        if self._drag_accumulated > 0:  # Drag right = scroll to show previous pets
                            if self.can_scroll_left():
                                old_first = self.first_visible_pet
                                self.first_visible_pet = max(0, self.first_visible_pet - 1)
                                if self.first_visible_pet != old_first:
                                    self.static_layer = None
                                    self.needs_redraw = True
                                    # Reset accumulated drag after successful scroll
                                    self._drag_accumulated = 0
                                    # Update drag start to prevent rapid scrolling
                                    self._drag_start_pos = current_pos
                                    return True
                        elif self._drag_accumulated < 0:  # Drag left = scroll to show next pets
                            if self.can_scroll_right():
                                old_first = self.first_visible_pet
                                self.first_visible_pet = min(len(self.pets) - self.visible_pets, 
                                                           self.first_visible_pet + 1)
                                if self.first_visible_pet != old_first:
                                    self.static_layer = None
                                    self.needs_redraw = True
                                    # Reset accumulated drag after successful scroll
                                    self._drag_accumulated = 0
                                    # Update drag start to prevent rapid scrolling
                                    self._drag_start_pos = current_pos
                                    return True
                
                # Update drag start position for next frame
                self._drag_start_pos = current_pos
                return True
                        
        elif event_type == "DRAG_END":
            # Clean up drag state
            if hasattr(self, '_drag_start_scroll'):
                delattr(self, '_drag_start_scroll')
            if hasattr(self, '_drag_start_selected'):
                delattr(self, '_drag_start_selected')
            if hasattr(self, '_is_dragging'):
                delattr(self, '_is_dragging')
            if hasattr(self, '_drag_start_pos'):
                delattr(self, '_drag_start_pos')
            if hasattr(self, '_drag_accumulated'):
                delattr(self, '_drag_accumulated')
            return True
        
        return False
    
    def handle_action_button(self):
        """Handle A button press - could be selection or arrow click based on mouse position"""
        if not (runtime_globals.INPUT_MODE in [runtime_globals.MOUSE_MODE, runtime_globals.TOUCH_MODE]):
            # No mouse/touch - just select current item
            self.select_item()
            return
            
        # Check if mouse is over a clickable area
        mouse_pos = runtime_globals.game_input.get_mouse_position()
        relative_x = mouse_pos[0] - self.rect.x
        relative_y = mouse_pos[1] - self.rect.y
        
        # Check if mouse is within component bounds
        if not (0 <= relative_x < self.rect.width and 0 <= relative_y < self.rect.height):
            self.select_item()  # Fallback to normal selection
            return
        
        # Get scaled dimensions
        scaled_arrow_width = self.manager.scale_value(self.base_arrow_width)
        
        # Check arrow areas - these navigate like LEFT/RIGHT keys when mouse is enabled
        if relative_x < scaled_arrow_width:  # Left arrow
            self.select_previous()
            self.left_arrow_pressed = True
            self.arrow_press_time = pygame.time.get_ticks()
            self.static_layer = None
            self.needs_redraw = True
            return
        elif relative_x >= self.rect.width - scaled_arrow_width:  # Right arrow
            self.select_next()
            self.right_arrow_pressed = True
            self.arrow_press_time = pygame.time.get_ticks()
            self.static_layer = None
            self.needs_redraw = True
            return
            
        # Otherwise, select the current item
        self.select_item()
    
    def select_previous(self):
        """Select previous item (navigation only, no activation)"""
        if self.selected_index > 0:
            old_index = self.selected_index
            self.selected_index -= 1
            # Animate left arrow 
            self.left_arrow_pressed = True
            self.arrow_press_time = pygame.time.get_ticks()
            # Don't auto-activate pets, just navigate
            self.ensure_visible(self.selected_index)
            self.static_layer = None  # Refresh static layer
            # Individual component highlighting - trigger redraw
            self.needs_redraw = True
            
    def select_next(self):
        """Select next item (navigation only, no activation)"""
        if self.selected_index < len(self.pets):  # Include EXIT button
            old_index = self.selected_index
            self.selected_index += 1
            # Animate right arrow
            self.right_arrow_pressed = True
            self.arrow_press_time = pygame.time.get_ticks()
            # Don't auto-activate pets, just navigate
            if self.selected_index < len(self.pets):
                self.ensure_visible(self.selected_index)
            self.static_layer = None  # Refresh static layer
            # Individual component highlighting - no global highlight system
            self.needs_redraw = True
    
    def update_component_highlight(self, from_index, to_index):
        """Update component highlighting when selection changes - individual component system"""
        # Individual component highlighting - just trigger redraw
        self.needs_redraw = True
            
    def ensure_visible(self, index):
        """Ensure the specified index is visible"""
        if index < self.first_visible_pet:
            self.first_visible_pet = index
            self.static_layer = None
        elif index >= self.first_visible_pet + self.visible_pets:
            self.first_visible_pet = index - self.visible_pets + 1
            self.static_layer = None
        
    def can_scroll_left(self):
        """Check if can scroll left"""
        return self.first_visible_pet > 0
        
    def can_scroll_right(self):
        """Check if can scroll right"""
        return self.first_visible_pet + self.visible_pets < len(self.pets)
        
    def scroll_left(self):
        """Scroll left by one page"""
        if self.can_scroll_left():
            self.first_visible_pet = max(0, self.first_visible_pet - self.visible_pets)
            self.static_layer = None
            
    def scroll_right(self):
        """Scroll right by one page"""
        if self.can_scroll_right():
            self.first_visible_pet = min(len(self.pets) - self.visible_pets, 
                                       self.first_visible_pet + self.visible_pets)
            self.static_layer = None
        
    def get_selected_pet(self):
        """Get the currently selected pet or None if EXIT is selected"""
        if 0 <= self.selected_index < len(self.pets):
            return self.pets[self.selected_index]
        return None
    
    def on_focus_gained(self):
        """Called when component gains focus"""
        self.focused = True
        self.needs_redraw = True
        # Individual component highlighting - no global system
    
    def on_focus_lost(self):
        """Called when component loses focus"""
        self.focused = False
        self.needs_redraw = True
        # Clear any component-specific highlight animations
        self.highlight_animating = False
        self.highlight_current_rect = None
    
    def get_mouse_sub_rect(self, mouse_pos):
        """Get the sub-component rect at the mouse position"""
        # Convert to component-relative coordinates
        relative_x = mouse_pos[0] - self.rect.x
        relative_y = mouse_pos[1] - self.rect.y
        
        # Check if mouse is within component bounds
        if not (0 <= relative_x < self.rect.width and 0 <= relative_y < self.rect.height):
            return None
        
        # Get scaled dimensions
        scaled_arrow_width = self.manager.scale_value(self.base_arrow_width)
        scaled_exit_width = self.manager.scale_value(self.base_exit_width)
        scaled_margin = self.manager.scale_value(self.base_margin)
        
        # Check left arrow
        if relative_x < scaled_arrow_width and self.selected_index > 0:
            return pygame.Rect(self.rect.x, self.rect.y, scaled_arrow_width, self.rect.height)
        
        # Check right arrow
        if relative_x >= self.rect.width - scaled_arrow_width and self.selected_index < len(self.pets):
            return pygame.Rect(self.rect.x + self.rect.width - scaled_arrow_width, self.rect.y, 
                             scaled_arrow_width, self.rect.height)
        
        # Check EXIT button
        exit_area_x = self.rect.width - scaled_arrow_width - scaled_exit_width - scaled_margin
        if exit_area_x <= relative_x < exit_area_x + scaled_exit_width:
            return pygame.Rect(self.rect.x + exit_area_x, self.rect.y, scaled_exit_width, self.rect.height)
        
        # Check pet slots
        pets_area_start = scaled_arrow_width + scaled_margin
        scaled_item_width = self.manager.scale_value(self.item_width)
        
        for i in range(self.visible_pets):
            pet_index = self.first_visible_pet + i
            if pet_index < len(self.pets):
                x_pos = pets_area_start + i * scaled_item_width - self.current_scroll_offset
                if x_pos <= relative_x < x_pos + scaled_item_width:
                    # Return the pet slot rect in screen coordinates
                    return pygame.Rect(self.rect.x + x_pos, self.rect.y, scaled_item_width, self.rect.height)
        
        # Return None if mouse is not over any specific sub-component
        return None
    
    def get_focused_sub_rect(self):
        """Get the rect of the currently focused sub-component"""
        element_rect = self.get_element_rect(self.selected_index)
        if element_rect:
            # Convert to screen coordinates
            return pygame.Rect(
                self.rect.x + element_rect.x,
                self.rect.y + element_rect.y,
                element_rect.width,
                element_rect.height
            )
        return self.rect
