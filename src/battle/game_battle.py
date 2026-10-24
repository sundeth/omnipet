from core import constants

class GameBattle:
    def __init__(self, team1, team2, hp_buff, attack_buff, module, enemy_first=False):
        self.module = module
        self.attack_buff = attack_buff  # Attack boost for the player
        self.team1 = team1  # Player's team
        self.team2 = team2  # Enemy's team
        self.enemy_first = enemy_first  # Whether enemy attacks first (DCom battles)
        #: Replaying a finished simulation (non-DCom PvP): the simulator plays
        #: each round as two halves -- every Digimon of one side, then every
        #: one of the other -- so no lane may fire into a half before all the
        #: others have finished the one before it. Otherwise a lane running
        #: ahead can knock out a Digimon that a slower lane's log still has
        #: shooting. See _may_fire.
        self.lockstep = False
        #: Lanes the battle plays: one per player pet, or one per enemy when
        #: the other side fields more (an arena team of three against one of
        #: one or two). A lane with nobody on one side plays like a lane
        #: whose Digimon was knocked out: that side never fires.
        self.lanes = max(len(team1), len(team2))
        self._lockstep_waits = [0] * self.lanes

        self.team1_hp = [0] * len(team1)  # HP for each pet in team1
        self.team1_max_hp = [0] * len(team1)  # Max HP for team1
        self.team2_hp = [0] * self.lanes  # HP for each enemy (zero in an empty lane)
        self.team2_max_hp = [0] * len(team2)

        self.team1_total_hp = self.get_hp(team1, self.team1_hp, hp_buff)
        self.team1_max_total_hp = self.team1_total_hp  # Store max HP for team1
        self.team1_max_hp = [hp for hp in self.team1_hp]  # Max HP with buff
        self.team2_total_hp = self.get_hp(team2, self.team2_hp)
        if len(team2) == 1 and len(team1) > 1:
            # Boss Fight scalling
            self.team2_total_hp *= len(team1)
            self.team2_hp[0] = self.team2_total_hp
        self.team2_max_total_hp = self.team2_total_hp  # Store max HP for team2
        self.team2_max_hp = [hp for hp in self.team2_hp]

        self.turns = [1] * self.lanes  # Track turns for each lane

        self.team1_projectiles = [[] for _ in range(self.lanes)]  # List of projectiles for the player's team
        self.team2_projectiles = [[] for _ in range(self.lanes)]  # List of projectiles for the enemy team
        self.team1_bar_counters = [0] * len(team1)  # Bar counters for each pet in team1
        self.team2_bar_counters = [0] * len(team2)  # Bar counters for each pet in team2
        self.phase = ["pet_charge"] * self.lanes
        self.victory_status = "Ongoing"  # Track battle status
        self.winners = [None] * self.lanes  # Track winners for each pair
        self.team1_shot = [False] * self.lanes  # Track if a shot was fired
        self.team2_shot = [False] * self.lanes  # Track if a shot was fired by the enemy
        self.shot_wait = [0] * self.lanes  # Track shot wait time for each lane
        self.xp = 0
        self.bonus = 0
        self.prize_item = None  # Prize item after battle
        self.level_up = [False] * self.lanes  # Track if pets level up
        self.reset_frame_counters()
        self.reset_cooldowns()
        self.special_attack = [False] * self.lanes  # Track if pet is doing a special/critical attack
        self.special_attack_enemy = [False] * len(self.team2)  # Track if enemy is doing a special attack

    def get_hp(self, team, team_hp, buff=0):
        """
        Calculates the total HP of a team.
        """
        total_hp = 0
        for i, pet in enumerate(team):
            hp = 0
            if self.module and self.module.battle_global_hit_points > 0:
                hp = self.module.battle_global_hit_points
                if hasattr(pet, "get_hp"):
                    hp += buff
            else:
                if hasattr(pet, "get_hp"):
                    hp += pet.get_hp() + buff
                elif hasattr(pet, "hp"):
                    hp += pet.hp + buff
            team_hp[i] = hp
            total_hp += hp
        return total_hp
    
    def increment_frame_counters(self):
        """
        Increments the frame counters for each pet in the player's team.
        """
        for i in range(len(self.frame_counters)):
            self.frame_counters[i] += 1

    def _lane_count(self):
        return getattr(self, "lanes", len(self.team1))

    def _team1_hp(self, i):
        """HP of the player's Digimon in lane *i* (0 in an empty lane)."""
        return self.team1_hp[i] if i < len(self.team1_hp) else 0

    def _team2_hp(self, i):
        """HP of the enemy in lane *i* (0 in an empty lane)."""
        return self.team2_hp[i] if i < len(self.team2_hp) else 0

    def reset_frame_counters(self):
        """
        Resets the frame counters for each lane.
        """
        self.frame_counters = [0] * self._lane_count()

    def reset_cooldowns(self):
        """
        Resets the cooldowns for each lane.
        """
        self.cooldowns = [self.calculate_deterministic_cooldown(i) for i in range(self._lane_count())]

    def reset_cooldowns_staggered(self, stagger_amount=10):
        """
        Resets the cooldowns with staggering to prevent simultaneous attacks.
        Used for PvP synchronization.
        """
        base_cooldowns = [self.calculate_deterministic_cooldown(i) for i in range(self._lane_count())]
        # Add staggering based on pet index to prevent simultaneous attacks
        for i in range(len(base_cooldowns)):
            self.cooldowns[i] = base_cooldowns[i] + (i * stagger_amount)

    def calculate_deterministic_cooldown(self, pet_index):
        """
        Calculates a deterministic cooldown value based on pet name, turn, phase, and team size.
        Returns a value between 30-70 * (FRAME_RATE / 30), scaled by team size.
        """
        # Get pet name for consistency
        pet_name = ""
        pet = self.team1[pet_index] if pet_index < len(self.team1) else None
        if hasattr(pet, 'name'):
            pet_name = pet.name
        elif hasattr(pet, 'species'):
            pet_name = pet.species
        else:
            pet_name = f"pet_{pet_index}"
        
        # Get current phase for this pet
        current_phase = self.phase[pet_index] if pet_index < len(self.phase) else "pet_charge"
        current_turn = self.turns[pet_index] if pet_index < len(self.turns) else 1
        team_size = len(self.team1)
        
        # Create a deterministic seed from all variables
        seed_string = f"{pet_name}_{current_turn}_{current_phase}_{team_size}"
        
        # Simple hash function to convert string to number
        hash_value = 0
        for char in seed_string:
            hash_value = (hash_value * 31 + ord(char)) % 1000000
        
        # Base range is 30-70
        base_min = 30
        base_max = 70
        base_range = base_max - base_min
        
        # Team size scaling: smaller teams tend toward smaller numbers
        # Team size 1: bias toward lower end (30-50)
        # Team size 2-3: normal range (30-70)  
        # Team size 4+: bias toward higher end (50-70)
        if team_size == 1:
            # Scale to 30-50 range
            adjusted_min = base_min
            adjusted_max = base_min + (base_range * 0.5)
        elif team_size <= 3:
            # Normal range 30-70
            adjusted_min = base_min
            adjusted_max = base_max
        else:
            # Scale to 50-70 range for larger teams
            adjusted_min = base_min + (base_range * 0.5)
            adjusted_max = base_max
        
        # Map hash to the adjusted range
        cooldown_base = adjusted_min + (hash_value % int(adjusted_max - adjusted_min + 1))
        
        # Apply frame rate scaling
        cooldown_scaled = int(cooldown_base * (constants.FRAME_RATE / 30))
        
        return cooldown_scaled

    def decrement_cooldowns(self):
        """
        Decrements the cooldowns for each pet in the player's team.
        """
        for i in range(len(self.cooldowns)):
            if self.cooldowns[i] > 0:
                self.cooldowns[i] -= 1

    def update(self):
        """
        Updates the player's team state, including frame counters and per-pet
        cooldowns. Pre-shot pet offsets are computed at draw time directly from
        each pet's remaining cooldown by ``battle_encounter._compute_combatant_attack_anim``.
        """
        self.decrement_cooldowns()
        self.update_bar_counters()
        for i in range(self._lane_count()):
            if self.turns[i] > 12:
                self.phase[i] = "result"
                continue

            if self.phase[i] in ["result"]:
                continue

            if self.cooldowns[i] <= 0:
                if self.phase[i] == "pet_attack" and (self.shot_wait[i] or self._team1_hp(i) <= 0):
                    self.shot_wait[i] = False
                    self.phase[i] = "enemy_charge"
                    # For enemy_first mode, increment turn AFTER pet attacks (end of round)
                    if self.enemy_first:
                        self.turns[i] += 1
                        if self.turns[i] > 12:
                            self.phase[i] = "result"
                elif self.phase[i] == "pet_charge":
                    if not self._may_fire(i):
                        continue
                    self.phase[i] = "pet_attack"
                    self.team1_shot[i] = self._team1_hp(i) > 0
                elif self.phase[i] == "enemy_attack" and (self.shot_wait[i] or self._team2_hp(i) <= 0):
                    self.shot_wait[i] = False
                    self.phase[i] = "pet_charge"
                    # For normal mode (pet first), increment turn AFTER enemy attacks (end of round)
                    if not self.enemy_first:
                        self.turns[i] += 1
                        if self.turns[i] > 12:
                            self.phase[i] = "result"
                elif self.phase[i] == "enemy_charge":
                    if not self._may_fire(i):
                        continue
                    self.phase[i] = "enemy_attack"
                    self.team2_shot[i] = self._team2_hp(i) > 0

                if not self.shot_wait[i]:
                    self.cooldowns[i] = self.calculate_deterministic_cooldown(i)
                    self.frame_counters[i] = 0

    #: Frames a lockstep lane waits for the others before firing anyway, so
    #: a lane that can never finish does not hold the battle forever.
    LOCKSTEP_MAX_WAIT = 90

    def _round_half(self, i):
        """Lane *i*'s place in the battle: two halves per turn."""
        first = ("enemy_charge", "enemy_attack") if self.enemy_first else ("pet_charge", "pet_attack")
        return self.turns[i] * 2 + (0 if self.phase[i] in first else 1)

    def _may_fire(self, i):
        """Whether lane *i* may leave its charge and fire (see lockstep)."""
        if not self.lockstep:
            return True
        mine = self._round_half(i)
        behind = any(self.phase[j] != "result" and self._round_half(j) < mine
                     for j in range(self._lane_count()) if j != i)
        if behind and self._lockstep_waits[i] < self.LOCKSTEP_MAX_WAIT:
            self._lockstep_waits[i] += 1
            return False
        self._lockstep_waits[i] = 0
        return True

    def update_bar_counters(self):
        """
        Updates the bar counters for each pet in the player's team.
        """
        for i in range(len(self.team1_bar_counters)):
            if self.team1_bar_counters[i] > 0:
                self.team1_bar_counters[i] -= 1
        for i in range(len(self.team2_bar_counters)):
            if self.team2_bar_counters[i] > 0:
                self.team2_bar_counters[i] -= 1