"""
Reward Popup UI Component
Shows quest rewards in animated popups using the UI component system.
"""
import pygame
import os
from typing import List, Dict
from ui.components.component import UIComponent
from ui.ui_constants import *
from core import runtime_globals
import core.constants as constants
from utils.pygame_utils import get_font
from utils.asset_utils import image_load
from utils.pygame_utils import blit_with_cache


class RewardPopupUI(UIComponent):
    """
    UI Component for displaying quest rewards in animated popups.
    """
    
    def __init__(self, x, y, width, height):
        super().__init__(x, y, width, height)
        
        self.reward_queue = []  # List of rewards to show
        self.current_reward = None  # Currently displayed reward
        self.show_timer = 0  # Timer for how long to show current reward
        self.fade_timer = 0  # Timer for fade in/out animation
        self.state = "hidden"  # hidden, fade_in, showing, fade_out
        
        # Load icons
        self.icons = {}
        self._load_icons()
        
        # This component is always visible but draws nothing when hidden
        self.visible = True
        self.focusable = True  # Focusable when active to capture input
        
    def _load_icons(self):
        """Load reward type icons."""
        try:
            # Trophy icon
            trophy_path = constants.TROPHIES_ICON_PATH
            if os.path.exists(trophy_path):
                self.icons['trophy'] = image_load(trophy_path).convert_alpha()
            
            # Heart icon for vital values
            heart_path = constants.HEART_FULL_ICON_PATH
            if os.path.exists(heart_path):
                self.icons['vital_values'] = image_load(heart_path).convert_alpha()
                
        except Exception as e:
            runtime_globals.game_console.log(f"[RewardPopupUI] Error loading icons: {e}")
    
    def add_rewards(self, rewards: List[Dict]):
        """Add a list of rewards to the display queue."""
        for reward in rewards:
            self.reward_queue.append(reward)
        
        # Start showing if not already active
        if self.state == "hidden" and self.reward_queue:
            self._start_next_reward()
    
    def _start_next_reward(self):
        """Start showing the next reward in the queue."""
        if not self.reward_queue:
            self.state = "hidden"
            self.current_reward = None
            return
            
        self.current_reward = self.reward_queue.pop(0)
        self.state = "fade_in"
        self.fade_timer = 0
        self.show_timer = 0
        self.needs_redraw = True
        
        # Play reward sound
        runtime_globals.game_sound.play("happy")
    
    def update(self):
        """Update the popup animation and timing."""
        if self.state == "hidden":
            return
            
        fade_duration = 15  # 15 frames for fade
        show_duration = 120  # frames: 4 s at the default 30 fps, 2 s at 60
        
        if self.state == "fade_in":
            self.fade_timer += 1
            self.needs_redraw = True
            if self.fade_timer >= fade_duration:
                self.state = "showing"
                self.show_timer = 0
                
        elif self.state == "showing":
            self.show_timer += 1
            if self.show_timer >= show_duration:
                self.state = "fade_out"
                self.fade_timer = fade_duration
                self.needs_redraw = True
                
        elif self.state == "fade_out":
            self.fade_timer -= 1
            self.needs_redraw = True
            if self.fade_timer <= 0:
                # Start next reward or hide
                self._start_next_reward()
    
    def render(self):
        """Render the current reward popup to a surface."""
        # Create/reuse transparent surface
        target_size = (self.rect.width, self.rect.height)
        if not hasattr(self, "_render_surface") or self._render_surface is None or self._render_surface.get_size() != target_size:
            self._render_surface = pygame.Surface(target_size, pygame.SRCALPHA)
        surface = self._render_surface
        surface.fill((0, 0, 0, 0))
        
        if self.state == "hidden" or not self.current_reward:
            return surface
        
        # Calculate fade alpha
        fade_duration = 15
        if self.state == "fade_in":
            alpha = int(255 * (self.fade_timer / fade_duration))
        elif self.state == "fade_out":
            alpha = int(255 * (self.fade_timer / fade_duration))
        else:
            alpha = 255
            
        alpha = max(0, min(255, alpha))
        
        # Draw popup background
        background_color = (40, 40, 40, alpha)
        border_color = (*GREEN, alpha)
        
        popup_rect = pygame.Rect(0, 0, self.rect.width, self.rect.height)
        pygame.draw.rect(surface, background_color, popup_rect)
        border_width = self.manager.scale_value(2) if self.manager else 2
        pygame.draw.rect(surface, border_color, popup_rect, border_width)
        
        # Draw reward content
        self._render_reward_content(surface, alpha)
        
        return surface
    
    def _render_reward_content(self, surface, alpha):
        """Render the reward content on the popup surface."""
        reward = self.current_reward
        if not reward:
            return
            
        padding = self.manager.scale_value(8) if self.manager else 8
        
        # Draw "REWARD!" title
        title_font = get_font(runtime_globals.FONT_SIZE_MEDIUM)
        title_text = title_font.render("REWARD!", True, YELLOW)
        title_text.set_alpha(alpha)
        title_x = (surface.get_width() - title_text.get_width()) // 2
        blit_with_cache(surface, title_text, (title_x, padding))
        
        # Draw reward based on type
        reward_type = reward["reward_type"]
        reward_quantity = reward["reward_quantity"]
        reward_value = reward["reward_value"]
        
        content_y = padding + title_text.get_height() + (self.manager.scale_value(4) if self.manager else 4)
        
        if reward_type == "ITEM":
            self._render_item_reward(surface, reward_value, reward_quantity, content_y, alpha)
        elif reward_type == "TROPHY":
            self._render_icon_reward(surface, "trophy", f"+{reward_quantity} Trophies", content_y, alpha)
        elif reward_type == "EXPERIENCE":
            self._render_text_reward(surface, f"+{reward_quantity} EXP", content_y, alpha)
        elif reward_type == "VITAL_VALUES":
            self._render_icon_reward(surface, "vital_values", f"+{reward_quantity} Vital Values", content_y, alpha)
    
    def _render_item_reward(self, surface, item_name: str, quantity: int, y: int, alpha: int):
        """Render item reward with icon if available."""
        text = f"+{quantity}x {item_name}"
        self._render_text_reward(surface, text, y, alpha)
    
    def _render_icon_reward(self, surface, icon_type: str, text: str, y: int, alpha: int):
        """Render reward with icon and text."""
        icon = self.icons.get(icon_type)
        if icon:
            # Scale icon
            icon_size = self.manager.scale_value(32) if self.manager else 32
            icon_scaled = pygame.transform.scale(icon, (icon_size, icon_size))
            icon_scaled.set_alpha(alpha)
            
            # Render text
            reward_font = get_font(runtime_globals.FONT_SIZE_SMALL)
            text_surface = reward_font.render(text, True, (255, 255, 255))
            text_surface.set_alpha(alpha)
            
            # Calculate positions
            spacing = self.manager.scale_value(8) if self.manager else 8
            total_width = icon_scaled.get_width() + spacing + text_surface.get_width()
            start_x = (surface.get_width() - total_width) // 2
            
            # Draw icon
            icon_y = y + (text_surface.get_height() - icon_scaled.get_height()) // 2
            blit_with_cache(surface, icon_scaled, (start_x, icon_y))
            
            # Draw text
            text_x = start_x + icon_scaled.get_width() + spacing
            blit_with_cache(surface, text_surface, (text_x, y))
        else:
            # Fallback to text only
            self._render_text_reward(surface, text, y, alpha)
    
    def _render_text_reward(self, surface, text: str, y: int, alpha: int):
        """Render text-only reward."""
        reward_font = get_font(runtime_globals.FONT_SIZE_SMALL)
        text_surface = reward_font.render(text, True, (255, 255, 255))
        text_surface.set_alpha(alpha)
        text_x = (surface.get_width() - text_surface.get_width()) // 2
        blit_with_cache(surface, text_surface, (text_x, y))
    
    def is_active(self) -> bool:
        """Check if the popup system is currently showing rewards."""
        return self.state != "hidden" or len(self.reward_queue) > 0
    
    def handle_event(self, event):
        """Handle input events - capture all input when active to prevent interaction with other components."""
        if not self.is_active():
            return False
            
        # Handle tuple-based events
        if not isinstance(event, tuple) or len(event) != 2:
            return False
            
        event_type, event_data = event
            
        # Consume all input when popup is active
        # Pressing A or B will skip the current reward
        if event_type in ["A", "B"]:
            # Skip to next reward
            if self.state in ["showing", "fade_in"]:
                self.state = "fade_out"
                self.fade_timer = 15
                self.needs_redraw = True
                return True
            # Consume all other input actions
            return True
            
        # Consume all pygame events (mouse clicks, etc.)
        if hasattr(event, 'type'):
            return True
            
        return False
