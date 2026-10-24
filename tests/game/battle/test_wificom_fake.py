# -*- coding: utf-8 -*-
"""A WiFiCom battle on every battle format, against a fake wificom.dev.

Omnipet acts as a WiFiCom: it logs in to wificom.dev's broker with the
device's ``secrets.json``, an app sends it a DigiROM through the site, the pet
answers it as the toy behind the WiFiCom would, the exchange goes back to the
app, and a whole battle plays out in the battle scene. The battle contract
(CLAUDE.md) says a WiFi-Com battle is fought on the exact format selected for
the request, never one inferred from the packets.

Nothing reaches the network: ``wificom.transport.create_client`` hands the
vendored ``mqtt.py`` a client on ``support/fake_wificom.py``'s in-memory
broker, whose topics and messages are wificom-lib's own (see that file).
The DigiROM the app sends is the one a DCom cable sends a device of the line
(``PacketExchange.cable_command``: the role stock operators can express,
``^``/``@`` and all), built from a pet of the line's native module -- so the
opponent is a real side of the line, never invented. The community's
known-good punchbag codes (``support/data/digiroms.txt``) are played too.

Each format is played the way a player does it: the WiFiCom view opens on
the pet, the format's box is tapped in the protocol grid, the charge
minigame is mashed, the view goes online, the app sends the ROM, BATTLE! is
pressed when the ROM is turn 2 (the adapter listens, so the toy starts the
battle), the battle scene plays it and the game returns to the main scene.
Each run must:

* publish exactly one result, the adapter's ``s:``/``r:`` report in the
  ROM's turn order (turn 2 ending in ``t``, as every capture does), with the
  request's application id and the device's version info, and acknowledge
  the request's ``ack_id``;
* hand the battle scene the exchange on the chosen format (skip_charge, the
  wire's HP, OEM for a native pet), with no exception and no error logged;
* end on the verdict the device reads from the same packets;
* count the connection battle (pvp_battles, pvp_wins) and the battle record
  (battles, win, totalBattles, totalWin), charge the battle cost once, and
  leave the service stopped.

Checklist: BAT-04 (every battle mode works), BAT-02, BAT-07 (the release gate
itself is test_release_battle_gates.WiFiComGate).
"""
import copy
import os
import sys
import time
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import battle_flow as bf  # noqa: E402

CONNECT_FRAMES = 3000
BATTLE_FRAMES = 12000
#: Frames (with a short real-time wait each) for the service's thread.
WAIT_FRAMES = 600

#: Known-good codes from wificom-lib's digiroms.txt: (format, code, our pet wins).
PUNCHBAGS = [
    ("DMOG", "V1-FC03-FD02", True), ("DMOG", "V1-FC03-FE01", False),
    ("PENOG", "V1-211F-000F-080F-EABF", True), ("PENOG", "V1-211F-000F-09FF-EABF", False),
    ("DMM", "X1-0159-4379-2E49-@4009", True), ("DMM", "X1-0159-4379-2AA9-@41F9", False),
    ("IC", "IC1-C067-4257-0197-0007-@F007", True),
]


def parse_report(text):
    """(s packets, r packets, ends in t) of an adapter report."""
    tokens = text.split()
    sent = [t[2:] for t in tokens if t.startswith("s:")]
    received = [t[2:] for t in tokens if t.startswith("r:")]
    return sent, received, bool(tokens) and tokens[-1] == "t"


