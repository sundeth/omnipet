"""
What an item does to the pets that take it.

An item has one main effect (`effect`, `status`, `amount`). The main effect
decides who can take the item, and the inventory scene runs it. Two things
then follow it, for the pets that took the item:

* its own weight change, `weight_gain`, whatever the effect. It is signed and
  floored at each pet's minimum weight (`GamePet.add_weight`), so -99 takes a
  pet to its minimum; None keeps the module's meat/protein rule, which
  `GamePet.set_eating` applies for food.
* its `extra_effects`: rows shaped like the main effect.

A `status_change` row is a plain change of the stat, not a meal. Its amount is
the change itself (not scaled by the module's meal gains), it puts on no
weight, and it stops at the stat's own limits: so +99 fills a stat and -99
empties it. An extra row that puts Hunger on makes a full pet refuse the
whole item (`fits`: anything that recovers Hunger is refused when full); run
on a full pet otherwise, a positive hunger row counts as overfeeding where the
module has it (`care_overfeed_timer` above 0). A `currency` row pays once per
use, however many pets took it.

Effects: status_change, status_boost, dna, currency, devolve, and the
Digivice iC's (`PET_EFFECTS`, run by `apply_pet_effect`):

* cure           heals one ailment: `status` "sick" the sickness poop and
                 broken sleep bring (Omnipet's Dots), "injury" the one a
                 battle leaves (the skull), "" either; the iC's Cold Medicine
                 and Injury Medicine;
* bedding        Digi Bedding: the pet sleeps `amount` minutes, its sickness
                 and injury heal, and one care mistake is forgiven;
* accessory      worn, or taken off when worn already (one at a time):
                 `status` "head" (a hat), "face" (glasses) or "aura" (drawn
                 around the pet). See `utils.accessory_utils`;
* closeup        the C'mon Switch: the Digimon comes up close to the screen;
* evolve         the pet becomes `target` (a monster of its own version);
* random_evolve  R-Shinka: the pet becomes one of the next-stage forms its
                 own routes lead to, at random;
* encounter      a ticket: starts the battle.json special encounter named
                 `target`.
* multiplier     a Vital Bracelet BE item: for `boost_time` minutes the
                 pet's gains of `status` (comma-separated: "pp" the trophies
                 training earns, "vp" the Vital Values a card battle wins;
                 the BE's "bp", "ap" and "hp" have no trained stat here) are
                 multiplied by `amount`. A pet runs one such item at a time,
                 a new one replacing it (utils.card_battle). An item none of
                 whose targets exists here is refused, not used up.

`training_limit` (the BE's Limit Boosts: `amount` minutes onto the Limit
timer) is catalogued but does nothing yet: Omnipet's VBE has no Limit timer.

And `bundle`: the item is a set of others, its `extra_effects` rows of
effect `item` (each `item` x `amount`), handed over once per use (the iC
20X's Weapon MAX, every weapon the Weapon Shop sells).

An item's `min_stage` keeps it from pets below that stage and its
`max_stage` (0: no limit) from pets above it; anything that recovers Hunger
is refused by a full pet -- a food by `GamePet.set_eating`, an item whose
extra effect puts Hunger on (the iC's Level Reverse) by `fits`; a `reusable`
one is not used up (the inventory's business).
"""

import random
from datetime import datetime, timedelta

from core import game_globals, pet_stats, runtime_globals
from utils import ailments
from utils.module_utils import get_module

#: Effects an item can name that do nothing yet: the inventory refuses them
#: rather than consuming the item.
NOT_IMPLEMENTED_EFFECTS = ("training_limit",)

#: Effects that act on the pets themselves rather than feeding them.
PET_EFFECTS = ("cure", "bedding", "accessory", "closeup", "evolve", "random_evolve", "encounter",
               "multiplier")

#: The `multiplier` targets something here multiplies.
MULTIPLIER_TARGETS = ("pp", "vp")

#: Accessory slots (an `accessory` item's `status`).
ACCESSORY_SLOTS = ("head", "face", "aura")

#: status -> (index in `GamePet.bonus_stats`, the module's cap attribute).
_BONUS_STATS = {
    "hp": (0, "hp_max_item_boost"),
    "attack": (1, "atk_max_item_boost"),
    "power": (2, "power_max_item_boost"),
}


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _log(text):
    console = getattr(runtime_globals, "game_console", None)
    if console is not None:
        console.log(text)


