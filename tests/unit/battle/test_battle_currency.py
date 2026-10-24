"""Adventure entry fees and currency rewards, and the Status screen's Next
Evolution box (owner, 2026-10-05).

* Entering an area whose round 1 enemies carry ``currency_cost`` pays the
  fee first; a short balance is refused with "No Money". The area picker
  shows the fee above the circle that enters the area.
* A won battle pays the biggest ``currency_reward`` among its enemies, once,
  and the result screen shows it.
* "Next Evolution" in a module's visible stats adds a carousel box with the
  blacked-out IDLE1 frame of the form the evolution check returns, a route's
  % chance counted as certain; "?" when no route matches.
"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SRC = os.path.join(REPO_ROOT, "src")
for path in (SRC, REPO_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

import pygame  # noqa: E402

from core import game_globals, runtime_globals  # noqa: E402
from models.game_enemy import GameEnemy  # noqa: E402
from models.game_pet import GamePet  # noqa: E402
from utils import currency_utils  # noqa: E402

IC = os.path.join(REPO_ROOT, "modules", "IC")


def enemy(**fields):
    base = dict(name="Mon", power=10, attribute="", area=1, round=1, version=1,
                atk_main=1, atk_alt=0, atk_alt_2=0, handicap=0, id=1, stage=3,
                hp=0, unlock=None, prize=None)
    base.update(fields)
    return GameEnemy(**base)


class RewardTests(unittest.TestCase):
    def encounter(self, outcome, enemies):
        from battle.battle_encounter import BattleEncounter
        encounter = BattleEncounter.__new__(BattleEncounter)
        pet = SimpleNamespace(level=1, stage=3, add_experience=mock.Mock(),
                              finish_battle=mock.Mock())
        encounter.pvp_mode = False
        encounter.victory_status = outcome
        encounter.get_battle_effect = lambda name: None
        encounter.battle_player = SimpleNamespace(team1=[pet], team2=enemies, xp=0, bonus=0,
                                                  level_up=[False])
        encounter.global_battle_log = SimpleNamespace(device1_final=[SimpleNamespace(alive=True)])
        encounter.module = SimpleNamespace(name="IC", battle_sequential_rounds=True, items=[])
        encounter.boss, encounter.round, encounter.area = False, 1, 1
        encounter.is_special_encounter = False
        encounter.frame_counter = 0
        return encounter

    def test_a_win_pays_and_a_loss_does_not(self):
        enemies = [enemy(currency="Fight Money", currency_reward=20),
                   enemy(currency="Fight Money", currency_reward=50)]
        with mock.patch.object(game_globals, "currency", {}), \
                mock.patch.object(runtime_globals, "game_console", SimpleNamespace(log=mock.Mock())):
            won = self.encounter("Victory", enemies)
            won.process_battle_results()
            self.assertEqual(won.currency_reward, ("Fight Money", 50))
            self.assertTrue(won._has_result_rewards())
            lost = self.encounter("Defeat", enemies)
            lost.process_battle_results()
            self.assertIsNone(lost.currency_reward)
            self.assertEqual(game_globals.currency, {"IC": {"Fight Money": 50}})

    def test_the_biggest_reward_is_paid_once(self):
        enemies = [enemy(currency="Fight Money", currency_reward=20),
                   enemy(currency="Fight Money", currency_reward=50),
                   enemy(currency="Fight Money", currency_reward=50),
                   enemy()]
        self.assertEqual(currency_utils.battle_reward(enemies), ("Fight Money", 50))
        self.assertEqual(currency_utils.battle_reward([enemy()]), ("", 0))
        self.assertEqual(currency_utils.battle_reward([enemy(currency_reward=30)]), ("", 0),
                         "a reward with no currency pays nothing")


@unittest.skipUnless(os.path.exists(os.path.join(IC, "shop.json")), "modules/ is gitignored")
class ICEntryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((240, 240))
        from models.game_module import GameModule
        cls.module = GameModule(IC)

    def setUp(self):
        self.slides = mock.Mock()
        self.sound = SimpleNamespace(play=mock.Mock())
        for patch in (
                mock.patch.object(game_globals, "currency", {}),
                mock.patch.object(runtime_globals, "game_modules", {"IC": self.module}),
                mock.patch.object(runtime_globals, "game_sound", self.sound),
                mock.patch.object(runtime_globals, "game_message",
                                  SimpleNamespace(add_slide=self.slides), create=True)):
            patch.start()
            self.addCleanup(patch.stop)

    def test_enemies_load_with_their_currency(self):
        loaded = self.module.get_enemies(2, 1, [1])[0]
        self.assertEqual((loaded.currency, loaded.currency_cost), ("Fight Money", 100))
        self.assertGreater(loaded.currency_reward, 0)

    def test_each_coliseum_charges_its_fee(self):
        pets = [SimpleNamespace(version=1)]
        fees = [currency_utils.entry_cost(self.module, area, pets)[1] for area in (1, 2, 3, 4)]
        self.assertEqual(fees, [0, 100, 500, 1000])

    def test_no_money_refuses_and_charges_nothing(self):
        from scenes.battle_views import adventure_area_selection_view as view
        pets = [SimpleNamespace(version=1)]
        with mock.patch.object(view, "get_battle_targets", return_value=pets):
            currency_utils.add_currency("IC", "Fight Money", 150)
            self.assertTrue(view.pay_entry_or_refuse(self.module, 2, 1))
            self.assertEqual(currency_utils.get_balance("IC", "Fight Money"), 50)
            self.assertFalse(view.pay_entry_or_refuse(self.module, 2, 1))
            self.assertEqual(currency_utils.get_balance("IC", "Fight Money"), 50)
            self.assertEqual(self.slides.call_args[0][0], "No Money")
            self.assertTrue(view.pay_entry_or_refuse(self.module, 2, 3),
                            "only entering the area, at round 1, pays")
            self.assertTrue(view.pay_entry_or_refuse(self.module, 1, 1), "area 1 is free")

    def test_the_picker_shows_the_fees(self):
        from scenes.battle_views.adventure_area_selection_view import AdventureAreaSelectionView
        from ui.ui_manager import UIManager
        pets = [SimpleNamespace(version=1)]
        with mock.patch("scenes.battle_views.adventure_area_selection_view.get_battle_targets",
                        return_value=pets), \
                mock.patch("ui.components.pet_selector.PetSelector.set_pets"), \
                mock.patch.object(game_globals, "battle_area", {"IC": 1}), \
                mock.patch.object(game_globals, "battle_round", {"IC": 1}):
            manager = UIManager("RED")
            view = AdventureAreaSelectionView(manager, lambda *a, **k: None, self.module, 1, 1,
                                              {1: 5, 2: 5, 3: 5, 4: 5})
            manager.update()
            manager.draw(pygame.Surface((240, 240)))
        self.assertEqual(view.area_selection.entry_prices, {2: "100P", 3: "500P", 4: "1000P"})


class EvolutionPreviewTests(unittest.TestCase):
    def pet(self, routes):
        pet = GamePet.__new__(GamePet)
        pet.module, pet.name, pet.version, pet.stage = "Test", "Babymon", 1, 1
        pet.evolve = routes
        pet.mistakes = 0
        pet.effort = 3
        pet.special_encounter = False
        pet.dna = {}
        return pet

    def module(self):
        forms = {"Childmon": {"name": "Childmon", "stage": 2},
                 "Lucky": {"name": "Lucky", "stage": 2}}
        return SimpleNamespace(get_monster=lambda name, version: forms.get(name), unlocks=[])

    def test_a_chance_counts_as_certain_and_nothing_changes(self):
        pet = self.pet([{"to": "Lucky", "chance": 1}, {"to": "Childmon"}])
        with mock.patch("models.game_pet.get_module", return_value=self.module()), \
                mock.patch("models.game_pet.random.random", return_value=0.99):
            self.assertEqual(pet.preview_evolution()["name"], "Lucky")
            # The real check still rolls: 99 >= 1 misses Lucky.
            self.assertEqual(pet.find_evolution()[1]["name"], "Childmon")
        self.assertEqual(pet.name, "Babymon")

    def test_unmet_requirements_and_no_route_give_none(self):
        pet = self.pet([{"to": "Childmon", "training": [5, 99]}, {"to": "Gone"}])
        with mock.patch("models.game_pet.get_module", return_value=self.module()), \
                mock.patch.object(runtime_globals, "game_console", SimpleNamespace(log=mock.Mock())):
            self.assertIsNone(pet.preview_evolution(),
                              "too little effort, and the other target is missing")

    def test_the_carousel_box(self):
        from ui.components.status_carousel import StatusCarousel
        from ui.ui_manager import UIManager
        pygame.init()
        pygame.display.set_mode((240, 240))
        manager = UIManager("PURPLE")
        sprite = pygame.Surface((16, 16), pygame.SRCALPHA)
        sprite.fill((0, 0, 0, 255))
        for value in (sprite, None):
            carousel = StatusCarousel(0, 0, 230, 38)
            manager.add_component(carousel)
            carousel.set_pet_data({"visible_stats": ["Next Evolution"], "next_evolution": value})
            self.assertEqual([b["id"] for b in carousel.boxes], ["next_evolution"])
            carousel.build_content_surface()
            manager.remove_component(carousel)
        carousel = StatusCarousel(0, 0, 230, 38)
        carousel.set_pet_data({"visible_stats": ["Evolution Timer"], "next_evolution": sprite})
        self.assertNotIn("next_evolution", [b["id"] for b in carousel.boxes],
                         "only where the module shows it")

    def test_the_silhouette_is_black_with_its_shape(self):
        from ui.components import status_carousel
        frame = pygame.Surface((4, 4), pygame.SRCALPHA)
        frame.fill((0, 0, 0, 0))
        frame.set_at((1, 1), (200, 100, 50, 255))
        pet = SimpleNamespace(module="Test", preview_evolution=lambda: {"name": "Childmon"})
        module = SimpleNamespace(folder_path="x")
        with mock.patch("utils.module_utils.get_module", return_value=module), \
                mock.patch("utils.sprite_utils.load_pet_sprites", return_value={0: frame}):
            shadow = status_carousel.evolution_silhouette(pet)
        self.assertEqual(tuple(shadow.get_at((1, 1))), (0, 0, 0, 255))
        self.assertEqual(shadow.get_at((0, 0))[3], 0)


if __name__ == "__main__":
    unittest.main()
