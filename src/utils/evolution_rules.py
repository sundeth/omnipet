"""
Evolution rules shared by the game (GamePet) and the Android offline copy
(services/android_pet_rules.AndroidPetRules).

Added for the Pendulum Color Godzilla Edition (2026-10), and written for any
module that wants them:

  Route criteria
    poops               [min, max] poops on screen when the route is checked
    total_battles       [min, max] battles over the pet's whole life
    total_win_ratio     [min, max] win ratio over the pet's whole life
    defeat_tag          a tag (monster.json ``tags``) the pet must defeat ...
    defeat_tag_amount   ... [min, max] times in this form; such a route is
                        tried at once, not on the evolution timer
    at_death            a percent: the route is tried only when the pet dies,
                        and taken with that chance instead of the death
    form_minutes        [min, max] minutes in the current form, asleep or
                        awake (Digimon World's Vademon: 240 hours as an Adult)
    virus               [min, max] the pet's virus: poops left uncleaned past
                        the module's care_poop_mistake_time, over its life.
                        Such a route is tried at once, not on the timer, and
                        taking it spends the virus (World's Sukamon at 16)
    unlock              a module unlock (module.json ``unlocks`` name) the
                        player must hold: progress any Digimon makes. DMGZ's
                        Koromon cannot fight, so its area-7 routes ask for
                        the unlock clearing area 7 grants (owner, 2026-10-15)

  Module fields
    evolution_win_ratio_chance   [[min ratio, chance %], ...]: the chance a
                        route with a win-ratio criterion is taken, by the
                        pet's ratio (the highest row at or below it). Default
                        [[0, 100]]: always, as before.
    failed_evolution_double_needs  once an evolution has failed, hunger and
                        strength drain and poop comes twice as fast, and so
                        at Stage VI+ after 48 hours in the form (the
                        Pendulum Color and Godzilla manuals).

  Failed evolutions (every module; owner, 2026-10-20)
    A pet with a route that reads the win rate (``win_ratio``,
    ``total_win_ratio``) gets one try when its timer runs out: if no route is
    taken it never evolves on the timer again (``evolution_failed``). Items,
    Level Reverse, jogress and armor evolutions, death routes and defeat
    routes still change it, and any new form starts unfailed.

  Form time (every module)
    form_minutes        minutes in the current form, asleep or awake; the
                        "48 hours in this form" rules of Stage VI and up.
"""

UNBOUNDED = 999999
FORM_48_HOURS = 2880
DEFAULT_WIN_RATIO_CHANCE = [[0, 100]]

#: Criteria that read the battle record.
BATTLE_RECORD_KEYS = ("battles", "win_ratio", "win_count", "total_battles", "total_win_ratio")
#: Criteria that read the win rate: a pet with a route using one fails for
#: good when the timer's try takes no route.
WIN_RATE_KEYS = ("win_ratio", "total_win_ratio")


def in_range(value, bounds):
    return bounds[0] <= value <= bounds[1]


def total_win_ratio(pet):
    battles = getattr(pet, "totalBattles", 0) or 0
    return (getattr(pet, "totalWin", 0) or 0) * 100 // battles if battles else 0


# --------------------------------------------------------------------------
# Route kinds
# --------------------------------------------------------------------------

def is_death_route(evo):
    """A route tried only when the pet dies."""
    try:
        return int(evo.get("at_death") or 0) > 0
    except (TypeError, ValueError):
        return False


def is_immediate_route(evo):
    """A route tried at once (every minute and after battles), not on the
    evolution timer: a defeat count, or a virus count."""
    return bool(evo.get("defeat_tag")) or "virus" in evo


def uses_battle_record(evo):
    return any(key in evo for key in BATTLE_RECORD_KEYS)


def uses_win_rate(evo):
    return any(key in evo for key in WIN_RATE_KEYS)


def route_wanted(evo, kind):
    """Whether a route belongs to this kind of check: "normal" (the timer),
    "immediate" (defeat counts) or "death"."""
    if kind == "death":
        return is_death_route(evo)
    if is_death_route(evo):
        return False
    if kind == "immediate":
        return is_immediate_route(evo)
    return True


# --------------------------------------------------------------------------
# Criteria
# --------------------------------------------------------------------------

def extra_criteria_fail(pet, evo, poops_on_screen):
    """True when one of this module's added criteria is not met."""
    if "total_battles" in evo and not in_range(getattr(pet, "totalBattles", 0) or 0,
                                               evo["total_battles"]):
        return True
    # As win_ratio: only tested once the pet has fought.
    if ("total_win_ratio" in evo and (getattr(pet, "totalBattles", 0) or 0)
            and not in_range(total_win_ratio(pet), evo["total_win_ratio"])):
        return True
    if "poops" in evo and not in_range(poops_on_screen, evo["poops"]):
        return True
    if "form_minutes" in evo and not in_range(getattr(pet, "form_minutes", 0) or 0,
                                              evo["form_minutes"]):
        return True
    if "virus" in evo and not in_range(getattr(pet, "virus", 0) or 0, evo["virus"]):
        return True
    if evo.get("defeat_tag"):
        amount = evo.get("defeat_tag_amount") or [1, UNBOUNDED]
        defeats = (getattr(pet, "tag_defeats", None) or {}).get(evo["defeat_tag"], 0)
        if not in_range(defeats, amount):
            return True
    if evo.get("unlock") and not unlock_held(pet, evo["unlock"]):
        return True
    return False


