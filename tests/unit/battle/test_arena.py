"""Arena Season: the headless engine, replay orientation and the freezer lock."""

import os
import pickle
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

# These tests live under utilities/claude/tests/, three folders below
# the repo root, so they are not carried in the git repository.
REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SRC = os.path.join(REPO_ROOT, "src")
for path in (SRC, REPO_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from core import pet_stats  # noqa: E402
from battle.arena import engine, replay  # noqa: E402

MODULES = os.path.join(REPO_ROOT, "modules")


def _entry(name="Testmon", power=40, hp=12, attribute="Va", stage=4, level=3):
    return {"module": "TEST", "module_version": "1", "name": name, "version": 1,
            "index": 1, "stage": stage, "attribute": attribute, "level": level,
            "power": power, "hp": hp, "atk_main": 3, "atk_alt": 4, "atk_alt_2": 0,
            "traited": False, "shook": False, "effort": 0}


class PowerRuleParityTests(unittest.TestCase):
    """GamePet now delegates to core.pet_stats; the numbers must not move."""

    RULES = ("None", "Star", "Strength Hearts", "Strength and Level", "Effort",
             "Stage Table", "Stage Table + Shaken", "Stage Table Xros")

    def _pet(self, **stats):
        from models.game_pet import GamePet
        pet = GamePet.__new__(GamePet)
        pet.module = "Test"
        pet.bonus_stats = [0, 0, 0]
        for key, value in stats.items():
            setattr(pet, key, value)
        return pet

    @staticmethod
    def _old_power(pet, rule):
        """The formula GamePet.get_power carried before the move."""
        power = pet.power
        if rule == "None":
            return power
        if rule == "Star":
            return int(power + (pet.star or 0) * 16)
        if rule == "Strength Hearts":
            if pet.stomach and not (pet.weight >= 99 or pet.hunger <= 0):
                power += min(16, (16 * pet.strength) // pet.stomach)
            return power
        if rule == "Strength and Level":
            if pet.stomach and pet.strength >= pet.stomach:
                power += 16 if int(pet.version) in (1, 2) else 15
            for milestone in (3, 6, 9):
                if pet.level >= milestone:
                    power += 10
            return power
        if rule == "Effort":
            if pet.effort >= 16:
                power += pet_stats.POWER_STAGE_TABLES["Stage Table + Shaken"].get(pet.stage, 0)
            return power
        table = pet_stats.POWER_STAGE_TABLES.get(rule)
        step = table.get(pet.stage, 0)
        if pet.stomach and pet.strength >= pet.stomach:
            power += step
        if pet.traited:
            power += step
        if rule == "Stage Table + Shaken" and pet.shook:
            power += 10
        return power

    def test_every_rule_matches_the_previous_formula(self):
        cases = []
        for stage in (3, 4, 5, 6):
            for strength in (0, 2, 4):
                for hunger, weight in ((0, 20), (3, 20), (3, 99)):
                    for level in (1, 3, 6, 9):
                        for version in (1, 3):
                            cases.append(dict(
                                power=40, stage=stage, strength=strength, stomach=4,
                                hunger=hunger, weight=weight, level=level,
                                version=version, effort=level * 3, traited=level > 3,
                                shook=strength == 2, star=level))
        for rule in self.RULES:
            module = SimpleNamespace(power_bonus_rule=rule, visible_stats=[])
            for stats in cases:
                pet = self._pet(**stats)
                with patch("models.game_pet.get_module", return_value=module):
                    self.assertEqual(pet.get_power(), self._old_power(pet, rule),
                                     (rule, stats))

    def test_hp_bonuses_match(self):
        module = SimpleNamespace(visible_stats=["Vital Values"])
        pet = self._pet(hp=12, level=10, stage=4, vital_values=5000)
        with patch("models.game_pet.get_module", return_value=module):
            self.assertEqual(pet.get_hp(), 12 + 10 + 6)
        pet = self._pet(hp=12, level=5, stage=4, vital_values=5000)
        with patch("models.game_pet.get_module",
                   return_value=SimpleNamespace(visible_stats=["Level"])):
            self.assertEqual(pet.get_hp(), 12 + 4)


@unittest.skipUnless(os.path.isdir(MODULES), "modules folder not present")
class EngineTests(unittest.TestCase):
    def setUp(self):
        self.catalog = engine.Catalog(MODULES)
        self.uploads = engine.random_team(self.catalog, seed=5,
                                          restrictions={"allowed_modules": ["DMC"]})

    def test_species_stats_come_from_the_module_not_the_upload(self):
        honest = engine.build_entry(self.catalog, self.uploads[0])
        forged = engine.build_entry(self.catalog, dict(
            self.uploads[0], power=999, attribute="Vi", stage=7, hp=99))
        self.assertEqual(honest, forged)

    def test_status_is_clamped_to_what_the_species_can_hold(self):
        entry = engine.build_entry(self.catalog, dict(
            self.uploads[0], status={"level": 99, "strength": 99, "hunger": -5,
                                     "weight": 1000, "effort": 10 ** 6}))
        status = entry["status"]
        monster = self.catalog.module(entry["module"])["monsters"][(entry["name"], entry["version"])]
        self.assertEqual(status["level"], pet_stats.MAX_LEVEL[entry["stage"]])
        self.assertEqual(status["strength"], monster["stomach"])
        self.assertEqual(status["hunger"], 0)
        self.assertEqual(status["weight"], engine.MAX_WEIGHT)
        self.assertEqual(status["effort"], engine.MAX_EFFORT)

    def test_unknown_modules_edited_and_dead_pets_are_refused(self):
        cases = {
            "module_unavailable": dict(self.uploads[0], module_name="NOT_HERE"),
            "unknown_digimon": dict(self.uploads[0], name="Nobodymon"),
            "edited": dict(self.uploads[0], status={"edited": True}),
            "dead": dict(self.uploads[0], status={"state": "dead"}),
        }
        for code, upload in cases.items():
            with self.assertRaises(engine.ArenaError) as ctx:
                engine.build_entry(self.catalog, upload)
            self.assertEqual(ctx.exception.code, code)

    def test_restrictions_accept_names_or_codes(self):
        entry = engine.build_entry(self.catalog, self.uploads[0])
        name = engine.ATTRIBUTE_NAMES[entry["attribute"]]
        self.assertIsNone(engine.restriction_error(entry, {"allowed_attributes": [name]}))
        self.assertIsNone(engine.restriction_error(
            entry, {"allowed_attributes": [entry["attribute"] or "Free"]}))
        other = [n for n in ("Vaccine", "Data", "Virus", "Free") if n != name]
        self.assertIsNotNone(engine.restriction_error(entry, {"allowed_attributes": other}))
        self.assertIsNotNone(engine.restriction_error(
            entry, {"allowed_stages": [entry["stage"] + 1]}))

    def test_a_team_needs_exactly_three(self):
        with self.assertRaises(engine.ArenaError):
            engine.validate_team(self.catalog, self.uploads[:2])

    def test_battles_are_deterministic_per_seed(self):
        team1, _ = engine.validate_team(self.catalog, self.uploads)
        team2, _ = engine.validate_team(self.catalog, engine.random_team(self.catalog, seed=6))
        a = engine.run_battle(team1, team2, seed=11, rules={"charge": "random"})
        b = engine.run_battle(team1, team2, seed=11, rules={"charge": "random"})
        self.assertEqual(a["result"], b["result"])
        self.assertEqual(a["rules"]["battle_format"], "DMX")


class DrawTests(unittest.TestCase):
    def test_a_battle_that_ends_level_is_a_draw(self):
        # Nobody can land a hit at power 0, so both teams finish whole.
        team = [_entry(power=0, name=f"Testmon{i}") for i in range(3)]
        outcome = engine.run_battle(team, [dict(e) for e in team], seed=3)
        self.assertEqual(outcome["winner"], "draw")
        self.assertEqual(replay.victory_status(outcome["winner"]), "Draw")


class ReplayTests(unittest.TestCase):
    def setUp(self):
        team1 = [_entry(power=60, name="A%d" % i) for i in range(3)]
        team2 = [_entry(power=20, attribute="Vi", name="B%d" % i) for i in range(3)]
        outcome = engine.run_battle(team1, team2, seed=9)
        self.log = {"version": replay.LOG_VERSION,
                    "attacker": {"pets": team1}, "defender": {"pets": team2},
                    "hp": outcome["hp"], "result": outcome["result"]}

    def test_swapping_twice_is_the_original(self):
        result = self.log["result"]
        self.assertEqual(replay.swap_sides(replay.swap_sides(result)), result)

    def test_the_defender_sees_itself_as_device1(self):
        mine, theirs, result, my_hp, _ = replay.viewer_side(self.log, False)
        self.assertEqual(mine["pets"][0]["name"], "B0")
        self.assertEqual(result["device1_final"], self.log["result"]["device2_final"])
        self.assertEqual(my_hp, self.log["hp"]["team2"])
        for turn in result["battle_log"]:
            for attack in turn["attacks"]:
                original = "device2" if attack["device"] == "device1" else "device1"
                self.assertIn(original, ("device1", "device2"))
        flipped = {"device1": "device2", "device2": "device1"}.get(
            self.log["result"]["winner"], "draw")
        self.assertEqual(result["winner"], flipped)

    def test_a_log_from_the_old_server_has_no_replay(self):
        with self.assertRaises(ValueError):
            replay.viewer_side({"version": "1.0", "rounds": []}, True)


class FreezerLockTests(unittest.TestCase):
    def setUp(self):
        from core import game_globals
        self.gg = game_globals
        self.tmp = tempfile.mkdtemp()
        self._patch = patch.object(game_globals, "get_save_dir", return_value=self.tmp)
        self._patch.start()
        self.saved_pets = list(game_globals.pet_list)

    def tearDown(self):
        self._patch.stop()
        self.gg.pet_list = self.saved_pets

    def test_the_lock_is_a_local_clock_check(self):
        pet = SimpleNamespace(arena_lock={"until": 1000.0})
        self.assertTrue(self.gg.is_pet_arena_locked(pet, now=999.0))
        self.assertFalse(self.gg.is_pet_arena_locked(pet, now=1000.0))
        self.assertFalse(self.gg.is_pet_arena_locked(SimpleNamespace()))

    def test_team_pets_move_to_the_freezer_and_stay_in_the_save(self):
        from models.game_freezer import GameFreezer
        pages = [GameFreezer([], i, "bg", "m", game_mode=self.gg.game_mode) for i in range(10)]
        with open(os.path.join(self.tmp, "freezer.pkl"), "wb") as f:
            pickle.dump(pages, f)
        team = [SimpleNamespace(name=f"p{i}") for i in range(3)]
        keep = SimpleNamespace(name="keep")
        self.gg.pet_list = team + [keep]
        with patch.object(self.gg, "save") as save:
            ok = self.gg.lock_pets_for_arena(team, {"until": 2e9, "team_id": "T1"})
        self.assertTrue(ok)
        save.assert_called_once()
        self.assertEqual([p.name for p in self.gg.pet_list], ["keep"])
        with open(os.path.join(self.tmp, "freezer.pkl"), "rb") as f:
            stored = [p for page in pickle.load(f) for p in page.pets]
        self.assertEqual(sorted(p.name for p in stored), ["p0", "p1", "p2"])
        self.assertTrue(all(p.arena_lock["team_id"] == "T1" for p in stored))

        # The server reporting the season over releases them early.
        self.assertEqual(self.gg.release_arena_locks(["T1"]), 3)
        with open(os.path.join(self.tmp, "freezer.pkl"), "rb") as f:
            stored = [p for page in pickle.load(f) for p in page.pets]
        self.assertTrue(all(p.arena_lock is None for p in stored))

    def test_a_failed_freezer_write_leaves_the_party_alone(self):
        team = [SimpleNamespace(name="p0")]
        self.gg.pet_list = list(team)
        with patch.object(self.gg, "freezer_deposit_pets", return_value=0):
            self.assertFalse(self.gg.lock_pets_for_arena(team, {"until": 2e9}))
        self.assertEqual(self.gg.pet_list, team)
        self.assertIsNone(team[0].arena_lock)


class TeamUploadTests(unittest.TestCase):
    def test_the_upload_names_the_species_and_carries_only_status(self):
        from scenes.connect_views.arena_team_creation_view import _pet_to_upload, _pet_passes
        pet = SimpleNamespace(name="Agumon", module="DMC", version=1, level=2,
                              strength=4, hunger=3, weight=20, effort=8, traited=False,
                              shook=False, vital_values=0, sick=0, state="idle",
                              edited=False, power=20, atk_main=3, stage=3, attribute="Va")
        upload = _pet_to_upload(pet)
        self.assertEqual(set(upload), {"name", "module_name", "module_version",
                                       "pet_version", "status"})
        self.assertEqual(_pet_passes(pet, {}, {"DMX"})[1], "Module not in this arena season")
        self.assertTrue(_pet_passes(pet, {"allowed_attributes": ["Vaccine"]}, {"DMC"})[0])
        self.assertFalse(_pet_passes(pet, {"allowed_attributes": ["Data"]}, {"DMC"})[0])


if __name__ == "__main__":
    unittest.main()
