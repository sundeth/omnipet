"""AND-10 (BLD-06): a closed app progresses as an open one, module by module.

For every release module (RELEASE_MODULES in tests/release/module_audit.py)
the same party, built from that module's own monster.json and module.json, is
lived twice from one checkpoint: by GamePet.update() minute by minute on a
virtual clock (the app left open on the main screen), and by
OfflineWorld.advance() (Android recovery and forecast). Every hour and at the
end the two must agree on hunger, strength, weight, care mistakes and
condition hearts, poop count and jumbo poops, sickness and injuries,
evolution, stage and history, dying and death and the five-minute removal,
G-Cells, Reliability, Vital Values, the form and evolution timers, sleep and
wake, DP, age, the minute phase, traited eggs, G-Cell fragments and
evolution unlocks (android_parity.compare).

Two lives per module:

  day    10:00-15:00. An egg about to hatch; a Child three minutes from its
         evolution time (it evolves and carries on as its new form); an Adult
         left starving at 99 g (the 99 g effect, calls and care mistakes,
         strength running out, poops piling up into poop sickness, G-Cells
         and Vital Values draining); an Adult whose evolution time comes with
         no battles (PENGZ: the failed evolution and its doubled drain); a
         Perfect sick for almost six hours (it dies or, with a death save,
         goes dying first, is removed five minutes later and may leave a
         traited egg or a G-Cell fragment).
  night  23:30 to an hour after the last wake time. A Child put to sleep at
         21:00 (it wakes at its wake time with DP refilled), a Child left
         awake in its sleep window (sleep calls and mistakes, no hunger
         drain), and a disturbed Adult going back to sleep (DMM: sick from
         its tenth disturbance, care_disturbance_sickness_count); midnight
         ages everyone.

Module traits each party meets on its own data: no Strength meter (iC), the
failed first try (every pet with a win-rate route; PENC and PENGZ double
its needs), condition hearts
(PENC), G-Cells (DMGZ, PENGZ), Vital Values (VB, VBE, VH), Reliability (iC),
the 99 g Dots/Skull effects, double/triple/jumbo poops (DMX, PENZ, PENC,
D-3, PENGZ). DW1 is being built elsewhere and takes part only for the
below-minimum weight rule (care_allow_below_min_weight).

Rolls are paired (the n-th poop, evolution check and traited-egg roll of a
pet draw the same numbers in both runs), so any difference is a rule
difference. Each module's two lives take well under a second.
"""
import sys
import unittest
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from android_parity import (Clock, Foreground, MODULES_DIR, OfflineWorld, compare,  # noqa: E402
                            load_module, local_ts, pair_offline, release_modules, sanity, species)
from core import pet_stats  # noqa: E402
from utils import ailments, evolution_rules, gcell_rules  # noqa: E402

SEED = 'and-10'
DAY = (2026, 9, 14)          # a Monday with no DST change in any zone used here
NEXT = (2026, 9, 15)
HOUR = 3600

#: Modules a parity difference is known for: name -> the bug (findings/android.md).
KNOWN = {}


def _wake_minutes(record):
    hh, mm = (record.get('wakes') or '07:00').split(':')
    return int(hh) * 60 + int(mm)


