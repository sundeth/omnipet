import struct
import random
import os
import sys

# Add project root to path for imports when running directly
if __name__ == "__main__":
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

try:
    from battle_utils import get_attack_pattern, get_attack_damage
    from battle_utils import get_dm20_attack_pattern, get_dm20_single_battle_attack_pattern
    from models import *
    import protocol_constants
except ImportError:
    # Absolute imports for direct testing
    from battle.sim.battle_utils import get_attack_pattern, get_attack_damage
    from battle.sim.battle_utils import get_dm20_attack_pattern, get_dm20_single_battle_attack_pattern
    from battle.sim.models import *
    from battle.sim import protocol_constants


def log(message=""):
    """Write a protocol trace line to the game console, or stdout standalone.

    The battle and packet dumps used bare ``print``, so they only ever reached
    stdout -- never ``logs/omnipet_*.log``, which is where a DCom exchange has
    to be readable after the fact. Everything routed through here lands in
    both.
    """
    try:
        from core import runtime_globals
        runtime_globals.game_console.log(message)
    except Exception:
        print(message)


class BattleSimulator:
    """Packet-accurate simulator for the real device protocols.

    Protocol constants and documented packet layouts live in
    ``protocol_constants``; the DCom exchange path is the tested reference.
    """

    # BattleProtocol enum -> constants class in protocol_constants
    PROTOCOL_CONSTANTS = {
        BattleProtocol.DMOG_BS: protocol_constants.DMOG,
        BattleProtocol.PENOG_BS: protocol_constants.PENOG,
        BattleProtocol.DMC_BS: protocol_constants.DMC,
        BattleProtocol.DM20_BS: protocol_constants.DM20,
        BattleProtocol.DMX_BS: protocol_constants.DMX,
        BattleProtocol.PEN20_BS: protocol_constants.PEN20,
    }

    def __init__(self, protocol: BattleProtocol, verbose: bool = False,
                 battle_format: str = None):
        """
        Initialize BattleSimulator with protocol.

        Args:
            protocol: BattleProtocol enum value
            verbose: Print packet dumps and battle logs to stdout (debug/tests)
        """
        self.protocol = protocol
        self.constants = self.PROTOCOL_CONSTANTS.get(protocol, protocol_constants.DM20)
        self.protocol_name = self.constants.NAME
        # Which device line is being fought, where that is finer than the
        # protocol: PENZ and DMX both resolve to DMX_BS, but a Pendulum Z
        # reads the level->pattern table a row lower. Defaults to the
        # protocol's own name, which is what every caller meant before.
        self.battle_format = battle_format or self.constants.NAME
        self.verbose = verbose

    def simulate(self, device1: Digimon, device2: Digimon) -> BattleResult:
        """
        Simulate a battle using the protocol's packet exchange.
        """
        log(f"[BattleSimulator] Using protocol: {self.constants.DISPLAY_NAME}")

        from battle.sim.exchange import simulate_exchange
        result = simulate_exchange(self.battle_format, device1, device2)

        # Always logged: `log` writes to the game console, which is itself
        # gated on the player's debug setting, so this is the packet trace a
        # DCom or versus battle can be diagnosed from afterwards.
        self.print_battle_log(result)
        self.print_dcom_code(result)
        return result
    
    def print_battle_log(self, result):
        """Dump the whole battle, turn by turn, plus both sides' packets."""
        log(f"Winner: {result.winner}")

        # Print final states of both devices
        log("Device 1:")
        for i, status in enumerate(result.device1_final):
            log(f"  {i}: {status.name} (HP: {status.hp}, Alive: {status.alive})")
        log("Device 2:")
        for i, status in enumerate(result.device2_final):
            log(f"  {i}: {status.name} (HP: {status.hp}, Alive: {status.alive})")
        log()

        # Iterate through the battle log
        for turn_data in result.battle_log:
            log(f"Turn {turn_data.turn}")

            # Device 1 attacks
            log(" Device 1 attacks:")
            for attack in turn_data.attacks:
                if attack.device == "device1":
                    attacker_name = result.device1_final[attack.attacker].name
                    defender_name = result.device2_final[attack.defender].name if attack.defender >= 0 else "?"
                    log(f"   {attacker_name} -> {defender_name}: hit={attack.hit} dmg={attack.damage} crit={attack.critical}")

            # Device 2 attacks
            log(" Device 2 attacks:")
            for attack in turn_data.attacks:
                if attack.device == "device2":
                    attacker_name = result.device2_final[attack.attacker].name
                    defender_name = result.device1_final[attack.defender].name if attack.defender >= 0 else "?"
                    log(f"   {attacker_name} -> {defender_name}: hit={attack.hit} dmg={attack.damage} crit={attack.critical}")

            # Print status of both devices
            device1_status = [f"{status.name}({status.hp})" for status in turn_data.device1_status]
            device2_status = [f"{status.name}({status.hp})" for status in turn_data.device2_status]
            log(f" Device 1 status: {device1_status}")
            log(f" Device 2 status: {device2_status}")
            log()

        # Print exchanged packet data
        log("Exchanged Packet Data:")
        log("Device 1 Packets:")
        for i, packet in enumerate(result.device1_packets):
            self._print_packet(i, packet)

        log("Device 2 Packets:")
        for i, packet in enumerate(result.device2_packets):
            self._print_packet(i, packet)

    def _print_packet(self, index, packet):
        """
        Helper method to log a single packet in binary and hexadecimal formats.
        Handles different packet formats (bytes, list of bytes, hex string).
        """
        if isinstance(packet, str):
            # Packets received from a DCom arrive as hex strings.
            try:
                packet = bytes.fromhex(packet)
            except ValueError:
                log(f"  Packet {index + 1}: Invalid hex: {packet}")
                return
        elif isinstance(packet, list):
            packet = b"".join(packet)

        if isinstance(packet, (bytes, bytearray)):
            binary = " ".join(f"{byte:08b}" for byte in packet)
            hex_representation = " ".join(f"{byte:02X}" for byte in packet)
            log(f"  Packet {index + 1}:")
            log(f"    Binary: {binary}")
            log(f"    Hex: {hex_representation}")
        else:
            log(f"  Packet {index + 1}: Invalid packet type: {type(packet)}")

    @staticmethod
    def _packet_hex(packet) -> str:
        """One packet as uppercase hex, whatever shape it arrived in."""
        if isinstance(packet, str):
            return packet.upper()
        if isinstance(packet, (bytes, bytearray)):
            return bytes(packet).hex().upper()
        if isinstance(packet, list):
            return b"".join(packet).hex().upper()
        return "0000"

    def print_dcom_code(self, result: BattleResult):
        """
        Logs the battle packets in DCom validator format:
        r:XXXX s:XXXX r:XXXX s:XXXX ... t

        Alternates between device1 (r:) and device2 (s:) packets.
        """
        parts = []

        # Determine the maximum number of packets
        max_packets = max(len(result.device1_packets), len(result.device2_packets))

        for i in range(max_packets):
            if i < len(result.device1_packets):
                parts.append(f"r:{self._packet_hex(result.device1_packets[i])}")
            if i < len(result.device2_packets):
                parts.append(f"s:{self._packet_hex(result.device2_packets[i])}")

        # Join all parts and add terminator
        log("[DCom Validator Format]")
        log(" ".join(parts) + " t")

    def _get_dm_slot_from_power(self, power: int) -> tuple:
        """
        Map power level to DM slot (A-L).
        Based on original Digital Monster slot system.
        
        Returns:
            Tuple of (slot_letter, slot_index) where slot_index is 0-11 (A=0, L=11)
        """
        # Power to slot mapping based on documentation
        if power <= 10:
            return ('A', 0)
        elif power <= 15:
            return ('B', 1)
        elif power <= 20:
            return ('C', 2)
        elif power <= 25:
            return ('D', 3)
        elif power <= 30:
            return ('E', 4)
        elif power <= 35:
            return ('F', 5)
        elif power <= 40:
            return ('G', 6)
        elif power <= 45:
            return ('H', 7)
        elif power <= 50:
            return ('I', 8)
        elif power <= 55:
            return ('J', 9)
        elif power <= 59:
            return ('K', 10)
        else:  # 60+
            return ('L', 11)

    def _get_dm_win_probability(self, my_slot_index: int, opponent_slot_index: int, my_boost: int = 0, opponent_boost: int = 0) -> int:
        """Chance out of 16 for a Digital Monster slot matchup.

        The table itself lives on `protocol_constants.DMOG` beside the
        power->slot bands it keys on, so the versus path here and the DCom
        path read the same twelve rows -- the same move `POWER_TO_SLOT` made
        when both needed it.
        """
        return protocol_constants.DMOG.slot_win_odds(
            my_slot_index, opponent_slot_index, my_boost, opponent_boost)





    
    
    
