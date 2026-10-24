"""
Module events (events.json): what triggers them and what they do.

An event has a **trigger** and a **type** (models.quest_event_data.EventData):

    trigger      when it is considered
    -----------  ---------------------------------------------------------
    random       the hourly XAI roll (models.event_clock); ``chance_percent``
                 is a weight among the module's random events
    adventure    after an adventure battle   } ``chance_percent`` is a chance
    area_clear   after an adventure area     }  in 100, rolled for each event
    connection   after a battle with another } in turn; ``outcome`` win, loss
                 device or pet               }  or any
    schedule     at the times of the pet's ``encounter_time_group`` in the
                 module's ``schedule`` (the Godzilla devices)

    type                 what it does
    -------------------  -------------------------------------------------
    0 special encounter  the battle.json special encounter at area/round
    1 item               ``item`` x ``item_quantity``
    2 Friend battle      one of the Friends a party pet still needs
    3 pooled encounter   a special encounter from ``pools``, the pool chosen
                         by the pet's ``pool_field`` (a monster field), each
                         pool a rotation: the pet's next slot each time
                         (an empty slot is a time without an encounter)
    4 battle run         every special-encounter round of ``area`` in turn;
                         ``item`` after ``reward_round`` (0: the last). The
                         area must hold special encounters only: an area the
                         adventure plays is refused, and special-only areas
                         never appear in the adventure (GameModule.area_exists)
    5 shop access        opens shop.json's ``shop`` (marked ``event_only``)
                         for ``access_minutes`` (0: for good), at once; -1
                         (ONE_VISIT) is one visit: the pending event, the
                         shop entered when it is accepted and gone once left
    6 card battle        the Vital Bracelet's random battle: a monster of the
                         pet's own version by its ``encounter_chances``; a
                         win pays the next of ``item_sequence`` and Vital
                         Values move by the stages (utils.card_battle)

``until_friend`` ends a special encounter event once its Digimon is a Friend
of the module (Digimon World's recruits: met until recruited).
``versions`` keeps an event to pets of those versions; ``trigger_areas`` keeps
an adventure or area_clear event to battles in those adventure areas (the
area fought in, or the area just cleared); a connection event may
name the ``opponent_device_version`` it needs (combat_constants.
ANY_OTHER_DEVICE: any device but the pet's own) and the ``protocol``, the
battle format it is fought on (device numbers repeat across formats).
Battle-triggered events sharing a ``draw`` are a single roll: at most one of
those fitting the battle happens, each taking its ``chance_percent`` of the
hundred in turn.

A battle-triggered event of type 1-4 becomes the pending event the main game
offers (the alert), unless one is pending already. A Friend battle with
``delay_minutes`` is promised for that many minutes later, as an area clear
always did (utils.xros_utils.promise_friend_event).

The pooled encounters' rotation is the pet's ``encounter_rotation``; it
advances at every scheduled time and every training entry (the Godzilla
devices' rule; `advance_rotation`).

Everything a pending event needs is resolved here from plain data, so the
Android offline replay (services.android_offline) uses the same code.
"""

import random
import time

from core import game_globals, runtime_globals

TRIGGERS = ("random", "adventure", "area_clear", "connection", "schedule")

#: A shop event's ``access_minutes`` for one visit: offered as the pending
#: event, opened when accepted, closed as the player leaves it.
ONE_VISIT = -1
OUTCOMES = ("win", "loss", "any")


def _log(text):
    console = getattr(runtime_globals, "game_console", None)
    if console is not None:
        console.log(text)


# Pets ---------------------------------------------------------------------------

#: (module, module version, name, version, field) -> value read from monster.json.
#: The scheduled-encounter check asks every awake pet every minute; reading the
#: record each time re-parsed monster.json (a 7-day Android catch-up spent
#: minutes on it). A module update changes its version, which retires the entry.
_RECORD_FIELDS = {}


def _monster_field(pet, module, field):
    """*pet*'s monster.json *field*: its own attribute, else its record's (a pet
    saved before the field existed has not read it yet)."""
    value = getattr(pet, field, None)
    if value is not None:
        return value
    if module is None:
        return None
    key = (getattr(module, "name", None), getattr(module, "version", None),
           getattr(pet, "name", None), getattr(pet, "version", None), field)
    if key not in _RECORD_FIELDS:
        try:
            record = module.get_monster(pet.name, pet.version)
        except Exception:
            record = None
        _RECORD_FIELDS[key] = (record or {}).get(field)
    return _RECORD_FIELDS[key]


def _for_pet(data, pet) -> bool:
    versions = data.versions or []
    return not versions or getattr(pet, "version", None) in versions


