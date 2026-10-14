#=====================================================================
# PoopDodge (ウンチよけ, the Digivice iC 10X)
#=====================================================================
"""Poop Dodge, the iC 10X's dodging minigame: Sukamon throws poop, and the
Digimon dodges it up and down on its way to the goal.

Sources: the playbook's page on it (p. 54, scan 60), which prints every
course; the Master Book (p. 62) for the keys and the pay; and the owner's
video of a 10X (``utilities/IC/3.mp4``, one run through all three stages)
for the timing. The sprites are in
``utilities/IC/make_poop_dodge_shuffle_sprites.py``.

* The opening, in place of READY: Sukamon a moment, then throwing -- the
  playbook's frame sliding six dots left and back (the video's second pose,
  between, is too blurred to read; the throwing frame stands in for it).
  The device opens it silently and starts the game with its own tune.
* The LCD is four lanes of eight rows. The Digimon stands at the right
  (columns 24-30), in the second lane at first, and UP/DOWN move it a lane
  (the device's Select and Decide keys); with a mouse or a finger, two
  arrow buttons beside it do. The course scrolls right past it a dot every
  STEP_MS, the same in every stage.
* Three stages, each one of four courses at random (the playbook's A-D),
  printed as screens of four 8-dot columns from the goal (left) to the
  start (right). The stage's sound plays as its goal edge leaves the LCD's
  left side -- the video's 32.3 and 57.7 s, its success at 83.1 s.
* A poop touching the Digimon ends the game, even one it has passed: it is
  wide, and the Digimon moved into it (the playbook's warning). **Inferred:**
  what a hit shows -- the run freezes and the Digimon blinks before the
  result; the video has no hit.
* The result is the stages cleared: a hit in stage 1 BAD, in stage 2 GOOD,
  in stage 3 GREAT, none EXCELLENT (owner, 2026-10-06). They pay 0, 10, 20
  or 50 P (the books), and all three cleared is the success that raises
  Reliability.

The poops are the game's own (``assets/Poop1.png``, ``Poop2.png``, in the
pet's sprite format: one maze cell, 8 dots a side), their flies taking
turns. The whole course is drawn once per frame of them, at the art's own
scale; each frame of the game shows one window of it, scaled to the LCD only
when the course has moved a dot or the flies have turned.
"""
import random

import pygame

from core import runtime_globals
from training.ic_minigame import ART_DOT, LCD, ICMinigame
from ui.components.button import Button
from utils.asset_utils import image_load

#: Each stage's courses, as the playbook prints them: four lanes, top to
#: bottom, each a column of 8 dots per character from the goal (left) to
#: the start (right), "#" a poop. The screens are four characters wide.
COURSES = {
    1: {
        "A": (
            ".#.. .... .... .... .... ....",
            "..#. .#.. .... .#.. .... ....",
            ".... .... ..#. .... ..#. ....",
            "#... ..#. .... ..#. .... ....",
        ),
        "B": (
            ".#.. .... ..#. ..#. ..#. ....",
            "..#. .... ..#. ..#. ..#. ....",
            ".... ..#. ..#. ..#. ..#. ....",
            "#... .... .... .... .... ....",
        ),
        "C": (
            ".#.. .... .... .... .... ....",
            "..#. .#.. .#.# .#.# .... ....",
            ".... .... ..## ..## ..#. ....",
            "#... ..#. .... .... .... ....",
        ),
        "D": (
            ".#.. #### #### #### .### ....",
            "..#. .... .... .... .... ....",
            ".... #### #### #### .... ....",
            "#... #### #### #### ..## ....",
        ),
    },
    2: {
        "A": (
            ".... ..#. .... ..#. ..#.",
            ".#.. .... .#.. .... ....",
            ".... .... .... .... ....",
            "..#. .#.. ..#. .#.. .#..",
        ),
        "B": (
            ".... #### #### .### ..#.",
            ".#.. .... .... .... ....",
            ".... #### #### .... ....",
            "..#. #### #### ..## .#..",
        ),
        "C": (
            ".... ..#. .... .#.. ..#.",
            ".#.. .... .#.. ..#. ....",
            ".... .... .... .... ....",
            "..#. .#.. ..#. #... .#..",
        ),
        "D": (
            ".... .... ..#. ..#. ..#.",
            ".#.. .... ..#. ..#. ....",
            ".... .... ..#. ..#. ....",
            "..#. .... .... .... .#..",
        ),
    },
    3: {
        "A": (
            ".... #### .#.# .#.. .#.#",
            ".... #### #... ..#. #...",
            ".... .... ..#. .... ..#.",
            ".... #### #..# #... #..#",
        ),
        "B": (
            ".... .#.# .... .... .#.#",
            ".... #... .#.# ###. #...",
            ".... ..#. ..#. ##.. ..#.",
            ".... #..# #.#. ...# #..#",
        ),
        "C": (
            ".... .... .#.. ##.# .#.#",
            ".... .... ..#. .##. #...",
            ".... ..#. .... .... ..#.",
            ".... .... #... #.## #..#",
        ),
        "D": (
            ".... ...# ##.# #### .#.#",
            ".... ##.. .##. #### #...",
            ".... ###. .... .... ..#.",
            ".... .... #.## #### #..#",
        ),
    },
}

