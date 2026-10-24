"""Headless Arena Season engine.

The Omninet server keeps a copy of Omnipet's source and module data for each
season and runs this module from it, so the rules can only change when a
season rolls over. It is invoked as ``python -m battle.arena`` with one JSON
request on stdin and answers with one JSON object on stdout; see ``handle``.

**Trust model.** A player's upload names a Digimon (module, name, version)
and carries its care status. The species data -- stage, attribute, base
power, base HP, attacks -- always comes from the server's module copy, never
from the upload. The status (level, strength, hunger, weight, effort,
traited/shaken egg, Vital Values) is clamped to what that species can hold
and then run through the same power/HP rules the game uses
(``core.pet_stats``). A module the server does not have is refused. The
upload may also say what the game holds for the species (``base``); when the
game runs the server's own version of the module those values must match,
or the Digimon is refused as edited (a different module version may differ
honestly, and the server's data wins anyway).

**Battle rules.** Arena battles are OMNIPET battles with the DMX default
patterns (the battle contract in CLAUDE.md): ``GlobalBattleSimulator`` on
the DMX table, the DMX module's attribute rule (+32 power), no damage cap,
three against three, and no forced winner -- a battle that ends level is a
draw.
"""
import contextlib
import json
import os
import random
import sys

from core import pet_stats
from battle.sim.global_battle_simulator import GlobalBattleSimulator
from battle.sim.models import Digimon

#: Bumped when the request/response contract with Omninet changes.
ENGINE_VERSION = 1

#: Every arena team fields exactly this many Digimon.
TEAM_SIZE = 3

#: OMNIPET with the DMX defaults. ``charge`` is the 0-3 charge quality each
#: Digimon is credited with, since nobody plays the minigame in an
#: asynchronous battle; a season may set it to another band or "random".
ARENA_RULES = {
    "battle_format": "DMX",
    "attribute_advantage": 32,
    "advantage_as_power": True,
    "damage_limit": 99,
    "max_hit_rate": 100,
    "charge": 2,
}

#: The rule keys a season's configuration may override.
SEASON_RULE_KEYS = ("charge",)

ATTRIBUTE_NAMES = {"Va": "Vaccine", "Da": "Data", "Vi": "Virus", "": "Free"}
_ATTRIBUTE_ALIASES = {
    "va": "Va", "vaccine": "Va",
    "da": "Da", "data": "Da",
    "vi": "Vi", "virus": "Vi",
    "": "", "fr": "", "free": "", "none": "",
}

#: Care-status fields an upload may carry, and nothing else.
STATUS_FIELDS = ("level", "strength", "hunger", "weight", "effort",
                 "traited", "shook", "vital_values", "sick")

#: Effort is a training count; nothing reads past a few full meters.
MAX_EFFORT = 99
MAX_WEIGHT = 99

#: Species values an upload's ``base`` is checked against (``check_base``):
#: the ones that decide a battle or a season's restrictions. Attack ids only
#: choose the art a replay draws (arena battles take their patterns from
#: stage, level and charge), and a module may change them without a new
#: version, so they are not checked.
BASE_FIELDS = ("stage", "attribute", "power", "hp")


