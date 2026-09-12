import pygame

#=====================================================================
# Pygame Version Compatibility
#=====================================================================
PYGAME_VERSION = tuple(map(int, pygame.version.ver.split('.')))
IS_PYGAME2 = PYGAME_VERSION >= (2, 0, 0)
# Use SRCALPHA for both versions - it's compatible
COMPATIBLE_SRCALPHA = pygame.SRCALPHA

#=====================================================================
# Configuration Accessor Properties
# These provide backwards-compatible access to configuration values
# The actual values are stored in game_globals.configuration
#=====================================================================

def _get_frame_rate():
    """Get frame rate from game_globals.configuration."""
    from core import game_globals
    return game_globals.configuration.frame_rate

def _get_max_pets():
    """Get max pets from game_globals.configuration."""
    from core import game_globals
    return game_globals.configuration.max_pets

def _get_debug_mode():
    """Get debug mode from game_globals.configuration."""
    from core import game_globals
    return game_globals.configuration.debug_mode

def _get_debug_file_logging():
    """Get debug file logging from game_globals.configuration."""
    from core import game_globals
    return game_globals.configuration.debug_file_logging

def _get_show_fps():
    """Get show fps from game_globals.configuration."""
    from core import game_globals
    return game_globals.configuration.show_fps

def _get_debug_blit_logging():
    """Get debug blit logging from game_globals.configuration."""
    from core import game_globals
    return game_globals.configuration.debug_blit_logging

def _get_debug_battle_info():
    """Get debug battle info from game_globals.configuration."""
    from core import game_globals
    return game_globals.configuration.debug_battle_logging


# Module-level class to make constants behave like a module with properties
class _ConfigProxy:
    """Proxy class that provides property access to configuration values."""
    
    @property
    def FRAME_RATE(self):
        return _get_frame_rate()
    
    @property
    def MAX_PETS(self):
        return _get_max_pets()
    
    @property
    def DEBUG_MODE(self):
        return _get_debug_mode()
    
    @property
    def DEBUG(self):
        return _get_debug_mode()
    
    @property
    def DEBUG_FILE_LOGGING(self):
        return _get_debug_file_logging()
    
    @property
    def LOGGING(self):
        return _get_debug_file_logging()
    
    @property
    def SHOW_FPS(self):
        return _get_show_fps()
    
    @property
    def DEBUG_BLIT_LOGGING(self):
        return _get_debug_blit_logging()
    
    @property
    def LOG_BLITS(self):
        return _get_debug_blit_logging()
    
    @property
    def DEBUG_BATTLE_INFO(self):
        return _get_debug_battle_info()


# Global instance for property access
_config = _ConfigProxy()

# Dynamic attribute access for backwards compatibility
def __getattr__(name):
    """Provide dynamic access to configuration values."""
    if name in ('FRAME_RATE', 'MAX_PETS', 'DEBUG_MODE', 'DEBUG', 
                'DEBUG_FILE_LOGGING', 'LOGGING', 'SHOW_FPS',
                'DEBUG_BLIT_LOGGING', 'LOG_BLITS', 'DEBUG_BATTLE_INFO'):
        return getattr(_config, name)
    raise AttributeError(f"module 'core.constants' has no attribute '{name}'")


#=====================================================================
# Static Constants (not configurable)
#=====================================================================

FRAME_SIZE = 48  # Original pet sprite frame size

#=====================================================================
# Screen and Window Constants
#=====================================================================
# SCREEN_WIDTH, SCREEN_HEIGHT = 240, 240
# FRAME_SIZE = 48  # Original pet sprite frame size
# FRAME_RATE = 30  # Frames per second

#=====================================================================
# Pet Constants
#=====================================================================
# MAX_PETS = 4
# Note: PET_WIDTH, PET_HEIGHT now in runtime_globals
STAGES = [
    "0-Egg", "I-Fresh", "II-In-Training", "III-Rookie",
    "IV-Champion", "V-Ultimate", "VI-Mega", "VII-Super Ultimate"
]
ATTR_COLORS = {
            "Da": (66, 165, 245),
            "Va": (102, 187, 106),
            "Vi": (237, 83, 80),
            "": (171, 71, 188),
            "???": (0, 0, 0)
        }
