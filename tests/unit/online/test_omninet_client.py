"""The Omninet client (services/omninet_service.py) against the fake server.

Protects: device linking by pairing code, register/login with the emailed
code, auto-login from the saved device key and its revocation, logout,
account purchases and their listing (ONL-01/02, ONL-04), coin rewards and
the Android reward outbox: delivered once, kept while logged out or offline,
dropped in Free Mode (AND-08). Every public call is driven through every
fault the fake can produce (HTTP 500/502, malformed and HTML bodies, an
empty body, a reset connection, a timeout, a dead port) and must answer
"failed" instead of raising (ARN-08 / ONL failure paths).

No game boot: saves are redirected to a temp folder (fake_omninet.isolate_saves)
and the service's credential file to the same place.
"""
import json
import os
import sys
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "support"))

from paths import temp_dir, use_src  # noqa: E402

use_src()

from fake_omninet import (EMAIL_CODE, FakeOmninet, isolate_client, isolate_saves,  # noqa: E402
                          login_service, reset_service, wait_for)

FAULTS = ("500", "502", "malformed", "html", "empty", "reset", "slow")


class OmninetClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.save_root = temp_dir("online_client_")
        cls.fake = FakeOmninet().start()
        cls._saves = isolate_saves(cls.save_root)
        cls.gg = cls._saves.__enter__()
        cls._client = isolate_client(cls.save_root, cls.fake, timeout=0.5)
        cls.svc = cls._client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls._client.__exit__(None, None, None)
        cls._saves.__exit__(None, None, None)
        cls.fake.stop()

    def setUp(self):
        self.fake.clear_faults()
        reset_service(self.svc)
        self.gg.game_mode = self.gg.GAME_MODE_FREE
        self.gg.player_id = None
        self.gg.coins = 0

    def _account(self, coins=100, **kw):
        return self.fake.add_account(f"Player{len(self.fake.accounts) + 1}", coins=coins, **kw)

    # ------------------------------------------------------------ linking
    def test_pairing_code_links_the_device_and_saves_the_key(self):
        acc = self._account(coins=77)
        self.assertTrue(self.svc.check_availability())
        ok, _msg, info = self.svc.validate_pairing_code(self.fake.pairing_code(acc).lower())
        self.assertTrue(ok)
        self.assertEqual(info["nickname"], acc["nickname"])
        self.assertTrue(self.svc.is_logged_in())
        self.assertEqual(self.svc.get_player_id(), acc["id"])
        self.assertEqual(self.svc.get_user_info()["coins"], 77)
        with open(self.svc._credentials_path) as f:
            saved = json.load(f)
        self.assertEqual(saved["player_id"], acc["id"])
        self.assertIn(saved["device_key"], self.fake.keys_of(acc))
        self.assertTrue(self.svc._credentials_path.startswith(self.save_root))

    def test_a_pairing_code_works_once_and_a_wrong_one_says_so(self):
        acc = self._account()
        code = self.fake.pairing_code(acc)
        self.assertTrue(self.svc.validate_pairing_code(code)[0])
        reset_service(self.svc)
        ok, msg, info = self.svc.validate_pairing_code(code)
        self.assertFalse(ok)
        self.assertIsNone(info)
        self.assertEqual(msg, "Invalid or expired pairing code")
        self.assertFalse(self.svc.is_logged_in())

    def test_a_saved_key_logs_in_again_after_a_restart(self):
        acc = self._account()
        login_service(self.svc, self.fake, acc)
        key = self.svc.get_device_key()
        # a restart: memory forgotten, the file stays
        self.svc._device_key = self.svc._player_id = self.svc._user_info = None
        self.svc._load_credentials()
        self.assertTrue(self.svc.has_saved_credentials())
        self.assertFalse(self.svc.is_logged_in())
        ok, _msg, info = self.svc.validate_device()
        self.assertTrue(ok)
        self.assertEqual(self.svc.get_device_key(), key)
        self.assertEqual(info["id"], acc["id"])

    def test_a_revoked_key_is_forgotten(self):
        acc = self._account()
        login_service(self.svc, self.fake, acc)
        for dev in self.fake.devices.values():
            dev["active"] = False
        ok, msg, _ = self.svc.validate_device()
        self.assertFalse(ok)
        self.assertEqual(msg, "Invalid or expired device key")
        self.assertFalse(self.svc.has_saved_credentials())
        self.assertFalse(os.path.exists(self.svc._credentials_path))

    def test_an_unreachable_server_keeps_the_saved_key(self):
        acc = self._account()
        login_service(self.svc, self.fake, acc)
        self.fake.fault("/api/v1/auth/validate-device", "reset")
        ok, msg, _ = self.svc.validate_device()
        self.assertFalse(ok)
        self.assertEqual(msg, "Cannot connect to server")
        self.assertTrue(self.svc.has_saved_credentials(), "an outage must not log the player out")

    # BUG online-server-error-logs-out: validate_device() treats every
    # non-200 answer as a rejected key and deletes the saved credentials, so
    # one HTTP 500 during auto-login (a server restart, a database hiccup)
    # logs the player out and sends them through the emailed-code login.
    # Fixed 2026-10-13; kept as a regression test.
    def test_a_server_error_during_auto_login_keeps_the_saved_key(self):
        acc = self._account()
        login_service(self.svc, self.fake, acc)
        self.fake.fault("/api/v1/auth/validate-device", "500", times=1)
        self.assertFalse(self.svc.validate_device()[0])
        self.assertTrue(self.svc.has_saved_credentials(), "HTTP 500 deleted the device key")

    def test_register_then_verify_creates_an_active_account(self):
        ok, _ = self.svc.register("Newbie", "newbie@example.com", "hunter22")
        self.assertTrue(ok)
        ok, msg = self.svc.verify_registration("newbie@example.com", "000000")
        self.assertFalse(ok)
        self.assertEqual(msg, "Invalid or expired verification code")
        ok, _ = self.svc.verify_registration("newbie@example.com", EMAIL_CODE)
        self.assertTrue(ok)
        self.assertTrue(self.svc.is_logged_in())
        self.assertEqual(self.svc.get_username(), "Newbie")
        ok, msg = self.svc.register("Newbie2", "newbie@example.com", "hunter22")
        self.assertEqual((ok, msg), (False, "Email is already registered"))

    def test_login_with_code_and_clear_devices_revokes_the_others(self):
        acc = self._account()
        other = self.fake.add_device(acc)          # a second Omnipet already logged in
        self.assertEqual(self.svc.login_request(acc["email"], "wrong"), (False, "Invalid email or password"))
        self.assertTrue(self.svc.login_request(acc["email"], acc["password"])[0])
        self.assertTrue(self.svc.verify_login(acc["email"], EMAIL_CODE, clear_devices=True)[0])
        self.assertTrue(self.svc.is_logged_in())
        self.assertEqual(self.fake.keys_of(acc), [self.svc.get_device_key()])
        self.assertNotIn(other, self.fake.keys_of(acc))

    def test_an_inactive_account_is_refused_with_the_servers_reason(self):
        acc = self._account(active=False)
        ok, msg = self.svc.login_request(acc["email"], acc["password"])
        self.assertFalse(ok)
        self.assertIn("not active", msg)
        self.assertTrue(self.svc.resend_code(acc["email"])[0])
        self.assertTrue(self.svc.verify_registration(acc["email"], EMAIL_CODE)[0])
        self.assertTrue(self.fake.account(acc)["is_active"])

    def test_logout_forgets_the_key_locally(self):
        acc = self._account()
        login_service(self.svc, self.fake, acc)
        self.assertTrue(self.svc.logout())
        self.assertFalse(self.svc.is_logged_in())
        self.assertFalse(self.svc.has_saved_credentials())
        self.assertFalse(os.path.exists(self.svc._credentials_path))

    # BUG online-logout-key-stays-valid: OmninetService.logout() posted to
    # /api/v1/auth/logout, a route the server does not have (404), so the
    # device key was never revoked. Fixed 2026-10-17: logout deletes its own
    # device (DELETE /users/me/devices/{id}); kept as a regression test.
    def test_logout_revokes_the_key_on_the_server(self):
        acc = self._account()
        login_service(self.svc, self.fake, acc)
        key = self.svc.get_device_key()
        self.svc.logout()
        self.assertNotIn(key, self.fake.keys_of(acc), "the logged-out key still opens the account")

    # ------------------------------------------------------------ shop API
    def test_purchases_belong_to_the_account(self):
        acc = self._account(coins=100)
        item = self.fake.add_item("Meat Pack", price=30)
        login_service(self.svc, self.fake, acc)
        ok, items = self.svc.get_shop_items()
        self.assertTrue(ok)
        self.assertIn(item["id"], [i["id"] for i in items])
        self.assertTrue(self.svc.purchase_item("item", item["id"])[0])
        self.assertEqual(self.fake.account(acc)["coins"], 70)
        # a second device on the same account sees the purchase
        reset_service(self.svc)
        login_service(self.svc, self.fake, acc)
        ok, data = self.svc.get_user_purchases()
        self.assertTrue(ok)
        self.assertEqual([p["item_id"] for p in data["purchases"]], [item["id"]])

    def test_the_first_module_is_free_and_later_ones_cost_the_fixed_price(self):
        from fake_omninet import MODULE_FIXED_PRICE
        acc = self._account(coins=100)
        a = self.fake.add_module("ModA", b"zip-a")
        b = self.fake.add_module("ModB", b"zip-b")
        login_service(self.svc, self.fake, acc)
        ok, mods = self.svc.get_shop_modules()
        self.assertTrue(ok)
        self.assertEqual({m["price"] for m in mods}, {0})
        self.assertTrue(self.svc.purchase_item("module", a["id"])[0])
        _, mods = self.svc.get_shop_modules()
        self.assertEqual({m["price"] for m in mods}, {MODULE_FIXED_PRICE})
        self.assertTrue(self.svc.purchase_item("module", b["id"])[0])
        self.assertEqual(self.fake.account(acc)["coins"], 100 - MODULE_FIXED_PRICE)
        ok, data = self.svc.download_module_zip(a["id"])
        self.assertEqual((ok, data), (True, b"zip-a"))

    # BUG online-refused-purchase-reported-as-success: the server answers a
    # refused purchase (not enough coins, already owned) with HTTP 200 and
    # {"success": false}; OmninetService.purchase_item only checks the HTTP
    # status, so the shop views deduct the price and grant the item locally.
    # Fixed 2026-10-13; kept as a regression test.
    def test_a_refused_purchase_is_reported_as_a_failure(self):
        acc = self._account(coins=5)
        item = self.fake.add_item("Expensive", price=50)
        login_service(self.svc, self.fake, acc)
        ok, msg = self.svc.purchase_item("item", item["id"])
        self.assertFalse(ok, f"server refused ({msg!r}) but the client says it worked")

    # ------------------------------------------------------------ faults
    def _calls(self, acc_key_holder):
        """Every public call that talks to the server, as (name, thunk, ok)."""
        s = self.svc
        return [
            ("check_availability", lambda: s.check_availability(), lambda r: r is True),
            ("validate_pairing_code", lambda: s.validate_pairing_code("ZZ99"), lambda r: r[0]),
            ("validate_device", lambda: s.validate_device(), lambda r: r[0]),
            ("register", lambda: s.register("Faulty", "faulty@example.com", "hunter22"), lambda r: r[0]),
            ("login_request", lambda: s.login_request("faulty@example.com", "x"), lambda r: r[0]),
            ("verify_login", lambda: s.verify_login("faulty@example.com", "123456"), lambda r: r[0]),
            ("resend_code", lambda: s.resend_code("faulty@example.com"), lambda r: r[0]),
            ("get_shop_modules", lambda: s.get_shop_modules(), lambda r: r[0]),
            ("get_shop_items", lambda: s.get_shop_items(), lambda r: r[0]),
            ("get_shop_cosmetics", lambda: s.get_shop_cosmetics(), lambda r: r[0]),
            ("get_shop_gameplay", lambda: s.get_shop_gameplay(), lambda r: r[0]),
            ("get_shop_specials", lambda: s.get_shop_specials(), lambda r: r[0]),
            ("purchase_item", lambda: s.purchase_item("item", "00000000-0000-0000-0000-000000000000"), lambda r: r[0]),
            ("get_user_purchases", lambda: s.get_user_purchases(), lambda r: r[0]),
            ("download_module", lambda: s.download_module("x"), lambda r: r[0]),
            ("download_cosmetic", lambda: s.download_cosmetic("x"), lambda r: r[0]),
            ("download_item", lambda: s.download_item("x"), lambda r: r[0]),
            ("download_gameplay", lambda: s.download_gameplay("x"), lambda r: r[0]),
            ("get_shop_sprite", lambda: s.get_shop_sprite("item", "x"), lambda r: r is not None),
            ("get_current_season", lambda: s.get_current_season(), lambda r: r[0]),
            ("get_arena_modules", lambda: s.get_arena_modules(), lambda r: r[0]),
            ("get_user_teams", lambda: s.get_user_teams(include_past=True), lambda r: r[0]),
            ("get_current_team", lambda: s.get_current_team(), lambda r: r[0]),
            ("create_team", lambda: s.create_team([]), lambda r: r[0]),
            ("claim_team_rewards", lambda: s.claim_team_rewards(), lambda r: r[0]),
            ("get_team_battles", lambda: s.get_team_battles("x"), lambda r: r[0]),
            ("get_battle", lambda: s.get_battle("x"), lambda r: r[0]),
            ("find_battle", lambda: s.find_battle("x"), lambda r: r[0]),
        ]

    def test_every_call_answers_failed_on_every_fault(self):
        """No call raises, none reports success, and an outage never logs out."""
        acc = self._account()
        login_service(self.svc, self.fake, acc)
        key = self.svc.get_device_key()
        # Arena calls wait longer (the server fights before it answers);
        # here every call gets the test's short timeout.
        self.svc.ARENA_TIMEOUT = 0
        self.addCleanup(lambda: self.svc.__dict__.pop("ARENA_TIMEOUT", None))
        for mode in FAULTS:
            self.fake.clear_faults()
            self.fake.fault("/", mode, delay=1.5)
            for name, call, succeeded in self._calls(acc):
                with self.subTest(fault=mode, call=name):
                    self.svc._device_key = key
                    try:
                        result = call()
                    except Exception as exc:  # noqa: BLE001
                        self.fail(f"{name} raised {exc!r} on {mode}")
                    if mode == "empty":
                        continue            # an empty 200 only has to be survived
                    if name == "check_availability" and mode in ("slow", "malformed", "html"):
                        continue            # /health answers 200 (or within its own 2 s timeout)
                    self.assertFalse(succeeded(result), f"{name} reported success on {mode}")
        self.fake.clear_faults()
        self.svc._device_key = key
        self.assertTrue(self.svc.validate_device()[0], "the key survived the outages")

    def test_a_dead_server_is_unavailable_and_nothing_raises(self):
        dead = FakeOmninet.dead_url()
        with isolate_client(self.save_root, dead, timeout=0.5) as svc:
            svc._device_key = "dk_offline"
            self.assertFalse(svc.check_availability())
            # Windows retries a refused local connect for ~2 s: either message
            offline = ("Cannot connect to server", "Connection timeout")
            ok, msg, _ = svc.validate_pairing_code("ABCD")
            self.assertFalse(ok)
            self.assertIn(msg, offline)
            self.assertEqual(svc.get_shop_items(), (False, []))
            ok, msg = svc.download_module_zip("x")
            self.assertFalse(ok)
            self.assertIn(msg, offline + ("Download timeout",))
            ok, msg = svc.get_current_season()
            self.assertFalse(ok)
            self.assertIn(msg, offline)

    # ------------------------------------------------------------ rewards
    def _progress_login(self, acc):
        login_service(self.svc, self.fake, acc)
        self.gg.game_mode = self.gg.GAME_MODE_PROGRESS
        self.gg.player_id = acc["id"]
        self.gg.coins = acc["coins"]

    def test_a_reward_is_credited_once_and_mirrored_into_the_coins(self):
        acc = self._account(coins=10)
        self._progress_login(acc)
        self.svc.claim_reward("unlock", "unlock:DMC:egg:Botamon")
        self.assertTrue(wait_for(lambda: self.gg.coins == 15))
        self.svc.claim_reward("unlock", "unlock:DMC:egg:Botamon")
        self.assertTrue(wait_for(lambda: len(self.fake.calls("/api/v1/rewards/claim")) >= 2))
        self.assertTrue(wait_for(lambda: self.fake.account(acc)["coins"] == 15))
        self.assertEqual(self.gg.coins, 15)

    def test_free_mode_and_logged_out_players_send_no_rewards(self):
        acc = self._account()
        login_service(self.svc, self.fake, acc)
        before = len(self.fake.calls("/api/v1/rewards"))
        self.svc.claim_reward("unlock", "unlock:free")        # Free Mode
        reset_service(self.svc)
        self.gg.game_mode = self.gg.GAME_MODE_PROGRESS
        self.svc.claim_reward("unlock", "unlock:anon")        # logged out
        self.assertFalse(wait_for(lambda: len(self.fake.calls("/api/v1/rewards")) > before, timeout=0.5))


