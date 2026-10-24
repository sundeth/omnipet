"""
Sickness and injury, counted apart (owner, 2026-10-21; the plan in
utilities/claude/docs/sickness-injury-split-plan.md). Shared by the game
(GamePet) and the Android offline copy (services/android_pet_rules), as
evolution_rules and lifespan_rules are.

  Pet values
    sick                doses of medicine the sickness (Dots) still needs;
                        0: not sick
    injury              doses the injury (Skull) still needs; 0: not injured
    sick_total          sicknesses in this form
    injury_total        injuries in this form
    care_sick_mistake_timer    awake minutes sick, untreated
    care_injury_mistake_timer  awake minutes injured, untreated

  One ailment at a time: a sick pet is not injured on top, nor the other
  way round (the Pendulum manuals: "you choose which one your Digimon
  has"). A form whose heal_doses is 0 takes neither. Both totals and timers
  reset on evolution (every manual: "in one form").

  What makes which (the module's effect fields: Dots is a sickness, Skull an
  injury, Nothing or Burpmon none)
    care_poop_sickness_effect         the poop pile
    care_99g_effect                   reaching 99 G
    care_disturbance_sickness_effect  every Nth sleep disturbance
    every battle roll                 an injury (battle_base_sick_chance_*,
                                      the protein and disturbance penalties
                                      and the species' injury_probability).
                                      No battle spreads a sickness (owner:
                                      never seen on a device)

  Module fields
    death_max_injuries     injuries in one form that kill; 0: none
    death_max_sicknesses   sicknesses in one form that kill; 0: none
    death_sick_timer       minutes sick and awake, untreated, that kill
    death_injury_timer     minutes injured and awake, untreated, that kill
    care_can_battle_while_sick / _injured, care_can_train_while_sick /
    _injured           what each ailment still allows
  A module from before the split lacks the new four: the loader gives each
  its old counterpart's value (models.game_module), and rules code reads
  them through the functions here, which do the same for test stand-ins.

Anything that asks "is the pet unwell?" (calls, the evolution wait, Vital
Values, the screensaver, the wire's sick flag) asks `ailing`.
"""

KINDS = ("sick", "injury")
TOTALS = {"sick": "sick_total", "injury": "injury_total"}
TIMERS = {"sick": "care_sick_mistake_timer", "injury": "care_injury_mistake_timer"}
#: The overlay each kind shows, and the effect-field value naming it.
EFFECTS = {"Dots": "sick", "Skull": "injury"}
#: death_cause names: a count reached, or an ailment left untreated.
COUNT_CAUSES = {"sick": "sicknesses", "injury": "injuries"}
TIMER_CAUSES = {"sick": "sickness", "injury": "injury"}


def doses(obj, kind):
    """Doses left on *obj*'s ailment of *kind* (0 when it has none)."""
    return int(getattr(obj, kind, 0) or 0)


def ailing(obj):
    """Whether *obj* is sick or injured. Works on anything carrying either
    field: a pet, an offline pet, a battle enemy."""
    return doses(obj, "sick") > 0 or doses(obj, "injury") > 0


def kind_of(obj):
    """"sick", "injury" or None."""
    if doses(obj, "sick") > 0:
        return "sick"
    if doses(obj, "injury") > 0:
        return "injury"
    return None


#: Effect values that give no ailment.
NO_AILMENT = ("Nothing", "Burpmon", "", None)


def kind_for_effect(effect):
    """The ailment an effect field's value gives: Dots "sick", Nothing (or
    Burpmon) None, and Skull, or any other value, "injury" (as before)."""
    if effect in NO_AILMENT:
        return None
    return EFFECTS.get(effect, "injury")


def onset(pet, kind):
    """*pet* falls sick or is injured: its doses come from heal_doses and
    the kind's total goes up. Refused (False) while it already has an
    ailment, and for a form that cannot take one (heal_doses 0)."""
    if kind not in KINDS or ailing(pet):
        return False
    heal = int(getattr(pet, "heal_doses", 0) or 0)
    if heal <= 0:
        return False
    setattr(pet, kind, heal)
    total = TOTALS[kind]
    setattr(pet, total, int(getattr(pet, total, 0) or 0) + 1)
    return True


def heal_dose(pet, kind=None):
    """One dose of medicine for *pet*'s ailment of *kind* (None: whichever
    it has). The doses still needed."""
    kind = kind or kind_of(pet)
    if kind is None or doses(pet, kind) <= 0:
        return 0
    left = doses(pet, kind) - 1
    setattr(pet, kind, left)
    return left


def cure(pet, kind=None):
    """Heal *pet*'s ailment of *kind* outright (None: either). True when
    there was one to heal."""
    cured = False
    for k in (KINDS if kind is None else (kind,)):
        if doses(pet, k) > 0:
            setattr(pet, k, 0)
            cured = True
    return cured


