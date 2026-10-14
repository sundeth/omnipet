"""
G-Cell Bar Component - Shows G-Cells as a row of colored indicators with paging system
"""
import pygame
from ui.components.component import UIComponent
from utils import gcell_rules
from utils.pygame_utils import blit_with_cache


class GCellBar(UIComponent):
    def __init__(self, x, y, width, height, pet=None):
        super().__init__(x, y, width, height)
        self.pet = pet
        self.focusable = False
        self.gcell_images = {}
        
    def load_images(self):
        """Load G-Cell images based on UI scale with fallback and scaling"""
        if not self.manager:
            return

        # Try to load with preferred scale first
        self.gcell_images = {
            "empty": self.manager.load_sprite_integer_scaling("Status", "DP", "Empty"),
            "blue": self.manager.load_sprite_integer_scaling("Status", "GCell", "Blue"),
            "yellow": self.manager.load_sprite_integer_scaling("Status", "GCell", "Yellow"),
            "red": self.manager.load_sprite_integer_scaling("Status", "GCell", "Red")
        }
        
    def set_pet(self, pet):
        """Update the pet reference"""
        if self.pet != pet:
            self.pet = pet
            self.needs_redraw = True
        
    def get_display_cells(self):
        """Calculate which cells to display based on G-Cell level and counts"""
        if not self.pet:
            return []

        # PENGZ style: 14 cells of the stage's size, Blue to 7, Red from 8.
        try:
            from utils.module_utils import get_module
            styled = gcell_rules.display_cells(get_module(self.pet.module), self.pet)
        except Exception:
            styled = None
        if styled is not None:
            return styled

        blue_count = self.pet.get_blue_gcells()
        yellow_count = self.pet.get_yellow_gcells()
        red_count = self.pet.get_red_gcells()
        level = self.pet.get_gcell_level()
        
        cells = []
        
        if level == 1:
            # Level 1: Show 0-14 blue cells
            for i in range(14):
                if i < blue_count:
                    cells.append("blue")
                else:
                    cells.append("empty")
        elif level == 2:
            # Level 2: Show 4 blue + 0-10 yellow
            for i in range(4):
                cells.append("blue")
            for i in range(10):
                if i < yellow_count:
                    cells.append("yellow")
                else:
                    cells.append("empty")
        elif level == 3:
            # Level 3: Show 4 yellow + 0-10 red
            for i in range(4):
                cells.append("yellow")
            for i in range(10):
                if i < red_count:
                    cells.append("red")
                else:
                    cells.append("empty")
        elif level == 4:
            # Level 4: Show 4 red + 0-10 red (continuing red progression)
            for i in range(4):
                cells.append("red")
            # Show the remaining red cells (10-20 range)
            remaining_red = red_count - 10  # red_count can be 10-20 at level 4
            for i in range(10):
                if i < remaining_red:
                    cells.append("red")
                else:
                    cells.append("empty")
        
        return cells
        
    def render(self):
        # Use screen dimensions for surface
        surface = pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
        
        # Load images if needed
        if not self.gcell_images:
            self.load_images()
        
        # Get the cells to display
        display_cells = self.get_display_cells()
        
        if not display_cells:
            return surface
            
        # Original G-Cell sprite dimensions (same as DP)
        original_gcell_width = self.gcell_images["empty"].get_width()
        original_gcell_height = self.gcell_images["empty"].get_height()
        
        # Calculate ideal dimensions to fit 14 G-Cells with 2-pixel overlap
        base_overlap = 2  # 2 pixels overlap at 240x240 resolution
        gcell_overlap = self.manager.scale_value(base_overlap)  # Scale overlap for current resolution
        gcell_start_x = self.manager.scale_value(1)  # Scale base padding
        available_width = self.rect.width - 2 * gcell_start_x
        
        # Calculate the effective width each G-Cell should take (with overlap)
        # For 14 G-Cells with overlap: width = GCell_width * 14 - overlap * 13
        # Solving for GCell_width: GCell_width = (width + overlap * 13) / 14
        effective_gcell_width = (available_width + gcell_overlap * 13) // 14
        
        # Scale the G-Cell sprites if needed to fit exactly
        if effective_gcell_width != original_gcell_width:
            # Maintain aspect ratio
            scale_factor = effective_gcell_width / original_gcell_width
            scaled_gcell_height = int(original_gcell_height * scale_factor)
            
            # Scale all G-Cell images
            scaled_gcell_size = (effective_gcell_width, scaled_gcell_height)
            scaled_images = {}
            for key, image in self.gcell_images.items():
                scaled_images[key] = pygame.transform.scale(image, scaled_gcell_size)
        else:
            scaled_images = self.gcell_images
            scaled_gcell_height = original_gcell_height
        
        # Center vertically
        gcell_start_y = (self.rect.height - scaled_gcell_height) // 2
        
        # Draw all 14 G-Cell indicators with proper overlap
        for i in range(14):
            gcell_x = gcell_start_x + i * (effective_gcell_width - gcell_overlap)
            
            # Get the cell type for this position
            if i < len(display_cells):
                cell_type = display_cells[i]
            else:
                cell_type = "empty"
                
            gcell_sprite = scaled_images[cell_type]
            blit_with_cache(surface, gcell_sprite, (gcell_x, gcell_start_y))
        
        # Draw highlight if focused and has tooltip
        if self.focused and hasattr(self, 'tooltip_text') and self.tooltip_text:
            colors = self.manager.get_theme_colors()
            highlight_color = colors.get("highlight", colors["fg"])  # Safe fallback
            pygame.draw.rect(surface, highlight_color, surface.get_rect(), 2)
            
        return surface