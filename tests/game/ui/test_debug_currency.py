"""The debug scene's "+1k Currency": 1000 of every currency a module declares
(shop.json), up to each currency's cap (the iC's Fight Money stops at 9,999).
Only module currencies: nothing else is touched.
"""
import os
import sys
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "support"))
MODULES = os.path.join(REPO_ROOT, "modules")


@unittest.skipUnless(os.path.isdir(MODULES), "modules/ is gitignored")
class DebugCurrency(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness import Env
        cls.env = Env("240x240")

    def setUp(self):
        self.env.reset()
        self.gg, self.rg = self.env.gg, self.env.rg
        self.game = self.env.game("debug")
        self.env.frames(self.game, 1)
        self.declared = {(name, c["name"]): int(c.get("cap", 0) or 0)
                         for name, module in self.rg.game_modules.items()
                         for c in getattr(module, "currencies", None) or [] if c.get("name")}

    def balance(self, module, name):
        return int((self.gg.currency or {}).get(module, {}).get(name, 0) or 0)

    def test_every_module_currency_gets_1000(self):
        if not self.declared:
            self.skipTest("no module declares a currency")
        before = {key: self.balance(*key) for key in self.declared}
        self.assertTrue(self.game.scene._add_currency())
        for (module, name), cap in self.declared.items():
            with self.subTest(module=module, currency=name):
                expected = before[(module, name)] + 1000
                if cap:
                    expected = min(expected, max(cap, before[(module, name)]))
                self.assertEqual(self.balance(module, name), expected)

    def test_a_cap_holds(self):
        capped = next(((key, cap) for key, cap in self.declared.items() if cap), None)
        if capped is None:
            self.skipTest("no capped currency")
        (module, name), cap = capped
        self.gg.currency.setdefault(module, {})[name] = cap - 10
        self.game.scene._add_currency()
        self.assertEqual(self.balance(module, name), cap)

    def test_nothing_but_module_currencies(self):
        self.game.scene._add_currency()
        self.assertEqual({(m, n) for m, held in self.gg.currency.items() for n in held
                          if (m, n) not in self.declared}, set())

    def test_it_is_on_the_menu(self):
        self.assertIn("+1k Currency", [name for name, _, _ in self.game.scene.debug_options])


if __name__ == "__main__":
    unittest.main()