LANES = 4
CELL = 8                    # dots a lane is tall, and a poop wide
PLAYER_COL = 24             # the Digimon's columns: 24-30
PLAYER_WIDTH = 7
START_LANE = 1
#: Milliseconds the course takes a dot (the video: 160 dots in 25.4 s).
STEP_MS = 159
#: Empty dots before the first stage's start screen (the video's first poop
#: comes 3.25 s in); empty dots after the goal, for the view to end on.
LEAD_IN = 20
RUN_OUT = LCD
#: A stage counts as cleared when its goal edge is this far past the LCD's
#: left side (the video: 2-3 dots).
CLEAR_PAST = 2

#: The opening (the video's 2.35-4.3 s): Sukamon still, then the throwing
#: frame a dot further left every SLIDE_MS, held where the unread second
#: pose stands, then back a dot at a time.
STILL_MS = 450
SLIDE_MS = 67
THROW_OUT = range(-1, -8, -1)          # -1 ... -7
HOLD_AT, HOLD_MS = -10, 470
THROW_BACK = range(-10, -3)            # -10 ... -4
READY_TOTAL_MS = STILL_MS + (len(THROW_OUT) + len(THROW_BACK)) * SLIDE_MS + HOLD_MS

#: The poops' flies turn this often.
FLY_MS = 500
#: A hit: the run stops and the Digimon blinks, then the result.
HIT_MS = 1200
BLINK_MS = 150

START_SOUND = "ic_poop_start"
STAGE_SOUND = "ic_poop_stage"
PRIZES = (0, 10, 20, 50)

#: The arrow buttons for a mouse or a finger: beside the Digimon, at the
#: LCD's right edge (base coordinates of the 240-pixel layout).
BUTTON_SIZE = 30
BUTTON_X = 240 - BUTTON_SIZE - 1
UP_Y, DOWN_Y = 40, 240 - BUTTON_SIZE - 40


def course_lanes(stage, name):
    """A course as four lane strings, a character per 8-dot column."""
    return [lane.replace(" ", "") for lane in COURSES[stage][name]]


