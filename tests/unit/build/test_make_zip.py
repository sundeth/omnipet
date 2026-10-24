"""Release zips extract the same on every platform (build/make_zip.py).

The builds agent found (2026-10-22) that .NET's ZipFile under Windows
PowerShell 5.1 wrote entry names with backslashes and no Unix modes: Linux
unzip exited 1, Python's zipfile extracted loose "assets\\x.png" files, and
the GamePi/Batocera folders were not writable nor launch.sh executable.
"""
import os
import shutil
import stat
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "build"))

import make_zip  # noqa: E402


class MakeZip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="make_zip_")
        src = os.path.join(self.tmp, "src")
        for folder in ("assets/sub", "save", "modules"):
            os.makedirs(os.path.join(src, folder))
        files = {"launch.sh": "echo hi\n", "batocera.py": "#!/usr/bin/env python3\n",
                 "main.py": "print(1)\n", "assets/sub/a.png": "x"}
        for name, text in files.items():
            with open(os.path.join(src, name), "w", encoding="utf-8") as fh:
                fh.write(text)
        self.zip = os.path.join(self.tmp, "out.zip")
        make_zip.make_zip(src, self.zip)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def modes(self):
        with zipfile.ZipFile(self.zip) as zf:
            return {i.filename: i.external_attr >> 16 for i in zf.infolist()}

    def test_names_use_forward_slashes_and_keep_empty_folders(self):
        names = set(self.modes())
        self.assertIn("assets/sub/a.png", names)
        self.assertIn("save/", names)
        self.assertIn("modules/", names)
        self.assertFalse([n for n in names if "\\" in n])

    def test_unix_modes(self):
        modes = self.modes()
        self.assertEqual(stat.S_IMODE(modes["save/"]), 0o755)
        self.assertTrue(stat.S_ISDIR(modes["save/"]))
        self.assertEqual(stat.S_IMODE(modes["launch.sh"]), 0o755)
        self.assertEqual(stat.S_IMODE(modes["batocera.py"]), 0o755, "a #! script")
        self.assertEqual(stat.S_IMODE(modes["main.py"]), 0o644)
        self.assertTrue(stat.S_ISREG(modes["main.py"]))

    def test_pythons_zipfile_extracts_folders(self):
        out = os.path.join(self.tmp, "x")
        zipfile.ZipFile(self.zip).extractall(out)
        self.assertTrue(os.path.isfile(os.path.join(out, "assets", "sub", "a.png")))
        self.assertTrue(os.path.isdir(os.path.join(out, "save")))


if __name__ == "__main__":
    unittest.main()
