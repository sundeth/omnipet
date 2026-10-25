"""Switching Free Mode -> Progress Mode carries nothing across (online
finding 29, reported 2026-10-25).

Change Mode points the save folder at the Progress account (game_mode, then
player_id) before that account's save is loaded. The autosave in between
wrote the Free Mode save into the Progress folder, and loading the account
then gave it the Free save's modules as owned (a Free Mode download marks
the module bought there) and its pets. Driven through the real SceneSetup
switch with the game's own save guard (the harness forces saving on) and
Omninet mocked as a valid saved account.
"""
import os
import sys
import threading
import time
import unittest
from unittest.mock import patch

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
for path in (os.path.join(REPO_ROOT, "tests", "support"), os.path.join(REPO_ROOT, "src")):
    if path not in sys.path:
        sys.path.insert(0, path)

from core import game_globals  # noqa: E402

REAL_GUARD = game_globals._can_access_save_dir
MODULES = os.path.join(REPO_ROOT, "modules")
PID = "11111111-2222-3333-4444-555555555555"
MODULE = "DMC"


@unittest.skipUnless(os.path.exists(os.path.join(MODULES, MODULE, "module.json")), "modules/ is gitignored")
class ModeSwitchSave(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness import Env
        cls.env = Env("240x240")

    def setUp(self):
        self.env.reset()
        self.gg = gg = self.env.gg
        patcher = patch.object(gg, "_can_access_save_dir", REAL_GUARD)
        patcher.start()
        self.addCleanup(patcher.stop)
        # A Progress account already played on this device, owning nothing.
        gg.game_mode = gg.GAME_MODE_PROGRESS
        gg.save_game_mode_preference()
        gg.set_player_id(PID)
        gg.load()
        gg.save()
        # Back in Free Mode, as a fresh launch (no player id), a module
        # downloaded there: ShopModulesView._on_free_download.
        gg.game_mode = gg.GAME_MODE_FREE
        gg.save_game_mode_preference()
        gg.player_id = None
        gg.load()
        self.free_pets = len(gg.pet_list)
        gg.purchases.add_module("guid-of-dmc", MODULE)
        gg.save()

    def switch_to_progress(self, minutes_on_chooser):
        """Settings > Change Mode > Progression, then "Use <account>"."""
        from services.omninet_service import omninet_service
        from scenes.scene_setup import SceneSetup
        gg, env = self.gg, self.env
        gg.setup_game_mode = True
        with patch.object(omninet_service, "has_saved_credentials", return_value=True), \
                patch.object(omninet_service, "validate_device", return_value=(True, "ok", {})), \
                patch.object(omninet_service, "get_username", return_value="tester"), \
                patch.object(omninet_service, "get_player_id", return_value=PID), \
                patch.object(omninet_service, "is_logged_in", return_value=False):
            game = env.game("setup", SceneSetup)
            scene = game.scene
            scene._on_game_mode_selected(0)
            for thread in threading.enumerate():
                if thread is not threading.current_thread() and thread.daemon:
                    thread.join(timeout=5)
            env.frames(game, 1)
            self.assertEqual(scene.phase, "account_select")
            for _ in range(minutes_on_chooser):
                gg._last_save_time = time.time() - gg.AUTOSAVE_INTERVAL_SECONDS - 1
                env.frames(game, 1)
            scene._on_account_selected(0)
        self.assertTrue(gg.is_progress_mode())
        self.assertEqual(gg.player_id, PID)

    def test_the_free_save_never_reaches_the_account(self):
        from utils import navigation_utils
        self.assertGreater(self.free_pets, 0)
        for minutes in (0, 1, 3):
            with self.subTest(minutes_on_chooser=minutes):
                self.setUp()
                self.switch_to_progress(minutes)
                self.assertFalse(self.gg.purchases.owns_module_name(MODULE))
                self.assertFalse(navigation_utils.has_owned_modules())
                self.assertEqual(self.gg.pet_list, [])

    def test_boot_loads_the_account_its_validation_names(self):
        # Progress Mode whose player id the cache did not hold at start (or
        # the server refreshed): boot learns it and must load that save.
        from scenes.scene_boot import SceneBoot
        from services.omninet_service import omninet_service
        from utils import module_utils, navigation_utils
        gg = self.gg
        gg.game_mode = gg.GAME_MODE_PROGRESS
        gg.save_game_mode_preference()
        self.assertFalse(gg.holds_save_dir())
        boot = SceneBoot.__new__(SceneBoot)
        with patch.object(omninet_service, "validate_device", return_value=(True, "ok", {})), \
                patch.object(omninet_service, "get_player_id", return_value=PID), \
                patch.object(module_utils, "sync_account_data"), \
                patch.object(module_utils, "sync_owned_modules"), \
                patch.object(navigation_utils, "route_to_next_scene"):
            boot._validate_progress_mode()
        self.assertTrue(gg.holds_save_dir())
        self.assertEqual(gg.pet_list, [])
        self.assertFalse(gg.purchases.owns_module_name(MODULE))

    def test_a_save_goes_only_where_it_was_loaded_from(self):
        gg = self.gg
        free_dir = gg.get_save_dir()
        gg.game_mode = gg.GAME_MODE_PROGRESS
        gg.set_player_id(PID)
        before = sorted(os.listdir(gg.get_save_dir()))
        gg.save()
        self.assertEqual(sorted(os.listdir(gg.get_save_dir())), before, "refused until loaded")
        gg.load()
        gg.save()
        self.assertNotEqual(sorted(os.listdir(gg.get_save_dir())), before, "the account's own state saves")
        self.assertTrue(os.listdir(free_dir))


if __name__ == "__main__":
    unittest.main()
