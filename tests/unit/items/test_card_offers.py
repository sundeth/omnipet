"""Card offers: shop lines that sell one card of a pack (owner, 2026-10-20).

A shop.json line ``card_offer`` names a cards.json pack and sells ONE card of
it, a different card each day and the same all day: World's Card Shop, six
single cards a day, is six such lines. The lines of one pack show different
cards, drawn by the pack's odds from a random seeded with the day (nothing
is saved). The price is the card's rarity's in ``rarity_prices``, else the
line's ``price``. Buying adds the card to the collection.
"""
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SRC = os.path.join(REPO_ROOT, "src")
for path in (SRC, REPO_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)
MODULES = os.path.join(REPO_ROOT, "modules")

from core import game_globals, runtime_globals  # noqa: E402
from utils import card_utils, currency_utils  # noqa: E402

RARITY = ("Common", "Rare", "Legendary")
CARDS = [{"id": f"c{n}", "name": f"Card {n}", "rarity": RARITY[n % 3]} for n in range(10)]
PACKS = [{"id": "offers", "name": "Offers", "cards_per_pack": 1,
          "cards": [{"id": c["id"], "odds": 1} for c in CARDS]},
         {"id": "tiny", "name": "Tiny", "cards": [{"id": "c1", "odds": 1}, {"id": "c2", "odds": 1}]}]
PRICES = {"Common": 500, "Rare": 1500, "Legendary": 5000}


def offer_line(pack="offers", **extra):
    return dict({"card_offer": pack, "price": 0, "rarity_prices": dict(PRICES), "unlock": ""}, **extra)


class CardOffers(unittest.TestCase):
    def setUp(self):
        self.module = SimpleNamespace(name="TEST", items=[])
        self.shop = {"name": "Card Shop", "currency": "Bits",
                     "items": [{"card_pack": "offers", "price": 500, "unlock": ""}] + [offer_line() for _ in range(6)]}
        data = {"cards": CARDS, "packs": PACKS}
        for p in (patch.object(card_utils, "get_module_cards", lambda name: data),
                  patch.object(runtime_globals, "game_console", Mock(), create=True),
                  patch.object(game_globals, "pet_list", [])):
            p.start()
            self.addCleanup(p.stop)

    def offers(self, day):
        return currency_utils.card_offers(self.module, self.shop, day)

    def test_six_different_cards_the_same_all_day(self):
        first = self.offers("2026-10-20")
        self.assertEqual(sorted(first), [1, 2, 3, 4, 5, 6], "every offer line, by its index")
        ids = [card["id"] for _pack, card in first.values()]
        self.assertEqual(len(set(ids)), 6, "the lines of one pack show different cards")
        self.assertEqual(ids, [card["id"] for _pack, card in self.offers("2026-10-20").values()])

    def test_another_day_brings_other_cards(self):
        days = {tuple(card["id"] for _p, card in self.offers(f"2026-11-{d:02d}").values()) for d in range(1, 11)}
        self.assertGreater(len(days), 1)

    def test_more_lines_than_cards_leave_the_rest_out(self):
        self.shop["items"] = [offer_line("tiny") for _ in range(4)]
        self.assertEqual(len(self.offers("2026-10-20")), 2)

    def test_the_stock_prices_each_card_by_its_rarity(self):
        with patch.object(currency_utils, "offer_day", return_value="2026-10-20"):
            stock = currency_utils.shop_stock(self.module, self.shop)
        self.assertEqual([o.kind for o in stock], ["card_pack"] + ["card"] * 6)
        for offer in stock[1:]:
            self.assertEqual(offer.price, PRICES[offer.card["rarity"]], offer.name)
            self.assertEqual(offer.name, offer.card["name"])

    def test_a_rarity_left_out_costs_the_line_price(self):
        line = offer_line(price=70, rarity_prices={"Rare": 1500})
        self.assertEqual(currency_utils.card_offer_price(line, {"rarity": "Common"}), 70)
        self.assertEqual(currency_utils.card_offer_price(line, {"rarity": "Rare"}), 1500)

    def test_buying_adds_the_card_and_pays_its_price(self):
        with patch.object(currency_utils, "offer_day", return_value="2026-10-20"):
            offer = currency_utils.shop_stock(self.module, self.shop)[1]
        with patch.object(currency_utils, "spend", return_value=True) as spend, \
                patch.object(card_utils, "add_card_copy") as add:
            got = currency_utils.buy(self.module, self.shop, offer)
        spend.assert_called_once_with("TEST", "Bits", offer.price)
        add.assert_called_once_with("TEST", offer.card["id"])
        self.assertEqual(got, [(offer.card, False)])

    def test_nothing_is_added_when_the_balance_is_short(self):
        with patch.object(currency_utils, "offer_day", return_value="2026-10-20"):
            offer = currency_utils.shop_stock(self.module, self.shop)[1]
        with patch.object(currency_utils, "spend", return_value=False), \
                patch.object(card_utils, "add_card_copy") as add:
            self.assertIsNone(currency_utils.buy(self.module, self.shop, offer))
        add.assert_not_called()


@unittest.skipUnless(os.path.isfile(os.path.join(MODULES, "DW1", "shop.json")), "DW1 not installed")
class DW1CardShop(unittest.TestCase):
    def test_six_offers_of_world_cards_but_shogungekomon(self):
        def load(name):
            with open(os.path.join(MODULES, "DW1", name), encoding="utf-8-sig") as fh:
                return json.load(fh)
        cards = load("cards.json")
        shop = next(s for s in load("shop.json")["shop"] if s["name"] == "Card Shop")
        offers = [e for e in shop["items"] if e.get("card_offer")]
        self.assertEqual(len(offers), 6)
        self.assertTrue(all(e["rarity_prices"] == {"Common": 500, "Rare": 1500, "Legendary": 5000} for e in offers))
        pack = next(p for p in cards["packs"] if p["id"] == offers[0]["card_offer"])
        numbers = {c["id"]: c["number"] for c in cards["cards"]}
        self.assertEqual(sorted(numbers[e["id"]] for e in pack["cards"]), [n for n in range(1, 65) if n != 4])


if __name__ == "__main__":
    unittest.main()
