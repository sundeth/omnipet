"""
Module currencies and shops (shop.json).

A module may declare currencies -- the Digivice iC's Fight Money -- and shops
that sell its items and card packs for them. Balances live on the save, not on
a pet: ``game_globals.currency[module][currency_name]``, since the iC keeps its
Fight Money across generations. A balance never goes below zero, nor above the
currency's ``cap`` where it has one (the iC's 9,999).

Currency is earned from adventure wins (`battle_reward`) and from training
(`training_earnings`: the currency's ``training_gain`` for the best outcome
among the module's pets, once per training; a minigame of a device's own,
like the iC's, pays its own prize instead). A training shows what it earned
on its currency screen, after the result.

A shop is open when its ``unlock`` is empty or unlocked for its module, and,
when marked ``event_only``, while an event has opened it; an
entry in it is on sale when the entry's own ``unlock`` is empty or unlocked,
and, when it lists ``versions``, while the party holds a pet of the module on
one of them: the Digivice iC 10X's Item Shop sells a Dragon Head where the
20X's sells Sunglasses.
An entry sells an item (``item``, an item.json name) or a card pack
(``card_pack``, a cards.json pack id), which is opened when bought. Only the
modules of the current party's pets have their shops listed, as with the
Specials menu's passwords.
"""

import os
from dataclasses import dataclass

from core import game_globals, runtime_globals


def _module(name):
    """The loaded module called *name*, or None (a pet's module can be
    missing from this install)."""
    return (getattr(runtime_globals, "game_modules", None) or {}).get(name)


def _balances(module_name, create=False):
    store = getattr(game_globals, "currency", None)
    if not isinstance(store, dict):
        store = game_globals.currency = {}
    if create:
        return store.setdefault(module_name, {})
    return store.get(module_name, {})


