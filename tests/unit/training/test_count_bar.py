"""Count Bar: the Digimon Mini's charge, its bars and its attack table."""

import os
import random
import sys
import unittest
from collections import Counter
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

# These tests live under utilities/claude/tests/, three folders below
# the repo root, so they are not carried in the git repository.
REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SRC = os.path.join(REPO_ROOT, "src")
for path in (SRC, REPO_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

import pygame  # noqa: E402

from core import game_globals, runtime_globals  # noqa: E402
from battle.sim import battle_utils  # noqa: E402
from battle.sim.battle_utils import get_dmm_pattern, is_dmm_megahit  # noqa: E402
from ui.minigames import count_bar  # noqa: E402
from ui.minigames.count_bar import (  # noqa: E402
    BAR_COUNT, CountBar, bar_color, bar_rect, bars_for_count)

#: The table as read off the device: how many rounds of 1, 2, 3 and 4 damage
#: each count throws. The order within a row is shuffled by the device, so
#: this is the whole of what a row says. Count 19 is the Stage 1-3 column of
#: utilities/DMM/attack_stage_count.csv, which a real Agumon's side confirms;
#: the first transcription had copied count 18's row there.
HITS = [
    "5000", "3200", "1220", "0320", "0500", "0230", "0140", "2111",
    "1211", "1121", "1112", "0050", "0050", "0401", "0041", "0104",
    "0302", "1130", "0221", "0023", "0023", "0014", "0014", "0014",
    "0005", "0005", "0005", "0005", "0005", "0005", "0005", "0005",
]


def setUpModule():
    pygame.init()
    pygame.display.set_mode((240, 240))


def tearDownModule():
    # Once per module: quitting between classes would kill the fonts
    # font_load has cached for the next one.
    pygame.quit()


class FakePet:
    """Hashable, as a real pet is: training keys its results on the pet."""

    def __init__(self, **fields):
        self.__dict__.update(fields)


def histogram(pattern):
    counts = Counter(pattern)
    return "".join(str(counts[v]) for v in (1, 2, 3, 4))


class TableTests(unittest.TestCase):
    def test_every_count_throws_what_the_device_threw(self):
        """The Stage 1-3 column, which is also what an unset stage reads."""
        self.assertEqual(len(HITS), battle_utils._dmm_table()["max_count"] + 1)
        for count, hits in enumerate(HITS):
            self.assertEqual(histogram(get_dmm_pattern(count)), hits, count)
            self.assertEqual(histogram(get_dmm_pattern(count, stage=3, attribute="Va")),
                             hits, count)

    def test_the_pool_is_the_guide_s_32(self):
        pool = battle_utils._dmm_table()["patterns"]
        self.assertEqual([p["no"] for p in pool], list(range(32)))
        for entry in pool:
            self.assertEqual(sum(entry["shots"]), 5)
            self.assertEqual(histogram(entry["pattern"]), "".join(map(str, entry["shots"])))

    def test_columns_follow_stage_and_attribute(self):
        from battle.sim.battle_utils import dmm_column
        self.assertEqual(dmm_column(2, "")["name"], "Stage 1-3")
        self.assertEqual(dmm_column(4, "Vi")["name"], "Stage 4 Vi")
        self.assertEqual(dmm_column(4, "Data")["name"], "Stage 4 Da")
        self.assertEqual(dmm_column(4, "Fr")["name"], "Stage 4 Va")
        self.assertEqual(dmm_column(5, "Vi")["name"], "Stage 5 Vi")
        self.assertEqual(dmm_column(7, "Vi")["name"], "Stage 6-7")
        self.assertEqual(dmm_column(8, "Va")["name"], "Stage 6-7")
        self.assertEqual(dmm_column(None, None)["name"], "Stage 1-3")

    def test_every_device_reading_is_in_the_table(self):
        """Read off real Minis, in battle and in training (protocol.txt)."""
        readings = {
            (3, "Va"): {5: 9, 6: 10, 10: 14, 19: 29, 21: 30},
            (4, "Vi"): {0: 0, 7: 11, 10: 14, 11: 15, 17: 21, 19: 23, 20: 24,
                        21: 25, 22: 26, 24: 29, 25: 30, 26: 30, 27: 30,
                        28: 31, 31: 31},
            (4, "Da"): {0: 0, 5: 7, 6: 9, 9: 12, 12: 15, 14: 16, 17: 19,
                        19: 21, 20: 22, 22: 24, 23: 25, 24: 26, 25: 27,
                        26: 29, 27: 30, 28: 30, 29: 31},
        }
        table = battle_utils._dmm_table()
        for (stage, attribute), cells in readings.items():
            column = battle_utils.dmm_column(stage, attribute)
            for count, number in cells.items():
                self.assertEqual(table["patterns"][column["select"][count]]["shots"],
                                 table["patterns"][number]["shots"],
                                 (column["name"], count))

    def test_each_column_climbs_and_meets_the_guide_s_hyper_count(self):
        """A column never falls back, and first reaches #30 at its Hyper count."""
        for column in battle_utils._dmm_table()["columns"]:
            select = column["select"]
            self.assertEqual(len(select), 32, column["name"])
            self.assertEqual(select, sorted(select), column["name"])
            self.assertEqual(select.index(30), column["hyper_start"], column["name"])

    def test_assumptions_are_only_cells_nothing_known_pins(self):
        table = battle_utils._dmm_table()
        names = {c["name"] for c in table["columns"]}
        assumed = {}
        for entry in table["assumptions"]:
            self.assertIn(entry["column"], names)
            self.assertTrue(entry["reason"])
            for count in entry["counts"]:
                self.assertTrue(0 <= count <= 31)
                assumed.setdefault(entry["column"], set()).add(count)
        # Fully known: Stage 1-3 and both Stage 4 columns that have been read
        # end to end. Stage 4 Data's last assumed cell, count 28, was read in
        # training on a Centarumon.
        for known in ("Stage 1-3", "Stage 4 Vi", "Stage 4 Da"):
            self.assertNotIn(known, assumed)
        # A Hyper start the guide gives is never an assumption.
        for column in table["columns"]:
            if column["name"] != "Stage 5 Da":
                self.assertNotIn(column["hyper_start"], assumed.get(column["name"], set()),
                                 column["name"])

    def test_rows_are_shuffled_but_keep_their_values(self):
        rng = random.Random(7)
        orders = {tuple(get_dmm_pattern(5, rng)) for _ in range(50)}
        self.assertGreater(len(orders), 1)
        self.assertTrue(all(sorted(o) == [2, 2, 3, 3, 3] for o in orders))

    def test_counts_outside_the_table_clamp(self):
        self.assertEqual(get_dmm_pattern(-3), [1, 1, 1, 1, 1])
        self.assertEqual(get_dmm_pattern(99), [4, 4, 4, 4, 4])

    def test_megahit_starts_at_twenty_four(self):
        megahits = [c for c in range(40) if is_dmm_megahit(get_dmm_pattern(c))]
        self.assertEqual(megahits[0], 24)
        self.assertEqual(megahits, list(range(24, 40)))


class BarTests(unittest.TestCase):
    def test_geometry(self):
        self.assertEqual(tuple(bar_rect(0)), (30, 222, 12, 8))
        self.assertEqual(tuple(bar_rect(BAR_COUNT - 1)), (198, 166, 12, 64))
        self.assertEqual({bar_rect(i).bottom for i in range(BAR_COUNT)}, {230})
        for i in range(BAR_COUNT - 1):
            self.assertEqual(bar_rect(i + 1).left - bar_rect(i).right, 12)
            self.assertEqual(bar_rect(i + 1).height - bar_rect(i).height, 8)

    def test_colours_run_yellow_to_red(self):
        self.assertEqual(bar_color(0), (255, 210, 0))
        self.assertEqual(bar_color(BAR_COUNT - 1), (255, 0, 0))
        greens = [bar_color(i)[1] for i in range(BAR_COUNT)]
        self.assertEqual(greens, sorted(greens, reverse=True))

    def test_one_bar_per_four_presses(self):
        self.assertEqual([bars_for_count(c) for c in (0, 3, 4, 7, 8, 31, 32, 99)],
                         [0, 0, 1, 1, 2, 7, 8, 8])


class LabelTests(unittest.TestCase):
    def test_counter_wears_the_colour_of_the_bar_it_fills(self):
        from ui.minigames.count_bar import label_color
        self.assertEqual(label_color(0), (255, 210, 0))
        self.assertEqual(label_color(3), bar_color(0))
        self.assertEqual(label_color(4), bar_color(1))
        self.assertEqual(label_color(28), (255, 0, 0))
        self.assertEqual(label_color(99), (255, 0, 0))

    def label_ink(self, width, height, count):
        """The counter's inked pixels, as a rect on the screen.

        The count is drawn in the SECOND step, between `CountMatch2.png`'s
        brackets -- there is no number on screen while the pressing is going
        on -- so the clock is wound past the counting to reach it.
        """
        from ui.minigames.count_bar import label_color
        from ui.ui_manager import UIManager
        with mock.patch.object(runtime_globals, "SCREEN_WIDTH", width), \
                mock.patch.object(runtime_globals, "SCREEN_HEIGHT", height), \
                mock.patch.object(runtime_globals, "UI_SCALE", height / 240):
            ui = UIManager("GREEN")
            with mock.patch.object(pygame.time, "get_ticks", return_value=0):
                game = CountBar(ui)
                game.start()
            game.count = count
            surface = pygame.Surface((width, height), pygame.SRCALPHA)
            with mock.patch.object(pygame.time, "get_ticks",
                                   return_value=count_bar.DURATION_MS):
                game.draw(surface)
        colour = label_color(count)
        top_rows = int(135 * ui.ui_scale) + ui.ui_offset_y
        points = [(x, y) for x in range(width) for y in range(top_rows)
                  if tuple(surface.get_at((x, y)))[:3] == colour]
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return ui, pygame.Rect(min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1)

    def test_the_count_sits_between_the_brackets(self):
        """The result step centres the count in `CountMatch2.png`'s gap, at
        every window size."""
        from ui.minigames.count_bar import LABEL_CENTER_X, LABEL_CENTER_Y
        for width, height in ((240, 240), (480, 480), (720, 720), (800, 480)):
            for count in (0, 6, 17, 65, 99):
                ui, ink = self.label_ink(width, height, count)
                scale = ui.ui_scale
                middle_x = (ink.left + ink.width / 2 - ui.ui_offset_x) / scale
                middle_y = (ink.top + ink.height / 2 - ui.ui_offset_y) / scale
                self.assertLessEqual(abs(middle_x - LABEL_CENTER_X), 1, (width, count))
                self.assertLessEqual(abs(middle_y - LABEL_CENTER_Y), 1, (width, count))
                # Tall enough to read, and clear of the brackets' opening.
                self.assertLessEqual(abs(ink.height / scale - 28), 1, (width, count))

    def test_the_layout_numbers_are_the_sprite_s_own(self):
        """The brackets on `CountMatch2.png` are where the layout says.

        Measured off the sprite rather than written down twice: the left
        bracket's last inked column and the right one's first bound the gap,
        and the row of marks they sit in bounds it vertically.
        """
        from ui.minigames.count_bar import (LABEL_CENTER_X, LABEL_CENTER_Y,
                                            RESULT_PATH)
        sprite = pygame.image.load(RESULT_PATH)
        band = range(56, 98)
        inked = [x for x in range(240)
                 if any(sprite.get_at((x, y))[3] for y in band)]
        # The gap is the one run of blank columns inside the marks.
        gaps = []
        for x in range(inked[0], inked[-1]):
            if x not in inked:
                if gaps and gaps[-1][-1] == x - 1:
                    gaps[-1].append(x)
                else:
                    gaps.append([x])
        widest = max(gaps, key=len)
        self.assertGreater(len(widest), 40, "the brackets' opening")
        self.assertLessEqual(
            abs((widest[0] + widest[-1] + 1) / 2 - LABEL_CENTER_X), 1)
        rows = [y for y in band
                if any(sprite.get_at((x, y))[3] for x in range(240))]
        self.assertLessEqual(
            abs((rows[0] + rows[-1] + 1) / 2 - LABEL_CENTER_Y), 1)

    def test_no_number_while_the_pressing_is_on(self):
        """**Step one shows the bars, not a total.** The counter was on
        screen the whole time while this charge borrowed the iC's RPM
        screen; the Mini shows COUNT! and the bars filling, and the number
        only when the pressing is over."""
        from ui.minigames.count_bar import label_color
        from ui.ui_manager import UIManager
        ui = UIManager("GREEN")
        with mock.patch.object(pygame.time, "get_ticks", return_value=0):
            game = CountBar(ui)
            game.start()
            game.count = 17
            counting = pygame.Surface((240, 240), pygame.SRCALPHA)
            game.draw(counting)
        with mock.patch.object(pygame.time, "get_ticks",
                               return_value=count_bar.DURATION_MS):
            result = pygame.Surface((240, 240), pygame.SRCALPHA)
            game.draw(result)
        colour = label_color(17)
        top = int(120 * ui.ui_scale) + ui.ui_offset_y

        def ink(surface):
            return sum(1 for x in range(surface.get_width())
                       for y in range(top)
                       if tuple(surface.get_at((x, y)))[:3] == colour)

        self.assertEqual(ink(counting), 0, "a number during the counting")
        self.assertGreater(ink(result), 0, "no number on the result step")


class MinigameTests(unittest.TestCase):
    def setUp(self):
        from ui.ui_manager import UIManager
        self.ui = UIManager("GREEN")

    def test_presses_count_until_time_is_up(self):
        """Presses stop at five seconds; the charge ends two seconds later.

        The two are separate now: the count settles when the pressing does,
        and the result step then shows it. A press during that step is
        swallowed rather than counted -- letting it climb after the bars
        stopped is how a player ends up with a charge they did not see
        themselves make -- so `handle_event` still claims the event.
        """
        game = CountBar(self.ui)
        with mock.patch.object(pygame.time, "get_ticks", return_value=1000):
            game.start()
            self.assertTrue(game.handle_event(("A", None)))
            self.assertTrue(game.handle_event(("LCLICK", {"pos": (10, 10)})))
            self.assertFalse(game.handle_event(("B", None)))
            self.assertFalse(game.handle_event(("SHAKE", None)))
        self.assertEqual(game.get_count(), 2)

        with mock.patch.object(pygame.time, "get_ticks",
                               return_value=1000 + count_bar.DURATION_MS):
            self.assertFalse(game.is_counting())
            self.assertTrue(game.is_showing_result())
            # Not over yet: the count still has to be shown.
            self.assertFalse(game.is_time_up())
            self.assertTrue(game.handle_event(("A", None)))
        self.assertEqual(game.get_count(), 2)

        with mock.patch.object(
                pygame.time, "get_ticks",
                return_value=1000 + count_bar.DURATION_MS + count_bar.RESULT_MS):
            self.assertTrue(game.is_time_up())
        self.assertEqual(game.get_count(), 2)

    def test_draws_the_counter_and_lit_bars(self):
        game = CountBar(self.ui)
        game.start()
        for _ in range(9):
            game.handle_event(("A", None))
        surface = pygame.Surface((240, 240))
        game.draw(surface)
        offset = self.ui.scale_position(0, 0)
        lit = bar_rect(1).move(offset).center
        unlit = bar_rect(2).move(offset).center
        self.assertEqual(tuple(surface.get_at(lit))[:3], bar_color(1))
        self.assertNotEqual(tuple(surface.get_at(unlit))[:3], bar_color(2))


class TrainingTests(unittest.TestCase):
    def training(self, count):
        from training.count_bar_training import CountBarTraining
        from ui.ui_manager import UIManager
        with mock.patch.object(game_globals, "pet_list", []), \
                mock.patch.object(runtime_globals, "selected_pets", []):
            training = CountBarTraining(UIManager("GREEN"))
        pet = FakePet(module="DMM", atk_main=1, atk_alt=2)
        training.pets = [pet]
        training.count_bar.count = count
        training.calculate_results()
        return training, pet

    def test_a_row_scores_its_shots(self):
        # nhoko: Single 0, Double 1, Triple 2, Hyper 4.
        from battle.sim.battle_utils import get_dmm_score
        self.assertEqual(get_dmm_score([1, 1, 1, 1, 1]), 0)
        self.assertEqual(get_dmm_score([2, 2, 2, 2, 2]), 5)
        self.assertEqual(get_dmm_score([3, 2, 1, 1, 1]), 3)
        self.assertEqual(get_dmm_score([4, 4, 4, 4, 4]), 20)

    def test_the_score_picks_the_grade(self):
        # 0-5 sheds weight only; 6-11, 12-17 and 18-20 are the strength bands.
        from battle.sim.battle_utils import get_dmm_grade
        rows = {0: [1, 1, 1, 1, 1], 5: [2, 2, 2, 2, 2], 6: [2, 2, 2, 2, 3],
                11: [4, 4, 3, 2, 1], 12: [3, 3, 3, 3, 4], 17: [4, 4, 4, 4, 2],
                18: [4, 4, 4, 4, 3], 20: [4, 4, 4, 4, 4]}
        grades = {score: get_dmm_grade(row) for score, row in rows.items()}
        self.assertEqual(grades, {0: 0, 5: 0, 6: 1, 11: 1, 12: 2, 17: 2, 18: 3, 20: 3})

    def test_training_grades_each_pet_on_its_own_row(self):
        from battle.sim.battle_utils import get_dmm_grade
        training, pet = self.training(0)
        self.assertFalse(training.check_victory())
        self.assertFalse(training.won_for(pet, True))
        for count in range(32):
            training, pet = self.training(count)
            grade = get_dmm_grade(training.patterns[pet])
            self.assertEqual(training.grade_for(pet), grade)
            self.assertEqual(training.check_victory(), grade > 0)
        training, pet = self.training(26)
        self.assertEqual(training.get_attack_count(), 3)

    def test_each_value_draws_its_own_shot(self):
        training, pet = self.training(0)
        main = pygame.Surface((16, 16))
        alt = pygame.Surface((20, 20))
        sprites = {1: main, 2: alt}
        with mock.patch.object(training, "get_attack_sprite",
                               lambda p, attack_id: sprites.get(attack_id)):
            one = training.count_ladder_sprite(pet, 1)
            two = training.count_ladder_sprite(pet, 2)
            three = training.count_ladder_sprite(pet, 3)
            four = training.count_ladder_sprite(pet, 4)
            pet.atk_alt = 0
            four_without_alt = training.count_ladder_sprite(pet, 4)
        self.assertEqual(one.get_size(), (16, 16))
        self.assertGreater(two.get_width(), 16)
        self.assertGreater(three.get_width(), two.get_width())
        # A Hyper is the alt sprite at double size, and a pet without one
        # draws its atk_main at that size instead.
        self.assertEqual(four.get_size(), (40, 40))
        self.assertEqual(four_without_alt.get_size(), (32, 32))

    def test_the_charge_ends_after_the_count_is_shown(self):
        """Five seconds of pressing, then two showing the count.

        The training used to leave the charge the instant the pressing
        stopped, which was right while there was nothing left to see. There
        is now: the count only appears in the second step.
        """
        training, pet = self.training(0)
        training.phase = "charge"
        with mock.patch.object(pygame.time, "get_ticks", return_value=0):
            training.update_charge_phase()
            for _ in range(26):
                training.handle_event(("A", None))
        self.assertEqual(training.phase, "charge")

        with mock.patch.object(pygame.time, "get_ticks",
                               return_value=count_bar.DURATION_MS), \
                mock.patch.object(training, "get_attack_sprite", return_value=None):
            training.update_charge_phase()
        self.assertEqual(training.phase, "charge", "left before showing the count")

        with mock.patch.object(
                pygame.time, "get_ticks",
                return_value=count_bar.DURATION_MS + count_bar.RESULT_MS), \
                mock.patch.object(training, "get_attack_sprite", return_value=None):
            training.update_charge_phase()
        self.assertEqual(training.phase, "wait_attack")
        self.assertEqual(training.count, 26)
        self.assertTrue(training.megahit)


class WireSpriteTests(unittest.TestCase):
    """The Mini numbers its one projectile as the module does."""

    def test_the_projectile_is_not_shifted_either_way(self):
        from battle.sim import protocol_constants
        from battle.sim.dcom_battle_simulator import DComBattleSimulator
        self.assertTrue(protocol_constants.DMM.SHOT_IS_OMNIPET_NUMBERED)

        sim = DComBattleSimulator.__new__(DComBattleSimulator)
        sim.wire = protocol_constants.DMM
        opponent = FakePet(shot1=1, shot2=1, level=1, stage=4,
                           name="Vi", attribute="Vi")
        with mock.patch.object(DComBattleSimulator, "_parse_dmm_opponent",
                               return_value=opponent),                 mock.patch.object(DComBattleSimulator, "_name_opponent",
                                  lambda self, o: None):
            sim.battle_format = "DMM"
            parsed = DComBattleSimulator.parse_opponent(
                sim, ["0089", "12A9", "0009", "F1B9"])
        # A real Mini sends projectile 1 and draws its ordinary shot, which is
        # the module's sprite 1 -- not 2, which is its Hyper.
        self.assertEqual((parsed.shot1, parsed.shot2), (1, 1))


class AdventureTests(unittest.TestCase):
    """A module declaring DMM fights its adventure battles on the Mini's table."""

    @staticmethod
    def digimon(name, stage, attribute, power=40):
        from battle.sim.models import Digimon
        return Digimon(name=name, order=0, traited=0, egg_shake=0, index=0, hp=6,
                       attribute=attribute, power=power, handicap=0, buff=0,
                       mini_game=0, level=1, stage=stage, sick=0, shot1=1,
                       shot2=2, tag_meter=0)

    def simulator(self, charge):
        from battle.sim.global_battle_simulator import GlobalBattleSimulator
        return GlobalBattleSimulator(attribute_advantage=10, damage_limit=99,
                                     battle_format="DMM", charge=charge)

    def test_the_player_throws_its_own_column_for_the_count(self):
        sim = self.simulator(26)
        for stage, attribute in ((3, "Va"), (4, "Da"), (5, "Vi"), (6, "Va")):
            got = sim._pattern_for(self.digimon("Pet", stage, attribute))
            self.assertEqual(histogram(got), histogram(
                get_dmm_pattern(26, stage=stage, attribute=attribute)))

    def test_an_enemy_plays_its_stage_count(self):
        from battle.sim.battle_utils import get_dmm_enemy_pattern
        damage = {1: 1, 2: 2, 3: 3, 4: 6}
        totals = []
        for stage in range(1, 8):
            column = battle_utils.dmm_column(stage, "Va")
            count = column["enemy_counts"][str(stage)]
            row = get_dmm_enemy_pattern(stage, "Va")
            self.assertEqual(histogram(row), histogram(
                get_dmm_pattern(count, stage=stage, attribute="Va")))
            totals.append(sum(damage[v] for v in row))
        self.assertEqual(totals, sorted(totals))
        # Every attribute of one stage lands on an equally strong row.
        for stage in (4, 5):
            rows = [get_dmm_enemy_pattern(stage, a) for a in ("Va", "Da", "Vi")]
            self.assertEqual(len({sum(damage[v] for v in r) for r in rows}), 1)

    def test_a_hyper_costs_six_and_nothing_else_moves(self):
        from battle.sim.global_battle_simulator import GlobalBattleSimulator
        sim = self.simulator(0)
        self.assertEqual([sim._hp_cost(v) for v in (1, 2, 3, 4)], [1, 2, 3, 6])
        other = GlobalBattleSimulator(battle_format="DMX")
        self.assertEqual([other._hp_cost(v) for v in (1, 2, 3, 4, 5)], [1, 2, 3, 4, 5])
        random.seed(7)
        for _ in range(20):
            result = self.simulator(26).simulate(
                [self.digimon("Pet", 3, "Va")], [self.digimon("Enemy", 4, "Vi")])
            for turn in result.battle_log:
                for attack in turn.attacks:
                    expected = {1: 1, 2: 2, 3: 3, 4: 6}[attack.damage] if attack.hit else 0
                    self.assertEqual(attack.hp_damage, expected)

    def test_the_battle_charge_grades_the_pets_own_row(self):
        from ui.minigames.minigame_session import minigame_result
        pet = FakePet(stage=6, attribute="Va")
        for count in (0, 12, 24, 31):
            grades = {minigame_result("Count Bar", count, pet=pet) for _ in range(5)}
            self.assertEqual(grades, {battle_utils.get_dmm_grade(
                get_dmm_pattern(count, stage=6, attribute="Va"))})


if __name__ == "__main__":
    unittest.main()
