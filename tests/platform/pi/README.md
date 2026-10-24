# Raspberry Pi Zero 2W checks

Scripts the owner copies to the Pi and runs over PuTTY. Each one prints a short report between two marker lines; paste everything from `===== OMNIPET PI ... paste from this line =====` to `===== exit N - paste up to this line =====` back into the conversation. A copy of each report (and the smoke test's full game log) is kept in `~/omnipet-test-results/` on the Pi.

| Script | Checklist | What it does | Time |
|---|---|---|---|
| `perf_scenes.sh` | PERF-01, BLD-03 | Enters every scene on the Pi's own display, fullscreen 240x240, holds each for 5 s at the game's frame pacing (`clock.tick(configuration.frame_rate)`, 30 on the Pi) and prints fps avg / worst second per scene; then the heavy loads, 30 s each with every pet selected: `game_crowded` (four pets and a screen of poop), `training_play` (a training played round after round by all four: charge, attack animation, result) and `battle_play` (a DM20 area-1 adventure battle fought by all four), each with its figures per phase; flags anything under 30 fps | about 3.5 min |
| `smoke.sh` | BLD-01, BLD-02, BLD-03 | Starts the real game (`main.main()`) with a temp save holding a small party, so it boots straight into the main game; runs 60 s; lists modules loaded, scene switches, fps, and every traceback / error line | about 1.5 min |
| `smoke.sh --tour --seconds 70` | BLD-02, UI-01 | The same, and also opens the nine main-menu scenes and Settings with GPIO button events | about 2 min |
| `input_check.sh` | UI-01 | Prints the game action for each GPIO button you press, using the game's own InputManager and the mapping the game would use (defaults plus your save's `gpio_map`) | as long as you take |
| `blit_bench.sh` | PERF-01 | Times each way of drawing the menus' UI overlay (plain alpha, `convert_alpha`, RLE, premultiplied, bounding box) on the Pi's display, with the real overlays of a few menus, and checks each draws the same picture. `perf_scenes --profile` found that one alpha blit cost 17 ms a frame | about 30 s |

Nothing touches your pets: every script runs the game from a throw-away folder in `/tmp` (symlinks to the game, an empty `save/`), refuses every network connection (nothing reaches Omninet) and blocks any write into the game folder. `input_check.sh` reads your newest save from a copy, only to show your button mapping.

## 1. Copy the scripts to the Pi

The scripts find the game (the folder with `main.py`, `src/`, `assets/`, `modules/`) by themselves when they sit inside it, at `<game>/tests/platform/pi`, or when it is `~/Games/Omnipet` or `~/Omnipet`; otherwise pass `--game /path/to/Omnipet` (or set `OMNIPET_DIR`). Copy this whole folder (`tests/platform/pi/`) into the game folder at the same path, or anywhere on the Pi, for example `~/omnipet-tests`:

- **WinSCP**: connect to the Pi (SFTP, same host/user as PuTTY), drag `E:\Omnipet\tests\platform\pi` to the Pi's home folder and rename it `omnipet-tests`. Transfer mode "Binary" (or "Automatic"): the `.sh` files have Unix line endings and must keep them.
- **scp** from a Windows terminal (PowerShell):
  ```powershell
  scp -r E:\Omnipet\tests\platform\pi pi@<pi-address>:~/omnipet-tests
  ```
  (`pscp -r` from the PuTTY folder works the same way.)

Optionally also copy `E:\Omnipet\tests\release\scene_sweep.py` into the same folder: `perf_scenes` then uses the current scene list; without it, it uses its built-in copy (21 scenes, 2026-10-13).

If a script stops with `bash: ...\r: command not found`, the line endings were converted on the way: `sed -i 's/\r$//' ~/omnipet-tests/*.sh`.

## 2. Stop the game

The game holds the screen and the GPIO pins, so stop it first. The scripts refuse to run while it is running (and say how to stop it):

```bash
sudo systemctl stop omnimon      # if it was installed as a service (setup.sh --service)
# or quit it from its menu / pkill -f "Omnipet/main.py"
```

Start it again when you are done (`sudo systemctl start omnimon`, or `./launch.sh`).

## 3. Run

In PuTTY:

```bash
cd ~/omnipet-tests
bash smoke.sh                     # first: does the game boot and run?
bash perf_scenes.sh               # PERF-01: fps of every scene
bash input_check.sh               # UI-01: press each button once
bash smoke.sh --tour --seconds 70 # optional: open every main-menu scene with button events
```

The scripts run the game with the first Python 3.10+ that imports pygame among: the one the GamePi image bundles in the game folder (`Python-3.10.14/python`, `Python-3.x/bin/python3`, `Python-3.x/bin/python3.NN`), a `venv` there, `python3.NN` on the PATH (newest first), `python3`. When none qualifies they stop and list every interpreter they tried. Raspberry Pi OS Bullseye's own Python is 3.9, which cannot run the game (it needs 3.10).

Useful options (all scripts accept `--game DIR`, `--python PATH` and `--allow-running`):

