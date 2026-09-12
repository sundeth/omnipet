import json
import os
from typing import List, Optional

import pygame
from utils.asset_utils import image_load, open_json, resolve_path
from utils.data_compat import availability as read_availability, get_data

from core import runtime_globals
import core.constants as constants
from models.game_enemy import GameEnemy
import copy

from models.game_item import GameItem
from battle.sim import protocol_constants
from models.quest_event_data import QuestData, EventData


#=====================================================================
# GameModule - Manages module data (monsters and metadata)
#=====================================================================

def _training_table(value, won, lost, scaled=None):
    """A four-slot training payout, indexed by outcome level 0-3.

    A list is taken as written. Anything else is a module from before the
    tables existed, and is rebuilt from the win/lose pair it used to carry:
    level 0 is the failed attempt and pays ``lost``, and the three winning
    levels pay ``won``, multiplied by the level when the old
    ``training_strengh_multiplier`` was in play - which is what
    ``gain * grade * multiplier`` used to compute.
    """
    if isinstance(value, list) and value:
        table = [int(v) for v in value][:4]
        return table + [table[-1]] * (4 - len(table))
    won, lost = int(won or 0), int(lost or 0)
    if scaled:
        return [lost, won, won * 2, won * 3]
    return [lost, won, won, won]


# What a module written before traited_egg_rule / power_bonus_rule existed
# should fall back to, as ``ruleset -> (traited egg rule, power bonus rule)``.
# Chosen to reproduce what that ruleset already did, so an old module behaves
# the same way after the migration.
LEGACY_RULESET_RULES = {
    "dm":  ("Stage V Chance", "Stage Table"),
    "pen": ("Win Ratio (Stage 5)", "Stage Table + Shaken"),
    "dmx": ("Evolution Timer (Area 45)", "Strength and Level"),
    "vb":  ("None", "Star"),
}


