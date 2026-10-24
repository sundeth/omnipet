"""The card Collection scene (owner, 2026-10-20, from screenshots at 240x240):

1. "Some texts are drawn over each other": the COLLECTION title ran into its
   bar's chevrons, and the module line ("DW1 0/66 (0 cards)", drawn in a
   24-pixel font in a 16-pixel row) into the title and the grid. The title is
   CARDS, the line is drawn in the tiles' name font in a row that holds it,
   and at every resolution the game offers the title, the page and the
   bottom row stay apart.
2. "No drag or scroll-wheel support in the grid": the wheel glides the grid a
   row a notch and a drag moves it with the pointer, as the item lists do.
3. "An option to show only obtained cards", in the FILTER menu.
4. "Show how many copies of each card the player has": x<copies> on the card.
5. "The VIEW / READ / EXIT buttons sit too high": the bottom row of the
   adventure screens (y 198, 25 high, 9 from the edges).
6. "The card grid is not horizontally centred."
7. Shiny cards shimmer in holo foil (`ui.card_holo`), over the art only.
"""
import os
import sys
import unittest
from unittest.mock import patch

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "support"))
MODULES = os.path.join(REPO_ROOT, "modules")

#: Every resolution the scene sweep covers (tests/release/scene_sweep.py),
#: with the window sizes between the UI's whole scales (360x360).
RESOLUTIONS = ["240x240", "360x360", "480x480", "720x720", "960x960", "320x240",
               "240x320", "800x480", "1280x720", "1400x640", "1920x1080"]


