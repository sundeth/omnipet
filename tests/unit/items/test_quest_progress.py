"""Feeding and Armor Evolution quests move (2026-10-22 documentation pass).

Nothing reported either quest type, so they never advanced: 8 of D-3's 11
quests were Feeding or Armor Evolution. A meal a pet takes now counts for its
module's Feeding quests; an armor evolution from the Armor menu counts for
Armor Evolution quests.
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
for path in (os.path.join(ROOT, "src"), os.path.join(ROOT, "tests", "unit", "android")):
    if path not in sys.path:
        sys.path.insert(0, path)

from core import game_globals, runtime_globals  # noqa: E402
from models.game_quest import GameQuest, QuestStatus, QuestType, RewardType  # noqa: E402
from test_android_offline import module, pet  # noqa: E402


def quest(kind, module_name="Test", target=2):
    return GameQuest("q-%s" % kind.name, kind.name, module_name, kind, target, RewardType.ITEM, "Meat", 1)


class QuestProgress(unittest.TestCase):
    def setUp(self):
        for p in (patch.object(runtime_globals, "game_console", Mock(), create=True),
                  patch.object(game_globals, "quests", [])):
            p.start()
            self.addCleanup(p.stop)
        self.mod = module(meat_weight_gain=1, protein_weight_gain=1, can_eat_sleeping=True,
                          meat_hunger_gain=1, overfeed_timer=0)

    def feed(self, p):
        with patch("models.game_pet.get_module", return_value=self.mod):
            return p.set_eating("hunger", 1)

    def test_a_meal_counts_for_its_modules_feeding_quest(self):
        mine, other = quest(QuestType.FEEDING), quest(QuestType.FEEDING, "Elsewhere")
        game_globals.quests[:] = [mine, other]
        p = pet(self.mod, module="Test", hunger=0, stomach=4)
        with patch.object(type(p), "_is_blocked_by_sleep", lambda self: False):
            self.assertTrue(self.feed(p))
            self.assertTrue(self.feed(p))
        self.assertEqual((mine.current_amount, mine.status), (2, QuestStatus.SUCCESS))
        self.assertEqual(other.current_amount, 0, "another module's quest")

    def test_a_refused_meal_does_not_count(self):
        mine = quest(QuestType.FEEDING)
        game_globals.quests[:] = [mine]
        p = pet(self.mod, module="Test", hunger=4, stomach=4)
        with patch.object(type(p), "_is_blocked_by_sleep", lambda self: False):
            self.assertFalse(self.feed(p))
        self.assertEqual(mine.current_amount, 0)

    def test_an_armor_evolution_counts(self):
        from scenes.battle_views import armor_view
        armor = quest(QuestType.ARMOR_EVOLUTION, target=1)
        game_globals.quests[:] = [armor]
        view = armor_view.ArmorView.__new__(armor_view.ArmorView)
        target = SimpleNamespace(name="Agumon", module="Test")
        view.pet_selector = SimpleNamespace(pets=[target])
        view.selected_armor_pet = 0
        view.selected_armor_item = SimpleNamespace(name="Digimental of Courage", id="i1")
        with patch("utils.evolution_items.use", return_value=(True, True)), \
                patch("utils.inventory_utils.remove_from_inventory"), \
                patch.object(armor_view, "change_scene"), \
                patch.object(runtime_globals, "game_sound", Mock(), create=True):
            view._on_confirm()
        self.assertEqual(armor.status, QuestStatus.SUCCESS)


if __name__ == "__main__":
    unittest.main()
