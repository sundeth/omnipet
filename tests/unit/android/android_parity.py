"""Shared helpers for the Android offline parity tests (not a test file itself).

A party built from a module's own monster data lives twice from one
checkpoint:

  foreground  GamePet.update() on a virtual clock: every pet's minute tick,
              then the frames its poop animation needs, as SceneMainGame
              would run them while the app is open;
  offline     OfflineWorld.advance(), the calculation Android recovery and
              the notification forecast both run while it is closed;

and the two are compared field by field at chosen instants (`compare`).

Only randomness is paired: the n-th poop roll, evolution check and
traited-egg roll of each pet draw the same numbers in both runs (the
android_day harness pairs poops the same way). Idle movement has its own
seeded generator. Time is injected: inside `Foreground` only, game_pet's
monotonic clock and datetime.now() follow the virtual `Clock` (restored on
exit); the offline side takes its time from the snapshot, as designed.

Nothing here writes a file, touches save/ or reaches the network: the
Digidex, rewards, quests, scene changes and sprite loading are stubbed for
the foreground run, and the offline world is isolated by construction.
"""
import ast
import copy
import datetime as _dt
import os
import random
import sys
from collections import defaultdict
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
ROOT = Path(__file__).resolve().parents[3]
for _path in (ROOT / 'tests' / 'support', ROOT / 'src'):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from core import game_globals, runtime_globals  # noqa: E402
from models.game_module import GameModule  # noqa: E402
from models.game_pet import GamePet  # noqa: E402
from services.android_offline import OfflinePet, OfflineWorld  # noqa: E402
from services.android_pet_rules import AndroidPetRules  # noqa: E402
from utils.data_compat import availability  # noqa: E402

MODULES_DIR = ROOT / 'modules'
_REAL_DATETIME = _dt.datetime

#: Console, sound and on-screen message stand-ins (nothing is shown or played).
QUIET = SimpleNamespace(log=lambda *a, **k: None, play=lambda *a, **k: None,
                        add_slide=lambda *a, **k: None, add=lambda *a, **k: None)


def release_modules():
    """RELEASE_MODULES from tests/release/module_audit.py, read without
    importing it (that tool reconfigures stdout on import)."""
    tree = ast.parse((ROOT / 'tests' / 'release' / 'module_audit.py').read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, 'id', None) == 'RELEASE_MODULES'
                                                for t in node.targets):
            return list(ast.literal_eval(node.value))
    raise LookupError('RELEASE_MODULES not found in module_audit.py')


def quiet():
    """Patch the console and sound for a test (an ExitStack to close)."""
    stack = ExitStack()
    stack.enter_context(patch.object(runtime_globals, 'game_console', QUIET))
    stack.enter_context(patch.object(runtime_globals, 'game_sound', QUIET))
    return stack


_MODULE_CACHE = {}


def cache_records(module):
    """Serve get_monster/get_all_monsters from one parse of monster.json.

    Each call still returns a fresh copy, exactly what re-reading the file
    gives, so no rule can tell the difference; only the disk parse is saved.
    The offline world asks for a record once per awake pet per minute
    (finding A2), which would otherwise dominate these tests' run time.
    """
    records = GameModule.get_all_monsters(module)

    def get_all_monsters():
        return copy.deepcopy(records)

    def get_monster(name, version):
        for record in records:
            if record['name'] == name and record['version'] == version:
                return copy.deepcopy(record)
        return None
    module.get_all_monsters = get_all_monsters
    module.get_monster = get_monster
    return module


def load_module(name, cached=True):
    """The real GameModule for modules/<name>, or None when it is missing or
    fails to load (modules/ is not in git; DW1 may be mid-build). The flag
    sprite is not loaded: no display exists. *cached*: see `cache_records`;
    False gives a separate, untouched instance."""
    key = (name, cached)
    if key not in _MODULE_CACHE:
        folder = MODULES_DIR / name
        module = None
        if (folder / 'module.json').is_file() and (folder / 'monster.json').is_file():
            with patch.object(GameModule, 'load_sprites'), \
                    patch.object(runtime_globals, 'game_console', QUIET):
                try:
                    module = GameModule(str(folder))
                    # A read-only cache GameModule fills on first use; warmed
                    # here so a test can treat the object as immutable.
                    module.has_gcell_fragment_egg()
                    module.load_event_extras()
                    if cached:
                        cache_records(module)
                except Exception:
                    module = None
        _MODULE_CACHE[key] = module
    return _MODULE_CACHE[key]


