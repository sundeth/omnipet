"""The daily gift quest (QuestType.DAILY_GIFT, 7; owner, 2026-10-20).

A quest that asks nothing: each party module with one offers one of its
gifts every day, ready to claim, in one of the three daily slots; the other
slots are drawn as before. DW1's is World's Meat Farm, three Giant Meat a day.
"""
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SRC = os.path.join(REPO_ROOT, "src")
for path in (SRC, REPO_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)
MODULES = os.path.join(REPO_ROOT, "modules")

from core import game_globals, runtime_globals  # noqa: E402
from models.game_quest import QuestStatus, QuestType  # noqa: E402
from models.quest_event_data import QuestData  # noqa: E402
from utils import quest_event_utils  # noqa: E402


def quest(qid, qtype, name="", reward="Meat"):
    return QuestData(id=qid, name=name, type=qtype, target_amount_range=[2, 2],
                     reward_type=0, reward_value=reward, reward_quantity=3)


class DailyGift(unittest.TestCase):
    def setUp(self):
        self.modules = {
            "GIFT": SimpleNamespace(load_quests_json=lambda: [
                quest("g1", 7, "Meat Farm", "Giant Meat"), quest("b1", 2)]),
            "OTHER": SimpleNamespace(load_quests_json=lambda: [quest("t1", 1), quest("e1", 4)]),
        }
        for p in (patch.object(runtime_globals, "game_modules", self.modules),
                  patch.object(runtime_globals, "game_console", Mock(), create=True),
                  patch.object(game_globals, "pet_list",
                               [SimpleNamespace(module="GIFT"), SimpleNamespace(module="OTHER")])):
            p.start()
            self.addCleanup(p.stop)

    def test_the_gift_is_offered_every_day_ready_to_claim(self):
        for _ in range(20):
            quests = quest_event_utils.generate_daily_quests()
            self.assertEqual(len(quests), 3)
            gifts = [q for q in quests if q.type == QuestType.DAILY_GIFT]
            self.assertEqual(len(gifts), 1)
            gift = gifts[0]
            self.assertEqual((gift.name, gift.module, gift.status), ("Meat Farm", "GIFT", QuestStatus.SUCCESS))
            self.assertEqual((gift.current_amount, gift.target_amount), (1, 1))
            self.assertEqual((gift.reward_value, gift.reward_quantity), ("Giant Meat", 3))
            for other in quests:
                if other is not gift:
                    self.assertEqual(other.status, QuestStatus.PENDING)

    def test_no_gift_without_a_party_pet_of_its_module(self):
        game_globals.pet_list = [SimpleNamespace(module="OTHER")]
        for _ in range(10):
            self.assertFalse(any(q.type == QuestType.DAILY_GIFT
                                 for q in quest_event_utils.generate_daily_quests()))

    def test_a_module_with_only_a_gift_gets_the_gift_alone(self):
        self.modules["GIFT"] = SimpleNamespace(load_quests_json=lambda: [quest("g1", 7, "Meat Farm")])
        game_globals.pet_list = [SimpleNamespace(module="GIFT")]
        quests = quest_event_utils.generate_daily_quests()
        self.assertEqual([q.id for q in quests], ["g1"])

    def test_claiming_pays_the_reward(self):
        game_globals.quests = [q for q in quest_event_utils.generate_daily_quests()
                               if q.type == QuestType.DAILY_GIFT]
        with patch.object(quest_event_utils, "get_item_by_name",
                          lambda module, name: SimpleNamespace(id=f"{module}:{name}")), \
                patch.object(quest_event_utils, "add_to_inventory") as add:
            reward = quest_event_utils.complete_quest("g1")
        add.assert_called_once_with("GIFT:Giant Meat", 3)
        self.assertEqual(reward["reward_quantity"], 3)
        self.assertEqual(game_globals.quests[0].status, QuestStatus.FINISHED)


@unittest.skipUnless(os.path.isfile(os.path.join(MODULES, "DW1", "quests.json")), "DW1 not installed")
class DW1MeatFarm(unittest.TestCase):
    def test_the_meat_farm_gives_three_giant_meat(self):
        with open(os.path.join(MODULES, "DW1", "quests.json"), encoding="utf-8-sig") as fh:
            quests = json.load(fh)["quests"]
        with open(os.path.join(MODULES, "DW1", "item.json"), encoding="utf-8-sig") as fh:
            items = {i["name"] for i in json.load(fh)["item"]}
        gifts = [q for q in quests if q["type"] == QuestType.DAILY_GIFT.value]
        self.assertEqual([(q["name"], q["reward_value"], q["reward_quantity"]) for q in gifts],
                         [("Meat Farm", "Giant Meat", 3)])
        self.assertIn("Giant Meat", items)


if __name__ == "__main__":
    unittest.main()
