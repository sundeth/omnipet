from core import game_globals, runtime_globals


# ----------------------------------------------------------------------------
# Per-attack animation timeline (shared by training and battle).
#
# Markers are in base 30fps frames. Callers convert their actual frame counter
# into base-30fps "ticks" by dividing by (FRAME_RATE / 30). The timeline runs
# for ATTACK_PREP_BASE_FRAMES ticks; the projectile is fired on the tick after
# the timeline ends. Layout:
#
#     0 .. SLIDE_START_F                  pets idle
#     SLIDE_START_F .. SLIDE_END_F        crit pets slide SPECIAL in
#     SLIDE_END_F .. SLIDE_HOLD_END_F     crit pets hold SPECIAL at landed pos
#     JUMP_START_F .. JUMP_END_F          non-crit pets jump back (TRAIN1)
#     JUMP_END_F .. MOVE_FORWARD_START_F  non-crit pets hold at back position
#     MOVE_FORWARD_START_F .. TRAIN2_START_F  all pets move forward (TRAIN1)
#     TRAIN2_START_F .. ATTACK_PREP_BASE_FRAMES  pets hold TRAIN2
#     ATTACK_PREP_BASE_FRAMES                    shot fires (sound + projectile)
# ----------------------------------------------------------------------------
ATTACK_PREP_BASE_FRAMES = 40
SLIDE_START_F = 8
SLIDE_END_F = 25
SLIDE_HOLD_FRAMES = 10
SLIDE_HOLD_END_F = SLIDE_END_F + SLIDE_HOLD_FRAMES
JUMP_START_F = 10
JUMP_END_F = 20
MOVE_FORWARD_START_F = 20
TRAIN2_START_F = 32
BACK_OFFSET_SLIDE = 14   # px (UI-scaled) where SPECIAL landed → matches TRAIN1 anchor
BACK_OFFSET_JUMP = 10    # px (UI-scaled) max jump-back distance for non-crit pets
JUMP_HEIGHT = 7          # px (UI-scaled) peak of the jump-back arc


def compute_attack_anim_state(elapsed_30fps, is_crit_wave, has_special):
    """Resolve a pet's animation state at a point in the attack-prep window.

    Args:
        elapsed_30fps: float frames elapsed since prep start, in base 30fps.
        is_crit_wave: True if this attack should trigger the SPECIAL slide-in.
        has_special: True if the pet actually has a SPECIAL frame to slide.

    Returns:
        (frame_enum, forward_offset, jump_offset, slide_progress)
        - frame_enum: PetFrame to draw at this tick.
        - forward_offset: px (unscaled) backward from rest position; >= 0.
          The caller is responsible for the sign — right-side pets add it to x,
          left-side pets subtract it.
        - jump_offset: px (unscaled) above rest position; >= 0.
        - slide_progress: float in [0, 1] when the pet is sliding (use for
          slide-x interpolation), else None. 0 = off-screen edge, 1 = landed.
    """
    # Local import keeps this module free of pygame/runtime-globals cycles.
    from models.animation import PetFrame

    f = elapsed_30fps
    pet_slides = is_crit_wave and has_special

    if pet_slides:
        if f < SLIDE_START_F:
            return PetFrame.IDLE1, 0.0, 0.0, None
        if f < SLIDE_END_F:
            progress = (f - SLIDE_START_F) / max(1, SLIDE_END_F - SLIDE_START_F)
            return PetFrame.SPECIAL, 0.0, 0.0, progress
        if f < SLIDE_HOLD_END_F:
            return PetFrame.SPECIAL, 0.0, 0.0, 1.0
        if f < MOVE_FORWARD_START_F:
            return PetFrame.TRAIN1, float(BACK_OFFSET_SLIDE), 0.0, None
        if f < TRAIN2_START_F:
            mf = (f - MOVE_FORWARD_START_F) / max(1, TRAIN2_START_F - MOVE_FORWARD_START_F)
            return PetFrame.TRAIN1, BACK_OFFSET_SLIDE * (1.0 - mf), 0.0, None
        return PetFrame.TRAIN2, 0.0, 0.0, None

    if f < JUMP_START_F:
        return PetFrame.IDLE1, 0.0, 0.0, None
    if f < JUMP_END_F:
        jb = (f - JUMP_START_F) / max(1, JUMP_END_F - JUMP_START_F)
        forward = BACK_OFFSET_JUMP * jb
        jump = JUMP_HEIGHT * (jb * 2 if jb < 0.5 else (1 - jb) * 2)
        return PetFrame.TRAIN1, forward, jump, None
    if f < MOVE_FORWARD_START_F:
        return PetFrame.TRAIN1, float(BACK_OFFSET_JUMP), 0.0, None
    if f < TRAIN2_START_F:
        mf = (f - MOVE_FORWARD_START_F) / max(1, TRAIN2_START_F - MOVE_FORWARD_START_F)
        return PetFrame.TRAIN1, BACK_OFFSET_JUMP * (1.0 - mf), 0.0, None
    return PetFrame.TRAIN2, 0.0, 0.0, None


