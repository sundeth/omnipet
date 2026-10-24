"""
Freezer Grid Component - 5x5 grid display for freezer box pets
"""
import pygame
from ui.components.grid import Grid, GridItem
from core import runtime_globals
import core.constants as constants
from utils.pygame_utils import blit_with_cache


class FreezerGrid(Grid):
    """Grid component specialized for displaying freezer box pets (5x5 grid)"""
    
    def __init__(self, x, y, width, height):
        # Freezer is always 5x5
        super().__init__(x, y, width, height, rows=5, columns=5)
        
        self.empty_slot_text = "-"
        self.attribute_colors = constants.ATTR_COLORS
        
        # Visual customization
        self.cell_padding = 2
        
        # Recalculate cell dimensions with new padding
        self.cell_width = (width - (self.cell_padding * (self.columns + 1))) // self.columns
        self.cell_height = (height - (self.cell_padding * (self.rows + 1))) // self.rows
        
        runtime_globals.game_console.log(f"[FreezerGrid] Created 5x5 grid for freezer box")
        
    def refresh_from_freezer_page(self, freezer_page):
        """Refresh grid items from a freezer page's pet_grid"""
        items = []
        
        # Flatten the 5x5 grid into a list
        for row in range(5):
            for col in range(5):
                if row < len(freezer_page.pet_grid) and col < len(freezer_page.pet_grid[row]):
                    pet = freezer_page.pet_grid[row][col]
                    
                    if pet:
                        # Get pet sprite
                        sprite = None
                        if pet in runtime_globals.pet_sprites:
                            sprite_list = runtime_globals.pet_sprites[pet]
                            if sprite_list:
                                sprite = sprite_list[0]
                        
                        # Create grid item with pet data
                        item = GridItem(sprite=sprite, text="", data=pet)
                        items.append(item)
                    else:
                        # Empty slot
                        items.append(GridItem(sprite=None, text=self.empty_slot_text, data=None))
                else:
                    # Empty slot
                    items.append(GridItem(sprite=None, text=self.empty_slot_text, data=None))
        
        self.set_items(items)
        
    def render(self):
        """Render the freezer grid with attribute-colored backgrounds"""
        from core import runtime_globals
        
        # Reuse a cached render surface to avoid per-frame allocations
        target_size = (self.rect.width, self.rect.height)
        if not hasattr(self, "_render_surface") or self._render_surface is None or self._render_surface.get_size() != target_size:
            self._render_surface = pygame.Surface(target_size, pygame.SRCALPHA)
        surface = self._render_surface
        surface.fill((0, 0, 0, 0))
        
        current_items = self.get_current_page_items()
        
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
                        attr_color = self.attribute_colors.get(getattr(pet, "attribute", None), (50, 50, 50))
                    else:  # Empty slot
                        attr_color = (50, 50, 50)
                    
                    pygame.draw.rect(surface, attr_color, cell_rect)
                    
                    # Draw sprite and flag if available
                    if item.sprite and item.data:
                        pet = item.data
                        
                        # Scale sprite to fit cell (scaled dimensions)
                        sprite_rect = item.sprite.get_rect()
                        available_width = int((self.cell_width - 4) * self.manager.ui_scale)
                        available_height = int((self.cell_height - 4) * self.manager.ui_scale)
                        
                        scale = min(available_width / sprite_rect.width, 
                                   available_height / sprite_rect.height)
                        
                        new_width = int(sprite_rect.width * scale)
                        new_height = int(sprite_rect.height * scale)
                        
                        scaled_sprite = pygame.transform.scale(item.sprite, (new_width, new_height))
                        
                        # Draw module flag on top
                        flag_sprite = runtime_globals.game_module_flag.get(pet.module)
                        if flag_sprite:
                            scaled_flag = pygame.transform.scale(flag_sprite, (new_width, new_height))
                            # Blit flag overlay at top of cell
                            flag_x = cell_rect.centerx - new_width // 2
                            flag_y = cell_rect.y + int(2 * self.manager.ui_scale)
                            blit_with_cache(surface, scaled_flag, (flag_x, flag_y))
                        
                        # Draw pet sprite below flag
                        sprite_x = cell_rect.centerx - new_width // 2
                        sprite_y = cell_rect.y + int(4 * self.manager.ui_scale)
                        blit_with_cache(surface, scaled_sprite, (sprite_x, sprite_y))
                    
                    # Draw empty slot dash
                    elif not item.data and item.text and self.manager:
                        font = self.get_font("text")
                        text_surface = font.render(item.text, True, (128, 128, 128))
                        text_rect = text_surface.get_rect()
                        text_rect.center = cell_rect.center
                        blit_with_cache(surface, text_surface, text_rect.topleft)
                
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
                        border_size = 2
                    pygame.draw.rect(surface, border_color, cell_rect, border_size)
        
        return surface
