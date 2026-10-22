"""
The module's lifespan rule (``lifespan_rule``; owner, 2026-10-21), shared by
the game (GamePet) and the Android offline copy
(services/android_pet_rules.AndroidPetRules).

One combo names how a pet's life ends, as the Traited Egg rules do: the
numbers come from data the module already has, or from the rule itself.

  None           no death of old age; pets live on (most modules, among
                 them the DMM, the XWM and the Digimon Twin)
  Activity Time  the Digivice iC: a form that cannot evolve two hours after
                 its evolution time (``time``, on the evolution timer) goes
                 near-death, through the module's death save; a form with no
                 evolution time (the Ultimates) at 144 hours. A saved pet
                 gets the save's hour and goes near-death again unless it
                 has evolved by then
  Old Age        Digimon World: dies ``death_old_age`` days into its life,
                 and cannot be saved
  Age 5          the Xros Wars Color: from 5 days old Hunger drains and poop
                 comes twice as fast, and 16 care mistakes in one form kill
                 (through the save)
  Evolution Window (Stage V+) / (Stage IV+)
                 the Digital Monster X / the Pendulum Z: from that stage, a
                 form evolves only when its evolution time comes; if no route
                 is met then, it has failed for good (it can still jogress,
                 and evolution_failed brings the module's faster needs). The
                 X fails at Stage VI and VI+ (from V), the Z at V, VI and VI+
                 (from IV): "within 32, 40 or 48 hours of your most recent
                 evolution" (humulos' manuals)

A module from before names only ``death_old_age``: over 0, it reads as Old
Age (models.game_module).

``life_minutes`` is the pet's own clock: minutes lived, asleep and awake,
ticked by the per-minute block while it is not dead. A pet in the Freezer,
or in a closed desktop game, does not age. Old saves start it at their
``age`` in days (GamePet.patch).
"""

RULES = ("None", "Activity Time", "Old Age", "Age 5",
         "Evolution Window (Stage IV+)", "Evolution Window (Stage V+)")
#: Evolution Window rules: the first stage whose evolution time is its only try.
WINDOW_STAGES = {"Evolution Window (Stage IV+)": 4, "Evolution Window (Stage V+)": 5}

#: Activity Time: minutes past the evolution time a form has left to evolve,
#: and the lifespan of a form without one (the iC's Ultimates).
ACTIVITY_GRACE = 120
ACTIVITY_NO_TIME = 144 * 60

#: Age 5: the age, in days, and the care mistakes in one form that kill.
AGE_5_DAYS = 5
AGE_5_MISTAKES = 16

DAY = 24 * 60


def rule(module):
    """The module's lifespan rule, "None" for an unknown one."""
    name = getattr(module, "lifespan_rule", "None") or "None"
    return name if name in RULES else "None"


def lived(pet, days):
    """Whether *pet* has lived *days* days on its own clock."""
    return (getattr(pet, "life_minutes", 0) or 0) >= days * DAY


def activity_deadline(pet):
    """Activity Time: the evolution-timer minute the form's lifespan ends."""
    time = getattr(pet, "time", 0) or 0
    return time + ACTIVITY_GRACE if time > 0 else ACTIVITY_NO_TIME


def death_cause(pet, module, can_evolve):
    """The cause the module's rule kills *pet* with now: "lifespan",
    "old_age", "care_mistakes", or "" for none. *can_evolve* is asked only
    when the Activity Time lifespan is over: True when a normal route is met
    now (the pet would evolve once its calls are answered)."""
    name = rule(module)
    if name == "Activity Time":
        if (pet.stage > 0 and (getattr(pet, "_evol_minutes", 0) or 0) >= activity_deadline(pet)
                and not can_evolve()):
            return "lifespan"
    elif name == "Old Age":
        days = int(getattr(module, "death_old_age", 0) or 0)
        if days > 0 and lived(pet, days):
            return "old_age"
    elif name == "Age 5":
        if lived(pet, AGE_5_DAYS) and (getattr(pet, "mistakes", 0) or 0) >= AGE_5_MISTAKES:
            return "care_mistakes"
    return ""


def closes_evolution(pet, module):
    """Whether this form's timer check, no route met, fails it for good: an
    Evolution Window rule from the form's stage on, for a form that has a
    route to take on its timer (a last form has none to fail)."""
    from utils import evolution_rules
    first = WINDOW_STAGES.get(rule(module))
    if first is None or (getattr(pet, "stage", 0) or 0) < first:
        return False
    return any(evolution_rules.route_wanted(evo, "normal") and not evolution_rules.is_immediate_route(evo)
               and not evo.get("jogress") and "item" not in evo
               for evo in (getattr(pet, "evolve", None) or []))


def needs_factor(pet, module):
    """How much faster Hunger drains and poop comes: 2 from Age 5, else 1."""
    return 2 if rule(module) == "Age 5" and lived(pet, AGE_5_DAYS) else 1
