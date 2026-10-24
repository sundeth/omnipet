# -*- coding: utf-8 -*-
"""A stand-in for wificom.dev's MQTT side, so a WiFiCom test needs no network.

Omnipet acts as a WiFiCom: it logs in to wificom.dev's broker with the
device's ``secrets.json`` and services two topics. Everything here mirrors
wificom-lib 2.1.0 (``lib/wificom/mqtt.py``, ``main.py``; vendored as
``src/wificom/``), not a guess at the site:

* topics: ``<mqtt_username lowercased>/f/<user_uuid>-<device_uuid>/wificom-input``
  and ``.../wificom-output``;
* a request on the input topic, as the site sends one for an app:
  ``{"digirom", "application_id", "api_response", "ack_id"?}``;
* a real-time battle invite: ``{"topic_action": "subscribe", "topic",
  "user_type", "host", "battle_type", "invite_code", "application_id",
  "api_response", "digirom": None}``, and the battle's own topic
  ``<host>/f/<topic>``;
* what the device publishes on the output topic: its version info
  (``version.dictionary()``) plus ``device_uuid``, ``application_uuid`` and
  ``output`` -- ``str(output)``, so a ping reads ``"None"``; and for an
  ``ack_id``, ``{"application_uuid", "device_uuid", "ack_id"}``.

The client side is the surface ``src/wificom/transport.py`` gives the
vendored ``mqtt.py`` (adafruit_minimqtt's): connect, subscribe, unsubscribe,
add_topic_callback, publish, loop, is_connected, disconnect, and the four
minimqtt-shaped callbacks. Callbacks run inside ``loop()``, on the caller's
thread, as they do with paho's manual loop.
"""
import json
import threading
import time

SECRETS = {
    "wireless_networks": [{"ssid": "SSID1", "password": "Password1"}],
    "broker": "mqtt.wificom.dev",
    "mqtt_username": "OmnipetTester",
    "mqtt_password": "token-for-tests",
    "user_uuid": "11111111-2222-3333-4444-555555555555",
    "device_uuid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
}
#: The application wificom.dev says a request came from.
APP_ID = "app-0001"


def topics(secrets=SECRETS):
    prefix = secrets["mqtt_username"].lower() + "/f/"
    ident = secrets["user_uuid"] + "-" + secrets["device_uuid"]
    return prefix + ident + "/wificom-input", prefix + ident + "/wificom-output"


