#!/usr/bin/env bash
# Time the ways of drawing the menus' UI overlay on the Pi's display (PERF-01).
#
#   bash blit_bench.sh [--game DIR] [--scene settings training status] [--count 200]
#
# Stop the game first. Takes about 30 s. See blit_bench.py.
set -u
# shellcheck source=_common.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"
pi_init "$@"
pi_run blit_bench blit_bench.py
