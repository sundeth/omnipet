import os
import pickle

from ui.ui_manager import UIManager
from ui.components.background import Background
from ui.components.title_scene import TitleScene
from ui.components.button import Button
from ui.components.party_grid import PartyGrid
from ui.components.freezer_grid import FreezerGrid
from ui.components.menu import Menu
from ui.components.label import Label
from ui.components.stats_panel import StatsPanel
from ui.ui_constants import BASE_RESOLUTION
from ui.windows.window_background import WindowBackground
from core import game_globals, runtime_globals
import core.constants as constants
from models.game_freezer import GameFreezer
from utils.scene_utils import change_scene
from utils.pygame_utils import sprite_load


def _format_lock_time(seconds: float) -> str:
    """Time left on an arena lock, short enough for a menu row."""
    minutes = int(seconds // 60)
    if minutes >= 24 * 60:
        return f"{minutes // (24 * 60)}d{(minutes // 60) % 24}h"
    if minutes >= 60:
        return f"{minutes // 60}h{minutes % 60}m"
    return f"{max(1, minutes)}m"


class SceneFreezerBox:
    def __init__(self):
        # Global background (animated)
        self.window_background = WindowBackground(False)
        
        # UI Manager with CYAN theme
        self.ui_manager = UIManager(theme="CYAN")
        
        # Connect input manager to UI manager
        self.ui_manager.set_input_manager(runtime_globals.game_input)
        
        # Mode tracking
        self.mode = "party"  # "party" or "freezer"
        
        # Freezer data
        self.freezer_pets = self.load_freezer_data()
        self.current_freezer_page = 0
        
        # Status window (legacy component)
        self.window_status = None
        self.current_page = 1
        
        # UI Components
        self.background = None
        self.title_scene = None
        self.box_page_label = None
        self.party_button = None
        self.box_button = None
        self.exit_button = None
        self.prev_page_button = None
        self.next_page_button = None
        self.party_grid = None
        self.freezer_grid = None
        self.menu = None
        self.stats_panel = None
        
        self._setup_ui()
        self.load_current_freezer_sprites()
        
        runtime_globals.game_console.log("[SceneFreezerBox] Freezer scene initialized with UI system (CYAN theme).")
    
    def _setup_ui(self):
        """Setup UI components for the freezer scene."""
        ui_width = ui_height = BASE_RESOLUTION
        
        # Background
        self.background = Background(ui_width, ui_height)
        self.background.set_regions([(0, ui_height, "black")])
        self.ui_manager.add_component(self.background)
        
        # Title
        self.title_scene = TitleScene(0, 9, "FREEZER")
        self.ui_manager.add_component(self.title_scene)
        
        # Box page indicator (only visible in box mode)
        self.box_page_label = Label(180, 12, f"Box {self.current_freezer_page + 1}/10", is_title=False)
        self.box_page_label.visible = False
        self.ui_manager.add_component(self.box_page_label)
        
        # Grid dimensions
        grid_x = 22
        grid_y = 30
        grid_width = 190
        grid_height = 145
        
        # Party Grid (initially visible)
        self.party_grid = PartyGrid(grid_x, grid_y, grid_width, grid_height)
        self.party_grid.on_selection_change = self._on_party_select
        self.ui_manager.add_component(self.party_grid)
        self.party_grid.refresh_from_party()
        
        # Freezer Grid (initially hidden)
        self.freezer_grid = FreezerGrid(grid_x+5, grid_y, grid_width, grid_height)
        self.freezer_grid.on_selection_change = self._on_freezer_select
        self.freezer_grid.visible = False
        self.ui_manager.add_component(self.freezer_grid)
        self.freezer_grid.refresh_from_freezer_page(self.freezer_pets[self.current_freezer_page])
        
        # Page navigation buttons (sides of grid, for freezer view only)
        nav_button_width = 20
        
        self.prev_page_button = Button(
            4, grid_y, nav_button_width, grid_height,
            "<", self._on_prev_page_button
        )
        self.prev_page_button.visible = False
        self.ui_manager.add_component(self.prev_page_button)
        
        self.next_page_button = Button(
            216, grid_y, nav_button_width, grid_height,
            ">", self._on_next_page_button
        )
        self.next_page_button.visible = False
        self.ui_manager.add_component(self.next_page_button)
        
        # Bottom buttons (mode switching and exit)
        button_y = 185
        button_height = 47
        
        # Mode switching buttons (Party / Box)
        mode_button_width = 70
        self.party_button = Button(
            8, button_y, mode_button_width, button_height,
            "", self._on_party_mode,
            decorators=["Freezer_Party"]
        )
        self.ui_manager.add_component(self.party_button)
        
        self.box_button = Button(
            82, button_y, mode_button_width, button_height,
            "", self._on_box_mode,
            decorators=["Freezer_Box"]
        )
        self.ui_manager.add_component(self.box_button)
        
        # EXIT button
        exit_button_width = 70
        self.exit_button = Button(
            156, button_y, exit_button_width, button_height,
            "EXIT", self._on_exit
        )
        self.ui_manager.add_component(self.exit_button)
        
        # Menu component (initially hidden) - NOT added to UI manager to avoid double event processing
        self.menu = Menu()
        self.menu.visible = False
        self.menu.manager = self.ui_manager  # Set manager for rendering/scaling
        
        # Manually set up menu rect scaling (since not added via add_component)
        if not self.menu.base_rect:
            self.menu.base_rect = self.menu.rect.copy()
        self.menu.rect = self.ui_manager.scale_rect(self.menu.base_rect)
        
        # Set mouse mode and initial focus
        self.ui_manager.set_focused_component(self.party_grid)
    
    def _on_party_mode(self):
        """Switch to party view."""
        if self.mode != "party":
            runtime_globals.game_sound.play("menu")
            self.mode = "party"
            self.party_grid.visible = True
            self.party_grid.refresh_from_party()
            self.freezer_grid.visible = False
            self.prev_page_button.visible = False
            self.next_page_button.visible = False
            self.box_page_label.visible = False
            #self.ui_manager.set_focused_component(self.party_grid)
            runtime_globals.game_console.log("[SceneFreezerBox] Switched to party view")
    
    def _on_box_mode(self):
        """Switch to freezer box view."""
        if self.mode != "freezer":
            runtime_globals.game_sound.play("menu")
            self.mode = "freezer"
            self.party_grid.visible = False
            self.freezer_grid.visible = True
            self.freezer_grid.refresh_from_freezer_page(self.freezer_pets[self.current_freezer_page])
            # Show arrow buttons only if mouse is enabled
            mouse_enabled = (runtime_globals.INPUT_MODE == runtime_globals.MOUSE_MODE or runtime_globals.INPUT_MODE == runtime_globals.TOUCH_MODE) if runtime_globals.game_input else False
            self.prev_page_button.visible = mouse_enabled
            self.next_page_button.visible = mouse_enabled
            self.box_page_label.visible = True
            self.box_page_label.set_text(f"Box {self.current_freezer_page + 1}/10")
            #self.ui_manager.set_focused_component(self.freezer_grid)
            self.load_current_freezer_sprites()
            runtime_globals.game_console.log("[SceneFreezerBox] Switched to box view")
    
    def _on_party_select(self, item):
        """Handle party grid selection (A button pressed)."""
        if not item:
            return
        
        if item.data:  # Has pet
            pet = item.data
            if getattr(pet, "state", None) == "dead":
                self.menu.open(["Clear", "Stats"], self._on_menu_select, self._on_menu_cancel)
                self.ui_manager.set_active_menu(self.menu)
            else:
                self.menu.open(["Store", "Stats"], self._on_menu_select, self._on_menu_cancel)
                self.ui_manager.set_active_menu(self.menu)
        else:  # Empty slot
            runtime_globals.game_sound.play("menu")
            self.clean_unused_pet_sprites()
            change_scene("egg")
    
    def _on_freezer_select(self, item):
        """Handle freezer grid selection (A button pressed)."""
        if not item or not item.data:
            return
        
        pet = item.data
        if getattr(pet, "state", None) == "dead":
            self.menu.open(["Clear", "Stats"], self._on_menu_select, self._on_menu_cancel)
            self.ui_manager.set_active_menu(self.menu)
        elif game_globals.is_pet_arena_locked(pet):
            # On an arena team: it stays here until the season ends.
            remaining = _format_lock_time(game_globals.arena_lock_remaining(pet))
            self.menu.open([f"Arena {remaining}", "Stats"], self._on_menu_select, self._on_menu_cancel)
            self.ui_manager.set_active_menu(self.menu)
        else:
            self.menu.open(["Add", "Stats"], self._on_menu_select, self._on_menu_cancel)
            self.ui_manager.set_active_menu(self.menu)
    
    def _on_prev_page_button(self):
        """Handle previous page button click"""
        self._change_freezer_page(-1)
    
    def _on_next_page_button(self):
        """Handle next page button click"""
        self._change_freezer_page(1)
    
    def _change_freezer_page(self, direction):
        """Change freezer page."""
        max_pages = len(self.freezer_pets)
        self.current_freezer_page = (self.current_freezer_page + direction) % max_pages
        
        # Update box page label if visible
        if self.box_page_label and self.box_page_label.visible:
            self.box_page_label.set_text(f"Box {self.current_freezer_page + 1}/10")
        
        # Refresh freezer grid if visible
        if self.freezer_grid and self.freezer_grid.visible:
            self.freezer_grid.refresh_from_freezer_page(self.freezer_pets[self.current_freezer_page])
            self.load_current_freezer_sprites()
    
    def _on_exit(self):
        """Handle EXIT button press."""
        runtime_globals.game_sound.play("cancel")
        self.clean_unused_pet_sprites()
        if len(game_globals.pet_list) == 0:
            change_scene("egg")
        else:
            change_scene("game")
    
    def _on_menu_select(self, option_index):
        """Handle menu option selection."""
        runtime_globals.game_console.log(f"[SceneFreezerBox] Menu option {option_index} selected")
        
        # Get selected pet from appropriate grid
        if self.mode == "party":
            item = self.party_grid.get_selected_item()
            selected_pet = item.data if item else None
        else:
            item = self.freezer_grid.get_selected_item()
            selected_pet = item.data if item else None
        
        if not selected_pet:
            runtime_globals.game_console.log(f"[SceneFreezerBox] No pet selected, closing menu")
            self.menu.close()
            return

        if option_index == 0:  # Add, Store, or Clear
            # Suppress menu opening during grid refresh
            if self.mode == "party":
                # Party mode: Store or Clear
                if getattr(selected_pet, "state", None) == "dead":
                    # Clear (delete) the pet from party
                    if selected_pet in game_globals.pet_list:
                        game_globals.pet_list.remove(selected_pet)
                        runtime_globals.game_console.log(f"Cleared {selected_pet.name} from party.")
                    else:
                        runtime_globals.game_console.log(f"[SceneFreezerBox] Pet {selected_pet.name} not in party list!")
                else:
                    # Store to freezer
                    if selected_pet in game_globals.pet_list:
                        game_globals.pet_list.remove(selected_pet)
                        self.freezer_pets[self.current_freezer_page].pets.append(selected_pet)
                        runtime_globals.game_console.log(f"Stored {selected_pet.name}.")
                    else:
                        runtime_globals.game_console.log(f"[SceneFreezerBox] Pet {selected_pet.name} not in party list!")
            else:
                # In freezer mode
                if getattr(selected_pet, "state", None) == "dead":
                    # Clear (delete) the pet
                    if selected_pet in self.freezer_pets[self.current_freezer_page].pets:
                        self.freezer_pets[self.current_freezer_page].pets.remove(selected_pet)
                        runtime_globals.game_console.log(f"Cleared {selected_pet.name} from freezer.")
                    else:
                        runtime_globals.game_console.log(f"[SceneFreezerBox] Pet {selected_pet.name} not in freezer!")
                    # Refresh freezer grid
                    self.freezer_grid.refresh_from_freezer_page(self.freezer_pets[self.current_freezer_page])
                elif game_globals.is_pet_arena_locked(selected_pet):
                    runtime_globals.game_console.log(
                        f"Cannot add {selected_pet.name}: on an arena team until the season ends.")
                    runtime_globals.game_sound.play("cancel")
                    self.menu.close()
                    return
                else:
                    # Move from freezer to party
                    if len(game_globals.pet_list) < game_globals.configuration.max_pets:
                        if selected_pet in self.freezer_pets[self.current_freezer_page].pets:
                            self.freezer_pets[self.current_freezer_page].pets.remove(selected_pet)
                            # A lock that has run out has no further use.
                            selected_pet.arena_lock = None
                            selected_pet.patch()
                            # Reset position to fix Y coordinate after resolution changes
                            selected_pet.begin_position()
                            game_globals.pet_list.append(selected_pet)
                            runtime_globals.game_console.log(f"Moved {selected_pet.name} to party.")
                            runtime_globals.game_sound.play("menu")
                        else:
                            runtime_globals.game_console.log(f"[SceneFreezerBox] Pet {selected_pet.name} not in freezer!")
                    else:
                        runtime_globals.game_console.log(f"Cannot add {selected_pet.name}: Party is full!")
                        runtime_globals.game_sound.play("cancel")
            
            # Save updated freezer state, rebuild, and update sprites
            self.save_freezer_data()
            self.freezer_pets[self.current_freezer_page].rebuild()
            self.load_current_freezer_sprites()

            # Storing or withdrawing changes the party size, and the pet slot
            # is sized from it.
            from utils.pet_utils import refresh_pet_sizes
            refresh_pet_sizes()
            
            # Refresh grids AFTER rebuild to ensure correct state
            if self.mode == "party":
                self.party_grid.refresh_from_party()
                self.freezer_grid.refresh_from_freezer_page(self.freezer_pets[self.current_freezer_page])
            else:
                self.freezer_grid.refresh_from_freezer_page(self.freezer_pets[self.current_freezer_page])
                self.party_grid.refresh_from_party()
            
        elif option_index == 1:  # Stats
            runtime_globals.game_console.log(f"Viewing stats of {selected_pet.name}.")
            # Create and show stats panel
            self.stats_panel = StatsPanel(selected_pet)
            self.ui_manager.set_active_stats_panel(self.stats_panel)
            runtime_globals.game_console.log(f"[SceneFreezerBox] Stats panel opened, returning early")
            return  # Return early since we already closed the menu
        
        # Close menu after any option
        runtime_globals.game_console.log(f"[SceneFreezerBox] Closing menu after option {option_index}")
        self.menu.close()
    
    def _on_menu_cancel(self):
        """Handle menu cancellation."""
        self.menu.close()
    
    def clean_unused_pet_sprites(self):
        """Clear and reload pet sprites, preserving dead pet sprites."""
        runtime_globals.pet_sprites = {}
        for pet in game_globals.pet_list:
            pet.load_sprite()
            # Restore dead sprite if pet is dead
            if pet.state == "dead":
                dead_sprite = sprite_load(constants.DEAD_FRAME_PATH, size=(runtime_globals.PET_WIDTH, runtime_globals.PET_HEIGHT))
                runtime_globals.pet_sprites[pet][0] = dead_sprite
                runtime_globals.pet_sprites[pet][1] = dead_sprite

    def load_current_freezer_sprites(self):
        # Load sprites for pets on the current freezer page
        current_page = self.freezer_pets[self.current_freezer_page]
        for pet in current_page.pets:
            if pet not in runtime_globals.pet_sprites:
                pet.load_sprite()



    def load_freezer_data(self):
        # Use game_globals.get_save_dir() which already handles Android and game mode subfolder
        save_dir = game_globals.get_save_dir()
        file_path = os.path.join(save_dir, "freezer.pkl")
        
        if os.path.exists(file_path):
            try:
                with open(file_path, "rb") as f:
                    pets = pickle.load(f)
                    
                    # Validate game mode compatibility
                    for page in pets:
                        # Patch legacy freezer pages that lack game_mode
                        if not hasattr(page, 'game_mode'):
                            page.game_mode = -1  # Legacy = free
                        
                        page_mode = page.game_mode
                        current_mode = game_globals.game_mode
                        
                        # Validate: legacy (-1) is compatible with free (0) only
                        # A free freezer cannot be loaded in progress mode and vice versa
                        if page_mode == -1:
                            # Legacy freezer = treat as free mode
                            if current_mode == game_globals.GAME_MODE_PROGRESS:
                                # Incompatible: legacy freezer in progress mode
                                # Clear all pets from this page
                                has_pets = any(p is not None for p in page.pets) if page.pets else False
                                if has_pets:
                                    runtime_globals.game_console.log(
                                        f"[Freezer] Warning: Legacy freezer page {page.page} has pets but game is in Progress mode. Pets hidden."
                                    )
                                    page.pets = []
                        elif page_mode != current_mode:
                            # Mode mismatch: clear pets from this page
                            has_pets = any(p is not None for p in page.pets) if page.pets else False
                            if has_pets:
                                runtime_globals.game_console.log(
                                    f"[Freezer] Warning: Freezer page {page.page} is mode {page_mode} but game is mode {current_mode}. Pets hidden."
                                )
                                page.pets = []
                        
                        page.rebuild()
                    return pets
            except Exception as e:
                print(f"[Freezer] Failed to load freezer data: {e}")
        
        # Create new empty freezer with current game mode
        pets = [GameFreezer([], i, "default_bg", "default_module", game_mode=game_globals.game_mode) for i in range(10)]
        self.save_freezer_data(pets)
        return pets

    def save_freezer_data(self, pets=None):
        pets = pets or self.freezer_pets
        
        # Stamp each page with the current game mode
        for page in pets:
            if not hasattr(page, 'game_mode') or page.game_mode == -1:
                page.game_mode = game_globals.game_mode
        
        # Use game_globals.get_save_dir() which already handles Android and game mode subfolder
        save_dir = game_globals.get_save_dir()
        os.makedirs(save_dir, exist_ok=True)
        file_path = os.path.join(save_dir, "freezer.pkl")
        
        with open(file_path, "wb") as f:
            pickle.dump(pets, f)

    def update(self):
        self.ui_manager.update()
        
        # Update arrow button visibility based on mouse mode
        if self.mode == "freezer":
            mouse_enabled = (runtime_globals.INPUT_MODE == runtime_globals.MOUSE_MODE or runtime_globals.INPUT_MODE == runtime_globals.TOUCH_MODE) if runtime_globals.game_input else False
            self.prev_page_button.visible = mouse_enabled
            self.next_page_button.visible = mouse_enabled

    def draw(self, surface):
        # Draw animated background
        self.window_background.draw(surface)
        
        # Draw status window overlay if active
        #if self.window_status:
        #    self.window_status.draw_page(surface, self.current_page)
        #    return
        
        # Draw UI components (includes menu and stats panel as modals)
        self.ui_manager.draw(surface)

    def handle_event(self, event):
        """Handle input events."""
        event_type, event_data = event

        if event_type != "MOUSE_MOTION":
            print(f"[SceneFreezerBox] Handling event: {event_type}, data: {event_data}")
        
        if self.ui_manager.handle_event(event):
            return
        
        # B button exits
        if event_type == "B":
            self._on_exit()
            return
        
        # Mode switching with SELECT - handle before grid
        if event_type == "SELECT":
            runtime_globals.game_sound.play("menu")
            if self.mode == "party":
                self._on_box_mode()
            else:
                self._on_party_mode()
            return
        
        # Page navigation with L/R shoulder buttons (freezer mode only) - handle before grid
        if self.mode == "freezer":
            if event_type == "L":
                runtime_globals.game_sound.play("menu")
                self._change_freezer_page(-1)
                return
            elif event_type == "R":
                runtime_globals.game_sound.play("menu")
                self._change_freezer_page(1)
                return
            # Check for LEFT/RIGHT at grid edges to change page
            if self.freezer_grid.focused:
                if event_type == "LEFT" and self.freezer_grid.cursor_col == 0:
                    runtime_globals.game_sound.play("menu")
                    self._change_freezer_page(-1)
                    return
                elif event_type == "RIGHT" and self.freezer_grid.cursor_col == self.freezer_grid.columns - 1:
                    runtime_globals.game_sound.play("menu")
                    self._change_freezer_page(1)
                    return

    def handle_status_input(self, input_action):
        if input_action == "LEFT":
            runtime_globals.game_sound.play("menu")
            self.current_page = 4 if self.current_page == 1 else self.current_page - 1
            runtime_globals.game_console.log(f"Status page {self.current_page}.")
        elif input_action == "RIGHT":
            runtime_globals.game_sound.play("menu")
            self.current_page = 1 if self.current_page == 4 else self.current_page + 1
            runtime_globals.game_console.log(f"Status page {self.current_page}.")
        elif input_action == "B":
            runtime_globals.game_sound.play("cancel")
            self.window_status = None

