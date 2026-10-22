# Online findings (fake Omninet)

Found by the online tests (2026-10-13): `tests/unit/online/test_omninet_client.py`
and `tests/game/online/test_online_*.py`, run against `tests/support/fake_omninet.py`,
whose answers mirror `E:/Omninet/omninet/routes/*.py`. Each bug below has an
`@unittest.expectedFailure` test with the correct expectation; when the bug is
fixed the test passes unexpectedly and its marker comes off. Line numbers are
those of 2026-10-13.

## Bugs

### ~~1. A purchase the server refuses is booked as bought (ONL-01)~~ Fixed 2026-10-13
- **What:** `POST /shop/purchase` answers a refused purchase (not enough coins, already owned) with HTTP 200 and `{"success": false, "message": ...}`. `OmninetService.purchase_item` only checks the HTTP status and returns `(True, message)`, so the shop views subtract the price from `game_globals.coins` and grant the item/module/cosmetic locally. The server sells an item once per account (`services/shop.py:217`, `user_owns_item` applies to items too), so the second Buy of the same item is always refused: the player loses the coins locally and gets a second copy that the server never sold.
- **Where:** `src/services/omninet_service.py:600-621`; consumers `shop_items_view.py:383-387`, `shop_modules_view.py:468-473`, `shop_cosmetics_view.py:430-434`, `shop_gameplay_view.py` (same pattern).
- **Tests:** `test_omninet_client.py::test_a_refused_purchase_is_reported_as_a_failure`, `test_online_shop.py::test_a_purchase_the_server_refuses_costs_nothing`.
- **Fix:** return `(data.get("success", False), data.get("message"))`; on success set `game_globals.coins = data["coins_remaining"]` instead of subtracting the displayed price.

### 2. Logout never revokes the device key
- **What:** `logout()` posts to `/api/v1/auth/logout`, which does not exist on the server (`routes/auth.py` has no logout route; the call gets a 404). The key is only forgotten locally; it keeps opening the account for anyone who copied `omninet_device.json`.
- **Where:** `src/services/omninet_service.py:241-272`; Omninet `routes/auth.py`.
- **Test:** `test_omninet_client.py::test_logout_revokes_the_key_on_the_server`.
- **Fix:** add a server route that sets the calling `UserDevice.is_active = False` (and use it), or document that logout is local only.

### ~~3. One HTTP 500 during auto-login logs the player out~~ Fixed 2026-10-13
- **What:** `validate_device()` treats every non-200 answer as a rejected key and deletes the saved credentials. A server restart or a database error at boot sends the player through the e-mailed-code login again. (Connection errors and timeouts keep the key, correctly.)
- **Where:** `src/services/omninet_service.py:216-231`.
- **Test:** `test_omninet_client.py::test_a_server_error_during_auto_login_keeps_the_saved_key`.
- **Fix:** clear the credentials only on 401/403.

### ~~4. Reward outbox retries an already-credited key forever (AND-08)~~ Fixed 2026-10-13
- **What:** the server answers a duplicate idempotency key with HTTP 400 "Already claimed" (`routes/rewards.py:43`). `flush_effects` treats every failure alike and keeps the entry, so a key the server credited before the app died (the case the comment at `android_progress.py:415` describes) is resent at every checkpoint and never leaves the outbox.
- **Where:** `src/services/android_progress.py:402-405`.
- **Test:** `test_omninet_client.py::test_an_entry_the_server_already_credited_leaves_the_outbox`.
- **Fix:** drop the entry when the answer is "Already claimed" (or have the server answer a duplicate with 200 and `coins_awarded: 0`).

### 5. A bought shop item has no effect (ONL-01)
- **What:** the inventory takes a shop item's effect from `json_data` in the shop listing (`shop_items_view.py:196`), but `GET /shop/items` has no `json_data` (`routes/shop.py:117-134`, `ItemListItem`); it is only in `GET /shop/download/item/{id}`, which the client never calls (`download_item` is unused). The item shows up with no effect and no status and the inventory refuses it ("has no implemented effect"). The consumer side works when the data is there (`test_the_inventory_uses_an_item_whose_effect_is_known`).
- **Test:** `test_online_shop.py::test_a_bought_item_can_be_used_from_the_inventory`.
- **Fix:** after a purchase (and in the account sync) fetch `/shop/download/item/{id}` and store its `json_data`, or add `json_data` to the listing.

### ~~6. A bought item disappears from the inventory after a restart (ONL-01)~~ Fixed 2026-10-14: `save()` writes `shop_items_data` and `load()` reads it back
- **What:** the inventory lists a shop item only if `game_globals.shop_items_data` has its metadata (`scene_inventory.py:131`); that dict is filled when the shop's Items page loads and `save()` does not write it (`core/game_globals.py:549`, `save()` at 677). After a restart the bought item is invisible until the player opens the shop again.
- **Test:** `test_online_shop.py::test_a_bought_item_is_in_the_inventory_after_a_restart`.
- **Fix:** persist `shop_items_data` (or rebuild it during the account sync).

