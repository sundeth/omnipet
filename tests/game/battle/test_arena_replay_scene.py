"""Arena replays through the real PvP battle scene end on the server's HP.

The scene plays a stored simulation lane by lane; these battles include
shots re-aimed across lanes, a defender's (enemy-first) view and a lane
running ahead of the others -- the cases that used to drop or misplace
shots. Runs headless on a simulated clock.
"""

import contextlib
import io
import os
import random
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SRC = os.path.join(REPO_ROOT, "src")
for path in (SRC, REPO_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

MODULES = os.path.join(REPO_ROOT, "modules")


@unittest.skipUnless(os.path.isdir(MODULES), "modules folder not present")
class ArenaReplaySceneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._cwd = os.getcwd()
        os.chdir(REPO_ROOT)
        with contextlib.redirect_stdout(io.StringIO()):
            import main
            main.setup_pygame()
            main.setup_display()
            from core import runtime_globals
            from utils.module_utils import load_modules
            from utils.pygame_utils import load_misc_sprites
            runtime_globals.misc_sprites = load_misc_sprites()
            load_modules()
        cls.rg = runtime_globals

    @classmethod
    def tearDownClass(cls):
        os.chdir(cls._cwd)

    def _battle(self, seed, sizes=(3, 3)):
        from battle.arena import engine
        catalog = engine.Catalog(MODULES)
        installed = set(self.rg.game_modules)
        modules = [m for m in catalog.names() if m in installed]
        rng = random.Random(seed)
        while True:
            teams = []
            for size in sizes:
                module = rng.choice(modules)
                try:
                    entries, _ = engine.validate_team(catalog, engine.random_team(
                        catalog, rng.randrange(10 ** 6), {"allowed_modules": [module]},
                        team_size=size), team_size=size)
                except engine.ArenaError:
                    break
                teams.append(entries)
            if len(teams) == 2 and [len(t) for t in teams] == list(sizes):
                break
        outcome = engine.run_battle(teams[0], teams[1], rng.randrange(10 ** 6),
                                    {"charge": "random"})
        return {"team1_id": "A", "team2_id": "B", "battle_log": {
            "version": 2, "rules": outcome["rules"], "hp": outcome["hp"],
            "result": outcome["result"],
            "attacker": {"pets": teams[0]}, "defender": {"pets": teams[1]}}}

    def _replay(self, battle, viewer):
        import pygame
        from scenes.scene_battle_pvp import SceneBattlePvP
        from utils.arena_replay import start_replay
        clock = [0]
        with patch.object(pygame.time, "get_ticks", lambda: clock[0]):
            self.assertIsNone(start_replay(battle, viewer))
            self.rg.game_state = None
            with contextlib.redirect_stdout(io.StringIO()):
                scene = SceneBattlePvP()
            encounter = scene.battle_encounter
            for _ in range(30000):
                clock[0] += 33
                with contextlib.redirect_stdout(io.StringIO()):
                    scene.update()
                    scene.draw(self.rg.render_surface)
                if encounter.phase == "result":
                    break
        self.assertEqual(encounter.phase, "result")
        return encounter

    def test_the_scene_ends_on_the_servers_hp_from_both_seats(self):
        # Seeds whose battles once lost shots: a cross-lane volley stalling a
        # lane, an attacker-first round seen from the defender's seat, and a
        # lane knocking out a Digimon a slower lane still had shooting.
        for seed in (3, 11):
            battle = self._battle(seed)
            for viewer in ("A", "B"):
                with self.subTest(seed=seed, viewer=viewer):
                    encounter = self._replay(battle, viewer)
                    log = encounter.global_battle_log
                    self.assertEqual([max(0, h) for h in encounter.battle_player.team1_hp],
                                     [s.hp for s in log.device1_final])
                    self.assertEqual([max(0, h) for h in encounter.battle_player.team2_hp],
                                     [s.hp for s in log.device2_final])
                    verdict = {"device1": "Victory", "device2": "Defeat"}.get(log.winner, "Draw")
                    self.assertEqual(encounter.victory_status, verdict)


    def test_uneven_teams_replay_from_both_seats(self):
        # Arena teams hold one to three Digimon. The side with fewer gets
        # empty lanes: a viewer outnumbered used to crash the scene, and a
        # lone opponent was drawn as an adventure boss.
        for sizes in ((1, 3), (2, 3), (3, 1)):
            battle = self._battle(5, sizes)
            for viewer in ("A", "B"):
                with self.subTest(sizes=sizes, viewer=viewer):
                    encounter = self._replay(battle, viewer)
                    log = encounter.global_battle_log
                    want1 = [s.hp for s in log.device1_final]
                    want2 = [s.hp for s in log.device2_final]
                    mine = [max(0, h) for h in encounter.battle_player.team1_hp]
                    theirs = [max(0, h) for h in encounter.battle_player.team2_hp]
                    self.assertEqual(mine, want1)
                    self.assertEqual(theirs[:len(want2)], want2)
                    self.assertFalse(any(theirs[len(want2):]))
                    self.assertEqual(len(encounter.enemies), len(want2))
                    verdict = {"device1": "Victory", "device2": "Defeat"}.get(log.winner, "Draw")
                    self.assertEqual(encounter.victory_status, verdict)


if __name__ == "__main__":
    unittest.main()