class ArenaError(Exception):
    """A request the engine refuses, with a stable machine-readable code."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def normalize_attribute(value):
    """A monster.json or restriction attribute as Va/Da/Vi, or "" for Free.

    monster.json stores the two-letter codes and "" for Free; a season
    restriction may be written either way.
    """
    key = str(value if value is not None else "").strip().lower()
    if key not in _ATTRIBUTE_ALIASES:
        raise ArenaError("bad_attribute", "Unknown attribute %r" % (value,))
    return _ATTRIBUTE_ALIASES[key]


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clamp(value, low, high):
    return max(low, min(high, value))


# ---------------------------------------------------------------------------
# Module catalog
# ---------------------------------------------------------------------------

class Catalog:
    """The module data under one runtime's ``modules`` folder.

    Modules are keyed by the ``name`` in their module.json, which is what a
    pet records as its module. Only JSON is read; nothing a module ships is
    ever executed.
    """

    def __init__(self, modules_dir):
        self.modules_dir = modules_dir
        self._modules = None

    def _load(self):
        if self._modules is not None:
            return self._modules
        modules = {}
        if os.path.isdir(self.modules_dir):
            for folder in sorted(os.listdir(self.modules_dir)):
                path = os.path.join(self.modules_dir, folder)
                module = _load_module(path)
                if module and module["name"] not in modules:
                    modules[module["name"]] = module
        self._modules = modules
        return modules

    def names(self):
        return sorted(self._load())

    def module(self, name):
        return self._load().get(name)

    def summary(self):
        return [{"name": m["name"], "version": m["version"],
                 "monsters": len(m["monsters"])}
                for m in (self._load()[n] for n in self.names())]


def _load_module(path):
    module_json = os.path.join(path, "module.json")
    monster_json = os.path.join(path, "monster.json")
    if not (os.path.isfile(module_json) and os.path.isfile(monster_json)):
        return None
    try:
        with open(module_json, encoding="utf-8") as f:
            meta = json.load(f)
        with open(monster_json, encoding="utf-8") as f:
            roster = json.load(f)
    except (OSError, ValueError):
        return None
    monsters = {}
    for entry in roster.get("monster", []) if isinstance(roster, dict) else []:
        key = (entry.get("name"), _int(entry.get("version"), None))
        # First match wins, as GameModule.get_monster reads it.
        monsters.setdefault(key, entry)
    return {
        "name": meta.get("name") or os.path.basename(path),
        "version": str(meta.get("version", "1.0")),
        "power_bonus_rule": pet_stats.resolve_power_bonus_rule(meta),
        "effort_power_tiers": meta.get("effort_power_tiers") or [],
        "visible_stats": pet_stats.parse_visible_stats(meta.get("visible_stats", "")),
        "strength_max": max(0, _int(meta.get("care_strength_max"), 0)),
        "monsters": monsters,
    }


# ---------------------------------------------------------------------------
# Building a battle entry from an upload
# ---------------------------------------------------------------------------

def clamp_status(monster, status, strength_max=0):
    """The upload's care status, restricted to what *monster* can hold.
    *strength_max* is its module's ``care_strength_max`` (0: the stomach)."""
    status = status if isinstance(status, dict) else {}
    stage = _int(monster.get("stage"), 0)
    stomach = max(0, _int(monster.get("stomach"), 4))
    min_weight = max(0, _int(monster.get("min_weight"), 0))
    max_level = max(1, pet_stats.MAX_LEVEL.get(stage, 10))
    return {
        "level": _clamp(_int(status.get("level"), 1), 1, max_level),
        "strength": _clamp(_int(status.get("strength"), 0), 0,
                           pet_stats.strength_cap(strength_max, stomach)),
        "hunger": _clamp(_int(status.get("hunger"), 0), 0, stomach),
        "weight": _clamp(_int(status.get("weight"), min_weight), min_weight,
                         max(min_weight, MAX_WEIGHT)),
        "effort": _clamp(_int(status.get("effort"), 0), 0, MAX_EFFORT),
        "traited": bool(status.get("traited")),
        "shook": bool(status.get("shook")),
        "vital_values": _clamp(_int(status.get("vital_values"), 0), 0,
                               pet_stats.vital_value_cap(stage)),
        "sick": bool(status.get("sick")),
    }


