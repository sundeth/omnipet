"""Sickness and injury counted apart (owner, 2026-10-21; the plan in
utilities/claude/docs/sickness-injury-split-plan.md, with the owner's D4, D8
and D9). A pet has `sick` (the doses a sickness, Dots, still needs),
`injury` (an injury, Skull), `sick_total` and `injury_total` (counts in this
form) and an untreated timer for each. The module's effect fields route each
cause, every battle roll is an injury, and each kind kills by its own count
(`death_max_sicknesses`, `death_max_injuries`) and timer (`death_sick_timer`,
`death_injury_timer`).

Checked on the shared rules (utils.ailments), the loader, GamePet and its
Android copy, the heal menu, items, the old-save conversion and every
module.json. The live per-module behaviour is the care crawler's
(tests/release/care_crawl.py, MOD-21).
"""

import glob
import json
import os
import pickle
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SRC = os.path.join(REPO_ROOT, "src")
MODULES = os.path.join(REPO_ROOT, "modules")
for path in (SRC, REPO_ROOT, os.path.join(REPO_ROOT, "tests", "unit", "android")):
    if path not in sys.path:
        sys.path.insert(0, path)

from core import runtime_globals  # noqa: E402
from models.game_module import GameModule  # noqa: E402
from models.game_pet import GamePet  # noqa: E402
from services.android_offline import OfflineWorld  # noqa: E402
from services.android_pet_rules import AndroidPetRules  # noqa: E402
from utils import ailments, item_effects  # noqa: E402
from test_android_offline import module, pet, snapshot  # noqa: E402


def bare(**fields):
    data = dict(sick=0, injury=0, sick_total=0, injury_total=0, care_sick_mistake_timer=0,
                care_injury_mistake_timer=0, heal_doses=2)
    data.update(fields)
    return SimpleNamespace(**data)


class Rules(unittest.TestCase):
    def test_the_effect_names_the_kind(self):
        self.assertEqual([ailments.kind_for_effect(e) for e in ("Dots", "Skull", "Nothing", "Burpmon")],
                         ["sick", "injury", None, None])
        self.assertEqual(ailments.kind_for_effect("Odd"), "injury", "anything else was the skull")

    def test_one_at_a_time_and_immune_forms(self):
        p = bare()
        self.assertTrue(ailments.onset(p, "sick"))
        self.assertEqual((p.sick, p.sick_total), (2, 1))
        self.assertFalse(ailments.onset(p, "injury"))
        self.assertFalse(ailments.onset(bare(heal_doses=0), "sick"))

    def test_doses_and_cures(self):
        p = bare(injury=2)
        self.assertEqual(ailments.heal_dose(p), 1)
        self.assertEqual(ailments.heal_dose(p, "sick"), 0, "no sickness to treat")
        self.assertEqual(p.injury, 1)
        self.assertTrue(ailments.cure(p))
        self.assertFalse(ailments.ailing(p))

    def test_each_kind_has_its_timer(self):
        p = bare(sick=1, care_injury_mistake_timer=9)
        ailments.tick_timers(p, sleeping=False)
        ailments.tick_timers(p, sleeping=True)
        self.assertEqual((p.care_sick_mistake_timer, p.care_injury_mistake_timer), (1, 0))

    def test_the_counts_and_timers_kill_apart(self):
        mod = SimpleNamespace(death_max_injuries=20, death_max_sicknesses=20, death_sick_timer=360,
                              death_injury_timer=300)
        self.assertEqual(ailments.death_cause(bare(sick_total=19, injury_total=19), mod), "")
        self.assertEqual(ailments.death_cause(bare(injury_total=20), mod), "injuries")
        self.assertEqual(ailments.death_cause(bare(sick_total=20), mod), "sicknesses")
        self.assertEqual(ailments.death_cause(bare(care_injury_mistake_timer=301), mod), "injury")
        self.assertEqual(ailments.death_cause(bare(injury_total=20, care_sick_mistake_timer=361), mod),
                         "sickness", "a timer wins, as it always did")
        none = SimpleNamespace(death_max_injuries=15, death_max_sicknesses=0, death_sick_timer=360)
        self.assertEqual(ailments.death_cause(bare(sick_total=99), none), "", "0: no count death")

    def test_a_module_from_before_gives_each_kind_its_counterpart(self):
        old = SimpleNamespace(death_max_injuries=12, death_sick_timer=360, care_can_battle_while_sick=True,
                              care_can_train_while_sick=False)
        self.assertEqual((ailments.death_max(old, "sick"), ailments.death_timer(old, "injury")), (12, 360))
        self.assertTrue(ailments.allows_battle(old, "injury"))
        self.assertFalse(ailments.allows_training(old, "injury"))

    def test_the_save_undoes_its_cause(self):
        for cause, fields, expected in (
                ("injuries", dict(injury_total=20), dict(injury_total=19)),
                ("sicknesses", dict(sick_total=20), dict(sick_total=19)),
                ("sickness", dict(sick=2, care_sick_mistake_timer=361), dict(sick=0, care_sick_mistake_timer=0)),
                ("injury", dict(injury=2, care_injury_mistake_timer=361), dict(injury=0, care_injury_mistake_timer=0))):
            with self.subTest(cause=cause):
                p = bare(**fields)
                self.assertTrue(ailments.undo(p, cause))
                self.assertEqual({k: getattr(p, k) for k in expected}, expected)
        self.assertFalse(ailments.undo(bare(), "hunger"))


