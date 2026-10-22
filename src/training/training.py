#=====================================================================
# Training (Base Class for All Training Modes)
#=====================================================================
import pygame

from ui.ui_constants import TEXT_FONT
from core import game_globals, runtime_globals
from models.animation import PetFrame
from ui.ui_manager import UIManager
from ui.components.animated_sprite import AnimatedSprite
from battle import combat_constants
import core.constants as constants
from utils.pet_utils import distribute_pets_evenly, get_training_targets
from utils.sprite_utils import snap_pet_sprite_size
from utils.pygame_utils import blit_with_cache, blit_with_shadow, load_attack_sprites, load_crit_attack_sprites, module_attack_sprites, module_crit_attack_sprites
from utils.scene_utils import change_scene
from models.game_quest import QuestType
from utils.quest_event_utils import update_quest_progress
from utils.module_utils import get_module


# Attack-prep timeline lives in battle.combat_constants and is shared with the
# battle encounter so training and battle stay visually consistent. Re-export
# under their old names for any subclass that imports them directly.
from battle.combat_constants import (
    ATTACK_PREP_BASE_FRAMES,
    compute_attack_anim_state,
)

TRAINING_READY_SOUND = "training_ready"
#: The currency screen, after the result, stays as long as the result does.
CURRENCY_SCREEN_FRAMES = combat_constants.RESULT_SCREEN_FRAMES


