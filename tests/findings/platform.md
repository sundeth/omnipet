# Platform findings

Bugs and gaps found by `tests/platform/` (Linux/WSL suite and case check, Raspberry Pi scripts run headless off the Pi, Android script). Each entry: what, where, how to reproduce, checklist id, suggested fix. Fixed entries are struck through with the date. Pass of 2026-10-13 against `dev` at 9ce97d8b plus the working tree.

## Game

### ~~P-01 GPIO remapping is ignored: every pin keeps its default action (UI-01)~~ Fixed 2026-10-14: `process_event` maps a GPIO event by its pin through the current `pin_map`, and `reload_input_mappings` registers any pin the new map adds (`tests/unit/ui/test_gpio_remap.py`; `input_check.py --simulate --remap 21=B,20=A` passes)

- **Where**: `src/input/input_manager.py:199-212` registers the gpiozero `Button`s once, in `InputManager.__init__`, which runs when `core.runtime_globals` is imported (`runtime_globals.py:172`). The save is not loaded yet at that point, so `pin_map` is `GameConfiguration.DEFAULT_GPIO_MAP`, and each handler captures that action (`make_gpio_handler(action, pin, ...)`, `:263-277`). `reload_input_mappings` (`:107-117`, called by `vpet.py:114-115` after the save loads and by `scene_setup.py:507-508` after the GPIO setup step) only replaces `pin_map`; the GPIO branch of `process_event` (`:534-542`) returns `event.action`, the captured default, and never reads `pin_map`.
- **Effect**: a GPIO mapping chosen in the setup screen, or loaded from the save, changes nothing. Each button keeps its default action, both right after setup and after a restart. Keyboard and joystick remaps work: they read `key_map` and `joystick_button_maps` on every event.
- **Reproduce** (off the Pi, simulated gpiozero):
  `python -B tests/platform/pi/input_check.py --game . --simulate --defaults --remap 21=B,20=A --tmp tmp/platform/pi`
  The result has `20  A  B  WRONG: configured A, game got B` and `21  B  A  WRONG ...`. On the Pi: remap A/B in setup, then run `bash input_check.sh`.
- **Fix**: in the `GPIO_PRESS_EVENT` and `GPIO_RELEASE_EVENT` branches, look the action up by pin: `action = self.pin_map.get(event.gpio_pin, event.action)`, and use the same value for `active_gpio_inputs`. `SceneSetup` already maps by `event.gpio_pin`, so it is unaffected. Alternatively, have `reload_input_mappings` close and re-register the Buttons.

### ~~P-02 Keyboard START (Backspace) raises TypeError in 8 scenes and does nothing (UI-01)~~ Fixed 2026-10-13: `VirtualPetGame.handle_event` offers the raw key only while a text field has focus (`tests/game/ui/test_raw_keys.py`)

- **Where**: `src/vpet.py:258-260` passes the raw `pygame` `KEYDOWN` Backspace event to `self.scene.handle_event(event)` before the input manager maps it. This is meant for focused text fields. Scenes that unpack `event_type, event_data = event` then raise `TypeError: cannot unpack non-iterable pygame.event.Event object`: `scene_boot.py:261`, `scene_setup.py:978`, `scene_maingame.py:941`, `scene_error.py:221`, `scene_inventory.py:302`, `scene_training.py:852`, `scene_freezerbox.py:483`, and `battle_pvp`, which falls back to the main game. `main.py:272` catches the exception per frame ("[Error] Exception in game loop"), so the game keeps running. The key never reaches `process_event`, though, so START (default keyboard binding `K_BACKSPACE`) does nothing in those scenes. For example, Settings cannot be opened from the main game with the keyboard.
- **Affects**: Windows, desktop Linux and Batocera keyboards, and a USB keyboard on the Pi. GPIO and joystick START are not affected.
- **Reproduce**: `python -B tests/platform/pi/smoke.py --game . --dummy --tour --tour-input keyboard --seconds 70 --tmp tmp/platform/pi` prints a traceback at the START step. All scenes at once: boot `harness.Env`, and for each `scene_sweep.SCENES` entry call `game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_BACKSPACE, mod=0, unicode="\b", scancode=42))`. 8 of 21 raise (2026-10-13).
- **Fix**: forward the raw Backspace only to a scene that has a focused text component, for example a scene attribute/method `wants_raw_backspace()` that `SceneConnect`/`SceneLogin` implement. Or have every scene's `handle_event` return early for non-tuple events (`if not isinstance(event, tuple): return False`).

