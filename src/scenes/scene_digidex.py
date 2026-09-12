import pygame

from ui.ui_manager import UIManager
from ui.components.background import Background
from ui.components.title_scene import TitleScene
from ui.components.button import Button
from ui.components.menu import Menu
from ui.components.digidex_list import DigidexList
from ui.components.digidex_module_list import (DigidexModuleEntry,
                                               DigidexModuleList,
                                               load_module_battle_icon)
from ui.components.digidex_tree import DigidexTree
from ui.ui_constants import BASE_RESOLUTION
from core import runtime_globals
import core.constants as constants
from models.game_digidex import is_pet_unlocked, load_digidex
from utils.data_compat import availability as read_availability
from models.game_digidex_entry import GameDigidexEntry
from utils.pygame_utils import  sprite_load_percent
from ui.windows.window_background import WindowBackground
from utils.scene_utils import change_scene
from utils.utils_unlocks import unlock_item

UNKNOWN_SPRITE_PATH = constants.UNKNOWN_SPRITE_PATH
SPRITE_BUFFER = 10 
SPRITE_FRAME = "0.png"
SPRITE_SIZE = int(48 * runtime_globals.UI_SCALE)


class SceneDigidex:
    """Refactored SceneDigidex: uses DigidexList as main view and DigidexTree as the tree view.

    The implementation preserves the original sprite-loading window behaviour and tree
    drawing logic but delegates UI responsibilities to the new components.
    """
    def __init__(self):
        # Global background (animated)
        self.window_background = WindowBackground(False)
        
        # UI Manager with LIME theme
        self.ui_manager = UIManager(theme="LIME")
        
        # Connect input manager to UI manager
        self.ui_manager.set_input_manager(runtime_globals.game_input)
        
        # Load unknown sprite for list/tree
        self.unknown_sprite = sprite_load_percent(
            UNKNOWN_SPRITE_PATH, 
            percent=(SPRITE_SIZE / runtime_globals.SCREEN_HEIGHT) * 100, 
            keep_proportion=True, 
            base_on="height"
        )

        self.digidex_data = load_digidex()
        self.pets = self.build_pet_list()
        self.all_pets = self.pets.copy()  # Store unfiltered list for filtering

        # Scope chosen at the module view: which module (None = All) and
        # whether the Friends list (availability == "Friend") is shown
        # instead of the album.
        self.scope_module = None
        self.scope_friends = False

        # View state / navigation: 'module' <-> 'list' <-> 'tree'
        # (the Friends list is a 'list' without a tree level)
        self.state = 'module'

        # UI Components
        self.background = None
        self.title_scene = None
        self.module_list = None
        self.list_view = None
        self.tree_view = None
        self.up_button = None
        self.down_button = None
        self.tree_button = None
        self.back_button = None

        self._setup_ui()
        self._show_module_view()

        runtime_globals.game_console.log("[SceneDigidex] Digidex scene initialized with UI system (LIME theme).")

    def _setup_ui(self):
        """Setup UI components for the digidex scene."""
        ui_width = ui_height = BASE_RESOLUTION
        
        # Background
        self.background = Background(ui_width, ui_height)
        self.background.set_regions([(0, ui_height, "black")])
        self.ui_manager.add_component(self.background)
        
        # Title
        self.title_scene = TitleScene(0, 9, "DIGIDEX")
        self.ui_manager.add_component(self.title_scene)
        
        # Filter button (top right, before EXIT)
        filter_button_width = 55
        filter_button_height = 20
        self.filter_button = Button(ui_width - filter_button_width - 60, 5, filter_button_width, filter_button_height, "FILTER", self._on_filter_click)
        self.ui_manager.add_component(self.filter_button)
        
        # Exit button (top right, next to title)
        exit_button_width = 50
        exit_button_height = 20
        self.exit_button = Button(ui_width - exit_button_width - 5, 5, exit_button_width, exit_button_height, "EXIT", self._on_exit_click)
        self.ui_manager.add_component(self.exit_button)
        
        # Filter state
        self.active_filters = {"module": None, "stage": None, "known": None, "friend": None}
        
        # Module selection list (entry view) — same visuals as the pet list.
        # Sized to its content (rows are 50 base px) up to 4 visible rows;
        # longer lists scroll (UP/DOWN keys, mouse wheel and drag).
        module_entries = self._build_module_entries()
        list_height = 202
        module_list_height = min(list_height, max(1, len(module_entries)) * 50)
        self.module_list = DigidexModuleList(5, 30, 230, module_list_height, self.unknown_sprite, sprite_size=SPRITE_SIZE)
        self.module_list.set_pets(module_entries)
        self.module_list.on_selection_callback = self._on_module_entry_selected
        self.ui_manager.add_component(self.module_list)

        # Pet list view (hidden until a module is chosen)
        self.list_view = DigidexList(5, 30, 230, list_height, self.unknown_sprite, sprite_size=SPRITE_SIZE)
        self.list_view.set_pets(self.pets)
        self.list_view.on_selection_callback = self._on_list_selection
        self.list_view.visible = False
        self.ui_manager.add_component(self.list_view)

        # Tree view (initially hidden)
        self.tree_view = DigidexTree(5, 30, 230, list_height, self.unknown_sprite, sprite_size=SPRITE_SIZE)
        self.tree_view.set_pets(self.pets)
        self.tree_view.on_back = self._on_tree_back
        self.tree_view.visible = False
        self.ui_manager.add_component(self.tree_view)

    # ------------------------------------------------------------------
    # Module scope selection (the scene's entry view)
    # ------------------------------------------------------------------

    def _build_module_entries(self):
        """Rows for the module view: 'All' plus one row per installed module,
        each with the module's battle icon and its known/total pet count."""
        icon_size = int(40 * runtime_globals.UI_SCALE)
        entries = []

        # Eggs (stage 0) are hidden from the lists — exclude them from the
        # counts too. They still appear as the root of the evolution tree.
        listed = [p for p in self.all_pets if p.stage != 0]
        total_all = len(listed)
        known_all = sum(1 for p in listed if p.known)
        entries.append(DigidexModuleEntry(
            "All", None, f"{known_all}/{total_all} known", module_name=None))

        for module in runtime_globals.game_modules.values():
            module_pets = [p for p in listed if p.module == module.name]
            if not module_pets:
                continue
            known = sum(1 for p in module_pets if p.known)
            icon = load_module_battle_icon(module, icon_size)
            entries.append(DigidexModuleEntry(
                module.name, icon, f"{known}/{len(module_pets)} known",
                module_name=module.name))
        return entries

    def _show_module_view(self):
        """Enter the module selection view (the navigation root)."""
        self.state = 'module'
        self.module_list.visible = True
        self.list_view.visible = False
        self.tree_view.visible = False
        self.filter_button.visible = False
        self.exit_button.set_text("EXIT")
        self.ui_manager.set_focused_component(self.module_list)

    def _on_module_entry_selected(self, entry):
        if entry.module_name is None:
            self._set_scope(None, False)
            return
        module_name = entry.module_name
        if self._module_has_friends(module_name):
            # Module has Friend pets: let the player pick which list to see.
            menu = Menu(width=120, height=70)
            menu.open(
                options=["Album", "Friends"],
                on_select=lambda i, m=module_name: self._set_scope(m, i == 1),
                on_cancel=lambda: None  # stay on the module view
            )
            self.ui_manager.set_active_menu(menu)
        else:
            self._set_scope(module_name, False)

    def _module_has_friends(self, module_name) -> bool:
        return any(getattr(p, 'availability', 'Normal') == 'Friend'
                   for p in self.all_pets if p.module == module_name)

    def _set_scope(self, module_name, friends: bool):
        """Apply the chosen scope and enter the pet/friend list view."""
        self.scope_module = module_name
        self.scope_friends = friends
        runtime_globals.game_sound.play("menu")
        self._refresh_filtered_list()

        self.state = 'list'
        self.module_list.visible = False
        self.list_view.visible = True
        self.tree_view.visible = False
        self.filter_button.visible = True
        self.exit_button.set_text("BACK")
        self.ui_manager.set_focused_component(self.list_view)
        runtime_globals.game_console.log(
            f"[SceneDigidex] Scope: module={module_name or 'All'} friends={friends}")

    def build_pet_list(self):
        all_entries = []
        known_count_by_module = {}

        for module in runtime_globals.game_modules.values():
            monsters = module.get_all_monsters()
            module_known_count = 0

            module_friends = None

            for monster in monsters:
                # Unobtainable pets never appear in the digidex.
                availability = read_availability(monster)
                if availability == "Unobtainable":
                    continue

                name = monster["name"]
                version = monster["version"]
                attribute = monster.get("attribute", "")
                stage = monster.get("stage", 0)
                name_format = module.name_format
                if availability == "Friend":
                    # Friend pets are discovered by battling their
                    # Friend-flagged enemy, tracked in the save's friend list.
                    if module_friends is None:
                        from utils.xros_utils import get_module_friends
                        module_friends = get_module_friends(module.name)
                    known = name in module_friends
                else:
                    known = is_pet_unlocked(name, module.name, version)

                if not known:
                    name = "????"
                    attribute = "???"
                    sprite = self.unknown_sprite
                else:
                    module_known_count += 1
                    sprite = None

                entry = GameDigidexEntry(name, attribute, stage, module.name, version, sprite, known, name_format)
                entry.availability = availability
                all_entries.append(entry)

            known_count_by_module[module.name] = module_known_count

        for module in runtime_globals.game_modules.values():
            unlocks = getattr(module, "unlocks", [])
            if isinstance(unlocks, list):
                module_known_count = known_count_by_module.get(module.name, 0)
                for unlock in unlocks:
                    if unlock.get("type") == "digidex" and "amount" in unlock:
                        if module_known_count >= unlock["amount"]:
                            unlock_item(module.name, "digidex", unlock["name"])

        all_entries.sort(key=lambda e: (e.stage, e.module.lower(), e.version))
        return all_entries

    def update(self):
        # Update shared window background
        self.window_background.update()
        
        # Update UI manager (delegates to active components)
        self.ui_manager.update()

    def draw(self, surface: pygame.Surface):
        # Draw shared window background
        self.window_background.draw(surface)
        
        # Draw UI components via manager
        self.ui_manager.draw(surface)

    def handle_event(self, event):
        if not isinstance(event, tuple) or len(event) != 2:
            return False
        
        event_type, event_data = event
        
        # Handle events through UIManager
        if self.ui_manager.handle_event(event):
            return True
        
        # Enable keyboard navigation mode for keyboard/scroll inputs
        if event_type in ["B"]:
            self.ui_manager.keyboard_navigation_mode = True
            # Mirror the EXIT/BACK button: one navigation level up,
            # leaving the scene only from the module selection view.
            self._navigate_back()
            return True
                
    
    def _on_list_selection(self, selected_pet):
        """Callback when a pet is selected in the list view"""
        # The Friends list has no evolution tree level.
        if self.scope_friends:
            return
        if selected_pet and selected_pet.known:
            # Switch to tree view
            self.list_view.visible = False
            self.tree_view.visible = True
            self.filter_button.visible = False  # Hide filter button in tree view
            self.exit_button.set_text("BACK")
            self.state = 'tree'

            # Load and set tree data
            root = self.find_stage_zero_entry(selected_pet)
            tree_data = self.load_evolution_tree(selected_pet)
            self.tree_view.set_root(root, tree_data, selected_pet=selected_pet)

            # Set focus to tree view
            self.ui_manager.set_focused_component(self.tree_view)

            runtime_globals.game_console.log(f"[SceneDigidex] Switched to tree view for {selected_pet.name}")

    def _on_tree_back(self):
        """Called by tree component when user requests back"""
        runtime_globals.game_console.log("[SceneDigidex] _on_tree_back called")
        self.tree_view.visible = False
        self.list_view.visible = True
        self.filter_button.visible = True  # Show filter button in list view
        self.exit_button.set_text("BACK")  # One more level up: module selection
        self.state = 'list'

        # Set focus back to list view
        self.ui_manager.set_focused_component(self.list_view)

        runtime_globals.game_console.log("[SceneDigidex] Returned to list view")

    def _navigate_back(self):
        """One navigation level up: tree -> list -> module selection -> exit.

        The EXIT button only leaves the scene from the module selection view.
        """
        runtime_globals.game_sound.play("cancel")
        if self.state == 'tree':
            self._on_tree_back()
        elif self.state == 'list':
            self._show_module_view()
        else:
            change_scene('game')

    def _on_exit_click(self):
        """EXIT/BACK button clicked — navigate one level up (exit at root)."""
        runtime_globals.game_console.log(f"[SceneDigidex] EXIT/BACK clicked, state={self.state}")
        self._navigate_back()
    
    def _on_filter_click(self):
        """FILTER button clicked - show filter menu"""
        runtime_globals.game_console.log("[SceneDigidex] FILTER button clicked")
        
        # Create and open filter menu
        menu = Menu(width=120, height=120)
        menu.open(
            options=["Module", "Stage", "Known", "Friend", "Reset"],
            on_select=self._on_filter_menu_select,
            on_cancel=lambda: None
        )
        self.ui_manager.set_active_menu(menu)
        runtime_globals.game_sound.play("menu")

    def _on_filter_menu_select(self, option_index):
        """Handle filter menu selection"""
        options = ["Module", "Stage", "Known", "Friend", "Reset"]
        selected = options[option_index]
        runtime_globals.game_console.log(f"[SceneDigidex] Filter option selected: {selected}")
        
        if selected == "Module":
            # Show module submenu
            module_names = [mod.name for mod in runtime_globals.game_modules.values()]
            menu = Menu(width=120, height=min(200, 20 + len(module_names) * 20))
            menu.open(
                options=module_names,
                on_select=lambda idx: self._apply_filter("module", module_names[idx]),
                on_cancel=lambda: None
            )
            self.ui_manager.set_active_menu(menu)
        
        elif selected == "Stage":
            # Show stage submenu (eggs are hidden from the list, so stage 0
            # is not offered; menu index 0 = stage 1)
            stage_list = constants.STAGES[1:]
            menu = Menu(width=150, height=min(200, 20 + len(stage_list) * 20))
            menu.open(
                options=stage_list,
                on_select=lambda idx: self._apply_filter("stage", idx + 1),
                on_cancel=lambda: None
            )
            self.ui_manager.set_active_menu(menu)
        
        elif selected == "Known":
            # Filter to known pets directly -- no submenu (a Yes/No prompt
            # here read as a confirmation dialog and confused players).
            self._apply_filter("known", True)

        elif selected == "Friend":
            # Filter to Friend pets directly (overrides the album scope).
            self._apply_filter("friend", True)

        elif selected == "Reset":
            # Confirm before clearing all filters
            menu = Menu(width=100, height=60)
            menu.open(
                options=["Yes", "No"],
                on_select=lambda idx: self._clear_filters() if idx == 0 else None,
                on_cancel=lambda: None
            )
            self.ui_manager.set_active_menu(menu)
    
    def _apply_filter(self, filter_type, value):
        """Apply a filter and refresh the list"""
        runtime_globals.game_console.log(f"[SceneDigidex] Applying filter: {filter_type}={value}")
        self.active_filters[filter_type] = value
        self._refresh_filtered_list()
        runtime_globals.game_sound.play("menu")
    
    def _clear_filters(self):
        """Clear all active filters"""
        runtime_globals.game_console.log("[SceneDigidex] Clearing all filters")
        self.active_filters = {"module": None, "stage": None, "known": None, "friend": None}
        self._refresh_filtered_list()
        runtime_globals.game_sound.play("menu")

    def _refresh_filtered_list(self):
        """Refresh the list view with the current scope + filters applied"""
        # Eggs never show in the lists (they still open the evolution tree
        # as its root node).
        filtered_pets = [p for p in self.all_pets if p.stage != 0]

        # Scope: chosen module (None = all modules)
        if self.scope_module is not None:
            filtered_pets = [p for p in filtered_pets if p.module == self.scope_module]

        # Friend pets live in their own "Friends" list; the album (and the
        # All view) hides them.  The Friend search filter overrides that.
        want_friends = self.scope_friends or self.active_filters.get("friend")
        if want_friends:
            filtered_pets = [p for p in filtered_pets
                             if getattr(p, 'availability', 'Normal') == 'Friend']
        else:
            filtered_pets = [p for p in filtered_pets
                             if getattr(p, 'availability', 'Normal') != 'Friend']

        # Apply module filter
        if self.active_filters["module"] is not None:
            filtered_pets = [p for p in filtered_pets if p.module == self.active_filters["module"]]

        # Apply stage filter
        if self.active_filters["stage"] is not None:
            filtered_pets = [p for p in filtered_pets if p.stage == self.active_filters["stage"]]

        # Apply known filter
        if self.active_filters["known"] is not None:
            filtered_pets = [p for p in filtered_pets if p.known == self.active_filters["known"]]
        
        # Update list view
        self.pets = filtered_pets
        self.list_view.set_pets(filtered_pets)
        self.list_view.selected_index = 0
        self.list_view.scroll_offset = 0
        self.list_view.needs_redraw = True
        
        runtime_globals.game_console.log(f"[SceneDigidex] Filtered list: {len(filtered_pets)} pets")

    # Keep helper functions for building/loading tree (copied from original for fidelity)
    def load_evolution_tree(self, root_entry):
        module = next((m for m in runtime_globals.game_modules.values() if m.name == root_entry.module), None)
        if not module:
            runtime_globals.game_console.log(f"[Digidex] Módulo '{root_entry.module}' não encontrado.")
            return {}

        tree = {}
        monsters = module.get_all_monsters()
        monsters = [m for m in monsters if m["version"] == root_entry.version]
        valid_names = {m["name"] for m in monsters}
        for monster in monsters:
            name = monster["name"]
            evolutions = monster.get("evolve", [])
            tree[name] = [evo["to"] for evo in evolutions if evo["to"] in valid_names]
        return tree

    def find_stage_zero_entry(self, pet):
        # Search the unfiltered list — eggs are hidden from self.pets but
        # remain the tree's root node.
        for entry in self.all_pets:
            if entry.module == pet.module and entry.version == pet.version and entry.stage == 0:
                return entry
        return pet
