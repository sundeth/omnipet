"""
JogressView - Jogress fusion selection
Shows pet selector and jogress display for 2-pet fusion.

The second slot can also be a **real device**. When one pet is chosen, that
pet can present itself to the hardware, and a DCom adapter is plugged in, the
slot fills with the Serial sprite and CONFIRM opens the exchange instead of
fusing two of our own pets. What comes out is the device's to say -- the
result hexagon shows the same "?" it always does -- so the flow is exchange
first, animation second: the evolution animation only starts once the device
has answered and a route has resolved, the way the local jogress only starts
once the pair is known to be compatible.
"""
import pygame
from ui.ui_manager import UIManager
from ui.components.title_scene import TitleScene
from ui.components.button import Button
from ui.components.background import Background
from ui.components.pet_selector import PetSelector
from ui.components.jogress_display import JogressDisplay
from ui.ui_constants import BASE_RESOLUTION
from core import runtime_globals
from utils.pet_utils import get_selected_pets
from utils.scene_utils import change_scene
from core import game_globals


class SerialPartner:
    """A real device standing in for the second pet.

    Duck-types the little of a pet the display reads -- a sprite and a state
    -- so the Serial slot draws through `draw_pet_sprite` and is hidden by
    `set_hide_pet_sprites` exactly as a pet's is, which is what lets the
    evolution animation work unchanged.
    """

    name = "Serial"
    module = None
    state = "idle"

    def __init__(self):
        self._sprite = None

    def get_sprite(self, frame=None):
        if self._sprite is None:
            from utils.pygame_utils import sprite_load_percent
            from core import constants
            try:
                self._sprite = sprite_load_percent(
                    constants.SERIAL_PATH, percent=100, keep_proportion=True,
                    base_on="height")
            except Exception as error:
                runtime_globals.game_console.log(
                    f"[JogressView] Could not load the Serial sprite: {error}")
                self._sprite = False
        return self._sprite or None


def is_serial(slot):
    """Whether a display slot is holding the device rather than a pet."""
    return isinstance(slot, SerialPartner)


