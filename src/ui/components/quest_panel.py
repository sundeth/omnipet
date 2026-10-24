"""
Quest Panel Component
Displays a single quest with interactive claim functionality.
"""
import pygame
import os
from ui.components.component import UIComponent
from ui.ui_constants import *
from core import runtime_globals
import core.constants as constants
from models.game_quest import QuestStatus, RewardType
from utils.pygame_utils import blit_with_cache, blit_with_shadow, get_font
from utils.asset_utils import image_load


class QuestPanel(UIComponent):
    """
    A panel that displays quest information and allows claiming rewards.
    """
    
    def __init__(self, x, y, width, height, on_claim=None):
        super().__init__(x, y, width, height)
        
        self.quest = None
        self.on_claim = on_claim
        self.focusable = False  # Only focusable when quest is claimable
        self.focused = False
        
        # Visual settings
        self.base_padding = 4
        self.padding = self.base_padding
        
        # Load icons
        self.trophy_icon = None
        self.heart_icon = None
        self._load_icons()
        
    def _load_icons(self):
        """Load reward icons."""
        try:
            # Trophy icon
            trophy_path = constants.TROPHIES_ICON_PATH
            if os.path.exists(trophy_path):
                self.trophy_icon = image_load(trophy_path).convert_alpha()
                
            # Heart icon for vital values
            heart_path = constants.HEART_FULL_ICON_PATH
            if os.path.exists(heart_path):
                self.heart_icon = image_load(heart_path).convert_alpha()
                
        except Exception as e:
            runtime_globals.game_console.log(f"[QuestPanel] Error loading icons: {e}")
    
    def _load_item_icon(self):
        """Load item icon for quest reward."""
        if not self.quest or self.quest.reward_type != RewardType.ITEM:
            return None
            
        try:
            from utils.inventory_utils import get_item_by_name
            item_instance = get_item_by_name(self.quest.module, self.quest.reward_value)
            
            if item_instance:
                item_sprite_path = f"modules/{self.quest.module}/items/{item_instance.sprite_name}.png"
                if os.path.exists(item_sprite_path):
                    item_icon = image_load(item_sprite_path).convert_alpha()
                    return item_icon
        except Exception as e:
            runtime_globals.game_console.log(f"[QuestPanel] Error loading item icon: {e}")
            
        return None
    
    def set_quest(self, quest):
        """Set the quest to display."""
        # Only mark for redraw if quest actually changed
        if self.quest != quest:
            self.quest = quest
            
            # Update focusable state - only focusable when quest is completed but not claimed
            if quest and quest.status == QuestStatus.SUCCESS:
                self.focusable = True
            else:
                self.focusable = False
                self.focused = False
            
            self.needs_redraw = True
        else:
            self.quest = quest
    
    def get_border_color(self):
        """Get the border color based on quest status."""
        if not self.quest:
            return GRAY
            
        if self.quest.status == QuestStatus.SUCCESS:
            return GREEN
        elif self.quest.status == QuestStatus.FINISHED:
            return GRAY
        elif self.quest.current_amount > 0:
            return YELLOW
        else:
            return RED
    
    def handle_event(self, event):
        """Handle click events for claiming rewards."""
        # Only handle if focused and claimable
        if not self.focusable or not self.focused:
            return False
            
        # Handle tuple-based events
        if not isinstance(event, tuple) or len(event) != 2:
            return False
            
        event_type, event_data = event
            
        # Handle mouse clicks
        if event_type == "LCLICK":
            if event_data and "pos" in event_data:
                # Check if click is within bounds
                if self.rect.collidepoint(event_data["pos"]):
                    if self.on_claim and self.quest:
                        self.on_claim(self.quest)
                        runtime_globals.game_sound.play("menu")
                    return True
        
        # A on the focused panel claims it. The game hands events on as
        # (action, data) tuples; this branch used to test for the bare string
        # "A", which never arrives, so only taps and START (claim all) worked.
        elif event_type == "A":
            if self.on_claim and self.quest and self.quest.status == QuestStatus.SUCCESS:
                self.on_claim(self.quest)
                runtime_globals.game_sound.play("menu")
            return True

        return False
    
    def render(self):
        """Render the quest panel to a surface."""
        if getattr(self, 'cached_surface', None) is None or self.cached_surface.get_size() != (self.rect.width, self.rect.height):
            self.cached_surface = pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
        surface = self.cached_surface
        
        # Get scaled values
        padding = int(self.base_padding * self.manager.ui_scale) if self.manager else self.base_padding
        
        # Draw background
        background_color = (40, 40, 40) if self.quest else (30, 30, 30)
        pygame.draw.rect(surface, background_color, (0, 0, self.rect.width, self.rect.height))
        
        # Draw border with status color
        border_color = self.get_border_color()
        border_width = int(2 * self.manager.ui_scale) if self.manager else 2
        
        # Highlight when focused and claimable
        if self.focused and self.focusable:
            # Draw thicker yellow highlight border
            pygame.draw.rect(surface, YELLOW, (0, 0, self.rect.width, self.rect.height), border_width + 1)
        else:
            pygame.draw.rect(surface, border_color, (0, 0, self.rect.width, self.rect.height), border_width)
        
        # Draw quest content or empty message
        if self.quest:
            self._render_quest_content(surface, padding)
        else:
            self._render_empty_content(surface)
            
        return surface
    
    def _render_quest_content(self, surface, padding):
        """Render the quest information on the surface."""
        # Quest title (top left) - larger font
        title_font = self.get_font(custom_size=24* self.manager.ui_scale)
        title_text = self.quest.name[:20]  # Limit length
        title_surface = title_font.render(title_text, True, (255, 255, 255))
        from utils.pygame_utils import blit_with_cache
        blit_with_cache(surface, title_surface, (padding, padding))
        
        # Module name or status (bottom left)
        module_font = self.get_font()
        if self.quest.status == QuestStatus.SUCCESS:
            status_text = "CLAIM"
            status_color = GREEN
        elif self.quest.status == QuestStatus.FINISHED:
            status_text = "DONE"
            status_color = GRAY
        else:
            status_text = self.quest.module.upper()
            status_color = GRAY
            
        status_surface = module_font.render(status_text, True, status_color)
        status_y = self.rect.height - padding - status_surface.get_height()
        blit_with_cache(surface, status_surface, (padding, status_y))
        
        # Quest progress (top right)
        progress_font = self.get_font(custom_size=24* self.manager.ui_scale)
        if self.quest.status == QuestStatus.FINISHED:
            progress_text = "✓"
            progress_color = GRAY
        else:
            progress_text = f"{self.quest.current_amount}/{self.quest.target_amount}"
            progress_color = (255, 255, 255)
            
        progress_surface = progress_font.render(progress_text, True, progress_color)
        progress_x = self.rect.width - padding - progress_surface.get_width()
        blit_with_cache(surface, progress_surface, (progress_x, padding))
        
        # Quest reward (bottom right)
        self._render_reward(surface, padding)
    
    def _render_reward(self, surface, padding):
        """Render the quest reward information."""
        if not self.quest:
            return
            
        reward_font = self.get_font(custom_size=16* self.manager.ui_scale)
        
        if self.quest.reward_type == RewardType.ITEM:
            # Try to load item icon
            item_icon = self._load_item_icon()
            if item_icon:
                # Show item icon and quantity
                self._render_icon_reward(surface, item_icon, f"x{self.quest.reward_quantity}", padding)
            else:
                # Fallback: Show quantity as text
                reward_text = f"x{self.quest.reward_quantity}"
                reward_surface = reward_font.render(reward_text, True, (255, 255, 255))
                reward_x = self.rect.width - padding - reward_surface.get_width()
                reward_y = self.rect.height - padding - reward_surface.get_height()
                blit_with_cache(surface, reward_surface, (reward_x, reward_y))
            
        elif self.quest.reward_type == RewardType.EXPERIENCE:
            # Show EXP value
            reward_text = f"{self.quest.reward_value} EXP"
            reward_surface = reward_font.render(reward_text, True, (255, 255, 255))
            reward_x = self.rect.width - padding - reward_surface.get_width()
            reward_y = self.rect.height - padding - reward_surface.get_height()
            blit_with_cache(surface, reward_surface, (reward_x, reward_y))
            
        elif self.quest.reward_type == RewardType.TROPHY:
            # Show trophy icon + value
            if self.trophy_icon:
                self._render_icon_reward(surface, self.trophy_icon, str(self.quest.reward_value), padding)
            else:
                reward_text = str(self.quest.reward_value)
                reward_surface = reward_font.render(reward_text, True, (255, 255, 255))
                reward_x = self.rect.width - padding - reward_surface.get_width()
                reward_y = self.rect.height - padding - reward_surface.get_height()
                blit_with_cache(surface, reward_surface, (reward_x, reward_y))
                
        elif self.quest.reward_type == RewardType.VITAL_VALUES:
            # Show heart icon + value
            if self.heart_icon:
                self._render_icon_reward(surface, self.heart_icon, str(self.quest.reward_value), padding)
            else:
                reward_text = f"{self.quest.reward_value} VV"
                reward_surface = reward_font.render(reward_text, True, (255, 255, 255))
                reward_x = self.rect.width - padding - reward_surface.get_width()
                reward_y = self.rect.height - padding - reward_surface.get_height()
                blit_with_cache(surface, reward_surface, (reward_x, reward_y))
    
    def _render_icon_reward(self, surface, icon, text, padding):
        """Render reward with icon and text."""
        reward_font = self.get_font(custom_size=16* self.manager.ui_scale)
        
        # Scale icon
        icon_size = int(20 * self.manager.ui_scale) if self.manager else 20
        scaled_icon = pygame.transform.scale(icon, (icon_size, icon_size))
        
        # Render text
        text_surface = reward_font.render(text, True, (255, 255, 255))
        
        # Calculate positions (icon at bottom right, text to its left)
        icon_x = self.rect.width - padding - scaled_icon.get_width()
        icon_y = self.rect.height - padding - scaled_icon.get_height()
        
        text_x = icon_x - text_surface.get_width() - 2
        text_y = self.rect.height - padding - text_surface.get_height()
        
        # Draw
        blit_with_cache(surface, scaled_icon, (icon_x, icon_y))
        blit_with_cache(surface, text_surface, (text_x, text_y))
    
    def _render_empty_content(self, surface):
        """Render empty quest slot message."""
        empty_font = self.get_font("text")
        empty_text = "No quest"
        empty_surface = empty_font.render(empty_text, True, GRAY)
        
        # Center the text
        text_x = self.rect.width // 2 - empty_surface.get_width() // 2
        text_y = self.rect.height // 2 - empty_surface.get_height() // 2
        
        blit_with_cache(surface, empty_surface, (text_x, text_y))
    
    def draw_scaled(self, surface):
        """Draw the quest panel."""
        if not self.manager:
            return
            
        # Get scaled values
        scaled_padding = self.manager.scale_value(self.padding)
        
        # Draw background
        background_color = (40, 40, 40) if self.quest else (30, 30, 30)
        pygame.draw.rect(surface, background_color, self.rect)
        
        # Draw border with status color
        border_color = self.get_border_color()
        border_width = self.manager.scale_value(2)
        
        # Highlight when focused and claimable
        if self.focused and self.focusable:
            # Draw thicker yellow highlight border
            pygame.draw.rect(surface, YELLOW, self.rect, border_width + self.manager.scale_value(1))
        else:
            pygame.draw.rect(surface, border_color, self.rect, border_width)
        
        # Draw quest content or empty message
        if self.quest:
            self._draw_quest_content(surface, scaled_padding)
        else:
            self._draw_empty_content(surface)
    
    def _draw_quest_content(self, surface, padding):
        """Draw the quest information."""
        # Quest title (top left) - larger font
        title_font = get_font(runtime_globals.FONT_SIZE_MEDIUM_LARGE)
        title_text = self.quest.name[:20]  # Limit length
        title_surface = title_font.render(title_text, True, (255, 255, 255))
        blit_with_shadow(surface, title_surface, (self.rect.x + padding, self.rect.y + padding))
        
        # Module name or status (bottom left)
        module_font = get_font(runtime_globals.FONT_SIZE_SMALL* self.manager.ui_scale)
        if self.quest.status == QuestStatus.SUCCESS:
            status_text = "READY TO CLAIM"
            status_color = GREEN
        elif self.quest.status == QuestStatus.FINISHED:
            status_text = "DONE"
            status_color = GRAY
        else:
            status_text = self.quest.module.upper()
            status_color = GRAY
            
        status_surface = module_font.render(status_text, True, status_color)
        status_y = self.rect.bottom - padding - status_surface.get_height()
        blit_with_shadow(surface, status_surface, (self.rect.x + padding, status_y))
        
        # Quest progress (top right)
        progress_font = get_font(runtime_globals.FONT_SIZE_MEDIUM* self.manager.ui_scale)
        if self.quest.status == QuestStatus.FINISHED:
            progress_text = "DONE"
            progress_color = GRAY
        else:
            progress_text = f"{self.quest.current_amount}/{self.quest.target_amount}"
            progress_color = (255, 255, 255)
            
        progress_surface = progress_font.render(progress_text, True, progress_color)
        progress_x = self.rect.right - padding - progress_surface.get_width()
        blit_with_shadow(surface, progress_surface, (progress_x, self.rect.y + padding))
        
        # Quest reward (bottom right)
        self._draw_reward(surface, padding)
    
    def _draw_reward(self, surface, padding):
        """Draw the quest reward information."""
        if not self.quest:
            return
            
        reward_font = get_font(runtime_globals.FONT_SIZE_SMALL* self.manager.ui_scale)
        
        if self.quest.reward_type == RewardType.ITEM:
            # Try to load item icon
            item_icon = self._load_item_icon()
            if item_icon:
                # Show item icon and quantity
                self._draw_icon_reward(surface, item_icon, f"x{self.quest.reward_quantity}", padding)
            else:
                # Fallback: Show quantity as text
                reward_text = f"x{self.quest.reward_quantity}"
                reward_surface = reward_font.render(reward_text, True, (255, 255, 255))
                reward_x = self.rect.right - padding - reward_surface.get_width()
                reward_y = self.rect.bottom - padding - reward_surface.get_height()
                blit_with_shadow(surface, reward_surface, (reward_x, reward_y))
            
        elif self.quest.reward_type == RewardType.EXPERIENCE:
            # Show EXP value
            reward_text = f"{self.quest.reward_value} EXP"
            reward_surface = reward_font.render(reward_text, True, (255, 255, 255))
            reward_x = self.rect.right - padding - reward_surface.get_width()
            reward_y = self.rect.bottom - padding - reward_surface.get_height()
            blit_with_shadow(surface, reward_surface, (reward_x, reward_y))
            
        elif self.quest.reward_type == RewardType.TROPHY:
            # Show trophy icon + value
            if self.trophy_icon:
                self._draw_icon_reward(surface, self.trophy_icon, str(self.quest.reward_value), padding)
            else:
                reward_text = str(self.quest.reward_value)
                reward_surface = reward_font.render(reward_text, True, (255, 255, 255))
                reward_x = self.rect.right - padding - reward_surface.get_width()
                reward_y = self.rect.bottom - padding - reward_surface.get_height()
                blit_with_shadow(surface, reward_surface, (reward_x, reward_y))
                
        elif self.quest.reward_type == RewardType.VITAL_VALUES:
            # Show heart icon + value
            if self.heart_icon:
                self._draw_icon_reward(surface, self.heart_icon, str(self.quest.reward_value), padding)
            else:
                reward_text = f"{self.quest.reward_value} VV"
                reward_surface = reward_font.render(reward_text, True, (255, 255, 255))
                reward_x = self.rect.right - padding - reward_surface.get_width()
                reward_y = self.rect.bottom - padding - reward_surface.get_height()
                blit_with_shadow(surface, reward_surface, (reward_x, reward_y))
    
    def _draw_icon_reward(self, surface, icon, text, padding):
        """Draw reward with icon and text."""
        reward_font = get_font(runtime_globals.FONT_SIZE_SMALL* self.manager.ui_scale)
        
        # Scale icon
        icon_size = self.manager.scale_value(20)
        scaled_icon = pygame.transform.scale(icon, (icon_size, icon_size))
        
        # Render text
        text_surface = reward_font.render(text, True, (255, 255, 255))
        text_surface = self.manager.scale_surface(text_surface)
        
        # Calculate positions (icon at bottom right, text to its left)
        icon_x = self.rect.right - padding - scaled_icon.get_width()
        icon_y = self.rect.bottom - padding - scaled_icon.get_height()
        
        text_x = icon_x - text_surface.get_width() - self.manager.scale_value(2)
        text_y = self.rect.bottom - padding - text_surface.get_height()
        
        # Draw
        blit_with_shadow(surface, scaled_icon, (icon_x, icon_y))
        blit_with_shadow(surface, text_surface, (text_x, text_y))
    
    def _draw_empty_content(self, surface):
        """Draw empty quest slot message."""
        empty_font = get_font(runtime_globals.FONT_SIZE_MEDIUM)
        empty_text = "No quest available"
        empty_surface = empty_font.render(empty_text, True, GRAY)
        empty_surface = self.manager.scale_surface(empty_surface)
        
        # Center the text
        text_x = self.rect.centerx - empty_surface.get_width() // 2
        text_y = self.rect.centery - empty_surface.get_height() // 2
        
        blit_with_shadow(surface, empty_surface, (text_x, text_y))
