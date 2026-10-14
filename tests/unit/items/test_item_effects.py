"""Items with more than one effect, item weight, devolve, currencies and
module shops (owner, 2026-10-05).

An item keeps one main effect, which decides who can take it; its own weight
change and its `extra_effects` then follow for the pets that took it.
"""

import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SRC = os.path.join(REPO_ROOT, "src")
for path in (SRC, REPO_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from core import game_globals, runtime_globals  # noqa: E402
from models.game_module import GameModule  # noqa: E402
from models.game_pet import GamePet  # noqa: E402
from scenes import scene_inventory  # noqa: E402
from utils import currency_utils, item_effects  # noqa: E402


def _module(**fields):
    defaults = dict(name="Test", can_eat_sleeping=True, meat_hunger_gain=1,
                    meat_weight_gain=1, protein_weight_gain=0, overfeed_timer=120,
                    hp_max_item_boost=0, atk_max_item_boost=0, power_max_item_boost=0)
    defaults.update(fields)
    return SimpleNamespace(**defaults)


def _pet(**fields):
    pet = GamePet.__new__(GamePet)
    pet.module = "Test"
    pet.name = "Testmon"
    pet.version = 1
    pet.stage = 3
    pet.hunger = 0
    pet.strength = 0
    pet.stomach = 4
    pet.weight = 15
    pet.min_weight = 10
    pet.overfeed = 0
    pet.overfeed_timer = 0
    pet.reliability = 10
    pet.injury_rate = 0
    pet.dp = 0
    pet.energy = 4
    pet.vital_values = 0
    pet.bonus_stats = [0, 0, 0]
    pet.update_99g_effect = Mock()
    for key, value in fields.items():
        setattr(pet, key, value)
    return pet


def _item(**fields):
    defaults = dict(id="it", name="Item", module="Test", effect="status_change",
                    status="hunger", amount=1, boost_time=0, weight_gain=0,
                    currency="", digisoul="", extra_effects=[])
    defaults.update(fields)
    return SimpleNamespace(**defaults)


class WeightTests(unittest.TestCase):
    def test_a_negative_weight_stops_at_the_minimum(self):
        pet = _pet(weight=15, min_weight=10)
        self.assertEqual(pet.add_weight(-99), -5)
        self.assertEqual(pet.weight, 10)
        self.assertEqual(pet.add_weight(4), 4)
        self.assertEqual(pet.weight, 14)

    def test_there_is_no_stage_limit_and_99_is_the_cap(self):
        pet = _pet(stage=1, weight=97, min_weight=5)
        pet.add_weight(10)
        self.assertEqual(pet.weight, 99)
        pet.update_99g_effect.assert_called()

    def test_an_unaccepted_meal_keeps_the_item_and_changes_nothing(self):
        """Weight and extra effects only reach a pet that took the item."""
        pet = _pet(hunger=4, stomach=4, weight=15)
        pet.set_eating = Mock(return_value=False)
        pet.check_disturbed_sleep = Mock()
        pet.add_reliability = Mock(return_value=1)
        item = SimpleNamespace(id="cake", game_item=_item(
            name="Cake", weight_gain=4,
            extra_effects=[{"effect": "status_change", "status": "reliability", "amount": 1}]))
        scene = scene_inventory.SceneInventory.__new__(scene_inventory.SceneInventory)
        scene._return_to_game = Mock()
        with patch.object(scene_inventory, "remove_from_inventory") as removed, \
                patch.object(runtime_globals, "game_console", SimpleNamespace(log=Mock())):
            scene._use_feeding_item(item, [pet])
        removed.assert_not_called()
        pet.add_reliability.assert_not_called()
        self.assertEqual(pet.weight, 15)

    def test_an_accepted_cake_gives_its_weight_and_reliability(self):
        pet = _pet(weight=15)
        pet.set_eating = Mock(return_value=True)
        pet.check_disturbed_sleep = Mock()
        item = SimpleNamespace(id="cake", game_item=_item(
            name="Cake", weight_gain=4,
            extra_effects=[{"effect": "status_change", "status": "reliability", "amount": 1}]))
        scene = scene_inventory.SceneInventory.__new__(scene_inventory.SceneInventory)
        scene._return_to_game = Mock()
        scene._setup_eating_animation = Mock()
        with patch.object(scene_inventory, "remove_from_inventory") as removed, \
                patch.object(runtime_globals, "default_items", {}, create=True), \
                patch.object(runtime_globals, "game_console", SimpleNamespace(log=Mock())), \
                patch("models.game_pet.get_module", return_value=_module()), \
                patch("utils.item_effects.get_module", return_value=_module()):
            scene._use_feeding_item(item, [pet])
        removed.assert_called_once_with("cake")
        self.assertEqual(pet.weight, 19)
        self.assertEqual(pet.reliability, 11)


class ExtraEffectTests(unittest.TestCase):
    def setUp(self):
        patcher = patch("utils.item_effects.get_module", return_value=_module())
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch("models.game_pet.get_module", return_value=_module())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_status_rows_are_plain_changes_within_limits(self):
        pet = _pet(strength=2, hunger=1, reliability=30, dp=1)
        item = _item(extra_effects=[
            {"effect": "status_change", "status": "strength", "amount": -99},
            {"effect": "status_change", "status": "hunger", "amount": 99},
            {"effect": "status_change", "status": "reliability", "amount": 31},
            {"effect": "status_change", "status": "dp", "amount": 99},
            {"effect": "status_change", "status": "injury_rate", "amount": 4},
        ])
        item_effects.apply_extra_effects(item, [pet])
        self.assertEqual((pet.strength, pet.hunger, pet.reliability, pet.dp, pet.injury_rate),
                         (0, 4, 31, 4, 4))
        self.assertEqual(pet.weight, 15, "a row puts on no weight")

    def test_a_hunger_row_on_a_full_pet_overfeeds_only_where_the_module_does(self):
        row = {"effect": "status_change", "status": "hunger", "amount": 1}
        pet = _pet(hunger=4)
        item_effects.apply_extra_effects(_item(extra_effects=[row]), [pet])
        self.assertEqual((pet.overfeed, pet.overfeed_timer), (1, 120))

        pet = _pet(hunger=4)
        with patch("utils.item_effects.get_module", return_value=_module(overfeed_timer=0)):
            item_effects.apply_extra_effects(_item(extra_effects=[row]), [pet])
        self.assertEqual((pet.overfeed, pet.overfeed_timer), (0, 0))

    def test_a_currency_row_pays_once_however_many_pets(self):
        item = _item(extra_effects=[
            {"effect": "currency", "currency": "Fight Money", "amount": 1000}])
        with patch.object(game_globals, "currency", {}), \
                patch("utils.currency_utils._module", return_value=SimpleNamespace(
                    currencies=[{"name": "Fight Money", "unit": "P"}])):
            notes = item_effects.apply_extra_effects(item, [_pet(), _pet()])
            self.assertEqual(currency_utils.get_balance("Test", "Fight Money"), 1000)
        self.assertEqual(notes, ["+1000P"])

    def test_nothing_happens_without_a_pet(self):
        pet_free = item_effects.apply_extra_effects(
            _item(extra_effects=[{"effect": "currency", "currency": "X", "amount": 5}]), [])
        self.assertEqual(pet_free, [])


class DevolveTests(unittest.TestCase):
    STAGES = {"Egg": 0, "Baby": 1, "Baby2": 2, "Child": 3, "Partner": 3, "Adult": 4}

    def _pet(self, name, history):
        pet = _pet(name=name, stage=self.STAGES[name])
        pet.evolution_history = list(history)

        def set_data(data):
            pet.name, pet.stage = data["name"], data["stage"]
        pet.set_data = set_data
        pet.reset_variables = Mock()
        pet.load_sprite = Mock()
        pet.set_state = Mock()
        return pet

    def _module(self):
        def find(name, version=None):
            stage = self.STAGES.get(name)
            return None if stage is None else {"name": name, "stage": stage, "version": 1}
        return SimpleNamespace(name="Test", find_monster=find)

    def test_it_walks_back_past_a_jogress_partner_but_never_to_an_egg(self):
        # A jogress records the partner, then evolve_to the pet's own form.
        pet = self._pet("Adult", ["Egg", "Baby", "Baby2", "Partner", "Child"])
        with patch("models.game_pet.get_module", return_value=self._module()), \
                patch.object(runtime_globals, "game_console", SimpleNamespace(log=Mock())):
            self.assertTrue(pet.devolve())
            self.assertEqual((pet.name, pet.evolution_history),
                             ("Child", ["Egg", "Baby", "Baby2", "Partner"]))
            self.assertTrue(pet.devolve())
            self.assertEqual((pet.name, pet.evolution_history), ("Baby2", ["Egg", "Baby"]))
            self.assertTrue(pet.devolve())
            self.assertEqual((pet.name, pet.evolution_history), ("Baby", ["Egg"]))
            self.assertFalse(pet.devolve(), "a Baby I never returns to its egg")
        self.assertEqual(pet.name, "Baby")
        pet.reset_variables.assert_called()


class CurrencyAndShopTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(game_globals, "currency", {})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_balances_never_go_negative_and_spending_needs_cover(self):
        self.assertEqual(currency_utils.add_currency("IC", "Fight Money", 300), 300)
        self.assertFalse(currency_utils.spend("IC", "Fight Money", 500))
        self.assertTrue(currency_utils.spend("IC", "Fight Money", 300))
        self.assertEqual(currency_utils.add_currency("IC", "Fight Money", -50), 0)
        self.assertEqual(game_globals.currency, {"IC": {"Fight Money": 0}})

    def test_a_shop_and_its_items_open_by_their_unlocks(self):
        afro = SimpleNamespace(name="Afro", id="afro", description="Equips an afro.")
        helmet = SimpleNamespace(name="Helmet", id="helmet", description="")
        module = SimpleNamespace(name="IC", items=[afro, helmet], shops=[
            {"name": "Item Shop", "unlock": "", "currency": "Fight Money", "items": [
                {"item": "Afro", "price": 300, "unlock": ""},
                {"item": "Helmet", "price": 500, "unlock": "helmets"},
                {"item": "Missing", "price": 1, "unlock": ""}]},
            {"name": "DigiShop 1", "unlock": "digishop_1", "currency": "Fight Money", "items": []}])
        with patch("utils.utils_unlocks.is_unlocked", return_value=False):
            self.assertEqual([s["name"] for s in currency_utils.available_shops(module)],
                             ["Item Shop"])
            stock = currency_utils.shop_stock(module, module.shops[0])
            self.assertEqual([(o.kind, o.item, o.price) for o in stock], [("item", afro, 300)])
        with patch("utils.utils_unlocks.is_unlocked", return_value=True):
            self.assertEqual(len(currency_utils.available_shops(module)), 2)

    def test_buying_spends_and_adds_one_to_the_inventory(self):
        module = SimpleNamespace(name="IC")
        shop = {"currency": "Fight Money"}
        item = SimpleNamespace(id="afro", name="Afro")
        offer = currency_utils.Offer("item", "Afro", "", 300, item=item)
        currency_utils.add_currency("IC", "Fight Money", 400)
        with patch("utils.inventory_utils.add_to_inventory") as added:
            self.assertEqual(currency_utils.buy(module, shop, offer), [])
            self.assertIsNone(currency_utils.buy(module, shop, offer), "100 P left")
        added.assert_called_once_with("afro", 1)
        self.assertEqual(currency_utils.get_balance("IC", "Fight Money"), 100)

    def test_the_balance_is_saved_and_follows_a_module_rename(self):
        self.assertIn("currency = {}", open(os.path.join(SRC, "core", "game_globals.py"),
                                            encoding="utf-8").read())
        game_globals.currency["DM"] = {"Gold": 5}
        game_globals._rename_saved_modules()
        self.assertEqual(game_globals.currency, {"DMOG": {"Gold": 5}})


class LoaderTests(unittest.TestCase):
    def test_items_read_their_currency_and_extra_effects(self):
        module = GameModule.__new__(GameModule)
        items = module.load_items_from_json({"item": [{
            "id": "p", "name": "Pineapple", "effect": "status_change", "status": "hunger",
            "amount": 4, "weight_gain": 10, "extra_effects": [
                {"effect": "currency", "status": "", "amount": 1000, "boost_time": 0,
                 "currency": "Fight Money"},
                {"effect": "", "amount": 3}]}]}, "IC")
        self.assertEqual(items[0].extra_effects, [{"effect": "currency", "status": "", "amount": 1000,
                                                   "boost_time": 0, "currency": "Fight Money"}])
        self.assertEqual(items[0].currency, "")
        plain = module.load_items_from_json({"item": [{"id": "m", "name": "Meat"}]}, "IC")[0]
        self.assertEqual(plain.extra_effects, [])

    def test_the_ic_shop_file_loads(self):
        folder = os.path.join(REPO_ROOT, "modules", "IC")
        if not os.path.exists(os.path.join(folder, "shop.json")):   # modules/ is gitignored
            return
        module = GameModule.__new__(GameModule)
        module.folder_path = folder
        module.load_shops()
        self.assertEqual([c["name"] for c in module.currencies], ["Fight Money"])
        self.assertIn("Item Shop", [s["name"] for s in module.shops])


class SceneTests(unittest.TestCase):
    def test_an_item_with_no_effect_is_refused_not_consumed(self):
        scene = scene_inventory.SceneInventory.__new__(scene_inventory.SceneInventory)
        scene._use_feeding_item = Mock()
        item = SimpleNamespace(id="cap", game_item=SimpleNamespace(
            name="Crown", effect="", status="", digisoul=""))
        pet = SimpleNamespace(_is_blocked_by_sleep=lambda: False, stomach=4, stage=3)
        sound = SimpleNamespace(play=Mock())
        with patch("scenes.scene_inventory.get_selected_pets", return_value=[pet]), \
                patch.object(runtime_globals, "strategy_index", 0), \
                patch.object(runtime_globals, "game_sound", sound), \
                patch.object(runtime_globals, "game_console", SimpleNamespace(log=Mock())):
            scene._use_item(item, 0)
        scene._use_feeding_item.assert_not_called()
        sound.play.assert_called_with("cancel")


class ICItemDataTests(unittest.TestCase):
    def test_the_ic_items_carry_their_second_effects(self):
        path = os.path.join(REPO_ROOT, "modules", "IC", "item.json")
        if not os.path.exists(path):          # modules/ is gitignored
            return
        items = {i["name"]: i for i in json.load(open(path, encoding="utf-8"))["item"]}
        for sweet in ("Cake", "Digi Gummy", "Wafer", "Ramune", "Chocolate"):
            self.assertEqual(items[sweet]["extra_effects"], [{
                "effect": "status_change", "status": "reliability", "amount": 1,
                "boost_time": 0}], sweet)
        self.assertEqual(items["Pineapple"]["extra_effects"][0]["currency"], "Fight Money")
        self.assertEqual(items["Pineapple"]["extra_effects"][0]["amount"], 1000)
        self.assertEqual((items["Reliability Max"]["status"], items["Reliability Max"]["amount"]),
                         ("reliability", 31))
        self.assertEqual(items["Level Reverse"]["effect"], "devolve")
        self.assertEqual(items["Level Reverse"]["extra_effects"][0]["status"], "hunger")
        self.assertEqual(items["Digi Bedding"]["effect"], "bedding")
        self.assertNotIn("extra_effects", items["Meat"])


if __name__ == "__main__":
    unittest.main()
