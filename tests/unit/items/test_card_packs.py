"""Currency caps, training pay, and card packs: opened from a shop, an
unlock or a battle prize (owner, 2026-10-05).

* A currency's ``cap`` is the most a player holds (the iC's 9,999).
* A training pays each module that had a pet in it once, the currency's
  ``training_gain`` for the best outcome among its pets.
* A pack draws ``cards_per_pack`` cards by ``odds``, shiny at
  ``shine_chance`` percent. Shops sell packs (``card_pack`` lines), unlocks
  grant them (``card_pack``), and an enemy's prize may be one
  (``prize_card_pack``). A win draws one prize at random from the round's
  enemies and rolls its ``prize_chance`` (items too; absent is 100).
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

from core import game_globals, runtime_globals  # noqa: E402
from models.game_enemy import GameEnemy  # noqa: E402
from utils import card_utils, currency_utils  # noqa: E402

CARDS = {
    "cards": [
        {"id": "a", "type": "iD Plate", "name": "Agumon Plate"},
        {"id": "b", "type": "iD Plate", "name": "Gabumon Plate"},
        {"id": "s", "type": "Soul Plate", "name": "Burst Blue"},
    ],
    "effects": [],
    "packs": [
        {"id": "p1", "name": "Starter Pack", "cards_per_pack": 3, "shine_chance": 100,
         "cards": [{"id": "a", "odds": 1}, {"id": "s", "odds": 1}]},
        {"id": "p0", "name": "Empty Pack", "cards_per_pack": 1, "shine_chance": 0, "cards": []},
    ],
}


def module(**fields):
    base = dict(name="Test", folder_path="x", currencies=[
        {"name": "Fight Money", "unit": "P", "training_gain": [0, 10, 20, 50], "cap": 9999}],
        shops=[], items=[], unlocks=[])
    base.update(fields)
    return SimpleNamespace(**base)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.module = module()
        self.slides = mock.Mock()
        for patch in (
                mock.patch.object(game_globals, "currency", {}),
                mock.patch.object(game_globals, "card_collection", {}),
                mock.patch.object(game_globals, "unlocks", {}),
                mock.patch.object(runtime_globals, "game_modules", {"Test": self.module}),
                mock.patch.dict(card_utils._module_cards_cache, {"Test": CARDS}),
                mock.patch.object(runtime_globals, "game_message",
                                  SimpleNamespace(add_slide=self.slides), create=True),
                mock.patch.object(runtime_globals, "game_console",
                                  SimpleNamespace(log=mock.Mock()))):
            patch.start()
            self.addCleanup(patch.stop)

    def owned(self, card_id):
        return card_utils.get_owned("Test", card_id)


class CapAndTrainingTests(Fixture):
    def test_the_cap_stops_earnings(self):
        currency_utils.add_currency("Test", "Fight Money", 9990)
        self.assertEqual(currency_utils.add_currency("Test", "Fight Money", 50), 9)
        self.assertEqual(currency_utils.get_balance("Test", "Fight Money"), 9999)
        self.assertEqual(currency_utils.add_currency("Test", "Fight Money", -1000), -1000)

    def test_a_balance_over_a_new_cap_is_not_cut(self):
        game_globals.currency["Test"] = {"Fight Money": 12000}
        self.assertEqual(currency_utils.add_currency("Test", "Fight Money", 10), 0)
        self.assertEqual(currency_utils.get_balance("Test", "Fight Money"), 12000)

    def test_training_pays_each_module_once_at_its_best_grade(self):
        other = module(name="Other", currencies=[
            {"name": "Coins", "unit": "", "training_gain": [1, 2, 3, 4]}])
        runtime_globals.game_modules["Other"] = other
        pets = [SimpleNamespace(module="Test"), SimpleNamespace(module="Test"),
                SimpleNamespace(module="Other"), SimpleNamespace(module="NoCurrency")]
        notes = currency_utils.pay_training([
            (pets[0], True, 1), (pets[1], True, 3), (pets[2], False, 3), (pets[3], True, 3)])
        self.assertEqual(currency_utils.get_balance("Test", "Fight Money"), 50, "Excellent, once")
        self.assertEqual(currency_utils.get_balance("Other", "Coins"), 1, "a failed pet is Bad")
        self.assertEqual(notes, ["+50P", "+1 Coins"])


class PackTests(Fixture):
    def test_a_pack_draws_its_cards_and_shines(self):
        drawn = card_utils.open_pack("Test", "p1")
        self.assertEqual(len(drawn), 3)
        for card, shiny in drawn:
            self.assertIn(card["id"], ("a", "s"))
            # A Soul Plate is never shiny, whatever the pack's chance.
            self.assertEqual(shiny, card["id"] == "a")
        self.assertEqual(self.owned("a")["digital"] + self.owned("s")["digital"], 3)
        self.assertEqual(self.owned("b")["digital"], 0, "not in the pack")

    def test_a_missing_or_empty_pack_gives_nothing(self):
        self.assertEqual(card_utils.open_pack("Test", "nope"), [])
        self.assertEqual(card_utils.open_pack("Test", "p0"), [])

    def test_a_shop_sells_a_pack_and_opens_it(self):
        shop = {"name": "Card Shop", "currency": "Fight Money", "items": [
            {"item": "", "card_pack": "p1", "price": 300, "unlock": ""},
            {"item": "", "card_pack": "gone", "price": 1, "unlock": ""}]}
        stock = currency_utils.shop_stock(self.module, shop)
        self.assertEqual([(o.kind, o.name, o.price) for o in stock],
                         [("card_pack", "Starter Pack", 300)])
        self.assertIsNone(currency_utils.buy(self.module, shop, stock[0]), "0 P")
        currency_utils.add_currency("Test", "Fight Money", 500)
        cards = currency_utils.buy(self.module, shop, stock[0])
        self.assertEqual(len(cards), 3)
        self.assertEqual(currency_utils.get_balance("Test", "Fight Money"), 200)

    def test_an_unlock_opens_its_pack_once(self):
        from utils.utils_unlocks import unlock_item
        self.module.unlocks = [{"name": "clear_1", "type": "adventure", "card_pack": "p1"}]
        with mock.patch("utils.reward_utils.reward_unlock", create=True):
            unlock_item("Test", "adventure", "clear_1")
            unlock_item("Test", "adventure", "clear_1")
        self.assertEqual(self.owned("a")["digital"] + self.owned("s")["digital"], 3)


class PrizeTests(Fixture):
    def enemy(self, **fields):
        base = dict(name="Mon", power=10, attribute="", area=1, round=1, version=1,
                    atk_main=1, atk_alt=0, atk_alt_2=0, handicap=0, id=1, stage=3,
                    hp=0, unlock=None, prize=None)
        base.update(fields)
        return GameEnemy(**base)

    def encounter(self, enemies):
        from battle.battle_encounter import BattleEncounter
        encounter = BattleEncounter.__new__(BattleEncounter)
        pet = SimpleNamespace(level=1, stage=3, add_experience=mock.Mock(), finish_battle=mock.Mock())
        encounter.pvp_mode = False
        encounter.victory_status = "Victory"
        encounter.get_battle_effect = lambda name: None
        encounter.battle_player = SimpleNamespace(team1=[pet], team2=enemies, xp=0, bonus=0,
                                                  level_up=[False])
        encounter.global_battle_log = SimpleNamespace(device1_final=[SimpleNamespace(alive=True)])
        self.module.battle_sequential_rounds = True
        self.module.items = [SimpleNamespace(name="Meat", id="meat")]
        encounter.module = self.module
        encounter.boss, encounter.round, encounter.area = False, 1, 1
        encounter.is_special_encounter = False
        encounter.frame_counter = 0
        return encounter

    def test_a_pack_prize_opens(self):
        won = self.encounter([self.enemy(prize_card_pack="p1")])
        won.process_battle_results()
        self.assertEqual(won.prize_pack["name"], "Starter Pack")
        self.assertIsNone(won.prize_item)
        self.assertTrue(won._has_result_rewards())

    def test_the_chance_is_rolled_for_items_and_packs(self):
        enemies = [self.enemy(prize="Meat", prize_chance=30), self.enemy(prize_card_pack="p1",
                                                                          prize_chance=30)]
        with mock.patch("battle.battle_encounter.random.random", return_value=0.5), \
                mock.patch("utils.inventory_utils.add_to_inventory") as added:
            missed = self.encounter(enemies)
            missed.process_battle_results()
        self.assertIsNone(missed.prize_item)
        self.assertIsNone(missed.prize_pack)
        added.assert_not_called()
        with mock.patch("battle.battle_encounter.random.random", return_value=0.29), \
                mock.patch("battle.battle_encounter.random.choice", side_effect=lambda seq: seq[0]), \
                mock.patch("battle.battle_encounter.inventory_utils.add_to_inventory") as added:
            hit = self.encounter(enemies)
            hit.process_battle_results()
        self.assertEqual(hit.prize_item.name, "Meat")
        added.assert_called_once_with("meat", 1)

    def test_one_prize_is_drawn_from_all_the_enemies(self):
        enemies = [self.enemy(prize="Meat"), self.enemy(prize_card_pack="p1"), self.enemy()]
        seen = []

        def choose(seq):
            seen.append([kind for _e, kind, _v in seq])
            return seq[-1]
        with mock.patch("battle.battle_encounter.random.choice", side_effect=choose):
            won = self.encounter(enemies)
            won.process_battle_results()
        self.assertEqual(seen[0], ["item", "card_pack"])
        self.assertIsNotNone(won.prize_pack)
        self.assertIsNone(won.prize_item, "only the drawn prize is given")


if __name__ == "__main__":
    unittest.main()
