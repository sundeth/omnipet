"""What one training pays a pet, for every module's own tables.

Checklist TRN-03 (every minigame applies its rewards by outcome: effort,
Strength, weight, G-Cells, currency). GamePet.finish_training is the one
place every training minigame's outcome lands (training.Training.
apply_training_results), so it is checked here directly, for every module
in modules/ (DW1 excepted: it is being built), every grade and both
verdicts, against the module's own module.json read without the loader:

* training_effort_gain / training_strength_gain / training_weight_loss are
  indexed by the grade, 0-3, and by 0 whenever the pet failed; a grade
  outside 0-3 is clamped; a Strength gain of -1 fills the meter;
* weight never drops below the pet's minimum weight (or below 1 where the
  module allows going under it);
* a success adds reliability_minigame_success (kept within 0-31), forgives
  two disturbance points and records the training vital activity once;
* G-Cells follow the module's style: DMGZ's success / phase-1 / phase-2
  failure, PENGZ's gcell_training_gain by grade (its Anguirus table every
  fifth Count Match), kept within 0 and the style's cap;
* a module's currency is paid once a training, at the best outcome among
  its pets (utils.currency_utils.training_earnings).

And get_training_targets, which decides who trains, under both of the
inventory's selection strategies.
"""
import json
import os
import sys
import unittest
from unittest import mock

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "support"))
MODULES = os.path.join(REPO_ROOT, "modules")
#: Being built by another session; nothing here asserts its data.
SKIP_MODULES = {"DW1"}


def module_names():
    if not os.path.isdir(MODULES):
        return []
    return sorted(n for n in os.listdir(MODULES)
                  if n not in SKIP_MODULES and os.path.isfile(os.path.join(MODULES, n, "module.json")))


def module_json(name):
    with open(os.path.join(MODULES, name, "module.json"), encoding="utf-8") as fh:
        return json.load(fh)


