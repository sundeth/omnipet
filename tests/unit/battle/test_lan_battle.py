"""WiFi battles between two Omnipets on one network (battle/lan_link.py,
battle/lan_battle.py), over this computer's loopback.

The owner (2026-10-21) ran two games on one computer: the first hosted, the
second never saw it. Join only waited two seconds and showed an empty list,
and the confirm screen could not start a battle at all. Here:

* a host is found by discovery (loopback, as two games on one computer
  find each other) on the port it announces, and is listed once;
* both games say hello, both press START, the host fights the battle with
  the arena's rules (the battle contract: OMNIPET with the DMX defaults) and
  the joining game receives the very log the host plays;
* each game's seat sees the same battle: its own team as team1, the
  verdicts mirrored, the joining game with the host shooting first;
* a peer on another protocol, a team that cannot battle, a cancel and a
  hang-up end the handshake with a reason; a peer's numbers are bounded;
* the battle leaves the game's own random sequence where it was.
"""
import os
import random
import socket
import sys
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
if os.path.join(ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "src"))

from battle import lan_battle  # noqa: E402
from battle.arena import engine  # noqa: E402
from battle import lan_link  # noqa: E402

LOOPBACK = ["127.0.0.1"]


def setUpModule():
    """A discovery port of the tests' own: a game hosting on this computer
    while the tests run must neither answer them nor be joined by them."""
    global _PORT
    _PORT = patch.object(lan_link, "DISCOVERY_PORT", private_udp_port())
    _PORT.start()


def tearDownModule():
    _PORT.stop()


def private_udp_port():
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]
    finally:
        probe.close()


def wait(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return bool(cond())


class FakePet(SimpleNamespace):
    """What team_entry reads off a GamePet."""

    def get_power(self):
        return self.power

    def get_hp(self):
        return self.hp


def pet(name, power=40, hp=10, attribute="Va", stage=3, module="DMC"):
    return FakePet(name=name, module=module, version=1, stage=stage, attribute=attribute,
                   level=1, power=power, hp=hp, atk_main=3, atk_alt=4, atk_alt_2=0,
                   traited=False, shook=False, effort=0)


def pair():
    """A host and a joined LanConnection on loopback, found by discovery."""
    host = lan_link.LanHost({"code": "AB12", "name": "Host", "pets": 1}).start()
    try:
        found = lan_link.discover(seconds=1.0, interval=0.2, targets=LOOPBACK)
        joined = lan_link.connect(found[0]["address"], found[0]["port"])
        assert wait(lambda: host._joined is not None), "the host never saw the connection"
        return host.poll(), joined, found
    finally:
        host.close()


def run(*sessions, until, timeout=5.0):
    def done():
        for s in sessions:
            s.update()
        return until()
    return wait(done, timeout)


class Discovery(unittest.TestCase):
    def test_a_host_is_found_once_on_the_port_it_announces(self):
        hosting, joined, found = pair()
        try:
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]["code"], "AB12")
            self.assertEqual(found[0]["name"], "Host")
            self.assertEqual(found[0]["protocol"], lan_link.PROTOCOL)
            self.assertNotEqual(found[0]["port"], 5555, "BlueStacks' ADB port")
            self.assertTrue(hosting.send({"type": "ping"}))
            self.assertTrue(wait(lambda: joined.poll() == [{"type": "ping"}] or False))
        finally:
            hosting.close()
            joined.close()

    def test_nothing_is_found_when_nobody_hosts(self):
        self.assertEqual(lan_link.discover(seconds=0.5, interval=0.2, targets=LOOPBACK), [])

    def test_a_closed_host_stops_answering(self):
        host = lan_link.LanHost({"code": "ZZ99"}).start()
        host.close()
        self.assertEqual(lan_link.discover(seconds=0.5, interval=0.2, targets=LOOPBACK), [])

    def test_the_broadcast_targets_include_this_computer(self):
        targets = lan_link.broadcast_targets()
        self.assertEqual(targets[0], "255.255.255.255")
        self.assertIn("127.0.0.1", targets)

    def test_a_hang_up_is_seen(self):
        hosting, joined, _found = pair()
        joined.close()
        self.assertTrue(wait(lambda: hosting.closed))
        self.assertFalse(hosting.send({"type": "ping"}))


