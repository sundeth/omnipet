# -*- coding: utf-8 -*-
"""Adventure played through SceneBattle like a player, by touch alone.

Checklist BAT-04 (every battle mode works, adventure through its real
screens) and BAT-03 (the module's adventure style and charge are the ones
played). Each case taps from the Battle menu: ADVENTURE -> the module's
button -> GO -> FIGHT (Area Selection) or NEXT / RESET (Next and Reset),
taps through the module's charge minigame, and watches the battle until the
game returns to the main scene. Nothing is driven behind the views' backs
except, in the feeding case, the HP that settles each round
(battle_flow.force_outcome) so the run reaches the feeding menu.

* DMC: an Area Selection, sequential module plays area 1 to its end -- every
  round in turn, until the boss falls or a round is lost;
* DM20: a Next and Reset module fights with NEXT, and RESET puts its
  progress back to area 1 first;
* IC: an area's entry fee is paid when FIGHT is pressed, and with too little
  Fight Money the fight is refused ("No Money") and nothing is charged;
* DMX: the feeding menu between rounds of a long area (Food, then Next)
  feeds the team and the next round starts.

Runs on the harness's fake clock in touch mode; every loop is bounded.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import battle_flow as bf  # noqa: E402

#: The longest any case may take: a whole sequential area, three rounds.
MAX_FRAMES = 30000


@unittest.skipUnless(os.path.isdir(bf.MODULES), "modules folder not present")
class AdventureSceneFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness import Env
        cls.env = Env("240x240")

    # ------------------------------------------------------------ helpers
    def start(self, module_name, seed=1, prepare=None):
        """A battle-ready pet of *module_name* alone in the party, the
        Battle scene open on its menu. *prepare* runs before the scene opens."""
        if bf.installed(module_name) is None:
            self.skipTest(f"{module_name} not installed")
        env = self.env
        bf.fresh(env, seed=seed, input_mode=env.rg.TOUCH_MODE)
        pet = bf.ensure_battle_record(bf.battle_pet(module_name))
        bf.set_party(env, [pet])
        if prepare:
            prepare(pet)
        game = env.game("battle")
        env.frames(game, 3)
        self.assertEqual(game.scene.current_view_name, "main_menu")
        return game, pet

    def tap(self, game, component):
        self.assertTrue(component.visible, f"{component} is not on screen")
        self.env.tap(game, component.rect.center)
        self.env.frames(game, 3)

    def open_module(self, game, module_name):
        """ADVENTURE, then the module's button (paging with MORE), then GO."""
        scene = game.scene
        self.tap(game, scene.current_view.adventure_button)
        self.assertEqual(scene.current_view_name, "adventure_module_selection")
        view = scene.current_view
        for _ in range(len(view.module_buttons)):
            button = next((b for b in view.module_buttons if b.module.name == module_name), None)
            self.assertIsNotNone(button, f"{module_name} has no adventure button")
            if button.visible:
                break
            self.tap(game, view.more_button)
        if view.selected_module is None or view.selected_module.name != module_name:
            self.tap(game, button)
        self.assertEqual(view.selected_module.name, module_name)
        self.tap(game, view.go_button)
        self.assertEqual(scene.current_view_name, "adventure_area_selection")
        return scene.current_view

    def play(self, game, win=None, on_phase=None):
        """Watch the adventure until the game leaves the Battle scene, tapping
        the screen through every charge. Returns the rounds' verdicts."""
        from scenes.scene_battle import SceneBattle
        env = self.env
        verdicts, last = [], None
        encounter = None
        for frame in range(MAX_FRAMES):
            scene = game.scene
            if not isinstance(scene, SceneBattle):
                return verdicts
            view = scene.current_view
            current = getattr(view, "battle_encounter", None)
            if current is not None and current is not encounter:
                encounter, last = current, None
            if encounter is not None:
                phase = encounter.phase
                if phase != last:
                    if phase == "charge" and win is not None:
                        bf.force_outcome(encounter, win)
                    if phase == "battle":
                        verdicts.append(encounter.victory_status)
                    if on_phase:
                        on_phase(view, encounter, phase)
                    last = phase
                if phase == "charge" and frame % bf.PRESS_EVERY == 0:
                    env.tap(game, (env.w // 2, env.h // 2))
            env.frames(game, 1)
        self.fail(f"still in the Battle scene after {MAX_FRAMES} frames: {verdicts}")

    def assert_back_in_the_game(self, game):
        from scenes.scene_maingame import SceneMainGame
        self.assertIsInstance(game.scene, SceneMainGame)
        self.assertEqual(bf.battle_errors(self.env), [])

    # ------------------------------------------------------------ cases
    def test_an_area_selection_module_plays_its_first_area(self):
        """DMC: FIGHT on area 1 plays its rounds in turn until the area ends."""
        game, pet = self.start("DMC")
        dp = pet.dp
        area_view = self.open_module(game, "DMC")
        self.assertEqual(area_view.area_selection.get_selected_area_round(), (1, 1))
        self.tap(game, area_view.fight_button)
        self.assertEqual(game.scene.current_view_name, "adventure_battle")
        encounter = game.scene.current_view.battle_encounter
        self.assertEqual((encounter.module.name, encounter.area, encounter.round), ("DMC", 1, 1))

        verdicts = self.play(game)

        self.assert_back_in_the_game(game)
        self.assertTrue(verdicts, "no round was fought")
        self.assertTrue(all(v in ("Victory", "Defeat") for v in verdicts), verdicts)
        # A sequential area goes on while it is won: every round but the last
        # one fought was a win, and the run ends on a loss or the boss.
        self.assertTrue(all(v == "Victory" for v in verdicts[:-1]), verdicts)
        area_rounds = encounter.module.get_area_round_counts()[1]
        self.assertTrue(verdicts[-1] == "Defeat" or len(verdicts) == area_rounds, verdicts)
        self.assertEqual(pet.battles, len(verdicts))
        self.assertEqual(pet.win, verdicts.count("Victory"))
        self.assertEqual(pet.dp, max(0, dp - len(verdicts) * encounter.module.battle_cost_amount))
        cleared = verdicts == ["Victory"] * area_rounds
        self.assertEqual(self.env.gg.battle_area.get("DMC"), 2 if cleared else 1)
        self.assertEqual(self.env.gg.battle_round.get("DMC"), 1)

    def test_a_next_and_reset_module_fights_with_next(self):
        """DM20: RESET puts the progress back to area 1, NEXT fights it."""
        def far_along(pet):
            self.env.gg.battle_area["DM20"] = 7
            self.env.gg.battle_round["DM20"] = 1
        game, pet = self.start("DM20", prepare=far_along)
        area_view = self.open_module(game, "DM20")
        self.assertIsNotNone(area_view.next_button)
        self.assertIsNone(area_view.fight_button)
        self.tap(game, area_view.reset_button)
        self.assertEqual((self.env.gg.battle_area["DM20"], self.env.gg.battle_round["DM20"]), (1, 1))
        self.tap(game, area_view.next_button)
        self.assertEqual(game.scene.current_view_name, "adventure_battle")
        encounter = game.scene.current_view.battle_encounter
        self.assertEqual((encounter.area, encounter.round), (1, 1))
        self.assertIsNotNone(encounter.module.battle_minigame)

        verdicts = self.play(game)

        self.assert_back_in_the_game(game)
        self.assertEqual(len(verdicts), 1, "a Next and Reset battle is one round")
        self.assertEqual(pet.battles, 1)
        self.assertEqual(self.env.gg.battle_area["DM20"], 2 if verdicts == ["Victory"] else 1)

    def test_an_entry_fee_is_paid_on_fight_or_refused(self):
        """IC: area 2 costs its Fight Money on FIGHT; short of it, No Money."""
        from utils import currency_utils
        module = bf.installed("IC")
        if module is None:
            self.skipTest("IC not installed")
        currency, fee = currency_utils.entry_cost(module, 2, [])
        if fee <= 0:
            self.skipTest("IC area 2 charges no entry fee")

        def at_area_2(pet):
            self.env.gg.battle_area["IC"] = 2
            self.env.gg.battle_round["IC"] = 1

        # Short of the fee: refused, nothing charged, no battle.
        game, pet = self.start("IC", prepare=at_area_2)
        currency_utils.add_currency("IC", currency, fee - 1 - currency_utils.get_balance("IC", currency))
        area_view = self.open_module(game, "IC")
        self.assertEqual(area_view.area_selection.get_selected_area_round(), (2, 1))
        self.tap(game, area_view.fight_button)
        self.assertEqual(game.scene.current_view_name, "adventure_area_selection")
        self.assertEqual(currency_utils.get_balance("IC", currency), fee - 1)
        self.assertIn("fail", self.env.sounds)
        self.assertEqual(pet.battles, 0)

        # With the fee: paid once, on FIGHT, and the battle is area 2's.
        game, pet = self.start("IC", prepare=at_area_2)
        currency_utils.add_currency("IC", currency, fee - currency_utils.get_balance("IC", currency))
        area_view = self.open_module(game, "IC")
        self.tap(game, area_view.fight_button)
        self.assertEqual(game.scene.current_view_name, "adventure_battle")
        self.assertEqual(currency_utils.get_balance("IC", currency), 0)
        encounter = game.scene.current_view.battle_encounter
        self.assertEqual((encounter.area, encounter.round), (2, 1))

        verdicts = self.play(game)

        self.assert_back_in_the_game(game)
        self.assertTrue(verdicts)
        self.assertEqual(pet.battles, len(verdicts))
        # Every round won paid its reward on top of the fee already spent.
        rewards = []
        for round_num, verdict in enumerate(verdicts, 1):
            if verdict == "Victory":
                enemies = module.get_enemies(2, round_num, [pet.version])
                rewards.append(currency_utils.battle_reward(enemies)[1])
        self.assertEqual(currency_utils.get_balance("IC", currency), sum(rewards))

    def test_the_feeding_menu_between_rounds(self):
        """DMX: after round 3 of a five-round area the feeding menu opens;
        Food feeds the team, Next starts round 4."""
        module = bf.installed("DMX")
        if module is None or not getattr(module, "battle_enable_feeding", False):
            self.skipTest("DMX not installed or without feeding")
        area = next((a for a, n in sorted(module.get_area_round_counts().items()) if n == 5), None)
        if area is None:
            self.skipTest("DMX has no five-round area")

        def at_area(pet):
            self.env.gg.battle_area["DMX"] = area
            self.env.gg.battle_round["DMX"] = 1
            pet.strength = 1        # room for the Food to show
        game, pet = self.start("DMX", prepare=at_area)
        area_view = self.open_module(game, "DMX")
        self.assertEqual(area_view.area_selection.get_selected_area_round(), (area, 1))
        self.tap(game, area_view.fight_button)
        seen = {}

        def on_phase(view, encounter, phase):
            if phase == "feeding" and "fed" not in seen:
                seen["round"] = encounter.round
                seen["strength"] = pet.strength
                game.scene.handle_event(("DOWN", None))     # Food
                game.scene.handle_event(("A", None))
                seen["fed"] = pet.strength
                game.scene.handle_event(("B", None))        # Next
            if phase == "level" and "fed" in seen and "next" not in seen:
                seen["next"] = encounter.round

        from harness import quiet
        with quiet():
            verdicts = self.play(game, win=True, on_phase=on_phase)

        self.assert_back_in_the_game(game)
        self.assertEqual(verdicts, ["Victory"] * 5)
        self.assertIn("fed", seen, "the feeding menu never opened")
        self.assertEqual(seen["round"], 4, "feeding opens before round 4 of five")
        self.assertGreater(seen["fed"], seen["strength"], "Food did not feed the team")
        self.assertEqual(seen.get("next"), 4)
        self.assertEqual(self.env.gg.battle_area["DMX"], area + 1)


if __name__ == "__main__":
    unittest.main()
