"""Arena Season rules on the game side and in the server's engine.

- The engine refuses species values that contradict the server's copy of
  the same module version (an edited pet), but not those of another version.
- Team sizes: a season may force one size or allow a range.
- One season per species form: ``arena_pets.fought_form`` mirrors the
  server rule, so the picker disables a veteran until it evolves.
- When a season ends, the record of the team's server copies goes onto the
  pets, once, and their lock is released -- even for a pet the freezer let
  out after its lock ran out.
- The picker and the rules screen read the season's team-size range.
"""
import json
import os
import pickle
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SRC = os.path.join(REPO_ROOT, "src")
for path in (SRC, REPO_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from battle.arena import engine  # noqa: E402
from utils import arena_pets  # noqa: E402

MONSTER = {"name": "Testmon", "version": 1, "stage": 4, "attribute": "Va", "power": 40,
           "hp": 12, "atk_main": 3, "atk_alt": 0, "stomach": 4, "min_weight": 10}


def _catalog(version="1.0.2"):
    """A Catalog over one temporary module holding MONSTER."""
    root = tempfile.mkdtemp()
    folder = os.path.join(root, "TEST")
    os.makedirs(folder)
    with open(os.path.join(folder, "module.json"), "w", encoding="utf-8") as f:
        json.dump({"name": "TEST", "version": version}, f)
    with open(os.path.join(folder, "monster.json"), "w", encoding="utf-8") as f:
        json.dump({"monster": [MONSTER, dict(MONSTER, name="Othermon", attribute="Vi")]}, f)
    return engine.Catalog(root)


def _upload(name="Testmon", module_version="1.0.2", **base):
    claimed = {"stage": 4, "attribute": "Va", "power": 40, "hp": 12, "atk_main": 3, "atk_alt": 3}
    claimed.update(base)
    return {"module_name": "TEST", "name": name, "pet_version": 1,
            "module_version": module_version, "base": claimed,
            "status": {"level": 2, "strength": 2, "hunger": 2, "weight": 12}}


class BaseCheckTests(unittest.TestCase):
    def test_matching_values_pass(self):
        entry = engine.build_entry(_catalog(), _upload())
        self.assertGreaterEqual(entry["power"], 40)

    def test_an_edited_value_on_the_same_version_is_refused(self):
        for field, value in (("power", 99), ("hp", 30), ("stage", 5),
                             ("attribute", "Data")):
            with self.subTest(field=field):
                with self.assertRaises(engine.ArenaError) as cm:
                    engine.build_entry(_catalog(), _upload(**{field: value}))
                self.assertEqual(cm.exception.code, "stats_mismatch")

    def test_attack_ids_are_art_and_not_checked(self):
        # A module may change its attack sprites without a new version.
        engine.build_entry(_catalog(), _upload(atk_main=7, atk_alt=9))

    def test_another_module_version_may_differ(self):
        # Accepted, and fought with the server's own species values.
        cat = _catalog()
        entry = engine.build_entry(cat, _upload(module_version="1.0.1", power=99))
        self.assertEqual(entry["power"], engine.build_entry(cat, _upload())["power"])

    def test_attribute_names_and_codes_compare_equal(self):
        engine.build_entry(_catalog(), _upload(attribute="Vaccine"))

    def test_an_upload_without_base_is_not_checked(self):
        upload = _upload()
        del upload["base"]
        engine.build_entry(_catalog(), upload)


class TeamSizeTests(unittest.TestCase):
    def test_a_range_accepts_every_size_in_it(self):
        cat = _catalog()
        for size in (1, 2, 3):
            entries, errors = engine.validate_team(cat, [_upload()] * size, min_size=1, max_size=3)
            self.assertEqual((len(entries), errors), (size, []))

    def test_a_forced_size_refuses_the_others(self):
        cat = _catalog()
        with self.assertRaises(engine.ArenaError) as cm:
            engine.validate_team(cat, [_upload()] * 2, min_size=1, max_size=1)
        self.assertIn("exactly 1", str(cm.exception))
        with self.assertRaises(engine.ArenaError) as cm:
            engine.validate_team(cat, [_upload()], min_size=2, max_size=3)
        self.assertIn("2 to 3", str(cm.exception))

    def test_an_old_request_still_means_exactly_three(self):
        with self.assertRaises(engine.ArenaError):
            engine.validate_team(_catalog(), [_upload()] * 2)

    def test_uneven_teams_fight(self):
        entries, _ = engine.validate_team(_catalog(), [_upload()] * 3, min_size=1, max_size=3)
        outcome = engine.run_battle(entries[:1], entries, 5, {"charge": 2})
        self.assertIn(outcome["winner"], ("device1", "device2", "draw"))
        self.assertEqual(len(outcome["result"]["device1_final"]), 1)
        self.assertEqual(len(outcome["result"]["device2_final"]), 3)

    def test_the_picker_reads_the_seasons_range(self):
        from scenes.connect_views.arena_team_creation_view import team_size_range, size_text
        self.assertEqual(team_size_range({}), (3, 3))          # an older server
        self.assertEqual(team_size_range({"config": {"min_team_size": 1, "max_team_size": 3}}), (1, 3))
        self.assertEqual(team_size_range({"config": {"min_team_size": 2, "max_team_size": 2}}), (2, 2))
        self.assertEqual(size_text(1, 3), "1-3")
        self.assertEqual(size_text(2, 2), "2")


class IdentityTests(unittest.TestCase):
    def _pet(self, **kw):
        pet = SimpleNamespace(name="Agumon", version=1, module="DMC", stage=3, power=30,
                              hp=0, attribute="Va", atk_main=2, atk_alt=0)
        pet.__dict__.update(kw)
        return pet

    def test_the_uid_is_made_once_and_kept(self):
        pet = self._pet()
        uid = arena_pets.pet_uid(pet)
        self.assertEqual(arena_pets.pet_uid(pet), uid)
        self.assertEqual(len(uid), 32)

    def test_a_form_fights_one_season_and_evolving_frees_it(self):
        pet = self._pet()
        arena_pets.mark_team([pet], {"id": "T1", "season_id": "S1", "season_name": "Week 1"})
        self.assertIsNone(arena_pets.fought_form(pet, "S1"))      # its own season
        self.assertEqual(arena_pets.fought_form(pet, "S2"), "Week 1")
        pet.name = "Greymon"                                       # evolved
        self.assertIsNone(arena_pets.fought_form(pet, "S2"))

    def test_the_snapshot_is_json_without_sprites_or_device_timers(self):
        import datetime
        pet = self._pet(frames=[object()], _rt_origin=5.0, born=datetime.date(2026, 1, 2),
                        tags={"a"}, odd=object(), nested={"when": datetime.datetime(2026, 1, 2)})
        snap = arena_pets.pet_snapshot(pet)
        json.dumps(snap)
        self.assertNotIn("frames", snap)
        self.assertNotIn("_rt_origin", snap)
        self.assertNotIn("odd", snap)
        self.assertEqual(snap["born"], "2026-01-02")
        self.assertEqual(snap["tags"], ["a"])

    def test_base_fills_hp_from_the_stage_table(self):
        from core import pet_stats
        base = arena_pets.pet_base(self._pet())
        self.assertEqual(base["hp"], pet_stats.HP_LEVEL[3])
        self.assertEqual(base["atk_alt"], 2)


class SeasonResultsTests(unittest.TestCase):
    def setUp(self):
        from core import game_globals
        from models.game_freezer import GameFreezer
        self.gg = game_globals
        self.tmp = tempfile.mkdtemp()
        self._patches = [patch.object(game_globals, "get_save_dir", return_value=self.tmp),
                         patch.object(game_globals, "save")]
        for p in self._patches:
            p.start()
        self.saved_pets = list(game_globals.pet_list)
        self.team = [SimpleNamespace(name=f"P{i}", version=1, pvp_battles=1, pvp_wins=0,
                                     totalBattles=4, totalWin=2) for i in range(3)]
        for pet in self.team:
            arena_pets.pet_uid(pet)
        arena_pets.mark_team(self.team, {"id": "T1", "season_id": "S1", "season_name": "W1"})
        for pet in self.team:
            pet.arena_lock = {"until": 2e9, "team_id": "T1"}
        pages = [GameFreezer([], i, "bg", "m", game_mode=self.gg.game_mode) for i in range(2)]
        pages[0].pets = self.team[:2]
        with open(os.path.join(self.tmp, "freezer.pkl"), "wb") as f:
            pickle.dump(pages, f)
        # The third was let out of the freezer after its lock ran out.
        self.team[2].arena_lock = None
        self.gg.pet_list = [self.team[2]]

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.gg.pet_list = self.saved_pets

    def _server_team(self):
        rows = [{"name": p.name, "uid": p.uid, "battles": 12, "wins": 7, "losses": 4, "draws": 1}
                for p in reversed(self.team)]
        return {"id": "T1", "final_rank": 2, "pets": rows}

    def test_the_record_goes_onto_every_pet_once(self):
        self.assertEqual(arena_pets.pending_team_ids(), {"T1"})
        applied = arena_pets.apply_season_results([self._server_team()])
        self.assertEqual(len(applied), 3)
        with open(os.path.join(self.tmp, "freezer.pkl"), "rb") as f:
            frozen = [p for page in pickle.load(f) for p in page.pets]
        for pet in frozen + self.gg.pet_list:
            self.assertEqual((pet.pvp_battles, pet.pvp_wins), (13, 7))
            self.assertEqual((pet.totalBattles, pet.totalWin), (16, 9))
            self.assertIsNone(pet.arena_lock)
            self.assertIsNone(pet.arena_pending)
            self.assertEqual(pet.arena_history[-1]["rank"], 2)
        # A second report changes nothing.
        self.assertEqual(arena_pets.apply_season_results([self._server_team()]), [])
        self.assertEqual(arena_pets.pending_team_ids(), set())
        self.assertEqual(self.gg.pet_list[0].pvp_battles, 13)


class UploadTests(unittest.TestCase):
    def test_version_zero_is_uploaded_as_zero(self):
        # PENC's Agumon is version 0; `version or 1` sent it as version 1,
        # which the server's module does not have.
        from scenes.connect_views.arena_team_creation_view import _pet_to_upload
        pet = SimpleNamespace(name="Agumon", module="PENC", version=0, level=1, strength=0,
                              hunger=0, weight=10, effort=0, stage=3, power=20, hp=0,
                              attribute="Va", atk_main=1, atk_alt=0)
        self.assertEqual(_pet_to_upload(pet)["pet_version"], 0)


class SeenDefencesTests(unittest.TestCase):
    def test_defences_count_until_the_history_is_opened(self):
        from core import game_globals
        tmp = tempfile.mkdtemp()
        with patch.object(game_globals, "get_save_dir", return_value=tmp):
            team = {"id": "T9", "defences": 3}
            self.assertEqual(arena_pets.unseen_defences(team), 3)
            arena_pets.mark_defences_seen("T9", 3)
            self.assertEqual(arena_pets.unseen_defences(team), 0)
            self.assertEqual(arena_pets.unseen_defences(dict(team, defences=5)), 2)
            self.assertEqual(arena_pets.unseen_defences({"id": "T9"}), 0)   # older server


if __name__ == "__main__":
    unittest.main()