class Training:
    """
    Training mode where players build up strength by holding a bar.

    Every minigame runs the same phases: ``alert`` (READY, its sound),
    ``charge`` (the minigame itself), the attack phases where it has them
    (``wait_attack``, ``attack_move``, ``impact``), ``result`` (BAD, GOOD,
    GREAT or EXCELLENT), and ``currency``, which shows the pets side by side
    with what the training earned in their modules' currencies. A training
    that earned nothing skips it.
    """

    def __init__(self, ui_manager: UIManager) -> None:
        self.ui_manager = ui_manager
        self.phase = "alert"
        self.frame_counter = 0

        self.attack_positions = []
        self.attack_phase = 1
        self.attack_waves = []
        self.current_wave_index = 0
        self.flash_frame = 0
        self.impact_counter = 0
        self.attacks_prepared = False
        self.phase2_reached = False

        # Animated sprite component for full-screen animations
        self.animated_sprite = AnimatedSprite(ui_manager)

        # Pet sprite caching for training display
        self._pet_sprite_cache = {}
        self.pet_state = None

        # Load only the trophy sprite since it's not handled by AnimatedSprite
        self.trophy_sprite = self.ui_manager.load_sprite_integer_scaling(name="Trophies", prefix="Status")

        self.background_color = (0, 0, 0)
        self.flash_color = (255, 216, 0)

        self.attack_sprites = load_attack_sprites()
        self.crit_attack_sprites = load_crit_attack_sprites()
        self._alert_anim_started = False
        self._impact_anim_started = False
        self._ready_sound_triggered = False
        self._ready_sound_started = False
        self._ready_sound_fallback = False
        self.alert_duration_frames = combat_constants.ALERT_DURATION_FRAMES

        self.pets = get_training_targets()
        self.module_attack_sprites = {}
        self.module_crit_attack_sprites = {}
        for pet in self.pets:
            self.module_attack_sprites[pet.module] = module_attack_sprites(pet.module)
            self.module_crit_attack_sprites[pet.module] = module_crit_attack_sprites(pet.module)

        # Crit-slide eligibility flags (set by subclasses in prepare_attacks).
        self.special_attack_active = False
        self.attack_wave_kinds = []
        # True during the 35-frame attack-prep window (idle → slide/jump-back →
        # move-forward → TRAIN2). False once the shot has fired and the sprite
        # is flying. Re-armed when the next wave begins.
        self._wave_in_prep = False
        self._costs_paid = False

    def pay_training_costs(self):
        """Charge each pet that plays this training its module's training cost
        (GamePet.pay_training_cost: the battle cost, where the module says
        training costs the same). Once a play: the training scene calls it as
        the play starts; a minigame that narrows `pets` (the iC's) calls it
        itself once they are known, and the scene's call is then a no-op."""
        if getattr(self, "_costs_paid", False):
            return
        self._costs_paid = True
        from utils.pet_utils import pay_training_cost
        for pet in getattr(self, "pets", None) or []:
            pay_training_cost(pet)

    def _is_dot_pet(self, pet):
        """Return True if this pet is currently rendered using dot sprites."""
        enable_old = getattr(game_globals.configuration, 'enable_old_sprites', False)
        if not enable_old:
            return False
        module = get_module(pet.module)
        if module is None:
            return False
        primary = getattr(module, 'primary_sprite_format', 'Color')
        secondary = getattr(module, 'secondary_sprite_format', 'HD')
        return primary == 'Dot' or secondary == 'Dot'

    def get_attack_sprite(self, pet, attack_id):
        """
        Get attack sprite for a pet, preferring module-specific sprites over defaults.
        Dot variants are selected only for pets currently rendered as dot (enable_old + Dot format).
        """
        is_dot = self._is_dot_pet(pet)

        if pet.module in self.module_attack_sprites:
            module_dict = self.module_attack_sprites[pet.module]
            if is_dot:
                dot_sprite = module_dict.get(f"{attack_id}_dot")
                if dot_sprite:
                    return dot_sprite
            sprite = module_dict.get(str(attack_id))
            if sprite:
                return sprite

        if is_dot:
            dot_sprite = self.attack_sprites.get(f"{attack_id}_dot")
            if dot_sprite:
                return dot_sprite
        return self.attack_sprites.get(str(attack_id))

    def get_crit_attack_sprite(self, pet, attack_id):
        """
        Get a critical-attack sprite for a critical hit.
        Priority: module-specific atk_crit folder → global assets/atk_crit folder.
        Returns None if nothing found — callers should fall back to normal atk + scale2x.
        Dot variants are selected only for pets currently rendered as dot.
        """
        is_dot = self._is_dot_pet(pet)

        crit_dict = self.module_crit_attack_sprites.get(pet.module, {})
        if is_dot:
            dot_sprite = crit_dict.get(f"{attack_id}_dot")
            if dot_sprite:
                return dot_sprite
        sprite = crit_dict.get(str(attack_id))
        if sprite:
            return sprite

        if is_dot:
            dot_sprite = self.crit_attack_sprites.get(f"{attack_id}_dot")
            if dot_sprite:
                return dot_sprite
        return self.crit_attack_sprites.get(str(attack_id))

    def _combine_sprites(self, sprite, offsets):
        """Combine a sprite rendered at multiple offsets into a single surface."""
        if len(offsets) == 1:
            return sprite.copy()
        sw, sh = sprite.get_width(), sprite.get_height()
        min_ox = min(o[0] for o in offsets)
        min_oy = min(o[1] for o in offsets)
        max_ox = max(o[0] for o in offsets)
        max_oy = max(o[1] for o in offsets)
        width = int(max_ox - min_ox) + sw
        height = int(max_oy - min_oy) + sh
        combined = pygame.Surface((width, height), pygame.SRCALPHA).convert_alpha()
        for ox, oy in offsets:
            combined.blit(sprite, (int(ox - min_ox), int(oy - min_oy)))
        return combined

    #: Where the sprites of a multi-shot attack sit relative to each other.
    def _shot_offsets(self, count):
        s = runtime_globals.UI_SCALE
        return [(0, 0), (-int(20 * s), -int(10 * s)),
                (-int(40 * s), int(10 * s))][:count]

    def line_pattern(self, pet, charge, protocol):
        """The five attacks *pet* really throws at this charge, on *protocol*.

        A training minigame belongs to a device line -- the Xai bar is the
        DMX's and Count Match Z the Pendulum Z's -- so it plays that line's
        table, read for this pet's own stage and level. The four hardcoded
        rows this replaces were the same for every Digimon in the party, so a
        Baby II and an Omnimon trained identically, and neither threw
        anything its device would have thrown.
        """
        from battle.sim.battle_utils import get_attack_pattern
        try:
            level = int(getattr(pet, "level", 1) or 1)
        except (TypeError, ValueError):
            level = 1
        return get_attack_pattern(level, charge, protocol,
                                  stage=getattr(pet, "stage", None))

    def ladder_sprite(self, pet, value):
        """The sprite a pattern value draws, and whether it is the critical.

        The five attack types are two ladders crossed: **a weak shot draws
        `atk_main` and a strong one `atk_alt`**, and each goes out once or
        twice -- 1 weak single, 2 strong single, 3 weak double, 4 strong
        double, 5 the critical. That is the same ladder
        `BattleEncounter._ladder_shot` draws, and the copy this replaces had
        2 and 3 the other way round, so a strong single drew as a weak double
        and a weak double as a strong single. It went unseen because training
        threw made-up rows that no table had to agree with.

        A pet with no `atk_alt` cannot tell the strong shots apart by sprite,
        so it tells them apart by count -- the JSON's own fallbacks, which do
        collide 2 with 3.

        `atk_alt_2` indexes the **crit** bank and not the ordinary one, so an
        id with nothing behind it drops to the ladder's own answer at double
        size rather than naming an unrelated ordinary shot.
        """
        main = self.get_attack_sprite(pet, getattr(pet, "atk_main", 0))
        if not main:
            return None, False
        alt_id = getattr(pet, "atk_alt", 0) or 0
        alt = self.get_attack_sprite(pet, alt_id) if alt_id > 0 else None
        alt2_id = getattr(pet, "atk_alt_2", 0) or 0

        if value >= 5:
            crit = (self.get_crit_attack_sprite(pet, alt2_id)
                    if alt2_id > 0 else None)
            if crit:
                return crit, True
            return pygame.transform.scale2x(alt or main), True
        if value == 4:
            if alt:
                return self._combine_sprites(alt, self._shot_offsets(2)), False
            return self._combine_sprites(main, self._shot_offsets(3)), False
        if value == 3:
            return self._combine_sprites(main, self._shot_offsets(2)), False
        if value == 2:
            if alt:
                return alt, False
            return self._combine_sprites(main, self._shot_offsets(2)), False
        return main, False

    def _has_special_frame(self, pet):
        """Check if a pet has a valid SPECIAL frame (PetFrame.SPECIAL = 15)."""
        sprite_list = runtime_globals.pet_sprites.get(pet)
        if sprite_list and len(sprite_list) > PetFrame.SPECIAL.value:
            return sprite_list[PetFrame.SPECIAL.value] is not None
        return False

    def _get_pet_module(self, pet):
        """Get the GameModule object for a pet."""
        return get_module(pet.module)

    def _is_critical_attack(self, pet, anim_hits):
        """Check if this attack should use the special/critical animation."""
        module = self._get_pet_module(pet)
        if not module:
            return False
        return (anim_hits >= 5 and 
                getattr(module, 'enable_special_attack_sprite', False) and 
                self._has_special_frame(pet))

    def update(self):
        # Update animated sprite component
        self.animated_sprite.update()

        if self.phase == "alert":
            self.update_alert_phase()
        elif self.phase == "charge":
            self.update_charge_phase()
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

    def update_alert_phase(self):
        if not self._ready_sound_triggered:
            sound_duration = runtime_globals.game_sound.get_duration(TRAINING_READY_SOUND)
            if sound_duration > 0:
                self.alert_duration_frames = max(
                    1,
                    int(round(sound_duration * game_globals.configuration.frame_rate)),
                )

            channel = runtime_globals.game_sound.play(TRAINING_READY_SOUND)
            self._ready_sound_triggered = True

            # Muted audio or an unavailable mixer has no real playback start to
            # observe. Keep the visual ready phase at the asset's duration.
            if channel is None:
                self._ready_sound_started = True
                self._ready_sound_fallback = True
                self.frame_counter = 0

        if not self._ready_sound_started:
            if runtime_globals.game_sound.is_playing(TRAINING_READY_SOUND):
                # Mixer startup may lag behind Sound.play(). Begin both the
                # alert counter and its visual only after playback is active.
                self._ready_sound_started = True
                self.frame_counter = 0
            else:
                self.frame_counter = 0
                return

        if (
            not self._ready_sound_fallback
            and not runtime_globals.game_sound.is_playing(TRAINING_READY_SOUND)
        ):
            self._finish_alert_phase()
            return

        if self.frame_counter >= self.alert_duration_frames:
            self._finish_alert_phase()

    def _finish_alert_phase(self):
        runtime_globals.game_sound.stop(TRAINING_READY_SOUND)
        self.animated_sprite.stop()
        self.phase = "charge"
        self.frame_counter = 0
        self.bar_timer = pygame.time.get_ticks()

    def update_charge_phase(self):
        pass

    def update_wait_attack_phase(self):
        """20-frame idle pause between charge and the first attack burst.

        Applies uniformly to wave-based modes (count/count_z/excite) and
        single-shot modes (dummy/shake/count_classic/mogera). Pets stay in
        IDLE1 for the duration; the per-wave prep inside ``attack_move`` then
        plays the full pre-shot animation (slide/jump → forward → TRAIN2).
        """
        if self.frame_counter >= combat_constants.WAIT_ATTACK_READY_FRAMES:
            self.phase = "attack_move"
            self.frame_counter = 0
            self._wave_in_prep = True

    def update_attack_move_phase(self):
        """Run the per-burst animation prep, then defer to ``move_attacks``.

        Wave-based modes get one prep window per wave (re-armed when
        ``move_attacks`` advances ``current_wave_index``). Single-shot modes
        get one prep window before their first sprite begins moving and then
        run as before.
        """
        if self._wave_in_prep:
            if self.frame_counter >= self._prep_total_frames():
                self._wave_in_prep = False
                self.frame_counter = 0
                # A charge too weak to fire queues no shot at all (dummy, shake
                # and count_classic at 0 attacks): nothing would ever reach the
                # target, so the phase waited forever. Straight to the result.
                if not self.attack_waves and not self.attack_positions:
                    self.phase = "result"
                    return
                # Shot fires NOW — play the attack sound regardless of subclass
                # so single-shot modes (dummy/shake/count_classic/mogera) get it
                # too. Adventure mode keeps its silent shot in battle_encounter.
                runtime_globals.game_sound.play("attack")
            return

        # All waves done (wave-based) — let move_attacks transition to result.
        if self.attack_waves and self.current_wave_index >= len(self.attack_waves):
            self.move_attacks()
            return

        prev_idx = self.current_wave_index
        self.move_attacks()
        if (self.attack_waves
                and self.current_wave_index != prev_idx
                and self.current_wave_index < len(self.attack_waves)):
            self._wave_in_prep = True
            # Waves after the first skip the idle lead-in of the prep window
            # so the bursts chain faster. Crit waves keep the full timeline —
            # the SPECIAL slide-in starts inside the skipped region.
            if not self._is_current_wave_crit():
                self.frame_counter = int(
                    combat_constants.JUMP_START_F * (constants.FRAME_RATE / 30))

    def _prep_total_frames(self):
        """Total frames in the per-wave prep window, scaled to the active FPS."""
        return int(ATTACK_PREP_BASE_FRAMES * (constants.FRAME_RATE / 30))

    def _is_current_wave_crit(self):
        """True if the current wave should trigger the special slide-in."""
        idx = self.current_wave_index
        return (
            self.special_attack_active
            and idx < len(self.attack_wave_kinds)
            and self.attack_wave_kinds[idx] == 5
        )

    def _compute_pet_attack_anim(self, pet, is_crit_wave):
        """Resolve a pet's prep-frame state at the current ``frame_counter``.

        Thin training-side adapter around the shared timeline in
        ``combat_constants.compute_attack_anim_state``. Translates the abstract
        ``slide_progress`` into the concrete on-screen slide x for the
        right-anchored pet roster.

        Returns ``(frame_enum, forward_offset, jump_offset, slide_x_or_None)``.
        """
        fps_scale = constants.FRAME_RATE / 30.0
        f = self.frame_counter / fps_scale if fps_scale > 0 else float(self.frame_counter)

        frame, fwd, jmp, slide_progress = compute_attack_anim_state(
            f, is_crit_wave, self._has_special_frame(pet)
        )
        if slide_progress is None:
            return frame, fwd, jmp, None

        sprite_w = runtime_globals.OPTION_ICON_SIZE * 2
        start_x = float(runtime_globals.SCREEN_WIDTH - sprite_w * 3 // 4)
        target_x = float(
            runtime_globals.SCREEN_WIDTH
            - sprite_w
            - int(2 * runtime_globals.UI_SCALE)
        )
        slide_x = start_x + (target_x - start_x) * slide_progress
        return frame, fwd, jmp, int(slide_x)

    def update_impact_phase(self):
        self.flash_frame += 1
        if self.flash_frame >= combat_constants.IMPACT_DURATION_FRAMES:
            self.animated_sprite.stop()
            self.phase = "result"
            self.frame_counter = 0

    def update_result_phase(self):
        if self.frame_counter >= combat_constants.RESULT_SCREEN_FRAMES:
            self.finish_training()

    def update_currency_phase(self):
        if self.frame_counter >= CURRENCY_SCREEN_FRAMES:
            self.finish_training()

    def move_attacks(self):
        pass

    def finish_training(self):
        """The result is over (or skipped): apply it, then show the currency
        it earned before leaving -- or leave at once when it earned none.
        From the currency screen, leave."""
        if getattr(self, "_results_applied", False):
            self.leave_training()
            return
        self._results_applied = True
        self.earnings = self.apply_training_results() or []
        if self.earnings:
            self.animated_sprite.stop()
            self.phase = "currency"
            self.frame_counter = 0
        else:
            self.leave_training()

    def apply_training_results(self):
        """Apply the outcome: the sound, the quest, trophies, each pet's
        training and the module currencies. Returns what was paid,
        ``[(module name, currency name, amount), ...]``."""
        won = self.check_victory()
        if won:
            runtime_globals.game_sound.play("attack_fail")

            # Update TRAINING quest progress when training is won
            update_quest_progress(QuestType.TRAINING, 1)
        else:
            runtime_globals.game_sound.play("fail")

        # Check for trophy conditions and award trophies
        self.check_and_award_trophies()

        results = []
        for pet in self.pets:
            pet_won, grade = self.won_for(pet, won), self.grade_for(pet)
            pet.finish_training(pet_won, grade=grade, phase2=self.phase2_reached,
                                anguirus=self.anguirus_for(pet))
            results.append((pet, pet_won, grade))

        # Module currencies: each module that had a pet in the training is
        # paid once, for the best outcome among its pets.
        from utils.currency_utils import pay_earnings, training_earnings
        return pay_earnings(training_earnings(results))

    def leave_training(self):
        """Back to the game, once: the scene changes on the next frame, and
        the phase timer would call again until it does."""
        if getattr(self, "_left", False):
            return
        self._left = True
        distribute_pets_evenly()
        change_scene("game")

    def grade_for(self, pet):
        """The 0-3 outcome *pet* is credited with. Shared by the whole party
        unless a mode throws each pet its own row (Count Bar)."""
        return self.get_attack_count()

    def anguirus_for(self, pet):
        """Whether *pet* trained with Anguirus (the PENGZ Count Match's every
        fifth training), which pays its own G-Cells."""
        return False

    def won_for(self, pet, won):
        """Whether *pet* succeeded; the session's verdict unless a mode grades
        each pet on its own row."""
        return won

    def _any_pet_shows_trophies(self):
        """Whether any pet in this session is on a device with a trophy meter.

        Trophies are a per-device stat, declared through visible_stats the same
        way the status screen decides what to show. Training a pet from a
        device that has no trophies used to flash a "+1 trophy" anyway, which
        promised a reward the player can never see.
        """
        if not hasattr(self, "_shows_trophies"):
            from utils.module_utils import get_module
            shows = False
            for pet in self.pets:
                module = get_module(getattr(pet, "module", None))
                stats = getattr(module, "visible_stats", None) or []
                if any("trophies" in str(s).lower() for s in stats):
                    shows = True
                    break
            self._shows_trophies = shows
        return self._shows_trophies

    def draw_trophy_notification(self, surface, quantity=1):
        if quantity > 0 and self._any_pet_shows_trophies():
            """Draw a small trophy icon with +1 in the bottom right corner"""
            from utils.asset_utils import font_load
            trophy_size = int(24 * runtime_globals.UI_SCALE)
            font = font_load(TEXT_FONT, int(24 * runtime_globals.UI_SCALE))
            plus_text = font.render(f"+{quantity}", True, constants.FONT_COLOR_YELLOW)

            # Draw trophy icon in bottom right
            trophy_x = runtime_globals.SCREEN_WIDTH - trophy_size - plus_text.get_width() - int(4 * runtime_globals.UI_SCALE)
            trophy_y = runtime_globals.SCREEN_HEIGHT - trophy_size
            blit_with_shadow(surface, self.trophy_sprite, (trophy_x, trophy_y))
            # Draw +1 text next to trophy
            
            text_x = trophy_x + trophy_size + int(2 * runtime_globals.UI_SCALE)
            text_y = trophy_y + int(4 * runtime_globals.UI_SCALE)
            blit_with_shadow(surface, plus_text, (text_x, text_y))

    def draw(self, screen: pygame.Surface):
        if self.phase == "alert":
            # Do not reveal or advance READY before the delayed mixer playback
            # has actually begun. Muted/unavailable audio uses the timed fallback.
            if self._ready_sound_started:
                self.draw_alert(screen)
        elif self.phase == "charge":
            self.draw_charge(screen)
        elif self.phase == "wait_attack":
            self.draw_attack_ready(screen)
        elif self.phase == "attack_move":
            self.draw_attack_move(screen)
        elif self.phase == "impact":
            self.draw_impact(screen)
        elif self.phase == "result":
            self.draw_result(screen)
        elif self.phase == "currency":
            self.draw_currency(screen)

    def _init_pet_sprite_cache(self):
        """
        Pre-scales all pet sprites for each frame_enum and caches them.
        Also pre-scales the SPECIAL frame at 2× width for the critical-attack
        entrance animation.
        """
        self._pet_sprite_cache = {}
        self._special_sprite_cache = {}  # pet → Surface at (sprite_size*2, sprite_size)
        # Pixel-perfect display size: largest ladder step (16/32/48*k) that
        # fits the OPTION_ICON_SIZE slot; the offset centers the sprite when
        # the slot itself isn't a ladder size.
        self._pet_sprite_size = snap_pet_sprite_size(runtime_globals.OPTION_ICON_SIZE)
        self._pet_slot_offset = (runtime_globals.OPTION_ICON_SIZE - self._pet_sprite_size) // 2
        sprite_size = self._pet_sprite_size
        for pet in self.pets:
            self._pet_sprite_cache[pet] = {}
            frames = runtime_globals.pet_sprites.get(pet, [])
            for frame_enum in PetFrame:
                if frame_enum.value >= len(frames) or frames[frame_enum.value] is None:
                    self._pet_sprite_cache[pet][frame_enum] = None
                    continue
                sprite = frames[frame_enum.value]
                scaled_sprite = pygame.transform.scale(sprite, (sprite_size, sprite_size))
                self._pet_sprite_cache[pet][frame_enum] = scaled_sprite

            # Pre-scale SPECIAL frame at double width for the slide-in animation
            special_idx = PetFrame.SPECIAL.value
            special_raw = frames[special_idx] if special_idx < len(frames) else None
            if special_raw is not None:
                self._special_sprite_cache[pet] = pygame.transform.scale(
                    special_raw, (sprite_size * 2, sprite_size)
                )
            else:
                self._special_sprite_cache[pet] = None

    def draw_pets(self, surface, frame_enum=None):
        """Draw the pet roster.

        ``frame_enum`` controls the sprite frame in non-prep contexts. If
        omitted (``None``):
          * during the attack_move post-prep window (sprite is flying), pets
            hold ``TRAIN2`` at the rest position;
          * elsewhere they show ``IDLE1``.
        Subclasses that want a specific pose during charge or after the shot
        (e.g. single-shot modes alternating ``ATK1``/``ATK2``) pass it
        explicitly.
        """
        current_pets = tuple(self.pets)
        if (not hasattr(self, '_pet_sprite_cache')
                or not hasattr(self, '_cached_pets_tuple')
                or self._cached_pets_tuple != current_pets):
            self._init_pet_sprite_cache()
            self._cached_pets_tuple = current_pets

        in_attack_prep = (self.phase == "attack_move" and self._wave_in_prep)
        is_crit_wave = in_attack_prep and self._is_current_wave_crit()

        if frame_enum is None:
            frame_enum = (PetFrame.TRAIN2 if self.phase == "attack_move"
                          else PetFrame.IDLE1)
        self.pet_state = frame_enum

        total_pets = len(self.pets)
        available_height = runtime_globals.SCREEN_HEIGHT
        spacing = min(available_height // total_pets,
                      runtime_globals.OPTION_ICON_SIZE + int(20 * runtime_globals.UI_SCALE))
        start_y = (runtime_globals.SCREEN_HEIGHT - (spacing * total_pets)) // 2
        base_x = (runtime_globals.SCREEN_WIDTH
                  - runtime_globals.OPTION_ICON_SIZE
                  - int(16 * runtime_globals.UI_SCALE))
        ui_scale = runtime_globals.UI_SCALE

        slot_off = self._pet_slot_offset
        for i, pet in enumerate(self.pets):
            y_base = start_y + i * spacing

            if in_attack_prep:
                pet_frame, fwd, jmp, slide_x = self._compute_pet_attack_anim(pet, is_crit_wave)
                if slide_x is not None:
                    special_sprite = self._special_sprite_cache.get(pet)
                    if special_sprite is not None:
                        blit_with_cache(surface, special_sprite, (slide_x, y_base + slot_off))
                        continue
                pet_sprite = (self._pet_sprite_cache[pet].get(pet_frame)
                              or self._pet_sprite_cache[pet].get(PetFrame.IDLE1))
                x = base_x + int(fwd * ui_scale)
                y = y_base - int(jmp * ui_scale)
            else:
                pet_sprite = (self._pet_sprite_cache[pet].get(frame_enum)
                              or self._pet_sprite_cache[pet].get(PetFrame.IDLE1))
                x = base_x
                y = y_base

            if pet_sprite is None:      # no art for this pet yet: skip it, never stop the minigame
                continue
            blit_with_cache(surface, pet_sprite, (x + slot_off, y + slot_off))

    def draw_alert(self, screen):
        # Use AnimatedSprite component with predefined ready animation
        if not self._alert_anim_started:
            # Start the ready animation once
            duration = self.alert_duration_frames / game_globals.configuration.frame_rate
            self.animated_sprite.play_ready(duration)
            self._alert_anim_started = True
        
        # Only draw if still playing (don't draw after update_alert_phase stopped it)
        if self.animated_sprite.is_animation_playing():
            self.animated_sprite.draw(screen)

    def draw_attack_ready(self, surface):
        # 20-frame idle pause; per-wave prep drives the actual pre-shot animation.
        self.draw_pets(surface, PetFrame.IDLE1)

    def draw_charge(self, surface):
        pass

    def draw_attack_move(self, surface):
        pass

    def draw_impact(self, screen):
        # Use AnimatedSprite component with predefined impact animation
        if not self._impact_anim_started:
            duration = combat_constants.IMPACT_DURATION_FRAMES / constants.FRAME_RATE
            self.animated_sprite.play_impact(duration)
            self._impact_anim_started = True
        
        if self.animated_sprite.is_animation_playing():
            self.animated_sprite.draw(screen)

    def draw_result(self, surface):
        pass

    def currency_panel(self, module_name, currency_name, amount):
        """A device's own picture of what it paid, or None for the text.
        The iC's is its "50P GET!" (training.ic_minigame.get_panel)."""
        from battle.ic_attacks import is_ic_module
        module = (getattr(runtime_globals, "game_modules", None) or {}).get(module_name)
        if is_ic_module(module):
            from training.ic_minigame import ART_DOT, DOT, get_panel
            return get_panel(amount, DOT // ART_DOT * runtime_globals.UI_SCALE)
        return None

    def _currency_lines(self):
        """What the currency screen stacks under the pets, once:
        ``[(surface, space after), ...]``."""
        if getattr(self, "_currency_lines_cache", None) is None:
            from utils.asset_utils import font_load
            from utils.currency_utils import format_amount
            scale = runtime_globals.UI_SCALE
            amount_font = font_load(TEXT_FONT, int(32 * scale))
            name_font = font_load(TEXT_FONT, int(20 * scale))
            lines = []
            for module_name, currency_name, amount in getattr(self, "earnings", []):
                panel = self.currency_panel(module_name, currency_name, amount)
                if panel is not None:
                    lines.append((panel, int(6 * scale)))
                    continue
                lines.append((amount_font.render(
                    "+" + format_amount(module_name, currency_name, amount),
                    True, constants.FONT_COLOR_YELLOW), 0))
                lines.append((name_font.render(currency_name, True, (255, 255, 255)),
                              int(6 * scale)))
            self._currency_lines_cache = lines
        return self._currency_lines_cache

    def draw_currency(self, surface):
        """Every pet that trained, side by side and happy, and under them
        what each module's currency gained: "+20P" over its name, or the
        device's own picture of it (the iC's "50P GET!")."""
        current_pets = tuple(self.pets)
        if getattr(self, "_cached_pets_tuple", None) != current_pets:
            self._init_pet_sprite_cache()
            self._cached_pets_tuple = current_pets
        scale = runtime_globals.UI_SCALE
        width = runtime_globals.SCREEN_WIDTH
        size = self._pet_sprite_size
        pad = int(8 * scale)
        lines = self._currency_lines()
        count = len(self.pets)
        text_height = sum(line.get_height() + after for line, after in lines)
        band_height = (size + pad if count else 0) + text_height + 2 * pad
        # A dark band across the screen, as the result's banners have, so it
        # reads on any background.
        y = (runtime_globals.SCREEN_HEIGHT - band_height) // 2
        band = pygame.Surface((width, band_height), pygame.SRCALPHA)
        band.fill((0, 0, 0, 170))
        surface.blit(band, (0, y))
        y += pad

        if count:
            gap = max(0, min(pad, (width - count * size) // max(1, count)))
            x = (width - (count * size + (count - 1) * gap)) // 2
            for pet in self.pets:
                frames = self._pet_sprite_cache.get(pet, {})
                sprite = frames.get(PetFrame.HAPPY) or frames.get(PetFrame.IDLE1)
                if sprite is not None:
                    blit_with_cache(surface, sprite, (x, y))
                x += size + gap
            y += size + pad

        for rendered, after in lines:
            blit_with_shadow(surface, rendered, ((width - rendered.get_width()) // 2, y))
            y += rendered.get_height() + after

    def handle_event(self, event):
        event_type, event_data = event

        if self.phase == "alert":
            return

        if self.phase == "charge" and event_type == "A":
            runtime_globals.game_sound.play("menu")
            self.strength = min(getattr(self, "strength", 0) + 1, getattr(self, "bar_level", 14))
        elif self.phase in ["wait_attack", "attack_move", "impact", "result"] and event_type in ["B", "START"]:
            self.finish_training()
        elif self.phase == "currency" and event_type in ["A", "B", "START"]:
            self.finish_training()
        elif self.phase == "charge" and event_type == "B":
            runtime_globals.game_sound.play("cancel")
            change_scene("game")
