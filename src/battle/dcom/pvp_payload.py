"""The payload that hands a finished packet exchange to the battle scene.

A DCom battle and a WiFiCom battle end the same way: both sides' packets have
been exchanged, a `BattleResult` has been built from them, and the player
should now watch it play out. The scene reads one dictionary, so building it
belongs in one place rather than once per pipe.

**device1 is the opponent and device2 is us, and it stays that way.** The
packets come out toy-first, so that is the order the result carries and the
order `draw_pets` / `draw_enemies` already expect. Remapping it as well swaps
the sides twice and puts every hit on the wrong pet.
"""

from battle.sim import protocol_constants
from core import runtime_globals


def opponent_attack_sprites(opponent, battle_format=None):
    """A DCom opponent's attack sprite ids: ``(atk_main, atk_alt, atk_alt_2)``.

    **A connection opponent is a device, and what it draws with belongs to
    the line it is fought on** -- not to the module the player happens to be
    raising, and not always to the packet either. Each wire answers this its
    own way, and the wire is what says which:

    * a line declaring ``ENEMY_ATTACK_SPRITES`` has a FIXED pair, because
      the device does. The Digimon Mini draws one projectile for its whole
      roster and one Hyper, so a DMM opponent is that module's 1 and 2 whatever its
      Projectile field said -- that field is the ordinary shot and the wire
      has no field for the Hyper at all;
    * a line declaring ``FORCED_ATTACK_SPRITE`` draws one sprite for
      everything, which is the Digital Monster and the original Pendulum.
      That one is applied at animation time, since it overrides both sides;
    * everything else carries real ids per Digimon in its packets, which is
      the DMX, the Colour line and the 20th lines, and they are read below.

    For the packet-carried case: ids are already 1-based here (`parse_opponent`
    shifts them on the way in), and **shot1 is the STRONG shot and shot2 the
    weak one** -- the order `pet_to_digimon` packs them in on the way out --
    so they cross over to `atk_alt` and `atk_main` rather than going straight
    across. Straight across drew every weak shot with the device's strong
    sprite and every strong one with its weak sprite. The DMX carries a third,
    `dmx_shot_m`, the critical's; without it a device's critical fell back to
    a doubled ordinary sprite however plainly the packet named one.

    **None of this touches our own pet**, which keeps its module's own pair
    and plays the line's ladder with it: a PENC pet fighting a Mini draws its
    own shots, three of `atk_main` and then one `atk_alt` at double size.

    **Both places that build an opponent read it here.** The DCom encounter
    builds its own `GameEnemy` rather than going through this payload, and it
    had the crossover the other way round.
    """
    limits = protocol_constants.get_constants(battle_format or "")
    fixed = getattr(limits, "ENEMY_ATTACK_SPRITES", None) if limits else None
    if fixed:
        return (fixed[0], fixed[1], 0)
    # The iC sends no sprite ids: the parser has already read which of the
    # iC's own sprites a receiving iC would draw it with (battle.ic_attacks).
    ic_sprites = getattr(opponent, "ic_sprites", None)
    if ic_sprites:
        return tuple(ic_sprites)
    return (opponent.shot2, opponent.shot1,
            getattr(opponent, "dmx_shot_m", 0) or 0)


def opponent_module(opponent, battle_format, fallback=None):
    """Which module an opponent's sprites belong to.

    The opponent is a real device, so its sprites belong to the module that
    reproduces that device -- its attack sprites, and its own sprite format.
    Handing it the player's module (which is what happened before) drew a
    Digital Monster's shots with whatever module the player was raising.
    When the player does not own it, *fallback* stands in, which is what the
    game has always done.

    **A crossover edition brings its own.** DMC, DMGZ, DMH and DMXW all speak
    the Colour line, and the Monster Hunter edition has its own 117 attack
    sprites at the same ids as the shared library -- so an opponent that
    resolved on one of those rosters has to draw from that module, or it gets
    standard Colour shots for a Digimon that has none. Filmed battle 44 is
    that case. `_name_opponent` records which roster answered, and it records
    it whenever the *module* is unambiguous even where the name is not -- a
    Ver.1 Numemon and a Ver.2 Sukamon are one Digimon Mini either way.
    """
    from battle.sim.dcom_battle_simulator import module_for_format

    protocol_module = module_for_format(battle_format)
    return (getattr(opponent, "source_module", None)
            or (protocol_module.name if protocol_module else fallback))