def write_secrets(folder, secrets=SECRETS):
    import os
    path = os.path.join(folder, "secrets.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(secrets, fh)
    return path


class FakeBroker:
    """An in-memory broker: exact-topic subscriptions, QoS 0, a record of
    every publish."""

    def __init__(self, accounts=None):
        self.lock = threading.Lock()
        self.clients = []
        #: [(topic, payload text, sender)] in order.
        self.published = []
        #: username -> password; None accepts anyone.
        self.accounts = accounts
        self.changed = threading.Condition(self.lock)

    def publish(self, topic, payload, sender=None):
        text = payload if isinstance(payload, str) else payload.decode("utf-8")
        with self.lock:
            self.published.append((topic, text, sender))
            for client in self.clients:
                if topic in client.subscriptions and client is not sender:
                    client.inbox.append((topic, text))
            self.changed.notify_all()

    def drop_all(self):
        """The connection to every client goes, as when the site goes away."""
        with self.lock:
            clients, self.clients = list(self.clients), []
        for client in clients:
            client._connected = False
            if client.on_disconnect:
                client.on_disconnect(client, None, 7)

    def messages(self, topic):
        with self.lock:
            return [text for t, text, _ in self.published if t == topic]

    def wait_for(self, predicate, timeout=10.0):
        """Wait until *predicate()* is true (it is called with the lock held)."""
        deadline = time.monotonic() + timeout
        with self.changed:
            while not predicate():
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                self.changed.wait(min(left, 0.05))
            return True


class FakeMqttClient:
    """transport.MqttClient's surface, on a FakeBroker."""

    def __init__(self, broker, username="", password=""):
        self.broker = broker
        self.username = username
        self.password = password
        self.on_connect = self.on_disconnect = None
        self.on_subscribe = self.on_unsubscribe = None
        self.subscriptions = set()
        self.callbacks = {}
        self.inbox = []
        self._connected = False
        #: As transport.MqttClient: the CONNACK code of a refused login.
        self.refused_code = None

    def connect(self, timeout=10):
        accounts = self.broker.accounts
        if accounts is not None and accounts.get(self.username) != self.password:
            self.refused_code = 5       # "not authorised"
            raise ConnectionRefusedError("bad username or password")
        with self.broker.lock:
            self.broker.clients.append(self)
        self._connected = True
        if self.on_connect:
            self.on_connect(self, None, {}, 0)
        return True

    def disconnect(self):
        with self.broker.lock:
            if self in self.broker.clients:
                self.broker.clients.remove(self)
        was = self._connected
        self._connected = False
        if was and self.on_disconnect:
            self.on_disconnect(self, None, 0)

    def subscribe(self, topic, qos=0):
        with self.broker.lock:
            self.subscriptions.add(topic)
        if self.on_subscribe:
            self.on_subscribe(self, None, topic, (qos,))
        return 0

    def unsubscribe(self, topic):
        with self.broker.lock:
            self.subscriptions.discard(topic)
        self.callbacks.pop(topic, None)
        if self.on_unsubscribe:
            self.on_unsubscribe(self, None, topic, 1)
        return 0

    def add_topic_callback(self, topic, callback):
        self.callbacks[topic] = callback

    def remove_topic_callback(self, topic):
        self.callbacks.pop(topic, None)

    def publish(self, topic, payload, qos=0, retain=False):
        if not self._connected:
            return 4      # paho's MQTT_ERR_NO_CONN: a return code, not a raise
        self.broker.publish(topic, payload, sender=self)
        return 0

    def loop(self, timeout=1):
        """Deliver what has arrived, waiting a moment if nothing has."""
        deadline = time.monotonic() + min(timeout, 0.05)
        while True:
            with self.broker.lock:
                pending, self.inbox = self.inbox, []
            if pending or time.monotonic() >= deadline:
                break
            time.sleep(0.005)
        for topic, text in pending:
            callback = self.callbacks.get(topic)
            if callback is not None:
                callback(self, topic, text)
        return 0

    def is_connected(self):
        return self._connected


class FakeWiFiComDev:
    """The site: sends an app's requests to the device and reads its output."""

    def __init__(self, broker, secrets=SECRETS):
        self.broker = broker
        self.secrets = secrets
        self.input_topic, self.output_topic = topics(secrets)
        self._acks = 0

    def client_factory(self):
        """What to patch over ``wificom.transport.create_client``."""
        secrets = self.secrets

        def create_client(broker=None, username=None, password=None, use_tls=True):
            from wificom import import_secrets
            return FakeMqttClient(self.broker,
                                  (username or import_secrets.secrets_mqtt_username).lower(),
                                  password or import_secrets.secrets_mqtt_password)
        return create_client

    # ---------------------------------------------------------------- sending
    def send_digirom(self, digirom, application_id=APP_ID, api_response=False,
                     ack=True, **extra):
        """A request carrying *digirom*, as the site forwards an app's."""
        message = {"digirom": digirom, "application_id": application_id,
                   "api_response": api_response}
        if ack:
            self._acks += 1
            message["ack_id"] = 100000 + self._acks
        message.update(extra)
        self.broker.publish(self.input_topic, json.dumps(message))
        return message

    def send_raw(self, text):
        self.broker.publish(self.input_topic, text)

    def invite_rtb(self, battle_type="digimon-penx-battle", user_type="guest",
                   host="wificomhost", topic="rtb-topic-1", invite_code="123456"):
        message = {"topic_action": "subscribe", "topic": topic, "user_type": user_type,
                   "host": host, "battle_type": battle_type, "invite_code": invite_code,
                   "application_id": 1, "api_response": False, "digirom": None}
        self.broker.publish(self.input_topic, json.dumps(message))
        return message

    # ---------------------------------------------------------------- reading
    def output_messages(self):
        return [json.loads(text) for text in self.broker.messages(self.output_topic)]

    def acks(self):
        return [m for m in self.output_messages() if "ack_id" in m]

    def outputs(self):
        """Every ``output`` the device published (pings included), in order."""
        return [m["output"] for m in self.output_messages() if "output" in m]

    def results(self):
        """The outputs that answer something: not a ping or a heartbeat."""
        return [m for m in self.output_messages()
                if "output" in m and m["output"] not in ("None", "RTB")]

    def connected(self):
        return any(self.input_topic in c.subscriptions for c in self.broker.clients)

    def wait_for_results(self, count, timeout=10.0):
        topic = self.output_topic

        def enough():
            found = 0
            for t, text, _ in self.broker.published:
                if t != topic:
                    continue
                try:
                    out = json.loads(text).get("output")
                except ValueError:
                    continue
                if out not in (None, "None", "RTB"):
                    found += 1
            return found >= count
        return self.broker.wait_for(enough, timeout)

    def wait_connected(self, timeout=10.0):
        return self.broker.wait_for(
            lambda: any(self.input_topic in c.subscriptions for c in self.broker.clients),
            timeout)
