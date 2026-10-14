"""pytest setup for everything under tests/.

Puts src/, the repository root and tests/support on sys.path and selects
SDL's dummy video and audio drivers, so any test file runs headless however
it is invoked (`python -m pytest tests/unit/battle/test_arena.py`, or
through tests/run_tests.py). Scratch files go under tmp/tests
(`paths.temp_dir()`), never into the repository.
"""
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "support"))

from paths import TESTS, use_src  # noqa: E402

use_src()
# Some care tests reuse the Android offline test's pet builders.
sys.path.insert(0, os.path.join(TESTS, "unit", "android"))
