"""Shop > Specials and contribution points, tapped through against the fake server.

Protects: contribution points (earned on the Digimon Database) are a balance
of their own: the Specials page shows them with the diamond, read afresh
from the server when it opens; a Special priced in points is bought from
them and never from the coins, refused when they fall short; the bought
background is downloaded with all its pictures into the player's save folder
and offered in Settings > Background, where the background window draws the
picture of the time of day (dusk included) and the _high one with High-Res;
a kind of Special this Omnipet cannot use is listed but not sold. The account
sync and the save keep the balance.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "support"))
sys.path.insert(0, HERE)

from fake_omninet import (FakeOmninet, isolate_client, login_service, png_bytes,  # noqa: E402
                          redirect_relative_save, reset_service, wait_for)
from online_ui import (button, connect, detail_settled, labels, progress_mode,  # noqa: E402
                       idle, settle, tap_button, tap_row, view)

TIMES = ("day", "dusk", "night")


def premium_pictures(base):
    """The six pictures of a premium background, each its own colour."""
    out = {}
    for n, time in enumerate(TIMES):
        out[f"{base}_{time}.png"] = png_bytes(8, 8, (40 * n, 90, 160, 255))
        out[f"{base}_{time}_high.png"] = png_bytes(16, 16, (40 * n, 90, 200, 255))
    return out


class OnlineSpecialsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness import Env
        cls.env = Env("240x240", network="local")
        cls.fake = FakeOmninet().start()
        cls._iso = isolate_client(cls.env, cls.fake, timeout=2.0)
        cls.svc = cls._iso.__enter__()
        cls.pictures = premium_pictures("bg_premium_swamp")
        cls.swamp = cls.fake.add_special(
            "Swamp", price=5, description="Day, dusk and night.",
            currency="contribution_points", special_type="background",
            sprite_name="bg_premium_swamp", pictures=cls.pictures,
            json_data={"name": "premium_swamp", "label": "Swamp"})
        cls.badge = cls.fake.add_special("Golden Badge", price=30, special_type="badge")

    @classmethod
    def tearDownClass(cls):
        cls._iso.__exit__(None, None, None)
        cls.fake.stop()

    def setUp(self):
        env = self.env
        env.reset(input_mode=env.rg.TOUCH_MODE)
        # The pointer stays where the last test tapped (env.tap moves it).
        env.rg.game_input.mouse_position = (0, 0)
        self.fake.clear_faults()
        self.fake.reset_log()
        reset_service(self.svc)
        from services.shop_image_cache import shop_image_cache
        shop_image_cache.clear()
        self.acc = self.fake.add_account(f"Contributor{len(self.fake.accounts)}", coins=100,
                                         contribution_points=3)
        login_service(self.svc, self.fake, self.acc)
        progress_mode(env, self.acc["id"])
        env.gg.coins = 100
        env.gg.contribution_points = 0          # the page reads the server's

    def tearDown(self):
        tracebacks = [l for l in self.env.logs if "Traceback" in l]
        self.assertEqual(tracebacks, [], "a scene or view logged a traceback")

    # ------------------------------------------------------------ helpers
    def _open(self):
        game = connect(self.env, "shop_specials")
        self.assertEqual(view(game), "shop_specials")
        v = game.scene.current_view
        self.assertTrue(settle(self.env, game, lambda: v.state == "list"), "Specials never loaded")
        return game, v

    def _select(self, game, v, name):
        names = [it.name for it in v.shop_list.items]
        self.assertIn(name, names)
        tap_row(self.env, game, v.shop_list, names.index(name))
        self.assertEqual(v.state, "detail")
        detail_settled(self.env, game, v)
        return v.selected_item

    def _server(self):
        return self.fake.account(self.acc)

    def _buy_swamp(self):
        env = self.env
        self.fake.credit_points(self.acc, 4)              # 7 now
        game, v = self._open()
        item = self._select(game, v, "Swamp")
        target = os.path.join(env.save_root, "_relative_save")
        with redirect_relative_save(target) as written:
            tap_button(env, game, "Buy", frames=0)
            self.assertTrue(wait_for(lambda: self.swamp["id"] in env.gg.shop_backgrounds),
                            "the bought background was never downloaded")
            idle()
        env.frames(game, 1)
        self.assertEqual(written, [], "wrote outside the player's save folder")
        return game, v, item

    # ------------------------------------------------------------ listing
    def test_the_page_shows_the_points_and_prices_them_with_the_diamond(self):
        game, v = self._open()
        self.assertEqual(self.env.gg.contribution_points, 3, "the balance was not read afresh")
        self.assertEqual(self.env.gg.coins, 100)
        self.assertIn("3", labels(game))
        self.assertTrue(v.balance_icon.image_path.endswith("Shop_Diamond_1.png"))
        self.assertTrue(os.path.isfile(os.path.join(REPO_ROOT, v.balance_icon.image_path)))
        swamp, badge = v.shop_list.items
        self.assertEqual((swamp.name, swamp.currency, swamp.price), ("Swamp", "contribution_points", 5))
        self.assertTrue(swamp.day_night and swamp.high_res)
        self.assertEqual((badge.currency, badge.supported), ("coins", False))
        self.env.frames(game, 2)                           # draws both price rows

    def test_a_special_the_points_do_not_cover_cannot_be_bought(self):
        game, v = self._open()
        self._select(game, v, "Swamp")
        self.assertIn("You have 3 contribution points", labels(game))
        self.assertFalse(button(game, "Buy").enabled)

    def test_a_kind_of_special_this_omnipet_cannot_use_is_not_sold(self):
        game, v = self._open()
        self._select(game, v, "Golden Badge")
        self.assertIn("Needs a newer Omnipet", labels(game))
        self.assertFalse(button(game, "Buy").enabled)

    # ------------------------------------------------------------ buying
    def test_buying_with_points_leaves_the_coins_and_downloads_every_picture(self):
        env = self.env
        game, v, item = self._buy_swamp()
        self.assertEqual((self._server()["contribution_points"], self._server()["coins"]), (2, 100))
        self.assertEqual((env.gg.contribution_points, env.gg.coins), (2, 100))
        self.assertTrue(env.gg.purchases.owns_special(self.swamp["id"]))
        self.assertTrue(item.owned)
        bought = self.fake.owned(self.acc, "special")
        self.assertEqual([(p["item_id"], p["currency"]) for p in bought],
                         [(self.swamp["id"], "contribution_points")])
        entry = env.gg.shop_backgrounds[self.swamp["id"]]
        self.assertEqual(sorted(entry["sprite_paths"]), sorted(self.pictures))
        save_dir = os.path.abspath(env.gg.get_save_dir())
        for name, path in entry["sprite_paths"].items():
            self.assertTrue(os.path.abspath(path).startswith(save_dir), path)
            with open(path, "rb") as f:
                self.assertEqual(f.read(), self.pictures[name])
        self.assertIn("Ready: Settings > Background", labels(game))
        self.assertIsNotNone(button(game, "Download"))
        settings = env.game("settings")
        env.frames(settings, 1)
        self.assertIn(("shop", "Swamp", "Swamp"), settings.scene.unlocked_backgrounds)

    def test_a_purchase_the_server_refuses_costs_nothing(self):
        env = self.env
        self.fake.credit_points(self.acc, 4)
        game, v = self._open()
        item = self._select(game, v, "Swamp")
        self._server()["contribution_points"] = 1               # spent elsewhere
        tap_button(env, game, "Buy", frames=0)
        self.assertTrue(wait_for(lambda: len(self.fake.calls("/api/v1/shop/purchase")) == 1))
        idle()
        env.frames(game, 1)
        self.assertFalse(item.owned)
        self.assertEqual((env.gg.contribution_points, env.gg.coins), (7, 100))
        self.assertNotIn(self.swamp["id"], env.gg.shop_backgrounds)
        self.assertTrue(any("Not enough contribution points" in t for t in labels(game)))

    def test_the_bought_background_is_drawn_by_the_time_of_day(self):
        env = self.env
        self._buy_swamp()
        gg = env.gg
        gg.background_module_name, gg.game_background = "shop", "Swamp"
        from ui.windows.window_background import WindowBackground
        wb = WindowBackground(False)
        for time in TIMES:
            for high in (False, True):
                with self.subTest(time=time, high_res=high):
                    gg.background_high_res = high
                    wb.time_of_day = time
                    wb.load_sprite(False)
                    want = f"bg_premium_swamp_{time}{'_high' if high else ''}.png"
                    self.assertTrue((wb.last_image_path or "").endswith(want),
                                    f"drew {wb.last_image_path!r}, not {want}")
        gg.background_high_res = False

    def test_the_balance_is_kept_by_the_save_and_the_account_sync(self):
        env = self.env
        self._buy_swamp()
        from harness import quiet
        with quiet():
            env.gg.save()
            env.gg.contribution_points = 0
            env.gg.load()
        self.assertEqual(env.gg.contribution_points, 2)
        self.fake.credit_points(self.acc, 10)
        self.svc.refresh_user_info()
        from utils.module_utils import sync_account_data
        sync_account_data(download_missing=False)
        self.assertEqual((env.gg.contribution_points, env.gg.coins), (12, 100))


class ShopBackgroundPathsTests(unittest.TestCase):
    """WindowBackground's choice among a bought background's pictures, with
    no server: one fixed picture, or three times of day, each with _high."""

    @classmethod
    def setUpClass(cls):
        from harness import Env
        cls.env = Env("240x240")

    def setUp(self):
        self.env.reset()
        from core import game_globals
        self.gg = game_globals
        self.gg.background_high_res = False

    def tearDown(self):
        self.gg.background_high_res = False
        self.gg.shop_backgrounds = {}

    def _paths(self, sprite_name, files, time):
        from ui.windows.window_background import WindowBackground
        self.gg.shop_backgrounds = {"x": {"id": "x", "name": "X", "sprite_name": sprite_name,
                                          "sprite_paths": {f: f"/s/{f}" for f in files}}}
        wb = WindowBackground.__new__(WindowBackground)
        wb.time_of_day = time
        return [os.path.basename(p) for p in wb._shop_paths("X")]

    def test_three_times_of_day(self):
        files = [f"bg_premium_ice_{t}{h}.png" for t in TIMES for h in ("", "_high")]
        self.assertEqual(self._paths("bg_premium_ice", files, "dusk")[0], "bg_premium_ice_dusk.png")
        self.gg.background_high_res = True
        self.assertEqual(self._paths("bg_premium_ice", files, "dusk")[:2],
                         ["bg_premium_ice_dusk_high.png", "bg_premium_ice_dusk.png"])

    def test_one_fixed_picture(self):
        files = ["bg_premium_dark_ocean.png", "bg_premium_dark_ocean_high.png"]
        self.assertEqual(self._paths("bg_premium_dark_ocean", files, "night")[0],
                         "bg_premium_dark_ocean.png")
        self.gg.background_high_res = True
        self.assertEqual(self._paths("bg_premium_dark_ocean", files, "night")[0],
                         "bg_premium_dark_ocean_high.png")

    def test_a_listing_name_without_the_prefix(self):
        """A cosmetic registered with Omninet's json name ("sky") still finds
        its bg_sky pictures."""
        self.assertEqual(self._paths("sky", ["bg_sky.png", "bg_sky_high.png"], "day")[0], "bg_sky.png")


if __name__ == "__main__":
    unittest.main()
