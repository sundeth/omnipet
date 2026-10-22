#=====================================================================
# Mogera Training - Multi-phase training with counter, charge, and attack phases
#=====================================================================

import random
import pygame

from core import runtime_globals
from models.animation import PetFrame
from training.training import Training
from ui.ui_manager import UIManager
from battle import combat_constants
import core.constants as constants
from models.game_module import sprite_load
from utils.pygame_utils import blit_with_cache
from ui.minigames.mogera_counter import MogeraCounter
from ui.minigames.dummy_charge import DummyCharge
from utils.scene_utils import change_scene

class MogeraTraining(Training):
    """
    Mogera training mode with multiple phases:
    1. Counter phase - counter 5 attacks
    2. Mogera appear phase  
    3. Charge phase - build up strength (bar difficulty based on phase 1)
    4. Attack phase - pets attack
    5. Result phase - show Mogera damaged or destroyed
    """

    def __init__(self, ui_manager: UIManager) -> None:
        super().__init__(ui_manager)
        
        # Select a random pet for phase 1
        self.counter_pet = random.choice(self.pets)
        
        # Phase 1: Counter minigame (will be created when entering counter phase)
        self.counter_game = None
        
        # Phase 3: Charge minigame (initialized after counter phase)
        self.charge_game = None
        self.bar_level = 14  # Will be adjusted based on counter results
        
        # Phase tracking
        self.current_phase = 1
        self.phase = "alert"  # Start with alert, then counter, mogera_appear, charge, wait_attack, attack_move, impact, result
        self.mogera_frame_counter = 0
        self.mogera_appear_duration = int(60 * (constants.FRAME_RATE / 30))  # 2 seconds
        
        # Load Mogera sprites with proportional scaling
        sprite_scale = runtime_globals.UI_SCALE
        try:
            # Load with proportional scaling - let sprite_load handle it without forcing size
            self.mogera1 = sprite_load(constants.MOGERA1_PATH)
            self.mogera2 = sprite_load(constants.MOGERA2_PATH)
            self.mogera3 = sprite_load(constants.MOGERA3_PATH)
            # Scale proportionally
            target_height = int(120 * sprite_scale)
            for i, sprite in enumerate([self.mogera1, self.mogera2, self.mogera3]):
                if sprite:
                    aspect_ratio = sprite.get_width() / sprite.get_height()
                    target_width = int(target_height * aspect_ratio)
                    scaled = pygame.transform.scale(sprite, (target_width, target_height))
                    if i == 0:
                        self.mogera1 = scaled
                    elif i == 1:
                        self.mogera2 = scaled
                    else:
                        self.mogera3 = scaled
        except:
            # Create placeholder surfaces if sprites don't exist
            mogera_size = (int(60 * sprite_scale), int(120 * sprite_scale))
            self.mogera1 = pygame.Surface(mogera_size)
            self.mogera1.fill((100, 100, 100))  # Gray placeholder
            self.mogera2 = pygame.Surface(mogera_size)
            self.mogera2.fill((150, 150, 150))  # Lighter gray placeholder
            self.mogera3 = pygame.Surface(mogera_size)
            self.mogera3.fill((200, 50, 50))  # Red placeholder for destroyed
            runtime_globals.game_console.log("[MogeraTraining] Mogera sprites not found, using placeholders")
        
        # Attack phase state
        self.attack_positions = []
        self.attack_phase = 1
        self.flash_frame = 0
        self.bar_timer = 0
        
        # Results
        self.countered_count = 0
        self.strength = 0

    def update(self):
        """Update the current phase"""
        # Always update animated sprite
        self.animated_sprite.update()
        
        if self.phase == "alert":
            # Call parent's alert phase update to handle sound and timing
            self.update_alert_phase()
            # Override the phase transition to go to counter instead of charge
            if self.phase == "charge":  # Parent set it to charge
                self.phase = "counter"
                self.frame_counter = 0
                # Create counter game now that pet sprites are loaded
                self.counter_game = MogeraCounter(self.ui_manager, self.counter_pet)
                runtime_globals.game_console.log("[MogeraTraining] Starting counter phase")
        elif self.phase == "counter":
            if self.counter_game:
                self.counter_game.update()
            if self.counter_game and self.counter_game.is_complete():
                self.countered_count = self.counter_game.get_countered_count()
                
                # Check if player countered at least 3 attacks
                if self.countered_count < 3:
                    # Failed - go directly to result with BAD
                    self.strength = 0
                    self.phase = "result"
                    self.frame_counter = 0
                else:
                    # Success - proceed to mogera appear phase
                    self.current_phase = 2
                    self.phase = "mogera_appear"
                    self.mogera_frame_counter = 0
                    self.frame_counter = 0
        
        elif self.phase == "mogera_appear":
            self.mogera_frame_counter += 1
            if self.mogera_frame_counter >= self.mogera_appear_duration:
                self._start_charge_phase()
        
        elif self.phase == "charge":
            self.charge_game.update()
            # Manually check if hold time exceeded (charge game doesn't track this)
            if pygame.time.get_ticks() - self.bar_timer > combat_constants.BAR_HOLD_TIME_MS:
                self.strength = self.charge_game.strength
                self.phase = "wait_attack"
                self.frame_counter = 0
                self.prepare_attacks()
        
        elif self.phase == "wait_attack":
            self.update_wait_attack_phase()

        elif self.phase == "attack_move":
            self.update_attack_move_phase()

        elif self.phase == "impact":
            self.update_impact_phase()
        
        elif self.phase == "result":
            self.update_result_phase()

        elif self.phase == "currency":
            self.update_currency_phase()

        self.frame_counter += 1

    def _start_charge_phase(self):
        """Initialize charge phase based on counter results"""
        # Adjust bar difficulty: 3 counters = hardest (14), 5 counters = easiest (10)
        # Bar level is how many presses needed to reach max
        if self.countered_count == 5:
            self.bar_level = 4
        elif self.countered_count == 4:
            self.bar_level = 2
        else:  # 3 counters
            self.bar_level = 0
        
        self.phase2_reached = True

        self.charge_game = DummyCharge(self.ui_manager)
        self.charge_game.strength = self.bar_level
        
        self.current_phase = 3
        self.phase = "charge"
        self.bar_timer = pygame.time.get_ticks()
        self.frame_counter = 0

    def move_attacks(self):
        """Handles the attack movement towards Mogera"""
        now = pygame.time.get_ticks()
        if not hasattr(self, '_last_atk_tick'):
            self._last_atk_tick = now
        dt_ms = min(100, max(1, now - self._last_atk_tick))
        self._last_atk_tick = now
        speed = combat_constants.ATTACK_SPEED * 30 * dt_ms / 1000

        finished = False
        new_positions = []
        
        if self.attack_phase == 1:
            # Attacks move from right to left
            for sprite, (x, y) in self.attack_positions:
                x -= speed
                if x <= 0:
                    finished = True
                new_positions.append((sprite, (x, y)))
            
            if finished:
                new_positions = []
                self.attack_phase = 2
                for sprite, (x, y) in self.attack_positions:
                    x += runtime_globals.SCREEN_WIDTH
                    new_positions.append((sprite, (x, y)))
            
            self.attack_positions = new_positions
        
        elif self.attack_phase == 2:
            # Attacks move toward Mogera
            mogera_x = int(50 * runtime_globals.UI_SCALE)
            for sprite, (x, y) in self.attack_positions:
                x -= speed
                
                if x <= mogera_x + (48 * runtime_globals.UI_SCALE):
                    finished = True
                new_positions.append((sprite, (x, y)))
            
            if finished:
                runtime_globals.game_sound.play("attack_hit")
                self.phase = "impact"
                self.flash_frame = 0
            
            self.attack_positions = new_positions

    def check_victory(self):
        """M.O.G.E.R.A. destroyed: Phase 1 cleared and the meter built."""
        return self.phase2_reached and self.strength >= 7

    def check_and_award_trophies(self):
        """Award trophy if strength reaches maximum (14) and perfect counter"""
        if self.strength == 14 and self.countered_count == 5:
            for pet in self.pets:
                pet.award_trophies(1)
            runtime_globals.game_console.log(f"[TROPHY] Mogera training perfect score! Trophy awarded.")

    def draw(self, surface):
        """Draw the current phase"""
        if self.phase == "alert":
            self.draw_alert(surface)
        elif self.phase == "counter":
            self.counter_game.draw(surface)
        elif self.phase == "mogera_appear":
            self.draw_mogera_appear(surface)
        elif self.phase == "charge":
            self.draw_charge(surface)
        elif self.phase == "wait_attack":
            self.draw_attack_ready(surface)
        elif self.phase == "attack_move":
            self.draw_attack_move(surface)
        elif self.phase == "impact":
            self.draw_impact(surface)
        elif self.phase == "result":
            self.draw_result(surface)
        elif self.phase == "currency":
            self.draw_currency(surface)

    def draw_mogera_appear(self, surface):
        """Draw Mogera appearing (alternating between mogera1 and mogera2)"""
        # Alternate sprites every half second
        frame_toggle = int((constants.FRAME_RATE / 2))
        mogera_sprite = self.mogera1 if (self.mogera_frame_counter // frame_toggle) % 2 == 0 else self.mogera2
        
        mogera_x = int(50 * runtime_globals.UI_SCALE)
        mogera_y = runtime_globals.SCREEN_HEIGHT // 2 - mogera_sprite.get_height() // 2
        blit_with_cache(surface, mogera_sprite, (mogera_x, mogera_y))

    def draw_charge(self, surface):
        """Draw the charge phase"""
        self.charge_game.draw(surface)
        self.draw_pets(surface)
    
    def draw_attack_ready(self, surface):
        """20-frame idle pause; per-wave prep handles the actual pre-shot anim."""
        self.draw_pets(surface, PetFrame.IDLE1)

    def handle_event(self, event):
        """Handle input events"""
        event_type, event_data = event

        if self.phase == "alert":
            return
        
        if self.phase == "counter":
            # Pass to UI manager for button clicks
            self.ui_manager.handle_event(event)
            
            # Pass to counter game
            if self.counter_game:
                if self.counter_game.handle_event(event):
                    return
            
            # Allow exit during counter phase
            if event_type in ("START", "B"):
                runtime_globals.game_sound.play("cancel")
                change_scene("game")
        
        elif self.phase == "charge":
            if self.charge_game.handle_event(event):
                return

            # "Canceling out of training before M.O.G.E.R.A. has been attacked
            # will not reward anything" (DMGZ manual): leave, as in Phase 1
            if event_type in ("START", "B"):
                runtime_globals.game_sound.play("cancel")
                change_scene("game")
        
        elif self.phase in ("wait_attack", "attack_move", "impact"):
            # Only allow B or START to skip to result, not A
            if event_type in ("B", "START"):
                runtime_globals.game_sound.play("cancel")
                self.phase = "result"
                self.frame_counter = 0
        
        elif self.phase == "result":
            # Allow any button to exit from result
            if event_type in ("A", "B", "START"):
                runtime_globals.game_sound.play("cancel")
                self.phase = "result"
                self.frame_counter = 0

    def draw_attack_move(self, surface):
        """Draw the attack movement phase"""
        if self._wave_in_prep:
            # Pre-shot animation runs through base draw_pets prep path; the
            # projectiles haven't fired yet so don't render them.
            self.draw_pets(surface)
            return

        if self.attack_phase == 1:
            # Show pets attacking
            if self.frame_counter < int(10 * (constants.FRAME_RATE / 30)):
                self.draw_pets(surface, PetFrame.ATK2)
            else:
                self.draw_pets(surface, PetFrame.ATK1)
        else:
            # Show Mogera being targeted
            mogera_sprite = self.mogera1
            blit_with_cache(surface, mogera_sprite, (int(50 * runtime_globals.UI_SCALE), runtime_globals.SCREEN_HEIGHT // 2 - mogera_sprite.get_height() // 2))

        # Draw attack projectiles
        for sprite, (x, y) in self.attack_positions:
            blit_with_cache(surface, sprite, (int(x), int(y)))

    def draw_result(self, surface):
        """Draw the result phase"""
        # If player failed counter phase (< 3 counters), skip directly to BAD animation
        if self.countered_count < 3:
            # Use AnimatedSprite component with predefined result animations
            if not self.animated_sprite.is_animation_playing():
                duration = combat_constants.RESULT_SCREEN_FRAMES / constants.FRAME_RATE
                self.animated_sprite.play_bad(duration)
            
            # Draw the animated sprite
            self.animated_sprite.draw(surface)
        else:
            # Normal result flow for successful counter
            # Determine which Mogera sprite to show based on results
            if self.strength < 7:
                result_img = self.mogera1  # Intact (failure)
            else:
                result_img = self.mogera3  # Destroyed (success)
            
            if self.frame_counter < 30:
                # Show Mogera result
                x = int(50 * runtime_globals.UI_SCALE)
                y = runtime_globals.SCREEN_HEIGHT // 2 - result_img.get_height() // 2
                blit_with_cache(surface, result_img, (x, y))
            else:
                # Use AnimatedSprite component with predefined result animations
                if not self.animated_sprite.is_animation_playing():
                    duration = combat_constants.RESULT_SCREEN_FRAMES / constants.FRAME_RATE
                    
                    # Choose which result animation to play
                    if self.strength < 7:
                        self.animated_sprite.play_bad(duration)
                    elif self.strength < 14:
                        self.animated_sprite.play_great(duration)
                    else:
                        self.animated_sprite.play_excellent(duration)
                
                # Draw the animated sprite
                self.animated_sprite.draw(surface)
                
                # Trophy notification on perfect score
                if self.strength >= 14 and self.countered_count == 5:
                    self.draw_trophy_notification(surface)

    def prepare_attacks(self):
        attack_count = self.get_attack_count()
        targets = self.pets
        total_pets = len(targets)
        if total_pets == 0:
            return

        available_height = runtime_globals.SCREEN_HEIGHT
        spacing = min(available_height // total_pets, int(48 * runtime_globals.UI_SCALE) + int(20 * runtime_globals.UI_SCALE))
        start_y = (runtime_globals.SCREEN_HEIGHT - (spacing * total_pets)) // 2

        s = runtime_globals.UI_SCALE
        for i, pet in enumerate(targets):
            # Use atk_alt for stronger attacks when available
            if attack_count >= 2 and getattr(pet, "atk_alt", 0) > 0:
                atk_sprite = self.get_attack_sprite(pet, pet.atk_alt)
            else:
                atk_sprite = self.get_attack_sprite(pet, pet.atk_main)
            x = runtime_globals.SCREEN_WIDTH - int(48 * s) - int(70 * s)
            y = start_y + i * spacing
            center_y = y + atk_sprite.get_height() // 2

            if attack_count == 1:
                self.attack_positions.append((atk_sprite, (x, y)))
            elif attack_count == 2:
                offsets = [(0, 0), (int(20 * s), int(10 * s))]
                combined = self._combine_sprites(atk_sprite, offsets)
                self.attack_positions.append((combined, (x, y)))
            elif attack_count == 3:
                scaled_sprite = pygame.transform.scale2x(atk_sprite)
                self.attack_positions.append((scaled_sprite, (x, center_y - scaled_sprite.get_height() // 2)))

    def get_attack_count(self):
        """The outcome, as the DMGZ manual gives it (owner, 2026-10-17: like
        the device). Failing the Anti-G phase pays nothing (Bad); clearing it
        earns Strength "whether or not you succeed" at M.O.G.E.R.A., so a
        surviving M.O.G.E.R.A. is a Good that is still a loss (DMGZ's phase-2
        G-Cells), and destroying it an Excellent. Phase 1 is cleared from 3
        counters of 5 (INFERENCE: the manual gives no number; the Color
        line's training wants 3 hits of 5)."""
        if not self.phase2_reached:
            return 0
        if self.strength < 7:
            return 1
        return 3
