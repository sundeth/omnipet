"""Arena views against the fake Omninet: hub, team creation, battles,
history, replays and the end of a season.

Protects ARN-05 (a team is exactly three pets; creating it moves them into
the freezer locked until the season ends, the upload names the species and
carries only care status; pets never leave the save; a season the server
reports completed releases them), ARN-07 (the results and history views,
and replays opened from the hub or from history return where they came
from) and the reward side of a finished season (coins claimed once, the
local balance mirrors the server's). The fake fights battles with the
game's own arena engine (src/battle/arena/engine.py), as the server does.
Replay playback itself is covered by tests/game/battle/test_arena_replay_scene.py;
here the replay scene is entered and left.

Checklist: ONL-03 (Arena works against a server), ARN-05, ARN-07.
"""
import os
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "support"))
sys.path.insert(0, HERE)
MODULES = os.path.join(REPO_ROOT, "modules")
ARENA_MODULES = ["DMC", "PENC", "IC", "VB"]       # the harness party's modules

from fake_omninet import (FakeOmninet, isolate_client, login_service, reset_service,  # noqa: E402
                          wait_for)
from online_ui import (button, connect, freezer_pets, labels, progress_mode,  # noqa: E402
                       scene_name, settle, tap_button, tap_pet, view)


@unittest.skipUnless(all(os.path.isdir(os.path.join(MODULES, m)) for m in ARENA_MODULES),
                     "party modules not present")
class OnlineArenaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness import Env
        cls.env = Env("240x240", network="local")
        cls.fake = FakeOmninet(arena_modules=ARENA_MODULES).start()
        cls._iso = isolate_client(cls.env, cls.fake, timeout=3.0)
        cls.svc = cls._iso.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls._iso.__exit__(None, None, None)
        cls.fake.stop()

    def setUp(self):
        env, fake = self.env, self.fake
        env.reset(input_mode=env.rg.TOUCH_MODE)
        fake.clear_faults()
        fake.reset_log()
        for s in fake.seasons:
            s["status"] = "completed"
        fake.teams.clear()
        fake.battles.clear()
        reset_service(self.svc)
        self.season = fake.start_season(f"Season {len(fake.seasons) + 1}", days=7)
        self.rival_acc, self.rival = fake.add_opponent_team("Rival", seed=7, modules=["DMC"])
        self.acc = fake.add_account(f"Arena{len(fake.accounts)}", coins=100)
        login_service(self.svc, fake, self.acc)
        progress_mode(env, self.acc["id"])
        env.gg.coins = 100
        with __import__("harness").quiet():
            env.gg.save()

    def tearDown(self):
        tracebacks = [l for l in self.env.logs if "Traceback" in l]
        self.assertEqual(tracebacks, [], "a scene or view logged a traceback")

    # ------------------------------------------------------------ helpers
    def _arena(self):
        game = connect(self.env, "arena")
        v = game.scene.current_view
        self.assertTrue(settle(self.env, game, lambda: not v._loading), "the arena never loaded")
        return game, v

    def _create_team(self):
        """CREATE TEAM, three pets tapped, CONFIRM; back on the hub."""
        env = self.env
        game, hub = self._arena()
        tap_button(env, game, "CREATE TEAM")
        self.assertEqual(view(game), "arena_team_creation")
        v = game.scene.current_view
        self.assertTrue(settle(env, game, lambda: v._server_modules is not None),
                        "arena modules never arrived")
        self.assertEqual(v._server_modules, set(ARENA_MODULES))
        self.assertFalse(v.confirm_button.enabled)
        self.chosen = list(env.gg.pet_list[:3])
        for i in range(3):
            tap_pet(env, game, v.pet_selector, i)
        self.assertEqual(v._selected_pet_indices, [0, 1, 2])
        self.assertTrue(v.confirm_button.enabled)
        tap_button(env, game, "CONFIRM", frames=0)
        self.assertTrue(wait_for(lambda: view(game) == "arena"), "team creation never returned")
        hub = game.scene.current_view
        self.assertTrue(settle(env, game, lambda: not hub._loading))
        return game, hub

    def _my_team(self):
        return next(t for t in self.fake.teams.values() if t["owner"] == self.acc["id"])

    # ------------------------------------------------------------ hub
    def test_the_hub_opens_from_the_connect_menu_and_offers_a_team(self):
        env = self.env
        game = connect(env)
        menu = game.scene.current_view
        self.assertTrue(menu.arena_button.enabled, "Arena is off for a logged-in Progress player")
        env.tap(game, menu.arena_button.rect.center)
        env.frames(game, 2)
        self.assertEqual(view(game), "arena")
        hub = game.scene.current_view
        self.assertTrue(settle(env, game, lambda: not hub._loading))
        self.assertTrue(button(game, "CREATE TEAM").enabled)
        self.assertFalse(hub.find_button.enabled)
        self.assertFalse(hub.history_button.enabled)
        self.assertTrue(hub.rules_button.enabled)
        self.assertTrue(hub.time_label.text.startswith("TIME LEFT: 6 DAYS"), hub.time_label.text)

    def test_creating_a_team_locks_its_pets_in_the_freezer(self):
        """ARN-05."""
        env = self.env
        game, hub = self._create_team()
        team = self._my_team()
        # the upload names the species and carries care status only
        upload = self.fake.calls("/api/v1/teams", "POST")[-1][2]["pets"]
        self.assertEqual([(p["name"], p["module_name"]) for p in upload],
                         [(p.name, p.module) for p in self.chosen])
        for p in upload:
            self.assertFalse({"power", "hp", "attribute", "stage", "atk_main"} & set(p))
        # pets left the party for the freezer, still in the save, locked
        self.assertEqual(len(env.gg.pet_list), 1)
        frozen = freezer_pets(env)
        self.assertEqual(sorted(p.name for p in frozen), sorted(p.name for p in self.chosen))
        until = self.season["ends_at"].timestamp()
        for pet in frozen:
            self.assertEqual(pet.arena_lock["team_id"], team["id"])
            self.assertAlmostEqual(pet.arena_lock["until"], until, delta=1)
            self.assertTrue(env.gg.is_pet_arena_locked(pet))
        # the hub shows the team
        self.assertEqual([lbl.text for lbl in hub.pet_labels], [p.name[:7] if len(p.name) <= 7
                                                                else p.name[:6] + "." for p in self.chosen])
        self.assertEqual(hub.find_button.text, "FIND BATTLE (10 LEFT)")
        self.assertTrue(hub.history_button.enabled)
        self.assertIsNone(button(game, "CREATE TEAM"))

    def test_a_pet_the_server_cannot_field_is_disabled_in_the_picker(self):
        env = self.env
        self.fake._arena_names = ["DMC"]
        self.fake._arena_catalog = None
        try:
            game, _hub = self._arena()
            tap_button(env, game, "CREATE TEAM")
            v = game.scene.current_view
            self.assertTrue(settle(env, game, lambda: v._server_modules is not None))
            self.assertEqual(v.pet_selector.enabled_pets, [0])
            self.assertEqual(set(v._reject_reasons.values()), {"Module not in this arena season"})
        finally:
            self.fake._arena_names = list(ARENA_MODULES)
            self.fake._arena_catalog = None

    def test_find_battle_plays_the_replay_and_comes_back_to_the_hub(self):
        env = self.env
        game, hub = self._create_team()
        tap_button(env, game, "FIND BATTLE (10 LEFT)", frames=0)
        self.assertTrue(wait_for(lambda: env.rg.game_state == "battle_pvp"
                                 or hub.status_label.text not in ("", "Finding battle...")),
                        "find battle never answered")
        self.assertEqual(env.rg.game_state, "battle_pvp", hub.status_label.text)
        replay = env.rg.pvp_battle_data["arena_replay"]
        self.assertEqual(replay["return_view"], "arena")
        env.frames(game, 2)
        self.assertEqual(scene_name(game), "SceneBattlePvP")
        team = self._my_team()
        self.assertEqual(team["attacks_today"], 1)
        game.scene.battle_encounter.finish_replay()
        env.frames(game, 2)
        self.assertEqual(view(game), "arena")
        hub = game.scene.current_view
        self.assertTrue(settle(env, game, lambda: not hub._loading))
        self.assertEqual(hub.find_button.text, "FIND BATTLE (9 LEFT)")
        self.assertEqual(hub.score_value.value_text, str(team["score"]))

    def test_no_attacks_left_today_disables_find_battle(self):
        """ARN-06 client side: the hub shows the server's daily allowance."""
        env = self.env
        self._create_team()
        from fake_omninet import MAX_DAILY_BATTLES
        self._my_team()["attacks_today"] = MAX_DAILY_BATTLES
        game, hub = self._arena()
        self.assertEqual(hub.find_button.text, "FIND BATTLE (0 LEFT)")
        self.assertFalse(hub.find_button.enabled)
        env.tap(game, hub.find_button.rect.center)
        env.frames(game, 1)
        self.assertEqual(self.fake.calls("/api/v1/battles/find"), [])

    def test_history_lists_attacks_and_defences_and_watch_returns_to_it(self):
        """ARN-07."""
        env, fake = self.env, self.fake
        game, hub = self._create_team()
        mine = self._my_team()
        attack = fake.fight(mine, self.rival)               # we attacked
        defence = fake.fight(self.rival, mine)              # we were attacked
        self.assertTrue(hub.history_button.enabled)
        game.scene._change_view("arena")                    # refresh the hub
        hub = game.scene.current_view
        settle(env, game, lambda: not hub._loading)
        tap_button(env, game, "HISTORY")
        self.assertEqual(view(game), "arena_history")
        hist = game.scene.current_view
        self.assertTrue(settle(env, game, lambda: hist._battles))
        rows = [lbl.text for lbl in hist._row_labels if lbl.visible]
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[0].startswith(">"))
        self.assertIn("Rival", rows[0])
        roles = sorted(next(t for t in r.split() if ":" in t).split(":")[0] for r in rows)
        self.assertEqual(roles, ["A", "D"])
        self.assertEqual({b["id"] for b in hist._battles}, {attack["id"], defence["id"]})
        hist.handle_event(("DOWN", None))
        self.assertEqual(hist._selected_index, 1)
        tap_button(env, game, "WATCH", frames=0)
        self.assertTrue(wait_for(lambda: env.rg.game_state == "battle_pvp"
                                 or hist.status_label.text not in ("", "Loading battle...")))
        self.assertEqual(env.rg.game_state, "battle_pvp", hist.status_label.text)
        data = env.rg.pvp_battle_data["arena_replay"]
        self.assertEqual(data["return_view"], "arena_history")
        self.assertEqual(data["return_kwargs"]["team_id"], mine["id"])
        env.frames(game, 2)
        game.scene.battle_encounter.finish_replay()
        env.frames(game, 2)
        self.assertEqual(view(game), "arena_history")
        hist = game.scene.current_view
        self.assertEqual(hist._team_id, mine["id"])
        self.assertTrue(settle(env, game, lambda: hist._battles))

    def test_a_finished_season_shows_results_pays_once_and_frees_the_pets(self):
        """ARN-05 release + ARN-07 results + the season reward."""
        env, fake = self.env, self.fake
        self._create_team()
        mine = self._my_team()
        fake.fight(mine, self.rival)
        fake.end_season(self.season)
        reward = mine["rewarded_coins"]
        self.assertGreater(reward, 0)
        game, hub = self._arena()
        # the server said completed: the locks are gone before their date
        for pet in freezer_pets(env):
            self.assertIsNone(pet.arena_lock, f"{pet.name} still locked after the season ended")
        self.assertEqual(hub.find_button.text, "SEASON RESULTS")
        self.assertIn(f"{self.season['name']} has ended.", labels(game))
        self.assertFalse(hub.history_button.enabled)
        tap_button(env, game, "SEASON RESULTS")
        self.assertEqual(view(game), "arena_reclaim")
        shown = labels(game)
        self.assertIn(f"Rank: {mine['final_rank']}", shown)
        self.assertIn(f"Reward: {reward} coins", shown)
        env.tap(game, (120, 120))                           # any tap dismisses
        self.assertTrue(wait_for(lambda: view(game) == "arena"), "results never closed")
        hub = game.scene.current_view
        self.assertTrue(settle(env, game, lambda: not hub._loading))
        self.assertTrue(mine["reward_claimed"])
        self.assertEqual(fake.account(self.acc)["coins"], 100 + reward)
        self.assertEqual(env.gg.coins, 100 + reward)
        self.assertEqual(hub.time_label.text, "No active season")
        self.assertEqual(len(fake.calls("/api/v1/teams/claim-rewards")), 1)
        env.tap(game, (120, 120))
        env.frames(game, 2)
        self.assertEqual(len(fake.calls("/api/v1/teams/claim-rewards")), 1, "claimed twice")

    # BUG online-results-without-pets: the results takeover reads the team's
    # pets from GET /teams?include_past=true, whose rows (TeamListResponse)
    # carry only pet_count, so the finished team is shown without its pets.
    # Fixed 2026-10-14; kept as a regression test.
    def test_the_results_takeover_names_the_finished_teams_pets(self):
        self._create_team()
        mine = self._my_team()
        self.fake.fight(mine, self.rival)
        self.fake.end_season(self.season)
        _game, hub = self._arena()
        self.assertEqual(hub.find_button.text, "SEASON RESULTS")
        self.assertEqual([lbl.text for lbl in hub.pet_labels if lbl.text],
                         [e["name"][:7] if len(e["name"]) <= 7 else e["name"][:6] + "."
                          for e in mine["entries"]])

    def test_a_lock_past_its_date_frees_the_pet_without_the_server(self):
        """No pet stays locked past its season even if Omninet never answers."""
        env = self.env
        self._create_team()
        pets = freezer_pets(env)
        self.assertTrue(pets)
        later = self.season["ends_at"].timestamp() + 1
        for pet in pets:
            self.assertTrue(env.gg.is_pet_arena_locked(pet, now=time.time()))
            self.assertFalse(env.gg.is_pet_arena_locked(pet, now=later))


if __name__ == "__main__":
    unittest.main()
