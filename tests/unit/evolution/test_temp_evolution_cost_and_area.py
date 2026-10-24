"""Temporary evolutions: `xros_cost` and `battle_area` (owner, 2026-10-21).

xros_cost: a DigiXros on the Xros Wars Color costs DP. humulos's details page
of each DigiXros reads "Required DP: N" (Shoutmon X2 1 ... Shoutmon X7 7); the
manual: "DP - Your stamina, this is required for using a DigiXros. DP is
completely restored by sleeping for at least 4 hours". The form is offered
only to a pet holding that much DP and taking it spends the DP
(utils.xros_utils.make_xros_pet).

battle_area: Arresterdramon's two Superior Modes are tied to World 20 (humulos:
"not available during World 20" / "only available during World 20"). The
range is the area the battle is fought in: an adventure area of the pet's own
module, 0 for any other battle (events, Versus, DCom).
"""
import io
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
MODULES = os.path.join(ROOT, "modules")
SOURCES = os.path.join(ROOT, "utilities", "claude", "dmxw_sources.json")

import models.game_pet  # noqa: E402,F401  (the game's import order)
from core import game_globals, runtime_globals  # noqa: E402
from utils import xros_utils  # noqa: E402

SUPERIOR = {"to": "Arresterdramon: Superior Mode", "type": "Mode Change",
            "strength": [14, 999999], "megahit": True, "battle_area": [0, 19]}
BRAVE = {"to": "Arresterdramon: Superior Mode (Brave Snatcher)", "type": "Mode Change",
         "strength": [14, 999999], "megahit": True, "battle_area": [20, 20]}


def pet(temp, dp=0, strength=14):
    return SimpleNamespace(module="DMXW", name="Pet", strength=strength, dp=dp, temp_evolve=temp)


def offered(p, area=0):
    with patch.object(game_globals, "friends", {"DMXW": []}), \
            patch.object(xros_utils, "is_unlocked", lambda *a: True):
        return [t["to"] for t in xros_utils.get_available_temp_evolutions(p, area)]


class XrosCost(unittest.TestCase):
    TEMP = [{"to": "Shoutmon X2", "type": "Xros", "xros_cost": 1},
            {"to": "Shoutmon X5", "type": "Xros", "xros_cost": 3},
            {"to": "Free Form", "type": "Xros"}]

    def test_offered_only_with_the_dp(self):
        self.assertEqual(offered(pet(self.TEMP, dp=0)), ["Free Form"])
        self.assertEqual(offered(pet(self.TEMP, dp=2)), ["Shoutmon X2", "Free Form"])
        self.assertEqual(offered(pet(self.TEMP, dp=3)), ["Shoutmon X2", "Shoutmon X5", "Free Form"])

    def test_bad_values_are_free(self):
        for value in (None, 0, -2, "x"):
            self.assertEqual(xros_utils.xros_cost({"xros_cost": value}), 0)

    def test_paying_spends_the_dp_of_the_pet_itself(self):
        real = SimpleNamespace(name="Shoutmon", dp=5)
        form = SimpleNamespace(pet=real)                # an XrosPet stand-in
        with patch.object(runtime_globals, "game_console", Mock(), create=True):
            self.assertEqual(xros_utils.pay_xros_cost(form, {"to": "Shoutmon X5", "xros_cost": 3}), 3)
            self.assertEqual(real.dp, 2)
            self.assertEqual(xros_utils.pay_xros_cost(real, {"to": "Free Form"}), 0)
            self.assertEqual(real.dp, 2)

    def test_taking_the_form_pays(self):
        module = SimpleNamespace(name="DMXW", unlocks=[],
                                 get_monster=lambda name, version: {"name": name, "power": 180})
        p = SimpleNamespace(module="DMXW", name="OmniShoutmon", version=1, power=120, attack=1, hp=10,
                            atk_main=1, atk_alt=1, atk_alt_2=0, sprite_format=None, dp=30)
        with patch.object(xros_utils, "get_module", return_value=module), \
                patch.object(xros_utils.XrosPet, "load_sprite"), \
                patch.object(xros_utils, "record_form"), \
                patch.object(runtime_globals, "game_console", Mock(), create=True):
            form = xros_utils.make_xros_pet(p, {"to": "Shoutmon X7", "type": "Xros", "xros_cost": 7})
        self.assertEqual(form.name, "Shoutmon X7")
        self.assertEqual(p.dp, 23)
        self.assertEqual(form.dp, 23)                   # the form reads the pet's own


