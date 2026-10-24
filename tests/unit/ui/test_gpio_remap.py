"""A GPIO button gives the action the current mapping names (UI-01, finding P-01).

The gpiozero Buttons are registered when `core.runtime_globals` is imported,
before the save loads, and each handler is made with the action its pin had
then (the default map). `reload_input_mappings` swaps in the saved map, so the
input manager must read a pin's action from that map when the event arrives,
not from the action the handler was made with. Off the Pi there is no
gpiozero: the events are built by hand as the handlers post them.
`tests/platform/pi/input_check.py --simulate --remap` checks the same on a
simulated gpiozero, and `input_check.sh` on the Pi itself.
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
from input import input_manager as im  # noqa: E402


class GpioRemapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((240, 240))

    def setUp(self):
        self.manager = runtime_globals.game_input
        for name in ("pin_map", "active_gpio_inputs", "just_pressed_gpio"):
            value = getattr(self.manager, name)
            self.addCleanup(setattr, self.manager, name, value)
            setattr(self.manager, name, type(value)(value))
        self.addCleanup(setattr, runtime_globals, "INPUT_MODE", runtime_globals.INPUT_MODE)

    def post(self, pin, action, pressed=True):
        """The event a handler made at start-up posts: its action is the old one."""
        kind = im.GPIO_PRESS_EVENT if pressed else im.GPIO_RELEASE_EVENT
        return self.manager.process_event(pygame.event.Event(kind, action=action, gpio_pin=pin))

    def test_a_remapped_pin_gives_its_new_action(self):
        self.manager.pin_map = {20: "A", 21: "B"}
        action, _ = self.post(21, "A")
        self.assertEqual(action, "B")
        self.assertIn("B", self.manager.active_gpio_inputs)
        self.assertNotIn("A", self.manager.active_gpio_inputs)

    def test_the_release_frees_the_remapped_action(self):
        self.manager.pin_map = {20: "A", 21: "B"}
        self.post(21, "A")
        self.post(21, "A", pressed=False)
        self.assertNotIn("B", self.manager.active_gpio_inputs)

    def test_an_unmapped_pin_keeps_the_action_it_was_made_with(self):
        self.manager.pin_map = {20: "A"}
        self.assertEqual(self.post(26, "START")[0], "START")


if __name__ == "__main__":
    unittest.main()