class ModuleParityBase(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        pair_offline(self.stack, SEED)

    def module_or_skip(self, name):
        if not MODULES_DIR.is_dir():
            self.skipTest('modules/ is not present')
        module = load_module(name)
        if module is None:
            self.skipTest(f'modules/{name} is missing or does not load')
        return module

    def live(self, name, build, start, end, fields=None, checkpoints=HOUR):
        """Build a party in a Foreground at *start*, take the checkpoint,
        then step both runs to each hour and to *end*, comparing."""
        module = self.module_or_skip(name)
        modules = {module.name: module}
        clock = Clock(start)
        with Foreground(modules, clock, seed=SEED) as fg:
            pets = build(fg, module)
            if not pets:
                self.skipTest(f'{name}: no forms to build this party from')
            state = fg.snapshot()
            fg.snapshot_pets = OfflineWorld(state, modules).pet_list  # the party at the checkpoint
            world = OfflineWorld(state, modules)
            problems = []
            t = start
            while t < end:
                t = min(t + checkpoints, end)
                fg.run_until(t)
                world.advance(t)
                kwargs = {'fields': fields} if fields else {}
                diffs = compare(fg, world, **kwargs) + sanity(world)
                if diffs:
                    stamp = clock.local_now().strftime('%H:%M')
                    problems.append(f'at {stamp}: ' + '; '.join(diffs[:12]))
                    break
            self.assertEqual(problems, [], f'{name}: open and closed runs differ\n' + '\n'.join(problems))
            return fg, world

    # -- parties ------------------------------------------------------------

    @staticmethod
    def pet(fg, record, android_id, **fields):
        p = fg.pet(record, android_id, **fields)
        # Finding A1 (findings/android.md): on a module that keeps the battle
        # record across evolutions (DMM) GamePet() never creates one, and the
        # first route or rule that reads it raises in both runs alike. The
        # party gets the record a pet that has never fought would have.
        p.__dict__.setdefault('win', 0)
        p.__dict__.setdefault('battles', 0)
        return p

    @staticmethod
    def strength(module, value):
        return value if pet_stats.tracks_strength(module.visible_stats) else 0

    def day_party(self, fg, module):
        child, adult, perfect, egg = (species(module, s) for s in (3, 4, 5, 0))
        if not child or not adult:
            return []
        perfect = perfect or adult
        s = lambda v: self.strength(module, v)  # noqa: E731
        gcells = gcell_rules.style_of(module) != gcell_rules.DISABLED
        pets = []
        if egg and egg.get('evolve'):
            pets.append(self.pet(fg, egg, 'egg', elapsed=5,
                               _evol_minutes=max(0, int(egg.get('time') or 0) - 3)))
        pets.append(self.pet(fg, child, 'evolver', elapsed=17, hunger=3, strength=s(3),
                           weight=int(child.get('min_weight') or 0) + 3,
                           _evol_minutes=max(0, int(child.get('time') or 0) - 3)))
        pets.append(self.pet(fg, adult, 'neglected', elapsed=29, hunger=1, _cd_hunger=2,
                           strength=s(1), _cd_strength=4, weight=99, _cd_poop=6,
                           gcell_points=60 if gcells else 0, vital_values=1000, reliability=5))
        pets.append(self.pet(fg, adult, 'failing', elapsed=41, hunger=4, strength=s(4),
                           weight=int(adult.get('min_weight') or 0) + 1, _cd_poop=12,
                           gcell_points=20 if gcells else 0,
                           _evol_minutes=max(0, int(adult.get('time') or 0) - 10)))
        lifespan = int(perfect.get('time') or 0)
        pets.append(self.pet(fg, perfect, 'dying', elapsed=53, hunger=2, strength=s(2), sick=1,
                           sick_total=1, care_sick_mistake_timer=max(0, module.death_sick_timer - 3),
                           gcell_points=30 if gcells else 0,
                           # Past its lifespan and 48 hours in the form: the
                           # traited-egg rules that read the timer can pay.
                           _evol_minutes=max(lifespan, 2880) + 1))
        return pets

    def night_party(self, fg, module):
        child, adult = species(module, 3), species(module, 4)
        if not child or not adult:
            return []
        s = lambda v: self.strength(module, v)  # noqa: E731
        count = int(getattr(module, 'care_disturbance_sickness_count', 0) or 0)
        disturbed = dict(back_to_sleep=3, hunger=3, strength=s(3), sleep_disturbances=max(count, 1))
        kind = ailments.kind_for_effect(getattr(module, 'care_disturbance_sickness_effect', 'Dots'))
        if count and kind:  # the count-th disturbance made it sick (DMM: tenth, Dots)
            disturbed.update({kind: 1, ailments.TOTALS[kind]: 1})
        return [
            self.pet(fg, child, 'sleeper', elapsed=7, state='nap', dp=0, hunger=2, strength=s(2),
                   sleep_start_time=datetime(*DAY, 21, 0)),
            self.pet(fg, child, 'awake', elapsed=19, hunger=3, strength=s(3)),
            self.pet(fg, adult, 'disturbed', elapsed=31, **disturbed),
        ]

    def night_end(self, module):
        records = [r for r in (species(module, 3), species(module, 4)) if r]
        latest = max(_wake_minutes(r) for r in records) if records else 7 * 60
        return local_ts(*NEXT) + latest * 60 + 75 * 60

    # -- the rules the lives were meant to meet -----------------------------
    # Agreement alone would also hold if a module's data stopped exercising
    # anything; these check, on the closed run, that each trait was met.

    def day_traits(self, module, world, fg):
        pets = {p.android_id: p for p in world.pet_list}
        start = {p.android_id: p for p in fg.snapshot_pets}
        self.assertNotIn('dying', pets, 'the sick Perfect died and was removed')
        self.assertTrue(any(e['kind'] == 'evolution' for e in world.effects), 'nobody evolved or hatched')
        self.assertTrue(world.poop_list, 'nobody pooped')
        neglected, failing = pets.get('neglected'), pets.get('failing')
        if neglected is None or failing is None:
            return
        hearts_lost = (getattr(start['neglected'], 'condition_hearts', 0)
                       - getattr(neglected, 'condition_hearts', 0)) if module.use_condition_hearts else 0
        self.assertGreater(neglected.mistakes + hearts_lost, 0, 'the starving Adult made no care mistake')
        if getattr(module, 'care_99g_effect', 'Skull') in ('Dots', 'Skull'):
            # 99 g, unless the poop pile's ailment came first (one at a time)
            self.assertGreaterEqual(neglected.sick_total + neglected.injury_total, 1, '99 g made it sick')
        if (failing.name == start['failing'].name
                and evolution_rules.should_fail(start['failing'].evolve or [])):
            self.assertTrue(failing.evolution_failed, 'the timer took no route: failed for good')
        if gcell_rules.style_of(module) != gcell_rules.DISABLED:
            self.assertNotEqual(neglected.gcell_points, 60, 'care mistakes moved its G-Cells')
        if pet_stats.tracks_vital_values(module.visible_stats):
            self.assertLess(neglected.vital_values, 1000, 'poor condition drained Vital Values')
        if not pet_stats.tracks_strength(module.visible_stats):
            self.assertEqual({p.strength for p in world.pet_list}, {0}, 'no Strength meter')

    def night_traits(self, module, world, fg):
        pets = {p.android_id: p for p in world.pet_list}
        sleeper, awake, disturbed = pets.get('sleeper'), pets.get('awake'), pets.get('disturbed')
        self.assertIsNotNone(sleeper)
        self.assertNotIn(sleeper.state, ('nap', 'dead'), 'the sleeper woke')
        self.assertEqual(sleeper.dp, sleeper.energy, 'ten hours of sleep refilled DP')
        self.assertTrue(all(p.age == 1 for p in world.pet_list), 'midnight aged everyone')
        if awake is not None:
            spent = awake.mistakes or (module.use_condition_hearts
                                       and awake.condition_hearts < awake.condition_hearts_max)
            self.assertTrue(spent, 'the pet left awake in its sleep window was not called to bed')
        kind = ailments.kind_for_effect(getattr(module, 'care_disturbance_sickness_effect', 'Dots'))
        if disturbed is not None and module.care_disturbance_sickness_count and kind:
            self.assertEqual((ailments.kind_of(disturbed), disturbed.sleep_disturbances),
                             (kind, module.care_disturbance_sickness_count))


def _make_tests(name):
    def day(self):
        start = local_ts(*DAY, 10)
        fg, world = self.live(name, self.day_party, start, start + 5 * HOUR)
        self.day_traits(self.module_or_skip(name), world, fg)

    def night(self):
        module = self.module_or_skip(name)
        fg, world = self.live(name, self.night_party, local_ts(*DAY, 23, 30), self.night_end(module))
        self.night_traits(module, world, fg)

    for test in (day, night):
        if name in KNOWN:
            test = unittest.expectedFailure(test)
        test.__doc__ = f'{name}: {test.__name__} life open and closed agree'
        yield test


class ReleaseModuleParity(ModuleParityBase):
    """One day life and one night life per release module (DW1 below)."""


for _name in release_modules():
    if _name == 'DW1':
        continue
    _ident = _name.replace('-', '_')
    for _test in _make_tests(_name):
        setattr(ReleaseModuleParity, f'test_{_ident}_{_test.__name__}', _test)


class BelowMinimumWeightParity(ModuleParityBase):
    """DW1 (care_allow_below_min_weight): poops take weight below the
    species' minimum, down to 1, the same open and closed. Only the weight
    rule is checked while DW1 is being built."""

    FIELDS = ('name', 'weight', '_cd_poop', 'unflushed_poops')

    def party(self, fg, module):
        if not getattr(module, 'care_allow_below_min_weight', False):
            self.skipTest('DW1 no longer sets care_allow_below_min_weight')
        child = species(module, 3)
        if not child:
            return []
        low = int(child.get('min_weight') or 0)
        return [self.pet(fg, child, 'at_minimum', elapsed=11, hunger=4, weight=low, _cd_poop=2),
                self.pet(fg, child, 'nearly_one', elapsed=37, hunger=4, weight=2, _cd_poop=3)]

    def test_DW1_weight_goes_below_the_minimum_alike(self):
        start = local_ts(*DAY, 10)
        fg, world = self.live('DW1', self.party, start, start + 5 * HOUR, fields=self.FIELDS)
        minimum = int(species(self.module_or_skip('DW1'), 3).get('min_weight') or 0)
        weights = {p.android_id: p.weight for p in world.pet_list}
        self.assertLess(weights['at_minimum'], minimum)
        self.assertEqual(weights['nearly_one'], 1)


class BattleRecordOnKeepCountModules(ModuleParityBase):
    """Finding A1: a module that keeps the battle record across evolutions
    (battle_keep_counts_on_evolution; DMM among the release modules) gets
    no record at all from GamePet(), so recovery, like the open game, raises
    when the first route reading it comes due."""

    def keep_count_modules(self):
        if not MODULES_DIR.is_dir():
            self.skipTest('modules/ is not present')
        names = [n for n in release_modules()
                 if load_module(n) is not None
                 and getattr(load_module(n), 'battle_keep_counts_on_evolution', False)]
        if not names:
            self.skipTest('no release module keeps the battle record')
        return names

    # Bug A1 (findings/android.md): GamePet.__init__ leaves win/battles unset
    # when reset_variables keeps the record (src/models/game_pet.py:220).
    # Fixed 2026-10-13; kept as a regression test.
    def test_a_new_pet_starts_with_an_empty_battle_record(self):
        for name in self.keep_count_modules():
            module = load_module(name)
            with Foreground({module.name: module}, Clock(local_ts(*DAY, 10))) as fg:
                egg = fg.pet(species(module, 0), 'egg')
                self.assertEqual((getattr(egg, 'win', None), getattr(egg, 'battles', None)), (0, 0), name)

    # Bug A1: the same pet, closed when an Adult route reading `battles`
    # comes due, makes recovery raise (android_progress.recover re-raises).
    # Fixed 2026-10-13; kept as a regression test.
    def test_recovery_reaches_a_battle_route_without_raising(self):
        for name in self.keep_count_modules():
            module = load_module(name)
            adult = species(module, 4)
            if not any('battles' in r for r in adult.get('evolve', [])):
                continue
            modules = {module.name: module}
            start = local_ts(*DAY, 10)
            with Foreground(modules, Clock(start)) as fg:
                fg.pet(adult, 'adult', hunger=4, strength=4,
                       _evol_minutes=int(adult.get('time') or 0) - 1)
                world = OfflineWorld(fg.snapshot(), modules)
            world.advance(start + 10 * 60)
            self.assertEqual(world.cursor, start + 10 * 60, name)


if __name__ == '__main__':
    unittest.main()
