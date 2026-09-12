"""Count Match Z -- the Pendulum Z's charge.

The ready phase shows a number of arrows; the charge phase adds one every few
shakes, and the player stops when the shown number is filled. Unlike the DMX's
Xai bar, every variant of this is the same game with different counts: what
changes is **how many arrows are asked for** and **how many slots there are to
overshoot into**.

The whole thing is measured. `utilities/DIGIROM/penz.txt` reads sixteen cells
off a real Pendulum Z -- seven stages, one to three levels each, with the
slots, the count asked for and the outcome of every possible shake count --
and the three rules below reproduce all sixteen exactly.

**The slots come from the stage and the level.** The stage sets a ceiling and
the top tier of any stage is always the easy three-slot game:

    slots = min(ceiling(stage), 4 - tier) + 2
    ceiling: stage 1-3 -> 1   stage 4-5 -> 2   stage 6-7 -> 3

which lands the drops where the device puts them -- stage 4 changes only at
level 6, stage 5 only at 8, and stages 6 and 7 at 5 and again at 10, while
stage 3 and below never change at all. That last one is why a Child looks
like it has "a single limit all over": its ceiling is 1, so there is nothing
to take away. The tier is `dmx_tier_index`, the same banding the attack table
and the Xai bar use.

**The count asked for is the attribute, read off the slots.** Free and
Vaccine ask for the whole meter, Data one less, and **Virus asks for one
whatever the meter is** -- read at three slots and again at four, and 1 both
times. That is what rules out the earlier reading, where each subtype was
thought to add one to the count as well as the slots: it does for three of
the four attributes and not for Virus. Free and Vaccine sharing an answer is
what makes them the pair that shares a type, which with three types and four
attributes one pair had to.

**The counter is the score.** There is no meter to band and no super hits to
count -- the player is asked for a number of arrows and either fills it or
does not, so `score_arrows(shakes, pet)` turns the counter straight into the
0-3 the protocols carry. It takes the pet because both the slots on offer and
the count asked for come from the Digimon. It used to be pushed through the
`super_hits` field Count Match **Color** ranks its colours into, which is a
different game's mechanic and is what let the result sit at 0 unnoticed.

**Scoring is the distance from the count asked for, with two departures.**
Exact is Excellent, one away Great, anything further Good -- so Bad is only
ever reached at the bottom of the meter:

* no shakes at all is Bad, always, even where that is one away;
* on a four- or five-slot game a single shake is Bad too, however close it
  lands. The same "barely shaking is a failure" the zero already says, and it
  is what separates a five-slot meter's `1 bad, 2 good` from a three-slot
  meter's `1 good`.
* where both neighbours exist, only one of them is Great: the one with more
  of the meter behind it, and the upper one where that ties. This is the only
  rule here resting on two readings rather than sixteen -- Free, Vaccine and
  Virus all ask for a count at one end of the meter, so **Data is the only
  attribute with a neighbour on each side**, and its two blocks are what show
  the asymmetry. They disagree about which side wins, which is what the "more
  room" reading resolves; a third Data block would confirm or break it.
"""
import pygame
from ui.ui_manager import UIManager
from ui.minigames.count_match import ShakeDetector
from core import runtime_globals

#: Slots at subtype 1. Each subtype adds one.
BASE_MAX_ARROWS = 3

#: How far below the full meter each attribute asks, once the slots are
#: known. Virus is not on this scale at all -- see `VIRUS_ARROWS`.
#:
#: All four are measured now. Free and Vaccine both ask for the whole meter,
#: which is what makes them the pair that shares a type; Data asks for one
#: less, read at three slots (asks 2) and at four (asks 3).
ARROWS_BELOW_MAX = {
    "Free": 0,      # measured at 3, 4 and 5 slots
    "": 0,          # a pet with no attribute is Free
    "Va": 0,        # measured at 3, 4 and 5 slots
    "Da": 1,        # measured at 3 and 4 slots
}

#: What a Virus pet is asked for, whatever the meter. Measured at three slots
#: and again at four, and 1 both times -- the one attribute whose count does
#: not grow with the game.
VIRUS_ARROWS = 1

#: The ceiling each stage band puts on the difficulty, as (top stage,
#: ceiling). Read at stages 1, 2 and 3 (three slots), 4 and 5 (four) and 6
#: and 7 (five).
STAGE_SLOTS = ((3, 1), (5, 2), (99, 3))


