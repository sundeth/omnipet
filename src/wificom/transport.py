"""
MQTT transport for the vendored WiFiCom code.

Upstream's `wifi_picow.py` joins a WiFi network and hands back an
`adafruit_minimqtt` client. Omnipet is already on a network, so only the
second half is needed -- but `mqtt.py` is vendored verbatim and drives the
client through the minimqtt surface, so this module presents that surface on
top of paho-mqtt.

The methods `mqtt.py` actually uses, and what each maps to:

    connect() / disconnect()        paho connect, pumped until CONNACK
    subscribe() / unsubscribe()     paho subscribe / unsubscribe
    add_topic_callback(topic, cb)   dispatched from our own on_message
    publish(topic, payload)         paho publish
    loop(timeout)                   paho's manual network loop
    is_connected()                  see the note on the method
    on_connect / on_disconnect /    minimqtt-shaped callbacks, which are not
    on_subscribe / on_unsubscribe   paho's shapes -- so we re-dispatch

The loop is driven by hand rather than by `loop_start()`, which is what
upstream does and what the game wants: callbacks then fire inside the
`mqtt.loop()` call the game makes, on the caller's thread, instead of on a
background thread racing the pygame loop.

paho-mqtt is optional. `PAHO_AVAILABLE` is False when it is not installed and
`create_client` returns None, the same way the NFC and serial features
degrade when their package is missing.
"""

import socket
import ssl
import time
from typing import Callable, Dict, Optional

try:
    import paho.mqtt.client as paho_mqtt
    PAHO_AVAILABLE = True
except ImportError:
    paho_mqtt = None
    PAHO_AVAILABLE = False
    print("Warning: paho-mqtt not installed. WiFiCom functionality disabled.")

from wificom import import_secrets


#: Broker port for a TLS connection, which is what wificom.dev uses.
DEFAULT_TLS_PORT = 8883
#: Broker port without TLS.
DEFAULT_PORT = 1883
#: Seconds between keepalives. Matches upstream's `wifi_picow.py`.
DEFAULT_KEEP_ALIVE = 15
#: Seconds to wait for CONNACK before giving up.
CONNECT_TIMEOUT = 10


