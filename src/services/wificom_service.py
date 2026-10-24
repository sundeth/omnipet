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

**Everything MQTT happens on one background thread**, and only there: the
broker connection is a TLS handshake plus a round trip, `mqtt.loop()` blocks
for its timeout, and paho's manual loop is not thread-safe. The view reads
`state` and `status_text` each frame and never touches the client.

**The pet is played on the game's own thread.** The worker answers what
needs no pet itself -- `P` (pause), `I` (version info), an unreadable
command, a ROM the selected line cannot answer -- and hands every other
DigiROM to the view (`take_incoming`). The view plays it (`play`), which
queues the result for the worker to publish. That keeps the pets and the
battle code on the thread that owns them, and lets a turn-2 ROM wait for the
player: turn 2 means the adapter listens and the toy has to start the battle,
which on Omnipet is the BATTLE! button.

**One session, one exact battle format.** The player chooses the line on the
WiFiCom screen and plays its charge before going online (`set_pet`), as the
DCom flow does. wificom.dev's request envelope for an ordinary DigiROM is
`{digirom, application_id, api_response, ack_id}` (wificom-lib `mqtt.py`) and
names no line, so the selection is the player's; a request that does name
one (`battle_format`) must name the selected line or it is not answered. A
ROM is checked against the line (`executor.fits`) and refused rather than
re-read as some other line -- several lines share one wire.

`wificom.mqtt` is imported only once credentials have loaded, because it
builds its topic strings at import time out of `import_secrets` -- and
reloaded when the credentials have changed since, or the topics would be
the old device's.

