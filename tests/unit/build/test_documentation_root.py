"""The Module Guide is rebuilt beside a one-file exe (2026-10-22 documentation
pass, finding 79).

main.py built ``Documentation/pages/module-guide.html`` from
``os.path.dirname(__file__)``; in a PyInstaller one-file exe that is the
temporary extraction folder, so the guide beside the exe never changed. A
frozen game now uses the exe's folder.
"""
import importlib
import os
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class DocumentationRoot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cwd = os.getcwd()
        os.chdir(ROOT)
        try:
            cls.main = importlib.import_module("main")
        finally:
            os.chdir(cwd)

    def test_from_source_it_is_the_game_folder(self):
        with patch.object(sys, "frozen", False, create=True):
            self.assertEqual(os.path.normcase(self.main.documentation_root()), os.path.normcase(ROOT))

    def test_frozen_it_is_the_exe_folder(self):
        exe = os.path.join(ROOT, "tmp", "Release", "Omnipet.exe")
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", exe):
            self.assertEqual(os.path.normcase(self.main.documentation_root()),
                             os.path.normcase(os.path.dirname(exe)))


if __name__ == "__main__":
    unittest.main()