class MqttClient:
    """An `adafruit_minimqtt`-shaped client backed by paho-mqtt.

    Only the surface the vendored `mqtt.py` uses is implemented. Anything
    else minimqtt offers is deliberately absent rather than half-built.
    """

    def __init__(self, broker, username, password, port=None, keep_alive=DEFAULT_KEEP_ALIVE,
                 use_tls=True):
        if not PAHO_AVAILABLE:
            raise RuntimeError("paho-mqtt is not installed")

        self.broker = broker
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.port = port if port is not None else (DEFAULT_TLS_PORT if use_tls else DEFAULT_PORT)
        self.keep_alive = keep_alive

        # minimqtt-shaped callbacks, assigned by mqtt.connect_to_mqtt.
        self.on_connect: Optional[Callable] = None
        self.on_disconnect: Optional[Callable] = None
        self.on_subscribe: Optional[Callable] = None
        self.on_unsubscribe: Optional[Callable] = None

        self._topic_callbacks: Dict[str, Callable] = {}
        # paho reports subscribe/unsubscribe by message id, minimqtt by topic,
        # so the topic is remembered against the id until the ack arrives.
        self._pending_subscribes: Dict[int, str] = {}
        self._pending_unsubscribes: Dict[int, str] = {}
        self._connected = False

        self._client = self._build_client()

    def _build_client(self):
        """Create the paho client, spanning the v1 and v2 callback APIs."""
        callback_api = getattr(paho_mqtt, "CallbackAPIVersion", None)
        if callback_api is not None:
            # paho-mqtt 2.x requires the callback API version up front.
            client = paho_mqtt.Client(callback_api.VERSION1)
        else:
            client = paho_mqtt.Client()

        client.username_pw_set(self.username, self.password)
        if self.use_tls:
            client.tls_set(cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS_CLIENT)

        client.on_connect = self._paho_on_connect
        client.on_disconnect = self._paho_on_disconnect
        client.on_subscribe = self._paho_on_subscribe
        client.on_unsubscribe = self._paho_on_unsubscribe
        client.on_message = self._paho_on_message
        return client

    # -- paho callbacks, translated to the shapes the vendored code expects --

    def _paho_on_connect(self, client, userdata, flags, r_c, *_):
        self._connected = (r_c == 0)
        if self.on_connect is not None:
            self.on_connect(self, userdata, flags, r_c)

    def _paho_on_disconnect(self, client, userdata, r_c, *_):
        self._connected = False
        if self.on_disconnect is not None:
            self.on_disconnect(self, userdata, r_c)

    def _paho_on_subscribe(self, client, userdata, mid, granted_qos, *_):
        topic = self._pending_subscribes.pop(mid, None)
        if self.on_subscribe is not None:
            self.on_subscribe(self, userdata, topic, granted_qos)

    def _paho_on_unsubscribe(self, client, userdata, mid, *_):
        topic = self._pending_unsubscribes.pop(mid, None)
        if self.on_unsubscribe is not None:
            self.on_unsubscribe(self, userdata, topic, mid)

    def _paho_on_message(self, client, userdata, message):
        """Dispatch to the per-topic callback, minimqtt style.

        minimqtt hands the callback `(client, topic, message)` with the
        message already a string, so that is what is handed on here.
        """
        topic = message.topic
        try:
            payload = message.payload.decode("utf-8")
        except UnicodeError:
            print(f"WiFiCom: undecodable payload on {topic}")
            return

        callback = self._topic_callbacks.get(topic)
        if callback is None:
            # Only reached for a wildcard subscription, which nothing
            # currently makes, but a miss here would silently drop a message.
            for pattern, candidate in self._topic_callbacks.items():
                if paho_mqtt.topic_matches_sub(pattern, topic):
                    callback = candidate
                    break
        if callback is not None:
            callback(self, topic, payload)

    # -- the minimqtt surface --

    def connect(self, timeout=CONNECT_TIMEOUT):
        """Connect and pump the loop until the broker acknowledges.

        minimqtt's `connect` returns only once the session is up, and
        `mqtt.connect_to_mqtt` subscribes on the next line, so returning
        before CONNACK would lose that subscription.
        """
        self._client.connect(self.broker, self.port, self.keep_alive)
        deadline = time.monotonic() + timeout
        while not self._connected:
            if time.monotonic() > deadline:
                raise TimeoutError(f"No CONNACK from {self.broker} within {timeout}s")
            self._client.loop(timeout=0.1)
        return True

    def disconnect(self):
        """Close the connection."""
        self._client.disconnect()
        self._connected = False

    def subscribe(self, topic, qos=0):
        """Subscribe to a topic."""
        (result, mid) = self._client.subscribe(topic, qos)
        if result == paho_mqtt.MQTT_ERR_SUCCESS:
            self._pending_subscribes[mid] = topic
        return result

    def unsubscribe(self, topic):
        """Unsubscribe from a topic and drop its callback."""
        (result, mid) = self._client.unsubscribe(topic)
        if result == paho_mqtt.MQTT_ERR_SUCCESS:
            self._pending_unsubscribes[mid] = topic
        self._topic_callbacks.pop(topic, None)
        return result

    def add_topic_callback(self, topic, callback):
        """Register `callback(client, topic, message)` for one topic."""
        self._topic_callbacks[topic] = callback

    def remove_topic_callback(self, topic):
        """Forget the callback for one topic."""
        self._topic_callbacks.pop(topic, None)

    def publish(self, topic, payload, qos=0, retain=False):
        """Publish to a topic."""
        return self._client.publish(topic, payload, qos, retain)

    def loop(self, timeout=1):
        """Service the network for up to `timeout` seconds.

        Incoming messages are delivered to their callbacks from inside this
        call, so the game controls when WiFiCom work happens.
        """
        try:
            return self._client.loop(timeout=timeout)
        except (OSError, socket.error) as e:
            self._connected = False
            print(f"WiFiCom: MQTT loop error: {repr(e)}")
            return None

    def is_connected(self):
        """Whether the broker session is up.

        A method, not a property, because that is minimqtt's shape -- and the
        vendored `mqtt.py` tests it as `if client.is_connected:`, which reads
        the bound method and is therefore always true. That is upstream's
        behaviour and it is kept here rather than quietly corrected: the
        publish is attempted regardless, and a publish with no connection
        fails on a return code instead of raising. Call it as
        `is_connected()` from Omnipet code.
        """
        return self._connected


def create_client(broker=None, username=None, password=None, use_tls=True):
    """Build a client from the imported secrets, as `wifi_picow.py` did.

    Returns None when paho-mqtt is missing or no broker is configured, so a
    caller can report "WiFiCom unavailable" instead of raising.
    """
    if not PAHO_AVAILABLE:
        return None

    broker = broker if broker is not None else import_secrets.secrets_mqtt_broker
    username = username if username is not None else import_secrets.secrets_mqtt_username
    password = password if password is not None else import_secrets.secrets_mqtt_password

    if not broker or not username:
        return None

    # Upstream lowercases the username for both the connection and the topic
    # prefix; `mqtt.py` builds its topics the same way, so the two must agree.
    return MqttClient(
        broker=broker,
        username=username.lower(),
        password=password,
        use_tls=use_tls,
    )
