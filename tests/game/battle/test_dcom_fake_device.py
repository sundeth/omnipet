# -*- coding: utf-8 -*-
"""A DCom battle on every battle format, against a fake adapter and device.

Checklist BAT-04 (every battle mode works: DCom once per protocol family),
BAT-02 (Omnipet can start a battle and answer one, here without hardware)
and BAT-06 (TWIN held back for 1.0). The battle contract in CLAUDE.md says a
DCom battle is fought on the SELECTED physical protocol.

No serial port is opened: DComView's ``DComController`` is replaced by
battle_flow.FakeAdapter, which takes the DigiROM command the view sends,
resolves its ``@``/``^`` operators the way stock firmware does and replies
with the ``r:``/``s:`` report line dmcomm prints. The device behind it is
Omnipet's own responder (PacketExchange, as WiFiCom and a second Omnipet
answer) fed a Digimon of the format's native module, so its packets have the
line's real layout, checksums and EOLs. ``serial.Serial`` is patched to
refuse, and the view's ``time`` reads the harness's fake clock.

Each format is played the way a player does it: the DCom view opens on the
pet, the format's box is tapped in the protocol grid, the charge minigame is
mashed while it runs, the exchange completes, the PvP battle scene plays the
result and the game returns to the main scene. Each run must:

* send one command, as the turn and signal letter the format's cable role uses;
* hand the battle scene the exchange on the chosen format (skip_charge, the
  wire's HP), with no exception and no error logged;
* end on the verdict the device reads from the same packets (the device's
  own PacketExchange result is the mirror of ours);
* count the connection battle (pvp_battles, pvp_wins on a win) and, as any
  battle (owner, 2026-10-21), the battle record (battles, win, totalBattles,
  totalWin), and charge the pet's module battle cost once.

Every format is fought by a native pet (OEM) and by a VB pet (a module with
no protocol: compatibility). Known defects are expectedFailure
(tests/findings/battle.md): BAT-F2 (a press after the charge cancels the
battle) and BAT-F8 (TWIN is still offered).
"""
import os
import sys
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import battle_flow as bf  # noqa: E402

#: Charge plus exchange, then the battle scene; both bounded.
CONNECT_FRAMES = 3000
BATTLE_FRAMES = 12000