def charge_subtype(pet):
    """Which difficulty band this pet plays, 1 to 3.

    The stage sets a ceiling and the top tier of any stage is always the easy
    band, so the difficulty eases off from the top down rather than stepping
    at every tier:

        subtype = min(ceiling(stage), 4 - tier)

    Sixteen readings fit it, and the shape of the drops is what pins it: a
    stage 4 pet changes **only at level 6**, its maximum, where a plain
    "one off per tier" would have dropped it at level 3 as well. Stage 5
    likewise changes only at 8, while stages 6 and 7 -- the only ones whose
    ceiling leaves room for two drops -- change at 5 and again at 10.

    Stage 3 and below never change, because a ceiling of 1 leaves nothing to
    take away. That is the whole of "a Child has a single limit all over",
    and it is a consequence rather than a special case.

    The tier is `battle_utils.pet_tier_index`, the same banding the attack
    table and the Xai bar already use, so the picture and the damage cannot
    drift apart. **A pet whose module has no Level stat bands by effort
    instead** -- it would otherwise sit at level 1 forever and never leave
    the widest game, which is the same reason the Xai bar reads effort, and
    the same call decides it for both.
    """
    try:
        stage = int(getattr(pet, "stage", 0) or 0)
        level = int(getattr(pet, "level", 1) or 1)
    except (TypeError, ValueError):
        return 1

    ceiling = STAGE_SLOTS[-1][1]
    for top, slots in STAGE_SLOTS:
        if stage <= top:
            ceiling = slots
            break

    from battle.sim.battle_utils import pet_tier_index

    try:
        tier = pet_tier_index(pet, "PENZ")
    except Exception:      # pylint: disable=broad-except
        tier = 1
    return max(1, min(ceiling, 4 - tier))


def arrow_slots(pet):
    """How many arrow slots this pet plays -- three, four or five."""
    return BASE_MAX_ARROWS + charge_subtype(pet) - 1


def arrows_asked(pet):
    """How many arrows the ready phase asks this pet to fill.

    Read off the slots on offer rather than off the subtype: Free and Vaccine
    ask for the whole meter, Data one less, and a Virus pet asks for one
    whatever the meter -- measured at three slots and at four, and 1 both
    times.
    """
    attribute = getattr(pet, "attribute", "") if pet else ""
    if attribute == "Vi":
        return VIRUS_ARROWS
    return max(1, arrow_slots(pet) - ARROWS_BELOW_MAX.get(attribute or "Free", 0))


def score_arrows(shakes, pet):
    """The 0-3 an arrow count is worth: BAD, GOOD, GREAT, EXCELLENT.

    **This game scores the counter directly.** There is no meter to band and
    no super hits to count -- the player is asked for a number of arrows and
    either fills it or does not, so the distance from that number is the
    whole result. It lives here rather than in `minigame_result` because it
    needs the pet: both the slots on offer and the count asked for come from
    the Digimon, and neither is a property of the charge.

    - Exact match = EXCELLENT (3)
    - One away = GREAT (2), but see the tie below
    - Anything further = GOOD (1)
    - Barely shaking = BAD (0)

    Bad is only ever reached at the bottom of the meter: no shakes at all,
    always, and a single shake on a four- or five-slot game however close it
    lands. That is what separates a five-slot meter's `1 bad, 2 good` from a
    three-slot meter's `1 good`.

    Every one of the seven scoring rows in `utilities/DIGIROM/penz.txt` falls
    out of this.
    """
    try:
        shakes = int(shakes or 0)
    except (TypeError, ValueError):
        shakes = 0
    slots = arrow_slots(pet)
    target = arrows_asked(pet)

    # Barely shaking is a failure, and on a wider meter one shake counts as
    # barely -- unless one is what was asked for.
    if shakes <= 0:
        return 0  # BAD
    if shakes == 1 and slots >= 4 and target != 1:
        return 0  # BAD

    diff = abs(shakes - target)
    if diff == 0:
        return 3  # EXCELLENT - exact match
    if diff == 1:
        # Where the target has a neighbour on each side, only one of them is
        # GREAT: the one with more of the meter behind it, and the upper one
        # where that ties. Read off the two Data rows, the only ones whose
        # target is not at an end of the meter.
        below, above = target - 1, slots - target
        if below and above:
            great = target - 1 if below > above else target + 1
            return 2 if shakes == great else 1
        return 2  # GREAT - off by 1
    return 1  # GOOD


