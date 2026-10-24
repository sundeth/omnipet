# Battle findings

Bugs and gaps the battle-mode tests found (checklist BAT-02, BAT-03, BAT-04, BAT-06). Each has the test that shows it, marked `@unittest.expectedFailure` until fixed; when a fix lands the test passes unexpectedly and its marker comes off. Line numbers are from the working tree of 2026-10-13 (`src/models/game_pet.py` was being edited by another agent at the time, so use the function names if the numbers have moved). Fixed entries are struck through with the date, not deleted, until the next release pass.

Test files: `tests/game/battle/test_adventure_every_area.py`, `test_adventure_rewards.py`, `test_adventure_scene_flow.py`, `test_versus_formats.py`, `test_dcom_fake_device.py` (shared driver `battle_flow.py`), `tests/unit/battle/test_release_battle_gates.py`.

## Summary

| Id | Severity | Mode | What | Test |
|---|---|---|---|---|
| ~~BAT-F1~~ | High | Adventure, Versus | ~~A fresh DMM pet has no `battles`/`win`: its first battle raises `AttributeError`~~ Fixed 2026-10-13 | `test_adventure_rewards.py::test_a_fresh_pet_can_battle` |
| ~~BAT-F2~~ | High | DCom | ~~A press during the half-second after the charge cancels the DCom battle~~ Fixed 2026-10-13 | `test_dcom_fake_device.py::test_a_press_after_the_charge_does_not_cancel_the_battle` |
| ~~BAT-F3~~ | Medium | Adventure | ~~`injury_probability` is never loaded, so no species injury roll ever happens (DMM, IC)~~ Fixed 2026-10-13 | `test_adventure_rewards.py::test_the_species_injury_chance_is_honoured`, `::test_DMM_sickness_chances`; `test_release_battle_gates.py::test_a_species_injury_chance_reaches_the_pet` |
| ~~BAT-F4~~ | Medium | Adventure | ~~A win that spends the last DP/Hunger records no progress, no victory, plays "fail"~~ Fixed 2026-10-13 | `test_adventure_rewards.py::test_a_win_with_the_last_dp_still_counts` |
| ~~BAT-F5~~ | High (known) | Versus | ~~PENC/DMXW/PENZ pets are prepared for DMC/DMX (compatibility, wrong charge)~~ Fixed 2026-10-14 | `test_versus_formats.py::test_the_payload_is_built_for_the_chosen_format` |
| BAT-F6 | High (known) | Versus | Every versus battle needs the DMC module installed | `test_versus_formats.py::test_versus_does_not_need_the_dmc_module` |
| ~~BAT-F7~~ | Medium | Versus | ~~With part of the party selected, the wrong two pets fight~~ Fixed 2026-10-13 | `test_versus_formats.py::test_the_picked_pets_are_the_ones_that_fight` |
| ~~BAT-F8~~ | Release gate (known, BAT-06) | Versus, DCom | ~~TWIN is still offered in the protocol grid~~ Fixed 2026-10-13 | `test_versus_formats.py::test_twin_is_not_offered_in_the_versus_grid`, `test_dcom_fake_device.py::test_twin_is_not_offered_in_the_dcom_grid`, `test_release_battle_gates.py::test_only_battle_formats_are_selectable_for_the_release` |
| ~~BAT-F9~~ | Medium | Adventure | ~~`adventure` unlocks ignore their `version`: clearing VBE area 1 with a Ver.1 pet grants the Ver.18-22 character unlocks~~ Fixed 2026-10-15 | `test_adventure_rewards.py::test_VBE_boss_win_opens_the_next_area` |
| ~~BAT-F10~~ | High | WiFi-Com | ~~No WiFi-Com battle ever opened: a turn-2 DigiROM (the role a cable takes on most lines) was answered in the wrong role, its `^`/`@` left unresolved and the stalled session kept; the line was inferred from the ROM and the pet's module; no charge; a malformed request or a changed secrets file broke the session; a dropped connection still read Online~~ Fixed 2026-10-21 | `test_wificom_fake.py` (every format, native and compatibility; punchbags), `unit/battle/test_wificom.py` |

## ~~BAT-F1 — a fresh pet of a counts-keeping module has no battle record (High; BAT-03, BAT-04)~~ Fixed 2026-10-13: `GamePet.reset_variables` and `patch()` give every pet a record

