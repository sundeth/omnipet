"""Jogress between pets of two modules on the same battle protocol (owner,
2026-10-16: "compatible either between pets of the same module, or same
protocol if any is set").

PENGZ and the Pendulum Color both connect on the PENC wire; on the device a
PENGZ jogress "via Connection with another Digimon Pendulum Color" takes the
last column of humulos's table ("Any Digimon from another Digimon Pendulum
Color Version"), and both Monsters evolve, each by its own options (the
manual). A named route matches another module's pet by name and version (the
Ver.Revival's "connection data is entirely identical to the DM20": DMRV's
WarGreymon (Anime) with a DM20's MetalGarurumon (Anime) v9). A module without
a protocol (VB's "None") pairs only with itself.
"""
import io
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SRC = os.path.join(REPO_ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
MODULES = os.path.join(REPO_ROOT, "modules")

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import models.game_pet  # noqa: E402,F401  (the game's import order: utils.module_utils after it)
from utils import jogress_utils  # noqa: E402
from utils.jogress_utils import can_pair, compatible, find_route, normalize_evolutions  # noqa: E402

PROTOCOLS = {"PENC": "PENC", "PENGZ": "PENC", "DMC": "DMC", "VB": "None", "VBE": "None", "DM20": "DM20", "DMRV": "DM20"}


def modules(name):
    return SimpleNamespace(battle_protocol=PROTOCOLS.get(name, ""))


def pet(module, name, version=1, stage=4, attribute="Va", evolve=()):
    return SimpleNamespace(module=module, name=name, version=version, stage=stage, attribute=attribute,
                           level=1, area=0, evolve=list(evolve))


class Pairing(unittest.TestCase):
    def setUp(self):
        patcher = patch("utils.module_utils.get_module", side_effect=modules)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_rule(self):
        self.assertTrue(can_pair(pet("PENC", "A"), pet("PENC", "B")))
        self.assertTrue(can_pair(pet("PENGZ", "A"), pet("PENC", "B")))
        self.assertFalse(can_pair(pet("PENGZ", "A"), pet("DMC", "B")))
        self.assertFalse(can_pair(pet("VB", "A"), pet("VBE", "B")))       # "None" sets none
        self.assertTrue(can_pair(pet("VB", "A"), pet("VB", "B")))

    def test_named_routes_by_name_and_version(self):
        # DMRV's WarGreymon (Anime) names the DM20's MetalGarurumon (Anime) v9.
        named = [{"to": "Omnimon", "jogress": "Single", "jogress_name": "MetalGarurumon (Anime)", "jogress_version": 9}]
        owner = pet("DMRV", "WarGreymon (Anime)", version=12, stage=6, evolve=named)
        self.assertIsNotNone(find_route(owner, pet("DM20", "MetalGarurumon (Anime)", version=9, stage=6)))
        self.assertIsNone(find_route(owner, pet("DM20", "MetalGarurumon (Anime)", version=13, stage=6)))
        self.assertIsNone(find_route(owner, pet("DMC", "MetalGarurumon (Anime)", version=9, stage=6)))

    def test_a_prefix_takes_any_version(self):
        # D-3's Ten Warriors: any "Ancient" Digimon, whatever its version, for
        # Susanomon; a plain named route without a version means the owner's.
        prefix = [{"to": "Susanomon", "jogress": "Single", "jogress_name": "Ancient", "jogress_prefix": True}]
        named = [{"to": "Susanomon", "jogress": "Single", "jogress_name": "AncientGarurumon"}]
        partner = pet("PENC", "AncientGarurumon", version=3, stage=6)
        self.assertIsNotNone(find_route(pet("PENC", "AncientGreymon", 1, 6, evolve=prefix), partner))
        self.assertIsNone(find_route(pet("PENC", "AncientGreymon", 1, 6, evolve=named), partner))

    def test_attribute_routes_cross(self):
        route = [{"to": "MasterTyrannomon", "jogress": "Dual", "jogress_stage": 4, "jogress_attribute": "Va"}]
        owner = pet("PENGZ", "Tyrannomon", evolve=route)
        self.assertEqual(find_route(owner, pet("PENC", "Kabuterimon"))["to"], "MasterTyrannomon")
        self.assertIsNone(find_route(owner, pet("DMC", "Kabuterimon")))
        self.assertFalse(compatible(owner, pet("DMC", "Kabuterimon")))


@unittest.skipUnless(os.path.isdir(os.path.join(MODULES, "PENGZ")) and os.path.isdir(os.path.join(MODULES, "PENC")),
                     "modules folder not present")
class ModuleData(unittest.TestCase):
    """PENGZ's Tyrannomon with a Nature Spirits Kabuterimon (PENC v1): each
    evolves by its own module's table, MasterTyrannomon and Angewomon
    (humulos's PENC list; the PENGZ manual's example says Jyagamon)."""

    def setUp(self):
        patcher = patch("utils.module_utils.get_module", side_effect=modules)
        patcher.start()
        self.addCleanup(patcher.stop)

    def record(self, module, name, version):
        with io.open(os.path.join(MODULES, module, "monster.json"), encoding="utf-8-sig") as fh:
            m = next(x for x in json.load(fh)["monster"] if x["name"] == name and x["version"] == version)
        return pet(module, name, version, m["stage"], m.get("attribute"), normalize_evolutions(m.get("evolve") or []))

    def test_both_evolve_by_their_own_table(self):
        tyrannomon, kabuterimon = self.record("PENGZ", "Tyrannomon", 1), self.record("PENC", "Kabuterimon", 1)
        self.assertTrue(compatible(tyrannomon, kabuterimon))
        mine, theirs = find_route(tyrannomon, kabuterimon), find_route(kabuterimon, tyrannomon)
        self.assertEqual((mine["to"], theirs["to"]), ("MasterTyrannomon", "Angewomon"))
        self.assertTrue(jogress_utils.is_dual(mine))


if __name__ == "__main__":
    unittest.main()
