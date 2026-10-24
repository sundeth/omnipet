"""
Connect Points: a pet's points from battles, and the item filling them gives.

A module turns them on with events.json's ``connect_points`` block:

    {"cap": 15, "win": 1, "loss": 1, "battles": ["connection"],
     "rewards": [{"version": 1, "item": "Leo Cap"}, {"item": ""}, ...]}

``battles`` names the battles that give points: ``connection``, a battle with
another device or pet (DCom, Versus, online), and ``adventure``, an adventure
battle; absent, connections only (the Digivice iC's meter). Each such battle
gives the pet ``win`` or ``loss`` points. When they reach ``cap`` the pet
draws one of the rewards of its version (a reward with no version is for
every version), each listed reward equally likely -- listing an item twice
doubles its chance -- and its points go back to 0. A reward naming no item
(``"item": ""``) is a draw that gives nothing, so a cap of 1 makes a drop
table rolled after every battle that counts (the Vital Bracelets, owner
2026-10-21: "set it to 1 and add the items with odds so that no item can be
obtained"). A cap of 0, or no block, switches the system off. The points are
the pet's own (`GamePet.connect_points`) and are kept through evolution: the
Digivice iC fills its meter over a Digimon's whole life.
"""

import random

from core import runtime_globals

#: The battles a module's ``battles`` can name.
BATTLES = ("connection", "adventure")
#: A block without ``battles``: battles with another device or pet only.
DEFAULT_BATTLES = ("connection",)


def settings(module) -> dict:
    """The module's ``connect_points`` block, or {} when it has none or its
    cap is 0."""
    block = (module.load_event_extras().get("connect_points") or {}) if module else {}
    try:
        return block if int(block.get("cap", 0) or 0) > 0 else {}
    except (TypeError, ValueError):
        return {}


def battles(block) -> tuple:
    """The battles that give *block*'s points (``battles``, else connections)."""
    named = block.get("battles") if isinstance(block, dict) else None
    if isinstance(named, str):
        named = [named]
    named = tuple(str(b).lower() for b in named or () if str(b).lower() in BATTLES)
    return named or DEFAULT_BATTLES


def shows_meter(block) -> bool:
    """Whether the status screen shows the meter: not for a cap of 1, where
    every battle that counts draws at once and the meter never shows a
    point."""
    try:
        return int(block.get("cap", 0) or 0) > 1
    except (TypeError, ValueError, AttributeError):
        return False


def rewards_for(block, version) -> list:
    """The item names the pet's *version* can draw, one entry a listing,
    "" for a listing that gives nothing."""
    out = []
    for row in block.get("rewards") or []:
        if not isinstance(row, dict):
            continue
        wanted = row.get("version")
        if wanted not in (None, "", 0) and int(wanted) != int(version or 0):
            continue
        out.append(str(row.get("item") or ""))
    return out


def award(pet, won, rng=random, battle="connection"):
    """Give *pet* its points for one *battle* (``connection`` or
    ``adventure``) when its module counts that battle; at the cap, a draw
    from its rewards. Returns the item name given, or ""."""
    from utils.module_utils import get_module
    module = get_module(getattr(pet, "module", None))
    block = settings(module)
    if not block or battle not in battles(block):
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
    if not name:
        runtime_globals.game_console.log(f"[Connect Points] {pet.name}: no item this time")
        return ""
    from utils.inventory_utils import add_to_inventory, get_item_by_name
    item = get_item_by_name(module.name, name)
    if item is None:
        runtime_globals.game_console.log(f"[Connect Points] {module.name} has no item {name}")
        return ""
    add_to_inventory(item.id, 1)
    message = getattr(runtime_globals, "game_message", None)
    if message is not None:
        text = f"Connect Points full: {name}!" if shows_meter(block) else f"Found {name}!"
        try:
            message.add_slide(text, (255, 255, 0),
                              56 * runtime_globals.UI_SCALE, runtime_globals.FONT_SIZE_SMALL)
        except Exception:
            pass
    runtime_globals.game_console.log(f"[Connect Points] {pet.name} filled its meter: {name}")
    return name
