import random
import copy

try:
    from battle_utils import (get_attack_pattern, get_dmog_pve_pattern,
                              get_penog_pattern, get_penog_enemy_pattern,
                              get_20th_enemy_pattern,
                              get_20th_single_battle_attack_pattern,
                              get_colour_pve_pattern,
                              get_penc_pattern, get_penc_enemy_pattern)
    from models import *
    import protocol_constants
except ImportError:
    # Absolute imports for direct testing
    from battle.sim.battle_utils import (get_attack_pattern, get_dmog_pve_pattern,
                                         get_penog_pattern,
                                         get_penog_enemy_pattern,
                                         get_20th_enemy_pattern,
                                         get_20th_single_battle_attack_pattern,
                                         get_colour_pve_pattern,
                              get_penc_pattern, get_penc_enemy_pattern)
    from battle.sim.models import *
    from battle.sim import protocol_constants


class GlobalBattleSimulator:
    """Stat-based team battle simulator (the "global protocol").

    Used for adventure-mode battles (parties vs enemies/bosses) and the
    arena (full party vs full party). It plays like the DMX/PENZ rules but
    with configurable damage_limit (attack limitation) and caller-supplied
    HP so each module's adventure feel can be matched. Not a wire protocol:
    nothing here is exchanged with real devices.
    """

    def __init__(self, attribute_advantage=5, damage_limit=3, force_winner=True,
                 pvp_mode=False, verbose=False, advantage_as_power=False,
                  battle_format=None, charge=0, max_hit_rate=100):
        self.attribute_advantage = attribute_advantage
        self.advantage_as_power = advantage_as_power
        self.damage_limit = damage_limit
        self.force_winner = force_winner
        self.pvp_mode = pvp_mode
        self.verbose = verbose
        #: The device line the module reproduces, if it declares one. It
        #: selects the attack table: most lines borrow the DMX one, which is
        #: what this simulator has always used, but the original Digital
        #: Monster has its own -- see _pattern_for.
        self.battle_format = battle_format
        #: Explicit internal/module ceiling; the selected pattern family
        #: cannot silently change combat probabilities.
        self.max_hit_rate = max(0, min(100, max_hit_rate))
        #: The raw meter the player actually played, for a wire that reads
        #: the number itself rather than a band. `mini_game` on each Digimon
        #: stays the 0-3 quality every other table is keyed on.
        self.charge = charge

    def _pattern_for(self, pet, is_enemy=False):
        """The attacks *pet* throws, one per round.

        A module on one of the two original lines draws from that line's own
        table rather than the DMX one. The DMX table describes a wire whose
        attacks run 1 to 5, and capping it at a limit of 2 turned almost
        every round into a 2 -- a cap is not a substitute for a table that
        only has the two values to begin with.

        The Pendulum's table is keyed on the charge, and an enemy has no
        charge to play, so an enemy reads its **stage** instead.
        """
        fmt = protocol_constants.canonical_format(self.battle_format or "")
        if fmt == "DMOG":
            # An adventure battle is fought on the module's own line, so its
            # Digimon are on the device's own 0-60 power scale.
            slot = protocol_constants.DMOG.slot_for_power(pet.power, oem=True)
            return get_dmog_pve_pattern(slot)
        if fmt == "PENOG":
            if is_enemy:
                return get_penog_enemy_pattern(getattr(pet, "stage", 1))
            return get_penog_pattern(self.charge)
        if fmt == "PENC":
            # **A Pendulum Color plays a charge and a Digital Monster Color
            # does not**, which is why the two share this wire and not this
            # table. Its manual keys the whole battle on the charge -- "you
            # begin each battle by shaking to get a specific color, just as
            # you do in Training" -- and the device's own rows are keyed on
            # the attacker's STAGE and the colour band that charge landed,
            # measured for all seven stages. A quest battle is the same
            # battle, so it reads the same table. An enemy has no charge and
            # reads its stage alone.
            if is_enemy:
                return get_penc_enemy_pattern(getattr(pet, "stage", 1))
            return get_penc_pattern(getattr(pet, "stage", 1), self.charge)
        if fmt == "DMXW":
            # The third Colour line, and the second that fights. Its charge
            # is Excite training's bar rather than Count Match Color, and
            # its rows are keyed on the stage as well as that band -- a
            # Shoutmon and its Xros evolution throw different ones.
            from battle.sim.battle_utils import (get_dmxw_pattern,
                                                 get_dmxw_enemy_pattern)
            if is_enemy:
                return get_dmxw_enemy_pattern(getattr(pet, "stage", 3))
            return get_dmxw_pattern(getattr(pet, "stage", 3), self.charge,
                                    getattr(pet, "effort", 0))
        if fmt == "DMC":
            # The Colour wire exchanges a verdict, so this table is only ever
            # reached by an adventure or arena battle -- and it exists so
            # those stop drawing the DMX's 1-to-5 values and clamping them
            # flat at 2. Keyed on the attacker's own stage and effort, which
            # an enemy answers too: it has a stage and no effort at all, so
            # it reads the 0-heart row without needing a table of its own.
            # The DMC has no charge to key on: its `battle_minigame` is
            # "None", which scores a flat 2 every battle.
            return get_colour_pve_pattern(getattr(pet, "stage", 1),
                                          getattr(pet, "effort", 0))
        if fmt in ("DM20", "PEN20"):
            # Each line's own measured table, indexed by the tap meter -- they
            # are different tables, sharing only their four attacks. An
            # adventure enemy plays no minigame, so it reads its stage the way
            # a PENOG enemy does.
            if is_enemy:
                return get_20th_enemy_pattern(getattr(pet, "stage", 1), fmt)
            return get_20th_single_battle_attack_pattern(self.charge, fmt)
        # The DMX chooses its row from the stage first and the level
        # second, so an adventure battle on that line has to say which.
        # **The line has to be named.** Omitting it took the default 'DMX',
        # so a Pendulum Z adventure battle drew the DMX's rows -- the two
        # tables are deliberately separate and share only their shape.
        return get_attack_pattern(pet.level, pet.mini_game, protocol=fmt,
                                  stage=getattr(pet, "stage", None))

    def _attribute_advantage(self, att_attr, def_attr):
        # Vaccine > Virus > Data > Vaccine
        if att_attr == "Va":
            if def_attr == "Da":
                return -self.attribute_advantage
            elif def_attr == "Vi":
                return self.attribute_advantage
        elif att_attr == "Da":
            if def_attr == "Va":
                return self.attribute_advantage
            elif def_attr == "Vi":
                return -self.attribute_advantage
        elif att_attr == "Vi":
            if def_attr == "Va":
                return -self.attribute_advantage
            elif def_attr == "Da":
                return self.attribute_advantage
        return 0

    def _hitrate(self, pet, target):
        """Chance for pet to land a hit on target, as a percentage.

        By default the attribute advantage is a flat percentage added to the
        hit rate. With advantage_as_power it is folded into the attacker's
        Power before the ratio is taken instead, which is how the Digital
        Monster X describes it (+32 Power rather than +N% to hit).

        **The handicap belongs to the Digimon being attacked.** "handicap --
        Used in Quest Mode only, certain Digimon have a handicap that will
        reduce your hitrate", and humulos' own calculator names the field
        `enemyHandicap` and subtracts it from the player's roll. Quest Mode
        is Adventure Mode here, which is why this is the only hit rate in the
        game that reads one: `battle_encounter` gives the player 0 and each
        enemy its own.

        It used to subtract `pet.handicap` -- the ATTACKER's -- which put it
        on the wrong side twice over. A handicapped enemy never made itself
        harder to hit and instead made itself less accurate, so the 51
        PENC quest enemies that carry one were easier on both halves of every
        round. SymbareAngoramon is the shape of it: power 60 with a handicap
        of 20, a Digimon the device made hard by the handicap and not by the
        power, and against a 150-power Adult the player's chance was reading
        71% where the device gives 51%.
        """
        adv = self._attribute_advantage(pet.attribute, target.attribute)
        power, other = pet.power, target.power
        if self.advantage_as_power:
            # **The bonus goes to the side that HAS the advantage.** The
            # module's wording is "+N to your Digimon's Power stat", so a
            # disadvantaged attacker is not penalised -- its opponent is
            # credited, and the ratio moves once rather than twice.
            #
            # Adding a negative advantage to our own power made the two sides
            # asymmetric: at power 20 each with a module advantage of 32, the
            # disadvantaged attacker read **0%** where its opponent read
            # 72.22%. Crediting the opponent instead gives 27.78% and 72.22%,
            # which are the two halves of one ratio. This is the same slip
            # `protocol_constants.hit_rate` carries a note about; the two are
            # separate copies because one is the module's rule and the other
            # the device's.
            if adv > 0:
                power = max(0, power + adv)
            elif adv < 0:
                other = max(0, other - adv)
            adv = 0
        total = power + other
        rate = ((power * 100) / total if total else 0) + adv - target.handicap
        return max(0, min(rate, self.max_hit_rate))

    def simulate(self, device1, device2):
        # Deep copy the teams to avoid modifying the original objects
        device1 = [copy.deepcopy(p) for p in device1]
        device2 = [copy.deepcopy(p) for p in device2]

        # Initialize Digimon states
        for pet in device1 + device2:
            pet.alive = True
            pet.current_hp = pet.hp
            pet.log = []

        # Generate attack patterns. device2 is the enemy side in an
        # adventure battle and a second player team in the arena, where both
        # sides have played their own charge.
        for pet in device1:
            pet.attack_pattern = (self._pattern_for(pet) * 2)[:12]
        for pet in device2:
            pattern = self._pattern_for(pet, is_enemy=not self.pvp_mode)
            pet.attack_pattern = (pattern * 2)[:12]

        rounds = 12
        battle_log = []

        for turn in range(rounds):
            turn_attacks = []

            # Team 1 attacks
            for i, pet in enumerate(device1):
                if not pet.alive:
                    continue

                # Try to attack the opposite Digimon by index
                if i < len(device2) and device2[i].alive:
                    target = device2[i]
                else:
                    # If the opposite is dead, pick the next available target
                    targets = [t for t in device2 if t.alive]
                    if not targets:
                        break
                    target = random.choice(targets)  # Pick the first available target

                # Calculate attack
                pattern = pet.attack_pattern
                base_dmg = min(pattern[turn % len(pattern)], self.damage_limit)
                dmg = max(0, base_dmg + pet.buff)
                hitrate = self._hitrate(pet, target)
                hit = random.randint(0, 99) < hitrate
                actual_dmg = dmg if hit else 0
                target.current_hp -= actual_dmg
                if target.current_hp <= 0:
                    target.alive = False
                    target.current_hp = 0
                turn_attacks.append(AttackLog(
                    turn=turn + 1,
                    device="device1",
                    attacker=i,
                    defender=device2.index(target),
                    hit=hit,
                    # The pattern value, always -- it is what the encounter
                    # counts projectiles from, so a missed strong shot still
                    # draws as a strong shot and a buff does not add sprites.
                    # The HP it really costs rides in hp_damage.
                    damage=base_dmg,
                    hp_damage=actual_dmg,
                    # Crit fires on the highest base damage the pattern can roll
                    # (pre-buff/level) so cosmetic damage stacking doesn't change
                    # which attacks trigger the slide-in.
                    critical=(base_dmg == 5),
                ))

            # Team 2 attacks (boss logic included)
            for i, pet in enumerate(device2):
                if not pet.alive:
                    continue

                # If this is a boss (team2 has only one member), attack all alive members of team1
                if len(device2) == 1 and not self.pvp_mode:
                    for target in [t for t in device1 if t.alive]:  # Filter only alive pets
                        pattern = pet.attack_pattern
                        base_dmg = min(pattern[turn % len(pattern)], self.damage_limit)
                        dmg = max(0, base_dmg + pet.buff)
                        hitrate = self._hitrate(pet, target)
                        hit = random.randint(0, 99) < hitrate
                        actual_dmg = dmg if hit else 0
                        target.current_hp -= actual_dmg
                        if target.current_hp <= 0:
                            target.alive = False
                            target.current_hp = 0
                        turn_attacks.append(AttackLog(
                            turn=turn + 1,
                            device="device2",
                            attacker=i,
                            defender=device1.index(target),
                            hit=hit,
                            damage=base_dmg,
                            hp_damage=actual_dmg,
                            critical=(base_dmg == 5),
                        ))
                else:
                    # Regular attack logic for non-boss enemies
                    if i < len(device1) and device1[i].alive:
                        target = device1[i]
                    else:
                        # If the opposite is dead, pick the next available target
                        targets = [t for t in device1 if t.alive]
                        if not targets:
                            break
                        target = random.choice(targets)  # Pick the first available target

                    # Calculate attack
                    pattern = pet.attack_pattern
                    base_dmg = min(pattern[turn % len(pattern)], self.damage_limit)
                    dmg = max(0, base_dmg + pet.buff)
                    hitrate = self._hitrate(pet, target)
                    hit = random.randint(0, 99) < hitrate
                    actual_dmg = dmg if hit else 0
                    target.current_hp -= actual_dmg
                    if target.current_hp <= 0:
                        target.alive = False
                        target.current_hp = 0
                    turn_attacks.append(AttackLog(
                        turn=turn + 1,
                        device="device2",
                        attacker=i,
                        defender=device1.index(target),
                        hit=hit,
                        damage=base_dmg,
                        hp_damage=actual_dmg,
                        critical=(base_dmg == 5),
                    ))

            # Log the state for this turn
            battle_log.append(TurnLog(
                turn=turn + 1,
                device1_status=[
                    DigimonStatus(name=p.name, hp=p.current_hp, alive=p.alive) for p in device1
                ],
                device2_status=[
                    DigimonStatus(name=p.name, hp=p.current_hp, alive=p.alive) for p in device2
                ],
                attacks=turn_attacks
            ))

            # Check for wipeout
            device1_alive = any(p.alive for p in device1)
            device2_alive = any(p.alive for p in device2)
            if not device1_alive or not device2_alive:
                break

        # Determine winner
        device1_alive = any(p.alive for p in device1)
        device2_alive = any(p.alive for p in device2)
        if device1_alive and not device2_alive:
            winner = "device1"
        elif not device1_alive and device2_alive:
            winner = "device2"
        else:
            # No wipeout, compare remaining HP
            team1_hp = sum(p.current_hp for p in device1 if p.alive)
            team2_hp = sum(p.current_hp for p in device2 if p.alive)
            if team1_hp > team2_hp:
                winner = "device1"
            elif team2_hp > team1_hp:
                winner = "device2"
            else:
                winner = random.choice(("device1", "device2")) if self.force_winner else "draw"

        # Prepare final result
        result =  BattleResult(
            winner=winner,
            device1_final=[
                DigimonStatus(name=p.name, hp=p.current_hp, alive=p.alive) for p in device1
            ],
            device2_final=[
                DigimonStatus(name=p.name, hp=p.current_hp, alive=p.alive) for p in device2
            ],
            battle_log=battle_log,
            device1_packets=[],
            device2_packets=[]
        )
        if self.verbose:
            self.print_battle_log(result)
        return result

    def print_battle_log(self, result):
        # Generate a detailed battle log
        print(f"Winner: {result.winner}")

        # Print final states of both devices
        print("Device 1:")
        for i, status in enumerate(result.device1_final):
            print(f"  {i}: {status.name} (HP: {status.hp}, Alive: {status.alive})")
        print("Device 2:")
        for i, status in enumerate(result.device2_final):
            print(f"  {i}: {status.name} (HP: {status.hp}, Alive: {status.alive})")
        print()

        # Iterate through the battle log
        for turn_data in result.battle_log:
            print(f"Turn {turn_data.turn}")

            # Device 1 attacks
            print(" Device 1 attacks:")
            for attack in turn_data.attacks:
                if attack.device == "device1":
                    attacker_name = result.device1_final[attack.attacker].name
                    defender_name = result.device2_final[attack.defender].name if attack.defender >= 0 else "?"
                    print(f"   {attacker_name} -> {defender_name}: hit={attack.hit} dmg={attack.damage} crit={attack.critical}")

            # Device 2 attacks
            print(" Device 2 attacks:")
            for attack in turn_data.attacks:
                if attack.device == "device2":
                    attacker_name = result.device2_final[attack.attacker].name
                    defender_name = result.device1_final[attack.defender].name if attack.defender >= 0 else "?"
                    print(f"   {attacker_name} -> {defender_name}: hit={attack.hit} dmg={attack.damage} crit={attack.critical}")

            # Print status of both devices
            device1_status = [f"{status.name}({status.hp})" for status in turn_data.device1_status]
            device2_status = [f"{status.name}({status.hp})" for status in turn_data.device2_status]
            print(f" Device 1 status: {device1_status}")
            print(f" Device 2 status: {device2_status}")
            print()

        # Print exchanged packet data
        print("Exchanged Packet Data:")
        print("Device 1 Packets:")
        for i, packets in enumerate(result.device1_packets):
            for packet in packets:
                binary = " ".join(f"{byte:08b}" for byte in packet)
                hex_representation = " ".join(f"{byte:02X}" for byte in packet)
                print(f"  Packet {i + 1}:")
                print(f"    Binary: {binary}")
                print(f"    Hex: {hex_representation}")

        print("Device 2 Packets:")
        for i, packets in enumerate(result.device2_packets):
            for packet in packets:
                binary = " ".join(f"{byte:08b}" for byte in packet)
                hex_representation = " ".join(f"{byte:02X}" for byte in packet)
                print(f"  Packet {i + 1}:")
                print(f"    Binary: {binary}")
                print(f"    Hex: {hex_representation}")