class CountMatchZ:
    """
    Count Match Z minigame - arrow-based counting with attribute-based scoring.
    """

    #: This minigame draws the alert phase itself, showing the arrows the
    #: player has to match, instead of leaving it to the animated sprite.
    HAS_READY_PHASE = True

    def __init__(self, ui_manager: UIManager, pet=None, animated_sprite=None) -> None:
        self.ui_manager = ui_manager
        if self.ui_manager is None:
            raise ValueError("UIManager cannot be None")
            
        self.pet = pet
        self.phase = "ready"  # ready, count
        self.press_counter = 0
        #: 1-3. Each step adds one slot and one to the count asked for.
        self.subtype = charge_subtype(pet)
        self.max_count = BASE_MAX_ARROWS + self.subtype - 1
        
        # Use the provided AnimatedSprite component
        self.animated_sprite = animated_sprite
        
        # Shake detection for mouse/touch fallback
        self.shake_detector = ShakeDetector()
        
        # Load arrow sprites from assets/ui/
        sprite_scale_factor = runtime_globals.UI_SCALE
        self._arrow_b_sprite = self.ui_manager.load_sprite_non_integer_scaling("assets/ReadyBW_ArrowB.png", sprite_scale_factor)
        self._arrow_w_sprite = self.ui_manager.load_sprite_non_integer_scaling("assets/ReadyBW_ArrowW.png", sprite_scale_factor)
        
        # Calculate arrow positions
        self._arrow_y = int(78 * runtime_globals.UI_SCALE)  # y=157 scaled
        
        self.set_phase("ready")

    def get_target_arrow_count(self):
        """How many arrows the player has to fill."""
        return arrows_asked(self.pet)

    def _calculate_arrow_positions(self, count):
        """Calculate arrow positions from left to right based on max_count mode."""
        if count <= 0:
            return []
            
        arrow_width = self._arrow_b_sprite.get_width() if self._arrow_b_sprite else int(32 * runtime_globals.UI_SCALE)
        
        # Evenly spaced across however many slots this pet plays -- three,
        # four or five, which is what `charge_subtype` decides.
        padding = int(20 * runtime_globals.UI_SCALE)
        available_width = runtime_globals.SCREEN_WIDTH - (2 * padding)
        spacing = available_width // self.max_count
        
        # Start from left side with padding
        start_x = padding + (spacing - arrow_width) // 2
        
        positions = []
        for i in range(count):
            x = start_x + (i * spacing)
            positions.append((x, self._arrow_y))
        
        return positions

    def set_phase(self, phase):
        """Set the current phase (ready or count)."""
        self.phase = phase
        if self.animated_sprite:
            self.animated_sprite.stop()
            
        if phase == "count":
            # Reset counter when starting count phase
            self.press_counter = 0
            # Setup count mode in animated sprite - use BW count sprite
            if self.animated_sprite:
                self.animated_sprite.setup_countdown_count_bw()
        elif phase == "ready":
            # Setup ready mode in animated sprite - use BW ready sprite
            if self.animated_sprite:
                self.animated_sprite.setup_countdown_ready_bw()

    def handle_event(self, event):
        """Handle input events for the minigame."""
        if not isinstance(event, tuple) or len(event) != 2:
            return False
        
        event_type, event_data = event
        
        if self.phase == "count" and event_type in ("Y", "SHAKE"):
            # Only count up to max_count
            if self.press_counter < self.max_count:
                self.press_counter += 1
                runtime_globals.game_sound.play("menu")
            return True
        return False

    def update(self):
        """Update the minigame state each frame."""
        self.shake_detector.update()
        if self.phase != "count":
            return

        # Detect shake from mouse/touch motion
        last_pos = getattr(self, '_last_mouse_pos', None)
        mouse_pos = pygame.mouse.get_pos()
        if mouse_pos == last_pos:
            return

        if self.shake_detector.add_mouse_position(mouse_pos):
            self.handle_event(("SHAKE", None))
        self._last_mouse_pos = mouse_pos

    def get_press_counter(self):
        """Get the current press counter."""
        return self.press_counter

    def calculate_result(self):
        """The 0-3 this pet's arrow count is worth -- see `score_arrows`."""
        return score_arrows(self.press_counter, self.pet)

    def draw(self, surface):
        """Draw the count match Z minigame components."""
        if self.phase == "ready":
            self.draw_ready(surface)
        else:
            self.draw_count(surface)

    def draw_ready(self, surface):
        """Draw the ready phase with attribute-based arrows."""
        # Draw animated sprite (ReadyBW)
        if self.animated_sprite:
            self.animated_sprite.draw(surface)
        
        # Draw target arrows (black arrows showing what to match)
        if self._arrow_b_sprite:
            target_count = self.get_target_arrow_count()
            positions = self._calculate_arrow_positions(target_count)
            for x, y in positions:
                surface.blit(self._arrow_b_sprite, (x, y))

    def draw_count(self, surface):
        """Draw the count phase with player's shake arrows."""
        # Draw animated sprite (CountBW)
        if self.animated_sprite:
            self.animated_sprite.draw(surface)
        
        # Draw white arrows for shakes made
        if self._arrow_w_sprite:
            positions = self._calculate_arrow_positions(self.press_counter)
            for x, y in positions:
                surface.blit(self._arrow_w_sprite, (x, y))
