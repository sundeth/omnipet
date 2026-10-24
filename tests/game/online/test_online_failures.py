"""Online views when Omninet is down, slow, broken or half-way through a request.

Every online screen must degrade gracefully: no exception, a readable
status, buttons usable again afterwards, no coins lost, nothing granted that
was not paid for, no pet left locked, nothing half-installed. Faults come
from the fake server: a dead port (connection refused), a reset connection,
HTTP 500 / 502, malformed JSON, and answers slower than the client's
timeout, including one that arrives after the server already acted.

Checklist: ARN-08 (arena offline / server errors), ONL-01..04 failure paths,
BLD-04 (the connect menu decides availability from OMNINET_LOCAL_URL, not
the server the game talks to; shown by an expected failure here).
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "support"))
sys.path.insert(0, HERE)
MODULES = os.path.join(REPO_ROOT, "modules")
ARENA_MODULES = ["DMC", "PENC", "IC", "VB"]

from fake_omninet import (FakeOmninet, isolate_client, login_service, module_zip,  # noqa: E402
                          modules_dir, reset_service, wait_for)
from online_ui import (button, connect, freezer_pets, labels, progress_mode,  # noqa: E402
                       detail_settled, idle, scene_name, settle, tap_button, tap_pet, tap_row, type_into,
                       view)

#: Specials is a "Coming Soon" placeholder that asks the server nothing.
SHOP_VIEWS = ("shop_items", "shop_cosmetics", "shop_modules", "shop_gameplay")
LISTINGS = {"shop_items": "/api/v1/shop/items", "shop_cosmetics": "/api/v1/shop/cosmetics",
            "shop_modules": "/api/v1/shop/modules", "shop_gameplay": "/api/v1/shop/gameplay"}
#: Faults a listing / page load must survive (slow = longer than the timeout).
PAGE_FAULTS = ("500", "502", "malformed", "html", "reset", "slow")


@unittest.skipUnless(all(os.path.isdir(os.path.join(MODULES, m)) for m in ARENA_MODULES + ["DMOG"]),
                     "modules not present")
class OnlineFailureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness import Env
        cls.env = Env("240x240", network="local")
        cls.fake = FakeOmninet(arena_modules=ARENA_MODULES).start()
        cls._iso = isolate_client(cls.env, cls.fake, timeout=0.5)
        cls.svc = cls._iso.__enter__()
        cls.module = cls.fake.add_module("DMOG", module_zip(os.path.join(MODULES, "DMOG")),
                                         version="1.0.3")
        cls.item = cls.fake.add_item("Super Meat", price=10)
        cls.cosmetic = cls.fake.add_cosmetic("Starry Night", price=20)
        cls.fake.add_gameplay("Extra Slot", price=30)
        cls.fake.add_special("Halloween Egg", price=40)

    @classmethod
    def tearDownClass(cls):
        cls._iso.__exit__(None, None, None)
        cls.fake.stop()

    def setUp(self):
        env, fake = self.env, self.fake
        env.reset(input_mode=env.rg.TOUCH_MODE)
        fake.clear_faults()
        fake.reset_log()
        reset_service(self.svc)
        from services.shop_image_cache import shop_image_cache
        shop_image_cache.clear()                     # sprites are fetched afresh per test
        for s in fake.seasons:
            s["status"] = "completed"
        fake.teams.clear()
        self.season = fake.start_season("Season X")
        self.acc = fake.add_account(f"Unlucky{len(fake.accounts)}", coins=100)
        login_service(self.svc, fake, self.acc)
        progress_mode(env, self.acc["id"])
        env.gg.coins = 100
        self.log_mark = len(env.logs)

    def tearDown(self):
        errors = [l for l in self.env.error_logs(self.log_mark) if "Traceback" in l]
        self.assertEqual(errors, [], "a view logged a traceback")

    def _server_coins(self):
        return self.fake.account(self.acc)["coins"]

    def _shop_view(self, name):
        game = connect(self.env, name)
        v = game.scene.current_view
        self.assertTrue(settle(self.env, game, lambda: v.state == "list", timeout=10),
                        f"{name} stayed loading")
        return game, v

    # ------------------------------------------------------------ connect menu
    def test_the_connect_menu_with_omninet_down(self):
        env = self.env
        dead = FakeOmninet.dead_url()
        with isolate_client(env, dead, timeout=0.5):
            game = connect(env)
            menu = game.scene.current_view
            self.assertTrue(settle(env, game, lambda: menu._shop_available is not None, timeout=10))
            env.frames(game, 1)
            self.assertFalse(menu.shop_button.enabled)
            self.assertIn("Connect_Offline", menu.shop_button.decorators)
            tap_button(env, game, "CONFIG")
            self.assertTrue(settle(env, game, lambda: menu._omninet_available is not None, timeout=15))
            env.frames(game, 1)
            self.assertIn("Status: Offline", labels(game))
            self.assertFalse(button(game, "CONNECT").enabled)
            tap_button(env, game, "BACK")
            tap_button(env, game, "EXIT")
            env.frames(game, 2)
            self.assertNotEqual(scene_name(game), "SceneConnect")

    def test_a_health_check_error_reads_as_offline(self):
        env = self.env
        self.fake.fault("/health", "500")
        game = connect(env)
        menu = game.scene.current_view
        self.assertTrue(settle(env, game, lambda: menu._shop_available is not None))
        env.frames(game, 1)
        self.assertFalse(menu.shop_button.enabled)

    # BUG BLD-04: the connect menu decides that Omninet (and the shop) is
    # available by probing constants.OMNINET_LOCAL_URL (the dev server) first
    # (main_menu_view.py:643, :923), while OmninetService talks to production.
    # With dev up and production down, the shop opens and every call fails.
    # Fixed 2026-10-13; kept as a regression test.
    def test_shop_availability_follows_the_server_the_game_uses(self):
        env = self.env
        from core import constants
        dead = FakeOmninet.dead_url()
        with isolate_client(env, dead, timeout=0.5):
            constants.OMNINET_LOCAL_URL = self.fake.url + "/"      # the dev server answers
            game = connect(env)
            menu = game.scene.current_view
            self.assertTrue(settle(env, game, lambda: menu._shop_available is not None, timeout=10))
            env.frames(game, 1)
            self.assertFalse(menu.shop_button.enabled, "shop enabled while production is down")

    # ------------------------------------------------------------ login scene
    def test_the_login_scene_with_omninet_down(self):
        env = self.env
        reset_service(self.svc)
        progress_mode(env)
        with isolate_client(env, FakeOmninet.dead_url(), timeout=0.5):
            game = env.game("login")
            env.frames(game, 1)
            scene = game.scene
            self.assertTrue(wait_for(lambda: "No internet" in scene._conn_label.text, timeout=10))
            tap_button(env, game, "Link Device")
            type_into(env, game, scene.code_entry, "AB12")
            tap_button(env, game, "Confirm", frames=0)
            self.assertTrue(wait_for(lambda: scene._async_result is not None, timeout=10))
            env.frames(game, 2)
            self.assertEqual(scene.phase, "link_device")
            shown = labels(game)
            self.assertTrue({"Cannot connect to server", "Connection timeout"} & set(shown), shown)
            self.assertTrue(button(game, "Confirm").enabled)
            self.assertFalse(self.svc.is_logged_in())

    def test_a_login_that_times_out_says_so_and_can_be_retried(self):
        env = self.env
        reset_service(self.svc)
        progress_mode(env)
        acc = self.fake.add_account("Retry")
        code = self.fake.pairing_code(acc)
        self.fake.fault("/api/v1/auth/validate-pairing-code", "slow", delay=1.5, times=1)
        game = env.game("login")
        env.frames(game, 1)
        scene = game.scene
        tap_button(env, game, "Link Device")
        type_into(env, game, scene.code_entry, code)
        tap_button(env, game, "Confirm", frames=0)
        self.assertTrue(wait_for(lambda: scene._async_result is not None, timeout=10))
        env.frames(game, 2)
        self.assertIn("Connection timeout", labels(game))
        # the server consumed the code after the client gave up: a new one works
        code = self.fake.pairing_code(acc)
        scene.code_entry.reset()
        type_into(env, game, scene.code_entry, code)
        tap_button(env, game, "Confirm", frames=0)
        self.assertTrue(wait_for(lambda: scene._async_result is not None, timeout=10))
        env.frames(game, 3)
        self.assertTrue(self.svc.is_logged_in(), labels(game))

    # BUG online-raw-parser-error-shown: an HTML error page (a 502 from the
    # proxy) makes response.json() raise inside OmninetService, and its
    # message ("Expecting value: line 1 column 1 (char 0)") is what the login
    # form shows the player.
    # Fixed 2026-10-13; kept as a regression test.
    def test_a_gateway_error_page_shows_a_readable_message(self):
        env = self.env
        reset_service(self.svc)
        progress_mode(env)
        acc = self.fake.add_account("Gateway")
        self.fake.fault("/api/v1/auth/login", "502")
        game = env.game("login")
        env.frames(game, 1)
        scene = game.scene
        tap_button(env, game, "Login")
        type_into(env, game, scene.inp_email, acc["email"])
        type_into(env, game, scene.inp_password, acc["password"])
        tap_button(env, game, "Login", frames=0)
        self.assertTrue(wait_for(lambda: scene._async_result is not None))
        env.frames(game, 2)
        shown = " ".join(labels(game))
        self.assertNotIn("Expecting value", shown)

    # ------------------------------------------------------------ shop
    def test_every_shop_page_survives_every_fault(self):
        env = self.env
        for name in SHOP_VIEWS:
            for mode in PAGE_FAULTS:
                with self.subTest(view=name, fault=mode):
                    self.fake.clear_faults()
                    self.fake.fault(LISTINGS[name], mode, delay=1.0)
                    game, v = self._shop_view(name)
                    self.assertEqual(v.shop_list.items, [])
                    env.frames(game, 2)
                    game.scene.handle_event(("B", None))
                    env.frames(game, 1)
                    self.assertEqual(view(game), "shop")
        self.assertEqual(env.gg.coins, 100)
        self.assertEqual(self._server_coins(), 100)

    def test_a_purchase_that_never_reaches_the_server_costs_nothing(self):
        env = self.env
        for mode in ("reset", "500", "502", "malformed"):
            with self.subTest(fault=mode):
                self.fake.clear_faults()
                game, v = self._shop_view("shop_items")
                tap_row(env, game, v.shop_list, 0)
                item = v.selected_item
                self.fake.fault("/api/v1/shop/purchase", mode, delay=1.0)
                before = len([s for s in env.sounds if s == "cancel"])
                tap_button(env, game, "Buy", frames=0)
                self.assertTrue(wait_for(lambda: len([s for s in env.sounds if s == "cancel"]) > before,
                                         timeout=10), "no failure feedback")
                idle()
                env.frames(game, 1)
                self.assertEqual(env.gg.coins, 100)
                self.assertEqual(item.quantity, 0)
                self.assertFalse(env.gg.purchases.has_item(self.item["id"]))
                self.assertIsNotNone(button(game, "Buy"), "the Buy button is gone")
        self.assertEqual(self._server_coins(), 100)
        self.assertEqual(self.fake.owned(self.acc), [])

    def test_a_purchase_answered_too_late_is_recovered_at_the_next_sync(self):
        """The server took the coins, the client timed out: the next start's
        sync gives the player the item and the server's balance."""
        env = self.env
        game, v = self._shop_view("shop_items")
        tap_row(env, game, v.shop_list, 0)
        self.fake.fault("/api/v1/shop/purchase", "slow_after", delay=1.0)
        tap_button(env, game, "Buy", frames=0)
        self.assertTrue(wait_for(lambda: self.fake.owned(self.acc, "item"), timeout=5))
        self.assertTrue(wait_for(lambda: "cancel" in env.sounds, timeout=5))
        self.assertEqual(env.gg.coins, 100)
        self.assertFalse(env.gg.purchases.has_item(self.item["id"]))
        self.fake.clear_faults()
        # what boot does after auto-login
        self.assertTrue(self.svc.validate_device()[0])
        from utils.module_utils import sync_account_data
        sync_account_data(download_missing=False)
        self.assertEqual(env.gg.coins, self._server_coins())
        self.assertTrue(env.gg.purchases.has_item(self.item["id"]))

    def test_a_failed_module_download_can_be_retried(self):
        env = self.env
        env.rg.game_modules = {k: m for k, m in env.rg.game_modules.items() if k != "DMOG"}
        self.fake.purchases[self.acc["id"]].append({
            "id": "p1", "item_id": self.module["id"], "purchase_type": "module", "price_paid": 0,
            "purchased_at": "2026-10-01T10:00:00.000000Z"})
        env.gg.purchases.add_module(self.module["id"], "DMOG")
        for mode in ("reset", "500", "502"):
            with self.subTest(fault=mode):
                self.fake.clear_faults()
                game, v = self._shop_view("shop_modules")
                tap_row(env, game, v.shop_list, 0)
                detail_settled(env, game, v)
                self.fake.fault(f"/api/v1/modules/{self.module['id']}/download", mode)
                tap_button(env, game, "Download", frames=0)
                self.assertTrue(settle(env, game, lambda: not v._downloading, timeout=10))
                self.assertEqual(v._status_label.text, "Error, try again")
                self.assertTrue(button(game, "Download").enabled, "retry impossible")
                self.assertTrue(button(game, "Back").enabled, "Back stays locked")
                self.assertNotIn("DMOG", env.rg.game_modules)
                self.assertTrue(env.gg.purchases.owns_module(self.module["id"]))
        self.fake.clear_faults()
        tap_button(env, game, "Download", frames=0)
        self.assertTrue(settle(env, game, lambda: not v._downloading, timeout=20))
        self.assertEqual(v._status_label.text, "Owned")
        self.assertIn("DMOG", env.rg.game_modules)

    # BUG online-late-logo-resets-download: the module detail fetches its
    # logo in the background and, when it lands, rebuilds the whole detail
    # view (shop_modules_view.py:441); during a download that resets the
    # status line and re-enables the Download button, so a second tap starts
    # a second install into the same folder.
    # Fixed 2026-10-14; kept as a regression test.
    def test_a_logo_arriving_during_a_download_keeps_the_download_state(self):
        env = self.env
        env.gg.game_mode = env.gg.GAME_MODE_FREE
        env.rg.game_modules = {k: m for k, m in env.rg.game_modules.items() if k != "DMOG"}
        mid = self.module["id"]
        self.fake.fault(f"/api/v1/modules/{mid}/logo", "slow", delay=0.3)
        self.fake.fault(f"/api/v1/modules/{mid}/download", "slow", delay=1.5)
        game, v = self._shop_view("shop_modules")
        tap_row(env, game, v.shop_list, [i.name for i in v.shop_list.items].index("DMOG"))
        item = v.selected_item
        tap_button(env, game, "Download", frames=0)
        try:
            self.assertTrue(wait_for(lambda: item.logo is not None, timeout=5), "logo never came")
            self.assertTrue(v._downloading, "precondition: the download is still running")
            self.assertFalse(v._action_button.enabled, "Download re-enabled mid-download")
            self.assertTrue(v._status_label.text.startswith("Downloading"), v._status_label.text)
        finally:
            settle(env, game, lambda: not v._downloading, timeout=20)

    def test_a_corrupt_module_zip_installs_nothing(self):
        env = self.env
        env.rg.game_modules = {k: m for k, m in env.rg.game_modules.items() if k != "DMOG"}
        broken = self.fake.add_module("Brokenmon", b"PK\x03\x04 this is not a zip", version="1.0")
        env.gg.game_mode = env.gg.GAME_MODE_FREE
        game, v = self._shop_view("shop_modules")
        names = [it.name for it in v.shop_list.items]
        tap_row(env, game, v.shop_list, names.index("Brokenmon"))
        detail_settled(env, game, v)
        tap_button(env, game, "Download", frames=0)
        self.assertTrue(settle(env, game, lambda: not v._downloading, timeout=10))
        self.assertEqual(v._status_label.text, "Error, try again")
        self.assertNotIn("Brokenmon", env.rg.game_modules)
        self.assertFalse(os.path.exists(os.path.join(modules_dir(), "Brokenmon", "module.json")))
        self.fake.catalog["module"].pop(broken["id"])

    # BUG online-failed-update-deletes-module: installing an update first
    # deletes the installed module folder (shop_modules_view.py:523,
    # module_utils.install_module_zip:113) and only then opens the zip, so a
    # broken or interrupted download leaves the player with no module at all.
    # Fixed 2026-10-13; kept as a regression test.
    def test_a_failed_update_keeps_the_installed_module(self):
        env = self.env
        env.gg.game_mode = env.gg.GAME_MODE_FREE
        env.rg.game_modules = {k: m for k, m in env.rg.game_modules.items() if k != "DMOG"}
        game, v = self._shop_view("shop_modules")
        tap_row(env, game, v.shop_list, [i.name for i in v.shop_list.items].index("DMOG"))
        detail_settled(env, game, v)
        tap_button(env, game, "Download", frames=0)
        self.assertTrue(settle(env, game, lambda: not v._downloading, timeout=20))
        installed = os.path.join(modules_dir(), "DMOG", "module.json")
        self.assertTrue(os.path.exists(installed))
        good_zip = self.fake.module_files[self.module["id"]]
        self.fake.catalog["module"][self.module["id"]]["version"] = "9.9.9"
        self.fake.module_files[self.module["id"]] = b"PK\x03\x04 truncated"
        try:
            game, v = self._shop_view("shop_modules")
            tap_row(env, game, v.shop_list, [i.name for i in v.shop_list.items].index("DMOG"))
            detail_settled(env, game, v)
            tap_button(env, game, "Update", frames=0)
            self.assertTrue(settle(env, game, lambda: not v._downloading, timeout=20))
            self.assertEqual(v._status_label.text, "Error, try again")
            self.assertTrue(os.path.exists(installed), "the failed update deleted the installed module")
        finally:
            self.fake.catalog["module"][self.module["id"]]["version"] = "1.0.3"
            self.fake.module_files[self.module["id"]] = good_zip

    # ------------------------------------------------------------ arena
    def _arena(self):
        game = connect(self.env, "arena")
        hub = game.scene.current_view
        self.assertTrue(settle(self.env, game, lambda: not hub._loading, timeout=15))
        return game, hub

    def test_the_arena_hub_with_omninet_down(self):
        env = self.env
        with isolate_client(env, FakeOmninet.dead_url(), timeout=0.5) as svc:
            svc._device_key, svc._user_info = "dk_offline", {"nickname": "x"}
            game, hub = self._arena()
            # A failed fetch is not "No active season" (2026-10-22 doc pass, 25).
            self.assertEqual(hub.time_label.text, "Cannot reach Omninet")
            self.assertFalse(hub.create_team_button.enabled)
            self.assertFalse(hub.find_button.enabled)
            self.assertFalse(hub.history_button.enabled)
            tap_button(env, game, "BACK")
            self.assertEqual(view(game), "main_menu")

    def test_the_arena_hub_survives_every_fault(self):
        env = self.env
        for mode in PAGE_FAULTS:
            with self.subTest(fault=mode):
                self.fake.clear_faults()
                self.fake.fault("/api/v1/seasons", mode, delay=1.0)
                self.fake.fault("/api/v1/teams", mode, delay=1.0)
                game, hub = self._arena()
                self.assertFalse(hub.find_button.enabled)
                self.assertFalse(hub.create_team_button.enabled)
                game.scene.handle_event(("B", None))
                env.frames(game, 1)
                self.assertEqual(view(game), "main_menu")

    def test_a_refused_or_failed_team_leaves_the_pets_in_the_party(self):
        env = self.env
        party = list(env.gg.pet_list)
        for mode in ("500", "reset", "malformed", "slow"):     # slow last: it creates the team
            with self.subTest(fault=mode):
                self.fake.clear_faults()
                env.gg.pet_list = list(party)
                game, _hub = self._arena()
                tap_button(env, game, "CREATE TEAM")
                v = game.scene.current_view
                self.assertTrue(settle(env, game, lambda: v._server_modules is not None))
                for i in range(3):
                    tap_pet(env, game, v.pet_selector, i)
                self.fake.fault("/api/v1/teams", mode, delay=1.0, method="POST")
                tap_button(env, game, "CONFIRM", frames=0)
                self.assertTrue(wait_for(lambda: not v._submitting, timeout=10), "submit never ended")
                idle()
                env.frames(game, 1)
                self.assertEqual(view(game), "arena_team_creation")
                self.assertNotIn(v.status_label.text, ("Creating team...", ""))
                self.assertTrue(v.confirm_button.enabled)
                self.assertTrue(v.back_button.enabled)
                self.assertEqual(len(env.gg.pet_list), 4)
                self.assertFalse(any(getattr(p, "arena_lock", None) for p in env.gg.pet_list))
                self.assertEqual(freezer_pets(env), [])
        self.fake.clear_faults()
        wait_for(lambda: False, timeout=1.2)
        self.fake.teams.clear()

    # BUG online-team-timeout-pets-unlocked: when the server creates the team
    # but its answer arrives after the client's timeout, the view reports a
    # failure and the pets stay in the party, unlocked; the hub then shows
    # the team (from GET /teams/current) and nothing ever locks them.
    def test_a_team_created_after_a_timeout_still_locks_its_pets(self):
        # Fixed 2026-10-16: the hub locks party pets whose uid is on the
        # current team (ArenaView._lock_loose_pets).
        env = self.env
        game, _hub = self._arena()
        tap_button(env, game, "CREATE TEAM")
        v = game.scene.current_view
        self.assertTrue(settle(env, game, lambda: v._server_modules is not None))
        for i in range(3):
            tap_pet(env, game, v.pet_selector, i)
        self.fake.fault("/api/v1/teams", "slow_after", delay=1.0, method="POST")
        tap_button(env, game, "CONFIRM")
        self.svc.ARENA_TIMEOUT = 0          # only the test's short timeout
        try:
            tap_button(env, game, "SURE?", frames=0)
            self.assertTrue(wait_for(lambda: not v._submitting, timeout=10))
        finally:
            del self.svc.ARENA_TIMEOUT
        self.assertTrue(wait_for(lambda: self.fake.teams, timeout=5))
        self.fake.clear_faults()
        game, hub = self._arena()
        self.assertTrue(hub._team, "the hub does not show the created team")
        self.assertEqual(len(env.gg.pet_list), 1, "team pets are still free in the party")

    def test_arena_modules_unavailable_keeps_confirm_off(self):
        env = self.env
        self.fake.fault("/api/v1/arena/modules", "500")
        game, _hub = self._arena()
        tap_button(env, game, "CREATE TEAM")
        v = game.scene.current_view
        self.assertTrue(settle(env, game, lambda: v.status_label.text != "Checking arena modules..."))
        self.assertIsNone(v._server_modules)
        for i in range(3):
            tap_pet(env, game, v.pet_selector, i)
        self.assertFalse(v.confirm_button.enabled)
        tap_button(env, game, "BACK")
        self.assertEqual(view(game), "arena")

    def _team_with_battle(self):
        from battle.arena import engine
        uploads = engine.random_team(self.fake.arena_catalog, 3, modules=["DMC"])
        ok, team = self.svc.create_team(uploads)
        self.assertTrue(ok, team)
        _acc, rival = self.fake.add_opponent_team("Foe", seed=9, modules=["DMC"])
        self.fake.fight(self.fake.teams[team["id"]], rival)
        return team

    def test_find_battle_and_history_errors_are_shown_and_recoverable(self):
        env = self.env
        team = self._team_with_battle()
        game, hub = self._arena()
        self.assertTrue(hub.find_button.enabled)
        self.fake.fault("/api/v1/battles/find", "500")
        tap_button(env, game, hub.find_button.text, frames=0)
        self.assertTrue(wait_for(lambda: hub.status_label.text not in ("", "Finding battle...")))
        idle()
        env.frames(game, 1)
        self.assertTrue(hub.find_button.enabled, "Find Battle stays disabled after an error")
        self.assertEqual(env.rg.game_state, "connect")
        self.fake.fault("/api/v1/battles/team", "reset")
        tap_button(env, game, "HISTORY")
        hist = game.scene.current_view
        self.assertTrue(settle(env, game, lambda: not hist._loading))
        self.assertFalse(hist.watch_button.enabled)
        self.assertNotEqual(hist.status_label.text, "Loading battles...")
        self.fake.clear_faults()
        game.scene._change_view("arena_history", team_id=team["id"], team_name=team["name"])
        hist = game.scene.current_view
        self.assertTrue(settle(env, game, lambda: hist._battles))
        self.fake.fault("/api/v1/battles/", "malformed")
        tap_button(env, game, "WATCH", frames=0)
        self.assertTrue(wait_for(lambda: hist.status_label.text not in ("", "Loading battle...")))
        idle()
        env.frames(game, 1)
        self.assertEqual(env.rg.game_state, "connect", "a broken battle opened the replay")
        tap_button(env, game, "BACK")
        self.assertEqual(view(game), "arena")

    # BUG online-history-error-reads-as-empty: when the history request
    # fails, ArenaHistoryView shows the error and then _render_rows()
    # overwrites it with "No battles yet" (arena_history_view.py:119-128),
    # so an outage tells the player their team never fought.
    # Fixed 2026-10-14; kept as a regression test.
    def test_a_history_that_failed_to_load_does_not_read_as_empty(self):
        env = self.env
        team = self._team_with_battle()
        self.fake.fault("/api/v1/battles/team", "reset")
        game = connect(env, "arena_history", team_id=team["id"], team_name=team["name"])
        hist = game.scene.current_view
        self.assertTrue(settle(env, game, lambda: not hist._loading))
        self.assertNotEqual(hist.status_label.text, "No battles yet")

    def test_a_failed_reward_claim_loses_nothing_and_can_be_retried(self):
        env = self.env
        team = self._team_with_battle()
        self.fake.end_season(self.season)
        reward = self.fake.teams[team["id"]]["rewarded_coins"]
        game, hub = self._arena()
        tap_button(env, game, "SEASON RESULTS")
        self.fake.fault("/api/v1/teams/claim-rewards", "reset")
        env.tap(game, (120, 120))
        self.assertTrue(wait_for(lambda: view(game) == "arena", timeout=10))
        hub = game.scene.current_view
        self.assertTrue(settle(env, game, lambda: not hub._loading))
        self.assertEqual(env.gg.coins, 100)
        self.assertFalse(self.fake.teams[team["id"]]["reward_claimed"])
        self.assertEqual(hub.find_button.text, "SEASON RESULTS", "the results cannot be claimed again")
        self.fake.clear_faults()
        tap_button(env, game, "SEASON RESULTS")
        env.tap(game, (120, 120))
        self.assertTrue(wait_for(lambda: view(game) == "arena", timeout=10))
        self.assertEqual(env.gg.coins, 100 + reward)
        self.assertEqual(self._server_coins(), 100 + reward)


if __name__ == "__main__":
    unittest.main()
