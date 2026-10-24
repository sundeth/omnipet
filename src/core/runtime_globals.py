import os
import sys
import random

# Defence-in-depth: on some Android emulators (notably Bluestacks) the
# entry-point script's ``sys.path.insert(0, '<app>/src')`` doesn't take
# effect before this module is imported, and the top-level
# ``from input.X import Y`` lines below fail with ModuleNotFoundError.
# Try several roots to locate the sibling ``input`` package and add its
# parent (i.e. ``src/``) to sys.path before the imports run.
def _ensure_src_on_path():
    candidates = []
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        # p4a may set __file__ to the .pyc inside __pycache__; walk up past it
        if os.path.basename(here) == "__pycache__":
            here = os.path.dirname(here)
        # here is now .../src/core/; parent is .../src/
        candidates.append(os.path.dirname(here))
        # also try grandparent in case we're nested one level deeper
        candidates.append(os.path.dirname(os.path.dirname(here)))
    except Exception:
        pass
    try:
        cwd = os.getcwd()
        candidates.append(os.path.join(cwd, "src"))
        candidates.append(cwd)
    except Exception:
        pass
    for src in candidates:
        try:
            if src and os.path.isdir(os.path.join(src, "input")) and src not in sys.path:
                sys.path.insert(0, src)
                return
        except Exception:
            continue

_ensure_src_on_path()

from models.game_console import GameConsole
from models.game_item import GameItem
from models.game_message import GameMessage
from models.game_sound import GameSound
from input.i2c_utils import I2CUtils
from input.input_manager import InputManager
from input.shake_detector import ShakeDetector

#=====================================================================
# Runtime (Non-Persistent) Global Variables
#=====================================================================

# --- Android Environment ---
APP_ROOT = ""  # Set to os.getcwd() on Android for absolute path building
# Auto-detected at import time: python-for-android always sets
# ANDROID_ARGUMENT in the process environment.  Detecting here (instead of
# relying on the entry point assigning it later) matters because module-level
# singletons below (e.g. InputManager, which enables the accelerometer on
# Android) are constructed during this import, before any entry-point code
# gets a chance to run.  The Android entry points still assign True
# explicitly, which is harmless.
IS_ANDROID = "ANDROID_ARGUMENT" in os.environ

KEYBOARD_MODE = 1
MOUSE_MODE = 2
TOUCH_MODE = 3
GPIO_MODE = 4
INPUT_MODE = KEYBOARD_MODE
INPUT_MODE_FORCED = False  # If True, INPUT_MODE won't auto-switch based on input device

def use_virtual_keyboard() -> bool:
    """Return True when the on-screen virtual keyboard should be shown.

    Android relies on the native system keyboard (handled separately).
    Touch / GPIO modes have no physical keyboard; the virtual one is needed.
    Mouse / Keyboard modes assume a physical keyboard and skip the overlay.
    """
    if IS_ANDROID:
        return False
    return INPUT_MODE in (TOUCH_MODE, GPIO_MODE)

# --- Resolution and Scaling (Mutable) ---
SCREEN_WIDTH = 240
SCREEN_HEIGHT = 240
UI_SCALE = 1.0
# The internal canvas the scenes render to (SCREEN_WIDTH x SCREEN_HEIGHT).
# The main loop scales this onto the actual window each frame, so the render
# resolution and the window size can differ.  Set during display setup.
render_surface = None
# The render resolution the currently-loaded save was written at.  Pet/poop
# coordinates are absolute pixels, so when a save written at a different
# resolution is loaded they must be re-placed for the current dimensions.
# Set by game_globals.load(); consumed when the game scene is (re)entered.
save_render_resolution = None
PET_WIDTH = 48
PET_HEIGHT = 48
# Boss render size: PET size * BOSS_MULTIPLIER snapped to the pixel-perfect
# ladder (see utils.sprite_utils.snap_pet_sprite_size).
PET_WIDTH_BOSS = 96
PET_HEIGHT_BOSS = 96
MENU_ICON_SIZE = 24
OPTION_ICON_SIZE = 48
OPTION_FRAME_WIDTH = 96
OPTION_FRAME_HEIGHT = 116
PET_ICON_SIZE = 48
FONT_SIZE_SMALL = 24
FONT_SIZE_MEDIUM = 28
FONT_SIZE_MEDIUM_LARGE = 30
FONT_SIZE_LARGE = 40

# --- Scene and State Control ---
game_state = "boot"
game_state_update = False
# When set, SceneConnect opens directly on this view (e.g. "shop_modules")
# instead of the main menu.  Consumed once, then cleared.
scene_connect_initial_view = None
# When set, SceneBattle opens on this view instead of its main menu:
# (view name, kwargs), e.g. ("specials", {"module_name": "IC"}) as the
# training Bonus list's BACK leaves it.  Consumed once, then cleared.
scene_battle_initial_view = None
# "bonus": SceneTraining opens on its Bonus list (the iC's minigames), and
# training_bonus_return is the SceneBattle view (as above) its BACK returns
# to.  Both consumed once, then cleared.
scene_training_initial_view = None
training_bonus_return = None
# If set, SceneEggSelection jumps directly into that module's egg picker,
# bypassing the category selection step.  Cleared after consumption.
preselected_module = None

# --- Main Menu Navigation ---
main_menu_index = -1

# --- Menu Selections ---
food_index = 0
strategy_index = 0
training_focus = None  # TRAINING_MODES key of the minigame the menu reopens on
training_bonus_focus = None  # the same for the Bonus list (BONUS_MODES)
battle_index = {}