#=====================================================================
# Game Mechanics
#=====================================================================
MOVE_SPEED = 0.5  # Movement speed in subpixels/frame
IDLE_PROBABILITY = 0.2  # 20% chance of idle vs. moving
CLEANING_SPEED = 6  # Speed of cleaning animation
RELIABILITY_MIN = 0
RELIABILITY_MAX = 31
DIGISOUL_DNA_TYPES = (
    "Beast", "Bird", "Machine", "Water",
    "Dragon", "Insect", "Holy", "Dark",
)
SLEEP_RECOVERY_HOURS = 8  # Hours needed to fully recover
SLEEP_MANUAL_DURATION_HOURS = 1  # Duration when manually sleeping
SLEEP_DISTURBANCE_THRESHOLD_SECONDS = 7200  # 2 hours threshold for disturbance detection
# BOOT_TIMER_FRAMES is calculated dynamically based on frame_rate 

MAX_LEVEL = {0: 0, 1: 1, 2: 3, 3: 4, 4: 6, 5: 8, 6: 10, 7: 10, 8: 10}
EXPERIENCE_LEVEL = {0: 0, 1: 0, 2: 50, 3: 150, 4: 500, 5: 800, 6: 1000, 7: 1500, 8: 2000, 9: 3000, 10:5000}
HP_LEVEL = {
    0: 0,    # Egg
    1: 0,    # Fresh
    2: 10,   # In-Training
    3: 10,   # Rookie
    4: 12,   # Champion
    5: 15,   # Ultimate
    6: 18,   # Mega
    7: 20,   # Super Ultimate
    8: 20    # (If used, for extra stage)
}
ATK_LEVEL = {
    0: 0,   # Egg
    1: 0,   # Fresh
    2: 2,   # In-Training (10 // 4 = 2)
    3: 2,   # Rookie      (10 // 4 = 2)
    4: 3,   # Champion    (12 // 4 = 3)
    5: 3,   # Ultimate    (15 // 4 = 3)
    6: 4,   # Mega        (18 // 4 = 4)
    7: 5,   # Super Ultimate (20 // 4 = 5)
    8: 5    # Extra stage (20 // 4 = 5)
}

# Digimon Mini "terahit": the B-button count that produces the strongest
# attack pattern, out of a maximum of 31. The Mini's whole battle is a mash
# whose count picks Single (attack 1), Double (2), Triple (3) or Hyper (6);
# with every Digimon on a flat 6 HP a Hyper lands as a one-shot kill, so this
# is the device's skill ceiling, and it climbs with stage.
#
# Source: the official Ver.2.0+3.0 playbook, printed page 102, which gives the
# threshold per stage. Individual Digimon sit at or above their stage's figure
# - the per-form values are tabulated in modules/DMM/DMM_RESEARCH.md - and the
# guide stops at LEVEL 6, so stage 7 is taken from the two hidden forms, which
# both read 29.
#
# NOT WIRED UP. get_minigame_strength grades the Dummy Bar on fixed 5/10/14
# cutoffs shared by every module; honouring this table means scaling those
# cutoffs by the pet's stage. Recorded now so the values are not lost.
TERAHIT_COUNT = {
    0: 0,    # Egg              - cannot battle
    1: 0,    # Fresh            - cannot battle
    2: 21,   # In-Training
    3: 21,   # Rookie
    4: 25,   # Champion
    5: 27,   # Ultimate
    6: 30,   # Mega
    7: 29,   # Super Ultimate   - the hidden LEVEL 7 forms
    8: 29    # Extra stage
}
TERAHIT_MAX_COUNT = 31  # the highest count the Mini's meter reads

