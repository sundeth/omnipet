#=====================================================================
# BuildingSmash (ビルはかい, the Digivice iC 10X)
#=====================================================================
"""Building Smash, the iC 10X's timing minigame.

Read off the owner's video of a 10X (``utilities/IC/1.mp4``; the frame by
frame account is in ``utilities/IC/make_building_smash_sprites.py``) and the
Master Book (scan 63). It is the charge phase of an ICMinigame, between
READY and the result:

* A cursor runs under a box from the left edge to the right and back, and
  A stops it. The stop hits when the cursor's point is under the black bar
  that hangs into the box: 6 dots wide for the first stop, 4 for the
  second, 2 for the third. A miss ends the game.
* Three hits clear a stage. The Digimon fires its own shot at the enemy's
  building, which explodes: it stands damaged after stage 1 and in rubble
  after stage 2, and stage 3 finishes it.
* The cursor speeds up each stage: about 10, 15 and 31 dots a second.
* The result is the stages cleared: none BAD, one GOOD, two GREAT, three
  EXCELLENT. They pay 0, 10, 20 or 50 P, and clearing all three is the
  success that raises Reliability (the 10X playbook's table).
"""
import pygame

from battle import ic_attacks
from core import runtime_globals
from models.animation import PetFrame
from training.ic_minigame import ICMinigame, LCD, PET_DOTS

#: The black bar's columns, first stop to third.
TARGETS = ((13, 18), (14, 17), (15, 16))
#: Milliseconds the cursor takes a dot, stage 1 to 3.
STEP_MS = (100, 67, 32)
#: The cursor's point runs between these columns; the cursor is 5 dots wide
#: under the box (rows 16-18), its point on top.
APEX_MIN, APEX_MAX = 2, 29
CURSOR_ROW = 16
#: P for the stages cleared: none, 1, 2, 3.
PRIZES = (0, 10, 20, 50)

#: A hit holds the cursor and blinks the bar before the next stop; a miss
#: holds it a little longer before the result.
HIT_HOLD_MS = 1000
MISS_HOLD_MS = 1200
BLINK_MS = 100
#: The attack: the pet in the middle, then at the right firing its shot
#: (which leaves the screen in the first second), then the building with the
#: shot flying in, then the bursts, then what is left of the building.
PET_MS = 600
FIRE_MS = 1500
SHOT_OUT_MS = 1000
APPROACH_MS = 850
BURSTS = (("building_explosion_1", 500), ("building_explosion_2", 450),
          ("building_explosion_1", 500), ("building_explosion_2", 450))
#: The iC's own blast (utilities/IC/make_ic_sounds.py).
BLAST_SOUND = "ic_building_break"
AFTER_MS = 1000
#: After the last stage the building is gone and the pet stands alone.
WON_MS = 1200

#: The building each stage shoots at; what stands after stage n is the
#: next one.
BUILDINGS = ("building_1", "building_2", "building_3")
#: building_1-3.png put the building's left edge 19 art pixels into their
#: canvas; it stands at the LCD's left edge.
BUILDING_X = -19
BUILDING_RIGHT = 16
#: The shot is the Digimon's own attack sprite, as big as the pet.
SHOT_DOTS = 16
PET_ROW = LCD - PET_DOTS


