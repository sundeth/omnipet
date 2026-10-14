# -*- coding: utf-8 -*-
"""ICX-11: everything the Digivice iC keeps survives saving and loading.

On the booted game (tests/support/harness.py: the real save code writing
into a throw-away folder under tmp/tests), an iC pet and the save are given
every piece of iC state:

    Fight Money                 game_globals.currency["IC"]["Fight Money"]
    the inventory               game_globals.inventory (Afro, Level Reverse)
    the worn accessory          GamePet.accessory (the Afro)
    the card collection         game_globals.card_collection (an iD Plate, shiny, and a Soul Plate)
    the DNA queue               GamePet.dna
    Connect Points              GamePet.connect_points
    open DigiShops              game_globals.shop_access: for good, and for 30 minutes
    the equipped weapon         game_globals.battle_effects (the Digi Cannon)
    Reliability                 GamePet.reliability

and the tests check that each comes back
  * from game_globals.save() / load();
  * through an Android offline run: save with the Android checkpoint, cold
    load two hours later and recover (services.android_progress /
    android_offline, as tests/unit/android/test_android_offline.py builds
    it), where the pet's care moves on (two hours of Reliability) and
    nothing else is lost;
  * across a Free/Progress game-mode switch (core.game_globals, the Free
    branch of scenes.scene_setup._on_game_mode_selected): each mode keeps its
    own save, and switching back to Free brings the iC state back.
A timed DigiShop closes once its time has passed, saved or not.

Checklist: ICX-11 (release-1.0.md). No network: the harness refuses it and
Progress Mode's player id is set by hand, as a login would.
"""
import copy
import os
import sys
import time
import unittest
from datetime import datetime
from unittest.mock import patch

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "support"))
MODULES = os.path.join(REPO_ROOT, "modules")

AFRO = "1c000040-0000-4000-8000-000000000040"
LEVEL_REVERSE = "1c000037-0000-4000-8000-000000000037"
DIGI_CANNON = "1c000009-0000-4000-8000-000000000009"


