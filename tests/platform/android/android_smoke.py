#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Launch the installed Omnipet on BlueStacks and watch it (BLD-01/02/03, BLD-05).

    python -B tests/platform/android/android_smoke.py [--seconds 60] [--serial 127.0.0.1:5555]
           [--adb PATH] [--package org.omnipet.omnipet] [--no-launch] [--shots 2]
           [--install-test-apk APK --test-package org.omnipet.omnipetofflinetest]

Read-only towards the device unless --install-test-apk is given:
  1. adb (BlueStacks' HD-Adb.exe first: it matches the adb server BlueStacks
     runs; then the Android SDK's, then PATH), `adb connect` the serial, and
     check the device answers;
  2. device and app facts: model, Android version, ABI; the package's
     versionName/versionCode (compared with buildozer.spec, BLD-05) and its
     launcher activity;
  3. `am start -W` of the installed app (its launch time), then logcat from
     that moment for --seconds, filtered to Python, SDL and crash lines;
     the app's pid is polled to see it die or restart;
  4. screenshots (screencap) into tmp/platform/android/;
  5. a report: crashes (FATAL EXCEPTION, Fatal signal, tombstones), ANRs,
     Python tracebacks and the game's own "[Error]" lines, the scenes the game
     switched to, and the dropbox crash/ANR entries for the package.

Never: install, uninstall, clear data or force-stop org.omnipet.omnipet,
`adb root`, `logcat -c` (the log is read from the launch time instead), or
anything that closes BlueStacks. --install-test-apk installs only an APK
whose package (read with the SDK's aapt2) is not org.omnipet.omnipet, and
requires --test-package to name it (the convention of
utilities/claude/android_day/device/: org.omnipet.omnipetofflinetest).
Do not trust an APK's file name: bin/omnipet-offline-*.apk is the real package.

Exit 0 when the app ran for --seconds without a crash, ANR or traceback;
1 when it did not; 2 when no device or no adb was found.
"""
import argparse
import datetime
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
OUT = os.path.join(ROOT, "tmp", "platform", "android")
REAL_PACKAGE = "org.omnipet.omnipet"
#: buildozer.spec android.entrypoint (the launcher activity) when the device cannot tell.
DEFAULT_ACTIVITY = "org.omnipet.offline.PetActivity"
CRASH = re.compile(r"FATAL EXCEPTION|Fatal signal|SIGSEGV|SIGABRT|backtrace:|tombstone|"
                   r"has died|Force finishing|Process crashed|beginning of crash", re.I)
ANR = re.compile(r"ANR in |Application Not Responding|not responding", re.I)
PY_ERR = re.compile(r"Traceback|Error|Exception|\[!\]|failed", re.I)
KEEP_TAGS = re.compile(r"\b(python|SDL|PythonActivity|PythonService|AndroidRuntime|libc|DEBUG|"
                       r"ActivityManager|ActivityTaskManager|Omnipet|omnipet|PetActivity|PetNotifications)\b")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# ---------------------------------------------------------------- adb
def find_adb(explicit=None):
    cands = [explicit, os.environ.get("ADB"),
             r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe",
             r"C:\Program Files\BlueStacks\HD-Adb.exe",
             os.path.join(os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk", "platform-tools", "adb.exe"),
             os.path.join(os.environ.get("ANDROID_HOME", "") or os.environ.get("ANDROID_SDK_ROOT", ""),
                          "platform-tools", "adb.exe"),
             shutil.which("adb"), "/usr/bin/adb", os.path.expanduser("~/Android/Sdk/platform-tools/adb")]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def find_aapt2():
    roots = [os.path.join(os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk", "build-tools"),
             os.path.join(os.environ.get("ANDROID_HOME", "") or os.environ.get("ANDROID_SDK_ROOT", ""), "build-tools"),
             os.path.expanduser("~/Android/Sdk/build-tools")]
    for r in roots:
        hits = sorted(glob.glob(os.path.join(r, "*", "aapt2.exe")) + glob.glob(os.path.join(r, "*", "aapt2")))
        if hits:
            return hits[-1]
    return shutil.which("aapt2")


class Adb:
    def __init__(self, exe, serial):
        self.exe, self.serial = exe, serial

    def run(self, *args, timeout=30, serial=True):
        cmd = [self.exe] + (["-s", self.serial] if serial and self.serial else []) + list(args)
        try:
            p = subprocess.run(cmd, capture_output=True, timeout=timeout)
            return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")
        except subprocess.TimeoutExpired:
            return 124, "", f"timeout after {timeout}s: {' '.join(args)}"

    def sh(self, cmd, timeout=30):
        return self.run("shell", cmd, timeout=timeout)[1].strip()


# ---------------------------------------------------------------- helpers
def buildozer_version():
    try:
        with open(os.path.join(ROOT, "buildozer.spec"), encoding="utf-8", errors="replace") as fh:
            m = re.search(r"^version\s*=\s*(\S+)", fh.read(), re.M)
        return m.group(1) if m else None
    except OSError:
        return None


def package_facts(adb, pkg):
    dump = adb.sh(f"dumpsys package {pkg}", timeout=60)
    facts = {}
    for key in ("versionName", "versionCode", "firstInstallTime", "lastUpdateTime", "targetSdk", "minSdk"):
        m = re.search(rf"{key}=(\S+)", dump)
        if m:
            facts[key] = m.group(1)
    facts["installed"] = bool(adb.sh(f"pm path {pkg}"))
    act = adb.sh(f"cmd package resolve-activity --brief {pkg}").splitlines()
    facts["activity"] = next((l.strip() for l in reversed(act) if "/" in l), None)
    return facts


def device_now(adb):
    """Device clock as logcat -T wants it ('MM-DD hh:mm:ss.mmm')."""
    out = adb.sh("date '+%m-%d %H:%M:%S'")
    return (out + ".000") if re.fullmatch(r"\d\d-\d\d \d\d:\d\d:\d\d", out) else None


class Logcat(threading.Thread):
    def __init__(self, adb, since, path):
        super().__init__(daemon=True)
        self.adb, self.since, self.path = adb, since, path
        self.lines, self.proc = [], None

    def run(self):
        args = [self.adb.exe, "-s", self.adb.serial, "logcat", "-v", "threadtime"]
        if self.since:
            args += ["-T", self.since]
        self.proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        with open(self.path, "w", encoding="utf-8") as fh:
            for raw in self.proc.stdout:
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                self.lines.append(line)
                fh.write(line + "\n")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def screenshot(adb, path):
    try:
        p = subprocess.run([adb.exe, "-s", adb.serial, "exec-out", "screencap", "-p"], capture_output=True, timeout=30)
    except subprocess.TimeoutExpired:
        return None
    data = p.stdout
    if not data.startswith(b"\x89PNG"):
        data = data.replace(b"\r\n", b"\n")          # old adb shells translated line ends
    if not data.startswith(b"\x89PNG"):
        return None
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def install_test_apk(adb, apk, test_pkg):
    """Install a TEST package only: its real package name must be test_pkg."""
    if not test_pkg or test_pkg == REAL_PACKAGE:
        raise SystemExit(f"--test-package must name the test package (not {REAL_PACKAGE})")
    aapt2 = find_aapt2()
    if not aapt2:
        raise SystemExit("aapt2 (Android SDK build-tools) not found: cannot verify the APK's package; not installing")
    p = subprocess.run([aapt2, "dump", "packagename", apk], capture_output=True, text=True)
    name = p.stdout.strip().splitlines()[-1].strip() if p.stdout.strip() else ""
    if name != test_pkg:
        raise SystemExit(f"{apk} is package {name or '?'} (aapt2), not {test_pkg}: not installing")
    code, out, err = adb.run("install", "-r", apk, timeout=600)
    print(f"install  {test_pkg}: {(out + err).strip().splitlines()[-1] if (out + err).strip() else code}")
    if code:
        raise SystemExit(1)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--adb")
    ap.add_argument("--serial", default="127.0.0.1:5555")
    ap.add_argument("--package", default=REAL_PACKAGE)
    ap.add_argument("--activity", help="launcher activity (default: what the device resolves)")
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--shots", type=int, default=2, help="screenshots, spread over the run (the last at the end)")
    ap.add_argument("--no-launch", action="store_true", help="only watch an app that is already running")
    ap.add_argument("--install-test-apk", metavar="APK")
    ap.add_argument("--test-package")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()
    stamp = time.strftime("%Y%m%d_%H%M%S")
    os.makedirs(args.out, exist_ok=True)
    print("== Omnipet android_smoke (BlueStacks) ==")

    exe = find_adb(args.adb)
    if not exe:
        print("RESULT   no adb found: install the Android SDK platform-tools or BlueStacks, or pass --adb PATH")
        sys.exit(2)
    adb = Adb(exe, args.serial)
    code, out, err = adb.run("version", serial=False)
    print(f"adb      {exe} ({(out.splitlines() or ['?'])[0].strip()})")
    if ":" in args.serial:
        code, out, err = adb.run("connect", args.serial, serial=False, timeout=20)
        print(f"connect  {args.serial}: {(out + err).strip() or code}")
    code, state, err = adb.run("get-state", timeout=15)
    if code or state.strip() != "device":
        devices = adb.run("devices", serial=False)[1].strip().replace("\n", "; ")
        print(f"RESULT   no device at {args.serial} ({(state + err).strip() or 'no answer'}); adb devices: {devices}")
        print("         Start BlueStacks (and enable Settings > Advanced > Android Debug Bridge), then run this again.")
        sys.exit(2)

    props = {k: adb.sh(f"getprop {k}") for k in ("ro.product.model", "ro.build.version.release",
                                                  "ro.build.version.sdk", "ro.product.cpu.abi")}
    print(f"device   {props['ro.product.model']} Android {props['ro.build.version.release']} "
          f"(API {props['ro.build.version.sdk']}, {props['ro.product.cpu.abi']}) at {args.serial}")
    size = adb.sh("wm size").replace("Physical size:", "").strip()
    if size:
        print(f"screen   {size}")
    if args.install_test_apk:
        install_test_apk(adb, args.install_test_apk, args.test_package)
    if args.test_package:
        # --test-package alone watches a test package installed before; it
        # used to be ignored without --install-test-apk, and the run then
        # launched the player's own org.omnipet.omnipet (2026-10-14)
        if args.test_package == REAL_PACKAGE:
            print(f"RESULT   --test-package may not be the player's own {REAL_PACKAGE}")
            sys.exit(2)
        args.package = args.test_package
    facts = package_facts(adb, args.package)
    if not facts["installed"]:
        print(f"RESULT   {args.package} is not installed on the device (this script never installs it)")
        sys.exit(1)
    want = buildozer_version()
    vn = facts.get("versionName")
    ver_note = "" if not want else (" = buildozer.spec" if vn == want else f" (buildozer.spec says {want}: BLD-05)")
    print(f"app      {args.package} versionName {vn}{ver_note}, versionCode {facts.get('versionCode')}, "
          f"updated {facts.get('lastUpdateTime', '?')}")
    activity = args.activity or facts.get("activity") or f"{args.package}/{DEFAULT_ACTIVITY}"
    print(f"activity {activity}")

    # logcat from now on (no `logcat -c`)
    since = device_now(adb)
    raw_path = os.path.join(args.out, f"logcat_{stamp}.txt")
    log = Logcat(adb, since, raw_path)
    log.start()
    time.sleep(1.0)
    pid0 = adb.sh(f"pidof {args.package}")
    launch = {}
    if not args.no_launch:
        out = adb.sh(f"am start -W -n {activity}", timeout=90)
        for key in ("Status", "LaunchState", "TotalTime", "WaitTime"):
            m = re.search(rf"{key}:\s*(\S+)", out)
            if m:
                launch[key] = m.group(1)
        warn = re.search(r"Warning: (.*)", out)
        print(f"launch   {launch.get('Status', '?')} {launch.get('LaunchState', '')} total {launch.get('TotalTime', '?')} ms"
              + (f" ({warn.group(1).strip()})" if warn else "") + (f"; was already running as pid {pid0}" if pid0 else ""))
    start = time.time()
    pids, shots = [], []
    shot_times = [args.seconds * (i + 1) / max(1, args.shots) for i in range(max(0, args.shots))]
    while time.time() - start < args.seconds:
        pid = adb.sh(f"pidof {args.package}")
        if not pids or pids[-1][1] != pid:
            pids.append((round(time.time() - start, 1), pid))
        if shot_times and time.time() - start >= shot_times[0] - 2:
            shot_times.pop(0)
            p = screenshot(adb, os.path.join(args.out, f"screen_{stamp}_{len(shots) + 1}.png"))
            if p:
                shots.append(p)
        time.sleep(2.0)
    if shot_times:
        p = screenshot(adb, os.path.join(args.out, f"screen_{stamp}_{len(shots) + 1}.png"))
        if p:
            shots.append(p)
    log.stop()
    log.join(5)

    # report
    lines = log.lines
    pid_now = pids[-1][1] if pids else ""
    pid_set = {p for _, p in pids if p}
    mine = [l for l in lines if KEEP_TAGS.search(l) or any(p and f" {p} " in l for p in pid_set)]
    filt_path = os.path.join(args.out, f"logcat_{stamp}_filtered.txt")
    with open(filt_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(mine) + "\n")
    crashes = [l for l in mine if CRASH.search(l) and (args.package in l or any(p and f" {p} " in l for p in pid_set)
                                                      or "AndroidRuntime" in l or "DEBUG" in l)]
    anrs = [l for l in mine if ANR.search(l) and args.package in l]
    py = [l for l in mine if re.search(r"\bpython\b", l) and PY_ERR.search(l)]
    scenes = [m.group(1) for l in mine for m in [re.search(r"\[Scene\] Switching to (\w+)", l)] if m]
    started = any("Game initialized successfully" in l or "Starting main game loop" in l for l in mine)
    drop = adb.sh("dumpsys dropbox --print data_app_crash data_app_anr data_app_native_crash", timeout=60)
    drop_hits = []
    for block in re.split(r"\n(?=\d{4}-\d\d-\d\d \d\d:\d\d:\d\d )", drop):
        head = block.split("\n", 1)[0]
        m = re.match(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (\S+)", head)
        if m and args.package in block:
            try:
                when = datetime.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                when = None
            drop_hits.append((m.group(1), m.group(2), when))
    pid_txt = " > ".join("%s@%gs" % (p or "none", t) for t, p in pids) or "?"
    print(f"run      {args.seconds:g} s; pid {pid_txt}")
    print(f"game     {'main loop started' if started else 'no start line seen'}; scenes: {' > '.join(scenes) or 'none logged'}")
    print(f"logcat   {len(lines)} lines, {len(mine)} kept: {filt_path}")
    print(f"crashes  {len(crashes)}" + "".join(f"\n         {l[:300]}" for l in crashes[:12]))
    print(f"ANRs     {len(anrs)}" + "".join(f"\n         {l[:300]}" for l in anrs[:6]))
    print(f"python   {len(py)} error lines" + "".join(f"\n         {l[:300]}" for l in py[:20]))
    if drop_hits:
        print(f"dropbox  {len(drop_hits)} crash/ANR entries for {args.package} (all time, newest last):"
              + "".join(f"\n         {w} {k}" for w, k, _ in drop_hits[-6:]))
    print(f"shots    {', '.join(shots) or 'none taken'}")
    died = len(pid_set) > 1 or not pid_now
    tracebacks = [l for l in py if "Traceback" in l]
    ok = not crashes and not anrs and not tracebacks and not died
    why = []
    if not pid_now:
        why.append("the app is not running at the end")
    elif len(pid_set) > 1:
        why.append("the app restarted (pid changed)")
    if crashes:
        why.append(f"{len(crashes)} crash lines")
    if anrs:
        why.append(f"{len(anrs)} ANR lines")
    if tracebacks:
        why.append(f"{len(tracebacks)} Python tracebacks")
    print(f"RESULT   android {'PASS' if ok else 'FAIL'}" + (": " + "; ".join(why) if why else ""))
    with open(os.path.join(args.out, f"android_smoke_{stamp}.json"), "w", encoding="utf-8") as fh:
        json.dump({"device": props, "app": facts, "launch": launch, "pids": pids, "crashes": crashes, "anrs": anrs,
                   "python_errors": py, "scenes": scenes, "screenshots": shots, "ok": ok}, fh, indent=1)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
