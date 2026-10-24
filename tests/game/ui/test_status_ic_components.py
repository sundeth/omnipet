# -*- coding: utf-8 -*-
"""The Status scene's Connect Points meter and Next Evolution box, in the
running game (owner, 2026-10-20).

    iC Connect Points   on Reliability's gauge in the row right below it,
                        the pet's points out of the module's cap (15)
    other modules       a module without Connect Points (DMC) shows none
    DW1                 Effort keeps the row below Reliability, so its Connect
                        Points (cap 10) take the top of the right column
    iC Next Evolution   the iC lists it: the carousel shows the coming form's
                        frame 0 in black, or "?" when no route is met; DMC
                        does not list it
    nothing per frame   frames on the Status scene and showing a pet again
                        neither preview the evolution nor load sprites

The party is the harness's DMC and iC pets plus a DW1 one (each a Child).
"""
import os
import sys
import unittest
from unittest.mock import patch

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "support"))
MODULES = os.path.join(REPO_ROOT, "modules")


@unittest.skipUnless(os.path.exists(os.path.join(MODULES, "IC", "module.json")), "modules/ is gitignored")
class StatusICComponents(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness import Env
        cls.env = Env("240x240", party=[("DMC", 1), ("IC", 1), ("DW1", 1)])

    def setUp(self):
        from ui.components import status_carousel
        env = self.env
        env.reset(input_mode=env.rg.TOUCH_MODE)
        status_carousel._SILHOUETTES.clear()
        self.gg = env.gg
        self.ic = self.pet("IC")
        self.dmc = self.pet("DMC")

    def pet(self, module):
        return next((p for p in self.gg.pet_list if p.module == module), None)

    def status(self, pet):
        game = self.env.game("status")
        self.env.frames(game, 2)
        game.scene.on_pet_selected(pet)
        self.env.frames(game, 2)
        return game, game.scene

    def next_evolution_box(self, scene):
        return next((b for b in scene.status_carousel.boxes if b["id"] == "next_evolution"), None)

    # ------------------------------------------------------------ Connect Points
    def test_ic_connect_points_right_below_reliability(self):
        self.ic.connect_points = 9
        _, scene = self.status(self.ic)
        cp, rel, hunger = scene.connect_points_meter, scene.reliability_meter, scene.hunger_meter
        self.assertTrue(cp.visible)
        self.assertTrue(rel.visible)
        self.assertEqual((cp.label, cp.value, cp.maximum), ("CP", 9, 15))
        self.assertEqual(cp.rect.x, rel.rect.x)
        self.assertEqual(cp.rect.size, rel.rect.size)
        self.assertEqual(cp.rect.y - rel.rect.y, rel.rect.y - hunger.rect.y, "the next row")
        self.assertFalse(scene.effort_meter.visible)
        self.assertTrue(cp.tooltip_text.startswith("Connect Points 9/15"), cp.tooltip_text)
        self.assertEqual(self.env.error_logs(), [])

    def test_only_modules_with_connect_points_show_them(self):
        self.ic.connect_points = 4
        game, scene = self.status(self.dmc)
        self.assertFalse(scene.connect_points_meter.visible)
        scene.on_pet_selected(self.ic)
        self.env.frames(game, 2)
        self.assertTrue(scene.connect_points_meter.visible)
        self.assertEqual(scene.connect_points_meter.value, 4)
        scene.on_pet_selected(self.dmc)
        self.env.frames(game, 2)
        self.assertFalse(scene.connect_points_meter.visible)
        self.assertEqual(self.env.error_logs(), [])

    def test_dw1_connect_points_in_the_right_column(self):
        dw1 = self.pet("DW1")
        if dw1 is None:
            self.skipTest("no DW1 module")
        from utils import connect_points
        from utils.module_utils import get_module
        cap = int((connect_points.settings(get_module("DW1")) or {}).get("cap", 0))
        if not cap:
            self.skipTest("DW1 has no Connect Points")
        dw1.connect_points = 3
        game, scene = self.status(dw1)
        cp = scene.connect_points_meter
        self.assertTrue(cp.visible)
        self.assertTrue(scene.effort_meter.visible, "Effort keeps the row below Reliability")
        self.assertEqual((cp.value, cp.maximum), (3, cap))
        self.assertEqual(cp.rect.x, scene.dp_bar.rect.x)
        self.assertEqual(cp.rect.y, scene.hunger_meter.rect.y)
        # Back on the iC pet, it returns below Reliability.
        scene.on_pet_selected(self.ic)
        self.env.frames(game, 2)
        self.assertEqual(cp.rect.x, scene.reliability_meter.rect.x)
        self.assertEqual(self.env.error_logs(), [])

    # ------------------------------------------------------------ Next Evolution
    def test_ic_shows_the_next_evolution(self):
        from utils.module_utils import get_module
        self.assertIn("Next Evolution", get_module("IC").visible_stats)
        target = self.ic.preview_evolution()
        self.assertIsNotNone(target, "the harness's iC Child has a route")
        game, scene = self.status(self.ic)
        box = self.next_evolution_box(scene)
        self.assertIsNotNone(box, "a Next Evolution box in the carousel")
        sprite = box["sprite"]
        self.assertIsNotNone(sprite, f"{target['name']}'s frame 0")
        w, h = sprite.get_size()
        shown = [sprite.get_at((x, y)) for x in range(w) for y in range(h)]
        self.assertTrue(any(c[3] for c in shown), "not empty")
        self.assertTrue(all(tuple(c[:3]) == (0, 0, 0) for c in shown if c[3]), "all black")

        with patch.object(self.ic, "preview_evolution", lambda: None, create=True):
            scene.on_pet_selected(self.ic)
            self.env.frames(game, 2)
        box = self.next_evolution_box(scene)
        self.assertIsNotNone(box)
        self.assertIsNone(box["sprite"], "no route: the box draws a ?")

        scene.on_pet_selected(self.dmc)
        self.env.frames(game, 2)
        self.assertIsNone(self.next_evolution_box(scene), "DMC does not list it")
        self.assertEqual(self.env.error_logs(), [])

    def test_nothing_is_worked_out_per_frame(self):
        from models.game_pet import GamePet
        game, scene = self.status(self.ic)
        previews = []
        real_preview = GamePet.preview_evolution

        def counted(pet):
            previews.append(pet.name)
            return real_preview(pet)
        with patch.object(GamePet, "preview_evolution", counted), \
                patch("utils.sprite_utils.load_pet_sprites", side_effect=AssertionError("loaded")) as loads:
            self.env.frames(game, 30)
            self.assertEqual(previews, [], "no evolution check while the screen shows")
            scene.on_pet_selected(self.dmc)
            scene.on_pet_selected(self.ic)          # its form is cached
            self.env.frames(game, 5)
            self.assertEqual(loads.call_count, 0)
        self.assertEqual(previews, [self.ic.name], "once, when the iC pet is shown again")
        self.assertIsNotNone(self.next_evolution_box(scene)["sprite"])
        self.assertEqual(self.env.error_logs(), [])


if __name__ == "__main__":
    unittest.main()
