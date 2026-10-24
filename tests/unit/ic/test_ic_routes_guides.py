"""iC evolution routes against the guides (2026-10-16).

The 10X follows the official Master Book's four evolution charts, its gates
20 and 50 wins on the record kept through the forms; the 20X follows File
Island, with MetalGarurumon and Barbamon (File Island's "??? DigiSoul") as
the owner read them. utilities/IC/check_routes_fileisland.py compares every
route at the Reliability band edges, for each leading DigiSoul and none.

The egg's own DigiSoul Plate, given when the egg is started and scanned again
at each stage, carries a Digimon from Baby I to an Ultimate (owner: "that
should unlock at least one evolution line beginning to end").
"""
import importlib.util
import io
import json
import os
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
MODULE = os.path.join(REPO_ROOT, "modules", "IC")
CHECKER = os.path.join(REPO_ROOT, "utilities", "IC", "check_routes_fileisland.py")


def load(name):
    with io.open(os.path.join(MODULE, name), encoding="utf-8-sig") as fh:
        return json.load(fh)


@unittest.skipUnless(os.path.isdir(MODULE) and os.path.exists(CHECKER), "IC module or its checker not present")
class Guides(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("check_routes_fileisland", CHECKER)
        cls.checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.checker)
        cls.checker.BOOK = True
        cls.monsters = load("monster.json")["monster"]

    def differences(self, version):
        out = []
        spec = self.checker.SPECS[version]
        for m in self.monsters:
            if m["version"] != version or m["stage"] == 0 or spec(m["name"], 31, "Dragon") is None:
                continue
            for r in self.checker.LEVELS:
                for lead in (None,) + self.checker.TYPES:
                    want = spec(m["name"], r, lead)
                    got = self.checker.module_outcomes(m.get("evolve") or [], r, lead, set())
                    if want != got:
                        out.append((m["name"], r, lead, sorted(map(str, want)), sorted(map(str, got))))
        return out

    def test_10x_is_the_master_book(self):
        self.assertEqual(self.differences(1), [])

    def test_20x_is_file_island(self):
        self.assertEqual(self.differences(2), [])

    def test_10x_gates_are_wins_on_the_kept_record(self):
        self.assertTrue(load("module.json").get("battle_keep_counts_on_evolution"))
        gates = {(m["stage"], k, tuple(e[k])) for m in self.monsters if m["version"] == 1
                 for e in m.get("evolve") or [] for k in ("battles", "win_count") if k in e}
        self.assertEqual(gates, {(4, "win_count", (20, 999999)), (5, "win_count", (50, 999999))})


@unittest.skipUnless(os.path.isdir(MODULE), "IC module not present")
class EggPlateLine(unittest.TestCase):
    def plate_dna(self, version):
        """The DigiSoul the version's egg plate charges (a DigiSoul Charge row)."""
        cards = load("cards.json")
        by_id = {c["id"]: c for c in cards["cards"]}
        plate = next(by_id[u["card"]] for u in load("module.json")["unlocks"]
                     if u.get("type") == "egg" and u.get("card") and u.get("version") == version)
        for group in cards["effects"]:
            if group.get("tool") == "DigiSoul Charge" and group.get("value") == plate["value"]:
                for e in group["effects"]:
                    if e.get("type") == "DNA" and e.get("version", -1) in (version, -1):
                        return e["dna"]
        self.fail("no DigiSoul Charge row for %s" % plate["name"])

    def walk(self, version):
        records = {m["name"]: m for m in load("monster.json")["monster"] if m["version"] == version}
        dna = self.plate_dna(version)
        form = next(m for m in records.values() if m["stage"] == 0)["evolve"][0]["to"]
        line = [form]
        while records[form].get("evolve"):
            route = next((e for e in records[form]["evolve"]
                          if "chance" not in e and dna in (e.get("digisoul_dna") or [dna])
                          and e.get("reliability", [0, 31])[0] <= 25 <= e.get("reliability", [0, 31])[1]), None)
            if route is None:
                break
            form = route["to"]
            line.append(form)
        return dna, line, records[form]["stage"]

    def test_the_egg_plate_reaches_an_ultimate(self):
        for version in (1, 2):
            dna, line, stage = self.walk(version)
            self.assertEqual(stage, 6, "v%d on %s stops at %s" % (version, dna, " > ".join(line)))


if __name__ == "__main__":
    unittest.main()
