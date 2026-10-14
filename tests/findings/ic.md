# Findings: Digivice iC custom systems (ICX)

Found by the iC tests (`tests/unit/ic/`, `tests/game/ic/`) on 2026-10-13, for the 1.0 release pass. Each bug has a test written with the expected behaviour and marked `@unittest.expectedFailure` until it is fixed. When a fix makes that test pass, take the marker off and strike the entry through with the date.

## Bugs

### ~~1. A connection win gives no Reliability (ICX-01)~~ Fixed 2026-10-13 (the test is now a plain regression test)

- **What:** winning a DCom battle against a real device, or an online (WiFi/Omninet) PvP battle, never applies the module's `reliability_battle_win` (+1 on the iC). An adventure win (`GamePet.finish_battle`) and a local Versus win (`GamePet.finish_versus`) do apply it. The iC's battles are mostly connection battles, and the 10X playbook's row is "Win a battle: +1, once for every victory" (utilities/IC/IC_RESEARCH_AND_TODO.md, "Exact 10X changes").
- **Where:** `src/battle/battle_encounter_dcom.py:394` `update_result`: the result loop (lines 419-435) adds `pvp_wins`, takes the battle cost and builds `connection_results` for Connect Points and the connection events, but has no Reliability call. The same applies to `src/battle/battle_encounter.py:2663` `update_result`, the `pvp_mode` loop at lines 2698-2717.
- **Reproduce:** `tests/unit/ic/test_ic_reliability.py::ConnectionBattleTests::test_a_connection_win_gives_one` runs `BattleEncounterDCom.update_result` on a won battle. The iC pet keeps 15; it should have 16. Its sibling `test_the_result_path_counts_the_win` shows that the same path does count the win (pvp_wins, Connect Points, the DigiShop opening, the hunger cost).
- **Suggested fix:** in both loops, `if local_won: pet.pvp_wins += 1; pet._apply_reliability_event('reliability_battle_win')`. Every non-iC module has the field at 0, so nothing else changes.
- **Severity:** medium. The iC's high-Reliability routes and the Reliability 31 Just Attack rely on battle wins as the main way to gain Reliability.

### ~~2. Two saves in the same second: load can pick the older one (ICX-11)~~ Fixed 2026-10-13: `game_globals._saves_newest_first` breaks a time tie by the save rotation (the test is now a plain regression test)

- **What:** `load()` takes the save file with the newest modification time. When two files tie, it keeps them in directory order. On a file system that stores modification times in coarse steps, two saves written within one step get the same mtime, and the older save can load. This PC's `E:` drive is exFAT: every save's mtime came out rounded to 2 s, and pushed into the future. `save_data_1` (from the fixture) and a `save_data_2` written moments later had the same mtime, and `load()` took `save_data_1`. In play, the autosave (every 60 s) followed within 2 s by a save on entering a Coliseum (`adventure_area_selection_view.py:265`, after its fee is paid) or on quitting means the next launch loads the earlier state. Whatever happened in between is lost: Fight Money paid, an item bought, an evolution. FAT32/exFAT are what USB sticks and SD cards use; NTFS, ext4 and f2fs are not affected in practice.
- **Where:** `src/core/game_globals.py:823` (`load`: `all_saves.sort(key=getmtime, reverse=True)`). The same tie-break is in `get_latest_save_file` (line 614, which picks the next save number) and `cleanup_old_saves` (line 636, which removes the "oldest").
- **Reproduce:** `tests/game/ic/test_ic_persistence.py::ICPersistenceTests::test_the_newer_of_two_saves_in_the_same_second_loads` gives two saves (100 P, then 300 P) the same mtime and lists names in ascending order, as NTFS and exFAT do. `load()` returns 100 P where it should return 300 P. The other persistence tests move older saves an hour back (`age_saves`) so that this bug does not affect them.
- **Suggested fix:** write a save sequence number (or `time.time_ns()`) into each save's data and choose the newest by it, falling back to mtime for old saves. Or break mtime ties by save number in rotation order: the number that follows the newest wraps at `MAX_BACKUPS`, so 1 follows 10. Use the same key in `get_latest_save_file` and `cleanup_old_saves`.
- **Severity:** low to medium. At most about 2 s of play is lost, but the loss is silent, and it can include a purchase or a paid fee.

## Gaps and owner questions (not marked as bugs)

- **Bedtime care mistakes repeat (known, ICX-10).** With the lights left on, `update_care_mistakes` records a care mistake every 3 minutes (`care_sleep_care_mistake_timer`). The research notes record the device's bedtime call as one-shot (IC_RESEARCH_AND_TODO.md "Not implemented yet" item 17). The tests check only what is settled: the first mistake comes after 3 minutes, and Reliability is lost once a night (`test_ic_reliability.py::CallTests::test_an_ignored_bedtime_call_costs_one_each_night` and the Android parity test). They do not assert whether later mistakes repeat.
- **"Answering a call" covers hunger and bedtime only (ICX-01).** The playbook also lists evolution and dying as calls. A death save by B presses or an evolution gives no +1. This is unverified on hardware and not tested.
- **Ordinary training gives the iC Reliability (ICX-01).** `GamePet.finish_training(won=True)` applies `reliability_minigame_success`, so any won standard training (Dummy Bar and others) raises an iC pet's Reliability by 1, at no cost. On the device, only the minigames do this, and each costs a heart of hunger (`training/ic_minigame.py`). Is this intended? Tested as the code behaves now (`MinigameTests`).
- **The poop-sickness threshold grows with the party (ICX-10).** It is `care_poop_sickness_count * max(1, len(pet_list) - 1)`: 6 poops for one or two pets, 12 for three, 18 for four (`src/models/game_pet.py:1531`, the same in `services/android_pet_rules.py:605`). Only the single-pet case (6, Dots) is tested.
- **No event opens DigiShop 1 for a 20X pet (ICX-07, data).** `shop.json`'s DigiShop 1 has a 20X price (Level Reverse 1500 P, `versions: [2]`), and the research notes say the owner's 20X has DigiShop 1 open. Yet `events.json`'s DigiShop 1 event is `versions: [1]` only. A 20X pet sees DigiShop 1 only if a 10X pet in the same save opened it, because shop access is kept per module.

## What the tests could not cover

- Real devices: DCom against an iC or Burst (ICX-07 manual). The connection win is simulated through `event_utils.after_connection` and `BattleEncounterDCom.update_result`, the code the result screens call.
- An Android device: the offline run uses `services.android_offline` on the desktop, the same way `tests/unit/android/test_android_offline.py` does. Native notifications and the JNI clock are patched out.
- Progress Mode with a real Omninet login. The test sets the player id itself and makes no network call.
