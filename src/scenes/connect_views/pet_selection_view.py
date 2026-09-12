"""
PetSelectionView - Pet selection for battles
Allows selecting pets for WiFi or Discord battles
"""
from ui.ui_manager import UIManager
from ui.components.title_scene import TitleScene
from ui.components.button import Button
from ui.components.background import Background
from ui.components.label import Label
from ui.components.pet_selector import PetSelector
from ui.ui_constants import BASE_RESOLUTION
from core import runtime_globals
from utils.pet_utils import get_battle_pvp_targets, get_wificom_battle_targets


class PetSelectionView:
    """Pet selection view for WiFi/Discord battles."""
    
    def __init__(self, ui_manager: UIManager, change_view_callback, 
                 is_online_mode=False, is_dcom_mode=False, is_wificom_mode=False,
                 max_pets=4, return_view="main_menu", discord_module=None):
        """Initialize the pet selection view.
        
        Args:
            ui_manager: The UI manager instance
            change_view_callback: Callback to change to another view
            is_online_mode: True if this is an online (Discord) battle
            is_dcom_mode: True if this is a DCom battle
            is_wificom_mode: True if this is a WiFiCom battle.  Narrows the
                list further than DCom does -- see get_wificom_battle_targets.
            max_pets: Maximum number of pets that can be selected
            return_view: View to return to on back (e.g., "main_menu" or submenu hint)
        """
        self.ui_manager = ui_manager
        self.change_view = change_view_callback
        self.is_online_mode = is_online_mode
        self.is_dcom_mode = is_dcom_mode
        self.is_wificom_mode = is_wificom_mode
        # Both device modes battle one pet against one toy.
        self.max_pets = 1 if (is_dcom_mode or is_wificom_mode) else max_pets
        self.return_view = return_view
        
        # Selected pets
        self.selected_pets = []
        
        # UI Components
        self.background = None
        self.title_scene = None
        self.pet_selector = None
        self.instructions_label = None
        self.confirm_button = None
        self.back_button = None
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup the UI components."""
        ui_width = ui_height = BASE_RESOLUTION
        
        # Background
        self.background = Background(ui_width, ui_height)
        self.background.set_regions([(0, ui_height, "black")])
        self.ui_manager.add_component(self.background)
        
        # Title
        self.title_scene = TitleScene(0, 9, "CONNECT")
        self.ui_manager.add_component(self.title_scene)
        
        # Pet selector
        selector_width = 220
        selector_height = 120
        selector_x = (BASE_RESOLUTION - selector_width) // 2
        selector_y = 40
        
        self.pet_selector = PetSelector(selector_x, selector_y, selector_width, selector_height)
        # A WiFiCom battle announces the pet to a real device, so the pet
        # needs a protocol to speak and a roster entry to claim.
        eligible = (get_wificom_battle_targets() if self.is_wificom_mode
                    else get_battle_pvp_targets())
        self.pet_selector.set_pets(eligible)
        # The cap the view already knew about, told to the thing that
        # enforces it. Both device modes battle one pet against one toy, and
        # the packets only ever describe the first.
        self.pet_selector.max_selection = self.max_pets
        self.pet_selector.set_interactive(True)
        self.ui_manager.add_component(self.pet_selector)
        
        # Instructions
        if self.is_wificom_mode:
            if eligible:
                instruction_text = "Select 1 pet for WiFiCom battle"
            else:
                # Nothing qualifies, and the reason is not obvious from an
                # empty selector.
                instruction_text = "No pet can use WiFiCom yet"
        elif self.is_dcom_mode:
            instruction_text = "Select 1 pet for DCom battle"
        else:
            instruction_text = f"Select up to {self.max_pets} pets. Press START when ready."
        
        self.instructions_label = Label(10, 165, instruction_text, is_title=False)
        self.ui_manager.add_component(self.instructions_label)
        
        # Confirm button
        confirm_width = 100
        confirm_height = 35
        confirm_x = 20
        confirm_y = 195
        
        self.confirm_button = Button(
            confirm_x, confirm_y, confirm_width, confirm_height,
            "CONFIRM", self._on_confirm
        )
        self.ui_manager.add_component(self.confirm_button)
        
        # Back button
        back_width = 80
        back_height = 35
        back_x = BASE_RESOLUTION - back_width - 20
        back_y = 195
        
        self.back_button = Button(
            back_x, back_y, back_width, back_height,
            "BACK", self._on_back
        )
        self.ui_manager.add_component(self.back_button)
        
        runtime_globals.game_console.log("[PetSelectionView] UI setup complete")
        
        # Set initial keyboard focus on the pet selector
        if self.pet_selector:
            self.ui_manager.set_focused_component(self.pet_selector)
    
    def _on_confirm(self):
        """Confirm button clicked."""
        # Get selected pets from selector
        self.selected_pets = self.pet_selector.get_selected_pets() if hasattr(self.pet_selector, 'get_selected_pets') else []
        
        if not self.selected_pets:
            runtime_globals.game_console.log("[PetSelectionView] No pets selected")
            return
        
        runtime_globals.game_sound.play("menu")
        runtime_globals.game_console.log(f"[PetSelectionView] Selected {len(self.selected_pets)} pets")
        
        if self.is_wificom_mode:
            self.change_view("wificom", selected_pets=self.selected_pets)
        elif self.is_dcom_mode:
            # Via the temporary-evolution chooser: the DigiXros form is what
            # fights, so it has to be picked before the packets are built.
            # The view skips itself when no pet has a form available.
            self.change_view("xros", selected_pets=self.selected_pets)
        elif self.is_online_mode:
            self.change_view("discord", selected_pets=self.selected_pets, is_online_mode=True)
        else:
            self.change_view("wifi_hosting", selected_pets=self.selected_pets, is_online_mode=False)
    
    def _on_back(self):
        """Back button clicked."""
        runtime_globals.game_sound.play("cancel")
        # Return to local_battle submenu for DCom/WiFi/WiFiCom, or main menu for Discord
        if self.is_dcom_mode or self.is_wificom_mode or not self.is_online_mode:
            # For local battles (DCom/WiFi), return to main_menu with local_battle submenu shown
            self.change_view("main_menu", initial_submenu="local_battle")
        else:
            # For online battles (Discord), return to main_menu with arena submenu shown
            self.change_view("main_menu", initial_submenu="arena")
    
    def update(self):
        """Update the view."""
        pass
    
    def draw(self, surface):
        """Draw additional elements."""
        pass
    
    def handle_event(self, event):
        """Handle input events."""
        if not isinstance(event, tuple) or len(event) != 2:
            return
        
        event_type, event_data = event
        
        if event_type == "B":
            self._on_back()
            return True
        elif event_type == "A":
            self._on_confirm()
            return True
    
    def cleanup(self):
        """Cleanup when view is destroyed."""
        components = [
            self.background, self.title_scene, self.pet_selector,
            self.instructions_label, self.confirm_button, self.back_button,
        ]
        
        for comp in components:
            if comp and comp in self.ui_manager.components:
                self.ui_manager.remove_component(comp)
        
        runtime_globals.game_console.log("[PetSelectionView] Cleanup complete")
    
    def get_selected_pets(self):
        """Get the list of selected pets."""
        return self.selected_pets