def build_entry(catalog, upload):
    """One uploaded Digimon as the server will fight it.

    Raises ArenaError when the module is not on the server, the species is
    unknown, the pet is flagged edited or dead, or it cannot battle.
    """
    if not isinstance(upload, dict):
        raise ArenaError("bad_upload", "Each pet must be an object")
    module_name = str(upload.get("module_name") or upload.get("module") or "")
    module = catalog.module(module_name)
    if module is None:
        raise ArenaError("module_unavailable",
                         "%s is not available in this arena season" % (module_name or "?"))
    name = str(upload.get("name") or "")
    version = _int(upload.get("pet_version", upload.get("version")), None)
    monster = module["monsters"].get((name, version))
    if monster is None:
        raise ArenaError("unknown_digimon",
                         "%s (version %s) is not in %s" % (name or "?", version, module_name))
    status = upload.get("status") if isinstance(upload.get("status"), dict) else {}
    if status.get("edited"):
        raise ArenaError("edited", "%s has been edited" % name)
    if status.get("state") == "dead":
        raise ArenaError("dead", "%s is dead" % name)

    stage = _int(monster.get("stage"), 0)
    clamped = clamp_status(monster, status, module.get("strength_max", 0))
    base_power = _int(monster.get("power"), 0)
    base_hp = _int(monster.get("hp"), 0) or pet_stats.HP_LEVEL.get(stage, 0)
    power = pet_stats.power_with_bonus_rule(
        module["power_bonus_rule"], base_power, stage=stage,
        strength=clamped["strength"], stomach=_int(monster.get("stomach"), 0),
        hunger=clamped["hunger"], weight=clamped["weight"],
        level=clamped["level"], version=version, effort=clamped["effort"],
        traited=clamped["traited"], shook=clamped["shook"],
        star=_int(monster.get("star"), 0),
        effort_tiers=module.get("effort_power_tiers"),
        strength_max=module.get("strength_max", 0))
    vital_cap = (pet_stats.vital_value_cap(stage)
                 if pet_stats.tracks_vital_values(module["visible_stats"]) else 0)
    hp = pet_stats.hp_with_bonuses(base_hp, level=clamped["level"],
                                   vital_values=clamped["vital_values"],
                                   vital_cap=vital_cap)
    atk_main = _int(monster.get("atk_main"), 0)
    atk_alt = _int(monster.get("atk_alt"), 0) or atk_main
    if power <= 0 or hp <= 0 or atk_main <= 0:
        raise ArenaError("cannot_battle", "%s cannot battle" % name)
    check_base(upload, module, {
        "stage": stage, "attribute": normalize_attribute(monster.get("attribute")),
        "power": base_power, "hp": base_hp, "atk_main": atk_main, "atk_alt": atk_alt})

    return {
        "module": module_name,
        "module_version": module["version"],
        "name": name,
        "version": version,
        "index": monster.get("index"),
        "stage": stage,
        "attribute": normalize_attribute(monster.get("attribute")),
        "level": clamped["level"],
        "power": int(power),
        "hp": int(hp),
        "atk_main": atk_main,
        "atk_alt": atk_alt,
        "atk_alt_2": _int(monster.get("atk_alt_2"), 0),
        "traited": clamped["traited"],
        "shook": clamped["shook"],
        "effort": clamped["effort"],
        "status": clamped,
    }


def check_base(upload, module, server):
    """Refuse an upload whose ``base`` contradicts the server's species data.

    Only when the upload says it comes from the module version the server
    holds: another version may honestly differ (the server's data is used
    either way). Raises ArenaError ``stats_mismatch``.
    """
    claimed = upload.get("base")
    if not isinstance(claimed, dict) or not claimed:
        return
    if str(upload.get("module_version") or "") != str(module["version"]):
        return
    for field in BASE_FIELDS:
        if field not in claimed:
            continue
        value = claimed[field]
        if field == "attribute":
            try:
                value = normalize_attribute(value)
            except ArenaError:
                value = None
        elif field == "hp":
            value = _int(value, 0) or pet_stats.HP_LEVEL.get(server["stage"], 0)
        else:
            value = _int(value, None)
        if value != server[field]:
            raise ArenaError(
                "stats_mismatch",
                "%s does not match the server's %s data (%s)"
                % (upload.get("name") or "?", module["name"], field))


def restriction_error(entry, restrictions):
    """Why *entry* breaks the season *restrictions*, or None."""
    restrictions = restrictions or {}
    stages = restrictions.get("allowed_stages")
    if stages and entry["stage"] not in {_int(s, -1) for s in stages}:
        return "Stage %s is not allowed this season" % entry["stage"]
    attributes = restrictions.get("allowed_attributes")
    if attributes:
        allowed = {normalize_attribute(a) for a in attributes}
        if entry["attribute"] not in allowed:
            return "%s is not allowed this season" % ATTRIBUTE_NAMES[entry["attribute"]]
    modules = restrictions.get("allowed_modules")
    if modules and entry["module"] not in set(modules):
        return "%s is not allowed this season" % entry["module"]
    return None