**What.** `GamePet.reset_variables` sets `self.win = self.battles = 0` only when the module's `battle_keep_counts_on_evolution` is false, and `GamePet.__init__` never sets them (it does set `event_communications`, the other kept count, at line 49). On a module that keeps its counts the attributes never exist: the first `finish_battle` (`self.battles += 1`, game_pet.py:2106) or `finish_versus` (2083) raises `AttributeError`, as does an evolution route with a `battles` or `win_ratio` condition (game_pet.py:1439). Nothing in `game_globals.load` or `GamePet.patch` supplies them, so a saved pet does not recover.

**Who.** DMM in the 1.0 release (`battle_keep_counts_on_evolution: true`); also ACCEL, PENPROG, PENX and TWIN. An egg hatched in scene_eggselection.py:1418 goes through the same constructor.

**Reproduce.** `pet = GamePet(dict(<DMM Child record>, module="DMM"))`; `hasattr(pet, "battles")` is False; fight any adventure battle: the exception is raised from `BattleEncounter.update_charge` -> `process_battle_results` -> `finish_battle`, outside any handler, so the game crashes.

**Fix.** Initialise `self.win = self.battles = 0` in `__init__` before `reset_variables()` (as `event_communications` already is), and add both to `GamePet.patch()` for existing saves. Same pattern in `services/android_pet_rules.py:91`.

The other battle tests give their pets a record by hand (`battle_flow.ensure_battle_record`) so they test the battle, not this.

## ~~BAT-F2 — a press after the DCom charge abandons the battle (High; BAT-04)~~ Fixed 2026-10-13: `UIManager` ignores a focused component that is hidden

**What.** `DComView._start_minigame` hides the CANCEL button (dcom_view.py:427) but it keeps the UI manager's focus. When the charge ends, `_finish_minigame` sets `self.minigame = None` (438) and waits half a second (441) before the exchange. During that wait `SceneConnect.handle_event` no longer routes input to the view (scene_connect.py:355 requires `minigame`), so the next A press reaches the UI manager, which activates the focused, invisible CANCEL: `_on_cancel` disconnects the adapter and goes back to the Connect menu. The comment on the settle says it exists so "the last press of a mashed minigame cannot fall through onto whatever is drawn next" -- it falls through onto a button that is not drawn.

**Who.** Every DCom line whose charge is mashed with A: DM20 (Dummy Bar), DMM (Count Bar), IC (RPM), DMX (Xai Roll+Bar), DMXW (Xai Bar). A player mashing at five presses a second almost always lands one in the window. Shake charges (PENOG, PEN20, PENZ, PENC) send Y, which no button takes.

**Reproduce.** The test: DM20 over the fake adapter, A pressed every 6 frames through the charge and on until the battle would start; the view ends on `main_menu` and no command is ever sent.

**Fix.** Swallow input in the view while `_minigame_settle_at` is set (or keep `phase == "minigame"` routing in SceneConnect until the settle ends), and do not leave focus on a hidden button (`set_focused_component(None)` or disable CANCEL while it is hidden). A UIManager rule that invisible components never take A would close the whole class.

## ~~BAT-F3 — the species injury chance is never loaded (Medium; BAT-03)~~ Fixed 2026-10-13: `GamePet.set_data` loads `injury_probability`

**What.** `finish_battle` rolls a loss's injury from `getattr(self, "injury_probability", 0)` (game_pet.py:2155), but `GamePet.set_data` (134-204) never copies `injury_probability` from the monster record, so the roll always reads 0. The data is there: 47 DMM and 110 IC Digimon carry it, and the module editor writes it (`Pet.cs:97`).

**Effect.** DMM (`battle_base_sick_chance_lose: 0`) never injures a pet on a loss, where the Digimon Mini injures at 10%; iC Digimon lose their own 5-25% and keep only the module's 10%.

**Reproduce.** DMM Child, settled loss, every `random()` at 0.05 (under its 10%): the pet stays healthy. Unit form: `GamePet.__new__(GamePet).set_data({... "injury_probability": 10})` leaves no attribute.

**Fix.** `self.injury_probability = int(data.get("injury_probability", 0) or 0)` in `set_data` (it then follows evolutions); pets already saved pick it up on their next evolution, or refresh it in `patch()` from the module record.

