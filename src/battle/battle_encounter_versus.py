# core/combat/battle_encounter_versus.py

import pygame
from battle.battle_encounter import BattleEncounter, GameBattle
from battle.sim.battle_simulator import BattleSimulator, BattleProtocol
from models.animation import PetFrame
from battle.sim.models import Digimon
from battle.sim.dcom_battle_simulator import pet_to_digimon
from battle.sim import protocol_constants
import core.constants as constants
from utils.scene_utils import change_scene
from core import game_globals, runtime_globals
from utils.utils_unlocks import unlock_item
from utils.module_utils import get_module
import ui.ui_constants as ui_constants
from ui.components.image import Image
from ui.components.label import Label
from ui.components.component import UIComponent
from battle.combat_constants import ANY_OTHER_DEVICE

class BattleEncounterVersus(BattleEncounter):
    def __init__(self, pet1, pet2, protocol: BattleProtocol, battle_format: str = None):
        """
        Initializes the Versus encounter for PvP battles.
        """
        self.pet1 = pet1
        self.pet2 = pet2
        self.pet2.x = 2 * (runtime_globals.SCREEN_WIDTH / 240)
        self.protocol = protocol
        
        # Set pvp_mode flag before calling parent init
        self.pvp_mode = True
        
        # Call the base class initializer with module="DMC"
        module = "DMC"

        super().__init__(module, 0, 0, pvp_mode=True)
        # The device line this battle is fought on. The base class sets it to
        # None, so it has to be filled in after super().__init__ -- without it
        # a versus battle had no format at all, and the presentation fell back
        # to whichever module the encounter happened to be built with.
        self.battle_format = battle_format or self.BATTLE_FORMATS.get(protocol)
        self.enemy_entry_counter = 0

        # Override the BattlePlayer with the two pets for versus mode
        self.battle_player = GameBattle([pet1], [pet2], 0, 0, self.module)
        # The HP a versus battle is fought with belongs to the wire, exactly
        # as it does over a cable, and so does the round count. This was a
        # chain of literals keyed on the protocol, and PENOG had simply never
        # been added to it -- so the simulation fought at its fixed 3 HP
        # while the pets on screen kept their own, which is the DMX's
        # variable-HP behaviour. Read from the format now, where the values
        # already lived and where nothing new can be forgotten.
        #
        # FIXED_HP of None means the wire has no fixed HP (DMX, PENZ) and the
        # pets keep theirs.
        limits = protocol_constants.get_constants(self.battle_format)
        fixed_hp = getattr(limits, 'FIXED_HP', None) if limits else None
        self.turn_limit = getattr(limits, 'TURNS', 5) if limits else 5

        if fixed_hp is not None:
            self.battle_player.team1_hp[0] = fixed_hp
            self.battle_player.team2_hp[0] = fixed_hp
            self.battle_player.team1_max_hp[0] = fixed_hp
            self.battle_player.team2_max_hp[0] = fixed_hp
            self.battle_player.team1_total_hp = fixed_hp
            self.battle_player.team2_total_hp = fixed_hp
            self.battle_player.team1_max_total_hp = fixed_hp
            self.battle_player.team2_max_total_hp = fixed_hp
        else:
            team1hp = pet1.get_hp()
            team2hp = pet2.get_hp()
            self.battle_player.team1_hp[0] = team1hp
            self.battle_player.team2_hp[0] = team2hp
            self.battle_player.team1_max_hp[0] = team1hp
            self.battle_player.team2_max_hp[0] = team2hp
            self.battle_player.team1_total_hp = team1hp
            self.battle_player.team2_total_hp = team2hp
            self.battle_player.team1_max_total_hp = team1hp
            self.battle_player.team2_max_total_hp = team2hp

        self.alert_sprite = self.ui_manager.load_sprite_integer_scaling("Battle", "VersusFrame", "")

        # Setup persistent UI components for the alert phase (image + labels)
        # These components are added to the UI manager so the manager will
        # handle scaling and drawing automatically.
        self.setup_alert_components()

        # Initialize the BattleSimulator with the given protocol
        self.simulator = BattleSimulator(protocol, battle_format=battle_format)

        # Configure the global HPBar for versus mode and initialize totals
        self.hp_bar.set_mode('versus')
        self.hp_bar.set_totals(self.battle_player.team2_total_hp, self.battle_player.team1_total_hp)
        self.hp_bar.set_values(self.battle_player.team2_total_hp, self.battle_player.team1_total_hp)
        
        # Initialize result timer
        self.result_timer = 0
        
        # Set initial state
        self.phase = "alert"

    def calculate_combat_for_pairs(self):
        self.simulate_combat()
        
        # Load battle turns from simulation into BattlePlayer for animations
        self._load_protocol_turns_into_battle_player()

        self.process_battle_results()
    
    def _load_protocol_turns_into_battle_player(self):
        """
        Load battle turns from global_battle_log into BattlePlayer so animations can play.
        Sets up the battle system to use short cooldowns for rapid attack sequences.
        """
        if not self.global_battle_log or not self.global_battle_log.battle_log:
            runtime_globals.game_console.log("[BattleEncounterVersus] No battle log to load")
            return
        
        # Set short cooldowns for protocol battles to trigger rapid attacks
        for i in range(len(self.battle_player.team1)):
            self.battle_player.cooldowns[i] = 10  # Very short cooldown for fast attacks
            self.battle_player.phase[i] = "pet_charge"  # Start with charge phase
            self.battle_player.turns[i] = 1
        
        runtime_globals.game_console.log(f"[BattleEncounterVersus] Loaded protocol turns for {len(self.global_battle_log.battle_log)} turns")

    def setup_alert_components(self):
        """
        Create persistent UI components for the alert phase and register them
        with the UI manager so the UI system handles scaling/drawing.

        Components created:
        - self.alert_image : Image(0,0,240,240) using self.alert_sprite
        - self.left_label  : Label(27,186) left-aligned, fixed_width=170, font size 48
        - self.right_label : Label(280,245) right-aligned, fixed_width=170, font size 48
        """
        # Create alert image component (base UI coords covering the UI area)
        self.alert_image = Image(0, 0, 240, 240, image_surface=self.alert_sprite)
        # Add to UI manager so it gets scaled and drawn automatically
        self.ui_manager.add_component(self.alert_image)

        # Pet portrait images: left (above name) and right (below name)
        # Use IDLE1 frame by default. We swap which pet is shown on each side
        # so left will show pet2 (flipped to face right) and right will show pet1.
        left_sprite = None
        right_sprite = None
        # Left side shows pet2 (flip so it faces toward the center)
        left_sprite = self.pet2.get_sprite(PetFrame.IDLE1.value) if hasattr(self.pet2, 'get_sprite') else None
        if left_sprite:
            left_sprite = pygame.transform.flip(left_sprite, True, False)

        # Right side shows pet1 (no flip)
        right_sprite = self.pet1.get_sprite(PetFrame.IDLE1.value) if hasattr(self.pet1, 'get_sprite') else None

        # Create Image components for pet portraits (base coords)
        # Left portrait above the left label
        # Position: center of top-left quadrant on 240x240 base -> center (60,60)
        # With size 70x70, top-left = (60-35, 60-35) = (25,25)
        self.left_pet_image = Image(25, 15, 70, 70, image_surface=left_sprite)
        self.ui_manager.add_component(self.left_pet_image)

        # Right portrait below the right label
        # Position: center of bottom-right quadrant on 240x240 base -> center (180,180)
        # With size 70x70, top-left = (180-35, 180-35) = (145,145)
        self.right_pet_image = Image(145, 155, 70, 70, image_surface=right_sprite)
        self.ui_manager.add_component(self.right_pet_image)

        # Left label (left aligned) - now shows pet2's name
        self.left_label = Label(13, 99, text=getattr(self.pet2, 'name', ''), is_title=False, align_right=False, fixed_width=85, color_override=ui_constants.ANIM_BLACK)
        # Force a fixed size for this label instance regardless of manager
        # defaults; scaled with the screen so it does not shrink away on a
        # large display.
        _versus_label_size = int(24 * runtime_globals.UI_SCALE)
        self.left_label.get_font = lambda font_type, custom_size=None: UIComponent.get_font(self.left_label, font_type, custom_size=_versus_label_size)
        self.ui_manager.add_component(self.left_label)

        # Right label (right aligned) - now shows pet1's name
        self.right_label = Label(140, 130, text=getattr(self.pet1, 'name', ''), is_title=False, align_right=True, fixed_width=85, color_override=ui_constants.ANIM_BLACK)
        self.right_label.get_font = lambda font_type, custom_size=None: UIComponent.get_font(self.right_label, font_type, custom_size=_versus_label_size)
        self.ui_manager.add_component(self.right_label)

    #: The device line each versus protocol builds its packets for. The
    #: packets are the real ones, so the payload has to be built the same way
    #: a DCom battle builds it.
    BATTLE_FORMATS = {
        BattleProtocol.DMOG_BS: 'DMOG',
        BattleProtocol.PENOG_BS: 'PENOG',
        BattleProtocol.DM20_BS: 'DM20',
        BattleProtocol.PEN20_BS: 'PEN20',
        BattleProtocol.DMX_BS: 'DMX',
        BattleProtocol.DMC_BS: 'DMC',
    }

    #: Versus has no charge minigame; both sides get the same charge so the
    #: fight is decided by the pets rather than by a bar nobody played.
    #:
    #: A format may name its own, because a flat number does not mean the
    #: same thing on every scale: 3 is a full meter where the wire carries
    #: the banded 0-3 quality, and a tenth of one where it carries the raw
    #: shake count. `VERSUS_CHARGE` is that per-format value and is meant to
    #: be a fixed, deliberate choice rather than a maximum -- PENOG sets 10
    #: of its 40. Anything not naming one keeps the flat 3 it has always had.
    FIXED_CHARGE = 3

    @property
    def fixed_charge(self):
        constants = protocol_constants.get_constants(
            self.BATTLE_FORMATS.get(self.protocol, 'DM20'))
        return getattr(constants, 'VERSUS_CHARGE', self.FIXED_CHARGE)

    def simulate_combat(self):
        """Run the protocol simulation over both pets' packets."""
        battle_format = self.BATTLE_FORMATS.get(self.protocol, 'DM20')

        # Built by the same conversion a DCom battle uses, so a versus packet
        # says the same thing about a pet as a packet sent to a real device.
        # Building it here by hand had drifted: the attack sprite ids went out
        # 1-based (the protocols are 0-based, and Omnipet reserves 0 for "no
        # sprite"), a pet with no second attack sent sprite 1 rather than
        # none, `index` carried the pet's position in the team instead of its
        # real index, and power was never clamped to the 8 bits the field has.
        charge = self.fixed_charge
        attacker = pet_to_digimon(self.battle_player.team1[0], battle_format,
                                  charge)
        defender = pet_to_digimon(self.battle_player.team2[0], battle_format,
                                  charge)
        defender.order = 1

        # Run simulation
        self.global_battle_log = self.simulator.simulate(attacker, defender)

        # Store the attacker's turns as the combat log for animation
        self.victory_status = "Victory" if self.global_battle_log.winner == "device1" else "Defeat"

    def update_alert(self):
        """
        Handles the alert phase, transitioning to the battle phase.
        """
        if self.frame_counter > game_globals.configuration.frame_rate * 3:  # Wait for 3 seconds
            self.frame_counter = 0
            self.phase = "battle"
            self.calculate_combat_for_pairs()

    def update_result(self):
        """
        Handles the result phase, displaying the winner and transitioning back to the main scene.
        """
        self.result_timer += 1
        if self.result_timer == 2:
            runtime_globals.game_sound.play("happy")
        if self.result_timer > 90:  # Wait for 1.5 seconds (assuming 60 FPS)
            # Process the result
            winner = self.pet1 if self.global_battle_log.winner == "device1" else self.pet2
            loser = self.pet2 if winner == self.pet1 else self.pet1

            winner.finish_versus(True)
            loser.finish_versus(False)

            # Versus unlock logic: check if both pets are from the same module
            # and meet version requirements for versus unlocks
            pet1_module = getattr(self.pet1, 'module', None)
            pet2_module = getattr(self.pet2, 'module', None)
            
            # Only process versus unlocks if both pets are from the same module
            if pet1_module and pet2_module and pet1_module == pet2_module:
                pet_module = get_module(pet1_module)
                if pet_module:
                    module_unlocks = getattr(pet_module, 'unlocks', []) or []
                    for unlock in module_unlocks:
                        if unlock.get('type') == 'versus':
                            ver_req = unlock.get('version', None)
                            unlock_name = unlock.get('name')
                            if unlock_name:
                                # Check if at least one pet meets the version requirement
                                pet1_version = getattr(self.pet1, 'version', 0)
                                pet2_version = getattr(self.pet2, 'version', 0)

                                # Which physical device each pet was hatched on.
                                # A connection requirement is about the hardware,
                                # so device_version decides it, not the gameplay
                                # version used for evolutions.
                                dev1 = getattr(self.pet1, 'device_version', pet1_version)
                                dev2 = getattr(self.pet2, 'device_version', pet2_version)
                                dev_req = unlock.get('device_version', None)
                                opp_req = unlock.get('opponent_device_version', None)

                                # "Battle XA with XB" style pairing: one side has
                                # to be the named device and the other its partner.
                                # An opponent of ANY_OTHER_DEVICE means "any
                                # device that is not this one", which is how a
                                # device states "battle with any other version".
                                if dev_req is not None or opp_req is not None:
                                    def _side(own, other):
                                        if dev_req is not None and own != dev_req:
                                            return False
                                        if opp_req is None:
                                            return True
                                        if opp_req == ANY_OTHER_DEVICE:
                                            return other != own
                                        return other == opp_req

                                    paired = _side(dev1, dev2) or _side(dev2, dev1)
                                    if paired:
                                        unlock_item(pet1_module, 'versus', unlock_name)
                                        runtime_globals.game_console.log(f"[Versus] Unlocked {unlock_name} for {pet1_module}")
                                elif ver_req is not None:
                                    # Version requirement specified - check if either pet meets it
                                    if pet1_version == ver_req or pet2_version == ver_req:
                                        unlock_item(pet1_module, 'versus', unlock_name)
                                        runtime_globals.game_console.log(f"[Versus] Unlocked {unlock_name} for {pet1_module}")
                                else:
                                    # No version requirement - unlock for any versus battle in this module
                                    unlock_item(pet1_module, 'versus', unlock_name)
                                    runtime_globals.game_console.log(f"[Versus] Unlocked {unlock_name} for {pet1_module}")
            # Return to the main scene
            change_scene("game")

    def draw_result(self, surface: pygame.Surface):
        """
        Draws the result phase, showing the winner or indicating a draw with AnimatedSprite component.
        """
        # Start versus result animation if not already playing
        if not self.animated_sprite.is_animation_playing():
            self.animated_sprite.play_versus_result(duration_seconds=3.0)
        
        # Draw the animated sprite background
        self.animated_sprite.draw(surface)
        
        # Determine which pet won and should be displayed
        if self.global_battle_log.winner == "device1":
            winner_pet = self.pet1
        elif self.global_battle_log.winner == "device2":
            winner_pet = self.pet2
        else:
            winner_pet = None  # Draw for tie case
        
        # Animate winner pet sprite centered on screen
        # Toggle between IDLE1 and HAPPY every half second
        anim_toggle = (self.frame_counter // (game_globals.configuration.frame_rate // 2)) % 2
        
        if winner_pet:
            # Get the frame (IDLE1 or HAPPY)
            frame_id = PetFrame.IDLE1.value if anim_toggle == 0 else PetFrame.HAPPY.value
            pet_sprite = winner_pet.get_sprite(frame_id)
            
            # Center the sprite on screen
            pet_x = runtime_globals.SCREEN_WIDTH // 2 - pet_sprite.get_width() // 2
            pet_y = runtime_globals.SCREEN_HEIGHT // 2 - pet_sprite.get_height() // 2
            
            surface.blit(pet_sprite, (pet_x, pet_y))
        else:
            # Draw both pets for a tie (smaller and side by side), snapped to
            # the pixel-perfect ladder (PET//2 can land between steps).
            from utils.sprite_utils import snap_pet_sprite_size
            sprite_width = snap_pet_sprite_size(runtime_globals.PET_WIDTH // 2)
            sprite_height = sprite_width
            
            # Both pets animate between IDLE1 and HAPPY
            frame_id = PetFrame.IDLE1.value if anim_toggle == 0 else PetFrame.HAPPY.value
            
            # Position for pet1 (left side)
            pet1_x = runtime_globals.SCREEN_WIDTH // 4 - sprite_width // 2
            pet1_y = runtime_globals.SCREEN_HEIGHT // 2 - sprite_height // 2
            pet1_sprite = self.pet1.get_sprite(frame_id)
            pet1_sprite = pygame.transform.scale(pet1_sprite, (sprite_width, sprite_height))
            surface.blit(pet1_sprite, (pet1_x, pet1_y))
            
            # Position for pet2 (right side)
            pet2_x = 3 * runtime_globals.SCREEN_WIDTH // 4 - sprite_width // 2
            pet2_y = runtime_globals.SCREEN_HEIGHT // 2 - sprite_height // 2
            pet2_sprite = self.pet2.get_sprite(frame_id)
            pet2_sprite = pygame.transform.scale(pet2_sprite, (sprite_width, sprite_height))
            surface.blit(pet2_sprite, (pet2_x, pet2_y))

    def draw_alert(self, surface):
        """
        Draws the alert phase overlay.
        """
        # Fill the entire screen (or UI area) with the combat blue color.
        # The UI manager will draw the persistent Image and Label components
        # that were registered in `setup_alert_components`.
        surface.fill(ui_constants.COMBAT_BLUE)
        self.ui_manager.draw(surface)