class DMCDevice:
    """
    A Digimon Color device on the DMC wire: two 16-byte packets.

    This *is* what a real Color device is sent. The document specifies it in
    full -- "Digital Monster Color Battle System", extracted by cyanic -- and
    both of its worked examples are reproduced byte for byte by
    tests/test_battle_protocols.py. An earlier note here claimed a DCom
    battle on DMC went out over the DMX 6-packet wire; it did, and that is
    why a real Pendulum Color never answered one.
    """
    def __init__(self, data: Digimon, magic: int = None,
                 operation_offset: int = 0, trailer: int = 0, limits=None):
        self.magic = magic
        self.operation_offset = operation_offset
        self.trailer = trailer
        #: Which Colour format this side is fighting as. Only the outcome
        #: reads it -- the packet fields are already described by the three
        #: arguments above -- but a Pendulum Color spends 10 on the attribute
        #: where a Digital Monster Color spends 5, and taking DMC's constant
        #: whatever the format made every PENC versus battle fight as a DMC.
        self.limits = limits or protocol_constants.DMC
        #: What this side declares in packet 2 when it holds the result. On
        #: the Colour line that is the INITIATOR for a Digital Monster Color
        #: and the RESPONDER for a Pendulum Color -- see
        #: `battle_utils.penc_result_from_wire`.
        self.declared_outcome = 0
        self.declared_hits = 0
        self.data = data
        self.hp = self.data.hp
        self.power = self.data.power
        self.attribute = self.data.attribute
        self.index = self.data.index
        self.shot = self.data.shot1
        self.packet_index = 0
        self.received_packets = []  # Store received packets

    def generate_packet1(self, operation):
        return DMCBSPacket(
            operation=operation,
            index=self.index,
            power=self.power,
            attribute=self.attribute,
            shot=self.shot,
            outcome=0,
            magic=self.magic,
            version=getattr(self.data, 'version', 0),
            operation_offset=self.operation_offset,
            trailer=self.trailer,
        ).build_packet1()

    def generate_packet2(self, operation, outcome, hits=0):
        return DMCBSPacket(
            operation=operation,
            index=self.index,
            power=self.power,
            attribute=self.attribute,
            shot=self.shot,
            outcome=outcome,
            hits=hits,
            magic=self.magic,
            version=getattr(self.data, 'version', 0),
            operation_offset=self.operation_offset,
            trailer=self.trailer,
        ).build_packet2()

    def generate_all_packets(self, order: int = 0, outcome: int = 0) -> list:
        """The two packets this side sends, in the order the document gives.

        "0 - Player 1 Digimon Data, 1 - Player 2 Digimon Data, 2 - Player 1
        Battle Data, 3 - Player 2 Battle Data. All four operations will be
        used during a code exchange, in the above order for each packet." So
        player 1 sends 0 then 2, player 2 sends 1 then 3 -- which side we are
        follows who opened the exchange, the same rule the Order bit carries
        on the other wires.

        "Only Operation 2 will report the victory, Operation 3 sends 0
        regardless of a loss or victory", so a player 2 battle packet always
        carries outcome 0.
        """
        player_one = order == 1
        #: **Which side reports the result is not the same on both Colour
        #: lines.** A Digital Monster Color puts it in operation 2, the
        #: initiator's -- "only Operation 2 will report the victory,
        #: Operation 3 sends 0 regardless". A Pendulum Color puts it in
        #: operation 0x13, the RESPONDER's, which is what the filmed battles
        #: show; forcing a zero there is what told fourteen real devices that
        #: the initiator lost and missed every round.
        penc = protocol_constants.fights_its_battle(
            getattr(self.limits, "NAME", ""))
        reports = (not player_one) if penc else player_one
        return [
            self.generate_packet1(0 if player_one else 1),
            self.generate_packet2(2 if player_one else 3,
                                  outcome if reports else 0,
                                  self.declared_hits if reports else 0),
        ]

    def process_packet(self, packet):
        """
        Processes an incoming packet and stores it for later use.
        """
        self.received_packets.append(packet)

    def calculate_outcome(self, opponent):
        """
        Calculates the battle outcome based on the exchanged data.
        """
        # Both lines' manuals give the formula outright: "hitrate =
        # ((playerPower * 100)/(playerPower + opponentPower)) +
        # attributeAdvantage". The cycle is written in the Colour line's own
        # attribute encoding (Free 0, Virus 1, Data 2, Vaccine 3), so it does
        # not read like the one every other wire uses -- which is why it is
        # `ATTRIBUTE_BEATS` on the format rather than the shared default.
        #
        # **The two lines differ in what the triangle is worth**: 10 on a
        # Pendulum Color, 5 on a Digital Monster Color, and PENC's own manual
        # says a Pendulum Color fighting a DMC drops to the DMC's 5. Reading
        # `protocol_constants.DMC` literally here fought every PENC versus
        # battle at 5, which is the compatibility-mode value on a battle that
        # is not in compatibility mode.
        hitrate = protocol_constants.hit_rate(
            self.limits, self.power, self.attribute,
            opponent.power, opponent.attribute)

        # One roll settles it: this wire exchanges a verdict, not a round of
        # hits, so the whole battle is this single hit landing or not.
        attack_roll = random.randint(0, 99)
        return 1 if attack_roll < hitrate else 0  # 1 = win, 0 = lose


class DMDevice:
    """
    Represents a Digimon device in the original DM (Digital Monster) protocol.
    Uses slot-based battle system with 2 packets containing mirrored bits.
    """
    
    # A pet native to this line already HAS a slot: every DM module version
    # lists the twelve battling Digimon at indices 2..13 in the chart order
    # the document gives, so the slot is just the index shifted up by one.
    # Checked across all six versions -- v1 is Agumon(A) .. Monzaemon(L),
    # exactly the guidebook table.
    #
    # A pet from any other module has no place on that chart, and no source
    # says what a modern device sends for one. The Pendulum answers with a
    # flat slot L, but a real DMX in old-device mode sent 0xA, so that is not
    # a general rule -- and until more devices are captured the power bands
    # below stand in. They are OURS, not the device's: consistent enough to
    # battle with, and the first thing to revisit when there is data.
    #: The bands themselves live on the protocol constants, where the rest of
    #: the slot chart is and where the adventure-mode pattern table can read
    #: them too.
    POWER_TO_SLOT = protocol_constants.DMOG.POWER_TO_SLOT
    
    def __init__(self, digimon: Digimon):
        self.digimon = digimon
        self.power = digimon.power
        self.boost = min(4, max(0, digimon.mini_game if digimon.mini_game else 0))  # 0-4 from pills
        self.slot = self._get_slot(digimon)
        #: Whatever pet_to_digimon resolved: an OEM pet's own
        #: ``device_version``, clamped to the range this wire declares, and
        #: DMOG.COMPATIBILITY_VERSION for an outsider. This used to be a
        #: hardcoded 1, so every DMOG battle announced Ver.1 whichever
        #: Digital Monster the player was actually raising -- and version is
        #: what a device reads to decide whether cross-version content
        #: should open.
        self.version = int(getattr(digimon, 'version', 1) or 0)

    @classmethod
    def _get_slot(cls, digimon: Digimon) -> int:
        """The slot this Digimon occupies, preferring its real one."""
        limits = protocol_constants.DMOG
        index = getattr(digimon, 'index', 0) or 0
        if limits.FIRST_SLOT_INDEX <= index <= limits.LAST_SLOT_INDEX:
            # Native to this line: the chart position it actually holds.
            return index + limits.SLOT_INDEX_OFFSET
        # Off the chart, so it is placed by power -- on the scale its own
        # roster uses. A native pet is already on the device's 0-60 range; a
        # pet from any other module is not, and is rescaled.
        oem = not getattr(digimon, 'compatibility', False)
        return cls._get_slot_from_power(digimon.power, oem=oem)

    @classmethod
    def _get_slot_from_power(cls, power: int, oem: bool = False) -> int:
        """Convert power to slot hex value (3-E)."""
        return protocol_constants.DMOG.slot_for_power(power, oem=oem)
    
    def _mirror_bits(self, value: int, bits: int = 4) -> int:
        """Mirror/invert bits of a value."""
        return (~value) & ((1 << bits) - 1)
    
    def generate_packet1(self) -> bytes:
        """
        Generate Packet 1: Digimon Data
        Format: [boost_mirror(4) | slot_mirror(4)] [boost(4) | slot(4)]
        """
        boost_mirror = self._mirror_bits(self.boost)
        slot_mirror = self._mirror_bits(self.slot)
        
        byte1 = (boost_mirror << 4) | slot_mirror
        byte2 = (self.boost << 4) | self.slot
        
        return struct.pack(">BB", byte1, byte2)
    
    def generate_packet2(self, outcome: int = 0) -> bytes:
        """
        Generate Packet 2: Battle Result
        Format: [version_mirror(4) | outcome_mirror(4)] [version(4) | outcome(4)]
        
        Args:
            outcome: 0 = not yet determined, 1 = victory, 2 = defeat
        """
        version_mirror = self._mirror_bits(self.version)
        outcome_mirror = self._mirror_bits(outcome)
        
        byte1 = (version_mirror << 4) | outcome_mirror
        byte2 = (self.version << 4) | outcome
        
        return struct.pack(">BB", byte1, byte2)
    
    def generate_all_packets(self, outcome: int = None) -> list:
        """Both packets for the DMOG wire.

        The outcome is never 0. The document allows exactly two values --
        "1 means victory while 2 means defeat" -- and 0 is neither, which is
        what every DMOG code we sent used to carry. When we answer rather
        than open the exchange the adapter overwrites this digit with the
        opposite of the device's (DMOG.DCOM_OUTCOME_ECHO); the literal here
        is what goes out when we open, and defeat is the honest default,
        since opening means declaring a result we have not earned.
        """
        if outcome is None:
            outcome = protocol_constants.DMOG.OUTCOME_DEFEAT
        return [
            self.generate_packet1(),
            self.generate_packet2(outcome)
        ]
    
    @staticmethod
    def parse_packet1(data: bytes) -> dict:
        """Parse opponent's Packet 1."""
        if len(data) < 2:
            return None
        byte1, byte2 = struct.unpack(">BB", data[:2])
        boost = (byte2 >> 4) & 0x0F
        slot = byte2 & 0x0F
        return {'boost': boost, 'slot': slot}
    
    @staticmethod
    def parse_packet2(data: bytes) -> dict:
        """Parse opponent's Packet 2."""
        if len(data) < 2:
            return None
        byte1, byte2 = struct.unpack(">BB", data[:2])
        version = (byte2 >> 4) & 0x0F
        outcome = byte2 & 0x0F
        return {'version': version, 'outcome': outcome}

    
