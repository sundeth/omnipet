# core/combat/battle_encounter_dcom.py

"""
BattleEncounterDCom - DCom-specific battle logic
Extends BattleEncounter to handle real physical device battles via serial connection.
"""

import pygame
import traceback
from typing import Optional
from battle.battle_encounter import BattleEncounter
from battle.game_battle import GameBattle
from battle.dcom.dcom_dialog import DComDialog
from battle.dcom.dcom_controller import DComController
from battle.dcom.dcom_protocol import ProtocolType
from battle.sim.models import Digimon, BattleResult
from battle.sim.dcom_battle_simulator import DComBattleSimulator, pet_to_digimon
from battle.sim import protocol_constants
from core import runtime_globals
from battle.combat_constants import ANY_OTHER_DEVICE


class BattleEncounterDCom(BattleEncounter):
    """
    BattleEncounter subclass for handling DCom device battles.
    Manages serial communication, packet exchange, and battle simulation with real devices.
    """

    def __init__(self, module, dcom_controller=None, dcom_protocol=None, area=0, round=0, version=1):
        """
        Initialize DCom battle encounter.
        
        Args:
            module: Game module name
            dcom_controller: Optional DComController instance (will create if None)
            dcom_protocol: Optional ProtocolType (will prompt if None)
            area: Battle area
            round: Battle round
            version: Battle version
        """
        # Initialize parent with pvp_mode=True since DCom is a 1v1 battle
        super().__init__(module, area, round, version, pvp_mode=True)
        
        # DCom-specific initialization
        self.dcom_controller: Optional[DComController] = dcom_controller
        self.dcom_protocol: Optional[ProtocolType] = dcom_protocol
        self.dcom_mode = True  # Flag to indicate this is a DCom battle
        self.enemy_first = True  # Enemy (device2) attacks first in DCom V2 protocol
        self.dcom_simulator: Optional[DComBattleSimulator] = None
        self.dcom_battle_result: Optional[BattleResult] = None
        self.dcom_button_rect = None  # Will be set in draw phase
        self.global_battle_log = None  # Initialize to None, will be set after simulation
        
        # Set turn limit based on protocol (DM20 has 5 attacks)
        # Default to 5 for V_PET protocol, can be overridden in _setup_simulator
        self.turn_limit = 5
        
        # Initialize DCom dialog if no controller provided
        self.dcom_dialog = None
        self._setup_simulator()
            
        runtime_globals.game_console.log("[BattleEncounterDCom] Initialized DCom battle encounter")

    def _on_dcom_connected(self, controller: DComController, protocol: ProtocolType):
        """
        Callback when DCom device is connected and protocol selected.
        """
        self.dcom_controller = controller
        self.dcom_protocol = protocol
        self.dcom_mode = True
        
        runtime_globals.game_console.log(f"[BattleEncounterDCom] DCom connected with protocol: {protocol.display_name}")
        
        # Setup simulator now that we have controller and protocol
        self._setup_simulator()
    
    def _setup_simulator(self):
        """Initialize the DCom battle simulator."""
        # The connection view normally finishes the exchange before this scene
        # opens; it leaves the battle format (and the controller, if it is
        # still connected) in pvp_battle_data.
        pvp_data = getattr(runtime_globals, 'pvp_battle_data', None) or {}
        if isinstance(pvp_data, dict):
            if not self.dcom_controller:
                self.dcom_controller = pvp_data.get('dcom_controller')
                self.dcom_protocol = pvp_data.get('dcom_protocol')
            self.battle_format = pvp_data.get('battle_format')
        else:
            self.battle_format = None

        if self.dcom_controller:
            self.dcom_simulator = DComBattleSimulator(
                self.dcom_controller, self.dcom_protocol, self.battle_format)
            runtime_globals.game_console.log(
                f"[BattleEncounterDCom] Simulator ready for {self.dcom_simulator.battle_format}")
        else:
            runtime_globals.game_console.log(
                "[BattleEncounterDCom] No live connection; replaying the exchange "
                "the connection view already made")

    def adopt_battle_result(self, result):
        """Take a battle the connection view already fought.

        The result is kept exactly as the exchange produced it -- device1 the
        opponent, device2 us, the order the packets went in. The animation
        already reads it that way: ``draw_pets`` and ``draw_enemies`` pick
        their device label off ``is_dcom_mode``, which the scene sets before
        calling this. Remapping here as well swapped the sides twice and put
        every hit on the wrong pet.

        (The live-controller path in calculate_combat_for_pairs does remap,
        because nothing sets is_dcom_mode there.)
        """
        self.dcom_battle_result = result
        self.global_battle_log = result
        self.victory_status = "Victory" if result.winner == "device2" else "Defeat"
        runtime_globals.game_console.log(
            f"[BattleEncounterDCom] Adopted the exchange: {self.victory_status}, "
            f"{len(self.global_battle_log.battle_log)} turn(s)")
        return self.global_battle_log

    def apply_exchange_hp(self, player_hp, enemy_hp):
        """Force the HP the exchange agreed on.

        A DCom battle's HP belongs to the protocol -- 5 on the DM20 and PEN20
        wires, and whatever the two devices announced in their packets on the
        DMX one. GameBattle otherwise fills it in from the pet's module, and
        ``battle_global_hit_points`` is an adventure-battle setting: a DMC pet
        was arriving with 4 HP for a fight both sides had agreed was 10, so
        the first hit ended it.
        """
        if not self.battle_player:
            return
        player_hp = max(1, int(player_hp or 1))
        enemy_hp = max(1, int(enemy_hp or 1))

        for i in range(len(self.battle_player.team1_hp)):
            self.battle_player.team1_hp[i] = player_hp
            self.battle_player.team1_max_hp[i] = player_hp
        for i in range(len(self.battle_player.team2_hp)):
            self.battle_player.team2_hp[i] = enemy_hp
            self.battle_player.team2_max_hp[i] = enemy_hp

        self.battle_player.team1_total_hp = player_hp * len(self.battle_player.team1_hp)
        self.battle_player.team1_max_total_hp = self.battle_player.team1_total_hp
        self.battle_player.team2_total_hp = enemy_hp * len(self.battle_player.team2_hp)
        self.battle_player.team2_max_total_hp = self.battle_player.team2_total_hp

        if getattr(self, 'hp_bar', None):
            self.hp_bar.set_totals(self.battle_player.team2_total_hp,
                                   self.battle_player.team1_total_hp)
            self.hp_bar.set_values(self.battle_player.team2_total_hp,
                                   self.battle_player.team1_total_hp)

        runtime_globals.game_console.log(
            f"[BattleEncounterDCom] HP from the exchange: player {player_hp}, "
            f"opponent {enemy_hp}")

    def calculate_combat_for_pairs(self):
        """
        Run the DCom exchange, or replay the one already made.

        The connection view does the exchange itself so the serial wait does
        not block the game loop, and hands the finished log to this scene; in
        that case there is nothing left to do here. A live controller (the
        in-battle DCom dialog) still runs the exchange from here.
        """
        if self.global_battle_log is not None:
            runtime_globals.game_console.log(
                "[BattleEncounterDCom] Using the battle log from the exchange")
            return

        runtime_globals.game_console.log("[BattleEncounterDCom] Starting DCom battle...")

        if not self.dcom_simulator:
            runtime_globals.game_console.log("[BattleEncounterDCom] ERROR: No simulator available")
            self.victory_status = "Error"
            return

        # Get player's Digimon data
        player_digimon = self._get_player_digimon()
        if not player_digimon:
            runtime_globals.game_console.log("[BattleEncounterDCom] ERROR: Could not create player Digimon")
            return
        
        # Run battle simulation with physical device
        # This sends packets, waits for response, parses opponent, and returns BattleResult
        runtime_globals.game_console.log("[BattleEncounterDCom] Calling simulator.simulate_with_device()...")
        self.dcom_battle_result = self.dcom_simulator.simulate_with_device(player_digimon)
        
        if self.dcom_battle_result:
            runtime_globals.game_console.log("[BattleEncounterDCom] Simulation returned result!")
            # Remap the battle log to swap device labels to match BattleEncounter convention
            # DCom simulator uses: device1=opponent, device2=player
            # BattleEncounter uses: device1=team1=player, device2=team2=enemy
            self.global_battle_log = self._remap_battle_result(self.dcom_battle_result)
            # In DCom simulator: device1=opponent (DCom), device2=player (our pet)
            # So winner=="device2" means WE won
            self.victory_status = "Victory" if self.dcom_battle_result.winner == "device2" else "Defeat"
            runtime_globals.game_console.log(f"[BattleEncounterDCom] Battle complete: {self.victory_status}")
            runtime_globals.game_console.log(f"[BattleEncounterDCom] Battle log has {len(self.global_battle_log.battle_log)} turns")
            runtime_globals.game_console.log(f"[BattleEncounterDCom] Battle result object: {self.dcom_battle_result}")
            runtime_globals.game_console.log(f"[BattleEncounterDCom] global_battle_log is: {self.global_battle_log}")
            
            # Now that we have opponent data from the device, set up battle teams properly
            # This is needed for animations and result processing
            self._setup_teams_from_battle_result()
            
            # Process battle results (updates HP, etc.)
            self.process_battle_results()
        else:
            runtime_globals.game_console.log("[BattleEncounterDCom] Battle simulation failed")
            self.victory_status = "Error"
    
    def _remap_battle_result(self, result: BattleResult) -> BattleResult:
        """
        Remap battle result to swap device labels to match BattleEncounter convention.
        
        DCom simulator uses: device1=opponent (DCom device), device2=player (our pet)
        BattleEncounter uses: device1=team1=player, device2=team2=enemy
        
        This method creates a new BattleResult with swapped device labels so the
        animations in draw_pets() and draw_enemies() work correctly.
        """
        from battle.sim.models import BattleResult, TurnLog, AttackLog, DigimonStatus
        
        remapped_log = []
        for turn_log in result.battle_log:
            # Swap device1_status and device2_status
            # Original: device1=opponent, device2=player
            # New: device1=player, device2=opponent
            remapped_attacks = []
            for attack in turn_log.attacks:
                # Swap device labels
                new_device = "device2" if attack.device == "device1" else "device1"
                remapped_attacks.append(AttackLog(
                    turn=attack.turn,
                    device=new_device,
                    attacker=attack.attacker,
                    defender=attack.defender,
                    hit=attack.hit,
                    damage=attack.damage,
                    # AttackLog.critical has no default: leaving it off here
                    # raised a TypeError the moment a DCom battle was remapped.
                    critical=attack.critical,
                ))
            
            remapped_turn = TurnLog(
                turn=turn_log.turn,
                device1_status=turn_log.device2_status,  # Player becomes device1
                device2_status=turn_log.device1_status,  # Opponent becomes device2
                attacks=remapped_attacks
            )
            remapped_log.append(remapped_turn)
        
        # Swap winner label
        new_winner = "device1" if result.winner == "device2" else "device2"
        
        remapped_result = BattleResult(
            winner=new_winner,
            device1_final=result.device2_final,  # Player becomes device1  
            device2_final=result.device1_final,  # Opponent becomes device2
            battle_log=remapped_log,
            device1_packets=result.device2_packets,
            device2_packets=result.device1_packets
        )
        
        runtime_globals.game_console.log(f"[BattleEncounterDCom] Remapped battle log: winner={new_winner}")
        return remapped_result

    def _get_player_digimon(self) -> Optional[Digimon]:
        """The packet payload for the pet fighting this battle.

        Built by the shared ``pet_to_digimon``, so this path and the
        connection view send a real device identical bytes for the same pet.
        """
        if not self.battle_player or not self.battle_player.teams[1]:
            runtime_globals.game_console.log("[BattleEncounterDCom] No player team available")
            return None

        first_pet = self.battle_player.teams[1][0]
        battle_format = self.dcom_simulator.battle_format if self.dcom_simulator else 'DM20'
        return pet_to_digimon(first_pet, battle_format,
                              self.get_minigame_strength())

    def _setup_teams_from_battle_result(self):
        """
        Set up battle teams after getting opponent data from device.
        This creates proper GameEnemy objects for animations.
        
        IMPORTANT: In DCom simulator, device1=opponent (DCom device), device2=player (our pet)
        In BattleEncounter, team1=player pets, team2=enemies
        So we need to swap: device1_final -> team2 (enemies), device2_final -> team1 (our pets)
        """
        if not self.dcom_battle_result or not self.battle_player:
            runtime_globals.game_console.log("[BattleEncounterDCom] Cannot setup teams: no result or battle_player")
            return
        
        from models.game_enemy import GameEnemy
        
        # Get opponent data from battle result (device1 = opponent in DCom simulator)
        opponent_status = self.dcom_battle_result.device1_final[0]
        
        # Use parsed opponent Digimon data if available (has actual attribute, shots, stage, etc.)
        opp = getattr(self.dcom_simulator, 'opponent_digimon', None)
        
        # Map attribute integer to string for GameEnemy
        attr_int_to_str = {0: "Va", 1: "Da", 2: "Vi", 3: "Fr"}
        opp_attribute = attr_int_to_str.get(opp.attribute, "Va") if opp else "Va"
        
        # Create enemy object from opponent data. The shot ids are already
        # 1-based here -- parse_opponent shifts them off the 0-based wire on
        # the way in, so shifting again would point at the next sprite.
        enemy = GameEnemy(
            name=opponent_status.name,
            power=opp.power if opp else 1,
            attribute=opp_attribute,
            area=0,
            round=0,
            version=opp.version if opp and hasattr(opp, 'version') else 1,
            atk_main=opp.shot1 if opp else 1,
            atk_alt=opp.shot2 if opp else 1,
            atk_alt_2=0,
            handicap=0,
            id=opp.index if opp else 0,
            stage=opp.stage if opp else 3,
            hp=opponent_status.hp,
            unlock="",
            prize="",
            mini_game=opp.mini_game if opp and hasattr(opp, 'mini_game') else 3
        )
        
        # Set additional properties
        enemy.level = opp.level if opp else 1
        enemy.sick = opp.sick if opp else 0
        enemy.traited = bool(opp.traited) if opp else False
        enemy.shook = bool(opp.egg_shake) if opp else False
        enemy.module = self.module.name

        # Load sprite for the enemy
        enemy.load_sprite(enemy.module, boss=False)
        
        # Update battle_player teams
        my_pets = self.battle_player.teams[1]  # Keep existing player pets
        self.battle_player = GameBattle(my_pets, [enemy], 0, 0, self.module)
        self.enemies = [enemy]
        
        # Override HP with the wire's. GameBattle computes it from the pet
        # objects, but a connection battle is fought with the HP the two
        # devices agreed on -- see DComBattleSimulator.get_initial_hp.
        fixed_hp = (self.dcom_simulator.get_initial_hp()
                    if self.dcom_simulator else protocol_constants.DM20.FIXED_HP)
        for i in range(len(self.battle_player.team1_hp)):
            self.battle_player.team1_hp[i] = fixed_hp
            self.battle_player.team1_max_hp[i] = fixed_hp
        for i in range(len(self.battle_player.team2_hp)):
            self.battle_player.team2_hp[i] = fixed_hp
            self.battle_player.team2_max_hp[i] = fixed_hp
        self.battle_player.team1_total_hp = fixed_hp * len(my_pets)
        self.battle_player.team1_max_total_hp = self.battle_player.team1_total_hp
        self.battle_player.team2_total_hp = fixed_hp * len([enemy])
        self.battle_player.team2_max_total_hp = self.battle_player.team2_total_hp
        
        # Update HP bar with correct fixed HP values
        if hasattr(self, 'hp_bar') and self.hp_bar:
            # HPBar: set_totals(enemy_total, player_total) and set_values(enemy_hp, player_hp)
            self.hp_bar.set_totals(self.battle_player.team2_total_hp, self.battle_player.team1_total_hp)
            self.hp_bar.set_values(self.battle_player.team2_total_hp, self.battle_player.team1_total_hp)

        # DCom battles always have enemy attacking first
        self.prime_enemy_first()
        
        runtime_globals.game_console.log(f"[BattleEncounterDCom] Teams set up: player={my_pets[0].name}, opponent={enemy.name}")
    
    def update_result(self):
        """
        Override result handling for DCom battles.
        Extends the parent PvP unlock logic with OEM-specific unlocks:
        - versus: triggered by any OEM DCom battle
        - battle: triggered by OEM DCom victories (increments total_victories)
        - pvp: handled by parent logic (pvp_wins counter)
        """
        from core import game_globals, constants
        from utils.utils_unlocks import unlock_item
        
        # Same timer logic as parent
        if self.result_timer == 0 and not self._has_result_rewards():
            self.result_timer = int(120 * (constants.FRAME_RATE / 30))
        
        self.result_timer += 1
        
        if self.result_timer < int(120 * (constants.FRAME_RATE / 30)):
            return
        
        # Play appropriate sound
        runtime_globals.game_sound.play("happy" if self.victory_status == "Victory" else "fail")
        
        # Update PvP counters (same as parent)
        for i, pet in enumerate(self.battle_player.team1):
            try:
                pet.pvp_battles += 1
                # Charge the module's battle cost (the parent PvP path does
                # this too; the override was skipping it, making DCom free)
                pet._deduct_battle_cost()
                if hasattr(self.battle_player, 'winners') and i < len(self.battle_player.winners):
                    winner = self.battle_player.winners[i]
                    local_won = (winner == 'team1') or (self.victory_status == 'Victory')
                else:
                    local_won = (self.victory_status == 'Victory')
                if local_won:
                    pet.pvp_wins += 1
                runtime_globals.game_console.log(f"[PvP] Pet {getattr(pet,'name',i)} pvp_battles={pet.pvp_battles} pvp_wins={pet.pvp_wins}")
            except Exception as e:
                runtime_globals.game_console.log(f"[PvP] Error updating pet PvP counters: {e}")
        
        # PvP-type unlocks (same as parent)
        try:
            module_unlocks = getattr(self.module, 'unlocks', []) or []
            for unlock in module_unlocks:
                if unlock.get('type') == 'pvp':
                    req = unlock.get('amount', None)
                    name = unlock.get('name')
                    if req is None or not name:
                        continue
                    for pet in self.battle_player.team1:
                        if getattr(pet, 'pvp_wins', 0) >= int(req):
                            unlock_item(self.module.name, 'pvp', name)
                            break
        except Exception as e:
            runtime_globals.game_console.log(f"[PvP] Error processing PvP unlocks: {e}")
        
        # OEM-specific unlocks: versus, battle
        if getattr(self, 'is_oem_mode', False):
            try:
                module_unlocks = getattr(self.module, 'unlocks', []) or []
                
                # Versus-type unlocks: triggered by any OEM DCom battle
                for unlock in module_unlocks:
                    if unlock.get('type') == 'versus':
                        name = unlock.get('name')
                        if name:
                            ver_req = unlock.get('version', None)
                            dev_req = unlock.get('device_version', None)
                            opp_req = unlock.get('opponent_device_version', None)
                            pet = self.battle_player.team1[0] if self.battle_player.team1 else None
                            pet_version = getattr(pet, 'version', 0) if pet else 0
                            # The hardware the pet was hatched on, and what the
                            # other device announced in its battle packets.
                            dev = getattr(pet, 'device_version', pet_version) if pet else 0
                            # The connection view runs the exchange, so the
                            # version the toy announced arrives with the
                            # battle data rather than off a live simulator.
                            opp = getattr(self.dcom_simulator, 'opponent_device_version', None)
                            if opp is None:
                                pvp_data = getattr(runtime_globals, 'pvp_battle_data', None) or {}
                                opp = pvp_data.get('opponent_device_version')

                            if dev_req is not None or opp_req is not None:
                                # ANY_OTHER_DEVICE means "any device that is not
                                # this one" - see battle_encounter_versus.
                                if opp_req == ANY_OTHER_DEVICE:
                                    opponent_ok = opp is not None and opp != dev
                                else:
                                    opponent_ok = opp_req is None or opp == opp_req
                                if (dev_req is None or dev == dev_req) and opponent_ok:
                                    unlock_item(self.module.name, 'versus', name)
                                    runtime_globals.game_console.log(f"[DCom OEM] Unlocked versus: {name}")
                            elif ver_req is not None:
                                if pet_version == ver_req:
                                    unlock_item(self.module.name, 'versus', name)
                                    runtime_globals.game_console.log(f"[DCom OEM] Unlocked versus: {name}")
                            else:
                                unlock_item(self.module.name, 'versus', name)
                                runtime_globals.game_console.log(f"[DCom OEM] Unlocked versus: {name}")
                
                # Battle-type unlocks: triggered by OEM DCom victories
                if self.victory_status == "Victory":
                    if self.module.name not in game_globals.total_victories:
                        game_globals.total_victories[self.module.name] = 0
                    game_globals.total_victories[self.module.name] += 1
                    runtime_globals.game_console.log(f"[DCom OEM] Total victories for {self.module.name}: {game_globals.total_victories[self.module.name]}")
                    
                    for unlock in module_unlocks:
                        if unlock.get('type') == 'battle':
                            req = unlock.get('amount', None)
                            name = unlock.get('name')
                            if req is None or not name:
                                continue
                            current_victories = game_globals.total_victories.get(self.module.name, 0)
                            if current_victories >= int(req):
                                unlock_item(self.module.name, 'battle', name)
                                runtime_globals.game_console.log(f"[DCom OEM] Unlocked battle: {name} after {current_victories} victories")
            except Exception as e:
                runtime_globals.game_console.log(f"[DCom OEM] Error processing OEM unlocks: {e}")
        
        self.return_to_main_scene()

    def draw_level(self, surface):
        """
        Override level drawing to show DCom-specific UI.
        """
        super().draw_level(surface)
        
        # Draw DCom button/indicator if available
        self._draw_dcom_button(surface)
    
    def _draw_dcom_button(self, surface):
        """
        Draw DCom connection button/status on the level/entry screen.
        """
        if not self.dcom_mode:
            return
        
        # Simple status text
        font = self.font_small
        status_text = "DCom: Connected" if self.dcom_controller else "DCom: Disconnected"
        text_surface = font.render(status_text, True, (255, 255, 255))
        
        # Position at top-right corner
        x = runtime_globals.SCREEN_WIDTH - text_surface.get_width() - 10
        y = 10
        
        surface.blit(text_surface, (x, y))
        
        # Store rect for click detection
        self.dcom_button_rect = pygame.Rect(x, y, text_surface.get_width(), text_surface.get_height())
    
    def handle_event(self, event):
        """
        Override event handling to add DCom-specific interactions.
        """
        # DCom-specific controls run before the base handler, so lock them here
        # as well to keep READY/alert non-skippable.
        if self.phase == "alert":
            return

        # Handle DCom dialog events if active
        if self.dcom_dialog and hasattr(self.dcom_dialog, 'handle_event'):
            if self.dcom_dialog.handle_event(event):
                return  # Dialog handled the event
        
        # Handle DCom button clicks - event is tuple (event_type, event_data)
        if isinstance(event, tuple) and len(event) == 2:
            event_type, event_data = event
            if event_type == "LCLICK" and self.dcom_button_rect:
                mouse_pos = pygame.mouse.get_pos()
                if self.dcom_button_rect.collidepoint(mouse_pos):
                    runtime_globals.game_console.log("[BattleEncounterDCom] DCom button clicked")
                    if not self.dcom_controller and self.dcom_dialog:
                        self.dcom_dialog.show()
                    return
        
        # Call parent event handler
        super().handle_event(event)
    
    def __del__(self):
        """
        Clean up DCom resources.
        """
        # Reached during interpreter teardown too, where the attribute may
        # never have been set.
        controller = getattr(self, 'dcom_controller', None)
        if controller:
            try:
                controller.disconnect()
            except Exception:
                pass
