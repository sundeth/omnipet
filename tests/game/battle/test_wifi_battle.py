# -*- coding: utf-8 -*-
"""A WiFi battle through the real connect screens, against a second Omnipet.

The owner (2026-10-21) ran two games on one computer: the first hosted, the
second never saw it (Join waited two seconds and listed nothing), and the
confirmation screen could not have started a battle anyway. Here the game
under test is driven the way a player does it, and the other Omnipet is
scripted with the same link and handshake (battle/lan_link.py,
battle/lan_battle.py) over this computer's loopback, in both roles:

* the WiFi button leads to pet selection; the chosen pets go on to
  Host/Join;
* Host: the game shows its code and waits, the other game finds it by
  discovery and connects; Join: the game lists the other game's host and
  connects to it;
* both teams appear on the confirmation, START waits for the other player,
  and the battle opens once the host has fought it;
* the game plays the host's own log from its seat (its pets as team1, on
  the log's HP; the joining game with the host shooting first) and ends on
  the log's verdict;
* the battle counts like any connection battle (battles, wins, PvP counts)
  and the game returns to the main scene.

Checklist: BAT-04 (every battle mode works), BAT-02.
"""
import os
import socket
import sys
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "online"))
import battle_flow as bf  # noqa: E402
from online_ui import tap_button, tap_pet, view, wait_for  # noqa: E402

BATTLE_FRAMES = 12000
PLAYER_MODULE, PEER_MODULE = "DMC", "PENC"


@unittest.skipUnless(all(os.path.isdir(os.path.join(bf.MODULES, m))
                         for m in (PLAYER_MODULE, PEER_MODULE)), "modules not present")
