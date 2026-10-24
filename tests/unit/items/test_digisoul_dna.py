"""DigiSoul DNA as a queue, and evolution by the leading DNA (owner,
2026-10-05).

The devices do not count DigiSoul: one DNA fed is enough to take a route,
and of two types held the one fed most leads -- the latest fed on a tie, so
a Digimon holding Beast that is fed Bird goes the Bird way. A Digimon
remembers its last ``DNA_QUEUE_SIZE`` (16) feeds. A route names the types it
takes (``digisoul_dna``); routes are tried in order, and a route without DNA
after the DNA ones is where a Digimon with no fitting DNA goes. An egg's DNA
hatches with it (its device's DigiSoul Plate is charged into it when it is
started); every other evolution clears the DNA.
"""

import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

# These tests live under utilities/claude/tests/, three folders below
# the repo root, so they are not carried in the git repository.
REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SRC = os.path.join(REPO_ROOT, "src")
for path in (SRC, REPO_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from core import constants, runtime_globals  # noqa: E402
from models.game_pet import GamePet  # noqa: E402

IC = os.path.join(REPO_ROOT, "modules", "IC")


def make_pet(dna=(), routes=None, stage=1):
    pet = GamePet.__new__(GamePet)
    pet.name = "Botamon"
    pet.module = "Test"
    pet.version = 1
    pet.stage = stage
    pet.dna = list(dna)
    pet.evolve = routes or []
    return pet


class QueueTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(runtime_globals, "game_console", SimpleNamespace(log=Mock()))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_feeding_joins_the_queue_case_insensitively(self):
        pet = make_pet()
        self.assertEqual(pet.add_dna("dragon", 2), 2)
        self.assertEqual(pet.add_dna("BIRD", 1), 1)
        self.assertEqual(pet.dna, ["Dragon", "Dragon", "Bird"])
        self.assertEqual(pet.add_dna("Unknown", 5), 0)
        self.assertEqual(pet.add_dna("Dragon", 0), 0)
        self.assertEqual(pet.add_dna("Dragon", -3), 0, "DNA is fed, never taken back")

    def test_only_the_last_sixteen_are_remembered(self):
        pet = make_pet()
        pet.add_dna("Beast", 10)
        pet.add_dna("Bird", 10)
        self.assertEqual(len(pet.dna), constants.DNA_QUEUE_SIZE)
        self.assertEqual(pet.dna.count("Beast"), constants.DNA_QUEUE_SIZE - 10)
        self.assertEqual(pet.leading_dna(), "Bird")

    def test_the_type_fed_most_leads_and_the_latest_breaks_a_tie(self):
        self.assertIsNone(make_pet().leading_dna())
        self.assertEqual(make_pet(["Beast", "Bird"]).leading_dna(), "Bird")
        self.assertEqual(make_pet(["Bird", "Beast"]).leading_dna(), "Beast")
        self.assertEqual(make_pet(["Beast", "Beast", "Bird"]).leading_dna(), "Beast")
        self.assertEqual(make_pet(["Beast", "Bird", "Bird", "Beast"]).leading_dna(), "Beast")


class RouteTests(unittest.TestCase):
    ROUTES = [
        {"to": "Koromon", "digisoul_dna": ["Dragon", "Bird", "Holy"]},
        {"to": "Wanyamon", "digisoul_dna": ["Beast", "Water", "Dark"]},
        {"to": "Budmon", "digisoul_dna": ["Insect", "Machine"]},
        {"to": "Chuumon"},
    ]

    def target(self, pet):
        forms = {name: {"name": name, "stage": 2} for name in
                 ("Koromon", "Wanyamon", "Budmon", "Chuumon")}
        module = SimpleNamespace(get_monster=lambda name, version: forms.get(name), unlocks=[])
        with patch("models.game_pet.get_module", return_value=module):
            match = pet.find_evolution()
        return match[0]["to"] if match else None

    def test_one_dna_is_enough_and_the_leading_type_picks_the_route(self):
        self.assertEqual(self.target(make_pet(["Dragon"], self.ROUTES)), "Koromon")
        self.assertEqual(self.target(make_pet(["Machine"], self.ROUTES)), "Budmon")
        # Beast held, then Bird fed: Bird leads.
        self.assertEqual(self.target(make_pet(["Beast", "Bird"], self.ROUTES)), "Koromon")

    def test_a_route_without_dna_after_them_takes_the_rest(self):
        self.assertEqual(self.target(make_pet([], self.ROUTES)), "Chuumon")

    def test_routes_keep_their_order(self):
        routes = [{"to": "Koromon", "digisoul_dna": ["Dragon"]},
                  {"to": "Wanyamon", "digisoul_dna": list(constants.DIGISOUL_DNA_TYPES)}]
        self.assertEqual(self.target(make_pet(["Dragon"], routes)), "Koromon")
        self.assertEqual(self.target(make_pet(["Holy"], routes)), "Wanyamon")

    def test_an_empty_or_missing_list_is_no_requirement(self):
        pet = make_pet()
        self.assertFalse(pet._has_dna_evolution_criterion({"to": "X", "digisoul_dna": []}))
        self.assertFalse(pet._has_dna_evolution_criterion({"to": "X"}))
        self.assertTrue(pet._has_dna_evolution_criterion({"to": "X", "digisoul_dna": ["Holy"]}))


class EvolutionClearsDnaTests(unittest.TestCase):
    def evolve(self, stage):
        pet = make_pet(["Dragon"], stage=stage)
        pet.name = "Mon"
        module = SimpleNamespace(name="Test", get_monster=lambda n, v: {"name": n, "stage": stage + 1})
        pet.set_data = lambda data: setattr(pet, "stage", data["stage"])
        pet.reset_variables = pet.load_sprite = pet.set_state = Mock()
        with patch("models.game_pet.get_module", return_value=module), \
                patch("models.game_pet.register_digidex_entry"), \
                patch("utils.utils_unlocks.check_digidex_unlocks"), \
                patch("utils.reward_utils.reward_evolution", create=True), \
                patch.object(runtime_globals, "game_sound", SimpleNamespace(play=Mock()), create=True), \
                patch.object(runtime_globals, "game_console", SimpleNamespace(log=Mock())):
            self.assertTrue(pet.evolve_to("Next", 1, reward=False))
        return pet.dna

    def test_an_egg_hatches_with_its_dna(self):
        self.assertEqual(self.evolve(0), ["Dragon"])

    def test_every_other_evolution_starts_clean(self):
        self.assertEqual(self.evolve(1), [])
        self.assertEqual(self.evolve(4), [])


class EggPlateTests(unittest.TestCase):
    def test_an_egg_is_charged_with_its_versions_plate(self):
        from utils import card_utils, utils_unlocks
        cards = {"cards": [{"id": "p101", "type": "Soul Plate", "name": "IC 101", "value": "01101",
                            "lr": "L/R"},
                           {"id": "id1", "type": "iD Plate", "name": "Agumon", "value": "1",
                            "lr": "L/R"}],
                 "effects": [{"tool": "DigiSoul Charge", "value": "01101", "lr": "Any", "effects": [
                     {"type": "DNA", "dna": "Dragon", "amount": 1, "version": 1},
                     {"type": "DNA", "dna": "Bird", "amount": 1, "version": 2}]}],
                 "packs": []}
        module = SimpleNamespace(name="Test", unlocks=[
            {"name": "plate_101", "type": "egg", "version": 1, "card": "p101"},
            {"name": "plate_other", "type": "egg", "version": 2, "card": "p101"},
            {"name": "not_a_plate", "type": "egg", "version": None, "card": "id1"}])
        egg = make_pet(stage=0)
        with patch.dict(card_utils._module_cards_cache, {"Test": cards}), \
                patch.object(runtime_globals, "game_modules", {"Test": module}), \
                patch.object(runtime_globals, "game_console", SimpleNamespace(log=Mock())):
            self.assertEqual(utils_unlocks.charge_egg_plates("Test", egg), 1)
        self.assertEqual(egg.dna, ["Dragon"], "the 10X plate, for the 10X egg only")


@unittest.skipUnless(os.path.exists(os.path.join(IC, "cards.json")), "modules/ is gitignored")
class ICDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load = lambda name: json.load(open(os.path.join(IC, name), encoding="utf-8"))
        cls.cards = load("cards.json")
        cls.monsters = load("monster.json")["monster"]
        cls.unlocks = {u["name"]: u for u in load("module.json")["unlocks"]}
        cls.enemies = load("battle.json")["enemies"]
        cls.shops = {s["name"]: s for s in load("shop.json")["shop"]}

    def name_of(self, card_id):
        return next(c["name"] for c in self.cards["cards"] if c["id"] == card_id)

    def pack_of(self, pack_id):
        return next(p["name"] for p in self.cards["packs"] if p["id"] == pack_id)

    def test_eggs_and_areas_give_their_plates(self):
        wanted = {"plate_ic_101": ("egg", 1, None, "IC 101"),
                  "plate_ic_201": ("egg", 2, None, "IC 201"),
                  "plate_burst_blue": ("egg", 3, None, "Burst Blue"),
                  "plate_ic_102": ("adventure", None, 1, "IC 102"),
                  "plate_ic_202": ("adventure", None, 2, "IC 202"),
                  "plate_burst_orange": ("adventure", None, 3, "Burst Orange")}
        for name, (kind, version, area, card) in wanted.items():
            unlock = self.unlocks[name]
            self.assertEqual((unlock["type"], unlock["version"], unlock["area"],
                              self.name_of(unlock["card"])), (kind, version, area, card), name)

    def test_area_clears_can_drop_a_pack(self):
        drops = {(e["area"], self.pack_of(e["prize_card_pack"]), e["prize_chance"])
                 for e in self.enemies if e.get("prize_card_pack")}
        self.assertEqual(drops, {(1, "iD Plate 01", 10), (2, "iD Plate 02", 10),
                                 (3, "iD Plate 03", 10), (4, "Digimon iD Plate Limited", 10)})

    def test_the_digishops_sell_packs(self):
        sold = {name: [(self.pack_of(line["card_pack"]), line["price"])
                       for line in shop["items"] if line.get("card_pack")]
                for name, shop in self.shops.items() if name.startswith("DigiShop")}
        self.assertEqual(sold, {"DigiShop 1": [("iD Plate 01", 2000)],
                                "DigiShop 2": [("iD Plate 02", 2000)],
                                "DigiShop 3": [("iD Plate 03", 2000)],
                                "DigiShop 4": [("Digimon iD Plate Limited", 5000)],
                                # The 20X's (owner, 2026-10-17; 8 2026-10-21; 6 and 7
                                # 2026-10-23): no pack.
                                "DigiShop 6": [], "DigiShop 7": [],
                                "DigiShop 8": [], "DigiShop 9": [], "DigiShop 10": [], "DigiShop 13": [],
                                "DigiShop 14": [], "DigiShop 15": [], "DigiShop 16": []})

    def test_routes_name_types_only_and_no_dna_routes_come_last(self):
        for monster in self.monsters:
            routes = monster.get("evolve") or []
            self.assertFalse(any("digisoul_amount" in r for r in routes), monster["name"])
            self.assertFalse(any(r.get("digisoul_dna") == [] for r in routes), monster["name"])
            dna = [i for i, r in enumerate(routes) if r.get("digisoul_dna")]
            if not dna:
                continue
            # No plain route stands between two DNA routes of a Digimon
            # unless it asks for something else the DNA routes do not.
            for i in range(dna[0], dna[-1]):
                route = routes[i]
                if not route.get("digisoul_dna"):
                    self.assertTrue(set(route) - {"to", "version"},
                                    f"{monster['name']}: a bare route before a DNA route")


if __name__ == "__main__":
    unittest.main()