### 7. A used item comes back at every login or start (ONL-01/02)
- **What:** `sync_account_data` (run after every login and at boot) sets every purchased item whose local quantity is 0 back to 1 (`_apply_purchase_entries`). Using an item and restarting the game gives it back: unlimited consumables.
- **Where:** `src/utils/module_utils.py:269-272`.
- **Test:** `test_online_shop.py::test_a_used_item_does_not_come_back_at_the_next_login`.
- **Fix:** record consumed purchase ids in the save (or have the server keep quantities) and only grant an item for a purchase this save has not seen.

### ~~8. A selected shop background is never drawn (ONL-01)~~ Fixed 2026-10-14: `WindowBackground._shop_paths` draws a "shop" background from the files its download wrote (`bg_<name>.png`, `bg_<name>_night.png`)
- **What:** Settings > Backgrounds lists a downloaded background under the module name `"shop"` (`scene_settingsmenu.py:262-265`), but `WindowBackground` looks backgrounds up as `modules/<module>/backgrounds/bg_<name>.png` through `get_module(name)`; there is no module `"shop"`, so the selection silently falls back (to `assets/Splash.png` in the test).
- **Where:** `src/ui/windows/window_background.py:62-95`.
- **Test:** `test_online_shop.py::test_a_selected_shop_background_is_drawn`.
- **Fix:** for `background_module_name == "shop"` use `game_globals.shop_backgrounds[...]['sprite_paths']`.

### ~~9. A downloaded background is gone after a restart (ONL-01/02)~~ Fixed 2026-10-14: `save()` writes `shop_backgrounds` and `load()` reads it back
- **What:** the download registers the background only in `game_globals.shop_backgrounds`, which `save()` does not write; after a restart it is missing from Settings until downloaded again.
- **Where:** `src/core/game_globals.py:550`, `save()` at 677; `shop_cosmetics_view.py:492-500`.
- **Test:** `test_online_shop.py::test_a_downloaded_background_survives_a_restart`.
- **Fix:** persist `shop_backgrounds`, or rebuild it from `purchases.cosmetics` at the account sync.

