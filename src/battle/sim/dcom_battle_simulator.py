"""Device packet codecs, validation and transcript replay.

PacketExchange drives local versus and WiFiCom one packet at a time. Stock
cable firmware receives its supported symbolic DigiROM plan and reports the
actual sent/received packets; those use the same validated replay engine.
Each battle format selects its own rules independently of the byte layout.
"""
import time
import re
from typing import List, Optional, Dict
from battle.dcom.dcom_controller import DComController
from battle.dcom.dcom_protocol import ProtocolType
from battle.sim.models import Digimon, BattleResult, DigimonStatus, BattleProtocol
from battle.sim.battle_simulator import (BattleSimulator, DMDevice, DM20Device,
                                         PENOGDevice,
                                         PEN20Device, DMXDevice, DMCDevice)
from battle.sim import protocol_constants
from core import runtime_globals
from battle.sim.battle_utils import get_dm20_single_battle_attack_pattern


#: Fallback for callers that still identify a battle by a DCom signal type.
#: Every format is sent over ``V`` timings, so this only names the format the
#: menu treats as that type's default.
FORMAT_FOR_PROTOCOL = {
    ProtocolType.V_PET: 'DM20',
    ProtocolType.PEN_X: 'PEN20',
    ProtocolType.COLOR: 'DMX',
}

#: Attribute code -> the generic name a nameless opponent is shown under.
ATTRIBUTE_NAMES = {0: "Va", 1: "Da", 2: "Vi", 3: "Free"}

#: What an opponent is called when the wire named no Digimon we could
#: resolve -- the attribute it *did* send, and the sprite set drawn for it.
#:
#: **Free is `Fr` and not `Free`**, because the shared libraries ship
#: `Fr_dmc` and have no `Free_dmc` at all. The Colour parser spelled it out
#: in full and so drew nothing: no Digimon, and not even a fallback, which is
#: filmed battles 44 and 45 exactly. DM20, DMX and PEN20 each carried their
#: own copy of this table with the short spelling and were fine; one table
#: now, so a fourth copy cannot go the other way.
FALLBACK_NAMES = {0: "Va", 1: "Da", 2: "Vi", 3: "Fr"}

#: Internal attribute strings -> the 2-bit code every protocol puts on the wire.
ATTRIBUTE_CODES = {"Va": 0, "Vaccine": 0, "Da": 1, "Data": 1,
                   "Vi": 2, "Virus": 2, "Fr": 3, "Free": 3, "": 3}


def is_oem_pet(pet, battle_format: str) -> bool:
    """Whether *pet* is native to the device line being battled.

    An OEM battle sends the pet's real index and version so the toy can run
    its own unlocks against it; anything else is a compatibility battle and
    sends zeroes, which every device reads as "an outsider".
    """
    module_name = getattr(pet, 'module', '')
    if not module_name or not battle_format:
        return False
    try:
        from utils.module_utils import get_module
        module = get_module(module_name)
        if not module:
            return False
        declared = protocol_constants.canonical_format(
            getattr(module, 'battle_protocol', ''))
        return declared == protocol_constants.canonical_format(battle_format)
    except Exception:
        return False


def module_for_format(battle_format: str):
    """The installed module that reproduces the device line *battle_format*.

    A DCom or WiFiCom opponent is a real toy, not one of our pets, so its
    sprites belong to the module that reproduces that toy rather than to
    whatever module the player happens to be raising -- which is what the
    payload used to hand it, so a Digital Monster fought from a Pendulum Z
    save drew Pendulum Z attack sprites.

    The lookup is on the module's declared ``battle_protocol`` and not on its
    name, because names move: the DM module is being renamed to DMOG, and PEN
    already declares PENOG while keeping its own name. An exact name match is
    preferred first, since several modules can declare one line -- DMGZ, DMH
    and DMXW all speak DMC, and the DMC module is the one that *is* it.

    Returns None when the player does not own the module, which is the
    ordinary case; the caller then keeps its existing fallback.
    """
    found = modules_for_format(battle_format)
    return found[0] if found else None


def modules_for_format(battle_format: str):
    """Every installed module reproducing *battle_format*, best match first.

    Several modules can declare one line, and on the Colour line that is the
    ordinary case rather than an oddity: **DMC, DMGZ, DMH and DMXW all speak
    DMC**, because the Godzilla, Monster Hunter and Xros Wars editions are
    Digital Monster Colors with their own rosters. The module named after the
    format is the one that *is* it and comes first; the rest are its
    crossovers, and an opponent that resolves on none of the format's own
    roster can still be one of theirs.

    The lookup is on the declared ``battle_protocol`` and not on the name,
    because names move -- the DM module was renamed DMOG, and PEN declares
    PENOG while keeping its own name.
    """
    canonical = protocol_constants.canonical_format(battle_format)
    if not canonical:
        return []
    modules = getattr(runtime_globals, 'game_modules', None) or {}
    names = ([canonical] if canonical in modules else [])
    names += sorted(name for name in modules if name != canonical)
    found = []
    for name in names:
        module = modules.get(name)
        declared = protocol_constants.canonical_format(
            getattr(module, 'battle_protocol', '') or '')
        if declared == canonical:
            found.append(module)
    return found


def penc_super_hits_from_wire_or_zero(opponent):
    """The opponent's charge if its battle packet has been read, else 0.

    Packet 1 carries no charge -- it is in packet 2's COU -- so a verdict
    declared from a first attempt has to assume the weakest one. It is the
    honest assumption: claiming a charge we have not seen would put a number
    on the wire that nothing measured.
    """
    return getattr(opponent, 'mini_game', 0) or 0


def colour_trailer(battle_format: str, digimon) -> int:
    """What packet 2's COU low word carries for this battle.

    A Digital Monster Color leaves it at zero; a Pendulum Color puts a
    **selector naming a row of its attack table** there, which depends on the
    Digimon's stage as well as the colour band its charge landed. Six pairs
    are measured, each off a device whose Digimon resolved to a roster record
    and whose colour the battle heading records.

    It used to be a flat `BATTLE_TRAILER`, which is what the static
    background-unlock codes carry and is not one of the values a battle
    produces -- so the device was told the same thing however the player
    rolled, which is exactly what a real Pendulum Color showed. Then it was
    keyed on the **super-hit count**, which cannot represent the wire: stages
    3 and 4 pay the same counts and send different selectors.

    `mini_game` holds the raw super-hit count on this line, so it is crossed
    back to a band with the pet's own stage.
    """
    limits = protocol_constants.get_constants(battle_format)
    default = getattr(limits, 'BATTLE_TRAILER', 0) or 0
    name = protocol_constants.canonical_format(battle_format)

    if name == 'DMXW':
        # **Its selection table is the firmware's, so there is nothing to
        # approximate.** Stage, effort tier and Excite band pick a pool index
        # outright. Sending the flat default instead announced pool row 0 --
        # all normal hits -- however the player charged, and the device drew
        # our shots from it: filmed battles 62 and 63 charged 3 and 2 and
        # both threw three 1s. The same shape as PENC's flat 2.
        from battle.sim.battle_utils import get_dmxw_selector
        return get_dmxw_selector(getattr(digimon, 'stage', 3) or 3,
                                 getattr(digimon, 'mini_game', 0) or 0,
                                 getattr(digimon, 'effort', 0) or 0)

    if name != 'PENC':
        return default
    from battle.sim.battle_utils import (get_penc_wire_charge,
                                         penc_band_for_super_hits,
                                         penc_wire_charge_is_measured,
                                         PENC_BANDS)
    stage = getattr(digimon, 'stage', 1) or 1
    band = penc_band_for_super_hits(stage,
                                    getattr(digimon, 'mini_game', 0) or 0)
    selector = get_penc_wire_charge(stage, band)
    if not penc_wire_charge_is_measured(stage, band):
        # Said out loud rather than passed off as known: no device has been
        # read at this stage and band, so this is the same band's selector
        # from the nearest stage that has.
        runtime_globals.game_console.log(
            "[DComBattleSimulator] PENC: no selector measured for stage %s / "
            "%s -- sending 0x%04X, the nearest stage's"
            % (stage, PENC_BANDS[band], selector))
    return selector


def pet_to_digimon(pet, battle_format: str, minigame_result: int = 0) -> Digimon:
    """Build the packet payload for *pet* on *battle_format*.

    One conversion for both DCom entry points -- the connection view and the
    battle encounter each had their own, and they had drifted apart on which
    power and which version to send.

    Power and HP come from ``get_power``/``get_hp`` so the module's bonus
    rules reach the real device, the same values the in-game battle fights
    with. Attack sprite ids go out 0-based (Omnipet reserves 0 for "no
    sprite"). ``device_version`` is the hardware revision, which is what the
    protocols key off -- not the gameplay version used for evolutions.

    Every field is clamped to the width the wire actually has -- the wire the
    format is sent over, which for PEN20 is DM20's and for PENZ and DMC is
    DMX's. Omnipet's stats outgrow several of those fields (a levelled Super
    Ultimate has more HP than DMX's 5-bit one can hold), and an over-wide
    value does not truncate quietly: it makes ``struct.pack`` reject the whole
    packet.
    """
    attribute = ATTRIBUTE_CODES.get(getattr(pet, 'attribute', 'Va'), 0)
    # Most devices agree on Va 0, Da 1, Vi 2, Free 3. A Digital Monster Color
    # does not -- the document gives its order as Free 0, Virus 1, Data 2,
    # Vaccine 3 -- so a format may declare its own mapping.
    attribute_map = getattr(protocol_constants.get_constants(battle_format),
                            'ATTRIBUTE_MAP', None)
    if attribute_map:
        attribute = attribute_map.get(attribute, attribute)
    limits = protocol_constants.get_wire(battle_format)

    def fit(value, attribute_name, default, offset_name=None):
        """Clamp *value* to a field the protocol declares, minus its offset.

        Some fields are numbered from a different origin than Omnipet uses --
        DMX counts levels from 0 and starts its stage scale at Baby II -- and
        the offset belongs to the wire, so it is applied here.
        """
        offset = getattr(limits, offset_name, 0) if offset_name else 0
        return max(0, min(int(value or 0) - offset,
                          getattr(limits, attribute_name, default)))

    oem = is_oem_pet(pet, battle_format)
    compatibility = not oem
    if oem:
        # A Digitama's index is -1, which no protocol can carry; it is also
        # never in a battle, so 0 ("an outsider") is the honest value.
        index = fit(getattr(pet, 'index', 0), 'MAX_INDEX', 0xFF)
        version = protocol_constants.clamp_oem_version(
            battle_format,
            getattr(pet, 'device_version', getattr(pet, 'version', 1)))
        runtime_globals.game_console.log(
            f"[DCom] OEM battle: sending index={index}, version={version}")
    else:
        # Index 0 is "an outsider" -- a Digimon the device has no roster
        # entry for. The version is not free alongside it: each wire declares
        # a range, and sending one outside it is what made a real DMX draw
        # our attacks from the wrong row of its pattern table.
        index = 0
        version = protocol_constants.get_compatibility_version(battle_format)
        # **The Colour lines can do better than 0.** Their wire carries no
        # stage, so a toy that wants one has only the version and index to
        # read -- and index 0 on this roster is a stage 1 record, which is
        # not what an outsider Adult should look like. Announcing the lowest
        # real index at our own stage keeps the identity coherent. It does
        # not change the battle: the device draws our shots from packet 2's
        # selector, measured in filmed battles 59 and 60.
        if protocol_constants.canonical_format(battle_format) == 'PENC':
            from battle.sim.battle_utils import penc_index_for_stage
            stand_in = penc_index_for_stage(
                version, getattr(pet, 'stage', 0) or 0)
            if stand_in:
                index = stand_in
        runtime_globals.game_console.log(
            f"[DCom] Compatibility battle: sending index={index}, "
            f"version={version}"
            " (mirrored from the device where the wire allows it)")

    # An empty slot falls back to one the pet does have. Omnipet's 0 means
    # "this module named no sprite for that slot", not "this Digimon attacks
    # with nothing -- and a device fighting a battle expects a sprite in
    # every slot it reads. A DMX and a Pendulum Z both aborted the exchange
    # with FF00 on receiving the packet that carried the all-ones "none" in
    # Shot M. The sentinel is still what goes out when the pet has no attack
    # sprite at all, and is still understood on the way in.
    def raw(attr):
        return getattr(pet, attr, 0) or 0

    #: Each sprite field has its own bank, and the mega shot's is a
    #: different folder entirely -- the ordinary shots come from the
    #: module's `atk/` and the mega from the global `assets/atk_crit`. So
    #: the count has to follow the field, not the format.
    SHOT_BANKS = {'MAX_SHOT': 'SHOT_COUNT', 'MAX_SHOT_M': 'SHOT_COUNT_M'}

    def shot(value, limit_name='MAX_SHOT', default=0x3F):
        # The field's width and the device's sprite bank are different
        # limits -- see shot_to_wire.
        bank = SHOT_BANKS.get(limit_name, 'SHOT_COUNT')
        return protocol_constants.shot_to_wire(
            value, getattr(limits, limit_name, default),
            getattr(limits, bank, 0))

    if limits.NAME == 'DMX':
        # Three shots on this wire: atk_main is the weak one, atk_alt strong,
        # atk_alt_2 the mega. shot1/shot2 carry strong/weak.
        strong, weak, mega = raw('atk_alt'), raw('atk_main'), raw('atk_alt_2')
        fallback = strong or weak or mega
        shot1 = shot(strong or fallback)
        shot2 = shot(weak or fallback)
        shot_m = shot(mega or fallback, 'MAX_SHOT_M', 0x1F)
    else:
        main, alt = raw('atk_main'), raw('atk_alt')
        fallback = main or alt
        shot1 = shot(main or fallback)
        shot2 = shot(alt or fallback)
        shot_m = 0

    # Deliberate policy exception (2026-09-10): keep each pet's own power
    # bonus formula, including its module rule, for device battles for now.
    # Review separately from peer parsing; only the resulting wire power is
    # authoritative once sent. Do not reconstruct a peer's private bonuses.
    raw_power = pet.get_power() if hasattr(pet, 'get_power') else getattr(pet, 'power', 50)
    raw_hp = pet.get_hp() if hasattr(pet, 'get_hp') else getattr(pet, 'hp', 5)
    power = fit(raw_power, 'MAX_POWER', 0xFF)
    hp = fit(raw_hp, 'MAX_HP', 0xFF)

    digimon = Digimon(
        name=getattr(pet, 'name', 'Player'),
        order=0,
        traited=1 if getattr(pet, 'traited', False) else 0,
        egg_shake=1 if getattr(pet, 'shook', False) else 0,
        index=index,
        hp=hp,
        attribute=attribute,
        power=power,
        handicap=0,
        buff=0,
        mini_game=minigame_result,
        level=fit(getattr(pet, 'level', 1), 'MAX_LEVEL', 0xFF, 'LEVEL_OFFSET'),
        stage=fit(getattr(pet, 'stage', 3), 'MAX_STAGE', 0xFF, 'STAGE_OFFSET'),
        sick=1 if getattr(pet, 'sick', 0) else 0,
        shot1=shot1,
        shot2=shot2,
        tag_meter=0,
    )
    # Read by DM20Device/DMXDevice when packing their packets.
    digimon.version = version
    #: Whether the Strength meter is full, for the wires that pay a damage
    #: bonus for it (DM20: "+1 for each attack in Single Battles"). The meter
    #: itself never goes on the wire -- only the Power it has already bought
    #: -- so this is knowable for our own pet and for nobody else's.
    stomach = getattr(pet, 'stomach', 0) or 0
    digimon.strength_full = bool(stomach and
                                 getattr(pet, 'strength', 0) >= stomach)
    digimon.dmx_shot_m = shot_m
    #: The Pendulum's own hidden training stat, 0-40. It is the only strength
    #: figure that wire carries -- there is no Power field on it at all.
    digimon.effort = max(0, min(getattr(protocol_constants.PENOG, 'MAX_EFFORT', 40),
                                int(getattr(pet, 'effort', 0) or 0)))

    if (power, hp) != (raw_power, raw_hp):
        runtime_globals.game_console.log(
            f"[DCom] the {limits.NAME} wire cannot carry this pet whole: "
            f"power {raw_power}->{power}, HP {raw_hp}->{hp}")
    #: A compatibility pet announces no version of its own; the wire may
    #: mirror the device's instead (DMX.DCOM_VERSION_ECHO).
    digimon.compatibility = compatibility

    runtime_globals.game_console.log(
        f"[DCom] {digimon.name}: HP={hp}, Power={power}, attr={attribute}, "
        f"shots=({shot1},{shot2},{shot_m}), charge={minigame_result}")
    return digimon