def build(my_pet, opponent, battle_result, battle_format, simulator,
          minigame_result=0, opponent_name=None, is_dcom_mode=True,
          enemy_first=True,
          xros_forms=None):
    """Fill `runtime_globals.pvp_battle_data` from a finished exchange.

    *simulator* is the `DComBattleSimulator` the exchange ran on: it owns the
    HP the battle was actually fought with, which is the wire's and not the
    pet's.
    """
    from battle.sim.dcom_battle_simulator import is_oem_pet, pet_to_digimon

    my_pet_data = {
        "name": getattr(my_pet, "name", "Pet"),
        "stage": getattr(my_pet, "stage", 1),
        "level": getattr(my_pet, "level", 1),
        # The HP the battle was fought with belongs to the wire, not the pet:
        # DMC, DM20 and PEN20 all fix it. Sending the pet's own left a
        # Shoutmon on a 12 HP bar for a fight the log drained from 5.
        "hp": simulator.get_initial_hp(
            pet_to_digimon(my_pet, battle_format, minigame_result)),
        "power": (my_pet.get_power() if hasattr(my_pet, "get_power")
                  else getattr(my_pet, "power", 1)),
        "attribute": getattr(my_pet, "attribute", 0),
        "atk_main": getattr(my_pet, "atk_main", None),
        "atk_alt": getattr(my_pet, "atk_alt", None),
        "module": getattr(my_pet, "module", "base"),
        "sick": getattr(my_pet, "sick", 0) > 0,
        "traited": getattr(my_pet, "traited", False),
        "shook": getattr(my_pet, "shook", False),
        "mini_game": minigame_result,
    }

    device_module = opponent_module(opponent, battle_format,
                                    getattr(my_pet, "module", "base"))
    atk_main, atk_alt, atk_alt_2 = opponent_attack_sprites(opponent,
                                                            battle_format)

    opponent_pet_data = {
        "name": opponent.name,
        "stage": opponent.stage,
        "level": opponent.level,
        "hp": simulator.get_initial_hp(opponent),
        "power": opponent.power,
        "attribute": opponent.attribute,
        "atk_main": atk_main,
        "atk_alt": atk_alt,
        "atk_alt_2": atk_alt_2,
        "module": device_module,
        # Whose attack library its shot ids are numbered in. Normally the
        # line's, which is what a connection battle draws from -- but a
        # crossover edition ships its own `atk/` at the same ids, and when
        # the opponent resolved onto that roster we know which device fired.
        "attack_sprite_module": getattr(opponent, "source_module", None),
        # An iC side says whether its Max Reliability flag is set;
        # None for every other line.
        "ic_max_reliability": getattr(opponent, "ic_max_reliability", None),
        # Its weapon's number and its family, which pick its ordinary sprite.
        "ic_weapon": getattr(opponent, "ic_weapon", None),
        "digisoul": getattr(opponent, "digisoul", None),
        "sick": bool(opponent.sick),
        "traited": bool(opponent.traited),
        "shook": bool(opponent.egg_shake),
        "mini_game": opponent.mini_game,
    }

    simulation_data = {
        "battle_log": (battle_result.to_dict()
                       if hasattr(battle_result, "to_dict") else {}),
        "team1": [my_pet_data],
        "team2": [opponent_pet_data],
        "module": getattr(my_pet, "module", "base"),
        # device1 is the other side in an exchange result, so its win is our
        # defeat.
        "victory_status": ("Defeat" if battle_result.winner == "device1"
                           else "Victory"),
    }

    runtime_globals.pvp_battle_data = {
        "simulation_data": simulation_data,
        "original_battle_log": battle_result,
        "is_host": True,
        "my_pets": [my_pet],
        "my_team_data": [my_pet_data],
        "enemy_team_data": [opponent_pet_data],
        "module": getattr(my_pet, "module", "base"),
        "my_player_name": "YOU",
        "enemy_player_name": opponent_name or battle_format,
        "is_online_mode": False,
        "is_dcom_mode": is_dcom_mode,
        "is_oem_mode": is_oem_pet(my_pet, battle_format),
        "battle_format": battle_format,
        "opponent_device_version": getattr(simulator, "opponent_device_version", None),
        # The toy normally opens the exchange, so it normally strikes
        # first -- but the player can open it instead, and then the order
        # follows. The caller says which.
        "enemy_first": enemy_first,
    }
    if xros_forms:
        runtime_globals.pvp_battle_data["xros_forms"] = xros_forms
    return runtime_globals.pvp_battle_data
