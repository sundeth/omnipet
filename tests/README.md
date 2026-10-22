# Omnipet tests

Automated tests and release checks for the game. They are the automated half of the release checklist (`utilities/claude/docs/release-checklist.md`) and are rerun on every release. `tests/` is versioned in git; it is never packaged into a build (the build scripts copy `src/`, `assets/` and named files only, and buildozer excludes `tests` and `tmp`).

## Layout

| Folder | What lives there |
|---|---|
| `support/` | Shared code, imported by name: `paths` (ROOT, SRC, `temp_dir()`), `harness` (a headless game: `Env`, fixtures, `tap`, frames on a fake clock), `sprites` (sprite lookup as the game does it) |
| `unit/<area>/` | Fast tests of rules and components: `battle`, `care`, `items`, `training`, `ui`, `android`, plus an area per feature |
| `game/<area>/` | Tests that boot the real game headless through `support/harness.py` and drive its scenes (minigames played through, replays, battles) |
| `release/` | Release-pass tools: `run_release_checks.py` runs them all; `module_audit.py` (with `module_files.py`, MOD-18), `editor_report.ps1`, `device_validators.py`, `scene_sweep.py`, `menu_crawl.py`, `evolution_crawl.py` (MOD-19), `collection_crawl.py` (MOD-20), `care_crawl.py` (MOD-21: lifespan, sickness and injury on the live clock), `build_checks.py` (with BLD-07, build contents), `production_probe.py` (the production Omninet, read-only: ARN-09, MOD-17); `editor_docs.ps1` regenerates the modules' documentation (DOC-01, writes `modules/*/documentation/`) |
| `platform/android/` | BlueStacks scripts (adb on `127.0.0.1:5555`) |
| `platform/linux/` | WSL scripts: the suite and build smoke on a case-sensitive file system |
| `platform/pi/` | Shell scripts to run on the Raspberry Pi Zero 2W build over PuTTY |

Every test file sits exactly two folders below `tests/` (`tests/unit/battle/test_x.py`), so `REPO_ROOT = parents[3]` holds everywhere.

## Running

```powershell
python -B tests/run_tests.py                 # every test file, one process each, 4 at a time
python -B tests/run_tests.py --only battle   # paths containing "battle"
python -B -m pytest -q -p no:cacheprovider tests/unit/battle/test_arena.py
python -B tests/unit/battle/test_battle_protocols.py           # its own script runner
python -B tests/release/run_release_checks.py                  # the whole automated release pass (~6 min)
```

Do not run the whole folder in one pytest process: a test that quits pygame's font module leaves a cached Font behind and the next test crashes. `run_tests.py` gives each file its own interpreter. Files still in the legacy folder `utilities/claude/tests/` are collected too until they move (see its `MOVED.md`).

## Conventions

- **unittest classes**, runnable by pytest. Use `self.subTest` for tables of cases.
- **Scratch files only under `tmp/`**: `paths.temp_dir("prefix_")` returns a fresh folder under `tmp/tests/`, removed at exit. Never write into `src/`, `modules/`, `assets/`, `save/` or `Documentation/`.
- **Modules are optional**: `modules/` is not in git. A test that needs them skips with `unittest.skipUnless(os.path.isdir(MODULES), ...)`.
- **Headless game**: `from harness import Env`. `Env(res, fixture=...)` boots once per class (about 2 s); `env.reset()` restores the fixture save before each case; `env.game(scene_name)` returns a `VirtualPetGame` on that scene; `env.frames(game, n)` runs update + draw on a fake clock (33 ms a frame); `env.tap(game, pos)` taps as the input manager does (it moves the pointer first: the UI manager reads click positions from it). Fixtures: `default` (four pets), `room` (three), `sick` (one pet sick, Dots, one injured, Skull), `empty` (none); the crawl adds `boot` (starts at the boot scene), `replay` (an arena replay played to the arena screens) and `online` (the fake Omninet, logged in, every shop stocked, an arena season: `menu_crawl.start_fake_omninet`). `Env(res, network="local")` allows localhost only, for `support/fake_omninet.py`; Omninet credentials are kept in the temp save. `env.sounds` and `env.logs` record every sound played and console line.
- **Network is refused** inside `Env` (sockets raise): nothing reaches Omninet or a device. Online code is tested against a fake server in `support/` (see below).
- **A test that finds a bug** in game code does not change `src/` or `modules/` in the same change unless that is its job: it is written as the correct expectation, marked `@unittest.expectedFailure` with a comment naming the bug, and the bug is listed in `tests/findings/<area>.md` (one file per area, so parallel work never edits the same file). When the bug is fixed the test passes unexpectedly and its marker comes off.
- **Processes**: at most 4 test processes at a time on the development PC (`run_tests.py` default); the crawl and sweep pace themselves (`-j`, up to 4 by default; each crawl process loads every module). Never start several full release passes at once.
- **Names**: `test_<thing>.py`; one area per folder; a new feature gets its own folder (`unit/arena/`, `game/ic/`).

## Platform scripts

- **Android (BlueStacks)**: `platform/android/` drives the debug APK with adb (`127.0.0.1:5555`). Never replace the user's installed `org.omnipet.omnipet`; tests install their own package (see `utilities/claude/android_day/device/` for the existing offline-progression device test).
- **Linux (WSL)**: `platform/linux/run_suite.sh` runs `run_tests.py` under WSL's Python against the same checkout. `E:` is exFAT, so `/mnt/e` forgives letter case even under Linux: only the default `strict` mode (a case-checking shim in every test process) or `--mode mirror` (a copy on ext4) catch asset paths in the wrong case; `--mode plain` does not. Details: `platform/README.md`.
- **Raspberry Pi Zero 2W**: `platform/pi/*.sh` are copied to the Pi and run over PuTTY; they print one summary per check (FPS per scene, boot time, input mapping) so the result can be pasted back.
