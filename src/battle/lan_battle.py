"""WiFi battles: two Omnipets on one local network.

The battle contract (CLAUDE.md) makes a WiFi battle an OMNIPET battle with
the DMX default patterns, which is what an Arena Season fights. So it is
fought by the same engine (``battle.arena.engine.run_battle`` with its
``ARENA_RULES``: DMX table, +32 attribute advantage as power, no forced
winner, every Digimon at the default charge), stored in the same log and
played back the same way. The host is the attacker (team1) and fights the
battle once both players have pressed START, then sends the log; each game
plays it from its own seat, the joining one with the sides swapped and the
host shooting first, as an arena defender sees a battle
(``battle.arena.replay``). Unlike an arena replay the real pets fight, so
the battle counts like any other connection battle: battles and wins, the
PvP counts, the battle cost, Connect Points.

Each game describes its own team (``team_entry``): the species values it
holds and the power and HP its pets fight with now. A peer's description is
only bounded (``clean_team``), never refused for its values: the two
players are in the same room, and the opponent's module need not be
installed here.

Messages on the link (``battle.lan_link``)::

    hello   {"type": "hello", "protocol", "game", "name", "team": [entry, ...]}
    ready   {"type": "ready"}                        START pressed
    battle  {"type": "battle", "log": {...}}         host -> joining game
    bye     {"type": "bye"}                          cancelled

Nothing here touches pygame.
"""
import random

from battle.arena import engine
from battle.arena import replay

#: Bumped when a message or the log changes; a peer on another one is
#: refused ("Different game version").
PROTOCOL = 1

#: A team is the party's pets that can battle (the party holds up to four).
MAX_TEAM = 4

_MAX_TEXT = 40


def _text(value):
    return str(value if value is not None else "")[:_MAX_TEXT].strip()


def _bounded(value, low, high, default=None):
    try:
        number = int(value)
    except (TypeError, ValueError):
        if default is None:
            raise ValueError("not a number: %r" % (value,))
        number = default
    return max(low, min(high, number))


def _attribute(value):
    try:
        return engine.normalize_attribute(value)
    except engine.ArenaError:
        return ""


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------

def team_entry(pet):
    """What a game tells its opponent about one of its pets: who it is and
    what it fights with now (power and HP with every bonus it has)."""
    stage = int(getattr(pet, "stage", 0) or 0)
    atk_main = int(getattr(pet, "atk_main", 0) or 0)
    version = getattr(pet, "version", 1)
    return {
        "module": getattr(pet, "module", ""),
        "name": getattr(pet, "name", ""),
        # Version 0 is a real version (PENC's Agumon): never `or 1`.
        "version": int(version) if version is not None else 1,
        "stage": stage,
        "attribute": _attribute(getattr(pet, "attribute", "")),
        "level": int(getattr(pet, "level", 1) or 1),
        "power": int(pet.get_power()),
        "hp": int(pet.get_hp()),
        "atk_main": atk_main,
        "atk_alt": int(getattr(pet, "atk_alt", 0) or 0) or atk_main,
        "atk_alt_2": int(getattr(pet, "atk_alt_2", 0) or 0),
        "traited": bool(getattr(pet, "traited", False)),
        "shook": bool(getattr(pet, "shook", False)),
        "effort": int(getattr(pet, "effort", 0) or 0),
    }


def clean_entry(raw):
    """A peer's entry with every value bounded; ValueError when it does not
    describe a Digimon that can fight."""
    if not isinstance(raw, dict):
        raise ValueError("not a Digimon")
    name, module = _text(raw.get("name")), _text(raw.get("module"))
    if not name or not module:
        raise ValueError("a Digimon needs a name and a module")
    atk_main = _bounded(raw.get("atk_main"), 0, 9999)
    if atk_main <= 0:
        raise ValueError("%s has no attack" % name)
    return {
        "module": module,
        "name": name,
        "version": _bounded(raw.get("version"), 0, 999, default=1),
        "stage": _bounded(raw.get("stage"), 0, 9),
        "attribute": _attribute(raw.get("attribute")),
        "level": _bounded(raw.get("level"), 1, 99, default=1),
        "power": _bounded(raw.get("power"), 1, 9999),
        "hp": _bounded(raw.get("hp"), 1, 999),
        "atk_main": atk_main,
        "atk_alt": _bounded(raw.get("atk_alt"), 0, 9999, default=0) or atk_main,
        "atk_alt_2": _bounded(raw.get("atk_alt_2"), 0, 9999, default=0),
        "traited": bool(raw.get("traited")),
        "shook": bool(raw.get("shook")),
        "effort": _bounded(raw.get("effort"), 0, engine.MAX_EFFORT, default=0),
    }


def clean_team(raw):
    """A peer's team, each entry bounded; ValueError when it is no team."""
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_TEAM:
        raise ValueError("a team has 1 to %d Digimon" % MAX_TEAM)
    return [clean_entry(entry) for entry in raw]


# ---------------------------------------------------------------------------
# The battle
# ---------------------------------------------------------------------------

