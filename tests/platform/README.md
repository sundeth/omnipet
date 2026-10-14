# Platform scripts

Checks that need another operating system, real hardware or an emulator. Each folder has its own details; this page is the overview. Findings go to `tests/findings/platform.md`.

| Folder | Runs on | Checklist | Entry points |
|---|---|---|---|
| `linux/` | WSL (Ubuntu) on the development PC, or any Linux | UI-08 (exact letter case), MOD-02, every automated test under Linux | `run_suite.sh`, `case_check.py`, `compare_runs.py` |
| `pi/` | The Raspberry Pi Zero 2W GamePi build, over PuTTY (owner) | PERF-01, BLD-01/02/03, UI-01 (GPIO) | `perf_scenes.sh`, `smoke.sh`, `input_check.sh` (see `pi/README.md`) |
| `android/` | BlueStacks on the PC, adb at `127.0.0.1:5555` | BLD-01/02/03, BLD-05 | `android_smoke.py` (see `android/README.md`) |

## Linux / WSL

From PowerShell (from Git Bash, prefix `MSYS_NO_PATHCONV=1` or it rewrites the `/mnt/e/...` paths):

```powershell
wsl -d Ubuntu -- bash /mnt/e/Omnipet/tests/platform/linux/run_suite.sh                 # strict mode, -j 2
wsl -d Ubuntu -- bash /mnt/e/Omnipet/tests/platform/linux/run_suite.sh --compare /mnt/e/Omnipet/tmp/platform/windows_run.json
python -B tests/platform/linux/case_check.py [--runtime]                                # also fine on Windows
```

**The checkout's disk forgives letter case even under Linux.** `E:` is exFAT, which has no case-sensitive mode, and WSL's `/mnt/e` inherits that: `open("/mnt/e/Omnipet/MAIN.PY")` succeeds in WSL. Running the suite there with Linux's Python therefore does not, by itself, catch an asset path in the wrong case. `run_suite.sh` has three modes:

| Mode | How | Catches case slips |
|---|---|---|
| `strict` (default) | In place on `/mnt/e`, with `linux/strictcase/sitecustomize.py` on `PYTHONPATH` in every test process: a path under the checkout that only exists in another letter case fails as on Linux (open, stat, exists/isfile/isdir, listdir/scandir and pygame's image, font, sound and music loaders), and each one is logged with the code that asked for it to `tmp/platform/linux/case_misses.jsonl` | Yes, for Python and pygame file access (not `os.open` or other C extensions) |
| `mirror` | rsync of `src/ assets/ modules/ tests/`, the legacy tests and the root files to an ext4 folder (default `~/omnipet-linux-mirror`, about 2.5 GB, outside the checkout), run there | Yes: real Linux file system |
| `plain` | In place, no shim | No |

Python: `~/omnipet-test-venv` when present, else `python3` if it has pygame, pytest and requests, else the venv is created and `linux/requirements.txt` installed (the Windows PC's versions: pygame 2.6.1, pytest 8.4.1, requests 2.32.3, psutil, pyserial, paho-mqtt, pillow, numpy). No sudo, nothing system-wide. Results: `tmp/platform/linux/run_tests_<mode>.json` / `.log`, `case_misses.jsonl`, `case_check.json`. `-j` defaults to 2 (the PC is shared).

`case_check.py` is the static half, independent of the file system: every module's fixed files and art folders, every monster/enemy sprite set looked up as the game does (`tests/support/sprites.py` order; Color, Dot and HD; it reports where Windows and Linux would draw different sets), backgrounds, device sprites, item art, every file name a module JSON names, and every `assets/...` path in `src/` (literals, `os.path.join("assets", ...)`, f-string prefixes). `--runtime` adds a pass that boots the headless game with strict case and enters every scene; `--misses LOG` summarises a strict run's log.

`compare_runs.py LINUX.json WINDOWS.json` lists test files that fail only on Linux. Rerun such a file on both sides before calling it a finding: other work may have changed it between the runs.

## Raspberry Pi

Copy `tests/platform/pi/` to the Pi (WinSCP or `scp -r`), stop the game, run the three scripts over PuTTY and paste back the block between the `=====` markers. Everything runs from a throw-away sandbox with a temp save; network is refused; writes into the game folder are blocked. Details, options and what to paste: `pi/README.md`. Off the Pi the Python parts run headless (`--dummy`, `--simulate`).

## Android

Start BlueStacks with ADB enabled, then `python -B tests/platform/android/android_smoke.py`. It launches the installed `org.omnipet.omnipet` (never installs, clears or force-stops it), reads logcat from the launch for `--seconds`, polls the pid, takes screenshots into `tmp/platform/android/` and reports crashes, ANRs and Python errors. A separate test package can be installed behind `--install-test-apk ... --test-package ...` only after aapt2 confirms its package name. Details: `android/README.md`.

## Rules these scripts keep

- Scratch only under `tmp/platform/` (the WSL venv and the optional mirror live in the WSL home); never `save/`, `modules/`, `assets/`.
- No real game servers: the Pi scripts and the case-check runtime pass refuse every non-local connection.
- At most 2 test processes at a time on the PC.
- Shell scripts have LF line endings (check with `file` or `grep -c $'\r'`).
