# -*- coding: utf-8 -*-
"""Headless game environment shared by the release checks.

Boots the game the way main.py does, with SDL dummy drivers, a throw-away save
folder and sockets refused (nothing reaches Omninet or a device), gives it a
small party and records every sound played and every console line logged.

    env = Env("240x240")
    env.reset()                      # back to the fixture, fresh random seed
    game = env.game("game")          # a VirtualPetGame driving that scene
    env.frames(game, 10)             # update + draw on a fake clock

`reset()` puts the save folder, the save-backed globals and the plain
runtime globals back as they were when the fixture was written, so a crawler
can replay a path from scratch as often as it likes.
"""
import contextlib
import copy
import io
import os
import random
import shutil
import sys
import tempfile
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from paths import ROOT, SRC, temp_dir  # noqa: E402

#: Named starting states (Env._apply_fixture).
FIXTURES = ("default", "room", "sick", "empty", "boot", "replay", "online")
#: (module, version) of the fixture party: one per sprite library.
PARTY = [("DMC", 1), ("PENC", 1), ("IC", 1), ("VB", 1)]
SENTINEL = (255, 0, 254)
FRAME_MS = 33
#: Console lines that mean an exception was caught and logged instead of raised.
ERROR_MARKERS = ("Traceback", "Exception", "Error ", "ERROR", "[!]", "failed", "Failed")


def quiet():
    return contextlib.redirect_stdout(io.StringIO())


