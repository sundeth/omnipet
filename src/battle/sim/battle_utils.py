import json
import random
import os


def _load_json(file_path):
    """Load a JSON file directly.

    Paths here are built from __file__ and are already absolute, so no
    Android APP_ROOT resolution is needed. (The old optional import of
    utils.asset_utils.open_json had a broken fallback that returned parsed
    JSON where a file handle was expected, crashing any standalone use.)
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)


DMX_PATTERN_TABLE = None

#: One loaded table per device line on this wire. DMX's was measured; the
#: others still read the pre-measurement copy under their own name.
_PATTERN_TABLES = {}


def _pattern_table(name):
    table = _PATTERN_TABLES.get(name)
    if table is None:
        path = os.path.join(os.path.dirname(__file__), "..", "..", "data",
                            "attack_patterns", "%s.json" % name)
        table = _PATTERN_TABLES[name] = _load_json(path)
    return table


def _stage_tier(line, stage, level):
    """The band an attacker of this stage and level falls in, on *line*.

    Both lines carrying a table of this shape choose their row from the
    attacker's **stage** and a three-tier band of its level -- the top tier
    always being that stage's own maximum level on its own -- and not from
    the level alone, which is what the table this replaced assumed. The
    attribute plays no part on either: DMX stage 3 was read on a Data pet and
    a Virus pet and came out identical, and PENZ stage 6 was read on a Free
    pet against stage 7 on a Vaccine one with all 40 cells agreeing.

    Stage 1 is the exception to the three: a Baby I has one level and cannot
    battle at all, so its single band was read off the training minigame.

    A stage or level outside what was measured is clamped to the nearest band
    rather than refused. A pet from any module can carry any stage onto this
    wire, and the nearest measured band is a better answer than falling
    through to the weakest row in the file.
    """
    tiers = _pattern_table(line)["tiers"]
    stages = sorted({t["stage"] for t in tiers})
    try:
        stage = int(stage)
    except (TypeError, ValueError):
        stage = stages[0]
    if stage not in stages:
        stage = min(stages, key=lambda s: (abs(s - stage), s))
    band = [t for t in tiers if t["stage"] == stage]
    try:
        level = int(level)
    except (TypeError, ValueError):
        level = 1
    for tier in band:
        low, high = tier["levels"]
        if low <= level <= high:
            return tier
    return band[0] if level < band[0]["levels"][0] else band[-1]


def stage_tier_index(stage, level, line="DMX"):
    """Which of a stage's tiers this level falls in, 1-based.

    The XAI bar widens its scoring zones at exactly the levels the attack
    table changes row -- a Varudurumon's bar went `1-1` at level 4, `1-2` at
    5-9 and `1-3` at 10 -- and Count Match Z eases its difficulty on the same
    ladder. So both read the bands out of a table rather than carrying a
    copy: one measurement, one place, and no way for the picture and the
    damage to disagree.

    The ladder is a property of the level range a stage has rather than of
    either device, and the two tables agree on it throughout, which is why
    one line's bands answer for both.
    """
    tier = _stage_tier(line, stage, level)
    band = [t for t in _pattern_table(line)["tiers"]
            if t["stage"] == tier["stage"]]
    return band.index(tier) + 1


def dmx_tier_index(stage, level):
    """The level ladder, under the name its callers already use."""
    return stage_tier_index(stage, level)


#: Where a pet with no Level stat sits on the same three-band ladder, read
#: off its EFFORT instead. Both of the charge minigames that widen with the
#: pet use these, so they are written down once.
EFFORT_BANDS = ((9, 1), (16, 2), (None, 3))


def pet_tier_index(pet, line="DMX"):
    """Which of three bands *pet* sits in, 1-3, for a charge that widens.

    **A device that levels its Digimon bands by the level; one that does not
    bands by effort.** Showing Level as a stat is what says a module has one
    -- a pet from a module with no level would otherwise sit at level 1
    forever and never leave the first band, which is how the Xai bar came to
    read effort in the first place. Count Match Z reads the same call, so the
    two cannot drift.

    The level side is the attack table's own banding (`stage_tier_index`), so
    a charge widens exactly where the attacks change row -- a stage 6 pet
    steps at levels 5 and 10, a stage 3 pet at 3 and 4. The effort side is a
    flat 0-8 / 9-15 / 16+, which is the Xai bar's and has no measurement
    behind it beyond being the bar art's own three steps.
    """
    if pet is None:
        return 1
    # `get_module` raises on a module that is not loaded, which a pet can
    # outlive -- a save carries the module's name, not the module. Treat not
    # knowing as not levelling: the effort side answers for every pet, where
    # the level side answers only for a pet whose module says it has one.
    try:
        from utils.module_utils import get_module
        module = get_module(getattr(pet, "module", None))
    except Exception:      # pylint: disable=broad-except
        module = None
    visible = (getattr(module, "visible_stats", None) or []) if module else []
    if "Level" in visible:
        try:
            return stage_tier_index(getattr(pet, "stage", None),
                                    getattr(pet, "level", 1), line)
        except Exception:      # pylint: disable=broad-except
            return 1
    try:
        effort = int(getattr(pet, "effort", 0) or 0)
    except (TypeError, ValueError):
        effort = 0
    for top, band in EFFORT_BANDS:
        if top is None or effort < top:
            return band
    return 1


def _tiered_pattern(line, stage, level, mini_game):
    """The five attacks *line* draws for this attacker and charge."""
    table = _pattern_table(line)
    tier = _stage_tier(line, stage, level)
    charge = max(0, min(int(mini_game or 0), len(tier["patterns"]) - 1))
    wanted = tier["patterns"][charge]
    for row in table["patterns"]:
        if row["id"] == wanted:
            return list(row["pattern"])
    return [1, 1, 1, 1, 1]


def verdict_rounds(hit_points):
    """The rounds a verdict wire stages, for a bar of *hit_points*.

    These wires exchange a result and nothing else, so the battle is ours to
    present -- but its shape is measured, on the Digital Monster's five: three
    traded single hits, then the winner's double against the loser's single
    **that misses**. The winner spends exactly its opponent's HP and takes one
    less than its own, finishing on 2.

    Written as a rule rather than a row so it survives a different bar. The
    **Pendulum Color fights at three**, which its manual states outright --
    "each Digimon has 3 health points which will be reduced by 1 for a normal
    hit and by 2 for a super hit" -- and the five-HP row spends 5 against it,
    killing the loser a round early and leaving the last round dead.

    At 5 it reproduces `DMC.json`'s measured `[1, 1, 1, 2]` / `[1, 1, 1, 1]`
    exactly, which is what the test pins; at 3 it gives `[1, 2]` / `[1, 1]`,
    the same shape scaled. The round COUNT at three is a construction, not a
    reading -- no Pendulum Color battle has been filmed -- but the damage
    values and the bar it spends them against are both the manual's.
    """
    try:
        hit_points = int(hit_points)
    except (TypeError, ValueError):
        hit_points = 5
    if hit_points < 2:
        return [hit_points], [1]
    # Singles until a double finishes it, so the spend is exactly the bar.
    winner = [1] * (hit_points - 2) + [2]
    return winner, [1] * len(winner)


#: The verdict wires' battle, filled from DMC.json on first use.
DMC_PATTERN_TABLE = None


def _dmc_patterns():
    """The damage rows both verdict wires stage their battle from.

    DMC.json has carried the right table all along -- four rounds, the winner
    closing on a double against a 5 HP bar -- while the hardcoded copy that
    used to live here had grown a fifth round on each side, so the winner
    spent 6 damage against 5 and the loser had to be given a phantom miss to
    stay standing. A DMOG battle filmed against a real device settled it at
    four rounds, and `_simulate_dm_bs` had the same four hardcoded inline all
    along. One table, one file.
    """
    global DMC_PATTERN_TABLE
    if DMC_PATTERN_TABLE is None:
        pattern_path = os.path.join(os.path.dirname(__file__), "..", "..",
                                    "data", "attack_patterns", "DMC.json")
        DMC_PATTERN_TABLE = _load_json(pattern_path)
    return DMC_PATTERN_TABLE["patterns"]
DM20_PATTERN_TABLE = None
DM20_TAG_PATTERNS = None  # Loaded from JSON

# DM20 single battle attack patterns (verified from actual DM20 device)
#: Both of the Ver.20th's tables, from data/attack_patterns/DM20.json.
DM20_PATTERN_TABLE = None

#: The Pendulum 20th's, from data/attack_patterns/PEN20.json. **Its own** --
#: not one of its fifteen rows matches DM20's, which this used to assume.
PEN20_PATTERN_TABLE = None

#: A value is the attack, and the attack is its damage.
DM20_SINGLE_WEAK = 1
DM20_SINGLE_STRONG = 2
DM20_DOUBLE_WEAK = 3
DM20_DOUBLE_STRONG = 4

#: Possible damage values in a single battle. Critical is a fifth attack that
#: only Tag Battles reach, so it is not among them.
DM20_DAMAGE_VALUES = [DM20_SINGLE_WEAK, DM20_SINGLE_STRONG,
                      DM20_DOUBLE_WEAK, DM20_DOUBLE_STRONG]


def _dm20_table():
    global DM20_PATTERN_TABLE
    if DM20_PATTERN_TABLE is None:
        pattern_path = os.path.join(os.path.dirname(__file__), "..", "..",
                                    "data", "attack_patterns", "DM20.json")
        DM20_PATTERN_TABLE = _load_json(pattern_path)
    return DM20_PATTERN_TABLE


def load_dm20_tag_patterns():
    """The tag-battle rows.

    DM20.json used to be a bare list of them; it now carries the measured
    single-battle table beside them, so a dict is read from `tag` and a plain
    list is taken whole.
    """
    global DM20_TAG_PATTERNS

    if DM20_TAG_PATTERNS is not None:
        return DM20_TAG_PATTERNS

    try:
        table = _dm20_table()
        DM20_TAG_PATTERNS = table["tag"] if isinstance(table, dict) else table
        return DM20_TAG_PATTERNS
    except Exception as error:
        print("Warning: Could not load DM20 tag patterns: %s" % error)
        return []


def get_dm20_pattern_index_from_taps(taps: int) -> int:
    """
    Convert minigame button taps (0-14) to DM20 pattern index (0-15).
    
    In DM20 protocol, the pattern index (0-14) directly corresponds to 
    the number of button presses in the minigame. Pattern 15 is treated as 14.
    
    Args:
        taps: Number of button presses in minigame (0-14)
        
    Returns:
        Pattern index (0-14) to use in Packet 3
    """
    # Clamp to valid range and use directly as pattern index
    return max(0, min(14, taps))


def _pen20_table():
    global PEN20_PATTERN_TABLE
    if PEN20_PATTERN_TABLE is None:
        pattern_path = os.path.join(os.path.dirname(__file__), "..", "..",
                                    "data", "attack_patterns", "PEN20.json")
        PEN20_PATTERN_TABLE = _load_json(pattern_path)
    return PEN20_PATTERN_TABLE


def _twentieth_table(battle_format):
    """The measured table for whichever 20th-anniversary line this is."""
    return _pen20_table() if battle_format == "PEN20" else _dm20_table()


def get_20th_single_battle_attack_pattern(pattern_index, battle_format="DM20"):
    """The five attacks a 20th-anniversary line throws for a tap meter.

    Both lines were measured the same way -- a battle per point of the meter,
    the attack read off the screen each round -- and **they are different
    tables**. Not one of PEN20's fifteen rows matches DM20's, though the two
    share the same four attacks, the same damage-is-the-value rule and the
    same reversed sprite pairing.
    """
    rows = _twentieth_table(battle_format)["single"]
    pattern_index = max(0, min(len(rows) - 1, int(pattern_index or 0)))
    return list(rows[pattern_index]["pattern"])


def get_20th_enemy_pattern(stage, battle_format="DM20"):
    """The five attacks an adventure enemy throws on a 20th line.

    An enemy plays no minigame, so its stage stands in -- and every row is one
    of the measured meter rows, picked so total damage rises strictly with the
    stage, so an enemy always throws a pattern the device really produces.
    """
    rows = _twentieth_table(battle_format)["enemy_patterns"]
    stage = int(stage or 1)
    for row in rows:
        if row["stage"] == stage:
            return list(row["pattern"])
    return list(rows[0]["pattern"] if stage < rows[0]["stage"]
                else rows[-1]["pattern"])


def get_dm20_enemy_pattern(stage):
    """The five attacks an adventure enemy throws on the Ver.20th's line.

    An enemy plays no minigame, so there is no meter to read a row from. Its
    stage stands in, and every row is one of the **measured** meter rows --
    chosen so total damage rises strictly with the stage -- so an enemy is
    always throwing a pattern the device really produces.
    """
    rows = _dm20_table()["enemy_patterns"]
    stage = int(stage or 1)
    for row in rows:
        if row["stage"] == stage:
            return list(row["pattern"])
    return list(rows[0]["pattern"] if stage < rows[0]["stage"]
                else rows[-1]["pattern"])


def get_dm20_single_battle_attack_pattern(pattern_index: int, minigame_taps: int = 0) -> list:
    """The five attacks a Ver.20th throws for a given tap meter.

    **Measured**: fifteen battles against a real Ver.20th, one per point of
    the meter, with what the Digimon fired read off the screen each round
    (utilities/DIGIROM/dm20pattern.txt, via
    utilities/claude/map_dm20_attacks.py).

    A value is the attack and the attack is its damage -- 1 single weak, 2
    single strong, 3 double weak, 4 double strong. The table this replaced
    held only 1s and 2s: it had recorded how many shots went out and not
    which sprite, so a Strong and a Double Weak were the same entry in it.

    Args:
        pattern_index: the Attack field from packet 3, 0-14.
        minigame_taps: unused, kept for callers that pass it.

    Returns:
        Five damage values, 1-4.
    """
    rows = _dm20_table()["single"]
    pattern_index = max(0, min(len(rows) - 1, int(pattern_index or 0)))
    return list(rows[pattern_index]["pattern"])


def get_dm20_tag_battle_attack_pattern(bar1: int, bar2: int, taps: int) -> list:
    """
    Get DM20 attack pattern for tag battles.
    
    In tag battles, the pattern depends on:
    - bar1: Tag meter value for device1 (0-3)
    - bar2: Tag meter value for device2 (0-7) 
    - taps: Number of button presses (0-14)
    
    Args:
        bar1: Tag meter for device1 (0-3)
        bar2: Tag meter for device2 (0-7)
        taps: Number of button presses in minigame (0-14)
        
    Returns:
        List of 5 damage values [1-3] for tag battle (includes critical hits)
        Returns first 4 if pattern not found (fallback to single battle pattern)
    """
    patterns = load_dm20_tag_patterns()
    
    if not patterns:
        # Fallback to single battle pattern
        return get_dm20_single_battle_attack_pattern(taps)
    
    # Find matching pattern
    for entry in patterns:
        if entry['bar1'] == bar1 and entry['bar2'] == bar2 and taps in entry['taps']:
            return entry['pattern']
    
    # No match found - use single battle pattern as fallback
    single_pattern = get_dm20_single_battle_attack_pattern(taps)
    # Extend to 5 attacks by duplicating first attack (as per DM20 spec)
    return single_pattern + [single_pattern[0]]

#: The lines whose table is keyed on (stage, level band, charge), each in
#: its own file. They share the shape and nothing else -- see
#: `get_attack_pattern`.
TIERED_PROTOCOLS = ("DMX", "PENZ")

#: Every format riding the DMX packet layout, which is a different question
#: from which table it reads: DMC rides the wire and keeps its own rows.
DMX_WIRE_PROTOCOLS = ("DMX", "PENZ", "DMC")


#: DMC's pre-measurement (level, charge) table, from DMC.json on first use.
DMC_LEVEL_TABLE = None


def _dmc_levels():
    """The rows a Digital Monster Color draws, unchanged and unmeasured.

    They lived in PENZ.json while both lines read them; the Pendulum Z has
    its own measured table now, so they moved into DMC.json rather than stay
    under another line's name. Nothing here has been read off hardware.
    """
    global DMC_LEVEL_TABLE
    if DMC_LEVEL_TABLE is None:
        DMC_LEVEL_TABLE = _pattern_table("DMC")["levels"]
    return DMC_LEVEL_TABLE


#: How many effort points make one heart. Effort is drawn as four hearts
#: at four points each, so a pet's band is `effort // EFFORT_PER_HEART`.
EFFORT_PER_HEART = 4


def get_colour_pve_pattern(stage=1, effort=0):
    """The six attacks a Colour-line ADVENTURE or ARENA battle throws.

    The wire itself exchanges a verdict, so a connection battle has no
    pattern to send and `_simulate_verdict_turns` stages the same four rounds
    every time. A battle fought here is the other case, and it used to draw
    from `DMX.json` -- values 1 to 5 -- then clamp them to this line's
    `DAMAGE_LIMIT` of 2. Nearly every value in that table is 2 or above, so
    nearly every round came out as the maximum: the same thing the Digital
    Monster's own adventure table was written to fix.

    Keyed on the attacker's **stage** and its **effort hearts**, which are
    both properties of the Digimon -- what it has grown into, and what its
    training bought. The charge was the second axis before and was the wrong
    one: it says nothing about the pet, and on DMC it does not vary at all,
    because that module's `battle_minigame` is "None" and scores a flat 2.

    **An enemy needs no table of its own.** It has a stage and no effort, so
    it reads (its stage, 0 hearts) through the same door.
    """
    table = _pattern_table("DMC")["pve"]["rows"]
    try:
        stage = int(stage or 1)
    except (TypeError, ValueError):
        stage = 1
    try:
        hearts = int(effort or 0) // EFFORT_PER_HEART
    except (TypeError, ValueError):
        hearts = 0
    band = table[str(max(1, min(stage, len(table))))]
    return list(band[str(max(0, min(hearts, len(band) - 1)))])


#: The four outcomes a Count Match Color charge can reach, weakest first.
#: A colour is worth its PLACE in the attribute's own ranking, not its name.
PENC_BANDS = ("none", "worst", "middle", "own")


def penc_band_name(band):
    """A 0-3 band index as the name the table is keyed on."""
    try:
        index = int(band or 0)
    except (TypeError, ValueError):
        index = 0
    return PENC_BANDS[max(0, min(index, len(PENC_BANDS) - 1))]


def get_penc_pattern(stage=1, band=0):
    """The five attacks a Pendulum Color throws, from its stage and charge.

    **This line does not exchange a verdict; it fights.** Its manual states
    the whole rule: "You begin each battle by shaking to get a specific
    color, just as you do in Training" and "each Digimon has 3 health points
    which will be reduced by 1 for a normal hit and by 2 for a super hit".

    **The table is keyed on the STAGE and the colour band, and on nothing
    else.** All seven stages were read off a real device
    (`utilities/DIGIROM/penc.txt`), and effort, hunger and strength were
    maxed on several of them without moving a single row -- so nothing the
    pet has trained reaches this. Stage 3 was read twice, on a Virus pet and
    on a Data pet, and the two came out identical once keyed on the band,
    which is what shows the arrangement follows the band and not the colour.

    That also retires the old split between a "training" table and a battle
    one: there is one table, and the device plays a charge in training, in a
    quest and in a connection battle alike.

    The super-hit count is not an input -- it is the number of 2s in the row
    that comes back, and it follows from the stage: the bottom band pays 0 at
    stages 1-2 and 1 from stage 3 up, and the middle band 3 at stages 1-4 and
    4 from stage 5 up. So the manual's "3 or 4" is the stage speaking rather
    than a roll.
    """
    table = _pattern_table("PENC")["stage_patterns"]["patterns"]
    try:
        stage = int(stage or 1)
    except (TypeError, ValueError):
        stage = 1
    rows = table.get(str(max(1, min(stage, len(table)))))
    return list(rows[penc_band_name(band)])


#: How many shots the CHARGE fires, which is not how many rounds a battle
#: runs. The minigame throws five and the manual counts super hits out of
#: five -- "5 (Megahit)" is its top band -- while the battle has six.
PENC_CHARGE_ROUNDS = 5


def penc_super_hits(pattern):
    """How many super hits a row throws, out of the charge's five shots.

    **Five, not the battle's six.** The count is the minigame's own -- the
    manual bands its rewards on it and tops out at "5 (Megahit)" -- and the
    charge fires five shots on screen. The sixth round is a battle round
    beyond what the charge shows, so it does not enter the count.
    """
    return sum(1 for value in (pattern or [])[:PENC_CHARGE_ROUNDS]
               if value >= 2)


#: Wire version -> index -> stage, per Colour line, from `data/rosters/`.
#: Only a line whose file exists can answer; the others report None and the
#: caller keeps its own fallback.
COLOUR_STAGES = {}


def colour_stage_from_wire(battle_format, version, index):
    """The stage a Colour device's version and index name, or None.

    **This wire carries no stage**, and the attack table is keyed on one, so
    it has to be recovered from the two identity fields the packet does have.
    The index alone cannot do it -- 19 of 34 indexes name more than one stage
    across the eight versions, and index 21 is a Child on one, an Ultimate on
    another and a Super Ultimate on a third -- but the **pair** is exact, with
    0 of 259 records ambiguous.

    The table lives in `data/rosters/` and not in the module on purpose: the
    opponent is a real device whether or not the player owns PENC, and that is
    exactly the case where there is no module to ask. `_parse_dmc_opponent`
    used to hand every Colour opponent a flat `stage=4`, which was harmless
    while nothing read it and stopped being so the moment the attack table
    became keyed on the stage.

    **Index 0 is refused**, as it is on every wire: it is what a
    compatibility pet announces -- "an outsider" -- and this line does have a
    stage 1 record sitting there, so resolving it would report a foreign
    device as a Baby I. None means that, or a version or index this line does
    not have, and the caller keeps its own fallback rather than being handed a
    stage that was made up.

    **Only PENC has a table, and DMXW deliberately does not.** Xros Wars has
    one physical device carrying three rosters, and its wire announced
    version 0 for a version 1 Digimon -- so if it always sends 0, the index
    alone has to carry the stage and it cannot: 11 of its 32 indexes name two
    stages, index 0 being both a Baby I and an Adult. Either the wire does
    distinguish the three (and a device holding a version 2 or 3 Digimon
    would announce 1 or 2), or the device's index space is not the module's
    and has to come out of the firmware dump. One battle against a version 2
    or 3 Digimon says which, and until then there is nothing honest to store.
    """
    from battle.sim import protocol_constants

    name = protocol_constants.canonical_format(battle_format)
    if name not in COLOUR_STAGES:
        import json
        import os
        path = os.path.join(os.path.dirname(__file__), "..", "..",
                            "data", "rosters", "%s.json" % name)
        try:
            with open(os.path.abspath(path), encoding="utf-8") as handle:
                COLOUR_STAGES[name] = json.load(handle).get("stages", {})
        except (IOError, OSError, ValueError):
            # No table for this line, which is an answer: see DMXW below.
            COLOUR_STAGES[name] = {}
    try:
        version, index = int(version), int(index)
    except (TypeError, ValueError):
        return None
    if index <= 0:
        return None
    return COLOUR_STAGES[name].get(str(version), {}).get(str(index))


def penc_index_for_stage(version, stage):
    """An index on this line's roster whose stage is *stage*, or None.

    The other direction of `colour_stage_from_wire`, for a **compatibility**
    pet. Such a pet has no entry on the device's roster and the wire's answer
    is index 0, "an outsider" -- which on this line reads as a stage 1 record
    if the toy looks it up at all. Announcing a real index of our own stage
    keeps the identity we present consistent with the Digimon we are.

    **It does not change the attack pattern**, which is measured: the device
    draws our shots from the selector in packet 2, not from our identity.
    Filmed battles 59 and 60 are that reading -- we announced a stage 3
    Floramon alongside stage 4's selector and the toy drew stage 4's row.
    So this is about the identity being coherent, not about the battle.

    The lowest matching index is taken, so the choice is stable rather than
    varying between runs, and None means this line has nothing at that stage.
    """
    colour_stage_from_wire('PENC', version, 1)     # prime the table
    try:
        version, stage = int(version), int(stage)
    except (TypeError, ValueError):
        return None
    rows = COLOUR_STAGES.get('PENC', {}).get(str(version), {})
    matches = [int(i) for i, st in rows.items() if st == stage and int(i) > 0]
    return min(matches) if matches else None


#: The Colour family's shared 15-row attack pool, and Xros Wars' own table
#: choosing from it. Both are read out of the DMXW firmware by
#: `utilities/claude/extract_colour_patterns.py`.
COLOUR_ROWS = None
DMXW_SELECT = None


def _colour_data(name, key):
    import json
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "..",
                        "data", "attack_patterns", "%s.json" % name)
    with open(os.path.abspath(path), encoding="utf-8") as handle:
        return json.load(handle)[key]


def colour_pool():
    """The 15 rows every Colour line's selector indexes into.

    **The selector IS this index.** All 28 rows measured off a real Pendulum
    Color are in here, using all 15 entries, and all seven selectors read off
    that wire are exactly the index -- which is the encoding seven readings
    could not derive on their own. Read out of the Xros Wars firmware.

    Rows are stored six rounds long, which is how the device holds them;
    callers take the first `PENC_ROUNDS`.
    """
    global COLOUR_ROWS
    if COLOUR_ROWS is None:
        COLOUR_ROWS = _colour_data("COLOUR_ROWS", "rows")
    return COLOUR_ROWS


def colour_knows(selector):
    """Whether the shared pool has a row at this index."""
    try:
        return 0 <= int(selector) < len(colour_pool())
    except (TypeError, ValueError):
        return False


def colour_row(selector):
    """One pool row by index, or all normal hits for an index it has not."""
    pool = colour_pool()
    try:
        selector = int(selector)
    except (TypeError, ValueError):
        return [1] * PENC_ROUNDS
    if not 0 <= selector < len(pool):
        return [1] * PENC_ROUNDS
    return list(pool[selector][:PENC_ROUNDS])


def dmxw_effort_tier(effort):
    """Which of the three training tiers an effort value falls in.

    0-9 trainings, 10-19, and 20 -- the firmware's own banding.
    """
    try:
        effort = int(effort or 0)
    except (TypeError, ValueError):
        effort = 0
    return max(0, min(2, effort // 10))


def get_dmxw_selector(stage=3, band=0, effort=0):
    """The pool index an Xros Wars device announces in packet 2's word 6.

    The selection table's own entry, which is what the wire carries: word 6
    is an index into the family's shared pool, measured twice on hardware --
    an OmniShoutmon at stage 4 sent 3 and a Shoutmon DX at stage 5 sent 5,
    and both threw the rows those name.
    """
    global DMXW_SELECT
    if DMXW_SELECT is None:
        DMXW_SELECT = _colour_data("DMXW_SELECT", "select")
    try:
        stage = int(stage or 3)
    except (TypeError, ValueError):
        stage = 3
    stage = max(1, min(stage, len(DMXW_SELECT) // 3))
    try:
        band = max(0, min(int(band or 0), 3))
    except (TypeError, ValueError):
        band = 0
    return DMXW_SELECT[(stage - 1) * 3 + dmxw_effort_tier(effort)][band]


def get_dmxw_pattern(stage=3, band=0, effort=0):
    """The five attacks an Xros Wars device throws.

    **Stage, effort tier and charge band**, read out of the firmware rather
    than inferred: `DMXW_SELECT.json` is 15 rows of four pool indexes, five
    stages by three effort tiers, and `colour_pool` holds the rows they name.

    This replaced a per-Digimon table, which was wrong. Two Xros forms at the
    same stage threw different rows, and with no third axis in view the
    Digimon looked like the key -- but the missing axis was **effort**:
    Shoutmon X2 was at tier 1 and the other forms at tier 2. The firmware
    reproduces all three readings exactly and a Digimon never comes into it.
    """
    global DMXW_SELECT
    if DMXW_SELECT is None:
        DMXW_SELECT = _colour_data("DMXW_SELECT", "select")
    try:
        stage = int(stage or 3)
    except (TypeError, ValueError):
        stage = 3
    # Five stages, indexed by the record's own stage - 1; anything above
    # clamps rather than falling off the end.
    stage = max(1, min(stage, len(DMXW_SELECT) // 3))
    return colour_row(get_dmxw_selector(stage, band, effort))


def get_dmxw_enemy_pattern(stage=3):
    """The five attacks an Xros Wars quest enemy throws, by stage.

    An enemy plays no charge and has no training, so it reads its stage and
    takes a real row of the device's own table. **Which tier and band is
    ours**: the middle band at tier 1, the same "not the weakest, not the
    strongest" choice every other line's enemy makes.
    """
    block = _colour_data("DMXW", "enemy_patterns")
    return get_dmxw_pattern(stage, PENC_BANDS.index(block["band"]),
                            block["tier"] * 10)


def colour_pattern(battle_format, stage=1, charge=0, effort=0):
    """The five shots a fought Colour battle throws, for either line.

    Both fight, and neither fights the same way. A Pendulum Color's charge
    rides the wire as a raw super-hit count, so it is crossed back to a band
    here; an Xros Wars plays Excite training's bar, which is already a 0-3
    band. Both key their rows on the attacker's **stage**.

    One door, so a caller that does not care which line it is holding does
    not have to. **The two tables are not interchangeable** -- see
    `get_dmxw_pattern` for why the overlap between them is a small
    vocabulary rather than a mapping.
    """
    from battle.sim import protocol_constants

    name = protocol_constants.canonical_format(battle_format)
    if name == 'DMXW':
        return get_dmxw_pattern(stage, charge, effort)
    return get_penc_pattern(stage, penc_band_for_super_hits(stage, charge))


def penc_charge_pattern(digimon, battle_format='PENC'):
    """The row a Digimon's own stage and announced charge throw.

    **Only a fallback.** A battle packet carries a selector, and the selector
    IS the row -- `get_penc_wire_pattern` reads it straight out of the shared
    pool, so neither side's charge chooses the pattern in a real exchange.
    This is for a transcript that carries no selector at all, and it takes
    the line as an argument because the Xros Wars table is keyed on stage and
    effort where the Pendulum Color's is keyed on stage and band.
    """
    stage = getattr(digimon, "stage", 1) or 1
    hits = getattr(digimon, "mini_game", 0) or 0
    return colour_pattern(battle_format, stage, hits,
                          getattr(digimon, "effort", 0) or 0)


def penc_band_for_super_hits(stage, super_hits):
    """Which colour band a super-hit count means at this stage, 0-3.

    The inverse of the table, and it is needed in two places. The **wire**
    carries the count -- packet 2's COU is keyed on it through
    `charge_to_selector`, and `penc_super_hits_from_wire` is how a device's
    own charge is read back -- while the **table** is keyed on the band, so
    something has to cross between them.

    Within one stage the four counts are distinct (0/1/3/5 at stages 1-2,
    1/2/3/5 at 3-4, 1/2/4/5 from 5 up), so the inverse is exact wherever the
    count is one the stage can produce. A count it cannot -- a device of an
    unknown stage, or the flat `VERSUS_CHARGE` -- takes the nearest band
    rather than falling through to the weakest.
    """
    try:
        hits = int(super_hits or 0)
    except (TypeError, ValueError):
        hits = 0
    counts = [penc_super_hits(get_penc_pattern(stage, band))
              for band in range(len(PENC_BANDS))]
    if hits in counts:
        return counts.index(hits)
    return min(range(len(counts)), key=lambda i: abs(counts[i] - hits))


def get_penc_wire_charge(stage=1, band=0):
    """What packet 2's COU low word carries for our stage and colour band.

    A Pendulum Color announces its charge in the low word of packet 2's COU,
    and the value **names a row of the attack table** -- so it depends on the
    stage as well as the band. Six points are measured, each from a device
    whose Digimon resolved to a roster record (giving its stage) in a battle
    whose heading records the colour it landed (giving its band):

        stage 3   none 0x02   middle 0x0A                own 0x0E
        stage 4   none 0x03   worst  0x08   middle 0x0B  own 0x0E

    **It cannot be keyed on the super-hit count**, which is what it was.
    Stages 3 and 4 both pay 1 super hit for their bottom band and both pay 3
    for their middle one, yet they send different selectors -- so a stage 3
    pet was announcing a stage 4 row.

    A pair nobody has read falls back to the known selector for the **same
    band** at the nearest stage. That is an approximation, and the caller
    logs it as one: within a band the selector rises by 1 per stage across the
    two points measured, but two points are not a formula, and no block layout
    tried reproduces all six.

    We used to send a flat 2 here (`PENC.BATTLE_TRAILER`), taken from the
    static background-unlock codes in `utilities/DIGIROM` -- and 2 is not one
    of the values a battle produces, so the device was told the same thing
    whatever the player rolled.
    """
    values = _pattern_table("PENC")["charge_to_selector"]["values"]
    name = penc_band_name(band)
    try:
        stage = int(stage or 1)
    except (TypeError, ValueError):
        stage = 1

    exact = values.get(str(stage), {}).get(name)
    if exact is not None:
        return exact
    # Every stage 1-7 is in the map, so this is only reachable for a stage
    # outside the line's own range; clamp rather than invent an index.
    stage = max(1, min(stage, max(int(k) for k in values)))
    return values[str(stage)][name]


def penc_wire_charge_is_measured(stage, band):
    """Whether this pair was read off a device, as opposed to derived.

    All 28 are known now -- the selector is the row's index in the shared
    pool -- but seven were read off real Pendulum Colors and the rest follow
    from the pool, and that difference is worth being able to state.
    """
    measured = _pattern_table("PENC")["charge_to_selector"]["measured"]
    try:
        stage = int(stage or 1)
    except (TypeError, ValueError):
        stage = 1
    return penc_band_name(band) in measured.get(str(stage), [])


class PencRound(object):
    """One round of a Pendulum Color battle: what each side threw and landed."""

    __slots__ = ("turn", "a_damage", "a_hit", "b_damage", "b_hit",
                 "a_hp", "b_hp")

    def __init__(self, turn, a_damage, a_hit, b_damage, b_hit, a_hp, b_hp):
        self.turn = turn
        self.a_damage, self.a_hit = a_damage, a_hit
        self.b_damage, self.b_hit = b_damage, b_hit
        self.a_hp, self.b_hp = a_hp, b_hp


def fight_penc(a_power, a_attribute, a_charge,
               b_power, b_attribute, b_charge, rng=None,
               a_stage=1, b_stage=1, battle_format='PENC',
               a_effort=0, b_effort=0):
    """A fought Colour battle, round by round -- Pendulum Color or Xros Wars.

    **The one place this battle happens.** A DCom battle is Omnipet standing
    in for a real device and a versus battle is Omnipet standing in for both,
    so they cannot be two different battles -- and this line is where that
    bites hardest, because unlike the Digital Monster Color it exchanges no
    verdict for the DCom path to lean on. Both sides send their power, their
    attribute and their charge, which is the whole of a battle, so each
    device runs it for itself.

    Everything in it is the manual's:

    * the hit rate is `protocol_constants.hit_rate` -- the power ratio plus
      the attribute triangle at this line's own +10/-10, capped at 99;
    * the pattern is each side's own stage and colour band, measured off a
      real device for all seven stages -- `a_charge` and `b_charge` are the
      super-hit counts the wire carries, crossed to bands here;
    * three hit points a side, and every shot rolled -- the guaranteed hits
      belong to the compatibility battle with a Digital Monster Color and to
      nothing else.

    Attributes are in the Colour line's own encoding on both sides and the
    charges are 0-3 colour bands; the caller converts. Returns
    (a_won, [PencRound, ...]).
    """
    import random

    from battle.sim import protocol_constants

    rng = rng or random
    limits = protocol_constants.get_constants(battle_format)         or protocol_constants.PENC
    a_rate = protocol_constants.hit_rate(limits, a_power, a_attribute,
                                         b_power, b_attribute)
    b_rate = protocol_constants.hit_rate(limits, b_power, b_attribute,
                                         a_power, a_attribute)
    # The callers hold super-hit COUNTS, because that is what the wire
    # carries and what a device's own packet reads back as. The table is
    # keyed on the band, so the crossing happens here, once.
    a_pattern = colour_pattern(battle_format, a_stage, a_charge, a_effort)
    b_pattern = colour_pattern(battle_format, b_stage, b_charge, b_effort)

    a_hp = b_hp = limits.FIXED_HP
    rounds = []
    for turn in range(min(limits.TURNS, len(a_pattern), len(b_pattern))):
        a_hit = rng.randint(0, 99) < a_rate
        b_hit = rng.randint(0, 99) < b_rate
        if a_hit:
            b_hp = max(0, b_hp - a_pattern[turn])
        if b_hit:
            a_hp = max(0, a_hp - b_pattern[turn])
        rounds.append(PencRound(turn + 1, a_pattern[turn], a_hit,
                                b_pattern[turn], b_hit, a_hp, b_hp))
        if a_hp == 0 or b_hp == 0:
            break

    # "Once a Digimon runs out of HP, it loses the battle." Both emptying on
    # one round is the case the rounds cannot settle; the higher bar keeps
    # it, and on a tie the side that opened.
    if a_hp and not b_hp:
        a_won = True
    elif b_hp and not a_hp:
        a_won = False
    else:
        a_won = a_hp >= b_hp
    return a_won, rounds


#: How many rounds a fought Colour battle can run to.
#:
#: **Six, not five.** Every row of the family's shared pool stores six values
#: (`COLOUR_ROWS.json`, read out of the Xros Wars firmware), and PENC's hit
#: mask has twice been seen with bit 5 set -- a sixth round. Five was taken
#: from the charge, which fires five shots on screen; the charge is not the
#: battle. At three hit points a sixth round is rare rather than unreachable,
#: which is why nothing had run that long to show it.
PENC_ROUNDS = 6


def get_penc_wire_pattern(selector):
    """The five shots a wire selector throws.

    **The selector is an index into the Colour family's shared pool**, which
    is read out of the Xros Wars firmware. That was worked out the long way
    first -- six selectors filmed off a Pendulum Color, each tied to the
    (stage, band) of the device that sent it -- and the pool confirms every
    one of them and supplies the other nine.

    An index the pool does not have falls back to all normal hits, the
    weakest thing it could be, so an unknown never overstates its damage.
    """
    return colour_row(selector)


def get_penc_training_pattern(stage=1, band=0):
    """The five shots the Pendulum Color's TRAINING minigame fires.

    The same table a battle reads. They used to be separate, on four rows
    measured at one stage -- and reading every stage showed the difference
    was the stage, so there is nothing left for a second table to hold.
    """
    return get_penc_pattern(stage, band)


def penc_result_from_wire(op13_words, we_are_initiator):
    """Read a Pendulum Color battle out of the responder's final packet.

    Word 4 says whether the **initiator** won and word 5 is the initiator's
    hit mask, least significant bit first -- both in operation **0x13**,
    which is the responder's packet and not the initiator's. That is where
    this line differs from the Digital Monster Color, whose verdict is in
    operation 2; the two share a packet layout and not a battle, and assuming
    otherwise is what made every PENC battle come out wrong.

    Verified against the filmed annotations: 32 of 32 visible hit/miss
    observations and 14 of 14 winners.

    **The responder's hits are the initiator's inverted, and that is a
    hypothesis.** One mask covers both sides only if exactly one lands a hit
    each round. The DMX document states that rule for its own wire and the
    Vital Bracelet notes repeat it, which makes it plausible rather than
    established -- the films only ever annotate the game's attacks, so the
    device's own flags have never been read. A two-screen capture settles it.

    Returns (we_won, our hits per round, their hits per round).
    """
    won_flag = op13_words[4]
    mask = op13_words[5]
    initiator_hits = [bool((mask >> turn) & 1) for turn in range(PENC_ROUNDS)]
    responder_hits = [not hit for hit in initiator_hits]

    we_won = bool(won_flag) == bool(we_are_initiator)
    ours = initiator_hits if we_are_initiator else responder_hits
    theirs = responder_hits if we_are_initiator else initiator_hits
    return we_won, ours, theirs


def penc_hit_mask(hits):
    """Pack per-round hits into the wire's mask, least significant bit first."""
    mask = 0
    for turn, hit in enumerate(hits[:PENC_ROUNDS]):
        if hit:
            mask |= 1 << turn
    return mask


