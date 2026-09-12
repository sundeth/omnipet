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

from core import runtime_globals


def build(my_pet, opponent, battle_result, battle_format, simulator,
          minigame_result=0, opponent_name=None, is_dcom_mode=True,
          enemy_first=True,
          xros_forms=None):
    """Fill `runtime_globals.pvp_battle_data` from a finished exchange.

    *simulator* is the `DComBattleSimulator` the exchange ran on: it owns the
    HP the battle was actually fought with, which is the wire's and not the
    pet's.
    """
    from battle.sim.dcom_battle_simulator import (is_oem_pet, module_for_format,
                                                  pet_to_digimon)

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

    # The opponent is a real device, so its sprites belong to the module that
    # reproduces that device -- its attack sprites, and its own sprite format.
    # Handing it the player's module (which is what happened before) drew a
    # Digital Monster's shots with whatever module the player was raising.
    # When the player does not own it, the player's module stands in, which is
    # what the game has always done.
    #
    # **A crossover edition brings its own.** DMC, DMGZ, DMH and DMXW all
    # speak the Colour line, and the Monster Hunter edition has its own 117
    # attack sprites at the same ids as the shared library -- so an opponent
    # that resolved on one of those rosters has to draw from that module, or
    # it gets standard Colour shots for a Digimon that has none. Filmed
    # battle 44 is that case. `_name_opponent` records which roster answered.
    protocol_module = module_for_format(battle_format)
    opponent_module = (getattr(opponent, "source_module", None)
                       or (protocol_module.name if protocol_module
                           else getattr(my_pet, "module", "base")))

    # Attack sprite ids are already 1-based here: parse_opponent shifts them
    # on the way in.
    #
    # **shot1 is the STRONG shot and shot2 the weak one**, which is the order
    # `pet_to_digimon` packs them in on the way out -- so they cross over to
    # `atk_alt` and `atk_main`, not straight across. They used to go straight
    # across, which drew every weak shot with the device's strong sprite and
    # every strong one with its weak sprite: real ids off the wire, on the
    # wrong shots.
    #
    # The DMX wire carries a third, `dmx_shot_m`, which is the critical's --
    # without it a device's critical fell back to a doubled ordinary sprite
    # however plainly the packet named one.
    opponent_pet_data = {
        "name": opponent.name,
        "stage": opponent.stage,
        "level": opponent.level,
        "hp": simulator.get_initial_hp(opponent),
        "power": opponent.power,
        "attribute": opponent.attribute,
        "atk_main": opponent.shot2,
        "atk_alt": opponent.shot1,
        "atk_alt_2": getattr(opponent, "dmx_shot_m", 0) or 0,
        "module": opponent_module,
        # Whose attack library its shot ids are numbered in. Normally the
        # line's, which is what a connection battle draws from -- but a
        # crossover edition ships its own `atk/` at the same ids, and when
        # the opponent resolved onto that roster we know which device fired.
        "attack_sprite_module": getattr(opponent, "source_module", None),
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
