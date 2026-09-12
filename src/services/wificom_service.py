"""
WiFiComService - Omnipet acting as a WiFiCom.

A WiFiCom is a Pi Pico W between a real V-Pet and wificom.dev: it takes a
DigiROM off an MQTT topic, plays it to the toy, and publishes what came back.
Omnipet carries the pets itself, so it has no reason to own one -- it
presents itself as one, and the "toy" is the selected pet.

This is the Omnipet side of upstream's `main.py run_wifi()` loop, driving the
vendored package in `src/wificom/`:

    transport.create_client()   paho-mqtt in place of adafruit_minimqtt
    mqtt.connect_to_mqtt()      topics, callbacks, real-time battle state
    mqtt.loop()                 serviced here, on the worker thread

Everything MQTT happens on one background thread. The broker connection is a
TLS handshake plus a round trip, and `mqtt.loop()` blocks for its timeout, so
neither can sit on the frame loop. The view reads `state` and `status_text`
each frame and never touches the client.

`wificom.mqtt` is imported only once credentials have loaded, because it
builds its topic strings at import time out of `import_secrets` -- importing
it earlier would bake in the empty ones.

**A WiFiCom is a middleman, and starter-agnostic.** The same battle two
toys would have over a cable is carried as DigiROMs through wificom.dev, so
Omnipet has to be able to open one (the Battle button) and to answer one
(anything arriving while the screen is open). Which it is doing is the only
thing the two ends disagree about.

`WiFiComBattle` drives it, over the same `PacketExchange` the cable and the
versus battle use -- one place per protocol, and the packets that cannot be
written until the other side has spoken (the DMX's inverse hits, the DMOG's
opposite verdict) are resolved there rather than three times over. When the
exchange completes and validates, the result is handed to the battle scene
exactly as a DCom battle is.

There is also a **toy on the other end** case: an app with a real WiFiCom
sends a whole DigiROM and expects the executed exchange back, `s:` for each
of its packets and `r:` for each of ours (`wificom.executor`). Both shapes
arrive on the same topic, so the service tells them apart by whether the
message continues a battle it is already having.

Two commands are not ROMs at all and are answered without touching a pet:
`P` (pause) and `I` (version info). Apps send `P` after consuming a result,
so ignoring it makes a working WiFiCom look wedged.
"""

import queue
import socket
import threading
import time

from core import runtime_globals


#: Not started, or stopped.
STATE_OFFLINE = "offline"
#: Connecting to the broker.
STATE_CONNECTING = "connecting"
#: Connected and listening: Omnipet is a WiFiCom on the air.
STATE_ONLINE = "online"
#: Connection failed or dropped. `last_error` says why.
STATE_ERROR = "error"

#: Seconds between the pings that keep the device visible to the website.
#: Upstream sends one every loop of `run_wifi`, which idles at 5 seconds.
PING_INTERVAL = 5.0

#: How long each `mqtt.loop()` call services the socket for.
LOOP_TIMEOUT = 1.0

#: Host and port for the "is there internet" probe, matching the check the
#: connect menu already uses for local WiFi.
INTERNET_PROBE = ("8.8.8.8", 53)
INTERNET_TIMEOUT = 2


def internet_available(timeout=INTERNET_TIMEOUT):
    """Whether a route to the internet exists.

    Same probe the connect menu uses for the local WiFi option, so the two
    availability checks cannot disagree about whether the network is up.
    """
    try:
        socket.create_connection(INTERNET_PROBE, timeout=timeout).close()
        return True
    except OSError:
        return False


def credentials_available():
    """Whether a usable `secrets.json` is present.

    Re-reads the file each time: the player can drop it in while the game is
    running, and the menu re-checks every few seconds.
    """
    try:
        from wificom import import_secrets
        return import_secrets.reload()
    except Exception as e:  # pylint: disable=broad-except
        runtime_globals.game_console.log(f"[WiFiCom] Credential check failed: {e}")
        return False


def transport_available():
    """Whether the MQTT client library is installed."""
    try:
        from wificom.transport import PAHO_AVAILABLE
        return PAHO_AVAILABLE
    except Exception:  # pylint: disable=broad-except
        return False