class PENOGDevice:
    """The original Digimon Pendulum's own battle signal -- four packets.

    Layout, field meanings and the EOL/checksum quirks are documented in
    ``protocol_constants.PENOG``. Everything here reproduces the protocol
    document's worked example (an Ikkakumon from Pendulum 2.0) and both of
    wificom's known-good punchbag codes byte for byte.

    Unlike the Digital Monster's slot system this exchanges a real battle:
    each side sends its own five-round Hits pattern and its own Attack
    pattern saying which of those rounds are strong, and the two are read
    against 3 HP a side.
    """

    #: Packet 3's second field is 4 on every code on record -- the document's
    #: example, both wificom punchbags and both DigiROM battle codes.
    COU_PACKET3 = protocol_constants.PENOG.PACKET3_COU

    def __init__(self, digimon: Digimon):
        self.digimon = digimon
        self.sick = digimon.sick
        self.shot = digimon.shot1
        self.own_packets = []

        limits = protocol_constants.PENOG
        # Effort is the Pendulum's own hidden training stat, 0-40, and the
        # only strength figure this wire carries -- there is no Power field.
        self.effort = max(0, min(limits.MAX_EFFORT,
                                 int(getattr(digimon, 'effort', 0) or 0)))
        self.slot = self._get_slot(digimon)

    @classmethod
    def _get_slot(cls, digimon: Digimon) -> int:
        """The chart slot this Digimon occupies.

        A pet native to the line has it already: the module lists its
        battling Digimon in chart order -- stage, then Vaccine/Data/Virus --
        from index 2, and the real jogress codes label those same slots
        "Vaccine Adult 1" upward. So the slot is the index shifted by one.

        A pet from elsewhere has no place on that chart, and the ratios were
        never published, so it is placed by stage and attribute into the band
        the chart would give it -- the nearest thing to an honest answer, and
        marked as ours rather than the device's.
        """
        limits = protocol_constants.PENOG
        index = getattr(digimon, 'index', 0) or 0
        if limits.FIRST_SLOT_INDEX <= index <= limits.MAX_INDEX:
            return index + limits.SLOT_INDEX_OFFSET

        # Ours: the chart puts three Child slots first, then two per
        # attribute per stage in Vaccine, Data, Virus order.
        stage = max(3, min(6, getattr(digimon, 'stage', 4) or 4))
        attribute = min(2, max(0, getattr(digimon, 'attribute', 0) or 0))
        if stage <= 3:
            return limits.FIRST_SLOT + attribute
        band = min(2, stage - 4)          # Adult, Perfect, Ultimate
        return limits.FIRST_SLOT + 3 + band * 6 + attribute * 2

    def _record(self, packet: bytes) -> bytes:
        self.own_packets.append(packet)
        return packet

    def generate_packet1(self, version, operation=0,
                         eol=protocol_constants.PENOG.EOL) -> bytes:
        """COU(1) Version(3) Sick(1) Operation(1) COU(1) Slot(5) EOL(4)."""
        word = (((version & 0x7) << 12)
                | ((self.sick & 0x1) << 11)
                | ((operation & 0x1) << 10)
                | ((self.slot & 0x1F) << 4)
                | (eol & 0xF))
        return self._record(struct.pack(">H", word))

    def generate_packet2(self, attack,
                         eol=protocol_constants.PENOG.EOL) -> bytes:
        """Effort_2(4) Effort_1(3) Attack(5) EOL(4).

        Effort is split into digits: Effort_1 the tens, Effort_2 the units,
        so an effort of 40 goes out as 4 and 0.
        """
        tens, units = divmod(self.effort, 10)
        word = (((units & 0xF) << 12)
                | ((tens & 0x7) << 9)
                | ((attack & 0x1F) << 4)
                | (eol & 0xF))
        return self._record(struct.pack(">H", word))

    def generate_packet3(self, hits, eol=protocol_constants.PENOG.EOL) -> bytes:
        """COU(4) COU(3) Hits(5) EOL(4) -- our own hits, one side only."""
        word = (((self.COU_PACKET3 & 0x7) << 9)
                | ((hits & 0x1F) << 4)
                | (eol & 0xF))
        return self._record(struct.pack(">H", word))

    def generate_packet4(self, eol=protocol_constants.PENOG.EOL) -> bytes:
        """Check(4) Shot(8) EOL(4).

        The Check nibble brings the nibble sum of the whole signal to a
        remainder of 11.
        """
        shot = self.shot & 0xFF
        checksum = 0
        for packet in self.own_packets[:3]:
            for byte in packet:
                checksum += (byte >> 4) & 0xF
                checksum += byte & 0xF
        checksum += (shot >> 4) & 0xF
        checksum += shot & 0xF
        checksum += eol & 0xF
        check = (protocol_constants.PENOG.CHECKSUM_REMAINDER - checksum) % 16
        word = ((check & 0xF) << 12) | (shot << 4) | (eol & 0xF)
        return self._record(struct.pack(">H", word))

    def generate_all_packets(self, version=None, attack=None, hits=None,
                             operation=0,
                             eol=protocol_constants.PENOG.EOL) -> list:
        """The four packets, in order.

        *attack* and *hits* are five-bit patterns read right to left, one bit
        per round. Left unset, the attack pattern comes from the charge and
        every round is claimed as a hit -- which is all a pre-built packet can
        say, since this wire is opened rather than answered and there is no
        reply to derive anything from.
        """
        limits = protocol_constants.PENOG
        self.own_packets = []
        if version is None:
            version = getattr(self.digimon, 'version', limits.DEFAULT_VERSION)
            v_min, v_max = limits.VERSION_RANGE
            version = max(v_min, min(v_max, int(version or 0)))
        if attack is None:
            attack = self.attack_pattern(
                getattr(self.digimon, 'mini_game', 0))
        if hits is None:
            hits = 0  # Template only: PacketExchange resolves after slot/effort arrive.
        return [
            self.generate_packet1(version, operation, eol),
            self.generate_packet2(attack, eol),
            self.generate_packet3(hits, eol),
            self.generate_packet4(eol),
        ]

    @staticmethod
    def attack_pattern(charge: int) -> int:
        """The five-round Attack field a charge is worth, as wire bits.

        Read right to left, one bit per round: set is a strong shot for 2
        damage, clear a weak one for 1. The rows live in
        data/attack_patterns/PENOG.json, one per effort level -- see
        ``battle_utils.get_penog_pattern`` for where they come from.

        The charge is the **raw shake meter, 0-14**, not the banded 0-3
        quality -- see PENOG.CHARGE_SCALE for why that band threw most of a
        played charge away before it reached the packet.
        """
        from battle.sim.battle_utils import get_penog_pattern
        bits = 0
        for turn, damage in enumerate(get_penog_pattern(charge)):
            if damage >= 2:
                bits |= 1 << turn
        return bits & ((1 << protocol_constants.PENOG.TURNS) - 1)

    @staticmethod
    def hits_pattern(rate: float) -> int:
        """Roll five PENOG hits at an explicit rate from the protocol slot model."""
        limits = protocol_constants.PENOG
        bits = 0
        for turn in range(limits.TURNS):
            if random.randint(1, 100) <= rate:
                bits |= 1 << turn
        return bits

    # ------------------------------------------------------------------
    # Reading the other side
    # ------------------------------------------------------------------

    @staticmethod
    def parse_packet1(data: bytes) -> dict:
        if len(data) < 2:
            return None
        word = struct.unpack(">H", data[:2])[0]
        return {
            'version': (word >> 12) & 0x7,
            'sick': (word >> 11) & 0x1,
            'operation': (word >> 10) & 0x1,
            'slot': (word >> 4) & 0x1F,
            'eol': word & 0xF,
        }

    @staticmethod
    def parse_packet2(data: bytes) -> dict:
        if len(data) < 2:
            return None
        word = struct.unpack(">H", data[:2])[0]
        units = (word >> 12) & 0xF
        tens = (word >> 9) & 0x7
        return {
            'effort': tens * 10 + units,
            'attack': (word >> 4) & 0x1F,
            'eol': word & 0xF,
        }

    @staticmethod
    def parse_packet3(data: bytes) -> dict:
        if len(data) < 2:
            return None
        word = struct.unpack(">H", data[:2])[0]
        return {'hits': (word >> 4) & 0x1F, 'eol': word & 0xF}

    @staticmethod
    def parse_packet4(data: bytes) -> dict:
        if len(data) < 2:
            return None
        word = struct.unpack(">H", data[:2])[0]
        return {
            'check': (word >> 12) & 0xF,
            'shot': (word >> 4) & 0xFF,
            'eol': word & 0xF,
        }


