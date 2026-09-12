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


def normalize_evolutions(evolutions) -> list:
    """Normalise a whole ``evolve`` list (returns a new list)."""
    if not evolutions:
        return evolutions or []
    return [normalize_evolution(e) if isinstance(e, dict) else e
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
    partner_name = getattr(partner, "name", "") or ""
    if evo.get("jogress_prefix"):
        if not partner_name.startswith(name):
            return False
    elif partner_name != name:
        return False

    version = evo.get("jogress_version")
    if version is None:
        version = getattr(owner, "version", None)
    if version is not None and getattr(partner, "version", None) != version:
        return False

    stage = evo.get("jogress_stage")
    if stage is not None and getattr(partner, "stage", None) != stage:
        return False
    return True


def find_route(pet, partner):
    """The first jogress route on *pet* that *partner* satisfies, or None.

    Evolution order is load-bearing (first match wins), so this walks the list
    in order and never sorts it.
    """
    for evo in (getattr(pet, "evolve", None) or []):
        if is_jogress(evo) and matches_partner(evo, pet, partner):
            return evo
    return None


def is_dual(evo: dict) -> bool:
    return evo.get("jogress") == DUAL


def compatible(pet1, pet2) -> bool:
    """Whether these two can jogress, in EITHER direction.

    Checked both ways round because a pairing declared only on the partner's
    side is still a real pairing - testing just the first-selected pet made
    such a pair read as incompatible half the time, depending on tap order.
    """
    if not pet1 or not pet2 or pet1 is pet2:
        return False
    if getattr(pet1, "module", None) != getattr(pet2, "module", None):
        return False
    return find_route(pet1, pet2) is not None or find_route(pet2, pet1) is not None
