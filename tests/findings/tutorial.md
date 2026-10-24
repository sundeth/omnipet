# Tutorial findings

Bugs and gaps found by the tutorial crawler (UI-11), 2026-10-24. The crawler plays the tutorial as a player does (keyboard, mouse, touch; from Settings' Replay, a first run and a fresh build's first run that ends in the shop), fumbles at every step and skips at every step; see the docstring of `tests/release/tutorial_crawl.py`. Each entry names the crawl finding that shows it (`python -B tests/release/tutorial_crawl.py`, report in `tmp/release-reports/tutorial/tutorial_crawl.md`); when a bug is fixed the finding disappears from the report. Strike an entry through with the date when it is fixed.

## Bugs

### ~~1. Touch cannot do any main-menu step (UI-01, UI-11)~~

**Fixed 2026-10-24:** `TutorialMainGame.handle_event` takes a click's or tap's index from `self.menu.get_menu_index_at(pos)`.

- **What:** every step that asks for a main-menu icon (Status, Inventory twice, Clean, Training, Status again, Battle; Connect in the shop branch) ignores a tap on the highlighted icon and answers "cancel". A touch player (every Android player) cannot get past "Enter the Status Menu" and can only SKIP.
- **Where:** `src/scenes/tutorial_scenes/tutorial_maingame.py:62-65`, `TutorialMainGame.handle_event`: an `LCLICK` is judged by `runtime_globals.main_menu_index`, which only the pointer's hover sets (`SceneMainGame.update_mouse_hover`, MOUSE mode only); `SceneMainGame.handle_event`, which takes the index from the tap position (`self.menu.get_menu_index_at(pos)`), is never reached for these clicks. A tap leaves the index at -1.
- **Crawl:** `stuck` at steps 24, 51, 75, 104, 112, 139, 158 (and 193 in the shop fixtures), every touch run: "taps at (25, 29) did nothing; under it: main menu icon 0 (selected index -1)".
- **Fix:** for an `LCLICK` with a position, set `main_menu_index` from `self.menu.get_menu_index_at(pos)` before the allowed-index check.

### ~~2. On a non-square screen the main-menu highlight is not on the icons (UI-03, UI-11)~~

**Fixed 2026-10-24:** `SceneTutorial._focus_menu_icon` focuses `embedded_scene.menu.icon_rects[index]`, turned back into the overlay's base coordinates; every main-menu step uses it.

- **What:** on a non-square screen the main-menu highlight sits between or beside the icons. A click in it hits nothing or the neighbouring icon, which the tutorial refuses: by mouse, Status and Clean at 320x240, and Status, Inventory, Clean and Battle at 800x480. By keyboard the cursor reaches only the neighbouring icon for Status and Clean at 800x480; at 320x240 the Status highlight straddles Status and Inventory and the keyboard gets through only because its border just reaches Status's centre. (Touch fails these steps anyway, bug 1.)
- **Where:** `src/scenes/scene_tutorial.py:733-775` (`_get_menu_top_y`, `_focus_status_menu` ...): fixed 48-px slots of a 240 square, drawn in "global" mode (`:1193`), which `TutorialFocus` centres on the screen (`tutorial_focus.py:114`). The main game spreads its five icons over the whole width (`src/ui/windows/window_mainmenu.py:65-86`, `calculate_spacing`); the two agree only on square screens.
- **Crawl:** `stuck` in the 320x240 and 800x480 play runs: "taps at (64, 29) did nothing; under it: nothing" (mouse 320x240), "A did nothing; under it: main menu icon 1 (selected index 1)" (keyboard 800x480, at Status).
- **Fix:** focus the main-menu steps on `embedded_scene.menu.icon_rects[index]` (screen coordinates) instead of computed base slots.

### ~~3. B on the tutorial's battle menu leaves the tutorial with the tutorial's Digimon as the party (UI-11)~~

**Fixed 2026-10-24:** `TutorialBattle.handle_event` answers B with "cancel" unless a battle is in progress.

