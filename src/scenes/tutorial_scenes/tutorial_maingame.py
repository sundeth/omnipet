"""
Tutorial Main Game Scene
Inherits from SceneMainGame and overrides input handling for tutorial control.
"""

from scenes.scene_maingame import SceneMainGame
from core import runtime_globals, game_globals


class TutorialMainGame(SceneMainGame):
    """
    Tutorial-controlled version of SceneMainGame.
    Overrides input handling to give tutorial full control.
    """
    
    def __init__(self) -> None:
        """Initialize the tutorial main game scene."""
        super().__init__()
        
        # Tutorial control flags
        self.allow_menu_selection = False
        self.allowed_menu_index = None  # Which menu index is allowed (None = any)
        self.on_menu_selected_callback = None
        self.allow_navigation = True
        self.on_cleaning_complete_callback = None  # Callback when cleaning animation finishes
        # The clock screensaver must never kick in mid-tutorial.
        self._screensaver_disabled = True
        
        runtime_globals.game_console.log("[TutorialMainGame] Tutorial main game scene initialized")
    
    def set_allow_menu_selection(self, allow: bool, allowed_index=None, callback=None):
        """
        Set whether menu selection is allowed.
        
        Args:
            allow: Whether any menu selection is allowed
            allowed_index: If set, only this menu index can be selected
            callback: Called when valid menu is selected
        """
        self.allow_menu_selection = allow
        self.allowed_menu_index = allowed_index
        self.on_menu_selected_callback = callback
    
    def set_allow_navigation(self, allow: bool):
        """Set whether menu navigation is allowed."""
        self.allow_navigation = allow
    
    def set_on_cleaning_complete(self, callback):
        """Set callback for when cleaning animation completes."""
        self.on_cleaning_complete_callback = callback
    
    def handle_event(self, event) -> bool:
        """
        Handle input events with tutorial control.
        Only allows actions that the tutorial has enabled.
        """
        if not isinstance(event, tuple) or len(event) != 2:
            return False
        event_type, event_data = event

        # Handle A button or click - menu selection
        if event_type in ["A", "LCLICK"]:
            if self.allow_menu_selection:
                # A click or tap selects the icon under it (only the mouse's
                # hover sets the index, so a tap left it at -1); one off the
                # icons selects nothing and is refused below.
                if event_type == "LCLICK" and isinstance(event_data, dict) and "pos" in event_data:
                    runtime_globals.main_menu_index = self.menu.get_menu_index_at(event_data["pos"])
                # Check if correct menu is selected
                current_index = runtime_globals.main_menu_index
                
                if self.allowed_menu_index is None or current_index == self.allowed_menu_index:
                    # Valid selection - notify tutorial callback
                    # Only call parent for actions that execute within this scene (like cleaning at index 4)
                    # Do NOT call parent for menu selections that would change_scene (indices 0-3, 5-8)
                    # as that would leave the tutorial
                    if current_index == 4:  # Cleaning - executes in current scene
                        result = super().handle_event(event)
                    else:
                        result = True  # Don't call parent - would trigger change_scene
                    
                    if self.on_menu_selected_callback:
                        self.on_menu_selected_callback(current_index)
                    return result
                else:
                    # Wrong menu - play cancel sound
                    if hasattr(runtime_globals, 'game_sound') and runtime_globals.game_sound:
                        runtime_globals.game_sound.play("cancel")
                    return True
            else:
                # Block all menu selection
                return True
        
        # Handle B button - typically does nothing in main game
        if event_type == "B":
            return True
        
        # Handle navigation
        if event_type in ["UP", "DOWN", "LEFT", "RIGHT"]:
            if self.allow_navigation:
                return super().handle_event(event)
            return True
        
        return True
    
    def update_cleaning(self) -> None:
        """Override cleaning update to notify tutorial when complete."""
        was_cleaning = self.cleaning
        super().update_cleaning()
        
        # Detect when cleaning just finished
        if was_cleaning and not self.cleaning:
            if self.on_cleaning_complete_callback:
                runtime_globals.game_console.log("[TutorialMainGame] Cleaning complete, notifying tutorial")
                self.on_cleaning_complete_callback()
    
    def get_menu_top_y(self):
        """Get the Y position of the top menu row in base 240 coordinates."""
        return 20 if game_globals.showClock else 5
    
    def get_menu_bottom_y(self):
        """Get the Y position of the bottom menu row in base 240 coordinates."""
        return 182  # 240 - 48 - 10
    
    def get_menu_icon_rect(self, index: int):
        """
        Get the bounds of a menu icon in base 240 coordinates.
        
        Args:
            index: Menu index 0-9
            
        Returns:
            Tuple (x, y, width, height)
        """
        # Icons are 48x48 at base resolution
        # Top row: indices 0-4 at y = get_menu_top_y()
        # Bottom row: indices 5-9 at y = 182
        icon_size = 48
        
        if index < 5:
            x = index * icon_size
            y = self.get_menu_top_y()
        else:
            x = (index - 5) * icon_size
            y = self.get_menu_bottom_y()
        
        return (x, y, icon_size, icon_size)
    
    def get_status_menu_rect(self):
        """Get Status menu icon bounds (index 0)."""
        return self.get_menu_icon_rect(0)
    
    def get_inventory_menu_rect(self):
        """Get Inventory menu icon bounds (index 1)."""
        return self.get_menu_icon_rect(1)
    
    def get_training_menu_rect(self):
        """Get Training menu icon bounds (index 2)."""
        return self.get_menu_icon_rect(2)
    
    def get_battle_menu_rect(self):
        """Get Battle menu icon bounds (index 3)."""
        return self.get_menu_icon_rect(3)
    
    def get_connect_menu_rect(self):
        """Get Connect menu icon bounds (index 8)."""
        return self.get_menu_icon_rect(8)
    
    def get_call_sign_rect(self):
        """Get Call Sign icon bounds (index 9)."""
        return self.get_menu_icon_rect(9)
