#=====================================================================
# HeadToHeadTraining (Reaction Timing and Coordination)
#=====================================================================

import os
import random
import pygame

from core import runtime_globals
from training.training import Training
from ui.ui_manager import UIManager
from ui.minigames.head_charge import HeadCharge
from utils.pet_utils import get_training_targets
from utils.scene_utils import change_scene

class HeadToHeadTraining(Training):
    """
    Head-to-Head training mode where two pets face off based on player's timing.
    Now uses the HeadCharge minigame for cleaner separation of concerns.
    """

    def __init__(self, ui_manager: UIManager) -> None:
        super().__init__(ui_manager)
        self.left_pet = None
        self.right_pet = None
        self.head_charge = None

        self.select_pets()
        
        # Initialize the head charge minigame if we have pets, passing attack sprites
        self.head_charge = HeadCharge(ui_manager, self.left_pet, self.right_pet, self.get_attack_sprite(self.left_pet, self.left_pet.atk_main), self.get_attack_sprite(self.right_pet, self.right_pet.atk_main))

    def select_pets(self):
        """Select two pets for head-to-head combat"""
        candidates = get_training_targets()
        self.left_pet, self.right_pet = random.sample(candidates, 2)

    def update(self):
        """Update training state and minigame"""
        super().update()
        if self.phase != "alert":
            self.head_charge.update()
            
        # Check if minigame is complete. Only from the charge: after the result
        # the phase moves on to the currency screen, which this used to undo.
        if self.head_charge.is_complete() and self.phase == "charge":
            self.phase = "result"
            self.frame_counter = 0
            

    def draw_charge(self, surface: pygame.Surface):
        """Draw the head-to-head training"""
        if not (self.left_pet and self.right_pet) or not self.head_charge:
            return

        # Let the head charge minigame handle all drawing
        self.head_charge.draw(surface)
        
        # Draw trophy notification if won and in result phase
        if self.phase == "result" and self.check_victory():
            self.draw_trophy_notification(surface)

    def draw_result(self, surface):
        self.head_charge.draw(surface)
        
        # Draw trophy notification if won and in result phase
        if self.phase == "result" and self.check_victory():
            self.draw_trophy_notification(surface)

    def handle_event(self, event):
        """Handle input events - delegate to minigame or handle exit"""      
        event_type, event_data = event

        if self.phase == "alert":
            return
        
        # Let minigame handle the event first (UP/DOWN inputs)
        if self.phase != "alert" and self.head_charge and self.head_charge.handle_event(event):
            return  # Minigame handled the event
        
        # Let UI manager process components (buttons for mouse/touch)
        if self.phase != "alert" and self.ui_manager and self.ui_manager.handle_event(event):
            return
        
        # Handle exit commands
        if event_type in ("START", "RCLICK") and self.phase == "charge":
            runtime_globals.game_sound.play("cancel")
            change_scene("game")
        elif event_type == "B" and self.phase == "charge":
            runtime_globals.game_sound.play("cancel")
            change_scene("game")
        elif event_type in ("A", "B") and self.phase == "result":
            self.finish_training()

    def check_victory(self):
        """Check if player won the training"""
        if self.head_charge:
            return self.head_charge.check_victory()
        return False

    def check_and_award_trophies(self):
        """Award trophy on winning head-to-head training"""
        if self.check_victory():
            for pet in self.pets:
                pet.award_trophies(1)
            runtime_globals.game_console.log(f"[TROPHY] Head-to-head training won! Trophy awarded.")

    def get_attack_count(self):
        """Get attack count from minigame results"""
        if self.head_charge:
            return self.head_charge.get_attack_count()
        return 0