class JogressView:
    """Jogress fusion selection view."""
    
    def __init__(self, ui_manager: UIManager, change_view_callback):
        """Initialize the Jogress view.
        
        Args:
            ui_manager: The UI manager instance
            change_view_callback: Callback to change to another view
        """
        self.ui_manager = ui_manager
        self.change_view = change_view_callback
        
        # Selection state
        self.selected_pets = []  # positions in `selectable_pets`, max 2
        self.selectable_pets = []  # what the selector shows, in its order
        self.selection_themes = ["GREEN", "BLUE"]  # GREEN→left, BLUE→right
        self.pet_theme_assignments = {}  # Dict: pet_index -> theme_name
        
        # Evolution animation state
        self.evolution_animation_active = False
        self.evolution_animation_timer = 0.0
        self.evolution_animation_duration = 3.0
        self.pet_circles = []
        self.particles = []
        
        # Jogress execution state
        self.jogress_executing = False  # True when performing jogress after animation

        # Serial jogress state. The adapter is only *detected* up front -- a
        # port scan is cheap, opening one costs a couple of seconds while the
        # Arduino resets, so that waits until the player actually confirms.
        self.serial_available = False
        self.serial_partner = None      # the stand-in occupying slot 2
        self.serial_session = None      # the live exchange, once started
        self.dcom_controller = None
        self.status_label = None
        
        # UI Components
        self.background = None
        self.title_scene = None
        self.pet_selector = None
        self.jogress_display = None
        self.confirm_button = None
        self.back_button = None
        
        self._setup_ui()
        
    def _setup_ui(self):
        """Setup the UI components."""
        ui_width = ui_height = BASE_RESOLUTION
        
        # Background
        self.background = Background(ui_width, ui_height)
        self.background.set_regions([(0, ui_height, "black")])
        self.ui_manager.add_component(self.background)
        
        # Title
        self.title_scene = TitleScene(0, 9, "BATTLE")
        self.ui_manager.add_component(self.title_scene)
        
        # Jogress display
        display_width = 160
        display_height = 125
        display_x = (ui_width - display_width) // 2
        display_y = 25
        
        self.jogress_display = JogressDisplay(display_x, display_y, display_width, display_height)
        self.jogress_display.set_compatibility_callback(self._check_pet_compatibility)
        self.ui_manager.add_component(self.jogress_display)
        
        # Buttons
        back_button_width = 60
        confirm_button_width = 80
        button_height = 25
        button_spacing = 5
        
        total_button_width = back_button_width + confirm_button_width + button_spacing
        buttons_start_x = (ui_width - total_button_width) // 2
        buttons_y = display_y + display_height + 10
        
        self.back_button = Button(
            buttons_start_x, buttons_y, back_button_width, button_height,
            "BACK", self._on_back
        )
        self.ui_manager.add_component(self.back_button)
        
        confirm_button_x = buttons_start_x + back_button_width + button_spacing
        self.confirm_button = Button(
            confirm_button_x, buttons_y, confirm_button_width, button_height,
            "CONFIRM", self._on_confirm,
            enabled=False
        )
        self.ui_manager.add_component(self.confirm_button)
        
        # Pet selector
        selector_y = buttons_y + button_height + 5
        selector_height = 50
        self.pet_selector = PetSelector(10, selector_y, ui_width - 20, selector_height)
        # **The selector's list is not `game_globals.pet_list`.** It is
        # `get_selected_pets()`, which is the pre-selected party where there
        # is one and otherwise the living, hatched pets -- so an egg, a dead
        # pet or a pre-selection shifts every index. `selected_pets` counts
        # positions in THIS list, so everything that turns one back into a
        # pet has to read it here rather than the global roster.
        pets = get_selected_pets()
        self.selectable_pets = pets
        self.pet_selector.set_pets(pets)
        # Grey out the pets that could never be part of a jogress, so the
        # player is not left selecting one and waiting for an explanation.
        self.pet_selector.set_enabled_pets(
            [i for i, pet in enumerate(pets) if self._pet_can_jogress(pet)])
        self.pet_selector.set_interactive(True)
        self.pet_selector.activation_callback = self._handle_pet_activation
        self.ui_manager.add_component(self.pet_selector)
        
        # Status line for the serial exchange. It sits where the buttons are
        # and only appears once they are hidden, so nothing moves.
        from ui.components.label import Label
        self.status_label = Label(10, buttons_y, "", is_title=False,
                                  word_wrap=True, max_width=ui_width - 20)
        self.status_label.visible = False
        self.ui_manager.add_component(self.status_label)

        # Set initial focus
        self.ui_manager.set_focused_component(self.pet_selector)
        self.pet_selector.focused_cell = 0

        self._detect_adapter()

        runtime_globals.game_console.log("[JogressView] UI setup complete")

    def _detect_adapter(self):
        """Note whether a DCom adapter is plugged in, without opening it.

        Only a port enumeration -- opening the port resets the Arduino and
        costs the game a couple of frozen seconds, which is not something to
        spend on every visit to this screen.
        """
        try:
            from battle.dcom.dcom_controller import DComController
            self.serial_available = bool(DComController().find_dcom_devices())
        except Exception as error:
            runtime_globals.game_console.log(
                f"[JogressView] No adapter detected: {error}")
            self.serial_available = False
        if self.serial_available:
            runtime_globals.game_console.log(
                "[JogressView] Adapter present - serial jogress is available")
    
    def _handle_pet_activation(self):
        """Handle pet activation from pet selector."""
        pet_index = self.pet_selector.get_activation_cell()
        if pet_index >= 0 and pet_index < len(self.pet_selector.pets):
            if pet_index in self.pet_selector.enabled_pets:
                return self._toggle_pet_selection(pet_index)
        return False
    
    def _toggle_pet_selection(self, pet_index):
        """Toggle pet selection (max 2 pets)."""
        if pet_index in self.selected_pets:
            # Deselect
            self.selected_pets.remove(pet_index)
            
            if self.jogress_display:
                slot_to_clear = None
                if pet_index in self.pet_theme_assignments:
                    theme = self.pet_theme_assignments[pet_index]
                    slot_to_clear = 0 if theme == "GREEN" else 1
                    
                if slot_to_clear is not None:
                    self.jogress_display.clear_slot(slot_to_clear)
            
            if pet_index in self.pet_theme_assignments:
                del self.pet_theme_assignments[pet_index]
                
            runtime_globals.game_sound.play("cancel")
        else:
            # Select
            if len(self.selected_pets) < 2:
                self.selected_pets.append(pet_index)
                
                # Assign theme
                used_themes = set(self.pet_theme_assignments.values())
                available_themes = [theme for theme in self.selection_themes if theme not in used_themes]
                
                if available_themes:
                    self.pet_theme_assignments[pet_index] = available_themes[0]
                    assigned_theme = available_themes[0]
                    
                    if self.jogress_display:
                        pet = self.pet_selector.pets[pet_index] if pet_index < len(self.pet_selector.pets) else None
                        if pet:
                            slot_index = 0 if assigned_theme == "GREEN" else 1
                            self.jogress_display.set_pet_slot(slot_index, pet)
                else:
                    self.pet_theme_assignments[pet_index] = "GREEN"
                    if self.jogress_display:
                        pet = self.pet_selector.pets[pet_index] if pet_index < len(self.pet_selector.pets) else None
                        if pet:
                            self.jogress_display.set_pet_slot(0, pet)
                
                runtime_globals.game_sound.play("menu")
            else:
                runtime_globals.game_sound.play("cancel")
                return False
        
        # Update state
        self.pet_selector.selected_pets = self.selected_pets[:]

        self._refresh_serial_slot()

        if self.confirm_button:
            self.confirm_button.set_enabled(
                len(self.selected_pets) == 2
                or (len(self.selected_pets) == 1 and self.serial_partner is not None))

        self._update_pet_themes()
        self.pet_selector.needs_redraw = True
        return True
    
    def _serial_candidate(self):
        """The chosen pet, if it alone could jogress with a real device.

        Only ever offered for a single selection: picking a second pet is the
        player saying they want that pairing instead.
        """
        if not self.serial_available or len(self.selected_pets) != 1:
            return None
        index = self.selected_pets[0]
        if index >= len(self.selectable_pets):
            return None
        pet = self.selectable_pets[index]
        from battle.sim.jogress_session import can_jogress_over_serial
        possible, reason = can_jogress_over_serial(pet)
        if not possible:
            runtime_globals.game_console.log(
                f"[JogressView] No serial jogress for {pet.name}: {reason}")
            return None
        return pet

    def _refresh_serial_slot(self):
        """Put the device in the second slot, or take it back out.

        The device always takes the *second* slot, so the one remaining pet
        is moved into the first -- a pet that was sitting in slot 2 when its
        partner was deselected would otherwise be overwritten by the Serial
        sprite and disappear from the display.
        """
        pet = self._serial_candidate()
        if not self.jogress_display:
            self.serial_partner = SerialPartner() if pet else None
            return

        if pet:
            index = self.selected_pets[0]
            self.pet_theme_assignments[index] = self.selection_themes[0]
            self.jogress_display.set_pet_slot(0, pet)
            if self.serial_partner is None:
                self.serial_partner = SerialPartner()
            self.jogress_display.set_pet_slot(1, self.serial_partner)
            return

        # Only ever clear the slot the device is actually in: by the time a
        # second pet has been chosen, slot 2 already holds that pet.
        if self.serial_partner is not None:
            if is_serial(self.jogress_display.get_slot_pet(1)):
                self.jogress_display.clear_slot(1)
            self.serial_partner = None

    def _update_pet_themes(self):
        """Update pet selector themes."""
        if not self.pet_selector:
            return
            
        self.pet_selector.clear_custom_themes()
        
        for pet_index in self.selected_pets:
            if pet_index in self.pet_theme_assignments:
                theme = self.pet_theme_assignments[pet_index]
                self.pet_selector.set_pet_custom_theme(pet_index, theme)
    
    # Jogress cost stats: attribute name + per-pet "full" value. Both pets
    # must be at (or above — effort can exceed 16) that value to jogress;
    # the stat is zeroed on the evolved pets afterwards.
    JOGRESS_COST_STATS = {
        "DP": ("dp", lambda pet: getattr(pet, "energy", 0)),
        "Effort": ("effort", lambda pet: 16),
        "Strength": ("strength", lambda pet: JogressView._care_stat_max(pet)),
        "Hunger": ("hunger", lambda pet: JogressView._care_stat_max(pet)),
    }

    @staticmethod
    def _care_stat_max(pet):
        """Full-hearts value for hunger/strength, mirroring SceneStatus.

        Fixed-4-hearts modules: 4 (1 unit per heart). Otherwise the heart
        count comes from the stomach (stomach // 2, clamped 1-4) with 2
        units per heart. A pet with no stomach has no hearts to fill, so
        the requirement is trivially met.
        """
        from utils.module_utils import get_module
        module = get_module(getattr(pet, "module", None))
        stomach = getattr(pet, "stomach", 4)
        if stomach <= 0:
            return 0
        if getattr(module, "care_fixed_4_hearts", True):
            return 4
        return max(1, min(4, stomach // 2)) * 2

    def _get_jogress_cost(self, pet):
        """The module's jogress cost stat name ('Nothing' disables the cost)."""
        from utils.module_utils import get_module
        module = get_module(pet.module)
        return getattr(module, "jogress_cost", "DP") if module else "DP"

    def _pet_meets_jogress_cost(self, pet):
        """True when this pet has the module's cost stat at its maximum."""
        entry = self.JOGRESS_COST_STATS.get(self._get_jogress_cost(pet))
        if entry is None:  # "Nothing" (or unknown value): no requirement
            return True
        attr, max_fn = entry
        return getattr(pet, attr, 0) >= max_fn(pet)

    def _pets_meet_jogress_cost(self, pet1, pet2):
        """True when both pets have the cost stat at its maximum."""
        return all(self._pet_meets_jogress_cost(p) for p in (pet1, pet2))

    def _pet_can_jogress(self, pet):
        """Whether this pet can be picked for a jogress at all.

        Two ways a pet is simply not a candidate, and both are worth showing
        before the player selects it: it has no jogress route on its own
        evolution list, or it has not paid the module's jogress cost. Note
        this deliberately does not judge compatibility — that depends on the
        partner and is what the display reports once two are chosen.
        """
        from utils.jogress_utils import is_jogress
        if not any(is_jogress(evo) for evo in getattr(pet, "evolve", []) or []):
            return False
        return self._pet_meets_jogress_cost(pet)

    def _apply_jogress_cost(self, pets):
        """Consume the cost: zero the stat on the evolved (surviving) pets."""
        if not pets:
            return
        entry = self.JOGRESS_COST_STATS.get(self._get_jogress_cost(pets[0]))
        if entry is None:
            return
        attr, _ = entry
        for pet in pets:
            setattr(pet, attr, 0)
        runtime_globals.game_console.log(
            f"[Jogress] Consumed {attr} from {len(pets)} evolved pet(s)")

    def _check_pet_compatibility(self, pet1, pet2):
        """Check if two pets are compatible for Jogress."""
        if not pet1 or not pet2:
            return False

        # A device in the second slot is always "compatible": what comes out
        # is the device's to say, and we do not know it until it answers.
        if is_serial(pet1) or is_serial(pet2):
            return True

        if pet1.module != pet2.module:
            return False

        # Checked in BOTH directions: a pairing declared only on the
        # partner's side is still a real pairing, and testing just the
        # first-selected pet made such a pair read as incompatible depending
        # on which one the player tapped first.
        from utils.jogress_utils import compatible
        return compatible(pet1, pet2)

    def get_jogress_evolution_info(self, pet1, pet2):
        """Get evolution info for compatible pets - used by JogressDisplay."""
        if not pet1 or not pet2:
            return None

        # Nothing is known about a serial jogress until the device answers,
        # so the result hexagon shows the single "?" it draws for an unknown
        # outcome. One "?", because only our pet evolves over the wire.
        if is_serial(pet1) or is_serial(pet2):
            return {"evolution": None, "is_dual": False}

        from utils.jogress_utils import find_route, is_dual

        evo = find_route(pet1, pet2)
        if evo is None:
            # Declared on the partner's side only - report it from there so the
            # display still shows what the pair produces.
            evo = find_route(pet2, pet1)
            if evo is None:
                return None
            pet1, pet2 = pet2, pet1

        if not is_dual(evo):
            return {"evolution": evo, "is_dual": False}
        return {
            "evolution": evo,
            "evolution2": find_route(pet2, pet1),   # partner's own route
            "is_dual": True,
        }

    def _on_confirm(self):
        """Handle confirm button."""
        if self.serial_partner is not None and len(self.selected_pets) == 1:
            self._start_serial_jogress()
            return

        if len(self.selected_pets) != 2:
            runtime_globals.game_sound.play("cancel")
            return
        
        # Check compatibility
        pet1 = self.selectable_pets[self.selected_pets[0]]
        pet2 = self.selectable_pets[self.selected_pets[1]]
        
        if not self._check_pet_compatibility(pet1, pet2):
            runtime_globals.game_console.log("[JogressView] Pets are not compatible")
            runtime_globals.game_sound.play("cancel")
            return

        # Module jogress cost: both pets must have the stat at max
        if not self._pets_meet_jogress_cost(pet1, pet2):
            cost = self._get_jogress_cost(pet1)
            runtime_globals.game_console.log(
                f"[JogressView] Jogress requires both pets at full {cost}")
            runtime_globals.game_message.add_slide(
                f"Both pets need full {cost}!", (255, 80, 80))
            runtime_globals.game_sound.play("cancel")
            return

        # Start evolution animation (original implementation)
        self._start_evolution_animation()
    
    # ------------------------------------------------------------------
    # Jogress with a real device
    # ------------------------------------------------------------------

    def _start_serial_jogress(self):
        """Open the port, send our code, and start listening for the reply."""
        pet = self._serial_candidate()
        if not pet:
            runtime_globals.game_sound.play("cancel")
            return

        # Same cost as a jogress between two of our own: this is the same
        # evolution, and only one pet is paying it.
        if not self._pet_meets_jogress_cost(pet):
            cost = self._get_jogress_cost(pet)
            runtime_globals.game_message.add_slide(
                f"{pet.name} needs full {cost}!", (255, 80, 80))
            runtime_globals.game_sound.play("cancel")
            return

        if not self._connect_adapter():
            runtime_globals.game_message.add_slide("No adapter found!", (255, 80, 80))
            runtime_globals.game_sound.play("cancel")
            return

        from battle.sim.jogress_session import SerialJogressSession
        session = SerialJogressSession(pet, self.dcom_controller)
        if not session.start():
            runtime_globals.game_message.add_slide(
                session.failure or "Could not send the code.", (255, 80, 80))
            runtime_globals.game_sound.play("cancel")
            self._release_adapter()
            return

        self.serial_session = session
        self._set_serial_status("Hold your device to the adapter and start "
                                "the jogress on it.")
        runtime_globals.game_sound.play("menu")

    def _connect_adapter(self):
        """Open the adapter's port. True once it is talking to us."""
        try:
            from battle.dcom.dcom_controller import DComController
            if self.dcom_controller and self.dcom_controller.connected:
                return True
            self.dcom_controller = DComController()
            devices = self.dcom_controller.find_dcom_devices()
            if not devices:
                self.serial_available = False
                self._refresh_serial_slot()
                return False
            port, description = devices[0]
            runtime_globals.game_console.log(
                f"[JogressView] Connecting to {description} on {port}")
            return bool(self.dcom_controller.connect(port))
        except Exception as error:
            runtime_globals.game_console.log(
                f"[JogressView] Adapter connection failed: {error}")
            return False

    def _release_adapter(self):
        """Give the port back, so the next screen can have it."""
        if self.dcom_controller:
            try:
                self.dcom_controller.disconnect()
            except Exception as error:
                runtime_globals.game_console.log(
                    f"[JogressView] Error closing the port: {error}")
        self.dcom_controller = None

    def _set_serial_status(self, text):
        """Show the exchange's progress where the buttons were.

        **Hidden is not disabled.** `Button` gates its clicks and its
        keypresses on `enabled` alone and never looks at `visible`, so a
        button taken off the screen still answers a press where it used to
        be -- and CONFIRM during a live exchange would start a second one on
        a port the first is already holding. Both go out together.
        """
        if self.confirm_button:
            self.confirm_button.visible = False
            self.confirm_button.set_enabled(False)
        if self.back_button:
            self.back_button.visible = False
            self.back_button.set_enabled(False)
        if self.pet_selector:
            self.pet_selector.set_interactive(False)
        if self.status_label:
            self.status_label.visible = True
            self.status_label.set_text(text)

    def _poll_serial(self):
        """Drain the adapter a frame at a time while the exchange is open.

        Polled rather than blocking: the player has to walk to the toy and
        press its button, and the game must not freeze for the minute that
        takes.
        """
        session = self.serial_session
        if not session or session.partner:
            return

        port = getattr(self.dcom_controller, "serial_port", None)
        try:
            while port is not None and port.in_waiting > 0:
                line = port.readline().decode("utf-8", errors="ignore").strip()
                if line and session.consume_line(line):
                    self._finish_serial_exchange()
                    return
        except Exception as error:
            runtime_globals.game_console.log(f"[JogressView] Read failed: {error}")
            self._abort_serial("Lost the adapter.")
            return

        if session.timed_out:
            self._abort_serial(session.diagnosis() or "The device did not answer.")

    def _finish_serial_exchange(self):
        """The device answered. Work out what it means, then animate."""
        session = self.serial_session
        route = session.resolve()
        partner = session.partner_name()

        if not route:
            # The device presented something this pet has no route for. That
            # is a real answer, not a fault -- say who it was and stop.
            self._abort_serial(f"{session.pet.name} has no jogress with {partner}.")
            return

        runtime_globals.game_console.log(
            f"[JogressView] {session.pet.name} + {partner} -> {route.get('to')}")
        self._release_adapter()
        if self.status_label:
            self.status_label.visible = False
        # Only now does the animation start: the exchange decides the outcome,
        # exactly as compatibility does for a jogress between two of our own.
        self._start_evolution_animation()

    def _abort_serial(self, message):
        """Give up on the exchange and hand the screen back to the player."""
        runtime_globals.game_console.log(
            f"[JogressView] Serial jogress ended: {message}")
        self.serial_session = None
        self._release_adapter()
        if self.status_label:
            self.status_label.visible = False
        if self.confirm_button:
            self.confirm_button.visible = True
            # Back to whatever the current selection allows, not a flat True:
            # the exchange may have ended with nothing selected.
            self.confirm_button.set_enabled(
                len(self.selected_pets) == 2
                or (len(self.selected_pets) == 1
                    and self.serial_partner is not None))
        if self.back_button:
            self.back_button.visible = True
            self.back_button.set_enabled(True)
        if self.pet_selector:
            self.pet_selector.set_interactive(True)
        runtime_globals.game_message.add_slide(message, (255, 80, 80))
        runtime_globals.game_sound.play("cancel")

    def _perform_serial_jogress(self):
        """Evolve our pet along the route the device's answer resolved to.

        Single and Dual are not consulted. They decide how many pets come out
        of a jogress between two of ours; over the wire the device keeps its
        own pet and evolves it itself, so ours simply takes its route.
        """
        session = self.serial_session
        self.serial_session = None
        if not session or not session.route:
            return

        pet, route = session.pet, session.route
        partner = session.partner_name()
        if not hasattr(pet, "evolution_history"):
            pet.evolution_history = []
        if partner:
            pet.evolution_history.append(partner)

        if not pet.evolve_to(route["to"], pet.version):
            # evolve_to refuses a target missing on this version rather than
            # half-evolving, so the pet is exactly as it was.
            runtime_globals.game_message.add_slide(
                "{0} is missing from this module!".format(route["to"]),
                (255, 80, 80))
            runtime_globals.game_sound.play("fail")
            change_scene("game")
            return

        self._apply_jogress_cost([pet])
        runtime_globals.game_console.log(
            f"[Jogress] {pet.name} jogressed with {partner} over serial!")
        from utils.quest_event_utils import update_evolution_quest_progress
        update_evolution_quest_progress("jogress", pet.module)
        change_scene("game")

    def _perform_jogress(self):
        """Carry out the fusion the two selected pets are eligible for.

        Two outcomes, decided by the route's own type rather than by how the
        partner happened to be matched:

          Single  the partner is absorbed - it evolves too (so the form is
                  recorded in the digidex) and then leaves the party;
          Dual    both pets stay, each evolving along ITS OWN route, so a
                  cross-version pair can produce two different Digimon
                  (Tengumon + SeitenGokuumon -> Enmamon + Shakamon).
        """
        pet1 = self.selectable_pets[self.selected_pets[0]]
        pet2 = self.selectable_pets[self.selected_pets[1]]

        if pet1.module != pet2.module:
            runtime_globals.game_console.log("[JogressView] Module mismatch")
            return

        from utils.jogress_utils import find_route, is_dual

        evo = find_route(pet1, pet2)
        if evo is None:
            # Only the partner declares the pairing: run it from that side so
            # the result does not depend on selection order.
            evo = find_route(pet2, pet1)
            if evo is not None:
                pet1, pet2 = pet2, pet1
        if evo is None:
            runtime_globals.game_console.log("[Jogress] Invalid combination.")
            runtime_globals.game_sound.play("fail")
            return

        if is_dual(evo):
            self._jogress_dual(pet1, pet2, evo)
        else:
            self._jogress_single(pet1, pet2, evo)

        runtime_globals.game_sound.play("evolution")
        from utils.quest_event_utils import update_evolution_quest_progress
        update_evolution_quest_progress("jogress", pet1.module)
        change_scene("game")

    def _jogress_single(self, pet1, pet2, evo):
        """2 in, 1 out - pet2 is absorbed into pet1."""
        if not hasattr(pet1, 'evolution_history'):
            pet1.evolution_history = []
        pet1.evolution_history.append(pet2.name)
        # 2->1 fusion: only score the evolution once (pet2 is absorbed), but
        # still evolve pet2 first so the form lands in the digidex.
        pet1.evolve_to(evo["to"], pet1.version)
        pet2.evolve_to(evo["to"], pet2.version, reward=False)
        # Carry the partner's special traits over to the survivor.
        if pet2.traited:
            pet1.traited = True
        if pet2.shiny:
            pet1.shiny = True
        if pet2.shook:
            pet1.shook = True
        if pet2 in game_globals.pet_list:
            game_globals.pet_list.remove(pet2)
        # The absorbed partner leaves the party, so the survivors get a
        # bigger slot.
        from utils.pet_utils import refresh_pet_sizes
        refresh_pet_sizes()
        self._apply_jogress_cost([pet1])
        runtime_globals.game_console.log(
            f"[Jogress] {pet1.name} jogressed to {evo['to']}!")

    def _jogress_dual(self, pet1, pet2, evo):
        """2 in, 2 out - each pet evolves along its own route, both stay."""
        from utils.jogress_utils import find_route

        evo2 = find_route(pet2, pet1)
        pet1.evolve_to(evo["to"], pet1.version)
        if evo2:
            pet2.evolve_to(evo2["to"], pet2.version)
            self._apply_jogress_cost([pet1, pet2])
            runtime_globals.game_console.log(
                f"[Jogress] dual: {evo['to']} + {evo2['to']}")
        else:
            # The partner declares no route back, so only pet1 evolves - but
            # it is NOT absorbed either, this is still a dual jogress.
            self._apply_jogress_cost([pet1])
            runtime_globals.game_console.log(
                f"[Jogress] dual: {evo['to']} (partner had no route back)")

    def _on_back(self):
        """Handle back button."""
        runtime_globals.game_sound.play("cancel")
        self.change_view("main_menu")
    
    def cleanup(self):
        """Remove all UI components."""
        # An open exchange must not outlive the screen, or the port stays
        # claimed and the next connection screen cannot have it.
        self.serial_session = None
        self._release_adapter()
        if self.status_label:
            self.ui_manager.remove_component(self.status_label)
        if self.background:
            self.ui_manager.remove_component(self.background)
        if self.title_scene:
            self.ui_manager.remove_component(self.title_scene)
        if self.pet_selector:
            self.ui_manager.remove_component(self.pet_selector)
        if self.jogress_display:
            self.ui_manager.remove_component(self.jogress_display)
        if self.confirm_button:
            self.ui_manager.remove_component(self.confirm_button)
        if self.back_button:
            self.ui_manager.remove_component(self.back_button)
    
    def _start_evolution_animation(self):
        """Start the Jogress evolution animation with circles and particles."""
        import math
        
        self.evolution_animation_active = True
        self.evolution_animation_timer = 0.0
        self.pet_circles = []
        self.particles = []
        
        # Hide confirm and back buttons during animation
        if self.confirm_button:
            self.confirm_button.visible = False
        if self.back_button:
            self.back_button.visible = False
            
        # Hide the pet sprites in the JogressDisplay
        if self.jogress_display:
            self.jogress_display.set_hide_pet_sprites(True)
            
        # Get pet positions from jogress display
        if self.jogress_display:
            # Convert base coordinates to screen coordinates
            if self.ui_manager:
                # Get the jogress display's screen position
                display_rect = self.jogress_display.rect
                display_offset_x = display_rect.x
                display_offset_y = display_rect.y
                
                # Pet circle positions (bottom hexagons)
                if self.jogress_display.bottom_left_center and self.jogress_display.bottom_right_center:
                    left_center = self.jogress_display.bottom_left_center
                    right_center = self.jogress_display.bottom_right_center
                    
                    # Convert to screen coordinates
                    left_screen_x = display_offset_x + self.ui_manager.scale_value(left_center[0])
                    left_screen_y = display_offset_y + self.ui_manager.scale_value(left_center[1])
                    right_screen_x = display_offset_x + self.ui_manager.scale_value(right_center[0])
                    right_screen_y = display_offset_y + self.ui_manager.scale_value(right_center[1])
                    
                    # Initial circle radius
                    initial_radius = self.ui_manager.scale_value(self.jogress_display.base_hexagon_size) * 0.6
                    
                    # Create pet circles
                    self.pet_circles = [
                        {
                            "x": left_screen_x,
                            "y": left_screen_y, 
                            "initial_radius": initial_radius,
                            "current_radius": initial_radius,
                            "color": (255, 255, 255)  # White
                        },
                        {
                            "x": right_screen_x,
                            "y": right_screen_y,
                            "initial_radius": initial_radius, 
                            "current_radius": initial_radius,
                            "color": (255, 255, 255)  # White
                        }
                    ]
        
        runtime_globals.game_console.log("[JogressView] Evolution animation started")
    
    def _update_evolution_animation(self):
        """Update the evolution animation state."""
        if not self.evolution_animation_active:
            return
            
        import random
        import math
        
        # Update timer
        dt = 1.0 / 30.0  # Assume 30 FPS
        self.evolution_animation_timer += dt
        
        # Animation progress (0.0 to 1.0)
        progress = min(self.evolution_animation_timer / self.evolution_animation_duration, 1.0)
        
        # Phase 1: Spawn particles and shrink circles (first 80% of animation)
        if progress < 0.8:
            phase_progress = progress / 0.8
            
            # Shrink pet circles
            for circle in self.pet_circles:
                circle["current_radius"] = circle["initial_radius"] * (1.0 - phase_progress)
                
            # Spawn particles from circles
            if random.random() < 0.3:  # 30% chance per frame
                for circle in self.pet_circles:
                    if circle["current_radius"] > 2:  # Only spawn from visible circles
                        # Get target position (top hexagon center)
                        target_x, target_y = self._get_top_hexagon_screen_center()
                        
                        # Spawn particle at circle edge
                        angle = random.uniform(0, 2 * math.pi)
                        spawn_x = circle["x"] + math.cos(angle) * circle["current_radius"]
                        spawn_y = circle["y"] + math.sin(angle) * circle["current_radius"]
                        
                        # Calculate movement vector
                        dx = target_x - spawn_x
                        dy = target_y - spawn_y
                        distance = math.sqrt(dx * dx + dy * dy)
                        
                        if distance > 0:
                            # Normalize and set speed
                            speed = 3.0  # pixels per frame
                            vx = (dx / distance) * speed
                            vy = (dy / distance) * speed
                            
                            # Add particle
                            self.particles.append({
                                "x": spawn_x,
                                "y": spawn_y,
                                "vx": vx,
                                "vy": vy,
                                "target_x": target_x,
                                "target_y": target_y,
                                "life": 1.0,
                                "size": random.uniform(2, 4)
                            })
        
        # Update particles
        for particle in self.particles[:]:  # Copy list to allow removal
            particle["x"] += particle["vx"]
            particle["y"] += particle["vy"]
            particle["life"] -= 0.02  # Fade out
            
            # Check if particle reached target or faded out
            dx = particle["target_x"] - particle["x"]
            dy = particle["target_y"] - particle["y"]
            distance = math.sqrt(dx * dx + dy * dy)
            
            if distance < 5 or particle["life"] <= 0:
                self.particles.remove(particle)
        
        # Phase 2: Complete animation (last 20%)
        if progress >= 0.8:
            # Clear remaining particles and circles
            if progress >= 0.9:
                self.particles.clear()
                for circle in self.pet_circles:
                    circle["current_radius"] = 0
        
        # End animation and perform evolution
        if progress >= 1.0:
            self.evolution_animation_active = False
            runtime_globals.game_console.log("[JogressView] Evolution animation completed, performing Jogress...")
            # The same animation serves both: two circles feeding one result.
            # Only what happens at the end differs, because a serial jogress
            # has one pet of ours and a route the device already decided.
            if self.serial_session is not None:
                self._perform_serial_jogress()
            else:
                self._perform_jogress()
    
    def _get_top_hexagon_screen_center(self):
        """Get the screen coordinates of the top hexagon center."""
        if self.jogress_display and self.jogress_display.top_hexagon_center:
            # Get the jogress display's screen position
            display_rect = self.jogress_display.rect
            display_offset_x = display_rect.x
            display_offset_y = display_rect.y
            
            top_center = self.jogress_display.top_hexagon_center
            screen_x = display_offset_x + self.ui_manager.scale_value(top_center[0])
            screen_y = display_offset_y + self.ui_manager.scale_value(top_center[1])
            
            return screen_x, screen_y
        return 120, 60  # Fallback center
    
    def _draw_evolution_animation(self, surface):
        """Draw the evolution animation over the UI."""
        if not self.evolution_animation_active:
            return
            
        # Draw pet circles
        for circle in self.pet_circles:
            if circle["current_radius"] > 0:
                pygame.draw.circle(
                    surface, 
                    circle["color"], 
                    (int(circle["x"]), int(circle["y"])), 
                    int(circle["current_radius"])
                )
        
        # Draw particles
        for particle in self.particles:
            if particle["life"] > 0:
                # Fade particle alpha based on life
                alpha = int(255 * particle["life"])
                color = (255, 255, 255, alpha)
                
                # Create a small surface for the particle with alpha
                particle_surface = pygame.Surface((int(particle["size"] * 2), int(particle["size"] * 2)), pygame.SRCALPHA)
                pygame.draw.circle(
                    particle_surface, 
                    color[:3],  # RGB only for circle
                    (int(particle["size"]), int(particle["size"])), 
                    int(particle["size"])
                )
                
                # Set surface alpha
                particle_surface.set_alpha(alpha)
                
                # Blit to main surface
                surface.blit(
                    particle_surface, 
                    (int(particle["x"] - particle["size"]), int(particle["y"] - particle["size"]))
                )
    
    def update(self):
        """Update the view."""
        # Serial exchange, if one is open
        self._poll_serial()

        # Update evolution animation
        self._update_evolution_animation()
    
    def draw(self, surface: pygame.Surface):
        """Draw the view."""
        # Draw evolution animation over the UI
        self._draw_evolution_animation(surface)
    
    def handle_event(self, event):
        """Handle input events."""
        if not isinstance(event, tuple) or len(event) != 2:
            return
        event_type, event_data = event
        if event_type == "B":
            self._on_back()
