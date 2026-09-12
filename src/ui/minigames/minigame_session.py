"""
Charge-minigame session
=======================

One run of a battle charge minigame, outside a BattleEncounter.

The DCom connection flow plays the charge minigame *before* the battle exists
-- its result goes into the packets sent to the real device -- so it cannot
lean on BattleEncounter's charge phase.  It used to carry its own copy of the
setup/update/draw/input code for each minigame, and that copy went stale: the
Count Match minigames were built without the AnimatedSprite they draw through
(so nothing appeared on screen), Count Match Z was never taken out of its
ready phase (so it always scored 0), and the Xai bar was still being re-scored
from a 0-20 meter after ``XaiBar.get_result`` was changed to return 0-3.

``MinigameSession`` is that flow's minigame, built from the same components
BattleEncounter uses, and it runs the same two phases a battle does:

    READY   the ready sound with its animation, or -- for the Count Match
            minigames, which own their ready screen -- the attribute sprite
            or the arrows to match. Non-skippable, as in a battle.
    CHARGE  the minigame proper.

``minigame_result`` is the shared 0-3 scoring the protocols actually carry,
used by both.
"""

import random

import pygame

from core import runtime_globals
from ui.minigames.count_match import CountMatch
from ui.minigames.count_match_classic import CountMatchClassic
from ui.minigames.count_match_z import CountMatchZ
from ui.minigames.dummy_charge import DummyCharge
from ui.minigames.shake_punch import ShakePunch
from ui.minigames.xai_bar import XaiBar
from ui.minigames.xai_roll import XaiRoll
from ui.components.animated_sprite import AnimatedSprite
from ui.windows.window_background import WindowBackground
from battle import combat_constants
from core import game_globals
from training.training import TRAINING_READY_SOUND


#: Every value ``module.json``'s ``battle_minigame`` (and a protocol's
#: ``MINIGAME``) can take.
MINIGAMES = (
    "None", "Dummy Bar", "Count Match Color", "Count Match Classic",
    "Count Match Z", "Xai Roll+Bar", "Xai Bar", "Punch", "Mogera",
)

#: Minigames that draw the READY phase themselves rather than leaving it to
#: the animated ready sprite -- Count Match Color shows an attribute-specific
#: sprite and Count Match Z the arrows to match. Built from the classes' own
#: HAS_READY_PHASE flag, the same way battle_encounter builds its copy, so
#: giving another minigame a ready screen is one change in the minigame.
READY_PHASE_MINIGAMES = {
    name: cls
    for name, cls in (("Count Match Color", CountMatch),
                      ("Count Match Z", CountMatchZ),
                      ("Count Match Classic", CountMatchClassic))
    if getattr(cls, "HAS_READY_PHASE", False)
}


def minigame_result(minigame: str, strength: int = 0, super_hits: int = 0,
                    arrows: int = 0, pet=None, color_band=None) -> int:
    """The 0-3 charge quality a minigame's raw score maps to.

    Every protocol carries the charge as 0-3 (Bad/Good/Great/Excellent) or as
    a 0-14 tap count that the packet generator bands the same way, so this is
    the one place the bands are written down.  Dispatches on the minigame
    rather than the ruleset: PENZ runs a Count Match on the DMX wire format,
    and reading that as an Xai bar returned a raw meter where its minigame
    produces super hits.

    Three raw scores reach it, because the minigames do not measure the same
    thing. ``strength`` is a meter, ``super_hits`` is Count Match **Color's**
    colour-ranked hit count, and ``arrows`` is Count Match **Z's** counter --
    which is scored against the number the pet was asked for, so that one
    needs the ``pet`` as well. Count Match Z used to be pushed through
    ``super_hits``, which is a different game's mechanic and is what let its
    result sit at 0 unnoticed.
    """
    if minigame == "None":
        return 2

    if minigame == "Dummy Bar":
        # Dummy charge meter, 0-14.
        if strength < 5:
            return 0
        if strength < 10:
            return 1
        if strength < 14:
            return 2
        return 3

    if minigame == "Count Match Color":
        # The band IS this minigame's result -- which of the four outcomes
        # the colour was worth to that attribute -- so a caller that has it
        # passes it straight through. Recovering it from the super-hit count
        # is the fallback and is lossy at stages 1-2, where the weakest
        # colour pays one super hit and bands back down to nothing.
        if color_band is not None:
            return max(0, min(int(color_band), 3))
        return count_match_band(super_hits)

    if minigame == "Count Match Z":
        # Scored straight off the arrow counter: the player is asked for a
        # number of arrows and either fills it or does not, so the distance
        # from that number is the whole result. Both the slots on offer and
        # the count asked for come from the pet, so the rule lives with the
        # minigame rather than in these bands.
        from ui.minigames.count_match_z import score_arrows
        return score_arrows(arrows, pet)

    if minigame == "Count Match Classic":
        # A shake meter, not a colour match, and it keeps the full count --
        # 0-40, because the Pendulum's wire reads the number itself. The
        # bands are the old 0-14 ones scaled onto it, so the difficulty is
        # unchanged: Excellent is still a perfect meter and anything under
        # about three quarters is still Bad.
        if strength <= 28:
            return 0
        if strength < 35:
            return 1
        if strength < 40:
            return 2
        return 3

    if minigame in ("Xai Roll+Bar", "Xai Bar"):
        # The Xai bar already reports 0-3.
        return max(0, min(3, strength))

    if minigame == "Punch":
        # Shake punch meter, 0-20.
        if strength < 10:
            return 0
        if strength < 15:
            return 1
        if strength < 20:
            return 2
        return 3

    if minigame == "Mogera":
        # No shakes at all is a failed charge, which the protocol carries as
        # Bad; above that the two bands are the device's.
        if strength <= 0:
            return 0
        if strength < 7:
            return 1
        if strength < 14:
            return 2
        return 3

    return 1


