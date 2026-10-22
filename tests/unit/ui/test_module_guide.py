"""The player documentation's Module Guide is rebuilt from its template (P-07, decision 20).

Every start rebuilds Documentation/pages/module-guide.html from the modules
that carry documentation. Its template had moved out from under the builder
(game/core/utils), so every start logged "Template not found" and the page
kept a 2025 list with a second copy of the page spliced into it. The template
is Documentation/templates/module-guide_template.html, with markers.
"""
import json
import os
import shutil
import sys
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "support"))
from paths import temp_dir, use_src  # noqa: E402

use_src()

from core import runtime_globals  # noqa: E402,F401  (the game's import order)
from utils.document_utils import DocumentationBuilder  # noqa: E402


class ModuleGuide(unittest.TestCase):
    def setUp(self):
        self.root = temp_dir("module_guide_")
        os.makedirs(os.path.join(self.root, "Documentation", "templates"))
        shutil.copy(os.path.join(REPO_ROOT, "Documentation", "templates", "module-guide_template.html"),
                    os.path.join(self.root, "Documentation", "templates"))

    def module(self, name, documented=True):
        path = os.path.join(self.root, "modules", name)
        os.makedirs(os.path.join(path, "documentation"))
        with open(os.path.join(path, "module.json"), "w", encoding="utf-8") as fh:
            json.dump({"name": name, "version": "1.0.0", "description": f"The {name} module."}, fh)
        open(os.path.join(path, "logo.png"), "wb").close()      # a module needs a logo or Flag.png
        if documented:
            open(os.path.join(path, "documentation", "index.html"), "w").close()

    def build(self):
        builder = DocumentationBuilder(self.root)
        self.assertTrue(builder.build_module_guide())
        with open(builder.output_path, encoding="utf-8") as fh:
            return fh.read()

    def test_the_documented_modules_are_listed_once_in_one_page(self):
        self.module("DMC")
        self.module("PENC")
        self.module("NODOCS", documented=False)
        page = self.build()
        self.assertEqual(page.count("<!DOCTYPE"), 1)
        self.assertEqual(page.count('class="module-card"'), 2)
        self.assertIn("../../modules/DMC/documentation/index.html", page)
        self.assertNotIn("NODOCS", page)
        self.assertNotIn("<!-- MODULE_LIST -->", page)
        self.assertNotIn("<!-- MODULE_GUIDE_CSS -->", page)

    def test_no_modules_says_how_to_add_them(self):
        os.makedirs(os.path.join(self.root, "modules"))
        page = self.build()
        self.assertIn("No Module Documentation Found", page)


if __name__ == "__main__":
    unittest.main()