def fight(host_team, joined_team, seed, host_name="", joined_name=""):
    """The host's team (the attacker) against the joining game's: the log
    both games play, in the arena's stored form (``replay.LOG_VERSION``).

    The engine seeds the global ``random`` for its simulator; the game's own
    sequence is put back afterwards.
    """
    state = random.getstate()
    try:
        outcome = engine.run_battle(host_team, joined_team, seed)
    finally:
        random.setstate(state)
    return {
        "version": replay.LOG_VERSION,
        "rules": outcome["rules"],
        "hp": outcome["hp"],
        "result": outcome["result"],
        "seed": seed,
        "attacker": {"nickname": host_name, "pets": list(host_team)},
        "defender": {"nickname": joined_name, "pets": list(joined_team)},
    }


def pvp_battle_data(log, my_pets, is_host, online=False):
    """``runtime_globals.pvp_battle_data`` for this game's seat: its real
    pets as team1, the opponent's entries as the enemies. *online* (a
    Discord battle) puts the players' names on the versus screen."""
    from utils.arena_replay import enemy_data
    mine, theirs, result, my_hp, their_hp = replay.viewer_side(log, is_host)
    if len(mine["pets"]) != len(my_pets):
        raise ValueError("the battle is not this team's")
    rules = log.get("rules") or {}
    return {
        # The scene draws its own player as team1 on both games; "host"
        # only picks that layout here.
        "is_host": True,
        "my_pets": list(my_pets),
        "my_team_data": [],
        "enemy_team_data": [enemy_data(entry) for entry in theirs["pets"]],
        "simulation_data": {
            "battle_log": result,
            "victory_status": replay.victory_status(result.get("winner")),
        },
        "module": my_pets[0].module,
        "my_player_name": mine.get("nickname") or "YOU",
        "enemy_player_name": theirs.get("nickname") or "RIVAL",
        "is_online_mode": online,
        "lan_battle": {
            "team1_hp": my_hp,
            "team2_hp": their_hp,
            "presentation_format": rules.get("battle_format", "DMX"),
            # The host is the attacker and shoots first every round.
            "enemy_first": not is_host,
        },
    }


# ---------------------------------------------------------------------------
# The handshake
# ---------------------------------------------------------------------------

class Session:
    """One WiFi battle over an open link, stepped once a frame (``update``).

    Both games say hello with their team; each player presses START
    (``press_start``); the host then fights and sends the log. ``state`` is
    "hello" (no opponent yet), "confirm" (START not pressed), "waiting"
    (pressed, the opponent has not), "battle" (``log`` is ready) or
    "closed" (``error`` says why).
    """

    def __init__(self, link, is_host, pets, name="", game=""):
        self.link = link
        self.is_host = is_host
        self.pets = list(pets)
        self.name = name
        self.team = [team_entry(pet) for pet in self.pets]
        self.opponent = None
        self.ready = False
        self.opponent_ready = False
        self.log = None
        self.error = None
        link.send({"type": "hello", "protocol": PROTOCOL, "game": game,
                   "name": name, "team": self.team})

    @property
    def state(self):
        if self.log is not None:
            return "battle"
        if self.error:
            return "closed"
        if self.opponent is None:
            return "hello"
        return "waiting" if self.ready else "confirm"

    def press_start(self):
        """This player is ready; False when there is no opponent yet."""
        if self.opponent is None or self.error or self.ready:
            return False
        self.ready = True
        self.link.send({"type": "ready"})
        return True

    def cancel(self):
        if not self.link.closed:
            self.link.send({"type": "bye"})
        self.link.close()
        if self.log is None and not self.error:
            self.error = "Cancelled"

    def close(self):
        self.link.close()

    def update(self):
        for message in self.link.poll():
            self._receive(message)
        if (self.is_host and self.ready and self.opponent_ready
                and self.log is None and not self.error):
            self._fight()
        if self.link.closed and self.log is None and not self.error:
            self.error = "The opponent left"
        return self.state

    def _receive(self, message):
        kind = message.get("type")
        if kind == "hello":
            if message.get("protocol") != PROTOCOL:
                self._refuse("Different game version")
                return
            try:
                team = clean_team(message.get("team"))
            except ValueError:
                self._refuse("Their team cannot battle")
                return
            self.opponent = {"name": _text(message.get("name")),
                             "game": _text(message.get("game")), "team": team}
        elif kind == "ready":
            self.opponent_ready = True
        elif kind == "battle" and not self.is_host and self.ready:
            log = message.get("log")
            try:
                replay.viewer_side(log, False)
                if len(log["defender"]["pets"]) != len(self.team):
                    raise ValueError("not this team's battle")
            except (ValueError, KeyError, TypeError):
                self._refuse("Battle could not be read")
                return
            self.log = log
        elif kind == "bye" and self.log is None:
            self.error = "The opponent left"
            self.link.close()

    def _refuse(self, reason):
        self.error = reason
        self.link.send({"type": "bye"})
        self.link.close()

    def _fight(self):
        seed = random.SystemRandom().randrange(1 << 31)
        log = fight(self.team, self.opponent["team"], seed,
                    host_name=self.name, joined_name=self.opponent["name"])
        if not self.link.send({"type": "battle", "log": log}):
            self.error = "The opponent left"
            return
        self.log = log
