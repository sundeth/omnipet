# -*- coding: utf-8 -*-
"""The DCom wait keeps what it has to say, and START ends with the wait
(2026-10-22 documentation pass, finding 20).

The countdown line ("Waiting for device... (Ns)") replaced the status every
frame, so START's message, the turn-swap advice ("Start battle on the
device, then connect it.") and the adapter warning vanished at once; and
after a timeout the START button stayed up and would send on a closed port.
Now the countdown is added to the message, and START goes when the wait
ends. Played against battle_flow's FakeAdapter with no device behind it.
"""
import os
import sys
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import battle_flow as bf  # noqa: E402

FORMAT_LIMIT_FRAMES = 3000


@unittest.skipUnless(os.path.isfile(os.path.join(bf.MODULES, "DMC", "module.json")), "modules folder not present")
class DComWaitStatus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness import Env
        cls.env = Env("240x240")

    def tearDown(self):
        bf.FakeAdapter.device = None

    def wait_on(self, battle_format, module):
        """The DCom view waiting for a device that never answers."""
        from harness import quiet
        env = self.env
        bf.fresh(env, seed=5, input_mode=env.rg.TOUCH_MODE)
        pet = bf.ensure_battle_record(bf.battle_pet(module))
        bf.set_party(env, [pet])
        bf.FakeAdapter.device = None
        bf.FakeAdapter.made = []
        env.rg.scene_connect_initial_view = ("dcom", {"selected_pets": [pet]})
        game = env.game("connect")
        env.frames(game, 2)
        view = game.scene.current_view
        self.assertEqual(view.phase, "protocol_select")
        env.tap(game, bf.selector_cell_center(view.protocol_menu, battle_format))
        press = bf.CHARGE_PRESS.get(getattr(view.simulator, "minigame", "None"))
        for frame in range(FORMAT_LIMIT_FRAMES):
            if view.phase == "communicating" and view.communicating:
                break
            if press and view.minigame is not None and frame % bf.PRESS_EVERY == 0:
                with quiet():
                    game.scene.handle_event((press, None))
            env.frames(game, 1)
        self.assertTrue(view.communicating, f"never started waiting: {view.phase}")
        return game, view

    def run_wait(self, battle_format, module, notice):
        import scenes.connect_views.dcom_view as dcom_view
        patches = [patch.object(dcom_view, "DComController", bf.FakeAdapter),
                   patch.object(dcom_view, "time", bf.FakeClock(self.env))] + bf.no_real_serial()
        for p in patches:
            p.start()
        try:
            game, view = self.wait_on(battle_format, module)
            self.assertTrue(view.start_button.visible)
            game.scene.handle_event(("START", None))
            self.env.frames(game, 5)
            text = view.status_label.text
            self.assertTrue(text.startswith(notice), f"START's message was replaced: {text!r}")
            self.assertTrue(text.rstrip().endswith("s)"), f"the countdown is added: {text!r}")
            for _ in range(int(dcom_view.COMM_TIMEOUT_SECONDS * 31) + 60):
                if not view.communicating:
                    break
                self.env.frames(game, 1)
            self.assertFalse(view.communicating, "the wait never ended")
            self.env.frames(game, 1)
            self.assertFalse(view.start_button.visible, "START outlived the wait")
            sent = len(bf.FakeAdapter.made[-1].commands)
            view._on_start()
            game.scene.handle_event(("START", None))
            self.assertEqual(len(bf.FakeAdapter.made[-1].commands), sent, "START sent after the wait")
        finally:
            for p in patches:
                p.stop()

    def test_start_on_a_line_the_device_opens_keeps_its_message(self):
        from battle.sim.exchange import PacketExchange
        if PacketExchange.cable_opens("DMC"):
            self.skipTest("DMC's cable opens the exchange")
        self.run_wait("DMC", "DMC", "Start battle on the device.")

    def test_start_on_a_line_omnipet_opens_says_so(self):
        from battle.sim.exchange import PacketExchange
        if not bf.installed("PENC"):
            self.skipTest("PENC not installed")
        self.assertTrue(PacketExchange.cable_opens("PENC"))
        self.run_wait("PENC", "PENC", "Opening the battle")


if __name__ == "__main__":
    unittest.main()
