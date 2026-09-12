"""
DComView - battling a real Digimon toy through a DCom adapter.

The view drives the flow and owns nothing about the protocols:

    scan -> connect -> pick the device line -> charge minigame -> exchange
    -> hand the result to the PvP battle scene

``DComBattleSimulator`` owns every wire decision (which packets, how many to
expect, how to parse them) and ``MinigameSession`` owns the charge.  Both are
shared with the rest of the battle code; this view used to carry its own
copies of both, and they went stale -- the Count Match minigames were built
without the AnimatedSprite they draw through, and PENZ generated six packets
then looked for ten when building the battle log.

The exchange itself is polled a frame at a time rather than run through
``simulate_with_device``: that one blocks for its whole timeout, which would
freeze the game for a minute while the player presses the button on the toy.

The adapter reports why every failed read failed, and those codes are the
only account of a connection that never gets going, so they are counted and
shown to the player instead of a bare countdown.
"""
import time
import re

from ui.ui_manager import UIManager
from ui.components.title_scene import TitleScene
from ui.components.button import Button
from ui.components.background import Background
from ui.components.label import Label
from ui.components.menu import Menu
from ui.minigames.minigame_session import MinigameSession
from ui.ui_constants import BASE_RESOLUTION
from core import runtime_globals
from battle.dcom.dcom_controller import DComController
from battle.dcom.dcom_protocol import EMPTY_PACKET, describe_status
from battle.sim import protocol_constants
from battle.sim.exchange import PacketExchange
from battle.sim.dcom_battle_simulator import (DComBattleSimulator, is_oem_pet,
                                              pet_to_digimon)

#: How long to wait for the player to start the battle on the real toy.
COMM_TIMEOUT_SECONDS = 60.0

#: Half way through the wait, with nothing received, the other turn is tried:
#: some toys open the exchange and some wait to be spoken to, and which is
#: which is exactly what we cannot see from here.
TURN_SWAP_SECONDS = COMM_TIMEOUT_SECONDS / 2

#: An adapter that drops off the bus mid-wait -- a nudged USB connector, most
#: likely, since the player is standing at the toy and not at the keyboard --
#: is worth recovering from quietly. The bus is re-checked this often; the
#: port is only reopened once the adapter is enumerated again, because
#: opening one costs two and a half seconds of frozen game while the Arduino
#: takes its reset.
RECONNECT_INTERVAL_SECONDS = 2.0

#: How long to keep trying before giving up and saying so. Long enough to
#: cover pushing a connector back in, short enough not to retry all session.
RECONNECT_WINDOW_SECONDS = 30.0

