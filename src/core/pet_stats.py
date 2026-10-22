"""Battle stats derived from a Digimon's species data and its care status.

These are the rules ``GamePet.get_power`` / ``get_hp`` apply, written as
plain functions so they can run without pygame or a loaded module registry.
The arena engine (``battle.arena.engine``) runs them on the Omninet server
against the server's own copy of each module, which is why nothing here may
import pygame, ``core.constants`` or the module registry.
"""

#: Highest level a Digimon of each stage can reach.
MAX_LEVEL = {0: 0, 1: 1, 2: 3, 3: 4, 4: 6, 5: 8, 6: 10, 7: 10, 8: 10}

#: Fallback HP for a species whose monster.json gives none.
HP_LEVEL = {
    0: 0,    # Egg
    1: 0,    # Fresh
    2: 10,   # In-Training
    3: 10,   # Rookie
    4: 12,   # Champion
    5: 15,   # Ultimate
    6: 18,   # Mega
    7: 20,   # Super Ultimate
    8: 20    # (If used, for extra stage)
}

# What a module written before traited_egg_rule / power_bonus_rule existed
# should fall back to, as ``ruleset -> (traited egg rule, power bonus rule)``.
# Chosen to reproduce what that ruleset already did, so an old module behaves
# the same way after the migration.
LEGACY_RULESET_RULES = {
    "dm":  ("Stage V Chance", "Stage Table"),
    "pen": ("Win Ratio (Stage 5)", "Stage Table + Shaken"),
    "dmx": ("Evolution Timer (Area 45)", "Strength and Level"),
    "vb":  ("None", "Star"),
}

#: Old ruleset spellings, normalised as GameModule does.
_RULESET_FIXES = {"dmc": "dm", "penc": "pen"}

#: Vital Values are capped per stage, not globally - a Child holds 4000
#: where an Ultimate holds 9999. Baby I and II fill the Child's pool: the
#: device keeps Vital Values from Stage I through Stage III and resets them
#: at every later evolution (humulos' VB and BE guides), and its Baby II
#: routes ask for up to 1200. The Child held 2500, below the 4000 the BE
#: cards ask of theirs (Ukkomon, Fumikage Tokoyami).
VITAL_VALUE_CAPS = {1: 4000, 2: 4000, 3: 4000, 4: 5000, 5: 7500, 6: 9999, 7: 9999, 8: 9999}

#: The forms whose Vital Values the next one keeps (Stage I -> II -> III).
VITAL_VALUES_CARRIED_FROM = (1, 2)

#: The weight at which the device stops paying the Strength Bonus. "If
#: your Digimon is at 99G for weight, or has no Hunger Hearts, the
#: Strength Bonus will be removed, reverting it to its base power" -- the
#: Ver.20th manual. It is the same 99 the weight meter itself caps at.
STRENGTH_BONUS_WEIGHT_CEILING = 99

#: Old ``power_bonus_rule`` names, and the rule each one is now. The plain
#: "Strength Hearts" became "Strength Hearts +16" when the Digimon Mini's
#: banded rule, "Strength Hearts +15", was added (2026-10-19); modules and
#: saved data written before that still say the old name.
POWER_RULE_ALIASES = {"Strength Hearts": "Strength Hearts +16"}

#: The Digimon Mini's Strength bonus on its 0-15 meter, as ``(lowest
#: Strength, power added)`` from the top band down: nothing at 0-3, then +4,
#: +8 and +15 at 4-7, 8-11 and 12-15. The bands are nhoko's; the sizes were
#: read on the wire, where a Centarumon fed up from an empty meter sent 50,
#: 54, 58 and 65 (utilities/DMM/protocol.txt, battles 25-28).
STRENGTH_BANDS_15 = ((12, 15), (8, 8), (4, 4))

#: Power added at full Strength Hearts, per stage, per power_bonus_rule.
#: Taken from the Power Bonus tables in each device's manual. The Traited
#: Egg column is the same figure again, granted independently.
POWER_STAGE_TABLES = {
    "Stage Table":            {3: 5, 4: 8, 5: 15, 6: 25, 7: 25, 8: 25},
    "Stage Table + Shaken":   {3: 5, 4: 8, 5: 15, 6: 20, 7: 20, 8: 20},
    "Stage Table Xros":       {3: 5, 4: 10, 5: 20},
    # The Pendulum Color Godzilla Edition: strength as Stage Table + Shaken,
    # a Traited Egg capped at +15, and Red G-Cells (PENGZ G-Cell style)
    # paying the strength table once more. No Shaken Egg.
    "Stage Table + G-Cells":  {3: 5, 4: 8, 5: 15, 6: 20, 7: 20, 8: 20},
}

