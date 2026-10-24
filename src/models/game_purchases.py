"""
GamePurchases - Tracks purchased items from the shop.
Stores purchase IDs per category for modules, cosmetics, gameplay, items, and specials.
Items are consumable and track quantity.
"""
from dataclasses import dataclass, field
from typing import Dict, Set, Optional
import json


@dataclass
class GamePurchases:
    """
    Tracks all shop purchases for the player.
    
    Attributes:
        modules: Set of purchased module IDs (GUIDs)
        module_names: Set of purchased module local names (for egg selection filtering)
        cosmetics: Set of purchased cosmetic IDs (GUIDs) 
        gameplay: Set of purchased gameplay feature IDs (GUIDs)
        items: Dict mapping item ID to quantity (consumable items)
        specials: Set of purchased special item IDs (GUIDs)
    """
    modules: Set[str] = field(default_factory=set)
    module_names: Set[str] = field(default_factory=set)
    cosmetics: Set[str] = field(default_factory=set)
    gameplay: Set[str] = field(default_factory=set)
    items: Dict[str, int] = field(default_factory=dict)  # item_id -> quantity
    specials: Set[str] = field(default_factory=set)
    #: The server's purchase rows this save has counted into `items`. Items
    #: are bought again and again (one row each) and used up here, so a row
    #: is counted once: the account sync used to set every used item back to 1.
    item_purchase_ids: Set[str] = field(default_factory=set)
    #: False for a save from before the rows were counted: its first sync
    #: takes the quantities it holds as what it has (apply_purchase_entries).
    item_purchases_tracked: bool = True
    
    def owns_module(self, module_id: str) -> bool:
        """Check if player owns a module."""
        return module_id in self.modules
    
    def owns_cosmetic(self, cosmetic_id: str) -> bool:
        """Check if player owns a cosmetic."""
        return cosmetic_id in self.cosmetics
    
    def owns_gameplay(self, gameplay_id: str) -> bool:
        """Check if player owns a gameplay feature."""
        return gameplay_id in self.gameplay
    
    def owns_special(self, special_id: str) -> bool:
        """Check if player owns a special item."""
        return special_id in self.specials
    
    def get_item_quantity(self, item_id: str) -> int:
        """Get quantity of a consumable item."""
        return self.items.get(item_id, 0)
    
    def has_item(self, item_id: str) -> bool:
        """Check if player has at least one of an item."""
        return self.get_item_quantity(item_id) > 0
    
    def owns_module_name(self, module_name: str) -> bool:
        """Check if player owns a module by its local name."""
        return module_name in self.module_names

    def add_module(self, module_id: str, module_name: str = None) -> None:
        """Add a purchased module.
        
        Args:
            module_id: Shop GUID for the module
            module_name: Optional local module name for egg selection filtering
        """
        self.modules.add(module_id)
        if module_name:
            self.module_names.add(module_name)
    
    def add_cosmetic(self, cosmetic_id: str) -> None:
        """Add a purchased cosmetic."""
        self.cosmetics.add(cosmetic_id)
    
    def add_gameplay(self, gameplay_id: str) -> None:
        """Add a purchased gameplay feature."""
        self.gameplay.add(gameplay_id)
    
    def add_special(self, special_id: str) -> None:
        """Add a purchased special item."""
        self.specials.add(special_id)
    
    def add_item(self, item_id: str, quantity: int = 1) -> None:
        """Add consumable items (stacks with existing quantity)."""
        current = self.items.get(item_id, 0)
        self.items[item_id] = current + quantity

    def apply_item_purchase(self, item_id: str, purchase_id: Optional[str]) -> bool:
        """One bought item, from the server's purchase row *purchase_id*: +1
        unless that row was counted already. True if it added one."""
        purchase_id = str(purchase_id) if purchase_id else ""
        if purchase_id and purchase_id in self.item_purchase_ids:
            return False
        self.add_item(item_id, 1)
        if purchase_id:
            self.item_purchase_ids.add(purchase_id)
        return True
    
    def use_item(self, item_id: str, quantity: int = 1) -> bool:
        """
        Use a consumable item.
        
        Returns:
            True if item was used, False if insufficient quantity
        """
        current = self.items.get(item_id, 0)
        if current < quantity:
            return False
        
        self.items[item_id] = current - quantity
        
        # Remove item if quantity reaches 0
        if self.items[item_id] <= 0:
            del self.items[item_id]
        
        return True
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            'modules': list(self.modules),
            'module_names': list(self.module_names),
            'cosmetics': list(self.cosmetics),
            'gameplay': list(self.gameplay),
            'items': self.items.copy(),
            'specials': list(self.specials),
            'item_purchase_ids': sorted(self.item_purchase_ids),
            'item_purchases_tracked': self.item_purchases_tracked,
        }
    
    @classmethod
    def from_dict(cls, data: Optional[dict]) -> 'GamePurchases':
        """Create from dictionary (for deserialization)."""
        if not data:
            return cls()
        
        return cls(
            modules=set(data.get('modules', [])),
            module_names=set(data.get('module_names', [])),
            cosmetics=set(data.get('cosmetics', [])),
            gameplay=set(data.get('gameplay', [])),
            items=data.get('items', {}),
            specials=set(data.get('specials', [])),
            item_purchase_ids=set(data.get('item_purchase_ids', [])),
            # A save written before the rows were counted has no such key
            item_purchases_tracked=bool(data.get('item_purchases_tracked', False)),
        )
    
    def __repr__(self) -> str:
        return (f"GamePurchases(modules={len(self.modules)}, cosmetics={len(self.cosmetics)}, "
                f"gameplay={len(self.gameplay)}, items={len(self.items)}, specials={len(self.specials)})")