class DM20Device:
    """
    Represents a Digimon device in the DM20_BS protocol.
    Handles packet generation, processing, and state management.
    Uses protocol definition for constants.
    """
    def __init__(self, digimon: Digimon):
        self.digimon = digimon
        self.hp = digimon.hp
        self.power = digimon.power
        self.attribute = digimon.attribute
        self.index = digimon.index
        self.shot1 = digimon.shot1
        self.shot2 = digimon.shot2
        self.tag_meter = digimon.tag_meter  # Use the tag_meter attribute from the Digimon class
        self.packets = []  # Stores packets received from the opponent
        self.opponent_data = []  # Store opponent's data
        self.own_packets = []  # Track our own sent packets for checksum calculation

    def generate_packet1(self):
        """
        Generates Packet 1: Name 2, Name 1.
        """
        tamer_name = ["O", "M", "N", "I"]
        packet = struct.pack(">BB", ord(tamer_name[1]), ord(tamer_name[0]))
        self.own_packets.append(packet)
        return packet

    def generate_packet2(self):
        """
        Generates Packet 2: Name 4, Name 3.
        """
        tamer_name = ["O", "M", "N", "I"]
        packet = struct.pack(">BB", ord(tamer_name[3]), ord(tamer_name[2]))
        self.own_packets.append(packet)
        return packet

    def generate_packet3(self, order, version, eol):
        """
        Generates Packet 3: Order | Attack (pattern index) | Operation | Version | EOL
        Packet 3: 1 bit Order, 5 bits Attack, 2 bits Operation, 4 bits Version, 4 bits EOL
        Binary: O AAAAA OO VVVV EEEE
        """
        # Convert minigame taps to pattern index
        from battle.sim.battle_utils import get_dm20_pattern_index_from_taps
        pattern_index = get_dm20_pattern_index_from_taps(self.digimon.mini_game)
        
        operation = 0b00  # Single Battle (2 bits)
        # Pack across bytes: O AAAAA OO VVVV EEEE
        byte1 = (order << 7) | (pattern_index << 2) | operation
        byte2 = (version << 4) | eol
        packet = struct.pack(">BB", byte1, byte2)
        self.own_packets.append(packet)
        return packet

    def generate_packet4(self, cou, eol):
        """
        Generates Packet 4: COU | Index L | Attribute L | EOL
        Packet 4: 2 bits COU, 8 bits Index, 2 bits Attribute, 4 bits EOL
        Binary: CC IIIIIIII AA EEEE
        """
        # Pack across bytes: CC IIIIII II AA EEEE = CCIIIIIII IAAEEEEE -> CCIIIIII IIAAEEEE
        byte1 = (cou << 6) | (self.index >> 2)
        byte2 = ((self.index & 0x03) << 6) | (self.attribute << 4) | eol
        packet = struct.pack(">BB", byte1, byte2)
        self.own_packets.append(packet)
        return packet

    def generate_packet5(self, eol):
        """
        Generates Packet 5: Shot S L | Shot W L | EOL
        Packet 5: 6 bits Shot S, 6 bits Shot W, 4 bits EOL
        Binary: SSSSSS WWWWWW EEEE
        """
        # Pack across bytes: SSSSSS WW WWWW EEEE = SSSSSSW W WWWWEEEE -> SSSSSSWW WWWWEEEE
        byte1 = (self.shot1 << 2) | (self.shot2 >> 4)
        byte2 = ((self.shot2 & 0x0F) << 4) | eol
        packet = struct.pack(">BB", byte1, byte2)
        self.own_packets.append(packet)
        return packet

    def generate_packet6(self, cou, eol):
        """
        Generates Packet 6: COU | Power L | EOL
        Packet 6: 4 bits COU, 8 bits Power, 4 bits EOL
        Binary: CCCC PPPPPPPP EEEE
        """
        # Pack across bytes: CCCC PPPP PPPP EEEE = CCCCPPPP PPPPEEEE
        byte1 = (cou << 4) | (self.power >> 4)
        byte2 = ((self.power & 0x0F) << 4) | eol
        packet = struct.pack(">BB", byte1, byte2)
        self.own_packets.append(packet)
        return packet

    def generate_packet7(self, cou, eol):
        """
        Generates Packet 7: COU | Index R | Attribute R | EOL
        For single battles, R values are 0
        """
        index_r = 0
        attribute_r = 0
        byte1 = (cou << 6) | (index_r >> 2)
        byte2 = ((index_r & 0x03) << 6) | (attribute_r << 4) | eol
        packet = struct.pack(">BB", byte1, byte2)
        self.own_packets.append(packet)
        return packet

    def generate_packet8(self, eol):
        """
        Generates Packet 8: Shot S R | Shot W R | EOL
        For single battles, R values are 0
        """
        shot_s_r = 0
        shot_w_r = 0
        byte1 = (shot_s_r << 2) | (shot_w_r >> 4)
        byte2 = ((shot_w_r & 0x0F) << 4) | eol
        packet = struct.pack(">BB", byte1, byte2)
        self.own_packets.append(packet)
        return packet

    def generate_packet9(self, eol):
        """
        Generates Packet 9: Tag Meter | Power R | EOL
        Packet 9: 4 bits Tag Meter, 8 bits Power R, 4 bits EOL
        For single battles, Power R is 0
        """
        tag_meter = self.digimon.tag_meter
        power_r = 0
        byte1 = (tag_meter << 4) | (power_r >> 4)
        byte2 = ((power_r & 0x0F) << 4) | eol
        packet = struct.pack(">BB", byte1, byte2)
        self.own_packets.append(packet)
        return packet

    def process_packet(self, packet):
        """
        Processes an incoming packet and stores it for later use.
        """
        self.opponent_data.append(packet)

    def generate_packetA(self, eol):
        """
        Generates Packet A: Check, Dodges, Hits, EOL.
        """
        if len(self.opponent_data) < 6:
            raise ValueError("Opponent data is not available. Ensure packets are processed before generating Packet A.")

        # Opponent power and attribute, read from the packets they actually
        # live in (opponent_data[i] is packet i+1):
        #   packet 4  COU(2) | Index(8) | Attribute(2) | EOL(4)
        #   packet 6  COU(4) | Power(8) | EOL(4)
        # Both fields straddle the byte boundary, so neither is a whole byte.
        # This used to read packet 5 (the attack sprite ids) as the power and
        # packet 2 (the tamer name) as the attribute, which made the hit rate
        # a function of the opponent's sprite numbers instead of their power.
        packet4 = self.opponent_data[3]
        packet6 = self.opponent_data[5]
        opponent_attribute = (packet4[1] >> 4) & 0b11
        opponent_power = ((packet6[0] & 0x0F) << 4) | ((packet6[1] >> 4) & 0x0F)

        power = self.digimon.power

        # Attribute advantage. Vaccine beats Virus, Virus beats Data, Data
        # beats Vaccine. **On POWER, +32**, which is what the Ver.20th manual
        # says: "having an attribute advantage will effectively grant a +32
        # bonus to your Digimon's Power stat", and Power is what the hit rate
        # is a ratio of. The Pendulum Ver.20th manual repeats it word for
        # word, so both 20th lines carry it.
        #
        # This spent 5 on the ROLL instead, taken from the module rather than
        # the manual, and the module was wrong. `generate_packetA` -- which
        # decides the hits that actually go on the wire -- had always spent
        # 32 on Power, so the packet and the battle drawn from it disagreed
        # about the same rule.
        limits = protocol_constants.get_constants(
            getattr(self, "battle_format", None) or "DM20")

        # One formula for every wire -- the power ratio plus the attribute
        # triangle, spent on Power here because that is what both 20th
        # manuals say ("a +32 bonus to your Digimon's Power stat"), which is
        # what `ATTRIBUTE_ADVANTAGE_ON_POWER` selects. This used to open-code
        # the triangle and the clamp, as three other places did, so a change
        # to any of them reached only one.
        hitrate = protocol_constants.hit_rate(
            limits, power, self.digimon.attribute,
            opponent_power, opponent_attribute)

        # Initialize hits and dodges
        hits = 0
        dodges = 0

        # Calculate hits and dodges for 4 attacks
        for i in range(4):
            # Simulate hit
            attack_roll = random.randint(0, 99)
            hit = 1 if attack_roll < hitrate else 0

            # Calculate dodge (inverted for single battles)
            dodge = 1 - hit

            # Update hits and dodges bit patterns (right to left)
            hits |= (hit << i)
            dodges |= (dodge << i)

        check = self._calculate_check(hits, dodges, eol)

        # Pack the data into bytes
        return struct.pack(">B", (check << 4) | dodges) + struct.pack(">B", (hits << 4) | eol)

    def _calculate_check(self, hits, dodges, eol):
        """
        Calculates the Check value for Packet A.
        Sums all nibbles from THIS device's own packets 1-9 plus hits, dodges, EOL, 
        and finds check value that makes total % 16 == 0.
        """
        # Sum all nibbles from OUR OWN packets 1-9 (not opponent's)
        checksum = 0
        for pkt in self.own_packets[:9]:  # First 9 packets we sent
            for byte in pkt:
                checksum += (byte >> 4) & 0xF  # Upper nibble
                checksum += byte & 0xF          # Lower nibble
        
        # Add dodges, hits, and EOL nibbles
        checksum += dodges & 0xF
        checksum += hits & 0xF
        checksum += eol & 0xF
        
        # Find check value that makes (checksum + check) % 16 == 0
        check = (16 - (checksum % 16)) % 16
        return check
    
    def generate_all_packets_for_dcom(self, order=0, cou=0b00, version=None, eol=0b1110):
        """
        Generate all 10 DM20 packets for DCom battle communication.
        Uses proper checksum calculation matching the test implementation.
        Returns list of 10 packets (bytes objects).
        """
        packets = []
        
        # Generate packets 1-9
        packets.append(self.generate_packet1())
        packets.append(self.generate_packet2())
        # Determine version from digimon.version if not explicitly provided
        if version is None:
            try:
                v = int(getattr(self.digimon, 'version', 1))
            except Exception:
                v = 1
            # Clamp DM20 version to range 1..5
            v = max(1, min(5, v))
            version = v

        packets.append(self.generate_packet3(order, version, eol))
        packets.append(self.generate_packet4(cou, eol))
        packets.append(self.generate_packet5(eol))
        packets.append(self.generate_packet6(cou, eol))
        packets.append(self.generate_packet7(cou, eol))
        packets.append(self.generate_packet8(eol))
        packets.append(self.generate_packet9(eol))
        
        # Calculate proper checksum by summing all nibbles
        checksum = 0
        for pkt in packets:
            for byte in pkt:
                checksum += (byte >> 4) & 0x0F  # Upper nibble
                checksum += byte & 0x0F          # Lower nibble
        
        # Generate Packet A with proper checksum
        dodges = 0x0  # All dodge (0000)
        hits = 0xF    # All hit (1111)
        
        # Add dodges, hits, and EOL nibbles to checksum
        checksum += dodges
        checksum += hits
        checksum += eol
        
        # Find check value that makes (checksum + check) % 16 == 0
        check = (16 - (checksum % 16)) % 16
        
        byte1 = (check << 4) | dodges
        byte2 = (hits << 4) | eol
        packetA = struct.pack(">BB", byte1, byte2)
        packets.append(packetA)
        
        return packets

