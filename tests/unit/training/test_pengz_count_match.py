"""The PENGZ Count Match Color (a hidden variant of the minigame for PENGZ
G-Cell style modules), quest enemies' attack patterns, the Stage Table +
G-Cells power rule and the PENGZ quest gates."""

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

from utils import gcell_rules, pengz_count_match as pcm  # noqa: E402

MODULES = os.path.join(REPO_ROOT, "modules")
PENGZ = SimpleNamespace(gcell_style="PENGZ", gcell_points_per_cell=[2, 2, 2, 4, 8, 16, 16, 16, 16],
                        gcell_training_gain=[-1, 0, 1, 2],
                        gcell_training_gain_anguirus=[-2, 0, 4, 8])
DMC = SimpleNamespace(gcell_style="Disabled")


class _Pet:
    """A hashable stand-in: training keys its results by pet."""
    def __init__(self, **fields):
        self.__dict__.update(fields)


def _pet(attribute="", stage=4, points=0, module="PENGZ"):
    return _Pet(attribute=attribute, stage=stage, gcell_points=points, module=module)


#: humulos's super-hit chart: attribute, G-Cell band -> buckets 3-4 ... 13+.
HUMULOS = {
    ("", 0): [4, 5, 2, 3, 1, 0], ("Da", 0): [4, 5, 2, 3, 1, 0], ("Vi", 0): [2, 3, 4, 5, 1, 0],
    ("", 1): [0, 1, 5, 4, 2, 3], ("Da", 1): [3, 2, 0, 1, 5, 4], ("Vi", 1): [4, 5, 0, 1, 3, 2],
    ("", 2): [4, 5, 1, 0, 3, 2], ("Da", 2): [0, 1, 4, 5, 3, 2], ("Vi", 2): [1, 0, 2, 3, 5, 4],
    ("", 3): [2, 3, 0, 1, 5, 4], ("Da", 3): [4, 5, 2, 0, 2, 3], ("Vi", 3): [0, 1, 5, 4, 3, 2],
}


class FirmwareTableTests(unittest.TestCase):
    def test_reproduces_humulos_chart(self):
        for (attribute, band), supers in HUMULOS.items():
            with self.subTest(attribute=attribute, band=band):
                rows = pcm.SCORES[attribute][band]
                self.assertEqual([pcm.super_hits(r) for r in rows], supers)

    def test_reproduces_the_manual_target_colours(self):
        names = {1: "Red", 2: "Yellow", 3: "Blue"}
        manual = {"": ["Blue", "Yellow", "Blue", "Red"], "Va": ["Blue", "Yellow", "Blue", "Red"],
                  "Da": ["Blue", "Red", "Yellow", "Blue"], "Vi": ["Yellow", "Blue", "Red", "Yellow"]}
        for attribute, colours in manual.items():
            for band, colour in enumerate(colours):
                row = pcm.SCORES[attribute][band]
                self.assertEqual(names[pcm.BUCKET_COLOURS[row.index(14) + 1]], colour)

    def test_buckets_and_colours(self):
        self.assertEqual([pcm.bucket(s) for s in range(15)],
                         [0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6])
        self.assertEqual([pcm.colour(s) for s in (0, 2, 3, 6, 7, 10, 11, 20)],
                         [4, 4, 3, 3, 2, 2, 1, 1])

    def test_band_follows_the_stage_cell_size(self):
        with patch.object(pcm, "_module_of", return_value=PENGZ):
            # Stage IV: 8 points a cell; a partial cell counts.
            self.assertEqual(pcm.band(_pet(stage=4, points=24)), 0)     # 3 cells
            self.assertEqual(pcm.band(_pet(stage=4, points=25)), 1)     # 4 cells
            self.assertEqual(pcm.band(_pet(stage=4, points=81)), 3)     # 11 cells
            # Stage V: 16 a cell
            self.assertEqual(pcm.band(_pet(stage=5, points=81)), 1)     # 6 cells

    def test_score_pattern_and_grade(self):
        with patch.object(pcm, "_module_of", return_value=PENGZ):
            pet = _pet("Da", stage=4, points=0)                         # band 0
            self.assertEqual(pcm.score(pet, 2), 0)                      # too few shakes
            self.assertEqual(pcm.score(pet, 6), 14)                     # 5-6: Megahit
            self.assertEqual(pcm.pattern(14), [2, 2, 2, 2, 2, 2])
            self.assertEqual(pcm.target_colour(pet), 3)                 # Blue
        self.assertEqual([pcm.grade(n) for n in range(6)], [0, 1, 1, 2, 2, 3])

    def test_applies_only_to_pengz_style(self):
        with patch.object(pcm, "_module_of", return_value=PENGZ):
            self.assertTrue(pcm.applies(_pet()))
        with patch.object(pcm, "_module_of", return_value=DMC):
            self.assertFalse(pcm.applies(_pet()))
        self.assertFalse(pcm.applies(None))

    def test_anguirus_every_fifth(self):
        pet = _pet()
        came = [pcm.count_training(pet) for _ in range(10)]
        self.assertEqual(came, [False] * 4 + [True] + [False] * 4 + [True])

    def test_anguirus_gcells(self):
        pet = _pet(stage=4)
        self.assertEqual(gcell_rules.gain(PENGZ, pet, "training", won=True, grade=3), 2)
        self.assertEqual(gcell_rules.gain(PENGZ, pet, "training", won=True, grade=3,
                                          anguirus=True), 8)
        self.assertEqual(gcell_rules.gain(PENGZ, pet, "training", won=False, anguirus=True), -2)


