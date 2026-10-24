"""Evolution items: what the Armor / Item menu offers (owner, 2026-10-15).

One menu evolves a pet with an item, whatever kind of item it is:

    a route item      an `item` route of the pet (D-3's DigiMentals, the
                      Twin's Bombs): each use counts, and the route is taken
                      once its `item_amount` is reached (GamePet.use_evolution_item);
    an evolve item    item.json effect "evolve" (the iC's Ouryujin, Digimon
                      World's Black Wing): the item's own target, for a pet
                      within its stages (item_effects.evolve_target);
    a random one      effect "random_evolve" (the iC's R-Shinka): one of the
                      pet's next-stage forms.

The inventory still uses evolve and random items as before.
"""
from utils import item_effects

#: Item effects that evolve a pet by themselves.
ITEM_EVOLUTIONS = ("evolve", "random_evolve")
#: The armor items' effect (their routes name them).
DIGIMENTAL = "digimental"


def route_items(pet):
    """Names of the items this pet's routes ask for."""
    return {evo.get("item") for evo in getattr(pet, "evolve", None) or [] if evo.get("item")}


def is_evolution_item(item, pets=()):
    """Whether *item* belongs in the menu: an armor or evolving item, or one
    a route of a party pet names."""
    effect = getattr(item, "effect", "")
    if effect == DIGIMENTAL or effect in ITEM_EVOLUTIONS:
        return True
    name = getattr(item, "name", None)
    return any(name in route_items(pet) for pet in pets)


def can_use(pet, item):
    """Whether using *item* on *pet* does something: its own target or a
    next-stage form for an evolving item, a route naming it otherwise."""
    if pet is None or item is None:
        return False
    if getattr(item, "effect", "") in ITEM_EVOLUTIONS:
        return getattr(item, "module", getattr(pet, "module", None)) == pet.module and item_effects.fits(item, pet)
    return getattr(item, "name", None) in route_items(pet)


def use(pet, item):
    """Use *item* on *pet*. Returns (consumed, evolved): an evolving item is
    consumed only when it evolves the pet; a route item's use always counts."""
    if getattr(item, "effect", "") in ITEM_EVOLUTIONS:
        took = item_effects.apply_pet_effect(item, pet)
        return bool(took), bool(took)
    before = pet.name
    pet.use_evolution_item(item.name)
    return True, pet.name != before
