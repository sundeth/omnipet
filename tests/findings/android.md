# Android background simulator: findings

Bugs and gaps found by the tests in `tests/unit/android/` (checklist BLD-06; 1.0 tracker rows AND-01, AND-03, AND-09, AND-10). Each bug has a test marked `@unittest.expectedFailure` that starts passing once it is fixed; take the marker off then. Line numbers are as of 2026-10-13.

## ~~A1. A pet on a module that keeps its battle record has no battle record (DMM)~~ Fixed 2026-10-13: `reset_variables` starts a new pet at 0 and `patch()` repairs saves

- **What**: `GamePet.__init__` never sets `win` or `battles`. Only `reset_variables` does, and it skips them when the module has `battle_keep_counts_on_evolution` (so the Twin keeps its record across an evolution). A new pet on such a module has neither attribute until something writes one, and nothing does. DMM is the one release module with the flag; ACCEL, PENPROG, PENX and TWIN have it too.
- **Where**: `src/models/game_pet.py:47-51` (`__init__`, which sets `totalWin`/`totalBattles` but not `win`/`battles`) and `:220-221` (`reset_variables`). `GamePet.patch()` (`:2355`) does not add them for existing saves either.
- **Effect**: an `AttributeError` at the first read or write:
  - the first battle: `finish_battle`/`finish_versus` (`self.battles += 1`, `game_pet.py:2083, 2106`);
  - an evolution route with `battles`, `win_count` or `win_ratio` (`game_pet.py:1439-1441`), for example DMM Greymon's, raised from `GamePet.update()` when its evolution time comes;
  - the status screen and stats panel (`scenes/scene_status.py:650-656`, `ui/components/stats_panel.py:136-141`), and the `Stage V and Battles` / `Win Ratio` traited-egg rules;
  - on Android, the same route raises inside recovery (`services/android_pet_rules.py:459-461`). `android_progress.recover` re-raises, so `on_load` fails at boot (`utils/display_utils.py:294, 332`) and the forecast records the error and publishes no plan.
- **Reproduce**: `GamePet(<DMM egg record>)`, then `hasattr(pet, "battles")` is False; `pet.finish_versus(True)` raises.
- **Tests**: `test_android_module_parity.py::BattleRecordOnKeepCountModules` (2 xfail). The parity parties give each pet `win = battles = 0` so the rest of DMM can be compared.
- **Checklist**: BLD-06 / AND-10. This is also a care and battle defect for those areas' checklists.
- **Suggested fix**: set `self.win = self.battles = 0` in `__init__` next to `totalWin`, and in `patch()` add `if not hasattr(self, "win")` and `if not hasattr(self, "battles")` (each set to 0) for existing saves.

## ~~A2. The offline calculation re-reads monster.json once per awake pet per minute~~ Fixed 2026-10-13: `event_utils._monster_field` caches the field per module version and species

- **What**: each simulated minute `OfflineWorld.advance` runs the scheduled-encounter check (`services/android_offline.py:371`). `utils/event_utils.scheduled_event` (`:240-266`) asks `_monster_field(pet, module, "encounter_time_group")` for every awake pet, even when the module has no schedule (`schedule` is read at `:252` but only checked afterwards). `_monster_field` (`:76-86`) falls back to `module.get_monster` whenever the pet's own value is None, which is the case for every form outside the Godzilla devices. `GameModule.get_monster` (`models/game_module.py:728`) opens and parses monster.json on every call.
- **Measured** (development PC, 2 awake pets, six simulated hours): VB took 5.3 s for 720 parses of its 597 forms (about 7 ms each); DMC took 0.66 s; PENGZ took 0.03 s, because its forms carry the field.
  - Recovery runs before the first frame on a cold start (`on_load`) and on a warm resume, and its cost grows with the time spent closed. Three closed days with four awake VB pets come to about 17,000 parses, roughly two minutes on this PC and longer on a phone.
  - The seven-day forecast after every save does the same work: about 150 s for two VB pets here.
  - The open game makes the same lookup once a minute per pet, which costs nothing noticeable.
- **Tests**: `test_android_offline_cost.py::OfflineCost::test_a_quiet_half_day_does_not_reread_monster_records_every_minute` (xfail). It counts 1440 lookups for 2 pets over 12 hours, against an allowance of 24. The parity tests serve records from one parse (`android_parity.cache_records`), so they stay fast and give the same results.
- **Checklist**: BLD-06 / AND-03 (forecast, seven days) and AND-01 (recovery).
- **Suggested fix**: in `scheduled_event`, `continue` when `schedule` is empty before calling `_monster_field`. Also make `_monster_field` trust a pet that has the attribute (`hasattr` rather than `is not None`), since `set_data` always sets `encounter_time_group`. Caching parsed records in `GameModule` would also help every other caller.