def validate_team(catalog, uploads, restrictions=None, team_size=TEAM_SIZE,
                  min_size=None, max_size=None):
    """Build every entry of a team; returns (entries, errors).

    The team holds exactly *team_size* Digimon, or, when *min_size* /
    *max_size* are given, any number in that range.
    """
    if min_size is not None or max_size is not None:
        low = _int(min_size, 1) if min_size is not None else 1
        high = _int(max_size, TEAM_SIZE) if max_size is not None else TEAM_SIZE
        if not isinstance(uploads, list) or not low <= len(uploads) <= high:
            raise ArenaError("team_size", (
                "A team must have exactly %d Digimon" % low if low == high
                else "A team must have %d to %d Digimon" % (low, high)))
    elif not isinstance(uploads, list) or len(uploads) != team_size:
        raise ArenaError("team_size", "A team must have exactly %d Digimon" % team_size)
    entries, errors = [], []
    for i, upload in enumerate(uploads):
        try:
            entry = build_entry(catalog, upload)
        except ArenaError as exc:
            errors.append({"index": i, "code": exc.code, "message": str(exc)})
            continue
        problem = restriction_error(entry, restrictions)
        if problem:
            errors.append({"index": i, "code": "restricted", "message": problem})
            continue
        entries.append(entry)
    return entries, errors


# ---------------------------------------------------------------------------
# Battle
# ---------------------------------------------------------------------------

def effective_rules(overrides=None):
    rules = dict(ARENA_RULES)
    for key in SEASON_RULE_KEYS:
        if overrides and key in overrides and overrides[key] is not None:
            rules[key] = overrides[key]
    return rules


def _charge_for(rules, rng):
    charge = rules.get("charge", ARENA_RULES["charge"])
    if charge == "random":
        return rng.randint(0, 3)
    return _clamp(_int(charge, ARENA_RULES["charge"]), 0, 3)


def _to_digimon(entry, order, charge):
    digimon = Digimon(
        name=entry["name"], order=order,
        traited=1 if entry.get("traited") else 0,
        egg_shake=1 if entry.get("shook") else 0,
        index=order, hp=int(entry["hp"]), attribute=entry["attribute"],
        power=int(entry["power"]), handicap=0, buff=0, mini_game=charge,
        level=int(entry["level"]), stage=int(entry["stage"]), sick=0,
        shot1=entry["atk_main"], shot2=entry["atk_alt"], tag_meter=0)
    digimon.effort = entry.get("effort", 0)
    return digimon


def run_battle(team1, team2, seed, rules=None):
    """Fight *team1* (the attacker) against *team2*; deterministic per seed.

    The simulator draws from the global ``random`` module, so the engine
    seeds it -- this runs in its own process on the server.
    """
    rules = effective_rules(rules)
    rng = random.Random(seed)
    charges1 = [_charge_for(rules, rng) for _ in team1]
    charges2 = [_charge_for(rules, rng) for _ in team2]
    random.seed(seed)
    sim = GlobalBattleSimulator(
        attribute_advantage=rules["attribute_advantage"],
        damage_limit=rules["damage_limit"],
        force_winner=False,
        pvp_mode=True,
        advantage_as_power=rules["advantage_as_power"],
        battle_format=rules["battle_format"],
        max_hit_rate=rules["max_hit_rate"])
    result = sim.simulate(
        [_to_digimon(e, i, c) for i, (e, c) in enumerate(zip(team1, charges1))],
        [_to_digimon(e, i, c) for i, (e, c) in enumerate(zip(team2, charges2))])
    return {
        "winner": result.winner,
        "result": result.to_dict(),
        "hp": {"team1": [int(e["hp"]) for e in team1],
               "team2": [int(e["hp"]) for e in team2]},
        "charges": {"team1": charges1, "team2": charges2},
        "rules": rules,
        "seed": seed,
        "engine_version": ENGINE_VERSION,
    }


# ---------------------------------------------------------------------------
# Development helpers
# ---------------------------------------------------------------------------

