"""
Party Grid Component - Grid display for party pets with dynamic sizing
"""
import pygame
import math
from ui.components.grid import Grid, GridItem
from core import game_globals, runtime_globals
import core.constants as constants
from utils.pygame_utils import blit_with_cache


def get_grid_dimensions(max_pets):
    """Calculate optimal rows/cols based on MAX_PETS and screen aspect ratio"""
    if max_pets == 1:
        return (1, 1)
    elif max_pets == 2:
        if runtime_globals.SCREEN_WIDTH >= runtime_globals.SCREEN_HEIGHT:
            return (1, 2)
        else:
            return (2, 1)
    else:
        if runtime_globals.SCREEN_WIDTH >= runtime_globals.SCREEN_HEIGHT:
            aspect_ratio = runtime_globals.SCREEN_WIDTH / runtime_globals.SCREEN_HEIGHT
            cols = math.ceil(math.sqrt(max_pets))
            if aspect_ratio * cols > (cols + 1):
                cols = int(min((aspect_ratio * cols), max_pets))
            rows = math.ceil(max_pets / cols)
            if (rows - 1) * cols >= max_pets:
                rows -= 1
        else:
            aspect_ratio = runtime_globals.SCREEN_HEIGHT / runtime_globals.SCREEN_WIDTH
            rows = math.ceil(math.sqrt(max_pets))
            if aspect_ratio * rows > (rows + 1):
                rows = int(min((aspect_ratio * rows), max_pets))
            cols = math.ceil(max_pets / rows)
            if (cols - 1) * rows >= max_pets:
                cols -= 1
        return (rows, cols)


