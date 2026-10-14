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

    def _battle(self, seed):
        from battle.arena import engine
        catalog = engine.Catalog(MODULES)
        installed = set(self.rg.game_modules)
        modules = [m for m in catalog.names() if m in installed]
        rng = random.Random(seed)
        while True:
            teams = []
            for _ in range(2):
                module = rng.choice(modules)
                try:
                    entries, _ = engine.validate_team(catalog, engine.random_team(
                        catalog, rng.randrange(10 ** 6), {"allowed_modules": [module]}))
                except engine.ArenaError:
                    break
                teams.append(entries)
            if len(teams) == 2 and all(len(t) == 3 for t in teams):
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


if __name__ == "__main__":
    unittest.main()
