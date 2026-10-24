#!/usr/bin/env bash
# Boot the game to the main game with a temp save and run it (BLD-01/02/03).
#
#   bash smoke.sh [--game DIR] [--seconds 60] [--tour] [--tour-input gpio|keyboard]
#                 [--windowed] [--driver kmsdrm] [--no-audio] [--verbose]
#
# Stop the game first. --tour also opens every main-menu scene (give it
# --seconds 70). Prints boot timings, modules, scene switches, fps and every
# traceback/error line; the game's full output is kept in
# ~/omnipet-test-results/smoke_<time>.log. See README.md.
set -u
# shellcheck source=_common.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"
pi_init "$@"
pi_run smoke smoke.py
