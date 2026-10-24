"""Playing a received DigiROM against the pet, as a WiFiCom would at a toy.

Upstream's WiFiCom hands the parsed ROM to dmcomm-python's controller, which
drives the prong line and collects what the toy sent back. Omnipet *is* the
toy, so the same job is: play the ROM's packets as the adapter would send
them, answer each as the pet would on the selected line, and report the
exchange the way the adapter prints it.

**The battle format is the one the player selected, never one read off the
ROM.** Several lines share a wire (DMX and PENZ, DM20 and PEN20 send the same
layout), so a ROM cannot say which line it is for -- `fits` only checks that
it can be the selected one (signal letter, packet width, Colour magic,
packet count) and refuses it otherwise, the way a toy of another line would
simply not answer. Nothing here falls back to the pet's module or to
whichever format the packet count suggests.

**The result is an exchange, not a command.** Upstream publishes
`str(rom.result)`, tests it with `"r:" in result`, and calls it short if
`len(rom.result) < 2 * len(rom)` -- so a finished exchange is two entries per
packet, one sent and one received, and anything without an `r:` reads as a
failure.

**`s:` is what the adapter sent and `r:` what the toy (our pet) sent** -- the
mirror image of a DCom battle log, where Omnipet holds the adapter. The ROM's
turn is the adapter's: turn 1 means the adapter opens and our pet answers,
turn 2 means the adapter listens and **our pet opens**. The order follows
(turn 1 `s: r: ...`, turn 2 `r: s: ...`), and so does what is printed at the
end: a turn-2 adapter listens once more after its last packet and, the toy
having nothing left to say, prints ``t`` -- every turn-2 capture on record
ends `... s:XXXX t` -- while a turn-1 exchange ends on the toy's last packet.

The adapter's operators (``^``, ``@``, Colour ``++++``/``____``) are worked
out by `digirom.resolve_packet`, as dmcomm works them out, against the
packet it has just received from the pet.
"""

from core import runtime_globals
from wificom import digirom as digirom_module
from wificom.digirom import DigiROM

#: What the adapter prints for a read that never arrived.
TIMEOUT_MARKER = "t"
#: What dmcomm prints for a packet it could not build from the ROM.
UNREADABLE_PACKET = "?"


def format_result(entries, timed_out=False):
    """The adapter's own rendering of an exchange.

    Entries are ``("s", hex)`` / ``("r", hex)`` in the order they happened.
    """
    text = " ".join("%s:%s" % (kind, value.upper()) for kind, value in entries)
    if timed_out:
        text = (text + " " + TIMEOUT_MARKER).strip()
    return text


def fits(rom, battle_format):
    """Why *rom* cannot be a ROM for *battle_format*, or None if it can.

    Only what the wire itself says is checked: the signal letter, the packet
    width, a Colour line's magic in its first four bytes, the turn, and that
    it carries no more packets than the line sends. Fewer is fine -- a scan
    is one packet.
    """
    from battle.sim import protocol_constants

    battle_format = protocol_constants.canonical_format(battle_format or "")
    if battle_format not in protocol_constants.BATTLE_FORMATS:
        return "no battle format selected" if not battle_format else (
            "%s has no battle format" % battle_format)
    if not isinstance(rom, DigiROM):
        return "not a DigiROM"
    wire = protocol_constants.get_wire(battle_format)
    signal = getattr(wire, "DCOM_OP", protocol_constants.DCOM_OP)
    if rom.signal_type != signal:
        return "the %s signal, and %s is on %s" % (rom.signal_type, battle_format, signal)
    if rom.turn not in (protocol_constants.DCOM_TURN_GO_FIRST,
                        protocol_constants.DCOM_TURN_LISTEN):
        return "turn %d only listens" % rom.turn
    width = getattr(wire, "PACKET_BYTES", 2) * 2
    if rom.packet_hex_length != width:
        return "packets of %s digits, and %s sends %d" % (
            rom.packet_hex_length or "mixed", battle_format, width)
    if len(rom) > wire.PACKET_COUNT:
        return "%d packets, and %s sends %d" % (len(rom), battle_format,
                                                 wire.PACKET_COUNT)
    magic = getattr(protocol_constants.get_constants(battle_format), "MAGIC", None)
    first, literal = rom.packet_bytes()[0]
    if magic is not None and literal and first[:4].hex().upper() != "%08X" % magic:
        return "addressed to %s, and %s is %08X" % (first[:4].hex().upper(),
                                                     battle_format, magic)
    return None


