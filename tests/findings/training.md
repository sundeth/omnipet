# Training findings

Bugs and gaps found by the training minigame outcome tests (TRN-02, TRN-03, ICX-09), 2026-10-13. Each bug has a test written with the correct expectation and marked `@unittest.expectedFailure`; when the bug is fixed the test passes unexpectedly and the marker comes off. Strike an entry through with the date when it is fixed.

Tests: `tests/game/training/test_minigame_outcomes.py` (the ten training-menu minigames), `tests/game/training/test_bonus_minigame_outcomes.py` (the iC Bonus minigames), `tests/unit/training/test_training_rewards_by_module.py` (`GamePet.finish_training` for every module's tables).

## Bugs

### ~~1. Excite pays a Good stop as Great (TRN-03)~~ Fixed 2026-10-13 (the test is now a plain regression test)

- **What:** stopping the Xai bar on blue (the bar's own result 1, Good) gives the training grade 2, so every pet is paid the Great row of its tables (DMX: +2 Strength and 6 weight lost instead of +1 and 2; the iC's Fight Money 20 instead of 10). Good is unreachable. The method's own comment says the bar's 0-3 "is exactly the Digital Monster X's Bad / Good / Great / Excellent".
- **Where:** `src/training/excite_training.py:189-198`, `ExciteTraining.get_attack_count`: `elif strength < 3: return 2`.
- **Reproduce:** Excite with a DMX pet first, stop the arrow over the blue zone: `result grade 2`.
- **Test:** `test_minigame_outcomes.py::test_excite_blue_is_good`.
- **Fix:** return the bar's value (`return max(0, min(3, strength or 0))`).

### ~~2. Count Match Classic: shaking past 14 loses the trophy (TRN-03)~~ Fixed 2026-10-13 (the test is now a plain regression test)

- **What:** the meter now counts to 40 (`CountMatchClassic.max_strength`), the training grades anything from 14 EXCELLENT and the result screen draws "+1 trophy" from 14 up (`draw_result`: `>= 14`), but the trophy is only awarded at exactly 14. A player who keeps shaking (the natural way to play a shake meter) sees the trophy promised and does not get it.
- **Where:** `src/training/count_classic_training.py:121`, `check_and_award_trophies`: `if self.strength == 14`.
- **Reproduce:** Count Match Classic, 20 shakes: grade 3, trophies unchanged.
- **Test:** `test_minigame_outcomes.py::test_count_match_classic_shaking_past_fourteen_keeps_the_trophy`.
- **Fix:** `if self.strength >= 14`. (See also note d below on the 0-14 bands.)

### ~~3. Head to Head never shows the currency screen (TRN-03)~~ Fixed 2026-10-13 (the test is now a plain regression test)

- **What:** with an iC pet in the party a won Head to Head pays Fight Money, and `finish_training` opens the currency screen ("+50P GET!"), but on the very same frame `HeadToHeadTraining.update` sees the head charge complete and the phase not "result", and sets it back to "result". The player gets a second result screen instead of the currency screen. The money itself is paid once (correct).
- **Where:** `src/training/head_training.py:45-47` (`if self.head_charge.is_complete() and self.phase != "result"`).
- **Reproduce:** party DMC + IC, Head to Head, win all five strikes: right after the result is applied the phase is "result", never "currency".
- **Test:** `test_minigame_outcomes.py::test_head_to_head_shows_the_currency_it_earned`.
- **Fix:** only move to the result from the charge: `if self.head_charge.is_complete() and self.phase == "charge":`.

### 4. Mogera's verdict and grade disagree (TRN-03)

- **What:** `check_victory` reads only the charge (`strength >= 7`) while `get_attack_count` needs all five counters. So:
  - 3 or 4 counters and a full charge: the screen shows Mogera destroyed with GREAT/EXCELLENT, the verdict is a win (success sound, TRAINING quest step, Reliability, DMGZ's success G-Cells, the disturbance penalty forgiven, a happy pet) but the grade is 0, so effort/Strength/weight come from the failure row and the iC is paid nothing.
  - 5 counters and a weak charge: grade 1 (Good) but the verdict is a loss, so the Good grade is never paid (the pet gets the failure row; DMGZ's phase-2 failure G-Cells, which is right for that device).
  Every other minigame keeps `won == (grade > 0)`.
- **Where:** `src/training/mogera_training.py:222-224` (`check_victory`) and `:417-425` (`get_attack_count`); the counter phase lets 3-4 counters through to the charge at `:112`.
- **Reproduce:** Mogera, counter 4 of 5, then press A 12 times: `won=True grade=0`.
- **Test:** `test_minigame_outcomes.py::test_mogera_verdict_and_grade_agree` (the passing `test_mogera_a_weak_charge_after_the_counters_is_a_phase_two_failure` pins what the 5-counter/weak-charge case pays today).
- **Fix (needs the owner's rule):** decide what 3-4 counters with a destroyed Mogera is worth and make both methods read the same thing, e.g. `check_victory` = `get_attack_count() > 0`, with `get_attack_count` grading 3-4 counters + charge >= 7 as Great; and either drop the Good for 5 counters + weak charge or make it a win.

### ~~5. SEL-NEED crashes the training menu (TRN-02)~~ Fixed 2026-10-13 (the test is now a plain regression test)

- **What:** with the inventory's selection strategy switched to NEED (`runtime_globals.strategy_index = 1`, the inventory's SEL-NEED button), opening Training with a pet at 16 effort and Strength below 4 raises `AttributeError: 'GameModule' object has no attribute 'training_strengh_gain_win'` while the scene is built (`SceneTraining.setup_ui` -> `get_training_targets`). The misspelled field is a module.json key the loader folds into the `training_strength_gain` table; the GameModule never has it as an attribute.
- **Where:** `src/utils/pet_utils.py:32` (`get_training_targets`, NEED branch).
- **Reproduce:** fixture party, `rg.strategy_index = 1`, first pet `effort = 16, strength = 0`, `env.game("training")` raises.
- **Test:** `test_training_rewards_by_module.py::test_the_need_selection_lists_a_pet_that_still_gains_strength` (the passing `test_the_need_selection_never_breaks_choosing_who_trains` covers the short-circuit cases).
- **Fix:** read the table: `max(get_module(pet.module).training_strength_gain[1:]) > 0` (a won training gains Strength).

## Notes for the owner (no test asserts these; worth a decision)

- **a. PEN20's Megahit fills Strength to the stomach, 24.** `training_strength_gain[3] = -1` ("fills the meter") sets `strength = stomach` (`src/models/game_pet.py:2058`); a PEN20 pet's stomach is 24 while its device shows 4 fixed hearts (`care_fixed_4_hearts`), so Strength reads 24 until the next drain trims it to 4. The tests only assert the meter is full (>= 4). Protein feeding uses the same `stomach` cap.
- **b. Head to Head trains the whole selection.** Two pets fight (`select_pets`), but every selected pet that can train gets the result, the trophy and the tables (`Training.pets = get_training_targets()`, `src/training/training.py:83`). Head to Head also awards a trophy for any win (`head_training.py:100-105`), where the other minigames award it only at the top grade (Punch: 1 at Great, 2 at Excellent). The tests pin today's rule.
- **c. Head to Head has no time limit.** With no input it waits on the first strike forever; EXIT/B leaves. Every other minigame ends on its own clock.
- **d. Count Match Classic is banded twice.** Training grades the raw shake count on the old 0-14 bands (11-12 Good, 13 Great, 14+ Excellent), the battle charge (`minigame_session.minigame_result`) on 0-40 (29-34 Good ... 40 Excellent). The same 20 shakes are EXCELLENT in training and BAD in a battle. The tests pin the training's 0-14 bands; if the training should follow the 40-step meter, they need updating with it.
- **e. Count Bar's Megahit trophy goes to every pet,** including one whose own row failed (count 24: a stage 3 pet's Megahit, a stage 6 pet's Bad); the trophy follows the first pet's row (`count_bar_training.py:184-189`).
- **f. One-frame input gap at the start of Count Bar and RPM.** The counter starts on the first charge-phase update, so a press delivered on the frame READY ends is swallowed. Harmless at 30/60 fps; the tests wait a frame.

## Not automated

- The ready sound's real length decides READY on a device with audio; the tests mute it so READY runs on the fake clock (`ALERT_DURATION_FRAMES`/the asset's duration).
- Real shake input (accelerometer on Android, the Pi's I2C shake detector, the mouse/touch shake gesture of `ShakeDetector`) is not driven; the tests send the `Y`/`SHAKE` actions those produce.
- Gotcha! (Bonus list) has no minigame yet (`cls` None); `test_training_menu.py` covers that it does not start.
