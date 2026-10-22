"""
G-Cells in the module's style (module.json ``gcell_style``), shared by the
game (GamePet) and the Android offline copy (AndroidPetRules).

  Disabled   no G-Cells.
  DMGZ       the Digital Monster COLOR Godzilla 70th Edition's meter: 0-472
             points at every stage; 14 Blue cells of 8 points, then 10 Yellow
             and 20 Red of 12 (levels 1-4); one flat gain per action
             (gcell_battle_win, gcell_care_mistake, ...).
  PENGZ      the Pendulum Color Godzilla Edition's: 14 cells whose size is
             the stage's (gcell_points_per_cell: 2/2/4/8/16/16/16 points for
             I-VI+), a partial cell counting as one; 0-7 cells Blue, 8-14
             Red. Gains by stage for a care mistake or an empty-strength
             call, a battle in this module's adventure or against one of its
             own pets, and a random encounter; flat ones for protein,
             training (gcell_training_gain by grade) and a versus against
             another module's pet. Red adds the power table's stage bonus
             again (core.pet_stats).

A module from before ``gcell_style`` reads ``use_gcells``: true is DMGZ.
Points reset on evolution in both styles. The evolution criterion ``gcells``
reads `cells`; ``blue_/yellow_/red_gcells`` and ``gcell_level`` read the
DMGZ meter.
"""

DISABLED, DMGZ, PENGZ = "Disabled", "DMGZ", "PENGZ"
STYLES = (DISABLED, DMGZ, PENGZ)

DMGZ_MAX_POINTS = 472
PENGZ_CELLS = 14
PENGZ_RED_FROM = 8

# PENGZ defaults, indexed by Omnipet stage (0 the egg ... 8): its manual's
# tables for I-II / III / IV / V / VI / VI+. The manual also gives random
# encounters a flat +12 / -6; the per-stage table is taken here.
DEFAULT_POINTS_PER_CELL = [2, 2, 2, 4, 8, 16, 16, 16, 16]
DEFAULT_CARE_MISTAKE_BY_STAGE = [0, -1, -1, -1, -2, -4, -4, -4, -4]
DEFAULT_BATTLE_WIN_BY_STAGE = [0, 0, 0, 4, 6, 8, 10, 0, 0]
DEFAULT_BATTLE_LOSS_BY_STAGE = [0, 0, 0, -3, -4, -6, -8, 0, 0]
DEFAULT_ENCOUNTER_WIN_BY_STAGE = [0, 0, 0, 6, 12, 24, 32, 0, 0]
DEFAULT_ENCOUNTER_LOSS_BY_STAGE = [0, 0, 0, -4, -8, -16, -24, 0, 0]
#: Training by grade: Bad (0 supers), Good (1-2), Great (3-4), Excellent
#: (Megahit).
DEFAULT_TRAINING_GAIN = [-1, 0, 1, 2]
#: The same with Anguirus, every fifth training (utils.pengz_count_match).
DEFAULT_TRAINING_GAIN_ANGUIRUS = [-2, 0, 4, 8]
DEFAULT_OTHER_DEVICE_WIN = 6
DEFAULT_OTHER_DEVICE_LOSS = -4


def style_of(module):
    style = getattr(module, "gcell_style", None)
    if style in STYLES:
        return style
    return DMGZ if getattr(module, "use_gcells", False) else DISABLED


def read_style(data):
    """``gcell_style`` from module.json data, or what ``use_gcells`` meant."""
    style = data.get("gcell_style")
    if style in STYLES:
        return style
    return DMGZ if data.get("use_gcells") else DISABLED


def stage_table(value, default):
    """A by-stage list (0-8) from module data: padded with its last value,
    or *default* when absent or unreadable."""
    try:
        table = [int(v) for v in value] if isinstance(value, list) and value else None
    except (TypeError, ValueError):
        table = None
    if not table:
        return list(default)
    return (table + [table[-1]] * 9)[:max(9, len(table))]


def _at(table, stage):
    if not table:
        return 0
    return int(table[max(0, min(len(table) - 1, int(stage or 0)))])


def points_per_cell(module, stage):
    return max(1, _at(getattr(module, "gcell_points_per_cell", None)
                      or DEFAULT_POINTS_PER_CELL, stage))


def max_points(module, stage):
    if style_of(module) == PENGZ:
        return PENGZ_CELLS * points_per_cell(module, stage)
    return DMGZ_MAX_POINTS