| Option | Scripts | Meaning |
|---|---|---|
| `--seconds N` | perf_scenes (per scene, default 5), smoke (default 60), input_check (default 60) | How long |
| `--scene game battle ...` | perf_scenes | Only these scenes (and no heavy loads unless `--load` names them) |
| `--load game_crowded training_play battle_play` | perf_scenes | Only these heavy loads (`--loads-only`: no scenes; `--no-loads`: no loads; `--load-seconds N`, default 30) |
| `--training dummy`, `--battle-module DM20` | perf_scenes | The training `training_play` plays (a key of the training menu) and the module whose area 1 `battle_play` fights (one with a charge minigame) |
| `--uncapped` | perf_scenes | No frame cap: the most fps the Pi can draw per scene (headroom); no PERF-01 verdict |
| `--driver kmsdrm` | perf_scenes, smoke | SDL video driver. By default the scripts find the desktop session (X11 `:0` or Wayland) the way the game's own launch does; with no desktop running they try `kmsdrm` |
| `--windowed` | perf_scenes, smoke | A window instead of fullscreen |
| `--no-audio` | perf_scenes, smoke | Silence (SDL dummy audio) |
| `--defaults` | input_check | Ignore your save: the default GamePi mapping |
| `--remap 21=B,20=A` | input_check | Apply a custom mapping on top, as the setup screen saves one |
| `--scan-pins 4,17` | input_check | Also listen on these unmapped BCM pins (find a button wired elsewhere). Avoid the display's pins and I2C (2, 3) |
| `--in-place` | all | Run from the game folder instead of the `/tmp` symlink sandbox (save still redirected, writes into the game folder still blocked). Use it if a script fails while setting up its sandbox |
| `--tour-input keyboard` | smoke | Tour with key presses instead of GPIO button events |

`perf_scenes.sh` takes about `21 x (seconds + 1)` seconds for the scenes, plus `3 x load-seconds` for the heavy loads. Under each load, one line per phase (`dummy:charge`, `dummy:attack_move`, `battle:battle`, `game:minute tick` ...) shows where the frames go; `game_crowded` brings the pets' per-minute work and the scene's minute tick due 3 s in. PERF-01 allows dips while loading: the boot scene is reported as a loading screen (its longest frame), the Library's Loading frames are counted apart, and a scene that asks to move on is measured only until it does (the game would leave it). A scene "UNDER 29.5 FPS" fails PERF-01 (30 fps, less 0.5 for the timer's millisecond rounding); "dip under 27" means one second fell below 27 fps after the first second (loading is not counted). The `cpu ms` column is the work per frame without the wait: under 33 ms leaves headroom at 30 fps.

## 4. What to paste back

For each script you ran: everything from its `===== OMNIPET PI <name> ... paste from this line =====` line to its `===== exit N - paste up to this line =====` line. Most useful:

- `perf_scenes`: the scene table and the `RESULT` line (plus any `ENTER` / `ERROR` / `LOG` lines under it).
- `smoke`: the whole block (`boot`, `modules`, `scenes`, `frames`, `errors`, `RESULT`). If it failed, also the last 100 lines of the log it names: `tail -n 100 ~/omnipet-test-results/smoke_<time>.log`.
- `input_check`: the two tables and the `RESULT` line. Note any button that did nothing at all.

## Off the Pi

The Python parts also run headless on the PC, for checking the scripts themselves (`--dummy` for perf_scenes and smoke, `--simulate` for input_check, which presses every pin through a stand-in gpiozero):

```bash
# WSL, from E:\Omnipet (pygame from the test venv, see tests/platform/README.md)
~/omnipet-test-venv/bin/python -B tests/platform/pi/perf_scenes.py --game /mnt/e/Omnipet --dummy --seconds 1 --tmp /mnt/e/Omnipet/tmp/platform/pi
~/omnipet-test-venv/bin/python -B tests/platform/pi/smoke.py --game /mnt/e/Omnipet --dummy --seconds 20 --tour --tmp /mnt/e/Omnipet/tmp/platform/pi
~/omnipet-test-venv/bin/python -B tests/platform/pi/input_check.py --game /mnt/e/Omnipet --simulate --defaults --remap 21=B,20=A --tmp /mnt/e/Omnipet/tmp/platform/pi
```

`/mnt/e` is exFAT and cannot hold symlinks, so off the Pi the scripts fall back to `--in-place` on their own. The `/tmp` symlink sandbox is the mode the Pi uses; if it misbehaves there, rerun with `--in-place`.

## Files

| File | Role |
|---|---|
| `_common.sh` | Shared shell set-up: finds the game and its Python, refuses while the game runs, tees the report to `~/omnipet-test-results/` between the paste markers |
| `pi_common.py` | Shared Python set-up: sandbox, write guard, network refusal, display choice, boot with a party (the boot of `tests/release/scene_sweep.py`), system facts (model, temperature, throttling) |
| `perf_scenes.py`, `smoke.py`, `input_check.py` | The checks (run them through the `.sh` wrappers on the Pi) |
