#=====================================================================
# DigiWhack (デジタタキ, the Digivice iC 20X)
#=====================================================================
"""Digi Whack, the iC 20X's whack-a-Digimon minigame.

Sources: the 20X booklet (p. 23: "stop the cursor with good timing, the
Digimon appears, hit it"), the owner's account of the device (2026-10-07:
one key moves the pointer, the other whacks; a whack lands only on a
Digimon that is out, anything else loses; 3 hits pass to the second stage,
5 to the third, 7 finish it) and the owner's videos of a 20X
(``utilities/IC/10.mp4`` and ``11.mp4``), read frame by frame with each
key's chirp. The sprites are in
``utilities/IC/make_digi_whack_mash_sprites.py``.

* The 20X's READY and START open it (IC20Minigame). Three holes stand in a
  triangle: top, bottom left, bottom right. In each, on its own, a Digimon
  rises (peeks over the rim), sometimes comes out, and sinks back (the
  videos: peeks of 0.4-2 s, outs of about 1.3 s in stage 1 and 1 s in
  stage 2, two at once now and then). Stage 3's outs are shorter still
  (**inferred**: no run reached it on film).
* The pointer stands under one hole and moves only when the device's
  Select key is pressed, a hole a press: top, left, right, top...
  Omnipet's arrow keys and SELECT move it (LEFT and UP back a hole, as a
  convenience the device does not have).
* The Decide key whacks the hole the pointer is under -- Omnipet's A. A
  Digimon that is out is hit: the "!" shows over the hole for HIT_MS and
  the hole empties. Anything else -- an empty hole, a Digimon only
  peeking or sinking -- is a miss and ends the game (the 10.mp4 run that
  failed ended at once on a whack at a hole whose Digimon had gone in).
* With a mouse the pointer follows the hole the mouse is over, and a click
  on a hole whacks it -- as Shuffle points at the bucket hovered and picks
  the one clicked; a finger's tap on a hole whacks it at once. (A first
  click that only moved the pointer left the Digimon, out about a second,
  gone before the second: owner, 2026-10-07, "not working with mouse".)
* Three hits clear stage 1, five stage 2 and seven stage 3; a cleared stage
  shows CLEAR! with the success jingle, then READY and START again. The
  result is the stages cleared: none BAD, one GOOD, two GREAT, three
  EXCELLENT, paying 0, 10, 30 or 50 P (the videos' 10P GET! after one
  stage and 30P GET! after two). Clearing all three is the success that
  raises Reliability.
"""
import random

import pygame

from core import runtime_globals
from training.ic_minigame import IC20Minigame

#: Each hole's top-left dot: top, bottom left, bottom right -- the order the
#: pointer moves in.
HOLES = ((12, 7), (4, 19), (20, 19))
HOLE_DOTS = (8, 5)
#: Where each state's sprite starts, rows above the hole's top.
PEEK_ROWS = 1
OUT_ROWS = 3
HIT_ROWS = 3
#: The pointer: a column in and six rows down from its hole's top.
CURSOR_OFFSET = (1, 6)
#: Hits that clear each stage.
TARGETS = (3, 5, 7)
#: P for the stages cleared: none, 1, 2, 3.
PRIZES = (0, 10, 30, 50)

#: A hole's own cycle, in ms: empty, then a Digimon peeking, then -- one
#: time in OUT_CHANCE -- out for OUT_MS of the stage and sinking (peeking)
#: for SINK_MS, else straight back in.
EMPTY_MS = (400, 1800)
PEEK_MS = (400, 1200)
OUT_CHANCE = 0.6
OUT_MS = (1300, 1000, 800)
SINK_MS = 400
HIT_MS = 500
#: A miss holds the screen a moment before the result.
MISS_HOLD_MS = 800

EMPTY, PEEK, OUT, SINK, HIT = "empty", "peek", "out", "sink", "hit"
NEXT_KEYS = ("RIGHT", "DOWN", "SELECT")
BACK_KEYS = ("LEFT", "UP")