# --- Runtime-only Assets and Selections ---
feeding_frames = []
selected_pets = []
misc_sprites = {}
battle_enemies = {}
pet_sprites = {}
# Each pet's right-facing frames, {left frame surface: right frame surface}
# (utils.sprite_utils.pair_right_frames); a frame without one is mirrored.
pet_sprites_right = {}
evolution_data = []
evolution_pet = None
last_headtohead_pattern = random.randint(0, 5)
special_encounter = []
# A C'mon Switch close-up on the main game screen: {"pet": ..., "start":
# monotonic seconds}, or None (utils.accessory_utils).
pet_closeup = None
# A battle-run event being started: {"name", "item", "item_quantity",
# "reward_round"}; the special encounter it starts takes it over
# (battle.battle_encounter). None otherwise.
special_run = None
# A card-battle event being started: {"module", "event_id", "name",
# "opponent", "opponent_version"}; the battle takes it over and fights that
# monster (battle.battle_encounter, utils.card_battle). None otherwise.
card_battle = None
# A Friend just won in a special encounter, waiting to be celebrated on the
# main game screen: {"name": ..., "module": ...}.  Runtime only — the Friend
# itself is already recorded in the save; this is just the little show.
friend_celebration = None

# --- Global Managers ---
game_sound = GameSound()
game_console = GameConsole()
game_message = GameMessage()
game_input = InputManager()
game_modules = {}
game_module_flag = {}
game_pet_eating = {}

default_items = {
    # The id and sprite keep their original names: saved inventories reference
    # the id, and the artwork is shipped under the old filename. Only what the
    # player reads changed.
    "protein": GameItem(
        id="default-protein",
        name="Food",
        description="Basic food. Refills hunger.",
        sprite_name="Protein.png",
        module="core",
        effect="status_change",
        status="hunger",
        amount=1,
        boost_time=0,
        component_item=""
    ),
    "vitamin": GameItem(
        id="default-vitamin",
        name="Vitamin",
        description="Basic food. Refills strength.",
        sprite_name="Vitamin.png",
        module="core",
        effect="status_change",
        status="strength",
        amount=1,
        boost_time=0,
        component_item=""
    )
}

# --- Pet/Gameplay Flags ---
pet_alert = False
show_hearts = False
check_shaking = False

# --- Ruleset Flags ---
dmc_enabled = False
penc_enabled = False
dmx_enabled = False
vb_enabled = False

# --- Hardware/Input ---
i2c = I2CUtils()
shake_detector = ShakeDetector(i2c)
last_input_frame = 0

#=====================================================================
# Resolution Update Helper
#=====================================================================
def update_resolution_constants(width: int = None, height: int = None) -> None:
    """
    Update resolution-dependent runtime values.
    Call this after display setup to scale UI elements.
    
    If width/height not provided, uses values from game_globals.configuration.
    """
    global SCREEN_WIDTH, SCREEN_HEIGHT, UI_SCALE
    global MENU_ICON_SIZE, OPTION_ICON_SIZE, OPTION_FRAME_WIDTH, OPTION_FRAME_HEIGHT, PET_ICON_SIZE
    global FONT_SIZE_SMALL, FONT_SIZE_MEDIUM, FONT_SIZE_MEDIUM_LARGE, FONT_SIZE_LARGE
    global PET_WIDTH, PET_HEIGHT, PET_WIDTH_BOSS, PET_HEIGHT_BOSS

    # Get resolution from configuration if not provided
    if width is None or height is None:
        try:
            from core import game_globals
            config = game_globals.configuration
            width = config.screen_width
            height = config.screen_height
        except (ImportError, AttributeError):
            width = width or 240
            height = height or 240

    SCREEN_WIDTH = width
    SCREEN_HEIGHT = height
    UI_SCALE = height / 240.0

    MENU_ICON_SIZE = int(24 * UI_SCALE)
    OPTION_ICON_SIZE = int(48 * UI_SCALE)
    OPTION_FRAME_WIDTH = int(96 * UI_SCALE)
    OPTION_FRAME_HEIGHT = int(116 * UI_SCALE)
    PET_ICON_SIZE = int(48 * UI_SCALE)

    FONT_SIZE_SMALL = int(24 * UI_SCALE)
    FONT_SIZE_MEDIUM = int(28 * UI_SCALE)
    FONT_SIZE_MEDIUM_LARGE = int(30 * UI_SCALE)
    FONT_SIZE_LARGE = int(40 * UI_SCALE)

    # The slot a pet is drawn in, from how many pets are actually in the party
    # rather than the Max Pets setting — a party of two on a device configured
    # for six was being drawn at the six-pet size for no reason. The divisor
    # still floors at 4 so a lone pet does not fill the screen. The result is
    # snapped to the pixel-perfect ladder (16/32/48*k); the boss size gets its
    # own snap since BOSS_MULTIPLIER (1.5x) lands between ladder steps.
    from utils.sprite_utils import snap_pet_sprite_size
    try:
        from core import game_globals
        party = len([p for p in game_globals.pet_list
                     if getattr(p, "state", None) != "dead"])
        # Before a save is loaded the party is empty; Max Pets is the best
        # guess available then, and load() recomputes once the pets exist.
        slots = party or game_globals.configuration.max_pets
        PET_WIDTH = PET_HEIGHT = snap_pet_sprite_size(height // max(slots, 4))
    except Exception:
        PET_WIDTH = PET_HEIGHT = snap_pet_sprite_size(height // 2)
    try:
        from core import constants
        boss_target = PET_WIDTH * constants.BOSS_MULTIPLIER
    except Exception:
        boss_target = PET_WIDTH * 1.5
    PET_WIDTH_BOSS = PET_HEIGHT_BOSS = snap_pet_sprite_size(boss_target, allow_up=True)

    # Also update combat constants if available
    try:
        import battle.combat_constants as battle_constants
        if hasattr(battle_constants, "update_combat_constants"):
            battle_constants.update_combat_constants()
    except Exception:
        pass