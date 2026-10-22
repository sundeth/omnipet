"""
Armor Item List Component
Specialized ItemList for displaying armor items (status="armor") for armor evolution.
"""
import pygame
import os
from ui.components.item_list import ItemList
from core import runtime_globals
from utils.inventory_utils import get_inventory_value
from utils.asset_utils import image_load


class ArmorItemList(ItemList):
    """Specialized ItemList for armor items only."""
    
    def __init__(self, x, y, width, height, on_item_activated=None):
        """Initialize the armor item list."""
        super().__init__(x, y, width, height, on_item_activated)
        
        # Load armor items immediately
        self.load_armor_items()
        
    def load_armor_items(self):
        """Load the evolution items the player holds, from all modules: the
        armor items (DigiMentals), the evolving items (the iC's, Digimon
        World's) and any item a party pet's route names
        (utils.evolution_items)."""
        from core import game_globals
        from utils.evolution_items import is_evolution_item
        items = []
        party = list(game_globals.pet_list or [])

        for module in runtime_globals.game_modules.values():
            if hasattr(module, "items"):
                for item in module.items:
                    if is_evolution_item(item, party):
                        amount = get_inventory_value(item.id)
                        if amount > 0:
                            # Load sprite for this item
                            sprite_name = item.sprite_name
                            if not sprite_name.lower().endswith(".png"):
                                sprite_name += ".png"
                            sprite_path = os.path.join(module.folder_path, "items", sprite_name)
                            anim_path = os.path.join(module.folder_path, "items", f"{sprite_name.split('.')[0]}_anim.png")
                            
                            if os.path.exists(sprite_path):
                                icon = image_load(sprite_path).convert_alpha()
                            else:
                                # Create placeholder icon if sprite not found
                                icon = pygame.Surface((48, 48), pygame.SRCALPHA)
                                icon.fill((100, 100, 100))  # Gray placeholder
                            
                            # Create armor item object
                            class ArmorItem:
                                def __init__(self, item_id, game_item, icon, quantity, anim_path=None):
                                    self.id = item_id
                                    self.game_item = game_item
                                    self.icon = icon
                                    self.quantity = quantity
                                    self.anim_path = anim_path
                                    
                            items.append(ArmorItem(item.id, item, icon, amount, anim_path))
                            runtime_globals.game_console.log(f"[ArmorItemList] Added digimental item: {item.name} (amount: {amount})")
        
        # Set the armor items to the list
        self.set_items(items)
        runtime_globals.game_console.log(f"[ArmorItemList] Loaded {len(items)} digimental items")
        
    def refresh_armor_items(self):
        """Refresh the armor items list (call when inventory changes)."""
        self.load_armor_items()
        
    def get_selected_armor_item(self):
        """Get the currently selected armor item, or None if no selection."""
        if hasattr(self, 'focused_index') and self.focused_index >= 0 and self.items:
            if self.focused_index < len(self.items):
                return self.items[self.focused_index]
        return None
        
    def get_selected_armor_item_data(self):
        """Get the game item data for the currently selected armor item."""
        armor_item = self.get_selected_armor_item()
        if armor_item and hasattr(armor_item, 'game_item'):
            return armor_item.game_item
        return None
    
    def get_selected_item(self):
        """Alias for get_selected_armor_item for compatibility."""
        return self.get_selected_armor_item()