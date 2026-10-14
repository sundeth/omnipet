"""Showing a stored arena battle from either team's side.

The server stores every battle with the attacker as ``device1``. A battle
scene always draws the player's team as ``device1``, so the defender's view
swaps the two sides. Nothing here touches pygame.
"""

LOG_VERSION = 2

_SWAP = {"device1": "device2", "device2": "device1"}


def swap_sides(result):
    """A serialized ``BattleResult`` with device1 and device2 exchanged."""
    turns = []
    for turn in result.get("battle_log", []):
        turns.append({
            "turn": turn.get("turn"),
            "device1_status": turn.get("device2_status", []),
            "device2_status": turn.get("device1_status", []),
            "attacks": [dict(attack, device=_SWAP.get(attack.get("device"), attack.get("device")))
                        for attack in turn.get("attacks", [])],
        })
    return {
        "winner": _SWAP.get(result.get("winner"), result.get("winner")),
        "device1_final": result.get("device2_final", []),
        "device2_final": result.get("device1_final", []),
        "battle_log": turns,
        "device1_packets": result.get("device2_packets", []),
        "device2_packets": result.get("device1_packets", []),
    }


def victory_status(winner):
    """The scene's verdict for the player drawn as device1."""
    return {"device1": "Victory", "device2": "Defeat"}.get(winner, "Draw")


def viewer_side(battle_log, viewer_is_attacker):
    """(my team, their team, result, my hp, their hp) for one viewer.

    *battle_log* is the server's stored log (``LOG_VERSION``); raises
    ValueError for a log this game cannot replay.
    """
    if not isinstance(battle_log, dict) or battle_log.get("version") != LOG_VERSION:
        raise ValueError("This battle has no replay")
    attacker, defender = battle_log["attacker"], battle_log["defender"]
    result, hp = battle_log["result"], battle_log["hp"]
    if viewer_is_attacker:
        return attacker, defender, result, hp["team1"], hp["team2"]
    return defender, attacker, swap_sides(result), hp["team2"], hp["team1"]
