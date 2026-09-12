import random
import pygame

from core import game_globals, runtime_globals
from models.animation import PetFrame
from training.training import Training
from ui.ui_manager import UIManager
from ui.minigames.count_match import CountMatch
from ui.minigames.minigame_session import (count_match_rank,
                                            count_match_super_hits)
from battle.sim.battle_utils import get_penc_training_pattern
from battle import combat_constants
import core.constants as constants
from utils.pygame_utils import blit_with_cache

class CountMatchTraining(Training):
    def __init__(self, ui_manager: UIManager):
        super().__init__(ui_manager)
        self.press_counter = 0
        self.rotation_index = 0
        self.start_time = 0
        self.final_color = 3
        self.correct_color = 0
        self.super_hits = {}
        self.color_band = 0
        self.result_text = None
        self.flash_frame = 0
        self.anim_counter = -1
        
        # Initialize the count match minigame with our AnimatedSprite component
        self.count_match = None
        pet = self.pets[0]
        self.count_match = CountMatch(self.ui_manager, pet, self.animated_sprite)

    def update(self):
        """Override base update to include minigame updates."""
        # Call parent update
        super().update()
        
        # Update minigame and sync counters
        if self.count_match:
            self.count_match.update()
            # Always sync our counters with the minigame in case it processed shake events internally
            self.press_counter = self.count_match.get_press_counter()
            self.rotation_index = self.count_match.get_rotation_index()

    def update_charge_phase(self):
        if self.count_match.phase != "count":
            self.start_count_phase()
        # Use frame-rate independent timing (3 seconds)
        if self.frame_counter > int(3 * game_globals.configuration.frame_rate):
            self.phase = "wait_attack"
            self.calculate_results()
            self.prepare_attack()

    def start_count_phase(self):
        self.phase = "charge"
        self.press_counter = 0
        self.rotation_index = 4  # Start at 4 so first shake goes to 3
        
        # Set minigame to count phase
        self.count_match.set_phase("count")

    def handle_event(self, event):
        event_type, event_data = event

        if self.phase == "alert":
            return
        
        if self.phase == "charge" and event_type in ("Y", "SHAKE"):
            # Let the minigame handle the input
            if self.count_match and self.count_match.handle_event(event):
                self.press_counter = self.count_match.get_press_counter()
                self.rotation_index = self.count_match.get_rotation_index()
                
        elif self.phase in ["wait_attack", "attack_move", "impact"] and event_type in ["B", "START"]:
            # Skip to result phase
            runtime_globals.game_sound.play("cancel")
            self.animated_sprite.stop()
            self.phase = "result"
            self.frame_counter = 0
        elif self.phase == "result" and event_type in ["B", "START"]:
            self.finish_training()
    def get_first_pet_attribute(self):
        pet = self.pets[0]
        attr = getattr(pet, "attribute", "")
        if attr in ["", "Va"]:
            return 0  # Default/Vaccine -> Ready0
        elif attr == "Da":
            return 1  # Data -> Ready1
        elif attr == "Vi":
            return 2  # Virus -> Ready2
        return 0

    def calculate_results(self):
        self.correct_color = self.get_first_pet_attribute()
        self.final_color = self.rotation_index
        pets = self.pets
        if not pets:
            return

        pet = pets[0]
        shakes = self.press_counter
        attr_type = getattr(pet, "attribute", "")

        # One scorer, shared with the battle. The manual's chart is the
        # attribute's ranking of the three colours paying 5 / 3-4 / 2, and
        # this used to work it out from the DISTANCE between the landed
        # colour and the target instead -- which agrees with the ranking but
        # says nothing about it, and was a second copy either way. The battle
        # carried the other copy and had the payouts wrong.
        # The band is shared -- one colour was landed, ranked by the first
        # pet's attribute -- but the ROW it selects is each pet's own, since
        # the table is keyed on the stage as well. So a Child and an Ultimate
        # trained together throw different patterns from the same shake, which
        # is what the device does.
        self.color_band = count_match_rank(self.final_color, attr_type)
        for p in pets:
            self.super_hits[p] = count_match_super_hits(
                self.final_color, attr_type, getattr(p, "stage", 1) or 1)

    def prepare_attack(self):
        self.attack_phase = 0
        self.attack_waves = [[] for _ in range(5)]
        pets = self.pets
        total_pets = len(pets)
        available_height = runtime_globals.SCREEN_HEIGHT
        spacing = min(available_height // total_pets, runtime_globals.OPTION_ICON_SIZE + (20 * runtime_globals.UI_SCALE))
        start_y = (runtime_globals.SCREEN_HEIGHT - (spacing * total_pets)) // 2

        s = runtime_globals.UI_SCALE
        for i, pet in enumerate(pets):
            main_sprite = self.get_attack_sprite(pet, pet.atk_main)
            alt_sprite = self.get_attack_sprite(pet, pet.atk_alt) if getattr(pet, "atk_alt", 0) > 0 else main_sprite
            if not main_sprite:
                continue
            count = self.super_hits.get(pet, 0)
            # **The measured rows, keyed on this pet's own stage.** A real
            # Pendulum Color was shaken to every colour at every stage and the
            # shots read off the screen; not one of the 28 rows opens with its
            # super hits, which is what `[2] * count + [1] * (5 - count)`
            # drew. A Megahit keeps its own triple-sprite level -- that is a
            # training picture and not a damage value, and this line spends
            # 1 or 2 in a battle.
            pattern = ([3] * 5 if count == 5
                       else get_penc_training_pattern(
                           getattr(pet, "stage", 1) or 1,
                           getattr(self, "color_band", 0) or 0))
            pet_y = start_y + i * spacing + runtime_globals.OPTION_ICON_SIZE // 2 - main_sprite.get_height() // 2
            for j, kind in enumerate(pattern):
                x = runtime_globals.SCREEN_WIDTH - runtime_globals.OPTION_ICON_SIZE - (20 * s)
                y = pet_y
                sprite = alt_sprite if kind >= 2 else main_sprite
                if kind == 3:
                    offsets = [(0, 0), (-int(20 * s), -int(10 * s)), (-int(40 * s), int(10 * s))]
                    combined = self._combine_sprites(sprite, offsets)
                    self.attack_waves[j].append((combined, x, y))
                elif kind == 2:
                    offsets = [(0, 0), (-int(20 * s), -int(10 * s))]
                    combined = self._combine_sprites(sprite, offsets)
                    self.attack_waves[j].append((combined, x, y))
                else:
                    self.attack_waves[j].append((sprite, x, y))
        self.frame_counter = 0

    def move_attacks(self):
        """Handles the attack movement towards the bag, all in one phase."""
        if self.current_wave_index >= len(self.attack_waves):
            self.phase = "result"
            self.frame_counter = 0
            return

        wave = self.attack_waves[self.current_wave_index]
        new_wave = []
        all_off_screen = True

        # Shot sound is played by the base class on prep-end; don't duplicate here.

        now = pygame.time.get_ticks()
        if not hasattr(self, '_last_atk_tick'):
            self._last_atk_tick = now
        dt_ms = min(100, max(1, now - self._last_atk_tick))
        self._last_atk_tick = now
        speed = combat_constants.ATTACK_SPEED * 30 * dt_ms / 1000

        for sprite, x, y in wave:
            x -= speed
            if x + (24 * runtime_globals.UI_SCALE) > 0:
                all_off_screen = False
                new_wave.append((sprite, x, y))

        self.attack_waves[self.current_wave_index] = new_wave

        # Short breather (at 30fps) before the next wave
        if all_off_screen and self.frame_counter >= int(4 * (game_globals.configuration.frame_rate / 30)):
            self.current_wave_index += 1
            self.frame_counter = 0

    def draw_alert(self, surface):
        # Use the count match minigame to handle ready sprite drawing via AnimatedSprite
        self.count_match.draw(surface)

    def draw_charge(self, surface):
        # Use the count match minigame to handle count sprite drawing via AnimatedSprite
        self.count_match.draw(surface)

    def draw_attack_move(self, surface):
        self.draw_pets(surface)
        for wave in self.attack_waves:
            for sprite, x, y in wave:
                if x < runtime_globals.SCREEN_WIDTH - (90 * runtime_globals.UI_SCALE):
                    blit_with_cache(surface, sprite, (x, y))

    def draw_result(self, screen):
        pets = self.pets
        pet = pets[0]
        hits = self.super_hits.get(pet, 0)
        
        # Completely disable count_match during result phase to prevent interference
        if self.count_match:
            self.count_match.set_phase(None)
        
        # CRITICAL: Force stop any manual countdown mode and reset AnimatedSprite state
        self.animated_sprite.stop()
        
        # Set up result animation based on hit count
        if not self.animated_sprite.is_animation_playing():
            duration = combat_constants.RESULT_SCREEN_FRAMES / constants.FRAME_RATE
            
            if hits == 5:
                self.animated_sprite.play_megahit(duration)
            elif hits < 2:
                self.animated_sprite.play_bad(duration)
            elif hits < 4:
                self.animated_sprite.play_good(duration)
            else:
                self.animated_sprite.play_great(duration)
        
        # Draw the animated sprite
        self.animated_sprite.draw(screen)
        
        # Trophy notification for megahit
        if hits == 5:
            self.draw_trophy_notification(screen, quantity=1)

    def check_victory(self):
        """Apply training results and return to game."""
        return self.super_hits.get(self.pets[0], 0) > 1

    def check_and_award_trophies(self):
        """Award trophy if super_hits reaches maximum (5)"""
        if self.super_hits.get(self.pets[0], 0) == 5:
            for pet in self.pets:
                pet.trophies += 1
            runtime_globals.game_console.log(f"[TROPHY] Count training perfect score achieved! Trophy awarded.")

    # ...existing code...
    def get_attack_count(self):
        """Outcome level 0-3 from the super-hit count.

        The Pendulum Color manual's own grading: a Megahit is five hits,
        three or four is the next band down, two is the lowest win and
        anything under that is a failed training.
        """
        hits = self.super_hits.get(self.pets[0], 0)
        if hits >= 5:
            return 3
        if hits >= 3:
            return 2
        if hits >= 2:
            return 1
        return 0
