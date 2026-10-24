"""Every press and tap answers with a sound (UI-06, owner rule 2026-10-13).

`VirtualPetGame.dispatch_input` hands each input action to the scene; when the
scene played nothing, it answers for it: "menu" if the press changed the screen
(scene, view, phase, focus, selection) and "cancel" if it did nothing. A scene
running gameplay of its own (minigame, battle) opts out with
`plays_own_input_sounds()`. Pointer motion, scrolling and drags are not presses.
The menu crawl (tests/release/menu_crawl.py) checks the same on every screen.
"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from core import runtime_globals  # noqa: E402
from vpet import VirtualPetGame  # noqa: E402


class Scene:
    """A scene whose handler does what the test tells it to."""

    def __init__(self, effect=None, exempt=False):
        self.phase = "menu"
        self.effect = effect
        self.exempt = exempt

    def plays_own_input_sounds(self):
        return self.exempt

    def handle_event(self, event):
        if self.effect == "switch":
            self.phase = "other"
        elif self.effect == "own sound":
            runtime_globals.game_sound.play("menu")
        return False


class InputSoundTests(unittest.TestCase):
    def setUp(self):
        self.played = []
        sound = runtime_globals.game_sound
        original = sound.play

        def record(name):
            self.played.append(name)
            sound.play_requests += 1
        sound.play = record
        self.addCleanup(setattr, sound, "play", original)
        self.game = VirtualPetGame.__new__(VirtualPetGame)

    def send(self, scene, event=("A", None)):
        self.game.scene = scene
        self.game.dispatch_input(event)
        return self.played

    def test_a_press_that_does_nothing_plays_cancel(self):
        self.assertEqual(self.send(Scene()), ["cancel"])

    def test_a_press_that_switches_something_plays_menu(self):
        self.assertEqual(self.send(Scene("switch")), ["menu"])

    def test_a_scene_that_answered_is_not_answered_twice(self):
        self.assertEqual(self.send(Scene("own sound")), ["menu"])

    def test_every_button_and_tap_is_answered(self):
        for event in (("UP", None), ("DOWN", None), ("LEFT", None), ("RIGHT", None), ("B", None),
                      ("START", None), ("SELECT", None), ("LCLICK", {"pos": (1, 1)})):
            with self.subTest(event=event[0]):
                self.played.clear()
                self.assertEqual(self.send(Scene(), event), ["cancel"])

    def test_pointer_motion_scroll_and_drags_are_not_presses(self):
        for event in (("MOUSE_MOTION", {"pos": (1, 1)}), ("SCROLL", {"direction": "UP"}),
                      ("DRAG_MOTION", {"pos": (1, 1)}), ("F12", None)):
            with self.subTest(event=event[0]):
                self.assertEqual(self.send(Scene(), event), [])

    def test_a_scene_in_play_keeps_its_own_sounds(self):
        self.assertEqual(self.send(Scene(exempt=True)), [])


if __name__ == "__main__":
    unittest.main()
