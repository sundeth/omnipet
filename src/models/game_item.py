from dataclasses import dataclass, field
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
    # number is the item's own signed change, made to every pet that takes
    # the item whatever its effect, floored at the pet's `min_weight`, or 1
    # with the module's `care_allow_below_min_weight`
    # (`item_effects.apply_weight`); -99 drops a pet to that floor.
    weight_gain: Optional[int] = None
    # What the item puts on its module's battle wire while its boost is
    # active; 0 sends nothing. On the iC wire it is packet 3's weapon
    # nibble (a Beast Claw sent 2). See `inventory_utils.active_protocol_value`.
    protocol_value: int = 0
    # The ordinary attack sprite the pet throws while this item's boost is
    # active, an id in its module's `atk/`; 0 changes nothing. An iC weapon
    # draws its family's sprite. See `inventory_utils.active_attack_sprite`.
    attack_sprite: int = 0
    # A DigiSoul family (`constants.DIGISOUL_DNA_TYPES`), or "" for none.
    # With effect `dna` it is the DNA the item adds to a pet, `amount` of
    # it. With `status_boost` it restricts the item to pets of that family
    # (`monster.json.digisoul`): an iC family weapon.
    digisoul: str = ""
    # The shop.json currency a `currency` effect pays out, `amount` of it.
    currency: str = ""
    # Further effects, applied to the pets that took the item after its
    # main one: rows of `effect`, `status`, `amount` and, where they apply,
    # `boost_time`, `currency` and `digisoul`. The main effect still decides
    # who can take the item. See `utils.item_effects`.
    extra_effects: list = field(default_factory=list)
    # Using the item does not use it up: the Digivice iC's Meat and
    # medicines, its C'mon Switch, and the accessories, which are put on and
    # taken off again.
    reusable: bool = False
    # What an `evolve` item turns a pet into (a monster name on the pet's
    # version), or the battle.json special encounter an `encounter` item
    # starts (the enemy's name). "" for neither.
    target: str = ""
    # The lowest stage that can take the item, 0 for any: the iC's
    # hidden-Ultimate items work from Child (3), its Aura on Ultimates (6).
    min_stage: int = 0
    # The highest stage that can take the item, 0 for no limit: Digimon
    # World's evolution items work only one stage below their Digimon
    # (min_stage and max_stage the same).
    max_stage: int = 0