@unittest.skipUnless(os.path.isdir(MODULES), "modules folder not present")
class TrainingRewardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness import Env, quiet
        cls.env = Env("240x240", party=[])
        cls.quiet = staticmethod(quiet)
        cls.pets = {}

    def setUp(self):
        self.env.reset()

    def pet(self, module):
        """A trainable pet of *module*: its first form with an attack, at
        stage 3 where it has one."""
        if module not in self.pets:
            from models.game_pet import GamePet
            from utils.module_utils import get_module
            mod = get_module(module)
            form = None
            for stage in (3, 4, 2, 5, 6, 1):
                forms = [m for m in mod.get_monsters_by_stage(stage) if (m.get("atk_main") or 0) > 0]
                if forms:
                    form = forms[0]
                    break
            if form is None:
                self.skipTest(f"{module} has no trainable form")
            with self.quiet():
                self.pets[module] = GamePet(dict(form, module=module))
        return self.pets[module]

    def fresh(self, module, **stats):
        pet = self.pet(module)
        pet.effort = 0
        pet.strength = 0
        pet.weight = min(99, (pet.min_weight or 5) + 30)
        pet.reliability = 15 if module_json(module).get("reliability_minigame_success") else 0
        pet.disturbance_penalty = 3
        pet.vital_activities = []
        pet.gcell_points = 20
        pet.state = "idle"
        pet.pengz_trainings = 0
        for key, value in stats.items():
            setattr(pet, key, value)
        return pet

    def train(self, pet, won, grade, **kwargs):
        with self.quiet():
            pet.finish_training(won, grade=grade, **kwargs)

    # ------------------------------------------------------------ the tables
    def test_every_module_pays_its_own_row_for_each_outcome(self):
        names = module_names()
        self.assertGreater(len(names), 10)
        for name in names:
            data = module_json(name)
            tables = [data.get(k) for k in ("training_effort_gain", "training_strength_gain",
                                             "training_weight_loss")]
            if not all(isinstance(t, list) and len(t) == 4 for t in tables):
                continue        # a pre-table module, read from the old win/lose pair
            effort, strength, weight = tables
            for won in (True, False):
                for grade in range(4):
                    with self.subTest(module=name, won=won, grade=grade):
                        pet = self.fresh(name)
                        before_weight = pet.weight
                        self.train(pet, won, grade)
                        # The grade picks the row, won or lost (2026-10-17: Mogera's
                        # lost Phase 2 is a Good; elsewhere won == (grade > 0))
                        level = grade
                        self.assertEqual(pet.effort, effort[level], "effort")
                        if strength[level] < 0:
                            self.assertGreaterEqual(pet.strength, 4, "a -1 fills the meter")
                        else:
                            self.assertEqual(pet.strength, strength[level], "strength")
                        self.assertEqual(pet.weight, max(pet.min_weight or 0, before_weight - weight[level]),
                                         "weight")
                        self.assertEqual(pet.state, "happy2" if won else "angry")

    def test_a_grade_outside_the_four_is_clamped(self):
        data = module_json("PENC")
        for grade, level in ((7, 3), (-2, 0)):
            with self.subTest(grade=grade):
                pet = self.fresh("PENC")
                self.train(pet, True, grade)
                self.assertEqual(pet.strength, data["training_strength_gain"][level])

    def test_weight_stops_at_the_minimum(self):
        pet = self.fresh("PENC")
        pet.weight = pet.min_weight + 1
        self.train(pet, True, 3)                    # PENC sheds 20 for a Megahit
        self.assertEqual(pet.weight, pet.min_weight)

    def test_a_module_that_allows_it_goes_below_the_minimum_down_to_one(self):
        from utils.module_utils import get_module
        pet = self.fresh("PENC")
        pet.weight = pet.min_weight + 1
        with mock.patch.object(get_module("PENC"), "care_allow_below_min_weight", True, create=True):
            self.train(pet, True, 3)
        self.assertEqual(pet.weight, max(1, pet.min_weight + 1 - 20))

    # ------------------------------------------------------------ a success
    def test_a_success_raises_reliability_where_the_module_says(self):
        for name in module_names():
            gain = module_json(name).get("reliability_minigame_success", 0) or 0
            with self.subTest(module=name):
                pet = self.fresh(name, reliability=10)
                self.train(pet, True, 2)
                self.assertEqual(pet.reliability, min(31, 10 + gain))
                pet = self.fresh(name, reliability=10)
                self.train(pet, False, 0)
                self.assertEqual(pet.reliability, 10, "a failure changes nothing")

    def test_reliability_stays_within_its_meter(self):
        pet = self.fresh("IC", reliability=31)
        self.train(pet, True, 3)
        self.assertEqual(pet.reliability, 31)

    def test_a_success_forgives_two_disturbance_points_and_counts_the_activity_once(self):
        pet = self.fresh("DMC", disturbance_penalty=3)
        self.train(pet, True, 1)
        self.train(pet, True, 1)
        self.assertEqual(pet.disturbance_penalty, 1, "only while two are there to forgive")
        self.assertEqual(pet.vital_activities, ["training"])
        pet = self.fresh("DMC", disturbance_penalty=3)
        self.train(pet, False, 0)
        self.assertEqual(pet.disturbance_penalty, 3)
        self.assertEqual(pet.vital_activities, [])

    # ------------------------------------------------------------ G-Cells
    def gcell_modules(self, style):
        return [n for n in module_names()
                if (module_json(n).get("gcell_style") or
                    ("DMGZ" if module_json(n).get("use_gcells") else "Disabled")) == style]

    def test_dmgz_g_cells_pay_success_and_each_phases_failure(self):
        names = self.gcell_modules("DMGZ")
        self.assertTrue(names)
        for name in names:
            data = module_json(name)
            for won, phase2, field in ((True, False, "gcell_training_success"),
                                       (True, True, "gcell_training_success"),
                                       (False, False, "gcell_training_phase1_failure"),
                                       (False, True, "gcell_training_phase2_failure")):
                with self.subTest(module=name, won=won, phase2=phase2):
                    pet = self.fresh(name, gcell_points=40)
                    self.train(pet, won, 3 if won else 0, phase2=phase2)
                    self.assertEqual(pet.gcell_points, max(0, 40 + data[field]))

    def test_pengz_g_cells_pay_by_grade_and_anguirus_pays_his_own(self):
        names = self.gcell_modules("PENGZ")
        self.assertTrue(names)
        for name in names:
            data = module_json(name)
            for anguirus, field in ((False, "gcell_training_gain"),
                                    (True, "gcell_training_gain_anguirus")):
                for won, grade in ((True, 1), (True, 2), (True, 3), (False, 3)):
                    with self.subTest(module=name, anguirus=anguirus, won=won, grade=grade):
                        pet = self.fresh(name, gcell_points=10)
                        self.train(pet, won, grade, anguirus=anguirus)
                        level = grade
                        self.assertEqual(pet.gcell_points, 10 + data[field][level])

    def test_g_cells_stay_between_zero_and_the_cap(self):
        from utils import gcell_rules
        from utils.module_utils import get_module
        for name in self.gcell_modules("DMGZ") + self.gcell_modules("PENGZ"):
            with self.subTest(module=name):
                pet = self.fresh(name, gcell_points=0)
                self.train(pet, False, 0, anguirus=True)
                self.assertEqual(pet.gcell_points, 0, "never below zero")
                cap = gcell_rules.max_points(get_module(name), pet.stage)
                pet = self.fresh(name, gcell_points=cap)
                self.train(pet, True, 3, anguirus=True)
                self.assertEqual(pet.gcell_points, cap, "never past the cap")

    def test_no_g_cells_where_the_module_has_none(self):
        for name in self.gcell_modules("Disabled"):
            with self.subTest(module=name):
                pet = self.fresh(name, gcell_points=20)
                self.train(pet, True, 3)
                self.train(pet, False, 0)
                self.assertEqual(pet.gcell_points, 20)

    # ------------------------------------------------------------ currency
    def test_a_module_is_paid_once_at_its_best_outcome(self):
        from utils.currency_utils import training_earnings
        with open(os.path.join(MODULES, "IC", "shop.json"), encoding="utf-8") as fh:
            gains = json.load(fh)["currency"][0]["training_gain"]
        ic, dmc = self.pet("IC"), self.pet("DMC")
        cases = (
            ([(ic, True, 1), (ic, True, 3)], gains[3]),
            ([(ic, True, 2)], gains[2]),
            ([(ic, False, 3)], gains[0]),             # a failure pays the failure row
            ([(ic, True, 9)], gains[3]),              # clamped like the tables
        )
        for results, amount in cases:
            with self.subTest(results=[(p.module, w, g) for p, w, g in results]):
                self.assertEqual(training_earnings(results + [(dmc, True, 3)]),
                                 [("IC", "Fight Money", amount)],
                                 "only a module with a currency is paid, once")

    # ------------------------------------------------------------ who trains
    def test_the_need_selection_never_breaks_choosing_who_trains(self):
        """SEL-NEED (the inventory's second strategy) still lists a pet below
        16 effort, and leaves out one with nothing left to gain."""
        from utils.pet_utils import get_training_targets
        pet = self.fresh("DMC", effort=3, strength=4)
        with self.need_selection(pet):
            self.assertEqual(get_training_targets(), [pet])
            pet.effort, pet.strength = 16, 4
            self.assertEqual(get_training_targets(), [])

    def need_selection(self, pet):
        """SEL-NEED on, *pet* the whole party and selected, awake."""
        import contextlib
        from models.game_pet import GamePet
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(GamePet, "should_sleep", return_value=False))
        stack.enter_context(mock.patch.object(self.env.rg, "strategy_index", 1))
        stack.enter_context(mock.patch.object(self.env.gg, "pet_list", [pet]))
        stack.enter_context(mock.patch.object(self.env.rg, "selected_pets", [pet]))
        return stack

    # BUG (tests/findings/training.md, "SEL-NEED crashes the training menu"):
    # utils/pet_utils.get_training_targets reads the module's
    # `training_strengh_gain_win`, which GameModule never sets (the loader
    # turns it into the training_strength_gain table), so a pet at 16
    # effort with Strength below 4 raises AttributeError.
    # Fixed 2026-10-13; kept as a regression test.
    def test_the_need_selection_lists_a_pet_that_still_gains_strength(self):
        from utils.pet_utils import get_training_targets
        pet = self.fresh("DMC", effort=16, strength=0)
        with self.need_selection(pet):
            self.assertEqual(get_training_targets(), [pet])


if __name__ == "__main__":
    unittest.main()
