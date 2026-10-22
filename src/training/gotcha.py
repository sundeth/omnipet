#=====================================================================
# Gotcha (ゲッチュー!, the Digivice iC 20X)
#=====================================================================
"""Gotcha!, the iC 20X's catch-Chuumon minigame.

Sources: the owner's account (2026-10-20: Chuumon walks left and right at
several speeds, shown as arrows on both sides at the top, and A drops the
trap to catch him), the playbook's 3, 5 and 7 catches paying 10/30/50 P,
and the owner's video of a 20X (``utilities/IC/10.mp4`` at 137-232 s:
three games, twelve drops -- nine catches, three misses -- and one stage
cleared), read frame by frame (``utilities/IC/video_analysis/gotcha/``)
with each key's chirp. The sprites are in
``utilities/IC/make_digi_whack_mash_sprites.py``.

* The 20X's READY and START open it (IC20Minigame). The trap hangs at the
  top, columns 8-23, its bottom on row 9; Chuumon walks along the bottom,
  rows 16-31, from the right edge, a column a step. At either edge he
  turns where he stands (that is a step) and takes a new speed: a step
  every 360 ms with no arrows, every 250 ms with an arrow a side, every
  125 ms with two (the arrows stand at the top corners and point in).
  Each game opens at a step every 280 ms, with no arrows. **Inferred:**
  that a turn picks its speed at random, among those three -- the film
  shows no order, one turn kept its speed, and none of its eight turns
  went back to the opening speed. A new stage keeps the speed (seen once).
* A -- or a click or a tap anywhere -- drops the trap: a row lower every
  FALL_ROW_MS while Chuumon walks on under it. When its bottom reaches
  row 15, just over his head, he stops. Under it -- his left column 7-9,
  centred at 8 -- he is caught: the trap falls on over him to row 23,
  where only his feet show, to the key's chirp; it rests there 580 ms and
  goes back up, and he walks on as he was. Anywhere else (the film's
  misses: 5, 5 and 14) the trap stops where it is, and after 530 ms the
  player's own Digimon shows its defeat for three seconds, to the fail
  sound (the film's was the owner's pet; owner, 2026-10-21): the game is
  over. **Inferred:** whether columns 6 and 10 catch (no drop
  decided there on film), and that the fall's two rates are chosen at
  random (the film's 12 drops: 4 a row every ~94 ms, 8 every ~125 ms).
* Three catches clear stage 1, five stage 2 and seven stage 3 (the
  playbook; the film clears stage 1 with three and misses stage 2's
  fourth); the last catch's rest ends in CLEAR! with the success jingle,
  then READY and START, and Chuumon starts again from the right edge. The
  result is the stages cleared: none BAD, one GOOD, two GREAT, three
  EXCELLENT, paying 0, 10, 30 or 50 P (the film's 0P GET! and 10P GET!).
  Clearing all three is the success that raises Reliability.
"""
import random

import pygame

from core import runtime_globals
from models.animation import PetFrame
from training.ic_minigame import IC20Minigame, LCD, PET_DOTS

#: The trap: 16 dots wide from TRAP_COL and TRAP_ROWS tall, placed by its
#: bottom row -- hanging, where the catch is decided, and landed.
TRAP_COL = 8
TRAP_ROWS = 14
HANG_ROW, DECIDE_ROW, LAND_ROW = 9, 15, 23
#: Chuumon, 16 dots square on rows 16-31; his left column runs 0-16 and
#: starts each stage at the right edge, walking left.
CHUUMON_ROW = 16
LAST_COL = 16
#: Caught when his left column is within CATCH_RANGE of CENTRE_COL.
CENTRE_COL = 8
CATCH_RANGE = 1
#: Speeds: (ms a step, arrows a side). The opening speed, then each
#: turn's pick.
OPENING_SPEED = (280, 0)
SPEEDS = ((360, 0), (250, 1), (125, 2))
#: The trap falls a row every one of these, the faster one drop in
#: FAST_FALL_CHANCE; its first row a row's time after the press.
FALL_ROW_MS = (94, 125)
FAST_FALL_CHANCE = 1 / 3
#: A catch rests landed before the trap goes back up; a miss holds the
#: trap over him before the pet's defeat (the "taunt"), whose two frames
#: take turns: the game's own defeat animation, LOSE and ANGRY.
CATCH_HOLD_MS = 580
MISS_HOLD_MS = 530
TAUNT_FRAME_MS = 500
TAUNT_MS = 3000
TAUNT_FRAMES = (PetFrame.LOSE, PetFrame.ANGRY)
#: The pet stands in the middle of the LCD for it.
TAUNT_COL = TAUNT_ROW = (LCD - PET_DOTS) // 2
#: The speed arrows: rows 2-6, three dots wide; the left ones at columns 0
#: and 4, the right ones mirrored at 29 and 25.
ARROW_ROW = 2
ARROW_COLS = (0, 4)
ARROW_DOTS = 3
#: Catches that clear each stage, and P for the stages cleared: none, 1, 2, 3.
TARGETS = (3, 5, 7)
PRIZES = (0, 10, 30, 50)
#: The device chirps its key sound on the press and again on a catch.
KEY_SOUND = "menu"
FAIL_SOUND = "ic_fail"