def cells(module, pet):
    """The pet's G-Cells: PENGZ's 0-14 (a partial cell counts), DMGZ's
    Blue + Yellow + Red, or 0."""
    style = style_of(module)
    points = max(0, getattr(pet, "gcell_points", 0) or 0)
    if style == PENGZ:
        per = points_per_cell(module, getattr(pet, "stage", 0))
        return min(PENGZ_CELLS, -(-points // per))
    if style == DMGZ:
        return pet.get_blue_gcells() + pet.get_yellow_gcells() + pet.get_red_gcells()
    return 0


def is_red(module, pet):
    """PENGZ's Red ("activated") G-Cells: 8 or more."""
    return style_of(module) == PENGZ and cells(module, pet) >= PENGZ_RED_FROM


def gain(module, pet, event, *, won=False, grade=0, phase2=False, special=False,
         other_device=False, anguirus=False):
    """The points an event gives, in the module's style.

    *event*: "care_mistake", "empty_strength" (the strength call starts),
    "protein", "training" (*won*, *grade* 0-3, *phase2*, *anguirus*) or "battle" (*won*;
    *special* a random encounter; *other_device* a versus against another
    module's pet)."""
    style = style_of(module)
    if style == DISABLED:
        return 0
    get = lambda name, default=0: getattr(module, name, default)
    if style == DMGZ:
        if event == "care_mistake":
            return int(get("gcell_care_mistake"))
        if event == "protein":
            return int(get("gcell_protein"))
        if event == "training":
            if won:
                return int(get("gcell_training_success"))
            return int(get("gcell_training_phase2_failure" if phase2
                           else "gcell_training_phase1_failure"))
        if event == "battle":
            if special:
                return int(get("gcell_random_encounter_win" if won
                               else "gcell_random_encounter_loose"))
            return int(get("gcell_battle_win" if won else "gcell_battle_loose"))
        return 0

    stage = getattr(pet, "stage", 0)
    if event in ("care_mistake", "empty_strength"):
        return _at(get("gcell_care_mistake_by_stage", DEFAULT_CARE_MISTAKE_BY_STAGE), stage)
    if event == "protein":
        return int(get("gcell_protein"))
    if event == "training":
        table = (get("gcell_training_gain_anguirus", DEFAULT_TRAINING_GAIN_ANGUIRUS)
                 or DEFAULT_TRAINING_GAIN_ANGUIRUS) if anguirus else (
                 get("gcell_training_gain", DEFAULT_TRAINING_GAIN) or DEFAULT_TRAINING_GAIN)
        # The grade's row, won or lost, as GamePet.finish_training pays the
        # care tables (only Mogera's lost Phase 2 has a grade above Bad)
        level = max(0, min(3, int(grade)))
        return int(table[min(level, len(table) - 1)])
    if event == "battle":
        if special:
            name = "gcell_random_encounter_win_by_stage" if won else "gcell_random_encounter_loss_by_stage"
            default = DEFAULT_ENCOUNTER_WIN_BY_STAGE if won else DEFAULT_ENCOUNTER_LOSS_BY_STAGE
            return _at(get(name, default), stage)
        if other_device:
            return int(get("gcell_other_device_win", DEFAULT_OTHER_DEVICE_WIN) if won
                       else get("gcell_other_device_loss", DEFAULT_OTHER_DEVICE_LOSS))
        name = "gcell_battle_win_by_stage" if won else "gcell_battle_loss_by_stage"
        default = DEFAULT_BATTLE_WIN_BY_STAGE if won else DEFAULT_BATTLE_LOSS_BY_STAGE
        return _at(get(name, default), stage)
    return 0


def add_points(module, pet, points):
    """Add *points*, kept within 0 and the style's cap. Returns the change."""
    old = getattr(pet, "gcell_points", 0) or 0
    pet.gcell_points = max(0, min(max_points(module, getattr(pet, "stage", 0)), old + points))
    return pet.gcell_points - old


def display_cells(module, pet):
    """The status bar's 14 cells, as "empty" / "blue" / "yellow" / "red";
    None to draw the DMGZ meter."""
    if style_of(module) != PENGZ:
        return None
    count = cells(module, pet)
    colour = "red" if count >= PENGZ_RED_FROM else "blue"
    return [colour if i < count else "empty" for i in range(PENGZ_CELLS)]
