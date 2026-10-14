from datetime import datetime
import time
import pygame
import random

from core import game_globals, runtime_globals
from core import pet_stats
from models.animation import Animation, PetFrame
import core.constants as constants
from models.game_digidex import register_digidex_entry
from utils.sprite_utils import (load_pet_sprites_resolved, convert_sprites_to_list,
                                pair_right_frames, right_facing)
from models.game_poop import GamePoop
from utils.module_utils import get_module
from utils.pygame_utils import blit_with_cache, sprite_load
from utils.scene_utils import change_scene
from utils.utils_unlocks import is_unlocked, unlock_item
from utils.asset_utils import image_load
from utils.data_compat import availability as read_availability, get_data
from utils import evolution_rules, gcell_rules


#: The crossover Digital Monster Colors, for the save migration below. Each
#: ships exactly one device and it announces `COLOUR_CROSSOVER_VERSION`.
#: PENC is not among them: it numbers its releases by a map rather than an
#: offset and its `devices.json` has always carried the wire's own values.
COLOUR_CROSSOVER_MODULES = ("DMGZ", "DMH", "DMXW")

#: What a crossover announces -- one past the five, which is how a Colour
#: device says it is not one of them. Measured on a Monster Hunter edition
#: (filmed battle 44) and an Xros Wars one (battle 45).
COLOUR_CROSSOVER_VERSION = 5


def global_sleep_times():
    """The player's Settings override (sleep, wake), each a time or None.

    Settings keeps them on game_globals.configuration; reading
    game_globals.sleep_time / wake_time, as this did, found nothing, so the
    override never applied (fixed 2026-10-13).
    """
    cfg = getattr(game_globals, "configuration", None)
    return getattr(cfg, "sleep_time", None), getattr(cfg, "wake_time", None)


