"""Android-only, isolated minute rules, based on GamePet's care helpers.

The foreground methods and update loop are deliberately unchanged. These
data-only counterparts receive an explicit world (clock, RNG, party and effect
collector), and must never import mutable game globals or call platform/UI APIs.
When changing a foreground care rule, update its counterpart here and the parity
tests. Presentation, evolution commit and clock reconciliation live in
android_offline.py. This is not a background service.
"""
from datetime import datetime
from core import constants, pet_stats
from utils.data_compat import availability as read_availability, get_data
from utils import ailments, evolution_rules, gcell_rules, lifespan_rules


class AndroidPetRules:
    VITAL_VALUE_CAPS = pet_stats.VITAL_VALUE_CAPS

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
        # GamePet.set_data: a later generation evolves earlier from Child on.
        world = getattr(self, "world", None)
        self.time = evolution_rules.generation_time(
            world.get_module(self.module) if world else None, self, self.stage, data.get("time", 0))
        self.poop_timer = data.get("poop_timer", 60)
        self.min_weight = data.get("min_weight")
        self.evol_weight = data.get("evol_weight", 0)
        self.stomach = data.get("stomach")
        self.hunger_loss = data.get("hunger_loss")
        self.strength_loss = data.get("strength_loss")
        self.power = data.get("power")
        # GamePet.set_data: an offline evolution takes the new form's RPM and
        # injury chance too (it kept the old form's before).
        self.rpm = data.get("rpm", 0)
        self.injury_probability = data.get("injury_probability", 0) or 0
        self.injury_chance_offset = 0
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
        # Scheduled encounters (GamePet.set_data).
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
        # No ailment, counts or untreated timers in a new form (GamePet).
        ailments.reset(self)
        self.level = 1
        self.experience = 0
        # The Digimon Twin carries its battle record across an evolution while
        # resetting the training count, which is what lets a Perfect reach
        # Ultimate without fighting again.
        if not getattr(self.world.get_module(self.module), 'battle_keep_counts_on_evolution', False):
            self.win = self.battles = 0
        self.animation_counter = self.frame_counter = self.frame_index = 0
        self.care_food_mistake_timer = self.care_strength_mistake_timer = self.care_sleep_mistake_timer = 0

        # Reset real-time gameplay timers (NOT _last_age_date — age persists across evolutions)
        _now = self.world.cursor
        self._rt_origin = _now
        self._rt_last_minute = 0
        self._rt_dead_start = 0.0
        self._rt_last_sleep_check = _now
        # Countdown counters: start at max, tick down 1/min, trigger & reset at 0
        self._cd_hunger = self.hunger_loss or 0
        self._cd_strength = self.strength_loss or 0
        # The poop countdown runs on through an evolution (GamePet.reset_variables).
        if self._cd_poop > 0 and self.poop_timer:
            self._cd_poop = min(self._cd_poop, self.poop_timer)
        else:
            self._cd_poop = self.poop_timer or 0
        # Evolution count-up: starts at 0, increments 1/min, checks conditions after reaching self.time
        self._evol_minutes = 0
        # Form time, a failed evolution and tagged defeats (GamePet).
        self.form_minutes = 0
        self.evolution_failed = False
        self.tag_defeats = {}
        self.special_encounter = False

        self.enemy_kills = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        self.starvation_counter = 0
        # Strength's starvation counter (the Xros Wars Color's Debilitation)
        self.debilitation_counter = 0
        # Minutes the hunger / strength meter has been empty (death_*_timer)
        self.hunger_empty_minutes = self.strength_empty_minutes = 0
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
        self.death_save_elapsed = 0.0
        self.death_save_immunity = 0
        self.death_cause = ""  # tracks what triggered death: injuries, sicknesses, sickness, injury, hunger, strength, care_mistakes, starvation, old_age, lifespan, stage_mistakes

        self.quests_completed = 0

        # Digimon Twin Event Communications. Its Perfect Conditions weigh this
        # against the win ratio, so it is pet state rather than a statistic.
        # It follows the battle record: kept across an evolution on a module
        # that keeps counts, cleared with them otherwise.
        if not getattr(self.world.get_module(self.module), 'battle_keep_counts_on_evolution', False):
            self.event_communications = 0

        # Item uses, for the evolution criteria that count them - the Twin
        # needs five Bombs for Digitamamon. Keyed by item id.
        self.item_uses = {}

        self.trophies = 0
        self.vital_values = 100
        self.overfeed = 0
        self.sleep_disturbances = 0

        module = self.world.get_module(self.module)

        if self.traited:
            self.level = module.traited_egg_starting_level

        self.use_condition_hearts = module.use_condition_hearts
        if self.use_condition_hearts:
            self.condition_hearts = self.condition_hearts_max
        self.mistakes = 0

        self.gcell_points = 0

        self._99g_triggered = False
        self.burpmon_active = False

    def check_death_conditions(self):
        if self.state in ["nap", "dead"]:
            return False

        result = False
        death_cause = ""

        module = self.world.get_module(self.module)

        # 1. Too many injuries or sicknesses in one form, or one left
        # untreated too long (GamePet; utils.ailments).
        ailment_cause = ailments.death_cause(self, module)
        if ailment_cause:
            result = True
            death_cause = ailment_cause

        # 3. Hunger or Strength empty for N consecutive minutes (DMC, DM20: 12 h;
        # the original DM: 6 h). Counted apart from the call timers, which
        # stop at the care mistake: reading those, this death never came.
        if module.death_hunger_timer > 0 and getattr(self, 'hunger_empty_minutes', 0) >= module.death_hunger_timer:
            result = True
            death_cause = "hunger"
        if module.death_strength_timer > 0 and getattr(self, 'strength_empty_minutes', 0) >= module.death_strength_timer:
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

        # The meter emptied N times without being filled (Pendulum Color 20,
        # Xros Wars Color 18): "if the counter reaches 18, it will die".
        if module.death_starvation_count > 0 and self.starvation_counter >= module.death_starvation_count:
            result = True
            death_cause = "starvation"
        if (getattr(module, 'death_debilitation_count', 0) > 0
                and getattr(self, 'debilitation_counter', 0) >= module.death_debilitation_count):
            result = True
            death_cause = "debilitation"

        if module.death_care_mistake > 0 and self.mistakes >= module.death_care_mistake:
            result = True
            death_cause = "care_mistakes"

        # The module's lifespan rule (GamePet). Old age overrides all other
        # causes and cannot be saved.
        lifespan_cause = lifespan_rules.death_cause(self, module, self.can_evolve)
        if lifespan_cause == "old_age":
            return True
        if lifespan_cause:
            result = True
            death_cause = lifespan_cause

        # Old age death cannot be saved
        if result and death_cause == "old_age":
            return True

        # The death save (module death_save_*): the pet is dying, and the
        # player has the module's seconds to press or shake it back.
        if result and self.death_save_immunity == 0 and not self.dying:
            if module.death_save_by != "Nothing":
                self.death_cause = death_cause
                self.dying = True
                self.death_save_elapsed = 0.0
                self.set_state("dying")
                self.world.sound("death")
                if module.death_save_by == "B Press":
                    self.death_save_b_counter, what = module.death_save_amount, "B presses"
                else:
                    self.death_save_shake_counter, what = module.death_save_amount, "shakes"
                self.world.log(
                    f"[Death Save] {self.name} needs {module.death_save_amount} {what} in "
                    f"{module.death_save_seconds} seconds! Cause: {death_cause}")
                return False
        # A dying pet lives or dies by its save (update_death_save).
        if self.dying:
            return False

        return result

    def update_death_save(self, seconds):
        """GamePet.update_death_save: the presses or shakes made within the
        module's seconds, its chance decides; out of time, the pet dies.
        Nobody presses while the app is closed, so here the time runs out."""
        if not self.dying:
            return
        module = self.world.get_module(self.module)
        if module.death_save_by == "Nothing":
            self.die()
        elif self.death_save_b_counter <= 0 and self.death_save_shake_counter <= 0:
            if self.world.rng.random() * 100 < module.death_save_chance:
                self._death_saved()
            else:
                self.world.log(
                    f"[Death Save] {self.name} made it, but lost its {module.death_save_chance}% chance")
                self.die()
        else:
            self.death_save_elapsed = (getattr(self, "death_save_elapsed", 0.0) or 0.0) + seconds
            if self.death_save_elapsed >= module.death_save_seconds:
                self.world.log(f"[Death Save] {self.name} ran out of time")
                self.die(late=self.death_save_elapsed - module.death_save_seconds)

    def die(self, late=0.0):
        """The pet dies, *late* seconds ago (OfflinePet: a death route may
        take it instead)."""
        raise NotImplementedError

    def _death_saved(self):
        """GamePet._death_saved: what was killing the pet is undone, and it
        is immune for an hour."""
        cause = getattr(self, 'death_cause', '')
        if ailments.undo(self, cause):
            pass
        elif cause == "hunger":
            self.care_food_mistake_timer = 0
            self.hunger_empty_minutes = 0
        elif cause == "strength":
            self.care_strength_mistake_timer = 0
            self.strength_empty_minutes = 0
        elif cause == "starvation":
            self.starvation_counter = max(0, self.starvation_counter - 1)
        elif cause == "debilitation":
            self.debilitation_counter = max(0, self.debilitation_counter - 1)
        elif cause in ("care_mistakes", "stage_mistakes"):
            self.mistakes = max(0, self.mistakes - 1)
        # "lifespan" has nothing to undo (GamePet).
        self.death_save_immunity = 60  # 60 minutes
        self.death_save_b_counter = 0
        self.death_save_shake_counter = 0
        self.death_save_elapsed = 0.0
        self.dying = False
        self.death_cause = ""
        self.set_state("happy2")
        self.world.sound("happy")
        self.world.log(f"[Death Save] {self.name} was saved (cause: {cause})! 60-minute immunity granted.")

    def add_ailment(self, kind):
        """GamePet.add_ailment: a sickness or an injury, one at a time, none
        for a form with heal_doses 0."""
        if not ailments.onset(self, kind):
            return False
        self._apply_reliability_event('reliability_sickness_or_injury')
        self.set_state("sick")
        return True

    def update_99g_effect(self):
        """Handle the 99g weight effect based on the module's care_99g_effect setting."""
        module = self.world.get_module(self.module)
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

        if self.weight >= 99 and not getattr(self, '_99g_triggered', False):
            self._99g_triggered = True
            kind = ailments.kind_for_effect(effect)
            if kind:
                self.add_ailment(kind)

    def _has_dna_evolution_criterion(self, evolution):
        """Whether a route asks for DigiSoul DNA: a non-empty
        ``digisoul_dna``, the types any of which it takes (GamePet's rule)."""
        dna_types = evolution.get("digisoul_dna")
        return isinstance(dna_types, (list, tuple)) and len(dna_types) > 0

    def get_dna_total(self, dna_types=None):
        """How many of the remembered DNA feeds are of *dna_types*."""
        wanted = None if dna_types is None else {str(t).casefold() for t in dna_types}
        dna = getattr(self, "dna", None)
        return sum(1 for d in (dna if isinstance(dna, list) else [])
                   if wanted is None or d.casefold() in wanted)

    def leading_dna(self):
        """The type held most among the remembered feeds, the latest fed on
        a tie; None for none (GamePet.leading_dna)."""
        dna = getattr(self, "dna", None)
        queue = list(dna) if isinstance(dna, list) else []
        if not queue:
            return None
        counts, last_fed = {}, {}
        for position, d in enumerate(queue):
            counts[d] = counts.get(d, 0) + 1
            last_fed[d] = position
        return max(counts, key=lambda d: (counts[d], last_fed[d]))

    def _dna_evolution_requirement_met(self, evolution):
        """A DNA route is taken when the leading DNA is one of its types."""
        if not self._has_dna_evolution_criterion(evolution):
            return True
        leading = self.leading_dna()
        return leading is not None and leading.casefold() in {
            str(t).casefold() for t in evolution["digisoul_dna"]}

    def _ordered_normal_evolution_routes(self):
        """The routes in their JSON order: the first one met wins."""
        return list(self.evolve)

    def update_evolution(self):
        """GamePet.update_evolution: defeat-count routes at once, the rest on
        the timer, and a failed evolution is final."""
        if any(evolution_rules.is_immediate_route(e) for e in (self.evolve or [])):
            evo = self.find_evolution(kind="immediate")
            if evo is not None:
                self._apply_evolution(evo)
                return

        if self._evol_minutes < self.time or self.need_care():
            return
        if getattr(self, "evolution_failed", False):
            return

        evo = self.find_evolution()
        if evo is None:
            # GamePet.update_evolution: a pet with a win-rate route gets one
            # try, and so does a form an Evolution Window rule covers.
            if (evolution_rules.should_fail(self.evolve or [])
                    or lifespan_rules.closes_evolution(self, self.world.get_module(self.module))):
                self.evolution_failed = True
                self.world.log(f"{self.name} failed to evolve.")
            return
        self._apply_evolution(evo)

    def death_evolution(self):
        """GamePet._death_evolution: a death route (``at_death``) taken
        instead of dying. True when the pet evolved."""
        if not any(evolution_rules.is_death_route(e) for e in (self.evolve or [])):
            return False
        evo = self.find_evolution(kind="death")
        if evo is None:
            return False
        self.dying = False
        self.death_cause = ""
        self._apply_evolution(evo)
        return True

    def can_evolve(self):
        """GamePet.can_evolve: no failed evolution, and a normal route met
        now, its chances counted as met (no number drawn)."""
        return not getattr(self, "evolution_failed", False) and self.find_evolution(roll_chance=False) is not None

    def find_evolution(self, kind="normal", roll_chance=True):
        """GamePet.find_evolution: the route taken, or None. Chances are
        rolled when *roll_chance*; otherwise they count as met."""
        module_obj = self.world.get_module(self.module)
        poops_on_screen = len(self.world.poop_list)
        table_roll = evolution_rules.once(lambda: self.world.rng.random() * 100)
        for evo in self._ordered_normal_evolution_routes():
            if not evolution_rules.route_wanted(evo, kind):
                continue
            def in_range(val, r): return r[0] <= val <= r[1]
            def in_time_range(time_range):
                try:
                    now_time = self.world.now.time()
                    start_time = datetime.strptime(time_range[0].strip(), "%H:%M").time()
                    end_time = datetime.strptime(time_range[1].strip(), "%H:%M").time()
                    
                    if start_time < end_time:
                        return start_time <= now_time <= end_time
                    else:
                        # Handle overnight range (e.g., 23:00 to 01:00)
                        return now_time >= start_time or now_time <= end_time
                except Exception as e:
                    self.world.log(f"[!] Error parsing time_range: {e}")
                    return False
                    
            if (
                ("jogress" in evo) or ("item" in evo) or
                ("mistakes" in evo and not in_range(self.mistakes, evo["mistakes"])) or
                ("condition_hearts" in evo and not in_range(self.condition_hearts, evo["condition_hearts"])) or
                ("training" in evo and not in_range(self.effort, evo["training"])) or
                ("overfeed" in evo and not in_range(self.overfeed, evo["overfeed"])) or
                # true: beat a special encounter in this form; false: did not
                # (mirrors GamePet.find_evolution).
                (evo.get("special_encounter") is not None and
                 bool(evo["special_encounter"]) != bool(self.special_encounter)) or
                ("level" in evo and not in_range(self.level, evo["level"])) or
                ("quests_completed" in evo and not in_range(self.quests_completed, evo["quests_completed"])) or
                # Digimon Twin: Event Communications run against the win ratio
                # to give the Perfect/Ultimate chance.
                ("event_communication" in evo and
                 not in_range(getattr(self, "event_communications", 0),
                              evo["event_communication"])) or
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
                # G-Cells in the module's style (GamePet)
                ("gcells" in evo and not in_range(gcell_rules.cells(module_obj, self), evo["gcells"])) or
                ("stage-5" in evo and not in_range(self.enemy_kills[5], evo["stage-5"])) or
                ("stage-6" in evo and not in_range(self.enemy_kills[6], evo["stage-6"])) or
                ("stage-7" in evo and not in_range(self.enemy_kills[7], evo["stage-7"])) or
                ("stage-8" in evo and not in_range(self.enemy_kills[8], evo["stage-8"])) or
                ("stage-9" in evo and not in_range(self.enemy_kills[9], evo["stage-9"])) or
                ("pvp" in evo and not in_range(getattr(self, "pvp_battles", 0) or 0, evo["pvp"])) or
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
                 self.world.rng.random() * 100 >= evo["chance"])
            ):
                continue
            # Then the module's win-ratio table and a death route's chance.
            if roll_chance and evolution_rules.rolls_fail(
                    module_obj, self, evo, lambda: self.world.rng.random() * 100, kind, table_roll):
                continue

            # The target has to exist on this version before anything else is
            # decided. Checked for EVERY stage: this block used to be skipped
            # for eggs, so a stage-0 route naming a missing form fell straight
            # through to evolve_to and left the egg unable to hatch at all.
            module = self.world.get_module(self.module)
            pet_data = module.get_monster(evo["to"], self.version) if module else None
            if not pet_data:
                self.world.log(
                    f"[!] {self.name}: evolution target '{evo['to']}' v{self.version} "
                    f"missing from {self.module}; route skipped")
                continue

            if self.stage > 0:
                if pet_data.get("special", False):
                    special_key = pet_data.get("special_key")
                    if special_key and not self.world.is_unlocked(self.module, None, special_key):
                        self.world.log(f"{self.name} cannot evolve into {evo['to']}—special evolution {special_key} is locked.")
                        continue  # Skip this evolution
                    else:
                        self.world.log("Special evolution check pass")

            return evo
        return None

    def start_poop_timer(self, module):
        """GamePet.start_poop_timer."""
        limit = int(getattr(module, "care_poop_mistake_time", 0) or 0)
        if limit > 0:
            self.poop_mistake_timers = list(getattr(self, "poop_mistake_timers", None) or []) + [limit]

    def update_poop_mistakes(self, minutes_passed):
        """GamePet.update_poop_mistakes: a poop left past the module's
        care_poop_mistake_time costs a care mistake and a point of virus."""
        timers = getattr(self, "poop_mistake_timers", None) or []
        if not timers:
            return
        self.poop_mistake_timers, expired = pet_stats.tick_poop_timers(timers, minutes_passed)
        for _ in range(expired):
            self.virus = int(getattr(self, "virus", 0) or 0) + 1
            self.add_care_mistake("poop")

    def _apply_evolution(self, evo):
        """GamePet._apply_evolution: a taken route's unlocks, then the form."""
        if "virus" in evo:
            self.virus = 0
        # Unlock evolution if present in module unlocks (new format)
        module = self.world.get_module(self.module)
        unlocks = getattr(module, "unlocks", [])
        target_stage = None
        for unlock in unlocks:
            if unlock.get("type") != "evolution":
                continue
            if unlock.get("to") and evo["to"] in unlock["to"]:
                self.world.unlock_item(self.module, "evolution", unlock["name"])
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
                self.world.unlock_item(self.module, "evolution", unlock["name"])

        if self.stage == 0 and self.shake_counter >= 99 and self.world.get_module(self.module).enable_shaken_egg:
            self.shook = True
            
        self.evolve_to(evo["to"], evo.get("version", self.version))

        # Update quest progress for normal evolution
        self.world.quest_evolution(self.module)

    def update_needs(self, minutes_passed):
        # Skip hunger/strength decay when pet should be sleeping. The Digimon
        # Twin drains Strength through the night on purpose - it is what makes
        # its wake-up training call a real mechanic - so a module can opt out.
        sleeping = self.should_sleep() or self.state == "nap"
        if sleeping and getattr(self.world.get_module(self.module),
                                'care_needs_decay_while_sleeping', False):
            sleeping = False
        # GamePet.update_needs: twice as fast after a failed evolution or at
        # Stage VI+ after 48 hours, where the module fails evolutions; Hunger
        # alone also from Age 5.
        module = self.world.get_module(self.module)
        drain = minutes_passed * evolution_rules.needs_factor(self, module)
        hunger_drain = max(drain, minutes_passed * lifespan_rules.needs_factor(self, module))

        # Hunger countdown
        if self._cd_hunger > 0 and not sleeping:
            if self.overfeed_timer == 0:
                self._cd_hunger -= hunger_drain
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
                if self.strength > 0:
                    # Above 4 falls to 4 at once, unless the module caps the
                    # meter itself (pet_stats.drained_strength, as GamePet).
                    self.strength = pet_stats.drained_strength(
                        self.strength, getattr(self.world.get_module(self.module), 'strength_max', 0))
                    if self.strength == 0:
                        # The empty-strength call costs PENGZ G-Cells (GamePet).
                        self._gcell_event("empty_strength")
                else:
                    self.debilitation_counter = getattr(self, 'debilitation_counter', 0) + 1
                self._cd_strength += self.strength_loss
        if self.overfeed_timer > 0:
            self.overfeed_timer -= 1

        self.update_99g_effect()

    def update_pooping(self, minutes_passed):
        if self.stage <= 0 or self._cd_poop <= 0:
            return
        module = self.world.get_module(self.module)
        poop_sickness_count = getattr(module, 'care_poop_sickness_count', 0)
        if poop_sickness_count > 0:
            poop_threshold = poop_sickness_count * max(1, len(self.world.pet_list) - 1)
            poop_sick = len(self.world.poop_list) >= poop_threshold and self.stage >= 2
        else:
            poop_sick = False
        if poop_sick:
            if self.poop_count_flag == 0:
                self.poop_count_flag = 1
                poop_effect = getattr(module, 'care_poop_sickness_effect', 'Skull')
                kind = ailments.kind_for_effect(poop_effect)
                if kind:
                    self.add_ailment(kind)
                self.world.log(
                    f"[!] Care sick of poop ({len(self.world.poop_list)})! Effect: {poop_effect}, "
                    f"sicknesses {self.sick_total}, injuries {self.injury_total}")
        else:
            self.poop_count_flag = 0

        depletion = minutes_passed * max(evolution_rules.poop_factor(self, module),
                                         lifespan_rules.needs_factor(self, module))
        self._cd_poop -= depletion
        if self._cd_poop <= 0:
            self.set_state("pooping")
            self._cd_poop = max(1, self.poop_timer)

    def update_care_mistakes(self):
        sound_alert = False
        sleeping = self.should_sleep() or self.state == "nap"
        module = self.world.get_module(self.module)

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
        
        # The meters' empty minutes, for the death timers: counted while
        # awake as the calls are, paused asleep, cleared once refilled.
        if self.hunger > 0:
            self.hunger_empty_minutes = 0
        elif not sleeping:
            self.hunger_empty_minutes = getattr(self, 'hunger_empty_minutes', 0) + 1
        if not self.strength_empty():
            self.strength_empty_minutes = 0
        elif not sleeping:
            self.strength_empty_minutes = getattr(self, 'strength_empty_minutes', 0) + 1

        # Sickness and injury left untreated (GamePet).
        ailments.tick_timers(self, sleeping)

        #sleep call — one care mistake a call, as hunger's (owner, 2026-10-17;
        # it repeated every care_sleep_care_mistake_timer minutes): the timer
        # stops at the threshold and starts again only when the call ends, the
        # pet going to sleep (set_state "nap") or its sleep window closing.
        if sleeping:
            if self.care_sleep_mistake_timer < module.sleep_care_mistake_timer:
                self.care_sleep_mistake_timer += 1
                if self.care_sleep_mistake_timer == module.sleep_care_mistake_timer:
                    if not self._reliability_sleep_call_resolved:
                        self._apply_reliability_event('reliability_ignoring_call')
                        self._reliability_sleep_call_resolved = True
                    self.add_care_mistake("sleep")
                    sound_alert = True
        else:
            # The window closed: the next bedtime is a new call.
            self.care_sleep_mistake_timer = 0
            self._reliability_sleep_call_resolved = False
                
        
        if sound_alert:
            self.world.sound("alarm")

    def update_vital_values_gain(self):
        """Update vital values every hour - gain if pet is healthy and well-fed"""
        if self.stage <= 0 or self.state in ("dead", "nap") or ailments.ailing(self) or self.hunger == 0 or self.strength_empty():
            return

        # only devices that show the meter earn anything, the same rule
        # Experience follows
        if not self.tracks_vital_values():
            return

        module = self.world.get_module(self.module)
        base_gain = getattr(module, 'vital_value_base', 50)  # Default to 50 if not defined

        # Calculate multiplier based on activities (base + activities)
        activity_multiplier = 1 + len(self.vital_activities)
        vital_gain = base_gain * activity_multiplier

        # The cap is per stage - a Child tops out at 4000 where an Ultimate
        # reaches 9999 - so evolving is what raises the ceiling.
        ceiling = self.vital_value_cap() or 9999
        self.vital_values = min(ceiling, self.vital_values + vital_gain)
        
        self.world.log(f"[Vital] {self.name} gained {vital_gain} vital values (activities: {len(self.vital_activities)}). Total: {self.vital_values}")
        
        # Clear activities after gaining vital values
        self.vital_activities.clear()

    def update_vital_values_loss(self):
        """Update vital values every minute - lose if pet is in poor condition"""
        if self.stage <= 0 or self.state in ("dead", "nap") or not ailments.ailing(self) and self.hunger > 0 and not self.strength_empty():
            return
            
        module = self.world.get_module(self.module)
        vital_loss = getattr(module, 'vital_value_loss', 1)  # Default to 1 if not defined
        
        # Remove from vital_values (minimum 0)
        old_vital = self.vital_values
        self.vital_values = max(0, self.vital_values - vital_loss)
        
        if old_vital != self.vital_values:
            self.world.log(f"[Vital] {self.name} lost {vital_loss} vital values (poor condition). Total: {self.vital_values}")

    def add_care_mistake(self, mistake_type):
        module = self.world.get_module(self.module)
        
        if self.use_condition_hearts:
            if self.condition_hearts > 0:
                self.condition_hearts -= 1
                self.world.log(f"[!] Care mistake ({mistake_type})! Condition hearts left: {self.condition_hearts}")
        else:
            self.mistakes += 1
            self.world.log(f"[!] Care mistake ({mistake_type})! Total: {self.mistakes}")
        
        # Remove G-Cell points for care mistake if module uses G-Cells
        # G-Cell points for a care mistake, in the module's style (GamePet)
        self._gcell_event("care_mistake")

    def need_care(self):
        return self.stage != 0 and self.state not in ("dead","nap") and (self.hunger == 0 or self.strength_empty() or ailments.ailing(self) or self.should_sleep()) 

    def call_sign(self):
        if self.stage == 0 or self.state in ("dead","nap"):
            return False
        if self.hunger == 0 and self.care_food_mistake_timer < self.world.get_module(self.module).meat_care_mistake_time:
            return True
        elif self.strength_empty() and self.care_strength_mistake_timer < self.world.get_module(self.module).protein_care_mistake_time:
            return True
        elif self.should_sleep() and self.care_sleep_mistake_timer < self.world.get_module(self.module).sleep_care_mistake_timer:
            return True
        return False

    def _grant_traited_egg(self):
        key = f"{self.module}@{self.version}"
        if key not in self.world.traited:
            self.world.traited.append(key)
            self.world.log(f"Traited Egg granted for {self.name}!")
        # GamePet._grant_traited_egg: an inherited Digitama, a generation on.
        if getattr(self.world.get_module(self.module), "traited_egg_rule", "") == "Generation":
            generations = self.world.generations
            generations[key] = max(generations.get(key, 0), (getattr(self, "generation", 1) or 1) + 1)

    def _grant_gcell_fragment(self):
        """Make the module's G-Cell Fragment egg available once.

        scene_eggselection consumes the entry when the egg is picked, so the
        player has to earn it again for the next one.
        """
        key = f"{self.module}@{self.version}"
        if not hasattr(self.world, "gcell_fragments"):
            self.world.gcell_fragments = []
        if key not in self.world.gcell_fragments:
            self.world.gcell_fragments.append(key)
            self.world.log(
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
          Generation                 stage V or higher, always; the egg hatches a
                                     generation on (the iC's inherited Digitama)
        """
        module = self.world.get_module(self.module)
        rule = getattr(module, "traited_egg_rule", "Stage V Chance")

        if rule == "None":
            return

        if rule in ("Stage V", "Generation"):
            # The Digimon Mini lays a Digitama whenever the pet reaches
            # LEVEL 5, with no roll at all; so does the Digivice iC, whose
            # inherited Digitama is a generation on ("Generation").
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
                    roll = self.world.rng.random()
                    if roll < 0.15:
                        self._grant_traited_egg()
                    elif roll < 0.30:
                        self._grant_gcell_fragment()
                elif self.world.rng.random() < 0.30:
                    self._grant_traited_egg()
            return

        if rule.startswith("Win Ratio"):
            min_stage = 4 if "Stage 4" in rule else 5
            win_ratio = (self.win * 100) // self.battles if self.battles else 0
            if rule.startswith("Win Ratio (Failed or Aged"):
                # GamePet.set_traited_egg: from a failed evolution or a Stage
                # VI+ 48 hours in its form; "..., Lifetime" (the PENGZ) reads
                # the lifetime ratio.
                if not (getattr(self, "evolution_failed", False)
                        or (self.stage >= 6 and evolution_rules.form_aged(self))):
                    return
                if "Lifetime" in rule:
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
        if not getattr(self.world.get_module(self.module), 'care_block_actions_when_sleeping', True):
            return False
        return self.state == "nap" or self.should_sleep()

    def _has_battle_resources(self):
        module = self.world.get_module(self.module)
        cost_type = getattr(module, 'battle_cost_type', 'DP')
        cost_amount = getattr(module, 'battle_cost_amount', 1.0)
        if cost_type == "Nothing":
            return True
        elif cost_type == "Hunger":
            # A hungry pet cannot battle whatever the cost (see GamePet).
            return self.hunger > 0 and self.hunger >= cost_amount
        else:  # DP
            return self.dp >= cost_amount

    def battle_block_reason(self, entering=True):
        """Why this pet cannot battle, or None when it can.

        The full set of conditions gates *entering* an area. Once a run is
        under way the pet has already committed to it, so falling sick or
        reaching its bedtime mid-area does not eject it - only running out of
        the battle cost does. Pass entering=False for that check.
        """
        module = self.world.get_module(self.module)
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
        blocked = ailments.blocks_battle(self, module)
        if blocked:
            return f"{blocked}={ailments.doses(self, blocked)}"
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

    def weight_floor(self):
        """min_weight, or 1 with care_allow_below_min_weight (GamePet)."""
        module = self.world.get_module(self.module)
        return pet_stats.weight_floor(
            getattr(self, "min_weight", 0),
            getattr(module, "care_allow_below_min_weight", False))

    def tracks_strength(self):
        """Whether this pet's device has a Strength meter at all (GamePet)."""
        module = self.world.get_module(self.module)
        return pet_stats.tracks_strength(getattr(module, "visible_stats", []))

    def strength_empty(self):
        """Strength at 0 on a device that has the meter (GamePet)."""
        return self.strength == 0 and self.tracks_strength()

    def tracks_vital_values(self):
        """Whether this pet's device has a Vital Values meter at all.

        Keyed on visible_stats, the same way Experience is, so a module that
        never shows the stat is untouched by anything built on it.
        """
        module = self.world.get_module(self.module)
        stats = [str(s).lower() for s in getattr(module, "visible_stats", []) or []]
        return any("vital" in s for s in stats)

    def vital_value_cap(self):
        """The ceiling for this pet's stage, or 0 where it earns none."""
        return self.VITAL_VALUE_CAPS.get(self.stage, 0)

    def should_sleep(self):
        if not self.sleeps or not self.wakes:
            return False
        
        # Use global sleep/wake if set
        global_sleep = getattr(self.world, "sleep_time", None)
        global_wake = getattr(self.world, "wake_time", None)

        try:
            now_time = self.world.now.time()

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
            self.world.log(f"[!] Error parsing sleep range: {e}")
            return False

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
        """GamePet._gcell_event."""
        points = gcell_rules.gain(self.world.get_module(self.module), self, event, **kwargs)
        if points:
            self.add_gcell_points(points)

    def add_gcell_points(self, points):
        """
        Adds G-Cell points, kept between 0 and the module style's cap
        (DMGZ 472; PENGZ 14 cells of the stage's size).
        Returns the actual amount added/subtracted.
        """
        actual_change = gcell_rules.add_points(self.world.get_module(self.module), self, points)
        
        if actual_change != 0:
            self.world.log(f"[G-Cell] {self.name} {'+' if actual_change > 0 else ''}{actual_change} points. Total: {self.gcell_points}")
        
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
            self.world.log(
                f"[Reliability] {self.name} {actual_change:+d}. Total: {self.reliability}")
        return actual_change

    def _apply_reliability_event(self, module_field):
        """Apply one signed Reliability delta configured by the module."""
        module = self.world.get_module(self.module)
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