def species(module, stage, skip=0):
    """A raisable (Normal, not special) form of *stage* with evolution routes
    and an evolution time where possible, in monster.json order: the
    *skip*-th such one. A dict ready for GamePet (module name filled in)."""
    records = [m for m in module.get_all_monsters()
               if m.get('stage') == stage and not m.get('special')
               and availability(m) == 'Normal']
    preferred = [m for m in records if m.get('evolve') and m.get('time')]
    pool = preferred or records
    if not pool:
        return None
    record = dict(pool[min(skip, len(pool) - 1)])
    record['module'] = module.name
    record.setdefault('special', False)
    record.setdefault('evolve', [])
    return record


# --------------------------------------------------------------------------
# Time
# --------------------------------------------------------------------------

class Clock:
    """One virtual instant for both clocks: wall (epoch seconds) and the
    monotonic clock GamePet counts minutes on. Steps are exact binary
    fractions so phases and the five-minute removal compare exactly."""

    def __init__(self, wall0, zone=None, mono0=50000.0):
        self.wall0 = float(wall0)
        self.mono0 = float(mono0)
        self.t = 0.0
        self.zone_name = zone
        self.zone = ZoneInfo(zone) if zone else None

    def wall(self):
        return self.wall0 + self.t

    def mono(self):
        return self.mono0 + self.t

    def to_mono(self, wall):
        return self.mono0 + (wall - self.wall0)

    def to_wall(self, mono):
        return self.wall0 + (mono - self.mono0)

    def set_mono(self, mono):
        self.t = mono - self.mono0

    def local_now(self):
        """datetime.now() as the device shows it: naive local time, in
        *zone* when one is given (the offline world's own convention)."""
        if self.zone is not None:
            return _REAL_DATETIME.fromtimestamp(self.wall(), self.zone).replace(tzinfo=None)
        return _REAL_DATETIME.fromtimestamp(self.wall())


def fake_datetime(clock):
    """A datetime class whose now()/today() read *clock*."""
    class FakeDatetime(_REAL_DATETIME):
        @classmethod
        def now(cls, tz=None):
            if tz is not None:
                return _REAL_DATETIME.fromtimestamp(clock.wall(), tz)
            return clock.local_now()

        @classmethod
        def today(cls):
            return clock.local_now()
    return FakeDatetime


def local_ts(year, month, day, hour=0, minute=0, second=0, zone=None):
    """Epoch seconds of a local wall time (machine zone, or *zone*)."""
    tz = ZoneInfo(zone) if zone else None
    if tz is None:
        return _REAL_DATETIME(year, month, day, hour, minute, second).timestamp()
    return _REAL_DATETIME(year, month, day, hour, minute, second, tzinfo=tz).timestamp()


# --------------------------------------------------------------------------
# Paired randomness
# --------------------------------------------------------------------------

class Rolls:
    """The n-th roll of each kind for each pet: the same generator in both
    runs, whatever else either run draws in between."""

    def __init__(self, seed):
        self.seed = seed
        self.count = defaultdict(int)

    def stream(self, pet, kind):
        key = (getattr(pet, 'android_id', None) or '?', kind)
        n = self.count[key]
        self.count[key] += 1
        return random.Random(f'{self.seed}|{key[0]}|{kind}|{n}')


class PairedRandom:
    """Stands in for game_pet's `random` module: a seeded generator for idle
    movement, or the paired stream a wrapped call has opened."""

    def __init__(self, seed):
        self.base = random.Random(seed)
        self.override = None

    def __getattr__(self, name):
        return getattr(self.override or self.base, name)


def _kind(prefix):
    return lambda args, kwargs: f"{prefix}-{kwargs.get('kind', 'normal')}"


def _fg_paired(rng, rolls, original, kind_of):
    def wrapper(self, *args, **kwargs):
        previous = rng.override
        rng.override = rolls.stream(self, kind_of(args, kwargs))
        try:
            return original(self, *args, **kwargs)
        finally:
            rng.override = previous
    return wrapper


def _off_paired(rolls, original, kind_of):
    def wrapper(self, *args, **kwargs):
        world = self.world
        previous = world.rng
        world.rng = rolls.stream(self, kind_of(args, kwargs))
        try:
            return original(self, *args, **kwargs)
        finally:
            world.rng = previous
    return wrapper


