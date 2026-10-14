"""AND-03 (BLD-06): the notification forecast has no side effects.

The forecast runs on every successful Android save (android_progress.
after_save, on a background thread) over seven days of the checkpoint. With
a busy party from real modules (an evolution due, a failed PENGZ evolution,
deaths with traited-egg and G-Cell fragment rolls, Vital Values, iC
Reliability, poops on the floor, a pending evolution quest, random and
scheduled events allowed to fire), running it must leave untouched:

  - every live pet, deeply (its whole __dict__);
  - game_globals: the party and poop lists, unlocks, traited eggs, G-Cell
    fragments, quests (the objects), friends, the event and its clock, XAI;
  - runtime_globals' presentation state and the shared module objects;
  - the global `random` state;
  - the file system (no file opened for writing, created, moved or
    removed), the network (no socket), the save (game.save not called), the
    Digidex/reward outbox (flush_effects not called) and the live console;

and publish exactly one plan: covering seven days from the checkpoint and
equal to what recovery computes from the same checkpoint. A forecast
superseded by a newer save publishes nothing; a forecast that fails
publishes nothing, records the error and still leaves everything as it was.

Also checks the one deliberate effect of the save hooks around it: pets get
a stable android_id and game_globals.android_offline holds the metadata.
"""
import builtins
import copy
import json
import os
import random
import shutil
import socket
import sys
import time
import unittest
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from android_parity import (Clock, Foreground, MODULES_DIR, OfflineWorld, Session,  # noqa: E402
                            differences, freeze, load_module, local_ts, quiet, species)
from core import game_globals, runtime_globals  # noqa: E402
from models.game_poop import GamePoop  # noqa: E402
from models.game_quest import GameQuest, QuestType, RewardType  # noqa: E402
from services import android_progress  # noqa: E402

FORECAST_MODULES = ('DMC', 'PENGZ', 'VB', 'IC', 'DMGZ')
GLOBAL_KEYS = ('pet_list', 'poop_list', 'unlocks', 'traited', 'gcell_fragments', 'quests',
               'friends', 'friend_event_pending', 'event', 'event_time', 'xai', 'xai_date')
RUNTIME_KEYS = ('evolution_pet', 'selected_pets', 'game_pet_eating', 'friend_celebration')
WRITE_MODES = set('wax+')


class Tripwire:
    """Records any file write, move or removal, any socket and any console
    line while armed; the test asserts the record stays empty."""

    def __init__(self):
        self.events = []
        self.armed = False

    def install(self, stack):
        real_open = builtins.open

        def guarded_open(file, mode='r', *args, **kwargs):
            if self.armed and WRITE_MODES & set(str(mode)):
                self.events.append(f'open({file!r}, {mode!r})')
            return real_open(file, mode, *args, **kwargs)
        stack.enter_context(patch.object(builtins, 'open', guarded_open))
        for owner, name in ((os, 'replace'), (os, 'rename'), (os, 'remove'), (os, 'unlink'),
                            (os, 'makedirs'), (os, 'mkdir'), (shutil, 'copy'), (shutil, 'copy2'),
                            (shutil, 'move'), (shutil, 'rmtree')):
            stack.enter_context(patch.object(owner, name, self._wrap(name, getattr(owner, name))))

        tripwire = self

        class NoSocket(socket.socket):
            def __init__(self, *args, **kwargs):
                if tripwire.armed:
                    tripwire.events.append('socket()')
                    raise OSError('network refused by the forecast isolation test')
                super().__init__(*args, **kwargs)
        stack.enter_context(patch.object(socket, 'socket', NoSocket))
        console = SimpleNamespace(log=self._log, play=lambda *a, **k: None)
        stack.enter_context(patch.object(runtime_globals, 'game_console', console))

    def _wrap(self, name, real):
        def wrapper(*args, **kwargs):
            if self.armed:
                self.events.append(f'{name}{args!r}')
            return real(*args, **kwargs)
        return wrapper

    def _log(self, *args, **kwargs):
        if self.armed:
            self.events.append(f'console: {args[0] if args else ""}')


