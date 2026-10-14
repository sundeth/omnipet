#!/usr/bin/env bash
# Run the Omnipet test suite under WSL's (or any Linux's) Python.
#
#   bash tests/platform/linux/run_suite.sh [--mode strict|mirror|plain] [-j N]
#        [--repo DIR] [--venv DIR] [--mirror-dir DIR] [--no-case-check]
#        [--compare WINDOWS_RUN.json] [-- run_tests.py arguments ...]
#
# From Windows:  wsl -d Ubuntu -- bash /mnt/e/Omnipet/tests/platform/linux/run_suite.sh
#
# Why three modes: the checkout is on E:, an exFAT disk. exFAT is
# case-insensitive, and so is WSL's view of it (/mnt/e), so running the suite
# there "on Linux" still forgives every letter-case slip.
#   strict  (default) run in place on /mnt/e with strictcase/sitecustomize.py
#           loaded into every test process: a path under the checkout that only
#           exists in another letter case fails as it would on Linux, and each
#           one is logged with the code that asked for it.
#   mirror  rsync src/ assets/ modules/ tests/ and the root files to an ext4
#           folder (default ~/omnipet-linux-mirror, about 2.5 GB, outside
#           the checkout) and run there: real Linux file-system semantics.
#   plain   in place, no shim (Linux Python, but case-forgiving disk).
#
# Python: the first of $VENV (default ~/omnipet-test-venv), then python3 if it
# has pygame, pytest and requests; otherwise the venv is created and
# requirements.txt (the Windows PC's versions) installed into it. Nothing is
# installed system-wide and no sudo is used.
#
# Output (always in the checkout): tmp/platform/linux/
#   run_tests_<mode>.json / .log   the run_tests.py results
#   case_misses.jsonl              strict mode: every case-only path access
#   case_check.json                the static case check (case_check.py)
# Exit status: run_tests.py's (1 when any test file failed or crashed).
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
MODE=strict
JOBS=2
VENV="${OMNIPET_TEST_VENV:-$HOME/omnipet-test-venv}"
MIRROR="${OMNIPET_LINUX_MIRROR:-$HOME/omnipet-linux-mirror}"
CASE_CHECK=1
COMPARE=""
EXTRA=()

while [ $# -gt 0 ]; do
    case "$1" in
        --mode) MODE="$2"; shift 2 ;;
        -j) JOBS="$2"; shift 2 ;;
        --repo) REPO="$(cd "$2" && pwd)"; shift 2 ;;
        --venv) VENV="$2"; shift 2 ;;
        --mirror-dir) MIRROR="$2"; shift 2 ;;
        --no-case-check) CASE_CHECK=0; shift ;;
        --compare) COMPARE="$2"; shift 2 ;;
        --) shift; EXTRA=("$@"); break ;;
        -h|--help) sed -n '2,36p' "$0"; exit 0 ;;
        *) EXTRA+=("$1"); shift ;;
    esac
done
case "$MODE" in strict|mirror|plain) ;; *) echo "unknown --mode $MODE"; exit 2 ;; esac

OUT="$REPO/tmp/platform/linux"
mkdir -p "$OUT"

# ---------------------------------------------------------------- Python
have_deps() { "$1" -c 'import pygame, pytest, requests' >/dev/null 2>&1; }
if [ -x "$VENV/bin/python" ] && have_deps "$VENV/bin/python"; then
    PY="$VENV/bin/python"
elif command -v python3 >/dev/null 2>&1 && have_deps python3; then
    PY="$(command -v python3)"
else
    echo "[suite] creating venv $VENV (pygame/pytest/requests missing)"
    python3 -m venv "$VENV" || { echo "[suite] python3 -m venv failed (python3-venv missing?)"; exit 2; }
    "$VENV/bin/python" -m pip install -q --upgrade pip
    if ! "$VENV/bin/python" -m pip install -q -r "$HERE/requirements.txt"; then
        echo "[suite] pinned install failed; installing unpinned"
        "$VENV/bin/python" -m pip install -q $(sed -e 's/#.*//' -e 's/==.*//' "$HERE/requirements.txt")
    fi
    PY="$VENV/bin/python"
