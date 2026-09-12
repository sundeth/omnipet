import pygame

from ui.components.component import UIComponent
from core import runtime_globals
from utils.sprite_utils import load_pet_sprites
from utils.module_utils import get_module
from utils.pygame_utils import blit_with_cache, blit_with_shadow
import core.constants as constants

SPRITE_BUFFER = 10

class DigidexList(UIComponent):
    """A vertical / windowed list component for the Digidex.

    Responsibilities:
    - Render a scrollable vertical list of pets with sprites
    - Manage on-demand sprite loading with LRU window
    - Provide navigation buttons (UP/DOWN icons, Tree, Back)
    - Support drag scrolling
    """
    def __init__(self, x, y, width, height, unknown_sprite, sprite_size=None):
        super().__init__(x, y, width, height)
        self.pets = []
        self.unknown_sprite = unknown_sprite
        self.sprite_size = sprite_size or int(48 * runtime_globals.UI_SCALE)
        self.focusable = True
        self.on_selection_callback = None
        self.on_tree_callback = None
        self.on_back_callback = None
        
        # Selection and scrolling
        self.selected_index = 0
        self.scroll_offset = 0
        self.hover_index = -1  # Mouse hover tracking
        
        # Drag state
        self._is_dragging = False
        self._drag_start_pos = None
        self._drag_start_scroll = 0
        self._drag_accumulated = 0

    def set_pets(self, pets):
        self.pets = pets
        self.selected_index = min(self.selected_index, len(pets) - 1) if pets else 0
        self.needs_redraw = True

    def navigate_up(self):
        """Navigate up in the list"""
        if self.selected_index > 0:
            self.selected_index -= 1
            self.needs_redraw = True
    
    def navigate_down(self):
        """Navigate down in the list"""
        if self.selected_index < len(self.pets) - 1:
            self.selected_index += 1
            self.needs_redraw = True

    def update_sprite_cache(self):
        # Keep only nearby sprites loaded to save memory
        # Cache based on visible scroll area, not just selected index
        if not self.manager:
            return
        
        # Use base coordinates for calculations
        base_item_height = 50
        max_visible = max(1, self.base_rect.height // base_item_height)
        
        # Cache from scroll offset minus buffer to scroll offset plus visible + buffer
        min_index = max(0, self.scroll_offset - SPRITE_BUFFER)
        max_index = min(len(self.pets), self.scroll_offset + max_visible + SPRITE_BUFFER)

        for i, pet in enumerate(self.pets):
            if i < min_index or i >= max_index:
                # Don't unload sprites for unknown pets (they use unknown_sprite)
                if pet.sprite and pet.sprite != self.unknown_sprite:
                    pet.sprite = None
            else:
                if not pet.sprite:
                    if pet.known:
                        # Load actual sprite for known pets
                        try:
                            module = get_module(pet.module)
                            sprites_dict = load_pet_sprites(
                                pet.name,
                                module.folder_path,
                                module.name_format,
                                size=(self.sprite_size, self.sprite_size),
                                primary_sprite_format=getattr(module, 'primary_sprite_format', 'Color'),
                                secondary_sprite_format=getattr(module, 'secondary_sprite_format', 'HD'),
                            )
                            # Frame keys are ints (see load_sprites_from_directory)
                            frame0 = sprites_dict.get(0) or sprites_dict.get("0")
                            pet.sprite = frame0 if frame0 is not None else self.unknown_sprite
                        except Exception as e:
                            runtime_globals.game_console.log(f"[DigidexList] Failed to load sprite {pet.name}: {e}")
                    else:
                        # Unknown pet - set unknown sprite
                        pet.sprite = self.unknown_sprite

    def update(self):
        super().update()
        
        # Only update if visible
        if not self.visible:
            return
        
        # Handle mouse hover for list item highlighting
        self.handle_mouse_hover()
        
        # Track index changes
        old_index = getattr(self, '_last_index', -1)
        old_scroll = getattr(self, '_last_scroll', -1)
        
        if old_index != self.selected_index or old_scroll != self.scroll_offset:
            self.needs_redraw = True
            self._last_index = self.selected_index
            self._last_scroll = self.scroll_offset
            # Only update sprite cache when selection or scroll changes
            self.update_sprite_cache()

    def handle_mouse_hover(self):
        """Handle mouse hover for highlighting list items (separate from keyboard focus)"""
        if not (runtime_globals.INPUT_MODE in [runtime_globals.MOUSE_MODE, runtime_globals.TOUCH_MODE]):
            old_hover = getattr(self, 'hover_index', -1)
            self.hover_index = -1
            if old_hover != -1:
                self.needs_redraw = True
            return
        
        # Disable hover during drag
        if hasattr(self, '_is_dragging') and self._is_dragging:
            old_hover = getattr(self, 'hover_index', -1)
            self.hover_index = -1
            if old_hover != -1:
                self.needs_redraw = True
            return
        
        # Don't update hover if in keyboard navigation mode (UI manager controls this)
        if self.manager and hasattr(self.manager, 'keyboard_navigation_mode') and self.manager.keyboard_navigation_mode:
            return
        
        # Get mouse position in UI coordinates from the manager
        if not self.manager:
            return
        
        mouse_ui_pos = self.manager.screen_to_ui_pos(runtime_globals.game_input.get_mouse_position())
        if not mouse_ui_pos:
            old_hover = getattr(self, 'hover_index', -1)
            self.hover_index = -1
            if old_hover != -1:
                self.needs_redraw = True
            return
        
        # Calculate relative position in base coordinates
        relative_x = mouse_ui_pos[0] - self.base_rect.x
        relative_y = mouse_ui_pos[1] - self.base_rect.y
        
        old_hover = getattr(self, 'hover_index', -1)
        self.hover_index = -1
        
        # Check if mouse is within component bounds (base coordinates)
        if not (0 <= relative_x < self.base_rect.width and 0 <= relative_y < self.base_rect.height):
            if old_hover != -1:
                self.needs_redraw = True
            return
        
        # Check which list item is under the mouse (base coordinates)
        if not self.pets:
            return
        
        base_item_height = 50
        item_index = int(relative_y / base_item_height) + self.scroll_offset
        
        if 0 <= item_index < len(self.pets):
            self.hover_index = item_index
            # Only change selection on hover if not in keyboard mode
            if self.selected_index != item_index:
                self.selected_index = item_index
                self.needs_redraw = True
        
        if old_hover != self.hover_index:
            self.needs_redraw = True
    
    def get_mouse_sub_rect(self, mouse_pos):
        """Get the sub-component rect at the mouse position"""
        if not self.manager:
            return None
        
        # Convert screen coordinates to UI coordinates
        mouse_ui_pos = self.manager.screen_to_ui_pos(mouse_pos)
        if not mouse_ui_pos:
            return None
        
        # Calculate relative position in base coordinates
        relative_x = mouse_ui_pos[0] - self.base_rect.x
        relative_y = mouse_ui_pos[1] - self.base_rect.y
        
        # Check if mouse is within component bounds (base coordinates)
        if not (0 <= relative_x < self.base_rect.width and 0 <= relative_y < self.base_rect.height):
            return None
        
        # Check list items
        if self.pets:
            base_item_height = 50
            item_index = int(relative_y / base_item_height) + self.scroll_offset
            
            if 0 <= item_index < len(self.pets):
                # Calculate rect in base coordinates
                item_y = (item_index - self.scroll_offset) * base_item_height
                base_item_rect = pygame.Rect(
                    self.base_rect.x,
                    self.base_rect.y + item_y,
                    self.base_rect.width,
                    base_item_height
                )
                # Convert to screen coordinates
                return self.manager.ui_to_screen_rect(base_item_rect)
        
        # Mouse is in component but not over anything specific
        return self.rect
    
    def get_focused_sub_rect(self):
        """Get the rect of the currently focused/selected list item"""
        if not self.pets or self.selected_index < 0 or self.selected_index >= len(self.pets):
            return self.rect
        
        if not self.manager:
            return self.rect
        
        # Calculate the rect of the selected item in base coordinates
        base_item_height = 50
        item_y = (self.selected_index - self.scroll_offset) * base_item_height
        
        base_item_rect = pygame.Rect(
            self.base_rect.x,
            self.base_rect.y + item_y,
            self.base_rect.width,
            base_item_height
        )
        
        # Convert to screen coordinates
        return self.manager.ui_to_screen_rect(base_item_rect)
    
    def handle_event(self, event):
        # Handle list navigation - tuple-based events
        if not isinstance(event, tuple) or len(event) != 2:
            return False
            
        event_type, event_data = event
        
        if event_type == "UP":
            self.navigate_up()
            runtime_globals.game_sound.play("menu")
            return True
        elif event_type == "DOWN":
            self.navigate_down()
            runtime_globals.game_sound.play("menu")
            return True
        elif event_type == "A":
            # Select current pet - trigger callback
            selected = self.get_selected_pet()
            if selected and selected.known and self.on_selection_callback:
                self.on_selection_callback(selected)
                runtime_globals.game_sound.play("menu")
            return True
        elif event_type == "SCROLL":
            # Handle wheel directly instead of relying on the manager's
            # focused/hover fallback chain.
            return self.handle_scroll(event)
        elif event_type in ("DRAG_START", "DRAG_MOTION", "DRAG_END"):
            return self.handle_drag(event)
        return False
    
    def handle_mouse_click(self, mouse_pos, action):
        """Handle direct mouse clicks on list items"""
        if not (runtime_globals.INPUT_MODE in [runtime_globals.MOUSE_MODE, runtime_globals.TOUCH_MODE]):
            return False
        
        # Don't handle clicks during drag
        if hasattr(self, '_is_dragging') and self._is_dragging:
            return False
        
        if hasattr(runtime_globals.game_input, 'is_dragging') and runtime_globals.game_input.is_dragging():
            return False
        
        if not self.manager:
            return False
        
        # Convert screen coordinates to UI coordinates
        mouse_ui_pos = self.manager.screen_to_ui_pos(mouse_pos)
        if not mouse_ui_pos:
            return False
        
        # Calculate relative position in base coordinates
        relative_x = mouse_ui_pos[0] - self.base_rect.x
        relative_y = mouse_ui_pos[1] - self.base_rect.y
        
        # Check if click is within component bounds (base coordinates)
        if not (0 <= relative_x < self.base_rect.width and 0 <= relative_y < self.base_rect.height):
            return False
        
        # Check which list item was clicked (base coordinates)
        if self.pets:
            base_item_height = 50
            item_index = int(relative_y / base_item_height) + self.scroll_offset
            
            if 0 <= item_index < len(self.pets):
                clicked_pet = self.pets[item_index]
                
                # Single click opens tree view if pet is known
                if clicked_pet.known and self.on_selection_callback:
                    self.on_selection_callback(clicked_pet)
                    runtime_globals.game_sound.play("menu")
                    return True
                
                # Update selection even if not known (handled by hover, but play sound)
                if item_index != self.selected_index:
                    runtime_globals.game_sound.play("menu")
                return True
        
        return False
    
    def handle_scroll(self, action):
        """Handle scroll wheel events for list navigation.

        The UI manager passes the full ("SCROLL", {"direction": "UP"/"DOWN"})
        event tuple; legacy "SCROLL_UP"/"SCROLL_DOWN" strings are still
        accepted for safety.
        """
        if not (runtime_globals.INPUT_MODE in [runtime_globals.MOUSE_MODE, runtime_globals.TOUCH_MODE]):
            return False

        direction = None
        if isinstance(action, tuple) and len(action) == 2 and action[0] == "SCROLL":
            direction = (action[1] or {}).get("direction")
        elif action == "SCROLL_UP":
            direction = "UP"
        elif action == "SCROLL_DOWN":
            direction = "DOWN"

        if direction == "UP":
            self.navigate_up()
            runtime_globals.game_sound.play("menu")
            return True
        elif direction == "DOWN":
            self.navigate_down()
            runtime_globals.game_sound.play("menu")
            return True

        return False
    
    def handle_drag(self, event):
        """Handle drag events for vertical scrolling"""
        if not isinstance(event, tuple) or len(event) != 2:
            return False
        
        event_type, event_data = event
        
        if not (runtime_globals.INPUT_MODE in [runtime_globals.MOUSE_MODE, runtime_globals.TOUCH_MODE]):
            return False
        
        if not self.manager:
            return False
        
        if event_type == "DRAG_START":
            mouse_pos = event_data.get("pos")
            if not mouse_pos:
                return False
                
            mouse_ui_pos = self.manager.screen_to_ui_pos(mouse_pos)
            if not mouse_ui_pos:
                return False
            
            relative_x = mouse_ui_pos[0] - self.base_rect.x
            relative_y = mouse_ui_pos[1] - self.base_rect.y
            
            # Check if mouse is within component bounds (base coordinates)
            if not (0 <= relative_x < self.base_rect.width and 0 <= relative_y < self.base_rect.height):
                return False
            
            # Start drag
            self._drag_start_scroll = self.scroll_offset
            self._drag_start_pos = mouse_pos
            self._drag_accumulated = 0
            self._is_dragging = True
            return True
        
        elif event_type == "DRAG_MOTION" and self._is_dragging:
            current_pos = event_data.get("pos")
            if not current_pos:
                return False
            dy = current_pos[1] - self._drag_start_pos[1]
            
            self._drag_accumulated += dy
            
            # Calculate item height in screen pixels (scaled)
            base_item_height = 50
            item_height = int(base_item_height * self.manager.ui_scale)
            
            # Use 30% of item height as threshold for more responsive dragging
            scroll_threshold = item_height * 0.3
            
            if abs(self._drag_accumulated) > scroll_threshold:
                if self._drag_accumulated > 0:  # Drag down = scroll up in list
                    if self.scroll_offset > 0:
                        self.scroll_offset -= 1
                        self.needs_redraw = True
                        self._drag_accumulated = 0
                        self._drag_start_pos = current_pos
                elif self._drag_accumulated < 0:  # Drag up = scroll down in list
                    max_scroll = max(0, len(self.pets) - self._get_max_visible())
                    if self.scroll_offset < max_scroll:
                        self.scroll_offset += 1
                        self.needs_redraw = True
                        self._drag_accumulated = 0
                        self._drag_start_pos = current_pos
            
            self._drag_start_pos = current_pos
            return True
        
        elif event_type == "DRAG_END":
            self._is_dragging = False
            self._drag_start_pos = None
            self._drag_accumulated = 0
            return True
        
        return False
    
    def _get_max_visible(self):
        """Calculate how many items fit in the visible area"""
        base_item_height = 50
        height = self.base_rect.height if self.base_rect else self.rect.height
        return max(1, height // base_item_height)

    def render(self):
        # Create surface at scaled resolution
        surface = pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
        
        if not self.pets:
            return surface
        
        # Get UI scale
        ui_scale = self.manager.ui_scale if self.manager else 1
        
        # Calculate layout (base values, will be scaled)
        base_item_height = 50
        base_icon_size = 40
        base_left_padding = 8
        
        # Scaled values
        item_height = int(base_item_height * ui_scale)
        icon_size = int(base_icon_size * ui_scale)
        left_padding = int(base_left_padding * ui_scale)
        
        list_x = 0
        list_width = self.rect.width
        max_visible = max(1, self.rect.height // item_height)
        
        # Adjust scroll to keep selected visible
        if self.selected_index < self.scroll_offset:
            self.scroll_offset = self.selected_index
        elif self.selected_index >= self.scroll_offset + max_visible:
            self.scroll_offset = self.selected_index - max_visible + 1
        
        # Get theme colors and fonts (scaled).  Use the UI system's default
        # text size for both lines -- the previous 14/10 custom sizes were
        # too small to read comfortably.
        colors = self.get_colors()
        font = self.get_font("text")
        small_font = self.get_font("text")
        
        # Draw visible items
        for idx in range(self.scroll_offset, min(self.scroll_offset + max_visible, len(self.pets))):
            pet = self.pets[idx]
            y_pos = (idx - self.scroll_offset) * item_height
            
            # Draw sprite
            if pet.sprite:
                scaled_sprite = pygame.transform.scale(pet.sprite, (icon_size, icon_size))
                blit_with_cache(surface, scaled_sprite, (list_x + left_padding, y_pos + int(5 * ui_scale)))
            
            # Draw name and info with shadow
            name_text = font.render(pet.name[:15], True, colors["fg"])
            blit_with_shadow(surface, name_text, (list_x + left_padding + icon_size + int(5 * ui_scale), y_pos + int(8 * ui_scale)))
            
            info_text = small_font.render(f"{pet.attribute if pet.attribute != '' else 'Free'} | Stage {constants.STAGES[pet.stage]}", True, (200, 200, 200))
            blit_with_shadow(surface, info_text, (list_x + left_padding + icon_size + int(5 * ui_scale), y_pos + int(28 * ui_scale)))

            # Friend pets carry a small tag in the top-right of the row
            if getattr(pet, 'availability', 'Normal') == 'Friend':
                tag_text = small_font.render("Friend", True, (120, 220, 120))
                blit_with_shadow(surface, tag_text,
                                 (list_x + list_width - tag_text.get_width() - int(6 * ui_scale),
                                  y_pos + int(4 * ui_scale)))
            
            # Highlight selected or hovered item
            is_hovered = (idx == self.hover_index)
            is_selected = (idx == self.selected_index)
            
            if is_selected or (is_hovered and self.focused):
                # Use highlight color if hovered and focused, or line color if just selected
                # Fallback to line color if highlight not available
                # Skip focus highlighting in touch mode - it's for keyboard/mouse navigation only
                highlight_color = colors.get("highlight", colors["line"])
                show_focus = (is_hovered and self.focused) and runtime_globals.INPUT_MODE != runtime_globals.TOUCH_MODE
                border_color = highlight_color if show_focus else colors["line"]
                border_width = max(1, int(2 * ui_scale))
                pygame.draw.rect(surface, border_color, (list_x, y_pos, list_width, item_height), border_width)
        
        return surface

    def get_selected_pet(self):
        if 0 <= self.selected_index < len(self.pets):
            return self.pets[self.selected_index]
        return None