def unlock_held(pet, name):
    """Whether the player holds module unlock *name* for the pet's module: the
    Android copy asks its world, the game the save (utils_unlocks)."""
    world = getattr(pet, "world", None)
    if world is not None and hasattr(world, "is_unlocked"):
        return bool(world.is_unlocked(pet.module, None, name))
    from utils.utils_unlocks import is_unlocked
    return is_unlocked(pet.module, None, name)


def win_ratio_chance(module, pet, evo):
    """The percent chance the module's table gives this route (100 when the
    route has no win-ratio criterion or the pet has not fought)."""
    if "total_win_ratio" in evo:
        if not (getattr(pet, "totalBattles", 0) or 0):
            return 100
        ratio = total_win_ratio(pet)
    elif "win_ratio" in evo:
        battles = getattr(pet, "battles", 0) or 0
        if not battles:
            return 100
        ratio = (getattr(pet, "win", 0) or 0) * 100 // battles
    else:
        return 100
    table = getattr(module, "evolution_win_ratio_chance", None) or DEFAULT_WIN_RATIO_CHANCE
    best = None
    for row in table:
        try:
            low, chance = int(row[0]), int(row[1])
        except (TypeError, ValueError, IndexError):
            continue
        if ratio >= low and (best is None or low > best[0]):
            best = (low, chance)
    return best[1] if best else 0


def once(roll):
    """*roll*, drawn the first time and repeated after: the table's roll is
    one per evolution check, so a pet meeting two routes is not given two
    chances (the device decides once)."""
    drawn = []

    def again():
        if not drawn:
            drawn.append(roll())
        return drawn[0]
    return again


def rolls_fail(module, pet, evo, roll, kind, table_roll=None):
    """The rolls a route makes after its criteria pass: the module's
    win-ratio table (*table_roll*, one per check: see `once`), then the
    death chance (*roll*). Each returns 0-100."""
    chance = win_ratio_chance(module, pet, evo)
    if chance < 100 and (table_roll or roll)() >= chance:
        return True
    if kind == "death" and roll() >= int(evo.get("at_death") or 0):
        return True
    return False


# --------------------------------------------------------------------------
# Failure and form time
# --------------------------------------------------------------------------

def doubles_needs(module):
    return bool(getattr(module, "failed_evolution_double_needs", False))


def should_fail(routes):
    """After the timer's try took no route: whether the pet now never
    evolves on the timer (it has a route that reads the win rate)."""
    return any(route_wanted(evo, "normal") and not is_immediate_route(evo)
               and not evo.get("jogress") and "item" not in evo
               and uses_win_rate(evo) for evo in routes)


# --------------------------------------------------------------------------
# Generations (traited_egg_rule "Generation": the Digivice iC)
# --------------------------------------------------------------------------

#: The most a generation gives: from the second generation on, each Child or
#: later form evolves an hour earlier and the pet starts with a point more
#: Reliability per generation, up to eight (the 10X playbook).
GENERATION_BONUS_MAX = 8


def generation_bonus(module, pet):
    """The hours and Reliability points *pet*'s generation gives, 0-8; 0 on
    a module whose Traited Egg rule is not "Generation"."""
    if getattr(module, "traited_egg_rule", "") != "Generation":
        return 0
    return max(0, min(GENERATION_BONUS_MAX, (getattr(pet, "generation", 1) or 1) - 1))


def generation_time(module, pet, stage, minutes):
    """A form's evolution time, shortened by its generation from Child on."""
    bonus = generation_bonus(module, pet)
    if not bonus or (stage or 0) < 3 or not minutes:
        return minutes
    return max(1, minutes - 60 * bonus)


def form_aged(pet, minutes=FORM_48_HOURS):
    return (getattr(pet, "form_minutes", 0) or 0) >= minutes


def poop_factor(pet, module):
    """Poop runs twice as fast at Stage VI+ after 48 hours in the form, and
    (where the module doubles needs) once an evolution has failed."""
    if getattr(pet, "stage", 0) >= 6 and form_aged(pet):
        return 2
    if doubles_needs(module) and getattr(pet, "evolution_failed", False):
        return 2
    return 1


def needs_factor(pet, module):
    """Hunger and strength drain twice as fast, on a module that doubles
    needs, once an evolution has failed or at Stage VI+ after 48 hours."""
    if not doubles_needs(module):
        return 1
    if getattr(pet, "evolution_failed", False):
        return 2
    if getattr(pet, "stage", 0) >= 6 and form_aged(pet):
        return 2
    return 1


# --------------------------------------------------------------------------
# Tags and defeats
# --------------------------------------------------------------------------

def tags_of(module, name, version=None):
    """A species' ``tags`` in a module's monster.json (empty when none)."""
    if module is None or not name:
        return []
    record = None
    finder = getattr(module, "find_monster", None)
    if finder is not None:
        record = finder(name, version)
    elif version is not None:
        record = module.get_monster(name, version)
    tags = (record or {}).get("tags") or []
    return [str(t) for t in tags] if isinstance(tags, list) else [str(tags)]


def record_defeat(pet, module, name, version=None):
    """Count a defeated opponent's tags on the pet, for ``defeat_tag``."""
    tags = tags_of(module, name, version)
    if not tags:
        return
    counts = getattr(pet, "tag_defeats", None)
    if counts is None:
        counts = {}
        pet.tag_defeats = counts
    for tag in tags:
        counts[tag] = counts.get(tag, 0) + 1
