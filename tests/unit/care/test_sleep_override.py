"""Sleep windows by day and the player's Settings override.

DW1's species keep World's sleep patterns on the real clock, some by day
(07:00-16:00). should_sleep() handles a window within one day as well as one
across midnight; and the Settings override (game_globals.configuration's
sleep_time / wake_time) replaces every pet's times. The override used to be
read from game_globals.sleep_time, which nothing set, so it never applied
(fixed 2026-10-13).
"""
import datetime as dt
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'src'))
from core import game_globals, runtime_globals  # noqa: E402
import models.game_pet as game_pet_module  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_android_offline import module, pet  # noqa: E402


def at(hour, minute=0):
    class Fixed(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return dt.datetime(2026, 10, 13, hour, minute)
    return patch.object(game_pet_module, 'datetime', Fixed)


class SleepWindowTests(unittest.TestCase):
    def setUp(self):
        p = patch.object(runtime_globals, 'game_console', SimpleNamespace(log=lambda *_: None))
        p.start()
        self.addCleanup(p.stop)
        self.cfg = SimpleNamespace(sleep_time=None, wake_time=None)
        p = patch.object(game_globals, 'configuration', self.cfg)
        p.start()
        self.addCleanup(p.stop)

    def daytime_sleeper(self):
        return pet(module(), sleeps="07:00", wakes="16:00")

    def test_a_window_within_the_day(self):
        p = self.daytime_sleeper()
        for hour, asleep in ((6, False), (7, True), (12, True), (15, True), (16, False), (23, False)):
            with at(hour):
                self.assertEqual(p.should_sleep(), asleep, hour)

    def test_a_window_across_midnight(self):
        p = pet(module(), sleeps="19:00", wakes="04:00")
        for hour, asleep in ((18, False), (19, True), (0, True), (3, True), (4, False), (12, False)):
            with at(hour):
                self.assertEqual(p.should_sleep(), asleep, hour)

    def test_the_settings_override_replaces_the_species_times(self):
        p = self.daytime_sleeper()
        self.cfg.sleep_time, self.cfg.wake_time = dt.time(22, 0), dt.time(7, 0)
        with at(12):
            self.assertFalse(p.should_sleep())
        with at(23):
            self.assertTrue(p.should_sleep())

    def test_the_override_needs_both_times(self):
        p = self.daytime_sleeper()
        self.cfg.sleep_time = dt.time(22, 0)
        with at(12):
            self.assertTrue(p.should_sleep())


if __name__ == '__main__':
    unittest.main()