- **What:** at "Let's enter the tutorial's Adventure Mode" (and while GO and Fight are allowed), B or the menu's EXIT goes to the main game. The tutorial is gone, the Tutorial module stays loaded, and the party is the tutorial's Agumon instead of the player's (the next save keeps it).
- **Where:** `src/scenes/tutorial_scenes/tutorial_battle.py:263`: while any selection is allowed every event goes to `SceneBattle.handle_event`, whose views exit on B.
- **Crawl:** `escape` at step 167 (fumble keyboard, replay and shop): "B left the tutorial for SceneMainGame (the Tutorial module still loaded; the party is ['Agumon'])".
- **Fix:** answer B with "cancel" in `TutorialBattle.handle_event` unless a battle is in progress (as `TutorialStatus` does when exit is not allowed).

### ~~4. Any A in the training menu counts as choosing Dummy (UI-11)~~

**Fixed 2026-10-24:** the tutorial is notified only when the press moved the phase to "dummy".

- **What:** at "Enter the Dummy Charge Training", an A with the cursor on the pet row (`PetSelector`) starts nothing, but the tutorial moves on and waits for a charge phase that never comes: stuck.
- **Where:** `src/scenes/tutorial_scenes/tutorial_training.py:170-175`: `on_training_selected_callback` is called after every A or click while button selection is allowed, whatever it pressed.
- **Crawl:** `escape` at step 122 (fumble keyboard): "A on ... PetSelector@(91, 189), off the highlight, moved the tutorial on to step 123 focus_off as if enter_dummy_training had been done", then `stuck` at steps 125, 129, 130.
- **Fix:** notify only when the dummy training started (`self.phase == "dummy"` after the parent handled the press, or from `on_dummy_training`).

### ~~5. A second press between steps reaches the scene behind the tutorial (UI-11)~~

**Fixed 2026-10-24:** `notify_action` sets `block_scene_input`; only the next UNBLOCK step lets input through.

- **What:** after an action is done, the tutorial lets input through to the embedded scene until its next BLOCK step. A double click on Adventure (mouse) presses the next view's GO before the tutorial has hooked it: the view moves on, the tutorial waits for GO forever. A double tap on the Connect menu's Shop (touch, shop branch) opens Specials: the tutorial waits for the Modules view forever and the module is never bought.
- **Where:** `src/scenes/scene_tutorial.py:1488-1491`: with no action awaited and `block_scene_input` still False from the last UNBLOCK step, the event goes to the embedded scene.
- **Crawl:** `escape` at step 168 (fumble mouse): "tap (120, 132) moved TutorialBattle / adventure_area_selection on (from adventure_module_selection) without the tutorial, which waited for nothing", then `stuck` at 174; `escape` at step 205 (fumble touch, shop), then `stuck` at 210, 214, 219 and the run ends in the shop with no module.
- **Fix:** block scene input when an awaited action is notified (in `notify_action`), so only the next UNBLOCK step lets input through again.

### ~~6. Skipping during the battle leaves the battle's return to the game hijacked (UI-11)~~

**Fixed 2026-10-24:** `_restore_game_state` (skip and finish) puts `battle_encounter.change_scene` back to `scene_utils.change_scene`, whichever scene is shown.

- **What:** START or SKIP while the tutorial's battle runs leaves `battle.battle_encounter.change_scene` patched by `TutorialBattle._patch_battle_encounter`. The next real adventure battle that ends calls the dead tutorial's callback instead of returning to the main game.
- **Where:** `src/scenes/scene_tutorial.py:1542-1547` (`skip_tutorial`) never calls `TutorialBattle._restore_change_scene`.
- **Crawl:** `end` in the skip runs at step 183: "skipping left battle_encounter.change_scene patched: the next battle's return to the game is swallowed".
- **Fix:** in `skip_tutorial` (or `_restore_game_state`), call the embedded scene's `_restore_change_scene` when it has one.

### ~~7. Skipping between the mess and the cleaning leaves the tutorial's poop in the player's game (UI-11)~~

