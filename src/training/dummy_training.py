#=====================================================================
# DummyTraining (Simple Strength Bar Training)
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
from ui.minigames.dummy_charge import DummyCharge
from utils.scene_utils import change_scene

class DummyTraining(Training):
    """
    Dummy training mode where players build up strength by holding a bar.
    """

    def __init__(self, ui_manager: UIManager) -> None:
        super().__init__(ui_manager)
        # Delegate charge/attack logic to the DummyCharge minigame
        self.minigame = DummyCharge(ui_manager)
        # expose commonly accessed fields for compatibility
        self.strength = self.minigame.strength
        self.bar_level = self.minigame.bar_level
        self.bar_timer = 0
        self.attack_phase = 1
        self.flash_frame = 0

        # Restore attack/result assets/positions (training-specific)
        SPRITE_SETS = [
            (constants.BAG1_PATH, constants.BAG2_PATH),
            (constants.ROCK1_PATH, constants.ROCK2_PATH),
            (constants.TREE1_PATH, constants.TREE2_PATH),
            (constants.BRICK1_PATH, constants.BRICK2_PATH),
        ]

        selected_sprites = random.choice(SPRITE_SETS)
        self.bag1 = sprite_load(selected_sprites[0], size=(60 * runtime_globals.UI_SCALE, 120 * runtime_globals.UI_SCALE))
        self.bag2 = sprite_load(selected_sprites[1], size=(60 * runtime_globals.UI_SCALE, 120 * runtime_globals.UI_SCALE))
        self.attack_positions = []

    def update_charge_phase(self):
        # Ensure minigame is updated and synced before checking phase
        self.minigame.update()
        self.strength = self.minigame.strength

        # Transition to wait_attack if hold time exceeded
        if pygame.time.get_ticks() - self.bar_timer > combat_constants.BAR_HOLD_TIME_MS:
            self.phase = "wait_attack"
            self.frame_counter = 0
            self.prepare_attacks()

    def move_attacks(self):
        """Handles the attack movement towards the bag."""
        now = pygame.time.get_ticks()
        if not hasattr(self, '_last_atk_tick'):
            self._last_atk_tick = now
        dt_ms = min(100, max(1, now - self._last_atk_tick))
        self._last_atk_tick = now
        speed = combat_constants.ATTACK_SPEED * 30 * dt_ms / 1000

        finished = False
        new_positions = []

        if self.attack_phase == 1:
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
            bag_x = 50 * runtime_globals.UI_SCALE
            for sprite, (x, y) in self.attack_positions:
                x -= speed

                if x <= bag_x + (48 * runtime_globals.UI_SCALE):
                    finished = True
                new_positions.append((sprite, (x, y)))

            if finished:
                runtime_globals.game_sound.play("attack_hit")
                self.phase = "impact"
                self.flash_frame = 0

            self.attack_positions = new_positions

    def check_victory(self):
        """Apply training results and return to game."""
        # sync strength from minigame
        self.strength = self.minigame.strength
        return self.strength > 10

    def check_and_award_trophies(self):
        """Award trophy if strength reaches maximum (14)"""
        self.strength = self.minigame.strength

        if self.strength == 14:
            for pet in self.pets:
                pet.award_trophies(1)
            runtime_globals.game_console.log(f"[TROPHY] Dummy training perfect score achieved! Trophy awarded.")

    def draw_charge(self, surface):
        
        self.minigame.draw(surface)
        self.draw_pets(surface)

    def handle_event(self, event):
        """Forward input events to the bar component."""
        event_type, event_data = event

        if self.phase == "alert":
            return
        
        if self.phase == "charge" and self.minigame.handle_event(event):
            return
        
        if event_type in ("START", "B") and self.phase == "charge":
            runtime_globals.game_sound.play("cancel")
            change_scene("game")
        elif event_type in ("B") and self.phase != "result":
            runtime_globals.game_sound.play("cancel")
            self.animated_sprite.stop()
            self.phase = "result"

    def draw_attack_move(self, surface):
        if self._wave_in_prep:
            # Pre-shot animation runs through the base draw_pets prep path; the
            # projectile hasn't fired yet so don't render it.
            self.draw_pets(surface)
            return

        if self.attack_phase == 1:
            if self.frame_counter < int(10 * (constants.FRAME_RATE / 30)):
                self.draw_pets(surface, PetFrame.ATK2)
            else:
                self.draw_pets(surface, PetFrame.ATK1)
        else:
            blit_with_cache(surface, self.bag1, (int(50 * runtime_globals.UI_SCALE), runtime_globals.SCREEN_HEIGHT // 2 - self.bag1.get_height() // 2))

        for sprite, (x, y) in self.attack_positions:
            blit_with_cache(surface, sprite, (int(x), int(y)))

    def draw_result(self, surface):
        self.strength = self.minigame.strength

        result_img = None
        if 10 <= self.strength < 14:
            result_img = self.bag2
        elif self.strength < 10:
            result_img = self.bag1

        
        if self.frame_counter < 30:
            if result_img:
                x = int(50 * runtime_globals.UI_SCALE)
                y = runtime_globals.SCREEN_HEIGHT // 2 - result_img.get_height() // 2
                blit_with_cache(surface, result_img, (x, y))
        else:
            # Use AnimatedSprite component with predefined result animations
            if not self.animated_sprite.is_animation_playing():
                duration = combat_constants.RESULT_SCREEN_FRAMES / constants.FRAME_RATE
                
                
                # Choose which result animation to play
                if self.strength < 10:
                    self.animated_sprite.play_bad(duration)
                elif self.strength < 14:
                    self.animated_sprite.play_great(duration)
                else:
                    self.animated_sprite.play_excellent(duration)
            
            # Draw the animated sprite
            self.animated_sprite.draw(surface)

            # Trophy notification on max (draw on top of animated sprite)
            if self.strength >= 14:
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
        """Returns the number of attacks based on strength."""
        self.strength = self.minigame.strength
        if self.strength <= 10:
            return 0
        elif self.strength < 13:
            return 1
        elif self.strength < 14:
            return 2
        else:
            return 3