def penc_super_hits_from_wire(value):
    """The super-hit count a Pendulum Color's COU low word announces.

    The selector names a row, so the count is that row's own -- no ranges and
    nothing rolled. It used to invert a super-hits-to-selector map, which
    could not represent the wire at all: two stages send different selectors
    for the same count, so half the values fell through to 0. Filmed battle
    58 is that failure exactly -- a Fujamon that had landed its middle colour
    sent 0x000A and was read as "0 super hits".

    A selector the table does not have is a device saying something we have
    not measured; it reads as no charge rather than as a guess.
    """
    return penc_super_hits(colour_row(value)) if colour_knows(value) else 0


def _penc_band_of_selector(selector):
    """Which colour band a selector means on the Pendulum Color, or None.

    The pool is shared but the table choosing from it is not, so this asks
    PENC's own map which (stage, band) sends this index. Where two stages
    send the same one -- 14 is the Megahit everywhere -- the band is still
    unambiguous, which is why only the band comes back and not the stage.
    """
    values = _pattern_table("PENC")["charge_to_selector"]["values"]
    bands = set()
    for stage_map in values.values():
        for name, value in stage_map.items():
            if value == selector:
                bands.add(PENC_BANDS.index(name))
    return bands.pop() if len(bands) == 1 else None


def penc_band_from_wire(value):
    """The colour band a selector names, or None if it is not on record."""
    return _penc_band_of_selector(value)


