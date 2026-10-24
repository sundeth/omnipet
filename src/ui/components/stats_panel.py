"""
Stats Panel Component - A popup panel that displays pet statistics
"""
import pygame
from ui.components.component import UIComponent
from ui.components.label import Label
from ui.components.label_value import LabelValue
from ui.components.heart import HeartMeter
from core import constants
from utils.module_utils import get_module
from ui.ui_constants import CYAN


class StatsPanel(UIComponent):
    """
    A popup panel that displays pet statistics.
    Closes on any input (like a tooltip).
    """
    
    def __init__(self, pet):
        """
        Initialize the stats panel for a specific pet.
        
        Args:
            pet: The pet object whose stats to display
        """
        # Center the panel on screen (180x200 panel, screen is 240x240)
        x = 30
        y = 20
        width = 180
        height = 200
        
        super().__init__(x, y, width, height)
        
        self.pet = pet
        self.visible = True  # Start visible
        self.focusable = False  # Don't participate in focus management
        self.needs_redraw = True
        
        # Get module info for visible stats
        module = get_module(pet.module)
        self.visible_stats = getattr(module, "visible_stats", [])
        
        # Create child components for stats display
        self.stat_components = []
        self._create_stat_components()
    
    def _create_stat_components(self):
        """Create UI components for displaying stats"""
        padding = 8
        current_y = 0  # Relative to panel top
        line_height = 15
        
        # Pet name (title)
        name_label = Label(padding, padding + current_y, self.pet.name.upper(), is_title=True)
        self.stat_components.append(name_label)
        current_y += 20
        
        # Stage
        stage_text = f"Stage: {constants.stage_name(self.pet.stage)}"
        stage_label = Label(padding, padding + current_y, stage_text, is_title=False)
        self.stat_components.append(stage_label)
        current_y += line_height
        
        # Age (if visible)
        if "Age" in self.visible_stats:
            age_label = LabelValue(padding, padding + current_y, 164, line_height, "Age:", f"{self.pet.age}d", color_override=CYAN)
            self.stat_components.append(age_label)
            current_y += line_height
        
        # Weight (if visible)
        if "Weight" in self.visible_stats:
            weight_label = LabelValue(padding, padding + current_y, 164, line_height, "Weight:", f"{self.pet.weight}g", color_override=CYAN)
            self.stat_components.append(weight_label)
            current_y += line_height
        
        # Level (if visible)
        if "Level" in self.visible_stats:
            level_label = LabelValue(padding, padding + current_y, 164, line_height, "Level:", str(self.pet.level), color_override=CYAN)
            self.stat_components.append(level_label)
            current_y += line_height
        
        # Trophies (if visible)
        if "Trophies" in self.visible_stats:
            trophies_label = LabelValue(padding, padding + current_y, 164, line_height, "Trophies:", str(getattr(self.pet, 'trophies', 0)), color_override=CYAN)
            self.stat_components.append(trophies_label)
            current_y += line_height
        
        # Vital Values (if visible)
        if "Vital Values" in self.visible_stats:
            vital_label = LabelValue(padding, padding + current_y, 164, line_height, "Vital Values:", str(getattr(self.pet, 'vital_values', 0)), color_override=CYAN)
            self.stat_components.append(vital_label)
            current_y += line_height
        
        current_y += 3
        
        # Heart meters for hunger, strength, effort
        heart_width = 164
        heart_height = 18
        
        if "Hunger" in self.visible_stats:
            hunger_meter = HeartMeter(padding, padding + current_y, heart_width, heart_height, "Hunger", self.pet.hunger, 4, 1)
            self.stat_components.append(hunger_meter)
            current_y += heart_height + 2
        
        if "Strength" in self.visible_stats:
            strength_meter = HeartMeter(padding, padding + current_y, heart_width, heart_height, "Vitamin", self.pet.strength, 4, 1)
            self.stat_components.append(strength_meter)
            current_y += heart_height + 2
        
        if "Effort" in self.visible_stats:
            effort_meter = HeartMeter(padding, padding + current_y, heart_width, heart_height, "Effort", self.pet.effort, 4, 4)
            self.stat_components.append(effort_meter)
            current_y += heart_height + 2
        
        # G-Cells (if available)
        if hasattr(self.pet, "gcells"):
            gcells_label = LabelValue(padding, padding + current_y, 164, line_height, "G-Cells:", str(self.pet.gcells), color_override=CYAN)
            self.stat_components.append(gcells_label)
            current_y += line_height
        
        # Battle stats (if visible)
        if "Power" in self.visible_stats:
            from utils.power_display import power_display
            power, color = power_display(self.pet, items=False)
            # Same rule as the status scene: the pet having a star is what
            # decides whether one is shown, not the module's ruleset.
            if getattr(self.pet, 'star', 0) > 0:
                power += f"({self.pet.star}★)"
            power_label = LabelValue(padding, padding + current_y, 164, line_height, "Power:", power,
                                     color_override=CYAN, value_color=color)
            self.stat_components.append(power_label)
            current_y += line_height
        
        if "Battles" in self.visible_stats:
            battles_label = LabelValue(padding, padding + current_y, 164, line_height, "Battles:", str(self.pet.battles), color_override=CYAN)
            self.stat_components.append(battles_label)
            current_y += line_height
        
        if "Win Rate" in self.visible_stats and self.pet.battles > 0:
            win_rate = (self.pet.win * 100) // self.pet.battles
            win_rate_label = LabelValue(padding, padding + current_y, 164, line_height, "Win Rate:", f"{win_rate}%", color_override=CYAN)
            self.stat_components.append(win_rate_label)
            current_y += line_height
        
        if "DP" in self.visible_stats:
            dp_label = LabelValue(padding, padding + current_y, 164, line_height, "DP:", str(self.pet.dp), color_override=CYAN)
            self.stat_components.append(dp_label)
            current_y += line_height
        
    def handle_event(self, event):
        """Block all events and close panel"""
        if not self.visible:
            return False
        
        # Block all events while visible and close panel
        if isinstance(event, tuple) and len(event) == 2:
            self.visible = False
            return True
            
        return True
                
        return True  # Block everything else too
    
    def render(self):
        """Render the stats panel with pet information - returns surface"""
        if not self.visible:
            return super().render()  # Return empty surface
        
        if not self.manager:
            return super().render()  # Return empty surface
        
        # Create surface at screen dimensions
        surface = pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
            
        # Get theme colors from manager
        colors = self.manager.get_theme_colors()
        bg_color = colors.get("bg", (0, 0, 0))
        fg_color = colors.get("fg", (255, 255, 255))
        
        # Draw panel background
        pygame.draw.rect(surface, bg_color, (0, 0, surface.get_width(), surface.get_height()))
        
        # Draw border
        border_width = 2
        pygame.draw.rect(surface, fg_color, pygame.Rect(0, 0, surface.get_width(), surface.get_height()), border_width)
        
        # Set manager for all child components and render them
        for component in self.stat_components:
            component.manager = self.manager
            
            # Scale the component's base rect to match current UI scale
            if component.base_rect is None:
                component.base_rect = component.rect.copy()
            
            # Component positions are absolute, convert to relative
            rel_x = component.base_rect.x
            rel_y = component.base_rect.y
            
            # Scale the position for blitting on scaled surface
            scaled_x = self.manager.scale_value(rel_x)
            scaled_y = self.manager.scale_value(rel_y)
            
            # Scale the full rect for rendering
            scaled_rect = self.manager.scale_rect(component.base_rect)
            component.rect = scaled_rect
            
            # Render the component
            component_surface = component.render()
            
            # Blit to panel surface at scaled position
            from utils.pygame_utils import blit_with_cache
            blit_with_cache(surface, component_surface, (scaled_x, scaled_y))
        
        return surface