#: Colour -> super hits, best to worst, from the Pendulum Color manual's own
#: chart. Colours are 1=Red 2=Yellow 3=Blue and each attribute ranks them
#: differently, but the three bands are the same for all four:
#:
#:      Attribute  Megahit          3-4 Super Hits   2 Super Hits
#:      Baby       Red / 12 shakes  Yellow / 7       Blue / 2
#:      Vaccine    Red / 12         Yellow / 7       Blue / 2
#:      Data       Yellow / 6       Red / 11         Blue / 2
#:      Virus      Blue / 2         Yellow / 7       Red / 12
#:      Free       Red / 11         Yellow / 7       Blue / 2
#:
#: So the ranking is the attribute's and the payout is not: landing the
#: attribute's own colour is a **Megahit of five**, the next is three or
#: four, and the last is two.
COUNT_MATCH_RANKINGS = {
    "": (1, 2, 3),     # blank is Free, and the manual ranks it as Vaccine does
    "Va": (1, 2, 3),   # Red > Yellow > Blue
    "Da": (2, 1, 3),   # Yellow > Red > Blue
    "Vi": (3, 2, 1),   # Blue > Yellow > Red
}

#: The band a colour's place in that ranking is worth, weakest first, as
#: `battle_utils.PENC_BANDS` names them: no colour at all, then the last
#: colour, the middle one, and the attribute's own.
COUNT_MATCH_NO_COLOUR, COUNT_MATCH_RANK_BANDS = 0, (3, 2, 1)


def count_match_rank(color: int, attribute: str) -> int:
    """Which of the four Count Match Color outcomes a colour is, 0-3.

    **This is what the minigame actually produces.** The colour is worth its
    *place* in the attribute's own ranking and not its name -- Blue is a
    Megahit for a Virus pet and the weakest result for a Vaccine one -- and
    the place is what the Pendulum Color's attack table is keyed on, beside
    the stage. Order runs weakest first: 0 no colour, 1 the last colour, 2
    the middle one, 3 the pet's own.

    An attribute with no ranking, or a colour outside it (which is what
    fewer than two shakes gives), is band 0.
    """
    order = COUNT_MATCH_RANKINGS.get(attribute)
    if not order or color not in order:
        return COUNT_MATCH_NO_COLOUR
    return COUNT_MATCH_RANK_BANDS[order.index(color)]


