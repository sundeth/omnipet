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
#: 16-byte packets; the others are the 2-byte prong/IR wires. **"IC" is two
#: letters**, the Digivice iC's own infrared battle -- Omnipet's own punchbag
#: file has shipped an `IC1-` ROM all along and this parser rejected it,
#: because every other signal is a single character. Longest first, so "IC"
#: is matched before anything that starts with "I".
SIGNAL_TYPES = ("IC", "V", "X", "Y", "C")

#: Turn 1 opens the exchange, turn 2 listens and answers, and 0 is listen-only.
TURNS = (0, 1, 2)

#: Single-letter commands that are not ROMs.
OTHER_COMMANDS = ("P", "I")

#: A packet group: hex digits, possibly carrying adapter operators.
_PACKET = re.compile(r"^[0-9A-F@^]+$", re.I)

#: A Colour packet: eight 16-bit words, each four hex digits or one of the
#: two word instructions dmcomm-python and the dmcomm firmware share --
#: ``++++`` (the sum of the words before it in this packet) and ``____``
#: (the same word of the packet just received).
_COLOUR_PACKET = re.compile(r"^(?:[0-9A-F]{4}|\+{4}|_{4})+$", re.I)

#: Digits an operator consumes, so a group's literal width can be measured.
_OPERATOR = re.compile(r"[@^].", re.I)

#: The Colour word instructions, for reading a packet's literal digits.
_WORD_INSTRUCTION = re.compile(r"\+{4}|_{4}")


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
            literal = not any(mark in packet for mark in "@^+_")
            digits = _WORD_INSTRUCTION.sub("0000", _OPERATOR.sub("0", packet))
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

    # Longest signal first: "IC" is two characters and everything else is
    # one, so matching a single character would read an iC ROM as an unknown
    # "I" and reject it.
    signal_type = next((t for t in sorted(SIGNAL_TYPES, key=len, reverse=True)
                        if upper.startswith(t)), None)
    if signal_type is None:
        raise CommandError("Unknown signal type: %s" % command[0])
    width = len(signal_type)
    if len(command) <= width or not command[width].isdigit():
        raise CommandError("No turn digit: %s" % command[:4])
    turn = int(command[width])
    if turn not in TURNS:
        raise CommandError("Bad turn: %d" % turn)

    rest = command[width + 1:]
    if not rest.startswith("-"):
        raise CommandError("Expected '-' after the turn: %s" % command[:6])
    packets = [p for p in rest[1:].split("-") if p != ""]
    if not packets:
        raise CommandError("No packets: %s" % command)
    pattern = _COLOUR_PACKET if signal_type == "C" else _PACKET
    for packet in packets:
        if not pattern.match(packet):
            raise CommandError("Bad packet: %s" % packet)
        if literal_width(packet) % 2:
            raise CommandError("Packet is not whole bytes: %s" % packet)

    return DigiROM(signal_type, turn, packets)


# ---------------------------------------------------------------------------
# Resolving a packet the way the adapter does
# ---------------------------------------------------------------------------
#
# A ROM's operators are the adapter's to work out, at the moment it sends the
# packet, against what it has seen so far. Omnipet stands where the adapter
# and the toy both stand, so it has to work them out exactly as the adapter
# would -- these follow dmcomm's `makePacket` and `makeColorPacket`
# (dmcomm-project/dmcomm/dmcomm.ino), which dmcomm-python matches:
#
# * ``^X`` XORs digit X with the same digit of **the packet just received**.
#   That is the toy's packet at the same index when the toy opened (turn 2),
#   and the one before it when the adapter opened (turn 1); before anything
#   has arrived it is zero.
# * ``@X`` is a check digit: it makes the sum of every digit the adapter has
#   sent in this exchange, this packet included, come to X (mod 16). The
#   running sum carries from packet to packet.
# * A Colour packet's ``++++`` is the 16-bit sum of the words before it in
#   that packet, and ``____`` copies the word in the same place of the packet
#   just received (zero before anything has arrived).


class AdapterState:
    """What an adapter carries from one packet of a ROM to the next."""

    def __init__(self):
        #: The running digit sum the ``@`` check digit is taken against.
        self.checksum = 0
        #: The last packet received from the toy, as bytes, or None.
        self.last_received = None


def resolve_packet(signal_type, template, state):
    """One packet of a ROM as the adapter puts it on the wire.

    Returns the packet's hex digits, or None when the template cannot be
    read (dmcomm prints ``s:?`` and stops). *state* is updated.
    """
    if signal_type == "C":
        return _resolve_colour(template, state)
    return _resolve_classic(template, state)


def _resolve_classic(template, state):
    width = literal_width(template)
    received = state.last_received
    if received is not None and len(received) * 2 == width:
        digits = [int(c, 16) for c in received.hex()]
    else:
        digits = [0] * width
    check_at = check_target = None
    position = cursor = 0
    text = template.upper()
    while cursor < len(text):
        if position >= width:
            return None
        character = text[cursor]
        if character in "@^":
            if cursor + 1 >= len(text) or text[cursor + 1] not in "0123456789ABCDEF":
                return None
            operand = int(text[cursor + 1], 16)
            if character == "@":
                check_at, check_target = position, operand
            else:
                digits[position] ^= operand
            cursor += 2
        else:
            if character not in "0123456789ABCDEF":
                return None
            digits[position] = int(character, 16)
            cursor += 1
        if character != "@":
            state.checksum = (state.checksum + digits[position]) & 0xF
        position += 1
    if check_at is not None:
        digits[check_at] = (check_target - state.checksum) & 0xF
        state.checksum = check_target
    return "".join("%X" % digit for digit in digits)


def _resolve_colour(template, state):
    text = template.upper()
    if len(text) % 4:
        return None
    received = state.last_received
    words = []
    total = 0
    for at in range(0, len(text), 4):
        token = text[at:at + 4]
        if token == "++++":
            word = total & 0xFFFF
        elif token == "____":
            index = at // 4
            word = (int.from_bytes(received[index * 2:index * 2 + 2], "big")
                    if received is not None and len(received) >= index * 2 + 2 else 0)
        else:
            try:
                word = int(token, 16)
            except ValueError:
                return None
        words.append(word)
        total += word
    return "".join("%04X" % word for word in words)