class DComView:
    """DCom view for device battles."""

    def __init__(self, ui_manager: UIManager, change_view_callback,
                 selected_pets=None, is_dcom_mode=True, discord_module=None):
        """Initialize the DCom view.

        Args:
            ui_manager: The UI manager instance
            change_view_callback: Callback to change to another view
            selected_pets: List of selected pets for battle
            is_dcom_mode: Whether this is DCom mode (always True for this view)
        """
        self.ui_manager = ui_manager
        self.change_view = change_view_callback
        self.selected_pets = selected_pets or []

        # device_list, protocol_select, minigame, communicating
        self.phase = "device_list"
        self.dcom_controller = None
        self.dcom_selected_device = None
        self.simulator = None
        self.battle_format = None
        self.format_menu = []

        # Device discovery
        self.discovered_devices = []

        # Charge minigame
        self.minigame = None
        self.minigame_result = 0
        self._minigame_settle_at = 0

        # Communication state
        self.communicating = False
        self.comm_start_time = 0
        self.response_packets = []
        self.player_packets = []
        # What the adapter has been reporting: {code: (count, explanation)}.
        # Its status codes are the only diagnosis a connection that never gets
        # going ever produces, so they are counted rather than discarded.
        self.status_counts = {}
        self.empty_reads = 0
        self.turn = None
        self._turn_swapped = False
        self._opened_at = 0.0
        #: Who attacks first in the battle we hand to the scene. The toy
        #: normally opens the exchange, so it normally strikes first; if we
        #: open it, we do.
        self.enemy_first = True
        self._version_retried = False
        self._device_answered = False
        self._last_status_log = 0
        self._last_comm_log = 0
        # Set while the adapter is missing from the bus (see _on_port_lost).
        self._port_lost = False
        #: Set when the adapter answers as a Python prompt rather than as
        #: firmware -- see _looks_like_repl.
        self._repl_seen = False
        self._port_lost_at = 0
        self._next_reconnect_at = 0
        self._last_reconnect_log = 0
        self._reconnect_attempts = 0

        # UI Components
        self.background = None
        self.title_scene = None
        self.status_label = None
        self.device_menu = None
        self.protocol_menu = None
        self.cancel_button = None
        self.start_button = None

        # Set when the view cannot run at all. The hand-off waits for the
        # first update(): changing views from inside a constructor leaves the
        # scene overwriting the new view with this one.
        self.abort = False

        self._setup_ui()

        # Pets should be selected before reaching this view
        if not self.selected_pets:
            runtime_globals.game_console.log("[DComView] ERROR: No pets selected!")
            self.abort = True
            return

        # Start device scan
        self._start_dcom_scan()

    @property
    def pet(self):
        """The pet fighting this battle (a temporary evolution, if one was chosen)."""
        return self.selected_pets[0] if self.selected_pets else None

    def _setup_ui(self):
        """Setup the UI components."""
        ui_width = ui_height = BASE_RESOLUTION

        # Background
        self.background = Background(ui_width, ui_height)
        self.background.set_regions([(0, ui_height, "black")])
        self.ui_manager.add_component(self.background)

        # Title
        self.title_scene = TitleScene(0, 9, "CONNECT")
        self.ui_manager.add_component(self.title_scene)

        # Status label with word wrapping
        self.status_label = Label(10, 60, "Scanning for DCom...", is_title=False,
                                  word_wrap=True, max_width=220)
        self.ui_manager.add_component(self.status_label)

        # Cancel button
        cancel_width = 100
        cancel_height = 35
        cancel_x = (BASE_RESOLUTION - cancel_width) // 2
        cancel_y = 195

        # **A button rather than a keypress.** Waiting for START or A means
        # the player has to know the keypress exists, and gets no sign that
        # it landed -- which is what made a working first press look inert
        # and invited a second. A button says it is there, takes the focus so
        # it can be pressed without hunting, and changes to LOADING the
        # moment it is used.
        self.start_button = Button(
            cancel_x, cancel_y - cancel_height - 10, cancel_width,
            cancel_height, "START", self._on_start
        )
        self.start_button.visible = False
        self.ui_manager.add_component(self.start_button)

        self.cancel_button = Button(
            cancel_x, cancel_y, cancel_width, cancel_height,
            "CANCEL", self._on_cancel
        )
        self.ui_manager.add_component(self.cancel_button)

        runtime_globals.game_console.log("[DComView] UI setup complete")

    # ------------------------------------------------------------------
    # Device discovery and connection
    # ------------------------------------------------------------------

    def _start_dcom_scan(self):
        """Scan for DCom devices."""
        runtime_globals.game_console.log("[DComView] Starting DCom device scan...")

        try:
            import serial.tools.list_ports  # noqa: F401
        except ImportError:
            runtime_globals.game_console.log("[DComView] pyserial not installed")
            self.status_label.set_text("ERROR: pyserial not installed!")
            return

        try:
            if not self.dcom_controller:
                self.dcom_controller = DComController()

            # List all ports
            all_ports = DComController.list_all_ports()
            runtime_globals.game_console.log(f"[DComView] Found {len(all_ports)} serial ports")

            # Find DCom devices
            self.discovered_devices = self.dcom_controller.find_dcom_devices()

            if not self.discovered_devices:
                if all_ports:
                    self.status_label.set_text(f"No DCom found ({len(all_ports)} ports)")
                else:
                    self.status_label.set_text("No serial ports found!")
                return

            runtime_globals.game_console.log(f"[DComView] Found {len(self.discovered_devices)} DCom device(s)")
            self.status_label.set_text(f"Found {len(self.discovered_devices)} device(s)")

            # Auto-select if only one device
            if len(self.discovered_devices) == 1:
                self._on_device_select(0)
                return

            # Show device selection menu
            device_options = [desc for port, desc in self.discovered_devices]
            self.device_menu = Menu(width=180, height=140)
            self.device_menu.open(device_options, self._on_device_select,
                                  on_cancel=self._on_cancel)
            self.ui_manager.add_component(self.device_menu)
            self.ui_manager.set_active_menu(self.device_menu)

        except Exception as e:
            runtime_globals.game_console.log(f"[DComView] Scan error: {e}")
            self.status_label.set_text(f"Scan error: {str(e)}")

    def _on_device_select(self, index):
        """Device selected from menu."""
        if index >= len(self.discovered_devices):
            return

        port, desc = self.discovered_devices[index]
        runtime_globals.game_console.log(f"[DComView] Selected: {desc} on {port}")
        self.dcom_selected_device = (port, desc)

        self._close_menu('device_menu')

        # Connect to device
        try:
            if not self.dcom_controller:
                self.dcom_controller = DComController()

            if not self.dcom_controller.connect(port):
                raise Exception("Failed to connect")

            runtime_globals.game_console.log("[DComView] Connected!")
            self._show_protocol_selection()

        except Exception as e:
            runtime_globals.game_console.log(f"[DComView] Connection error: {e}")
            self.status_label.set_text(f"Error: {str(e)}")
            if self.dcom_controller:
                self.dcom_controller.disconnect()

    def _close_menu(self, attribute):
        """Close and forget one of the view's menus."""
        menu = getattr(self, attribute, None)
        if not menu:
            return
        menu.close()
        if self.ui_manager.active_menu is menu:
            self.ui_manager.active_menu = None
        self.ui_manager.remove_component(menu)
        setattr(self, attribute, None)

    # ------------------------------------------------------------------
    # Device line selection
    # ------------------------------------------------------------------

    def _show_protocol_selection(self):
        """Show the device-line menu."""
        runtime_globals.game_console.log("[DComView] Showing protocol selection...")
        self.phase = "protocol_select"
        self.status_label.set_text("Which device?")

        # Shared with the versus protocol menu, so the two always offer the
        # same device lines.
        self.format_menu = protocol_constants.menu_entries()
        options = [label for _, label in self.format_menu]
        options.append("Cancel")

        self.protocol_menu = Menu(width=200, height=140)
        self.protocol_menu.open(options, self._on_protocol_select,
                                on_cancel=self._on_cancel)
        self.ui_manager.add_component(self.protocol_menu)
        self.ui_manager.set_active_menu(self.protocol_menu)

        # Start on the line the selected pet's own module belongs to.
        pet_module = self._pet_battle_protocol()
        if pet_module in protocol_constants.BATTLE_FORMATS:
            self.protocol_menu.selected_index = protocol_constants.BATTLE_FORMATS.index(pet_module)

    def _pet_battle_protocol(self):
        """The battle_protocol of the selected pet's module, or None."""
        try:
            from utils.module_utils import get_module
            module = get_module(getattr(self.pet, 'module', ''))
            return getattr(module, 'battle_protocol', None) if module else None
        except Exception:
            return None

    def _on_protocol_select(self, index):
        """Device line selected from menu."""
        self._close_menu('protocol_menu')

        if index >= len(self.format_menu):
            self._on_cancel()
            return

        self.battle_format = self.format_menu[index][0]
        self.simulator = DComBattleSimulator(self.dcom_controller,
                                             battle_format=self.battle_format)
        runtime_globals.game_console.log(
            f"[DComView] Battle format: {self.battle_format}")
        self._start_minigame()

    # ------------------------------------------------------------------
    # Charge minigame
    # ------------------------------------------------------------------

    def _start_minigame(self):
        """Play the charge minigame this device line uses, if it has one."""
        name = self.simulator.minigame
        if name == "None":
            # No charge to make: the boost comes from items on these devices.
            self.minigame_result = 0
            self._start_communication()
            return

        self.phase = "minigame"
        self.minigame = MinigameSession(name, self.ui_manager, self.pet)
        self.cancel_button.visible = False
        if self.start_button:
            self.start_button.visible = False

    def _finish_minigame(self):
        """Take the charge value and move on after a short settle."""
        # The wire decides what the charge means: a raw 0-14 meter on the
        # DM20 line, a 0-3 quality on the DMX one.
        self.minigame_result = self.simulator.charge_value(self.minigame)
        runtime_globals.game_console.log(
            f"[DComView] Charge complete: {self.minigame_result}")
        self.minigame = None
        # A short pause so the last press of a mashed minigame cannot fall
        # through onto whatever is drawn next.
        self._minigame_settle_at = time.time() + 0.5

    # ------------------------------------------------------------------
    # Serial exchange
    # ------------------------------------------------------------------

    def _start_communication(self):
        """Send our packets and start listening for the toy's reply."""
        runtime_globals.game_console.log(
            f"[DComView] ===== {self.battle_format} EXCHANGE =====")
        self.phase = "communicating"
        self.communicating = True
        self.comm_start_time = time.time()
        self.response_packets = []
        self.status_counts = {}
        self.empty_reads = 0
        self.turn = 1 if PacketExchange.cable_opens(self.battle_format) else 2
        self.simulator.opening = self.turn == 1
        self.enemy_first = self.turn != 1
        self._turn_swapped = False
        self._version_retried = False
        self._device_answered = False
        self._last_status_log = time.time()
        self._last_comm_log = time.time()

        self.status_label.set_text("Waiting for device...")
        self.cancel_button.visible = True
        self._arm_start_button()

        if not self.pet:
            runtime_globals.game_console.log("[DComView] ERROR: No pet selected!")
            self.status_label.set_text("Error: No pet selected")
            self.communicating = False
            return

        if not self._build_and_send():
            return

        runtime_globals.game_console.log(
            f"[DComView] {COMM_TIMEOUT_SECONDS:.0f}s window open - "
            + ("hold your device to the adapter now!" if self.simulator.goes_first
               else "press START to begin, or start it on your device"))

    def _build_and_send(self) -> bool:
        """Build this turn's packets and hand them to the adapter.

        The packets depend on the turn: whoever opens the exchange carries
        Order 1, so swapping turns means regenerating, not just resending.
        """
        digimon = pet_to_digimon(self.pet, self.battle_format, self.minigame_result)
        self.exchange = PacketExchange(self.battle_format, digimon,
                                       opens=self.turn == 1, peer=False,
                                       simulator=self.simulator)
        self.player_packets = self.exchange._planned
        if not self.player_packets:
            self.status_label.set_text("Error: could not build packets")
            self.communicating = False
            return False
        self._send_packets()
        return True

    def _swap_turn(self):
        """Keep the stock adapter in its supported role after an idle wait."""
        self._turn_swapped = True
        # Stock firmware cannot calculate our final outcome mid-exchange.
        # Keep the role whose reply can be encoded, rather than send a
        # placeholder merely because the peer has not answered yet.
        self.status_label.set_text('Start battle on the device, then connect it.')

    def _arm_start_button(self):
        """Offer the button, ready to be pressed, and take the focus.

        Focused because it is the one thing to do on this screen -- the
        alternative is a player hunting for it while the sixty-second window
        runs down.
        """
        if not self.start_button:
            return
        self.start_button.set_text("START")
        self.start_button.set_enabled(True)
        self.start_button.visible = True
        self.ui_manager.set_focused_component(self.start_button)

    def _on_start(self):
        """START pressed: open the exchange, and say that we did.

        The button goes to LOADING and stops accepting input, because a
        turn-1 command can take several seconds to echo and several more to
        complete. Nothing visibly happening is what makes people press again,
        and a second press was never going to help.
        """
        if self.start_button:
            self.start_button.set_text("LOADING")
            self.start_button.set_enabled(False)
        runtime_globals.game_sound.play("menu")
        self._open_exchange()

    def _open_exchange(self):
        """Open only when the adapter can send this protocol role without guessing a result."""
        if not PacketExchange.cable_opens(self.battle_format):
            self.status_label.set_text('Start battle on the device. This adapter must answer.')
            return
        if self.turn == protocol_constants.DCOM_TURN_GO_FIRST and \
                self.simulator.opening:
            return
        self.turn = protocol_constants.DCOM_TURN_GO_FIRST
        self.simulator.opening = True
        self._turn_swapped = True      # do not let the timer swap us back
        self._opened_at = time.time()
        # **We opened, so we strike first.** A DCom battle is presented with
        # the toy attacking first because the toy is normally the one that
        # opens; when it is us, the order follows.
        self.enemy_first = False
        runtime_globals.game_console.log(
            "[DComView] START pressed: opening the exchange ourselves "
            "(turn 1, and Player 1 where the wire has roles)")
        self.status_label.set_text("Opening the battle - hold your device "
                                   "to the adapter")
        self._build_and_send()

    def _send_packets(self):
        """Send the exchange command with our packets."""
        try:
            command = self.exchange.cable_command()
            runtime_globals.game_console.log(f"[DComView] TX: {command}")
            self.dcom_controller._send_raw(command + '\r')
        except OSError as e:
            # The port went away mid-write. Not an error to abort on: the
            # recovery below reopens it and sends these same packets again.
            self._on_port_lost(e)
        except Exception as e:
            import traceback
            runtime_globals.game_console.log(f"[DComView] Error sending packets: {e}")
            runtime_globals.game_console.log(f"Traceback:\n{traceback.format_exc()}")
            self.status_label.set_text(f"Error: {str(e)}")
            self.communicating = False

    def _check_dcom_response(self) -> bool:
        """Drain the adapter; True once every packet has arrived.

        Everything waiting is read each frame rather than one line per frame:
        a real exchange arrives as a burst, and taking it a frame at a time
        spreads ten packets over ten frames for no reason.
        """
        try:
            port = getattr(self.dcom_controller, 'serial_port', None) if self.dcom_controller else None
            if not port:
                return False

            while port.in_waiting > 0:
                line = port.readline().decode('utf-8', errors='ignore').strip()
                if not line:
                    continue
                if self._consume_line(line):
                    return True
            return False
        except OSError as e:
            # The handle itself is stale -- an unplugged or nudged connector
            # raises this on every frame, for as long as it is held. Report it
            # once and go and get the adapter back instead.
            self._on_port_lost(e)
            return False
        except Exception as e:
            runtime_globals.game_console.log(f"[DComView] Error checking response: {e}")
            return False

    def _on_port_lost(self, error):
        """The adapter stopped answering the OS; start trying to get it back.

        The stale handle is dropped here so Windows can hand the port back
        when the device re-enumerates, and so the poll stops raising. The
        exchange is left running: ``_attempt_reconnect`` reopens the port and
        resends, and the player need never know it happened.
        """
        if self._port_lost:
            return

        self._port_lost = True
        self._port_lost_at = time.time()
        self._next_reconnect_at = self._port_lost_at + RECONNECT_INTERVAL_SECONDS
        runtime_globals.game_console.log(
            f"[DComView] Adapter stopped responding ({error}); reconnecting")

        self._release_port()

        if self.status_label:
            self.status_label.set_text("Reconnecting...")

    def _release_port(self):
        """Drop the adapter's handle, even if pyserial cannot close it.

        A CH340 that vanishes mid-read can make pyserial's close() raise
        before it reaches CloseHandle -- SetCommTimeouts on a dead handle is
        enough to do it. The OS handle then leaks for the life of the
        process, Windows keeps reporting the port as busy, and every
        reconnect fails with the same "access denied" that started all this.
        Closing it by hand is the only way back without restarting the game.
        """
        port = getattr(self.dcom_controller, 'serial_port', None) if self.dcom_controller else None
        try:
            if self.dcom_controller:
                self.dcom_controller.disconnect()
        except Exception:
            pass          # the handle is already unusable, which is the point

        handle = getattr(port, '_port_handle', None)
        if not handle:
            return        # close() got there first, which is the normal case
        try:
            import serial.win32 as win32
            win32.CloseHandle(handle)
            runtime_globals.game_console.log(
                "[DComView] pyserial could not close the port; released the handle by hand")
        except Exception as e:
            runtime_globals.game_console.log(
                f"[DComView] Could not release the port handle: {e}")
        try:
            port._port_handle = None
        except Exception:
            pass

    def _attempt_reconnect(self):
        """Reopen the adapter and resend the exchange, if it is back."""
        now = time.time()
        self._next_reconnect_at = now + RECONNECT_INTERVAL_SECONDS
        self._reconnect_attempts += 1

        remembered = self.dcom_selected_device[0] if self.dcom_selected_device else None

        # Candidates, best first: the port it had, then anything else on the
        # bus, since Windows can hand the adapter a different COM number when
        # it re-enumerates. Opening a port that is not there fails before the
        # two-and-a-half second Arduino reset, so trying the remembered one
        # blind costs nothing and works even when the scan cannot see it yet.
        try:
            devices = self.dcom_controller.find_dcom_devices()
        except Exception as e:
            self._log_reconnect(f"could not enumerate the ports: {e}")
            return

        candidates = []
        if remembered:
            candidates.append((remembered, remembered))
        candidates.extend((p, d) for p, d in devices if p != remembered)

        failures = []
        port = desc = None
        for candidate, label in candidates:
            try:
                if self.dcom_controller.connect(candidate):
                    port, desc = candidate, label
                    break
                failures.append(f"{candidate}: refused")
            except Exception as e:
                failures.append(f"{candidate}: {e}")

        if port is None:
            seen = ", ".join(p for p, _ in devices) or "none"
            self._log_reconnect(
                f"attempt {self._reconnect_attempts}: ports on the bus [{seen}]; "
                + ("; ".join(failures) if failures else "nothing to try"))
            return

        outage = time.time() - self._port_lost_at
        self._port_lost = False
        self.dcom_selected_device = (port, desc)
        runtime_globals.game_console.log(
            f"[DComView] Adapter back on {port} after {outage:.1f}s; resending")

        # Reopening the port resets the Arduino, so the command it was running
        # is gone and the packets have to go out again. The turn has not
        # changed, so they are the same packets.
        self._send_packets()

        # The player spent the outage waiting, not failing to press a button,
        # so the time it ate is given back instead of counted against them.
        self.comm_start_time += outage
        self._reconnect_attempts = 0

        # Reopening resets the adapter, so whatever exchange was in flight is
        # gone -- including one the toy may have finished on its own while we
        # were off the bus. The packets are back on the wire, but the battle
        # has to be started again on the device.
        runtime_globals.game_console.log(
            "[DComView] The exchange was lost with the port; start the battle "
            "on your device again")

    def _log_reconnect(self, message):
        """Report a failed reconnect, at most once every few seconds.

        Quiet enough not to become the flood this whole path exists to stop,
        loud enough that a recovery which never lands says so.
        """
        now = time.time()
        if self._reconnect_attempts > 1 and now - self._last_reconnect_log < 5.0:
            return
        self._last_reconnect_log = now
        runtime_globals.game_console.log(f"[DComView] Reconnect: {message}")

    #: What a CircuitPython prompt says when our command reaches it instead
    #: of the firmware. The adapter drops here if code.py stops -- a crash, a
    #: Ctrl-C during boot -- and then every DigiROM we send is typed at a
    #: Python prompt, which answers with a SyntaxError and nothing else.
    #: Without this the symptom is a silent minute and "No response from the
    #: adapter", which points at the toy rather than at the adapter.
    REPL_MARKERS = (">>>", "Traceback (most recent call last)",
                    'File "<stdin>"', "SyntaxError:", "NameError:")

    @classmethod
    def _looks_like_repl(cls, line: str) -> bool:
        stripped = line.strip()
        return any(stripped.startswith(marker) or marker in stripped
                   for marker in cls.REPL_MARKERS)

    def _consume_line(self, line: str) -> bool:
        """Handle one line from the adapter; True when the exchange is done."""
        if self._looks_like_repl(line):
            if not self._repl_seen:
                self._repl_seen = True
                runtime_globals.game_console.log(
                    "[DComView] The adapter answered as a Python prompt, not "
                    "as firmware: it has dropped to the CircuitPython REPL. "
                    "Reset it (Ctrl-D at the prompt, or unplug and replug) so "
                    "code.py runs again -- nothing will answer until it does.")
            runtime_globals.game_console.log(f"[DComView] RX: {line}")
            return False

        status = describe_status(line)
        if status:
            # These arrive several times a second for as long as nothing is
            # connected, so they are tallied and only logged occasionally.
            code, explanation = status
            count, _ = self.status_counts.get(code, (0, explanation))
            self.status_counts[code] = (count + 1, explanation)
            if time.time() - self._last_status_log > 2.0:
                runtime_globals.game_console.log(
                    f"[DComView] DCom status: {line} -> {explanation} "
                    f"({count + 1} so far)")
                self._last_status_log = time.time()
            return False

        runtime_globals.game_console.log(f"[DComView] RX: {line}")

        # Data got through, so whatever the adapter reported up to now was
        # just the wait, not a fault worth telling the player about.
        self.status_counts.clear()

        # ONE LINE IS ONE EXCHANGE ATTEMPT. The adapter prints a whole
        # attempt and ends it with a newline, so a line that carries fewer
        # packets than the format needs is a failed attempt, not the first
        # part of a good one. Accumulating across lines turned six failed
        # attempts -- each one packet long -- into "six packets received",
        # six copies of the same packet that then failed validation.
        expected = self.simulator.expected_packet_count
        received = []
        aborted = False
        for hex_data in self.simulator.response_pattern().findall(line):
            if hex_data.upper() == 'FF00':
                # Not a terminator: the device sends this to abort, having
                # objected to something we sent it.
                aborted = True
                runtime_globals.game_console.log(
                    "[DComView] Device sent FF00 - it rejected the exchange")
                continue
            if hex_data.upper() == EMPTY_PACKET:
                # A read that came back empty; the device sent nothing, so
                # counting it as data would only fail validation later.
                self.empty_reads += 1
                runtime_globals.game_console.log(
                    f"[DComView] empty read (ignored, {self.empty_reads} so far)")
                continue
            received.append(hex_data)

        if not received:
            return False

        # The device is talking to us, whatever else is wrong.
        self._device_answered = True

        if len(received) == expected and not aborted:
            sent = re.findall(r's:([0-9A-Fa-f]{%d})(?![0-9A-Fa-f])' % self.simulator.packet_hex_length, line)
            if len(sent) != expected:
                self.status_label.set_text('Incomplete adapter transcript. Retry the connection.')
                return False
            self.player_packets = [bytes.fromhex(p) for p in sent]
            self.response_packets = received
            runtime_globals.game_console.log(
                f"[DComView] ===== ALL {expected} PACKETS RECEIVED =====")
            runtime_globals.game_console.log(
                f"[DComView] {' '.join(self.response_packets)}")
            return True

        runtime_globals.game_console.log(
            f"[DComView] Exchange {'refused' if aborted else 'stopped'} after "
            f"{len(received)}/{expected} packet(s): {' '.join(received)}")
        if aborted:
            self.status_label.set_text("Device refused the battle. Retrying...")
        self._learn_from_partial(received)
        return False

    def _learn_from_partial(self, received):
        """Use a broken-off exchange to correct what we are sending.

        The device announces its own version in its first packet. If ours
        says something else it can simply stop answering, which looks exactly
        like a dead connection -- so the version it told us is adopted and
        the packets rebuilt. It retries every few seconds, so the corrected
        reply is waiting for the next attempt.
        """
        if not received:
            return

        # Outcome data from an earlier attempt must never determine the next
        # exchange. Only compatibility version negotiation survives a retry.
        if is_oem_pet(self.pet, self.battle_format):
            return

        if self._version_retried:
            return
        try:
            theirs = self.simulator.peek_version(received[0])
        except Exception as exc:
            runtime_globals.game_console.log(f"[DComView] Could not read their version: {exc}")
            return
        if theirs is None or theirs == self.simulator.sent_version:
            return

        self._version_retried = True
        runtime_globals.game_console.log(
            f"[DComView] Device reports version {theirs}, we sent "
            f"{self.simulator.sent_version}; matching it and retrying")
        self.simulator.force_version = theirs
        self._build_and_send()

    def _connection_diagnosis(self) -> str:
        """The adapter's own account of why nothing arrived."""
        if self._port_lost:
            return "Adapter disconnected - check the USB cable."
        if self._repl_seen:
            return ("Adapter is at the CircuitPython REPL - reset it so "
                    "code.py runs.")
        if not self.status_counts:
            return "No response from the adapter."
        # The code it reported most is the one describing the connection.
        _, explanation = max(self.status_counts.values(), key=lambda entry: entry[0])
        return explanation

    def _update_dcom_communication(self):
        """Update loop for DCom communication phase."""
        current_time = time.time()

        # Nothing else can run while the adapter is off the bus: the poll
        # would only raise again, and swapping the turn or timing out would
        # blame the player for a cable.
        if self._port_lost:
            lost_for = current_time - self._port_lost_at
            if lost_for >= RECONNECT_WINDOW_SECONDS:
                runtime_globals.game_console.log(
                    "[DComView] ===== ADAPTER DID NOT COME BACK =====")
                self.status_label.set_text("Adapter disconnected - check the cable")
                self.communicating = False
                return
            if current_time >= self._next_reconnect_at:
                self._attempt_reconnect()
            if self._port_lost:
                self.status_label.set_text(
                    f"Reconnecting... ({int(RECONNECT_WINDOW_SECONDS - lost_for)}s)")
                return
            # Reopening cost a couple of seconds of wall clock, and the window
            # was moved to match, so both are re-read.
            current_time = time.time()

        elapsed = current_time - self.comm_start_time

        if current_time - self._last_comm_log >= 5.0:
            runtime_globals.game_console.log(
                f"[DComView] Still listening... {elapsed:.1f}s, "
                f"{len(self.response_packets)} packet(s), "
                f"adapter says: {self._connection_diagnosis()}")
            self._last_comm_log = current_time

        if elapsed >= COMM_TIMEOUT_SECONDS:
            runtime_globals.game_console.log("[DComView] ===== EXCHANGE TIMED OUT =====")
            runtime_globals.game_console.log(
                f"[DComView] {len(self.response_packets)} packet(s), "
                f"{self.empty_reads} empty read(s) before timeout")
            for code, (count, explanation) in sorted(self.status_counts.items()):
                runtime_globals.game_console.log(
                    f"[DComView]   {code}: {count}x - {explanation}")
            self.status_label.set_text(self._connection_diagnosis())
            self.communicating = False
            if self.dcom_controller:
                self.dcom_controller.disconnect()
            return

        # The adapter reports a failed read several times a second for as
        # long as nothing is connected, and those reports are perfectly
        # normal while the player is still walking over to press the button.
        # So the wait says only that it is waiting; the codes become a
        # diagnosis at the timeout, when nothing did arrive.
        remaining = int(COMM_TIMEOUT_SECONDS - elapsed)
        # Nothing at all half way through: the toy may be waiting to be
        # spoken to rather than opening the exchange itself. Try it the other
        # way round before giving up -- but only in silence. Once the device
        # has answered, the turn is evidently right and swapping it would
        # abandon an exchange that is part way through.
        if (not self._turn_swapped and not self._device_answered
                and elapsed >= TURN_SWAP_SECONDS):
            self._swap_turn()

        self.status_label.set_text(f"Waiting for device... ({remaining}s)")

        if self._check_dcom_response():
            self.communicating = False
            self._process_battle_result()

    # ------------------------------------------------------------------
    # Result
    # ------------------------------------------------------------------

    def _process_battle_result(self):
        """Turn the exchange into battle data and open the battle scene."""
        runtime_globals.game_console.log("[DComView] ===== PROCESSING DCOM BATTLE RESULT =====")

        try:
            pet = self.pet
            player_digimon = pet_to_digimon(pet, self.battle_format, self.minigame_result)

            opponent = self.simulator.parse_opponent(self.response_packets, player_digimon)
            if not opponent:
                self.status_label.set_text("ERROR: corrupt data from device")
                if self.dcom_controller:
                    self.dcom_controller.disconnect()
                return

            exchange = PacketExchange.from_transcript(
                self.battle_format, player_digimon, self.player_packets,
                self.response_packets, simulator=self.simulator)
            result = exchange.result()
            if not result:
                raise Exception("Battle result is None")

            runtime_globals.game_console.log(
                f"[DComView] Winner={result.winner}, {len(result.battle_log)} turn(s)")
            self.simulator.log_battle(result)

            self._create_dcom_pvp_data(pet, opponent, result)

            self.dcom_controller.disconnect()

            runtime_globals.game_console.log("[DComView] Transitioning to PvP battle scene...")
            from utils.scene_utils import change_scene
            change_scene("battle_pvp")

        except Exception as e:
            import traceback
            runtime_globals.game_console.log(f"[DComView] Error processing battle result: {e}")
            runtime_globals.game_console.log(f"[DComView] Traceback: {traceback.format_exc()}")
            self.status_label.set_text(f"Error: {str(e)[:50]}")
            if self.dcom_controller:
                self.dcom_controller.disconnect()

    def _create_dcom_pvp_data(self, my_pet, opponent, battle_result):
        """Create PvP battle data from DCom battle result."""
        runtime_globals.game_console.log("[DComView] Creating PvP battle data...")

        my_pet_data = {
            "name": getattr(my_pet, "name", "Pet"),
            "stage": getattr(my_pet, "stage", 1),
            "level": getattr(my_pet, "level", 1),
            # The HP the battle was fought with belongs to the wire, not the
            # pet: DMC, DM20 and PEN20 all fix it. Sending the pet's own left
            # a Shoutmon on a 12 HP bar for a five-round DMC fight the log
            # drained from 5, so the bar stopped at 7 instead of empty.
            "hp": self.simulator.get_initial_hp(
                pet_to_digimon(my_pet, self.battle_format, self.minigame_result)),
            "power": my_pet.get_power() if hasattr(my_pet, "get_power") else getattr(my_pet, "power", 1),
            "attribute": getattr(my_pet, "attribute", 0),
            "atk_main": getattr(my_pet, "atk_main", None),
            "atk_alt": getattr(my_pet, "atk_alt", None),
            "module": getattr(my_pet, "module", "base"),
            "sick": getattr(my_pet, "sick", 0) > 0,
            "traited": getattr(my_pet, "traited", False),
            "shook": getattr(my_pet, "shook", False),
            "mini_game": self.minigame_result,
        }

        # Attack sprite ids are already 1-based here: parse_opponent shifts
        # them on the way in.
        opponent_pet_data = {
            "name": opponent.name,
            "stage": opponent.stage,
            "level": opponent.level,
            "hp": self.simulator.get_initial_hp(opponent),
            "power": opponent.power,
            "attribute": opponent.attribute,
            "atk_main": opponent.shot1,
            "atk_alt": opponent.shot2,
            "module": getattr(my_pet, "module", "base"),
            "sick": bool(opponent.sick),
            "traited": bool(opponent.traited),
            "shook": bool(opponent.egg_shake),
            "mini_game": opponent.mini_game,
        }

        battle_simulation_data = {
            "battle_log": battle_result.to_dict() if hasattr(battle_result, 'to_dict') else {},
            "team1": [my_pet_data],
            "team2": [opponent_pet_data],
            "module": getattr(my_pet, "module", "base"),
            # device1 is the toy in a DCom result, so its win is our defeat.
            "victory_status": "Defeat" if battle_result.winner == "device1" else "Victory",
        }

        runtime_globals.pvp_battle_data = {
            "simulation_data": battle_simulation_data,
            "original_battle_log": battle_result,
            "is_host": True,
            "my_pets": [my_pet],
            "my_team_data": [my_pet_data],
            "enemy_team_data": [opponent_pet_data],
            "module": getattr(my_pet, "module", "base"),
            "my_player_name": "YOU",
            "enemy_player_name": self.battle_format,
            "is_online_mode": False,
            "is_dcom_mode": True,
            "is_oem_mode": is_oem_pet(my_pet, self.battle_format),
            "battle_format": self.battle_format,
            "opponent_device_version": getattr(self.simulator, 'opponent_device_version', None),
            "enemy_first": self.enemy_first,
        }

        runtime_globals.game_console.log("[DComView] PvP battle data created")

    # ------------------------------------------------------------------
    # View lifecycle
    # ------------------------------------------------------------------

    def _on_minigame_cancel(self):
        """Backing out of the charge returns to picking a pet.

        The charge is played after the line has been chosen, so cancelling it
        is "not this battle" rather than "not any battle" -- and dropping the
        player at the main menu makes them walk the whole flow again. It used
        to call `_on_cancel`, which leaves the connection screen entirely.
        """
        runtime_globals.game_sound.play("cancel")
        self.minigame = None
        self._cleanup_dcom()
        self.change_view("pet_selection", is_dcom_mode=True)

    def _on_cancel(self):
        """Cancel button clicked."""
        runtime_globals.game_sound.play("cancel")
        self._cleanup_dcom()
        self.change_view("main_menu", initial_submenu="local_battle")

    def _cleanup_dcom(self):
        """Cleanup DCom resources."""
        self.communicating = False
        if self.dcom_controller:
            try:
                self.dcom_controller.disconnect()
            except Exception:
                pass
            self.dcom_controller = None

    def update(self):
        """Update the view."""
        if self.abort:
            self.abort = False
            self.change_view("main_menu", initial_submenu="local_battle")
            return

        if self._minigame_settle_at:
            if time.time() >= self._minigame_settle_at:
                self._minigame_settle_at = 0
                self._start_communication()
            return

        if self.phase == "minigame" and self.minigame:
            self.minigame.update()
            if self.minigame.finished:
                self._finish_minigame()
            return

        if self.phase == "communicating" and self.communicating:
            self._update_dcom_communication()

    def draw(self, surface):
        """Draw view-specific elements."""
        if self.phase == "minigame" and self.minigame:
            self.minigame.draw(surface)

    def handle_event(self, event):
        """Handle input events."""
        if not isinstance(event, tuple) or len(event) != 2:
            return
        event_type, _ = event

        if self.phase == "minigame" and self.minigame:
            if event_type == "ESC":
                runtime_globals.game_console.log("[DComView] Minigame cancelled")
                self._on_minigame_cancel()
                return True
            return self.minigame.handle_event(event)

        # **A as well as START.** START is the natural name for "open the
        # battle", but A is this game's confirm button everywhere else, and
        # reaching for it first is the obvious mistake to make -- so it is
        # not a mistake.
        # The keypress still works -- some players will reach for it, and it
        # goes through the same handler so the button changes to LOADING
        # whichever way it was triggered.
        if event_type in ("START", "A") and self.communicating:
            if not (self.start_button and not self.start_button.enabled):
                self._on_start()
            return True

        if event_type == "B":
            self._on_cancel()
            return True
        return False

    def cleanup(self):
        """Cleanup when view is destroyed."""
        self._cleanup_dcom()

        for comp in (self.background, self.title_scene, self.status_label,
                     self.device_menu, self.protocol_menu, self.cancel_button,
                     self.start_button):
            if comp and comp in self.ui_manager.components:
                self.ui_manager.remove_component(comp)

        runtime_globals.game_console.log("[DComView] Cleanup complete")