class OldSaves(unittest.TestCase):
    """GamePet.patch converts a pet from the one count (ailments.migrate)."""

    def test_the_doses_go_to_their_kind(self):
        dots = dict(sick=2, sick_type="dots", injuries=4, care_sick_mistake_timer=30)
        self.assertTrue(ailments.migrate(dots))
        self.assertEqual((dots["sick"], dots["injury"], dots["sick_total"], dots["injury_total"],
                          dots["care_sick_mistake_timer"]), (2, 0, 0, 4, 30))
        skull = dict(sick=3, sick_type="", injuries=7, care_sick_mistake_timer=50, death_cause="sickness")
        ailments.migrate(skull)
        self.assertEqual((skull["sick"], skull["injury"], skull["care_injury_mistake_timer"],
                          skull["care_sick_mistake_timer"], skull["death_cause"]), (0, 3, 50, 0, "injury"))
        self.assertNotIn("sick_type", skull)
        self.assertNotIn("injuries", skull)

    def test_it_runs_once(self):
        state = dict(sick=0, injury=1, sick_total=2, injury_total=3, injuries=5)
        self.assertFalse(ailments.migrate(state))
        self.assertEqual((state["injury"], state["sick_total"], state["injury_total"]), (1, 2, 3))
        self.assertNotIn("injuries", state, "the copy written for older builds goes")

    def test_a_save_round_trip(self):
        mod = module()
        p = pet(mod, injury=1, injury_total=3, sick_total=2)
        state = p.__getstate__()
        self.assertEqual(state["injuries"], 5, "an older build reads the sum")
        loaded = GamePet.__new__(GamePet)
        with patch("models.game_pet.get_module", return_value=mod), patch.object(GamePet, "load_sprite"):
            loaded.__setstate__(pickle.loads(pickle.dumps(state)))
            loaded.patch()
        self.assertEqual((loaded.injury, loaded.sick_total, loaded.injury_total), (1, 2, 3))
        self.assertFalse(hasattr(loaded, "injuries"))

    def test_an_old_pet_patched(self):
        mod = module()
        p = pet(mod)
        for k in ("injury", "sick_total", "injury_total", "care_injury_mistake_timer"):
            delattr(p, k)
        p.__dict__.update(sick=1, sick_type="", injuries=6)
        with patch("models.game_pet.get_module", return_value=mod):
            p.patch()
        self.assertEqual((p.sick, p.injury, p.injury_total, p.sick_total), (0, 1, 6, 0))

    def test_an_offline_checkpoint_from_before(self):
        mod = module()
        state = snapshot([pet(mod)])
        state["pets"][0].update(sick=1, sick_type="dots", injuries=2)
        for k in ("injury", "sick_total", "injury_total"):
            state["pets"][0].pop(k, None)
        world = OfflineWorld(state, {"Test": mod})
        self.assertEqual((world.pet_list[0].sick, world.pet_list[0].injury_total), (1, 2))


