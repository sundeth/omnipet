# -*- coding: utf-8 -*-
"""Release gates of the battle modes, checked without booting the game.

Checklist BAT-03 (each module's adventure is fought on a protocol the game
knows), BAT-04 (every mode can be played by the headless drivers in
tests/game/battle), BAT-06 (unfinished protocols are held back: TWIN for
1.0) and BAT-07 (WiFi-Com battles are held back for 1.0).

* every release module declares a battle format or none ("None" plays the
  DMX ruleset); an unknown name would silently fall through the pattern
  lookup;
* every battle format maps to a versus protocol the simulator runs, and the
  menus offer nothing that is not a battle format (TWIN, BAT-F8);
* a species' ``injury_probability`` reaches the pet (BAT-F3);
* every charge minigame a release module or a format plays has a press in
  the game tests' player (tests/game/battle/battle_flow.CHARGE_PRESS), so a
  new minigame cannot leave those tests waiting on a charge nobody plays.

Known bugs are expectedFailure (tests/findings/battle.md).
"""
import json
import os
import sys
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
for path in (os.path.join(REPO_ROOT, "src"), REPO_ROOT, os.path.join(REPO_ROOT, "tests", "game", "battle")):
    if path not in sys.path:
        sys.path.insert(0, path)
MODULES = os.path.join(REPO_ROOT, "modules")

import battle_flow as bf  # noqa: E402  (tests/game/battle; imports nothing of the game at load)
from battle.sim import protocol_constants as pc  # noqa: E402


def module_json(name):
    path = os.path.join(MODULES, name, "module.json")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8-sig") as fh:
        return json.load(fh)


def release_modules():
    return [m for m in bf.release_modules() if m not in bf.SKIP_MODULES and module_json(m)]


class ProtocolGates(unittest.TestCase):
    @unittest.skipUnless(os.path.isdir(MODULES), "modules folder not present")
    def test_every_release_module_declares_a_known_battle_format(self):
        """battle_protocol is a battle format, a legacy spelling of one, or None."""
        for name in release_modules():
            declared = module_json(name).get("battle_protocol") or "None"
            with self.subTest(module=name, battle_protocol=declared):
                self.assertTrue(declared == "None" or pc.canonical_format(declared) in pc.BATTLE_FORMATS,
                                f"{name} declares {declared!r}, which is no battle format")

    def test_every_battle_format_has_a_versus_protocol(self):
        """versus_protocol never falls back to DM20 for a format that is not DM20's."""
        from battle.sim.battle_simulator import BattleSimulator
        default = pc.versus_protocol("no such format")
        for battle_format in pc.BATTLE_FORMATS:
            with self.subTest(format=battle_format):
                protocol = pc.versus_protocol(battle_format)
                self.assertIsNotNone(protocol)
                if protocol == default:
                    self.assertIn(battle_format, ("DM20",), f"{battle_format} fell back to {default}")
                self.assertIsNotNone(BattleSimulator(protocol, battle_format=battle_format))

    def test_every_offered_line_is_a_battle_format_or_a_capture(self):
        """Whatever the grid enables is either fought or recorded, never
        fought as another line."""
        for line, label, enabled in pc.menu_entries():
            if enabled:
                with self.subTest(line=line):
                    self.assertTrue(line in pc.BATTLE_FORMATS or pc.capture_constants(line))

    # Fixed 2026-10-13; kept as a regression test.
    def test_only_battle_formats_are_selectable_for_the_release(self):
        """For 1.0 the protocol grid (versus and DCom alike) enables exactly
        the battle formats: no upcoming line is offered."""
        enabled = {line for line, _, on in pc.menu_entries() if on}
        self.assertEqual(enabled, set(pc.BATTLE_FORMATS))


class WiFiComGate(unittest.TestCase):
    """BAT-07: WiFi-Com battles are held back for 1.0 (owner, 2026-10-13).
    The Connect menu's WiFi-Com button is the only way in; its availability
    check reports it unavailable outside debug mode, even with the wificom.dev
    credentials in place and the internet reachable."""

    def check(self, debug):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        from unittest import mock
        from core import game_globals
        from scenes.connect_views.main_menu_view import MainMenuView
        from services import wificom_service
        menu = MainMenuView.__new__(MainMenuView)
        menu._wificom_available = None
        config = mock.Mock(debug_mode=debug)
        with mock.patch.object(game_globals, "configuration", config),                 mock.patch.object(wificom_service, "transport_available", return_value=True),                 mock.patch.object(wificom_service, "credentials_available", return_value=True),                 mock.patch.object(wificom_service, "internet_available", return_value=True):
            MainMenuView._check_wificom_availability_async(menu)
        return menu._wificom_available

    def test_wificom_is_not_offered_for_the_release(self):
        self.assertIs(self.check(debug=False), False)

    def test_debug_mode_still_offers_wificom(self):
        self.assertIs(self.check(debug=True), True)


class PetBattleData(unittest.TestCase):
    # Fixed 2026-10-13; kept as a regression test.
    def test_a_species_injury_chance_reaches_the_pet(self):
        """finish_battle reads ``injury_probability`` off the pet; set_data has
        to put it there from the monster record (DMM, IC give one)."""
        from models.game_pet import GamePet
        record = {"module": "DMM", "name": "Testmon", "stage": 3, "version": 1, "special": False,
                  "evolve": [], "power": 20, "atk_main": 1, "injury_probability": 10}
        pet = GamePet.__new__(GamePet)
        pet.set_data(record)
        self.assertEqual(getattr(pet, "injury_probability", 0), 10)


class DriverCoverage(unittest.TestCase):
    def charge_minigames(self):
        names = {getattr(pc.get_constants(f), "MINIGAME", "None") for f in pc.BATTLE_FORMATS}
        for name in release_modules():
            names.add(module_json(name).get("battle_minigame", "Dummy Bar"))
        return names - {"None", None}

    def test_the_test_player_knows_every_charge_minigame(self):
        """A charge minigame with no press in CHARGE_PRESS would leave the
        battle tests waiting on a bar that never fills or stops."""
        from ui.minigames.minigame_session import MINIGAMES
        for minigame in sorted(self.charge_minigames()):
            with self.subTest(minigame=minigame):
                self.assertIn(minigame, bf.CHARGE_PRESS)
                self.assertIn(minigame, MINIGAMES, f"{minigame} is not a minigame the game knows")


if __name__ == "__main__":
    unittest.main()