**Fixed 2026-10-24:** the player's `poop_list` is kept with `original_pet_list` and put back on skip and finish.

- **What:** skipped from "Oh no! Koromon made a mess!" until the wash ends, the poop the tutorial forced stays in `poop_list` and is saved with the player's party (it can cost a care mistake).
- **Where:** `src/scenes/scene_tutorial.py:1549-1556`, `_restore_game_state` restores the party but not `poop_list`.
- **Crawl:** `save` in the skip runs at steps 100-106: "skipping changed the save's poop_list: +{...}".
- **Fix:** keep the player's `poop_list` with `original_pet_list` and put it back.

### ~~8. A stray press in module selection starts another module's real adventure (UI-11)~~

**Fixed 2026-10-24.** A fumbled A on another module's button (or LEFT/RIGHT, which cycles modules) selected it: GO then opened that module's area selection (DM20's "Next and Reset" NEXT where the tutorial highlights FIGHT) and fought its real battle; `last_adventure_module` became "DM20" and the battle's `change_scene` patch was left behind. Crawl: `escape` at step 181 (fumble keyboard replay). Now `TutorialBattle._setup_tutorial_module_selection` disables every other module's button, module cycling answers "cancel", and the hooked GO re-asserts the Tutorial module.

### ~~9. In the shop branch, B and the Connect menus' other buttons leave the tutorial (UI-11)~~

**Fixed 2026-10-24.** B on the Connect main menu went to the main game with the tutorial's party (`escape` at step 204, fumble keyboard shop); A on the WiFi button opened `wifi_hosting`; a tap on the module list's Back went back to the shop (`escape` at step 214, fumble touch shop). Now B/CANCEL are refused while SceneConnect is embedded, and every frame the main menu keeps only SHOP enabled, the shop only MODULES, and every view loses its BACK/EXIT (`SceneTutorial.CONNECT_PATH_BUTTONS`, `_update_connect_phase_progress`).

### ~~10. A second A on SHOP in the same frame skips the shop step (UI-11)~~

**Fixed 2026-10-24.** SceneConnect's progress is polled once a frame, so a second press before the next frame reached the shop's MODULES button while the tutorial still waited for `enter_shop`. The progress is now also checked right after each press passed to the scene.

### ~~11. The module detail's back-to-list takes the Download highlight away (UI-11)~~

**Fixed 2026-10-24.** After the purchase the tutorial highlights the detail's Download; A on its Back (to the list) left a highlight over nothing (`stuck` at step 219, fumble keyboard shop). It is disabled while the tutorial waits for the download. Also: a highlight that is fading out no longer refuses taps (the battle's charge right after FIGHT takes them), and a refusal while a minigame or battle is in play is silent.

## For review (owner)

- **The tutorial writes into the player's save** (`save` findings, every run): the Digidex gets the Tutorial module's Botamon, Koromon and Agumon (`game_pet.py:846` records a discovery even with `reward=False`); `battle_area`, `battle_round` and `unlocks` get a `Tutorial` entry and `last_adventure_module` becomes `"Tutorial"` (a module that is unloaded when the tutorial ends); the tutorial's Dummy training counts toward the player's daily "Train N Times" quest. Intended, or should the tutorial leave the save as it found it?
- **The touch SKIP pill covers the top dialog and several highlights** (`overlap`): the pill at base (200, 40, 36, 18) (`skip_overlay.py:37-38`) lies over the top dialog (7, 2, 226, 50) and over the highlights of EXIT, the item description, Clean and GO. A tap on those parts skips the whole tutorial.
- ~~**Presses in the tutorial's training READY and battle answer "cancel"**~~ Fixed 2026-10-24: `SceneTutorial.plays_own_input_sounds` asks the embedded scene. Left in the crawl's `sound` list, none of them the tutorial's: a tap during the fight animation skips it and the battle itself plays "cancel" (`battle_encounter.py`, in or out of the tutorial: keep?); A on the Tutorial module's own (already selected) button and A on the area selector answer "menu", as they select.
