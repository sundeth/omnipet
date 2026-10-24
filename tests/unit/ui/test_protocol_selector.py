"""ProtocolSelector: the device-line grid around CANCEL, and the views using it."""

import os
import sys
import unittest
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

from core import runtime_globals  # noqa: E402
from battle.sim import protocol_constants  # noqa: E402
from ui.components import protocol_selector  # noqa: E402
from ui.components.protocol_selector import (  # noqa: E402
    ProtocolSelector, fill_order, grid_size)

#: The screen globals make_manager changes, restored after the module.
_SCREEN_GLOBALS = ("SCREEN_WIDTH", "SCREEN_HEIGHT", "UI_SCALE")
_saved_globals = {}


def setUpModule():
    _saved_globals.update({name: getattr(runtime_globals, name) for name in _SCREEN_GLOBALS})
    os.chdir(REPO_ROOT)  # icons and fonts load from repo-relative paths
    pygame.init()
    pygame.display.set_mode((240, 240))
    # Fonts cached before another module's pygame.quit() are dangling, and
    # rendering through one is an access violation (see test_rpm).
    from utils import asset_utils
    asset_utils._font_cache.clear()


def tearDownModule():
    for name, value in _saved_globals.items():
        setattr(runtime_globals, name, value)
    from utils import asset_utils
    asset_utils._font_cache.clear()
    pygame.quit()


def make_manager(size=240):
    from ui.ui_manager import UIManager
    runtime_globals.SCREEN_WIDTH = runtime_globals.SCREEN_HEIGHT = size
    runtime_globals.UI_SCALE = size / 240.0
    return UIManager("RED")


def open_selector(manager=None, focus=None, note=None, include_upcoming=False):
    """A selector over the real menu, recording what it calls (include_upcoming:
    the debug-mode grid, which offers TWIN ahead of its battle format)."""
    calls = []
    selector = ProtocolSelector()
    selector.open(protocol_constants.menu_entries(include_upcoming),
                  lambda line: calls.append(("select", line)),
                  on_cancel=lambda: calls.append(("cancel",)),
                  focus=focus, note=note)
    if manager:
        manager.add_component(selector)
        manager.set_active_menu(selector)
    return selector, calls


def cell_centre(selector, line):
    """Screen position of the middle of a line's box."""
    index = [key for key, _, _ in selector.entries].index(line)
    x, y = selector._cell_origin(*selector.cells[index])
    scale = selector._scale()
    half = selector.CELL * scale // 2
    return (selector.rect.x + x * scale + half, selector.rect.y + y * scale + half)