#: Where a rule's Traited Egg pays its own table rather than the strength one.
POWER_TRAITED_TABLES = {
    "Stage Table + G-Cells":  {3: 5, 4: 8, 5: 15, 6: 15, 7: 15, 8: 15},
}


def canonical_power_bonus_rule(rule):
    """*rule* under its current name (`POWER_RULE_ALIASES`)."""
    return POWER_RULE_ALIASES.get(rule, rule)


def resolve_power_bonus_rule(module_data: dict) -> str:
    """The ``power_bonus_rule`` a module.json declares, or its legacy default."""
    ruleset = module_data.get("ruleset", "dm")
    ruleset = _RULESET_FIXES.get(ruleset, ruleset)
    legacy = LEGACY_RULESET_RULES.get(ruleset, LEGACY_RULESET_RULES["dm"])
    return canonical_power_bonus_rule(module_data.get("power_bonus_rule") or legacy[1])


def strength_cap(strength_max, stomach) -> int:
    """The most Strength protein can give a pet: the module's own
    ``care_strength_max`` where it sets one (the Digimon Mini's and the
    Twin's 0-15 meter), otherwise the pet's stomach, as every device had it
    before that field. Protein past the cap is still eaten, and still weighs;
    it just adds no Strength."""
    return int(strength_max) if strength_max and int(strength_max) > 0 else int(stomach or 0)


def drained_strength(strength, strength_max) -> int:
    """Strength after one ``strength_loss`` interval.

    A module without a cap of its own keeps the old rule: a meter fed past
    four hearts falls straight to 4 on the first drain, then one at a time,
    so the first loss of an overfull meter looks skipped (the owner's
    reading of the Color devices). A module with ``care_strength_max`` loses
    one point a drain all the way down, as the Digimon Twin does ("1 per
    60 min, fixed, on a 0-15 scale", nhoko); the Mini's rate is unmeasured
    and is taken to be the same.
    """
    strength = int(strength or 0)
    if strength <= 0:
        return 0
    if not strength_max and strength > 4:
        return 4
    return strength - 1


