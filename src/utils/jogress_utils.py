"""
Jogress routes - the shared shape, and the migration from the old one.
=====================================================================

A jogress evolution has two independent parts, which the original data format
ran together:

  * HOW the partner is matched - by attribute, by exact name, or by a name
    prefix;
  * WHAT comes out - one Digimon (the partner is absorbed) or two (each pet
    evolves along its own route).

The old format implied the second from the first: ``"jogress": "PenC"`` meant
attribute-matched AND dual, a partner name meant name-matched AND fusion, and
there was no way at all to say "name-matched, two out" - which is exactly what
the Pendulum Color Toho Braves / Saiyu Warriors need (Tengumon + SeitenGokuumon
leaves Enmamon *and* Shakamon).

The current shape separates them:

    to                 target of this route (unchanged, as for any evolution)
    jogress            "" | "Single" | "Dual"   <- the type; non-empty marks
                                                   the route as a jogress
    jogress_name       partner's name, or the prefix when jogress_prefix
    jogress_prefix     match jogress_name as a prefix instead of exactly
    jogress_stage      stage the partner must be
    jogress_version    version the partner must be
    jogress_attribute  attribute the partner must have

Matching mode follows from which field is set: ``jogress_attribute`` means
attribute matching, otherwise ``jogress_name`` (as a prefix when the flag is
set). The jogress fields are namespaced because ``stage`` / ``version`` /
``attribute`` on a jogress route described the PARTNER while the same keys on
an ordinary route describe the pet itself - one key, two meanings.

Old modules are migrated on load rather than rewritten on disk, the same way
``game_module.LEGACY_RULESET_RULES`` handles the old ``ruleset`` field. Opening
and saving a module in the editor writes the new shape out.
"""

#: Outcome types.
SINGLE = "Single"   # 2 in, 1 out - the partner is absorbed
DUAL = "Dual"       # 2 in, 2 out - each pet evolves along its own route

#: What the attribute-matched jogress used to be called in the ``jogress``
#: field. Named after the Pendulum Color, but several other devices use the
#: same rule, which is part of why it stopped being a good name for it.
LEGACY_ATTRIBUTE_MARKER = "PenC"

_JOGRESS_KEYS = ("jogress_name", "jogress_prefix", "jogress_stage",
                 "jogress_version", "jogress_attribute")


def is_attribute_pair(evo) -> bool:
    """Whether this route names a partner by stage and attribute alone.

    The oldest shape of an attribute jogress, written without any ``jogress``
    marker at all -- PENZ has 448 of them and no other module has any. It is
    unambiguous: across every module, ``stage`` and ``attribute`` together
    appear on jogress routes and nowhere else, and they cannot be describing
    the pet itself, whose own stage and attribute are fixed by its record.
    """
    return "jogress" not in evo and "stage" in evo and "attribute" in evo


def is_jogress(evo) -> bool:
    """Whether this evolution route is a jogress at all."""
    return bool(evo.get("jogress")) or is_attribute_pair(evo)


def normalize_evolution(evo: dict) -> dict:
    """Return *evo* in the current shape, migrating the old one if needed.

    Returns the same object when nothing had to change, so this is cheap to
    call on every load. Non-jogress routes are returned untouched.
    """
    raw = evo.get("jogress")
    if not raw:
        if not is_attribute_pair(evo):
            return evo
        # Marker-less attribute jogress: the same thing "PenC" spelled out.
        raw = LEGACY_ATTRIBUTE_MARKER
    if raw in (SINGLE, DUAL):
        return evo  # already migrated

    out = dict(evo)
    if raw == LEGACY_ATTRIBUTE_MARKER:
        # Attribute-matched, and always produced two Digimon.
        out["jogress"] = DUAL
        out["jogress_attribute"] = evo.get("attribute")
        out["jogress_stage"] = evo.get("stage")
        out.pop("attribute", None)
        out.pop("stage", None)
    else:
        # A partner name (or a prefix): always a fusion in the old format.
        out["jogress"] = SINGLE
        out["jogress_name"] = raw
        if evo.get("jogress_prefix"):
            # A prefix route carried no partner stage/version.
            out["jogress_prefix"] = True
        else:
            out["jogress_version"] = evo.get("version")
            out.pop("version", None)
            if "stage" in evo:
                out["jogress_stage"] = evo.get("stage")
                out.pop("stage", None)
    # Drop keys that ended up empty so the data stays tidy.
    for key in _JOGRESS_KEYS:
        if key in out and out[key] is None:
            del out[key]
    return out


def normalize_item_route(evo: dict) -> dict:
    """The old use-count shape (``item_use`` + ``item_use_amount``: the
    Twin's five Bombs for Digitamamon) as the one item route, ``item`` +
    ``item_amount`` (owner, 2026-10-15: a single item field and an amount,
    1 by default). Returns *evo* itself when there is nothing to migrate."""
    if "item_use" not in evo:
        return evo
    out = dict(evo)
    name = out.pop("item_use")
    amount = out.pop("item_use_amount", None)
    out.setdefault("item", name)
    try:
        if amount is not None and int(amount) > 1:
            out.setdefault("item_amount", int(amount))
    except (TypeError, ValueError):
        pass
    return out