class Env:
    def __init__(self, res="240x240", party=PARTY, network=False, fixture="default"):
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        os.environ["SDL_AUDIODRIVER"] = "dummy"
        os.chdir(ROOT)
        for p in (SRC, ROOT):
            if p not in sys.path:
                sys.path.insert(0, p)
        # network=False: every connection refused. network="local": only this
        # machine (a fake Omninet server in tests/support); never a real host.
        if network is not True:
            import socket
            real_create, real_connect = socket.create_connection, socket.socket.connect

            def local(address):
                host = address[0] if isinstance(address, tuple) else address
                return network == "local" and host in ("127.0.0.1", "localhost", "::1")

            def create_connection(address, *a, **k):
                if local(address):
                    return real_create(address, *a, **k)
                raise OSError(f"network disabled by the test harness ({address})")

            def connect(self, address, *a, **k):
                if local(address):
                    return real_connect(self, address, *a, **k)
                raise OSError(f"network disabled by the test harness ({address})")
            socket.create_connection = create_connection
            socket.socket.connect = connect
        self.w, self.h = (int(x) for x in res.split("x"))
        self.sounds, self.logs = [], []
        self.clock_ms = 0
        #: callables run at the end of every reset() (state the save cannot hold)
        self.after_reset = []
        with quiet():
            import pygame
            import main
            from core import game_globals, runtime_globals
            self.pygame, self.gg, self.rg = pygame, game_globals, runtime_globals
            self.save_root = temp_dir("save_")
            game_globals._get_base_save_dir = lambda: self.save_root
            game_globals._can_access_save_dir = lambda: True
            game_globals.game_mode = game_globals.GAME_MODE_FREE
            cfg = game_globals.configuration
            cfg.fullscreen = False
            cfg.screen_width, cfg.screen_height = self.w, self.h
            cfg.window_width, cfg.window_height = self.w, self.h
            main.setup_pygame()
            main.setup_display()
            pygame.time.get_ticks = lambda: self.clock_ms
            from utils.pygame_utils import load_misc_sprites
            from utils.module_utils import load_modules
            runtime_globals.misc_sprites = load_misc_sprites()
            load_modules()
            # The Omninet device credentials live beside the save (computed at
            # import as the cwd-relative save/omninet_device.json): keep them
            # in this run's temporary save folder, never the repository's.
            try:
                from services.omninet_service import omninet_service
                omninet_service._credentials_path = os.path.join(self.save_root, "omninet_device.json")
            except Exception:
                pass
            # The Discord link lives beside the save too (save/discord_data.json):
            # a developer's own linked account must not leak into a test run.
            try:
                from scenes.scene_connect import DiscordModule
                DiscordModule.SAVE_PATH = os.path.join(self.save_root, "discord_data.json")
            except Exception:
                pass
            self._party(party)
            self._apply_fixture(fixture)
            self._hook_sound_and_log()
            game_globals.save()
        self.fixture = temp_dir("fixture_")
        shutil.copytree(self.save_root, self.fixture, dirs_exist_ok=True)
        self._rg_plain = self._plain(runtime_globals)
        self._gg_plain = self._plain(game_globals)
        from vpet import VirtualPetGame
        self.VirtualPetGame = VirtualPetGame

    # ------------------------------------------------------------ setup
    def _party(self, party):
        from models.game_pet import GamePet
        from utils.module_utils import get_module
        gg = self.gg
        gg.pet_list = []
        for mod_name, version in party:
            mod = get_module(mod_name)
            if not mod:
                continue
            child = next((m for m in mod.get_monsters_by_stage(3) if m.get("version") == version), None)
            if child:
                pet = GamePet(dict(child, module=mod_name))
                pet.hunger = pet.strength = 4
                gg.pet_list.append(pet)
        from utils.pet_utils import refresh_pet_sizes
        refresh_pet_sizes()
        gg.game_background = "ver1"
        gg.background_module_name = "DMC"
        gg.show_tutorial = False

    def _apply_fixture(self, fixture):
        """Starting states for the screens the default party cannot reach.

        default  four pets, a full party
        room     three pets: an empty party slot opens egg selection
        sick     one pet sick (Dots) and one injured (Skull): Heal opens
                 the healing scene instead of healing everyone
        empty    no pets at all: the first-run path to an egg
        boot     the default party, for a crawl that starts at the boot scene
        replay   the default party with an arena battle loaded as a replay
                 (the PvP battle scene plays it)
        online   (crawler only: tests/release/menu_crawl.start_fake_omninet)
                 the default party logged in to a fake Omninet server
        """
        pets = self.gg.pet_list
        if fixture == "room":
            del pets[3:]
        elif fixture == "sick":
            for pet, kind in zip(pets[:2], ("sick", "injury")):
                setattr(pet, kind, 2)
                setattr(pet, kind + "_total", 1)
        elif fixture == "empty":
            del pets[:]
        elif fixture == "replay":
            self._arena_replay(seed=3)
        elif fixture not in ("default", "boot", "online"):
            raise ValueError(f"unknown fixture {fixture!r}")
        self.fixture_name = fixture
        from utils.pet_utils import refresh_pet_sizes
        refresh_pet_sizes()

    def _arena_replay(self, seed):
        """Load a fixed-seed arena battle as a replay (runtime_globals.pvp_battle_data),
        the way the arena history opens one; the PvP battle scene plays it."""
        import random as _random
        from battle.arena import engine
        from utils.arena_replay import start_replay
        from paths import MODULES
        catalog = engine.Catalog(MODULES)
        modules = [m for m in catalog.names() if m in self.rg.game_modules]
        rng = _random.Random(seed)
        while True:
            teams = []
            for _ in range(2):
                try:
                    entries, _ = engine.validate_team(catalog, engine.random_team(
                        catalog, rng.randrange(10 ** 6), {"allowed_modules": [rng.choice(modules)]}))
                except engine.ArenaError:
                    break
                teams.append(entries)
            if len(teams) == 2 and all(len(t) == 3 for t in teams):
                break
        outcome = engine.run_battle(teams[0], teams[1], rng.randrange(10 ** 6), {"charge": "random"})
        battle = {"team1_id": "A", "team2_id": "B", "battle_log": {
            "version": 2, "rules": outcome["rules"], "hp": outcome["hp"], "result": outcome["result"],
            "attacker": {"pets": teams[0]}, "defender": {"pets": teams[1]}}}
        problem = start_replay(battle, "A")
        if problem:
            raise RuntimeError(f"arena replay fixture: {problem}")
        self.rg.game_state_update = False

    def _hook_sound_and_log(self):
        rg = self.rg
        real_play = rg.game_sound.play

        def play(name):
            self.sounds.append(name)
            try:
                return real_play(name)
            except Exception:
                return None
        rg.game_sound.play = play
        real_log = rg.game_console.log

        def log(msg, *a, **k):
            self.logs.append(str(msg))
            try:
                return real_log(msg, *a, **k)
            except Exception:
                return None
        rg.game_console.log = log

    @staticmethod
    def _plain(module):
        """Copies of a module's plain values (numbers, strings, containers)."""
        out = {}
        for k, v in vars(module).items():
            if k.startswith("__") or isinstance(v, (types.ModuleType, types.FunctionType, type)):
                continue
            if v is None or isinstance(v, (bool, int, float, str, tuple)):
                out[k] = v
            elif isinstance(v, (list, dict, set)):
                out[k] = copy.copy(v)
        return out

    # ------------------------------------------------------------ per replay
    def reset(self, seed=0, input_mode=None):
        """Back to the fixture: save files, save-backed globals, plain runtime globals."""
        with quiet():
            # Windows keeps a deleted file "delete pending" while a scanner or
            # indexer still holds it, and writing it again is then refused for
            # a moment (a 2026-10-17 release run): retry the restore briefly.
            for attempt in range(6):
                shutil.rmtree(self.save_root, ignore_errors=True)
                try:
                    shutil.copytree(self.fixture, self.save_root, dirs_exist_ok=True)
                    break
                except (shutil.Error, PermissionError):
                    if attempt == 5:
                        raise
                    time.sleep(0.1 * (attempt + 1))
            for k, v in self._gg_plain.items():
                setattr(self.gg, k, copy.copy(v))
            # runtime first: load() reloads every pet's sprites into rg.pet_sprites
            for k, v in self._rg_plain.items():
                setattr(self.rg, k, copy.copy(v))
            self.gg.load()
            cfg = self.gg.configuration
            if (cfg.screen_width, cfg.screen_height) != (self.w, self.h) or \
                    self.rg.render_surface.get_size() != (self.w, self.h):
                cfg.fullscreen = False
                cfg.screen_width, cfg.screen_height = self.w, self.h
                cfg.window_width, cfg.window_height = self.w, self.h
                from utils import display_utils
                self.pygame.display.set_mode((self.w, self.h))
                display_utils._rebuild_render_surface()
            self.rg.game_message.messages = []
            self.rg.game_message.slide_queue = []
            self.rg.game_message.current_slide = None
            self.rg.selected_pets = list(self.gg.pet_list[:1])
            if input_mode is not None:
                self.rg.INPUT_MODE = input_mode
        random.seed(seed)
        self.clock_ms = 0
        del self.sounds[:]
        del self.logs[:]
        for hook in self.after_reset:               # e.g. log in to a fake server again
            with quiet():
                hook()

    def game(self, scene_name, scene_cls=None):
        """A VirtualPetGame (the real scene switching) starting on *scene_name*."""
        game = self.VirtualPetGame.__new__(self.VirtualPetGame)
        game.rotated = False
        game.mouse_pointer = None
        game._mouse_pointer_orig = None
        game._mouse_pointer_size = None
        game.stat_font = None
        with quiet():
            if scene_cls is None and scene_name == "boot":
                # Not in change_scene's map: VirtualPetGame builds it at start-up.
                from scenes.scene_boot import SceneBoot
                scene_cls = SceneBoot
            if scene_cls is None:
                self.rg.game_state = scene_name
                self.rg.game_state_update = True
                game.scene = types.SimpleNamespace()
                game.change_scene()
            else:
                game.scene = scene_cls()
        return game

    def frames(self, game, n=1):
        """update + draw n times; returns the frame times in seconds."""
        surface = self.rg.render_surface
        times = []
        with quiet():
            for _ in range(n):
                t = time.perf_counter()
                game.update()
                surface = self.rg.render_surface
                surface.fill(SENTINEL)
                game.draw(surface)
                times.append(time.perf_counter() - t)
                self.clock_ms += FRAME_MS
        return times

    def tap(self, game, pos, motion=False):
        """A click or tap at *pos*, as the game delivers it: the pointer moves
        there first (UIManager reads the click position from it), then the
        action goes through VirtualPetGame.dispatch_input like a real one."""
        self.rg.game_input.mouse_position = tuple(pos)
        with quiet():
            if motion:
                game.dispatch_input(("MOUSE_MOTION", {"pos": tuple(pos)}))
            return game.dispatch_input(("LCLICK", {"pos": tuple(pos)}))

    def press(self, game, action):
        """A button (UP, DOWN, LEFT, RIGHT, A, B, START, SELECT) as the input
        manager hands it on: keyboard, joystick and GPIO all arrive like this."""
        with quiet():
            return game.dispatch_input((action, None))

    def unpainted(self):
        surface = self.rg.render_surface
        return self.pygame.mask.from_threshold(surface, SENTINEL, (1, 1, 1, 255)).count()

    def error_logs(self, since=0):
        return [l for l in self.logs[since:] if any(m in l for m in ERROR_MARKERS)]


def managers(scene):
    """Every UIManager reachable from a scene (its views included)."""
    from ui.ui_manager import UIManager
    found, seen, stack = [], set(), [(scene, 0)]
    while stack:
        obj, depth = stack.pop()
        if id(obj) in seen or depth > 3:
            continue
        seen.add(id(obj))
        if isinstance(obj, UIManager):
            found.append(obj)
            continue
        if isinstance(obj, dict):
            values = list(obj.values())
        elif isinstance(obj, (list, tuple)):
            values = list(obj)
        elif hasattr(obj, "__dict__") and type(obj).__module__.split(".")[0] in ("scenes", "ui", "battle", "training"):
            values = list(vars(obj).values())
        else:
            values = []
        for v in values:
            if v is None or isinstance(v, (int, float, str, bytes, bool)):
                continue
            if hasattr(v, "get_size") and hasattr(v, "blit"):
                continue
            stack.append((v, depth + 1))
    return found


def focusables(scene):
    out = []
    for mgr in managers(scene):
        for c in mgr.focusable_components:
            if getattr(c, "visible", True):
                out.append(c)
    return out
