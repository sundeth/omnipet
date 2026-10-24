# -*- coding: utf-8 -*-
"""One simulated player running the real game, headless, through the UI.

Started by ``run_seasons.py`` as its own process (one game instance each).
It boots Omnipet with ``tests/support/harness.Env`` (SDL dummy drivers, a
fake clock, sockets limited to this machine), logs in to the simulation
server with a device key and then obeys one JSON command per stdin line,
answering one JSON line on stdout. Every action goes through the arena
screens with taps, as a player would: the hub, team creation, FIND BATTLE
with the replay played to its end in the battle scene, history and
defence replays, the ranks table, rules and the season results.

Commands: boot, prepare, create_team, attack, history, ranks, rules,
results, evolve, state, quit. See ``Player.cmd_<name>``.
"""
import contextlib
import io
import json
import os
import random
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import simlib  # noqa: E402  (sets sys.path for src/ and tests/support)

REAL_STDOUT = sys.stdout


def reply(obj):
    REAL_STDOUT.write(json.dumps(obj, default=str) + "\n")
    REAL_STDOUT.flush()


class Player:
    def __init__(self):
        self.env = None
        self.svc = None
        self.game = None
        self.rng = random.Random()
        self.shots = None
        self.name = "?"

    # ------------------------------------------------------------ helpers
    def ui(self):
        import online_ui
        return online_ui

    def shot(self, label):
        if not self.shots:
            return None
        import pygame
        os.makedirs(self.shots, exist_ok=True)
        path = os.path.join(self.shots, f"{time.strftime('%H%M%S')}_{self.name}_{label}.png")
        try:
            pygame.image.save(self.env.rg.render_surface, path)
        except Exception:  # pylint: disable=broad-except
            return None
        return path

    def hub(self):
        """A fresh game on the arena hub, loaded."""
        ui = self.ui()
        self.game = ui.connect(self.env, "arena")
        v = self.game.scene.current_view
        if not ui.settle(self.env, self.game, lambda: not v._loading, timeout=60):
            raise RuntimeError("the arena hub never loaded")
        self.env.frames(self.game, 2)
        return v

    def labels(self):
        return [t for t in self.ui().labels(self.game) if t]

    def wait_view(self, name, timeout=60):
        ui = self.ui()
        if not ui.wait_for(lambda: ui.view(self.game) == name, timeout):
            raise RuntimeError(f"view {name!r} never opened (at {ui.view(self.game)!r})")
        self.env.frames(self.game, 2)
        return self.game.scene.current_view

    def freezer(self):
        return self.ui().freezer_pets(self.env)

    # ------------------------------------------------------------ commands
    def cmd_boot(self, device_key, nickname, seed=0, shots=None):
        from harness import Env, quiet
        from fake_omninet import isolate_client
        self.name = nickname
        self.shots = shots
        self.rng = random.Random(seed)
        self.env = Env("240x240", network=simlib.network_mode())
        self.env.reset(input_mode=self.env.rg.TOUCH_MODE)
        self._iso = isolate_client(self.env, simlib.URL, timeout=60)
        self.svc = self._iso.__enter__()
        self.svc._device_key = device_key
        with quiet():
            ok, msg, info = self.svc.validate_device()
        if not ok:
            raise RuntimeError(f"login failed: {msg}")
        self.ui().progress_mode(self.env, self.svc.get_player_id())
        gg = self.env.gg
        gg.pet_list = []
        gg.coins = int((info or {}).get("coins") or 0)
        with quiet():
            gg.save()
        return {"player_id": self.svc.get_player_id(), "coins": gg.coins}

    def cmd_prepare(self, season, server_modules, size, veteran=True, exclude=()):
        """Make the party the pets this season needs: *size*+1 eligible
        pets (raised as needed) and, when one exists, a veteran that fought
        in its current form, to see the picker refuse it."""
        from harness import quiet
        import players
        from players import Catalog, make_pet
        players.DRIFTED.update(tuple(x) for x in exclude or ())
        from scenes.connect_views.arena_team_creation_view import _pet_passes
        from utils import arena_pets
        gg = self.env.gg
        restrictions = season.get("restrictions") or {}
        catalog = Catalog(server_modules)
        everyone = list(gg.pet_list) + [p for p in self.freezer()
                                        if not gg.is_pet_arena_locked(p)]
        # A species the server holds other data for stays out of the party.
        everyone = [p for p in everyone
                    if (getattr(p, "module", None), p.name, getattr(p, "version", None))
                    not in players.DRIFTED]
        eligible = [p for p in everyone
                    if _pet_passes(p, restrictions, set(server_modules), season.get("id"))[0]]
        veterans = [p for p in everyone if arena_pets.fought_form(p, season.get("id"))]
        cap = gg.configuration.max_pets
        want = min(cap - (1 if veteran and veterans else 0), size + 1)
        options = catalog.matching(restrictions)
        while len(eligible) < want and options:
            module, monster = self.rng.choice(options)
            eligible.append(make_pet(module, monster, self.rng))
        party = eligible[:want] + (veterans[:1] if veteran else [])
        party = party[:cap]
        # Everyone else waits in the freezer.
        with quiet():
            stay = [p for p in gg.pet_list if not any(p is q for q in party)]
            frozen = self.freezer()
            new_in_party = [p for p in party if not any(p is q for q in gg.pet_list)]
            # Pets coming out of the freezer leave it.
            if any(any(p is q for q in frozen) or any(p.uid == getattr(q, "uid", None) for q in frozen)
                   for p in new_in_party):
                self._remove_from_freezer([p for p in new_in_party])
            if stay:
                gg.freezer_deposit_pets(stay)
            gg.pet_list = party
            from utils.pet_utils import refresh_pet_sizes
            refresh_pet_sizes()
            gg.save()
        return {"party": [f"{p.name}/{p.module} s{p.stage}" for p in party],
                "party_species": [[p.module, p.name, p.version] for p in party],
                "veteran": veterans[0].name if veterans and veteran else None}

    def _remove_from_freezer(self, pets):
        import pickle
        path = os.path.join(self.env.gg.get_save_dir(), "freezer.pkl")
        if not os.path.exists(path):
            return
        with open(path, "rb") as f:
            pages = pickle.load(f) or []
        uids = {getattr(p, "uid", None) for p in pets} - {None}
        for page in pages:
            page.pets = [p for p in (getattr(page, "pets", None) or [])
                         if getattr(p, "uid", None) not in uids]
        with open(path, "wb") as f:
            pickle.dump(pages, f)

    def cmd_create_team(self, size, probe_veteran=True):
        ui = self.ui()
        env = self.env
        hub = self.hub()
        out = {"hub_labels": self.labels(), "claimed_first": []}
        # Results of a finished season come first, as for any player.
        for _ in range(3):
            if hub.find_button.text != "SEASON RESULTS":
                break
            claimed = self.cmd_results()
            out["claimed_first"].append({k: claimed.get(k) for k in ("ok", "coins_before", "coins_after")})
            hub = self.hub()
        if ui.button(self.game, "CREATE TEAM") is None:
            return dict(out, ok=False, error="no CREATE TEAM button")
        ui.tap_button(env, self.game, "CREATE TEAM")
        v = self.wait_view("arena_team_creation")
        ui.settle(env, self.game, lambda: v._server_modules is not None, timeout=60)
        out["rules_line"] = v.status_label.text
        out["slots"] = v.team_display.SLOTS
        enabled = list(v.pet_selector.enabled_pets)
        out["enabled"] = len(enabled)
        out["reasons"] = sorted(set(v._reject_reasons.values()))
        if probe_veteran and v._reject_reasons:
            idx = next(iter(v._reject_reasons))
            ui.tap_pet(env, self.game, v.pet_selector, idx)
            out["refused_tap"] = v.status_label.text
        if len(enabled) < size:
            self.shot("team_short")
            return dict(out, ok=False, error=f"{len(enabled)} eligible for {size}")
        for idx in enabled[:size]:
            ui.tap_pet(env, self.game, v.pet_selector, idx)
        out["selected"] = list(v._selected_pet_indices)
        if not v.confirm_button.enabled:
            self.shot("confirm_disabled")
            return dict(out, ok=False, error="CONFIRM stayed disabled")
        chosen = [v.pet_selector.pets[i] for i in v._selected_pet_indices]
        ui.tap_button(env, self.game, "CONFIRM")
        out["confirm_warning"] = v.status_label.text
        self.shot("team_confirm")
        ui.tap_button(env, self.game, "SURE?", frames=0)
        if not ui.wait_for(lambda: ui.view(self.game) == "arena"
                           or (not v._submitting and v.status_label.text != "Registering team..."),
                           60):
            return dict(out, ok=False, error="registration never answered")
        if ui.view(self.game) != "arena":
            env.frames(self.game, 2)
            self.shot("team_refused")
            return dict(out, ok=False, error=v.status_label.text)
        hub = self.game.scene.current_view
        ui.settle(env, self.game, lambda: not hub._loading, timeout=60)
        env.frames(self.game, 2)
        self.shot("hub_after_team")
        frozen = self.freezer()
        locked = [p for p in frozen if any(p is c or getattr(p, "uid", 1) == getattr(c, "uid", 2)
                                           for c in chosen)]
        out.update(ok=True, notice=hub.status_label.text, find=hub.find_button.text,
                   pets=[p.name for p in chosen],
                   locked=[bool(env.gg.is_pet_arena_locked(p)) for p in locked],
                   in_party_after=[p.name for p in env.gg.pet_list],
                   rank=hub.rank_value.value_text, team_display=hub.team_display.visible)
        return out

    def _play_replay(self, max_frames=40000):
        """Run the battle scene to its result and back; returns the check."""
        ui = self.ui()
        env, game = self.env, self.game
        env.frames(game, 2)
        if ui.scene_name(game) != "SceneBattlePvP":
            return {"played": False, "scene": ui.scene_name(game)}
        enc = game.scene.battle_encounter
        frames = 0
        while frames < max_frames and enc.phase != "result":
            env.frames(game, 20)
            frames += 20
        log = enc.global_battle_log
        check = {"played": enc.phase == "result", "frames": frames,
                 "victory": enc.victory_status}
        if log is not None:
            mine = [max(0, h) for h in enc.battle_player.team1_hp]
            theirs = [max(0, h) for h in enc.battle_player.team2_hp]
            want1 = [s.hp for s in log.device1_final]
            want2 = [s.hp for s in log.device2_final]
            # A side with fewer Digimon has empty lanes, at zero.
            check.update(
                sizes=[len(want1), len(want2)],
                hp_ok=(mine[:len(want1)] == want1 and theirs[:len(want2)] == want2
                       and not any(mine[len(want1):]) and not any(theirs[len(want2):])),
                hp_scene=[mine, theirs],
                hp_log=[[s.hp for s in log.device1_final], [s.hp for s in log.device2_final]],
                verdict_ok=enc.victory_status == {"device1": "Victory", "device2": "Defeat"}.get(
                    log.winner, "Draw"))
        self.shot("replay_result")
        # Let the result screen hand back to the arena by itself.
        returned = False
        for i in range(600):
            env.frames(game, 5)
            if ui.scene_name(game) == "SceneConnect":
                returned = True
                break
            if i % 40 == 39:
                env.press(game, "A")
        if not returned:
            enc.finish_replay()
            env.frames(game, 2)
        check["returned_by_itself"] = returned
        return check

    def cmd_attack(self, times=1):
        ui = self.ui()
        env = self.env
        results = []
        for _ in range(times):
            hub = self.hub()
            text = hub.find_button.text
            if not hub.find_button.enabled:
                results.append({"ok": False, "button": text, "info": hub.info_label.text})
                break
            ui.tap_button(env, self.game, text, frames=0)
            if not ui.wait_for(lambda: env.rg.game_state == "battle_pvp"
                               or hub.status_label.text not in ("", "Finding an opponent..."), 60):
                results.append({"ok": False, "error": "find battle never answered"})
                break
            if env.rg.game_state != "battle_pvp":
                env.frames(self.game, 2)
                results.append({"ok": False, "status": hub.status_label.text})
                break
            check = self._play_replay()
            back = self.game.scene.current_view if ui.scene_name(self.game) == "SceneConnect" else None
            if back is not None and hasattr(back, "_loading"):
                ui.settle(env, self.game, lambda: not back._loading, timeout=60)
                env.frames(self.game, 2)
                check["notice"] = back.status_label.text
                check["after_button"] = back.find_button.text
                check["score"] = back.score_value.value_text
                check["record"] = back.record_value.value_text
                check["info"] = back.info_label.text
                self.shot("hub_after_battle")
            results.append(dict(check, ok=True, button=text))
        return {"attacks": results}

    def cmd_history(self, watch_role="defense"):
        ui = self.ui()
        env = self.env
        hub = self.hub()
        if not hub.history_button.enabled:
            return {"ok": False, "error": "HISTORY disabled"}
        ui.tap_button(env, self.game, "HISTORY")
        v = self.wait_view("arena_history")
        ui.settle(env, self.game, lambda: not v._loading, timeout=60)
        env.frames(self.game, 2)
        rows = list(v._battles)
        out = {"ok": True, "rows": len(rows),
               "attacks": sum(1 for r in rows if r.get("role") == "attack"),
               "defences": sum(1 for r in rows if r.get("role") != "attack"),
               "first_lines": [lbl.text for lbl in v._row_labels if lbl.visible][:3],
               "detail": v.detail_label.text}
        self.shot("history")
        target = next((i for i, r in enumerate(rows) if (r.get("role") == "attack") ==
                       (watch_role == "attack")), None)
        if target is None:
            return dict(out, watched=None)
        while v._selected_index < target:
            env.press(self.game, "DOWN")
        env.frames(self.game, 1)
        ui.tap_button(env, self.game, "WATCH", frames=0)
        if not ui.wait_for(lambda: env.rg.game_state == "battle_pvp"
                           or v.status_label.text not in ("", "Loading battle..."), 60):
            return dict(out, watched={"error": "never loaded"})
        if env.rg.game_state != "battle_pvp":
            return dict(out, watched={"error": v.status_label.text})
        check = self._play_replay()
        check["back_to"] = ui.view(self.game)
        return dict(out, watched=dict(check, role=rows[target].get("role")))

    def cmd_ranks(self):
        ui = self.ui()
        env = self.env
        hub = self.hub()
        if not hub.ranks_button.enabled:
            return {"ok": False, "error": "RANKS disabled"}
        ui.tap_button(env, self.game, "RANKS")
        v = self.wait_view("arena_standings")
        ui.wait_for(lambda: not v._loading and v._rows is not None, 60)
        ui.wait_for(lambda: bool(v._rows) or v.status_label.text not in ("Loading ranks...",), 60)
        env.frames(self.game, 2)
        self.shot("ranks")
        mine = next((r for r in v._rows if r.get("is_you")), None)
        return {"ok": True, "rows": len(v._rows), "mine": mine,
                "lines": [lbl.text for lbl in v._row_labels if lbl.visible]}

    def cmd_rules(self):
        ui = self.ui()
        hub = self.hub()
        ui.tap_button(self.env, self.game, "RULES")
        self.wait_view("arena_rules")
        self.shot("rules")
        return {"ok": True, "labels": self.labels()}

    def cmd_results(self):
        """The finished season: SEASON RESULTS, claim, pets released."""
        ui = self.ui()
        env = self.env
        gg = env.gg
        before = {p.uid: (int(getattr(p, "pvp_battles", 0) or 0), int(getattr(p, "pvp_wins", 0) or 0))
                  for p in self.freezer() + list(gg.pet_list) if getattr(p, "uid", None)}
        coins_before = gg.coins
        hub = self.hub()
        out = {"hub_button": hub.find_button.text, "hub_status": hub.status_label.text,
               "hub_info": hub.info_label.text}
        self.shot("hub_season_over")
        after_pets = {p.uid: p for p in self.freezer() + list(gg.pet_list) if getattr(p, "uid", None)}
        out["records_added"] = {
            p.name: [int(getattr(p, "pvp_battles", 0) or 0) - before.get(uid, (0, 0))[0],
                     int(getattr(p, "pvp_wins", 0) or 0) - before.get(uid, (0, 0))[1]]
            for uid, p in after_pets.items()
            if (int(getattr(p, "pvp_battles", 0) or 0), int(getattr(p, "pvp_wins", 0) or 0))
            != before.get(uid, (0, 0))}
        out["still_locked"] = [p.name for p in self.freezer() if gg.is_pet_arena_locked(p)]
        out["still_pending"] = [p.name for p in after_pets.values()
                                if getattr(p, "arena_pending", None)]
        if hub.find_button.text != "SEASON RESULTS":
            return dict(out, ok=False, error="no SEASON RESULTS")
        ui.tap_button(env, self.game, "SEASON RESULTS")
        v = self.wait_view("arena_reclaim")
        out["results_screen"] = self.labels()
        self.shot("results")
        env.press(self.game, "A")
        if not ui.wait_for(lambda: ui.view(self.game) == "arena", 60):
            return dict(out, ok=False, error="results never closed")
        hub = self.game.scene.current_view
        ui.settle(env, self.game, lambda: not hub._loading, timeout=60)
        env.frames(self.game, 2)
        self.shot("hub_after_results")
        out.update(ok=True, coins_before=coins_before, coins_after=gg.coins,
                   hub_after=hub.find_button.text, notice_after=hub.status_label.text,
                   create_visible=ui.button(self.game, "CREATE TEAM") is not None)
        return out

    def cmd_evolve(self, chance=0.7):
        """Evolve released veterans (party and freezer)."""
        from harness import quiet
        from utils.module_utils import get_module
        import pickle
        gg = self.env.gg
        evolved = []
        path = os.path.join(gg.get_save_dir(), "freezer.pkl")
        pages = []
        if os.path.exists(path):
            with open(path, "rb") as f:
                pages = pickle.load(f) or []
        pets = list(gg.pet_list) + [p for page in pages for p in (getattr(page, "pets", None) or [])]
        with quiet():
            for pet in pets:
                if getattr(pet, "arena_pending", None) or gg.is_pet_arena_locked(pet):
                    continue
                if not getattr(pet, "arena_history", None) or self.rng.random() > chance:
                    continue
                module = get_module(pet.module)
                data = module.get_monster(pet.name, pet.version) if module else None
                targets = [e.get("to") for e in (data or {}).get("evolve", [])
                           if e.get("to") and module.get_monster(e.get("to"), pet.version)]
                if targets:
                    before = pet.name
                    if pet.evolve_to(self.rng.choice(targets), pet.version, reward=False) is not False:
                        evolved.append(f"{before}->{pet.name}")
            if pages:
                with open(path, "wb") as f:
                    pickle.dump(pages, f)
            gg.save()
        return {"evolved": evolved}

    def cmd_state(self):
        gg = self.env.gg
        def row(p):
            return {"name": p.name, "module": p.module, "stage": p.stage,
                    "uid": getattr(p, "uid", None),
                    "locked": bool(gg.is_pet_arena_locked(p)),
                    "pending": bool(getattr(p, "arena_pending", None)),
                    "pvp": [getattr(p, "pvp_battles", 0), getattr(p, "pvp_wins", 0)],
                    "seasons": len(getattr(p, "arena_history", None) or [])}
        return {"coins": gg.coins, "party": [row(p) for p in gg.pet_list],
                "freezer": [row(p) for p in self.freezer()]}


def main():
    player = Player()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            reply({"ok": False, "error": "bad json"})
            continue
        cmd = msg.pop("cmd", "")
        if cmd == "quit":
            reply({"ok": True, "bye": True})
            break
        handler = getattr(player, f"cmd_{cmd}", None)
        if handler is None:
            reply({"ok": False, "error": f"unknown command {cmd}"})
            continue
        started = time.monotonic()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                result = handler(**msg)
            errors = player.env.error_logs() if player.env else []
            if player.env:
                del player.env.logs[:]
            reply({"ok": True, "result": result, "seconds": round(time.monotonic() - started, 1),
                   "error_logs": [e[:300] for e in errors if "Traceback" in e or "Error" in e][:10]})
        except Exception as exc:  # pylint: disable=broad-except
            reply({"ok": False, "error": repr(exc), "trace": traceback.format_exc()[-2000:],
                   "seconds": round(time.monotonic() - started, 1)})


if __name__ == "__main__":
    main()
