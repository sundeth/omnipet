"""
The Pendulum Color Godzilla Edition's Count Match Color: a hidden variant of
the minigame. When the first pet of the party belongs to a module whose
G-Cell style is PENGZ (utils.gcell_rules), training and the adventure's
battle charge follow these rules instead of the Pendulum Color's
(ui.minigames.minigame_session.count_match_rank and PENC's stage table).

Read out of the PENGZ firmware (penc_godzilla.bin, Sunplus u'nSP; the
listing is utilities/PENGZ/disasm/code_0_80000.txt):

  * The shakes fall in a bucket, 0-6, at 0 / 3 / 5 / 7 / 9 / 11 / 13 shakes
    (table at CPU 0x20D320, read by 0x20D683).
  * A bucket shows a colour: none, then Blue (3-6 shakes), Yellow (7-10) and
    Red (11+) (0x20D309, sprites 132-135).
  * Attribute x G-Cell band x bucket gives a score, 0-14 (0x20D344, one
    4 x 6 block per attribute, read by 0x20D6C2). The band is the G-Cell
    count, 0-3 / 4-7 / 8-10 / 11-14 (a partial cell counting); the stage
    only sets the cell's size.
  * The score is a row of the Colour family's attack-pattern pool
    (src/data/attack_patterns/COLOUR_ROWS.json, the same fifteen rows at
    0x20D2AF): the training throws its first five shots, and its super hits
    are the 2s among them (0x208C1B builds that five-shot mask).

So humulos's super-hit chart is this table seen through the pool, its
"Data / 11-14: 4 5 2 0 2 3" included (scores 5 and 7 are both two-super
rows). Every fifth training brings Anguirus, which pays the module's
gcell_training_gain_anguirus instead of gcell_training_gain.
"""
import json
import os

from utils import gcell_rules

#: Shakes at which each bucket starts.
BUCKET_STARTS = (0, 3, 5, 7, 9, 11, 13)

#: Count Match colours (ui.minigames.count_match): 1 Red, 2 Yellow, 3 Blue,
#: 4 none yet. Bucket -> colour.
BUCKET_COLOURS = (4, 3, 3, 2, 2, 1, 1)

#: Attribute -> G-Cell band -> score for buckets 1-6 (bucket 0 scores 0).
#: The firmware's attribute order is Free, Virus, Data, Vaccine; its
#: Vaccine block repeats Free's.
SCORES = {
    "": ((12, 14, 5, 9, 4, 0), (0, 3, 14, 13, 7, 10),
         (12, 14, 1, 0, 9, 8), (6, 11, 0, 2, 14, 13)),
    "Vi": ((6, 9, 12, 14, 3, 0), (13, 14, 0, 2, 11, 7),
           (4, 0, 5, 10, 14, 12), (0, 1, 14, 13, 10, 8)),
    "Da": ((13, 14, 7, 9, 2, 0), (10, 6, 0, 3, 14, 12),
           (0, 4, 13, 14, 11, 8), (12, 14, 5, 0, 7, 10)),
}
SCORES["Va"] = SCORES[""]

#: Every how many trainings Anguirus comes.
ANGUIRUS_EVERY = 5

_POOL = None


def pool():
    """The Colour attack-pattern pool, fifteen rows of six."""
    global _POOL
    if _POOL is None:
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "data", "attack_patterns", "COLOUR_ROWS.json")
        with open(path, encoding="utf-8") as fh:
            _POOL = json.load(fh)["rows"]
    return _POOL


def _module_of(pet):
    try:
        from utils.module_utils import get_module
        return get_module(getattr(pet, "module", None))
    except Exception:
        return None


def applies(pet):
    """Whether *pet*'s module plays these rules (its G-Cell style is PENGZ)."""
    if pet is None:
        return False
    return gcell_rules.style_of(_module_of(pet)) == gcell_rules.PENGZ


def bucket(shakes):
    """The 0-6 bucket *shakes* reaches."""
    shakes = max(0, int(shakes or 0))
    return max(i for i, start in enumerate(BUCKET_STARTS) if shakes >= start)


def colour(shakes):
    """The colour the count shows after *shakes* (1 Red, 2 Yellow, 3 Blue,
    4 none yet)."""
    return BUCKET_COLOURS[bucket(shakes)]


def band(pet, module=None):
    """The pet's G-Cell band, 0-3: 0-3, 4-7, 8-10 or 11-14 cells."""
    cells = gcell_rules.cells(module or _module_of(pet), pet)
    if cells <= 3:
        return 0
    if cells <= 7:
        return 1
    if cells <= 10:
        return 2
    return 3


def _row(pet, module=None):
    table = SCORES.get(getattr(pet, "attribute", "") or "", SCORES[""])
    return table[band(pet, module)]


def score(pet, shakes, module=None):
    """The 0-14 score: the pool row the pet throws."""
    b = bucket(shakes)
    return 0 if b == 0 else _row(pet, module)[b - 1]


def pattern(row):
    """The six attacks of pool row *row* (1 normal, 2 super)."""
    return list(pool()[max(0, min(14, int(row)))])


def super_hits(row):
    """Super hits in the five shots a training throws from row *row*."""
    return sum(1 for shot in pattern(row)[:5] if shot >= 2)


def target_colour(pet, module=None):
    """The colour READY asks for: the one where the Megahit (score 14) is."""
    row = _row(pet, module)
    return BUCKET_COLOURS[row.index(14) + 1]


def grade(supers):
    """The 0-3 training outcome: no super hit, 1-2, 3-4, a Megahit."""
    if supers >= 5:
        return 3
    if supers >= 3:
        return 2
    if supers >= 1:
        return 1
    return 0


def count_training(pet):
    """Count a training that got past the shaking; True when it is the one
    Anguirus comes to (every fifth)."""
    count = (getattr(pet, "pengz_trainings", 0) or 0) + 1
    pet.pengz_trainings = count
    return count % ANGUIRUS_EVERY == 0