class GamePet:
    def __init__(self, pet_data, traited = False):
        self.hunger = self.strength = self.age = self.injuries = self.poop_count_flag = self.weight = 0
        self.event_communications = 0
        self.item_uses = {}
        self.totalWin = self.totalBattles = 0
        # The id of the accessory item the pet wears (utils.accessory_utils),
        # kept through evolutions; None for none.
        self.accessory = None
        # When a nap an item started ends (a datetime): the iC's Digi
        # Bedding sleeps the pet ten minutes. None outside such a nap.
        self.nap_until = None
        # Points from battling other devices and pets, kept through
        # evolution (utils.connect_points), and the next slot of the pet's
        # pooled-encounter rotation (utils.event_utils).
        self.connect_points = 0
        self.encounter_rotation = 0
        # The one item effect the pet has running, a Vital Bracelet BE item
        # ({"item", "targets", "amount", "until"}; utils.card_battle), and its
        # place in each card-battle event's item sequence (event id -> index).
        self.active_boost = None
        self.event_sequence = {}

        self.traited = traited
        self.shiny = False
        self.shook = False
        self.edited = False

        # Real-time gameplay timers (seconds via time.monotonic)
        _now = time.monotonic()
        self._rt_origin = _now        # Base for per-minute tick detection
        self._rt_last_minute = 0      # Last processed minute count since _rt_origin
        self._rt_last_sleep_check = _now
        self._rt_dead_start = 0.0     # When pet entered dead state (0 = not dead)
        self._last_age_date = datetime.now().date()  # Age increments at midnight
        # Countdown/countup gameplay counters (initialized properly in reset_variables)
        self._evol_minutes = 0
        self._cd_hunger = 0
        self._cd_strength = 0
        self._cd_poop = 0

        self.set_data(pet_data)
        module = get_module(self.module)
        reliability_base = getattr(module, 'reliability_base', constants.RELIABILITY_MIN)
        self.reliability = max(constants.RELIABILITY_MIN,
                               min(constants.RELIABILITY_MAX, int(reliability_base)))
        # DigiSoul DNA fed to this form, oldest first, at most
        # constants.DNA_QUEUE_SIZE (`add_dna`). An egg's DNA carries into the
        # Digimon it hatches; every other evolution starts with none.
        self.dna = []
        # Injury-rate points from items (the Digimon Twin's special foods),
        # kept across evolutions. Nothing rolls an injury from them yet.
        self.injury_rate = 0
        # Reliability's hourly cycle and unflushed-poop episode survive
        # ordinary evolutions, just like the Reliability value itself.
        self._cd_reliability = 60
        self.unflushed_poops = 0
        # Each uncleaned poop's minutes before it costs a care mistake
        # (care_poop_mistake_time), and the poops that did: Digimon World's
        # virus bar, kept through evolutions until a `virus` route spends it.
        self.poop_mistake_timers = []
        self.virus = 0
        self._reliability_sleep_call_resolved = False
        self.reset_variables()
        self.load_sprite()
        self.begin_position()

        self.state = ""
        self.set_state("idle")
        
        self.direction = -1
        self.injuries = 0
        self.move_timer = random.randint(60, 120)

        self.sleep_start_time = None
        self.sleep_timer = 0 
        self.back_to_sleep = 0

        self.dying = False

        self.level = 1
        self.experience = 0
        self.gcell_fragment = False
        self.vital_activities = []
        self.evolution_history = []  # Names of prior forms, oldest first

        self.bonus_stats = [0, 0, 0]  # HP, ATK, POWER bonuses from items

    def set_data(self, data):
        self.module = data["module"]
        self.name = data["name"]
        self.stage = data["stage"]
        self.version = data["version"]
        # The hardware protocol version is chosen when an egg is hatched. It
        # intentionally survives evolutions, whose monster data has only the
        # gameplay/evolution-line version.
        if "device_version" in data:
            self.device_version = int(data["device_version"])
        elif not hasattr(self, "device_version"):
            self.device_version = int(self.version)
        self.special = data["special"]
        self.index = data.get("index", 0)
        if self.special:
            self.special_key = data.get("special_key")
        else:
            self.special_key = None
        # Jogress routes are migrated from the old shape here, so everything
        # downstream only ever sees the current one (see utils.jogress_utils).
        from utils.jogress_utils import normalize_evolutions
        self.evolve = normalize_evolutions(data["evolve"])
        self.sleeps = data.get("sleeps")
        self.wakes = data.get("wakes")
        self.atk_main = data.get("atk_main", 0)
        self.atk_alt = data.get("atk_alt", 0)
        if self.atk_alt == 0:
            self.atk_alt = self.atk_main
        self.atk_alt_2 = data.get("atk_alt_2", 0)
        self.time = data.get("time", 0)
        self.poop_timer = data.get("poop_timer", 60)
        self.min_weight = data.get("min_weight")
        self.evol_weight = data.get("evol_weight", 0)
        self.stomach = data.get("stomach")
        self.hunger_loss = data.get("hunger_loss")
        self.strength_loss = data.get("strength_loss")
        self.power = data.get("power")
        #: The rate this Digimon's charge asks for, in the Digivice iC's own
        #: RPM. **Per Digimon, not per stage**: the iC roster gives every
        #: form a figure between 50 and 85. Sustaining a rhythm earns bars;
        #: reaching this number once does not grant Hyper x5. 0 means the
        #: module named none, and the RPM charge
        #: falls back to the playbook's stage/attribute table
        #: (`battle_utils.ic_rpm_target`) -- which is what a pet from any
        #: other module on this wire reads.
        self.rpm = data.get("rpm", 0)
        # Per-species chance (%) of an injury on a lost battle (finish_battle).
        # It was never copied from the record, so DMM never injured and the
        # iC's Digimon lost their own 5-25%.
        self.injury_probability = data.get("injury_probability", 0) or 0
        self.attribute = data.get("attribute")
        self.digisoul = data.get("digisoul", "")
        self.energy = data.get("energy")

        self.heal_doses = data.get("heal_doses", 1)
        self.hp = data.get("hp", 0)
        self.star = data.get("star", 0)
        self.attack = data.get("attack", 1)
        self.critical_turn = data.get("critical_turn", 0)

        self.condition_hearts_max = int(data.get("condition_hearts", 0))
        self.jogress_available = int(get_data(data, "jogress_available", 0))

        # Battle-only temporary evolutions (Mode Change / Xros) and availability
        # ("Normal" default; "Unobtainable" / "Friend" pets aren't hatchable).
        self.temp_evolve = data.get("temporary-evolution") or []
        self.availability = read_availability(data)

        # The Godzilla devices' scheduled encounters: when this form's
        # encounters come (a group of the module's events.json schedule) and
        # whom from (a pool of a "schedule" event). None for neither. See
        # utils.event_utils.
        self.encounter_time_group = data.get("encounter_time_group")
        self.encounter_opponent_group = data.get("encounter_opponent_group")


    def reset_variables(self):
        self.timer = 0  # Kept for animation/frame counting only
        if self.evol_weight > 0:
            self.weight = self.evol_weight
        if self.weight < self.min_weight:
            self.weight = self.min_weight
        self.dp = self.energy
        self.effort = 0
        self.sick = 0
        self.level = 1
        self.experience = 0
        # The Digimon Twin carries its battle record across an evolution while
        # resetting the training count, which is what lets a Perfect reach
        # Ultimate without fighting again.
        if not getattr(get_module(self.module), 'battle_keep_counts_on_evolution', False):
            self.win = self.battles = 0
        else:
            # Kept across an evolution, but a pet just hatched has none yet:
            # without this its first battle (and the Status screen) raised
            # AttributeError on DMM and the other modules that keep counts.
            self.win = getattr(self, "win", 0)
            self.battles = getattr(self, "battles", 0)
        self.animation_counter = self.frame_counter = self.frame_index = 0
        self.care_food_mistake_timer = self.care_strength_mistake_timer = self.care_sleep_mistake_timer = self.care_sick_mistake_timer = 0

        # Reset real-time gameplay timers (NOT _last_age_date — age persists across evolutions)
        _now = time.monotonic()
        self._rt_origin = _now
        self._rt_last_minute = 0
        self._rt_dead_start = 0.0
        self._rt_last_sleep_check = _now
        # Countdown counters: start at max, tick down 1/min, trigger & reset at 0
        self._cd_hunger = self.hunger_loss or 0
        self._cd_strength = self.strength_loss or 0
        # The poop countdown runs on through an evolution (the owner's Twin kept
        # its hourly poop minute across two, 2026-10-06); it starts fresh only
        # when the previous form had none, and never exceeds the new interval.
        if self._cd_poop > 0 and self.poop_timer:
            self._cd_poop = min(self._cd_poop, self.poop_timer)
        else:
            self._cd_poop = self.poop_timer or 0
        # Evolution count-up: starts at 0, increments 1/min, checks conditions after reaching self.time
        self._evol_minutes = 0
        # Minutes in this form, asleep or awake (the 48-hour rules), whether
        # this form has failed to evolve, and the tagged opponents it has
        # defeated (utils.evolution_rules).
        self.form_minutes = 0
        self.evolution_failed = False
        self.tag_defeats = {}
        self.special_encounter = False

        self.enemy_kills = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        self.injuries = 0
        self.starvation_counter = 0
        self.disturbance_penalty = 0
        self.overfeed_timer = 0
        self.protein_feedings = 0
        self.protein_overdose = 0
        self.shake_counter = 0
        self.pvp_wins = 0
        self.pvp_battles = 0
        
        # Death save system variables
        self.death_save_b_counter = 0
        self.death_save_shake_counter = 0
        self.death_save_immunity = 0
        self.death_cause = ""  # tracks what triggered death: injuries, sickness, hunger, strength, care_mistakes, starvation, old_age, stage_mistakes

        self.quests_completed = 0

        # Digimon Twin Event Communications. Its Perfect Conditions weigh this
        # against the win ratio, so it is pet state rather than a statistic.
        # It follows the battle record: kept across an evolution on a module
        # that keeps counts, cleared with them otherwise.
        if not getattr(get_module(self.module), 'battle_keep_counts_on_evolution', False):
            self.event_communications = 0

        # Item uses, for the evolution criteria that count them - the Twin
        # needs five Bombs for Digitamamon. Keyed by item id.
        self.item_uses = {}

        self.trophies = 0
        self.vital_values = 100
        self.overfeed = 0
        self.sleep_disturbances = 0

        module = get_module(self.module)

        if self.traited:
            self.level = module.traited_egg_starting_level

        self.use_condition_hearts = module.use_condition_hearts
        if self.use_condition_hearts:
            self.condition_hearts = self.condition_hearts_max
        self.mistakes = 0

        self.gcell_points = 0

        self._99g_triggered = False
        self.sick_type = ""
        self.burpmon_active = False

    def begin_position(self):
        self.subpixel_x = float(runtime_globals.SCREEN_WIDTH - runtime_globals.PET_WIDTH) / 2
        self.x = int(self.subpixel_x)
        # Old formula did not work well when MAX_PETS != 4:
        # self.y = (24 * runtime_globals.UI_SCALE) + (runtime_globals.SCREEN_HEIGHT - runtime_globals.PET_HEIGHT) // 2
        # New formula keeps the placement of the bottom of the sprite in the same place for most MAX_PETS as the previous
        # formula for MAX_PETS = 4. Slight offset to sprite for MAX_PETS <= 2 as to not overlap the top menu icons.
        if constants.MAX_PETS > 2:
            self.y = int(174 * runtime_globals.UI_SCALE - runtime_globals.PET_HEIGHT)
        else:
            self.y = int(190 * runtime_globals.UI_SCALE - runtime_globals.PET_HEIGHT - 5)
        self.x_range = (0, runtime_globals.SCREEN_WIDTH - runtime_globals.PET_WIDTH)

    def get_sprite(self, index):
        sprites = runtime_globals.pet_sprites.get(self)
        if sprites is None:
            # A sprite-cache reset (display or sprite settings) reloads the
            # party's art only; a pet outside the party (an arena replay's,
            # a battle's) loads its own again rather than stopping the draw.
            self.load_sprite()
            sprites = runtime_globals.pet_sprites.get(self, [])
        return sprites[index]

    def get_right_sprite(self, index):
        """Frame *index* facing right: the set's own right-facing drawing
        (``<n>R.png``), else the frame mirrored. None when it is missing."""
        frame = self.get_sprite(index)
        if frame is None:
            return None
        return right_facing(frame, runtime_globals.pet_sprites_right.get(self))

    def set_state(self, new_state, force=False):
        if self.state == "dead":
            return
        if self.state == "dying" and new_state not in ("dead", "happy2", "dying"):
            return
        if self.stage == 0 and new_state not in ("idle", "hatch"):
            return

        if self.state != new_state or force:
            self.state = new_state
            self.animation_counter = 0
            self.animation_frames = getattr(Animation, new_state.upper(), Animation.IDLE)
            self.frame_index = self.frame_counter = self.animation_counter = 0
            
            # Mark as dirty when state changes since overlays may change
            if hasattr(self, 'dirty'):
                self.dirty = True
            
            runtime_globals.game_console.log(f"{self.name} status {self.state}")

            if self.state == "nap" and self.should_sleep() and new_state != "nap":
                self.set_back_to_sleep()

            # Handle sleeping
            if new_state == "nap":
                from datetime import datetime
                self.sleep_start_time = datetime.now()
                self.sleep_timer = 0
            elif self.state == "idle":
                self.sleep_start_time = None
                self.sleep_timer = 0

    def load_sprite(self):
        """Loads animation frames for the pet using the new sprite loading utility."""
        # Get module object to access folder_path and name_format
        module_obj = get_module(self.module)
        if not module_obj:
            runtime_globals.game_console.log(f"Module {self.module} not found for pet {self.name}")
            return
        
        # Get module properties
        module_path = module_obj.folder_path
        name_format = getattr(module_obj, 'name_format', '$_dmc')
        primary_format = getattr(module_obj, 'primary_sprite_format', 'Color')
        secondary_format = getattr(module_obj, 'secondary_sprite_format', 'HD')
        
        # Load sprites using the new utility function with format parameters.
        # Capture the resolved format ("Color"/"Dot"/"HD") so draw() can pick
        # matching overlay icons (dot pets -> *_dot, HD pets -> *_hd).
        right = {}
        sprites_dict, self.sprite_format = load_pet_sprites_resolved(
            self.name,
            module_path,
            name_format,
            size=(runtime_globals.PET_WIDTH, runtime_globals.PET_HEIGHT),
            primary_sprite_format=primary_format,
            secondary_sprite_format=secondary_format,
            # Pet art is drawn at a whole multiple of its own size rather than
            # squeezed into the slot: the HD library is 54x48, not 48x48.
            pixel_perfect=True,
            right=right
        )
        # The set's own right-facing frames, paired by surface so the
        # reverse_atk_frames swap below keeps each with its drawing.
        runtime_globals.pet_sprites_right[self] = pair_right_frames(sprites_dict, right)

        # Convert to list format expected by existing code
        sprite_list = convert_sprites_to_list(sprites_dict)
        
        # If no sprites found at all, create fallback white squares
        if not sprite_list or all(s is None for s in sprite_list):
            runtime_globals.game_console.log(f"[Pet] No sprites found for {self.name}, creating fallback")
            fallback_sprite = pygame.Surface((runtime_globals.PET_WIDTH, runtime_globals.PET_HEIGHT))
            fallback_sprite.fill((255, 255, 255))  # White square
            sprite_list = [fallback_sprite] * 20
        
        runtime_globals.pet_sprites[self] = sprite_list
        
        # Apply frame swapping if needed for modules with reverse_atk_frames
        if module_obj.reverse_atk_frames:
            sprites = runtime_globals.pet_sprites[self]
            # Swap TRAIN1 <-> TRAIN2 and ATK1 <-> ATK2
            if len(sprites) > 6:
                sprites[PetFrame.TRAIN1.value], sprites[PetFrame.TRAIN2.value] = sprites[PetFrame.TRAIN2.value], sprites[PetFrame.TRAIN1.value]
                sprites[PetFrame.ATK1.value], sprites[PetFrame.ATK2.value] = sprites[PetFrame.ATK2.value], sprites[PetFrame.ATK1.value]
            runtime_globals.pet_sprites[self] = sprites

        # If pet was saved as Burpmon, restore that sprite
        if getattr(self, 'burpmon_active', False):
            self._load_burpmon_sprite()

    def draw(self, surface):
        # Get base frame; skip if missing
        sprite_list = runtime_globals.pet_sprites.get(self)
        if not sprite_list:
            return
        
        frame_key = self.animation_frames[self.frame_index].value
        frame = sprite_list[frame_key] if frame_key < len(sprite_list) else None
        if frame is None:
            # A frame the set does not carry (or that failed to decode) would
            # otherwise be blitted as None, so the pet vanishes for exactly the
            # frames the animation asks for it — which reads as flickering.
            # Fall back to IDLE1, which every set has.
            frame = sprite_list[0] if sprite_list else None
            if frame is None:
                return
            if not getattr(self, "_warned_missing_frame", False):
                self._warned_missing_frame = True
                runtime_globals.game_console.log(
                    f"[!] {self.name}: sprite frame {frame_key} missing, using IDLE1")

        # Facing right: the set's own right-facing frame, else the frame
        # flipped (cached — flipping allocated a surface per frame)
        if self.direction == 1:
            frame = right_facing(frame, runtime_globals.pet_sprites_right.get(self))
        
        # Draw base pet sprite, with what it wears (an aura goes under it):
        # on the main screen's idle, happy and angry frames only, as the
        # Digivice iC shows them (utils.accessory_utils).
        if getattr(self, "accessory", None) and frame_key in (
                PetFrame.IDLE1.value, PetFrame.IDLE2.value, PetFrame.HAPPY.value, PetFrame.ANGRY.value):
            from utils import accessory_utils
            accessory_utils.draw_behind(surface, self, frame, (self.x, self.y))
            blit_with_cache(surface, frame, (self.x, self.y))
            accessory_utils.draw_over(surface, self, frame, (self.x, self.y))
        else:
            blit_with_cache(surface, frame, (self.x, self.y))
        
        # Determine overlay, if any (dead pets show no overlays)
        overlay = None
        anim_phase = (self.animation_counter // constants.FRAME_RATE) % 2  # precompute phase

        sick = False

        # Overlays come in three flavors keyed off the sprite the pet is
        # actually rendering with (resolved by load_sprite -> self.sprite_format):
        #   Dot -> *_dot overlays, HD -> *_hd overlays, everything else -> default.
        # _misc() prefers the matching variant and falls back to the default
        # when a given overlay has no variant (e.g. Dots has no _hd).
        sprite_format = getattr(self, "sprite_format", None)
        is_dot = sprite_format == "Dot"
        is_hd = sprite_format == "HD"

        def _misc(name):
            """Return the format-matching variant of a misc sprite, else the default."""
            if is_hd:
                hd = runtime_globals.misc_sprites.get(f"{name}_hd")
                if hd:
                    return hd
            elif is_dot:
                dot = runtime_globals.misc_sprites.get(f"{name}_dot")
                if dot:
                    return dot
            return runtime_globals.misc_sprites.get(name)

        if self.state != "dead":
            if self.state == "nap":
                overlay = _misc(f"Sleep{anim_phase + 1}")
            elif self.state in {"happy2", "happy3"} and anim_phase == 0:
                overlay = _misc("Cheer")
            elif self.sick > 0:
                if getattr(self, 'sick_type', '') == "dots":
                    overlay = runtime_globals.misc_sprites.get(f"Dots{anim_phase + 1}")
                else:
                    overlay = _misc(f"Sick{anim_phase + 1}")
                sick = True
            elif self.state == "angry":
                overlay = _misc(f"Mad{anim_phase + 1}")
            elif getattr(self, "dying", False) or self.death_save_b_counter > 0 or self.death_save_shake_counter > 0:
                overlay = _misc(f"Sick{anim_phase + 1}")

        if overlay:
            x = self.x + runtime_globals.PET_WIDTH
            # Prevent overlay from overlapping menu icons
            y_offset = 20 * runtime_globals.UI_SCALE if game_globals.showClock else 5 * runtime_globals.UI_SCALE
            icon_size = 2 * runtime_globals.MENU_ICON_SIZE
            y_min = y_offset + icon_size
            y = max(y_min, self.y - (runtime_globals.PET_WIDTH // 2))
            if self.state in ["happy2", "happy3"]:
                y = self.y
            base_pos = (x, y)
            blit_with_cache(surface, overlay, base_pos)
            
            if self.state == "happy3" and not sick:
                blit_with_cache(surface, overlay, (x, y + (24 * runtime_globals.UI_SCALE)))
                blit_with_cache(surface, overlay, (x - runtime_globals.PET_WIDTH - (24 * runtime_globals.UI_SCALE), y))
                blit_with_cache(surface, overlay, (x - runtime_globals.PET_WIDTH - (24 * runtime_globals.UI_SCALE), y + (24 * runtime_globals.UI_SCALE)))

    def update(self):
        self.timer += 1
        self.update_animation()
        self.update_cache()

        # Frame-based state handling (animation/movement)
        if self.state in ("moving", "idle"):
            self.update_idle_movement()
        elif self.state == "nap":
            self.sleep_timer += 1
            self.check_wake_up()
        elif self.state == "pooping":
            if self.frame_counter in [0, int(6 * (constants.FRAME_RATE / 30))]:
                self.x += int(2 * runtime_globals.UI_SCALE)
                if hasattr(self, 'dirty'):
                    self.dirty = True
            elif self.frame_counter in [int(3 * (constants.FRAME_RATE / 30)), int(9 * (constants.FRAME_RATE / 30))]:
                self.x -= int(2 * runtime_globals.UI_SCALE)
                if hasattr(self, 'dirty'):
                    self.dirty = True

            if self.animation_counter == int(15 * (constants.FRAME_RATE / 30)):
                self.poop()

        # --- Real-time gameplay ticks ---
        now = time.monotonic()

        # Sleep check (~every 0.5s real-time)
        if now - self._rt_last_sleep_check >= 0.5:
            self._rt_last_sleep_check = now
            if self.state in ("moving", "idle") and self.should_sleep():
                self.set_state("tired")

            # Age at midnight. Checked at the same 0.5s cadence — the date
            # flips once a day, and datetime.now() per pet per frame was one
            # of the scene's biggest per-frame costs.
            today = datetime.now().date()
            if today > self._last_age_date:
                self.age += (today - self._last_age_date).days
                self._last_age_date = today
                runtime_globals.game_console.log(f"{self.name} aged to {self.age}")

        # Per-minute gameplay tick
        elapsed_min = int((now - self._rt_origin) / 60)
        if elapsed_min > self._rt_last_minute:
            minutes_passed = elapsed_min - self._rt_last_minute
            self._rt_last_minute = elapsed_min

            # The iC guide gives no sleep exemption for Reliability's hourly
            # loss, so its dedicated countdown runs during both wake and sleep.
            if self.state != "dead":
                self.update_reliability(minutes_passed)
                # Time in this form runs asleep and awake alike.
                self.form_minutes = (getattr(self, "form_minutes", 0) or 0) + minutes_passed

            if self.state not in ("nap", "dead"):
                self._evol_minutes += minutes_passed
                self.update_evolution()
                self.update_needs(minutes_passed)
                self.update_pooping(minutes_passed)
                self.update_poop_mistakes(minutes_passed)
                self.update_care_mistakes()
                self.update_vital_values_loss()
            elif self.state == "nap" and getattr(get_module(self.module), 'count_evolution_while_sleeping', True):
                self._evol_minutes += minutes_passed
                self.update_evolution()
            if self.state != "nap":
                self.update_death_save_counters()
                self.update_death_check(now)

                if self.death_save_immunity > 0:
                    self.death_save_immunity -= 1
                    if self.death_save_immunity == 0:
                        runtime_globals.game_console.log(f"[Death Save] {self.name} immunity expired!")

            if self.back_to_sleep > 0:
                self.back_to_sleep -= 1
                if self.back_to_sleep == 0 and self.state != "nap" and self.should_sleep():
                    self.set_state("nap")

            # Per-hour tick
            if elapsed_min // 60 > (elapsed_min - minutes_passed) // 60:
                if self.state not in ("nap", "dead"):
                    self.update_vital_values_gain()

    def android_offline_snapshot(self, wall_time, monotonic_time, restored=False):
        """Android only: copy care state without invoking pickle/sprite loading.

        Timers in the isolated copy use the checkpoint's wall-time coordinate.
        The normal update loop and desktop serialization are unaffected.
        *restored*: the pet was just loaded from the save that *wall_time*
        dates, so its timers stand as __setstate__ restored them; the time the
        rest of the load took has not passed at the checkpoint.
        """
        import copy
        import uuid
        if not getattr(self, 'android_id', None):
            self.android_id = uuid.uuid4().hex
        if restored:
            monotonic_time = getattr(self, '_rt_restored_at', monotonic_time)
        data = copy.deepcopy({k: v for k, v in self.__dict__.items()
                              if k not in ('frames', '_rt_restored_at')})
        elapsed = max(0.0, monotonic_time - self._rt_origin)
        data['_rt_origin'] = wall_time - elapsed
        # Only SceneMainGame runs update(), so a party left on another screen
        # has minutes it has not applied yet. Offline applies them as the one
        # batch the next update() would; dropping them would lose that care.
        data['android_pending_minutes'] = max(0, int(elapsed / 60) - self._rt_last_minute)
        data['_rt_last_minute'] = int(elapsed / 60)
        data['next_minute'] = wall_time + (60 - elapsed % 60)
        data['_rt_dead_start'] = (wall_time - max(0, monotonic_time - self._rt_dead_start)
                                  if self._rt_dead_start else 0)
        return data

    def android_apply_offline(self, data, wall_time, monotonic_time):
        """Android only: reveal the final care state, never historical animation."""
        import copy
        result = copy.deepcopy(data)
        result.pop('next_minute', None)
        self.__dict__.update(result)
        self._rt_origin = monotonic_time - max(0, wall_time - result['_rt_origin'])
        self._rt_last_sleep_check = monotonic_time
        if result.get('_rt_dead_start'):
            self._rt_dead_start = monotonic_time - max(0, wall_time - result['_rt_dead_start'])
        if self.state not in ('nap', 'dead', 'dying'):
            self.state = 'idle'
        self.animation_frames = getattr(Animation, self.state.upper(), Animation.IDLE)
        self.frame_index = self.frame_counter = self.animation_counter = 0
        self.dirty = True
        self.load_sprite()
        if self.state == 'dead':
            dead = sprite_load(constants.DEAD_FRAME_PATH,
                               size=(runtime_globals.PET_WIDTH, runtime_globals.PET_HEIGHT))
            runtime_globals.pet_sprites[self][0] = dead
            runtime_globals.pet_sprites[self][1] = dead

    def update_cache(self):
        # Check for changes that require cache invalidation
        frame_key = self.animation_frames[self.frame_index].value
        
        # Determine if there's an overlay (same logic as in draw method)
        anim_phase = (self.animation_counter // constants.FRAME_RATE) % 2
        has_overlay = self.state != "dead" and (
            self.state == "nap" or
            (self.state in {"happy2", "happy3"} and anim_phase == 0) or
            self.sick > 0 or
            self.state == "angry" or
            getattr(self, "dying", False)
        )
        
        # Mark as dirty if position, frame, or overlay state changed
        if (hasattr(self, 'cache_x') and hasattr(self, 'cache_frame_index') and hasattr(self, 'cache_has_overlay')):
            if (self.cache_x != self.x or 
                self.cache_frame_index != frame_key or 
                self.cache_has_overlay != has_overlay):
                self.dirty = True
        else:
            # First time setup
            self.dirty = True
        
        # Update cache values
        self.cache_x = self.x
        self.cache_frame_index = frame_key
        self.cache_has_overlay = has_overlay

    def update_idle_movement(self):
        if self.stage == 0 or self.state in ("nap", "dying"):
            return

        self.move_timer -= 1
        # Determine if we should move
        move_chance = (1 - constants.IDLE_PROBABILITY)

        if self.move_timer <= 0:
            if self.state == "idle" and random.random() < 0.30:
                self.set_state("sick" if self.sick > 0 else ("happy" if not self.need_care() else "angry"))
                self.move_timer = random.randint(60, 120)
                return

            if random.random() < move_chance:
                self.set_state("moving")
                self.direction = random.choice([-1, 1])
                self.move_timer = random.randint(20, 60)
            else:
                self.set_state("idle")
                self.move_timer = random.randint(90, 180)

        # Move in sync with frame updates (choppy movement)
        if self.state == "moving" and self.frame_counter % int(constants.FRAME_RATE / 3) == 0:  # move only when animation frame updates
            step = random.choice([2, 6])
            old_x = self.x
            self.x += (step * (runtime_globals.SCREEN_WIDTH / 240)) * self.direction
            if self.x <= self.x_range[0]:
                self.x = self.x_range[0]
                self.direction = 1
            elif self.x >= self.x_range[1]:
                self.x = self.x_range[1]
                self.direction = -1
            
            # Mark as dirty if position actually changed
            if old_x != self.x and hasattr(self, 'dirty'):
                self.dirty = True

    def update_animation(self):
        # Handle special 'nope' animation with direction flip
        if self.state == "nope" and self.timer % constants.FRAME_RATE == 0:
            self.direction *= -1

        # Choppy animation sync for movement
        if self.state == "moving":
            # Move every N frames, same as movement (e.g., every 15 frames)
            self.frame_counter += 1
            if self.frame_counter % ( constants.FRAME_RATE // 3) == 0:
                self.frame_index = (self.frame_index + 1) % len(self.animation_frames)
        else:
            # Regular animation update for non-moving states
            self.frame_counter += 1
            if self.frame_counter > (constants.FRAME_RATE // 2):
                self.frame_counter = 0
                self.frame_index = (self.frame_index + 1) % len(self.animation_frames)

        # Handle timed state resets
        self.animation_counter += 1
        if self.state not in ("moving", "idle", "nap", "dead"):
            if self.state != "nap" and self.animation_counter > int(4 * constants.FRAME_RATE):
                self.set_state("happy"if self.state == "eat" else "idle")

        # Handle hatching animation (real-time: within 5 seconds of evolution time)
        if self.stage == 0:
            elapsed_sec = time.monotonic() - self._rt_origin
            if elapsed_sec - (self.time * 60) >= -5:
                self.set_state("hatch")

    def evolve_to(self, name, version, reward=True):
        """Transform this pet into the given form.

        ``reward`` controls whether the Progress-Mode evolution coin is granted
        for this call.  It defaults to True (normal / armor evolutions and the
        kept pets of a jogress); a standard jogress passes reward=False for the
        absorbed second pet so a 2->1 fusion only scores once, while a PenC
        jogress leaves both True to double the reward.
        """
        # Resolve the target BEFORE changing anything. A module can name a
        # route whose target does not exist on that version — this used to
        # crash on the line below with the sound already played and the old
        # form already pushed onto the history, leaving a half-evolved pet
        # (an egg pointed at a missing form simply never hatched). Now the
        # evolution is refused and the pet is left exactly as it was, so a
        # corrected module can still evolve it later.
        module = get_module(self.module)
        pet_data = module.get_monster(name, version) if module else None
        if not pet_data:
            runtime_globals.game_console.log(
                f"[!] Cannot evolve {self.name} -> '{name}' v{version}: "
                f"not found in module {self.module}. Evolution skipped.")
            return False

        runtime_globals.game_console.log(f"Evolving to {name}")
        runtime_globals.game_sound.play("evolution")
        # The DNA fed into an egg hatches with it - a DigiSoul Plate's, so
        # the Baby I always has a way to evolve; any other evolution starts
        # the new form with none, as the devices do.
        if int(self.stage or 0) != 0:
            self.dna = []
        if not hasattr(self, 'evolution_history'):
            self.evolution_history = []
        self.evolution_history.append(self.name)
        pet_data = dict(pet_data)
        pet_data["module"] = module.name
        self.set_data(pet_data)
        self.reset_variables()
        self.load_sprite()
        self.set_state("happy1")
        # register_digidex_entry grants the first-time "new pet" reward itself
        # (suppressed when this evolution isn't rewarded, e.g. tutorial / the
        # absorbed pet of a fusion).
        register_digidex_entry(self.name, module.name, self.version, reward=reward)

        # Digidex-count unlocks are checked here rather than only when the
        # digidex screen is opened, so the player does not have to visit it.
        from utils.utils_unlocks import check_digidex_unlocks
        check_digidex_unlocks(module.name)

        # Progress Mode: one coin grant per evolution (no-op in Free Mode).
        if reward:
            try:
                from utils.reward_utils import reward_evolution
                reward_evolution(module.name, self.name)
            except Exception as exc:
                runtime_globals.game_console.log(f"[GamePet] evolution reward failed: {exc}")
        # Refusing above returns False, so success has to say so: a caller
        # that checks (the serial jogress does, to keep the cost unspent when
        # nothing happened) would otherwise read every success as a failure.
        return True

    def armor_evolve(self, item_name):
        """Evolve the pet using an armor item (digimental).
        
        Args:
            item_name: The name of the armor item (must match evolution's "item" field)
        """
        runtime_globals.game_console.log(f"[GamePet] Armor evolving with {item_name}")
        
        # Find evolution with matching item requirement
        for evo in self.evolve:
            if "item" in evo and evo["item"] == item_name:
                target_name = evo["to"]
                target_version = evo.get("version", self.version)
                runtime_globals.game_console.log(f"[GamePet] Armor evolution found: {target_name} (version {target_version})")
                self.evolve_to(target_name, target_version)
                return
        
        runtime_globals.game_console.log(f"[GamePet] Warning: No armor evolution found for {item_name}")

    def force_poop(self):
        self.set_state("pooping")

    def poop(self):
        # Get module for care settings
        module = get_module(self.module)
        cfg = game_globals.configuration
        # Poop sprite matches the sprite format the pet is actually rendering,
        # so its overlays and poop stay visually consistent (dot pet -> dot
        # poop, HD pet -> HD poop). JumboPoop has no _hd variant; GamePoop.draw
        # falls back to the base sprite in that case.
        sprite_format = getattr(self, "sprite_format", None)
        use_dot_poop_sprite = (sprite_format == "Dot")
        use_hd_poop_sprite = (sprite_format == "HD")
        
        # care_poop_alarm: play sound on poop if True (default True for backwards compatibility)
        care_poop_alarm = getattr(module, 'care_poop_alarm', True)
        if care_poop_alarm:
            runtime_globals.game_sound.play("cancel")
        
        # care_poop_chance: [single, double, triple, giga] percentages
        # Default: [80, 0, 0, 20] for backwards compatibility (80% single, 20% giga/jumbo)
        care_poop_chance = getattr(module, 'care_poop_chance', [80, 0, 0, 20])
        
        # Normalize chances to ensure we have 4 values
        if len(care_poop_chance) < 4:
            care_poop_chance = care_poop_chance + [0] * (4 - len(care_poop_chance))
        
        # Calculate cumulative probabilities
        total = sum(care_poop_chance)
        if total <= 0:
            total = 100
            care_poop_chance = [100, 0, 0, 0]  # Default fallback
        
        roll = random.random() * total
        cumulative = 0
        poop_type = 0  # 0=single, 1=double, 2=triple, 3=giga
        
        for i, chance in enumerate(care_poop_chance):
            cumulative += chance
            if roll < cumulative:
                poop_type = i
                break
        
        # Calculate base position for poop
        base_x = (12 * runtime_globals.UI_SCALE) + self.x + (constants.FRAME_SIZE // 2)
        base_y = self.y + (runtime_globals.PET_HEIGHT - (24 * runtime_globals.UI_SCALE))
        
        # Create poop(s) based on type
        if poop_type == 0:  # Single
            game_globals.poop_list.append(GamePoop(base_x, base_y, use_dot_sprite=use_dot_poop_sprite, use_hd_sprite=use_hd_poop_sprite))
        elif poop_type == 1:  # Double
            game_globals.poop_list.append(GamePoop(base_x - (12 * runtime_globals.UI_SCALE), base_y, use_dot_sprite=use_dot_poop_sprite, use_hd_sprite=use_hd_poop_sprite))
            game_globals.poop_list.append(GamePoop(base_x + (12 * runtime_globals.UI_SCALE), base_y, use_dot_sprite=use_dot_poop_sprite, use_hd_sprite=use_hd_poop_sprite))
        elif poop_type == 2:  # Triple
            game_globals.poop_list.append(GamePoop(base_x - (18 * runtime_globals.UI_SCALE), base_y, use_dot_sprite=use_dot_poop_sprite, use_hd_sprite=use_hd_poop_sprite))
            game_globals.poop_list.append(GamePoop(base_x, base_y, use_dot_sprite=use_dot_poop_sprite, use_hd_sprite=use_hd_poop_sprite))
            game_globals.poop_list.append(GamePoop(base_x + (18 * runtime_globals.UI_SCALE), base_y, use_dot_sprite=use_dot_poop_sprite, use_hd_sprite=use_hd_poop_sprite))
        elif poop_type == 3:  # Giga (jumbo)
            giga_y = self.y + (runtime_globals.PET_HEIGHT - (48 * runtime_globals.UI_SCALE))
            game_globals.poop_list.append(GamePoop(base_x, giga_y, jumbo=True, use_dot_sprite=use_dot_poop_sprite, use_hd_sprite=use_hd_poop_sprite))

        # Reliability counts poop events, not the number of sprites a module
        # happens to draw for one event. Flushing starts a fresh accumulation.
        self.unflushed_poops += 1
        if self.unflushed_poops % 2 == 0:
            self._apply_reliability_event('reliability_two_poops')
        self.start_poop_timer(module)
        
        if self.weight > self.weight_floor():
            self.weight -= 1
        self.update_99g_effect()
        self.set_state("idle")

    def start_poop_timer(self, module):
        """A new poop has the module's care_poop_mistake_time to be cleaned."""
        limit = int(getattr(module, "care_poop_mistake_time", 0) or 0)
        if limit > 0:
            self.poop_mistake_timers = list(getattr(self, "poop_mistake_timers", None) or []) + [limit]

    def update_poop_mistakes(self, minutes_passed):
        """A poop left uncleaned past care_poop_mistake_time: a care mistake
        and a point of virus, once a poop (Digimon World's poop on the
        ground). Cleaning stops the timers (SceneMainGame)."""
        timers = getattr(self, "poop_mistake_timers", None) or []
        if not timers:
            return
        self.poop_mistake_timers, expired = pet_stats.tick_poop_timers(timers, minutes_passed)
        for _ in range(expired):
            self.virus = int(getattr(self, "virus", 0) or 0) + 1
            self.add_care_mistake("poop")

    def check_death_conditions(self):
        if self.state in ["nap", "dead"]:
            return False

        result = False
        death_cause = ""

        module = get_module(self.module)

        # 1. 15 ou mais ferimentos em uma forma
        if module.death_max_injuries > 0 and self.injuries >= module.death_max_injuries:
            result = True
            death_cause = "injuries"

        # 2. Ficou ferido por 6h contínuas (sem curar)
        if module.death_sick_timer > 0 and self.care_sick_mistake_timer > module.death_sick_timer:
            result = True
            death_cause = "sickness"

        # 3. Fome OU força vazia por 12h contínuas
        if module.death_hunger_timer > 0 and self.care_food_mistake_timer > module.death_hunger_timer:
            result = True
            death_cause = "hunger"
        if module.death_strength_timer > 0 and self.care_strength_mistake_timer > module.death_strength_timer:
            result = True
            death_cause = "strength"

        # 4. Stage IV ou V + 5+ erros após fim do tempo de evolução
        if self.stage in [4, 5] and module.death_stage45_mistake > 0 and self.mistakes >= module.death_stage45_mistake:
            if self._evol_minutes > self.time:
                result = True
                death_cause = "stage_mistakes"

        # 5. Stage VI ou VII + 5+ erros após 48 hours in this form
        if self.stage >= 6 and module.death_stage67_mistake > 0 and self.mistakes >= module.death_stage67_mistake:
            if evolution_rules.form_aged(self):
                result = True
                death_cause = "stage_mistakes"

        if module.death_starvation_count > 0 and self.starvation_counter > module.death_starvation_count:
            result = True
            death_cause = "starvation"

        if module.death_care_mistake > 0 and self.mistakes >= module.death_care_mistake:
            result = True
            death_cause = "care_mistakes"

        # Old age overrides all other causes and cannot be saved
        if module.death_old_age > 0 and self.age >= module.death_old_age:
            return True

        # Old age death cannot be saved
        if result and death_cause == "old_age":
            return True

        # Death save system - activate if death conditions met and not immune
        if result and self.death_save_immunity == 0 and not self.dying:
            has_save_method = module.death_save_by_b_press > 0 or module.death_save_by_shake > 0
            if has_save_method:
                self.death_cause = death_cause
                self.dying = True
                self.set_state("dying")
                runtime_globals.game_sound.play("death")
                if module.death_save_by_b_press > 0 and self.death_save_b_counter == 0:
                    self.death_save_b_counter = module.death_save_by_b_press
                    runtime_globals.game_console.log(f"[Death Save] {self.name} needs {module.death_save_by_b_press} B presses in 60 seconds! Cause: {death_cause}")
                elif module.death_save_by_shake > 0 and self.death_save_shake_counter == 0:
                    self.death_save_shake_counter = module.death_save_by_shake
                    runtime_globals.game_console.log(f"[Death Save] {self.name} needs {module.death_save_by_shake} shakes in 60 seconds! Cause: {death_cause}")
                return False

        return result

    def update_death_save_counters(self):
        """Update death save counters and handle success/failure."""
        if self.dying:
            if self.death_save_b_counter <= 0 and self.death_save_shake_counter <= 0:
                # Successfully saved! Negate death trigger based on cause
                module = get_module(self.module)
                cause = getattr(self, 'death_cause', '')
                if cause == "injuries":
                    self.injuries = max(0, self.injuries - 1)
                elif cause == "sickness":
                    self.sick = 0
                    self.care_sick_mistake_timer = 0
                elif cause == "hunger":
                    self.care_food_mistake_timer = 0
                elif cause == "strength":
                    self.care_strength_mistake_timer = 0
                elif cause == "starvation":
                    self.starvation_counter = max(0, self.starvation_counter - 1)
                elif cause in ("care_mistakes", "stage_mistakes"):
                    self.mistakes = max(0, self.mistakes - 1)
                self.death_save_immunity = 60  # 60 minutes
                self.death_save_b_counter = 0
                self.death_save_shake_counter = 0
                self.dying = False
                self.death_cause = ""
                self.set_state("happy2")
                runtime_globals.game_sound.play("happy")
                runtime_globals.game_console.log(f"[Death Save] {self.name} was saved (cause: {cause})! 60-minute immunity granted.")

    def _death_evolution(self):
        """Take a death route (``at_death``) instead of dying, if one is met
        and its chance rolls. True when the pet evolved."""
        if not any(evolution_rules.is_death_route(e) for e in (self.evolve or [])):
            return False
        match = self.find_evolution(kind="death")
        if match is None:
            return False
        self.dying = False
        self.death_cause = ""
        runtime_globals.game_console.log(f"{self.name} evolved instead of dying.")
        self._apply_evolution(match[0])
        return True

    def update_death_check(self, now=None):
        """Checks pet death conditions and updates the sprite accordingly."""
        if now is None:
            now = time.monotonic()
        if self.check_death_conditions() and self.death_save_immunity == 0:
            # A death route (at_death) may take the pet instead of the death:
            # the PENGZ's Skull Greymon G. A saved pet never reaches here.
            if self._death_evolution():
                return
            # Pet dies (either no save method or save timer expired)
            module = get_module(self.module)
            has_save_method = module.death_save_by_b_press > 0 or module.death_save_by_shake > 0
            if has_save_method:
                runtime_globals.game_sound.play("fail")
            else:
                runtime_globals.game_sound.play("death")
            self.dying = False
            self.death_cause = ""
            self.set_state("dead")
            self.burpmon_active = False

            dead_sprite = sprite_load(constants.DEAD_FRAME_PATH, size=(runtime_globals.PET_WIDTH, runtime_globals.PET_HEIGHT))
            runtime_globals.pet_sprites[self][0] = dead_sprite
            runtime_globals.pet_sprites[self][1] = dead_sprite

            self._rt_dead_start = now

        # Remove pet from game if dead for 5 minutes (real-time)
        if self.state == "dead" and self._rt_dead_start > 0 and now - self._rt_dead_start > 300:
            if self in game_globals.pet_list:
                game_globals.pet_list.remove(self)
                del runtime_globals.pet_sprites[self]
                runtime_globals.pet_sprites_right.pop(self, None)
                # One fewer pet in the party means the rest get a bigger slot.
                from utils.pet_utils import refresh_pet_sizes
                refresh_pet_sizes()

            self.set_traited_egg()

            if not game_globals.pet_list:
                change_scene("egg")


    def set_eating(self, food_type: str, amount: int,
                   weight_gain=None) -> bool:
        """
        Handles feeding logic for different food types.
        Returns True if the pet accepted the food, False otherwise.
        """
        module = get_module(self.module)

        if weight_gain is None:
            hunger_weight_gain = module.meat_weight_gain
            strength_weight_gain = module.protein_weight_gain
        else:
            # An item's own weight is made by the inventory to every pet that
            # takes it, whatever the effect (`item_effects.apply_weight`).
            hunger_weight_gain = strength_weight_gain = 0

        # Can't eat if sleeping and module doesn't allow it
        if not module.can_eat_sleeping and self.state == "nap":
            return False

        # Block feeding during sleep window if care_block_actions_when_sleeping is set
        if self._is_blocked_by_sleep():
            return False

        accepted = False

        if food_type == "hunger":
            if self.hunger == self.stomach or self.overfeed_timer:
                if self.overfeed_timer == 0:
                    self.overfeed_timer = module.overfeed_timer
                    self.overfeed += 1
                self.set_state("nope")
            else:
                old_hunger = self.hunger
                self.answer_call("hunger")
                self.check_disturbed_sleep()
                self.set_state("eat", True)
                self.hunger = min(self.stomach, self.hunger + (module.meat_hunger_gain * amount))
                if self.stage > 1 and self.weight < 99:
                    self.weight = min(99, self.weight + hunger_weight_gain)
                self.care_food_mistake_timer = 0
                accepted = True
                # 満腹 means the pet's actual satiety limit: the same point at
                # which it refuses another meal. It is not the four-heart UI
                # threshold used by some modules.
                if (self.stomach > 0 and old_hunger < self.stomach and
                        self.hunger >= self.stomach):
                    self._apply_reliability_event('reliability_becoming_full')
                runtime_globals.game_console.log(f"{self.name} ate food (hunger). Hunger {self.hunger}")
        elif food_type == "strength" and not self.tracks_strength():
            # No Strength meter on this device (the iC, DW1): nothing to fill.
            self.set_state("nope")
        elif food_type == "strength":
            self.check_disturbed_sleep()
            self.set_state("eat")
            self.strength = min(self.stomach, self.strength + (module.protein_strengh_gain * amount))
            self.protein_feedings += 1
            if self.stage > 1 and self.weight < 99:
                self.weight = min(99, self.weight + strength_weight_gain)
            if self.protein_feedings % 4 == 0:
                self.protein_overdose = min(get_module(self.module).protein_overdose_max, self.protein_overdose + 1)
                self.protein_feedings = 0
                if self.dp < self.energy:
                    self.dp = min(self.energy, self.dp + module.protein_dp_gain)
            self.care_strength_mistake_timer = 0
            
            # G-Cell points for protein feeding, in the module's style
            self._gcell_event("protein")
            
            accepted = True
            runtime_globals.game_console.log(f"{self.name} ate food (strength). Strength {self.strength}")
        else:
            # For other food types, only accept if pet can battle
            if self.can_battle():
                self.check_disturbed_sleep()
                self.set_state("eat")
                accepted = True
                runtime_globals.game_console.log(f"{self.name} ate food ({food_type}).")
            else:
                self.set_state("nope")

        self.update_99g_effect()
        return accepted

    def set_sick(self, sick_type=""):
        # Already sick pets cannot fall sick again - the ailment has to be
        # healed first. Without this an untreated pet keeps re-rolling its
        # heal doses and racking up injuries toward death.
        if self.sick > 0:
            return False
        self.sick_type = sick_type
        self.sick = self.heal_doses
        self.injuries += 1
        self._apply_reliability_event('reliability_sickness_or_injury')
        self.set_state("sick")
        return True

    def update_99g_effect(self):
        """Handle the 99g weight effect based on the module's care_99g_effect setting."""
        module = get_module(self.module)
        effect = getattr(module, 'care_99g_effect', 'Skull')

        if effect == "Nothing":
            return

        if effect == "Burpmon":
            if self.state == "dead":
                if getattr(self, 'burpmon_active', False):
                    self.burpmon_active = False
                    self.load_sprite()
                return
            if (self.weight >= constants.BURPMON_WEIGHT
                    and not getattr(self, 'burpmon_active', False)):
                self.burpmon_active = True
                self._load_burpmon_sprite()
            elif (self.weight < constants.BURPMON_WEIGHT
                    and getattr(self, 'burpmon_active', False)):
                self.burpmon_active = False
                self.load_sprite()
            return

        # Dots or Skull: allow re-trigger only after weight drops below 90
        if self.weight < 90:
            self._99g_triggered = False
            if self.sick == 0:
                self.sick_type = ""

        if self.weight >= 99 and not getattr(self, '_99g_triggered', False):
            self._99g_triggered = True
            if effect == "Dots":
                self.set_sick("dots")
            else:  # Skull
                self.set_sick()

    def _load_burpmon_sprite(self):
        """Replace current pet sprite with the Burpmon sprite."""
        module_obj = get_module(self.module)
        if not module_obj:
            return
        
        primary_format = getattr(module_obj, 'primary_sprite_format', 'Color')
        secondary_format = getattr(module_obj, 'secondary_sprite_format', 'HD')
        
        sprites_dict, resolved_format = load_pet_sprites_resolved(
            "Burpmon",
            module_obj.folder_path,
            module_obj.name_format,
            size=(runtime_globals.PET_WIDTH, runtime_globals.PET_HEIGHT),
            primary_sprite_format=primary_format,
            secondary_sprite_format=secondary_format,
            pixel_perfect=True
        )
        if sprites_dict:
            self.sprite_format = resolved_format
            runtime_globals.pet_sprites[self] = convert_sprites_to_list(sprites_dict)
            runtime_globals.game_console.log(f"[99g] {self.name} became Burpmon!")
        else:
            runtime_globals.game_console.log(f"[99g] Burpmon sprite not found, keeping original.")

    def _has_dna_evolution_criterion(self, evolution):
        """Whether a route asks for DigiSoul DNA: a non-empty
        ``digisoul_dna``, the types any of which it takes."""
        dna_types = evolution.get("digisoul_dna")
        return isinstance(dna_types, (list, tuple)) and len(dna_types) > 0

    def get_dna_total(self, dna_types=None):
        """How many of the remembered DNA feeds are of *dna_types* (all
        types when None)."""
        wanted = None if dna_types is None else {str(t).casefold() for t in dna_types}
        return sum(1 for dna in getattr(self, "dna", None) or []
                   if wanted is None or dna.casefold() in wanted)

    def leading_dna(self):
        """The DNA this Digimon's evolution reads: the type it holds most of
        among the remembered feeds, the one fed latest on a tie. None when it
        holds none.

        One feed is enough, and the latest feed decides a tie, so a Digimon
        that has taken Beast and then Bird goes the Bird way (owner,
        2026-10-05).
        """
        queue = list(getattr(self, "dna", None) or [])
        if not queue:
            return None
        counts = {}
        last_fed = {}
        for position, dna in enumerate(queue):
            counts[dna] = counts.get(dna, 0) + 1
            last_fed[dna] = position
        return max(counts, key=lambda dna: (counts[dna], last_fed[dna]))

    def _dna_evolution_requirement_met(self, evolution):
        """A DNA route is taken when the leading DNA is one of its types."""
        if not self._has_dna_evolution_criterion(evolution):
            return True
        leading = self.leading_dna()
        return leading is not None and leading.casefold() in {
            str(t).casefold() for t in evolution["digisoul_dna"]}

    def _ordered_normal_evolution_routes(self):
        """The routes in their JSON order: the first one met wins. A route
        without a DNA requirement, listed after the DNA ones, is the way a
        Digimon that holds no fitting DNA goes."""
        return list(self.evolve)

    def update_evolution(self):
        module = get_module(self.module)
        # A defeat-count route (`defeat_tag`) evolves the pet as soon as its
        # count is reached, whatever the timer says.
        if any(evolution_rules.is_immediate_route(e) for e in (self.evolve or [])):
            match = self.find_evolution(kind="immediate")
            if match is not None:
                self._apply_evolution(match[0])
                return

        if self._evol_minutes < self.time or self.need_care():
            return
        # A failed evolution is final (evolution_fail_on_first_try).
        if getattr(self, "evolution_failed", False):
            return

        match = self.find_evolution()
        if match is None:
            # The first try is the only one for a route that reads the battle
            # record, on a module that says so; other routes keep waiting.
            if evolution_rules.should_fail(module, self.evolve or []):
                self.evolution_failed = True
                runtime_globals.game_console.log(f"{self.name} failed to evolve.")
            return
        self._apply_evolution(match[0])

    def _apply_evolution(self, evo):
        """Evolve along a route that has been taken: its unlocks, then the form."""
        # A `virus` route spends the virus (World's Sukamon empties the bar).
        if "virus" in evo:
            self.virus = 0
        # Unlock evolution if present in module unlocks (new format)
        module = get_module(self.module)
        unlocks = getattr(module, "unlocks", [])
        target_stage = None
        for unlock in unlocks:
            if unlock.get("type") != "evolution":
                continue
            if unlock.get("to") and evo["to"] in unlock["to"]:
                unlock_item(self.module, "evolution", unlock["name"])
                continue
            # An evolution unlock can name a stage instead of a target,
            # for the devices that hand out a Digitama simply for getting
            # a Digimon that far. PEN20 opens four of its eggs this way,
            # "Unlocked by evolving into Child".
            wanted = unlock.get("stage")
            if wanted is None:
                continue
            if target_stage is None:
                target_stage = (module.get_monster(evo["to"], self.version)
                                or {}).get("stage", 0)
            if target_stage >= wanted:
                unlock_item(self.module, "evolution", unlock["name"])

        if self.stage == 0 and self.shake_counter >= 99 and get_module(self.module).enable_shaken_egg:
            self.shook = True

        self.evolve_to(evo["to"], evo.get("version", self.version))

        # Update quest progress for normal evolution
        from utils.quest_event_utils import update_evolution_quest_progress
        update_evolution_quest_progress("normal", self.module)

    def preview_evolution(self):
        """The form this pet would evolve into if it evolved now: the first
        route whose requirements it meets, a route's % chance counted as a
        certainty. The target's monster.json record, or None. Neither the
        evolution timer nor care calls are waited for, and nothing changes."""
        match = self.find_evolution(roll_chance=False)
        return match[1] if match else None

    def find_evolution(self, roll_chance=True, kind="normal"):
        """The first normal evolution route this pet satisfies now, as
        ``(route, target's monster.json record)``, or None.

        Routes are tried in their order (`_ordered_normal_evolution_routes`);
        jogress and armor routes are never normal ones. A route's ``chance``
        is rolled, last, when *roll_chance*; otherwise it counts as met, and
        so do the module's win-ratio table and a death route's ``at_death``.
        *kind* picks the routes: "normal" (the timer), "immediate" (defeat
        counts) or "death" (only ``at_death`` routes; see
        utils.evolution_rules). A target missing from this version, or a
        special one still locked, is passed over. Nothing about the pet
        changes here.
        """
        module_obj = get_module(self.module)
        poops_on_screen = len(game_globals.poop_list)
        table_roll = evolution_rules.once(lambda: random.random() * 100)
        for evo in self._ordered_normal_evolution_routes():
            if not evolution_rules.route_wanted(evo, kind):
                continue
            def in_range(val, r): return r[0] <= val <= r[1]
            def in_time_range(time_range):
                try:
                    now_time = datetime.now().time()
                    start_time = datetime.strptime(time_range[0].strip(), "%H:%M").time()
                    end_time = datetime.strptime(time_range[1].strip(), "%H:%M").time()
                    
                    if start_time < end_time:
                        return start_time <= now_time <= end_time
                    else:
                        # Handle overnight range (e.g., 23:00 to 01:00)
                        return now_time >= start_time or now_time <= end_time
                except Exception as e:
                    runtime_globals.game_console.log(f"[!] Error parsing time_range: {e}")
                    return False
                    
            if (
                ("jogress" in evo) or ("item" in evo) or
                ("mistakes" in evo and not in_range(self.mistakes, evo["mistakes"])) or
                ("condition_hearts" in evo and not in_range(self.condition_hearts, evo["condition_hearts"])) or
                ("training" in evo and not in_range(self.effort, evo["training"])) or
                ("overfeed" in evo and not in_range(self.overfeed, evo["overfeed"])) or
                ("special_encounter" in evo and not self.special_encounter) or
                ("level" in evo and not in_range(self.level, evo["level"])) or
                ("quests_completed" in evo and not in_range(self.quests_completed, evo["quests_completed"])) or
                # Digimon Twin: Event Communications run against the win ratio
                # to give the Perfect/Ultimate chance.
                ("event_communication" in evo and
                 not in_range(getattr(self, "event_communications", 0),
                              evo["event_communication"])) or
                # "item_use" counts how many times an item has been used, as
                # against "item", which names an armor/digimental to evolve
                # with. The Twin wants five Bombs for Digitamamon.
                ("item_use" in evo and
                 getattr(self, "item_uses", {}).get(evo["item_use"], 0)
                 < evo.get("item_use_amount", 1)) or
                ("weight" in evo and not in_range(self.weight, evo["weight"])) or
                ("trophies" in evo and not in_range(self.trophies, evo["trophies"])) or
                ("vital_values" in evo and not in_range(self.vital_values, evo["vital_values"])) or
                ("reliability" in evo and not in_range(self.reliability, evo["reliability"])) or
                (self._has_dna_evolution_criterion(evo) and
                 not self._dna_evolution_requirement_met(evo)) or
                ("blue_gcells" in evo and not in_range(self.get_blue_gcells(), evo["blue_gcells"])) or
                ("yellow_gcells" in evo and not in_range(self.get_yellow_gcells(), evo["yellow_gcells"])) or
                ("red_gcells" in evo and not in_range(self.get_red_gcells(), evo["red_gcells"])) or
                ("gcell_level" in evo and not in_range(self.get_gcell_level(), evo["gcell_level"])) or
                ("gcell_hatch" in evo and not self.gcell_fragment) or
                # G-Cells in the module's style (PENGZ: 0-14, Red from 8)
                ("gcells" in evo and not in_range(gcell_rules.cells(module_obj, self), evo["gcells"])) or
                ("stage-5" in evo and not in_range(self.enemy_kills[5], evo["stage-5"])) or
                ("stage-6" in evo and not in_range(self.enemy_kills[6], evo["stage-6"])) or
                ("stage-7" in evo and not in_range(self.enemy_kills[7], evo["stage-7"])) or
                ("stage-8" in evo and not in_range(self.enemy_kills[8], evo["stage-8"])) or
                ("stage-9" in evo and not in_range(self.enemy_kills[9], evo["stage-9"])) or
                ("pvp" in evo and not in_range(self.pvp_wins, evo["pvp"])) or
                ("sleep_disturbances" in evo and not in_range(self.sleep_disturbances, evo["sleep_disturbances"])) or
                ("battles" in evo and not in_range(self.battles, evo["battles"])) or
                ("win_count" in evo and not in_range(self.win, evo["win_count"])) or
                ("win_ratio" in evo and self.battles and not in_range((self.win * 100) // self.battles, evo["win_ratio"])) or
                # Minimum adventure area the pet must have cleared. self.area
                # is the furthest area it has won a battle in (finish_battle).
                ("area" in evo and evo["area"] is not None and
                 getattr(self, "area", 0) < evo["area"]) or
                ("time_range" in evo and not in_time_range(evo["time_range"])) or
                # Poops on screen, the lifetime record and tagged defeats.
                evolution_rules.extra_criteria_fail(self, evo, poops_on_screen) or
                # "chance" is rolled last, so it is only spent on an entry
                # whose other requirements are already satisfied. A failed
                # roll falls through to the next entry, which is how the
                # device presents a coin flip between two outcomes: give the
                # first one a chance and leave the second without one.
                # -1 (or absent) means the criterion is unused.
                (roll_chance and "chance" in evo and evo["chance"] >= 0 and
                 random.random() * 100 >= evo["chance"])
            ):
                continue
            # Then the module's win-ratio table and a death route's chance.
            if roll_chance and evolution_rules.rolls_fail(
                    module_obj, self, evo, lambda: random.random() * 100, kind, table_roll):
                continue

            # The target has to exist on this version before anything else is
            # decided. Checked for EVERY stage: this block used to be skipped
            # for eggs, so a stage-0 route naming a missing form fell straight
            # through to evolve_to and left the egg unable to hatch at all.
            module = get_module(self.module)
            pet_data = module.get_monster(evo["to"], self.version) if module else None
            if not pet_data:
                runtime_globals.game_console.log(
                    f"[!] {self.name}: evolution target '{evo['to']}' v{self.version} "
                    f"missing from {self.module}; route skipped")
                continue

            if self.stage > 0:
                if pet_data.get("special", False):
                    special_key = pet_data.get("special_key")
                    if special_key and not is_unlocked(self.module, None, special_key):
                        runtime_globals.game_console.log(f"{self.name} cannot evolve into {evo['to']}—special evolution {special_key} is locked.")
                        continue  # Skip this evolution

            return evo, pet_data
        return None

    def update_needs(self, minutes_passed):
        # Skip hunger/strength decay when pet should be sleeping. The Digimon
        # Twin drains Strength through the night on purpose - it is what makes
        # its wake-up training call a real mechanic - so a module can opt out.
        sleeping = self.should_sleep() or self.state == "nap"
        if sleeping and getattr(get_module(self.module),
                                'care_needs_decay_while_sleeping', False):
            sleeping = False
        # Twice as fast after a failed evolution, or at Stage VI+ after 48
        # hours in the form, where the module fails evolutions (PENGZ).
        drain = minutes_passed * evolution_rules.needs_factor(self, get_module(self.module))

        # Hunger countdown
        if self._cd_hunger > 0 and not sleeping:
            if self.overfeed_timer == 0:
                self._cd_hunger -= drain
                while self._cd_hunger <= 0:
                    if self.hunger > 0:
                        self.hunger -= 1
                    else:
                        self.starvation_counter += 1
                    self._cd_hunger += self.hunger_loss
        # Strength countdown, on a device that has the meter
        if self._cd_strength > 0 and not sleeping and self.tracks_strength():
            self._cd_strength -= drain
            while self._cd_strength <= 0:
                if self.strength > 4:
                    self.strength = 4
                elif self.strength > 0:
                    self.strength -= 1
                    if self.strength == 0:
                        # The empty-strength call costs PENGZ G-Cells.
                        self._gcell_event("empty_strength")
                self._cd_strength += self.strength_loss
        if self.overfeed_timer > 0:
            self.overfeed_timer -= 1

        self.update_99g_effect()

    def update_pooping(self, minutes_passed):
        if self.stage <= 0 or self._cd_poop <= 0:
            return
        module = get_module(self.module)
        poop_sickness_count = getattr(module, 'care_poop_sickness_count', 0)
        if poop_sickness_count > 0:
            poop_threshold = poop_sickness_count * max(1, len(game_globals.pet_list) - 1)
            poop_sick = len(game_globals.poop_list) >= poop_threshold and self.stage >= 2
        else:
            poop_sick = False
        if poop_sick:
            if self.poop_count_flag == 0:
                self.poop_count_flag = 1
                poop_effect = getattr(module, 'care_poop_sickness_effect', 'Skull')
                if poop_effect == "Nothing":
                    pass
                elif poop_effect == "Dots":
                    self.set_sick("dots")
                else:  # Skull
                    self.set_sick()
                runtime_globals.game_console.log(f"[!] Care sick of poop ({len(game_globals.poop_list)})! Effect: {poop_effect}, Injuries: {self.injuries}")
        else:
            self.poop_count_flag = 0

        # Twice as fast at Stage VI+ after 48 hours in the form, and after a
        # failed evolution where the module fails them.
        depletion = minutes_passed * evolution_rules.poop_factor(self, module)
        self._cd_poop -= depletion
        if self._cd_poop <= 0:
            self.set_state("pooping")
            self._cd_poop = max(1, self.poop_timer)

    def update_care_mistakes(self):
        sound_alert = False
        sleeping = self.should_sleep() or self.state == "nap"
        module = get_module(self.module)

        #hunger call — only tick while pet is not in sleep window;
        # once care mistake fires, timer caps at threshold (no repeat)
        if self.hunger == 0 and not sleeping:
            if self.care_food_mistake_timer < module.meat_care_mistake_time:
                self.care_food_mistake_timer += 1
                if self.care_food_mistake_timer == module.meat_care_mistake_time:
                    self._apply_reliability_event('reliability_ignoring_call')
                    self.add_care_mistake("hunger")
                    sound_alert = True
        
        #strength call — same single-fire guard (only where the meter exists)
        if self.strength_empty() and not sleeping:
            if self.care_strength_mistake_timer < module.protein_care_mistake_time:
                self.care_strength_mistake_timer += 1
                if self.care_strength_mistake_timer == module.protein_care_mistake_time:
                    self.add_care_mistake("strength")
                    sound_alert = True
        
        #sick call — pause timer while sleeping
        if self.sick > 0 and not sleeping:
            self.care_sick_mistake_timer += 1
        elif self.sick == 0:
            self.care_sick_mistake_timer = 0

        #sleep call
        if sleeping:
            self.care_sleep_mistake_timer += 1
            if self.care_sleep_mistake_timer >= module.sleep_care_mistake_timer:
                if not self._reliability_sleep_call_resolved:
                    self._apply_reliability_event('reliability_ignoring_call')
                    self._reliability_sleep_call_resolved = True
                self.add_care_mistake("sleep")
                sound_alert = True
                self.care_sleep_mistake_timer = 0
        else:
            # A new bedtime starts a new call episode. Resetting the timer
            # also prevents a partly answered call carrying into tomorrow.
            if (getattr(module, 'reliability_answering_call', 0) or
                    getattr(module, 'reliability_ignoring_call', 0)):
                self.care_sleep_mistake_timer = 0
            self._reliability_sleep_call_resolved = False
                
        
        if sound_alert:
            runtime_globals.game_sound.play("alarm")

    def update_vital_values_gain(self):
        """Update vital values every hour - gain if pet is healthy and well-fed"""
        if self.stage <= 0 or self.state in ("dead", "nap") or self.sick > 0 or self.hunger == 0 or self.strength_empty():
            return

        # only devices that show the meter earn anything, the same rule
        # Experience follows
        if not self.tracks_vital_values():
            return

        module = get_module(self.module)
        base_gain = getattr(module, 'vital_value_base', 50)  # Default to 50 if not defined

        # Calculate multiplier based on activities (base + activities)
        activity_multiplier = 1 + len(self.vital_activities)
        vital_gain = base_gain * activity_multiplier

        # The cap is per stage - a Child tops out at 2500 where an Ultimate
        # reaches 9999 - so evolving is what raises the ceiling.
        ceiling = self.vital_value_cap() or 9999
        self.vital_values = min(ceiling, self.vital_values + vital_gain)
        
        runtime_globals.game_console.log(f"[Vital] {self.name} gained {vital_gain} vital values (activities: {len(self.vital_activities)}). Total: {self.vital_values}")
        
        # Clear activities after gaining vital values
        self.vital_activities.clear()

    def update_vital_values_loss(self):
        """Update vital values every minute - lose if pet is in poor condition"""
        if self.stage <= 0 or self.state in ("dead", "nap") or self.sick <= 0 and self.hunger > 0 and not self.strength_empty():
            return

        module = get_module(self.module)
        vital_loss = getattr(module, 'vital_value_loss', 1)  # Default to 1 if not defined
        
        # Remove from vital_values (minimum 0)
        old_vital = self.vital_values
        self.vital_values = max(0, self.vital_values - vital_loss)
        
        if old_vital != self.vital_values:
            runtime_globals.game_console.log(f"[Vital] {self.name} lost {vital_loss} vital values (poor condition). Total: {self.vital_values}")
    
    def add_care_mistake(self, mistake_type):
        module = get_module(self.module)
        
        if self.use_condition_hearts:
            if self.condition_hearts > 0:
                self.condition_hearts -= 1
                runtime_globals.game_console.log(f"[!] Care mistake ({mistake_type})! Condition hearts left: {self.condition_hearts}")
        else:
            self.mistakes += 1
            runtime_globals.game_console.log(f"[!] Care mistake ({mistake_type})! Total: {self.mistakes}")
        
        # G-Cell points for a care mistake, in the module's style
        self._gcell_event("care_mistake")

    def need_care(self):
        return self.stage != 0 and self.state not in ("dead","nap") and (self.hunger == 0 or self.strength_empty() or self.sick > 0 or self.should_sleep())

    def call_sign(self):
        if self.stage == 0 or self.state in ("dead","nap"):
            return False
        if self.hunger == 0 and self.care_food_mistake_timer < get_module(self.module).meat_care_mistake_time:
            return True
        elif self.strength_empty() and self.care_strength_mistake_timer < get_module(self.module).protein_care_mistake_time:
            return True
        elif self.should_sleep() and self.care_sleep_mistake_timer < get_module(self.module).sleep_care_mistake_timer:
            return True
        return False

    def answer_call(self, call_type):
        """Resolve a pending care call and apply its configured Reliability.

        A call pays once. Hunger is pending only before its care-mistake
        deadline; bedtime additionally has an episode guard because the
        existing sleep-penalty counter may fire more than once overnight.
        """
        module = get_module(self.module)
        if not module:
            return False
        if not (getattr(module, 'reliability_answering_call', 0) or
                getattr(module, 'reliability_ignoring_call', 0)):
            return False

        if call_type == "hunger":
            pending = (
                self.hunger == 0 and
                self.care_food_mistake_timer < module.meat_care_mistake_time
            )
        elif call_type == "sleep":
            pending = (
                self.should_sleep() and
                self.care_sleep_mistake_timer < module.sleep_care_mistake_timer and
                not self._reliability_sleep_call_resolved
            )
            if pending:
                self._reliability_sleep_call_resolved = True
                self.care_sleep_mistake_timer = 0
        else:
            return False

        if pending:
            self._apply_reliability_event('reliability_answering_call')
        return pending

    def _grant_traited_egg(self):
        key = f"{self.module}@{self.version}"
        if key not in game_globals.traited:
            game_globals.traited.append(key)
            runtime_globals.game_console.log(f"Traited Egg granted for {self.name}!")

    def _grant_gcell_fragment(self):
        """Make the module's G-Cell Fragment egg available once.

        scene_eggselection consumes the entry when the egg is picked, so the
        player has to earn it again for the next one.
        """
        key = f"{self.module}@{self.version}"
        if not hasattr(game_globals, "gcell_fragments"):
            game_globals.gcell_fragments = []
        if key not in game_globals.gcell_fragments:
            game_globals.gcell_fragments.append(key)
            runtime_globals.game_console.log(
                f"[G-Cell] {self.name} left a G-Cell Fragment for {self.module} v{self.version}!")

    def set_traited_egg(self):
        """Leave a Traited Egg if this device's rule says the pet earned one.

        ``traited_egg_rule`` on the module picks between the five ways the
        devices grant one:

          None                       never
          Stage V                    stage V or higher, always
          Stage V and Battles        stage V or higher and 100+ battles
          Stage V Chance             stage V or higher, 30% roll
          Win Ratio (Stage 4)        stage IV or higher and a 60% win ratio
          Win Ratio (Stage 5)        the same from stage V
          Evolution Timer            48 hours since the last evolution
          Evolution Timer (Area 45)  the same, gated on the X's Area 45
          Outlive Lifespan           still alive past its listed lifespan
        """
        module = get_module(self.module)
        rule = getattr(module, "traited_egg_rule", "Stage V Chance")

        if rule == "None":
            return

        if rule == "Stage V":
            # The Digimon Mini lays a Digitama whenever the pet reaches
            # LEVEL 5, with no roll at all.
            if self.stage >= 5:
                self._grant_traited_egg()
            return

        if rule == "Stage V and Battles":
            # The Digimon Twin adds a battle record to the same rule: Perfect
            # or above *and* more than 100 battles.
            if self.stage >= 5 and self.battles >= 100:
                self._grant_traited_egg()
            return

        if rule == "Stage V Chance":
            # "When most Stage V or higher Monsters die, they have a 30%
            # chance of leaving a Traited Egg." Devices that also have a
            # G-Cell Fragment egg split that chance instead: 15% traited,
            # 15% fragment.
            if self.stage >= 5:
                if module.has_gcell_fragment_egg():
                    roll = random.random()
                    if roll < 0.15:
                        self._grant_traited_egg()
                    elif roll < 0.30:
                        self._grant_gcell_fragment()
                elif random.random() < 0.30:
                    self._grant_traited_egg()
            return

        if rule.startswith("Win Ratio"):
            min_stage = 4 if "Stage 4" in rule else 5
            win_ratio = (self.win * 100) // self.battles if self.battles else 0
            if evolution_rules.fails_on_first_try(module):
                # The PENGZ: the lifetime ratio, and only from a pet whose
                # evolution failed or a Stage VI+ 48 hours in its form.
                if not (getattr(self, "evolution_failed", False)
                        or (self.stage >= 6 and evolution_rules.form_aged(self))):
                    return
                win_ratio = evolution_rules.total_win_ratio(self)
            if self.stage >= min_stage and win_ratio >= 60:
                self._grant_traited_egg()
            return

        if rule.startswith("Evolution Timer"):
            if self._evol_minutes < 2880:  # 48 hours
                return
            # The Digital Monster X keeps the egg from its later versions
            # until Area 45 has been cleared.
            if "Area 45" in rule and self.version > 4 and self.area < 45:
                return
            self._grant_traited_egg()
            return

        if rule == "Outlive Lifespan":
            # "keep your Digimon alive longer than its natural lifespan"
            if self.time and self._evol_minutes >= self.time:
                self._grant_traited_egg()
            return


    def _is_blocked_by_sleep(self):
        if not getattr(get_module(self.module), 'care_block_actions_when_sleeping', True):
            return False
        return self.state == "nap" or self.should_sleep()

    def _has_battle_resources(self):
        module = get_module(self.module)
        cost_type = getattr(module, 'battle_cost_type', 'DP')
        cost_amount = getattr(module, 'battle_cost_amount', 1.0)
        if cost_type == "Nothing":
            return True
        elif cost_type == "Hunger":
            # A hungry pet cannot battle whatever the cost, so a Hunger cost
            # of 0 means "free, but not on an empty stomach" - the Mini's rule.
            return self.hunger > 0 and self.hunger >= cost_amount
        else:  # DP
            return self.dp >= cost_amount

    def _deduct_battle_cost(self):
        module = get_module(self.module)
        cost_type = getattr(module, 'battle_cost_type', 'DP')
        cost_amount = getattr(module, 'battle_cost_amount', 1.0)
        if cost_type == "Hunger":
            self.hunger = max(0, self.hunger - cost_amount)
        elif cost_type == "DP":
            self.dp = max(0, self.dp - cost_amount)

        # Weight shed per battle, independent of the cost resource (0 for
        # modules that don't use it).
        weight_loss = getattr(module, 'battle_weight_loss', 0)
        if weight_loss and self.stage > 1:
            self.weight = max(self.weight_floor(), self.weight - weight_loss)
            self.update_99g_effect()

    def battle_block_reason(self, entering=True):
        """Why this pet cannot battle, or None when it can.

        The full set of conditions gates *entering* an area. Once a run is
        under way the pet has already committed to it, so falling sick or
        reaching its bedtime mid-area does not eject it - only running out of
        the battle cost does. Pass entering=False for that check.
        """
        module = get_module(self.module)
        # Conditions that knock a pet out at any point, mid-run included.
        if self.state == "dead":
            return "dead"
        if not self._has_battle_resources():
            cost_type = getattr(module, 'battle_cost_type', 'DP')
            have = self.hunger if cost_type == "Hunger" else self.dp
            if cost_type == "Hunger" and have <= 0:
                return "hungry"
            return (f"{cost_type.lower()}={have} < "
                    f"{getattr(module, 'battle_cost_amount', 1.0)}")
        if not entering:
            return None

        # Conditions that only decide whether a run may be started.
        if not getattr(module, 'care_can_battle_while_sick', False) and self.sick > 0:
            return f"sick={self.sick}"
        if self.stage <= 1:
            return f"stage={self.stage}"
        if self.power <= 0:
            return f"power={self.power}"
        if self.atk_main <= 0:
            return "no atk_main"
        if self._is_blocked_by_sleep():
            return f"asleep (state={self.state})"
        return None

    def can_battle(self):
        return self.battle_block_reason() is None

    def can_continue_battle(self):
        """Whether a pet already in an area may fight the next round."""
        return self.battle_block_reason(entering=False) is None

    def can_battle_pvp(self):
        return self.battle_block_reason() is None
    
    def can_train(self):
        module = get_module(self.module)
        if self.sick > 0 and not getattr(module, 'care_can_train_while_sick', False):
            return False
        return self.stage > 0 and self.state != "dead" and self.atk_main > 0 and not self._is_blocked_by_sleep()

    def set_back_to_sleep(self):
        self.back_to_sleep = get_module(self.module).back_to_sleep_time

    def check_disturbed_sleep(self):
        if self.state == "nap":
            runtime_globals.game_console.log(f"[DEBUG] Sleep disturbance {self.sleep_disturbances}")
            self.nap_until = None
            self.set_state("idle")
            self.sleep_disturbances += 1
            self.disturbance_penalty += 2
            self.set_back_to_sleep()
            self._check_disturbance_sickness()

    def _check_disturbance_sickness(self):
        """Every Nth sleep disturbance makes the pet sick, where a device says so.

        `care_disturbance_sickness_count` is that N and 0 switches it off, the
        way `care_poop_sickness_count` does for poop. It counts the pet's whole
        record rather than a run, so the tenth, twentieth and thirtieth each
        land; `sleep_disturbances` is also an evolution criterion, so it is
        never reset for this.
        """
        module = get_module(self.module)
        count = getattr(module, 'care_disturbance_sickness_count', 0)
        if count <= 0 or self.sleep_disturbances % count != 0:
            return
        effect = getattr(module, 'care_disturbance_sickness_effect', 'Dots')
        if effect == "Nothing":
            return
        self.set_sick("dots" if effect == "Dots" else "")
        runtime_globals.game_console.log(
            f"[!] {self.name} is sick from {self.sleep_disturbances} sleep "
            f"disturbances! Effect: {effect}")

    def get_hp(self):
        if not hasattr(self, 'hp') or self.hp == 0 or self.hp == None:
            self.hp = constants.HP_LEVEL[self.stage]

        # Level milestones and the Vital Values quarters; see core.pet_stats.
        # Devices that do not track Vital Values are unaffected: the bonus is
        # gated on the same visible_stats entry the meter itself keys off.
        vital_cap = self.vital_value_cap() if self.tracks_vital_values() else 0
        hp = pet_stats.hp_with_bonuses(
            self.hp, level=self.level,
            vital_values=getattr(self, "vital_values", 0), vital_cap=vital_cap)

        # Add bonus from status_change items
        if hasattr(self, 'bonus_stats') and len(self.bonus_stats) > 0:
            hp += self.bonus_stats[0]

        return hp

    #: The battle-stat tables live in core.pet_stats, where the arena engine
    #: reads them too; these names are kept for existing callers.
    VITAL_VALUE_CAPS = pet_stats.VITAL_VALUE_CAPS
    STRENGTH_BONUS_WEIGHT_CEILING = pet_stats.STRENGTH_BONUS_WEIGHT_CEILING
    POWER_STAGE_TABLES = pet_stats.POWER_STAGE_TABLES

    def tracks_vital_values(self):
        """Whether this pet's device has a Vital Values meter at all."""
        module = get_module(self.module)
        return pet_stats.tracks_vital_values(getattr(module, "visible_stats", []))

    def vital_value_cap(self):
        """The ceiling for this pet's stage, or 0 where it earns none."""
        return pet_stats.vital_value_cap(self.stage)

    def weight_floor(self):
        """How low losses take this pet's weight: min_weight, or 1 where the
        module allows going below it (care_allow_below_min_weight). A pet
        whose module is not loaded keeps min_weight, as before the setting."""
        try:
            module = get_module(self.module)
        except KeyError:
            module = None
        return pet_stats.weight_floor(
            getattr(self, "min_weight", 0),
            getattr(module, "care_allow_below_min_weight", False))

    def tracks_strength(self):
        """Whether this pet's device has a Strength meter at all."""
        module = get_module(self.module)
        return pet_stats.tracks_strength(getattr(module, "visible_stats", []))

    def strength_empty(self):
        """Strength at 0 on a device that has the meter. Without one (the
        iC, DW1) Strength is never filled, and its 0 means nothing."""
        return self.strength == 0 and self.tracks_strength()

    def strength_bonus_blocked(self) -> bool:
        """Whether the device is withholding the Strength Bonus."""
        return pet_stats.strength_bonus_blocked(self.weight, self.hunger)

    def get_power(self, bonus=0):
        """Battle power: the species base plus this device's bonus rule.

        The rule itself is ``core.pet_stats.power_with_bonus_rule``, which
        the module's ``power_bonus_rule`` selects.
        """
        module = get_module(self.module)
        rule = getattr(module, "power_bonus_rule", "Stage Table")
        power = self.power + bonus

        # Add bonus from vb status_change items
        if hasattr(self, 'bonus_stats') and len(self.bonus_stats) > 2:
            power += self.bonus_stats[2]

        return pet_stats.power_with_bonus_rule(
            rule, power, stage=self.stage, strength=self.strength,
            stomach=self.stomach, hunger=self.hunger, weight=self.weight,
            level=self.level, version=getattr(self, "version", 0),
            effort=self.effort, traited=self.traited, shook=self.shook,
            star=self.star, gcell_red=gcell_rules.is_red(module, self),
            effort_tiers=getattr(module, "effort_power_tiers", None))

    def get_attack(self):
        attack = 1 # constants.ATK_LEVEL[self.stage]

        if self.level >= 4:
            attack += 1
        if self.level >= 7:
            attack += 1
        
        # Add bonus from status_change items
        if hasattr(self, 'bonus_stats') and len(self.bonus_stats) > 1:
            attack += self.bonus_stats[1]
        
        return attack
    
    def award_trophies(self, amount=1):
        """Trophies a training earned: the VBE's PP, which a running PP
        multiplier item triples (utils.card_battle.boost_factor)."""
        from utils.card_battle import boost_factor
        gained = int(amount) * boost_factor(self, "pp")
        self.trophies += gained
        return gained

    def finish_training(self, won = False, grade=0, phase2=False, anguirus=False):
        """Apply one training's result.

        ``grade`` is the outcome level every training mode reports, 0-3 for
        Bad, Good, Great and Excellent — the same four levels the DM20, DMC
        and DMX connection protocols carry, where Bad is the failed attempt.
        The module's three tables are indexed by it directly, so a device that
        pays nothing for a failure simply starts its list with a zero and one
        that still credits effort does not.
        """
        module = get_module(self.module)
        level = max(0, min(3, int(grade)))
        if not won:
            level = 0

        self.effort += module.training_effort_gain[level]
        strength_gain = module.training_strength_gain[level]
        if strength_gain < 0:
            # -1 fills the meter outright, which is what a Megahit does on the
            # Pendulum Ver.20th
            self.strength = self.stomach or self.strength
        else:
            self.strength += strength_gain

        if won:
            self.set_state("happy2")
            self._apply_reliability_event('reliability_minigame_success')
            if self.disturbance_penalty >= 2:
                self.disturbance_penalty -= 2

            # Add training activity for vital_values (only once)
            if "training" not in self.vital_activities:
                self.vital_activities.append("training")
        else:
            self.set_state("angry")

        weight_loss = module.training_weight_loss[level]
        self.weight = max(self.weight_floor(), self.weight - weight_loss)
        self.update_99g_effect()

        # G-Cell points for training, in the module's style: DMGZ pays a
        # success or the phase failed in, PENGZ the grade.
        self._gcell_event("training", won=won, grade=grade, phase2=phase2, anguirus=anguirus)

    def finish_versus(self, won=False, opponent=None):
        self.battles += 1
        self._deduct_battle_cost()
        self.totalBattles += 1
        if won:
            self.set_state("happy3")
            self.win += 1
            self.totalWin += 1
            self._apply_reliability_event('reliability_battle_win')
            # A tagged opponent counts towards a defeat_tag route.
            if opponent is not None:
                evolution_rules.record_defeat(
                    self, get_module(getattr(opponent, "module", None) or self.module),
                    getattr(opponent, "name", ""), getattr(opponent, "version", None))
            
        # G-Cell points for the versus, in the module's style. PENGZ pays a
        # battle against one of its own pets by stage and one against another
        # module's pet ("another device") flat.
        other_device = (opponent is not None
                        and getattr(opponent, "module", self.module) != self.module)
        self._gcell_event("battle", won=won, other_device=other_device)

    def finish_battle(self, won, enemy, area, final = False, is_special_encounter=False,
                      enemy_module=None):
        self.battles += 1
        self._deduct_battle_cost()
        self.totalBattles += 1
        if won:
            if final:
                self.set_state("happy3")
            self.win += 1
            self.totalWin += 1
            self._apply_reliability_event('reliability_battle_win')
            sick_chance = get_module(self.module).battle_base_sick_chance_win

            # Mark special encounter flag on win (enables special evolution paths)
            if is_special_encounter:
                self.special_encounter = True

            # Add battle activity for vital_values (only once)
            if "battle" not in self.vital_activities:
                self.vital_activities.append("battle")

            if not hasattr(self, 'area'):
                self.area = 0
                
            if self.area < area:
                self.area = area
                runtime_globals.game_console.log(f"[DEBUG] {self.name} area increased to {self.area} (previous: {self.area})")

            if not hasattr(self, 'enemy_kills'):
                self.enemy_kills = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]

            self.enemy_kills[enemy.stage] += 1
            # A tagged enemy counts towards a defeat_tag route.
            evolution_rules.record_defeat(
                self, get_module(enemy_module or self.module),
                getattr(enemy, "name", ""), getattr(enemy, "version", None))
            
            # G-Cell Fragments are not won in battle: they are left behind on
            # death, alongside the Traited Egg roll (see set_traited_egg).

            # G-Cell points for the win (a random encounter's own), in the
            # module's style
            self._gcell_event("battle", won=True, special=is_special_encounter)
        else:
            # A loss always ends the run - there is no next round to carry on
            # to - so the pet shows its defeat pose whether or not this was
            # the boss. `final` only gates the win pose, which would otherwise
            # play between rounds of an area still in progress.
            self.set_state("lose")
            # Per-species injury chance on a loss, if the module gives one.
            # The Digimon Mini and Twin both start every Digimon at 10%.
            injury_chance = getattr(self, "injury_probability", 0) or 0
            if injury_chance > 0 and random.random() * 100 < injury_chance:
                self.set_sick()
            sick_chance = get_module(self.module).battle_base_sick_chance_lose
            
            # G-Cell points for the loss, in the module's style
            self._gcell_event("battle", won=False, special=is_special_encounter)
            if self.protein_overdose > get_module(self.module).protein_overdose_max:
                self.protein_overdose = get_module(self.module).protein_overdose_max
            sick_chance += self.protein_overdose * get_module(self.module).protein_penalty
            self.protein_overdose = 0

            if self.disturbance_penalty > get_module(self.module).disturbance_penalty_max:
                self.disturbance_penalty = get_module(self.module).disturbance_penalty_max

            sick_chance += self.disturbance_penalty
            self.disturbance_penalty = 0

        try:
            sc = float(sick_chance)
        except Exception:
            sc = 0.0
        # clamp percentage 0..100 then convert to 0.0..1.0
        sick_chance = max(0.0, min(sc, 100.0)) / 100.0
        
        if random.random() < sick_chance:
            self.set_sick()

    def add_experience(self, xp):
        self.experience += xp
        if self.level == constants.MAX_LEVEL[self.stage]:
            self.experience = 0
        if self.experience >= constants.EXPERIENCE_LEVEL[self.level+1]:
            self.experience -= constants.EXPERIENCE_LEVEL[self.level+1]
            self.level += 1
            #runtime_globals.game_message.add(f"Level UP!", (self.x + (PET_WIDTH // 2), self.y), FONT_COLOR_GREEN)
            if self.level == constants.MAX_LEVEL[self.stage]:
                self.experience = 0

    def should_sleep(self):
        if not self.sleeps or not self.wakes:
            return False
        
        # Use global sleep/wake if set
        global_sleep, global_wake = global_sleep_times()

        try:
            now_time = datetime.now().time()

            # Use global times if set
            if global_sleep is not None and global_wake is not None:
                sleep_time = global_sleep
                wake_time = global_wake
            elif self.sleeps and self.wakes:
                # Cache parsing whenever sleeps/wakes change
                if not hasattr(self, '_cached_sleep_time') or self._last_sleeps != self.sleeps or self._last_wakes != self.wakes:
                    self._cached_sleep_time = datetime.strptime(self.sleeps.strip(), "%H:%M").time()
                    self._cached_wake_time = datetime.strptime(self.wakes.strip(), "%H:%M").time()
                    self._last_sleeps = self.sleeps
                    self._last_wakes = self.wakes
                sleep_time = self._cached_sleep_time
                wake_time = self._cached_wake_time
            else:
                return False

            if sleep_time < wake_time:
                return sleep_time <= now_time < wake_time
            else:
                return now_time >= sleep_time or now_time < wake_time

        except Exception as e:
            runtime_globals.game_console.log(f"[!] Error parsing sleep range: {e}")
            return False

    def check_wake_up(self):
        now = datetime.now()

        # A nap an item started (Digi Bedding) ends on its own time, unless
        # it has run into the pet's bedtime, when the pet sleeps on.
        nap_until = getattr(self, 'nap_until', None)
        if nap_until is not None:
            if now < nap_until:
                return
            self.nap_until = None
            if not self.should_sleep():
                self.set_state("idle")
            return

        if not hasattr(self, 'sleep_start_time'):
            return

        _, global_wake = global_sleep_times()

        try:
            # Use global wake time if set
            if global_wake is not None:
                wake_time = global_wake
            elif self.wakes:
                # Cache parsing if wakes change
                if not hasattr(self, '_cached_wake_time') or self._last_wakes != self.wakes:
                    self._cached_wake_time = datetime.strptime(self.wakes.strip(), "%H:%M").time()
                    self._last_wakes = self.wakes
                wake_time = self._cached_wake_time
            else:
                return

            # Wake up if it's the wake time exactly (match hour and minute)
            if now.hour == wake_time.hour and now.minute == wake_time.minute:
                slept_seconds = (now - self.sleep_start_time).total_seconds()
                slept_hours = int(slept_seconds // 3600)

                if slept_hours >= constants.SLEEP_RECOVERY_HOURS:
                    self.dp = self.energy
                    runtime_globals.game_console.log(f"{self.name} slept {slept_hours}h and recovered DP!")

                self.set_state("idle")
                runtime_globals.game_console.log(f"{self.name} woke up naturally at {wake_time.strftime('%H:%M')}")

        except Exception as e:
            runtime_globals.game_console.log(f"[!] Error parsing wake time: {e}")

    def __getstate__(self):
        state = self.__dict__.copy()
        state.pop("frames", None)
        # Convert monotonic timestamps to elapsed seconds for serialization
        now = time.monotonic()
        state['_rt_elapsed_sec'] = now - self._rt_origin
        if self._rt_dead_start > 0:
            state['_rt_dead_elapsed_sec'] = now - self._rt_dead_start
        else:
            state['_rt_dead_elapsed_sec'] = 0.0
        # Remove non-serializable monotonic timestamps
        state.pop('_rt_origin', None)
        state.pop('_rt_last_sleep_check', None)
        state.pop('_rt_dead_start', None)
        state.pop('_rt_restored_at', None)
        # Remove deprecated keys from old system
        state.pop('_rt_age_origin', None)
        return state
    
    def __setstate__(self, state):
        self.__dict__.update(state)
        now = time.monotonic()
        # Restore monotonic timestamp for per-minute tick
        rt_elapsed = state.get('_rt_elapsed_sec', None)
        if rt_elapsed is None:
            rt_elapsed = getattr(self, 'timer', 0) / 30
        self._rt_origin = now - rt_elapsed
        self._rt_last_sleep_check = now
        self._rt_restored_at = now  # the save's moment on this clock (Android checkpoint)
        dead_elapsed = state.get('_rt_dead_elapsed_sec', 0.0)
        self._rt_dead_start = (now - dead_elapsed) if dead_elapsed > 0 else 0.0
        # Ensure minute counter exists
        if not hasattr(self, '_rt_last_minute'):
            self._rt_last_minute = int(rt_elapsed / 60)
        # Migrate old age system to midnight-based
        if not hasattr(self, '_last_age_date'):
            self._last_age_date = datetime.now().date()
        # Migrate old elapsed-minute counters to new countdown/countup system
        if not hasattr(self, '_evol_minutes'):
            self._evol_minutes = int(rt_elapsed / 60)
        if not hasattr(self, '_cd_hunger'):
            self._cd_hunger = getattr(self, 'hunger_loss', 0) or 0
        if not hasattr(self, '_cd_strength'):
            self._cd_strength = getattr(self, 'strength_loss', 0) or 0
        if not hasattr(self, '_cd_poop'):
            self._cd_poop = getattr(self, 'poop_timer', 60) or 60
        if not hasattr(self, 'evolution_history'):
            self.evolution_history = []
        # A save from before form time: the evolution count-up is the best
        # record of how long the pet has been in this form.
        if not hasattr(self, 'form_minutes'):
            self.form_minutes = getattr(self, '_evol_minutes', 0) or 0
        if not hasattr(self, 'evolution_failed'):
            self.evolution_failed = False
        if not hasattr(self, 'tag_defeats'):
            self.tag_defeats = {}
        if not hasattr(self, 'accessory'):
            self.accessory = None
        if not hasattr(self, 'nap_until'):
            self.nap_until = None
        if not hasattr(self, 'connect_points'):
            self.connect_points = 0
        if not hasattr(self, 'encounter_rotation'):
            self.encounter_rotation = 0
        if not hasattr(self, 'active_boost'):
            self.active_boost = None
        if not hasattr(self, 'event_sequence'):
            self.event_sequence = {}
        # Clean up serialization-only and deprecated keys
        for key in ('_rt_elapsed_sec', '_rt_age_elapsed_sec', '_rt_dead_elapsed_sec',
                    '_rt_age_origin', '_rt_last_age_day',
                    '_rt_last_hunger_min', '_rt_last_strength_min', '_rt_last_poop_min'):
            self.__dict__.pop(key, None)
        self.load_sprite()
        if self.state == "dead":
            runtime_globals.pet_sprites[self][0] = image_load(constants.DEAD_FRAME_PATH).convert_alpha()
            runtime_globals.pet_sprites[self][0] = pygame.transform.scale(runtime_globals.pet_sprites[self][0], (runtime_globals.PET_WIDTH, runtime_globals.PET_HEIGHT))
            runtime_globals.pet_sprites[self][1] = runtime_globals.pet_sprites[self][0]

    def patch(self):
        module = get_module(self.module)
        if not hasattr(self, "digisoul"):
            self.digisoul = ""
        # DigiSoul is immutable species metadata, so old saves can safely
        # recover it from the current module without touching care progress.
        try:
            monster = module.get_monster(self.name, self.version) if module else None
            if monster is not None:
                self.digisoul = monster.get("digisoul", "")
        except Exception:
            pass
        # Saves made while a keep-counts module never set them (see reset_variables).
        if not hasattr(self, "win"):
            self.win = 0
        if not hasattr(self, "battles"):
            self.battles = 0
        if not hasattr(self, "reliability"):
            base = getattr(module, 'reliability_base', constants.RELIABILITY_MIN)
            self.reliability = int(base)
        self.reliability = max(constants.RELIABILITY_MIN,
                               min(constants.RELIABILITY_MAX, int(self.reliability)))
        # The DNA queue (`add_dna`). A save from before it held per-type
        # totals; those are dropped, not converted (still in development).
        old_dna = getattr(self, "dna", None)
        self.dna = ([str(d) for d in old_dna if d in constants.DIGISOUL_DNA_TYPES]
                    [-constants.DNA_QUEUE_SIZE:] if isinstance(old_dna, list) else [])
        if not hasattr(self, "_cd_reliability"):
            self._cd_reliability = 60
        if not hasattr(self, "injury_rate"):
            self.injury_rate = 0
        if not hasattr(self, "unflushed_poops"):
            self.unflushed_poops = 0
        if not hasattr(self, "poop_mistake_timers"):
            self.poop_mistake_timers = []
        if not hasattr(self, "virus"):
            self.virus = 0
        if not hasattr(self, "_reliability_sleep_call_resolved"):
            self._reliability_sleep_call_resolved = False
        if not hasattr(self, "trophies"):
            self.trophies = 0
        if not hasattr(self, "vital_values"):
            self.vital_values = 0
        if not hasattr(self, "vital_activities"):
            self.vital_activities = []
        if not hasattr(self, "dirty"):
            self.dirty = True  # Force initial update
            self.cache_x = -1  # Invalid initial value to force update
            self.cache_frame_index = -1  # Invalid initial value to force update
            self.cache_has_overlay = False
        if not hasattr(self, "quests_completed"):
            self.quests_completed = 0
        if not hasattr(self, "pvp_wins"):
            self.pvp_wins = 0
        if not hasattr(self, "pvp_battles"):
            self.pvp_battles = 0
        if not hasattr(self, "protein_feedings"):
            self.protein_feedings = 0
        if not hasattr(self, "edited"):
            self.edited = False
        if not hasattr(self, "gcell_points"):
            self.gcell_points = 0
        if not hasattr(self, "gcell_fragment"):
            self.gcell_fragment = False
        if not hasattr(self, "form_minutes"):
            self.form_minutes = getattr(self, "_evol_minutes", 0) or 0
        if not hasattr(self, "evolution_failed"):
            self.evolution_failed = False
        if not hasattr(self, "tag_defeats"):
            self.tag_defeats = {}
        if not hasattr(self, "death_save_b_counter"):
            self.death_save_b_counter = 0
        if not hasattr(self, "death_save_shake_counter"):
            self.death_save_shake_counter = 0
        if not hasattr(self, "death_save_immunity"):
            self.death_save_immunity = 0
        if not hasattr(self, "bonus_stats"):
            self.bonus_stats = [0, 0, 0]
        if not hasattr(self, "atk_alt_2"):
            # Migrate old saves that stored the field without underscore
            self.atk_alt_2 = getattr(self, "atk_alt2", 0)
        if not hasattr(self, "evolution_history"):
            self.evolution_history = []
        if not hasattr(self, "temp_evolve"):
            self.temp_evolve = []
        # Routes pickled into an old save are still in the old jogress shape.
        # refresh_pet_evolutions() re-reads most pets from their module at
        # boot, but one whose species has since left the module is skipped
        # there, so migrate whatever the save carried as well.
        try:
            from utils.jogress_utils import normalize_evolutions
            self.evolve = normalize_evolutions(getattr(self, "evolve", None) or [])
        except Exception:
            pass
        if not hasattr(self, "availability"):
            # Migrate old saves that stored these under the misspelled name
            self.availability = getattr(self, "avaliability", "Normal")
        if not hasattr(self, "jogress_available"):
            self.jogress_available = int(getattr(self, "jogress_avaliable", 0))
        if not hasattr(self, "device_version"):
            # Saves created before the device system use the gameplay version
            # as their safe backward-compatible protocol value.
            self.device_version = int(getattr(self, "version", 0))
        elif (getattr(self, "module", None) == "PENZ"
                and int(self.device_version) <= 5):
            # The Pendulum Z announces **module version + 5** on the wire --
            # 6 to 11 -- and its `devices.json` now says so, which is what
            # stopped an OEM pet claiming a version the device rejects. A pet
            # hatched before that carries the old 1-5 (and 0 for the Virus
            # Busters), so it would still announce the wrong one.
            #
            # The old numbering is not a clean offset -- the Virus Busters
            # were 0 where their module version is 6 -- so this is derived
            # from the module version rather than added to what is there. The
            # two ranges are disjoint, which is what makes "<= 5" a safe test
            # for "this save predates the change".
            self.device_version = int(getattr(self, "version", 1)) + 5
        elif (getattr(self, "module", None) in COLOUR_CROSSOVER_MODULES
                and int(getattr(self, "device_version", 0))
                    != COLOUR_CROSSOVER_VERSION):
            # A crossover Digital Monster Color -- Monster Hunter, Godzilla,
            # Xros Wars -- announces **5**, which is how a device says "I am
            # not one of the five". Each of those modules ships exactly one
            # device, so there is nothing to derive: any pet from one of them
            # announces 5, and a pet hatched before the renumber carried 1
            # and claimed to be a Digital Monster Color Ver.1.
            self.device_version = COLOUR_CROSSOVER_VERSION
        elif (getattr(self, "module", None) == "DMC"
                and int(getattr(self, "device_version", 0)) >= 1
                and int(getattr(self, "device_version", 0))
                    == int(getattr(self, "version", 0))):
            # The Digital Monster Color numbers its releases from **zero** --
            # Ver.1 announces 0 -- and its `devices.json` now says so, where
            # it used to list 1-5 and have `VERSION_OFFSET` take one off at
            # send time. A pet hatched before that carries the old value and
            # would announce one release too high.
            #
            # The test is that `device_version` still equals the gameplay
            # `version`, which is exactly what the old table produced and
            # what the new one never does: after the renumber a Ver.1 pet is
            # version 1 / device_version 0.
            self.device_version = int(self.device_version) - 1
        # Repair a pet left stuck in a temporary evolution.
        #
        # Temporary evolutions used to be applied by overwriting the pet's own
        # fields and keeping a backup to undo afterwards. Pets are pickled
        # whole, so a game closed mid-battle saved the evolved stats and the
        # pet stayed transformed for good. The form is now a separate
        # battle-only object that cannot touch the pet at all, but a save made
        # before that still has to be put right: restore the backup if it
        # survived, and drop the leftover fields either way.
        backup = getattr(self, "xros_backup", None)
        if backup:
            for field, value in backup.items():
                setattr(self, field, value)
            runtime_globals.game_console.log(
                f"[Xros] Restored {self.name} from a stuck temporary evolution")
        if hasattr(self, "xros_backup"):
            del self.xros_backup
        if hasattr(self, "xros_evolved"):
            del self.xros_evolved
        # Migrate / repair real-time timer attributes
        now = time.monotonic()
        if not hasattr(self, '_rt_origin'):
            fps = getattr(constants, 'FRAME_RATE', 30) or 30
            elapsed_sec = getattr(self, 'timer', 0) / fps
            self._rt_origin = now - elapsed_sec
            self._rt_last_sleep_check = now
            self._rt_dead_start = now if self.state == "dead" else 0.0
            self._rt_last_minute = int(elapsed_sec / 60)
        else:
            if not hasattr(self, '_rt_last_minute'):
                self._rt_last_minute = int((now - self._rt_origin) / 60)
            if not hasattr(self, '_rt_last_sleep_check'):
                self._rt_last_sleep_check = now
            if not hasattr(self, '_rt_dead_start'):
                self._rt_dead_start = now if self.state == "dead" else 0.0
        # Migrate to countdown/countup counter system
        if not hasattr(self, '_last_age_date'):
            self._last_age_date = datetime.now().date()
        if not hasattr(self, '_evol_minutes'):
            self._evol_minutes = int((now - self._rt_origin) / 60)
        if not hasattr(self, '_cd_hunger'):
            self._cd_hunger = getattr(self, 'hunger_loss', 0) or 0
        if not hasattr(self, '_cd_strength'):
            self._cd_strength = getattr(self, 'strength_loss', 0) or 0
        if not hasattr(self, '_cd_poop'):
            self._cd_poop = getattr(self, 'poop_timer', 60) or 60
        # Clean up deprecated attributes from old timer system
        for key in ('_rt_age_origin', '_rt_last_age_day',
                    '_rt_last_hunger_min', '_rt_last_strength_min', '_rt_last_poop_min'):
            self.__dict__.pop(key, None)

    def get_blue_gcells(self):
        """
        Returns the number of blue G-Cells based on gcell_points.
        Blue G-Cells: 1 every 8 points, max 14 at 112+ points.
        """
        if self.gcell_points >= 112:
            return 14
        return min(14, self.gcell_points // 8)

    def get_yellow_gcells(self):
        """
        Returns the number of yellow G-Cells based on gcell_points.
        Yellow G-Cells: 1 every 12 points between 113-232, max 10.
        """
        if self.gcell_points < 113:
            return 0
        if self.gcell_points >= 232:
            return 10
        return min(10, (self.gcell_points - 112) // 12)

    def get_red_gcells(self):
        """
        Returns the number of red G-Cells based on gcell_points.
        Red G-Cells: 1 every 12 points between 233-472, max 20.
        """
        if self.gcell_points < 233:
            return 0
        if self.gcell_points >= 472:
            return 20
        return min(20, (self.gcell_points - 232) // 12)

    def get_gcell_level(self):
        """
        Returns the current G-Cell meter level (1-4) based on gcell_points.
        Level 1: 0-112 points (Blue)
        Level 2: 113-232 points (Yellow)
        Level 3: 233-352 points (Red)
        Level 4: 353-472 points (Red)
        """
        if self.gcell_points <= 112:
            return 1
        elif self.gcell_points <= 232:
            return 2
        elif self.gcell_points <= 352:
            return 3
        else:
            return 4

    def _gcell_event(self, event, **kwargs):
        """Apply an event's G-Cell points in the module's style
        (utils.gcell_rules.gain)."""
        points = gcell_rules.gain(get_module(self.module), self, event, **kwargs)
        if points:
            self.add_gcell_points(points)

    def add_gcell_points(self, points):
        """
        Adds G-Cell points, kept between 0 and the module style's cap
        (DMGZ 472; PENGZ 14 cells of the stage's size).
        Returns the actual amount added/subtracted.
        """
        actual_change = gcell_rules.add_points(get_module(self.module), self, points)
        
        if actual_change != 0:
            runtime_globals.game_console.log(f"[G-Cell] {self.name} {'+' if actual_change > 0 else ''}{actual_change} points. Total: {self.gcell_points}")
        
        return actual_change

    def add_reliability(self, amount):
        """Add a signed Reliability amount and clamp the pet to 0..31.

        Returns the actual change after applying the bounds, which lets
        callers distinguish a configured event from one that hit a limit.
        """
        try:
            amount = int(amount)
        except (TypeError, ValueError):
            return 0

        old_value = max(constants.RELIABILITY_MIN,
                        min(constants.RELIABILITY_MAX,
                            int(getattr(self, 'reliability', constants.RELIABILITY_MIN))))
        self.reliability = max(
            constants.RELIABILITY_MIN,
            min(constants.RELIABILITY_MAX, old_value + amount)
        )
        actual_change = self.reliability - old_value
        if actual_change:
            runtime_globals.game_console.log(
                f"[Reliability] {self.name} {actual_change:+d}. Total: {self.reliability}")
        return actual_change

    def add_dna(self, digisoul_type, amount):
        """Feed *amount* DigiSoul DNA of one type: each feed joins the end of
        the queue, and past constants.DNA_QUEUE_SIZE the oldest falls out.
        Returns how many were fed (0 for an unknown type or no amount)."""
        canonical_type = next(
            (known for known in constants.DIGISOUL_DNA_TYPES
             if known.casefold() == str(digisoul_type).strip().casefold()),
            None
        )
        if canonical_type is None:
            runtime_globals.game_console.log(
                f"[!] Unknown DigiSoul DNA type: {digisoul_type}")
            return 0
        try:
            amount = int(amount)
        except (TypeError, ValueError):
            return 0
        if amount <= 0:
            return 0
        if not isinstance(getattr(self, "dna", None), list):
            self.dna = []
        self.dna.extend([canonical_type] * amount)
        del self.dna[:-constants.DNA_QUEUE_SIZE]
        runtime_globals.game_console.log(
            f"[DigiSoul DNA] {self.name} fed {amount} {canonical_type}. "
            f"Leading: {self.leading_dna()}")
        return amount

    def add_weight(self, amount):
        """Add an item's signed weight change, at any stage.

        Capped at 99 and floored at the species' minimum weight, so -99
        takes a pet to its minimum. Returns the change actually made.
        """
        try:
            amount = int(amount)
        except (TypeError, ValueError):
            return 0
        if not amount:
            return 0
        old = int(self.weight or 0)
        if amount > 0:
            new = min(max(old, 99), old + amount)
        else:
            floor = self.weight_floor()
            new = max(min(old, floor), old + amount)
        self.weight = new
        self.update_99g_effect()
        return new - old

    def add_injury_rate(self, amount):
        """Add signed injury-rate points, never below zero. Returns the change.

        The Digimon Twin's special foods carry them (+1% injury chance per 4
        points, utilities/TWIN/TWIN_RESEARCH.md); the injury roll does not
        read them yet.
        """
        try:
            amount = int(amount)
        except (TypeError, ValueError):
            return 0
        old = max(0, int(getattr(self, "injury_rate", 0) or 0))
        self.injury_rate = max(0, old + amount)
        return self.injury_rate - old

    def devolve(self):
        """Return to the form this pet evolved from (an item's `devolve`).

        `evolution_history` lists the forms the pet has been, oldest first.
        A jogress also records its partner there, at the stage the pet then
        had, so the form to return to is the latest entry of a lower stage
        than the current one -- never an egg. That entry and everything
        after it leave the history, which is then as it stood while the pet
        was that form. The pet takes the form as an evolution does
        (`set_data`, `reset_variables`), without the evolution's sound,
        Digidex entry or reward.

        Returns False, changing nothing, when no such form is found in the
        pet's module.
        """
        module = get_module(self.module)
        if module is None:
            return False
        history = list(getattr(self, "evolution_history", None) or [])
        for index in range(len(history) - 1, -1, -1):
            data = module.find_monster(history[index], self.version)
            if data is None:
                continue
            stage = int(data.get("stage", 0) or 0)
            if 1 <= stage < int(self.stage or 0):
                break
        else:
            return False

        runtime_globals.game_console.log(f"Devolving {self.name} to {data['name']}")
        self.dna = []
        self.evolution_history = history[:index]
        pet_data = dict(data)
        pet_data["module"] = module.name
        self.set_data(pet_data)
        self.reset_variables()
        self.load_sprite()
        self.set_state("happy1")
        return True

    def _apply_reliability_event(self, module_field):
        """Apply one signed Reliability delta configured by the module."""
        module = get_module(self.module)
        return self.add_reliability(getattr(module, module_field, 0) if module else 0)

    def update_reliability(self, minutes_passed):
        """Advance the independent recurring Reliability timer."""
        if minutes_passed <= 0:
            return
        if not hasattr(self, '_cd_reliability') or self._cd_reliability <= 0:
            self._cd_reliability = 60
        self._cd_reliability -= minutes_passed
        while self._cd_reliability <= 0:
            self._apply_reliability_event('reliability_hourly')
            self._cd_reliability += 60
