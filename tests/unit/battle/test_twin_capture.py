"""TWIN capture: answering a Digimon Twin with the known code and recording it."""

import os
import re
import sys
import time
import unittest
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

# These tests live under utilities/claude/tests/, three folders below
# the repo root, so they are not carried in the git repository.
REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SRC = os.path.join(REPO_ROOT, "src")
for path in (SRC, REPO_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

import pygame  # noqa: E402

from core import runtime_globals  # noqa: E402
from battle.sim import protocol_constants  # noqa: E402
from battle.dcom.dcom_capture import DComCapture, digit_sum  # noqa: E402

TWIN = protocol_constants.TWIN

#: A made-up Twin side, and the replies the code's operators make to it:
#: P2 echoes digit 1 and flips digit 2 by 2 (B -> 9), and P4's check digit
#: brings our P1-P4 to 4 mod 16 (33 + c + 15 = 4 mod 16, so c = 4).
THEIRS = ["1A27", "3B47", "0007", "5C0F"] + ["0000"] * 16
OURS = ["0007", "3907", "0007", "400F"] + ["0000"] * 16


def transcript(theirs, ours):
    """An adapter line for an exchange the device opened."""
    return " ".join(f"r:{t} s:{o}" for t, o in zip(theirs, ours)) + " t"


def setUpModule():
    os.chdir(REPO_ROOT)
    pygame.init()
    pygame.display.set_mode((240, 240))
    # Fonts cached before another module's pygame.quit() are dangling, and
    # rendering through one is an access violation (see test_rpm).
    from utils import asset_utils
    asset_utils._font_cache.clear()


def tearDownModule():
    from utils import asset_utils
    asset_utils._font_cache.clear()
    pygame.quit()


class ConstantsTests(unittest.TestCase):
    def test_the_code_is_the_shipped_punchbag(self):
        with open(os.path.join(os.path.dirname(SRC), "tests", "support", "data", "digiroms.txt"), encoding="utf-8") as f:
            text = f.read()
        shipped = re.search(r"Twin battle/event\s*\n(?:\s*#.*\n)*\s*(\S+)", text).group(1)
        self.assertEqual(TWIN.CAPTURE_ROM, shipped)

    def test_the_code_has_the_twins_packet_count(self):
        self.assertTrue(TWIN.CAPTURE_ROM.startswith(TWIN.DCOM_OP + "2-"))
        self.assertEqual(len(TWIN.CAPTURE_ROM.split("-")) - 1, TWIN.PACKET_COUNT)

    def test_twin_is_recorded_not_battled(self):
        self.assertIs(protocol_constants.capture_constants("TWIN"), TWIN)
        self.assertNotIn("TWIN", protocol_constants.BATTLE_FORMATS)
        self.assertIsNone(protocol_constants.get_constants("TWIN"))
        self.assertIsNone(protocol_constants.capture_constants("DMOG"))

    def test_the_made_up_replies_follow_the_codes_operators(self):
        self.assertEqual(digit_sum(OURS[:TWIN.CAPTURE_CHECK_PACKETS]),
                         TWIN.CAPTURE_CHECK_REMAINDER)


class RecordTests(unittest.TestCase):
    def setUp(self):
        self.capture = DComCapture("TWIN")

    def test_a_whole_exchange_is_kept_and_laid_out(self):
        report = self.capture.record(transcript(THEIRS, OURS))
        self.assertEqual(self.capture.captures, [(OURS, THEIRS)])
        text = "\n".join(report)
        self.assertIn("TWIN EXCHANGE #1: 20 of 20 packets", text)
        self.assertIn("P4  5C0F  body 5C0  EOL F  | ours 400F", text)
        self.assertIn("all zero: P5-P20", text)
        self.assertIn("ours 4 (the code asks for 4)", text)
        self.assertIn("P2 echo: TWIN 3B47 -> ours 3907, XOR per digit 0240", text)

    def test_zero_packets_are_data(self):
        self.capture.record(transcript(THEIRS, OURS))
        self.assertEqual(len(self.capture.captures[0][1]), 20)

    def test_a_short_exchange_is_kept_too(self):
        report = self.capture.record(transcript(THEIRS[:3], OURS[:3]))
        self.assertIn("3 of 20 packets", report[0])
        self.assertEqual(len(self.capture.captures), 1)

    def test_a_line_without_packets_is_not_an_exchange(self):
        self.assertEqual(self.capture.record("t"), [])
        self.assertEqual(self.capture.captures, [])

    def test_the_next_exchange_shows_what_changed(self):
        self.capture.record(transcript(THEIRS, OURS))
        changed = ["1A27", "3D47"] + THEIRS[2:]
        report = self.capture.record(transcript(changed, OURS))
        self.assertIn("since #1: P2 3B47->3D47", report[-1])
        report = self.capture.record(transcript(changed, OURS))
        self.assertIn("since #2: identical", report[-1])

    def test_it_answers_with_the_code_as_written(self):
        self.assertEqual(self.capture.cable_command(), TWIN.CAPTURE_ROM)
        self.assertEqual(self.capture.expected_packet_count, 20)
        self.assertEqual(self.capture.minigame, "None")
        self.assertFalse(self.capture.goes_first)

    def test_only_capture_lines_can_be_recorded(self):
        with self.assertRaises(ValueError):
            DComCapture("DMOG")


class FakeController:
    """An adapter that has said what it is and remembers what it was sent."""

    def __init__(self, info="wificom & pico-terminal"):
        self.device_info = info
        self.sent = []
        self.disconnected = False

    def _send_raw(self, data):
        self.sent.append(data)

    def disconnect(self):
        self.disconnected = True


class ViewTests(unittest.TestCase):
    def view(self, info="wificom & pico-terminal"):
        from scenes.connect_views.dcom_view import DComView
        from ui.ui_manager import UIManager

        class Pet:
            module = "TWIN"
            name = "Gaomon"

        with mock.patch.object(DComView, "_start_dcom_scan"):
            view = DComView(UIManager("RED"), lambda *a, **k: None,
                            selected_pets=[Pet()])
        view.dcom_controller = FakeController(info)
        self.addCleanup(view.cleanup)
        return view

    def test_choosing_twin_answers_with_the_code(self):
        view = self.view()
        view._on_protocol_select("TWIN")
        self.assertIsInstance(view.simulator, DComCapture)
        self.assertEqual(view.phase, "communicating")
        self.assertEqual(view.dcom_controller.sent, [TWIN.CAPTURE_ROM + "\r"])

    def test_every_exchange_is_recorded_and_the_window_stays_open(self):
        view = self.view()
        view._on_protocol_select("TWIN")
        view.comm_start_time = time.time() - 50
        self.assertFalse(view._consume_line(transcript(THEIRS, OURS)))
        self.assertFalse(view._consume_line(transcript(THEIRS, OURS)))
        self.assertEqual(len(view.simulator.captures), 2)
        self.assertGreater(view.comm_start_time, time.time() - 5)
        view._update_dcom_communication()
        self.assertTrue(view.communicating)
        self.assertIn("Recorded 2", view.status_label.text)

    def test_the_window_closes_with_a_count(self):
        view = self.view()
        view._on_protocol_select("TWIN")
        view._consume_line(transcript(THEIRS, OURS))
        view.comm_start_time = time.time() - 61
        view._update_dcom_communication()
        self.assertFalse(view.communicating)
        self.assertIn("Recorded 1 exchange", view.status_label.text)
        self.assertTrue(view.dcom_controller.disconnected)

    def test_a_prong_adapter_is_warned_and_its_refusal_named(self):
        view = self.view(info="dmcomm-original 4")
        view._on_protocol_select("TWIN")
        self.assertIn("infrared", view._transport_warning)
        view._consume_line("(paused)")
        self.assertIn("infrared firmware", view._connection_diagnosis())


if __name__ == "__main__":
    unittest.main()
