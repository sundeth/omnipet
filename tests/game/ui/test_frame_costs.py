"""Per-frame work the Pi Zero 2W could not afford stays out of the frame (PERF-01).

Found by tests/platform/pi/perf_scenes.sh on the owner's Pi (2026-10-14):
training 19 fps (51 ms of CPU a frame), the Library 15 fps with a 2.5 s frame,
the tutorial 26 fps. Each fix keeps a cache; these tests keep the caches in use:

* the training menu set its pet row's pets every frame, which marked the row
  for redraw and rebuilt the whole menu's cached surface;
* the Library parsed every module's monster.json in one frame, three times
  over; it now builds a few modules per frame from each module's cached
  roster summary, and a second visit parses nothing;
* the tutorial dialog re-rendered its wrapped text every frame to fade it.
"""
import os
import sys
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "support"))
MODULES = os.path.join(REPO_ROOT, "modules")


@unittest.skipUnless(os.path.isdir(MODULES), "modules folder not present")
class FrameCosts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness import Env
        cls.env = Env("240x240")

    def setUp(self):
        self.env.reset()

    def count_rebuilds(self, game, frames):
        ui = game.scene.ui_manager
        calls = [0]
        original = ui._rebuild_master_ui_surface

        def counting():
            calls[0] += 1
            original()

        ui._rebuild_master_ui_surface = counting
        try:
            self.env.frames(game, frames)
        finally:
            ui._rebuild_master_ui_surface = original
        return calls[0]

    def test_the_training_menu_does_not_rebuild_every_frame(self):
        from harness import quiet
        with quiet():
            game = self.env.game("training")
            self.env.frames(game, 5)
            rebuilds = self.count_rebuilds(game, 60)
        self.assertLessEqual(rebuilds, 2, "the menu's cached surface was rebuilt frame after frame")

    def test_the_training_pet_row_follows_a_pet_that_can_no_longer_train(self):
        from harness import quiet
        with quiet():
            game = self.env.game("training")
            self.env.frames(game, 3)
        scene = game.scene
        before = list(scene.pet_selector.pets)
        self.assertTrue(before)
        before[0].atk_main = 0              # can_train() is now False
        with quiet():
            self.env.frames(game, 2)
        shown = [id(p) for p in scene.pet_selector.pets]
        self.assertNotIn(id(before[0]), shown)
        self.assertEqual(shown, [id(p) for p in before[1:]])

    def test_the_library_builds_module_by_module(self):
        from harness import quiet
        with quiet():
            game = self.env.game("digidex")
        scene = game.scene
        scene.LOAD_BUDGET_S = 0          # one module per frame
        modules = len(self.env.rg.game_modules)
        frames = 0
        labels = set()
        while scene._loading and frames < modules + 5:
            with quiet():
                self.env.frames(game, 1)
            labels.add(scene._loading_label.text if scene._loading else "")
            frames += 1
        self.assertFalse(scene._loading)
        self.assertGreaterEqual(frames, modules, "the roster was built in fewer frames than modules")
        self.assertTrue(any(l.startswith("Loading... ") for l in labels), labels)
        with quiet():
            whole = scene.build_pet_list()
        key = lambda e: (e.name, e.module, e.version, e.known, getattr(e, "availability", None))  # noqa: E731
        self.assertEqual(sorted(map(key, scene.all_pets)), sorted(map(key, whole)))

    def test_a_second_library_visit_parses_no_monster_json(self):
        from harness import quiet
        from models import game_module
        with quiet():
            game = self.env.game("digidex")
            self.env.frames(game, 40)            # first visit: summaries cached
        parses = [0]
        original = game_module.GameModule.get_all_monsters

        def counting(module):
            parses[0] += 1
            return original(module)

        game_module.GameModule.get_all_monsters = counting
        try:
            with quiet():
                game = self.env.game("digidex")
                self.env.frames(game, 40)
        finally:
            game_module.GameModule.get_all_monsters = original
        self.assertFalse(game.scene._loading)
        self.assertEqual(parses[0], 0)

    def test_every_frame_overlays_are_run_length_encoded(self):
        """perf_scenes --profile on the Pi: one alpha blit of the menu overlay
        took 17 ms a frame (and the training border another 17). RLE keeps it
        a copy of the opaque runs; blit_bench.sh measures it on the Pi. (SDL
        encodes at the first blit: RLEACCELOK is the request, RLEACCEL the
        encoded state.)"""
        import pygame
        from harness import quiet
        rle = pygame.RLEACCEL | pygame.RLEACCELOK
        for name in ("settings", "training", "status"):
            with self.subTest(scene=name), quiet():
                game = self.env.game(name)
                self.env.frames(game, 2)
                overlay = game.scene.ui_manager.master_ui_surface
                self.assertTrue(overlay.get_flags() & pygame.RLEACCEL, f"{name}: the UI overlay is not RLE")
        with quiet():
            game = self.env.game("training")
        self.assertTrue(game.scene.static_border_surface.get_flags() & rle, "the training border is not RLE")

    def test_an_overlay_rebuilt_every_frame_is_not_rle(self):
        """RLE pays only while the overlay is still: re-encoding it every frame
        cost the Pi more than the blend (the debug scene went from 34 to 65 ms
        a frame). The UI manager switches it off after RLE_OFF_AFTER rebuilds
        in a row and on again after RLE_ON_AFTER still frames."""
        import pygame
        from ui.ui_manager import UIManager
        from ui.components.button import Button
        ui = UIManager(theme="BLUE")
        ui.add_component(Button(10, 10, 100, 30, "OK", lambda: None))
        target = pygame.Surface((240, 240))
        rle = pygame.RLEACCEL | pygame.RLEACCELOK
        ui.draw(target)
        self.assertTrue(ui.master_ui_surface.get_flags() & rle)
        for _ in range(UIManager.RLE_OFF_AFTER):
            ui.master_ui_dirty = True
            ui.draw(target)
        self.assertFalse(ui.master_ui_surface.get_flags() & rle, "still RLE while rebuilt every frame")
        for _ in range(UIManager.RLE_ON_AFTER):
            ui.draw(target)
        self.assertTrue(ui.master_ui_surface.get_flags() & rle, "RLE did not come back once still")

    def test_monster_lookups_parse_the_file_once_and_hand_out_copies(self):
        """A pet's per-minute evolution and unlock checks call get_monster: it
        parsed the whole monster.json each time (up to 0.4 s on the Pi)."""
        from models import game_module
        module = self.env.rg.game_modules["VB"]
        first = module.get_monster("Pulsemon", 1)
        self.assertIsNotNone(first)
        parses = [0]
        original = game_module.GameModule.get_all_monsters

        def counting(mod):
            parses[0] += 1
            return original(mod)

        game_module.GameModule.get_all_monsters = counting
        try:
            again = [module.get_monster("Pulsemon", 1) for _ in range(20)]
            found = module.find_monster("Pulsemon")
        finally:
            game_module.GameModule.get_all_monsters = original
        self.assertEqual(parses[0], 0, "monster.json was parsed again")
        self.assertEqual(again[0], first)
        self.assertIsNot(again[0], first)
        self.assertEqual(found["name"], "Pulsemon")
        again[0]["name"] = "Changed"
        again[0].setdefault("evolve", []).append({"to": "Nothing"})
        self.assertEqual(module.get_monster("Pulsemon", 1), first, "a caller's change reached the cache")

    def test_a_new_session_reads_the_roster_from_the_disk_cache(self):
        """The Library's first visit of a session parsed every monster.json
        (0.5 s for VB on the Pi); the roster summary is saved under
        save/cache/roster/ for exactly that file (time and size)."""
        import json
        import os
        from models import game_module
        module = self.env.rg.game_modules["VB"]

        def forget():
            for attr in ("_roster_summary", "_monster_records", "_recruit_friends"):
                if hasattr(module, attr):
                    delattr(module, attr)

        path = module._disk_cache_path("roster")
        if os.path.exists(path):
            os.remove(path)
        forget()
        roster = module.roster_summary()
        self.assertTrue(os.path.exists(path), "no cache file written")
        parses = [0]
        original = game_module.GameModule.get_all_monsters

        def counting(mod):
            parses[0] += 1
            return original(mod)

        game_module.GameModule.get_all_monsters = counting
        try:
            forget()
            self.assertEqual(module.roster_summary(), roster)
            self.assertEqual(parses[0], 0, "a new session parsed monster.json despite the cache")
            # a cache for another version of the file is ignored
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            data["stamp"] = [1, 2]
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            forget()
            self.assertEqual(module.roster_summary(), roster)
            self.assertEqual(parses[0], 1, "a stale cache was trusted")
        finally:
            game_module.GameModule.get_all_monsters = original

    def test_the_debug_scene_does_not_rebuild_every_frame(self):
        from harness import quiet
        with quiet():
            game = self.env.game("debug")
            self.env.frames(game, 5)
            rebuilds = self.count_rebuilds(game, 60)
        self.assertLessEqual(rebuilds, 2)

    def test_a_steady_tutorial_focus_is_not_copied_every_frame(self):
        import pygame
        from scenes.tutorial_scenes.tutorial_focus import TutorialFocus
        focus = TutorialFocus()
        focus.focus_on(10, 10, 50, 50)
        while focus.state != focus.STATE_ACTIVE:
            focus.update()
        self.assertTrue(focus.overlay_surface.get_flags() & (pygame.RLEACCEL | pygame.RLEACCELOK))
        drawn = []

        class Target:
            def blit(self, source, pos, *args, **kwargs):
                drawn.append(source)

        for _ in range(3):
            focus.draw(Target())
        self.assertEqual(len(drawn), 3)
        self.assertTrue(all(source is focus.overlay_surface for source in drawn),
                        "a steady overlay was copied before every blit")

    def test_the_tutorial_dialog_reuses_its_box_while_fading(self):
        import pygame
        from ui.components.tutorial_dialog import TutorialDialog
        from ui.ui_manager import UIManager
        ui = UIManager(theme="BLUE")
        dialog = TutorialDialog(x=7, y=190, width=226, height=50)
        ui.add_component(dialog)
        dialog.show_message("Hello *world*, this is a long enough line to wrap.")
        boxes = set()
        for alpha in (20, 120, 255):
            dialog.alpha = alpha
            surface = dialog.render()
            self.assertIsInstance(surface, pygame.Surface)
            self.assertEqual(surface.get_alpha(), alpha)
            boxes.add(id(surface))
        self.assertEqual(len(boxes), 1, "the box was rendered again for an alpha change")
        dialog.show_message("Another message")
        dialog.alpha = 255
        self.assertNotIn(id(dialog.render()), boxes, "a new message reused the old box")


if __name__ == "__main__":
    unittest.main()