class PartyGrid(Grid):
    """Grid component specialized for displaying party pets"""
    
    def __init__(self, x, y, width, height):
        # Calculate grid dimensions based on MAX_PETS
        max_pets = max(constants.MAX_PETS, len(game_globals.pet_list))
        rows, cols = get_grid_dimensions(max_pets)
        
        super().__init__(x, y, width, height, rows, cols)
        
        self.max_pets = max_pets
        self.empty_slot_text = "+"
        
        # Visual customization
        self.cell_padding = 4
        self.show_empty_slots = True
        self.attribute_colors = constants.ATTR_COLORS
        
        # Recalculate cell dimensions with new padding
        self.cell_width = (width - (self.cell_padding * (cols + 1))) // cols
        self.cell_height = (height - (self.cell_padding * (rows + 1))) // rows
        
        # Text scrolling system (separate layer for performance)
        self.text_layer_cache = {}  # Cache text surfaces per cell: {cell_index: surface}
        self.text_scroll_offsets = {}  # Scroll offsets per cell: {cell_index: offset}
        self.text_scroll_directions = {}  # Scroll directions per cell: {cell_index: direction}
        self.text_scroll_pause_timers = {}  # Pause timers per cell: {cell_index: timer}
        self.scroll_speed = 0.5  # pixels per frame
        self.scroll_pause_duration = 5  # frames to pause at each end
        self.last_scroll_update = 0
        self.text_needs_update = set()  # Set of cell indices that need text redraw
        
        runtime_globals.game_console.log(f"[PartyGrid] Created {rows}x{cols} grid for {max_pets} pets")
        
    def refresh_from_party(self):
        """Refresh grid items from current pet_list"""
        items = []
        
        # Add existing pets
        for pet in game_globals.pet_list:
            # Get pet sprite
            sprite = None
            if pet in runtime_globals.pet_sprites:
                sprite_list = runtime_globals.pet_sprites[pet]
                if sprite_list:
                    sprite = sprite_list[0]
            
            # Create grid item with pet data
            item = GridItem(sprite=sprite, text=pet.name, data=pet)
            items.append(item)
        
        # Add empty slots up to MAX_PETS
        while len(items) < self.max_pets:
            items.append(GridItem(sprite=None, text=self.empty_slot_text, data=None))
        
        self.set_items(items)
        
        # Clear text caches when items change
        self._clear_text_caches()
    
    def _clear_text_caches(self):
        """Clear all text-related caches"""
        self.text_layer_cache.clear()
        self.text_scroll_offsets.clear()
        self.text_scroll_directions.clear()
        self.text_scroll_pause_timers.clear()
        self.text_needs_update.clear()
    
    def _initialize_text_scrolling(self, cell_index, text, text_width, available_width):
        """Initialize scrolling parameters for a cell"""
        self.text_scroll_offsets[cell_index] = 0
        self.text_scroll_directions[cell_index] = 1  # 1 for right, -1 for left
        self.text_scroll_pause_timers[cell_index] = self.scroll_pause_duration
        
        # Only mark for updates if text actually needs scrolling
        if text_width > available_width:
            self.text_needs_update.add(cell_index)
    
    def update(self):
        """Update text scrolling animation"""
        super().update()
        
        if not self.visible or not self.text_needs_update:
            return
        
        current_time = pygame.time.get_ticks()
        
        # Update scrolling at ~60 FPS
        if current_time - self.last_scroll_update < 16:
            return
        
        self.last_scroll_update = current_time
        
        # Get current page items for context
        current_items = self.get_current_page_items()
        
        # Update each cell that needs scrolling
        for cell_index in list(self.text_needs_update):
            if cell_index >= len(current_items):
                continue
            
            item = current_items[cell_index]
            if not item or not item.text or not item.data:  # Skip empty slots and those without pets
                continue
            
            # Get text dimensions
            if not self.manager:
                continue
                
            # Same size the Button component uses for its text
            font = self.get_font("text")
            text_surface = font.render(item.text, True, (255, 255, 255))
            text_width = text_surface.get_width()
            available_width = int(self.cell_width * self.manager.ui_scale) - int(4 * self.manager.ui_scale)
            
            # Skip if text doesn't need scrolling
            if text_width <= available_width:
                self.text_needs_update.discard(cell_index)
                continue
            
            # Handle pause timer
            if self.text_scroll_pause_timers.get(cell_index, 0) > 0:
                self.text_scroll_pause_timers[cell_index] -= 1
                continue
            
            # Update scroll offset
            current_offset = self.text_scroll_offsets.get(cell_index, 0)
            direction = self.text_scroll_directions.get(cell_index, 1)
            
            new_offset = current_offset + (direction * self.scroll_speed)
            
            # Check boundaries and reverse direction
            max_offset = text_width - available_width
            if new_offset >= max_offset:
                new_offset = max_offset
                self.text_scroll_directions[cell_index] = -1
                self.text_scroll_pause_timers[cell_index] = self.scroll_pause_duration
            elif new_offset <= 0:
                new_offset = 0
                self.text_scroll_directions[cell_index] = 1
                self.text_scroll_pause_timers[cell_index] = self.scroll_pause_duration
            
            self.text_scroll_offsets[cell_index] = new_offset
            
            # Mark that we need to redraw the text layer for this cell
            if cell_index in self.text_layer_cache:
                del self.text_layer_cache[cell_index]
            
            # Force grid redraw since text has changed
            self.needs_redraw = True
        
    def _render_text_layer(self, item_index, item, cell_rect):
        """Render text layer for a specific cell with scrolling support"""
        if not self.manager or not item.text:
            return None
        
        # Same size the Button component uses for its text
        font = self.get_font("text")
        text_color = (255, 255, 255)
        
        # Use scaled cell dimensions
        cell_width = int(self.cell_width * self.manager.ui_scale)
        cell_height = int(self.cell_height * self.manager.ui_scale)
        
        # Empty slot - show "+" centered
        if not item.data:
            text_surface = font.render("+", True, text_color)
            text_rect = text_surface.get_rect()
            text_rect.center = (cell_width // 2, cell_height // 2)
            
            layer = pygame.Surface((cell_width, cell_height), pygame.SRCALPHA)
            blit_with_cache(layer, text_surface, text_rect.topleft)
            return layer
        
        # Pet name at bottom with scrolling
        text_surface = font.render(item.text, True, text_color)
        text_width = text_surface.get_width()
        available_width = cell_width - int(4 * self.manager.ui_scale)
        
        # Create text layer surface
        layer = pygame.Surface((cell_width, cell_height), pygame.SRCALPHA)
        
        # Check if text needs scrolling
        if text_width > available_width:
            # Initialize scrolling if not already done
            if item_index not in self.text_scroll_offsets:
                self._initialize_text_scrolling(item_index, item.text, text_width, available_width)
            
            # Create scrolling text container
            scroll_container = pygame.Surface((available_width, text_surface.get_height()), pygame.SRCALPHA)
            
            # Get current scroll offset
            scroll_offset = self.text_scroll_offsets.get(item_index, 0)
            
            # Blit with offset
            blit_with_cache(scroll_container, text_surface, (-int(scroll_offset), 0))
            
            # Position at bottom center of cell
            text_rect = scroll_container.get_rect()
            text_rect.centerx = cell_width // 2
            text_rect.bottom = cell_height - int(4 * self.manager.ui_scale)
            blit_with_cache(layer, scroll_container, text_rect.topleft)
        else:
            # Text fits - render normally without scrolling
            text_rect = text_surface.get_rect()
            text_rect.centerx = cell_width // 2
            text_rect.bottom = cell_height - int(4 * self.manager.ui_scale)
            blit_with_cache(layer, text_surface, text_rect.topleft)
        
        return layer
    
    def render(self):
        """Render the party grid with attribute-colored backgrounds"""
        # Reuse a cached render surface to avoid per-frame allocations
        target_size = (self.rect.width, self.rect.height)
        if not hasattr(self, "_render_surface") or self._render_surface is None or self._render_surface.get_size() != target_size:
            self._render_surface = pygame.Surface(target_size, pygame.SRCALPHA)
        surface = self._render_surface
        surface.fill((0, 0, 0, 0))
        
        current_items = self.get_current_page_items()
        colors = self.manager.get_theme_colors() if self.manager else {}
        
        # Draw grid cells
        for row in range(self.rows):
            for col in range(self.columns):
                item_index = row * self.columns + col
                
                # Calculate cell position (base coordinates scaled by ui_scale)
                cell_x = int((self.cell_padding + col * (self.cell_width + self.cell_padding)) * self.manager.ui_scale)
                cell_y = int((self.cell_padding + row * (self.cell_height + self.cell_padding)) * self.manager.ui_scale)
                
                # Cell rect at scaled dimensions
                cell_rect = pygame.Rect(
                    cell_x, cell_y,
                    int(self.cell_width * self.manager.ui_scale),
                    int(self.cell_height * self.manager.ui_scale)
                )
                
                # Check states
                is_focused = row == self.cursor_row and col == self.cursor_col and self.focused
                is_selected = row == self.selected_row and col == self.selected_col
                
                # Check if this cell has an item
                if item_index < len(current_items):
                    item = current_items[item_index]
                    
                    # Draw cell background based on pet attribute or empty slot
                    if item.data:  # Has pet
                        pet = item.data
                        attr_color = self.attribute_colors.get(getattr(pet, "attribute", None), (60, 60, 60))
                    else:  # Empty slot
                        attr_color = colors.get("bg", (50, 50, 50))
                    
                    pygame.draw.rect(surface, attr_color, cell_rect, border_radius=int(8 * self.manager.ui_scale))
                    
                    # Draw sprite if available
                    if item.sprite:
                        # Calculate sprite size (scaled dimensions)
                        available_height = int((self.cell_height - 15) * self.manager.ui_scale)  # Reserve space for text
                        
                        # Scale sprite to fit
                        sprite_rect = item.sprite.get_rect()
                        scale_x = (int((self.cell_width - 8) * self.manager.ui_scale)) / sprite_rect.width
                        scale_y = (available_height - int(4 * self.manager.ui_scale)) / sprite_rect.height
                        scale = min(scale_x, scale_y)
                        
                        new_width = int(sprite_rect.width * scale)
                        new_height = int(sprite_rect.height * scale)
                        
                        scaled_sprite = pygame.transform.scale(item.sprite, (new_width, new_height))
                        
                        # Draw module flag overlay (if pet exists)
                        if item.data:
                            pet = item.data
                            flag_sprite = runtime_globals.game_module_flag.get(pet.module)
                            if flag_sprite:
                                scaled_flag = pygame.transform.scale(flag_sprite, (new_width, new_height))
                                # Composite flag on top of sprite
                                sprite_with_flag = scaled_sprite.copy()
                                sprite_with_flag.blit(scaled_flag, (0, 0))
                                scaled_sprite = sprite_with_flag
                        
                        # Center sprite in cell horizontally, position with padding from top
                        sprite_x = cell_rect.centerx - new_width // 2
                        sprite_y = cell_rect.y + int(4 * self.manager.ui_scale)
                        blit_with_cache(surface, scaled_sprite, (sprite_x, sprite_y))
                    
                    # Draw text layer (with scrolling support)
                    if item.text and self.manager:
                        # Check if we have a cached text layer
                        if item_index not in self.text_layer_cache:
                            self.text_layer_cache[item_index] = self._render_text_layer(item_index, item, cell_rect)
                        
                        if self.text_layer_cache[item_index]:
                            blit_with_cache(surface, self.text_layer_cache[item_index], (cell_rect.x, cell_rect.y))
                
                # Draw focus border
                # Skip in touch mode - focus highlights are for keyboard/mouse navigation only
                if is_focused and runtime_globals.INPUT_MODE != runtime_globals.TOUCH_MODE:
                    # Get theme color for border
                    if self.manager:
                        colors = self.manager.get_theme_colors()
                        border_color = colors.get("highlight", (255, 255, 255))
                        border_size = self.manager.get_border_size()
                    else:
                        border_color = (255, 255, 255)
                        border_size = 3
                    pygame.draw.rect(surface, border_color, cell_rect, border_size, border_radius=int(8 * self.manager.ui_scale))
        
        return surface
