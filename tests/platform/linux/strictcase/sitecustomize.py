# -*- coding: utf-8 -*-
"""Loaded by Python at start-up when this folder is on PYTHONPATH
(tests/platform/linux/run_suite.sh --mode strict does that for every test
process). Installs strict_case for OMNIPET_STRICT_CASE_ROOT, logging case
misses to OMNIPET_CASE_LOG. Does nothing when the variable is unset."""
import os
import sys

_root = os.environ.get("OMNIPET_STRICT_CASE_ROOT")
if _root:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import strict_case
        strict_case.install(_root, os.environ.get("OMNIPET_CASE_LOG"))
    finally:
        del sys.path[0]
