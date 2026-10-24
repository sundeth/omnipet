# -*- coding: utf-8 -*-
"""Where things are, for every test and release tool.

    ROOT     the repository (main.py, src/, modules/, assets/)
    SRC      ROOT/src, put on sys.path by `use_src()`
    TMP      ROOT/tmp/tests: scratch space (tmp/ is gitignored and never built)

Tests never write anywhere else: `temp_dir()` hands out a fresh folder under
TMP, and the release reports go to ROOT/tmp/release-reports.
"""
import os
import sys
import tempfile

SUPPORT = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(SUPPORT)
ROOT = os.path.dirname(TESTS)
SRC = os.path.join(ROOT, "src")
MODULES = os.path.join(ROOT, "modules")
ASSETS = os.path.join(ROOT, "assets")
TMP = os.path.join(ROOT, "tmp", "tests")
REPORTS = os.path.join(ROOT, "tmp", "release-reports")


def use_src():
    """Put src/, the repository and tests/support on sys.path (idempotent)."""
    for p in (SUPPORT, ROOT, SRC):
        if p not in sys.path:
            sys.path.insert(0, p)


def temp_dir(prefix="omnipet_", keep=False):
    """A new empty folder under ROOT/tmp/tests, removed when the process exits
    unless *keep*."""
    os.makedirs(TMP, exist_ok=True)
    path = tempfile.mkdtemp(prefix=prefix, dir=TMP)
    if not keep:
        import atexit
        import shutil
        atexit.register(shutil.rmtree, path, True)
    return path
