#=====================================================================
# BattleEncounter
#=====================================================================

import math
import random
import pygame
from typing import List, Optional
from ui.minigames.count_match import CountMatch
from ui.minigames.count_match_classic import CountMatchClassic
from ui.minigames.count_match_z import CountMatchZ
from ui.minigames.dummy_charge import DummyCharge
from ui.minigames.shake_punch import ShakePunch
from ui.minigames.xai_roll import XaiRoll
from ui.minigames.xai_bar import XaiBar
from ui.ui_manager import UIManager
from ui.components.animated_sprite import AnimatedSprite
from ui.components.hp_bar import HPBar
from ui.components.label import Label
from ui.components.label_value import LabelValue

from ui import ui_constants
from core import game_globals, runtime_globals
from models.animation import PetFrame
from battle.game_battle import GameBattle
from battle.sim.models import Digimon, BattleProtocol
from battle.sim import protocol_constants
from models.game_module import sprite_load
from utils.module_utils import get_module
from utils.pet_utils import (distribute_pets_evenly, get_battle_targets,
                             get_battle_continue_targets)
from utils.pygame_utils import blit_with_cache, get_font, load_attack_sprites, load_crit_attack_sprites, module_attack_sprites, module_crit_attack_sprites, sprite_load_percent
from utils.scene_utils import change_scene
from utils.utils_unlocks import unlock_item
from utils import inventory_utils
from battle.sim.global_battle_simulator import GlobalBattleSimulator
from core import constants
from battle import combat_constants
from models.game_quest import QuestType
from utils.quest_event_utils import update_quest_progress
from services.omninet_service import omninet_service
from training.training import TRAINING_READY_SOUND


# Minigames that draw the alert phase themselves, as
# ``battle_minigame -> (attribute the instance lives on, class)``. Count Match
# Color puts up an attribute-specific ready sprite and Count Match Z the
# arrows to match, both before the count begins; everything else leaves the
# alert phase to the animated ready sprite. Built from the classes' own
# HAS_READY_PHASE flag, so giving a minigame a ready phase is one change in
# the minigame itself — Count Match Classic starts at "charge" and drops out
# of this map on its own.
READY_PHASE_MINIGAMES = {
    name: (attribute, minigame_class)
    for name, attribute, minigame_class in (
        ("Count Match Color", "count_match", CountMatch),
        ("Count Match Z", "count_match_z", CountMatchZ),
        ("Count Match Classic", "count_match_classic", CountMatchClassic),
    )
    if getattr(minigame_class, "HAS_READY_PHASE", False)
}

#=====================================================================
# BattleEncounter Class
#=====================================================================

BAR_COUNTER = 20  # Number of frames for the bar counter

