"""Offline care boundaries, forecast isolation and foreground-rule parity."""
import copy
import os
import random
import sys
import time
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'src'))
from core import game_globals, runtime_globals
from models.game_pet import GamePet
from models.game_event import GameEvent, EventType
from models.event_clock import EventClock
from services.android_offline import OfflineWorld
from services.android_progress import elapsed_since, valid_claim
from services import android_progress


def module(**overrides):
    data = dict(name='Test', unlocks=[], visible_stats=[], traited_egg_starting_level=1,
                use_condition_hearts=False, care_99g_effect='Nothing',
                meat_care_mistake_time=20, protein_care_mistake_time=20,
                sleep_care_mistake_timer=20, death_max_injuries=0, death_sick_timer=0,
                death_hunger_timer=0, death_strength_timer=0, death_stage45_mistake=0,
                death_stage67_mistake=0, death_starvation_count=0, death_care_mistake=0,
                death_old_age=0, death_save_by_b_press=0, death_save_by_shake=0,
                care_poop_chance=[100, 0, 0, 0], care_poop_sickness_count=0,
                traited_egg_rule='None', get_monster=lambda *_: None,
                get_all_monsters=lambda: [], load_events_json=lambda: [],
                get_friend_encounters=lambda: [], use_gcells=False)
    data.update(overrides)
    return SimpleNamespace(**data)


def species(name='Baby', stage=3, **overrides):
    data = dict(module='Test', name=name, stage=stage, version=1, special=False,
                evolve=[], time=999999, min_weight=10, stomach=4, hunger_loss=10,
                strength_loss=15, power=10, attribute='Va', energy=20,
                poop_timer=30, atk_main=1)
    data.update(overrides)
    return data


def pet(mod, **overrides):
    with patch('models.game_pet.get_module', return_value=mod), \
            patch.object(GamePet, 'load_sprite'), patch.object(GamePet, 'begin_position'):
        p = GamePet(species())
    p.android_id = 'pet1'
    p.hunger = p.strength = 4
    p.x = p.y = 0
    p.__dict__.update(overrides)
    return p


def snapshot(pets, at=None, elapsed=0):
    at = at or datetime(2026, 9, 12, 12).timestamp()
    mono = time.monotonic()
    for p in pets:
        p._rt_origin = mono - elapsed
        p._last_age_date = datetime.fromtimestamp(at).date()
    return dict(at=at, generation='test-generation', rng=random.Random(42).getstate(),
                pets=[p.android_offline_snapshot(at, mono) for p in pets],
                poop_list=[], unlocks={}, traited=[], gcell_fragments=[], quests=[],
                friends={}, digidex=[], friend_event_pending=None, xai=3,
                xai_date=datetime.fromtimestamp(at).date(), event=None, event_time=60)