class Gotcha(IC20Minigame):
    def __init__(self, ui_manager):
        super().__init__(ui_manager)
        self.stage = 0
        self.catches = 0
        self.cleared = 0
        self.col = LAST_COL
        self.facing = -1                    # -1 walking left, 1 right
        self.step_ms, self.arrows = OPENING_SPEED
        self.next_step = 0
        self.trap_row = HANG_ROW
        self.fall_ms = FALL_ROW_MS[1]
        self.next_row = 0
        self._flipped = {}

    #-----------------------------------------------------------------
    # Rules
    #-----------------------------------------------------------------

    @staticmethod
    def now():
        return pygame.time.get_ticks()

    def start_game(self):
        self.step_ms, self.arrows = OPENING_SPEED
        self.begin_stage()

    def begin_stage(self):
        self.catches = 0
        self.col = LAST_COL
        self.facing = -1
        self.trap_row = HANG_ROW
        self.next_step = self.now() + self.step_ms
        self.set_step("play")

    def take_step(self):
        """Chuumon's next step: a column on, or at an edge a turn where he
        stands and a new speed."""
        end = 0 if self.facing < 0 else LAST_COL
        if self.col == end:
            self.facing = -self.facing
            self.step_ms, self.arrows = random.choice(SPEEDS)
        else:
            self.col += self.facing
        self.next_step += self.step_ms

    def walk(self, until=None):
        """Chuumon's steps due by now (or by *until*)."""
        until = self.now() if until is None else until
        while self.next_step <= until:
            self.take_step()

    def caught(self):
        return abs(self.col - CENTRE_COL) <= CATCH_RANGE

    def drop(self):
        runtime_globals.game_sound.play(KEY_SOUND)
        self.fall_ms = FALL_ROW_MS[0] if random.random() < FAST_FALL_CHANCE else FALL_ROW_MS[1]
        self.next_row = self.now() + self.fall_ms
        self.set_step("drop")

    def lower_trap(self, last_row):
        """The trap's rows due by now, down to *last_row*; True there."""
        now = self.now()
        while self.trap_row < last_row and now >= self.next_row:
            self.trap_row += 1
            self.next_row += self.fall_ms
        return self.trap_row >= last_row

    def update_game(self):
        step = self.step
        if step == "play":
            self.walk()
        elif step == "drop":
            # His steps and the trap's rows in the order they fall due, so
            # he is judged where he stood as it reached DECIDE_ROW.
            while self.next_row <= self.now():
                self.walk(until=self.next_row - 1)
                self.trap_row += 1
                self.next_row += self.fall_ms
                if self.trap_row >= DECIDE_ROW:
                    # He stops where he is; under the trap, it falls on.
                    self.set_step("fall" if self.caught() else "missed")
                    return
            self.walk()
        elif step == "fall":
            if self.lower_trap(LAND_ROW):
                runtime_globals.game_sound.play(KEY_SOUND)
                self.catches += 1
                self.set_step("landed")
        elif step == "landed":
            if self.elapsed() >= CATCH_HOLD_MS:
                self.trap_row = HANG_ROW
                if self.catches >= TARGETS[self.stage]:
                    self.stage_cleared()
                else:
                    self.next_step = self.now() + self.step_ms
                    self.set_step("play")
        elif step == "missed":
            if self.elapsed() >= MISS_HOLD_MS:
                runtime_globals.game_sound.play(FAIL_SOUND)
                self.set_step("taunt")
        elif step == "taunt":
            if self.elapsed() >= TAUNT_MS:
                # The fail sound played as the taunt began.
                self.end_game(self.cleared, PRIZES[self.cleared], succeeded=False, sound=False)
        elif self.update_intro():
            self.begin_stage()

    def stage_cleared(self):
        self.cleared = self.stage + 1
        if self.stage == len(TARGETS) - 1:
            self.end_game(self.cleared, PRIZES[self.cleared], succeeded=True)
            return
        self.stage += 1
        self.start_intro(cleared=True)

    def handle_game_event(self, event):
        if self.step == "play" and (event[0] == "A" or self.tap_pos(event) is not None):
            self.drop()
            return True
        return False

    #-----------------------------------------------------------------
    # Drawing
    #-----------------------------------------------------------------

    def mirrored(self, name):
        """``art(name)`` facing the other way."""
        if name not in self._flipped:
            self._flipped[name] = pygame.transform.flip(self.art(name), True, False)
        return self._flipped[name]

    def draw_game(self, surface):
        step = self.step
        if step in ("clear", "ready", "start"):
            return              # CLEAR!, READY and START: the animated sprite's
        if step == "taunt":
            self.blit_pet(surface, self.alternate(*TAUNT_FRAMES, period=TAUNT_FRAME_MS),
                          TAUNT_COL, TAUNT_ROW)
            return
        if self.facing < 0:
            self.blit_art(surface, "gotcha_chuumon", self.col, CHUUMON_ROW)
        else:
            surface.blit(self.mirrored("gotcha_chuumon"), self.at(self.col, CHUUMON_ROW))
        # Opaque inside: over Chuumon only his feet show below it.
        self.blit_art(surface, "gotcha_trap", TRAP_COL, self.trap_row - TRAP_ROWS + 1)
        for k in range(self.arrows):
            self.blit_art(surface, "gotcha_arrow", ARROW_COLS[k], ARROW_ROW)
            surface.blit(self.mirrored("gotcha_arrow"),
                         self.at(LCD - ARROW_COLS[k] - ARROW_DOTS, ARROW_ROW))