def normalize_evolutions(evolutions) -> list:
    """Normalise a whole ``evolve`` list (returns a new list): the old
    jogress shapes and the old item-use shape."""
    if not evolutions:
        return evolutions or []
    return [normalize_item_route(normalize_evolution(e)) if isinstance(e, dict) else e
            for e in evolutions]


# =====================================================================
# Matching
# =====================================================================

def matches_partner(evo: dict, owner, partner) -> bool:
    """Whether *partner* satisfies this jogress route belonging to *owner*.

    Mirrors the three matching modes. ``owner`` supplies the default version
    for a named route, which is how the old format behaved.
    """
    if not is_jogress(evo):
        return False
    if not can_pair(owner, partner):
        return False

    attribute = evo.get("jogress_attribute")
    if attribute:
        # "" on a pet means Free.
        pet_attr = getattr(partner, "attribute", "") or ""
        if not (pet_attr == attribute or (pet_attr == "" and attribute == "Free")):
            return False
        stage = evo.get("jogress_stage")
        if stage is not None and getattr(partner, "stage", None) != stage:
            return False
        return True

    name = evo.get("jogress_name")
    if not name:
        return False
    # A pet of another module on the same protocol (can_pair) answers a
    # named route by name and version too: DMRV's WarGreymon (Anime) names
    # the DM20's MetalGarurumon (Anime) v9 ("the connection data is entirely
    # identical to the DM20", humulos).
    partner_name = getattr(partner, "name", "") or ""
    if evo.get("jogress_prefix"):
        if not partner_name.startswith(name):
            return False
    elif partner_name != name:
        return False

    # A named route without a version means the owner's; a prefix route
    # without one takes the name in any version (D-3's "Ancient" Warriors
    # for Susanomon, PENZ's "Jogress with Metal Garurumon"), as its migration
    # always meant: it was held to the owner's version all the same.
    version = evo.get("jogress_version")
    if version is None and not evo.get("jogress_prefix"):
        version = getattr(owner, "version", None)
    if version is not None and getattr(partner, "version", None) != version:
        return False

    stage = evo.get("jogress_stage")
    if stage is not None and getattr(partner, "stage", None) != stage:
        return False
    return True


def owner_requirements_met(evo: dict, owner) -> bool:
    """Whether *owner* meets the route's requirements on itself, apart from
    the partner: its level (Pendulum Z: Level 1-5 gives one result, Level 6
    another, with the same partner), the area it has reached (VBE's Examon)
    or a module unlock the player holds (Pendulum Color: a partner of the
    same attribute gives one Digimon once the version's Slot 6/7 is unlocked
    and another before). They were ignored, so the first route for a partner
    always won.
    """
    level = evo.get("level")
    if level and not (level[0] <= (getattr(owner, "level", 0) or 0) <= level[1]):
        return False
    area = evo.get("area")
    if area is not None and (getattr(owner, "area", 0) or 0) < area:
        return False
    if evo.get("unlock"):
        from utils.evolution_rules import unlock_held
        if not unlock_held(owner, evo["unlock"]):
            return False
    return True


def find_route(pet, partner):
    """The first jogress route on *pet* that *partner* satisfies, or None.

    Evolution order is load-bearing (first match wins), so this walks the list
    in order and never sorts it.
    """
    for evo in (getattr(pet, "evolve", None) or []):
        if (is_jogress(evo) and owner_requirements_met(evo, pet)
                and matches_partner(evo, pet, partner)):
            return evo
    return None


def is_dual(evo: dict) -> bool:
    return evo.get("jogress") == DUAL


def protocol_of(module_name) -> str:
    """The module's `battle_protocol`, upper case; "" when it sets none."""
    from utils.module_utils import get_module
    value = str(getattr(get_module(module_name), "battle_protocol", "") or "").strip()
    return "" if value.lower() in ("", "none") else value.upper()


def can_pair(pet1, pet2) -> bool:
    """Whether these two pets may jogress at all: the same module, or two
    modules setting the same `battle_protocol` (PENGZ and the Pendulum Color
    connect on the PENC wire; the device's connection jogress)."""
    module1, module2 = getattr(pet1, "module", None), getattr(pet2, "module", None)
    if module1 == module2:
        return True
    protocol = protocol_of(module1)
    return bool(protocol) and protocol == protocol_of(module2)


def compatible(pet1, pet2) -> bool:
    """Whether these two can jogress, in EITHER direction.

    Checked both ways round because a pairing declared only on the partner's
    side is still a real pairing - testing just the first-selected pet made
    such a pair read as incompatible half the time, depending on tap order.
    """
    if not pet1 or not pet2 or pet1 is pet2:
        return False
    if not can_pair(pet1, pet2):
        return False
    return find_route(pet1, pet2) is not None or find_route(pet2, pet1) is not None
