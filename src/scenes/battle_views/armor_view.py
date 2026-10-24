"""
ArmorView - Armor evolution selection
Shows pet selector, armor display, and armor item list for single-pet armor evolution
"""
import pygame
from ui.ui_manager import UIManager
from ui.components.title_scene import TitleScene
from ui.components.button import Button
from ui.components.background import Background
from ui.components.pet_selector import PetSelector
from ui.components.armor_display import ArmorDisplay
from ui.components.armor_item_list import ArmorItemList
from ui.ui_constants import BASE_RESOLUTION
from core import runtime_globals
from utils.pet_utils import get_selected_pets
from utils.scene_utils import change_scene


class ArmorView:
    """Armor evolution selection view."""
    
    def __init__(self, ui_manager: UIManager, change_view_callback):
        """Initialize the Armor view.
        
        Args:
            ui_manager: The UI manager instance
            change_view_callback: Callback to change to another view
        """
        self.ui_manager = ui_manager
        self.change_view = change_view_callback
        
        # Selection state
        self.selected_armor_pet = None
        self.selected_armor_item = None
        
        # UI Components
        self.background = None
        self.title_scene = None
        self.pet_selector = None
        self.armor_display = None
        self.armor_item_list = None
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
        
        # Armor display (left side)
        display_width = 80
        display_height = 80
        display_x = 15 
        display_y = 40
        
        self.armor_display = ArmorDisplay(display_x, display_y, display_width, display_height)
        self.ui_manager.add_component(self.armor_display)
        
        # Armor item list (right side)
        item_list_width = 120
        item_list_height = 125
        item_list_x = ui_width - item_list_width - 10
        item_list_y = 25
        
        self.armor_item_list = ArmorItemList(
            item_list_x, item_list_y, item_list_width, item_list_height,
            on_item_activated=self._on_armor_item_activated
        )
        self.armor_item_list.set_background_visible(False)
        self.armor_item_list.set_border_visible(False)
        self.ui_manager.add_component(self.armor_item_list)
        
        # Check if there's a default selected item (first item is selected by default in BaseList)
        if self.armor_item_list.items and len(self.armor_item_list.items) > 0:
            first_item = self.armor_item_list.items[0]
            if hasattr(first_item, 'game_item'):
                self.selected_armor_item = first_item.game_item
                runtime_globals.game_console.log(f"[ArmorView] Default armor item selected: {self.selected_armor_item.name}")
        
        # Buttons
        back_button_width = 60
        confirm_button_width = 80
        button_height = 25
        button_spacing = 5
        
        total_button_width = back_button_width + confirm_button_width + button_spacing
        buttons_start_x = (ui_width - total_button_width) // 2
        buttons_y = item_list_y + item_list_height + 10
        
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
        self.pet_selector.set_pets(get_selected_pets())
        self.pet_selector.set_interactive(True)
        self.pet_selector.set_armor_mode(True)
        self.pet_selector.activation_callback = self._handle_pet_activation
        self.ui_manager.add_component(self.pet_selector)
        
        # Set initial focus
        self.ui_manager.set_focused_component(self.pet_selector)
        self.pet_selector.focused_cell = 0
        
        # Apply eligibility up front — with or without an item selected, a pet
        # with no armor route at all is never a candidate.
        self._update_pet_compatibility()


        runtime_globals.game_console.log("[ArmorView] UI setup complete")
    
    def _handle_pet_activation(self):
        """Handle pet activation from pet selector."""
        pet_index = self.pet_selector.get_activation_cell()
        if pet_index >= 0 and pet_index < len(self.pet_selector.pets):
            if pet_index in self.pet_selector.enabled_pets:
                return self._toggle_pet_selection(pet_index)
        return False
    
    def _toggle_pet_selection(self, pet_index):
        """Toggle pet selection (max 1 pet)."""
        from core import game_globals
        
        if self.selected_armor_pet == pet_index:
            # Deselect
            self.selected_armor_pet = None
            if self.armor_display:
                self.armor_display.clear_pet()
                self.armor_display.needs_redraw = True
            runtime_globals.game_sound.play("cancel")
        else:
            # Select
            self.selected_armor_pet = pet_index
            pet = self.pet_selector.pets[pet_index] if pet_index < len(self.pet_selector.pets) else None
            if pet and self.armor_display:
                self.armor_display.set_pet(pet)
                self.armor_display.needs_redraw = True
            runtime_globals.game_sound.play("menu")
        
        # Update state
        self.pet_selector.selected_pets = [self.selected_armor_pet] if self.selected_armor_pet is not None else []
        
        # Re-check if current armor item selection is valid for this pet
        can_evolve = False
        if self.selected_armor_pet is not None and self.selected_armor_item is not None:
            pet = self.pet_selector.pets[self.selected_armor_pet]
            can_evolve = self._check_armor_evolution_possible(pet, self.selected_armor_item)
        
        # Update confirm button state
        if self.confirm_button:
            should_enable = self.selected_armor_pet is not None and self.selected_armor_item is not None and can_evolve
            self.confirm_button.set_enabled(should_enable)
        
        self.pet_selector.needs_redraw = True
        return True
    
    def _on_armor_item_activated(self, item, index, use_immediately=False):
        """Handle armor item selection.
        
        Args:
            item: The selected armor item
            index: Index of the item in the list
            use_immediately: If True, activate immediately (keyboard or double-click)
        """
        if not item:
            return
            
        # Get the actual game item data
        armor_game_item = item.game_item if hasattr(item, 'game_item') else None
        if not armor_game_item:
            runtime_globals.game_console.log(f"[ArmorView] Warning: Item has no game_item data")
            return
            
        self.selected_armor_item = armor_game_item
        runtime_globals.game_console.log(f"[ArmorView] Armor item selected: {armor_game_item.name}")

        # A different item means a different set of eligible pets (and may
        # drop the current selection).
        self._update_pet_compatibility()

        # Check if the selected pet can evolve with this item
        can_evolve = False
        if self.selected_armor_pet is not None:
            from core import game_globals
            pet = self.pet_selector.pets[self.selected_armor_pet]
            can_evolve = self._check_armor_evolution_possible(pet, armor_game_item)
            
            if can_evolve:
                runtime_globals.game_console.log(f"[ArmorView] {pet.name} can evolve with {armor_game_item.name}")
            else:
                runtime_globals.game_console.log(f"[ArmorView] {pet.name} cannot evolve with {armor_game_item.name}")
        
        # Enable confirm button only if both pet and item are selected AND evolution is possible
        if self.confirm_button:
            should_enable = self.selected_armor_pet is not None and self.selected_armor_item is not None and can_evolve
            self.confirm_button.set_enabled(should_enable)
            
        # If use_immediately is True and evolution is possible, activate immediately
        if use_immediately and can_evolve:
            self._on_confirm()
    
    def _on_confirm(self):
        """Handle confirm button - perform armor evolution."""
        if self.selected_armor_pet is None or self.selected_armor_item is None:
            runtime_globals.game_sound.play("cancel")
            return
        
        from utils.inventory_utils import remove_from_inventory
        from utils import evolution_items

        # The selector lists the selected pets, so its index is into them.
        pet = self.pet_selector.pets[self.selected_armor_pet]
        armor_item = self.selected_armor_item

        runtime_globals.game_console.log(f"[ArmorView] Using {armor_item.name} on {pet.name}")
        consumed, evolved = evolution_items.use(pet, armor_item)
        if not consumed:
            runtime_globals.game_sound.play("cancel")
            return
        # An item route may want several uses (the Twin's five Bombs): a
        # counted use without the evolution yet still spends the item.
        runtime_globals.game_sound.play("evolution" if evolved else "menu")
        remove_from_inventory(armor_item.id)
        if evolved:
            # Armor Evolution quests (they never moved: nothing reported
            # them; 2026-10-22 doc pass).
            from utils.quest_event_utils import update_evolution_quest_progress
            update_evolution_quest_progress("armor", pet.module)
        runtime_globals.game_console.log(
            f"[ArmorView] {armor_item.name}: {pet.name} {'evolved' if evolved else 'counted a use'}")
        
        # Return to game scene
        runtime_globals.game_console.log("[ArmorView] Returning to game")
        change_scene("game")
    
    def _pet_has_armor_evolution(self, pet):
        """Whether any evolution item the player holds does something for
        this pet (utils.evolution_items.can_use)."""
        from utils.evolution_items import can_use
        held = [getattr(entry, "game_item", None) for entry in getattr(self.armor_item_list, "items", None) or []]
        return any(can_use(pet, item) for item in held if item is not None)

    def _update_pet_compatibility(self):
        """Grey out the pets this armor item is no use to.

        A pet is selectable when it has an armor route at all and — once an
        item is chosen — when that item is the one its route asks for. This
        used only to add pets to the enabled list and never remove any, so
        every pet stayed selectable however unrelated it was to the item.
        """
        if not self.pet_selector:
            return

        enabled = []
        for i, pet in enumerate(self.pet_selector.pets):
            if not self._pet_has_armor_evolution(pet):
                continue
            if (self.selected_armor_item is not None
                    and not self._check_armor_evolution_possible(
                        pet, self.selected_armor_item)):
                continue
            enabled.append(i)
        self.pet_selector.set_enabled_pets(enabled)

        # A pet that just became ineligible must not stay selected.
        if self.selected_armor_pet is not None and self.selected_armor_pet not in enabled:
            self.selected_armor_pet = None
            if self.armor_display:
                self.armor_display.clear_pet()
                self.armor_display.needs_redraw = True
            if self.confirm_button:
                self.confirm_button.set_enabled(False)

        self.pet_selector.needs_redraw = True

    def _check_armor_evolution_possible(self, pet, armor_item):
        """Check if the given pet can evolve using the given armor item.
        
        Args:
            pet: The GamePet instance
            armor_item: The GameItem with armor data
            
        Returns:
            bool: True if evolution is possible, False otherwise
        """
        # A route naming the item, or an evolving item's own target for
        # this pet (utils.evolution_items).
        from utils.evolution_items import can_use
        return can_use(pet, armor_item)
    
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
        if self.armor_display:
            self.ui_manager.remove_component(self.armor_display)
        if self.armor_item_list:
            self.ui_manager.remove_component(self.armor_item_list)
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
