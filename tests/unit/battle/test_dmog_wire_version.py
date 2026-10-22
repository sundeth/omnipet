"""The Digital Monster's packet 2 numbers its releases from 0 (a player's
report, 2026-10-21, on a WonderSwan Ver.; wificom's punchbags agree: "DMOG
you win" is V1-FC03-FD02, version 0). Omnipet sent Ver.1 as 1.

    devices.json      Ver.1-Ver.6 carry 0-5; their eggs keep versions 1-6
    what a pet sends  its device_version (VERSION_RANGE 0-4; Ver.6 clamped to 4)
    an outsider       0, the first release
    old saves         device_version == version (1-6) becomes 0-5 on load
    a received 0      the roster's Ver.1
"""
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
for path in (os.path.join(ROOT, "src"), os.path.join(ROOT, "tests", "unit", "android")):
    if path not in sys.path:
        sys.path.insert(0, path)

from battle.sim import protocol_constants  # noqa: E402
from battle.sim.battle_simulator import DMDevice  # noqa: E402
from core import runtime_globals  # noqa: E402
from test_android_offline import module, pet  # noqa: E402

MODULES = os.path.join(ROOT, "modules")


class Wire(unittest.TestCase):
    def test_ver1_sends_0_as_the_punchbag_does(self):
        digimon = SimpleNamespace(version=0, power=0, mini_game=0, index=2, compatibility=False)
        self.assertEqual(DMDevice(digimon).generate_packet2(2).hex().upper(), "FD02")

    def test_the_range_and_an_outsider(self):
        self.assertEqual(protocol_constants.DMOG.VERSION_RANGE, (0, 4))
        self.assertEqual(protocol_constants.get_compatibility_version("DMOG"), 0)
        self.assertEqual([protocol_constants.clamp_oem_version("DMOG", v) for v in range(6)],
                         [0, 1, 2, 3, 4, 4])

    def test_a_received_version_names_the_roster(self):
        self.assertEqual([protocol_constants.module_versions_for_wire("DMOG", w) for w in range(5)],
                         [[1], [2], [3], [4], [5]])


@unittest.skipUnless(os.path.isdir(MODULES), "modules/ is gitignored")
class Devices(unittest.TestCase):
    def test_devices_carry_the_wire_numbers(self):
        with open(os.path.join(MODULES, "DMOG", "devices.json"), encoding="utf-8-sig") as fh:
            devices = json.load(fh)["devices"]
        self.assertEqual([(d["device_version"], [e["version"] for e in d["eggs"]]) for d in devices],
                         [(n - 1, [n]) for n in range(1, 7)])


class OldSaves(unittest.TestCase):
    def test_an_old_save_is_renumbered_once(self):
        mod = module()
        for version in range(1, 7):
            with self.subTest(version=version), \
                    patch("models.game_pet.get_module", return_value=mod), \
                    patch.object(runtime_globals, "game_console", SimpleNamespace(log=lambda *_: None)):
                p = pet(mod, module="DMOG", version=version, device_version=version)
                p.patch()
                self.assertEqual(p.device_version, version - 1)
                p.patch()
                self.assertEqual(p.device_version, version - 1, "once only")


if __name__ == "__main__":
    unittest.main()