class DigiWhack(IC20Minigame):
    def __init__(self, ui_manager):
        super().__init__(ui_manager)
        self.stage = 0
        self.hits = 0
        self.cleared = 0
        self.pointer = 0
        self.holes = [EMPTY] * len(HOLES)
        self.until = [0] * len(HOLES)      # when each hole's state ends
        self.hit_hole = None

    #-----------------------------------------------------------------
    # Rules
    #-----------------------------------------------------------------

    @staticmethod
    def now():
        return pygame.time.get_ticks()

    def start_game(self):
        self.begin_stage()

    def begin_stage(self):
        self.hits = 0
        self.hit_hole = None
        now = self.now()
        for k in range(len(HOLES)):
            self.holes[k] = EMPTY
            self.until[k] = now + random.randint(*EMPTY_MS)
        self.set_step("play")

    def set_hole(self, k, state, ms):
        self.holes[k] = state
        self.until[k] = self.now() + ms

    def advance_hole(self, k):
        """Hole *k*'s next state, its own one ending."""
        state = self.holes[k]
        if state == EMPTY:
            self.set_hole(k, PEEK, random.randint(*PEEK_MS))
        elif state == PEEK:
            if random.random() < OUT_CHANCE:
                self.set_hole(k, OUT, OUT_MS[self.stage])
            else:
                self.set_hole(k, EMPTY, random.randint(*EMPTY_MS))
        elif state == OUT:
            self.set_hole(k, SINK, SINK_MS)
        else:                                   # SINK, HIT
            self.set_hole(k, EMPTY, random.randint(*EMPTY_MS))

    def move(self, step):
        self.pointer = (self.pointer + step) % len(HOLES)
        runtime_globals.game_sound.play("menu")

    def whack(self):
        runtime_globals.game_sound.play("menu")
        k = self.pointer
        if self.holes[k] == OUT:
            self.hits += 1
            self.hit_hole = k
            self.set_hole(k, HIT, HIT_MS)
        else:
            self.set_step("miss")

    def update_game(self):
        if self.step == "play":
            self.update_play()
        elif self.step == "miss":
            if self.elapsed() >= MISS_HOLD_MS:
                self.end_game(self.cleared, PRIZES[self.cleared], succeeded=False)
        elif self.update_intro():
            self.begin_stage()

    def update_play(self):
        now = self.now()
        for k in range(len(HOLES)):
            if now < self.until[k]:
                continue
            if self.holes[k] == HIT:
                self.hit_hole = None
                if self.hits >= TARGETS[self.stage]:
                    self.stage_cleared()
                    return
            self.advance_hole(k)

    def stage_cleared(self):
        self.cleared = self.stage + 1
        if self.stage == len(TARGETS) - 1:
            self.end_game(self.cleared, PRIZES[self.cleared], succeeded=True)
            return
        self.stage += 1
        self.start_intro(cleared=True)

    def hole_at(self, pos):
        """The hole a tap at screen *pos* landed on (with the rows a
        Digimon out stands above it), or None."""
        for k, (col, row) in enumerate(HOLES):
            x, y = self.at(col, row - OUT_ROWS)
            rect = pygame.Rect(x, y, HOLE_DOTS[0] * self.dot(), (HOLE_DOTS[1] + OUT_ROWS) * self.dot())
            if rect.collidepoint(pos):
                return k
        return None

    def handle_game_event(self, event):
        if self.step != "play" or self.hit_hole is not None:
            return False
        key, data = event
        if key == "A":
            self.whack()
            return True
        if key in NEXT_KEYS or key in BACK_KEYS:
            self.move(1 if key in NEXT_KEYS else -1)
            return True
        if key == "MOUSE_MOTION" and data and "pos" in data:
            # The mouse is the pointer: it stands under the hole hovered.
            k = self.hole_at(data["pos"])
            if k is not None and k != self.pointer:
                self.pointer = k
                runtime_globals.game_sound.play("menu")
            return True
        pos = self.tap_pos(event)
        if pos is not None:
            # A click or a tap whacks the hole it lands on.
            k = self.hole_at(pos)
            if k is not None:
                self.pointer = k
                self.whack()
            return True
        return False

    #-----------------------------------------------------------------
    # Drawing
    #-----------------------------------------------------------------

    def hole_art(self, k):
        """The sprite hole *k* shows and the rows above its top it starts."""
        return {HIT: ("digi_whack_hit", HIT_ROWS), OUT: ("digi_whack_out", OUT_ROWS),
                PEEK: ("digi_whack_peek", PEEK_ROWS), SINK: ("digi_whack_peek", PEEK_ROWS),
                }.get(self.holes[k], ("digi_whack_hole", 0))

    def draw_game(self, surface):
        if self.step not in ("play", "miss"):
            return              # CLEAR!, READY and START: the animated sprite's
        for k, (col, row) in enumerate(HOLES):
            name, above = self.hole_art(k)
            self.blit_art(surface, name, col, row - above)
        col, row = HOLES[self.pointer]
        self.blit_art(surface, "digi_whack_cursor", col + CURSOR_OFFSET[0], row + CURSOR_OFFSET[1])
