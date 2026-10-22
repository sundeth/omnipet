# -*- coding: utf-8 -*-
"""The iC devices carry the IC wire's own numbers (owner, 2026-10-17).

Every iC packet on record announces its device in packet 1's two version
bits: 10X Digimon 0 (C087, C0A7, C0F7, C117, C147), 20X Digimon 1 (D087,
D0A7, D127, D147) and the Burst's code 2. `devices.json` said 1/2/3 and
nothing shifted it on the way out, so an Omnipet 10X announced itself as a
20X, and DCom readings (0-2) matched the DigiShop events (1-3) one device off.

    devices.json      10X 0, 20X 1, Burst 2; their eggs keep versions 1/2/3
    what a pet sends  its device_version as it is (VERSION_RANGE 0-2)
    old saves         device_version == version (1/2/3) becomes 0/1/2 on load
    the DigiWindow    announces 1 like a 20X; its index 0x57 makes it device 4
    the Mini's wire   every iC announces 1 there, with its own index

Checklist: ICX-07, BAT-02 (release-1.0.md, decision 22).
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from ic_fixtures import ICCase, MODULES  # noqa: E402


def side(text):
    return [bytes.fromhex(p) for p in text.split("-")]


class ICWireNumbers(ICCase):
    def test_devices_carry_the_wire_numbers_and_their_eggs_the_versions(self):
        with open(os.path.join(MODULES, "IC", "devices.json"), encoding="utf-8-sig") as fh:
            devices = json.load(fh)["devices"]
        self.assertEqual([(d["device_version"], [e["version"] for e in d["eggs"]]) for d in devices],
                         [(0, [1]), (1, [2]), (2, [3])])

    def test_a_pet_announces_its_device_as_the_wire_numbers_it(self):
        from battle.sim.dcom_battle_simulator import pet_to_digimon
        for version, device in ((1, 0), (2, 1), (3, 2)):
            with self.subTest(version=version):
                pet = self.pet(version=version, device_version=device, party=False)
                self.assertEqual(pet_to_digimon(pet, "IC", 3).version, device)

    def test_on_the_minis_wire_every_ic_announces_1(self):
        """Both iCs, a 10X and a 20X, send version 1 in their Mini/Accel mode
        (documented battles 36-37); an Omnipet iC pet there did the same with
        its own index, but announced 0 (feature-gaps IC 21; 2026-10-21)."""
        from battle.sim.dcom_battle_simulator import pet_to_digimon
        for version, device in ((1, 0), (2, 1)):
            with self.subTest(version=version):
                pet = self.pet(version=version, device_version=device, party=False)
                digimon = pet_to_digimon(pet, "DMM", 3)
                self.assertEqual((digimon.version, digimon.index), (1, pet.index))

    def test_an_old_save_is_renumbered_on_load(self):
        for version in (1, 2, 3):
            with self.subTest(version=version):
                pet = self.pet(version=version, device_version=version, party=False)
                pet.patch()
                self.assertEqual(pet.device_version, version - 1)
                pet.patch()
                self.assertEqual(pet.device_version, version - 1, "once only")

    def test_the_digiwindow_is_told_apart_by_its_index(self):
        from battle.sim.dcom_battle_simulator import DComBattleSimulator
        window = DComBattleSimulator(None, battle_format="IC")
        window._parse_dmm_opponent(side("1577-4927-0B47-0007-0057"))
        self.assertEqual(window.opponent_device_version, 4)
        twenty = DComBattleSimulator(None, battle_format="IC")
        twenty._parse_dmm_opponent(side("1137-4B07-0B37-0007-E1F7"))
        self.assertEqual(twenty.opponent_device_version, 1)
        ten = DComBattleSimulator(None, battle_format="IC")
        ten._parse_dmm_opponent(side("0067-4257-0197-0007-D087"))
        self.assertEqual(ten.opponent_device_version, 0)


if __name__ == "__main__":
    unittest.main()
