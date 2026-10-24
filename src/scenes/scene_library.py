"""
Scene Library
Displays daily quests, with navigation to Digidex, Freezer, and Settings.
Refactored to use the new UI system with bright yellow theme.
"""

import os
import pygame

from ui.ui_manager import UIManager
from ui.components.background import Background
from ui.components.title_scene import TitleScene
from ui.components.button import Button
from ui.components.quest_panel import QuestPanel
from ui.components.reward_popup_ui import RewardPopupUI
from ui.ui_constants import BASE_RESOLUTION
from ui.windows.window_background import WindowBackground
from core import game_globals, runtime_globals
import core.constants as constants
from utils.scene_utils import change_scene
from models.game_quest import QuestStatus

#=====================================================================
# SceneLibrary
#=====================================================================
class SceneLibrary:
    """
    Scene for displaying daily quests and providing access to Digidex, Freezer, and Settings.
    Refactored to use the new UI system.
    """

    def __init__(self) -> None:
        """
        Initializes the library scene with UI components.
        """
        # Global background
        self.window_background = WindowBackground()
        
        # UI Manager with bright yellow theme
        self.ui_manager = UIManager(theme="YELLOW_BRIGHT")
        
        # Connect input manager to UI manager for mouse handling
        self.ui_manager.set_input_manager(runtime_globals.game_input)
        
        # UI Components
        self.background = None
        self.title_scene = None
        self.quest_panels = []  # 3 quest panels
        self.reward_popup = None
        self.freezer_button = None
        self.digidex_button = None
        self.settings_button = None
        self.exit_button = None
        
        self._setup_ui()
        
        runtime_globals.game_console.log("[SceneLibrary] Library scene initialized with UI system (YELLOW_BRIGHT theme).")
    
    def _setup_ui(self):
        """Setup UI components for the library scene."""
        ui_width = ui_height = BASE_RESOLUTION
        
        # Background with dark yellow region behind quest panels
        self.background = Background(ui_width, ui_height)
        # Quest panels area: y=30 to y=180, add dark yellow region
        self.background.set_regions([
            (0, ui_height, "black")
        ])
        self.ui_manager.add_component(self.background)
        
        # Title
        self.title_scene = TitleScene(0, 9, "LIBRARY")
        self.ui_manager.add_component(self.title_scene)
        
        # Quest panels (3 panels stacked vertically)
        # Title ends around y=30, buttons start at y=188, so we have ~158 pixels for quests
        # 3 panels with 2px spacing = (158 - 4) / 3 = ~51 pixels per panel
        quest_start_y = 28
        quest_height = 45
        quest_spacing = 5
        quest_width = ui_width - 16  # 8px margin on each side
        
        for i in range(3):
            quest_y = quest_start_y + (i * (quest_height + quest_spacing))
            quest_panel = QuestPanel(8, quest_y, quest_width, quest_height, on_claim=self._on_quest_claim)
            
            # Set quest if available
            if i < len(game_globals.quests):
                quest_panel.set_quest(game_globals.quests[i])
            
            self.quest_panels.append(quest_panel)
            self.ui_manager.add_component(quest_panel)
        
        # Bottom buttons (4 buttons side by side)
        button_y = 180
        button_width = 52
        button_height = 52
        button_spacing = 8
        total_width = (button_width * 4) + (button_spacing * 3)
        start_x = (ui_width - total_width) // 2
        
        # Freezer button (icon)
        self.freezer_button = Button(
            start_x, button_y, button_width, button_height,
            "", self._on_freezer,
            decorators=["Library_Freezer"]
        )
        self.ui_manager.add_component(self.freezer_button)
        
        # Digidex button (icon)
        digidex_x = start_x + button_width + button_spacing
        self.digidex_button = Button(
            digidex_x, button_y, button_width, button_height,
            "", self._on_digidex,
            decorators=["Library_Digidex"]
        )
        self.ui_manager.add_component(self.digidex_button)
        
        # Settings button (icon)
        settings_x = digidex_x + button_width + button_spacing
        self.settings_button = Button(
            settings_x, button_y, button_width, button_height,
            "", self._on_settings,
            decorators=["Library_Settings"]
        )
        self.ui_manager.add_component(self.settings_button)
        
        # Collection button (takes the old EXIT slot; B still exits, and the
        # small back arrow next to the title covers touch users)
        collection_x = settings_x + button_width + button_spacing
        self.collection_button = Button(
            collection_x, button_y, button_width, button_height,
            "", self._on_collection,
            decorators=["Library_Collection"]
        )
        self.ui_manager.add_component(self.collection_button)

        # EXIT button next to the title (same style/placement as the Digidex)
        exit_button_width = 50
        exit_button_height = 20
        self.exit_button = Button(ui_width - exit_button_width - 5, 5,
                                  exit_button_width, exit_button_height,
                                  "EXIT", self._on_exit)
        self.ui_manager.add_component(self.exit_button)
        
        # Reward popup (centered, overlays everything)
        popup_width = 200
        popup_height = 80
        popup_x = (ui_width - popup_width) // 2
        popup_y = 60
        self.reward_popup = RewardPopupUI(popup_x, popup_y, popup_width, popup_height)
        self.ui_manager.add_component(self.reward_popup)
        
        # Update quest panels with current quests
        self._update_quest_panels()
        
        # Set mouse mode and initial focus
        if self.freezer_button:
            self.ui_manager.set_focused_component(self.freezer_button)

    def _update_quest_panels(self):
        """Update quest panels with current quests."""
        for i, panel in enumerate(self.quest_panels):
            if i < len(game_globals.quests):
                panel.set_quest(game_globals.quests[i])
            else:
                panel.set_quest(None)
    
    def update(self) -> None:
        """Updates the library scene."""
        # The Library left open past midnight shows the new day's quests
        # (checked once a second, as the main scene does).
        self._frames = getattr(self, "_frames", 0) + 1
        if self._frames % constants.FRAME_RATE == 0:
            from utils.quest_event_utils import ensure_daily_quests, roll_over_day
            if roll_over_day():
                ensure_daily_quests()
        # Update quest panels if quests have changed
        self._update_quest_panels()
        
        self.ui_manager.update()

    def draw(self, surface: pygame.Surface) -> None:
        """Draws the library scene."""
        # Draw global background layer
        self.window_background.draw(surface)
        
        # Draw UI components (includes quest panels, buttons, and reward popup)
        self.ui_manager.draw(surface)

    def _on_quest_claim(self, quest):
        """Handle quest claim button press."""
        if quest and quest.status == QuestStatus.SUCCESS:
            # Claim the specific quest
            from utils.quest_event_utils import complete_quest
            reward = complete_quest(quest.id)
            if reward:
                self.reward_popup.add_rewards([reward])
                # Increment quest completion counter for all pets
                for pet in game_globals.pet_list:
                    pet.quests_completed += 1
                runtime_globals.game_sound.play("menu")
            self._update_quest_panels()
    
    def _on_freezer(self):
        """Handle Freezer button press."""
        runtime_globals.game_sound.play("menu")
        change_scene("freezer")
    
    def _on_digidex(self):
        """Handle Digidex button press."""
        runtime_globals.game_sound.play("menu")
        change_scene("digidex")
    
    def _on_settings(self):
        """Handle Settings button press."""
        runtime_globals.game_sound.play("menu")
        change_scene("settings")

    def _on_collection(self):
        """Handle Collection (CARDS) button press."""
        runtime_globals.game_sound.play("menu")
        change_scene("collection")
    
    def _on_exit(self):
        """Handle EXIT button press."""
        runtime_globals.game_sound.play("cancel")
        change_scene("game")
    
    def handle_event(self, event) -> None:
        """Handle input events."""
        if not isinstance(event, tuple) or len(event) != 2:
            return
        
        event_type, event_data = event
        
        # If reward popup is active, let it handle all input first (modal behavior)
        if self.reward_popup and self.reward_popup.is_active():
            if self.reward_popup.handle_event(event):
                return
        
        # Handle events through UI manager
        if self.ui_manager.handle_event(event):
            return
        
        # START button - Claim all completed quests
        if event_type == "START":
            from utils.quest_event_utils import claim_all_completed_quests
            rewards = claim_all_completed_quests()
            if rewards:
                self.reward_popup.add_rewards(rewards)
                # Increment quest completion counter for all pets
                for pet in game_globals.pet_list:
                    pet.quests_completed += len(rewards)
                runtime_globals.game_sound.play("menu")
                self._update_quest_panels()
            return
        elif event_type == "B":
            runtime_globals.game_sound.play("cancel")
            change_scene("game")
            return