### ~~10. Cosmetic files are written outside the player's save folder~~ Fixed 2026-10-14: the download writes to `get_save_dir()/cosmetics/backgrounds`
- **What:** the download writes to the cwd-relative `save/cosmetics/backgrounds` (shared by every account and mode; on Android the working directory is not the app's storage folder, so the write can fail or land in the bundle).
- **Where:** `src/scenes/connect_views/shop_cosmetics_view.py:470`.
- **Test:** `test_online_shop.py::test_downloaded_cosmetics_go_to_the_players_save_folder` (the test redirects the write into a temp folder with `fake_omninet.redirect_relative_save`).
- **Fix:** build the folder from `game_globals.get_save_dir()` (or `_get_base_save_dir()` for files shared by the account's devices).

### ~~11. BLD-04: the connect menu decides availability from the dev server~~ Fixed 2026-10-13
- **What:** `_check_shop_availability_async` and `_check_omninet_availability_async` probe `constants.OMNINET_LOCAL_URL` (`https://dev.omnipet.app.br/`) before production, while `OmninetService` always talks to production. With dev up and production down the Shop button opens and every call fails. (Known; tracker row BLD-04.)
- **Where:** `src/scenes/connect_views/main_menu_view.py:643-660`, `:923-944`.
- **Test:** `test_online_failures.py::test_shop_availability_follows_the_server_the_game_uses`.
- **Fix:** use `omninet_service.check_availability()` in both places.

### ~~12. The player sees raw JSON parser errors~~ Fixed 2026-10-13
- **What:** when the server (or a proxy) answers with an HTML page, `response.json()` raises inside `OmninetService` and the caught exception text is returned as the message; the login form shows "Expecting value: line 1 column 1 (char 0". The arena history WATCH shows the same text for a broken battle record.
- **Where:** `src/services/omninet_service.py` (the generic `except Exception: return False, str(e)` of every call, e.g. 311-313, 381-382; `validate_pairing_code` 169-171 parses error bodies unguarded); shown by `scene_login.py:364` and `arena_history_view.py:219-220`.
- **Test:** `test_online_failures.py::test_a_gateway_error_page_shows_a_readable_message`.
- **Fix:** map non-JSON bodies and parse errors to one readable message ("Omninet is not answering, try again later").

### ~~13. A failed module update deletes the installed module~~ Fixed 2026-10-13: `module_utils.install_zip_into` stages, checks module.json, then swaps
- **What:** installing first deletes `modules/<name>/` and only then opens the zip; a broken or interrupted download leaves the player without the module they had (and its pets without their module).
- **Where:** `src/scenes/connect_views/shop_modules_view.py:521-528`; `src/utils/module_utils.py:111-117` (owned-module sync).
- **Test:** `test_online_failures.py::test_a_failed_update_keeps_the_installed_module`.
- **Fix:** extract into a temp sibling folder, check `module.json`, then swap folders; keep the old one on any failure.

### ~~14. A late module logo resets a running download~~ Fixed 2026-10-14: `ShopModulesView._show_late_logo` only adds the logo while `_downloading` (the cosmetics preview rebuild at `shop_cosmetics_view.py:166-170` is not changed)
- **What:** the module detail fetches its logo in a thread and, when it lands, rebuilds the whole detail view. During a download that replaces the status line ("Downloading 40%" becomes "Already Owned") and re-enables the Download button, so a second tap starts a second install into the same folder while the first is extracting. The cosmetics detail has the same rebuild on a late preview (`shop_cosmetics_view.py:166-170`).
- **Where:** `src/scenes/connect_views/shop_modules_view.py:435-446`.
- **Test:** `test_online_failures.py::test_a_logo_arriving_during_a_download_keeps_the_download_state`.
- **Fix:** while `_downloading`, only swap the logo image; never rebuild the action button and status line.

### ~~15. A team created after a client timeout leaves its pets unlocked (ARN-05)~~ Fixed 2026-10-16: every upload carries the pet's `uid`, the server returns it per team pet, and `ArenaView._lock_loose_pets` locks party pets whose uid is on the current team; registration and FIND BATTLE also wait `OmninetService.ARENA_TIMEOUT` (20 s) instead of 5
- **What:** if the server creates the team but its answer arrives after the client's 5 s timeout, the view reports a failure and the pets stay in the party, unlocked; the hub then shows the team (`GET /teams/current`) and nothing ever moves its pets to the freezer, so they keep being raised, evolved or released while they fight on the server.
- **Where:** `src/scenes/connect_views/arena_team_creation_view.py:342-373`; `arena_view.py:173-177`.
- **Test:** `test_online_failures.py::test_a_team_created_after_a_timeout_still_locks_its_pets`.
- **Fix:** when the hub loads a current-season team whose pets are still in the party unlocked, lock them with the team's `season_ends_at`; or make creation idempotent with a client request id and retry instead of failing.

### ~~16. The season-results takeover shows no pets (ARN-07)~~ Fixed 2026-10-14: `ArenaView._with_team_details` fetches `GET /teams/{id}` (new `OmninetService.get_team`; the fake serves it) for the pending team
- **What:** the hub's results state reads the finished team's pets from `GET /teams?include_past=true`, whose rows (`TeamListResponse`, `routes/teams.py:96-113`) carry only `pet_count`; the team is shown with empty pet slots.
- **Where:** `src/scenes/connect_views/arena_view.py:309-316`.
- **Test:** `test_online_arena.py::test_the_results_takeover_names_the_finished_teams_pets`.
- **Fix:** fetch `GET /teams/{id}` for the pending team, or add the pets to the list rows.

### ~~17. A history that failed to load says "No battles yet" (ARN-08)~~ Fixed 2026-10-14: `ArenaHistoryView` keeps `_load_error` and shows it instead of the empty state
- **What:** the worker shows the error, then `_render_rows()` replaces it with "No battles yet" (the loading flag was already cleared), so an outage tells the player their team never fought.
- **Where:** `src/scenes/connect_views/arena_history_view.py:115-128`.
- **Test:** `test_online_failures.py::test_a_history_that_failed_to_load_does_not_read_as_empty`.
- **Fix:** keep an error flag and render it instead of the empty state.

### ~~18. Arena replays of uneven teams crash or drop a shot (ARN-02)~~ Fixed 2026-10-16: `GameBattle.lanes` = the larger team; a lone PvP opponent keeps its own lane (`BattleEncounter.setup_enemy_attack`)
- **What:** arena teams hold 1-3 Digimon. A viewer outnumbered (1v3, 2v3) crashed the battle scene: `GameBattle` sized every lane array by the player's team, so `get_hp` overflowed (`IndexError`, swallowed by the scene) and the empty battle then failed on `max(turns)`. A viewer facing a lone opponent (3v1) saw it as an adventure boss whose shot went to the target's lane slot; lane 0 never learnt it landed, stalled, and the battle ended on the 10 s fallback with a shot unplayed (the HP differed from the server's).
- **Where:** `src/battle/game_battle.py` (lane arrays), `src/battle/battle_encounter.py` (`own_lane` in `setup_enemy_attack`).
- **Test:** `test_arena_replay_scene.py::test_uneven_teams_replay_from_both_seats`; found by `tests/arena_sim`.

### ~~19. The arena hub's buttons never redraw after loading (ARN-07)~~ Fixed 2026-10-16: the arena views use `Button.set_enabled` / `set_text`
- **What:** the hub assigned `button.enabled` and `button.text` directly. `Button` caches its surface and only redraws (and updates `focusable`) through `set_enabled` / `set_text`, so FIND BATTLE, HISTORY (and the new RANKS) stayed drawn greyed with their first text after the data arrived, although tapping them worked.
- **Where:** `src/scenes/connect_views/arena_view.py`, `arena_history_view.py`.
- **Test:** seen on the `tests/arena_sim` screenshots.

### ~~20. Matchmaking picked rarely-attacking teams far more often (ARN-06)~~ Fixed 2026-10-16 (Omninet `TeamService.find_opponent`)
- **What:** the first fair-matchmaking key counted meetings in both directions, so a team that attacked little looked "unmet" to everyone and defended 2-3x as often as active teams (season 1 of the simulation: 9-26 defences).
- **Fix:** rotate on the attacker's own attacks today, then on defences received today, then the same over the season.

### ~~21. A version-0 Digimon cannot join an arena team (ARN-05)~~ Fixed 2026-10-17: `_pet_to_upload` sends the pet's version as it is (`_version`)
- **What:** the upload sent `int(pet.version or 1)`, so a species whose monster.json version is 0 (PENC's Agumon and its line) went up as version 1 and the server refused it: "Agumon (version 1) is not in PENC".
- **Where:** `src/scenes/connect_views/arena_team_creation_view.py`.
- **Test:** `tests/unit/arena/test_arena_seasons.py::UploadTests`; found by `tests/arena_sim`.

### ~~22. The team picker never says why a pet is disabled (ARN-05)~~ Fixed 2026-10-17: `PetSelector.disabled_callback`
- **What:** `PetSelector` ignored taps (and A) on disabled cells, so `ArenaTeamCreationView` could never show its reasons ("Fought last season: evolve it first", "Wrong stage for this season", ...).
- **Where:** `src/ui/components/pet_selector.py` (opt-in callback; other pickers unchanged), `arena_team_creation_view.py`.
- **Test:** seen by `tests/arena_sim` (game instances tap a veteran).

## Gaps in the shared harness (not game bugs)

- ~~`tests/support/harness.py` does not redirect `OmninetService._credentials_path`.~~ Done 2026-10-13: `Env` points it into its save folder. The service is created at import, before `Env` patches the save folder, so its path is the cwd-relative `save/omninet_device.json`, the repository's own save folder: any test that logs in without `fake_omninet.isolate_client` writes the developer's real device key file. Suggest `Env.__init__` set `omninet_service._credentials_path = os.path.join(self.save_root, "omninet_device.json")`.
- The same applies to `DiscordModule` (`scene_connect.py:64-81`), which reads and writes the cwd-relative `save/discord_data.json`; if that file exists on the PC, the main menu probes the Discord bot URL (`localhost:5000` by default; `isolate_client` points `DISCORD_BOT_URL` at the fake).

## Observations (no failing test)

- **Server: module downloads need no purchase.** `GET /api/v1/modules/{id}/download` (Omninet `routes/modules.py:305-331`) requires no device key and checks no ownership; the game uses it for paid downloads too, so any module can be fetched without buying it.
- **Server: cosmetic downloads carry no image.** `services/shop.py:274-277` returns every sprite as `""` (TODO), so against production the client writes 0-byte PNGs. The fake sends real base64 PNGs, as the schema describes.
- **Specials** is a "Coming Soon" placeholder; `GET /shop/specials` is never called.
- Any HTTP 200 on `/health` (a captive-portal page) reads as "Omninet available"; the screens then fail gracefully.
- Shop and arena workers rebuild components and call `change_view` from background threads while the main thread draws. The tests avoid the race by waiting without frames; a crawler should do the same.
- `SceneLogin`: after an inactive-account login the follow-up resend runs while `_end_loading()` has already re-enabled the buttons (`scene_login.py:848`, called after the callback that started the resend).
- Touch/GPIO input mode: a focused text field's on-screen keyboard covers the login forms' bottom buttons, and the forms' TextInputs have no `on_confirm`, so the keyboard's OK does nothing there; the player has to tap outside the field first.
- `sync_account_data` mirrors the coin balance cached at the last `validate_device()`; within a session it can be stale (only boot and login call it after a fresh validation, so this does not show today).