class MinigameTests(unittest.TestCase):
    def make(self, module):
        from ui.minigames.count_match import CountMatch
        with patch.object(pcm, "_module_of", return_value=module):
            return CountMatch(Mock(), _pet("Vi", stage=4, points=40), Mock())

    def test_pengz_colours_and_ready(self):
        cm = self.make(PENGZ)
        self.assertTrue(cm.pengz)
        with patch.object(pcm, "_module_of", return_value=PENGZ):
            self.assertEqual(cm.get_pet_attribute_ready_frame(), 3)    # Vi, 5 cells: Blue
        cm.set_phase("count")
        shown = []
        for _ in range(11):
            cm.handle_event(("Y", None))
            shown.append(cm.get_rotation_index())
        self.assertEqual(shown, [4, 4, 3, 3, 3, 3, 2, 2, 2, 2, 1])

    def test_other_modules_keep_the_pendulum_color(self):
        cm = self.make(DMC)
        self.assertFalse(cm.pengz)
        cm.set_phase("count")
        cm.handle_event(("Y", None))
        cm.handle_event(("Y", None))
        self.assertEqual(cm.get_rotation_index(), 3)                   # Blue at 2


class TrainingTests(unittest.TestCase):
    def training(self, pets, shakes):
        from training.count_training import CountMatchTraining
        t = CountMatchTraining.__new__(CountMatchTraining)
        t.pets = pets
        t.press_counter = shakes
        t.rotation_index = pcm.colour(shakes)
        t.super_hits = {}
        t.pengz = True
        t.pengz_rows = {}
        t.anguirus = False
        return t

    def test_results_and_anguirus(self):
        pet = _pet("Da", stage=4, points=0)
        pet.pengz_trainings = 4
        t = self.training([pet], 6)
        with patch.object(pcm, "_module_of", return_value=PENGZ), \
                patch("training.count_training.runtime_globals.game_console", Mock()):
            t.calculate_results()
        self.assertEqual(t.super_hits[pet], 5)
        self.assertEqual(t.get_attack_count(), 3)
        self.assertTrue(t.check_victory())
        self.assertTrue(t.anguirus)
        self.assertTrue(t.anguirus_for(pet))

    def test_one_super_hit_wins(self):
        pet = _pet("", stage=4, points=0)                               # bucket 6 row 0: 0
        t = self.training([pet], 9)                                     # bucket 4: row 9 -> 3 supers
        with patch.object(pcm, "_module_of", return_value=PENGZ):
            t.calculate_results()
        self.assertEqual(t.super_hits[pet], 3)
        t = self.training([pet], 11)                                    # bucket 5: row 4 -> 1 super
        with patch.object(pcm, "_module_of", return_value=PENGZ):
            t.calculate_results()
        self.assertEqual(t.super_hits[pet], 1)
        self.assertTrue(t.check_victory())
        self.assertEqual(t.get_attack_count(), 1)


