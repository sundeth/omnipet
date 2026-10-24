"""The Digivice iC's attack sprites: which of its own it draws, and when.

Read off real devices from 2026-09-30 on (utilities/IC/protocol.txt). The iC
never takes a sprite id from the wire. It draws every Digimon's attacks from
its own small library, and three things choose among them:

* **the Max Reliability flag**, the low bit of packet 2's Kind nibble.
  Clear, every Digimon throws the standard ordinary shot and the standard
  critical. Set (Reliability 31, Perfect or above), it throws the "strong"
  ordinary shot and a critical of its own.
* **the Power byte**, whose top three bits are the Digimon's family and
  decide whose critical that is (claw, wolf head, wing, thorns, cross) and,
  with the flag clear, whether a sender is drawn with sprite 3.
* **a weapon it can use**, which replaces the ordinary shot at any
  Reliability: one sprite for the any-family weapons and one per family.

The ids are the IC module's own (`modules/IC/atk/`, `atk_crit/`), named in
`protocol_constants.IC`, and every iC Digimon carries them as data:
`atk_main` the standard shot, `atk_alt` the Max Reliability one and
`atk_alt_2` its Max Reliability critical. So it has its sprites on every
other line as well, and here the flag picks between the first two.
"""

from battle.sim import protocol_constants
from core import runtime_globals

IC = protocol_constants.IC


def is_ic_native(entity, default_module=None) -> bool:
    """Whether *entity* is a Digivice iC's own Digimon.

    True for a pet or enemy whose module declares the IC wire or is the one
    the wire names as its own (`IC.NATIVE_MODULES`), whatever it declares.
    """
    name = getattr(entity, "module", None) or default_module
    if not name:
        return False
    if name in IC.NATIVE_MODULES:
        return True
    module = (getattr(runtime_globals, "game_modules", None) or {}).get(name)
    return is_ic_module(module)


def is_ic_module(module) -> bool:
    """Whether a loaded module is a Digivice iC's: it declares the IC wire
    or is one the wire names as its own."""
    if module is None:
        return False
    if getattr(module, "name", None) in IC.NATIVE_MODULES:
        return True
    declared = getattr(module, "battle_protocol", "") or ""
    return protocol_constants.canonical_format(declared) == IC.NAME


def max_reliability(entity, default_module=None) -> bool:
    """Whether *entity* fights with the Max Reliability flag set.

    A device's side says so itself (`ic_max_reliability`, read off its
    packet). A pet of ours qualifies by the playbook's two stats:
    Reliability 31 and Perfect or above. Nothing from another line ever does.
    """
    stated = getattr(entity, "ic_max_reliability", None)
    if stated is not None:
        return bool(stated)
    if not is_ic_native(entity, default_module):
        return False
    reliability = int(getattr(entity, "reliability", 0) or 0)
    stage = int(getattr(entity, "stage", 0) or 0)
    return (reliability >= IC.MAX_RELIABILITY
            and stage >= IC.MAX_RELIABILITY_MIN_STAGE)


def weapon(entity, default_module=None) -> int:
    """The number of the weapon *entity* fights with, 0 for none.

    A device's side states it (`ic_weapon`, read off its packets). A pet of
    ours holds the active boost item its module declares a `protocol_value`
    for, which is what `pet_to_digimon` sends.
    """
    stated = getattr(entity, "ic_weapon", None)
    if stated is not None:
        return int(stated or 0)
    if not is_ic_native(entity, default_module):
        return 0
    from utils.inventory_utils import active_protocol_value
    return active_protocol_value(getattr(entity, "module", None) or default_module)


def _own_sprite(entity, field, fallback):
    """The Digimon's own *field* where it is one of the iC's ordinary ids."""
    sprite = int(getattr(entity, field, 0) or 0)
    return sprite if sprite in IC.NORMAL_SPRITES else fallback


def attack_ids(entity, default_module=None):
    """The ``(ordinary, critical)`` ids an iC Digimon throws.

    Flag clear: its `atk_main` and the wire's standard critical. Flag set:
    its `atk_alt` and its own critical, `atk_alt_2`, falling back to the
    standard one when its critical is not known yet. Either way a weapon it
    can use replaces the ordinary sprite: the one its item names
    (`attack_sprite`) for a pet of ours, the wire's own table
    (`IC.weapon_sprite`) for a side read off a device.
    """
    armed = 0
    if getattr(entity, "ic_weapon", None) is None and is_ic_native(entity, default_module):
        from utils.inventory_utils import active_attack_sprite
        armed = active_attack_sprite(entity)
        if armed not in IC.NORMAL_SPRITES:
            armed = 0
    armed = armed or IC.weapon_sprite(weapon(entity, default_module),
                                      getattr(entity, "digisoul", None))
    if max_reliability(entity, default_module):
        crit = int(getattr(entity, "atk_alt_2", 0) or 0)
        return (armed or _own_sprite(entity, "atk_alt", IC.MAX_RELIABILITY_SPRITE),
                crit if crit in IC.CRIT_SPRITES else IC.STANDARD_CRIT)
    return (armed or _own_sprite(entity, "atk_main", IC.STANDARD_SPRITE),
            IC.STANDARD_CRIT)


def sender_sprites(kind, power, weapon=0, family=None):
    """What an iC draws for a side that sent *kind*, *power* and *weapon*.

    Returns ``(atk_main, atk_alt, atk_alt_2, max_reliability)`` in the IC
    module's ids, ready for a parsed opponent: the ordinary sprite its
    flag-clear battles draw, the Max Reliability one, the critical its Power
    band names, and whether the flag is set. A weapon the side can use is
    both ordinary sprites; *family* is its `digisoul` where the roster
    named it.
    """
    armed = IC.weapon_sprite(weapon, family)
    return (armed or IC.normal_for_power(power),
            armed or IC.MAX_RELIABILITY_SPRITE,
            IC.crit_for_power(power), IC.is_max_reliability(kind))


def wire_strength(pet) -> int:
    """The strength a pet of ours sends in packet 2's low five bits.

    An iC's own Digimon carries it: the module's `power` is the device's
    strength x10 (`IC.POWER_SCALE`), the scale every module uses. Its base
    value, since the device's did not move with Reliability, wins or
    weapons. Any other pet, or one with no power, sends its stage's
    (`IC.STRENGTH_BY_STAGE`).
    """
    if is_ic_native(pet):
        strength = int(round((getattr(pet, "power", 0) or 0) / IC.POWER_SCALE))
        if strength > 0:
            return min(IC.MAX_STRENGTH, strength)
    return IC.stage_value(IC.STRENGTH_BY_STAGE, getattr(pet, "stage", 0))