fi
echo "[suite] $(uname -sr) | $("$PY" -c 'import sys,pygame,pytest; print("python", sys.version.split()[0], "| pygame", pygame.version.ver, "| pytest", pytest.__version__)' 2>/dev/null | tail -1)"
echo "[suite] interpreter $PY"

# ---------------------------------------------------------------- where to run
RUN_ROOT="$REPO"
export SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1
unset OMNIPET_STRICT_CASE_ROOT OMNIPET_CASE_LOG
if [ "$MODE" = strict ]; then
    : > "$OUT/case_misses.jsonl"
    export PYTHONPATH="$HERE/strictcase${PYTHONPATH:+:$PYTHONPATH}"
    export OMNIPET_STRICT_CASE_ROOT="$REPO"
    export OMNIPET_CASE_LOG="$OUT/case_misses.jsonl"
    echo "[suite] strict letter case under $REPO (log: tmp/platform/linux/case_misses.jsonl)"
elif [ "$MODE" = mirror ]; then
    command -v rsync >/dev/null 2>&1 || { echo "[suite] rsync not found"; exit 2; }
    case "$MIRROR" in /mnt/*) echo "[suite] warning: $MIRROR is a Windows drive, probably case-insensitive";; esac
    echo "[suite] mirroring to $MIRROR"
    mkdir -p "$MIRROR"
    RS=(rsync -a --delete --exclude=__pycache__ --exclude='*.pyc')
    for d in src assets modules tests android_src; do
        [ -d "$REPO/$d" ] && "${RS[@]}" "$REPO/$d/" "$MIRROR/$d/"
    done
    mkdir -p "$MIRROR/utilities/claude"
    [ -d "$REPO/utilities/claude/tests" ] && "${RS[@]}" "$REPO/utilities/claude/tests/" "$MIRROR/utilities/claude/tests/"
    find "$REPO" -maxdepth 1 -type f \( -name '*.py' -o -name '*.spec' -o -name '*.sh' -o -name '*.txt' \) \
        -exec cp -p {} "$MIRROR/" \;
    find "$REPO/utilities/claude" -maxdepth 1 -type f -name '*.py' -exec cp -p {} "$MIRROR/utilities/claude/" \; 2>/dev/null
    mkdir -p "$MIRROR/save" "$MIRROR/tmp"
    RUN_ROOT="$MIRROR"
fi

# ---------------------------------------------------------------- run
cd "$RUN_ROOT" || exit 2
JSON="$OUT/run_tests_$MODE.json"
LOG="$OUT/run_tests_$MODE.log"
START=$(date +%s)
"$PY" -B tests/run_tests.py -j "$JOBS" --json "$JSON" "${EXTRA[@]}" 2>&1 | tee "$LOG"
STATUS=${PIPESTATUS[0]}
echo "[suite] run_tests.py exit $STATUS after $(( $(date +%s) - START )) s; results $JSON"

# ---------------------------------------------------------------- case reports
unset OMNIPET_STRICT_CASE_ROOT
export PYTHONPATH="${PYTHONPATH#"$HERE/strictcase:"}"
[ "$PYTHONPATH" = "$HERE/strictcase" ] && unset PYTHONPATH
if [ "$MODE" = strict ] && [ -s "$OUT/case_misses.jsonl" ]; then
    "$PY" -B "$HERE/case_check.py" --root "$REPO" --misses "$OUT/case_misses.jsonl" --only-misses
elif [ "$MODE" = strict ]; then
    echo "[suite] no case-only path was accessed during the run"
fi
if [ "$CASE_CHECK" = 1 ]; then
    "$PY" -B "$HERE/case_check.py" --root "$REPO" --json "$OUT/case_check.json"
fi
if [ -n "$COMPARE" ]; then
    "$PY" -B "$HERE/compare_runs.py" "$JSON" "$COMPARE"
fi
exit "$STATUS"