class ForecastIsolation(unittest.TestCase):
    def setUp(self):
        if not MODULES_DIR.is_dir():
            self.skipTest('modules/ is not present')
        self.modules = {}
        for name in FORECAST_MODULES:
            module = load_module(name)
            if module is not None:
                self.modules[module.name] = module
        if not self.modules:
            self.skipTest('none of the forecast modules is present')
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(quiet())
        self.start = local_ts(2026, 9, 14, 10)

    # -- the live game ------------------------------------------------------

    def party(self):
        """Live GamePets of every forecast module, each with something
        going on, built on a virtual clock and then re-anchored on the real
        monotonic clock android_progress reads."""
        clock = Clock(self.start)
        pets = []
        with Foreground(self.modules, clock) as fg:
            for index, (name, module) in enumerate(sorted(self.modules.items())):
                child, adult, perfect = (species(module, s) for s in (3, 4, 5))
                base = f'{name.lower()}-'
                if child:
                    pets.append(fg.pet(child, base + 'evolver', hunger=3, strength=3,
                                       _evol_minutes=max(0, int(child.get('time') or 0) - 5)))
                if adult:
                    pets.append(fg.pet(adult, base + 'failing', hunger=4, strength=4,
                                       _evol_minutes=max(0, int(adult.get('time') or 0) - 2)))
                if perfect:
                    pets.append(fg.pet(perfect, base + 'dying', hunger=2, strength=2, sick=1,
                                       care_sick_mistake_timer=max(0, module.death_sick_timer - 2),
                                       _evol_minutes=max(int(perfect.get('time') or 0), 2880) + 1,
                                       gcell_points=40))
        offsets = {}
        now = time.monotonic()
        for n, p in enumerate(pets):
            p.__dict__.setdefault('win', 0)
            p.__dict__.setdefault('battles', 0)
            elapsed = 3 + 11 * n % 57
            p._rt_origin = now - elapsed
            p._rt_last_minute = 0
            p._rt_last_sleep_check = now
            p._last_age_date = datetime.fromtimestamp(self.start).date()
            offsets[p.android_id] = elapsed
        return pets

    def live_game(self, session):
        game_globals.poop_list[:] = [GamePoop(10, 20), GamePoop(30, 20, jumbo=True)]
        first = next(iter(self.modules))
        game_globals.unlocks.clear()
        game_globals.unlocks[first] = [{'type': 'egg', 'name': 'already'}]
        game_globals.traited[:] = []
        game_globals.gcell_fragments[:] = []
        game_globals.quests[:] = [GameQuest('q1', 'Evolve once', first, QuestType.EVOLUTION, 1,
                                            RewardType.ITEM, 'x', 1)]
        game_globals.friends.clear()
        game_globals.event = None
        game_globals.event_time = 2      # the event clock fires in the forecast
        game_globals.xai = 7
        game_globals.xai_date = datetime.fromtimestamp(self.start).date()
        game_globals.friend_event_pending = None

    def picture(self):
        return {
            'pets': freeze([p.__dict__ for p in game_globals.pet_list]),
            'party': [id(p) for p in game_globals.pet_list],
            'globals': {k: freeze(getattr(game_globals, k)) for k in GLOBAL_KEYS},
            'runtime': {k: freeze(getattr(runtime_globals, k, None)) for k in RUNTIME_KEYS},
            'sprites': sorted(id(k) for k in runtime_globals.pet_sprites),
            'modules': {name: freeze(vars(m)) for name, m in self.modules.items()},
            'rng': random.getstate(),
        }

    def assert_same(self, before, after):
        for key in before:
            if key == 'rng':
                self.assertEqual(before['rng'], after['rng'], 'the global random state moved')
                continue
            diffs = differences(before[key], after[key], key)
            self.assertEqual(diffs, [], f'{key} changed')
        self.assertEqual(before, after)

    def session(self, pets):
        session = Session(pets, self.modules, self.start)
        self.stack.enter_context(session)
        self.stack.enter_context(patch.object(android_progress, '_last_error', ''))
        self.live_game(session)
        return session

    # -- tests --------------------------------------------------------------

    def test_forecast_leaves_everything_untouched_and_matches_recovery(self):
        pets = self.party()
        session = self.session(pets)
        tripwire = Tripwire()
        tripwire.install(self.stack)
        meta = session.close()
        # The save hooks' deliberate effects, before the forecast runs.
        self.assertIs(game_globals.android_offline, meta)
        self.assertEqual(len({p.android_id for p in game_globals.pet_list}), len(pets))
        self.assertEqual(len(session.forecasts), 1)
        flushes = android_progress.flush_effects.call_count
        saves = session.saves
        checkpoint = copy.deepcopy(android_progress._checkpoint)
        before = self.picture()
        tripwire.armed = True
        started = time.time()
        try:
            session.forecasts[0]()
        finally:
            tripwire.armed = False
        took = time.time() - started
        self.assertEqual(android_progress._last_error, '')
        self.assertEqual(tripwire.events, [])
        self.assertEqual(session.saves, saves, 'the forecast saved the game')
        self.assertEqual(android_progress.flush_effects.call_count, flushes,
                         'the forecast delivered rewards')
        self.assert_same(before, self.picture())
        # One plan, seven days, the same calculation recovery runs.
        self.assertEqual(len(session.native.published), 1)
        plan = json.loads(session.native.published[0])
        self.assertEqual(plan['generation'], meta['generation'])
        self.assertEqual(plan['until'], int((checkpoint['at'] + 7 * 86400) * 1000))
        recovery = OfflineWorld(checkpoint, self.modules).advance(checkpoint['at'] + 7 * 86400)
        self.assertEqual(plan['entries'], json.loads(json.dumps(recovery.notices)))
        kinds = {entry['kind'] for entry in plan['entries']}
        self.assertTrue({'call', 'poop'} <= kinds, kinds)
        self.assertLess(took, 90)

    def test_a_superseded_forecast_publishes_nothing(self):
        session = self.session(self.party())
        first = session.close()
        session.advance(60)
        second = session.close()
        self.assertNotEqual(first['generation'], second['generation'])
        stale, current = session.forecasts
        before = self.picture()
        stale()
        self.assertEqual(session.native.published, [])
        current()
        self.assertEqual([json.loads(p)['generation'] for p in session.native.published],
                         [second['generation']])
        self.assert_same(before, self.picture())

    def test_a_failing_forecast_publishes_nothing_and_changes_nothing(self):
        session = self.session(self.party())
        session.close()
        before = self.picture()
        with patch.object(OfflineWorld, 'advance', side_effect=RuntimeError('forecast broke')), \
                patch('builtins.print'):
            session.forecasts[0]()
        self.assertEqual(session.native.published, [])
        self.assertIn('forecast broke', android_progress._last_error)
        self.assert_same(before, self.picture())

    def test_the_checkpoint_is_a_copy(self):
        """Changing the live party after the save (the player feeds a pet)
        must not reach the checkpoint the forecast reads, nor the reverse."""
        session = self.session(self.party())
        session.close()
        captured = copy.deepcopy(android_progress._checkpoint)
        game_globals.pet_list[0].hunger = 0
        game_globals.pet_list[0].dna.append('changed-after-save')
        game_globals.unlocks.setdefault('X', []).append({'type': 'egg', 'name': 'later'})
        game_globals.poop_list.append(GamePoop(0, 0))
        self.assertEqual(freeze(android_progress._checkpoint), freeze(captured))
        android_progress._checkpoint['pets'][1]['hunger'] = 99
        self.assertNotEqual(game_globals.pet_list[1].hunger, 99)


if __name__ == '__main__':
    unittest.main()
