"""Route criterion `unlock` (owner, 2026-10-15): a held module unlock.

A route's `area` is the furthest area *this* pet has won in, so a form that
cannot battle could never meet it. DMGZ's Koromon had four area-7 routes; on
the device they mean area 7 was cleared before, by another Digimon. They now
need the `adventure` unlock clearing area 7 grants, and the same goes for
VBE's eggs and Baby II (area_unlock_routes_20261015.py). GamePet and the
Android copy share the check (utils.evolution_rules.extra_criteria_fail).
"""
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SRC = os.path.join(REPO_ROOT, "src")
for path in (SRC, REPO_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)
MODULES = os.path.join(REPO_ROOT, "modules")

from core import game_globals  # noqa: E402
from utils import evolution_rules  # noqa: E402

ROUTE = {"to": "Agumon", "mistakes": [2, 4], "unlock": "area_7_ver_1"}


class Criterion(unittest.TestCase):
    def test_the_game_reads_the_save(self):
        pet = SimpleNamespace(module="DMGZ")
        with patch.object(game_globals, "unlocks", {"DMGZ": []}):
            self.assertTrue(evolution_rules.extra_criteria_fail(pet, ROUTE, 0))
        with patch.object(game_globals, "unlocks", {"DMGZ": [{"type": "adventure", "name": "area_7_ver_1"}]}):
            self.assertFalse(evolution_rules.extra_criteria_fail(pet, ROUTE, 0))

    def test_the_android_copy_asks_its_world(self):
        held = set()
        world = SimpleNamespace(is_unlocked=lambda module, kind, name: (module, name) in held)
        pet = SimpleNamespace(module="DMGZ", world=world)
        self.assertTrue(evolution_rules.extra_criteria_fail(pet, ROUTE, 0))
        held.add(("DMGZ", "area_7_ver_1"))
        self.assertFalse(evolution_rules.extra_criteria_fail(pet, ROUTE, 0))

    def test_a_route_without_it_is_unaffected(self):
        pet = SimpleNamespace(module="DMGZ")
        with patch.object(game_globals, "unlocks", {"DMGZ": []}):
            self.assertFalse(evolution_rules.extra_criteria_fail(pet, {"to": "Agumon"}, 0))


@unittest.skipUnless(os.path.isdir(MODULES), "modules folder not present")
class ModuleData(unittest.TestCase):
    def load(self, module, name, key):
        with open(os.path.join(MODULES, module, name), encoding="utf-8-sig") as f:
            return json.load(f)[key]

    def test_no_form_that_cannot_battle_needs_an_area(self):
        for module in ("DMGZ", "VBE"):
            unlocks = {u["name"]: u for u in self.load(module, "module.json", "unlocks")}
            for m in self.load(module, "monster.json", "monster"):
                fights = (m.get("stage") or 0) >= 2 and m.get("power") and m.get("atk_main")
                for route in m.get("evolve") or []:
                    with self.subTest(module=module, form=m["name"], to=route.get("to")):
                        if not fights:
                            self.assertNotIn("area", route)
                        if route.get("unlock"):
                            unlock = unlocks[route["unlock"]]
                            self.assertEqual(unlock["type"], "adventure")
                            self.assertEqual(unlock["version"], m["version"])

    def test_koromon_waits_for_area_7(self):
        koromon = next(m for m in self.load("DMGZ", "monster.json", "monster") if m["name"] == "Koromon")
        self.assertEqual(sum(r.get("unlock") == "area_7_ver_1" for r in koromon["evolve"]), 4)
        unlock = next(u for u in self.load("DMGZ", "module.json", "unlocks") if u["name"] == "area_7_ver_1")
        self.assertEqual((unlock["type"], unlock["area"]), ("adventure", 7))


if __name__ == "__main__":
    unittest.main()