class GameModule:
    """
    Represents a game module, capable of loading metadata and monsters from its folder.
    """

    def __init__(self, folder_path: str) -> None:
        self.folder_path = folder_path
        self.name = "default"
        self.name_format = ""
        self.ruleset = ""
        self.unlocks = {"eggs": [], "backgrounds": [], "evolutions": []}
        self.backgrounds = []
        self.devices = []
        self.visible_stats = []
        self.load_module_data()
        self.load_devices()
        self.load_sprites()
        self.load_items()
        self.load_passwords()

    def load_module_data(self) -> None:
        json_path = os.path.join(self.folder_path, "module.json")
        resolved_path = resolve_path(json_path)
        if os.path.exists(resolved_path):
            try:
                with open_json(json_path) as file:
                    data = json.load(file)
                    self.name = data.get("name", "default")
                    self.name_format = data.get("name_format", "$_dmc")
                    # Ruleset (legacy names normalized: dmc -> dm, penc -> pen)
                    # Superseded by traited_egg_rule and power_bonus_rule; it
                    # is still read so a module written before those existed
                    # keeps working.
                    _ruleset_fixes = {"dmc": "dm", "penc": "pen"}
                    _ruleset = data.get("ruleset", "dm")
                    self.ruleset = _ruleset_fixes.get(_ruleset, _ruleset)
                    _legacy = LEGACY_RULESET_RULES.get(self.ruleset,
                                                       LEGACY_RULESET_RULES["dm"])
                    # How a Traited Egg is earned, and where a pet's power
                    # bonus comes from. See the two tables in game_pet.
                    self.traited_egg_rule = data.get("traited_egg_rule") or _legacy[0]
                    self.power_bonus_rule = data.get("power_bonus_rule") or _legacy[1]
                    # Stat both pets must have at max to jogress; consumed
                    # (set to 0) on the evolved pets after the fusion.
                    # "Nothing", "DP", "Effort", "Strength" or "Hunger".
                    self.jogress_cost = data.get("jogress_cost", "DP")
                    self.author = data.get("author", "Unknown")
                    self.version = data.get("version", "1.0")
                    self.category = data.get("category", "Custom")
                    self.description = data.get("description", "No description available.")

                    self.adventure_mode = data.get("adventure_mode", False)
                    self.battle_protocol = data.get("battle_protocol", "")
                    self.adventure_style = data.get("adventure_style", "Area Selection")

                    self.meat_weight_gain = int(data.get("care_meat_weight_gain"))
                    self.meat_hunger_gain = float(data.get("care_meat_hunger_gain"))
                    self.meat_care_mistake_time = int(data.get("care_meat_care_mistake_time"))
                    self.overfeed_timer = int(data.get("care_overfeed_timer"))
                    self.use_condition_hearts = bool(data.get("care_condition_heart", False))
                    self.can_eat_sleeping = bool(data.get("care_can_eat_sleeping", True))
                    
                    self.back_to_sleep_time = int(data.get("care_back_to_sleep_time", 10))
                    self.enable_shaken_egg = bool(data.get("care_enable_shaken_egg", False))

                    self.protein_weight_gain = int(data.get("care_protein_weight_gain"))
                    self.protein_strengh_gain = float(data.get("care_protein_strengh_gain"))
                    self.protein_dp_gain = int(data.get("care_protein_dp_gain"))
                    self.protein_care_mistake_time = int(data.get("care_protein_care_mistake_time"))
                    self.protein_overdose_max = int(data.get("care_protein_overdose_max", 0))
                    self.protein_penalty = int(data.get("care_protein_penalty", 10))
                    self.disturbance_penalty_max = int(data.get("care_disturbance_penalty_max", 0))

                    self.care_flush_disturbance_sleep = bool(data.get("care_flush_disturbance_sleep", True))

                    self.sleep_care_mistake_timer = int(data.get("care_sleep_care_mistake_timer"))

                    # What one training pays out, indexed by its outcome level
                    # 0-3 (Bad, Good, Great, Excellent) - the four levels the
                    # connection protocols carry. A module written before
                    # these existed is read from the old win/lose pair.
                    self.training_effort_gain = _training_table(
                        data.get("training_effort_gain"),
                        won=data.get("training_effort_gain", 1), lost=0)
                    self.training_strength_gain = _training_table(
                        data.get("training_strength_gain"),
                        won=data.get("training_strengh_gain_win", 1),
                        lost=data.get("training_strengh_gain_lose", 0),
                        scaled=data.get("training_strengh_multiplier", 1))
                    self.training_weight_loss = _training_table(
                        data.get("training_weight_loss"),
                        won=data.get("training_weight_win", 1),
                        lost=data.get("training_weight_lose", 1))

                    self.traited_egg_starting_level = int(data.get("traited_egg_starting_level"))

                    self.reverse_atk_frames = bool(data.get("reverse_atk_frames", False))

                    self.battle_base_sick_chance_win = int(data.get("battle_base_sick_chance_win"))
                    self.battle_base_sick_chance_lose = int(data.get("battle_base_sick_chance_lose"))
                    self.battle_attribute_advantage = int(get_data(data, "battle_attribute_advantage", 5))
                    # The X devices add the advantage to Power before working
                    # out the hit rate rather than to the hit rate itself.
                    self.battle_attribute_advantage_power = bool(
                        get_data(data, "battle_attribute_advantage_power", False))
                    self.battle_global_hit_points = int(data.get("battle_global_hit_points", 0))
                    # sequential rounds is a boolean flag in newer module.json files
                    self.battle_sequential_rounds = bool(data.get("battle_sequential_rounds", False))
                    # battle_minigame determines which minigame to use in adventure battles.
                    # Legacy module.json labels are normalized to the current
                    # names ("Count Match" was ambiguous between the classic
                    # and Z variants; parenthesized names were dropped).
                    _minigame_label_fixes = {
                        "Count Match (Color)": "Count Match Color",
                        "Count Match (Z)": "Count Match Z",
                        "Count Match": "Count Match Classic",
                    }
                    _minigame = data.get("battle_minigame", "Dummy Bar")
                    self.battle_minigame = _minigame_label_fixes.get(_minigame, _minigame)

                    # Battle cost configuration
                    # Digimon Twin: Strength drains overnight, and the battle
                    # record survives an evolution where the training count
                    # does not. Both default off so no other module moves.
                    self.care_needs_decay_while_sleeping = bool(
                        data.get("care_needs_decay_while_sleeping", False))
                    self.battle_keep_counts_on_evolution = bool(
                        data.get("battle_keep_counts_on_evolution", False))
                    # Event Communication: the outcome table is a list of
                    # {outcome, item, chance, cross_version} rows.
                    self.event_communication = bool(
                        data.get("event_communication", False))
                    self.event_communication_outcomes = list(
                        data.get("event_communication_outcomes", []))
                    # Panic: a hit can leave the pet unable to counter or
                    # dodge next turn until the player mashes out of it. The
                    # attribute matchup shifts the rate either way. 0 is off,
                    # which is every module but the Twin.
                    self.battle_panic_rate = int(data.get("battle_panic_rate", 0))
                    self.battle_panic_attribute_bonus = int(
                        data.get("battle_panic_attribute_bonus", 0))
                    self.battle_cost_type = data.get("battle_cost_type", "DP")
                    self.battle_cost_amount = float(data.get("battle_cost_amount", 1.0))
                    # Weight (g) shed per battle, on top of the cost resource.
                    # 0 for every device that doesn't do this; the original
                    # Digital Monster loses 4g a fight.
                    self.battle_weight_loss = int(data.get("battle_weight_loss", 0))
                    self.battle_enable_feeding = bool(data.get("battle_enable_feeding", False))

                    # Care settings for fixed hearts and poop
                    self.care_fixed_4_hearts = bool(data.get("care_fixed_4_hearts", True))
                    self.care_poop_alarm = bool(data.get("care_poop_alarm", True))
                    self.care_poop_chance = data.get("care_poop_chance", [80, 0, 0, 20])
                    self.care_poop_sickness_count = int(data.get("care_poop_sickness_count", 4))
                    self.care_poop_sickness_effect = data.get("care_poop_sickness_effect", "Skull")
                    self.care_99g_effect = data.get("care_99g_effect", "Skull")
                    self.care_block_actions_when_sleeping = bool(data.get("care_block_actions_when_sleeping", True))
                    self.care_can_battle_while_sick = bool(data.get("care_can_battle_while_sick", False))
                    self.count_evolution_while_sleeping = bool(data.get("count_evolution_while_sleeping", True))

                    self.death_max_injuries = int(data.get("death_max_injuries"))
                    self.death_sick_timer = int(data.get("death_sick_timer"))
                    self.death_hunger_timer = int(data.get("death_hunger_timer"))
                    self.death_starvation_count = int(data.get("death_starvation_count"))
                    self.death_strength_timer = int(data.get("death_strength_timer"))
                    self.death_stage45_mistake = int(data.get("death_stage45_mistake"))
                    self.death_stage67_mistake = int(data.get("death_stage67_mistake"))
                    self.death_care_mistake = int(data.get("death_care_mistake",999999))
                    self.death_save_by_b_press = int(data.get("death_save_by_b_press",0))
                    self.death_save_by_shake = int(data.get("death_save_by_shake",0))
                    self.death_old_age = int(data.get("death_old_age",0))
                    
                    self.hp_max_item_boost = int(data.get("hp_max_item_boost", 0))
                    self.atk_max_item_boost = int(data.get("atk_max_item_boost", 0))
                    self.power_max_item_boost = int(data.get("power_max_item_boost", 0))

                    self.vital_value_base = int(data.get("vital_value_base", 50))
                    self.vital_value_loss = int(data.get("vital_value_loss", 50))

                    # Reliability is an optional module-driven care stat. A
                    # zero-filled configuration leaves older modules exactly
                    # as they behaved before the stat existed.
                    self.reliability_base = int(data.get("reliability_base", 0) or 0)
                    self.reliability_becoming_full = int(data.get("reliability_becoming_full", 0) or 0)
                    self.reliability_answering_call = int(data.get("reliability_answering_call", 0) or 0)
                    self.reliability_ignoring_call = int(data.get("reliability_ignoring_call", 0) or 0)
                    self.reliability_minigame_success = int(data.get("reliability_minigame_success", 0) or 0)
                    self.reliability_two_poops = int(data.get("reliability_two_poops", 0) or 0)
                    self.reliability_sickness_or_injury = int(data.get("reliability_sickness_or_injury", 0) or 0)
                    self.reliability_battle_win = int(data.get("reliability_battle_win", 0) or 0)
                    self.reliability_hourly = int(data.get("reliability_hourly", 0) or 0)

                    # G-Cell system configuration
                    self.use_gcells = bool(data.get("use_gcells", False))
                    self.gcell_random_encounter_win = int(data.get("gcell_random_encounter_win", 0))
                    self.gcell_random_encounter_loose = int(data.get("gcell_random_encounter_loose", 0))
                    self.gcell_battle_win = int(data.get("gcell_battle_win", 0))
                    self.gcell_battle_loose = int(data.get("gcell_battle_loose", 0))
                    self.gcell_training_success = int(data.get("gcell_training_success", 0))
                    self.gcell_training_phase2_failure = int(data.get("gcell_training_phase2_failure", 0))
                    self.gcell_training_phase1_failure = int(data.get("gcell_training_phase1_failure", 0))
                    self.gcell_protein = int(data.get("gcell_protein", 0))
                    self.gcell_care_mistake = int(data.get("gcell_care_mistake", 0))

                    # Internal combat borrows patterns, not device limits.
                    # Modules may cap base damage explicitly; battle bonuses
                    # are added by the internal engine after that cap.
                    self.battle_damage_limit = max(1, int(data.get('battle_damage_limit', 99)))
                    self.battle_max_hit_rate = max(0, min(100, int(data.get('battle_max_hit_rate', 100))))
                    
                    self.unlocks = data.get("unlocks", {
                        "eggs": [],
                        "backgrounds": [],
                        "evolutions": []
                    })

                    self.backgrounds = data.get("backgrounds", [])

                    # Sprite format settings (replaces old high_definition_sprites boolean)
                    # Valid values: "Dot", "Color", "HD"
                    self.primary_sprite_format = data.get("primary_sprite_format", "Color")
                    self.secondary_sprite_format = data.get("secondary_sprite_format", "HD")
                    
                    # Backward compatibility: if old high_definition_sprites field exists, use it to set formats
                    if "high_definition_sprites" in data and "primary_sprite_format" not in data:
                        is_hd = bool(data.get("high_definition_sprites", False))
                        self.primary_sprite_format = "HD" if is_hd else "Color"
                        self.secondary_sprite_format = "Color" if is_hd else "HD"
                    
                    self.enable_special_attack_sprite = bool(data.get("enable_special_attack_sprite", False))

                    visible_stats_raw = data.get("visible_stats", "")
                    if isinstance(visible_stats_raw, str):
                        self.visible_stats = [s.strip() for s in visible_stats_raw.split(",") if s.strip()]
                    elif isinstance(visible_stats_raw, list):
                        self.visible_stats = visible_stats_raw
            except json.JSONDecodeError:
                runtime_globals.game_console.log(f"⚠️ Failed to parse {json_path}")
        else:
            runtime_globals.game_console.log(f"⚠️ Module metadata file {json_path} not found.")

    def load_devices(self) -> None:
        """Load optional physical-device definitions from ``devices.json``.

        Device versions are protocol values and intentionally live outside
        ``module.json`` so they remain independent from evolution-line
        versions. Modules without this file keep their existing egg flow.
        """
        self.devices = []
        json_path = os.path.join(self.folder_path, "devices.json")
        resolved_path = resolve_path(json_path)
        if not os.path.exists(resolved_path):
            return
        try:
            with open_json(json_path) as file:
                data = json.load(file)
            entries = data.get("devices", []) if isinstance(data, dict) else []
            if not isinstance(entries, list):
                return
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                eggs = entry.get("eggs", [])
                if not isinstance(eggs, list):
                    eggs = []
                device = dict(entry)
                device["eggs"] = [
                    egg for egg in eggs
                    if isinstance(egg, dict) and egg.get("name") is not None
                ]
                self.devices.append(device)
            runtime_globals.game_console.log(
                f"[Module {self.name}] Loaded {len(self.devices)} device definitions")
        except (OSError, json.JSONDecodeError) as exc:
            runtime_globals.game_console.log(
                f"[Module {self.name}] Failed to load devices.json: {exc}")

    def load_items(self):
        """Loads items from item.json if it exists in the module folder."""
        json_path = os.path.join(self.folder_path, "item.json")
        resolved_path = resolve_path(json_path)
        if os.path.exists(resolved_path):
            with open_json(json_path) as file:
                try:
                    data = json.load(file)
                    # Expecting a list of items in the JSON file
                    self.items = self.load_items_from_json(data, self.name)
                except json.JSONDecodeError:
                    runtime_globals.game_console.log(f"Error: Failed to parse {json_path}")
        else:
            self.items = {}

    def load_passwords(self):
        """Loads redeemable passwords from codes.json if it exists.

        Each entry: {name, code, type (item|pet|unlock|encounter),
        item/amount | pet/version | unlock | area, cooldown} where cooldown
        is minutes between redemptions (0 = none, -1 = one use only).
        """
        self.passwords = []
        json_path = os.path.join(self.folder_path, "codes.json")
        resolved_path = resolve_path(json_path)
        if not os.path.exists(resolved_path):
            return
        try:
            with open_json(json_path) as file:
                data = json.load(file)
                entries = data.get("passwords", []) if isinstance(data, dict) else []
                self.passwords = [e for e in entries
                                  if isinstance(e, dict) and e.get("code") and e.get("type")]
        except json.JSONDecodeError:
            runtime_globals.game_console.log(f"Error: Failed to parse {json_path}")

    def has_passwords(self) -> bool:
        return bool(getattr(self, "passwords", None))

    def has_gcell_fragment_egg(self) -> bool:
        """True when the module ships a G-Cell Fragment egg.

        Such a module splits the death reward 15% Traited Egg / 15% G-Cell
        Fragment instead of a flat 30% Traited Egg. Cached: this reads
        monster.json.
        """
        if not hasattr(self, "_has_gcell_fragment_egg"):
            self._has_gcell_fragment_egg = any(
                m.get("special") and m.get("special_key") == "gcell_fragment"
                for m in self.get_monsters_by_stage(0)
            )
        return self._has_gcell_fragment_egg

    def load_quests_json(self) -> List[QuestData]:
        """Loads quest data from quests.json if it exists in the module folder."""
        json_path = os.path.join(self.folder_path, "quests.json")
        resolved_path = resolve_path(json_path)
        if not os.path.exists(resolved_path):
            return []
            
        try:
            with open_json(json_path) as file:
                data = json.load(file)
                return self.parse_quests_from_json(data)
        except json.JSONDecodeError:
            runtime_globals.game_console.log(f"Error: Failed to parse {json_path}")
            return []

    def load_events_json(self) -> List[EventData]:
        """Loads event data from events.json if it exists in the module folder."""
        json_path = os.path.join(self.folder_path, "events.json")
        resolved_path = resolve_path(json_path)
        if not os.path.exists(resolved_path):
            return []
            
        try:
            with open_json(json_path) as file:
                data = json.load(file)
                return self.parse_events_from_json(data)
        except json.JSONDecodeError:
            runtime_globals.game_console.log(f"Error: Failed to parse {json_path}")
            return []

    def parse_quests_from_json(self, data) -> List[QuestData]:
        """
        Parse quest data from JSON into QuestData objects.
        """
        # If data is a string, parse it as JSON
        if isinstance(data, str):
            data = json.loads(data)
        # If data is a dict, extract the first list value (e.g., "quest" or "quests")
        if isinstance(data, dict):
            # Try common keys, fallback to first list found
            for key in ("quests", "quest"):
                if key in data and isinstance(data[key], list):
                    data = data[key]
                    break
            else:
                # Fallback: find the first list value in the dict
                for v in data.values():
                    if isinstance(v, list):
                        data = v
                        break
                        
        quests = []
        for entry in data:
            if not isinstance(entry, dict):
                continue  # skip invalid entries
                
            quest_data = QuestData(
                id=entry["id"],
                name=entry["name"],
                type=entry.get("type", 0),
                target_amount_range=entry.get("target_amount_range"),
                target_amount=entry.get("target_amount"),
                reward_type=entry.get("reward_type", 0),
                reward_value=entry.get("reward_value"),
                reward_item=entry.get("reward_item"),
                reward_quantity=entry.get("reward_quantity", 1),
                reward_amount=entry.get("reward_amount", 1)
            )
            quests.append(quest_data)
        return quests

    def parse_events_from_json(self, data) -> List[EventData]:
        """
        Parse event data from JSON into EventData objects.
        """
        # If data is a string, parse it as JSON
        if isinstance(data, str):
            data = json.loads(data)
        # If data is a dict, extract the first list value (e.g., "event" or "events")
        if isinstance(data, dict):
            # Try common keys, fallback to first list found
            for key in ("events", "event"):
                if key in data and isinstance(data[key], list):
                    data = data[key]
                    break
            else:
                # Fallback: find the first list value in the dict
                for v in data.values():
                    if isinstance(v, list):
                        data = v
                        break
                        
        events = []
        for entry in data:
            if not isinstance(entry, dict):
                continue  # skip invalid entries
                
            event_data = EventData(
                id=entry["id"],
                name=entry["name"],
                global_event=entry.get("global", False),
                type=entry.get("type", 0),
                chance_percent=entry.get("chance_percent", 1),
                area=entry.get("area", 1),
                round=entry.get("round", 1),
                item=entry.get("item", ""),
                item_quantity=entry.get("item_quantity", 1)
            )
            events.append(event_data)
        return events

    def load_items_from_json(self, data, module_name):
        """
        Loads items from a JSON list for a given module.
        Each item in the JSON should have: id, name, description, sprite_name, effect, status, amount, boost_time.
        """
        # If data is a string, parse it as JSON
        if isinstance(data, str):
            import json
            data = json.loads(data)
        # If data is a dict, extract the first list value (e.g., "item" or "items")
        if isinstance(data, dict):
            # Try common keys, fallback to first list found
            for key in ("items", "item"):
                if key in data and isinstance(data[key], list):
                    data = data[key]
                    break
            else:
                # Fallback: find the first list value in the dict
                for v in data.values():
                    if isinstance(v, list):
                        data = v
                        break
        # Now data should be a list of dicts
        items = []
        for entry in data:
            if not isinstance(entry, dict):
                continue  # ski p invalid entries
            items.append(GameItem(
                id=entry["id"],
                name=entry["name"],
                description=entry.get("description", ""),
                sprite_name=entry.get("sprite_name", ""),
                effect=entry.get("effect", ""),
                status=entry.get("status", ""),
                amount=entry.get("amount", 0),
                boost_time=entry.get("boost_time", 0),
                module=module_name,
                component_item=entry.get("component_item", ""),
                weight_gain=entry.get("weight_gain")
            ))
        return items

    def load_sprites(self):
        """Loads the flag sprite for the game module."""
        flag_path = os.path.join(self.folder_path, "Flag.png")
        try:
            resolved = resolve_path(flag_path)
            runtime_globals.game_console.log(f"[Module {self.name}] Loading flag from: {flag_path} exists={os.path.exists(resolved)}")
        except Exception:
            pass
        runtime_globals.game_module_flag[self.name] = sprite_load(flag_path, size=(runtime_globals.OPTION_ICON_SIZE, runtime_globals.OPTION_ICON_SIZE))

    def get_monsters_by_stage(self, stage: int, special_list: list[str] = None) -> list[dict]:
        monsters = []
        json_path = os.path.join(self.folder_path, "monster.json")
        resolved_path = resolve_path(json_path)

        if not os.path.exists(resolved_path):
            runtime_globals.game_console.log(f"⚠️ Monster file {json_path} not found.")
            return monsters

        try:
            with open_json(json_path) as file:
                data = json.load(file)
                for monster in data.get("monster", []):
                    if monster["stage"] == stage and (special_list is None or (monster["special"] and monster["name"] in special_list)):
                        monster["module"] = self.name
                        monsters.append(monster)

                runtime_globals.game_console.log(f"✅ Loaded {len(monsters)} monsters from stage {stage}.")
                return monsters
        except json.JSONDecodeError:
            runtime_globals.game_console.log(f"⚠️ Failed to parse {json_path}")
            return monsters

    def get_monster(self, name: str, version: int) -> Optional[dict]:
        json_path = os.path.join(self.folder_path, "monster.json")
        resolved_path = resolve_path(json_path)

        if not os.path.exists(resolved_path):
            runtime_globals.game_console.log(f"⚠️ Monster file {json_path} not found.")
            return None

        try:
            with open_json(json_path) as file:
                data = json.load(file)
                for monster in data.get("monster", []):
                    if monster["name"] == name and monster["version"] == version:
                        return monster
        except json.JSONDecodeError:
            runtime_globals.game_console.log(f"⚠️ Failed to parse {json_path}")
        return None

    def get_monsters_by_index(self, index: int, versions=None) -> list:
        """Every roster record sitting at *index*, across *versions*.

        An index is per-version on these devices -- "each version set has its
        own index" -- so one index can name several different Digimon. A
        caller with no reliable version has to see them all before it can say
        whether the answer is unambiguous.
        """
        json_path = os.path.join(self.folder_path, "monster.json")
        if not os.path.exists(resolve_path(json_path)):
            return []
        found = []
        try:
            with open_json(json_path) as file:
                data = json.load(file)
                for monster in data.get("monster", []):
                    if monster.get("index") != index:
                        continue
                    if versions is None or monster.get("version") in versions:
                        record = dict(monster)
                        record["module"] = self.name
                        found.append(record)
        except json.JSONDecodeError:
            runtime_globals.game_console.log(f"⚠️ Failed to parse {json_path}")
        return found

    def get_monster_by_index(self, index: int, versions=None) -> Optional[dict]:
        """The roster record sitting at *index*, on any of *versions*.

        ``index`` is the Digimon's position in a real device's own roster,
        which is what the connection protocols put on the wire to say what
        the toy is holding. Reading it back is how a DCom opponent gets its
        real name and sprite instead of a generic attribute stand-in.

        *versions* is a collection rather than a single number because the
        wire's version is not always the module's -- the Colour line numbers
        its versions from zero -- so the caller passes every module version
        the received one could mean. None matches any version.
        """
        json_path = os.path.join(self.folder_path, "monster.json")
        resolved_path = resolve_path(json_path)

        if not os.path.exists(resolved_path):
            return None

        try:
            with open_json(json_path) as file:
                data = json.load(file)
                for monster in data.get("monster", []):
                    if monster.get("index") != index:
                        continue
                    if versions is None or monster.get("version") in versions:
                        monster["module"] = self.name
                        return monster
        except json.JSONDecodeError:
            runtime_globals.game_console.log(f"⚠️ Failed to parse {json_path}")
        return None

    def _parse_battle_json(self, path):
        """Helper to load and normalize battle.json data to a list of dicts."""
        resolved_path = resolve_path(path)
        if not os.path.exists(resolved_path):
            return []
        try:
            with open_json(path) as file:
                data = json.load(file)
                if isinstance(data, dict) and "enemies" in data and isinstance(data["enemies"], list):
                    return data["enemies"]
                elif isinstance(data, list):
                    return data
                else:
                    return []
        except Exception as e:
            runtime_globals.game_console.log(f"⚠️ Failed to parse {path}: {e}")
            return []

    def get_enemies(self, area: int, round: int, versions: List[int], special_encounter: bool = False,
                    encounter_name: str = None) -> List[Optional[GameEnemy]]:
        battle_path = os.path.join(self.folder_path, "battle.json")
        all_enemies = self._parse_battle_json(battle_path)
        if not all_enemies:
            runtime_globals.game_console.log(f"⚠️ Enemy file {battle_path} not found or empty.")
            return [None] * len(versions)

        id = 1
        selected = []
        for v in versions:
            match = next(
                (e for e in all_enemies
                 if int(e.get("area", -1)) == int(area)
                 and int(e.get("round", -1)) == int(round)
                 and int(e.get("version", -1)) == int(v)
                 and bool(e.get("special_encounter", False)) == special_encounter),
                None
            )
            if special_encounter and encounter_name:
                # The caller named the enemy (a Friend event picks one specific
                # Friend), so that wins over the area/round lookup - two
                # Friends can share an area and only the name tells them apart.
                named = next(
                    (e for e in all_enemies
                     if e.get("name") == encounter_name
                     and bool(e.get("special_encounter", False))),
                    None
                )
                if named:
                    match = named
            if match is None and special_encounter:
                # Special encounters can live on a version the player never
                # raises - the Xros Wars Friends sit on their own roster - so
                # fall back to any version once the exact one comes up empty.
                match = next(
                    (e for e in all_enemies
                     if int(e.get("area", -1)) == int(area)
                     and int(e.get("round", -1)) == int(round)
                     and bool(e.get("special_encounter", False))),
                    None
                )
            if match:
                if "handicap" not in match:
                    match["handicap"] = 0
                match["id"] = id
                # Ensure required fields for GameEnemy
                if "unlock" not in match:
                    match["unlock"] = None
                if "prize" not in match:
                    match["prize"] = None
                if "hp" not in match:
                    match["hp"] = 0
                if "atk_alt_2" not in match:
                    match["atk_alt_2"] = 0

                id += 1
                selected.append(copy.deepcopy(GameEnemy(**match)))
            else:
                selected.append(None)
        return selected

    def get_enemy_versions(self, area: int, round_: int, special_encounter: bool = False) -> list[int]:
        battle_path = os.path.join(self.folder_path, "battle.json")
        all_enemies = self._parse_battle_json(battle_path)
        if not all_enemies:
            runtime_globals.game_console.log(f"⚠️ Enemy file {battle_path} not found or empty.")
            return []
        versions = set()
        for entry in all_enemies:
            if (int(entry.get("area", -1)) == int(area)
                    and int(entry.get("round", -1)) == int(round_)
                    and bool(entry.get("special_encounter", False)) == special_encounter):
                v = entry.get("version")
                if v is not None:
                    versions.add(v)
        return sorted(versions)

    def get_friend_encounters(self) -> list:
        """Special encounters that register a Friend when beaten.

        Only modules that ship a Friend roster return anything, so callers can
        use an empty list to mean "this module doesn't play by those rules".
        """
        if not hasattr(self, "_friend_encounters"):
            # A Friend is declared on the pet side, as a monster whose
            # availability is "Friend"; the battle side only needs the special
            # encounter that awards it, matched by name.
            friends = {m.get("name") for m in self.get_all_monsters()
                       if read_availability(m) == "Friend"}
            battle_path = os.path.join(self.folder_path, "battle.json")
            out, seen = [], set()
            for entry in (self._parse_battle_json(battle_path) or []):
                if not entry.get("special_encounter"):
                    continue
                name = entry.get("name")
                if not name or name in seen or name not in friends:
                    continue
                seen.add(name)
                out.append({"name": name, "area": int(entry.get("area", 1)),
                            "round": int(entry.get("round", 1))})
            self._friend_encounters = out
        return self._friend_encounters

    def has_friends(self) -> bool:
        return bool(self.get_friend_encounters())

    def get_area_locks(self) -> list:
        """Areas that stay shut until an unlock is earned.

        Some devices hide their last area behind a condition rather than
        behind progress: the Digital Monster X only opens its SP area once
        the device has been connected to its partner version. Any unlock can
        declare `unlocks_area`; the unlock's `version` scopes it to a single
        gameplay version, and no version means it covers every version.

        Returns a list of (area, version_or_None, unlock_name).
        """
        if not hasattr(self, "_area_locks"):
            locks = []
            for unlock in (self.unlocks if isinstance(self.unlocks, list) else []):
                if not isinstance(unlock, dict):
                    continue
                area = unlock.get("unlocks_area")
                if area:
                    locks.append((int(area), unlock.get("version"), unlock.get("name")))
            self._area_locks = locks
        return self._area_locks

    def is_area_unlocked(self, area: int, version=None) -> bool:
        """True when `area` may be entered by a pet of this gameplay version."""
        locks = self.get_area_locks()
        if not locks:
            return True
        from utils.utils_unlocks import is_unlocked
        for lock_area, lock_version, name in locks:
            if lock_area != int(area):
                continue
            if lock_version is not None:
                # A lock scoped to one version can only be judged when the
                # version is known; the same area number is an ordinary area
                # on the other devices, so never hide it on a guess.
                if version is None or int(lock_version) != int(version):
                    continue
            if not is_unlocked(self.name, None, name):
                return False
        return True

    def area_exists(self, area: int) -> bool:
        battle_path = os.path.join(self.folder_path, "battle.json")
        all_enemies = self._parse_battle_json(battle_path)
        if not all_enemies:
            runtime_globals.game_console.log(f"⚠️ Enemy file {battle_path} not found or empty.")
            return False
        for entry in all_enemies:
            if int(entry.get("area", -1)) == int(area):
                return True
        return False

    def get_area_round_counts(self) -> dict:
        battle_path = os.path.join(self.folder_path, "battle.json")
        all_enemies = self._parse_battle_json(battle_path)
        if not all_enemies:
            runtime_globals.game_console.log(f"⚠️ Enemy file {battle_path} not found or empty.")
            return {}
        area_rounds = {}
        for entry in all_enemies:
            area = int(entry.get("area", -1))
            round_ = int(entry.get("round", -1))
            if area == -1 or round_ == -1:
                continue
            if area not in area_rounds:
                area_rounds[area] = set()
            area_rounds[area].add(round_)
        return {area: len(rounds) for area, rounds in area_rounds.items()}
        
    def is_boss(self, area, round, version):
        """
        Checks if the enemy in the specified area, round, and version is a boss.
        """
        enemies = self.get_enemies(area, round + 1, [version])
        return enemies[0] == None
    
    def get_all_monsters(self) -> list[dict]:
        """
        Retorna todos os monstros listados no monster.json deste módulo.
        """
        json_path = os.path.join(self.folder_path, "monster.json")
        resolved_path = resolve_path(json_path)
        if not os.path.exists(resolved_path):
            runtime_globals.game_console.log(f"⚠️ Monster file {json_path} not found.")
            return []

        try:
            with open_json(json_path) as file:
                data = json.load(file)
                return data.get("monster", [])
        except json.JSONDecodeError:
            runtime_globals.game_console.log(f"⚠️ Failed to parse {json_path}")
            return []
        
    def is_valid_area_round(self, area: int, round_: int) -> bool:
        """
        Return True if this module has any battle entry for the given area and round.
        """
        battle_path = os.path.join(self.folder_path, "battle.json")
        all_enemies = self._parse_battle_json(battle_path)
        if not all_enemies:
            return False
        for entry in all_enemies:
            try:
                a = int(entry.get("area", -1))
                r = int(entry.get("round", -1))
            except Exception:
                continue
            if a == int(area) and r == int(round_):
                return True
        return False

    def get_available_area_rounds(self) -> dict:
        """
        Return a dict mapping available area -> sorted list of rounds defined
        in this module's battle.json. Example: {1: [1,2,3], 2: [1,2]}
        """
        battle_path = os.path.join(self.folder_path, "battle.json")
        all_enemies = self._parse_battle_json(battle_path)
        if not all_enemies:
            return {}
        area_rounds = {}
        for entry in all_enemies:
            try:
                a = int(entry.get("area", -1))
                r = int(entry.get("round", -1))
            except Exception:
                continue
            if a == -1 or r == -1:
                continue
            area_rounds.setdefault(a, set()).add(r)
        # convert sets to sorted lists
        return {a: sorted(list(rounds)) for a, rounds in area_rounds.items()}
        
def sprite_load(path, size=None, scale=1):
    """Loads a sprite and optionally scales it to a fixed size or by a scale factor."""
    img = image_load(path).convert_alpha()
    
    if size:
        return pygame.transform.scale(img, size)  # 🔹 Scale to a fixed size
    elif scale != 1:
        base_size = img.get_size()
        new_size = (int(base_size[0] * scale), int(base_size[1] * scale))
        return pygame.transform.scale(img, new_size)  # 🔹 Scale by a multiplier
    
    return img  # 🔹 Return original image if no scaling is applied
