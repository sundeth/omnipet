# -*- coding: utf-8 -*-
"""An online (Discord) battle through the real connect screens.

The owner (2026-10-21) linked two games, made a relay room on one and joined
it from the other; both stopped at "Battle not available" with an empty
"Your team" (the room screen never received the chosen pets). Here the game
is driven from pet selection through the room screen, against an in-memory
copy of Omninet's relay (the same answers as omninet/routes/discord.py and
GameRooms), with a second player scripted on the same relay link and
handshake (battle/relay_link.py, battle/lan_battle.py), as host and as guest:

* the chosen pets reach the room screen and the confirmation;
* Host Room makes a room the other player joins; Browse Rooms lists the
  other player's room and joins it;
* both press START, the host fights, the game plays the host's own log from
  its seat with the players' names, and counts it like any connection
  battle; the game returns to the main scene.

Checklist: BAT-04 (every battle mode works).
"""
import os
import random
import string
import sys
import threading
import unittest
from datetime import datetime
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "online"))
import battle_flow as bf  # noqa: E402
from online_ui import tap_button, tap_pet, view, wait_for  # noqa: E402

BATTLE_FRAMES = 12000
PLAYER_MODULE, PEER_MODULE = "DMC", "PENC"


class FakeRelay:
    """Omninet's relay rooms (GameRooms) behind DiscordModule._request."""

    def __init__(self):
        self.rooms = {}
        self.lock = threading.Lock()

    def create(self, host, name="Battle"):
        room_id = "".join(random.choices(string.ascii_uppercase, k=6))
        self.rooms[room_id] = {"id": room_id, "name": name, "host_name": host, "status": "waiting",
                               "guests": [], "data_queue": []}
        return room_id

    def join(self, room_id, player):
        room = self.rooms.get(room_id)
        if room is None:
            return 404, {"error": "Room not found"}
        if room["status"] != "waiting":
            return 400, {"error": "Room already in battle"}
        room["guests"].append(player)
        room["status"] = "ready"
        return 200, {"success": True, "status": "ready"}

    def status(self, room_id):
        room = self.rooms.get(room_id)
        if room is None:
            return 404, {"error": "Room not found"}
        return 200, {"id": room_id, "status": room["status"], "host": room["host_name"],
                     "guests": list(room["guests"]),
                     "opponent": room["guests"][0] if room["guests"] else None,
                     "data_queue": room["data_queue"][-50:]}

    def post(self, room_id, data):
        room = self.rooms.get(room_id)
        if room is None:
            return 404, {"error": "Room not found"}
        room["data_queue"].append({"ts": datetime.now().isoformat(), "data": data})
        del room["data_queue"][:-50]
        return 200, {"success": True}

    def request(self, _discord, method, path, payload=None):
        with self.lock:
            parts = path.strip("/").split("/")
            if method == "GET" and parts == ["rooms"]:
                return 200, [{"id": r["id"], "room_id": r["id"], "name": r["name"],
                              "host": r["host_name"], "status": r["status"]}
                             for r in self.rooms.values()]
            if method == "POST" and parts == ["room"]:
                room_id = self.create(payload.get("host"), payload.get("name"))
                return 200, {"success": True, "room_id": room_id, "room_code": room_id}
            if parts[0] == "room" and len(parts) == 3:
                room_id, action = parts[1], parts[2]
                if method == "POST" and action == "join":
                    return self.join(room_id, payload.get("player"))
                if method == "GET" and action == "status":
                    return self.status(room_id)
                if method == "POST" and action == "data":
                    return self.post(room_id, payload)
            return 404, {"detail": "Not Found"}

    def peer_link(self, room_id, role):
        from battle.relay_link import RelayLink

        def post(data):
            with self.lock:
                return self.post(room_id, data)[0] == 200

        def fetch():
            with self.lock:
                status, body = self.status(room_id)
            return body["data_queue"] if status == 200 else None
        return RelayLink(post, fetch, role, poll_seconds=0.05)


