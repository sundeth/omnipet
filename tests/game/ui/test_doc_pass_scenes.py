# -*- coding: utf-8 -*-
"""Scene fixes from the 2026-10-22 documentation pass
(utilities/claude/docs/doc-pass-findings-2026-10-22.md), in the running game.

1   the evolution cutscene: never started from the main screen, and reached
    without an evolution it goes back to the game; with one it plays its
    stage-3 sequence through (it raised NameError on UI_SCALE,
    FONT_SIZE_MEDIUM, SCREEN_WIDTH...)
7   A on a Library quest panel that can be claimed claims it
8   a new day while the main screen or the Library stays open deals the
    day's quests
22  BACK from the Discord pet selection returns to the main menu
28  a full freezer box refuses another Digimon; the box label counts the boxes
30  the Settings hints say LEFT/RIGHT for LEFT/RIGHT
31  Secrets scrolls by the wheel and by its arrow buttons
32  SELECT opens the Digidex FILTER (keys never reached the button)
33  a stage-8 Digimon (DMX's Jesmon GX) shows on Status and in the Digidex
36  the Status Evolution Timer reads the evolution clock
38  Data is "Data"; Next Evolution has a tooltip; a 4-digit trophy count
    shows 999; the Reliability tooltip gives the value; the wheel moves the
    Status pet row
40  no Strength hearts for an iC Digimon; the press that wakes the
    screensaver only wakes it
48  the healing strip shows the party a dose reaches
"""
import datetime
import os
import sys
import types
import unittest
from unittest.mock import patch

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "support"))
MODULES = os.path.join(REPO_ROOT, "modules")


def has(*names):
    return all(os.path.exists(os.path.join(MODULES, n, "module.json")) for n in names)