def strength_hearts(strength, strength_max, hearts=4) -> int:
    """How many of *hearts* a capped Strength meter lights: a share of the
    cap each, rounded up. On a 0-15 meter four hearts are the Mini's large
    band (12-15), three the medium (8-11), two the small (4-7) and one 1-3,
    so the hearts drop as the meter does instead of reading full until 4."""
    strength = int(strength or 0)
    if strength <= 0 or not strength_max:
        return max(0, strength)
    return min(hearts, -(-strength * hearts // int(strength_max)))


def parse_visible_stats(raw) -> list:
    """module.json's ``visible_stats``, which is a comma list or a list."""
    if isinstance(raw, str):
        return [s.strip() for s in raw.split(",") if s.strip()]
    if isinstance(raw, list):
        return raw
    return []


def tracks_vital_values(visible_stats) -> bool:
    """Whether a device has a Vital Values meter at all.

    Keyed on visible_stats, the same way Experience is, so a module that
    never shows the stat is untouched by anything built on it.
    """
    stats = [str(s).lower() for s in visible_stats or []]
    return any("vital" in s for s in stats)


def tracks_trophies(visible_stats) -> bool:
    """Whether a pet can earn trophies: its module shows "Trophies" (owner,
    2026-10-17). The Vital Bracelets do; a training run by a party that
    mixes devices gives them only to those pets."""
    return any(str(s).strip().lower() == "trophies" for s in visible_stats or [])


def tracks_strength(visible_stats) -> bool:
    """Whether a device has a Strength (vitamin) meter at all.

    Keyed on visible_stats, as Vital Values are. A device without one (the
    iC, DW1) never fills Strength, so its 0 must not count: no call, no care
    mistake, no drain, no death, and it must not hold back evolution.
    """
    return any(str(s).strip().lower() == "strength" for s in visible_stats or [])


def weight_floor(min_weight, allow_below_min) -> int:
    """The lowest weight losses can take a pet to: its species' min_weight,
    or 1 on a module with `care_allow_below_min_weight` (never below 0)."""
    floor = max(0, int(min_weight or 0))
    return min(floor, 1) if allow_below_min else floor


def vital_value_cap(stage) -> int:
    """The Vital Values ceiling for *stage*, or 0 where it earns none."""
    return VITAL_VALUE_CAPS.get(stage, 0)


def carried_vital_values(old_stage, new_stage, vital_values):
    """The Vital Values a form of *new_stage* starts with when one of
    *old_stage* holding *vital_values* evolves into it, or None when it starts
    afresh: only Stage I -> II and II -> III keep them."""
    if old_stage in VITAL_VALUES_CARRIED_FROM and new_stage == old_stage + 1:
        return min(int(vital_values or 0), vital_value_cap(new_stage))
    return None


def strength_bonus_blocked(weight, hunger) -> bool:
    """Whether the device is withholding the Strength Bonus.

    An overfed pet at the weight ceiling, or a starving one with no
    Hunger Hearts left, reverts to its base power however full its
    Strength meter is. From the Ver.20th manual, so it applies to the
    `Strength Hearts` rule -- which DM20, DMRV and PEN20 all declare.
    """
    return weight >= STRENGTH_BONUS_WEIGHT_CEILING or hunger <= 0


def hp_with_bonuses(hp, *, level, vital_values=0, vital_cap=0) -> int:
    """Species HP plus the level and Vital Values bonuses.

    *vital_cap* is 0 for a device without a Vital Values meter, which turns
    that bonus off. Item bonuses are the caller's to add.
    """
    # HP+2 at levels 2, 5, 6, 8 and 10 (+10 by max level), matching the
    # level table in the Digital Monster X manual.
    for milestone in (2, 5, 6, 8, 10):
        if level >= milestone:
            hp += 2

    # +2 HP for each quarter of the Vital Values bar that is filled, to a
    # maximum of +6, as the Vital Bracelet manual describes. The cap is
    # per stage, so a Child at its own maximum gets the full bonus.
    if vital_cap:
        quarters = int(vital_values * 4 // vital_cap)
        hp += 2 * max(0, min(3, quarters))
    return hp


def effort_tier_bonus(tiers, stage, effort) -> int:
    """The power the "Effort Tiers" rule adds: of the module's
    ``effort_power_tiers`` rows [stage, effort, power] for *stage* (stage 0:
    every stage), the one with the most effort at or below *effort* pays its
    power. Effort resets on evolving, so the tiers start over in each form."""
    best = None
    for row in tiers or []:
        try:
            row_stage, need, bonus = (int(v) for v in list(row)[:3])
        except (TypeError, ValueError):
            continue
        if row_stage in (0, int(stage or 0)) and int(effort or 0) >= need \
                and (best is None or need >= best[0]):
            best = (need, bonus)
    return best[1] if best else 0


def tick_poop_timers(timers, minutes):
    """The minutes each uncleaned poop has left before it costs its pet
    (module ``care_poop_mistake_time``), run down by *minutes*: returns
    (the timers still running, how many ran out)."""
    left = [int(t) - int(minutes) for t in timers or []]
    return [t for t in left if t > 0], sum(1 for t in left if t <= 0)


def effort_tier_level(tiers, stage, effort) -> int:
    """How many of *stage*'s effort tiers (the stage's own rows and the
    every-stage ones, by distinct effort) the pet has reached: 0 for none.
    The status screen colours the power by it."""
    reached = set()
    for row in tiers or []:
        try:
            row_stage, need, _bonus = (int(v) for v in list(row)[:3])
        except (TypeError, ValueError):
            continue
        if row_stage in (0, int(stage or 0)) and int(effort or 0) >= need:
            reached.add(need)
    return len(reached)


def power_with_bonus_rule(rule, power, *, stage, strength, stomach, hunger,
                          weight, level, version, effort, traited, shook,
                          star, gcell_red=False, effort_tiers=None,
                          strength_max=0):
    """Battle power: *power* (species base plus flat bonuses) under *rule*.

    ``power_bonus_rule`` on the module picks the formula:

      None                   base power only
      Stage Table            full Strength Hearts pay the stage table,
                             and a Traited Egg pays it again
      Stage Table + Shaken   the same, plus a flat +10 for a Shaken Egg
      Stage Table Xros       the same on the Xros Wars three-stage table
      Stage Table + G-Cells  the PENGZ's: strength table, Traited Egg on its
                             own table (to +15), Red G-Cells the strength
                             table again
      Strength and Level     full Strength Hearts plus a level bonus
      Strength Hearts +16    +4 per Strength Heart, +16 at full (DM20); the
                             old "Strength Hearts" is this rule
      Strength Hearts +15    the Digimon Mini's bands: +0 / +4 / +8 / +15
                             at Strength 0-3 / 4-7 / 8-11 / 12+
      Effort                 the hidden effort stat
      Effort Tiers           the module's *effort_tiers* table
                             (``effort_power_tiers``, `effort_tier_bonus`):
                             Digimon World's training, past 16
      Star                   base power plus 16 per star

    Every table is keyed on a *full* Strength meter, which is what the
    manuals say; this used to read ``effort``, and paid the Traited Egg
    only when that same condition held. Full is the module's
    *strength_max* where it sets one, else the stomach (`strength_cap`).
    *gcell_red* (PENGZ-style Red G-Cells, utils.gcell_rules.is_red) pays a
    stage table once more.
    """
    rule = canonical_power_bonus_rule(rule)
    full = strength_cap(strength_max, stomach)
    if rule == "None":
        return power

    if rule == "Star":
        # A pet with base power 70 and 10 stars comes out at 230.
        return int(power + (star or 0) * 16)

    if rule == "Strength Hearts +16":
        # "each Strength Heart adds 4 points to power, meaning you can
        # add a total of 16 power to your Digimon" - four hearts of four.
        # strength is the raw meter and `full` its capacity, so the
        # bonus is scaled off how full it is rather than counted directly.
        #
        # And the device takes the whole bonus away when the pet is
        # neglected: "if your Digimon is at 99G for weight, or has no
        # Hunger Hearts, the Strength Bonus will be removed, reverting it
        # to its base power". Not reduced - removed, however full the
        # Strength meter is.
        if full and not strength_bonus_blocked(weight, hunger):
            power += min(16, (16 * strength) // full)
        return power

    if rule == "Strength Hearts +15":
        # The raw meter picks the band, so a module on this rule sets
        # care_strength_max 15 to reach the top one. No source says whether
        # the Mini withholds the bonus at 99 g or on an empty stomach the way
        # the Ver.20th does, so it does not here.
        for lowest, bonus in STRENGTH_BANDS_15:
            if strength >= lowest:
                return power + bonus
        return power

    if rule == "Strength and Level":
        # The X manual ties this to a full strength meter, and gives +16
        # on XA/XB against +15 on XC through XF.
        if full and strength >= full:
            # The manual names the DEVICES -- XA and XB against XC to XF
            # -- and on the X those are versions 1 and 2 either way, so
            # the gameplay version answers it and keeps answering it.
            # `device_version` does not: the Pendulum Z shares this rule
            # and its devices are numbered 6-11, because that is what it
            # announces on the wire. Reading the version leaves both
            # lines exactly as they were.
            power += 16 if int(version or 0) in (1, 2) else 15
        for milestone in (3, 6, 9):
            if level >= milestone:
                power += 10
        return power

    if rule == "Effort Tiers":
        return power + effort_tier_bonus(effort_tiers, stage, effort)

    if rule == "Effort":
        # The original Pendulum's effort is a hidden 0-40 battle stat the
        # manual never puts a table to; this keeps the shape the device
        # has always been played with here.
        if effort >= 16:
            power += POWER_STAGE_TABLES["Stage Table + Shaken"].get(stage, 0)
        return power

    table = POWER_STAGE_TABLES.get(rule)
    if table is None:
        return power
    step = table.get(stage, 0)
    if full and strength >= full:
        power += step
    if traited:
        power += POWER_TRAITED_TABLES.get(rule, table).get(stage, 0)
    if gcell_red:
        power += step
    if rule == "Stage Table + Shaken" and shook:
        power += 10
    return power
