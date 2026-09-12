#=====================================================================
# ExciteTraining (Simple Strength Bar Training)
#=====================================================================

import pygame
from core import game_globals, runtime_globals
from models.animation import PetFrame
from training.training import Training
from ui.ui_manager import UIManager
from battle import combat_constants
import core.constants as constants
from ui.minigames.xai_bar import XaiBar
from utils.pygame_utils import blit_with_cache
from utils.scene_utils import change_scene

class ExciteTraining(Training):
    """
    Excite training mode where players build up strength by holding a bar.
    """

    def __init__(self, ui_manager: UIManager) -> None:
        super().__init__(ui_manager)
        self.xaibar = XaiBar(10 * runtime_globals.UI_SCALE, runtime_globals.SCREEN_HEIGHT // 2 - (18 * runtime_globals.UI_SCALE), game_globals.xai, self.pets[0])
        self.xaibar.start()
        # Remove separate sprite assignments; use self._sprite_cache from base class

    def _do_xaibar_stop(self):
        """Freeze the bar; the phase advances after its 0.5s result hold."""
        runtime_globals.game_sound.play("menu")
        self.xaibar.stop()
        runtime_globals.game_console.log(f"XaiBar phase ended strength {self.xaibar.selected_strength}.")

    def _finish_xaibar_phase(self):
        self.phase = "wait_attack"
        self.frame_counter = 0
        self.prepare_attacks()

    def update_charge_phase(self):
        # After stopping, linger half a second so the landed color is visible
        if getattr(self.xaibar, 'stopped', False):
            if self.xaibar.is_finished():
                self._finish_xaibar_phase()
            return

        self.xaibar.update()
        # Auto-stop after the time limit
        if self.frame_counter > int(30 * 3 * (constants.FRAME_RATE / 30)):
            self.xaibar.stop()
            runtime_globals.game_console.log(f"XaiBar phase ended strength {self.xaibar.selected_strength}.")

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

    def check_victory(self):
        """Apply training results and return to game."""
        return self.xaibar.selected_strength > 0

    def check_and_award_trophies(self):
        """Award trophy if strength reaches maximum (3)"""
        if self.xaibar.selected_strength == 3:
            for pet in self.pets:
                pet.trophies += 1
            runtime_globals.game_console.log(f"[TROPHY] Excite training perfect score achieved! Trophy awarded.")

    def draw_charge(self, surface):
        self.xaibar.draw(surface)
        self.draw_pets(surface, PetFrame.IDLE1)

    def draw_attack_move(self, surface):
        self.draw_pets(surface)
        for wave in self.attack_waves:
            for sprite, x, y in wave:
                if x < runtime_globals.SCREEN_WIDTH - (90 * runtime_globals.UI_SCALE):
                    blit_with_cache(surface, sprite, (x, y))

    def draw_result(self, surface):
        strength = self.xaibar.selected_strength
        
        # Use AnimatedSprite component with predefined result animations
        if not self.animated_sprite.is_animation_playing():
            duration = combat_constants.RESULT_SCREEN_FRAMES / constants.FRAME_RATE
            
            # Choose which result animation to play based on strength
            if strength == 0:
                self.animated_sprite.play_bad(duration)
            elif strength == 1:
                self.animated_sprite.play_good(duration)
            elif strength == 2:
                self.animated_sprite.play_great(duration)
            else:
                self.animated_sprite.play_megahit(duration)
        
        # Draw the animated sprite
        self.animated_sprite.draw(surface)

        # Trophy notification on max
        if strength == 3:
            self.draw_trophy_notification(surface)

    def prepare_attacks(self):
        """Prepare each pet's five attacks, from that pet's own table row.

        The Xai bar is the Digital Monster X's charge, so this plays the
        **DMX's** measured table -- read for each Digimon's own stage and
        level, not one row shared by the party. The four hardcoded rows this
        replaces (`[5, 4, 5, 4, 4]` for a full bar, and so on down) were the
        same for a Baby II and an Omnimon alike, and were not rows the device
        has: a real Baby II never throws a strong attack at all, let alone
        two criticals.
        """
        self.attack_phase = 0
        self.attack_waves = [[] for _ in range(5)]
        pets = self.pets
        total_pets = len(pets)

        available_height = runtime_globals.SCREEN_HEIGHT
        spacing = min(available_height // total_pets, runtime_globals.OPTION_ICON_SIZE + (20 * runtime_globals.UI_SCALE))
        start_y = (runtime_globals.SCREEN_HEIGHT - (spacing * total_pets)) // 2

        # The bar already reports 0-3, which is the wire's own Bad / Good /
        # Great / Excellent -- so it is the charge the table is keyed on.
        charge = self.xaibar.selected_strength

        # A wave slides the critical in if ANY pet crits in it, so the kinds
        # are merged across the party rather than taken from one row.
        wave_kinds = [0] * 5

        s = runtime_globals.UI_SCALE
        for i, pet in enumerate(pets):
            main_sprite = self.get_attack_sprite(pet, pet.atk_main)
            if not main_sprite:
                continue
            pattern = self.line_pattern(pet, charge, "DMX")
            for j, kind in enumerate(pattern[:5]):
                wave_kinds[j] = max(wave_kinds[j], kind)
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

        # Store wave kinds for per-wave slide animation
        self.attack_wave_kinds = wave_kinds

    def get_attack_count(self):
        # The Xai bar already reports 0-3, which is exactly the Digital
        # Monster X's Bad / Good / Great / Excellent.
        strength = self.xaibar.selected_strength
        if strength < 1:
            return 0
        elif strength < 3:
            return 2
        else:
            return 3

    def handle_event(self, event):
        event_type, event_data = event

        if self.phase == "alert":
            return

        if event_type in ["A", "LCLICK"]:
            if self.phase == "charge":
                self._do_xaibar_stop()
        elif self.phase in ["wait_attack", "attack_move", "impact"] and event_type in ["B", "START"]:
            runtime_globals.game_sound.play("cancel")
            self.animated_sprite.stop()
            self.phase = "result"
        elif self.phase == "charge" and event_type == "B":
            runtime_globals.game_sound.play("cancel")
            change_scene("game")