# Weight at which the "Burpmon" 99g effect turns the pet into Burpmon, and the
# weight it has to fall back to before the pet returns to its own form. The
# Digimon Twin - the only device with this effect - uses 80 g, so the trigger
# is not the 99 g the field name suggests. The device also only lets a pet out
# of it at 65 g or below; that hysteresis is documented but not modelled, so
# the pet reverts as soon as it is back under the trigger.
BURPMON_WEIGHT = 80
#=====================================================================
# UI Settings
#=====================================================================
# UI scaling values moved to runtime_globals (mutable at runtime)
# Font and background colors remain constant

FONT_COLOR_DEFAULT = (255, 255, 255)
FONT_COLOR_GRAY = (150, 150, 150)
FONT_COLOR_GREEN = (0, 231, 58)
FONT_COLOR_RED = (237, 83, 80)
FONT_COLOR_YELLOW = (255, 255, 0)
FONT_COLOR_BLUE = (0, 0, 255)
FONT_COLOR_ORANGE = (255, 200, 50)
BACKGROUND_COLOR = (198, 203, 173)

#=====================================================================
# Paths: General Resources
#=====================================================================
MODULES_FOLDER = "modules"
ARROW_IMAGE_PATH = "assets/Arrow.png"
#FOOD_SHEET_PATH = "assets/FoodVitamin.png"
ATK_FOLDER = "assets/atk"
ATK_CRIT_FOLDER = "assets/atk_crit"

#=====================================================================
# Paths: UI Sprites
#=====================================================================
#SELECTION_OFF_PATH = "assets/SelectionOff.png"
#SELECTION_ON_PATH = "assets/SelectionOn.png"
#MENU_BACKGROUND_PATH = "assets/MenuBackground.png"
#PET_SELECTION_BACKGROUND_PATH = "assets/PetSelectionBack.png"
#PET_SELECTION_SMALL_ON_PATH = "assets/PetSelectionSmallOn.png"
#PET_SELECTION_SMALL_OFF_PATH = "assets/PetSelectionSmallOff.png"
GIFT_PATH = "assets/Gift.png"
ALERT_ICON_PATH = "assets/Alert.png"
CALL_SIGN_INVERSE_PATH = "assets/CallSignInverted.png"

#=====================================================================
# Paths: Battle & Training Sprites
#=====================================================================
#BATTLE_BACKGROUND_PATH = "assets/BattleBackground.png"
#TRAINING_BACKGROUND_PATH = "assets/TrainingBackground.png"
HEADTRAINING_PATH = "assets/HeadTraining.png"
VS_PATH = "assets/Vs.png"
#STRIKES_BACK_PATH = "assets/StrikesBar.png"
#STRIKE_PATH = "assets/Strike.png"
#BATTLE_ICON_PATH = "assets/BattleIcon.png"
#NEXT_BATTLE_ICON_PATH = "assets/NextBattle.png"
#RESTART_BATTLE_ICON_PATH = "assets/RestartBattle.png"
#HEAD_TRAINING_ICON_PATH = "assets/HeadTrainingIcon.png"
#VERSUS_BATTLE_ICON_PATH = "assets/VersusBattle.png"
#JOGRESS_ICON_PATH = "assets/Jogress.png"
#ARMOR_EVOLUTION_ICON_PATH = "assets/ArmorEvolution.png"
#DUMMY_TRAINING_ICON_PATH = "assets/BagIcon.png"
#SHAKE_MATCH_ICON_PATH = "assets/CountTrainingIcon.png"
#EXCITE_MATCH_ICON_PATH = "assets/ExciteTrainingIcon.png"
#PUNCH_MATCH_ICON_PATH = "assets/PunchTrainingIcon.png"
XAIARROW_ICON_PATH = "assets/XaiArrow.png"
BOSS_MULTIPLIER = 1.5 