## ~~A3. Clock set back past the wake time: a sleeping pet sleeps a further day when closed~~ Fixed 2026-10-17: a nap start later than the clock becomes the clock's time, in `OfflinePet.check_wake_up` and `GamePet.check_wake_up` alike, so both wake at the next wake time and count DP from the hours actually slept (the test is now a plain regression test). N1 (below) is still open

- **What**: `OfflinePet.check_wake_up` wakes the pet at the first wake time after `sleep_start_time` (`services/android_offline.py:111-113`). `GamePet.check_wake_up` wakes it whenever the clock shows the wake minute (`models/game_pet.py:2262`). Suppose the device clock is set back past the wake time during a nap, so the nap started "after" the current clock time.
  - **Open**: the pet wakes at the next 07:00 on the clock. It gets no DP, because the slept time comes out negative.
  - **Closed**: the pet stays asleep until 07:00 the day after its sleep start, a further 24 hours, with no hunger drain and no calls the open game would have.
- **Reproduce**: a pet napping since 21:00 and waking at 07:00. The clock is set back to 02:00 the same day, then the app stays closed for 6 hours. The open pet is idle at 08:00; the closed one is still `nap`.
- **Test**: `test_android_clock_changes.py::ClockSetBackWhileAsleep` (xfail).
- **Checklist**: AND-09.
- **Severity**: low. It needs a manual clock change of more than about 14 hours back while a pet sleeps.
- **Suggested fix**: wake when the minute crosses the wake time on the clock, whatever the sleep start. One way is `previous_now < wake_boundary <= now`, with the boundary taken from `now.date()`. Another is to treat a `sleep_start_time` later than `now` as `now`.

## Observations (no test; for the owner)

- **N1, the open game's wake rule (foreground)**: `GamePet.check_wake_up` only wakes at the exact wake minute (`game_pet.py:2262`). If the clock jumps past the wake time while a pet sleeps (clock set forward, or travelling east with the app open), the open game keeps it asleep until the next day's wake time. The closed run wakes it at its next checkpoint, so here open and closed differ the other way from A3. A fix for A3 that compares against the clock covers both.
- ~~**N2, hunger/strength death timers never fire (care area)**~~ Fixed 2026-10-17 (decision 17): the empty minutes are counted apart (`hunger_empty_minutes`, `strength_empty_minutes`, open and closed alike) and each module follows its manual (`death_rules_from_manuals_20261017.py`, `tests/unit/care/test_hunger_strength_deaths.py`). The finding: `update_care_mistakes` stops `care_food_mistake_timer` and `care_strength_mistake_timer` at `meat_care_mistake_time`/`protein_care_mistake_time` (`game_pet.py:1565-1567`, and the same for strength). `check_death_conditions` needs them above `death_hunger_timer`/`death_strength_timer` (`game_pet.py:948-951`). Those are 600-10000 minutes in every release module that sets them, against mistake times of 3-90, so death by 12 hours of hunger or strength cannot happen. Open and closed agree, so this is not an Android bug; it is listed for the care tests.
- **N3, transient states**: the closed run keeps a pet's last transient state (`sick`, `happy1` after an evolution) where the open game's animation returns it to idle after four seconds. `android_apply_offline` shows every such state as idle, so the player never sees the difference. The parity tests compare states as recovery presents them (`android_parity.care_state`).

## Coverage added (2026-10-13)

| File | Rows | What it decides |
|---|---|---|
| `test_android_module_parity.py` | AND-10, AND-01 | For every release module (DW1 for its below-minimum weight rule only), one day and one night lived open (`GamePet.update` on a virtual clock) and closed (`OfflineWorld`) agree hourly on every care field (`android_parity.PET_FIELDS`), the minute phase, poops, traited eggs, G-Cell fragments and evolution unlocks. The traits each life is meant to meet are asserted too, so a data change cannot make it pass trivially. |
| `test_android_clock_changes.py` | AND-09 | DST (New York, plus the midnight changes in Santiago, Beirut and Havana) open/closed parity with an exact minute count; a timezone change between close and open; an unknown zone; the clock set back or forward within a boot and across a reboot; ten days with no cap; no native clock; SDL's suspension fallback; `elapsed_since` edge cases. |
| `test_android_forecast_isolation.py` | AND-03 | The forecast leaves live pets, globals, quests, modules, presentation state, the RNG, files, network, save, outbox and console untouched; one seven-day plan equal to recovery's result; a superseded or failing forecast publishes nothing. |
| `test_android_offline_cost.py` | AND-03, AND-01 | Monster-record lookups per simulated minute (A2). |
