"""Vital Values a run without care mistakes earns (owner, 2026-10-15).

The routes keep their requirements; the acquisition changed so they are in
reach (utilities/claude/vital_values_balance_20261015.py, MOD-19's
vital_values_reach):

* the device keeps Vital Values from Stage I through Stage III and resets
  them at every later evolution (humulos' VB and BE guides); Omnipet reset
  them every time;
* the hour that ends a form pays before its routes are read: Baby II's three
  hours paid twice;
* an Adventure battle pays the BE stage table a card battle pays ("winning
  battles will increase them, while losing battles will decrease them");
* the Child holds 4000, the most its BE routes ask (Ukkomon v14), not 2500.

GamePet and its Android copy (services.android_offline) agree.
"""
import os
import random
import sys
import time
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SRC = os.path.join(REPO_ROOT, "src")
for path in (SRC, REPO_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from core import pet_stats, runtime_globals  # noqa: E402
from models.game_pet import GamePet  # noqa: E402
from services.android_offline import OfflineWorld  # noqa: E402
from utils import card_battle  # noqa: E402


def module(**overrides):
    data = dict(name="Test", unlocks=[], visible_stats=["Vital Values"], traited_egg_starting_level=1,
                use_condition_hearts=False, care_99g_effect="Nothing",
                meat_care_mistake_time=20, protein_care_mistake_time=20,
                sleep_care_mistake_timer=20, death_max_injuries=0, death_sick_timer=0,
                death_hunger_timer=0, death_strength_timer=0, death_stage45_mistake=0,
                death_stage67_mistake=0, death_starvation_count=0, death_care_mistake=0,
                death_old_age=0, death_save_by="Nothing", death_save_amount=0,
                death_save_seconds=60, death_save_chance=100, injury_chance_step=0,
                care_poop_chance=[100, 0, 0, 0], care_poop_sickness_count=0,
                traited_egg_rule="None", get_monster=lambda *_: None,
                get_all_monsters=lambda: [], load_events_json=lambda: [],
                get_friend_encounters=lambda: [], use_gcells=False,
                vital_value_base=150, vital_value_loss=50)
    data.update(overrides)
    return SimpleNamespace(**data)


def species(name="Baby", stage=2, **overrides):
    data = dict(module="Test", name=name, stage=stage, version=1, special=False,
                evolve=[], time=999999, min_weight=10, stomach=4, hunger_loss=9999,
                strength_loss=9999, power=0, attribute="Va", energy=20,
                poop_timer=9999, atk_main=1, sleeps="23:59", wakes="00:00")
    data.update(overrides)
    return data


def pet(mod, **overrides):
    with patch("models.game_pet.get_module", return_value=mod), \
            patch.object(GamePet, "load_sprite"), patch.object(GamePet, "begin_position"):
        p = GamePet(species(**{k: v for k, v in overrides.items() if k in ("stage", "time", "evolve")}))
    p.android_id = "pet1"
    p.hunger = p.strength = 4
    p.x = p.y = 0
    p.__dict__.update(overrides)
    return p


def snapshot(pets, at):
    mono = time.monotonic()
    for p in pets:
        p._rt_origin = mono
        p._last_age_date = datetime.fromtimestamp(at).date()
    return dict(at=at, generation="test-generation", rng=random.Random(42).getstate(),
                pets=[p.android_offline_snapshot(at, mono) for p in pets],
                poop_list=[], unlocks={}, traited=[], gcell_fragments=[], quests=[],
                friends={}, digidex=[], friend_event_pending=None, xai=3,
                xai_date=datetime.fromtimestamp(at).date(), event=None, event_time=60)


class Quiet(unittest.TestCase):
    def setUp(self):
        for name, value in (("game_console", SimpleNamespace(log=lambda *_: None)),
                            ("game_sound", SimpleNamespace(play=lambda *_: None))):
            patcher = patch.object(runtime_globals, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)


class Carry(Quiet):
    def test_the_rule(self):
        self.assertEqual(pet_stats.carried_vital_values(1, 2, 700), 700)
        self.assertEqual(pet_stats.carried_vital_values(2, 3, 1300), 1300)
        self.assertEqual(pet_stats.carried_vital_values(2, 3, 9000), 4000)   # the Child's cap
        self.assertIsNone(pet_stats.carried_vital_values(3, 4, 4000))
        self.assertIsNone(pet_stats.carried_vital_values(0, 1, 100))

    def evolve(self, from_stage, to_stage, visible=("Vital Values",)):
        mod = module(visible_stats=list(visible),
                     get_monster=lambda *_: species("Next", stage=to_stage))
        p = pet(mod, stage=from_stage, vital_values=1300)
        with patch("models.game_pet.get_module", return_value=mod), \
                patch.object(GamePet, "load_sprite"), \
                patch("models.game_pet.register_digidex_entry"), \
                patch("utils.utils_unlocks.check_digidex_unlocks"), \
                patch("utils.reward_utils.reward_evolution"):
            self.assertTrue(p.evolve_to("Next", 1))
        return p.vital_values

    def test_foreground(self):
        self.assertEqual(self.evolve(2, 3), 1300)
        self.assertEqual(self.evolve(3, 4), 100)
        self.assertEqual(self.evolve(2, 3, visible=()), 100)

    def test_android(self):
        at = datetime(2026, 9, 12, 12).timestamp()
        for to_stage, expected in ((3, 1300), (4, 100)):
            mod = module(get_monster=lambda *_, s=to_stage: species("Next", stage=s))
            state = snapshot([pet(mod, stage=to_stage - 1, time=1, evolve=[{"to": "Next"}],
                                  vital_values=1300)], at)
            world = OfflineWorld(state, {"Test": mod}).advance(at + 60)
            self.assertEqual((world.pet_list[0].name, world.pet_list[0].vital_values), ("Next", expected))


class LastHour(Quiet):
    def test_the_hour_that_ends_the_form_counts(self):
        # Baby II for an hour, trained in it: 100 + 150 x 2 reaches 400.
        at = datetime(2026, 9, 12, 12).timestamp()
        route = [{"to": "Child", "vital_values": [400, 999999]}, {"to": "Other"}]
        mod = module(get_monster=lambda name, *_: species(name, stage=3))
        state = snapshot([pet(mod, stage=2, time=60, evolve=route, vital_values=100,
                              vital_activities=["training"])], at)
        world = OfflineWorld(state, {"Test": mod}).advance(at + 3600)
        self.assertEqual(world.pet_list[0].name, "Child")
        self.assertEqual(world.pet_list[0].vital_values, 400)


class Battles(Quiet):
    def fighter(self, stage=3, vital_values=1000):
        return SimpleNamespace(name="Fighter", stage=stage, state="idle", vital_values=vital_values,
                               active_boost=None, tracks_vital_values=lambda: True,
                               vital_value_cap=lambda: pet_stats.vital_value_cap(stage))

    def test_adventure_pays_the_table(self):
        from battle.battle_encounter import BattleEncounter
        for won, expected in ((True, 1200), (False, 840)):
            fighter = self.fighter()
            encounter = SimpleNamespace(card_battle=None, xros_forms={}, battle_player=SimpleNamespace(
                team1=[fighter], team2=[SimpleNamespace(stage=3)]))
            BattleEncounter._battle_vital_values(encounter, won)
            self.assertEqual(fighter.vital_values, expected)

    def test_a_card_battle_pays_once(self):
        from battle.battle_encounter import BattleEncounter
        fighter = self.fighter()
        encounter = SimpleNamespace(card_battle={"event_id": "x"}, xros_forms={}, battle_player=SimpleNamespace(
            team1=[fighter], team2=[SimpleNamespace(stage=3)]))
        BattleEncounter._battle_vital_values(encounter, True)
        self.assertEqual(fighter.vital_values, 1000)

    def test_babies_and_the_cap(self):
        baby = self.fighter(stage=2)
        self.assertEqual(card_battle.battle_vital_values(baby, 3, True), 0)
        child = self.fighter(vital_values=3900)
        card_battle.battle_vital_values(child, 4, True)
        self.assertEqual(child.vital_values, 4000)


if __name__ == "__main__":
    unittest.main()
