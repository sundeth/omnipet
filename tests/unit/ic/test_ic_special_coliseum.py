# -*- coding: utf-8 -*-
"""The iC 20X's Special Coliseum after a connection (IC 24, owner,
2026-10-22): its line-ups are three opponents of one Field.

Seen by the owner: Bird Falcomon > Peckmon > Ravemon, Water Kamemon >
Gawappamon > JumboGamemon, Holy Kudamon > Reppamon > Chirinmon; "any other
combination as long as the 3 stages are the same field" is assumed, and the
reward does not follow the Field. utilities/IC/apply_ic_events.py builds a
battle run (event type 4) for each Field that has a Child and an Adult on the
20X, in an area of its own (6 + the Field's place in the eight), whose round
3 lists the Field's Perfect and Ultimate. The runs share the Coliseum's 20 in
the hundred of the after-battle draw.

Owner, 2026-10-23: the filmed Elecmon > Bakemon > LoaderLeomon run was
probably misread and is gone (every trio is one Field); the reward is random,
any of the Attack +2 weapons, whatever the line-up (``item_pool``); only a win
brings a run or a one-visit shop.
"""
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ic_fixtures import MODULES, ICCase  # noqa: E402

#: Field -> (area, Child, Adult, round-3 candidates); the seen last one first.
LINEUPS = {
    "Water": (9, "Kamemon", "Gawappamon", ("JumboGamemon", "Shaujinmon")),
    "Bird": (10, "Falcomon", "Peckmon", ("Ravemon", "Crowmon")),
    "Holy": (12, "Kudamon", "Reppamon", ("Chirinmon", "Kentaurosmon")),
}
#: The filmed run's old area (removed 2026-10-23).
FILMED_AREA = 5
#: Every Attack +2 weapon: the eight Field ones and Metal Armor.
REWARDS = {"Dragon Break", "Beast Blow", "Water Cure", "Fowl Buraiga", "Jungle Enemis", "Holy Saber",
           "Dark Destroy", "Metal Axe", "Metal Armor"}


def runs(module):
    return [e for e in module.load_events_json() if int(e.type or 0) == 4]


class SpecialColiseumData(ICCase):
    def test_one_run_a_field_shares_the_twenty(self):
        found = {e.name: e for e in runs(self.ic)}
        self.assertEqual(set(found), {"Special Coliseum (%s)" % f for f in LINEUPS})
        self.assertAlmostEqual(sum(float(e.chance_percent) for e in found.values()), 20, places=2)
        for field, (area, *_rest) in LINEUPS.items():
            self.assertEqual(found["Special Coliseum (%s)" % field].area, area)
        for event in found.values():
            with self.subTest(event=event.name):
                self.assertEqual((event.trigger, event.outcome, event.draw, list(event.versions)),
                                 ("connection", "win", "after battle", [2]))
                self.assertEqual((event.item, set(event.item_pool)), ("", REWARDS),
                                 "the reward does not follow the Field")

    def test_the_pool_is_the_attack_plus_two_weapons(self):
        data = json.load(open(os.path.join(MODULES, "IC", "item.json"), encoding="utf-8-sig"))
        items = {i["name"]: i for i in data["item"]}
        plus_two = {n for n, i in items.items() if i.get("effect") == "status_boost" and i.get("amount") == 2}
        self.assertEqual(plus_two, REWARDS)

    def test_each_field_run_is_child_adult_then_perfect_or_ultimate_of_its_field(self):
        records = {m["name"]: m for m in self.ic.get_all_monsters() if m.get("version") == 2}
        for field, (area, child, adult, last) in LINEUPS.items():
            with self.subTest(field=field):
                rounds = {}
                for row in self.enemies(area):
                    rounds.setdefault(row["round"], set()).add(row["name"])
                self.assertEqual(rounds, {1: {child}, 2: {adult}, 3: set(last)})
                for name in [child, adult, *last]:
                    self.assertEqual(records[name]["digisoul"], field, name)
                self.assertEqual([records[n]["stage"] for n in (child, adult)], [3, 4])
                self.assertEqual(sorted(records[n]["stage"] for n in last), [5, 6])

    def test_the_rows_carry_their_records_strength(self):
        records = {m["name"]: m for m in self.ic.get_all_monsters() if m.get("version") == 2}
        for field, (area, *_rest) in LINEUPS.items():
            for row in self.enemies(area):
                with self.subTest(name=row["name"]):
                    record = records[row["name"]]
                    self.assertEqual((row["power"], row["stage"], row["version"]),
                                     (record["power"], record["stage"], 2))
                    self.assertTrue(row["special_encounter"])
                    self.assertEqual(row["atk_alt"], 1 if row["stage"] >= 5 else 0)
                    self.assertFalse(self.ic.area_exists(area), "no adventure round there")

    def test_the_filmed_run_is_gone(self):
        self.assertEqual(self.enemies(FILMED_AREA), [])
        self.assertNotIn("Special Coliseum", [e.name for e in self.ic.load_events_json()])

    # ------------------------------------------------------------- helpers
    def enemies(self, area):
        data = json.load(open(os.path.join(MODULES, "IC", "battle.json"), encoding="utf-8"))
        return [e for e in data["enemies"] if e.get("special_encounter") and e.get("area") == area]


