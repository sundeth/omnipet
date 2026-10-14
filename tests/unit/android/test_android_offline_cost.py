"""AND-03 / AND-01 (BLD-06): what a closed hour costs the offline calculation.

Recovery runs before the first frame on every open and the forecast covers
seven days after every save, minute by minute for the whole party, so its
per-minute work has to stay small. Reading module data is the expensive
part: GameModule.get_monster parses monster.json from disk on every call
(about 7 ms for VB's 597 forms on the development PC).

Finding A2 (marked expectedFailure): the scheduled-encounter check
(utils.event_utils.scheduled_event, run by OfflineWorld every minute) looks
up every awake pet's record each minute when its form has no
encounter_time_group - every form outside the Godzilla devices - so a day
of two awake pets parses monster.json 2880 times. The test counts the
lookups (with the record cache of android_parity, so it runs in a second);
a party's evolutions and deaths need a handful, not one per pet-minute.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from android_parity import (Clock, Foreground, MODULES_DIR, OfflineWorld, load_module,  # noqa: E402
                            local_ts, quiet, species)

#: Lookups a 12-hour window may need for two pets that neither evolve nor die.
ALLOWANCE = 24


class OfflineCost(unittest.TestCase):
    def setUp(self):
        if not MODULES_DIR.is_dir():
            self.skipTest('modules/ is not present')
        self.stack = quiet()
        self.addCleanup(self.stack.close)

    def lookups(self, name, hours=12):
        module = load_module(name)
        if module is None:
            self.skipTest(f'modules/{name} is missing')
        modules = {module.name: module}
        start = local_ts(2026, 9, 14, 8)
        child = species(module, 3)
        with Foreground(modules, Clock(start)) as fg:
            for n in range(2):
                fg.pet(child, f'pet{n}', elapsed=9 + 20 * n, hunger=4, strength=4, _evol_minutes=0)
            state = fg.snapshot()
        world = OfflineWorld(state, modules)
        calls = []
        real = module.get_monster
        with patch.object(module, 'get_monster', side_effect=lambda *a: calls.append(a) or real(*a)):
            world.advance(start + hours * 3600)
        awake = sum(1 for p in world.pet_list if p.state != 'nap')
        return len(calls), awake

    def test_the_godzilla_schedule_check_reads_its_own_field(self):
        # PENGZ forms carry encounter_time_group, so no lookup is made.
        calls, _ = self.lookups('PENGZ')
        self.assertLessEqual(calls, ALLOWANCE)

    # Bug A2 (findings/android.md): event_utils._monster_field falls back to
    # module.get_monster every minute for a form whose field is None
    # (src/utils/event_utils.py:76-86, called from scheduled_event:252).
    # Fixed 2026-10-13; kept as a regression test.
    def test_a_quiet_half_day_does_not_reread_monster_records_every_minute(self):
        calls, awake = self.lookups('DMC')
        self.assertGreater(awake, 0)
        self.assertLessEqual(calls, ALLOWANCE, f'{calls} monster.json lookups for 2 pets over 12 hours')


if __name__ == '__main__':
    unittest.main()
