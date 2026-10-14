"""
Connect Points: a pet's points from battling other devices and pets.

A module turns them on with events.json's ``connect_points`` block:

    {"cap": 15, "win": 1, "loss": 1,
     "rewards": [{"version": 1, "item": "Leo Cap"}, ...]}

Every battle with another device or pet (DCom, Versus, online) gives the pet
``win`` or ``loss`` points. When they reach ``cap`` the pet gets one of the
rewards of its version (a reward with no version is for every version), each
listed reward equally likely -- listing an item twice doubles its chance --
and its points go back to 0. A cap of 0, or no block, switches the system
off. The points are the pet's own (`GamePet.connect_points`) and are kept
through evolution: the Digivice iC fills its meter over a Digimon's whole
life.
"""

import random

from core import runtime_globals


def settings(module) -> dict:
    """The module's ``connect_points`` block, or {} when it has none or its
    cap is 0."""
    block = (module.load_event_extras().get("connect_points") or {}) if module else {}
    try:
        return block if int(block.get("cap", 0) or 0) > 0 else {}
    except (TypeError, ValueError):
        return {}


def rewards_for(block, version) -> list:
    """The item names the pet's *version* can draw, one entry a listing."""
    out = []
    for row in block.get("rewards") or []:
        if not isinstance(row, dict) or not row.get("item"):
            continue
        wanted = row.get("version")
        if wanted not in (None, "", 0) and int(wanted) != int(version or 0):
            continue
        out.append(row["item"])
    return out


def award(pet, won, rng=random):
    """Give *pet* its points for one battle; at the cap, its reward. Returns
    the item name given, or ""."""
    from utils.module_utils import get_module
    module = get_module(getattr(pet, "module", None))
    block = settings(module)
    if not block:
        return ""
    gain = int(block.get("win" if won else "loss", 0) or 0)
    cap = int(block["cap"])
    pet.connect_points = max(0, int(getattr(pet, "connect_points", 0) or 0) + gain)
    if pet.connect_points < cap:
        return ""
    pet.connect_points = 0
    choices = rewards_for(block, getattr(pet, "version", 0))
    if not choices:
        return ""
    name = rng.choice(choices)
    from utils.inventory_utils import add_to_inventory, get_item_by_name
    item = get_item_by_name(module.name, name)
    if item is None:
        runtime_globals.game_console.log(f"[Connect Points] {module.name} has no item {name}")
        return ""
    add_to_inventory(item.id, 1)
    message = getattr(runtime_globals, "game_message", None)
    if message is not None:
        try:
            message.add_slide(f"Connect Points full: {name}!", (255, 255, 0),
                              56 * runtime_globals.UI_SCALE, runtime_globals.FONT_SIZE_SMALL)
        except Exception:
            pass
    runtime_globals.game_console.log(f"[Connect Points] {pet.name} filled its meter: {name}")
    return name