Real-time battles (wificom.dev's `topic_action: subscribe`, upstream's
`realtime.py`) are not played: upstream runs them for Legendz and the
Pendulum X's 3-prong battle only, neither of which is an Omnipet battle
format. An invite is reported as unsupported, and an ordinary DigiROM still
works -- upstream leaves the real-time battle when one arrives.
"""

import importlib
import json
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
#: Upstream's heartbeat during a real-time battle ("approx every 10 seconds").
RTB_PING_INTERVAL = 10.0

#: How long each `mqtt.loop()` call services the socket for (upstream's
#: `mqtt.loop()` asks the client for one second).
LOOP_TIMEOUT = 1.0

#: The envelope key a request may use to name the battle format, in
#: Omnipet's own spelling (`protocol_constants.BATTLE_FORMATS`).
ENVELOPE_FORMAT_KEY = "battle_format"

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


def _input_topic(import_secrets):
    """The input topic `mqtt.py` builds out of the current credentials."""
    return (import_secrets.secrets_mqtt_username.lower() + "/f/"
            + import_secrets.secrets_user_uuid + "-"
            + import_secrets.secrets_device_uuid + "/wificom-input")


def load_mqtt():
    """`wificom.mqtt`, with topics built from the credentials loaded now."""
    from wificom import import_secrets
    from wificom import mqtt
    if getattr(mqtt, "_mqtt_topic_input", None) != _input_topic(import_secrets):
        mqtt = importlib.reload(mqtt)
    return mqtt


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
        #: The last ROM an app sent us, and what we answered with.
        self.last_received = None
        self.last_result = None
        #: How many ROMs the pet has answered this session.
        self.exchanges = 0
        #: The session: the pet a ROM is played against, the exact battle
        #: format the player chose and the charge it fights with.
        self.pet = None
        self.battle_format = None
        self.charge = 0
        #: Why the last DigiROM went unanswered, for the view; cleared by it.
        self.notice = None

        self._thread = None
        self._stop_event = threading.Event()
        self._outbox = queue.Queue()
        self._incoming = None
        self._incoming_lock = threading.Lock()
        #: The format the envelope of the DigiROM being read named, if any.
        self._envelope_format = None
        #: Upstream's "a DigiROM is loaded": from a ROM until P, I or an
        #: unreadable command. It pings only while none is.
        self._loaded = False
        #: A turn-2 ROM handed to the game and not played yet: the adapter
        #: is listening for the toy, and reports each listen that times out.
        self._listening = None
        self._client = None
        self._mqtt = None

    # -- lifecycle ---------------------------------------------------------

    def start(self):
        """Bring the service up. Returns False if it cannot even try."""
        if self._thread is not None and self._thread.is_alive():
            if not self._stop_event.is_set():
                return True
            # Still on its way out from a stop that did not wait.
            self._thread.join(timeout=LOOP_TIMEOUT + 1.0)

        if not transport_available():
            self._fail("MQTT unavailable")
            return False
        if not credentials_available():
            from wificom import import_secrets
            self._fail(import_secrets.secrets_error_display or "No credentials")
            return False

        self.last_error = None
        self.notice = None
        self.exchanges = 0
        self._loaded = False
        self._listening = None
        self.state = STATE_CONNECTING
        self._stop_event.clear()
        # Drop anything queued while offline rather than sending it late.
        self._drain_outbox()
        self.take_incoming()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="wificom-service")
        self._thread.start()
        runtime_globals.game_console.log("[WiFiCom] Service starting")
        return True

    def stop(self, wait=True):
        """Take the service down.

        Whatever is still queued -- the result of the battle that is about to
        play -- is published on the way out. *wait* waits for that (up to one
        loop of the socket); without it the worker finishes on its own, so
        the battle can start without the game pausing for the network.
        """
        self._stop_event.set()
        thread = self._thread
        if wait and thread is not None and thread.is_alive():
            thread.join(timeout=LOOP_TIMEOUT + 1.0)
        if wait or thread is None or not thread.is_alive():
            self._thread = None
        self.state = STATE_OFFLINE
        self.take_incoming()
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
                code = self.rtb_invite_code
                if code:
                    return f"Real-time battle #{code} is not supported"
                return "Real-time battles are not supported"
            return "Online. Waiting for a DigiROM..."
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

    def set_pet(self, pet, battle_format, charge=0):
        """The session: the pet, the exact battle format and its charge."""
        from battle.sim import protocol_constants
        self.pet = pet
        self.battle_format = protocol_constants.canonical_format(battle_format or "") or None
        self.charge = charge or 0

    # -- the game's side ----------------------------------------------------

    def take_incoming(self):
        """The DigiROM waiting to be played, once, or None."""
        with self._incoming_lock:
            rom, self._incoming = self._incoming, None
        return rom

    def play(self, rom):
        """Play *rom* against the session's pet and publish what came back.

        Called on the game's thread. Returns the `executor.Played`.
        """
        from wificom import executor
        self._listening = None
        played = executor.play(rom, self.pet, self.battle_format, self.charge)
        self.exchanges += 1
        self.last_result = played.result
        self.publish(played.result)
        return played

    def publish(self, output):
        """Queue *output* for the worker to publish on the output topic."""
        self._outbox.put(output)

    # -- receiving (worker thread) -----------------------------------------

    def _handle_command(self, command):
        """Answer one thing an app published on our input topic.

        Mirrors upstream's `process_new_digirom`: the two non-ROM commands
        and anything unreadable are answered here with a string of their own
        -- going quiet is indistinguishable from being offline. A ROM the
        selected line cannot answer gets what the adapter would report with
        nobody answering. Returns the output to publish now, or None when
        the ROM went to the game to be played.
        """
        from wificom import digirom, executor
        from wificom.dmcomm_shim import CommandError

        self.last_received = command
        envelope_format, self._envelope_format = self._envelope_format, None
        # Whatever was loaded is replaced, as upstream replaces it.
        self._loaded = False
        self._listening = None
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

        self._loaded = True
        refusal = None
        if self.pet is None or not self.battle_format:
            refusal = "no pet selected"
        elif envelope_format is not None:
            from battle.sim import protocol_constants
            named = protocol_constants.canonical_format(str(envelope_format))
            if named != self.battle_format:
                refusal = "the request is for %s, and this pet is on %s" % (
                    envelope_format, self.battle_format)
        if refusal is None:
            refusal = executor.fits(rom, self.battle_format)
        if refusal is not None:
            self.notice = refusal
            runtime_globals.game_console.log(f"[WiFiCom] Not answering {command}: {refusal}")
            return executor.unanswered(rom, self.battle_format, refusal).result

        # Upstream replaces whatever ROM it had with a new one; so does this.
        with self._incoming_lock:
            self._incoming = rom
        if rom.turn == 2:
            self._listening = rom
        runtime_globals.game_console.log(
            "[WiFiCom] %s DigiROM for the pet: %s" % (self.battle_format, command))
        return None

    def _on_input(self, mqtt, client, topic, message):
        """The input topic's callback: note the envelope, then upstream's.

        Upstream's callback raises on a message that is not JSON or lacks a
        field it reads; on a WiFiCom that ends in its crash report. Here it
        is logged and the connection kept.
        """
        try:
            envelope = json.loads(message)
        except (TypeError, ValueError):
            envelope = None
        if isinstance(envelope, dict) and envelope.get("digirom") is not None:
            self._envelope_format = envelope.get(ENVELOPE_FORMAT_KEY)
        try:
            mqtt.on_app_feed_callback(client, topic, message)
        except Exception as error:  # pylint: disable=broad-except
            runtime_globals.game_console.log(
                f"[WiFiCom] Unreadable request ignored: {error!r}")
        # Upstream has just subscribed to a real-time battle's topic with its
        # own callback, which raises the same way on a bad message.
        rtb = mqtt.rtb
        if rtb.active and rtb.host and rtb.topic:
            client.add_topic_callback(rtb.host + "/f/" + rtb.topic,
                                      lambda c, t, m: self._guarded(mqtt.on_realtime_battle_feed_callback, c, t, m))

    @staticmethod
    def _guarded(callback, client, topic, message):
        try:
            callback(client, topic, message)
        except Exception as error:  # pylint: disable=broad-except
            runtime_globals.game_console.log(
                f"[WiFiCom] Unreadable real-time battle message ignored: {error!r}")

    # -- worker ------------------------------------------------------------

    def _run(self):
        """Connect, then service the socket until asked to stop."""
        try:
            from wificom import transport
            # Not at module scope: mqtt.py builds its topics at import time
            # from the credentials, which are only known to be loaded now.
            mqtt = load_mqtt()
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

        # Upstream reports whether the WiFiCom has a screen; Omnipet's is the
        # one showing this session.
        try:
            from wificom import version
            version.set_display(True)
        except Exception:  # pylint: disable=broad-except
            pass

        client = transport.create_client()
        if client is None:
            self._fail("No broker configured")
            return

        try:
            connected = mqtt.connect_to_mqtt(client)
        except Exception as e:  # pylint: disable=broad-except
            runtime_globals.game_console.log(f"[WiFiCom] Connect failed: {repr(e)}")
            connected = False
        if not connected:
            # Upstream's connect_to_mqtt swallows the reason; the client
            # remembers whether the broker refused the login or was never
            # reached, which are different things to tell the player.
            if getattr(client, "refused_code", None) is not None:
                self._fail("Login refused: check secrets.json")
            else:
                self._fail("Could not reach wificom.dev")
            return
        client.add_topic_callback(
            mqtt._mqtt_topic_input,  # pylint: disable=protected-access
            lambda c, t, m: self._on_input(mqtt, c, t, m))

        self._client = client
        self.state = STATE_ONLINE
        runtime_globals.game_console.log("[WiFiCom] Online")
        from wificom import executor

        next_ping = 0.0
        next_rtb_ping = 0.0
        try:
            while not self._stop_event.is_set():
                # Results first: the app is holding a request open for them.
                sent_anything = self._flush_outbox(mqtt)

                command = mqtt.get_subscribed_output()
                if command is not None:
                    runtime_globals.game_console.log(f"[WiFiCom] RX: {command}")
                    output = self._handle_command(command)
                    if output is not None:
                        self._send(mqtt, output)
                        sent_anything = True

                now = time.monotonic()
                if mqtt.rtb.active:
                    # Upstream's heartbeat while it is in a real-time battle.
                    if now >= next_rtb_ping:
                        mqtt.send_digirom_output("RTB")
                        next_rtb_ping = now + RTB_PING_INTERVAL
                elif sent_anything:
                    next_ping = now + PING_INTERVAL
                elif now >= next_ping:
                    if self._listening is not None:
                        # A turn-2 ROM the toy has not started (BATTLE! not
                        # pressed): the adapter's listen timed out.
                        self._send(mqtt, executor.TIMEOUT_MARKER)
                    elif not self._loaded:
                        # Upstream pings with a null output to stay visible,
                        # and only while no DigiROM is loaded -- a ping after
                        # a result would stand in for it.
                        mqtt.send_digirom_output(None)
                    next_ping = now + PING_INTERVAL

                mqtt.loop()
                # A dropped connection does not raise here the way it does in
                # minimqtt (upstream then reboots): paho reports it and
                # carries on, so it has to be looked for, or the screen says
                # "Online" over a dead socket.
                if not client.is_connected():
                    self._fail("Connection lost")
                    break
        except Exception as e:  # pylint: disable=broad-except
            runtime_globals.game_console.log(f"[WiFiCom] Loop ended: {repr(e)}")
            self._fail("Connection lost")
        finally:
            try:
                self._flush_outbox(mqtt)
            except Exception:  # pylint: disable=broad-except
                pass
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

    def _send(self, mqtt, output):
        mqtt.send_digirom_output(output)
        self.last_sent = output
        runtime_globals.game_console.log(f"[WiFiCom] TX: {output}")

    def _flush_outbox(self, mqtt):
        """Publish everything queued. Returns True if anything went out."""
        sent = False
        while True:
            try:
                output = self._outbox.get_nowait()
            except queue.Empty:
                return sent
            self._send(mqtt, output)
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