@unittest.skipUnless(os.path.exists(os.path.join(MODULES, "IC", "module.json")), "modules/ is gitignored")
class ICPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness import Env
        cls.env = Env("240x240")

    def setUp(self):
        self.env.reset()
        self.gg, self.rg = self.env.gg, self.env.rg
        self.ic = self.ic_pet()
        self.assertIsNotNone(self.ic, "the harness party has an iC pet")

    def ic_pet(self):
        return next((p for p in self.gg.pet_list if p.module == "IC"), None)

    # ------------------------------------------------------------ the state
    def give_ic_state(self):
        from utils import card_utils, connect_points, currency_utils, event_utils, item_effects
        from utils.inventory_utils import add_to_inventory, get_item_by_id
        pet = self.ic
        currency_utils.add_currency("IC", "Fight Money", 1234)
        add_to_inventory(AFRO, 1)
        add_to_inventory(LEVEL_REVERSE, 3)
        self.assertTrue(item_effects.toggle_accessory(pet, get_item_by_id(AFRO)))
        cards = card_utils.get_module_cards("IC")["cards"]
        plate = next(c["id"] for c in cards if c.get("type") != "Soul Plate")
        soul = next(c["id"] for c in cards if c.get("type") == "Soul Plate")
        card_utils.add_card_copy("IC", plate, shiny=True)
        card_utils.add_card_copy("IC", plate, physical=True)
        card_utils.add_card_copy("IC", soul)
        pet.add_dna("Dragon", 3)
        pet.add_dna("Beast", 1)
        for _ in range(7):
            connect_points.award(pet, True)
        event_utils.grant_shop_access("IC", "DigiShop 1")             # for good
        event_utils.grant_shop_access("IC", "DigiShop 2", minutes=30)  # timed
        cannon = get_item_by_id(DIGI_CANNON)
        item_effects.add_battle_boost(cannon, cannon.status, cannon.amount, cannon.boost_time)
        pet.reliability = 22
        return dict(
            currency=copy.deepcopy(self.gg.currency.get("IC")),
            inventory={AFRO: 1, LEVEL_REVERSE: 3},
            cards=copy.deepcopy(self.gg.card_collection.get("IC")),
            shop_access=copy.deepcopy(self.gg.shop_access.get("IC")),
            weapon=copy.deepcopy(self.gg.battle_effects.get("attack")),
            accessory=AFRO, dna=["Dragon"] * 3 + ["Beast"], connect_points=7, reliability=22)

    def assert_ic_state(self, expected, reliability=None):
        from utils import accessory_utils, currency_utils, event_utils
        pet = self.ic_pet()
        self.assertIsNotNone(pet, "the iC pet was loaded")
        self.assertEqual(currency_utils.get_balance("IC", "Fight Money"), 1234)
        self.assertEqual(self.gg.currency.get("IC"), expected["currency"])
        self.assertEqual({k: self.gg.inventory.get(k) for k in expected["inventory"]}, expected["inventory"])
        self.assertEqual(self.gg.card_collection.get("IC"), expected["cards"])
        self.assertEqual(self.gg.shop_access.get("IC"), expected["shop_access"])
        self.assertTrue(event_utils.shop_access_open("IC", "DigiShop 1"))
        self.assertTrue(event_utils.shop_access_open("IC", "DigiShop 2"))
        self.assertEqual(self.gg.battle_effects.get("attack"), expected["weapon"])
        self.assertEqual(expected["weapon"]["item_id"], DIGI_CANNON)
        self.assertEqual(pet.accessory, expected["accessory"])
        self.assertEqual(accessory_utils.worn(pet).name, "Afro")
        self.assertEqual(pet.dna, expected["dna"])
        self.assertEqual(pet.leading_dna(), "Dragon")
        self.assertEqual(pet.connect_points, expected["connect_points"])
        self.assertEqual(pet.reliability, expected["reliability"] if reliability is None else reliability)

    def forget_everything(self):
        """What a fresh process starts from before load()."""
        gg = self.gg
        gg.pet_list, gg.currency, gg.inventory = [], {}, {}
        gg.card_collection, gg.shop_access, gg.battle_effects = {}, {}, {}

    def age_saves(self):
        """Move every save already written an hour into the past.

        load() takes the save with the newest modification time, and on a
        file system that keeps it to two seconds (this exFAT drive) two
        saves a test writes in a row tie and the older can win: a real bug,
        shown by test_the_newer_of_two_saves_in_the_same_second_loads and
        listed in tests/findings/ic.md. Called before each step that saves
        once, so the save that step writes is the newest, as it would be
        minutes apart in play."""
        for folder, _dirs, files in os.walk(self.env.save_root):
            for name in files:
                if name.startswith("save_data_"):
                    path = os.path.join(folder, name)
                    mtime = os.path.getmtime(path) - 3600
                    os.utime(path, (mtime, mtime))

    def save(self):
        self.age_saves()
        self.assertTrue(self.gg.save())

    # ------------------------------------------------------------ save/load
    def test_everything_survives_save_and_load(self):
        expected = self.give_ic_state()
        self.save()
        self.forget_everything()
        self.gg.load()
        self.assert_ic_state(expected)
        from utils import currency_utils
        names = [s["name"] for s in currency_utils.available_shops(self.rg.game_modules["IC"])]
        self.assertEqual(names, ["Item Shop", "Weapon Shop", "Rare Shop", "DigiShop 1", "DigiShop 2"])

    def test_a_second_round_trip_changes_nothing(self):
        expected = self.give_ic_state()
        for _ in range(2):
            self.save()
            self.forget_everything()
            self.gg.load()
        self.assert_ic_state(expected)

    # Bug: load() picks the save with the newest mtime and breaks a tie by
    # directory order, so of two saves within the file system's mtime
    # resolution (2 s on FAT/exFAT) the older can load
    # (core/game_globals.py load and get_latest_save_file); see
    # tests/findings/ic.md, 2 "Two saves in the same second".
    # Fixed 2026-10-13; kept as a regression test.
    def test_the_newer_of_two_saves_in_the_same_second_loads(self):
        from utils import currency_utils
        self.age_saves()
        currency_utils.add_currency("IC", "Fight Money", 100)
        self.assertTrue(self.gg.save())
        currency_utils.add_currency("IC", "Fight Money", 200)     # a purchase's worth later
        self.assertTrue(self.gg.save())
        folder = self.gg.get_save_dir()
        stamp = time.time()
        for name in os.listdir(folder):
            if name.startswith("save_data_") and os.path.getmtime(os.path.join(folder, name)) > stamp - 600:
                os.utime(os.path.join(folder, name), (stamp, stamp))   # one tick of a 2 s clock
        self.forget_everything()
        listdir = os.listdir
        # Names in ascending order, as NTFS and exFAT list them, on every
        # file system (ext4's hash order would make the result a coin toss).
        with patch("os.listdir", side_effect=lambda path=".": sorted(listdir(path))):
            self.gg.load()
        self.assertEqual(currency_utils.get_balance("IC", "Fight Money"), 300)

    def test_a_timed_digishop_closes_once_its_time_has_passed(self):
        from utils import currency_utils, event_utils
        self.give_ic_state()
        self.save()
        self.forget_everything()
        self.gg.load()
        later = time.time() + 31 * 60
        with patch("utils.event_utils.time.time", return_value=later):
            self.assertFalse(event_utils.shop_access_open("IC", "DigiShop 2"))
            self.assertTrue(event_utils.shop_access_open("IC", "DigiShop 1"), "for good")
            names = [s["name"] for s in currency_utils.available_shops(self.rg.game_modules["IC"])]
        self.assertNotIn("DigiShop 2", names)

    # ------------------------------------------------------------ Android
    def test_everything_survives_an_android_offline_run(self):
        """Saved on Android, closed for two hours, reopened: the offline run
        moves the pet's care on and keeps the rest of the iC state."""
        from services import android_progress
        from models.game_pet import GamePet
        expected = self.give_ic_state()
        at = datetime(2026, 9, 12, 12).timestamp()          # noon: nobody is asleep
        clock = {"wall": at}
        patches = [
            patch.object(self.rg, "IS_ANDROID", True),
            patch.object(self.gg, "android_offline", None),
            patch.object(android_progress, "native", return_value=None),
            patch.object(android_progress, "after_save"),
            patch.object(android_progress, "flush_effects"),
            patch.object(android_progress, "_checkpoint", None),
            patch.object(android_progress, "_prepared", None),
            patch.object(android_progress, "_recovering", False),
            patch.object(android_progress, "_background", False),
            patch.object(android_progress, "_game_instance", None),
            patch.object(android_progress, "clock_record", side_effect=lambda: dict(clock)),
            patch.object(GamePet, "should_sleep", return_value=False),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.save()
        self.assertIsNotNone(self.gg.android_offline, "the checkpoint went into the save")
        self.forget_everything()
        self.gg.load()
        clock["wall"] = at + 2 * 3600
        self.age_saves()
        android_progress.on_load()                          # recovers and saves
        # Two hours of the iC's hourly -1; the hunger it lost is no call yet.
        self.assert_ic_state(expected, reliability=20)
        pet = self.ic_pet()
        self.assertEqual(pet.hunger, 2, "Agumon loses a heart an hour")
        # The recovered state was saved: a later cold load finds it again.
        self.forget_everything()
        with patch.object(android_progress, "on_load"):
            self.gg.load()
        self.assert_ic_state(expected, reliability=20)

    # ------------------------------------------------------------ mode switch
    def switch_mode(self, mode, player=None):
        """What choosing a mode in Settings does, offline: the mode and its
        save folder, then the active save loaded keeping the display
        (scenes.scene_setup._on_game_mode_selected, the Free branch; a
        Progress login sets the player id the same way)."""
        from utils import display_utils
        gg = self.gg
        gg.game_mode = mode
        if player:
            gg.set_player_id(player)
        gg.save_game_mode_preference()
        gg.migrate_legacy_saves()
        self.age_saves()
        display_utils.load_preserving_display()            # loads, then saves

    def test_each_mode_keeps_its_own_ic_state(self):
        gg = self.gg
        expected = self.give_ic_state()
        self.save()
        free_dir = gg.get_save_dir()
        self.switch_mode(gg.GAME_MODE_PROGRESS, player="ic-test-player")
        self.assertNotEqual(gg.get_save_dir(), free_dir)
        self.assertTrue(gg.get_save_dir().startswith(self.env.save_root), "still in the test's folder")
        self.assertEqual((gg.pet_list, gg.currency.get("IC"), gg.shop_access.get("IC")), ([], None, None),
                         "a new Progress profile starts empty")
        from utils import currency_utils
        currency_utils.add_currency("IC", "Fight Money", 5)
        self.save()
        self.switch_mode(gg.GAME_MODE_FREE)
        self.assertEqual(gg.get_save_dir(), free_dir)
        self.assert_ic_state(expected)
        self.switch_mode(gg.GAME_MODE_PROGRESS, player="ic-test-player")
        self.assertEqual(currency_utils.get_balance("IC", "Fight Money"), 5, "Progress kept its own")


if __name__ == "__main__":
    unittest.main()
