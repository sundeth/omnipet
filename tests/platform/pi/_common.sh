# shellcheck shell=bash
# Shared by perf_scenes.sh, smoke.sh and input_check.sh (sourced, not run).
#
#   pi_init "$@"     sets HERE GAME PY RESULTS STAMP and ARGS (the rest of the
#                    arguments, passed on to the Python script)
#   pi_run NAME SCRIPT    runs it, tees the output to $RESULTS/NAME_STAMP.txt
#                    between the paste-back markers, exits with its status
#
# Options every script understands:
#   --game DIR        the Omnipet folder (default: $OMNIPET_DIR, else the game
#                     folder these scripts sit in (<game>/tests/platform/pi),
#                     else ~/Games/Omnipet, else ~/Omnipet)
#   --python PATH     the interpreter (default: the first Python 3.10+ with
#                     pygame among the one bundled in the game folder
#                     (Python-3.x/python, Python-3.x/bin/python3[.NN]), a venv
#                     there, python3.NN on the PATH, python3)
#   --allow-running   do not stop when the game is already running

pi_init() {
    HERE="$(cd "$(dirname "${BASH_SOURCE[1]}")" && pwd)"
    GAME="${OMNIPET_DIR:-}"
    PY="${OMNIPET_PYTHON:-}"
    ALLOW_RUNNING=0
    ARGS=()
    TRIED=()
    while [ $# -gt 0 ]; do
        case "$1" in
            --game) GAME="$2"; shift 2 ;;
            --python) PY="$2"; shift 2 ;;
            --allow-running) ALLOW_RUNNING=1; shift ;;
            *) ARGS+=("$1"); shift ;;
        esac
    done
    local asked="$GAME" c
    if [ -z "$GAME" ]; then
        asked="$HERE/../../.., $HOME/Games/Omnipet, $HOME/Omnipet"
        for c in "$HERE/../../.." "$HOME/Games/Omnipet" "$HOME/Omnipet"; do
            if [ -f "$c/main.py" ] && [ -f "$c/src/vpet.py" ]; then GAME="$c"; break; fi
        done
    fi
    if [ -z "$GAME" ] || ! GAME="$(cd "$GAME" 2>/dev/null && pwd -P)" || [ ! -f "$GAME/main.py" ]; then
        echo "Omnipet not found (no main.py in $asked); pass --game /path/to/Omnipet"
        exit 2
    fi
    if [ -z "$PY" ]; then
        pi_pick_python
    fi
    [ -n "$PY" ] || { echo "python3 not found; pass --python PATH"; exit 2; }
    if ! "$PY" -c 'import pygame' >/dev/null 2>&1; then
        echo "pygame is not importable with $PY; pass --python with the interpreter the game uses"
        pi_print_tried
        exit 2
    fi
    if ! "$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
        echo "$PY is Python $("$PY" -c 'import sys; print(sys.version.split()[0])'); the game needs 3.10 or newer."
        pi_print_tried
        echo "Pass --python with the interpreter the game runs with."
        exit 2
    fi
    RESULTS="$HOME/omnipet-test-results"
    mkdir -p "$RESULTS"
    STAMP="$(date +%Y%m%d_%H%M%S)"
    if [ "$ALLOW_RUNNING" = 0 ]; then
        pi_refuse_if_running
    fi
}

# The interpreter the game runs with: the first candidate that is Python 3.10+
# and imports pygame. The GamePi image bundles its own build in the game
# folder; Raspberry Pi OS Bullseye's python3 is 3.9, too old for the game.
pi_pick_python() {
    local c resolved minor
    local candidates=("$GAME"/Python-3*/python "$GAME"/Python-3*/bin/python3
                      "$GAME"/Python-3*/bin/python3.[0-9][0-9] "$GAME"/Python-3*/python3*
                      "$GAME/venv/bin/python" "$GAME/.venv/bin/python")
    # python3.NN on the PATH, newest first (make altinstall installs python3.10)
    for minor in 14 13 12 11 10; do
        candidates+=("python3.$minor")
    done
    candidates+=("python3")
    TRIED=()
    for c in "${candidates[@]}"; do
        resolved="$(command -v "$c" 2>/dev/null)" || continue
        [ -x "$resolved" ] && [ ! -d "$resolved" ] || continue
        case "$resolved" in *-config) continue ;; esac
        if "$resolved" -c 'import sys, pygame; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
            PY="$resolved"
            return
        fi
        TRIED+=("$resolved ($("$resolved" -c 'import sys; print(sys.version.split()[0])' 2>/dev/null || echo "not runnable")$("$resolved" -c 'import pygame' >/dev/null 2>&1 || echo ", no pygame"))")
    done
    PY="$(command -v python3)"
}

pi_print_tried() {
    local t
    [ "${#TRIED[@]}" -gt 0 ] || return 0
    echo "Interpreters tried (none is Python 3.10+ with pygame):"
    for t in "${TRIED[@]}"; do
        echo "  $t"
    done
    if ls -d "$GAME"/Python-3* >/dev/null 2>&1; then
        echo "Executables named python* in the bundled Python folder(s):"
        find "$GAME"/Python-3* -maxdepth 3 -name 'python*' -type f -perm -u+x 2>/dev/null | sed 's/^/  /'
    else
        echo "No Python-3* folder in $GAME"
    fi
}

# The game holds the display and the GPIO pins: two copies fight over them.
pi_refuse_if_running() {
    local pid cwd running=""
    for pid in $(pgrep -f 'main\.py' 2>/dev/null); do
        [ "$pid" = "$$" ] && continue
        cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null || true)"
        if [ "$cwd" = "$GAME" ] || tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -q "$GAME/main.py"; then
            running="$running $pid"
        fi
    done
    if [ -n "$running" ]; then
        echo "Omnipet is running (pid$running): it holds the screen and the buttons."
        if systemctl is-active --quiet omnimon 2>/dev/null; then
            echo "It runs as the omnimon service: sudo systemctl stop omnimon   (start it again afterwards)"
        else
            echo "Quit it from its menu, or: kill$running"
        fi
        echo "Then run this again (or add --allow-running to try anyway)."
        exit 3
    fi
}

pi_run() {
    local name="$1" script="$2" out status
    out="$RESULTS/${name}_${STAMP}.txt"
    echo "===== OMNIPET PI $name $(date '+%Y-%m-%d %H:%M') - paste from this line ====="
    "$PY" -B "$HERE/$script" --game "$GAME" "${ARGS[@]}" 2>&1 | tee "$out"
    status=${PIPESTATUS[0]}
    echo "===== exit $status - paste up to this line (saved: $out) ====="
    exit "$status"
}
