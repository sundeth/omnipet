"""The debug scene's card tools: "+Card Packs" opens one of every module's
packs into the collection (packs are never held unopened), and "+Shiny Card"
(temporary, for the holo) adds a shiny copy of one card per module.
"""
import os
import sys
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "support"))
MODULES = os.path.join(REPO_ROOT, "modules")


@unittest.skipUnless(os.path.isdir(MODULES), "modules/ is gitignored")
class DebugCards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness import Env
        cls.env = Env("240x240")

    def setUp(self):
        from utils import card_utils
        self.cards = card_utils
        self.env.reset()
        self.gg = self.env.gg
        self.game = self.env.game("debug")
        self.env.frames(self.game, 1)
        self.modules = self.cards.modules_with_cards()
        if not self.modules:
            self.skipTest("no module ships cards")

    def copies(self, field):
        return sum(entry.get(field, 0) for module in (self.gg.card_collection or {}).values()
                   for entry in module.values())

    def test_every_pack_is_opened(self):
        packs = sum(len(data.get("packs") or []) for _name, data in self.modules)
        if not packs:
            self.skipTest("no module has a pack")
        before = self.copies("digital")
        self.assertTrue(self.game.scene._add_card_packs())
        self.assertGreaterEqual(self.copies("digital") - before, packs, "a card a pack at least")

    def test_one_shiny_a_module(self):
        before = self.copies("shiny")
        self.assertTrue(self.game.scene._add_shiny_card())
        shinyable = sum(any(self.cards.card_can_be_shiny(name, c.get("id")) for c in data["cards"])
                        for name, data in self.modules)
        self.assertEqual(self.copies("shiny") - before, shinyable)

    def test_both_are_on_the_menu(self):
        names = [name for name, _, _ in self.game.scene.debug_options]
        self.assertIn("+Card Packs", names)
        self.assertIn("+Shiny Card", names)


if __name__ == "__main__":
    unittest.main()