class Loader(unittest.TestCase):
    def load(self, **fields):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        with open(os.path.join(REPO_ROOT, "assets", "Tutorial", "module.json"), encoding="utf-8-sig") as f:
            data = json.load(f)
        for k in ("death_max_sicknesses", "death_injury_timer", "care_can_battle_while_injured",
                  "care_can_train_while_injured"):
            data.pop(k, None)
        data.update(fields)
        with open(os.path.join(folder, "module.json"), "w", encoding="utf-8") as f:
            json.dump(data, f)
        mod = GameModule.__new__(GameModule)
        mod.folder_path = folder
        mod.load_module_data()
        return mod

    def test_a_module_from_before_gets_its_counterparts(self):
        mod = self.load(death_max_injuries=20, death_sick_timer=300, care_can_battle_while_sick=True)
        self.assertEqual((mod.death_max_sicknesses, mod.death_injury_timer, mod.care_can_battle_while_injured,
                          mod.care_can_train_while_injured), (20, 300, True, False))

    def test_the_new_fields(self):
        mod = self.load(death_max_injuries=30, death_max_sicknesses=0, death_injury_timer=120,
                        care_can_battle_while_sick=True, care_can_battle_while_injured=False)
        self.assertEqual((mod.death_max_sicknesses, mod.death_injury_timer, mod.care_can_battle_while_injured),
                         (0, 120, False))


class Pets(unittest.TestCase):
    """GamePet and its Android copy, through the module's routing."""

    def setUp(self):
        for target in ("game_console", "game_sound"):
            p = patch.object(runtime_globals, target, SimpleNamespace(log=lambda *_: None, play=lambda *_: None))
            p.start()
            self.addCleanup(p.stop)

    def test_every_battle_roll_is_an_injury(self):
        mod = module(battle_base_sick_chance_win=100, battle_base_sick_chance_lose=100,
                     protein_overdose_max=0, protein_penalty=0, disturbance_penalty_max=0)
        for won in (True, False):
            with self.subTest(won=won):
                p = pet(mod, protein_overdose=0, disturbance_penalty=0, injury_probability=0)
                with patch("models.game_pet.get_module", return_value=mod):
                    p._battle_health(won)
                self.assertEqual((p.sick, p.injury_total), (0, 1))

    def test_the_gates_read_each_kind(self):
        mod = module(care_can_battle_while_sick=True, care_can_battle_while_injured=False,
                     care_can_train_while_sick=False, care_can_train_while_injured=True)
        sick, injured = pet(mod, sick=1), pet(mod, injury=1)
        self.assertIsNone(ailments.blocks_battle(sick, mod))
        self.assertEqual(ailments.blocks_battle(injured, mod), "injury")
        self.assertEqual(ailments.blocks_training(sick, mod), "sick")
        self.assertIsNone(ailments.blocks_training(injured, mod))

    def test_the_overlay_and_the_calls(self):
        mod = module()
        for kind in ("sick", "injury"):
            with self.subTest(kind=kind):
                p = pet(mod, **{kind: 1})
                with patch("models.game_pet.get_module", return_value=mod), \
                        patch.object(GamePet, "should_sleep", return_value=False):
                    self.assertTrue(p.need_care(), "either ailment calls and holds the evolution")

    def test_the_android_copy_routes_the_same(self):
        mod = module(care_poop_sickness_count=1, care_poop_sickness_effect="Dots", care_99g_effect="Skull")
        state = snapshot([pet(mod, weight=99, _cd_poop=1)])
        world = OfflineWorld(state, {"Test": mod}).advance(state["at"] + 60)
        p = world.pet_list[0]
        # 99 g (Skull) lands first in the minute, so the poop pile's Dots waits.
        self.assertEqual((p.injury_total, p.sick_total, ailments.kind_of(p)), (1, 0, "injury"))


