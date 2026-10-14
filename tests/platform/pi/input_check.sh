#!/usr/bin/env bash
# Print the game action each GPIO button produces (UI-01).
#
#   bash input_check.sh [--game DIR] [--seconds 60] [--defaults]
#                       [--remap 21=B,20=A] [--scan-pins 4,17]
#
# Stop the game first (it holds the pins). Press every button once; the
# script stops when all mapped buttons were pressed and released, or after
# --seconds. The mapping is the game's: defaults plus the gpio_map in your
# newest save (read from a copy; --defaults ignores it). See README.md.
set -u
# shellcheck source=_common.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"
pi_init "$@"
pi_run input_check input_check.py
