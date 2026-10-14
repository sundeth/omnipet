"""AND-09 (BLD-06): clock changes while the app is closed.

Recovery counts real time, not wall-clock arithmetic, and keeps the calendar
the player's device shows:

  DST       Closed across a spring-forward or fall-back night (New York's
            02:00 changes, and the midnight changes of Santiago, Beirut and
            Havana, where the date itself is skipped or repeated): the closed
            party ends exactly as the open one (GamePet.update on the same
            zoned clock), every real minute is applied once (none twice in
            the repeated hour, none invented in the skipped one), sleepers
            wake at the local wake time, age and the XAI day turn over once
            per local date, and the calculation never steps backwards.
  zone      A timezone change between close and open: the window is
            simulated in the zone saved at close, the next checkpoint takes
            the new one, and age never runs backwards or twice. An unknown
            zone name falls back to the saved UTC offset.
  set back  The wall clock set back: within a boot the suspend-inclusive
            clock decides (real minutes, never negative); after a reboot the
            nonnegative wall fallback applies nothing, and the minutes are
            never applied twice afterwards.
  forward   The wall clock jumped forward days: within a boot only real
            minutes are applied, the calendar jump shows up once at the next
            checkpoint (as the open app shows it); after a reboot the wall
            fallback catches up in full - ten days, no seven-day cap.
  reboot    Wall time instead of the suspend clock when the boot id changes
            or the native clock is unavailable; SDL's suspension fallback
            ignores a zero, negative or non-finite gap.

A pet napping when the clock is set back past its wake time is the one case
where closed and open differ (finding A3, marked expectedFailure).

Time is injected through the code's own seams: the checkpoint's `at`/zone,
android_progress.clock_record (the native clock) and, for the open run,
game_pet's clock inside android_parity.Foreground. Runs in a few seconds.
"""
import math
import sys
import time
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from android_parity import (Clock, Foreground, OfflineWorld, Session, lockstep,  # noqa: E402
                            local_ts, pair_offline, quiet)
from test_android_offline import module, species  # noqa: E402
from services import android_progress  # noqa: E402
from services.android_progress import elapsed_since  # noqa: E402

HOUR = 3600
SEED = 'and-09'


def clock_module(**overrides):
    """The synthetic module of test_android_offline, with a Strength meter
    and no deaths: these tests are about the clock, not the care rules."""
    return module(**dict(dict(visible_stats=['Hunger', 'Strength'], care_poop_chance=[100, 0, 0, 0]),
                         **overrides))


def quiet_record(**overrides):
    """A form whose only moving part is the clock: no hunger, strength or
    poop events, no evolution."""
    return species('Quiet', **dict(dict(hunger_loss=99999, strength_loss=99999, poop_timer=0,
                                        time=999999), **overrides))


def transition(zone, year, month):
    """The first UTC offset change of *zone* in *month* (epoch seconds),
    found by scanning, so the dates are checked rather than assumed."""
    tz = ZoneInfo(zone)
    t = datetime(year, month, 1, tzinfo=timezone.utc)
    before = t.astimezone(tz).utcoffset()
    while t.month == month:
        t += timedelta(minutes=30)
        if t.astimezone(tz).utcoffset() != before:
            return t.timestamp()
    raise LookupError(f'no transition for {zone} in {year}-{month:02d}')


