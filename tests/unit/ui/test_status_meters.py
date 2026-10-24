"""Status scene pieces (owner, 2026-10-20): Connect Points and Next Evolution.

    CP slot           the row below Reliability when Effort and G-Cells leave
                      it free (the iC); else the top of the right column when
                      there is no DP bar (DW1); else nowhere
    same gauge        the CP meter is Reliability's gauge with "CP" and the
                      module's cap: empty and full it draws exactly what REL
                      draws at 0 and 31, gauges lined up
    range             values clamp to 0..cap; a new cap clamps the value
    silhouette cache  a form's silhouette is made once: one sprite load per
                      form, a form without art remembered as None
    big "?"           with no form to show, the box draws a "?" taller than
                      the title font's and over half the box
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SRC = os.path.join(REPO_ROOT, "src")
for path in (SRC, REPO_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

import pygame  # noqa: E402

from scenes.scene_status import connect_points_slot, connect_points_tooltip  # noqa: E402
from ui.components import status_carousel  # noqa: E402
from ui.components.reliability_meter import ReliabilityMeter  # noqa: E402

IC_STATS = ["Age", "Weight", "Hunger", "Stomach", "Power", "Battles", "Win Rate",
            "Total Win Rate", "Evolution Timer", "Next Evolution", "Flags",
            "Reliability", "Digisoul"]
DW1_STATS = ["Age", "Weight", "Hunger", "Effort", "Power", "Battles", "Win Rate",
             "Total Win Rate", "Mistakes/Condition Hearts", "Evolution Timer",
             "Reliability", "Flags", "Virus"]
DMC_STATS = ["Age", "Weight", "Hunger", "Strength", "Effort", "Power", "DP",
             "Battles", "Win Rate", "Total Win Rate", "Flags"]


class ConnectPointsSlot(unittest.TestCase):
    def test_slots(self):
        for stats, slot in ((IC_STATS, "left"), (DW1_STATS, "right"),
                            (DMC_STATS, None), (["G-Cells", "DP"], None),
                            (["G-Cells"], "right"), ([], "left")):
            with self.subTest(stats=stats):
                self.assertEqual(connect_points_slot(stats), slot)

    def test_tooltip_gives_the_fill(self):
        self.assertTrue(connect_points_tooltip(9, 15).startswith("Connect Points 9/15"))


class MeterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((240, 240))
        from ui.ui_manager import UIManager
        cls.manager = UIManager("PURPLE")

    def meter(self, value, **kw):
        meter = ReliabilityMeter(0, 0, 85, 24, value, **kw)
        self.manager.add_component(meter)
        self.addCleanup(self.manager.remove_component, meter)
        return meter

    def cp(self, value, cap=15):
        return self.meter(value, label="CP", minimum=0, maximum=cap)

    def test_reliability_keeps_its_range(self):
        rel = self.meter(40)
        self.assertEqual((rel.label, rel.minimum, rel.maximum, rel.value), ("REL", 0, 31, 31))

    def test_connect_points_clamp_to_the_cap(self):
        for value, shown in ((-1, 0), (0, 0), (9, 9), (15, 15), (16, 15), ("x", 0), (None, 0)):
            with self.subTest(value=value):
                self.assertEqual(self.cp(value).value, shown)
        meter = self.cp(12)
        meter.set_maximum(10)
        self.assertEqual((meter.maximum, meter.value), (10, 10))
        meter.set_value(4)
        self.assertEqual(meter.value, 4)

    def test_the_same_gauge_lined_up(self):
        """Empty and full, CP's gauge is pixel for pixel REL's: the label
        differs, the gauge starts at the same x and the marker reaches the
        same ends."""
        for rel_value, cp_value in ((0, 0), (31, 15)):
            with self.subTest(rel=rel_value, cp=cp_value):
                rel = self.meter(rel_value).render()
                cp = self.cp(cp_value).render()
                gauge = pygame.Rect(30, 0, rel.get_width() - 30, rel.get_height())
                self.assertEqual(pygame.image.tostring(rel.subsurface(gauge), "RGBA"),
                                 pygame.image.tostring(cp.subsurface(gauge), "RGBA"))
                self.assertNotEqual(pygame.image.tostring(rel, "RGBA"),
                                    pygame.image.tostring(cp, "RGBA"), "the labels differ")

    def test_the_marker_moves_with_the_points(self):
        a, b = self.cp(3).render(), self.cp(9).render()
        self.assertNotEqual(pygame.image.tostring(a, "RGBA"), pygame.image.tostring(b, "RGBA"))

    def test_a_big_question_mark_without_a_form(self):
        from ui.ui_constants import PURPLE
        carousel = status_carousel.StatusCarousel(0, 0, 230, 38)
        self.manager.add_component(carousel)
        self.addCleanup(self.manager.remove_component, carousel)
        carousel.set_pet_data({"visible_stats": ["Next Evolution"], "next_evolution": None})
        box = carousel.create_box_surface(carousel.boxes[0], 0, carousel.get_font("text"))
        mark = pygame.mask.from_threshold(box, PURPLE, (1, 1, 1, 255)).get_bounding_rects()
        self.assertTrue(mark, "a ? is drawn")
        height = max(r.bottom for r in mark) - min(r.top for r in mark)
        title = carousel.get_font("title").render("?", True, PURPLE).get_bounding_rect()
        self.assertGreater(height, title.height)
        self.assertGreater(height, carousel.box_height // 2)


class SilhouetteCache(unittest.TestCase):
    def setUp(self):
        status_carousel._SILHOUETTES.clear()
        self.addCleanup(status_carousel._SILHOUETTES.clear)

    def test_each_form_is_loaded_once(self):
        frame = pygame.Surface((4, 4), pygame.SRCALPHA)
        frame.fill((0, 0, 0, 0))
        frame.set_at((2, 2), (10, 200, 30, 255))
        targets = {"name": "Childmon"}
        pet = SimpleNamespace(module="Test", preview_evolution=lambda: targets)
        module = SimpleNamespace(folder_path="x")
        loads = mock.Mock(side_effect=lambda name, *a, **k: {0: frame} if name == "Childmon" else {})
        with mock.patch("utils.module_utils.get_module", return_value=module), \
                mock.patch("utils.sprite_utils.load_pet_sprites", loads):
            first = status_carousel.evolution_silhouette(pet)
            self.assertIs(status_carousel.evolution_silhouette(pet), first, "the cached one")
            self.assertEqual(loads.call_count, 1)
            self.assertEqual(tuple(first.get_at((2, 2))), (0, 0, 0, 255))
            self.assertEqual(first.get_at((0, 0))[3], 0)
            targets = {"name": "Noartmon"}
            pet.preview_evolution = lambda: targets
            self.assertIsNone(status_carousel.evolution_silhouette(pet))
            self.assertIsNone(status_carousel.evolution_silhouette(pet))
            self.assertEqual(loads.call_count, 2, "a form without art is remembered too")
            pet.preview_evolution = lambda: None
            self.assertIsNone(status_carousel.evolution_silhouette(pet))
            self.assertEqual(loads.call_count, 2, "no form, nothing loaded")


if __name__ == "__main__":
    unittest.main()
