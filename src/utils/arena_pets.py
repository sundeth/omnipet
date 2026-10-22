"""The player's own pets in Arena Seasons.

- ``pet_uid``: the Digimon's arena identity, made on first use and kept in
  the save; evolution keeps the same pet object, so it survives evolving.
  The server lets one species form fight one season (it may come back once
  it has evolved); ``fought_form`` is the local copy of that rule.
- ``pet_base`` / ``pet_snapshot``: what a team upload carries besides the
  care status -- the species values the game holds (the server refuses them
  when they contradict its own copy of the same module version) and a full
  JSON copy of the pet, which the server keeps with the team.
- ``unseen_defences`` / ``mark_defences_seen``: how many times the team
  was attacked since the player last opened its history (kept in the save
  folder's ``arena_seen.json``).
- ``mark_team`` / ``apply_season_results``: a team's pets remember their
  season while they sit locked in the freezer; when the server reports the
  season finished, the record of their server copies (battles, wins) is
  added to them and the lock is released. ``arena_pending`` survives the
  freezer clearing an expired lock, so a pet taken out early still gets
  its record once the results arrive.

Nothing here touches pygame.
"""
import datetime as _dt
import json
import os
import pickle
import uuid

from core import game_globals

#: Species values sent as ``base`` (battle.arena.engine.BASE_FIELDS).
BASE_FIELDS = ("stage", "attribute", "power", "hp", "atk_main", "atk_alt")

#: Attributes never copied into a pet's JSON upload: sprites and frames are
#: not data, and the monotonic timers mean nothing off the device.
_SKIP = {"frames", "sprite", "sprites", "image", "surface"}
_SKIP_PREFIXES = ("_rt_",)


def pet_uid(pet) -> str:
    """The pet's arena identity (created and kept on the pet when missing)."""
    uid = getattr(pet, "uid", None)
    if not uid:
        uid = uuid.uuid4().hex
        pet.uid = uid
    return uid


def pet_base(pet) -> dict:
    """The species values the game holds for *pet*."""
    from core import pet_stats
    stage = int(getattr(pet, "stage", 0) or 0)
    atk_main = int(getattr(pet, "atk_main", 0) or 0)
    return {
        "stage": stage,
        "attribute": getattr(pet, "attribute", "") or "",
        "power": int(getattr(pet, "power", 0) or 0),
        "hp": int(getattr(pet, "hp", 0) or 0) or pet_stats.HP_LEVEL.get(stage, 0),
        "atk_main": atk_main,
        "atk_alt": int(getattr(pet, "atk_alt", 0) or 0) or atk_main,
    }


def _jsonable(value, depth=0):
    """*value* as JSON data, or a skip marker for what JSON cannot hold."""
    if depth > 6:
        return _SKIPPED
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if value == value and value not in (float("inf"), float("-inf")) else None
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat()
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [_jsonable(v, depth + 1) for v in value]
        return [v for v in items if v is not _SKIPPED]
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            v = _jsonable(v, depth + 1)
            if v is not _SKIPPED:
                out[str(k)] = v
        return out
    return _SKIPPED


_SKIPPED = object()


def pet_snapshot(pet) -> dict:
    """A JSON copy of everything the save holds for *pet* (its pickled
    state minus sprites and device-local timers)."""
    state = pet.__getstate__() if hasattr(pet, "__getstate__") else dict(pet.__dict__)
    if not isinstance(state, dict):
        state = dict(getattr(pet, "__dict__", {}))
    out = {}
    for key, value in state.items():
        if key in _SKIP or key.startswith(_SKIP_PREFIXES):
            continue
        value = _jsonable(value)
        if value is not _SKIPPED:
            out[key] = value
    return out


def fought_form(pet, current_season_id=None):
    """The season *pet* already fought in its current form, or None.

    The game's copy of the server rule: a Digimon fights one season per
    species form (``arena_history`` is written by ``mark_team``).
    """
    name, version = getattr(pet, "name", None), getattr(pet, "version", None)
    for entry in getattr(pet, "arena_history", None) or []:
        if not isinstance(entry, dict):
            continue
        if current_season_id and str(entry.get("season_id")) == str(current_season_id):
            continue
        if entry.get("name") == name and str(entry.get("version")) == str(version):
            return entry.get("season_name") or "a past season"
    return None


def mark_team(pets, team: dict) -> None:
    """Stamp a newly registered team's pets with its season (before they are
    locked in the freezer): the history ``fought_form`` reads and the
    pending result ``apply_season_results`` resolves."""
    team_id = str(team.get("id") or "")
    for pet in pets:
        history = list(getattr(pet, "arena_history", None) or [])
        history.append({
            "season_id": str(team.get("season_id") or ""),
            "season_name": team.get("season_name") or "",
            "team_id": team_id,
            "name": getattr(pet, "name", None),
            "version": getattr(pet, "version", None),
        })
        pet.arena_history = history
        pet.arena_pending = {"team_id": team_id,
                             "season_id": str(team.get("season_id") or ""),
                             "season_name": team.get("season_name") or ""}