def _get_frame_rate():
    """Get frame rate from configuration, with fallback for early initialization."""
    try:
        return game_globals.configuration.frame_rate
    except (AttributeError, RuntimeError):
        return 30  # Default fallback

def _get_screen_width():
    """Get the live render width, with fallback for early initialization.

    runtime_globals.SCREEN_WIDTH is authoritative: it always matches the
    canvas actually being rendered.  configuration.screen_width can lag
    behind it on Android, where the entry point picks the render resolution
    from the device screen without writing it back to the configuration --
    scaling attack speed from the config there made attacks crawl across
    the (much wider) real canvas.
    """
    if runtime_globals.SCREEN_WIDTH and runtime_globals.SCREEN_WIDTH > 0:
        return runtime_globals.SCREEN_WIDTH
    try:
        return game_globals.configuration.screen_width
    except (AttributeError, RuntimeError):
        return 240


# Timing constants - evaluated lazily via update_combat_constants()
ALERT_DURATION_FRAMES = 50
WAIT_AFTER_BAR_FRAMES = 30
IMPACT_DURATION_FRAMES = 60
WAIT_ATTACK_READY_FRAMES = 20
RESULT_SCREEN_FRAMES = 90
BAR_HOLD_TIME_MS = 2500
PUNCH_HOLD_TIME_MS = 18000
ATTACK_SPEED = 4

ENEMY_ENTRY_SPEED = 1
IDLE_ANIM_DURATION = 90
ALERT_FRAME_DELAY = 10
AFTER_ATTACK_DELAY_FRAMES = 50
LEVEL_DURATION_FRAMES = 60

READY_FRAME_COUNTER = 60
ALERT_FRAME_COUNTER = 90

# How long the critical-attack special-frame slide-in takes, in seconds.
# Increase to slow the entrance down; decrease to speed it up.
SPECIAL_SLIDE_IN_SECONDS = 0.5

def update_combat_constants():
    """Update combat constants based on current frame rate and screen width."""
    global ALERT_DURATION_FRAMES, WAIT_AFTER_BAR_FRAMES, IMPACT_DURATION_FRAMES, WAIT_ATTACK_READY_FRAMES
    global RESULT_SCREEN_FRAMES, ATTACK_SPEED, ENEMY_ENTRY_SPEED, IDLE_ANIM_DURATION
    global ALERT_FRAME_DELAY, AFTER_ATTACK_DELAY_FRAMES, LEVEL_DURATION_FRAMES
    global READY_FRAME_COUNTER, ALERT_FRAME_COUNTER

    frame_rate = _get_frame_rate()
    screen_width = _get_screen_width()
    
    ALERT_DURATION_FRAMES = int(60 * (frame_rate / 30))
    WAIT_AFTER_BAR_FRAMES = int(30 * (frame_rate / 30))
    IMPACT_DURATION_FRAMES = int(60 * (frame_rate / 30))
    WAIT_ATTACK_READY_FRAMES = int(20 * (frame_rate / 30))
    RESULT_SCREEN_FRAMES = int(90 * (frame_rate / 30))
    ATTACK_SPEED = 4 * (screen_width / 240)
    ENEMY_ENTRY_SPEED = 1 * (screen_width / 240)
    IDLE_ANIM_DURATION = int(90 * (frame_rate / 30))
    ALERT_FRAME_DELAY = int(10 * (frame_rate / 30))
    AFTER_ATTACK_DELAY_FRAMES = int(50 * (frame_rate / 30))
    LEVEL_DURATION_FRAMES = int(60 * (frame_rate / 30))
    READY_FRAME_COUNTER = int(60 * (frame_rate / 30))
    ALERT_FRAME_COUNTER = int(90 * (frame_rate / 30))


# Usage elsewhere:
# speed = get_attack_speed()
# entry_speed = get_enemy_entry_speed()


#: ``opponent_device_version`` value meaning "any device that is not the one
#: the pet was hatched on". No real device carries a negative version, so it
#: is safe as a sentinel, and it lets a module say "battle with any other
#: version" without listing every pair.
ANY_OTHER_DEVICE = -1
