# -*- coding: utf-8 -*-
"""Adventure result fixes from the 2026-10-22 documentation pass, headless.

16  a lost boss fight goes straight to its LOSE (it played WIN first, the
    "clear" phase being entered for any boss fight); a loss with nothing to
    list still plays its LOSE banner before the battle ends (the result
    screen was skipped whole when there was no reward); B during a boss's
    CLEAR records the result (it quit the battle).
18a replaying an older area leaves the saved round of the furthest area
    alone: winning a round there wrote its round, clearing it reset the
    round to 1, and so did a loss there.
18b the result's "Exp +N" includes the +10% bonus every pet was given.
19  the PvP scene hands the result screen's buttons to the encounter (its own
    branch compared the event tuple to strings and never ran).
"""
import os
import sys
import unittest
from unittest.mock import Mock, patch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import battle_flow as bf  # noqa: E402

NEEDED = ("DMC", "DMM", "D-3")


@unittest.skipUnless(all(os.path.isfile(os.path.join(bf.MODULES, m, "module.json")) for m in NEEDED),
                     "modules folder not present")
class ResultFlowFixes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness import Env
        cls.env = Env("240x240")

    def encounter(self, module, area, round_num, pet=None):
        from battle.battle_encounter import BattleEncounter
        from harness import quiet
        bf.fresh(self.env, seed=3)
        pet = pet or bf.ensure_battle_record(bf.battle_pet(module))
        bf.set_party(self.env, [pet])
        with quiet():
            enc = BattleEncounter(module, area, round_num, 1)
        enc.banners = []
        for name in ("win", "lose", "clear", "warning", "battle"):
            real = getattr(enc.animated_sprite, "play_" + name)

            def record(duration=1.0, _name=name, _real=real):
                enc.banners.append(_name)
                return _real(duration)
            setattr(enc.animated_sprite, "play_" + name, record)
        return enc, pet

    def boss_round(self, module, area=1):
        from utils.module_utils import get_module
        return get_module(module).get_area_round_counts()[area]

    # ------------------------------------------------------------ 16
    def test_a_lost_boss_fight_plays_no_win(self):
        enc, _ = self.encounter("DMC", 1, self.boss_round("DMC"))
        self.assertTrue(enc.boss)
        result = bf.run_round(self.env, enc, win=False)
        self.assertEqual(result["victory"], "Defeat")
        self.assertNotIn("clear", result["phases"])
        self.assertNotIn("win", enc.banners)
        self.assertIn("lose", enc.banners)

    def test_a_loss_with_nothing_to_list_still_shows_lose(self):
        enc, _ = self.encounter("DMC", 1, 1)
        frames_in_result = []
        real_update = enc.update_result

        def counted():
            frames_in_result.append(1)
            return real_update()
        enc.update_result = counted
        result = bf.run_round(self.env, enc, win=False, skip_battle=True)
        self.assertEqual(result["victory"], "Defeat")
        self.assertFalse(enc._has_result_rewards())
        self.assertIn("lose", enc.banners)
        # The LOSE banner lasts two seconds (60 frames at 30 fps): the
        # result waits for it instead of ending on its first frame.
        self.assertGreaterEqual(len(frames_in_result), 50)

    def test_b_during_a_boss_clear_records_the_win(self):
        from harness import quiet
        enc, _ = self.encounter("DMC", 1, self.boss_round("DMC"))
        gg = self.env.gg
        before = gg.battle_area.get("DMC", 1)
        surface = self.env.rg.render_surface
        pressed = False
        with quiet():
            for _ in range(6000):
                phase = enc.phase
                if phase == "charge" and not getattr(enc, "_forced", False):
                    bf.force_outcome(enc, True)
                    enc._forced = True
                if phase == "clear" and not pressed:
                    enc.handle_event(("B", None))
                    pressed = True
                enc.update()
                enc.draw(surface)
                self.env.clock_ms += 33
                if self.env.rg.game_state_update:
                    break
        self.assertTrue(pressed, "the boss win went through its CLEAR")
        self.assertEqual(enc.victory_status, "Victory")
        self.assertGreater(gg.battle_area.get("DMC", 1), before, "the area clear was recorded")

    # ------------------------------------------------------------ 18a
    def test_an_older_area_leaves_the_saved_round_alone(self):
        gg = self.env.gg
        for area, round_num, win in ((1, 1, True), (1, self.boss_round("DMM"), True), (1, 1, False)):
            with self.subTest(area=area, round=round_num, win=win):
                enc, _ = self.encounter("DMM", area, round_num)
                gg.battle_area["DMM"], gg.battle_round["DMM"] = 3, 2
                result = bf.run_round(self.env, enc, win=win, skip_battle=True)
                self.assertEqual(result["victory"], "Victory" if win else "Defeat")
                self.assertEqual((gg.battle_area["DMM"], gg.battle_round["DMM"]), (3, 2))

    def test_the_furthest_area_still_moves_its_round(self):
        gg = self.env.gg
        enc, _ = self.encounter("DMM", 2, 1)
        gg.battle_area["DMM"], gg.battle_round["DMM"] = 2, 1
        bf.run_round(self.env, enc, win=True, skip_battle=True)
        self.assertEqual((gg.battle_area["DMM"], gg.battle_round["DMM"]), (2, 2))
        enc, _ = self.encounter("DMM", 2, 2)
        gg.battle_area["DMM"], gg.battle_round["DMM"] = 2, 2
        bf.run_round(self.env, enc, win=False, skip_battle=True)
        self.assertEqual(gg.battle_round["DMM"], 1, "a loss there is back to round 1")

    # ------------------------------------------------------------ 18b
    def test_the_result_exp_includes_the_bonus(self):
        import battle.battle_encounter as encounter_module
        texts = []
        real_label = encounter_module.Label

        def label(*args, **kwargs):
            texts.append(args[2] if len(args) > 2 else kwargs.get("text"))
            return real_label(*args, **kwargs)
        from utils.module_utils import get_module
        # D-3 shows Level and Exp on the result; its last area pays enough
        # experience for a bonus of at least 1.
        last_area = max(get_module("D-3").get_area_round_counts())
        enc, pet = self.encounter("D-3", last_area, 1)
        pet.level = 1
        with patch.object(encounter_module, "Label", label):
            result = bf.run_round(self.env, enc, win=True, skip_battle=True)
        snap = result["snapshot"]
        self.assertGreater(snap["bonus"], 0, "every pet alive earns the bonus")
        self.assertIn(f"Exp +{snap['xp'] + snap['bonus']}", texts)

    # ------------------------------------------------------------ 19
    def test_the_pvp_scene_leaves_the_result_to_the_encounter(self):
        from scenes.scene_battle_pvp import SceneBattlePvP
        scene = SceneBattlePvP.__new__(SceneBattlePvP)
        scene.battle_encounter = Mock(phase="result", replay_return=None)
        self.env.rg.game_state_update = False
        for action in ("A", "B", "START"):
            scene.handle_event((action, None))
            scene.battle_encounter.handle_event.assert_called_with((action, None))
        self.assertFalse(self.env.rg.game_state_update, "the scene did not leave over the result")


if __name__ == "__main__":
    unittest.main()