class HealAndItems(unittest.TestCase):
    def test_medicine_by_kind(self):
        sick, injured = bare(sick=1), bare(injury=1)
        self.assertFalse(item_effects.cure(sick, "injury"))
        self.assertTrue(item_effects.cure(sick, "sick"))
        self.assertTrue(item_effects.cure(injured, ""))
        self.assertFalse(ailments.ailing(injured))

    def test_the_heal_menu(self):
        """One kind in the party heals directly; both open SceneHealing,
        whose Dots button treats the sick and Skull the injured."""
        from scenes.scene_maingame import SceneMainGame
        from scenes.scene_healing import SceneHealing
        from core import game_globals
        scene = SceneMainGame.__new__(SceneMainGame)
        scene.start_scene = Mock()
        a, b = Mock(sick=1, injury=0), Mock(sick=0, injury=2)
        with patch.object(game_globals, "pet_list", [a, b]), \
                patch("scenes.scene_maingame.distribute_pets_evenly"), \
                patch.object(runtime_globals, "game_sound", Mock()), \
                patch.object(runtime_globals, "game_console", Mock()):
            scene.heal_sick_pets()
            scene.start_scene.assert_called_once_with("healing")
            healing = SceneHealing.__new__(SceneHealing)
            with patch("scenes.scene_healing.distribute_pets_evenly"), \
                    patch("scenes.scene_healing.change_scene"):
                healing.on_skull_button()
            self.assertEqual((a.sick, b.injury), (1, 1))
            with patch.object(game_globals, "pet_list", [b]):
                scene.heal_sick_pets()
            self.assertEqual(b.injury, 0)


def _module_files():
    files = sorted(glob.glob(os.path.join(MODULES, "*", "module.json")))
    return files + [os.path.join(REPO_ROOT, "assets", "Tutorial", "module.json")]


@unittest.skipUnless(os.path.isdir(MODULES), "modules/ is gitignored")
class ModuleData(unittest.TestCase):
    #: (death_max_sicknesses, death_max_injuries) as migrated (sickness_injury_split_20261021.py).
    COUNTS = {"D-3": (12, 12), "DMX": (20, 20), "PEN20": (20, 20), "PENOG": (20, 20), "PENZ": (20, 20),
              "PENC": (12, 12), "PENGZ": (12, 12), "IC": (30, 30), "DMM": (30, 30), "TWIN": (20, 20),
              "PENX": (30, 30), "PENPROG": (0, 0)}
    SKULL_ONLY = {"DMC", "DMGZ", "DMH", "DM20", "DMRV", "DMOG", "DMXW", "DW1", "VB", "VBE", "VH", "ACCEL",
                  "Tutorial"}

    def test_every_module_names_both(self):
        for path in _module_files():
            name = os.path.basename(os.path.dirname(path))
            with self.subTest(module=name):
                with open(path, encoding="utf-8-sig") as f:
                    data = json.load(f)
                self.assertIn("death_max_sicknesses", data)
                self.assertIn("death_injury_timer", data)
                self.assertEqual(data["death_injury_timer"], data["death_sick_timer"])
                if name in self.COUNTS:
                    self.assertEqual((data["death_max_sicknesses"], data["death_max_injuries"]), self.COUNTS[name])
                else:
                    self.assertIn(name, self.SKULL_ONLY)
                    self.assertEqual(data["death_max_sicknesses"], 0)
                    dots = [f for f, count in (("care_poop_sickness_effect", "care_poop_sickness_count"),
                                               ("care_99g_effect", None))
                            if data.get(f) == "Dots" and (count is None or data.get(count, 4))]
                    self.assertEqual(dots, [], "a Skull-only module causes no sickness")

    def test_the_owners_changes(self):
        def read(name):
            with open(os.path.join(MODULES, name, "module.json"), encoding="utf-8-sig") as f:
                return json.load(f)
        vb = read("VB")
        self.assertEqual((vb["care_poop_sickness_effect"], vb["care_99g_effect"]), ("Skull", "Skull"))
        dmm = read("DMM")
        self.assertEqual((dmm["care_can_battle_while_sick"], dmm["care_can_battle_while_injured"]), (True, False))
        if os.path.isfile(os.path.join(MODULES, "TWIN", "module.json")):
            twin = read("TWIN")
            self.assertEqual((twin["care_poop_sickness_effect"], twin["care_disturbance_sickness_effect"]),
                             ("Dots", "Dots"))


if __name__ == "__main__":
    unittest.main()
