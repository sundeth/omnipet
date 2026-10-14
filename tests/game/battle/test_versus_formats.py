# -*- coding: utf-8 -*-
"""Two local pets fight a versus battle on every battle format, by touch.

Checklist BAT-04 (every battle mode works: Versus once per protocol
family), BAT-02's "works without its native module" for the local path, and
BAT-06 (unfinished protocols are held back: TWIN for 1.0). The battle
contract in CLAUDE.md says Versus is fought on the SELECTED physical
protocol, which owns its HP, rounds, charge and patterns.

For each format in protocol_constants.BATTLE_FORMATS the Battle menu is
tapped through VERSUS -> two party slots -> CONFIRM -> the format's box in
the protocol grid, and the battle is watched until the game is back on the
main scene. The pair is one pet of a module native to the format and one VB
pet (a module with no protocol of its own), so every format is also fought
by a compatibility participant. Each battle must:

* run on the chosen format (BattleEncounterVersus.battle_format, the
  simulator's protocol) with its fixed HP where it has one;
* reach a winner with no exception and no error logged;
* give both pets their battle (finish_versus), the win to the winner only,
  and charge each pet its own module's battle cost.

Known defects are written as the correct expectation and marked
expectedFailure (tests/findings/battle.md): BAT-F6 (every versus battle
needs the DMC module; the battle review of 2026-09-20, #2). Fixed and kept
as regression tests: BAT-F5 (the pets were prepared by the shared wire enum,
review #1), BAT-F7 (the wrong pets fought when the selection was part of the
party) and BAT-F8 (TWIN was offered).
"""
import os
import sys
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import battle_flow as bf  # noqa: E402

MAX_FRAMES = 6000


