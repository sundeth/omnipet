"""The first pet starts on a background its module has (UI-10).

Egg selection used to set the first background to `ver<version>`, which IC,
PENGZ, DMXW and DW1 do not have: the background window fell back to another
one, but the save kept the missing name. It now takes the chosen device's
background, else one the egg unlocks, else `ver<version>`. Every release
module with eggs is hatched on an empty party, once per selectable device
(once with no device when it has none). VB, VBE and VH devices are DIM cards
with no background of their own, so theirs come from the egg.
"""
import os
import sys
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "support"))
MODULES = os.path.join(REPO_ROOT, "modules")

RELEASE = ("D-3", "DM20", "DMC", "DMGZ", "DMH", "DMM", "DMOG", "DMRV", "DMX", "DMXW",
           "IC", "PEN20", "PENC", "PENGZ", "PENOG", "PENZ", "VB", "VBE", "VH")


@unittest.skipUnless(os.path.isdir(MODULES), "modules folder not present")
class FirstBackground(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness import Env
        cls.env = Env("240x240", fixture="empty")

    def hatch(self, module_name, device):
        """The first egg the egg screen offers for *device*, hatched on an empty party."""
        from harness import quiet
        env = self.env
        env.reset()
        env.gg.game_background = env.gg.background_module_name = None   # a new save
        game = env.game("egg")
        scene = game.scene
        module = env.rg.game_modules[module_name]
        eggs = scene._get_available_eggs(module)
        if device is not None:
            eggs = scene._get_device_eggs(module, device, eggs)
        if not eggs:
            return None
        scene.selected_device = device
        with quiet():
            scene.select_egg(eggs[0])
        return env.gg.background_module_name, env.gg.game_background

    def test_the_first_background_exists_in_its_module(self):
        for name in RELEASE:
            module = self.env.rg.game_modules.get(name)
            if module is None:
                continue
            backgrounds = {bg.get("name") for bg in getattr(module, "backgrounds", []) or []}
            if not backgrounds:
                continue
            scene = self.env.game("egg").scene
            devices = scene._get_selectable_devices(module) or [None]
            for device in devices:
                label = (device or {}).get("name", "no device")
                with self.subTest(module=name, device=label):
                    got = self.hatch(name, device)
                    if got is None:
                        self.skipTest(f"{name} {label}: no egg offered")
                    self.assertEqual(got[0], name)
                    self.assertIn(got[1], backgrounds)
                    if device is not None and device.get("background"):
                        self.assertEqual(got[1], device.get("background"))


    def test_dim_card_devices_are_offered(self):
        """Decision 9 (owner, 2026-10-14): a VB, VBE or VH device is the DIM
        card itself, with no background by design; the egg screen offers it."""
        for name in ("VB", "VBE", "VH"):
            module = self.env.rg.game_modules.get(name)
            if module is None:
                continue
            with self.subTest(module=name):
                scene = self.env.game("egg").scene
                devices = scene._get_selectable_devices(module)
                self.assertTrue(devices, f"{name}: no device offered")
                self.assertFalse([d.get("name") for d in devices if d.get("background")])
                self.assertTrue(all(scene._compose_device_sprite(module, d) is not None for d in devices))


    def test_held_back_versions_are_not_offered(self):
        """DMM Ver.3.0 and the Digivice Burst lack data for 1.0 (owner,
        2026-10-15): their eggs are Unobtainable, so neither the egg nor its
        device is offered."""
        for name, device_name in (("DMM", "Ver.3.0"), ("IC", "Digivice Burst")):
            module = self.env.rg.game_modules.get(name)
            if module is None:
                continue
            with self.subTest(module=name):
                scene = self.env.game("egg").scene
                self.assertFalse([e["name"] for e in scene._get_available_eggs(module) if e.get("version") == 3])
                self.assertNotIn(device_name, [d.get("name") for d in scene._get_selectable_devices(module)])
                self.assertTrue([e for e in scene._get_available_eggs(module) if e.get("version") in (1, 2)])


if __name__ == "__main__":
    unittest.main()
