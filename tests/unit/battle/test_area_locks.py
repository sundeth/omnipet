"""Areas locked behind an unlock (`unlocks_area`; MOD-13, BAT-04).

A locked area with a later area after it is a side area: clearing the area
before it moves progress past it, and it opens, among the areas already
passed, once its unlock is held (DW1, 2026-10-20: World's Beetle Land opens
with Seadramon, Factorial Town with Whamon's ferry). A locked LAST area is
not moved into (PENGZ's Stage F and Omega, opened together by an
evolution). battle_encounter.BattleEncounter._next_open_area decides it.

DW1's recruits each give something as they join (owner, 2026-10-20): their
own card as a shiny copy, or a Card Pack where World has no card of them.
"""
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SRC = os.path.join(REPO_ROOT, "src")
for path in (SRC, REPO_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)
MODULES = os.path.join(REPO_ROOT, "modules")

from core import game_globals, runtime_globals  # noqa: E402
from models.game_module import GameModule  # noqa: E402
from battle.battle_encounter import BattleEncounter  # noqa: E402


def load(module, name):
    with open(os.path.join(MODULES, module, name), encoding="utf-8-sig") as fh:
        return json.load(fh)


def fake_module(name, unlocks, areas):
    """The module's own lock logic over *unlocks*, with adventure *areas*."""
    module = SimpleNamespace(name=name, unlocks=unlocks)
    module.get_area_locks = lambda: GameModule.get_area_locks(module)
    module.is_area_unlocked = lambda area, version=None: GameModule.is_area_unlocked(module, area, version)
    module.area_exists = lambda area: area in areas
    return module


class Case(unittest.TestCase):
    def setUp(self):
        for p in (patch.object(game_globals, "unlocks", {}),
                  patch.object(runtime_globals, "game_console", Mock(), create=True)):
            p.start()
            self.addCleanup(p.stop)

    def hold(self, module, name):
        game_globals.unlocks.setdefault(module, []).append({"type": "encounter", "name": name})

    def next_area(self, module, area, version=1):
        return BattleEncounter._next_open_area(SimpleNamespace(module=module, version=version), area)


class SideAreas(Case):
    UNLOCKS = [{"name": "ferry", "type": "encounter", "unlocks_area": 3},
               {"name": "last", "type": "encounter", "unlocks_area": 5}]

    def setUp(self):
        super().setUp()
        self.module = fake_module("TEST", self.UNLOCKS, {1, 2, 3, 4, 5})

    def test_a_locked_area_with_one_after_it_is_passed_by(self):
        self.assertEqual(self.next_area(self.module, 3), 4)

    def test_the_area_opens_once_its_unlock_is_held(self):
        self.hold("TEST", "ferry")
        self.assertEqual(self.next_area(self.module, 3), 3)

    def test_a_locked_last_area_is_not_moved_into(self):
        self.assertIsNone(self.next_area(self.module, 5))
        self.hold("TEST", "last")
        self.assertEqual(self.next_area(self.module, 5), 5)

    def test_no_area_after_the_last(self):
        self.assertIsNone(self.next_area(self.module, 6))


@unittest.skipUnless(os.path.isdir(os.path.join(MODULES, "DW1")), "DW1 not installed")
class DW1Recruits(Case):
    def setUp(self):
        super().setUp()
        self.unlocks = load("DW1", "module.json")["unlocks"]
        self.enemies = load("DW1", "battle.json")["enemies"]
        self.areas = {e["area"] for e in self.enemies if not e.get("special_encounter")}
        self.module = fake_module("DW1", self.unlocks, self.areas)

    def test_factorial_town_and_beetle_land_wait_for_their_recruits(self):
        gates = {u["name"]: u["unlocks_area"] for u in self.unlocks if u.get("unlocks_area")}
        self.assertEqual(gates, {"recruit_whamon_champion": 16, "recruit_seadramon": 18})
        self.assertEqual(self.next_area(self.module, 16), 17)
        self.assertEqual(self.next_area(self.module, 18), 19)
        self.hold("DW1", "recruit_whamon_champion")
        self.hold("DW1", "recruit_seadramon")
        self.assertEqual(self.next_area(self.module, 16), 16)
        self.assertEqual(self.next_area(self.module, 18), 18)

    def test_each_gate_recruit_is_met_before_its_area(self):
        for u in self.unlocks:
            if not u.get("unlocks_area"):
                continue
            met = [e["area"] for e in self.enemies if e.get("unlock") == u["name"]]
            self.assertTrue(met, f"{u['name']}: no enemy grants it")
            self.assertLess(min(met), u["unlocks_area"], f"{u['name']} is met only past its area")

    def test_every_recruit_gives_a_card_or_a_pack_and_something_to_drop(self):
        cards = load("DW1", "cards.json")
        ids = {c["id"] for c in cards["cards"]}
        packs = {p["id"] for p in cards["packs"]}
        by_name = {u["name"]: u for u in self.unlocks}
        for e in self.enemies:
            if not e.get("friend"):
                continue
            with self.subTest(recruit=e["name"]):
                unlock = by_name[e["unlock"]]
                self.assertTrue(unlock.get("card") in ids or unlock.get("card_pack") in packs,
                                "no card and no card pack")
                self.assertTrue(e.get("prize"), "drops nothing")


if __name__ == "__main__":
    unittest.main()
