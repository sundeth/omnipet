"""
VersusBattleView - Versus battle encounter
Handles the versus battle including all phases and result screen
"""
import pygame
from ui.ui_manager import UIManager
from ui.windows.window_background import WindowBackground
from core import runtime_globals
from battle.battle_encounter_versus import BattleEncounterVersus


class VersusBattleView:
    """Versus battle encounter view."""
    
    def __init__(self, ui_manager: UIManager, change_view_callback, pet1, pet2, protocol,
                 battle_format=None):
        """Initialize the Versus Battle view.
        
        Args:
            ui_manager: The UI manager instance
            change_view_callback: Callback to change to another view
            pet1: First pet for battle
            pet2: Second pet for battle
            protocol: Battle protocol to use
        """
        self.ui_manager = ui_manager
        self.change_view = change_view_callback
        self.pet1 = pet1
        self.pet2 = pet2
        self.protocol = protocol
        #: The device line chosen, where that is finer than the protocol.
        self.battle_format = battle_format
        
        # Battle background
        self.battle_background = WindowBackground()
        
        # Battle encounter
        self.battle_encounter = None
        
        self._start_battle()
        
    def _start_battle(self):
        """Start the versus battle."""
        runtime_globals.game_sound.play("battle_online")
        runtime_globals.game_console.log(f"[VersusBattleView] Starting battle: {self.pet1.name} vs {self.pet2.name} using {self.protocol}")
        
        # Create battle encounter
        self.battle_encounter = BattleEncounterVersus(
            self.pet1, self.pet2, self.protocol, battle_format=self.battle_format)
        
        # Check sleep disturbance
        self.pet1.check_disturbed_sleep()
        self.pet2.check_disturbed_sleep()
        
        runtime_globals.game_console.log("[VersusBattleView] Battle encounter created")
    
    def cleanup(self):
        """Cleanup the view."""
        # Battle encounter handles its own cleanup
        pass
    
    def update(self):
        """Update the view."""
        if self.battle_encounter:
            self.battle_encounter.update()
    
    def draw(self, surface: pygame.Surface):
        """Draw the view."""
        # Draw battle background
        self.battle_background.draw(surface)
        
        # Draw battle encounter
        if self.battle_encounter:
            self.battle_encounter.draw(surface)
    
    def handle_event(self, event):
        """Handle input events."""
        if not isinstance(event, tuple) or len(event) != 2:
            return
        if self.battle_encounter:
            self.battle_encounter.handle_event(event)
