#!/usr/bin/env bash
# Frame rate of every scene on the Pi's display, fullscreen 240x240 (PERF-01).
#
#   bash perf_scenes.sh [--game DIR] [--seconds 5] [--scene game battle ...]
#                       [--uncapped] [--windowed] [--driver kmsdrm] [--no-audio]
#
# Stop the game first. Temp save, network refused; about 2 minutes with the
# default 5 s per scene. Output: one line per scene and a RESULT line; a copy
# goes to ~/omnipet-test-results/. See README.md.
set -u
# shellcheck source=_common.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"
pi_init "$@"
pi_run perf_scenes perf_scenes.py