class BattleArea(unittest.TestCase):
    def test_the_superior_modes_split_on_world_20(self):
        temp = [SUPERIOR, BRAVE]
        self.assertEqual(offered(pet(temp), 0), [SUPERIOR["to"]])      # Versus, DCom, an event
        self.assertEqual(offered(pet(temp), 7), [SUPERIOR["to"]])
        self.assertEqual(offered(pet(temp), 19), [SUPERIOR["to"]])
        self.assertEqual(offered(pet(temp), 20), [BRAVE["to"]])

    def test_open_ends(self):
        temp = [dict(SUPERIOR, battle_area=[5, -1]), dict(BRAVE, battle_area=[-1, 3])]
        self.assertEqual(offered(pet(temp), 0), [BRAVE["to"]])
        self.assertEqual(offered(pet(temp), 4), [])
        self.assertEqual(offered(pet(temp), 50), [SUPERIOR["to"]])

    def test_no_area_requirement_means_anywhere(self):
        temp = [{"to": "Armamon: Burst Mode", "type": "Mode Change", "strength": [14, 999999]}]
        for area in (0, 1, 20):
            self.assertEqual(offered(pet(temp), area), ["Armamon: Burst Mode"])

    def test_the_encounter_reads_its_own_module_areas_only(self):
        from battle.battle_encounter import BattleEncounter
        enc = SimpleNamespace(pvp_mode=False, is_special_encounter=False, area=20,
                              module=SimpleNamespace(name="DMXW"))
        own, other = SimpleNamespace(module="DMXW"), SimpleNamespace(module="DMC")
        self.assertEqual(BattleEncounter._xros_area(enc, own), 20)
        self.assertEqual(BattleEncounter._xros_area(enc, other), 0)
        enc.is_special_encounter = True                     # an event battle
        self.assertEqual(BattleEncounter._xros_area(enc, own), 0)
        enc.is_special_encounter, enc.pvp_mode = False, True
        self.assertEqual(BattleEncounter._xros_area(enc, own), 0)


@unittest.skipUnless(os.path.isdir(os.path.join(MODULES, "DMXW")), "modules/ is gitignored")
class ModuleData(unittest.TestCase):
    def setUp(self):
        with io.open(os.path.join(MODULES, "DMXW", "monster.json"), encoding="utf-8-sig") as fh:
            self.monsters = json.load(fh)["monster"]

    def test_every_digixros_costs_dp(self):
        for m in self.monsters:
            for t in m.get("temporary-evolution") or []:
                if t.get("type") == "Xros":
                    self.assertGreater(t.get("xros_cost") or 0, 0, "%s -> %s" % (m["name"], t["to"]))
                    self.assertLessEqual(t["xros_cost"], m.get("energy") or 0, m["name"])

    @unittest.skipUnless(os.path.isfile(SOURCES), "utilities/ is gitignored")
    def test_costs_are_humulos_required_dp(self):
        with io.open(SOURCES, encoding="utf-8") as fh:
            details = json.load(fh)["details"]
        aliases = {"Decker Greymon": "DeckerGreymon", "Grey Knightsmon": "GreyKnightsmon",
                   "Metal Greymon (2010)": "MetalGreymon (2010 Anime Version)"}
        required = {aliases.get(d["name"], d["name"]): d["required_dp"]
                    for d in details.values() if d.get("required_dp")}
        self.assertEqual(required["Shoutmon X7"], 7)
        for m in self.monsters:
            for t in m.get("temporary-evolution") or []:
                if t.get("type") == "Xros":
                    self.assertEqual(t["xros_cost"], required[t["to"]], t["to"])

    def test_the_superior_modes(self):
        arrester = next(m for m in self.monsters if m["name"] == "Arresterdramon" and m["version"] == 1)
        areas = {t["to"]: t.get("battle_area") for t in arrester["temporary-evolution"]}
        self.assertEqual(areas[SUPERIOR["to"]], [0, 19])
        self.assertEqual(areas[BRAVE["to"]], [20, 20])
        with io.open(os.path.join(MODULES, "DMXW", "battle.json"), encoding="utf-8-sig") as fh:
            last = max(e["area"] for e in json.load(fh)["enemies"] if not e.get("special_encounter"))
        self.assertEqual(last, 20)                          # World 20 is the last, World F
        for m in self.monsters:
            for t in m.get("temporary-evolution") or []:
                if t["to"] == "Shoutmon X7: Superior Mode":     # reached through the X7 DigiXros
                    self.assertEqual(t.get("xros_cost"), 7, m["name"])


if __name__ == "__main__":
    unittest.main()