PAIRED = (('poop', lambda a, k: 'poop'), ('find_evolution', _kind('evo')),
          ('set_traited_egg', lambda a, k: 'traited'))


def pair_offline(stack, seed):
    """Pair the offline world's rolls with a `Foreground` of the same seed."""
    rolls = Rolls(seed)
    for name, kind_of in PAIRED:
        owner = OfflinePet if name == 'poop' else AndroidPetRules
        stack.enter_context(patch.object(owner, name,
                                         _off_paired(rolls, getattr(owner, name), kind_of)))
    return rolls


# --------------------------------------------------------------------------
# Foreground run
# --------------------------------------------------------------------------

class Foreground:
    """GamePet.update() on a virtual clock, with the game's globals swapped
    for empty ones and every presentation/file/network side effect stubbed.

        with Foreground(modules, clock) as fg:
            pet = fg.pet(record, 'pet1', hunger=2)
            ...
            fg.run_until(wall)

    Each pet's minute tick runs at its own phase (an exact binary epsilon
    after the boundary); a pet that starts pooping gets the frames its
    animation needs before the next tick. Patches are undone on exit."""

    EPS = 2 ** -10
    FRAME = 1 / 64
    TAIL_FRAMES = 48

    def __init__(self, modules, clock, seed='parity', movement_seed=11):
        self.modules = modules
        self.clock = clock
        self.seed = seed
        self.rng = PairedRandom(movement_seed)
        self.rolls = Rolls(seed)
        self.pets = []
        self.cards = []

    def __enter__(self):
        stack = self.stack = ExitStack()
        clock = self.clock
        fake = fake_datetime(clock)
        gp = 'models.game_pet.'
        stack.enter_context(quiet())
        stack.enter_context(patch.object(runtime_globals, 'game_message', QUIET))
        stack.enter_context(patch.object(runtime_globals, 'game_modules', self.modules))
        stack.enter_context(patch.object(runtime_globals, 'pet_sprites', defaultdict(lambda: [None] * 20)))
        stack.enter_context(patch.object(runtime_globals, 'pet_sprites_right', {}))
        stack.enter_context(patch(gp + 'get_module', side_effect=lambda name: self.modules.get(name)))
        stack.enter_context(patch(gp + 'time', SimpleNamespace(monotonic=clock.mono, time=clock.wall)))
        stack.enter_context(patch(gp + 'datetime', fake))
        # set_state('nap') imports datetime locally.
        stack.enter_context(patch.object(_dt, 'datetime', fake))
        stack.enter_context(patch(gp + 'random', self.rng))
        stack.enter_context(patch(gp + 'sprite_load', return_value=None))
        stack.enter_context(patch(gp + 'register_digidex_entry'))
        stack.enter_context(patch(gp + 'change_scene'))
        stack.enter_context(patch('utils.utils_unlocks.check_digidex_unlocks'))
        stack.enter_context(patch('utils.utils_unlocks._grant_card_reward',
                                  side_effect=lambda module, data: self.cards.append((module, data))))
        stack.enter_context(patch('utils.reward_utils.reward_evolution'))
        stack.enter_context(patch('utils.reward_utils.reward_unlock'))
        stack.enter_context(patch('utils.quest_event_utils.update_evolution_quest_progress'))
        stack.enter_context(patch('utils.pet_utils.refresh_pet_sizes'))
        stack.enter_context(patch.object(GamePet, 'load_sprite'))
        stack.enter_context(patch.object(GamePet, '_load_burpmon_sprite'))
        stack.enter_context(patch.object(GamePet, 'begin_position'))
        for name, kind_of in PAIRED:
            stack.enter_context(patch.object(
                GamePet, name, _fg_paired(self.rng, self.rolls, getattr(GamePet, name), kind_of)))
        for key, value in (('pet_list', []), ('poop_list', []), ('unlocks', {}), ('traited', []),
                           ('gcell_fragments', []), ('quests', []), ('friends', {})):
            stack.enter_context(patch.object(game_globals, key, value))
        config = game_globals.configuration
        stack.enter_context(patch.object(config, 'sleep_time', None))
        stack.enter_context(patch.object(config, 'wake_time', None))
        return self

    def __exit__(self, *exc):
        self.stack.close()
        return False

    def pet(self, record, android_id, elapsed=0, state=None, **fields):
        """A GamePet of *record*, *elapsed* seconds into its minute clock at
        the clock's present instant, then *fields* applied. *state* goes
        through set_state (with its animation), before *fields*."""
        p = GamePet(dict(record))
        p.android_id = android_id
        p.x, p.y, p.subpixel_x, p.x_range = 0, 0, 0.0, (0, 192)
        p._rt_origin = self.clock.mono() - elapsed
        p._rt_last_minute = int(elapsed // 60)
        p._rt_last_sleep_check = self.clock.mono()
        if state:
            p.set_state(state, force=True)
        p.__dict__.update(fields)
        game_globals.pet_list.append(p)
        self.pets.append(p)
        return p

    def frame(self):
        for p in list(game_globals.pet_list):
            p.update()

    def _due(self):
        pets = game_globals.pet_list
        if not pets:
            return None
        return min(p._rt_origin + 60 * (p._rt_last_minute + 1) for p in pets)

    def run_until(self, wall):
        """Every minute tick up to *wall*, each followed by the frames a poop
        that started needs; then the clock stands at *wall*. Pick instants
        off the pets' minute boundaries (give pets odd phases): a tick the
        foreground runs EPS after a boundary equal to *wall* is left for the
        next call, where the offline world applies it at *wall* itself."""
        limit = self.clock.to_mono(wall)
        while True:
            due = self._due()
            if due is None or due + self.EPS > limit:
                break
            self.clock.set_mono(due + self.EPS)
            self.frame()
            for _ in range(self.TAIL_FRAMES):
                if not any(p.state == 'pooping' for p in game_globals.pet_list):
                    break
                self.clock.t += self.FRAME
                self.frame()
        self.clock.set_mono(limit)

    def snapshot(self, zone=None, utc_offset=0, rng_seed=5, **extra):
        """The checkpoint android_progress.snapshot() would take now."""
        at, mono = self.clock.wall(), self.clock.mono()
        state = dict(
            at=at, generation='parity', rng=random.Random(rng_seed).getstate(),
            zone=zone, utc_offset=utc_offset, event_until=at + 60,
            pets=[p.android_offline_snapshot(at, mono) for p in game_globals.pet_list],
            poop_list=[copy.deepcopy(q.__dict__) for q in game_globals.poop_list],
            unlocks=copy.deepcopy(game_globals.unlocks), traited=list(game_globals.traited),
            gcell_fragments=list(game_globals.gcell_fragments), quests=[], friends={},
            friend_event_pending=None, xai=3, xai_date=self.clock.local_now().date(),
            event_time=60, event=None, sleep_time=None, wake_time=None, digidex=[])
        state.update(extra)
        return state


# --------------------------------------------------------------------------
# Android session (save hooks and recovery, no device)
# --------------------------------------------------------------------------

class FakeNative:
    """The PetNotifications bridge as android_progress calls it, recording
    what it is asked to do. *zone*/*offset* answer timezoneId() and
    utcOffsetSeconds(); clock records come from `Session.record`."""

    def __init__(self, zone='', offset=0):
        self.zone, self.offset = zone, offset
        self.published = []
        self.calls = []

    def __getattr__(self, name):
        # expectGeneration, setForeground, cancelPlan, consumeClaim, ...
        def call(*args):
            self.calls.append((name, args))
        return call

    def timezoneId(self):
        return self.zone

    def utcOffsetSeconds(self):
        return self.offset

    def peekClaim(self):
        return ''

    def publish(self, text):
        self.published.append(text)


class Session:
    """The Android save/recovery hooks around a live party, without a device,
    a save file or a forecast thread.

    The device clock is `record`: wall time, the suspend-inclusive elapsed
    clock and a boot id, set by the test (`close`, `open`). game.save()
    succeeds without writing; the forecast thread's target is kept in
    `forecasts` and run only when a test calls it. Everything the hooks touch
    in game_globals and android_progress is restored on exit."""

    def __init__(self, pets, modules, wall, zone='', offset=0, boot='boot-1', elapsed=1000.0):
        from services import android_progress
        self.progress = android_progress
        self.pets, self.modules = pets, modules
        self.native = FakeNative(zone, offset)
        self.record = {'wall': float(wall), 'elapsed': float(elapsed), 'boot': boot}
        self.forecasts = []
        self.saves = 0

    def clock_record(self):
        return dict(self.record) if self.record is not None else {'wall': time_wall()}

    def _thread(self, target=None, name=None, daemon=None):
        session = self

        class Recorded:
            def start(self):
                session.forecasts.append(target)
        return Recorded()

    def _save(self):
        self.saves += 1
        return True

    def __enter__(self):
        ap = self.progress
        stack = self.stack = ExitStack()
        stack.enter_context(quiet())
        for target, key, value in (
                (runtime_globals, 'IS_ANDROID', True), (runtime_globals, 'game_modules', self.modules),
                (game_globals, 'pet_list', list(self.pets)), (game_globals, 'poop_list', []),
                (game_globals, 'android_offline', None),
                (ap, '_checkpoint', None), (ap, '_prepared', None), (ap, '_recovering', False),
                (ap, '_background', False), (ap, '_game_instance', None),
                (ap, '_forecast_generation', None), (ap, '_needs_scene_refresh', False)):
            stack.enter_context(patch.object(target, key, value))
        for key in ('unlocks', 'traited', 'gcell_fragments', 'quests', 'friends',
                    'friend_event_pending', 'event', 'event_time', 'xai', 'xai_date'):
            stack.enter_context(patch.object(game_globals, key, copy.deepcopy(getattr(game_globals, key))))
        stack.enter_context(patch.object(game_globals, 'get_save_dir', return_value='parity-profile'))
        stack.enter_context(patch.object(game_globals, 'save', side_effect=self._save))
        stack.enter_context(patch.object(ap, 'native', return_value=self.native))
        stack.enter_context(patch.object(ap, 'clock_record', side_effect=self.clock_record))
        stack.enter_context(patch.object(ap, 'flush_effects'))
        stack.enter_context(patch.object(ap, 'threading', SimpleNamespace(Thread=self._thread)))
        stack.enter_context(patch('models.game_digidex.load_digidex', return_value=[]))
        stack.enter_context(patch.object(GamePet, 'load_sprite'))
        stack.enter_context(patch.object(GamePet, 'patch'))
        stack.enter_context(patch('models.game_pet.get_module',
                                  side_effect=lambda name: self.modules.get(name)))
        stack.enter_context(patch('models.game_pet.sprite_load', return_value=None))
        stack.enter_context(patch.object(runtime_globals, 'pet_sprites', defaultdict(lambda: [None] * 20)))
        return self

    def __exit__(self, *exc):
        self.stack.close()
        return False

    def close(self):
        """The app goes to the background: the existing save path runs the
        checkpoint hooks (before_save, then after_save on success)."""
        meta = self.progress.before_save()
        self.progress.after_save(meta)
        return meta

    def advance(self, seconds, elapsed=None, wall=None, boot=None):
        """The device clock moves: *seconds* of real time pass on the
        suspend-inclusive clock (unless *elapsed* says otherwise), the wall
        clock by the same or to *wall*, a new *boot* id after a reboot
        (whose elapsed clock starts again from *elapsed*, default 50 s)."""
        r = self.record
        if boot is not None and boot != r.get('boot'):
            r['boot'] = boot
            r['elapsed'] = 50.0 if elapsed is None else float(elapsed)
        else:
            r['elapsed'] = r.get('elapsed', 0.0) + (seconds if elapsed is None else elapsed)
        r['wall'] = float(wall) if wall is not None else r['wall'] + seconds

    def open(self):
        """Warm resume: recovery from the last checkpoint."""
        return self.progress.recover()

    @property
    def live(self):
        return game_globals.pet_list


def time_wall():
    import time
    return time.time()


# --------------------------------------------------------------------------
# Deep pictures of live state (side-effect checks)
# --------------------------------------------------------------------------

_LEAVES = (str, int, float, bool, type(None), bytes)


def freeze(obj, _stack=None):
    """A value-only picture of *obj* that compares with ==: dicts, lists,
    sets and objects' __dict__ recursively, dates/enums/other leaves by
    repr. Two pictures are equal exactly when nothing reachable changed."""
    if isinstance(obj, _LEAVES):
        return obj
    if isinstance(obj, (_dt.date, _dt.time, _dt.timedelta)):
        return ('dt', repr(obj))
    import enum
    if isinstance(obj, enum.Enum):
        return ('enum', repr(obj))
    stack = _stack if _stack is not None else set()
    if id(obj) in stack:
        return ('cycle', type(obj).__name__)
    stack.add(id(obj))
    try:
        if isinstance(obj, dict):
            return ('dict', tuple(sorted(((repr(k), freeze(v, stack)) for k, v in obj.items()),
                                         key=lambda kv: kv[0])))
        if isinstance(obj, (list, tuple)):
            return (type(obj).__name__, tuple(freeze(v, stack) for v in obj))
        if isinstance(obj, (set, frozenset)):
            return ('set', tuple(sorted(repr(v) for v in obj)))
        if callable(obj):
            return ('callable', getattr(obj, '__qualname__', type(obj).__name__))
        if hasattr(obj, '__dict__'):
            return (type(obj).__name__, freeze(vars(obj), stack))
        return ('repr', repr(obj))
    finally:
        stack.discard(id(obj))


def differences(before, after, path='', limit=12):
    """Where two `freeze` pictures differ, as paths (at most *limit*)."""
    out = []

    def walk(a, b, where):
        if len(out) >= limit or a == b:
            return
        if (isinstance(a, tuple) and isinstance(b, tuple) and len(a) == 2 == len(b)
                and a[0] == b[0] == 'dict'):
            da, db = dict(a[1]), dict(b[1])
            for key in sorted(set(da) | set(db)):
                if key not in da or key not in db:
                    out.append(f'{where}[{key}] {"added" if key in db else "removed"}')
                else:
                    walk(da[key], db[key], f'{where}[{key}]')
            return
        if (isinstance(a, tuple) and isinstance(b, tuple) and len(a) == 2 == len(b)
                and a[0] == b[0] and isinstance(a[1], tuple) and isinstance(b[1], tuple)
                and len(a[1]) == len(b[1]) and a[0] in ('list', 'tuple')):
            for i, (x, y) in enumerate(zip(a[1], b[1])):
                walk(x, y, f'{where}[{i}]')
            return
        if (isinstance(a, tuple) and isinstance(b, tuple) and len(a) == 2 == len(b)
                and a[0] == b[0] and isinstance(a[0], str)):
            walk(a[1], b[1], f'{where}<{a[0]}>')
            return
        out.append(f'{where}: {str(a)[:80]} -> {str(b)[:80]}')
    walk(before, after, path)
    return out


# --------------------------------------------------------------------------
# Comparison
# --------------------------------------------------------------------------

#: Care state that must come out the same open and closed.
PET_FIELDS = (
    'name', 'stage', 'version', 'hunger', 'strength', 'weight', 'mistakes', 'condition_hearts',
    'sick', 'injury', 'sick_total', 'injury_total', 'dying', 'death_cause', 'gcell_points', 'reliability',
    '_cd_reliability', 'form_minutes', '_evol_minutes', '_rt_last_minute', '_cd_hunger',
    '_cd_strength', '_cd_poop', 'care_food_mistake_timer', 'care_strength_mistake_timer',
    'care_sleep_mistake_timer', 'care_sick_mistake_timer', 'care_injury_mistake_timer',
    'starvation_counter', 'vital_values',
    'debilitation_counter', 'hunger_empty_minutes', 'strength_empty_minutes',
    'age', '_last_age_date', 'life_minutes', 'evolution_failed', 'unflushed_poops', 'poop_mistake_timers', 'virus',
    'back_to_sleep', 'overfeed_timer', '_99g_triggered', 'burpmon_active', 'death_save_immunity',
    'death_save_b_counter', 'death_save_shake_counter', 'evolution_history', 'dp',
    'sleep_disturbances', 'poop_count_flag', 'dna', '_reliability_sleep_call_resolved', 'nap_until',
    'evolution_call',
)
MISSING = '<missing>'


def care_state(state):
    """What the player sees of a state after recovery (android_apply_offline
    shows any transient animation as idle)."""
    return state if state in ('nap', 'dead', 'dying') else 'awake'


def _close(a, b, tolerance=0.01):
    return abs(a - b) <= tolerance


def compare(fg, world, fields=PET_FIELDS):
    """Differences between the foreground party and the offline world, as
    readable lines (empty when they agree)."""
    out = []
    live = {p.android_id: p for p in game_globals.pet_list}
    off = {p.android_id: p for p in world.pet_list}
    if list(live) != list(off):
        out.append(f'party: open {[getattr(p, "name", "?") for p in game_globals.pet_list]} '
                   f'closed {[p.name for p in world.pet_list]}')
    mono = fg.clock.mono()
    for pid in live.keys() & off.keys():
        a, b = live[pid].__dict__, off[pid].__dict__
        for f in fields:
            if a.get(f, MISSING) != b.get(f, MISSING):
                out.append(f'{pid}.{f}: open {a.get(f, MISSING)!r} closed {b.get(f, MISSING)!r}')
        if care_state(a['state']) != care_state(b['state']):
            out.append(f"{pid}.state: open {a['state']!r} closed {b['state']!r}")
        # Minute phase: seconds until the next care minute.
        open_left = a['_rt_origin'] + 60 * (a['_rt_last_minute'] + 1) - mono
        closed_left = b['next_minute'] - world.cursor
        if not _close(open_left, closed_left):
            out.append(f'{pid}.next minute in: open {open_left:.3f}s closed {closed_left:.3f}s')
        if bool(a.get('_rt_dead_start')) != bool(b.get('_rt_dead_start')) or (
                a.get('_rt_dead_start') and not _close(mono - a['_rt_dead_start'],
                                                       world.cursor - b['_rt_dead_start'])):
            out.append(f'{pid}.dead for: open {a.get("_rt_dead_start")} closed {b.get("_rt_dead_start")}')
        sa, sb = a.get('sleep_start_time'), b.get('sleep_start_time')
        if (sa is None) != (sb is None) or (sa and abs((sa - sb).total_seconds()) > 1):
            out.append(f'{pid}.sleep_start_time: open {sa} closed {sb}')
    open_poops = [bool(q.jumbo) for q in game_globals.poop_list]
    closed_poops = [bool(q.get('jumbo')) for q in world.poop_list]
    if (len(open_poops), sum(open_poops)) != (len(closed_poops), sum(closed_poops)):
        out.append(f'poops (count, jumbo): open {(len(open_poops), sum(open_poops))} '
                   f'closed {(len(closed_poops), sum(closed_poops))}')
    for key in ('traited', 'gcell_fragments'):
        if sorted(getattr(game_globals, key)) != sorted(getattr(world, key)):
            out.append(f'{key}: open {getattr(game_globals, key)} closed {getattr(world, key)}')

    def evolution_unlocks(store):
        return sorted((m, u.get('name')) for m, entries in (store or {}).items()
                      for u in entries if isinstance(u, dict) and u.get('type') == 'evolution')
    if evolution_unlocks(game_globals.unlocks) != evolution_unlocks(world.unlocks):
        out.append(f'evolution unlocks: open {evolution_unlocks(game_globals.unlocks)} '
                   f'closed {evolution_unlocks(world.unlocks)}')
    return out


def lockstep(fg, world, instants, fields=PET_FIELDS, probe=None):
    """Step both runs to each wall instant in turn, comparing; the problems
    at the first instant that differs (empty when every one agrees).
    *probe(instant)* may add checks of its own at each instant."""
    for instant in sorted(instants):
        fg.run_until(instant)
        world.advance(instant)
        diffs = compare(fg, world, fields) + sanity(world)
        if probe is not None:
            diffs += probe(instant) or []
        if diffs:
            stamp = fg.clock.local_now().strftime('%Y-%m-%d %H:%M')
            return [f'at {stamp} (local): ' + '; '.join(diffs[:12])]
    return []


def sanity(world):
    """Counters a recovery must never leave negative or broken, as lines."""
    out = []
    for p in world.pet_list:
        d = p.__dict__
        for f in ('hunger', 'strength', 'weight', 'mistakes', 'sick', 'injury', 'sick_total',
                  'injury_total', 'age',
                  '_evol_minutes', '_rt_last_minute', 'form_minutes', 'care_food_mistake_timer',
                  'care_strength_mistake_timer', 'care_sleep_mistake_timer',
                  'care_sick_mistake_timer', 'care_injury_mistake_timer', 'starvation_counter',
                  'vital_values', 'reliability',
                  'debilitation_counter', 'hunger_empty_minutes', 'strength_empty_minutes',
                  'gcell_points', 'unflushed_poops', 'back_to_sleep', 'death_save_immunity'):
            v = d.get(f, 0)
            if v is None:
                continue
            if v < 0:
                out.append(f'{p.android_id}.{f} = {v}')
        if d['next_minute'] <= world.cursor or d['next_minute'] > world.cursor + 60:
            out.append(f'{p.android_id}.next_minute {d["next_minute"]} vs cursor {world.cursor}')
    return out