class Battle(unittest.TestCase):
    def setUp(self):
        self.links = pair()[:2]
        self.host_pets = [pet("Agumon", power=60), pet("Gabumon", power=30, attribute="Da")]
        self.guest_pets = [pet("Betamon", power=45, attribute="Vi")]

    def tearDown(self):
        for link in self.links:
            link.close()

    def sessions(self):
        hosting, joined = self.links
        host = lan_link_session(hosting, True, self.host_pets, "Host")
        guest = lan_link_session(joined, False, self.guest_pets, "Guest")
        return host, guest

    def test_both_games_play_the_hosts_battle_from_their_own_seat(self):
        host, guest = self.sessions()
        self.assertTrue(run(host, guest, until=lambda: host.state == guest.state == "confirm"))
        self.assertEqual([e["name"] for e in host.opponent["team"]], ["Betamon"])
        self.assertEqual(guest.opponent["name"], "Host")
        self.assertTrue(host.press_start())
        run(host, guest, until=lambda: False, timeout=0.3)
        self.assertEqual(host.state, "waiting", "the host waits for the guest's START")
        self.assertIsNone(host.log)
        self.assertTrue(guest.press_start())
        self.assertTrue(run(host, guest, until=lambda: host.log and guest.log))
        self.assertEqual(guest.log, host.log, "the guest plays the host's own log")
        log = host.log
        self.assertEqual(log["rules"]["battle_format"], "DMX")
        self.assertEqual(log["rules"], engine.effective_rules())
        self.assertEqual([p["name"] for p in log["attacker"]["pets"]], ["Agumon", "Gabumon"])

        from battle.arena import replay
        mine, theirs, result, my_hp, their_hp = replay.viewer_side(log, True)
        g_mine, g_theirs, g_result, g_my_hp, g_their_hp = replay.viewer_side(log, False)
        self.assertEqual(mine["pets"], g_theirs["pets"])
        self.assertEqual((my_hp, their_hp), (g_their_hp, g_my_hp))
        verdicts = {replay.victory_status(result["winner"]), replay.victory_status(g_result["winner"])}
        self.assertIn(verdicts, ({"Victory", "Defeat"}, {"Draw"}))

    def test_the_battle_is_the_engines_for_its_seed(self):
        host, guest = self.sessions()
        run(host, guest, until=lambda: host.state == guest.state == "confirm")
        host.press_start()
        guest.press_start()
        self.assertTrue(run(host, guest, until=lambda: guest.log))
        again = lan_battle.fight(host.team, host.opponent["team"], host.log["seed"])
        self.assertEqual(again["result"], host.log["result"])

    def test_a_cancel_ends_the_other_side_with_a_reason(self):
        host, guest = self.sessions()
        run(host, guest, until=lambda: host.state == guest.state == "confirm")
        guest.cancel()
        self.assertTrue(run(host, until=lambda: host.state == "closed"))
        self.assertEqual(host.error, "The opponent left")
        self.assertFalse(host.press_start())

    def test_a_peer_on_another_protocol_is_refused(self):
        hosting, joined = self.links
        host = lan_link_session(hosting, True, self.host_pets, "Host")
        joined.send({"type": "hello", "protocol": lan_battle.PROTOCOL + 1, "team": []})
        self.assertTrue(run(host, until=lambda: host.state == "closed"))
        self.assertEqual(host.error, "Different game version")

    def test_a_team_that_cannot_battle_is_refused(self):
        hosting, joined = self.links
        host = lan_link_session(hosting, True, self.host_pets, "Host")
        joined.send({"type": "hello", "protocol": lan_battle.PROTOCOL,
                     "team": [{"name": "Botamon", "module": "DMC", "atk_main": 0}]})
        self.assertTrue(run(host, until=lambda: host.state == "closed"))
        self.assertEqual(host.error, "Their team cannot battle")


def lan_link_session(link, is_host, pets, name):
    return lan_battle.Session(link, is_host, pets, name=name, game="test")


class Entries(unittest.TestCase):
    def test_a_peers_numbers_are_bounded(self):
        entry = lan_battle.clean_entry({
            "name": "X" * 99, "module": "DMC", "version": 0, "stage": 42, "attribute": "virus",
            "level": -5, "power": 10 ** 9, "hp": 0, "atk_main": 7, "atk_alt": None,
            "effort": 500, "traited": 1})
        self.assertEqual(len(entry["name"]), 40)
        self.assertEqual(entry["version"], 0, "version 0 is a real version")
        self.assertEqual((entry["stage"], entry["level"]), (9, 1))
        self.assertEqual((entry["power"], entry["hp"]), (9999, 1))
        self.assertEqual(entry["attribute"], "Vi")
        self.assertEqual(entry["atk_alt"], 7, "no second attack: the first")
        self.assertEqual(entry["effort"], engine.MAX_EFFORT)
        self.assertIs(entry["traited"], True)

    def test_what_is_not_a_team_is_refused(self):
        for team in (None, [], [{}] * 5, [{"name": "A", "module": "DMC", "atk_main": 1}]):
            with self.subTest(team=team), self.assertRaises(ValueError):
                lan_battle.clean_team(team)

    def test_the_games_random_sequence_is_left_alone(self):
        team = [lan_battle.team_entry(pet("Agumon"))]
        random.seed(1234)
        expected = [random.random() for _ in range(3)]
        random.seed(1234)
        lan_battle.fight(team, team, seed=99)
        self.assertEqual([random.random() for _ in range(3)], expected)


if __name__ == "__main__":
    unittest.main()
