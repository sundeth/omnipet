"""
DComCapture - record a device whose battle format is not written yet.

A line can be offered in the DCom grid before Omnipet can battle it
(``protocol_constants.CAPTURE_FORMATS``): a code is known to make the device
start an exchange, and nothing is known about what the device sends back.
This answers with that code, keeps every exchange the device runs, and logs
each one laid out for decoding -- the way the iC's layout was read, from its
own DCom transcripts (``utilities/IC/protocol.txt``). It never makes a battle
out of them: nothing in the packets is understood yet, and a battle built
from them would be invented.

It stands in for ``DComBattleSimulator`` in ``DComView``, offering only what
the listening loop reads, and acts as its own exchange: there is nothing of
the pet's to encode, so ``cable_command`` is the code as written and the
adapter resolves its ``^``/``@`` operators.
"""

import re

from battle.sim import protocol_constants

#: One packet each way on a 16-bit wire's transcript line.
_RECEIVED = re.compile(r'r:([0-9A-Fa-f]{4})(?![0-9A-Fa-f])')
_SENT = re.compile(r's:([0-9A-Fa-f]{4})(?![0-9A-Fa-f])')


def digit_sum(packets):
    """The packets' hex digits added up, mod 16."""
    return sum(int(digit, 16) for packet in packets for digit in packet) % 16


class DComCapture:
    """Answers a device with a fixed code and records what it sends."""

    #: Read by DComView to take the capture path instead of a battle's.
    capture_only = True
    #: The code carries nothing of the pet's, so there is no charge to play.
    minigame = "None"
    #: Every capture code on record answers (`IC2-`): the device opens.
    goes_first = False
    packet_hex_length = 4

    def __init__(self, battle_format):
        self.battle_format = battle_format
        self.constants = protocol_constants.capture_constants(battle_format)
        if self.constants is None:
            raise ValueError(f"{battle_format} has no capture code")
        # DComView sets and reads these on any simulator; a fixed code has
        # no version to announce or negotiate.
        self.opening = False
        self.sent_version = None
        self.force_version = None
        #: Every exchange so far: [(ours, theirs)], hex strings per packet.
        self.captures = []

    @property
    def expected_packet_count(self):
        return self.constants.PACKET_COUNT

    def response_pattern(self):
        return _RECEIVED

    def charge_value(self, session):
        return 0

    def peek_version(self, packet_hex):
        return None

    def cable_command(self):
        return self.constants.CAPTURE_ROM

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(self, line):
        """Keep the exchange on one adapter line; the report to log, or [].

        A short exchange is kept too: where a device stops is as telling as
        what it sent before stopping. ``0000`` is data here -- the code's own
        last sixteen packets are all zero -- not the empty read a battle
        format discards.
        """
        theirs = [packet.upper() for packet in _RECEIVED.findall(line)]
        if not theirs:
            return []
        ours = [packet.upper() for packet in _SENT.findall(line)]
        previous = self.captures[-1][1] if self.captures else None
        self.captures.append((ours, theirs))
        return self.describe(len(self.captures), ours, theirs, previous)

    def describe(self, number, ours, theirs, previous=None):
        """The exchange laid out for decoding, one log line per entry."""
        limits = self.constants
        name = limits.NAME
        lines = [f"===== {name} EXCHANGE #{number}: {len(theirs)} of "
                 f"{limits.PACKET_COUNT} packets =====",
                 f"{name}: {' '.join(theirs)}",
                 f"ours: {' '.join(ours) or '(not echoed)'}"]

        # Body and EOL of every packet that is not all zero; a run of zero
        # packets is one line, since the code's own tail is sixteen of them.
        quiet = [i for i, packet in enumerate(theirs, 1) if packet == "0000"]
        for index, packet in enumerate(theirs, 1):
            if packet != "0000":
                mine = ours[index - 1] if index <= len(ours) else "----"
                lines.append(f"  P{index:<2} {packet}  body {packet[:3]}  "
                             f"EOL {packet[3]}  | ours {mine}")
        if quiet:
            lines.append(f"  all zero: {self._ranges(quiet)}")

        # The code's `@` asks for its packets 1..n to reach a remainder; a
        # device keeping the same check would show it on its own side too.
        span = limits.CAPTURE_CHECK_PACKETS
        target = limits.CAPTURE_CHECK_REMAINDER
        if len(theirs) >= span:
            device_sum = digit_sum(theirs[:span])
            lines.append(
                f"  digits P1-P{span} mod 16: {name} {device_sum:X}, ours "
                f"{digit_sum(ours[:span]):X} (the code asks for {target:X})"
                + (" -- MATCHES" if device_sum == target else ""))
        lines.append(f"  digits P1-P{len(theirs)} mod 16: {name} {digit_sum(theirs):X}")

        # `^` replies are XORs against the packet answered: show what the
        # device's packet held and what it became in ours.
        echo = limits.CAPTURE_ECHO_PACKET
        if len(theirs) >= echo and len(ours) >= echo:
            theirs_digits = theirs[echo - 1]
            ours_digits = ours[echo - 1]
            flips = [int(a, 16) ^ int(b, 16) for a, b in zip(theirs_digits, ours_digits)]
            lines.append(
                f"  P{echo} echo: {name} {theirs_digits} -> ours {ours_digits}, "
                f"XOR per digit {''.join('%X' % f for f in flips)} (the code "
                f"asks for {''.join('%X' % x for x in limits.CAPTURE_ECHO_XOR)} "
                f"on the first {len(limits.CAPTURE_ECHO_XOR)})")

        if previous is not None:
            changed = [f"P{i} {old}->{new}"
                       for i, (old, new) in enumerate(zip(previous, theirs), 1)
                       if old != new]
            if len(previous) != len(theirs):
                changed.append(f"length {len(previous)}->{len(theirs)}")
            lines.append("  since #%d: %s" % (number - 1, ", ".join(changed) or "identical"))
        return lines

    @staticmethod
    def _ranges(numbers):
        """``[5, 6, 7, 9]`` as ``P5-P7, P9``."""
        spans = []
        for number in numbers:
            if spans and number == spans[-1][1] + 1:
                spans[-1][1] = number
            else:
                spans.append([number, number])
        return ", ".join(f"P{a}" if a == b else f"P{a}-P{b}" for a, b in spans)
