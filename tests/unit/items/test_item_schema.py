"""Checks for item-specific weight gains and inert catalog entries."""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

# These tests live under utilities/claude/tests/, three folders below
# the repo root, so they are not carried in the git repository.
REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SRC = os.path.join(REPO_ROOT, "src")
for path in (SRC, REPO_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from core import runtime_globals  # noqa: E402
from models.game_module import GameModule  # noqa: E402
from models.game_pet import GamePet  # noqa: E402
from scenes.scene_inventory import SceneInventory  # noqa: E402


class ItemSchemaTests(unittest.TestCase):
    def test_module_loader_preserves_item_weight_gain(self):
        module = GameModule.__new__(GameModule)
        items = module.load_items_from_json({"item": [{
            "id": "food", "name": "Food", "sprite_name": "food",
            "effect": "status_change", "status": "hunger", "amount": 2,
            "boost_time": 0, "component_item": "", "weight_gain": 4,
        }]}, "Test")
        self.assertEqual(items[0].weight_gain, 4)

    @staticmethod
    def _pet():
        pet = GamePet.__new__(GamePet)
        pet.module = "Test"
        pet.name = "Testmon"
        pet.state = "idle"
        pet.hunger = 0
        pet.stomach = 8
        pet.overfeed_timer = 0
        pet.stage = 3
        pet.weight = 15
        pet.answer_call = Mock()
        pet.check_disturbed_sleep = Mock()
        pet.set_state = Mock()
        pet.update_99g_effect = Mock()
        pet._apply_reliability_event = Mock()
        pet._is_blocked_by_sleep = Mock(return_value=False)
        return pet

    def test_food_can_override_module_weight_gain(self):
        """An item's own weight replaces the module's meat rule. The meal
        itself puts on nothing: the inventory then makes the item's change
        for every pet that took it (`item_effects.apply_weight`)."""
        from utils import item_effects
        module = SimpleNamespace(
            can_eat_sleeping=True, meat_hunger_gain=1, meat_weight_gain=1,
            protein_weight_gain=0, overfeed_timer=120)
        pet = self._pet()
        pet.min_weight = 5
        with patch("models.game_pet.get_module", return_value=module):
            self.assertTrue(pet.set_eating("hunger", 2, weight_gain=4))
            self.assertEqual(pet.weight, 15)
            item_effects.apply_weight(SimpleNamespace(weight_gain=4), [pet])
        self.assertEqual(pet.hunger, 2)
        self.assertEqual(pet.weight, 19)

    def test_missing_weight_gain_keeps_legacy_module_rule(self):
        module = SimpleNamespace(
            can_eat_sleeping=True, meat_hunger_gain=1, meat_weight_gain=1,
            protein_weight_gain=0, overfeed_timer=120)
        pet = self._pet()
        with patch("models.game_pet.get_module", return_value=module):
            self.assertTrue(pet.set_eating("hunger", 2))
        self.assertEqual(pet.weight, 16)

    def test_catalog_only_item_is_not_consumed_as_food(self):
        scene = SceneInventory.__new__(SceneInventory)
        scene._use_feeding_item = Mock()
        item = SimpleNamespace(
            id="pending",
            game_item=SimpleNamespace(
                name="Pending Weapon", effect="", status=""))
        pet = SimpleNamespace(_is_blocked_by_sleep=lambda: False, stomach=4)
        sound = SimpleNamespace(play=Mock())
        console = SimpleNamespace(log=Mock())

        with patch("scenes.scene_inventory.get_selected_pets",
                   return_value=[pet]), \
                patch.object(runtime_globals, "strategy_index", 0), \
                patch.object(runtime_globals, "game_sound", sound), \
                patch.object(runtime_globals, "game_console", console):
            scene._use_item(item, 0)

        scene._use_feeding_item.assert_not_called()
        sound.play.assert_called_with("cancel")


class ProtocolValueTests(unittest.TestCase):
    """`protocol_value`: what an item puts on its module's battle wire."""

    def test_the_loader_reads_it_and_defaults_to_nothing(self):
        module = GameModule.__new__(GameModule)
        items = module.load_items_from_json({"item": [
            {"id": "claw", "name": "Beast Claw", "effect": "status_boost",
             "status": "attack", "amount": 1, "boost_time": 1,
             "protocol_value": 2},
            {"id": "meat", "name": "Meat", "effect": "status_change",
             "status": "hunger", "amount": 1},
        ]}, "IC")
        self.assertEqual(items[0].protocol_value, 2)
        self.assertEqual(items[0].attack_sprite, 0, "older item.json files")
        self.assertEqual(items[0].digisoul, "", "older item.json files")
        self.assertEqual(items[1].protocol_value, 0, "older item.json files")

    def test_only_an_active_boost_from_that_module_is_sent(self):
        from core import game_globals
        from utils import inventory_utils
        claw = SimpleNamespace(id="claw", protocol_value=2)
        chip = SimpleNamespace(id="chip", protocol_value=0)
        modules = {"IC": SimpleNamespace(items=[claw]),
                   "DMX": SimpleNamespace(items=[chip])}
        with patch.object(runtime_globals, "game_modules", modules), \
                patch.object(game_globals, "battle_effects", {}):
            self.assertEqual(inventory_utils.active_protocol_value("IC"), 0)
            game_globals.battle_effects["attack"] = {
                "amount": 1, "boost_time": 1, "module": "IC", "item_id": "claw"}
            self.assertEqual(inventory_utils.active_protocol_value("IC"), 2)
            self.assertEqual(inventory_utils.active_protocol_value("DMX"), 0,
                             "another module's boost is not this wire's")
            game_globals.battle_effects["attack"]["item_id"] = "chip"
            game_globals.battle_effects["attack"]["module"] = "DMX"
            self.assertEqual(inventory_utils.active_protocol_value("DMX"), 0,
                             "an item that declares nothing sends nothing")

    def test_a_boost_item_with_a_digisoul_is_that_familys_only(self):
        """`digisoul` restricts a `status_boost` item to its family; on a
        `dna` item it is what the item gives, so it fits every pet."""
        from types import SimpleNamespace
        from utils import inventory_utils
        fits = inventory_utils.item_fits_pet
        bird = SimpleNamespace(digisoul="Bird")
        beast = SimpleNamespace(digisoul="Beast")
        other_line = SimpleNamespace()
        weapon = SimpleNamespace(effect="status_boost", digisoul="Bird")
        self.assertTrue(fits(weapon, bird))
        self.assertFalse(fits(weapon, beast))
        self.assertFalse(fits(weapon, other_line))
        cannon = SimpleNamespace(effect="status_boost", digisoul="")
        self.assertTrue(fits(cannon, beast) and fits(cannon, other_line))
        soul = SimpleNamespace(effect="dna", digisoul="Bird")
        self.assertTrue(fits(soul, beast))

    def test_a_dna_item_adds_its_digisoul(self):
        """The inventory's `dna` effect: `amount` of the item's family."""
        from types import SimpleNamespace
        from scenes import scene_inventory
        taken = []
        pet = SimpleNamespace(
            add_dna=lambda family, amount: taken.append((family, amount)) or amount,
            check_disturbed_sleep=lambda: None, set_state=lambda *a: None)
        item = SimpleNamespace(id="soul", game_item=SimpleNamespace(
            name="DigiSoul (Bird)", effect="dna", digisoul="Bird", amount=1))
        scene = scene_inventory.SceneInventory.__new__(scene_inventory.SceneInventory)
        scene._setup_eating_animation = lambda *a: None
        scene._return_to_game = lambda: None
        with patch.object(scene_inventory, "remove_from_inventory") as removed, \
                patch.object(scene_inventory.runtime_globals, "default_items", {},
                             create=True):
            scene._use_dna_item(item, [pet])
        self.assertEqual(taken, [("Bird", 1)])
        removed.assert_called_once_with("soul")

    def test_the_ic_weapons_are_configured(self):
        """The 19 weapons boost Attack for a battle, as the DMX/PENZ items
        do; each sends the number read off a device."""
        import json
        path = os.path.join(REPO_ROOT, "modules", "IC", "item.json")
        if not os.path.exists(path):          # modules/ is gitignored
            return
        items = json.load(open(path, encoding="utf-8"))["item"]
        weapons = [i for i in items if "Attack +" in i.get("description", "")]
        self.assertEqual(len(weapons), 19)
        for item in weapons:
            self.assertEqual((item["effect"], item["status"], item["boost_time"]),
                             ("status_boost", "attack", 1), item["name"])
            self.assertEqual(item["amount"],
                             int(item["description"].split("Attack +")[1][0]))
        sent = {i["name"]: i["protocol_value"] for i in items if i.get("protocol_value")}
        drawn = {i["name"]: i["attack_sprite"] for i in items if i.get("attack_sprite")}
        self.assertEqual(drawn, {
            "Digi Cannon": 4, "Metal Armor": 4, "Silver Rope": 4,
            "Dragon Sword": 3, "Dragon Break": 3, "Beast Claw": 8,
            "Beast Blow": 8, "Fowl Tornado": 10, "Fowl Buraiga": 10,
            "Jungle Needle": 5, "Jungle Enemis": 5, "Holy Saint": 11, "Holy Saber": 11,
            "Dark Darkness": 6, "Dark Destroy": 6, "Metal Knuckle": 7, "Metal Axe": 7,
            "Water Drop": 9, "Water Cure": 9})
        for item in weapons:
            family = item["description"].split("-family weapon")[0]
            self.assertEqual(item["digisoul"],
                             "" if "any family" in item["description"] else family,
                             item["name"])
        souls = {i["name"]: (i["effect"], i["digisoul"], i["amount"])
                 for i in items if i["name"].startswith("DigiSoul (")}
        self.assertEqual(len(souls), 8)
        for name, (effect, family, amount) in souls.items():
            self.assertEqual((effect, "DigiSoul (%s)" % family, amount),
                             ("dna", name, 1))
        self.assertEqual(sorted(sent.values()), list(range(1, 20)),
                         "the weapons are numbered 1-19 on the wire")
        self.assertEqual({name: sent[name] for name in (
            "Dragon Sword", "Dark Darkness", "Digi Cannon", "Dragon Break",
            "Holy Saber")}, {"Dragon Sword": 1, "Dark Darkness": 8,
                             "Digi Cannon": 9, "Dragon Break": 16,
                             "Holy Saber": 19})


if __name__ == "__main__":
    unittest.main()
