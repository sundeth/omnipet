"""Packet exchange shared by local versus, WiFiCom and cable replay.

Opening endpoints roll only after receiving the required peer fields;
responders follow their protocol's result ownership. Local versus drives two
instances. Stock cable adapters cannot call the host between packets, so
cable_command selects the role expressible with their @/^ operators and
from_transcript adopts the adapter's actual s:/r: report without rerolling.
"""

from battle.sim import protocol_constants
from core import runtime_globals


class PacketExchange:
    """Our half of one battle exchange, driven a packet at a time."""

    def __init__(self, battle_format, digimon, opens=False, peer=True, simulator=None):
        """Take the stated role; peer type never substitutes for packet data."""
        from battle.sim.dcom_battle_simulator import DComBattleSimulator

        self.battle_format = protocol_constants.canonical_format(battle_format)
        self.digimon = digimon
        self.opens = bool(opens)
        self.peer = bool(peer)
        self.simulator = simulator or DComBattleSimulator(None, battle_format=self.battle_format)
        self.simulator.opening = self.opens
        self.wire = self.simulator.wire

        self.turn = (protocol_constants.DCOM_TURN_GO_FIRST if opens
                     else protocol_constants.DCOM_TURN_LISTEN)
        #: Everything we would send, before the packets that depend on theirs
        #: are resolved. Rebuilt if we learn their version.
        self._planned = self.simulator.generate_player_packets(
            digimon, turn=self.turn, peer=self.peer)
        #: What we have actually sent, and what they have sent us.
        self.sent = []
        self.received = []
        self.aborted = False

    # ------------------------------------------------------------------
    # Shape
    # ------------------------------------------------------------------

    @property
    def packet_count(self):
        """How many packets each side sends on this wire."""
        return self.wire.PACKET_COUNT

    @property
    def packet_hex_length(self):
        return self.simulator.packet_hex_length

    @property
    def complete(self):
        """Both sides have said everything they are going to."""
        return (len(self.sent) >= self.packet_count
                and len(self.received) >= self.packet_count)

    @property
    def waiting_for_them(self):
        """True when it is their turn to speak.

        Whoever opens sends packet N before receiving it; the other side
        receives first. So the count that has to be ahead differs by one.
        """
        if self.opens:
            return len(self.received) < len(self.sent)
        return len(self.received) <= len(self.sent)

    # ------------------------------------------------------------------
    # Driving it
    # ------------------------------------------------------------------

    def receive(self, packet):
        """Take one packet from the other side. Accepts hex or bytes.

        A ROM written for an adapter still carries its operators when it
        reaches us -- an app has no reason to resolve them, because on a real
        WiFiCom the adapter would. So they are resolved here; dropping the
        packet instead stalls the exchange one short of complete, and nothing
        ever plays.
        """
        if isinstance(packet, str):
            text = packet.strip().upper()
            if text in ("FF00", ""):
                if text:
                    self.aborted = True
                return
            if "@" in text or "^" in text:
                resolved = self._resolve_incoming(text, len(self.received))
                if resolved is None:
                    runtime_globals.game_console.log(
                        f"[Exchange] Could not work out {text!r}")
                    return
                runtime_globals.game_console.log(
                    f"[Exchange] {text} resolves to {resolved}")
                text = resolved
            try:
                packet = bytes.fromhex(text)
            except ValueError:
                runtime_globals.game_console.log(
                    f"[Exchange] Not a packet: {packet!r}")
                return
        if (not isinstance(packet, (bytes, bytearray)) or
                len(packet) * 2 != self.packet_hex_length or
                len(self.received) >= self.packet_count or packet == b'\xff\x00'):
            self.aborted = True
            return
        if self.wire.NAME == 'DMC' and not self.received:
            if self.simulator.parse_colour_identity(packet) is None:
                self.aborted = True
                return
        self.received.append(bytes(packet))
        if len(self.received) == self.packet_count and not self.validate():
            self.aborted = True
            return
        if len(self.received) == 1:
            self._learn_version(packet)

    def _resolve_incoming(self, text, index):
        """One received packet with its adapter operators worked out.

        Two operators, and both are resolvable from what we already hold:

        ``^X`` XORs a digit with X against the packet being replied to, which
        for a packet they are sending us is the one we sent at the same
        index; ``@X`` is the check digit that brings the sender's own nibbles
        to a remainder of X, so it follows from their earlier packets and the
        rest of this one.
        """
        mirror = (self.sent[index].hex().upper()
                  if index < len(self.sent) else "")
        digits = []
        check_target = None
        check_at = None
        position = 0
        while position < len(text):
            character = text[position]
            if character in "@^":
                if position + 1 >= len(text):
                    return None
                try:
                    operand = int(text[position + 1], 16)
                except ValueError:
                    return None
                if character == "^":
                    if len(digits) >= len(mirror):
                        return None
                    base = int(mirror[len(digits)], 16)
                    digits.append("%X" % (base ^ operand))
                else:
                    check_target = operand
                    check_at = len(digits)
                    digits.append("0")
                position += 2
            else:
                if character not in "0123456789ABCDEF":
                    return None
                digits.append(character)
                position += 1

        if check_at is not None:
            total = 0
            for earlier in self.received[:index]:
                for byte in earlier:
                    total += (byte >> 4) & 0xF
                    total += byte & 0xF
            for at, digit in enumerate(digits):
                if at != check_at:
                    total += int(digit, 16)
            digits[check_at] = "%X" % ((check_target - total) % 16)
        return "".join(digits)

    def next_packet(self):
        """The packet we send now, or None when we have sent them all.

        Resolved against what they have already said, so the packets that a
        cable would have had the adapter compute are computed here instead.
        """
        index = len(self.sent)
        if self.aborted or self.waiting_for_them:
            return None
        if index >= len(self._planned):
            return None
        packet = self._resolve(index, self._planned[index])
        self.sent.append(packet)
        return packet

    def _learn_version(self, packet):
        """Adopt the version they announced, and rebuild if it differs.

        A device stops answering when the version it is shown is outside its
        own range, which looks exactly like a dead line -- the same rule the
        DCom flow learned the hard way against a Pendulum Z reporting 10.
        """
        try:
            theirs = self.simulator.peek_version(packet.hex())
        except Exception:
            return
        if theirs is None or theirs == self.simulator.sent_version:
            return
        if not getattr(self.digimon, "compatibility", False):
            return
        runtime_globals.game_console.log(
            f"[Exchange] They report version {theirs}; matching it")
        self.simulator.force_version = theirs
        self._planned = self.simulator.generate_player_packets(
            self.digimon, turn=self.turn, peer=self.peer)

    def _resolve(self, index, packet):
        """Fill in a packet that could only be written once they had spoken."""
        wire = self.wire.NAME
        last = index == self.packet_count - 1
        heard = len(self.received) > index

        # **The opener has to compute its own final packet too.** `heard` is
        # only ever true for the ANSWERER -- when the opener reaches its last
        # index it has received one packet fewer -- so every branch below was
        # the answerer's, and the opener shipped whatever the batch generator
        # had put there: an all-hit mask on DMX, DM20 and PEN20. A power-1
        # opener beat a power-255 opponent 20 times out of 20 with no roll
        # taken. It cannot invert what has not arrived, but by then it HAS
        # heard the packets carrying their power and attribute, so it rolls
        # against the real hit rate instead.
        if last and not heard and self.received:
            rolled = self._roll_opener_final(packet)
            if rolled is not None:
                return rolled

        # The DMX wire's last packet is the inverse of theirs: "Player and
        # Opponents appear to always be inverse, and ties are not programmed
        # into the device. If a tie would occur, the device will freeze."
        if wire == "DMX" and last and heard:
            hits = self._their_hits(self.received[index])
            if hits is not None:
                return self.simulator._rebuild_dmx_final(
                    self.sent + [packet], (~hits) & 0x1F)

        # The DM20 family's packet A holds both sides at once, so a peer's
        # has to be our inversion or the two read different battles.
        if wire in ("DM20", "PEN20") and last and heard:
            return self._invert_dm20_final(packet, self.received[index])

        # The Pendulum's hits are its own, rolled from a slot table that was
        # never published -- "would require a LOT of tedious testing". Two
        # Omnipets have no such table to agree on, so the answering side
        # takes the inverse, which is ours rather than the device's but is
        # the same guarantee the DMX gets by rule.
        if wire == "PENOG" and index == 2:
            if heard:
                return self._invert_penog_hits(packet, self.received[index])
            from battle.sim.battle_simulator import PENOGDevice
            from battle.sim.penog_rules import slot_hit_rate
            mine = PENOGDevice.parse_packet1(self.sent[0])
            theirs = PENOGDevice.parse_packet1(self.received[0])
            effort = PENOGDevice.parse_packet2(self.sent[1])['effort']
            their_effort = PENOGDevice.parse_packet2(self.received[1])['effort']
            hits = self._roll(slot_hit_rate(mine['slot'], theirs['slot'], effort, their_effort), 5)
            word = (int.from_bytes(packet, 'big') & ~(31 << 4)) | (hits << 4)
            return word.to_bytes(2, 'big')

        # ...and its Check nibble lives in packet 4, one packet later than
        # the hits it certifies, so inverting packet 3 leaves it stale. It
        # went unnoticed while packet 3 always claimed all five rounds: the
        # inverse of 0b11111 is 0b00000, which changes the nibble sum by
        # exactly 16 and so leaves the remainder alone. A rolled hit pattern
        # does not have that courtesy.
        if wire == "PENOG" and last:
            return self._recheck_penog_final(packet)

        # The Colour wire's player 1 declares the verdict, and can only do it
        # once it has seen the opponent's first packet.
        if wire == "DMC" and index == 1 and self.received:
            return self._declare_colour_outcome(packet)

        # The DMOG wire's verdict is the opposite of theirs.
        if getattr(self.wire, "DCOM_OUTCOME_ECHO", None) and index == 1 and len(self.received) > 1:
            theirs = self.received[1]
            ours = bytearray(packet)
            ours[0] = (ours[0] & 0xF0) | ((theirs[0] & 0x0F) ^ 0x3)
            ours[1] = (ours[1] & 0xF0) | ((theirs[1] & 0x0F) ^ 0x3)
            return bytes(ours)

        return packet

    def _opponent_stats(self, packets=None):
        """The opponent's power and attribute, out of what has arrived.

        Read from the packets those fields actually live in, which differ by
        wire -- the same positions the stat-aware generators use.
        """
        wire = self.wire.NAME
        got = self.received if packets is None else packets
        try:
            if wire == "DMX":
                # power in packet 5, attribute in packet 2
                power = ((got[4][0] & 0x0F) << 4) | ((got[4][1] >> 4) & 0x0F)
                return power, (got[1][1] >> 4) & 0x03
            if wire == "PEN20":
                return ((got[4][0] & 0x0F) << 4) | (got[4][1] >> 4), (got[1][1] >> 4) & 3
            if wire == "DM20":
                # attribute in packet 4, power in packet 6
                attribute = (got[3][1] >> 4) & 0b11
                power = ((got[5][0] & 0x0F) << 4) | ((got[5][1] >> 4) & 0x0F)
                return power, attribute
        except (IndexError, TypeError):
            return None
        return None

    def _roll(self, rate, count):
        """`count` rounds rolled at `rate` per cent, least significant first."""
        import random

        bits = 0
        for turn in range(count):
            if random.randint(0, 99) < rate:
                bits |= 1 << turn
        return bits

    def _roll_opener_final(self, packet):
        """The opener's dependent packet, rolled against their real stats.

        Returns None for a wire whose opener owes nothing -- the Colour
        lines, where the result belongs to whichever side the format says,
        and DMOG and PENOG, which have their own branches below.
        """
        wire = self.wire.NAME

        if wire == "DMOG":
            # **The opener declares, and it was declaring defeat.** Packet 2
            # carries the sender's own result, so an opener that ships the
            # generator's default loses every battle it starts whatever it is
            # holding -- 0 wins in 40 at power 255 against power 1. It has
            # heard their packet 1 by now, which carries the slot and boost
            # the guidebook matrix is indexed by, so it rolls that instead.
            return self._roll_dmog_outcome(packet)

        if wire not in ("DMX", "DM20", "PEN20"):
            return None
        stats = self._opponent_stats()
        if stats is None:
            return None
        their_power, their_attribute = stats
        my_power, my_attribute = self._opponent_stats(self.sent)
        limits = protocol_constants.get_constants(self.battle_format)

        ours = protocol_constants.hit_rate(
            limits, my_power, my_attribute,
            their_power, their_attribute)

        if wire == "DMX":
            hits = self._roll(ours, protocol_constants.DMX.TURNS)
            runtime_globals.game_console.log(
                "[Exchange] %s opener rolled hits %s at %d%% "
                "(power %d vs %d)"
                % (self.battle_format, format(hits, "05b"), ours,
                   self.digimon.power, their_power))
            return self.simulator._rebuild_dmx_final(self.sent + [packet],
                                                     hits)

        # Packet A states BOTH sides, so the opener rolls both: byte 1's high
        # nibble is our hits on them, byte 0's low nibble theirs on us.
        theirs = protocol_constants.hit_rate(
            limits, their_power, their_attribute,
            my_power, my_attribute)
        hits = self._roll(ours, 4) & 0xF
        # Single battles encode complementary sides of one hit decision.
        # Independent nibbles contradict each other's transcript on replay.
        dodges = (~hits) & 0xF
        runtime_globals.game_console.log(
            "[Exchange] %s opener rolled hits %s at %d%%, theirs %s at "
            "%d%%" % (self.battle_format, format(hits, "04b"), ours,
                      format(dodges, "04b"), theirs))
        return self._dm20_final(packet, dodges, hits)

    def _roll_dmog_outcome(self, packet):
        """Packet 2 with the outcome rolled from the guidebook slot matrix.

        "1 means victory while 2 means defeat", and the digit describes
        whoever sent it. Our own slot comes from the packet 1 we already
        sent; theirs from the packet 1 that arrived.
        """
        from battle.sim.battle_simulator import DMDevice

        if not self.sent or not self.received or len(packet) < 2:
            return None
        mine = DMDevice.parse_packet1(self.sent[0])
        theirs = DMDevice.parse_packet1(self.received[0])
        if not mine or not theirs:
            return None

        import random

        odds = protocol_constants.DMOG.slot_win_odds(
            protocol_constants.DMOG.slot_index(mine['slot']),
            protocol_constants.DMOG.slot_index(theirs['slot']),
            mine.get('boost', 0), theirs.get('boost', 0))
        won = random.randint(1, 16) <= odds
        outcome = (protocol_constants.DMOG.OUTCOME_VICTORY if won
                   else protocol_constants.DMOG.OUTCOME_DEFEAT)
        runtime_globals.game_console.log(
            "[Exchange] DMOG opener: slot %X against %X is %d in 16, so we "
            "declare %s" % (mine['slot'], theirs['slot'], odds,
                            "victory" if won else "defeat"))
        # Packet 2 is `Check(4) | COU(3) | Outcome(1) ...` on this wire, and
        # the generator has already laid it out -- only the outcome nibble
        # and the mirror byte change, which is what `DCOM_OUTCOME_ECHO`
        # rewrites for the answerer.
        ours = bytearray(packet)
        ours[0] = (ours[0] & 0xF0) | ((~outcome) & 0x0F)
        ours[1] = (ours[1] & 0xF0) | (outcome & 0x0F)
        return bytes(ours)

    def _dm20_final(self, packet, dodges, hits):
        """Packet A carrying these two nibbles, with its Check recomputed."""
        if len(packet) < 2:
            return packet
        eol = packet[1] & 0xF
        total = 0
        for earlier in self.sent:
            for byte in earlier:
                total += (byte >> 4) & 0xF
                total += byte & 0xF
        total += dodges + hits + eol
        target = getattr(self.wire, "CHECKSUM_REMAINDER", 0)
        check = (target - total) % 16
        return bytes([(check << 4) | dodges, (hits << 4) | eol])

    def _invert_dm20_final(self, packet, theirs):
        """Packet A with Dodges and Hits inverted from theirs.

        `Check(4) | Dodges(4) | Hits(4) | EOL(4)`, and the Check nibble has to
        be recomputed because the two it certifies just changed.
        """
        if len(theirs) < 2 or len(packet) < 2:
            return packet
        dodges = (~((theirs[0]) & 0xF)) & 0xF
        hits = (~((theirs[1] >> 4) & 0xF)) & 0xF
        return self._dm20_final(packet, dodges, hits)

    def _invert_penog_hits(self, packet, theirs):
        """Packet 3 with the hit pattern inverted from theirs."""
        if len(theirs) < 2 or len(packet) < 2:
            return packet
        their_hits = ((theirs[0] & 0x1) << 4) | ((theirs[1] >> 4) & 0xF)
        hits = (~their_hits) & 0x1F
        word = ((packet[0] << 8) | packet[1]) & ~(0x1F << 4)
        word |= (hits & 0x1F) << 4
        return bytes([(word >> 8) & 0xFF, word & 0xFF])

    def _recheck_penog_final(self, packet):
        """Packet 4 with its Check nibble recomputed over what we really sent.

        `Check(4) | Shot(8) | EOL(4)`, and the check brings the nibble sum of
        the whole four-packet signal to a remainder of 11 -- so it can only be
        written once packets 1 to 3 are final.
        """
        if len(packet) < 2:
            return packet
        limits = protocol_constants.PENOG
        shot = ((packet[0] & 0xF) << 4) | ((packet[1] >> 4) & 0xF)
        eol = packet[1] & 0xF

        total = 0
        for earlier in self.sent[:3]:
            for byte in earlier:
                total += (byte >> 4) & 0xF
                total += byte & 0xF
        total += (shot >> 4) & 0xF
        total += shot & 0xF
        total += eol
        check = (limits.CHECKSUM_REMAINDER - total) % 16
        word = ((check & 0xF) << 12) | (shot << 4) | eol
        return bytes([(word >> 8) & 0xFF, word & 0xFF])

    def _declare_colour_outcome(self, packet):
        """The battle packet that carries the result, built from their data.

        **Which side owes it depends on the line.** A Digital Monster Color
        puts the verdict in the initiator's operation 2 -- "only Operation 2
        will report the victory, Operation 3 sends 0 regardless" -- while a
        Pendulum Color and an Xros Wars put it in the RESPONDER's, which is
        the side that has heard both. `fights_its_battle` is the flag; this
        used to apply the DMC's rule to all three, so on a fought line the
        packet that actually decides the battle went out as zeros.

        Two other things were wrong here and both are the same kind of slip.
        The operation was passed on **already offset**, and `generate_packet2`
        adds the offset again -- so a Pendulum Color emitted operation `0x22`
        under its own magic. And the `DMCDevice` was built with no `limits`,
        which defaults to DMC, so even a correct outcome was suppressed on
        the way out.
        """
        from battle.sim.battle_simulator import DMCDevice
        from battle.sim.dcom_battle_simulator import colour_trailer

        line = protocol_constants.get_constants(self.battle_format)
        offset = getattr(line, "OPERATION_OFFSET", 0)
        operation = (packet[5] if len(packet) > 5 else 0)
        relative = operation - offset

        # The responder declares on a line that fights; the initiator on one
        # that exchanges a verdict.
        fought = protocol_constants.fights_its_battle(self.battle_format)
        if relative != (3 if fought else 2):
            return packet

        if not self.received:
            return packet
        opponent = self.simulator.parse_colour_identity(self.received[0])
        if opponent is None:
            return packet

        if fought:
            return self._declare_fought_colour(packet, relative, line)

        # **Tell the simulator which role we are.** It works the verdict out
        # relative to the initiator, so a wrong role inverts the answer --
        # and nothing else was setting this from the exchange's own `opens`.
        self.simulator.opening = self.opens
        try:
            import copy
            declared = copy.copy(self.digimon)
            own_identity = self.simulator._colour_words(self.sent[0])
            declared.power, declared.attribute = own_identity[5], own_identity[6]
            self.simulator.declare_colour_outcome(self.received[0], declared)
        except Exception as error:
            runtime_globals.game_console.log(
                "[Exchange] Could not declare a Colour result: %s" % error)
            return packet

        outcome = getattr(self.simulator, 'colour_outcome', 0)
        hits = getattr(self.simulator, 'colour_hits', 0)
        rebuilt = DMCDevice(
            self.digimon,
            magic=line.MAGIC,
            operation_offset=offset,
            # The charge, not the flat unlock-code value -- see
            # `colour_trailer`. Rebuilding this packet has to say the same
            # thing the first one did, or the two disagree about the charge.
            trailer=colour_trailer(self.battle_format, self.digimon),
            limits=line,
        ).generate_packet2(relative, outcome, hits)
        runtime_globals.game_console.log(
            "[Exchange] %s result declared in operation 0x%02X: "
            "word4=%d word5=0x%04X"
            % (self.battle_format, operation, outcome, hits))
        return rebuilt

    def _declare_fought_colour(self, packet, operation, line):
        """Resolve PENC/DMXW from transmitted identities and selectors only.

        Their result encodes the initiator's hit bits. Roll that one stream
        and derive the responder's complementary hits, exactly as replay
        does. Stage/effort are already represented by each sent selector.
        """
        from battle.sim.battle_simulator import DMCDevice
        from battle.sim.battle_utils import colour_knows, colour_row
        if len(self.received) != 2 or not self.sent:
            raise ValueError('Colour responder needs identity and battle data')
        if not self.simulator._validate_packets(self.received):
            raise ValueError('Invalid Colour initiator transcript')
        mine = self.simulator._colour_words(self.sent[0])
        theirs = self.simulator._colour_words(self.received[0])
        my_selector = int.from_bytes(packet[12:14], 'big')
        their_selector = int.from_bytes(self.received[1][12:14], 'big')
        if not colour_knows(my_selector) or not colour_knows(their_selector):
            raise ValueError('Unknown Colour attack selector')
        my_pattern, their_pattern = colour_row(my_selector), colour_row(their_selector)
        rate = protocol_constants.hit_rate(line, theirs[5], theirs[6], mine[5], mine[6])
        hits = self._roll(rate, line.TURNS)
        my_hp = their_hp = line.FIXED_HP
        for turn, (my_attack, their_attack) in enumerate(zip(my_pattern, their_pattern)):
            if turn >= line.TURNS:
                break
            if (hits >> turn) & 1:
                my_hp = max(0, my_hp - their_attack)
            else:
                their_hp = max(0, their_hp - my_attack)
            if not my_hp or not their_hp:
                break
        # Same transcript policy as replay: initiator wins an equal-HP end.
        outcome = int(their_hp >= my_hp)
        return DMCDevice(self.digimon, magic=line.MAGIC,
                         operation_offset=line.OPERATION_OFFSET,
                         trailer=my_selector, limits=line).generate_packet2(operation, outcome, hits)

    @staticmethod
    def _their_hits(packet):
        """The 5-bit hit pattern out of a DMX packet 6.

        `Check(4) | COU(3) | Hits(5) | EOL(4)`, so the top hit bit is the low
        bit of byte 0 and the rest are the top nibble of byte 1 -- the same
        expression `_simulate_dmx_turns` reads it with.
        """
        if len(packet) < 2:
            return None
        return ((packet[0] & 0x1) << 4) | ((packet[1] >> 4) & 0xF)

    # ------------------------------------------------------------------
    # What came of it
    # ------------------------------------------------------------------

    def validate(self):
        """Whether what they sent is a well-formed exchange on this wire."""
        if self.aborted or len(self.received) != self.packet_count:
            return False
        return bool(self.simulator._validate_packets(self.received))

    def opponent(self):
        """The Digimon they presented, or None."""
        return self.simulator.parse_opponent(
            [p.hex().upper() for p in self.received[:self.packet_count]],
            self.digimon)

    def result(self):
        """The finished battle, or None if the exchange did not complete."""
        if not self.complete or self.aborted or not self.validate():
            return None
        opponent = self.opponent()
        if opponent is None:
            return None
        return self.simulator.build_result(
            self.digimon, opponent, list(self.sent[:self.packet_count]),
            [p.hex().upper() for p in self.received[:self.packet_count]])

    # ------------------------------------------------------------------
    # Carrying it
    # ------------------------------------------------------------------

    def command(self, packets=None):
        """Our packets as a DigiROM command string.

        The same string a DCom cable would carry, so a pipe that speaks
        DigiROMs -- the WiFiCom does -- needs no format of its own.

        Built here rather than through `build_command`, which substitutes the
        adapter operators (`^1^FE`, `^3`) into the packets that depend on the
        other side. Those are an instruction *to an adapter*, and there is no
        adapter on this pipe: `_resolve` has already worked the same packets
        out from what actually arrived, so sending the placeholder would
        replace a real packet with a request to compute one.
        """
        chosen = list(packets if packets is not None else self.sent)
        op = getattr(self.wire, "DCOM_OP", protocol_constants.DCOM_OP)
        return "%s%d-" % (op, self.turn) + "-".join(
            packet.hex().upper() for packet in chosen)

    @staticmethod
    def cable_opens(battle_format):
        """Role expressible by stock DigiROM firmware without a host callback.

        Let the device declare its verdict/hits. Fought Colour puts them in
        the responder's packet, every other supported format in the opener's.
        """
        return protocol_constants.fights_its_battle(battle_format)

    def cable_command(self):
        if self.opens != self.cable_opens(self.battle_format):
            raise ValueError('This cable role needs an adapter with packet callbacks')
        return self.simulator.build_command(self._planned, self.turn)

    @classmethod
    def from_transcript(cls, battle_format, digimon, sent, received, simulator=None):
        """Adopt an adapter's actual s:/r: packets without rolling anything."""
        from battle.sim.dcom_battle_simulator import DComBattleSimulator
        result = cls.__new__(cls)
        result.battle_format = protocol_constants.canonical_format(battle_format)
        result.digimon = digimon
        result.simulator = simulator or DComBattleSimulator(None, battle_format=battle_format)
        result.wire = result.simulator.wire
        result.sent = result.simulator._join_wire_groups(list(sent))
        result.received = result.simulator._join_wire_groups([
            bytes.fromhex(p) if isinstance(p, str) else p for p in received])
        result._planned = result.sent
        result.aborted, result.peer = False, False
        wire = result.wire.NAME
        if wire == 'DMC':
            identity = result.simulator._colour_words(result.sent[0]) if result.sent else None
            result.opens = bool(identity and identity[2] == result.simulator.colour_operations()[0])
        elif wire in ('DM20', 'PEN20', 'DMX'):
            index = 2 if wire == 'DM20' else 0
            result.opens = bool(len(result.sent) > index and result.sent[index][0] & 128)
        else:
            result.opens = bool(result.simulator.opening)
        result.turn = 1 if result.opens else 2
        result.simulator.opening = result.opens
        # These are already materialized by the adapter, not its templates.
        result.simulator.sent_computed_final = False
        result.simulator.sent_echoed_outcome = False
        result.simulator.sent_echoed_version = False
        return result


def simulate_exchange(battle_format, device1, device2):
    """Drive both endpoints locally, then use the cable transcript replay.

    Device 1 opens. Reading the responder's view preserves the local API's
    device1/device2 convention because DCom results put the opponent first.
    """
    import copy
    first = PacketExchange(battle_format, copy.deepcopy(device1), opens=True)
    second = PacketExchange(battle_format, copy.deepcopy(device2), opens=False)
    for _ in range(first.packet_count):
        second.receive(first.next_packet())
        first.receive(second.next_packet())
    result = second.result()
    if result is None:
        raise ValueError(f"Invalid {battle_format} battle transcript")
    # Optional rosters are for presentation; restore the known local names.
    result.device1_final[0].name = device1.name
    result.device2_final[0].name = device2.name
    for turn in result.battle_log:
        turn.device1_status[0].name = device1.name
        turn.device2_status[0].name = device2.name
    return result
