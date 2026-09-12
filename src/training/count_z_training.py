#=====================================================================
# CountMatchZTraining (Arrow-based Attribute Match Training)
#=====================================================================

import random
import pygame

from core import runtime_globals
from models.animation import PetFrame
from training.training import Training
from ui.ui_manager import UIManager
from ui.minigames.count_match_z import CountMatchZ, score_arrows
from battle import combat_constants
import core.constants as constants
from utils.pygame_utils import blit_with_cache


class CountMatchZTraining(Training):
    """
    Count Match Z training mode where players match arrows based on attribute.
    Uses the CountMatchZ minigame (arrow-based counting).
    """

    def __init__(self, ui_manager: UIManager):
        super().__init__(ui_manager)
        self.press_counter = 0
        self.start_time = 0
        #: The 0-3 each pet trains at. Not super hits -- this game has
        #: none; the arrow counter is the whole score.
        self.charge_result = {}
        self.result_text = None
        self.flash_frame = 0
        self.anim_counter = -1
        
        # Initialize the count match Z minigame with our AnimatedSprite component
        self.count_match_z = None
        pet = self.pets[0]
        self.count_match_z = CountMatchZ(self.ui_manager, pet, self.animated_sprite)

    def update(self):
        """Override base update to include minigame updates."""
        # Call parent update
        super().update()
        
        # Update minigame and sync counters
        if self.count_match_z:
            self.count_match_z.update()
            self.press_counter = self.count_match_z.get_press_counter()

    def update_charge_phase(self):
        if self.count_match_z.phase != "count":
            self.start_count_phase()
        # Use frame-rate independent timing (3 seconds)
        if self.frame_counter > int(3 * constants.FRAME_RATE):
            self.phase = "wait_attack"
            self.calculate_results()
            self.prepare_attack()

    def start_count_phase(self):
        self.phase = "charge"
        self.press_counter = 0
        
        # Set minigame to count phase
        self.count_match_z.set_phase("count")

    def handle_event(self, event):
        event_type, event_data = event

        if self.phase == "alert":
            return
        
        if self.phase == "charge" and event_type in ("Y", "SHAKE"):
            # Let the minigame handle the input
            if self.count_match_z and self.count_match_z.handle_event(event):
                self.press_counter = self.count_match_z.get_press_counter()
                
        elif self.phase in ["wait_attack", "attack_move", "impact"] and event_type in ["B", "START"]:
            # Skip to result phase
            runtime_globals.game_sound.play("cancel")
            self.animated_sprite.stop()
            self.phase = "result"
            self.frame_counter = 0
        elif self.phase == "result" and event_type in ["B", "START"]:
            self.finish_training()
    def calculate_results(self):
        """Calculate training results based on minigame result."""
        pets = self.pets
        if not pets:
            return

        # Straight off the arrow counter: the player was asked for a number
        # of arrows and either filled it or did not, and the distance from
        # that number is the whole result. One ready screen means one target
        # and so one result, shared by everyone training -- the device raises
        # one Digimon and shows one row of arrows.
        result = score_arrows(self.count_match_z.get_press_counter(),
                              self.count_match_z.pet)

        # Store strength result for result screen
        self.strength_result = result

        for p in pets:
            self.charge_result[p] = result

    def prepare_attack(self):
        """Prepare each pet's five attacks, from that pet's own table row.

        Count Match Z is the Pendulum Z's charge, so this plays the **PENZ**
        table -- its own file, sharing not a row with the DMX's -- read for
        each Digimon's stage and level. The four hardcoded rows this replaces
        were the DMX training screen's, shared by every pet in the party and
        belonging to neither device.
        """
        self.attack_phase = 0
        self.attack_waves = [[] for _ in range(5)]
        pets = self.pets
        total_pets = len(pets)
        available_height = runtime_globals.SCREEN_HEIGHT
        spacing = min(available_height // total_pets, runtime_globals.OPTION_ICON_SIZE + (20 * runtime_globals.UI_SCALE))
        start_y = (runtime_globals.SCREEN_HEIGHT - (spacing * total_pets)) // 2

        # Per-wave maximum kind across all pets -- drives crit-slide detection.
        wave_kinds_max = [0] * 5

        s = runtime_globals.UI_SCALE
        for i, pet in enumerate(pets):
            main_sprite = self.get_attack_sprite(pet, pet.atk_main)
            if not main_sprite:
                continue
            # The minigame's own 0-3 is the charge every row is keyed on.
            pattern = self.line_pattern(pet, self.charge_result.get(pet, 0), "PENZ")
            for j, kind in enumerate(pattern[:5]):
                wave_kinds_max[j] = max(wave_kinds_max[j], kind)
            if 5 in pattern and self._is_critical_attack(pet, 5):
                self.special_attack_active = True

            pet_y = start_y + i * spacing + runtime_globals.OPTION_ICON_SIZE // 2 - main_sprite.get_height() // 2
            slot_center_y = pet_y + main_sprite.get_height() // 2
            for j, kind in enumerate(pattern[:5]):
                sprite, is_crit = self.ladder_sprite(pet, kind)
                if sprite is None:
                    continue
                if is_crit:
                    # Crit sprites start at the visibility threshold rather
                    # than past it, so they stay hidden through the slide-in
                    # and only appear when move_attacks() fires them.
                    x = runtime_globals.SCREEN_WIDTH - int(90 * s)
                    y = slot_center_y - sprite.get_height() // 2
                else:
                    x = runtime_globals.SCREEN_WIDTH - runtime_globals.OPTION_ICON_SIZE - (20 * s)
                    y = pet_y
                self.attack_waves[j].append((sprite, x, y))

        # Set attack_wave_kinds to the per-wave maximum kind across all pets
        self.attack_wave_kinds = wave_kinds_max
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

        # Wait at least 10 frames (at 30fps) before next wave
        if all_off_screen and self.frame_counter >= int(4 * (constants.FRAME_RATE / 30)):
            self.current_wave_index += 1
            self.frame_counter = 0

    def draw_alert(self, surface):
        # Use the count match Z minigame to handle ready sprite drawing
        self.count_match_z.draw(surface)

    def draw_charge(self, surface):
        # Use the count match Z minigame to handle count sprite drawing
        self.count_match_z.draw(surface)

    def draw_attack_move(self, surface):
        self.draw_pets(surface)
        for wave in self.attack_waves:
            for sprite, x, y in wave:
                if x < runtime_globals.SCREEN_WIDTH - (90 * runtime_globals.UI_SCALE):
                    blit_with_cache(surface, sprite, (x, y))

    def draw_result(self, screen):
        pets = self.pets
        pet = pets[0]
        hits = self.charge_result.get(pet, 0)
        
        # Completely disable count_match_z during result phase to prevent interference
        if self.count_match_z:
            self.count_match_z.set_phase(None)
        
        # Force stop any manual countdown mode and reset AnimatedSprite state
        self.animated_sprite.stop()
        
        # Set up result animation based on strength result
        if not self.animated_sprite.is_animation_playing():
            duration = combat_constants.RESULT_SCREEN_FRAMES / constants.FRAME_RATE
            
            if hits == 3:
                self.animated_sprite.play_megahit(duration)
            elif hits == 2:
                self.animated_sprite.play_great(duration)
            elif hits == 1:
                self.animated_sprite.play_good(duration)
            else:
                self.animated_sprite.play_bad(duration)
        
        # Draw the animated sprite
        self.animated_sprite.draw(screen)
        
        # Trophy notification for megahit
        if hits == 3:
            self.draw_trophy_notification(screen, quantity=1)

    def check_victory(self):
        """Apply training results and return to game."""
        return self.charge_result.get(self.pets[0], 0) > 0

    def check_and_award_trophies(self):
        """Award trophy if strength result reaches maximum (3)"""
        if self.charge_result.get(self.pets[0], 0) == 3:
            for pet in self.pets:
                pet.trophies += 1
            runtime_globals.game_console.log(f"[TROPHY] Count Match Z training perfect score achieved! Trophy awarded.")

    def get_attack_count(self):
        """
        Determine attack count based on strength result:
          3 (megahit) -> 3
          2 (great) -> 2
          1 (good) -> 1
          0 (bad/fail) -> 0
        """
        return self.charge_result.get(self.pets[0], 0)