class WiFiComService:
    """Runs the WiFiCom MQTT connection for the game.

    Single instance, like the other services. `start` is safe to call when
    already running; `stop` is safe when already stopped.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self.state = STATE_OFFLINE
        self.last_error = None
        #: Set by the worker when it publishes; read for the status line.
        self.last_sent = None
        #: The last ROM an app sent us, and what we answered with. Read by
        #: the view so the player can see the exchange happening.
        self.last_received = None
        self.last_result = None
        #: How many ROMs we have answered this session.
        self.exchanges = 0
        #: The pet a received ROM is played against. Set by the view.
        self.pet = None
        #: The battle format the Battle button opens with. Set by the view.
        self.battle_format = None
        #: The battle in progress, if any, and the finished one waiting to be
        #: picked up by the view.
        self.battle = None
        self.finished_battle = None

        self._thread = None
        self._stop_event = threading.Event()
        self._outbox = queue.Queue()
        self._client = None
        self._mqtt = None

    # -- lifecycle ---------------------------------------------------------

    def start(self):
        """Bring the service up. Returns False if it cannot even try."""
        if self._thread is not None and self._thread.is_alive():
            return True

        if not transport_available():
            self._fail("MQTT unavailable")
            return False
        if not credentials_available():
            from wificom import import_secrets
            self._fail(import_secrets.secrets_error_display or "No credentials")
            return False

        self.last_error = None
        self.state = STATE_CONNECTING
        self._stop_event.clear()
        # Drop anything queued while offline rather than sending it late.
        self._drain_outbox()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="wificom-service")
        self._thread.start()
        runtime_globals.game_console.log("[WiFiCom] Service starting")
        return True

    def stop(self):
        """Take the service down and wait briefly for the worker to notice."""
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=LOOP_TIMEOUT + 1.0)
        self._thread = None
        self.state = STATE_OFFLINE
        runtime_globals.game_console.log("[WiFiCom] Service stopped")

    @property
    def is_running(self):
        """Whether the worker thread is alive."""
        return self._thread is not None and self._thread.is_alive()

    # -- what the view shows ----------------------------------------------

    @property
    def status_text(self):
        """One line describing the current state, for the waiting view."""
        if self.state == STATE_CONNECTING:
            return "Connecting..."
        if self.state == STATE_ONLINE:
            if self.rtb_active:
                return "Battle invite received"
            return "Waiting..."
        if self.state == STATE_ERROR:
            return self.last_error or "Connection failed"
        return "Offline"

    @property
    def rtb_active(self):
        """Whether wificom.dev has put this device into a real-time battle."""
        if self._mqtt is None:
            return False
        return bool(self._mqtt.rtb.active)

    @property
    def rtb_invite_code(self):
        """The invite code of the active real-time battle, or None."""
        if self._mqtt is None:
            return None
        return self._mqtt.rtb.invite_code

    def set_pet(self, pet, battle_format=None):
        """The pet an incoming DigiROM is played against."""
        self.pet = pet
        self.battle_format = battle_format

    def start_battle(self):
        """Open a battle: we are the starter. Returns (True, digirom) or (False, why)."""
        if self.state != STATE_ONLINE:
            return False, "Not connected"
        if self.pet is None or not self.battle_format:
            return False, "No pet to battle with"
        if self.battle is not None and not self.battle.complete:
            return False, "A battle is already running"

        from wificom.battle_session import WiFiComBattle

        try:
            self.battle = WiFiComBattle(self.pet, self.battle_format, opens=True)
            opening = self.battle.open()
        except Exception as error:  # pylint: disable=broad-except
            runtime_globals.game_console.log(f"[WiFiCom] Could not open: {error!r}")
            self.battle = None
            return False, "Could not build packets"
        if not opening:
            self.battle = None
            return False, "Could not build packets"

        self._outbox.put(opening)
        runtime_globals.game_console.log(
            f"[WiFiCom] Opening a {self.battle_format} battle: {opening}")
        return True, opening

    def take_finished_battle(self):
        """The completed battle, once, for the view to hand to the scene."""
        finished, self.finished_battle = self.finished_battle, None
        return finished

    # -- receiving ---------------------------------------------------------

    def _handle_command(self, mqtt, command):
        """Answer one thing an app published on our input topic.

        Mirrors upstream's `process_new_digirom` / `execute_digirom`: a ROM
        is played and its exchange published, and the two non-ROM commands
        are answered with a string of their own. Anything unreadable is
        published as the error rather than dropped -- going quiet is
        indistinguishable from being offline.
        """
        from wificom import digirom, executor
        from wificom.dmcomm_shim import CommandError

        self.last_received = command
        try:
            rom = digirom.parse_command(command)
        except CommandError as error:
            runtime_globals.game_console.log(f"[WiFiCom] Bad DigiROM: {error}")
            return repr(error)

        if rom.signal_type is None:
            if rom.op == "P":
                runtime_globals.game_console.log("[WiFiCom] Paused by the app")
                return "[pause]"
            if rom.op == "I":
                from wificom import version
                return version.toml()
            return "NotImplementedError:op=" + rom.op

        if self.pet is None:
            runtime_globals.game_console.log("[WiFiCom] No pet selected to answer with")
            return repr(CommandError("No pet selected"))

        # Every battle message goes through one path, whether it is a peer
        # taking turns or an app that sent its whole side at once. Both end
        # in a battle the player watches; only the shape of the reply
        # differs, and that follows from how much they sent.
        reply = self._continue_battle(command)
        if reply is not None:
            return reply

        # Not a battle on any wire we know: answer it as a one-shot so an app
        # still gets something readable back.
        try:
            return executor.execute(rom, self.pet)
        except Exception as error:  # pylint: disable=broad-except
            runtime_globals.game_console.log(f"[WiFiCom] Execute failed: {error!r}")
            return repr(error)

    def _continue_battle(self, command):
        """Advance a battle, or start answering one. None if it is not one."""
        from battle.sim import protocol_constants
        from wificom import digirom as digirom_module
        from wificom.battle_session import WiFiComBattle, format_for

        if self.battle is None or self.battle.complete:
            battle_format = format_for(command, self.pet)
            if not battle_format:
                return None
            self.battle = WiFiComBattle(self.pet, battle_format, opens=False)
            # A message carrying a whole side at once is an app with a real
            # WiFiCom behind it: it will not answer again, so it wants the
            # executed exchange rather than a command to reply to.
            try:
                rom = digirom_module.parse_command(command)
                expected = protocol_constants.get_wire(battle_format).PACKET_COUNT
                self.battle.whole_side = len(rom) >= expected
            except Exception:  # pylint: disable=broad-except
                self.battle.whole_side = False
            runtime_globals.game_console.log(
                "[WiFiCom] Answering a %s battle%s"
                % (battle_format, " (whole side)" if self.battle.whole_side else ""))

        battle = self.battle
        reply = battle.consume(command)
        if battle.failed:
            runtime_globals.game_console.log(f"[WiFiCom] Battle ended: {battle.failed}")
            self.battle = None
            return None

        if battle.complete:
            result = battle.result()
            if result is not None:
                self.exchanges += 1
                self.finished_battle = (battle, result)
                runtime_globals.game_console.log(
                    "[WiFiCom] Exchange complete: %d packet(s) each way, playing it out"
                    % battle.packet_count)
            self.battle = None

        if reply is None:
            return None
        # An app that sent everything reads an exchange; a peer reads a ROM.
        if getattr(battle, "whole_side", False):
            return battle.exchange_string()
        return reply

    # -- sending -----------------------------------------------------------

    def send_battle(self, pet, battle_format):
        """Queue this pet's battle packets for the worker to publish.

        The DigiROM is built by the same `DComBattleSimulator` the DCom cable
        battles use, under the format of the pet's own module, so a pet puts
        the same bytes on the wire whichever way it reaches an opponent.

        Returns (True, digirom) or (False, reason).
        """
        if self.state != STATE_ONLINE:
            return False, "Not connected"

        try:
            from battle.sim.dcom_battle_simulator import (DComBattleSimulator,
                                                          pet_to_digimon)
            # No controller: nothing here goes near a serial port, and
            # packet generation does not use one.
            simulator = DComBattleSimulator(None, battle_format=battle_format)
            digimon = pet_to_digimon(pet, battle_format)
            packets = simulator.generate_player_packets(digimon)
            if not packets:
                return False, "Could not build packets"
            digirom = simulator.build_command(packets)
        except Exception as e:  # pylint: disable=broad-except
            runtime_globals.game_console.log(f"[WiFiCom] Packet build failed: {e}")
            return False, "Could not build packets"

        self._outbox.put(digirom)
        runtime_globals.game_console.log(f"[WiFiCom] Queued DigiROM: {digirom}")
        return True, digirom

    # -- worker ------------------------------------------------------------

    def _run(self):
        """Connect, then service the socket until asked to stop."""
        try:
            from wificom import transport
            # Imported here, not at module scope: mqtt.py builds its topics
            # at import time from the credentials, which are only known to be
            # loaded now.
            from wificom import mqtt
        except Exception as e:  # pylint: disable=broad-except
            self._fail(f"WiFiCom unavailable: {e}")
            return

        self._mqtt = mqtt

        # The vendored real-time battle code reaches for the parser through
        # the shim, so install ours before anything can ask.
        try:
            from wificom import digirom, dmcomm_shim
            dmcomm_shim.set_parser(digirom.parse_command)
        except Exception as error:  # pylint: disable=broad-except
            runtime_globals.game_console.log(
                f"[WiFiCom] Could not install the DigiROM parser: {error}")

        client = transport.create_client()
        if client is None:
            self._fail("No broker configured")
            return

        try:
            if not mqtt.connect_to_mqtt(client):
                self._fail("Login refused")
                return
        except Exception as e:  # pylint: disable=broad-except
            runtime_globals.game_console.log(f"[WiFiCom] Connect failed: {repr(e)}")
            self._fail("Could not reach wificom.dev")
            return

        self._client = client
        self.state = STATE_ONLINE
        runtime_globals.game_console.log("[WiFiCom] Online")

        next_ping = 0.0
        try:
            while not self._stop_event.is_set():
                # Anything the player asked to send goes first, so pressing
                # Battle! is not held up behind a ping.
                sent_anything = self._flush_outbox(mqtt)

                # Then anything an app sent us. Upstream reads this at the top
                # of every loop; the reply is published immediately, because
                # the app is holding a request open waiting for it.
                command = mqtt.get_subscribed_output()
                if command is not None:
                    runtime_globals.game_console.log(f"[WiFiCom] RX: {command}")
                    result = self._handle_command(mqtt, command)
                    self.last_result = result
                    runtime_globals.game_console.log(f"[WiFiCom] TX: {result}")
                    mqtt.send_digirom_output(result)
                    self.last_sent = result
                    sent_anything = True

                if not sent_anything and time.monotonic() >= next_ping:
                    # Upstream pings with a null output to stay visible to
                    # the website; an active battle pings on its own topic.
                    mqtt.send_digirom_output("RTB" if mqtt.rtb.active else None)
                    next_ping = time.monotonic() + PING_INTERVAL

                mqtt.loop()
        except Exception as e:  # pylint: disable=broad-except
            runtime_globals.game_console.log(f"[WiFiCom] Loop ended: {repr(e)}")
            self._fail("Connection lost")
        finally:
            try:
                mqtt.quit_rtb()
            except Exception:  # pylint: disable=broad-except
                pass
            try:
                client.disconnect()
            except Exception:  # pylint: disable=broad-except
                pass
            self._client = None
            if self.state == STATE_ONLINE:
                self.state = STATE_OFFLINE

    def _flush_outbox(self, mqtt):
        """Publish everything queued. Returns True if anything went out."""
        sent = False
        while True:
            try:
                digirom = self._outbox.get_nowait()
            except queue.Empty:
                return sent
            if mqtt.rtb.active:
                mqtt.send_rtb_digirom_output(digirom)
            else:
                mqtt.send_digirom_output(digirom)
            self.last_sent = digirom
            sent = True

    def _drain_outbox(self):
        """Throw away anything still queued."""
        while True:
            try:
                self._outbox.get_nowait()
            except queue.Empty:
                return

    def _fail(self, message):
        """Record an error and go to the error state."""
        self.last_error = message
        self.state = STATE_ERROR
        runtime_globals.game_console.log(f"[WiFiCom] {message}")


#: The single instance, as with the other services.
wificom_service = WiFiComService()
