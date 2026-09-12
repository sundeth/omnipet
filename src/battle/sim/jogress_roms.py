"""Jogress over the wire: one packet, describing your own pet.

A battle exchanges four packets and settles who won. A jogress exchanges one
each way, and on the Colour lines each side's packet describes **its own
pet**:

    MAGIC(32) | Operation(16) | Version(16) | Index(16) | Attribute(16)
              | Stage(16) | Check(16)

Attribute is the Colour line's own encoding (Free 0, Virus 1, Data 2,
Vaccine 3) and stage sits one below Omnipet's, so an Adult goes out as 3.
The check is the sum of every 16-bit word before it, as everywhere else on
this wire.

**The operation says which side is speaking, and the reply is one higher.**
Every stored code is an initiator's 0x14 (with 0x16 for a second packet),
which is right for what we send and wrong for what comes back: a Pendulum
Color answers **0x15**, the same initiator/responder pairing its battle uses
for 0x10/0x11 and 0x12/0x13. Accepting only 0x14 read the device's reply as
"not a jogress" and dropped it, so the toy evolved and our pet did not.

So the exchange is: find the ROM our pet fits -- one describing a pet of its
stage and attribute -- send that, and read the device's reply back into a
stage and attribute to match against our evolve routes, which name a partner
exactly that way (`jogress_stage`, `jogress_attribute`).

The ROMs come from `data/jogress/roms.json`, built by
`utilities/claude/build_jogress_roms.py` out of nacatech's DigiROM dump. We
send a real device's own code rather than building one from our pet, and
**if no ROM fits the pet, the jogress simply cannot be offered**. That is
deliberate: the packet carries a version and index that only mean something
on the device's roster, so a made-up one is a lie the toy would act on. It
also means a module with data a real device would never produce cannot push
that data onto the hardware -- the enforcement is the lookup failing.
`utilities/claude/check_jogress_roms.py` reports which modules are covered.

**Version is a map, not an offset.** A device numbers its releases in the
order they shipped and Omnipet does not: PENC's Virus Busters set is the
sixth release, so it goes out as wire version 5 while the module calls it 0.
Each line carries its own `version_map`, and the ROMs are stored with the
module version already resolved, so nothing here does version arithmetic.

**Two packet layouts are readable, and PENZ is the second.** Its codes are
three 2-byte packets over the DMX wire, and the first two are the DMX
battle's own packets 1 and 2 -- `Order(1) Level(4) Sick(1) Attack(2)
Version(4) EOL(4)`, then `Stage(3) Index(7) Attribute(2) EOL(4)`. That is
not a family resemblance: all eight generic codes decode to exactly the
stage and attribute their labels claim, and the named ones land on the
module's own records. Its versions are a flat wire = module + 5.

**Four lines are stored but unreadable.** PENX, Accel, Pendulum Cycle and
Pendulum Progress carry adapter operators (`^` XOR-with-reply, `@` check
digit) in packets whose layout nothing here has established, so a reply on
those wires cannot be parsed. Their codes are kept anyway; `supports()` is
about whether a whole exchange can be completed, not about whether codes
exist, and `roms()` reaches them regardless.
"""
import json
import os

_DATABASE = None

#: Where the packet's fields sit, in 16-bit words.
_MAGIC_HIGH, _MAGIC_LOW = 0, 1
_OPERATION, _VERSION, _INDEX, _ATTRIBUTE, _STAGE, _CHECK = 2, 3, 4, 5, 6, 7

#: The packet layouts we can read a reply from. A line stored under anything
#: else has codes we can send and no way to understand the answer.
_READABLE = ("colour", "dmx")

#: The DMX wire numbers stages from Baby II, so Omnipet's are two higher, and
#: writes attributes in Omnipet's own order. Both are the battle wire's, and
#: they are what `_parse_dmx_opponent` already reads off a real device.
_DMX_STAGE_OFFSET = 2
_DMX_ATTRIBUTES = {0: "Va", 1: "Da", 2: "Vi", 3: "Free"}
_EOL = 0xE


def _database():
    global _DATABASE
    if _DATABASE is None:
        path = os.path.join(os.path.dirname(__file__), "..", "..",
                            "data", "jogress", "roms.json")
        with open(os.path.abspath(path), encoding="utf-8") as handle:
            _DATABASE = json.load(handle)
    return _DATABASE


def _line(protocol):
    return _database().get("protocols", {}).get(protocol)


def supports(protocol):
    """Whether a jogress exchange can be completed over this battle format.

    Codes alone are not enough: the reply has to be readable, which today
    means the Colour or the DMX packet layout. A line with stored ROMs but no
    way to parse what comes back reports False rather than starting an
    exchange it cannot finish.
    """
    line = _line(protocol)
    return bool(line) and line.get("packets") in _READABLE


