# -*- coding: utf-8 -*-
"""Game-level smoke of the iC's shops: buy with Fight Money, use what was
bought, and a DigiShop opened by a connection win.

The real game, headless (tests/support/harness.py), with the harness party
(DMC, PENC, IC and VB pets) and the iC Digimon selected. Everything is
reached by tapping the screen's own buttons:

    battle menu  SPECIALS -> the iC's tile strip -> Item Shop -> BUY the Afro (300P)
    inventory    USE the Afro: the iC Digimon wears it, the Afro stays (reusable)
    main game    the pet is drawn wearing it without an error
    connection   a lost battle against a 20X opens nothing; a win against a
                 10X (device 1) opens DigiShop 1 for good (events.json
                 "connection", utils.event_utils.after_connection, the call
                 every connection battle's result makes)
    DigiShop 1   its tile appears; BUY Level Reverse (800P, the 10X price);
                 USE it: the Child returns to its Baby II

Rules protected: ICX-05 (shops, version-specific stock), ICX-06 (Fight Money
spent, never below 0), ICX-07 (a connection win against device 1 opens
DigiShop 1), ICX-04 (accessory and Level Reverse used from the inventory).
"""
import os
import sys
import unittest
from unittest.mock import patch

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "support"))
MODULES = os.path.join(REPO_ROOT, "modules")

AFRO = "1c000040-0000-4000-8000-000000000040"
LEVEL_REVERSE = "1c000037-0000-4000-8000-000000000037"


