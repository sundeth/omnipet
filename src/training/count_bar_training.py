#=====================================================================
# CountBarTraining (Press-count Training, Digimon Mini)
#=====================================================================

import pygame

from core import runtime_globals
from training.training import Training
from ui.ui_manager import UIManager
from ui.minigames.count_bar import CountBar
from battle.sim.battle_utils import get_dmm_grade, get_dmm_pattern, is_dmm_megahit
from battle import combat_constants
import core.constants as constants
from utils.pygame_utils import blit_with_cache


class CountBarTraining(Training):
    """
    Count Bar training: press for five seconds, and the count picks the five
    shots each pet throws, from the Digimon Mini's table.
    """

    def __init__(self, ui_manager: UIManager):
        super().__init__(ui_manager)
        self.count_bar = CountBar(ui_manager)
        self.count = 0
        #: Each pet's five rounds, already shuffled.
        self.patterns = {}
        self.megahit = False

    def update_charge_phase(self):
        if self.count_bar.start_ticks is None:
            self.count_bar.start()
        self.count_bar.update()
        self.count = self.count_bar.get_count()
        if self.count_bar.is_time_up():
            self.phase = "wait_attack"
            self.frame_counter = 0
            self.calculate_results()
            self.prepare_attack()

    def handle_event(self, event):
        event_type, event_data = event

        if self.phase == "alert":
            return

        if self.phase == "charge" and event_type == "B":
            # B (and the EXIT button, which sends it) leaves, as in Dummy.
            # RPM training is this class too.
            self.quit_charge()
        elif self.phase == "charge":
            self.count_bar.handle_event(event)
        elif self.phase in ["wait_attack", "attack_move", "impact"] and event_type in ["B", "START"]:
            # Skip to result phase
            runtime_globals.game_sound.play("cancel")
            self.animated_sprite.stop()
            self.phase = "result"
            self.frame_counter = 0
        elif self.phase == "result" and event_type in ["B", "START"]:
            self.finish_training()

    def calculate_results(self):
        """Deal each pet its own shuffled row for the shared count.

        The count is one player's presses, so it is shared; the row is each
        pet's own, read from its stage and attribute, and the order the device
        plays it in is dealt fresh every time.
        """
        self.count = self.count_bar.get_count()
        # Each pet's own column: the table is keyed on stage and attribute.
        self.patterns = {pet: get_dmm_pattern(self.count, stage=getattr(pet, "stage", None),
                                              attribute=getattr(pet, "attribute", None))
                         for pet in self.pets}
        if self.pets:
            self.megahit = is_dmm_megahit(self.patterns[self.pets[0]])

    def count_ladder_sprite(self, pet, value):
        """The sprite a Count Bar round draws.

        1, 2 and 3 are that many `atk_main`; 4 is a single `atk_alt` **at
        double size**, the same shot the battle screen draws for a Hyper
        (`BattleEncounter._count_bar_shot`). A pet with no `atk_alt` draws its
        `atk_main` at that size instead.
        """
        main = self.get_attack_sprite(pet, getattr(pet, "atk_main", 0))
        if not main:
            return None
        if value >= 4:
            alt_id = getattr(pet, "atk_alt", 0) or 0
            alt = self.get_attack_sprite(pet, alt_id) if alt_id > 0 else None
            return pygame.transform.scale2x(alt if alt else main)
        return self._combine_sprites(main, self._shot_offsets(max(1, value)))

    def prepare_attack(self):
        self.attack_phase = 0
        self.attack_waves = [[] for _ in range(5)]
        pets = self.pets
        total_pets = len(pets)
        if total_pets == 0:
            return
        available_height = runtime_globals.SCREEN_HEIGHT
        spacing = min(available_height // total_pets, runtime_globals.OPTION_ICON_SIZE + (20 * runtime_globals.UI_SCALE))
        start_y = (runtime_globals.SCREEN_HEIGHT - (spacing * total_pets)) // 2

        s = runtime_globals.UI_SCALE
        for i, pet in enumerate(pets):
            main_sprite = self.get_attack_sprite(pet, pet.atk_main)
            if not main_sprite:
                continue
            slot_center_y = start_y + i * spacing + runtime_globals.OPTION_ICON_SIZE // 2
            for j, value in enumerate(self.patterns.get(pet, [])[:5]):
                sprite = self.count_ladder_sprite(pet, value)
                if sprite is None:
                    continue
                x = runtime_globals.SCREEN_WIDTH - runtime_globals.OPTION_ICON_SIZE - (20 * s)
                y = slot_center_y - sprite.get_height() // 2
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
            if x + sprite.get_width() > 0:
                all_off_screen = False
                new_wave.append((sprite, x, y))

        self.attack_waves[self.current_wave_index] = new_wave

        # Short breather (at 30fps) before the next wave
        if all_off_screen and self.frame_counter >= int(4 * (constants.FRAME_RATE / 30)):
            self.current_wave_index += 1
            self.frame_counter = 0

    def draw_charge(self, surface):
        self.count_bar.draw(surface)

    def draw_attack_move(self, surface):
        self.draw_pets(surface)
        for wave in self.attack_waves:
            for sprite, x, y in wave:
                if x < runtime_globals.SCREEN_WIDTH - (90 * runtime_globals.UI_SCALE):
                    blit_with_cache(surface, sprite, (x, y))

    def draw_result(self, screen):
        if not self.animated_sprite.is_animation_playing():
            duration = combat_constants.RESULT_SCREEN_FRAMES / constants.FRAME_RATE
            grade = self.get_attack_count()
            if self.megahit:
                self.animated_sprite.play_megahit(duration)
            elif grade == 3:
                self.animated_sprite.play_excellent(duration)
            elif grade == 2:
                self.animated_sprite.play_great(duration)
            elif grade == 1:
                self.animated_sprite.play_good(duration)
            else:
                self.animated_sprite.play_bad(duration)

        self.animated_sprite.draw(screen)

        if self.megahit:
            self.draw_trophy_notification(screen, quantity=1)

    def check_victory(self):
        """A success is a score of 6 or more; 0-5 only sheds weight."""
        return self.get_attack_count() > 0

    def check_and_award_trophies(self):
        """Award a trophy for a Megahit."""
        if self.megahit:
            for pet in self.pets:
                pet.award_trophies(1)
            runtime_globals.game_console.log("[TROPHY] Count Bar training Megahit! Trophy awarded.")

    def get_attack_count(self):
        """Outcome level 0-3 for the result screen: the first pet's grade."""
        return self.grade_for(self.pets[0]) if self.pets else 0

    def grade_for(self, pet):
        """*pet*'s grade, from the score of its own row (`get_dmm_grade`).

        One count throws a different row at each stage, so a Baby II and an
        Ultimate trained together are graded apart.
        """
        return get_dmm_grade(self.patterns.get(pet, []))

    def won_for(self, pet, won):
        return self.grade_for(pet) > 0
