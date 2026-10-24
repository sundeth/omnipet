"""What a shop purchase delivers, with Omninet's real data shapes.

Protects (ONL-01): a bought item is usable by any Digimon even when a module
defines an item of the same id (Omninet sells the Vital Bracelets' NEXT and
Battle Clocks under the ids VB, VBE and VH give them), and is counted once;
its icon is kept in the save and drawn in the inventory; a bought background
draws although Omninet's download names its files without their pictures.
Found buying every entry of the dev shop on 2026-10-22.

The fake server mirrors those shapes: item ids fixed by Omninet's
items.json, item sprites named without ".png", cosmetics listed as
"bg_<name>", downloads whose pictures are empty (fake.download_pictures).
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "support"))
sys.path.insert(0, HERE)

from fake_omninet import (FakeOmninet, isolate_client, login_service, png_bytes,  # noqa: E402
                          reset_service, wait_for)
from online_ui import (connect, detail_settled, idle, labels, progress_mode, settle,  # noqa: E402
                       tap_button, tap_row)

#: Omninet storage/items/items.json: the Vital Bracelets' Battle Clock S.
BATTLE_CLOCK_S = "e3c1a686-10f8-47e7-a467-b0e407407066"
CLOCK_JSON = {"id": BATTLE_CLOCK_S, "name": "Battle Clock S", "description": "Recovers DP+3",
              "sprite_name": "icon_itm801", "effect": "status_change", "status": "dp",
              "amount": 3, "boost_time": 0, "component_item": "", "weight_gain": 0}
ICON_RGBA = (30, 200, 120, 255)
BG_RGBA = (20, 90, 160, 255)


class OnlineShopDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness import Env
        cls.env = Env("240x240", network="local")
        cls.fake = FakeOmninet().start()
        cls._iso = isolate_client(cls.env, cls.fake, timeout=2.0)
        cls.svc = cls._iso.__enter__()
        cls.clock = cls.fake.add_item("Battle Clock S", price=5, description="Recovers DP+3",
                                      sprite_name="icon_itm801", json_data=CLOCK_JSON,
                                      sprite=png_bytes(16, 16, ICON_RGBA), item_id=BATTLE_CLOCK_S)
        cls.bg_png = png_bytes(240, 240, BG_RGBA)
        cls.ocean = cls.fake.add_cosmetic("Ocean", price=25, sprite_name="bg_ocean", sprite=cls.bg_png)
        cls.alpha = cls.fake.add_module("Alpha", b"", version="1.0.0", owner="Sundeth", official=False)
        cls.beta = cls.fake.add_module("Beta", b"", version="1.0.0", owner="Sundeth", official=False)

    @classmethod
    def tearDownClass(cls):
        cls._iso.__exit__(None, None, None)
        cls.fake.stop()

    def setUp(self):
        env = self.env
        env.reset(input_mode=env.rg.TOUCH_MODE)
        reset_service(self.svc)
        from services.shop_image_cache import shop_image_cache
        shop_image_cache.clear()
        self.acc = self.fake.add_account(f"Shopper{len(self.fake.accounts)}", coins=100)
        login_service(self.svc, self.fake, self.acc)
        progress_mode(env, self.acc["id"])
        env.gg.coins = 100

    def tearDown(self):
        tracebacks = [l for l in self.env.logs if "Traceback" in l]
        self.assertEqual(tracebacks, [], "a scene or view logged a traceback")

    # ------------------------------------------------------------ helpers
    def _open(self, view_name):
        game = connect(self.env, view_name)
        v = game.scene.current_view
        self.assertTrue(settle(self.env, game, lambda: v.state == "list"), f"{view_name} never loaded")
        return game, v

    def _buy_clock(self):
        env = self.env
        game, v = self._open("shop_items")
        tap_row(env, game, v.shop_list, [it.name for it in v.shop_list.items].index("Battle Clock S"))
        detail_settled(env, game, v)
        item = v.selected_item
        tap_button(env, game, "Buy", frames=0)
        self.assertTrue(settle(env, game, lambda: item.quantity == 1), "the purchase never landed")
        idle()

    def _inventory_entries(self):
        game = self.env.game("feeding")
        self.env.frames(game, 2)
        return game, [it for it in game.scene.item_list.items if it.id == BATTLE_CLOCK_S]

    # ------------------------------------------------------------ items
    # BUG online-shop-item-shares-module-id: the inventory counted a shop
    # item once for every module defining its id (x3 with VB, VBE and VH)
    # and listed it as the first such module's item, so only that module's
    # Digimon could take it: a Battle Clock bought for an Agumon went to a
    # VB Digimon with full DP and was refused ("No pets affected").
    # Fixed 2026-10-22; kept as a regression test.
    def test_a_shop_item_a_module_also_defines_is_held_once_and_any_digimon_takes_it(self):
        from utils.inventory_utils import get_item_by_id
        if get_item_by_id(BATTLE_CLOCK_S) is None:
            self.skipTest("no installed module defines the Battle Clock S id")
        self._buy_clock()
        env = self.env
        pet = next(p for p in env.gg.pet_list if p.module not in ("VB", "VBE", "VH") and p.energy > 0)
        pet.should_sleep = lambda: False            # whatever the hour of the run
        pet.dp = 0
        env.rg.selected_pets = [pet]
        game, entries = self._inventory_entries()
        self.assertEqual(len(entries), 1, "the item is listed more than once")
        self.assertEqual(entries[0].quantity, 1, "one purchase shows as more than one item")
        self.assertTrue(getattr(entries[0].game_item, "cross_module", False),
                        "listed as a module's item instead of the shop's")
        scene = game.scene
        scene.on_item_activated(entries[0], scene.item_list.items.index(entries[0]), use_immediately=True)
        env.frames(game, 3)
        self.assertEqual(pet.dp, min(3, pet.energy), f"{pet.module} {pet.name} did not take the item")
        self.assertEqual(env.gg.purchases.get_item_quantity(BATTLE_CLOCK_S), 0)

    # BUG online-shop-item-download-fails-unusable: Omninet's item download
    # answers 500 once an account bought the item twice (its ownership check
    # expects one row), and the game has the effect only from there: on a
    # new device every clock bought twice stayed unusable. The item is the
    # module item it shares its id with, so the inventory takes that
    # definition. Found on dev 2026-10-22; kept as a regression test.
    def test_an_item_whose_download_fails_is_the_module_item_of_its_id(self):
        from utils.inventory_utils import get_item_by_id
        from utils.module_utils import shop_item_effect_known
        if get_item_by_id(BATTLE_CLOCK_S) is None:
            self.skipTest("no installed module defines the Battle Clock S id")
        self.fake.fault("/api/v1/shop/download/item", "500")
        try:
            self._buy_clock()
        finally:
            self.fake.clear_faults()
        env = self.env
        self.assertFalse(shop_item_effect_known(env.gg.shop_items_data.get(BATTLE_CLOCK_S)))
        pet = next(p for p in env.gg.pet_list if p.module not in ("VB", "VBE", "VH") and p.energy > 0)
        pet.should_sleep = lambda: False
        pet.dp = 0
        env.rg.selected_pets = [pet]
        game, entries = self._inventory_entries()
        self.assertEqual(len(entries), 1)
        self.assertTrue(getattr(entries[0].game_item, "cross_module", False))
        scene = game.scene
        scene.on_item_activated(entries[0], scene.item_list.items.index(entries[0]), use_immediately=True)
        env.frames(game, 3)
        self.assertEqual(pet.dp, min(3, pet.energy), "the item had no effect")

    # BUG online-shop-item-icon-blank: the inventory looked for a shop
    # item's icon in assets/items/<sprite_name>, which the game does not ship
    # (and Omninet names without ".png"): every bought item showed an empty
    # square. Fixed 2026-10-22 (the icon is kept in the save at purchase);
    # kept as a regression test.
    def test_a_bought_items_icon_is_kept_and_drawn_in_the_inventory(self):
        self._buy_clock()
        env = self.env
        from utils.module_utils import shop_item_icon_path
        path = shop_item_icon_path(env.gg.shop_items_data[BATTLE_CLOCK_S])
        self.assertTrue(os.path.abspath(path).startswith(os.path.abspath(env.gg.get_save_dir())), path)
        with open(path, "rb") as f:
            self.assertEqual(f.read(), self.fake.sprites[("item", BATTLE_CLOCK_S)])
        from services.shop_image_cache import shop_image_cache
        shop_image_cache.clear()                    # as after a restart
        _game, entries = self._inventory_entries()
        self.assertTrue(entries, "the bought item is not in the inventory")
        icon = entries[0].icon
        self.assertEqual(tuple(icon.get_at((icon.get_width() // 2, icon.get_height() // 2))), ICON_RGBA)

    # ------------------------------------------------------------ backgrounds
    # BUG online-background-download-empty: Omninet's cosmetic download
    # names bg_<name>.png but sends no picture, and the view wrote that
    # empty file and registered it: Settings offered the background and drew
    # the splash instead (every background of the dev shop, 2026-10-22).
    # Fixed 2026-10-22 (the shop's picture of it stands in); kept as a
    # regression test.
    def test_a_background_whose_download_has_no_picture_still_draws(self):
        env = self.env
        self.assertFalse(self.fake.download_pictures)
        game, v = self._open("shop_cosmetics")
        tap_row(env, game, v.shop_list, [it.name for it in v.shop_list.items].index("Ocean"))
        detail_settled(env, game, v)
        item = v.selected_item
        tap_button(env, game, "Buy", frames=0)
        self.assertTrue(settle(env, game, lambda: item.owned), "the purchase never landed")
        tap_button(env, game, "Download", frames=0)
        self.assertTrue(wait_for(lambda: self.ocean["id"] in env.gg.shop_backgrounds),
                        "the download never registered the background")
        idle()
        paths = env.gg.shop_backgrounds[self.ocean["id"]]["sprite_paths"]
        self.assertEqual(list(paths), ["bg_ocean.png"])
        with open(paths["bg_ocean.png"], "rb") as f:
            self.assertEqual(f.read(), self.bg_png)
        settings = env.game("settings")
        env.frames(settings, 1)
        scene = settings.scene
        scene._navigate_to("background")
        for _ in range(len(scene.unlocked_backgrounds)):
            if env.gg.background_module_name == "shop":
                break
            scene._change_background(True)
        self.assertEqual((env.gg.background_module_name, env.gg.game_background), ("shop", "Ocean"))
        env.frames(settings, 1)
        drawn = scene.window_background.last_image_path or ""
        self.assertEqual(os.path.normpath(drawn), os.path.normpath(paths["bg_ocean.png"]))


    # ------------------------------------------------------------ modules
    # BUG online-module-price-stale: the module list keeps the prices it was
    # loaded with; after the free first module every other one still said
    # "Free", the server charged it the fixed price, and the game took
    # nothing off its coins (the balance was wrong until the next login).
    # Fixed 2026-10-22 (the server's balance after a purchase; the list is
    # priced again after the free one); kept as a regression test.
    def test_after_the_free_first_module_the_next_one_costs_its_price(self):
        env = self.env
        game, v = self._open("shop_modules")
        names = [it.name for it in v.shop_list.items]
        tap_row(env, game, v.shop_list, names.index("Alpha"))
        detail_settled(env, game, v)
        self.assertIn("Free", labels(game))
        self.assertIn("Author: Sundeth", labels(game))
        alpha = v.selected_item
        tap_button(env, game, "Purchase", frames=0)
        self.assertTrue(settle(env, game, lambda: alpha.owned), "the purchase never landed")
        beta = next(it for it in v.shop_list.items if it.name == "Beta")
        wait_for(lambda: beta.price > 0, timeout=5)
        idle()
        tap_button(env, game, "Back")
        tap_row(env, game, v.shop_list, names.index("Beta"))
        detail_settled(env, game, v)
        self.assertNotIn("Free", labels(game), "the second module is offered free")
        tap_button(env, game, "Purchase", frames=0)
        self.assertTrue(settle(env, game, lambda: beta.owned), "the purchase never landed")
        server = self.fake.account(self.acc)["coins"]
        self.assertEqual(server, 50)
        self.assertEqual(env.gg.coins, server, "the game's coins differ from the account's")

    # BUG online-module-install-access-denied: on Windows a virus scanner
    # or the search indexer holds the files a module zip has just written,
    # for up to a minute, and the install's folder rename was refused
    # ("[WinError 5] Access denied"): DMC, DMGZ, DMOG, PENOG, VB, VBE and VH
    # failed to install from the dev shop on 2026-10-22.
    # Fixed 2026-10-22 (after a moment the files are copied into place);
    # kept as a regression test.
    @unittest.skipUnless(os.name == "nt", "a Windows refusal")
    def test_a_module_installs_while_a_scanner_holds_its_new_files(self):
        import io
        import zipfile
        from unittest import mock
        from paths import temp_dir
        from utils import module_utils
        for wrapped in (False, True):
            with self.subTest(wrapped=wrapped):
                prefix = "Tiny/" if wrapped else ""
                data = io.BytesIO()
                with zipfile.ZipFile(data, "w") as zf:
                    zf.writestr(prefix + "module.json", "{}")
                    zf.writestr(prefix + "monsters/a.png", b"png")
                target = os.path.join(temp_dir("install_"), "Tiny")
                real, refused = os.rename, []

                def rename(src, dst):
                    if os.path.normpath(dst) == os.path.normpath(target):
                        refused.append(src)                 # held the whole time
                        raise PermissionError(13, "Access is denied", src)
                    return real(src, dst)
                with mock.patch("os.rename", rename):
                    ok = module_utils.install_zip_into(target, data.getvalue(), "Tiny")
                self.assertTrue(refused, "the rename was never tried")
                self.assertTrue(ok, "the install gave up while the files were held")
                self.assertTrue(os.path.isfile(os.path.join(target, "module.json")))
                self.assertTrue(os.path.isfile(os.path.join(target, "monsters", "a.png")))
                self.assertFalse(os.path.exists(target + ".installing"), "the work folder was left")

if __name__ == "__main__":
    unittest.main()
