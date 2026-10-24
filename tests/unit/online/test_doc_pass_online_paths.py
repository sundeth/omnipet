"""Online fixes from the 2026-10-22 documentation pass (findings 25 and 26).

25  the Arena tells a failed season fetch (no answer, a gateway error, a page
    it cannot read) from the server's 404 between seasons: both read
    "No active season".
26  the Discord link is kept in the base save folder (the app's storage on
    Android), not in a "save" folder relative to the working directory.
"""
import os
import shutil
import sys
import tempfile
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
if os.path.join(ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "src"))

from core import runtime_globals  # noqa: E402


class SeasonFetch(unittest.TestCase):
    def test_a_failed_fetch_is_not_the_404_between_seasons(self):
        from scenes.connect_views.arena_view import season_fetch_failed
        from services.omninet_service import UNREADABLE_ANSWER
        for message in ("Cannot connect to server", "Connection timeout", UNREADABLE_ANSWER,
                        "Omninet request failed, try again later", "Request failed: 502"):
            with self.subTest(message=message):
                self.assertTrue(season_fetch_failed(message))
        for message in ("No arena season is running", "Request failed: 404", "Not Found", None):
            with self.subTest(message=message):
                self.assertFalse(season_fetch_failed(message))


class DiscordSavePath(unittest.TestCase):
    def setUp(self):
        from scenes.scene_connect import DiscordModule
        self.tmp = tempfile.mkdtemp(prefix="discord_path_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for p in (patch.object(DiscordModule, "SAVE_PATH", None),
                  patch.object(runtime_globals, "game_console", SimpleNamespace(log=lambda *a: None))):
            p.start()
            self.addCleanup(p.stop)
        with patch.object(DiscordModule, "_load_data", lambda self: None):
            self.discord = DiscordModule()

    def test_on_android_the_link_is_in_the_app_storage(self):
        android = types.ModuleType("android")
        storage = types.ModuleType("android.storage")
        storage.app_storage_path = lambda: self.tmp
        android.storage = storage
        with patch.dict(sys.modules, {"android": android, "android.storage": storage}), \
                patch.object(runtime_globals, "IS_ANDROID", True):
            path = self.discord._get_save_path()
            self.assertEqual(os.path.normpath(path),
                             os.path.normpath(os.path.join(self.tmp, "save", "discord_data.json")))
            self.discord.linked_account, self.discord.account_name = True, "tamer"
            self.discord._save_data()
            self.assertTrue(os.path.isfile(path), "saved where it is read")

    def test_on_the_desktop_it_stays_beside_the_save(self):
        with patch.object(runtime_globals, "IS_ANDROID", False):
            self.assertEqual(os.path.normpath(self.discord._get_save_path()),
                             os.path.normpath(os.path.join("save", "discord_data.json")))

    def test_a_path_set_by_the_harness_wins(self):
        from scenes.scene_connect import DiscordModule
        target = os.path.join(self.tmp, "x", "discord_data.json")
        with patch.object(DiscordModule, "SAVE_PATH", target):
            self.assertEqual(self.discord._get_save_path(), target)
            self.discord._save_data()
            self.assertTrue(os.path.isfile(target))


if __name__ == "__main__":
    unittest.main()