class Played:
    """One DigiROM played against the pet: the exchange and what it settled."""

    def __init__(self, rom, battle_format, exchange=None, entries=(),
                 timed_out=True, refused=None):
        self.rom = rom
        self.battle_format = battle_format
        #: Our side's PacketExchange, or None when the ROM was not answered.
        self.exchange = exchange
        self.entries = list(entries)
        self.timed_out = timed_out
        #: Why the pet did not answer at all (see `fits`), or None.
        self.refused = refused
        #: What upstream publishes.
        self.result = format_result(self.entries, timed_out=timed_out)
        rom.result = self.result

    @property
    def complete(self):
        """Whether a whole battle was exchanged (not a scan or a stall)."""
        return bool(self.exchange is not None and self.exchange.complete
                    and not self.exchange.aborted)

    @property
    def enemy_first(self):
        """Whoever opened strikes first: the adapter's side on turn 1."""
        return self.rom.turn == 1

    def battle_result(self):
        """The finished battle, or None (incomplete, or it did not check out)."""
        if not self.complete:
            return None
        return self.exchange.result()

    def opponent(self):
        """The Digimon the ROM presented, or None."""
        if not self.complete:
            return None
        return self.exchange.opponent()


def play(rom, pet, battle_format, charge=0):
    """Play *rom* against *pet* on the selected *battle_format*.

    *charge* is the minigame result the pet fights with, as the DCom flow
    passes it to `pet_to_digimon`. Returns a `Played`; its `result` is the
    string upstream publishes and is also left on `rom.result`.
    """
    if not isinstance(rom, DigiROM):
        raise ValueError("Not a DigiROM")
    from battle.sim import protocol_constants

    battle_format = protocol_constants.canonical_format(battle_format or "")
    problem = fits(rom, battle_format)
    if problem:
        runtime_globals.game_console.log(
            "[WiFiCom] Not answering %r on %s: %s" % (rom, battle_format or "-", problem))
        return unanswered(rom, battle_format, problem)

    from battle.sim.dcom_battle_simulator import pet_to_digimon
    from battle.sim.exchange import PacketExchange

    # The ROM's turn is the adapter's. Turn 2 listens, so the toy -- our pet
    # -- opens, and whoever opens carries Order 1.
    opens = rom.turn == protocol_constants.DCOM_TURN_LISTEN
    exchange = PacketExchange(battle_format, pet_to_digimon(pet, battle_format, charge),
                              opens=opens)
    state = digirom_module.AdapterState()
    entries = []
    timed_out = False

    def ours():
        packet = exchange.next_packet()
        if packet is None:
            return False
        entries.append(("r", packet.hex().upper()))
        state.last_received = packet
        return True

    if opens and not ours():
        timed_out = True
    else:
        for template in rom.packets:
            theirs = digirom_module.resolve_packet(rom.signal_type, template, state)
            if theirs is None:
                entries.append(("s", UNREADABLE_PACKET))
                break
            entries.append(("s", theirs))
            exchange.receive(theirs)
            # A toy that cannot use what it was sent stops answering.
            if exchange.aborted or not ours():
                timed_out = True
                break

    played = Played(rom, battle_format, exchange, entries, timed_out)
    runtime_globals.game_console.log(
        "[WiFiCom] Played %s as %s: %d sent, %d answered%s"
        % (rom, battle_format, len(exchange.received), len(exchange.sent),
           " -- a whole battle" if played.complete else ""))
    return played


def unanswered(rom, battle_format, problem):
    """What the adapter reports when the toy does not answer at all.

    Turn 1 still sends its first packet before it waits; turn 2 only waits.
    """
    entries = []
    if rom.turn == 1 and rom.packets:
        first = digirom_module.resolve_packet(rom.signal_type, rom.packets[0],
                                              digirom_module.AdapterState())
        entries.append(("s", first or UNREADABLE_PACKET))
    return Played(rom, battle_format, None, entries, True, refused=problem)


def execute(rom, pet, battle_format, charge=0):
    """Play *rom* and return the exchange as the adapter prints it."""
    return play(rom, pet, battle_format, charge).result
