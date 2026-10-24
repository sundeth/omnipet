"""
Battle items
============

Items with a battle effect (``status_boost``: the Digivice iC's weapons, the
Digital Monster X's chips, Digimon World's disks) are used before a battle,
from a list of the battle module's own, and not from the inventory. When the
list is offered is the module's ``battle_item_use`` (module.json):

    "area"   at the start of an adventure battle, not between its rounds; the
             effect lasts the item's ``boost_time`` (in areas: it wears off
             after the area's boss, or after each battle of a module without
             sequential rounds). The Digital Monster X: a chip for the area.
    "round"  before every round; the effect lasts that round only. The
             Digivice iC's coliseum: a new weapon for every round.

The effect itself is stored as the inventory stored it before
(`item_effects.add_battle_boost`), and the battle reads it the same way
(`BattleEncounter.get_battle_effect`, `inventory_utils.active_boost_item`).
"""

from core import runtime_globals

BATTLE_ITEM_USE_AREA = "area"
BATTLE_ITEM_USE_ROUND = "round"
BATTLE_ITEM_USES = (BATTLE_ITEM_USE_AREA, BATTLE_ITEM_USE_ROUND)

#: The effect that makes an item a battle item.
BATTLE_EFFECT = "status_boost"


def item_use_timing(module) -> str:
    """The module's ``battle_item_use``: "area" (the default) or "round"."""
    value = str(getattr(module, "battle_item_use", BATTLE_ITEM_USE_AREA) or "").lower()
    return value if value in BATTLE_ITEM_USES else BATTLE_ITEM_USE_AREA


def is_battle_item(item) -> bool:
    return getattr(item, "effect", "") == BATTLE_EFFECT


def battle_items(module, pets=None):
    """``[(item, quantity), ...]``: the module's battle items the player has,
    in the module's item order. With *pets*, only items one of them can
    take (an iC family weapon is its family's)."""
    from utils.inventory_utils import get_inventory_value, item_fits_pet
    if module is None:
        return []
    found = []
    for item in getattr(module, "items", None) or []:
        if not is_battle_item(item):
            continue
        quantity = get_inventory_value(item.id)
        if quantity <= 0:
            continue
        if pets is not None and not any(item_fits_pet(item, pet) for pet in pets):
            continue
        found.append((item, quantity))
    return found


def offers_items_now(module, first_battle, pets=None) -> bool:
    """Whether the item list is offered before this battle: the first of an
    adventure in either timing, every round in "round" timing; and only
    when the player has one of the module's battle items."""
    if not first_battle and item_use_timing(module) != BATTLE_ITEM_USE_ROUND:
        return False
    return bool(battle_items(module, pets))


def use_battle_item(item, pets):
    """Use *item* for the coming battle: its effect is stored for its
    module, then its weight and extra effects go to the *pets* it fits; one
    is used up unless it is reusable. Returns lines for the player."""
    from utils import item_effects
    from utils.inventory_utils import item_fits_pet, remove_from_inventory
    item_effects.add_battle_boost(item, item.status, item.amount, item.boost_time)
    takers = [pet for pet in pets or [] if item_fits_pet(item, pet)]
    notes = item_effects.finish_use(item, takers)
    if not getattr(item, "reusable", False):
        remove_from_inventory(item.id)
    runtime_globals.game_console.log(
        f"[BattleItems] {item.name} used ({item.status} {item.amount}, "
        f"{item.boost_time} {'round' if item_use_timing(runtime_globals.game_modules.get(item.module)) == BATTLE_ITEM_USE_ROUND else 'area'}(s))")
    return notes


def menu_options(items):
    """The pre-battle list: FIGHT first, then each item and how many."""
    return ["Fight"] + [f"{item.name} x{quantity}" for item, quantity in items]


def wire_items(module, pet):
    """The battle items that go on a connection battle's wire, for *pet*:
    those with a ``protocol_value`` (the iC's weapons, packet 3). Other
    battle effects do nothing outside the adventure."""
    return [(item, quantity) for item, quantity in battle_items(module, [pet])
            if int(getattr(item, "protocol_value", 0) or 0)]


def count_down(module_name):
    """One battle of *module_name*'s battle effects used up, outside the
    adventure (a DCom battle with an iC weapon): each effect's boost time
    drops by one and ends at zero."""
    from core import game_globals
    ended = []
    for status, effect in list(game_globals.battle_effects.items()):
        if not isinstance(effect, dict) or effect.get("module") != module_name:
            continue
        effect["boost_time"] = int(effect.get("boost_time", 0) or 0) - 1
        if effect["boost_time"] <= 0:
            ended.append(status)
            del game_globals.battle_effects[status]
    if ended:
        runtime_globals.game_console.log(f"[BattleItems] {module_name}: {', '.join(ended)} used up")
    return ended
