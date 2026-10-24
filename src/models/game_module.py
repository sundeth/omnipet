import json
import os
import random
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
from utils import gcell_rules
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


def _win_ratio_chance_table(value):
    """``evolution_win_ratio_chance`` as [[min ratio, chance %], ...], rows
    clamped to 0-100 and sorted by ratio; [[0, 100]] when absent or empty."""
    rows = []
    for row in value if isinstance(value, list) else []:
        try:
            low, chance = int(row[0]), int(row[1])
        except (TypeError, ValueError, IndexError):
            continue
        rows.append([max(0, min(100, low)), max(0, min(100, chance))])
    return sorted(rows) or [[0, 100]]


#: How a dying pet can be saved (``death_save_by``).
DEATH_SAVE_METHODS = ("Nothing", "B Press", "Shake")


def _death_save(data):
    """The module's death save as (method, amount, seconds, chance %).

    ``death_save_by`` names the method, ``death_save_amount`` the presses
    or shakes, ``death_save_seconds`` the time to make them in, and
    ``death_save_chance`` the chance the pet then lives (the iC: 60 presses
    in 30 seconds, then 5%). A module from before them names only a count,
    ``death_save_by_b_press`` or ``death_save_by_shake``: that method, in
    60 seconds (the minute the pet used to get), always saved. No method or
    no amount is ("Nothing", 0, 60, 100).
    """
    method = data.get("death_save_by")
    if method is None:
        presses = int(data.get("death_save_by_b_press", 0) or 0)
        shakes = int(data.get("death_save_by_shake", 0) or 0)
        method, amount = (("B Press", presses) if presses > 0
                          else ("Shake", shakes) if shakes > 0 else ("Nothing", 0))
    else:
        amount = int(data.get("death_save_amount", 0) or 0)
    seconds = int(data.get("death_save_seconds", 60) or 60)
    chance = data.get("death_save_chance", 100)
    chance = max(0, min(100, int(100 if chance is None else chance)))
    if method not in DEATH_SAVE_METHODS[1:] or amount <= 0:
        return "Nothing", 0, 60, 100
    return method, amount, max(1, seconds), chance