@unittest.skipUnless(os.path.isdir(bf.MODULES), "modules folder not present")
class VersusFormats(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness import Env
        cls.env = Env("240x240")

    # ------------------------------------------------------------ helpers
    def party(self, *module_names, seed=3):
        """Battle-ready pets of *module_names*, the whole party, touch mode."""
        env = self.env
        bf.fresh(env, seed=seed, input_mode=env.rg.TOUCH_MODE)
        pets = [bf.ensure_battle_record(bf.battle_pet(name)) for name in module_names]   # BAT-F1
        bf.set_party(env, pets)
        return pets

    def to_protocol_grid(self, slots=(0, 1)):
        """Battle menu -> VERSUS -> tap *slots* -> CONFIRM; returns the game."""
        env = self.env
        game = env.game("battle")
        env.frames(game, 3)
        scene = game.scene
        env.tap(game, scene.current_view.versus_button.rect.center)
        env.frames(game, 3)
        self.assertEqual(scene.current_view_name, "versus")
        view = scene.current_view
        for slot in slots:
            env.tap(game, bf.pet_cell_center(view.pet_selector, slot))
            env.frames(game, 1)
        self.assertTrue(view.confirm_button.enabled, "two pets picked but CONFIRM is off")
        env.tap(game, view.confirm_button.rect.center)
        env.frames(game, 3)
        self.assertEqual(scene.current_view_name, "protocol")
        return game

    def choose(self, game, battle_format):
        view = game.scene.current_view
        self.env.tap(game, bf.selector_cell_center(view.protocol_menu, battle_format))
        self.env.frames(game, 2)

    def native_pet_module(self, battle_format):
        natives = bf.native_modules_of(battle_format)
        if not natives:
            self.skipTest(f"no module native to {battle_format} installed")
        return natives[0]

    # ------------------------------------------------------------ every format
    def fight_on(self, battle_format):
        from battle.battle_encounter_versus import BattleEncounterVersus
        from battle.sim import protocol_constants
        from scenes.scene_battle import SceneBattle
        from scenes.scene_maingame import SceneMainGame
        from utils.module_utils import get_module
        if bf.installed("VB") is None:
            self.skipTest("VB not installed")
        native = self.native_pet_module(battle_format)
        pet1, pet2 = self.party(native, "VB")
        before = [(p.battles, p.win, p.dp, p.hunger) for p in (pet1, pet2)]
        game = self.to_protocol_grid()
        self.assertEqual((game.scene.current_view.pet1, game.scene.current_view.pet2), (pet1, pet2))
        self.choose(game, battle_format)
        self.assertEqual(game.scene.current_view_name, "versus_battle")
        encounter = game.scene.current_view.battle_encounter
        self.assertIsInstance(encounter, BattleEncounterVersus)
        self.assertEqual(encounter.battle_format, battle_format)
        self.assertEqual(encounter.protocol, protocol_constants.versus_protocol(battle_format))
        self.assertEqual(encounter.simulator.battle_format, battle_format)
        fixed_hp = getattr(protocol_constants.get_constants(battle_format), "FIXED_HP", None)
        if fixed_hp is not None:
            self.assertEqual((encounter.battle_player.team1_max_hp[:1], encounter.battle_player.team2_max_hp[:1]),
                             ([fixed_hp], [fixed_hp]), "the format's fixed HP was not used")

        for _ in range(MAX_FRAMES):
            if not isinstance(game.scene, SceneBattle):
                break
            self.env.frames(game, 1)
        self.assertIsInstance(game.scene, SceneMainGame, f"still fighting after {MAX_FRAMES} frames")
        self.assertEqual(bf.battle_errors(self.env), [])

        log = encounter.global_battle_log
        self.assertIn(log.winner, ("device1", "device2"))
        self.assertTrue(log.battle_log, "the simulation fought no round")
        winner = pet1 if log.winner == "device1" else pet2
        for pet, (battles, wins, dp, hunger) in zip((pet1, pet2), before):
            module = get_module(pet.module)
            cost_type = getattr(module, "battle_cost_type", "DP")
            cost = getattr(module, "battle_cost_amount", 1.0)
            with self.subTest(pet=pet.module):
                self.assertEqual(pet.battles, battles + 1)
                self.assertEqual(pet.win, wins + (1 if pet is winner else 0))
                if cost_type == "DP":
                    self.assertEqual((pet.dp, pet.hunger), (max(0, dp - cost), hunger))
                elif cost_type == "Hunger":
                    self.assertEqual((pet.dp, pet.hunger), (dp, max(0, hunger - cost)))
                else:
                    self.assertEqual((pet.dp, pet.hunger), (dp, hunger))

    # ------------------------------------------------------------ TWIN (BAT-06)
    def test_choosing_twin_starts_no_battle(self):
        """TWIN has no battle format: choosing it in the versus grid keeps the
        grid open with a note, and no battle starts."""
        from battle.sim import protocol_constants
        if "TWIN" in protocol_constants.BATTLE_FORMATS:
            self.skipTest("TWIN has a battle format now")
        self.party("DMC", "VB")
        game = self.to_protocol_grid()
        view = game.scene.current_view
        if "TWIN" not in [key for key, _, _ in view.protocol_menu.entries]:
            return      # not offered at all: held back, as BAT-06 wants
        self.choose(game, "TWIN")
        self.assertEqual(game.scene.current_view_name, "protocol")
        self.assertTrue(view.protocol_menu.visible)
        # 1.0 greys TWIN out ("Coming soon"); a debug build offers it and says
        # it is "not ready". Either way no battle starts.
        self.assertTrue(any(word in (view.protocol_menu.note or "") for word in ("not ready", "Coming soon")),
                        view.protocol_menu.note)

    # Fixed 2026-10-13; kept as a regression test.
    def test_twin_is_not_offered_in_the_versus_grid(self):
        """For 1.0 an unfinished line is not selectable: TWIN's box is absent
        or disabled in the versus protocol grid."""
        self.party("DMC", "VB")
        game = self.to_protocol_grid()
        menu = game.scene.current_view.protocol_menu
        keys = [key for key, _, _ in menu.entries]
        if "TWIN" in keys:
            self.assertFalse(menu.enabled[keys.index("TWIN")], "TWIN can be chosen")

    # ------------------------------------------------------------ known defects
    # BAT-F5 (prepared by the protocol enum). Fixed 2026-10-14; kept as a regression test.
    def test_the_payload_is_built_for_the_chosen_format(self):
        """PENC, DMXW and PENZ share a BattleProtocol with DMC or DMX. Their
        pets must still be prepared for the format chosen -- its own index
        (not the shared line's compatibility 0) and its own VERSUS_CHARGE."""
        import battle.battle_encounter_versus as versus_module
        from battle.battle_encounter_versus import BattleEncounterVersus
        from battle.sim import protocol_constants
        from harness import quiet
        real = versus_module.pet_to_digimon
        for battle_format in ("PENC", "DMXW", "PENZ"):
            with self.subTest(format=battle_format):
                native = self.native_pet_module(battle_format)
                pet1, pet2 = self.party(native, native)
                calls = []

                def spy(pet, fmt, charge=0):
                    calls.append((fmt, charge))
                    return real(pet, fmt, charge)
                with patch.object(versus_module, "pet_to_digimon", spy), quiet():
                    encounter = BattleEncounterVersus(
                        pet1, pet2, protocol_constants.versus_protocol(battle_format),
                        battle_format=battle_format)
                    encounter.simulate_combat()
                charge = getattr(protocol_constants.get_constants(battle_format), "VERSUS_CHARGE",
                                 BattleEncounterVersus.FIXED_CHARGE)
                self.assertEqual(calls, [(battle_format, charge)] * 2)

    @unittest.expectedFailure  # BAT-F6: battle_encounter_versus.py:36 builds on module "DMC"
    def test_versus_does_not_need_the_dmc_module(self):
        """A DM20 versus between two DM20 pets starts with no DMC module
        installed (physical protocols must work without other modules)."""
        from battle.battle_encounter_versus import BattleEncounterVersus
        from battle.sim import protocol_constants
        from harness import quiet
        pet1, pet2 = self.party("DM20", "DM20")
        modules = dict(self.env.rg.game_modules)
        modules.pop("DMC", None)
        with patch.dict(self.env.rg.game_modules, modules, clear=True), quiet():
            encounter = BattleEncounterVersus(pet1, pet2, protocol_constants.versus_protocol("DM20"),
                                              battle_format="DM20")
            encounter.simulate_combat()
        self.assertIn(encounter.global_battle_log.winner, ("device1", "device2"))

    # Fixed 2026-10-13; kept as a regression test.
    def test_the_picked_pets_are_the_ones_that_fight(self):
        """With only part of the party selected, VERSUS lists those pets, and
        the two tapped are the two that go to the protocol grid."""
        pets = self.party("DMC", "PENC", "DM20", "VB")
        self.env.rg.selected_pets = [pets[2], pets[3]]
        game = self.to_protocol_grid(slots=(0, 1))
        view = game.scene.current_view
        self.assertIs(view.pet1, pets[2])
        self.assertIs(view.pet2, pets[3])


def _format_test(battle_format):
    def test(self):
        self.fight_on(battle_format)
    test.__doc__ = f"{battle_format}: a versus battle is tapped through and fought on its own rules."
    return test


def _formats():
    try:
        sys.path.insert(0, os.path.join(bf.REPO_ROOT, "src"))
        from battle.sim import protocol_constants
        return protocol_constants.BATTLE_FORMATS
    except Exception:
        return ()


for _format in _formats():
    setattr(VersusFormats, f"test_{_format}", _format_test(_format))


if __name__ == "__main__":
    unittest.main()
