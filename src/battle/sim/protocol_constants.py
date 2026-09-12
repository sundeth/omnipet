"""
Battle protocol constants
=========================

Single source of truth for the real-device battle protocol constants.

POLICY: the DCom exchange path (``dcom_battle_simulator`` + the device
classes' ``generate_all_packets_for_dcom``) was validated against real
Digimon devices and is considered the correct implementation. Values here
are the ones that tested path effectively used. Where the community protocol
documentation disagrees with tested behavior, the difference is called out
in the comments — do not "fix" those without re-testing on hardware.

The old ``src/data/protocols/*.json`` definitions were removed: they were
never used for packing/unpacking (the field extractor was a stub), several
never loaded at all (``PENZ.json`` was malformed, ``Pen20.json`` failed the
case-sensitive lookup on Linux/Android), and their values had drifted from
the tested code (e.g. DM20 fixed HP 4 vs the tested 5).

Packet layouts live as documented bit-packing in the device classes in
``battle_simulator.py`` (DM20Device, PEN20Device, DMXDevice, DMCDevice,
DMDevice); the parsing/validation mirrors live in
``dcom_battle_simulator``. ``tests/test_battle_protocols.py`` round-trips
generation through the tested parsers to keep the two in sync.

Reference document (bit layouts, checksum targets):
https://docs.google.com/document/d/11CuxpKQFaHexAbi8jHX4UnfhZVfovwDAXo5xYZCEDpM

THE DCOM WIRE IS NOT THE VERSUS FORMAT. Six battle formats can be selected
for a DCom battle, but they share only three packet layouts on the wire, and
a format's ``DCOM_WIRE`` says which one it uses:

    DM     2 packets     DM
    DM20   10 packets    DM20, PEN20
    DMX    6 packets     DMX, PENZ, DMC

A format that borrows another's wire differs only in the charge minigame.
The versus (Omnipet vs Omnipet) simulation is free to use a richer format for
the same device -- PEN20Device and DMCDevice below are versus formats, both
sides agree on them, and neither is what a real toy is sent. Reading those
classes as the wire format is the mistake to avoid.
"""

#: Every DCom battle goes out over 2-prong timings, whatever the format.
#: The letter opening a DCom command selects the signalling; this is the one
#: the tested exchange used for all six formats.
DCOM_OP = "V"

#: Who opens the exchange, as the digit after the op letter.
#:
#:   1  the adapter sends first, repeating every few seconds
#:   2  the adapter listens, and answers whatever the toy sends
#:
#: This is a property of the toy, not of the packets: a Ver.20th sits waiting
#: to be spoken to once you press its button (turn 2), while a Pendulum 20th
#: never opens the conversation at all -- it acknowledges the contact and
#: then waits to be sent to, so nothing happens until the adapter goes first.
#: DMComm's own code list says as much: "Codes written as 'V1' or 'X1' must
#: be '1'", and every battle code it lists for the Pendulum line is a V1.
DCOM_TURN_GO_FIRST = 1
DCOM_TURN_LISTEN = 2

#: DCom exchanges 16-bit packets: 4 hex digits each on the serial line.
DCOM_PACKET_HEX = 4


def shot_to_wire(sprite_id: int, field_max: int, sprite_count: int = 0) -> int:
    """An Omnipet attack sprite id as the devices number them.

    Omnipet reserves 0 for "no sprite" and starts the real ones at 1; the
    devices start at 0 and spell "none" as the field filled with ones (which
    is where the 65535 in a firmware dump comes from -- the same convention
    at full width). So the shift is not a plain -1: an empty slot has to go
    out as the sentinel, not as sprite 0, or the toy draws its first attack
    for a Digimon that has none.

    **The field is wider than the device's sprite bank**, and the two are
    different limits. DM20 carries six bits, so 0-62 fit below the sentinel,
    while the device itself has 44 sprites -- ids 0-43. Sending 50 names
    nothing it can draw. `SHOT_COUNT` on the format is how many the line
    really has, and it caps the value where it is declared; the sentinel
    stays the field's own all-ones, because that is what "none" is on the
    wire whatever the bank holds.
    """
    if field_max <= 0:
        return 0
    if not sprite_id:
        return field_max
    # Kept below the sentinel so a real sprite can never read as "none".
    top = field_max - 1
    if sprite_count:
        top = min(top, int(sprite_count) - 1)
    return max(0, min(int(sprite_id) - 1, top))


def stage_from_wire(battle_format: str, stage) -> int:
    """A wire stage back on Omnipet's scale.

    `pet_to_digimon` writes the wire's numbering into the Digimon it builds
    -- the DMX counts from Baby II, so an Ultimate goes out as 4 -- while
    `parse_opponent` puts the toy's back on Omnipet's before anything reads
    it. So the two sides of a finished exchange are on **different scales**,
    and anything comparing them has to say which it holds.

    That mattered the moment the DMX's attack table became keyed on the
    stage: our own Raremon, an Adult, reached the lookup as a 2 and drew
    Baby II's row.
    """
    if stage is None:
        return None
    limits = get_constants(battle_format)
    return int(stage) + (getattr(limits, "STAGE_OFFSET", 0) if limits else 0)


def shot_from_wire(value: int, field_max: int) -> int:
    """The inverse: a device's sprite id as Omnipet numbers them."""
    if field_max <= 0 or value is None:
        return 0
    if int(value) >= field_max:
        return 0
    return int(value) + 1


