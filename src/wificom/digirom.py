"""Reading a DigiROM command string back.

`battle/dcom/dcom_protocol.py` writes these; nothing read them until now, and
that was the one hard blocker on Omnipet answering a WiFiCom. A DigiROM is
what an app sends for the adapter to play at a toy:

    C1-47444C4300000001000C007300019408-47444C4300020002000000000000938B
    V2-04^0E-4EEE-@E00E
    V1-FC03-FD02

so it is a signal letter, a turn digit, and then one packet per `-` group.
Two single-letter commands share the same channel and are not ROMs at all:
`P` pauses and `I` asks for version info -- an app sends `P` after it has
consumed a result, so a WiFiCom that ignores it looks wedged even when
everything else works.

Packets are kept **as written**, operators and all. `^` XORs a digit against
the packet being replied to and `@` is a check digit: both are resolved by
the adapter at send time, against bytes that do not exist until the exchange
runs, so a parser has no business evaluating them. `packet_bytes` gives the
literal ones and reports which could not be taken literally.
"""

import re

from wificom.dmcomm_shim import CommandError

#: Signal letters dmcomm accepts. "C" is the Colour transport, which carries
#: 16-byte packets; the other three are the 2-byte prong/IR wires.
SIGNAL_TYPES = ("V", "X", "Y", "C")

#: Turn 1 opens the exchange, turn 2 listens and answers, and 0 is listen-only.
TURNS = (0, 1, 2)

#: Single-letter commands that are not ROMs.
OTHER_COMMANDS = ("P", "I")

#: A packet group: hex digits, possibly carrying adapter operators.
_PACKET = re.compile(r"^[0-9A-F@^]+$", re.I)

#: Digits an operator consumes, so a group's literal width can be measured.
_OPERATOR = re.compile(r"[@^].", re.I)


class OtherCommand:
    """A `P` or `I`, which the caller answers without touching the wire."""

    signal_type = None

    def __init__(self, op):
        self.op = op

    def __repr__(self):
        return "OtherCommand(%r)" % self.op


class DigiROM:
    """One parsed command: a signal type, a turn, and its packets."""

    def __init__(self, signal_type, turn, packets):
        self.signal_type = signal_type
        self.turn = turn
        self.packets = list(packets)
        #: Filled in by the executor, and what gets published.
        self.result = None

    def __len__(self):
        return len(self.packets)

    def __repr__(self):
        return "DigiROM(%s%d, %d packets)" % (self.signal_type, self.turn,
                                              len(self.packets))

    @property
    def packet_hex_length(self):
        """Hex digits per packet, ignoring operators.

        The Colour wire's 16-byte packets are 32 digits and everything else
        is 4, so this is what tells the two apart.
        """
        widths = {literal_width(p) for p in self.packets}
        return widths.pop() if len(widths) == 1 else 0

    def packet_bytes(self):
        """(bytes, literal) per packet.

        `literal` is False where a packet carries an operator the adapter
        would have resolved: its bytes are then whatever the literal digits
        give, which is enough to read the fields that are not computed.
        """
        out = []
        for packet in self.packets:
            literal = "@" not in packet and "^" not in packet
            digits = _OPERATOR.sub("0", packet)
            try:
                out.append((bytes.fromhex(digits), literal))
            except ValueError:
                out.append((b"", False))
        return out


def literal_width(packet):
    """How many hex digits a packet is, counting an operator pair as one."""
    return len(_OPERATOR.sub("0", packet))


def parse_command(text):
    """A DigiROM command string -> DigiROM or OtherCommand.

    Raises `CommandError` on anything it cannot read, which is what the
    callers already expect: upstream answers a bad ROM by publishing the
    error rather than going quiet.
    """
    if text is None:
        raise CommandError("No command")
    command = str(text).strip()
    if not command:
        raise CommandError("Empty command")

    upper = command.upper()
    if upper in OTHER_COMMANDS:
        return OtherCommand(upper)

    signal_type = upper[0]
    if signal_type not in SIGNAL_TYPES:
        raise CommandError("Unknown signal type: %s" % command[0])
    if len(command) < 2 or not command[1].isdigit():
        raise CommandError("No turn digit: %s" % command[:4])
    turn = int(command[1])
    if turn not in TURNS:
        raise CommandError("Bad turn: %d" % turn)

    rest = command[2:]
    if not rest.startswith("-"):
        raise CommandError("Expected '-' after the turn: %s" % command[:6])
    packets = [p for p in rest[1:].split("-") if p != ""]
    if not packets:
        raise CommandError("No packets: %s" % command)
    for packet in packets:
        if not _PACKET.match(packet):
            raise CommandError("Bad packet: %s" % packet)
        if literal_width(packet) % 2:
            raise CommandError("Packet is not whole bytes: %s" % packet)

    return DigiROM(signal_type, turn, packets)
