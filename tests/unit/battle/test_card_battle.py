"""The Vital Bracelet BE's NFC battle as a card-battle event (event type 6,
2026-10-12): the opponent drawn from the pet's own card by its chances, the
BE's Vital Value table, Cyanic's item grant order, the BE items' effects,
and the VBE module data that uses them."""

import json
import os
import random
import sys
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SRC = os.path.join(REPO_ROOT, "src")
for path in (SRC, REPO_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from core import game_globals, runtime_globals  # noqa: E402
from models.game_event import EventType  # noqa: E402
from models.game_module import GameModule  # noqa: E402
from models.quest_event_data import EventData  # noqa: E402
from utils import card_battle, event_utils, item_effects  # noqa: E402

VBE = os.path.join(REPO_ROOT, "modules", "VBE")


class FixedRoll:
    """An rng whose randrange gives *value*."""

    def __init__(self, value):
        self.value = value

    def randrange(self, _n):
        return self.value


def _card(*rows):
    """Monster records of version 1: (name, stage, index, chances)."""
    return [{"name": n, "stage": s, "index": i, "version": 1, "encounter_chances": c}
            for n, s, i, c in rows]


def _module(monsters, events=()):
    module = SimpleNamespace(name="VBE", folder_path="")
    module.get_all_monsters = lambda: list(monsters)
    module.load_events_json = lambda: list(events)
    return module


def _pet(**fields):
    pet = SimpleNamespace(module="VBE", name="Agumon", version=1, stage=3, state="idle",
                          vital_values=0, active_boost=None, event_sequence={})
    pet.tracks_vital_values = lambda: True
    pet.vital_value_cap = lambda: 2500
    pet.__dict__.update(fields)
    return pet


def _event(**fields):
    defaults = dict(id="nfc", name="NFC Battle", type=6, chance_percent=10, trigger="random")
    defaults.update(fields)
    return EventData(**defaults)


class Quiet(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(runtime_globals, "game_console", SimpleNamespace(log=Mock()), create=True)
        patcher.start()
        self.addCleanup(patcher.stop)


class OpponentTests(Quiet):
    CARD = _card(("Egg", 0, -1, None), ("Agumon", 3, 2, [60, 0, 0]),
                 ("Greymon", 4, 4, [40, 70, 0]), ("WarGreymon", 6, 9, [0, 30, 100]))

    def test_stage_groups(self):
        self.assertEqual([card_battle.chance_slot(s) for s in (1, 3, 4, 5, 7, 8, 9)],
                         [0, 0, 0, 1, 1, 2, 2])

    def test_roll_walks_the_card_in_index_order(self):
        module = _module(list(reversed(self.CARD)))
        pick = lambda roll, stage: card_battle.pick_opponent(module, 1, stage, FixedRoll(roll))["name"]
        self.assertEqual([pick(0, 3), pick(59, 3), pick(60, 4), pick(99, 4)],
                         ["Agumon", "Agumon", "Greymon", "Greymon"])
        self.assertEqual([pick(69, 5), pick(70, 7), pick(0, 8)], ["Greymon", "WarGreymon", "WarGreymon"])

    def test_short_card_falls_back_to_own_species(self):
        module = _module(_card(("Agumon", 3, 2, [10, 0, 0]), ("Gabumon", 3, 3, [None, 0, 0])))
        self.assertEqual(card_battle.pick_opponent(module, 1, 3, FixedRoll(50), own_name="Gabumon")["name"],
                         "Gabumon")
        self.assertIsNone(card_battle.pick_opponent(module, 1, 3, FixedRoll(50), own_name="Nobody"))

    def test_resolve_needs_stage_three_and_the_module(self):
        module = _module(self.CARD)
        data = _event()
        self.assertIsNone(event_utils.resolve("VBE", module, data, [_pet(stage=2)], FixedRoll(0)))
        self.assertIsNone(event_utils.resolve("VBE", module, data, [_pet(module="DMX")], FixedRoll(0)))
        event = event_utils.resolve("VBE", module, data, [_pet(stage=2), _pet(stage=4)], FixedRoll(99))
        self.assertEqual((event.type, event.opponent, event.opponent_version),
                         (EventType.CARD_BATTLE, "Greymon", 1))


class RewardTests(Quiet):
    def test_vital_table(self):
        self.assertEqual(card_battle.vital_change(3, 3, True), 200)
        self.assertEqual(card_battle.vital_change(3, 3, False), -160)
        self.assertEqual(card_battle.vital_change(6, 8, True), 900)
        self.assertEqual(card_battle.vital_change(8, 3, False), -2400)
        # Outside 3-8 counts as the nearest.
        self.assertEqual(card_battle.vital_change(9, 2, True), card_battle.vital_change(8, 3, True))

    def test_sequence_advances_per_win_and_wraps(self):
        pet, data = _pet(), _event(item_sequence=["A", "", "B"])
        self.assertEqual([card_battle.next_reward(pet, data) for _ in range(4)], ["A", "", "B", "A"])
        self.assertEqual(pet.event_sequence, {"nfc": 1})

    def test_finish_pays_vital_values_and_item_on_a_win(self):
        pet, data = _pet(vital_values=2400), _event(item_sequence=["Squat Multiplier"])
        item = SimpleNamespace(id="sq", name="Squat Multiplier")
        with patch("utils.inventory_utils.get_item_by_name", return_value=item), \
                patch("utils.inventory_utils.add_to_inventory", return_value=1) as add:
            lines = card_battle.finish("VBE", data, [pet], 3, True)
        self.assertEqual(pet.vital_values, 2500)  # within the stage's cap
        self.assertEqual(lines, ["Squat Multiplier!"])
        add.assert_called_once_with("sq", 1)

    def test_a_loss_pays_no_item_and_keeps_the_place(self):
        pet, data = _pet(vital_values=100), _event(item_sequence=["A"])
        card_battle.finish("VBE", data, [pet], 3, False)
        self.assertEqual((pet.vital_values, pet.event_sequence), (0, {}))

    def test_vital_multiplier_doubles_a_win_only(self):
        pet = _pet(vital_values=0)
        card_battle.set_boost(pet, "Vital Value Reward Multiplier", ["vp"], 2, 180)
        card_battle.finish("VBE", _event(), [pet], 3, True)
        self.assertEqual(pet.vital_values, 400)

    def test_expired_boost_is_cleared(self):
        pet = _pet(active_boost={"targets": ["pp"], "amount": 3, "until": time.time() - 1})
        self.assertEqual(card_battle.boost_factor(pet, "pp"), 1)
        self.assertIsNone(pet.active_boost)


class ItemEffectTests(Quiet):
    def _item(self, status, amount=3, minutes=60):
        return SimpleNamespace(name="Item", effect="multiplier", status=status, amount=amount,
                               boost_time=minutes, min_stage=0)

    def test_pp_multiplier_triples_trophies(self):
        from models.game_pet import GamePet
        pet = _pet(trophies=0)
        self.assertTrue(item_effects.apply_pet_effect(self._item("pp"), pet))
        self.assertEqual(GamePet.award_trophies(pet, 1), 3)
        self.assertEqual(pet.trophies, 3)

    def test_one_item_at_a_time(self):
        pet = _pet()
        item_effects.apply_pet_effect(self._item("pp"), pet)
        item_effects.apply_pet_effect(self._item("vp", 2, 180), pet)
        self.assertEqual((card_battle.boost_factor(pet, "pp"), card_battle.boost_factor(pet, "vp")), (1, 2))

    def test_targets_with_no_stat_here_are_refused(self):
        pet = _pet()
        for status in ("bp", "ap", "hp"):
            self.assertFalse(item_effects.fits(self._item(status), pet))
            self.assertFalse(item_effects.apply_pet_effect(self._item(status), pet))
        self.assertTrue(item_effects.fits(self._item("pp,bp,ap,hp"), pet))
        self.assertFalse(item_effects.fits(self._item("vp"), _pet(tracks_vital_values=lambda: False)))
        self.assertIn("training_limit", item_effects.NOT_IMPLEMENTED_EFFECTS)


class BattleSideTests(Quiet):
    """BattleEncounter's part: the enemy is the drawn monster with its own
    stats, and the rewards go to the pets that fought."""

    def _encounter(self, monsters, events, team1, victory):
        from battle.battle_encounter import BattleEncounter
        encounter = BattleEncounter.__new__(BattleEncounter)
        encounter.module = _module(monsters, events)
        encounter.area, encounter.round = -1, 1
        encounter.xros_forms = {}
        encounter.card_battle = {"module": "VBE", "event_id": "nfc", "name": "NFC Battle",
                                 "opponent": "Greymon", "opponent_version": 1}
        encounter.victory_status = victory
        encounter.battle_player = SimpleNamespace(team1=team1, team2=[])
        return encounter

    def test_enemy_from_the_monster_record(self):
        monsters = [{"name": "Greymon", "version": 1, "index": 4, "stage": 4, "power": 112, "hp": 9,
                     "attribute": "Va", "atk_main": 43, "atk_alt": 66}]
        enemy = self._encounter(monsters, [], [], None)._card_battle_enemy()
        self.assertEqual((enemy.name, enemy.power, enemy.hp, enemy.stage, enemy.attribute,
                          enemy.atk_main, enemy.atk_alt, enemy.special_encounter),
                         ("Greymon", 112, 9, 4, "Va", 43, 66, True))

    def test_rewards_go_to_the_pets_that_fought(self):
        pet = _pet(stage=4, vital_values=0)
        encounter = self._encounter([], [_event(item_sequence=[""])], [pet], "Victory")
        encounter.battle_player.team2 = [SimpleNamespace(stage=4)]
        with patch("utils.event_utils._announce"):
            encounter._finish_card_battle()
        self.assertEqual((pet.vital_values, pet.event_sequence), (300, {"nfc": 0}))


class VBEDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        def load(name):
            return json.loads(open(os.path.join(VBE, name), "rb").read().decode("utf-8"))
        cls.monsters = load("monster.json")["monster"]
        cls.items = {i["name"]: i for i in load("item.json")["item"]}
        cls.events = GameModule.__new__(GameModule).parse_events_from_json(load("events.json"))

    def test_every_version_chances_sum_to_100(self):
        for version in range(1, 23):
            card = [m for m in self.monsters if m["version"] == version and "encounter_chances" in m]
            self.assertTrue(card, version)
            for slot in range(3):
                self.assertEqual(sum(m["encounter_chances"][slot] or 0 for m in card), 100,
                                 (version, slot))

    def test_nfc_event_and_its_items(self):
        self.assertEqual([(e.name, e.type, e.trigger) for e in self.events],
                         [("NFC Battle", 6, "random")])
        sequence = self.events[0].item_sequence
        self.assertEqual(len(sequence), 200)
        self.assertEqual(sum(1 for n in sequence if n), 89)
        for name in set(sequence) - {""}:
            self.assertIn(name, self.items)
            icon = os.path.join(VBE, "items", self.items[name]["sprite_name"] + ".png")
            self.assertTrue(os.path.exists(icon), icon)

    def test_draconic_blaze_card_on_version_6(self):
        greymon_line = next(m for m in self.monsters if m["version"] == 6 and m["index"] == 5)
        self.assertEqual(greymon_line["encounter_chances"], [10, 5, 5])
        rng = random.Random(1)
        module = _module(self.monsters)
        for _ in range(50):
            pick = card_battle.pick_opponent(module, 6, 4, rng)
            self.assertEqual(pick["version"], 6)
            self.assertTrue(pick["encounter_chances"][0])


if __name__ == "__main__":
    unittest.main()
