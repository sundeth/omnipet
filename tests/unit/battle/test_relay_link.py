"""Online (Discord) battles over Omninet's relay rooms (battle/relay_link.py).

The owner (2026-10-21) linked two games through Discord, made a room on one
and joined it from the other, and both stopped at "Battle not available":
nothing fought over a room. A room is one message queue both players post
to and read the last 50 entries of (Omninet's GameRooms); RelayLink makes it
the same kind of link the WiFi battle uses, so the same handshake
(battle/lan_battle.py) runs over it. Here, against an in-memory room with
the relay's own behaviour:

* both games say hello, both press START, the host fights and the guest
  receives the very log the host plays;
* a game reads only the other side's entries, each once and in order, and
  ignores anything else in the room;
* a cancel reaches the other side as "the opponent left", even though the
  link closes right after sending it; a room that disappears closes the link.
"""
import os
import sys
import threading
import time
import unittest
from types import SimpleNamespace

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
if os.path.join(ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "src"))

from battle import lan_battle  # noqa: E402
from battle.relay_link import RelayLink  # noqa: E402

QUEUE_MAX = 50          # Omninet's relay keeps the last 50 entries


class Room:
    """Omninet's GameRooms for one room: post appends, fetch reads the tail."""

    def __init__(self):
        self.queue = []
        self.gone = False
        self.lock = threading.Lock()

    def post(self, data):
        with self.lock:
            if self.gone:
                return False
            self.queue.append({"ts": "now", "data": data})
            del self.queue[:-QUEUE_MAX]
            return True

    def fetch(self):
        with self.lock:
            return None if self.gone else list(self.queue[-QUEUE_MAX:])


class FakePet(SimpleNamespace):
    def get_power(self):
        return self.power

    def get_hp(self):
        return self.hp


def pet(name, power=50):
    return FakePet(name=name, module="DMC", version=1, stage=4, attribute="Va", level=3,
                   power=power, hp=10, atk_main=3, atk_alt=4, atk_alt_2=0,
                   traited=False, shook=False, effort=0)


def wait(cond, sessions=(), timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        for s in sessions:
            s.update()
        if cond():
            return True
        time.sleep(0.01)
    return bool(cond())


class RelayBattle(unittest.TestCase):
    def setUp(self):
        self.room = Room()
        self.host_link = RelayLink(self.room.post, self.room.fetch, "host", poll_seconds=0.02)
        self.guest_link = RelayLink(self.room.post, self.room.fetch, "guest", poll_seconds=0.02)

    def tearDown(self):
        self.host_link.close()
        self.guest_link.close()

    def sessions(self):
        host = lan_battle.Session(self.host_link, True, [pet("Agumon", 60), pet("Gabumon")],
                                  name="HostTamer", game="test")
        guest = lan_battle.Session(self.guest_link, False, [pet("Betamon", 45)],
                                   name="GuestTamer", game="test")
        return host, guest

    def test_both_games_play_the_hosts_battle(self):
        host, guest = self.sessions()
        self.assertTrue(wait(lambda: host.state == guest.state == "confirm", (host, guest)))
        self.assertEqual(guest.opponent["name"], "HostTamer")
        self.assertEqual([e["name"] for e in host.opponent["team"]], ["Betamon"])
        host.press_start()
        wait(lambda: False, (host, guest), timeout=0.2)
        self.assertIsNone(host.log, "the host waits for the guest's START")
        guest.press_start()
        self.assertTrue(wait(lambda: host.log and guest.log, (host, guest)))
        self.assertEqual(guest.log, host.log)
        data = lan_battle.pvp_battle_data(guest.log, guest.pets, False, online=True)
        self.assertTrue(data["is_online_mode"])
        self.assertEqual(data["enemy_player_name"], "HostTamer")
        self.assertEqual(data["my_player_name"], "GuestTamer")

    def test_each_message_once_in_order_and_nothing_else(self):
        self.room.post({"type": "host_data", "note": "the bot's own entries"})
        self.room.post("plain text")
        for n in range(3):
            self.guest_link.send({"type": "n", "n": n})
        got = []
        self.assertTrue(wait(lambda: got.extend(self.host_link.poll()) or len(got) >= 3))
        wait(lambda: got.extend(self.host_link.poll()) and False, timeout=0.2)
        self.assertEqual([m["n"] for m in got], [0, 1, 2])
        self.assertEqual(self.guest_link.poll(), [], "a game never reads its own messages")

    def test_a_cancel_reaches_the_other_side(self):
        host, guest = self.sessions()
        wait(lambda: host.state == guest.state == "confirm", (host, guest))
        guest.cancel()
        self.assertTrue(self.guest_link.closed)
        self.assertTrue(wait(lambda: host.state == "closed", (host,)))
        self.assertEqual(host.error, "The opponent left")

    def test_a_room_that_disappears_closes_the_link(self):
        host, _guest = self.sessions()
        self.room.gone = True
        self.assertTrue(wait(lambda: host.state == "closed", (host,)))
        self.assertEqual(host.error, "The opponent left")




if __name__ == "__main__":
    unittest.main()
