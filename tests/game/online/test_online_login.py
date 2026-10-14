"""Omninet login scene and logout, driven by taps against the fake server.

Protects the Progress Mode authentication paths of scenes/scene_login.py:
the mandatory menu (no Back, "Change to Free Play"), Link Device with the
editor's pairing code, Create Account -> emailed code, Login -> emailed code
(and an account that was never activated), wrong codes, the post-login
handoff (player id, save folder, server coin balance, account sync), and
logout from the connect menu's Config page. A second device logging into the
same account sees its purchases and coins (ONL-02).

Checklist: ONL-02 (account-owned purchases), ONL-04 (Omninet reachable);
BLD-04 is the known bug that the connect menu reads OMNINET_LOCAL_URL, so
those constants are pointed at the fake here (fake_omninet.isolate_client).
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "support"))
sys.path.insert(0, HERE)
MODULES = os.path.join(REPO_ROOT, "modules")

from fake_omninet import EMAIL_CODE, FakeOmninet, isolate_client, reset_service, wait_for  # noqa: E402
from online_ui import (button, labels, progress_mode, scene_name, settle, tap_button,  # noqa: E402
                       type_into, view, connect)


@unittest.skipUnless(os.path.isdir(MODULES), "modules folder not present")
class OnlineLoginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness import Env
        cls.env = Env("240x240", network="local")
        cls.fake = FakeOmninet().start()
        cls._iso = isolate_client(cls.env, cls.fake, timeout=1.0)
        cls.svc = cls._iso.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls._iso.__exit__(None, None, None)
        cls.fake.stop()

    def setUp(self):
        env = self.env
        env.reset(input_mode=env.rg.TOUCH_MODE)
        self.fake.clear_faults()
        self.fake.reset_log()
        reset_service(self.svc)
        progress_mode(env)

    def tearDown(self):
        tracebacks = [l for l in self.env.logs if "Traceback" in l]
        self.assertEqual(tracebacks, [], "a scene or view logged a traceback")

    # ------------------------------------------------------------ helpers
    def _login_scene(self):
        game = self.env.game("login")
        self.env.frames(game, 2)
        self.assertEqual(scene_name(game), "SceneLogin")
        return game

    def _finish_async(self, game, frames=3):
        """Let the scene's worker answer, then run the frames that apply it."""
        scene = game.scene
        self.assertTrue(wait_for(lambda: getattr(scene, "_async_result", None) is not None),
                        "the login worker never answered")
        self.env.frames(game, frames)

    def _fill_login(self, game, acc):
        tap_button(self.env, game, "Login")
        self.assertEqual(game.scene.phase, "login")
        type_into(self.env, game, game.scene.inp_email, acc["email"])
        type_into(self.env, game, game.scene.inp_password, acc["password"])
        tap_button(self.env, game, "Login", frames=0)

    def _assert_logged_in_as(self, game, acc):
        gg = self.env.gg
        self.assertTrue(self.svc.is_logged_in())
        self.assertEqual(gg.player_id, acc["id"])
        self.assertEqual(os.path.basename(gg.get_save_dir()), acc["id"])
        self.assertTrue(gg.get_save_dir().startswith(self.env.save_root))
        self.assertEqual(gg.coins, self.fake.account(acc)["coins"], "coins come from the server")
        self.assertNotEqual(scene_name(game), "SceneLogin", "login did not route onward")
        # the account sync that follows every login
        self.assertTrue(wait_for(lambda: self.fake.calls("/api/v1/shop/purchases")),
                        "the purchases were never synced")

    # ------------------------------------------------------------ tests
    def test_the_mandatory_menu_has_no_back_and_reports_the_connection(self):
        game = self._login_scene()
        self.assertIsNone(button(game, "Back"))
        self.assertIsNotNone(button(game, "Change to Free Play"))
        scene = game.scene
        self.assertTrue(wait_for(lambda: scene._conn_label.text == ""),
                        f"connection label still {scene._conn_label.text!r}")
        self.assertTrue(self.fake.calls("/health"))
        game.scene.handle_event(("B", None))            # B cannot leave it
        self.env.frames(game, 1)
        self.assertEqual(scene_name(game), "SceneLogin")

    def test_link_device_with_a_pairing_code(self):
        acc = self.fake.add_account("Linker", coins=42)
        code = self.fake.pairing_code(acc)
        game = self._login_scene()
        tap_button(self.env, game, "Link Device")
        self.assertEqual(game.scene.phase, "link_device")
        type_into(self.env, game, game.scene.code_entry, code)
        self.assertEqual(game.scene.code_entry.get_text(), code)
        tap_button(self.env, game, "Confirm", frames=0)
        self._finish_async(game)
        self._assert_logged_in_as(game, acc)
        self.assertTrue(os.path.exists(self.svc._credentials_path))

    def test_a_wrong_pairing_code_stays_on_the_form_with_the_reason(self):
        game = self._login_scene()
        tap_button(self.env, game, "Link Device")
        type_into(self.env, game, game.scene.code_entry, "ZZ99")
        tap_button(self.env, game, "Confirm", frames=0)
        self._finish_async(game)
        self.assertEqual(game.scene.phase, "link_device")
        self.assertIn("Invalid or expired pairing code"[:32], labels(game))
        self.assertTrue(button(game, "Confirm").enabled, "buttons stay disabled after a failure")
        self.assertFalse(self.svc.is_logged_in())

    def test_create_account_then_verify_the_emailed_code(self):
        game = self._login_scene()
        tap_button(self.env, game, "Create Account")
        scene = game.scene
        self.assertEqual(scene.phase, "create_account")
        type_into(self.env, game, scene.inp_nickname, "Newbie")
        type_into(self.env, game, scene.inp_email, "newbie@example.com")
        type_into(self.env, game, scene.inp_password, "short")
        tap_button(self.env, game, "Create")
        self.assertIn("Password must be 6+ characters", labels(game))
        self.assertEqual(self.fake.calls("/api/v1/auth/register"), [], "invalid form was sent")
        scene.inp_password.set_text("hunter22")
        tap_button(self.env, game, "Create", frames=0)
        self._finish_async(game)
        self.assertEqual(game.scene.phase, "verify")
        type_into(self.env, game, game.scene.code_entry, EMAIL_CODE)
        tap_button(self.env, game, "Verify", frames=0)
        self._finish_async(game)
        acc = next(a for a in self.fake.accounts.values() if a["email"] == "newbie@example.com")
        self.assertTrue(acc["is_active"])
        self._assert_logged_in_as(game, acc)

    def test_a_wrong_emailed_code_keeps_the_verify_form(self):
        acc = self.fake.add_account("Coder", coins=5)
        game = self._login_scene()
        self._fill_login(game, acc)
        self._finish_async(game)
        self.assertEqual(game.scene.phase, "verify")
        type_into(self.env, game, game.scene.code_entry, "000000")
        tap_button(self.env, game, "Verify", frames=0)
        self._finish_async(game)
        self.assertEqual(game.scene.phase, "verify")
        self.assertIn("Invalid or expired verification code", labels(game))
        self.assertTrue(button(game, "Verify").enabled)
        self.assertFalse(button(game, "Resend").enabled, "Resend unlocks only when the code expires")
        self.assertFalse(self.svc.is_logged_in())

    def test_a_second_device_logs_in_and_sees_the_accounts_purchases(self):
        """ONL-02: purchases and coins follow the account, not the device."""
        dmc = self.env.rg.game_modules["DMC"]
        acc = self.fake.add_account("Owner", coins=64)
        item = self.fake.add_item("Vitamin", price=5)
        bg = self.fake.add_cosmetic("Night Sky", price=5)
        mod = self.fake.add_module("DMC", b"unused", version=dmc.version)
        first = self.fake.add_device(acc)                # the first Omnipet
        for kind, row, price in (("item", item, 5), ("cosmetic", bg, 5), ("module", mod, 0)):
            self.fake.purchases[acc["id"]].append({"id": f"p-{kind}", "item_id": row["id"],
                                                   "purchase_type": kind, "price_paid": price,
                                                   "purchased_at": "2026-10-01T10:00:00.000000Z"})
        game = self._login_scene()
        self._fill_login(game, acc)
        self._finish_async(game)
        type_into(self.env, game, game.scene.code_entry, EMAIL_CODE)
        tap_button(self.env, game, "Verify", frames=0)
        self._finish_async(game)
        self._assert_logged_in_as(game, acc)
        self.assertIn(first, self.fake.keys_of(acc), "a normal login must not revoke the other device")
        p = self.env.gg.purchases
        self.assertTrue(wait_for(lambda: p.owns_module_name("DMC")), "owned module never reconciled")
        self.assertTrue(p.owns_module(mod["id"]))
        self.assertTrue(p.owns_cosmetic(bg["id"]))
        self.assertTrue(p.has_item(item["id"]))
        self.assertEqual(self.env.gg.coins, 64)

    def test_an_account_never_activated_gets_a_new_code_and_activates(self):
        acc = self.fake.add_account("Sleeper", active=False)
        game = self._login_scene()
        self._fill_login(game, acc)
        self._finish_async(game)                         # login refused ...
        self._finish_async(game)                         # ... a fresh code sent
        self.assertEqual(game.scene.phase, "verify")
        self.assertIn("Account not activated. New code sent.", labels(game))
        type_into(self.env, game, game.scene.code_entry, EMAIL_CODE)
        tap_button(self.env, game, "Verify", frames=0)
        self._finish_async(game)
        self._assert_logged_in_as(game, acc)

    def test_change_to_free_play_leaves_without_an_account(self):
        game = self._login_scene()
        tap_button(self.env, game, "Change to Free Play")
        self.assertTrue(self.env.gg.is_free_mode())
        self.assertNotEqual(scene_name(game), "SceneLogin")
        self.assertFalse(self.svc.is_logged_in())

    def test_disconnect_from_config_logs_out_and_opens_login(self):
        acc = self.fake.add_account("Leaver")
        self.assertTrue(self.svc.validate_pairing_code(self.fake.pairing_code(acc))[0])
        progress_mode(self.env, acc["id"])
        game = connect(self.env)
        self.assertEqual(view(game), "main_menu")
        tap_button(self.env, game, "CONFIG")
        settle(self.env, game, lambda: game.scene.current_view._omninet_available is not None)
        self.assertIn("Status: Connected", labels(game))
        self.assertIn(f"Account: {acc['nickname']}", labels(game))
        tap_button(self.env, game, "DISCONNECT")
        self.assertFalse(self.svc.is_logged_in())
        self.assertFalse(self.svc.has_saved_credentials())
        self.env.frames(game, 2)
        self.assertEqual(scene_name(game), "SceneLogin")


if __name__ == "__main__":
    unittest.main()
