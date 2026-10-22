"""A temporary evolution unlocks itself (owner, 2026-10-21: "any temporary
evolution should unlock itself in the library"). When a pet takes a battle
form (DigiXros, Mode Change: utils.xros_utils.make_xros_pet), the Library
(Digidex) records the form and the module's evolution unlocks naming it are
earned, as an evolution into it earns them. The Xros Wars Color's Album
forms (Shoutmon King Version, Gumdramon, OmniShoutmon, ZeigGreymon) are
keyed on those unlocks and could not be reached before.
"""
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

from core import runtime_globals  # noqa: E402
from utils import xros_utils  # noqa: E402

MODULES = os.path.join(ROOT, "modules")
UNLOCKS = [
    {"name": "Album: Shoutmon X7", "type": "evolution", "to": ["Shoutmon X7"]},
    {"name": "Album: Other", "type": "evolution", "to": ["Someone Else"]},
    {"name": "Stage V", "type": "evolution", "stage": 5},
    {"name": "Shoutmon X7", "type": "adventure", "area": 3},
]


class RecordForm(unittest.TestCase):
    def record(self, name):
        module = SimpleNamespace(name="DMXW", unlocks=UNLOCKS)
        with patch("models.game_digidex.register_digidex_entry") as dex, \
                patch("utils.utils_unlocks.unlock_item") as unlock, \
                patch("utils.utils_unlocks.check_digidex_unlocks") as counts:
            xros_utils.record_form(module, name, 1)
        return dex, unlock, counts

    def test_the_library_records_the_form(self):
        dex, _unlock, counts = self.record("Shoutmon X7")
        dex.assert_called_once_with("Shoutmon X7", "DMXW", 1)
        counts.assert_called_once_with("DMXW")

    def test_only_the_evolution_unlocks_naming_it(self):
        _dex, unlock, _counts = self.record("Shoutmon X7")
        unlock.assert_called_once_with("DMXW", "evolution", "Album: Shoutmon X7")

    def test_a_form_no_unlock_names(self):
        _dex, unlock, _counts = self.record("Shoutmon X2")
        unlock.assert_not_called()

    def test_taking_the_form_records_it(self):
        module = SimpleNamespace(name="DMXW", unlocks=UNLOCKS,
                                 get_monster=lambda name, version: {"name": name, "power": 90})
        pet = SimpleNamespace(module="DMXW", name="OmniShoutmon", version=1, power=80, attack=1, hp=10,
                              atk_main=1, atk_alt=1, atk_alt_2=0, sprite_format=None)
        with patch.object(xros_utils, "get_module", return_value=module), \
                patch.object(xros_utils.XrosPet, "load_sprite"), \
                patch.object(xros_utils, "record_form") as record, \
                patch.object(runtime_globals, "game_console", Mock(), create=True):
            form = xros_utils.make_xros_pet(pet, {"to": "Shoutmon X7", "type": "Xros"})
        self.assertEqual(form.name, "Shoutmon X7")
        record.assert_called_once_with(module, "Shoutmon X7", 1)


@unittest.skipUnless(os.path.isdir(MODULES), "modules/ is gitignored")
class ModuleData(unittest.TestCase):
    def test_every_album_unlock_has_a_temporary_form_that_earns_it(self):
        """Every evolution unlock a special form is keyed on names a form
        some route or temporary evolution reaches, on every module."""
        for name in sorted(os.listdir(MODULES)):
            folder = os.path.join(MODULES, name)
            if not os.path.isfile(os.path.join(folder, "monster.json")):
                continue
            with open(os.path.join(folder, "module.json"), encoding="utf-8-sig") as f:
                unlocks = {u.get("name"): u for u in json.load(f).get("unlocks") or []}
            with open(os.path.join(folder, "monster.json"), encoding="utf-8-sig") as f:
                monsters = json.load(f)["monster"]
            targets = {e.get("to") for m in monsters
                       for e in (m.get("evolve") or []) + (m.get("temporary-evolution") or [])}
            for m in monsters:
                key = m.get("special_key")
                u = unlocks.get(key)
                if not m.get("special") or not u or u.get("type") != "evolution" or not u.get("to"):
                    continue
                with self.subTest(module=name, form=m.get("name"), unlock=key):
                    self.assertTrue(set(u["to"]) & targets, f"nothing reaches {u['to']}")


if __name__ == "__main__":
    unittest.main()
