"""
ProtocolView - Battle protocol selection

Shows the device lines a versus battle can be fought under. The list comes
from ``protocol_constants``, the same place the DCom grid takes it from, so
the two can never drift -- this view used to carry its own literal and had
simply never had PENZ added to it.

Two pets of any lines fight here, so there is no line of their own to start
on: the grid opens on CANCEL, in its middle.
"""
import pygame
from ui.ui_manager import UIManager
from ui.components.title_scene import TitleScene
from ui.components.background import Background
from ui.components.protocol_selector import ProtocolSelector
from ui.ui_constants import BASE_RESOLUTION
from core import runtime_globals
from battle.sim import protocol_constants


class ProtocolView:
    """Protocol selection view for versus battles."""
    
    def __init__(self, ui_manager: UIManager, change_view_callback, pet1, pet2):
        """Initialize the Protocol view.
        
        Args:
            ui_manager: The UI manager instance
            change_view_callback: Callback to change to another view
            pet1: First pet for battle
            pet2: Second pet for battle
        """
        self.ui_manager = ui_manager
        self.change_view = change_view_callback
        self.pet1 = pet1
        self.pet2 = pet2
        
        # UI Components
        self.background = None
        self.title_scene = None
        self.protocol_menu = None

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
        
        # Protocol selection grid (the same one DCom uses). It is modal, so
        # B reaches it rather than handle_event below, and is passed on here.
        self.protocol_menu = ProtocolSelector()
        self.ui_manager.add_component(self.protocol_menu)
        self._open_grid()

        runtime_globals.game_console.log("[ProtocolView] UI setup complete")

    def _open_grid(self, focus=None, note=None):
        """Show the grid, on *focus* (CANCEL when None) with *note* as its caption."""
        self.protocol_menu.open(protocol_constants.menu_entries(_debug_mode()),
                                self._on_protocol_select,
                                on_cancel=self._on_cancel,
                                focus=focus, note=note)
        self.ui_manager.set_active_menu(self.protocol_menu)

    def _on_protocol_select(self, battle_format):
        """Device line chosen from the grid."""
        if battle_format not in protocol_constants.BATTLE_FORMATS:
            # Offered ahead of its battle format (see OFFERED_UPCOMING). Say
            # so: versus_protocol would otherwise fight it as DM20.
            self._open_grid(focus=battle_format,
                            note=f"{battle_format} is not ready yet")
            return

        # PENZ shares DMX's simulation as it shares its wire; the two differ
        # in the charge minigame, and versus does not play one.
        protocol = protocol_constants.versus_protocol(battle_format)

        runtime_globals.game_console.log(
            f"[ProtocolView] {battle_format} selected ({protocol.name})")

        # Close menu before transitioning
        if self.protocol_menu:
            self.protocol_menu.close()
            if self.ui_manager.active_menu == self.protocol_menu:
                self.ui_manager.active_menu = None
        
        # Change to versus battle view
        # The format travels alongside the protocol: PENZ and DMX share
        # DMX_BS but read the level->pattern table differently.
        self.change_view("versus_battle", pet1=self.pet1, pet2=self.pet2,
                         protocol=protocol, battle_format=battle_format)
    
    def _on_cancel(self):
        """Handle cancel button."""
        runtime_globals.game_sound.play("cancel")
        
        # Close menu before transitioning
        if self.protocol_menu:
            self.protocol_menu.close()
            if self.ui_manager.active_menu == self.protocol_menu:
                self.ui_manager.active_menu = None
        
        self.change_view("versus")
    
    def cleanup(self):
        """Remove all UI components."""
        if self.background:
            self.ui_manager.remove_component(self.background)
        if self.title_scene:
            self.ui_manager.remove_component(self.title_scene)
        if self.protocol_menu:
            self.protocol_menu.close()
            self.ui_manager.remove_component(self.protocol_menu)
    
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
            self._on_cancel()

def _debug_mode():
    """Upcoming lines (TWIN) are offered in the protocol grid only in debug mode."""
    from core import game_globals
    return bool(getattr(game_globals.configuration, "debug_mode", False))