class DMCBSPacket:
    """
    Represents a DMC_BS packet (2 packets per exchange).
    """
    #: Default only. Each Color line opens its packets with its own four
    #: bytes -- 'GDLC' Digital Monster Color, 'GDDp' Pendulum Color, 'GDWX'
    #: Color Xros Wars -- and the caller passes the one for the line being
    #: fought. Sending the wrong word is a packet the device will not answer.
    COU = 0x47444C43  # 'GDLC', Digital Monster Color

    def __init__(self, operation: int, index: int, power: int, attribute: int, shot: int,
                 outcome: int, version: int = 0, magic: int = None,
                 operation_offset: int = 0, trailer: int = 0, hits: int = 0):
        self.operation = operation  # Operation code (0-3)
        self.index = index          # Digimon index
        self.power = power          # Digimon power
        self.attribute = attribute  # Digimon attribute (0=Free, 1=Virus, 2=Data, 3=Vaccine)
        self.shot = shot            # Attack sprite ID
        self.outcome = outcome      # Battle outcome (0=loss, 1=win)
        self.version = version      # Which version set the index belongs to
        #: Some Color lines number the four operations from a different base.
        self.operation = operation + operation_offset
        #: And some carry a value where others leave a COU half at zero.
        self.trailer = trailer
        #: Word 5 of packet 2, which the Digital Monster Color leaves at zero
        #: and a Pendulum Color fills with the **initiator's hit mask** in
        #: operation 0x13. It was hardcoded to zero here with no way to set
        #: it -- so every packet Omnipet ever sent as responder said the
        #: initiator missed every round, and the device believed it.
        self.hits = hits
        if magic is not None:
            self.COU = magic        # the device line's own opening word

    def _calc_check(self, packet_bytes: bytes) -> int:
        """
        Calculates the checksum for the packet.
        The checksum is the sum of all 16-bit fields, keeping only the lowest 16 bits.
        """
        check = 0
        for i in range(0, len(packet_bytes) - 2, 2):  # Exclude the last 2 bytes (checksum field)
            segment = int.from_bytes(packet_bytes[i:i+2], 'big')
            check += segment
        return check & 0xFFFF  # Keep only the lowest 16 bits

    def build_packet1(self) -> bytes:
        """
        Builds Packet 1 (Digimon Data Packet).
        Structure:
        COU (4 bytes) | Operation (2 bytes) | Version (2 bytes) | Index (2 bytes) |
        Power (2 bytes) | Attribute (2 bytes) | Check (2 bytes)
        """
        version = self.version
        packet = struct.pack(">IHHHHHH",
            self.COU,           # COU (4 bytes)
            self.operation,     # Operation (2 bytes)
            version,            # Version (2 bytes)
            self.index,         # Index (2 bytes)
            self.power,         # Power (2 bytes)
            self.attribute,     # Attribute (2 bytes)
            0                   # Check (placeholder, 2 bytes)
        )
        check = self._calc_check(packet)
        return struct.pack(">IHHHHHH",
            self.COU,
            self.operation,
            version,
            self.index,
            self.power,
            self.attribute,
            check                # Final checksum
        )

    def build_packet2(self) -> bytes:
        """
        Builds Packet 2 (Battle Data Packet).
        Structure:
        COU (4 bytes) | Operation (2 bytes) | Shot (2 bytes) | Outcome (2 bytes) |
        COU (4 bytes) | Check (2 bytes)
        """
        packet = struct.pack(">IHHHHHH",
            self.COU,           # COU (4 bytes)
            self.operation,     # Operation (2 bytes)
            self.shot,          # Shot (2 bytes)
            self.outcome,       # Outcome (2 bytes)
            self.hits,          # zero on the DMC; the hit mask on the PenC
            self.trailer,       # zero on the DMC; the selector on the PenC
            0                   # Check (placeholder, 2 bytes)
        )
        check = self._calc_check(packet)
        return struct.pack(">IHHHHHH",
            self.COU,
            self.operation,
            self.shot,
            self.outcome,
            self.hits,
            self.trailer,
            check                # Final checksum
        )