class BuildingSmash(ICMinigame):
    def __init__(self, ui_manager):
        super().__init__(ui_manager)
        self.stage = 0          # 0-2
        self.stop = 0           # 0-2, the stop within the stage
        self.cleared = 0        # stages cleared
        self.hit = False
        self.stopped_at = APEX_MIN
        self._shot = None
        self._blast_sounded = False

    #-----------------------------------------------------------------
    # Rules
    #-----------------------------------------------------------------

    def start_game(self):
        self.set_step("aim")

    def apex(self):
        """The column under the cursor's point now: from the left edge to
        the right and back, a dot every STEP_MS."""
        steps = self.elapsed() // STEP_MS[self.stage]
        span = APEX_MAX - APEX_MIN
        k = steps % (2 * span)
        return APEX_MIN + (k if k <= span else 2 * span - k)

    def target(self):
        return TARGETS[self.stop]

    def stop_cursor(self):
        self.stopped_at = self.apex()
        first, last = self.target()
        self.hit = first <= self.stopped_at <= last
        runtime_globals.game_sound.play("menu")
        self.set_step("hold")

    def update_game(self):
        t = self.elapsed()
        step = self.step
        if step == "hold":
            if self.hit and t >= HIT_HOLD_MS:
                if self.stop < len(TARGETS) - 1:
                    self.stop += 1
                    self.set_step("aim")
                else:
                    self.set_step("pet")
            elif not self.hit and t >= MISS_HOLD_MS:
                self.end_game(self.cleared, PRIZES[self.cleared], succeeded=False)
        elif step == "pet" and t >= PET_MS:
            runtime_globals.game_sound.play("attack")
            self.set_step("fire")
        elif step == "fire" and t >= FIRE_MS:
            self.set_step("approach")
        elif step == "approach" and t >= APPROACH_MS:
            runtime_globals.game_sound.play("attack_hit")
            self._blast_sounded = False
            self.set_step("burst")
        elif step == "burst" and not self._blast_sounded and t >= BURSTS[0][1]:
            # The blast sounds as the first big burst comes up (the video's
            # 40.5 s), and runs on over what is left of the building.
            self._blast_sounded = True
            runtime_globals.game_sound.play(BLAST_SOUND)
        elif step == "burst" and t >= sum(ms for _, ms in BURSTS):
            self.cleared = self.stage + 1
            self.set_step("after" if self.stage < len(BUILDINGS) - 1 else "won")
        elif step == "after" and t >= AFTER_MS:
            self.stage += 1
            self.stop = 0
            self.set_step("aim")
        elif step == "won" and t >= WON_MS:
            self.end_game(self.cleared, PRIZES[self.cleared], succeeded=True)

    def handle_game_event(self, event):
        if self.step == "aim" and (event[0] == "A" or self.tap_pos(event) is not None):
            self.stop_cursor()
            return True
        return False

    #-----------------------------------------------------------------
    # Drawing
    #-----------------------------------------------------------------

    def shot(self):
        """The Digimon's own ordinary shot, as the iC picks it, pet-sized."""
        if self._shot is None:
            normal, _crit = ic_attacks.attack_ids(self.pet)
            sprite = (self.get_attack_sprite(self.pet, normal)
                      or self.get_attack_sprite(self.pet, getattr(self.pet, "atk_main", 0)))
            size = SHOT_DOTS * self.dot()
            self._shot = pygame.transform.scale(sprite, (size, size)) if sprite else False
        return self._shot or None

    def blit_shot(self, surface, col):
        shot = self.shot()
        if shot is not None:
            surface.blit(shot, self.at(col, PET_ROW))

    def blit_building(self, surface, name):
        self.blit_art(surface, name, x=BUILDING_X)

    def draw_game(self, surface):
        t = self.elapsed()
        middle = (LCD - PET_DOTS) / 2
        step = self.step
        if step in ("aim", "hold"):
            self.blit_art(surface, "building_bar")
            blinking = step == "hold" and self.hit and (t // BLINK_MS) % 2
            if not blinking:
                self.blit_art(surface, f"building_target_{self.stop + 1}")
            apex = self.stopped_at if step == "hold" else self.apex()
            self.blit_art(surface, "building_cursor", apex - 2, CURSOR_ROW)
        elif step == "pet":
            self.blit_pet(surface, self.alternate(PetFrame.IDLE1, PetFrame.IDLE2, period=300),
                          middle, PET_ROW)
        elif step == "fire":
            right = LCD - PET_DOTS
            firing = t < SHOT_OUT_MS
            self.blit_pet(surface, PetFrame.ATK1 if firing else PetFrame.IDLE1, right, PET_ROW)
            if firing:
                # From beside the pet off the left edge.
                start = right - SHOT_DOTS
                self.blit_shot(surface, start - (start + SHOT_DOTS) * t / SHOT_OUT_MS)
        elif step == "approach":
            self.blit_building(surface, BUILDINGS[self.stage])
            self.blit_shot(surface, LCD - (LCD - BUILDING_RIGHT) * t / APPROACH_MS)
        elif step == "burst":
            for name, ms in BURSTS:
                if t < ms:
                    self.blit_art(surface, name)
                    break
                t -= ms
        elif step == "after":
            self.blit_building(surface, BUILDINGS[self.stage + 1])
        elif step == "won":
            self.blit_pet(surface, PetFrame.HAPPY, middle, PET_ROW)
