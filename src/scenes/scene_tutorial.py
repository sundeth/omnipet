"""
Scene Tutorial
Interactive tutorial scene that guides players through game mechanics.
Uses embedded scenes and custom dialog/focus overlays.
"""

import pygame
import os
import json

from ui.windows.window_background import WindowBackground
from ui.ui_manager import UIManager
from ui.components.tutorial_dialog import TutorialDialog
from ui.components.skip_overlay import SkipOverlay
from core import game_globals, runtime_globals
from models.game_pet import GamePet
from models.game_module import GameModule
from utils.scene_utils import change_scene
from utils.asset_utils import image_load
from utils import navigation_utils
from scenes.tutorial_scenes.tutorial_focus import TutorialFocus
from scenes.tutorial_scenes.tutorial_sprite import TutorialSprite


class SceneTutorial:
    """
    Interactive tutorial scene that guides players through game mechanics.
    
    Uses a step-based system where each step can:
    - Display dialog messages
    - Show/animate sprites
    - Focus on UI elements
    - Embed and control other game scenes
    - Wait for specific player actions
    """
    
    # Tutorial step types
    STEP_DIALOG = "dialog"
    STEP_DIALOG_TOP = "dialog_top"  # Dialog at top of screen
    STEP_SPRITE_SHOW = "sprite_show"
    STEP_SPRITE_HIDE = "sprite_hide"
    STEP_SPRITE_MOVE = "sprite_move"
    STEP_SPRITE_REPLACE = "sprite_replace"
    STEP_FOCUS_ON = "focus_on"
    STEP_FOCUS_OFF = "focus_off"
    STEP_FOCUS_WAIT = "focus_wait"  # Focus and wait for fade-in before continuing
    STEP_SCENE_SWITCH = "scene_switch"
    STEP_BLOCK_INPUT = "block_input"
    STEP_UNBLOCK_INPUT = "unblock_input"
    STEP_WAIT_ACTION = "wait_action"
    STEP_WAIT_FRAMES = "wait_frames"
    STEP_CALLBACK = "callback"
    STEP_PET_CREATE = "pet_create"
    STEP_PET_EVOLVE = "pet_evolve"
    STEP_PLAY_SOUND = "play_sound"
    STEP_SET_CALL_SIGN = "set_call_sign"
    STEP_ADD_COINS = "add_coins"  # Add coins to player

    #: The shop branch's way through SceneConnect: the one button of each of
    #: these views it goes on by (the rest are disabled while it runs).
    CONNECT_PATH_BUTTONS = {"main_menu": "shop_button", "shop": "modules_button"}

    def __init__(self) -> None:
        """Initialize the tutorial scene."""
        self.background = WindowBackground(True)
        
        # UI Manager with GRAY theme for main game
        self.ui_manager = UIManager(theme="GRAY")
        # Disable external border for tutorial - we need to see the scene below
        self.ui_manager.show_external_border = False
        
        # UI components - bottom dialog (default) - wider for more text
        self.dialog = TutorialDialog(x=7, y=190, width=226, height=50)
        self.ui_manager.add_component(self.dialog)
        
        # Top dialog for special messages - wider for more text
        self.dialog_top = TutorialDialog(x=7, y=2, width=226, height=50)
        self.ui_manager.add_component(self.dialog_top)
        
        self.focus = TutorialFocus()
        self.professor_sprite = TutorialSprite()
        self.extra_sprite = TutorialSprite()  # For Agumon, egg, etc.
        
        # UI scaling
        self.ui_scale = runtime_globals.UI_SCALE
        
        # Embedded scene
        self.embedded_scene = None
        self.embedded_scene_name = None
        self.block_scene_input = True
        self.current_scene_name = None  # Track current scene for focus positioning
        
        # Tutorial state
        self.current_step_index = 0
        self.steps = []
        self.waiting_for_action = None  # Action name we're waiting for
        self.wait_frames = 0
        self.tutorial_complete = False
        # When True, the player is locked on the module download: back/cancel
        # is swallowed so they can't leave the shop mid-download.  Cleared when
        # the download finishes.
        self._download_lock = False
        
        # Focus timing - wait for focus fade-in before showing dialog
        self.focus_delay_frames = int(game_globals.configuration.frame_rate * 0.4)  # 0.4 second delay
        self.waiting_for_focus = False  # True when waiting for focus animation
        
        # Expected menu index for action validation
        self.expected_menu_index = None
        
        # Tutorial action callback - called by embedded scenes
        self.pending_action = None
        
        # Tutorial module and pet
        self.tutorial_module = None
        self.tutorial_pet = None
        self.original_pet_list = None  # Store original pets
        self.original_poop_list = None  # and their poop: the tutorial makes and cleans its own

        # Skip confirmation
        self.skip_requested = False

        # Touch-only SKIP pill — gives finger users a visible way out;
        # invisible / inert on keyboard / mouse / GPIO devices. It skips as
        # START does: it used to leave the tutorial's Digimon in the party
        # and the Tutorial module loaded.
        self._skip_overlay = SkipOverlay(on_skip=self.skip_tutorial)

        # Build tutorial steps
        self._build_tutorial_steps()
        
        runtime_globals.game_console.log("[SceneTutorial] Initialized with step-based system")

    def _build_tutorial_steps(self):
        """Build the list of tutorial steps."""
        self.steps = []
        
        # Helper to add focus with delay before next dialog
        def add_focus_and_delay():
            """Add a standard delay after focus operations."""
            return self.focus_delay_frames
        
        # ===== PART 1: Introduction with Professor =====
        
        # Switch to main game scene
        self.steps.append((self.STEP_SCENE_SWITCH, "maingame"))
        self.steps.append((self.STEP_BLOCK_INPUT, None))
        
        # Show professor at center, bottom aligned with pet area
        self.steps.append((self.STEP_CALLBACK, self._show_professor_intro))
        
        # Introduction dialog
        self.steps.append((self.STEP_DIALOG, ["Hello there! Welcome to the world of VPets!",
                                               "My name is Shrub! People call me the VPET PROF!"]))
        
        # Animate professor moving left, swap sprite
        self.steps.append((self.STEP_CALLBACK, self._move_professor_left))
        self.steps.append((self.STEP_WAIT_FRAMES, int(game_globals.configuration.frame_rate * 1.5)))
        self.steps.append((self.STEP_SPRITE_REPLACE, ("professor", "assets/Professor2.png")))
        
        # Show Agumon sprite
        self.steps.append((self.STEP_CALLBACK, self._show_agumon))
        
        # More dialog
        self.steps.append((self.STEP_DIALOG, ["This world is inhabited mostly by creatures called DIGIMON!",
                                               "For some people, DIGIMON are virtual pets. Others are watching anime too much.",
                                               "Myself... I study DIGIMON as a profession.",
                                               "Don't worry I don't need your name, for now."]))
        
        # Hide Agumon
        self.steps.append((self.STEP_SPRITE_HIDE, "extra"))
        
        self.steps.append((self.STEP_DIALOG, ["Let's play a little tutorial to get things started."]))
        
        # Load tutorial module and create egg pet
        self.steps.append((self.STEP_CALLBACK, self._load_tutorial_module))
        self.steps.append((self.STEP_PET_CREATE, None))
        self.steps.append((self.STEP_CALLBACK, self._show_tutorial_pet))
        
        self.steps.append((self.STEP_DIALOG, ["Here's an egg I'm taking care of, isn't it pretty! Ohh, it's moving!"]))
        
        # Force egg to hatch
        self.steps.append((self.STEP_CALLBACK, self._force_egg_hatch))
        self.steps.append((self.STEP_PET_EVOLVE, 1))  # Wait for evolution to stage 1 (Botamon)
        
        # Enable call sign
        self.steps.append((self.STEP_SET_CALL_SIGN, True))
        self.steps.append((self.STEP_PLAY_SOUND, "call"))
        
        # Show at top of screen
        self.steps.append((self.STEP_DIALOG_TOP, ["Botamon has hatched, it's calling our attention!"]))
        
        # Focus on call sign (last menu item, index 9) and wait for focus to complete
        self.steps.append((self.STEP_FOCUS_WAIT, self._focus_call_sign))
        
        self.steps.append((self.STEP_DIALOG_TOP, ["Let's find out what it needs. Enter the Status Menu"]))
        
        # Switch focus to Status icon (first menu item) - no FOCUS_OFF to prevent blink
        self.steps.append((self.STEP_FOCUS_WAIT, self._focus_status_menu))
        
        self.steps.append((self.STEP_CALLBACK, self._enable_status_menu_selection))
        self.steps.append((self.STEP_WAIT_ACTION, "enter_status"))
        
        # ===== PART 2: Status Scene =====
        self.steps.append((self.STEP_SCENE_SWITCH, "status"))
        self.steps.append((self.STEP_BLOCK_INPUT, None))
        
        # Turn off focus from previous scene before showing dialog
        self.steps.append((self.STEP_FOCUS_OFF, None))
        self.steps.append((self.STEP_WAIT_FRAMES, self.focus_delay_frames // 2))
        
        self.steps.append((self.STEP_DIALOG, ["This is the Status Menu!"]))
        
        # Focus on pet list and wait for focus to complete - dialog at BOTTOM
        self.steps.append((self.STEP_FOCUS_WAIT, self._focus_pet_list))
        self.steps.append((self.STEP_DIALOG, ["At the top you can change between pets once you have more than 1"]))
        
        # Switch focus to basic info (Region 2) - dialog at TOP
        self.steps.append((self.STEP_FOCUS_WAIT, self._focus_basic_info))
        self.steps.append((self.STEP_DIALOG_TOP, ["Here you can find basic information like name and age"]))
        
        # Switch focus to care info (left column of Region 3) - dialog at TOP
        self.steps.append((self.STEP_FOCUS_WAIT, self._focus_care_info))
        self.steps.append((self.STEP_DIALOG_TOP, ["In this area we have important care information.",
                                               "Note your pet needs *food* and *vitamin* and has *no* *effort*"]))
        
        # Switch focus to battle info (right column of Region 3) - dialog at TOP
        self.steps.append((self.STEP_FOCUS_WAIT, self._focus_battle_info))
        self.steps.append((self.STEP_DIALOG_TOP, ["Finally, here you can find battle data and DP"]))
        
        # Turn off focus before showing closing dialogs
        self.steps.append((self.STEP_FOCUS_OFF, None))
        self.steps.append((self.STEP_WAIT_FRAMES, self.focus_delay_frames // 2))
        
        self.steps.append((self.STEP_DIALOG, ["We know what Botamon needs, he's hungry!",
                                               "Let's take care of that! Close the Status Menu."]))
        
        # Focus on exit button and wait for focus to complete
        self.steps.append((self.STEP_FOCUS_WAIT, self._focus_exit_button))
        self.steps.append((self.STEP_CALLBACK, self._enable_status_exit))
        self.steps.append((self.STEP_WAIT_ACTION, "exit_status"))
        
        # ===== PART 3: Back to Main Game, Open Inventory =====
        self.steps.append((self.STEP_SCENE_SWITCH, "maingame"))
        self.steps.append((self.STEP_BLOCK_INPUT, None))
        
        # Turn off focus from previous scene
        self.steps.append((self.STEP_FOCUS_OFF, None))
        self.steps.append((self.STEP_WAIT_FRAMES, self.focus_delay_frames // 2))
        
        self.steps.append((self.STEP_DIALOG, ["Now open the Inventory"]))
        
        # Focus on inventory
        self.steps.append((self.STEP_FOCUS_WAIT, self._focus_inventory_menu))
        self.steps.append((self.STEP_CALLBACK, self._enable_inventory_menu_selection))
        self.steps.append((self.STEP_WAIT_ACTION, "enter_inventory"))
        
        # ===== PART 4: Inventory Scene =====
        self.steps.append((self.STEP_SCENE_SWITCH, "inventory"))
        self.steps.append((self.STEP_BLOCK_INPUT, None))
        
        # Turn off focus from previous scene
        self.steps.append((self.STEP_FOCUS_OFF, None))
        self.steps.append((self.STEP_WAIT_FRAMES, self.focus_delay_frames // 2))
        
        self.steps.append((self.STEP_DIALOG, ["This is the Inventory Menu!",
                                               "Here you can find items you've obtained in-game."]))
        
        # Focus on item list - dialog at bottom
        self.steps.append((self.STEP_FOCUS_WAIT, self._focus_item_list))
        self.steps.append((self.STEP_DIALOG, ["This is the item list, showing the items you currently have"]))

        # Focus on description panel - dialog at bottom since it's short
        self.steps.append((self.STEP_FOCUS_WAIT, self._focus_description_panel))
        self.steps.append((self.STEP_DIALOG, ["Here you can find a brief item description"]))
        
        # Turn off focus before instruction
        self.steps.append((self.STEP_FOCUS_OFF, None))
        self.steps.append((self.STEP_WAIT_FRAMES, self.focus_delay_frames // 2))
        
        self.steps.append((self.STEP_DIALOG, ["Let's feed our Botamon some Food",
                                               "Select Food, you can press A to use automatically, or click the Use button"]))
        
        # Focus on first item and use button, then enable item use and unblock input
        self.steps.append((self.STEP_FOCUS_WAIT, self._focus_first_item_and_use))
        self.steps.append((self.STEP_CALLBACK, self._enable_inventory_use_protein))
        self.steps.append((self.STEP_UNBLOCK_INPUT, None))
        self.steps.append((self.STEP_WAIT_ACTION, "use_item"))
        
        # ===== PART 5: Feed Vitamin =====
        self.steps.append((self.STEP_SCENE_SWITCH, "maingame"))
        self.steps.append((self.STEP_BLOCK_INPUT, None))
        
        # Turn off focus from previous scene
        self.steps.append((self.STEP_FOCUS_OFF, None))
        
        self.steps.append((self.STEP_WAIT_FRAMES, game_globals.configuration.frame_rate))  # Wait 1 second
        
        self.steps.append((self.STEP_DIALOG, ["Now let's give him some Vitamin"]))
        
        # Focus on inventory
        self.steps.append((self.STEP_FOCUS_WAIT, self._focus_inventory_menu))
        self.steps.append((self.STEP_CALLBACK, self._enable_inventory_menu_selection))
        self.steps.append((self.STEP_WAIT_ACTION, "enter_inventory"))
        
        # Back to inventory for vitamin
        self.steps.append((self.STEP_SCENE_SWITCH, "inventory"))
        self.steps.append((self.STEP_BLOCK_INPUT, None))
        self.steps.append((self.STEP_FOCUS_OFF, None))
        self.steps.append((self.STEP_WAIT_FRAMES, self.focus_delay_frames // 2))
        
        self.steps.append((self.STEP_DIALOG, ["Now use the Vitamin!"]))
        
        # Select the second item (vitamin) programmatically so USE button uses it
        self.steps.append((self.STEP_CALLBACK, self._select_second_inventory_item))
        
        # Focus on second item (vitamin) and use button - protein is still in the list
        self.steps.append((self.STEP_FOCUS_WAIT, self._focus_second_item_and_use))
        self.steps.append((self.STEP_CALLBACK, self._enable_inventory_use_vitamin))
        self.steps.append((self.STEP_UNBLOCK_INPUT, None))
        self.steps.append((self.STEP_WAIT_ACTION, "use_item"))
        
        # ===== PART 6: Evolution to Koromon =====
        self.steps.append((self.STEP_SCENE_SWITCH, "maingame"))
        self.steps.append((self.STEP_BLOCK_INPUT, None))
        
        # Turn off focus from previous scene
        self.steps.append((self.STEP_FOCUS_OFF, None))
        
        self.steps.append((self.STEP_WAIT_FRAMES, game_globals.configuration.frame_rate))  # Wait 1 second
        
        self.steps.append((self.STEP_SET_CALL_SIGN, False))
        self.steps.append((self.STEP_FOCUS_WAIT, self._focus_call_sign))
        self.steps.append((self.STEP_DIALOG_TOP, ["Look, the Call Sign has disappeared!"]))
        self.steps.append((self.STEP_FOCUS_OFF, None))
        
        # Force evolution to Koromon
        self.steps.append((self.STEP_PLAY_SOUND, "evolution"))
        self.steps.append((self.STEP_CALLBACK, self._force_evolution_to_koromon))
        self.steps.append((self.STEP_PET_EVOLVE, 2))  # Wait for evolution to stage 2 (Koromon)
        
        # ===== PART 6.5: Poop Tutorial =====
        self.steps.append((self.STEP_DIALOG, ["Look, it evolved! But wait, something happened..."]))
        
        # Force the pet to poop
        self.steps.append((self.STEP_CALLBACK, self._force_poop))
        self.steps.append((self.STEP_WAIT_FRAMES, game_globals.configuration.frame_rate))  # Wait 1 second for poop animation
        
        self.steps.append((self.STEP_DIALOG, ["Oh no! Koromon made a mess!",
                                               "Pets poop regularly. If you don't clean it, they can get sick!",
                                               "Let's clean this up!"]))
        
        # Focus on poop cleaning button (last icon in top row)
        self.steps.append((self.STEP_FOCUS_WAIT, self._focus_poop_button))
        self.steps.append((self.STEP_CALLBACK, self._enable_poop_cleaning))
        self.steps.append((self.STEP_UNBLOCK_INPUT, None))
        self.steps.append((self.STEP_WAIT_ACTION, "clean_poop"))
        
        # Wait for cleaning animation to complete
        self.steps.append((self.STEP_BLOCK_INPUT, None))
        self.steps.append((self.STEP_WAIT_ACTION, "cleaning_complete"))
        
        # Turn off focus after cleaning
        self.steps.append((self.STEP_FOCUS_OFF, None))
        
        self.steps.append((self.STEP_DIALOG, ["Good job! Keep an eye on your pet and clean regularly.",
                                               "A happy, healthy pet is a strong pet!"]))
        
        # ===== PART 7: Training =====
        self.steps.append((self.STEP_DIALOG, ["Now it's the perfect time to train! Enter the Training Menu."]))
        
        # Focus on training menu
        self.steps.append((self.STEP_FOCUS_WAIT, self._focus_training_menu))
        self.steps.append((self.STEP_CALLBACK, self._enable_training_menu_selection))
        self.steps.append((self.STEP_WAIT_ACTION, "enter_training"))
        
        # ===== Training Scene =====
        self.steps.append((self.STEP_SCENE_SWITCH, "training"))
        self.steps.append((self.STEP_BLOCK_INPUT, None))
        
        # Turn off focus from previous scene
        self.steps.append((self.STEP_FOCUS_OFF, None))
        self.steps.append((self.STEP_WAIT_FRAMES, self.focus_delay_frames // 2))
        
        self.steps.append((self.STEP_DIALOG, ["Enter the Dummy Charge Training"]))
        
        # Setup training mode BEFORE user clicks - this enables TutorialDummyTraining
        self.steps.append((self.STEP_CALLBACK, self._setup_training_phase))
        
        # Focus on dummy button
        self.steps.append((self.STEP_FOCUS_WAIT, self._focus_dummy_training))
        self.steps.append((self.STEP_CALLBACK, self._enable_training_button_selection))
        self.steps.append((self.STEP_UNBLOCK_INPUT, None))
        self.steps.append((self.STEP_WAIT_ACTION, "enter_dummy_training"))
        
        # Turn off focus after training button is clicked
        self.steps.append((self.STEP_FOCUS_OFF, None))
        self.steps.append((self.STEP_BLOCK_INPUT, None))
        
        # Wait for alert phase to finish and charge phase to start
        self.steps.append((self.STEP_WAIT_ACTION, "training_charge_phase"))
        
        # Show instruction dialog
        self.steps.append((self.STEP_DIALOG, ["To succeed training you need to smash A/Click button to fill the bar!"]))
        
        # Enable input for charging and wait for completion
        self.steps.append((self.STEP_CALLBACK, self._enable_training_charging))
        self.steps.append((self.STEP_UNBLOCK_INPUT, None))
        self.steps.append((self.STEP_WAIT_ACTION, "training_complete"))
        
        # Wait for training animation to finish (attack, impact, result phases)
        self.steps.append((self.STEP_WAIT_ACTION, "training_animation_done"))
        
        # ===== Back to Main Game after Training =====
        self.steps.append((self.STEP_SCENE_SWITCH, "maingame"))
        self.steps.append((self.STEP_BLOCK_INPUT, None))
        self.steps.append((self.STEP_DIALOG, ["Success! Every time a pet succeeds training it gains a little bit of effort.",
                                               "Effort increases the pet's power, but it can also affect its evolutions."]))
        
        # Focus on status menu with delay
        self.steps.append((self.STEP_CALLBACK, self._focus_status_menu))
        self.steps.append((self.STEP_WAIT_FRAMES, self.focus_delay_frames))
        self.steps.append((self.STEP_DIALOG, ["Let's check its status again"]))
        self.steps.append((self.STEP_CALLBACK, self._enable_status_menu_selection))
        self.steps.append((self.STEP_UNBLOCK_INPUT, None))
        self.steps.append((self.STEP_WAIT_ACTION, "enter_status"))
        
        # ===== Status Scene - Check Stats =====
        self.steps.append((self.STEP_SCENE_SWITCH, "status"))
        self.steps.append((self.STEP_BLOCK_INPUT, None))
        
        # Turn off focus from previous scene
        self.steps.append((self.STEP_FOCUS_OFF, None))
        self.steps.append((self.STEP_WAIT_FRAMES, self.focus_delay_frames // 2))
        
        self.steps.append((self.STEP_DIALOG, ["Koromon's status meters are no longer empty!"]))
        
        # Focus on care info to show the stats (same as first status visit)
        self.steps.append((self.STEP_FOCUS_WAIT, self._focus_care_info))
        self.steps.append((self.STEP_DIALOG_TOP, ["Because we trained successfully, it got a boost in Strength!"]))
        
        # Turn off focus before returning to main game
        self.steps.append((self.STEP_FOCUS_OFF, None))
        self.steps.append((self.STEP_WAIT_FRAMES, self.focus_delay_frames // 2))
        
        # Auto-return to main game
        self.steps.append((self.STEP_SCENE_SWITCH, "maingame"))
        
        # ===== PART 8: Evolution to Agumon =====
        self.steps.append((self.STEP_PLAY_SOUND, "evolution"))
        self.steps.append((self.STEP_CALLBACK, self._force_evolution_to_agumon))
        self.steps.append((self.STEP_PET_EVOLVE, 3))  # Wait for evolution to stage 3 (Agumon)
        
        self.steps.append((self.STEP_DIALOG, ["Koromon has evolved into Agumon!",
                                               "Each pet can evolve into multiple forms based on its care.",
                                               "Feeding, training, battling - everything counts!",
                                               "Some forms even require specific times of day!"]))
        
        # ===== PART 9: Battling =====
        self.steps.append((self.STEP_DIALOG, ["Agumon is now strong enough to battle, let's try the Adventure Mode!"]))
        
        # Focus on battle menu
        self.steps.append((self.STEP_FOCUS_WAIT, self._focus_battle_menu))
        self.steps.append((self.STEP_CALLBACK, self._enable_battle_menu_selection))
        self.steps.append((self.STEP_UNBLOCK_INPUT, None))
        self.steps.append((self.STEP_WAIT_ACTION, "enter_battle"))
        
        # ===== Battle Scene =====
        self.steps.append((self.STEP_SCENE_SWITCH, "battle"))
        self.steps.append((self.STEP_BLOCK_INPUT, None))
        
        # Turn off focus from previous scene
        self.steps.append((self.STEP_FOCUS_OFF, None))
        self.steps.append((self.STEP_WAIT_FRAMES, self.focus_delay_frames // 2))
        
        self.steps.append((self.STEP_DIALOG, ["This is the Battle Menu!",
                                               "Here you can battle, jogress and do armor evolutions!",
                                               "Let's enter the tutorial's Adventure Mode."]))
        
        # Focus on adventure mode button
        self.steps.append((self.STEP_FOCUS_WAIT, self._focus_adventure_mode))
        self.steps.append((self.STEP_CALLBACK, self._enable_adventure_selection))
        self.steps.append((self.STEP_UNBLOCK_INPUT, None))
        self.steps.append((self.STEP_WAIT_ACTION, "select_adventure"))
        
        # Turn off focus after selection
        self.steps.append((self.STEP_FOCUS_OFF, None))
        self.steps.append((self.STEP_BLOCK_INPUT, None))
        
        # Focus on Go button
        self.steps.append((self.STEP_FOCUS_WAIT, self._focus_go_button))
        self.steps.append((self.STEP_DIALOG, ["Select GO"]))
        self.steps.append((self.STEP_CALLBACK, self._enable_go_selection))
        self.steps.append((self.STEP_UNBLOCK_INPUT, None))
        self.steps.append((self.STEP_WAIT_ACTION, "select_go"))
        
        # Turn off focus after selection
        self.steps.append((self.STEP_FOCUS_OFF, None))
        self.steps.append((self.STEP_BLOCK_INPUT, None))
        
        # Focus on Fight button
        self.steps.append((self.STEP_FOCUS_WAIT, self._focus_fight_button))
        self.steps.append((self.STEP_DIALOG, ["Select Fight"]))
        self.steps.append((self.STEP_CALLBACK, self._enable_fight_selection))
        self.steps.append((self.STEP_UNBLOCK_INPUT, None))
        self.steps.append((self.STEP_WAIT_ACTION, "select_fight"))
        
        # Turn off focus and let battle play out with input unblocked for charge phase
        self.steps.append((self.STEP_FOCUS_OFF, None))
        # Note: Keep input unblocked so player can participate in charge minigame
        self.steps.append((self.STEP_WAIT_ACTION, "battle_complete"))
        
        # ===== Back to Main Game after Battle =====
        self.steps.append((self.STEP_SCENE_SWITCH, "maingame"))
        self.steps.append((self.STEP_BLOCK_INPUT, None))
        self.steps.append((self.STEP_DIALOG, ["Here comes the winner!",
                                               "Battles can unlock evolutions and earn special items!",
                                               "I think you are ready to begin your own journey!"]))
        
        # ===== PART 10: Module Shop (if needed) =====
        self.steps.append((self.STEP_CALLBACK, self._check_modules_for_shop))

    def _build_shop_tutorial_steps(self):
        """Build shop tutorial steps if player has no modules."""
        self.steps.append((self.STEP_DIALOG, ["It seems you don't have any modules yet.",
                                               "Modules are the core of *Omnipet*.",
                                               "They contain everything needed to play!",
                                               "Let's get your first module from the Shop."]))
        
        # Focus on connect button - focus appears here after the message
        self.steps.append((self.STEP_FOCUS_WAIT, self._focus_connect_menu))
        self.steps.append((self.STEP_DIALOG, ["Enter the Connect Menu."]))
        self.steps.append((self.STEP_CALLBACK, self._enable_connect_menu_selection))
        self.steps.append((self.STEP_UNBLOCK_INPUT, None))
        self.steps.append((self.STEP_WAIT_ACTION, "enter_connect"))
        
        # ===== Connect Scene =====
        self.steps.append((self.STEP_SCENE_SWITCH, "connect"))
        self.steps.append((self.STEP_CALLBACK, self._check_shop_available))
        self.steps.append((self.STEP_BLOCK_INPUT, None))
        
        # Turn off focus from previous scene
        self.steps.append((self.STEP_FOCUS_OFF, None))
        self.steps.append((self.STEP_WAIT_FRAMES, self.focus_delay_frames // 2))
        
        self.steps.append((self.STEP_DIALOG, ["This is the Connect Menu!",
                                               "Here you can battle friends, join arenas, and shop!"]))
        
        self.steps.append((self.STEP_DIALOG, ["Your first module is free!",
                                               "After that, you earn Coins by battling, evolving pets, and finding secrets!"]))
        
        # Focus on shop button
        self.steps.append((self.STEP_FOCUS_WAIT, self._focus_shop_button))
        self.steps.append((self.STEP_CALLBACK, self._enable_shop_selection))
        self.steps.append((self.STEP_UNBLOCK_INPUT, None))
        self.steps.append((self.STEP_WAIT_ACTION, "enter_shop"))
        
        # Turn off focus after selection
        self.steps.append((self.STEP_FOCUS_OFF, None))
        self.steps.append((self.STEP_BLOCK_INPUT, None))
        
        # Focus on modules button
        self.steps.append((self.STEP_FOCUS_WAIT, self._focus_modules_button))
        self.steps.append((self.STEP_CALLBACK, self._enable_modules_selection))
        self.steps.append((self.STEP_UNBLOCK_INPUT, None))
        self.steps.append((self.STEP_WAIT_ACTION, "view_modules"))
        
        # Turn off focus after selection
        self.steps.append((self.STEP_FOCUS_OFF, None))
        
        self.steps.append((self.STEP_DIALOG, ["Choose your first module, pick wisely!"]))
        
        # Wait for purchase
        self.steps.append((self.STEP_UNBLOCK_INPUT, None))
        self.steps.append((self.STEP_WAIT_ACTION, "purchase_module"))
        
        # Focus on download button and lock the player in: they bought the
        # module, now they must download it.  Back/cancel is swallowed so they
        # can't leave the shop until the download finishes (cleared when the
        # download_module action fires).
        self.steps.append((self.STEP_FOCUS_WAIT, self._focus_download_button))
        self.steps.append((self.STEP_CALLBACK, self._enable_download_selection))
        self.steps.append((self.STEP_CALLBACK, self._lock_input_for_download))
        self.steps.append((self.STEP_UNBLOCK_INPUT, None))
        self.steps.append((self.STEP_WAIT_ACTION, "download_module"))
        
        # Turn off focus after download
        self.steps.append((self.STEP_FOCUS_OFF, None))
        
        self.steps.append((self.STEP_BLOCK_INPUT, None))
        self._build_tutorial_ending_steps()

    def _build_tutorial_ending_steps(self):
        """Build the ending steps for the tutorial."""
        self.steps.append((self.STEP_DIALOG, ["You did it! You have your first module installed!",
                                               "You are ready to start your own journey!"]))
        self._build_common_ending_steps()

    def _build_common_ending_steps(self):
        """Build common ending steps."""
        self.steps.append((self.STEP_DIALOG, ["Replay this tutorial anytime from the Settings Menu.",
                                               "Check the documentation in the game's folder for guides.",
                                               "Keep caring, exploring, and evolving!",
                                               "Take care and see you in the arena!"]))
        
        self.steps.append((self.STEP_CALLBACK, self._complete_tutorial))

    # =========================================================================
    # CALLBACK FUNCTIONS
    # =========================================================================
    
    def _show_professor_intro(self):
        """Show professor sprite at center bottom."""
        # Professor appears at center, bottom aligned with pet area (around y=160 in base)
        self.professor_sprite.show_at_bottom_aligned(
            "assets/Professor1.png",
            center_x=120,
            bottom_y=180,
            scale=1.0
        )
    
    def _move_professor_left(self):
        """Move professor to the left side."""
        # Move to x=60 (left third of screen)
        sprite_rect = self.professor_sprite.get_rect()
        target_x = 20
        target_y = sprite_rect.y
        self.professor_sprite.move_to(target_x, target_y, speed=2.0)
    
    def _show_agumon(self):
        """Show Agumon sprite to the right of professor."""
        # Agumon appears to the right of professor, bottom aligned
        # Get professor's bottom Y position
        prof_rect = self.professor_sprite.get_rect()
        prof_bottom_y = prof_rect.y + prof_rect.height
        
        # Load Agumon temporarily to get its height
        from utils.asset_utils import image_load
        agumon_img = image_load("assets/Agumon.png")
        if agumon_img:
            agumon_height = agumon_img.get_height()
            agumon_y = prof_bottom_y - agumon_height
        else:
            agumon_y = 120
        
        self.extra_sprite.show(
            "assets/Agumon.png",
            x=140,
            y=agumon_y,
            scale=1.0,
            anchor="topleft"
        )
    
    def _load_tutorial_module(self):
        """Load the tutorial module from assets/Tutorial."""
        try:
            module_folder = "assets/Tutorial"
            if os.path.exists(os.path.join(module_folder, "module.json")):
                self.tutorial_module = GameModule(module_folder)
                # Register the module in the global registry
                runtime_globals.game_modules[self.tutorial_module.name] = self.tutorial_module
                runtime_globals.game_console.log("[SceneTutorial] Tutorial module loaded and registered")
            else:
                runtime_globals.game_console.log("[SceneTutorial] Warning: Tutorial module not found")
        except Exception as e:
            runtime_globals.game_console.log(f"[SceneTutorial] Error loading tutorial module: {e}")
    
    def _create_tutorial_pet(self):
        """Create a tutorial pet from stage 0 (egg)."""
        if self.tutorial_module:
            # Store original pet list
            self.original_pet_list = list(game_globals.pet_list) if game_globals.pet_list else []
            self.original_poop_list = list(game_globals.poop_list or [])

            # Get stage 0 pets (eggs) - returns a list
            eggs = self.tutorial_module.get_monsters_by_stage(0)
            if eggs:
                egg_data = eggs[0]  # Get the first egg
                # GamePet expects a dictionary with all pet data
                self.tutorial_pet = GamePet(egg_data)
                # Set up pet in game globals
                game_globals.pet_list = [self.tutorial_pet]
                runtime_globals.game_console.log(f"[SceneTutorial] Tutorial pet created: {self.tutorial_pet.name}")
            else:
                runtime_globals.game_console.log("[SceneTutorial] No egg found in Tutorial module")
    
    def _show_tutorial_pet(self):
        """Show the tutorial pet in place of extra sprite."""
        # Hide professor and agumon sprites so pet is visible
        self.professor_sprite.hide()
        self.extra_sprite.hide()
        
        # Create the pet if not already
        if not self.tutorial_pet:
            self._create_tutorial_pet()
    
    def _force_egg_hatch(self):
        """Force the egg to hatch immediately."""
        if self.tutorial_pet and self.tutorial_pet.stage == 0:
            # Get the first evolution target (Botamon)
            if self.tutorial_pet.evolve and len(self.tutorial_pet.evolve) > 0:
                target = self.tutorial_pet.evolve[0]
                target_name = target.get("to")
                target_version = target.get("version", 1)
                runtime_globals.game_console.log(f"[SceneTutorial] Forcing egg to evolve to {target_name}")
                # Directly evolve to Botamon (no coin reward — scripted tutorial)
                self.tutorial_pet.evolve_to(target_name, target_version, reward=False)
    
    def _force_evolution_to_koromon(self):
        """Force Botamon to evolve to Koromon."""
        if self.tutorial_pet and self.tutorial_pet.stage == 1:
            # Get the first evolution target (Koromon)
            if self.tutorial_pet.evolve and len(self.tutorial_pet.evolve) > 0:
                target = self.tutorial_pet.evolve[0]
                target_name = target.get("to")
                target_version = target.get("version", 1)
                runtime_globals.game_console.log(f"[SceneTutorial] Forcing Botamon to evolve to {target_name}")
                # Directly evolve to Koromon (no coin reward — scripted tutorial)
                self.tutorial_pet.evolve_to(target_name, target_version, reward=False)
    
    def _force_evolution_to_agumon(self):
        """Force Koromon to evolve to Agumon."""
        if self.tutorial_pet and self.tutorial_pet.stage == 2:
            # Get the first evolution target (Agumon)
            if self.tutorial_pet.evolve and len(self.tutorial_pet.evolve) > 0:
                target = self.tutorial_pet.evolve[0]
                target_name = target.get("to")
                target_version = target.get("version", 1)
                runtime_globals.game_console.log(f"[SceneTutorial] Forcing Koromon to evolve to {target_name}")
                # Directly evolve to Agumon (no coin reward — scripted tutorial)
                self.tutorial_pet.evolve_to(target_name, target_version, reward=False)
    
    def _force_poop(self):
        """Force the tutorial pet to poop."""
        if self.tutorial_pet:
            runtime_globals.game_console.log("[SceneTutorial] Forcing pet to poop")
            self.tutorial_pet.force_poop()
    
    def _get_menu_top_y(self):
        """Get the Y position of the top menu row in base 240 coordinates."""
        # If clock is shown, menu is lower
        return 20 if game_globals.showClock else 5
    
    def _get_menu_bottom_y(self):
        """Get the Y position of the bottom menu row in base 240 coordinates."""
        # Bottom row: 240 - 48 (icon height) - 10 (margin) = 182
        return 182
    
    def _focus_menu_icon(self, index):
        """Focus main-menu icon *index* where the main game draws it.

        WindowMenu spreads its five icons over the screen's whole width
        (calculate_spacing); fixed 48-px slots of the 240 square agree with
        them only on a square screen. The icon's screen rect is turned back
        into the overlay's base coordinates (global mode: the 240 square
        centred on the screen)."""
        rects = getattr(getattr(self.embedded_scene, "menu", None), "icon_rects", None) or []
        if index < len(rects):
            rect = rects[index]
            scale = runtime_globals.UI_SCALE
            offset_x = (runtime_globals.SCREEN_WIDTH - int(240 * scale)) // 2
            offset_y = (runtime_globals.SCREEN_HEIGHT - int(240 * scale)) // 2
            self.focus.focus_on((rect.x - offset_x) / scale, (rect.y - offset_y) / scale,
                                rect.w / scale, rect.h / scale)
        else:
            y = self._get_menu_top_y() if index < 5 else self._get_menu_bottom_y()
            self.focus.focus_on((index % 5) * 48, y, 48, 48)

    def _focus_call_sign(self):
        """Focus on the call sign icon (menu item 9, bottom row far right)."""
        self._focus_menu_icon(9)

    def _focus_status_menu(self):
        """Focus on the Status menu icon (menu item 0, top row first)."""
        self._focus_menu_icon(0)
        self.expected_menu_index = 0

    def _focus_inventory_menu(self):
        """Focus on the Inventory/Feeding menu icon (menu item 1, top row second)."""
        self._focus_menu_icon(1)
        self.expected_menu_index = 1

    def _focus_training_menu(self):
        """Focus on the Training menu icon (menu item 2, top row third)."""
        self._focus_menu_icon(2)
        self.expected_menu_index = 2

    def _focus_poop_button(self):
        """Focus on the Poop cleaning button (menu item 4, top row last)."""
        self._focus_menu_icon(4)
        self.expected_menu_index = 4
    
    def _focus_pet_list(self):
        """Focus on the pet list component in Status scene."""
        # Pet list spans full width, height=44, starts at y=7
        self.focus.focus_on(0, 7, 240, 44)
    
    def _focus_basic_info(self):
        """Focus on basic info area (Region 2) in Status scene."""
        # Region 2: from pet_list_height+10 (54) to region1_end+71 (125)
        # This covers name, stage, age labels
        # Full width of content area
        self.focus.focus_on(0, 54, 240, 71)
    
    def _focus_care_info(self):
        """Focus on care info area (left column of Region 3) in Status scene."""
        # Region 3: 125 to 197
        # Left half of region 3 (margin=12, column_width~=103)
        self.focus.focus_on(12, 125, 103, 72)
    
    def _focus_battle_info(self):
        """Focus on battle info area (right column of Region 3) in Status scene."""
        # Region 3: 125 to 197
        # Right half of region 3 (x = margin + column_width + gap = 12 + 103 + 10 = 125)
        self.focus.focus_on(125, 125, 103, 72)
    
    def _focus_exit_button(self):
        """Focus on the EXIT button in Status scene's pet list."""
        # Pet list is at y=7, height=44
        # EXIT button: x = 240 - margin(24) - width(40) - 2 = 174, y=7
        # Height should match the button, not full pet list
        self.focus.focus_on(174, 7, 42, 44)
    
    def _focus_item_list(self):
        """Focus on the item list in Inventory scene."""
        # Item list at x=0, y=27, width=156, height=176
        self.focus.focus_on(0, 27, 156, 176)
    
    def _focus_description_panel(self):
        """Focus on the description panel in Inventory scene."""
        # Text panel at x=158, y=24, width=78, height=106
        self.focus.focus_on(158, 24, 78, 106)
    
    def _focus_first_item_and_use(self):
        """Focus on first item and USE button in Inventory scene."""
        # Item list at x=0, y=27, width=156, height=176
        # items_rect.y = arrow_size(12) + 2*margin(4) = 16 relative to list
        # First item global y = 27 + 16 = 43, height=31
        # USE button at x=158, y=134, width=80, height=23
        self.focus.focus_on_multiple([
            (0, 43, 156, 31),    # First item slot
            (158, 134, 80, 23)   # USE button
        ])
    
    def _focus_second_item_and_use(self):
        """Focus on second item and USE button in Inventory scene."""
        # Item list at x=0, y=27, width=156, height=176
        # items_rect.y = 16 relative to list, first item at y=43
        # Second item at y=43 + 31 (item) + 7 (spacing) = 81, height=31
        # USE button at x=158, y=134, width=80, height=23
        self.focus.focus_on_multiple([
            (0, 81, 156, 31),    # Second item slot
            (158, 134, 80, 23)   # USE button
        ])
    
    def _focus_dummy_training(self):
        """Focus on the dummy training button in Training scene."""
        # Buttons at start_x=36, start_y=25, size=54x54
        # Dummy is always the first button
        self.focus.focus_on(36, 25, 54, 54)
    
    def _focus_battle_menu(self):
        """Focus on the Battle menu icon (menu item 3, top row fourth)."""
        self._focus_menu_icon(3)
        self.expected_menu_index = 3
    
    def _focus_adventure_mode(self):
        """Focus on the Adventure Mode button in battle scene."""
        # Adventure button: x=21, y=120, width=199, height=34 (from adventure_view.py)
        # Use smaller height (24) to prevent clicking exit button below at y=157
        # Note: positioning mode is already set in _switch_to_scene
        self.focus.focus_on(21, 120, 199, 24)
    
    def _focus_go_button(self):
        """Focus on the GO button in battle scene."""
        # GO button position from adventure_module_selection_view.py: (179, 43, 52, 55)
        # Note: positioning mode is already set in _switch_to_scene
        runtime_globals.game_console.log(f"[SceneTutorial] _focus_go_button called, current focus state={self.focus.state}")
        self.focus.focus_on(179, 43, 52, 55)
        runtime_globals.game_console.log(f"[SceneTutorial] After focus_on, focus state={self.focus.state}")
    
    def _focus_fight_button(self):
        """Focus on the Fight button in battle scene."""
        # Fight button in adventure_area_selection_view.py: x=9, y=198, width=145, height=25
        # Note: positioning mode is already set in _switch_to_scene
        self.focus.focus_on(9, 198, 145, 25)
    
    def _focus_connect_menu(self):
        """Focus on the Connect menu icon (menu item 8, bottom row fourth)."""
        self._focus_menu_icon(8)
        self.expected_menu_index = 8
    
    def _focus_shop_button(self):
        """Focus on the Shop button in connect scene main menu."""
        # Main menu: Shop button at left side, bottom row
        # Position: left_button_x=17, bottom_row_y=145, size 95x74
        self.focus.focus_on(17, 145, 95, 74)
    
    def _focus_modules_button(self):
        """Focus on the Modules button in shop."""
        # Shop view: Modules button at col1_x=17, row1_y=35, size 90x62
        self.focus.focus_on(17, 35, 90, 62)
    
    def _focus_download_button(self):
        """Focus on the Download button in module detail."""
        # Module detail view: Download/Buy button at right side, bottom
        # Position: x=150, y=202, size 80x28
        self.focus.focus_on(150, 202, 80, 28)
    
    def _setup_training_phase(self):
        """Setup training phase callbacks."""
        if self.embedded_scene:
            if hasattr(self.embedded_scene, 'set_on_charge_phase_started'):
                self.embedded_scene.set_on_charge_phase_started(self._on_charge_phase_started)
            if hasattr(self.embedded_scene, 'set_tutorial_training_mode'):
                self.embedded_scene.set_tutorial_training_mode(True, target_strength=14)
            if hasattr(self.embedded_scene, 'set_tutorial_controlled'):
                self.embedded_scene.set_tutorial_controlled(True)
            if hasattr(self.embedded_scene, 'set_on_training_animation_complete'):
                self.embedded_scene.set_on_training_animation_complete(self._on_training_animation_complete)
        runtime_globals.game_console.log("[SceneTutorial] Training phase setup complete")
    
    def _on_charge_phase_started(self):
        """Called when the charge phase starts."""
        runtime_globals.game_console.log("[SceneTutorial] Charge phase started")
        self.notify_action("training_charge_phase")
    
    def _enable_training_charging(self):
        """Enable charging during training and set completion callback."""
        if self.embedded_scene and hasattr(self.embedded_scene, 'set_on_training_complete'):
            self.embedded_scene.set_on_training_complete(self._on_training_complete)
        runtime_globals.game_console.log("[SceneTutorial] Training charging enabled")
    
    def _on_training_complete(self):
        """Called when training target strength is reached."""
        runtime_globals.game_console.log("[SceneTutorial] Training complete!")
        self.notify_action("training_complete")
    
    def _on_training_animation_complete(self):
        """Called when training animation is done (result phase ended)."""
        runtime_globals.game_console.log("[SceneTutorial] Training animation complete!")
        self.notify_action("training_animation_done")
    
    def _start_training_phase(self):
        """Start the training phase in embedded scene (legacy callback)."""
        # This would need integration with the training scene
        runtime_globals.game_console.log("[SceneTutorial] Starting training phase")
    
    # =========================================================================
    # EMBEDDED SCENE CONTROL CALLBACKS
    # =========================================================================
    
    def _enable_status_exit(self):
        """Enable exiting the status scene."""
        if self.embedded_scene and hasattr(self.embedded_scene, 'set_allow_exit'):
            self.embedded_scene.set_allow_exit(True, callback=self._on_status_exited)
    
    def _on_status_exited(self):
        """Called when status scene is exited."""
        self.notify_action("exit_status")
    
    def _enable_inventory_menu_selection(self):
        """Enable selecting the inventory menu from main game."""
        if self.embedded_scene and hasattr(self.embedded_scene, 'set_allow_menu_selection'):
            self.embedded_scene.set_allow_menu_selection(True, allowed_index=1, callback=self._on_inventory_menu_selected)
    
    def _on_inventory_menu_selected(self, index):
        """Called when inventory menu is selected."""
        self.notify_action("enter_inventory")
    
    def _select_second_inventory_item(self):
        """Select the second item (vitamin) in the inventory list."""
        if self.embedded_scene and hasattr(self.embedded_scene, 'item_list') and self.embedded_scene.item_list:
            self.embedded_scene.item_list.selected_index = 1
            runtime_globals.game_console.log("[SceneTutorial] Selected second inventory item (vitamin)")
    
    def _enable_inventory_use_protein(self):
        """Enable using the first item (protein) in inventory scene."""
        if self.embedded_scene and hasattr(self.embedded_scene, 'set_allow_use_item'):
            self.embedded_scene.set_allow_use_item(True, callback=self._on_item_used, required_index=0)
    
    def _enable_inventory_use_vitamin(self):
        """Enable using the second item (vitamin) in inventory scene."""
        if self.embedded_scene and hasattr(self.embedded_scene, 'set_allow_use_item'):
            self.embedded_scene.set_allow_use_item(True, callback=self._on_item_used, required_index=1)
    
    def _enable_inventory_use_item(self):
        """Enable using any item in inventory scene (legacy, no index restriction)."""
        if self.embedded_scene and hasattr(self.embedded_scene, 'set_allow_use_item'):
            self.embedded_scene.set_allow_use_item(True, callback=self._on_item_used, required_index=None)
    
    def _on_item_used(self):
        """Called when an item is used."""
        self.notify_action("use_item")
    
    def _enable_training_menu_selection(self):
        """Enable selecting the training menu from main game."""
        if self.embedded_scene and hasattr(self.embedded_scene, 'set_allow_menu_selection'):
            self.embedded_scene.set_allow_menu_selection(True, allowed_index=2, callback=self._on_training_menu_selected)
    
    def _on_training_menu_selected(self, index):
        """Called when training menu is selected."""
        self.notify_action("enter_training")
    
    def _enable_poop_cleaning(self):
        """Enable cleaning poop from main game."""
        if self.embedded_scene and hasattr(self.embedded_scene, 'set_allow_menu_selection'):
            self.embedded_scene.set_allow_menu_selection(True, allowed_index=4, callback=self._on_poop_cleaned)
        # Also set up callback for when cleaning animation completes
        if self.embedded_scene and hasattr(self.embedded_scene, 'set_on_cleaning_complete'):
            self.embedded_scene.set_on_cleaning_complete(self._on_cleaning_complete)
    
    def _on_poop_cleaned(self, index):
        """Called when poop cleaning menu is selected (animation starts)."""
        self.notify_action("clean_poop")
    
    def _on_cleaning_complete(self):
        """Called when poop cleaning animation completes."""
        self.notify_action("cleaning_complete")
    
    def _enable_training_button_selection(self):
        """Enable selecting training buttons in training scene."""
        if self.embedded_scene and hasattr(self.embedded_scene, 'set_allow_button_selection'):
            self.embedded_scene.set_allow_button_selection(True, callback=self._on_training_selected)
    
    def _on_training_selected(self):
        """Called when a training is selected."""
        self.notify_action("enter_dummy_training")
    
    def _enable_status_menu_selection(self):
        """Enable selecting the status menu from main game."""
        if self.embedded_scene and hasattr(self.embedded_scene, 'set_allow_menu_selection'):
            self.embedded_scene.set_allow_menu_selection(True, allowed_index=0, callback=self._on_status_menu_selected)
    
    def _on_status_menu_selected(self, index):
        """Called when status menu is selected."""
        self.notify_action("enter_status")
    
    def _enable_battle_menu_selection(self):
        """Enable selecting the battle menu from main game."""
        if self.embedded_scene and hasattr(self.embedded_scene, 'set_allow_menu_selection'):
            self.embedded_scene.set_allow_menu_selection(True, allowed_index=3, callback=self._on_battle_menu_selected)
    
    def _on_battle_menu_selected(self, index):
        """Called when battle menu is selected."""
        self.notify_action("enter_battle")
    
    def _enable_adventure_selection(self):
        """Enable selecting adventure mode in battle scene."""
        runtime_globals.game_console.log("[SceneTutorial] Enabling adventure selection")
        if self.embedded_scene and hasattr(self.embedded_scene, 'set_allow_adventure_selection'):
            self.embedded_scene.set_allow_adventure_selection(True, callback=self._on_adventure_selected)
        else:
            runtime_globals.game_console.log("[SceneTutorial] WARNING: Could not enable adventure selection - embedded_scene missing or no method")
    
    def _on_adventure_selected(self):
        """Called when adventure mode is selected."""
        runtime_globals.game_console.log("[SceneTutorial] Adventure selected, notifying action")
        self.notify_action("select_adventure")
    
    def _enable_go_selection(self):
        """Enable selecting GO button in battle scene."""
        runtime_globals.game_console.log("[SceneTutorial] Enabling GO selection")
        if self.embedded_scene and hasattr(self.embedded_scene, 'set_allow_go_selection'):
            self.embedded_scene.set_allow_go_selection(True, callback=self._on_go_selected)
        else:
            runtime_globals.game_console.log("[SceneTutorial] WARNING: Could not enable GO selection - embedded_scene missing or no method")
    
    def _on_go_selected(self):
        """Called when GO is selected."""
        self.notify_action("select_go")
    
    def _enable_fight_selection(self):
        """Enable selecting Fight button in battle scene."""
        if self.embedded_scene and hasattr(self.embedded_scene, 'set_allow_fight_selection'):
            self.embedded_scene.set_allow_fight_selection(True, callback=self._on_fight_selected)
    
    def _on_fight_selected(self):
        """Called when Fight is selected."""
        self.notify_action("select_fight")
        # Setup battle complete callback after fight starts
        if self.embedded_scene and hasattr(self.embedded_scene, 'set_on_battle_complete'):
            self.embedded_scene.set_on_battle_complete(self._on_battle_complete)
    
    def _on_battle_complete(self):
        """Called when the battle is complete."""
        self.notify_action("battle_complete")
    
    def _enable_connect_menu_selection(self):
        """Enable selecting the connect menu from main game."""
        # Connect is menu index 8 (bottom row, 4th icon) — see
        # SceneMainGame: `elif index == 8: self.start_connect()`.
        if self.embedded_scene and hasattr(self.embedded_scene, 'set_allow_menu_selection'):
            self.embedded_scene.set_allow_menu_selection(True, allowed_index=8, callback=self._on_connect_menu_selected)
    
    def _on_connect_menu_selected(self, index):
        """Called when connect menu is selected."""
        self.notify_action("enter_connect")
    
    def _enable_shop_selection(self):
        """Enable selecting shop button in connect scene."""
        if self.embedded_scene and hasattr(self.embedded_scene, 'set_allow_shop_selection'):
            self.embedded_scene.set_allow_shop_selection(True, callback=self._on_shop_selected)
    
    def _on_shop_selected(self):
        """Called when shop is selected."""
        self.notify_action("enter_shop")
    
    def _enable_modules_selection(self):
        """Enable selecting modules button in shop."""
        if self.embedded_scene and hasattr(self.embedded_scene, 'set_allow_modules_selection'):
            self.embedded_scene.set_allow_modules_selection(True, callback=self._on_modules_selected)
    
    def _on_modules_selected(self):
        """Called when modules tab is selected."""
        self.notify_action("view_modules")
    
    def _enable_download_selection(self):
        """Enable selecting download button for a module."""
        if self.embedded_scene and hasattr(self.embedded_scene, 'set_allow_download_selection'):
            self.embedded_scene.set_allow_download_selection(True, callback=self._on_download_selected)

    def _lock_input_for_download(self):
        """Lock the player on the shop until the module download completes."""
        self._download_lock = True
    
    def _on_download_selected(self):
        """Called when download is selected."""
        self.notify_action("download_module")
    
    def _check_modules_for_shop(self):
        """Check if player has modules and build appropriate tutorial steps."""
        has_modules = len(runtime_globals.game_modules) > 1  # More than just Tutorial module
        
        if has_modules:
            # Player has modules, skip shop tutorial
            self._build_common_ending_steps()
            self._advance_step()
        else:
            # No modules, add shop tutorial steps
            self._build_shop_tutorial_steps()
            self._advance_step()
    
    def _check_shop_available(self):
        """No-op placeholder.

        Previously bounced the player to SceneError when no internet was
        detected.  The shop view itself surfaces an offline message, so
        the tutorial now always continues into the shop instead of
        derailing into an error scene when modules aren't installed.
        """
        return
    
    def _complete_tutorial(self):
        """Mark tutorial as complete and transition to next scene."""
        self.tutorial_complete = True
    
    def _complete_part1(self):
        """Complete Part 1 of the tutorial (legacy callback)."""
        runtime_globals.game_console.log("[SceneTutorial] Part 1 complete")
        # Continue to Part 2 or end
        self.tutorial_complete = True

    # =========================================================================
    # EMBEDDED SCENE MANAGEMENT
    # =========================================================================
    
    def _switch_to_scene(self, scene_name: str):
        """Switch to an embedded scene using tutorial subclasses."""
        # Use tutorial-controlled subclasses for scenes we need to control
        from scenes.tutorial_scenes.tutorial_maingame import TutorialMainGame
        from scenes.tutorial_scenes.tutorial_status import TutorialStatus
        from scenes.tutorial_scenes.tutorial_inventory import TutorialInventory
        from scenes.tutorial_scenes.tutorial_training import TutorialTraining
        from scenes.tutorial_scenes.tutorial_battle import TutorialBattle
        from scenes.scene_connect import SceneConnect
        
        scene_classes = {
            "maingame": TutorialMainGame,
            "status": TutorialStatus,
            "inventory": TutorialInventory,
            "training": TutorialTraining,
            "battle": TutorialBattle,
            "connect": SceneConnect
        }
        
        # Theme mapping for each scene
        scene_themes = {
            "maingame": "GRAY",
            "status": "PURPLE",
            "inventory": "BLUE",
            "training": "GREEN",
            "battle": "RED",
            "connect": "RED_DARK_VARIANT"
        }
        
        scene_class = scene_classes.get(scene_name)
        if scene_class:
            self.embedded_scene = scene_class()
            self.embedded_scene_name = scene_name
            self.current_scene_name = scene_name
            
            # Update UI manager theme to match scene
            theme = scene_themes.get(scene_name, "GRAY")
            self.ui_manager.set_theme(theme)
            
            # Update focus positioning mode based on scene
            if scene_name == "maingame":
                # MainGame uses full screen positioning
                self.focus.set_positioning_mode("global")
            else:
                # Other scenes use UIManager positioning
                self.focus.set_positioning_mode("ui_manager", self.embedded_scene.ui_manager if hasattr(self.embedded_scene, 'ui_manager') else None)
            
            runtime_globals.game_console.log(f"[SceneTutorial] Switched to embedded {scene_name} with theme {theme}")
        else:
            runtime_globals.game_console.log(f"[SceneTutorial] Unknown scene: {scene_name}")

    # =========================================================================
    # STEP EXECUTION
    # =========================================================================
    
    def _execute_current_step(self):
        """Execute the current tutorial step."""
        if self.current_step_index >= len(self.steps):
            return
            
        step_type, step_data = self.steps[self.current_step_index]
        runtime_globals.game_console.log(f"[SceneTutorial] Executing step {self.current_step_index}: {step_type}")
        
        if step_type == self.STEP_DIALOG:
            messages = step_data if isinstance(step_data, list) else [step_data]
            self.dialog.show_messages(messages, on_complete=self._advance_step)
            
        elif step_type == self.STEP_DIALOG_TOP:
            # Dialog at top of screen
            messages = step_data if isinstance(step_data, list) else [step_data]
            self.dialog_top.show_messages(messages, on_complete=self._advance_step)
            
        elif step_type == self.STEP_SPRITE_SHOW:
            sprite_name, path, x, y, scale = step_data
            sprite = self.professor_sprite if sprite_name == "professor" else self.extra_sprite
            sprite.show(path, x, y, scale)
            self._advance_step()
            
        elif step_type == self.STEP_SPRITE_HIDE:
            sprite_name = step_data
            sprite = self.professor_sprite if sprite_name == "professor" else self.extra_sprite
            sprite.hide()
            self._advance_step()
            
        elif step_type == self.STEP_SPRITE_REPLACE:
            sprite_name, path = step_data
            sprite = self.professor_sprite if sprite_name == "professor" else self.extra_sprite
            sprite.replace(path)
            self._advance_step()
            
        elif step_type == self.STEP_SPRITE_MOVE:
            sprite_name, x, y, speed = step_data
            sprite = self.professor_sprite if sprite_name == "professor" else self.extra_sprite
            sprite.move_to(x, y, speed, on_complete=self._advance_step)
            
        elif step_type == self.STEP_FOCUS_ON:
            x, y, w, h = step_data
            self.focus.focus_on(x, y, w, h)
            self._advance_step()
            
        elif step_type == self.STEP_FOCUS_OFF:
            self.focus.focus_off()
            # Wait a short moment for fade-out
            self.wait_frames = self.focus_delay_frames // 2
            
        elif step_type == self.STEP_FOCUS_WAIT:
            # Focus with waiting for animation to complete
            callback, = step_data if isinstance(step_data, tuple) else (step_data,)
            callback()  # Call focus function
            self.waiting_for_focus = True
            # Will advance when focus fade-in completes
            
        elif step_type == self.STEP_SCENE_SWITCH:
            self._switch_to_scene(step_data)
            self._advance_step()
            
        elif step_type == self.STEP_BLOCK_INPUT:
            self.block_scene_input = True
            self._advance_step()
            
        elif step_type == self.STEP_UNBLOCK_INPUT:
            self.block_scene_input = False
            self._advance_step()
            
        elif step_type == self.STEP_WAIT_ACTION:
            self.waiting_for_action = step_data
            # Don't advance until action is performed
            
        elif step_type == self.STEP_WAIT_FRAMES:
            self.wait_frames = step_data
            # Will advance when frames counted down
            
        elif step_type == self.STEP_CALLBACK:
            callback = step_data
            callback()
            self._advance_step()
            
        elif step_type == self.STEP_PET_CREATE:
            self._create_tutorial_pet()
            self._advance_step()
            
        elif step_type == self.STEP_PET_EVOLVE:
            # Wait for pet to evolve
            # Check in update loop
            pass
            
        elif step_type == self.STEP_PLAY_SOUND:
            sound_name = step_data
            if hasattr(runtime_globals, 'game_sound') and runtime_globals.game_sound:
                runtime_globals.game_sound.play(sound_name)
            self._advance_step()
            
        elif step_type == self.STEP_SET_CALL_SIGN:
            runtime_globals.pet_alert = step_data
            self._advance_step()
            
        elif step_type == self.STEP_ADD_COINS:
            # Add coins to player (Progress Mode only)
            if hasattr(game_globals, 'coins') and game_globals.is_progress_mode():
                game_globals.coins += step_data
                runtime_globals.game_console.log(f"[SceneTutorial] Added {step_data} coins")
            elif game_globals.is_free_mode():
                runtime_globals.game_console.log(f"[SceneTutorial] Skipping coin reward in Free Mode")
            self._advance_step()
    
    def _advance_step(self):
        """Advance to the next step."""
        runtime_globals.game_console.log(f"[SceneTutorial] Advancing from step {self.current_step_index} to {self.current_step_index + 1}")
        self.current_step_index += 1
        if self.current_step_index < len(self.steps):
            self._execute_current_step()
        else:
            runtime_globals.game_console.log("[SceneTutorial] Tutorial complete - no more steps")
            self.tutorial_complete = True

    # =========================================================================
    # UPDATE / DRAW / EVENTS
    # =========================================================================

    def update(self) -> None:
        """Update the tutorial scene."""
        # Update embedded scene
        if self.embedded_scene:
            self.embedded_scene.update()
        
        # Update tutorial components
        self.ui_manager.update()
        self.focus.update()
        self.professor_sprite.update()
        self.extra_sprite.update()
        
        # Detect connect/shop progress (embedded SceneConnect has no tutorial
        # notification hooks, so we poll its state instead).
        self._update_connect_phase_progress()

        # Handle waiting states
        if self.wait_frames > 0:
            self.wait_frames -= 1
            if self.wait_frames <= 0:
                self._advance_step()
        
        # Handle focus waiting (wait for focus to fade in)
        if self.waiting_for_focus:
            # Debug: log focus state occasionally to avoid spam
            if hasattr(self, '_focus_log_counter'):
                self._focus_log_counter += 1
            else:
                self._focus_log_counter = 0
            if self._focus_log_counter % 30 == 0:  # Log every ~1 second at 30fps
                runtime_globals.game_console.log(f"[SceneTutorial] Waiting for focus: state={self.focus.state}, is_fully_visible={self.focus.is_fully_visible()}, ui_manager_ref={self.focus.ui_manager_ref is not None}")
            
            if self.focus.is_fully_visible():
                self.waiting_for_focus = False
                self._focus_log_counter = 0
                self._advance_step()
        
        # Check for pet evolution completion
        if self.current_step_index < len(self.steps):
            step_type, step_data = self.steps[self.current_step_index]
            if step_type == self.STEP_PET_EVOLVE:
                # Wait for pet to actually evolve to the next stage
                # step_data contains the expected stage number
                if self.tutorial_pet and self.tutorial_pet.stage == step_data:
                    self._advance_step()
        
        # Start first step if not started
        if self.current_step_index == 0 and not self.dialog.is_active() and not self.tutorial_complete:
            self._execute_current_step()
        
        # Complete tutorial
        if self.tutorial_complete:
            self.complete_tutorial()

    def draw(self, surface: pygame.Surface) -> None:
        """Draw the tutorial scene."""
        # Draw background or embedded scene
        if self.embedded_scene:
            self.embedded_scene.draw(surface)
        else:
            self.background.draw(surface)
        
        # Draw tutorial sprites (on top of scene)
        self.professor_sprite.draw(surface)
        self.extra_sprite.draw(surface)
        
        # Draw focus overlay
        self.focus.draw(surface)
        
        # Draw dialog via UI manager (on top)
        self.ui_manager.draw(surface)
        
        # Draw skip hint (keyboard players see the START hint; touch
        # players get the SkipOverlay pill below — both are non-blocking).
        self._draw_skip_hint(surface)
        self._skip_overlay.draw(surface)
    
    def _draw_skip_hint(self, surface: pygame.Surface):
        """Draw the hint to skip the tutorial."""
        from utils.asset_utils import font_load
        from ui.ui_constants import TEXT_FONT
        # The game's own text font at the ordinary size — this used to be
        # pygame's default face at two thirds of it, and read as noise.
        # Rendered once per scale, not every frame.
        cached = getattr(self, "_skip_hint_text", None)
        if cached is None or cached[0] != self.ui_scale:
            font = font_load(TEXT_FONT, int(16 * self.ui_scale))
            cached = (self.ui_scale, font.render("START to skip tutorial", True, (150, 150, 150)))
            self._skip_hint_text = cached
        text = cached[1]
        
        # Position at top-right
        x = runtime_globals.SCREEN_WIDTH - text.get_width() - int(5 * self.ui_scale)
        y = int(2 * self.ui_scale)
        surface.blit(text, (x, y))

    def plays_own_input_sounds(self):
        """A minigame or battle running in the tutorial reads presses as play,
        as it does outside it (dispatch_input leaves them be; UI-06)."""
        check = getattr(self.embedded_scene, "plays_own_input_sounds", None)
        return bool(check()) if callable(check) else False

    def handle_event(self, event) -> bool:
        """Handle input events."""
        # Touch-mode SKIP pill gets first crack at any tap so it can
        # exit the tutorial without competing with focus / step actions.
        if self._skip_overlay.handle_event(event):
            return True

        # Ignore raw pygame events (TEXTINPUT / physical keys the main loop
        # may forward); the tutorial only acts on the game's tuple events.
        if not isinstance(event, tuple) or len(event) != 2:
            return False

        event_type, event_data = event

        # START skips tutorial
        if event_type == "START":
            self.skip_tutorial()
            return True

        # The shop branch follows SceneConnect forward only (main menu, shop,
        # its modules, the download): back/cancel would move it back or out
        # of the tutorial with the tutorial's Digimon as the party. START
        # (skip) still works.
        if (self._download_lock or self.embedded_scene_name == "connect") and event_type in ("B", "CANCEL"):
            if hasattr(runtime_globals, 'game_sound') and runtime_globals.game_sound:
                runtime_globals.game_sound.play("cancel")
            return True
        
        # Dialog handles events first (both top and bottom)
        # This allows clicking anywhere to advance/close dialog
        if self.dialog.is_active():
            if self.dialog.handle_event(event):
                return True
        
        if self.dialog_top.is_active():
            if self.dialog_top.handle_event(event):
                return True
        
        # Block clicks outside focused regions while a highlight is shown (one
        # fading out belongs to a step that is done: the battle's charge right
        # after FIGHT takes taps anywhere)
        if event_type == "LCLICK" and self.focus.state in (TutorialFocus.STATE_FADE_IN, TutorialFocus.STATE_ACTIVE):
            # Get mouse position
            mouse_pos = None
            if event_data and "pos" in event_data:
                mouse_pos = event_data["pos"]
            elif hasattr(runtime_globals, 'input_manager') and runtime_globals.input_manager:
                mouse_pos = runtime_globals.input_manager.get_mouse_position()
            
            if mouse_pos:
                # Check if click is inside focused region
                if not self.focus.is_click_inside_focus(mouse_pos[0], mouse_pos[1]):
                    # Click is outside focus - block it and play cancel sound
                    # (silent while a minigame or battle reads presses as play)
                    if (hasattr(runtime_globals, 'game_sound') and runtime_globals.game_sound
                            and not self.plays_own_input_sounds()):
                        runtime_globals.game_sound.play("cancel")
                    runtime_globals.game_console.log(f"[SceneTutorial] Click blocked outside focus region at {mouse_pos}")
                    return True
        
        # If waiting for an action, let the embedded scene handle the event
        # The embedded scene's callbacks will call notify_action when appropriate
        if self.waiting_for_action:
            if self.embedded_scene and hasattr(self.embedded_scene, 'handle_event'):
                self.embedded_scene.handle_event(event)
            # SceneConnect has no hooks, so its progress is polled; poll it now
            # too, or a second press before the next frame (A twice on SHOP)
            # reaches the next view before the tutorial knows it got there.
            self._update_connect_phase_progress()
            return True
        
        # Pass to embedded scene if input not blocked
        if self.embedded_scene and not self.block_scene_input:
            if hasattr(self.embedded_scene, 'handle_event'):
                self.embedded_scene.handle_event(event)
        
        return True  # Always consume events in tutorial
    
    def _update_connect_phase_progress(self):
        """Advance the shop tutorial by polling the embedded SceneConnect.

        The connect step embeds the real SceneConnect (not a tutorial
        subclass), so the set_allow_* notification hooks no-op.  Instead we
        watch its current view and the player's module state and fire the
        matching action when each milestone is reached:

            enter_shop      → SceneConnect shows the "shop" view
            view_modules    → SceneConnect shows the "shop_modules" view
            purchase_module → the player has acquired a module (purchases set)
            download_module → an owned module is now installed on disk
        """
        if self.embedded_scene_name != "connect" or not self.embedded_scene:
            return
        # The branch goes main menu -> SHOP -> MODULES -> a module: any other
        # button of those two menus (WiFi, Arena, Items ...) and each view's
        # own way back or out would leave the step the tutorial waits on.
        # They are disabled every frame, as the views rebuild them on every
        # change. In the module list everything but its Back stays: browsing
        # it (and a detail's back-to-list) is the step.
        current = getattr(self.embedded_scene, 'current_view', None)
        keep = self.CONNECT_PATH_BUTTONS.get(getattr(self.embedded_scene, 'current_view_name', None))
        for name, button in (vars(current).items() if current is not None else ()):
            if not name.endswith('_button') or not hasattr(button, 'set_enabled'):
                continue
            if name in ('back_button', 'exit_button') or (keep and name != keep):
                if button.enabled:
                    button.set_enabled(False)
        # Once the module is bought the step is its Download, highlighted on
        # the detail page: the detail's back-to-list would take it away.
        if self.waiting_for_action == "download_module" and current is not None:
            to_list = getattr(current, '_on_detail_back', None)
            for component in getattr(current, 'detail_components', None) or []:
                if (to_list is not None and getattr(component, 'on_click_callback', None) == to_list
                        and getattr(component, 'enabled', False)):
                    component.set_enabled(False)

        action = self.waiting_for_action
        if not action:
            return

        view = getattr(self.embedded_scene, 'current_view_name', None)

        if action == "enter_shop":
            if view == "shop":
                self.notify_action("enter_shop")
        elif action == "view_modules":
            if view == "shop_modules":
                self.notify_action("view_modules")
        elif action == "purchase_module":
            purchases = getattr(game_globals, 'purchases', None)
            if purchases and len(purchases.modules) > 0:
                self.notify_action("purchase_module")
        elif action == "download_module":
            if navigation_utils.has_installed_owned_modules():
                self._download_lock = False
                self.notify_action("download_module")

    def notify_action(self, action_name: str):
        """Called by embedded scenes or callbacks to notify tutorial of completed actions."""
        runtime_globals.game_console.log(f"[SceneTutorial] notify_action: {action_name}, waiting_for: {self.waiting_for_action}")
        if self.waiting_for_action == action_name:
            runtime_globals.game_console.log(f"[SceneTutorial] Action matched, advancing from step {self.current_step_index}")
            self.waiting_for_action = None
            self.expected_menu_index = None
            # The scene behind is the player's again only at the next UNBLOCK
            # step: a second press right after the action (a double click on
            # Adventure, a double tap on Shop) would otherwise move it on
            # before the tutorial has hooked the next view.
            self.block_scene_input = True
            self._advance_step()
        else:
            runtime_globals.game_console.log(f"[SceneTutorial] Action mismatch - ignoring")
    
    def skip_tutorial(self):
        """Skip the entire tutorial."""
        runtime_globals.game_console.log("[SceneTutorial] Tutorial skipped by player")
        self._restore_game_state()
        self._cleanup_tutorial_module()
        self._complete_after_skip()
    
    def _restore_game_state(self):
        """Restore game state after tutorial."""
        # Restore original pet list
        if self.original_pet_list is not None:
            game_globals.pet_list = self.original_pet_list
        # ...and their poop: the tutorial's mess, left when skipped before the
        # wash, would be saved with the party (and cost a care mistake).
        if self.original_poop_list is not None:
            game_globals.poop_list = list(self.original_poop_list)

        # A skip during the battle, or a battle the tutorial never saw end,
        # leaves battle_encounter.change_scene patched
        # (TutorialBattle._patch_battle_encounter): the next real battle's
        # return to the game would call the finished tutorial. The scene shown
        # by then is not the battle, so put the module's own name back.
        import battle.battle_encounter as battle_encounter_module
        from utils import scene_utils
        battle_encounter_module.change_scene = scene_utils.change_scene

        # Reset tutorial flags
        runtime_globals.pet_alert = False
    
    def _cleanup_tutorial_module(self):
        """Remove tutorial module from game_modules."""
        if self.tutorial_module and self.tutorial_module.name in runtime_globals.game_modules:
            del runtime_globals.game_modules[self.tutorial_module.name]
            runtime_globals.game_console.log("[SceneTutorial] Tutorial module removed from game_modules")
    
    def _has_user_modules(self) -> bool:
        """Check if user has any modules installed (excluding Tutorial)."""
        for module_name in runtime_globals.game_modules:
            if module_name.lower() != "tutorial":
                return True
        return False
    
    def _complete_after_skip(self) -> None:
        """Complete tutorial after skip — route via navigation_utils."""
        game_globals.show_tutorial = False
        game_globals.save()
        runtime_globals.game_console.log("[SceneTutorial] Tutorial skipped")
        navigation_utils.route_to_next_scene(check_tutorial=False)

    def complete_tutorial(self) -> None:
        """Complete tutorial and transition to next scene via navigation_utils."""
        game_globals.show_tutorial = False
        self._restore_game_state()
        # The Tutorial module goes with its Digimon: left loaded, it showed
        # among the modules (egg selection's CUSTOM) until a restart.
        self._cleanup_tutorial_module()
        game_globals.save()
        runtime_globals.game_console.log("[SceneTutorial] Tutorial complete")
        navigation_utils.route_to_next_scene(check_tutorial=False)
