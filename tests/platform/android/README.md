# Android (BlueStacks) smoke

`android_smoke.py` launches the Omnipet already installed on BlueStacks (`org.omnipet.omnipet`), watches it for a minute and reports crashes, ANRs and Python errors. Checklist BLD-01/02/03 (the build starts and keeps running; launch time) and BLD-05 (the installed versionName against `buildozer.spec`). Background simulation (BLD-06) has its own tools: `tests/unit/android/test_android_offline.py` and `utilities/claude/android_day/`.

```powershell
python -B tests/platform/android/android_smoke.py                 # 60 s, 2 screenshots
python -B tests/platform/android/android_smoke.py --seconds 180 --shots 4
python -B tests/platform/android/android_smoke.py --no-launch     # only watch an app already open
```

## Before running

1. Start BlueStacks (BlueStacks 5, the Pie64 instance used so far) and leave its window open: closing it powers the virtual device off.
2. BlueStacks Settings > Advanced > **Android Debug Bridge (ADB)** on. It listens on `127.0.0.1:5555` (`--serial` for another instance, e.g. `127.0.0.1:5565`).
3. Omnipet installed in it, as you normally install it. The script never installs, updates, clears or force-stops it.

## What it does

1. Finds adb: `--adb`, `$ADB`, BlueStacks' `C:\Program Files\BlueStacks_nxt\HD-Adb.exe` (preferred: it matches the adb server BlueStacks keeps running; a newer SDK adb would restart that server), then the Android SDK's `platform-tools\adb.exe`, then `PATH` (WSL has `/usr/bin/adb`).
2. `adb connect 127.0.0.1:5555`, `get-state`; then `getprop` (model, Android version, ABI), `wm size`, `dumpsys package` (versionName, versionCode, install times) and `cmd package resolve-activity` (the launcher activity, `org.omnipet.offline.PetActivity` per `buildozer.spec`).
3. Reads logcat from the device's current time (`logcat -T`, never `logcat -c`), then `am start -W` of the app (prints its launch time; if it was open it is just brought to the front), polls `pidof` every 2 s, and takes `screencap` screenshots spread over the run.
4. Reports: pid history (a change means it died and restarted), the game's start line and `[Scene] Switching to ...` sequence, crash lines (`FATAL EXCEPTION`, `Fatal signal`, tombstones, `has died`), ANRs, Python error lines and tracebacks, and the dropbox crash/ANR entries for the package (all time).

Output goes to `tmp/platform/android/`: `logcat_<time>.txt` (everything from launch), `logcat_<time>_filtered.txt` (Python, SDL, ActivityManager, crash lines and the app's pid), `screen_<time>_<n>.png`, `android_smoke_<time>.json`. Exit 0 = ran the whole time without a crash, ANR or traceback; 1 = it did not; 2 = no adb or no device.

## Test package (optional, off by default)

To run a build you made without touching your installed game, build it as a separate package the way `utilities/claude/android_day/device/build_test_apk.sh` does (`package.name = omnipetofflinetest`, so `org.omnipet.omnipetofflinetest`), then:

```powershell
python -B tests/platform/android/android_smoke.py --install-test-apk <apk> --test-package org.omnipet.omnipetofflinetest
```

The script reads the APK's real package name with the SDK's `aapt2` and refuses to install anything that is not the `--test-package` you named, and never `org.omnipet.omnipet`. Do not go by file names: `bin/omnipet-offline-1.0.0-arm64-v8a-debug.apk` is the real `org.omnipet.omnipet` package (checked with aapt2, 2026-10-13). The test package is then launched and watched like the real one. Never run `adb root` on BlueStacks (it drops adbd until the player restarts).

## Building the test package

`build_smoke_apk.sh` (run in WSL: `wsl -d Ubuntu -- bash /mnt/e/Omnipet/tests/platform/android/build_smoke_apk.sh`; from Git Bash prefix `MSYS_NO_PATHCONV=1`) stages the current tree like `build/build_android.ps1` in `~/omnipet_smoke_build` as `org.omnipet.omnipetsmoketest` with the DMC, PENC, IC and VB modules, and leaves the APK in `tmp/platform/android/` (about 10 min with the copied buildozer cache). Then `--install-test-apk <apk> --test-package org.omnipet.omnipetsmoketest`; later runs `--test-package org.omnipet.omnipetsmoketest` alone. The first start unpacks the bundle (over a minute): give the first run `--seconds 180`.

## When it was last run

2026-10-13: BlueStacks was not running (only its `HD-Adb.exe` server, no device attached), so only the "no device" path ran: `adb connect` refused, exit 2. The install guard was checked offline against `bin/*.apk` (refused: real package). A run with BlueStacks open is still needed.

2026-10-14: the installed `org.omnipet.omnipet` is a 2026-05-27 build (Kivy's activity, no background simulator): launches in 1 s, 60 s without a crash, in first-run setup. The 1.0 test package (`build_smoke_apk.sh`) installs, unpacks, and runs to the first-run setup (Progression / Free Mode) for 120 s: no crash, ANR or Python error. A run with `--test-package` but no `--install-test-apk` used to launch the player's own app (fixed); doing so started the May build's background service, which crash-looped (`ServicePet_background`, "Empty className detected") until the app is stopped.