class RewardOutboxTests(unittest.TestCase):
    """AND-08: the Android reward outbox (android_progress.flush_effects)."""

    @classmethod
    def setUpClass(cls):
        cls.save_root = temp_dir("online_outbox_")
        cls.fake = FakeOmninet().start()
        cls._saves = isolate_saves(cls.save_root)
        cls.gg = cls._saves.__enter__()
        cls._client = isolate_client(cls.save_root, cls.fake, timeout=0.5)
        cls.svc = cls._client.__enter__()
        from services import android_progress
        cls.ap = android_progress

    @classmethod
    def tearDownClass(cls):
        cls._client.__exit__(None, None, None)
        cls._saves.__exit__(None, None, None)
        cls.fake.stop()

    def setUp(self):
        self.fake.clear_faults()
        self.fake.reset_log()
        reset_service(self.svc)
        self.acc = self.fake.add_account(f"Droid{len(self.fake.accounts)}", coins=20)
        self.gg.game_mode = self.gg.GAME_MODE_PROGRESS
        self.gg.player_id = self.acc["id"]
        self.gg.coins = 20
        self.ap._outbox_busy = False

    def _meta(self, *entries):
        meta = {"profile": self.gg.get_save_dir(), "outbox": [list(e) for e in entries]}
        self.gg.android_offline = meta
        return meta

    def _flush(self, meta):
        self.ap.flush_effects(meta)
        self.assertTrue(wait_for(lambda: not self.ap._outbox_busy), "the outbox worker never ended")

    def test_logged_in_entries_are_delivered_once_and_acknowledged(self):
        login_service(self.svc, self.fake, self.acc)
        meta = self._meta(("evolution", "evolution:offline:1"), ("new_pet", "new_pet:DMC:Agumon:1"),
                          ("evolution", "evolution:offline:1"))
        self._flush(meta)
        self.assertEqual(meta["outbox"], [])
        self.assertEqual(sorted(self.fake.reward_keys[self.acc["id"]]),
                         ["evolution:offline:1", "new_pet:DMC:Agumon:1"])
        self.assertEqual(self.fake.account(self.acc)["coins"], 25)
        self.assertEqual(self.gg.coins, 25)
        self._flush(meta)                       # nothing left: nothing sent again
        self.assertEqual(len(self.fake.calls("/api/v1/rewards/claim")), 2)

    def test_logged_out_entries_wait_for_the_next_login(self):
        meta = self._meta(("unlock", "unlock:DMC:egg:Punimon"))
        self._flush(meta)
        self.assertEqual(meta["outbox"], [["unlock", "unlock:DMC:egg:Punimon"]])
        self.assertEqual(self.fake.calls("/api/v1/rewards"), [])
        login_service(self.svc, self.fake, self.acc)
        self._flush(meta)
        self.assertEqual(meta["outbox"], [])
        self.assertEqual(self.fake.account(self.acc)["coins"], 25)

    def test_an_offline_flush_keeps_every_entry(self):
        login_service(self.svc, self.fake, self.acc)
        self.fake.fault("/api/v1/rewards", "reset")
        meta = self._meta(("unlock", "unlock:a"), ("new_pet", "new_pet:b"))
        self._flush(meta)
        self.assertEqual(len(meta["outbox"]), 2)
        self.assertEqual(self.fake.account(self.acc)["coins"], 20)

    def test_a_pending_digidex_is_written_once_logged_in_or_not(self):
        from models.game_digidex import load_digidex
        entries = [{"name": "Agumon", "module": "DMC", "version": 1}]
        for logged_in in (False, True):
            with self.subTest(logged_in=logged_in):
                if logged_in:
                    login_service(self.svc, self.fake, self.acc)
                meta = self._meta()
                meta["digidex_pending"] = [dict(e, logged_in=logged_in) for e in entries]
                self._flush(meta)
                self.assertNotIn("digidex_pending", meta)
                path = os.path.join(self.gg.get_save_dir(), "digidex.json")
                self.assertTrue(path.startswith(self.save_root) and os.path.exists(path))
                self.assertEqual([e.get("logged_in") for e in load_digidex()], [logged_in])

    def test_free_mode_drops_the_outbox(self):
        login_service(self.svc, self.fake, self.acc)
        self.gg.game_mode = self.gg.GAME_MODE_FREE
        meta = self._meta(("unlock", "unlock:a"))
        meta["profile"] = self.gg.get_save_dir()
        self._flush(meta)
        self.assertEqual(meta["outbox"], [])
        self.assertEqual(self.fake.calls("/api/v1/rewards"), [])

    # BUG online-outbox-retries-claimed-keys: a key the server already
    # credited (the app died after the claim, before the acknowledgement was
    # saved) is answered 400 "Already claimed"; flush_effects treats every
    # failure alike and keeps the entry, so it is resent on every flush forever.
    # Fixed 2026-10-13; kept as a regression test.
    def test_an_entry_the_server_already_credited_leaves_the_outbox(self):
        login_service(self.svc, self.fake, self.acc)
        self.fake.reward_keys[self.acc["id"]]["unlock:already"] = 5
        meta = self._meta(("unlock", "unlock:already"))
        self._flush(meta)
        self.assertEqual(meta["outbox"], [])


if __name__ == "__main__":
    unittest.main()
