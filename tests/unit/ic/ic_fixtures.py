# -*- coding: utf-8 -*-
"""Shared builders for the Digivice iC tests (tests/unit/ic, tests/game/ic).

Not a test file. It loads the real modules (modules/IC, and DMC as the
non-iC comparison), builds real GamePets from their monster.json records and
patches the globals a pet's care code reaches for, so a test drives the same
GamePet methods the game runs.

    class MyTests(ICCase):
        def test_x(self):
            pet = self.pet()                 # an iC Child (Agumon, version 1)
            self.tick(pet)                   # one minute of GamePet.update

Every case runs on a fixed random seed. `should_sleep` is patched to the
pet's `_test_bedtime` (default False), so no result depends on the wall
clock; set it True for a bedtime.
"""
import os
import random
import sys
import time
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SRC = os.path.join(REPO_ROOT, "src")
MODULES = os.path.join(REPO_ROOT, "modules")
for _path in (os.path.join(REPO_ROOT, "tests", "support"), SRC, REPO_ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)

#: modules/ is gitignored: the iC tests skip without it.
HAVE_IC = os.path.exists(os.path.join(MODULES, "IC", "module.json"))
HAVE_DMC = os.path.exists(os.path.join(MODULES, "DMC", "module.json"))

#: The iC's module.json values these tests protect (ICX-01, ICX-10).
IC_RELIABILITY = dict(
    reliability_base=15, reliability_becoming_full=1, reliability_answering_call=1,
    reliability_ignoring_call=-1, reliability_minigame_success=1, reliability_two_poops=-1,
    reliability_sickness_or_injury=-1, reliability_battle_win=1, reliability_hourly=-1)

_loaded = {}


def init_pygame():
    """A dummy display: module flags and pet sprites are converted surfaces."""
    import pygame
    if not pygame.get_init():
        pygame.init()
    if pygame.display.get_surface() is None:
        pygame.display.set_mode((240, 240))
    return pygame


def load_modules(*names):
    """The real GameModules *names*, loaded once per process."""
    os.chdir(REPO_ROOT)              # assets load from repo-relative paths
    init_pygame()
    from core import runtime_globals
    from models.game_module import GameModule
    for name in names:
        if name not in _loaded:
            with patch.object(runtime_globals, "game_console", SimpleNamespace(log=lambda *a, **k: None)):
                _loaded[name] = GameModule(os.path.join(MODULES, name))
    return {name: _loaded[name] for name in names}


def record(module, name=None, stage=3, version=1):
    """A monster.json record of *module*: *name*, else its first form of
    *stage* on *version*."""
    if name:
        data = module.get_monster(name, version)
    else:
        data = next(m for m in module.get_monsters_by_stage(stage) if m.get("version") == version)
    return dict(data, module=module.name)


class ICCase(unittest.TestCase):
    """Real IC and DMC modules, quiet console and sound, an empty party and
    poop list, the wall clock kept out of bedtime, seed 0."""

    MODULE_NAMES = ("IC", "DMC")

    @classmethod
    def setUpClass(cls):
        if not (HAVE_IC and HAVE_DMC):
            raise unittest.SkipTest("modules/ is gitignored: IC and DMC are needed")
        cls.modules = load_modules(*cls.MODULE_NAMES)
        cls.ic = cls.modules["IC"]
        cls.dmc = cls.modules["DMC"]

    def setUp(self):
        from core import game_globals, runtime_globals
        from models.game_pet import GamePet
        self.gg, self.rg = game_globals, runtime_globals
        self.sound = SimpleNamespace(play=Mock())
        self.console = SimpleNamespace(log=Mock())
        self.slides = Mock()
        patches = [
            patch.object(runtime_globals, "game_modules", dict(self.modules)),
            patch.object(runtime_globals, "game_console", self.console),
            patch.object(runtime_globals, "game_sound", self.sound),
            patch.object(runtime_globals, "game_message", SimpleNamespace(add_slide=self.slides), create=True),
            patch.object(runtime_globals, "pet_sprites", {}),
            patch.object(game_globals, "pet_list", []),
            patch.object(game_globals, "poop_list", []),
            patch.object(game_globals, "inventory", {}),
            patch.object(game_globals, "currency", {}),
            patch.object(game_globals, "shop_access", {}),
            patch.object(game_globals, "event", None),
            patch.object(game_globals, "unlocks", {}),
            patch.object(GamePet, "load_sprite"),
            patch.object(GamePet, "begin_position"),
            patch.object(GamePet, "should_sleep", lambda pet: bool(getattr(pet, "_test_bedtime", False))),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        random.seed(0)

    # ------------------------------------------------------------- builders
    def pet(self, module=None, name=None, stage=3, version=1, party=True, **fields):
        """A real GamePet of *module* (the iC by default), fed to 4 hearts
        as the harness party is, so no hunger call runs unasked."""
        from models.game_pet import GamePet
        module = module or self.ic
        pet = GamePet(record(module, name, stage, version))
        pet.x, pet.y = 40, 100
        pet.hunger = pet.strength = 4
        pet.__dict__.update(fields)
        self.rg.pet_sprites[pet] = [None, None]
        if party:
            self.gg.pet_list.append(pet)
        return pet

    # ------------------------------------------------------------- driving
    @staticmethod
    def tick(pet, minutes=1, batch=False):
        """*minutes* one-minute ticks of the real GamePet.update, each as
        the per-minute section of the game loop sees it; *batch*: one
        update that finds all of them pending at once (a frame after time
        spent on another screen)."""
        for step in ([minutes] if batch else [1] * minutes):
            pet._rt_origin = time.monotonic() - 60 * (pet._rt_last_minute + step) - 0.5
            pet._rt_last_sleep_check = time.monotonic()
            pet.update()

    @staticmethod
    def seconds(pet, seconds):
        """*seconds* of GamePet.update's real-time part (the death save's
        clock) in one frame, with no minute passing."""
        pet._rt_last_sleep_check = time.monotonic() - seconds
        pet.update()


def offline_world(pets, modules, at=None):
    """An Android OfflineWorld (services.android_offline) holding *pets* as
    the checkpoint before closing the app took them, at *at* (noon on
    2026-09-12 by default). Returns (world, at)."""
    import uuid
    from services.android_offline import OfflineWorld
    at = at or datetime(2026, 9, 12, 12).timestamp()
    mono = time.monotonic()
    for pet in pets:
        pet._last_age_date = datetime.fromtimestamp(at).date()
        if not getattr(pet, "android_id", None):
            pet.android_id = uuid.uuid4().hex
    state = dict(at=at, generation="ic-test", rng=random.Random(42).getstate(),
                 pets=[pet.android_offline_snapshot(at, mono) for pet in pets],
                 poop_list=[], unlocks={}, traited=[], gcell_fragments=[], quests=[],
                 friends={}, digidex=[], friend_event_pending=None, xai=3,
                 xai_date=datetime.fromtimestamp(at).date(), event=None, event_time=60)
    return OfflineWorld(state, modules), at
