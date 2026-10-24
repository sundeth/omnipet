#=====================================================================
# ICMinigame (base for the Digivice iC's own minigames)
#=====================================================================
"""The Digivice iC's own minigames, played from the training scene's Bonus
list (scenes.scene_training.BONUS_MODES).

They run the phases every minigame runs (training.Training): READY, then
the charge -- here the minigame itself, in steps of its own -- then the
result, BAD, GOOD, GREAT or EXCELLENT, then the currency screen with what
it earned. On the devices they are money games, not training: a play costs
a hunger heart and clearing pays Fight Money (Master Book scan 63), and a
success raises Reliability by the module's ``reliability_minigame_success``.
So none of them trains the pet or counts as a training: nothing here goes
through ``pet.finish_training`` or the training quests. Only iC Digimon
play; with several in the party they share the game, the first one is the
one drawn, and the module is paid once.

They are drawn on the iC's 32 x 32 LCD, DOT layout pixels a dot (192 of
the 240), centred. Their art is 3 pixels a dot and is drawn as the files
have it (owner, 2026-10-06), to be recoloured in the files themselves. A
pet is drawn 16 dots square, which is its own 48-pixel sprite at that scale.

Every time is in milliseconds and was measured on the device.
"""
import pygame

from battle import combat_constants, ic_attacks
from core import constants, runtime_globals
from models.animation import PetFrame
from training.training import Training
from utils.asset_utils import image_load
from utils.currency_utils import pay_earnings
from utils.pet_utils import get_training_targets
from utils.scene_utils import change_scene

LCD = 32
#: Layout pixels a dot, and the art's own pixels a dot.
DOT = 6
ART_DOT = 3
LCD_X = LCD_Y = (240 - LCD * DOT) // 2
#: A pet is 16 dots square.
PET_DOTS = 16

#: What the iC shows when its money games pay, "50P GET!" (Master Book scan
#: 63; the owner's video's "0P GET!"): ic_get.png's lower half, the
#: brackets and GET! on rows 16-31, with the amount right-aligned to column
#: 22 on rows 19-23 and P at columns 24-26, in ic_digits.png's font (0-9
#: then P, three dots wide, four apart). The currency screen shows it for
#: an iC module's earnings, on the colour of the iC's LCD (its background,
#: modules/IC/backgrounds/bg_ic.png), since the art is black.
PANEL_ROWS = (16, 32)
AMOUNT_ROW = 19
AMOUNT_LAST_COL = 20
UNIT_COL = 24
GLYPHS = "0123456789P"
GLYPH_PITCH = 4
GLYPH_WIDTH = 3
LCD_COLOUR = (224, 243, 237)


def get_panel(amount, factor):
    """The "P GET!" panel for *amount*, each art pixel *factor* pixels."""
    get = image_load("assets/ic_get.png").convert_alpha()
    digits = image_load("assets/ic_digits.png").convert_alpha()
    top, bottom = PANEL_ROWS
    panel = pygame.Surface((LCD * ART_DOT, (bottom - top) * ART_DOT))
    panel.fill(LCD_COLOUR)
    panel.blit(get, (0, -top * ART_DOT))

    def glyph(char, col):
        source = pygame.Rect(GLYPHS.index(char) * GLYPH_PITCH * ART_DOT, 0,
                             GLYPH_WIDTH * ART_DOT, digits.get_height())
        panel.blit(digits, (col * ART_DOT, (AMOUNT_ROW - top) * ART_DOT), source)

    text = str(max(0, int(amount)))
    first = AMOUNT_LAST_COL - GLYPH_PITCH * (len(text) - 1)
    for index, char in enumerate(text):
        glyph(char, first + index * GLYPH_PITCH)
    glyph("P", UNIT_COL)
    return pygame.transform.scale(panel, (panel.get_width() * factor, panel.get_height() * factor))