@unittest.skipUnless(has("DMC", "PENC", "IC", "VB", "DMX"), "modules/ is gitignored")
class DocPassScenes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness import Env
        cls.env = Env("240x240")

    def setUp(self):
        self.env.reset()
        self.gg, self.rg = self.env.gg, self.env.rg

    def pet(self, module):
        return next(p for p in self.gg.pet_list if p.module == module)

    def make_pet(self, module, stage, name=None):
        from models.game_pet import GamePet
        from utils.module_utils import get_module
        records = [m for m in get_module(module).get_monsters_by_stage(stage)
                   if name is None or m.get("name") == name]
        pet = GamePet(dict(records[0], module=module))
        pet.hunger = pet.strength = 4
        return pet

    # ------------------------------------------------------------ 1
    def test_the_evolution_cutscene_is_never_started(self):
        from scenes import scene_maingame
        self.assertFalse(scene_maingame.EVOLUTION_CUTSCENE)
        game = self.env.game("game")
        self.rg.evolution_pet = self.gg.pet_list[0]
        try:
            self.env.frames(game, 5)
        finally:
            self.rg.evolution_pet = None
        self.assertEqual(type(game.scene).__name__, "SceneMainGame")
        self.assertNotEqual(self.rg.game_state, "evolution")

    def test_the_evolution_scene_without_an_evolution_goes_back(self):
        from scenes.scene_evolution import SceneEvolution
        self.rg.evolution_data, self.rg.evolution_pet = [], None
        game = self.env.game("evolution", SceneEvolution)
        self.env.frames(game, 3)
        self.assertEqual(type(game.scene).__name__, "SceneMainGame")
        self.assertEqual(self.env.error_logs(), [])

    def test_the_evolution_scene_plays_through_without_name_errors(self):
        from models.game_evolution_entity import GameEvolutionEntity
        from scenes.scene_evolution import SceneEvolution
        a, b = self.gg.pet_list[0], self.gg.pet_list[1]
        # Stage 3's sequence. The Ultimate ("mega") sequence is unfinished:
        # it calls a replace_pixel that was never written (unreachable).
        for stage in (3,):
            with self.subTest(stage=stage):
                self.env.reset()
                a, b = self.gg.pet_list[0], self.gg.pet_list[1]
                a.stage = stage
                self.rg.evolution_pet = a
                self.rg.evolution_data = [GameEvolutionEntity(
                    from_name=a.name, from_attribute=a.attribute,
                    from_sprite=self.rg.pet_sprites[a][0], to_attribute=b.attribute,
                    to_name=b.name, to_sprite=self.rg.pet_sprites[b][0], stage=stage)]
                try:
                    game = self.env.game("evolution", SceneEvolution)
                    for _ in range(1500):
                        if type(game.scene).__name__ != "SceneEvolution":
                            break
                        self.env.frames(game, 1)
                finally:
                    self.rg.evolution_pet, self.rg.evolution_data = None, []
                self.assertEqual(type(game.scene).__name__, "SceneMainGame", "the scene never ended")

    # ------------------------------------------------------------ 7
    def test_a_on_a_claimable_quest_panel_claims_it(self):
        from models.game_quest import GameQuest, QuestStatus, QuestType, RewardType
        quest = GameQuest("q-doc", "Win", "DMC", QuestType.BATTLE, 1, RewardType.TROPHY, 1, 1)
        quest.current_amount, quest.status = 1, QuestStatus.SUCCESS
        self.gg.quests = [quest]
        game = self.env.game("library")
        self.env.frames(game, 2)
        panel = game.scene.quest_panels[0]
        self.assertTrue(panel.focusable)
        game.scene.ui_manager.set_focused_component(panel)
        self.env.press(game, "A")
        self.assertEqual(quest.status, QuestStatus.FINISHED)

    # ------------------------------------------------------------ 8
    def test_a_new_day_deals_new_quests_on_the_main_screen(self):
        import core.constants as constants
        game = self.env.game("game")
        self.env.frames(game, 1)
        old = list(self.gg.quests)
        self.assertTrue(old, "the main screen deals the day's quests")
        self.gg.xai_date = datetime.date.today() - datetime.timedelta(days=1)
        marker = object()
        with patch("utils.quest_event_utils.generate_daily_quests", return_value=[marker]):
            self.env.frames(game, constants.FRAME_RATE + 1)
        self.assertEqual(self.gg.quests, [marker])
        self.assertEqual(self.gg.xai_date, datetime.date.today())

    def test_a_new_day_deals_new_quests_in_the_library(self):
        import core.constants as constants
        game = self.env.game("library")
        self.env.frames(game, 1)
        self.gg.xai_date = datetime.date.today() - datetime.timedelta(days=1)
        with patch("utils.quest_event_utils.generate_daily_quests", return_value=[]) as deal:
            self.env.frames(game, constants.FRAME_RATE + 1)
        self.assertTrue(deal.called)
        self.assertEqual(self.gg.xai_date, datetime.date.today())

    # ------------------------------------------------------------ 22
    def test_back_from_the_discord_pet_selection_opens_the_main_menu(self):
        self.rg.scene_connect_initial_view = ("pet_selection", {"is_online_mode": True})
        game = self.env.game("connect")
        self.env.frames(game, 2)
        self.assertEqual(type(game.scene.current_view).__name__, "PetSelectionView")
        self.env.press(game, "B")
        self.env.frames(game, 2)
        view = game.scene.current_view
        self.assertEqual(type(view).__name__, "MainMenuView")
        self.assertIsNone(view.current_submenu, "the old arena submenu")

    # ------------------------------------------------------------ 28
    def test_a_full_freezer_box_refuses_another_digimon(self):
        from models.game_freezer import BOX_CAPACITY
        game = self.env.game("freezer")
        self.env.frames(game, 2)
        scene = game.scene
        box = scene.freezer_pets[scene.current_freezer_page]
        box.pets[:] = [self.make_pet("DMC", 3) for _ in range(BOX_CAPACITY)]
        pet = self.gg.pet_list[0]
        scene.mode = "party"
        with patch.object(scene.party_grid, "get_selected_item", return_value=types.SimpleNamespace(data=pet)):
            scene._on_menu_select(0)
        self.assertIn(pet, self.gg.pet_list, "stays in the party")
        self.assertEqual(len(box.pets), BOX_CAPACITY)
        box.pets.pop()
        with patch.object(scene.party_grid, "get_selected_item", return_value=types.SimpleNamespace(data=pet)):
            scene._on_menu_select(0)
        self.assertNotIn(pet, self.gg.pet_list)
        self.assertIn(pet, box.pets, "a box with room takes it")
        self.assertEqual(scene._box_label_text(), f"Box {scene.current_freezer_page + 1}/{len(scene.freezer_pets)}")

    # ------------------------------------------------------------ 30, 31
    def secrets(self, input_mode):
        self.env.reset(input_mode=input_mode)
        game = self.env.game("settings")
        self.env.frames(game, 2)
        scene = game.scene
        scene.unlockables_data = [{"name": "DMC", "icon": None, "all": [{}] * 9,
                                   "unlocked": [{"name": f"secret{i}", "label": f"Secret {i}"} for i in range(9)]}]
        scene.current_unlock_module_index = 0
        scene.current_unlock_item_index = 0
        with patch.object(scene, "_current_section_key", return_value="unlockables"), \
                patch.object(scene, "_load_unlockables", lambda: None):
            scene._clear_dynamic()
            scene._build_unlockables_view()
        return game, scene

    def labels(self, scene):
        return [getattr(c, "text", "") for c in scene._dynamic_components]

    def test_the_settings_hints_name_left_and_right(self):
        _, scene = self.secrets(self.rg.KEYBOARD_MODE if hasattr(self.rg, "KEYBOARD_MODE") else None)
        texts = self.labels(scene)
        self.assertIn("LEFT/RIGHT: Module", texts)
        self.assertFalse([t for t in texts if t.startswith("L/R")])
        import inspect
        from scenes import scene_settingsmenu
        self.assertNotIn('"L/R:', inspect.getsource(scene_settingsmenu))

    def test_secrets_scroll_by_the_wheel_and_the_arrows(self):
        game, scene = self.secrets(self.rg.MOUSE_MODE)
        with patch.object(scene, "_current_section_key", return_value="unlockables"):
            scene.handle_event(("SCROLL", {"direction": "DOWN", "amount": 1}))
            self.assertEqual(scene.current_unlock_item_index, 1)
            scene.handle_event(("SCROLL", {"direction": "UP", "amount": 1}))
            self.assertEqual(scene.current_unlock_item_index, 0)
        self.assertTrue(scene._unlock_down_button.visible)
        scene._unlock_down_button.on_click_callback()
        scene._unlock_down_button.on_click_callback()
        self.assertEqual(scene.current_unlock_item_index, 2)
        scene._unlock_up_button.on_click_callback()
        self.assertEqual(scene.current_unlock_item_index, 1)
        shown = [lbl.text for lbl in scene._unlock_item_labels]
        self.assertIn("Secret 1", shown)

    # ------------------------------------------------------------ 33
    def test_a_stage_8_digimon_shows_on_status_and_in_the_digidex(self):
        import core.constants as constants
        from ui.components.stats_panel import StatsPanel
        pet = self.make_pet("DMX", 8)
        self.assertEqual(pet.stage, 8)
        self.assertEqual(constants.stage_name(8), "VIII-Super Ultimate+")
        self.assertEqual(constants.stage_name(42), "42")
        self.gg.pet_list.append(pet)
        game = self.env.game("status")
        self.env.frames(game, 2)
        game.scene.on_pet_selected(pet)
        self.env.frames(game, 2)
        StatsPanel(pet)
        self.assertEqual(self.env.error_logs(), [])

    # ------------------------------------------------------------ 32
    def test_select_opens_the_digidex_filter_from_keys(self):
        game = self.env.game("digidex")
        for _ in range(400):
            self.env.frames(game, 1)
            if not game.scene._loading:
                break
        scene = game.scene
        self.env.press(game, "A")                  # "All": the list
        self.env.frames(game, 2)
        self.assertEqual(scene.state, "list")
        self.assertIsNone(scene.ui_manager.active_menu)
        self.env.press(game, "SELECT")
        self.assertIsNotNone(scene.ui_manager.active_menu, "FILTER was out of reach of the keys")

    # ------------------------------------------------------------ 36
    def test_the_evolution_timer_reads_the_evolution_clock(self):
        from ui.components.status_carousel import StatusCarousel
        fmt = StatusCarousel.format_evolution_timer
        data = {"evolution_timer": 120, "evolution_minutes": 30, "timer": 10 ** 7, "evolve": [{"to": "X"}]}
        self.assertEqual(fmt(None, data), "01:30")
        self.assertEqual(fmt(None, dict(data, evolution_minutes=200)), "00:00")
        self.assertEqual(fmt(None, dict(data, evolve=[])), "")
        self.assertEqual(fmt(None, dict(data, evolution_timer="00:00")), "")
        pet = self.pet("DMC")
        pet.time, pet._evol_minutes, pet.timer = 600, 120, 5
        game = self.env.game("status")
        self.env.frames(game, 2)
        game.scene.on_pet_selected(pet)
        self.env.frames(game, 1)
        boxes = {b["id"]: b for b in game.scene.status_carousel.boxes}
        if "evolution_timer" in boxes:
            self.assertEqual(boxes["evolution_timer"]["value"], "08:00")

    # ------------------------------------------------------------ 38
    def test_status_small_fixes(self):
        from ui.components.flag_panel import FlagPanel
        from ui.components.numeric_meter import NumericMeter
        from ui.components.status_carousel import StatusCarousel
        panel = FlagPanel.__new__(FlagPanel)
        panel.flags = []
        with patch.object(FlagPanel, "_layout_flags", create=True, return_value=[]):
            try:
                panel.set_pet_flags(types.SimpleNamespace(attribute="Da"))
            except Exception:
                pass
        self.assertIn(("Da", "Attribute: Data"), panel.flags)
        self.assertEqual(StatusCarousel.box_tooltip({"id": "next_evolution", "name": "Next Evolution",
                                                     "value": "", "sprite": None}),
                         "Next Evolution: no route met yet")
        self.assertTrue(StatusCarousel.box_tooltip({"id": "next_evolution", "name": "Next Evolution",
                                                    "value": "", "sprite": object()}).endswith("heading for"))
        meter = NumericMeter(0, 0, 47, 24, "Trophies", 1234, max_digits=3)
        self.assertEqual(meter.display_text(), "999")
        meter.set_value(42)
        self.assertEqual(meter.display_text(), "42")

    def test_the_reliability_tooltip_gives_the_value(self):
        pet = self.pet("IC")
        pet.reliability = 12
        game = self.env.game("status")
        self.env.frames(game, 2)
        game.scene.on_pet_selected(pet)
        self.env.frames(game, 1)
        meter = game.scene.reliability_meter
        self.assertTrue(meter.visible)
        self.assertTrue(meter.tooltip_text.startswith("Reliability 12/31"), meter.tooltip_text)

    def test_the_wheel_moves_the_status_pet_row(self):
        self.env.reset(input_mode=self.rg.MOUSE_MODE)
        game = self.env.game("status")
        self.env.frames(game, 2)
        from ui.components.pet_list import PetList
        lists = [c for c in game.scene.ui_manager.components if isinstance(c, PetList)]
        self.assertTrue(lists, "the Status scene has a pet row")
        row = lists[0]
        before = row.selected_index
        self.assertTrue(row.handle_scroll(("SCROLL", {"direction": "DOWN", "amount": 1})))
        self.assertNotEqual(row.selected_index, before)
        self.assertTrue(row.handle_scroll(("SCROLL", {"direction": "UP", "amount": 1})))
        self.assertEqual(row.selected_index, before)

    # ------------------------------------------------------------ 40
    def test_no_strength_hearts_for_an_ic_digimon(self):
        game = self.env.game("game")
        self.env.frames(game, 1)
        scene = game.scene
        calls = []
        with patch.object(type(scene), "draw_hearts", lambda self, *a: calls.append(a)):
            scene.draw_pet(self.rg.render_surface, self.pet("IC"), 0, set(), True)
            ic_rows = len(calls)
            del calls[:]
            scene.draw_pet(self.rg.render_surface, self.pet("DMC"), 0, set(), True)
            dmc_rows = len(calls)
        self.assertEqual((ic_rows, dmc_rows), (1, 2))

    def test_the_press_that_wakes_the_screensaver_only_wakes_it(self):
        game = self.env.game("game")
        self.env.frames(game, 1)
        scene = game.scene
        scene._ss_active = True
        with patch.object(type(scene), "handle_action_keys", create=True) as act:
            self.env.press(game, "A")
            self.assertFalse(act.called, "the waking press acted")
            self.assertFalse(scene._ss_active)
            self.env.press(game, "A")
        self.assertTrue(act.called, "the next press acts")

    # ------------------------------------------------------------ 48
    def test_the_healing_strip_shows_the_party(self):
        from utils import ailments
        party = [p for p in self.gg.pet_list if p.stage > 0]
        self.rg.selected_pets = [party[0]]
        ailments.add(party[1], "sick") if hasattr(ailments, "add") else None
        game = self.env.game("healing")
        self.env.frames(game, 1)
        self.assertEqual(list(game.scene.pet_selector.pets), party)


if __name__ == "__main__":
    unittest.main()
