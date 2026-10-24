"""
VersusView - Versus battle pet selection
Shows pet selector and versus display for 2-pet versus selection
"""
import pygame
from ui.ui_manager import UIManager
from ui.components.title_scene import TitleScene
from ui.components.button import Button
from ui.components.background import Background
from ui.components.pet_selector import PetSelector
from ui.components.versus_display import VersusDisplay
from ui.ui_constants import BASE_RESOLUTION
from core import runtime_globals
from utils.pet_utils import get_selected_pets


class VersusView:
    """Versus pet selection view."""
    
    def __init__(self, ui_manager: UIManager, change_view_callback):
        """Initialize the Versus view.
        
        Args:
            ui_manager: The UI manager instance
            change_view_callback: Callback to change to another view (view_name, **kwargs)
        """
        self.ui_manager = ui_manager
        self.change_view = change_view_callback
        
        # Selection state
        self.selected_pets = []  # List of selected pet indices (max 2)
        self.versus_themes = ["BLUE", "GREEN"]  # BLUE→right, GREEN→left
        self.pet_theme_assignments = {}
        
        # UI Components
        self.background = None
        self.title_scene = None
        self.pet_selector = None
        self.versus_display = None
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
        self.title_scene = TitleScene(0, 9, "BATTLE")
        self.ui_manager.add_component(self.title_scene)
        
        # Versus display
        display_width = 160
        display_height = 80
        display_x = (ui_width - display_width) // 2
        display_y = 40
        
        self.versus_display = VersusDisplay(display_x, display_y, display_width, display_height)
        self.ui_manager.add_component(self.versus_display)
        
        # Buttons
        back_button_width = 60
        confirm_button_width = 80
        button_height = 25
        button_spacing = 5
        
        total_button_width = back_button_width + confirm_button_width + button_spacing
        buttons_start_x = (ui_width - total_button_width) // 2
        buttons_y = display_y + display_height + 10
        
        self.back_button = Button(
            buttons_start_x, buttons_y, back_button_width, button_height,
            "BACK", self._on_back
        )
        self.ui_manager.add_component(self.back_button)
        
        confirm_button_x = buttons_start_x + back_button_width + button_spacing
        self.confirm_button = Button(
            confirm_button_x, buttons_y, confirm_button_width, button_height,
            "CONFIRM", self._on_confirm,
            enabled=False
        )
        self.ui_manager.add_component(self.confirm_button)
        
        # Pet selector
        selector_y = buttons_y + button_height + 5
        selector_height = 50
        self.pet_selector = PetSelector(10, selector_y, ui_width - 20, selector_height)
        versus_pets = get_selected_pets()
        self.pet_selector.set_pets(versus_pets)
        # Pets without battle resources (module battle cost: DP/hunger) or
        # otherwise unable to fight can't be picked for versus.
        self.pet_selector.set_enabled_pets(
            [i for i, pet in enumerate(versus_pets) if pet.can_battle()])
        self.pet_selector.set_interactive(True)
        self.pet_selector.activation_callback = self._handle_pet_activation
        self.ui_manager.add_component(self.pet_selector)
        
        # Set initial focus
        self.ui_manager.set_focused_component(self.pet_selector)
        self.pet_selector.focused_cell = 0
        
        runtime_globals.game_console.log("[VersusView] UI setup complete")
    
    def _handle_pet_activation(self):
        """Handle pet activation from pet selector."""
        pet_index = self.pet_selector.get_activation_cell()
        if pet_index >= 0 and pet_index < len(self.pet_selector.pets):
            if pet_index in self.pet_selector.enabled_pets:
                return self._toggle_pet_selection(pet_index)
        return False
    
    def _toggle_pet_selection(self, pet_index):
        """Toggle pet selection (max 2 pets)."""
        if pet_index in self.selected_pets:
            # Deselect
            self.selected_pets.remove(pet_index)
            
            if self.versus_display:
                slot_to_clear = None
                if pet_index in self.pet_theme_assignments:
                    theme = self.pet_theme_assignments[pet_index]
                    # Versus: GREEN→left (slot 0), BLUE→right (slot 1)
                    slot_to_clear = 1 if theme == "GREEN" else 0
                    
                if slot_to_clear is not None:
                    self.versus_display.clear_slot(slot_to_clear)
            
            if pet_index in self.pet_theme_assignments:
                del self.pet_theme_assignments[pet_index]
                
            runtime_globals.game_sound.play("cancel")
        else:
            # Select
            if len(self.selected_pets) < 2:
                self.selected_pets.append(pet_index)
                
                # Assign theme
                used_themes = set(self.pet_theme_assignments.values())
                available_themes = [theme for theme in self.versus_themes if theme not in used_themes]
                
                if available_themes:
                    self.pet_theme_assignments[pet_index] = available_themes[0]
                    assigned_theme = available_themes[0]
                    
                    if self.versus_display:
                        pet = self.pet_selector.pets[pet_index] if pet_index < len(self.pet_selector.pets) else None
                        if pet:
                            slot_index = 1 if assigned_theme == "GREEN" else 0
                            self.versus_display.set_pet_slot(slot_index, pet)
                else:
                    self.pet_theme_assignments[pet_index] = "BLUE"
                    if self.versus_display:
                        pet = self.pet_selector.pets[pet_index] if pet_index < len(self.pet_selector.pets) else None
                        if pet:
                            self.versus_display.set_pet_slot(1, pet)
                
                runtime_globals.game_sound.play("menu")
            else:
                runtime_globals.game_sound.play("cancel")
                return False
        
        # Update state
        self.pet_selector.selected_pets = self.selected_pets[:]
        
        if self.confirm_button:
            self.confirm_button.set_enabled(len(self.selected_pets) == 2)
        
        self._update_pet_themes()
        self.pet_selector.needs_redraw = True
        return True
    
    def _update_pet_themes(self):
        """Update pet selector themes."""
        if not self.pet_selector:
            return
            
        self.pet_selector.clear_custom_themes()
        
        for pet_index in self.selected_pets:
            if pet_index in self.pet_theme_assignments:
                theme = self.pet_theme_assignments[pet_index]
                self.pet_selector.set_pet_custom_theme(pet_index, theme)
    
    def _on_confirm(self):
        """Handle confirm button - go to protocol selection."""
        if len(self.selected_pets) != 2:
            runtime_globals.game_sound.play("cancel")
            return
        
        runtime_globals.game_sound.play("menu")
        
        # The selection holds indices into the list shown (the selected pets,
        # or the party), not into the party: reading pet_list fought other
        # pets than the two tapped whenever the two lists differed.
        pet1 = self.pet_selector.pets[self.selected_pets[0]]
        pet2 = self.pet_selector.pets[self.selected_pets[1]]
        
        # Change to protocol selection view with the selected pets
        self.change_view("protocol", pet1=pet1, pet2=pet2)
    
    def _on_back(self):
        """Handle back button."""
        runtime_globals.game_sound.play("cancel")
        self.change_view("main_menu")
    
    def cleanup(self):
        """Remove all UI components."""
        if self.background:
            self.ui_manager.remove_component(self.background)
        if self.title_scene:
            self.ui_manager.remove_component(self.title_scene)
        if self.pet_selector:
            self.ui_manager.remove_component(self.pet_selector)
        if self.versus_display:
            self.ui_manager.remove_component(self.versus_display)
        if self.confirm_button:
            self.ui_manager.remove_component(self.confirm_button)
        if self.back_button:
            self.ui_manager.remove_component(self.back_button)
    
    def update(self):
        """Update the view."""
        pass
    
    def draw(self, surface: pygame.Surface):
        """Draw the view."""
        pass
    
    def handle_event(self, event):
        """Handle input events."""
        if not isinstance(event, tuple) or len(event) != 2:
            return
        event_type, event_data = event
        if event_type == "B":
            self._on_back()
