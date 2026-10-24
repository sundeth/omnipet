"""Every training-menu minigame can be won and lost, and pays by outcome.

Checklist TRN-02 (every minigame can be played to its end and won) and
TRN-03 (every minigame applies its rewards by outcome); tracker ICX-09 for
RPM. Each of the ten minigames in scenes.scene_training.TRAINING_MODES is
started from the training menu with a party of real module pets and played
headless, the way the player plays it (the actions its handle_event reads,
on the harness's fake clock):

* a perfect play reaches the top grade (3, EXCELLENT or Megahit);
* a failing play reaches the bottom grade (0, BAD) and the minigame still
  ends and hands the screen back -- no hang, including the plays that fire no
  shot at all (Dummy, Punch and Count Match Classic used to wait forever);
* where the minigame has them, the grades between pay their own row;
* once it ends, every pet's stats moved exactly as its own module.json says
  for that outcome: training_effort_gain / training_strength_gain /
  training_weight_loss indexed by the grade (0 whenever the pet failed),
  reliability_minigame_success on a success, the G-Cells in the module's
  style (DMGZ success / phase-1 / phase-2 failure; PENGZ gcell_training_gain,
  or its Anguirus table every fifth Count Match), the disturbance penalty a
  success forgives, the trophies the minigame awards (tripled by a running
  PP multiplier item), the TRAINING quest step, and the iC's Fight Money
  from shop.json's training_gain, once.

Kept covered: Count Match Color crashed when its charge ended (the Pendulum
Color rows run six rounds, the training five waves) -- every colour at every
stage is played through here.

The expected numbers are read from the module files themselves
(minigame_driver.expected_training), never from the game's loader.
"""
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "support"))
sys.path.insert(0, HERE)

import minigame_driver as md  # noqa: E402

#: The party each minigame is played with: its own device's pet first (the
#: first pet decides the colour, the arrows, the bar art and the RPM
#: target), then modules whose tables differ -- PEN20's Megahit that fills
#: the Strength meter, PENOG's failure that pays no effort, VB's that still
#: pays Strength, DMGZ's and PENGZ's G-Cells -- and an iC pet, whose module
#: pays Fight Money and Reliability and trains nothing else.
PARTIES = {
    "dummy": ["DM20", "PEN20", "DMGZ", "IC"],
    "head": ["DMC", "PENC", "PENGZ", "IC"],
    "count": ["PENC", "DMC", "DMGZ", "IC"],
    "count_bar": ["DMM", "VB", "PENOG", "IC"],
    "rpm": ["IC", "DMM", "PENGZ", "DMGZ"],
    "count_classic": ["PEN20", "PENOG", "VB", "IC"],
    "count_z": ["PENZ", "DMX", "DMC", "IC"],
    "excite": ["DMX", "PENZ", "DMC", "IC"],
    "punch": ["DMC", "PENC", "VB", "IC"],
    "mogera": ["DMGZ", "PENGZ", "DMC", "IC"],
}
NEEDED = sorted({m for party in PARTIES.values() for m in party})

#: The shakes that land a Count Match Color pet's own colour, its Megahit:
#: the Pendulum Color manual's chart (Red at 12 for Vaccine and Free, Yellow
#: from 7 for Data, Blue from 2 for Virus).
COLOUR_MEGAHIT_SHAKES = {"Va": 12, "": 12, "Da": 7, "Vi": 2}
#: The arrows a stage 3 pet is asked for in Count Match Z (three slots):
#: Free and Vaccine the whole meter, Data one less, Virus one.
ARROWS_ASKED_STAGE_3 = {"Va": 3, "": 3, "Da": 2, "Vi": 1}


