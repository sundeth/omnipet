"""
Grid Component - A grid layout for displaying items with pagination and cursor selection
"""
import pygame
import math
from ui.components.component import UIComponent
from core import runtime_globals
from utils.pygame_utils import blit_with_cache


class GridItem:
    """Represents an item in the grid"""
    def __init__(self, sprite=None, text="", data=None):
        self.sprite = sprite
        self.text = text
        self.data = data  # Any additional data associated with this item


class Grid(UIComponent):
    """A grid component that displays items in a grid layout with pagination and cursor selection"""
    
    def __init__(self, x, y, width, height, rows=2, columns=2):
        super().__init__(x, y, width, height)
        self.rows = rows
        self.columns = columns
        self.items = []  # List of GridItem objects
        self.current_page = 0
        self.cursor_row = 0  # Currently focused item (for navigation)
        self.cursor_col = 0
        self.selected_row = -1  # Currently selected item (for highlighting) - -1 means no selection
        self.selected_col = -1
        self.selected_item_index = -1  # Global index of selected item across all pages
        self.items_per_page = rows * columns
        self.focusable = True
        
        # Visual properties
        self.cell_padding = 5  # Padding around each cell content
        self.cursor_color = (255, 255, 255)  # White cursor
        self.cursor_thickness = 2
        self.text_color = (255, 255, 255)  # White text
        self.background_color = None  # Transparent background
        
        # Calculate cell dimensions
        self.cell_width = (width - (self.cell_padding * (columns + 1))) // columns
        self.cell_height = (height - (self.cell_padding * (rows + 1))) // rows
        
        # Callbacks
        self.on_selection_change = None  # Callback when cursor moves
        self.on_page_change = None  # Callback when page changes
        
    def set_items(self, items):
        """Set the items to display in the grid"""
        # Only mark redraw if items actually changed
        items_changed = (self.items != items)
        
        self.items = items
        self.current_page = 0
        self.cursor_row = 0
        self.cursor_col = 0
        self.selected_row = -1
        self.selected_col = -1
        self.selected_item_index = -1
        
        if items_changed:
            self.needs_redraw = True
        
        # Trigger page change callback
        if self.on_page_change:
            self.on_page_change(self.current_page, self.get_total_pages())
            
    def add_item(self, sprite=None, text="", data=None):
        """Add an item to the grid"""
        item = GridItem(sprite, text, data)
        self.items.append(item)
        self.needs_redraw = True
        
    def get_total_pages(self):
        """Get the total number of pages"""
        if not self.items:
            return 0
        return math.ceil(len(self.items) / self.items_per_page)
        
    def get_current_page_items(self):
        """Get the items for the current page"""
        start_idx = self.current_page * self.items_per_page
        end_idx = start_idx + self.items_per_page
        return self.items[start_idx:end_idx]
        
    def get_selected_item(self):
        """Get the currently selected item"""
        current_items = self.get_current_page_items()
        item_index = self.cursor_row * self.columns + self.cursor_col
        
        if 0 <= item_index < len(current_items):
            return current_items[item_index]
        return None
        
    def select_current_item(self):
        """Select the currently focused item (for highlighting)"""
        self.selected_row = self.cursor_row
        self.selected_col = self.cursor_col
        
        # Calculate global item index
        item_index = self.cursor_row * self.columns + self.cursor_col
        self.selected_item_index = self.current_page * self.items_per_page + item_index
        
        self.needs_redraw = True
        
    def clear_selection(self):
        """Clear the current selection"""
        self.selected_row = -1
        self.selected_col = -1
        self.selected_item_index = -1
        self.needs_redraw = True
        
    def move_cursor(self, dx, dy):
        """Move the cursor by the given delta. Returns False if at edge to allow focus navigation."""
        old_row, old_col = self.cursor_row, self.cursor_col
        
        new_col = self.cursor_col + dx
        new_row = self.cursor_row + dy
        
        # Check if we're trying to move beyond the grid boundaries
        # If so, return False to allow UI manager to handle focus navigation
        if new_col < 0 or new_col >= self.columns or new_row < 0 or new_row >= self.rows:
            return False
        
        # Check if the new position has a valid item
        current_items = self.get_current_page_items()
        item_index = new_row * self.columns + new_col
        
        if 0 <= item_index < len(current_items):
            self.cursor_row = new_row
            self.cursor_col = new_col
            self.needs_redraw = True
            
            # Don't trigger selection change callback on navigation - only on actual selection (A button/click)
                
            return True
        
        # No valid item at new position and we're within grid bounds - don't move, but consume the input
        return True
        
    def change_page(self, delta):
        """Change the page by the given delta"""
        total_pages = self.get_total_pages()
        if total_pages <= 1:
            return False
            
        new_page = self.current_page + delta
        new_page = max(0, min(total_pages - 1, new_page))
        
        if new_page != self.current_page:
            self.current_page = new_page
            
            # Check if the globally selected item is on this page
            if self.selected_item_index >= 0:
                # Calculate which page the selected item is on
                selected_page = self.selected_item_index // self.items_per_page
                
                if selected_page == self.current_page:
                    # Selected item is on this page, restore local selection
                    local_item_index = self.selected_item_index % self.items_per_page
                    self.selected_row = local_item_index // self.columns
                    self.selected_col = local_item_index % self.columns
                else:
                    # Selected item is not on this page, clear local selection but keep global selection
                    self.selected_row = -1
                    self.selected_col = -1
            else:
                # No global selection, ensure local selection is cleared
                self.selected_row = -1
                self.selected_col = -1
            
            # Reset cursor to top-left and ensure it's on a valid item
            self.cursor_row = 0
            self.cursor_col = 0
            
            # Find first valid item position on new page
            current_items = self.get_current_page_items()
            if current_items:
                self.needs_redraw = True
                
                # Trigger page change callback (but not selection change - that's only for actual selection)
                if self.on_page_change:
                    self.on_page_change(self.current_page, total_pages)
                    
                return True
        return False
        
    def handle_event(self, event):
        """Handle input events for the grid component"""
        if not self.visible or not self.focusable:
            return False
            
        # Handle tuple-based events from the input manager
        if not isinstance(event, tuple) or len(event) != 2:
            return False
            
        event_type, event_data = event
            
        # Only handle keyboard navigation when this component is focused
        if not self.focused:
            return False
                
        if event_type == "UP":
            runtime_globals.game_sound.play("menu")
            return self.move_cursor(0, -1)
        elif event_type == "DOWN":
            runtime_globals.game_sound.play("menu")
            return self.move_cursor(0, 1)
        elif event_type == "LEFT":
            runtime_globals.game_sound.play("menu")
            return self.move_cursor(-1, 0)
        elif event_type == "RIGHT":
            runtime_globals.game_sound.play("menu")
            return self.move_cursor(1, 0)
        elif event_type == "L":  # Page left
            runtime_globals.game_sound.play("menu")
            return self.change_page(-1)
        elif event_type == "R":  # Page right
            runtime_globals.game_sound.play("menu")
            return self.change_page(1)
        elif event_type == "A":  # Select item
            selected_item = self.get_selected_item()
            # Allow selecting even if item is None (empty cell) - let parent decide what to do
            runtime_globals.game_sound.play("menu")
            # Actually select the current item for highlighting
            self.select_current_item()
            # Trigger selection change callback to notify parent of selection
            if self.on_selection_change:
                self.on_selection_change(selected_item)
            return True
        elif event_type == "LCLICK":
            # Handle mouse clicks for selection
            if event_data and "pos" in event_data:
                # Select the currently focused item on click
                current_items = self.get_current_page_items()
                item_index = self.cursor_row * self.columns + self.cursor_col
                
                if 0 <= item_index < len(current_items):
                    runtime_globals.game_sound.play("menu")
                    self.select_current_item()
                    # Trigger selection change callback only on actual click/selection
                    if self.on_selection_change:
                        self.on_selection_change(self.get_selected_item())
                    return True
            
        return False
        
    def render(self):
        """Render the grid component"""
        # Reuse a cached render surface to avoid per-frame allocations
        target_size = (self.rect.width, self.rect.height)
        if not hasattr(self, "_render_surface") or self._render_surface is None or self._render_surface.get_size() != target_size:
            self._render_surface = pygame.Surface(target_size, pygame.SRCALPHA)
        surface = self._render_surface
        surface.fill((0, 0, 0, 0))
        
        # Draw background if specified
        if self.background_color:
            surface.fill(self.background_color)
            
        current_items = self.get_current_page_items()

        # Get UI scale factor
        ui_scale = self.manager.ui_scale if self.manager else 1.0

        # Item captions (egg names, device names) use the ordinary text size —
        # they were drawn two thirds of that and were barely legible. The
        # sprite area reserves the font's real height so the taller text does
        # not clip against the bottom of the cell.
        caption_font = self.get_font("text") if self.manager else None
        caption_height = caption_font.get_height() if caption_font else int(16 * ui_scale)

        # Draw grid cells
        for row in range(self.rows):
            for col in range(self.columns):
                item_index = row * self.columns + col
                
                # Calculate cell position (base coordinates scaled by ui_scale)
                cell_x = int((self.cell_padding + col * (self.cell_width + self.cell_padding)) * ui_scale)
                cell_y = int((self.cell_padding + row * (self.cell_height + self.cell_padding)) * ui_scale)
                
                # Draw cell background (scaled dimensions)
                cell_rect = pygame.Rect(
                    cell_x, cell_y,
                    int(self.cell_width * ui_scale),
                    int(self.cell_height * ui_scale)
                )
                
                # Check if this is the focused cell (cursor position) for border highlight
                is_focused = row == self.cursor_row and col == self.cursor_col and self.focused
                # Check if this is the selected cell (clicked/chosen) for background highlight
                is_selected = row == self.selected_row and col == self.selected_col
                
                # Check if this cell has an item
                if item_index < len(current_items):
                    item = current_items[item_index]
                    
                    # Draw highlight background for selected cell
                    if is_selected and self.manager:
                        # Get theme highlight color
                        colors = self.manager.get_theme_colors()
                        highlight_color = colors.get("highlight", (200, 200, 200))  # Default light gray
                        # Create a lighter version of the highlight color
                        light_highlight = tuple(min(255, c + 50) for c in highlight_color)
                        pygame.draw.rect(surface, light_highlight, cell_rect)
                    
                    # Draw sprite if available
                    if item.sprite:
                        # Calculate scaled sprite size to fill cell while maintaining aspect ratio
                        sprite_rect = item.sprite.get_rect()
                        original_width = sprite_rect.width
                        original_height = sprite_rect.height
                        
                        # Reserve space for text if it exists (in scaled pixels)
                        available_height = int(self.cell_height * ui_scale)
                        if item.text:
                            available_height -= caption_height  # Reserve space for text at bottom
                        
                        # Calculate scaling factors for width and height (scaled dimensions)
                        scale_x = (int((self.cell_width - 4) * ui_scale)) / original_width  # -4 for padding
                        scale_y = available_height / original_height
                        
                        # Use the smaller scale to maintain aspect ratio
                        scale = min(scale_x, scale_y)
                        
                        # Calculate new dimensions
                        new_width = int(original_width * scale)
                        new_height = int(original_height * scale)
                        
                        # Scale the sprite
                        scaled_sprite = pygame.transform.scale(item.sprite, (new_width, new_height))
                        
                        # Center the scaled sprite in the cell (or in available space if text exists)
                        sprite_rect = scaled_sprite.get_rect()
                        sprite_rect.centerx = cell_rect.centerx
                        
                        if item.text:
                            # Position sprite in upper part of cell, leaving space for text
                            sprite_rect.centery = cell_rect.y + (available_height // 2)
                        else:
                            # Center sprite in entire cell
                            sprite_rect.centery = cell_rect.centery
                        
                        blit_with_cache(surface, scaled_sprite, sprite_rect.topleft)
                    
                    # Draw text if available (below sprite or centered if no sprite)
                    if item.text and self.manager:
                        font = caption_font

                        # Calculate available text width (scaled)
                        available_text_width = int((self.cell_width - 4) * ui_scale)  # -4 for padding
                        
                        # Choose text color based on selection state
                        text_color = (0, 0, 0) if is_selected else self.text_color  # Black if selected, white if not
                        
                        # Render text initially to check size
                        text_surface = font.render(item.text, True, text_color)
                        text_rect = text_surface.get_rect()
                        
                        # If text is too wide, create a truncated version
                        if text_surface.get_width() > available_text_width:
                            # Create a surface with the available width
                            truncated_surface = pygame.Surface((available_text_width, text_surface.get_height()), pygame.SRCALPHA)
                            # Blit only the portion that fits
                            truncated_surface.blit(text_surface, (0, 0))
                            text_surface = truncated_surface
                            text_rect = text_surface.get_rect()
                        
                        if item.sprite:
                            # Position text below sprite
                            text_rect.centerx = cell_rect.centerx
                            text_rect.bottom = cell_rect.bottom - int(2 * ui_scale)
                        else:
                            # Center text in cell
                            text_rect.center = cell_rect.center
                            
                        blit_with_cache(surface, text_surface, text_rect.topleft)
                
                # Draw border cursor if this is the focused cell (for navigation)
                # Skip in touch mode - focus highlights are for keyboard/mouse navigation only
                if is_focused and runtime_globals.INPUT_MODE != runtime_globals.TOUCH_MODE:
                    # Draw a subtle border around the focused cell (scaled border width)
                    border_width = max(1, int(1 * ui_scale))
                    pygame.draw.rect(surface, self.cursor_color, cell_rect, border_width)
                    
        return surface
        
    def get_focused_sub_rect(self):
        """Get the rect of the currently focused cell"""
        return None
        
    def get_mouse_sub_rect(self, mouse_pos):
        """Get the rect of the cell under the mouse"""
        from core import runtime_globals
        
        if not self.manager:
            return None
        
        # mouse_pos is in UI coordinates (base 240x240 space)
        # self.base_rect is also in base coordinates
        
        # Convert to component-relative coordinates in base space
        relative_x = mouse_pos[0] - self.base_rect.x
        relative_y = mouse_pos[1] - self.base_rect.y
        
        # Check if mouse is within component bounds (base coordinates)
        if not (0 <= relative_x < self.base_rect.width and 0 <= relative_y < self.base_rect.height):
            return None
        
        # Find which cell the mouse is over (all in base coordinates)
        for row in range(self.rows):
            for col in range(self.columns):
                # Calculate cell position in base coordinates (relative to component)
                cell_x = self.cell_padding + col * (self.cell_width + self.cell_padding)
                cell_y = self.cell_padding + row * (self.cell_height + self.cell_padding)
                
                # Check if mouse is over this cell (base space comparison)
                if (cell_x <= relative_x < cell_x + self.cell_width and
                    cell_y <= relative_y < cell_y + self.cell_height):
                    
                    # Update cursor position
                    if self.cursor_row != row or self.cursor_col != col:
                        self.cursor_row = row
                        self.cursor_col = col
                        self.needs_redraw = True
                    
                    # Return the cell rect in screen coordinates
                    # Calculate absolute cell position in base space
                    abs_cell_x = self.base_rect.x + cell_x
                    abs_cell_y = self.base_rect.y + cell_y
                    
                    # Scale to screen coordinates
                    scaled_x, scaled_y = self.manager.scale_position(abs_cell_x, abs_cell_y)
                    scaled_width = self.manager.scale_value(self.cell_width)
                    scaled_height = self.manager.scale_value(self.cell_height)
                    
                    return pygame.Rect(scaled_x, scaled_y, scaled_width, scaled_height)
        
        return None
        
    def on_manager_set(self):
        """Called when the UI manager is set"""
        # Recalculate cell dimensions if manager scale has changed
        if self.manager:
            # Cell dimensions are already calculated in base coordinates
            self.needs_redraw = True