class ICMinigame(Training):
    """The standard phases around a minigame of the iC's own.

    A subclass plays its minigame in the charge phase: ``start_game`` sets
    its first step, ``update_game``/``draw_game``/``handle_game_event`` run
    it, and ``end_game`` hands over to the result with the grade (0-3), the
    prize and whether it was a success.

    A minigame that the device opens with a scene of its own -- Shuffle's
    Chuumon climbing into his bucket, Poop Dodge's Numemon -- shows it in
    place of READY: it sets ``READY_MS`` and draws it in ``draw_ready``. The
    phase lasts the scene's length, with ``READY_SOUND`` (the device opens
    both silently).

    A full-screen screen -- Shuffle's SHUFFLE and SELECT!, the 20X's READY,
    START and CLEAR! -- is the animated sprite's (ui.components.
    animated_sprite: ``play_shuffle_title`` and the like), from assets/ui as
    its combat screens are; while it plays it is drawn over the whole
    screen.

    The device sounds the end of every game the same way: its success
    jingle when the game was cleared, its fail sound when it ended on a
    miss, both as the result comes up (``ic_success``, ``ic_fail``:
    utilities/IC/make_ic_sounds.py).
    """

    #: How long the minigame's own opening scene runs; None for READY.
    READY_MS = None
    #: The sound the opening scene plays; None for none.
    READY_SOUND = None

    def __init__(self, ui_manager):
        super().__init__(ui_manager)
        self.pets = [pet for pet in get_training_targets() if ic_attacks.is_ic_native(pet)]
        self.pet = self.pets[0] if self.pets else None
        self.grade = 0          # 0-3: Bad, Good, Great, Excellent
        self.prize = 0
        self.succeeded = False
        self.game_cleared = False
        self.step = None
        self.step_started = 0
        self._ready_started = None
        self._art = {}
        self._pet_frames = {}
        # Each play costs a heart, whether or not it is finished: the iC
        # charges a training as a battle (`training_uses_battle_cost`, Hunger 1).
        self.pay_training_costs()

    #-----------------------------------------------------------------
    # The opening scene, in place of READY
    #-----------------------------------------------------------------

    def update_alert_phase(self):
        if self.READY_MS is None:
            super().update_alert_phase()
            return
        if self._ready_started is None:
            self._ready_started = pygame.time.get_ticks()
            self._ready_sound_started = True    # the base draws the phase from now
            if self.READY_SOUND:
                runtime_globals.game_sound.play(self.READY_SOUND)
        if self.ready_elapsed() >= self.READY_MS:
            self._finish_alert_phase()

    def ready_elapsed(self):
        """Milliseconds into the opening scene."""
        if self._ready_started is None:
            return 0
        return pygame.time.get_ticks() - self._ready_started

    def draw_ready(self, surface):
        """Draw the opening scene at ``ready_elapsed()``."""

    def draw_alert(self, surface):
        if self.READY_MS is None:
            super().draw_alert(surface)
            return
        clip = surface.get_clip()
        surface.set_clip(self.lcd_rect())
        try:
            self.draw_ready(surface)
        finally:
            surface.set_clip(clip)

    #-----------------------------------------------------------------
    # The minigame, inside the charge phase
    #-----------------------------------------------------------------

    def _finish_alert_phase(self):
        super()._finish_alert_phase()
        self.start_game()

    def start_game(self):
        """Set the minigame's first step."""

    def update_game(self):
        """Advance the minigame's steps."""

    def draw_game(self, surface):
        """Draw the minigame's current step on the LCD."""

    def handle_game_event(self, event):
        """The minigame's own input; True when it used the event."""
        return False

    @staticmethod
    def tap_pos(event):
        """Where a click or a tap landed, or None. A finger that moves a few
        pixels before it lifts makes a drag, not a click (the input
        manager's 5-pixel threshold), so a drag's end counts as a tap."""
        event_type, data = event
        if event_type in ("LCLICK", "DRAG_END") and data and "pos" in data:
            return data["pos"]
        return None

    def set_step(self, step):
        self.step = step
        self.step_started = pygame.time.get_ticks()

    def elapsed(self):
        """Milliseconds into the current step."""
        return pygame.time.get_ticks() - self.step_started

    def end_game(self, grade, prize, succeeded, cleared=None, sound=True):
        """The minigame is over: on to the result, with the device's own
        sound -- its success jingle when the game was *cleared* (by default,
        when it *succeeded*), its fail sound when it ended on a miss. A game
        that sounded its end already (Gotcha!'s taunt plays the fail sound
        as it starts) passes *sound* False."""
        self.grade = max(0, min(3, int(grade)))
        self.prize = int(prize)
        self.succeeded = bool(succeeded)
        self.game_cleared = self.succeeded if cleared is None else bool(cleared)
        if sound:
            runtime_globals.game_sound.play("ic_success" if self.game_cleared else "ic_fail")
        self.animated_sprite.stop()
        self.phase = "result"
        self.frame_counter = 0

    def update_charge_phase(self):
        self.update_game()

    def draw_charge(self, surface):
        if self.animated_sprite.is_animation_playing():
            self.animated_sprite.draw(surface)      # full screen
            return
        clip = surface.get_clip()
        surface.set_clip(self.lcd_rect())
        try:
            self.draw_game(surface)
        finally:
            surface.set_clip(clip)

    #-----------------------------------------------------------------
    # The outcome
    #-----------------------------------------------------------------

    def get_attack_count(self):
        return self.grade

    def check_victory(self):
        return self.grade > 0

    def check_and_award_trophies(self):
        pass

    def apply_training_results(self):
        """Not a training: a success raises Reliability, and the prize is
        paid once a module in its currency (the iC's Fight Money, its only
        one). Returns what was paid. Its sound played as the result came
        up (``end_game``)."""
        earnings = []
        paid = set()
        modules = getattr(runtime_globals, "game_modules", None) or {}
        for pet in self.pets:
            if self.succeeded:
                pet._apply_reliability_event("reliability_minigame_success")
            if self.prize and pet.module not in paid:
                paid.add(pet.module)
                currencies = getattr(modules.get(pet.module), "currencies", None) or []
                if currencies:
                    earnings.append((pet.module, currencies[0].get("name"), self.prize))
        return pay_earnings(earnings)

    def draw_result(self, surface):
        if not self.animated_sprite.is_animation_playing():
            duration = combat_constants.RESULT_SCREEN_FRAMES / constants.FRAME_RATE
            (self.animated_sprite.play_bad, self.animated_sprite.play_good,
             self.animated_sprite.play_great, self.animated_sprite.play_excellent)[self.grade](duration)
        self.animated_sprite.draw(surface)

    #-----------------------------------------------------------------
    # Input
    #-----------------------------------------------------------------

    def handle_event(self, event):
        if self.phase == "charge":
            if self.handle_game_event(event):
                return
            if event[0] in ("B", "START"):
                # Leaving mid-game, as from any minigame's charge; the heart
                # is already spent.
                runtime_globals.game_sound.play("cancel")
                change_scene("game")
            return
        super().handle_event(event)

    #-----------------------------------------------------------------
    # The LCD
    #-----------------------------------------------------------------

    def dot(self):
        """Screen pixels a dot."""
        return DOT * self.ui_manager.ui_scale

    def at(self, col, row):
        """Screen position of LCD dot (col, row); fractions allowed."""
        x, y = self.ui_manager.scale_position(LCD_X, LCD_Y)
        return int(x + col * self.dot()), int(y + row * self.dot())

    def lcd_rect(self):
        x, y = self.at(0, 0)
        return pygame.Rect(x, y, LCD * self.dot(), LCD * self.dot())

    def art(self, name):
        """``assets/<name>.png`` at the LCD's scale, in its own colours."""
        if name not in self._art:
            image = image_load(f"assets/{name}.png").convert_alpha()
            factor = self.dot() // ART_DOT
            self._art[name] = pygame.transform.scale(
                image, (image.get_width() * factor, image.get_height() * factor))
        return self._art[name]

    def blit_art(self, surface, name, col=0, row=0, x=0):
        """Draw art with its top-left at dot (col, row), *x* art pixels further."""
        px, py = self.at(col, row)
        surface.blit(self.art(name), (px + x * self.dot() // ART_DOT, py))

    def pet_sprite(self, frame):
        """The drawn pet's *frame*, 16 dots square; IDLE1 where it has none."""
        if frame not in self._pet_frames:
            frames = runtime_globals.pet_sprites.get(self.pet) or []
            sprite = frames[frame.value] if frame.value < len(frames) else None
            if sprite is None and frames:
                sprite = frames[PetFrame.IDLE1.value]
            size = PET_DOTS * self.dot()
            self._pet_frames[frame] = (pygame.transform.scale(sprite, (size, size))
                                       if sprite is not None else None)
        return self._pet_frames[frame]

    def blit_pet(self, surface, frame, col, row):
        sprite = self.pet_sprite(frame)
        if sprite is not None:
            surface.blit(sprite, self.at(col, row))

    def alternate(self, *frames, period=500):
        """The frame of *frames* showing now, each for *period* ms."""
        return frames[(self.elapsed() // period) % len(frames)]


#: The 20X's own READY and START (the owner's videos, utilities/IC/10.mp4 at
#: 55.5 s): READY's three notes a second apart, then START for half a
#: second, the screens the Master Book prints (the animated sprite's
#: assets/ui/Combat_IC20Ready_1.png, Combat_IC20Start_1.png). A stage
#: cleared shows CLEAR! (Combat_IC20Clear_1.png) with the success jingle
#: first (10.mp4 at 66.7 s).
READY_20X_MS = 3020
START_20X_MS = 550
CLEAR_20X_MS = 730
READY_20X_SOUND = "ic20_ready"
START_20X_SOUND = "ic20_start"


class IC20Minigame(ICMinigame):
    """A minigame of the iC 20X's: it opens with the 20X's READY and START
    instead of the game's READY, and a game of stages runs CLEAR!, READY
    and START between them (``start_intro``)."""

    READY_MS = READY_20X_MS + START_20X_MS
    READY_SOUND = READY_20X_SOUND

    def __init__(self, ui_manager):
        super().__init__(ui_manager)
        self._start_sounded = False

    def update_alert_phase(self):
        if self._ready_started is None:
            self.animated_sprite.play_ic20_ready(READY_20X_MS / 1000)
        elif not self._start_sounded and self.ready_elapsed() >= READY_20X_MS:
            self._start_sounded = True
            runtime_globals.game_sound.play(START_20X_SOUND)
            self.animated_sprite.play_ic20_start(START_20X_MS / 1000)
        super().update_alert_phase()

    def draw_alert(self, surface):
        # READY and START fill the screen.
        self.animated_sprite.draw(surface)

    def start_intro(self, cleared):
        """Between stages: CLEAR! when *cleared*, then READY, then START;
        ``update_intro`` says when the next stage begins."""
        if cleared:
            runtime_globals.game_sound.play("ic_success")
            self.set_step("clear")
            self.animated_sprite.play_ic20_clear(CLEAR_20X_MS / 1000)
        else:
            self.intro_ready()

    def intro_ready(self):
        runtime_globals.game_sound.play(READY_20X_SOUND)
        self.set_step("ready")
        self.animated_sprite.play_ic20_ready(READY_20X_MS / 1000)

    def update_intro(self):
        """Advance CLEAR!, READY and START; True once START is over."""
        t = self.elapsed()
        if self.step == "clear" and t >= CLEAR_20X_MS:
            self.intro_ready()
        elif self.step == "ready" and t >= READY_20X_MS:
            runtime_globals.game_sound.play(START_20X_SOUND)
            self.set_step("start")
            self.animated_sprite.play_ic20_start(START_20X_MS / 1000)
        elif self.step == "start" and t >= START_20X_MS:
            self.animated_sprite.stop()
            return True
        return False
