"""A jogress route's own requirements on the pet that owns it (2026-10-15).

Pendulum Z pairs the same two Digimon for two results: Gatomon with Aquilamon
gives Angewomon + Hippogriffomon at Level 1-5 (each keeps its own result, a
Dual jogress) and Silphymon at Level 6 (one Digimon). The `level` on those
routes was ignored, so the first route for the partner always won and the
Level 6 one could never happen; VBE's Examon routes ask for an area the same
way, and the Pendulum Color's same-attribute pairs a version's Slot 6/7 unlock
(reachable_routes_20261015.py). find_route and the serial jogress
(battle.sim.jogress_roms) both check them now. The PENZ pairs are
cross-version and name the partner's version (fix_jogress_partners_20261015.py).
"""
import json
import os
import sys
import unittest
from types import SimpleNamespace

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SRC = os.path.join(REPO_ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
MODULES = os.path.join(REPO_ROOT, "modules")

from utils.jogress_utils import compatible, find_route, is_dual, normalize_evolutions  # noqa: E402

GATOMON = [{"to": "Angewomon", "level": [1, 5], "jogress": "Dual", "jogress_name": "Aquilamon", "jogress_version": 4},
           {"to": "Angewomon", "mistakes": [0, 2], "level": [4, 10]},
           {"to": "Silphymon", "level": [6, 10], "jogress": "Single", "jogress_name": "Aquilamon", "jogress_version": 4}]


def pet(name, version, level, evolve=(), area=0, module="PENZ"):
    return SimpleNamespace(name=name, version=version, level=level, area=area, stage=4,
                           attribute="", module=module, evolve=list(evolve))


class OwnerLevel(unittest.TestCase):
    def test_level_picks_the_route(self):
        partner = pet("Aquilamon", 4, 1)
        self.assertEqual(find_route(pet("Gatomon", 1, 3, GATOMON), partner)["to"], "Angewomon")
        self.assertEqual(find_route(pet("Gatomon", 1, 6, GATOMON), partner)["to"], "Silphymon")

    def test_outside_every_level_there_is_no_jogress(self):
        gatomon = pet("Gatomon", 1, 0, GATOMON)
        self.assertIsNone(find_route(gatomon, pet("Aquilamon", 4, 1)))
        self.assertFalse(compatible(gatomon, pet("Aquilamon", 4, 1)))

    def test_area(self):
        route = [{"to": "Examon", "area": 6, "jogress": "Single", "jogress_name": "Breakdramon"}]
        partner = pet("Breakdramon", 6, 0, module="VBE")
        self.assertIsNone(find_route(pet("Slayerdramon", 6, 0, route, area=5, module="VBE"), partner))
        self.assertIsNotNone(find_route(pet("Slayerdramon", 6, 0, route, area=6, module="VBE"), partner))

    def test_unlock(self):
        from unittest.mock import patch
        from core import game_globals
        routes = [{"to": "GrandGalemon", "unlock": "slot7_wgu", "jogress": "Dual", "jogress_stage": 4, "jogress_attribute": "Da"},
                  {"to": "Lillymon", "jogress": "Dual", "jogress_stage": 4, "jogress_attribute": "Da"}]
        kiwimon, partner = pet("Kiwimon", 4, 1, routes, module="PENC"), pet("Monochromon", 1, 1, module="PENC")
        partner.attribute = "Da"
        with patch.object(game_globals, "unlocks", {"PENC": []}):
            self.assertEqual(find_route(kiwimon, partner)["to"], "Lillymon")
        with patch.object(game_globals, "unlocks", {"PENC": [{"type": "versus", "name": "slot7_wgu"}]}):
            self.assertEqual(find_route(kiwimon, partner)["to"], "GrandGalemon")

    def test_serial_jogress_reads_it_too(self):
        from battle.sim import jogress_roms
        roster = [{"name": "Aquilamon", "version": 4, "index": 12}]
        partner = {"version": 4, "index": 12, "stage": 4, "attribute": "Free"}
        low, high = pet("Gatomon", 1, 3, GATOMON), pet("Gatomon", 1, 7, GATOMON)
        self.assertEqual(jogress_roms.matching_route(low, partner, roster)["to"], "Angewomon")
        self.assertEqual(jogress_roms.matching_route(high, partner, roster)["to"], "Silphymon")


@unittest.skipUnless(os.path.isdir(os.path.join(MODULES, "PENZ")), "modules folder not present")
class PendulumZPairs(unittest.TestCase):
    """The module's cross-version pairs find each other both ways."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(MODULES, "PENZ", "monster.json"), encoding="utf-8-sig") as f:
            cls.records = {(m["name"], m["version"]): m for m in json.load(f)["monster"]}

    def pet(self, name, version, level):
        record = self.records[(name, version)]
        return pet(name, version, level, normalize_evolutions(record.get("evolve") or []))

    def test_pairs(self):
        # (owner, partner, level 1-5 results, level 6 result)
        for a, b, low, high in ((("Gatomon", 1), ("Aquilamon", 4), ("Angewomon", "HippoGryphonmon"), "Silphymon"),
                                (("Ankylomon", 2), ("Angemon", 6), ("MarineChimairamon", "MagnaAngemon"), "Shakkoumon"),
                                (("Stingmon", 3), ("ExVeemon", 5), ("Dinobeemon", "Dinobeemon"), "Paildramon")):
            with self.subTest(a=a, b=b):
                first, second = self.pet(*a, 3), self.pet(*b, 3)
                there, back = find_route(first, second), find_route(second, first)
                self.assertEqual((there["to"], back["to"]), low)
                self.assertEqual(is_dual(there), low[0] != low[1])
                first, second = self.pet(*a, 6), self.pet(*b, 6)
                self.assertEqual(find_route(first, second)["to"], high)
                self.assertEqual(find_route(second, first)["to"], high)


if __name__ == "__main__":
    unittest.main()