def random_team(catalog, seed, restrictions=None, team_size=TEAM_SIZE, modules=None):
    """Uploads for a plausible random team, for development dummy players.

    Picks battle-capable species that pass *restrictions* and gives each a
    random but legal care status; the result goes through ``validate_team``
    like any player's upload.
    """
    rng = random.Random(seed)
    candidates = []
    for module_name in catalog.names():
        if modules and module_name not in modules:
            continue
        for (name, version), monster in catalog.module(module_name)["monsters"].items():
            if name is None or version is None:
                continue
            upload = {"module_name": module_name, "name": name, "pet_version": version}
            try:
                entry = build_entry(catalog, upload)
            except ArenaError:
                continue
            if restriction_error(entry, restrictions):
                continue
            candidates.append((module_name, name, version, monster))
    if not candidates:
        raise ArenaError("no_candidates", "No Digimon on the server fit these restrictions")
    team = []
    for _ in range(team_size):
        module_name, name, version, monster = rng.choice(candidates)
        stage = _int(monster.get("stage"), 0)
        stomach = max(0, _int(monster.get("stomach"), 4))
        min_weight = _int(monster.get("min_weight"), 0)
        team.append({
            "module_name": module_name, "name": name, "pet_version": version,
            "status": {
                "level": rng.randint(1, max(1, pet_stats.MAX_LEVEL.get(stage, 1))),
                "strength": rng.randint(0, stomach),
                "hunger": rng.randint(min(1, stomach), stomach),
                "weight": rng.randint(min_weight, min(MAX_WEIGHT, min_weight + 20)),
                "effort": rng.randint(0, 20),
                "traited": rng.random() < 0.1,
                "shook": rng.random() < 0.1,
                "vital_values": rng.randint(0, pet_stats.vital_value_cap(stage)),
            },
        })
    return team


# ---------------------------------------------------------------------------
# Request handling
# ---------------------------------------------------------------------------

def handle(request):
    """Answer one request dict. Commands:

    ``info``           engine version and default rules
    ``catalog``        modules (name, version, roster size) on this runtime
    ``validate_team``  ``pets`` + ``restrictions`` -> ``entries`` / ``errors``
    ``battle``         ``team1`` / ``team2`` entries, ``seed``, ``rules``
    ``random_team``    ``seed`` + ``restrictions`` -> ``pets`` (uploads)

    Every request but ``info`` names ``modules_dir``.
    """
    command = request.get("command")
    if command == "info":
        return {"ok": True, "engine_version": ENGINE_VERSION,
                "rules": ARENA_RULES, "team_size": TEAM_SIZE}
    catalog = Catalog(request.get("modules_dir") or "modules")
    if command == "catalog":
        return {"ok": True, "engine_version": ENGINE_VERSION,
                "modules": catalog.summary()}
    if command == "validate_team":
        entries, errors = validate_team(
            catalog, request.get("pets"), request.get("restrictions"),
            _int(request.get("team_size"), TEAM_SIZE),
            request.get("min_team_size"), request.get("max_team_size"))
        return {"ok": not errors, "entries": entries, "errors": errors}
    if command == "battle":
        outcome = run_battle(request.get("team1") or [], request.get("team2") or [],
                             _int(request.get("seed"), 0), request.get("rules"))
        return dict(outcome, ok=True)
    if command == "random_team":
        pets = random_team(catalog, _int(request.get("seed"), 0),
                           request.get("restrictions"),
                           _int(request.get("team_size"), TEAM_SIZE),
                           request.get("modules"))
        return {"ok": True, "pets": pets}
    raise ArenaError("bad_command", "Unknown command %r" % (command,))


def main():
    """JSON in on stdin, JSON out on stdout; diagnostics go to stderr."""
    real_stdout = sys.stdout
    try:
        with contextlib.redirect_stdout(sys.stderr):
            request = json.loads(sys.stdin.read() or "{}")
            response = handle(request)
    except ArenaError as exc:
        response = {"ok": False, "error": exc.code, "message": str(exc)}
    except Exception as exc:  # pylint: disable=broad-except
        response = {"ok": False, "error": "engine_failure", "message": repr(exc)}
    real_stdout.write(json.dumps(response))
    real_stdout.flush()