def get_penc_enemy_pattern(stage=1):
    """The five attacks a Pendulum Color quest enemy throws, by stage.

    An enemy plays no charge, so it reads its stage and takes one of that
    stage's own measured rows -- the same shape PENOG's and DM20's enemy
    tables use, so an enemy never throws a pattern the device could not.
    **Which band each stage fights at is ours by construction**: nothing on a
    device says what an enemy shakes. The bands were picked to reproduce the
    damage the invented table already dealt, so this changes which rows are
    thrown and not how hard a quest hits.
    """
    bands = _pattern_table("PENC")["enemy_patterns"]["bands"]
    try:
        stage = int(stage or 1)
    except (TypeError, ValueError):
        stage = 1
    stage = max(1, min(stage, len(bands)))
    return get_penc_pattern(stage, PENC_BANDS.index(bands[str(stage)]))


#: The original Digital Monster's adventure table, from DMOG.json.
DMOG_PVE_TABLE = None


def get_dmog_pve_pattern(slot, rng=None):
    """The six attacks a Digital Monster adventure battle throws, by slot.

    The wire has two attack values and no more, so the module reproducing it
    has two as well -- but the adventure simulator used to draw from the DMX
    table, whose values run 1-5, and clamp them to the module's limit. Nearly
    every value in that table is 2 or above, so nearly every round came out
    as a 2: the strongest attack available, every time, which is not a
    battle so much as a formality.

    This table is 1s and 2s to begin with. Which mix comes out is the
    attacker's battle slot -- all singles at slot A, all doubles at L, and a
    ramp between -- with several arrangements per slot so the rounds are not
    predictable. The slot is the Digital Monster's own measure of how strong
    a Digimon is, which makes it the right thing to key on.
    """
    global DMOG_PVE_TABLE
    if DMOG_PVE_TABLE is None:
        pattern_path = os.path.join(os.path.dirname(__file__), "..", "..",
                                    "data", "attack_patterns", "DMOG.json")
        DMOG_PVE_TABLE = _load_json(pattern_path)

    rows = DMOG_PVE_TABLE["slots"]
    row = next((r for r in rows if r["hex"] == slot), None)
    if row is None:
        # Off the chart in either direction: take the nearest end.
        row = rows[0] if slot < rows[0]["hex"] else rows[-1]
    choices = row["patterns"]
    picker = rng.choice if rng is not None else random.choice
    return list(picker(choices))


