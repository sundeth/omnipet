"""The training menu: its order, its pages and where it reopens."""

import os
import sys
import unittest
from types import SimpleNamespace
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
from scenes import scene_training  # noqa: E402
from scenes.scene_training import (  # noqa: E402
    BONUS_MODES, MODES_PER_PAGE, TRAINING_GAMEPLAY_IDS, TRAINING_MODES, SceneTraining,
    order_training_modes)
from scenes.tutorial_scenes.tutorial_training import TutorialTraining  # noqa: E402

ALL = list(TRAINING_MODES)


def pet(module):
    return SimpleNamespace(module=module)


class OrderTests(unittest.TestCase):
    modules = {
        "PENZ": SimpleNamespace(battle_minigame="Count Match Z"),
        "DMX": SimpleNamespace(battle_minigame="Xai Roll+Bar"),
        "DMC": SimpleNamespace(battle_minigame="None"),
    }

    def test_alphabetical_without_module_minigames(self):
        self.assertEqual(
            order_training_modes(ALL, [], self.modules),
            ["count_bar", "count_classic", "count", "count_z", "dummy",
             "excite", "head", "mogera", "punch", "rpm"])

    def test_pet_modules_come_first_in_pet_order(self):
        order = order_training_modes(
            ALL, [pet("DMX"), pet("PENZ"), pet("DMX"), pet("DMC")], self.modules)
        self.assertEqual(order[:2], ["excite", "count_z"])
        self.assertEqual(sorted(order), sorted(ALL))

    def test_a_module_minigame_the_player_does_not_own_is_skipped(self):
        order = order_training_modes(["dummy", "punch"], [pet("PENZ")], self.modules)
        self.assertEqual(order, ["dummy", "punch"])

    def test_tutorial_puts_dummy_first_and_ignores_modules(self):
        order = order_training_modes(ALL, [pet("PENZ")], self.modules, dummy_first=True)
        self.assertEqual(order[0], "dummy")
        self.assertEqual(order[1:4], ["count_bar", "count_classic", "count"])


class MenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((240, 240))

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def setUp(self):
        patches = [
            mock.patch.object(game_globals, "game_mode", game_globals.GAME_MODE_FREE),
            mock.patch.object(game_globals, "pet_list", []),
            mock.patch.object(runtime_globals, "selected_pets", []),
            mock.patch.object(runtime_globals, "training_focus", None),
            mock.patch.object(runtime_globals, "INPUT_MODE", runtime_globals.KEYBOARD_MODE),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def visible_modes(self, scene):
        return [key for key in scene.mode_keys if scene.mode_buttons[key].visible]

    def focused_key(self, scene):
        return scene._focused_mode_key()

    def test_more_than_six_minigames_make_two_pages(self):
        scene = SceneTraining()
        self.assertEqual(len(scene.mode_keys), len(TRAINING_MODES))
        self.assertEqual(self.visible_modes(scene), scene.mode_keys[:MODES_PER_PAGE])
        self.assertTrue(scene.more_button.enabled)
        scene.on_more()
        self.assertEqual(self.visible_modes(scene), scene.mode_keys[MODES_PER_PAGE:])
        scene.on_more()
        self.assertEqual(scene.page, 0)

    def test_six_or_fewer_disables_more(self):
        owned = {"dummy", "head", "count", "punch", "mogera", "excite"}
        with mock.patch.object(game_globals, "game_mode", game_globals.GAME_MODE_PROGRESS), \
                mock.patch.object(SceneTraining, "owns_training_mode",
                                  lambda self, key: key in owned):
            scene = SceneTraining()
        self.assertEqual(len(scene.mode_keys), 6)
        self.assertFalse(scene.more_button.enabled)
        self.assertTrue(scene.random_button.enabled)
        scene.handle_event(("SCROLL", {"direction": "DOWN", "amount": 1}))
        self.assertEqual(scene.page, 0)

    def test_minigames_fill_the_top_two_rows_and_controls_the_third(self):
        scene = SceneTraining()
        rows = {scene.mode_buttons[key].base_rect.y for key in scene.mode_keys}
        self.assertEqual(rows, {25, 81})
        self.assertEqual(
            [b.base_rect.topleft for b in (scene.more_button, scene.random_button,
                                           scene.exit_button)],
            [(36, 137), (92, 137), (148, 137)])

    def last_key_in_row(self, scene, page, row):
        """The last button of *row* on *page*, or the page's last if that row
        is empty.

        Computed rather than written down, because the page layout moves
        whenever a training mode is added: the Digivice iC's `rpm` made a
        tenth, which gave page 2 a second row and turned "the last button on
        the page" into "the last button of row 0".
        """
        from scenes.scene_training import COLUMNS, MODES_PER_PAGE
        page_keys = scene.mode_keys[page * MODES_PER_PAGE:
                                    (page + 1) * MODES_PER_PAGE]
        row_keys = page_keys[row * COLUMNS:(row + 1) * COLUMNS]
        return (row_keys or page_keys)[-1]

    def test_pressing_past_the_edge_turns_the_page(self):
        scene = SceneTraining()
        first, sixth = scene.mode_keys[0], scene.mode_keys[5]
        scene.ui_manager.set_focused_component(scene.mode_buttons[first])
        scene.handle_event(("LEFT", None))
        self.assertEqual(scene.page, 1)
        # Row 0 is where the focus was, so its last button takes it.
        self.assertEqual(self.focused_key(scene),
                         self.last_key_in_row(scene, 1, 0))
        scene.handle_event(("RIGHT", None))
        self.assertEqual(scene.page, 0)
        self.assertEqual(self.focused_key(scene), first)

        scene.ui_manager.set_focused_component(scene.mode_buttons[sixth])
        scene.handle_event(("RIGHT", None))
        self.assertEqual(scene.page, 1)
        # The focus was in row 1; if page 2 has no row 1 the nearest button
        # there is the page's last.
        self.assertEqual(self.focused_key(scene),
                         self.last_key_in_row(scene, 1, 1))

    def test_moving_inside_the_grid_does_not_turn_the_page(self):
        scene = SceneTraining()
        scene.ui_manager.set_focused_component(scene.mode_buttons[scene.mode_keys[0]])
        scene.handle_event(("RIGHT", None))
        self.assertEqual(scene.page, 0)
        self.assertEqual(self.focused_key(scene), scene.mode_keys[1])

    def test_wheel_turns_pages_both_ways(self):
        scene = SceneTraining()
        scene.handle_event(("SCROLL", {"direction": "DOWN", "amount": 1}))
        self.assertEqual(scene.page, 1)
        scene.handle_event(("SCROLL", {"direction": "UP", "amount": 1}))
        self.assertEqual(scene.page, 0)

    def test_arrows_are_for_pointers_only(self):
        scene = SceneTraining()
        self.assertFalse(scene.prev_page_button.visible)
        with mock.patch.object(runtime_globals, "INPUT_MODE", runtime_globals.TOUCH_MODE):
            scene.update()
            self.assertTrue(scene.prev_page_button.visible)
            self.assertTrue(scene.next_page_button.visible)
            self.assertEqual(scene.next_page_button.base_rect.y, 81)
            scene.next_page_button.activate()
            self.assertEqual(scene.page, 1)

    def test_reopens_on_the_minigame_last_chosen(self):
        scene = SceneTraining()
        last = scene.mode_keys[-1]
        scene.select_training(last)  # no pets, so it does not start
        self.assertIsNone(scene.mode)
        self.assertEqual(runtime_globals.training_focus, last)

        reopened = SceneTraining()
        self.assertEqual(reopened.page, 1)
        self.assertTrue(reopened.mode_buttons[last].visible)
        self.assertEqual(self.focused_key(reopened), last)

    def test_returning_from_a_minigame_keeps_its_page(self):
        scene = SceneTraining()
        key = scene.mode_keys[-1]
        scene.select_training(key)
        scene.hide_menu_buttons()
        scene.show_menu_buttons()
        self.assertEqual(self.visible_modes(scene), scene.mode_keys[MODES_PER_PAGE:])
        self.assertFalse(scene.prev_page_button.visible)

    def test_random_needs_a_playable_minigame(self):
        scene = SceneTraining()
        with mock.patch.object(scene_training, "get_training_targets", return_value=[]), \
                mock.patch.object(scene, "select_training") as select:
            scene.on_random()
        select.assert_not_called()

        one_pet = [SimpleNamespace(check_disturbed_sleep=lambda: None)]
        with mock.patch.object(scene_training, "get_training_targets", return_value=one_pet), \
                mock.patch.object(scene, "select_training") as select:
            for _ in range(40):
                scene.on_random()
        picked = {call.args[0] for call in select.call_args_list}
        self.assertNotIn("head", picked)  # needs two pets
        self.assertTrue(picked)

    def test_tutorial_layout(self):
        runtime_globals.training_focus = "mogera"
        scene = TutorialTraining()
        self.assertEqual(scene.mode_keys[0], "dummy")
        self.assertEqual(scene.dummy_button.base_rect.topleft, (36, 25))
        self.assertTrue(scene.dummy_button.visible)
        self.assertEqual(scene.page, 0)
        self.assertFalse(scene.more_button.enabled)
        self.assertFalse(scene.random_button.enabled)
        scene.ui_manager.set_focused_component(scene.dummy_button)
        SceneTraining.handle_event(scene, ("LEFT", None))
        self.assertEqual(scene.page, 0)
        with mock.patch.object(runtime_globals, "INPUT_MODE", runtime_globals.MOUSE_MODE):
            scene.update()
            self.assertFalse(scene.prev_page_button.visible)


def ic_pet(stage=2, state="normal", hunger=4):
    """A pet of the IC module, which the IC wire names as its own."""
    return SimpleNamespace(module="IC", stage=stage, state=state, hunger=hunger,
                           check_disturbed_sleep=lambda: None)


class BonusTests(unittest.TestCase):
    """The iC's minigames, under BONUS (owner, 2026-10-06)."""

    @classmethod
    def setUpClass(cls):
        os.chdir(REPO_ROOT)         # button art loads from repo-relative paths
        pygame.init()
        pygame.display.set_mode((240, 240))

    def setUp(self):
        self.party = []
        patches = [
            mock.patch.object(game_globals, "game_mode", game_globals.GAME_MODE_FREE),
            mock.patch.object(game_globals, "pet_list", self.party),
            mock.patch.object(runtime_globals, "selected_pets", []),
            mock.patch.object(runtime_globals, "training_focus", None),
            mock.patch.object(runtime_globals, "training_bonus_focus", None),
            mock.patch.object(runtime_globals, "scene_training_initial_view", None),
            mock.patch.object(runtime_globals, "training_bonus_return", None),
            mock.patch.object(runtime_globals, "scene_battle_initial_view", None),
            mock.patch.object(runtime_globals, "game_state", "training"),
            mock.patch.object(runtime_globals, "INPUT_MODE", runtime_globals.KEYBOARD_MODE),
            # The pets that would play decide BONUS: here every living,
            # hatched pet of the party can train.
            mock.patch.object(scene_training, "get_training_targets", side_effect=self.trainers),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def trainers(self):
        return [pet for pet in self.party if pet.state != "dead" and pet.stage > 0]

    def test_rpm_uses_its_own_icon(self):
        self.assertEqual(TRAINING_MODES["rpm"]["decorators"], ["RPM"])
        self.assertTrue(os.path.exists(os.path.join(REPO_ROOT, "assets", "ui", "Training_RPM_1.png")))

    def test_bonus_needs_an_ic_digimon_in_the_party(self):
        self.party.append(SimpleNamespace(module="DMC", stage=2, state="normal"))
        self.assertFalse(SceneTraining().bonus_button.visible)
        self.party.append(ic_pet(stage=0))           # an egg does not count
        self.assertFalse(SceneTraining().bonus_button.visible)
        self.party.append(ic_pet())
        scene = SceneTraining()
        self.assertTrue(scene.bonus_button.visible)
        self.assertTrue(scene.bonus_button.focusable)

    def test_bonus_needs_an_ic_digimon_among_the_pets_that_would_play(self):
        """An iC Digimon in the party, a non-iC one selected: no BONUS, as
        none of its minigames would let the selection in."""
        self.party.append(ic_pet())
        dmc = SimpleNamespace(module="DMC", stage=2, state="normal")
        self.party.append(dmc)
        with mock.patch.object(scene_training, "get_training_targets", return_value=[dmc]):
            scene = SceneTraining()
            self.assertFalse(scene.bonus_button.visible)
            self.assertFalse(scene.bonus_button.focusable)
        scene.update()
        self.assertTrue(scene.bonus_button.visible, "the iC Digimon can play again")

    def test_bonus_sits_level_with_the_title(self):
        self.party.append(ic_pet())
        scene = SceneTraining()
        bonus, title = scene.bonus_button.base_rect, scene.title_scene.base_rect
        self.assertEqual((bonus.y, bonus.height), (title.y, 16))
        self.assertGreater(bonus.x, title.right)
        self.assertLessEqual(bonus.right, 240)

    def test_bonus_lists_the_six_ic_minigames(self):
        self.party.append(ic_pet())
        scene = SceneTraining()
        scene.bonus_button.activate()
        self.assertEqual(scene.view, "bonus")
        self.assertEqual(scene.mode_keys, list(BONUS_MODES))
        self.assertEqual(len(scene.mode_keys), 6)
        self.assertEqual(scene.title_scene.title_text, "BONUS")
        self.assertEqual(scene.exit_button.text, "BACK")
        self.assertEqual(scene.random_button.text, "RANDOM")
        self.assertFalse(scene.bonus_button.visible)
        self.assertFalse(scene.more_button.enabled, "six fit one page")
        # All six have their art (assets/ui/Training_<Name>_1.png), so no name.
        for key, art in (("building_smash", "BuildingSmash"), ("poop_dodge", "PoopDodge"),
                         ("shuffle", "Shuffle"), ("digi_whack", "DigiWhack"),
                         ("digi_mash", "DigiMash"), ("gotcha", "Gotcha")):
            self.assertEqual(scene.mode_buttons[key].decorators, [art])
            self.assertEqual(scene.mode_buttons[key].text, "", key)

    def test_bonus_minigames_are_neither_sold_nor_trained(self):
        for key in BONUS_MODES:
            self.assertNotIn(key, TRAINING_GAMEPLAY_IDS)
            self.assertNotIn(key, TRAINING_MODES)

    def test_back_returns_to_the_main_list(self):
        self.party.append(ic_pet())
        scene = SceneTraining()
        scene.show_view("bonus")
        scene.exit_button.activate()
        self.assertEqual(scene.view, "main")
        self.assertEqual(scene.title_scene.title_text, "TRAINING")
        self.assertEqual(scene.exit_button.text, "EXIT")
        self.assertTrue(scene.bonus_button.visible)
        self.assertEqual(runtime_globals.game_state, "training")

    def test_from_the_specials_hub_back_returns_there(self):
        self.party.append(ic_pet())
        runtime_globals.scene_training_initial_view = "bonus"
        runtime_globals.training_bonus_return = ("specials", {"module_name": "IC"})
        scene = SceneTraining()
        self.assertEqual(scene.view, "bonus")
        self.assertIsNone(runtime_globals.scene_training_initial_view)
        scene.handle_event(("B", None))
        self.assertEqual(runtime_globals.game_state, "battle")
        self.assertEqual(runtime_globals.scene_battle_initial_view,
                         ("specials", {"module_name": "IC"}))

    def test_only_ic_digimon_play(self):
        other = SimpleNamespace(module="DMC", stage=2, state="normal")
        mine = ic_pet()
        with mock.patch.object(scene_training, "get_training_targets", return_value=[other, mine]):
            self.assertEqual(scene_training.bonus_targets(), [mine])

    def test_an_unwritten_minigame_does_not_start(self):
        self.party.append(ic_pet())
        scene = SceneTraining()
        scene.show_view("bonus")
        with mock.patch.object(scene_training, "get_training_targets", return_value=[ic_pet()]):
            scene.select_training("gotcha")
            self.assertIsNone(scene.mode)
            self.assertEqual(scene.phase, "menu")
            self.assertEqual(runtime_globals.training_bonus_focus, "gotcha")
            self.assertIsNone(runtime_globals.training_focus, "each list keeps its own")
            with mock.patch.object(scene, "select_training") as select:
                for _ in range(20):
                    scene.on_random()
            written = {key for key, spec in BONUS_MODES.items() if spec["cls"] is not None}
            self.assertLessEqual({call.args[0] for call in select.call_args_list}, written,
                                 "RANDOM picks only what is written")
            self.assertIn("shuffle", written)

    def test_building_smash_starts(self):
        self.party.append(ic_pet())
        scene = SceneTraining()
        scene.show_view("bonus")
        targets = [ic_pet(hunger=4)]
        ic_module = SimpleNamespace(currencies=[], folder_path=os.path.join(REPO_ROOT, "modules", "IC"))
        with mock.patch.object(runtime_globals, "game_modules", {"IC": ic_module}), \
                mock.patch.object(scene_training, "get_training_targets", return_value=targets), \
                mock.patch("training.training.get_training_targets", return_value=targets), \
                mock.patch("training.ic_minigame.get_training_targets", return_value=targets):
            scene.select_training("building_smash")
        self.assertIsInstance(scene.mode, BONUS_MODES["building_smash"]["cls"])
        self.assertEqual(scene.mode.phase, "alert", "READY first, as every minigame")
        self.assertEqual(targets[0].hunger, 3)

    def test_a_button_moves_on_from_the_currency_screen(self):
        scene = SceneTraining()
        scene.phase = "building_smash"
        scene.mode = SimpleNamespace(phase="currency", finish_training=mock.Mock(),
                                     handle_event=mock.Mock())
        scene.handle_event(("RIGHT", None))
        scene.mode.finish_training.assert_not_called()
        scene.handle_event(("A", None))
        scene.mode.finish_training.assert_called_once()
        scene.mode.handle_event.assert_not_called()

    def test_bonus_buttons_have_square_corners(self):
        self.party.append(ic_pet())
        scene = SceneTraining()
        scene.show_view("bonus")
        for key, button in scene.mode_buttons.items():
            self.assertFalse(any(button.cut_corners.values()), key)

    def test_each_list_reopens_on_its_own_last_minigame(self):
        self.party.append(ic_pet())
        runtime_globals.training_focus = "mogera"
        runtime_globals.training_bonus_focus = "gotcha"
        scene = SceneTraining()
        self.assertEqual(scene._focused_mode_key(), "mogera")
        scene.show_view("bonus")
        self.assertEqual(scene._focused_mode_key(), "gotcha")

    def test_the_tutorial_never_offers_bonus(self):
        self.party.append(ic_pet())
        self.assertFalse(TutorialTraining().bonus_button.visible)


if __name__ == "__main__":
    unittest.main()