@unittest.skipUnless(os.path.exists(os.path.join(MODULES, "IC", "shop.json")), "modules/ is gitignored")
class ICShopSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness import Env
        cls.env = Env("240x240")

    def setUp(self):
        from models.game_pet import GamePet
        env = self.env
        env.reset(input_mode=env.rg.TOUCH_MODE)
        self.gg, self.rg = env.gg, env.rg
        self.ic = next(p for p in self.gg.pet_list if p.module == "IC")
        self.rg.selected_pets = [self.ic]
        # The wall clock must not put anyone to bed mid-test.
        sleep = patch.object(GamePet, "should_sleep", return_value=False)
        sleep.start()
        self.addCleanup(sleep.stop)

    # ------------------------------------------------------------ helpers
    def tap(self, game, component, frames=3):
        self.assertTrue(component.visible, f"{component} is not on screen")
        self.env.tap(game, component.rect.center)
        self.env.frames(game, frames)

    def open_ic_specials(self):
        """Battle menu -> SPECIALS -> the iC module."""
        env = self.env
        game = env.game("battle")
        env.frames(game, 3)
        menu = game.scene.current_view
        self.assertIsNotNone(menu.specials_button, "the iC's shops give the menu its SPECIALS")
        self.tap(game, menu.specials_button)
        self.assertEqual(game.scene.current_view_name, "specials")
        hub = game.scene.current_view
        names = [module.name for module, _ in hub.entries]
        self.assertIn("IC", names)
        if hub.selected != names.index("IC"):
            self.tap(game, hub.module_buttons[names.index("IC")])
        return game, hub

    def open_shop(self, game, hub, shop_name):
        titles = [tile.special.title for tile in hub.tiles]
        self.assertIn(shop_name, titles)
        self.tap(game, hub.tiles[titles.index(shop_name)])
        self.assertEqual(game.scene.current_view_name, "module_shop")
        return game.scene.current_view

    def buy(self, game, shop, item_name):
        rows = [row.game_item.name for row in shop.item_list.items]
        self.assertIn(item_name, rows)
        shop.item_list.set_selected_index(rows.index(item_name))
        self.env.frames(game, 2)
        self.tap(game, shop.buy_button)

    def use_from_inventory(self, item_id):
        env = self.env
        game = env.game("feeding")
        env.frames(game, 3)
        inventory = game.scene
        ids = [row.id for row in inventory.item_list.items]
        self.assertIn(item_id, ids, "the bought item is listed")
        inventory.item_list.set_selected_index(ids.index(item_id))
        env.frames(game, 2)
        self.tap(game, inventory.use_button, frames=4)
        return game

    def balance(self):
        from utils import currency_utils
        return currency_utils.get_balance("IC", "Fight Money")

    # ------------------------------------------------------------ tests
    def test_buy_the_afro_and_wear_it(self):
        from utils import currency_utils
        env = self.env
        currency_utils.add_currency("IC", "Fight Money", 1000)
        game, hub = self.open_ic_specials()
        self.assertEqual([t.special.title for t in hub.tiles],
                         ["Item Shop", "Weapon Shop", "Rare Shop", "Minigames"],
                         "no DigiShop before a connection")
        shop = self.open_shop(game, hub, "Item Shop")
        afro = next(r for r in shop.item_list.items if r.game_item.name == "Afro")
        self.assertEqual(afro.amount_text, "300P")
        self.buy(game, shop, "Afro")
        self.assertEqual(self.balance(), 700)
        self.assertEqual(self.gg.inventory.get(AFRO), 1)
        self.assertIn("happy2", env.sounds)
        self.tap(game, shop.back_button)
        self.assertEqual(game.scene.current_view_name, "specials")

        game = self.use_from_inventory(AFRO)
        self.assertEqual(self.ic.accessory, AFRO)
        self.assertEqual(self.gg.inventory.get(AFRO), 1, "the Afro is worn, not used up")
        self.assertEqual(self.rg.game_state, "game")
        since = len(env.logs)
        main = env.game("game")
        env.frames(main, 20)                     # drawn wearing it
        self.assertEqual(env.error_logs(since), [])
        self.assertEqual(env.unpainted(), 0)

    def test_not_enough_fight_money_buys_nothing(self):
        from utils import currency_utils
        currency_utils.add_currency("IC", "Fight Money", 299)
        game, hub = self.open_ic_specials()
        shop = self.open_shop(game, hub, "Item Shop")
        self.buy(game, shop, "Afro")
        self.assertEqual((self.balance(), self.gg.inventory.get(AFRO, 0)), (299, 0))
        self.assertIn("fail", self.env.sounds)

    def test_a_connection_win_opens_digishop_1_and_its_level_reverse_works(self):
        from utils import currency_utils, event_utils
        env = self.env
        currency_utils.add_currency("IC", "Fight Money", 1000)
        event_utils.after_connection([(self.ic, False)], 1, battle_format="IC")   # lost to a 20X (wire 1)
        self.assertEqual(self.gg.shop_access.get("IC", {}), {})
        event_utils.after_connection([(self.ic, True)], 0, battle_format="DMM")  # a Mini on the 10X's number: not a 10X
        self.assertEqual(self.gg.shop_access.get("IC", {}), {})
        event_utils.after_connection([(self.ic, True)], 0, battle_format="IC")   # beat a 10X (wire 0)
        self.assertEqual(self.gg.shop_access["IC"], {"DigiShop 1": 0}, "for good")
        self.assertEqual(self.ic.connect_points, 3, "a point for each battle")

        game, hub = self.open_ic_specials()
        titles = [t.special.title for t in hub.tiles]
        self.assertEqual(titles, ["Item Shop", "Weapon Shop", "Rare Shop", "DigiShop 1", "Minigames"])
        shop = self.open_shop(game, hub, "DigiShop 1")
        level_reverse = [r for r in shop.item_list.items if r.game_item.name == "Level Reverse"]
        self.assertEqual([r.amount_text for r in level_reverse], ["800P"], "the 10X's price only")
        self.buy(game, shop, "Level Reverse")
        self.assertEqual(self.balance(), 200)
        self.assertEqual(self.gg.inventory.get(LEVEL_REVERSE), 1)

        pet = self.ic
        pet.evolution_history = ["iC 10X", "Botamon", "Koromon"]
        pet.hunger, weight = 1, pet.weight
        self.use_from_inventory(LEVEL_REVERSE)
        self.assertEqual((pet.name, pet.stage), ("Koromon", 2))
        self.assertEqual(self.gg.inventory.get(LEVEL_REVERSE, 0), 0, "used up")
        self.assertEqual(pet.weight, min(99, weight + 10), "Weight +10")
        self.assertEqual(pet.hunger, 5, "Hunger +4")
        self.assertEqual(env.error_logs(), [])

    def test_an_after_battle_digishop_is_one_visit(self):
        """Owner, 2026-10-17: the 20X's DigiShops after a connection open
        there and then and cannot be reached afterwards. The roll lands on
        DigiShop 10 (a 10X beaten): the alert, accepted, goes straight into
        the shop; leaving it goes back to the game and leaves nothing open."""
        from utils import currency_utils, event_utils
        env = self.env
        self.ic.version = 2                                   # a 20X
        currency_utils.add_currency("IC", "Fight Money", 1000)
        with patch("random.random", return_value=0.10):      # inside DigiShop 10's 25
            done = event_utils.after_connection([(self.ic, True)], 0, battle_format="IC")   # a 10X
        self.assertIsNotNone(self.gg.event)
        self.assertEqual((self.gg.event.shop, self.gg.event.access_minutes), ("DigiShop 10", -1))
        self.assertNotIn("DigiShop 10", self.gg.shop_access.get("IC", {}))

        game = env.game("game")
        game.scene.event_stage = 2                            # the player answered the alert
        env.frames(game, 4)
        self.assertEqual(game.scene.current_view_name, "module_shop")
        shop = game.scene.current_view
        self.assertTrue(shop.visit)
        self.buy(game, shop, "Weapon MAX")
        self.assertEqual(self.balance(), 800)
        self.tap(game, shop.back_button, frames=4)
        self.assertEqual(self.rg.game_state, "game")
        self.assertIsNone(self.gg.event)
        self.assertNotIn("DigiShop 10", self.gg.shop_access.get("IC", {}), "gone once left")
        self.assertEqual(env.error_logs(), [])


if __name__ == "__main__":
    unittest.main()