#: The Pendulum's own table, from PENOG.json.
PENOG_PATTERN_TABLE = None


def _penog_table():
    global PENOG_PATTERN_TABLE
    if PENOG_PATTERN_TABLE is None:
        pattern_path = os.path.join(os.path.dirname(__file__), "..", "..",
                                    "data", "attack_patterns", "PENOG.json")
        PENOG_PATTERN_TABLE = _load_json(pattern_path)
    return PENOG_PATTERN_TABLE


def get_penog_pattern(charge):
    """The five rounds a Pendulum throws for a given charge, damage per round.

    The wire carries five rounds of weak (1) or strong (2), and the charge is
    what picks them: a Pendulum 20th in its legacy Pendulum mode plays Count
    Match Classic before the battle, and it sent an Attack pattern with a
    strong round while announcing **effort 0** -- which the training meter
    could not have produced. So the table is indexed by the charge.

    *charge* is the **raw shake count**, 0-40 -- what Count Match Classic
    actually counted -- not the banded 0-3 quality the rest of the game uses,
    which throws most of a played charge away before it reaches the packet.

    Only the endpoints are the document's: an empty meter is five weak rounds
    and a full one the five strong ones its Ikkakumon sends. The ramp between,
    and which rounds turn strong within a band, are ours.
    """
    table = _penog_table()
    rows = table["patterns"]
    charge = max(0, min(int(charge or 0), table["max_charge"]))
    return list(rows[charge]["pattern"])