### ~~P-03 Entering Connect probes the dev server before production (BLD-04)~~ Fixed 2026-10-13: both checks use `omninet_service.check_availability()` (online finding 11)

- **Where**: `src/scenes/connect_views/main_menu_view.py:643` (`_check_shop_availability_async`) and `:923` (`_check_omninet_availability_async`) request `constants.OMNINET_LOCAL_URL` (`https://dev.omnipet.app.br/`, `constants.py:437`) and only then `OMNINET_MAIN_URL`. The fallback default at `:923` is `http://localhost:8000`.
- **Seen at runtime**: `perf_scenes.py` and `smoke.py --tour` record every refused connection. Entering `connect` produced `('dev.omnipet.app.br', 443)` alongside `('omnipet.app.br', 443)`. `tests/release/build_checks.py` reports the same code statically ("probes OMNINET_LOCAL_URL").
- **Fix**: use `omninet_service._get_base_url()` (production unless `OMNIPET_OMNINET_URL` overrides it) for both health checks.

### ~~P-04 Build scripts copy config files that no longer exist (BLD-01)~~ Fixed 2026-10-14: the config copies are gone from the six build scripts (nothing reads `config/`: settings live in the save); the manual, the installation guide, `utilities/setup.sh` and `build/BUILD_REQUIREMENTS.md` now point at the Settings menu. A `config/` folder left on an installed GamePi from an older build is unused and can be deleted