class PEN20Device:
    """
    Represents a Digimon device in the PEN20_BS protocol.
    Handles packet generation, processing, and state management.
    Packet layouts are documented in protocol_constants.PEN20.

    Traited and Egg Shake are sent as their own bits in packet 5, and the
    protocol document says of both that the value "does not appear to affect
    battle outcome" -- so the Power field carries the pet's power as it
    stands. It used to have a traited/egg-shake bonus added on top, which
    both contradicted that and double-counted the module's own power rule
    (already applied by get_power): the document's own 248-power example came
    out as 255.
    """

    #: COU values the protocol document's worked example carries. "Constant
    #: Or Unknown ... the same across all signals we have analyzed", so they
    #: are reproduced rather than zeroed. Only packets 5 and 9 are non-zero.
    COU_PACKET5 = 0b01
    COU_PACKET9 = 0b0011
    
    def __init__(self, digimon: Digimon):
        self.digimon = digimon
        self.hp = digimon.hp
        self.attribute = digimon.attribute
        self.index = digimon.index
        self.shot1 = digimon.shot1  # Strong shot
        self.shot2 = digimon.shot2  # Weak shot
        self.traited = digimon.traited  # Trait status (0 or 1)
        self.egg_shake = digimon.egg_shake  # Egg shake status (0 or 1)
        self.sick = digimon.sick  # Sick status
        self.stage = digimon.stage  # Evolution stage for traited bonus calculation
        self.tag_meter = digimon.tag_meter
        self.packets = []  # Stores packets received from the opponent
        self.opponent_data = []  # Store opponent's data
        self.own_packets = []  # Track our own sent packets for the checksum

        # Power goes on the wire as it stands; the Traited and Egg Shake
        # flags travel beside it in packet 5 and do not affect the outcome.
        self.power = min(255, digimon.power)

    def _record(self, packet):
        """Remember a packet we sent; the Check nibble is computed over them."""
        self.own_packets.append(packet)
        return packet

    def generate_packet1(self, order, version, eol):
        """
        Generates Packet 1: Order(1) COU(1) Attack(4) Operation(2) Version(4) EOL(4)
        
        Bit layout (16 bits total):
        Byte 1: Order(1) | COU(1) | Attack(4) | Operation(2) = 8 bits
        Byte 2: Version(4) | EOL(4) = 8 bits
        """
        attack = min(14, self.digimon.mini_game)  # Dummy minigame: 0-14 taps
        operation = 0b00  # Single Battle
        cou = 0b0  # Constant (1 bit)

        # Byte 1: Order(1) + COU(1) + Attack(4) + Operation(2)
        byte1 = (order << 7) | (cou << 6) | ((attack & 0xF) << 2) | (operation & 0x3)
        
        # Byte 2: Version(4) + EOL(4)
        byte2 = ((version & 0xF) << 4) | (eol & 0xF)
        
        return self._record(struct.pack(">BB", byte1, byte2))

    def generate_packet2(self, cou, eol):
        """
        Generates Packet 2: COU(2) Index(8) Attribute(2) EOL(4)
        
        Bit layout (16 bits total):
        Byte 1: COU(2) | Index high 6 bits = 8 bits
        Byte 2: Index low 2 bits | Attribute(2) | EOL(4) = 8 bits
        """
        index = self.index & 0xFF  # 8 bits
        # Byte 1: COU(2) + Index high 6 bits
        byte1 = ((cou & 0x3) << 6) | ((index >> 2) & 0x3F)
        # Byte 2: Index low 2 bits + Attribute(2) + EOL(4)
        byte2 = ((index & 0x3) << 6) | ((self.attribute & 0x3) << 4) | (eol & 0xF)
        return self._record(struct.pack(">BB", byte1, byte2))

    def generate_packet3(self, cou, eol):
        """
        Generates Packet 3: COU(4) Shot_W(8) EOL(4)
        
        Bit layout (16 bits total):
        Byte 1: COU(4) | Shot_W high 4 bits = 8 bits
        Byte 2: Shot_W low 4 bits | EOL(4) = 8 bits
        """
        shot_w = self.shot2 & 0xFF  # 8 bits
        byte1 = ((cou & 0xF) << 4) | ((shot_w >> 4) & 0xF)
        byte2 = ((shot_w & 0xF) << 4) | (eol & 0xF)
        return self._record(struct.pack(">BB", byte1, byte2))

    def generate_packet4(self, cou, eol):
        """
        Generates Packet 4: Sick(1) COU(3) Shot_S(8) EOL(4)
        
        Bit layout (16 bits total):
        Byte 1: Sick(1) | COU(3) | Shot_S high 4 bits = 8 bits
        Byte 2: Shot_S low 4 bits | EOL(4) = 8 bits
        """
        shot_s = self.shot1 & 0xFF  # 8 bits
        byte1 = ((self.sick & 0x1) << 7) | ((cou & 0x7) << 4) | ((shot_s >> 4) & 0xF)
        byte2 = ((shot_s & 0xF) << 4) | (eol & 0xF)
        return self._record(struct.pack(">BB", byte1, byte2))

    def generate_packet5(self, cou=None, eol=0b1110):
        """
        Generates Packet 5: COU(2) Traited(1) Egg_Shake(1) Power(8) EOL(4)
        
        Bit layout (16 bits total):
        Byte 1: COU(2) | Traited(1) | Egg_Shake(1) | Power high 4 bits = 8 bits
        Byte 2: Power low 4 bits | EOL(4) = 8 bits

        This packet's COU is 1, not 0 (see COU_PACKET5).
        """
        cou = self.COU_PACKET5 if cou is None else cou
        power = self.power & 0xFF
        byte1 = ((cou & 0x3) << 6) | ((self.traited & 0x1) << 5) | ((self.egg_shake & 0x1) << 4) | ((power >> 4) & 0xF)
        byte2 = ((power & 0xF) << 4) | (eol & 0xF)
        return self._record(struct.pack(">BB", byte1, byte2))

    def generate_packet6(self, eol):
        """
        Generates Packet 6: Copy(2) Index_R(8) Attribute_R(2) EOL(4)
        For single battles, all R values are 0.
        """
        copy = 0
        index_r = 0
        attribute_r = 0
        byte1 = ((copy & 0x3) << 6) | ((index_r >> 2) & 0x3F)
        byte2 = ((index_r & 0x3) << 6) | ((attribute_r & 0x3) << 4) | (eol & 0xF)
        return self._record(struct.pack(">BB", byte1, byte2))

    def generate_packet7(self, cou, eol):
        """
        Generates Packet 7: COU, Shot W R, EOL.
        """
        shot_w_r = 0  # For single battles, Shot W R is 0
        return self._record(struct.pack(">BB",
                                        (cou << 4) | (shot_w_r >> 4),
                                        ((shot_w_r & 0b1111) << 4) | eol))

    def generate_packet8(self, cou, eol):
        """
        Generates Packet 8: COU, Shot S R, EOL.
        """
        shot_s_r = 0  # For single battles, Shot S R is 0
        return self._record(struct.pack(">BB",
                                        (cou << 4) | (shot_s_r >> 4),
                                        ((shot_s_r & 0b1111) << 4) | eol))

    def generate_packet9(self, cou=None, eol=0b1110):
        """
        Generates Packet 9: COU(4), Power R(8), EOL(4).

        This packet's COU is 3, not 0 (see COU_PACKET9). Power R belongs to
        the right-hand Digimon of a Tag Battle and is 0 in a single battle;
        the COU is not an R value and is sent either way.
        """
        cou = self.COU_PACKET9 if cou is None else cou
        power_r = 0  # For single battles, Power R is 0
        return self._record(struct.pack(">BB",
                                        (cou << 4) | (power_r >> 4),
                                        ((power_r & 0b1111) << 4) | eol))

    def process_packet(self, packet):
        """
        Processes an incoming packet and stores it for later use.
        """
        self.opponent_data.append(packet)

    def generate_packetA(self, eol):
        """
        Generates Packet A: Check, Dodges, Hits, EOL.
        """
        if len(self.opponent_data) < 5:
            raise ValueError("Opponent data is not available. Ensure packets are processed before generating Packet A.")

        # Opponent power and attribute, read from the packets they live in on
        # the PEN20 layout (opponent_data[i] is packet i+1):
        #   packet 2  COU(2) | Index(8) | Attribute(2) | EOL(4)
        #   packet 5  COU(2) | Traited(1) | Egg_Shake(1) | Power(8) | EOL(4)
        # Both straddle the byte boundary. The attribute mask used to be 4
        # bits wide, which swept in the low bits of the index.
        packet2 = self.opponent_data[1]
        packet5 = self.opponent_data[4]
        opponent_attribute = (packet2[1] >> 4) & 0b11
        opponent_power = ((packet5[0] & 0x0F) << 4) | ((packet5[1] >> 4) & 0x0F)

        # +32 on Power, from the manual. Read off the format rather than
        # written here, so this and `_simulate_dm20_turns` cannot drift --
        # they did, and the packet's hits disagreed with the battle drawn
        # from them.
        # The same one formula the other wires use -- see DM20's packet A.
        # The default is this line's own; it read "DM20", which is harmless
        # only because both 20th lines spend the same 32 on Power.
        limits = protocol_constants.get_constants(
            getattr(self, "battle_format", None) or "PEN20")
        power = self.digimon.power
        hitrate = protocol_constants.hit_rate(
            limits, power, self.digimon.attribute,
            opponent_power, opponent_attribute)

        # Initialize hits and dodges
        hits = 0
        dodges = 0

        # Calculate hits and dodges for 4 attacks
        for i in range(4):
            # Simulate hit
            attack_roll = random.randint(0, 99)
            hit = 1 if attack_roll < hitrate else 0

            # Calculate dodge (inverted for single battles)
            dodge = 1 - hit

            # Update hits and dodges bit patterns (right to left)
            hits |= (hit << i)
            dodges |= (dodge << i)

        check = self._calculate_check(hits, dodges, eol)

        # Pack the data into bytes
        return self._record(struct.pack(">BB", (check << 4) | dodges,
                                        (hits << 4) | eol))

    def _calculate_check(self, hits, dodges, eol):
        """
        Calculates the Check value for Packet A.

        PEN20's target remainder is 12, not 0 -- "Remainder should always
        equal 12" in the protocol document, and its worked example sums to
        exactly that. The sum covers OUR OWN packets 1-9; it used to sum the
        opponent's, which is not what the Check nibble certifies.
        """
        checksum = 0
        for pkt in self.own_packets[:9]:  # First 9 packets we sent
            for byte in pkt:
                checksum += (byte >> 4) & 0xF  # Upper nibble
                checksum += byte & 0xF          # Lower nibble

        # Add dodges, hits, and EOL nibbles
        checksum += dodges & 0xF
        checksum += hits & 0xF
        checksum += eol & 0xF

        target = protocol_constants.PEN20.CHECKSUM_REMAINDER
        return (target - checksum) % 16

    def generate_all_packets_for_dcom(self, order=0, cou=0b00, version=None,
                                      eol=protocol_constants.PEN20.EOL):
        """
        Generate all 10 packets in the PEN20 *versus* format.

        NOT what a real Pendulum 20th is sent, despite the name: a DCom
        battle on PEN20 goes out over the DM20 wire (see
        protocol_constants.PEN20.DCOM_WIRE), because the two devices differ
        in the charge minigame rather than in their packets. Kept as the
        counterpart of the versus format PEN20Device otherwise builds.

        Mirrors DM20Device.generate_all_packets_for_dcom: packets 1-9 carry
        our data, packet A claims all hits with a checksum over our own
        transmission. Target remainder 0 — matching _validate_pen20_packets
        (see protocol_constants.PEN20 for the note about the doc claiming 12).
        """
        if version is None:
            try:
                v = int(getattr(self.digimon, 'version', 1))
            except Exception:
                v = 1
            v_min, v_max = protocol_constants.PEN20.VERSION_RANGE
            version = max(v_min, min(v_max, v))

        packets = [
            self.generate_packet1(order, version, eol),
            self.generate_packet2(cou, eol),
            self.generate_packet3(0, eol),
            self.generate_packet4(0, eol),
            self.generate_packet5(eol=eol),
            self.generate_packet6(eol),
            self.generate_packet7(0, eol),
            self.generate_packet8(0, eol),
            self.generate_packet9(eol=eol),
        ]

        # Sum every nibble of packets 1-9
        checksum = 0
        for pkt in packets:
            for byte in pkt:
                checksum += (byte >> 4) & 0x0F
                checksum += byte & 0x0F

        # Packet A: Check(4) | Dodges(4) | Hits(4) | EOL(4)
        dodges = 0x0
        hits = 0xF
        checksum += dodges + hits + (eol & 0xF)
        target = protocol_constants.PEN20.CHECKSUM_REMAINDER
        check = (target - (checksum % 16)) % 16

        packets.append(struct.pack(">BB", (check << 4) | dodges, (hits << 4) | eol))
        return packets