def rom_for(protocol, stage, attribute):
    """The DigiROM that presents a pet of *stage* and *attribute*, or None.

    This is what we send: the packet describes our own pet, so the lookup is
    on the pet's own stage and attribute, not on the partner it wants. None
    means no real device ever presents a pet like this one, and the jogress
    cannot be offered.

    Stage and attribute are Omnipet's -- 4 for an Adult, "Va" for Vaccine.
    """
    line = _line(protocol)
    if not line:
        return None
    for entry in line.get("presents", []):
        if entry["stage"] == stage and entry["attribute"] == attribute:
            return entry["rom"]
    return None


def available(protocol):
    """Every pet shape this protocol can present, for diagnostics."""
    line = _line(protocol)
    return list(line.get("presents", [])) if line else []


def roms(protocol):
    """Every stored code for a line, readable or not.

    Includes the lines Omnipet has no module for yet, which is the point of
    keeping them: PENX and Accel have no battle format here, and their codes
    are still on record.
    """
    line = _line(protocol)
    return list(line.get("named", [])) if line else []


def module_version(protocol, wire_version):
    """The module version a wire version names, per the line's own map."""
    line = _line(protocol) or {}
    return line.get("version_map", {}).get(str(wire_version), wire_version)


def _operations(data):
    """Which operation words are a jogress, sent or answered.

    A device ANSWERS a jogress with the operation one above the one it was
    sent, exactly as it answers a battle: 0x10/0x11 for Digimon data,
    0x12/0x13 for battle data, and so 0x14/0x15 here. Measured -- a Pendulum
    Color sent `C1-47444470001400020006000300038BD6` replied
    `4744447000150004001D000100038BEE`, a valid packet naming
    Hi-Commandramon on its own roster.

    A two-packet named code measures the other pair: sending 0x14 then 0x16
    drew 0x15 then 0x17, both describing the same pet, so the +1 holds for
    the second packet too. Only the first reply is read -- the second repeats
    it.

    Reading only the initiator's 0x14, which is what a code we SEND always
    carries, threw that reply away as "not a jogress" -- the device evolved
    and our pet did not. `operation` stays the one a stored code carries,
    because that is what the builder filters on; this is what may come back.
    """
    return data.get("operations") or [data["operation"]]


def _words(packet_hex):
    return [int(packet_hex[i:i + 4], 16) for i in range(0, 32, 4)]


def parse(packet_hex, protocol=None):
    """The partner a device offered, or None if the packet is not one.

    Takes the packet with or without its `C1-` prefix. Returns the same
    shape a route matches on -- Omnipet's stage and attribute -- plus the
    version and index, which identify the Digimon on its own roster. The
    version comes back as the module's, already through the line's map.
    """
    if not packet_hex:
        return None
    body = packet_hex.split("-")[-1].strip().upper()
    if len(body) != 32:
        return None
    try:
        w = _words(body)
    except ValueError:
        return None
    if sum(w[:-1]) & 0xFFFF != w[_CHECK]:
        return None

    data = _database()
    if w[_OPERATION] not in _operations(data):
        return None

    magic = "%04X%04X" % (w[_MAGIC_HIGH], w[_MAGIC_LOW])
    names = dict((v, k) for k, v in data["attribute_codes"].items())
    if w[_ATTRIBUTE] not in names:
        return None

    line = None
    for name, entry in data.get("protocols", {}).items():
        presents = entry.get("presents") or []
        if presents and presents[0]["rom"].split("-")[1][:8] == magic:
            line = name
            break
    if protocol and line and line != protocol:
        return None

    line = line or protocol
    return {
        "protocol": line,
        "version": module_version(line, w[_VERSION]),
        "wire_version": w[_VERSION],
        "index": w[_INDEX],
        "attribute": names[w[_ATTRIBUTE]],
        "stage": w[_STAGE] + data["stage_offset"],
    }


