#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Can every item and every card be obtained? (owner, 2026-10-20: "we could
also think about crawlers to get all cards and all items".)

For each release module, every way the game gives an item or a card, followed
to a fixpoint from what a player can do on their own:

    item   a shop entry (the shop open: its unlock earnable, or an event that
           opens it; its currency earnable; the entry's own unlock earnable),
           an enemy's prize (an adventure area, or a special encounter some
           event or ticket starts), a quest reward, an event's item (item
           packages, battle runs, card battles' item_sequence), a password,
           Connect Points, a card read for it, a bundle, crafting, an Event
           Communication outcome
    card   a pack (in a shop, as a prize, from an unlock) that holds it with
           odds above 0, or an unlock's own card

A source that needs another device is "connection" (a connection-triggered
event, a DigiShop it opens), one that needs a physical card "physical" (an
NFC read); the rest is "own play". Unlocks a player can earn come from the
module audit (`module_audit.Audit.reachability`), so an area, a shop or a
recruit behind an unearnable unlock is not counted.

    python -B tests/release/collection_crawl.py [--modules DW1 IC ...] [--out DIR] [--quiet]

Writes collection_crawl.json and collection_crawl.md to --out (default
tests/release/reports/collection/). Exit 1 when an item or card of a module
cannot be obtained at all.
"""
import argparse
import collections
import contextlib
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "support"))
import module_audit as audit_mod   # noqa: E402
from paths import REPORTS          # noqa: E402

OWN, CONNECTION, PHYSICAL = "own play", "connection", "physical"
LEFT_OUT = "left out"
#: Items nothing grants on purpose: listed, never a failure.
KNOWN = {
    "IC": dict(
        {f"DigiSoul ({t})": "DigiSoul comes only from cards (utilities/IC/IC_RESEARCH_AND_TODO.md, "
                            "2026-10-16); the item exists, nothing grants it"
         for t in ("Dragon", "Beast", "Insect", "Machine", "Water", "Bird", "Holy", "Dark")},
        **{n: "Omnipet's own default food and medicine do its work (IC research)"
           for n in ("Meat", "Cold Medicine", "Injury Medicine")}),
    **{m: {f"NEXT Clock {s}": "not sold (owner, 2026-10-17: no evolution-timer items in the Stat Shop); "
                              "nothing else grants it" for s in "SML"}
       for m in ("VB", "VBE", "VH")},
}
RANK = {OWN: 0, CONNECTION: 1, PHYSICAL: 2}
#: Event types (models/game_event.EventType).
ENEMY_BATTLE, ITEM_PACKAGE, FRIEND_BATTLE, POOL_BATTLE, BATTLE_RUN, SHOP_ACCESS, CARD_BATTLE = range(7)


def _better(a, b):
    """The more open of two ways (own play beats a connection beats a card)."""
    if a is None:
        return b
    if b is None:
        return a
    return a if RANK[a] <= RANK[b] else b


def _trigger_way(event):
    return CONNECTION if str(event.get("trigger") or "") == "connection" else OWN


class Crawl:
    def __init__(self, name):
        self.mod = audit_mod.Module(name)
        self.audit = audit_mod.Audit(self.mod)
        with contextlib.redirect_stdout(io.StringIO()):
            self.audit.reachability()
        self.got = self.audit.got_unlocks
        self.items = {}      # name -> (way, how)
        self.cards = {}      # id -> (way, how)

    # ------------------------------------------------------------------ helpers
    def _unlocked(self, name):
        return not name or name in self.got

    def _give_item(self, name, way, how):
        if not name or way is None:
            return False
        old = self.items.get(name)
        best = _better(old[0] if old else None, way)
        if old is None or best != old[0]:
            self.items[name] = (best, how)
            return True
        return False

    def _give_card(self, cid, way, how):
        if not cid or way is None:
            return False
        old = self.cards.get(cid)
        best = _better(old[0] if old else None, way)
        if old is None or best != old[0]:
            self.cards[cid] = (best, how)
            return True
        return False

    def _currency_way(self, currency):
        """How the currency is earned: training, a won battle, or an item."""
        if not currency:
            return OWN
        for c in self.mod.currencies:
            if c.get("name") == currency and any(int(g or 0) > 0 for g in c.get("training_gain") or []):
                return OWN
        for e in self.mod.enemies:
            if e.get("currency") == currency and int(e.get("currency_reward", 0) or 0) > 0:
                return self._enemy_way(e)
        way = None
        for it in self.mod.items:
            if it.get("effect") == "currency" and it.get("currency") == currency and it.get("name") in self.items:
                way = _better(way, self.items[it["name"]][0])
        return way

    def _enemy_way(self, e):
        """An adventure enemy is met by playing; a special encounter only
        when an event, a ticket or a run starts it."""
        if not e.get("special_encounter"):
            return OWN if e.get("area") in self.mod.adventure_areas else None
        way = None
        for ev in self.mod.events:
            if int(ev.get("type", -1) if ev.get("type") is not None else -1) in (ENEMY_BATTLE, BATTLE_RUN, POOL_BATTLE) \
                    and ev.get("area") == e.get("area"):
                way = _better(way, _trigger_way(ev))
            if ev.get("type") == FRIEND_BATTLE or ev.get("name") == e.get("name"):
                way = _better(way, _trigger_way(ev))
        for it in self.mod.items:
            if it.get("effect") == "encounter" and it.get("target") == e.get("name") and it.get("name") in self.items:
                way = _better(way, self.items[it["name"]][0])
        for c in self.mod.cards.get("effects", []) if isinstance(self.mod.cards, dict) else []:
            for fx in c.get("effects") or []:
                if fx.get("type") == "Encounter" and fx.get("area") == e.get("area"):
                    way = _better(way, self._effect_group_way(c))
        return way

    def _shop_way(self, shop):
        if shop.get("unlock") and shop["unlock"] not in self.got:
            return None
        if shop.get("event_only"):
            way = None
            for ev in self.mod.events:
                if ev.get("shop") == shop.get("name"):
                    way = _better(way, _trigger_way(ev))
            return way
        opened = OWN
        # A shop an event opens (the iC's DigiShops) without event_only is
        # still open on its own; nothing to add.
        return opened

    def _card_matches(self, card, group):
        def norm(v):
            return "L/R" if str(v).upper() == "LR" else str(v or "Any").upper()
        tool = "DigiSoul Charge" if card.get("type") == "Soul Plate" else "Plate Charge"
        return (group.get("value") == card.get("value")
                and (norm(group.get("lr")) in ("ANY",) or norm(group.get("lr")) == norm(card.get("lr")))
                and (group.get("tool") or "Any") in ("Any", tool))

    def _effect_group_way(self, group):
        way = None
        for c in self.mod.cards.get("cards", []) if isinstance(self.mod.cards, dict) else []:
            if c.get("id") in self.cards and self._card_matches(c, group):
                way = _better(way, self.cards[c["id"]][0])
        return way

    # ------------------------------------------------------------------ crawl
    def run(self):
        mod = self.mod
        cards = mod.cards if isinstance(mod.cards, dict) else {}
        packs = {p.get("id"): p for p in cards.get("packs") or []}
        for _ in range(12):
            changed = False
            # Shops: items and card packs.
            for s in mod.shops:
                shop_way = self._shop_way(s)
                pay = self._currency_way(s.get("currency"))
                if shop_way is None or pay is None:
                    continue
                way = _better(shop_way, pay) if RANK[shop_way] < RANK[pay] else shop_way
                way = shop_way if RANK[shop_way] >= RANK[pay] else pay
                for entry in s.get("items") or []:
                    if not self._unlocked(entry.get("unlock")):
                        continue
                    if entry.get("item"):
                        changed |= self._give_item(entry["item"], way, f"shop {s.get('name')}")
                    if entry.get("card_pack") in packs:
                        changed |= self._open_pack(packs[entry["card_pack"]], way, f"shop {s.get('name')}")
                    # A card offer sells one card of its pack, another each
                    # day: in time, every card of it.
                    if entry.get("card_offer") in packs:
                        changed |= self._open_pack(packs[entry["card_offer"]], way,
                                                   f"shop {s.get('name')} (daily card offer)")
            # Enemies' prizes.
            for e in mod.enemies:
                way = self._enemy_way(e)
                if way is None:
                    continue
                where = f"prize of {e.get('name')} (area {e.get('area')}, round {e.get('round')})"
                if e.get("prize"):
                    changed |= self._give_item(e["prize"], way, where)
                if e.get("prize_card_pack") in packs:
                    changed |= self._open_pack(packs[e["prize_card_pack"]], way, where)
            # Unlocks' packs and cards.
            for u in mod.unlocks:
                if u.get("name") not in self.got:
                    continue
                if u.get("card_pack") in packs:
                    changed |= self._open_pack(packs[u["card_pack"]], OWN, f"unlock {u.get('name')}")
                if u.get("card"):
                    changed |= self._give_card(u["card"], OWN, f"unlock {u.get('name')}")
            # Quests, events, passwords, Connect Points.
            for q in mod.quests:
                if q.get("reward_type") == 0 and q.get("reward_value"):
                    changed |= self._give_item(q["reward_value"], OWN, f"quest {q.get('name')}")
            for ev in mod.events:
                way = _trigger_way(ev)
                if ev.get("type") in (ITEM_PACKAGE, BATTLE_RUN) and ev.get("item"):
                    changed |= self._give_item(ev["item"], way, f"event {ev.get('name')}")
                for name in ev.get("item_sequence") or []:
                    changed |= self._give_item(name, way, f"card battle {ev.get('name')}")
            for c in mod.codes:
                if c.get("type") == "item" and c.get("item"):
                    changed |= self._give_item(c["item"], OWN, f"password {c.get('name')}")
            for r in (mod.connect_points or {}).get("rewards", []) if isinstance(mod.connect_points, dict) else []:
                if r.get("item"):
                    changed |= self._give_item(r["item"], CONNECTION, "Connect Points")
            for o in mod.meta.get("event_communication_outcomes") or []:
                if o.get("outcome") == "item" and o.get("item"):
                    changed |= self._give_item(o["item"], CONNECTION, "Event Communication")
            # Items from items: bundles and crafting.
            for it in mod.items:
                have = self.items.get(it.get("name"))
                if not have:
                    continue
                if it.get("effect") == "component" and it.get("component_item"):
                    changed |= self._give_item(it["component_item"], have[0], f"crafted from {it['name']}")
                for row in it.get("extra_effects") or []:
                    if row.get("effect") == "item" and row.get("item"):
                        changed |= self._give_item(row["item"], have[0], f"in {it['name']}")
            # Items from cards read (digital copies; NFC tags are physical).
            for group in cards.get("effects") or []:
                way = self._effect_group_way(group)
                for fx in group.get("effects") or []:
                    if (fx.get("type") or "Item") == "Item" and fx.get("item"):
                        changed |= self._give_item(fx["item"], way or PHYSICAL,
                                                   "a card read" if way else "an NFC read")
            if not changed:
                break
        return self

    def _open_pack(self, pack, way, how):
        changed = False
        for entry in pack.get("cards") or []:
            if int(entry.get("odds", 1) or 0) > 0:
                changed |= self._give_card(entry.get("id"), way, f"pack {pack.get('name')} ({how})")
        return changed

    # ------------------------------------------------------------------ report
    def result(self):
        mod = self.mod
        out = {"module": mod.name, "items": [], "cards": []}
        default_kept = {"effect": None}
        known = KNOWN.get(mod.name, {})
        for it in mod.items:
            name = it.get("name")
            way, how = self.items.get(name, (None, ""))
            if way is None and name in known:
                way, how = LEFT_OUT, known[name]
            out["items"].append({"name": name, "effect": it.get("effect") or "", "way": way or "none",
                                 "how": how})
        cards = mod.cards.get("cards", []) if isinstance(mod.cards, dict) else []
        for c in cards:
            way, how = self.cards.get(c.get("id"), (None, ""))
            out["cards"].append({"name": c.get("name"), "id": c.get("id"), "type": c.get("type"),
                                 "way": way or "none", "how": how})
        return out


def markdown(results):
    lines = ["# Items and cards: can each be obtained?", "",
             "Ways: own play; connection (another device); physical (an NFC card); none.", "",
             "| Module | Items | own play | connection | physical | left out | none | Cards | own play | connection | none |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        ti = collections.Counter(i["way"] for i in r["items"])
        tc = collections.Counter(c["way"] for c in r["cards"])
        lines.append(f"| {r['module']} | {len(r['items'])} | {ti[OWN]} | {ti[CONNECTION]} | {ti[PHYSICAL]} | "
                     f"{ti[LEFT_OUT]} | **{ti['none']}** | {len(r['cards'])} | {tc[OWN]} | {tc[CONNECTION]} | "
                     f"**{tc['none']}** |")
    for r in results:
        missing_i = [i for i in r["items"] if i["way"] == "none"]
        missing_c = [c for c in r["cards"] if c["way"] == "none"]
        other = [i for i in r["items"] if i["way"] in (CONNECTION, PHYSICAL)]
        left = [i for i in r["items"] if i["way"] == LEFT_OUT]
        if not (missing_i or missing_c or other or left):
            continue
        lines += ["", f"## {r['module']}"]
        if missing_i:
            lines.append("")
            lines.append("Items nobody can get: " + ", ".join(f"{i['name']} ({i['effect'] or 'food'})"
                                                              for i in missing_i))
        if missing_c:
            lines.append("")
            lines.append("Cards nobody can get: " + ", ".join(f"{c['name']} [{c['type']}]" for c in missing_c))
        if other:
            lines.append("")
            lines.append("Only with another device or a physical card: " +
                         ", ".join(f"{i['name']} ({i['way']}: {i['how']})" for i in other))
        if left:
            lines.append("")
            lines.append("Left out on purpose: " + "; ".join(f"{i['name']} ({i['how']})" for i in left))
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modules", nargs="*")
    ap.add_argument("--out", default=os.path.join(REPORTS, "collection"))
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    names = args.modules or audit_mod.RELEASE_MODULES
    results = [Crawl(n).run().result() for n in names]
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "collection_crawl.json"), "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=1, ensure_ascii=False)
    md = markdown(results)
    with open(os.path.join(args.out, "collection_crawl.md"), "w", encoding="utf-8") as fh:
        fh.write(md)
    if not args.quiet:
        print(md)
    bad = sum(1 for r in results for x in r["items"] + r["cards"] if x["way"] == "none")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