def count_match_super_hits(color: int, attribute: str, stage: int = 1) -> int:
    """Super hits from a Count Match Color result (0-5).

    **Derived, not chosen.** The count is the number of super hits in the row
    the device would throw, and the row comes from the pet's **stage** and the
    colour band -- so the count follows from those two and is not an input to
    anything. Read off a real device for all seven stages: the bottom band
    pays 0 at stages 1-2 and 1 from stage 3 up, and the middle band 3 at
    stages 1-4 and 4 from stage 5 up.

    That retires two things. The manual's "3 or 4" was being **rolled**
    (`COUNT_MATCH_PAYOUT` held `(3, 4)` and picked one), and it is the stage
    speaking rather than a roll. And the `shakes` argument existed only to
    split the bottom band between 0 and 1 -- "if you do not shake at least
    two times, you will only get 0 or 1 Super Hits" -- which the stage now
    answers, so it is gone. Fewer than two shakes leaves no colour at all,
    which is band 0 either way.
    """
    from battle.sim.battle_utils import get_penc_pattern, penc_super_hits

    return penc_super_hits(
        get_penc_pattern(stage, count_match_rank(color, attribute)))


def count_match_band(super_hits: int) -> int:
    """The 0-3 charge quality a super-hit count is worth.

    The manual's own grading: a Megahit is the top band, three or four the
    next, two the lowest win, and anything under that a failure.

    **Prefer `count_match_rank`, which is the band itself.** Recovering it
    from the count is lossy at stages 1 and 2, where the weakest colour pays
    a single super hit and reads back as no colour at all. This is for a
    caller holding only a count.
    """
    if super_hits >= 5:
        return 3
    if super_hits >= 3:
        return 2
    if super_hits >= 2:
        return 1
    return 0


