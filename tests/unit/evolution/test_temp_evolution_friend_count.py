"""Temporary evolutions: `friend_count` (2026-10-16).

DMXW's Shoutmon X7: Superior Mode is a mode change "only available when there
are 13 or more Digimon in the Friend list" (humulos). OmniShoutmon and
ZeigGreymon, whose DigiXros is Shoutmon X7, offer it beside X7: the same
Friends, and 13 or more of them on the list (dmxw_superior_mode_20261016.py).
"""
import io
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SRC = os.path.join(REPO_ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
MODULES = os.path.join(REPO_ROOT, "modules")

import models.game_pet  # noqa: E402,F401  (the game's import order)
from core import game_globals  # noqa: E402
from utils import xros_utils  # noqa: E402

X7_FRIENDS = ["ZeigGreymon", "Ballistamon", "Dorulumon", "Starmons", "Sparrowmon"]


def pet(temp):
    return SimpleNamespace(module="DMXW", strength=14, temp_evolve=temp)


class FriendCount(unittest.TestCase):
    def offered(self, temp, friends):
        with patch.object(game_globals, "friends", {"DMXW": friends}), \
                patch.object(xros_utils, "is_unlocked", lambda *a: True):
            return [t["to"] for t in xros_utils.get_available_temp_evolutions(pet(temp))]

    def test_the_count(self):
        temp = [{"to": "Shoutmon X7", "type": "Xros", "friend": X7_FRIENDS},
                {"to": "Shoutmon X7: Superior Mode", "type": "Mode Change", "strength": [14, 999999],
                 "megahit": True, "friend": X7_FRIENDS, "friend_count": [13, 999999]}]
        twelve = X7_FRIENDS + ["Friend %d" % i for i in range(7)]
        self.assertEqual(self.offered(temp, twelve), ["Shoutmon X7"])
        self.assertEqual(self.offered(temp, twelve + ["Friend 7"]), ["Shoutmon X7", "Shoutmon X7: Superior Mode"])
        self.assertEqual(self.offered(temp, ["Friend %d" % i for i in range(20)]), [])

    @unittest.skipUnless(os.path.isdir(os.path.join(MODULES, "DMXW")), "modules folder not present")
    def test_module_data(self):
        with io.open(os.path.join(MODULES, "DMXW", "monster.json"), encoding="utf-8-sig") as fh:
            records = {(m["name"], m["version"]): m for m in json.load(fh)["monster"]}
        for key in (("OmniShoutmon", 1), ("ZeigGreymon", 2)):
            temp = records[key]["temporary-evolution"]
            superior = next(t for t in temp if t["to"] == "Shoutmon X7: Superior Mode")
            x7 = next(t for t in temp if t["to"] == "Shoutmon X7")
            self.assertEqual((superior["friend"], superior["friend_count"]), (x7["friend"], [13, 999999]))


if __name__ == "__main__":
    unittest.main()
