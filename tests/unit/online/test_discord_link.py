"""Linking a Discord account: why it failed (owner, 2026-10-21).

The owner's link was refused with "Invalid or expired code" while the server
had no Discord relay at all: Omninet mounts /api/v1/discord only where a bot
token is set, and production had none, so FastAPI answered its own
{"detail": "Not Found"}. The relay answers an unknown code with {"error"}.
The game now tells the two apart ("Discord is offline").
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
if os.path.join(ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "src"))

import requests  # noqa: E402

from core import runtime_globals  # noqa: E402
from scenes.scene_connect import DiscordModule  # noqa: E402


class Answer:
    def __init__(self, status, body):
        self.status_code, self._body, self.text = status, body, str(body)

    def json(self):
        if self._body is None:
            raise ValueError("no JSON")
        return self._body


class DiscordLink(unittest.TestCase):
    def setUp(self):
        self.quiet = patch.object(runtime_globals, "game_console", SimpleNamespace(log=lambda *a: None))
        self.quiet.start()
        with patch.object(DiscordModule, "_load_data", lambda self: None):
            self.discord = DiscordModule()
        self.discord._save_data = lambda: None

    def tearDown(self):
        self.quiet.stop()

    def link(self, answer):
        with patch.object(requests, "post", side_effect=answer if isinstance(answer, Exception)
                          else (lambda *a, **k: answer)):
            return self.discord.login("AB12")

    def test_a_server_without_the_relay_is_offline(self):
        self.assertFalse(self.link(Answer(404, {"detail": "Not Found"})))
        self.assertEqual(self.discord.last_error, "offline")

    def test_an_unreachable_server_is_offline(self):
        self.assertFalse(self.link(requests.ConnectionError("down")))
        self.assertEqual(self.discord.last_error, "offline")
        self.assertFalse(self.link(Answer(502, None)))
        self.assertEqual(self.discord.last_error, "offline")

    def test_an_unknown_code_is_invalid(self):
        self.assertFalse(self.link(Answer(404, {"error": "Invalid code or not linked yet"})))
        self.assertEqual(self.discord.last_error, "invalid")

    def test_a_known_code_links(self):
        self.assertTrue(self.link(Answer(200, {"status": "success", "username": "sundeth",
                                               "tamer_name": "Sundeth", "user_id": "1"})))
        self.assertIsNone(self.discord.last_error)
        self.assertEqual(self.discord.get_account_name(), "sundeth")


if __name__ == "__main__":
    unittest.main()