def get_penog_enemy_pattern(stage):
    """The five rounds an adventure enemy throws on the Pendulum's line.

    An enemy plays no charge, so there is no meter to read it from. Its
    stage stands in instead -- Baby I all weak through Super Ultimate all
    strong -- which is the same thing the wire's own slot chart says about
    relative strength: "higher Stage Digimon being stronger than lower stage
    ones". Rows are in PENOG.json's `enemy_patterns`.
    """
    rows = _penog_table()["enemy_patterns"]
    stage = int(stage or 1)
    for row in rows:
        if row["stage"] == stage:
            return list(row["pattern"])
    # Off either end of the chart: take the nearest.
    return list(rows[0]["pattern"] if stage < rows[0]["stage"]
                else rows[-1]["pattern"])


def get_attack_pattern(level, mini_game, protocol="DMX", stage=None):
    """The attack types a Digimon uses, one per round.

    ``stage`` is the attacker's Omnipet stage, and on both tiered lines it is
    the **first** thing the row is chosen by -- see `_stage_tier`.

    **The DMX and the Pendulum Z do not share a table.** They share the wire,
    the five attack types and the level ladder, and nothing else: of the
    sixteen blocks read off a Pendulum Z, eight also appear in DMX.json and
    eight appear nowhere in it, and the two that agree at high stages do not
    even agree about which stage. Each reads its own file, and there is no
    longer any path from one to the other -- the low-stage special case that
    used to send a Pendulum Z's Baby I and Baby II into DMX.json is gone,
    because those rows are in PENZ.json where they belong.
    """
    if protocol in TIERED_PROTOCOLS:
        return _tiered_pattern(protocol, stage, level, mini_game)
    if protocol in ("DMC", "PENC"):
        # Not read off a Digital Monster Color, and never reached from a
        # battle: the Colour wire exchanges a verdict, so its DCom and versus
        # paths stage `verdict_rounds` and its adventure battles read the
        # `pve` table. PENC used to fall through every branch here and return
        # **None**, which a caller indexing the result would have died on.
        # the pre-measurement (level, charge) assignments this line has always
        # drawn, kept verbatim under its own name.
        table = _dmc_levels()
        for assign in table["assignments"]:
            if assign["level"] == level and assign["mini-game"] == mini_game:
                pattern_id = assign["pattern_id"]
                break
        else:
            pattern_id = 1
        for pat in table["patterns"]:
            if pat["id"] == pattern_id:
                return list(pat["pattern"])
        return [1, 1, 1, 1, 1]
    elif protocol == "DMC_WINNER":
        return list(_dmc_patterns()["winner"]["pattern"])
    elif protocol == "DMC_LOOSER":
        return list(_dmc_patterns()["loser"]["pattern"])
    elif protocol == "PEN20":
        # Its own measured table, not DM20's -- see
        # get_20th_single_battle_attack_pattern.
        return get_20th_single_battle_attack_pattern(mini_game, "PEN20")

    # DMOG, PENOG and DM20 reach their tables by their own names --
    # `get_dmog_pve_pattern`, `get_penog_pattern`,
    # `get_20th_single_battle_attack_pattern` -- so nothing asks for them
    # here. Falling off the end returned **None**, which a caller indexing
    # the result would have died on; five weak rounds is a row every line
    # has, and a wrong answer is easier to see than a crash.
    return [1, 1, 1, 1, 1]

