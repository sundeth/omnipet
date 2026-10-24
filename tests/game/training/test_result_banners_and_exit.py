"""Training fixes from the 2026-10-22 documentation pass, played headless.

9   every result banner is the grade the training pays: BAD for a loss, then
    GOOD, GREAT and EXCELLENT (the Color line's Megahit on top). Dummy 10
    read GREAT and was a loss; Dummy 11-12 read GREAT and paid Good; Count
    Match Classic's grade 1 read GREAT; a surviving M.O.G.E.R.A. read BAD and
    paid Good, 7-13 read GREAT and paid Excellent; the Pendulum Color's 3
    super hits read GOOD and paid Great; the PENGZ's 1 super hit read BAD and
    was a win.
11  B (and the EXIT button, which sends it) leaves the charge of Count Match
    Color, Z and Classic, Count Bar and RPM, as it does Dummy's; it did
    nothing.
13  Head to Head: UP fires along the upper lane, DOWN the lower one (UP flew
    low).
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

NEEDED = ["DM20", "PENC", "PENGZ", "PEN20", "DMGZ", "DMM", "IC", "DMC"]
BANNERS = ("bad", "good", "great", "excellent", "megahit")


@unittest.skipUnless(md.has_modules(*NEEDED), "modules folder not present")
class ResultBannersAndExit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness import Env
        cls.env = Env("240x240")

    def setUp(self):
        from models.game_pet import GamePet
        self.env.reset(seed=7)
        sleep = mock.patch.object(GamePet, "should_sleep", return_value=False)
        sleep.start()
        self.addCleanup(sleep.stop)
        quests = mock.patch("training.training.update_quest_progress")
        quests.start()
        self.addCleanup(quests.stop)

    def start(self, key, party, input_mode=None):
        self.env.reset(seed=7, input_mode=input_mode)
        md.make_party(self.env, party)
        run = md.MinigameRun(self.env, key)
        run.banners = []
        sprite = run.mode.animated_sprite
        for name in BANNERS:
            real = getattr(sprite, "play_" + name)

            def record(duration=1.0, _name=name, _real=real):
                run.banners.append(_name)
                return _real(duration)
            setattr(sprite, "play_" + name, record)
        return run

    def banner(self, run):
        """The result banner shown (the last one played)."""
        self.assertTrue(run.banners, f"{run.key} showed no result banner")
        return run.banners[-1]

    def expect(self, run, grade, top="excellent"):
        self.assertIsNotNone(run.result, f"{run.key} applied no result")
        self.assertEqual(run.result.grade, grade, "grade paid")
        expected = top if grade == 3 else ("bad", "good", "great")[grade]
        if grade == 0 and not run.banners:
            return      # a play that fires no shot may end without a banner
        self.assertEqual(self.banner(run), expected, f"banner for grade {grade}")

    # ------------------------------------------------------------ 9
    def test_dummy_banner_is_the_grade_paid(self):
        for presses, grade in ((10, 0), (11, 1), (12, 1), (13, 2), (14, 3)):
            with self.subTest(presses=presses):
                run = self.start("dummy", ["DM20", "IC"])
                run.until_charge()
                run.send("A", presses)
                run.finish()
                self.expect(run, grade)
                self.assertEqual(run.result.won, grade > 0)

    def test_count_match_classic_banner_is_the_grade_paid(self):
        for shakes, grade in ((20, 0), (30, 1), (37, 2), (40, 3)):
            with self.subTest(shakes=shakes):
                run = self.start("count_classic", ["PEN20", "IC"])
                run.until_charge()
                run.frames(1)
                run.send("Y", shakes)
                run.finish()
                self.expect(run, grade)

    def test_count_match_color_banners_follow_the_grade(self):
        """Whatever the shakes land on, the banner is the grade paid; at least
        one play lands between BAD and the Megahit."""
        seen = set()
        for module in ("PENC", "PENGZ"):
            for shakes in (0, 2, 3, 5, 7, 9, 11, 12):
                with self.subTest(module=module, shakes=shakes):
                    run = self.start("count", [module, "IC"])
                    run.until_charge()
                    run.until(lambda: run.mode.count_match.phase == "count", what="the count")
                    run.send("Y", shakes)
                    run.finish()
                    self.expect(run, run.result.grade, top="megahit")
                    seen.add((module, run.result.grade))
        self.assertTrue({g for _, g in seen} & {1, 2}, seen)

    def test_mogera_banner_is_the_grade_paid(self):
        def play(counters, presses):
            run = self.start("mogera", ["DMGZ", "IC"])
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
            return run
        self.expect(play(5, 0), 1)       # M.O.G.E.R.A. survives: GOOD (read BAD)
        self.expect(play(5, 9), 3)       # destroyed at 9: EXCELLENT (read GREAT)
        self.expect(play(0, 0), 0)

    # ------------------------------------------------------------ 11
    def test_b_and_exit_leave_every_charge(self):
        for key, party, ready in (
                ("count", ["PENC", "IC"], lambda r: r.mode.count_match.phase == "count"),
                ("count_z", ["PENZ" if md.has_modules("PENZ") else "PENC", "IC"], None),
                ("count_classic", ["PEN20", "IC"], None),
                ("count_bar", ["DMM", "IC"], None),
                ("rpm", ["IC", "DMM"], None)):
            for how in ("B", "EXIT"):
                with self.subTest(minigame=key, how=how):
                    # The EXIT button is a touch and mouse control.
                    run = self.start(key, party, self.env.rg.TOUCH_MODE if how == "EXIT" else None)
                    run.until_charge()
                    if ready is not None:
                        run.until(lambda: ready(run), what="the count")
                    if how == "B":
                        run.send("B")
                    else:
                        self.env.tap(run.game, run.scene.training_exit_button.rect.center)
                    run.frames(2)
                    self.assertTrue(run.left(), f"{key}: {how} during the charge did not leave")
                    self.assertIsNone(run.result, "leaving the charge applies no result")

    # ------------------------------------------------------------ 13
    def test_head_to_head_up_fires_along_the_upper_lane(self):
        for action, upper in (("UP", True), ("DOWN", False)):
            with self.subTest(action=action):
                run = self.start("head", ["DMC", "IC"])
                hc = run.mode.head_charge
                run.until(lambda: run.phase != "alert" and hc.phase == "charge"
                          and hasattr(hc, "left_y"), what="the first strike")
                run.send(action)
                y_up = hc.left_y
                shot_y = hc.attack_positions[1][1][1]
                self.assertEqual(shot_y == y_up, upper, f"{action} flew along the wrong lane")


if __name__ == "__main__":
    unittest.main()
