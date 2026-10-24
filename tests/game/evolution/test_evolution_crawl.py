"""The evolution crawler (MOD-19, tests/release/evolution_crawl.py) on planted routes.

A real form (DMC's Agumon v1, DMX's Kentaurosmon (X Antibody)) is given
routes of the test's own, so each verdict is known: a route reached only by
moving past earlier ones, a requirement no player reaches, a copy of an earlier
route, a route a failed chance falls through to, an unlock nobody earns, VBE's
Vital Values against what a run without care mistakes earns, and DMX's
special-encounter pair (special_encounter false: "did not beat one", which
the game used to ignore).
"""
import os
import sys
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "support"))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "release"))
MODULES = os.path.join(REPO_ROOT, "modules")


@unittest.skipUnless(os.path.isdir(os.path.join(MODULES, "DMC")), "modules folder not present")
class Crawler(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness import Env
        cls.env = Env("240x240", fixture="empty")
        import evolution_crawl as crawl
        from models import game_pet
        # The crawler's stand-ins, put back afterwards: other test files can
        # share this process (pytest on several files).
        cls._saved = (game_pet.datetime, game_pet.GamePet.load_sprite, game_pet.register_digidex_entry)
        game_pet.datetime = crawl.FakeDatetime
        game_pet.GamePet.load_sprite = lambda self: None
        game_pet.register_digidex_entry = lambda *a, **k: None
        cls.crawl = crawl
        cls.ctx = {}

    @classmethod
    def tearDownClass(cls):
        from models import game_pet
        game_pet.datetime, game_pet.GamePet.load_sprite, game_pet.register_digidex_entry = cls._saved

    def verdict(self, module, name, version, routes, index):
        from harness import quiet
        crawl = self.crawl
        if module not in self.ctx:
            self.ctx[module] = crawl.Ctx(module, self.env.rg.game_modules[module])
        ctx = self.ctx[module]
        form = dict(ctx.game_module.get_monster(name, version))
        form["evolve"] = routes
        with quiet():
            return crawl.crawl_route(crawl.Bench(ctx, self.env), form, index, routes[index], ctx)

    def test_moving_past_earlier_routes(self):
        routes = [{"to": "Greymon", "training": [32, 999999], "mistakes": [0, 3]},
                  {"to": "Devimon", "training": [0, 31], "mistakes": [0, 3]},
                  {"to": "Numemon"}]
        row = self.verdict("DMC", "Agumon", 1, routes, 2)
        self.assertEqual(row["result"], "achieved", row)
        self.assertGreaterEqual(row["state"]["mistakes"], 4)

    def test_criteria_that_move_together(self):
        # Numemon needs 3+ mistakes and 5+ trainings: past Greymon only with
        # 6+ battles (or 6+ mistakes, which Devimon takes), past Devimon only
        # with 3-4 mistakes. The exact search finds the corner.
        routes = [{"to": "Greymon", "mistakes": [0, 5], "training": [5, 999999], "battles": [0, 5]},
                  {"to": "Devimon", "mistakes": [5, 999999]},
                  {"to": "Numemon", "mistakes": [3, 999999], "training": [5, 999999]}]
        row = self.verdict("DMC", "Agumon", 1, routes, 2)
        self.assertEqual(row["result"], "achieved", row)

    def test_a_requirement_no_player_reaches(self):
        routes = [{"to": "Greymon", "trophies": [5, 999999]}]
        row = self.verdict("DMC", "Agumon", 1, routes, 0)
        self.assertEqual(row["result"], "impossible")
        self.assertIn("Trophies", row["reason"])

    def test_a_copy_of_an_earlier_route_is_shadowed(self):
        routes = [{"to": "Greymon", "training": [16, 999999]},
                  {"to": "Devimon", "training": [16, 999999]}]
        row = self.verdict("DMC", "Agumon", 1, routes, 1)
        self.assertEqual(row["result"], "shadowed")
        self.assertEqual(row["by"], 0)

    def test_a_failed_chance_falls_through(self):
        routes = [{"to": "Greymon", "chance": 50}, {"to": "Devimon"}]
        row = self.verdict("DMC", "Agumon", 1, routes, 1)
        self.assertEqual(row["result"], "achieved", row)

    def test_an_unlock_nobody_earns(self):
        routes = [{"to": "Greymon", "unlock": "no_such_unlock"}]
        row = self.verdict("DMC", "Agumon", 1, routes, 0)
        self.assertEqual(row["result"], "impossible")

    @unittest.skipUnless(os.path.isdir(os.path.join(MODULES, "VBE")), "VBE not present")
    def test_vital_values_a_run_without_mistakes_earns(self):
        # BigUkkomon asks 4000 of a Child (BE card data), 20 battles at 60%+;
        # 4500 is more than the Child holds.
        record = self.env.rg.game_modules["VBE"].get_monster("Ukkomon", 14)
        routes = [dict(r) for r in record["evolve"]]
        index = next(i for i, r in enumerate(routes) if r.get("to") == "BigUkkomon")
        self.assertEqual(routes[index]["vital_values"][0], 4000)
        row = self.verdict("VBE", "Ukkomon", 14, routes, index)
        self.assertEqual(row["result"], "achieved", row)
        row = self.verdict("VBE", "Ukkomon", 14, [{"to": "BigUkkomon", "vital_values": [4500, 999999]}], 0)
        self.assertEqual(row["result"], "impossible")
        self.assertIn("vital_values", row["reason"])

    @unittest.skipUnless(os.path.isdir(os.path.join(MODULES, "DMX")), "DMX not present")
    def test_special_encounter_false(self):
        record = self.env.rg.game_modules["DMX"].get_monster("Kentaurosmon (X Antibody)", 1)
        routes = [dict(r) for r in record["evolve"]]
        index = next(i for i, r in enumerate(routes) if r.get("special_encounter") is False)
        row = self.verdict("DMX", "Kentaurosmon (X Antibody)", 1, routes, index)
        self.assertEqual(row["result"], "achieved", row)


if __name__ == "__main__":
    unittest.main()
