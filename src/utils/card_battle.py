"""
The Vital Bracelet's random battle as a module event (event type 6, "card
battle"): the BE's NFC battle, which touching any NFC source starts, fired by
the hourly XAI roll instead.

The opponent is a character of the pet's own card: a monster of the pet's
version, chosen by the monsters' ``encounter_chances`` (monster.json, three
percentages: for a pet of stage 1-4, 5-7 and 8). A roll of 0-99 is taken off
each character's chance in card order (``index``) and the one that takes it
below zero is met; if none does, the pet meets its own species. Only a pet of
stage 3 or higher battles. (GMMan's BE battle notes, gist ab92d0ec...;
VitalWear's ``assignRandomTargetFromCard`` walks the card the same way but
gives the third chance to stages 7-8.)

After the battle each pet of the module that fought:

* gains or loses Vital Values by its stage against the opponent's
  (`vital_change`, the BE table), within its stage's cap; a win counts
  double under an active ``vp`` multiplier (`GamePet.active_boost`). An
  Adventure battle pays the same (`battle_vital_values`): "winning battles
  will increase them, while losing battles will decrease them" (humulos'
  VB and BE guides);
* on a win, gets the next item of the event's ``item_sequence`` (Cyanic's BE
  grant order; "" a win without an item), its place kept per event in
  ``GamePet.event_sequence``.

Battles and wins count as any battle's do (`GamePet.finish_battle`).
"""

import random
import time

from core import runtime_globals

#: The highest stage of each ``encounter_chances`` slot: stages 1-4 use the
#: first, 5-7 the second, 8 and above the third.
STAGE_GROUPS = (4, 7)

#: Only a Digimon of stage III or higher battles (the BE manual).
MIN_STAGE = 3

#: Vital Values won and lost, by own stage then the opponent's, stages 3-8
#: (GMMan's BE battle notes; humulos' manual table agrees for III-VI).
VITAL_WIN = {
    3: (200, 300, 600, 1200, 1800, 2400),
    4: (100, 300, 450, 700, 1400, 2100),
    5: (20, 150, 400, 600, 800, 1600),
    6: (20, 20, 400, 500, 750, 900),
    7: (20, 20, 20, 500, 600, 800),
    8: (20, 20, 20, 20, 600, 700),
}
VITAL_LOSS = {
    3: (160, 100, 20, 20, 20, 20),
    4: (300, 240, 150, 20, 20, 20),
    5: (600, 450, 320, 400, 20, 20),
    6: (1200, 700, 600, 400, 500, 20),
    7: (1800, 1400, 800, 750, 480, 600),
    8: (2400, 2100, 1600, 900, 800, 560),
}


def _log(text):
    console = getattr(runtime_globals, "game_console", None)
    if console is not None:
        console.log(text)


def chance_slot(stage) -> int:
    """Which of the ``encounter_chances`` a pet of *stage* uses."""
    stage = int(stage or 0)
    for slot, top in enumerate(STAGE_GROUPS):
        if stage <= top:
            return slot
    return len(STAGE_GROUPS)


def can_battle(pet) -> bool:
    return (getattr(pet, "state", "") not in ("dead", "nap", "dying")
            and int(getattr(pet, "stage", 0) or 0) >= MIN_STAGE)


def _chance(record, slot) -> int:
    chances = record.get("encounter_chances") or []
    try:
        value = chances[slot]
    except (IndexError, TypeError):
        return 0
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def pick_opponent(module, version, stage, rng=random, own_name=None):
    """The monster record a pet of *version* and *stage* meets, or None when
    the card holds neither a chosen character nor the pet's own species."""
    # Eggs (index -1) are not on the card.
    records = [m for m in module.get_all_monsters()
               if int(m.get("version") or 0) == int(version or 0)
               and int(m.get("index", -1) if m.get("index") is not None else -1) >= 0]
    records.sort(key=lambda m: int(m["index"]))
    slot = chance_slot(stage)
    roll = rng.randrange(100)
    for record in records:
        roll -= _chance(record, slot)
        if roll < 0:
            return record
    # A card whose chances fall short of 100: the pet meets its own species.
    return next((m for m in records if m.get("name") == own_name), None)


def vital_change(stage, enemy_stage, won) -> int:
    """The Vital Values a pet of *stage* gains (+) or loses (-) against an
    opponent of *enemy_stage*. Stages outside 3-8 count as the nearest."""
    own = max(3, min(8, int(stage or 0)))
    other = max(3, min(8, int(enemy_stage or 0))) - 3
    return VITAL_WIN[own][other] if won else -VITAL_LOSS[own][other]


def battle_vital_values(pet, enemy_stage, won):
    """Pay *pet* the Vital Values of a battle against an opponent of
    *enemy_stage* (`vital_change`, a win doubled under a ``vp`` multiplier),
    within its stage's cap. Only a pet of a module with the meter that can
    battle (stage III+) is paid. Returns the change made."""
    if not can_battle(pet) or not pet.tracks_vital_values():
        return 0
    change = vital_change(pet.stage, enemy_stage, won)
    if change > 0:
        change *= boost_factor(pet, "vp")
    ceiling = pet.vital_value_cap() or 9999
    old = int(getattr(pet, "vital_values", 0) or 0)
    pet.vital_values = max(0, min(max(ceiling, old), old + change))
    _log(f"[Battle] {pet.name}: Vital Values {old} -> {pet.vital_values}")
    return pet.vital_values - old


# The pet's active item ----------------------------------------------------

def boost_factor(pet, target) -> int:
    """The multiplier *pet*'s active item puts on *target* ("pp", "vp"...),
    1 for none. An expired item is cleared."""
    boost = getattr(pet, "active_boost", None)
    if not boost:
        return 1
    if float(boost.get("until", 0) or 0) <= time.time():
        pet.active_boost = None
        return 1
    if target not in (boost.get("targets") or []):
        return 1
    return max(1, int(boost.get("amount", 1) or 1))


def set_boost(pet, item_name, targets, amount, minutes):
    """Make *item_name* the pet's one active item (a new one replaces it)."""
    pet.active_boost = {"item": item_name, "targets": list(targets),
                        "amount": int(amount), "until": time.time() + int(minutes) * 60}


# Rewards ------------------------------------------------------------------

def next_reward(pet, data) -> str:
    """The item *pet* gets for a win of *data* (an EventData), its place in
    the sequence moved on; "" for a win without one."""
    sequence = list(getattr(data, "item_sequence", None) or [])
    if not sequence:
        return ""
    places = getattr(pet, "event_sequence", None)
    if not isinstance(places, dict):
        places = pet.event_sequence = {}
    index = int(places.get(data.id, 0) or 0)
    places[data.id] = (index + 1) % len(sequence)
    return str(sequence[index % len(sequence)] or "")


def finish(module_name, data, pets, enemy_stage, won):
    """Pay *pets* (the module's pets that fought) for a card battle against an
    opponent of *enemy_stage*. Returns lines for the player."""
    from utils.inventory_utils import add_to_inventory, get_item_by_name
    lines = []
    for pet in pets:
        if getattr(pet, "module", None) != module_name or not can_battle(pet):
            continue
        battle_vital_values(pet, enemy_stage, won)
        if not won:
            continue
        name = next_reward(pet, data)
        if not name:
            continue
        item = get_item_by_name(module_name, name)
        if item is None:
            _log(f"[CardBattle] {data.name}: no item {name}")
            continue
        if add_to_inventory(item.id, 1):
            lines.append(f"{item.name}!")
    return lines