class MinigameSession:
    """A charge minigame played on its own, with its own screen and input.

    Usage::

        session = MinigameSession("Dummy Bar", ui_manager, pet)
        ...  session.update() / session.draw(surface) / session.handle_event(e)
        if session.finished:
            value = session.result      # 0-3, ready for the packet

    It opens on the READY phase and moves to the charge itself; the caller
    only has to pump it.
    """

    def __init__(self, minigame: str, ui_manager, pet=None, theme: str = "RED_DARK_VARIANT",
                 draw_background: bool = True):
        self.minigame = minigame if minigame in MINIGAMES else "None"
        self.ui_manager = ui_manager
        self.pet = pet
        self.theme = theme

        # The minigame is drawn over whatever the caller had on screen. In a
        # battle that is the battle scene, which is what it is meant to sit
        # on; anywhere else it needs its own ground, or the menus and labels
        # behind it show through the gaps in the bar.
        self.background = WindowBackground(False) if draw_background else None

        self.finished = False
        self.strength = 0
        self.super_hits = 0
        #: Count Match Color's own result: which of the four outcomes the
        #: colour was worth to this pet's attribute, 0-3. The super-hit count
        #: is derived from this and the stage, not the other way round.
        self.color_band = None
        #: Count Match Z's arrow counter, which is its whole score.
        self.arrows = 0

        self.phase = "ready"       # ready -> charge
        self.instance = None       # the minigame component, when it has one
        self.animated_sprite = None
        self.xai_roll = None
        self.xai_bar = None
        self.xai_phase = 0
        self._xai_pending_stop = False
        self._deadline_ms = 0

        # READY phase state, run the same way training and battle run theirs:
        # the phase lasts exactly as long as the ready sound and does not
        # start until playback actually has.
        self._ready_frames = combat_constants.ALERT_DURATION_FRAMES
        self._ready_counter = 0
        self._ready_sound_triggered = False
        self._ready_sound_started = False
        self._ready_sound_fallback = False

        self._setup_ready()

    # ------------------------------------------------------------------
    # READY phase
    # ------------------------------------------------------------------

    def _setup_ready(self):
        """Open on READY, unless there is no minigame to get ready for."""
        if self.minigame == "None":
            self.phase = "charge"
            self.finished = True
            runtime_globals.game_console.log("[Minigame] No charge for this device")
            return

        self.animated_sprite = AnimatedSprite(self.ui_manager)

        # A minigame that owns its ready screen has to exist before the phase
        # draws, so it is built here rather than at the charge.
        ready_class = READY_PHASE_MINIGAMES.get(self.minigame)
        if ready_class:
            self.instance = ready_class(self.ui_manager, self.pet, self.animated_sprite)
            self.instance.set_phase("ready")

        runtime_globals.game_console.log(f"[Minigame] READY for '{self.minigame}'")

    def _update_ready(self):
        """Hold READY for as long as its sound plays, then start the charge."""
        if not self._ready_sound_triggered:
            duration = runtime_globals.game_sound.get_duration(TRAINING_READY_SOUND)
            if duration > 0:
                self._ready_frames = max(
                    1, int(round(duration * game_globals.configuration.frame_rate)))
            channel = runtime_globals.game_sound.play(TRAINING_READY_SOUND)
            self._ready_sound_triggered = True
            # Muted audio or no mixer has no playback start to wait for.
            if channel is None:
                self._ready_sound_started = True
                self._ready_sound_fallback = True
                self._ready_counter = 0

        if not self._ready_sound_started:
            # The mixer can lag behind play(); hold at frame 0 until the
            # sound is actually audible so the two stay in step.
            if runtime_globals.game_sound.is_playing(TRAINING_READY_SOUND):
                self._ready_sound_started = True
            self._ready_counter = 0
            return

        self._ready_counter += 1
        if (not self._ready_sound_fallback
                and not runtime_globals.game_sound.is_playing(TRAINING_READY_SOUND)):
            self._start_charge()
            return
        if self._ready_counter >= self._ready_frames:
            self._start_charge()

    def _draw_ready(self, surface):
        if self.instance is not None:
            # The minigame draws its own ready screen -- through the same
            # animated sprite, which is why stopping it here left only the
            # arrows on an empty background.
            self.instance.draw(surface)
            return
        if not self.animated_sprite.is_animation_playing():
            self.animated_sprite.play_ready(
                self._ready_frames / max(1, game_globals.configuration.frame_rate))
        self.animated_sprite.draw(surface)

    def _start_charge(self):
        """Leave READY for the minigame itself."""
        runtime_globals.game_sound.stop(TRAINING_READY_SOUND)
        self.animated_sprite.stop()
        self.phase = "charge"
        self._setup()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _setup(self):
        name = self.minigame
        runtime_globals.game_console.log(f"[Minigame] Charging '{name}'")

        if name == "Dummy Bar":
            self.instance = DummyCharge(self.ui_manager, self.theme)
        elif name == "Count Match Classic":
            # Count Match Classic has no ready screen of its own, so it is
            # built here; the Count Match family all draw through the shared
            # AnimatedSprite and run invisibly without one.
            if self.instance is None:
                self.instance = CountMatchClassic(self.ui_manager,
                                                  self.animated_sprite, self.theme)
        elif name in ("Count Match Color", "Count Match Z"):
            # Built for the ready phase already; move it on to the count.
            self.instance.set_phase("count")
        elif name in ("Punch", "Mogera"):
            pets = [self.pet] if self.pet else []
            self.instance = ShakePunch(self.ui_manager, pets)
            self.instance.set_phase("punch")
        elif name == "Xai Roll+Bar":
            self.xai_phase = 1
            self.xai_roll = XaiRoll(
                x=runtime_globals.SCREEN_WIDTH // 2 - int(100 * runtime_globals.UI_SCALE) // 2,
                y=runtime_globals.SCREEN_HEIGHT // 2 - int(100 * runtime_globals.UI_SCALE) // 2,
                width=int(100 * runtime_globals.UI_SCALE),
                height=int(100 * runtime_globals.UI_SCALE),
                xai_number=1,
            )
            self.xai_roll.roll()
        elif name == "Xai Bar":
            from core import game_globals
            self.xai_phase = 2
            self._start_xai_bar(getattr(game_globals, 'xai', 1))

        self._deadline_ms = pygame.time.get_ticks() + combat_constants.BAR_HOLD_TIME_MS

    def _start_xai_bar(self, xai_number):
        self.xai_bar = XaiBar(
            x=runtime_globals.SCREEN_WIDTH // 2 - int(152 * runtime_globals.UI_SCALE) // 2,
            y=runtime_globals.SCREEN_HEIGHT // 2 - int(72 * runtime_globals.UI_SCALE) // 2
              + int(48 * runtime_globals.UI_SCALE),
            xai_number=xai_number,
            pet=self.pet,
        )
        self.xai_bar.start()

    # ------------------------------------------------------------------
    # Loop
    # ------------------------------------------------------------------

    def update(self):
        if self.finished:
            return

        if self.phase == "ready":
            self._update_ready()
            if self.instance is not None:
                self.instance.update()
            return

        name = self.minigame

        if name in ("Xai Roll+Bar", "Xai Bar"):
            self._update_xai()
            if self.xai_phase == 3:
                self._finish()
            return

        if self.instance:
            self.instance.update()

        if name == "Dummy Bar":
            self.strength = self.instance.strength
        elif name == "Count Match Classic":
            self.strength = self.instance.strength
        elif name in ("Punch", "Mogera"):
            self.strength = self.instance.get_strength()
            if self.instance.is_time_up() or self.strength >= 20:
                self._finish()
                return

        if pygame.time.get_ticks() >= self._deadline_ms:
            self._finish()

    def _update_xai(self):
        if self.xai_phase == 1 and self.xai_roll:
            self.xai_roll.update()
            if not self.xai_roll.rolling and not self.xai_roll.stopping:
                self.xai_phase = 2
                # Read the landed face off the roll rather than off the input
                # handler: the roll also stops itself after a few seconds with
                # no press, and that result has to reach the bar just the same.
                self._start_xai_bar(self.xai_roll.get_result())
        elif self.xai_phase == 2 and self.xai_bar:
            if self._xai_pending_stop:
                self._xai_pending_stop = False
                self.xai_bar.stop()
            else:
                self.xai_bar.update()
            # The bar lingers half a second after stopping so the player can
            # see which colour they landed on.
            if getattr(self.xai_bar, 'stopped', False) and self.xai_bar.is_finished():
                self.strength = self.xai_bar.get_result()
                self.xai_phase = 3

    def _finish(self):
        if self.finished:
            return
        if self.minigame in ("Xai Roll+Bar", "Xai Bar"):
            # Committing early while the bar is still travelling scores
            # whatever it is over right now, and nothing at all before it
            # starts - the same as letting a bad stop happen.
            if self.xai_bar and self.xai_phase < 3:
                self.xai_bar.stop()
                self.strength = self.xai_bar.get_result()
        elif self.minigame == "Count Match Z" and self.instance:
            self.arrows = self.instance.get_press_counter()
        elif self.minigame == "Count Match Color" and self.instance:
            self.color_band = count_match_rank(
                self.instance.get_rotation_index(),
                getattr(self.pet, 'attribute', '') or '')
            self.super_hits = count_match_super_hits(
                self.instance.get_rotation_index(),
                getattr(self.pet, 'attribute', '') or '',
                getattr(self.pet, 'stage', 1) or 1,
            )
        self.finished = True
        runtime_globals.game_console.log(
            f"[Minigame] '{self.minigame}' finished: strength={self.strength}, "
            f"super_hits={self.super_hits}, result={self.result}")

    @property
    def result(self) -> int:
        """The 0-3 value to put in the battle packet."""
        return minigame_result(self.minigame, self.strength, self.super_hits,
                               self.arrows, self.pet, self.color_band)

    # ------------------------------------------------------------------
    # Input / drawing
    # ------------------------------------------------------------------

    def handle_event(self, event) -> bool:
        """True when the event belonged to the minigame."""
        if self.finished or not isinstance(event, tuple) or len(event) != 2:
            return False
        if self.phase == "ready":
            # READY is deliberately non-skippable, as it is in a battle, so a
            # press meant for the charge cannot land before it starts.
            return True
        event_type, _ = event

        # Commit the charge at whatever it has reached and move on.
        if event_type in ("B", "X"):
            self._finish()
            runtime_globals.game_sound.play("menu")
            return True

        if self.minigame in ("Xai Roll+Bar", "Xai Bar"):
            if event_type not in ("A", "LCLICK"):
                return False
            if self.xai_phase == 1 and self.xai_roll:
                if self.xai_roll.rolling and not self.xai_roll.stopping:
                    self.xai_roll.stop()
                elif not self.xai_roll.stopping:
                    # The roll already landed and the bar starts next frame;
                    # buffer the press so it stops on the bar's first frame.
                    self._xai_pending_stop = True
            elif self.xai_phase == 2 and self.xai_bar:
                self.xai_bar.stop()
            return True

        if not self.instance:
            return False

        return bool(self.instance.handle_event(event))

    def draw(self, surface):
        if self.background is not None:
            self.background.draw(surface)
        if self.phase == "ready":
            self._draw_ready(surface)
            return
        if self.minigame in ("Xai Roll+Bar", "Xai Bar"):
            if self.xai_phase == 1 and self.xai_roll:
                self.xai_roll.draw(surface)
            elif self.xai_phase >= 2 and self.xai_bar:
                self.xai_bar.draw(surface)
        elif self.instance:
            self.instance.draw(surface)
