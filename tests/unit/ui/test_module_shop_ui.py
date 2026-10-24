"""The Specials hub and the module shops, drawn headless against the real
IC and PEN20 modules (owner, 2026-10-05).

The hub lists each party module that offers something on a strip, and the
selected module's specials below: IC's open shops, PEN20's codes under its
own name for them (Copymon). A shop buys with its module's currency, and the
code entry takes only its module's codes.
"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SRC = os.path.join(REPO_ROOT, "src")
for path in (SRC, REPO_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

import pygame  # noqa: E402

from core import game_globals, runtime_globals  # noqa: E402
from ui.ui_manager import UIManager  # noqa: E402

MODULES = os.path.join(REPO_ROOT, "modules")


@unittest.skipUnless(os.path.exists(os.path.join(MODULES, "IC", "shop.json"))
                     and os.path.exists(os.path.join(MODULES, "PEN20", "codes.json")),
                     "modules/ is gitignored")
class SpecialsHubTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.chdir(REPO_ROOT)         # UI sprites load from repo-relative paths
        pygame.init()
        pygame.display.set_mode((240, 240))
        from models.game_module import GameModule
        cls.modules = {name: GameModule(os.path.join(MODULES, name))
                       for name in ("IC", "PEN20", "DMC")}

    # No pygame.quit() here: the UI's font cache outlives it, and a later
    # test that renders text would then touch freed fonts.

    def setUp(self):
        self.sound = SimpleNamespace(play=mock.Mock())
        self.slides = mock.Mock()
        party = [SimpleNamespace(module=name) for name in ("DMC", "IC", "PEN20", "IC")]
        from utils import specials_utils
        patches = [
            # Every pet of the party can train.
            mock.patch.object(specials_utils, "get_training_targets", return_value=party),
            mock.patch.object(runtime_globals, "game_modules", self.modules),
            mock.patch.object(game_globals, "pet_list", party),
            mock.patch.object(game_globals, "currency", {}),
            mock.patch.object(game_globals, "inventory", {}),
            mock.patch.object(game_globals, "unlocks", {}),
            mock.patch.object(runtime_globals, "game_sound", self.sound),
            mock.patch.object(runtime_globals, "game_message",
                              SimpleNamespace(add_slide=self.slides), create=True),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.views = []

    def change_view(self, name, **kwargs):
        self.views.append((name, kwargs))

    @staticmethod
    def draw(manager, view=None):
        surface = pygame.Surface((240, 240))
        for _ in range(2):
            manager.update()
            if view is not None:
                view.update()
            manager.draw(surface)

    def rows(self, view):
        return [tile.special.title for tile in view.tiles]

    def test_specials_is_as_wide_as_exit(self):
        from scenes.battle_views.adventure_view import AdventureView
        manager = UIManager("RED")
        view = AdventureView(manager, self.change_view)
        self.draw(manager)
        self.assertIsNotNone(view.specials_button)
        self.assertEqual(view.specials_button.base_rect.width, view.exit_button.base_rect.width)
        self.assertEqual(view.specials_button.base_rect.x, view.exit_button.base_rect.x)

    def test_the_hub_lists_each_module_with_specials_once(self):
        from scenes.battle_views.specials_view import SpecialsView
        manager = UIManager("RED")
        view = SpecialsView(manager, self.change_view)
        self.draw(manager, view)
        # DMC offers nothing; IC is in the party twice.
        self.assertEqual([module.name for module, _ in view.entries], ["IC", "PEN20"])
        self.assertIsNone(view.prev_button, "two modules need no page arrows")
        self.assertEqual(self.rows(view), ["Item Shop", "Weapon Shop", "Rare Shop", "Minigames"],
                         "the DigiShops stay hidden until unlocked")
        self.assertEqual([t.base_rect.topleft for t in view.tiles],
                         [(2, 88), (80, 88), (158, 88), (2, 154)])
        self.assertEqual(view.open_button.base_rect.y, view.back_button.base_rect.y,
                         "OPEN and BACK side by side")

        view._on_open()
        self.assertEqual(self.views[-1], ("module_shop", {"shop_key": ("IC", "Item Shop")}))

        view.module_buttons[1].activate()      # PEN20
        self.draw(manager, view)
        self.assertEqual(self.rows(view), ["Copymon"])
        view._on_open()
        self.assertEqual(self.views[-1], ("password", {"module_name": "PEN20"}))

    def test_minigames_opens_the_training_bonus_list(self):
        from scenes.battle_views.specials_view import SpecialsView
        from scenes.scene_battle import SceneBattle
        patches = [mock.patch.object(runtime_globals, name, None)
                   for name in ("scene_training_initial_view", "training_bonus_return",
                                "scene_battle_initial_view")]
        patches.append(mock.patch.object(runtime_globals, "game_state", "battle"))
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        manager = UIManager("RED")
        view = SpecialsView(manager, self.change_view)
        self.draw(manager, view)
        tile = view.tiles[self.rows(view).index("Minigames")]
        self.assertEqual(tile.special.icon_path,
                         os.path.join(self.modules["IC"].folder_path, "icons", "minigames.png"))
        self.assertIsNotNone(tile.source_icon, "the module's own icon")
        tile.activate()
        self.assertEqual(runtime_globals.game_state, "training")
        self.assertEqual(runtime_globals.scene_training_initial_view, "bonus")
        self.assertEqual(runtime_globals.training_bonus_return, ("specials", {"module_name": "IC"}))

        # The Bonus list's BACK reopens the hub on the IC module.
        runtime_globals.scene_battle_initial_view = runtime_globals.training_bonus_return
        scene = SceneBattle()
        self.assertEqual(scene.current_view_name, "specials")
        self.assertEqual(self.rows(scene.current_view)[-1], "Minigames")
        self.assertIsNone(runtime_globals.scene_battle_initial_view)

    def test_only_an_ic_module_offers_minigames(self):
        from utils import specials_utils
        kinds = {name: [s.kind for s in specials_utils.module_specials(module)]
                 for name, module in self.modules.items()}
        self.assertIn("minigames", kinds["IC"])
        self.assertNotIn("minigames", kinds["PEN20"])
        self.assertNotIn("minigames", kinds["DMC"])

    def test_no_minigames_while_no_ic_digimon_would_play(self):
        """An iC Digimon in the party, a non-iC one selected: the Bonus list
        would let nobody in, so the hub does not offer it."""
        from utils import specials_utils
        dmc = [SimpleNamespace(module="DMC")]
        with mock.patch.object(specials_utils, "get_training_targets", return_value=dmc):
            kinds = [s.kind for s in specials_utils.module_specials(self.modules["IC"])]
        self.assertNotIn("minigames", kinds)
        self.assertIn("shop", kinds, "the shops stay")

    def test_returning_reopens_the_module(self):
        from scenes.battle_views.specials_view import SpecialsView
        manager = UIManager("RED")
        view = SpecialsView(manager, self.change_view, module_name="PEN20")
        self.draw(manager, view)
        self.assertEqual(self.rows(view), ["Copymon"])
        self.assertTrue(view.module_buttons[1].is_toggled)

    def test_left_and_right_move_through_the_modules(self):
        from scenes.battle_views.specials_view import SpecialsView
        manager = UIManager("RED")
        view = SpecialsView(manager, self.change_view)
        self.draw(manager, view)
        view.module_buttons[0].handle_event(("RIGHT", None))
        self.assertEqual(view.selected, 1)
        view.module_buttons[1].handle_event(("RIGHT", None))
        self.assertEqual(view.selected, 0, "it wraps round")
        # Activating the selected module enters its list, not untoggles it.
        view.module_buttons[0].activate()
        self.assertTrue(view.module_buttons[0].is_toggled)

    def test_more_than_four_modules_page(self):
        from scenes.battle_views.specials_view import SpecialsView
        from utils import specials_utils
        entries = specials_utils.party_specials()
        with mock.patch.object(specials_utils, "party_specials", return_value=(entries * 3)[:5]):
            manager = UIManager("RED")
            view = SpecialsView(manager, self.change_view)
        self.draw(manager, view)
        self.assertIsNotNone(view.next_button)
        self.assertEqual([b.visible for b in view.module_buttons], [True] * 4 + [False])
        view._turn_page(1)
        self.assertEqual([b.visible for b in view.module_buttons], [False] * 4 + [True])
        self.assertEqual(view.selected, 4)

    def test_a_long_name_scrolls_and_a_short_one_does_not(self):
        from scenes.battle_views.specials_view import SpecialsView
        manager = UIManager("RED")
        view = SpecialsView(manager, self.change_view)
        self.draw(manager, view)
        # Font sizes vary with the display earlier tests set up, so the
        # rule is checked rather than which names happen to overflow.
        overflowing = [tile.get_font("text").size(tile.special.title)[0] > tile._caption_room()
                       for tile in view.tiles]
        self.assertIn(True, overflowing, "Weapon Shop is wider than its tile")
        # A clock that runs on from the real one, 20 ms a call.
        start = pygame.time.get_ticks() + 1000
        ticks = iter(range(start, start + 100000, 20))
        with mock.patch("pygame.time.get_ticks", side_effect=lambda: next(ticks)):
            for _ in range(view.tiles[0].SCROLL_PAUSE + 5):
                for tile in view.tiles:
                    tile.update()
        self.assertEqual([tile.scroll_offset > 0 for tile in view.tiles], overflowing)
        self.draw(manager, view)

    def test_more_than_six_specials_scroll_a_row(self):
        from scenes.battle_views.specials_view import SpecialsView
        # The DigiShops open only after a connection event: open 1-4.
        opened = {"IC": {f"DigiShop {n}": 0 for n in (1, 2, 3, 4)}}
        with mock.patch("utils.utils_unlocks.is_unlocked", return_value=True), \
                mock.patch.object(game_globals, "shop_access", opened, create=True):
            manager = UIManager("RED")
            view = SpecialsView(manager, self.change_view)
            self.draw(manager, view)
            self.assertEqual(len(view.tiles), 8, "three shops, DigiShops 1-4 and Minigames")
            self.assertEqual([t.visible for t in view.tiles], [True] * 6 + [False] * 2)
            view.tiles[3].handle_event(("DOWN", None))
            self.assertEqual(view.top_row, 1)
            self.assertEqual([t.visible for t in view.tiles], [False] * 3 + [True] * 5)
            self.assertEqual(view.current, 6)
            view._on_open()
            self.assertEqual(self.views[-1],
                             ("module_shop", {"shop_key": ("IC", "DigiShop 4")}))
            view.tiles[3].handle_event(("UP", None))
            self.assertEqual(view.top_row, 0)
            self.draw(manager, view)

    def test_buying_spends_fight_money(self):
        from scenes.battle_views.module_shop_view import ModuleShopView
        from utils import currency_utils
        manager = UIManager("RED")
        view = ModuleShopView(manager, self.change_view, shop_key=("IC", "Item Shop"))
        self.draw(manager, view)
        afro = view.item_list.items[0]
        self.assertEqual((afro.game_item.name, afro.amount_text), ("Afro", "300P"))

        view._on_buy()                          # 0 P: refused
        self.sound.play.assert_called_with("fail")
        self.assertEqual(game_globals.inventory, {})

        currency_utils.add_currency("IC", "Fight Money", 1000)
        view._on_buy()
        self.draw(manager, view)
        self.assertEqual(currency_utils.get_balance("IC", "Fight Money"), 700)
        self.assertEqual(game_globals.inventory, {afro.offer.item.id: 1})
        self.slides.assert_called()

        view._on_back()
        self.assertEqual(self.views[-1], ("specials", {"module_name": "IC"}))

    def test_the_code_entry_is_the_modules_own(self):
        from scenes.battle_views.password_view import PasswordView
        from utils import password_utils
        manager = UIManager("RED")
        view = PasswordView(manager, self.change_view, module_name="PEN20")
        self.draw(manager, view)
        self.assertEqual(view.codes_title, "Copymon")
        code = self.modules["PEN20"].passwords[0]["code"]
        self.assertEqual(password_utils.find_password(code, module_name="PEN20")[1]["code"], code)
        self.assertEqual(password_utils.find_password(code, module_name="IC"), (None, None))
        view._on_back()
        self.assertEqual(self.views[-1], ("specials", {"module_name": "PEN20"}))


if __name__ == "__main__":
    unittest.main()
