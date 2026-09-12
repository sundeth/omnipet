"""Playing a received DigiROM against the pet, as a WiFiCom would at a toy.

Upstream's WiFiCom hands the parsed ROM to dmcomm-python's controller, which
drives the prong line and collects what the toy sent back. Omnipet *is* the
toy, so the same job is: read the ROM's packets as the opponent's, build our
pet's for that wire, and report the exchange the way the adapter would have
printed it.

**The result is an exchange, not a command.** Upstream publishes
`str(rom.result)`, tests it with `"r:" in result`, and calls it short if
`len(rom.result) < 2 * len(rom)` -- so a finished exchange is two entries per
packet, one sent and one received, and anything without an `r:` reads as a
failure. Publishing a freshly built command instead is why nothing ever
answered: it is the right bytes in the wrong envelope.

Which is `s:` and which is `r:` follows from where the adapter stands. It
*sends* the ROM's packets and *receives* the toy's, so the ROM's own packets
are the `s:` ones and ours are the `r:` ones -- the mirror image of a DCom
battle log, where Omnipet was holding the adapter. The turn decides the
order: turn 1 opens with a send, turn 2 listens first.

**A ROM's turn is the adapter's, and we are on the other side of it.** Turn 1
means the app opens the exchange, so it is the initiator and *we* answer --
our Order bit is 0, which is what a turn of 2 produces. Building our packets
on the ROM's own turn claims the initiative twice over and puts the wrong bit
on both sides.
"""

from core import runtime_globals
from wificom.digirom import DigiROM

#: What the adapter prints for a read that never arrived.
TIMEOUT_MARKER = "t"


def format_result(entries, timed_out=False):
    """The adapter's own rendering of an exchange.

    Entries are ``("s", hex)`` / ``("r", hex)`` in the order they happened.
    """
    text = " ".join("%s:%s" % (kind, value.upper()) for kind, value in entries)
    if timed_out:
        text = (text + " " + TIMEOUT_MARKER).strip()
    return text


def battle_format_for(rom, pet=None):
    """The battle format a received ROM is asking for.

    The signal letter and the packet **width** say which wire it is on, and
    those are the only two that always hold: a ROM is not always a battle.
    A scan is one packet and a jogress three, where the same wire's battle is
    two or six, so a format's own packet count can only ever be a preference.

    Several formats share a wire, so among the survivors: the Colour lines
    name themselves in their first four bytes, and otherwise the pet's own
    module breaks the tie -- a DMX and a PENZ differ only in the charge
    minigame, so following the pet keeps the exchange consistent with it.
    """
    from battle.sim import protocol_constants

    width = rom.packet_hex_length
    if not width:
        return None

    candidates = []
    for name in protocol_constants.BATTLE_FORMATS:
        wire = protocol_constants.get_wire(name)
        if getattr(wire, "DCOM_OP", protocol_constants.DCOM_OP) != rom.signal_type:
            continue
        if getattr(wire, "PACKET_BYTES", 2) * 2 == width:
            candidates.append(name)
    if not candidates:
        return None

    # The Colour wire says outright which line it is: its first four bytes.
    first = rom.packets[0]
    for name in candidates:
        magic = getattr(protocol_constants.get_constants(name), "MAGIC", None)
        if magic is not None and len(first) >= 8 and first[:8].upper() == "%08X" % magic:
            return name

    # Then the pet's own module, if this is its wire.
    if pet is not None:
        from battle.sim.dcom_battle_simulator import is_oem_pet

        for name in candidates:
            if is_oem_pet(pet, name):
                return name

    # Then whichever format sends this many packets, and failing that the
    # first on the wire -- a ROM whose length matches nothing is still worth
    # answering, it is just not a battle.
    for name in candidates:
        if protocol_constants.get_wire(name).PACKET_COUNT == len(rom):
            return name
    return candidates[0]


