"""Quest targets cover their whole range, and a new day starts on any screen
(2026-10-22 documentation pass, findings 6 and 8).

6  ``target_amount_range`` [min, max] used ``random.choice`` of the list, so
   [3, 5] gave 3 or 5 and never 4; the Module Editor says "drawn between Min
   and Max". Every number in the range now comes up.
8  The day's quests (and the XAI number) were renewed only when the main
   scene was built after midnight: a game left on the main screen or in the
   Library kept yesterday's quests. Both screens now check once a second.
"""
import datetime
import os
import random
import sys
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
if os.path.join(ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "src"))

from core import game_globals, runtime_globals  # noqa: E402
from models.quest_event_data import QuestData  # noqa: E402
from utils import quest_event_utils as qeu  # noqa: E402


class QuestTargets(unittest.TestCase):
    def test_every_number_of_the_range_comes_up(self):
        random.seed(3)
        seen = {qeu.target_from_range([3, 5]) for _ in range(300)}
        self.assertEqual(seen, {3, 4, 5})

    def test_a_one_number_range_and_a_reversed_one(self):
        self.assertEqual(qeu.target_from_range([2, 2]), 2)
        self.assertEqual(qeu.target_from_range([7]), 7)
        random.seed(1)
        self.assertEqual({qeu.target_from_range([6, 4]) for _ in range(200)}, {4, 5, 6})

    def test_a_quest_built_from_a_range_names_its_target(self):
        data = QuestData(id="q", name="", type=1, target_amount_range=[4, 6],
                         reward_type=1, reward_value="Meat", reward_quantity=1)
        random.seed(0)
        with patch.object(runtime_globals, "game_console", Mock(), create=True):
            targets = {qeu.create_quest_instance_from_data(data, "VB").target_amount for _ in range(200)}
        self.assertEqual(targets, {4, 5, 6})


class NewDay(unittest.TestCase):
    def setUp(self):
        for p in (patch.object(runtime_globals, "game_console", Mock(), create=True),
                  patch.object(game_globals, "quests", ["yesterday's"]),
                  patch.object(game_globals, "xai", 3),
                  patch.object(game_globals, "xai_date", datetime.date(2026, 10, 21))):
            p.start()
            self.addCleanup(p.stop)

    def test_the_same_day_keeps_the_quests(self):
        self.assertFalse(qeu.roll_over_day(datetime.date(2026, 10, 21)))
        self.assertEqual(game_globals.quests, ["yesterday's"])

    def test_a_new_day_drops_the_quests_and_draws_the_xai_again(self):
        self.assertTrue(qeu.roll_over_day(datetime.date(2026, 10, 22)))
        self.assertEqual(game_globals.quests, [])
        self.assertEqual(game_globals.xai_date, datetime.date(2026, 10, 22))
        self.assertIn(game_globals.xai, range(1, 8))
        self.assertFalse(qeu.roll_over_day(datetime.date(2026, 10, 22)), "once a day")

    def test_new_quests_are_dealt_when_there_are_none(self):
        game_globals.quests = []
        with patch.object(qeu, "generate_daily_quests", return_value=["today's"]):
            qeu.ensure_daily_quests()
        self.assertEqual(game_globals.quests, ["today's"])
        with patch.object(qeu, "generate_daily_quests", return_value=["other"]):
            qeu.ensure_daily_quests()
        self.assertEqual(game_globals.quests, ["today's"], "kept while there are some")


if __name__ == "__main__":
    unittest.main()