#: value -> damage for the DMX wire, filled from DMX.json on first use.
DMX_DAMAGE_BY_VALUE = None
_DAMAGE_BY_PROTOCOL = {}


def get_attack_damage(pattern_value, protocol="DMX"):
    """The HP a pattern value costs, which is not the value itself.

    What an attack pattern stores is the attack *type*: it picks the
    projectile sprite and the critical slide-in as well as the damage. The
    damage is a separate scale, and it is simply the sprite strength times
    the sprite count -- exactly what each type's sprite spec already
    describes:

        SINGLE_WEAK      1x atk_main               1 x 2 =  2
        SINGLE_STRONG    1x atk_alt                1 x 3 =  3
        DOUBLE_WEAK      2x atk_main               2 x 2 =  4
        DOUBLE_STRONG    2x atk_alt                2 x 3 =  6
        CRITICAL         1x atk_alt2 at 2x size    2 x 5 = 10

    Measured, not guessed. Ten battles against a real Digital Monster X
    were filmed on both screens and its HP bar read off round by round --
    one segment is one HP (`utilities/DMX/battle.txt`, reproduced by
    `tests/test_battle_protocols.py`). Every figure above is a direct
    reading: a critical against a full 18 leaves 8, and a single pattern
    walked down 16/10/6/4/0 gives the other four.

    Only the DMX wire has been measured; every other protocol keeps the
    pattern value as its damage, unchanged.
    """
    # Keyed on which TABLE the value came from, not which wire carried it.
    # PENZ shares the five types and their damage -- battle 12 measured a
    # critical at 10 on a Pendulum Z, the same as a DMX -- so testing for
    # "DMX" alone silently gave PENZ the raw value and a critical cost 5.
    #
    # DMC rides the same wire and does NOT share the table: its own rows are
    # 1s and 2s where the value simply is the damage, which is what
    # `ATTACK_ANIMATION = "count"` means on that line. Reading it here would
    # turn a 2 into 3 and spend 9 on a verdict battle's 5 HP bar.
    if protocol not in TIERED_PROTOCOLS:
        return pattern_value

    if protocol not in _DAMAGE_BY_PROTOCOL:
        pattern_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "attack_patterns", protocol + ".json")
        table = _load_json(pattern_path)
        _DAMAGE_BY_PROTOCOL[protocol] = {
            spec["value"]: spec.get("damage", spec["value"])
            for spec in table.get("attack_types", {}).values()
        }
    return _DAMAGE_BY_PROTOCOL[protocol].get(pattern_value, pattern_value)


def get_dm20_attack_pattern(tag_meter, taps):
    """
    Retrieves the correct attack pattern for the DM20 protocol based on tag_meter and taps.
    This is the legacy method - use get_dm20_single_battle_attack_pattern for single battles.
    
    :param tag_meter: The tag meter value (0-3) for tag battles, or 0 for single battles
    :param taps: The number of taps (0-14) from the minigame
    :return: A list representing the attack pattern [1-5 damage values]
    """
    global DM20_PATTERN_TABLE
    if DM20_PATTERN_TABLE is None:
        # Load the DM20 pattern table from the JSON file
        pattern_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "attack_patterns", "DM20.json")
        DM20_PATTERN_TABLE = _load_json(pattern_path)

    # Search for the matching pattern in the table
    for entry in DM20_PATTERN_TABLE:
        if entry["bar1"] == tag_meter and taps in entry["taps"]:
            return entry["pattern"]

    # Fallback pattern if no match is found
    return [1, 1, 1, 1, 1]