def apply_status(pet, status, amount) -> bool:
    """Change one of *pet*'s stats by *amount* within its limits. Returns
    whether anything changed."""
    amount = _int(amount)
    module = get_module(pet.module)

    if status in _BONUS_STATS:
        index, cap_attr = _BONUS_STATS[status]
        cap = _int(getattr(module, cap_attr, 0))
        old = pet.bonus_stats[index]
        if amount > 0 and old >= cap:
            return False
        pet.bonus_stats[index] = max(0, min(cap, old + amount))
        return pet.bonus_stats[index] != old

    if status == "hunger":
        if amount > 0 and pet.hunger >= pet.stomach:
            # Full: overfeeding where the module has it, else nothing.
            if _int(getattr(module, "overfeed_timer", 0)) > 0 and not pet.overfeed_timer:
                pet.overfeed_timer = module.overfeed_timer
                pet.overfeed += 1
            return False
        old = pet.hunger
        pet.hunger = max(0, min(pet.stomach, old + amount))
        _note_refilled(pet)
        return pet.hunger != old

    if status == "strength":
        old = pet.strength
        cap = pet_stats.strength_cap(getattr(module, "strength_max", 0), pet.stomach)
        pet.strength = max(0, min(max(cap, old), old + amount))
        _note_refilled(pet)
        return pet.strength != old

    if status == "dp":
        old = pet.dp
        pet.dp = max(0, min(max(pet.energy, old), old + amount))
        return pet.dp != old

    if status == "timer":
        # Minutes forward on the pet's real-time clock.
        if not amount:
            return False
        pet._rt_origin -= amount * 60
        return True

    if status == "vital_values":
        old = pet.vital_values
        pet.vital_values = max(0, min(9999, old + amount))
        return pet.vital_values != old

    if status == "reliability":
        return pet.add_reliability(amount) != 0

    if status == "injury_rate":
        return pet.add_injury_rate(amount) != 0

    _log(f"[ItemEffects] status '{status}' is not a stat an item can change")
    return False


def _note_refilled(pet):
    """A full meter clears its starvation counter (GamePet.note_meters_refilled)."""
    note = getattr(pet, "note_meters_refilled", None)
    if callable(note):
        note()


def add_battle_boost(item, status, amount, boost_time):
    """Store a timed battle effect, as a `status_boost` item does: one per
    status, its time adding up, with the item's id so the effect can find
    the item (`inventory_utils.active_boost_item`)."""
    effect = game_globals.battle_effects.get(
        status, {"amount": 0, "boost_time": 0, "module": item.module})
    effect["amount"] = amount
    effect["boost_time"] += boost_time
    effect["module"] = item.module
    effect["item_id"] = item.id
    game_globals.battle_effects[status] = effect


def pay_currency(item, currency_name, amount):
    """Pay *amount* of the item's module's *currency_name*. Returns a line
    for the player, or "" when nothing was paid."""
    from utils.currency_utils import add_currency, format_amount
    paid = add_currency(item.module, currency_name, amount)
    if not paid:
        _log(f"[ItemEffects] {item.name}: no {currency_name or 'currency'} paid")
        return ""
    return f"+{format_amount(item.module, currency_name, paid)}" if paid > 0 else \
        format_amount(item.module, currency_name, paid)


def apply_weight(item, pets):
    """The item's own weight change (`weight_gain`), to each pet that took
    it. None and 0 change nothing here."""
    change = getattr(item, "weight_gain", None)
    if not change:
        return
    for pet in pets:
        pet.add_weight(change)


def give_item(item, name, amount) -> str:
    """An `item` row: *amount* of the item's module's item *name*, once per
    use. Returns a line for the player, or ""."""
    from utils.inventory_utils import add_to_inventory, get_item_by_name
    given = get_item_by_name(item.module, name)
    if given is None:
        _log(f"[ItemEffects] {item.name}: no item {name}")
        return ""
    added = add_to_inventory(given.id, max(1, amount))
    return f"{given.name} +{added}" if added else ""


