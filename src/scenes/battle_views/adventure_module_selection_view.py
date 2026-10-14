"""
AdventureModuleSelectionView - Adventure module selection
Shows module buttons, adventure panel, and navigation buttons
"""
import pygame
import random
from ui.ui_manager import UIManager
from ui.components.title_scene import TitleScene
from ui.components.button import Button
from ui.components.background import Background
from ui.components.image import Image
from ui.components.adventure_panel import AdventurePanel
from ui.components.toggle_button import ToggleButton
from ui.components.button_group import ButtonGroup
from ui.ui_constants import BASE_RESOLUTION
from core import runtime_globals
from core import game_globals
from utils.asset_utils import image_load


class AdventureModuleSelectionView:
    """Adventure module selection view."""
    
    def __init__(self, ui_manager: UIManager, change_view_callback):
        """Initialize the Adventure Module Selection view.
        
        Args:
            ui_manager: The UI manager instance
            change_view_callback: Callback to change to another view
        """
        self.ui_manager = ui_manager
        self.change_view = change_view_callback
        
        # Selection state
        self.selected_module = None
        self.module_button_group = ButtonGroup()
        
        # Pagination state
        self.current_page = 0
        self.modules_per_page = 4
        self.all_adventure_modules = []  # All adventure modules ordered
        
        # UI Components
        self.background = None
        self.title_scene = None
        self.adventure_panel = None
        self.go_button = None
        self.module_selection_image = None
        self.module_buttons = []
        self.random_button = None
        self.more_button = None
        self.back_button = None

        self.available_area = {}
        self.available_round = {} 
        self.area_round_limits = {}  # <-- Store area/round limits per module

        for module in runtime_globals.game_modules.values():
            if module.name not in game_globals.battle_round:
                game_globals.battle_round[module.name] = 1
                game_globals.battle_area[module.name] = 1

            if not module.is_valid_area_round(game_globals.battle_area[module.name], game_globals.battle_round[module.name]):
                runtime_globals.game_console.log(f"[SceneBattle] Invalid saved area/round for {module.name}: {game_globals.battle_area[module.name]}/{game_globals.battle_round[module.name]} -> reset to 1/1")
                game_globals.battle_round[module.name] = 1
                game_globals.battle_area[module.name] = 1
                
            # Initialize selection to max unlocked
            self.available_area[module.name] = game_globals.battle_area[module.name]
            self.available_round[module.name] = game_globals.battle_round[module.name]
            # Store area/round counts for this module
            if hasattr(module, "get_area_round_counts"):
                self.area_round_limits[module.name] = module.get_area_round_counts()
            else:
                self.area_round_limits[module.name] = {}
        
        # Build ordered list of adventure modules
        self.all_adventure_modules = self._get_ordered_adventure_modules()
        
        self._setup_ui()
        
    def _setup_ui(self):
        """Setup the UI components."""
        ui_width = ui_height = BASE_RESOLUTION
        
        # Background
        self.background = Background(ui_width, ui_height)
        self.background.set_regions([(0, ui_height, "black")])
        self.ui_manager.add_component(self.background)
        
        # Title
        self.title_scene = TitleScene(0, 9, "BATTLE")
        self.ui_manager.add_component(self.title_scene)
        
        # Adventure panel
        self.adventure_panel = AdventurePanel(8, 43, 165, 55)
        self.ui_manager.add_component(self.adventure_panel)
        
        # GO button
        self.go_button = Button(
            179, 43, 52, 55,
            "", self._on_go,
            cut_corners={},
            decorators=["Battle_BattleGo"]
        )
        self._make_navigable(self.go_button)
        self.ui_manager.add_component(self.go_button)

        # Module selection background image
        self.module_selection_image = Image(0, 99, 240, 89)
        adventure_selection_sprite = self.ui_manager.load_sprite_integer_scaling("Battle", "ModuleSelection", "")
        if adventure_selection_sprite:
            self.module_selection_image.set_image(image_surface=adventure_selection_sprite)
        self.ui_manager.add_component(self.module_selection_image)
        
        # Module toggle buttons - create one for each adventure module
        button_size = 56
        button_spacing = 1
        start_x = 6
        start_y = 120
        
        # Create a toggle button for each adventure module
        for i, module in enumerate(self.all_adventure_modules):
            # Calculate position (all buttons will use slot positions)
            slot_index = i % 4
            button_x = start_x + slot_index * (button_size + button_spacing)
            
            module_button = ToggleButton(
                button_x, start_y, button_size, button_size,
                "",
                on_toggle=lambda btn, tog, mod=module: self._on_module_button_toggled(mod, tog)
            )
            
            # Store module reference
            module_button.module = module
            
            # Load BattleIcon
            try:
                battle_icon_path = module.folder_path + "/BattleIcon.png"
                battle_icon = image_load(battle_icon_path).convert_alpha()

                ui_scale = self.ui_manager.ui_scale
                icon_size = (button_size - 4) * ui_scale
                scaled_icon = pygame.transform.scale(battle_icon, (icon_size, icon_size))

                module_button.icon_sprite = scaled_icon
            except Exception as e:
                runtime_globals.game_console.log(f"[AdventureModuleSelectionView] Failed to load BattleIcon for {module.name}: {e}")
                module_button.icon_sprite = None

            self._make_navigable(module_button)

            # Initially hide all buttons (will be shown based on page)
            # Keep focusable=True so they're added to focusable_components list
            module_button.visible = False
            
            self.module_buttons.append(module_button)
            self.module_button_group.add_button(module_button)
            self.ui_manager.add_component(module_button)
        
        # Update visibility for first page
        self._update_page_visibility()
        
        # Bottom buttons
        random_button_width = 66
        more_button_width = 56
        back_button_width = 66
        button_height = 25
        button_spacing = 10
        start_x = 9
        start_y = 198
        
        # Random button
        self.random_button = Button(
            start_x, start_y, random_button_width, button_height,
            "RANDOM", self._on_random,
            cut_corners={'tl': False, 'tr': False, 'bl': True, 'br': False}
        )
        self.ui_manager.add_component(self.random_button)
        
        # More button
        more_x = start_x + random_button_width + button_spacing
        self.more_button = Button(
            more_x, start_y, more_button_width, button_height,
            "MORE", self._on_more,
            cut_corners={'tl': False, 'tr': False, 'bl': False, 'br': False}
        )
        self.ui_manager.add_component(self.more_button)
        
        # Back button
        back_x = more_x + more_button_width + button_spacing
        self.back_button = Button(
            back_x, start_y, back_button_width, button_height,
            "BACK", self._on_back,
            cut_corners={'tl': False, 'tr': False, 'bl': False, 'br': True}
        )
        self.ui_manager.add_component(self.back_button)
        
        # Set initial focus to GO button
        if self.go_button:
            self.ui_manager.set_focused_component(self.go_button)
        
        runtime_globals.game_console.log("[AdventureModuleSelectionView] UI setup complete")
    
    def _get_ordered_adventure_modules(self):
        """Get adventure modules ordered by: pet modules -> rest alphabetically.
        Only includes modules with adventure_mode=True."""
        from core import game_globals
        
        # Filter modules with adventure_mode=True
        adventure_modules = [m for m in runtime_globals.game_modules.values() 
                           if hasattr(m, 'adventure_mode') and m.adventure_mode]
        
        # Get pet modules (deduplicated)
        pet_module_names = set()
        for pet in game_globals.pet_list:
            if pet and hasattr(pet, 'module') and pet.module:
                pet_module_names.add(pet.module)
        
        # Separate pet modules from others
        pet_modules = []
        other_modules = []
        
        for module in adventure_modules:
            if module.name in pet_module_names:
                pet_modules.append(module)
            else:
                other_modules.append(module)
        
        # Sort other modules alphabetically by name
        other_modules.sort(key=lambda m: m.name.lower())
        
        # Build ordered list: pet modules first, then alphabetically sorted others
        ordered_modules = pet_modules + other_modules
        
        runtime_globals.game_console.log(f"[AdventureModuleSelectionView] Found {len(ordered_modules)} adventure modules")
        
        return ordered_modules
    
    def _update_page_visibility(self):
        """Update which module buttons are visible based on current page."""
        start_idx = self.current_page * self.modules_per_page
        end_idx = start_idx + self.modules_per_page
        
        runtime_globals.game_console.log(f"[AdventureModuleSelectionView] Updating page {self.current_page}: showing modules {start_idx} to {end_idx-1}")
        runtime_globals.game_console.log(f"[AdventureModuleSelectionView] Total module buttons: {len(self.module_buttons)}")
        
        # Hide all buttons first
        for i, button in enumerate(self.module_buttons):
            button.visible = False
            runtime_globals.game_console.log(f"[AdventureModuleSelectionView] Button {i} ({button.module.name}): hidden")
        
        # Show buttons for current page
        for i in range(start_idx, min(end_idx, len(self.module_buttons))):
            button = self.module_buttons[i]
            button.visible = True
            button.needs_redraw = True
            runtime_globals.game_console.log(f"[AdventureModuleSelectionView] Button {i} ({button.module.name}): visible={button.visible}, focusable={button.focusable}, rect={button.rect}")
        
        # Auto-select first visible module if none selected or selected is not visible
        first_visible_button = next((btn for btn in self.module_buttons if btn.visible), None)
        selected_button_visible = any(btn.visible and btn.is_toggled for btn in self.module_buttons)
        
        if first_visible_button and not selected_button_visible:
            first_visible_button.set_toggled(True, silent=True)
            self.selected_module = first_visible_button.module
            if self.selected_module and self.adventure_panel:
                self.adventure_panel.set_module(
                    self.selected_module,
                    self.available_area[self.selected_module.name],
                    self.available_round[self.selected_module.name],
                    self.area_round_limits[self.selected_module.name]
                )
    
    def _on_module_button_toggled(self, module, toggled):
        """Handle module button toggle."""
        runtime_globals.game_console.log(f"[AdventureModuleSelectionView] _on_module_button_toggled called: module={module.name}, toggled={toggled}")
        if toggled:
            runtime_globals.game_sound.play("menu")
            self.selected_module = module
            if self.adventure_panel:
                self.adventure_panel.set_module(
                    self.selected_module,
                    self.available_area[self.selected_module.name],
                    self.available_round[self.selected_module.name],
                    self.area_round_limits[self.selected_module.name]
                )
            runtime_globals.game_console.log(f"[AdventureModuleSelectionView] Module selected: {self.selected_module.name}")
    
    def _make_navigable(self, button):
        """Patch a button instance so LEFT/RIGHT cycle modules instead of moving focus."""
        original = button.handle_event
        def _handle(event):
            event_type, _ = event
            if event_type == "LEFT":
                self._navigate_module(-1)
                return True
            if event_type == "RIGHT":
                self._navigate_module(1)
                return True
            return original(event)
        button.handle_event = _handle

    def _navigate_module(self, direction):
        """Navigate to prev/next module cyclically, changing pages as needed."""
        if not self.module_buttons:
            return

        total = len(self.module_buttons)
        current_index = self.current_page * self.modules_per_page
        for i, btn in enumerate(self.module_buttons):
            if btn.module == self.selected_module:
                current_index = i
                break

        new_index = (current_index + direction) % total
        new_page = new_index // self.modules_per_page

        if new_page != self.current_page:
            self.current_page = new_page
            self._update_page_visibility()

        new_button = self.module_buttons[new_index]
        # set_toggled fires _on_module_button_toggled, which already
        # plays the menu sound - playing here doubled it.
        new_button.set_toggled(True)
        self.ui_manager.set_focused_component(new_button)

    def _on_go(self):
        """Handle GO button press."""
        if not self.selected_module:
            runtime_globals.game_sound.play("cancel")
            return

        runtime_globals.game_sound.play("menu")
        adventure_style = getattr(self.selected_module, 'adventure_style', 'Area Selection')

        if adventure_style == "Random":
            # Random: pick a random area and round, go straight to battle
            limits = self.area_round_limits.get(self.selected_module.name, {})
            if not limits:
                runtime_globals.game_sound.play("cancel")
                return
            area = random.choice(list(limits.keys()))
            round_count = limits[area]
            round_num = random.randint(1, round_count) if round_count > 0 else 1
            from scenes.battle_views.adventure_area_selection_view import pay_entry_or_refuse
            if not pay_entry_or_refuse(self.selected_module, area, round_num):
                return
            game_globals.last_adventure_module = self.selected_module.name
            game_globals.save()
            self.change_view("adventure_battle", module=self.selected_module, area=area, round_num=round_num)
        else:
            # Area Selection and Next and Reset both go to the area selection view
            self.change_view(
                "adventure_area_selection",
                module=self.selected_module,
                available_area=self.available_area[self.selected_module.name],
                available_round=self.available_round[self.selected_module.name],
                area_round_limits=self.area_round_limits[self.selected_module.name]
            )
    
    def _on_random(self):
        """Handle RANDOM button press - select random module and go to its page."""
        if not self.all_adventure_modules:
            runtime_globals.game_sound.play("cancel")
            return
        
        # Pick a random module button
        random_button = random.choice(self.module_buttons)
        
        # Find which page this module is on
        module_index = self.module_buttons.index(random_button)
        target_page = module_index // self.modules_per_page
        
        runtime_globals.game_console.log(f"[AdventureModuleSelectionView] Random selected: {random_button.module.name} (page {target_page})")
        
        # Change to that page
        self.current_page = target_page
        self._update_page_visibility()
        
        # Select the module button
        random_button.set_toggled(True)
        
        runtime_globals.game_sound.play("menu")
    
    def _on_more(self):
        """Handle MORE button press - cycle to next page."""
        if not self.all_adventure_modules:
            runtime_globals.game_sound.play("cancel")
            return
        
        # Calculate total pages
        total_pages = (len(self.all_adventure_modules) + self.modules_per_page - 1) // self.modules_per_page
        
        # Move to next page (wrap to 0 at the end)
        self.current_page = (self.current_page + 1) % total_pages
        
        runtime_globals.game_console.log(f"[AdventureModuleSelectionView] Moving to page {self.current_page} of {total_pages}")
        
        # Update page visibility
        self._update_page_visibility()
        
        runtime_globals.game_sound.play("menu")
    
    def _on_back(self):
        """Handle BACK button press."""
        runtime_globals.game_sound.play("cancel")
        self.change_view("main_menu")
    
    def cleanup(self):
        """Remove all UI components."""
        if self.background:
            self.ui_manager.remove_component(self.background)
        if self.title_scene:
            self.ui_manager.remove_component(self.title_scene)
        if self.adventure_panel:
            self.ui_manager.remove_component(self.adventure_panel)
        if self.go_button:
            self.ui_manager.remove_component(self.go_button)
        if self.module_selection_image:
            self.ui_manager.remove_component(self.module_selection_image)
        for button in self.module_buttons:
            self.ui_manager.remove_component(button)
        if self.random_button:
            self.ui_manager.remove_component(self.random_button)
        if self.more_button:
            self.ui_manager.remove_component(self.more_button)
        if self.back_button:
            self.ui_manager.remove_component(self.back_button)
    
    def update(self):
        """Update the view."""
        pass
    
    def draw(self, surface: pygame.Surface):
        """Draw the view."""
        pass
    
    def handle_event(self, event):
        """Handle input events."""
        if not isinstance(event, tuple) or len(event) != 2:
            return
        event_type, event_data = event
        if event_type == "B":
            self._on_back()
