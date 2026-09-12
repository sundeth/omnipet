from dataclasses import dataclass
from typing import Optional

@dataclass
class GameItem:
    id: str
    name: str
    description: str
    sprite_name: str
    module: str
    effect: str
    status: str
    amount: int
    boost_time: int
    component_item: str
    # None preserves the module's ordinary meat/protein weight rule. A
    # numeric value is an item-specific gain declared by item.json.
    weight_gain: Optional[int] = None