def apply_extra_effects(item, pets):
    """Run the item's `extra_effects` for the *pets* that took it. Returns
    lines for the player (currency paid)."""
    notes = []
    if not pets:
        return notes
    for row in getattr(item, "extra_effects", None) or []:
        effect = row.get("effect", "")
        status = row.get("status", "")
        amount = _int(row.get("amount"))
        if effect == "status_change":
            for pet in pets:
                apply_status(pet, status, amount)
        elif effect == "status_boost":
            add_battle_boost(item, status, amount, _int(row.get("boost_time")))
        elif effect == "dna":
            family = row.get("digisoul") or getattr(item, "digisoul", "")
            for pet in pets:
                pet.add_dna(family, amount)
        elif effect == "currency":
            note = pay_currency(item, row.get("currency") or getattr(item, "currency", ""), amount)
            if note:
                notes.append(note)
        elif effect == "devolve":
            for pet in pets:
                pet.devolve()
        elif effect == "item":
            note = give_item(item, row.get("item", ""), amount)
            if note:
                notes.append(note)
        else:
            _log(f"[ItemEffects] {item.name}: extra effect '{effect}' is not implemented")
    return notes


def _cure_kind(status):
    """The ailment a `cure` of *status* heals: "sick" a sickness, "injury"
    an injury, anything else either (utils.ailments)."""
    return status if status in ailments.KINDS else None


def has_ailment(pet, status) -> bool:
    """Whether *pet* has the ailment a `cure` of *status* heals."""
    kind = _cure_kind(status)
    return ailments.doses(pet, kind) > 0 if kind else ailments.ailing(pet)


def cure(pet, status) -> bool:
    """Heal *pet*'s ailment of *status* outright. Returns whether it had one."""
    if not has_ailment(pet, status):
        return False
    return ailments.cure(pet, _cure_kind(status))


def bedding(pet, minutes) -> bool:
    """Digi Bedding: *pet* sleeps *minutes* (`GamePet.nap_until`), its
    sickness and injury heal and one care mistake is taken off. The iC
    Master Book: "sleeps 10 minutes; cures sickness and injury, and the
    penalties go down by one"."""
    cure(pet, "")
    pet.mistakes = max(0, int(getattr(pet, "mistakes", 0) or 0) - 1)
    pet.set_state("nap")
    pet.nap_until = datetime.now() + timedelta(minutes=max(1, _int(minutes, 10)))
    return True


def toggle_accessory(pet, item) -> bool:
    """Put *item* on *pet*, or take it off when the pet wears it already.
    A pet wears one accessory at a time, as the iC's Digimon does."""
    pet.accessory = None if getattr(pet, "accessory", None) == item.id else item.id
    if hasattr(pet, "dirty"):
        pet.dirty = True
    return True


def stage_fits(item, pet) -> bool:
    """Whether *pet*'s stage is within *item*'s `min_stage` and
    `max_stage` (either 0: no limit that way)."""
    stage = int(getattr(pet, "stage", 0) or 0)
    low = int(getattr(item, "min_stage", 0) or 0)
    high = int(getattr(item, "max_stage", 0) or 0)
    return not (low and stage < low) and not (high and stage > high)


def evolve_target(pet, item):
    """The monster record an `evolve` *item* turns *pet* into, or None: the
    item's `target` on the pet's own version, in the pet's module, for a pet
    within the item's stages (`stage_fits`) that is not that form already."""
    name = getattr(item, "target", "") or ""
    if not name or pet.name == name or not stage_fits(item, pet):
        return None
    module = get_module(pet.module)
    return module.get_monster(name, pet.version) if module else None


def random_evolution_targets(pet) -> list:
    """``[(name, version), ...]``: the next-stage forms *pet*'s own routes
    lead to, each once, leaving out jogress and item routes (those need a
    partner or an item, not chance)."""
    module = get_module(pet.module)
    if module is None or int(pet.stage or 0) < 1:
        return []
    next_stage = {(m.get("name"), m.get("version")) for m in module.get_monsters_by_stage(int(pet.stage) + 1)}
    targets = []
    for route in getattr(pet, "evolve", None) or []:
        if not isinstance(route, dict) or route.get("jogress") or route.get("item"):
            continue
        target = (route.get("to"), route.get("version", pet.version))
        if target in next_stage and target not in targets:
            targets.append(target)
    return targets


