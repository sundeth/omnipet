"""No focus highlight in touch mode; keyboard and mouse keep theirs (UI-02).

Touch has no cursor: focus there only routes a tap to its component
(UIManager focuses whatever is tapped), so a component must render the same
focused or not. `UIComponent.focus_visible` is the one switch; the menu crawl
(tests/release/menu_crawl.py) checks every screen it reaches the
same way, by comparing pixels.
"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

import pygame  # noqa: E402

from core import runtime_globals  # noqa: E402


class TouchFocusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((240, 240))

    def setUp(self):
        self._mode = runtime_globals.INPUT_MODE
        self.addCleanup(setattr, runtime_globals, "INPUT_MODE", self._mode)

    def render(self, component, focused):
        component.focused = focused
        component.needs_redraw = True
        return pygame.image.tostring(component.render(), "RGBA")

    def components(self):
        from ui.ui_manager import UIManager
        from ui.components.button import Button
        from ui.components.heart_meter_condition import HeartMeterCondition
        manager = UIManager()
        made = [Button(20, 20, 80, 24, "OK", lambda: None)]
        try:
            made.append(HeartMeterCondition(20, 60, 100, 20))
        except TypeError:
            pass
        for c in made:
            manager.add_component(c)
        return made

    def test_touch_draws_no_focus(self):
        runtime_globals.INPUT_MODE = runtime_globals.TOUCH_MODE
        for c in self.components():
            with self.subTest(component=type(c).__name__):
                self.assertEqual(self.render(c, False), self.render(c, True))

    def test_keyboard_and_mouse_still_draw_it(self):
        for mode in (runtime_globals.KEYBOARD_MODE, runtime_globals.MOUSE_MODE):
            runtime_globals.INPUT_MODE = mode
            button = self.components()[0]
            with self.subTest(mode=mode):
                self.assertNotEqual(self.render(button, False), self.render(button, True))


if __name__ == "__main__":
    unittest.main()
