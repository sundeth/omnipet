#=====================================================================
# DigiMash (デジレンダ, the Digivice iC 20X)
#=====================================================================
"""Digi Mash, the iC 20X's button-mashing minigame.

Sources: the 20X booklet (p. 24: "hit repeatedly before the time limit to
make the Digimon evolve"; ▶00◀ with Puwamon, ▶20◀ with Falcomon), the
playbook's ladder (0/10/20/30/50 P), the owner's account of the line
(2026-10-07: Puwamon, Pinamon, Falcomon, Peckmon, LoaderLeomon) and the
owner's videos of a 20X (``utilities/IC/10.mp4`` and ``11.mp4``, nine runs,
the counter read on every frame). The sprites are in
``utilities/IC/make_digi_whack_mash_sprites.py``.

* The 20X's READY and START open it (IC20Minigame); then A, as fast as it
  goes, for MASH_MS (4.3-4.5 s from START in the videos, at up to eight
  presses a second). Each press counts on the two-digit counter at the top
  and beeps.
* The Digimon at the bottom is the form the count has reached, and steps
  two columns right and back about every 0.3 s (SWAY_MS): Puwamon, then
  Falcomon from the 16th press, Peckmon from the 21st and LoaderLeomon
  from the 26th (the videos: the playbook's 15, 20 and 25 passed). Pinamon,
  in the owner's line, does not show in the filmed runs (0-28 presses), and
  nobody filmed the 31st press: past it the top tier pays its 50 P with
  LoaderLeomon still standing.
* When time is up the form holds a moment, then the result: Puwamon BAD,
  Falcomon GOOD, Peckmon and LoaderLeomon GREAT, 31 presses EXCELLENT,
  paying 0, 10, 20, 30 or 50 P. The top tier is the success that raises
  Reliability (**inferred**, as the 10X's games count clearing them); any
  evolution ends on the success jingle, Puwamon on the fail sound.
"""
from core import runtime_globals
from training.ic_minigame import IC20Minigame

MASH_MS = 4400
#: The form after the time is up, before the result.
HOLD_MS = 1200
SWAY_MS = 300
#: The counter: tens at column 10, units at 17, rows 1-7, a 5-dot glyph
#: every DIGIT_PITCH dots in digi_mash_digits.png.
TENS_COL, UNITS_COL, DIGITS_ROW = 10, 17, 1
DIGIT_DOTS, DIGIT_PITCH = 5, 6
MAX_COUNT = 99
#: Presses, the form, its art, its row, its two columns (left, right).
FORMS = (
    (0, "Puwamon", "digi_mash_puwamon", 21, (6, 8)),
    (16, "Falcomon", "digi_mash_falcomon", 15, (6, 8)),
    (21, "Peckmon", "digi_mash_peckmon", 7, (6, 8)),
    (26, "LoaderLeomon", "digi_mash_loaderleomon", 7, (2, 4)),
    (31, "top", "digi_mash_loaderleomon", 7, (2, 4)),
)
#: Each tier's result grade and prize, Puwamon to the top.
GRADES = (0, 1, 2, 2, 3)
PRIZES = (0, 10, 20, 30, 50)
PRESS_SOUND = "ic_press"


class DigiMash(IC20Minigame):
    def __init__(self, ui_manager):
        super().__init__(ui_manager)
        self.count = 0

    def start_game(self):
        self.set_step("mash")

    def form(self):
        """The index into FORMS of the form *count* has reached."""
        return max(k for k, entry in enumerate(FORMS) if self.count >= entry[0])

    def update_game(self):
        if self.step == "mash" and self.elapsed() >= MASH_MS:
            self.set_step("hold")
        elif self.step == "hold" and self.elapsed() >= HOLD_MS:
            k = self.form()
            self.end_game(GRADES[k], PRIZES[k], succeeded=k == len(FORMS) - 1,
                          cleared=k > 0)

    def handle_game_event(self, event):
        if self.step == "mash" and (event[0] == "A" or self.tap_pos(event) is not None):
            self.count = min(MAX_COUNT, self.count + 1)
            runtime_globals.game_sound.play(PRESS_SOUND)
            return True
        return False

    def blit_digit(self, surface, digit, col):
        art = self.art("digi_mash_digits")
        size = self.dot()
        x, y = self.at(col, DIGITS_ROW)
        source = (digit * DIGIT_PITCH * size, 0, DIGIT_DOTS * size, art.get_height())
        surface.blit(art, (x, y), source)

    def draw_game(self, surface):
        tens, units = divmod(self.count, 10)
        self.blit_digit(surface, tens, TENS_COL)
        self.blit_digit(surface, units, UNITS_COL)
        _, _, art, row, cols = FORMS[self.form()]
        # The sway runs on its own clock, through the hold too.
        col = cols[(self.elapsed() // SWAY_MS) % 2]
        self.blit_art(surface, art, col, row)