class LayoutTests(unittest.TestCase):
    def test_grid_is_the_smallest_odd_one_widening_first(self):
        self.assertEqual(grid_size(1), (1, 1))
        self.assertEqual(grid_size(3), (3, 1))
        self.assertEqual(grid_size(9), (3, 3))
        self.assertEqual(grid_size(12), (5, 3))
        self.assertEqual(grid_size(15), (5, 3))
        self.assertEqual(grid_size(16), (5, 5))
        self.assertEqual(grid_size(25), (5, 5))

    def test_cancel_takes_the_centre_and_the_rest_read_in_order(self):
        order = fill_order(5, 3)
        self.assertEqual(order[0], (2, 1))
        self.assertEqual(order[1:], [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0),
                                     (0, 1), (1, 1), (3, 1), (4, 1),
                                     (0, 2), (1, 2), (2, 2), (3, 2), (4, 2)])

    def test_the_oldest_line_is_top_left(self):
        selector, _ = open_selector()
        first = protocol_constants.menu_entries()[0][0]
        self.assertEqual(first, "DMOG")
        self.assertEqual(selector.cells[1], (0, 0))
        self.assertEqual(selector.entries[1][0], first)

    def test_cancel_is_the_centre_and_the_default_focus(self):
        selector, _ = open_selector()
        self.assertEqual((selector.columns, selector.rows),
                         grid_size(len(protocol_constants.menu_entries()) + 1))
        self.assertIsNone(selector.entries[0][0])
        self.assertEqual(selector.cells[0], (selector.columns // 2, selector.rows // 2))
        self.assertIsNone(selector.focused_format)

    def test_every_line_is_offered_once_in_release_order(self):
        selector, _ = open_selector()
        entries = protocol_constants.menu_entries()
        self.assertEqual([key for key, _, _ in selector.entries[1:]],
                         [line for line, _, _ in entries])
        self.assertEqual(selector.enabled[1:], [enabled for _, _, enabled in entries])
        self.assertEqual(len(set(selector.cells)), len(selector.entries))

    def test_upcoming_lines_are_disabled_but_twin_in_debug(self):
        """1.0 holds TWIN back (BAT-06); debug mode offers it for its research capture."""
        for debug in (False, True):
            selector, _ = open_selector(include_upcoming=debug)
            enabled = dict(zip([key for key, _, _ in selector.entries], selector.enabled))
            for line in ("PENPROG", "PENX", "ACCEL", "XWM"):
                self.assertFalse(enabled[line], line)
            self.assertEqual(enabled["TWIN"], debug)
            for line in protocol_constants.BATTLE_FORMATS:
                self.assertTrue(enabled[line], line)

    def test_two_tuples_are_enabled(self):
        selector = ProtocolSelector()
        selector.open([("DMOG", "DMOG (Original)")], print)
        self.assertEqual(selector.enabled, [True, True])

    def test_focus_starts_on_the_named_line(self):
        for line, _, _ in protocol_constants.menu_entries():
            selector, _ = open_selector(focus=line)
            self.assertEqual(selector.focused_format, line)

    def test_an_unoffered_focus_falls_back_to_cancel(self):
        for focus in ("None", "VB", "", None):
            selector, _ = open_selector(focus=focus)
            self.assertIsNone(selector.focused_format, focus)

    def test_panel_fits_the_screen_under_the_title(self):
        manager = make_manager()
        selector, _ = open_selector(manager)
        base = selector.base_rect
        self.assertGreaterEqual(base.x, 0)
        self.assertGreaterEqual(base.y, selector.TITLE_CLEARANCE)
        self.assertLessEqual(base.right, 240)
        self.assertLessEqual(base.bottom, 240)

    def test_every_line_has_its_icon(self):
        selector, _ = open_selector()
        for (line, _, _), icon in zip(selector.entries[1:], selector.icons[1:]):
            self.assertIsNotNone(icon, f"{protocol_selector.ICON_DIR}/{line}.png")
            self.assertEqual(icon.get_size(), (32, 32), line)

    def test_a_line_without_an_icon_shows_its_name(self):
        manager = make_manager()
        selector = ProtocolSelector()
        selector.open([("NOICON", "NOICON (Test)")], print, focus="NOICON")
        manager.add_component(selector)
        self.assertIsNone(selector.icons[1])
        self.assertEqual(selector.render().get_size(), selector.rect.size)


class InputTests(unittest.TestCase):
    def setUp(self):
        self.manager = make_manager()
        self.selector, self.calls = open_selector(self.manager)

    def press(self, *keys):
        for key in keys:
            self.assertTrue(self.manager.handle_event((key, None)))

    def test_arrows_step_out_from_cancel(self):
        # DOWN passes the empty cells under CANCEL and wraps to the top.
        for key, line in (("UP", "TWIN"), ("DOWN", "PENPROG"),
                          ("RIGHT", "PENZ"), ("LEFT", "DMX")):
            self.selector.cursor = 0
            self.press(key)
            self.assertEqual(self.selector.focused_format, line, key)

    def test_moves_wrap_round_and_skip_empty_cells(self):
        self.press("LEFT", "LEFT")
        left_edge = self.selector.focused_format
        col, row = self.selector.cells[self.selector.cursor]
        self.assertEqual(col, 0)
        self.press("LEFT")  # off the left edge, back in on the right
        self.assertEqual(self.selector.cells[self.selector.cursor],
                         (self.selector.columns - 1, row))
        self.press("RIGHT")
        self.assertEqual(self.selector.focused_format, left_edge)
        # Down the left column, then past its empty last cell to the top.
        self.press("DOWN")
        self.assertEqual(self.selector.cells[self.selector.cursor], (0, row + 1))
        self.press("DOWN")
        self.assertEqual(self.selector.cells[self.selector.cursor], (0, 0))

    def test_a_on_a_line_selects_it(self):
        self.press("LEFT", "A")
        self.assertEqual(self.calls, [("select", "DMX")])
        self.assertFalse(self.selector.visible)
        self.assertIsNone(self.manager.active_menu)

    def test_twin_is_passed_on_like_any_other_in_debug(self):
        self.manager = make_manager()
        self.selector, self.calls = open_selector(self.manager, include_upcoming=True)
        self.press("UP")
        self.assertEqual(self.selector.focused_format, "TWIN")
        self.press("A")
        self.assertEqual(self.calls, [("select", "TWIN")])

    def test_twin_is_greyed_out_for_players(self):
        self.press("UP", "A")
        self.assertEqual(self.selector.focused_format, "TWIN")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.selector.note, protocol_selector.DISABLED_NOTE)

    def test_a_on_a_disabled_line_only_says_so(self):
        self.press("DOWN", "A")
        self.assertEqual(self.selector.focused_format, "PENPROG")
        self.assertEqual(self.calls, [])
        self.assertTrue(self.selector.visible)
        self.assertIs(self.manager.active_menu, self.selector)
        self.assertEqual(self.selector.note, protocol_selector.DISABLED_NOTE)
        self.press("LEFT")
        self.assertIsNone(self.selector.note)

    def test_clicking_a_disabled_line_only_says_so(self):
        self.manager.handle_event(("LCLICK", {"pos": cell_centre(self.selector, "XWM")}))
        self.assertEqual(self.selector.focused_format, "XWM")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.selector.note, protocol_selector.DISABLED_NOTE)

    def test_a_on_cancel_cancels(self):
        self.press("A")
        self.assertEqual(self.calls, [("cancel",)])
        self.assertIsNone(self.manager.active_menu)

    def test_b_cancels(self):
        self.press("RIGHT", "B")
        self.assertEqual(self.calls, [("cancel",)])

    def test_hover_focuses_and_click_selects(self):
        pos = cell_centre(self.selector, "PEN20")
        self.manager.handle_event(("MOUSE_MOTION", {"pos": pos}))
        self.assertEqual(self.selector.focused_format, "PEN20")
        self.assertEqual(self.calls, [])
        self.manager.handle_event(("LCLICK", {"pos": pos}))
        self.assertEqual(self.calls, [("select", "PEN20")])

    def test_click_in_a_gap_does_nothing_and_outside_cancels(self):
        x, y = cell_centre(self.selector, "DMOG")
        gap = (x + self.selector.CELL // 2 + self.selector.COLUMN_GAP // 2, y)
        self.manager.handle_event(("LCLICK", {"pos": gap}))
        self.assertEqual(self.calls, [])
        self.assertTrue(self.selector.visible)
        outside = (self.selector.rect.x - 1, self.selector.rect.y - 1)
        self.manager.handle_event(("LCLICK", {"pos": outside}))
        self.assertEqual(self.calls, [("cancel",)])


class RenderTests(unittest.TestCase):
    def test_renders_at_each_scale(self):
        for size in (240, 480, 720):
            manager = make_manager(size)
            for focus, note in ((None, None), ("PENZ", None), ("PENOG", None),
                                ("XWM", None), ("TWIN", "TWIN is not ready yet")):
                selector, _ = open_selector(manager, focus=focus, note=note)
                surface = selector.render()
                self.assertEqual(surface.get_size(), selector.rect.size, (size, focus))
                self.assertEqual(selector.rect.width, selector.base_rect.width * manager.ui_scale)
                screen = pygame.Surface((size, size))
                manager.update()
                manager.draw(screen)

    def test_render_is_cached_until_the_cursor_or_note_changes(self):
        manager = make_manager()
        selector, _ = open_selector(manager)
        first = selector.render()
        self.assertIs(selector.render(), first)
        manager.handle_event(("DOWN", None))
        second = selector.render()
        self.assertIsNot(second, first)
        manager.handle_event(("A", None))  # disabled: only the note changes
        self.assertIsNot(selector.render(), second)


class ViewTests(unittest.TestCase):
    def versus_view(self):
        from scenes.battle_views.protocol_view import ProtocolView
        manager = make_manager()
        changes = []
        view = ProtocolView(manager, lambda name, **kw: changes.append((name, kw)),
                            "pet1", "pet2")
        self.addCleanup(view.cleanup)
        return manager, view, changes

    def test_versus_grid_opens_on_cancel_and_b_returns(self):
        manager, view, changes = self.versus_view()
        self.assertIs(manager.active_menu, view.protocol_menu)
        self.assertIsNone(view.protocol_menu.focused_format)
        manager.handle_event(("B", None))
        self.assertEqual([name for name, _ in changes], ["versus"])

    def test_versus_grid_starts_the_chosen_format(self):
        manager, view, changes = self.versus_view()
        manager.handle_event(("LEFT", None))
        manager.handle_event(("A", None))
        self.assertEqual(len(changes), 1)
        name, kwargs = changes[0]
        self.assertEqual(name, "versus_battle")
        self.assertEqual(kwargs["battle_format"], "DMX")
        self.assertEqual(kwargs["protocol"], protocol_constants.versus_protocol("DMX"))

    def test_versus_twin_is_not_fought_as_another_line(self):
        manager, view, changes = self.versus_view()
        for key in ("UP", "A"):
            manager.handle_event((key, None))
        self.assertEqual(changes, [])
        self.assertIs(manager.active_menu, view.protocol_menu)
        self.assertEqual(view.protocol_menu.focused_format, "TWIN")
        # 1.0 greys it out ("Coming soon"); debug mode offers it and says "not ready".
        self.assertIn(view.protocol_menu.note, ("TWIN is not ready yet", protocol_selector.DISABLED_NOTE))

    def dcom_view(self, module_name, modules):
        from scenes.connect_views.dcom_view import DComView

        class Pet:
            module = module_name

        class Stub:
            visible = True

            def set_text(self, text):
                self.text = text

        view = DComView.__new__(DComView)
        view.ui_manager = make_manager()
        view.selected_pets = [Pet()]
        view.status_label = Stub()
        view.cancel_button = Stub()
        view.protocol_menu = None
        view.battle_format = None
        saved_modules = runtime_globals.game_modules
        runtime_globals.game_modules = modules
        self.addCleanup(setattr, runtime_globals, "game_modules", saved_modules)
        return view

    def test_dcom_focuses_the_pets_own_line(self):
        class Module:
            def __init__(self, battle_protocol):
                self.battle_protocol = battle_protocol

        modules = {"DM20": Module("DM20"), "DMH": Module("DMC"),
                   "IC": Module("IC"), "OLD": Module("PENX"),
                   "OLD_IC": Module("DMM"),
                   "ACCEL": Module("DMM"), "TWIN": Module("TWIN"),
                   "PENPROG": Module("None"), "VB": Module("None")}
        expected = {"DM20": "DM20", "DMH": "DMC", "IC": "IC",
                    # Legacy spelling of the Digimon Mini line.
                    "OLD": "DMM",
                    # A declared line the menu offers wins over the name.
                    "ACCEL": "DMM",
                    # A line offered ahead of its battle format.
                    "TWIN": "TWIN",
                    # Declaring none, a module named after a line gets it.
                    "PENPROG": "PENPROG",
                    "VB": None, "MISSING": None}
        # A line's named owner wins over what the module declares: an IC
        # module saved when it declared DMM is still the iC.
        with mock.patch.object(protocol_constants.IC, "NATIVE_MODULES",
                               ("IC", "OLD_IC")):
            view = self.dcom_view("OLD_IC", modules)
            view._show_protocol_selection()
            self.assertEqual(view.protocol_menu.focused_format, "IC")
        for module_name, line in expected.items():
            view = self.dcom_view(module_name, modules)
            view._show_protocol_selection()
            self.assertIs(view.ui_manager.active_menu, view.protocol_menu)
            self.assertEqual(view.protocol_menu.focused_format, line, module_name)
            # Its own CANCEL replaces the view's while the grid is up.
            self.assertFalse(view.cancel_button.visible)

    def test_dcom_cancel_leaves_and_select_goes_on(self):
        view = self.dcom_view("MISSING", {})  # starts on CANCEL
        chosen, cancelled = [], []
        view._on_protocol_select = chosen.append
        view._on_cancel = lambda: cancelled.append(True)
        view._show_protocol_selection()
        view.ui_manager.handle_event(("LEFT", None))
        view.ui_manager.handle_event(("A", None))
        self.assertEqual(chosen, ["DMX"])

        view._show_protocol_selection()
        view.ui_manager.handle_event(("B", None))
        self.assertEqual(cancelled, [True])

    def test_dcom_line_with_no_format_or_capture_is_not_fought(self):
        """TWIN is recorded instead (test_twin_capture); a line with neither
        a battle format nor a capture code is refused, never fought as DM20."""
        view = self.dcom_view("DM20", {})
        view._on_protocol_select("ACCEL")
        self.assertIsNone(view.battle_format)
        self.assertIs(view.ui_manager.active_menu, view.protocol_menu)
        self.assertEqual(view.protocol_menu.focused_format, "ACCEL")
        self.assertEqual(view.protocol_menu.note, "ACCEL is not ready yet")


if __name__ == "__main__":
    unittest.main()