class BattleEncounter:
    """
    Handles the logic and rendering for a battle encounter.
    """

    #========================
    # Region: Setup & State
    #========================

    def __init__(self, module, area=0, round=0, version=1, pvp_mode=False, is_special_encounter=False,
                 encounter_name=None):
        """
        Initializes the BattleEncounter, loading graphics and setting initial state.
        """
        # Load module-specific attack sprites for pets and enemies
        self.pvp_mode = pvp_mode
        self.is_special_encounter = is_special_encounter
        # Names the exact enemy for a special encounter; a Friend event picks
        # one specific Friend and it must be the one fought.
        self.encounter_name = encounter_name
        # real pet -> its battle-only evolved form, for this battle only.
        self.xros_forms = {}
        self.module_attack_sprites = {}
        self.module_crit_attack_sprites = {}
        self.module = get_module(module)
        self.set_initial_state(area, round, version)

        # Initialize UI Manager and AnimatedSprite component for battle result animations
        self.ui_manager = UIManager()
        self.animated_sprite = AnimatedSprite(self.ui_manager)

        # Initialize minigames for different rulesets
        self.reset_minigames()

        # Create a top-centered HPBar using screen/global coordinates (not within the reduced UI area)
        width_scale = runtime_globals.SCREEN_WIDTH / 240
        left_bar_w = int(100 * width_scale)
        center_s = int(29 * width_scale)
        right_bar_w = int(100 * width_scale)
        total_w = left_bar_w + center_s + right_bar_w
        bar_h = max(29, int(29 * width_scale))
        x = (runtime_globals.SCREEN_WIDTH - total_w) // 2
        y = int(6 * width_scale)

        self.hp_bar = HPBar(0, 0, total_w, bar_h)
        # Position using screen coordinates so UIManager scaling isn't required for placement
        self.hp_bar.rect = pygame.Rect(x, y, total_w, bar_h)
        # Provide ui_scale via manager so internal scaling of bar internals matches screen sizing
        self.hp_bar.manager = self.ui_manager
        # Default mode for non-versus encounters - pass module for BattleIcon display
        self.hp_bar.set_mode('adventure', module=self.module)
        # Attempt to load center sprite now that manager is available
        self.hp_bar.on_manager_set()
        # Initialize totals if battle_player already exists
            
        self.hp_bar.set_totals(self.battle_player.team2_total_hp, self.battle_player.team1_total_hp)
        self.hp_bar.set_values(self.battle_player.team2_total_hp, self.battle_player.team1_total_hp)


        self.font = get_font(runtime_globals.FONT_SIZE_LARGE)
        self.font_small = get_font(runtime_globals.FONT_SIZE_MEDIUM)
        # Note: All sprites now handled by AnimatedSprite component

        self.attack_sprites = load_attack_sprites()
        self.crit_attack_sprites = load_crit_attack_sprites()

        self.load_module_attack_sprites()
        
        self.hit_animation_frames = self.load_hit_animation()
        self.hit_animations = []
        self.turn_limit = 12
        #: Frames held on the battle screen after the last blow lands, so the
        #: hit animation and the HP bar's drain are watched rather than
        #: glimpsed. None while the battle is still running.
        self._battle_end_frames = None
        self.super_hits = 0
        self.color_band = None
        self.strength = 0
        #: Set when the charge was already made and sent elsewhere (DCom).
        self.skip_charge = False

        # Cache for result screen rendering (everything except animated pets)
        self.result_surface_cache = None
        self.result_animation_started = False

        # Load KO overlay sprite, scaled to pet size (preserving aspect ratio)
        self._ko_sprite = self._load_ko_sprite(runtime_globals.PET_WIDTH, runtime_globals.PET_HEIGHT)
        boss_w = runtime_globals.PET_WIDTH_BOSS
        boss_h = runtime_globals.PET_HEIGHT_BOSS
        self._ko_sprite_boss = self._load_ko_sprite(boss_w, boss_h)
        

    def _current_targets(self):
        """The pets this encounter is fighting with right now.

        Round 1 applies the full entry rule; later rounds use the looser one
        so a pet that fell sick mid-area keeps its place instead of vanishing
        from the layout and minigames while still being on the team.

        A pet in a temporary evolution is swapped for its battle-only form
        here, and only here — the party list itself always holds the real
        pets. Sequential rounds rebuild the team every round, so the swap has
        to happen on every lookup rather than once.
        """
        pets = (get_battle_targets() if self.round <= 1
                else get_battle_continue_targets())
        if not self.xros_forms:
            return pets
        return [self.xros_forms.get(pet, pet) for pet in pets]

    def _play_shot_sound(self, team_hp):
        """Play the attack sound for a shot, if the firing team is small.

        Training plays this on every shot, but a full row of pets firing at
        once in battle turns it into noise, which is why the battle shot was
        silent. With two or fewer still standing the shots are sparse enough
        that the silence is what reads as wrong, so the sound comes back.
        """
        if sum(1 for hp in team_hp if hp > 0) <= 2:
            runtime_globals.game_sound.play("attack")

    def set_initial_state(self, area=0, round=0, version=1):
        """
        Set all non-graphic variables for (re)initialization.
        """
        # Kept so area progress can be checked against the module's area locks.
        self.version = version
        # --- Jumper Gate: skip to boss if status_boost is active ---
        if not self.pvp_mode:
            skip_effect = self.get_battle_effect("skip_to_boss")
            if skip_effect and skip_effect.get("amount", 0) > 0:
                # Find the next boss round for this area
                current_area = game_globals.battle_area[self.module.name] if area == 0 else area
                round_to_check = game_globals.battle_round[self.module.name] if round == 0 else round
                # Only skip if not already at boss
                while not self.module.is_boss(current_area, round_to_check, version):
                    round_to_check += 1
                # Use local variables for area and round
                area = current_area
                round = round_to_check  # Set round to boss round

        self.phase = "level"
        self.after_attack_phase = None
        self.victory_status = None
        self.bonus_experience = 0
        self.frame_counter = 0
        self.result_timer = 0
        self.enemies = []
        #: The device line this battle is fought on, for a DCom/WiFiCom
        #: battle -- set by the scene once the exchange data is in. An
        #: adventure or local battle leaves it None and keeps the module's
        #: own presentation rules.
        self.battle_format = None

        # Per-battle draw caches: mirrored enemy frames, 2x crit slide-in
        # sprites, and the per-turn attack-log entries the draw loop needs.
        self._enemy_flip_cache = {}
        self._special_slide_cache = {}
        self._attack_entry_cache = {}

        # Reset result screen cache
        self.result_surface_cache = None
        self.result_animation_started = False

        if self.pvp_mode:
            self.area = 0
            self.round = 0

            self.boss = False
            self.enemy_entry_counter = 0
        else:
            # Use self.area and self.round, not the global values
            self.area = area if area != 0 else game_globals.battle_area[self.module.name]
            self.round = round if round != 0 else game_globals.battle_round[self.module.name]

            self.boss = self.module.is_boss(self.area, self.round, version)
            # For "Next and Reset" style, only flag as boss on the very last area
            if self.boss and getattr(self.module, 'adventure_style', 'Area Selection') == "Next and Reset":
                if self.module.area_exists(self.area + 1):
                    self.boss = False
            self.enemy_entry_counter = runtime_globals.PET_WIDTH + (2 * runtime_globals.UI_SCALE)

            # --- Apply XAI roll boost (Seven Switch) ---
            xai_effect = self.get_battle_effect("xai_roll")
            if xai_effect:
                xai_val = xai_effect.get("amount", None)
                if xai_val is not None:
                    runtime_globals.game_console.log(f"[BattleEncounter] XAI roll boost applied: {xai_val}")

            # --- Apply EXP multiplier boost (EXP Coat) ---
            exp_effect = self.get_battle_effect("exp_multiplier")
            if exp_effect:
                exp_val = exp_effect.get("amount", None)
                if exp_val is not None:
                    runtime_globals.game_console.log(f"[BattleEncounter] EXP multiplier boost applied: x{exp_val}")

            # --- Apply Jumper Gate boost ---
            skip_effect = self.get_battle_effect("skip_to_boss")
            if skip_effect:
                skip_val = skip_effect.get("amount", None)
                if skip_val:
                    runtime_globals.game_console.log(f"[BattleEncounter] Jumper Gate: Skipping to boss round.")

        if self.pvp_mode:
            self.hp_boost = 0
            self.attack_boost = 0
            self.strength_bonus = 0
            self.power_bonus = 0
        else:
            self.load_enemies()

            # --- Apply HP boost from status_boost items if present ---
            self.hp_boost = 0
            hp_effect = self.get_battle_effect("hp")
            if hp_effect:
                self.hp_boost = hp_effect.get("amount", 0)
                runtime_globals.game_console.log(f"[BattleEncounter] HP boost applied: +{self.hp_boost}")

            # --- Apply Attack boost from status_boost items (DMX ruleset) ---
            self.attack_boost = 0
            attack_effect = self.get_battle_effect("attack")
            if attack_effect:
                self.attack_boost = attack_effect.get("amount", 0)
                runtime_globals.game_console.log(f"[BattleEncounter] Attack boost applied: +{self.attack_boost}")

            # --- Apply Strength boost from status_boost items (PW Board) ---
            self.strength_bonus = 0
            strength_effect = self.get_battle_effect("strength")
            if strength_effect:
                self.strength_bonus = strength_effect.get("amount", 0)
                runtime_globals.game_console.log(f"[BattleEncounter] Strength boost applied: +{self.strength_bonus}")

            # --- Apply Power boost from status_boost items ---
            self.power_bonus = 0
            power_effect = self.get_battle_effect("power")
            if power_effect:
                self.power_bonus = power_effect.get("amount", 0)
                runtime_globals.game_console.log(f"[BattleEncounter] Power boost applied: +{self.power_bonus}")

        # Round 1 of an area is the entry check; later rounds use the looser
        # rule so a pet that fell sick mid-run is not silently dropped.
        self.battle_player = GameBattle(self._current_targets(), self.enemies, self.hp_boost, self.attack_boost, self.module)
        # PvP ordering flag: when True, enemy actions are processed before pets
        self.enemy_first = False
        
        # For PvP mode, use staggered cooldowns to prevent simultaneous attacks
        if self.pvp_mode:
            self.battle_player.reset_cooldowns_staggered()

        # Debug battle log display (when DEBUG flag is on)
        self.debug_battle_logs = []  # List of log entries per pet position: [{"turn": int, "hit": str, "arrow": str}, ...]
        self.init_debug_battle_logs()

        # Reload module attack sprites for the current battle participants
        self.load_module_attack_sprites()
        
        # Reset minigames and counters
        self.reset_minigames()
        
        # Reset and update HPBar with new battle values
        if hasattr(self, 'hp_bar') and self.hp_bar:
            self.hp_bar.set_totals(self.battle_player.team2_total_hp, self.battle_player.team1_total_hp)
            self.hp_bar.set_values(self.battle_player.team2_total_hp, self.battle_player.team1_total_hp)

    def prime_enemy_first(self):
        """Configure this encounter so enemy actions are processed before pets.

        This sets the flag and primes the BattlePlayer shot/phase arrays so
        the enemy (team2) will fire on the first update cycle.
        """
        self.enemy_first = True
        if not hasattr(self, 'battle_player') or self.battle_player is None:
            return
        bp = self.battle_player
        # Set enemy_first on GameBattle so it knows to increment turns after pet attacks
        bp.enemy_first = True
        n = max(len(bp.team1), len(bp.team2))
        for i in range(n):
            if i < len(bp.team1_shot):
                bp.team1_shot[i] = False
            if i < len(bp.team2_shot):
                bp.team2_shot[i] = True
            if i < len(bp.phase):
                bp.phase[i] = "enemy_attack"
        
        # For PvP clients, use staggered cooldowns to ensure proper synchronization
        if self.pvp_mode:
            bp.reset_cooldowns_staggered()

    def reset_minigames(self):
        """Reset all minigame instances and related counters."""
        # Reset minigame counters
        self.press_counter = 0
        self.rotation_index = 0
        self.super_hits = 0
        self.color_band = None
        self.strength = 0
        self.xai_phase = 0
        
        # Clean up minigame instances
        self.count_match = None
        self.count_match_classic = None
        self.count_match_z = None
        self.dummy_charge = None
        self.shake_punch = None
        self.xai_roll = None
        self.xai_bar = None
        self._xai_pending_stop = False

    def get_battle_effect(self, effect_name, default=None):
        """
        Get a battle effect value if it applies to this battle.
        Only returns effects for non-PvP battles that match the current module.
        
        Args:
            effect_name: Name of the effect to retrieve
            default: Default value to return if effect doesn't exist or doesn't apply
            
        Returns:
            The effect dict if it exists and applies, otherwise default
        """
        if self.pvp_mode:
            return default
            
        if effect_name not in game_globals.battle_effects:
            return default
            
        effect = game_globals.battle_effects[effect_name]
        
        # Check if effect has module restriction
        if "module" in effect:
            if effect["module"] != self.module.name:
                return default
        
        return effect

    def setup_pvp_teams(self, my_pets, enemy_pet_data, is_host: bool = True):
        """Sets up teams for PvP battle from pet data.

        Args:
            my_pets: List of GamePet objects for the local device.
            enemy_pet_data: List of dicts describing the remote team.
            is_host: True if this device is the PvP host (device1),
                     False if it's the client (device2). Used to
                     configure the HP bar mode (pvp_host/pvp_client).
        """
        from models.game_enemy import GameEnemy
        
        # Create enemy objects from received pet data
        enemy_objects = []
        for i, pet_data in enumerate(enemy_pet_data):
            # Create GameEnemy with the pet data
            enemy = GameEnemy(
                name=pet_data["name"], 
                power=pet_data["power"],
                attribute=pet_data["attribute"], 
                area=0,  # PvP doesn't use area/round
                round=0,
                version=1,  # Default version
                atk_main=pet_data["atk_main"],
                atk_alt=pet_data["atk_alt"],
                atk_alt_2=pet_data.get("atk_alt_2", 0),
                handicap=0,  # No handicap in PvP
                id=i,  # Use index as ID
                stage=pet_data["stage"],
                hp=pet_data["hp"],
                unlock="",  # No unlock requirements for PvP
                prize="",  # No prizes in PvP
                mini_game=pet_data.get("mini_game", 0)  # Strength/MiniGame score for attack patterns
            )
            
            # Set additional properties that might be needed
            enemy.level = pet_data["level"]
            enemy.sick = 1 if pet_data["sick"] else 0
            enemy.traited = pet_data["traited"]
            enemy.shook = pet_data["shook"]
            enemy.module = pet_data["module"]
            enemy.attack_sprite_module = pet_data.get("attack_sprite_module")
            
            # Load sprite for the enemy
            enemy.load_sprite(enemy.module, boss=False)
            
            enemy_objects.append(enemy)
        
        # Update battle_player with PvP teams (my pets vs enemy objects)
        self.battle_player = GameBattle(my_pets, enemy_objects, 0, 0, self.module)
        self.enemies = enemy_objects
        # The enemies did not exist when the constructor loaded sprites, and
        # a connection opponent brings a module of its own.
        self.load_module_attack_sprites()
        self._enemy_flip_cache = {}
        self._special_slide_cache = {}
        
        # Update HP bar for PvP mode
        if hasattr(self, 'hp_bar') and self.hp_bar:
            # Use dedicated PvP modes so the local player's side is always red
            # and the remote side blue, regardless of host/client role.
            if is_host:
                # Host is device1 on the left
                self.hp_bar.set_mode('pvp_host', module=self.module)
            else:
                # Client is device2 on the right
                self.hp_bar.set_mode('pvp_client', module=self.module)

            # Left bar = device1 / team2_total_hp, right bar = device2 / team1_total_hp
            # This ordering matches the adventure/PvE layout we use elsewhere.
            self.hp_bar.set_totals(self.battle_player.team2_total_hp, self.battle_player.team1_total_hp)
            self.hp_bar.set_values(self.battle_player.team2_total_hp, self.battle_player.team1_total_hp)
        
        # Initialize debug logs for PvP
        if game_globals.configuration.debug_mode:
            self.init_debug_battle_logs()

    def init_debug_battle_logs(self):
        """Initialize debug battle log entries for each pet position."""
        if not game_globals.configuration.debug_mode:
            return
        
        num_pets = len(self._current_targets()) if not self.pvp_mode else len(self.battle_player.team1)
        self.debug_battle_logs = []
        for i in range(num_pets):
            self.debug_battle_logs.append({
                "turn": 1,
                "hit": "",
                "arrow": ""
            })

    def update_debug_battle_logs(self):
        """Update debug battle logs with current phase information and hit results."""
        if not game_globals.configuration.debug_mode or not hasattr(self, 'debug_battle_logs'):
            return
            
        for i in range(len(self.debug_battle_logs)):
            if i >= len(self.battle_player.phase) or i >= len(self.battle_player.turns):
                continue
                
            phase = self.battle_player.phase[i]
            turn = self.battle_player.turns[i]
            
            # Update turn number
            self.debug_battle_logs[i]["turn"] = turn
            
            # Update arrow and hit info based on phase
            if phase == "pet_charge":
                self.debug_battle_logs[i]["arrow"] = ">"
                # Show last hit result if available
                self.debug_battle_logs[i]["hit"] = self.get_last_hit_result(i, "pet")
            elif phase == "pet_attack":
                self.debug_battle_logs[i]["arrow"] = ">"
                self.debug_battle_logs[i]["hit"] = ""
            elif phase == "enemy_charge":
                self.debug_battle_logs[i]["arrow"] = "<"
                # Show last hit result if available
                self.debug_battle_logs[i]["hit"] = self.get_last_hit_result(i, "enemy")
            elif phase == "enemy_attack":
                self.debug_battle_logs[i]["arrow"] = "<"
                self.debug_battle_logs[i]["hit"] = ""
            else:
                self.debug_battle_logs[i]["arrow"] = ""
                self.debug_battle_logs[i]["hit"] = ""

    def get_last_hit_result(self, pet_index, attacker_type):
        """Get the last hit result for display in debug logs."""
        if not hasattr(self, 'global_battle_log') or not self.global_battle_log:
            return ""
            
        try:
            # Predict the upcoming attack for the current turn (show before it lands)
            turn = self.battle_player.turns[pet_index]
            turn_idx = max(0, int(turn) - 1)  # use current turn (0-based)
            if turn_idx < len(self.global_battle_log.battle_log):
                turn_log = self.global_battle_log.battle_log[turn_idx]

                # Support both dataclass objects and dict shapes
                attacks = None
                if hasattr(turn_log, 'attacks'):
                    attacks = turn_log.attacks
                elif isinstance(turn_log, dict):
                    attacks = turn_log.get('attacks', [])
                else:
                    attacks = []

                for attack in attacks:
                    # extract fields generically
                    if isinstance(attack, dict):
                        dev = attack.get('device')
                        attacker = attack.get('attacker')
                        defender = attack.get('defender')
                        hit = attack.get('hit')
                        damage = attack.get('damage', 0)
                    else:
                        dev = getattr(attack, 'device', None)
                        attacker = getattr(attack, 'attacker', None)
                        defender = getattr(attack, 'defender', None)
                        hit = getattr(attack, 'hit', None)
                        damage = getattr(attack, 'damage', 0)

                    try:
                        attacker = int(attacker) if attacker is not None else None
                    except Exception:
                        attacker = None
                    try:
                        defender = int(defender) if defender is not None else None
                    except Exception:
                        defender = None

                    if attacker_type == 'pet' and dev == 'device1' and attacker == pet_index:
                        if not hit:
                            return 'Miss!'
                        if damage <= 2:
                            return 'Hit!'
                        if damage == 3:
                            return 'SuperHit!'
                        if damage >= 4:
                            return 'MegaHit!'
                        return 'Hit!'

                    if attacker_type == 'enemy' and dev == 'device2' and defender == pet_index:
                        if not hit:
                            return 'Miss!'
                        if damage <= 2:
                            return 'Hit!'
                        if damage == 3:
                            return 'SuperHit!'
                        if damage >= 4:
                            return 'MegaHit!'
                        return 'Hit!'
        except:
            pass
            
        return ""

    def get_hit_text_color(self, hit_text):
        """Get the color for hit text display."""
        if hit_text == "Miss!":
            return constants.FONT_COLOR_RED
        elif hit_text == "Hit!":
            return constants.FONT_COLOR_DEFAULT  # White
        elif hit_text == "SuperHit!":
            return constants.FONT_COLOR_GREEN
        elif hit_text == "MegaHit!":
            return (255, 192, 203)  # Pink
        else:
            return constants.FONT_COLOR_DEFAULT

    def load_enemies(self):
        """
        Loads enemy data for the current area and round, sets up enemy positions and health.
        """
        selected_pets = self._current_targets()
        version_range = self.module.get_enemy_versions(self.area, self.round, special_encounter=self.is_special_encounter)
        versions = []
        for p in selected_pets:
            if not version_range:
                versions.append(p.version)
            elif p.version not in version_range:
                versions.append(random.choice(version_range))
            else:
                versions.append(p.version)

        # New enemy objects invalidate the per-entity draw caches.
        self._enemy_flip_cache = {}
        self._special_slide_cache = {}

        self.enemies = self.module.get_enemies(self.area, self.round, versions,
                                               special_encounter=self.is_special_encounter,
                                               encounter_name=self.encounter_name)
        if self.boss:
            # If it's a boss, ensure we have only one enemy
            self.enemies = [self.enemies[0]] if self.enemies else []

        for enemy in self.enemies:
            if enemy:
                enemy.load_sprite(self.module.name, self.boss)

    def _load_ko_sprite(self, target_w, target_h):
        """Load KO.png and scale it to fit within target dimensions, preserving aspect ratio."""
        raw = sprite_load(constants.KO_PATH)
        if raw is None:
            return None
        orig_w, orig_h = raw.get_size()
        if orig_w == 0 or orig_h == 0:
            return None
        ratio = min(target_w / orig_w, target_h / orig_h)
        new_w = max(1, int(orig_w * ratio))
        new_h = max(1, int(orig_h * ratio))
        return pygame.transform.smoothscale(raw, (new_w, new_h)).convert_alpha()

    def load_hit_animation(self):
        """
        Loads the hit animation sprite sheet and splits it into frames.
        """
        sprite_sheet = sprite_load(constants.HIT_ANIMATION_PATH, (runtime_globals.PET_WIDTH * 12, runtime_globals.PET_HEIGHT))
        frames = []
        for i in range(12):
            frame = sprite_sheet.subsurface(pygame.Rect(i * runtime_globals.PET_WIDTH, 0, runtime_globals.PET_WIDTH, runtime_globals.PET_HEIGHT))
            frames.append(frame)
        return frames

    def load_module_attack_sprites(self):
        """
        Load module-specific attack sprites for all pets and enemies in battle.
        """
        # Get all unique modules from pets and enemies
        modules_to_load = set()
        
        # Add modules from battle targets (pets)
        for pet in self._current_targets():
            modules_to_load.add(pet.module)
        
        # The battle area's own module, for adventure enemies.
        modules_to_load.add(self.module.name)

        # And the line being fought, because in a connection battle BOTH
        # sides' shots are drawn from its library -- the id goes over the
        # wire in its numbering. The opponent usually brings it along, but
        # our own pet needs it whether or not the opponent resolved.
        battle_format = getattr(self, "battle_format", None)
        if battle_format:
            from battle.sim.dcom_battle_simulator import module_for_format
            line = module_for_format(battle_format)
            if line is not None and getattr(line, "name", None):
                modules_to_load.add(line.name)

        # A connection opponent carries its own: it is a real device, and its
        # attack sprites belong to the module that reproduces it rather than
        # to the area being fought in.
        for enemy in (self.enemies or []):
            enemy_module = getattr(enemy, 'module', None)
            if enemy_module:
                modules_to_load.add(enemy_module)
        
        # Load sprites for each unique module (atk and atk_crit folders)
        for module_name in modules_to_load:
            self.module_attack_sprites[module_name] = module_attack_sprites(module_name)
            self.module_crit_attack_sprites[module_name] = module_crit_attack_sprites(module_name)

    def _is_dot_entity(self, entity):
        """Return True if this entity is currently rendered using dot sprites."""
        enable_old = getattr(game_globals.configuration, 'enable_old_sprites', False)
        if not enable_old:
            return False
        module_name = getattr(entity, 'module', self.module.name)
        # Not get_module: that indexes the registry and raises on a name that
        # is not loaded, so the `is None` this has always carried could never
        # fire. A connection opponent carries the module of the device it
        # reproduces, and a saved payload or a peer can name one this player
        # does not own -- which would have crashed the battle here, but only
        # for players with old sprites turned on.
        mod = runtime_globals.game_modules.get(module_name)
        if mod is None:
            return False
        primary = getattr(mod, 'primary_sprite_format', 'Color')
        secondary = getattr(mod, 'secondary_sprite_format', 'HD')
        return primary == 'Dot' or secondary == 'Dot'

    def _attack_sprite_module(self, entity):
        """Which module's attack library a shot is drawn from.

        In a **connection battle** the sprite id travels over the wire in the
        LINE's own numbering, and the toy draws it from that line's library
        -- so ours has to as well, or the two screens show different attacks
        for the same id. A DMX Damemon on the Colour wire announced shot 8:
        the device drew the Colour library's 9, a lightning bolt, and we drew
        the DMX module's 9, which is a heart.

        The opponent already came with the line's module (`parse_opponent`
        gives it one), so this is really about our own pet, and it settles
        both the same way. Not owning the module leaves the entity's own,
        which is what the game has always done.

        Only for a protocol battle: `battle_format` is set for versus, DCom
        and WiFiCom and left None by an adventure battle, where a pet fights
        on its own line and keeps its own library.
        """
        own = getattr(entity, 'module', self.module.name)
        battle_format = getattr(self, "battle_format", None)
        if not battle_format:
            return own
        # **Unless we know which device fired it.** Several modules can
        # reproduce one line, and a crossover edition ships its own `atk/`
        # at the same ids as the shared library -- so a Monster Hunter
        # opponent's shot 73 is a Monster Hunter sprite, not the Colour
        # library's. That is only knowable for a side whose roster the
        # opponent actually resolved on, which is what this carries; our own
        # pet has no such claim and keeps taking the line's.
        named = getattr(entity, 'attack_sprite_module', None)
        if named:
            return named
        from battle.sim.dcom_battle_simulator import module_for_format
        line = module_for_format(battle_format)
        return getattr(line, "name", None) or own

    def get_attack_sprite(self, entity, attack_id):
        """
        Get attack sprite for a pet or enemy, preferring module-specific sprites over defaults.
        Dot variants are selected only for entities currently rendered as dot (enable_old + Dot format).
        """
        module_name = self._attack_sprite_module(entity)
        is_dot = self._is_dot_entity(entity)

        if module_name in self.module_attack_sprites:
            module_dict = self.module_attack_sprites[module_name]
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
        sprite = self.attack_sprites.get(str(attack_id))
        if sprite:
            return sprite

        # Nothing by that id. A real device can name one we simply do not
        # have -- the Pendulum's Shot field is 8 bits and Omnipet ships 117
        # sprites, so an opponent announcing 152 is perfectly legal on the
        # wire and unresolvable here. This used to return None and the caller
        # handed it straight to pygame.transform.flip, which killed the whole
        # battle. Draw *a* shot instead: the sprite the module does have is a
        # better answer than no battle at all.
        fallback = self.module_attack_sprites.get(module_name, {})
        for candidate in ("1", "2"):
            sprite = fallback.get(candidate) or self.attack_sprites.get(candidate)
            if sprite:
                runtime_globals.game_console.log(
                    f"[BattleEncounter] no attack sprite {attack_id} for "
                    f"{module_name}; falling back to {candidate}")
                return sprite
        return None

    def get_crit_attack_sprite(self, entity, attack_id):
        """
        Get a critical-attack sprite for a critical hit.
        Priority: module-specific atk_crit folder → global assets/atk_crit folder.
        Returns None if nothing found — callers should fall back to normal atk + scale2x.
        Dot variants are selected only for entities currently rendered as dot.
        """
        module_name = self._attack_sprite_module(entity)
        is_dot = self._is_dot_entity(entity)

        crit_dict = self.module_crit_attack_sprites.get(module_name, {})
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

    #: Where the Nth sprite of a multi-sprite shot sits, relative to the
    #: first, before UI scaling. The first three are the spacing the DMX
    #: ladder already drew its doubles and triples with; an enemy negates
    #: them, since it fires the other way.
    PROJECTILE_OFFSETS = ((0, 0), (-20, -10), (-40, 10), (-60, -20), (-80, 20))

    def _count_offsets(self, count, scale, mirrored=False):
        """Offsets for a shot drawn as *count* copies of one sprite."""
        count = max(1, min(int(count), len(self.PROJECTILE_OFFSETS)))
        sign = -1 if mirrored else 1
        return [(ox * scale * sign, oy * scale * sign)
                for ox, oy in self.PROJECTILE_OFFSETS[:count]]

    def _paired_shot(self, entity, anim_hits):
        """The Ver.20th's shot for a damage value: ``(atk_id, count, double)``.

        Damage rises in pairs and the sprite alternates within each -- 1 and 2
        are one sprite, 3 and 4 are two, and the odd value of each pair draws
        `atk_alt` where the even one draws `atk_main`. **This line reverses
        the usual pairing**: its weak attacks are the alternate sprite.

        A pet with no `atk_alt` cannot make that distinction, so it separates
        the four by count instead -- one, two and three sprites, then a single
        sprite at double size for the strongest.
        """
        main = str(getattr(entity, "atk_main", 30))
        alt = getattr(entity, "atk_alt", 0) or 0
        damage = max(1, min(4, int(anim_hits or 1)))

        if not alt:
            return main, (damage if damage < 4 else 1), damage == 4
        return (str(alt) if damage % 2 else main), (1 if damage <= 2 else 2), False

    def _forced_attack_sprite(self):
        """The one attack sprite this wire draws, whatever the pet.

        The Digital Monster exchanges no sprite ids -- there is no field for
        one -- and the device draws the same shot for every Digimon, which is
        what every filmed battle shows. So a connection battle on that line
        uses it for both sides rather than each pet's own.

        Only for a protocol battle: ``battle_format`` is set for versus, DCom
        and WiFiCom and left None by an adventure battle, which keeps each
        pet's own sprite even on a DMOG module.
        """
        battle_format = getattr(self, "battle_format", None)
        if not battle_format:
            return None
        constants = protocol_constants.get_constants(battle_format)
        return getattr(constants, "FORCED_ATTACK_SPRITE", None)

    def _attack_animation_style(self):
        """How this battle turns a damage value into projectiles.

        A protocol battle is fought on the device's wire, so the wire is what
        decides: a format declaring ``ATTACK_ANIMATION`` owns its own
        presentation, and "count" means N damage is N atk_main sprites --
        what a filmed DMOG battle shows, and what DMC inherits from it.

        An adventure battle has no wire, but it does have a module, and the
        module says which device it reproduces. A DMOG module's adventure
        battles should look like a Digital Monster's for the same reason its
        connection battles do -- otherwise a 2 drew as one scaled-up shot
        there while the same 2 drew as two shots over the cable.

        Everything else keeps the module's own rule, where
        ``battle_damage_limit`` says whether that module's damage values have
        the range the five-rung sprite ladder needs. That was the *only*
        rule until now, which is why a DCom battle used to be animated from
        whichever pet the player brought rather than from the device it was
        being fought against.
        """
        battle_format = (getattr(self, "battle_format", None)
                         or getattr(self.module, "battle_protocol", None))
        if battle_format:
            constants = protocol_constants.get_constants(battle_format)
            style = getattr(constants, "ATTACK_ANIMATION", None)
            if style:
                return style
        return "simple" if self.module.battle_damage_limit < 3 else "ladder"

    def _ladder_shot(self, entity, value, critical=False, crit_bank=True):
        """The DMX/PENZ shot for a pattern value: ``(atk_id, count, double, crit)``.

        The five attack types are two ladders crossed. **A weak shot draws
        `atk_main` and a strong one `atk_alt`**, and each goes out once or
        twice: 1 weak single, 2 strong single, 3 weak double, 4 strong
        double. `data/attack_patterns/DMX.json` has said exactly that since
        the damage table was read off the device's own HP bar -- a strong
        shot is worth 3 where a weak one is worth 2, and the damage is the
        sprite strength times the sprite count, so the pairing is what the
        measured numbers are built on.

        The code this replaces had 1 and 2 on `atk_main` and 3 and 4 on
        `atk_alt`, which is the same ladder shifted by one: a strong single
        drew as a weak double and a weak double as a strong single. The two
        readings agree only at 1.

        A pet with no `atk_alt` cannot make the distinction, so it adds a
        sprite instead -- the fallback counts are the JSON's own. The fifth
        type is the critical: the dedicated crit sprite at its own size, or
        the best sprite the pet does have at double.
        """
        main = str(getattr(entity, "atk_main", 30) or 30)
        alt = getattr(entity, "atk_alt", 0) or 0
        alt2 = getattr(entity, "atk_alt_2", 0) or 0

        if critical or value >= 5:
            if crit_bank and alt2 > 0:
                return str(alt2), 1, False, True
            return (str(alt) if alt > 0 else main), 1, True, False
        if value == 4:
            return (str(alt), 2, False, False) if alt > 0 else (main, 3, False, False)
        if value == 3:
            return main, 2, False, False
        if value == 2:
            return (str(alt), 1, False, False) if alt > 0 else (main, 2, False, False)
        return main, 1, False, False

    def _ladder_sprite(self, entity, value, critical):
        """Resolve `_ladder_shot` to a sprite, dropping to the ordinary bank.

        `atk_alt_2` indexes the crit sprites, which are a separate folder --
        so an id with nothing behind it must fall back to the ladder's own
        answer rather than being handed to `get_attack_sprite`, where it
        would name some unrelated ordinary shot.
        """
        atk_id, count, double, crit = self._ladder_shot(entity, value, critical)
        if crit:
            sprite = self.get_crit_attack_sprite(entity, atk_id)
            if sprite is not None:
                return sprite, atk_id, count, double
            atk_id, count, double, crit = self._ladder_shot(
                entity, value, critical, crit_bank=False)
        return self.get_attack_sprite(entity, atk_id), atk_id, count, double

    def _has_special_frame(self, entity):
        """Check if a pet/enemy has a valid SPECIAL frame (index 15)."""
        try:
            return entity.get_sprite(PetFrame.SPECIAL.value) is not None
        except Exception:
            return False

    def _is_critical_attack(self, entity, anim_hits):
        """Check if this attack should use the special/critical animation."""
        return (anim_hits >= 5 and 
                self.module.enable_special_attack_sprite and 
                self._has_special_frame(entity))

    #========================
    # Region: Update Methods
    #========================

    def update(self):
        """
        Main update loop for the battle encounter, calls phase-specific updates.
        """
        self.frame_counter += 1
        self.battle_player.increment_frame_counters()
        
        # Update AnimatedSprite component
        self.animated_sprite.update()

        if self.phase == "level":
            self.update_level()
        elif self.phase == "entry":
            self.update_entry()
        elif self.phase == "intimidate":
            self.update_intimidate()
        elif self.phase == "xros_select":
            self.update_xros_select()
        elif self.phase == "xros_anim":
            self.update_xros_anim()
        elif self.phase == "alert":
            self.update_alert()
        elif self.phase == "charge":
            self.update_charge()
        elif self.phase == "battle":
            self.update_battle()
        elif self.phase == "clear":
            self.update_clear()
        elif self.phase == "result":
            self.update_result()
        elif self.phase == "feeding":
            self.update_feeding()
        elif self.phase == "retire_check":
            self.update_retire_check()
        elif self.phase == "retire_animation":
            self.update_retire_animation()

        runtime_globals.game_message.update()

        advance_every = max(1, int( constants.FRAME_RATE // 15))
        if self.frame_counter % advance_every == 0:
            for anim in self.hit_animations:
                anim[0] += 1  # Advance one frame

        self.hit_animations = [a for a in self.hit_animations if a[0] < len(self.hit_animation_frames)]

    def update_level(self):
        """
        Update logic for the level phase, transitions to entry phase after duration.
        """
        if self.frame_counter >= combat_constants.LEVEL_DURATION_FRAMES:
            self.phase = "entry"
            self.frame_counter = 0
            runtime_globals.game_sound.play("battle")

    def update_entry(self):
        """
        Update logic for the enemy entry phase, moves enemies into position.
        """

        self.enemy_entry_counter -= combat_constants.ENEMY_ENTRY_SPEED * (30 / constants.FRAME_RATE)  # Frame-rate independent speed

        if self.enemy_entry_counter <= 0:
            runtime_globals.game_console.log("Entering intimidate phase")
            self.phase = "intimidate"
            self.frame_counter = 0
            self.enemy_entry_counter = 0
            self.battle_player.reset_frame_counters()
            
            # Start intimidate animation once when entering phase
            duration = 3.0  # 3 second intimidate animation (increased from 2.0)
            if self.boss:
                # Use warning animation for boss (intimidating)
                self.animated_sprite.play_warning(duration)
            else:
                # Use battle animation for normal battle
                self.animated_sprite.play_battle(duration)

    def update_intimidate(self):
        """
        Update logic for the intimidate phase, transitions to the xros
        selection (when any pet can temporarily evolve) or the alert phase.
        """
        if self.frame_counter >= combat_constants.IDLE_ANIM_DURATION:
            # Stop intimidate animation when exiting phase
            self.animated_sprite.stop()
            if self._start_xros_selection():
                return
            self._enter_alert_phase()

    def _enter_alert_phase(self):
        """Enter the alert phase (from intimidate or after the xros flow)."""
        self.phase = "alert"
        self.frame_counter = 0

        # READY sound state, same flow training uses (see Training.update_alert_phase).
        self._ready_sound_triggered = False
        self._ready_sound_started = False
        self._ready_sound_fallback = False
        self.alert_duration_frames = combat_constants.ALERT_DURATION_FRAMES

        # Reset minigames before alert phase
        self.reset_minigames()

        # A minigame that owns its ready phase has to exist before the alert
        # phase draws, so build it here rather than in setup_charge.
        ready = READY_PHASE_MINIGAMES.get(
            getattr(self.module, 'battle_minigame', ''))
        if ready:
            attribute, minigame_class = ready
            pets = self._current_targets()
            instance = minigame_class(self.ui_manager, pets[0] if pets else None,
                                      self.animated_sprite)
            instance.set_phase("ready")
            setattr(self, attribute, instance)

    # ------------------------------------------------------------------
    # Xros / temporary evolution flow (after intimidate, before alert)
    # ------------------------------------------------------------------

    def _start_xros_selection(self) -> bool:
        """Open the temporary-evolution selector when any pet qualifies.

        Only offered once per encounter — with Battle Sequential Rounds the
        same encounter instance runs every round, so the pets evolve at the
        first battle and keep the form for all rounds.  Returns True when the
        selection phase was entered.
        """
        if self.pvp_mode or getattr(self, 'xros_prompted', False):
            return False
        self.xros_prompted = True

        try:
            from utils.xros_utils import get_available_temp_evolutions
            candidates = []
            for pet in self.battle_player.team1:
                options = get_available_temp_evolutions(pet)
                if options:
                    candidates.append((pet, options))
            if not candidates:
                return False

            from ui.components.xros_selector import XrosSelector
            self.xros_selector = XrosSelector(candidates, self.ui_manager)
            self.phase = "xros_select"
            self.frame_counter = 0
            runtime_globals.game_console.log(
                f"[Xros] Selection opened for {len(candidates)} pet(s)")
            return True
        except Exception as exc:
            runtime_globals.game_console.log(f"[Xros] selection setup failed: {exc}")
            return False

    def _on_xros_confirm(self):
        """Apply the chosen temporary evolutions and play the animation."""
        selections = [(pet, evo) for pet, evo in self.xros_selector.get_selections() if evo]
        self.xros_selector = None
        if not selections:
            self._enter_alert_phase()
            return

        # Starts the moment the choice is made and runs over the animation's
        # opening background segment, which is exactly as long as this sound.
        runtime_globals.game_sound.play("xros_start")

        try:
            # Build the animation FIRST (it captures the pre-evolution
            # sprites), then create each pet's battle-only evolved form. The
            # party pets themselves are left exactly as they are.
            from ui.components.xros_animation import XrosAnimation
            from utils.xros_utils import make_xros_pet
            self.xros_animation = XrosAnimation(selections)
            for pet, evo in selections:
                form = make_xros_pet(pet, evo)
                if form is not None:
                    self.xros_forms[pet] = form
            # The team was built from the un-evolved pets; rebuild it so the
            # forms are the ones that actually fight.
            if self.xros_forms:
                self.battle_player.team1 = self._current_targets()
            self.phase = "xros_anim"
            self.frame_counter = 0
        except Exception as exc:
            runtime_globals.game_console.log(f"[Xros] apply failed: {exc}")
            self._enter_alert_phase()

    def _clear_xros_forms(self) -> list:
        """End every temporary evolution; returns the pets that were in one.

        Nothing is restored because nothing was changed — the forms are simply
        dropped and the team goes back to holding the real pets.
        """
        if not self.xros_forms:
            return []
        pets = list(self.xros_forms.keys())
        for form in self.xros_forms.values():
            form.release()
        self.xros_forms = {}
        if getattr(self, "battle_player", None):
            # Swap the forms out of the team so the result screen and anything
            # after it sees the pets themselves.
            self.battle_player.team1 = [
                getattr(p, "pet", p) for p in self.battle_player.team1]
        runtime_globals.game_console.log(
            f"[Xros] {len(pets)} temporary evolution(s) ended")
        return pets

    def update_xros_select(self):
        """Waits on player input (handled in handle_event)."""
        pass

    def update_xros_anim(self):
        self.xros_animation.update()
        if self.xros_animation.finished:
            self.xros_animation = None
            self._enter_alert_phase()

    def draw_xros_select(self, surface):
        surface.fill((0, 0, 0))
        if getattr(self, 'xros_selector', None):
            self.xros_selector.draw(surface)

    def draw_xros_anim(self, surface):
        if getattr(self, 'xros_animation', None):
            self.xros_animation.draw(surface)

    def update_alert(self):
        """
        Update logic for the alert phase, prepares for charge phase after duration.

        Adventure battles run the same READY as training: the phase lasts
        exactly as long as the READY sound, and does not begin until playback
        has actually started, so the sound and the sprite stay in step. Versus
        and DCom keep the fixed-length alert — their timing is negotiated with
        the other device and must not stretch to fit an audio asset.
        """
        if self.pvp_mode:
            if self.frame_counter == int(combat_constants.ALERT_DURATION_FRAMES * 0.8):
                runtime_globals.game_sound.play("happy")
            elif self.frame_counter > combat_constants.ALERT_DURATION_FRAMES:
                self._finish_alert_phase()
            return

        if not self._ready_sound_triggered:
            duration = runtime_globals.game_sound.get_duration(TRAINING_READY_SOUND)
            if duration > 0:
                self.alert_duration_frames = max(
                    1, int(round(duration * game_globals.configuration.frame_rate)))

            channel = runtime_globals.game_sound.play(TRAINING_READY_SOUND)
            self._ready_sound_triggered = True

            # Muted audio or an unavailable mixer has no playback start to
            # observe; fall back to the asset's own length.
            if channel is None:
                self._ready_sound_started = True
                self._ready_sound_fallback = True
                self.frame_counter = 0

        if not self._ready_sound_started:
            # The mixer can lag behind play(); hold the phase at frame 0 until
            # the sound is actually audible.
            if runtime_globals.game_sound.is_playing(TRAINING_READY_SOUND):
                self._ready_sound_started = True
            self.frame_counter = 0
            return

        if (not self._ready_sound_fallback
                and not runtime_globals.game_sound.is_playing(TRAINING_READY_SOUND)):
            self._finish_alert_phase()
            return

        if self.frame_counter >= self.alert_duration_frames:
            self._finish_alert_phase()

    def _finish_alert_phase(self):
        """Leave READY for the charge minigame."""
        runtime_globals.game_sound.stop(TRAINING_READY_SOUND)

        # A DCom battle already played its charge in the connection flow and
        # sent the result to the real device; playing it again here would ask
        # the player to charge a second time for no effect.
        if getattr(self, 'skip_charge', False):
            runtime_globals.game_console.log("Charge already committed; entering battle phase")
            self.phase = "battle"
            self.frame_counter = 0
            self.animated_sprite.stop()
            self.battle_player.reset_frame_counters()
            self._skip_grace_until = 0
            self._last_pet_proj_tick = pygame.time.get_ticks()
            self._last_enemy_proj_tick = pygame.time.get_ticks()
            self.calculate_combat_for_pairs()
            return

        runtime_globals.game_console.log("Entering charge phase")
        self.phase = "charge"
        self.frame_counter = 0
        self.bar_timer = pygame.time.get_ticks()
        self.setup_charge()

    def setup_charge(self):
        """
        Setup logic for the charge phase, varies by module's battle_minigame setting.
        battle_minigame options: "None", "Dummy Bar", "Count Match Color", "Count Match Z",
                                 "Count Match Classic", "Xai Roll+Bar", "Xai Bar", "Punch", "Mogera"
        """
        minigame = getattr(self.module, 'battle_minigame', 'Dummy Bar')
        pets = self._current_targets()
        
        if minigame == "None":
            # Skip charge phase; `minigame_result` answers 2 for this one
            # whatever it is handed, so the strength is all that is needed.
            self.strength = 2
        elif minigame == "Dummy Bar":
            # Dummy charge minigame (A button presses)
            self.bar_level = 14
            self.battle_player.reset_frame_counters()
            self.dummy_charge = DummyCharge(self.ui_manager, "RED")
        elif minigame == "Count Match Color":
            # Color count match minigame (shake-based with attribute colors)
            self.rotation_index = 3
            if not self.count_match:
                self.count_match = CountMatch(self.ui_manager, pets[0] if pets else None, self.animated_sprite)
            self.count_match.set_phase("count")
        elif minigame == "Count Match Classic":
            # Count Match Classic (shake-based, 0-14 like Dummy Bar).
            # Needs the shared AnimatedSprite — without it the minigame runs
            # but draws nothing during the charge phase.
            self.bar_level = 14
            self.count_match_classic = CountMatchClassic(self.ui_manager, self.animated_sprite)
        elif minigame == "Count Match Z":
            # Count Match Z (arrow-based with attribute scoring)
            if not self.count_match_z:
                self.count_match_z = CountMatchZ(self.ui_manager, pets[0] if pets else None, self.animated_sprite)
            self.count_match_z.set_phase("count")
        elif minigame == "Xai Roll+Bar":
            # XAI roll and bar minigame
            self.xai_phase = 1
            self.xai_roll = XaiRoll(
                x=runtime_globals.SCREEN_WIDTH // 2 - int(100 * runtime_globals.UI_SCALE) // 2,
                y=runtime_globals.SCREEN_HEIGHT // 2 - int(100 * runtime_globals.UI_SCALE) // 2,
                width=int(100 * runtime_globals.UI_SCALE),
                height=int(100 * runtime_globals.UI_SCALE),
                xai_number=1
            )
            self.xai_roll.roll()
        elif minigame == "Xai Bar":
            # XAI bar only (skips roll, uses daily xai value)
            self.xai_phase = 2
            self.xai_bar = XaiBar(
                x=runtime_globals.SCREEN_WIDTH // 2 - int(152 * runtime_globals.UI_SCALE) // 2,
                y=runtime_globals.SCREEN_HEIGHT // 2 - int(72 * runtime_globals.UI_SCALE) // 2 + int(48 * runtime_globals.UI_SCALE),
                xai_number=game_globals.xai,
                pet=pets[0] if pets else None
            )
            self.xai_bar.start()
        elif minigame == "Punch":
            # Shake punch minigame
            self.bar_level = 20
            self.shake_punch = ShakePunch(self.ui_manager, pets)
            self.shake_punch.set_phase("punch")
        elif minigame == "Mogera":
            # Mogera minigame - uses same shake punch component for now
            self.bar_level = 20
            self.shake_punch = ShakePunch(self.ui_manager, pets)
            self.shake_punch.set_phase("punch")

    def update_charge(self):
        """
        Update logic for the charge phase, handles input and transitions to pet_charge phase.
        """
        minigame = getattr(self.module, 'battle_minigame', 'Dummy Bar')
        
        # Update minigames based on battle_minigame setting
        if minigame == "None":
            # Immediately transition - no minigame
            pass
        elif minigame == "Dummy Bar" and self.dummy_charge:
            self.dummy_charge.update()
            self.strength = self.dummy_charge.strength
        elif minigame == "Count Match Color" and self.count_match:
            self.count_match.update()
            self.press_counter = self.count_match.get_press_counter()
            self.rotation_index = self.count_match.get_rotation_index()
        elif minigame == "Count Match Classic" and self.count_match_classic:
            self.count_match_classic.update()
            self.strength = self.count_match_classic.strength
        elif minigame == "Count Match Z" and self.count_match_z:
            self.count_match_z.update()
            self.press_counter = self.count_match_z.get_press_counter()
        elif minigame == "Punch" and self.shake_punch:
            self.shake_punch.update()
            self.strength = self.shake_punch.get_strength()
        elif minigame == "Mogera" and self.shake_punch:
            self.shake_punch.update()
            self.strength = self.shake_punch.get_strength()
        elif minigame in ["Xai Roll+Bar", "Xai Bar"]:
            if self.xai_phase == 1 and self.xai_roll:
                self.xai_roll.update()
                if not self.xai_roll.rolling and not self.xai_roll.stopping:
                    self.xai_phase = 2
                    pets = self._current_targets()
                    # Read the landed face from the roll rather than relying on
                    # the input handler having set it: the roll also stops
                    # itself after a few seconds with no press, and that result
                    # has to reach the bar just the same. Covers the Seven
                    # Switch too, whose forced frame is already applied here.
                    self.xai_number = self.xai_roll.get_result()
                    self.xai_bar = XaiBar(
                        x=runtime_globals.SCREEN_WIDTH // 2 - int(152 * runtime_globals.UI_SCALE) // 2,
                        y=runtime_globals.SCREEN_HEIGHT // 2 - int(72 * runtime_globals.UI_SCALE) // 2 + int(48 * runtime_globals.UI_SCALE),
                        xai_number=self.xai_number,
                        pet=pets[0] if pets else None
                    )
                    self.xai_bar.start()
            elif self.xai_phase == 2 and self.xai_bar:
                if self._xai_pending_stop:
                    self._xai_pending_stop = False
                    self._do_xai_bar_stop()
                else:
                    self.xai_bar.update()
                # The bar lingers for half a second after stopping so the
                # player can see which color they landed on.
                if getattr(self.xai_bar, 'stopped', False) and self.xai_bar.is_finished():
                    # get_result already returns 0-3; "or 1" used to turn a
                    # missed bar into a Good, which the protocol reads as a
                    # better charge than it was.
                    self.strength = self.xai_bar.get_result()
                    self.xai_phase = 3
                    self.bar_timer = pygame.time.get_ticks()

        # Check if minigame time is up and transition to battle
        time_up = False
        if minigame == "None":
            time_up = True  # Immediately proceed
        elif minigame in ["Punch", "Mogera"] and self.shake_punch:
            time_up = self.shake_punch.is_time_up() or self.strength >= 20
        elif minigame in ["Xai Roll+Bar", "Xai Bar"]:
            time_up = self.xai_phase == 3
        else:
            time_up = pygame.time.get_ticks() - self.bar_timer > combat_constants.BAR_HOLD_TIME_MS
        
        if time_up:
            runtime_globals.game_console.log("Entering battle phase")
            self.phase = "battle"
            self.frame_counter = 0
            # The dummy charge is mashed with A/LCLICK; give mouse/touch
            # players a 1s grace before LCLICK counts as "skip battle".
            if minigame == "Dummy Bar":
                self._skip_grace_until = pygame.time.get_ticks() + 1000
            else:
                self._skip_grace_until = 0
            self.animated_sprite.stop()
            self.battle_player.reset_frame_counters()
            # Reset projectile delta-time trackers for the new battle phase
            self._last_pet_proj_tick = pygame.time.get_ticks()
            self._last_enemy_proj_tick = pygame.time.get_ticks()
            if minigame == "Count Match Color":
                self.calculate_results()
            elif minigame == "Count Match Z" and self.count_match_z:
                # The counter is the score, so take a final reading of it --
                # `get_minigame_strength` turns it into the 0-3. It used to
                # be pre-scored into a `minigame_result` attribute nothing
                # has ever read, so the charge stayed 0 and **every battle on
                # a Pendulum Z module went out as Bad** however well it was
                # played.
                self.press_counter = self.count_match_z.get_press_counter()
            self.calculate_combat_for_pairs()

    def _do_xai_bar_stop(self):
        """Freeze the XAI bar; the result is applied after its 0.5s hold."""
        self.xai_bar.stop()

    def calculate_results(self):
        """Score the Count Match Color result into a band and a hit count."""
        from ui.minigames.minigame_session import (count_match_rank,
                                                   count_match_super_hits)
        self.correct_color = self.get_first_pet_attribute()
        self.final_color = self.rotation_index
        pets = self.battle_player.team1
        if not pets:
            return

        # Only the first pet's attribute decides the colour ranking; the
        # result is then shared by the whole team. The band is the minigame's
        # own answer and the super-hit count follows from it and the stage,
        # so each pet's row is looked up with its own stage later.
        attribute = getattr(pets[0], "attribute", "") or ""
        self.color_band = count_match_rank(self.final_color, attribute)
        self.super_hits = count_match_super_hits(
            self.final_color, attribute, getattr(pets[0], "stage", 1) or 1)

    def get_first_pet_attribute(self):
        """
        Get the attribute of the first pet, used for determining attack color in charge phase.
        """
        pet = self._current_targets()[0]
        if pet.attribute in ["", "Va"]:
            return 1
        elif pet.attribute == "Da":
            return 2
        elif pet.attribute == "Vi":
            return 3
        return 1
    
    def _lost_pair(self, index: int, side: str) -> bool:
        """Whether *side* ("team1"/"team2") lost the pair it fought.

        ``GameBattle.winners`` is per-pair and is the right answer in a battle
        with several pets -- but nothing has ever assigned it, so it stays
        ``[None]`` in every mode and both result animations fell through to
        the celebrating frame. Whoever had won, **both sides played their
        happy animation**: a pet that had just been knocked out stood up and
        cheered next to the device that killed it.

        The whole-battle verdict is the fallback, which is what the
        horizontal result layout in ``draw_pets`` already reads. It also
        covers an index the per-pair list does not have, since a team of one
        pet can face several enemies.
        """
        winners = self.battle_player.winners
        winner = winners[index] if index < len(winners) else None
        if winner is not None:
            return winner != side
        if self.victory_status == "Victory":
            return side == "team2"
        if self.victory_status == "Defeat":
            return side == "team1"
        return False

    def process_battle_results(self):
        """
        Processes the results of a global protocol battle using the new log structure.
        """
        # Skip experience and level-ups for PvP mode
        if self.pvp_mode:
            runtime_globals.game_console.log("[BattleEncounter] PvP battle completed - no experience awarded")
            return

        # Friends are NOT registered here: this runs whatever the outcome, and
        # a Friend is only won by beating it. See update_result().

        # If defeat, no XP for anyone
        if self.victory_status == "Defeat":
            self.battle_player.xp = 0
            self.battle_player.bonus = 0
            # Call finish_battle here to update DP, battle number, and win rate for a loss.
            for i, pet in enumerate(self.battle_player.team1):
                pet.finish_battle(self.victory_status == "Victory", self.battle_player.team2[0], self.area, (self.boss or not self.module.battle_sequential_rounds), is_special_encounter=self.is_special_encounter)
            return

        # If victory, calculate XP for winners and bonus
        xp_multiplier = 1
        exp_effect = self.get_battle_effect("exp_multiplier")
        if exp_effect:
            xp_multiplier = exp_effect.get("amount", 1)
        boss = self.boss

        self.battle_player.xp = int((2.83 * self.battle_player.team2[0].stage) + (0.81 * self.battle_player.team2[0].power) + (0.17 * self.round) + ((0.67 * self.area) * (6.39 if boss else 0))) * xp_multiplier
        #total_xp = int(self.battle_player.xp * len(self.battle_player.team1))

        if all(digimonstatus.alive for digimonstatus in self.global_battle_log.device1_final):
            # If all pets are alive, apply bonus XP
            self.battle_player.bonus = int(self.battle_player.xp * 0.1)

        for i, pet in enumerate(self.battle_player.team1):
            prev_level = getattr(pet, "level", 1)
            # Add XP and bonus to pet, check for level up
            if hasattr(pet, "add_experience"):
                pet.add_experience(self.battle_player.xp + self.battle_player.bonus)
                self.battle_player.level_up[i] = getattr(pet, "level", 1) > prev_level
            else:
                self.battle_player.level_up[i] = False

            pet.finish_battle(self.victory_status == "Victory", self.battle_player.team2[0], self.area, (self.boss or not self.module.battle_sequential_rounds), is_special_encounter=self.is_special_encounter)

        # --- Prize logic for Victory ---
        self.prize_item = None
        if self.victory_status == "Victory":
            # Collect all enemies with a prize
            prize_enemies = [e for e in self.battle_player.team2 if hasattr(e, "prize") and e.prize]
            if prize_enemies:
                chosen_enemy = random.choice(prize_enemies)
                prize_name = getattr(chosen_enemy, "prize", None)
                if prize_name and hasattr(self.module, "items") and self.module.items:
                    matching_items = [item for item in self.module.items if item.name == prize_name]
                    if matching_items:
                        self.prize_item = random.choice(matching_items)
                        inventory_utils.add_to_inventory(self.prize_item.id, 1)
                        runtime_globals.game_console.log(f"Received item: {self.prize_item.name}")

        # --- Remove expired boosts if boss or not sequential rounds ---
        if self.boss or not self.module.battle_sequential_rounds:
            to_remove = []
            for status, effect in game_globals.battle_effects.items():
                # Only decrement boosts for this module
                if "module" in effect and effect["module"] != self.module.name:
                    continue
                if "boost_time" in effect:
                    effect["boost_time"] -= 1
                    if effect["boost_time"] <= 0:
                        to_remove.append(status)
            if to_remove:
                runtime_globals.game_console.log(f"[BattleEncounter] Removing expired boosts: {', '.join(to_remove)}")
            for status in to_remove:
                del game_globals.battle_effects[status]

    #: How long the battle screen holds after the killing blow. The result
    #: used to replace it in the same frame the last projectile landed, so
    #: the shot that ended the fight was never seen and the HP bar jumped
    #: from full to empty -- on every line, not just the ones being worked on.
    BATTLE_END_HOLD_FRAMES = int(constants.FRAME_RATE * 0.9)
    #: And a little longer while the bar is still draining, but never past
    #: this: a bar that somehow never settles must not strand the battle.
    BATTLE_END_HOLD_MAX_FRAMES = int(constants.FRAME_RATE * 2.0)

    def _request_battle_end(self):
        """Note that the battle is decided; the hold does the rest.

        Called instead of setting the phase directly, from all three places
        that can end a fight -- the HP check and either side's projectiles.
        Idempotent, because more than one of them can fire on the same frame.
        """
        if self._battle_end_frames is None:
            self._battle_end_frames = 0

    def _battle_end_ready(self):
        """Has the last blow finished playing?"""
        held = self._battle_end_frames
        if held < self.BATTLE_END_HOLD_FRAMES:
            return False
        if held >= self.BATTLE_END_HOLD_MAX_FRAMES:
            return True
        bar = getattr(self, "hp_bar", None)
        return not (bar is not None and bar.is_animating())

    def update_battle(self):
        self.battle_player.update()

        # Update debug battle logs based on current phases
        if game_globals.configuration.debug_mode:
            self.update_debug_battle_logs()
        self.hp_bar.update()
        
        # Process attacks based on enemy_first flag
        # For DCom battles: enemy attacks first (enemy_first=True)
        # For normal PvP/battles: player attacks first (enemy_first=False)
        # Nothing new is thrown once the battle is decided -- the hold is for
        # watching the blow that decided it, not for fitting another round in.
        if self._battle_end_frames is not None:
            pass
        elif self.enemy_first:
            # Enemy attacks first (DCom V2 protocol - device2 initiates)
            for i in range(len(self.battle_player.team2)):
                if self.battle_player.turns[i] <= self.turn_limit and self.battle_player.team2_shot[i] and self.battle_player.phase[i] == "enemy_attack":
                    self.setup_enemy_attack(self.battle_player.team2[i])
                    self.battle_player.team2_shot[i] = False
            
            for i in range(len(self.battle_player.team1)):
                if self.battle_player.turns[i] <= self.turn_limit and self.battle_player.team1_shot[i] and self.battle_player.phase[i] == "pet_attack":
                    self.setup_pet_attack(self.battle_player.team1[i])
                    self.battle_player.team1_shot[i] = False
        else:
            # Player attacks first (normal order)
            for i in range(len(self.battle_player.team1)):
                if self.battle_player.turns[i] <= self.turn_limit and self.battle_player.team1_shot[i] and self.battle_player.phase[i] == "pet_attack":
                    self.setup_pet_attack(self.battle_player.team1[i])
                    self.battle_player.team1_shot[i] = False

            for i in range(len(self.battle_player.team2)):
                if self.battle_player.turns[i] <= self.turn_limit and self.battle_player.team2_shot[i] and self.battle_player.phase[i] == "enemy_attack":
                    self.setup_enemy_attack(self.battle_player.team2[i])
                    self.battle_player.team2_shot[i] = False

        self.update_battle_pet_projectiles()
        self.update_battle_enemy_projectiles()

        # Check for battle termination
        if self.pvp_mode:
            # For PvP, check if simulation is complete or if we've run out of battle log entries
            max_turn = max(self.battle_player.turns)
            battle_log_length = len(self.global_battle_log.battle_log) if hasattr(self.global_battle_log, 'battle_log') else 0
            
            # Check if all pets have finished their turns, reached the end of battle log, or a team is KO'd
            if (self.battle_player.team1_total_hp <= 0 or self.battle_player.team2_total_hp <= 0 or
                all(turn > self.turn_limit for turn in self.battle_player.turns) or 
                max_turn > battle_log_length or
                all(phase == "result" for phase in self.battle_player.phase)):
                if self._battle_end_frames is None:
                    runtime_globals.game_console.log(
                        f"PvP battle finished: max_turn={max_turn}, "
                        f"log_length={battle_log_length}")
                self._request_battle_end()
        else:
            # For PvE, use HP-based termination
            if self.battle_player.team1_total_hp <= 0 or self.battle_player.team2_total_hp <= 0 or all(turn > self.turn_limit for turn in self.battle_player.turns):
                if self._battle_end_frames is None:
                    runtime_globals.game_console.log(
                        "All pairs finished battle, entering result phase")
                self._request_battle_end()

        # Held after the last blow so the hit animation and the HP bar drain
        # can finish; the projectiles above keep updating throughout, so the
        # shot that ends the fight lands on screen before the result arrives.
        if self._battle_end_frames is not None:
            self._battle_end_frames += 1
            if self._battle_end_ready():
                self._battle_end_frames = None
                self.phase = "result" if not self.boss else "clear"
                self.frame_counter = 0

    def setup_pet_attack(self, pet):
        """
        Sets up the pet's attack animation and projectiles using the global battle log.
        """
        # Find the index of the pet in team1
        pet_index = self.battle_player.team1.index(pet)

        # Determine the current turn (1-based)
        turn = self.battle_player.turns[pet_index]

        # Get the correct log entry for this turn
        if turn - 1 >= len(self.global_battle_log.battle_log):
            runtime_globals.game_console.log(f"[BattleEncounter] Invalid turn {turn} for pet {pet_index}, log length is {len(self.global_battle_log.battle_log)}")
            # Still need to set shot_wait so battle can progress to enemy turn
            self.battle_player.shot_wait[pet_index] = True
            return
        turn_log = self.global_battle_log.battle_log[turn - 1]

        # For PvP, determine which device this pet belongs to from the perspective of the battle log
        # Both devices use the same battle log and same visual team arrangement:
        # Team1 (left) = device1 pets, Team2 (right) = device2 pets
        if self.pvp_mode:
            # For DCom battles, device mapping is swapped: device1=opponent, device2=player
            # So team1 (player) should look for device2 attacks
            if hasattr(self, 'is_dcom_mode') and self.is_dcom_mode:
                device_label = "device2"  # Player is device2 in DCom battle logs
            else:
                # Normal PvP: team1 maps to device1
                device_label = "device1"
        else:
            # PvE: my pets are always device1
            device_label = "device1"

        # Find the attack entry for this pet
        attack_entry = next(
            (a for a in turn_log.attacks if a.device == device_label and a.attacker == pet_index),
            None
        )

        runtime_globals.game_console.log(f"Device {device_label} turn {turn} attack {attack_entry}")

        if not attack_entry:
            runtime_globals.game_console.log(f"[BattleEncounter] No attack entry found for pet {pet_index} in turn {turn} for device {device_label}")
            # Still need to set shot_wait so battle can progress to enemy turn
            self.battle_player.shot_wait[pet_index] = True
            return

        # ALWAYS use the attack pattern value, regardless of hit/miss
        # The 'damage' field stores the pattern value (1=weak, 2=strong)
        # The 'hit' field indicates whether the attack connected
        hits = attack_entry.damage
        defender_idx = attack_entry.defender if attack_entry else 0

        if pet_index != defender_idx:
            runtime_globals.game_console.log(f"[BattleEncounter] Pet {pet_index} attacking defender {defender_idx} with hits: {hits}")

        # Update debug battle log for this pet
        if game_globals.configuration.debug_mode and pet_index < len(self.debug_battle_logs):
            self.debug_battle_logs[pet_index]["turn"] = turn
            self.debug_battle_logs[pet_index]["arrow"] = ">"
            # Don't show hit info during attack phase, only during charge

        # Choose attack sprite based on protocol/ruleset
        # Cap hits at 5 for animation (bonuses don't affect animation)
        anim_hits = min(5, hits)

        # Critical/slide-in is now driven by the simulator's `critical` flag on
        # the AttackLog (set when the BASE pattern damage equals 5, before
        # buffs/level bonuses). The pet still needs a SPECIAL frame and a
        # module that allows the slide visual.
        is_crit = (bool(getattr(attack_entry, "critical", False))
                   and self.module.enable_special_attack_sprite
                   and self._has_special_frame(pet))
        self.battle_player.special_attack[pet_index] = is_crit

        style = self._attack_animation_style()
        forced = self._forced_attack_sprite()
        if forced:
            # This wire draws one shot for every Digimon (DMOG).
            atk_id = str(forced)
        elif style == "count":
            # DMOG/DMC: the shot is N copies of atk_main and nothing else --
            # these wires never draw the alternate sprite.
            atk_id = str(getattr(pet, "atk_main", 30))
        elif style == "count_alt":
            # PENOG: same one-sprite-per-damage rule, but a strong shot is
            # drawn with atk_alt where the pet has one.
            alt = getattr(pet, "atk_alt", 0) or 0
            atk_id = str(alt if anim_hits >= 2 and alt > 0
                         else getattr(pet, "atk_main", 30))
        elif style == "paired":
            # DM20/PEN20: see _paired_shot.
            atk_id, paired_count, paired_double = self._paired_shot(pet, anim_hits)
        elif style == "simple":
            # DM20/PEN20: 1-2 attack types, 70% atk_main / 30% atk_alt random
            if getattr(pet, "atk_alt", 0) > 0 and random.random() < 0.3:
                atk_id = str(pet.atk_alt)
            else:
                atk_id = str(pet.atk_main)
        if style not in ("count", "count_alt", "paired", "simple") and not forced:
            # DMX/PENZ/INTERNAL_PVE: see _ladder_shot. The crit bank is a
            # separate folder, so the sprite is resolved with the id.
            atk_sprite, atk_id, ladder_count, ladder_double = self._ladder_sprite(
                pet, anim_hits, bool(getattr(attack_entry, "critical", False)))
        else:
            atk_sprite = self.get_attack_sprite(pet, atk_id)
        if atk_sprite is None:
            runtime_globals.game_console.log(
                f"[BattleEncounter] pet has no drawable attack sprite "
                f"({atk_id}); skipping its shot")
            self.battle_player.shot_wait[pet_index] = True
            return

        # Start position — store as character center Y so any sprite size is drawn centered
        y = self.get_y(pet_index, len(self.battle_player.team1)) + runtime_globals.PET_HEIGHT // 2
        x = self.get_team1_x(pet_index)

        # Target position
        if defender_idx < len(self.battle_player.team2):
            target_enemy = self.battle_player.team2[defender_idx]
            target_x = self.get_team2_x(defender_idx) + (runtime_globals.PET_WIDTH_BOSS if self.boss else runtime_globals.PET_WIDTH) // 2
            target_y = self.get_y(defender_idx, len(self.battle_player.team2)) + runtime_globals.PET_HEIGHT // 2
        else:
            target_x, target_y = x, y

        dx = target_x - x
        dy = target_y - y
        angle = -math.degrees(math.atan2(dy, dx))
        atk_sprite = pygame.transform.flip(atk_sprite, True, True)
        rotated_sprite = pygame.transform.rotate(atk_sprite, angle)

        self.battle_player.team1_projectiles[pet_index] = []
        self._play_shot_sound(self.battle_player.team1_hp)
        s = runtime_globals.UI_SCALE
        if style in ("count", "count_alt"):
            # One sprite per point of damage. A 2 is two shots, not one
            # bigger one -- the device draws it that way.
            offsets = self._count_offsets(anim_hits, s)
            base_pos = [x, y - rotated_sprite.get_height() // 2]
            base_tgt = [target_x, target_y - rotated_sprite.get_height() // 2]
            self.battle_player.team1_projectiles[pet_index].append(
                self._combine_projectile_sprites(rotated_sprite, offsets, base_pos, base_tgt, attack_entry))
        elif style == "paired":
            # DM20/PEN20: the count and the size come from the pair, not from
            # the damage value itself.
            if paired_double:
                rotated_sprite = pygame.transform.scale2x(rotated_sprite.copy())
            offsets = self._count_offsets(paired_count, s)
            base_pos = [x, y - rotated_sprite.get_height() // 2]
            base_tgt = [target_x, target_y - rotated_sprite.get_height() // 2]
            self.battle_player.team1_projectiles[pet_index].append(
                self._combine_projectile_sprites(rotated_sprite, offsets, base_pos, base_tgt, attack_entry))
        elif style == "simple":
            # DM20/PEN20: 1 or 2 projectiles, scale2x for 2
            if anim_hits >= 2:
                rotated_sprite = pygame.transform.scale2x(rotated_sprite.copy())
            by = y - rotated_sprite.get_height() // 2
            bty = target_y - rotated_sprite.get_height() // 2
            self.battle_player.team1_projectiles[pet_index].append([rotated_sprite, [x, by], [target_x, bty], attack_entry])
        else:
            # DMX/PENZ/INTERNAL_PVE: see _ladder_shot. The count and the size
            # come with the sprite, so the crit sprite is already loaded and
            # only a pet without one needs the double.
            if ladder_double:
                rotated_sprite = pygame.transform.scale2x(rotated_sprite.copy())
            offsets = self._count_offsets(ladder_count, s)
            base_pos = [x, y - rotated_sprite.get_height() // 2]
            base_tgt = [target_x, target_y - rotated_sprite.get_height() // 2]
            self.battle_player.team1_projectiles[pet_index].append(
                self._combine_projectile_sprites(rotated_sprite, offsets, base_pos, base_tgt, attack_entry))

    def setup_enemy_attack(self, enemy):
        """
        Sets up the enemy's attack animation and projectiles using the global battle log.
        Handles boss attacks (multiple per turn).
        """
        # Find the index of the enemy in team2
        enemy_index = self.battle_player.team2.index(enemy)

        # Determine the current turn (1-based)
        turn = self.battle_player.turns[enemy_index]

        # Get the correct log entry for this turn
        if turn - 1 >= len(self.global_battle_log.battle_log):
            runtime_globals.game_console.log(f"[BattleEncounter] Invalid turn {turn} for enemy {enemy_index}, log length is {len(self.global_battle_log.battle_log)}")
            # Still need to set shot_wait so battle can progress
            self.battle_player.shot_wait[enemy_index] = True
            return
        turn_log = self.global_battle_log.battle_log[turn - 1]

        # For PvP, determine which device this enemy belongs to from the perspective of the battle log
        # Both devices use the same battle log and same visual team arrangement:
        # Team1 (left) = device1 pets, Team2 (right) = device2 pets
        if self.pvp_mode:
            # For DCom battles, device mapping is swapped: device1=opponent, device2=player
            # So team2 (enemy) should look for device1 attacks
            if hasattr(self, 'is_dcom_mode') and self.is_dcom_mode:
                device_label = "device1"  # Opponent is device1 in DCom battle logs
            else:
                # Normal PvP: team2 maps to device2
                device_label = "device2"
        else:
            # PvE: enemy attacks are always device2
            device_label = "device2"

        # For bosses, collect all attacks by this enemy in this turn
        attack_entries = [
            a for a in turn_log.attacks
            if a.device == device_label and a.attacker == enemy_index
        ]

        runtime_globals.game_console.log(f"Device {device_label} turn {turn} attack {attack_entries}")

        if not attack_entries:
            runtime_globals.game_console.log(f"[BattleEncounter] No attack entries found for enemy {enemy_index} in turn {turn} for device {device_label}")
            # Still need to set shot_wait so battle can progress to next turn
            self.battle_player.shot_wait[enemy_index] = True
            return

        # ALWAYS use the attack pattern value, regardless of hit/miss
        # The 'damage' field stores the pattern value (1=weak, 2=strong)
        # The 'hit' field indicates whether the attack connected
        hits = attack_entries[0].damage if attack_entries else 0
        # Cap hits at 5 for animation (bonuses don't affect animation)
        anim_hits = min(5, hits)
        
        # Critical/slide-in is now driven by the simulator's `critical` flag on
        # the AttackLog (set when the BASE pattern damage equals 5, before
        # buffs/level bonuses). Pet must also have a SPECIAL frame and the
        # module must allow the slide visual.
        entry_is_crit = bool(any(getattr(a, "critical", False) for a in attack_entries))
        if enemy_index < len(self.battle_player.special_attack_enemy):
            self.battle_player.special_attack_enemy[enemy_index] = (
                entry_is_crit
                and self.module.enable_special_attack_sprite
                and self._has_special_frame(enemy)
            )
        
        # Update debug battle log for enemy attacks (affects the defender pet)
        if game_globals.configuration.debug_mode and attack_entries:
            for attack_entry in attack_entries:
                defender_idx = attack_entry.defender
                if defender_idx < len(self.debug_battle_logs):
                    self.debug_battle_logs[defender_idx]["turn"] = turn
                    self.debug_battle_logs[defender_idx]["arrow"] = "<"
                    # Don't show hit info during attack phase, only during charge
        
        # Choose attack sprite based on protocol/ruleset
        style = self._attack_animation_style()
        forced = self._forced_attack_sprite()
        if forced:
            # This wire draws one shot for every Digimon (DMOG).
            atk_id = str(forced)
        elif style == "count":
            # DMOG/DMC: the shot is N copies of atk_main and nothing else.
            atk_id = str(getattr(enemy, "atk_main", 30))
        elif style == "count_alt":
            # PENOG: a strong shot is drawn with atk_alt where it has one.
            alt = getattr(enemy, "atk_alt", 0) or 0
            atk_id = str(alt if anim_hits >= 2 and alt > 0
                         else getattr(enemy, "atk_main", 30))
        elif style == "paired":
            # DM20/PEN20: see _paired_shot.
            atk_id, paired_count, paired_double = self._paired_shot(enemy, anim_hits)
        elif style == "simple":
            # DM20/PEN20: 1-2 attack types, 70% atk_main / 30% atk_alt random
            atk_alt = getattr(enemy, "atk_alt", None)
            if atk_alt is not None and atk_alt > 0 and random.random() < 0.3:
                atk_id = str(atk_alt)
            else:
                atk_id = str(getattr(enemy, "atk_main", 30))
        if style not in ("count", "count_alt", "paired", "simple") and not forced:
            # DMX/PENZ/INTERNAL_PVE: see _ladder_shot.
            base_sprite, atk_id, ladder_count, ladder_double = self._ladder_sprite(
                enemy, anim_hits, entry_is_crit)
        else:
            base_sprite = self.get_attack_sprite(enemy, atk_id)
        if base_sprite is None:
            # Nothing to draw at all: skip the volley rather than take the
            # battle down with it.
            runtime_globals.game_console.log(
                f"[BattleEncounter] enemy has no drawable attack sprite "
                f"({atk_id}); skipping its shot")
            return
        base_sprite = pygame.transform.flip(base_sprite, True, False)

        y = self.get_y(enemy_index, len(self.battle_player.team2)) + runtime_globals.PET_HEIGHT // 2
        x = self.get_team2_x(enemy_index) + (runtime_globals.PET_WIDTH_BOSS if self.boss else runtime_globals.PET_WIDTH) // 2

        # Once per turn, not once per target: a boss firing at several pets is
        # still a single volley.
        self._play_shot_sound(self.battle_player.team2_hp)

        # For each attack entry (boss may attack multiple pets in one turn)
        for attack_entry in attack_entries:
            defender_idx = attack_entry.defender if attack_entry else 0
            self.battle_player.team2_projectiles[defender_idx] = []
            # Target position
            if defender_idx < len(self.battle_player.team1):
                target_pet_x = self.get_team1_x(defender_idx) - (runtime_globals.PET_WIDTH // 2)
                target_pet_y = self.get_y(defender_idx, len(self.battle_player.team1)) + runtime_globals.PET_HEIGHT // 2
            else:
                target_pet_x, target_pet_y = x, y

            dx = target_pet_x - x
            dy = target_pet_y - y
            angle = -math.degrees(math.atan2(dy, dx))
            rotated_sprite = pygame.transform.rotate(base_sprite, angle)

            # Add projectile for this attack based on protocol/ruleset
            s = runtime_globals.UI_SCALE
            if style in ("count", "count_alt"):
                # One sprite per point of damage, mirrored because the enemy
                # fires the other way.
                offsets = self._count_offsets(anim_hits, s, mirrored=True)
                base_pos = [x, y - rotated_sprite.get_height() // 2]
                base_tgt = [target_pet_x, target_pet_y - rotated_sprite.get_height() // 2]
                self.battle_player.team2_projectiles[defender_idx].append(
                    self._combine_projectile_sprites(rotated_sprite, offsets, base_pos, base_tgt, attack_entry))
            elif style == "paired":
                # DM20/PEN20, mirrored because the enemy fires the other way.
                if paired_double:
                    rotated_sprite = pygame.transform.scale2x(rotated_sprite)
                offsets = self._count_offsets(paired_count, s, mirrored=True)
                base_pos = [x, y - rotated_sprite.get_height() // 2]
                base_tgt = [target_pet_x, target_pet_y - rotated_sprite.get_height() // 2]
                self.battle_player.team2_projectiles[defender_idx].append(
                    self._combine_projectile_sprites(rotated_sprite, offsets, base_pos, base_tgt, attack_entry))
            elif style == "simple":
                # DM20/PEN20: 1 or 2 projectiles, scale2x for 2
                if anim_hits >= 2:
                    rotated_sprite = pygame.transform.scale2x(rotated_sprite)
                by = y - rotated_sprite.get_height() // 2
                bty = target_pet_y - rotated_sprite.get_height() // 2
                self.battle_player.team2_projectiles[defender_idx].append([rotated_sprite, [x, by], [target_pet_x, bty], attack_entry])
            else:
                # DMX/PENZ/INTERNAL_PVE: see _ladder_shot. An enemy fires the
                # other way, so the spread is mirrored.
                if ladder_double:
                    rotated_sprite = pygame.transform.scale2x(rotated_sprite)
                offsets = self._count_offsets(ladder_count, s, mirrored=True)
                base_pos = [x, y - rotated_sprite.get_height() // 2]
                base_tgt = [target_pet_x, target_pet_y - rotated_sprite.get_height() // 2]
                self.battle_player.team2_projectiles[defender_idx].append(
                    self._combine_projectile_sprites(rotated_sprite, offsets, base_pos, base_tgt, attack_entry))

    def _combine_projectile_sprites(self, sprite, offsets, base_pos, base_target, attack_entry):
        """Combine a sprite rendered at multiple offsets into a single projectile entry."""
        if len(offsets) == 1:
            ox, oy = offsets[0]
            return [sprite.copy(), [base_pos[0] + ox, base_pos[1] + oy],
                    [base_target[0] + ox, base_target[1] + oy], attack_entry]
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
        return [combined,
                [base_pos[0] + min_ox, base_pos[1] + min_oy],
                [base_target[0] + min_ox, base_target[1] + min_oy],
                attack_entry]

    def move_towards(self, pos, target, speed):
        dx = target[0] - pos[0]
        dy = target[1] - pos[1]
        dist = math.hypot(dx, dy)
        if dist == 0:
            return pos
        step = min(speed, dist)
        return [pos[0] + dx / dist * step, pos[1] + dy / dist * step]


    def update_battle_pet_projectiles(self):
        if len(self.battle_player.team1_projectiles) == 0:
            return

        # Use actual elapsed time for smooth frame-rate independent movement
        now = pygame.time.get_ticks()
        if not hasattr(self, '_last_pet_proj_tick'):
            self._last_pet_proj_tick = now
        dt_ms = min(100, max(1, now - self._last_pet_proj_tick))
        self._last_pet_proj_tick = now
        speed = combat_constants.ATTACK_SPEED * 30 * dt_ms / 1000

        for i, main_data in enumerate(self.battle_player.team1_projectiles):
            if len(main_data) == 0:
                continue

            done = True
            for sprite_data in main_data:
                sprite, pos, target, attack_entry = sprite_data
                new_pos = self.move_towards(pos, target, speed)
                sprite_data[1][0], sprite_data[1][1] = new_pos
                if math.hypot(new_pos[0] - target[0], new_pos[1] - target[1]) > 2:
                    done = False

            # When all projectiles are done for this attack
            if done:
                defender_idx = attack_entry.defender
                hit = attack_entry.hit
                # `damage` is the attack-type id on some wires -- it is what
                # the projectiles are counted from. The HP it costs is a
                # separate scale there (a DMX critical is type 5 but takes
                # 10 HP), so spend hp_damage when the log carries one.
                damage = attack_entry.hp_damage
                if damage is None:
                    damage = attack_entry.damage

                # Play hit or miss sound and animation
                self.battle_player.shot_wait[i] = True
                if hit:
                    enemy = self.battle_player.team2[defender_idx]
                    enemy_y = self.get_y(defender_idx, len(self.battle_player.team2))
                    enemy_x = self.get_team2_x(defender_idx) + (runtime_globals.PET_WIDTH_BOSS if self.boss else runtime_globals.PET_WIDTH) // 2
                    self.hit_animations.append([0, [enemy_x, enemy_y + (16 * runtime_globals.UI_SCALE)]])
                    runtime_globals.game_sound.play("attack_hit")

                    # Apply damage
                    self.battle_player.team2_hp[defender_idx] = max(0, self.battle_player.team2_hp[defender_idx] - damage)
                    self.battle_player.team2_total_hp = sum(self.battle_player.team2_hp)
                    # Trigger HPBar animation for enemy (left side) and update current HP
                    self.hp_bar.add_damage('left', damage)
                    self.hp_bar.set_current_hp(left_current=self.battle_player.team2_total_hp)

                    self.battle_player.team2_bar_counters[defender_idx] = BAR_COUNTER
                else:
                    runtime_globals.game_sound.play("attack_fail")
                    if defender_idx >= 0 and defender_idx < len(self.battle_player.team2):
                        enemy = self.battle_player.team2[defender_idx]
                        enemy_y = self.get_y(defender_idx, len(self.battle_player.team2))
                        enemy_x = self.get_team2_x(defender_idx)
                        runtime_globals.game_message.add("MISS", (enemy_x + (16 * runtime_globals.UI_SCALE), enemy_y - (10 * runtime_globals.UI_SCALE)), (255, 0, 0))

                self.battle_player.team1_projectiles[i] = []

        # Check if all pets/enemies are in result phase
        if all(phase == "result" for phase in self.battle_player.phase):
            self._request_battle_end()

    def update_battle_enemy_projectiles(self):
        if len(self.battle_player.team2_projectiles) == 0:
            return

        # Use actual elapsed time for smooth frame-rate independent movement
        now = pygame.time.get_ticks()
        if not hasattr(self, '_last_enemy_proj_tick'):
            self._last_enemy_proj_tick = now
        dt_ms = min(100, max(1, now - self._last_enemy_proj_tick))
        self._last_enemy_proj_tick = now
        speed = combat_constants.ATTACK_SPEED * 30 * dt_ms / 1000

        for i, main_data in enumerate(self.battle_player.team2_projectiles):
            if len(main_data) == 0:
                continue

            done = True
            for sprite_data in main_data:
                sprite, pos, target, attack_entry = sprite_data
                new_pos = self.move_towards(pos, target, speed)
                sprite_data[1][0], sprite_data[1][1] = new_pos
                if math.hypot(new_pos[0] - target[0], new_pos[1] - target[1]) > 2:
                    done = False

            # When all projectiles are done for this attack
            if done:
                index = i
                if self.boss:
                    index = 0
                defender_idx = attack_entry.defender
                hit = attack_entry.hit
                # `damage` is the attack-type id on some wires -- it is what
                # the projectiles are counted from. The HP it costs is a
                # separate scale there (a DMX critical is type 5 but takes
                # 10 HP), so spend hp_damage when the log carries one.
                damage = attack_entry.hp_damage
                if damage is None:
                    damage = attack_entry.damage
                self.battle_player.shot_wait[index] = True
                if hit:
                    pet_y = self.get_y(defender_idx, len(self.battle_player.team1))
                    pet_x = self.get_team1_x(defender_idx) + (runtime_globals.PET_WIDTH // 2)
                    self.hit_animations.append([0, [pet_x, pet_y + (24 * runtime_globals.UI_SCALE)]])
                    runtime_globals.game_sound.play("attack_hit")
                    self.battle_player.team1_hp[defender_idx] = max(0, self.battle_player.team1_hp[defender_idx] - damage)
                    self.battle_player.team1_total_hp = sum(self.battle_player.team1_hp)
                    # Trigger HPBar animation for player (right side) and update current HP
                    self.hp_bar.add_damage('right', damage)
                    self.hp_bar.set_current_hp(right_current=self.battle_player.team1_total_hp)

                    self.battle_player.team1_bar_counters[defender_idx] = BAR_COUNTER
                else:
                    runtime_globals.game_sound.play("attack_fail")
                    if defender_idx >= 0 and defender_idx < len(self.battle_player.team1):
                        pet_y = self.get_y(defender_idx, len(self.battle_player.team1))
                        pet_x = self.get_team1_x(defender_idx)
                        runtime_globals.game_message.add("MISS", (pet_x + (16 * runtime_globals.UI_SCALE), pet_y - (10 * runtime_globals.UI_SCALE)), (255, 0, 0))
                
                self.battle_player.team2_projectiles[i] = []

        # Check if all pets/enemies are in result phase
        if all(phase == "result" for phase in self.battle_player.phase):
            self._request_battle_end()

    def update_clear(self):
        """
        Update logic for the update_clear phase,
        """

        if not self.boss or self.frame_counter > int(30 * ( constants.FRAME_RATE / 30)):
            self.frame_counter = 0
            self.phase = "result"

    def _has_result_rewards(self):
        """Check if there are any meaningful rewards to display on the result screen."""
        if self.pvp_mode:
            return True  # Always show PvP results
        if self.battle_player.xp > 0 or self.battle_player.bonus > 0:
            return True
        if getattr(self, 'prize_item', None) is not None:
            return True
        if any(self.battle_player.level_up):
            return True
        # Check if any pet's module uses gcells and would gain/lose points
        for pet in self.battle_player.team1:
            pet_module = get_module(getattr(pet, 'module', self.module.name))
            if getattr(pet_module, 'use_gcells', False):
                if self.victory_status == "Victory":
                    if getattr(pet_module, 'gcell_battle_win', 0) != 0:
                        return True
                else:
                    if getattr(pet_module, 'gcell_battle_loose', 0) != 0:
                        return True
        return False

    def update_result(self):
        """
        Update logic for the result phase, handles victory or defeat actions.
        """
        # Skip the result screen entirely if there are no rewards to show
        if self.result_timer == 0 and not self._has_result_rewards():
            runtime_globals.game_console.log("[BattleEncounter] No rewards to display, skipping result screen")
            # Still need to run the post-result logic (progression, unlocks, etc.)
            # Jump the timer past the wait threshold to fall through immediately
            self.result_timer = int(120 * (constants.FRAME_RATE / 30))

        # Result timer, frame-rate independent
        self.result_timer += 1

        if self.result_timer < int(120 * ( constants.FRAME_RATE / 30)):
            # pisca aviso clear
            return

        # For PvP battles, update per-pet PvP counters, run unlock checks, then
        # return to game after showing results. We maintain per-pet counters so
        # unlocks that rely on PvP wins/participation can reference them.
        if self.pvp_mode:
            # Play appropriate sound
            runtime_globals.game_sound.play("happy" if self.victory_status == "Victory" else "fail")

            # Update each local pet's PvP counters. Pets on team1 are the local
            # owner's pets in PvP mode.
            for i, pet in enumerate(self.battle_player.team1):
                try:
                    pet.pvp_battles += 1
                    pet._deduct_battle_cost()
                    # Determine if this pet won its pairing
                    if hasattr(self.battle_player, 'winners') and i < len(self.battle_player.winners):
                        winner = self.battle_player.winners[i]
                        local_won = (winner == 'team1') or (self.victory_status == 'Victory')
                    else:
                        # Fallback: use global victory_status when per-pair winners
                        # are not available
                        local_won = (self.victory_status == 'Victory')

                    if local_won:
                        pet.pvp_wins += 1

                    # Persist these counters to global save state via runtime globals
                    # so they'll be picked up on next autosave
                    runtime_globals.game_console.log(f"[PvP] Pet {getattr(pet,'name',i)} pvp_battles={pet.pvp_battles} pvp_wins={pet.pvp_wins}")
                except Exception as e:
                    runtime_globals.game_console.log(f"[PvP] Error updating pet PvP counters: {e}")

            # Unlock logic for PvP: scan module unlock entries of type 'pvp' and
            # compare their "amount" to the pet owner's pvp_wins count.
            try:
                module_unlocks = getattr(self.module, 'unlocks', []) or []
                for unlock in module_unlocks:
                    if unlock.get('type') == 'pvp':
                        req = unlock.get('amount', None)
                        name = unlock.get('name')
                        if req is None or not name:
                            continue
                        # If any local pet has pvp_wins >= req, unlock for module
                        for pet in self.battle_player.team1:
                            if getattr(pet, 'pvp_wins', 0) >= int(req):
                                unlock_item(self.module.name, 'pvp', name)
                                break
            except Exception as e:
                runtime_globals.game_console.log(f"[PvP] Error processing PvP unlocks: {e}")

            # Return to main scene after PvP
            self.return_to_main_scene()
            return
        
        # Random encounters skip progression and return to game immediately
        if self.is_special_encounter:
            # Beating a Friend encounter is the only way to win the Friend:
            # it goes into the digidex and the module's Friend list, and the
            # main game shows it celebrating on the way back. Losing registers
            # nothing, so it stays in the pool for another attempt.
            if self.victory_status == "Victory":
                try:
                    from utils.xros_utils import register_friend, _find_friend_monster
                    from utils.utils_unlocks import check_encounter_unlocks
                    for enemy in (self.battle_player.team2 or []):
                        name = getattr(enemy, "name", None)
                        if not name or not _find_friend_monster(self.module, name):
                            continue
                        if register_friend(self.module.name, name):
                            runtime_globals.friend_celebration = {
                                "name": name, "module": self.module.name}
                        break
                    # Friends register first, so an unlock counting them sees
                    # the one just won.
                    check_encounter_unlocks(self.module.name,
                                            self.battle_player.team2)
                except Exception as exc:
                    runtime_globals.game_console.log(f"[Friend] register failed: {exc}")
            runtime_globals.game_sound.play("happy" if self.victory_status == "Victory" else "fail")
            self.return_to_main_scene()
            return

        area_advanced = False
        pets = get_battle_continue_targets()
        if self.victory_status == "Victory":
            if not self.boss:
                if len(pets) == 0:
                    # No more pets capable of continuing the battle
                    runtime_globals.game_sound.play("fail")
                    self._start_retire_animation()
                    return
                else:
                    self.round += 1
                    # Check if the new round has enemies; if not, the area is cleared
                    next_versions = self.module.get_enemy_versions(self.area, self.round, special_encounter=self.is_special_encounter)
                    if not next_versions:
                        # Area cleared — advance to next area
                        self.area += 1
                        self.round = 1
                        area_advanced = True
                        if self.module.area_exists(self.area):
                            game_globals.battle_round[self.module.name] = self.round
                            game_globals.battle_area[self.module.name] = max(self.area, game_globals.battle_area.get(self.module.name, 0))
                        # Fall through to total victories, unlocks, and return_to_main_scene
                    else:
                        if self.round > game_globals.battle_round[self.module.name]:
                            game_globals.battle_round[self.module.name] = self.round
                        self.victory_status = None
                        if self.module.battle_sequential_rounds:
                            # Check if feeding phase should trigger before next round
                            if self._should_trigger_feeding():
                                self._start_feeding_phase()
                                return
                            self._check_retire_or_proceed()
                            return
            else:
                # --- Unlock adventure items of the area just won ---
                unlocks = getattr(self.module, "unlocks", None)
                if isinstance(unlocks, list):
                    for unlock in unlocks:
                        unlocked = False
                        
                        # Check for area-based unlocks
                        if unlock.get("type") == "adventure" and unlock.get("area") == self.area:
                            unlocked = True
                        
                        # Check for boss-specific unlock keys
                        elif unlock.get("type") == "adventure" and "name" in unlock:
                            unlock_name = unlock["name"]
                            # Check if any defeated enemy has this unlock key
                            for enemy in self.battle_player.team2:
                                if hasattr(enemy, 'unlock') and enemy.unlock == unlock_name:
                                    unlocked = True
                                    runtime_globals.game_console.log(f"[Adventure] Boss {enemy.name} dropped unlock key: {unlock_name}")
                                    break
                        
                        if unlocked:
                            unlock_item(self.module.name, "adventure", unlock["name"])
                            runtime_globals.game_console.log(f"[Adventure] Unlocked: {unlock['name']}")

                self.area += 1
                self.round = 1
                area_advanced = True

                # Clearing an area promises a Friend encounter to one of the
                # pets that cleared it — but only a pet of THIS module that has
                # a DigiXros form asking for Friends, since a pet can only ever
                # unlock the Friends its own forms need.
                if not self.is_special_encounter:
                    try:
                        from utils.xros_utils import promise_friend_event
                        promise_friend_event(self.module.name,
                                             self.battle_player.team1)
                    except Exception as exc:
                        runtime_globals.game_console.log(
                            f"[Friend] promise failed: {exc}")

                # An area the module keeps locked is not progress the player
                # can act on yet, so don't move them into it.
                if (self.module.area_exists(self.area)
                        and self.module.is_area_unlocked(
                            self.area, getattr(self, "version", None))):
                    game_globals.battle_round[self.module.name] = self.round
                    game_globals.battle_area[self.module.name] = max(self.area, game_globals.battle_area[self.module.name])
            
            # Increment total victories for this module
            if self.module.name not in game_globals.total_victories:
                game_globals.total_victories[self.module.name] = 0
            game_globals.total_victories[self.module.name] += 1
            runtime_globals.game_console.log(f"[Battle] Total victories for {self.module.name}: {game_globals.total_victories[self.module.name]}")
            
            # Check for battle unlocks
            try:
                module_unlocks = getattr(self.module, 'unlocks', []) or []
                for unlock in module_unlocks:
                    if unlock.get('type') == 'battle':
                        req = unlock.get('amount', None)
                        name = unlock.get('name')
                        if req is None or not name:
                            continue
                        # Check if total victories >= required amount
                        current_victories = game_globals.total_victories.get(self.module.name, 0)
                        if current_victories >= int(req):
                            unlock_item(self.module.name, 'battle', name)
                            runtime_globals.game_console.log(f"[Battle] Unlocked {name} after {current_victories} victories")
            except Exception as e:
                runtime_globals.game_console.log(f"[Battle] Error processing battle unlocks: {e}")
        else:
            runtime_globals.game_sound.play("fail")
            # perdeu
            game_globals.battle_round[self.module.name] = 1

        if area_advanced:
            # Adventure coin rewards (Progress Mode only; no-op otherwise).
            # Special/random encounters already returned earlier, so anything
            # here is real adventure progression.
            style = getattr(self.module, 'adventure_style', 'Area Selection')
            if style in ("Next and Reset", "Area Selection"):
                from utils.reward_utils import (reward_area_clear,
                                                reward_adventure_complete)
                # 1 coin the first time an area is cleared by beating its boss.
                if self.boss:
                    reward_area_clear(self.module.name, self.area - 1)
                # 10 coins the first time the module's whole adventure is
                # finished — i.e. the area just cleared was the last one.
                if not self.module.area_exists(self.area):
                    reward_adventure_complete(self.module.name)

        self.return_to_main_scene()

    #========================
    # Region: Feeding Phase
    #========================

    def _should_trigger_feeding(self):
        """Check if the feeding phase should trigger before the next round."""
        if not getattr(self.module, 'battle_enable_feeding', False):
            return False
        if not self.module.battle_sequential_rounds:
            return False
        area_rounds = self.module.get_area_round_counts()
        total_rounds = area_rounds.get(self.area, 0)
        completed_round = self.round - 1  # round was already incremented
        if total_rounds == 5 and completed_round == 3:
            return True
        if total_rounds >= 6 and completed_round == 4:
            return True
        return False

    def _start_feeding_phase(self):
        """Transition to the feeding phase — menu is managed by the view."""
        self.phase = "feeding"
        self.frame_counter = 0
        runtime_globals.game_console.log("[BattleEncounter] Feeding phase started")

    def feed_protein_to_team(self):
        """Feed protein to all team1 pets (called by view on Protein selection)."""
        for pet in self.battle_player.team1:
            pet.set_eating("strength", 1)
        runtime_globals.game_sound.play("menu")
        runtime_globals.game_console.log("[BattleEncounter] Fed all pets protein")

    def end_feeding_and_proceed(self):
        """End the feeding phase and proceed to retire check or next round."""
        runtime_globals.game_console.log("[BattleEncounter] Feeding phase ended")
        self._check_retire_or_proceed()

    def update_feeding(self):
        """Update logic for the feeding phase."""
        pass

    def draw_feeding(self, surface):
        """Draw the feeding phase — pets only; menu overlay is drawn by the view."""
        total = len(self.battle_player.team1)
        height_scale = runtime_globals.SCREEN_HEIGHT / 240
        spacing = min(
            (runtime_globals.SCREEN_WIDTH - int(30 * runtime_globals.UI_SCALE)) // max(total, 1),
            int(runtime_globals.PET_WIDTH * runtime_globals.UI_SCALE) + int(16 * runtime_globals.UI_SCALE),
        )
        total_width = spacing * total
        offset_x = (runtime_globals.SCREEN_WIDTH - total_width) // 2
        y = int(40 * height_scale)

        for i, pet in enumerate(self.battle_player.team1):
            anim_toggle = (self.frame_counter + i * 5) // int(15 * constants.FRAME_RATE / 30) % 2
            frame_id = PetFrame.IDLE1.value if anim_toggle == 0 else PetFrame.HAPPY.value
            sprite = self._sized_pet_sprite(pet.get_sprite(frame_id))
            x = offset_x + i * spacing
            blit_with_cache(surface, sprite, (x, y))

    #========================
    # Region: Retire Phase
    #========================

    def _check_retire_or_proceed(self):
        """Check if any team1 pets can't battle the next round; if so, show retire menu."""
        pets = get_battle_continue_targets()
        if len(pets) == 0:
            # No pets can continue at all
            runtime_globals.game_sound.play("fail")
            self._start_retire_animation()
            return
        # Check if any team1 pets lost eligibility
        retiring = [p for p in self.battle_player.team1 if not p.can_continue_battle()]
        if retiring:
            runtime_globals.game_console.log(
                "[BattleEncounter] Retire check — "
                + "; ".join(f"{p.name}: {p.battle_block_reason(entering=False)}" for p in retiring))
            self._start_retire_check_phase()
        else:
            self.set_initial_state(round=self.round, area=self.area)

    def _start_retire_check_phase(self):
        """Transition to the retire_check phase — menu is managed by the view."""
        self.phase = "retire_check"
        self.frame_counter = 0
        runtime_globals.game_console.log("[BattleEncounter] Retire check phase started")

    def do_retire(self):
        """Player chose to retire — play retire animation and exit (called by view)."""
        runtime_globals.game_sound.play("fail")
        self._start_retire_animation()

    def do_continue_battle(self):
        """Player chose to continue — proceed with remaining capable pets (called by view)."""
        runtime_globals.game_console.log("[BattleEncounter] Player chose to continue")
        self.set_initial_state(round=self.round, area=self.area)

    def _start_retire_animation(self):
        """Play the retire animation before returning to main scene."""
        self.phase = "retire_animation"
        self.frame_counter = 0
        self.animated_sprite.play_retire(duration_seconds=2.0)
        runtime_globals.game_console.log("[BattleEncounter] Retire animation started")

    def update_retire_check(self):
        """Update logic for the retire check phase."""
        pass

    def update_retire_animation(self):
        """Update logic for the retire animation phase."""
        if not self.animated_sprite.is_playing:
            self.return_to_main_scene()

    def draw_retire_check(self, surface):
        """Draw the retire check phase — pets only; menu overlay is drawn by the view."""
        total = len(self.battle_player.team1)
        height_scale = runtime_globals.SCREEN_HEIGHT / 240
        spacing = min(
            (runtime_globals.SCREEN_WIDTH - int(30 * runtime_globals.UI_SCALE)) // max(total, 1),
            int(runtime_globals.PET_WIDTH * runtime_globals.UI_SCALE) + int(16 * runtime_globals.UI_SCALE),
        )
        total_width = spacing * total
        offset_x = (runtime_globals.SCREEN_WIDTH - total_width) // 2
        y = int(40 * height_scale)

        for i, pet in enumerate(self.battle_player.team1):
            can_fight = pet.can_battle()
            if can_fight:
                anim_toggle = (self.frame_counter + i * 5) // int(15 * constants.FRAME_RATE / 30) % 2
                frame_id = PetFrame.IDLE1.value if anim_toggle == 0 else PetFrame.HAPPY.value
            else:
                frame_id = PetFrame.LOSE.value

            sprite = self._sized_pet_sprite(pet.get_sprite(frame_id))

            if not can_fight:
                sprite = sprite.copy()
                sprite.set_alpha(100)

            x = offset_x + i * spacing
            surface.blit(sprite, (x, y))

    def draw_retire_animation(self, surface):
        """Draw the retire animation using AnimatedSprite."""
        self.animated_sprite.draw(surface)

    def load_next_round(self):
        """
        Prepares the next round by resetting health and loading new enemies.
        """
        self.phase = "level"
        self.result_timer  = 0
        # A finished battle's hold must not carry into the next round.
        self._battle_end_frames = None
        self.press_counter = 0
        self.final_color = 3
        self.correct_color = 0
        self.super_hits = 0
        self.color_band = None
        self.frame_counter = 0
        self.enemies = []
        self.enemy_positions = []
        self.load_enemies()

    def draw(self, surface: pygame.Surface):
        """
        Main draw loop for the battle encounter, calls phase-specific draws.
        """
        # Hide HPBar during charge phase for cleaner minigame presentation
        if self.phase not in ["charge", "result", "feeding", "retire_check",
                              "retire_animation", "xros_select", "xros_anim"]:
            self.draw_health_bars(surface)
        #surface.blit(self.backgroundIm, (0, 0))

        # Draw by phase
        if self.phase == "level":
            self.draw_level(surface)
        elif self.phase == "entry":
            self.draw_entry(surface)
        elif self.phase == "intimidate":
            self.draw_intimidate(surface)
        elif self.phase == "xros_select":
            self.draw_xros_select(surface)
        elif self.phase == "xros_anim":
            self.draw_xros_anim(surface)
        elif self.phase == "alert":
            self.draw_alert(surface)
        elif self.phase == "charge":
            self.draw_charge(surface)
        elif self.phase == "battle":
            self.draw_battle(surface)
        elif self.phase == "clear":
            self.draw_clear(surface)
        elif self.phase == "result":
            self.draw_result(surface)
        elif self.phase == "feeding":
            self.draw_feeding(surface)
        elif self.phase == "retire_check":
            self.draw_retire_check(surface)
        elif self.phase == "retire_animation":
            self.draw_retire_animation(surface)

        # Draw debug battle logs if DEBUG_MODE and DEBUG_BATTLE_INFO flags are enabled
        if constants.DEBUG_MODE and constants.DEBUG_BATTLE_INFO and self.phase in ["battle"]:
            self.draw_debug_battle_logs(surface)

    def draw_level(self, surface):
        """
        Draws the level information on the screen using AnimatedSprite component.
        """
        # Check if we need to start the battle level animation
        if not self.animated_sprite.is_animation_playing():
            self.animated_sprite.play_battle_level(duration_seconds=1.0)
        
        # Draw the animated sprite (just the Combat_Level sprite)
        self.animated_sprite.draw(surface)
        
        # Draw area/round text using scaled font
        from ui import ui_constants
        if self.is_special_encounter:
            area_text = "SPECIAL ENCOUNTER"
        else:
            adventure_style = getattr(self.module, 'adventure_style', 'Area Selection')
            if adventure_style == "Next and Reset":
                area_text = f"AREA {self.area}"
            elif adventure_style == "Random":
                # Show first enemy name for Random style
                if self.enemies and self.enemies[0] and hasattr(self.enemies[0], 'name'):
                    area_text = self.enemies[0].name
                else:
                    area_text = f"AREA {self.area}-{self.round}"
            else:
                area_text = f"AREA {self.area}-{self.round}"
        
        # Position: 6 pixels from left in UI space, accounting for UI offset
        text_x = self.ui_manager.ui_offset_x + int(6 * runtime_globals.UI_SCALE)
        
        # Use title font with scaled size (32 * UI_SCALE), left-aligned
        font_size = int(32 * runtime_globals.UI_SCALE)
        font = get_font(font_size)
        text_surface = font.render(area_text, True, ui_constants.GREEN).convert_alpha()
        
        # Center vertically based on actual text height, accounting for UI offset
        text_y = self.ui_manager.ui_offset_y + ((self.ui_manager.ui_height - text_surface.get_height()) // 2)
        surface.blit(text_surface, (text_x, text_y))

    def draw_entry(self, surface):
        """
        Draws the entry phase, showing enemies and pets in their starting positions.
        """
        self.draw_enemies(surface)
        self.draw_pets(surface)
        runtime_globals.game_message.draw(surface)
        self.draw_hit_animations(surface)

    def draw_intimidate(self, surface):
        """
        Draws the intimidate phase, showing warning or battle sprites using AnimatedSprite component.
        """
        if self.frame_counter >= combat_constants.IDLE_ANIM_DURATION // 2:
            # Draw the animated sprite (animation started in update_entry when entering phase)
            self.animated_sprite.draw(surface)
        else:
            self.draw_enemies(surface)
            self.draw_pets(surface)
            runtime_globals.game_message.draw(surface)
            self.draw_hit_animations(surface)

    def draw_alert(self, surface):
        """
        Draws the alert phase, showing readiness sprites using AnimatedSprite component.
        """
        # Do not reveal READY before the sound it is timed against has actually
        # started (adventure only — pvp keeps the fixed-length alert).
        if not self.pvp_mode and not getattr(self, "_ready_sound_started", True):
            return

        ready = READY_PHASE_MINIGAMES.get(
            getattr(self.module, 'battle_minigame', ''))
        instance = getattr(self, ready[0], None) if ready else None
        if instance is not None:
            self.animated_sprite.stop()
            # The minigame shows in both the alert and the charge phase, so
            # draw only its version here.
            instance.set_phase("ready")
            instance.draw(surface)
        else:
            # For other rulesets, use animated sprite ready animation. The
            # previous animation was already stopped when leaving intimidate;
            # stopping again here every frame restarted (and re-loaded) the
            # ready animation on each draw.
            if not self.animated_sprite.is_animation_playing():
                # Match however long the phase is actually going to last, so
                # the animation and the READY sound finish together.
                duration = (getattr(self, "alert_duration_frames",
                                    combat_constants.ALERT_DURATION_FRAMES)
                            / max(1, game_globals.configuration.frame_rate))
                self.animated_sprite.play_ready(duration)

            # Draw the animated sprite
            self.animated_sprite.draw(surface)

    def draw_charge(self, surface):
        """
        Draws the charge phase, showing strength bar, minigame, or Xai roll.

        Dispatches on the module's battle_minigame — the same setting
        setup_charge/update_charge use — so a module whose ruleset and
        minigame don't pair up (e.g. dmc ruleset with minigame "None") can't
        hit a minigame instance that was never created. Each branch is also
        None-guarded for the frame between phase entry and setup.
        """
        minigame = getattr(self.module, 'battle_minigame', 'Dummy Bar')

        # Punch/Mogera (shake punch) render full screen and draw their own
        # pets; every other minigame draws over the battle roster.
        if not (minigame in ("Punch", "Mogera") and self.shake_punch):
            self.draw_enemies(surface)
            self.draw_pets(surface)

        if minigame == "Dummy Bar" and self.dummy_charge:
            self.dummy_charge.draw(surface)
        elif minigame == "Count Match Color" and self.count_match:
            self.count_match.draw(surface)
        elif minigame == "Count Match Classic" and self.count_match_classic:
            self.count_match_classic.draw(surface)
        elif minigame == "Count Match Z" and self.count_match_z:
            self.count_match_z.draw(surface)
        elif minigame in ("Punch", "Mogera") and self.shake_punch:
            self.shake_punch.draw(surface)
        elif minigame in ("Xai Roll+Bar", "Xai Bar"):
            if self.xai_phase == 1 and self.xai_roll:
                self.xai_roll.draw(surface)
            elif self.xai_phase >= 2 and self.xai_bar:
                self.xai_bar.draw(surface)

    def draw_battle(self, surface):
        """
        Draws the battle phase, showing pets and enemies in combat.
        """
        self.draw_enemies(surface)
        self.draw_pets(surface)
        runtime_globals.game_message.draw(surface)
        self.draw_hit_animations(surface)
        self.draw_projectiles(surface)
        self.draw_enemy_projectiles(surface)
        self.draw_health_bars_for_battlers(surface)

    def draw_clear(self, surface):
        """
        Draws the clear of the battle, showing clear sprites using AnimatedSprite component.
        This phase is only reached for boss battles - show win animation here.
        """
        if self.boss:
            # Use AnimatedSprite component for win animation during clear phase
            if not self.animated_sprite.is_animation_playing():
                duration = 1.0  # 1 second win animation (will be followed by clear in result phase)
                self.animated_sprite.play_win(duration)
            
            # Draw the animated sprite
            self.animated_sprite.draw(surface)

    def draw_result(self, surface):
        """
        Upgraded result screen using new UI elements:
        - Title label (WIN/LOSE) at top in theme colors
        - Animated pet sprites (not UI components)
        - Per-pet reward labels below each pet based on module's visible_stats
        - Prize label at bottom using LabelValue
        All labels use global screen positions scaled to any screen size.
        """
        # Start result animation once at the beginning
        if not self.result_animation_started:
            self.animated_sprite.stop()
            if self.victory_status == "Victory" and self.boss:
                # For boss victory: play clear for 1 second (win was already shown in clear phase)
                duration = 1.0
                self.animated_sprite.play_clear(duration)
            elif self.victory_status == "Victory":
                # For normal victory: play win for 2 seconds
                duration = 2.0
                self.animated_sprite.play_win(duration)
            else:
                # For defeat: play lose for 2 seconds
                duration = 2.0
                self.animated_sprite.play_lose(duration)
            self.result_animation_started = True
        
        # Show result animation for the first 1-2 seconds
        if self.animated_sprite.is_playing:
            # Draw the animated sprite
            self.animated_sprite.draw(surface)
        else:
            # Build UI components once (labels for title, pet rewards, and prize)
            if self.result_surface_cache is None:
                # End any temporary evolution now: the result screen shows a
                # brief X_1/X_2 "devolution" flash over the pet's slot and then
                # the normal (pre-evolution) sprite, so the pet is already back
                # to its real form when returning to the main game scene.
                #
                # With Battle Sequential Rounds a non-boss victory result leads
                # into the NEXT round of the same encounter — the evolution is
                # kept in that case and only reverted on the final result
                # (boss / defeat / non-sequential battles).
                battle_may_continue = (
                    self.victory_status == "Victory"
                    and not self.boss
                    and getattr(self.module, 'battle_sequential_rounds', False)
                )
                reverted = []
                if not battle_may_continue:
                    reverted = self._clear_xros_forms()
                self.xros_devolve_pets = set(reverted)
                self.xros_devolve_timer = int(1.0 * constants.FRAME_RATE) if reverted else 0
                self.xros_devolve_sprites = None

                # Use UI constants for colors (not theme colors)
                win_color = ui_constants.GREEN
                lose_color = ui_constants.RED
                white_color = (245, 245, 245)
                yellow_color = ui_constants.YELLOW
                
                # Calculate positions
                width_scale = runtime_globals.SCREEN_WIDTH / 240
                height_scale = runtime_globals.SCREEN_HEIGHT / 240
                
                # Title label at top center (using global positioning)
                title_text = "WIN" if self.victory_status == "Victory" else "LOSE"
                title_color = win_color if self.victory_status == "Victory" else lose_color
                title_y = int(20 * height_scale)
                
                # Create title label (will be centered after rendering)
                self.result_title_label = Label(0, title_y, title_text, is_title=True, color_override=title_color)
                self.result_title_label.manager = self.ui_manager
                
                # Determine pets to display
                if self.pvp_mode and hasattr(self, 'show_team2_in_result') and self.show_team2_in_result:
                    pets = [enemy for enemy in self.battle_player.team2 if hasattr(enemy, 'get_sprite')]
                else:
                    pets = self.battle_player.team1
                
                # Calculate pet layout with better spacing
                total = len(pets)
                # Use larger sprites and better horizontal distribution
                base_sprite_size = runtime_globals.PET_WIDTH  # Use full size instead of half
                sprite_width = int(base_sprite_size)
                sprite_height = int(base_sprite_size)
                
                # Calculate spacing to distribute evenly across width
                margin = int(20 * width_scale)  # Side margins
                gap_between_pets = int(16 * width_scale)  # Gap between pets
                
                # Calculate the actual width occupied by all pets
                if total > 1:
                    # Total width = all sprites + gaps between them
                    total_pets_width = (total * sprite_width) + ((total - 1) * gap_between_pets)
                    
                    # If pets don't fit, scale them down — snapped to the
                    # pixel-perfect ladder so the shrunk sprites stay crisp.
                    available_width = runtime_globals.SCREEN_WIDTH - (2 * margin)
                    if total_pets_width > available_width:
                        from utils.sprite_utils import snap_pet_sprite_size
                        sprite_width = snap_pet_sprite_size(
                            (available_width - ((total - 1) * gap_between_pets)) // total)
                        sprite_height = sprite_width  # Keep square
                        total_pets_width = (total * sprite_width) + ((total - 1) * gap_between_pets)
                else:
                    # Single pet - just the sprite width
                    total_pets_width = sprite_width
                
                # Center the pet group horizontally
                offset_x = (runtime_globals.SCREEN_WIDTH - total_pets_width) // 2
                pets_y = int(50 * height_scale)
                
                # Create per-pet reward labels with doubled font size
                self.result_pet_labels = []
                for i, pet in enumerate(pets):
                    pet_center_x = offset_x + (i * (sprite_width + gap_between_pets)) + sprite_width // 2
                    label_y_start = pets_y + sprite_height + int(12 * height_scale)
                    
                    pet_labels = []
                    current_y = label_y_start
                    
                    # Get pet's module
                    pet_module_name = getattr(pet, 'module', self.module.name)
                    pet_module = get_module(pet_module_name)
                    
                    # Check if module uses G-Cells
                    if getattr(pet_module, 'use_gcells', False):
                        # Calculate G-Cell points gained (from finish_battle logic)
                        if self.victory_status == "Victory":
                            gcell_points = getattr(pet_module, 'gcell_battle_win', 0)
                        else:
                            gcell_points = getattr(pet_module, 'gcell_battle_loose', 0)
                        
                        if gcell_points != 0:
                            # Use title font for doubled size
                            gcell_label = Label(0, current_y, f"GC {gcell_points:+d}", is_title=False, color_override=win_color if gcell_points > 0 else white_color, shadow_mode="full", custom_size=int(16*runtime_globals.UI_SCALE))
                            gcell_label.manager = self.ui_manager
                            pet_labels.append((gcell_label, pet_center_x))
                            current_y += int(28 * height_scale)  # More spacing for larger font
                    
                    # Check if module has Level in visible_stats
                    visible_stats = getattr(pet_module, 'visible_stats', None)
                    if visible_stats and "Level" in visible_stats:
                        # Show level and level up indicator
                        level = getattr(pet, "level", 1)
                        level_up_indicator = ""
                        level_color = white_color
                        
                        if not self.pvp_mode and i < len(self.battle_player.level_up):
                            if self.battle_player.level_up[i]:
                                level_up_indicator = " +"
                                level_color = win_color
                        
                        # Use title font for doubled size
                        level_label = Label(0, current_y, f"Lv {level}{level_up_indicator}", is_title=False, color_override=level_color, shadow_mode="full", custom_size=int(16*runtime_globals.UI_SCALE))
                        level_label.manager = self.ui_manager
                        pet_labels.append((level_label, pet_center_x))
                        current_y += int(28 * height_scale)  # More spacing for larger font
                        
                        # Show experience gained
                        exp_gained = self.battle_player.xp if self.victory_status == "Victory" else 0
                        
                        # Check if at max level
                        if i < len(self.battle_player.team1):
                            max_level_check = self.battle_player.team1[i].level == constants.MAX_LEVEL.get(self.battle_player.team1[i].stage, 99)
                            level_up_check = self.battle_player.level_up[i] if i < len(self.battle_player.level_up) else False
                            
                            if not level_up_check and max_level_check:
                                exp_gained = 0
                        
                        # Use title font for doubled size
                        exp_label = Label(0, current_y, f"Exp +{exp_gained}", is_title=False, color_override=win_color if exp_gained > 0 else white_color, shadow_mode="full", custom_size=int(16*runtime_globals.UI_SCALE))
                        exp_label.manager = self.ui_manager
                        pet_labels.append((exp_label, pet_center_x))
                        current_y += int(28 * height_scale)  # More spacing for larger font
                    
                    self.result_pet_labels.append(pet_labels)
                
                # Create prize labels at bottom (using Label components for doubled font size)
                prize_y = runtime_globals.SCREEN_HEIGHT - int(35 * height_scale)
                prize_label_x = int(20 * width_scale)
                
                # No prize is simply nothing to report — "Prize: None" is just
                # a line of clutter along the bottom of the result screen, so
                # the row is left out entirely in that case.
                if self.victory_status == "Victory" and getattr(self, "prize_item", None):
                    self.result_prize_label_text = Label(prize_label_x, prize_y, "Prize:", is_title=False, color_override=white_color, shadow_mode="full", custom_size=int(32*runtime_globals.UI_SCALE))
                    self.result_prize_label_text.manager = self.ui_manager

                    # Create the prize value label once and cache it
                    prize_value_x = prize_label_x + int(8 * width_scale)  # Will be adjusted after rendering "Prize:" text
                    self.result_prize_value_label = Label(prize_value_x, prize_y, self.prize_item.name, is_title=False, color_override=ui_constants.GREEN, shadow_mode="full", custom_size=int(32*runtime_globals.UI_SCALE))
                    self.result_prize_value_label.manager = self.ui_manager
                else:
                    self.result_prize_label_text = None
                    self.result_prize_value_label = None
                
                # Pre-cache scaled pet sprites to avoid per-frame scaling
                self.result_pet_sprites_cache = {}
                for pet in pets:
                    self.result_pet_sprites_cache[pet] = {}
                    for frame_id in [PetFrame.IDLE1.value, PetFrame.HAPPY.value, PetFrame.LOSE.value]:
                        original_sprite = pet.get_sprite(frame_id)
                        scaled_sprite = pygame.transform.scale(original_sprite, (sprite_width, sprite_height))
                        self.result_pet_sprites_cache[pet][frame_id] = scaled_sprite

                # Pre-scale the X_1/X_2 devolution flash sprites once
                if self.xros_devolve_pets:
                    try:
                        from utils.asset_utils import image_load
                        self.xros_devolve_sprites = [
                            pygame.transform.scale(
                                image_load(f"assets/X_{i}.png").convert_alpha(),
                                (sprite_width, sprite_height))
                            for i in (1, 2)
                        ]
                    except Exception as exc:
                        runtime_globals.game_console.log(f"[Xros] X sprites load failed: {exc}")
                        self.xros_devolve_pets = set()
                        self.xros_devolve_timer = 0
                
                # Store sprite dimensions for drawing
                self.result_sprite_width = sprite_width
                self.result_sprite_height = sprite_height
                self.result_offset_x = offset_x
                self.result_gap_between_pets = gap_between_pets
                self.result_pets_y = pets_y
                
                # Create a single cached surface for ALL static text (rendered once)
                # This avoids per-frame text rendering and shadow blitting which causes flickering
                self.result_static_text_surface = pygame.Surface((runtime_globals.SCREEN_WIDTH, runtime_globals.SCREEN_HEIGHT), pygame.SRCALPHA)
                self.result_static_text_surface.fill((0, 0, 0, 0))  # Transparent
                
                # Render title label (centered at top)
                title_surface = self.result_title_label.render()
                title_x = (runtime_globals.SCREEN_WIDTH - title_surface.get_width()) // 2
                self.result_static_text_surface.blit(title_surface, (title_x, self.result_title_label.rect.y))
                
                # Render prize labels at bottom (absent when there is no prize)
                if self.result_prize_label_text and self.result_prize_value_label:
                    prize_label_surface = self.result_prize_label_text.render()
                    self.result_static_text_surface.blit(prize_label_surface, (self.result_prize_label_text.rect.x, self.result_prize_label_text.rect.y))

                    # Render prize value to the right of label
                    width_scale = runtime_globals.SCREEN_WIDTH / 240
                    prize_value_x = self.result_prize_label_text.rect.x + prize_label_surface.get_width() + int(8 * width_scale)
                    self.result_prize_value_label.rect.x = prize_value_x
                    prize_value_surface = self.result_prize_value_label.render()
                    self.result_static_text_surface.blit(prize_value_surface, (prize_value_x, self.result_prize_label_text.rect.y))
                
                # Render all per-pet labels to the static surface
                for i, pet_labels in enumerate(self.result_pet_labels):
                    pet_center_x = offset_x + (i * (sprite_width + gap_between_pets)) + sprite_width // 2
                    for label, label_center_x in pet_labels:
                        label_surface = label.render()
                        label_x = label_center_x - label_surface.get_width() // 2
                        self.result_static_text_surface.blit(label_surface, (label_x, label.rect.y))
                
                # Mark cache as built
                self.result_surface_cache = True
            
            # Draw the cached static text surface (single blit for all text)
            surface.blit(self.result_static_text_surface, (0, 0))
            
            # Draw animated pet sprites (not cached, drawn directly)
            if self.pvp_mode and hasattr(self, 'show_team2_in_result') and self.show_team2_in_result:
                pets = [enemy for enemy in self.battle_player.team2 if hasattr(enemy, 'get_sprite')]
                # Use team2 indices for frame counters and winners
                team1_count = len(self.battle_player.team1)
                pet_frame_counters = []
                pet_winners = []
                for i in range(len(pets)):
                    frame_counter_idx = team1_count + i
                    if frame_counter_idx < len(self.battle_player.frame_counters):
                        pet_frame_counters.append(self.battle_player.frame_counters[frame_counter_idx])
                    else:
                        pet_frame_counters.append(0)  # Default frame counter
                    
                    winner_idx = team1_count + i  
                    if winner_idx < len(self.battle_player.winners):
                        pet_winners.append(self.battle_player.winners[winner_idx])
                    else:
                        pet_winners.append("team1")  # Default winner
            else:
                pets = self.battle_player.team1
                pet_frame_counters = self.battle_player.frame_counters[:len(self.battle_player.team1)]
                pet_winners = self.battle_player.winners[:len(self.battle_player.team1)]
            
            # Draw each pet sprite and their labels (using cached layout values)
            devolve_active = getattr(self, 'xros_devolve_timer', 0) > 0 and \
                getattr(self, 'xros_devolve_sprites', None)
            for i, pet in enumerate(pets):
                pet_x = self.result_offset_x + (i * (self.result_sprite_width + self.result_gap_between_pets))
                pet_center_x = pet_x + self.result_sprite_width // 2

                # Pets that were temporarily evolved flash the X_1/X_2 sprites
                # briefly before their normal sprite is shown.
                if devolve_active and pet in self.xros_devolve_pets:
                    quarter = max(1, int(constants.FRAME_RATE * 0.25))
                    toggle = (self.xros_devolve_timer // quarter) % 2
                    blit_with_cache(surface, self.xros_devolve_sprites[toggle],
                                    (pet_x, self.result_pets_y))
                    continue

                # Draw pet sprite (animated) using cached scaled sprites
                if i < len(pet_frame_counters):
                    anim_toggle = (pet_frame_counters[i] + i * 5) // (15 * constants.FRAME_RATE / 30) % 2
                else:
                    anim_toggle = 0

                if (i < len(pet_winners) and pet_winners[i] == "team2") or self.victory_status == "Defeat":
                    frame_id = PetFrame.LOSE.value
                else:
                    frame_id = PetFrame.IDLE1.value if anim_toggle == 0 else PetFrame.HAPPY.value

                # Use cached scaled sprite
                if pet in self.result_pet_sprites_cache and frame_id in self.result_pet_sprites_cache[pet]:
                    sprite = self.result_pet_sprites_cache[pet][frame_id]
                else:
                    # Fallback if cache miss (shouldn't happen)
                    sprite = pet.get_sprite(frame_id)
                    sprite = pygame.transform.scale(sprite, (self.result_sprite_width, self.result_sprite_height))

                blit_with_cache(surface, sprite, (pet_x, self.result_pets_y))

            # Tick the devolution flash (once per drawn frame)
            if getattr(self, 'xros_devolve_timer', 0) > 0:
                self.xros_devolve_timer -= 1

    def draw_hit_animations(self, surface):
        """
        Draws the hit animations at the impact points of attacks.
        """
        for frame_index, (x, y) in self.hit_animations:
            if 0 <= frame_index < len(self.hit_animation_frames):
                sprite = self.hit_animation_frames[frame_index]
                blit_with_cache(surface, sprite, (x - sprite.get_width() // 2, y - 32))

    def _compute_combatant_attack_anim(self, combatant, index, side, attack_entry=None):
        """Resolve a combatant's attack-prep state from its cooldown.

        Each pet/enemy ticks its own cooldown (game_battle.cooldowns[i]) so all
        combatants animate independently. Cooldown counts down to 0; the shot
        fires at 0. The shared timeline in
        ``combat_constants.compute_attack_anim_state`` runs in the LAST
        ATTACK_PREP_BASE_FRAMES ticks of the cooldown — anything before that
        is treated as idle by the helper.

        ``attack_entry`` is the simulator log entry for this combatant's
        current turn. When provided, its ``critical`` flag drives the slide-in
        directly — this avoids the one-turn lag that would otherwise occur if
        we relied on ``special_attack[i]``, which is only set when the shot
        fires (``setup_pet_attack``/``setup_enemy_attack``).

        Args:
            combatant: the pet/enemy object (used to query SPECIAL frame).
            index: index into the per-pet cooldown / special-attack arrays.
            side: "team1" (right side, slide from right edge) or "team2"
                  (left side, slide from left edge).
            attack_entry: the AttackLog for this turn (or None to fall back to
                  the cached ``special_attack[i]`` flag).

        Returns:
            (frame_id, dx, dy, slide_x_or_None).
        """
        fps_scale = constants.FRAME_RATE / 30.0
        cooldowns = self.battle_player.cooldowns
        cooldown = cooldowns[index] if index < len(cooldowns) else 0
        elapsed_30fps = combat_constants.ATTACK_PREP_BASE_FRAMES - (cooldown / fps_scale)

        if attack_entry is not None:
            entry_crit = bool(getattr(attack_entry, "critical", False))
            is_crit = (entry_crit
                       and self.module.enable_special_attack_sprite
                       and self._has_special_frame(combatant))
        else:
            crit_arr = (self.battle_player.special_attack if side == "team1"
                        else self.battle_player.special_attack_enemy)
            is_crit = crit_arr[index] if index < len(crit_arr) else False

        special_sprite = combatant.get_sprite(PetFrame.SPECIAL.value)
        has_special = special_sprite is not None

        frame, fwd, jmp, slide_progress = combat_constants.compute_attack_anim_state(
            elapsed_30fps, is_crit, has_special
        )

        ui_scale = runtime_globals.UI_SCALE
        pet_w = runtime_globals.PET_WIDTH
        dy = -int(jmp * ui_scale)

        if side == "team1":
            dx = int(fwd * ui_scale)
            slide_x = None
            if slide_progress is not None:
                special_w = pet_w * 2
                base_x = self.get_team1_x(index)
                target_x = float(base_x - pet_w)
                start_x = float(runtime_globals.SCREEN_WIDTH)
                slide_x = int(start_x + (target_x - start_x) * slide_progress)
        else:
            dx = -int(fwd * ui_scale)
            slide_x = None
            if slide_progress is not None:
                special_w = pet_w * 2
                base_x = self.get_team2_x(index) - self.enemy_entry_counter
                target_x = float(base_x + int(2 * ui_scale))
                start_x = float(-special_w)
                slide_x = int(start_x + (target_x - start_x) * slide_progress)

        return frame.value, dx, dy, slide_x

    def _sized_pet_sprite(self, sprite):
        """Return the sprite at PET size.

        Pet frames are pre-scaled to (PET_WIDTH, PET_HEIGHT) at load time, so
        this is normally a no-op; only odd-sized fallbacks pay for a rescale.
        """
        size = (runtime_globals.PET_WIDTH, runtime_globals.PET_HEIGHT)
        if sprite.get_size() != size:
            sprite = pygame.transform.scale(sprite, size)
        return sprite

    def _get_flipped_enemy_sprite(self, enemy, frame_id):
        """Enemy frames face right but battle shows them mirrored.

        Flip once per (enemy, frame) instead of allocating a new flipped
        surface every drawn frame. Keyed by id() because GameEnemy is a
        dataclass (auto __eq__ makes it unhashable); the cache is reset
        whenever the enemy roster changes, so ids stay valid.
        """
        key = (id(enemy), frame_id)
        cached = self._enemy_flip_cache.get(key)
        if cached is not None:
            return cached
        sprite = enemy.get_sprite(frame_id)
        if sprite is None:
            return None
        flipped = pygame.transform.flip(sprite, True, False)
        self._enemy_flip_cache[key] = flipped
        return flipped

    def _get_special_slide_sprite(self, entity, flip):
        """2x-wide SPECIAL frame used by the crit slide-in.

        Scaled (and mirrored for enemies) once per entity instead of on every
        frame of the slide. id()-keyed for the same reason as the flip cache
        (dataclass enemies are unhashable).
        """
        key = (id(entity), flip)
        cached = self._special_slide_cache.get(key)
        if cached is not None:
            return cached
        special = entity.get_sprite(PetFrame.SPECIAL.value)
        if special is None:
            return None
        scaled = pygame.transform.scale(
            special, (runtime_globals.PET_WIDTH * 2, runtime_globals.PET_HEIGHT))
        if flip:
            scaled = pygame.transform.flip(scaled, True, False)
        self._special_slide_cache[key] = scaled
        return scaled

    def _get_draw_attack_entry(self, device_label, index):
        """Attack-log entry for this combatant's current turn.

        Cached per (device, index, turn) so the draw loop doesn't rescan the
        turn log every frame; a turn advance simply produces a new key.
        """
        turn = self.battle_player.turns[index]
        if turn > self.turn_limit:
            return None
        log = getattr(self, 'global_battle_log', None)
        if not log or len(log.battle_log) < turn:
            return None
        key = (device_label, index, turn)
        if key in self._attack_entry_cache:
            return self._attack_entry_cache[key]
        turn_log = log.battle_log[turn - 1]
        entry = next(
            (a for a in turn_log.attacks
             if a.device == device_label and a.attacker == index),
            None
        )
        self._attack_entry_cache[key] = entry
        return entry

    def draw_enemies(self, surface: pygame.Surface):
        """
        Draws the enemy sprites on the screen, with animations based on the battle phase.
        """
        total = len(self.battle_player.team2)

        for i, enemy in enumerate(self.battle_player.team2):
            y = self.get_y(i, total)
            x = self.get_team2_x(i) - self.enemy_entry_counter
            anim_toggle = (self.battle_player.frame_counters[i] + i * 5) // (15 * constants.FRAME_RATE / 30) % 2

            attack_entry = None
            if self.phase == "battle":
                attack_entry = self._get_draw_attack_entry("device2", i)

            in_attack_prep = (attack_entry
                              and self.battle_player.phase[i] == "enemy_charge"
                              and self.battle_player.team2_hp[i] > 0)

            if self.phase in ["intimidate", "entry"]:
                frame_id = PetFrame.IDLE1.value if anim_toggle == 0 else PetFrame.ANGRY.value
            elif self.phase in ["alert", "charge"]:
                frame_id = PetFrame.IDLE1.value if anim_toggle == 0 else PetFrame.IDLE2.value
            elif self.battle_player.team2_hp[i] <= 0:
                frame_id = PetFrame.LOSE.value
            elif attack_entry and self.battle_player.phase[i] == "enemy_attack":
                frame_id = PetFrame.ATK1.value
            elif in_attack_prep:
                # Drive the pre-shot pose through the shared timeline so each
                # enemy animates independently from its own cooldown. Pass the
                # current turn's attack_entry so the slide-in fires on the same
                # turn the simulator marked critical (otherwise special_attack
                # only flips on shot-fire and the slide lags by one round).
                frame_id, dx, dy, slide_x = self._compute_combatant_attack_anim(
                    enemy, i, "team2", attack_entry=attack_entry
                )
                if slide_x is not None:
                    special_sprite_scaled = self._get_special_slide_sprite(enemy, flip=True)
                    if special_sprite_scaled is not None:
                        blit_with_cache(surface, special_sprite_scaled, (slide_x, y))
                        continue
                x += dx
                y += dy
            elif self.battle_player.phase[i] == "result":
                if self._lost_pair(i, "team2"):
                    frame_id = PetFrame.LOSE.value
                else:
                    frame_id = PetFrame.IDLE1.value if anim_toggle == 0 else PetFrame.HAPPY.value
            else:
                frame_id = PetFrame.IDLE1.value if anim_toggle == 0 else PetFrame.IDLE2.value

            sprite = self._get_flipped_enemy_sprite(enemy, frame_id)

            if sprite:
                blit_with_cache(surface, sprite, (x + (2 * runtime_globals.UI_SCALE), y))

    def draw_pets(self, surface: pygame.Surface):
        """
        Draws the player pets on the screen, with animations based on the battle phase.
        In the result phase, pets are drawn horizontally and centered vertically.
        """
        total = len(self.battle_player.team1)

        if self.phase == "result":
            # Horizontal layout
            spacing = min((runtime_globals.SCREEN_WIDTH - int(30 * runtime_globals.UI_SCALE)) // total, int(runtime_globals.PET_WIDTH * runtime_globals.UI_SCALE) + int(16 * runtime_globals.UI_SCALE))
            total_width = spacing * total
            offset_x = (runtime_globals.SCREEN_WIDTH - total_width) // 2
            y = (runtime_globals.SCREEN_HEIGHT - runtime_globals.PET_HEIGHT) // 2
            for i, pet in enumerate(self.battle_player.team1):
                x = self.get_team1_x(i)
                anim_toggle = (self.battle_player.frame_counters[i] + i * 5) // (15 * constants.FRAME_RATE / 30) % 2
                if self.victory_status == "Defeat":
                    frame_id = PetFrame.LOSE.value
                else:
                    frame_id = PetFrame.IDLE1.value if anim_toggle == 0 else PetFrame.HAPPY.value
                sprite = self._sized_pet_sprite(pet.get_sprite(frame_id))
                x = offset_x + i * spacing
                blit_with_cache(surface, sprite, (x, y))
        else:
            # Original vertical layout
            for i, pet in enumerate(self.battle_player.team1):
                anim_toggle = (self.battle_player.frame_counters[i] + i * 5) // (15 * constants.FRAME_RATE / 30) % 2
                x = self.get_team1_x(i)
                attack_entry = None
                if self.phase == "battle":
                    attack_entry = self._get_draw_attack_entry("device1", i)

                in_attack_prep = (attack_entry
                                  and self.battle_player.phase[i] == "pet_charge"
                                  and self.battle_player.team1_hp[i] > 0)
                y = self.get_y(i, total)

                if self.phase in ["alert", "charge"]:
                    frame_id = PetFrame.IDLE1.value if anim_toggle == 0 else PetFrame.ANGRY.value
                elif self.phase in ["intimidate", "entry"]:
                    frame_id = PetFrame.IDLE1.value if anim_toggle == 0 else PetFrame.IDLE2.value
                elif self.battle_player.team1_hp[i] <= 0:
                    frame_id = PetFrame.LOSE.value
                elif attack_entry and self.battle_player.phase[i] == "pet_attack":
                    frame_id = PetFrame.ATK1.value
                elif in_attack_prep:
                    # Shared timeline drives the pre-shot pose; cooldown ticks
                    # independently per pet so multiple combatants stay decoupled.
                    # Pass attack_entry so the slide-in fires on the same turn
                    # the simulator marked critical (special_attack only flips
                    # on shot-fire and would otherwise lag by one round).
                    frame_id, dx, dy, slide_x = self._compute_combatant_attack_anim(
                        pet, i, "team1", attack_entry=attack_entry
                    )
                    if slide_x is not None:
                        special_sprite_scaled = self._get_special_slide_sprite(pet, flip=False)
                        if special_sprite_scaled is not None:
                            blit_with_cache(surface, special_sprite_scaled, (slide_x, y))
                            continue
                    x += dx
                    y += dy
                elif self.battle_player.phase[i] == "result":
                    if self._lost_pair(i, "team1"):
                        frame_id = PetFrame.LOSE.value
                    else:
                        frame_id = PetFrame.IDLE1.value if anim_toggle == 0 else PetFrame.HAPPY.value
                else:
                    frame_id = PetFrame.IDLE1.value if anim_toggle == 0 else PetFrame.IDLE2.value

                sprite = self._sized_pet_sprite(pet.get_sprite(frame_id))
                blit_with_cache(surface, sprite, (x, y))

    def draw_projectiles(self, surface):
        """
        Draws the projectiles fired by the player's pets during their attack.
        """
        for data in self.battle_player.team1_projectiles:
            for sprite, pos, target, dt in data:
                blit_with_cache(surface, sprite, (pos[0], pos[1]))

    def draw_enemy_projectiles(self, surface):
        """
        Draws the projectiles fired by the enemies during their attack.
        """
        for data in self.battle_player.team2_projectiles:
            for sprite, pos, target, dt in data:
                blit_with_cache(surface, sprite, (pos[0], pos[1]))

    def draw_strength_bar(self, surface):
        """
        Draws the strength training bar for the DMC ruleset.
        """
        bar_x = (runtime_globals.SCREEN_WIDTH // 2) - (self.bar_back.get_width() // 2)
        bar_bottom_y = runtime_globals.SCREEN_HEIGHT - int(2 * runtime_globals.UI_SCALE)

        if self.strength == 14:
            surface.blit(self.training_max, (bar_x - int(18 * runtime_globals.UI_SCALE), bar_bottom_y - int(209 * runtime_globals.UI_SCALE)))

        blit_with_cache(surface, self.bar_back, (bar_x - int(3 * runtime_globals.UI_SCALE), bar_bottom_y - int(169 * runtime_globals.UI_SCALE)))

        for i in range(self.strength):
            y = bar_bottom_y - (i + 1) * self.bar_piece.get_height()
            surface.blit(self.bar_piece, (bar_x, y))

    def draw_health_bars(self, surface):
        """
        Draws the health bars for the player and enemy, showing current and max health.
        """
        self.hp_bar.draw(surface)

    def draw_health_bars_for_battlers(self, surface):
        """
        Draws individual health bars under each pet and enemy using the new team structure.
        """
        bar_height = int(8 * runtime_globals.UI_SCALE)
        bar_offset_y = runtime_globals.PET_HEIGHT - int(6 * runtime_globals.UI_SCALE)
        green = (0, 255, 108)
        red = (181, 41, 41)
        x_color = (255, 0, 0)
        x_thickness = max(2, int(2 * runtime_globals.UI_SCALE))

        # Draw pet health bars
        total_pets = len(self.battle_player.team1)
        for i, pet in enumerate(self.battle_player.team1):
            pet_x = self.get_team1_x(i)
            pet_y = self.get_y(i, total_pets) + bar_offset_y
            current_hp = self.battle_player.team1_hp[i]
            max_hp = self.battle_player.team1_max_hp[i]
            if current_hp > 0:
                if self.battle_player.team1_bar_counters[i] > 0:
                    pet_hp_ratio = current_hp / max_hp if max_hp else 0
                    pet_bar_width = int(runtime_globals.PET_WIDTH * pet_hp_ratio)
                    pygame.draw.rect(surface, red, (pet_x, pet_y, runtime_globals.PET_WIDTH, bar_height))
                    pygame.draw.rect(surface, green, (pet_x, pet_y, pet_bar_width, bar_height))
            else:
                pet_y = self.get_y(i, total_pets)
                if self._ko_sprite:
                    ko_x = pet_x + (runtime_globals.PET_WIDTH - self._ko_sprite.get_width()) // 2
                    ko_y = pet_y + (runtime_globals.PET_HEIGHT - self._ko_sprite.get_height()) // 2
                    surface.blit(self._ko_sprite, (ko_x, ko_y))
                else:
                    start1 = (pet_x, pet_y)
                    end1 = (pet_x + runtime_globals.PET_WIDTH, pet_y + runtime_globals.PET_HEIGHT)
                    start2 = (pet_x + runtime_globals.PET_WIDTH, pet_y)
                    end2 = (pet_x, pet_y + runtime_globals.PET_HEIGHT)
                    pygame.draw.line(surface, x_color, start1, end1, x_thickness)
                    pygame.draw.line(surface, x_color, start2, end2, x_thickness)

        # Draw enemy health bars
        total_enemies = len(self.battle_player.team2)
        if self.boss:
            bar_offset_y = runtime_globals.PET_HEIGHT_BOSS - int(6 * runtime_globals.UI_SCALE)
        for i, enemy in enumerate(self.battle_player.team2):
            enemy_x = self.get_team2_x(i)
            enemy_y = self.get_y(i, total_enemies) + bar_offset_y
            current_hp = self.battle_player.team2_hp[i]
            max_hp = self.battle_player.team2_max_hp[i]
            width = runtime_globals.PET_WIDTH_BOSS if self.boss else runtime_globals.PET_WIDTH
            height = runtime_globals.PET_HEIGHT_BOSS if self.boss else runtime_globals.PET_HEIGHT
            if current_hp > 0:
                if self.battle_player.team2_bar_counters[i] > 0:
                    enemy_hp_ratio = current_hp / max_hp if max_hp else 0
                    enemy_bar_width = int(width * enemy_hp_ratio)
                    pygame.draw.rect(surface, red, (enemy_x, enemy_y, width, bar_height))
                    pygame.draw.rect(surface, green, (enemy_x, enemy_y, enemy_bar_width, bar_height))
            else:
                enemy_y = self.get_y(i, total_enemies)
                ko = self._ko_sprite_boss if self.boss else self._ko_sprite
                if ko:
                    ko_x = enemy_x + (width - ko.get_width()) // 2
                    ko_y = enemy_y + (height - ko.get_height()) // 2
                    surface.blit(ko, (ko_x, ko_y))
                else:
                    start1 = (enemy_x, enemy_y)
                    end1 = (enemy_x + width, enemy_y + height)
                    start2 = (enemy_x + width, enemy_y)
                    end2 = (enemy_x, enemy_y + height)
                    pygame.draw.line(surface, x_color, start1, end1, x_thickness)
                    pygame.draw.line(surface, x_color, start2, end2, x_thickness)

    def get_y(self, index, total):
        """
        Calculates the vertical position for drawing based on index and total number of sprites.
        Centers sprites dynamically and spreads them evenly, accounting for sprite height.
        """
        margin_top = int(40 * runtime_globals.UI_SCALE)
        margin_bottom = int(10 * runtime_globals.UI_SCALE)
        available_height = runtime_globals.SCREEN_HEIGHT - margin_top - margin_bottom

        sprite_height = runtime_globals.PET_HEIGHT

        if total == 1:
            # Center single sprite vertically
            return (runtime_globals.SCREEN_HEIGHT - sprite_height) // 2
        else:
            # Spread sprites evenly, center each sprite in its slot
            slot_height = available_height / total
            return int(margin_top + slot_height * index + (slot_height - sprite_height) / 2)

    def get_team1_x(self, index):
        """
        Returns the x position for the player's team based on index.
        """
        return runtime_globals.SCREEN_WIDTH - runtime_globals.PET_WIDTH - (4 * runtime_globals.UI_SCALE)
    
    def get_team2_x(self, index):
        """
        Returns the x position for the enemy team based on index.
        If it's a boss, it returns the enemy's x position.
        """
        return (3 * runtime_globals.UI_SCALE)
    #========================
    # Region: Event Handling
    #========================

    def handle_event(self, event):
        """
        Handles input events for the battle encounter, phase and battle_minigame specific.
        """
        if not isinstance(event, tuple) or len(event) != 2:
            return
        
        event_type, event_data = event
        minigame = getattr(self.module, 'battle_minigame', 'Dummy Bar')

        # Temporary-evolution phases get first crack at the input.
        if self.phase == "xros_select":
            if event_type == "B":
                # No cancel option on the selector; B still quits the battle
                # (nothing was applied yet, so no revert needed).
                runtime_globals.game_sound.play("cancel")
                change_scene("game")
                return
            if getattr(self, 'xros_selector', None):
                if self.xros_selector.handle_event(event) == "confirm":
                    self._on_xros_confirm()
            return
        if self.phase == "xros_anim":
            # Block input while the transformation animation plays.
            return

        # READY/alert is intentionally non-skippable. This early lock also
        # prevents B from falling through to the general quit-battle branch.
        if self.phase == "alert":
            return

        # Skip animation-only phases on B or LCLICK. A is reserved for the
        # charge minigames (dummy charge mashes A) — with A doubling as skip,
        # leftover presses from the minigame skipped the whole battle.
        if event_type in ("B", "LCLICK") and self.phase in ("level", "entry", "intimidate", "battle"):
            # Mouse/touch grace: the dummy charge is click-driven, so ignore
            # clicks that land right after the minigame ends — otherwise the
            # last mash would instantly skip the battle animation.
            if (event_type == "LCLICK" and self.phase == "battle"
                    and pygame.time.get_ticks() < getattr(self, '_skip_grace_until', 0)):
                return
            if self.phase == "level":
                self.phase = "entry"
                self.frame_counter = 0
                runtime_globals.game_sound.play("battle")
            elif self.phase == "entry":
                self.enemy_entry_counter = 0
                self.phase = "intimidate"
                self.frame_counter = 0
                self.battle_player.reset_frame_counters()
                duration = 3.0
                if self.boss:
                    self.animated_sprite.play_warning(duration)
                else:
                    self.animated_sprite.play_battle(duration)
            elif self.phase == "intimidate":
                # Skipping the intimidate animation still goes through the
                # temporary-evolution selection when a pet qualifies.
                self.animated_sprite.stop()
                if not self._start_xros_selection():
                    self._enter_alert_phase()
            elif self.phase == "battle":
                runtime_globals.game_sound.play("cancel")
                self.phase = "result"
                self.frame_counter = 0
        elif event_type == "B":
            if self.phase in ("feeding", "retire_check", "retire_animation"):
                # Handled by the view / blocked during the retire animation
                return
            # Quitting mid-battle (charge, result): the temporary evolution
            # ends with the battle.
            self._clear_xros_forms()
            runtime_globals.game_sound.play("cancel")
            change_scene("game")
        elif self.phase in ("feeding", "retire_check"):
            # Events for these phases are handled by the view
            return
        elif self.phase == "retire_animation":
            # Block all input during retire animation
            return
        elif self.phase == "charge":
            # Handle charge phase input based on minigame type
            if minigame == "Dummy Bar":
                if event_type in ("A", "LCLICK"):
                    if self.dummy_charge and self.dummy_charge.handle_event(event):
                        self.strength = self.dummy_charge.strength
            elif minigame == "Count Match Color":
                if event_type in ("Y", "SHAKE"):
                    if self.count_match and self.count_match.handle_event(event):
                        self.press_counter = self.count_match.get_press_counter()
                        self.rotation_index = self.count_match.get_rotation_index()
            elif minigame == "Count Match Classic":
                if event_type in ("Y", "SHAKE"):
                    if self.count_match_classic and self.count_match_classic.handle_event(event):
                        self.strength = self.count_match_classic.strength
            elif minigame == "Count Match Z":
                if event_type in ("Y", "SHAKE"):
                    if self.count_match_z and self.count_match_z.handle_event(event):
                        self.press_counter = self.count_match_z.get_press_counter()
            elif minigame in ["Punch", "Mogera"]:
                if event_type in ("Y", "SHAKE"):
                    if self.shake_punch and self.shake_punch.handle_event(event):
                        self.strength = self.shake_punch.get_strength()
            elif minigame in ["Xai Roll+Bar", "Xai Bar"]:
                if self.xai_phase == 1 and event_type in ["A", "LCLICK"] and self.xai_roll and not self.xai_roll.stopping:
                    # --- Seven Switch: force XAI roll to 7 if status_boost is active ---
                    xai_effect = self.get_battle_effect("xai_roll")
                    if xai_effect and xai_effect.get("amount", 0) == 7:
                        self.xai_roll.stop()
                        self.xai_roll.stop_target_frame = 6
                        self.xai_number = 7
                    else:
                        if self.xai_roll.rolling:
                            self.xai_roll.stop()
                            self.xai_number = self.xai_roll.get_result()
                        else:
                            # Roll already finished — transition to bar is imminent.
                            # Buffer the press so the bar stops on its very first frame,
                            # before the arrow has moved at all.
                            self._xai_pending_stop = True
                elif self.xai_phase == 2 and event_type in ["A", "LCLICK"] and self.xai_bar:
                    self._do_xai_bar_stop()

    #========================
    # Region: Utility Methods
    #========================

    def return_to_main_scene(self):
        """
        Ends the battle and returns to the main game scene.
        """
        # Safety net: no temporary evolution outlives the battle (normally
        # already ended by the result screen's devolution flash).
        self._clear_xros_forms()

        runtime_globals.game_console.log(f"[Scene_Battle] exiting to main game")
        distribute_pets_evenly()
        change_scene("game")

    def calculate_combat_for_pairs(self):
        self.simulate_global_combat()

        self.process_battle_results()

    def raw_charge(self):
        """The charge as its own minigame counts it, not as a 0-3 band.

        Three minigames measure three different things and two lines read the
        raw number rather than the band: PENOG takes Count Match Classic's
        0-40 shake meter, and PENC takes Count Match Color's **super hits**,
        which are its attack pattern outright ("N super hits for 2 damage
        each"). `self.strength` is the meter, and on a Count Match Color
        module it is never set at all -- so passing it sent every Pendulum
        Color battle out at charge 0 whatever the player rolled.

        The band is still what `get_minigame_strength` returns and what the
        packets carry; this is only for the tables keyed on the raw score.
        """
        minigame = getattr(self.module, 'battle_minigame', 'Dummy Bar')
        if minigame == "Count Match Color":
            return self.super_hits
        if minigame == "Count Match Z":
            return self.press_counter
        return self.strength

    def get_minigame_strength(self):
        """The 0-3 charge quality the battle packets carry.

        The bands live in ``minigame_session.minigame_result`` so the DCom
        connection flow, which plays its charge before any battle exists,
        scores identically.
        """
        from ui.minigames.minigame_session import minigame_result
        return minigame_result(
            getattr(self.module, 'battle_minigame', 'Dummy Bar'),
            self.strength, self.super_hits,
            self.press_counter, getattr(self.count_match_z, "pet", None),
            getattr(self, "color_band", None))

    def simulate_global_combat(self):
        # Use the BattlePlayer's teams for simulation
        team1 = []
        team2 = []
        
        # Prepare team1 (player's Digimon)
        for i, pet in enumerate(self.battle_player.team1):
            team1.append(Digimon(
                name=pet.name,
                order=i,
                traited=1 if pet.traited else 0,
                egg_shake=1 if pet.shook else 0,
                index=i,
                hp=self.battle_player.team1_hp[i],
                attribute=pet.attribute,
                power=pet.get_power(self.power_bonus),
                handicap=0,
                buff=self.attack_boost + (getattr(pet, 'bonus_stats', None) or [0, 0, 0])[1],
                mini_game=self.get_minigame_strength(),
                level=pet.level,
                stage=pet.stage,
                sick=1 if pet.sick > 0 else 0,
                shot1=pet.atk_main,
                shot2=pet.atk_alt,
                tag_meter=0
            ))
            # The Colour line's adventure table is keyed on effort hearts,
            # and `Digimon` has no field for it -- the wire never carried
            # one, so nothing needed it until that table existed.
            team1[-1].effort = getattr(pet, "effort", 0)

        # Prepare team2 (enemy Digimon)
        for i, enemy in enumerate(self.battle_player.team2):
            enemy_stage_index = max(1, enemy.stage - 1)
            enemy_level = constants.MAX_LEVEL.get(enemy_stage_index, 1)
            
            # Get enemy power - handle PvP pets with custom power values
            if hasattr(enemy, '_pvp_power'):
                enemy_power = enemy._pvp_power
            elif hasattr(enemy, 'get_power') and callable(enemy.get_power):
                enemy_power = enemy.get_power()
            else:
                enemy_power = getattr(enemy, 'power', 1)
            
            team2.append(Digimon(
                name=enemy.name,
                order=i,
                traited=getattr(enemy, 'traited', 0),
                egg_shake=getattr(enemy, 'shook', 0),
                index=i,
                hp=self.battle_player.team2_hp[i],
                attribute=enemy.attribute,
                power=enemy_power,
                handicap=getattr(enemy, "handicap", 0),
                buff=(getattr(enemy, 'bonus_stats', None) or [0, 0, 0])[1],
                mini_game=1,
                level=getattr(enemy, 'level', enemy_level),
                stage=enemy.stage,
                sick=1 if getattr(enemy, 'sick', 0) > 0 else 0,
                shot1=enemy.atk_main,
                shot2=enemy.atk_alt,
                tag_meter=0
            ))

        # Simulate the battle using the GlobalBattleSimulator
        sim = GlobalBattleSimulator(
            pvp_mode=self.pvp_mode,
            max_hit_rate=getattr(self.module, 'battle_max_hit_rate', 100),
            attribute_advantage=self.module.battle_attribute_advantage,
            damage_limit=self.module.battle_damage_limit,
            advantage_as_power=getattr(
                self.module, "battle_attribute_advantage_power", False),
            # Which attack table an adventure battle draws from: the module
            # says which device it reproduces, and the two original lines
            # have their own.
            battle_format=getattr(self.module, "battle_protocol", None),
            # The raw score, for a table that reads the number rather than a
            # band. `mini_game` on each Digimon stays the 0-3 quality.
            charge=self.raw_charge()
        )
        result = sim.simulate(team1, team2)

        # Store the result for animation/processing
        self.global_battle_log = result
        # A fresh log invalidates the per-turn entries cached by the draw loop.
        self._attack_entry_cache = {}
        self.victory_status = "Victory" if result.winner == "device1" else "Defeat"
        
        # Update quest progress if battle was won (skip for PvP)

        if not self.pvp_mode and self.victory_status == "Victory":
            if self.boss:
                # Update BOSS quest progress
                update_quest_progress(QuestType.BOSS, 1, self.module.name)
            # Update BATTLE quest progress
            update_quest_progress(QuestType.BATTLE, 1, self.module.name)

        # Process battle results for animations and rewards
        #Remove because it is called by calling function calculate_combat_for_pairs() directly,
        #otherwise it is called twice, and DP and battles are updated twice, not once.
        #self.process_battle_results()

    def draw_debug_battle_logs(self, surface):
        """
        Draws debug battle log information between enemies and pets when DEBUG_MODE flag is enabled.
        Shows turn number, hit results, and attack direction arrows.
        """
        if not constants.DEBUG_MODE or not hasattr(self, 'debug_battle_logs'):
            return
            
        font_small = get_font(runtime_globals.FONT_SIZE_SMALL)
        
        for i, log_entry in enumerate(self.debug_battle_logs):
            if i >= len(self.battle_player.team1):
                continue
                
            # Calculate position between enemy and pet
            pet_y = self.get_y(i, len(self.battle_player.team1))
            pet_x = self.get_team1_x(i)
            
            if i < len(self.battle_player.team2):
                enemy_x = self.get_team2_x(i) + (runtime_globals.PET_WIDTH_BOSS if self.boss else runtime_globals.PET_WIDTH)
            else:
                # For cases where there are fewer enemies than pets (boss battle)
                enemy_x = self.get_team2_x(0) + (runtime_globals.PET_WIDTH_BOSS if self.boss else runtime_globals.PET_WIDTH)
            
            # Position debug log in the middle between enemy and pet
            log_x = (enemy_x + pet_x) // 2
            log_y = pet_y + runtime_globals.PET_HEIGHT // 2
            
            # Draw turn information
            turn_text = f"Turn {log_entry['turn']}"
            arrow = log_entry['arrow']
            hit_text = log_entry['hit']
            
            # Combine arrow and turn text
            if arrow == ">":
                display_text = f"{turn_text} >"
            elif arrow == "<":
                display_text = f"< {turn_text}"
            else:
                display_text = turn_text
                
            # Draw turn text
            turn_surface = font_small.render(display_text, True, constants.FONT_COLOR_DEFAULT)
            text_rect = turn_surface.get_rect(center=(log_x, log_y - int(10 * runtime_globals.UI_SCALE)))
            surface.blit(turn_surface, text_rect)
            
            # Draw hit result if available
            if hit_text:
                hit_color = self.get_hit_text_color(hit_text)
                hit_surface = font_small.render(hit_text, True, hit_color)
                hit_rect = hit_surface.get_rect(center=(log_x, log_y + int(10 * runtime_globals.UI_SCALE)))
                surface.blit(hit_surface, hit_rect)