class ZonedParity(unittest.TestCase):
    """A party lived open and closed across a DST change, in one zone."""

    def setUp(self):
        self.stack = quiet()
        self.addCleanup(self.stack.close)
        pair_offline(self.stack, SEED)

    def night(self, zone, start, end, extra=(), early=False):
        """Lockstep from *start* to *end* (epoch seconds) in *zone* with a
        sleeper (asleep since 21:00), a pet awake in its sleep window and a
        never-sleeping counter; *early*: a sleeper waking at 01:30."""
        mod = clock_module()
        modules = {'Test': mod}
        clock = Clock(start, zone=zone)
        local = clock.local_now()
        with Foreground(modules, clock, seed=SEED) as fg:
            night_record = species('Night', sleeps='21:00', wakes='07:00')
            fg.pet(night_record, 'sleeper', elapsed=7, state='nap', dp=0,
                   sleep_start_time=datetime.combine(local.date(), datetime.min.time()).replace(hour=21))
            fg.pet(night_record, 'awake', elapsed=23)
            counter = fg.pet(quiet_record(), 'counter', elapsed=41)
            if early:
                fg.pet(species('Early', sleeps='22:00', wakes='01:30'), 'early', elapsed=53,
                       state='nap', dp=0,
                       sleep_start_time=datetime.combine(local.date(), datetime.min.time()).replace(hour=22))
            state = fg.snapshot(zone=zone)
            world = OfflineWorld(state, modules)
            ages = {p.android_id: p.age for p in fg.pets}
            last = [world.cursor]

            def probe(instant):
                out = []
                if world.cursor < last[0]:
                    out.append(f'cursor went back from {last[0]} to {world.cursor}')
                last[0] = world.cursor
                off = next(p for p in world.pet_list if p.android_id == 'counter')
                # Real minutes since the checkpoint, from the counter's phase.
                expected = int((instant - start + 41) // 60)
                if off._evol_minutes != expected:
                    out.append(f'counter applied {off._evol_minutes} minutes, real time is {expected}')
                return out
            hours = [start + n * HOUR for n in range(1, int((end - start) // HOUR) + 1)]
            problems = lockstep(fg, world, set(hours) | set(extra) | {end}, probe=probe)
            self.assertEqual(problems, [], f'{zone}: open and closed differ\n' + '\n'.join(problems))
            return fg, world, ages, counter

    def awake_at(self, world, pid):
        return next(p for p in world.pet_list if p.android_id == pid).state != 'nap'

    def test_spring_forward_new_york(self):
        zone = 'America/New_York'
        change = transition(zone, 2026, 3)
        self.assertEqual(datetime.fromtimestamp(change, ZoneInfo(zone)).hour, 3)
        start = local_ts(2026, 3, 7, 23, zone=zone)
        wake = local_ts(2026, 3, 8, 7, zone=zone)
        end = local_ts(2026, 3, 8, 9, zone=zone)
        self.assertEqual(end - start, 9 * HOUR)  # one wall hour never happened
        fg, world, ages, _ = self.night(zone, start, end, extra=(wake - 120, wake + 120))
        sleeper = next(p for p in world.pet_list if p.android_id == 'sleeper')
        self.assertEqual(sleeper.state, 'idle')
        self.assertEqual(sleeper.dp, sleeper.energy)  # 21:00-07:00 by the clock on the wall
        self.assertEqual({p.android_id: p.age for p in world.pet_list},
                         {k: v + 1 for k, v in ages.items()})
        self.assertEqual(world.xai_date, date(2026, 3, 8))

    def test_spring_forward_sleeper_wakes_at_local_seven(self):
        zone = 'America/New_York'
        start = local_ts(2026, 3, 7, 23, zone=zone)
        wake = local_ts(2026, 3, 8, 7, zone=zone)
        mod = clock_module()
        clock = Clock(start, zone=zone)
        with Foreground({'Test': mod}, clock, seed=SEED) as fg:
            fg.pet(species('Night', sleeps='21:00', wakes='07:00'), 'sleeper', elapsed=7,
                   state='nap', sleep_start_time=datetime(2026, 3, 7, 21))
            world = OfflineWorld(fg.snapshot(zone=zone), {'Test': mod})
        world.advance(wake - 90)
        self.assertEqual(world.pet_list[0].state, 'nap')
        world.advance(wake + 90)
        self.assertEqual(world.pet_list[0].state, 'idle')

    def test_fall_back_new_york_repeats_no_minute(self):
        zone = 'America/New_York'
        change = transition(zone, 2026, 11)
        self.assertEqual(datetime.fromtimestamp(change, ZoneInfo(zone)).hour, 1)
        start = local_ts(2026, 10, 31, 23, zone=zone)
        end = local_ts(2026, 11, 1, 9, zone=zone)
        self.assertEqual(end - start, 11 * HOUR)  # 01:00-02:00 happened twice
        first_0130 = change - 30 * 60  # 01:30 EDT; the second is an hour later
        fg, world, ages, _ = self.night(zone, start, end, early=True,
                                        extra=(first_0130 - 90, first_0130 + 90, first_0130 + HOUR + 90))
        early = next(p for p in world.pet_list if p.android_id == 'early')
        self.assertNotEqual(early.state, 'nap')
        self.assertEqual({p.android_id: p.age for p in world.pet_list},
                         {k: v + 1 for k, v in ages.items()})

    def test_midnight_changes_skip_or_repeat_the_date_once(self):
        cases = (('America/Santiago', 2026, 9), ('America/Santiago', 2026, 4),
                 ('Asia/Beirut', 2026, 3), ('Asia/Beirut', 2026, 10),
                 ('America/Havana', 2026, 3), ('America/Havana', 2026, 11))
        for zone, year, month in cases:
            with self.subTest(zone=zone, month=month):
                change = transition(zone, year, month)
                tz = ZoneInfo(zone)
                start = change - 2 * HOUR
                end = change + 10 * HOUR
                fg, world, ages, _ = self.night(zone, start, end)
                days = {datetime.fromtimestamp(t, tz).date() for t in (start, end)}
                self.assertEqual(len(days), 2, 'the window crosses one local midnight')
                self.assertEqual({p.android_id: p.age for p in world.pet_list},
                                 {k: v + 1 for k, v in ages.items()})
                self.assertEqual(world.xai_date, datetime.fromtimestamp(end, tz).date())
                self.assertEqual(world.cursor, end)


class ZoneChanges(unittest.TestCase):
    """The timezone between close and open, through the real save hooks."""

    TOKYO, NEW_YORK = 'Asia/Tokyo', 'America/New_York'

    def setUp(self):
        self.stack = quiet()
        self.addCleanup(self.stack.close)

    def party(self, mod, close_local_date):
        from test_android_offline import pet
        sleeper = pet(mod, **dict(species('Night', sleeps='21:00', wakes='07:00'), android_id='sleeper'))
        sleeper.__dict__.update(state='nap', dp=0, hunger=4, strength=4,
                                sleep_start_time=datetime.combine(close_local_date, datetime.min.time())
                                .replace(hour=21))
        counter = pet(mod, **dict(quiet_record(), android_id='counter'))
        for p in (sleeper, counter):
            p._rt_origin = time.monotonic() - 30
            p._rt_last_minute = 0
            p._last_age_date = close_local_date
        return [sleeper, counter]

    def test_recovery_uses_the_zone_saved_at_close(self):
        mod = clock_module()
        close = local_ts(2026, 9, 14, 22, zone=self.TOKYO)
        pets = self.party(mod, date(2026, 9, 14))
        with Session(pets, {'Test': mod}, close, zone=self.TOKYO,
                     offset=9 * HOUR) as session:
            meta = session.close()
            self.assertEqual(meta['zone'], self.TOKYO)
            # The player flies to New York; ten real hours later (19:00 there,
            # 08:00 in Tokyo) the app opens.
            session.native.zone, session.native.offset = self.NEW_YORK, -4 * HOUR
            session.advance(10 * HOUR)
            self.assertTrue(session.open())
            sleeper, counter = session.live
            # Woken at 07:00 Tokyo time: 07:00 New York is still twelve hours off.
            self.assertEqual(sleeper.state, 'idle')
            self.assertEqual(sleeper.dp, sleeper.energy)
            self.assertEqual(counter._evol_minutes, 600)
            self.assertEqual(sleeper.age, 1)  # Tokyo's midnight
            self.assertEqual(sleeper._last_age_date, date(2026, 9, 15))
            # The next checkpoint is New York's.
            meta = session.close()
            self.assertEqual(meta['zone'], self.NEW_YORK)
            session.advance(6 * HOUR)  # 01:00 New York, Sept 15
            self.assertTrue(session.open())
            sleeper, counter = session.live
            self.assertEqual(counter._evol_minutes, 960)
            # New York's 15th is no newer than the Tokyo date already counted.
            self.assertEqual(sleeper.age, 1)
            self.assertEqual(sleeper._last_age_date, date(2026, 9, 15))
            self.assertGreaterEqual(sleeper.hunger, 0)
            self.assertGreaterEqual(sleeper.mistakes, 0)

    def test_eastward_change_ages_by_the_new_calendar_once(self):
        mod = clock_module()
        close = local_ts(2026, 9, 14, 20, zone=self.NEW_YORK)  # 09:00 Sept 15 in Tokyo
        pets = self.party(mod, date(2026, 9, 14))
        with Session(pets, {'Test': mod}, close, zone=self.NEW_YORK) as session:
            session.close()
            session.advance(HOUR)
            session.open()  # still New York's evening: no birthday yet
            self.assertEqual(session.live[1].age, 0)
            session.native.zone = self.TOKYO
            session.close()
            session.advance(HOUR)
            session.open()  # Tokyo is a day ahead: counted once
            self.assertEqual(session.live[1].age, 1)
            session.close()
            session.advance(HOUR)
            session.open()
            self.assertEqual(session.live[1].age, 1)
            self.assertEqual(session.live[1]._evol_minutes, 180)

    def test_unknown_zone_falls_back_to_the_saved_offset(self):
        mod = clock_module()
        for zone in ('Not/AZone', '../../etc/passwd'):
            with self.subTest(zone=zone):
                # 22:00 at UTC+9 is 13:00 UTC; the sleeper wakes at 07:00 UTC+9.
                close = datetime(2026, 9, 14, 13, tzinfo=timezone.utc).timestamp()
                clock = Clock(close, zone='Asia/Tokyo')
                with Foreground({'Test': mod}, clock) as fg:
                    fg.pet(species('Night', sleeps='21:00', wakes='07:00'), 'sleeper', elapsed=5,
                           state='nap', sleep_start_time=datetime(2026, 9, 14, 21))
                    state = fg.snapshot(zone=zone, utc_offset=9 * HOUR)
                world = OfflineWorld(state, {'Test': mod})
                self.assertEqual(world.now, datetime(2026, 9, 14, 22))
                wake = datetime(2026, 9, 14, 22, tzinfo=timezone.utc).timestamp()  # 07:00 UTC+9
                world.advance(wake - 90)
                self.assertEqual(world.pet_list[0].state, 'nap')
                world.advance(wake + 90)
                self.assertEqual(world.pet_list[0].state, 'idle')


class ClockJumps(unittest.TestCase):
    """Set back, forward and reboots, through before_save/after_save and
    recover() with a controlled native clock."""

    def setUp(self):
        self.stack = quiet()
        self.addCleanup(self.stack.close)
        self.mod = clock_module()
        self.start = local_ts(2026, 9, 14, 10)

    def session(self, **kwargs):
        from test_android_offline import pet
        p = pet(self.mod, **dict(quiet_record(), android_id='counter'))
        p._rt_origin = time.monotonic() - 30  # 30 s into its minute
        p._rt_last_minute = 0
        p._last_age_date = date(2026, 9, 14)
        return Session([p], {'Test': self.mod}, self.start, **kwargs)

    def minutes(self, session):
        return session.live[0]._evol_minutes

    def assert_sane(self, session):
        p = session.live[0]
        for field in ('_evol_minutes', '_rt_last_minute', 'form_minutes', 'age', 'hunger', 'strength'):
            self.assertGreaterEqual(getattr(p, field), 0, field)

    def test_set_back_within_a_boot_counts_real_minutes(self):
        with self.session() as s:
            s.close()
            s.advance(600, wall=self.start - 86400 + 600)  # set back a day, ten minutes pass
            s.open()
            self.assertEqual(self.minutes(s), 10)
            self.assertEqual(s.live[0].age, 0)
            self.assert_sane(s)
            s.open()  # reopened at once: nothing more
            self.assertEqual(self.minutes(s), 10)
            s.close()
            s.advance(120)
            s.open()
            self.assertEqual(self.minutes(s), 12)
            self.assertEqual(s.live[0].age, 0)  # the set-back date never ages it

    def test_forward_within_a_boot_counts_real_minutes_and_dates_once(self):
        with self.session() as s:
            s.close()
            s.advance(600, wall=self.start + 3 * 86400 + 600)
            s.open()
            self.assertEqual(self.minutes(s), 10)
            self.assertEqual(s.live[0].age, 0)  # the window itself was ten minutes
            s.close()  # anchored at the device's new date from here on
            s.advance(60)
            s.open()
            self.assertEqual(self.minutes(s), 11)
            # Three calendar days on the device's clock, once, as the open
            # app's first frame after the jump counts them.
            self.assertEqual(s.live[0].age, 3)
            s.close()
            s.advance(60)
            s.open()
            self.assertEqual(s.live[0].age, 3)
            self.assert_sane(s)

    def test_reboot_uses_wall_time(self):
        with self.session() as s:
            s.close()
            s.advance(2 * HOUR, boot='boot-2')
            s.open()
            self.assertEqual(self.minutes(s), 120)

    def test_reboot_with_the_clock_set_back_applies_nothing_and_nothing_twice(self):
        with self.session() as s:
            s.close()
            s.advance(0, wall=self.start - HOUR, boot='boot-2')
            s.open()
            self.assertEqual(self.minutes(s), 0)
            self.assert_sane(s)
            s.close()
            s.advance(300)  # same (new) boot: the elapsed clock counts
            s.open()
            self.assertEqual(self.minutes(s), 5)
            s.close()
            s.advance(HOUR + 60, boot='boot-3')  # wall back where it was, plus a minute
            s.open()
            self.assertEqual(self.minutes(s), 66)

    def test_reboot_ten_days_forward_catches_up_in_full(self):
        with self.session() as s:
            s.close()
            s.advance(10 * 86400, boot='boot-2')
            started = time.time()
            s.open()
            self.assertEqual(self.minutes(s), 10 * 1440)
            self.assertEqual(s.live[0].age, 10)
            self.assertLess(time.time() - started, 60)

    def test_without_the_native_clock_wall_time_is_used(self):
        with self.session() as s:
            s.record = {'wall': self.start}
            s.close()
            s.record = {'wall': self.start + 900}
            s.open()
            self.assertEqual(self.minutes(s), 15)
            s.close()
            s.record = {'wall': self.start}  # set back
            s.open()
            self.assertEqual(self.minutes(s), 15)
            self.assert_sane(s)

    def test_suspension_fallback_ignores_bad_gaps(self):
        with self.session() as s:
            s.close()
            for gap in (0, -30, float('nan'), float('inf'), float('-inf')):
                android_progress.recover_suspension(gap)
                self.assertEqual(self.minutes(s), 0, gap)
            android_progress.recover_suspension(125)
            self.assertEqual(self.minutes(s), 2)  # 30 s phase + 125 s

    def test_elapsed_since_edge_cases(self):
        cases = (
            (dict(wall=1000, elapsed=500, boot='a'), dict(wall=900, elapsed=400, boot='a'), 0),
            (dict(wall=1000, elapsed=500, boot='a'), dict(wall=5000, elapsed=560, boot='a'), 60),
            (dict(wall=1000, elapsed=500, boot='a'), dict(wall=1060, boot='b'), 60),
            (dict(wall=1000), dict(wall=1090, elapsed=7, boot='b'), 90),
            (dict(wall=1000, boot=None), dict(wall=900, boot=None), 0),
            (dict(wall=1000), dict(wall=float('nan')), 0),
            (dict(wall=1000), dict(wall=float('inf')), 0),
            (dict(wall=1000, elapsed=1, boot='a'), dict(wall=1000, elapsed=float('inf'), boot='a'), 0),
        )
        for previous, current, expected in cases:
            with self.subTest(previous=previous, current=current):
                result = elapsed_since(previous, current)
                self.assertEqual(result, expected)
                self.assertTrue(math.isfinite(result) and result >= 0)


class ClockSetBackWhileAsleep(unittest.TestCase):
    """Finding A3: a nap that began 'after' the clock's new time."""

    def setUp(self):
        self.stack = quiet()
        self.addCleanup(self.stack.close)
        pair_offline(self.stack, SEED)

    # Bug A3 (findings/android.md): OfflinePet.check_wake_up waits for the
    # first wake time after sleep_start_time; GamePet.check_wake_up wakes at
    # the wake time on the clock. Set back across the wake time, the closed
    # pet sleeps a further day.
    @unittest.expectedFailure
    def test_pet_wakes_at_its_wake_time_after_the_clock_was_set_back(self):
        mod = clock_module()
        # Asleep since 21:00; the clock is then set back to 02:00 the same day.
        start = local_ts(2026, 9, 14, 2)
        clock = Clock(start)
        with Foreground({'Test': mod}, clock, seed=SEED) as fg:
            fg.pet(species('Night', sleeps='21:00', wakes='07:00'), 'sleeper', elapsed=9,
                   state='nap', sleep_start_time=datetime(2026, 9, 14, 21))
            world = OfflineWorld(fg.snapshot(), {'Test': mod})
            problems = lockstep(fg, world, [start + n * HOUR for n in range(1, 7)])
        self.assertEqual(problems, [])
        self.assertEqual(world.pet_list[0].state, 'idle')


if __name__ == '__main__':
    unittest.main()