#=====================================================================
# Paths: Pet Sprites
#=====================================================================
DEAD_FRAME_PATH = "assets/Dead.png"
#AGE_ICON_PATH = "assets/Age.png"
#WEIGHT_ICON_PATH = "assets/Scale.png"
#MODULE_ICON_PATH = "assets/Module.png"
#VERSION_ICON_PATH = "assets/Version.png"
#MISTAKES_ICON_PATH = "assets/Mistakes.png"
#TRAITED_ICON_PATH = "assets/Traited.png"
#SPECIAL_ICON_PATH = "assets/Special.png"
#SHINY_ICON_PATH = "assets/Shiny.png"
#SHOOK_ICON_PATH = "assets/Shook.png"
#OVERFEED_ICON_PATH = "assets/Overfeed.png"
#SICK_ICON_PATH = "assets/Sick1.png"
#SLEEP_DISTURBANCES_ICON_PATH = "assets/SleepDisturbances.png"
XAI_ICON_PATH = "assets/Xai.png"
TROPHIES_ICON_PATH = "assets/Trophies.png"
#VITAL_VALUES_ICON_PATH = "assets/vitalvalues.png"
#DIGIDEX_ICON_PATH = "assets/DigidexIcon.png"
#FREEZER_ICON_PATH = "assets/FreezerIcon.png"


#=====================================================================
# Paths: UI Icons
#=====================================================================
HEART_EMPTY_ICON_PATH = "assets/Heart Empty.png"
HEART_HALF_ICON_PATH = "assets/Heart Half.png"
HEART_FULL_ICON_PATH = "assets/Heart Full.png"
#ENERGY_BAR_ICON_PATH = "assets/Energy Bar Count - Green.png"
#ENERGY_BAR_BACK_ICON_PATH = "assets/Energy Bar.png"
#LEVEL_ICON_PATH = "assets/Level.png"
#EXP_ICON_PATH = "assets/Exp.png"

#=====================================================================
# Paths: Scene Backgrounds
#=====================================================================
SPLASH_PATH = "assets/Splash.png"
MAIN_MENU_PATH = "assets/Menu.png"
#DIGIDEX_BACKGROUND_PATH = "assets/Digidex.png"

#=====================================================================
# Paths: Battle Scene Sprites
#=====================================================================
#BATTLE_SPRITE_PATH = "assets/Battle.png"
#BATTLE_LEVEL_SPRITE_PATH = "assets/BattleLevel.png"
#BAR_BACK_PATH = "assets/StrengthBarBack.png"
#BAR_PIECE_PATH = "assets/StrengthBar.png"
#TRAINING_MAX_PATH = "assets/TrainingMax.png"

# Themed dummy charge bar sprites
BAR_PIECE_GREEN_PATH = "assets/DummyBar_Green.png"
BAR_PIECE_YELLOW_PATH = "assets/DummyBar_Yellow.png"
BAR_PIECE_RED_MAX_PATH = "assets/DummyBarMax_Red.png"
BAR_BACK_GREEN_PATH = "assets/DummyBarBack_Green.png"
BAR_BACK_RED_PATH = "assets/DummyBarBack_Red.png"

# Head training specific sprites
HEADTRAINING_BACK_PATH = "assets/HeadTraining_Back.png"
HEADTRAINING_STRIKE_PATH = "assets/HeadTraining_Strike.png"

#ALERT_SPRITE_PATH = "assets/Alert.png"
#GO_SPRITE_PATH = "assets/Go.png"
#BAD_SPRITE_PATH = "assets/Bad.png"
#GOOD_SPRITE_PATH = "assets/Good.png"
#GREAT_SPRITE_PATH = "assets/Great.png"
#EXCELLENT_SPRITE_PATH = "assets/Excellent.png"
#READY_SPRITE_PATH = "assets/Ready.png"
#BATTLE1_PATH = "assets/Battle1.png"
#BATTLE2_PATH = "assets/Battle2.png"
BAG1_PATH = "assets/Bag1.png"
BAG2_PATH = "assets/Bag2.png"
BRICK1_PATH = "assets/Brick1.png"
BRICK2_PATH = "assets/Brick2.png"
ROCK1_PATH = "assets/Rock1.png"
ROCK2_PATH = "assets/Rock2.png"
TREE1_PATH = "assets/Tree1.png"
TREE2_PATH = "assets/Tree2.png"
MOGERA1_PATH = "assets/Mogera1.png"
MOGERA2_PATH = "assets/Mogera2.png"
MOGERA3_PATH = "assets/Mogera3.png"
ANTIG1_PATH = "assets/AntiG1.png"
ANTIG2_PATH = "assets/AntiG2.png"
TRAININGHIT1_PATH = "assets/TrainingHit1.png"
TRAININGHIT2_PATH = "assets/TrainingHit2.png"