# What a module written before traited_egg_rule / power_bonus_rule existed
# should fall back to, as ``ruleset -> (traited egg rule, power bonus rule)``.
# Kept in core.pet_stats so the arena engine resolves the same rule.
from core.pet_stats import LEGACY_RULESET_RULES, canonical_power_bonus_rule  # noqa: E402


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
        self.load_shops()

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
                    # "Strength Hearts" is read as "Strength Hearts +16".
                    self.power_bonus_rule = canonical_power_bonus_rule(
                        data.get("power_bonus_rule") or _legacy[1])
                    # The "Effort Tiers" rule's rows [stage, effort, power].
                    self.effort_power_tiers = [list(r) for r in data.get("effort_power_tiers") or []
                                               if isinstance(r, (list, tuple)) and len(r) >= 3]
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
                    # The most Strength a pet holds, whatever its stomach: the
                    # Digimon Mini's and the Twin's 0-15 meter. 0 keeps the
                    # stomach as the cap and the old drain (pet_stats.
                    # strength_cap / drained_strength).
                    self.strength_max = max(0, int(data.get("care_strength_max", 0) or 0))
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
                    # Points a form's injury chance rises after each lost
                    # battle and falls after each won one, from its own
                    # `injury_probability` (the iC: 1). 0 keeps it fixed.
                    self.injury_chance_step = int(data.get("injury_chance_step", 0) or 0)
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
                    # Every training costs what a battle does (the iC: one
                    # hunger heart); GamePet.can_train / pay_training_cost.
                    self.training_uses_battle_cost = bool(data.get("training_uses_battle_cost", False))
                    # When battle items (status_boost) are used: "area", at
                    # the start of an adventure battle, lasting the area (the
                    # X's chips); "round", before every round, lasting it (the
                    # iC's weapons). See utils.battle_items.
                    self.battle_item_use = str(data.get("battle_item_use", "area") or "area").lower()
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
                    # Training is the one a sick pet is normally refused: the
                    # Digimon Mini makes you treat it first, and no device is
                    # known to allow it, so this defaults off where
                    # `care_can_battle_while_sick` defaults to refusing.
                    self.care_can_train_while_sick = bool(data.get("care_can_train_while_sick", False))
                    # An injury (Skull) apart from a sickness (Dots) since
                    # 2026-10-21 (utils.ailments); a module from before has
                    # one flag for both.
                    self.care_can_battle_while_injured = bool(data.get(
                        "care_can_battle_while_injured", self.care_can_battle_while_sick))
                    self.care_can_train_while_injured = bool(data.get(
                        "care_can_train_while_injured", self.care_can_train_while_sick))
                    # Weight may fall below the species' min_weight, down to
                    # 1 (Digimon World: starving a Digimon down is how some
                    # evolutions are reached). Off, min_weight is the floor.
                    self.care_allow_below_min_weight = bool(
                        data.get("care_allow_below_min_weight", False))
                    # Minutes a poop may stay uncleaned before it costs its pet
                    # a care mistake and a point of virus; 0 never.
                    self.care_poop_mistake_time = int(data.get("care_poop_mistake_time", 0) or 0)
                    # Every N sleep disturbances make the pet sick; 0 is off.
                    # The Mini's tenth disturbance does it (nhoko, the manual).
                    self.care_disturbance_sickness_count = int(
                        data.get("care_disturbance_sickness_count", 0))
                    self.care_disturbance_sickness_effect = data.get(
                        "care_disturbance_sickness_effect", "Dots")
                    self.count_evolution_while_sleeping = bool(data.get("count_evolution_while_sleeping", True))
                    # The chance a route with a win-ratio criterion is taken,
                    # by the pet's ratio: [[min ratio, chance %], ...], the
                    # highest row at or below it. [[0, 100]]: always, as before.
                    # See utils.evolution_rules.
                    self.evolution_win_ratio_chance = _win_ratio_chance_table(
                        data.get("evolution_win_ratio_chance"))
                    # Once an evolution has failed (any pet with a win-rate
                    # route whose timer try took none), hunger, strength and
                    # poop run twice as fast; so at Stage VI+ after 48 hours
                    # (PENC, PENGZ). A module from before names the old
                    # evolution_fail_on_first_try, which brought this.
                    legacy_fail = bool(data.get("evolution_fail_on_first_try", False))
                    self.failed_evolution_double_needs = bool(
                        data.get("failed_evolution_double_needs", legacy_fail))
                    # That flag also marked the PENGZ's Traited Egg rule.
                    if legacy_fail and self.traited_egg_rule == "Win Ratio (Stage 5)":
                        self.traited_egg_rule = "Win Ratio (Failed or Aged, Lifetime)"

                    # Injuries (Skull) and sicknesses (Dots) in one form,
                    # counted apart, and the minutes each may go untreated
                    # (utils.ailments). A module from before the split names
                    # one count and one timer for both: each kind gets them.
                    self.death_max_injuries = int(data.get("death_max_injuries"))
                    self.death_max_sicknesses = int(data.get("death_max_sicknesses", self.death_max_injuries))
                    self.death_sick_timer = int(data.get("death_sick_timer"))
                    self.death_injury_timer = int(data.get("death_injury_timer", self.death_sick_timer))
                    self.death_hunger_timer = int(data.get("death_hunger_timer"))
                    self.death_starvation_count = int(data.get("death_starvation_count"))
                    # Strength's starvation counter: the meter found empty
                    # this many times without being filled kills (the Xros
                    # Wars Color's Debilitation counter, 18). 0 disables it.
                    self.death_debilitation_count = int(data.get("death_debilitation_count", 0) or 0)
                    self.death_strength_timer = int(data.get("death_strength_timer"))
                    self.death_stage45_mistake = int(data.get("death_stage45_mistake"))
                    self.death_stage67_mistake = int(data.get("death_stage67_mistake"))
                    self.death_care_mistake = int(data.get("death_care_mistake",999999))
                    (self.death_save_by, self.death_save_amount,
                     self.death_save_seconds, self.death_save_chance) = _death_save(data)
                    self.death_old_age = int(data.get("death_old_age",0))
                    # How a pet's life ends (utils.lifespan_rules): None,
                    # Activity Time, Old Age or Age 5. A module from before
                    # names only death_old_age, which was Old Age.
                    self.lifespan_rule = str(data.get(
                        "lifespan_rule", "Old Age" if self.death_old_age > 0 else "None") or "None")
                    
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
                    # The style picks the meter and how gains are read
                    # (utils.gcell_rules): Disabled, DMGZ (the flat gcell_*
                    # values below) or PENGZ (the by-stage tables). A module
                    # from before it says use_gcells, which meant DMGZ.
                    self.gcell_style = gcell_rules.read_style(data)
                    self.use_gcells = self.gcell_style != gcell_rules.DISABLED
                    self.gcell_points_per_cell = gcell_rules.stage_table(
                        data.get("gcell_points_per_cell"), gcell_rules.DEFAULT_POINTS_PER_CELL)
                    self.gcell_care_mistake_by_stage = gcell_rules.stage_table(
                        data.get("gcell_care_mistake_by_stage"),
                        gcell_rules.DEFAULT_CARE_MISTAKE_BY_STAGE)
                    self.gcell_battle_win_by_stage = gcell_rules.stage_table(
                        data.get("gcell_battle_win_by_stage"), gcell_rules.DEFAULT_BATTLE_WIN_BY_STAGE)
                    self.gcell_battle_loss_by_stage = gcell_rules.stage_table(
                        data.get("gcell_battle_loss_by_stage"),
                        gcell_rules.DEFAULT_BATTLE_LOSS_BY_STAGE)
                    self.gcell_random_encounter_win_by_stage = gcell_rules.stage_table(
                        data.get("gcell_random_encounter_win_by_stage"),
                        gcell_rules.DEFAULT_ENCOUNTER_WIN_BY_STAGE)
                    self.gcell_random_encounter_loss_by_stage = gcell_rules.stage_table(
                        data.get("gcell_random_encounter_loss_by_stage"),
                        gcell_rules.DEFAULT_ENCOUNTER_LOSS_BY_STAGE)
                    self.gcell_training_gain = _training_table(
                        data.get("gcell_training_gain") or list(gcell_rules.DEFAULT_TRAINING_GAIN),
                        0, 0)
                    self.gcell_training_gain_anguirus = _training_table(
                        data.get("gcell_training_gain_anguirus")
                        or list(gcell_rules.DEFAULT_TRAINING_GAIN_ANGUIRUS), 0, 0)
                    self.gcell_other_device_win = int(data.get(
                        "gcell_other_device_win", gcell_rules.DEFAULT_OTHER_DEVICE_WIN))
                    self.gcell_other_device_loss = int(data.get(
                        "gcell_other_device_loss", gcell_rules.DEFAULT_OTHER_DEVICE_LOSS))
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

        The file may also name the codes for the Specials hub: ``title``
        (PEN20's are "Copymon"; empty means "Password") and ``icon``, a
        sprite in the module's ``icons/`` folder (empty: the generic one).
        """
        self.passwords = []
        self.passwords_title = ""
        self.passwords_icon = ""
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
                if isinstance(data, dict):
                    self.passwords_title = str(data.get("title", "") or "")
                    self.passwords_icon = str(data.get("icon", "") or "")
        except json.JSONDecodeError:
            runtime_globals.game_console.log(f"Error: Failed to parse {json_path}")

    def load_shops(self):
        """Loads currencies and shops from shop.json if it exists.

        ``currency``: [{name, icon, unit, training_gain[4], cap}];
        ``shop``: [{name, unlock, icon, currency, items: [{item, price,
        unlock, card_pack, card_offer, rarity_prices, versions}]}], each item
        an item.json name, or a card pack (cards.json pack id) in its place,
        or a card offer (``card_offer``, a pack id: one card of that pack, a
        different one each day, priced by its rarity in ``rarity_prices``,
        {"Common": 500, ...}, else at ``price``); ``versions`` (optional)
        the pet versions it is sold to. A module without the file has
        neither. Balances and buying: utils.currency_utils.
        """
        self.currencies, self.shops = [], []
        json_path = os.path.join(self.folder_path, "shop.json")
        if not os.path.exists(resolve_path(json_path)):
            return
        try:
            with open_json(json_path) as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError) as exc:
            runtime_globals.game_console.log(f"Error: Failed to parse {json_path}: {exc}")
            return
        if not isinstance(data, dict):
            return
        self.currencies = [c for c in data.get("currency") or []
                           if isinstance(c, dict) and c.get("name")]
        self.shops = [s for s in data.get("shop") or []
                      if isinstance(s, dict) and s.get("name")]

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
                item=entry.get("item", "") or "",
                item_quantity=entry.get("item_quantity", 1),
                trigger=str(entry.get("trigger", "random") or "random"),
                outcome=str(entry.get("outcome", "win") or "win"),
                opponent_device_version=entry.get("opponent_device_version"),
                protocol=str(entry.get("protocol", "") or ""),
                draw=str(entry.get("draw", "") or ""),
                versions=entry.get("versions") or None,
                pools=entry.get("pools") or None,
                pool_field=str(entry.get("pool_field", "") or ""),
                shop=str(entry.get("shop", "") or ""),
                access_minutes=int(entry.get("access_minutes", 0) or 0),
                reward_round=int(entry.get("reward_round", 0) or 0),
                delay_minutes=entry.get("delay_minutes") or None,
                item_sequence=[str(n or "") for n in entry.get("item_sequence") or []] or None,
                item_pool=[str(n) for n in entry.get("item_pool") or [] if n] or None,
                trigger_areas=[int(a) for a in entry.get("trigger_areas") or []] or None,
                until_friend=bool(entry.get("until_friend", False)),
            )
            events.append(event_data)
        return events

    def load_event_extras(self) -> dict:
        """events.json's module-wide blocks, beside its ``events`` list:

        ``schedule``        {time group: ["HH:MM", ...]}, the times a
                            "schedule" event can fire for a pet whose
                            ``encounter_time_group`` is that group (the
                            Godzilla devices' encounter times);
        ``connect_points``  {cap, win, loss, battles, rewards: [{version,
                            item}]}: a pet's Connect Points, the battles
                            that give them (connection, adventure) and what
                            filling them gives, an empty item a draw of
                            nothing (utils.connect_points). A cap of 0, or
                            no block, switches them off.

        Cached; {} when the file has neither."""
        if not hasattr(self, "_event_extras"):
            self._event_extras = {}
            json_path = os.path.join(self.folder_path, "events.json")
            if os.path.exists(resolve_path(json_path)):
                try:
                    with open_json(json_path) as file:
                        data = json.load(file)
                    if isinstance(data, dict):
                        self._event_extras = {k: data[k] for k in ("schedule", "connect_points")
                                              if isinstance(data.get(k), dict)}
                except (OSError, json.JSONDecodeError):
                    runtime_globals.game_console.log(f"Error: Failed to parse {json_path}")
        return self._event_extras

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
                weight_gain=entry.get("weight_gain"),
                protocol_value=int(entry.get("protocol_value", 0) or 0),
                attack_sprite=int(entry.get("attack_sprite", 0) or 0),
                digisoul=str(entry.get("digisoul", "") or ""),
                currency=str(entry.get("currency", "") or ""),
                extra_effects=[dict(row) for row in entry.get("extra_effects") or []
                               if isinstance(row, dict) and row.get("effect")],
                reusable=bool(entry.get("reusable", False)),
                target=str(entry.get("target", "") or ""),
                min_stage=int(entry.get("min_stage", 0) or 0),
                max_stage=int(entry.get("max_stage", 0) or 0)
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

    def _monster_cache(self):
        """(records, {(name, version): first record}) of monster.json, parsed
        again only when the file changes (its modification time and size), or
        None when there is no file. The records are shared: never handed out.

        get_monster used to parse the whole file for one record, from a pet's
        evolution and unlock checks among others: up to 0.4 s a call on the
        Pi Zero 2W for the larger modules (VB's file is 0.9 MB).
        """
        json_path = os.path.join(self.folder_path, "monster.json")
        try:
            st = os.stat(resolve_path(json_path))
        except OSError:
            return None
        stamp = (st.st_mtime_ns, st.st_size)
        cached = getattr(self, "_monster_records", None)
        if cached is not None and cached[0] == stamp:
            return cached[1], cached[2]
        records = [m for m in self.get_all_monsters() if isinstance(m, dict)]
        index = {}
        for monster in records:
            index.setdefault((monster.get("name"), monster.get("version")), monster)
        self._monster_records = (stamp, records, index)
        return records, index

    def get_monster(self, name: str, version: int) -> Optional[dict]:
        """The first record of *name* at *version*: the caller's own copy."""
        cache = self._monster_cache()
        if cache is None:
            runtime_globals.game_console.log(
                f"⚠️ Monster file {os.path.join(self.folder_path, 'monster.json')} not found.")
            return None
        record = cache[1].get((name, version))
        return copy.deepcopy(record) if record is not None else None

    def find_monster(self, name: str, version: int = None) -> Optional[dict]:
        """`get_monster`, else the first form called *name* on any version:
        a pet's history keeps names only, and a route can cross versions."""
        if version is not None:
            monster = self.get_monster(name, version)
            if monster is not None:
                return monster
        cache = self._monster_cache()
        if cache is None:
            return None
        record = next((m for m in cache[0] if m.get("name") == name), None)
        return copy.deepcopy(record) if record is not None else None

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
            matches = [e for e in all_enemies
                       if int(e.get("area", -1)) == int(area)
                       and int(e.get("round", -1)) == int(round)
                       and int(e.get("version", -1)) == int(v)
                       and bool(e.get("special_encounter", False)) == special_encounter]
            # A special round may list several enemies: one is met at random
            # (the Digivice iC 20X's connection Coliseum changed its line-up
            # between runs). An adventure round keeps its first.
            match = (random.choice(matches) if special_encounter and len(matches) > 1
                     else (matches[0] if matches else None))
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

    def get_recruit_friends(self) -> list:
        """Raisable Digimon a battle.json ``friend`` enemy recruits as a
        Friend when beaten, in an adventure round or a special encounter
        (Digimon World's recruits): their names. Friends of availability
        "Friend" are not among them (`get_friend_encounters`)."""
        if not hasattr(self, "_recruit_friends"):
            # Saved on disk per module (both source files' times and sizes):
            # reading every module's battle.json text cost the Library's first
            # visit of a session a read of 1.7 MB.
            stamps = (self._file_stamp("battle.json"), self._file_stamp("monster.json"))
            stamp = None if None in stamps else stamps[0] + stamps[1]
            saved = self._read_disk_cache("recruits", stamp) if stamp is not None else None
            if isinstance(saved, list):
                self._recruit_friends = saved
                return saved
            roster = self.roster_summary()
            friends = {r[0] for r in roster if r[4] == "Friend"}
            raisable = {r[0] for r in roster}
            battle_path = os.path.join(self.folder_path, "battle.json")
            out = []
            # Only a battle.json that flags an enemy as a friend can recruit:
            # the text check spares parsing every other module's.
            try:
                with open(resolve_path(battle_path), encoding="utf-8-sig") as fh:
                    mentions_friend = '"friend"' in fh.read()
            except OSError:
                mentions_friend = True        # unreadable here: let the parser decide
            for entry in ((self._parse_battle_json(battle_path) or []) if mentions_friend else []):
                name = entry.get("name")
                if entry.get("friend") and name in raisable and name not in friends \
                        and name not in out:
                    out.append(name)
            if stamp is not None:
                self._write_disk_cache("recruits", stamp, out)
            self._recruit_friends = out
        return self._recruit_friends

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
        """Whether *area* is an adventure area: one with an enemy that is not
        a special encounter. Special encounters may sit in areas of their
        own (the Godzilla devices' encounter opponents, an event's battle
        run), which the adventure never moves into."""
        battle_path = os.path.join(self.folder_path, "battle.json")
        all_enemies = self._parse_battle_json(battle_path)
        if not all_enemies:
            runtime_globals.game_console.log(f"⚠️ Enemy file {battle_path} not found or empty.")
            return False
        for entry in all_enemies:
            if int(entry.get("area", -1)) == int(area) and not entry.get("special_encounter"):
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
            # Adventure rounds only, as `area_exists` counts them.
            if area == -1 or round_ == -1 or entry.get("special_encounter"):
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
    
    def roster_summary(self) -> tuple:
        """(name, version, attribute, stage, availability) of every monster in
        monster.json, read-only, parsed again only when the file changes.

        For listing rosters: the Library lists every module's, and parsing
        all of them each time it opened cost the Pi Zero 2W 2.5 s. The
        summary is also kept on disk (save/cache/roster/), so a session's
        first visit reads a few KB per module instead of parsing monster.json
        (still ~0.5 s for the largest on the Pi).
        """
        stamp = self._file_stamp("monster.json")   # None: nothing to key a cache on, read every time
        cached = getattr(self, "_roster_summary", None)
        if stamp is not None and cached is not None and cached[0] == stamp:
            return cached[1]
        saved = self._read_disk_cache("roster", stamp) if stamp is not None else None
        roster = tuple(tuple(row) for row in saved) if isinstance(saved, list) else None
        if roster is None:
            cache = self._monster_cache() if stamp is not None else None
            records = cache[0] if cache is not None else self.get_all_monsters()
            roster = tuple(
                (m.get("name"), m.get("version"), m.get("attribute", ""), m.get("stage", 0),
                 read_availability(m))
                for m in records if isinstance(m, dict))
            if stamp is not None:
                self._write_disk_cache("roster", stamp, [list(row) for row in roster])
        if stamp is not None:
            self._roster_summary = (stamp, roster)
        return roster

    #: Bump when what the disk caches hold changes: older cache files are ignored.
    ROSTER_CACHE_FORMAT = 1

    def _file_stamp(self, file_name):
        """(modification time, size) of one of the module's files, or None."""
        try:
            st = os.stat(resolve_path(os.path.join(self.folder_path, file_name)))
        except OSError:
            return None
        return (st.st_mtime_ns, st.st_size)

    def _disk_cache_path(self, kind):
        from core import game_globals
        suffix = "" if kind == "roster" else f".{kind}"
        return os.path.join(game_globals._get_base_save_dir(), "cache", "roster", f"{self.name}{suffix}.json")

    def _read_disk_cache(self, kind, stamp):
        """What was saved under *kind* for exactly these source files (times
        and sizes), or None."""
        try:
            with open(self._disk_cache_path(kind), encoding="utf-8") as fh:
                data = json.load(fh)
            if data.get("format") != self.ROSTER_CACHE_FORMAT or data.get("stamp") != list(stamp):
                return None
            return data["value"]
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return None

    def _write_disk_cache(self, kind, stamp, value):
        """Save *value* for the next session; a failure only costs a parse."""
        try:
            path = self._disk_cache_path(kind)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"format": self.ROSTER_CACHE_FORMAT, "module": self.name,
                           "stamp": list(stamp), "value": value}, fh)
            os.replace(tmp, path)
        except (OSError, TypeError, ValueError):
            pass

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
        Return True if this module has an adventure battle (not a special
        encounter) for the given area and round.
        """
        battle_path = os.path.join(self.folder_path, "battle.json")
        all_enemies = self._parse_battle_json(battle_path)
        if not all_enemies:
            return False
        for entry in all_enemies:
            if entry.get("special_encounter"):
                continue
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
        Return a dict mapping adventure area -> sorted list of its rounds in
        this module's battle.json (special encounters left out). Example:
        {1: [1,2,3], 2: [1,2]}
        """
        battle_path = os.path.join(self.folder_path, "battle.json")
        all_enemies = self._parse_battle_json(battle_path)
        if not all_enemies:
            return {}
        area_rounds = {}
        for entry in all_enemies:
            if entry.get("special_encounter"):
                continue
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
