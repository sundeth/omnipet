"""Every iC Bonus minigame can be won and lost, and pays by outcome.

Checklist TRN-02 (every minigame can be played to its end and won) and
TRN-03 (every minigame applies its rewards by outcome); tracker ICX-09 (the
iC training minigames: can be won, rewards). The Digivice iC's own games in
scenes.scene_training.BONUS_MODES -- Building Smash, Poop Dodge, Shuffle
(10X) and Digi Whack, Digi Mash, Gotcha! (20X) -- are started from the training
scene's Bonus list (and once from the Battle scene's Specials hub, the way
the module's Minigames tile opens them) with two iC pets and one from
another module, and played headless the way the player plays them.

They are money games, not training (training.ic_minigame): a play costs
each iC player a hunger heart whatever happens; the grade is the stages
cleared (Shuffle: the finds); the prize is the device's ladder, paid once
in the module's currency (shop.json's Fight Money, capped at its cap); and
only a success raises Reliability by the module's
reliability_minigame_success. Nothing else moves -- no effort, Strength,
weight, trophies or G-Cells, no TRAINING quest step -- and the pet from
another module neither plays nor pays.

For each game: a perfect play reaches the top grade and its prize; a
failing play reaches BAD, pays nothing and still ends; the grades between
pay their own rung.
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

#: Two iC Digimon (they share the game; the module is paid once) and a
#: Digital Monster COLOR one, which can play none of them.
PARTY = ["IC", ("IC", {"version": 2}), "DMC"]
FIGHT_MONEY = "Fight Money"

#: The prizes, by stages cleared, as the iC books print them.
BUILDING_SMASH_PRIZES = (0, 10, 20, 50)
POOP_DODGE_PRIZES = (0, 10, 20, 50)
DIGI_WHACK_PRIZES = (0, 10, 30, 50)
GOTCHA_PRIZES = (0, 10, 30, 50)


def shuffle_prize(finds):
    """The book's ladder: 5 P for the first find, doubling to the tenth."""
    return 5 * 2 ** (finds - 1) if finds else 0


#: Digi Mash: presses -> (grade, prize, success): Puwamon, Falcomon from 16,
#: Peckmon from 21, LoaderLeomon from 26, the top tier from 31.
DIGI_MASH = {0: (0, 0, False), 15: (0, 0, False), 16: (1, 10, False), 21: (2, 20, False),
             26: (2, 30, False), 31: (3, 50, True), 40: (3, 50, True)}