class DMXDevice:
    """
    Represents a Digimon device in the DMX/PENZ protocol.
    Handles packet generation, processing, and state management.
    
    DMX uses XAI Roll + XAI Bar minigame (0-3).
    PENZ uses Count Match minigame (rotation index 1-3, maps to 0-3).
    
    Attack quality is determined by level + minigame result:
    - Bad (0), Good (1), Great (2), Excellent (3)
    
    Power is capped at 255 to prevent overflow bugs from original Version 1 devices.
    """
    MAX_POWER = 255
    
    def __init__(self, digimon: Digimon):
        self.digimon = digimon
        self.hp = digimon.hp
        # Cap power at 255 to prevent Version 1 overflow bug
        self.power = min(self.MAX_POWER, digimon.power)
        self.attribute = digimon.attribute
        self.level = digimon.level
        self.sick = digimon.sick
        self.stage = digimon.stage
        self.index = digimon.index
        self.shot_s = digimon.shot1
        self.shot_w = digimon.shot2
        self.shot_m = getattr(digimon, 'dmx_shot_m', digimon.shot1)
        self.buff = min(2, digimon.buff)  # Max buff is 2
        self.order = digimon.order
        self.version = getattr(digimon, 'version', 0) & 0x0F  # 4-bit version from Digimon
        self.hits = 0  # Hit pattern (5 bits for 5 turns)
        self.check = 0  # Check value
        self.received_packets = []  # Store received packets

    def generate_packet1(self):
        """
        Generates Packet 1: Order(1) Level(4) Sick(1) Attack(2) Version(4) EOL(4).
        Total: 16 bits = 2 bytes
        
        Attack is only 2 bits (0-3): Bad(0), Good(1), Great(2), Excellent(3)
        """
        attack = self.digimon.mini_game & 0x03  # Only 2 bits (0-3)
        eol = 0xE  # 1110
        
        # Byte 1: Order(1) Level(4) Sick(1) Attack(2)
        # Byte 2: Version(4) EOL(4)
        return struct.pack(
            ">B", (self.order << 7) | (self.level << 3) | (self.sick << 2) | (attack & 0x03)
        ) + struct.pack(
            ">B", ((self.version & 0x0F) << 4) | eol
        )

    def generate_packet2(self):
        """
        Generates Packet 2: Stage(3) Index(7) Attribute(2) EOL(4).
        Total: 16 bits = 2 bytes
        
        Index is 7 bits (0-127), not 8 bits
        Attribute is 2 bits (0-3), not 3 bits
        """
        eol = 0xE  # 1110
        index = self.index & 0x7F  # 7 bits
        attribute = self.attribute & 0x03  # 2 bits
        
        # Byte 1: Stage(3) + Index high 5 bits
        # Byte 2: Index low 2 bits + Attribute(2) + EOL(4)
        return struct.pack(
            ">B", (self.stage << 5) | (index >> 2)
        ) + struct.pack(
            ">B", ((index & 0x03) << 6) | (attribute << 4) | eol
        )

    def generate_packet3(self):
        """
        Generates Packet 3: Shot S(6), Shot W(6), EOL(4).
        Total: 16 bits = 2 bytes
        """
        # Byte 1: Shot S (6 bits) + Shot W high 2 bits
        # Byte 2: Shot W low 4 bits + EOL (4 bits)
        return struct.pack(
            ">B", ((self.shot_s & 0x3F) << 2) | ((self.shot_w >> 4) & 0x03)
        ) + struct.pack(
            ">B", ((self.shot_w & 0x0F) << 4) | 0b1110
        )

    def generate_packet4(self):
        """
        Generates Packet 4: COU, HP, Shot M, EOL.
        """
        return struct.pack(
            ">B", (0b00 << 6) | (self.hp << 1) | (self.shot_m >> 4)
        ) + struct.pack(
            ">B", ((self.shot_m & 0b1111) << 4) | 0b1110
        )

    def generate_packet5(self):
        """
        Generates Packet 5: COU(2), Buff(2), Power(8), EOL(4).
        Total: 16 bits = 2 bytes
        """
        # Byte 1: COU(2) + Buff(2) + Power high 4 bits
        # Byte 2: Power low 4 bits + EOL(4)
        return struct.pack(
            ">B", (0b00 << 6) | ((self.buff & 0x03) << 4) | ((self.power >> 4) & 0x0F)
        ) + struct.pack(
            ">B", ((self.power & 0x0F) << 4) | 0b1110
        )

    def generate_packet6(self, eol=0b1110):
        """
        Generates Packet 6: Check(4) COU(3) Hits(5) EOL(4).
        Calculates checksum from all previous packets and hits pattern.
        """
        if len(self.received_packets) < 5:
            raise ValueError("Not enough packets received to calculate checksum.")

        # Extract opponent's power from Packet 5
        opponent_power_byte = self.received_packets[4][0]
        opponent_power = ((opponent_power_byte & 0x0F) << 4) | ((self.received_packets[4][1] >> 4) & 0x0F)

        # Extract opponent's attribute from Packet 2
        opponent_attribute = (self.received_packets[1][1] >> 4) & 0x03

        # Attribute advantage. Vaccine beats Virus, Virus beats Data, Data
        # beats Vaccine; the winner's Power is raised, which the manual puts
        # as a "+32 bonus to your Digimon's Power stat". The amount and the
        # fact that it is spent on Power rather than on the roll are the DMX
        # module's own values, hardcoded in protocol_constants because the
        # protocol is usable without that module installed.
        # One formula for every wire, and the FORMAT's own constants --
        # this read `protocol_constants.DMX` literally, which is right
        # for PENZ only because it inherits the same 32 on Power.
        limits = (protocol_constants.get_constants(
            getattr(self, 'battle_format', None) or 'DMX')
            or protocol_constants.DMX)
        hitrate = protocol_constants.hit_rate(
            limits, self.power, self.attribute,
            opponent_power, opponent_attribute)

        hits = 0
        for i in range(protocol_constants.DMX.TURNS):
            attack_roll = random.randint(0, 99)
            hit = 1 if attack_roll < hitrate else 0
            hits |= (hit << i)

        self.hits = hits
        cou3 = 0  # 3-bit COU value

        # Calculate checksum - sum all nibbles from packets 1-5 (sent by this device)
        checksum = 0
        # We need to sum our OWN packets that were sent, not received packets
        # For simulation, we need to recalculate what we sent
        # This is tricky - we should track sent packets properly
        # For now, use a simplified approach
        
        # Generate the first 5 packets again to get nibble sums
        from io import BytesIO
        temp_packets = [
            self.generate_packet1(),
            self.generate_packet2(),
            self.generate_packet3(),
            self.generate_packet4(),
            self.generate_packet5()
        ]
        
        for pkt in temp_packets:
            for byte in pkt:
                checksum += (byte >> 4) & 0x0F  # Upper nibble
                checksum += byte & 0x0F  # Lower nibble
        
        # Build packet 6 structure without check
        byte1_without_check = (cou3 << 1) | (hits >> 4)
        byte2 = ((hits & 0x0F) << 4) | eol
        
        # Add nibbles from packet 6 (without check nibble)
        checksum += byte1_without_check & 0x0F
        checksum += (byte2 >> 4) & 0x0F
        checksum += byte2 & 0x0F
        
        # Find check value that makes (checksum + check) % 16 == 8
        intended_remainder = 8
        check = (intended_remainder - (checksum % 16)) % 16
        self.check = check
        
        # Build final packet
        byte1 = (check << 4) | byte1_without_check
        
        return struct.pack(">BB", byte1, byte2)

    def process_packet(self, packet):
        """
        Processes an incoming packet and stores it for later use.
        """
        self.received_packets.append(packet)

    def generate_all_packets_for_dcom(self, eol=protocol_constants.DMX.EOL):
        """
        Generate all 6 DMX/PENZ packets for DCom battle communication.

        Packet 6 here is a PLACEHOLDER. It cannot be stated in advance --
        the hits have to be the inverse of the ones the toy is about to send,
        and claiming all five instead can drive both sides to 0 on the same
        round, which freezes a real device. The adapter computes the real one
        from the packet it is replying to; DComBattleSimulator.build_command
        substitutes DMX.DCOM_FINAL_SEGMENT for this packet, and the checksum
        along with it. What is built here only keeps the list six long and
        the nibble sum ≡ 8 (mod 16) for _validate_dmx_packets.
        """
        packets = [
            self.generate_packet1(),
            self.generate_packet2(),
            self.generate_packet3(),
            self.generate_packet4(),
            self.generate_packet5(),
        ]

        checksum = 0
        for pkt in packets:
            for byte in pkt:
                checksum += (byte >> 4) & 0x0F
                checksum += byte & 0x0F

        # Packet 6: Check(4) | COU(3) | Hits(5) | EOL(4)
        hits = 0b11111
        cou3 = 0
        byte1_without_check = (cou3 << 1) | ((hits >> 4) & 0x1)
        byte2 = ((hits & 0x0F) << 4) | (eol & 0xF)

        checksum += byte1_without_check & 0x0F
        checksum += (byte2 >> 4) & 0x0F
        checksum += byte2 & 0x0F

        target = protocol_constants.DMX.CHECKSUM_REMAINDER
        check = (target - (checksum % 16)) % 16
        self.hits = hits
        self.check = check

        packets.append(struct.pack(">BB", (check << 4) | byte1_without_check, byte2))
        return packets