def get_balance(module_name, currency_name) -> int:
    """The player's balance of *currency_name* on *module_name*."""
    try:
        return int(_balances(module_name).get(currency_name, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _currency(module_name, currency_name):
    module = _module(module_name)
    return next((c for c in getattr(module, "currencies", None) or []
                 if c.get("name") == currency_name), {})


def currency_cap(module_name, currency_name) -> int:
    """The most of the currency the player can hold; 0 for no limit."""
    try:
        return max(0, int(_currency(module_name, currency_name).get("cap", 0) or 0))
    except (TypeError, ValueError):
        return 0


def add_currency(module_name, currency_name, amount) -> int:
    """Add a signed *amount*, never dropping below zero nor rising past the
    currency's cap (a balance already over a newly set cap is not cut).
    Returns the change actually made."""
    if not module_name or not currency_name:
        return 0
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        return 0
    old = get_balance(module_name, currency_name)
    new = max(0, old + amount)
    cap = currency_cap(module_name, currency_name)
    if cap:
        new = min(new, max(cap, old))
    _balances(module_name, create=True)[currency_name] = new
    return new - old


def spend(module_name, currency_name, amount) -> bool:
    """Take *amount* if the balance covers it; refuse otherwise."""
    amount = int(amount or 0)
    if amount < 0 or get_balance(module_name, currency_name) < amount:
        return False
    add_currency(module_name, currency_name, -amount)
    return True


def currency_unit(module_name, currency_name) -> str:
    """The unit shown after an amount ("P" for Fight Money), or ""."""
    return str(_currency(module_name, currency_name).get("unit", "") or "")


def format_amount(module_name, currency_name, amount) -> str:
    unit = currency_unit(module_name, currency_name)
    return f"{int(amount)}{unit}" if unit else f"{int(amount)} {currency_name}"


def _is_open(module_name, unlock) -> bool:
    if not unlock:
        return True
    from utils.utils_unlocks import is_unlocked
    return is_unlocked(module_name, None, unlock)


def available_shops(module) -> list:
    """*module*'s open shops, in shop.json's order. A shop marked
    ``event_only`` is open only while an event has given access to it
    (utils.event_utils.grant_shop_access): the Digivice iC's DigiShops
    appear after a connection."""
    if module is None:
        return []
    from utils.event_utils import shop_access_open
    return [shop for shop in getattr(module, "shops", None) or []
            if _is_open(module.name, shop.get("unlock", ""))
            and (not shop.get("event_only") or shop_access_open(module.name, shop.get("name", "")))]


@dataclass
class Offer:
    """One thing a shop sells: an item or a card pack, at a price."""
    kind: str                   # "item" or "card_pack"
    name: str
    description: str
    price: int
    item: object = None         # the GameItem
    pack: dict = None           # the cards.json pack


def party_versions(module_name) -> set:
    """The versions of the party's pets of *module_name*."""
    return {getattr(pet, "version", None) for pet in game_globals.pet_list
            if getattr(pet, "module", None) == module_name}


def _for_party(entry, versions) -> bool:
    """An entry listing ``versions`` is for a party holding one of them; with
    no pet of the module in the party, every entry shows."""
    wanted = entry.get("versions") or []
    return not wanted or not versions or any(v in versions for v in wanted)


def shop_stock(module, shop) -> list:
    """The `Offer`s *shop* has on sale now, in its order. An entry naming an
    item or a pack the module does not have is skipped; one naming both
    sells the pack."""
    by_name = {item.name: item for item in getattr(module, "items", None) or []}
    versions = party_versions(module.name)
    stock = []
    for entry in shop.get("items") or []:
        if not _is_open(module.name, entry.get("unlock", "")) or not _for_party(entry, versions):
            continue
        price = max(0, int(entry.get("price", 0) or 0))
        if entry.get("card_pack"):
            from utils.card_utils import find_pack
            pack = find_pack(module.name, entry["card_pack"])
            if pack is None:
                continue
            count = int(pack.get("cards_per_pack", 1) or 1)
            plural = "s" if count != 1 else ""
            stock.append(Offer("card_pack", pack.get("name", "Card Pack"),
                               f"Card pack: {count} card{plural}.", price, pack=pack))
            continue
        item = by_name.get(entry.get("item"))
        if item is not None:
            stock.append(Offer("item", item.name, item.description or "", price, item=item))
    return stock


def party_shops() -> list:
    """``[(module, shop), ...]`` for every open shop of a party pet's module."""
    seen, shops = set(), []
    for pet in game_globals.pet_list:
        name = getattr(pet, "module", None)
        if name in seen:
            continue
        seen.add(name)
        module = _module(name)
        shops.extend((module, shop) for shop in available_shops(module))
    return shops


def any_party_shop() -> bool:
    return bool(party_shops())


def _round_versions(enemies, area, round_):
    return {int(e.get("version", -1)) for e in enemies
            if int(e.get("area", -1)) == int(area) and int(e.get("round", -1)) == int(round_)
            and not e.get("special_encounter")}


def entry_cost(module, area, pets=None):
    """``(currency, cost)`` for entering *area*, or ``("", 0)``.

    The fee sits on the area's round 1 enemies (``currency_cost``). Which
    of them a battle meets depends on the pets' versions -- a pet whose
    version has no enemy there meets a random one of the area's -- so the
    fee is the highest among the enemies the party can meet.
    """
    if module is None:
        return "", 0
    enemies = module._parse_battle_json(os.path.join(module.folder_path, "battle.json"))
    in_round = _round_versions(enemies, area, 1)
    met = set()
    for pet in pets or []:
        version = getattr(pet, "version", None)
        met |= {version} if version in in_round else in_round
    if not pets:
        met = in_round
    currency, cost = "", 0
    for enemy in enemies:
        if (int(enemy.get("area", -1)) != int(area) or int(enemy.get("round", -1)) != 1
                or enemy.get("special_encounter") or int(enemy.get("version", -1)) not in met):
            continue
        fee = int(enemy.get("currency_cost", 0) or 0)
        if fee > cost and enemy.get("currency"):
            currency, cost = enemy["currency"], fee
    return currency, cost


def pay_entry(module, area, pets=None) -> bool:
    """Charge *area*'s entry fee; False, charging nothing, when the balance
    is short. An area with no fee is always entered."""
    currency, cost = entry_cost(module, area, pets)
    if cost <= 0:
        return True
    return spend(module.name, currency, cost)


def battle_reward(enemies):
    """``(currency, amount)`` a won battle pays: the biggest
    ``currency_reward`` among *enemies*, once, however many there were."""
    currency, amount = "", 0
    for enemy in enemies or []:
        reward = int(getattr(enemy, "currency_reward", 0) or 0)
        if reward > amount and getattr(enemy, "currency", ""):
            currency, amount = enemy.currency, reward
    return currency, amount


def buy(module, shop, offer):
    """Pay *offer*'s price in *shop*'s currency: an item goes to the
    inventory, a card pack is opened into the collection. Returns None when
    the balance is short or the player holds all of the item they can
    (nothing is paid), else the cards a pack gave (``[(card, shiny), ...]``,
    empty for an item)."""
    from utils.inventory_utils import is_full
    if offer.kind == "item" and is_full(offer.item.id):
        return None
    if not spend(module.name, shop.get("currency", ""), offer.price):
        return None
    if offer.kind == "card_pack":
        from utils.card_utils import open_pack
        return open_pack(module.name, offer.pack.get("id"))
    from utils.inventory_utils import add_to_inventory
    add_to_inventory(offer.item.id, 1)
    return []


def training_earnings(results):
    """What one training earns in each module's currencies, unpaid.

    *results* is ``[(pet, won, grade), ...]``: grade 0-3 for Bad, Good,
    Great and Excellent, Bad when the pet failed. A module is paid once
    however many of its pets trained, at the best outcome among them, the
    currency's ``training_gain`` for it. Returns ``[(module name, currency
    name, amount), ...]``.
    """
    best = {}
    for pet, won, grade in results:
        name = getattr(pet, "module", None)
        level = max(0, min(3, int(grade or 0))) if won else 0
        best[name] = max(best.get(name, 0), level)
    earnings = []
    for name, level in best.items():
        for currency in getattr(_module(name), "currencies", None) or []:
            gains = list(currency.get("training_gain") or []) + [0, 0, 0, 0]
            earnings.append((name, currency.get("name"), gains[level]))
    return earnings


def pay_earnings(earnings):
    """Pay ``[(module name, currency name, amount), ...]``. Returns what was
    actually added (a cap can cut it), leaving out what added nothing."""
    paid = []
    for module_name, currency_name, amount in earnings:
        got = add_currency(module_name, currency_name, amount)
        if got > 0:
            paid.append((module_name, currency_name, got))
    return paid


def pay_training(results):
    """Pay each module's currencies for one training (`training_earnings`).
    Returns the lines to show ("+20P")."""
    return ["+" + format_amount(name, currency, got)
            for name, currency, got in pay_earnings(training_earnings(results))]