def _apply(pet, row: dict, team: dict) -> dict:
    """Add one server copy's record to *pet*; returns what was added."""
    battles = max(0, int(row.get("battles") or 0))
    wins = max(0, int(row.get("wins") or 0))
    # Arena battles are PvP battles (the `pvp` route criterion counts them,
    # won or lost) and count in the pet's lifetime totals.
    pet.pvp_battles = int(getattr(pet, "pvp_battles", 0) or 0) + battles
    pet.pvp_wins = int(getattr(pet, "pvp_wins", 0) or 0) + wins
    pet.totalBattles = int(getattr(pet, "totalBattles", 0) or 0) + battles
    pet.totalWin = int(getattr(pet, "totalWin", 0) or 0) + wins
    team_id = str(team.get("id") or "")
    for entry in getattr(pet, "arena_history", None) or []:
        if isinstance(entry, dict) and entry.get("team_id") == team_id:
            entry.update({
                "battles": battles, "wins": wins,
                "losses": int(row.get("losses") or 0), "draws": int(row.get("draws") or 0),
                "rank": team.get("final_rank") or team.get("rank"),
            })
    pet.arena_pending = None
    pet.arena_lock = None
    return {"name": getattr(pet, "name", "?"), "battles": battles, "wins": wins}


def _match(pets, rows):
    """Pair a team's pets with its server rows: by uid, else in order."""
    pairs, left = [], list(rows)
    for pet in pets:
        uid = getattr(pet, "uid", None)
        row = next((r for r in left if uid and r.get("uid") == uid), None)
        if row is None:
            row = next((r for r in left if r.get("name") == getattr(pet, "name", None)), None)
        if row is not None:
            left.remove(row)
            pairs.append((pet, row))
    return pairs


def _freezer_path():
    return os.path.join(game_globals.get_save_dir(), "freezer.pkl")


def pending_team_ids() -> set:
    """Teams some of the player's pets still wait on results from."""
    ids = set()
    for pet in _all_pets()[0]:
        pending = getattr(pet, "arena_pending", None)
        lock = getattr(pet, "arena_lock", None)
        for marker in (pending, lock):
            if isinstance(marker, dict) and marker.get("team_id"):
                ids.add(str(marker["team_id"]))
    return ids


def _all_pets():
    """(every pet in the party and the freezer, the freezer pages)."""
    pages = []
    path = _freezer_path()
    if os.path.exists(path):
        try:
            with open(path, "rb") as f:
                pages = pickle.load(f) or []
        except Exception:  # pylint: disable=broad-except
            pages = []
    pets = list(game_globals.pet_list or [])
    for page in pages:
        pets.extend(getattr(page, "pets", None) or [])
    return pets, pages


def apply_season_results(teams) -> list:
    """Give finished teams' pets their server record and release them.

    *teams* are server team payloads (``GET /teams/{id}``) of seasons that
    have completed, with their ``pets`` rows. Each of the player's pets
    still pending on one of them gets that row's battles and wins added and
    its lock cleared; a pet is never credited twice (the pending marker is
    cleared with it). Returns [{"name", "battles", "wins"}] for what was
    applied. The party and the freezer are saved when anything changed.
    """
    by_id = {str(t.get("id")): t for t in teams or [] if isinstance(t, dict) and t.get("id")}
    if not by_id:
        return []
    pets, pages = _all_pets()
    applied = []
    party_changed = freezer_changed = False
    party = list(game_globals.pet_list or [])
    for team_id, team in by_id.items():
        waiting = [p for p in pets
                   if str((getattr(p, "arena_pending", None) or {}).get("team_id", "")) == team_id
                   or str((getattr(p, "arena_lock", None) or {}).get("team_id", "")) == team_id]
        if not waiting:
            continue
        rows = team.get("pets") or []
        for pet, row in _match(waiting, rows):
            applied.append(_apply(pet, row, team))
            if any(pet is q for q in party):
                party_changed = True
            else:
                freezer_changed = True
        for pet in waiting:              # no row left for it: release anyway
            if getattr(pet, "arena_pending", None) or getattr(pet, "arena_lock", None):
                pet.arena_pending = None
                pet.arena_lock = None
                freezer_changed = freezer_changed or not any(pet is q for q in party)
                party_changed = party_changed or any(pet is q for q in party)
    if freezer_changed and pages:
        with open(_freezer_path(), "wb") as f:
            pickle.dump(pages, f)
    if party_changed:
        game_globals.save()
    return applied


def upload_size(pet) -> int:
    """Bytes of *pet*'s JSON copy (the server refuses very large ones)."""
    return len(json.dumps(pet_snapshot(pet)))


def _seen_path():
    return os.path.join(game_globals.get_save_dir(), "arena_seen.json")


def _seen():
    try:
        with open(_seen_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def unseen_defences(team: dict) -> int:
    """Defences *team* fought since the player last opened its history."""
    if not isinstance(team, dict) or team.get("defences") is None:
        return 0
    seen = int(_seen().get(str(team.get("id")), 0) or 0)
    return max(0, int(team.get("defences") or 0) - seen)


def mark_defences_seen(team_id, defences) -> None:
    """Remember that the player has seen *defences* defences of *team_id*."""
    if not team_id or defences is None:
        return
    data = _seen()
    data[str(team_id)] = int(defences)
    try:
        os.makedirs(os.path.dirname(_seen_path()), exist_ok=True)
        with open(_seen_path(), "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass
