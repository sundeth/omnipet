"""
Scene Debug
A debug scene with various testing and debugging options for pets.
Refactored to use the new UI system with button components.
"""
import pygame
import random
import time

from ui.ui_manager import UIManager
from ui.components.background import Background
from ui.components.button import Button
from ui.components.menu import Menu
from ui.components.title_scene import TitleScene
from ui.components.pet_selector import PetSelector
from ui.ui_constants import BASE_RESOLUTION
from ui.windows.window_background import WindowBackground
from core import game_globals, runtime_globals
from models.game_digidex import register_digidex_entry
from models.game_pet import GamePet
from utils.scene_utils import change_scene
from utils.pet_utils import distribute_pets_evenly, get_selected_pets, refresh_pet_sizes
from utils.module_utils import get_module
from utils.quest_event_utils import force_complete_quest, generate_daily_quests, get_hourly_random_event
from utils.utils_unlocks import is_unlocked


#=====================================================================
# SceneDebug
#=====================================================================
class SceneDebug:
    """
    Debug scene with various testing options for pets and game systems.
    Refactored to use UI system with button grid and page navigation.
    """

    # Rows the Add Pet picker shows at once; the rest are scrolled to.
    MENU_MAX_VISIBLE = 8

    def __init__(self) -> None:
        """
        Initializes the debug scene with UI components.
        """
        # Global background (old system)
        self.window_background = WindowBackground()
        
        # UI Manager for component handling (Gray theme)
        self.ui_manager = UIManager(theme="GRAY")
        
        # Connect input manager to UI manager for mouse handling
        self.ui_manager.set_input_manager(runtime_globals.game_input)
        
        # Current page for button options
        self.current_page = 0
        
        # Counter for each debug action
        self.action_counters = {}
        
        # Define debug options - will be split into pages of 6
        self.debug_options = [
            ("+60min", self._add_60min, "Add 60 minutes to pet timers"),
            ("Sick", self._add_sickness, "Add sickness and injuries"), 
            ("Mistake", self._add_mistake, "Add care mistake or remove condition heart"),
            ("Effort", self._add_effort, "Add to effort counter"),
            ("Overfeed", self._add_overfeed, "Add to overfeed counter"),
            ("Sp Enc ON", self._special_encounter_on, "Turn special encounter ON"),
            ("Sp Enc OFF", self._special_encounter_off, "Turn special encounter OFF"),
            ("+100 EXP", self._add_experience, "Add 100 experience points"),
            ("+1 Lv", self._add_level, "Add 1 level (max 10)"),
            ("+Quest Count", self._add_quest_count, "Add to quest completed counter"),
            ("Weight Res", self._reset_weight, "Reset weight to minimum"),
            ("+Trophy", self._add_trophy, "Add a trophy"),
            ("+1000VV", self._add_vital_values, "Add 1000 vital values (max 9999)"),
            ("+Stage5", self._add_stage5_kill, "Add to stage 5 enemy kills"),
            ("Sleep Dist", self._add_sleep_disturbance, "Add sleep disturbance"),
            ("+Battle Win", self._add_battle_win, "Add battle and win"),
            ("+Battle Lose", self._add_battle_lose, "Add battle loss"),
            ("DP", self._reset_dp, "Reset DP to energy value"),
            ("NAP", self._force_nap, "Force all pets to nap"),
            ("POOP", self._force_poop, "Force all pets to poop"),
            ("KILL", self._kill_pets, "Kill selected pets"),
            ("Traited", self._add_traited_egg, "Add random traited egg"),
            ("G-Fragment", self._add_gcell_fragment, "Add G-Cell fragment for DMGZ v1"),
            ("Quest Reset", self._reset_quests, "Reset daily quests"),
            ("Complete Quests", self._complete_quests, "Complete all available quests"),
            ("Try Event", self._try_event, "Attempt to trigger an event"),
            ("+All Items", self._add_all_items, "Add 1 of each item from all modules"),
            ("Add Pet", self._add_pet, "Pick any pet from any module and add it to the party")
        ]

        # "Add Pet" picker state. The Menu closes itself right after a
        # callback runs, so each step is queued and opened on the next update.
        self.menu = None
        self.pending_menu = None
        self.picker_modules = []
        self.picker_module_index = 0
        self.picker_versions = []
        self.picker_version_index = 0
        self.picker_monsters = []
        self.picker_monster_index = 0
        
        # Initialize counters
        for option_name, _, _ in self.debug_options:
            self.action_counters[option_name] = 0
        
        # Calculate total pages (6 options per page in 2x3 grid)
        self.options_per_page = 6
        self.total_pages = (len(self.debug_options) + self.options_per_page - 1) // self.options_per_page
        
        # UI Components
        self.background = None
        self.title_scene = None
        self.pet_selector = None
        self.option_buttons = []  # 6 buttons for options
        self.left_button = None
        self.exit_button = None
        self.right_button = None
        
        self._setup_ui()
        
        runtime_globals.game_console.log("[SceneDebug] Debug scene initialized with UI system (Gray theme).")

    def _setup_ui(self):
        """Setup UI components for the debug scene."""
        ui_width = ui_height = BASE_RESOLUTION
        
        # Background
        self.background = Background(ui_width, ui_height)
        self.background.set_regions([(0, ui_height, "black")])
        self.ui_manager.add_component(self.background)
        
        # Title
        title_text = f"DEBUG ({self.current_page + 1}/{self.total_pages})"
        self.title_scene = TitleScene(0, 9, title_text)
        self.ui_manager.add_component(self.title_scene)
        
        # Grid layout for 2x3 option buttons
        button_width = 110
        button_height = 28
        button_spacing_x = 8
        button_spacing_y = 4
        
        # Starting position (below title)
        start_x = 8
        start_y = 52  # Moved up to make room for pet selector
        
        # Create 6 option buttons in 2x3 grid (2 columns, 3 rows)
        for row in range(3):
            for col in range(2):
                button_index = row * 2 + col
                x = start_x + col * (button_width + button_spacing_x)
                y = start_y + row * (button_height + button_spacing_y)
                
                button = Button(
                    x, y, button_width, button_height,
                    "",  # Text will be set when updating buttons
                    lambda idx=button_index: self._on_option_selected(idx),
                    cut_corners={'tl': False, 'tr': False, 'bl': True, 'br': False}
                )
                self.option_buttons.append(button)
                self.ui_manager.add_component(button)
        
        # Navigation buttons
        nav_button_width = 66
        nav_button_height = 25
        nav_y = 148  # Moved up
        
        # Left button
        self.left_button = Button(
            9, nav_y, nav_button_width, nav_button_height,
            "< PREV",
            self._on_prev_page,
            cut_corners={'tl': False, 'tr': False, 'bl': True, 'br': False}
        )
        self.ui_manager.add_component(self.left_button)
        
        # Exit button (center)
        exit_x = 9 + nav_button_width + 10
        self.exit_button = Button(
            exit_x, nav_y, nav_button_width, nav_button_height,
            "EXIT",
            self._on_exit,
            cut_corners={'tl': False, 'tr': False, 'bl': False, 'br': False}
        )
        self.ui_manager.add_component(self.exit_button)
        
        # Right button
        right_x = exit_x + nav_button_width + 10
        self.right_button = Button(
            right_x, nav_y, nav_button_width, nav_button_height,
            "NEXT >",
            self._on_next_page,
            cut_corners={'tl': False, 'tr': False, 'bl': False, 'br': True}
        )
        self.ui_manager.add_component(self.right_button)
        
        # Pet selector at bottom
        self.pet_selector = PetSelector(8, 180, 224, 52)
        self.pet_selector.is_interactive = False  # Read-only display, no selection
        self.pet_selector.set_pets(get_selected_pets())  # Set selected pets
        self.pet_selector.selected_pets = []  # No selection highlighting needed
        self.ui_manager.add_component(self.pet_selector)

        # Add Pet picker menu. Kept out of the UI manager's component list (as
        # the freezer box does) so its events are not processed twice; the
        # manager still renders it and routes to it as the active modal.
        self.menu = Menu(width=180)
        self.menu.visible = False
        self.menu.manager = self.ui_manager
        if not self.menu.base_rect:
            self.menu.base_rect = self.menu.rect.copy()
        self.menu.rect = self.ui_manager.scale_rect(self.menu.base_rect)

        # Update button texts for first page
        self._update_button_texts()
        
        # Set mouse mode and initial focus
        if self.option_buttons:
            self.ui_manager.set_focused_component(self.option_buttons[0])

    def _update_button_texts(self):
        """Update button texts based on current page."""
        start_index = self.current_page * self.options_per_page
        
        for i, button in enumerate(self.option_buttons):
            option_index = start_index + i
            
            if option_index < len(self.debug_options):
                option_name, _, _ = self.debug_options[option_index]
                counter = self.action_counters[option_name]
                button.text = f"{option_name} x{counter}"
                button.visible = True
                button.focusable = True
                button.needs_redraw = True  # Force redraw
            else:
                # Hide buttons that don't have options
                button.text = ""
                button.visible = False
                button.focusable = False
                button.needs_redraw = True  # Force redraw
        
        # Update navigation button states
        self.left_button.enabled = self.current_page > 0
        self.right_button.enabled = self.current_page < self.total_pages - 1
        
        # Update page indicator in title
        page_info = f" ({self.current_page + 1}/{self.total_pages})"
        if hasattr(self.title_scene, 'set_title'):
            self.title_scene.set_title(f"DEBUG{page_info}")
            self.title_scene.needs_redraw = True  # Force title redraw

    def _on_option_selected(self, button_index):
        """Handle option button press."""
        option_index = self.current_page * self.options_per_page + button_index
        
        if option_index < len(self.debug_options):
            option_name, action_func, description = self.debug_options[option_index]
            success = action_func()
            
            if success:
                self.action_counters[option_name] += 1
                runtime_globals.game_sound.play("menu")
                runtime_globals.game_console.log(f"[SceneDebug] Executed: {option_name} - {description}")
                # Update button text to show new counter
                self._update_button_texts()
            else:
                runtime_globals.game_sound.play("cancel")

    def _on_prev_page(self):
        """Navigate to previous page."""
        if self.current_page > 0:
            self.current_page -= 1
            self._update_button_texts()
            runtime_globals.game_sound.play("menu")

    def _on_next_page(self):
        """Navigate to next page."""
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self._update_button_texts()
            runtime_globals.game_sound.play("menu")

    def _on_exit(self):
        """Exit debug scene."""
        runtime_globals.game_sound.play("cancel")
        change_scene("game")

    def update(self) -> None:
        """Updates the debug scene."""
        # A Menu closes itself right after its callback returns, so the next
        # step of the Add Pet picker is opened here instead of inside it.
        if self.pending_menu:
            open_next_step = self.pending_menu
            self.pending_menu = None
            open_next_step()

        # Update pet selector with current selected pets
        if self.pet_selector:
            current_pets = get_selected_pets()
            self.pet_selector.set_pets(current_pets)
        
        self.ui_manager.update()

    def draw(self, surface: pygame.Surface) -> None:
        """Draws the debug scene."""
        # Draw global background layer
        self.window_background.draw(surface)
        
        # Draw UI components (includes pet selector)
        self.ui_manager.draw(surface)

    def handle_event(self, event) -> None:
        """Handles input events in the debug scene."""
        if not isinstance(event, tuple) or len(event) != 2:
            return
        
        event_type, event_data = event
        
        # Handle events through UI manager first
        if self.ui_manager.handle_event(event):
            return

    # Debug action methods
    def _add_60min(self) -> bool:
        """Add 60 minutes to pet timers WITHOUT gameplay events.

        Shifting only _rt_origin used to make the per-minute tick see 60
        elapsed minutes at once, so pets instantly lost hunger/strength and
        pooped. Instead: advance the real-time clocks (hatch timers), swallow
        the jump in the minute tick (no hunger/poop/care/death events), and
        credit the evolution clock directly so evolution still progresses.
        """
        selected_pets = get_selected_pets()
        if not selected_pets:
            return False

        from utils.module_utils import get_module
        for pet in selected_pets:
            pet._rt_origin -= 60 * 60      # real-time clocks move forward
            pet._rt_last_minute += 60      # minute tick skips the jump: no events

            # Evolution time still advances (same conditions as the tick)
            module = get_module(pet.module)
            counts_asleep = getattr(module, 'count_evolution_while_sleeping', True)
            if pet.state not in ("nap", "dead") or (pet.state == "nap" and counts_asleep):
                pet._evol_minutes += 60
                pet.update_evolution()

            pet.edited = True
        return True

    def _add_sickness(self) -> bool:
        """Add sickness and injuries."""
        selected_pets = get_selected_pets()
        if not selected_pets:
            return False
            
        for pet in selected_pets:
            pet.sick += 1
            pet.injuries += 1
            pet.edited = True
        return True

    def _add_mistake(self) -> bool:
        """Add care mistake or remove condition heart."""
        selected_pets = get_selected_pets()
        if not selected_pets:
            return False
            
        for pet in selected_pets:
            if get_module(pet.module).use_condition_hearts:
                if pet.condition_hearts > 0:
                    pet.condition_hearts -= 1
            else:
                pet.mistakes += 1
            pet.edited = True
        return True

    def _add_effort(self) -> bool:
        """Add to effort counter."""
        selected_pets = get_selected_pets()
        if not selected_pets:
            return False
            
        for pet in selected_pets:
            pet.effort += 1
            pet.edited = True
        return True

    def _add_overfeed(self) -> bool:
        """Add to overfeed counter."""
        selected_pets = get_selected_pets()
        if not selected_pets:
            return False
            
        for pet in selected_pets:
            pet.overfeed += 1
            pet.edited = True
        return True

    def _special_encounter_on(self) -> bool:
        """Turn special encounter ON."""
        selected_pets = get_selected_pets()
        if not selected_pets:
            return False
            
        for pet in selected_pets:
            pet.special_encounter = True
            pet.edited = True
        return True

    def _special_encounter_off(self) -> bool:
        """Turn special encounter OFF."""
        selected_pets = get_selected_pets()
        if not selected_pets:
            return False
            
        for pet in selected_pets:
            pet.special_encounter = False
            pet.edited = True
        return True

    def _add_experience(self) -> bool:
        """Add 100 experience points."""
        selected_pets = get_selected_pets()
        if not selected_pets:
            return False
            
        for pet in selected_pets:
            pet.add_experience(100)
            pet.edited = True
        return True

    def _add_level(self) -> bool:
        """Add 1 level (max 10)."""
        selected_pets = get_selected_pets()
        if not selected_pets:
            return False
            
        for pet in selected_pets:
            if pet.level < 10:
                pet.level += 1
            pet.edited = True
        return True

    def _add_quest_count(self) -> bool:
        """Add to quest completed counter."""
        selected_pets = get_selected_pets()
        if not selected_pets:
            return False
            
        for pet in selected_pets:
            pet.quests_completed += 1
            pet.edited = True
        return True

    def _reset_weight(self) -> bool:
        """Reset weight to minimum."""
        selected_pets = get_selected_pets()
        if not selected_pets:
            return False
            
        for pet in selected_pets:
            pet.weight = pet.min_weight
            pet.edited = True
        return True

    def _add_trophy(self) -> bool:
        """Add a trophy."""
        selected_pets = get_selected_pets()
        if not selected_pets:
            return False
            
        for pet in selected_pets:
            pet.trophies += 1
            pet.edited = True
        return True

    def _add_vital_values(self) -> bool:
        """Add 1000 vital values (max 9999)."""
        selected_pets = get_selected_pets()
        if not selected_pets:
            return False
            
        for pet in selected_pets:
            pet.vital_values = min(9999, pet.vital_values + 1000)
            pet.edited = True
        return True

    def _add_stage5_kill(self) -> bool:
        """Add to stage 5 enemy kills."""
        selected_pets = get_selected_pets()
        if not selected_pets:
            return False
            
        for pet in selected_pets:
            pet.enemy_kills[5] += 1
            pet.edited = True
        return True

    def _add_sleep_disturbance(self) -> bool:
        """Add sleep disturbance."""
        selected_pets = get_selected_pets()
        if not selected_pets:
            return False
            
        for pet in selected_pets:
            pet.sleep_disturbances += 1
            pet.edited = True
        return True

    def _add_battle_win(self) -> bool:
        """Add battle and win."""
        selected_pets = get_selected_pets()
        if not selected_pets:
            return False
            
        for pet in selected_pets:
            pet.battles += 1
            pet.totalBattles += 1
            pet.win += 1
            pet.totalWin += 1
            pet.edited = True
        return True

    def _add_battle_lose(self) -> bool:
        """Add battle loss."""
        selected_pets = get_selected_pets()
        if not selected_pets:
            return False
            
        for pet in selected_pets:
            pet.battles += 1
            pet.totalBattles += 1
            pet.edited = True
        return True

    def _reset_dp(self) -> bool:
        """Reset DP to energy value."""
        selected_pets = get_selected_pets()
        if not selected_pets:
            return False
            
        for pet in selected_pets:
            pet.dp = pet.energy
            pet.edited = True
        return True

    def _force_nap(self) -> bool:
        """Force all pets to nap."""
        if not game_globals.pet_list:
            return False
            
        for pet in game_globals.pet_list:
            pet.set_state("nap")
            pet.edited = True
        return True

    def _force_poop(self) -> bool:
        """Force all pets to poop."""
        if not game_globals.pet_list:
            return False
            
        for pet in game_globals.pet_list:
            pet.force_poop()
            pet.edited = True
        return True

    def _kill_pets(self) -> bool:
        """Kill selected pets."""
        selected_pets = get_selected_pets()
        if not selected_pets:
            return False
            
        for pet in selected_pets:
            pet.set_state("dead")
            pet.edited = True
        return True

    def _add_traited_egg(self) -> bool:
        """Add random traited egg."""
        if not runtime_globals.game_modules:
            return False
            
        # Get a random module
        module_names = list(runtime_globals.game_modules.keys())
        random_module_name = random.choice(module_names)
        random_module = runtime_globals.game_modules[random_module_name]
        
        # Get random egg from that module
        eggs = random_module.get_monsters_by_stage(0)
        if not eggs:
            return False
            
        random_egg = random.choice(eggs)
        key = f"{random_module_name}@{random_egg['version']}"
        if key not in game_globals.traited:
            game_globals.traited.append(key)

        runtime_globals.game_console.log(f"[SceneDebug] Added traited egg: {random_egg['name']} from {random_module_name}")
        return True

    def _add_gcell_fragment(self) -> bool:
        """Add G-Cell fragment for DMGZ v1."""
        fragment_key = "DMGZ@1"
        
        # Initialize gcell_fragments if it doesn't exist
        if not hasattr(game_globals, 'gcell_fragments'):
            game_globals.gcell_fragments = []
        
        # Add fragment if not already present
        if fragment_key not in game_globals.gcell_fragments:
            game_globals.gcell_fragments.append(fragment_key)
            runtime_globals.game_console.log(f"[SceneDebug] Added G-Cell fragment: {fragment_key}")
            return True
        else:
            runtime_globals.game_console.log(f"[SceneDebug] G-Cell fragment already exists: {fragment_key}")
            return False

    def _reset_quests(self) -> bool:
        """Reset daily quests."""
        game_globals.quests = generate_daily_quests()
        runtime_globals.game_console.log("[SceneDebug] Daily quests reset")
        return True

    def _complete_quests(self) -> bool:
        """
        Complete all currently available quests.
        """
        if not game_globals.quests:
            runtime_globals.game_console.log("[SceneDebug] No quests available to complete.")
            return False
        
        for quest in game_globals.quests:
            force_complete_quest(quest.id)
        
        runtime_globals.game_console.log("[SceneDebug] All quests forcibly completed.")
        return True

    def _try_event(self) -> bool:
        """Attempt to trigger an event."""
        event = get_hourly_random_event()
        if event:
            game_globals.event = event
            runtime_globals.game_console.log(f"[SceneDebug] Triggered event: {event.name}")
            return True
        else:
            runtime_globals.game_console.log("[SceneDebug] No event triggered")
            return False

    def _add_all_items(self) -> bool:
        """Add 1 of each item from all modules to the inventory."""
        from utils.inventory_utils import add_to_inventory
        
        items_added = 0
        for module_name, module in runtime_globals.game_modules.items():
            if hasattr(module, 'items') and module.items:
                for item in module.items:
                    add_to_inventory(item.id, 1)
                    items_added += 1
        
        runtime_globals.game_console.log(f"[SceneDebug] Added {items_added} items to inventory.")
        return items_added > 0

    # Add Pet picker: module -> version -> pet
    def _add_pet(self) -> bool:
        """Open the picker that adds any module's pet to the party."""
        if not runtime_globals.game_modules:
            return False

        self._open_module_menu()
        return True

    def _open_picker_menu(self, options, on_select, on_cancel, selected_index):
        """Open one step of the picker, restoring where its cursor was."""
        self.menu.open(options, on_select, on_cancel, max_visible=self.MENU_MAX_VISIBLE)
        self.menu.set_selected_index(selected_index)
        self.ui_manager.set_active_menu(self.menu)

    def _open_module_menu(self):
        """Step 1: every installed module."""
        self.picker_modules = sorted(runtime_globals.game_modules.keys())
        self._open_picker_menu(self.picker_modules, self._on_picker_module,
                               self._on_picker_cancel, self.picker_module_index)

    def _open_version_menu(self):
        """Step 2: the versions of that module that have a hatchable egg."""
        options = [f"Ver. {version}" for version in self.picker_versions]
        self._open_picker_menu(options, self._on_picker_version,
                               self._open_module_menu_later, self.picker_version_index)

    def _open_pet_menu(self):
        """Step 3: every pet on the chosen version."""
        options = [monster["name"] for monster in self.picker_monsters]
        self._open_picker_menu(options, self._on_picker_monster,
                               self._open_version_menu_later, self.picker_monster_index)

    def _open_module_menu_later(self):
        self.pending_menu = self._open_module_menu

    def _open_version_menu_later(self):
        self.pending_menu = self._open_version_menu

    def _on_picker_cancel(self):
        """Backing out of the first step closes the picker."""
        self.pending_menu = None

    def _on_picker_module(self, index):
        if not 0 <= index < len(self.picker_modules):
            return
        self.picker_module_index = index
        module = get_module(self.picker_modules[index])
        self.picker_versions = self._get_hatchable_versions(module)
        if not self.picker_versions:
            # Nothing to pick — fall back to the module list rather than
            # opening an empty menu.
            runtime_globals.game_console.log(
                f"[SceneDebug] {module.name} has no hatchable eggs")
            runtime_globals.game_sound.play("cancel")
            self.pending_menu = self._open_module_menu
            return
        self.picker_version_index = 0
        self.pending_menu = self._open_version_menu

    def _on_picker_version(self, index):
        if not 0 <= index < len(self.picker_versions):
            return
        self.picker_version_index = index
        version = self.picker_versions[index]
        module = get_module(self.picker_modules[self.picker_module_index])
        self.picker_monsters = [monster for monster in module.get_all_monsters()
                                if monster.get("version") == version]
        if not self.picker_monsters:
            runtime_globals.game_sound.play("cancel")
            self.pending_menu = self._open_version_menu
            return
        self.picker_monster_index = 0
        self.pending_menu = self._open_pet_menu

    def _on_picker_monster(self, index):
        if not 0 <= index < len(self.picker_monsters):
            return
        self.picker_monster_index = index
        self._spawn_pet(self.picker_monsters[index])

    def _get_hatchable_versions(self, module) -> list:
        """Versions of ``module`` that currently have an obtainable egg.

        Same availability rules as the egg selector: a special egg only counts
        once its unlock — or its G-Cell fragment — is held.
        """
        versions = []
        for egg in module.get_monsters_by_stage(0):
            if egg.get("special", False):
                special_key = egg.get("special_key", "")
                module_name = egg.get("module", module.name)
                if special_key == "gcell_fragment":
                    fragment_key = f"{module_name}@{egg.get('version', 1)}"
                    if fragment_key not in getattr(game_globals, "gcell_fragments", []):
                        continue
                elif special_key and not is_unlocked(module_name, None, special_key):
                    continue
            version = egg.get("version")
            if version is not None and version not in versions:
                versions.append(version)
        return sorted(versions)

    def _spawn_pet(self, monster) -> None:
        """Create the chosen monster and put it in the party."""
        if len(game_globals.pet_list) >= game_globals.configuration.max_pets:
            runtime_globals.game_console.log("[SceneDebug] Party is full, pet not added")
            runtime_globals.game_sound.play("cancel")
            return

        # get_all_monsters returns the raw records, which carry no module.
        pet_data = dict(monster)
        pet_data["module"] = self.picker_modules[self.picker_module_index]

        pet = GamePet(pet_data)
        game_globals.pet_list.append(pet)
        register_digidex_entry(pet.name, pet.module, pet.version)

        # Pet size depends on how many are in the party, so the whole row is
        # resized when one joins.
        refresh_pet_sizes()
        distribute_pets_evenly()

        runtime_globals.game_console.log(
            f"[SceneDebug] Added {pet.name} (v{pet.version}) from {pet.module}")