class WifiBattle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness import Env
        cls.env = Env("240x240", network="local")

    def setUp(self):
        from battle import lan_link
        self.lan_link = lan_link
        # Discovery stays on this computer, on a port of the test's own (a
        # game hosting here while the tests run must not answer them).
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        self.patches = [patch.object(lan_link, "broadcast_targets", lambda: ["127.0.0.1"]),
                        patch.object(lan_link, "DISCOVERY_PORT", port)]
        for p in self.patches:
            p.start()
        self.peer = self.peer_host = None

    def tearDown(self):
        for p in self.patches:
            p.stop()
        for thing in (self.peer, self.peer_host):
            if thing is not None:
                thing.close()
        if hasattr(self.env.rg, "pvp_battle_data"):
            delattr(self.env.rg, "pvp_battle_data")

    # ------------------------------------------------------------ the flow
    def open_wifi(self):
        """The game on Host/Join with two pets chosen. Returns (game, pets)."""
        env = self.env
        for name in (PLAYER_MODULE, PEER_MODULE):
            if bf.installed(name) is None:
                self.skipTest(f"{name} not installed")
        bf.fresh(env, seed=3, input_mode=env.rg.TOUCH_MODE)
        pets = [bf.ensure_battle_record(bf.battle_pet(PLAYER_MODULE)),
                bf.ensure_battle_record(bf.battle_pet(PLAYER_MODULE, stage=4))]
        bf.set_party(env, pets)
        game = env.game("connect")
        env.frames(game, 2)
        game.scene.current_view._on_wifi_selected()          # the WiFi button
        env.frames(game, 1)
        self.assertEqual(view(game), "pet_selection")
        selector = game.scene.current_view.pet_selector
        for i in range(len(pets)):
            tap_pet(env, game, selector, i)
        tap_button(env, game, "CONFIRM")
        self.assertEqual(view(game), "wifi_hosting")
        self.assertEqual(game.scene.current_view.selected_pets, pets)
        return game, pets

    def peer_pets(self):
        return [bf.ensure_battle_record(bf.battle_pet(PEER_MODULE))]

    def frames_until(self, game, cond, peer=None, frames=600):
        for _ in range(frames):
            if peer is not None:
                peer.update()
            if cond():
                return True
            self.env.frames(game, 1)
            wait_for(lambda: False, 0.005)
        return bool(cond())

    def confirm_and_fight(self, game, peer, pets, is_host):
        """START on both sides; the battle scene to its end."""
        from scenes.scene_battle_pvp import SceneBattlePvP
        from scenes.scene_maingame import SceneMainGame
        env = self.env
        self.assertTrue(self.frames_until(game, lambda: view(game) == "battle_confirm", peer))
        confirm = game.scene.current_view
        self.assertTrue(self.frames_until(
            game, lambda: confirm.session.state == "confirm" and peer.state == "confirm", peer),
            f"no hello: {confirm.session.state}/{peer.state}")
        panel = confirm.info_panel.text
        self.assertIn(peer.pets[0].name, panel)
        self.assertIn(pets[0].name, panel)

        record = [(p.battles, p.win, p.pvp_battles, p.pvp_wins) for p in pets]
        tap_button(env, game, "START")
        self.assertEqual(confirm.session.state, "waiting")
        env.frames(game, 5)
        self.assertEqual(view(game), "battle_confirm", "the battle began before the other START")
        self.assertTrue(peer.press_start())
        self.assertTrue(self.frames_until(game, lambda: isinstance(game.scene, SceneBattlePvP), peer),
                        f"the battle never opened: {confirm.session.state} {confirm.session.error}")
        log = peer.log
        self.assertIsNotNone(log, "the other game has no battle")
        data = env.rg.pvp_battle_data
        self.assertEqual(data["my_pets"], pets, "the real pets fight")
        encounter = game.scene.battle_encounter
        self.assertEqual(encounter.presentation_format, "DMX")

        for _ in range(BATTLE_FRAMES):
            if encounter.phase == "result":
                break
            env.frames(game, 1)
        self.assertEqual(encounter.phase, "result")
        from battle.arena import replay
        _mine, _theirs, result, _my_hp, _their_hp = replay.viewer_side(log, is_host)
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
                             (battles + 1, wins + won, pvp_battles + 1, pvp_wins + won),
                             f"{pet.name}'s record")

    # ------------------------------------------------------------ tests
    def test_hosting_a_battle_another_omnipet_joins(self):
        from battle import lan_battle
        env = self.env
        game, pets = self.open_wifi()
        env.press(game, "A")                                    # Host Battle
        env.frames(game, 1)
        hosting = game.scene.current_view
        self.assertEqual(hosting.phase, "hosting")
        self.assertIn(hosting.host_code, hosting.code_label.text)

        found = self.lan_link.discover(seconds=1.0, interval=0.2)
        self.assertEqual([h["code"] for h in found], [hosting.host_code])
        self.assertEqual(found[0]["pets"], len(pets))
        link = self.lan_link.connect(found[0]["address"], found[0]["port"])
        self.peer = lan_battle.Session(link, False, self.peer_pets(), name="Peer", game="test")
        self.confirm_and_fight(game, self.peer, pets, is_host=True)

    def test_joining_another_omnipets_battle(self):
        from battle import lan_battle
        env = self.env
        game, pets = self.open_wifi()
        self.peer_host = self.lan_link.LanHost({"code": "PEER", "name": "Peer", "pets": 1}).start()
        env.press(game, "DOWN")
        env.press(game, "A")                                    # Join Battle
        joining = game.scene.current_view
        self.assertTrue(self.frames_until(game, lambda: joining.phase == "device_list", frames=900),
                        f"the search never finished: {joining.phase}")
        self.assertEqual([h["code"] for h in joining.hosts], ["PEER"])
        self.assertTrue(joining.device_list_menu.options[0].startswith("PEER"))
        env.press(game, "A")                                    # the host listed
        self.assertTrue(self.frames_until(game, lambda: self.peer_host._joined is not None),
                        f"never connected: {joining.phase}")
        link = self.peer_host.poll()
        self.peer = lan_battle.Session(link, True, self.peer_pets(), name="Peer", game="test")
        self.confirm_and_fight(game, self.peer, pets, is_host=False)

    def test_the_other_player_leaving_ends_the_confirmation(self):
        from battle import lan_battle
        env = self.env
        game, _pets = self.open_wifi()
        env.press(game, "A")
        env.frames(game, 1)
        found = self.lan_link.discover(seconds=1.0, interval=0.2)
        link = self.lan_link.connect(found[0]["address"], found[0]["port"])
        self.peer = lan_battle.Session(link, False, self.peer_pets(), name="Peer", game="test")
        self.assertTrue(self.frames_until(game, lambda: view(game) == "battle_confirm", self.peer))
        confirm = game.scene.current_view
        self.assertTrue(self.frames_until(game, lambda: confirm.session.state == "confirm", self.peer))
        self.peer.cancel()
        self.assertTrue(self.frames_until(game, lambda: confirm.session.state == "closed"))
        self.assertEqual(confirm.status_label.text, "The opponent left")
        self.assertFalse(confirm.start_button.enabled)
        tap_button(env, game, "BACK")
        self.assertEqual(view(game), "wifi_hosting")
        self.assertEqual(bf.battle_errors(env), [])


if __name__ == "__main__":
    unittest.main()