def encounter_enemy(item):
    """The battle.json special encounter an `encounter` *item* starts (its
    enemy entry), or None when the module has none of that name."""
    import os
    module = get_module(item.module)
    name = getattr(item, "target", "") or ""
    if module is None or not name:
        return None
    enemies = module._parse_battle_json(os.path.join(module.folder_path, "battle.json"))
    return next((e for e in enemies if e.get("special_encounter") and e.get("name") == name), None)


def start_encounter(item) -> bool:
    """Start the battle an `encounter` item names; False, starting nothing,
    when the module has no such encounter or no pet can battle."""
    enemy = encounter_enemy(item)
    if enemy is None:
        _log(f"[ItemEffects] {item.name}: no special encounter '{getattr(item, 'target', '')}'")
        return False
    if not any(pet.can_battle() for pet in game_globals.pet_list):
        _log(f"[ItemEffects] {item.name}: no pet can battle")
        return False
    from utils.scene_utils import change_scene
    runtime_globals.special_encounter = [item.module, int(enemy.get("area", 1) or 1),
                                         int(enemy.get("round", 1) or 1), enemy["name"]]
    change_scene("battle")
    return True


def multiplier_targets(item) -> list:
    """A `multiplier` item's targets (its `status`, comma-separated)."""
    return [t.strip().lower() for t in str(getattr(item, "status", "") or "").split(",") if t.strip()]


def is_full(pet) -> bool:
    """Whether *pet*'s Hunger is at its stomach (a pet with none is never full)."""
    stomach = _int(getattr(pet, "stomach", 0))
    return stomach > 0 and _int(getattr(pet, "hunger", 0)) >= stomach


def feeds_by_extra(item) -> bool:
    """Whether *item* puts Hunger on through an extra effect (the iC's Level
    Reverse, Reliability Max). A food's own Hunger is `GamePet.set_eating`'s,
    which already refuses a full pet and counts its overfeeding."""
    if getattr(item, "effect", "") in ("", "status_change") and getattr(item, "status", "") == "hunger":
        return False
    return any(row.get("effect") == "status_change" and row.get("status") == "hunger"
               and _int(row.get("amount")) > 0 for row in getattr(item, "extra_effects", None) or [])


def fits(item, pet) -> bool:
    """Whether *item*'s own rules let *pet* take it: its stages, a full pet
    refusing anything that recovers Hunger, for the evolving effects a form
    to become, and for a multiplier a target that exists here."""
    if not stage_fits(item, pet):
        return False
    if feeds_by_extra(item) and is_full(pet):
        return False
    effect = getattr(item, "effect", "")
    if effect == "evolve":
        return evolve_target(pet, item) is not None
    if effect == "random_evolve":
        return bool(random_evolution_targets(pet))
    if effect == "multiplier":
        targets = [t for t in multiplier_targets(item) if t in MULTIPLIER_TARGETS]
        if targets == ["vp"]:
            return bool(getattr(pet, "tracks_vital_values", lambda: False)())
        return bool(targets)
    return True


def apply_pet_effect(item, pet) -> bool:
    """Run a `PET_EFFECTS` main effect on one pet (closeup and encounter are
    the inventory's: they are not per pet). Returns whether it took."""
    effect = item.effect
    if effect == "cure":
        return cure(pet, item.status)
    if effect == "bedding":
        return bedding(pet, item.amount)
    if effect == "accessory":
        return toggle_accessory(pet, item)
    if effect == "evolve":
        target = evolve_target(pet, item)
        return bool(target) and pet.evolve_to(target["name"], target.get("version", pet.version))
    if effect == "random_evolve":
        targets = random_evolution_targets(pet)
        if not targets:
            return False
        name, version = random.choice(targets)
        return pet.evolve_to(name, version)
    if effect == "multiplier":
        if not fits(item, pet):
            return False
        from utils.card_battle import set_boost
        set_boost(pet, item.name, multiplier_targets(item), _int(item.amount, 1),
                  _int(getattr(item, "boost_time", 0)))
        return True
    _log(f"[ItemEffects] {item.name}: '{effect}' is not a per-pet effect")
    return False


def finish_use(item, pets):
    """Everything that follows a main effect: the weight change, then the
    extra effects. Returns lines for the player."""
    if not pets:
        return []
    apply_weight(item, pets)
    return apply_extra_effects(item, pets)
