"""
LinkDialogView - Discord account linking dialog
Shows code entry for linking Discord account
"""
from ui.ui_manager import UIManager
from ui.components.title_scene import TitleScene
from ui.components.button import Button
from ui.components.background import Background
from ui.components.label import Label
from ui.components.code_entry import CodeEntry
from ui.ui_constants import BASE_RESOLUTION
from core import runtime_globals


class LinkDialogView:
    """Discord account linking dialog view."""
    
    def __init__(self, ui_manager: UIManager, change_view_callback,
                 is_online_mode=False, return_view="main_menu", discord_module=None):
        """Initialize the link dialog view.
        
        Args:
            ui_manager: The UI manager instance
            change_view_callback: Callback to change to another view
            is_online_mode: Whether this is for online mode
            return_view: View to return to after linking (or cancelling)
            discord_module: Reference to the Discord module
        """
        self.ui_manager = ui_manager
        self.change_view = change_view_callback
        self.is_online_mode = is_online_mode
        self.return_view = return_view
        self.discord = discord_module
        
        # UI Components
        self.background = None
        self.title_scene = None
        self.link_title = None
        self.code_entry = None
        self.instruction_label = None
        self.confirm_button = None
        self.cancel_button = None
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup the UI components."""
        ui_width = ui_height = BASE_RESOLUTION
        
        # Background
        self.background = Background(ui_width, ui_height)
        self.background.set_regions([(0, ui_height, "black")])
        self.ui_manager.add_component(self.background)
        
        # Title
        self.title_scene = TitleScene(0, 9, "CONNECT")
        self.ui_manager.add_component(self.title_scene)
        
        # Link title
        self.link_title = Label(0, 40, "Enter Pairing Code", is_title=True)
        self.ui_manager.add_component(self.link_title)
        
        # Code entry (4 characters)
        self.code_entry = CodeEntry((BASE_RESOLUTION - 190) // 2, 80, length=4)
        self.ui_manager.add_component(self.code_entry)
        
        # Instruction label
        self.instruction_label = Label(0, 140, "Use !link in Discord to get code", is_title=False)
        self.ui_manager.add_component(self.instruction_label)
        
        # Buttons
        btn_y = 170
        btn_w = 80
        btn_h = 30
        gap = 20
        
        self.confirm_button = Button(
            (BASE_RESOLUTION // 2) - btn_w - (gap // 2), btn_y, btn_w, btn_h,
            "Confirm", self._on_confirm
        )
        self.ui_manager.add_component(self.confirm_button)
        
        self.cancel_button = Button(
            (BASE_RESOLUTION // 2) + (gap // 2), btn_y, btn_w, btn_h,
            "Cancel", self._on_cancel
        )
        self.ui_manager.add_component(self.cancel_button)
        
        # Set focus to code entry
        self.ui_manager.set_focused_component(self.code_entry)
        
        runtime_globals.game_console.log("[LinkDialogView] UI setup complete")
    
    def _on_confirm(self):
        """Confirm button clicked."""
        # Get code from code entry
        code = ''.join(self.code_entry.chars) if hasattr(self.code_entry, 'chars') else ""
        
        if len(code) != 4:
            self.instruction_label.set_text("Please enter a 4-character code")
            return
        
        runtime_globals.game_console.log(f"[LinkDialogView] Attempting to link with code: {code}")
        
        try:
            if self.discord:
                if self.discord.login(code):
                    runtime_globals.game_console.log(f"[LinkDialogView] Linked as: {self.discord.get_account_name()}")
                    runtime_globals.game_sound.play("menu")
                    
                    # Return to appropriate view
                    if self.is_online_mode:
                        self.change_view("pet_selection", is_online_mode=True)
                    else:
                        self.change_view(self.return_view)
                elif getattr(self.discord, "last_error", None) == "offline":
                    self.instruction_label.set_text("Discord is offline")
                else:
                    self.instruction_label.set_text("Invalid or expired code")
            else:
                self.instruction_label.set_text("Discord not available")
        except Exception as e:
            runtime_globals.game_console.log(f"[LinkDialogView] Link error: {e}")
            self.instruction_label.set_text(f"Error: {str(e)}")
    
    def _on_cancel(self):
        """Cancel button clicked."""
        runtime_globals.game_sound.play("cancel")
        self.change_view(self.return_view)
    
    def update(self):
        """Update the view."""
        pass
    
    def draw(self, surface):
        """Draw view-specific elements."""
        pass
    
    def handle_event(self, event):
        """Handle input events."""
        if not isinstance(event, tuple) or len(event) != 2:
            return
        
        event_type, event_data = event
        
        if event_type == "B":
            self._on_cancel()
            return True
        elif event_type == "A":
            self._on_confirm()
            return True
    
    def cleanup(self):
        """Cleanup when view is destroyed."""
        components = [
            self.background, self.title_scene, self.link_title,
            self.code_entry, self.instruction_label,
            self.confirm_button, self.cancel_button,
        ]
        
        for comp in components:
            if comp and comp in self.ui_manager.components:
                self.ui_manager.remove_component(comp)
        
        runtime_globals.game_console.log("[LinkDialogView] Cleanup complete")
