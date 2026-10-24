"""Connect Points as a battle drop table (owner, 2026-10-21): the Vital
Bracelets had no shop, their apps' items came from play, so VB, VBE and VH
roll after every won battle instead of selling a "Stat Shop".

* ``connect_points.battles`` names the battles that give points:
  ``connection`` (another device or pet) and ``adventure``; absent, only
  connections (the iC's meter).
* A reward naming no item is a draw that gives nothing, so a cap of 1 with
  empty listings is a per-battle roll that can come up empty.
* A cap of 1 shows no meter on the status screen.
* The VB, VBE and VH data: no shop.json, cap 1, wins only, adventure and
  connection battles, every listed item in item.json, no evolution-timer
  item, about the BE's no-item share (111/200) of empty listings.
"""

import json
import os
import random
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

from core import runtime_globals  # noqa: E402
from utils import connect_points, event_utils  # noqa: E402

MODULES = os.path.join(REPO_ROOT, "modules")
VITAL_BRACELETS = ("VB", "VBE", "VH")
#: The former Stat Shop's items (vb_stat_shops_20261017.py): each must stay
#: obtainable as a drop.
FORMER_SHOP = (
    [f"{s}+{n}" for s in ("HP", "ATK", "POWER") for n in range(1, 6)]
    + ["HP Temp +5", "ATK Temp +1", "POWER Temp+5"]
    + [f"Vital Drink {s}" for s in ("S", "M", "L", "XL", "XXL", "MAX")]
    + [f"Battle Clock {s}" for s in ("S", "M", "L")])


def _pet(**fields):
    pet = SimpleNamespace(module="VB", name="Agumon", version=1, connect_points=0)
    pet.__dict__.update(fields)
    return pet


class FixedChoice:
    """An rng whose choice takes the *index*th listing."""

    def __init__(self, index):
        self.index = index

    def choice(self, seq):
        return seq[self.index]


class Quiet(unittest.TestCase):
    def setUp(self):
        for name, value in (("game_console", SimpleNamespace(log=Mock())),
                            ("game_message", None)):
            patcher = patch.object(runtime_globals, name, value, create=True)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _award(self, block, pet, won, battle="connection", rng=random):
        module = SimpleNamespace(name=pet.module, load_event_extras=lambda: {"connect_points": block})
        items = {"Vital Drink S": SimpleNamespace(id="vds"), "HP+1": SimpleNamespace(id="hp1")}
        with patch("utils.module_utils.get_module", return_value=module), \
                patch("utils.inventory_utils.get_item_by_name", side_effect=lambda m, n: items.get(n)), \
                patch("utils.inventory_utils.add_to_inventory") as add:
            name = connect_points.award(pet, won, rng=rng, battle=battle)
        return name, add


class BattlesTests(Quiet):
    def test_without_battles_only_connections_count(self):
        self.assertEqual(connect_points.battles({"cap": 15}), ("connection",))
        block = {"cap": 3, "win": 1, "loss": 1, "rewards": [{"item": "HP+1"}]}
        pet = _pet()
        self._award(block, pet, True, battle="adventure")
        self.assertEqual(pet.connect_points, 0, "an adventure battle gives the iC nothing")
        self._award(block, pet, True, battle="connection")
        self.assertEqual(pet.connect_points, 1)

    def test_named_battles_count(self):
        block = {"cap": 3, "win": 1, "loss": 1, "battles": ["adventure"],
                 "rewards": [{"item": "HP+1"}]}
        self.assertEqual(connect_points.battles(block), ("adventure",))
        pet = _pet()
        self._award(block, pet, True, battle="connection")
        self.assertEqual(pet.connect_points, 0)
        self._award(block, pet, True, battle="adventure")
        self.assertEqual(pet.connect_points, 1)

    def test_unknown_battle_names_fall_back_to_connections(self):
        self.assertEqual(connect_points.battles({"battles": ["arena"]}), ("connection",))
        self.assertEqual(connect_points.battles({"battles": "Adventure"}), ("adventure",))


