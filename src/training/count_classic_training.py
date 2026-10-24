#=====================================================================
# CountMatchClassicTraining (Shake-based Strength Bar Training)
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
from ui.minigames.count_match_classic import CountMatchClassic
from ui.minigames.minigame_session import minigame_result


class CountMatchClassicTraining(Training):
    """
    Count Match Classic training mode where players build up strength by shaking.
    Uses the CountMatchClassic minigame (shake to charge 0-40), graded on
    the battle charge's bands (`minigame_result`): one meter, one grading
    (owner, 2026-10-17; training used the old 0-14 bands, so 20 shakes
    were EXCELLENT here and BAD in a battle).
    """

    def __init__(self, ui_manager: UIManager) -> None:
        super().__init__(ui_manager)
        # Don't create minigame yet - wait for charge phase
        # The animated_sprite will show Ready during alert phase (handled by base Training)
        self.minigame = None
        # expose commonly accessed fields for compatibility
        self.strength = 0
        self.bar_level = 14
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
        # Create minigame on first entry to charge phase
        if self.minigame is None:
            self.minigame = CountMatchClassic(self.ui_manager, animated_sprite=self.animated_sprite)
            self.bar_timer = pygame.time.get_ticks()
        
        # Ensure minigame is updated and synced before checking phase
        self.minigame.update()
        self.strength = self.minigame.strength

        # Transition to wait_attack if hold time exceeded (double time for classic: 5000ms)
        if pygame.time.get_ticks() - self.bar_timer > combat_constants.BAR_HOLD_TIME_MS * 2:
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

    def grade(self):
        """The charge's 0-3 grade, as a battle charge grades the same meter."""
        if self.minigame:
            self.strength = self.minigame.strength
        return minigame_result("Count Match Classic", strength=self.strength)

    def check_victory(self):
        """Apply training results and return to game."""
        return self.grade() > 0

    def check_and_award_trophies(self):
        """Award a trophy for an Excellent charge (a full meter)."""
        if self.grade() == 3:
            for pet in self.pets:
                pet.award_trophies(1)
            runtime_globals.game_console.log(f"[TROPHY] Count Match Classic training perfect score achieved! Trophy awarded.")

    def draw_charge(self, surface):
        # Draw pets first, then minigame overlay on top
        self.draw_pets(surface)
        if self.minigame:
            self.minigame.draw(surface)

    def handle_event(self, event):
        """Forward input events to the minigame."""
        event_type, event_data = event

        if self.phase == "alert":
            return
        
        if self.phase == "charge" and self.minigame and self.minigame.handle_event(event):
            return

        if self.phase == "charge" and event_type == "B":
            # B (and the EXIT button, which sends it) leaves, as in Dummy.
            self.quit_charge()
        elif self.phase in ["wait_attack", "attack_move", "impact"] and event_type in ["B", "START"]:
            # Skip to result phase
            runtime_globals.game_sound.play("cancel")
            self.animated_sprite.stop()
            self.phase = "result"
            self.frame_counter = 0
        elif self.phase == "result" and event_type in ["B", "START"]:
            self.finish_training()

    def draw_attack_move(self, surface):
        if self._wave_in_prep:
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
        grade = self.grade()

        result_img = None
        if grade in (1, 2):
            result_img = self.bag2
        elif grade == 0:
            result_img = self.bag1

        if self.frame_counter < 30:
            if result_img:
                x = int(50 * runtime_globals.UI_SCALE)
                y = runtime_globals.SCREEN_HEIGHT // 2 - result_img.get_height() // 2
                blit_with_cache(surface, result_img, (x, y))
        else:
            # Use AnimatedSprite component with predefined result animations
            if not self.animated_sprite.is_animation_playing():
                # The banner of the grade paid (grade 1 used to read GREAT).
                self.play_grade_banner(grade)
            
            # Draw the animated sprite
            self.animated_sprite.draw(surface)

            # Trophy notification on max (draw on top of animated sprite)
            if grade == 3:
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
        """The number of attacks: the charge's grade."""
        return self.grade()
