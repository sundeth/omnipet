#=====================================================================
# RPMTraining (Rhythm Training, Digivice iC)
#=====================================================================

from training.count_bar_training import CountBarTraining
from ui.ui_manager import UIManager
from ui.minigames.rpm import RPM
from battle.sim.battle_utils import (
    get_ic_grade, get_ic_pattern, ic_rpm_target, is_dmm_megahit,
)


class RPMTraining(CountBarTraining):
    """Play one rhythm, evaluated against each training pet's preferred pace.

    The first pet owns the displayed bar meter. Other pets replay the same
    press timestamps; their result cannot be recovered from the final RPM.
    """

    def __init__(self, ui_manager: UIManager):
        super().__init__(ui_manager)
        # Reuse the attack presentation, with the first pet's rhythm meter.
        self.count_bar = RPM(ui_manager, self.pets[0] if self.pets else None)

    def update_charge_phase(self):
        # CountBarTraining's update calls get_count(), which RPM does not have.
        if self.count_bar.start_ticks is None:
            self.count_bar.start()
        self.count_bar.update()
        self.count = self.count_bar.get_rpm()
        if self.count_bar.is_time_up():
            self.phase = "wait_attack"
            self.frame_counter = 0
            self.calculate_results()
            self.prepare_attack()

    def count_ladder_sprite(self, pet, value):
        """The sprite an RPM round draws.

        1, 2 and 3 are that many `atk_main`, as on the Mini. **4 comes from
        the crit bank** (`assets/atk_crit/`), at the same id -- the iC draws
        its Hyper with a sprite of its own where the Mini scales the ordinary
        one up, and this wire has one projectile field, so the id that names
        the ordinary sprite names the crit one too
        (`protocol_constants.IC.CRIT_BANK_DAMAGE`).

        A pet with no crit sprite at that id falls back to the Mini's
        presentation rather than drawing nothing, which is what keeps this
        usable while `atk_crit/` is still being filled in.
        """
        from battle import ic_attacks
        from battle.sim import protocol_constants

        crit_at = getattr(protocol_constants.IC, "CRIT_BANK_DAMAGE", None)
        if ic_attacks.is_ic_native(pet):
            # An iC's own Digimon throws the iC's own sprites, chosen by its
            # Max Reliability flag and its weapon (battle.ic_attacks).
            import pygame
            normal, crit = ic_attacks.attack_ids(pet)
            main = self.get_attack_sprite(pet, normal)
            if not main:
                return None
            if crit_at is not None and int(value or 0) >= crit_at:
                sprite = self.get_crit_attack_sprite(pet, crit)
                return sprite if sprite is not None else pygame.transform.scale2x(main)
            return self._combine_sprites(main, self._shot_offsets(max(1, value)))
        if crit_at is not None and int(value or 0) == crit_at:
            alt2 = getattr(pet, "atk_alt_2", 0) or 0
            if alt2 > 0:
                sprite = self.get_crit_attack_sprite(pet, alt2)
                if sprite is not None:
                    return sprite
        return super().count_ladder_sprite(pet, value)

    def calculate_results(self):
        """Deal rows from the earned bars, replaying the input for each pet."""
        # Keep the displayed reading separately from each pet's earned bars.
        self.count = self.count_bar.get_rpm()
        self.patterns = {
            pet: get_ic_pattern(self.count_bar.get_bars(ic_rpm_target(pet)))
            for pet in self.pets
        }
        if self.pets:
            # The Megahit is five of the strongest shot, which is the same
            # row on both devices -- bar 10 here, count 31 on the Mini.
            self.megahit = is_dmm_megahit(self.patterns[self.pets[0]])

    def grade_for(self, pet):
        return get_ic_grade(self.patterns.get(pet, []))
