#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Evolution crawler: can every evolution route actually be taken? (MOD-19)

For each release module, each form a player can raise (module_audit's
reachability: from a choosable egg, a code, an item) and each of its routes:

  1. a GamePet of the form, built from the module's own record;
  2. its counters set the way the debug screen sets them, inside the route's
     requirements and within what a player can actually reach (the owner's
     rules, 2026-10-15: below), then moved outside the earlier routes' where
     a value allows it, since the first route met wins;
  3. evolved by the game's own method:
        normal and immediate routes  update_evolution() on a due timer
        death routes (at_death)      _death_evolution()
        armor routes (item)          armor_evolve(item)
        jogress routes               a real partner pet: find_route, then
                                     evolve_to, as JogressView does;
  4. achieved when the pet is the target afterwards. Rolled routes (chance,
     at_death, the module's win-ratio table) get up to ROLLS tries.

Otherwise the report says why:

    impossible   a requirement no player can reach, with the rule
    shadowed     an earlier route is always met first
    not met      the requirements were set and the game still did not take
                 it (a target missing on the version, a special target whose
                 key cannot be earned, a jogress partner that never exists)
    missed       a rolled route that never came up in ROLLS tries
    not tested   TWIN's Event Communications (owner: not now)

What a player can reach (owner, 2026-10-15): condition hearts 0..the
species' max, and a module uses them or mistakes, never both; mistakes from
0 to one below the module's death count; training counts every session;
battles have no limit, wins never exceed battles, win ratios are 0-100;
Level only where it is a visible stat, up to the stage's MAX_LEVEL; overfeed
needs a stomach; sleep disturbances are impossible where the module blocks
actions while asleep; Trophies, Vital Values (what a run without care
mistakes earns in the form, vital_values_reach) and Reliability (0-31) need
their visible stat; weight from the minimum weight
(1 with care_allow_below_min_weight) to 99; quests need daily quests; an
area must exist and the form must be able to battle; stage-N kills need a
stage-N enemy; G-Cells only on the Godzilla modules; a jogress partner must
exist, be raisable and have the target in its own line.

    python -B tests/release/evolution_crawl.py [MODULE ...] [--out DIR] [--quiet]

Writes <out>/evolution_crawl.json and evolution_crawl.md (default
tmp/release-reports/evolutions/). Exit 1 when a route is impossible.
"""
import argparse
import collections
import datetime as _dt
import json
import os
import random
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "support"))
from paths import ROOT  # noqa: E402
import module_audit as audit  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

UNBOUNDED = 999999
#: Tries for a route that rolls (chance, at_death, the win-ratio table).
ROLLS = 200
#: Rounds of moving counters to get past earlier routes.
AVOID_ROUNDS = 40
#: Largest battle count the battle-record search starts from above a route's minimum.
BATTLE_SPAN = 60
PLAIN_STAGES = (5, 6, 7, 8, 9)

#: Route criterion -> state variable (the pet attribute find_evolution reads).
COUNTERS = {
    "mistakes": "mistakes", "condition_hearts": "condition_hearts", "training": "effort",
    "overfeed": "overfeed", "level": "level", "quests_completed": "quests_completed",
    "weight": "weight", "trophies": "trophies", "vital_values": "vital_values",
    "reliability": "reliability", "pvp": "pvp_battles", "sleep_disturbances": "sleep_disturbances",
    "battles": "battles", "win_count": "win", "total_battles": "totalBattles",
    "form_minutes": "form_minutes", "virus": "virus", "poops": "poops",
    "stage-5": "kills5", "stage-6": "kills6", "stage-7": "kills7", "stage-8": "kills8", "stage-9": "kills9",
}
RATIOS = {"win_ratio": ("win", "battles"), "total_win_ratio": ("totalWin", "totalBattles")}
GCELL_KEYS = ("blue_gcells", "yellow_gcells", "red_gcells", "gcell_level", "gcells")
NOT_TESTED = {"event_communication": "TWIN's Event Communications are not tested for 1.0 (owner)"}
#: Keys that only describe a route or its partner, not the pet.
ROUTE_ONLY = {"to", "version", "chance", "at_death", "jogress", "jogress_name", "jogress_prefix",
              "jogress_stage", "jogress_version", "jogress_attribute", "defeat_tag_amount",
              "item_use_amount", "stage", "attribute"}
BATTLE_KEYS = {"battles", "win_count", "win_ratio", "total_battles", "total_win_ratio", "pvp",
               "area", "defeat_tag", "stage-5", "stage-6", "stage-7", "stage-8", "stage-9"}


class Impossible(Exception):
    """A requirement no player can meet."""


class FakeDatetime(_dt.datetime):
    """models.game_pet's clock: sleep times and time-of-day routes read it."""
    current = _dt.datetime(2026, 1, 1, 12, 0)

    @classmethod
    def now(cls, tz=None):
        return cls.current


def _range(value):
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return int(value[0]), int(value[1])
    if isinstance(value, (int, float)):
        return int(value), UNBOUNDED
    return None


# ----------------------------------------------------------------------------
# The module, as a player can play it
# ----------------------------------------------------------------------------

class Ctx:
    """What one module lets a player reach."""

    def __init__(self, name, game_module):
        self.name = name
        self.game_module = game_module
        self.mod = audit.Module(name)
        checker = audit.Audit(self.mod)
        self.reach = checker.reachability()
        self.held = set(checker.got_unlocks)            # unlocks a player can earn
        meta = self.mod.meta
        self.visible = self.mod.visible
        self.use_condition_hearts = bool(meta.get("care_condition_heart"))
        self.death_mistakes = int(meta.get("death_care_mistake") or 0)
        self.below_min_weight = bool(meta.get("care_allow_below_min_weight"))
        self.block_asleep = bool(meta.get("care_block_actions_when_sleeping"))
        self.poop_rule = int(meta.get("care_poop_mistake_time") or 0)
        # Days a pet lives under the Old Age lifespan rule (utils.lifespan_rules).
        old_age = meta.get("lifespan_rule", "Old Age") == "Old Age"
        self.old_age_days = int(meta.get("death_old_age") or 0) if old_age else 0
        self.gcells = bool(meta.get("use_gcells")) or (meta.get("gcell_style") not in (None, "", "Disabled"))
        self.enemy_stages = {int(e.get("stage") or 0) for e in self.mod.enemies}
        self.special_encounters = any(e.get("special_encounter") for e in self.mod.enemies)
        self.areas = set(self.mod.adventure_areas)
        self.tags = {t for m in self.mod.monsters for t in (m.get("tags") or [])}
        self.items = self.mod.item_names
        self.has_quests = bool(self.mod.quests)


def can_battle(form):
    return (form.get("stage") or 0) >= 2 and (form.get("power") or 0) > 0 and bool(form.get("atk_main"))


def vital_values_reach(form, route, ctx):
    """The Vital Values a run without care mistakes holds when *form*'s
    routes are read (owner, 2026-10-15: such a run reaches every route; the
    Vital Drinks add more but are not counted).

    Every awake hour pays the module's vital_value_base x (1 + a training +
    a battle won): GamePet.update_vital_values_gain, the hour landing before
    the evolution check. A form that cannot battle only trains. A form whose
    Vital Values carry over (core.pet_stats: Stage I -> II -> III) shares the
    day with the forms before it, which run from the moment the pet wakes;
    any other form starts at 100 when it wakes. The route's own battles pay
    the BE stage table (utils.card_battle), as many won as its win ratio
    allows. The result stops at the stage's cap."""
    from core import pet_stats
    from utils.card_battle import VITAL_LOSS, VITAL_WIN
    base = int(ctx.mod.meta.get("vital_value_base", 50) or 0)
    stage = int(form.get("stage") or 0)

    def awake_per_day(record):
        try:
            sh, sm = (int(x) for x in str(record.get("sleeps")).split(":"))
            wh, wm = (int(x) for x in str(record.get("wakes")).split(":"))
        except (TypeError, ValueError):
            return 24
        return ((sh * 60 + sm) - (wh * 60 + wm)) % 1440 // 60 or 24

    # The forms before this one in the same day: the shortest of each stage
    # (fewer hours, fewer Vital Values).
    chain = []
    s = stage
    while s - 1 in pet_stats.VITAL_VALUES_CARRIED_FROM:
        s -= 1
        times = [int(m.get("time") or 0) for m in ctx.mod.monsters if int(m.get("stage") or 0) == s]
        chain.insert(0, (min(times) // 60 if times else 0, 2))      # a training an hour
    hi = 100
    if route.get("win_ratio"):
        hi = min(100, _range(route["win_ratio"])[1])
    own = 1 + bool(form.get("atk_main")) + (can_battle(form) and hi > 0)
    chain.append((int(form.get("time") or 0) // 60, own))
    day = awake_per_day(form)
    total, hour = 100, 0
    for hours, factor in chain:
        for _ in range(hours):
            if hour % 24 < day:
                total += base * factor
            hour += 1
    if stage >= 3 and can_battle(form) and route.get("battles"):
        battles = _range(route["battles"])[0]
        wins = battles * hi // 100
        own_stage = max(3, min(8, stage))
        total += (wins * VITAL_WIN[own_stage][own_stage - 3]
                  - (battles - wins) * VITAL_LOSS[own_stage][own_stage - 3])
    return min(max(0, total), pet_stats.vital_value_cap(stage) or UNBOUNDED)


def legal(key, form, ctx, route=None):
    """The (lo, hi) a player can reach for a counter criterion; Impossible
    with the rule when none."""
    stage = int(form.get("stage") or 0)
    if key in BATTLE_KEYS and not can_battle(form):
        raise Impossible("this form cannot battle (stage, power or attack)")
    if key == "mistakes":
        if ctx.use_condition_hearts:
            raise Impossible("the module counts condition hearts, not mistakes")
        if 0 < ctx.death_mistakes < UNBOUNDED:
            return 0, ctx.death_mistakes - 1
        return 0, UNBOUNDED
    if key == "condition_hearts":
        if not ctx.use_condition_hearts:
            raise Impossible("the module counts mistakes, not condition hearts")
        return 0, int(form.get("condition_hearts") or 0)
    if key == "overfeed" and not form.get("stomach"):
        raise Impossible("overfeeding needs a stomach value")
    if key == "level":
        if "level" not in ctx.visible:
            raise Impossible("Level is not a visible stat of the module")
        from core.pet_stats import MAX_LEVEL
        return 1, MAX_LEVEL.get(stage, 10)
    if key == "quests_completed" and not ctx.has_quests:
        raise Impossible("the module has no daily quests")
    if key == "weight":
        floor = 1 if ctx.below_min_weight else int(form.get("min_weight") or 0)
        return floor, 99
    if key == "trophies" and "trophies" not in ctx.visible:
        raise Impossible("Trophies is not a visible stat of the module")
    if key == "vital_values":
        if "vital values" not in ctx.visible:
            raise Impossible("Vital Values is not a visible stat of the module")
        return 0, vital_values_reach(form, route or {}, ctx)
    if key == "reliability":
        if "reliability" not in ctx.visible:
            raise Impossible("Reliability is not a visible stat of the module")
        return 0, 31
    if key == "sleep_disturbances" and ctx.block_asleep:
        raise Impossible("the module blocks actions while asleep, so nothing disturbs sleep")
    if key == "virus" and not ctx.poop_rule:
        raise Impossible("the module has no poop rule (care_poop_mistake_time)")
    if key == "form_minutes" and ctx.old_age_days:
        return 0, ctx.old_age_days * 1440
    if key.startswith("stage-"):
        level = int(key.split("-")[1])
        if level not in ctx.enemy_stages:
            raise Impossible(f"the module has no stage-{level} enemy to defeat")
    if key in ("win_ratio", "total_win_ratio"):
        return 0, 100
    return 0, UNBOUNDED


def window(route, key, form, ctx):
    """The route's requirement on *key* within what a player reaches."""
    lo, hi = legal(key, form, ctx, route)
    want = _range(route.get(key))
    if want is None:
        return lo, hi
    a, b = max(lo, want[0]), min(hi, want[1])
    if a > b:
        raise Impossible(f"{key} {list(want)} but a player reaches {lo}-{hi if hi < UNBOUNDED else 'any'}")
    return a, b


# ----------------------------------------------------------------------------
# Pets and state
# ----------------------------------------------------------------------------

def neutral(form, ctx):
    """A form's state on arrival: the counters a fresh pet has."""
    hearts = int(form.get("condition_hearts") or 0)
    return {
        "mistakes": 0, "condition_hearts": hearts, "effort": 0, "overfeed": 0, "level": 1,
        "quests_completed": 0, "weight": max(int(form.get("min_weight") or 0), 1),
        "trophies": 0, "vital_values": 0, "reliability": 15 if "reliability" in ctx.visible else 0,
        "pvp_battles": 0, "sleep_disturbances": 0, "battles": 0, "win": 0, "totalBattles": 0,
        "totalWin": 0, "form_minutes": 0, "virus": 0, "poops": 0,
        "kills5": 0, "kills6": 0, "kills7": 0, "kills8": 0, "kills9": 0,
        "gcell_points": 0, "special_encounter": False, "gcell_fragment": False, "dna": [],
        "item_uses": {}, "tag_defeats": {}, "unlocks": set(), "clock": None, "asleep": False,
    }


class Bench:
    """Builds pets of one module and runs the game's evolution code on them."""

    def __init__(self, ctx, env):
        self.ctx = ctx
        self.env = env
        from models.game_pet import GamePet
        self.GamePet = GamePet

    def pet(self, form, state):
        """A GamePet of *form*: the game's record (crawl() hands those in,
        routes migrated), so a test can hand in routes of its own. A form
        carrying `_module` is another module's (a jogress partner)."""
        data = dict(form)
        data["module"] = data.pop("_module", None) or self.ctx.name
        pet = self.GamePet(data)
        self.apply(pet, state)
        return pet

    def apply(self, pet, state):
        from core import game_globals
        for key in ("mistakes", "condition_hearts", "effort", "overfeed", "level", "quests_completed",
                    "weight", "trophies", "vital_values", "reliability", "pvp_battles",
                    "sleep_disturbances", "battles", "win", "totalBattles", "totalWin",
                    "form_minutes", "virus", "gcell_points", "special_encounter", "gcell_fragment"):
            setattr(pet, key, state[key])
        pet.dna = list(state["dna"])
        pet.item_uses = dict(state["item_uses"])
        pet.tag_defeats = dict(state["tag_defeats"])
        pet.area = int(state.get("area") or 0)
        kills = [0] * 11
        for level in PLAIN_STAGES:
            kills[level] = state[f"kills{level}"]
        pet.enemy_kills = kills
        # Fed, strong, healthy and due: nothing but the route holds it back.
        pet.hunger = max(1, int(getattr(pet, "stomach", 0) or 4))
        pet.strength = max(4, int(getattr(pet, "stomach", 0) or 4))
        pet.sick = pet.injury = 0
        pet.dying = False
        pet.evolution_failed = False
        pet._evol_minutes = max(int(getattr(pet, "time", 0) or 0), 0)
        pet.state = "nap" if state["asleep"] else "idle"
        game_globals.poop_list = [object()] * int(state["poops"])
        game_globals.unlocks[self.ctx.name] = [{"type": "crawl", "name": n} for n in state["unlocks"]]
        FakeDatetime.current = state["clock"] or self.awake_time(pet)

    @staticmethod
    def awake_time(pet):
        """Noon, or the first half hour the form is awake."""
        sleeps, wakes = getattr(pet, "sleeps", None), getattr(pet, "wakes", None)
        for minutes in range(12 * 60, 12 * 60 + 24 * 60, 30):
            moment = _dt.datetime(2026, 1, 1) + _dt.timedelta(minutes=minutes)
            if not sleeps or not wakes or not asleep_at(moment.time(), sleeps, wakes):
                return moment
        return _dt.datetime(2026, 1, 1, 12, 0)

    # -- oracles: the game's own route check, no rolls --------------------
    @staticmethod
    def first(pet, kind):
        match = pet.find_evolution(roll_chance=False, kind=kind)
        return match[0] if match else None

    @staticmethod
    def meets(pet, route, kind):
        saved = pet.evolve
        try:
            pet.evolve = [route]
            return pet.find_evolution(roll_chance=False, kind=kind) is not None
        finally:
            pet.evolve = saved


def asleep_at(moment, sleeps, wakes):
    try:
        s = _dt.datetime.strptime(sleeps.strip(), "%H:%M").time()
        w = _dt.datetime.strptime(wakes.strip(), "%H:%M").time()
    except (ValueError, AttributeError):
        return False
    return s <= moment < w if s < w else (moment >= s or moment < w)


def kind_of(route):
    from utils import evolution_rules
    from utils.jogress_utils import is_jogress
    if is_jogress(route):
        return "jogress"
    if "item" in route:
        return "item"
    if evolution_rules.is_death_route(route):
        return "death"
    if evolution_rules.is_immediate_route(route):
        return "immediate"
    return "normal"


def rolls(route, ctx):
    """Whether taking the route involves a roll."""
    if route.get("chance") is not None and int(route.get("chance")) >= 0:
        return True
    if route.get("at_death"):
        return True
    if "win_ratio" in route or "total_win_ratio" in route:
        table = ctx.game_module and getattr(ctx.game_module, "evolution_win_ratio_chance", None)
        return bool(table) and table != [[0, 100]]
    return False


# ----------------------------------------------------------------------------
# Meeting one route
# ----------------------------------------------------------------------------

def requirements(route, form, ctx, state):
    """Set *state* inside every requirement of *route*. Returns the windows
    used, {criterion: (lo, hi)}; raises Impossible."""
    windows = {}
    for key, value in route.items():
        if key in ROUTE_ONLY:
            continue
        if key in NOT_TESTED:
            raise NotTested(NOT_TESTED[key])
        if key in COUNTERS:
            lo, hi = window(route, key, form, ctx)
            windows[key] = (lo, hi)
            state[COUNTERS[key]] = lo
        elif key in RATIOS:
            windows[key] = window(route, key, form, ctx)
        elif key in GCELL_KEYS:
            if not ctx.gcells:
                raise Impossible(f"{key} on a module without G-Cells")
            windows[key] = _range(value)
        elif key == "area":
            if not can_battle(form):
                raise Impossible("this form cannot battle, so it never clears an area itself")
            if value not in ctx.areas:
                raise Impossible(f"area {value} has no adventure enemies")
            state["area"] = value
        elif key == "unlock":
            if value not in ctx.held:
                raise Impossible(f"unlock '{value}' cannot be earned")
            state["unlocks"].add(value)
        elif key == "special_encounter":
            if value and not ctx.special_encounters:
                raise Impossible("the module has no special encounters")
            state["special_encounter"] = bool(value)
        elif key == "gcell_hatch":
            if not ctx.game_module.has_gcell_fragment_egg():
                raise Impossible("the module has no G-Cell Fragment egg")
            state["gcell_fragment"] = True
        elif key == "digisoul_dna":
            if value:
                state["dna"] = [value[0]]
        elif key == "item_use":
            if value not in ctx.items:
                raise Impossible(f"item '{value}' is not in item.json")
            state["item_uses"] = {value: int(route.get("item_use_amount") or 1)}
        elif key == "defeat_tag":
            if not can_battle(form):
                raise Impossible("this form cannot battle")
            if value not in ctx.tags:
                raise Impossible(f"no Digimon in the module carries the tag '{value}'")
            amount = _range(route.get("defeat_tag_amount")) or (1, UNBOUNDED)
            state["tag_defeats"] = {value: amount[0]}
        elif key == "time_range":
            state["clock"] = clock_in(value)
        elif key in ("item",):
            continue
        else:
            raise NotTested(f"criterion '{key}' unknown to the crawler")
    return windows


class NotTested(Exception):
    pass


def clock_in(time_range):
    try:
        start = _dt.datetime.strptime(str(time_range[0]).strip(), "%H:%M")
    except (ValueError, TypeError, IndexError):
        return None
    return _dt.datetime(2026, 1, 1, start.hour, start.minute) + _dt.timedelta(minutes=1)


def battle_record(route, windows, state, prefer=None):
    """Battles and wins (and totals) inside the route's battle windows."""
    b_lo, b_hi = windows.get("battles", (state["battles"], state["battles"] if "battles" not in windows else UNBOUNDED))
    if "battles" not in windows and ("win_ratio" in windows or "win_count" in windows):
        b_lo, b_hi = 0, UNBOUNDED
    w_lo, w_hi = windows.get("win_count", (0, UNBOUNDED))
    b_lo = max(b_lo, w_lo)
    r = windows.get("win_ratio")
    tb_lo, tb_hi = windows.get("total_battles", (0, UNBOUNDED))
    tr = windows.get("total_win_ratio")
    for battles in range(b_lo, min(b_hi, b_lo + BATTLE_SPAN) + 1):
        for wins in (prefer or range(0, battles + 1)):
            if wins > battles or not (w_lo <= wins <= w_hi):
                continue
            if r and battles and not (r[0] <= wins * 100 // battles <= r[1]):
                continue
            for total in range(max(battles, tb_lo), max(battles, tb_lo) + BATTLE_SPAN + 1):
                if total > tb_hi:
                    break
                for twins in range(wins, wins + (total - battles) + 1):
                    if tr and total and not (tr[0] <= twins * 100 // total <= tr[1]):
                        continue
                    state.update(battles=battles, win=wins, totalBattles=total, totalWin=twins)
                    return True
    return False


def gcell_points(route, windows, ctx, pet):
    """A G-Cell point total whose cells the route asks for."""
    from utils import gcell_rules
    keys = [k for k in GCELL_KEYS if k in windows]
    if not keys:
        return None
    for points in range(0, 2000):
        pet.gcell_points = points
        values = {"blue_gcells": pet.get_blue_gcells(), "yellow_gcells": pet.get_yellow_gcells(),
                  "red_gcells": pet.get_red_gcells(), "gcell_level": pet.get_gcell_level(),
                  "gcells": gcell_rules.cells(ctx.game_module, pet)}
        if all(windows[k][0] <= values[k] <= windows[k][1] for k in keys):
            return points
    raise Impossible("no G-Cell total gives " + ", ".join(f"{k} {list(windows[k])}" for k in keys))


def candidates(key, route, windows, form, ctx, avoid):
    """Values for *key*'s variable inside the route's window and outside the
    earlier route's (*avoid*), nearest first."""
    lo, hi = windows.get(key) or legal(key, form, ctx, route)
    out = []
    bad = _range(avoid.get(key))
    for v in (lo, hi if hi < UNBOUNDED else lo + 50, (bad[0] - 1) if bad else None,
              (bad[1] + 1) if bad and bad[1] < UNBOUNDED else None):
        if v is not None and lo <= v <= hi and (not bad or not bad[0] <= v <= bad[1]) and v not in out:
            out.append(v)
    return out


def get_past(bench, pet, form, route, kind, windows, state, earlier):
    """Move counters until *route* is the first one met. Returns None, or the
    earlier route that always wins."""
    ctx = bench.ctx
    for _ in range(AVOID_ROUNDS):
        bench.apply(pet, state)
        hit = bench.first(pet, kind)
        if hit is route:
            return None
        if hit is None or hit not in earlier:
            return "unmet"
        if hit_rolls(hit, ctx):
            # A failed roll falls through to the next route: try it for real,
            # as often as a rolled route.
            return "rolled"
        moved = False
        for key in hit:
            if key in ROUTE_ONLY:
                continue
            trials = []
            if key in COUNTERS:
                var = COUNTERS[key]
                trials = [{var: v} for v in candidates(key, route, windows, form, ctx, hit)]
                if key in ("battles", "win_count", "total_battles"):
                    trials += [dict(battles=b, win=w, totalBattles=max(b, state["totalBattles"]),
                                    totalWin=max(w, state["totalWin"]))
                               for b in range(0, BATTLE_SPAN) for w in (0, b)]
            elif key in RATIOS:
                win, battles = RATIOS[key]
                for b in range(max(1, state[battles]), state[battles] + BATTLE_SPAN):
                    for w in range(0, b + 1):
                        trials.append({battles: b, win: w,
                                       "totalBattles": max(b, state["totalBattles"]),
                                       "totalWin": max(w, min(state["totalWin"], b))})
            elif key == "special_encounter" and "special_encounter" not in route:
                trials = [{"special_encounter": not hit.get("special_encounter")}]
            elif key == "digisoul_dna":
                theirs = set(hit.get("digisoul_dna") or [])
                ours = route.get("digisoul_dna") or []
                trials = [{"dna": [t]} for t in ours if t not in theirs]
                if "digisoul_dna" not in route:
                    trials.append({"dna": []})
            elif key == "unlock" and "unlock" not in route:
                trials = [{"unlocks": set()}]
            elif key == "time_range":
                trials = [{"clock": _dt.datetime(2026, 1, 1, h, m)} for h in range(24) for m in (5, 35)]
            here = pet.evolve.index(hit)
            for change in trials:
                trial = dict(state, **change)
                bench.apply(pet, trial)
                now = bench.first(pet, kind)
                # Only forward: the first route met has to move later in the
                # list (or be this one), or two earlier routes trade places
                # for ever.
                forward = now is not None and (now is route or pet.evolve.index(now) > here)
                if forward and bench.meets(pet, route, kind):
                    state.update(change)
                    moved = True
                    break
            if moved:
                break
        if not moved:
            return hit
    return "unmet"


def take(bench, form, route, kind, state, partner=None, index=None):
    """Run the game's method once on a fresh pet; True when it evolved into the target."""
    pet = bench.pet(form, state)
    target = route.get("to")
    if kind in ("normal", "immediate"):
        pet.update_evolution()
    elif kind == "death":
        pet._death_evolution()
    elif kind == "item":
        # The Armor / Item menu, as often as the route's amount asks.
        for _ in range(max(1, int(route.get("item_amount") or 1))):
            if pet.use_evolution_item(route["item"]):
                break
    elif kind == "jogress":
        from utils.jogress_utils import find_route
        other = bench.pet(partner, neutral(partner, ctx_of(partner, bench)))
        # Building the partner set the save to its state; the owner's
        # (its unlocks) is the one the route reads.
        bench.apply(pet, state)
        # The pet's own copy of its routes: the one at this route's place
        # has to be the first the partner satisfies.
        evo = find_route(pet, other)
        if evo is None or pet.evolve.index(evo) != index:
            return False
        pet.evolve_to(evo["to"], pet.version)
    return pet.name == target


def taken_route(bench, form, state, partner):
    """The jogress route a pet of *form* takes with *partner*."""
    from utils.jogress_utils import find_route
    other = bench.pet(partner, neutral(partner, ctx_of(partner, bench)))
    return find_route(bench.pet(form, state), other)


#: Each module's Ctx, built once (a jogress partner's module too).
CTXS = {}


def ctx_for(name, env):
    if name not in CTXS:
        CTXS[name] = Ctx(name, env.rg.game_modules[name])
    return CTXS[name]


def ctx_of(form, bench):
    """The Ctx of *form*'s module: its own `_module`, or the bench's."""
    name = form.get("_module")
    return ctx_for(name, bench.env) if name and name != bench.ctx.name else bench.ctx


def protocol_peers(ctx, env):
    """The other installed modules on the same battle protocol: their pets
    can jogress with this module's (jogress_utils.can_pair)."""
    from utils.jogress_utils import protocol_of
    mine = protocol_of(ctx.name)
    if not mine:
        return []
    return [n for n in sorted(env.rg.game_modules) if n != ctx.name and protocol_of(n) == mine]


def jogress_partners(route, form, ctx, bench):
    """Raisable forms that satisfy the route. A fusion (Single) also needs
    the target in the partner's own line (owner: both Digimon need it); in a
    Dual jogress each pet takes its own route, so a matching partner is
    enough. Pets of a module on the same battle protocol count too (PENGZ
    with the Pendulum Color, DMRV with the DM20)."""
    from utils.jogress_utils import matches_partner, is_jogress, is_dual
    owner = bench.pet(form, neutral(form, ctx))
    found, wrong_line = [], []
    sources = [(ctx, None)] + [(ctx_for(name, bench.env), name) for name in protocol_peers(ctx, bench.env)]
    for source, foreign in sources:
        for raw in source.mod.monsters:
            if (raw.get("name"), raw.get("version")) not in source.reach or raw.get("stage", 0) <= 0:
                continue
            other = dict(source.game_module.get_monster(raw["name"], raw["version"]) or raw)
            if foreign:
                other["_module"] = foreign
            candidate = bench.pet(other, neutral(other, source))
            if not matches_partner(route, owner, candidate):
                continue
            if is_dual(route) or any(is_jogress(r) and r.get("to") == route.get("to")
                                     for r in candidate.evolve or []):
                found.append(other)
            else:
                wrong_line.append(other)
    return found, wrong_line


def crawl_route(bench, form, index, route, ctx):
    kind = kind_of(route)
    row = {"module": ctx.name, "form": form.get("name"), "version": form.get("version"),
           "stage": form.get("stage"), "route": index, "to": route.get("to"), "kind": kind}
    state = neutral(form, ctx)
    target = ctx.mod.by_key.get((route.get("to"), route.get("version", form.get("version")))) \
        or next(iter(ctx.mod.by_name.get(route.get("to")) or []), None)
    if target is None:
        return dict(row, result="not met", reason="the target is not in the module")
    key = target.get("special_key")
    if target.get("special") and key and (form.get("stage") or 0) > 0:
        if key not in ctx.held:
            return dict(row, result="not met", reason=f"special target: key '{key}' cannot be earned")
        state["unlocks"].add(key)
    try:
        windows = requirements(route, form, ctx, state)
    except Impossible as exc:
        return dict(row, result="impossible", reason=str(exc))
    except NotTested as exc:
        return dict(row, result="not tested", reason=str(exc))

    if kind == "jogress":
        partners, wrong_line = jogress_partners(route, form, ctx, bench)
        if wrong_line and not partners:
            return dict(row, result="not met", reason="partners lack the target in their own line: " +
                        ", ".join(f"{p['name']} v{p['version']}" for p in wrong_line[:4]))
        if not partners:
            # Only a connected device could be the partner (or the data
            # names one that does not exist).
            return dict(row, result="partner elsewhere",
                        reason="no raisable form of the module matches the partner")
        for partner in partners:
            if take(bench, form, route, kind, state, partner, index):
                where = f" ({partner['_module']})" if partner.get("_module") else ""
                return dict(row, result="achieved", partner=f"{partner['name']} v{partner['version']}{where}")
        if route.get("jogress_attribute") and all(
                (taken_route(bench, form, state, partner) or {}).get("jogress_name") for partner in partners):
            # Every partner here is named by an earlier route; the attribute
            # route is for the rest, another device's (PENGZ: "any Digimon
            # from another Digimon Pendulum Color Version").
            return dict(row, result="partner elsewhere",
                        reason="every raisable partner takes an earlier route naming it")
        return dict(row, result="shadowed", reason="an earlier jogress route of the pair is taken")
    if kind == "item":
        first = next((i for i, r in enumerate(form.get("evolve") or []) if r.get("item") == route["item"]), index)
        if first != index:
            return dict(row, result="shadowed", reason=f"route {first} uses the same item first")
        return dict(row, result="achieved" if take(bench, form, route, kind, state) else "not met",
                    reason=None)

    pet = bench.pet(form, state)
    if any(k in windows for k in RATIOS) or any(k in windows for k in ("battles", "win_count", "total_battles")):
        if not battle_record(route, windows, state):
            return dict(row, result="impossible", reason="no battle record meets battles, wins and ratios together")
    try:
        points = gcell_points(route, windows, ctx, pet)
    except Impossible as exc:
        return dict(row, result="impossible", reason=str(exc))
    if points is not None:
        state["gcell_points"] = points
    if state["clock"] is not None and asleep_at(state["clock"].time(), getattr(pet, "sleeps", "") or "",
                                                 getattr(pet, "wakes", "") or ""):
        state["asleep"] = True
    lookup = "death" if kind == "death" else ("immediate" if kind == "immediate" else "normal")
    routes = form.get("evolve") or []
    earlier = [r for r in pet.evolve[:index]]
    route_obj = pet.evolve[index]
    blocker = get_past(bench, pet, form, route_obj, lookup, windows, state, earlier)
    if blocker == "unmet":
        bench.apply(pet, state)
        return dict(row, result="not met", reason="the game does not take it with every requirement set",
                    state=summary(state))
    rolled = blocker == "rolled"
    if rolled:
        blocker = None
    if blocker is not None:
        # The step-by-step search can stall where several criteria must move
        # together (DW1's 3-of-4 routes); the exact search settles it.
        found = exact_state(bench, form, index, ctx, state, windows, lookup)
        if found is None:
            j = pet.evolve.index(blocker)
            return dict(row, result="shadowed", reason=f"route {j} (to {blocker.get('to')}) is always met first",
                        by=j)
        state = found
    tries = ROLLS if rolled or rolls(routes[index], ctx) else 1
    for attempt in range(tries):
        random.seed(attempt)
        pet = bench.pet(form, state)
        route_obj = pet.evolve[index]
        if take_pet(pet, route_obj, kind):
            return dict(row, result="achieved", tries=attempt + 1, state=summary(state))
    return dict(row, result="missed" if tries > 1 else "not met",
                reason=f"never taken in {tries} {'tries' if tries > 1 else 'try'}", state=summary(state))


def _box(route, form, ctx):
    """A route's criteria as {key: (lo, hi)}; None for one the exact search
    cannot vary (the route is then left out of it)."""
    out = {}
    for key, value in route.items():
        if key in ROUTE_ONLY or key in ("time_range", "dna", "digisoul_dna", "item", "item_amount"):
            continue
        if key in COUNTERS or key in RATIOS or key.startswith("stage-"):
            lo, hi = _range(value)
            out[key] = (lo, hi)
        elif key == "area":
            out[key] = (int(value), UNBOUNDED)
        elif key == "special_encounter":
            out[key] = (1, 1) if value else (0, 0)
        elif key == "unlock":
            out["unlock:" + value] = (1, 1)
        else:
            return None
    return out


def exact_state(bench, form, index, ctx, state, windows, kind):
    """A state that meets route *index* and no earlier route, or None: each
    earlier route needs one criterion outside its range (a hitting set over
    intervals), and the game has the last word (Bench.first)."""
    routes = form.get("evolve") or []
    target = _box(routes[index], form, ctx)
    if target is None:
        return None
    earlier = []
    for j in range(index):
        r = routes[j]
        if (not evolution_rules_wanted(r, kind) or r.get("jogress") or r.get("item")
                or r.get("chance") is not None):
            continue
        b = _box(r, form, ctx)
        if b is None:
            return None             # a criterion the search cannot avoid
        earlier.append(b)
    keys = set(target) | {k for b in earlier for k in b}
    box = {}
    for k in keys:
        if k in windows:
            lo, hi = windows[k]
        elif k.startswith("unlock:"):
            lo, hi = (0, 1) if k[7:] in ctx.held else (0, 0)
        elif k == "special_encounter":
            lo, hi = (0, 1) if ctx.special_encounters else (0, 0)
        elif k == "area":
            lo, hi = 0, (max(ctx.areas) if ctx.areas and can_battle(form) else 0)
        else:
            try:
                lo, hi = legal(k, form, ctx, routes[index])
            except Impossible:
                lo = hi = 0
        if k in target:
            lo, hi = max(lo, target[k][0]), min(hi, target[k][1])
        if lo > hi:
            return None
        box[k] = (lo, hi)

    def dfs(n, box):
        if n == len(earlier):
            return box
        b = earlier[n]
        if any(box[k][1] < a or box[k][0] > z for k, (a, z) in b.items()):
            return dfs(n + 1, box)
        for k, (a, z) in b.items():
            lo, hi = box[k]
            for nlo, nhi in ((lo, a - 1), (z + 1, hi)):
                if nlo <= nhi:
                    got = dfs(n + 1, dict(box, **{k: (nlo, nhi)}))
                    if got:
                        return got
        return None

    got = dfs(0, box)
    if not got:
        return None
    trial = dict(state, unlocks=set(state["unlocks"]))
    for k, (lo, _) in got.items():
        if k in COUNTERS:
            trial[COUNTERS[k]] = lo
        elif k == "area":
            trial["area"] = lo
        elif k == "special_encounter":
            trial["special_encounter"] = bool(lo)
        elif k.startswith("unlock:"):
            (trial["unlocks"].add if lo else trial["unlocks"].discard)(k[7:])
        elif k.startswith("stage-"):
            trial["kills" + k[6:]] = lo
    for ratio, (wins, total) in RATIOS.items():
        if ratio in got:
            r = got[ratio][0]
            trial[total] = max(int(trial.get(total) or 0), 100 if r else 1)
            trial[wins] = (trial[total] * r + 99) // 100
    trial["totalBattles"] = max(trial["totalBattles"], trial["battles"])
    trial["totalWin"] = max(trial["totalWin"], trial["win"])
    pet = bench.pet(form, trial)
    first = bench.first(pet, kind)
    return trial if first is not None and pet.evolve.index(first) == index else None


def evolution_rules_wanted(route, kind):
    from utils import evolution_rules
    return evolution_rules.route_wanted(route, kind)


def take_pet(pet, route, kind):
    target = route.get("to")
    if kind in ("normal", "immediate"):
        pet.update_evolution()
    elif kind == "death":
        pet._death_evolution()
    return pet.name == target


def hit_rolls(route, ctx):
    return rolls(route, ctx)


def redundant(rows):
    """A shadowed route whose target another route of the same form reaches
    loses nothing: mark it redundant (info)."""
    reached = {(r["module"], r["form"], r["version"], r["to"]) for r in rows if r["result"] == "achieved"}
    for r in rows:
        if r["result"] == "shadowed" and (r["module"], r.get("form"), r.get("version"), r.get("to")) in reached:
            r["result"] = "redundant"
            r["reason"] = (r.get("reason") or "") + "; another route reaches the same target"
    return rows


def summary(state):
    out = {k: v for k, v in state.items() if v not in (0, False, None, [], {}, set()) and k != "clock"}
    if state.get("clock"):
        out["clock"] = state["clock"].strftime("%H:%M")
    if "unlocks" in out:
        out["unlocks"] = sorted(out["unlocks"])
    return out


# ----------------------------------------------------------------------------
# Running
# ----------------------------------------------------------------------------

def crawl(names, quiet=False):
    from harness import Env, quiet as hush
    env = Env("240x240", fixture="empty")
    from utils.jogress_utils import normalize_evolutions
    from models import game_pet
    game_pet.datetime = FakeDatetime
    game_pet.GamePet.load_sprite = lambda self: None
    game_pet.register_digidex_entry = lambda *a, **k: None
    from utils import utils_unlocks, quest_event_utils
    utils_unlocks.check_digidex_unlocks = lambda *a, **k: None
    quest_event_utils.update_evolution_quest_progress = lambda *a, **k: None
    rows = []
    for name in names:
        game_module = env.rg.game_modules.get(name)
        if game_module is None:
            rows.append({"module": name, "result": "not tested", "reason": "module not installed"})
            continue
        started = time.time()
        ctx = ctx_for(name, env)
        bench = Bench(ctx, env)
        count = 0
        for raw in ctx.mod.monsters:
            if (raw.get("name"), raw.get("version")) not in ctx.reach:
                continue
            # The game's record: old route shapes (D-3's partner-named
            # jogress, PENZ's stage+attribute pairs) migrated on load.
            form = dict(game_module.get_monster(raw["name"], raw["version"]) or raw)
            form["evolve"] = normalize_evolutions(form.get("evolve") or [])
            for index, route in enumerate(form.get("evolve") or []):
                count += 1
                try:
                    with hush():
                        rows.append(crawl_route(bench, form, index, route, ctx))
                except Exception as exc:  # one broken route must not stop the crawl
                    rows.append({"module": name, "form": form.get("name"), "version": form.get("version"),
                                 "route": index, "to": route.get("to"), "result": "error",
                                 "reason": f"{exc!r}", "trace": traceback.format_exc()[-1500:]})
        tally = collections.Counter(r["result"] for r in rows if r.get("module") == name)
        if not quiet:
            print(f"{name:8} {count:5} routes in {time.time() - started:5.1f}s  " +
                  "  ".join(f"{k} {v}" for k, v in sorted(tally.items())), flush=True)
    return redundant(rows)


SEVERITY = {"impossible": "error", "error": "error", "not met": "error", "shadowed": "warn",
            "missed": "warn", "partner elsewhere": "warn", "redundant": "info", "not tested": "info",
            "achieved": "ok"}


def markdown(rows, names):
    lines = ["# Evolution crawl", "", f"{time.strftime('%Y-%m-%d %H:%M')}. Every route of every form a player "
             "can raise, evolved by the game's own method (tests/release/evolution_crawl.py, MOD-19).", "",
             "| Module | Routes | Achieved | Impossible | Not met | Shadowed | Partner elsewhere | Missed | Redundant | Not tested |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for name in names:
        tally = collections.Counter(r["result"] for r in rows if r.get("module") == name)
        lines.append(f"| {name} | {sum(tally.values())} | {tally['achieved']} | {tally['impossible']} | "
                     f"{tally['not met'] + tally['error']} | {tally['shadowed']} | {tally['partner elsewhere']} | "
                     f"{tally['missed']} | "
                     f"{tally['redundant']} | {tally['not tested']} |")
    for name in names:
        bad = [r for r in rows if r.get("module") == name and r["result"] != "achieved"]
        if not bad:
            continue
        lines += ["", f"## {name}", ""]
        for r in bad:
            lines.append(f"- **{r['result']}** {r.get('form')} v{r.get('version')} route {r.get('route')} "
                         f"-> {r.get('to')} ({r.get('kind', '')}): {r.get('reason')}")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("modules", nargs="*")
    ap.add_argument("--out", default=os.path.join(ROOT, "tmp", "release-reports", "evolutions"))
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    names = args.modules or audit.RELEASE_MODULES
    rows = crawl(names, args.quiet)
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "evolution_crawl.json"), "w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=1, ensure_ascii=False, default=str)
    with open(os.path.join(args.out, "evolution_crawl.md"), "w", encoding="utf-8") as fh:
        fh.write(markdown(rows, names))
    tally = collections.Counter(r["result"] for r in rows)
    print("total: " + ", ".join(f"{k} {v}" for k, v in sorted(tally.items())))
    return 1 if tally["impossible"] or tally["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