def _awake(pet) -> bool:
    return (getattr(pet, "state", "") not in ("dead", "nap", "dying")
            and int(getattr(pet, "stage", 0) or 0) > 0)


def advance_rotation(pets):
    """A training entry moves each pet's pooled-encounter rotation on one
    slot, as on the Godzilla devices."""
    for pet in pets or []:
        pet.encounter_rotation = int(getattr(pet, "encounter_rotation", 0) or 0) + 1


# Resolving an event ---------------------------------------------------------------

def _special_encounters(module):
    import os
    return [e for e in module._parse_battle_json(os.path.join(module.folder_path, "battle.json"))
            if e.get("special_encounter")]


def _battle(data, module_name, name, area, round_):
    from models.game_event import EventType, GameEvent
    return GameEvent(data.id, name, module_name, data.global_event, EventType.ENEMY_BATTLE,
                     data.chance_percent, area, round_)


def _pool_slot(data, module, pet):
    """The name in *pet*'s next pool slot ("" for none), the rotation moved
    on past it."""
    group = _monster_field(pet, module, data.pool_field) if data.pool_field else None
    pool = (data.pools or {}).get(str(group)) if group is not None else None
    if not pool:
        return ""
    index = int(getattr(pet, "encounter_rotation", 0) or 0)
    pet.encounter_rotation = index + 1
    return str(pool[index % len(pool)] or "")


def _friend_battle(data, module_name, module, pets, friends, rng):
    """A battle with a Friend a pet of the module still needs: (pet, name,
    encounter) or None."""
    from utils.data_compat import availability
    known = set((friends or {}).get(module_name, []))
    choices = []
    for pet in pets:
        if getattr(pet, "module", None) != module_name or not _for_pet(data, pet) or not _awake(pet):
            continue
        for evo in getattr(pet, "temp_evolve", None) or []:
            for name in evo.get("friend") or []:
                if name in known:
                    continue
                encounter = next((e for e in module.get_friend_encounters() if e.get("name") == name), None)
                if encounter and (pet, name, encounter) not in choices:
                    choices.append((pet, name, encounter))
    if not choices:
        return None
    pet, name, encounter = rng.choice(choices)
    # Friends are matched by availability; the record must still be one.
    if not any(m.get("name") == name and availability(m) == "Friend" for m in module.get_all_monsters()):
        return None
    return pet, name, encounter


def resolve(module_name, module, data, pets, rng=random, friends=None, pet=None):
    """The GameEvent *data* comes to now, or None (nothing to offer: a pooled
    slot left empty, no Friend missing, no such encounter). *pet* is the pet
    a scheduled event is for."""
    from models.game_event import EventType, GameEvent
    kind = int(data.type or 0)
    # An item pool pays one of its items at random, drawn as the event happens.
    pool = getattr(data, "item_pool", None)
    item = rng.choice(pool) if pool else data.item
    if kind == EventType.ITEM_PACKAGE.value:
        return GameEvent(data.id, data.name, module_name, data.global_event, EventType.ITEM_PACKAGE,
                         data.chance_percent, data.area, data.round, item, data.item_quantity)
    if kind == EventType.SHOP_ACCESS.value:
        return GameEvent(data.id, data.name, module_name, data.global_event, EventType.SHOP_ACCESS,
                         data.chance_percent, data.area, data.round, shop=data.shop,
                         access_minutes=data.access_minutes)
    if kind == EventType.BATTLE_RUN.value:
        # A run's area is its own: one the adventure also plays would mix the
        # two, so it is refused (the editor's report flags it too).
        area_exists = getattr(module, "area_exists", None)
        if area_exists is not None and area_exists(int(data.area)):
            _log(f"[Events] {data.name}: area {data.area} is an adventure area; a battle run needs its own")
            return None
        rounds = sorted({int(e.get("round", 1)) for e in _special_encounters(module)
                         if int(e.get("area", -1)) == int(data.area)})
        if not rounds:
            _log(f"[Events] {data.name}: area {data.area} has no special encounters")
            return None
        return GameEvent(data.id, data.name, module_name, data.global_event, EventType.BATTLE_RUN,
                         data.chance_percent, data.area, rounds[0], item, data.item_quantity,
                         reward_round=data.reward_round)
    if kind == EventType.CARD_BATTLE.value:
        from utils import card_battle
        pet = pet or next((p for p in pets if getattr(p, "module", None) == module_name
                           and _for_pet(data, p) and card_battle.can_battle(p)), None)
        if pet is None or not card_battle.can_battle(pet):
            return None
        record = card_battle.pick_opponent(module, pet.version, pet.stage, rng, own_name=pet.name)
        if record is None:
            _log(f"[Events] {data.name}: no opponent on version {pet.version}'s card")
            return None
        return GameEvent(data.id, data.name, module_name, data.global_event, EventType.CARD_BATTLE,
                         data.chance_percent, data.area, data.round,
                         opponent=record["name"], opponent_version=int(record.get("version") or 0))
    if kind == EventType.FRIEND_BATTLE.value:
        if friends is None:
            friends = getattr(game_globals, "friends", None) or {}
        found = _friend_battle(data, module_name, module, [pet] if pet else pets, friends, rng)
        if not found:
            return None
        _pet, name, encounter = found
        return _battle(data, module_name, name, encounter["area"], encounter["round"])
    if kind == EventType.POOL_BATTLE.value:
        pet = pet or next((p for p in pets if getattr(p, "module", None) == module_name
                           and _for_pet(data, p)), None)
        if pet is None:
            return None
        name = _pool_slot(data, module, pet)
        if not name:
            return None
        encounter = next((e for e in _special_encounters(module) if e.get("name") == name), None)
        if encounter is None:
            _log(f"[Events] {data.name}: no special encounter named {name}")
            return None
        return _battle(data, module_name, name, encounter["area"], encounter["round"])
    if getattr(data, "until_friend", False):
        encounter = next((e for e in _special_encounters(module)
                          if int(e.get("area", -1)) == int(data.area)
                          and int(e.get("round", -1)) == int(data.round)), None)
        from utils.xros_utils import get_module_friends
        if encounter is not None and encounter.get("name") in get_module_friends(module_name):
            return None
    return _battle(data, module_name, data.name, data.area, data.round)