class SimulatorTests(unittest.TestCase):
    def test_a_preset_pattern_wins(self):
        from battle.sim.global_battle_simulator import GlobalBattleSimulator
        from battle.sim.models import Digimon
        sim = GlobalBattleSimulator(battle_format="PENC")
        enemy = Digimon(name="X", order=0, traited=0, egg_shake=0, index=0, hp=3, attribute="Va",
                        power=10, handicap=0, buff=0, mini_game=1, level=1, stage=4, sick=0,
                        shot1=1, shot2=1, tag_meter=0)
        default = sim._pattern_for(enemy, is_enemy=True)
        enemy.preset_pattern = [2, 1, 2, 1, 2, 1]
        self.assertEqual(sim._pattern_for(enemy, is_enemy=True), [2, 1, 2, 1, 2, 1])
        self.assertNotEqual(default, [2, 1, 2, 1, 2, 1])

    def test_game_enemy_carries_the_field(self):
        from models.game_enemy import GameEnemy
        fields = dict(name="X", power=1, attribute="", area=1, round=1, version=1, atk_main=1,
                      atk_alt=0, atk_alt_2=0, handicap=0, id=1, stage=3, hp=0, unlock="",
                      prize="")
        self.assertIsNone(GameEnemy(**fields).attack_pattern)
        self.assertEqual(GameEnemy(attack_pattern=[1, 2], **fields).attack_pattern, [1, 2])


class PowerRuleTests(unittest.TestCase):
    def test_stage_table_g_cells(self):
        from core import pet_stats
        args = dict(strength=4, stomach=4, hunger=4, weight=20, level=1, version=1, effort=0,
                    shook=False, star=0)
        rule = "Stage Table + G-Cells"
        for stage, full in ((5, 145), (6, 155), (7, 155)):
            self.assertEqual(pet_stats.power_with_bonus_rule(
                rule, 100, stage=stage, traited=True, gcell_red=True, **args), full)
        self.assertEqual(pet_stats.power_with_bonus_rule(
            rule, 100, stage=6, traited=True, gcell_red=False, **args), 135)


class ModuleDataTests(unittest.TestCase):
    def load(self, module, name):
        with open(os.path.join(MODULES, module, name), encoding="utf-8-sig") as fh:
            return json.load(fh)

    def test_quest_patterns(self):
        pool = json.load(open(os.path.join(SRC, "data", "attack_patterns", "COLOUR_ROWS.json"),
                              encoding="utf-8"))["rows"]
        for module, expected in (("PENGZ", 72), ("PENC", 240)):
            quest = [e for e in self.load(module, "battle.json")["enemies"]
                     if not e.get("special_encounter")]
            with self.subTest(module=module):
                self.assertEqual(len(quest), expected)
                self.assertTrue(all(e.get("attack_pattern") in pool for e in quest))

    def test_pengz_module(self):
        module = self.load("PENGZ", "module.json")
        self.assertEqual(module["power_bonus_rule"], "Stage Table + G-Cells")
        self.assertEqual(module["gcell_training_gain_anguirus"], [-2, 0, 4, 8])
        gates = {u["unlocks_area"]: u for u in module["unlocks"] if u.get("unlocks_area")}
        self.assertEqual(sorted(gates), [21, 22])
        for gate in gates.values():
            self.assertEqual(gate["to"], ["Omnimon: G-Fusion Mode"])
            self.assertIsNone(gate["version"])


if __name__ == "__main__":
    unittest.main()
