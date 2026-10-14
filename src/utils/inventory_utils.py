from core import game_globals, runtime_globals


def _shop_purchases_items():
    """Return the GamePurchases.items dict if available, else None."""
    purchases = getattr(game_globals, 'purchases', None)
    if purchases is None:
        return None
    return getattr(purchases, 'items', None)


def get_inventory_value(item_id):
    """
    Returns the quantity of the item with the given id, or 0 if not present.

    Module inventories are checked first; if the id isn't there we fall
    back to shop-purchased items so cross-module shop items show the right
    quantity wherever this helper is used.
    """
    amount = game_globals.inventory.get(item_id, 0)
    if amount:
        return amount
    shop_items = _shop_purchases_items()
    if shop_items is not None:
        return shop_items.get(item_id, 0)
    return 0


#: The most of one item a player holds (the Digivice iC's 99); getting more
#: of an item at the limit does nothing.
MAX_ITEM_STACK = 99


def is_full(item_id) -> bool:
    """Whether the player already holds the most of *item_id* they can."""
    return game_globals.inventory.get(item_id, 0) >= MAX_ITEM_STACK


def add_to_inventory(item_id, amount=1):
    """
    Adds the specified amount of the item to the inventory, up to
    `MAX_ITEM_STACK`; what would go past it is not added. Returns how many
    were added.

    If the item id is already tracked in shop purchases, the increment
    goes there to keep shop-item counts consistent across modules (those
    are Omninet store purchases, paid for, and have no limit).
    """
    shop_items = _shop_purchases_items()
    if shop_items is not None and item_id in shop_items:
        shop_items[item_id] = shop_items.get(item_id, 0) + amount
        return amount
    old = game_globals.inventory.get(item_id, 0)
    new = min(MAX_ITEM_STACK, old + amount) if amount > 0 else old + amount
    game_globals.inventory[item_id] = max(old, new) if amount > 0 else new
    return game_globals.inventory[item_id] - old


def remove_from_inventory(item_id, amount=1):
    """
    Removes the specified amount of the item from the inventory.

    Shop-purchased items are decremented from purchases.items instead of
    the per-module inventory dict.
    """
    if item_id in game_globals.inventory:
        game_globals.inventory[item_id] -= amount
        if game_globals.inventory[item_id] <= 0:
            del game_globals.inventory[item_id]
        return
    shop_items = _shop_purchases_items()
    if shop_items is not None and item_id in shop_items:
        shop_items[item_id] = max(0, shop_items.get(item_id, 0) - amount)
        if shop_items[item_id] <= 0:
            del shop_items[item_id]

def get_item_by_id(item_id):
    """
    Gets an item object by item ID across all modules.
    Returns the item object if found, None otherwise.
    """
    # Search through all loaded modules for the item
    for module_name, module in runtime_globals.game_modules.items():
        # Check if module has items
        if hasattr(module, "items"):
            # Search for item by ID
            for item in module.items:
                if item.id == item_id:
                    return item
    
    return None

def item_fits_pet(item, pet) -> bool:
    """Whether *pet* can use *item*, by the item's `digisoul`, `min_stage`,
    `max_stage` and, for an evolving item, whether it has a form to become
    (`item_effects.fits`).

    A `status_boost` item that names a DigiSoul family belongs to pets of
    that family (`monster.json.digisoul`) and to nobody else. Every other
    item fits every pet: on a `dna` item the family is what it gives, not
    who may take it.
    """
    from utils import item_effects
    if not item_effects.fits(item, pet):
        return False
    family = getattr(item, "digisoul", "") or ""
    if not family or getattr(item, "effect", "") != "status_boost":
        return True
    return (getattr(pet, "digisoul", "") or "").casefold() == family.casefold()


def active_boost_item(module_name, field="protocol_value"):
    """*module_name*'s latest active battle boost item that declares *field*.

    A `status_boost` item stores its effect in `game_globals.battle_effects`
    with the item's id, and stays there while the boost lasts. The latest
    such boost wins, as a newly equipped weapon replaces the last.
    """
    found = None
    for effect in game_globals.battle_effects.values():
        if not isinstance(effect, dict) or effect.get("module") != module_name:
            continue
        item = get_item_by_id(effect.get("item_id"))
        if item is not None and getattr(item, field, 0):
            found = item
    return found


def active_attack_sprite(pet):
    """The ordinary attack sprite *pet*'s active boost item gives it, or 0.

    The item names the sprite (`attack_sprite`, an id in its module's
    `atk/`). Only for a pet that can use the item (`item_fits_pet`), and a
    wire with a rule of its own about that applies it too: an iC weapon
    changes the sprite only of a Digimon that can use it (`IC.weapon_tier`).
    """
    module_name = getattr(pet, "module", None)
    item = active_boost_item(module_name, "attack_sprite") if module_name else None
    if item is None or not item_fits_pet(item, pet):
        return 0
    from battle import ic_attacks
    if ic_attacks.is_ic_native(pet) and not ic_attacks.IC.weapon_tier(
            getattr(item, "protocol_value", 0), getattr(pet, "digisoul", None)):
        return 0
    return int(item.attack_sprite)


def active_protocol_value(module_name):
    """The wire value of *module_name*'s active battle boost, or 0.

    A `status_boost` item stores its effect in `game_globals.battle_effects`
    with the item's id, and stays there while the boost lasts. An item that
    declares a `protocol_value` puts it on its module's wire for as long as
    that is so: an iC weapon is sent in packet 3 while it is equipped. The
    latest such boost wins, as a newly equipped weapon replaces the last.
    """
    value = 0
    for effect in game_globals.battle_effects.values():
        if not isinstance(effect, dict) or effect.get("module") != module_name:
            continue
        item = get_item_by_id(effect.get("item_id"))
        if item is not None and getattr(item, "protocol_value", 0):
            value = item.protocol_value
    return value


def get_item_by_name(module_name, item_name):
    """
    Gets an item object by module name and item name.
    Returns the item object if found, None otherwise.
    """
    # Check if module exists
    if module_name not in runtime_globals.game_modules:
        return None
    
    module = runtime_globals.game_modules[module_name]
    
    # Check if module has items
    if not hasattr(module, "items"):
        return None
    
    # Search for item by name
    for item in module.items:
        if item.name == item_name:
            return item
    
    return None