@unittest.skipUnless(os.path.isdir(bf.MODULES), "modules folder not present")
class DComFakeDevice(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness import Env
        cls.env = Env("240x240")

    def tearDown(self):
        # The battle scene leaves its hand-off behind; nothing else may see it.
        if hasattr(self.env.rg, "pvp_battle_data"):
            delattr(self.env.rg, "pvp_battle_data")
        bf.FakeAdapter.device = None

    # ------------------------------------------------------------ the flow
    def open_dcom(self, battle_format, player_module, device_module, seed=5):
        """The DCom view open on a pet of *player_module*, a device of
        *device_module* on the far side. Returns (game, pet, device)."""
        from battle.sim.dcom_battle_simulator import pet_to_digimon
        for name in {player_module, device_module} - {None}:
            if bf.installed(name) is None:
                self.skipTest(f"{name} not installed")
        env = self.env
        bf.fresh(env, seed=seed, input_mode=env.rg.TOUCH_MODE)
        pet = bf.ensure_battle_record(bf.battle_pet(player_module))      # BAT-F1
        device = None
        if device_module:
            other = bf.battle_pet(device_module, skip=(pet.name,))
            device = bf.FakeDevice(battle_format, pet_to_digimon(other, battle_format, 2))
        bf.set_party(env, [pet])
        bf.FakeAdapter.device = device
        bf.FakeAdapter.made = []
        env.rg.scene_connect_initial_view = ("dcom", {"selected_pets": [pet]})
        game = env.game("connect")
        env.frames(game, 2)
        view = game.scene.current_view
        self.assertEqual(type(view).__name__, "DComView")
        self.assertEqual(view.phase, "protocol_select", "no adapter found or connected")
        return game, pet, device

    def patched(self):
        import scenes.connect_views.dcom_view as dcom_view
        return [patch.object(dcom_view, "DComController", bf.FakeAdapter),
                patch.object(dcom_view, "time", bf.FakeClock(self.env))] + bf.no_real_serial()

    def charge_and_connect(self, game, battle_format, press_after_charge=False):
        """Tap the format, mash its charge, wait for the exchange. Returns
        the phases the DCom view went through."""
        from scenes.scene_connect import SceneConnect
        from harness import quiet
        env = self.env
        view = game.scene.current_view
        env.tap(game, bf.selector_cell_center(view.protocol_menu, battle_format))
        env.frames(game, 1)
        phases = [view.phase]
        press = bf.CHARGE_PRESS.get(getattr(view.simulator, "minigame", "None"))
        charged = False
        for frame in range(CONNECT_FRAMES):
            if not isinstance(game.scene, SceneConnect) or game.scene.current_view is not view:
                break
            charging = view.minigame is not None and view.minigame.phase == "charge"
            charged = charged or charging
            mashing = charging or (press_after_charge and charged and view.phase == "minigame")
            if press and mashing and frame % bf.PRESS_EVERY == 0:
                with quiet():
                    game.scene.handle_event((press, None))
            env.frames(game, 1)
            if view.phase != phases[-1]:
                phases.append(view.phase)
        return phases

    def fight(self, battle_format, player_module, device_module):
        from battle.battle_encounter_dcom import BattleEncounterDCom
        from battle.sim import protocol_constants
        from battle.sim.exchange import PacketExchange
        from scenes.scene_battle_pvp import SceneBattlePvP
        from scenes.scene_maingame import SceneMainGame
        from utils.module_utils import get_module
        patches = self.patched()
        for p in patches:
            p.start()
        try:
            game, pet, device = self.open_dcom(battle_format, player_module, device_module)
            before = (pet.pvp_battles, pet.pvp_wins, pet.dp, pet.hunger)
            record = (pet.battles, pet.win, pet.totalBattles, pet.totalWin)
            phases = self.charge_and_connect(game, battle_format)
            minigame = protocol_constants.get_constants(battle_format).MINIGAME
            if minigame != "None":
                self.assertIn("minigame", phases, f"the {minigame} charge was not played")
            self.assertIsInstance(game.scene, SceneBattlePvP,
                                  f"the exchange never reached the battle: {phases}, "
                                  f"{bf.battle_errors(self.env)}")

            adapter = bf.FakeAdapter.made[-1]
            self.assertEqual(len(adapter.commands), 1, adapter.commands)
            wire = protocol_constants.get_wire(battle_format)
            turn = 1 if PacketExchange.cable_opens(battle_format) else 2
            op = getattr(wire, "DCOM_OP", protocol_constants.DCOM_OP)
            self.assertTrue(adapter.commands[0].startswith(f"{op}{turn}-"), adapter.commands[0])
            self.assertFalse(adapter.connected, "the adapter was left connected")

            data = self.env.rg.pvp_battle_data
            encounter = game.scene.battle_encounter
            self.assertIsInstance(encounter, BattleEncounterDCom)
            self.assertEqual(data["battle_format"], battle_format)
            self.assertEqual(encounter.battle_format, battle_format)
            self.assertTrue(encounter.skip_charge and encounter.is_dcom_mode)
            self.assertEqual(data["is_oem_mode"], player_module in bf.native_modules_of(battle_format))
            self.assertEqual(encounter.battle_player.team1_max_hp[:1], [data["my_team_data"][0]["hp"]])

            for _ in range(BATTLE_FRAMES):
                if not isinstance(game.scene, SceneBattlePvP):
                    break
                self.env.frames(game, 1)
            self.assertIsInstance(game.scene, SceneMainGame, f"still in the battle after {BATTLE_FRAMES} frames")
            self.assertEqual(bf.battle_errors(self.env), [])

            # Both ends read the same battle out of the same packets.
            ours = data["original_battle_log"]
            theirs = device.exchanges[-1]["device"].result()
            self.assertIsNotNone(theirs, "the device could not read the exchange")
            self.assertEqual(encounter.victory_status, "Victory" if ours.winner == "device2" else "Defeat")
            self.assertEqual(ours.winner, {"device1": "device2", "device2": "device1"}.get(theirs.winner))
            self.assertEqual(ours.device1_final[0].hp, theirs.device2_final[0].hp)
            self.assertEqual(ours.device2_final[0].hp, theirs.device1_final[0].hp)

            battles, wins, dp, hunger = before
            won = encounter.victory_status == "Victory"
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
        finally:
            for p in patches:
                p.stop()

    # ------------------------------------------------------------ TWIN (BAT-06)
    def test_choosing_twin_records_and_never_battles(self):
        """TWIN is a capture line: choosing it in DCom never builds a battle,
        however long the adapter is listened to."""
        from battle.sim import protocol_constants
        from scenes.scene_battle_pvp import SceneBattlePvP
        if "TWIN" in protocol_constants.BATTLE_FORMATS:
            self.skipTest("TWIN has a battle format now")
        patches = self.patched()
        for p in patches:
            p.start()
        try:
            game, pet, _ = self.open_dcom("TWIN", "DMC", None)
            menu = game.scene.current_view.protocol_menu
            if "TWIN" not in [key for key, _, _ in menu.entries]:
                return      # not offered at all: held back, as BAT-06 wants
            self.charge_and_connect(game, "TWIN")
            for _ in range(2500):           # past the 60 s window on the fake clock
                self.assertNotIsInstance(game.scene, SceneBattlePvP)
                self.env.frames(game, 1)
            self.assertEqual(pet.pvp_battles, 0)
        finally:
            for p in patches:
                p.stop()

    # Fixed 2026-10-13; kept as a regression test.
    def test_twin_is_not_offered_in_the_dcom_grid(self):
        """For 1.0 an unfinished line is not selectable in DCom either."""
        patches = self.patched()
        for p in patches:
            p.start()
        try:
            game, _, _ = self.open_dcom("TWIN", "DMC", None)
            menu = game.scene.current_view.protocol_menu
            keys = [key for key, _, _ in menu.entries]
            if "TWIN" in keys:
                self.assertFalse(menu.enabled[keys.index("TWIN")], "TWIN can be chosen")
        finally:
            for p in patches:
                p.stop()

    # ------------------------------------------------------------ known defects
    # Fixed 2026-10-13 (UIManager: a hidden component never takes a press); kept as a regression test.
    def test_a_press_after_the_charge_does_not_cancel_the_battle(self):
        """Mashing A a moment past the end of a Dummy Bar charge (the view's
        half-second settle) must not land on the hidden CANCEL button: the
        exchange still runs and the battle still starts."""
        from scenes.scene_battle_pvp import SceneBattlePvP
        natives = bf.native_modules_of("DM20")
        if not natives:
            self.skipTest("no DM20 module installed")
        patches = self.patched()
        for p in patches:
            p.start()
        try:
            game, _, _ = self.open_dcom("DM20", natives[0], natives[0])
            phases = self.charge_and_connect(game, "DM20", press_after_charge=True)
            self.assertIsInstance(game.scene, SceneBattlePvP,
                                  f"the battle was abandoned: {phases}, view now "
                                  f"{getattr(game.scene, 'current_view_name', None)}")
        finally:
            for p in patches:
                p.stop()


def _dcom_test(battle_format, compatibility):
    def test(self):
        natives = bf.native_modules_of(battle_format)
        if not natives:
            self.skipTest(f"no module native to {battle_format} installed")
        self.fight(battle_format, "VB" if compatibility else natives[0], natives[0])
    who = "a VB pet (compatibility)" if compatibility else "a native pet"
    test.__doc__ = f"{battle_format}: {who} fights a device of the line over the fake adapter."
    return test


def _formats():
    try:
        sys.path.insert(0, os.path.join(bf.REPO_ROOT, "src"))
        from battle.sim import protocol_constants
        return protocol_constants.BATTLE_FORMATS
    except Exception:
        return ()


for _format in _formats():
    setattr(DComFakeDevice, f"test_{_format}_native", _dcom_test(_format, False))
    setattr(DComFakeDevice, f"test_{_format}_compatibility", _dcom_test(_format, True))


if __name__ == "__main__":
    unittest.main()