#=====================================================================
# Paths: Training Sprites
#=====================================================================
READY_SPRITES_PATHS = {
    1: "assets/Ready1.png",
    2: "assets/Ready2.png",
    3: "assets/Ready3.png"
}

COUNT_SPRITES_PATHS = {
    4: "assets/Count4.png",
    3: "assets/Count3.png",
    2: "assets/Count2.png",
    1: "assets/Count1.png"
}

MEGA_HIT_PATH = "assets/MegaHit.png"
CLEAR1_PATH = "assets/Clear1.png"
CLEAR2_PATH = "assets/Clear2.png"
WARNING1_PATH = "assets/Warning1.png"
WARNING2_PATH = "assets/Warning2.png"
HIT_ANIMATION_PATH = "assets/Hit.png"
KO_PATH = "assets/KO.png"

ITEM_SPRITESHEET = "assets/Items.png"
ITEM_SPRITE_SIZE = 48  # Each cell is 48x48 in a 5x7 grid

#=====================================================================
# Paths: Additional Resources (previously hardcoded)
#=====================================================================
FONT_TTF_PATH = "assets/vpet_font.TTF"
FONT_ALT_TTF_PATH = "assets/vpet_font_alt.ttf"
ICON_ON_PATH = "assets/IconOn.png"
ICON_OFF_PATH = "assets/IconOff.png"
OMNI_WIFI_PATH = "assets/OmniWifi.png"
SLEEP_ICON_PATH = "assets/SleepIcon.png"
WAKE_ICON_PATH = "assets/WakeIcon.png"
EVO1_PATH = "assets/Evo1.png"
EVO2_PATH = "assets/Evo2.png" 
EVO3_PATH = "assets/Evo3.png"
EVO5_PATH = "assets/Evo5.png"
FOG_PATH = "assets/Fog.png"
ORB_PATH = "assets/Orb.png"
LIGHT_SOURCE_PATH = "assets/LightSource.png"
LIGHT_PARTICLE_PATH = "assets/LightParticle.png"
DNA_PATH = "assets/Dna.png"

#: The adapter icon, shown in the jogress slot a real device occupies.
SERIAL_PATH = "assets/Serial.png"
UNKNOWN_SPRITE_PATH = "assets/Unknown.png"
TRAITED_EGG_PATH = "assets/TraitedEgg.png"
OMNIPET_LOGO_PATH = "assets/OmnipetLogo.png"
CONTROLLERS_PC_PATH = "assets/ControllersPC.png"
CONTROLLERS_BATO_PATH = "assets/ControllersBato.png"
CONTROLLERS_PI_PATH = "assets/ControllersPi.png"
CONTROLLERS_JOY_PATH = "assets/ControllersJoy.png"
DMC_SOUNDS_PATH = "assets/dmc_sounds"


#=====================================================================
# Discord / Online Settings
#=====================================================================
# Discord bot connection
DISCORD_BOT_LOCAL_URL = "http://localhost:5000"
DISCORD_BOT_MAIN_URL = "http://localhost:5000"
DISCORD_ENABLED = True
DISCORD_DEBUG = True  # Enable detailed Discord logging

# Discord UI
DISCORD_ROOM_REFRESH_RATE = 5  # Seconds between room list refreshes
DISCORD_POLL_RATE = 1  # Seconds between status polls

OMNINET_LOCAL_URL = "https://dev.omnipet.app.br/"
OMNINET_MAIN_URL = "https://omnipet.app.br"