# --- Test code ---
if __name__ == "__main__":
    # Test Digimon data
    device1 = Digimon(
        name="Agumon",
        order=0,
        traited=0,
        egg_shake=0,
        index=2,
        hp=6,
        attribute=0,  # Vaccine
        power=50,
        handicap=0,
        buff=0,
        mini_game=5,
        level=5,
        stage=0,
        sick=0,
        shot1=10,
        shot2=15,
        tag_meter=2
    )

    device2 = Digimon(
        name="Gabumon",
        order=0,
        traited=0,
        egg_shake=0,
        index=18,
        hp=6,
        attribute=2,  # Virus
        power=45,
        handicap=0,
        buff=0,
        mini_game=8,
        level=5,
        stage=0,
        sick=0,
        shot1=12,
        shot2=17,
        tag_meter=2
    )

    print("=" * 70)
    print("TESTING ALL BATTLE PROTOCOLS")
    print("=" * 70)
    print()
    
    # NOTE: the maintained protocol test suite lives in
    # tests/test_battle_protocols.py — this block is just a quick smoke run.
    protocol_map = {
        'DM20': BattleProtocol.DM20_BS,
        'DMC': BattleProtocol.DMC_BS,
        'DMX': BattleProtocol.DMX_BS,
        'PEN20': BattleProtocol.PEN20_BS,
    }

    test_results = []

    for protocol_name in protocol_map:
        print(f"{'='*70}")
        print(f"TESTING: {protocol_name}")
        print(f"{'='*70}")

        try:
            # Create simulator with protocol
            simulator = BattleSimulator(protocol=protocol_map[protocol_name], verbose=True)
            
            # Run battle
            result = simulator.simulate(device1, device2)
            
            # Print packet data
            if hasattr(result, 'device1_packets') and result.device1_packets:
                print("\nDevice 1 Packets:")
                for i, packet in enumerate(result.device1_packets, 1):
                    hex_str = ' '.join(f'{b:02X}' for b in packet)
                    bin_str = ' '.join(f'{b:08b}' for b in packet)
                    print(f"  Packet {i}: {hex_str}")
                    print(f"            {bin_str}")
            
            if hasattr(result, 'device2_packets') and result.device2_packets:
                print("\nDevice 2 Packets:")
                for i, packet in enumerate(result.device2_packets, 1):
                    hex_str = ' '.join(f'{b:02X}' for b in packet)
                    bin_str = ' '.join(f'{b:08b}' for b in packet)
                    print(f"  Packet {i}: {hex_str}")
                    print(f"            {bin_str}")
            
            # Print DCom code format (alternating r: and s:)
            if hasattr(result, 'device1_packets') and hasattr(result, 'device2_packets') and result.device1_packets and result.device2_packets:
                # Format: r:packet s:packet r:packet s:packet ... t
                # r: = receive (from device 2), s: = send (from device 1)
                # Packets are already in correct byte order from Device classes
                dcom_parts = []
                max_packets = max(len(result.device1_packets), len(result.device2_packets))
                
                for i in range(max_packets):
                    # Receive from device 2 - direct hex representation
                    if i < len(result.device2_packets):
                        packet = result.device2_packets[i]
                        packet_hex = ''.join(f'{b:02X}' for b in packet)
                        dcom_parts.append(f"r:{packet_hex}")
                    
                    # Send from device 1 - direct hex representation
                    if i < len(result.device1_packets):
                        packet = result.device1_packets[i]
                        packet_hex = ''.join(f'{b:02X}' for b in packet)
                        dcom_parts.append(f"s:{packet_hex}")
                
                dcom_parts.append("t")  # Terminator
                dcom_code = ' '.join(dcom_parts)
                print(f"\nDCom Code: {dcom_code}")
            
            test_results.append((protocol_name, "[OK] SUCCESS"))
            print(f"\n[OK] {protocol_name} test completed successfully!")
            
        except Exception as e:
            test_results.append((protocol_name, f"[FAIL] {str(e)}"))
            print(f"\n[FAIL] {protocol_name} test failed: {str(e)}")
        
        print()
    
    # Summary
    print("=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    for protocol, status in test_results:
        print(f"{protocol:15s} - {status}")
    print()
    print("=" * 70)
    print("ALL PROTOCOL TESTS COMPLETED!")
    print("=" * 70)
