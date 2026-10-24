"""
AdventureView - Main battle menu
Shows Jogress, Versus, Armor, Adventure, and Exit buttons
"""
import pygame
from ui.ui_manager import UIManager
from ui.components.title_scene import TitleScene
from ui.components.button import Button
from ui.components.background import Background
from ui.components.image import Image
from ui.ui_constants import BASE_RESOLUTION
from core import runtime_globals
from utils.scene_utils import change_scene


class AdventureView:
    """Main battle menu view with navigation buttons."""
    
    def __init__(self, ui_manager: UIManager, change_view_callback):
        """Initialize the main menu view.
        
        Args:
            ui_manager: The UI manager instance
            change_view_callback: Callback to change to another view
        """
        self.ui_manager = ui_manager
        self.change_view = change_view_callback
        
        # UI Components
        self.background = None
        self.title_scene = None
        self.battle_frame = None
        self.jogress_button = None
        self.versus_button = None
        self.armor_button = None
        self.adventure_button = None
        self.specials_button = None
        self.exit_button = None
        
        self._setup_ui()
        
    def _setup_ui(self):
        """Setup the UI components for the main menu."""
        ui_width = ui_height = BASE_RESOLUTION
        
        # Background
        self.background = Background(ui_width, ui_height)
        self.background.set_regions([(0, ui_height, "black")])
        self.ui_manager.add_component(self.background)
        
        # Title
        self.title_scene = TitleScene(0, 9, "BATTLE")
        self.ui_manager.add_component(self.title_scene)
        
        # Battle frame background
        self.battle_frame = Image(0, 0, ui_width, ui_height)
        if self.ui_manager:
            battle_frame_sprite = self.ui_manager.load_sprite_integer_scaling("Battle", "Frame", "")
            if battle_frame_sprite:
                self.battle_frame.set_image(image_surface=battle_frame_sprite)
        self.ui_manager.add_component(self.battle_frame)
        
        # Button dimensions
        button_width = 61
        button_height = 56
        button_spacing = 9
        
        # Calculate positions for 3 buttons side by side
        total_width = (button_width * 3) + (button_spacing * 2)
        start_x = (ui_width - total_width) // 2
        start_y = 60
        
        # Row 1: Jogress, Versus, Armor
        self.jogress_button = Button(
            start_x, start_y, button_width, button_height,
            "", self._on_jogress,
            cut_corners={'tl': True, 'tr': True, 'bl': False, 'br': False},
            decorators=["Battle_Jogress"]
        )
        self.ui_manager.add_component(self.jogress_button)
        
        self.versus_button = Button(
            start_x + (button_width + button_spacing), start_y, button_width, button_height,
            "", self._on_versus,
            cut_corners={'tl': True, 'tr': True, 'bl': False, 'br': False},
            decorators=["Battle_Versus"]
        )
        self.ui_manager.add_component(self.versus_button)
        
        self.armor_button = Button(
            start_x + (button_width + button_spacing) * 2, start_y, button_width, button_height,
            "", self._on_armor,
            cut_corners={'tl': True, 'tr': True, 'bl': False, 'br': False},
            decorators=["Battle_Armor"]
        )
        self.ui_manager.add_component(self.armor_button)
        
        # Adventure button
        adventure_y = start_y + button_height + button_spacing // 2
        self.adventure_button = Button(
            start_x + 2, adventure_y, total_width - 2, 34,
            "", self._on_adventure,
            cut_corners={'tl': False, 'tr': False, 'bl': False, 'br': False},
            decorators=["Battle_Adventure"],
            draw_background=False
        )
        self.ui_manager.add_component(self.adventure_button)
        
        # Specials button (the Specials hub) — only shown when a party pet's
        # module offers something there: codes (codes.json) or an open shop
        # (shop.json). See utils.specials_utils.
        from utils.specials_utils import any_party_specials
        has_specials = any_party_specials()

        exit_width = 75
        exit_height = 25
        exit_x = (ui_width - exit_width) // 2
        exit_y = adventure_y + button_height // 2 + button_spacing

        if has_specials:
            # As wide as EXIT, under it; the label alone fits that width.
            self.specials_button = Button(
                exit_x, exit_y, exit_width, exit_height,
                "SPECIALS", self._on_specials,
                cut_corners={'tl': False, 'tr': False, 'bl': False, 'br': False}
            )
            self.ui_manager.add_component(self.specials_button)
            exit_y += exit_height + 3

        # Exit button
        self.exit_button = Button(
            exit_x, exit_y, exit_width, exit_height,
            "EXIT", self._on_exit,
            cut_corners={'tl': False, 'tr': False, 'bl': False, 'br': False}
        )
        self.ui_manager.add_component(self.exit_button)
        
        # Set initial focus
        if self.adventure_button:
            self.ui_manager.set_focused_component(self.adventure_button)
        
        runtime_globals.game_console.log("[AdventureView] Main menu UI setup complete")
    
    def _on_jogress(self):
        """Handle Jogress button press."""
        runtime_globals.game_sound.play("menu")
        self.change_view("jogress")
    
    def _on_versus(self):
        """Handle Versus button press."""
        runtime_globals.game_sound.play("menu")
        self.change_view("versus")
    
    def _on_armor(self):
        """Handle Armor button press."""
        runtime_globals.game_sound.play("menu")
        self.change_view("armor")
    
    def _on_adventure(self):
        """Handle Adventure button press."""
        runtime_globals.game_sound.play("menu")
        self.change_view("adventure_module_selection")

    def _on_specials(self):
        """Handle Specials button press."""
        runtime_globals.game_sound.play("menu")
        self.change_view("specials")
    
    def _on_exit(self):
        """Handle Exit button press."""
        runtime_globals.game_sound.play("cancel")
        change_scene("game")
    
    def cleanup(self):
        """Remove all UI components from the manager."""
        if self.background:
            self.ui_manager.remove_component(self.background)
        if self.title_scene:
            self.ui_manager.remove_component(self.title_scene)
        if self.battle_frame:
            self.ui_manager.remove_component(self.battle_frame)
        if self.jogress_button:
            self.ui_manager.remove_component(self.jogress_button)
        if self.versus_button:
            self.ui_manager.remove_component(self.versus_button)
        if self.armor_button:
            self.ui_manager.remove_component(self.armor_button)
        if self.adventure_button:
            self.ui_manager.remove_component(self.adventure_button)
        if self.specials_button:
            self.ui_manager.remove_component(self.specials_button)
        if self.exit_button:
            self.ui_manager.remove_component(self.exit_button)
    
    def update(self):
        """Update the view."""
        pass  # UI manager handles updates
    
    def draw(self, surface: pygame.Surface):
        """Draw the view."""
        pass  # UI manager handles drawing
    
    def handle_event(self, event):
        """Handle input events."""
        if not isinstance(event, tuple) or len(event) != 2:
            return
        event_type, event_data = event
        if event_type == "B":
            self._on_exit()
