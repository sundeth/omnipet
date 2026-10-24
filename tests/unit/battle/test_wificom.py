# -*- coding: utf-8 -*-
"""WiFiCom: the adapter's DigiROM semantics, the line check, and the service.

Omnipet acts as a WiFiCom (src/wificom/, src/services/wificom_service.py).
These run without the game, the network or a module:

* ``digirom.resolve_packet`` works a ROM's operators out exactly as dmcomm
  does (``makePacket`` / ``makeColorPacket`` in dmcomm-project's
  ``dmcomm.ino``, matched by dmcomm-python): ``^`` against the packet just
  received, ``@`` over every digit the adapter has sent, Colour ``++++`` and
  ``____``;
* ``executor.fits`` refuses a ROM the selected line cannot answer, and never
  picks another line;
* the service, over ``support/fake_wificom.py``'s broker (wificom-lib's own
  topics and messages): ``P``/``I``/bad commands answered as upstream does,
  acknowledgements, a ROM of another line answered as nobody answering, a
  ROM of the line handed to the game, a request naming another format
  refused, a real-time battle invite reported as unsupported, malformed
  requests survived, queued results published on the way out, and topics
  rebuilt when the credentials change.

The game-level flow, every battle format through the real screens, is
tests/game/battle/test_wificom_fake.py.
"""
import io
import json
import os
import sys
import time
import unittest
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SUPPORT = os.path.join(REPO_ROOT, "tests", "support")
for path in (SUPPORT, os.path.join(REPO_ROOT, "src"), REPO_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from wificom import digirom, executor  # noqa: E402
from wificom.dmcomm_shim import CommandError  # noqa: E402


def resolve(signal, templates, replies):
    """The packets an adapter sends for *templates*, the toy answering with
    *replies*: before each of ours when the toy opens (turn 2), after each
    when we do. Returns the resolved packets."""
    state = digirom.AdapterState()
    out = []
    for template, reply in zip(templates, replies):
        if reply is not None:
            state.last_received = bytes.fromhex(reply)
        out.append(digirom.resolve_packet(signal, template, state))
    return out


class AdapterOperators(unittest.TestCase):
    def test_the_dmcomm_readme_example(self):
        """dmcomm's README: in `Y2-1017-0057-0007-@C^1^F7` the final
        response copies 3 bits of the second digit and 5 bits of the second
        and third inverted from the message just received, and its first
        digit makes the sum of the 16 digits sent 0xC."""
        sent = resolve("Y", "1017-0057-0007-@C^1^F7".split("-"),
                       ["1111", "2222", "3333", "ABCD"])
        self.assertEqual(sent[:3], ["1017", "0057", "0007"])
        final = sent[3]
        self.assertEqual(final[1:], "%X%X7" % (0xB ^ 1, 0xC ^ 0xF))
        total = sum(int(c, 16) for packet in sent for c in packet)
        self.assertEqual(total % 16, 0xC)

    def test_xor_reads_the_packet_just_received(self):
        """Turn 1: the adapter's second packet replies to the toy's FIRST
        packet -- the one just received -- not to the toy's second."""
        state = digirom.AdapterState()
        self.assertEqual(digirom.resolve_packet("V", "^F^F^F^F", state), "FFFF",
                         "before anything arrives the received bits are zero")
        state.last_received = bytes.fromhex("1234")
        self.assertEqual(digirom.resolve_packet("V", "^F^0^F^0", state), "E2C4")

    def test_the_check_digit_runs_over_the_whole_exchange(self):
        sent = resolve("V", ["0123", "@4000"], [None, "FFFF"])
        self.assertEqual(sent[1], "%X000" % ((4 - 6) % 16))

    def test_colour_word_instructions(self):
        state = digirom.AdapterState()
        state.last_received = bytes.fromhex("47444C43" + "0001000200030004" + "00050006")
        packet = digirom.resolve_packet(
            "C", "47444C43" + "________" + "1111" + "2222" + "++++" + "0000", state)
        words = [int(packet[i:i + 4], 16) for i in range(0, 32, 4)]
        self.assertEqual(words[:6], [0x4744, 0x4C43, 0x0001, 0x0002, 0x1111, 0x2222])
        self.assertEqual(words[6], sum(words[:6]) & 0xFFFF)

    def test_the_parser_takes_colour_words_on_the_colour_signal_only(self):
        rom = digirom.parse_command("C1-47444C43________00000000++++0000")
        self.assertEqual((rom.signal_type, len(rom), rom.packet_hex_length), ("C", 1, 32))
        with self.assertRaises(CommandError):
            digirom.parse_command("V1-++++")


class LineCheck(unittest.TestCase):
    """`executor.fits`: what the wire says, nothing inferred."""

    def test_a_rom_of_the_line(self):
        for fmt, code in (("DMOG", "V1-FC03-FD02"), ("DMM", "X1-0159-4379-2E49-@4009"),
                          ("IC", "IC1-C067-4257-0197-0007-@F007"),
                          ("DMC", "C1-47444C43000000010000000000009388")):
            with self.subTest(fmt=fmt):
                self.assertIsNone(executor.fits(digirom.parse_command(code), fmt))

    def test_refusals(self):
        cases = [
            ("DMC", "V1-FC03-FD02", "signal"),
            ("DMOG", "V1-FC03-FD02-FD02", "packets"),                  # DMOG sends two
            ("DM20", "V1-1234567890AB", "digits"),
            ("PENC", "C1-47444C43000000010000000000009388", "addressed"),   # DMC's magic
            ("TWIN", "IC2-0007", "battle format"),
            (None, "V1-FC03", "no battle format"),
        ]
        for fmt, code, word in cases:
            with self.subTest(fmt=fmt, code=code):
                problem = executor.fits(digirom.parse_command(code), fmt)
                self.assertIsNotNone(problem)
                self.assertIn(word, problem)

    def test_a_shared_wire_does_not_choose_the_line(self):
        """A DMX ROM fits PENZ as well as DMX: the wire cannot tell them
        apart, so the selection is what decides, and both are accepted."""
        rom = digirom.parse_command("V2-021E-218E-0D2E-142E-010E-@8^1^FE")
        self.assertIsNone(executor.fits(rom, "DMX"))
        self.assertIsNone(executor.fits(rom, "PENZ"))

    def test_no_inference_is_left(self):
        self.assertFalse(hasattr(executor, "battle_format_for"),
                         "the line must come from the session, never the ROM")

    def test_an_unanswered_rom_reads_as_nobody_answering(self):
        rom = digirom.parse_command("V1-FC03-FD02")
        self.assertEqual(executor.unanswered(rom, "DMC", "x").result, "s:FC03 t")
        rom = digirom.parse_command("V2-FC03-FD02")
        self.assertEqual(executor.unanswered(rom, "DMC", "x").result, "t")


class ServiceOverFakeSite(unittest.TestCase):
    """The WiFiCom service, online against the fake wificom.dev."""

    def setUp(self):
        import fake_wificom as fw
        from paths import temp_dir
        from core import game_globals
        from wificom import transport
        import services.wificom_service as ws
        self.fw, self.ws = fw, ws
        self.save = temp_dir("wificom_")
        fw.write_secrets(self.save)
        self.broker = fw.FakeBroker()
        self.site = fw.FakeWiFiComDev(self.broker)
        self.patches = [
            mock.patch.object(game_globals, "_get_base_save_dir", lambda: self.save),
            mock.patch.object(transport, "create_client", self.site.client_factory()),
            mock.patch.object(ws, "transport_available", lambda: True),
            # Upstream's mqtt.py prints every message; keep the run quiet.
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ]
        for p in self.patches:
            p.start()
        self.service = ws.wificom_service
        self.service.set_pet(object(), "DMC", 0)

    def tearDown(self):
        self.service.stop()
        for p in reversed(self.patches):
            p.stop()

    def start(self):
        self.assertTrue(self.service.start())
        self.assertTrue(self.site.wait_connected(5), self.service.last_error)
        deadline = time.monotonic() + 5
        while self.service.state != self.ws.STATE_ONLINE and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(self.service.state, self.ws.STATE_ONLINE)

    def answer(self, digirom_text, **extra):
        before = len(self.site.results())
        self.site.send_digirom(digirom_text, **extra)
        self.assertTrue(self.site.wait_for_results(before + 1, 5), "nothing was published")
        return self.site.results()[before]["output"]

    def wait_incoming(self, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            rom = self.service.take_incoming()
            if rom is not None:
                return rom
            time.sleep(0.01)
        return None

    def test_pause_info_and_unreadable_commands(self):
        self.start()
        self.assertEqual(self.answer("P"), "[pause]")
        info = self.answer("I")
        self.assertIn('name = "wificom"', info)
        self.assertIn('version = "', info)
        self.assertTrue(self.answer("Z1-1234").startswith("CommandError("))
        self.assertTrue(self.answer("V1-12G4").startswith("CommandError("))

    def test_requests_are_acknowledged_and_results_addressed(self):
        self.start()
        request = self.site.send_digirom("P", application_id="app-77")
        self.assertTrue(self.site.wait_for_results(1, 5))
        result = self.site.results()[0]
        self.assertEqual(result["application_uuid"], "app-77")
        self.assertEqual(result["device_uuid"], self.fw.SECRETS["device_uuid"])
        for key in ("name", "version", "circuitpython_version", "circuitpython_board_id",
                    "has_display", "output"):
            self.assertIn(key, result)
        self.assertTrue(self.broker.wait_for(
            lambda: any('"ack_id": %d' % request["ack_id"] in text
                        for _, text, _ in self.broker.published), 5))
        ack = [a for a in self.site.acks() if a["ack_id"] == request["ack_id"]][0]
        self.assertEqual(ack["device_uuid"], self.fw.SECRETS["device_uuid"])

    def test_a_rom_of_the_line_goes_to_the_game_unanswered_until_played(self):
        self.start()
        self.site.send_digirom("C2-47444C430001000100030019000193A6-47444C4300030004000000000000938E")
        rom = self.wait_incoming()
        self.assertIsNotNone(rom)
        self.assertEqual((rom.signal_type, rom.turn, len(rom)), ("C", 2, 2))
        time.sleep(0.1)
        self.assertEqual(self.site.results(), [], "answered before the pet played it")

    def test_a_rom_of_another_line_is_answered_as_nobody_answering(self):
        self.start()
        self.assertEqual(self.answer("V2-4D4F-494E"), "t")
        self.assertEqual(self.answer("C1-47444470001000000003001400028BDD"),
                         "s:47444470001000000003001400028BDD t")
        self.assertIsNone(self.service.take_incoming())
        self.assertIn("addressed to 47444470", self.service.notice)

    def test_a_request_naming_another_format_is_refused(self):
        self.start()
        code = "C1-47444C43000000010000000000009388"
        self.assertEqual(self.answer(code, battle_format="PENC"),
                         "s:47444C43000000010000000000009388 t")
        self.assertIn("PENC", self.service.notice)
        self.site.send_digirom(code, battle_format="DMC")
        self.assertIsNotNone(self.wait_incoming(), "the selected format was refused")

    def test_a_real_time_battle_invite_is_reported_and_left_behind(self):
        self.start()
        self.site.invite_rtb(invite_code="424242")
        self.assertTrue(self.broker.wait_for(
            lambda: any('"output": "RTB"' in text for _, text, _ in self.broker.published), 5),
            "no real-time heartbeat")
        self.assertIn("not supported", self.service.status_text)
        self.assertIn("424242", self.service.status_text)
        # A message upstream's real-time callback cannot read keeps the session.
        self.broker.publish("wificomhost/f/rtb-topic-1", "not json")
        time.sleep(0.2)
        self.assertEqual(self.service.state, self.ws.STATE_ONLINE)
        self.site.send_digirom("C1-47444C43000000010000000000009388")
        self.assertIsNotNone(self.wait_incoming(), "an ordinary DigiROM no longer reaches the pet")
        self.assertFalse(self.service.rtb_active, "upstream leaves the real-time battle")

    def test_a_malformed_request_does_not_drop_the_connection(self):
        self.start()
        self.site.send_raw("this is not json")
        self.site.send_raw(json.dumps({"application_id": "x"}))      # no digirom, no api_response
        self.assertEqual(self.answer("P"), "[pause]")
        self.assertEqual(self.service.state, self.ws.STATE_ONLINE)

    def test_the_device_pings_while_idle(self):
        self.start()
        self.assertTrue(self.broker.wait_for(
            lambda: any('"output": "None"' in text for _, text, _ in self.broker.published), 5))

    def test_no_ping_stands_in_for_a_result(self):
        """Upstream pings (output "None") only while no DigiROM is loaded:
        after a result it stays quiet until the app's P."""
        with mock.patch.object(self.ws, "PING_INTERVAL", 0.05):
            self.start()
            answered = self.answer("C1-47444470001000000003001400028BDD")
            self.assertTrue(answered.endswith(" t"))
            time.sleep(0.4)
            after = self.site.outputs()
            self.assertEqual(after[after.index(answered) + 1:], [], "pinged over the result")
            self.assertEqual(self.answer("P"), "[pause]")
            self.assertTrue(self.broker.wait_for(
                lambda: self.broker.published[-1][1].count('"output": "None"') == 1, 5),
                "no ping once paused")

    def test_a_turn_2_rom_waiting_for_the_toy_reads_as_listening(self):
        """Until BATTLE! starts it, the adapter's listen times out: "t"."""
        with mock.patch.object(self.ws, "PING_INTERVAL", 0.05):
            self.start()
            count = len(self.site.outputs())
            self.site.send_digirom(
                "C2-47444C430001000100030019000193A6-47444C4300030004000000000000938E")
            time.sleep(0.4)
            later = self.site.outputs()[count:]
            self.assertIn("t", later)
            self.assertNotIn("None", later)

    def test_a_result_queued_at_the_end_is_published(self):
        self.start()
        self.service.publish("s:FC03 r:FD02")
        self.service.stop()
        self.assertIn("s:FC03 r:FD02", self.site.outputs())

    def test_the_topics_follow_new_credentials(self):
        """mqtt.py builds its topics once, at import: a device swapped in the
        secrets file must not leave the session on the old one's topics."""
        self.start()
        self.service.stop()
        other = dict(self.fw.SECRETS, device_uuid="ffffffff-0000-0000-0000-000000000000")
        self.fw.write_secrets(self.save, other)
        site = self.fw.FakeWiFiComDev(self.broker, other)
        self.start_with(site)

    def start_with(self, site):
        self.assertTrue(self.service.start())
        self.assertTrue(site.wait_connected(5), "the new device's topic was never subscribed")

    def test_a_refused_login_is_reported_as_one(self):
        self.broker.accounts = {"someone-else": "x"}
        self.assertTrue(self.service.start())
        deadline = time.monotonic() + 5
        while self.service.state != self.ws.STATE_ERROR and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(self.service.last_error, "Login refused: check secrets.json")

    def test_a_dropped_connection_is_noticed(self):
        """paho does not raise when the broker goes away, it reports it; the
        screen must not go on saying Online over a dead socket."""
        self.start()
        self.broker.drop_all()
        deadline = time.monotonic() + 5
        while self.service.state == self.ws.STATE_ONLINE and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(self.service.state, self.ws.STATE_ERROR)
        self.assertEqual(self.service.status_text, "Connection lost")

    def test_no_credentials_no_connection(self):
        os.remove(os.path.join(self.save, "secrets.json"))
        with mock.patch.object(sys.modules["wificom.import_secrets"], "SECRETS_FILENAME",
                               "no-such-secrets.json"):
            self.assertFalse(self.service.start())
        self.assertEqual(self.service.state, self.ws.STATE_ERROR)
        self.assertEqual(self.service.last_error, "No credentials")


class PahoTransport(unittest.TestCase):
    """transport.MqttClient (paho-mqtt behind minimqtt's surface) and the
    whole service over it, against support/mini_mqtt_broker.py on this
    computer -- the one layer the fake client stands in for elsewhere. No
    TLS, which is the only difference from wificom.dev's broker."""

    def setUp(self):
        from wificom import transport
        if not transport.PAHO_AVAILABLE:
            self.skipTest("paho-mqtt not installed")
        from mini_mqtt_broker import MiniBroker
        import fake_wificom as fw
        self.fw, self.transport = fw, transport
        self.username = fw.SECRETS["mqtt_username"].lower()
        self.broker = MiniBroker({self.username: fw.SECRETS["mqtt_password"]})
        self.addCleanup(self.broker.close)
        self.stdout = mock.patch("sys.stdout", new_callable=io.StringIO)
        self.stdout.start()
        self.addCleanup(self.stdout.stop)

    def client(self, password=None):
        return self.transport.MqttClient(
            "127.0.0.1", self.username,
            password if password is not None else self.fw.SECRETS["mqtt_password"],
            port=self.broker.port, use_tls=False)

    def test_the_minimqtt_surface_over_paho(self):
        client = self.client()
        events = []
        client.on_connect = lambda c, u, f, rc: events.append(("connect", rc))
        client.on_subscribe = lambda c, u, topic, qos: events.append(("subscribe", topic))
        self.assertTrue(client.connect())
        client.subscribe("x/f/in")
        got = []
        client.add_topic_callback("x/f/in", lambda c, topic, message: got.append((topic, message)))
        deadline = time.monotonic() + 5
        while ("subscribe", "x/f/in") not in events and time.monotonic() < deadline:
            client.loop(0.05)
        self.broker.publish("x/f/in", '{"digirom": "P"}')
        while not got and time.monotonic() < deadline:
            client.loop(0.05)
        self.assertEqual(got, [("x/f/in", '{"digirom": "P"}')], "a message is a str, per topic")
        client.publish("x/f/out", "hello")
        while ("x/f/out", "hello") not in self.broker.published and time.monotonic() < deadline:
            client.loop(0.05)
        self.assertIn(("x/f/out", "hello"), self.broker.published)
        self.assertTrue(client.is_connected())
        client.disconnect()
        self.assertFalse(client.is_connected())

    def test_a_refused_login_raises_at_once(self):
        client = self.client(password="wrong")
        started = time.monotonic()
        with self.assertRaises(ConnectionRefusedError):
            client.connect(timeout=10)
        self.assertLess(time.monotonic() - started, 5, "waited out the timeout")
        self.assertEqual(client.refused_code, 5)

    def test_the_service_over_paho(self):
        from paths import temp_dir
        from core import game_globals
        import services.wificom_service as ws
        save = temp_dir("wificom_paho_")
        self.fw.write_secrets(save)
        input_topic, output_topic = self.fw.topics()
        patches = [mock.patch.object(game_globals, "_get_base_save_dir", lambda: save),
                   mock.patch.object(self.transport, "create_client", lambda *a, **k: self.client())]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        service = ws.wificom_service
        service.set_pet(object(), "DMC", 0)
        self.addCleanup(service.stop)
        self.assertTrue(service.start())
        deadline = time.monotonic() + 10
        while (not any(input_topic in t for t in self.broker.subscriptions.values())
               and time.monotonic() < deadline):
            time.sleep(0.02)
        self.assertEqual(service.state, ws.STATE_ONLINE, service.last_error)
        self.broker.publish(input_topic, json.dumps(
            {"digirom": "P", "application_id": "app-9", "api_response": False, "ack_id": 7}))
        self.broker.publish(input_topic, json.dumps(
            {"digirom": "C1-47444C43000000010000000000009388", "application_id": "app-9",
             "api_response": False}))

        def outputs():
            return [json.loads(text) for topic, text in list(self.broker.published)
                    if topic == output_topic]
        while time.monotonic() < deadline and not (
                any(m.get("output") == "[pause]" for m in outputs())
                and any(m.get("ack_id") == 7 for m in outputs())):
            time.sleep(0.02)
        self.assertTrue(any(m.get("output") == "[pause]" and m.get("application_uuid") == "app-9"
                            for m in outputs()), outputs())
        self.assertTrue(any(m.get("ack_id") == 7 for m in outputs()))
        rom = None
        while rom is None and time.monotonic() < deadline:
            rom = service.take_incoming()
            time.sleep(0.02)
        self.assertIsNotNone(rom, "the DMC DigiROM never reached the game")
        service.publish("s:47444C43000000010000000000009388 r:47444C43")
        service.stop()
        self.assertIn("s:47444C43000000010000000000009388 r:47444C43",
                      [m.get("output") for m in outputs()])


if __name__ == "__main__":
    unittest.main()
