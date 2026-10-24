"""Behavioral checks for the video-informed approximation, not firmware parity."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from ui.minigames.rpm_rhythm import CHARGE_MS, RPMRhythm, rpm_for_interval


def play(times, target=70, until=None, frames=()):
    charge = RPMRhythm(target)
    events = [(t, 0) for t in times] + [(t, 1) for t in frames]
    for at, is_frame in sorted(events):
        (charge.advance if is_frame else charge.press)(at)
    if until is not None:
        charge.advance(until)
    return charge


class RhythmTests(unittest.TestCase):
    def test_same_count_and_final_rpm_can_have_different_bars(self):
        steady = list(range(100, 5501, 300))
        uneven = [100]
        for gap in [100, 500] * 8 + [300, 300]:
            uneven.append(uneven[-1] + gap)
        a, b = play(steady), play(uneven)
        self.assertEqual(len(a.press_times), len(b.press_times))
        self.assertEqual(a.elapsed_ms, b.elapsed_ms)
        self.assertEqual(a.rpm, b.rpm)
        self.assertEqual(a.bars, 10)
        self.assertLess(b.bars, a.bars)

    def test_faster_is_not_automatically_better(self):
        # Corresponds to the qualitative IC 2 contrast: ~70 RPM/10 bars
        # versus ~90 RPM/6 bars. These are synthetic regular inputs, not
        # falsely precise button timestamps extracted from the recording.
        steady = play(range(100, 5901, 300))
        fast = play(range(100, 5901, 200))
        self.assertGreater(fast.rpm, steady.rpm)
        self.assertGreater(len(fast.press_times), len(steady.press_times))
        self.assertEqual(steady.bars, 10)
        self.assertLess(fast.bars, steady.bars)

    def test_small_cadence_variations_can_sustain_maximum_charge(self):
        # IC 2 try 2 maintains a full meter while the display alternates
        # around 65-70. Matching exactly one interval must not be required.
        times = [100]
        for gap in [300, 325] * 9:
            times.append(times[-1] + gap)
        charge = play(times)
        self.assertEqual(charge.bars, 10)

    def test_mistiming_first_stalls_then_loses_a_bar(self):
        charge = play(range(100, 1901, 300))
        before = charge.bars
        charge.press(2000)
        self.assertEqual(charge.bars, before)
        charge.press(2100)
        self.assertEqual(charge.bars, before - 1)

    def test_pause_drains_the_meter_without_another_press(self):
        charge = play(range(100, 3101, 300))
        self.assertEqual(charge.bars, 10)
        charge.advance(3470)
        self.assertEqual(charge.bars, 10)  # first missed beat stalls
        charge.advance(3770)
        self.assertEqual(charge.bars, 9)
        charge.advance(CHARGE_MS)
        self.assertLess(charge.bars, 9)
        self.assertEqual(charge.rpm, 0)

    def test_no_input_or_one_press_does_not_award_charge(self):
        for times in ([], [10], [5900]):
            charge = play(times, until=CHARGE_MS)
            self.assertEqual((charge.rpm, charge.bars), (0, 0))

    def test_slow_spaced_presses_can_finish_on_zero(self):
        charge = play(range(100, 5701, 700), until=CHARGE_MS)
        self.assertEqual((charge.rpm, charge.bars), (0, 0))

    def test_readout_is_recent_not_a_whole_round_average(self):
        charge = play([100, 500, 900])
        self.assertEqual(charge.rpm, 50)
        charge.press(1100)
        self.assertEqual(charge.rpm, 90)
        self.assertNotEqual(charge.bars, 10)

    def test_readout_has_observed_steps_and_two_digit_cap(self):
        allowed = set(range(0, 100, 5)) | {99}
        for interval in range(60, 1000):
            self.assertIn(rpm_for_interval(interval), allowed)
        self.assertEqual(rpm_for_interval(100), 99)
        self.assertEqual(rpm_for_interval(700), 0)

    def test_targets_change_bars_without_changing_displayed_rpm(self):
        a, b = (play(range(100, 5801, 300), target) for target in (70, 85))
        self.assertEqual(a.rpm, b.rpm)
        self.assertGreater(a.bars, b.bars)
        self.assertEqual(a.bars_for_target(85), b.bars)

    def test_frame_rate_and_missed_frames_do_not_change_results(self):
        times = [100, 400, 700, 1000, 1700, 1900, 2200, 2700, 3100, 5900]
        sparse = play(times, until=CHARGE_MS)
        for period in (8, 16, 33, 100):
            dense = play(times, until=CHARGE_MS, frames=range(0, CHARGE_MS, period))
            self.assertEqual((dense.rpm, dense.bars, dense.misses),
                             (sparse.rpm, sparse.bars, sparse.misses))

    def test_deadline_settles_and_freezes_even_on_a_late_frame(self):
        times = list(range(100, 5501, 300))
        timely = play(times, until=CHARGE_MS)
        late = play(times, until=CHARGE_MS + 2500)
        result = late.rpm, late.bars, tuple(late.press_times)
        self.assertEqual((late.rpm, late.bars), (timely.rpm, timely.bars))
        for at in (CHARGE_MS, CHARGE_MS + 3000, CHARGE_MS + 10000):
            self.assertFalse(late.press(at))
            late.advance(at)
            self.assertEqual((late.rpm, late.bars, tuple(late.press_times)), result)

    def test_duplicate_events_do_not_create_a_fake_rhythm(self):
        charge = RPMRhythm(70)
        self.assertTrue(charge.press(100))
        self.assertFalse(charge.press(100))
        self.assertFalse(charge.press(110))
        self.assertTrue(charge.press(400))
        self.assertEqual(charge.press_times, [100, 400])
        self.assertEqual(charge.rpm, 70)

    def test_history_replay_includes_pauses_and_the_deadline(self):
        times = [100, 350, 600, 850, 1100, 2000, 2250, 2500, 5000, 5250]
        primary = play(times, 70, until=CHARGE_MS)
        for target in (50, 55, 70, 85):
            separate = play(times, target, until=CHARGE_MS)
            self.assertEqual(primary.bars_for_target(target), separate.bars)


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pygame
        from utils import asset_utils
        pygame.init()
        pygame.display.set_mode((240, 240))
        asset_utils._font_cache.clear()

    @classmethod
    def tearDownClass(cls):
        import pygame
        from utils import asset_utils
        asset_utils._font_cache.clear()
        pygame.quit()

    def game(self, target=70):
        import pygame
        from types import SimpleNamespace
        from ui.ui_manager import UIManager
        from ui.minigames.rpm import RPM
        with mock.patch.object(pygame.time, "get_ticks", return_value=0):
            game = RPM(UIManager("GREEN"), SimpleNamespace(rpm=target))
            game.start()
        return game

    def tap(self, game, at):
        import pygame
        with mock.patch.object(pygame.time, "get_ticks", return_value=at):
            game.handle_event(("A", None))

    def test_session_manual_finish_commits_latest_press(self):
        import pygame
        from ui.minigames.minigame_session import MinigameSession
        game = self.game()
        session = MinigameSession("RPM", game.ui_manager, game.pet)
        session.phase, session.instance = "charge", game
        for at in range(100, 1901, 300):
            self.tap(game, at)
        self.assertEqual(session.strength, 0)  # no session.update yet
        with mock.patch.object(pygame.time, "get_ticks", return_value=1900):
            session.handle_event(("B", None))
        self.assertTrue(session.finished)
        self.assertEqual(session.strength, game.get_bars())
        self.assertGreater(session.strength, 0)
        self.assertEqual(session.rpm, game.get_rpm())

    def test_training_updates_and_scores_each_pets_history(self):
        import pygame
        from training.rpm_training import RPMTraining

        class Pet:
            def __init__(self, rpm):
                self.rpm = rpm

        pets = [Pet(70), Pet(85)]
        training = RPMTraining.__new__(RPMTraining)
        training.pets, training.count_bar = pets, self.game()
        training.phase, training.frame_counter = "charge", 0
        training.prepare_attack = mock.Mock()
        for at in range(100, 5901, 300):
            self.tap(training.count_bar, at)
            with mock.patch.object(pygame.time, "get_ticks", return_value=at):
                training.update_charge_phase()
        self.assertEqual(training.phase, "charge")
        with mock.patch.object(pygame.time, "get_ticks", return_value=10000), \
                mock.patch("training.rpm_training.get_ic_pattern", return_value=[4] * 5) as lookup:
            training.update_charge_phase()
        self.assertEqual(training.phase, "wait_attack")
        training.prepare_attack.assert_called_once()
        self.assertEqual([c.args[0] for c in lookup.call_args_list],
                         [training.count_bar.get_bars(p.rpm) for p in pets])
        self.assertNotEqual(lookup.call_args_list[0], lookup.call_args_list[1])

    def test_label_cache_changes_when_bars_change_at_the_same_rpm(self):
        import pygame
        from ui.minigames.rpm import label_color
        game = self.game()
        surface = pygame.Surface((240, 240))
        for at in (100, 400):
            self.tap(game, at)
        game.draw(surface)
        old_key, old_image = game._label_cache
        self.tap(game, 700)
        game.draw(surface)
        key, img = game._label_cache
        self.assertEqual(key[0], old_key[0])
        self.assertNotEqual(key[1], old_key[1])
        self.assertIsNot(img, old_image)
        self.assertNotEqual(label_color(key[1]), label_color(old_key[1]))

    def test_restart_clears_the_previous_rhythm(self):
        import pygame
        game = self.game()
        for at in range(100, 1901, 300):
            self.tap(game, at)
        with mock.patch.object(pygame.time, "get_ticks", return_value=3000):
            game.start()
        self.assertEqual((game.get_bars(), game.get_rpm(), game.get_presses()), (0, 0, 0))
        self.assertEqual(game.rhythm.press_times, [])


if __name__ == "__main__":
    unittest.main()