@unittest.skipUnless(md.has_modules("IC", "DMC"), "modules folder not present")
class BonusMinigameOutcomeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness import Env
        cls.env = Env("240x240")

    def setUp(self):
        from models.game_pet import GamePet
        self.env.reset(seed=11)
        sleep = mock.patch.object(GamePet, "should_sleep", return_value=False)
        sleep.start()
        self.addCleanup(sleep.stop)
        quests = mock.patch("training.training.update_quest_progress")
        self.quests = quests.start()
        self.addCleanup(quests.stop)
        self.input_mode = None

    # ------------------------------------------------------------ playing
    def start(self, key, balance=0, seed=11):
        self.env.reset(seed=seed, input_mode=self.input_mode)
        self.quests.reset_mock()
        md.make_party(self.env, PARTY)
        if balance:
            from utils.currency_utils import add_currency
            add_currency("IC", FIGHT_MONEY, balance)
        self.fm_before = md.balance("IC", FIGHT_MONEY)
        return md.MinigameRun(self.env, key, bonus=True)

    def play(self, key, step, **kwargs):
        run = self.start(key, **kwargs)
        run.finish(step=lambda: step(run))
        return run

    # ------------------------------------------------------------ checking
    def check(self, run, grade, prize, succeeded):
        rel = md.module_json("IC").get("reliability_minigame_success", 0)
        mode = run.mode
        self.assertTrue(run.left(), f"{run.key} did not hand the screen back")
        self.assertEqual(run.applied, 1, "the result was applied more than once")
        self.assertEqual(run.result.grade, grade, "grade")
        self.assertEqual(run.result.won, grade > 0, "a graded play is a won one")
        self.assertEqual(mode.prize, prize, "prize")
        self.assertEqual(mode.succeeded, succeeded, "success")
        self.assertEqual(sorted(p.module for p in run.pets), ["IC", "IC"], "only iC Digimon play")
        # Paid once, in the module's currency, up to its cap.
        cap = next(c for c in md.module_json("IC", "shop.json")["currency"]
                   if c["name"] == FIGHT_MONEY).get("cap") or 10 ** 9
        paid = min(prize, max(0, cap - self.fm_before))
        self.assertEqual(md.balance("IC", FIGHT_MONEY) - self.fm_before, paid, "Fight Money")
        self.assertEqual(run.result.paid, [("IC", FIGHT_MONEY, paid)] if paid else [])
        for pet in run.party:
            before, after = run.before[pet], run.after[pet]
            with self.subTest(module=pet.module, pet=pet.name):
                if pet.module == "IC":
                    self.assertEqual(after["hunger"], max(0, before["hunger"] - 1), "a play costs a heart")
                    self.assertEqual(after["reliability"],
                                     min(31, before["reliability"] + (rel if succeeded else 0)),
                                     "Reliability")
                else:
                    self.assertEqual(after["hunger"], before["hunger"], "a non-player pays nothing")
                    self.assertEqual(after["reliability"], before["reliability"])
                for field in ("effort", "strength", "weight", "trophies", "gcell_points",
                              "disturbance_penalty", "vital_activities"):
                    self.assertEqual(after[field], before[field], f"{field}: not a training")
        self.assertFalse(self.quests.called, "a money game is not a training quest step")
        self.assertEqual(self.env.error_logs(), [], "errors logged during the play")

    # ======================================================= Building Smash
    def smash(self, hits):
        """Stop the cursor under the bar for the first *hits* stops, then
        stop it at once (at the box's edge, a miss)."""
        done = []

        def step(run):
            m = run.mode
            if m.phase == "charge" and m.step == "aim":
                first, last = m.target()
                if len(done) >= hits or first <= m.apex() <= last:
                    done.append(True)
                    run.send("A")
        return step

    def test_building_smash_three_stages_are_excellent(self):
        self.check(self.play("building_smash", self.smash(9)), 3, 50, True)

    def test_building_smash_pays_the_stages_cleared(self):
        for hits, stages in ((3, 1), (6, 2)):
            with self.subTest(stages=stages):
                run = self.play("building_smash", self.smash(hits))
                self.check(run, stages, BUILDING_SMASH_PRIZES[stages], False)

    def test_building_smash_a_first_miss_is_bad(self):
        self.check(self.play("building_smash", self.smash(0)), 0, 0, False)

    def test_building_smash_by_touch(self):
        self.input_mode = self.env.rg.TOUCH_MODE

        def step(run):
            m = run.mode
            if m.phase == "charge" and m.step == "aim":
                first, last = m.target()
                if first <= m.apex() <= last:
                    self.env.tap(run.game, m.lcd_rect().center)
        self.check(self.play("building_smash", step), 3, 50, True)

    # =========================================================== Poop Dodge
    @staticmethod
    def dodge_plan(game):
        """The lane to be in at each view of the course, dodging every poop:
        a search over (view, lane), stepping only through free lanes."""
        from training import poop_dodge as pd
        end = game.goal_edges[3] - pd.CLEAR_PAST
        parent = {game.start_view: {pd.START_LANE: None}}
        for view in range(game.start_view, end, -1):
            nxt = {}
            for lane in parent[view]:
                for way in (-1, 1):
                    target = lane
                    while 0 <= target < pd.LANES and not game.hits(view, target):
                        if not game.hits(view - 1, target):
                            nxt.setdefault(target, lane)
                        target += way
            if not nxt:
                return None
            parent[view - 1] = nxt
        lane = next(iter(parent[end]))
        path = {end: lane}
        for view in range(end, game.start_view):
            lane = parent[view][lane]
            path[view + 1] = lane
        return path

    def dodge(self, stages):
        """Dodge everything until *stages* are cleared, then step into the
        first poop beside the Digimon."""
        from training import poop_dodge as pd
        plan = {}

        def step(run):
            m = run.mode
            if m.phase != "charge" or m.step != "run":
                return
            if "path" not in plan:
                plan["path"] = self.dodge_plan(m)
                self.assertIsNotNone(plan["path"], "this course cannot be cleared")
            view = m.view_left()
            if m.cleared < stages:
                target = plan["path"].get(view - 1, m.lane)
                while m.step == "run" and m.lane != target:
                    run.send("UP" if target < m.lane else "DOWN")
            else:
                for action, way in (("UP", -1), ("DOWN", 1)):
                    lane = m.lane + way
                    if 0 <= lane < pd.LANES and m.hits(view, lane):
                        run.send(action)
                        break
        return step

    def test_poop_dodge_dodging_everything_is_excellent(self):
        self.check(self.play("poop_dodge", self.dodge(3)), 3, 50, True)

    def test_poop_dodge_pays_the_stages_cleared(self):
        for stages in (1, 2):
            with self.subTest(stages=stages):
                run = self.play("poop_dodge", self.dodge(stages))
                self.check(run, stages, POOP_DODGE_PRIZES[stages], False)

    def test_poop_dodge_a_hit_in_stage_one_is_bad(self):
        self.check(self.play("poop_dodge", self.dodge(0)), 0, 0, False)

    # ============================================================== Shuffle
    def shuffle(self, finds):
        """Pick Chuumon's bucket for the first *finds* rounds, then the other."""
        def step(run):
            m = run.mode
            if m.phase == "charge" and m.step == "choose":
                bucket = m.where if m.finds < finds else 1 - m.where
                run.send("LEFT" if bucket == 0 else "RIGHT")
                run.send("A")
        return step

    def test_shuffle_ten_finds_end_the_game_excellent(self):
        run = self.play("shuffle", self.shuffle(99))
        self.assertEqual(run.mode.finds, 10)
        self.check(run, 3, shuffle_prize(10), True)

    def test_shuffle_pays_the_ladder_for_the_finds_before_a_miss(self):
        for finds in (1, 2, 3, 5):
            with self.subTest(finds=finds):
                run = self.play("shuffle", self.shuffle(finds))
                self.check(run, min(finds, 3), shuffle_prize(finds), True)

    def test_shuffle_a_first_miss_is_bad(self):
        self.check(self.play("shuffle", self.shuffle(0)), 0, 0, False)

    def test_shuffle_by_touch_on_the_buckets(self):
        self.input_mode = self.env.rg.TOUCH_MODE

        def step(run):
            m = run.mode
            if m.phase == "charge" and m.step == "choose" and m.finds < 3:
                lcd = m.lcd_rect()
                x = lcd.left + lcd.width // 4 if m.where == 0 else lcd.right - lcd.width // 4
                self.env.tap(run.game, (x, lcd.centery))
            elif m.phase == "charge" and m.step == "choose":
                lcd = m.lcd_rect()
                x = lcd.right - lcd.width // 4 if m.where == 0 else lcd.left + lcd.width // 4
                self.env.tap(run.game, (x, lcd.centery))
        self.check(self.play("shuffle", step), 3, shuffle_prize(3), True)

    # =========================================================== Digi Whack
    def whack(self, stages):
        """Whack every Digimon that is out until *stages* are cleared, then
        whack the first hole that has none out."""
        from training import digi_whack as dw

        def step(run):
            m = run.mode
            if m.phase != "charge" or m.step != "play" or m.hit_hole is not None:
                return
            if m.cleared < stages:
                out = [k for k, state in enumerate(m.holes) if state == dw.OUT]
                if out:
                    while m.pointer != out[0]:
                        run.send("RIGHT")
                    run.send("A")
            elif m.holes[m.pointer] != dw.OUT:
                run.send("A")
        return step

    def test_digi_whack_three_stages_are_excellent(self):
        self.check(self.play("digi_whack", self.whack(3)), 3, 50, True)

    def test_digi_whack_pays_the_stages_cleared(self):
        for stages in (1, 2):
            with self.subTest(stages=stages):
                run = self.play("digi_whack", self.whack(stages))
                self.check(run, stages, DIGI_WHACK_PRIZES[stages], False)

    def test_digi_whack_a_first_miss_is_bad(self):
        self.check(self.play("digi_whack", self.whack(0)), 0, 0, False)

    # ============================================================ Digi Mash
    def mash(self, presses):
        done = []

        def step(run):
            m = run.mode
            if m.phase == "charge" and m.step == "mash" and not done:
                done.append(True)
                run.send("A", presses)
        return step

    def test_digi_mash_pays_the_form_the_count_reached(self):
        for presses, (grade, prize, succeeded) in sorted(DIGI_MASH.items()):
            with self.subTest(presses=presses):
                run = self.play("digi_mash", self.mash(presses))
                self.check(run, grade, prize, succeeded)

    def test_fight_money_stops_at_its_cap(self):
        run = self.play("digi_mash", self.mash(31), balance=9990)
        self.assertEqual(md.balance("IC", FIGHT_MONEY), 9999)
        self.check(run, 3, 50, True)

    # ============================================================== Gotcha!
    @staticmethod
    def lands_under(m, fall_ms):
        """Whether Chuumon, walking on as he is, stands under the trap when a
        drop made now, falling a row every *fall_ms*, reaches the row that
        decides it; None when he would turn first (a turn takes a speed at
        random)."""
        from training import gotcha as gt
        decide = m.now() + (gt.DECIDE_ROW - gt.HANG_ROW) * fall_ms
        col, facing, due = m.col, m.facing, m.next_step
        while due <= decide - 1:
            if col == (0 if facing < 0 else gt.LAST_COL):
                return None
            col += facing
            due += m.step_ms
        return abs(col - gt.CENTRE_COL) <= gt.CATCH_RANGE

    def catch(self, stages, press=None):
        """Drop the trap when Chuumon will be under it at either of its rates
        until *stages* are cleared, then when he will be under it at
        neither. *press* drops it (A by default)."""
        from training import gotcha as gt

        def step(run):
            m = run.mode
            if m.phase != "charge" or m.step != "play":
                return
            under = [self.lands_under(m, ms) for ms in gt.FALL_ROW_MS]
            if (all(under) if m.cleared < stages else under == [False, False]):
                (press or (lambda: run.send("A")))()
        return step

    def test_gotcha_three_stages_are_excellent(self):
        self.check(self.play("gotcha", self.catch(3)), 3, 50, True)

    def test_gotcha_pays_the_stages_cleared(self):
        for stages in (1, 2):
            with self.subTest(stages=stages):
                run = self.play("gotcha", self.catch(stages))
                self.check(run, stages, GOTCHA_PRIZES[stages], False)

    def test_gotcha_a_first_miss_is_bad(self):
        self.check(self.play("gotcha", self.catch(0)), 0, 0, False)

    def test_gotcha_by_touch(self):
        self.input_mode = self.env.rg.TOUCH_MODE
        run = self.start("gotcha")
        tap = lambda: self.env.tap(run.game, run.mode.lcd_rect().center)  # noqa: E731
        run.finish(step=lambda: self.catch(1, press=tap)(run))
        self.check(run, 1, GOTCHA_PRIZES[1], False)

    # ====================================================== the Specials hub
    def test_the_specials_minigames_tile_opens_them_and_they_pay(self):
        """Battle > Specials > iC > Minigames opens the Bonus list; Digi Mash
        is chosen there by touch and played to its prize."""
        self.input_mode = self.env.rg.TOUCH_MODE
        env = self.env
        env.reset(seed=11, input_mode=self.input_mode)
        md.make_party(env, PARTY)
        env.gg.configuration.sound_volume = 0
        self.fm_before = md.balance("IC", FIGHT_MONEY)
        env.rg.scene_battle_initial_view = ("specials", {"module_name": "IC"})
        game = env.game("battle")
        env.frames(game, 3)
        view = game.scene.current_view
        self.assertEqual(game.scene.current_view_name, "specials")
        tiles = [t for t in view.tiles if t.special.kind == "minigames"]
        self.assertEqual(len(tiles), 1, "the iC offers its Minigames")
        env.tap(game, tiles[0].rect.center)
        env.frames(game, 3)
        self.assertEqual(type(game.scene).__name__, "SceneTraining")
        self.assertEqual(game.scene.view, "bonus")
        run = md.MinigameRun.on(env, game, "digi_mash")
        button = game.scene.mode_buttons["digi_mash"]
        self.assertTrue(button.visible)
        env.tap(game, button.rect.center)
        run.attach()
        run.finish(step=lambda: self.mash(31)(run))
        self.check(run, 3, 50, True)

    # ======================================================== every minigame
    def test_every_playable_bonus_minigame_has_an_outcome_test(self):
        from scenes.scene_training import BONUS_MODES
        playable = sorted(k for k, spec in BONUS_MODES.items() if spec["cls"] is not None)
        self.assertEqual(playable, ["building_smash", "digi_mash", "digi_whack",
                                    "gotcha", "poop_dodge", "shuffle"])


if __name__ == "__main__":
    unittest.main()