# ----------------------------------------------------------------------------
# Module values (each defaults to its pre-split counterpart)
# ----------------------------------------------------------------------------

def death_max(module, kind):
    """The count of *kind* in one form that kills; 0: none."""
    injuries = int(getattr(module, "death_max_injuries", 0) or 0)
    if kind == "injury":
        return injuries
    return int(getattr(module, "death_max_sicknesses", injuries) or 0)


def death_timer(module, kind):
    """Awake minutes of untreated *kind* that kill; 0: none."""
    sick = int(getattr(module, "death_sick_timer", 0) or 0)
    if kind == "sick":
        return sick
    return int(getattr(module, "death_injury_timer", sick) or 0)


def allows_battle(module, kind):
    sick = bool(getattr(module, "care_can_battle_while_sick", False))
    return sick if kind == "sick" else bool(getattr(module, "care_can_battle_while_injured", sick))


def allows_training(module, kind):
    sick = bool(getattr(module, "care_can_train_while_sick", False))
    return sick if kind == "sick" else bool(getattr(module, "care_can_train_while_injured", sick))


def blocks_battle(pet, module):
    """The ailment that keeps *pet* from battling, or None."""
    kind = kind_of(pet)
    return kind if kind and not allows_battle(module, kind) else None


def blocks_training(pet, module):
    kind = kind_of(pet)
    return kind if kind and not allows_training(module, kind) else None


# ----------------------------------------------------------------------------
# Untreated timers, death and the death save
# ----------------------------------------------------------------------------

def tick_timers(pet, sleeping):
    """One awake minute: each ailment's untreated timer counts while the pet
    has it and is awake (paused asleep), and is 0 once healed."""
    for kind, timer in TIMERS.items():
        if doses(pet, kind) > 0:
            if not sleeping:
                setattr(pet, timer, int(getattr(pet, timer, 0) or 0) + 1)
        else:
            setattr(pet, timer, 0)


def death_cause(pet, module):
    """What the ailments kill *pet* of now, or "": a count reached
    ("injuries", "sicknesses") or an ailment left untreated too long
    ("sickness", "injury"; these win, as the timer always did)."""
    cause = ""
    for kind in ("injury", "sick"):
        limit = death_max(module, kind)
        if limit > 0 and int(getattr(pet, TOTALS[kind], 0) or 0) >= limit:
            cause = COUNT_CAUSES[kind]
    for kind in ("sick", "injury"):
        limit = death_timer(module, kind)
        if limit > 0 and int(getattr(pet, TIMERS[kind], 0) or 0) > limit:
            cause = TIMER_CAUSES[kind]
    return cause


def undo(pet, cause):
    """A death save from *cause*: one count back, or the untreated ailment
    healed. True when *cause* was an ailment's."""
    for kind in KINDS:
        if cause == COUNT_CAUSES[kind]:
            total = TOTALS[kind]
            setattr(pet, total, max(0, int(getattr(pet, total, 0) or 0) - 1))
            return True
        if cause == TIMER_CAUSES[kind]:
            setattr(pet, kind, 0)
            setattr(pet, TIMERS[kind], 0)
            return True
    return False


def reset(pet):
    """A new form: no ailment, no counts, no timers."""
    for kind in KINDS:
        setattr(pet, kind, 0)
        setattr(pet, TOTALS[kind], 0)
        setattr(pet, TIMERS[kind], 0)


# ----------------------------------------------------------------------------
# Saves from before the split
# ----------------------------------------------------------------------------

def migrate(state):
    """Bring a pet's state (its __dict__, or a saved dict) from the one
    count to the two. Before, `sick` held either ailment's doses, its
    `sick_type` "dots" for Dots and anything else for Skull, and `injuries`
    counted both. The doses go to their kind (a Skull's untreated minutes
    with them), the count all to injury_total (it can only be lower than
    the old combined total against the same threshold), and a death save
    under way for an untreated Skull becomes the injury's. Idempotent: a
    state that has sick_total is left alone. True when it changed."""
    if "sick_total" in state:
        state.pop("injuries", None)  # the copy written for older builds
        state.pop("sick_type", None)
        return False
    doses_left = int(state.get("sick", 0) or 0)
    dots = state.get("sick_type", "") == "dots"
    timer = int(state.get("care_sick_mistake_timer", 0) or 0)
    if doses_left > 0 and not dots:
        state["sick"], state["injury"] = 0, doses_left
        state["care_injury_mistake_timer"], state["care_sick_mistake_timer"] = timer, 0
        if state.get("death_cause") == "sickness":
            state["death_cause"] = "injury"
    else:
        state["sick"] = doses_left
        state["injury"] = 0
        state["care_injury_mistake_timer"] = 0
        if doses_left <= 0:
            state["care_sick_mistake_timer"] = 0
    state["injury_total"] = int(state.pop("injuries", 0) or 0)
    state["sick_total"] = 0
    state.pop("sick_type", None)
    return True
