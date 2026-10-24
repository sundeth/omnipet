"""The adventure battle view's menus: the between-round Food menu and the
battle item list (owner, 2026-10-17).

A ``Menu`` closes itself after its ``on_select`` returns. The Food menu
reopened the same Menu object from inside ``on_select``, so it vanished after
one feed and the player had to press B to go on (BAT-F10). The battle item
list opens a fresh Menu each time for the same reason.
"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SRC = os.path.join(REPO_ROOT, "src")
for path in (SRC, REPO_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from core import runtime_globals  # noqa: E402
from scenes.battle_views import adventure_battle_view as abv  # noqa: E402


class FakeUI:
    """Just what the view asks of a UI manager."""

    def __init__(self):
        self.active_menu = None
        self.show_external_border = True
        self.components = []

    def add_component(self, component):
        self.components.append(component)

    def remove_component(self, component):
        if component in self.components:
            self.components.remove(component)

    def set_active_menu(self, menu):
        self.active_menu = menu
        if menu is not None:
            menu.manager = self


def _view(encounter=None):
    view = abv.AdventureBattleView.__new__(abv.AdventureBattleView)
    view.ui_manager = FakeUI()
    view.change_view = Mock()
    view.module = SimpleNamespace(name="IC", items=[], battle_item_use="round")
    view.area, view.round_num = 1, 1
    view.is_special_encounter = False
    view.encounter_name = None
    view.battle_encounter = encounter
    view._menu = None
    view._tracked_phase = None
    view._pre_battle_menu = None
    return view


def _quiet():
    return (patch.object(runtime_globals, "game_sound", SimpleNamespace(play=Mock())),
            patch.object(runtime_globals, "game_console", SimpleNamespace(log=Mock())),
            patch.object(runtime_globals, "game_message", SimpleNamespace(add_slide=Mock())))


class FeedingMenuTests(unittest.TestCase):
    def test_the_food_menu_stays_open_after_a_feed(self):
        encounter = SimpleNamespace(ui_manager=FakeUI(), feed_protein_to_team=Mock(),
                                    end_feeding_and_proceed=Mock())
        view = _view(encounter)
        a, b, c = _quiet()
        with a, b, c:
            view._enter_feeding()
            menu = view._menu
            menu.set_selected_index(1)              # Food
            menu.handle_event(("A", None))
        encounter.feed_protein_to_team.assert_called_once()
        self.assertIsNotNone(view._menu)
        self.assertTrue(view._menu.visible, "the menu is still there for another feed or Next")
        self.assertIs(encounter.ui_manager.active_menu, view._menu)
        encounter.end_feeding_and_proceed.assert_not_called()


class BattleItemListTests(unittest.TestCase):
    def setUp(self):
        self.cannon = SimpleNamespace(id="cannon", name="Digi Cannon", module="IC",
                                      effect="status_boost", status="attack", amount=1,
                                      boost_time=1, reusable=False)
        self.stock = {"cannon": 2}

    def rows(self, module, pets=None):
        return [(self.cannon, self.stock["cannon"])] if self.stock["cannon"] else []

    def use(self, item, pets):
        self.stock[item.id] -= 1
        return []

    def test_an_item_then_fight(self):
        view = _view()
        view._start_battle = Mock()
        a, b, c = _quiet()
        with a, b, c, patch.object(abv.battle_items, "battle_items", side_effect=self.rows), \
                patch.object(abv.battle_items, "use_battle_item", side_effect=self.use) as used, \
                patch.object(abv, "get_battle_targets", return_value=[]):
            view._open_pre_battle_items()
            first = view._pre_battle_menu
            self.assertEqual(first.options, ["Fight", "Digi Cannon x2"])
            first.set_selected_index(1)
            first.handle_event(("A", None))
            used.assert_called_once()
            second = view._pre_battle_menu
            self.assertIsNot(second, first, "a fresh menu, as the old one closes itself")
            self.assertTrue(second.visible)
            self.assertEqual(second.options, ["Fight", "Digi Cannon x1"])
            view._start_battle.assert_not_called()
            second.handle_event(("A", None))         # Fight
        view._start_battle.assert_called_once()
        self.assertIsNone(view._pre_battle_menu)

    def test_b_fights_without_an_item(self):
        view = _view()
        view._start_battle = Mock()
        a, b, c = _quiet()
        with a, b, c, patch.object(abv.battle_items, "battle_items", side_effect=self.rows), \
                patch.object(abv, "get_battle_targets", return_value=[]):
            view._open_pre_battle_items()
            view._pre_battle_menu.handle_event(("B", None))
        view._start_battle.assert_called_once()
        self.assertEqual(self.stock["cannon"], 2)

    def test_the_list_before_a_later_round(self):
        encounter = SimpleNamespace(ui_manager=FakeUI(), end_battle_items_and_proceed=Mock())
        view = _view(encounter)
        a, b, c = _quiet()
        with a, b, c, patch.object(abv.battle_items, "battle_items", side_effect=self.rows), \
                patch.object(abv.battle_items, "use_battle_item", side_effect=self.use), \
                patch.object(abv, "get_battle_continue_targets", return_value=[]):
            view._enter_battle_items()
            view._menu.set_selected_index(1)
            view._menu.handle_event(("A", None))
            self.assertTrue(view._menu.visible)
            self.assertEqual(view._menu.options, ["Fight", "Digi Cannon x1"])
            view._menu.set_selected_index(1)
            view._menu.handle_event(("A", None))    # the last one: straight to the round
        encounter.end_battle_items_and_proceed.assert_called_once()


class DComWeaponTests(unittest.TestCase):
    """The iC's weapons go on the DCom wire (packet 3): chosen before the
    charge, used up by the battle."""

    def view(self, battle_format="IC"):
        from scenes.connect_views.dcom_view import DComView
        view = DComView.__new__(DComView)
        view.ui_manager = FakeUI()
        view.selected_pets = [SimpleNamespace(module="IC", digisoul="Dragon", stage=3)]
        view.battle_format = battle_format
        view.simulator = SimpleNamespace()
        view.items_menu = None
        view.phase = "protocol_select"
        view.status_label = SimpleNamespace(set_text=Mock())
        view._start_minigame = Mock()
        return view

    def test_a_weapon_then_the_charge(self):
        cannon = SimpleNamespace(id="cannon", name="Digi Cannon", module="IC", protocol_value=9)
        stock = {"n": 1}

        def rows(module, pet):
            return [(cannon, stock["n"])] if stock["n"] else []

        def use(item, pets):
            stock["n"] -= 1
            return []
        view = self.view()
        a, b, c = _quiet()
        with a, b, c, patch.dict(runtime_globals.game_modules, {"IC": SimpleNamespace(name="IC")}), \
                patch("utils.battle_items.wire_items", side_effect=rows), \
                patch("utils.battle_items.use_battle_item", side_effect=use) as used, \
                patch("scenes.connect_views.dcom_view.DComView._capturing", False):
            view._offer_battle_items()
            self.assertEqual(view.phase, "battle_items")
            view._start_minigame.assert_not_called()
            view.items_menu.set_selected_index(1)
            view.items_menu.handle_event(("A", None))
        used.assert_called_once()
        view._start_minigame.assert_called_once()   # nothing left: straight to the charge

    def test_another_line_goes_straight_to_the_charge(self):
        view = self.view("DMX")
        with patch("scenes.connect_views.dcom_view.DComView._capturing", False):
            view._offer_battle_items()
        view._start_minigame.assert_called_once()

    def test_the_battle_uses_the_weapon_up(self):
        from core import game_globals
        from utils import battle_items
        effects = {"attack": {"amount": 1, "boost_time": 1, "module": "IC", "item_id": "cannon"},
                   "hp": {"amount": 2, "boost_time": 2, "module": "DMX", "item_id": "rom"}}
        a, b, c = _quiet()
        with a, b, c, patch.object(game_globals, "battle_effects", effects):
            battle_items.count_down("IC")
        self.assertEqual(list(effects), ["hp"], "another module's effect is left alone")


if __name__ == "__main__":
    unittest.main()