class DMOG:
    """Digital Monster (Original, 1997) — slot-based battle.

    2 packets of 16 bits each; no EOL marker, validation is done by
    mirrored (bit-inverted) copies of each field inside the packet.
    Packet 1: mirrors byte + (Boost(4) | Slot(4)); Packet 2: mirrors byte +
    (Version(4) | Outcome(4)). Outcome: 1 = victory, 2 = defeat.
    The power->slot table and the slot-vs-slot win-probability matrix are
    hardcoded in BattleSimulator._get_dm_slot_from_power /
    _get_dm_win_probability.
    """
    NAME = "DMOG"
    DISPLAY_NAME = "DM (Original Digital Monster)"
    MENU_LABEL = "DMOG (Original)"
    PACKET_COUNT = 2
    FIXED_HP = 5          # in-game versus HP; real DM has no HP exchange
    #: Presentation only -- this wire exchanges a verdict, never a round
    #: count. **Four**, measured: a battle filmed against a real device
    #: played three traded singles and then the winner's double, and the
    #: winner's damage over those four rounds (1+1+1+2) is exactly FIXED_HP.
    #: The table itself lives in data/attack_patterns/DMC.json, which both
    #: verdict wires read -- DMC's battles are built on this one.
    TURNS = 4
    #: The highest attack value a battle on this line can roll, and so the
    #: cap `GameModule.battle_damage_limit` takes. It belongs to the device
    #: line and not to the module's HP bar: a module reproducing this device
    #: with a longer bar so its adventure mode lasts is still fighting a
    #: device that only ever hits for 1 or 2. Protocols are hardcoded here, so
    #: their limit is too; a module declaring no protocol keeps the old
    #: HP-derived rule.
    DAMAGE_LIMIT = 2
    #: Ver.1 to Ver.5. The module carries a sixth, but that was an
    #: Australia-only release and is not known to battle at all, so there is
    #: no wire version that is honestly its own.
    VERSION_RANGE = (1, 5)
    #: A version outside that range is clamped to the nearest end rather than
    #: sent as 0. Every other wire spells "a version this device does not
    #: have" as 0 -- but 0 is also what a device reads as *special*, and it
    #: is the value most likely to open content the pet has not earned. A
    #: Ver.6 pet announcing 5 at least says "the last release", which is
    #: adjacent to the truth; announcing 1 would claim it is the first.
    #: Only this line clamps; nothing else changes behaviour.
    CLAMP_VERSION_TO_RANGE = True
    DCOM_WIRE = "DMOG"    # its own 2-packet layout
    #: Packet 2 is VersionMirror(4) OutcomeMirror(4) Version(4) Outcome(4),
    #: and the outcome is not ours to invent: "1 means victory while 2 means
    #: defeat", and whoever sends their outcome packet first decides it --
    #: "the outcome is always decided by the Digital Monster since it sends
    #: its outcome packet first". Answering, we send the opposite of theirs,
    #: and both digits that carry it are a XOR with 3 (1<->2, and their
    #: mirrors E<->D), so the adapter builds it from the packet it is
    #: replying to. The two literal digits are our own version and its mirror,
    #: filled in by build_command.
    #:
    #: We sent Outcome 0 for a long time, which is neither victory nor defeat.
    #: The mirror bits were self-consistent so the code was not rejected as
    #: corrupt -- it simply told the device nothing, and nothing came back.
    DCOM_OUTCOME_ECHO = "^3{version}^3"
    #: Stated from the SENDER's point of view: the side that writes 1 is the
    #: side that won. Three sources agree -- the document ("1 means victory
    #: while 2 means defeat"), wificom's punchbags (the code named "DMOG you
    #: win", meaning the toy wins, sends outcome **2**), and a filmed battle
    #: where a real device sent 1 and played a win. Reading the toy's digit
    #: as our own result inverts every DMOG battle.
    OUTCOME_VICTORY = 1
    OUTCOME_DEFEAT = 2
    #: The one attack sprite this line draws, whatever Digimon is holding it.
    #: The wire has no sprite field at all -- nothing about the attack is
    #: exchanged -- and on the device every Digimon fires the same shot, seen
    #: across every filmed battle. So a connection battle here uses it for
    #: both sides rather than each pet's own. An adventure battle on a DMOG
    #: module is not a connection battle and keeps the pet's own sprite.
    FORCED_ATTACK_SPRITE = 2
    #: What an outsider announces. An OEM pet -- one raised on the module
    #: that reproduces this device -- sends its own ``device_version``
    #: instead, so a Ver.3 Digital Monster tells the toy it is a Ver.3.
    #: A compatibility pet has no version on this line's chart and sends 1,
    #: the first release, rather than the 0 that means "special" and could
    #: open content the pet has not earned.
    COMPATIBILITY_VERSION = 1
    #: We listen rather than open. Whoever sends their outcome packet first
    #: decides it, and opening means declaring a result we have not earned --
    #: which we did, always as a defeat, so every battle we started was a
    #: loss. The document puts the modern device on this side too: "the
    #: Digimon Pendulum could not initiate battles with the Digital Monster,
    #: so the outcome is always decided by the Digital Monster since it sends
    #: its outcome packet first". Answering also lets DCOM_OUTCOME_ECHO run,
    #: which needs a reply to XOR against.
    DCOM_TURN = DCOM_TURN_LISTEN
    MINIGAME = "None"     # boost comes from pills, not from a charge
    #: How a damage value becomes projectiles on screen. "count" is the
    #: literal reading -- N damage is N atk_main sprites in the shot -- and
    #: it is what the filmed battle shows: one shot for a 1, a double shot
    #: for the 2 that finishes the loser off. This wire never draws atk_alt.
    #:
    #: It is not the module's business. A DCom battle is fought on the
    #: device's wire, but the animation branch used to be picked from the
    #: player's own `battle_damage_limit`, which describes that module's
    #: adventure battles -- so the same DMOG exchange animated differently
    #: depending on which pet the player happened to bring.
    ATTACK_ANIMATION = "count"
    #: Boost is the pill count, 0-4; there is no charge minigame. A modern
    #: device sends 0 and cannot raise it -- "the boost for all modern
    #: devices using the 'Other' Battle System will be 0" -- which a real DMX
    #: in old-device mode confirmed. (The Pendulum's famous 7 is its own
    #: cheat, not general modern behaviour.)
    CHARGE_SCALE = "taps"
    MAX_CHARGE = 4
    # Field widths, for clamping a pet onto the wire (see pet_to_digimon).
    # Power is not sent, and no shots are exchanged. The index is not sent
    # either -- but it *chooses* the slot for a pet native to this line, so
    # it is kept to the chart's own top index rather than flattened to 0.
    MAX_INDEX = 13
    MAX_SHOT = 0

    #: The twelve battle slots, in chart order, as the wire numbers them.
    #: "The original Digital Monster used a slot system to represent what
    #: Digimon was being used... two Digimon in the same slot were
    #: effectively the same Digimon", the chart being 2 Child, 7 Adult and
    #: 3 Perfect. Slot A is 0x3 and they run consecutively to L at 0xE.
    SLOT_LETTERS = "ABCDEFGHIJKL"
    FIRST_SLOT = 0x3
    LAST_SLOT = 0xE
    #: Every DM module version lists exactly these twelve at indices 2..13,
    #: in chart order, so a pet native to this line has its real slot already:
    #: index 2 Agumon is slot A (0x3) and index 13 Monzaemon is slot L (0xE).
    SLOT_INDEX_OFFSET = 1
    FIRST_SLOT_INDEX = 2
    LAST_SLOT_INDEX = 13

    #: A slot is a tier, not an identity. "Two Digimon in the same slot were
    #: effectively the same Digimon" -- Greymon, Kabuterimon and Unimon all
    #: go out as slot C -- and a modern device in legacy mode maps whatever
    #: it holds onto the same twelve. So the opponent cannot be named, and
    #: naming it anyway put a Digital Monster's Seadramon on screen for a DMX
    #: that was holding something else entirely. It gets the placeholder set
    #: instead. Any wire that exchanges no identity should declare this.
    GENERIC_OPPONENT = "Unknown"

    #: What the chart does say about a slot: which stage band it sits in.
    #: A-B are the two Child slots, C-I the seven Adult, J-L the three
    #: Perfect. Lossy on the way in -- an Ultimate has nowhere else to go but
    #: the top band -- but it is the wire's own reading, not a guess.
    SLOT_STAGES = ((0x4, 3), (0xB, 4), (0xE, 5))

    #: The original chart's own power bands, for a pet **native to this
    #: line**. The Digital Monster's roster runs 0-60 and these are the bands
    #: that range was drawn for, so a DMOG pet is never rescaled -- it is
    #: already on the scale the device uses. (In practice a native pet takes
    #: its real chart position from `index` and never reaches these at all;
    #: they are the floor for one whose index is off the chart.)
    #: Lives here rather than on DMDevice because the adventure-mode pattern
    #: table reads it too.
    POWER_TO_SLOT = (
        (10, 0x3),   # A: power <= 10
        (15, 0x4),   # B: 11-15
        (20, 0x5),   # C: 16-20
        (25, 0x6),   # D: 21-25
        (30, 0x7),   # E: 26-30
        (35, 0x8),   # F: 31-35
        (40, 0x9),   # G: 36-40
        (45, 0xA),   # H: 41-45
        (50, 0xB),   # I: 46-50
        (55, 0xC),   # J: 51-55
        (59, 0xD),   # K: 56-59
    )                # L: 60 and up

    #: Power per slot for a pet from **any other module**, which arrives on a
    #: completely different scale: Omnipet's battling rosters run to 240,
    #: against the Digital Monster's 60. Read through the bands above, half
    #: of every roster announced slot **L** -- the strongest on the chart,
    #: which the guidebook matrix scores at 13-15 out of 16 against most
    #: slots. That is the Pendulum's own cheat, applied by accident to half
    #: the game.
    #:
    #: Sixteen is not arbitrary: it is what a real Pendulum Z did in legacy
    #: mode, twice and exactly -- Falcomon at power 8 announced slot A and
    #: Orochimon at 88 announced F, both `3 + power // 16`. It is the only
    #: rule with hardware behind it, though from one device line; a DMX and a
    #: PEN20 each landed somewhere else, so **the devices do not agree with
    #: each other** and this stays ours rather than theirs.
    COMPATIBILITY_POWER_PER_SLOT = 16

    #: Chance out of 16 that the row's slot beats the column's, from the
    #: guidebook matchup matrix -- rows and columns both A(0) to L(11). It
    #: lives here beside `POWER_TO_SLOT` rather than in one simulator,
    #: because both the versus path and the DCom path need it and a slot is
    #: the only measure of strength this wire exchanges.
    SLOT_WIN_ODDS = (
        #  A   B   C   D   E   F   G   H   I   J   K   L
        ( 8,  8,  2,  3,  2,  3,  2,  3,  7,  1,  1,  1),  # A
        ( 8,  8,  2,  3,  2,  3,  2,  3,  7,  1,  1,  1),  # B
        (15, 15,  8, 11,  9, 11,  7, 11, 13,  3,  3,  3),  # C
        (13, 13,  5,  8,  5,  9,  5,  7, 11,  2,  2,  2),  # D
        (15, 15,  7, 11,  8, 11,  9, 11, 13,  3,  3,  3),  # E
        (13, 13,  5,  7,  5,  8,  5,  9, 11,  2,  2,  2),  # F
        (15, 15,  9, 11,  7, 11,  8, 11, 13,  3,  3,  3),  # G
        (13, 13,  5,  9,  5,  7,  5,  8, 11,  2,  2,  2),  # H
        ( 9,  9,  3,  5,  3,  5,  3,  5,  8,  1,  1,  1),  # I
        (15, 15, 13, 14, 13, 14, 13, 14, 15,  8,  5,  5),  # J
        (15, 15, 13, 14, 13, 14, 13, 14, 15, 11,  8,  5),  # K
        (15, 15, 13, 14, 13, 14, 13, 14, 15, 11, 11,  8),  # L
    )

    @staticmethod
    def slot_win_odds(my_slot_index, opponent_slot_index,
                      my_boost=0, opponent_boost=0):
        """Chance out of 16 that *my_slot_index* wins, boosts included.

        The boost is the pills a Digital Monster can be fed before a battle,
        and the difference between the two shifts the odds one for one --
        kept inside 1..15 so neither side is ever a certainty. A modern
        device sends boost 0, which is the ordinary case here.
        """
        span = len(DMOG.SLOT_WIN_ODDS) - 1
        mine = min(span, max(0, int(my_slot_index)))
        theirs = min(span, max(0, int(opponent_slot_index)))
        base = DMOG.SLOT_WIN_ODDS[mine][theirs]
        return min(15, max(1, base + int(my_boost) - int(opponent_boost)))

    @staticmethod
    def slot_index(slot: int) -> int:
        """A wire slot value (0x3 A .. 0xE L) as a 0-11 index."""
        return min(len(DMOG.SLOT_WIN_ODDS) - 1,
                   max(0, int(slot or DMOG.FIRST_SLOT) - DMOG.FIRST_SLOT))

    @staticmethod
    def slot_for_power(power: int, oem: bool = False) -> int:
        """The battle slot a pet of *power* stands in, as a hex value.

        *oem* selects the scale: a pet native to this line is already on the
        device's own 0-60 range and is read through `POWER_TO_SLOT` as it
        stands, while anything else is rescaled -- see
        `COMPATIBILITY_POWER_PER_SLOT`.
        """
        power = max(0, int(power or 0))
        if oem:
            for top, slot in DMOG.POWER_TO_SLOT:
                if power <= top:
                    return slot
            return DMOG.LAST_SLOT
        return min(DMOG.LAST_SLOT,
                   DMOG.FIRST_SLOT + power // DMOG.COMPATIBILITY_POWER_PER_SLOT)


class PENOG:
    """Digimon Pendulum (original) -- 4 packet exchange.

    The Pendulum can speak the Digital Monster's slot-and-verdict system, but
    it also brought its own, which exchanges a real battle: "Digimon each now
    have 3 HP, and exchange shots until the one Digimon's HP is depleted.
    Digimon can either deal 1 or 2 damage each turn."

    Packets (16 bits each):
      1: COU(1) | Version(3) | Sick(1) | Operation(1) | COU(1) | Slot(5) | EOL(4)
      2: Effort_2(4) | Effort_1(3) | Attack(5) | EOL(4)
      3: COU(4)      | COU(3)      | Hits(5)   | EOL(4)
      4: Check(4)    | Shot(8)     | EOL(4)

    **The EOL nibble is F here, not the E every other wire uses**, and the
    checksum targets remainder **11**. Both hold across the document's worked
    example (an Ikkakumon from Pendulum 2.0) and every real code on record.

    Attack and Hits are 5-bit patterns read right to left, one round per bit:
    a set Attack bit is a strong shot for 2 damage, a clear one weak for 1,
    and Hits says which of our rounds land. Each side sends **its own** hits,
    the way the DMX wire does -- packet 3 carries one side only.

    Effort is split into two digits for no obvious reason: `Effort_1` is the
    tens and `Effort_2` the units, so 4 and 0 is an effort of 40, which is
    the cap. It rises by one per training session.

    Operation is Battle (0) or Jogress (1); only Single Battles are
    implemented, so it is always 0.

    Slot works as it does on the Digital Monster -- a tier rather than an
    identity -- but on a chart of its own, ordered by **stage, then attribute
    (Va, Da, Vi), then ordinal**: 3-5 the Child slots, 6-11 the six Adult,
    12-17 the six Perfect, 18-19 the Ultimates. The document names slot 6
    "Vaccine Adult 1", and the real jogress codes label slots 6 to 19 exactly
    that way. The PEN module lists its battling Digimon in that same order at
    indices 2 upward, so `slot = index + 1`, the same relationship the DMOG
    chart has.

    The slot ratios themselves were never published -- "would require a LOT
    of tedious testing" -- but nothing here needs them: each device sends its
    own Hits, so the battle is read off the wire rather than rolled from a
    matchup table.
    """
    NAME = "PENOG"
    DISPLAY_NAME = "PENOG (Digimon Pendulum)"
    MENU_LABEL = "PENOG (Pendulum)"
    PACKET_COUNT = 4
    #: F, not E. Every packet on this wire ends in it.
    EOL = 0b1111
    #: "Remainder should always equal 11" -- and the document's example plus
    #: both of wificom's known-good codes all land on it.
    CHECKSUM_REMAINDER = 11
    #: "Digimon each now have 3 HP".
    FIXED_HP = 3
    #: The highest attack value a battle on this line can roll, and so the
    #: cap `GameModule.battle_damage_limit` takes. It belongs to the device
    #: line and not to the module's HP bar: a module reproducing this device
    #: with a longer bar so its adventure mode lasts is still fighting a
    #: device that only ever hits for 1 or 2. Protocols are hardcoded here, so
    #: their limit is too; a module declaring no protocol keeps the old
    #: HP-derived rule.
    DAMAGE_LIMIT = 2
    #: Attack and Hits are five bits, so five rounds at most.
    TURNS = 5
    DEFAULT_VERSION = 0
    #: Three bits. Five real versions, 1-5, one per Pendulum release -- the
    #: ten devices are 1.0/1.5 through 5.0/5.5 and ".5 versions do NOT have a
    #: separate version from their .0 counterparts" -- plus **0** for the
    #: Virus Busters, which is its own thing.
    #:
    #: The module already does that collapsing: devices.json gives 1.0 and
    #: 1.5 the same `device_version` 1, and the Virus Busters 0. So the pet's
    #: device_version *is* the wire version and goes out as it stands. It
    #: used to be divided again by a VERSION_DIVISOR of 2, on the assumption
    #: that it arrived as the module's 1-11 gameplay version -- so a Pendulum
    #: 5.0 announced itself as a 2, and 1.0, 1.5 and 2.0 all announced 0.
    VERSION_RANGE = (0, 5)
    #: An outsider announces 1, the first release. An OEM pet sends its own
    #: device_version instead.
    COMPATIBILITY_VERSION = 1
    DCOM_WIRE = "PENOG"
    #: Every code on record is written V1 -- both of wificom's punchbags and
    #: both battle codes in the DigiROM dump -- so the adapter opens. Nothing
    #: here needs a reply to build a packet from, unlike the DMOG verdict.
    DCOM_TURN = DCOM_TURN_GO_FIRST
    #: A Pendulum 20th in its legacy Pendulum mode **does** play a charge
    #: before the battle, and it is Count Match Classic -- watched on the
    #: device, which is the only PENOG opponent we have.
    #:
    #: What the charge does is a separate question, and open. The Attack
    #: field comes from **Effort**: "damage amounts being directly affected by
    #: how well you shook your device for that specific Digimon", and shaking
    #: is what raises Effort. So for now the charge is what the player does,
    #: not what the packet says -- the same standing PENC's Count Match Color
    #: has, where the Colour layout carries no charge field either. If a
    #: filmed battle shows the charge changing the shots, the table moves.
    MINIGAME = "Count Match Classic"
    #: Slots, as the real jogress codes label them.
    FIRST_SLOT = 3
    LAST_SLOT = 0x1F      # 5 bits
    SLOT_INDEX_OFFSET = 1
    FIRST_SLOT_INDEX = 2
    #: A slot is a tier, not an identity, exactly as on the Digital Monster,
    #: so an incoming one is not turned back into a Digimon.
    GENERIC_OPPONENT = "Unknown"
    #: Stage bands, from the chart the jogress codes spell out.
    SLOT_STAGES = ((5, 3), (11, 4), (17, 5), (0x1F, 6))

    #: Effort is two digits, tens then units, capped at 40.
    MAX_EFFORT = 40
    #: Constant in packet 3's second field on every code on record.
    PACKET3_COU = 0b100
    #: One sprite per point of damage, as on the Digital Monster -- a weak
    #: shot is one, a strong shot two -- but the strong pair is drawn with
    #: `atk_alt` where the Digimon has one, falling back to `atk_main`. Two
    #: attack levels and two sprites for them, which is what the wire says
    #: and all it says: there is no critical here.
    ATTACK_ANIMATION = "count_alt"
    #: The **raw shake meter**, 0-14, not the banded 0-3 quality. Count Match
    #: Classic fills the same field for DM20 and PEN20 and they read it whole;
    #: this wire took the band, and that band collapses eleven of the fifteen
    #: meter values onto zero (`minigame_result`: <= 10 is a flat Bad), so
    #: most of a played charge simply vanished before it reached the packet.
    CHARGE_SCALE = "taps"
    #: The whole shake meter. Count Match Classic keeps 0-40 now, and this
    #: wire reads the number itself rather than a band, so the table has a
    #: row per point.
    MAX_CHARGE = 40
    #: A versus battle has no charge to play -- the player would be shaking
    #: against themselves -- so both sides take this. Ten of forty: not the
    #: weakest, not the strongest, and enough for a strong round.
    VERSUS_CHARGE = 10
    #: One attack sprite for every Digimon in a **connection** battle, the
    #: same as the Digital Monster. Watched on a Pendulum 20th in legacy
    #: Pendulum mode: whatever either side is holding, the shot drawn is
    #: sprite 2. The wire does carry a Shot id, but it is the device's own
    #: numbering and lands outside anything we ship -- a real one announced
    #: 223 against the 117 sprites Omnipet has.
    #:
    #: Only a connection battle. An adventure battle on this line has no
    #: `battle_format`, so it keeps each pet's own sprites and the
    #: ATTACK_ANIMATION rule above picks between them.
    FORCED_ATTACK_SPRITE = 2
    #: Percent chance each of our five rounds lands, when the packet has to
    #: be built before the opponent has spoken. **Ours, and deliberately
    #: even**: the toy rolls this from a slot matchup table that "does not
    #: appear to have been officially published", and we open this exchange,
    #: so there is nothing to weigh ourselves against. The versus simulator
    #: knows both sides and uses the real power ratio instead.
    HIT_RATE_MODEL = 'battle_rules/PENOG.json'  # Deliberately approximate; see its provenance.

    # Field widths, for clamping a pet onto the wire (see pet_to_digimon).
    # No index, power or attribute goes out -- the slot carries all three --
    # but the index is what *chooses* the slot, so it survives to the builder
    # rather than being flattened, exactly as on the DMOG wire.
    MAX_INDEX = LAST_SLOT - SLOT_INDEX_OFFSET
    MAX_SHOT = 0xFF       # one 8-bit sprite field, not a pair


class DM20:
    """Digital Monster Ver.20th — 10 packet exchange.

    Packets (16 bits each):
      1: Name_2(8)  | Name_1(8)              (tamer name, chars 2/1)
      2: Name_4(8)  | Name_3(8)              (tamer name, chars 4/3)
      3: Order(1)   | Pattern(5) | Operation(2) | Version(4) | EOL(4)
      4: COU(2)     | Index_L(8) | Attribute_L(2) | EOL(4)
      5: Shot_S_L(6)| Shot_W_L(6)| EOL(4)
      6: COU(4)     | Power_L(8) | EOL(4)
      7: COU(2)     | Index_R(8) | Attribute_R(2) | EOL(4)   (0 for single)
      8: Shot_S_R(6)| Shot_W_R(6)| EOL(4)                    (0 for single)
      9: Tag_Meter(4)| Power_R(8)| EOL(4)                    (0 for single)
      A: Check(4)   | Dodges(4)  | Hits(4)   | EOL(4)

    Checksum: sum of every nibble of all 10 packets must be ≡ 0 (mod 16);
    the Check nibble is chosen to satisfy that. Attribute: 0=Va 1=Da 2=Vi
    3=Free. Hits/Dodges are 4-bit patterns read right-to-left, repeated
    when more than 4 rounds are needed; in single battles the opponent's
    values are the inversion of ours.
    """
    NAME = "DM20"
    DISPLAY_NAME = "DM20 (V-Pet/Pendulum/Progress)"
    MENU_LABEL = "DM20 (20th Anniversary)"
    PACKET_COUNT = 10
    EOL = 0b1110          # 0xE end-of-line marker on packets 3..A
    DEFAULT_VERSION = 1
    VERSION_RANGE = (1, 5)
    #: **Ten, measured on the device** -- and ten for every Digimon on the
    #: line, whatever its stage. This was 5, on a DCom note rather than a
    #: reading; before that the removed DM20.json said 4. Neither was ever
    #: watched, and the difference matters now that the measured attack
    #: table reaches 4 damage a shot: at 5 HP a Double Strong is half a
    #: battle, and a max-Strength one nearly all of it.
    FIXED_HP = 10
    #: The highest attack value a battle on this line can roll, and so the
    #: cap `GameModule.battle_damage_limit` takes. It belongs to the device
    #: line and not to the module's HP bar -- see DMOG.DAMAGE_LIMIT.
    #:
    #: **Four**, measured: the four single-battle attacks are Weak, Strong,
    #: Double Weak and Double Strong, and a value is its own damage. This was
    #: 3, from a table that held only 1s and 2s because it had recorded how
    #: many shots went out and not which sprite. Critical is a fifth attack
    #: that only Tag Battles reach. PEN20 draws from the same table.
    DAMAGE_LIMIT = 4
    #: "If your Digimon is at max Strength, damage output will increase for
    #: each attack by 1 in Single Battles, or 2 in Tag Battles (both Digimon
    #: must be at max Strength in Tag Battles for the bonus to apply)." Max
    #: Strength is four hearts, which the manual pins independently: "each
    #: Strength Heart adds 4 points to power, meaning you can add a total of
    #: 16". Only Single Battles are implemented, so the bonus is 1.
    #:
    #: It is applied to **our** side only. The wire carries Power but not the
    #: meter behind it, so there is no way to tell whether the toy's Digimon
    #: is at max Strength -- each device knows its own.
    MAX_STRENGTH_DAMAGE_BONUS = 1
    #: Damage rises in pairs and the sprite alternates within each: 1 and 2
    #: are one sprite, 3 and 4 are two, and the odd value of each pair draws
    #: `atk_alt` where the even one draws `atk_main`. **This line reverses
    #: the usual pairing** -- its weak attacks are the alternate sprite --
    #: and a pet with no `atk_alt` separates the four by count instead.
    ATTACK_ANIMATION = "paired"
    CHECKSUM_REMAINDER = 0
    #: What an attribute advantage is worth, and where it is spent. From the
    #: DM20 module's battle_attribute_advantage (5) and
    #: battle_attribute_advantage_power (false): five percentage points on the
    #: roll, not a bonus to Power. Held here rather than read from the module
    #: for the same reason as DMX's -- the DM20 *protocol* can be used by a pet
    #: from any module, and by a player who does not own the DM20 module.
    #: **+32 on Power**, from the Ver.20th manual: "Having an attribute
    #: advantage will effectively grant a +32 bonus to your Digimon's Power
    #: stat", and Power is what the hit rate is a ratio of -- "if your power
    #: is higher than your enemy's power, then your attacks are more likely
    #: to hit". The Pendulum Ver.20th manual says it word for word, so both
    #: 20th lines carry the same rule.
    #:
    #: It was 5 on the roll here, taken from the module rather than from the
    #: manual, and the module was wrong. The two halves of the code
    #: disagreed as a result: `generate_packetA` -- which decides the hits
    #: that actually go on the wire -- had always spent 32 on Power.
    ATTRIBUTE_ADVANTAGE = 32
    ATTRIBUTE_ADVANTAGE_ON_POWER = True
    DCOM_WIRE = "DM20"    # its own 10-packet layout
    DCOM_TURN = DCOM_TURN_LISTEN   # confirmed against a real Ver.20th
    DCOM_FINAL_SEGMENT = "@0^F^FE"
    MINIGAME = "Dummy Bar"   # 0-14 taps -> attack pattern index
    #: "Attack Pattern is determined by how many times the button was pressed
    #: for the rising meter in the Pre-Battle Minigame" -- the raw meter goes
    #: on the wire, not the 0-3 quality the DMX line uses.
    CHARGE_SCALE = "taps"
    MAX_CHARGE = 14
    # Field widths, for clamping a pet onto the wire (see pet_to_digimon).
    MAX_INDEX = 0xFF      # 8 bits
    MAX_POWER = 0xFF      # 8 bits
    MAX_SHOT = 0x3F       # 6 bits each
    #: How many attack sprites the Ver.20th actually has -- ids 0-43 on the
    #: wire, 1-44 in the module. The field is six bits wide and would carry
    #: up to 62, but a value past the bank names nothing the device can draw.
    #: The two limits are separate and `shot_to_wire` applies both.
    #:
    #: The count is the module's own `atk/` folder, which holds the device's
    #: sprites and nothing else. It was renumbered into a contiguous run by
    #: `utilities/claude/renumber_atk_sprites.py`; before that the folder
    #: carried the **Digital Monster Color's** ids, gaps and all, because
    #: that is what the global `assets/atk` is numbered by and what the
    #: module was written against.
    SHOT_COUNT = 44


class PEN20:
    """Digimon Pendulum Ver.20th — 10 packet exchange.

    Packets (16 bits each):
      1: Order(1) | COU(1) | Attack(4) | Operation(2) | Version(4) | EOL(4)
      2: COU(2)   | Index(8)   | Attribute(2) | EOL(4)
      3: COU(4)   | Shot_W(8)  | EOL(4)
      4: Sick(1)  | COU(3) | Shot_S(8) | EOL(4)
      5: COU(2)   | Traited(1) | Egg_Shake(1) | Power(8) | EOL(4)
      6: Copy(2)  | Index_R(8) | Attribute_R(2) | EOL(4)  (0 for single)
      7: COU(4)   | Shot_W_R(8)| EOL(4)                   (0 for single)
      8: COU(4)   | Shot_S_R(8)| EOL(4)                   (0 for single)
      9: COU(4)   | Power_R(8) | EOL(4)                   (0 for single)
      A: Check(4) | Dodges(4)  | Hits(4) | EOL(4)

    THIS IS THE VERSUS FORMAT, NOT THE DCOM WIRE. A real Pendulum 20th is
    talked to over the DM20 layout (``DCOM_WIRE = "DM20"``); the two devices
    differ in the charge minigame, not in the packets. The layout above is
    what PEN20Device generates for an Omnipet-vs-Omnipet battle, where both
    sides agree on it.

    The Check nibble targets remainder 12, not DM20's 0 -- "Remainder should
    always equal 12" in the protocol document, and its worked example (the
    Ordinemon/Chaosmon tag battle) sums to exactly 12. The code used to
    target 0 on the grounds that it was the tested value; nothing had in fact
    tested it against a Pendulum 20th.

    Power goes out as it stands. Traited and Egg Shake ride in packet 5 as
    their own bits and the document says of both that the value "does not
    appear to affect battle outcome", so no bonus is folded into Power.
    """
    NAME = "PEN20"
    DISPLAY_NAME = "PEN20 (Pendulum 20th)"
    MENU_LABEL = "PEN20 (Pendulum 20th)"
    PACKET_COUNT = 10
    EOL = 0b1110
    DEFAULT_VERSION = 1
    VERSION_RANGE = (1, 4)
    #: Ten, the same as DM20 -- measured on the device.
    FIXED_HP = 10
    #: Four, and the paired sprite rule with it -- PEN20 draws from DM20's
    #: measured table. See DM20.DAMAGE_LIMIT.
    DAMAGE_LIMIT = 4
    ATTACK_ANIMATION = "paired"
    MAX_STRENGTH_DAMAGE_BONUS = 1
    CHECKSUM_REMAINDER = 12  # doc, and its worked example, both say 12
    #: The Pendulum 20th speaks its own signal, not DM20's -- the layout
    #: above, remainder 12, its own Operation values and the Copy / Traited /
    #: Egg Shake fields DM20 has no room for. The DCom exchange used to send
    #: DM20's ten packets here, which is why a real Pendulum 20th never
    #: answered.
    DCOM_WIRE = "PEN20"
    DCOM_FINAL_SEGMENT = "@C^F^FE"
    #: And it never opens the exchange: it acknowledges the contact, then
    #: waits to be sent to.
    DCOM_TURN = DCOM_TURN_GO_FIRST
    # Field widths, for clamping a pet onto the wire (see pet_to_digimon).
    # The shots are a whole byte each here, twice DM20's 6 bits.
    MAX_INDEX = 0xFF      # 8 bits
    MAX_POWER = 0xFF      # 8 bits
    #: The Pendulum Ver.20th manual carries the Ver.20th's sentence word
    #: for word -- "+32 bonus to your Digimon's Power stat" -- so both 20th
    #: lines spend it the same way, and its module already said so.
    ATTRIBUTE_ADVANTAGE = 32
    ATTRIBUTE_ADVANTAGE_ON_POWER = True
    MAX_SHOT = 0xFF       # 8 bits each
    #: How many attack sprites the Pendulum Ver.20th actually has -- ids
    #: 0-107 on the wire, 1-108 in the module. Its field is eight bits and
    #: would carry up to 254, so the bank is much the tighter limit here.
    #: Same story as DM20's: the folder held the Digital Monster Color's
    #: numbering until `utilities/claude/renumber_atk_sprites.py` closed the
    #: gaps.
    SHOT_COUNT = 108
    MINIGAME = "Count Match Classic"  # shake meter, same 0-14 field as DM20
    CHARGE_SCALE = "taps"
    MAX_CHARGE = 14


class DMX:
    """Digital Monster X / Digimon Pendulum Z — 6 packet exchange.

    This is the wire for DMX, PENZ and DMC alike; those three differ only in
    the pre-battle minigame (DMX: Xai roll+bar, PENZ: count match, DMC: none),
    which is why PENZ and DMC below declare ``DCOM_WIRE = "DMX"``.

    Packets (16 bits each):
      1: Order(1) | Level(4) | Sick(1) | Attack(2) | Version(4) | EOL(4)
      2: Stage(3) | Index(7) | Attribute(2) | EOL(4)
      3: Shot_S(6)| Shot_W(6)| EOL(4)
      4: COU(2)   | HP(5)    | Shot_M(5) | EOL(4)
      5: COU(2)   | Buff(2)  | Power(8)  | EOL(4)
      6: Check(4) | COU(3)   | Hits(5)   | EOL(4)

    Checksum: nibble sum of all 6 packets ≡ 8 (mod 16). Attack quality:
    0=Bad 1=Good 2=Great 3=Excellent. Hits: 5-bit pattern right-to-left,
    5-round battle. Variable HP (5-bit field). Power capped at 255 to
    avoid the V1 hardware overflow. Attribute advantage: +32 power.
    """
    NAME = "DMX"
    DISPLAY_NAME = "DMX (Digital Monster X)"
    MENU_LABEL = "DMX (Digimon X)"
    PACKET_COUNT = 6
    EOL = 0b1110
    DEFAULT_VERSION = 0
    VERSION_RANGE = (1, 6)
    #: The version a compatibility battle announces. Everything else sends 0
    #: (see get_compatibility_version), but the DMX declares 1-6 and 0 is
    #: outside it -- and a real DMX given 0 drew the opponent's attacks from
    #: the Level *2* row of the pattern table instead of Level 1, twice, in
    #: the only two battles that sent it. Six battles that sent 1 or 2 all
    #: drew the right row.
    COMPATIBILITY_VERSION = 1
    #: Better than announcing a version of our own: mirror the device's.
    #: Packet 1 is Order(1) Level(4) Sick(1) Attack(2) | Version(4) EOL(4),
    #: so its last two hex digits are Version and EOL. ``^0`` XORs a digit
    #: with 0 against the packet being replied to -- which copies it. The
    #: toy therefore sees a Digimon of its own version, the most ordinary
    #: thing a battle can present, and nothing cross-version can unlock off
    #: the back of it.
    #:
    #: Like DCOM_FINAL_SEGMENT this needs a listen-and-reply exchange; going
    #: first there is nothing to copy, and COMPATIBILITY_VERSION is the
    #: fallback for that case.
    DCOM_VERSION_ECHO = "^0E"
    FIXED_HP = None       # variable, 5-bit (max 31)
    #: The highest attack value a battle on this line can roll, and so the
    #: cap `GameModule.battle_damage_limit` takes. It belongs to the device
    #: line and not to the module's HP bar: a module reproducing this device
    #: with a longer bar so its adventure mode lasts is still fighting a
    #: device that only ever hits for one of its five attack types. Protocols are hardcoded here, so
    #: their limit is too; a module declaring no protocol keeps the old
    #: HP-derived rule.
    DAMAGE_LIMIT = 5
    DEFAULT_HP = 12       # fallback when a pet has no HP (stage 4 value)
    TURNS = 5
    MAX_POWER = 255
    CHECKSUM_REMAINDER = 8
    #: What an attribute advantage is worth, and where it is spent. Taken
    #: from the DMX module's battle_attribute_advantage (32) and
    #: battle_attribute_advantage_power (true), but held here rather than
    #: read from the module: the DMX *protocol* can be used by a pet from any
    #: module, and a player battling a real DMX need not own the DMX module
    #: at all. The two are made after the same device but are not the same
    #: thing. PENZ shares this wire and its module agrees (32, on power).
    ATTRIBUTE_ADVANTAGE = 32
    ATTRIBUTE_ADVANTAGE_ON_POWER = True
    DCOM_WIRE = "DMX"     # its own 6-packet layout, shared with PENZ and DMC
    DCOM_TURN = DCOM_TURN_LISTEN
    #: Packet 6 is not sent literally: the adapter builds it from the packet 6
    #: it just received, as Check(4) COU(3) Hits(5) EOL(4) where the five hit
    #: bits are the device's own inverted.
    #:
    #:     @8   check digit, so every digit we send sums to 8 (mod 16)
    #:     ^1   XOR their digit 2 with 1 -- COU stays 0, hit bit 4 flips
    #:     ^F   XOR their digit 3 with F -- hit bits 3..0 flip
    #:     E    the EOL marker
    #:
    #: "Player and Opponents appear to always be inverse, and ties are not
    #: programmed into the device. If a tie would occur, the device will
    #: freeze and will need to be reset." Claiming every round as a hit --
    #: which is all a pre-built packet can do -- lets both sides reach 0 on
    #: the same round, and a real DMX froze on exactly that. The adapter can
    #: compute the inverse for us because its type-2 codes may XOR against
    #: the packet being replied to, and their packet 6 arrives before ours
    #: goes out.
    DCOM_FINAL_SEGMENT = "@8^1^FE"
    MINIGAME = "Xai Roll+Bar"
    #: The DMX family carries a 2-bit quality -- Bad, Good, Great, Excellent --
    #: not a tap count, so the banded 0-3 is what goes on the wire. PENZ and
    #: DMC inherit it.
    CHARGE_SCALE = "quality"
    MAX_CHARGE = 3
    #: Attack is 2 bits: Bad(0) Good(1) Great(2) Excellent(3).
    MAX_INDEX = 0x7F      # 7 bits
    MAX_HP = 0x1F         # 5 bits - the only line that puts HP on the wire
    MAX_SHOT = 0x3F       # 6 bits for the strong/weak shots
    MAX_SHOT_M = 0x1F     # 5 bits for the mega shot
    #: The two banks behind those fields, and they are different folders.
    #: The ordinary shots come from the module's own `atk/` -- 58 sprites,
    #: ids 0-57 on the wire -- and the mega shot from `assets/atk_crit`,
    #: which is global because the X lines are the only ones that use it: 29
    #: sprites, ids 0-28. Both fields are wider than their bank (63 and 31),
    #: so without these a shot could name a sprite the device cannot draw.
    #:
    #: PENZ inherits both, and its own `atk/` is the same 58.
    SHOT_COUNT = 58
    SHOT_COUNT_M = 29
    #: "Level 1 displays as 0, and maximum is level 10, which displays as 9."
    LEVEL_OFFSET = 1
    MAX_LEVEL = 9         # 4-bit field, but only 0-9 are meaningful
    #: "Baby I is not considered, values range from Baby II (0) to Super
    #: Ultimate (5)" -- Omnipet numbers Baby II as 2, so the wire is two
    #: lower. Sending Omnipet's own number put an Ultimate out as 6, past
    #: the top of the scale the device reads.
    STAGE_OFFSET = 2
    MAX_STAGE = 5         # 3-bit field, Baby II .. Super Ultimate


class PENZ(DMX):
    # Inherits the DMX wire but not its compatibility version: a Pendulum Z
    # reports 10, its own range starts at 0, and the exchange already learns
    # the device's version and rebuilds to match (peek_version).
    #: The first release, not the 0 that means "special" -- the same
    #: reasoning as the DMX's, on this line's own numbering.
    COMPATIBILITY_VERSION = 6
    #: Mirror the device's version rather than claim one, exactly as the DMX
    #: does: `^0` XORs a digit with zero against the packet being replied to,
    #: which copies it. The toy then sees a Digimon of its own version, the
    #: most ordinary thing a battle can present. Needs a listen-and-reply
    #: exchange, so `COMPATIBILITY_VERSION` is the fallback when we open.
    DCOM_VERSION_ECHO = "^0E"

    """Digimon Pendulum Z — the DMX wire with its own charge minigame."""
    NAME = "PENZ"
    DISPLAY_NAME = "PENZ (Pendulum Z)"
    MENU_LABEL = "PENZ (Pendulum Z)"
    #: **6 to 11, not 1 to 6.** `devices.json` carries the wire numbering
    #: directly now, so an OEM pet announces what the device expects and
    #: nothing does version arithmetic at send time.
    VERSION_RANGE = (6, 11)
    #: **On the wire this line numbers its versions module + 5**, which is
    #: why a real Pendulum Z announces 6, 7, 9 or 10 where a DMX announces
    #: 0-5. The ranges are disjoint, and that is how a device tells the two
    #: apart. Hardware-confirmed by the jogress codes, six of which pin
    #: exactly one module version each and all six land: 6 -> 1 Gatomon,
    #: 7 -> 2 Ankylomon, 8 -> 3 Stingmon, 9 -> 4 Aquilamon, 10 -> 5 ExVeemon,
    #: 11 -> 6 Angemon.
    #:
    #: `module_versions_for_wire` uses it to turn a device's announced
    #: version back into a **module** version, which is what lets an
    #: opponent's index resolve -- the roster is keyed on 1-6, not on what
    #: goes over the wire. The sending side needs no arithmetic: the module
    #: declares the wire numbering as its `device_version`.
    WIRE_VERSION_OFFSET = 5
    MINIGAME = "Count Match Z"
    #: A Pendulum Z reads the level->pattern table exactly as a DMX does.
    #: An earlier reading had it one row lower, from a single battle where
    #: the device's Adult was levelled to 2; every other observation that
    #: seemed to support it turns out to be a low-stage case, covered by the
    #: rule below, because fifteen of sixteen of our own pets went out as a
    #: Child. That one battle is now treated as mis-transcribed.
    #: **This line has its own attack table**, `data/attack_patterns/PENZ.json`,
    #: keyed on the stage and a three-tier band of the level exactly as the
    #: DMX's is -- and sharing not one row with it by reference. Sixteen
    #: blocks were read off a real Pendulum Z; eight of them also appear in
    #: DMX.json and eight appear nowhere in it, and the two that agree at
    #: high stages do not agree about which stage, so the overlap is
    #: collision rather than kinship.
    #:
    #: There used to be a `LOW_STAGE_ROWS` here sending a Baby I, a Baby II
    #: and a Child into DMX.json for a fixed row. Every part of it is now
    #: either measured in this line's own file or known to be wrong: stage 1
    #: and stage 2 really are one row each (stage 2 read at all three of its
    #: levels), and stage 3 is **not** -- read at level 4, a Child draws its
    #: own tier 3, not the tier 1 the rule pinned it to. So the special case
    #: is gone and a low stage is looked up like any other.


class DMC:
    """Digital Monster Color — two 16-byte packets, four operations.

    Its own wire, not anybody else's. The document specifies it in full
    ("Digital Monster Color Battle System", extracted by cyanic) and both of
    its worked examples are reproduced byte for byte by the tests:

    Packet 1 (op 0/1): "DMCL"(32) | Operation(16) | Version(16) | Index(16)
                       | Power(16) | Attribute(16) | Check(16)
    Packet 2 (op 2/3): "DMCL"(32) | Operation(16) | Shot(16) | Outcome(16)
                       | COU(32) | Check(16)
    Check = the sum of all preceding 16-bit words, low 16 bits kept.

    Operations: 0 Player 1 Digimon Data, 1 Player 2 Digimon Data, 2 Player 1
    Battle Data, 3 Player 2 Battle Data. All four appear in one exchange, in
    that order, so each side sends two. Only operation 2 reports the victory;
    operation 3 sends 0 whatever happened.

    **The attribute encoding is DMC's own**: 0 Free, 1 Virus, 2 Data,
    3 Vaccine — not the 0=Vaccine every other device uses. ``ATTRIBUTE_MAP``
    converts on the way out and ``attribute_from_wire`` on the way back.

    This used to declare ``DCOM_WIRE = "DMX"``, which sent a real Color
    device six 2-byte DMX packets. It never answered, and there was never a
    reason to think it would: the wire was a guess where the document had the
    answer.
    """
    #: The Color wire is shared, but each line opens its packets with its
    #: own four bytes -- the Pico Terminal's analyzer decodes them as:
    #:
    #:     47444C43  'GDLC'  Digital Monster Color
    #:     47445758  'GDWX'  Digimon Color Xros Wars
    #:     47444470  'GDDp'  Digimon Pendulum Color
    #:     44563532  'DV52'  Digivice Color
    #:     44333235  'D325'  D-3 Color
    #:
    #: Sending a Pendulum Color the Digital Monster Color word is why it
    #: never answered: the layout was right and the first field was not.
    NAME = "DMC"
    DISPLAY_NAME = "DMC (Digital Monster Color)"
    MENU_LABEL = "DMC (Color)"
    PACKET_COUNT = 2
    MAGIC = 0x47444C43
    #: Four, from DMC.json -- the Color line's battles are built on the
    #: original Digital Monster's, so it takes the round count measured
    #: there. At five the winner spent 6 damage against a 5 HP bar and the
    #: versus battle drained both sides to 0.
    TURNS = 4
    #: The highest attack value a battle on this line can roll, and so the
    #: cap `GameModule.battle_damage_limit` takes. It belongs to the device
    #: line and not to the module's HP bar: a module reproducing this device
    #: with a longer bar so its adventure mode lasts is still fighting a
    #: device that only ever hits for 1 or 2. Protocols are hardcoded here, so
    #: their limit is too; a module declaring no protocol keeps the old
    #: HP-derived rule.
    DAMAGE_LIMIT = 2
    #: Drawn the same way as DMOG's, for the same reason: this line's
    #: battles are built on the original Digital Monster's. PENC inherits it.
    ATTACK_ANIMATION = "count"
    FIXED_HP = 5          # in-game versus presentation (winner 1112 / loser 1111)
    #: Ver.1 goes on the wire as 0 -- the document says so outright
    #: ("Example Value: 0 (Ver.1)"), and the Pico Terminal's analyzer indexes
    #: ["dmc1".."dmc5"] by the value received. So the five are 0-4, and a
    #: pet's version is shifted down on the way out.
    #:
    #: **5 is a sixth value and it is not a sixth Digital Monster Color.**
    #: It is what a CROSSOVER edition announces -- the Monster Hunter,
    #: Godzilla and Xros Wars devices are Digital Monster Colors with rosters
    #: of their own, and this is how one says "I am not one of the five".
    #: The analyzer reads it the same way (`device_version > 4` means a
    #: crossover, and it then asks the user which one, because the packet
    #: does not say), and it is measured twice: filmed battle 44 is a Monster
    #: Hunter edition and battle 45 an Xros Wars edition, both announcing 5.
    #:
    #: The range has to hold it, or `clamp_oem_version` sends a crossover
    #: pet's version as 0 -- "special" -- instead of its own.
    VERSION_RANGE = (0, 5)
    #: **No offset: the module carries the wire's own numbering.** It used to
    #: declare `VERSION_OFFSET = 1`, because `devices.json` listed Ver.1 to
    #: Ver.5 as `device_version` 1-5 and the wire wanted 0-4. Doing the
    #: arithmetic at send time is the thing every other line has been moved
    #: away from -- the Pendulum Z's `devices.json` says 6-11 because that is
    #: what it announces -- and it is what `version` vs `device_version` is
    #: for: the gameplay version stays 1-5 and the hardware one is 0-4.
    #:
    #: A save made before the renumber still carries the old value and is
    #: migrated on load (`GamePet`, keyed on the module), the same way the
    #: Pendulum Z's was.
    VERSION_OFFSET = 0
    #: Wire minus this is the **gameplay** version, which is what a roster
    #: lookup filters on -- `module_versions_for_wire` inverts the wire into
    #: `monster.json`'s own `version` field, not back into `device_version`.
    #:
    #: The two used to be the same number here (both 1-5), so the difference
    #: was invisible; with `device_version` renumbered to the wire's 0-4 they
    #: are one apart, and inverting the wire straight would have named the
    #: Digimon one release too low. The known-good reading is the check: a
    #: real Ver.2 DMC answered `47444C4300000001000A0028000193BB`, wire
    #: version 1 with index 10, and it was holding a **Vegiemon** -- which is
    #: gameplay version 2, index 10.
    WIRE_VERSION_OFFSET = -1
    DCOM_WIRE = "DMC"     # its own 2-packet, 16-byte layout
    #: A real Color device takes Player 1 for itself. Sent a C1 with our own
    #: operation 0, a Ver.2 DMC answered with operation 0 as well -- both of
    #: us claiming the same role -- and then waited for the Player 2 packets
    #: that never came. So we answer instead: it sends operation 0, we send
    #: 1, it sends 2 (the one carrying the verdict), we send 3. That is also
    #: the order the document gives, "in the above order for each packet".
    DCOM_TURN = DCOM_TURN_LISTEN
    DEVICE_IS_PLAYER_ONE = True
    MINIGAME = "None"
    #: Bytes per packet on this wire, against 2 everywhere else, and they go
    #: out WHOLE -- the Color protocol carries a 16-byte packet as one group
    #: rather than eight. Known-good codes from wificom-lib's digiroms.txt:
    #:
    #:   C1-47444C4300000000000E00AA00019440-47444C430002003000000000000093B9
    #:
    #: which also gives the op letter: "C", not the "V" every other wire
    #: uses. Sending V2 with sixteen four-digit groups is why a Color device
    #: never answered -- the layout was right and the transport was not.
    PACKET_BYTES = 16
    DCOM_OP = "C"
    #: Omnipet's attribute order is Va, Da, Vi, Free. DMC's is Free, Virus,
    #: Data, Vaccine, so the two are neither equal nor reversed.
    ATTRIBUTE_MAP = {0: 3, 1: 2, 2: 1, 3: 0}
    #: From the DMC module (battle_attribute_advantage 5, ..._power false),
    #: and the document gives the same formula every wire uses:
    #: "hitrate = ((playerPower * 100)/(playerPower + opponentPower)) +
    #: attributeAdvantage". Held here rather than read from the module,
    #: because the protocol is usable without it installed.
    ATTRIBUTE_ADVANTAGE = 5
    ATTRIBUTE_ADVANTAGE_ON_POWER = False
    #: Vaccine beats Virus, Virus beats Data, Data beats Vaccine -- written in
    #: DMC's own encoding (Free 0, Virus 1, Data 2, Vaccine 3), so it does not
    #: read like the cycle every other wire uses.
    ATTRIBUTE_BEATS = {3: 1, 1: 2, 2: 3}
    #: The four roles are numbered from here: 0 Player 1 Digimon Data, 1
    #: Player 2, 2 Player 1 Battle Data, 3 Player 2. A Pendulum Color counts
    #: the same four from 0x10, which is what `PENC.OPERATION_OFFSET` says --
    #: and reading the verdict at a bare `== 2` is what threw its away.
    OPERATION_OFFSET = 0
    MAX_INDEX = 0xFFFF
    MAX_POWER = 0xFFFF
    MAX_SHOT = 0xFFFF
    #: The Colour line draws from the GLOBAL `assets/atk`, which is its own
    #: numbering -- 117 sprites, a contiguous 1-117, ids 0-116 on the wire.
    #: That library is the Digital Monster Color's set, which is why every
    #: other line's module was written against it and had to be given its own
    #: folder; here it is simply correct.
    #:
    #: The field is sixteen bits, so it would carry 65534 -- by far the
    #: widest gap between a field and its bank on any wire. PENC inherits it,
    #: and so do the other modules riding this format: DMGZ has no folder of
    #: its own, and DMH's holds the same 117.
    SHOT_COUNT = 117
    MAX_HP = 0xFFFF
    #: The layout has no charge field at all -- a Color device plays no
    #: pre-battle minigame. These exist so the shared charge plumbing has an
    #: answer; nothing of it reaches the wire.
    CHARGE_SCALE = "quality"
    MAX_CHARGE = 3


class PENC(DMC):
    """Digimon Pendulum Color — its own protocol on the Colour layout.

    **A Pendulum Color supports two protocols.** It speaks the Digital
    Monster Color's in compatibility mode, and it has its own, which is not
    that one with a different word at the front: it plays a charge the DMC
    has no field for, fights at **three** hit points where the DMC fights at
    five, spends **10** on the hit rate where the DMC spends 5, and numbers
    its versions by a map rather than an offset.

    What it does share is the Colour line's packet LAYOUT -- two 16-byte
    packets, the 16-bit word-sum check and the Free/Virus/Data/Vaccine
    attribute order -- and 43 codes in `utilities/DIGIROM` confirm it: all 68
    of their packets verify against that checksum. Its operations are the
    DMC's four shifted up by 0x10, plus 0x14 and 0x16 for jogress.

    **The document Omnipet was built from covers the DMC only**, so the rest
    is being worked out from DigiROMs -- and they do not reach the battle.
    Every op-0x12 packet on record is byte-identical, six background-unlock
    codes differing only in the version in packet 1, so what varies during a
    real battle is exactly what nothing here has seen.
    """
    NAME = "PENC"
    DISPLAY_NAME = "PENC (Pendulum Color)"
    MENU_LABEL = "PENC (Pendulum Color)"
    MAGIC = 0x47444470
    #: Eight versions, numbered from zero like the Digital Monster Color's.
    VERSION_RANGE = (0, 7)
    #: **A map, not an offset.** This line numbers its releases in shipping
    #: order and the module does not: the Virus Busters set is the SIXTH
    #: release, so it goes out as wire **5** while the module calls it 0, and
    #: the two later sets line up at 6 and 7 unchanged.
    #:
    #: The flat `VERSION_OFFSET` it inherits gets five of the eight right by
    #: coincidence and breaks the rest -- the Virus Busters collided with
    #: Nature Spirits on wire 0, so a Virus Busters pet announced itself as
    #: a Nature Spirits one, and Saiyu Warriors and Toho Braves each went out
    #: one low. This is the same map the jogress ROMs carry
    #: (`data/jogress/roms.json`, PENC's `version_map` inverted), which is
    #: hardware-derived, so the battle wire and the jogress wire finally
    #: agree about what a Pendulum Color calls itself.
    VERSION_MAP = {0: 5, 1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 6, 7: 7}
    #: **Three, not the Digital Monster Color's five.** The Pendulum Color
    #: manual is explicit: "each Digimon has 3 health points which will be
    #: reduced by 1 for a normal hit and by 2 for a super hit". It had been
    #: inheriting the DMC's 5.
    FIXED_HP = 3
    #: **+10 on the hit rate**, where the Digital Monster Color spends 5.
    #: The manual gives the formula outright -- "hitrate = ((playerPower *
    #: 100)/(playerPower + opponentPower)) + attributeAdvantage - handicap"
    #: -- with attributeAdvantage "10 if you have an attribute advantage,
    #: -10 if you have an attribute disadvantage". Its own module said 10 all
    #: along; the 5 was inherited from the DMC.
    #:
    #: The manual adds that a Pendulum Color fighting a Digital Monster
    #: Color uses "5/-5 instead of 10/-10", which nothing here reads yet: the
    #: advantage is taken from one side's format, not from the pairing.
    ATTRIBUTE_ADVANTAGE = 10
    #: **This line fights; the Digital Monster Color exchanges a verdict.**
    #: They share a packet layout and not a battle, and assuming otherwise is
    #: what put the verdict in the wrong packet for every PENC battle. The
    #: flag is what the shared paths branch on, so a third Colour line that
    #: fights (DMXW) needs no new special case.
    FOUGHT_BATTLE = True
    #: **99, not 100.** "hitrate -- This number represents the chance of your
    #: hit connecting, out of 100. The maximum value is 99, even if the
    #: calculation would exceed that amount." So a Pendulum Color keeps one
    #: round in a hundred missing however lopsided the power is, where a
    #: clamp at 100 makes the hit a certainty. Only this line states it, so
    #: only this line declares it -- the calculator on humulos caps at 100
    #: and disagrees with its own manual here; the manual is the more
    #: specific claim and this follows it.
    MAX_HIT_RATE = 99
    #: The four roles are the DMC's shifted up: 0x10 Player 1 Digimon Data,
    #: 0x11 Player 2 Digimon Data, 0x12 Player 1 Battle Data, 0x13 Player 2
    #: Battle Data. A real Pendulum Color answered ours with 0x10, and the
    #: PenC battle codes in utilities/DIGIROM use 0x10 and 0x12 throughout.
    #: (Its jogress codes use 0x14, which is a different operation again.)
    OPERATION_OFFSET = 0x10
    #: **The low word of packet 2's COU is the charge, and it is measured.**
    #: The DMC leaves that half at zero and a Pendulum Color does not, which
    #: is what first made it the candidate -- but every op-0x12 packet in the
    #: DigiROM dump carries a flat 2, because those are six background-unlock
    #: codes and not battles. Six filmed battles against a real device gave
    #: the four values a charge actually produces:
    #:
    #:      no colour   (0-1 super hits)   ->   3
    #:      worst       (2 super hits)     ->   8
    #:      middle      (3-4 super hits)   ->  11
    #:      own colour  (Megahit, 5)       ->  14
    #:
    #: and they are keyed on the **super-hit band**, not the colour and not
    #: the shake count: the device's Data pet ranks Yellow > Red > Blue while
    #: the colours arrive Blue, Yellow, Red, so red takes the most shakes and
    #: still lands between blue and yellow. `data/attack_patterns/PENC.json`
    #: holds the table and `battle_utils.get_penc_wire_charge` reads it.
    #:
    #: This value is what a packet carries when there is no charge to state
    #: -- a scan, or a code that is not a battle. A battle packet takes the
    #: charge's own, and sending this instead is what made every PENC battle
    #: look identical however the player rolled.
    BATTLE_TRAILER = 2
    #: **A Pendulum Color plays a charge and a Digital Monster Color does
    #: not**, which is one of the things that makes this its own protocol
    #: rather than the DMC's with a different word at the front. Where the
    #: result goes is not known -- see `BATTLE_TRAILER` for the candidate --
    #: so for now it is what the player does, not what the packet says.
    MINIGAME = "Count Match Color"
    #: **Five rounds, not the Digital Monster Color's four.** The DMC's four
    #: are a presentation of a verdict -- three traded singles and the
    #: winner's double, which is exactly the 5 HP it spends. A Pendulum Color
    #: fights instead, against 3 HP.
    #:
    #: **Six, not the five the charge fires.** Every row of the Colour
    #: family's shared pool stores six values, and this line's hit mask has
    #: twice been seen with bit 5 set. The charge produces five shots on
    #: screen and that is what fixed the number here; the charge is not the
    #: battle. At three hit points a sixth round is rare rather than
    #: unreachable, which is why no filmed battle has run that long.
    TURNS = 6
    #: The charge is the raw super-hit count, 0-5, not the 0-3 band -- the
    #: band cannot separate a Megahit from the middle rung, and on this line
    #: that is two damage across a three-point battle.
    CHARGE_SCALE = "super hits"
    MAX_CHARGE = 5
    #: A versus battle has no charge to play -- the player would be shaking
    #: against themselves -- so the format names a fixed one. Two super hits
    #: is the manual's lowest winning band, which is the same "not the
    #: weakest, not the strongest" choice PENOG's 10-of-40 makes.
    VERSUS_CHARGE = 2


class DMXW(DMC):
    """Digimon Color Xros Wars — its own protocol on the Colour layout.

    **A third line that speaks two protocols.** Like a Pendulum Color it can
    battle a Digital Monster Color in compatibility mode, and it has a system
    of its own for battling other Xros Wars devices — which is not that one
    with a different word at the front.

    **Almost nothing about it is documented.** The `utilities/DIGIROM` dump
    carries **no GDWX codes at all**, and the Pico Terminal's analyzer knows
    this magic only as "a DMC at device version 5" plus one index fold, so it
    describes the compatibility view and not this. What is here comes from a
    real device and from what the shape of the Colour family makes checkable.

    **One packet is measured**, and it settles the layout:

        47445758 0020 0000 0004 0028 0000 9EE8

    which is `GDWX`, operation **0x20**, version 0, index 4, power 40,
    attribute 0 (Free), and a checksum that verifies against the same 16-bit
    word sum the whole Colour family uses. So the layout is the Colour
    layout, and the operations are the DMC's four shifted up by **0x20** —
    the same relationship PENC's 0x10 has. The device sent it unprompted
    while we were listening on turn 2, so it takes Player 1 as its siblings
    do.

    **The battle is PENC-shaped, not DMC-shaped.** Three hit points, a
    charge that is played before the fight, super hits counted, and a Megahit
    at the top — all reported off the device. That is a real battle rather
    than the DMC's exchanged verdict, so this class follows PENC's treatment
    and not its parent's.
    """
    NAME = "DMXW"
    DISPLAY_NAME = "DMXW (Digimon Color Xros Wars)"
    MENU_LABEL = "DMXW (Color Xros Wars)"
    #: `GDWX`. Measured off a real device; also what the Pico Terminal's
    #: analyzer lists for this line.
    MAGIC = 0x47445758
    #: The DMC's four roles shifted up by 0x20 -- 0x20 Player 1 Digimon Data,
    #: 0x21 Player 2, 0x22 Player 1 Battle Data, 0x23 Player 2. **0x20 is
    #: measured**; the other three are the family's own arithmetic, the same
    #: step PENC takes at 0x10, and are the first thing a live exchange will
    #: confirm or break.
    OPERATION_OFFSET = 0x20
    #: **One release, so one wire version.** The module carries three
    #: rosters -- Xros Heart, Blue Flare and the partners -- but `devices.json`
    #: declares a single physical device, and its two eggs are versions 1 and
    #: 2 of that one device. So the three are evolution lines within a
    #: release rather than releases, and the measured packet agrees: a real
    #: device holding a version 1 Digimon announced version **0**.
    #:
    #: `devices.json` says device_version **5**, which is the number a
    #: crossover announces on the Digital Monster Color's wire -- the one
    #: field has to serve both wires. Declaring the range as (0, 0) resolves
    #: it without touching the module: `clamp_oem_version` sends 0 for
    #: anything outside, which is the only version this wire has.
    #:
    #: **Settled: there is one Xros Wars device, so there is one version.**
    #: A version number on the wire names a hardware release, and this line
    #: had exactly one. The module's three rosters are Omnipet's own
    #: convention for organising a device's Digimon -- which is what the
    #: `version` / `device_version` split exists for -- and never reach the
    #: wire.
    #:
    #: It follows that the index alone cannot carry a stage here (11 of the
    #: module's 32 indexes name two), and nothing needs it to: the opponent's
    #: attack row comes from the SELECTOR in its battle packet, not from its
    #: stage. So this line has no `data/rosters/` file and wants none.
    VERSION_RANGE = (0, 0)
    #: Reported off the device, and what the module has always declared for
    #: its own battles (`battle_global_hit_points: 3`).
    FIXED_HP = 3
    #: Six, as on the Pendulum Color: the firmware's own rows are six values
    #: long, which is where the number comes from on both lines.
    TURNS = 6
    #: **Excite training's bar**, which is the Digital Monster X's minigame
    #: and what this device plays. It scores 0-3, and the device produces
    #: exactly four attack rows, so the band IS the key.
    MINIGAME = "Xai Bar"
    CHARGE_SCALE = "quality"
    MAX_CHARGE = 3
    #: Mid-table, the same "not the weakest, not the strongest" choice every
    #: other format's versus charge makes.
    VERSUS_CHARGE = 1
    #: **Zero: this line has no attribute.** Every Xros Wars Digimon is Free
    #: -- the module's roster throughout, and the measured packets agree
    #: (attribute 0 on both sides). The field exists only because the layout
    #: is the Digital Monster Color's, and the device is not believed to read
    #: it. Inheriting the DMC's 5 left a triangle that could fire against a
    #: compatibility opponent and change a battle on a rule this device does
    #: not have.
    ATTRIBUTE_ADVANTAGE = 0
    #: Assumed, not measured. The Pendulum Color's manual pins 99 and nothing
    #: says what this line uses; at one round in a hundred the difference is
    #: not worth a capture, and there is no clean way to test it.
    MAX_HIT_RATE = 100
    #: Reported off the device: three hit points, a charge played first,
    #: super hits counted and a Megahit at the top. That is a fought battle,
    #: not the Digital Monster Color's exchanged verdict.
    FOUGHT_BATTLE = True


# OEM mode: when the pet's module battle_protocol matches the connected
# device's format, the pet's real index/version are sent so the device can
# run unlocks; out-of-range versions are sent as 0 (special).  Shared by
# dcom_view and battle_encounter_dcom (previously duplicated in both).
# One entry per battle format, each taking the range its own class declares,
# so the two cannot drift. The literal that used to be here had grown a
# 'PEN' key no format is called, listed 'PENC' twice, and had **no 'PENOG'
# at all** -- so the Pendulum's own wire silently fell through to the
# (1, 5) default instead of the (0, 5) it declares.
VERSION_RANGES = {
    'DMOG': DMOG.VERSION_RANGE,
    'PENOG': PENOG.VERSION_RANGE,
    'DM20': DM20.VERSION_RANGE,
    'PEN20': PEN20.VERSION_RANGE,
    'DMX': DMX.VERSION_RANGE,
    'PENZ': PENZ.VERSION_RANGE,
    'DMC': DMC.VERSION_RANGE,
    'PENC': PENC.VERSION_RANGE,
    'DMXW': DMXW.VERSION_RANGE,
}


#: Every battle format that can be selected, in menu order. Both the DCom
#: menu and the versus protocol menu are built from this, so the two can
#: never offer different lists -- the versus one used to be its own literal
#: and had simply never had PENZ added to it.
BATTLE_FORMATS = ('DMOG', 'PENOG', 'DM20', 'PEN20', 'DMX', 'PENZ', 'DMC',
                  'PENC', 'DMXW')


def menu_entries():
    """``[(battle_format, label), ...]`` for a protocol menu, in menu order."""
    return [(name, get_constants(name).MENU_LABEL) for name in BATTLE_FORMATS]


def fights_its_battle(battle_format: str) -> bool:
    """Whether this format fights round by round or exchanges a verdict.

    The Colour layout carries both kinds. A Digital Monster Color sends one
    bit and the rounds are ours to present; a Pendulum Color and a Color
    Xros Wars play a charge and fight it out, so their rounds are real. The
    shared paths branch on this rather than on a format name, because
    "PENC or DMXW" written out nine times is how the third one gets missed.
    """
    limits = get_constants(battle_format)
    return bool(limits and getattr(limits, 'FOUGHT_BATTLE', False))


def versus_protocol(battle_format: str):
    """The BattleProtocol the in-game simulator runs a format under.

    PENZ shares DMX's simulation as it shares its wire -- the two differ in
    the charge minigame, not in the battle.
    """
    from battle.sim.models import BattleProtocol
    return {
        'DMOG': BattleProtocol.DMOG_BS,
        'PENOG': BattleProtocol.PENOG_BS,
        'PENC': BattleProtocol.DMC_BS,
        'DM20': BattleProtocol.DM20_BS,
        'PEN20': BattleProtocol.PEN20_BS,
        'DMX': BattleProtocol.DMX_BS,
        'PENZ': BattleProtocol.DMX_BS,
        'DMC': BattleProtocol.DMC_BS,
        'DMXW': BattleProtocol.DMC_BS,
    }.get(battle_format, BattleProtocol.DM20_BS)


#: The packet layouts a DCom exchange can use, by ``DCOM_WIRE`` name. Three
#: are in use; PEN20's own layout is implemented and selectable but no format
#: currently points at it (see PEN20.DCOM_WIRE).
#: Wire name -> the class that describes that packet layout. Every format's
#: DCOM_WIRE must appear here; get_wire refuses an unknown one rather than
#: falling back, because a wrong wire is six DMX packets at a Color device
#: that will never answer them.
WIRE_FORMATS = {'DMOG': DMOG, 'PENOG': PENOG, 'DM20': DM20, 'DMX': DMX,
                'PEN20': PEN20, 'DMC': DMC}

#: Format names that changed. Read but never written; a module saved after
#: the rename carries the new one.
LEGACY_FORMAT_NAMES = {'DM': 'DMOG'}


def canonical_format(name):
    """The current name for a battle format, translating legacy spellings."""
    return LEGACY_FORMAT_NAMES.get(name, name)


def get_constants(protocol_name: str):
    """Constants class for a battle format name, or None if unknown."""
    return {
        'DMOG': DMOG, 'PENOG': PENOG, 'DM20': DM20, 'PEN20': PEN20,
        'DMX': DMX, 'PENZ': PENZ, 'DMC': DMC, 'PENC': PENC, 'DMXW': DMXW,
    }.get(canonical_format(protocol_name))


def damage_limit(protocol_name: str):
    """The damage cap a module declaring *protocol_name* fights under.

    ``GameModule.battle_damage_limit`` used to be derived from the module's
    own ``battle_global_hit_points``, which conflated two different things:
    how long an adventure battle should last, and how hard the device it
    reproduces can hit. A module mimicking the Digital Monster with a longer
    HP bar so its adventure mode runs on is still a Digital Monster, and
    still only hits for 1 or 2 -- but the old rule handed it a limit of 3,
    and handed DMGZ and DMH (both DMC, both with no global HP set) a limit of
    **99**, so their battles could roll a critical on a wire that has none.

    Returns None for a module that declares no protocol -- or one we have no
    constants for -- and the caller keeps the HP-derived rule for it.
    """
    constants = get_constants(protocol_name)
    return getattr(constants, 'DAMAGE_LIMIT', None) if constants else None


#: The attribute cycle in the 2-bit code every wire but the Colour line uses
#: (Va 0, Da 1, Vi 2, Free 3): Vaccine beats Virus, Virus beats Data, Data
#: beats Vaccine. Free sits in neither half, so it never scores either way.
#: DMC writes its own (`DMC.ATTRIBUTE_BEATS`) because that line orders the
#: four differently, which is why this is a default and not the rule.
DEFAULT_ATTRIBUTE_BEATS = {0: 2, 2: 1, 1: 0}

#: The ceiling a rolled hit rate is clamped to. 100 makes a certainty of a
#: hit, which is what every wire here has always done -- PENC's manual is the
#: one that states otherwise ("the maximum value is 99, even if the
#: calculation would exceed that amount"), so only that format declares its
#: own.
DEFAULT_MAX_HIT_RATE = 100


def attribute_advantage(limits, attacker, defender):
    """What the attribute triangle is worth to *attacker* against *defender*.

    Both attributes are in the format's OWN encoding -- the 2-bit code the
    wire carries -- because that is what a Digimon built by `pet_to_digimon`
    holds. The Colour line orders the four differently and says so in its own
    `ATTRIBUTE_BEATS`; everything else takes `DEFAULT_ATTRIBUTE_BEATS`.

    Positive for an advantage, negative for a disadvantage, 0 for neither
    (which is every pairing involving Free).
    """
    beats = getattr(limits, 'ATTRIBUTE_BEATS', None) or DEFAULT_ATTRIBUTE_BEATS
    value = getattr(limits, 'ATTRIBUTE_ADVANTAGE', 0)
    if beats.get(attacker) == defender:
        return value
    if beats.get(defender) == attacker:
        return -value
    return 0


def hit_rate(limits, power, attribute, opponent_power, opponent_attribute,
             handicap=0):
    """The chance *this* Digimon lands a hit, as a percentage.

    One formula for every wire -- `power * 100 / (power + opponentPower)`,
    plus the attribute triangle -- because that is what each line's manual
    states in the same words. Only what feeds it differs by device: the X
    lines spend their advantage on Power before the ratio is taken
    (`ATTRIBUTE_ADVANTAGE_ON_POWER`) rather than on the roll after it, and
    PENC subtracts a handicap.

    **The handicap is the DEFENDER's.** "Used in Quest Mode only, certain
    Digimon have a handicap that will reduce your hitrate" -- so it is a
    property of the Digimon being attacked, and the caller passes that side's
    value. Quest Mode is Adventure Mode here, which is the only place a
    handicap is ever set.
    """
    advantage = attribute_advantage(limits, attribute, opponent_attribute)
    if getattr(limits, 'ATTRIBUTE_ADVANTAGE_ON_POWER', False):
        # **The bonus goes to whoever HAS the advantage.** "Having an
        # attribute advantage will effectively grant a +32 bonus to your
        # Digimon's Power stat" -- a bonus to one side, not a penalty on the
        # other, and at equal power those are different ratios: 92/(92+60) is
        # 0.605 where (60-32)/(28+60) is 0.318.
        #
        # The roll-based lines really are symmetric and stay that way: PENC's
        # manual spells out "10 if you have an attribute advantage, -10 if
        # you have an attribute disadvantage".
        if advantage > 0:
            power += advantage
        elif advantage < 0:
            opponent_power += -advantage
        advantage = 0
    total = power + opponent_power
    rate = (power * 100 / total if total else 0) + advantage - handicap
    return max(0, min(rate, getattr(limits, 'MAX_HIT_RATE',
                                    DEFAULT_MAX_HIT_RATE)))


def get_wire(battle_format: str):
    """The packet layout *battle_format* is actually sent over.

    Several formats share one layout -- PEN20 goes out as DM20, PENZ and DMC
    as DMX -- and differ only in the charge minigame. Everything about the
    exchange (packet count, field widths, HP, validation, parsing) belongs to
    the layout; only the minigame and the OEM version range belong to the
    format.
    """
    constants = get_constants(battle_format) or DM20
    wire = getattr(constants, 'DCOM_WIRE', None)
    if wire not in WIRE_FORMATS:
        raise ValueError(
            f"{battle_format} declares no known DCOM_WIRE ({wire!r}). "
            "Every format names its own layout -- there is no default, "
            "because a wrong wire is packets the device will never answer.")
    return WIRE_FORMATS[wire]


def module_versions_for_wire(battle_format: str, wire_version):
    """Which module versions would have produced this wire version.

    The inverse of what goes out, and the thing that lets an opponent's index
    be looked up: an index is per-version, and on the X lines most of them
    name several Digimon across the roster, so without the version there is
    nothing to resolve.

    ``None`` means the number says nothing -- it is outside anything the line
    uses, which is what a device sends when it has nothing to say (a real
    Ver.20th announces 0 in an ordinary battle). Searching the whole roster
    is the right answer then; inventing a version is not.

    A line declaring `WIRE_VERSION_OFFSET` numbers the wire away from its
    module versions outright, and the Pendulum Z does: it announces module +
    5, so 9 is module 4. Inverting that through `clamp_oem_version` found
    nothing at all -- no module version maps to 9 -- so every Pendulum Z
    opponent fell back to a bare attribute name and its generic sprite.
    """
    if wire_version is None:
        return None
    limits = get_constants(battle_format)
    mapping = getattr(limits, 'VERSION_MAP', None) if limits else None
    if mapping:
        found = [module for module, wire in mapping.items()
                 if wire == wire_version]
        return found or None
    offset = getattr(limits, 'WIRE_VERSION_OFFSET', 0) if limits else 0
    if offset:
        module = int(wire_version) - offset
        return [module] if module > 0 else None
    v_min, v_max = VERSION_RANGES.get(canonical_format(battle_format), (1, 5))
    if not v_min <= wire_version <= v_max:
        return None
    return [v for v in range(0, 32)
            if clamp_oem_version(battle_format, v) == wire_version] or None


def clamp_oem_version(battle_format: str, version: int) -> int:
    """The version to put in an OEM packet, or 0 when out of the device's range.

    A version the real device does not have is read as "special" there, and 0
    is how every protocol spells that.
    """
    v_min, v_max = VERSION_RANGES.get(battle_format, (1, 5))
    try:
        version = int(version)
    except (TypeError, ValueError):
        return 0
    limits = get_constants(battle_format)
    # A line whose releases and module versions are in different orders needs
    # a map rather than an offset -- see PENC.VERSION_MAP.
    mapping = getattr(limits, 'VERSION_MAP', None) if limits else None
    if mapping:
        return mapping.get(version, 0)
    # Wires that number their versions from zero take the pet's version
    # shifted down; everything else carries it as it stands.
    version -= getattr(limits, 'VERSION_OFFSET', 0) if limits else 0
    # And a wire where two module versions share one: the Pendulum ships .0
    # and .5 of each release and "the .5 versions do NOT have a separate
    # version from their .0 counterparts", so module 3 and 4 both go out as
    # wire 1 -- "Pendulum 2.X", exactly what the document's example says.
    divisor = getattr(limits, 'VERSION_DIVISOR', 1) if limits else 1
    if divisor > 1:
        version = (version - 1) // divisor
    if v_min <= version <= v_max:
        return version
    # A line may prefer the nearest real version to "special" -- see
    # DMOG.CLAMP_VERSION_TO_RANGE for why that is not the general rule.
    if limits is not None and getattr(limits, 'CLAMP_VERSION_TO_RANGE', False):
        return v_max if version > v_max else v_min
    return 0



def get_compatibility_version(battle_format):
    """The version a compatibility battle announces on this wire.

    A compatibility battle sends index 0 -- "an outsider", a Digimon the
    device has no roster entry for -- and used to send version 0 with it.
    Version is not a free field: it is what the device reads to decide
    whether special content should unlock, and each format declares the
    range it accepts. 0 sits outside the DMX's 1-6, and the two battles that
    sent it are the only two of ten where the device drew the opponent's
    attacks from the wrong row of its pattern table. So the DMX announces 1.

    The formats confirmed working on hardware with 0 keep it until each is
    tested the same way; the value lives on the format so they can move one
    at a time.
    """
    limits = get_constants(battle_format)
    return getattr(limits, 'COMPATIBILITY_VERSION', 0) if limits else 0
