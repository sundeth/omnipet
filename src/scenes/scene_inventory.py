"""
Scene Inventory - Modern UI version with inventory management
Allows the player to browse inventory items and use/discard them.
"""

import pygame
import os
import time

from ui.ui_manager import UIManager
from ui.components.title_scene import TitleScene
from ui.components.button import Button
from ui.components.pet_selector import PetSelector
from ui.components.background import Background
from ui.components.item_list import ItemList
from ui.components.text_panel import TextPanel
from ui.windows.window_background import WindowBackground
from core import runtime_globals, game_globals
import core.constants as constants
from utils.module_utils import get_module
from utils.pet_utils import get_selected_pets
from utils.scene_utils import change_scene
from utils.inventory_utils import get_inventory_value, remove_from_inventory, add_to_inventory
from ui.ui_constants import BASE_RESOLUTION
from utils.asset_utils import image_load

#=====================================================================
# SceneInventory
#=====================================================================
class SceneInventory:
    """
    Modern UI scene for inventory management and item usage.
    """

    def __init__(self) -> None:
        """Initialize the inventory scene with new UI system."""
        
        # Use BLUE theme for inventory
        self.ui_manager = UIManager("BLUE")
        
        # UI Components
        self.background = None
        self.title_scene = None
        self.item_list = None
        self.pet_selector = None
        self.text_panel = None
        self.use_button = None
        self.discard_button = None
        self.selection_button = None
        self.exit_button = None
        
        # Black background for areas not covered by UI
        self.window_background = WindowBackground(False)
        
        self.setup_ui()
        
        runtime_globals.game_console.log("[SceneInventory] Modern inventory scene initialized.")

    def load_inventory_items(self):
        """Load items from inventory, similar to the old inventory menu."""
        items = []
        
        # Create item object class
        class InventoryItem:
            def __init__(self, item_id, game_item, icon, quantity=-1, anim_path=None):
                self.id = item_id
                self.game_item = game_item
                self.icon = icon
                self.quantity = quantity
                self.anim_path = anim_path
        
        # Add default items (Protein and Vitamin) as the first options, without amount
        default_sprite_folder = os.path.join("assets", "items")
        for default_item in runtime_globals.default_items.values():
            sprite_path = os.path.join(default_sprite_folder, default_item.sprite_name)
            anim_path = os.path.join(default_sprite_folder, f"{default_item.sprite_name.split('.')[0]}_anim.png")
            if os.path.exists(sprite_path):
                icon = image_load(sprite_path).convert_alpha()
            else:
                icon = pygame.Surface((48, 48), pygame.SRCALPHA)
                    
            # Add description for default items
            items.append(InventoryItem(default_item.id, default_item, icon, -1, anim_path))

        # Track items by ID to avoid duplicates across modules
        items_by_id = {}
        
        # Add items from inventory (from all modules)
        for module in runtime_globals.game_modules.values():
            if hasattr(module, "items"):
                for item in module.items:
                    if getattr(item, "effect", "") == "digimental":
                        continue
                    amount = get_inventory_value(item.id)
                    if amount > 0:
                        # Check if we already have this item ID
                        if item.id in items_by_id:
                            # Add to existing quantity
                            items_by_id[item.id].quantity += amount
                        else:
                            # Create new item entry
                            sprite_name = item.sprite_name
                            if not sprite_name.lower().endswith(".png"):
                                sprite_name += ".png"
                            sprite_path = os.path.join(module.folder_path, "items", sprite_name)
                            anim_path = os.path.join(module.folder_path, "items", f"{sprite_name.split('.')[0]}_anim.png")
                            if os.path.exists(sprite_path):
                                icon = image_load(sprite_path).convert_alpha()
                            else:
                                icon = pygame.Surface((48, 48), pygame.SRCALPHA)
                            
                            items_by_id[item.id] = InventoryItem(item.id, item, icon, amount, anim_path)
        
        # Add all unique items to the list
        items.extend(items_by_id.values())

        # Shop-purchased items (cross-module): pulled from purchases.items
        # (quantity per id) + metadata from game_globals.shop_items_data
        # (cached when the shop items view loaded).  Skip any item that
        # already exists in items_by_id (i.e. also defined by a module).
        try:
            purchases = getattr(game_globals, 'purchases', None)
            shop_meta = getattr(game_globals, 'shop_items_data', {}) or {}
            if purchases and shop_meta and getattr(purchases, 'items', None):
                items_dir = os.path.join("assets", "items")
                for shop_id, qty in purchases.items.items():
                    if qty <= 0 or shop_id in items_by_id:
                        continue
                    meta = shop_meta.get(shop_id)
                    if not meta:
                        continue
                    sprite_name = meta.get('sprite_name') or ''
                    sprite_path = os.path.join(items_dir, sprite_name) if sprite_name else ''
                    icon = pygame.Surface((48, 48), pygame.SRCALPHA)
                    if sprite_path and os.path.exists(sprite_path):
                        try:
                            icon = image_load(sprite_path).convert_alpha()
                        except Exception:
                            pass
                    # Build a lightweight game_item proxy holding the
                    # fields the inventory consumer expects.  cross_module
                    # is True so the apply-effect path bypasses the usual
                    # per-module pet filter.
                    class _ShopGameItem:
                        pass
                    proxy = _ShopGameItem()
                    proxy.id = shop_id
                    proxy.name = meta.get('name', 'Item')
                    proxy.description = meta.get('description', '')
                    proxy.sprite_name = sprite_name
                    proxy.module = 'shop'
                    proxy.effect = meta.get('effect', '')
                    proxy.status = meta.get('status', '')
                    proxy.amount = meta.get('amount', 1)
                    proxy.boost_time = meta.get('boost_time', 0)
                    proxy.component_item = ''
                    proxy.cross_module = True
                    items.append(InventoryItem(shop_id, proxy, icon, qty, None))
        except Exception as exc:
            runtime_globals.game_console.log(
                f"[SceneInventory] Shop items load error: {exc}")

        return items

    def setup_ui(self):
        """Setup the UI components for the inventory scene."""
        try:
            # Use base 240x240 resolution for UI layout
            ui_width = ui_height = BASE_RESOLUTION
            
            # Create and add the UI background that covers the full UI area
            self.background = Background(ui_width, ui_height)
            # Set single black region covering entire UI
            self.background.set_regions([(0, ui_height, "black")])
            self.ui_manager.add_component(self.background)
            
            # Create and add the title scene at top
            self.title_scene = TitleScene(0, 9, "INVENTORY")
            self.ui_manager.add_component(self.title_scene)
            
            # Create and add the item list positioned at 0, 27 with size 156x176
            item_list_x = 0
            item_list_y = 27
            item_list_width = 156
            item_list_height = 176
            
            self.item_list = ItemList(item_list_x, item_list_y, item_list_width, item_list_height, 
                                     on_item_activated=self.on_item_activated)
            
            # Hide background and border for the inventory - we only want the items visible
            self.item_list.set_background_visible(False)
            self.item_list.set_border_visible(False)
            
            # Load actual inventory items
            inventory_items = self.load_inventory_items()
            self.item_list.set_items(inventory_items)
            self.ui_manager.add_component(self.item_list)
            
            # Create and add the pet selector at bottom (150x46 size)
            selector_width = 145
            selector_height = 40
            selector_x = 5  # Center horizontally
            selector_y = 200  # Near bottom with margin
            
            self.pet_selector = PetSelector(selector_x, selector_y, selector_width, selector_height)
            # Set pets and make it static for now
            self.pet_selector.set_pets(game_globals.pet_list)
            self.pet_selector.set_interactive(False)  # Static display for now
            self.ui_manager.add_component(self.pet_selector)
            
            # Create and add the text panel for item descriptions
            text_panel_x = 158
            text_panel_y = 24
            text_panel_width = 78
            text_panel_height = 106
            
            self.text_panel = TextPanel(text_panel_x, text_panel_y, text_panel_width, text_panel_height)
            self.text_panel.set_text("")
            self.ui_manager.add_component(self.text_panel)
            
            # Create buttons positioned at 135x160 and below
            button_width = 80
            button_height = 23
            button_x = 158
            button_y = 134
            button_spacing = 3  # Vertical spacing between buttons
            
            # USE button
            self.use_button = Button(
                button_x, button_y, button_width, button_height,
                "USE", self.on_use_button
            )
            self.ui_manager.add_component(self.use_button)
            
            # DISCARD button
            self.discard_button = Button(
                button_x, button_y + button_height + button_spacing, button_width, button_height,
                "DISCARD", self.on_discard_button
            )
            self.ui_manager.add_component(self.discard_button)
            
            # SELECTION button - starts with appropriate icon based on current strategy
            #strategy_icon = "All" if runtime_globals.strategy_index == 0 else "Need"
            self.selection_button = Button(
                button_x, button_y + ((button_height + button_spacing) * 2), button_width, button_height,
                f"SEL-{'ALL' if runtime_globals.strategy_index == 0 else 'NEED'}", self.on_selection_button, #icon_name=strategy_icon, icon_prefix="Inventory"
            )
            self.ui_manager.add_component(self.selection_button)
            
            # EXIT button
            self.exit_button = Button(
                button_x, button_y + ((button_height + button_spacing) * 3), button_width, button_height,
                "EXIT", self.on_exit_button
            )
            self.ui_manager.add_component(self.exit_button)
            
            runtime_globals.game_console.log("[SceneInventory] UI setup completed successfully")

            if runtime_globals.food_index >= len(inventory_items):
                runtime_globals.food_index = 0
            self.item_list.set_selected_index(runtime_globals.food_index, instant_scroll=True)
            if inventory_items:
                # Set initial item description and update pet selector
                initial_item = inventory_items[runtime_globals.food_index]
                self.text_panel.set_text(initial_item.game_item.description)
                self._update_pet_selector_for_item(initial_item)
            else:
                self.text_panel.set_text("No items")
            
        except Exception as e:
            runtime_globals.game_console.log(f"[SceneInventory] ERROR in setup_ui: {e}")
            import traceback
            runtime_globals.game_console.log(f"[SceneInventory] Traceback: {traceback.format_exc()}")
            raise
        
        # Focus on the item list initially
        if self.item_list:
            self.ui_manager.set_focused_component(self.item_list)

                
    def update(self) -> None:
        """Update the inventory scene."""
        self.window_background.update()
        self.ui_manager.update()
        
    def draw(self, surface: pygame.Surface) -> None:
        """Draw the inventory scene."""
        # Fill with black background first
        surface.fill((0, 0, 0))
        
        # Draw window background (for texture/pattern if needed)
        self.window_background.draw(surface)
        
        # Draw UI components on top
        self.ui_manager.draw(surface)
        
    def handle_event(self, event) -> None:
        """Handle events in the inventory scene."""        
        event_type, event_data = event

        if event_type in ["A", "LCLICK"]:
            print(f"[SceneInventory] Handling event: {event_type} with data: {event_data}")

        # Handle events through UI manager first
        if self.ui_manager.handle_event(event):
            return
        
        if event_type == "B":
            runtime_globals.game_sound.play("cancel")
            # Preserve the currently selected food index before leaving the scene
            if self.item_list:
                runtime_globals.food_index = self.item_list.selected_index
            else:
                runtime_globals.food_index = 0
            change_scene("game")
            return
        elif event_type == "SELECT":
            # Handle SELECT key same as SELECTION button
            self.on_selection_button()
            return

    def on_item_activated(self, item, index, use_immediately=False):
        """Called when an item is activated - use immediately for keyboard, just select for mouse"""
        # Validate that we have a valid item and index
        if not item or index < 0 or not self.item_list or index >= len(self.item_list.items):
            runtime_globals.game_console.log(f"[SceneInventory] Invalid item activation: item={item}, index={index}")
            return
        
        # Update text panel with item description
        self._update_item_description(item)
        
        # Update pet selector based on current selection strategy and item requirements
        self._update_pet_selector_for_item(item)
        
        if use_immediately:
            # For keyboard activation (A button) or second click on same item, directly use the item
            runtime_globals.game_console.log(f"[SceneInventory] Using item immediately: {item.game_item.name}")
            self._use_item(item, index)
        else:
            # For first mouse click on new item, just select the item (no focus change)
            runtime_globals.game_console.log(f"[SceneInventory] Item '{item.game_item.name}' selected")
            
    def _update_item_description(self, item):
        """Update the text panel with the selected item's description"""
        if not self.text_panel:
            return
            
        # Get item description
        description = item.game_item.description
            
        self.text_panel.set_text(description)
            
    def _is_food_item(self, item):
        """True if using the item feeds hunger/strength (capped by the pet's
        stomach).  A pet with stomach 0 cannot accept these, so they are
        greyed out for such pets."""
        gi = item.game_item
        if gi.effect in ("component", "status_boost"):
            return False
        if gi.effect == "status_change" and gi.status not in ("hunger", "strength"):
            return False
        return gi.status in ("hunger", "strength")

    def _update_pet_selector_for_item(self, item):
        """Update pet selector enable/disable flags based on selection strategy and item requirements"""
        if not self.pet_selector:
            return

        # Pet selector should always show ALL pets from game_globals.pet_list
        all_pets = game_globals.pet_list
        selected_pets = get_selected_pets()  # Pets that can interact with items

        # Only set pets if the list has changed (to avoid unnecessary redraws)
        if not hasattr(self, '_last_pet_count') or self._last_pet_count != len(all_pets):
            self.pet_selector.set_pets(all_pets)
            self._last_pet_count = len(all_pets)

        # Create a mapping of selected pets for quick lookup
        selected_pet_set = set(selected_pets)

        # Food (hunger/strength) items can't be used by a pet with stomach 0.
        is_food = self._is_food_item(item)

        if runtime_globals.strategy_index == 0:
            # Strategy 0: Enable all pets that are in selected_pets list
            enabled_indices = []
            for i, pet in enumerate(all_pets):
                if pet in selected_pet_set and not pet._is_blocked_by_sleep():
                    if is_food and pet.stomach <= 0:
                        continue  # Can't eat — grey out
                    enabled_indices.append(i)
            self.pet_selector.set_enabled_pets(enabled_indices)
        else:
            # Strategy 1: Only pets that need this item AND are in selected_pets
            item_status = item.game_item.status
            enabled_indices = []
            for i, pet in enumerate(all_pets):
                if pet not in selected_pet_set:
                    continue  # Skip pets not in selected_pets
                if pet._is_blocked_by_sleep():
                    continue  # Skip pets blocked by sleep window
                if is_food and pet.stomach <= 0:
                    continue  # Can't eat — grey out

                pet_needs_item = False
                if item_status == "hunger":
                    pet_needs_item = pet.hunger < 4
                elif item_status == "strength":
                    pet_needs_item = pet.strength < 4
                else:
                    # For any other status, check if pet can battle
                    pet_needs_item = pet.can_battle()

                if pet_needs_item:
                    enabled_indices.append(i)

            self.pet_selector.set_enabled_pets(enabled_indices)
            
    def _use_item(self, item, index):
        """Internal method to use an item - dispatches to effect-specific handlers"""
        # Get targets (selected pets), excluding sleep-blocked pets
        targets = [pet for pet in get_selected_pets() if not pet._is_blocked_by_sleep()]
        # Food items (hunger/strength) can't be eaten by a pet with stomach 0.
        if self._is_food_item(item):
            targets = [pet for pet in targets if pet.stomach > 0]
        if runtime_globals.strategy_index != 0:
            # NEED mode: only pets that actually need this item
            item_status = item.game_item.status
            filtered = []
            for pet in targets:
                if item_status == "hunger":
                    if pet.hunger < 4:
                        filtered.append(pet)
                elif item_status == "strength":
                    if pet.strength < 4:
                        filtered.append(pet)
                else:
                    if pet.can_battle():
                        filtered.append(pet)
            targets = filtered
        if not targets:
            runtime_globals.game_sound.play("cancel")
            runtime_globals.game_console.log("[SceneInventory] No pets selected for feeding")
            return
        
        # Dispatch to appropriate handler based on item effect
        effect = item.game_item.effect
        status = item.game_item.status
        if effect == "component":
            self._use_component_item(item)
        elif effect == "status_boost":
            self._use_status_boost_item(item, targets)
        elif effect == "status_change" and status not in ["hunger", "strength"]:
            self._use_status_change_item(item, targets)
        elif not effect and not status:
            # Catalogued items whose authentic behavior is not implemented
            # remain visible/grantable, but cannot be accidentally consumed
            # as a generic food item.
            runtime_globals.game_sound.play("cancel")
            runtime_globals.game_console.log(
                f"[SceneInventory] {item.game_item.name} has no implemented effect")
            return
        else:
            self._use_feeding_item(item, targets)
    
    def _use_component_item(self, item):
        """Handle component crafting items"""
        current_amount = get_inventory_value(item.id)
        required_amount = item.game_item.amount
        
        if current_amount < required_amount:
            runtime_globals.game_sound.play("cancel")
            runtime_globals.game_console.log(f"[SceneInventory] Not enough {item.game_item.name} (have {current_amount}, need {required_amount})")
            return
        
        # BaseList already played the activation sound
        remove_from_inventory(item.id, required_amount)
        
        # Find the component item in the same module
        component_item = None
        for module in runtime_globals.game_modules.values():
            if hasattr(module, "items"):
                for it in module.items:
                    if it.name == item.game_item.component_item:
                        component_item = it
                        break
                if component_item:
                    break
        
        if component_item:
            add_to_inventory(component_item.id, 1)
            runtime_globals.game_message.add_slide(f"{component_item.name} obtained!", (255, 255, 0), 56 * runtime_globals.UI_SCALE, runtime_globals.FONT_SIZE_SMALL)
            runtime_globals.game_console.log(f"[SceneInventory] Crafted {component_item.name} from {item.game_item.name}")
        else:
            runtime_globals.game_console.log(f"[SceneInventory] Component item '{item.game_item.component_item}' not found in module")
        
        runtime_globals.game_sound.play("happy2")
        self._return_to_game()
    
    def _use_status_boost_item(self, item, targets):
        """Handle status boost items (battle effects)"""

        eff = game_globals.battle_effects.get(item.game_item.status, {"amount": 0, "boost_time": 0, "module": item.game_item.module})
        eff["amount"] = item.game_item.amount
        eff["boost_time"] += item.game_item.boost_time
        eff["module"] = item.game_item.module
        eff["item_id"] = item.game_item.id
        game_globals.battle_effects[item.game_item.status] = eff
        
        # Continue to feeding animation
        self._use_feeding_item(item, targets)
    
    def _use_status_change_item(self, item, targets):
        """Handle status change items (direct stat modifications)"""
        status_to_change = item.game_item.status
        amount = item.game_item.amount
        affected_pets = []  # Track pets that received stat changes
        
        # For capped stats, check if all pets have reached the cap
        if status_to_change in ['hp', 'attack', 'power']:
            all_capped = True
            bonus_index = {'hp': 0, 'attack': 1, 'power': 2}[status_to_change]
            cap_attr = {'hp': 'hp_max_item_boost', 'attack': 'atk_max_item_boost', 'power': 'power_max_item_boost'}[status_to_change]
            
            for pet in targets:
                pet_module = get_module(pet.module)
                cap = getattr(pet_module, cap_attr, 0)
                current_bonus = pet.bonus_stats[bonus_index]
                if current_bonus < cap:
                    all_capped = False
                    break
            
            if all_capped:
                runtime_globals.game_sound.play("cancel")
                runtime_globals.game_console.log(f"[SceneInventory] All pets have reached {status_to_change} cap")
                return
            
            # Apply bonus to pets that haven't reached cap
            for pet in targets:
                pet_module = get_module(pet.module)
                cap = getattr(pet_module, cap_attr, 0)
                current_bonus = pet.bonus_stats[bonus_index]
                if current_bonus < cap:
                    new_bonus = min(cap, current_bonus + amount)
                    pet.bonus_stats[bonus_index] = new_bonus
                    affected_pets.append(pet)
                    runtime_globals.game_console.log(f"[SceneInventory] {pet.name} {status_to_change} bonus: {current_bonus} -> {new_bonus} (cap: {cap})")
        
        # For uncapped or direct stats
        elif status_to_change == 'strength':
            for pet in targets:
                old_strength = pet.strength
                pet.strength = min(4, pet.strength + amount)
                if pet.strength != old_strength:
                    affected_pets.append(pet)
                    runtime_globals.game_console.log(f"[SceneInventory] {pet.name} strength: {pet.strength}")
        
        elif status_to_change == 'dp':
            for pet in targets:
                old_dp = pet.dp
                pet.dp = min(pet.energy, pet.dp + amount)
                if pet.dp != old_dp:
                    affected_pets.append(pet)
                    runtime_globals.game_console.log(f"[SceneInventory] {pet.name} dp: {pet.dp}/{pet.energy}")
        
        elif status_to_change == 'timer':
            for pet in targets:
                pet._rt_origin -= amount * 60  # shift origin back by the given number of minutes
                affected_pets.append(pet)
                runtime_globals.game_console.log(f"[SceneInventory] {pet.name} timer advanced by {amount} minutes")
        
        elif status_to_change == 'vital_values':
            for pet in targets:
                old_vital = pet.vital_values
                pet.vital_values = min(9999, pet.vital_values + amount)
                if pet.vital_values != old_vital:
                    affected_pets.append(pet)
                    runtime_globals.game_console.log(f"[SceneInventory] {pet.name} vital_values: {pet.vital_values}")
        
        if len(affected_pets) == 0:
            runtime_globals.game_sound.play("cancel")
            runtime_globals.game_console.log(f"[SceneInventory] No pets affected by {item.game_item.name}")
            return

        for pet in affected_pets:
            pet.check_disturbed_sleep()
            pet.set_state("eat", True)
        
        # Set up eating animation for affected pets
        self._setup_eating_animation(item, affected_pets)
        
        # Remove item from inventory
        if item.id not in [ditem.id for ditem in runtime_globals.default_items.values()]:
            remove_from_inventory(item.id)
        
        runtime_globals.game_console.log(f"[SceneInventory] Applied {item.game_item.name} to {len(affected_pets)} pets")
        self._return_to_game()
    
    def _use_feeding_item(self, item, targets):
        """Handle regular feeding items (hunger/strength)"""

        food_status = item.game_item.status
        food_amount = item.game_item.amount
        accepted_pets = []
        
        for pet in targets:
            pet.check_disturbed_sleep()
            accepted = pet.set_eating(
                food_status, food_amount,
                getattr(item.game_item, 'weight_gain', None))
            if accepted:
                pet.animation_counter = 0
                accepted_pets.append(pet)
        
        # Set up eating animation for pets that accepted the food
        self._setup_eating_animation(item, accepted_pets)
        
        # Remove from inventory for non-default items
        if item.id not in [ditem.id for ditem in runtime_globals.default_items.values()]:
            remove_from_inventory(item.id)
        
        runtime_globals.game_console.log(f"[SceneInventory] Fed {len(accepted_pets)} pets with {item.game_item.name}")
        self._return_to_game()
    
    def _setup_eating_animation(self, item, pets):
        """Set up eating animation for a list of pets"""
        runtime_globals.game_pet_eating = {}
        
        for pet in pets:
            pet_index = game_globals.pet_list.index(pet)
            
            # Load animation frames if available
            anim_frames = None
            if hasattr(item, 'anim_path') and item.anim_path and os.path.exists(item.anim_path):
                anim_image = image_load(item.anim_path).convert_alpha()
                w, h = anim_image.get_width() // 4, anim_image.get_height()
                anim_frames = [
                    pygame.transform.scale(
                        anim_image.subsurface((i * w, 0, w, h)).copy(),
                        (int(runtime_globals.PET_WIDTH * 0.75), int(runtime_globals.PET_HEIGHT * 0.75))
                    )
                    for i in range(4)
                ]
            
            # Create scaled sprite for item icon
            if hasattr(item, 'icon') and item.icon:
                scaled_sprite = pygame.transform.scale(
                    item.icon, (int(runtime_globals.PET_WIDTH * 0.75), int(runtime_globals.PET_HEIGHT * 0.75))
                )
                runtime_globals.game_pet_eating[pet_index] = {
                    "item": item,
                    "sprite": scaled_sprite,
                    "anim_frames": anim_frames
                }
    
    def _return_to_game(self):
        """Save selection and return to game scene"""
        if self.item_list:
            runtime_globals.food_index = self.item_list.selected_index
        else:
            runtime_globals.food_index = 0
        change_scene("game")
        
    # Button callback methods
    def on_use_button(self):
        """Handle USE button press - feed the selected item to pets."""
        if not self.item_list or not self.item_list.items:
            runtime_globals.game_sound.play("cancel")
            return
            
        # Get the currently selected item
        selected_index = self.item_list.selected_index
        if selected_index < 0 or selected_index >= len(self.item_list.items):
            runtime_globals.game_sound.play("cancel")
            return
            
        item = self.item_list.items[selected_index]
        self._use_item(item, selected_index)
        
    def on_discard_button(self):
        """Handle DISCARD button press - remove item from inventory."""
        if not self.item_list or not self.item_list.items:
            runtime_globals.game_sound.play("cancel")
            return
            
        # Get the currently selected item
        selected_index = self.item_list.selected_index
        if selected_index < 0 or selected_index >= len(self.item_list.items):
            runtime_globals.game_sound.play("cancel")
            return
            
        item = self.item_list.items[selected_index]
        
        # Don't allow discarding default items (Protein/Vitamin)
        if hasattr(item, 'id') and item.id in [ditem.id for ditem in runtime_globals.default_items.values()]:
            runtime_globals.game_sound.play("cancel")
            #runtime_globals.game_console.log(f"[SceneInventory] Cannot discard default item: {item.name}")
            return
            
        runtime_globals.game_sound.play("menu")
        
        # Remove 1 from inventory
        if hasattr(item, 'id'):
            remove_from_inventory(item.id, 1)
            runtime_globals.game_console.log(f"[SceneInventory] Discarded 1x {item.game_item.name}")
            
            # Refresh the inventory items list
            inventory_items = self.load_inventory_items()
            self.item_list.set_items(inventory_items)
            
            # Ensure selection index is valid after item removal
            if inventory_items:
                # Keep the same index if possible, otherwise clamp to valid range
                if selected_index >= len(inventory_items):
                    selected_index = len(inventory_items) - 1
                self.item_list.set_selected_index(selected_index)
                
                # Update description and pet selector for new selection
                current_item = inventory_items[selected_index]
                self._update_item_description(current_item)
                self._update_pet_selector_for_item(current_item)
            else:
                # No items left
                self.text_panel.set_text("No items")
                
            # Ensure focus returns to item list for continued navigation
            self.ui_manager.set_focused_component(self.item_list)
        else:
            runtime_globals.game_console.log(f"[SceneInventory] Could not discard item - no ID found")
        
    def on_selection_button(self):
        """Handle SELECTION button press - toggle pet selection strategy."""
        runtime_globals.game_sound.play("menu")
        # Cycle through pet selection strategies
        runtime_globals.strategy_index = (runtime_globals.strategy_index + 1) % 2
        strategy_names = ["All Pets", "Need Only"]
        current_strategy = strategy_names[runtime_globals.strategy_index]
        runtime_globals.game_console.log(f"[SceneInventory] Switched to strategy: {current_strategy}")
        
        # Update button icon based on new strategy
        #strategy_icon = "All" if runtime_globals.strategy_index == 0 else "Need"
        #if self.selection_button:
        #    self.selection_button.icon_name = strategy_icon
        #    self.selection_button.needs_redraw = True
        
        self.selection_button.text = f"SEL-{'ALL' if runtime_globals.strategy_index == 0 else 'NEED'}"
        self.selection_button.needs_redraw = True
        # Update pet selector based on current item and new strategy
        if self.item_list and self.item_list.items and self.item_list.selected_index >= 0:
            current_item = self.item_list.items[self.item_list.selected_index]
            self._update_pet_selector_for_item(current_item)
        else:
            # No item selected, enable pets based on strategy and selected_pets
            if self.pet_selector:
                all_pets = game_globals.pet_list
                selected_pets = get_selected_pets()
                selected_pet_set = set(selected_pets)
                
                if runtime_globals.strategy_index == 0:
                    # Enable all pets that are in selected_pets
                    enabled_indices = []
                    for i, pet in enumerate(all_pets):
                        if pet in selected_pet_set:
                            enabled_indices.append(i)
                else:
                    enabled_indices = []  # No item selected, so no pets need anything
                self.pet_selector.set_enabled_pets(enabled_indices)
        
    def on_exit_button(self):
        """Handle EXIT button press."""
        runtime_globals.game_sound.play("cancel")
        # Preserve the currently selected food index before leaving the scene
        if self.item_list:
            runtime_globals.food_index = self.item_list.selected_index
        else:
            runtime_globals.food_index = 0
        change_scene("game")
