"""
WiFiComView - Omnipet on the air as a WiFiCom.

The view is thin: `services/wificom_service.py` owns the MQTT connection and
runs it on its own thread, and this reports what that thread is doing and
offers the two things the player can do about it.

    Battle!  put the pet's packets on the wire
    Back     take the service down and return to the local battle menu

The protocol is never chosen here. A WiFiCom battle always speaks the
`battle_protocol` of the selected pet's own module -- which is also what
makes it an OEM battle, so the pet goes out with its real index and version
rather than as an outsider.
"""
from ui.ui_manager import UIManager
from ui.components.title_scene import TitleScene
from ui.components.button import Button
from ui.components.background import Background
from ui.components.label import Label
from ui.ui_constants import BASE_RESOLUTION
from core import runtime_globals
from battle.sim import protocol_constants
from services.wificom_service import wificom_service, STATE_ONLINE


class WiFiComView:
    """The waiting screen for a WiFiCom battle."""

    def __init__(self, ui_manager: UIManager, change_view_callback,
                 selected_pets=None, discord_module=None):
        """Initialize the WiFiCom view.

        Args:
            ui_manager: The UI manager instance
            change_view_callback: Callback to change to another view
            selected_pets: The pet that will fight, as a one-item list
        """
        self.ui_manager = ui_manager
        self.change_view = change_view_callback
        self.selected_pets = selected_pets or []
        self.pet = self.selected_pets[0] if self.selected_pets else None

        self.battle_format = self._pet_battle_format()
        #: Replaces the status line for a few seconds after Battle! is
        #: pressed, then clears back to whatever the service reports.
        self._message = None
        self._message_until = 0
        self._last_status = None

        # UI Components
        self.background = None
        self.title_scene = None
        self.status_label = None
        self.pet_label = None
        self.format_label = None
        self.battle_button = None
        self.back_button = None

        self._setup_ui()
        self._start_service()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _pet_battle_format(self):
        """The battle_protocol of the pet's module, canonicalised, or None."""
        if self.pet is None:
            return None
        try:
            from utils.module_utils import get_module
            module = get_module(getattr(self.pet, 'module', ''))
            declared = getattr(module, 'battle_protocol', '') if module else ''
            return protocol_constants.canonical_format(declared) or None
        except Exception:  # pylint: disable=broad-except
            return None

    def _setup_ui(self):
        """Setup the UI components."""
        ui_width = ui_height = BASE_RESOLUTION

        self.background = Background(ui_width, ui_height)
        self.background.set_regions([(0, ui_height, "black")])
        self.ui_manager.add_component(self.background)

        self.title_scene = TitleScene(0, 9, "WIFICOM")
        self.ui_manager.add_component(self.title_scene)

        self.status_label = Label(
            ui_width // 2, 62, "Connecting...", is_title=True, center=True,
            word_wrap=True, max_width=ui_width - 24, center_lines=True
        )
        self.ui_manager.add_component(self.status_label)

        pet_name = getattr(self.pet, 'name', 'No pet') if self.pet else 'No pet'
        self.pet_label = Label(
            ui_width // 2, 130, pet_name, center=True,
            word_wrap=True, max_width=ui_width - 24, center_lines=True
        )
        self.ui_manager.add_component(self.pet_label)

        format_name = self._format_display_name()
        self.format_label = Label(
            ui_width // 2, 150, format_name, center=True,
            word_wrap=True, max_width=ui_width - 24, center_lines=True
        )
        self.ui_manager.add_component(self.format_label)

        btn_width = 80
        btn_height = 26
        btn_gap = 16
        btn_y = ui_height - btn_height - 18
        battle_x = (ui_width // 2) - btn_width - (btn_gap // 2)
        back_x = (ui_width // 2) + (btn_gap // 2)

        self.battle_button = Button(
            battle_x, btn_y, btn_width, btn_height,
            "BATTLE!", self._on_battle,
            cut_corners={'tl': False, 'tr': True, 'bl': False, 'br': True}
        )
        # Nothing to send until the service is up.
        self.battle_button.enabled = False
        self.ui_manager.add_component(self.battle_button)

        self.back_button = Button(
            back_x, btn_y, btn_width, btn_height,
            "BACK", self._on_back,
            cut_corners={'tl': True, 'tr': False, 'bl': True, 'br': False}
        )
        self.ui_manager.add_component(self.back_button)

        self.ui_manager.set_focused_component(self.back_button)

        runtime_globals.game_console.log("[WiFiComView] UI setup complete")

    def _format_display_name(self):
        """The device line being spoken, for the player to read."""
        if not self.battle_format:
            return "No protocol"
        constants = protocol_constants.get_constants(self.battle_format)
        return getattr(constants, 'DISPLAY_NAME', self.battle_format)

    def _start_service(self):
        """Bring Omnipet up as a WiFiCom."""
        if self.pet is None or not self.battle_format:
            self._show_message("No pet to battle with")
            return
        # An incoming DigiROM is played against this pet, so the service has
        # to know which one before it is listening.
        wificom_service.set_pet(self.pet, self.battle_format)
        wificom_service.start()

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------

    def _on_battle(self):
        """Battle! -- open one, as the starter.

        A WiFiCom is starter-agnostic: this screen answers a battle anyone
        else opens, and this is how it opens one of its own. Only the first
        packet goes out; the rest follow as the other side replies.
        """
        if self.pet is None or not self.battle_format:
            return
        runtime_globals.game_sound.play("menu")
        (sent, detail) = wificom_service.start_battle()
        if sent:
            self._show_message("Battle sent, waiting...")
        else:
            self._show_message(detail)

    def _on_back(self):
        """Back -- take the service down and leave."""
        runtime_globals.game_sound.play("cancel")
        wificom_service.stop()
        self.change_view("main_menu", initial_submenu="local_battle")

    def _show_message(self, text, seconds=3.0):
        """Show *text* in place of the service status for a moment."""
        import time
        self._message = text
        self._message_until = time.monotonic() + seconds
        runtime_globals.game_console.log(f"[WiFiComView] {text}")

    # ------------------------------------------------------------------
    # Frame
    # ------------------------------------------------------------------

    def update(self):
        """Follow the service's state."""
        import time

        if self._message is not None and time.monotonic() >= self._message_until:
            self._message = None

        status = self._message or wificom_service.status_text
        if wificom_service.rtb_active and self._message is None:
            code = wificom_service.rtb_invite_code
            if code:
                status = f"Battle #{code}"

        if status != self._last_status:
            self._last_status = status
            self.status_label.set_text(status)

        # Only offer Battle! once there is a connection to send it down, and
        # not while one is already running.
        running = wificom_service.battle is not None
        online = (wificom_service.state == STATE_ONLINE
                  and self.battle_format is not None and not running)
        if self.battle_button.enabled != online:
            self.battle_button.set_enabled(online)

        # A finished exchange goes to the battle scene, the same way a DCom
        # one does -- both sides of a WiFiCom battle watch it play out.
        self._check_finished_battle()

    def _check_finished_battle(self):
        """Hand a completed exchange to the battle scene."""
        finished = wificom_service.take_finished_battle()
        if not finished:
            return
        battle, result = finished
        opponent = battle.opponent()
        if opponent is None:
            self._show_message("Could not read the opponent")
            return
        runtime_globals.game_console.log(
            "[WiFiComView] %s exchange complete, playing it out"
            % battle.battle_format)
        try:
            from battle.dcom import pvp_payload

            pvp_payload.build(self.pet, opponent, result, battle.battle_format,
                              battle.exchange.simulator,
                              opponent_name="WiFiCom")
        except Exception as error:  # pylint: disable=broad-except
            runtime_globals.game_console.log(
                f"[WiFiComView] Could not build the battle: {error!r}")
            self._show_message("Could not start the battle")
            return
        from utils.scene_utils import change_scene

        wificom_service.stop()
        change_scene("battle_pvp")

    def draw(self, surface):
        """Draw additional elements."""
        pass

    def handle_event(self, event):
        """Handle input events."""
        if not isinstance(event, tuple) or len(event) != 2:
            return

        event_type, _ = event

        if event_type == "B":
            self._on_back()
            return True

    def cleanup(self):
        """Cleanup when view is destroyed.

        The service is stopped here as well as in Back, because the view can
        also be left by an error or a scene change, and a live MQTT
        connection must not outlive the screen that owns it.
        """
        wificom_service.stop()

        components = [
            self.background, self.title_scene, self.status_label,
            self.pet_label, self.format_label,
            self.battle_button, self.back_button,
        ]

        for comp in components:
            if comp and comp in self.ui_manager.components:
                self.ui_manager.remove_component(comp)

        runtime_globals.game_console.log("[WiFiComView] Cleanup complete")