@unittest.skipUnless(md.has_modules(*NEEDED), "modules folder not present")
class MinigameOutcomeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness import Env
        cls.env = Env("240x240")

    def setUp(self):
        from models.game_pet import GamePet
        self.env.reset(seed=7)
        # Whatever the time of day, the party is awake to train.
        sleep = mock.patch.object(GamePet, "should_sleep", return_value=False)
        sleep.start()
        self.addCleanup(sleep.stop)
        quests = mock.patch("training.training.update_quest_progress")
        self.quests = quests.start()
        self.addCleanup(quests.stop)
        #: The input mode a play starts in (None: the fixture's, keys).
        self.input_mode = None

    # ------------------------------------------------------------ playing
    def start(self, key, party=None, prepare=None):
        """Back to the fixture, the party in the save, then *key* started
        from its menu button (after *prepare()*, for anything the minigame
        reads as it is built)."""
        self.env.reset(seed=7, input_mode=self.input_mode)
        self.quests.reset_mock()
        md.make_party(self.env, party or PARTIES[key])
        self.fm_before = md.balance("IC", "Fight Money")
        if prepare is not None:
            prepare()
        return md.MinigameRun(self.env, key)

    def play(self, key, charge=None, step=None, party=None):
        """Start *key*, call *charge(run)* once its charge phase is on, call
        *step()* every frame, and play on until the scene leaves."""
        run = self.start(key, party)
        if charge is not None:
            run.until_charge()
            charge(run)
        run.finish(step=step)
        return run

    # ------------------------------------------------------------ checking
    def check(self, run, grade, won, trophies=0, phase2=False, anguirus=(), grades=True):
        """The run ended through its result, once, with *grade* and *won* for
        every pet, and every pet's stats are its module's for that outcome."""
        from models.game_quest import QuestType
        self.assertTrue(run.left(), f"{run.key} did not hand the screen back")
        self.assertEqual(type(run.game.scene).__name__, "SceneMainGame")
        self.assertIsNotNone(run.result, f"{run.key} ended without applying a result")
        self.assertEqual(run.applied, 1, "the result was applied more than once")
        self.assertEqual(run.result.won, won, "verdict")
        if grades:
            self.assertEqual(run.result.grade, grade, "grade on the result screen")
            for pet in run.pets:
                self.assertEqual(run.result.grades[pet], grade, f"{pet.module} grade")
        for pet in run.pets:
            self.assertEqual(run.result.won_for[pet], won, f"{pet.module} verdict")
            before, after = run.before[pet], run.after[pet]
            exp = md.expected_training(pet.module, before, grade, won, phase2=phase2,
                                       anguirus=pet in anguirus)
            with self.subTest(module=pet.module, pet=pet.name):
                self.assertEqual(after["effort"], exp["effort"], "effort")
                if exp["strength"] is None:
                    # A strength gain of -1 fills the meter outright.
                    self.assertGreaterEqual(after["strength"], 4, "strength meter filled")
                else:
                    self.assertEqual(after["strength"], exp["strength"], "strength")
                self.assertEqual(after["weight"], exp["weight"], "weight")
                self.assertEqual(after["reliability"], exp["reliability"], "reliability")
                self.assertEqual(after["gcell_points"], exp["gcell_points"], "G-Cells")
                self.assertEqual(after["disturbance_penalty"], exp["disturbance_penalty"],
                                 "disturbance penalty")
                # Only a pet whose module shows Trophies earns them (owner, 2026-10-17).
                from core import pet_stats
                from utils.module_utils import get_module
                earns = pet_stats.tracks_trophies(getattr(get_module(pet.module), "visible_stats", []))
                self.assertEqual(after["trophies"], before["trophies"] + (trophies if earns else 0), "trophies")
                # A training costs nothing, or what a battle does where the
                # module says so (the iC: one hunger heart; owner, 2026-10-17).
                module = get_module(pet.module)
                cost = (int(module.battle_cost_amount)
                        if getattr(module, "training_uses_battle_cost", False)
                        and module.battle_cost_type == "Hunger" else 0)
                self.assertEqual(after["hunger"], max(0, before["hunger"] - cost), "the training's hunger cost")
                self.assertEqual(after["state"], exp["state"], "mood after the result")
                self.assertEqual(after["vital_activities"], exp["vital_activities"])
        # The TRAINING quest counts a won training, once.
        calls = [c for c in self.quests.call_args_list if c.args and c.args[0] == QuestType.TRAINING]
        self.assertEqual(len(calls), 1 if won else 0, "TRAINING quest progress")
        # The iC's Fight Money: its module is paid once, at the best outcome
        # among its pets (they all share this one here).
        if any(p.module == "IC" for p in run.pets):
            level = grade if won else 0
            gain = md.fight_money_gain("IC", level)["Fight Money"]
            self.assertEqual(md.balance("IC", "Fight Money") - self.fm_before, gain, "Fight Money")
            # Other modules with a currency are paid too: only the iC's
            # line is checked.
            ic_paid = [row for row in run.result.paid if row[0] == "IC"]
            self.assertEqual(ic_paid, [("IC", "Fight Money", gain)] if gain else [])
        self.assertEqual(self.env.error_logs(), [], "errors logged during the play")

    # ================================================================ Dummy
    def test_dummy_a_full_bar_is_excellent_and_wins_a_trophy(self):
        run = self.play("dummy", charge=lambda r: r.send("A", 14))
        self.check(run, grade=3, won=True, trophies=1)

    def test_dummy_each_band_of_the_bar_pays_its_own_grade(self):
        for presses, grade in ((11, 1), (12, 1), (13, 2)):
            with self.subTest(presses=presses):
                run = self.play("dummy", charge=lambda r: r.send("A", presses))
                self.check(run, grade=grade, won=True)

    def test_dummy_an_empty_bar_is_bad_and_still_ends(self):
        """Ten presses or fewer fire no shot; it used to wait for one forever."""
        for presses in (0, 10):
            with self.subTest(presses=presses):
                run = self.play("dummy", charge=lambda r: r.send("A", presses))
                self.check(run, grade=0, won=False)

    def test_a_pp_multiplier_triples_the_trophy(self):
        """A running PP x3 item (the VBE's, utils.card_battle) triples the
        trophy -- the PP -- the top grade pays its pet, and only its pet. The
        DM20 pet earns none: its module does not show Trophies."""
        import time
        boost = {"item": "PP x3", "targets": ["pp"], "amount": 3, "until": time.time() + 3600}
        party = ["DM20", ("VB", {"active_boost": boost})]
        run = self.play("dummy", party=party, charge=lambda r: r.send("A", 14))
        self.assertEqual(run.result.grade, 3)
        trophies = {p.module: run.after[p]["trophies"] - run.before[p]["trophies"] for p in run.pets}
        self.assertEqual(trophies, {"DM20": 0, "VB": 3})

    def test_dummy_by_touch(self):
        """Tapping the screen charges the bar as A does."""
        self.input_mode = self.env.rg.TOUCH_MODE

        def tap(run):
            for _ in range(14):
                self.env.tap(run.game, (120, 120))
        run = self.play("dummy", charge=tap)
        self.check(run, grade=3, won=True, trophies=1)

    # ========================================================= Head to Head
    def head_step(self, run, right):
        """Answer each strike: UP sends B and DOWN sends A, and a strike is
        won by answering the opposite of the pattern's letter. The first
        *right* strikes are answered right, the rest wrong."""
        def step():
            hc = run.mode.head_charge
            if run.phase != "alert" and hc.phase == "charge" and hasattr(hc, "left_y"):
                letter = hc.pattern[hc.current_index]
                good = "UP" if letter == "A" else "DOWN"
                bad = "DOWN" if good == "UP" else "UP"
                run.send(good if hc.current_index < right else bad)
        return step

    def test_head_to_head_five_strikes_won_is_excellent(self):
        run = self.start("head")
        run.finish(step=self.head_step(run, 5))
        self.check(run, grade=3, won=True, trophies=1)

    def test_head_to_head_grades_by_strikes_won(self):
        """3 of 5 is Good, 4 Great; a won session gives each pet a trophy
        (Head to Head's own rule: it awards one for any win)."""
        for right, grade in ((3, 1), (4, 2)):
            with self.subTest(won_strikes=right):
                run = self.start("head")
                run.finish(step=self.head_step(run, right))
                self.check(run, grade=grade, won=True, trophies=1)

    def test_head_to_head_losing_the_strikes_is_bad(self):
        for right in (0, 2):
            with self.subTest(won_strikes=right):
                run = self.start("head")
                run.finish(step=self.head_step(run, right))
                self.check(run, grade=0, won=False)

    def test_head_to_head_by_touch_on_its_arrow_buttons(self):
        self.input_mode = self.env.rg.TOUCH_MODE
        run = self.start("head")

        def step():
            hc = run.mode.head_charge
            if run.phase != "alert" and hc.phase == "charge" and hasattr(hc, "left_y"):
                button = hc.up_button if hc.pattern[hc.current_index] == "A" else hc.down_button
                self.env.tap(run.game, button.rect.center)
        run.finish(step=step)
        self.check(run, grade=3, won=True, trophies=1)

    # BUG (tests/findings/training.md, "Head to Head never shows the currency
    # screen"): HeadToHeadTraining.update puts the phase back to "result"
    # every frame the head charge is complete, so the currency screen that
    # finish_training opens is replaced by a second result screen.
    # Fixed 2026-10-13; kept as a regression test.
    def test_head_to_head_shows_the_currency_it_earned(self):
        run = self.start("head", ["DMC", "IC"])
        step = self.head_step(run, 5)
        for _ in range(md.HANG_FRAMES):
            if run.result is not None:
                break
            step()
            run.frames(1)
        self.assertTrue(run.result.paid, "an iC pet's win pays Fight Money")
        self.assertEqual(run.phase, "currency")
        run.frames(2)
        self.assertEqual(run.phase, "currency", "the currency screen stays up")

    # =================================================== Count Match Color
    def shake_to(self, shakes):
        def charge(run):
            run.until(lambda: run.mode.count_match.phase == "count", what="the count")
            run.send("Y", shakes)
        return charge

    def test_count_match_color_the_attributes_own_colour_is_a_megahit(self):
        """Vaccine lands Red, Data Yellow, Virus Blue: five super hits."""
        for attribute in ("Va", "Da", "Vi"):
            with self.subTest(attribute=attribute):
                party = [("PENC", {"attribute": attribute}), "DMC", "DMGZ", "IC"]
                run = self.play("count", party=party,
                                charge=self.shake_to(COLOUR_MEGAHIT_SHAKES[attribute]))
                self.assertEqual(run.mode.super_hits[run.mode.pets[0]], 5)
                self.check(run, grade=3, won=True, trophies=1)

    def test_count_match_color_no_shakes_is_bad_and_still_ends(self):
        run = self.play("count", charge=self.shake_to(0))
        self.check(run, grade=0, won=False)

    def test_count_match_color_plays_every_colour_at_every_stage(self):
        """The charge ends and the shots fly whatever the stage and colour (the
        six-round rows once crashed the five-wave training)."""
        from utils.module_utils import get_module
        stages = [s for s in range(1, 9)
                  if any((m.get("atk_main") or 0) > 0 for m in get_module("PENC").get_monsters_by_stage(s))]
        self.assertGreaterEqual(len(stages), 5, stages)
        groups = [stages[i:i + 4] for i in range(0, len(stages), 4)]
        for group in groups:
            for shakes in (0, 2, 7, 12, 20):
                with self.subTest(stages=group, shakes=shakes):
                    party = [("PENC", {"stage": s}) for s in group]
                    run = self.play("count", party=party, charge=self.shake_to(shakes))
                    self.assertIsNotNone(run.result)
                    self.assertTrue(run.left())
                    self.assertEqual(self.env.error_logs(), [])

    # ----- the PENGZ's variant, played when the first pet is a PENGZ Digimon
    def pengz_megahit_shakes(self, pet):
        from utils import pengz_count_match
        for shakes in pengz_count_match.BUCKET_STARTS:
            if pengz_count_match.score(pet, shakes) == 14:
                return shakes
        self.fail("no bucket scores the Megahit row")

    def pengz_play(self, best, anguirus):
        party = md.make_party(self.env, ["PENGZ", "PENC", "DMGZ", "IC"])
        if anguirus:
            party[0].pengz_trainings = 4          # this is the fifth
        self.quests.reset_mock()
        self.fm_before = md.balance("IC", "Fight Money")
        shakes = self.pengz_megahit_shakes(party[0]) if best else 0
        run = md.MinigameRun(self.env, "count")
        run.until_charge()
        self.shake_to(shakes)(run)
        run.finish()
        return run

    def test_count_match_pengz_megahit_pays_its_g_cells(self):
        for anguirus in (False, True):
            with self.subTest(anguirus=anguirus):
                self.env.reset(seed=7)
                run = self.pengz_play(best=True, anguirus=anguirus)
                self.assertEqual(run.mode.anguirus, anguirus)
                pengz = {p for p in run.pets if p.module == "PENGZ"}
                self.check(run, grade=3, won=True, trophies=1, anguirus=pengz if anguirus else ())

    def test_count_match_pengz_no_shakes_is_bad_and_costs_g_cells(self):
        for anguirus in (False, True):
            with self.subTest(anguirus=anguirus):
                self.env.reset(seed=7)
                run = self.pengz_play(best=False, anguirus=anguirus)
                pengz = {p for p in run.pets if p.module == "PENGZ"}
                self.check(run, grade=0, won=False, anguirus=pengz if anguirus else ())

    # ============================================================ Count Bar
    def test_count_bar_a_full_count_is_a_megahit_for_every_pet(self):
        run = self.play("count_bar", charge=lambda r: (r.frames(1), r.send("A", 40)))
        self.assertTrue(run.mode.megahit)
        self.check(run, grade=3, won=True, trophies=1)

    def test_count_bar_grades_each_pet_on_its_own_row(self):
        """One count of 24 is a Megahit at stage 3, Good at stage 4 and Bad
        at stage 6 (the Mini's columns): each pet is paid its own row, and the
        iC module once, at its pet's grade."""
        from battle.sim.battle_utils import get_dmm_grade, get_dmm_pattern
        party = [("DMM", {"stage": 3}), ("DMM", {"stage": 4}), ("PENC", {"stage": 6}), "IC"]
        run = self.play("count_bar", party=party, charge=lambda r: (r.frames(1), r.send("A", 24)))
        self.assertIsNotNone(run.result)
        grades = {}
        for pet in run.pets:
            grade = get_dmm_grade(get_dmm_pattern(24, stage=pet.stage, attribute=pet.attribute))
            grades[pet] = grade
            exp = md.expected_training(pet.module, run.before[pet], grade, grade > 0)
            with self.subTest(module=pet.module, stage=pet.stage):
                self.assertEqual(run.result.grades[pet], grade)
                self.assertEqual(run.result.won_for[pet], grade > 0)
                for field in ("effort", "strength", "weight", "reliability", "state"):
                    self.assertEqual(run.after[pet][field], exp[field], field)
        self.assertEqual(sorted(set(grades.values())), [0, 1, 3], "the stages really differ")
        ic_grade = max(g for p, g in grades.items() if p.module == "IC")
        self.assertEqual(md.balance("IC", "Fight Money") - self.fm_before,
                         md.fight_money_gain("IC", ic_grade)["Fight Money"])

    def test_count_bar_no_presses_is_bad_and_still_ends(self):
        run = self.play("count_bar")
        self.check(run, grade=0, won=False)

    def test_count_bar_presses_after_the_bars_stop_do_not_count(self):
        run = self.start("count_bar")
        run.until(lambda: run.phase == "charge" and run.mode.count_bar.is_showing_result(),
                  what="the result step")
        run.send("A", 40)
        run.finish()
        self.check(run, grade=0, won=False)

    # ================================================================== RPM
    def test_rpm_a_steady_pace_at_the_digimons_rpm_is_a_megahit(self):
        from battle.sim.battle_utils import ic_rpm_target
        from ui.minigames.rpm_rhythm import MS_PER_RPM, ZERO_RPM_INTERVAL_MS
        run = self.start("rpm")
        targets = {ic_rpm_target(p) for p in run.pets}
        self.assertEqual(len(targets), 1, "the party shares one RPM target")
        interval = ZERO_RPM_INTERVAL_MS - targets.pop() * MS_PER_RPM
        every = max(2, round(interval / 33))
        run.until(lambda: run.phase == "charge" and run.mode.count_bar.start_ticks is not None,
                  what="the RPM clock")
        while run.mode.count_bar.is_counting():
            run.send("A")
            run.frames(every)
        run.finish()
        self.assertEqual(run.mode.count_bar.get_bars(), 10)
        self.check(run, grade=3, won=True, trophies=1)

    def test_rpm_no_presses_is_bad_and_still_ends(self):
        run = self.play("rpm")
        self.check(run, grade=0, won=False)

    def test_rpm_mashing_is_not_a_rhythm(self):
        """Forty presses in one instant earn nothing: the iC scores the pace."""
        run = self.play("rpm", charge=lambda r: (r.frames(1), r.send("A", 40)))
        self.check(run, grade=0, won=False)

    # ================================================== Count Match Classic
    # Graded on the battle charge's 0-40 bands since 2026-10-17 (owner: one
    # meter, one grading; training used 0-14 and called 20 shakes EXCELLENT).
    def test_count_match_classic_a_full_meter_is_excellent_with_a_trophy(self):
        run = self.play("count_classic", charge=lambda r: (r.frames(1), r.send("Y", 40)))
        self.check(run, grade=3, won=True, trophies=1)

    def test_count_match_classic_each_band_pays_its_own_grade(self):
        for shakes, grade in ((30, 1), (37, 2)):
            with self.subTest(shakes=shakes):
                run = self.play("count_classic", charge=lambda r: (r.frames(1), r.send("Y", shakes)))
                self.check(run, grade=grade, won=True)

    def test_count_match_classic_no_shakes_is_bad_and_still_ends(self):
        """No shot is fired; it used to wait for one forever."""
        run = self.play("count_classic")
        self.check(run, grade=0, won=False)

    def test_count_match_classic_grades_as_a_battle_charge_does(self):
        """Twenty shakes are BAD in a battle (minigame_result), so in training too."""
        from ui.minigames.minigame_session import minigame_result
        run = self.play("count_classic", charge=lambda r: (r.frames(1), r.send("Y", 20)))
        self.assertEqual(minigame_result("Count Match Classic", strength=20), 0)
        self.check(run, grade=0, won=False)

    # ======================================================== Count Match Z
    def test_count_match_z_the_arrows_asked_for_are_excellent(self):
        def charge(run):
            run.until(lambda: run.mode.count_match_z.phase == "count", what="the count")
            first = run.mode.pets[0]
            run.send("Y", ARROWS_ASKED_STAGE_3[first.attribute or ""])
        run = self.play("count_z", charge=charge)
        self.check(run, grade=3, won=True, trophies=1)

    def test_count_match_z_no_shakes_is_bad_and_still_ends(self):
        run = self.play("count_z")
        self.check(run, grade=0, won=False)

    # =============================================================== Excite
    def excite(self, value, party=None):
        """Stop the Xai bar's arrow over a zone worth *value* (3 red, 2 yellow,
        1 blue, 0 grey), watching the arrow the way the player does."""
        def slowest():
            self.env.gg.xai = 7                  # XAI 7 sweeps slowest
        run = self.start("excite", party, prepare=slowest)
        run.until_charge()
        bar = run.mode.xaibar

        def over():
            cx = bar._drawn_cx
            return cx is not None and (bar._sample_color_at(cx) or 0) == value
        run.until(over, limit=170, what=f"the arrow over a {value} zone")
        run.send("A")
        run.finish()
        self.assertEqual(bar.selected_strength, value)
        return run

    def test_excite_red_is_excellent_with_a_trophy(self):
        self.check(self.excite(3), grade=3, won=True, trophies=1)

    def test_excite_yellow_is_great(self):
        self.check(self.excite(2), grade=2, won=True)

    # BUG (tests/findings/training.md, "Excite pays a Good stop as Great"):
    # ExciteTraining.get_attack_count maps the bar's 1 (blue, Good) to 2, so
    # a Good stop trains at the Great row of every table.
    # Fixed 2026-10-13; kept as a regression test.
    def test_excite_blue_is_good(self):
        self.check(self.excite(1), grade=1, won=True)

    def test_excite_grey_is_bad(self):
        self.check(self.excite(0), grade=0, won=False)

    def test_excite_with_no_press_stops_itself_and_ends(self):
        run = self.play("excite")
        self.assertTrue(run.mode.xaibar.stopped)
        self.assertIsNotNone(run.result)

    # ================================================================ Punch
    def test_punch_twenty_is_excellent_with_two_trophies(self):
        run = self.play("punch", charge=lambda r: (r.frames(2), r.send("Y", 20)))
        self.check(run, grade=3, won=True, trophies=2)

    def test_punch_each_band_pays_its_own_grade(self):
        """10-14 Good, 15-19 Great (and a trophy)."""
        for shakes, grade, trophies in ((10, 1, 0), (14, 1, 0), (15, 2, 1), (19, 2, 1)):
            with self.subTest(shakes=shakes):
                run = self.play("punch", charge=lambda r: (r.frames(2), r.send("Y", shakes)))
                self.check(run, grade=grade, won=True, trophies=trophies)

    def test_punch_no_shakes_is_bad_and_still_ends(self):
        """Eighteen seconds of nothing, then no shot; it used to wait forever."""
        for shakes in (0, 9):
            with self.subTest(shakes=shakes):
                run = self.play("punch", charge=lambda r: (r.frames(2), r.send("Y", shakes)))
                self.check(run, grade=0, won=False)

    # =============================================================== Mogera
    def mogera(self, counters, presses):
        """Counter the first *counters* Anti-G shots with the right arrow and
        let the rest through, then press A *presses* times in the charge."""
        run = self.start("mogera")
        pressed = []

        def step():
            mode = run.mode
            if mode.phase == "counter" and mode.counter_game:
                cg = mode.counter_game
                if (cg.phase == "active" and cg.attack_delay_timer == 0 and cg.attack_x >= 0
                        and not cg.has_countered_current and not cg.counter_input_locked
                        and cg.current_attack_index < min(counters, cg.total_attacks)):
                    run.send("UP" if cg.attacks[cg.current_attack_index] == "top" else "DOWN")
            elif mode.phase == "charge" and not pressed:
                pressed.append(True)
                run.send("A", presses)
        run.finish(step=step)
        self.assertEqual(run.mode.countered_count, counters)
        return run

    def test_mogera_both_phases_cleared_is_excellent(self):
        run = self.mogera(5, 10)
        self.check(run, grade=3, won=True, trophies=1, phase2=True)

    def test_mogera_no_counters_is_bad_a_phase_one_failure(self):
        run = self.mogera(0, 0)
        self.check(run, grade=0, won=False, phase2=False)

    def test_mogera_a_weak_charge_after_the_counters_is_a_phase_two_failure(self):
        """M.O.G.E.R.A. survives: a loss (DMGZ's phase-2 G-Cells) that still
        pays Strength, "whether or not you succeed" (DMGZ manual): the Good row."""
        run = self.mogera(5, 0)
        self.check(run, grade=1, won=False, phase2=True)

    # Mogera's verdict and grade disagreed (tests/findings/training.md 4):
    # the verdict read the charge and the grade wanted all five counters.
    # Owner, 2026-10-17: like the device. Fixed; kept as a regression test.
    def test_mogera_follows_the_dmgz_manual(self):
        """Phase 1 cleared (3+ counters) and the meter built destroys
        M.O.G.E.R.A.: a win; fewer than 3 counters pays nothing."""
        run = self.mogera(4, 12)
        self.check(run, grade=3, won=True, phase2=True)
        run = self.mogera(2, 12)
        self.check(run, grade=0, won=False, phase2=False)

    # ======================================================== every minigame
    def test_every_minigame_has_an_outcome_test(self):
        """A minigame added to the menu needs its win and loss here too."""
        from scenes.scene_training import TRAINING_MODES
        self.assertEqual(sorted(TRAINING_MODES), sorted(PARTIES))


if __name__ == "__main__":
    unittest.main()