## ~~BAT-F4 — a win that spends the last of the battle cost records nothing (Medium; BAT-03)~~ Fixed 2026-10-13: `update_result` records a non-boss win before retiring

**What.** `BattleEncounter.update_result` takes `pets = get_battle_continue_targets()` (battle_encounter.py:2803) and, on a non-boss Victory with no pet able to continue (2806), plays "fail" and the retire animation and returns (2809) -- before the round counter, `battle_round`/`battle_area`, `total_victories`, the `battle` unlocks and the `area_clear` events are touched. The pet has already been paid (XP, prize, currency, win count), but the player's progress is not.

**Effect.** On a module that fights one battle at a time and charges DP (DM20, PEN20, DMOG), winning with the last DP leaves the player on the area just won: DM20 area 1 won with 1 DP stays at area 1 instead of area 2, and the win does not count towards `battle` unlocks. On a sequential module the round just won is not saved either (`_check_retire_or_proceed` saves it in the same situation reached after feeding, battle_encounter.py:3026). The "fail" sound plays after a win.

**Reproduce.** The test: DM20/PEN20/DMOG Child with `dp = battle_cost_amount`, settled win on area 1 round 1: `battle_area`/`battle_round` unchanged, `total_victories` unchanged, phase `retire_animation`.

**Fix.** Do the round/area bookkeeping first and only then retire when no pet can continue -- or move the `len(pets) == 0` check into the sequential branch, where there is a next round to refuse.

## ~~BAT-F5 — Versus prepares PENC, DMXW and PENZ pets for another line (High, known; BAT-02, BAT-04)~~ Fixed 2026-10-14: `fixed_charge` and `simulate_combat` use `self.battle_format`

Already in the battle review (`utilities/codex/battle-system-review-2026-09-20.md`, finding 1); this pins it with a test. `BattleEncounterVersus.simulate_combat` (battle_encounter_versus.py:219) and `fixed_charge` (214) look the format up as `BATTLE_FORMATS.get(self.protocol, 'DM20')`, a map from the shared `BattleProtocol` enum, instead of `self.battle_format`. PENC and DMXW share `DMC_BS`, PENZ shares `DMX_BS`, so a PENC versus converts both pets as DMC compatibility pets (index 0, `compatibility=True`) with charge 3 instead of PENC's `VERSUS_CHARGE` 2 (DMXW: 1; PENZ: DMX's version 1 instead of its own 0). Measured: `pet_to_digimon` called with `('DMC', 3)` twice for a PENC battle. **Fix:** use `self.battle_format` in both places.

## ~~BAT-F6 — every Versus battle needs the DMC module (High, known; BAT-02)~~ Fixed 2026-10-17: the encounter is built on the first pet's module (always installed, as DCom builds on the player's); each pet keeps its own rules through `finish_versus` (the test is now a plain regression test)

