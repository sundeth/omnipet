"""Battle items chosen before a battle, items and cards read for one Digimon
of their own module, and the card pack reveal (owner, 2026-10-17).

* "battle effect items should not be usable in SceneInventory, instead they
  appear as a list before a battle is played (for the same module) ...
  DMX items are used at the beginning and persist for all rounds of the same
  area while IC needs a new item used on every round of the colosseum":
  ``battle_item_use`` "area" offers the list before an adventure battle
  only, "round" before every round, and a round's effect ends with it.
* "When using an item of a specific module make the player pick a digimon to
  apply the effects that belongs to that module."
* "when reading a card effect, make the player choose a pet from the same
  module so we have a version to use (if theres only 1 digimon of said
  module in the party, pick that automatically)".
* "Add some animation when a card pack is being opened to reveal the card":
  the reveal queues each pack and holds the input until it is done; a won
  or unlocked pack waits for the main game screen.

The Vital Bracelet modules' former Stat Shops are battle drops since
2026-10-21: tests/unit/items/test_battle_drops.py.
"""

import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SRC = os.path.join(REPO_ROOT, "src")
for path in (SRC, REPO_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from core import game_globals, runtime_globals  # noqa: E402
from utils import battle_items, card_utils  # noqa: E402


def _item(item_id, effect="status_boost", status="attack", amount=1, boost_time=1,
          module="IC", **fields):
    base = dict(id=item_id, name=item_id.title(), module=module, effect=effect, status=status,
                amount=amount, boost_time=boost_time, digisoul="", reusable=False,
                weight_gain=None, extra_effects=[], min_stage=0, max_stage=0, target="")
    base.update(fields)
    return SimpleNamespace(**base)


class BattleItemListTests(unittest.TestCase):
    def setUp(self):
        self.cannon = _item("cannon")
        self.claw = _item("claw", digisoul="Beast")
        self.meat = _item("meat", effect="status_change", status="hunger")
        self.module = SimpleNamespace(name="IC", items=[self.cannon, self.claw, self.meat],
                                      battle_item_use="round")
        self.stock = {"cannon": 2, "claw": 1, "meat": 5}
        patcher = patch("utils.inventory_utils.get_inventory_value",
                        side_effect=lambda item_id: self.stock.get(item_id, 0))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_only_the_modules_battle_items_the_player_has(self):
        rows = battle_items.battle_items(self.module)
        self.assertEqual([(item.id, qty) for item, qty in rows], [("cannon", 2), ("claw", 1)])
        self.stock["cannon"] = 0
        self.assertEqual([item.id for item, _ in battle_items.battle_items(self.module)], ["claw"])

    def test_a_family_weapon_is_listed_for_its_family_only(self):
        dragon = SimpleNamespace(digisoul="Dragon", stage=3)
        beast = SimpleNamespace(digisoul="Beast", stage=3)
        with patch("utils.item_effects.fits", return_value=True):
            self.assertEqual([i.id for i, _ in battle_items.battle_items(self.module, [dragon])],
                             ["cannon"])
            self.assertEqual([i.id for i, _ in battle_items.battle_items(self.module, [beast])],
                             ["cannon", "claw"])

    def test_area_timing_offers_the_list_before_the_first_battle_only(self):
        self.module.battle_item_use = "area"
        self.assertTrue(battle_items.offers_items_now(self.module, True))
        self.assertFalse(battle_items.offers_items_now(self.module, False))
        self.module.battle_item_use = "round"
        self.assertTrue(battle_items.offers_items_now(self.module, False))
        self.stock.update(cannon=0, claw=0)
        self.assertFalse(battle_items.offers_items_now(self.module, True), "nothing to offer")

    def test_timing_defaults_to_area(self):
        self.assertEqual(battle_items.item_use_timing(SimpleNamespace()), "area")
        self.assertEqual(battle_items.item_use_timing(SimpleNamespace(battle_item_use="ROUND")),
                         "round")
        self.assertEqual(battle_items.item_use_timing(SimpleNamespace(battle_item_use="x")), "area")

    def test_using_one_stores_its_effect_and_uses_it_up(self):
        effects = {}
        with patch.object(game_globals, "battle_effects", effects), \
                patch("utils.inventory_utils.remove_from_inventory") as removed, \
                patch.dict(runtime_globals.game_modules, {"IC": self.module}):
            battle_items.use_battle_item(self.cannon, [])
        self.assertEqual(effects["attack"]["module"], "IC")
        self.assertEqual(effects["attack"]["item_id"], "cannon")
        self.assertEqual(effects["attack"]["boost_time"], 1)
        removed.assert_called_once_with("cannon")


class RoundEffectExpiryTests(unittest.TestCase):
    """A round's weapon ends with the round where items are used every
    round; in an area it lasts to the boss."""

    def run_round(self, timing, boss=False, won=True):
        from battle.battle_encounter import BattleEncounter
        from models.game_enemy import GameEnemy
        enc = BattleEncounter.__new__(BattleEncounter)
        pet = SimpleNamespace(level=1, stage=3, add_experience=Mock(), finish_battle=Mock())
        enc.pvp_mode = False
        enc.victory_status = "Victory" if won else "Defeat"
        enc.get_battle_effect = lambda name: None
        enemy = GameEnemy(name="Mon", power=10, attribute="", area=1, round=2, version=1,
                          atk_main=1, atk_alt=0, atk_alt_2=0, handicap=0, id=1, stage=3,
                          hp=0, unlock=None, prize=None)
        enc.battle_player = SimpleNamespace(team1=[pet], team2=[enemy], xp=0, bonus=0,
                                            level_up=[False])
        enc.global_battle_log = SimpleNamespace(device1_final=[SimpleNamespace(alive=True)])
        enc.module = SimpleNamespace(name="IC", folder_path="x", battle_sequential_rounds=True,
                                     items=[], currencies=[], shops=[], unlocks=[],
                                     battle_item_use=timing)
        enc.boss, enc.round, enc.area = boss, 2, 1
        enc.is_special_encounter = False
        enc.frame_counter = 0
        effects = {"attack": {"amount": 1, "boost_time": 1, "module": "IC", "item_id": "cannon"}}
        with patch.object(game_globals, "battle_effects", effects), \
                patch.object(runtime_globals, "game_console", SimpleNamespace(log=Mock())), \
                patch.object(BattleEncounter, "_battle_vital_values", lambda self, won: None):
            enc.process_battle_results()
        return effects

    def test_round_timing_ends_the_effect_after_the_round(self):
        self.assertEqual(self.run_round("round"), {})
        self.assertEqual(self.run_round("round", won=False), {}, "a lost round too")

    def test_area_timing_keeps_it_until_the_boss(self):
        self.assertIn("attack", self.run_round("area"))
        self.assertIn("attack", self.run_round("area", won=False), "kept for the next attempt")
        self.assertEqual(self.run_round("area", boss=True), {})


class InventoryTests(unittest.TestCase):
    def scene(self):
        from scenes import scene_inventory
        scene = scene_inventory.SceneInventory.__new__(scene_inventory.SceneInventory)
        scene.picking_item = None
        scene.text_panel = None
        scene.item_list = None
        scene.pet_selector = Mock(enabled_pets=[])
        scene.ui_manager = Mock()
        scene._dispatch_item = Mock()
        scene._show_notes = Mock()
        return scene

    def pet(self, module):
        return SimpleNamespace(module=module, _is_blocked_by_sleep=lambda: False, stomach=4,
                               stage=3, digisoul="", hunger=1, strength=1)

    def run_use(self, scene, item, party, selected=None):
        with patch.object(game_globals, "pet_list", party), \
                patch("scenes.scene_inventory.get_selected_pets", return_value=selected or party), \
                patch.dict(runtime_globals.game_modules, {"IC": SimpleNamespace(name="IC")}), \
                patch.object(runtime_globals, "strategy_index", 0), \
                patch.object(runtime_globals, "game_sound", SimpleNamespace(play=Mock())), \
                patch.object(runtime_globals, "game_console", SimpleNamespace(log=Mock())), \
                patch("utils.item_effects.fits", return_value=True):
            scene._use_item(SimpleNamespace(id=item.id, game_item=item), 0)

    def test_a_battle_item_is_not_used_from_the_inventory(self):
        scene = self.scene()
        self.run_use(scene, _item("cannon"), [self.pet("IC")])
        scene._dispatch_item.assert_not_called()
        scene._show_notes.assert_called_once_with(["Use it before a battle"])

    def test_a_modules_item_asks_which_of_its_digimon(self):
        scene = self.scene()
        scene._start_pick = Mock()
        ic1, ic2, dmc = self.pet("IC"), self.pet("IC"), self.pet("DMC")
        item = _item("cake", effect="status_change", status="hunger")
        self.run_use(scene, item, [ic1, dmc, ic2], selected=[dmc])
        scene._start_pick.assert_called_once()
        self.assertEqual(scene._start_pick.call_args.args[1], [ic1, ic2],
                         "the module's Digimon, whoever is selected")
        scene._dispatch_item.assert_not_called()

    def test_with_one_digimon_of_the_module_it_takes_the_item(self):
        scene = self.scene()
        ic1, dmc = self.pet("IC"), self.pet("DMC")
        self.run_use(scene, _item("cake", effect="status_change", status="hunger"), [ic1, dmc])
        scene._dispatch_item.assert_called_once()
        self.assertEqual(scene._dispatch_item.call_args.args[1], [ic1])

    def test_a_core_food_still_feeds_the_selected_digimon(self):
        scene = self.scene()
        a, b = self.pet("IC"), self.pet("DMC")
        food = _item("protein", effect="status_change", status="hunger", module="core")
        self.run_use(scene, food, [a, b], selected=[a, b])
        self.assertEqual(scene._dispatch_item.call_args.args[1], [a, b])


class CardForOneDigimonTests(unittest.TestCase):
    def test_the_chosen_digimon_decides_the_version_and_takes_the_digisoul(self):
        v1 = SimpleNamespace(module="IC", version=1, add_dna=Mock(return_value=1))
        v2 = SimpleNamespace(module="IC", version=2, add_dna=Mock(return_value=1))
        effects = [{"type": "DNA", "dna": "Beast", "amount": 1, "version": 1},
                   {"type": "DNA", "dna": "Holy", "amount": 1, "version": 2},
                   {"type": "DNA", "dna": "Dark", "amount": 1, "version": -1}]
        with patch("utils.pet_utils.get_selected_pets", return_value=[v1, v2]):
            card_utils.apply_card_effects("IC", effects, v2)
        v1.add_dna.assert_not_called()
        self.assertEqual([c.args[0] for c in v2.add_dna.call_args_list], ["Holy", "Dark"])

    def test_the_party_pets_of_a_module(self):
        a, b, c = (SimpleNamespace(module=m) for m in ("IC", "DMC", "IC"))
        with patch.object(game_globals, "pet_list", [a, None, b, c]):
            self.assertEqual(card_utils.party_pets_of("IC"), [a, c])

    def collection(self):
        from scenes.scene_collection import SceneCollection
        scene = SceneCollection.__new__(SceneCollection)
        scene._set_mode = Mock()
        scene.pet_selector = Mock(pets=[])
        return scene

    def test_one_digimon_of_the_module_is_chosen_without_asking(self):
        scene = self.collection()
        only = SimpleNamespace(module="IC")
        then = Mock()
        with patch.object(game_globals, "pet_list", [only, SimpleNamespace(module="DMC")]):
            scene._choose_pet("IC", "Card", then, "view")
        then.assert_called_once_with(only)
        scene._set_mode.assert_not_called()

    def test_none_of_the_module_reads_it_for_no_digimon(self):
        scene = self.collection()
        then = Mock()
        with patch.object(game_globals, "pet_list", [SimpleNamespace(module="DMC")]):
            scene._choose_pet("IC", "Card", then, "view")
        then.assert_called_once_with(None)

    def test_two_of_the_module_ask_the_player(self):
        scene = self.collection()
        a, b = SimpleNamespace(module="IC"), SimpleNamespace(module="IC")
        then = Mock()
        with patch.object(game_globals, "pet_list", [SimpleNamespace(module="DMC"), a, b]):
            scene._choose_pet("IC", "Card", then, "view")
        then.assert_not_called()
        scene._set_mode.assert_called_once_with("pick")
        scene.pet_selector.set_enabled_pets.assert_called_once_with([1, 2])

    def test_an_unobtained_card_shows_no_name(self):
        from scenes.scene_collection import SceneCollection
        card = {"id": "x", "name": "Agumon", "number": 4}
        with patch.object(card_utils, "get_owned",
                          return_value={"digital": 0, "physical": 0, "shiny": 0}):
            self.assertEqual(SceneCollection.__new__(SceneCollection)._card_name("IC", card), "???")
        self.assertEqual(SceneCollection._number_text(card), "#4")
        self.assertEqual(SceneCollection._number_text({"type": "Soul Plate", "number": 0}), "?")


class RevealTests(unittest.TestCase):
    def setUp(self):
        from ui.card_reveal import CardReveal
        self.reveal = CardReveal()
        self.sound = SimpleNamespace(play=Mock())
        for patcher in (patch.object(runtime_globals, "game_sound", self.sound),
                        patch.object(card_utils, "total_copies", return_value=1)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.cards = [({"id": "a", "name": "A"}, False), ({"id": "b", "name": "B"}, True)]

    def test_a_pack_waits_for_its_scene_then_holds_the_input(self):
        self.reveal.add("IC", self.cards, {"name": "Pack"}, wait_for="SceneMainGame")
        self.reveal.update("SceneBattle")
        self.assertFalse(self.reveal.active, "a won pack waits for the main game")
        self.reveal.update("SceneMainGame")
        self.assertTrue(self.reveal.active)
        self.assertTrue(self.reveal.handle_event(("LEFT", None)), "every input is held")

    def test_a_goes_through_the_cards_and_closes(self):
        self.reveal.add("IC", self.cards)
        self.reveal.update()
        self.reveal.handle_event(("A", None))       # skip the pack
        self.assertEqual(self.reveal.phase, "flip")
        self.reveal.handle_event(("A", None))       # finish the turn
        self.assertEqual((self.reveal.phase, self.reveal.card_index), ("shown", 0))
        self.reveal.handle_event(("A", None))
        self.reveal.handle_event(("A", None))
        self.assertEqual((self.reveal.phase, self.reveal.card_index), ("shown", 1))
        self.sound.play.assert_any_call("card_shiny")
        self.reveal.handle_event(("A", None))
        self.assertFalse(self.reveal.active)
        self.assertFalse(self.reveal.pending())

    def test_b_skips_to_the_end(self):
        self.reveal.add("IC", self.cards)
        self.reveal.update()
        self.reveal.handle_event(("B", None))
        self.assertFalse(self.reveal.active)

    def test_a_card_is_new_when_every_copy_came_in_this_pack(self):
        with patch.object(card_utils, "total_copies", side_effect=lambda m, cid: {"a": 2, "b": 3}[cid]):
            self.reveal.add("IC", [({"id": "a"}, False), ({"id": "a"}, False), ({"id": "b"}, False)])
        cards = self.reveal.queue[0]["cards"]
        self.assertEqual([c["new"] for c in cards], [True, True, False])


def _module_json(module, name):
    path = os.path.join(REPO_ROOT, "modules", module, name)
    if not os.path.exists(path):        # modules/ is gitignored
        return None
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


class ModuleDataTests(unittest.TestCase):
    def test_the_ic_uses_battle_items_every_round(self):
        data = _module_json("IC", "module.json")
        if data is not None:
            self.assertEqual(data.get("battle_item_use"), "round")


if __name__ == "__main__":
    unittest.main()
