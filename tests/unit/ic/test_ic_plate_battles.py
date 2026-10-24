# -*- coding: utf-8 -*-
"""The iD Plates that start a battle (owner, 2026-10-21: "you can implement
cards with encounters as effect"; utilities/IC/plate_encounters_20261021.py).

Six Plate Charge results of the 10X and 20X are a battle whose prize comes
only with the win: the card's Encounter effect names special encounter area
6, round 1-6 (card_utils.apply_card_effects), the pet's version picks the
opponent (GameModule.get_enemies), and the won battle pays its `prize`
(battle_encounter). The Burst's wait for the Burst. The 20X's Asuramon and
HippoGryphonmon fight at an assumed power since 2026-10-24 (owner: valid
values for launch; utilities/IC/ic_launch_values_20261024.py).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ic_fixtures import ICCase  # noqa: E402

#: (pattern, side, round, 10X opponent, 20X opponent, prize)
BATTLES = (
    ("10101", "L", 1, "MetalGreymon (Vaccine)", "WarGrowlmon", "Aura"),
    ("10111", "L/R", 2, "Gallantmon", "LoaderLeomon", "Aura"),
    ("11110", "R", 3, "Angewomon", "Megadramon", "Metal Armor"),
    ("11111", "L", 4, "LadyDevimon", "Asuramon", "Reliability Max"),
    ("11111", "R", 5, "WereGarurumon", "HippoGryphonmon", "Reliability Max"),
    ("11111", "L/R", 6, "Kuwagamon", "Puppetmon", "Reliability Max"),
)


class PlateBattles(ICCase):
    def setUp(self):
        super().setUp()
        from utils import card_utils
        self.cards = card_utils
        card_utils.clear_card_caches()

    def effects(self, pattern, side):
        groups = [g for g in self.cards.get_module_cards("IC")["effects"]
                  if g.get("tool") == "Plate Charge" and g.get("value") == pattern and g.get("lr") == side]
        self.assertEqual(len(groups), 1, (pattern, side))
        return groups[0]["effects"]

    def test_each_plate_starts_its_battle_for_both_lines(self):
        for pattern, side, round_, ten, twenty, _prize in BATTLES:
            for version, opponent in ((1, ten), (2, twenty)):
                with self.subTest(pattern=pattern, side=side, version=version):
                    pet = self.pet(stage=3, version=version)
                    outcome = self.cards.apply_card_effects("IC", self.effects(pattern, side), pet)
                    self.assertEqual(outcome["encounter"], ("IC", 6, round_) if opponent else None)
                    self.assertEqual(outcome["rewards"], [], "nothing before the battle")

    def test_the_version_picks_the_opponent_and_the_win_pays_the_prize(self):
        for _pattern, _side, round_, ten, twenty, prize in BATTLES:
            for version, name in ((1, ten), (2, twenty)):
                if name is None:
                    continue
                with self.subTest(round=round_, version=version):
                    enemy, = self.ic.get_enemies(6, round_, [version], special_encounter=True)
                    self.assertEqual((enemy.name, enemy.prize, enemy.prize_chance), (name, prize, 100))
                    self.assertIn(prize, {item.name for item in self.ic.items})


if __name__ == "__main__":
    unittest.main()
