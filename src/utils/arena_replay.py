"""Play a stored arena battle in the PvP battle scene.

The server fought the battle; this only shows it. The player's side is
drawn with throwaway pets rebuilt from the local module (never the real
pets in the save, which the scene would otherwise charge a battle cost and
count a PvP battle on), and the opponent as enemies, whose sprites fall back
to the shared art when their module is not installed here.
"""
from battle.arena import replay as arena_replay
from core import runtime_globals
from utils.scene_utils import change_scene


def _local_pet(entry):
    """A disposable GamePet for one of the viewer's own team entries."""
    from models.game_pet import GamePet
    from utils.module_utils import get_module
    module = get_module(entry["module"])
    data = module.get_monster(entry["name"], entry["version"])
    if data is None:
        raise LookupError(entry["name"])
    data = dict(data, module=entry["module"])
    pet = GamePet(data, traited=bool(entry.get("traited")))
    pet.level = int(entry.get("level", 1))
    pet.shook = bool(entry.get("shook"))
    return pet


def _enemy_data(entry):
    """The dict ``BattleEncounter.setup_pvp_teams`` builds an enemy from."""
    return {
        "name": entry["name"],
        "power": entry["power"],
        "attribute": entry["attribute"],
        "atk_main": entry["atk_main"],
        "atk_alt": entry["atk_alt"],
        "atk_alt_2": entry.get("atk_alt_2", 0),
        "stage": entry["stage"],
        "hp": entry["hp"],
        "level": entry.get("level", 1),
        "sick": False,
        "traited": bool(entry.get("traited")),
        "shook": bool(entry.get("shook")),
        "module": entry["module"],
        "mini_game": 0,
    }


def start_replay(battle: dict, viewer_team_id, return_view="arena",
                 return_kwargs=None):
    """Open the battle scene on *battle* (a server battle record).

    Returns None once the scene is switched, or a short message saying why
    the battle cannot be shown.
    """
    viewer_is_attacker = str(battle.get("team1_id")) == str(viewer_team_id)
    try:
        mine, theirs, result, my_hp, their_hp = arena_replay.viewer_side(
            battle.get("battle_log"), viewer_is_attacker)
    except (ValueError, KeyError, TypeError):
        return "This battle has no replay"

    try:
        my_pets = [_local_pet(entry) for entry in mine["pets"]]
    except KeyError as exc:
        return f"Install {exc.args[0]} to watch"
    except Exception as exc:  # pylint: disable=broad-except
        runtime_globals.game_console.log(f"[ArenaReplay] could not rebuild team: {exc}")
        return "Cannot rebuild this team"

    rules = (battle.get("battle_log") or {}).get("rules") or {}
    runtime_globals.pvp_battle_data = {
        "is_host": True,
        "my_pets": my_pets,
        "my_team_data": [],
        "enemy_team_data": [_enemy_data(entry) for entry in theirs["pets"]],
        "simulation_data": {
            "battle_log": result,
            "victory_status": arena_replay.victory_status(result.get("winner")),
        },
        "module": my_pets[0].module,
        "my_player_name": mine.get("nickname") or "YOU",
        "enemy_player_name": theirs.get("nickname") or "RIVAL",
        "is_online_mode": True,
        "arena_replay": {
            "team1_hp": my_hp,
            "team2_hp": their_hp,
            "presentation_format": rules.get("battle_format", "DMX"),
            # The server's attacker acts first in every round.
            "enemy_first": not viewer_is_attacker,
            "return_view": return_view,
            "return_kwargs": return_kwargs or {},
        },
    }
    change_scene("battle_pvp")
    return None
