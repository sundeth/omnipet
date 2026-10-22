"""Shop items are counted per purchase row (online findings 5 and 7; owner, 2026-10-17).

Items are consumables bought again and again, one server purchase row each;
the game counts each row once (`GamePurchases.item_purchase_ids`). The
account sync used to set every used item back to 1 at each login. A save from
before the rows were counted takes what it holds as what it has at its first
sync, so nothing it used comes back and nothing is counted twice.
"""
import os
import sys
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "support"))
from paths import use_src  # noqa: E402

use_src()

from core import runtime_globals  # noqa: E402,F401  (the game's import order)
from models.game_purchases import GamePurchases  # noqa: E402
from utils.module_utils import _apply_purchase_entries  # noqa: E402


def row(purchase_id, item_id="meat"):
    return {"id": purchase_id, "item_id": item_id, "purchase_type": "item"}


class ItemPurchaseCounting(unittest.TestCase):
    def test_each_row_counts_once(self):
        purchases = GamePurchases()
        _apply_purchase_entries(purchases, [row("p1"), row("p2")])
        self.assertEqual(purchases.get_item_quantity("meat"), 2)
        _apply_purchase_entries(purchases, [row("p1"), row("p2")])
        self.assertEqual(purchases.get_item_quantity("meat"), 2, "a row counted twice")

    def test_a_used_item_does_not_come_back(self):
        purchases = GamePurchases()
        _apply_purchase_entries(purchases, [row("p1")])
        purchases.use_item("meat")
        _apply_purchase_entries(purchases, [row("p1")])
        self.assertEqual(purchases.get_item_quantity("meat"), 0)

    def test_a_purchase_made_here_is_not_counted_again_by_the_sync(self):
        purchases = GamePurchases()
        self.assertTrue(purchases.apply_item_purchase("meat", "p1"))
        _apply_purchase_entries(purchases, [row("p1")])
        self.assertEqual(purchases.get_item_quantity("meat"), 1)

    def test_an_older_save_keeps_what_it_holds_then_counts_new_rows(self):
        old = GamePurchases.from_dict({"items": {"meat": 1}})      # no rows recorded
        self.assertFalse(old.item_purchases_tracked)
        _apply_purchase_entries(old, [row("p1"), row("p2")])
        self.assertEqual(old.get_item_quantity("meat"), 1, "what it held, not re-granted")
        self.assertTrue(old.item_purchases_tracked)
        _apply_purchase_entries(old, [row("p1"), row("p2"), row("p3")])
        self.assertEqual(old.get_item_quantity("meat"), 2, "the new row")

    def test_the_record_survives_a_save(self):
        purchases = GamePurchases()
        purchases.apply_item_purchase("meat", "p1")
        again = GamePurchases.from_dict(purchases.to_dict())
        self.assertEqual((again.item_purchase_ids, again.item_purchases_tracked), ({"p1"}, True))


if __name__ == "__main__":
    unittest.main()
