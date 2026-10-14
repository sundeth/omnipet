"""
Enhanced Item List Component - Vertical scrollable list for inventory items
Inherits from BaseList and adds custom cut-rectangle design with amount and item display sections.
"""
import pygame
from ui.components.base_list import BaseList
from core import runtime_globals
from utils.inventory_utils import get_inventory_value


class ItemList(BaseList):
    def __init__(self, x, y, width, height, on_item_activated=None):
        """Initialize the item list with vertical orientation"""
        super().__init__(x, y, width, height, orientation="vertical")
        
        # Item activation callback
        self.on_item_activated_callback = on_item_activated
        
        # Custom settings for item list
        self.base_item_size = 31  # Height of each item at 1x scale
        self.base_item_spacing = 7   # Spacing between items
        self.base_arrow_size = 12    # Height of arrow buttons
        self.base_margin = 2         # Margin around arrows
        
        # Visual settings for cut rectangles
        self.cut_width = 10     # Width of the cut section
        self.amount_cuts = 3    # Amount block width, in cut widths (a shop's prices need 4)

        # Animation settings for text scrolling
        self.text_scroll_speed = 20 * (30 / (runtime_globals.FRAME_RATE if hasattr(runtime_globals, 'FRAME_RATE') else 30))
        self.text_scroll_offset = {}  # Dict to track scroll offset per item
        self.text_scroll_delay = 1000  # Delay before starting scroll (ms)
        self.text_scroll_start_time = {}  # Track when scrolling started per item
                
    def _calculate_cut_points(self, x, y, width, height, cut_width, left_side=True):
        """
        Return 6 corner points for a block.
        If left_side=True => flat left side, cut on RIGHT.
        If left_side=False => flat right side, cut on LEFT.
        """
        x = int(x)
        y = int(y)
        width = max(0, int(width)) - 3
        height = max(0, int(height))
        cw = max(0, min(int(cut_width), width // 2))

        top_cut_y = y + int(round(height * 0.25))
        bottom_cut_y = y + int(round(height * 0.75))

        if left_side:
            # flat left, cut on right
            return [
                (x, y),                             # top-left
                (x + width - cw, y),                # top edge before cut
                (x + width, top_cut_y),             # diagonal down
                (x + width, bottom_cut_y),          # vertical cut
                (x + width - cw, y + height),       # diagonal up
                (x, y + height)                     # bottom-left
            ]
        else:
            approximation = (5 * self.manager.ui_scale) if self.manager else 5
            # flat right, cut on left (mirrored of above)
            return [
                (x - approximation, y),                        # top edge after cut
                (x + width, y),                                # top-right
                (x + width, y + height),                       # bottom-right
                (x - approximation, y + height),               # bottom edge after cut
                (x + cut_width - approximation, bottom_cut_y), # diagonal up
                (x + cut_width - approximation, top_cut_y)     # vertical cut up
            ]

    def _draw_items(self, surface):
        """Draw inventory items with custom cut-rectangle design inside the items area"""
        if not self.items or not self.items_rect:
            return

        colors = self.manager.get_theme_colors()

        # Calculate visible range
        item_total_size = self.item_size + self.item_spacing
        scaled_scroll_offset = self.scroll_offset
        first_visible = max(0, int(scaled_scroll_offset // item_total_size))
        last_visible = min(len(self.items), first_visible + self.get_visible_item_count() + 2)

        left_x = self.items_rect.x
        scaled_cut_width = self.manager.scale_value(self.cut_width)
        amount_width = scaled_cut_width * self.amount_cuts  # Width for amount section
        item_width = self.items_rect.width - amount_width

        for i in range(first_visible, last_visible):
            if i >= len(self.items):
                break

            item = self.items[i]

            # Calculate item position within items area
            item_y = self.items_rect.y + (i * item_total_size) - scaled_scroll_offset

            # Skip if completely outside visible items area
            if item_y + self.item_size < self.items_rect.y or item_y > self.items_rect.y + self.items_rect.height:
                continue

            # Determine colors based on SELECTION and FOCUS states
            is_selected = (i == self.active_index)  # persistent selection
            is_hovered = (i == self.mouse_over_index)
            is_keyboard_focused = (self.focused and i == self.selected_index)
            # Skip focus highlighting in touch mode - it's for keyboard/mouse navigation only
            is_focus_highlighted = (is_hovered or is_keyboard_focused) and runtime_globals.INPUT_MODE != runtime_globals.TOUCH_MODE

            if is_selected:
                # Selected state: swap bg and fg colors
                fill_color = colors["fg"]
                text_color = colors["bg"]
                border_color = colors["bg"]
            else:
                # Unselected state: normal bg and fg colors
                fill_color = colors["bg"]
                text_color = colors["fg"]
                border_color = colors["fg"]

            # Focus state: override border and text color with highlight
            if is_focus_highlighted:
                border_color = colors["highlight"]
                text_color = colors["highlight"]

            border_size = self.manager.get_border_size()

            # Draw amount block (left side with right cut)
            amount_points = self._calculate_cut_points(
                left_x, item_y, amount_width, self.item_size, scaled_cut_width, left_side=True
            )
            if len(amount_points) >= 3:
                pygame.draw.polygon(surface, fill_color, amount_points)
                pygame.draw.polygon(surface, border_color, amount_points, border_size)

            # Draw item block (right side with left cut)
            item_points = self._calculate_cut_points(
                left_x + amount_width, item_y, item_width, self.item_size, scaled_cut_width, left_side=False
            )
            if len(item_points) >= 3:
                pygame.draw.polygon(surface, fill_color, item_points)
                pygame.draw.polygon(surface, border_color, item_points, border_size)

            # Draw amount text. An item may bring its own (a shop's price).
            font = self.get_font("text", custom_size=24 * self.manager.ui_scale)
            alternate_font = font
            amount_text = getattr(item, 'amount_text', None)
            if amount_text is not None:
                # Shrink a long one ("9990P") to fit its block.
                size = 16
                alternate_font = self.get_font("text", custom_size=size * self.manager.ui_scale)
                while (alternate_font and size > 9
                       and alternate_font.size(amount_text)[0] > amount_width - scaled_cut_width):
                    size -= 1
                    alternate_font = self.get_font("text", custom_size=size * self.manager.ui_scale)
            else:
                if hasattr(item, 'quantity') and item.quantity != 0:
                    amount = item.quantity
                else:
                    amount = get_inventory_value(item.id) if hasattr(item, 'id') else 0
                if amount < 0 or amount > 999:  # Infinite or very large amount
                    amount_text = "∞"
                    alternate_font = self.get_font("text", custom_size=56 * self.manager.ui_scale)
                else:
                    amount_text = f"{amount}x"

            if font:
                amount_surface = alternate_font.render(amount_text, True, text_color)
                amount_rect = amount_surface.get_rect()
                amount_rect.center = (
                    left_x + (amount_width // 2) - int(3 * self.manager.ui_scale),
                    item_y + self.item_size // 2,
                )
                surface.blit(amount_surface, amount_rect)

            # Draw item icon and name
            icon_size = int(self.item_size - (3 * self.manager.ui_scale))
            icon_x = left_x + amount_width + int(6 * self.manager.ui_scale)
            icon_y = item_y + int(2 * self.manager.ui_scale)

            # Draw item icon if available
            if hasattr(item, 'icon') and item.icon:
                # Scale icon to fit the icon area
                scaled_icon = pygame.transform.scale(item.icon, (icon_size, icon_size))
                surface.blit(scaled_icon, (icon_x, icon_y))
            else:
                # Draw placeholder rectangle if no icon
                icon_rect = pygame.Rect(icon_x, icon_y, icon_size, icon_size)
                pygame.draw.rect(surface, border_color, icon_rect, 1)

            # Draw item name with scrolling if needed
            if hasattr(item, 'game_item') and item.game_item.name:
                name_x = icon_x + icon_size + 4
                name_y = item_y + self.item_size // 2
                available_width = item_width - icon_size - 8
                self._draw_scrolling_text(surface, item.game_item.name, i, name_x, name_y, available_width, text_color)

    def _draw_scrolling_text(self, surface, text, item_index, x, y, max_width, color):
        """Draw text with scrolling effect if it doesn't fit, trying 2-line layout first"""
        # Try with smaller font size first (16*scale) for 2-line text
        small_font = self.get_font("text", custom_size=16 * self.manager.ui_scale)
        
        if small_font:
            # Try to fit text in 2 lines
            words = text.split()
            if len(words) > 1:
                # Try different line breaks to find best fit
                best_fit = None
                min_max_width = float('inf')
                
                for split_point in range(1, len(words)):
                    line1 = ' '.join(words[:split_point])
                    line2 = ' '.join(words[split_point:])
                    
                    line1_surface = small_font.render(line1, True, color)
                    line2_surface = small_font.render(line2, True, color)
                    
                    max_line_width = max(line1_surface.get_width(), line2_surface.get_width())
                    
                    if max_line_width <= max_width and max_line_width < min_max_width:
                        best_fit = (line1, line2, line1_surface, line2_surface)
                        min_max_width = max_line_width
                
                # If we found a good 2-line fit, use it
                if best_fit:
                    line1, line2, line1_surface, line2_surface = best_fit
                    line_height = small_font.get_height()
                    line_spacing = int(line_height * 1.1)  # Increased spacing between lines
                    
                    # Draw first line (left-aligned)
                    line1_rect = line1_surface.get_rect()
                    line1_rect.midleft = (x, y - line_spacing // 2)
                    from utils.pygame_utils import blit_with_cache
                    blit_with_cache(surface, line1_surface, line1_rect.topleft)
                    
                    # Draw second line (left-aligned)
                    line2_rect = line2_surface.get_rect()
                    line2_rect.midleft = (x, y + line_spacing // 2)
                    from utils.pygame_utils import blit_with_cache
                    blit_with_cache(surface, line2_surface, line2_rect.topleft)
                    
                    # Reset scroll state for this item since we're using 2-line layout
                    if item_index in self.text_scroll_offset:
                        del self.text_scroll_offset[item_index]
                    if item_index in self.text_scroll_start_time:
                        del self.text_scroll_start_time[item_index]
                    return
        
        # If 2-line doesn't work, fall back to scrolling with larger font
        font = self.get_font("text", custom_size=24 * self.manager.ui_scale)
            
        if not font:
            return
            
        text_surface = font.render(text, True, color)
        text_width = text_surface.get_width()
        
        if text_width <= max_width:
            # Text fits, no scrolling needed
            text_rect = text_surface.get_rect()
            text_rect.midleft = (x, y)  # Left-align the text
            from utils.pygame_utils import blit_with_cache
            blit_with_cache(surface, text_surface, text_rect.topleft)
            # Reset scroll state for this item
            if item_index in self.text_scroll_offset:
                del self.text_scroll_offset[item_index]
            if item_index in self.text_scroll_start_time:
                del self.text_scroll_start_time[item_index]
        else:
            # Text needs scrolling
            current_time = pygame.time.get_ticks()
            
            # Initialize scroll state if needed
            if item_index not in self.text_scroll_start_time:
                self.text_scroll_start_time[item_index] = current_time
                self.text_scroll_offset[item_index] = 0
                
            # Check if delay period has passed
            if current_time - self.text_scroll_start_time[item_index] > self.text_scroll_delay:
                # Update scroll offset
                dt = (current_time - self.last_scroll_time) / 1000.0 if self.last_scroll_time > 0 else 0
                scroll_offset = self.text_scroll_offset.get(item_index, 0)
                scroll_offset += self.text_scroll_speed * dt
                
                # Loop the scroll
                max_scroll = text_width + max_width  # Extra space before looping
                if scroll_offset > max_scroll:
                    scroll_offset = -max_width
                    
                self.text_scroll_offset[item_index] = scroll_offset
                
                # Create clipping area
                clip_rect = pygame.Rect(x, y - font.get_height()//2, max_width, font.get_height())
                surface.set_clip(clip_rect)
                
                # Draw text at scrolled position
                text_rect = text_surface.get_rect()
                text_rect.midleft = (x - scroll_offset, y)
                from utils.pygame_utils import blit_with_cache
                blit_with_cache(surface, text_surface, text_rect.topleft)
                
                # Clear clipping
                surface.set_clip(None)
            else:
                # Still in delay period, show static text
                clip_rect = pygame.Rect(x, y - font.get_height()//2, max_width, font.get_height())
                surface.set_clip(clip_rect)
                
                text_rect = text_surface.get_rect()
                text_rect.midleft = (x, y)
                from utils.pygame_utils import blit_with_cache
                blit_with_cache(surface, text_surface, text_rect.topleft)
                
                surface.set_clip(None)
                
    def update(self):
        """Update component state including text scrolling animation"""
        super().update()
        
        # Update text scrolling (this will invalidate cache as needed)
        if any(item_index in self.text_scroll_offset for item_index in range(len(self.items))):
            self.needs_redraw = True
            self.cached_surface = None  # Force cache rebuild for text animation
            
    def _on_item_activated(self, index, interaction_type="keyboard"):
        """Called when an item is activated via keyboard (A button)"""
        if 0 <= index < len(self.items):
            item = self.items[index]
            runtime_globals.game_console.log(f"[ItemList] Activated item via {interaction_type}: {item.name if hasattr(item, 'name') else item}")
            
            # For keyboard activation, directly use the item
            if interaction_type == "keyboard" and self.on_item_activated_callback:
                # Call with special flag to indicate direct usage
                self.on_item_activated_callback(item, index, use_immediately=True)
            elif self.on_item_activated_callback:
                # For other types, just notify selection
                self.on_item_activated_callback(item, index, use_immediately=False)
                
    def _on_item_clicked(self, index, was_already_selected=False):
        """
        Called when an item is clicked with mouse.
        - If was_already_selected=True: activate/use the item
        - If was_already_selected=False: just select the item
        """
        if 0 <= index < len(self.items):
            item = self.items[index]
            runtime_globals.game_console.log(f"[ItemList] Clicked item: {item.name if hasattr(item, 'name') else item} (was_already_selected={was_already_selected})")
            
            # For mouse clicks:
            # - First click: just select (use_immediately=False)
            # - Second click on same item: use it (use_immediately=True)
            if self.on_item_activated_callback:
                self.on_item_activated_callback(item, index, use_immediately=was_already_selected)
        else:
            # Invalid index - don't call callback
            runtime_globals.game_console.log(f"[ItemList] Invalid item click: index={index}, total_items={len(self.items)}")
            
    def _on_selection_changed(self, old_index, new_index):
        """Called when selection state changes"""
        runtime_globals.game_console.log(f"[ItemList] Selection changed from {old_index} to {new_index}")
        self.needs_redraw = True
    
    # Removed earlier duplicate set_selected_index that referenced a non-existent BaseList method

    def render(self):
        """Render the list component - override to include focused state in cache key"""
        if self.needs_layout_recalc:
            self._calculate_layout()
            
        # Check if we need to rebuild cache - IMPORTANT: include focused state!
        current_key = (
            self.scroll_offset, 
            self.selected_index, 
            self.active_index,
            self.mouse_over_index,
            len(self.items),
            self.prev_arrow_pressed,
            self.next_arrow_pressed,
            self.focused  # Add focused state to cache key!
        )
        
        if self.cached_surface is None or current_key != self.cache_key:
            self.cached_surface = self._render_to_cache()
            self.cache_key = current_key
            
        return self.cached_surface
        
    def _render_to_cache(self):
        """Use BaseList's renderer to draw arrows/background/border; our items are drawn via override."""
        return super()._render_to_cache()
        
    def on_focus_gained(self):
        """Called when component gains focus - trigger redraw to show selection highlight"""
        super().on_focus_gained()
        runtime_globals.game_console.log(f"[ItemList] DEBUG: Focus gained - focused={self.focused}")
        self.needs_redraw = True
        
    def on_focus_lost(self):
        """Called when component loses focus - trigger redraw to hide selection highlight"""
        super().on_focus_lost()
        runtime_globals.game_console.log(f"[ItemList] DEBUG: Focus lost - focused={self.focused}")
        self.needs_redraw = True

    def get_focused_sub_rect(self):
        """Get the rect of the currently selected item for focus highlight"""
        if not self.items or self.selected_index < 0 or self.selected_index >= len(self.items):
            return self.rect
        
        if not self.manager or not self.items_rect:
            return self.rect
        
        # Calculate the rect of the selected item in base coordinates
        item_total_size = self.base_item_size + self.base_item_spacing
        item_y = (self.selected_index * item_total_size) - self.scroll_offset
        
        base_item_rect = pygame.Rect(
            self.base_rect.x + self.items_rect.x,
            self.base_rect.y + item_y,
            self.items_rect.width,
            self.base_item_size
        )
        
        # Convert to screen coordinates
        return self.manager.ui_to_screen_rect(base_item_rect)
    
    def get_mouse_sub_rect(self, mouse_pos):
        """Check if mouse is over the list - return rect if valid, None if not"""
        if not self.manager or not self.base_rect:
            return self.rect

        # mouse_pos arrives already in UI/base coordinates from UIManager
        relative_x = mouse_pos[0] - self.base_rect.x
        relative_y = mouse_pos[1] - self.base_rect.y

        # Only accept positions inside the component's base rect
        if not (0 <= relative_x < self.base_rect.width and 0 <= relative_y < self.base_rect.height):
            return None

        return self.rect
    
    def set_selected_index(self, index, instant_scroll=False):
        """Set the selected index with bounds checking
        
        Args:
            index: The index to select
            instant_scroll: If True, scroll immediately without animation
        """
        if not self.items:
            self.selected_index = -1
            self.active_index = -1
            return
            
        # Clamp index to valid range
        if index < 0:
            self.selected_index = 0
        elif index >= len(self.items):
            self.selected_index = len(self.items) - 1
        else:
            self.selected_index = index
        
        # Call parent class method to handle scroll behavior
        super().set_selected_index(self.selected_index, instant_scroll=instant_scroll)
        
        # Set active_index to make the item visually selected (same as keyboard navigation)
        self.active_index = self.selected_index
        
        # Trigger redraw
        self.needs_redraw = True
    
    def _ensure_item_visible(self, index):
        """Ensure the item at the given index is visible by adjusting scroll offset"""
        if not self.items or index < 0 or index >= len(self.items):
            return
            
        item_total_size = self.item_size + self.item_spacing
        item_position = index * item_total_size
        
        # Get the visible area bounds
        visible_height = self.items_rect.height if self.items_rect else self.rect.height
        
        # Check if item is above visible area
        if item_position < self.scroll_offset:
            self.scroll_offset = item_position
            
        # Check if item is below visible area
        elif item_position + self.item_size > self.scroll_offset + visible_height:
            self.scroll_offset = item_position + self.item_size - visible_height