class PoopDodge(ICMinigame):
    READY_MS = READY_TOTAL_MS

    def __init__(self, ui_manager):
        super().__init__(ui_manager)
        self.courses = {stage: random.choice("ABCD") for stage in COURSES}
        self.lane = START_LANE
        self.cleared = 0
        self._build_course()
        self.frozen_view = self.start_view
        self._poop_frames = None
        self._view = None           # (key, scaled surface)
        self.up_button = self.down_button = None
        self._make_buttons()

    #-----------------------------------------------------------------
    # The course
    #-----------------------------------------------------------------

    def _build_course(self):
        """Lay the stages out on one map, goal at the left: run-out, stage
        3, stage 2, stage 1, lead-in. Each lane is a row of dots, True
        where a poop is; ``goal_edges[n]`` is where stage n's goal is."""
        width = RUN_OUT
        cells = []                  # (dot column, lane)
        self.goal_edges = {}
        for stage in (3, 2, 1):
            lanes = course_lanes(stage, self.courses[stage])
            self.goal_edges[stage] = width
            for lane, row in enumerate(lanes):
                for col, char in enumerate(row):
                    if char == "#":
                        cells.append((width + col * CELL, lane))
            width += len(lanes[0]) * CELL
        width += LEAD_IN
        self.map_width = width
        self.cells = cells
        self.occupied = [[False] * width for _ in range(LANES)]
        for x, lane in cells:
            for dx in range(CELL):
                self.occupied[lane][x + dx] = True
        self.start_view = width - LCD

    def view_left(self):
        """The map's dot at the LCD's left edge now."""
        if self.step != "run":
            return self.frozen_view
        return self.start_view - self.elapsed() // STEP_MS

    def hits(self, view_left=None, lane=None):
        """Whether a poop touches the Digimon."""
        view_left = self.view_left() if view_left is None else view_left
        lane = self.lane if lane is None else lane
        row = self.occupied[lane]
        first = view_left + PLAYER_COL
        return any(row[first:first + PLAYER_WIDTH])

    #-----------------------------------------------------------------
    # Rules
    #-----------------------------------------------------------------

    def start_game(self):
        self.frozen_view = self.start_view
        self.set_step("run")
        runtime_globals.game_sound.play(START_SOUND)

    def update_game(self):
        if self.step == "run":
            view = self.view_left()
            stage = self.cleared + 1
            if view <= self.goal_edges[stage] - CLEAR_PAST:
                self.cleared = stage
                if stage == 3:
                    self.frozen_view = view
                    self.end_game(3, PRIZES[3], succeeded=True)
                    return
                runtime_globals.game_sound.play(STAGE_SOUND)
            if self.hits(view):
                self.frozen_view = view
                self.set_step("hit")
        elif self.step == "hit" and self.elapsed() >= HIT_MS:
            self.end_game(self.cleared, PRIZES[self.cleared], succeeded=False)

    def move(self, step):
        lane = max(0, min(LANES - 1, self.lane + step))
        if lane != self.lane:
            self.lane = lane
            if self.hits():
                self.frozen_view = self.view_left()
                self.set_step("hit")

    def handle_game_event(self, event):
        if self.step != "run":
            return False
        event_type = event[0]
        if event_type in ("UP", "DOWN"):
            self.move(-1 if event_type == "UP" else 1)
            return True
        pos = self.tap_pos(event)
        if pos is not None and self.pointer_mode():
            for button, step in ((self.up_button, -1), (self.down_button, 1)):
                if button is not None and button.rect.collidepoint(pos):
                    self.move(step)
                    return True
        return False

    #-----------------------------------------------------------------
    # Buttons
    #-----------------------------------------------------------------

    @staticmethod
    def pointer_mode():
        return runtime_globals.INPUT_MODE in (runtime_globals.MOUSE_MODE,
                                              runtime_globals.TOUCH_MODE)

    def _make_buttons(self):
        """UP and DOWN for a mouse or a finger, as Head Charge has."""
        self.up_button = Button(BUTTON_X, UP_Y, BUTTON_SIZE, BUTTON_SIZE, "",
                                callback=lambda: self.move(-1),
                                decorators=["ArrowUp"], shadow_mode="full")
        self.down_button = Button(BUTTON_X, DOWN_Y, BUTTON_SIZE, BUTTON_SIZE, "",
                                  callback=lambda: self.move(1),
                                  decorators=["ArrowDown"], shadow_mode="full")
        for button in (self.up_button, self.down_button):
            self.ui_manager.add_component(button)

    #-----------------------------------------------------------------
    # Drawing
    #-----------------------------------------------------------------

    def draw_ready(self, surface):
        t = self.ready_elapsed()
        if t < STILL_MS:
            self.blit_art(surface, "poop_dodge_sukamon")
            return
        t -= STILL_MS
        out = len(THROW_OUT) * SLIDE_MS
        if t < out:
            dx = THROW_OUT[min(len(THROW_OUT) - 1, t // SLIDE_MS)]
        elif t < out + HOLD_MS:
            dx = HOLD_AT
        else:
            k = (t - out - HOLD_MS) // SLIDE_MS
            dx = THROW_BACK[min(len(THROW_BACK) - 1, k)]
        self.blit_art(surface, "poop_dodge_sukamon_throw", dx)

    def poop_frames(self):
        """The whole course, drawn once with each frame of the poops, at
        the art's scale (ART_DOT pixels a dot)."""
        if self._poop_frames is None:
            fmt = getattr(self.pet, "sprite_format", None)
            suffix = "_dot" if fmt == "Dot" else ("_hd" if fmt == "HD" else "")
            frames = []
            for n in (1, 2):
                try:
                    poop = image_load(f"assets/Poop{n}{suffix}.png").convert_alpha()
                except (pygame.error, FileNotFoundError):
                    poop = image_load(f"assets/Poop{n}.png").convert_alpha()
                size = CELL * ART_DOT
                if poop.get_size() != (size, size):
                    poop = pygame.transform.scale(poop, (size, size))
                course = pygame.Surface((self.map_width * ART_DOT, LCD * ART_DOT), pygame.SRCALPHA)
                for x, lane in self.cells:
                    course.blit(poop, (x * ART_DOT, lane * CELL * ART_DOT))
                frames.append(course)
            self._poop_frames = frames
        return self._poop_frames

    def course_view(self):
        """The LCD's window on the course, scaled; made again only when the
        course has moved or the flies have turned."""
        view = max(0, min(self.map_width - LCD, self.view_left()))
        frame = (pygame.time.get_ticks() // FLY_MS) % 2
        key = (view, frame)
        if self._view is None or self._view[0] != key:
            course = self.poop_frames()[frame]
            window = course.subsurface(pygame.Rect(view * ART_DOT, 0, LCD * ART_DOT, LCD * ART_DOT))
            size = LCD * self.dot()
            self._view = (key, pygame.transform.scale(window, (size, size)))
        return self._view[1]

    def draw_game(self, surface):
        surface.blit(self.course_view(), self.at(0, 0))
        blinking = self.step == "hit" and (self.elapsed() // BLINK_MS) % 2
        if not blinking:
            self.blit_art(surface, "poop_dodge_player", PLAYER_COL, self.lane * CELL)

    def draw_charge(self, surface):
        super().draw_charge(surface)
        if self.pointer_mode() and self.step == "run":
            # Outside the LCD's clip: the buttons stand at its edge.
            for button in (self.up_button, self.down_button):
                button.update()
                button.draw(surface)