class DropTests(Quiet):
    BLOCK = {"cap": 1, "win": 1, "loss": 0, "battles": ["adventure", "connection"],
             "rewards": [{"item": "Vital Drink S"}, {"item": ""}, {"item": ""}]}

    def test_an_empty_listing_is_a_draw_of_nothing(self):
        self.assertEqual(connect_points.rewards_for(self.BLOCK, 1), ["Vital Drink S", "", ""])
        pet = _pet()
        name, add = self._award(self.BLOCK, pet, True, rng=FixedChoice(1))
        self.assertEqual((name, pet.connect_points), ("", 0))
        add.assert_not_called()

    def test_a_cap_of_one_rolls_every_won_battle(self):
        pet = _pet()
        name, add = self._award(self.BLOCK, pet, True, battle="adventure", rng=FixedChoice(0))
        self.assertEqual((name, pet.connect_points), ("Vital Drink S", 0))
        add.assert_called_once_with("vds", 1)
        name, add = self._award(self.BLOCK, pet, False, battle="adventure", rng=FixedChoice(0))
        self.assertEqual((name, pet.connect_points), ("", 0), "a loss gives no point, no roll")
        add.assert_not_called()

    def test_the_odds_follow_the_listings(self):
        rng = random.Random(7)
        got = [self._award(self.BLOCK, _pet(), True, rng=rng)[0] for _ in range(600)]
        share = got.count("") / len(got)
        self.assertTrue(0.6 < share < 0.73, share)

    def test_a_drop_says_found_not_connect_points(self):
        message = SimpleNamespace(add_slide=Mock())
        with patch.object(runtime_globals, "game_message", message, create=True):
            self._award(self.BLOCK, _pet(), True, rng=FixedChoice(0))
            self._award({"cap": 2, "win": 2, "rewards": [{"item": "HP+1"}]}, _pet(), True)
        texts = [c.args[0] for c in message.add_slide.call_args_list]
        self.assertEqual(texts, ["Found Vital Drink S!", "Connect Points full: HP+1!"])

    def test_the_meter_needs_a_cap_above_one(self):
        self.assertFalse(connect_points.shows_meter(self.BLOCK))
        self.assertFalse(connect_points.shows_meter({}))
        self.assertTrue(connect_points.shows_meter({"cap": 15}))


class AfterAdventureTests(Quiet):
    def test_adventure_battles_award_then_roll_the_events(self):
        pets = [_pet(), _pet(module="DMC")]
        with patch.object(connect_points, "award", return_value="") as award, \
                patch.object(event_utils, "after_battle", return_value=["x"]) as after:
            done = event_utils.after_adventure("VB", pets, True, area=3)
        self.assertEqual(done, ["x"])
        self.assertEqual([c.args for c in award.call_args_list], [(pets[0], True), (pets[1], True)])
        self.assertTrue(all(c.kwargs == {"battle": "adventure"} for c in award.call_args_list))
        after.assert_called_once_with("adventure", "VB", pets, True, area=3)

    def test_connections_award_as_connections(self):
        pet = _pet()
        with patch.object(connect_points, "award", return_value="") as award, \
                patch.object(event_utils, "after_battle", return_value=[]):
            event_utils.after_connection([(pet, False)], 1, battle_format="DMC")
        award.assert_called_once_with(pet, False, battle="connection")


def _module_json(module, name):
    path = os.path.join(MODULES, module, name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


@unittest.skipUnless(os.path.isdir(MODULES), "modules/ is not installed")
class VitalBraceletDataTests(unittest.TestCase):
    def test_no_shop_and_a_drop_table(self):
        for module in VITAL_BRACELETS:
            events, items = _module_json(module, "events.json"), _module_json(module, "item.json")
            if events is None or items is None:
                continue
            with self.subTest(module=module):
                self.assertFalse(os.path.exists(os.path.join(MODULES, module, "shop.json")),
                                 "the bracelets had no shop")
                block = events.get("connect_points") or {}
                self.assertEqual((block.get("cap"), block.get("win"), block.get("loss")), (1, 1, 0))
                self.assertEqual(set(connect_points.battles(block)), {"adventure", "connection"})
                by_name = {i["name"]: i for i in items["item"]}
                listed = [r.get("item") or "" for r in block.get("rewards") or []]
                for name in filter(None, listed):
                    self.assertIn(name, by_name)
                    self.assertNotEqual(by_name[name].get("status"), "timer",
                                        f"{name} is an evolution-timer item")
                self.assertEqual(set(filter(None, listed)), set(FORMER_SHOP),
                                 "every former Stat Shop item, nothing else")
                nothing = listed.count("") / len(listed)
                self.assertAlmostEqual(nothing, 111 / 200, delta=0.02)

    def test_vb_still_accepts_its_stat_items(self):
        vb = _module_json("VB", "module.json")
        if vb is not None:
            self.assertGreater(vb["hp_max_item_boost"], 0, "VB's HP+ items were always refused")


if __name__ == "__main__":
    unittest.main()