Review finding 2. `BattleEncounterVersus.__init__` builds the encounter on `module = "DMC"` (battle_encounter_versus.py:36); `get_module` is a plain dict lookup, so with DMC not installed every versus battle raises `KeyError: 'DMC'`, whatever line was chosen and whichever modules the pets belong to. CLAUDE.md: each physical protocol must work without its native module -- here it even needs a different one. **Fix:** give the versus encounter a module-independent rules/presentation context (or the first pet's module) and look DMC up only for optional artwork.

## ~~BAT-F7 — VERSUS fights the wrong pets when only part of the party is selected (Medium; BAT-04)~~ Fixed 2026-10-13: `VersusView` reads the tapped pets from its own selector

**What.** `VersusView` lists `get_selected_pets()` -- the pets selected in the main game, or the whole party -- and records the tapped cells as indices into that list, but `_on_confirm` reads `game_globals.pet_list[index]` (versus_view.py:201-202). Whenever the selection is not the start of the party (or a dead pet or egg is filtered out of it) the protocol grid, and the battle, get other pets than the two shown and tapped.

**Reproduce.** Party of four, `runtime_globals.selected_pets = [pet 3, pet 4]`; VERSUS shows pets 3 and 4; tap both, CONFIRM: `ProtocolView.pet1/pet2` are pets 1 and 2.

**Fix.** `pet1 = self.pet_selector.pets[self.selected_pets[0]]` (and the same for pet2).

## ~~BAT-F8 — TWIN is still offered (release gate BAT-06, known)~~ Fixed 2026-10-13: `menu_entries()` offers upcoming lines only in debug mode

`protocol_constants.OFFERED_UPCOMING = ('TWIN',)` (protocol_constants.py:2137) enables TWIN's box in both protocol grids. Versus refuses it with "TWIN is not ready yet" and DCom only records a capture (both pass in `test_choosing_twin_*`), so it cannot be fought -- but BAT-06 wants unfinished lines not selectable for 1.0. Already listed in `release-1.0.md` (BAT-06 ❌). **Fix:** empty `OFFERED_UPCOMING` for the release build.

## ~~BAT-F9 — adventure unlocks ignore their version (Medium; BAT-03)~~ Fixed 2026-10-15: the loop skips a record whose version is not one of the winning pets' (0 counts as every version on a module with no version-0 Digimon, the test's rule)

**What.** The `adventure` unlock loop in `update_result` (battle_encounter.py:2839-2857) grants every `adventure` unlock whose `area` matches (or whose name a beaten enemy carries), whatever its `version`. module-rules.md: "`version` selects gameplay evolutions/unlocks", and the game honours it elsewhere (egg unlocks: utils_unlocks.py:52, scene_eggselection.py:1461; area locks: `GameModule.is_area_unlocked`).

**Effect.** VBE's 141 adventure unlocks are per version (`area_1_ver_22` "Maurice Shoemaker", version 22, area 1, and so on): a Ver.1 pet clearing area 1 unlocks the Ver.18, 20, 21, 22... characters as well. VB, VH, DMGZ, DMH and D-3 also scope adventure unlocks by version; DMC, DMX, DMXW, IC, PEN20, PENC, PENGZ do not.

**Decision needed before the fix.** D-3 writes `version: 0` on unlocks that are plainly for every version (the area-1 background "beach", "bambu", "sakura", "dark_ocean"), and D-3 has no version-0 Digimon. A strict check (`version is None or version == pet.version`) would make those unreachable. The test treats `0` as unscoped only on a module that has no version-0 Digimon (PEN lines do use a real version 0). Either make D-3's data `null`, or define 0 as "every version" where no version-0 Digimon exists. Then filter the loop by the pets' versions (`team1`) -- note the encounter is always built with `version=1` (adventure_battle_view.py:42-46), so it cannot use `self.version`.

## ~~BAT-F10 — the between-round Food menu vanishes after one feed (Medium)~~ Fixed 2026-10-17: a fresh Menu is opened for the next choice (`test_battle_view_menus.py`)

Found while adding the battle item list. `AdventureBattleView._on_feeding_select` reopened `self._menu` from inside the menu's own `on_select`, and `Menu.handle_event` closes the menu after `on_select` returns, so after one Food the menu disappeared with the phase still "feeding": nothing on screen, and only B (Next) went on. The battle item lists open a new Menu each time for the same reason.

## Notes (not bugs in the game)

- **Harness wall clock.** The fixture party (DMC Agumon, PENC Angoramon, IC Agumon, VB Pulsemon) keeps its module bedtimes, 20:00-08:00, and `GamePet.should_sleep` reads `datetime.now()`. Any harness test that battles or trains the fixture party is refused at night (`battle_block_reason`: asleep). These tests build their own pets with `sleeps`/`wakes` cleared (`battle_flow.battle_pet`). Worth doing in `harness._party` too.
- **MOD-01.** PENGZ has no `BattleIcon.png`; the module selection and the HP bar log `Failed to load ... BattleIcon` for it (and for DW1). Filtered out of these tests' error checks as a known asset gap (`battle_flow.KNOWN_ASSET_LOGS`); the module audit owns it.
- **Not covered.** Real hardware in either direction (BAT-02 manual), a stock-firmware `(paused)` refusal on the IC infrared wire, WiFi battles (review finding 3), the real wificom.dev service and a real device behind it (WiFi-Com is covered against a fake wificom.dev by `game/battle/test_wificom_fake.py` and `unit/battle/test_wificom.py`; BAT-07 still holds it back), Arena (covered by `test_arena*.py`), and DW1 (being built).
