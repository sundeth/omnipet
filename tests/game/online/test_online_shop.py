"""The Omninet shop views, tapped through against the fake server.

Protects: the shop is reachable from the connect menu once Omninet answers
and lists what the server sells (ONL-04); an item, a module and a background
can be bought with the account's coins, the server and the local balance
agree afterwards, and each bought thing can then be used (ONL-01): the item
from the inventory, the module downloaded, installed and loaded, the
background downloaded and offered in Settings > Backgrounds. Purchases
belong to the account: a second device on the same account sees them as
owned (ONL-02). Free Mode downloads a module without buying it.

Module installs go to a temp folder (fake_omninet.isolate_client patches
module_utils.get_modules_dir); the cosmetics download, which writes to the
cwd-relative save/ folder, is redirected into a temp folder too.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "support"))
sys.path.insert(0, HERE)
MODULES = os.path.join(REPO_ROOT, "modules")

from fake_omninet import (FakeOmninet, isolate_client, login_service, module_zip,  # noqa: E402
                          modules_dir, png_bytes, redirect_relative_save, reset_service, wait_for)
from online_ui import (button, connect, detail_settled, labels, progress_mode,  # noqa: E402
                       idle, settle, tap_button, tap_row, view)

FOOD = {"effect": "", "status": "hunger", "amount": 1}


@unittest.skipUnless(os.path.isdir(os.path.join(MODULES, "DMOG")), "modules/DMOG not present")
class OnlineShopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness import Env
        cls.env = Env("240x240", network="local")
        cls.fake = FakeOmninet().start()
        cls._iso = isolate_client(cls.env, cls.fake, timeout=2.0)
        cls.svc = cls._iso.__enter__()
        import json
        with open(os.path.join(MODULES, "DMOG", "module.json"), encoding="utf-8") as f:
            cls.dmog_version = json.load(f)["version"]
        cls.module = cls.fake.add_module("DMOG", module_zip(os.path.join(MODULES, "DMOG")),
                                         version=cls.dmog_version,
                                         description="The original Digital Monster.")
        cls.item = cls.fake.add_item("Super Meat", price=10, description="Fills one heart.",
                                     sprite_name="super_meat.png", json_data=FOOD)
        cls.bg_png = png_bytes(240, 240, (90, 30, 120, 255))
        cls.cosmetic = cls.fake.add_cosmetic("Starry Night", price=20, sprite_name="starry_night",
                                             sprite=cls.bg_png)
        cls.fake.add_gameplay("Extra Slot", price=30, description="One more party slot.")
        cls.fake.add_special("Halloween Egg", price=40, description="Limited.")

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
        from services.shop_image_cache import shop_image_cache
        shop_image_cache.clear()                     # sprites are fetched afresh per test
        self.acc = self.fake.add_account(f"Buyer{len(self.fake.accounts)}", coins=100)
        login_service(self.svc, self.fake, self.acc)
        progress_mode(env, self.acc["id"])
        env.gg.coins = 100

    def tearDown(self):
        tracebacks = [l for l in self.env.logs if "Traceback" in l]
        self.assertEqual(tracebacks, [], "a scene or view logged a traceback")

    # ------------------------------------------------------------ helpers
    def _open(self, view_name):
        game = connect(self.env, view_name)
        self.assertEqual(view(game), view_name)
        v = game.scene.current_view
        self.assertTrue(settle(self.env, game, lambda: v.state == "list"), f"{view_name} never loaded")
        return game, v

    def _select(self, game, v, name):
        names = [it.name for it in v.shop_list.items]
        self.assertIn(name, names)
        tap_row(self.env, game, v.shop_list, names.index(name))
        self.assertEqual(v.state, "detail")
        detail_settled(self.env, game, v)
        return v.selected_item

    def _server_coins(self):
        return self.fake.account(self.acc)["coins"]

    def _buy_item(self):
        game, v = self._open("shop_items")
        item = self._select(game, v, "Super Meat")
        tap_button(self.env, game, "Buy", frames=0)
        self.assertTrue(settle(self.env, game, lambda: item.quantity == 1), "the purchase never landed")
        return game, item

    # ------------------------------------------------------------ menu
    def test_the_shop_opens_from_the_connect_menu_and_lists_every_category(self):
        env = self.env
        game = connect(env)
        menu = game.scene.current_view
        self.assertTrue(settle(env, game, lambda: menu._shop_available is not None))
        env.frames(game, 1)
        self.assertTrue(menu.shop_button.enabled, "Omninet answers but the shop stays disabled")
        env.tap(game, menu.shop_button.rect.center)
        env.frames(game, 2)
        self.assertEqual(view(game), "shop")
        self.assertIn("100", labels(game))
        expected = {"items": ["Super Meat"], "cosmetics": ["Starry Night"],
                    "modules": ["DMOG"], "gameplay": ["Extra Slot"], "specials": ["Halloween Egg"]}
        for key, names in expected.items():
            with self.subTest(category=key):
                if view(game) != "shop":
                    game.scene._change_view("shop")
                    env.frames(game, 1)
                shop = game.scene.current_view
                env.tap(game, getattr(shop, f"{key}_button").rect.center)
                env.frames(game, 2)
                v = game.scene.current_view
                self.assertEqual(view(game), f"shop_{key}")
                if hasattr(v, "state"):
                    self.assertTrue(settle(env, game, lambda: v.state == "list"))
                    self.assertEqual([it.name for it in v.shop_list.items], names)
                game.scene.handle_event(("B", None))
                env.frames(game, 1)
                self.assertEqual(view(game), "shop")

    # ------------------------------------------------------------ items
    def test_buying_an_item_spends_the_accounts_coins(self):
        game, item = self._buy_item()
        gg = self.env.gg
        self.assertEqual(self._server_coins(), 90)
        self.assertEqual(gg.coins, 90)
        self.assertEqual(gg.purchases.get_item_quantity(self.item["id"]), 1)
        self.assertEqual([p["item_id"] for p in self.fake.owned(self.acc, "item")], [self.item["id"]])
        self.assertIn("Owned: x1", labels(game))

    # BUG online-shop-items-have-no-effect: the shop listing (GET
    # /shop/items) carries no json_data, and the client never calls
    # /shop/download/item/{id}, so a bought item has no effect or status and
    # the inventory refuses it ("has no implemented effect").
    # Fixed 2026-10-17 (module_utils.ensure_shop_item_data after a purchase);
    # kept as a regression test.
    def test_a_bought_item_can_be_used_from_the_inventory(self):
        self._buy_item()
        env = self.env
        pet = env.gg.pet_list[0]
        pet.hunger = 0
        env.rg.selected_pets = [pet]
        game = env.game("feeding")
        env.frames(game, 2)
        scene = game.scene
        entries = [it for it in scene.item_list.items if it.id == self.item["id"]]
        self.assertTrue(entries, "the bought item is not in the inventory")
        scene.on_item_activated(entries[0], scene.item_list.items.index(entries[0]), use_immediately=True)
        env.frames(game, 5)
        self.assertEqual(pet.hunger, 1, "the item did nothing")
        self.assertEqual(env.gg.purchases.get_item_quantity(self.item["id"]), 0)

    def test_the_inventory_uses_an_item_whose_effect_is_known(self):
        """The consumer side works once the item's json_data reached the game
        (what the fix above has to supply)."""
        self._buy_item()
        env = self.env
        env.gg.shop_items_data[self.item["id"]].update(FOOD)
        pet = env.gg.pet_list[0]
        pet.hunger = 0
        env.rg.selected_pets = [pet]
        game = env.game("feeding")
        env.frames(game, 2)
        scene = game.scene
        entry = next(it for it in scene.item_list.items if it.id == self.item["id"])
        self.assertEqual(entry.quantity, 1)
        scene.on_item_activated(entry, scene.item_list.items.index(entry), use_immediately=True)
        env.frames(game, 5)
        self.assertEqual(pet.hunger, 1)
        self.assertEqual(env.gg.purchases.get_item_quantity(self.item["id"]), 0)

    # BUG online-shop-item-metadata-not-saved: the inventory lists a shop
    # item only with its metadata from game_globals.shop_items_data, which is
    # filled when the shop's Items page loads and is not saved; after a
    # restart the bought item is missing from the inventory until the player
    # opens the shop again.
    # Fixed 2026-10-14; kept as a regression test.
    def test_a_bought_item_is_in_the_inventory_after_a_restart(self):
        self._buy_item()
        env = self.env
        from harness import quiet
        with quiet():
            env.gg.save()
            env.gg.shop_items_data = {}
            env.gg.load()
        self.assertEqual(env.gg.purchases.get_item_quantity(self.item["id"]), 1)
        game = env.game("feeding")
        env.frames(game, 2)
        self.assertIn(self.item["id"], [it.id for it in game.scene.item_list.items])

    def test_an_item_can_be_bought_again(self):
        """Items are consumables, bought whenever the player has the coins
        (owner, 2026-10-17); unlocks stay once per account."""
        game, item = self._buy_item()
        tap_button(self.env, game, "Buy", frames=0)
        self.assertTrue(settle(self.env, game, lambda: item.quantity == 2), "the second purchase never landed")
        self.assertEqual(self._server_coins(), 80)
        self.assertEqual(self.env.gg.coins, 80)
        self.assertEqual(len(self.fake.owned(self.acc, "item")), 2)

    # BUG online-refused-purchase-reported-as-success (UI side): a refused
    # purchase is HTTP 200 with {"success": false}; the view took the coins
    # and added one more locally. Items are no longer once per account
    # (2026-10-17), so the refusal here is the server's coins running short
    # of what the game shows.
    # Fixed 2026-10-13; kept as a regression test.
    def test_a_purchase_the_server_refuses_costs_nothing(self):
        game, item = self._buy_item()
        self.fake.account(self.acc)["coins"] = 5               # spent elsewhere
        tap_button(self.env, game, "Buy", frames=0)
        self.assertTrue(wait_for(lambda: len(self.fake.calls("/api/v1/shop/purchase")) == 2))
        wait_for(lambda: item.quantity == 2, timeout=1.0)
        idle()
        self.env.frames(game, 1)
        self.assertEqual(self._server_coins(), 5)
        self.assertEqual(self.env.gg.coins, 90, "coins were taken for a refused purchase")
        self.assertEqual(self.env.gg.purchases.get_item_quantity(self.item["id"]), 1)

    # BUG online-consumed-item-regranted: sync_account_data (run at every
    # login and at boot) set every purchased item whose local quantity is 0
    # back to 1 (module_utils._apply_purchase_entries), so a used item came
    # back after each restart. Fixed 2026-10-17 (each purchase row counts
    # once, GamePurchases.item_purchase_ids); kept as a regression test.
    def test_a_used_item_does_not_come_back_at_the_next_login(self):
        self._buy_item()
        gg = self.env.gg
        gg.purchases.use_item(self.item["id"])
        from utils.module_utils import sync_account_data
        sync_account_data(download_missing=False)
        self.assertEqual(gg.purchases.get_item_quantity(self.item["id"]), 0)

    # ------------------------------------------------------------ modules
    def test_buying_a_module_downloads_installs_and_loads_it(self):
        env = self.env
        env.rg.game_modules = {k: m for k, m in env.rg.game_modules.items() if k != "DMOG"}
        game, v = self._open("shop_modules")
        item = self._select(game, v, "DMOG")
        self.assertIn("Free", labels(game), "the first module is free")
        tap_button(env, game, "Purchase", frames=0)
        self.assertTrue(settle(env, game, lambda: item.owned), "the purchase never landed")
        self.assertIn("Purchase Successful", labels(game))
        self.assertEqual(self._server_coins(), 100)
        tap_button(env, game, "Download", frames=0)
        self.assertTrue(settle(env, game, lambda: not v._downloading and v._status_label.text in
                               ("Owned", "Error, try again"), timeout=30), "the download never ended")
        self.assertEqual(v._status_label.text, "Owned")
        folder = os.path.join(modules_dir(), "DMOG")
        self.assertTrue(os.path.isfile(os.path.join(folder, "module.json")), "zip not flattened")
        mod = env.rg.game_modules.get("DMOG")
        self.assertIsNotNone(mod, "the installed module did not load")
        self.assertEqual(os.path.normpath(mod.folder_path), os.path.normpath(folder))
        self.assertEqual(str(mod.version), self.dmog_version)
        self.assertTrue(mod.get_monsters_by_stage(0), "the installed module has no eggs")
        self.assertTrue(env.gg.purchases.owns_module(self.module["id"]))
        self.assertTrue(env.gg.purchases.owns_module_name("DMOG"))
        self.assertEqual(button(game, "Updated").enabled, False)

    def test_free_mode_downloads_a_module_without_buying_it(self):
        env = self.env
        reset_service(self.svc)
        env.gg.game_mode = env.gg.GAME_MODE_FREE
        env.rg.game_modules = {k: m for k, m in env.rg.game_modules.items() if k != "DMOG"}
        game, v = self._open("shop_modules")
        self._select(game, v, "DMOG")
        self.assertIn("Free", labels(game))
        tap_button(env, game, "Download", frames=0)
        self.assertTrue(settle(env, game, lambda: not v._downloading and v._status_label.text in
                               ("Installed", "Error, try again"), timeout=30))
        self.assertEqual(v._status_label.text, "Installed")
        self.assertIn("DMOG", env.rg.game_modules)
        self.assertEqual(self.fake.calls("/api/v1/shop/purchase"), [], "Free Mode bought something")

    # ------------------------------------------------------------ cosmetics
    def _buy_and_download_background(self):
        env = self.env
        game, v = self._open("shop_cosmetics")
        item = self._select(game, v, "Starry Night")
        tap_button(env, game, "Buy", frames=0)
        self.assertTrue(settle(env, game, lambda: item.owned), "the purchase never landed")
        self.assertIn("Already Owned", labels(game))
        target = os.path.join(env.save_root, "_relative_save")
        with redirect_relative_save(target) as written:
            tap_button(env, game, "Download", frames=0)
            self.assertTrue(wait_for(lambda: self.cosmetic["id"] in env.gg.shop_backgrounds),
                            "the download never registered the background")
            idle()
        env.frames(game, 1)
        return game, written

    def test_buying_a_background_and_downloading_it_offers_it_in_settings(self):
        env = self.env
        game, written = self._buy_and_download_background()
        self.assertEqual(self._server_coins(), 80)
        self.assertEqual(env.gg.coins, 80)
        self.assertTrue(env.gg.purchases.owns_cosmetic(self.cosmetic["id"]))
        paths = list(env.gg.shop_backgrounds[self.cosmetic["id"]]["sprite_paths"].values())
        self.assertEqual(len(paths), 1)
        save_dir = os.path.abspath(env.gg.get_save_dir())
        self.assertTrue(os.path.abspath(paths[0]).startswith(save_dir), paths[0])
        with open(paths[0], "rb") as f:
            self.assertEqual(f.read(), self.bg_png)
        settings = env.game("settings")
        env.frames(settings, 1)
        self.assertIn(("shop", "Starry Night", "Starry Night"), settings.scene.unlocked_backgrounds)

    # BUG online-shop-background-never-drawn: Settings lists a bought
    # background under the module name "shop", but WindowBackground has no
    # paths for that module (it looks for modules/<name>/backgrounds), so the
    # selected background silently falls back to a module one.
    # Fixed 2026-10-14; kept as a regression test.
    def test_a_selected_shop_background_is_drawn(self):
        env = self.env
        _game, written = self._buy_and_download_background()
        settings = env.game("settings")
        env.frames(settings, 1)
        scene = settings.scene
        scene._navigate_to("background")
        for _ in range(len(scene.unlocked_backgrounds)):
            if env.gg.background_module_name == "shop":
                break
            scene._change_background(True)
        self.assertEqual((env.gg.background_module_name, env.gg.game_background), ("shop", "Starry Night"))
        env.frames(settings, 1)
        path = scene.window_background.last_image_path or ""
        self.assertTrue(path.endswith("bg_starry_night.png"), f"drew {path!r} instead")

    # BUG online-shop-background-lost-on-restart: the downloaded background
    # is registered only in game_globals.shop_backgrounds, which save() does
    # not write, so after a restart it is gone from Settings until the player
    # downloads it again.
    # Fixed 2026-10-14; kept as a regression test.
    def test_a_downloaded_background_survives_a_restart(self):
        env = self.env
        self._buy_and_download_background()
        from harness import quiet
        with quiet():
            env.gg.save()
            env.gg.shop_backgrounds = {}
            env.gg.load()
        self.assertIn(self.cosmetic["id"], env.gg.shop_backgrounds)

    # BUG online-cosmetics-outside-save-folder: the download writes to the
    # cwd-relative "save/cosmetics/backgrounds" (shop_cosmetics_view.py:470)
    # instead of the player's save folder: shared by every account and,
    # on Android, not the app's storage folder.
    # Fixed 2026-10-14; kept as a regression test.
    def test_downloaded_cosmetics_go_to_the_players_save_folder(self):
        _game, written = self._buy_and_download_background()
        self.assertEqual(written, [], f"wrote to the shared folder: {[w[0] for w in written]}")

    # ------------------------------------------------------------ second device
    def test_a_second_device_sees_the_purchases_as_owned(self):
        """ONL-02: buy on one Omnipet, log in on another, the shop says owned."""
        env = self.env
        self._buy_item()
        game, v = self._open("shop_cosmetics")
        bg = self._select(game, v, "Starry Night")
        tap_button(env, game, "Buy", frames=0)
        self.assertTrue(settle(env, game, lambda: bg.owned))
        coins = self._server_coins()
        # the other Omnipet: a fresh save, logged in on the same account
        env.reset(input_mode=env.rg.TOUCH_MODE)
        reset_service(self.svc)
        login_service(self.svc, self.fake, self.acc)
        progress_mode(env, self.acc["id"])
        self.assertFalse(env.gg.purchases.owns_cosmetic(self.cosmetic["id"]))
        from utils.module_utils import sync_account_data
        sync_account_data(download_missing=False)
        self.assertEqual(env.gg.coins, coins)
        game, v = self._open("shop_cosmetics")
        self.assertTrue(v.shop_list.items[0].owned)
        self._select(game, v, "Starry Night")
        self.assertIn("Already Owned", labels(game))
        self.assertIsNotNone(button(game, "Download"))
        game, v = self._open("shop_items")
        self.assertEqual(v.shop_list.items[0].quantity, 1)


if __name__ == "__main__":
    unittest.main()