class OfflineTests(unittest.TestCase):
    def setUp(self):
        self.console = patch.object(runtime_globals, 'game_console', SimpleNamespace(log=lambda *_: None))
        self.sound = patch.object(runtime_globals, 'game_sound', SimpleNamespace(play=lambda *_: None))
        self.console.start()
        self.sound.start()
        self.addCleanup(self.console.stop)
        self.addCleanup(self.sound.stop)

    def test_minute_remainder_no_tick_before_boundary(self):
        mod = module()
        state = snapshot([pet(mod)], elapsed=40)
        world = OfflineWorld(state, {'Test': mod})
        world.advance(state['at'] + 19)
        self.assertEqual(world.pet_list[0]._cd_hunger, 10)
        world.advance(state['at'] + 30)
        self.assertEqual(world.pet_list[0]._cd_hunger, 9)
        self.assertAlmostEqual(world.pet_list[0].next_minute - world.cursor, 50)

    def test_minutes_pending_off_the_main_screen_apply_as_one_batch(self):
        # Only SceneMainGame runs update(): 5.5 minutes on another screen
        # leave five minutes unapplied when the app closes from there.
        mod = module()
        p = pet(mod, hunger=0, _cd_hunger=10, _cd_poop=9999)
        state = snapshot([p], elapsed=330)
        self.assertEqual(state['pets'][0]['android_pending_minutes'], 5)
        world = OfflineWorld(state, {'Test': mod}).advance(state['at'])
        offline = world.pet_list[0]
        self.assertEqual(offline._rt_last_minute, 5)
        self.assertEqual(offline._evol_minutes, p._evol_minutes + 5)
        self.assertEqual(offline._cd_hunger, 5)
        # update() counts an ignored call once per tick, however long the tick.
        self.assertEqual(offline.care_food_mistake_timer, 1)
        self.assertAlmostEqual(offline.next_minute - world.cursor, 30)
        self.assertNotIn('android_pending_minutes', offline.export())
        world.advance(state['at'] + 30)
        self.assertEqual(world.pet_list[0]._cd_hunger, 4)

    def test_warm_resume_rebuilds_a_kept_main_screen(self):
        class SceneMainGame:
            event_stage = 1  # an alert that recovery found expired

        class Game:  # VirtualPetGame.change_scene keeps a scene of the same class
            scene = SceneMainGame()

            def change_scene(self):
                if type(self.scene) is not SceneMainGame:
                    self.scene = SceneMainGame()
                    self.scene.event_stage = 0

        game = Game()
        kept = game.scene
        with patch.object(android_progress, '_needs_scene_refresh', True), \
                patch.object(android_progress, '_game_instance', None), \
                patch.object(game_globals, 'pet_list', [object()]), \
                patch('utils.scene_utils.change_scene'):
            android_progress.refresh_scene(game)
        self.assertIsNot(game.scene, kept)
        self.assertEqual(game.scene.event_stage, 0)

    def test_all_missed_poops_and_shared_sickness(self):
        mod = module(care_poop_sickness_count=2)
        p = pet(mod, _cd_poop=1, poop_timer=1)
        state = snapshot([p])
        world = OfflineWorld(state, {'Test': mod}).advance(state['at'] + 180)
        self.assertEqual(len(world.poop_list), 3)
        self.assertGreater(world.pet_list[0].sick, 0)
        self.assertEqual(world.pet_list[0].injuries, 1)
        self.assertEqual(world.pet_list[0].unflushed_poops, 3)

    def test_pending_poop_completes_without_waiting_for_another_minute(self):
        mod = module()
        state = snapshot([pet(mod, state='pooping')])
        world = OfflineWorld(state, {'Test': mod}).advance(state['at'] + 1)
        self.assertEqual(len(world.poop_list), 1)
        self.assertEqual(world.pet_list[0].state, 'idle')
        world.advance(state['at'] + 2)
        self.assertEqual(len(world.poop_list), 1)

    def test_forecast_isolated_and_chunked_recovery_matches(self):
        mod = module(care_poop_chance=[30, 30, 20, 20])
        state = snapshot([pet(mod)])
        original = copy.deepcopy(state)
        global_rng = random.getstate()
        one = OfflineWorld(state, {'Test': mod}).advance(state['at'] + 7200)
        chunks = OfflineWorld(state, {'Test': mod})
        for delta in (7, 71, 301, 950, 3511, 7200):
            chunks.advance(state['at'] + delta)
        self.assertEqual(one.pet_list[0].export(), chunks.pet_list[0].export())
        self.assertEqual(one.poop_list, chunks.poop_list)
        self.assertEqual(one.notices, chunks.notices)
        self.assertEqual(state, original)
        self.assertEqual(random.getstate(), global_rng)

    def test_wake_crossing_and_sleep_recovery(self):
        mod = module()
        at = datetime(2026, 9, 12, 6, 59, 45).timestamp()
        p = pet(mod, state='nap', sleeps='21:00', wakes='07:00', dp=0,
                sleep_start_time=datetime(2026, 9, 11, 21))
        state = snapshot([p], at=at)
        world = OfflineWorld(state, {'Test': mod}).advance(at + 120)
        self.assertEqual(world.pet_list[0].state, 'idle')
        self.assertEqual(world.pet_list[0].dp, p.energy)

    def test_midnight_age_and_day_rollover(self):
        mod = module()
        state = snapshot([pet(mod)], at=datetime(2026, 9, 12, 23, 59).timestamp())
        world = OfflineWorld(state, {'Test': mod}).advance(state['at'] + 120)
        self.assertEqual(world.pet_list[0].age, 1)
        self.assertEqual(world.xai_date, datetime(2026, 9, 13).date())

    def test_death_removal_occurs_at_existing_minute_boundary(self):
        mod = module(death_old_age=1)
        state = snapshot([pet(mod, age=1)])
        world = OfflineWorld(state, {'Test': mod})
        world.advance(state['at'] + 60)
        self.assertEqual(world.pet_list[0].state, 'dead')
        world.advance(state['at'] + 360)
        self.assertEqual(len(world.pet_list), 1)  # existing rule is > 300 seconds
        world.advance(state['at'] + 420)
        self.assertEqual(world.pet_list, [])

    def test_evolution_resets_timers_then_continues(self):
        target = species('Adult', stage=4, time=9999)
        mod = module(get_monster=lambda *_: target)
        p = pet(mod, time=1, evolve=[{'to': 'Adult'}])
        state = snapshot([p])
        world = OfflineWorld(state, {'Test': mod}).advance(state['at'] + 180)
        adult = world.pet_list[0]
        self.assertEqual(adult.name, 'Adult')
        self.assertEqual(adult._evol_minutes, 2)
        self.assertEqual(adult._rt_last_minute, 2)
        self.assertEqual(len([e for e in world.effects if e['kind'] == 'evolution']), 1)

    def test_poop_countdown_runs_through_evolution_offline(self):
        target = species('Adult', stage=4, time=9999, poop_timer=120)
        mod = module(get_monster=lambda *_: target)
        p = pet(mod, time=1, evolve=[{'to': 'Adult'}], _cd_poop=25)
        state = snapshot([p])
        world = OfflineWorld(state, {'Test': mod}).advance(state['at'] + 180)
        self.assertEqual(world.pet_list[0].name, 'Adult')
        self.assertEqual(world.pet_list[0]._cd_poop, 22)  # three ticks, not 117

    def test_poop_countdown_runs_through_evolution_foreground(self):
        mod = module()
        p = pet(mod)
        with patch('models.game_pet.get_module', return_value=mod):
            for running, timer, expected in ((25, 120, 25),   # carried
                                             (200, 120, 120),  # clamped to the new form
                                             (0, 120, 120),    # an egg hatching starts it
                                             (25, 0, 0)):      # a form that never poops
                p._cd_poop, p.poop_timer = running, timer
                p.reset_variables()
                self.assertEqual(p._cd_poop, expected, (running, timer))

    def test_evolution_does_not_invent_an_hourly_vital_reward(self):
        target = species('Adult', stage=4, time=9999)
        mod = module(get_monster=lambda *_: target, visible_stats=['Vital Values'])
        state = snapshot([pet(mod, time=1, evolve=[{'to': 'Adult'}])])
        world = OfflineWorld(state, {'Test': mod}).advance(state['at'] + 60)
        self.assertEqual(world.pet_list[0].vital_values, 100)

    def test_existing_foreground_care_helpers_match_offline(self):
        mod = module()
        p = pet(mod, _cd_poop=9999)
        state = snapshot([p])
        world = OfflineWorld(state, {'Test': mod})
        with patch('models.game_pet.get_module', return_value=mod):
            for _ in range(55):
                p.update_reliability(1)
                p.update_needs(1)
                p.update_care_mistakes()
                p.update_vital_values_loss()
        world.advance(state['at'] + 55 * 60)
        fields = ('hunger', 'strength', 'mistakes', 'care_food_mistake_timer',
                  'care_strength_mistake_timer', '_cd_hunger', '_cd_strength',
                  'starvation_counter', 'reliability', 'vital_values')
        for field in fields:
            self.assertEqual(getattr(p, field), getattr(world.pet_list[0], field), field)

    def test_notification_call_is_invalid_after_evolution_or_death(self):
        mod = module(death_old_age=1)
        at = datetime(2026, 9, 12, 23, 55).timestamp()
        p = pet(mod, hunger=1, _cd_hunger=1)
        state = snapshot([p], at=at)
        world = OfflineWorld(state, {'Test': mod}).advance(at + 600)
        calls = [n for n in world.notices if n['kind'] == 'call']
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['validUntil'], int(datetime(2026, 9, 13).timestamp() * 1000))

    def test_99g_sleep_and_reliability_module_variations(self):
        for decay in (True, False):
            mod = module(care_needs_decay_while_sleeping=decay,
                         reliability_hourly=-1)
            p = pet(mod, sleeps='21:00', wakes='07:00', reliability=10)
            state = snapshot([p], at=datetime(2026, 9, 12, 22).timestamp())
            world = OfflineWorld(state, {'Test': mod}).advance(state['at'] + 3600)
            self.assertEqual(world.pet_list[0].hunger, 0 if decay else 4)
            self.assertEqual(world.pet_list[0].reliability, 9)

    def test_seven_day_forecast_has_no_catchup_limit(self):
        mod = module()
        p = pet(mod, _cd_poop=0, hunger_loss=99999, strength_loss=99999,
                _cd_hunger=99999, _cd_strength=99999)
        state = snapshot([p])
        world = OfflineWorld(state, {'Test': mod}).advance(state['at'] + 8 * 86400)
        self.assertEqual(world.pet_list[0]._evol_minutes, 8 * 1440)

    def test_save_and_cold_load_recover_once_with_existing_pickle_files(self):
        mod = module()
        p = pet(mod, _cd_hunger=1, hunger_loss=1, _cd_poop=1, poop_timer=9999)
        at = time.time()
        patches = [
            patch.object(runtime_globals, 'IS_ANDROID', True),
            patch.object(runtime_globals, 'game_modules', {'Test': mod}),
            patch.object(game_globals, 'pet_list', [p]),
            patch.object(game_globals, 'poop_list', []),
            patch.object(game_globals, 'android_offline', None),
            patch.object(game_globals, '_can_access_save_dir', return_value=True),
            patch.object(android_progress, 'native', return_value=None),
            patch.object(android_progress, 'after_save'),
            patch.object(android_progress, 'flush_effects'),
            patch.object(android_progress, '_checkpoint', None),
            patch.object(android_progress, '_prepared', None),
            patch.object(android_progress, '_game_instance', None),
            patch.object(GamePet, 'load_sprite'),
            patch.object(GamePet, 'patch'),
        ]
        # Recovery mutates these global containers by design; restore them even
        # when a test fails, without touching the user's save directory.
        for key in ('unlocks', 'traited', 'gcell_fragments', 'quests', 'friends',
                    'friend_event_pending', 'event', 'event_time', 'xai', 'xai_date'):
            patches.append(patch.object(game_globals, key, copy.deepcopy(getattr(game_globals, key))))
        for context in patches:
            context.start()
            self.addCleanup(context.stop)
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(game_globals, 'get_save_dir', return_value=directory), \
                patch.object(android_progress, 'clock_record', return_value={'wall': at}):
            self.assertTrue(game_globals.save())
            self.assertTrue(list(Path(directory).glob('save_data_*.dat')))
            game_globals.pet_list = []
            game_globals.load()
            self.assertEqual(len(game_globals.pet_list), 1)
            with patch.object(android_progress, 'clock_record', return_value={'wall': at + 121}):
                android_progress.on_load()
                self.assertEqual(game_globals.pet_list[0].hunger, 2)
                self.assertEqual(len(game_globals.poop_list), 1)
                # It must be drawable in the very first restored frame,
                # before GamePoop.update has ever initialized animation state.
                self.assertEqual(game_globals.poop_list[0].frame_index, 0)
                android_progress.recover()
                self.assertEqual(game_globals.pet_list[0].hunger, 2)
                self.assertEqual(len(game_globals.poop_list), 1)

    def test_cold_load_checkpoint_does_not_count_the_load_time(self):
        # Saved 600 s into its minute clock; the rest of the save then takes
        # 3 s to load. At the checkpoint (the save's moment) it is still 600.
        p = pet(module())
        with patch('models.game_pet.time.monotonic', return_value=1000.0):
            p._rt_origin, p._rt_dead_start = 400.0, 0.0
            state = p.__getstate__()
        self.assertNotIn('_rt_restored_at', state)
        loaded = GamePet.__new__(GamePet)
        with patch('models.game_pet.time.monotonic', return_value=5000.0), \
                patch.object(GamePet, 'load_sprite'):
            loaded.__setstate__(state)
        at = 1_800_000_000.0
        self.assertEqual(loaded.android_offline_snapshot(at, 5003.0, restored=True)['_rt_origin'], at - 600)
        self.assertEqual(loaded.android_offline_snapshot(at, 5003.0)['_rt_origin'], at - 603)
        self.assertNotIn('_rt_restored_at', loaded.android_offline_snapshot(at, 5003.0))

    def test_reopening_scatters_offline_poops_and_moves_the_party(self):
        mod = module(care_poop_chance=[0, 100, 0, 0])  # every poop event is a double
        p = pet(mod, _cd_poop=1, poop_timer=5, x=40, x_range=(0, 200), state='idle')
        state = snapshot([p])
        world = OfflineWorld(state, {'Test': mod}).advance(state['at'] + 3600)
        patches = [
            patch.object(game_globals, 'pet_list', [p]),
            patch.object(game_globals, 'poop_list', []),
            patch.object(game_globals, 'android_offline', {}),
            patch.object(runtime_globals, 'game_modules', {'Test': mod}),
            patch.object(GamePet, 'load_sprite'),
        ]
        for key in ('unlocks', 'traited', 'gcell_fragments', 'quests', 'friend_event_pending',
                    'event', 'event_time', 'xai', 'xai_date'):
            patches.append(patch.object(game_globals, key, copy.deepcopy(getattr(game_globals, key))))
        for context in patches:
            context.start()
            self.addCleanup(context.stop)
        random.seed(7)
        computed_origin = world.pet_list[0]._rt_origin
        android_progress.apply_world(world, 9000.0)
        # The result sits at the instant it was computed for, not later.
        self.assertAlmostEqual(p._rt_origin, 9000.0 - (world.cursor - computed_origin))
        xs = [q.x for q in game_globals.poop_list]
        self.assertEqual(len(xs), 2 * 12)
        pairs = list(zip(xs[::2], xs[1::2]))
        for left, right in pairs:
            self.assertAlmostEqual(right - left, 24 * runtime_globals.UI_SCALE)
        self.assertGreater(len({round(left) for left, _ in pairs}), 6)  # not one heap
        self.assertTrue(0 <= p.x <= 200)
        self.assertNotEqual(p.x, 40)

    def test_desktop_save_does_not_invoke_android_calculation(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(game_globals, 'get_save_dir', return_value=directory), \
                patch.object(game_globals, '_can_access_save_dir', return_value=True), \
                patch.object(runtime_globals, 'IS_ANDROID', False), \
                patch.object(game_globals, 'pet_list', []), \
                patch.object(game_globals, 'poop_list', []), \
                patch.object(android_progress, 'before_save', side_effect=AssertionError('Android on desktop')):
            self.assertTrue(game_globals.save())

    def test_claim_window_uses_native_entry_time(self):
        meta = {'generation': 'g', 'profile': 'p', 'consumed': []}
        claim = dict(generation='g', profile='p', id='e', event={},
                     posted=1000, expires=301000, entered=300999)
        self.assertTrue(valid_claim(claim, meta))
        self.assertFalse(valid_claim(dict(claim, entered=301001), meta))
        self.assertFalse(valid_claim(claim, dict(meta, consumed=['e'])))
        self.assertFalse(valid_claim(claim, dict(meta, profile='other')))

    def test_elapsed_clock_survives_suspend_and_wall_clock_changes(self):
        before = dict(wall=1000, elapsed=500, boot='1')
        after = dict(wall=800, elapsed=600, boot='1')
        self.assertEqual(elapsed_since(before, after), 100)
        self.assertEqual(elapsed_since(before, dict(after, boot='2')), 0)
        self.assertEqual(elapsed_since(before, dict(wall=1500, boot='2')), 500)

    def test_event_controller_pauses_countdown_and_keeps_one_minute_ui(self):
        state = SimpleNamespace(event=object(), event_time=30, pet_list=[])
        EventClock.tick(state, lambda: self.fail('roll while pending'), lambda: self.fail('friend while pending'))
        self.assertEqual(state.event_time, 30)
        self.assertFalse(EventClock.expired(1799, 30))
        self.assertTrue(EventClock.expired(1800, 30))

    def test_existing_event_expiry_does_not_wait_for_the_next_pet_minute(self):
        mod = module()
        state = snapshot([pet(mod)])
        state['event'] = GameEvent('gift', 'Gift', 'Test', False, EventType.ITEM_PACKAGE, 100, 0, 0)
        state['event_until'] = state['at'] + 10
        world = OfflineWorld(state, {'Test': mod}).advance(state['at'] + 11)
        self.assertIsNone(world.event)

    def test_existing_alert_remaining_window_is_consumed_once(self):
        event = GameEvent('gift', 'Gift', 'Test', False, EventType.ITEM_PACKAGE, 100, 0, 0)
        event.android_remaining_seconds = 20
        event.android_silent_arrival = True
        self.assertEqual(EventClock.initial_alert(event, 30), (1200, True))
        self.assertEqual(EventClock.initial_alert(event, 30), (0, False))


if __name__ == '__main__':
    unittest.main()