def execute(rom, pet, battle_format=None):
    """Play *rom* against *pet* and return the exchange, as the adapter prints it.

    Returns the result string; `rom.result` is set to the same value, which
    is what upstream publishes.
    """
    if not isinstance(rom, DigiROM):
        raise ValueError("Not a DigiROM")

    battle_format = battle_format or battle_format_for(rom, pet)
    if battle_format is None:
        rom.result = format_result([], timed_out=True)
        runtime_globals.game_console.log(
            "[WiFiCom] No battle format matches %r (%d packets of %d digits)"
            % (rom.signal_type + str(rom.turn), len(rom), rom.packet_hex_length))
        return rom.result

    from battle.sim import protocol_constants
    from battle.sim.dcom_battle_simulator import (DComBattleSimulator,
                                                  pet_to_digimon)

    # A Colour ROM names its line in the first four bytes, and a device only
    # answers its own: "sending a Pendulum Color GDLC is why it never
    # answered". A scan for some other Colour line is not for this pet.
    magic = getattr(protocol_constants.get_constants(battle_format), "MAGIC", None)
    first = rom.packets[0]
    if magic is not None and len(first) >= 8 and first[:8].upper() != "%08X" % magic:
        runtime_globals.game_console.log(
            "[WiFiCom] %s is addressed to %s, and this pet is %s -- not answering"
            % (rom, first[:8].upper(), "%08X" % magic))
        rom.result = format_result([], timed_out=True)
        return rom.result

    simulator = DComBattleSimulator(None, battle_format=battle_format)
    digimon = pet_to_digimon(pet, battle_format)
    # Our turn is the opposite of the ROM's: whoever opens carries Order 1,
    # and if the app opened then we did not.
    our_turn = (protocol_constants.DCOM_TURN_LISTEN
                if rom.turn == protocol_constants.DCOM_TURN_GO_FIRST
                else protocol_constants.DCOM_TURN_GO_FIRST)
    from battle.sim.exchange import PacketExchange
    exchange = PacketExchange(battle_format, digimon, opens=our_turn == 1)
    theirs, mine = [], []
    # Feed the actual ROM in wire order. Even the fallback executor must
    # resolve outcomes after receiving the required fields.
    for packet in rom.packets:
        before = len(exchange.received)
        if exchange.opens:
            reply = exchange.next_packet()
        exchange.receive(packet)
        if exchange.aborted or len(exchange.received) == before:
            break
        if not exchange.opens:
            reply = exchange.next_packet()
        theirs.append(exchange.received[-1].hex().upper())
        if reply is not None:
            mine.append(reply.hex().upper())

    # One send and one receive per packet the ROM carries -- the adapter does
    # exactly that many exchanges, so a one-packet scan is answered with one
    # packet and not with a whole battle. Our packet 1 already carries the
    # pet's identity, which is what a scan is asking for.
    rounds = len(theirs)
    if len(mine) < rounds:
        runtime_globals.game_console.log(
            "[WiFiCom] %s sends %d packet(s) but the ROM has %d; answering "
            "what we have" % (battle_format, len(mine), rounds))

    # The adapter sends the ROM's packets and receives ours. Turn 1 opens with
    # a send; turn 2 listens first, so the toy's packet leads.
    entries = []
    for index in range(rounds):
        sent = theirs[index]
        received = mine[index] if index < len(mine) else None
        pair = [("s", sent), ("r", received)]
        if rom.turn != 1:
            pair.reverse()
        for kind, value in pair:
            if value is not None:
                entries.append((kind, value))

    rom.result = format_result(entries, timed_out=len(mine) < rounds)
    runtime_globals.game_console.log(
        "[WiFiCom] Played %s as %s: %d packet(s) each way"
        % (rom, battle_format, len(mine)))
    return rom.result


def opponent_from(rom, pet, battle_format=None):
    """The opponent the ROM describes, or None if it cannot be read.

    Used to turn a completed exchange into a battle the player can watch;
    the exchange itself does not need it.
    """
    battle_format = battle_format or battle_format_for(rom, pet)
    if battle_format is None:
        return None, None
    from battle.sim.dcom_battle_simulator import DComBattleSimulator, pet_to_digimon

    simulator = DComBattleSimulator(None, battle_format=battle_format)
    try:
        opponent = simulator.parse_opponent([p.upper() for p in rom.packets],
                                            pet_to_digimon(pet, battle_format))
    except Exception as error:  # pylint: disable=broad-except
        runtime_globals.game_console.log(f"[WiFiCom] Could not read opponent: {error}")
        return None, battle_format
    return opponent, battle_format