# Random (hourly) ----------------------------------------------------------------

def random_events(module, party: bool):
    """*module*'s random-trigger events; only the global ones when no pet of
    the party is of the module."""
    entries = [e for e in module.load_events_json() if (e.trigger or "random") == "random"]
    return entries if party else [e for e in entries if e.global_event]


# Scheduled --------------------------------------------------------------------------

def scheduled_event(pets, modules, now, rng=random, friends=None):
    """The scheduled event due this minute for the first pet whose time it
    is, or None. Each pet's minute is used once (``_encounter_stamp``), and a
    time consumes the pet's pool slot whether or not it holds an opponent."""
    stamp, hhmm = now.strftime("%Y-%m-%d %H:%M"), now.strftime("%H:%M")
    for pet in pets:
        if not _awake(pet):
            continue
        module = modules.get(getattr(pet, "module", None))
        extras = getattr(module, "load_event_extras", None)
        if extras is None:
            continue
        schedule = extras().get("schedule") or {}
        group = _monster_field(pet, module, "encounter_time_group")
        if group is None or hhmm not in (schedule.get(str(group)) or []):
            continue
        if getattr(pet, "_encounter_stamp", None) == stamp:
            continue
        pet._encounter_stamp = stamp
        for data in module.load_events_json():
            if data.trigger == "schedule" and _for_pet(data, pet):
                event = resolve(pet.module, module, data, pets, rng, friends, pet=pet)
                if event is not None:
                    return event
    return None


# After a battle ---------------------------------------------------------------------

def _outcome_ok(data, won) -> bool:
    outcome = (data.outcome or "win").lower()
    return outcome == "any" or (outcome == "win") == bool(won)


def _protocol_ok(data, battle_format) -> bool:
    """A connection event naming a ``protocol`` needs the battle fought on
    that format: device numbers repeat across formats (a Digimon Mini Ver.1
    and an iC 10X both read 1)."""
    wanted = getattr(data, "protocol", "") or ""
    if not wanted:
        return True
    from battle.sim.protocol_constants import canonical_format
    return (canonical_format(str(wanted).upper())
            == canonical_format(str(battle_format or "").upper()))


def _device_ok(data, pets, opponent_device_version) -> bool:
    wanted = data.opponent_device_version
    if wanted is None:
        return True
    if opponent_device_version is None:
        return False
    from battle.combat_constants import ANY_OTHER_DEVICE
    if int(wanted) == ANY_OTHER_DEVICE:
        return any(int(getattr(p, "device_version", getattr(p, "version", 0)) or 0)
                   != int(opponent_device_version) for p in pets)
    return int(wanted) == int(opponent_device_version)


def shop_access_open(module_name, shop_name) -> bool:
    """Whether an event has opened *shop_name* and its time has not run out."""
    access = (getattr(game_globals, "shop_access", None) or {}).get(module_name, {})
    if shop_name not in access:
        return False
    until = access[shop_name]
    return not until or until > time.time()