- **Where**: the `config/` folder was deleted in e09369e8 (2026-03-14). The build scripts still copy from it: `build/build_gamepi.ps1:54-55` (`config_raspberry.json`, `input_config_raspberry.json`), `build_windows.ps1:86-87`, `build_batocera.ps1:59-60`, `build_python_desktop.ps1:49-50`, `build_gamepi_nuitka.ps1:228-229` and `build_nuitka_windows.ps1:222-223`. `Copy-Item` fails without stopping, so each build prints errors and ships an empty `config/` folder (`Release/Omnipet_GamePi_Ver_1.0.0 Beta 3/config/` is empty).
- **Effect**: noise and an empty folder only, since the game now takes its settings from `GameConfiguration` defaults plus the save (`models/game_configuration.py`, `game_globals.load`). The texts that still tell players to edit `config.json` / `input_config.json` are stale, though: `launch.sh:4,55`, `utilities/setup.sh` (last line), `Documentation/pages/manual.html:59,1055,1088`, `Documentation/pages/installation-guide.html:234,347-349,682-695`, and `build/BUILD_REQUIREMENTS.md` ("config/ ... must be present").
- **Fix**: remove the config copy blocks (or ship a README in `config/` saying settings are in the game's Settings menu), and update the docs. `tests/platform/pi/input_check.py` reads the mapping the way the game does and notes any leftover `config/input_config*.json` it finds on the Pi.

### P-05 Linux launch: `fbcon` is not an SDL2 driver; `Omnipet_FULLSCREEN` is never read (BLD-01)

- **Where**:
  - `launch.sh:25` exports `SDL_VIDEODRIVER=fbcon` when no X11/Wayland session is found. `main.py:55,61` lists `x11, wayland, fbcon` for non-Batocera Linux. SDL2 (pygame 2) has no `fbcon` driver. With the variable set, `main.setup_pygame` calls `pygame.display.init()` outside any `try` (`main.py:86`), and the game dies with a `pygame.error`. Without a desktop session, the game therefore cannot start through `launch.sh` on a console-only Pi (Raspberry Pi OS Lite); `kmsdrm` is the SDL2 console driver.
  - `launch.sh:12,30` export `Omnipet_FULLSCREEN=1`, but `main.py:140` reads `OMNIPET_FULLSCREEN`. Environment variables are case-sensitive, so the export does nothing. Both cases are covered anyway (Batocera is detected through `batocera-info`, and `--fullscreen` reaches `main.py` through `"$@"`), so the variable is just dead.
- **Owner check**: `smoke.sh` and `perf_scenes.sh` print the driver they used (`video` line) and fall back to `kmsdrm` when no desktop session exists. This shows how the GamePi image actually runs.
- **Fix**: use `kmsdrm` instead of `fbcon` in `launch.sh` and in `main.try_set_video_driver`'s Linux list (keep `x11`/`wayland` first), and correct the variable name.

### ~~P-09 launch.sh started the game with the system Python (BLD-01)~~ Fixed 2026-10-14

- **What**: Raspberry Pi OS Bullseye's system `python3` is 3.9.2, which cannot import the game (`str | None` annotations: `TypeError: unsupported operand type(s) for |` in `input_manager.py`). The owner's GamePi runs the game with `/usr/local/bin/python3.10` (3.10.14, built from the `Python-3.10.14/` sources kept in the game folder). `launch.sh` ran whatever `python3` was on the PATH, and so did the Pi test scripts (found on the owner's Pi, 2026-10-14).
- **Fix**: `launch.sh` and `tests/platform/pi/_common.sh` take the first Python 3.10+ that imports pygame: one bundled in the game folder (`Python-3*/python`, `Python-3*/bin/python3[.NN]`), then `python3.14` ... `python3.10` on the PATH, then `python3`; with none, they say so (the scripts list what they tried). Checked under WSL with mock layouts and on the owner's Pi (`smoke.sh` picked `/usr/local/bin/python3.10`).
- **Open**: nothing in the repo installs Python 3.10 on a fresh GamePi image (`setup.sh` installs packages for the system `python3`; `build_gamepi.ps1` ships no Python). How a retail image gets its 3.10 and pygame is not written down.

### P-06 Every Linux is treated as a Pi for GPIO (UI-01, low)

- **Where**: `src/input/input_manager.py:126`: `self.device = "PC" if platform.system() != "Linux" else "Pi"`. On desktop Linux, Batocera and WSL it tries gpiozero and logs "[Input] GPIO unavailable: gpiozero not installed or import failed" at every start. That line was seen in every WSL run and matches the release scripts' error markers. On a non-Pi with gpiozero installed, it would try to claim pins.
- **Fix**: decide "Pi" from `/proc/device-tree/model` (contains "Raspberry Pi"), and log the missing gpiozero as information, not as a failure.

### P-07 Module-guide builder points at a template that does not exist (low)

- **Where**: `src/utils/document_utils.py:21`: the template path is `game/core/utils/module-guide_template.html`, and there is no `game/` folder. Every start prints "Template not found: .../game/core/utils/module-guide_template.html" (`main.py:237-238`), and `Documentation/pages/module-guide.html` is never rebuilt.
- **Fix**: point it at the template's current location, or drop the start-up build.

### P-08 `build_gamepi.ps1` needs an unversioned file; setup.sh is stale (BLD-01, low)

- `build/build_gamepi.ps1:33-36` stops when `utilities/setup.sh` is missing, and `utilities/` is gitignored. A clean checkout therefore cannot build the GamePi package.
- `utilities/setup.sh` still says "Omnimon" in its messages, installs `omnimon.service` and an `Omnimon.desktop` whose icon is `resources/icon.png` (no such file), and points to `./update.sh` (no such file). It also runs `sudo apt-get upgrade -y`.
- **Fix**: move `setup.sh` into a versioned folder (for example `build/gamepi/`), rename it to Omnipet, and fix the icon path and the update hint.

## Module data (letter case)

`tests/platform/linux/case_check.py` (static) and its `--runtime` pass (headless game, strict letter case, all 21 scenes) found no reachable name that only matches in another letter case: 24 modules (all sprite sets in Color, Dot and HD, backgrounds, devices, item art, JSON file references) and every `assets/` path in `src/`. The full WSL test suite in strict mode logged no case-only access either.

- **Dormant (warn)**: the legacy egg-device art, `devices/<egg name>.png`, differs in case from the files in two modules: `modules/DMC/devices/DmC Ver 1-5.png` vs `DMC Ver 1-5.png`, and `modules/PENC/devices/PenC SW.png` / `PenC TB.png` vs `PENC SW.png` / `PENC TB.png`. `scene_eggselection.py:937-943` reads these only for a module without selectable devices, and both modules have them. They would break on Linux only if their `devices.json` lost its backgrounds.
- **Info**: 16 literal `assets/*.png` paths in `src/core/constants.py` do not exist in any case (`Arrow.png`, `MegaHit.png`, `Clear1/2.png`, `Warning1/2.png`, `Items.png`, `SleepIcon.png`, `WakeIcon.png`, `Ready1-3.png`, `Count2-4.png`, ...). They are dead constants; `build_checks.py` reports the ones still read.

## Test infrastructure

### T-01 A WSL run on this checkout forgives letter case (UI-08)

`E:` is exFAT (`Get-Volume E`: FileSystem exFAT), and WSL's `/mnt/e` (9p drvfs) is case-insensitive on it: `test -f /mnt/e/Omnipet/MAIN.PY` succeeds. `fsutil file setCaseSensitiveInfo` needs NTFS. So "run the suite under WSL to catch letter-case bugs" (`tests/README.md`, Platform scripts) does not hold for a plain run. `tests/platform/linux/run_suite.sh` defaults to `--mode strict` (a `sitecustomize` shim that makes file access under the checkout case-exact and logs every miss) and offers `--mode mirror` (an ext4 copy in the WSL home). `tests/README.md` now says so (2026-10-13).

### Results of this pass

- **WSL suite** (`run_suite.sh --mode strict -j 2`, Ubuntu 20.04, Python 3.10.4, pygame 2.6.1, pytest 8.4.1), two passes:
  - First pass: 49 runs (8 legacy), 682 passed, 4 xfailed, 2 files failing, neither Linux-specific. `tests/unit/online/test_omninet_client.py` failed (`FakeOmninet` had no `reset_log`) while `tests/support/fake_omninet.py` was being edited by other work; it passed on rerun on both sides. `tests/unit/training/test_ic_minigame_art.py` failed because numpy was missing from the new venv; it is now in `requirements.txt`.
  - Final pass (315 s, after other work had added tests): 69 runs, 1009 passed, 30 xfailed, 6 failed in 3 files: `tests/game/battle/test_adventure_rewards.py`, `tests/unit/battle/test_release_battle_gates.py` and `tests/unit/ui/test_protocol_selector.py` (TWIN and injury-chance cases). All three fail on Windows too, with more failures there. This is in-flight battle work, not a platform difference. `compare_runs.py` reports `FAILS ONLY ON LINUX: 0`.
  - No case-only path access in either pass (`case_misses.jsonl` empty).
- **Pi scripts off the Pi**: `perf_scenes.py --dummy` entered 21/21 scenes. `smoke.py --dummy --tour` booted to the main game in about 10 s and opened status, feeding, training, battle, sleep, library, connect and settings with GPIO events, with no traceback. `input_check.py --simulate` mapped all 12 default pins correctly and showed P-01 with `--remap`. All `.sh` files pass `bash -n` and have LF line endings. Not validated here: the `/tmp` symlink sandbox, which the Pi uses (exFAT cannot hold symlinks and scratch stays under `tmp/`; the validated `--in-place` mode is the fallback), the real display, real GPIO and the Pi's frame rate.
- **Android**: BlueStacks was not running (`HD-Adb.exe devices`: none), so only the no-device path ran (exit 2). The test-APK install guard refused `bin/omnipet-offline-1.0.0-arm64-v8a-debug.apk`: aapt2 shows it is the real `org.omnipet.omnipet`, despite its name.