@unittest.skipUnless(all(os.path.isdir(os.path.join(bf.MODULES, m))
                         for m in (PLAYER_MODULE, PEER_MODULE)), "modules not present")
class OnlineBattle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness import Env
        cls.env = Env("240x240")

    def setUp(self):
        from scenes.scene_connect import DiscordModule
        self.relay = FakeRelay()
        relay = self.relay

        def linked(module):
            module.linked_account, module.account_name, module.user_id = "AB12", "Tamer", "1"

        self.patches = [
            patch.object(DiscordModule, "_request", lambda module, m, p, payload=None:
                         relay.request(module, m, p, payload)),
            patch.object(DiscordModule, "_load_data", linked),
            patch.object(DiscordModule, "check_connection", lambda module: True),
        ]
        for p in self.patches:
            p.start()
        self.peer = None

    def tearDown(self):
        for p in self.patches:
            p.stop()
        if self.peer is not None:
            self.peer.close()
        if hasattr(self.env.rg, "pvp_battle_data"):
            delattr(self.env.rg, "pvp_battle_data")

    # ------------------------------------------------------------ the flow
    def open_rooms(self):
        """The game on the room screen with two pets chosen."""
        env = self.env
        for name in (PLAYER_MODULE, PEER_MODULE):
            if bf.installed(name) is None:
                self.skipTest(f"{name} not installed")
        bf.fresh(env, seed=4, input_mode=env.rg.TOUCH_MODE)
        pets = [bf.ensure_battle_record(bf.battle_pet(PLAYER_MODULE)),
                bf.ensure_battle_record(bf.battle_pet(PLAYER_MODULE, stage=4))]
        bf.set_party(env, pets)
        env.rg.scene_connect_initial_view = ("pet_selection", {"is_online_mode": True})
        game = env.game("connect")
        env.frames(game, 2)
        selector = game.scene.current_view.pet_selector
        for i in range(len(pets)):
            tap_pet(env, game, selector, i)
        tap_button(env, game, "CONFIRM")
        self.assertEqual(view(game), "discord")
        self.assertEqual(game.scene.current_view.selected_pets, pets,
                         "the room screen did not get the chosen pets")
        return game, pets

    def peer_pets(self):
        return [bf.ensure_battle_record(bf.battle_pet(PEER_MODULE))]

    def frames_until(self, game, cond, peer=None, frames=900):
        for _ in range(frames):
            if peer is not None:
                peer.update()
            if cond():
                return True
            self.env.frames(game, 1)
            wait_for(lambda: False, 0.005)
        return bool(cond())

    def fight(self, game, pets, is_host):
        from battle.arena import replay
        from scenes.scene_battle_pvp import SceneBattlePvP
        from scenes.scene_maingame import SceneMainGame
        env, peer = self.env, self.peer
        self.assertTrue(self.frames_until(game, lambda: view(game) == "battle_confirm", peer))
        confirm = game.scene.current_view
        self.assertIsNotNone(confirm.session, "no battle behind the confirmation")
        self.assertTrue(self.frames_until(
            game, lambda: confirm.session.state == "confirm" and peer.state == "confirm", peer),
            f"no hello: {confirm.session.state}/{peer.state}")
        self.assertIn(pets[0].name, confirm.info_panel.text)
        self.assertIn(peer.pets[0].name, confirm.info_panel.text)
        self.assertEqual(confirm.session.opponent["name"], "Peer")

        record = [(p.battles, p.win, p.pvp_battles, p.pvp_wins) for p in pets]
        tap_button(env, game, "START")
        self.assertTrue(peer.press_start())
        self.assertTrue(self.frames_until(game, lambda: isinstance(game.scene, SceneBattlePvP), peer),
                        f"the battle never opened: {confirm.session.state} {confirm.session.error}")
        data = env.rg.pvp_battle_data
        self.assertTrue(data["is_online_mode"])
        self.assertEqual((data["my_player_name"], data["enemy_player_name"]), ("Tamer", "Peer"))
        encounter = game.scene.battle_encounter
        for _ in range(BATTLE_FRAMES):
            if encounter.phase == "result":
                break
            env.frames(game, 1)
        self.assertEqual(encounter.phase, "result")
        _mine, _theirs, result, _a, _b = replay.viewer_side(peer.log, is_host)
        self.assertEqual([max(0, h) for h in encounter.battle_player.team1_hp],
                         [s["hp"] for s in result["device1_final"]])
        self.assertEqual(encounter.victory_status, replay.victory_status(result["winner"]))
        for _ in range(BATTLE_FRAMES):
            if not isinstance(game.scene, SceneBattlePvP):
                break
            env.frames(game, 1)
        self.assertIsInstance(game.scene, SceneMainGame)
        self.assertEqual(bf.battle_errors(env), [])
        won = encounter.victory_status == "Victory"
        for pet, (battles, wins, pvp_battles, pvp_wins) in zip(pets, record):
            self.assertEqual((pet.battles, pet.win, pet.pvp_battles, pet.pvp_wins),
                             (battles + 1, wins + won, pvp_battles + 1, pvp_wins + won))

    # ------------------------------------------------------------ tests
    def test_hosting_a_room_another_player_joins(self):
        from battle import lan_battle
        env = self.env
        game, pets = self.open_rooms()
        rooms_view = game.scene.current_view
        env.press(game, "A")                                    # Host Room
        self.assertTrue(wait_for(lambda: self.relay.rooms, 5), "no room was made")
        room_id = next(iter(self.relay.rooms))
        with self.relay.lock:
            self.assertEqual(self.relay.join(room_id, "Peer")[0], 200)
        self.assertTrue(self.frames_until(game, lambda: view(game) == "battle_confirm", frames=300)
                        or wait_for(lambda: rooms_view._discord_opponent_found, 3))
        self.peer = lan_battle.Session(self.relay.peer_link(room_id, "guest"), False,
                                       self.peer_pets(), name="Peer", game="test")
        self.fight(game, pets, is_host=True)

    def test_joining_another_players_room(self):
        from battle import lan_battle
        env = self.env
        game, pets = self.open_rooms()
        with self.relay.lock:
            room_id = self.relay.create("Peer", "Peer's Room")
        self.peer = lan_battle.Session(self.relay.peer_link(room_id, "host"), True,
                                       self.peer_pets(), name="Peer", game="test")
        rooms_view = game.scene.current_view
        env.press(game, "DOWN")
        env.press(game, "A")                                    # Browse Rooms
        self.assertTrue(self.frames_until(game, lambda: rooms_view.available_rooms, frames=300),
                        "the room list never came")
        env.frames(game, 1)
        rooms_view._on_room_select(0)                           # the listed room
        self.fight(game, pets, is_host=False)

    def test_cancel_goes_back_to_the_rooms(self):
        from battle import lan_battle
        env = self.env
        game, pets = self.open_rooms()
        with self.relay.lock:
            room_id = self.relay.create("Peer")
        self.peer = lan_battle.Session(self.relay.peer_link(room_id, "host"), True,
                                       self.peer_pets(), name="Peer", game="test")
        game.scene.current_view._join_room({"room_id": room_id, "host": "Peer"})
        env.frames(game, 1)
        self.assertEqual(view(game), "battle_confirm")
        tap_button(env, game, "CANCEL")
        self.assertEqual(view(game), "discord")
        self.assertEqual(game.scene.current_view.selected_pets, pets)
        self.assertEqual(game.scene.current_view.host_join_menu.options,
                         ["Host Room", "Browse Rooms", "Back"])
        self.assertTrue(self.frames_until(game, lambda: self.peer.state == "closed", self.peer),
                        "the other player never heard the cancel")


if __name__ == "__main__":
    unittest.main()