def _parse_dmx(packets, protocol, expected=None):
    """A PENZ jogress reply -> the pet the device presented, or None.

    Packet 1 announces its version and packet 2 describes its pet, the same
    two fields a DMX battle reads off its own packets 1 and 2 -- which is
    also why the count matters. This wire carries no checksum, and a battle
    on it opens with two packets shaped exactly like these, so an attempt of
    the wrong length is a battle (or noise) and not a jogress.
    """
    if len(packets) < 2:
        return None
    if expected is not None and len(packets) != expected:
        return None
    try:
        values = [int(packet, 16) for packet in packets]
    except ValueError:
        return None
    # Every packet on this wire ends in the EOL nibble; anything else is not
    # one, and reading it would invent a Digimon out of noise.
    if any(value & 0xF != _EOL for value in values):
        return None
    header, pet = values[0], values[1]
    attribute = _DMX_ATTRIBUTES.get((pet >> 4) & 0x3)
    if attribute is None:
        return None

    wire_version = (header >> 4) & 0xF
    return {
        "protocol": protocol,
        "version": module_version(protocol, wire_version),
        "wire_version": wire_version,
        "index": (pet >> 6) & 0x7F,
        "attribute": attribute,
        "stage": (pet >> 13) + _DMX_STAGE_OFFSET,
    }


def parse_reply(packets, protocol):
    """The partner a device offered, read in whichever layout its line uses.

    Takes the packets a single exchange attempt produced, in the order they
    arrived. The Colour wire settles it in one 16-byte packet; the DMX wire
    needs two of its three, because the version and the pet are in different
    packets.
    """
    line = _line(protocol)
    if not line or not packets:
        return None
    layout = line.get("packets")
    if layout == "colour":
        return parse(packets[0], protocol)
    if layout == "dmx":
        return _parse_dmx(packets, protocol, line.get("packet_count"))
    return None


def rom_for_pet(pet, protocol):
    """The ROM presenting *pet*, or None if no real device presents its like.

    An exact match first -- a ROM whose version, index, attribute and stage
    are this very Digimon -- because that is what a named jogress needs: the
    device has to recognise *who* answered, not merely what shape it was.
    A module's LadyDevimon is version 3, index 18, Virus, Perfect, and the
    ROM labelled "Jogress Angewomon into Mastemon" carries exactly that,
    because that code is the one presenting a LadyDevimon.

    Failing an exact match, the generic entry for the pet's stage and
    attribute, which is all an attribute jogress needs.
    """
    line = _line(protocol)
    if not line:
        return None

    stage = getattr(pet, "stage", None)
    attribute = getattr(pet, "attribute", None) or "Free"
    version = getattr(pet, "version", None)
    index = getattr(pet, "index", None)

    if version is not None and index is not None:
        for entry in line.get("named", []):
            if (entry.get("version") == version and entry.get("index") == index
                    and entry.get("attribute") == attribute
                    and entry.get("stage") == stage):
                return entry["rom"]

    return rom_for(protocol, stage, attribute)


def presented_pet(partner, roster, protocol=None):
    """Which record in *roster* the device just presented, or None.

    The reply carries a version and index naming a Digimon on that device's
    own roster -- and for a module that is the same roster, the version
    already resolved by `parse`.
    """
    if not partner or not roster:
        return None
    version = partner.get("version")
    for record in roster:
        if (record.get("version") == version
                and record.get("index") == partner.get("index")):
            return record
    return None


def matching_route(pet, partner, roster=None):
    """The evolve route *pet* takes for this partner, or None.

    Two kinds of route, and the packet can satisfy both:

    * an **attribute** jogress names what the partner must be, which is
      exactly what the packet carries -- stage and attribute;
    * a **named** jogress names who it must be, which needs the module's own
      roster to turn the reply's version and index back into a Digimon. Pass
      *roster* for those; without it they are skipped rather than guessed at.

    Single and Dual are not consulted. They decide how many pets come out of
    a jogress between two of ours; over the wire the device keeps its own and
    we keep ours, so ours simply evolves.
    """
    if not partner:
        return None

    from utils import jogress_utils

    presented = presented_pet(partner, roster, partner.get("protocol"))
    routes = [jogress_utils.normalize_evolution(r)
              for r in (getattr(pet, "evolve", None) or [])
              if jogress_utils.is_jogress(r)]

    # A named route wins over an attribute one. Evolution is otherwise
    # first-match-wins on module order, and modules list the attribute routes
    # first -- but the wire says exactly *who* answered, which is the thing a
    # named route asks for and an attribute route only approximates. Pairing
    # LadyDevimon with Angewomon gives Mastemon on the device, not the
    # NoblePumpkinmon its "any Vaccine Perfect" route would otherwise take.
    if presented:
        for route in routes:
            named = route.get("jogress_name")
            if not named:
                continue
            if (presented.get("name") == named
                    and (route.get("jogress_version") is None
                         or route.get("jogress_version") == presented.get("version"))):
                return route

    for route in routes:
        if route.get("jogress_name"):
            continue
        if (route.get("jogress_stage") == partner["stage"]
                and route.get("jogress_attribute") == partner["attribute"]):
            return route
    return None