@unittest.skipUnless(os.path.isdir(bf.MODULES), "modules folder not present")
class WiFiComFake(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness import Env
        cls.env = Env("240x240")

    def setUp(self):
        import fake_wificom as fw
        from wificom import transport
        import services.wificom_service as ws
        import scenes.connect_views.wificom_view as wv
        self.fw, self.ws = fw, ws
        self.broker = fw.FakeBroker()
        self.site = fw.FakeWiFiComDev(self.broker)
        self.patches = [patch.object(transport, "create_client", self.site.client_factory()),
                        patch.object(ws, "transport_available", lambda: True),
                        patch.object(wv, "time", bf.FakeClock(self.env))] + bf.no_real_serial()
        for p in self.patches:
            p.start()

    def tearDown(self):
        self.ws.wificom_service.stop()
        for p in self.patches:
            p.stop()
        if hasattr(self.env.rg, "pvp_battle_data"):
            delattr(self.env.rg, "pvp_battle_data")

    # ------------------------------------------------------------ the flow
    def fresh(self, seed=5, debug=False):
        bf.fresh(self.env, seed=seed, input_mode=self.env.rg.TOUCH_MODE)
        self.env.gg.configuration.debug_mode = debug
        # The device's credentials, as the wificom.dev webapp hands them out,
        # in the save folder the game reads them from.
        self.fw.write_secrets(self.env.save_root)

    def pump(self, game, until, frames=WAIT_FRAMES):
        """Frames, with a moment for the service's thread between them."""
        from harness import quiet
        for _ in range(frames):
            if until():
                return True
            self.env.frames(game, 1)
            with quiet():
                time.sleep(0.003)
        return until()

    def open_wificom(self, pet):
        """The WiFiCom view open on *pet*, at the protocol grid."""
        bf.set_party(self.env, [pet])
        self.env.rg.scene_connect_initial_view = ("wificom", {"selected_pets": [pet]})
        game = self.env.game("connect")
        self.env.frames(game, 2)
        view = game.scene.current_view
        self.assertEqual(type(view).__name__, "WiFiComView")
        self.assertEqual(view.phase, "protocol_select")
        return game, view

    def go_online(self, game, view, battle_format):
        """Tap the format, mash its charge, wait until the site sees us."""
        from battle.sim import protocol_constants
        from harness import quiet
        env = self.env
        env.tap(game, bf.selector_cell_center(view.protocol_menu, battle_format))
        env.frames(game, 1)
        minigame = protocol_constants.get_constants(battle_format).MINIGAME
        press = bf.CHARGE_PRESS.get(minigame)
        charged = False
        for frame in range(CONNECT_FRAMES):
            if view.phase == "online":
                break
            if view.minigame is not None and view.minigame.phase == "charge":
                charged = True
                if press and frame % bf.PRESS_EVERY == 0:
                    with quiet():
                        game.scene.handle_event((press, None))
            env.frames(game, 1)
        self.assertEqual(view.phase, "online", "never went online")
        if minigame != "None":
            self.assertTrue(charged, f"the {minigame} charge was not played")
        self.assertEqual(view.battle_format, battle_format)
        self.assertTrue(self.pump(game, lambda: self.site.connected()), "never reached the broker")
        self.assertEqual(self.ws.wificom_service.battle_format, battle_format)
        return view.charge

    def device(self, battle_format, module, skip=()):
        """A side of the line: (its Digimon, the exchange DCom would run with it)."""
        from battle.sim.dcom_battle_simulator import pet_to_digimon
        from battle.sim.exchange import PacketExchange
        other = bf.battle_pet(module, skip=skip)
        digimon = pet_to_digimon(other, battle_format, 2)
        return digimon, PacketExchange(battle_format, copy.deepcopy(digimon),
                                       opens=PacketExchange.cable_opens(battle_format))

    def send_and_answer(self, game, view, rom):
        """The app sends *rom*; BATTLE! if it is turn 2. Returns the result message."""
        from scenes.scene_connect import SceneConnect
        site = self.site
        request = site.send_digirom(rom)
        left = lambda: not isinstance(game.scene, SceneConnect) or game.scene.current_view is not view  # noqa: E731
        from wificom.digirom import parse_command
        if parse_command(rom).turn == 2:
            self.assertTrue(self.pump(game, lambda: view.pending is not None or left()),
                            "the turn-2 DigiROM never reached the screen")
            self.assertEqual([m for m in site.results() if m["output"] != "t"], [],
                             "a turn-2 ROM was answered before BATTLE!")
            self.assertTrue(view.battle_button.enabled)
            self.env.tap(game, view.battle_button.rect.center)
        # The game plays the ROM on its own thread, the service publishes.
        # (A bare "t" is the adapter's listen timing out while BATTLE! waits.)
        answers = lambda: [m for m in site.results() if m["output"] != "t"]  # noqa: E731
        self.assertTrue(self.pump(game, answers), "no result was published")
        self.pump(game, left, frames=60)
        results = answers()
        self.assertEqual(len(results), 1, results)
        message = results[0]
        self.assertEqual(message["application_uuid"], request["application_id"])
        self.assertEqual(message["device_uuid"], self.fw.SECRETS["device_uuid"])
        self.assertEqual(message["name"], "wificom")
        for key in ("version", "circuitpython_version", "circuitpython_board_id"):
            self.assertIn(key, message)
        self.assertIn(request["ack_id"], [a["ack_id"] for a in site.acks()])
        return message

    def play_out(self, game):
        from scenes.scene_battle_pvp import SceneBattlePvP
        from scenes.scene_maingame import SceneMainGame
        for _ in range(BATTLE_FRAMES):
            if not isinstance(game.scene, SceneBattlePvP):
                break
            self.env.frames(game, 1)
        self.assertIsInstance(game.scene, SceneMainGame, f"still in the battle after {BATTLE_FRAMES} frames")
        self.assertEqual(bf.battle_errors(self.env), [])

    def check_counts(self, pet, before, record, won):
        from utils.module_utils import get_module
        battles, wins, dp, hunger = before
        self.assertEqual((pet.pvp_battles, pet.pvp_wins), (battles + 1, wins + (1 if won else 0)))
        self.assertEqual((pet.battles, pet.win, pet.totalBattles, pet.totalWin),
                         (record[0] + 1, record[1] + won, record[2] + 1, record[3] + won),
                         "a connection battle counts toward the battle record")
        module = get_module(pet.module)
        cost_type = getattr(module, "battle_cost_type", "DP")
        cost = getattr(module, "battle_cost_amount", 1.0)
        if cost_type == "DP":
            self.assertEqual((pet.dp, pet.hunger), (max(0, dp - cost), hunger))
        elif cost_type == "Hunger":
            self.assertEqual((pet.dp, pet.hunger), (dp, max(0, hunger - cost)))
        else:
            self.assertEqual((pet.dp, pet.hunger), (dp, hunger))

    def fight(self, battle_format, player_module, device_module):
        from battle.battle_encounter_dcom import BattleEncounterDCom
        from battle.sim import protocol_constants
        from battle.sim.exchange import PacketExchange
        from scenes.scene_battle_pvp import SceneBattlePvP
        for name in {player_module, device_module}:
            if bf.installed(name) is None:
                self.skipTest(f"{name} not installed")
        self.fresh()
        pet = bf.ensure_battle_record(bf.battle_pet(player_module))      # BAT-F1
        digimon, device = self.device(battle_format, device_module, skip=(pet.name,))
        rom = device.cable_command()
        game, view = self.open_wificom(pet)
        before = (pet.pvp_battles, pet.pvp_wins, pet.dp, pet.hunger)
        record = (pet.battles, pet.win, pet.totalBattles, pet.totalWin)
        self.go_online(game, view, battle_format)

        message = self.send_and_answer(game, view, rom)
        self.assertIsInstance(game.scene, SceneBattlePvP,
                              f"the exchange never reached the battle: {message['output']}, "
                              f"{bf.battle_errors(self.env)}")
        deadline = time.monotonic() + 5
        while self.ws.wificom_service.is_running and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(self.ws.wificom_service.is_running, "the service outlived the screen")

        # The report, in the adapter's words and the ROM's turn order.
        output = message["output"]
        sent, received, timed_out = parse_report(output)
        count = protocol_constants.get_wire(battle_format).PACKET_COUNT
        self.assertEqual((len(sent), len(received)), (count, count), output)
        turn = 1 if PacketExchange.cable_opens(battle_format) else 2
        self.assertTrue(output.startswith("s:" if turn == 1 else "r:"), output)
        self.assertEqual(timed_out, turn == 2, "turn 2 ends listening (t); turn 1 on the toy's packet")
        for template, packet in zip(rom.split("-")[1:], sent):
            if not any(mark in template for mark in "@^+_"):
                self.assertEqual(packet, template.upper(), "a literal packet went out changed")

        # The battle scene got the exchange on the chosen format.
        data = self.env.rg.pvp_battle_data
        encounter = game.scene.battle_encounter
        self.assertIsInstance(encounter, BattleEncounterDCom)
        self.assertEqual(data["battle_format"], battle_format)
        self.assertEqual(encounter.battle_format, battle_format)
        self.assertTrue(encounter.skip_charge and encounter.is_dcom_mode)
        self.assertEqual(data["is_oem_mode"], player_module in bf.native_modules_of(battle_format))
        self.assertEqual(data["enemy_first"], turn == 1, "whoever opened strikes first")
        self.assertEqual(encounter.battle_player.team1_max_hp[:1], [data["my_team_data"][0]["hp"]])

        self.play_out(game)

        # The device reads the same battle out of the same packets.
        ours = data["original_battle_log"]
        theirs = PacketExchange.from_transcript(
            battle_format, copy.deepcopy(digimon), [bytes.fromhex(p) for p in sent],
            received, simulator=device.simulator).result()
        self.assertIsNotNone(theirs, "the device could not read the exchange")
        self.assertEqual(encounter.victory_status, "Victory" if ours.winner == "device2" else "Defeat")
        self.assertEqual(ours.winner, {"device1": "device2", "device2": "device1"}.get(theirs.winner))
        self.assertEqual(ours.device1_final[0].hp, theirs.device2_final[0].hp)
        self.assertEqual(ours.device2_final[0].hp, theirs.device1_final[0].hp)

        self.check_counts(pet, before, record, encounter.victory_status == "Victory")

    # ------------------------------------------------------------ punchbags
    def test_punchbag_codes_decide_the_battle(self):
        """The community's known-good codes: "you win" makes our pet win and
        "you lose" lose, natively and as a compatibility pet (a VB pet)."""
        from wificom import digirom, executor
        from harness import quiet
        for battle_format, code, we_win in PUNCHBAGS:
            natives = bf.native_modules_of(battle_format)
            if not natives:
                continue
            for module in (natives[0], "VB"):
                if bf.installed(module) is None:
                    continue
                with self.subTest(code=code, module=module):
                    self.fresh(seed=3)
                    pet = bf.battle_pet(module)
                    with quiet():
                        played = executor.play(digirom.parse_command(code), pet, battle_format, 2)
                    self.assertTrue(played.complete, played.result)
                    self.assertTrue(played.result.startswith("s:" + code.split("-")[1]))
                    result = played.battle_result()
                    self.assertIsNotNone(result, played.result)
                    self.assertEqual(result.winner == "device2", we_win, played.result)

    def test_a_turn_1_punchbag_through_the_screen(self):
        """A turn-1 ROM has the adapter open: the pet answers at once, no
        BATTLE! press, and the battle plays."""
        from scenes.scene_battle_pvp import SceneBattlePvP
        natives = bf.native_modules_of("DMM")
        if not natives:
            self.skipTest("no DMM module installed")
        self.fresh()
        pet = bf.ensure_battle_record(bf.battle_pet(natives[0]))
        game, view = self.open_wificom(pet)
        self.go_online(game, view, "DMM")
        message = self.send_and_answer(game, view, "X1-0159-4379-2E49-@4009")
        sent, received, timed_out = parse_report(message["output"])
        self.assertTrue(message["output"].startswith("s:0159 r:"), message["output"])
        self.assertEqual(sent, ["0159", "4379", "2E49", "8009"], "@4009 is the adapter's check digit")
        self.assertEqual((len(received), timed_out), (4, False))
        self.assertIsInstance(game.scene, SceneBattlePvP)
        self.assertEqual(self.env.rg.pvp_battle_data["simulation_data"]["victory_status"], "Victory")
        self.play_out(game)

    # ------------------------------------------------------------ the screen
    def test_the_menu_path_reaches_the_grid(self):
        """Debug mode: Connect -> Local battle -> WiFiCom -> the risk notice
        -> YES -> one pet -> CONFIRM -> (no temporary form) -> the grid,
        focused on the pet's own line."""
        if bf.installed("DMC") is None:
            self.skipTest("DMC not installed")
        self.fresh(debug=True)
        pet = bf.battle_pet("DMC")
        bf.set_party(self.env, [pet])
        # The menu also asks for a route to the internet, which the harness
        # refuses; the credentials and the client library are the real checks.
        online = patch.object(self.ws, "internet_available", lambda *a, **k: True)
        online.start()
        self.addCleanup(online.stop)
        self.env.rg.scene_connect_initial_view = ("main_menu", {"initial_submenu": "local_battle"})
        game = self.env.game("connect")
        menu = game.scene.current_view
        self.assertTrue(self.pump(game, lambda: menu.local_wificom_button.enabled, frames=300),
                        "the WiFiCom button never became available in debug mode")
        self.env.tap(game, menu.local_wificom_button.rect.center)
        self.env.frames(game, 2)
        warning = game.scene.current_view
        self.assertEqual(type(warning).__name__, "WiFiComWarningView")
        self.env.tap(game, warning.yes_button.rect.center)
        self.env.frames(game, 2)
        selection = game.scene.current_view
        self.assertEqual(type(selection).__name__, "PetSelectionView")
        self.assertTrue(selection.is_wificom_mode)
        self.env.tap(game, bf.pet_cell_center(selection.pet_selector, 0))
        self.env.frames(game, 1)
        self.env.tap(game, selection.confirm_button.rect.center)
        self.assertTrue(self.pump(game, lambda: type(game.scene.current_view).__name__ == "WiFiComView",
                                  frames=30), type(game.scene.current_view).__name__)
        view = game.scene.current_view
        self.assertEqual(view.phase, "protocol_select")
        keys = [key for key, _, _ in view.protocol_menu.entries]
        self.assertEqual(keys[view.protocol_menu.cursor], "DMC", "the grid opens on the pet's line")
        from battle.sim import protocol_constants
        offered = {key for key, _, _ in view.protocol_menu.entries
                   if key and view.protocol_menu.enabled[keys.index(key)]}
        self.assertTrue(set(protocol_constants.BATTLE_FORMATS) <= offered)
        self.assertFalse(self.ws.wificom_service.is_running, "connected before the line was chosen")

    def test_backing_out_of_the_charge_returns_to_pet_selection(self):
        if bf.installed("DMC") is None:
            self.skipTest("DMC not installed")
        self.fresh()
        game, view = self.open_wificom(bf.battle_pet("DMC"))
        self.env.tap(game, bf.selector_cell_center(view.protocol_menu, "DM20"))
        self.assertTrue(self.pump(game, lambda: view.minigame is not None, frames=30))
        from harness import quiet
        with quiet():
            game.scene.handle_event(("ESC", None))
        self.env.frames(game, 2)
        after = game.scene.current_view
        self.assertEqual(type(after).__name__, "PetSelectionView")
        self.assertTrue(after.is_wificom_mode)
        self.assertFalse(self.ws.wificom_service.is_running)

    def test_a_scan_is_answered_and_no_battle_starts(self):
        """One packet is a scan: answered with one packet each way, and the
        screen stays online for the battle that may follow."""
        from scenes.scene_connect import SceneConnect
        if bf.installed("DMC") is None:
            self.skipTest("DMC not installed")
        self.fresh()
        game, view = self.open_wificom(bf.battle_pet("DMC"))
        self.go_online(game, view, "DMC")
        self.site.send_digirom("C1-47444C43000000010000000000009388")
        self.assertTrue(self.pump(game, lambda: self.site.results()))
        self.pump(game, lambda: False, frames=10)
        output = self.site.results()[0]["output"]
        self.assertEqual(len(output.split()), 2, output)
        self.assertTrue(output.startswith("s:47444C43000000010000000000009388 r:47444C43"), output)
        self.assertIsInstance(game.scene, SceneConnect)
        self.assertEqual(view.phase, "online")
        self.assertTrue(self.ws.wificom_service.is_running)

    def test_a_rom_of_another_line_is_not_answered(self):
        """A DM20 ROM to a pet set on DMC: no answer (a toy of another line
        would not give one), a note on screen, and nothing played."""
        if bf.installed("DMC") is None:
            self.skipTest("DMC not installed")
        self.fresh()
        game, view = self.open_wificom(bf.battle_pet("DMC"))
        self.go_online(game, view, "DMC")
        self.site.send_digirom("V2-4D4F-494E-081E-00EE-11EE-00CE-000E-000E-000E-@0^F^FE")
        self.assertTrue(self.site.wait_for_results(1))
        self.assertTrue(self.pump(game, lambda: (view._message or "").startswith("Not answered")))
        self.assertEqual(self.site.results()[0]["output"], "t")
        self.assertIsNone(view.pending)
        self.assertEqual(self.ws.wificom_service.exchanges, 0)

    def test_the_selected_line_is_kept_where_the_wire_is_shared(self):
        """PENZ rides the DMX wire: a DMX device's ROM to a pet set on PENZ is
        fought as PENZ (the selection), not re-read as DMX."""
        natives = bf.native_modules_of("DMX")
        if not natives or bf.installed("VB") is None:
            self.skipTest("no DMX module installed")
        from wificom import digirom, executor
        from harness import quiet
        self.fresh()
        _, device = self.device("DMX", natives[0])
        with quiet():
            played = executor.play(digirom.parse_command(device.cable_command()),
                                   bf.battle_pet("VB"), "PENZ", 2)
        self.assertTrue(played.complete, played.result)
        self.assertEqual(played.exchange.battle_format, "PENZ")
        self.assertEqual(played.exchange.simulator.battle_format, "PENZ")


def _wificom_test(battle_format, compatibility):
    def test(self):
        natives = bf.native_modules_of(battle_format)
        if not natives:
            self.skipTest(f"no module native to {battle_format} installed")
        self.fight(battle_format, "VB" if compatibility else natives[0], natives[0])
    who = "a VB pet (compatibility)" if compatibility else "a native pet"
    test.__doc__ = f"{battle_format}: {who} answers a device of the line through wificom.dev."
    return test


def _formats():
    try:
        sys.path.insert(0, os.path.join(bf.REPO_ROOT, "src"))
        from battle.sim import protocol_constants
        return protocol_constants.BATTLE_FORMATS
    except Exception:
        return ()


for _format in _formats():
    setattr(WiFiComFake, f"test_{_format}_native", _wificom_test(_format, False))
    setattr(WiFiComFake, f"test_{_format}_compatibility", _wificom_test(_format, True))


if __name__ == "__main__":
    unittest.main()