class SpecialColiseumPlay(ICCase):
    def test_a_run_never_mixes_fields(self):
        """Round 3 meets either candidate at random; rounds 1 and 2 have one."""
        for field, (area, child, adult, last) in LINEUPS.items():
            for pick in (0, -1):
                with self.subTest(field=field, pick=pick), \
                        patch("models.game_module.random.choice", side_effect=lambda seq: seq[pick]):
                    met = [self.ic.get_enemies(area, round_, [2], special_encounter=True)[0].name
                           for round_ in (1, 2, 3)]
                    self.assertEqual(met[:2], [child, adult])
                    self.assertIn(met[2], last)

    def test_the_after_battle_draw_starts_each_run(self):
        """Against a Burst (wire 2) no DigiShop is in the draw: a win meets the
        runs' thirds of the 20, in events.json's order, each paying a pool
        weapon."""
        from utils import event_utils
        found = runs(self.ic)
        start = 0.0
        for event in found:
            with self.subTest(run=event.name):
                self.gg.event = None
                with patch("random.random", return_value=(start + 1) / 100):
                    event_utils.after_connection([(self.pet(version=2, stage=4), True)], 2, battle_format="IC")
                self.assertEqual(self.gg.event.name, event.name)
                self.assertEqual(self.gg.event.round, 1)
                self.assertIn(self.gg.event.item, REWARDS)
            start += float(event.chance_percent)
        self.gg.event = None
        with patch("random.random", return_value=0.25):           # past the 20
            event_utils.after_connection([(self.pet(version=2, stage=4), True)], 2, battle_format="IC")
        self.assertIsNone(self.gg.event)

    def test_a_loss_brings_no_run_and_no_shop(self):
        from utils import event_utils
        for device in (1, 2):
            with self.subTest(device=device):
                self.gg.event = None
                with patch("random.random", return_value=0.01):
                    event_utils.after_connection([(self.pet(version=2, stage=4), False)], device,
                                                 battle_format="IC")
                self.assertIsNone(self.gg.event)

    def test_the_reward_is_drawn_from_the_pool(self):
        from utils import event_utils
        pool = runs(self.ic)[0].item_pool
        for pick in (0, -1):
            with self.subTest(pick=pick):
                self.gg.event = None
                with patch("random.random", return_value=0.01),                         patch("random.choice", side_effect=lambda seq: seq[pick]):
                    event_utils.after_connection([(self.pet(version=2, stage=4), True)], 2, battle_format="IC")
                self.assertEqual(self.gg.event.item, pool[pick])

    def test_a_20x_opponent_opens_digishop_6_or_7(self):
        """A win against a 20X (wire 1) draws DigiShop 6 or 7 before the
        runs (owner, 2026-10-23), 15 in the hundred each (placeholders)."""
        from utils import event_utils
        for value, shop in ((0.01, "DigiShop 6"), (0.16, "DigiShop 7")):
            with self.subTest(shop=shop):
                self.gg.event = None
                with patch("random.random", return_value=value):
                    event_utils.after_connection([(self.pet(version=2, stage=4), True)], 1,
                                                 battle_format="IC")
                self.assertEqual(self.gg.event.name, shop)

    def test_a_10x_pet_gets_no_run(self):
        from utils import event_utils
        with patch("random.random", return_value=0.01):
            event_utils.after_connection([(self.pet(version=1, stage=4), True)], 1, battle_format="IC")
        self.assertIsNone(self.gg.event)


if __name__ == "__main__":
    unittest.main()