class DComBattleSimulator:
    """
    Handles battles with physical Digimon devices via DCom serial communication.
    Sends the player's packets, receives the opponent's, interprets the result.

    Selected by ``battle_format`` (``'DM'``, ``'DM20'``, ``'PEN20'``,
    ``'DMX'``, ``'PENZ'``, ``'DMC'``) -- the line of real devices being talked
    to. Every wire decision then follows from ``self.wire``, the packet layout
    that format is sent over, so a format cannot generate one layout and parse
    another. Dispatching on the DCom ``ProtocolType`` instead is what left
    PENZ with an empty battle log: it generated six DMX packets, then looked
    for ten in the V_PET branch and found nothing to replay.
    """

    def __init__(self, dcom_controller: DComController, protocol: ProtocolType = None,
                 battle_format: str = None):
        """
        Args:
            dcom_controller: Active DComController for serial communication.
            protocol: DCom signal timings. Derived from ``battle_format`` when
                omitted; only pass it to force unusual timings.
            battle_format: Device line ('DM', 'DM20', 'PEN20', 'DMX', 'PENZ',
                'DMC'). Derived from ``protocol`` when omitted.
        """
        self.dcom_controller = dcom_controller

        if not battle_format:
            battle_format = FORMAT_FOR_PROTOCOL.get(protocol, 'DM20')
        self.battle_format = battle_format
        self.constants = protocol_constants.get_constants(battle_format)
        if self.constants is None:
            runtime_globals.game_console.log(
                f"[DComBattleSimulator] Unknown battle format '{battle_format}', using DM20")
            self.battle_format = 'DM20'
            self.constants = protocol_constants.DM20

        # The packet layout this format is actually sent over.
        self.wire = protocol_constants.get_wire(self.battle_format)
        # Kept for callers that still pass a signal type around; the wire is
        # 2-prong for every format, so it selects nothing here.
        self.protocol = protocol or ProtocolType.V_PET
        self.opponent_digimon = None
        self.opponent_device_version = None
        #: The version we last put on the wire, and an override for it when
        #: the device turns out to number its line differently than we do.
        self.sent_version = None
        self.force_version = None
        #: True once a command went out with the adapter computing the final
        #: packet for us (see DMX.DCOM_FINAL_SEGMENT).
        self.sent_computed_final = False
        #: True once a command went out with the adapter copying the device's
        #: version into our packet 1 (see DMX.DCOM_VERSION_ECHO).
        self.sent_echoed_version = False
        #: True once a command went out with the adapter inverting the
        #: device's battle outcome into our packet 2 (the DMOG wire).
        self.sent_echoed_outcome = False
        #: **The player asked to open the exchange**, rather than us falling
        #: into turn 1 through the automatic retry. It is a different claim:
        #: swapping turns is "nobody answered, try the other way round",
        #: while this is "I am Player 1". Only the Colour line reads it, and
        #: only because that is the one wire where the role decides which
        #: operations go out rather than just who speaks first.
        self.opening = False
        #: The hit mask to put in packet 2's word 5 when the result is ours
        #: to report. On a Pendulum Color that is the RESPONDER's packet, and
        #: the mask is the **initiator's** -- so when we answer, it describes
        #: the device's shots and not our own.
        self.colour_hits = 0
        #: The verdict to put in our packet 2 when we are Player 1 on the
        #: Colour line. Learned from the device's own packet 1 -- see
        #: `declare_colour_outcome` -- and 0 until then, which is what
        #: Player 2 always sends anyway.
        self.colour_outcome = 0
        #: Who won, where the battle was actually fought rather than staged.
        #: `build_result` re-derives a winner from the final HP, which is
        #: right for a presentation built to end with the loser on zero and
        #: wrong for a battle that can end level -- so a path that KNOWS the
        #: answer records it here and is believed. None means nothing has
        #: been decided and the HP reading stands.
        self.decided_player_wins = None
        #: The exchange the result was read out of, so the turn builder can
        #: replay it rather than roll a new one.
        self._penc_decoded = None
        self._last_player_packets = None
        self._last_opponent_packets = None
        #: Set from the payload: a compatibility pet has no version of its own
        #: to announce, so it mirrors the device's.
        self.echo_version = False

        runtime_globals.game_console.log(
            f"[DComBattleSimulator] {self.constants.DISPLAY_NAME}: "
            f"{self.wire.NAME} wire, {self.wire.PACKET_COUNT} packets, "
            f"HP={self.wire.FIXED_HP or 'variable'}, minigame={self.constants.MINIGAME}")

        # Internal simulator, used for the shared battle/packet logging.
        self.internal_simulator = BattleSimulator(
            protocol_constants.versus_protocol(self.battle_format),
            battle_format=self.battle_format)

    # ------------------------------------------------------------------
    # Wire facts
    # ------------------------------------------------------------------

    @property
    def expected_packet_count(self) -> int:
        """How many packets the device sends back."""
        return self.wire.PACKET_COUNT

    @property
    def packet_hex_length(self) -> int:
        """Hex digits per packet: two bytes everywhere except the Color wire."""
        return getattr(self.wire, 'PACKET_BYTES', 2) * 2

    def declare_colour_outcome(self, packet_hex, digimon):
        """Work out the verdict we owe, as Player 1 on the Colour line.

        "Only Operation 2 will report the victory" -- so a side that has
        claimed Player 1 has to say who won, and it has to say it in a packet
        built before the exchange runs. **The opponent is what is missing,
        and a previous attempt supplies it**: the device announces its power
        and attribute in its own packet 1, and it retries every few seconds,
        so a verdict computed from the first attempt is waiting for the next.
        That is the same shape `_learn_from_partial` already uses to adopt a
        device's version.

        The verdict is computed the way the versus battle computes it,
        because a DCom battle is Omnipet standing in for a real device and a
        versus battle is Omnipet standing in for both -- so they cannot be
        two different battles. DMC rolls one hit at the manual's rate
        (reproduced exactly by humulos' own calculator: the power ratio, the
        stage bonus already inside `get_power`, and +-5 on the roll); PENC
        fights its three-point battle out.

        Returns True when the verdict changed and the packets want rebuilding.
        """
        # The adapter reports hex; `parse_colour_identity` reads bytes. Take
        # either, since the callers differ.
        packet = packet_hex
        if isinstance(packet, str):
            try:
                packet = bytes.fromhex(packet)
            except ValueError:
                return False
        opponent = self.parse_colour_identity(packet)
        if opponent is None:
            return False

        limits = protocol_constants.get_constants(self.battle_format) \
            or protocol_constants.DMC
        from battle.sim.battle_utils import penc_hit_mask

        initiator_hits = None
        if protocol_constants.fights_its_battle(self.battle_format):
            from battle.sim.battle_utils import fight_penc, penc_hit_mask
            won, rounds = fight_penc(
                digimon.power, digimon.attribute,
                getattr(digimon, 'mini_game', 0) or 0,
                opponent.power, opponent.attribute,
                penc_super_hits_from_wire_or_zero(opponent),
                a_stage=getattr(digimon, 'stage', 1) or 1,
                b_stage=getattr(opponent, 'stage', 1) or 1,
                battle_format=self.battle_format,
                a_effort=getattr(digimon, 'effort', 0) or 0,
                b_effort=getattr(opponent, 'effort', 0) or 0)
            # The mask the wire wants is the initiator's, whichever of us
            # that is: our own rounds when we opened, the device's when we
            # answered.
            initiator_hits = [(r.a_hit if self.opening else r.b_hit)
                              for r in rounds]
        else:
            from battle.sim.battle_simulator import DMCDevice
            won = bool(DMCDevice(digimon, limits=limits)
                       .calculate_outcome(opponent))

        # **Word 4 is about the INITIATOR, not about us.** On a Pendulum
        # Color the result rides in the responder's packet and describes the
        # side that opened -- so answering a device means reporting whether
        # IT won, which is the opposite of what we just worked out for
        # ourselves. The Digital Monster Color is the other way round: there
        # the initiator reports, and the initiator is us.
        if protocol_constants.fights_its_battle(self.battle_format):
            initiator_won = not won if not self.opening else won
            outcome = 1 if initiator_won else 0
            hits = penc_hit_mask(initiator_hits or [])
        else:
            outcome = 1 if won else 0
            hits = 0

        changed = (outcome != self.colour_outcome
                   or hits != self.colour_hits)
        self.colour_outcome = outcome
        self.colour_hits = hits
        runtime_globals.game_console.log(
            "[DComBattleSimulator] %s: we declare %s (us %s vs them %s), "
            "word4=%d word5=0x%04X"
            % (self.battle_format, "victory" if won else "defeat",
               digimon.power, opponent.power, outcome, hits))
        return changed

    def peek_version(self, packet_hex: str):
        """The version a device announced in its first packet, or None.

        Every wire carries it in packet 1 except DM20's, which carries it in
        packet 3 (packets 1 and 2 are the tamer name), so a first packet
        tells us nothing there.
        """
        wire = self.wire.NAME
        if wire == 'DM20':
            return None
        try:
            packet = bytes.fromhex(packet_hex)
        except ValueError:
            return None
        if len(packet) < 2:
            return None
        # PEN20 and DMX both close packet 1 with Version(4) | EOL(4).
        if wire in ('PEN20', 'DMX'):
            return (packet[1] >> 4) & 0x0F
        # The Pendulum puts its version at the top of packet 1 instead.
        if wire == 'PENOG':
            return (packet[0] >> 4) & 0x7
        return None

    @property
    def turn(self) -> int:
        """Whether the adapter opens the exchange (1) or listens for it (2)."""
        return getattr(self.constants, 'DCOM_TURN', protocol_constants.DCOM_TURN_LISTEN)

    @property
    def goes_first(self) -> bool:
        """True when the adapter opens the exchange rather than answering."""
        return self.turn == protocol_constants.DCOM_TURN_GO_FIRST

    @property
    def minigame(self) -> str:
        """The charge minigame this device line plays before a battle."""
        return self.constants.MINIGAME

    def charge_value(self, session) -> int:
        """The charge a finished MinigameSession puts on this wire.

        The two wire families read the charge differently. DM20 (and PEN20
        with it) carries the *raw meter* -- "Attack Pattern is determined by
        how many times the button was pressed for the rising meter" -- and
        picks its damage pattern from it, so a 0-14 count belongs there. DMX
        (with PENZ and DMC) carries a 2-bit quality instead: Bad, Good,
        Great, Excellent. Sending the banded 0-3 value on a taps wire pinned
        every battle to the first four of fifteen attack patterns.

        **And the scale is the FORMAT's, not the wire's.** Every other format
        agrees with the layout it rides, so this went unnoticed -- but PENC
        carries "super hits", a raw 0-5, on the DMC's layout, and reading the
        wire banded it back to the 0-3 the DMC uses. The band cannot separate
        a Megahit from the middle rung and the device plainly does (14 on the
        wire against 11), so the difference is a real one.
        """
        if session is None:
            return 0
        limits = protocol_constants.get_constants(self.battle_format) or self.wire
        cap = getattr(limits, 'MAX_CHARGE', 3)
        scale = getattr(limits, 'CHARGE_SCALE', 'quality')
        if scale == "taps":
            raw = session.strength
        elif scale == "super hits":
            raw = getattr(session, 'super_hits', 0)
        else:
            raw = session.result
        return max(0, min(int(raw or 0), cap))

    def build_command(self, packets: List[bytes], turn: int = None) -> str:
        """The DCom command that sends *packets*.

        Turn 2 is listen-and-reply: the adapter waits for the toy to open the
        exchange, then answers with our packets. Turn 1 sends first instead,
        repeating every few seconds, which is the only way to reach a toy
        that waits to be spoken to. Every format goes out over 2-prong
        timings.
        """
        hex_packets = [pkt.hex().upper() for pkt in packets]
        turn = self.turn if turn is None else turn

        # Some wires cannot state their last packet in advance -- it depends
        # on the one the device is about to send. The adapter can build it,
        # but only in a listen-and-reply exchange: XOR-against-the-reply is a
        # type-2 feature, and going first there is nothing to reply to.
        replying = turn == protocol_constants.DCOM_TURN_LISTEN
        final = getattr(self.wire, 'DCOM_FINAL_SEGMENT', None)
        self.sent_computed_final = bool(final and replying and hex_packets)
        if self.sent_computed_final:
            hex_packets[-1] = final

        if self.wire.NAME == 'PENOG' and replying and len(hex_packets) == 4:
            # Complement the five peer hit bits, retaining PENOG's COU/EOL,
            # then checksum our own four packets using its remainder.
            hex_packets[2] = '0^1^FF'
            hex_packets[3] = '@B' + hex_packets[3][1:]

        # A compatibility pet has no version of its own worth announcing, so
        # the adapter copies the device's out of the packet it is replying to
        # -- we look like a Digimon of its own version rather than claiming
        # one, and nothing cross-version can unlock off the back of the
        # battle. Same type-2 constraint as the final packet above.
        # Read off the FORMAT, not the wire: PENZ and DMC ride the DMX
        # layout but each decides for itself whether to mirror.
        # The DMOG wire's outcome is the device's, inverted -- see
        # DMOG.DCOM_OUTCOME_ECHO. Only when answering, for the same reason.
        outcome_echo = getattr(self.wire, 'DCOM_OUTCOME_ECHO', None)
        self.sent_echoed_outcome = bool(outcome_echo and replying and len(hex_packets) >= 2)
        if self.sent_echoed_outcome:
            version_digit = hex_packets[1][2]
            hex_packets[1] = hex_packets[1][0] + outcome_echo.format(version=version_digit)

        echo = getattr(protocol_constants.get_constants(self.battle_format),
                       'DCOM_VERSION_ECHO', None)
        self.sent_echoed_version = bool(
            echo and replying and hex_packets and self.echo_version)
        if self.sent_echoed_version:
            hex_packets[0] = hex_packets[0][:2] + echo

        # The op letter belongs to the wire: "C" for the Color layout, "V"
        # for everything else.
        op = getattr(self.wire, 'DCOM_OP', protocol_constants.DCOM_OP)
        return f"{op}{turn}-" + "-".join(hex_packets)

    def get_initial_hp(self, digimon: Optional[Digimon] = None) -> int:
        """Starting HP for a Digimon on this wire.

        The FORMAT first, because the bar is not always the wire's: a
        Pendulum Color rides the Digital Monster Color's layout and fights at
        **three** where the DMC fights at five -- "each Digimon has 3 health
        points which will be reduced by 1 for a normal hit and by 2 for a
        super hit", from its own manual. Reading only the wire gave it the
        DMC's five, so its battle spent 5 against a 3-point bar.
        """
        limits = protocol_constants.get_constants(self.battle_format)
        fixed = getattr(limits, 'FIXED_HP', None) if limits else None
        if fixed is None:
            fixed = self.wire.FIXED_HP
        if fixed is not None:
            return fixed
        if digimon and getattr(digimon, 'hp', 0):
            return digimon.hp
        return getattr(self.wire, 'DEFAULT_HP', 4)

    def simulate_with_device(self, player_digimon: Digimon, timeout: float = 30.0) -> Optional[BattleResult]:
        """Blocking cable API, using the same plan and actual-transcript replay."""
        from battle.sim.exchange import PacketExchange
        exchange = PacketExchange(self.battle_format, player_digimon,
                                  opens=PacketExchange.cable_opens(self.battle_format),
                                  peer=False, simulator=self)
        try:
            command = exchange.cable_command()
            self.dcom_controller._send_raw(command + '\r')
            sent_pattern = re.compile(r's:([0-9A-Fa-f]{%d})(?![0-9A-Fa-f])' % self.packet_hex_length)
            received_pattern = self.response_pattern()
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                line = self.dcom_controller._read_line()
                if not line:
                    time.sleep(0.01)
                    continue
                if re.search(r'r:FF00(?:\s|$)', line, re.IGNORECASE):
                    continue
                sent = sent_pattern.findall(line)
                received = received_pattern.findall(line)
                # Each adapter line is one attempt. Never concatenate failed
                # attempts, or replay packets the adapter did not send.
                if len(sent) != exchange.packet_count or len(received) != exchange.packet_count:
                    continue
                finished = PacketExchange.from_transcript(
                    self.battle_format, player_digimon,
                    [bytes.fromhex(p) for p in sent], received, simulator=self)
                result = finished.result()
                if result is not None:
                    return result
        except Exception as error:
            runtime_globals.game_console.log(f'[DComBattleSimulator] Cable exchange failed: {error}')
        return None

    def log_battle(self, result: BattleResult):
        """Write the turn-by-turn log and both sides' packets to the log file."""
        self.internal_simulator.print_battle_log(result)
        self.internal_simulator.print_dcom_code(result)

    # ------------------------------------------------------------------
    # Packet generation
    # ------------------------------------------------------------------

    def generate_player_packets(self, digimon: Digimon, turn: int = None,
                                peer: bool = False) -> Optional[List[bytes]]:
        """Generate the packets to send for *digimon* under this format.

        One place per format, so the connection view and the battle encounter
        cannot send different bytes for the same device.

        The Order bit follows who opens the exchange -- "the initiating device
        will have a 1 for order, while the second device will have a 0" -- so
        it is decided by the turn, not fixed.
        """
        turn = self.turn if turn is None else turn
        order = 1 if turn == protocol_constants.DCOM_TURN_GO_FIRST else 0
        if self.force_version is not None:
            digimon.version = self.force_version
            runtime_globals.game_console.log(
                f"[DComBattleSimulator] Using the device's own version "
                f"{self.force_version}")
        self.sent_version = getattr(digimon, 'version', None)
        # Only a compatibility pet mirrors; an OEM pet has a real version and
        # the device needs to see it.
        self.echo_version = bool(getattr(digimon, 'compatibility', False))
        runtime_globals.game_console.log(
            f"[DComBattleSimulator] Generating {self.battle_format} packets "
            f"on the {self.wire.NAME} wire "
            f"(turn {turn}, order {order}, version {self.sent_version})...")

        try:
            wire = self.wire.NAME
            digimon.order = order
            if wire == 'DMOG':
                packets = DMDevice(digimon).generate_all_packets()
            elif wire == 'PENOG':
                # A template only. PacketExchange rolls from transmitted
                # slots/effort; a cable responder uses the adapter operators.
                packets = PENOGDevice(digimon).generate_all_packets()
            elif wire == 'DM20':
                packets = DM20Device(digimon).generate_all_packets_for_dcom(order=order)
            elif wire == 'PEN20':
                packets = PEN20Device(digimon).generate_all_packets_for_dcom(order=order)
            elif wire == 'DMX':
                # DMX and PENZ send these six packets. DMC does not: it has
                # its own layout, below.
                packets = DMXDevice(digimon).generate_all_packets_for_dcom()
            elif wire == 'DMC':
                # Operations follow the role we take in this exchange.
                # Peer type does not tell us which role it will claim.
                dmc_order = order
                line = protocol_constants.get_constants(self.battle_format)
                device = DMCDevice(
                    digimon,
                    magic=line.MAGIC,
                    operation_offset=getattr(line, 'OPERATION_OFFSET', 0),
                    trailer=colour_trailer(self.battle_format, digimon),
                    # **Without this it is a Digital Monster Color.**
                    # `DMCDevice.limits` defaults to DMC, and
                    # `generate_all_packets` reads it to decide which side
                    # reports the result -- so a Pendulum Color or an Xros
                    # Wars answering a device dropped its own computed
                    # outcome and hit mask and sent zeros, which say "the
                    # initiator lost and missed every round".
                    limits=line,
                )
                device.declared_hits = self.colour_hits
                packets = device.generate_all_packets(
                    order=dmc_order, outcome=self.colour_outcome)
            else:
                runtime_globals.game_console.log(
                    f"[DComBattleSimulator] Unsupported wire: {wire}")
                return None

            runtime_globals.game_console.log(f"[DComBattleSimulator] Generated {len(packets)} packets:")
            for i, pkt in enumerate(packets, 1):
                runtime_globals.game_console.log(f"  Packet {i}: {pkt.hex().upper()}")

            return packets

        except Exception as e:
            runtime_globals.game_console.log(f"[DComBattleSimulator] Packet generation error: {e}")
            import traceback
            runtime_globals.game_console.log(traceback.format_exc())
            return None

    # ------------------------------------------------------------------
    # Serial exchange
    # ------------------------------------------------------------------



    def response_pattern(self):
        """Regex matching one received packet of this format on a DCom line.

        The packet width is part of the format: 16-bit protocols answer with
        ``r:XXXX``, DMC with a full 16-byte word sequence.
        """
        return re.compile(r'r:([0-9A-Fa-f]{%d})(?![0-9A-Fa-f])' % self.packet_hex_length)

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def parse_opponent(self, packets: List[str], player_digimon: Digimon = None) -> Optional[Digimon]:
        """Parse the opponent out of the received packets.

        Attack sprite ids come off the wire 0-based; Omnipet reserves 0 for
        "no sprite", so they are shifted up by one here -- once, on the way
        in, rather than at each place that reads them.
        """
        runtime_globals.game_console.log("[DComBattleSimulator] Parsing opponent data from packets...")

        try:
            packet_bytes = [bytes.fromhex(pkt) for pkt in packets]

            if not self._validate_packets(packet_bytes):
                runtime_globals.game_console.log("[DComBattleSimulator] ERROR: Packet validation failed!")
                self._send_error_to_device()
                return None

            wire = self.wire.NAME
            if wire == 'DMX':
                opponent = self._parse_dmx_opponent(packet_bytes)
            elif wire == 'PEN20':
                opponent = self._parse_pen20_opponent(packet_bytes)
            elif wire == 'DM20':
                opponent = self._parse_dm20_opponent(packet_bytes)
            elif wire == 'DMOG':
                opponent = self._parse_dm_opponent(packet_bytes)
            elif wire == 'PENOG':
                opponent = self._parse_penog_opponent(packet_bytes)
            elif wire == 'DMC':
                opponent = self._parse_dmc_opponent(packet_bytes)
            else:
                runtime_globals.game_console.log(f"[DComBattleSimulator] Unknown wire: {wire}")
                return None

            if opponent:
                # Off the wire they are 0-based with an all-ones "none";
                # Omnipet numbers them from 1 with 0 for none. A wire that
                # exchanges no sprite ids at all (DM) has already filled in
                # Omnipet-numbered defaults, so it is left alone.
                shot_max = getattr(self.wire, 'MAX_SHOT', 0x3F)
                if shot_max > 0:
                    opponent.shot1 = protocol_constants.shot_from_wire(opponent.shot1, shot_max)
                    opponent.shot2 = protocol_constants.shot_from_wire(opponent.shot2, shot_max)
                if hasattr(opponent, 'dmx_shot_m'):
                    opponent.dmx_shot_m = protocol_constants.shot_from_wire(
                        opponent.dmx_shot_m, getattr(self.wire, 'MAX_SHOT_M', 0x1F))
                # Level and stage are numbered from a different origin on the
                # wire; put them back on Omnipet's scale.
                opponent.level += getattr(self.wire, 'LEVEL_OFFSET', 0)
                opponent.stage += getattr(self.wire, 'STAGE_OFFSET', 0)
                self._name_opponent(opponent)
                self.opponent_digimon = opponent
            return opponent

        except Exception as e:
            runtime_globals.game_console.log(f"[DComBattleSimulator] Parse error: {e}")
            import traceback
            runtime_globals.game_console.log(traceback.format_exc())
            self._send_error_to_device()
            return None

    def _validate_packets(self, packets: List[bytes]) -> bool:
        """Validate the complete transcript from one device before parsing."""
        if not packets or any(not isinstance(p, (bytes, bytearray)) for p in packets):
            return False
        packets = self._join_wire_groups(packets)
        width = getattr(self.wire, 'PACKET_BYTES', 2)
        if len(packets) != self.wire.PACKET_COUNT or any(
                not isinstance(p, (bytes, bytearray)) or len(p) != width for p in packets):
            return False
        wire = self.wire.NAME
        if wire == 'DMOG':
            return (all((p[0] ^ p[1]) == 0xFF for p in packets)
                    and (packets[1][1] & 0xF) in (1, 2))
        if wire == 'DMX':
            return self._validate_dmx_packets(packets)
        if wire == 'PEN20':
            return self._validate_pen20_packets(packets)
        if wire == 'DM20':
            return self._validate_dm20_packets(packets)
        if wire == 'DMC':
            return self._validate_dmc_packets(packets)
        if wire == 'PENOG':
            return self._validate_penog_packets(packets)
        return False

    def _validate_penog_packets(self, packets: List[bytes]) -> bool:
        """Four packets, every one ending in F, summing to a remainder of 11.

        The EOL nibble is F on this wire and E on every other, so a signal
        from a different device fails here rather than being read as a
        Pendulum's.
        """
        limits = protocol_constants.PENOG
        if len(packets) != limits.PACKET_COUNT:
            runtime_globals.game_console.log(
                f"[DComBattleSimulator] PENOG needs {limits.PACKET_COUNT} "
                f"packets, got {len(packets)}")
            return False
        total = 0
        for position, packet in enumerate(packets, start=1):
            if len(packet) < 2:
                return False
            if (packet[1] & 0xF) != limits.EOL:
                runtime_globals.game_console.log(
                    f"[DComBattleSimulator] PENOG packet {position} ends in "
                    f"{packet[1] & 0xF:X}, not {limits.EOL:X}")
                return False
            for byte in packet:
                total += (byte >> 4) & 0xF
                total += byte & 0xF
        if total % 16 != limits.CHECKSUM_REMAINDER:
            runtime_globals.game_console.log(
                f"[DComBattleSimulator] PENOG checksum remainder "
                f"{total % 16}, expected {limits.CHECKSUM_REMAINDER}")
            return False
        return True

    def _join_wire_groups(self, packets: List[bytes]) -> List[bytes]:
        """Reassemble DMComm's 16-bit groups into this wire's packets.

        The adapter reports 16 bits at a time, so a DMC packet arrives as
        eight groups. Everything else is one group per packet and passes
        through untouched.
        """
        width = getattr(self.wire, 'PACKET_BYTES', 2)
        if width <= 2 or not packets:
            return packets
        if all(len(p) == width for p in packets):
            return packets                      # already whole
        blob = b"".join(packets)
        return [blob[i:i + width] for i in range(0, len(blob), width)]

    def _validate_dmc_packets(self, packets: List[bytes]) -> bool:
        """Validate DMC packets: the magic word and the 16-bit sum.

        "Check -- Equal to the value of each 16 bit sequence", so the last
        word is the sum of every word before it, low 16 bits kept.
        """
        packets = self._join_wire_groups(packets)
        expected = self.wire.PACKET_COUNT
        if len(packets) != expected:
            runtime_globals.game_console.log(
                f"[DComBattleSimulator] Validation failed: expected {expected} "
                f"DMC packets, got {len(packets)}")
            return False
        for i, pkt in enumerate(packets[:expected], 1):
            if len(pkt) != self.wire.PACKET_BYTES:
                runtime_globals.game_console.log(
                    f"[DComBattleSimulator] DMC packet {i} is {len(pkt)} bytes, "
                    f"expected {self.wire.PACKET_BYTES}")
                return False
            words = [int.from_bytes(pkt[j:j + 2], 'big') for j in range(0, len(pkt), 2)]
            # The magic belongs to the device line, not the layout: PENC
            # rides DMC's wire but opens with 'GDDp' where DMC opens 'GDLC'.
            magic = protocol_constants.get_constants(self.battle_format).MAGIC
            if (words[0] << 16 | words[1]) != magic:
                runtime_globals.game_console.log(
                    f"[DComBattleSimulator] {self.battle_format} packet {i} does "
                    f"not open with {magic:08X}")
                return False
            if sum(words[:-1]) & 0xFFFF != words[-1]:
                runtime_globals.game_console.log(
                    f"[DComBattleSimulator] DMC packet {i} checksum "
                    f"{words[-1]:04X}, expected {sum(words[:-1]) & 0xFFFF:04X}")
                return False
        base = getattr(protocol_constants.get_constants(self.battle_format),
                       'OPERATION_OFFSET', 0)
        identity, battle = [self._colour_words(p) for p in packets]
        if identity[2] not in (base, base + 1) or battle[2] != identity[2] + 2:
            return False
        if identity[6] not in self.wire.ATTRIBUTE_MAP.values():
            return False
        # DMC's verdict is boolean in operation 2, zero in operation 3.
        # Do not impose DMC's result fields on PENC/DMXW.
        if protocol_constants.canonical_format(self.battle_format) == 'DMC':
            if battle[4] not in ((0, 1) if battle[2] == 2 else (0,)):
                return False
        runtime_globals.game_console.log("[DComBattleSimulator] DMC packet validation passed")
        return True

    def _parse_dmc_opponent(self, packets: List[bytes]) -> Optional[Digimon]:
        """The opponent, out of the two DMC packets.

        Packet 1 (op 0/1) carries version, index, power and attribute;
        packet 2 (op 2/3) the attack sprite and the outcome. The attribute
        arrives in DMC's own order -- Free 0, Virus 1, Data 2, Vaccine 3 --
        and is turned back into Omnipet's here.
        """
        try:
            packets = self._join_wire_groups(packets)

            def words(pkt):
                return [int.from_bytes(pkt[i:i + 2], 'big') for i in range(0, len(pkt), 2)]
            p1, p2 = words(packets[0]), words(packets[1])
            operation, version, index, power, attribute = p1[2], p1[3], p1[4], p1[5], p1[6]
            # Packet 2 carries its own operation -- 2 for player one's battle
            # data, 3 for player two's -- and that is the one that says
            # whether the outcome beside it means anything.
            battle_operation, shot, outcome = p2[2], p2[3], p2[4]
            # The COU's low word. A Digital Monster Color leaves it at zero;
            # a Pendulum Color puts its **charge** there, measured across six
            # filmed battles (`data/attack_patterns/PENC.json`). Reading it
            # is what lets a connection battle draw the shots the device
            # really fired.
            wire_charge = p2[6]

            back = {v: k for k, v in self.wire.ATTRIBUTE_MAP.items()}
            internal_attribute = back.get(attribute, attribute)

            runtime_globals.game_console.log(
                f"[DComBattleSimulator] DMC parsed: op={operation}, version={version}, "
                f"index={index}, power={power}, attribute={attribute} "
                f"(Omnipet {internal_attribute})")
            runtime_globals.game_console.log(
                f"[DComBattleSimulator] DMC parsed: battle op={battle_operation}, "
                f"shot={shot}, outcome={outcome}")

            # **This wire carries no stage**, and the attack table is keyed
            # on one -- so it comes from the version and index, which together
            # are exact on this line's roster (the index alone is not: 19 of
            # 34 name more than one stage). The table is in `data/rosters/`
            # rather than the module, because the opponent is a real device
            # whether or not the player owns PENC. A flat `stage=4` sat here
            # before, harmless while nothing read it.
            from battle.sim.battle_utils import colour_stage_from_wire
            stage = colour_stage_from_wire(self.battle_format, version, index)
            if stage is None:
                stage = 4
                runtime_globals.game_console.log(
                    "[DComBattleSimulator] %s: version %s index %s names no "
                    "stage on this roster; assuming Adult"
                    % (self.battle_format, version, index))
            opponent = Digimon(
                name=FALLBACK_NAMES.get(internal_attribute, "Opponent"),
                order=1 if operation == self.colour_operations()[0] else 0,
                traited=0, egg_shake=0, index=index,
                hp=self.get_initial_hp(), attribute=internal_attribute, power=power,
                handicap=0, buff=0, mini_game=0, level=1,
                stage=stage, sick=0, shot1=shot, shot2=shot, tag_meter=0)
            opponent.version = version
            # Every other wire's parser records this, and the opponent lookup
            # reads it: an index is per-version, and on this line index 3 is
            # a different Digimon on each of the five. Without it `versions`
            # stayed None, the whole roster was searched, and the answer came
            # back "Elecmon or Palmon" -- ambiguous, so the opponent kept its
            # bare attribute name and its generic sprite.
            self.opponent_device_version = version
            #: "Only Operation 2 will report the victory, Operation 3 sends 0
            #: regardless of a loss or victory" -- so this is meaningful only
            #: when the device was player one.
            #:
            #: **Which operation that IS depends on the line.** A Pendulum
            #: Color numbers the same four roles from 0x10, so its Player 1
            #: Battle Data is 0x12 and the bare `== 2` never matched: the
            #: verdict was thrown away as None and the battle fell through to
            #: settling on power, which handed the device a win it had just
            #: declined. Filmed battle 43 is exactly that -- outcome 0, "the
            #: device loses", shown in game as the device winning.
            limits = protocol_constants.get_constants(self.battle_format)
            player_one_battle = 2 + (getattr(limits, 'OPERATION_OFFSET', 0)
                                     if limits else 0)
            opponent.dmc_outcome = (outcome
                                    if battle_operation == player_one_battle
                                    else None)
            #: The charge the device played, as super hits. `mini_game` holds
            #: the raw count on this line rather than the 0-3 band, the same
            #: way our own side carries it.
            if protocol_constants.canonical_format(self.battle_format) == 'PENC':
                from battle.sim.battle_utils import penc_super_hits_from_wire
                opponent.mini_game = penc_super_hits_from_wire(wire_charge)
                runtime_globals.game_console.log(
                    "[DComBattleSimulator] PENC device charge: COU %d -> %d "
                    "super hit(s)" % (wire_charge, opponent.mini_game))
            return opponent
        except Exception as e:
            runtime_globals.game_console.log(
                f"[DComBattleSimulator] Failed to parse DMC packets: {e}")
            return None

    def _validate_dm20_packets(self, packets: List[bytes]) -> bool:
        """Validate DM20 packets: EOL markers and checksum."""
        if len(packets) < 10:
            runtime_globals.game_console.log(f"[DComBattleSimulator] Validation failed: expected 10 packets, got {len(packets)}")
            return False

        # Check EOL markers (should be 0xE = 1110 in last 4 bits of byte 2 for most packets)
        # Packets 3-10 should have EOL
        expected_eol = 0xE
        for i in range(2, 10):  # Packets 3-10 (0-indexed: 2-9)
            eol = packets[i][1] & 0x0F  # Last 4 bits of byte 2
            if eol != expected_eol:
                runtime_globals.game_console.log(f"[DComBattleSimulator] Validation failed: Packet {i+1} has invalid EOL: 0x{eol:X} (expected 0x{expected_eol:X})")
                return False

        # Validate checksum in Packet A (packet 10)
        checksum = 0
        for pkt in packets[:10]:  # All 10 packets
            for byte in pkt:
                checksum += (byte >> 4) & 0x0F  # Upper nibble
                checksum += byte & 0x0F          # Lower nibble

        if (checksum % 16) != 0:
            runtime_globals.game_console.log(f"[DComBattleSimulator] Validation failed: Invalid checksum (sum % 16 = {checksum % 16}, expected 0)")
            return False

        runtime_globals.game_console.log("[DComBattleSimulator] Packet validation passed")
        return True

    def _validate_dmx_packets(self, packets: List[bytes]) -> bool:
        """Validate DMX packets: EOL markers and checksum."""
        if len(packets) < 6:
            runtime_globals.game_console.log(f"[DComBattleSimulator] Validation failed: expected 6 packets, got {len(packets)}")
            return False

        # Check EOL markers in all 6 packets
        expected_eol = 0xE
        for i in range(6):
            eol = packets[i][1] & 0x0F  # Last 4 bits
            if eol != expected_eol:
                runtime_globals.game_console.log(f"[DComBattleSimulator] Validation failed: DMX Packet {i+1} has invalid EOL: 0x{eol:X}")
                return False

        # Nibble sum of all 6 packets, check nibble included, must be 8 (mod 16)
        checksum = 0
        for pkt in packets[:6]:
            for byte in pkt:
                checksum += (byte >> 4) & 0x0F
                checksum += byte & 0x0F

        if (checksum % 16) != protocol_constants.DMX.CHECKSUM_REMAINDER:
            runtime_globals.game_console.log(
                f"[DComBattleSimulator] Validation failed: Invalid DMX checksum "
                f"(sum % 16 = {checksum % 16}, expected {protocol_constants.DMX.CHECKSUM_REMAINDER})")
            return False

        runtime_globals.game_console.log("[DComBattleSimulator] DMX packet validation passed")
        return True

    def _validate_pen20_packets(self, packets: List[bytes]) -> bool:
        """Validate packets in the PEN20 layout.

        Same 10 packets and EOL markers as DM20, but the Check nibble targets
        remainder 12 rather than 0 -- "Remainder should always equal 12" in
        the protocol document, whose worked example sums to exactly that.

        Only reached when a format selects the PEN20 wire; PEN20 currently
        goes out over DM20's (see protocol_constants.PEN20.DCOM_WIRE).
        """
        if len(packets) < 10:
            runtime_globals.game_console.log(
                f"[DComBattleSimulator] PEN20 validation failed: expected 10 packets, "
                f"got {len(packets)}")
            return False

        for i in range(0, 10):
            eol = packets[i][1] & 0x0F
            if eol != protocol_constants.PEN20.EOL:
                runtime_globals.game_console.log(
                    f"[DComBattleSimulator] PEN20 validation failed: packet {i+1} "
                    f"has invalid EOL: 0x{eol:X}")
                return False

        checksum = 0
        for pkt in packets[:10]:
            for byte in pkt:
                checksum += (byte >> 4) & 0x0F
                checksum += byte & 0x0F

        target = protocol_constants.PEN20.CHECKSUM_REMAINDER
        if (checksum % 16) != target:
            runtime_globals.game_console.log(
                f"[DComBattleSimulator] PEN20 validation failed: checksum "
                f"{checksum % 16}, expected {target}")
            return False

        runtime_globals.game_console.log("[DComBattleSimulator] PEN20 packet validation passed")
        return True

    def _send_error_to_device(self):
        """Send error response to DCom device."""
        try:
            # Send FF00 error code to device
            error_command = "FF00"
            runtime_globals.game_console.log(f"[DComBattleSimulator] Sending error to device: {error_command}")
            self.dcom_controller._send_raw(error_command + '\r')
        except Exception as e:
            runtime_globals.game_console.log(f"[DComBattleSimulator] Failed to send error to device: {e}")

    def _parse_dm20_opponent(self, packets: List[bytes]) -> Optional[Digimon]:
        """Parse DM20 (V-Pet) protocol opponent data."""
        # DM20 packet structure (10 packets):
        # Packet 1: Name 2, Name 1
        # Packet 2: Name 4, Name 3
        # Packet 3: Order | Attack (pattern) | Operation | Version | EOL
        # Packet 4: COU | Index L | Attribute L | EOL
        # Packet 5: Shot S L | Shot W L | EOL
        # Packet 6: COU | Power L | EOL
        # Packet 7: COU | Index R | Attribute R | EOL
        # Packet 8: Shot S R | Shot W R | EOL
        # Packet 9: Tag Meter | Power R | EOL
        # Packet 10: Check | Dodges | Hits | EOL
        
        if len(packets) < 10:
            runtime_globals.game_console.log(f"[DComBattleSimulator] Incomplete DM20 packets: {len(packets)}/10")
            return None
        
        try:
            # Parse packet 3: Order(1) Pattern(5) Operation(2) | Version(4) EOL(4)
            pkt3 = packets[2]
            order = (pkt3[0] >> 7) & 0x01        # Bit 7 of byte 0
            pattern_index = (pkt3[0] >> 2) & 0x1F  # Bits 2-6 of byte 0 = pattern (5 bits)
            operation = pkt3[0] & 0x03              # Bits 0-1 of byte 0 = operation (2 bits)
            version = (pkt3[1] >> 4) & 0x0F         # Upper 4 bits of byte 1
            # Which device the other side is; unlocks that require a specific
            # pairing ("battle XA with XB") are checked against this.
            self.opponent_device_version = version
            
            runtime_globals.game_console.log(f"[DComBattleSimulator] Order: {order}, Pattern index: {pattern_index}, Operation: {operation}, Version: {version}")
            
            # Parse packet 4: COU(2) Index(8) Attribute(2) EOL(4)
            pkt4 = packets[3]
            opponent_index = ((pkt4[0] & 0x3F) << 2) | ((pkt4[1] >> 6) & 0x03)  # 8 bits across bytes
            opponent_attribute = (pkt4[1] >> 4) & 0x03  # Bits 4-5 of byte 1
            
            # Parse packet 5: Shot_S(6) Shot_W(6) EOL(4)
            pkt5 = packets[4]
            shot1 = (pkt5[0] >> 2) & 0x3F                              # Upper 6 bits of byte 0
            shot2 = ((pkt5[0] & 0x03) << 4) | ((pkt5[1] >> 4) & 0x0F) # 6 bits across bytes
            
            # Parse packet 6: COU(4) Power(8) EOL(4)
            pkt6 = packets[5]
            opponent_power = ((pkt6[0] & 0x0F) << 4) | ((pkt6[1] >> 4) & 0x0F)  # 8 bits across bytes
            
            # Parse packet 9: Tag_Meter(4) Power_R(8) EOL(4)
            pkt9 = packets[8]
            tag_meter = (pkt9[0] >> 4) & 0x0F  # Upper 4 bits = tag meter
            
            # Map attribute to name
            opponent_name = FALLBACK_NAMES.get(opponent_attribute, "Opponent")
            
            runtime_globals.game_console.log(f"[DComBattleSimulator] Opponent: {opponent_name}, Attr={opponent_attribute}, Index={opponent_index}, Power={opponent_power}")
            runtime_globals.game_console.log(f"[DComBattleSimulator] Opponent shots: shot1={shot1}, shot2={shot2}")
            runtime_globals.game_console.log(f"[DComBattleSimulator] Tag meter: {tag_meter}, Pattern: {pattern_index}, Version: {version}")
            
            # Create opponent Digimon with parsed data
            opponent = Digimon(
                name=opponent_name,
                order=order,
                traited=0,
                egg_shake=0,
                index=opponent_index,
                # Ten, measured -- the same for every Digimon on this line.
                # This literal said 4, which no reading ever supported.
                hp=protocol_constants.DM20.FIXED_HP,
                attribute=opponent_attribute,
                power=opponent_power,
                handicap=0,
                buff=0,
                mini_game=pattern_index,  # Store pattern index in mini_game field for battle simulation
                level=1,
                stage=3,
                sick=0,
                shot1=shot1,
                shot2=shot2,
                tag_meter=tag_meter  # Tag meter value for pattern calculation
            )
            
            return opponent
            
        except Exception as e:
            runtime_globals.game_console.log(f"[DComBattleSimulator] DM20 parse error: {e}")
            import traceback
            runtime_globals.game_console.log(traceback.format_exc())
            return None
    
    def _parse_dmx_opponent(self, packets: List[bytes]) -> Optional[Digimon]:
        """
        Parse DMX (Color) protocol opponent data from packets.
        
        DMX Packet Format:
        Packet 1: Order(1) Level(4) Sick(1) Attack(2) Version(4) EOL(4)
        Packet 2: Stage(3) Index(7) Attribute(2) EOL(4)
        Packet 3: Shot_S(6) Shot_W(6) EOL(4)
        Packet 4: COU(2) HP(5) Shot_M(5) EOL(4)
        Packet 5: COU(2) Buff(2) Power(8) EOL(4)
        Packet 6: Check(4) COU(3) Hits(5) EOL(4)
        """
        try:
            if len(packets) < 6:
                runtime_globals.game_console.log(f"[DComBattleSimulator] DMX parse error: Need 6 packets, got {len(packets)}")
                return None
            
            # Packet 1: Order(1) Level(4) Sick(1) Attack(2) Version(4) EOL(4)
            pkt1 = packets[0]
            order = (pkt1[0] >> 7) & 0x1
            level = (pkt1[0] >> 3) & 0xF  # 4 bits
            sick = (pkt1[0] >> 2) & 0x1
            attack = pkt1[0] & 0x3  # 2 bits (0-3)
            version = (pkt1[1] >> 4) & 0xF
            self.opponent_device_version = version
            
            # Packet 2: Stage(3) Index(7) Attribute(2) EOL(4)
            pkt2 = packets[1]
            stage = (pkt2[0] >> 5) & 0x7  # 3 bits
            index = ((pkt2[0] & 0x1F) << 2) | ((pkt2[1] >> 6) & 0x3)  # 7 bits
            attribute = (pkt2[1] >> 4) & 0x3  # 2 bits
            
            # Packet 3: Shot_S(6) Shot_W(6) EOL(4)
            pkt3 = packets[2]
            shot_s = (pkt3[0] >> 2) & 0x3F  # 6 bits
            shot_w = ((pkt3[0] & 0x3) << 4) | ((pkt3[1] >> 4) & 0xF)  # 6 bits
            
            # Packet 4: COU(2) HP(5) Shot_M(5) EOL(4)
            pkt4 = packets[3]
            hp = (pkt4[0] >> 1) & 0x1F  # 5 bits
            shot_m = ((pkt4[0] & 0x1) << 4) | ((pkt4[1] >> 4) & 0xF)  # 5 bits
            
            # Packet 5: COU(2) Buff(2) Power(8) EOL(4)
            pkt5 = packets[4]
            buff = (pkt5[0] >> 4) & 0x3  # 2 bits
            power = ((pkt5[0] & 0xF) << 4) | ((pkt5[1] >> 4) & 0xF)  # 8 bits
            
            # Packet 6: Check(4) COU(3) Hits(5) EOL(4)
            pkt6 = packets[5]
            check = (pkt6[0] >> 4) & 0xF  # 4 bits
            cou_6 = (pkt6[0] >> 1) & 0x7  # 3 bits
            hits = ((pkt6[0] & 0x1) << 4) | ((pkt6[1] >> 4) & 0xF)  # 5 bits
            
            runtime_globals.game_console.log(f"[DComBattleSimulator] DMX parsed: order={order}, level={level}, sick={sick}, attack={attack}")
            runtime_globals.game_console.log(f"[DComBattleSimulator] DMX parsed: stage={stage}, index={index}, attr={attribute}")
            runtime_globals.game_console.log(f"[DComBattleSimulator] DMX parsed: shot_s={shot_s}, shot_w={shot_w}, shot_m={shot_m}")
            runtime_globals.game_console.log(f"[DComBattleSimulator] DMX parsed: hp={hp}, buff={buff}, power={power}")
            runtime_globals.game_console.log(f"[DComBattleSimulator] DMX parsed: check={check}, hits=0b{hits:05b} ({hits})")
            
            # Map attribute to name (same as DM20)
            opponent_name = FALLBACK_NAMES.get(attribute, "DMX Opponent")
            
            opponent = Digimon(
                name=opponent_name,
                order=order,
                traited=0,
                egg_shake=0,
                index=index,
                hp=hp,
                attribute=attribute,
                power=power,
                handicap=0,
                buff=buff,
                mini_game=attack,  # Attack quality 0-3
                level=level,
                stage=stage,
                sick=sick,
                shot1=shot_s,
                shot2=shot_w,
                tag_meter=0
            )
            
            # Store parsed hits for later use in battle simulation
            opponent.dmx_hits = hits
            opponent.dmx_shot_m = shot_m
            
            return opponent
            
        except Exception as e:
            runtime_globals.game_console.log(f"[DComBattleSimulator] DMX parse error: {e}")
            import traceback
            runtime_globals.game_console.log(traceback.format_exc())
            return None
    
    def _parse_pen20_opponent(self, packets: List[bytes]) -> Optional[Digimon]:
        """Parse an opponent in the PEN20 layout.

        Only reached when a format selects the PEN20 wire; PEN20 currently
        goes out over DM20's (see protocol_constants.PEN20.DCOM_WIRE).

        Uses same attribute-based naming as DM20 (Va, Da, Vi, Fr).
        """
        try:
            if len(packets) < 10:
                runtime_globals.game_console.log(f"[DComBattleSimulator] PEN20 parse error: Need 10 packets, got {len(packets)}")
                return None
            
            # Packet 2: COU(2) Index(8) Attribute(2) EOL(4)
            pkt2 = packets[1]
            index = ((pkt2[0] & 0x3F) << 2) | ((pkt2[1] >> 6) & 0x3)
            attribute = (pkt2[1] >> 4) & 0x3
            
            # Packet 3: COU(4) Shot_W(8) EOL(4)
            pkt3 = packets[2]
            shot_w = ((pkt3[0] & 0xF) << 4) | ((pkt3[1] >> 4) & 0xF)

            # Packet 4: Sick(1) COU(3) Shot_S(8) EOL(4)
            pkt4 = packets[3]
            sick = (pkt4[0] >> 7) & 0x1
            shot_s = ((pkt4[0] & 0xF) << 4) | ((pkt4[1] >> 4) & 0xF)
            
            # Packet 5: COU(2) Traited(1) Egg_Shake(1) Power(8) EOL(4)
            pkt5 = packets[4]
            traited = (pkt5[0] >> 5) & 0x1
            egg_shake = (pkt5[0] >> 4) & 0x1
            power = ((pkt5[0] & 0xF) << 4) | ((pkt5[1] >> 4) & 0xF)
            
            # Map attribute to name (same as DM20)
            opponent_name = FALLBACK_NAMES.get(attribute, "PEN20 Opponent")
            
            runtime_globals.game_console.log(f"[DComBattleSimulator] PEN20 parsed: name={opponent_name}, attr={attribute}, power={power}")
            runtime_globals.game_console.log(f"[DComBattleSimulator] PEN20 parsed: shot_s={shot_s}, shot_w={shot_w}, index={index}")
            runtime_globals.game_console.log(f"[DComBattleSimulator] PEN20 parsed: sick={sick}, traited={traited}, egg_shake={egg_shake}")
            
            opponent = Digimon(
                name=opponent_name,
                order=1,
                traited=traited,
                egg_shake=egg_shake,
                index=index,
                hp=5,  # PEN20 uses fixed 5 HP
                attribute=attribute,
                power=power,
                handicap=0,
                buff=0,
                mini_game=3,
                level=1,
                stage=3,
                sick=sick,
                shot1=shot_s,
                shot2=shot_w,
                tag_meter=2
            )
            
            return opponent
            
        except Exception as e:
            runtime_globals.game_console.log(f"[DComBattleSimulator] PEN20 parse error: {e}")
            import traceback
            runtime_globals.game_console.log(traceback.format_exc())
            return None
    
    def resolve_sent_outcome(self, player_packets: List[bytes],
                             opponent_packets: List[bytes]) -> None:
        """Put the verdict we really sent into the packets we logged.

        Our packet 2 leaves here as a placeholder when the adapter is
        computing it -- ``DCOM_OUTCOME_ECHO`` is ``^3`` against the packet
        being replied to, which nothing on this side can fill in. The log
        would otherwise show the literal default and read as though we had
        declared a defeat we did not send, which is exactly the sort of
        thing that makes a capture impossible to interpret. DMX rewrites its
        own computed packet for the same reason.
        """
        if not (self.sent_echoed_outcome and len(player_packets) >= 2
                and len(opponent_packets) >= 2):
            return
        theirs = opponent_packets[1]
        ours = bytearray(player_packets[1])
        if len(theirs) < 2 or len(ours) < 2:
            return
        # ^3 on both digits that carry the outcome: the value (1<->2) and its
        # mirror (E<->D). The version digits stay ours.
        ours[0] = (ours[0] & 0xF0) | ((theirs[0] & 0x0F) ^ 0x3)
        ours[1] = (ours[1] & 0xF0) | ((theirs[1] & 0x0F) ^ 0x3)
        if bytes(ours) != player_packets[1]:
            runtime_globals.game_console.log(
                "[DComBattleSimulator] our packet 2 went out as %s, not %s "
                "(the adapter built it from theirs)"
                % (bytes(ours).hex().upper(), player_packets[1].hex().upper()))
            player_packets[1] = bytes(ours)

    def _parse_penog_opponent(self, packets: List[bytes]) -> Optional[Digimon]:
        """Read the Pendulum's four packets.

        Like the Digital Monster, this wire sends a slot rather than an
        identity, so the opponent gets the placeholder set; the slot's own
        band gives the stage. What it does carry is a real battle: its hits,
        its per-round attack strengths, and the effort behind them.
        """
        limits = protocol_constants.PENOG
        if len(packets) < limits.PACKET_COUNT:
            runtime_globals.game_console.log(
                f"[DComBattleSimulator] Incomplete PENOG packets: "
                f"{len(packets)}/{limits.PACKET_COUNT}")
            return None
        try:
            first = PENOGDevice.parse_packet1(packets[0]) or {}
            second = PENOGDevice.parse_packet2(packets[1]) or {}
            third = PENOGDevice.parse_packet3(packets[2]) or {}
            fourth = PENOGDevice.parse_packet4(packets[3]) or {}

            slot = first.get('slot', limits.FIRST_SLOT)
            version = first.get('version', 0)
            self.opponent_device_version = version
            stage = self._slot_stage(slot, limits)

            runtime_globals.game_console.log(
                "[DComBattleSimulator] PENOG parsed: slot=%d (stage %d), "
                "version=%d, sick=%d, effort=%d, attack=%s, hits=%s, shot=%d"
                % (slot, stage, version, first.get('sick', 0),
                   second.get('effort', 0), format(second.get('attack', 0), '05b'),
                   format(third.get('hits', 0), '05b'), fourth.get('shot', 0)))

            opponent = Digimon(
                name=getattr(self.wire, 'GENERIC_OPPONENT', None) or "Opponent",
                order=1, traited=0, egg_shake=0, index=0,
                hp=limits.FIXED_HP, attribute=3,
                # No power on this wire at all: effort is the only strength
                # figure, so it stands in for the presentation.
                power=second.get('effort', 0), handicap=0, buff=0,
                mini_game=0, level=1, stage=stage,
                sick=first.get('sick', 0),
                shot1=fourth.get('shot', 0), shot2=fourth.get('shot', 0),
                tag_meter=0,
            )
            opponent.version = version
            opponent.effort = second.get('effort', 0)
            opponent.penog_slot = slot
            opponent.penog_hits = third.get('hits', 0)
            opponent.penog_attack = second.get('attack', 0)
            return opponent
        except Exception as error:
            runtime_globals.game_console.log(
                f"[DComBattleSimulator] PENOG parse error: {error}")
            return None

    def _name_opponent(self, opponent: Digimon) -> None:
        """Give the opponent its real name, when the wire actually said one.

        Most wires carry the Digimon's position in the toy's own roster, and
        the module that reproduces that toy holds the same roster -- so when
        the player owns it, the index resolves to a name, a sprite and the
        device's own look instead of a generic attribute stand-in.

        Three things stop it, and each is a real answer rather than a
        failure:

        * a wire that declares ``GENERIC_OPPONENT`` exchanges no identity at
          all -- DMOG and PENOG send a slot, which is a tier and not a
          Digimon -- so the placeholder stands;
        * index 0 is what a compatibility pet sends, "an outsider" the
          device has no roster entry for, so there is nothing to resolve;
        * the player may simply not own the module.
        """
        if getattr(self.wire, 'GENERIC_OPPONENT', None):
            return
        index = getattr(opponent, 'index', 0) or 0
        if index <= 0:
            return
        # The devices spell "none" as the field filled with ones, the same
        # convention the shot ids use. A **Pendulum Color in Digital Monster
        # Color mode** sends exactly that -- filmed battle 42 announced
        # version 5, one past the DMC's own five, with index 0xFFFF: it is
        # saying it has no entry on this line's roster, which is true, and it
        # does not offer its Pendulum Color one instead. So there is nothing
        # to resolve, and the placeholder is the honest answer rather than a
        # failed lookup.
        limits = protocol_constants.get_constants(self.battle_format)
        sentinel = getattr(limits, 'MAX_INDEX', 0) if limits else 0
        if sentinel and index >= sentinel:
            runtime_globals.game_console.log(
                "[DComBattleSimulator] %s opponent sent index %d, the wire's "
                "\"none\" -- a device with nothing on this line's roster "
                "(a Pendulum Color in compatibility mode does this); keeping %s"
                % (self.battle_format, index, opponent.name))
            return
        # **Several modules can reproduce one line.** On the Colour line that
        # is the ordinary case: DMC, DMGZ, DMH and DMXW all declare DMC,
        # because the Godzilla, Monster Hunter and Xros Wars editions are
        # Digital Monster Colors with rosters of their own. The one named
        # after the format is tried first and answers every ordinary battle;
        # the crossovers are only reached when it has nothing, which is
        # exactly when the device said it was not one of the five.
        modules = modules_for_format(self.battle_format)
        if not modules:
            return
        module = modules[0]

        # The wire's version is not always the module's: each format clamps
        # (and the Colour line shifts) a version on the way out, so invert it
        # by asking which module versions would have produced this one.
        #
        # A version outside the format's own range is not a version at all --
        # it is what a device sends when it has nothing to say, and a real
        # Ver.20th announces **0** in an ordinary battle. Inverting that gave
        # every out-of-range number instead, a set the roster never uses, so
        # the lookup found nothing and every opponent stayed a bare attribute
        # name. Unstated means search the whole roster.
        wire_version = getattr(self, 'opponent_device_version', None)
        versions = protocol_constants.module_versions_for_wire(
            self.battle_format, wire_version)

        candidates = module.get_monsters_by_index(index, versions)
        if not candidates and len(modules) > 1:
            # A crossover edition. The Pico Terminal's own analyzer draws the
            # line in the same place -- on this wire a version above the
            # format's range means "a crossover device", and it then asks the
            # user which one, because the packet does not say. We can do
            # better than asking: the wire carries an index, an attribute and
            # a **power**, and a crossover roster is small, so the three
            # together usually leave exactly one Digimon across all of them.
            #
            # Filmed battle 44 is the case: a Monster Hunter edition
            # announced version 5, index 29, Free, power 170, and DMH's index
            # 29 is Thunderlord Zinogre -- Free, power 170, `atk_main` 74
            # against the packet's shot 73 (the wire is 0-based). DMGZ's index
            # 29 is a Virus Machinedramon at 185 and does not fit, so the
            # answer is unambiguous rather than a first match.
            #
            # A version is meaningless across rosters that number themselves
            # separately, so it is dropped here and the other fields carry it.
            for sibling in modules[1:]:
                candidates.extend(sibling.get_monsters_by_index(index, None))
            candidates = self._narrow_by_power(candidates, opponent)
            if candidates:
                runtime_globals.game_console.log(
                    "[DComBattleSimulator] %s index %d is not on %s's roster;"
                    " trying the crossovers on this line (%s)"
                    % (self.battle_format, index, module.name,
                       ", ".join(m.name for m in modules[1:])))
        # An index is per-version, so without a version it can name several
        # Digimon -- and how many depends entirely on the line. Not one index
        # on DM20's or PEN20's roster names two Digimon, but 60 of DMX's 76
        # do and 87 of PENZ's 100, because those lines reuse a fixed slot per
        # stage across every version. So the wire's other two identity fields
        # are worth spending: attribute takes DMX from 60 ambiguous to 32 and
        # stage takes it to 13 (PENZ 87 -> 53 -> 36). Each is applied only if
        # it leaves something, so a module disagreeing with the wire about a
        # Digimon's stage costs nothing.
        if versions is None and len(candidates) > 1:
            attribute = ATTRIBUTE_NAMES.get(getattr(opponent, 'attribute', None))
            if attribute:
                narrowed = [r for r in candidates
                            if r.get('attribute') == attribute]
                if narrowed:
                    candidates = narrowed
        if versions is None and len(candidates) > 1:
            stage = getattr(opponent, 'stage', None)
            if stage is not None:
                narrowed = [r for r in candidates if r.get('stage') == stage]
                if narrowed:
                    candidates = narrowed

        names = {record.get('name') for record in candidates}
        if not names:
            runtime_globals.game_console.log(
                "[DComBattleSimulator] %s index %d (version %s) is not on "
                "%s's roster; keeping %s"
                % (self.battle_format, index, wire_version, module.name,
                   opponent.name))
            return
        if len(names) > 1:
            # Two Digimon answer to this, and nothing on the wire separates
            # them. Naming one would be a coin toss shown as a fact.
            runtime_globals.game_console.log(
                "[DComBattleSimulator] %s index %d could be %s; nothing on "
                "the wire separates them, so keeping %s"
                % (self.battle_format, index, " or ".join(sorted(names)),
                   opponent.name))
            return

        record = candidates[0]
        runtime_globals.game_console.log(
            "[DComBattleSimulator] opponent resolved to %s (%s index %d, "
            "version %s)" % (record.get('name'), record.get('module',
                                                            module.name),
                             index, record.get('version')))
        opponent.name = record.get('name', opponent.name)
        #: Which module's roster answered. Usually the line's own, but a
        #: crossover edition has its own sprites -- and its own `atk/` folder,
        #: which is the whole reason battle 44's Monster Hunter opponent drew
        #: standard Colour shots. `pvp_payload` reads this.
        opponent.source_module = record.get('module', module.name)

    @staticmethod
    def _narrow_by_power(candidates, opponent):
        """Whittle *candidates* down with the identity the wire also carries.

        Power first, because it is the sharpest -- rosters standardise stats
        by stage, but not so tightly that two Digimon at one index on two
        different crossover rosters share one. Then attribute, and then
        stage. Each is applied only if it leaves something, so a module
        disagreeing with the wire about one field costs nothing.

        The attribute is matched against both spellings: a wire Free is
        `Free` in `ATTRIBUTE_NAMES` and an empty string in a module record,
        which is why matching on the name alone never narrowed a Free
        opponent.
        """
        if len(candidates) <= 1:
            return candidates

        power = getattr(opponent, 'power', None)
        if power:
            narrowed = [r for r in candidates if r.get('power') == power]
            if narrowed:
                candidates = narrowed

        if len(candidates) > 1:
            attribute = ATTRIBUTE_NAMES.get(getattr(opponent, 'attribute',
                                                    None))
            wanted = {attribute, ""} if attribute == "Free" else {attribute}
            if attribute:
                narrowed = [r for r in candidates
                            if (r.get('attribute') or "") in wanted
                            or r.get('attribute') == attribute]
                if narrowed:
                    candidates = narrowed

        if len(candidates) > 1:
            stage = getattr(opponent, 'stage', None)
            if stage is not None:
                narrowed = [r for r in candidates if r.get('stage') == stage]
                if narrowed:
                    candidates = narrowed
        return candidates

    def parse_colour_identity(self, packet: bytes):
        """The Digimon a Colour packet 1 describes, as a battle object.

        Only the fields the verdict needs -- power and attribute -- so it can
        be read from a single packet, before the exchange is finished.
        """
        from battle.sim.battle_simulator import DMCDevice

        if len(packet) != 16:
            return None
        words = self._colour_words(packet)
        line = protocol_constants.get_constants(self.battle_format)
        if ((words[0] << 16 | words[1]) != line.MAGIC or
                sum(words[:-1]) & 65535 != words[-1] or
                words[2] not in self.colour_operations()[:2] or
                words[6] not in line.ATTRIBUTE_MAP.values()):
            return None
        power = int.from_bytes(packet[10:12], "big")
        attribute = int.from_bytes(packet[12:14], "big")
        shaped = Digimon(
            name="Opponent", order=0, traited=0, egg_shake=0, index=0,
            hp=self.wire.FIXED_HP, attribute=attribute, power=power,
            handicap=0, buff=0, mini_game=0, level=1, stage=4, sick=0,
            shot1=0, shot2=0, tag_meter=0)
        return DMCDevice(shaped, limits=line)

    def _slot_stage(self, slot: int, limits=None) -> int:
        """The stage band a slot sits in: Child, Adult or Perfect."""
        limits = limits or protocol_constants.DMOG
        for top, stage in limits.SLOT_STAGES:
            if slot <= top:
                return stage
        return 5

    def _parse_dm_opponent(self, packets: List[bytes]) -> Optional[Digimon]:
        """Parse the original Digital Monster's two packets.

        The DM exchanges almost nothing: a slot with its 4-bit boost, and the
        battle verdict. **The slot is a tier, not an identity** -- "two
        Digimon in the same slot were effectively the same Digimon" -- so
        there is no way to say what the toy is holding, and a modern device
        in legacy mode maps its own roster onto the same twelve slots. The
        opponent therefore gets the placeholder set rather than a name
        recovered from a chart, which was wrong the moment anything but a
        real Digital Monster was on the other end.

        What the slot does give is the stage band and a representative power.
        """
        if len(packets) < 2:
            runtime_globals.game_console.log(
                f"[DComBattleSimulator] Incomplete DM packets: {len(packets)}/2")
            return None

        try:
            data = DMDevice.parse_packet1(packets[0]) or {}
            result = DMDevice.parse_packet2(packets[1]) or {}
            slot = data.get('slot', 0x3)
            boost = data.get('boost', 0)
            version = result.get('version', 1)
            self.opponent_device_version = version

            # Invert the slot back into a power, on the same scale our own
            # compatibility pets go out on -- the toy is a modern device and
            # its roster is not the Digital Monster's 0-60 one. Cosmetic
            # either way: this wire settles the battle from the outcome digit,
            # not from a power ratio.
            limits = protocol_constants.DMOG
            step = limits.COMPATIBILITY_POWER_PER_SLOT
            power = max(0, (slot - limits.FIRST_SLOT)) * step + step - 1

            # The battle scene loads the opponent's sprite from its name, and
            # this wire never says one, so it gets the placeholder set. The
            # generic attribute names the other wires fall back to would not
            # do: they read as a claim about an attribute this wire also
            # never sends, and Free has no sprite set at all.
            name = getattr(self.wire, 'GENERIC_OPPONENT', None) \
                or FALLBACK_NAMES.get(3, "Opponent")
            stage = self._slot_stage(slot)

            runtime_globals.game_console.log(
                f"[DComBattleSimulator] DM parsed: slot=0x{slot:X} "
                f"(stage {stage}, power ~{power}), boost={boost}, "
                f"version={version}, outcome={result.get('outcome')}")

            opponent = Digimon(
                name=name, order=1, traited=0, egg_shake=0, index=0,
                hp=protocol_constants.DMOG.FIXED_HP, attribute=3,
                power=power, handicap=0, buff=0, mini_game=boost, level=1,
                stage=stage, sick=0,
                # The DM exchanges no sprite ids either, and the device draws
                # the same shot for every Digimon -- so the opponent gets that
                # one rather than "no sprite", which would leave it unable to
                # animate an attack at all.
                shot1=protocol_constants.DMOG.FORCED_ATTACK_SPRITE,
                shot2=protocol_constants.DMOG.FORCED_ATTACK_SPRITE,
                tag_meter=0,
            )
            #: The slot as it arrived, not the power it was inverted into.
            #: The inversion is lossy -- twelve slots over a 0-240 range --
            #: and the slot is the only measure of strength this wire
            #: exchanges, so anything deciding a battle reads this.
            opponent.dm_slot = slot
            opponent.dm_boost = boost
            return opponent
        except Exception as e:
            runtime_globals.game_console.log(f"[DComBattleSimulator] DM parse error: {e}")
            import traceback
            runtime_globals.game_console.log(traceback.format_exc())
            return None

    def build_result(self, player: Digimon, opponent: Digimon,
                     player_packets: List[bytes], opponent_packets: List[str]) -> Optional[BattleResult]:
        """Build BattleResult from exchanged packets with turn-by-turn battle log."""
        # Nothing is decided until this exchange decides it.
        self.decided_player_wins = None
        self._penc_decoded = None
        self._last_player_packets = player_packets
        self._last_opponent_packets = opponent_packets
        runtime_globals.game_console.log("[DComBattleSimulator] Building battle result...")

        try:
            # Convert opponent hex strings to bytes for consistency
            opponent_bytes = [bytes.fromhex(pkt) for pkt in opponent_packets]
            opponent_bytes = self._join_wire_groups(opponent_bytes)
            player_packets = self._join_wire_groups(player_packets)
            self._last_player_packets = player_packets
            self._last_opponent_packets = opponent_bytes

            if not self._validate_packets(player_packets) or not self._validate_packets(opponent_bytes):
                return None
            if self.wire.NAME == 'DMC':
                mine, theirs = self._colour_words(player_packets[0]), self._colour_words(opponent_bytes[0])
                if mine[2] == theirs[2]:
                    return None  # Both streams claim the same role.

            # Turn resolution belongs to the packet layout: hits/dodges in
            # packet A on the DM20 wire, a 5-bit hit pattern in packet 6 on
            # the DMX one.
            wire = self.wire.NAME
            if self.wire.NAME == 'DMOG':
                # Before anything reads them: our verdict was the adapter's
                # to compute, so the packets we hold are not what went out.
                self.resolve_sent_outcome(player_packets, opponent_bytes)

            have = min(len(opponent_bytes), len(player_packets))
            # PEN20's packet A is Check|Dodges|Hits|EOL like DM20's, so the
            # two share the turn resolution even though the rest differs.
            if wire in ('DM20', 'PEN20') and have >= 10:
                battle_log = self._simulate_dm20_turns(player, opponent, player_packets, opponent_bytes)
            elif wire == 'DMX' and have >= 6:
                battle_log = self._simulate_dmx_turns(player, opponent, player_packets, opponent_bytes)
            elif wire == 'PENOG' and have >= 4:
                battle_log = self._simulate_penog_turns(player, opponent, player_packets, opponent_bytes)
            else:
                # DM exchanges a verdict rather than a hit pattern, and an
                # incomplete exchange has nothing to replay either.
                battle_log = self._simulate_outcome_turns(
                    player, opponent, opponent_bytes, player_packets)
                if not battle_log:
                    runtime_globals.game_console.log("[DComBattleSimulator] WARNING: No turn data available")

            # Calculate final HP based on battle log and protocol
            # Use protocol-specific initial HP, not the Digimon's HP field
            player_hp = self.get_initial_hp(player)
            opponent_hp = self.get_initial_hp(opponent)
            
            if battle_log:
                # Use final turn status (device1=opponent, device2=player)
                final_turn = battle_log[-1]
                opponent_hp = final_turn.device1_status[0].hp
                player_hp = final_turn.device2_status[0].hp
            
            # **The battle that was fought decides, where one was.** This
            # used to read the winner back out of the final HP in every
            # case, which is right for a staged presentation -- those are
            # built to end with the loser on zero -- and wrong for a battle
            # that is actually rolled, because that can end level. A PENC
            # battle did exactly that twice (filmed 57a at 2/2 and 57b at
            # 1/1): `fight_penc` said we won and the result said the device
            # did, from the same rounds.
            #
            # The old tie-break was "the initiator wins ties", meaning the
            # toy -- which stopped being true the moment START let us open
            # the exchange, and was the wrong way round in both battles.
            if self.decided_player_wins is not None:
                winner = "device2" if self.decided_player_wins else "device1"
            elif opponent_hp > player_hp:
                winner = "device1"  # Opponent won
            elif player_hp > opponent_hp:
                winner = "device2"  # Player won
            else:
                # Nothing decided it and the bars are level: the side that
                # opened the exchange keeps it, which is the same rule
                # `fight_penc` uses.
                winner = ("device2" if self.opening else "device1")
            
            runtime_globals.game_console.log(f"[DComBattleSimulator] Final HP: opponent={opponent_hp}, player={player_hp}, Winner: {winner}")
            
            # Create BattleResult (device1=opponent, device2=player)
            result = BattleResult(
                winner=winner,
                device1_final=[DigimonStatus(
                    name=opponent.name,
                    hp=opponent_hp,
                    alive=opponent_hp > 0
                )],
                device2_final=[DigimonStatus(
                    name=player.name,
                    hp=player_hp,
                    alive=player_hp > 0
                )],
                battle_log=battle_log,
                device1_packets=opponent_bytes,
                device2_packets=player_packets
            )
            
            return result
            
        except Exception as e:
            error_msg = f"[DComBattleSimulator] Result build error: {e}"
            runtime_globals.game_console.log(error_msg)
            import traceback
            trace = traceback.format_exc()
            runtime_globals.game_console.log(trace)
            return None
    
    def _settle_without_a_verdict(self, player: Digimon, opponent: Digimon):
        """Read the fought Colour result; missing device data is not a roll."""
        if protocol_constants.fights_its_battle(self.battle_format):
            decoded = self.penc_read_result(
                getattr(self, '_last_player_packets', None),
                getattr(self, '_last_opponent_packets', None))
            if decoded is not None:
                self._penc_decoded = decoded
                return decoded[0]
        raise ValueError('The exchange has no authoritative battle result')

    def _simulate_outcome_turns(self, player: Digimon, opponent: Digimon,
                                opponent_packets: List[bytes],
                                player_packets: List[bytes] = None):
        """Turn log for the DM wire, which exchanges a verdict not a pattern.

        The original Digital Monster declares who won in its second packet
        instead of sending per-round hits, so the presentation is built from
        that: the winner lands every round of the wire's turn count, the loser
        none.

        **A verdict is stated from the sender's point of view.** The toy
        writing 1 means the toy won, so it is our loss -- the same direction
        the DMC branch below already reads. This was inverted, on the
        reasoning that DMComm's code list "reads inverted, a code that says
        'I win' making the real toy lose". That observation is true and the
        conclusion drawn from it was backwards: wificom's punchbag named
        "DMOG you win" -- the one that makes the toy win -- sends outcome
        **2**, precisely because the digit describes whoever sent it. A
        filmed battle settled it: the device sent 1 and played a win.
        """
        from battle.sim.models import TurnLog, AttackLog, DigimonStatus

        outcome = 0
        if self.wire.NAME == 'DMOG' and len(opponent_packets) >= 2:
            # The toy's own result: 1 it won, 2 it lost, 0 not determined.
            # Flipped into ours, the way the DMC branch does just below.
            declared = (DMDevice.parse_packet2(opponent_packets[1]) or {}).get('outcome', 0)
            if declared in (protocol_constants.DMOG.OUTCOME_VICTORY,
                            protocol_constants.DMOG.OUTCOME_DEFEAT):
                outcome = (protocol_constants.DMOG.OUTCOME_DEFEAT
                           if declared == protocol_constants.DMOG.OUTCOME_VICTORY
                           else protocol_constants.DMOG.OUTCOME_VICTORY)
            runtime_globals.game_console.log(
                "[DComBattleSimulator] DMOG verdict: the device declared %d "
                "(%s for it), so we %s"
                % (declared,
                   {1: "victory", 2: "defeat"}.get(declared, "nothing"),
                   "win" if outcome == protocol_constants.DMOG.OUTCOME_VICTORY
                   else "lose" if outcome else "have no verdict"))

        elif (self.wire.NAME == 'DMC'
                and not protocol_constants.fights_its_battle(
                    self.battle_format)):
            # "Whether or not the device sending this signal wins the battle.
            # 0 for loss, 1 for victory. Only Operation 2 will report the
            # victory, Operation 3 sends 0 regardless" -- so the device's word
            # counts only when it was player one, which is the case whenever
            # it opened the exchange. parse_opponent leaves None otherwise.
            #
            # **A line that FIGHTS does not use this field**, so it is
            # excluded here rather than left to fall through. Naming PENC
            # alone let the Xros Wars line in, and it is fought too -- its
            # result lives in the responder's 0x23, so reading it as a DMC
            # verdict made two endpoints replaying one transcript disagree
            # about who won.
            declared = getattr(opponent, 'dmc_outcome', None)
            if declared is not None:
                outcome = 2 if declared == 1 else 1
            else:
                # **When WE opened, the verdict is in OUR packet.** Player
                # one declares it and player two "sends 0 regardless", so a
                # replay that only reads the opponent's finds nothing and
                # falls through to `_settle_without_a_verdict` -- which rolls
                # again, and can contradict the packet we already put on the
                # wire. Two endpoints replaying the same transcript then
                # disagree about who won.
                mine = self._colour_words((player_packets or [None, None])[1]
                                          if len(player_packets or []) > 1
                                          else None)
                offset = getattr(protocol_constants.get_constants(
                    self.battle_format), 'OPERATION_OFFSET', 0)
                if mine and mine[2] - offset == 2:
                    outcome = 1 if mine[4] else 2
                    runtime_globals.game_console.log(
                        "[DComBattleSimulator] %s: reading the verdict we "
                        "sent ourselves -- word4=%d, so we %s"
                        % (self.battle_format, mine[4],
                           "win" if outcome == 1 else "lose"))

        if outcome not in (1, 2):
            player_wins = self._settle_without_a_verdict(player, opponent)
        else:
            player_wins = outcome == 1
        self.decided_player_wins = player_wins
        runtime_globals.game_console.log(
            f"[DComBattleSimulator] {self.battle_format} outcome: "
            f"{'player wins' if player_wins else 'device wins'}")

        turns = getattr(self.wire, 'TURNS', 4)
        player_hp = self.get_initial_hp(player)
        opponent_hp = self.get_initial_hp(opponent)
        # Spread the loser's HP over the rounds so the bar drains across the
        # whole animation instead of emptying on the first hit. Rounded up, so
        # the last round is always the knockout.
        # Both verdict wires present the same battle: neither exchanges a
        # hit pattern, so the rounds are ours to stage, and staging them the
        # same way keeps one behaviour to reason about. The DMOG log used to
        # give the loser no shot at all, which reads as a walkover rather
        # than a battle.
        if protocol_constants.fights_its_battle(self.battle_format):
            return self._simulate_penc_turns(player, opponent, player_wins)
        if self.wire.NAME in ('DMC', 'DMOG'):
            return self._simulate_verdict_turns(player, opponent, player_wins)

        losing_hp = opponent_hp if player_wins else player_hp
        damage = max(1, -(-losing_hp // max(1, turns)))

        battle_log = []
        for turn in range(turns):
            if player_wins:
                opponent_hp = max(0, opponent_hp - damage)
            else:
                player_hp = max(0, player_hp - damage)
            battle_log.append(TurnLog(
                turn=turn + 1,
                device1_status=[DigimonStatus(name=opponent.name, hp=opponent_hp,
                                              alive=opponent_hp > 0)],
                device2_status=[DigimonStatus(name=player.name, hp=player_hp,
                                              alive=player_hp > 0)],
                attacks=[
                    AttackLog(turn=turn + 1, device="device1", attacker=0, defender=0,
                              hit=not player_wins, damage=damage if not player_wins else 0,
                              critical=False),
                    AttackLog(turn=turn + 1, device="device2", attacker=0, defender=0,
                              hit=player_wins, damage=damage if player_wins else 0,
                              critical=False),
                ],
            ))
            if player_hp == 0 or opponent_hp == 0:
                break

        return battle_log

    def _simulate_penog_turns(self, player: Digimon, opponent: Digimon,
                              player_packets: List[bytes],
                              opponent_packets: List[bytes]):
        """The Pendulum's battle, read straight off both sides' packets.

        Each side sends its own five-round Hits pattern and its own Attack
        pattern, both read right to left, one bit per round. "Weak attacks
        deal 1 damage while strong attacks deal 2", against 3 HP a side.

        The initiator strikes first -- "the initiating device will have a 1
        for order" is how the document defines it, and although this wire
        carries no Order bit, the turn we opened on says which of us that is.
        """
        from battle.sim.models import TurnLog, AttackLog, DigimonStatus

        limits = protocol_constants.PENOG
        mine = PENOGDevice.parse_packet3(player_packets[2]) or {}
        my_attack = (PENOGDevice.parse_packet2(player_packets[1]) or {}).get('attack', 0)
        theirs = PENOGDevice.parse_packet3(opponent_packets[2]) or {}
        their_attack = (PENOGDevice.parse_packet2(opponent_packets[1]) or {}).get('attack', 0)

        my_hits, their_hits = mine.get('hits', 0), theirs.get('hits', 0)
        runtime_globals.game_console.log(
            "[DComBattleSimulator] PENOG hits - player %s (attack %s), "
            "device %s (attack %s)"
            % (format(my_hits, '05b'), format(my_attack, '05b'),
               format(their_hits, '05b'), format(their_attack, '05b')))

        player_hp = self.get_initial_hp(player)
        opponent_hp = self.get_initial_hp(opponent)
        # We opened unless the exchange was answered, and the opener shoots
        # first.
        device_first = not self.goes_first

        battle_log = []
        for turn in range(limits.TURNS):
            my_hit = (my_hits >> turn) & 1
            their_hit = (their_hits >> turn) & 1
            my_damage = 2 if (my_attack >> turn) & 1 else 1
            their_damage = 2 if (their_attack >> turn) & 1 else 1

            if device_first:
                if their_hit:
                    player_hp = max(0, player_hp - their_damage)
                if my_hit and player_hp > 0:
                    opponent_hp = max(0, opponent_hp - my_damage)
                elif my_hit:
                    my_hit = 0
            else:
                if my_hit:
                    opponent_hp = max(0, opponent_hp - my_damage)
                if their_hit and opponent_hp > 0:
                    player_hp = max(0, player_hp - their_damage)
                elif their_hit:
                    their_hit = 0

            battle_log.append(TurnLog(
                turn=turn + 1,
                device1_status=[DigimonStatus(name=opponent.name, hp=opponent_hp,
                                              alive=opponent_hp > 0)],
                device2_status=[DigimonStatus(name=player.name, hp=player_hp,
                                              alive=player_hp > 0)],
                attacks=[
                    # Never critical. This wire has exactly two attack
                    # levels, weak and strong, and a strong shot is the
                    # ordinary top of that scale -- not the DMX's CRITICAL,
                    # which is a fifth attack type worth 10 HP. Flagging it
                    # played the critical slide-in on roughly half the shots
                    # of a three-HP battle.
                    AttackLog(turn=turn + 1, device="device1", attacker=0,
                              defender=0, hit=bool(their_hit),
                              damage=their_damage, critical=False),
                    AttackLog(turn=turn + 1, device="device2", attacker=0,
                              defender=0, hit=bool(my_hit),
                              damage=my_damage, critical=False),
                ],
            ))
            if player_hp == 0 or opponent_hp == 0:
                break

        runtime_globals.game_console.log(
            f"[DComBattleSimulator] PENOG battle: {len(battle_log)} rounds, "
            f"device {opponent_hp}, player {player_hp}")
        return battle_log

    def penc_attributes(self, player: Digimon, opponent: Digimon):
        """Both sides' attributes in the Colour line's own encoding.

        Ours is already there -- `pet_to_digimon` put it there -- while the
        opponent's was turned back into Omnipet's when its packet was parsed,
        so it goes forward again rather than the two being compared on
        different scales.
        """
        limits = protocol_constants.get_constants(self.battle_format)
        theirs = getattr(limits, 'ATTRIBUTE_MAP', {}).get(
            opponent.attribute, opponent.attribute)
        return player.attribute, theirs

    @staticmethod
    def _colour_words(packet):
        """A Colour packet as eight big-endian 16-bit words, or None."""
        if isinstance(packet, str):
            try:
                packet = bytes.fromhex(packet)
            except ValueError:
                return None
        if not packet or len(packet) < 16:
            return None
        return [int.from_bytes(packet[i:i + 2], "big") for i in range(0, 16, 2)]

    def colour_operations(self):
        """This line's four battle operations, from its own base.

        Every Colour line numbers the same four roles from a base of its
        own -- 0x00 on a Digital Monster Color, 0x10 on a Pendulum Color,
        0x20 on an Xros Wars -- so the roles are read relative to the base
        rather than written out. Returns (P1 Digimon, P2 Digimon, P1 battle,
        P2 battle).
        """
        base = getattr(protocol_constants.get_constants(self.battle_format),
                       'OPERATION_OFFSET', 0)
        return base, base + 1, base + 2, base + 3

    def penc_read_result(self, player_packets, opponent_packets):
        """The battle, decoded out of the exchange itself.

        **The result is in the RESPONDER's battle packet** -- 0x13 on a
        Pendulum Color, 0x23 on an Xros Wars -- which is not where the
        Digital Monster Color puts it. Those lines share a layout rather
        than a battle, and reading it in the DMC's place is what made every
        PENC battle come out wrong.

        The packet can have come from either side, and which side we were is
        read off the operations that actually went on the wire rather than
        assumed from the turn.

        **Measured on both lines.** PENC over 17 filmed battles; DMXW in one
        exchange whose every field checked out -- we answered its 0x20 with a
        0x23 carrying zeros, which says "the initiator lost and missed every
        round", and the device duly lost having been hit three times.

        Returns (we_won, our hits, their hits), or None when this exchange
        carries no responder battle packet at all.
        """
        from battle.sim.battle_utils import penc_result_from_wire

        p1_digimon, _p2_digimon, _p1_battle, p2_battle = self.colour_operations()
        ours = [self._colour_words(p) for p in (player_packets or [])]
        theirs = [self._colour_words(p) for p in (opponent_packets or [])]
        ours = [w for w in ours if w]
        theirs = [w for w in theirs if w]

        # Whoever sent the P1 Digimon packet opened it. That is the wire's
        # own account, and it disagrees with the button that was pressed
        # often enough to matter.
        we_are_initiator = any(w[2] == p1_digimon for w in ours)
        if not we_are_initiator and not any(w[2] == p1_digimon for w in theirs):
            return None

        result_packet = next((w for w in ours + theirs if w[2] == p2_battle),
                             None)
        if result_packet is None:
            return None

        if self.battle_format == 'DMXW':
            # ROM result word also carries a non-victory flag in bit 1.
            result_packet[4] &= 1

        we_won, our_hits, their_hits = penc_result_from_wire(
            result_packet, we_are_initiator)
        runtime_globals.game_console.log(
            "[DComBattleSimulator] %s result read off operation 0x%02X: "
            "we %s the exchange, word4=%d word5=0x%04X -> we %s, our hits %s"
            % (self.battle_format, p2_battle,
               "opened" if we_are_initiator else "answered",
               result_packet[4], result_packet[5],
               "win" if we_won else "lose",
               "".join("H" if h else "." for h in our_hits)))
        return we_won, our_hits, their_hits

    def penc_selectors(self, player_packets, opponent_packets):
        """Each side's attack-pattern selector, from its own battle packet."""
        _p1d, _p2d, p1_battle, p2_battle = self.colour_operations()

        def selector(packets):
            for packet in packets or []:
                words = self._colour_words(packet)
                if words and words[2] in (p1_battle, p2_battle):
                    return words[6]
            return None
        return selector(player_packets), selector(opponent_packets)

    def _fight_penc(self, player: Digimon, opponent: Digimon):
        """Fight the battle out, and keep the rounds it produced.

        The Pendulum Color exchanges no verdict, so this is not a fallback on
        that line -- it is the battle. `battle_utils.fight_penc` is the one
        place it happens, and the versus path calls the same function with
        two of our own pets. That is the whole of the difference between a
        DCom battle and a versus battle here.
        """
        from battle.sim.battle_utils import fight_penc

        my_attribute, their_attribute = self.penc_attributes(player, opponent)
        player_wins, rounds = fight_penc(
            player.power, my_attribute, getattr(player, 'mini_game', 0) or 0,
            opponent.power, their_attribute,
            getattr(opponent, 'mini_game', 0) or 0,
            a_stage=getattr(player, 'stage', 1) or 1,
            b_stage=getattr(opponent, 'stage', 1) or 1,
            battle_format=self.battle_format,
            a_effort=getattr(player, 'effort', 0) or 0,
            b_effort=getattr(opponent, 'effort', 0) or 0)
        self._penc_rounds = rounds
        runtime_globals.game_console.log(
            "[DComBattleSimulator] PENC fought it out over %d round(s): %s"
            % (len(rounds), "we win" if player_wins else "the device wins"))
        return player_wins

    def _simulate_penc_turns(self, player: Digimon, opponent: Digimon,
                             player_wins: bool):
        """The turn log for a Pendulum Color battle, as the wire reported it.

        **Nothing here is rolled.** The exchange carries the whole battle --
        who won and which rounds landed, in operation 0x13 -- and each side's
        attack selector says what it threw. Replaying that is the only way
        the two screens can agree; rolling a fresh battle afterwards, however
        faithfully, produces a different one every time.

        Where the exchange had no 0x13 to read, `_fight_penc` has already
        fought one and its rounds are used instead.
        """
        from battle.sim.models import TurnLog, AttackLog, DigimonStatus
        from battle.sim.battle_utils import (get_penc_wire_pattern,
                                             penc_charge_pattern)

        limits = protocol_constants.get_constants(self.battle_format)
        decoded = getattr(self, '_penc_decoded', None)

        if decoded is None:
            rounds = getattr(self, '_penc_rounds', None)
            if not rounds:
                self._fight_penc(player, opponent)
                rounds = getattr(self, '_penc_rounds', []) or []
            steps = [(r.a_damage, r.a_hit, r.b_damage, r.b_hit) for r in rounds]
        else:
            _won, our_hits, their_hits = decoded
            our_sel, their_sel = self.penc_selectors(
                getattr(self, '_last_player_packets', None),
                getattr(self, '_last_opponent_packets', None))
            ours = (get_penc_wire_pattern(our_sel) if our_sel is not None
                    else penc_charge_pattern(player, self.battle_format))
            theirs = (get_penc_wire_pattern(their_sel) if their_sel is not None
                      else penc_charge_pattern(opponent, self.battle_format))
            steps = list(zip(ours, our_hits, theirs, their_hits))
            runtime_globals.game_console.log(
                "[DComBattleSimulator] PENC selectors: ours 0x%s -> %s, "
                "device 0x%s -> %s"
                % ("----" if our_sel is None else "%04X" % our_sel, ours,
                   "----" if their_sel is None else "%04X" % their_sel, theirs))

        player_hp = opponent_hp = limits.FIXED_HP
        battle_log = []
        for turn, (our_damage, our_hit, their_damage, their_hit) in \
                enumerate(steps[:limits.TURNS], start=1):
            if our_hit:
                opponent_hp = max(0, opponent_hp - our_damage)
            if their_hit:
                player_hp = max(0, player_hp - their_damage)
            battle_log.append(TurnLog(
                turn=turn,
                device1_status=[DigimonStatus(name=opponent.name,
                                              hp=opponent_hp,
                                              alive=opponent_hp > 0)],
                device2_status=[DigimonStatus(name=player.name, hp=player_hp,
                                              alive=player_hp > 0)],
                attacks=[
                    # device1 is the toy: the packets are exchanged toy-first,
                    # so that is the order a result comes out in.
                    AttackLog(turn=turn, device="device1", attacker=0,
                              defender=0, hit=their_hit, damage=their_damage,
                              critical=False),
                    AttackLog(turn=turn, device="device2", attacker=0,
                              defender=0, hit=our_hit, damage=our_damage,
                              critical=False),
                ],
            ))
            if player_hp == 0 or opponent_hp == 0:
                break
        return battle_log

    def _simulate_verdict_turns(self, player: Digimon, opponent: Digimon,
                                player_wins: bool):
        """A battle on a wire that exchanges a verdict and nothing else.

        Four rounds: three traded singles, then the winner's double against
        the loser's single **that misses**. The winner spends 1+1+1+2 = 5,
        exactly the HP its opponent started with, and takes 1+1+1 = 3 of its
        own, so it finishes on 2. Nothing about it varies except who wins,
        which is the one thing the packets carry. There is no charge on
        either of these wires.

        Both halves are measured off film. Battle 1 gave the four rounds --
        three traded singles, then the double. Battle 3 gave the miss: the
        device won that one, and its last round played
        "Device Double / Game Single Miss". The loser fires as it goes down
        and the shot does not land.

        The table lives in data/attack_patterns/DMC.json.

        Shared by the Color line and the original Digital Monster: both send
        a result rather than a hit pattern, so both have the same nothing to
        reconstruct a battle from, and the Color line's battles are built on
        the Digital Monster's.
        """
        from battle.sim.models import TurnLog, AttackLog, DigimonStatus
        from battle.sim.battle_utils import verdict_rounds

        player_hp = self.get_initial_hp(player)
        opponent_hp = self.get_initial_hp(opponent)
        # The rounds follow the bar rather than a fixed row: this shape was
        # measured on the Digital Monster's five, and the Pendulum Color
        # fights at three, where a five-HP row spends 5 against a 3-HP bar --
        # killing the loser a round early and leaving the last round dead.
        # At 5 it is `DMC.json`'s measured row exactly.
        winner_pattern, loser_pattern = verdict_rounds(
            opponent_hp if player_wins else player_hp)
        battle_log = []

        for turn in range(min(len(winner_pattern), len(loser_pattern))):
            winner_damage = winner_pattern[turn]
            loser_damage = loser_pattern[turn]
            # The winner strikes first, and the loser answers only while it
            # is still standing. On the last round it is not: its shot goes
            # out and misses, which is what the film shows.
            if player_wins:
                opponent_hp = max(0, opponent_hp - winner_damage)
                loser_hit = opponent_hp > 0
                if loser_hit:
                    player_hp = max(0, player_hp - loser_damage)
            else:
                player_hp = max(0, player_hp - winner_damage)
                loser_hit = player_hp > 0
                if loser_hit:
                    opponent_hp = max(0, opponent_hp - loser_damage)

            battle_log.append(TurnLog(
                turn=turn + 1,
                device1_status=[DigimonStatus(name=opponent.name, hp=opponent_hp,
                                              alive=opponent_hp > 0)],
                device2_status=[DigimonStatus(name=player.name, hp=player_hp,
                                              alive=player_hp > 0)],
                attacks=[
                    AttackLog(turn=turn + 1, device="device1", attacker=0, defender=0,
                              hit=True if not player_wins else loser_hit,
                              damage=winner_damage if not player_wins else loser_damage,
                              critical=False),
                    AttackLog(turn=turn + 1, device="device2", attacker=0, defender=0,
                              hit=True if player_wins else loser_hit,
                              damage=winner_damage if player_wins else loser_damage,
                              critical=False),
                ],
            ))
            if player_hp == 0 or opponent_hp == 0:
                break

        runtime_globals.game_console.log(
            f"[DComBattleSimulator] {self.wire.NAME} battle: {len(battle_log)} rounds, "
            f"device {opponent_hp}, player {player_hp}")
        return battle_log

    def _simulate_dm20_turns(self, player: Digimon, opponent: Digimon,
                            player_packets: List[bytes], opponent_packets: List[bytes]):
        """Simulate turn-by-turn battle from DM20 packet A hits/dodges."""
        from battle.sim.models import TurnLog, AttackLog, DigimonStatus
        from battle.sim.battle_utils import get_dm20_single_battle_attack_pattern
        
        runtime_globals.game_console.log("[DComBattleSimulator] Simulating DM20 battle turns...")
        
        # Extract packet A (packet 10) from both devices
        player_pktA = player_packets[9]   # Our packet A
        opponent_pktA = opponent_packets[9]  # Device's packet A
        
        # Extract hits from Packet A
        # Per DMCom protocol (dm20.py BattleOrCopyView):
        #   Packet 10 as 16-bit value (big-endian): CCCC HHHH YYYY EEEE
        #   - Check = bits 12-15 (>> 12)
        #   - hit_me = bits 8-11 ((>> 8) & 0xF) = which of MY attacks HIT YOU
        #   - hit_you = bits 4-7 ((>> 4) & 0xF) = which of YOUR attacks HIT ME
        #   - EOL = bits 0-3
        #
        # As bytes: Byte0 = CCCC HHHH (Check | hit_me), Byte1 = YYYY EEEE (hit_you | EOL)
        # 
        # For opponent's packet:
        #   opponent.hit_you = which of opponent's attacks HIT US (we take damage)
        #   opponent.hit_me = which of OUR attacks HIT OPPONENT (they take damage)
        
        opponent_hit_you = (opponent_pktA[1] >> 4) & 0x0F  # Upper 4 bits of byte 1 = their hits on us
        opponent_hit_me = opponent_pktA[0] & 0x0F         # Lower 4 bits of byte 0 = our hits on them
        
        runtime_globals.game_console.log(f"[DComBattleSimulator] Opponent PacketA: hit_you=0x{opponent_hit_you:X} (their hits on us), hit_me=0x{opponent_hit_me:X} (our hits on them)")
        
        # Convert to bit arrays (bit 0 = turn 1, bit 1 = turn 2, etc)
        # opponent_attack_hits: whether opponent's attack HIT us this turn (1=we take damage)
        # player_attack_hits: whether OUR attack HIT opponent (1=they take damage)
        opponent_attack_hits = [(opponent_hit_you >> i) & 1 for i in range(4)]
        player_attack_hits = [(opponent_hit_me >> i) & 1 for i in range(4)]  # Direct hit indicator, NOT inverted!
        
        runtime_globals.game_console.log(f"[DComBattleSimulator] Opponent hits us (per turn): {opponent_attack_hits}")
        runtime_globals.game_console.log(f"[DComBattleSimulator] Player hits opponent (per turn): {player_attack_hits}")
        
        # Extract player's pattern index from player_packets[2] (Packet 3)
        # The charge picks the attack pattern, and the two wires keep it in
        # different packets -- the same split the Order bit has.
        #   DM20   packet 3: Order(1) | Attack(5) | Operation(2) | Version(4) | EOL(4)
        #   PEN20  packet 1: Order(1) | COU(1) | Attack(4) | Operation(2) | Version(4) | EOL(4)
        # Reading DM20's position out of a PEN20 exchange found the field in
        # packet 3, where PEN20 keeps something else entirely, and every
        # battle came out as pattern 0 however hard the meter was charged.
        if self.wire.NAME == 'PEN20':
            attack_packet, shift, mask = 0, 2, 0xF
        else:
            attack_packet, shift, mask = 2, 2, 0x1F

        # And the two lines have different tables. Not one of PEN20's fifteen
        # rows matches DM20's; a filmed battle settles it, its bar running
        # 10 -> 7 -> 4 -> 0, which is PEN20's row 10 exactly.
        from battle.sim.battle_utils import get_20th_single_battle_attack_pattern
        wire = self.wire.NAME

        player_pattern_index = (player_packets[attack_packet][0] >> shift) & mask
        player_pattern = get_20th_single_battle_attack_pattern(
            player_pattern_index, wire)

        opponent_pattern_index = (opponent_packets[attack_packet][0] >> shift) & mask
        opponent_pattern = get_20th_single_battle_attack_pattern(
            opponent_pattern_index, wire)
        
        runtime_globals.game_console.log(f"[DComBattleSimulator] Player pattern (index {player_pattern_index}): {player_pattern}")
        runtime_globals.game_console.log(f"[DComBattleSimulator] Opponent pattern (index {opponent_pattern_index}): {opponent_pattern}")
        
        # The wire's HP, not a literal: ten on this line, for every Digimon
        # whatever its stage.
        player_hp = self.wire.FIXED_HP
        opponent_hp = self.wire.FIXED_HP
        battle_log = []
        
        # Determine attack order based on Order field from Packet 3
        # Extract order from player's packet 3 (byte 0, bit 7)
        # Order rides in packet 3 on the DM20 wire and packet 1 on PEN20's.
        order_packet = 0 if self.wire.NAME == 'PEN20' else 2
        player_order = (player_packets[order_packet][0] >> 7) & 1
        opponent_order = (opponent_packets[order_packet][0] >> 7) & 1
        
        runtime_globals.game_console.log(f"[DComBattleSimulator] Player order={player_order}, Opponent order={opponent_order}")
        
        # Order=1 means initiating (attacks first), Order=0 means replying (attacks second)
        opponent_attacks_first = (opponent_order > player_order)
        
        # **A replay may only spend what the packets carry.** The manual
        # gives max Strength "+1 damage for each attack in Single Battles",
        # and this used to apply it from our own `strength_full` -- a flag
        # that is nowhere on the wire, and that the toy has no equivalent of
        # in anything it sends. Holding both packet streams fixed and
        # toggling only that flag flipped the winner, so the two endpoints
        # replaying one transcript disagreed about the HP and about who won.
        #
        # The bonus is not gone: an adventure battle still spends it, where
        # both sides are ours and there is nothing to agree with. What a
        # connection battle spends is what was transmitted -- the Power field
        # already carries what the meter bought, which is the part of the
        # bonus the wire does express.
        strength_bonus = 0

        # Five turns, and the pattern now has a value for each of them -- the
        # measured table is five long where the one it replaced was four, and
        # turn 5 used to wrap round to turn 1's value. The hit bits really are
        # four, so those still wrap.
        for turn in range(5):
            attack_index = turn
            hit_index = turn if turn < 4 else 0  # Packet A holds four bits
            
            if opponent_attacks_first:
                # Opponent attacks first
                opponent_hit = opponent_attack_hits[hit_index]
                opponent_attack = opponent_pattern[attack_index]
                player_damage = opponent_attack if opponent_hit else 0
                player_hp = max(0, player_hp - player_damage)
                
                # Player attacks second
                player_hit = player_attack_hits[hit_index]
                player_attack = player_pattern[attack_index] + strength_bonus
                opponent_damage = player_attack if player_hit else 0
                opponent_hp = max(0, opponent_hp - opponent_damage)
                
                runtime_globals.game_console.log(f"[DComBattleSimulator] Turn {turn+1}: Opponent hit={bool(opponent_hit)} dmg={player_damage}, Player hit={bool(player_hit)} dmg={opponent_damage}")
            else:
                # Player attacks first
                player_hit = player_attack_hits[hit_index]
                player_attack = player_pattern[attack_index] + strength_bonus
                opponent_damage = player_attack if player_hit else 0
                opponent_hp = max(0, opponent_hp - opponent_damage)
                
                # Opponent attacks second
                opponent_hit = opponent_attack_hits[hit_index]
                opponent_attack = opponent_pattern[attack_index]
                player_damage = opponent_attack if opponent_hit else 0
                player_hp = max(0, player_hp - player_damage)
                
                runtime_globals.game_console.log(f"[DComBattleSimulator] Turn {turn+1}: Player hit={bool(player_hit)} dmg={opponent_damage}, Opponent hit={bool(opponent_hit)} dmg={player_damage}")
            
            runtime_globals.game_console.log(f"[DComBattleSimulator] Turn {turn+1} HP: Player {player_hp}, Opponent {opponent_hp}")
            
            # Log the turn (device1=opponent, device2=player)
            # IMPORTANT: Store the ATTACK PATTERN VALUE (what attack was attempted), not dealt damage
            # The battle scene needs to know the attack type (1=weak, 2=strong) even on misses
            # The 'hit' field indicates whether the attack connected
            turn_log = TurnLog(
                turn=turn + 1,
                device1_status=[DigimonStatus(name=opponent.name, hp=opponent_hp, alive=opponent_hp > 0)],
                device2_status=[DigimonStatus(name=player.name, hp=player_hp, alive=player_hp > 0)],
                attacks=[
                    AttackLog(turn=turn+1, device="device1", attacker=0, defender=0, hit=bool(opponent_hit), damage=opponent_attack, critical=(opponent_attack == 5)),
                    AttackLog(turn=turn+1, device="device2", attacker=0, defender=0, hit=bool(player_hit), damage=player_attack, critical=(player_attack == 5))
                ]
            )
            battle_log.append(turn_log)

            # End battle if one is defeated (but still complete current turn's log entry)
            if player_hp == 0 or opponent_hp == 0:
                runtime_globals.game_console.log(f"[DComBattleSimulator] Battle ended after turn {turn+1}")
                break
        
        runtime_globals.game_console.log(f"[DComBattleSimulator] Battle complete with {len(battle_log)} turns")
        return battle_log

    @staticmethod
    def _rebuild_dmx_final(packets, hits):
        """Packet 6 as the adapter actually sent it, for the packet log.

        Check(4) COU(3) Hits(5) EOL(4), the check nibble chosen so every
        nibble we sent sums to the wire's remainder.
        """
        import struct
        eol = protocol_constants.DMX.EOL
        byte1_without_check = ((hits >> 4) & 0x1)
        byte2 = ((hits & 0x0F) << 4) | (eol & 0xF)

        checksum = 0
        for pkt in packets[:5]:
            for byte in pkt:
                checksum += (byte >> 4) & 0x0F
                checksum += byte & 0x0F
        checksum += byte1_without_check & 0x0F
        checksum += (byte2 >> 4) & 0x0F
        checksum += byte2 & 0x0F

        target = protocol_constants.DMX.CHECKSUM_REMAINDER
        check = (target - (checksum % 16)) % 16
        return struct.pack(">BB", (check << 4) | byte1_without_check, byte2)

    def _simulate_dmx_turns(self, player: Digimon, opponent: Digimon, 
                           player_packets: List[bytes], opponent_packets: List[bytes]):
        """
        Simulate turn-by-turn battle from DMX/PENZ packet 6 hits.
        
        DMX Battle System:
        - 5 rounds total
        - Each side has 5 hit bits indicating which attacks landed
        - Attack pattern determined by: Level + minigame result (0-3)
        - Attack types: 1=SINGLE_WEAK, 2=SINGLE_STRONG, 3=DOUBLE_WEAK, 4=DOUBLE_STRONG, 5=CRITICAL
        - Pattern value is base damage (1-5), plus buff bonus (0-2), plus level attack bonus (0-2)
        - Level bonuses: +1 attack at level 4, +1 attack at level 7
        - Winner is whoever has more HP at end (ties freeze device, we give to initiator)
        """
        from battle.sim.models import TurnLog, AttackLog, DigimonStatus
        from battle.sim.battle_utils import get_attack_pattern, get_attack_damage
        
        runtime_globals.game_console.log("[DComBattleSimulator] Simulating DMX battle turns...")
        
        # Extract hits from Packet 6 for both devices
        # Packet 6 format: Check(4) COU(3) Hits(5) EOL(4)
        player_pkt6 = player_packets[5]
        opponent_pkt6 = opponent_packets[5]
        
        # Extract 5-bit hits from packet 6
        # Hits is in bits 4-8 (5 bits), spanning bytes 0-1
        player_hits = ((player_pkt6[0] & 0x1) << 4) | ((player_pkt6[1] >> 4) & 0xF)
        opponent_hits = ((opponent_pkt6[0] & 0x1) << 4) | ((opponent_pkt6[1] >> 4) & 0xF)
        
        # Each side sends only its OWN hits on this wire -- packet 6 is
        # Check(4) COU(3) Hits(5) EOL(4), one pattern, unlike DM20's packet A
        # which carries both sides. The toy applies ours exactly as sent, so
        # what we score has to be what actually went out.
        #
        # And what goes out is the inverse of the toy's, computed by the
        # adapter from the packet 6 it just received (DMX.DCOM_FINAL_SEGMENT).
        # The locally generated packet 6 is only a placeholder standing in for
        # it, so it is rebuilt here for the record.
        # Packet 1's version is the same kind of placeholder when the adapter
        # copied the device's in (DMX.DCOM_VERSION_ECHO). Restore it first, so
        # the checksum the final packet is rebuilt against is the one that
        # actually went out.
        if self.sent_echoed_version and player_packets and opponent_packets:
            their_version = opponent_packets[0][1] >> 4
            mine = bytearray(player_packets[0])
            mine[1] = (their_version << 4) | (mine[1] & 0x0F)
            player_packets[0] = bytes(mine)
            runtime_globals.game_console.log(
                f"[DComBattleSimulator] Mirrored the device's version "
                f"{their_version} into packet 1")

        if self.sent_computed_final:
            player_hits = (~opponent_hits) & 0x1F
            # Written back into the caller's list on purpose: it is the record
            # of what was sent, and the placeholder never went on the wire.
            player_packets[5] = self._rebuild_dmx_final(player_packets, player_hits)
            source = "inverse of the device's, as the adapter sent it"
        else:
            source = "as sent"

        runtime_globals.game_console.log(f"[DComBattleSimulator] Player hits: 0b{player_hits:05b} ({player_hits}) ({source})")
        runtime_globals.game_console.log(f"[DComBattleSimulator] Opponent hits: 0b{opponent_hits:05b} ({opponent_hits})")
        
        # Convert to bit arrays (bit 0 = turn 1, bit 1 = turn 2, etc - read right to left)
        player_hit_bits = [(player_hits >> i) & 1 for i in range(5)]
        opponent_hit_bits = [(opponent_hits >> i) & 1 for i in range(5)]
        
        runtime_globals.game_console.log(f"[DComBattleSimulator] Player hit per turn (1-5): {player_hit_bits}")
        runtime_globals.game_console.log(f"[DComBattleSimulator] Opponent hit per turn (1-5): {opponent_hit_bits}")
        
        # Extract level and mini_game from Packet 1 for both sides
        # Packet 1: Order(1) Level(4) Sick(1) Attack(2) Version(4) EOL(4)
        player_pkt1 = player_packets[0]
        opponent_pkt1 = opponent_packets[0]
        
        player_level = (player_pkt1[0] >> 3) & 0xF
        player_mini_game = player_pkt1[0] & 0x3  # Attack quality 0-3
        opponent_level = (opponent_pkt1[0] >> 3) & 0xF
        opponent_mini_game = opponent_pkt1[0] & 0x3  # Attack quality 0-3
        
        # DMX level field is 0-indexed (0=Lvl.1, 6=Lvl.7, etc.), add 1 for table lookup
        # Ensure level is in valid range (1-10) after adjustment
        player_level = max(1, min(10, player_level + 1))
        opponent_level = max(1, min(10, opponent_level + 1))
        
        runtime_globals.game_console.log(f"[DComBattleSimulator] Player: level={player_level}, mini_game={player_mini_game}")
        runtime_globals.game_console.log(f"[DComBattleSimulator] Opponent: level={opponent_level}, mini_game={opponent_mini_game}")
        
        # Get attack patterns based on level and minigame result
        # Pattern values: 1=SINGLE_WEAK, 2=SINGLE_STRONG, 3=DOUBLE_WEAK, 4=DOUBLE_STRONG, 5=CRITICAL
        # Pattern value is the base damage (1-5)
        # The FORMAT, not the wire: PENZ rides the DMX layout but reads the
        # level->pattern table a row lower (battle_utils.PATTERN_LEVEL_OFFSET).
        # Stage matters on both tiered wires -- it is the FIRST thing the
        # row is chosen by, and each line reads its own table.
        # The two sides are on different stage scales: ours came from
        # pet_to_digimon and still carries the wire's numbering, while
        # parse_opponent already put the toy's back on Omnipet's. The DMX
        # picks its row from the stage, so this is not cosmetic.
        player_pattern = get_attack_pattern(
            player_level, player_mini_game, self.battle_format,
            stage=protocol_constants.stage_from_wire(
                self.battle_format, player_packets[1][0] >> 5))
        opponent_pattern = get_attack_pattern(opponent_level, opponent_mini_game,
                                              self.battle_format,
                                              stage=getattr(opponent, 'stage', None))
        
        runtime_globals.game_console.log(f"[DComBattleSimulator] Player attack pattern: {player_pattern}")
        runtime_globals.game_console.log(f"[DComBattleSimulator] Opponent attack pattern: {opponent_pattern}")
        
        # Calculate attack bonuses from level (cumulative)
        # Level 4: +1 Attack, Level 7: +1 Attack (total possible: +2)
        player_attack_bonus = (1 if player_level >= 4 else 0) + (1 if player_level >= 7 else 0)
        opponent_attack_bonus = (1 if opponent_level >= 4 else 0) + (1 if opponent_level >= 7 else 0)
        
        runtime_globals.game_console.log(f"[DComBattleSimulator] Attack bonus - Player: {player_attack_bonus}, Opponent: {opponent_attack_bonus}")
        
        # Get buff values from Packet 5: COU(2) Buff(2) Power(8) EOL(4)
        player_pkt5 = player_packets[4]
        opponent_pkt5 = opponent_packets[4]
        player_buff = (player_pkt5[0] >> 4) & 0x3
        opponent_buff = (opponent_pkt5[0] >> 4) & 0x3
        
        runtime_globals.game_console.log(f"[DComBattleSimulator] Player buff: {player_buff}, Opponent buff: {opponent_buff}")
        
        # Get initial HP from packet 4 for both sides
        # Packet 4: COU(2) HP(5) Shot_M(5) EOL(4)
        player_pkt4 = player_packets[3]
        opponent_pkt4 = opponent_packets[3]
        player_hp = (player_pkt4[0] >> 1) & 0x1F
        opponent_hp = (opponent_pkt4[0] >> 1) & 0x1F
        
        runtime_globals.game_console.log(f"[DComBattleSimulator] Initial HP - Player: {player_hp}, Opponent: {opponent_hp}")
        
        # Determine attack order from Packet 1
        # Order = 0 means device1/replying (attacks second), Order = 1 means initiating (attacks first)
        player_order = (player_packets[0][0] >> 7) & 1
        opponent_order = (opponent_packets[0][0] >> 7) & 1
        
        runtime_globals.game_console.log(f"[DComBattleSimulator] Order - Player: {player_order}, Opponent: {opponent_order}")
        
        # Order=1 means initiating (attacks first), Order=0 means replying (attacks second)
        opponent_attacks_first = opponent_order == 1
        
        battle_log = []
        
        # DMX has 5 rounds
        for turn in range(5):
            # Get attack type for this turn from patterns (1-5 damage value)
            player_attack_type = player_pattern[turn] if turn < len(player_pattern) else 1
            opponent_attack_type = opponent_pattern[turn] if turn < len(opponent_pattern) else 1
            
            # The pattern value is the attack TYPE, not the damage -- it also
            # picks the projectile sprite and the critical slide-in. For four
            # of the five the two coincide; a CRITICAL costs 7, not 5 (see
            # battle_utils.get_attack_damage). Buff (max 2) and the level's
            # attack bonus ride on top.
            player_damage_value = (get_attack_damage(player_attack_type, self.battle_format)
                                   + min(2, player_buff) + player_attack_bonus)
            opponent_damage_value = (get_attack_damage(opponent_attack_type, self.battle_format)
                                     + min(2, opponent_buff) + opponent_attack_bonus)
            
            if opponent_attacks_first:
                # Opponent attacks first
                opponent_hit = opponent_hit_bits[turn]
                player_damage = opponent_damage_value if opponent_hit else 0
                player_hp = max(0, player_hp - player_damage)
                
                # Player attacks second
                player_hit = player_hit_bits[turn]
                opponent_damage = player_damage_value if player_hit else 0
                opponent_hp = max(0, opponent_hp - opponent_damage)
            else:
                # Player attacks first
                player_hit = player_hit_bits[turn]
                opponent_damage = player_damage_value if player_hit else 0
                opponent_hp = max(0, opponent_hp - opponent_damage)
                
                # Opponent attacks second
                opponent_hit = opponent_hit_bits[turn]
                player_damage = opponent_damage_value if opponent_hit else 0
                player_hp = max(0, player_hp - player_damage)
            
            runtime_globals.game_console.log(f"[DComBattleSimulator] Turn {turn+1}: Player atk_type={player_attack_type} hit={player_hit} dmg={player_damage_value}, Opponent atk_type={opponent_attack_type} hit={opponent_hit} dmg={opponent_damage_value}")
            runtime_globals.game_console.log(f"[DComBattleSimulator] Turn {turn+1} HP: Player {player_hp}, Opponent {opponent_hp}")
            
            # Log the turn (device1=opponent, device2=player for BattleEncounter remapping)
            # Store attack_type in damage field for animation lookup
            turn_log = TurnLog(
                turn=turn + 1,
                device1_status=[DigimonStatus(name=opponent.name, hp=opponent_hp, alive=opponent_hp > 0)],
                device2_status=[DigimonStatus(name=player.name, hp=player_hp, alive=player_hp > 0)],
                attacks=[
                    # `damage` here stores the attack-type id (used by the
                    # encounter to pick the projectile sprite). `critical` is
                    # decided by the BASE attack pattern value (1..5) before
                    # buffs/bonuses, which is what the slide-in trigger needs.
                    AttackLog(turn=turn+1, device="device1", attacker=0, defender=0,
                              hit=bool(opponent_hit), damage=opponent_attack_type,
                              critical=(opponent_pattern[turn] == 5 if turn < len(opponent_pattern) else False),
                              hp_damage=opponent_damage_value),
                    AttackLog(turn=turn+1, device="device2", attacker=0, defender=0,
                              hit=bool(player_hit), damage=player_attack_type,
                              critical=(player_pattern[turn] == 5 if turn < len(player_pattern) else False),
                              hp_damage=player_damage_value)
                ]
            )
            battle_log.append(turn_log)
            
            # End battle if one is defeated
            if player_hp == 0 or opponent_hp == 0:
                runtime_globals.game_console.log(f"[DComBattleSimulator] Battle ended after turn {turn+1}")
                break
        
        runtime_globals.game_console.log(f"[DComBattleSimulator] DMX Battle complete with {len(battle_log)} turns")
        runtime_globals.game_console.log(f"[DComBattleSimulator] Final HP - Player: {player_hp}, Opponent: {opponent_hp}")
        return battle_log