@unittest.skipUnless(os.path.isdir(os.path.join(MODULES, "IC")), "the IC module is not present")
class CollectionScene(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness import Env
        cls.env = Env("240x240")

    def setUp(self):
        self.at("240x240")

    def at(self, res):
        """Back to the fixture at *res* (the harness rebuilds the canvas)."""
        env = self.env
        env.w, env.h = (int(x) for x in res.split("x"))
        env.reset()

    def ic_plates(self):
        from utils import card_utils
        cards = card_utils.ordered_cards(card_utils.get_module_cards("IC")["cards"])
        return [card for card in cards if card.get("type") == "iD Plate"]

    def open(self, module=None, obtained_only=False):
        from harness import quiet
        with quiet():
            game = self.env.game("collection")
        if module or obtained_only:
            game.scene._apply_filter(module, obtained_only=obtained_only)
        self.env.frames(game, 2)
        return game, game.scene

    # ------------------------------------------------------------ 1, 5, 6

    def test_nothing_overlaps_at_any_resolution(self):
        from scenes import scene_collection as sc
        for res in RESOLUTIONS:
            with self.subTest(res=res):
                self.at(res)
                game, scene = self.open()
                s = scene.scale
                content_top, content_bottom = scene._sy(sc.CONTENT_TOP), scene._sy(sc.CONTENT_BOTTOM)
                title = scene.title_scene
                bar = title.yellow_bright_background_sprite
                self.assertLessEqual(title.rect.top + bar.get_height(), content_top, "title bar over the page")
                # The bar's chevrons start 101 base pixels in; the title ends before them.
                self.assertLessEqual(title.text_margin + title.font.size(title.title_text)[0], 100 * s,
                                     "the title runs into its bar's chevrons")
                self.assertLessEqual(scene.filter_button.rect.bottom, content_top)
                for button in (scene.view_button, scene.read_button, scene.exit_button):
                    self.assertGreaterEqual(button.rect.top, content_bottom, f"{button.text} over the page")
                    self.assertLessEqual(button.rect.bottom, scene._sy(240))
                # The module line and the tile names fit their rows.
                self.assertLessEqual(scene.font_name.get_linesize(), scene.header_h * s)
                self.assertLessEqual(scene.font_name.get_height(), scene.name_h * s)
                first = scene.card_entries[0]
                self.assertEqual(scene.entries[0]["kind"], "header")
                self.assertGreaterEqual(first["y"], scene.header_h, "the first row under its header")
                # The grid is centred.
                left = min(e["x"] for e in scene.card_entries)
                right = max(e["x"] for e in scene.card_entries) + sc.TILE_W
                self.assertEqual(left, 240 - right)

    def test_the_bottom_row_is_where_the_other_screens_have_it(self):
        game, scene = self.open()
        manager = scene.ui_manager
        expected = {"VIEW": (9, 198, 66, 25), "READ": (85, 198, 70, 25), "EXIT": (165, 198, 66, 25)}
        for button in (scene.view_button, scene.read_button, scene.exit_button):
            self.assertEqual(tuple(button.base_rect), expected[button.text])
        self.assertEqual(manager.ui_to_screen_rect(scene.view_button.base_rect), scene.view_button.rect)
        self.assertEqual((scene.use_button.base_rect.left, scene.view_back_button.base_rect.right),
                         (9, 231))

    # ------------------------------------------------------------ 2

    def test_the_wheel_glides_a_row_a_notch(self):
        from scenes import scene_collection as sc
        game, scene = self.open()
        selection = scene.selection
        game.dispatch_input(("SCROLL", {"amount": 1, "direction": "DOWN"}))
        self.assertEqual(scene.scroll_target, sc.TILE_H + sc.TILE_GAP)
        self.assertIn("menu", self.env.sounds)
        self.env.frames(game, 30)
        self.assertEqual(scene.scroll_y, scene.scroll_target)
        self.assertEqual(scene.selection, selection, "the wheel scrolls; the selection stays")
        for _ in range(3):
            game.dispatch_input(("SCROLL", {"amount": 1, "direction": "UP"}))
        self.assertEqual(scene.scroll_target, 0, "never above the top")
        game.dispatch_input(("SCROLL", {"amount": 10 ** 4, "direction": "DOWN"}))
        self.assertEqual(scene.scroll_target, scene._max_scroll(), "never below the bottom")

    def test_a_drag_moves_the_grid_with_the_pointer(self):
        game, scene = self.open()
        s = scene.scale
        start = (scene._sx(120), scene._sy(150))
        selection = scene.selection
        game.dispatch_input(("DRAG_START", {"pos": start}))
        game.dispatch_input(("DRAG_MOTION", {"pos": (start[0], start[1] - 60 * s), "start_pos": start}))
        self.assertEqual(scene.scroll_y, 60)
        game.dispatch_input(("DRAG_MOTION", {"pos": (start[0], start[1] - 20 * s), "start_pos": start}))
        self.assertEqual(scene.scroll_y, 20, "it follows the pointer back")
        game.dispatch_input(("DRAG_END", {"pos": start, "start_pos": start}))
        self.env.frames(game, 5)
        self.assertEqual(scene.scroll_y, 20, "it stays where it was left")
        self.assertEqual((scene.mode, scene.selection), ("grid", selection), "a drag selects nothing")
        # A drag on the bottom row is not the grid's.
        game.dispatch_input(("DRAG_START", {"pos": scene.read_button.rect.center}))
        game.dispatch_input(("DRAG_MOTION", {"pos": (start[0], 0), "start_pos": start}))
        self.assertEqual(scene.scroll_y, 20)

    def test_the_arrows_bring_the_selection_back_after_the_wheel(self):
        from scenes import scene_collection as sc
        game, scene = self.open()
        for _ in range(6):
            game.dispatch_input(("SCROLL", {"amount": 1, "direction": "DOWN"}))
        self.env.frames(game, 60)
        self.assertGreater(scene.scroll_y, scene.card_entries[0]["y"])
        self.env.press(game, "RIGHT")
        self.env.frames(game, 60)
        entry = scene.card_entries[scene.selection]
        self.assertEqual(scene.selection, 1)
        self.assertGreaterEqual(entry["y"], scene.scroll_y)
        self.assertLessEqual(entry["y"] + sc.TILE_H, scene.scroll_y + sc.CONTENT_BOTTOM - sc.CONTENT_TOP)

    # ------------------------------------------------------------ 3, 4

    def test_filter_shows_only_the_obtained_cards(self):
        from utils import card_utils
        plates = self.ic_plates()
        card_utils.add_card_copy("IC", plates[3]["id"])
        card_utils.add_card_copy("IC", plates[7]["id"])
        game, scene = self.open(module="IC")
        scene.selection = next(i for i, e in enumerate(scene.card_entries)
                               if e["card"]["id"] == plates[7]["id"])
        options = self.choose_switch(game, scene)
        self.assertEqual(options[:2], ["Obtained: OFF", "All"])
        self.assertTrue(scene.obtained_only)
        self.assertEqual([e["card"]["id"] for e in scene.card_entries], [plates[3]["id"], plates[7]["id"]])
        self.assertEqual(scene.card_entries[scene.selection]["card"]["id"], plates[7]["id"],
                         "the selected card stays selected")
        self.assertIn("IC  2/50  (2 cards)", [e.get("text") for e in scene.entries],
                      "the header still counts the whole module")
        self.env.frames(game, 2)
        options = self.choose_switch(game, scene)
        self.assertEqual(options[0], "Obtained: ON")
        self.assertFalse(scene.obtained_only)
        self.assertEqual(len(scene.card_entries), 50)
        self.assertEqual(scene.module_filter, "IC", "the switch keeps the module")

    def choose_switch(self, game, scene):
        """SELECT opens FILTER on the module shown; up to the switch and A.
        Returns the menu's options."""
        self.env.press(game, "SELECT")
        menu = scene.ui_manager.active_menu
        options = list(menu.options)
        self.assertEqual(options[menu.selected_index], scene.module_filter or "All",
                         "the cursor starts on what the grid shows")
        for _ in range(menu.selected_index):
            self.env.press(game, "UP")
        self.env.press(game, "A")
        return options

    def test_with_nothing_obtained_the_grid_says_so(self):
        game, scene = self.open(obtained_only=True)
        self.assertEqual(scene.card_entries, [])
        self.env.frames(game, 2)
        self.assertIn(("No cards obtained"), [key[1] for key in scene._label_cache])
        self.assertEqual(self.env.error_logs(), [])

    def test_a_card_shows_how_many_copies_the_player_has(self):
        from utils import card_utils
        plate = self.ic_plates()[0]
        for _ in range(2):
            card_utils.add_card_copy("IC", plate["id"])
        card_utils.add_card_copy("IC", plate["id"], physical=True)
        game, scene = self.open(module="IC", obtained_only=True)
        with patch.object(scene, "_badge", wraps=scene._badge) as badge:
            self.env.frames(game, 1)
        self.assertIn("x3", [c.args[1] for c in badge.call_args_list])

    # ------------------------------------------------------------ 7

    def test_a_shiny_card_shimmers_in_the_grid_and_on_its_page(self):
        from ui import card_holo
        from utils import card_utils
        shiny, plain = self.ic_plates()[:2]
        card_utils.add_card_copy("IC", shiny["id"], shiny=True)
        card_utils.add_card_copy("IC", plain["id"])
        game, scene = self.open(module="IC", obtained_only=True)
        with patch.object(card_holo, "draw_holo", wraps=card_holo.draw_holo) as holo:
            self.env.frames(game, 1)
            self.assertEqual([c.args[1]["id"] for c in holo.call_args_list], [shiny["id"]])
            holo.reset_mock()
            self.env.press(game, "A")
            self.env.frames(game, 1)
            self.assertEqual(scene.mode, "view")
            self.assertEqual([c.args[1]["id"] for c in holo.call_args_list], [shiny["id"]])
        self.assertEqual(self.env.error_logs(), [])

    def test_card_faces_are_rle_encoded_for_the_pi(self):
        import pygame
        from utils import card_utils
        plate = self.ic_plates()[0]
        card_utils.add_card_copy("IC", plate["id"])
        game, scene = self.open(module="IC")
        self.env.frames(game, 1)
        entry = scene.card_entries[0]
        tile_w, image_h = 68 * scene.scale, (96 - scene.name_h) * scene.scale
        face = scene._card_face("IC", entry["card"], tile_w - 2, image_h - 2)
        self.assertTrue(face.get_flags() & (pygame.RLEACCEL | pygame.RLEACCELOK))


if __name__ == "__main__":
    unittest.main()
