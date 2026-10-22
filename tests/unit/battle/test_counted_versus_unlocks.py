"""Counted connection unlocks (MOD-13; owner, 2026-10-15).

A `versus` unlock can need several qualifying connection battles (`amount`),
fought on one battle format (`protocol`) against given devices
(`opponent_device_versions`), or several different devices (`distinct`), and
can count won battles only (`outcome: win`). Without these fields one battle
grants it, as before. utils_unlocks.record_connection_battle does the
counting for Versus and DCom; the counts live in game_globals.versus_progress.

The data: PENGZ's eight backgrounds (3-20 battles against a Pendulum Color),
DMGZ's five (3-15 against a standard DMC), DMC's File Island (all 4 other
versions), the iC's DigiShops (a win).
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
from utils import utils_unlocks  # noqa: E402
from utils.utils_unlocks import record_connection_battle, versus_record_matches  # noqa: E402


def side(device_version, version=1):
    return {"device_version": device_version, "version": version}


class Case(unittest.TestCase):
    def setUp(self):
        self.modules = {}
        patches = [
            patch.object(runtime_globals, "game_modules", self.modules),
            patch.object(runtime_globals, "game_message", Mock(), create=True),
            patch.object(runtime_globals, "game_console", Mock(), create=True),
            patch.object(game_globals, "unlocks", {}),
            patch.object(game_globals, "versus_progress", {}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def module(self, name, unlocks):
        self.modules[name] = SimpleNamespace(name=name, unlocks=unlocks)

    def held(self, module, name):
        return utils_unlocks.is_unlocked(module, "versus", name)

    def battle(self, module, own, opp, won=True, fmt="PENC"):
        return record_connection_battle(module, [(own, opp, won)], fmt)


class Counting(Case):
    def test_an_amount_needs_that_many_qualifying_battles(self):
        self.module("PENGZ", [{"name": "lakeside", "type": "versus", "protocol": "PENC",
                               "opponent_device_versions": list(range(9)), "amount": 3}])
        for n in range(2):
            self.battle("PENGZ", side(8), side(n))
            self.assertFalse(self.held("PENGZ", "lakeside"), n)
        self.battle("PENGZ", side(8), side(5), won=False)       # any outcome
        self.assertTrue(self.held("PENGZ", "lakeside"))

    def test_another_protocol_or_device_does_not_count(self):
        self.module("DMGZ", [{"name": "grasslands", "type": "versus", "protocol": "DMC",
                              "opponent_device_versions": [0, 1, 2, 3, 4], "amount": 2}])
        self.battle("DMGZ", side(5), side(2), fmt="PENC")        # not the DMC wire
        self.battle("DMGZ", side(5), side(5), fmt="DMC")         # a crossover, not a standard DMC
        self.assertEqual(game_globals.versus_progress, {})
        self.battle("DMGZ", side(5), side(0), fmt="DMC")
        self.battle("DMGZ", side(5), side(0), fmt="dmc")
        self.assertTrue(self.held("DMGZ", "grasslands"))

    def test_distinct_counts_other_devices_once_each(self):
        self.module("DMC", [{"name": "file_island", "type": "versus", "protocol": "DMC",
                             "opponent_device_versions": [0, 1, 2, 3, 4], "distinct": True, "amount": 4}])
        for opp in (0, 1, 1, 2, 2, 3):                           # 0 is the pet's own
            self.battle("DMC", side(0), side(opp), fmt="DMC")
        self.assertFalse(self.held("DMC", "file_island"))
        self.battle("DMC", side(0), side(4), fmt="DMC")
        self.assertTrue(self.held("DMC", "file_island"))

    def test_outcome_win_needs_a_win(self):
        self.module("IC", [{"name": "digishop_1", "type": "versus", "opponent_device_version": 1,
                            "outcome": "win"}])
        self.battle("IC", side(0), side(1), won=False, fmt="IC")
        self.assertFalse(self.held("IC", "digishop_1"))
        self.battle("IC", side(0), side(1), won=True, fmt="IC")
        self.assertTrue(self.held("IC", "digishop_1"))

    def test_species_on_each_side(self):
        # PEN20: a Jesmon must beat an Alphamon (humulos, "Battle With").
        self.module("PEN20", [{"name": "jesmon_x", "type": "versus", "outcome": "win",
                               "own_names": ["Jesmon"], "opponent_names": ["Alphamon"]}])
        jesmon, alphamon, other = (dict(side(9, 9), name="Jesmon"), dict(side(19, 19), name="Alphamon"),
                                   dict(side(19, 19), name="Ouryumon"))
        self.battle("PEN20", jesmon, other, fmt="PEN20")
        self.battle("PEN20", alphamon, jesmon, fmt="PEN20")       # Alphamon won
        self.battle("PEN20", dict(jesmon, name=None), alphamon, fmt="PEN20")
        self.assertFalse(self.held("PEN20", "jesmon_x"))
        record_connection_battle("PEN20", [(jesmon, alphamon, True), (alphamon, jesmon, False)], "PEN20")
        self.assertTrue(self.held("PEN20", "jesmon_x"))

    def test_records_sharing_a_requirement_count_together(self):
        self.module("DMGZ", [{"name": n, "type": "versus", "protocol": "DMC",
                              "opponent_device_versions": [0], "amount": a}
                             for n, a in (("grasslands", 3), ("desert", 6))])
        for _ in range(3):
            self.battle("DMGZ", side(5), side(0), fmt="DMC")
        self.assertTrue(self.held("DMGZ", "grasslands"))
        self.assertFalse(self.held("DMGZ", "desert"))
        for _ in range(3):
            self.battle("DMGZ", side(5), side(0), fmt="DMC")
        self.assertTrue(self.held("DMGZ", "desert"))


class OldRecords(Case):
    """Without the new fields a record behaves as before: one battle."""

    def test_pairs_any_other_device_and_versions(self):
        self.module("PENC", [
            {"name": "shambala_sky", "type": "versus", "device_version": 6, "opponent_device_version": 7},
            {"name": "slot6_nsp", "type": "versus", "device_version": 1, "opponent_device_version": -1},
            {"name": "sp_area", "type": "versus", "version": 3},
        ])
        record_connection_battle("PENC", [(side(6), side(7), True)])
        record_connection_battle("PENC", [(side(1), side(1), True)])        # its own version
        self.assertTrue(self.held("PENC", "shambala_sky"))
        self.assertFalse(self.held("PENC", "slot6_nsp"))
        record_connection_battle("PENC", [(side(1), side(4), False)])
        self.assertTrue(self.held("PENC", "slot6_nsp"))
        record_connection_battle("PENC", [(side(2, 2), side(4), True), (side(4, 3), side(2, 2), False)])
        self.assertTrue(self.held("PENC", "sp_area"))                     # either pet's version
        self.assertEqual(game_globals.versus_progress, {})

    def test_matching_rules(self):
        record = {"name": "x", "type": "versus", "opponent_device_version": -1}
        self.assertFalse(versus_record_matches(record, side(2), side(None)))
        self.assertTrue(versus_record_matches(record, side(2), side(3)))


class VersusEncounter(Case):
    """BattleEncounterVersus._record_versus_unlocks: same-module pets count once
    either way round; pets of two modules count only for protocol records."""

    def run_versus(self, pet1, pet2, winner, fmt):
        from battle.battle_encounter_versus import BattleEncounterVersus
        encounter = SimpleNamespace(pet1=pet1, pet2=pet2, battle_format=fmt)
        BattleEncounterVersus._record_versus_unlocks(encounter, winner)

    def test_two_modules(self):
        self.module("PENGZ", [{"name": "lakeside", "type": "versus", "protocol": "PENC",
                               "opponent_device_versions": list(range(9)), "amount": 1},
                              {"name": "old", "type": "versus"}])
        self.module("PENC", [{"name": "any", "type": "versus"}])
        gz = SimpleNamespace(module="PENGZ", version=1, device_version=8)
        pc = SimpleNamespace(module="PENC", version=3, device_version=3)
        self.run_versus(gz, pc, pc, "PENC")
        self.assertTrue(self.held("PENGZ", "lakeside"))
        self.assertFalse(self.held("PENGZ", "old"))       # same-module only, as before
        self.assertFalse(self.held("PENC", "any"))

    def test_one_module_counts_once(self):
        self.module("DMC", [{"name": "file_island", "type": "versus", "protocol": "DMC",
                             "opponent_device_versions": [0, 1, 2, 3, 4], "distinct": True, "amount": 2}])
        one = SimpleNamespace(module="DMC", version=1, device_version=0)
        two = SimpleNamespace(module="DMC", version=2, device_version=1)
        self.run_versus(one, two, one, "DMC")
        progress = list(game_globals.versus_progress["DMC"].values())[0]
        self.assertEqual(progress["battles"], 1)


class SaveTests(unittest.TestCase):
    def test_versus_progress_is_saved(self):
        import inspect
        source = inspect.getsource(game_globals)
        self.assertIn('"versus_progress": versus_progress', source)
        self.assertIn('versus_progress = data.get("versus_progress"', source)


@unittest.skipUnless(os.path.isdir(MODULES), "modules folder not present")
class ModuleData(unittest.TestCase):
    def unlocks(self, module):
        with open(os.path.join(MODULES, module, "module.json"), encoding="utf-8-sig") as f:
            return {u["name"]: u for u in json.load(f)["unlocks"] if u.get("type") == "versus"}

    def test_the_manuals_counts(self):
        pengz, dmgz = self.unlocks("PENGZ"), self.unlocks("DMGZ")
        self.assertEqual({n: pengz[n]["amount"] for n in ("lakeside", "underwater", "castle", "flower_field",
                                                          "factories", "sky", "genshi_continent", "ashino_island")},
                         dict(lakeside=3, underwater=5, castle=8, flower_field=10, factories=12, sky=15,
                              genshi_continent=18, ashino_island=20))
        self.assertTrue(all(pengz[n]["protocol"] == "PENC" for n in ("lakeside", "ashino_island")))
        self.assertEqual({n: dmgz[n]["amount"] for n in ("grasslands", "desert", "forest", "mountains", "beach")},
                         dict(grasslands=3, desert=6, forest=9, mountains=12, beach=15))
        self.assertEqual(dmgz["grasslands"]["opponent_device_versions"], [0, 1, 2, 3, 4])
        island = self.unlocks("DMC")["file_island"]
        self.assertEqual((island["amount"], island.get("distinct")), (4, True))
        self.assertTrue(all(u.get("outcome") == "win" for n, u in self.unlocks("IC").items()
                            if n.startswith("digishop_")))


if __name__ == "__main__":
    unittest.main()