def grant_shop_access(module_name, shop_name, minutes=0):
    """Open an ``event_only`` shop: for good (0) or *minutes*, never shortening
    a longer access already held."""
    store = getattr(game_globals, "shop_access", None)
    if not isinstance(store, dict):
        store = game_globals.shop_access = {}
    access = store.setdefault(module_name, {})
    until = 0 if not minutes else time.time() + int(minutes) * 60
    old = access.get(shop_name)
    if old == 0 and shop_name in access:
        return False
    access[shop_name] = until if old is None or until == 0 else max(old, until)
    return old is None


def after_battle(trigger, module_name, pets, won, opponent_device_version=None, rng=random,
                 area=None, battle_format=None):
    """Roll *module_name*'s *trigger* events ("adventure", "area_clear",
    "connection") for a battle *pets* (its pets in it) just fought, in
    adventure *area* (fought in, or just cleared) where there is one, on
    *battle_format* (a connection's). Shops open at once; the first battle or
    item event to hit becomes the pending event, and so does a one-visit shop
    (``access_minutes`` ONE_VISIT). Events sharing a ``draw`` are one roll:
    the first of those that fit, by their chances added up in order, or none.
    Returns the names of what happened, for the caller's log."""
    from models.game_event import EventType
    from utils.module_utils import get_module
    module = get_module(module_name)
    if module is None:
        return []
    pets = [p for p in pets or [] if getattr(p, "module", None) == module_name]
    if not pets:
        return []
    done = []

    def happen(data, mine):
        kind = int(data.type or 0)
        if kind == EventType.SHOP_ACCESS.value and int(data.access_minutes or 0) != ONE_VISIT:
            if grant_shop_access(module_name, data.shop, data.access_minutes):
                _announce(f"{data.shop} opened!")
                done.append(data.name)
            return
        if kind == EventType.FRIEND_BATTLE.value and data.delay_minutes:
            low, high = (list(data.delay_minutes) + [1, 1])[:2]
            from utils.xros_utils import promise_friend_event
            if promise_friend_event(module_name, mine, minutes=rng.randint(int(low), int(high))):
                done.append(data.name)
            return
        if getattr(game_globals, "event", None) is not None:
            return
        event = resolve(module_name, module, data, mine, rng)
        if event is not None:
            game_globals.event = event
            done.append(data.name)

    draws = {}
    for data in module.load_events_json():
        if data.trigger != trigger or not _outcome_ok(data, won):
            continue
        if data.trigger_areas and (area is None or int(area) not in data.trigger_areas):
            continue
        mine = [p for p in pets if _for_pet(data, p)]
        if not mine or not _device_ok(data, mine, opponent_device_version):
            continue
        if not _protocol_ok(data, battle_format):
            continue
        if getattr(data, "draw", ""):
            draws.setdefault(data.draw, []).append((data, mine))
            continue
        if rng.random() * 100 >= float(data.chance_percent or 0):
            continue
        happen(data, mine)
    for entries in draws.values():
        roll, total = rng.random() * 100, 0.0
        for data, mine in entries:
            total += float(data.chance_percent or 0)
            if roll < total:
                happen(data, mine)
                break
    if done:
        _log(f"[Events] {trigger} ({module_name}): {', '.join(done)}")
    return done


def after_connection(results, opponent_device_version=None, battle_format=None):
    """After a battle with another device or pet: each module's "connection"
    events, and its Connect Points, for its own pets. *results* is
    ``[(pet, won), ...]``; *battle_format* the format it was fought on."""
    from utils import connect_points
    by_module = {}
    for pet, won in results:
        by_module.setdefault(getattr(pet, "module", None), []).append((pet, won))
    for module_name, entries in by_module.items():
        for pet, won in entries:
            connect_points.award(pet, won, battle="connection")
        won_any = any(won for _pet, won in entries)
        after_battle("connection", module_name, [p for p, _w in entries], won_any,
                     opponent_device_version, battle_format=battle_format)


def after_adventure(module_name, pets, won, area=None):
    """After an adventure battle: the Connect Points of each pet that fought
    whose module counts adventure battles (``connect_points.battles``; the
    Vital Bracelets' battle drops), then *module_name*'s "adventure" events.
    Returns what `after_battle` returns."""
    from utils import connect_points
    for pet in pets or []:
        try:
            connect_points.award(pet, won, battle="adventure")
        except Exception as exc:
            _log(f"[Connect Points] adventure award failed: {exc}")
    return after_battle("adventure", module_name, pets, won, area=area)


def _announce(text):
    message = getattr(runtime_globals, "game_message", None)
    if message is not None:
        try:
            message.add_slide(text, (255, 255, 0), 56 * runtime_globals.UI_SCALE,
                              runtime_globals.FONT_SIZE_SMALL)
        except Exception:
            pass