if __name__ == "__main__":
    # Example 1: 4x4 party battle
    device1 = [
        Digimon(name="Agumon", hp=10, attribute="Va", power=120, handicap=0, buff=0, mini_game=2, level=3, sick=0, shot1=1, shot2=1, order=0, traited=0, egg_shake=0, index=0, stage=3),
        Digimon(name="Gabumon", hp=10, attribute="Da", power=110, handicap=0, buff=1, mini_game=3, level=3, sick=0, shot1=1, shot2=1, order=1, traited=0, egg_shake=0, index=1, stage=3),
        Digimon(name="Patamon", hp=10, attribute="Va", power=100, handicap=0, buff=0, mini_game=1, level=3, sick=0, shot1=1, shot2=1, order=2, traited=0, egg_shake=0, index=2, stage=3),
        Digimon(name="Tentomon", hp=10, attribute="Vi", power=105, handicap=0, buff=0, mini_game=2, level=3, sick=0, shot1=1, shot2=1, order=3, traited=0, egg_shake=0, index=3, stage=3),
    ]
    device2 = [
        Digimon(name="Impmon", hp=10, attribute="Vi", power=115, handicap=0, buff=0, mini_game=2, level=3, sick=0, shot1=1, shot2=1, order=0, traited=0, egg_shake=0, index=0, stage=3),
        Digimon(name="Wormmon", hp=10, attribute="Da", power=108, handicap=0, buff=1, mini_game=3, level=3, sick=0, shot1=1, shot2=1, order=1, traited=0, egg_shake=0, index=1, stage=3),
        Digimon(name="Gomamon", hp=10, attribute="Va", power=102, handicap=0, buff=0, mini_game=1, level=3, sick=0, shot1=1, shot2=1, order=2, traited=0, egg_shake=0, index=2, stage=3),
        Digimon(name="Palmon", hp=10, attribute="Da", power=104, handicap=0, buff=0, mini_game=2, level=3, sick=0, shot1=1, shot2=1, order=3, traited=0, egg_shake=0, index=3, stage=3),
    ]

    sim = GlobalBattleSimulator(attribute_advantage=5, damage_limit=3)
    result = sim.simulate(device1, device2)
