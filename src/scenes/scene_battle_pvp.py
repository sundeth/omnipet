"""
Scene Battle PvP
A scene for network battles against other Omnipet devices.
"""
import pygame
from ui.windows.window_background import WindowBackground
from core import game_globals, runtime_globals
from battle.battle_encounter import BattleEncounter
from battle.battle_encounter_dcom import BattleEncounterDCom
from battle.sim import models as sim_models
from utils.scene_utils import change_scene
from models.animation import PetFrame
from ui.components.image import Image
from ui.components.label import Label
from ui import ui_constants
from ui.components.component import UIComponent
import pygame

class SceneBattlePvP:
    """
    Scene for PvP network battles using simulation data.
    """

    def __init__(self) -> None:
        """
        Initializes the PvP battle scene.
        """
        self.background = WindowBackground()
        self.battle_encounter = None
        self.alert_timer = 0  # Initialize alert_timer early to prevent AttributeError
        
        runtime_globals.game_console.log("[SceneBattlePvP] Initializing PvP battle scene...")
        
        # Get PvP battle data from runtime globals
        if hasattr(runtime_globals, 'pvp_battle_data') and runtime_globals.pvp_battle_data:
            try:
                pvp_data = runtime_globals.pvp_battle_data
                self.is_host = pvp_data.get('is_host', False)
                self.my_pets = pvp_data.get('my_pets', [])
                self.my_team_data = pvp_data.get('my_team_data', [])
                self.enemy_team_data = pvp_data.get('enemy_team_data', [])
                self.simulation_data = pvp_data.get('simulation_data', {})
                self.module_name = pvp_data.get('module', 'DMC')
                self.my_player_name = pvp_data.get('my_player_name', 'YOU')
                self.enemy_player_name = pvp_data.get('enemy_player_name', 'ENEMY')
                self.is_online_mode = pvp_data.get('is_online_mode', False)
                self.is_dcom_mode = pvp_data.get('is_dcom_mode', False)  # DCom battle flag
                # The device line the exchange was fought on. It decides the
                # battle's presentation (round count, how a damage value is
                # drawn), which belongs to the wire and not to the module.
                self.battle_format = pvp_data.get('battle_format')
                self.is_oem_mode = pvp_data.get('is_oem_mode', False)  # DCom OEM mode flag
                self.enemy_first = pvp_data.get('enemy_first', False)  # Enemy attacks first flag
                
                # Validate required data
                if not self.my_pets:
                    runtime_globals.game_console.log("[SceneBattlePvP] No my_pets data found")
                    change_scene("game")
                    return
                    
                if not self.enemy_team_data:
                    runtime_globals.game_console.log("[SceneBattlePvP] No enemy_team_data found")
                    change_scene("game")
                    return
                
                # For non-DCom battles, simulation_data is required
                # For DCom battles, simulation_data will be created during the battle
                if not self.is_dcom_mode and not self.simulation_data:
                    runtime_globals.game_console.log("[SceneBattlePvP] No simulation_data found")
                    change_scene("game")
                    return
                
                runtime_globals.game_console.log(f"[SceneBattlePvP] PvP data loaded:")
                runtime_globals.game_console.log(f"  - Is Host: {self.is_host}")
                runtime_globals.game_console.log(f"  - My pets: {len(self.my_pets)}")
                runtime_globals.game_console.log(f"  - Enemy team data: {len(self.enemy_team_data)}")
                runtime_globals.game_console.log(f"  - Module: {self.module_name}")
                
                # Play online battle sound
                runtime_globals.game_sound.play("battle_online")
                
                # Create battle encounter for PvP
                self.setup_pvp_battle()
                
                # Setup alert screen components
                self.setup_alert_components()
                
                runtime_globals.game_console.log(f"[SceneBattlePvP] PVP battle scene initialized successfully")
                
            except Exception as e:
                runtime_globals.game_console.log(f"[SceneBattlePvP] Error initializing PvP data: {e}")
                import traceback
                runtime_globals.game_console.log(f"[SceneBattlePvP] Traceback: {traceback.format_exc()}")
                change_scene("game")
        else:
            runtime_globals.game_console.log("[SceneBattlePvP] No PvP battle data found, returning to game")
            change_scene("game")

    def setup_pvp_battle(self) -> None:
        """Sets up the PvP battle encounter with simulation data."""
        try:
            runtime_globals.game_console.log("[SceneBattlePvP] Setting up PvP battle encounter...")
            
            # Check if this is a DCom battle
            if self.is_dcom_mode:
                runtime_globals.game_console.log("[SceneBattlePvP] Creating DCom battle encounter...")
                # Create DCom battle encounter (no controller/protocol needed - already connected in scene_connect)
                self.battle_encounter = BattleEncounterDCom(
                    self.module_name,
                    dcom_controller=None,  # Will use existing connection if needed
                    dcom_protocol=None,    # Will use existing protocol if needed
                    area=0,
                    round=0,
                    version=1
                )
            else:
                runtime_globals.game_console.log("[SceneBattlePvP] Creating standard PvP battle encounter...")
                # Create standard PvP battle encounter
                self.battle_encounter = BattleEncounter(
                    self.module_name, 
                    area=0, 
                    round=0, 
                    version=1, 
                    pvp_mode=True
                )
            
            runtime_globals.game_console.log(f"[SceneBattlePvP] Battle encounter created for module: {self.module_name}")
            
            # Both devices should show the same visual arrangement:
            # Team1 (left) = device1 pets, Team2 (right) = device2 pets
            # Determine which pets belong to device1 and device2 from the battle log
            
            if self.is_host:
                # Host created the battle log: device1 = host pets, device2 = client pets
                team1_pets = self.my_pets  # Host pets (GamePet objects)
                team2_pet_data = self.enemy_team_data  # Client pets (pet data dicts)
            else:
                # Client: device1 = host pets, device2 = client pets (same as host perspective)
                # For client, we need to convert host's pet data to GamePet objects for team1
                # and convert client's GamePet objects to pet data dicts for team2
                
                # Convert host pet data dicts to GamePet objects for team1
                from models.game_pet import GamePet
                team1_pets = []
                for pet_data in self.enemy_team_data:  # Host pets (pet data dicts)
                    # Add missing keys that GamePet constructor expects
                    complete_pet_data = pet_data.copy()
                    complete_pet_data.setdefault("version", 1)  # Default version
                    complete_pet_data.setdefault("special", False)  # Default special
                    complete_pet_data.setdefault("evolve", [])  # Default evolve list
                    complete_pet_data.setdefault("sleeps", None)  # Default sleep time
                    complete_pet_data.setdefault("wakes", None)  # Default wake time
                    complete_pet_data.setdefault("time", 0)  # Default time
                    complete_pet_data.setdefault("poop_timer", 60)  # Default poop timer
                    complete_pet_data.setdefault("min_weight", 10)  # Default min weight
                    complete_pet_data.setdefault("evol_weight", 0)  # Default evol weight
                    complete_pet_data.setdefault("stomach", 4)  # Default stomach
                    complete_pet_data.setdefault("hunger_loss", 60)  # Default hunger loss
                    complete_pet_data.setdefault("strength_loss", 60)  # Default strength loss
                    complete_pet_data.setdefault("energy", 100)  # Default energy
                    complete_pet_data.setdefault("heal_doses", 1)  # Default heal doses
                    complete_pet_data.setdefault("condition_hearts", 0)  # Default condition hearts
                    complete_pet_data.setdefault("jogress_available", 0)  # Default jogress
                    
                    # Create GamePet object using complete pet_data
                    temp_pet = GamePet(complete_pet_data)
                    team1_pets.append(temp_pet)
                
                # Convert client GamePet objects to pet data dicts for team2
                team2_data = []
                for pet in self.my_pets:  # Client pets (GamePet objects)
                    pet_data = {
                        "name": pet.name,
                        "stage": pet.stage,
                        "level": pet.level,
                        "hp": pet.get_hp() if hasattr(pet, "get_hp") else getattr(pet, "hp", 100),
                        "power": pet.get_power() if hasattr(pet, "get_power") else getattr(pet, "power", 1),
                        "attribute": pet.attribute,
                        "atk_main": pet.atk_main,
                        "atk_alt": pet.atk_alt,
                        "atk_alt_2": getattr(pet, "atk_alt_2", 0),
                        "module": pet.module,
                        "sick": getattr(pet, "sick", 0) > 0,
                        "traited": getattr(pet, "traited", False),
                        "shook": getattr(pet, "shook", False)
                    }
                    team2_data.append(pet_data)
                team2_pet_data = team2_data
            
            runtime_globals.game_console.log(f"[SceneBattlePvP] Setting up teams: team1_pets={len(team1_pets)}, team2_pet_data={len(team2_pet_data)}")
            # Host uses pvp_host HP bar, client uses pvp_client
            # Only when we have one: BattleEncounterDCom reads the same value
            # out of pvp_battle_data for itself, and None must not clobber it.
            if getattr(self, 'battle_format', None):
                self.battle_encounter.battle_format = self.battle_format
            self.battle_encounter.setup_pvp_teams(team1_pets, team2_pet_data, is_host=self.is_host)
            
            # Set flag for which team to show in result phase
            # Host should show team1 (their pets), client should show team2 (their pets)
            self.battle_encounter.show_team2_in_result = not self.is_host
            
            # For DCom battles, don't set simulation data - let the battle run naturally
            if self.is_dcom_mode:
                runtime_globals.game_console.log("[SceneBattlePvP] DCom mode: Using pre-generated battle data")
                runtime_globals.game_console.log("[SceneBattlePvP] Skipping alert and charge phases, going straight to entry->battle->result")
                
                # Set DCom mode flag on battle encounter for device mapping
                self.battle_encounter.is_dcom_mode = True
                self.battle_encounter.is_oem_mode = getattr(self, 'is_oem_mode', False)
                # The charge minigame was played in the connection flow and
                # its value is already inside the packets the device answered.
                self.battle_encounter.skip_charge = True
                self._register_xros_forms()
                runtime_globals.game_console.log(f"[SceneBattlePvP] Set is_dcom_mode flag on battle encounter (OEM={self.battle_encounter.is_oem_mode})")
                
                # Apply enemy_first flag for DCom battles (enemy attacks first in V2 protocol)
                if self.enemy_first:
                    # Prime enemy first (sets up shot flags and phases)
                    self.battle_encounter.prime_enemy_first()
                    runtime_globals.game_console.log("[SceneBattlePvP] Called prime_enemy_first() for DCom battle")
                    
                    # Adjust phases to start with enemy_charge for proper animation sequence
                    # (prime_enemy_first sets phase to "enemy_attack", but we want the full charge->attack sequence)
                    for i in range(len(self.battle_encounter.battle_player.phase)):
                        self.battle_encounter.battle_player.phase[i] = "enemy_charge"
                    runtime_globals.game_console.log("[SceneBattlePvP] Set phases to enemy_charge for animation sequence")
                
                # The exchange was fought in the connection view; adopting it
                # swaps device1/device2 into the order a battle scene reads
                # (device1 = team1 = the player).
                self.battle_encounter.adopt_battle_result(
                    runtime_globals.pvp_battle_data.get('original_battle_log'))

                # And it fights with the HP the two devices agreed on, not
                # the pet module's adventure-battle HP.
                self.battle_encounter.apply_exchange_hp(
                    (self.my_team_data[0].get('hp') if self.my_team_data else None),
                    (self.enemy_team_data[0].get('hp') if self.enemy_team_data else None))
                
                runtime_globals.game_console.log(f"[SceneBattlePvP] Victory status: {self.battle_encounter.victory_status}")
                runtime_globals.game_console.log(f"[SceneBattlePvP] Battle log has {len(self.battle_encounter.global_battle_log.battle_log)} turns")
                
                # Process results for animations (skip XP in PvP)
                if hasattr(self.battle_encounter, 'process_battle_results'):
                    self.battle_encounter.process_battle_results()
                
                # Start at entry phase (will go entry -> battle -> result)
                self.battle_encounter.phase = "entry"
                self.battle_encounter.frame_counter = 0
                runtime_globals.game_console.log("[SceneBattlePvP] DCom battle setup completed, starting at entry phase")
                return
            
            # Set the simulation data for non-DCom battles
            # Try to use original battle log object first (for host)
            original_battle_log = runtime_globals.pvp_battle_data.get('original_battle_log', None)
            if original_battle_log is not None:
                runtime_globals.game_console.log("[SceneBattlePvP] Using original battle log object")
                self.battle_encounter.global_battle_log = original_battle_log
                # Log the winner from the battle log
                if hasattr(original_battle_log, 'winner'):
                    runtime_globals.game_console.log(f"[SceneBattlePvP] Battle log winner: {original_battle_log.winner}")
            else:
                # Fallback to serialized data (for non-host)
                battle_log = self.simulation_data.get('battle_log', {})
                runtime_globals.game_console.log("[SceneBattlePvP] Using serialized battle log data")
                # Log the winner from serialized data
                if isinstance(battle_log, dict) and 'winner' in battle_log:
                    runtime_globals.game_console.log(f"[SceneBattlePvP] Serialized battle log winner: {battle_log['winner']}")

                # Deserialize the battle log data
                try:
                    from battle.sim.models import battle_result_from_serialized
                    self.battle_encounter.global_battle_log = battle_result_from_serialized(battle_log)
                except Exception as e:
                    runtime_globals.game_console.log(f"[SceneBattlePvP] Failed to deserialize battle log: {e}")
                    self.battle_encounter.global_battle_log = battle_log
                
            # The simulation payload's victory_status represents the canonical result:
            # "Victory" = device1 won, "Defeat" = device2 won
            # Since both devices now show device1 pets on left, device2 pets on right:
            # - Host sees their pets (device1) on left, so "Victory" = their victory
            # - Client sees host pets (device1) on left, so "Victory" = host victory = client defeat
            original_victory_status = self.simulation_data.get('victory_status', 'Victory')
            runtime_globals.game_console.log(f"[SceneBattlePvP] Original victory status from simulation: {original_victory_status}")
            
            self.battle_encounter.victory_status = original_victory_status

            if not self.is_host:
                # Client: since they see host pets (device1) on left side:
                # The victory_status represents: "Victory" = device1 won, "Defeat" = device2 won
                # Client sees device1 pets on left, device2 pets (theirs) on right
                # So if device1 won ("Victory"), client lost and should see "Defeat"
                # If device2 won ("Defeat"), client won and should see "Victory"
                vs = self.battle_encounter.victory_status
                if vs == "Victory":  # device1 (host) won
                    self.battle_encounter.victory_status = "Defeat"  # client lost
                elif vs == "Defeat":  # device2 (client) won
                    self.battle_encounter.victory_status = "Victory"  # client won
                # Handle legacy device labels
                elif vs == "device1":
                    self.battle_encounter.victory_status = "Defeat" 
                elif vs == "device2":
                    self.battle_encounter.victory_status = "Victory"
                runtime_globals.game_console.log(f"[SceneBattlePvP] Client flipped victory status from {vs} to {self.battle_encounter.victory_status}")
            else:
                runtime_globals.game_console.log(f"[SceneBattlePvP] Host perspective. Victory status: {self.battle_encounter.victory_status}")
            
            # Log battle data info
            if hasattr(self.battle_encounter.global_battle_log, 'battle_log'):
                log_length = len(self.battle_encounter.global_battle_log.battle_log)
            elif isinstance(self.battle_encounter.global_battle_log, list):
                log_length = len(self.battle_encounter.global_battle_log)
            elif isinstance(self.battle_encounter.global_battle_log, dict) and 'battle_log' in self.battle_encounter.global_battle_log:
                log_length = len(self.battle_encounter.global_battle_log['battle_log'])
            else:
                log_length = 0
                
            runtime_globals.game_console.log(f"[SceneBattlePvP] Loaded {log_length} battle log entries")
            runtime_globals.game_console.log(f"[SceneBattlePvP] Victory status: {self.battle_encounter.victory_status}")
            
            # Process results for animations (but skip XP/level ups in PvP mode)
            if hasattr(self.battle_encounter, 'process_battle_results'):
                self.battle_encounter.process_battle_results()
            
            # Start at alert phase to show team preview
            self.battle_encounter.phase = "alert"
            self.battle_encounter.frame_counter = 0
            self.alert_timer = 0
            
            runtime_globals.game_console.log("[SceneBattlePvP] Battle setup completed successfully")
                
        except Exception as e:
            runtime_globals.game_console.log(f"[SceneBattlePvP] Error setting up PvP battle: {e}")
            import traceback
            runtime_globals.game_console.log(f"[SceneBattlePvP] Traceback: {traceback.format_exc()}")
            change_scene("game")
    
    def _register_xros_forms(self):
        """Hand any temporary evolutions to the encounter so they revert.

        The connection flow chooses the DigiXros form before the exchange, so
        the pets that arrive here can already be XrosPet stand-ins. Telling
        the encounter about them lets the result screen's devolution flash and
        the end-of-battle cleanup work exactly as they do in an adventure
        battle -- nothing is written to the real pet either way.
        """
        forms = {pet.pet: pet for pet in self.my_pets if hasattr(pet, 'pet')}
        if not forms:
            return
        self.battle_encounter.xros_forms = forms
        runtime_globals.game_console.log(
            f"[SceneBattlePvP] {len(forms)} temporary evolution(s) registered")

    def setup_alert_components(self):
        """Setup PVP alert screen with team previews and player labels."""
        try:
            # Load appropriate background based on host/client
            if self.is_host:
                self.alert_sprite = self.battle_encounter.ui_manager.load_sprite_integer_scaling("Battle", "VersusFrame_PVPHost", "")
            else:
                self.alert_sprite = self.battle_encounter.ui_manager.load_sprite_integer_scaling("Battle", "VersusFrame_PVPClient", "")
            
            # Create alert image component (base UI coords covering the UI area)
            # Add background FIRST so it draws at the bottom
            self.alert_image = Image(0, 0, 240, 240, image_surface=self.alert_sprite)
            self.alert_image.visible = True
            self.battle_encounter.ui_manager.add_component(self.alert_image)
            runtime_globals.game_console.log(f"[SceneBattlePvP] Alert background loaded: {self.alert_sprite is not None}")
            
            # Determine player labels based on online/local mode and host/client role
            # WiFi battles: Host shows ENEMY(left), YOU(right); Client shows YOU(left), ENEMY(right)
            # Online battles: Host shows opponent(left), their username(right); Client shows opponent(left), their username(right)
            if self.is_online_mode:
                # Online: Use Discord usernames
                if self.is_host:
                    # Host: enemy left, me right
                    top_label = self.enemy_player_name if self.enemy_player_name else "ENEMY"
                    bottom_label = self.my_player_name if self.my_player_name else "YOU"
                else:
                    # Client: opponent left, me right (enemy is on top/left from perspective)
                    top_label = self.enemy_player_name if self.enemy_player_name else "ENEMY"
                    bottom_label = self.my_player_name if self.my_player_name else "YOU"
            else:
                # WiFi: Use ENEMY/YOU labels
                if self.is_host:
                    # Host: ENEMY left, YOU right
                    top_label = "ENEMY"
                    bottom_label = "YOU"
                else:
                    # Client: YOU left, ENEMY right
                    top_label = "YOU"
                    bottom_label = "ENEMY"
            
            runtime_globals.game_console.log(f"[SceneBattlePvP] Alert labels: top='{top_label}', bottom='{bottom_label}', host={self.is_host}, online={self.is_online_mode}")
            
            # Top label (enemy team) - positioned like versus left label, add AFTER background so it draws on top
            self.top_label = Label(13, 99, text=top_label, is_title=True, align_right=False, fixed_width=85, color_override=ui_constants.ANIM_BLACK)
            self.top_label.visible = True
            self.battle_encounter.ui_manager.add_component(self.top_label)
            runtime_globals.game_console.log(f"[SceneBattlePvP] Added top label: '{top_label}' at (13, 99)")
            
            # Bottom label (your team) - positioned like versus right label, add AFTER background so it draws on top
            self.bottom_label = Label(140, 130, text=bottom_label, is_title=True, align_right=True, fixed_width=85, color_override=ui_constants.ANIM_BLACK)
            self.bottom_label.visible = True
            self.battle_encounter.ui_manager.add_component(self.bottom_label)
            runtime_globals.game_console.log(f"[SceneBattlePvP] Added bottom label: '{bottom_label}' at (140, 130)")
            
            # Display team2 pets at top (left to right, starting from left edge)
            team2_pets = self.battle_encounter.battle_player.team2
            pet_size = 40
            spacing = 50  # Spacing between pets
            
            runtime_globals.game_console.log(f"[SceneBattlePvP] Displaying {len(team2_pets)} team2 pets at top")
            for i, pet in enumerate(team2_pets):
                try:
                    pet_sprite = pet.get_sprite(PetFrame.IDLE1.value) if hasattr(pet, 'get_sprite') else None
                    if pet_sprite:
                        # Left to right: start at x=10, space by 50px
                        x = 10 + i * spacing
                        y = 40  # Higher up
                        pet_image = Image(x, y, pet_size, pet_size, image_surface=pet_sprite)
                        pet_image.visible = True
                        self.battle_encounter.ui_manager.add_component(pet_image)
                        runtime_globals.game_console.log(f"[SceneBattlePvP] Added team2 pet {i} at ({x}, {y})")
                    else:
                        runtime_globals.game_console.log(f"[SceneBattlePvP] Team2 pet {i} has no sprite")
                except Exception as e:
                    runtime_globals.game_console.log(f"[SceneBattlePvP] Error loading team2 pet {i}: {e}")
            
            # Display team1 pets at bottom (right to left, starting from right edge)
            team1_pets = self.battle_encounter.battle_player.team1
            
            runtime_globals.game_console.log(f"[SceneBattlePvP] Displaying {len(team1_pets)} team1 pets at bottom")
            for i, pet in enumerate(team1_pets):
                try:
                    pet_sprite = pet.get_sprite(PetFrame.IDLE1.value) if hasattr(pet, 'get_sprite') else None
                    if pet_sprite:
                        # Flip sprite to face right
                        pet_sprite = pygame.transform.flip(pet_sprite, True, False)
                        # Right to left: start at x=190 (240-40-10), go left by 50px each
                        x = 190 - i * spacing
                        y = 160  # Lower down
                        pet_image = Image(x, y, pet_size, pet_size, image_surface=pet_sprite)
                        pet_image.visible = True
                        self.battle_encounter.ui_manager.add_component(pet_image)
                        runtime_globals.game_console.log(f"[SceneBattlePvP] Added team1 pet {i} at ({x}, {y})")
                    else:
                        runtime_globals.game_console.log(f"[SceneBattlePvP] Team1 pet {i} has no sprite")
                except Exception as e:
                    runtime_globals.game_console.log(f"[SceneBattlePvP] Error loading team1 pet {i}: {e}")
            
            runtime_globals.game_console.log("[SceneBattlePvP] Alert components setup complete")
            
        except Exception as e:
            runtime_globals.game_console.log(f"[SceneBattlePvP] Error setting up alert components: {e}")
            import traceback
            runtime_globals.game_console.log(f"[SceneBattlePvP] Traceback: {traceback.format_exc()}")

    def swap_battle_log_devices(self, battle_log_dict):
        """Swaps device1/device2 in battle log for client perspective."""
        try:
            swapped_log = battle_log_dict.copy()
            
            # Swap winner
            if swapped_log.get('winner') == 'device1':
                swapped_log['winner'] = 'device2'
            elif swapped_log.get('winner') == 'device2':
                swapped_log['winner'] = 'device1'
            
            # Swap final device states
            if 'device1_final' in swapped_log and 'device2_final' in swapped_log:
                temp = swapped_log['device1_final']
                swapped_log['device1_final'] = swapped_log['device2_final']
                swapped_log['device2_final'] = temp
            
            # Swap battle log entries
            if 'battle_log' in swapped_log:
                for turn_log in swapped_log['battle_log']:
                    # Swap device status
                    if 'device1_status' in turn_log and 'device2_status' in turn_log:
                        temp = turn_log['device1_status']
                        turn_log['device1_status'] = turn_log['device2_status']
                        turn_log['device2_status'] = temp
                    
                    # Swap attack device references
                    if 'attacks' in turn_log:
                        for attack in turn_log['attacks']:
                            if attack.get('device') == 'device1':
                                attack['device'] = 'device2'
                            elif attack.get('device') == 'device2':
                                attack['device'] = 'device1'
            
            return swapped_log
        except Exception as e:
            runtime_globals.game_console.log(f"[SceneBattlePvP] Error swapping battle log: {e}")
            return battle_log_dict  # Return original on error

    def deserialize_battle_result(self, serialized: dict) -> sim_models.BattleResult:
        """Convert a serialized battle result dict into sim_models.BattleResult dataclass.

        This reconstructs DigimonStatus, AttackLog, TurnLog and BattleResult instances.
        Packet hex strings will be converted back to bytes when possible.
        """
        # Helper to restore DigimonStatus
        def make_status(d):
            return sim_models.DigimonStatus(name=d.get('name', ''), hp=int(d.get('hp', 0)), alive=bool(d.get('alive', False)))

        # Helper to restore AttackLog
        def make_attack(d):
            return sim_models.AttackLog(
                turn=int(d.get('turn', 0)),
                device=d.get('device', ''),
                attacker=int(d.get('attacker', -1)),
                defender=int(d.get('defender', -1)),
                hit=bool(d.get('hit', False)),
                damage=int(d.get('damage', 0))
            )

        # Helper to restore TurnLog
        def make_turn(t):
            device1 = [make_status(s) for s in t.get('device1_status', [])]
            device2 = [make_status(s) for s in t.get('device2_status', [])]
            attacks = [make_attack(a) for a in t.get('attacks', [])]
            return sim_models.TurnLog(turn=int(t.get('turn', 0)), device1_status=device1, device2_status=device2, attacks=attacks)

        # Reconstruct packets: convert hex strings back to bytes where applicable
        def restore_packets(packet_lists):
            restored = []
            for pkt_list in packet_lists or []:
                new_list = []
                for pkt in pkt_list:
                    if isinstance(pkt, str):
                        try:
                            new_list.append(bytes.fromhex(pkt))
                        except Exception:
                            new_list.append(pkt)
                    else:
                        new_list.append(pkt)
                restored.append(new_list)
            return restored

        winner = serialized.get('winner', 'draw')
        device1_final = [make_status(s) for s in serialized.get('device1_final', [])]
        device2_final = [make_status(s) for s in serialized.get('device2_final', [])]
        battle_log = [make_turn(t) for t in serialized.get('battle_log', [])]
        device1_packets = restore_packets(serialized.get('device1_packets', []))
        device2_packets = restore_packets(serialized.get('device2_packets', []))

        return sim_models.BattleResult(
            winner=winner,
            device1_final=device1_final,
            device2_final=device2_final,
            battle_log=battle_log,
            device1_packets=device1_packets,
            device2_packets=device2_packets
        )

    def update(self) -> None:
        """
        Updates the PvP battle scene.
        """
        if self.battle_encounter:
            # Handle alert phase
            if self.battle_encounter.phase == "alert":
                self.alert_timer += 1
                if self.alert_timer > game_globals.configuration.frame_rate * 3:  # 3 seconds
                    self.battle_encounter.phase = "battle"
                    self.battle_encounter.frame_counter = 0
                    runtime_globals.game_console.log("[SceneBattlePvP] Transitioning from alert to battle phase")
                return
            
            self.battle_encounter.update()
            
            # Check if battle is complete
            if self.battle_encounter.phase == "result" or self.battle_encounter.phase == "clear":
                # Battle completed, check for return to game
                pass

    def draw(self, surface: pygame.Surface) -> None:
        """
        Draws the PvP battle scene.
        """
        self.background.draw(surface)
        if self.battle_encounter:
            # Handle alert phase drawing
            if self.battle_encounter.phase == "alert":
                surface.fill(ui_constants.COMBAT_BLUE)
                self.battle_encounter.ui_manager.draw(surface)
            else:
                self.battle_encounter.draw(surface)

    def handle_event(self, event) -> None:
        """
        Handles keyboard and GPIO button inputs for the PvP battle scene.
        """
        if not isinstance(event, tuple) or len(event) != 2:
            return False
        
        if self.battle_encounter:
            self.battle_encounter.handle_event(event)
            
            # Check for battle completion and return to game
            if self.battle_encounter.phase in ["result", "clear", "finished"]:
                if event == "A" or event == "B" or event == "START":
                    runtime_globals.game_console.log("[SceneBattlePvP] PvP battle completed, returning to game")
                    # Clear PvP data
                    if hasattr(runtime_globals, 'pvp_battle_data'):
                        delattr(runtime_globals, 'pvp_battle_data')
                    change_scene("game")
        else:
            # If no battle encounter, return to game on any input
            if event:
                runtime_globals.game_console.log("[SceneBattlePvP] No battle encounter, returning to game")
                if hasattr(runtime_globals, 'pvp_battle_data'):
                    delattr(runtime_globals, 'pvp_battle_data')
                change_scene("game")
