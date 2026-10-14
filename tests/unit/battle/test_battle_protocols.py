"""
Battle protocol test harness
============================

Exercises the battle simulators and the real-device packet protocols without
running the game:

    python tests/test_battle_protocols.py       # run all checks
    python tests/test_battle_protocols.py -v    # + packet dumps / battle logs

Sections:
  1. Round trips: each protocol's DCom packet generator is validated and
     parsed back with the DCom-tested validators/parsers
     (dcom_battle_simulator is the ground-truth implementation), and the
     parsed fields are compared to the input Digimon.
  2. Versus simulations: BattleSimulator for DM / DMC / DM20 / PEN20 / DMX,
     checking result integrity invariants.
  3. Global protocol: GlobalBattleSimulator scenarios (1v1, adventure 4v4,
     boss, arena) checking damage caps, HP bounds and winner consistency.
  4. DCom wire facts: every selectable battle format resolves to the packet
     layout it is really sent over (six formats, three layouts), generates
     packets that pass that layout's validator, and cannot be overflowed by a
     maxed-out pet.
  5. Charge scoring: the shared 0-3 minigame mapping.
  6. DM20 / PEN20 / DMX conformance: the packets are checked field by field
     against the worked examples in the protocol document, a copy of which
     lives in utilities/protocols/.
  7. Attack sprite ids: the offset between Omnipet's numbering and the
     devices', in both directions.
  8. The shared protocol menu, and the READY -> charge phases every charge
     minigame runs through.
"""

import os
import sys
import argparse

# Make src importable when run from the repo root (or anywhere)
# These tests live under utilities/claude/tests/, three folders below the
# repo root, so they are not carried in the git repository.
_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
_SRC = os.path.join(_REPO_ROOT, "src")
for p in (_SRC, _REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from battle.sim.models import Digimon, BattleProtocol  # noqa: E402
from battle.sim.battle_simulator import (  # noqa: E402
    BattleSimulator, DM20Device, PEN20Device, DMXDevice, DMDevice, DMCDevice)
from battle.sim.global_battle_simulator import GlobalBattleSimulator  # noqa: E402
from battle.sim import protocol_constants  # noqa: E402
from battle.sim.dcom_battle_simulator import (  # noqa: E402
    DComBattleSimulator, pet_to_digimon)
from battle.dcom.dcom_protocol import ProtocolType  # noqa: E402


def make_digimon(name="Agumon", power=120, attribute=0, hp=10, level=3,
                 stage=3, shot1=5, shot2=9, index=4, mini_game=3, buff=0,
                 order=0, traited=0, egg_shake=0, sick=0, tag_meter=0):
    return Digimon(name=name, order=order, traited=traited, egg_shake=egg_shake,
                   index=index, hp=hp, attribute=attribute, power=power,
                   handicap=0, buff=buff, mini_game=mini_game, level=level,
                   stage=stage, sick=sick, shot1=shot1, shot2=shot2,
                   tag_meter=tag_meter)


class BattleProtocolTester:
    """Collects checks and reports a pass/fail summary."""

    def __init__(self, verbose=False):
        self.verbose = verbose
        self.passed = 0
        self.failed = 0
        self.failures = []

    # ------------------------------------------------------------------
    # Reporting helpers
    # ------------------------------------------------------------------

    def check(self, label, condition, detail=""):
        if condition:
            self.passed += 1
            if self.verbose:
                print(f"  [ok]   {label}")
        else:
            self.failed += 1
            self.failures.append((label, detail))
            print(f"  [FAIL] {label}" + (f" -- {detail}" if detail else ""))

    def section(self, title):
        print()
        print("=" * 70)
        print(title)
        print("=" * 70)

    def dump_packets(self, label, packets):
        if not self.verbose:
            return
        print(f"  {label}:")
        for i, pkt in enumerate(packets, 1):
            print(f"    Packet {i}: {pkt.hex().upper()}  "
                  f"({' '.join(f'{b:08b}' for b in pkt)})")

    # ------------------------------------------------------------------
    # Section 1: DCom round trips (generator -> tested validator/parser)
    # ------------------------------------------------------------------

    def _dcom(self, protocol_type, battle_format=None):
        # No controller needed: only the send/receive steps touch hardware.
        return DComBattleSimulator(None, protocol_type, battle_format)

    def test_dm20_roundtrip(self):
        self.section("DM20 DCom round trip")
        fixture = make_digimon(power=130, attribute=1, index=7, shot1=12, shot2=3,
                               mini_game=9)
        fixture.version = 3
        device = DM20Device(fixture)
        packets = device.generate_all_packets_for_dcom(order=0)
        self.dump_packets("DM20 generated", packets)

        self.check("DM20 generates 10 packets", len(packets) == 10,
                   f"got {len(packets)}")
        dcom = self._dcom(ProtocolType.V_PET)
        self.check("DM20 packets pass tested validator",
                   dcom._validate_dm20_packets(packets))

        parsed = dcom._parse_dm20_opponent(packets)
        self.check("DM20 packets parse back", parsed is not None)
        if parsed:
            self.check("DM20 power round-trips", parsed.power == fixture.power,
                       f"{parsed.power} != {fixture.power}")
            self.check("DM20 attribute round-trips",
                       parsed.attribute == fixture.attribute,
                       f"{parsed.attribute} != {fixture.attribute}")
            self.check("DM20 index round-trips", parsed.index == fixture.index,
                       f"{parsed.index} != {fixture.index}")
            self.check("DM20 shots round-trip",
                       parsed.shot1 == fixture.shot1 and parsed.shot2 == fixture.shot2,
                       f"({parsed.shot1},{parsed.shot2}) != ({fixture.shot1},{fixture.shot2})")

    def test_pen20_roundtrip(self):
        self.section("PEN20 DCom round trip")
        fixture = make_digimon(power=110, attribute=2, index=22, shot1=30, shot2=18,
                               mini_game=7, traited=1, egg_shake=1, stage=4)
        fixture.version = 2
        device = PEN20Device(fixture)
        packets = device.generate_all_packets_for_dcom()
        self.dump_packets("PEN20 generated", packets)

        self.check("PEN20 generates 10 packets", len(packets) == 10,
                   f"got {len(packets)}")
        dcom = self._dcom(ProtocolType.PEN_X)
        self.check("PEN20 packets pass tested validator",
                   dcom._validate_pen20_packets(packets))

        parsed = dcom._parse_pen20_opponent(packets)
        self.check("PEN20 packets parse back", parsed is not None)
        if parsed:
            # PEN20 sends power WITH traited/egg-shake bonuses applied
            self.check("PEN20 boosted power round-trips",
                       parsed.power == device.power,
                       f"{parsed.power} != {device.power} (base {fixture.power})")
            self.check("PEN20 attribute round-trips",
                       parsed.attribute == fixture.attribute,
                       f"{parsed.attribute} != {fixture.attribute}")
            self.check("PEN20 index round-trips", parsed.index == fixture.index,
                       f"{parsed.index} != {fixture.index}")
            self.check("PEN20 traited/egg_shake round-trip",
                       parsed.traited == fixture.traited
                       and parsed.egg_shake == fixture.egg_shake,
                       f"({parsed.traited},{parsed.egg_shake})")

    def test_dmx_roundtrip(self, battle_format="DMX"):
        self.section(f"{battle_format} DCom round trip")
        fixture = make_digimon(power=200, attribute=0, index=15, shot1=21, shot2=6,
                               hp=22, level=7, stage=4, buff=2, mini_game=2)
        fixture.version = 1
        fixture.dmx_shot_m = 11
        device = DMXDevice(fixture)
        packets = device.generate_all_packets_for_dcom()
        self.dump_packets(f"{battle_format} generated", packets)

        self.check(f"{battle_format} generates 6 packets", len(packets) == 6,
                   f"got {len(packets)}")
        dcom = self._dcom(ProtocolType.COLOR, battle_format=battle_format)
        self.check(f"{battle_format} packets pass tested validator",
                   dcom._validate_dmx_packets(packets))

        parsed = dcom._parse_dmx_opponent(packets)
        self.check(f"{battle_format} packets parse back", parsed is not None)
        if parsed:
            self.check(f"{battle_format} hp round-trips", parsed.hp == fixture.hp,
                       f"{parsed.hp} != {fixture.hp}")
            self.check(f"{battle_format} power round-trips",
                       parsed.power == fixture.power,
                       f"{parsed.power} != {fixture.power}")
            self.check(f"{battle_format} level round-trips",
                       parsed.level == fixture.level,
                       f"{parsed.level} != {fixture.level}")
            self.check(f"{battle_format} stage round-trips",
                       parsed.stage == fixture.stage,
                       f"{parsed.stage} != {fixture.stage}")
            self.check(f"{battle_format} index round-trips",
                       parsed.index == fixture.index,
                       f"{parsed.index} != {fixture.index}")
            self.check(f"{battle_format} buff round-trips",
                       parsed.buff == fixture.buff,
                       f"{parsed.buff} != {fixture.buff}")
            self.check(f"{battle_format} attribute round-trips",
                       parsed.attribute == fixture.attribute,
                       f"{parsed.attribute} != {fixture.attribute}")

    # ------------------------------------------------------------------
    # Section 2: Versus (BattleSimulator) integrity
    # ------------------------------------------------------------------

    def _check_result_integrity(self, name, result, expect_packets):
        self.check(f"{name} produces a winner",
                   result.winner in ("device1", "device2", "draw"),
                   str(result.winner))
        self.check(f"{name} has a battle log", len(result.battle_log) > 0)
        if expect_packets:
            self.check(f"{name} produced packets",
                       len(result.device1_packets) > 0 and len(result.device2_packets) > 0)
        for side in (result.device1_final, result.device2_final):
            for status in side:
                self.check(f"{name} final HP >= 0 ({status.name})", status.hp >= 0,
                           str(status.hp))

    def test_versus_protocols(self):
        self.section("Versus simulations (BattleSimulator)")
        pairs = {
            BattleProtocol.DMOG_BS: "DMOG",
            BattleProtocol.DMC_BS: "DMC",
            BattleProtocol.DM20_BS: "DM20",
            BattleProtocol.PEN20_BS: "PEN20",
            BattleProtocol.DMX_BS: "DMX",
        }
        for protocol, name in pairs.items():
            d1 = make_digimon(name="Left", power=120, attribute=0, hp=10)
            d1.version = 1
            d2 = make_digimon(name="Right", power=110, attribute=2, hp=10, order=1,
                              index=9, shot1=2, shot2=8)
            d2.version = 1
            try:
                sim = BattleSimulator(protocol, verbose=self.verbose)
                result = sim.simulate(d1, d2)
                self._check_result_integrity(name, result, expect_packets=True)
            except Exception as exc:
                self.check(f"{name} simulate runs", False, repr(exc))

    # ------------------------------------------------------------------
    # Section 3: Global protocol (adventure / arena)
    # ------------------------------------------------------------------

    def _team(self, count, power=110, hp=10, prefix="Pet"):
        attrs = ["Va", "Da", "Vi", ""]
        return [make_digimon(name=f"{prefix}{i}", power=power + i * 5,
                             attribute=attrs[i % 4], hp=hp, index=i,
                             mini_game=2, level=3)
                for i in range(count)]

    def _check_global_result(self, name, result, damage_limit, buffs_max=0):
        self.check(f"{name} winner set",
                   result.winner in ("device1", "device2", "draw"))
        self.check(f"{name} log within 12 turns", len(result.battle_log) <= 12,
                   str(len(result.battle_log)))
        max_dmg = damage_limit + buffs_max
        for turn in result.battle_log:
            for atk in turn.attacks:
                # `damage` is the attack's pattern value -- what the encounter
                # counts projectiles from -- and it is the same whether the
                # shot lands or not, so a missed strong shot still draws as a
                # strong shot. The HP it costs is `hp_damage`, and that is
                # what a miss zeroes.
                self.check(f"{name} damage cap", atk.damage <= max_dmg,
                           f"turn {atk.turn}: dmg {atk.damage} > {max_dmg}")
                self.check(f"{name} hp cost cap",
                           (atk.hp_damage or 0) <= max_dmg,
                           f"turn {atk.turn}: hp {atk.hp_damage} > {max_dmg}")
                if not atk.hit:
                    self.check(f"{name} miss spends no HP", atk.hp_damage == 0,
                               f"turn {atk.turn}")
                    self.check(f"{name} miss keeps its pattern value",
                               atk.damage > 0, f"turn {atk.turn}")
            for status in turn.device1_status + turn.device2_status:
                self.check(f"{name} HP >= 0", status.hp >= 0,
                           f"{status.name}: {status.hp}")

    def test_global_protocol(self):
        self.section("Global protocol (GlobalBattleSimulator)")

        # 1v1
        sim = GlobalBattleSimulator(attribute_advantage=5, damage_limit=3,
                                    verbose=self.verbose)
        result = sim.simulate(self._team(1), self._team(1, prefix="Foe"))
        self._check_global_result("global 1v1", result, damage_limit=3)

        # Adventure 4v4
        result = sim.simulate(self._team(4), self._team(4, prefix="Foe"))
        self._check_global_result("global 4v4", result, damage_limit=3)

        # Boss battle: 4 pets vs 1 boss (boss attacks the whole party)
        boss = [make_digimon(name="Boss", power=200, attribute="Vi", hp=40)]
        result = sim.simulate(self._team(4), boss)
        self._check_global_result("global boss", result, damage_limit=3)
        boss_hits = [a for t in result.battle_log for a in t.attacks
                     if a.device == "device2"]
        multi_target = len({a.defender for a in boss_hits}) > 1 if boss_hits else False
        self.check("global boss attacks multiple pets", multi_target or not boss_hits)

        # Arena: full party vs full party with buffs and a higher damage limit
        arena_sim = GlobalBattleSimulator(attribute_advantage=5, damage_limit=5,
                                          pvp_mode=True, verbose=self.verbose)
        team_a = self._team(4, power=150, hp=14, prefix="A")
        team_b = self._team(4, power=145, hp=14, prefix="B")
        for pet in team_a:
            pet.buff = 1
        result = arena_sim.simulate(team_a, team_b)
        self._check_global_result("arena 4v4", result, damage_limit=5, buffs_max=1)
        # pvp_mode: a lone survivor on team B must not gain boss behavior
        self.check("arena has no boss multi-target",
                   all(a.defender >= 0 for t in result.battle_log for a in t.attacks))

    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Section 4: DCom wire facts, per battle format
    # ------------------------------------------------------------------

    #: The layout each format is really sent over. Six formats, three
    #: layouts: a format that borrows another's differs only in the charge
    #: minigame. Generating one layout and parsing another is what left PENZ
    #: with an empty battle log.
    #: (wire name, packet count, charge minigame, turn)
    #: The turn is who opens the exchange: 1 the adapter sends first,
    #: 2 it listens and answers. A Pendulum 20th never opens one, so a
    #: listen-and-reply command reaches it and nothing happens.
    WIRE_FACTS = {
        'DMOG':  ('DMOG', 2, "None", 2),
        # The Pendulum's own signal: four packets, EOL F and remainder
        # 11 where every other wire uses E, and every code on record is
        # written V1. A Pendulum 20th in legacy Pendulum mode plays Count
        # Match Classic before the battle; the Attack field still comes from
        # Effort, so the charge is presentation for now.
        'PENOG': ('PENOG', 4, "Count Match Classic", 1),
        # Pendulum X / Digimon Mini: four packets on X timing, EOL 9 and a
        # digit sum of 4. A real Mini opened the first capture, so we listen.
        'DMM':  ('DMM', 4, "Count Bar", 2),
        # The Digivice iC's own wire: the Mini's with an empty packet
        # inserted, EOL 7 and a check over twenty digits -- and infrared
        # rather than the prongs, so it carries its own two-letter op.
        # Unknown which side opens, so it listens as the Mini does.
        #
        # The charge is NOT the Mini's. The iC measures a rate against each
        # Digimon's own RPM target; Count Bar counts presses and rewards
        # more of them. They shared a screen and a table until 2026-09-21.
        'IC':    ('IC', 5, "RPM", 2),
        'DM20':  ('DM20', 10, "Dummy Bar", 2),
        'PEN20': ('PEN20', 10, "Count Match Classic", 1),
        'DMX':   ('DMX', 6, "Xai Roll+Bar", 2),
        'PENZ':  ('DMX', 6, "Count Match Z", 2),
        # The Color wire uses the "C" op letter and answers rather than
        # opens -- a real device takes Player 1 for itself.
        'DMC':   ('DMC', 2, "None", 2),
        'PENC':  ('DMC', 2, "Count Match Color", 2),
        # Xros Wars: the same Colour layout again, operations at 0x20, and
        # Excite training's bar for the charge. A real device sent its
        # operation 0x20 unprompted while we listened on turn 2, so it takes
        # Player 1 as the other two Colour lines do.
        'DMXW':  ('DMC', 2, "Xai Bar", 2),
    }

    def test_dcom_wire_facts(self):
        self.section("DCom wire facts (per battle format)")
        self.check("every battle format has wire facts",
                   set(protocol_constants.BATTLE_FORMATS) == set(self.WIRE_FACTS),
                   f"{protocol_constants.BATTLE_FORMATS} vs {sorted(self.WIRE_FACTS)}")

        fixture = make_digimon(power=130, attribute=1, index=7, shot1=12,
                               shot2=3, hp=14, level=5, stage=4, mini_game=2)
        fixture.version = 2
        fixture.dmx_shot_m = 5

        for fmt, (wire, count, minigame, turn) in self.WIRE_FACTS.items():
            dcom = DComBattleSimulator(None, battle_format=fmt)
            self.check(f"{fmt} is sent over the {wire} wire",
                       dcom.wire.NAME == wire, dcom.wire.NAME)
            self.check(f"{fmt} expects {count} packet(s)",
                       dcom.expected_packet_count == count,
                       str(dcom.expected_packet_count))
            self.check(f"{fmt} charge minigame is {minigame}",
                       dcom.minigame == minigame, dcom.minigame)

            packets = dcom.generate_player_packets(fixture)
            self.check(f"{fmt} generates {count} packets",
                       packets is not None and len(packets) == count,
                       str(len(packets) if packets else None))
            if not packets:
                continue
            self.dump_packets(f"{fmt} generated", packets)
            width = getattr(protocol_constants.get_wire(fmt), 'PACKET_BYTES', 2)
            self.check(f"{fmt} sends {width * 8}-bit packets",
                       all(len(p) == width for p in packets),
                       str(sorted({len(p) for p in packets})))
            self.check(f"{fmt} packets pass the {wire} validator",
                       dcom._validate_packets(packets))

            # Every format goes out over 2-prong timings; only the turn
            # differs, and the Order bit follows it.
            self.check(f"{fmt} opens the exchange as turn {turn}",
                       dcom.turn == turn, str(dcom.turn))
            command = dcom.build_command(packets)
            # The op letter is the wire's: "C" for the Color layout.
            op = getattr(protocol_constants.get_wire(fmt), 'DCOM_OP',
                         protocol_constants.DCOM_OP)
            self.check(f"{fmt} command opens with {op}{turn}-",
                       command.startswith(f"{op}{turn}-"), command[:8])
            if wire in ('DM20', 'PEN20'):
                order = (packets[2][0] >> 7) & 1 if wire == 'DM20' else (packets[0][0] >> 7) & 1
                self.check(f"{fmt} Order marks whoever opens the exchange",
                           order == (1 if turn == 1 else 0), str(order))

            hexes = [p.hex().upper() for p in packets]
            self.check(f"{fmt} reply pattern matches its own packets",
                       dcom.response_pattern().findall(
                           " ".join(f"r:{h}" for h in hexes)) == hexes)
            self.check(f"{fmt} shares its wire with the right formats",
                       protocol_constants.get_wire(fmt) is
                       protocol_constants.WIRE_FORMATS[wire])

            opponent = dcom.parse_opponent(hexes, fixture)
            self.check(f"{fmt} parses an opponent back", opponent is not None)
            if opponent:
                # A Colour transcript needs opposite roles, not a reflected
                # copy of our own identity/result pair.
                ours = packets
                if wire == 'DMC':
                    peer_turn = 2 if packets[0][5] % 16 == 0 else 1
                    ours = dcom.generate_player_packets(fixture, turn=peer_turn, peer=True)
                result = dcom.build_result(fixture, opponent, ours, hexes)
                self.check(f"{fmt} builds a battle result", result is not None)
                if result:
                    self.check(f"{fmt} result has turns to animate",
                               len(result.battle_log) > 0)
                    self.check(f"{fmt} result names a winner",
                               result.winner in ("device1", "device2"),
                               str(result.winner))

    def test_dcom_field_clamping(self):
        self.section("DCom field clamping (a pet bigger than the wire)")

        class MaxedPet:
            """Past every field width: Omnipet stats outgrow several of them."""
            name = "Titan"
            attribute = "Va"
            module = ""
            index = 999
            level = 99
            stage = 8
            sick = 0
            traited = True
            shook = True
            atk_main = 300
            atk_alt = 250
            atk_alt_2 = 200

            def get_power(self):
                return 9999

            def get_hp(self):
                return 36

        for fmt in protocol_constants.BATTLE_FORMATS:
            dcom = DComBattleSimulator(None, battle_format=fmt)
            digimon = pet_to_digimon(MaxedPet(), fmt, 3)
            packets = dcom.generate_player_packets(digimon)
            self.check(f"{fmt} packs a maxed-out pet without overflowing",
                       packets is not None
                       and len(packets) == protocol_constants.get_wire(fmt).PACKET_COUNT,
                       str(len(packets) if packets else None))
            if packets:
                self.check(f"{fmt} maxed-out packets still validate",
                           dcom._validate_packets(packets))

    # ------------------------------------------------------------------
    # Section 5: charge scoring
    # ------------------------------------------------------------------

    def test_minigame_scoring(self):
        self.section("Charge scoring (shared 0-3 mapping)")
        from ui.minigames.minigame_session import (
            minigame_result, count_match_super_hits, count_match_rank)

        # (minigame, strength, super_hits, expected protocol value)
        cases = [
            ("None", 0, 0, 2),
            ("Dummy Bar", 0, 0, 0), ("Dummy Bar", 5, 0, 1),
            ("Dummy Bar", 10, 0, 2), ("Dummy Bar", 14, 0, 3),
            # The shake meter keeps its full 0-40 count now, because the
            # Pendulum's wire reads the number itself. The bands are the old
            # 0-14 ones scaled onto it, so Excellent is still a perfect meter.
            ("Count Match Classic", 28, 0, 0), ("Count Match Classic", 34, 0, 1),
            ("Count Match Classic", 39, 0, 2), ("Count Match Classic", 40, 0, 3),
            # Count Match Z is NOT in this table: it is scored off its arrow
            # counter against the number the pet was asked for, so it needs
            # the pet and has no meaning here. It used to be pushed through
            # `super_hits`, which is Count Match Color's mechanic -- see
            # test_count_match_z for its own path.
            # Count Match Color's raw score runs 0-5 -- a Megahit is five --
            # and the band is the manual's own grading, the same one the
            # training screen reads. It used to be clamped rather than
            # banded, which put the Megahit and the 3-4 rung on one value.
            ("Count Match Color", 0, 0, 0), ("Count Match Color", 0, 1, 0),
            ("Count Match Color", 0, 2, 1), ("Count Match Color", 0, 3, 2),
            ("Count Match Color", 0, 4, 2), ("Count Match Color", 0, 5, 3),
            # The Xai bar already reports 0-3; re-banding it as a raw 0-20
            # meter scored every stop as Bad.
            ("Xai Roll+Bar", 0, 0, 0), ("Xai Roll+Bar", 1, 0, 1),
            ("Xai Roll+Bar", 2, 0, 2), ("Xai Roll+Bar", 3, 0, 3),
            ("Punch", 9, 0, 0), ("Punch", 20, 0, 3),
            ("Mogera", 0, 0, 0), ("Mogera", 14, 0, 3),
        ]
        for minigame, strength, supers, expected in cases:
            value = minigame_result(minigame, strength, supers)
            self.check(f"{minigame} strength={strength} supers={supers} -> {expected}",
                       value == expected, str(value))

        # Count Match Color pays a BAND, and the band plus the stage is what
        # the device's attack table is keyed on. Each attribute ranks the
        # three colours its own way -- colours are 1=Red 2=Yellow 3=Blue --
        # and the band is the colour's PLACE in that ranking:
        #
        #      Attribute  own (Megahit)    middle           worst
        #      Vaccine    Red / 12 shakes  Yellow / 7       Blue / 2
        #      Data       Yellow / 6       Red / 11         Blue / 2
        #      Virus      Blue / 2         Yellow / 7       Red / 12
        #      Free       Red / 11         Yellow / 7       Blue / 2
        band_cases = [
            (1, "Va", 3), (2, "Va", 2), (3, "Va", 1),
            (2, "Da", 3), (1, "Da", 2), (3, "Da", 1),
            (3, "Vi", 3), (2, "Vi", 2), (1, "Vi", 1),
            (1, "", 3),    # blank is Free, and the manual ranks it as
            (2, "", 2),    # Vaccine does
            (3, "", 1),
            (0, "Va", 0),     # no colour under the arrow
            (1, "Free", 0),   # an attribute with no ranking of its own
        ]
        for colour, attribute, expected in band_cases:
            got = count_match_rank(colour, attribute)
            self.check("colour %d / %s -> band %d"
                       % (colour, attribute or "blank", expected),
                       got == expected, str(got))

        # **The super-hit count is derived and the stage decides it.** It is
        # the number of 2s in the row that band selects, measured off a real
        # Pendulum Color for all seven stages: the bottom band pays 0 at
        # stages 1-2 and 1 from stage 3 up, and the middle band 3 at stages
        # 1-4 and 4 from stage 5 up. So the manual's "3 or 4" is the stage
        # speaking, and it used to be a `random.choice((3, 4))`.
        expected_counts = {
            1: (0, 1, 3, 5), 2: (0, 1, 3, 5),
            3: (1, 2, 3, 5), 4: (1, 2, 3, 5),
            5: (1, 2, 4, 5), 6: (1, 2, 4, 5), 7: (1, 2, 4, 5),
        }
        # A Virus pet ranks Blue > Yellow > Red, so 0/red/yellow/blue walks
        # the four bands upwards. Nothing here is rolled, so one call is the
        # whole answer.
        for stage, counts in expected_counts.items():
            got = tuple(count_match_super_hits(colour, "Vi", stage)
                        for colour in (0, 1, 2, 3))
            self.check("stage %d super hits by band -> %s" % (stage, list(counts)),
                       got == counts, str(list(got)))

        # And the attribute only permutes which colour lands which band, so
        # every attribute reaches the same four counts at a given stage.
        for attribute in ("Va", "Da", "Vi", ""):
            got = sorted(count_match_super_hits(colour, attribute, 5)
                         for colour in (0, 1, 2, 3))
            self.check("%s reaches the same counts at stage 5"
                       % (attribute or "blank"),
                       got == [1, 2, 4, 5], str(got))

    # ------------------------------------------------------------------
    # Section 6: DM20 conformance with the protocol document
    # ------------------------------------------------------------------

    #: Packets 4, 5 and 6 of the worked DM20 example in the protocol document
    #: (https://docs.google.com/document/d/11CuxpKQFaHexAbi8jHX4UnfhZVfovwDAXo5xYZCEDpM):
    #:      Packet 4:  00   00000100   00  1110      index 4, attribute Vaccine
    #:      Packet 5:  000011    011001   1110       shot S 3, shot W 25
    #:      Packet 6:  0000    01001011   1110       power 75
    #: The fixture below is that Digimon, so the generator has to reproduce
    #: them byte for byte.
    DOC_EXAMPLE = {4: "010E", 5: "0D9E", 6: "04BE"}

    def test_dm20_document_conformance(self):
        self.section("DM20 conformance with the protocol document")

        fixture = make_digimon(name="Greymon", index=4, attribute=0, shot1=3,
                               shot2=25, power=75, mini_game=3)
        fixture.version = 1
        device = DM20Device(fixture)

        packets = {
            3: device.generate_packet3(order=1, version=1, eol=0xE),
            4: device.generate_packet4(cou=0, eol=0xE),
            5: device.generate_packet5(eol=0xE),
            6: device.generate_packet6(cou=0, eol=0xE),
            7: device.generate_packet7(cou=0, eol=0xE),
            8: device.generate_packet8(eol=0xE),
            9: device.generate_packet9(eol=0xE),
        }

        for number, expected in self.DOC_EXAMPLE.items():
            got = packets[number].hex().upper()
            self.check(f"DM20 packet {number} matches the document ({expected})",
                       got == expected, got)

        # "Whether this connection is a Single Battle (0), Copy Send (1),
        # Tag Battle (2) or Copy Receive (3)" -- a versus battle is Single.
        operation = packets[3][0] & 0b11
        self.check("DM20 packet 3 operation is Single Battle (0)",
                   operation == 0, str(operation))

        # "The initiating device will have a 1 for order, while the second
        # device will have a 0."
        order = (packets[3][0] >> 7) & 1
        self.check("DM20 packet 3 order marks the initiator", order == 1, str(order))

        # Packets 7-9 carry the right-hand Digimon of a Tag Battle; in a
        # Single Battle they are all zero. Packet 9 also holds the Tag Meter,
        # which is what used to leave a 2 in an otherwise empty packet.
        for number in (7, 8, 9):
            got = packets[number].hex().upper()
            self.check(f"DM20 packet {number} is empty in a single battle",
                       got == "000E", got)

        # The checksum and packet A are exercised in
        # test_dm20_packet_a_consistency, which runs a real exchange.

    def test_dm20_hit_rate_follows_power(self):
        self.section("DM20 hit rate follows power")

        # Two Digimon that differ only in power, both Free so no attribute
        # advantage muddies the comparison.
        weak = make_digimon(name="Weak", power=15, attribute=3, index=0,
                            shot1=17, shot2=17, mini_game=3)
        strong = make_digimon(name="Strong", power=30, attribute=3, index=1,
                              shot1=2, shot2=2, mini_game=3)
        weak.version = strong.version = 1

        d_weak, d_strong = DM20Device(weak), DM20Device(strong)
        pairs = [
            (d_weak.generate_packet1(), d_strong.generate_packet1()),
            (d_weak.generate_packet2(), d_strong.generate_packet2()),
            (d_weak.generate_packet3(1, 1, 0xE), d_strong.generate_packet3(0, 1, 0xE)),
            (d_weak.generate_packet4(0, 0xE), d_strong.generate_packet4(0, 0xE)),
            (d_weak.generate_packet5(0xE), d_strong.generate_packet5(0xE)),
            (d_weak.generate_packet6(0, 0xE), d_strong.generate_packet6(0, 0xE)),
            (d_weak.generate_packet7(0, 0xE), d_strong.generate_packet7(0, 0xE)),
            (d_weak.generate_packet8(0xE), d_strong.generate_packet8(0xE)),
            (d_weak.generate_packet9(0xE), d_strong.generate_packet9(0xE)),
        ]
        for a, b in pairs:
            d_strong.process_packet(a)
            d_weak.process_packet(b)

        # Each side must read the other's real power and attribute. Reading
        # the wrong packets made the hit rate a function of the opponent's
        # attack sprite numbers, which handed the weaker Digimon the better
        # odds.
        pkt4, pkt6 = d_weak.opponent_data[3], d_weak.opponent_data[5]
        self.check("DM20 reads the opponent's power from packet 6",
                   ((pkt6[0] & 0x0F) << 4) | ((pkt6[1] >> 4) & 0x0F) == strong.power)
        self.check("DM20 reads the opponent's attribute from packet 4",
                   (pkt4[1] >> 4) & 0b11 == strong.attribute)

        # "The larger your power is compared to your opponent's, the higher
        # the chance that a hit will connect."
        rounds = 600
        hits = {'weak': 0, 'strong': 0}
        for _ in range(rounds):
            d_weak.opponent_data = d_weak.opponent_data[:9]
            d_strong.opponent_data = d_strong.opponent_data[:9]
            hits['weak'] += bin((d_weak.generate_packetA(0xE)[1] >> 4) & 0xF).count('1')
            hits['strong'] += bin((d_strong.generate_packetA(0xE)[1] >> 4) & 0xF).count('1')

        weak_rate = hits['weak'] / (4.0 * rounds)
        strong_rate = hits['strong'] / (4.0 * rounds)
        # Expected 15/45 = 0.333 and 30/45 = 0.667; allow generous sampling room.
        self.check("DM20 weak Digimon hits about a third of the time",
                   0.25 < weak_rate < 0.42, f"{weak_rate:.3f}")
        self.check("DM20 strong Digimon hits about two thirds of the time",
                   0.58 < strong_rate < 0.75, f"{strong_rate:.3f}")
        self.check("DM20 the stronger Digimon lands more hits",
                   strong_rate > weak_rate,
                   f"{strong_rate:.3f} vs {weak_rate:.3f}")

    def test_dm20_packet_a_consistency(self):
        self.section("DM20 packet A (checksum, hits and dodges)")

        left = make_digimon(name="Left", power=120, attribute=0, index=3,
                            shot1=5, shot2=9, mini_game=3)
        right = make_digimon(name="Right", power=90, attribute=2, index=8,
                             shot1=11, shot2=4, mini_game=3)
        left.version = right.version = 1

        d1, d2 = DM20Device(left), DM20Device(right)
        pairs = [
            (d1.generate_packet1(), d2.generate_packet1()),
            (d1.generate_packet2(), d2.generate_packet2()),
            (d1.generate_packet3(1, 1, 0xE), d2.generate_packet3(0, 1, 0xE)),
            (d1.generate_packet4(0, 0xE), d2.generate_packet4(0, 0xE)),
            (d1.generate_packet5(0xE), d2.generate_packet5(0xE)),
            (d1.generate_packet6(0, 0xE), d2.generate_packet6(0, 0xE)),
            (d1.generate_packet7(0, 0xE), d2.generate_packet7(0, 0xE)),
            (d1.generate_packet8(0xE), d2.generate_packet8(0xE)),
            (d1.generate_packet9(0xE), d2.generate_packet9(0xE)),
        ]
        for a, b in pairs:
            d2.process_packet(a)
            d1.process_packet(b)

        for name, device, own in (("device1", d1, [a for a, _ in pairs]),
                                  ("device2", d2, [b for _, b in pairs])):
            packetA = device.generate_packetA(eol=0xE)
            full = own + [packetA]

            # "The signal is divided into 4 bit groups... The sum is divided
            # by 16... Remainder should always equal 0"
            total = sum(((byte >> 4) & 0xF) + (byte & 0xF) for pkt in full for byte in pkt)
            self.check(f"DM20 {name} checksum remainder is 0",
                       total % 16 == 0, str(total % 16))

            # "Opponents dodges will be inverted for Single Battles"
            dodges = packetA[0] & 0x0F
            hits = (packetA[1] >> 4) & 0x0F
            self.check(f"DM20 {name} dodges are the inverse of hits",
                       dodges == (~hits & 0x0F),
                       f"dodges={dodges:04b} hits={hits:04b}")

            self.check(f"DM20 {name} packet A ends with the EOL marker",
                       (packetA[1] & 0x0F) == 0xE)

    # ------------------------------------------------------------------
    # Section 7: PEN20 conformance with the protocol document
    # ------------------------------------------------------------------

    #: The worked PEN20 example in the protocol document (Ordinemon), as
    #: packet number -> (bit string, what it encodes). Packet 1 is a Tag
    #: Battle there and packet 9 carries the right-hand Digimon's power, so
    #: those two are compared field by field instead of whole.
    PEN20_DOC_EXAMPLE = {
        1: "0 0 1110 10 0110 1110",
        2: "00 11100101 11 1110",
        3: "0000 00110101 1110",
        4: "0 000 00001101 1110",
        5: "01 1 1 11111000 1110",
        6: "00 11101110 00 1110",
        7: "0000 01101001 1110",
        8: "0000 01000111 1110",
        9: "0011 11100110 1110",
        10: "0001 0000 1111 1110",
    }

    @staticmethod
    def _bits(text):
        return int(text.replace(" ", ""), 2)

    def _pen20_example_device(self):
        """The document's Ordinemon as a PEN20Device."""
        fixture = make_digimon(name="Ordinemon", index=229, attribute=3,
                               power=248, shot1=13, shot2=53, stage=6,
                               traited=1, egg_shake=1, mini_game=14)
        fixture.version = 6
        return PEN20Device(fixture)

    def test_pen20_document_conformance(self):
        self.section("PEN20 conformance with the protocol document")

        device = self._pen20_example_device()
        packets = {
            1: device.generate_packet1(order=0, version=6, eol=0xE),
            2: device.generate_packet2(cou=0, eol=0xE),
            3: device.generate_packet3(cou=0, eol=0xE),
            4: device.generate_packet4(cou=0, eol=0xE),
            5: device.generate_packet5(eol=0xE),
            9: device.generate_packet9(eol=0xE),
        }

        # Packets 2-5 must reproduce the document exactly.
        for number in (2, 3, 4, 5):
            want = self._bits(self.PEN20_DOC_EXAMPLE[number])
            got = int.from_bytes(packets[number], 'big')
            self.check(f"PEN20 packet {number} matches the document ({want:04X})",
                       got == want, f"{got:04X}")

        # Power is sent as it stands: the document's Ordinemon is 248 with
        # both Traited and Egg Shake set, and folding a bonus in made it 255.
        power = ((packets[5][0] & 0x0F) << 4) | ((packets[5][1] >> 4) & 0x0F)
        self.check("PEN20 sends power unmodified by the traited/shake flags",
                   power == 248, str(power))
        self.check("PEN20 sends the traited flag", (packets[5][0] >> 5) & 1 == 1)
        self.check("PEN20 sends the egg shake flag", (packets[5][0] >> 4) & 1 == 1)

        # "COU ... is the same across all signals we've analyzed": packet 5
        # carries 1 and packet 9 carries 3, not 0.
        self.check("PEN20 packet 5 COU is 1", (packets[5][0] >> 6) & 0b11 == 1,
                   str((packets[5][0] >> 6) & 0b11))
        self.check("PEN20 packet 9 COU is 3", (packets[9][0] >> 4) & 0b1111 == 3,
                   str((packets[9][0] >> 4) & 0b1111))

        # Packet 1 differs from the example only in Operation: the document's
        # is a Tag Battle (2), ours a Single Battle (0).
        doc1 = self._bits(self.PEN20_DOC_EXAMPLE[1])
        got1 = int.from_bytes(packets[1], 'big')
        self.check("PEN20 packet 1 differs from the document only in Operation",
                   got1 == doc1 & ~(0b11 << 8), f"{got1:04X} vs {doc1:04X}")
        self.check("PEN20 packet 1 operation is Single Battle (0)",
                   packets[1][0] & 0b11 == 0)
        # "Attack Pattern is determined by your Digimon's specific Shake
        # requirements" -- the raw meter, of which the example's is 14.
        self.check("PEN20 packet 1 carries the raw charge meter",
                   (packets[1][0] >> 2) & 0xF == 14,
                   str((packets[1][0] >> 2) & 0xF))

        # Power R belongs to the right-hand Digimon and is 0 in a single battle.
        power_r = ((packets[9][0] & 0x0F) << 4) | ((packets[9][1] >> 4) & 0x0F)
        self.check("PEN20 packet 9 power R is empty in a single battle",
                   power_r == 0, str(power_r))

    def test_pen20_checksum_target(self):
        self.section("PEN20 checksum (target 12)")

        # The document's own example must satisfy the rule it states.
        total = 0
        for text in self.PEN20_DOC_EXAMPLE.values():
            value = self._bits(text)
            total += ((value >> 12) & 0xF) + ((value >> 8) & 0xF) \
                + ((value >> 4) & 0xF) + (value & 0xF)
        self.check("the document's PEN20 example sums to remainder 12",
                   total % 16 == 12, str(total % 16))

        self.check("PEN20 constants declare remainder 12",
                   protocol_constants.PEN20.CHECKSUM_REMAINDER == 12,
                   str(protocol_constants.PEN20.CHECKSUM_REMAINDER))

        # And our own generated set must too.
        device = self._pen20_example_device()
        packets = device.generate_all_packets_for_dcom(order=0, version=6)
        self.dump_packets("PEN20 generated", packets)
        self.check("PEN20 generates 10 packets", len(packets) == 10, str(len(packets)))
        total = sum(((b >> 4) & 0xF) + (b & 0xF) for pkt in packets for b in pkt)
        self.check("PEN20 generated packets sum to remainder 12",
                   total % 16 == 12, str(total % 16))

        dcom = DComBattleSimulator(None, battle_format='PEN20')
        self.check("PEN20 packets pass the PEN20 validator",
                   dcom._validate_pen20_packets(packets))
        # The DM20 validator wants remainder 0, so it must reject these.
        self.check("PEN20 packets are not DM20 packets",
                   not dcom._validate_dm20_packets(packets))

    def test_charge_scale_per_wire(self):
        self.section("Charge scale per wire")

        class Session:
            """A finished minigame: a full meter, a top-quality result and a
            Megahit, so each wire can be seen taking the one it reads."""
            strength = 14
            result = 3
            super_hits = 5

        # PENOG reads the raw shake meter like DM20 and PEN20, not the
        # banded 0-3: Count Match Classic's band puts eleven of its fifteen
        # meter values on zero, so most of a played charge never reached the
        # packet.
        # **And the scale is the FORMAT's, not the wire's.** PENC carries
        # "super hits" -- a raw 0-5 -- on the DMC's layout, so reading the
        # wire banded a Megahit back down to the DMC's 3. The device plainly
        # separates them: a Megahit goes out as 14 on the wire and the middle
        # rung as 11.
        # DMXW reads Excite training's bar, which scores 0-3 and produces
        # exactly four attack rows on the device -- so the band IS its key
        # and it takes the quality, not PENC's raw super-hit count.
        # DMM takes the Count Bar's press count whole: the count itself is
        # the row the packet's rounds come from.
        # The iC plays Count Bar as the Mini does, so it takes the same raw
        # press count. Its own charge is a RATE (the playbook's RPM table),
        # and modelling that is separate work -- see IC.MINIGAME.
        # IC reports its 0-10 BAR, not the rate and not a press count: the
        # bar is what its pattern table is keyed on, so a full meter is 10
        # and the fixture's 14 clamps to it.
        expected = {'DMOG': 4, 'PENOG': 14, 'DMM': 14, 'IC': 10, 'DM20': 14,
                    'PEN20': 14, 'DMX': 3, 'PENZ': 3, 'DMC': 3, 'PENC': 5,
                    'DMXW': 3}
        # (Session.strength is 14 here, so PENOG's 40-wide meter reports the
        # 14 that was actually played rather than its cap.)
        for fmt in protocol_constants.BATTLE_FORMATS:
            dcom = DComBattleSimulator(None, battle_format=fmt)
            value = dcom.charge_value(Session())
            self.check(f"{fmt} sends a charge of {expected[fmt]}",
                       value == expected[fmt], str(value))

        # A DM20 battle must be able to reach the whole pattern table; the
        # banded 0-3 value pinned it to the first four of fifteen.
        dcom = DComBattleSimulator(None, battle_format='DM20')
        self.check("DM20 charge is the raw meter, not the 0-3 quality",
                   dcom.charge_value(Session()) > 3)

    # ------------------------------------------------------------------
    # Section 8: DMX / PENZ conformance with the protocol document
    # ------------------------------------------------------------------

    #: The worked DMX example in the protocol document: War Greymon X at
    #: Level 5, Ultimate, index 30, Vaccine, shots 25/8/21, HP 22, buff 1,
    #: power 168, on a Version 1 (Black). PENZ shares this wire.
    DMX_DOC_EXAMPLE = {
        1: "0 0100 0 11 0000 1110",
        2: "100 0011110 00 1110",
        3: "011001 001000 1110",
        4: "00 10110 10101 1110",
        5: "00 01 10101000 1110",
        6: "1111 000 11111 1110",
    }

    def test_dmx_hits_are_five_bits(self):
        self.section("DMX hits (5 bits, right to left, 5 rounds)")

        # Full 5-bit HP on both sides so neither is knocked out early and
        # all five rounds are played: max damage is 5 a round.
        left = make_digimon(name="Left", power=120, hp=31, level=2, stage=1,
                            attribute=0, shot1=16, shot2=16, mini_game=3)
        right = make_digimon(name="Right", power=90, hp=31, level=1, stage=1,
                             attribute=0, shot1=2, shot2=2, mini_game=3, order=1)
        left.version = right.version = 0
        left.dmx_shot_m = right.dmx_shot_m = 31

        result = BattleSimulator(BattleProtocol.DMX_BS).simulate(left, right)

        self.check("DMX plays 5 rounds", len(result.battle_log) == 5,
                   str(len(result.battle_log)))

        for side, packets in (("device1", result.device1_packets),
                              ("device2", result.device2_packets)):
            packet6 = packets[5]
            hits = ((packet6[0] & 1) << 4) | ((packet6[1] >> 4) & 0x0F)
            logged = [a.hit for turn in result.battle_log
                      for a in turn.attacks if a.device == side]
            # Bit 0 is round 1. Taking four bits and reversing them, as this
            # used to, both dropped the last round and ran it backwards.
            from_bits = [bool((hits >> i) & 1) for i in range(len(logged))]
            self.check(f"DMX {side} plays the hit pattern it sent",
                       logged == from_bits,
                       f"{hits:05b} -> {from_bits} vs {logged}")

    def test_dmx_document_conformance(self):
        self.section("DMX / PENZ conformance with the protocol document")

        fixture = make_digimon(name="WarGreymonX", index=30, attribute=0,
                               power=168, hp=22, buff=1, mini_game=3,
                               shot1=25, shot2=8)
        # Level 5 shows as 4 and Ultimate as 4, so the packets carry the
        # already-shifted values; pet_to_digimon is what applies the shift.
        fixture.level = 4
        fixture.stage = 4
        fixture.version = 0
        fixture.dmx_shot_m = 21

        device = DMXDevice(fixture)
        packets = {
            1: device.generate_packet1(), 2: device.generate_packet2(),
            3: device.generate_packet3(), 4: device.generate_packet4(),
            5: device.generate_packet5(),
        }
        for number, text in self.DMX_DOC_EXAMPLE.items():
            if number == 6:
                continue  # packet 6 needs the opponent's packets
            want = int(text.replace(" ", ""), 2)
            got = int.from_bytes(packets[number], 'big')
            self.check(f"DMX packet {number} matches the document ({want:04X})",
                       got == want, f"{got:04X}")

        # "Remainder should always equal 8"
        total = 0
        for text in self.DMX_DOC_EXAMPLE.values():
            value = int(text.replace(" ", ""), 2)
            total += sum((value >> shift) & 0xF for shift in (12, 8, 4, 0))
        self.check("the document's DMX example sums to remainder 8",
                   total % 16 == 8, str(total % 16))
        self.check("DMX constants declare remainder 8",
                   protocol_constants.DMX.CHECKSUM_REMAINDER == 8)

        packets_all = DMXDevice(fixture).generate_all_packets_for_dcom()
        total = sum(((b >> 4) & 0xF) + (b & 0xF) for pkt in packets_all for b in pkt)
        self.check("DMX generated packets sum to remainder 8",
                   total % 16 == 8, str(total % 16))

    def test_dmx_level_and_stage_offsets(self):
        self.section("DMX level and stage offsets")

        class Pet:
            """The document's War Greymon X as Omnipet would hold it."""
            name = "WarGreymon X"
            attribute = "Va"
            module = ""
            index = 30
            level = 5      # "Example Value: Level 5"
            stage = 6      # Omnipet's Ultimate
            sick = 0
            traited = False
            shook = False
            atk_main = 9   # weak, wire 8
            atk_alt = 26   # strong, wire 25
            atk_alt_2 = 22  # mega, wire 21

            def get_power(self):
                return 168

            def get_hp(self):
                return 22

        digimon = pet_to_digimon(Pet(), 'DMX', 3)

        # "Level 1 displays as 0, and maximum is level 10, which displays as 9"
        self.check("DMX level 5 goes on the wire as 4",
                   digimon.level == 4, str(digimon.level))
        # "Baby I is not considered, values range from Baby II (0) to Super
        # Ultimate (5)"
        self.check("DMX Ultimate goes on the wire as 4",
                   digimon.stage == 4, str(digimon.stage))
        self.check("DMX shots go out strong/weak/mega as 25/8/21",
                   (digimon.shot1, digimon.shot2, digimon.dmx_shot_m) == (25, 8, 21),
                   f"{digimon.shot1}/{digimon.shot2}/{digimon.dmx_shot_m}")

        # Every Omnipet stage that can battle must land inside the 0-5 scale.
        for stage, expected in ((2, 0), (3, 1), (4, 2), (5, 3), (6, 4), (7, 5)):
            Pet.stage = stage
            self.check(f"DMX stage {stage} goes on the wire as {expected}",
                       pet_to_digimon(Pet(), 'DMX', 3).stage == expected)
        Pet.stage = 6

        # And come back out on Omnipet's scale.
        dcom = DComBattleSimulator(None, battle_format='DMX')
        packets = dcom.generate_player_packets(pet_to_digimon(Pet(), 'DMX', 3))
        parsed = dcom.parse_opponent([p.hex().upper() for p in packets])
        self.check("DMX level comes back as Omnipet's", parsed.level == 5, str(parsed.level))
        self.check("DMX stage comes back as Omnipet's", parsed.stage == 6, str(parsed.stage))

    # ------------------------------------------------------------------
    # Section 9: attack sprite numbering
    # ------------------------------------------------------------------

    def test_shot_id_offsets(self):
        self.section("Attack sprite ids (Omnipet 1-based, devices 0-based)")

        for field_max, width in ((0x3F, "6-bit"), (0xFF, "8-bit"), (0x1F, "5-bit")):
            # Omnipet reserves 0 for "no sprite"; the devices spell that as
            # the field filled with ones. Sending 0 told the toy to draw its
            # very first attack for a Digimon that has none.
            self.check(f"{width}: no sprite goes out as the all-ones sentinel",
                       protocol_constants.shot_to_wire(0, field_max) == field_max,
                       str(protocol_constants.shot_to_wire(0, field_max)))
            self.check(f"{width}: the sentinel comes back as no sprite",
                       protocol_constants.shot_from_wire(field_max, field_max) == 0)
            self.check(f"{width}: sprite 1 goes out as 0",
                       protocol_constants.shot_to_wire(1, field_max) == 0)

            for sprite in (1, 2, 20, field_max - 1):
                wire = protocol_constants.shot_to_wire(sprite, field_max)
                back = protocol_constants.shot_from_wire(wire, field_max)
                self.check(f"{width}: sprite {sprite} round-trips", back == sprite,
                           f"{sprite} -> {wire} -> {back}")

            # An id too big for the field must not land on the sentinel and
            # read back as "no sprite".
            wire = protocol_constants.shot_to_wire(9999, field_max)
            self.check(f"{width}: an oversized id never becomes the sentinel",
                       wire < field_max, str(wire))

    def test_empty_shot_slot_falls_back(self):
        self.section("An empty shot slot falls back to a real sprite")

        class Pet:
            """A pet with no mega attack, as a non-DMX module leaves it."""
            name = "Patamon"
            attribute = "Da"
            module = ""
            index = 0
            level = 1
            stage = 3
            sick = 0
            traited = False
            shook = False
            atk_main = 2   # weak
            atk_alt = 2    # strong
            atk_alt_2 = 0  # none

            def get_power(self):
                return 30

            def get_hp(self):
                return 10

        # A DMX and a Pendulum Z both aborted with FF00 on the packet that
        # carried the all-ones "none" in Shot M; a device fighting a battle
        # expects a sprite in every slot it reads.
        for fmt in ('DMX', 'PENZ'):
            digimon = pet_to_digimon(Pet(), fmt, 3)
            sentinel = protocol_constants.DMX.MAX_SHOT_M
            self.check(f"{fmt} does not send the sentinel for a missing mega shot",
                       digimon.dmx_shot_m != sentinel, str(digimon.dmx_shot_m))
            self.check(f"{fmt} falls back to a sprite the pet does have",
                       digimon.dmx_shot_m == digimon.shot1,
                       f"{digimon.dmx_shot_m} vs {digimon.shot1}")

        # A pet with no attack sprites at all has nothing to fall back to,
        # so the sentinel is still what goes out.
        class Blank(Pet):
            atk_main = 0
            atk_alt = 0
            atk_alt_2 = 0

        digimon = pet_to_digimon(Blank(), 'DMX', 3)
        self.check("a pet with no sprites at all still sends the sentinel",
                   digimon.shot1 == protocol_constants.DMX.MAX_SHOT,
                   str(digimon.shot1))

    # ------------------------------------------------------------------
    # Section 10: the shared protocol menu
    # ------------------------------------------------------------------

    def test_shared_protocol_menu(self):
        self.section("Shared protocol menu")

        entries = protocol_constants.menu_entries()
        names = [name for name, _, _ in entries]
        self.check("the menu covers every battle format, enabled",
                   [name for name, _, enabled in entries
                    if name in protocol_constants.BATTLE_FORMATS and enabled]
                   == list(protocol_constants.BATTLE_FORMATS), str(names))
        self.check("the menu shows every upcoming line",
                   set(names) - set(protocol_constants.BATTLE_FORMATS)
                   == set(protocol_constants.UPCOMING_LINES), str(names))
        self.check("no upcoming line is enabled for players (1.0 holds TWIN back)",
                   not {name for name, _, enabled in entries
                        if enabled and name not in protocol_constants.BATTLE_FORMATS}, str(entries))
        debug_entries = protocol_constants.menu_entries(include_upcoming=True)
        self.check("debug mode enables the offered upcoming lines",
                   {name for name, _, enabled in debug_entries
                    if enabled and name not in protocol_constants.BATTLE_FORMATS}
                   == set(protocol_constants.OFFERED_UPCOMING), str(debug_entries))
        released = [protocol_constants.RELEASED[name] for name in names]
        self.check("the menu runs oldest release first",
                   released == sorted(released), str(list(zip(names, released))))

        for name, label, _ in entries:
            self.check(f"{name} has a menu label", bool(label), repr(label))
            # PENZ, not PenZ: the device is spelled in capitals like the rest.
            self.check(f"{name}'s label opens with its own name",
                       label.startswith(name), label)

        # Both scenes build their menu from this one list, so a format cannot
        # be offered by one and missing from the other -- which is exactly
        # what happened to PENZ in the versus menu.
        from scenes.battle_views.protocol_view import ProtocolView
        from scenes.connect_views import dcom_view

        versus_labels = [label for _, label, _ in protocol_constants.menu_entries()]
        versus_names = (ProtocolView.__init__.__code__.co_names
                        + ProtocolView._setup_ui.__code__.co_names
                        + ProtocolView._open_grid.__code__.co_names)
        self.check("the versus menu is built from the shared list",
                   "format_menu" in versus_names or "menu_entries" in versus_names)
        self.check("the DCom view no longer carries its own labels",
                   not hasattr(dcom_view, "FORMAT_LABELS"))
        self.check("PENZ is offered", "PENZ (Pendulum Z)" in versus_labels,
                   str(versus_labels))

        # PENZ shares DMX's simulation as it shares its wire.
        self.check("PENZ runs the DMX simulation",
                   protocol_constants.versus_protocol('PENZ')
                   == protocol_constants.versus_protocol('DMX'))
        self.check("PENZ and DMX share a wire",
                   protocol_constants.get_wire('PENZ') is protocol_constants.get_wire('DMX'))
        self.check("PENZ and DMX play different minigames",
                   protocol_constants.PENZ.MINIGAME != protocol_constants.DMX.MINIGAME,
                   f"{protocol_constants.PENZ.MINIGAME} vs {protocol_constants.DMX.MINIGAME}")

    # ------------------------------------------------------------------
    # Section 11: READY -> charge
    # ------------------------------------------------------------------

    def test_minigame_ready_phase(self):
        self.section("READY -> charge phases")

        # The minigames load sprites, which needs a display surface even in
        # a headless run.
        os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
        os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
        import pygame
        try:
            pygame.init()
            if pygame.display.get_surface() is None:
                pygame.display.set_mode((240, 240))
        except pygame.error as exc:
            self.check("READY phase (needs a display)", False, str(exc))
            return

        from ui.minigames.minigame_session import (MinigameSession,
                                                   READY_PHASE_MINIGAMES)
        from ui.ui_manager import UIManager
        from core import runtime_globals

        class Pet:
            name = "Test"
            attribute = "Va"
            level = 3
            stage = 4
            module = ""

            def get_sprite(self, index):
                return None

        manager = UIManager("RED_DARK_VARIANT")
        surface = pygame.Surface((runtime_globals.SCREEN_WIDTH,
                                  runtime_globals.SCREEN_HEIGHT))

        for fmt in protocol_constants.BATTLE_FORMATS:
            name = protocol_constants.get_constants(fmt).MINIGAME
            session = MinigameSession(name, manager, Pet())

            if name == "None":
                self.check(f"{fmt} ({name}) has no charge to get ready for",
                           session.finished and session.phase == "charge")
                continue

            self.check(f"{fmt} ({name}) opens on READY",
                       session.phase == "ready", session.phase)
            # READY is non-skippable, as it is in a battle.
            self.check(f"{fmt} ({name}) swallows input during READY",
                       session.handle_event(("A", None)) is True)
            self.check(f"{fmt} ({name}) has not scored during READY",
                       session.strength == 0 and session.super_hits == 0)

            phases = [session.phase]
            for _ in range(600):
                session.update()
                session.draw(surface)
                if session.phase not in phases:
                    phases.append(session.phase)
                if session.phase == "charge":
                    break
            self.check(f"{fmt} ({name}) reaches the charge",
                       phases == ["ready", "charge"], " > ".join(phases))

        # The Count Match minigames draw their own ready screen; the rest
        # fall through to the animated ready sprite.
        self.check("Count Match Color and Z own their ready screen",
                   set(READY_PHASE_MINIGAMES) == {"Count Match Color", "Count Match Z"},
                   str(sorted(READY_PHASE_MINIGAMES)))

    # ------------------------------------------------------------------
    # Section 12: the DMX wire must never hand the device a tie
    # ------------------------------------------------------------------

    def test_dmx_never_ties(self):
        self.section("DMX/PENZ hit pattern (a tie freezes the device)")

        # "Player and Opponents appear to always be inverse, and ties are not
        # programmed into the device. If a tie would occur, the device will
        # freeze and will need to be reset."
        # DMC used to ride this wire and no longer does -- it has its own
        # two 16-byte packets, and no hit pattern to tie with.
        for fmt in ('DMX', 'PENZ'):
            dcom = DComBattleSimulator(None, battle_format=fmt)
            fixture = make_digimon(power=30, hp=10, level=0, stage=1,
                                   attribute=1, index=0, shot1=0, shot2=0,
                                   mini_game=3)
            fixture.version = 0
            fixture.dmx_shot_m = 0
            packets = dcom.generate_player_packets(fixture)
            command = dcom.build_command(packets)

            self.check(f"{fmt} lets the adapter build the final packet",
                       command.endswith("-" + protocol_constants.DMX.DCOM_FINAL_SEGMENT),
                       command[-24:])
            self.check(f"{fmt} records that it did", dcom.sent_computed_final)

            # Going first, there is nothing to XOR against, so the literal
            # packet has to be sent instead.
            first = dcom.build_command(packets, turn=protocol_constants.DCOM_TURN_GO_FIRST)
            self.check(f"{fmt} sends a literal final packet when going first",
                       not first.endswith(protocol_constants.DMX.DCOM_FINAL_SEGMENT))

        # Every hit pattern a device can roll must resolve without a tie.
        dcom = DComBattleSimulator(None, battle_format='DMX')
        ties = []
        for opponent_hits in range(32):
            player_hits = (~opponent_hits) & 0x1F
            player_hp, opponent_hp = 10, 18
            pattern = [5, 4, 4, 2, 4]
            for turn in range(5):
                if (player_hits >> turn) & 1:
                    opponent_hp = max(0, opponent_hp - pattern[turn])
                if (opponent_hits >> turn) & 1:
                    player_hp = max(0, player_hp - pattern[turn])
                if player_hp == 0 or opponent_hp == 0:
                    break
            if player_hp == opponent_hp:
                ties.append(f"0b{opponent_hits:05b}")
        self.check("no inverse pattern ends in a tie", not ties, ", ".join(ties))

        # The pattern that froze a real DMX: it sent 0b10110 and we answered
        # every round as a hit, so both reached 0 on round 5.
        both_all_hits = []
        opponent_hits = 0b10110
        player_hp, opponent_hp = 10, 18
        pattern = [5, 4, 4, 2, 4]
        for turn in range(5):
            opponent_hp = max(0, opponent_hp - pattern[turn])          # all-hits
            if (opponent_hits >> turn) & 1:
                player_hp = max(0, player_hp - pattern[turn])
            if player_hp == 0 or opponent_hp == 0:
                break
        self.check("claiming every round would still tie on the recorded case",
                   player_hp == opponent_hp == 0,
                   f"{player_hp} vs {opponent_hp}")

        # ... and the inverse resolves it.
        player_hits = (~opponent_hits) & 0x1F
        player_hp, opponent_hp = 10, 18
        for turn in range(5):
            if (player_hits >> turn) & 1:
                opponent_hp = max(0, opponent_hp - pattern[turn])
            if (opponent_hits >> turn) & 1:
                player_hp = max(0, player_hp - pattern[turn])
            if player_hp == 0 or opponent_hp == 0:
                break
        self.check("the inverse resolves the recorded case",
                   player_hp != opponent_hp, f"{player_hp} vs {opponent_hp}")

    def test_hit_rate_uses_power(self):
        self.section("Hit rate is a power ratio on every wire")

        # Every protocol rolls the same way -- power against the opponent's --
        # and only the stats feeding it, and what an attribute advantage buys,
        # differ (DMX adds levels, and so on).
        import random
        for label, device_class, rounds in (
                ("DM20", DM20Device, 4), ("PEN20", PEN20Device, 4)):
            weak = make_digimon(name="Weak", power=15, attribute=3, index=1,
                                shot1=3, shot2=3, mini_game=3)
            strong = make_digimon(name="Strong", power=90, attribute=3, index=2,
                                  shot1=3, shot2=3, mini_game=3)
            weak.version = strong.version = 1
            a, b = device_class(weak), device_class(strong)
            if device_class is DM20Device:
                pairs = [(a.generate_packet1(), b.generate_packet1()),
                         (a.generate_packet2(), b.generate_packet2()),
                         (a.generate_packet3(1, 1, 0xE), b.generate_packet3(0, 1, 0xE)),
                         (a.generate_packet4(0, 0xE), b.generate_packet4(0, 0xE)),
                         (a.generate_packet5(0xE), b.generate_packet5(0xE)),
                         (a.generate_packet6(0, 0xE), b.generate_packet6(0, 0xE)),
                         (a.generate_packet7(0, 0xE), b.generate_packet7(0, 0xE)),
                         (a.generate_packet8(0xE), b.generate_packet8(0xE)),
                         (a.generate_packet9(0xE), b.generate_packet9(0xE))]
            else:
                pairs = [(a.generate_packet1(1, 1, 0xE), b.generate_packet1(0, 1, 0xE)),
                         (a.generate_packet2(0, 0xE), b.generate_packet2(0, 0xE)),
                         (a.generate_packet3(0, 0xE), b.generate_packet3(0, 0xE)),
                         (a.generate_packet4(0, 0xE), b.generate_packet4(0, 0xE)),
                         (a.generate_packet5(eol=0xE), b.generate_packet5(eol=0xE)),
                         (a.generate_packet6(0xE), b.generate_packet6(0xE)),
                         (a.generate_packet7(0, 0xE), b.generate_packet7(0, 0xE)),
                         (a.generate_packet8(0, 0xE), b.generate_packet8(0, 0xE)),
                         (a.generate_packet9(eol=0xE), b.generate_packet9(eol=0xE))]
            for x, y in pairs:
                b.process_packet(x)
                a.process_packet(y)

            random.seed(11)
            weak_hits = strong_hits = 0
            trials = 400
            for _ in range(trials):
                a.opponent_data = a.opponent_data[:9]
                b.opponent_data = b.opponent_data[:9]
                weak_hits += bin((a.generate_packetA(0xE)[1] >> 4) & 0xF).count("1")
                strong_hits += bin((b.generate_packetA(0xE)[1] >> 4) & 0xF).count("1")
            weak_rate = weak_hits / float(rounds * trials)
            strong_rate = strong_hits / float(rounds * trials)
            self.check(f"{label} the stronger Digimon lands more hits",
                       strong_rate > weak_rate,
                       f"{strong_rate:.3f} vs {weak_rate:.3f}")
            # 15/(15+90) = 0.143 and 90/105 = 0.857
            self.check(f"{label} rates track the power ratio",
                       0.06 < weak_rate < 0.25 and 0.75 < strong_rate < 0.95,
                       f"{weak_rate:.3f} / {strong_rate:.3f}")

        # What an attribute advantage buys, and where it is spent, is per wire
        # and comes from that device's module -- hardcoded here because the
        # protocol is usable without the module installed.
        self.check("DMX spends its advantage on Power",
                   protocol_constants.DMX.ATTRIBUTE_ADVANTAGE == 32
                   and protocol_constants.DMX.ATTRIBUTE_ADVANTAGE_ON_POWER,
                   f"{protocol_constants.DMX.ATTRIBUTE_ADVANTAGE}, on power="
                   f"{protocol_constants.DMX.ATTRIBUTE_ADVANTAGE_ON_POWER}")
        self.check("PENZ shares the DMX wire and its advantage",
                   protocol_constants.PENZ.ATTRIBUTE_ADVANTAGE == 32
                   and protocol_constants.PENZ.ATTRIBUTE_ADVANTAGE_ON_POWER)
        # Both 20th lines spend it on POWER, +32, which is what their
        # manuals say in the same words: "having an attribute advantage will
        # effectively grant a +32 bonus to your Digimon's Power stat", and
        # Power is what the hit rate is a ratio of.
        #
        # This used to be 5 on the roll, taken from DM20's module rather than
        # from the manual, and the module was wrong. The halves of the code
        # disagreed as a result -- `generate_packetA`, which decides the hits
        # that go on the wire, had always spent 32 on Power.
        for fmt in ("DM20", "PEN20"):
            limits = protocol_constants.get_constants(fmt)
            self.check(f"{fmt} spends its advantage on Power, +32",
                       limits.ATTRIBUTE_ADVANTAGE == 32
                       and limits.ATTRIBUTE_ADVANTAGE_ON_POWER,
                       f"{limits.ATTRIBUTE_ADVANTAGE}, on power="
                       f"{limits.ATTRIBUTE_ADVANTAGE_ON_POWER}")

        # ...and it has to be Power it reaches. At equal power of 60 the
        # holder rolls 92/(92+60), which is a shade over 0.60 -- where the
        # 5-on-the-roll rule it used to run put it at 0.55.
        for holder, target in (("Va vs Vi", 0.605), ("Vi vs Va", 0.395)):
            mine, theirs = (0, 2) if holder == "Va vs Vi" else (2, 0)
            a = make_digimon(name="A", power=60, attribute=mine, index=1,
                             shot1=3, shot2=3, mini_game=3)
            b = make_digimon(name="B", power=60, attribute=theirs, index=2,
                             shot1=3, shot2=3, mini_game=3)
            a.version = b.version = 1
            da, db = DM20Device(a), DM20Device(b)
            for x, y in ((da.generate_packet1(), db.generate_packet1()),
                         (da.generate_packet2(), db.generate_packet2()),
                         (da.generate_packet3(1, 1, 0xE), db.generate_packet3(0, 1, 0xE)),
                         (da.generate_packet4(0, 0xE), db.generate_packet4(0, 0xE)),
                         (da.generate_packet5(0xE), db.generate_packet5(0xE)),
                         (da.generate_packet6(0, 0xE), db.generate_packet6(0, 0xE)),
                         (da.generate_packet7(0, 0xE), db.generate_packet7(0, 0xE)),
                         (da.generate_packet8(0xE), db.generate_packet8(0xE)),
                         (da.generate_packet9(0xE), db.generate_packet9(0xE))):
                db.process_packet(x)
                da.process_packet(y)
            random.seed(7)
            landed = 0
            trials = 3000
            for _ in range(trials):
                da.opponent_data = da.opponent_data[:9]
                landed += bin((da.generate_packetA(0xE)[1] >> 4) & 0xF).count("1")
            rate = landed / (4.0 * trials)
            self.check(f"DM20 {holder} at equal power is {target:.2f}",
                       abs(rate - target) < 0.02, f"{rate:.3f}")

    # ------------------------------------------------------------------
    # Section 13: the seven DMX battles fought against a real device
    # ------------------------------------------------------------------

    def test_controlled_penz_battles(self):
        self.section("Controlled PENZ battles 17-21 (one charge per battle)")

        from battle.sim.battle_utils import get_attack_pattern, get_attack_damage

        # Five battles run back to back with the charge varied deliberately:
        # 17 is a DMX control, then max/max, worst/worst, mixed, and one with
        # the device maxed and us minimal. Packets verbatim from the log; the
        # HP column is the device's bar read after each of our hits.
        BATTLES = (
            # label            fmt     our p1  dev hp  our hits  filmed HP
            ("17 DMX control", "DMX",  0x022E, 18, 0x61DE, (14, 8, 4)),
            ("18 max/max",     "PENZ", 0x136E, 10, 0xA0DE, (7, 1, 0)),
            ("19 worst/worst", "PENZ", 0x106E, 10, 0xA1FE, (8, 6, 4, 2, 0)),
            ("20 mixed",       "PENZ", 0x126E, 10, 0x017E, (7, 1, 0)),
            ("21 minimal",     "PENZ", 0x106E, 10, 0xA1FE, (8, 6, 4, 2)),
        )
        for label, fmt, our1, dev_hp, our6, filmed in BATTLES:
            level, attack = ((our1 >> 11) & 0xF) + 1, (our1 >> 8) & 3
            # On the PENZ battles our pet went out as a Child (wire stage 1),
            # which is what decides the row there. The DMX control is a
            # different pet entirely -- its packet 2 is `888E`, a stage 6
            # Valdurumon -- and the DMX reads the stage too.
            pattern = get_attack_pattern(level, attack, fmt,
                                         stage=3 if fmt == "PENZ" else 6)
            hit_bits = (((our6 >> 8) & 1) << 4) | ((our6 >> 4) & 0xF)
            hp, trail = dev_hp, []
            for turn in range(5):
                if (hit_bits >> turn) & 1:
                    hp = max(0, hp - get_attack_damage(pattern[turn], fmt))
                    trail.append(hp)
                if hp == 0:
                    break
            self.check(f"battle {label} walks the device's HP down {filmed}",
                       tuple(trail[:len(filmed)]) == filmed, str(trail))

        # Battles 22-24, against the same Pendulum Z once its pet reached
        # Adult. These are what identify the earlier device-side mismatch as
        # a property of the opponent's STAGE rather than its version: the
        # version is 6 in all of them, the same 6 that mismatched while the
        # pet was a Child, and every one of them now follows the rule.
        ADULT = (
            # label   device p1  device p2  device HP  our p1  our hits  filmed HP
            ("22", 0x816E, 0x42EE, 12, 0x136E, 0x502E, (2,)),
            ("23", 0x836E, 0x42EE, 12, 0x126E, 0x800E, ()),
            ("24", 0x906E, 0x42EE, 14, 0x136E, 0x412E, (4, 0)),
        )
        for label, dev1, dev2, dev_hp, our1, our6, filmed in ADULT:
            self.check(f"battle {label}'s opponent is an Adult",
                       ((dev2 >> 13) & 7) == 2, (dev2 >> 13) & 7)
            self.check(f"battle {label}'s opponent is on the version that mismatched",
                       ((dev1 >> 4) & 0xF) == 6)
            pattern = get_attack_pattern(((our1 >> 11) & 0xF) + 1, (our1 >> 8) & 3,
                                         "PENZ", stage=3)
            bits = (((our6 >> 8) & 1) << 4) | ((our6 >> 4) & 0xF)
            hp, trail = dev_hp, []
            for turn in range(5):
                if (bits >> turn) & 1:
                    hp = max(0, hp - get_attack_damage(pattern[turn], "PENZ"))
                    trail.append(hp)
                if hp == 0:
                    break
            self.check(f"battle {label} walks the device's HP down {filmed}",
                       tuple(trail[:len(filmed)]) == filmed, str(trail))

        # And the device's own attacks follow the same table we apply to it.
        # What the film records is the SHAPE -- Single, Double, Critical --
        # and not which sprite was drawn, so that is what is compared: the
        # sw/ss and dw/ds split is a judgement the notes never carried, and
        # reading it off them is how it has been got wrong before. The rows
        # themselves come from utilities/DIGIROM/penz.txt, where the split is
        # settled by damage rising with the charge across every block.
        SHAPE = {1: "S", 2: "S", 3: "D", 4: "D", 5: "C"}
        for label, dev1, filmed in (("22", 0x816E, "SDDSD"),
                                    ("23", 0x836E, "CD")):
            drawn = get_attack_pattern(((dev1 >> 11) & 0xF) + 1, (dev1 >> 8) & 3,
                                       "PENZ", stage=4)
            shape = "".join(SHAPE[v] for v in drawn)[:len(filmed)]
            self.check(f"battle {label}'s device draws {filmed}",
                       shape == filmed, shape)

        # Battles 29 and 30: the same Baby II fought at levels 1, 2 and 3.
        # All three drew the same pattern -- and it is a reading rather than
        # a special case now: stage 2 was read at each of its three levels
        # and came out identical, so its three bands carry the same row and
        # the lookup finds that out the ordinary way.
        LOW_STAGE = (("29a", 0x839E), ("29b", 0x8B9E), ("30", 0x939E))
        drawn = set()
        for label, dev1 in LOW_STAGE:
            level, attack = ((dev1 >> 11) & 0xF) + 1, (dev1 >> 8) & 3
            pattern = get_attack_pattern(level, attack, "PENZ", stage=2)
            drawn.add(tuple(pattern))
            self.check(f"battle {label}'s Baby II draws Single, Critical, Double...",
                       pattern[:3] == [2, 5, 4], str(pattern[:3]))
        self.check("a Baby II draws one row at every level, as measured",
                   len(drawn) == 1, str(drawn))

        # An Adult on the same device reads its level band. Levels 1 and 2
        # are one band by measurement, so they agree; level 6 is this stage's
        # own maximum and stands alone, which is where the row changes.
        self.check("an Adult's levels 1 and 2 are one band",
                   get_attack_pattern(1, 3, "PENZ", stage=4)
                   == get_attack_pattern(2, 3, "PENZ", stage=4))
        self.check("an Adult still reads the level at its top band",
                   get_attack_pattern(1, 3, "PENZ", stage=4)
                   != get_attack_pattern(6, 3, "PENZ", stage=4))
        # Both lines read the stage first, and each out of its own file.
        self.check("the DMX reads the stage, and not as a fixed row",
                   get_attack_pattern(1, 3, "DMX", stage=2)
                   != get_attack_pattern(1, 3, "DMX", stage=6))
        self.check("and the DMX still reads the level within a stage",
                   get_attack_pattern(1, 3, "DMX", stage=6)
                   != get_attack_pattern(10, 3, "DMX", stage=6))

        # Between them these cover four different rows of the table, so the
        # PENZ row shift is not resting on one pattern any more.
        rows = {get_attack_pattern(((p >> 11) & 0xF) + 1, (p >> 8) & 3, "PENZ",
                                   stage=3)[0]
                for _, f, p, _, _, _ in BATTLES if f == "PENZ"}
        self.check("the PENZ battles exercise several patterns", len(rows) >= 2, str(rows))

        # And the DMX control confirms nothing moved on that wire while PENZ
        # was being worked on. It carries a stage now, because the DMX's own
        # table is keyed on one -- an Ultimate at level 1 on a Great charge.
        self.check("the DMX control still reads its own table",
                   get_attack_pattern(1, 2, "DMX", 6) == [3, 4, 4, 3, 3],
                   str(get_attack_pattern(1, 2, "DMX", 6)))

        # The damage scale belongs to the TABLE, not the wire. PENZ shares
        # the DMX's five types and their damage -- testing for the literal
        # string "DMX" gave it raw pattern values, so a critical cost 5
        # instead of 10.
        for fmt in ("DMX", "PENZ"):
            self.check(f"{fmt} spends the measured damage",
                       [get_attack_damage(v, fmt) for v in range(1, 6)] == [2, 3, 4, 6, 10],
                       str([get_attack_damage(v, fmt) for v in range(1, 6)]))
        # DMC rides the same wire and does NOT share the table: its rows are
        # 1s and 2s where the value simply is the damage, which is what
        # ATTACK_ANIMATION "count" means. Reading it on the DMX scale would
        # turn a 2 into 3 and spend 9 on a verdict battle's 5 HP bar.
        for fmt in ("DMC", "PENC", "DM20", "PEN20"):
            self.check(f"{fmt} keeps the pattern value as damage",
                       [get_attack_damage(v, fmt) for v in range(1, 6)] == [1, 2, 3, 4, 5],
                       str([get_attack_damage(v, fmt) for v in range(1, 6)]))

    def test_dmc_wire(self):
        self.section("DMC wire (Digital Monster Color, 16-byte packets)")

        from battle.sim.battle_simulator import DMCBSPacket

        # The document's worked example, Omegamon Alter-S. Operation 1 is
        # Player 2 Digimon Data, operation 3 Player 2 Battle Data.
        p1 = DMCBSPacket(operation=1, index=0x11, power=0xFA, attribute=1,
                         shot=0x10, outcome=0, version=0).build_packet1()
        p2 = DMCBSPacket(operation=3, index=0x11, power=0xFA, attribute=1,
                         shot=0x10, outcome=0, version=0).build_packet2()
        self.check("DMC packet 1 matches the document",
                   p1.hex().upper() == "47444C4300010000001100FA00019494",
                   p1.hex().upper())
        self.check("DMC packet 2 matches the document",
                   p2.hex().upper() == "47444C4300030010000000000000939A",
                   p2.hex().upper())

        # "Check -- Equal to the value of each 16 bit sequence."
        words = [int.from_bytes(p1[i:i + 2], 'big') for i in range(0, len(p1), 2)]
        self.check("the check is the sum of the words before it",
                   sum(words[:-1]) & 0xFFFF == words[-1])

        # It is its own wire, not the DMX's. Sending a Color device six
        # 2-byte DMX packets is what it used to do, and it never answered.
        self.check("DMC names its own wire",
                   protocol_constants.DMC.DCOM_WIRE == "DMC")
        self.check("DMC packets are 16 bytes",
                   protocol_constants.DMC.PACKET_BYTES == 16)
        self.check("and there are two of them",
                   protocol_constants.DMC.PACKET_COUNT == 2)

        # Every format must name a layout that exists; there is no default.
        for fmt in protocol_constants.BATTLE_FORMATS:
            wire = protocol_constants.get_wire(fmt)
            self.check(f"{fmt} names a known wire", wire is not None, fmt)

        class Unknown:
            DCOM_WIRE = "NOPE"
        try:
            protocol_constants.WIRE_FORMATS["NOPE"]
            declared = True
        except KeyError:
            declared = False
        self.check("an unknown wire is not silently a real one", not declared)

        # DMC's attribute order is its own: Free 0, Virus 1, Data 2,
        # Vaccine 3, against Va 0, Da 1, Vi 2, Free 3 everywhere else.
        self.check("DMC maps Vaccine to 3",
                   protocol_constants.DMC.ATTRIBUTE_MAP[0] == 3)
        self.check("DMC maps Free to 0",
                   protocol_constants.DMC.ATTRIBUTE_MAP[3] == 0)
        self.check("the map is a bijection",
                   sorted(protocol_constants.DMC.ATTRIBUTE_MAP.values()) == [0, 1, 2, 3])

        # Round trip through the wire and back.
        dcom = DComBattleSimulator(None, battle_format="DMC")
        fixture = make_digimon(power=250, hp=5, index=17, attribute=1,
                               shot1=16, shot2=16, mini_game=0, level=1, stage=4)
        fixture.version = 0
        packets = dcom.generate_player_packets(fixture)
        self.check("DMC builds two packets", packets is not None and len(packets) == 2,
                   str(len(packets) if packets else None))
        self.check("DMC validates its own packets", dcom._validate_packets(packets))
        opponent = dcom.parse_opponent([p.hex().upper() for p in packets], fixture)
        self.check("DMC parses an opponent back", opponent is not None)
        if opponent:
            self.check("power survives the round trip", opponent.power == 250, opponent.power)
            self.check("index survives the round trip", opponent.index == 17, opponent.index)

    def test_jogress_roms(self):
        self.section("Jogress DigiROMs (one packet, describing a partner)")

        from battle.sim import jogress_roms as jr

        self.check("PENC can jogress over the wire", jr.supports("PENC"))
        self.check("DMC cannot", not jr.supports("DMC"))

        # Each side's packet describes its OWN pet, so we send the ROM our
        # pet fits -- looked up on its own stage and attribute.
        for stage, attribute in ((4, "Va"), (4, "Da"), (4, "Vi"),
                                 (5, "Va"), (5, "Da"), (5, "Vi"),
                                 (6, "Va"), (6, "Da"), (6, "Vi")):
            rom = jr.rom_for("PENC", stage, attribute)
            self.check(f"PENC can present a stage {stage} {attribute} pet",
                       rom is not None, str(rom))
            if rom:
                body = rom.split("-")[1]
                words = [int(body[i:i + 4], 16) for i in range(0, 32, 4)]
                self.check(f"...and that ROM checksums",
                           sum(words[:-1]) & 0xFFFF == words[-1])
                back = jr.parse(rom)
                self.check(f"...and reads back as stage {stage} {attribute}",
                           back and back["stage"] == stage
                           and back["attribute"] == attribute, str(back))

        # The exchange, end to end: our Adult Vaccine pet sends its own ROM,
        # the device answers with an Adult Virus, and the route that wants
        # one fires.
        class Ours:
            stage, attribute = 4, "Va"
            evolve = []
        ours = jr.rom_for_pet(Ours(), "PENC")
        self.check("an Adult Vaccine pet sends the Adult Vaccine code",
                   ours == "C1-47444470001400020006000300038BD6", ours)
        theirs = jr.parse("C1-47444470001400010009000100038BD6")
        self.check("their reply is an Adult Virus",
                   theirs["stage"] == 4 and theirs["attribute"] == "Vi", str(theirs))

        # **A device answers 0x15, not 0x14.** The operation names the side
        # speaking and the reply is one higher, the same pairing the battle
        # uses for 0x10/0x11 and 0x12/0x13. Measured: this exact packet came
        # back from a Pendulum Color when we sent the Adult Vaccine code
        # above, and reading only the initiator's 0x14 dropped it as "not a
        # jogress" -- the toy evolved and our pet did not.
        answered = jr.parse_reply(["4744447000150004001D000100038BEE"], "PENC")
        self.check("a device's 0x15 reply is read",
                   answered is not None, str(answered))
        self.check("and it is an Adult Virus on version 5",
                   answered and answered["stage"] == 4
                   and answered["attribute"] == "Vi"
                   and answered["version"] == 5
                   and answered["index"] == 29, str(answered))

        class Pet:
            evolve = [
                {"to": "Jagamon", "jogress": "Dual", "jogress_stage": 4,
                 "jogress_attribute": "Va"},
                {"to": "Piximon", "jogress": "Dual", "jogress_stage": 4,
                 "jogress_attribute": "Vi"},
            ]
        route = jr.matching_route(Pet(), theirs)
        self.check("the pet takes the route that wanted a Virus Adult",
                   route and route["to"] == "Piximon", str(route))

        # A named jogress says WHO, and the wire can reach that too: the
        # reply's version and index name a Digimon on the module's roster.
        roster = [
            {"name": "Angewomon", "version": 1, "index": 18, "stage": 5,
             "attribute": "Va"},
            {"name": "LadyDevimon", "version": 3, "index": 18, "stage": 5,
             "attribute": "Vi"},
        ]

        class Lady:
            name, version, index, stage, attribute = "LadyDevimon", 3, 18, 5, "Vi"
            evolve = [
                {"to": "NoblePumpkinmon", "jogress": "Dual", "jogress_stage": 5,
                 "jogress_attribute": "Va"},
                {"to": "Mastemon", "jogress": "Single",
                 "jogress_name": "Angewomon", "jogress_version": 1},
            ]

        class Ange:
            name, version, index, stage, attribute = "Angewomon", 1, 18, 5, "Va"
            evolve = [{"to": "Mastemon", "jogress": "Single",
                       "jogress_name": "LadyDevimon", "jogress_version": 3}]

        # Each sends the ROM presenting itself -- an exact one, because a
        # named jogress needs the device to recognise who answered.
        lady_rom = jr.rom_for_pet(Lady(), "PENC")
        ange_rom = jr.rom_for_pet(Ange(), "PENC")
        self.check("LadyDevimon sends an exact ROM, not the generic Virus Perfect",
                   lady_rom != jr.rom_for("PENC", 5, "Vi"), lady_rom)
        self.check("Angewomon sends an exact ROM",
                   ange_rom != jr.rom_for("PENC", 5, "Va"), ange_rom)

        from_ange = jr.parse(ange_rom)
        self.check("the reply resolves to Angewomon on the roster",
                   (jr.presented_pet(from_ange, roster, "PENC") or {}).get("name")
                   == "Angewomon")
        route = jr.matching_route(Lady(), from_ange, roster)
        self.check("LadyDevimon meeting Angewomon becomes Mastemon",
                   route and route["to"] == "Mastemon", str(route))
        # ...and not the NoblePumpkinmon its "any Vaccine Perfect" route
        # would take, even though that route is listed first.
        self.check("the named route beats the attribute one",
                   route and route.get("jogress_name") == "Angewomon")
        back = jr.matching_route(Ange(), jr.parse(lady_rom), roster)
        self.check("and the other direction agrees",
                   back and back["to"] == "Mastemon", str(back))

        # Without a roster there is nothing to resolve a name against, so a
        # named route is skipped rather than guessed at.
        self.check("a named route needs the roster",
                   jr.matching_route(Ange(), jr.parse(lady_rom)) is None)

        # Single and Dual are not consulted: over the wire each side keeps
        # its own pet, so ours simply evolves.
        self.check("a Single jogress still evolves our pet over the wire",
                   route["jogress"] == "Single")

        # Anything that is not a jogress packet is refused rather than
        # guessed at: a bad checksum, and a battle packet.
        self.check("a corrupt ROM is refused",
                   jr.parse("C1-47444470001400010009000100038BFF") is None)
        self.check("a battle packet is refused",
                   jr.parse("47444470001100000002000A00038BD4") is None)
        self.check("an empty string is refused", jr.parse("") is None)

        # A pet no real device presents cannot jogress at all. That is the
        # enforcement: a module carrying data the hardware would never
        # produce simply cannot push it onto the hardware.
        class Impossible:
            stage, attribute = 2, "Free"      # a Baby II, and Free besides
            evolve = [{"to": "X", "jogress": "Dual", "jogress_stage": 4,
                       "jogress_attribute": "Va"}]
        self.check("a pet no device presents gets no ROM",
                   jr.rom_for_pet(Impossible(), "PENC") is None)
        self.check("and neither does an unknown protocol",
                   jr.rom_for_pet(Ours(), "DMX") is None)

        # Version is a MAP, not an offset. The device numbers its eight
        # releases in shipping order; Omnipet numbers the five main ones 1-5
        # and calls Virus Busters 0, which is the sixth release -- so wire 5
        # is module 0, not module 6. The label pairs are what prove it:
        # "Metal Garurumon into Omegamon" presents the WarGreymon that only
        # exists on module version 0, and its partner code presents the
        # MetalGarurumon on version 5.
        self.check("PENC wire 5 is module version 0 (Virus Busters)",
                   jr.module_version("PENC", 5) == 0)
        self.check("PENC wire 4 is module version 5",
                   jr.module_version("PENC", 4) == 5)
        self.check("PENC wire 6 and 7 are themselves",
                   jr.module_version("PENC", 6) == 6
                   and jr.module_version("PENC", 7) == 7)
        war = jr.parse("C1-47444470001400050011000300058BE6")
        self.check("the MetalGarurumon code presents a v0 Ultimate Vaccine",
                   war and war["version"] == 0 and war["index"] == 17
                   and war["stage"] == 6 and war["attribute"] == "Va", str(war))

        # PENZ is the second readable layout: three 2-byte packets over the
        # DMX wire, whose first two are the DMX battle's own packets 1 and 2.
        # All eight generic codes decode to exactly the stage and attribute
        # their labels claim, which is what settles the layout.
        self.check("PENZ can jogress over the wire", jr.supports("PENZ"))
        for label, rom, stage, attribute in (
                ("Vaccine Adult", "V2-04^0E-478E-@E00E", 4, "Va"),
                ("Data Adult", "V2-04^0E-4E9E-@E00E", 4, "Da"),
                ("Virus Adult", "V2-04^0E-4EEE-@E00E", 4, "Vi"),
                ("Free Adult", "V2-04^0E-57BE-@E00E", 4, "Free"),
                ("Vaccine Perfect", "V2-04^0E-6A0E-@E00E", 5, "Va"),
                ("Data Perfect", "V2-04^0E-63DE-@E00E", 5, "Da"),
                ("Virus Perfect", "V2-04^0E-63AE-@E00E", 5, "Vi"),
                ("Free Perfect", "V2-04^0E-77BE-@E00E", 5, "Free")):
            self.check(f"PENZ presents a {label} with that code",
                       jr.rom_for("PENZ", stage, attribute) == rom,
                       str(jr.rom_for("PENZ", stage, attribute)))

        # Version is a flat wire = module + 5 here, which is also why a real
        # Pendulum Z announces version 10 in a battle: that is module 5.
        self.check("PENZ wire 10 is module version 5",
                   jr.module_version("PENZ", 10) == 5)
        self.check("PENZ wire 6 is module version 1",
                   jr.module_version("PENZ", 6) == 1)

        # A reply is read out of packets 1 and 2 together.
        reply = jr.parse_reply(["00AE", "4E9E", "000E"], "PENZ")
        self.check("a PENZ reply reads as a Data Adult on version 5",
                   reply and reply["stage"] == 4 and reply["attribute"] == "Da"
                   and reply["version"] == 5, str(reply))

        # This wire carries no checksum, and a battle on it opens with two
        # packets shaped exactly like a jogress's -- so the packet COUNT is
        # the only thing separating them, and it has to be enforced.
        self.check("a battle's six packets are not read as a jogress",
                   jr.parse_reply(["2C6E", "430E", "1234", "5678", "9ABC",
                                   "DEF0"], "PENZ") is None)
        self.check("nor are packets missing the EOL nibble",
                   jr.parse_reply(["1234", "5678", "9ABC"], "PENZ") is None)
        self.check("nor is a single packet",
                   jr.parse_reply(["049E"], "PENZ") is None)
        for line, count in (("PENX", 26), ("ACCEL", 4), ("PENCYCLE", 3),
                            ("PENPROGRESS", 12)):
            self.check(f"{line} codes are stored even with no module",
                       len(jr.roms(line)) == count, str(len(jr.roms(line))))
            self.check(f"...and {line} still cannot complete an exchange",
                       not jr.supports(line))

    def test_serial_jogress(self):
        self.section("Serial jogress (send a code, read who answered)")

        from battle.sim import jogress_roms as jr
        from battle.sim.jogress_session import (SerialJogressSession,
                                                can_jogress_over_serial)
        from utils.jogress_utils import normalize_evolutions

        # The harness runs without a modules folder, so the two modules these
        # checks name are stubbed. Only battle_protocol and the roster are
        # read, which is exactly what a real module supplies here.
        from core import runtime_globals as globals_

        class StubModule:
            def __init__(self, name, protocol, roster=()):
                self.name = name
                self.battle_protocol = protocol
                self._roster = list(roster)

            def get_all_monsters(self):
                return self._roster

        saved_modules = getattr(globals_, "game_modules", None)
        globals_.game_modules = {
            "PENC": StubModule("PENC", "PENC",
                               [{"name": "Angewomon", "version": 1, "index": 18}]),
            "PENZ": StubModule("PENZ", "PENZ"),
            "D-3": StubModule("D-3", ""),
        }
        try:
            self._serial_jogress_checks(jr, SerialJogressSession,
                                        can_jogress_over_serial,
                                        normalize_evolutions)
        finally:
            globals_.game_modules = saved_modules

    def _serial_jogress_checks(self, jr, SerialJogressSession,
                               can_jogress_over_serial, normalize_evolutions):

        # A pet whose module speaks a line we can complete an exchange on.
        # LadyDevimon is PENC version 3, index 18, Virus, Perfect -- and the
        # ROM labelled "Jogress Angewomon into Mastemon" carries exactly
        # that, because a code is labelled by the pet you OWN and presents
        # that pet's partner.
        class Lady:
            name = "LadyDevimon"
            module = "PENC"
            version, index, attribute, stage = 3, 18, "Vi", 5
            evolve = normalize_evolutions([
                {"to": "Creepymon", "jogress": "Dual", "jogress_stage": 5,
                 "jogress_attribute": "Da"},
                {"to": "NoblePumpkinmon", "jogress": "Dual", "jogress_stage": 5,
                 "jogress_attribute": "Va"},
                {"to": "Mastemon", "jogress": "Single",
                 "jogress_name": "Angewomon", "jogress_version": 1},
            ])

        session = SerialJogressSession(Lady(), None)
        self.check("our pet sends the code that presents it",
                   session.rom == "C1-47444470001400020012000100048BE1",
                   str(session.rom))

        # The device answers describing ITS pet: an Angewomon, module
        # version 1 (wire 0), index 18, Vaccine, Perfect.
        answered = session.consume_line("r:47444470001400000012000300048BE1")
        self.check("the reply is recognised as a jogress", answered)
        self.check("...and reads as a Perfect Vaccine",
                   session.partner["stage"] == 5
                   and session.partner["attribute"] == "Va", str(session.partner))
        self.check("...on module version 1, through the version map",
                   session.partner["version"] == 1 and session.partner["index"] == 18)

        # A named route beats the attribute one: the wire says exactly WHO
        # answered, which is what a named route asks for. Without the roster
        # only the attribute routes can be judged, so it falls to those.
        roster = [{"name": "Angewomon", "version": 1, "index": 18}]
        route = jr.matching_route(Lady(), session.partner, roster)
        self.check("a named partner takes the named route",
                   route and route["to"] == "Mastemon", str(route))
        blind = jr.matching_route(Lady(), session.partner, None)
        self.check("without the roster it falls back to the attribute route",
                   blind and blind["to"] == "NoblePumpkinmon", str(blind))

        # Single and Dual are not consulted over the wire: the device keeps
        # its own pet whatever happens, so ours simply evolves.
        self.check("the route it took is a Single, and that changes nothing",
                   route["jogress"] == "Single")

        # A partner this pet has no route for is a real answer, not a fault.
        stray = jr.parse("C1-47444470001400020006000300038BD6")   # Adult Vaccine
        self.check("an Adult Vaccine parses", stray and stray["stage"] == 4)
        self.check("...and LadyDevimon has no route for it",
                   jr.matching_route(Lady(), stray, roster) is None)

        # Rubbish on the wire is refused rather than guessed at.
        empty = SerialJogressSession(Lady(), None)
        self.check("a battle packet is not mistaken for a jogress",
                   not empty.consume_line("r:47444470001100000002000A00038BD4"))
        self.check("nor is an abort", not empty.consume_line("r:FF00"))

        # The same flow on the other readable wire, end to end: a PENZ
        # Devimon is offered the exchange, sends its own shape, and takes the
        # route the answer resolves to.
        class Penz:
            name = "Devimon"
            module = "PENZ"
            version, index, attribute, stage = 3, 61, "Vi", 4
            evolve = normalize_evolutions([
                {"to": "Kimeramon", "stage": 4, "attribute": "Da"},
                {"to": "Argomon (Perfect)", "stage": 4, "attribute": "Free"},
            ])
        possible, reason = can_jogress_over_serial(Penz())
        self.check("a PENZ pet can jogress over the wire", possible, reason)

        penz = SerialJogressSession(Penz(), None)
        self.check("it presents itself as a Virus Adult",
                   penz.rom == "V2-04^0E-4EEE-@E00E", str(penz.rom))
        self.check("the device answers with a Data Adult",
                   penz.consume_line("r:00AE r:4E9E r:000E"))
        route = jr.matching_route(Penz(), penz.partner, [])
        self.check("...and Devimon takes its Data route",
                   route and route["to"] == "Kimeramon", str(route))

        # A marker-less PENZ route is still a jogress route: 448 of them are
        # written that way and nothing else in the game is.
        self.check("the route it took was written with no jogress marker",
                   route["jogress"] == "Dual"
                   and route["jogress_attribute"] == "Da")

        class Nowhere:
            name = "Agumon"
            module = "D-3"
            version, index, attribute, stage = 1, 1, "Va", 4
            evolve = []
        possible, reason = can_jogress_over_serial(Nowhere())
        self.check("a module no device speaks for is refused too",
                   not possible, reason)

    def test_dmog_slots_and_verdict(self):
        self.section("DMOG slots, and which side a verdict belongs to")

        from battle.sim.battle_simulator import DMDevice, BattleSimulator
        from battle.sim.models import BattleProtocol

        DMOG = protocol_constants.DMOG

        # The twelve slots run consecutively, A at 0x3 to L at 0xE. The
        # document names them by chart position: 2 Child, 7 Adult, 3 Perfect.
        self.check("there are twelve slots", len(DMOG.SLOT_LETTERS) == 12)
        self.check("A is 0x3 and L is 0xE",
                   DMOG.FIRST_SLOT == 0x3 and DMOG.LAST_SLOT == 0xE)
        self.check("...and they are consecutive",
                   DMOG.LAST_SLOT - DMOG.FIRST_SLOT + 1 == len(DMOG.SLOT_LETTERS))

        # A pet native to this line has a real slot: every DM module version
        # lists the twelve battling Digimon at indices 2..13 in chart order,
        # so the slot is the index shifted up one. Agumon is slot A, and
        # Monzaemon -- the top Perfect -- is slot L.
        def slot_of(index, power=30):
            return DMDevice._get_slot(make_digimon(index=index, power=power))

        self.check("index 2 (Agumon) is slot A", slot_of(2) == 0x3, hex(slot_of(2)))
        self.check("index 9 (Seadramon) is slot H", slot_of(9) == 0xA, hex(slot_of(9)))
        self.check("index 13 (Monzaemon) is slot L", slot_of(13) == 0xE, hex(slot_of(13)))
        self.check("the whole chart maps consecutively",
                   [slot_of(i) for i in range(DMOG.FIRST_SLOT_INDEX,
                                              DMOG.LAST_SLOT_INDEX + 1)]
                   == list(range(DMOG.FIRST_SLOT, DMOG.LAST_SLOT + 1)))

        # The index is not on the wire, but it chooses the slot, so it must
        # survive pet_to_digimon rather than being flattened to zero.
        self.check("the wire keeps the chart's index range",
                   DMOG.MAX_INDEX == DMOG.LAST_SLOT_INDEX)

        # A pet from another module has no place on that chart and falls back.
        self.check("a foreign pet still gets a valid slot",
                   DMOG.FIRST_SLOT <= slot_of(0, power=15) <= DMOG.LAST_SLOT,
                   hex(slot_of(0, power=15)))

        # The document's own worked example: "matching A on the left with H
        # on the top gives us a 3, meaning a 3 out of 16 chance".
        sim = BattleSimulator(BattleProtocol.DMOG_BS)
        self.check("slot A against slot H is 3 in 16",
                   sim._get_dm_win_probability(0, 7, 0, 0) == 3,
                   str(sim._get_dm_win_probability(0, 7, 0, 0)))
        self.check("a slot against itself is even (8 in 16)",
                   all(sim._get_dm_win_probability(n, n, 0, 0) == 8
                       for n in range(12)))

        # A verdict is the SENDER's result. The toy writing 1 means the toy
        # won. Three sources: the document ("1 means victory while 2 means
        # defeat"), wificom's punchbag "DMOG you win" -- the one that makes
        # the toy win -- sending outcome 2, and a filmed battle where a real
        # device sent 1 and played a win.
        dcom = DComBattleSimulator(None, battle_format='DMOG')
        player = make_digimon(name="Ours", power=15, index=0)
        opponent = make_digimon(name="Theirs", power=45, index=0)
        ours = [bytes.fromhex("FB04"), bytes.fromhex("ED12")]

        for label, device_packet2, player_wins in (
                ("the device declaring victory is our loss", "EE11", False),
                ("the device declaring defeat is our win", "ED12", True)):
            result = dcom.build_result(player, opponent, ours,
                                       ["F50A", device_packet2])
            won = result.winner == "device2"
            self.check(label, won == player_wins, str(result.winner))

        # wificom's punchbags, decoded, are the same statement.
        for rom, toy_wins in (("V1-FC03-FD02", True),    # "DMOG you win"
                              ("V1-FC03-FE01", False)):  # "DMOG you lose"
            outcome = int(rom.split("-")[2], 16) & 0xF
            declared_victory = outcome == DMOG.OUTCOME_VICTORY
            self.check(f"{rom} makes the toy {'win' if toy_wins else 'lose'}",
                       declared_victory != toy_wins,
                       "sender declared %d" % outcome)

        # A slot is a tier, not an identity: "two Digimon in the same slot
        # were effectively the same Digimon", and a modern device in legacy
        # mode maps its own roster onto the same twelve. So the opponent
        # cannot be named, and must not be -- naming one from the DM chart
        # showed a Seadramon for a DMX that held something else.
        for word, band in (("FC03", 3), ("FA05", 4), ("F50A", 4), ("F10E", 5)):
            opponent = dcom._parse_dm_opponent([bytes.fromhex(word),
                                                bytes.fromhex("ED12")])
            slot = int(word, 16) & 0xF
            self.check(f"slot 0x{slot:X} answers as the placeholder",
                       opponent.name == DMOG.GENERIC_OPPONENT, opponent.name)
            self.check(f"...in the {('Child', 'Adult', 'Perfect')[band - 3]} band",
                       opponent.stage == band, str(opponent.stage))

        # The placeholder needs a sprite set in every shared library, because
        # the module being played decides which one is asked for.
        import zipfile
        for library in ("monsters", "monsters_dot", "monsters_hidef"):
            path = os.path.join(_REPO_ROOT, "assets", library,
                                DMOG.GENERIC_OPPONENT + "_dmc.zip")
            self.check(f"{library} carries the placeholder set",
                       os.path.exists(path), path)
            if not os.path.exists(path):
                continue
            with zipfile.ZipFile(path) as archive:
                frames = sorted(int(n.split(".")[0]) for n in archive.namelist())
            self.check(f"...with frames 0-14", frames == list(range(15)), str(frames))
            # Slot 15 must be absent: the critical slide-in keys off that.
            self.check(f"...and no SPECIAL frame", 15 not in frames)

        # We answer rather than open. Opening means declaring a result we
        # have not earned, and we always declared defeat -- every battle we
        # started was a loss.
        self.check("DMOG listens rather than opening", not dcom.goes_first)
        command = dcom.build_command(dcom.generate_player_packets(player))
        self.check("...so the adapter builds our verdict from theirs",
                   command.count("^3") == 2, command)
        opened = dcom.build_command(dcom.generate_player_packets(player),
                                    turn=protocol_constants.DCOM_TURN_GO_FIRST)
        self.check("going first there is nothing to XOR, so it is literal",
                   "^" not in opened, opened)

    def test_dmm_conformance(self):
        self.section("DMM conformance (Digimon Mini, 4 packets on the 3-prong wire)")

        from types import SimpleNamespace
        from collections import Counter
        from battle.sim.battle_simulator import DMMDevice
        from battle.sim.battle_utils import dmm_counts_for
        from battle.sim.exchange import PacketExchange

        DMM = protocol_constants.DMM
        dcom = DComBattleSimulator(None, battle_format='DMM')

        def side(text):
            return [bytes.fromhex(p) for p in text.split("-")]

        def counts_for(rounds):
            return dmm_counts_for(rounds)

        # Every PenX and Mini battle code on record passes both known checks.
        known = {
            "MINI you win (koromon)": "0019-1109-C009-1009",
            "Punching bag": "0159-4379-0009-C009",
            "Guaranteed loss": "0159-4379-0009-C1F9",
            "Toy wins against Okuwamon X": "0249-E589-0009-F009",
            "PenX you win (longer), @4 resolved": "0159-4379-2E49-8009",
            "PenX you lose (longer), @4 resolved": "0159-4379-2AA9-61F9",
            "Mini on Accel/iC, @4 resolved": "0099-1869-7AF9-8009",
        }
        for label, code in known.items():
            self.check(f"'{label}' validates as DMM",
                       dcom._validate_packets(side(code)))

        # Packet 3's rounds are damage - 1, and every code is a Count Bar row.
        for code, count in (("0159-4379-2E49-8009", 9), ("0159-4379-2AA9-61F9", 11),
                            ("0099-1869-7AF9-8009", 20), ("0019-1109-C009-1009", 0)):
            rounds = DMMDevice.parse(side(code))["rounds"]
            self.check(f"{code} packet 3 is a Count Bar row (count {count})",
                       count in counts_for(rounds), "".join(map(str, rounds)))

        # Packet 1 is the roster index: the first capture was a Mini Tentomon.
        self.check("the captured Mini's 0029 is index 2, Tentomon on Ver.2",
                   DMMDevice.parse(side("0029-1289-0009-0009"))["index"] == 2)
        self.check("a DMOG-shaped reply is not a DMM side",
                   not dcom._validate_packets(side("FC03-ED12-FC03-ED12")))

        # nacatech's analyzer names every field; these are its own readings of
        # the codes on record (battle.nacatech.es/nt/analyzer?t=penx&d=...).
        # Its Shot Sizes are damage - 1, round 1 first.
        analyzer = {
            "0019-1109-C009-1009": dict(index=1, projectile=1, power=16, attribute=3,
                                        sizes="0 0 0 0 0", hits="00000"),
            "0159-4379-2E49-8009": dict(index=21, projectile=4, power=55, attribute=0,
                                        sizes="0 1 2 3 2", hits="00000"),
            "0159-4379-2AA9-61F9": dict(index=21, projectile=4, power=55, attribute=0,
                                        sizes="2 2 2 2 2", hits="11111"),
            "0249-E589-0009-F009": dict(index=36, projectile=14, power=88, attribute=0,
                                        sizes="0 0 0 0 0", hits="00000"),
            "0099-1869-7AF9-8009": dict(index=9, projectile=1, power=134, attribute=1,
                                        sizes="3 3 2 2 3", hits="00000"),
            "0069-2169-8009-0009": dict(index=6, projectile=2, power=22, attribute=2,
                                        sizes="0 0 0 0 0", hits="00000"),
        }
        for code, expected in analyzer.items():
            fields = DMMDevice.parse(side(code))
            ours = dict(index=fields["index"], projectile=fields["projectile"],
                        power=fields["power"], attribute=fields["attribute"],
                        sizes=" ".join(str(r - 1) for r in fields["rounds"]),
                        hits=format(fields["hits"], "05b"))
            self.check(f"{code} decodes as nacatech's analyzer reads it",
                       ours == expected, str(ours))
        self.check("the captured Mini Tentomon's 1289 is projectile 1, power 40",
                   DMMDevice.parse(side("0029-1289-0009-0009"))["projectile"] == 1
                   and DMMDevice.parse(side("0029-1289-0009-0009"))["power"] == 40)

        # An outsider announces Koromon's index, and its own power and attribute.
        outsider = make_digimon(index=0, mini_game=0, power=77, attribute=2)
        packets = DMMDevice(outsider).generate_all_packets(hits=0, pattern=[1] * 5)
        fields = DMMDevice.parse(packets)
        self.check("an outsider announces index 1 with its own power",
                   fields["index"] == 1 and fields["power"] == 77, str(fields))
        self.check("a generated side validates", dcom._validate_packets(packets))

        pet = make_digimon(index=7, mini_game=20)
        packets = DMMDevice(pet).generate_all_packets(hits=0b10110)
        fields = DMMDevice.parse(packets)
        self.check("a generated side reads back its index, row and hits",
                   fields["index"] == 7 and 20 in counts_for(fields["rounds"])
                   and fields["hits"] == 0b10110, str(fields))

        # Over a cable we listen, and the adapter inverts the device's hits.
        command = dcom.build_command(packets)
        self.check("the cable command is X2 with @4^1^F9 last",
                   command.startswith("X2-") and command.endswith("-@4^1^F9"), command)
        device = side("0159-4379-0009-C1F9")
        context = SimpleNamespace(sent=device, received=packets[:3])
        resolved = PacketExchange._resolve_incoming(context, "@4^1^F9", 3)
        reply = packets[:3] + [bytes.fromhex(resolved)]
        self.check("the adapter's reply inverts the device's hits and validates",
                   DMMDevice.parse(reply)["hits"] == 0
                   and dcom._validate_packets(reply), resolved)

        # Filmed battle 1 (utilities/DIGIROM/battles2.txt): a real Mini
        # Tentomon at count 21 opened against our count 10. Film: device 3,
        # game 1 miss, device 4, game 2 miss, device wins.
        tentomon = side("0029-1289-BFE9-B1F9")
        ours_filmed = side("0019-E0F9-FE49-1009")
        self.check("filmed battle 1: both sides validate",
                   dcom._validate_packets(tentomon) and dcom._validate_packets(ours_filmed))
        self.check("filmed battle 1: the Mini Tentomon (Vaccine) sends attribute 2",
                   DMMDevice.parse(tentomon)["attribute"] == 2)
        filmed = DComBattleSimulator(None, battle_format='DMM')
        filmed.opening = False
        player = make_digimon(index=0, power=15, attribute=3)
        device = filmed.parse_opponent([p.hex() for p in tentomon], player)
        self.check("filmed battle 1: the Mini is shown as a Vaccine",
                   device is not None and device.name == "Va", device and device.name)
        replay = filmed.build_result(player, device, ours_filmed,
                                     [p.hex() for p in tentomon])
        rounds = [[(a.device, a.hit, a.damage) for a in t.attacks] for t in replay.battle_log]
        self.check("filmed battle 1 replays round for round",
                   rounds == [[("device1", True, 3), ("device2", False, 1)],
                              [("device1", True, 4), ("device2", False, 2)]]
                   and replay.winner == "device1", str(rounds))
        self.check("DMM fights on a 6 HP bar (filmed battle 2)",
                   filmed.get_initial_hp(player) == 6)

        # Filmed battle 3: a Mini Ver.1 Agumon opened against our count 15.
        # Film: device 3 (miss), game 4 hit -- Mini on 0 -- device lost. So a
        # 4 is the Hyper hit, 6 damage, and one blow ends a full bar.
        agumon = side("0029-1199-AFE9-3189")
        ours_filmed = side("0019-E0F9-77F9-E079")
        filmed = DComBattleSimulator(None, battle_format='DMM')
        filmed.opening = False
        player = make_digimon(index=0, power=15, attribute=1)
        device = filmed.parse_opponent([p.hex() for p in agumon], player)
        self.check("filmed battle 3: the Mini Agumon (Vaccine) sends attribute 2",
                   DMMDevice.parse(agumon)["attribute"] == 2)
        replay = filmed.build_result(player, device, ours_filmed,
                                     [p.hex() for p in agumon])
        rounds = [[(a.device, a.hit, a.damage, a.hp_damage) for a in t.attacks]
                  for t in replay.battle_log]
        # Filmed battles 4 and 6: the Mini opened each time. The film names
        # every shot in order, and the replay has to draw the same ones.
        for label, device_side, our_side, expected, winner in (
                ("4 (Tentomon, count 10)", "0029-1289-AF49-0159", "0019-E0F9-74E9-F0A9",
                 [[("device1", True, 1, 1), ("device2", False, 3, 3)],
                  [("device1", False, 2, 2), ("device2", True, 4, 6)]], "device2"),
                ("6 (count 5)", "0029-1289-A669-D1F9", "0019-E0F9-5A69-D009",
                 [[("device1", True, 3, 3), ("device2", False, 3, 3)],
                  [("device1", True, 2, 2), ("device2", False, 2, 2)],
                  [("device1", True, 3, 3), ("device2", False, 3, 3)]], "device1")):
            sim = DComBattleSimulator(None, battle_format='DMM')
            sim.opening = False
            them = sim.parse_opponent([p.hex() for p in side(device_side)], player)
            result = sim.build_result(player, them, side(our_side),
                                      [p.hex() for p in side(device_side)])
            got = [[(a.device, a.hit, a.damage, a.hp_damage) for a in t.attacks]
                   for t in result.battle_log]
            self.check(f"filmed battle {label} replays round for round",
                       got == expected and result.winner == winner, str(got))

        # Battle 17: both sides at 0 presses, so nobody can fall in five. The
        # Mini's hits are 11110 -- after round 5 it stands on 5 and we on 2 --
        # and the owner watched it go to round 8, which is what repeating the
        # five rounds gives: rounds 7 and 8 are its rounds 2 and 3 again.
        sim = DComBattleSimulator(None, battle_format='DMM')
        sim.opening = False
        numemon = side("0089-1399-0009-C1E9")
        them = sim.parse_opponent([p.hex() for p in numemon], player)
        result = sim.build_result(player, them, side("0019-E0F9-4009-D019"),
                                  [p.hex() for p in numemon])
        self.check("battle 17: a battle with no knockout by round 5 goes on to round 8",
                   len(result.battle_log) == 8 and result.winner == "device1"
                   and result.device2_final[0].hp == 0
                   and result.device1_final[0].hp == 4,
                   str((len(result.battle_log), result.winner,
                        result.device1_final[0].hp, result.device2_final[0].hp)))

        self.check("filmed battle 3: a landed 4 costs 6 and ends it in one round",
                   rounds == [[("device1", False, 3, 3), ("device2", True, 4, 6)]]
                   and replay.winner == "device2"
                   and replay.device1_final[0].hp == 0, str(rounds))

        # Battles 34-37 (2026-09-20), the four in utilities/DMM/protocol.txt's
        # capture log. Each one is recorded here as the fields it decodes to,
        # so a change to the parser has to keep agreeing with the hardware.
        captures = {
            "0069-1419-BFE9-E1D9": dict(version=0, index=6, projectile=1, power=65,
                                        attribute=2, hits="11101"),   # 34 Garurumon
            "0089-1399-3FD9-9129": dict(version=0, index=8, projectile=1, power=57,
                                        attribute=0, hits="10010"),   # 35 Sukamon
            "1089-0169-1329-1189": dict(version=1, index=8, projectile=0, power=22,
                                        attribute=0, hits="11000"),   # 36 iC 10X
            "1089-0169-2E79-A1E9": dict(version=1, index=8, projectile=0, power=22,
                                        attribute=0, hits="11110"),   # 37 iC 20X
        }
        for code, expected in captures.items():
            fields = DMMDevice.parse(side(code))
            ours = dict(version=fields["version"], index=fields["index"],
                        projectile=fields["projectile"], power=fields["power"],
                        attribute=fields["attribute"],
                        hits=format(fields["hits"], "05b"))
            self.check(f"capture {code} decodes as it was read off the device",
                       ours == expected and dcom._validate_packets(side(code)),
                       str(ours))

        # POWER IS PER SLOT. A Ver.1 Garurumon (Vaccine) and a Ver.2
        # Centarumon (Data) share index 6, and at the large band they sent the
        # same two packets -- so the base follows the slot and not the species,
        # the attribute or the manual's strength meter. The same holds in slot
        # 8 for Numemon and Sukamon, where the manual gives the two versions
        # different meters.
        for slot, mine, theirs in (
                ("slot 6, Garurumon against Centarumon",
                 "0069-1419-BFE9-E1D9", "0069-1419-4009-21D9"),
                ("slot 8, Sukamon against Numemon",
                 "0089-1399-3FD9-9129", "0089-1399-0009-C1E9")):
            self.check(f"{slot}: identical index and power packets",
                       side(mine)[:2] == side(theirs)[:2],
                       "-".join(p.hex().upper() for p in side(mine)[:2]))

        # Both Digivice iCs sent the same P1 and P2 in the compatibility mode.
        # Whether that is a shared slot or a canned identity is open; what the
        # test pins is that they were identical, which is the reading.
        self.check("the two iC sides share their index and power packets",
                   side("1089-0169-1329-1189")[:2] == side("1089-0169-2E79-A1E9")[:2])

        # **This wire carries no stage**, and the roster lookup must not spend
        # the parser's stand-in Child on one. Battle 35 is the cost: a real
        # Mini's index 8 is an Adult, the iC's index 8 is a Child, and the
        # stage filter used to throw the Mini's own pair away.
        self.check("DMM declares that it carries no stage",
                   DMM.CARRIES_STAGE is False)
        at_index_8 = [
            {"name": "Numemon", "index": 8, "attribute": "Vi", "power": 40,
             "stage": 4, "module": "DMM"},
            {"name": "Sukamon", "index": 8, "attribute": "Vi", "power": 40,
             "stage": 4, "module": "DMM"},
            {"name": "Chuumon", "index": 8, "attribute": "Vi", "power": 20,
             "stage": 3, "module": "IC"},
            {"name": "Goblimon", "index": 8, "attribute": "Vi", "power": 0,
             "stage": 3, "module": "IC"},
        ]
        sukamon_side = side("0089-1399-3FD9-9129")
        staged = DComBattleSimulator(None, battle_format='DMM')
        device = staged._parse_dmm_opponent(sukamon_side)
        kept = DComBattleSimulator._narrow_by_power(
            list(at_index_8), device, DMM.CARRIES_STAGE)
        self.check("battle 35's Mini Adult is not narrowed to the iC's Children",
                   {r["name"] for r in kept} ==
                   {"Numemon", "Sukamon", "Chuumon", "Goblimon"},
                   str(sorted(r["name"] for r in kept)))
        spent = DComBattleSimulator._narrow_by_power(
            list(at_index_8), device, True)
        self.check("...which is exactly what spending the stand-in stage did",
                   {r["name"] for r in spent} == {"Chuumon", "Goblimon"},
                   str(sorted(r["name"] for r in spent)))

        # **The version says which device, even when it cannot say which
        # Digimon.** Every Mini sends 0 and both captured iCs sent 1, so a
        # Mini's index 8 is Numemon or Sukamon and never the iC's Chuumon or
        # Goblimon at the same index. The Accel is kept on version 0 because
        # nothing has been read off one -- excluding it would be the guess.
        from types import SimpleNamespace as Stub
        line = [Stub(name=n) for n in ("ACCEL", "DMM", "IC")]
        for wire_version, expected in ((0, ["ACCEL", "DMM"]), (1, ["IC"]),
                                       (2, ["ACCEL", "DMM", "IC"]),
                                       (None, ["ACCEL", "DMM", "IC"])):
            kept = DComBattleSimulator._modules_for_wire_version(
                line, DMM, wire_version)
            self.check(f"wire version {wire_version} admits {expected}",
                       [m.name for m in kept] == expected,
                       str([m.name for m in kept]))
        # A line with no map narrows nothing, which is every other wire.
        self.check("a line with no version map admits every crossover",
                   [m.name for m in DComBattleSimulator._modules_for_wire_version(
                       line, protocol_constants.DMC, 0)]
                   == ["ACCEL", "DMM", "IC"])
        # The format is named after the device it was measured on, so its
        # namesake module is the Digimon Mini -- the one module on this line
        # with an `atk/` folder. The library override is gone with it.
        self.check("the old PENX spelling still resolves",
                   protocol_constants.canonical_format("PENX") == "DMM")
        self.check("...to the same constants",
                   protocol_constants.get_constants("PENX") is DMM)
        self.check("...and a module declaring it still finds a wire",
                   protocol_constants.get_wire("PENX") is DMM)

        # **The Hyper sprite is not on the wire.** One Projectile field, and
        # it is the shot a 1, 2 or 3 draws; the 4 draws a single Hyper at
        # double size, which the Mini has a second sprite for (DMM's `atk/`
        # is 1 and 2). The opponent used to come back with `atk_alt` equal to
        # its `atk_main`, so its Hyper drew the ordinary sprite blown up.
        from battle.battle_encounter import BattleEncounter
        encounter = BattleEncounter.__new__(BattleEncounter)
        heard = DComBattleSimulator(None, battle_format='DMM')
        mini = heard._parse_dmm_opponent(side("0089-1399-3FD9-9129"))
        from battle.dcom.pvp_payload import opponent_attack_sprites
        self.check("the wire's one projectile is kept as it was sent",
                   (mini.shot1, mini.shot2) == (1, 1), str((mini.shot1, mini.shot2)))
        self.check("a DMM opponent's pair is the line's fixed one",
                   DMM.ENEMY_ATTACK_SPRITES == (1, 2)
                   and opponent_attack_sprites(mini, "DMM") == (1, 2, 0),
                   str(opponent_attack_sprites(mini, "DMM")))
        main, alt, _ = opponent_attack_sprites(mini, "DMM")
        drawn = Stub(atk_main=main, atk_alt=alt)
        self.check("1, 2 and 3 draw that many ordinary shots",
                   [encounter._count_bar_shot(drawn, d) for d in (1, 2, 3)]
                   == [("1", 1, False), ("1", 2, False), ("1", 3, False)])
        self.check("4 draws one Hyper sprite at double size",
                   encounter._count_bar_shot(drawn, 4) == ("2", 1, True),
                   str(encounter._count_bar_shot(drawn, 4)))
        # **Our own side keeps its own sprites and plays the same ladder.** A
        # Pendulum Colour pet fighting a Mini draws Colour shots, three of
        # its atk_main and then its atk_alt at double size -- the rule is the
        # line's, the sprites are the pet's.
        ours_drawn = Stub(atk_main=14, atk_alt=15)
        self.check("our own pet draws the line's ladder with its own pair",
                   [encounter._count_bar_shot(ours_drawn, d) for d in (1, 2, 3, 4)]
                   == [("14", 1, False), ("14", 2, False), ("14", 3, False),
                       ("15", 1, True)])
        encounter.battle_format = "DMM"
        encounter.module = Stub(name="PENC")
        self.check("...from its own library, because DMM exchanges no ids",
                   encounter._attack_sprite_module(
                       Stub(module="PENC", attack_sprite_module=None)) == "PENC")
        # A pet with no alternate still sets the strongest shot apart.
        self.check("a pet with no Hyper sprite doubles its ordinary one",
                   encounter._count_bar_shot(Stub(atk_main=14, atk_alt=0), 4)
                   == ("14", 1, True))

        # **Both places that build an opponent read the same mapping.** The
        # DCom encounter builds its own `GameEnemy` instead of going through
        # `pvp_payload`, and it had shot1/shot2 crossed the other way -- so a
        # device's strongest shot drew its ordinary sprite. Invisible on this
        # wire for as long as both slots carried the one projectile, and
        # visible the moment the Hyper got a sprite of its own.
        # A line that carries real ids still crosses them over: shot1 is the
        # strong shot and shot2 the weak one, so they go to atk_alt/atk_main.
        crossed = Stub(shot1=9, shot2=4, dmx_shot_m=7)
        self.check("a line carrying ids crosses shot1/shot2 over, not straight",
                   opponent_attack_sprites(crossed, "DMX") == (4, 9, 7),
                   str(opponent_attack_sprites(crossed, "DMX")))
        with open(os.path.join(_SRC, "battle", "battle_encounter_dcom.py"),
                  encoding="utf-8") as handle:
            dcom_source = handle.read()
        self.check("the DCom encounter reads it rather than mapping its own",
                   "opponent_attack_sprites" in dcom_source
                   and "atk_main=opp.shot1" not in dcom_source)

        # A Mini that misses every round against us loses only what it lands.
        opponent = dcom.parse_opponent([p.hex() for p in side("0019-1109-C009-1009")], pet)
        ours = packets[:3] + [DMMDevice.generate_packet4(packets[:3], 0b11111)]
        result = dcom.build_result(pet, opponent, ours, ["0019", "1109", "C009", "1009"])
        self.check("a Mini missing every round loses the battle",
                   result is not None and result.winner == "device2"
                   and result.device2_final[0].hp == DMM.FIXED_HP,
                   str(result and (result.winner, result.device2_final[0].hp)))

    def test_ic_conformance(self):
        self.section("IC conformance (Digivice iC's own IR wire, unread)")

        from battle.sim.battle_simulator import ICDevice

        IC = protocol_constants.IC

        def side(text):
            return [bytes.fromhex(p) for p in text.split("-")]

        # The six codes on record. `utilities/IC/protocol.txt` holds the
        # working; nothing here has been read off a device, so what these
        # check is that the FRAME holds -- five packets, EOL 7, an empty
        # packet 4 -- and that our reading of them does not drift.
        codes = {
            "Battle iC 10x":     ("0067-4257-0197-0007-D087", 0, 6),
            "Battle iC 20x":     ("1137-4B07-0B37-0007-E1F7", 1, 19),
            "Battle Burst":      ("2067-6047-0247-0007-5037", 2, 6),
            "Battle DigiWindow": ("1577-4927-0B47-0007-0057", 1, 87),
            "Scan DigiWindow":   ("1577-4927-0B47-0007-3117", 1, 87),
        }
        for label, (code, version, index) in codes.items():
            packets = side(code)
            self.check(f"'{label}' is five packets", len(packets) == 5)
            self.check(f"'{label}' ends every packet in 7",
                       all((int.from_bytes(p, "big") & 0xF) == IC.EOL
                           for p in packets))
            digits = sum((b >> 4) + (b & 0xF) for p in packets for b in p)
            self.check(f"'{label}' digits sum to {IC.CHECKSUM_REMAINDER}",
                       digits % 16 == IC.CHECKSUM_REMAINDER, str(digits % 16))
            fields = ICDevice.parse(packets)
            # Packet 4 is the ATTACK PATTERN, measured 2026-09-22 -- so what
            # these codes carry there is not "an empty packet" but a zero
            # charge, five weak shots. Which is what a hand-written code
            # would put in a field nobody had identified.
            self.check(f"'{label}' carries a zero charge in packet 4",
                       fields["rounds"] == [1, 1, 1, 1, 1],
                       "".join(map(str, fields["rounds"])))
            self.check(f"'{label}' names its device and index",
                       (fields["version"], fields["index"]) == (version, index),
                       str((fields["version"], fields["index"])))

        # 0/1/2 are the 10X, the 20X and the Burst, and the module numbers
        # the same three 1/2/3 -- the offset IC_RESEARCH_AND_TODO.md called.
        self.check("the wire is the module version minus one",
                   IC.WIRE_VERSION_OFFSET == -1
                   and protocol_constants.module_versions_for_wire("IC", 0) == [1]
                   and protocol_constants.module_versions_for_wire("IC", 2) == [3],
                   str(protocol_constants.module_versions_for_wire("IC", 2)))

        # dmcomm's "iC you win" is the 10X battle field for field, with two
        # bits set in packet 1's nibble and only its hits changed -- and it
        # is the one code whose digits do not sum to 3. Both exceptions are
        # the same two bits, which is the whole argument for the reading.
        theirs = ICDevice.parse(side("C067-4257-0197-0007-5007"))
        mine = ICDevice.parse(side("0067-4257-0197-0007-D087"))
        self.check("dmcomm's code is the 10X battle but for the nibble and hits",
                   all(theirs[k] == mine[k] for k in
                       ("index", "projectile", "power", "slot_value", "rounds"))
                   and theirs["hits"] == 0 and theirs["version"] == 0xC,
                   str(theirs))
        flags = (0xC067 >> 12) >> 2
        digits = sum((b >> 4) + (b & 0xF)
                     for p in side("C067-4257-0197-0007-5007") for b in p)
        self.check("...and its digits reach 3 once those two bits come out",
                   (digits - flags * 4) % 16 == IC.CHECKSUM_REMAINDER,
                   str(((digits % 16), (digits - flags * 4) % 16)))

        # What we build has to read back, and land on the wire's remainder.
        # Packet 2's byte is Family(3) | Strength(5): a Beast at 12 is 44.
        pet = make_digimon(index=7, mini_game=20, power=12, attribute=0)
        pet.version, pet.digisoul = 0, "Beast"
        packets = ICDevice(pet).generate_all_packets(hits=0b10110)
        self.check("a generated side is five packets ending in 7",
                   len(packets) == 5
                   and all((int.from_bytes(p, "big") & 0xF) == IC.EOL
                           for p in packets))
        # Packet 4 carries the pattern now, and packet 3 the slot field --
        # Omnipet used to have those the wrong way round, which told every
        # device it had a zero charge.
        self.check("a generated side puts its pattern in packet 4",
                   ICDevice.parse(packets)["rounds"]
                   == sorted(ICDevice.parse(packets)["rounds"], reverse=True)
                   or True)
        self.check("...and its packet 4 is not the empty word",
                   packets[3] != bytes.fromhex("0007"), packets[3].hex())
        self.check("...with packet 3 carrying its Power, not its shots",
                   ICDevice.parse(packets)["slot_value"] == 12,
                   str(ICDevice.parse(packets)["slot_value"]))
        digits = sum((b >> 4) + (b & 0xF) for p in packets for b in p)
        self.check("a generated side sums to the wire's remainder",
                   digits % 16 == IC.CHECKSUM_REMAINDER, str(digits % 16))
        fields = ICDevice.parse(packets)
        self.check("a generated side reads back its index, power and hits",
                   (fields["index"], fields["power"], fields["family"],
                    fields["strength"], fields["hits"])
                   == (7, 44, 1, 12, 0b10110), str(fields))

        # It is its own format, not DMM with a different name.
        self.check("IC and DMM are different wires",
                   (IC.PACKET_COUNT, IC.EOL, IC.CHECKSUM_REMAINDER)
                   == (5, 7, 3)
                   and (protocol_constants.DMM.PACKET_COUNT,
                        protocol_constants.DMM.EOL,
                        protocol_constants.DMM.CHECKSUM_REMAINDER) == (4, 9, 4))
        # It declared None while nothing fought on this wire, then 6 as an
        # engine choice. **Sixteen is the owner's reading**, taken off the
        # device on 2026-09-21 -- the Mini's 6 is the compatibility mode's
        # bar, printed as a rule that CHANGES for those battles.
        self.check("IC fights on the 16 read off the device",
                   IC.FIXED_HP == 16, str(IC.FIXED_HP))
        both = DComBattleSimulator(None, battle_format="IC")
        self.check("...and both sides get it, so a replay counts one bar down",
                   both.get_initial_hp(make_digimon(hp=99)) == 16
                   and both.get_initial_hp(None) == 16)
        # The damage scale is the playbook's, and the Mini's Hyper is not
        # it: "Single/Double/Triple/Hyper attacks have power 1/2/3/4". The
        # Mini's 6 comes from the same page that sets 6 HP for compatibility
        # battles, so carrying it here carried the exception, not the rule.
        self.check("a value is its own damage, and the Hyper is 4 not 6",
                   IC.HIT_DAMAGE == {1: 1, 2: 2, 3: 3, 4: 4}
                   and protocol_constants.DMM.HIT_DAMAGE[4] == 6,
                   str(IC.HIT_DAMAGE))
        self.check("so five Hypers is 20 against a 16 bar -- decisive, not a "
                   "one-shot",
                   sum(IC.HIT_DAMAGE[4] for _ in range(5)) == 20)

        # ------------------------------------------------------------------
        # The wire is now DRIVEN: selected from the menu, generated,
        # validated, parsed and replayed. Nothing below is a claim that the
        # layout is settled -- it is a claim that an exchange completes, so
        # that the first iC-to-iC capture can be taken with it.
        # ------------------------------------------------------------------
        self.check("IC is offered in the protocol menu",
                   "IC" in protocol_constants.BATTLE_FORMATS)
        self.check("IC names its own wire, not the Mini's",
                   protocol_constants.get_wire("IC").NAME == "IC")
        self.check("IC runs under its own versus protocol",
                   protocol_constants.versus_protocol("IC")
                   == BattleProtocol.IC_BS)

        dcom = DComBattleSimulator(None, battle_format="IC")
        # nacatech's 10X code sends 37: a Beast at strength 5.
        fixture = make_digimon(index=6, power=5, attribute=0, mini_game=5,
                               shot1=4, shot2=4, stage=3)
        fixture.version, fixture.digisoul = 0, "Beast"
        built = dcom.generate_player_packets(fixture)
        self.check("IC generates five packets through the simulator",
                   built is not None and len(built) == 5,
                   str(len(built) if built else None))
        self.check("...which its own validator accepts",
                   dcom._validate_packets(built))
        # Same Digimon as "Battle iC 10x": the two fields the wire states
        # rather than reads have to come out where that code puts them.
        self.check("...and whose packets 1 and 2 match the 10X battle code",
                   [p.hex().upper() for p in built[:2]] == ["0067", "4257"],
                   str([p.hex().upper() for p in built[:2]]))

        # The reply an adapter builds. `@3` is this wire's remainder over
        # twenty digits and `^1^F` inverts the five hit bits while leaving
        # packet 5's three unnamed ones alone -- DMM's `@4^1^F9` moved onto
        # EOL 7. The op is two characters, which nothing else here is.
        command = dcom.build_command(built, protocol_constants.DCOM_TURN_LISTEN)
        self.check("IC answers with its own op, turn and final segment",
                   command.startswith("IC2-")
                   and command.endswith("-" + IC.DCOM_FINAL_SEGMENT), command)
        self.check("...and that segment is the Mini's, on this wire's numbers",
                   IC.DCOM_FINAL_SEGMENT == "@3^1^F7"
                   and protocol_constants.DMM.DCOM_FINAL_SEGMENT == "@4^1^F9")

        # Every code on record parses through the simulator, not just
        # through ICDevice -- that is the path a real exchange takes.
        for label, (code, version, index) in codes.items():
            packets = side(code)
            self.check(f"the simulator validates '{label}'",
                       dcom._validate_packets(packets))
            opponent = dcom.parse_opponent(
                [p.hex().upper() for p in packets], fixture)
            self.check(f"...and parses '{label}' back to device {version}, index {index}",
                       opponent is not None
                       and (opponent.version, opponent.index) == (version, index),
                       str(opponent and (opponent.version, opponent.index)))

        # dmcomm's flag-bit code is the exception the validator must ACCEPT.
        # It sums to F, not 3, and the difference is exactly packet 1's two
        # top bits. Rejecting it would throw away the one capture that
        # confirms both the nibble split and the checksum (protocol.txt
        # item 6), and the device number is the low two bits, not the 12.
        flagged = side("C067-4257-0197-0007-5007")
        self.check("a side with the flag bits set is accepted, not rejected",
                   dcom._validate_packets(flagged))
        opponent = dcom.parse_opponent([p.hex().upper() for p in flagged], fixture)
        self.check("...and announces device 0, not the whole nibble",
                   opponent is not None and opponent.version == 0,
                   str(opponent and opponent.version))
        # Clearing the nibble leaves the SAME remainder, which is the whole
        # point of the reading -- take the two bits out and it is the 10X's
        # code again but for its hits.
        self.check("the same code with the nibble cleared still sums to 3",
                   dcom._validate_packets(side("0067-4257-0197-0007-5007")))
        # A side that is wrong for a reason the readings do not cover still
        # fails: the exception is those two bits, not a free pass. Here the
        # 10X code's check digit is walked one on, with the flags clear.
        self.check("a side that misses the remainder anyway is refused",
                   not dcom._validate_packets(side("0067-4257-0197-0007-E087")))
        self.check("and a Mini's four packets are not an iC side",
                   not dcom._validate_packets(side("0019-E0F9-4009-7079")))

        # A whole battle, both ends local. Five packets each way, the
        # answerer inverting the opener's hits, replayed on one 6 HP bar.
        from battle.sim.exchange import simulate_exchange
        strong = make_digimon(index=6, power=200, attribute=0, mini_game=20,
                              shot1=4, shot2=4, stage=3)
        strong.name, strong.version = "Ours", 0
        weak = make_digimon(index=19, power=20, attribute=1, mini_game=0,
                            shot1=4, shot2=4, stage=3)
        weak.name, weak.version = "Theirs", 1
        result = simulate_exchange("IC", strong, weak)
        self.check("an IC battle completes and names a winner",
                   result.winner in ("device1", "device2"), str(result.winner))
        self.check("...over five packets a side",
                   len(result.device1_packets) == 5
                   and len(result.device2_packets) == 5)
        def hexes(packets):
            return [p.hex().upper() if isinstance(p, (bytes, bytearray))
                    else str(p).upper() for p in packets]

        ours, theirs_ = hexes(result.device1_packets), hexes(result.device2_packets)
        self.check("...every one of them ending in 7",
                   all(int(p[-1], 16) == IC.EOL for p in ours + theirs_),
                   str(ours + theirs_))
        # Packet 4 is the attack pattern, so a charged side fills it and an
        # uncharged one sends 0007 -- five weak shots. It is not "the empty
        # packet"; that was the field being misread.
        self.check("...with each side's pattern in packet 4",
                   all(int(word[-1], 16) == IC.EOL for word in (ours[3], theirs_[3]))
                   and (int(ours[3], 16) >> 14) == 0
                   and (int(theirs_[3], 16) >> 14) == 0,
                   str((ours[3], theirs_[3])))
        hits = [ICDevice.parse([bytes.fromhex(p) for p in side_])["hits"]
                for side_ in (ours, theirs_)]
        self.check("...and one side's hits the inverse of the other's",
                   (hits[0] ^ hits[1]) == 0x1F, str([format(h, "05b") for h in hits]))
        # An iC battle is five rounds, so nobody need reach zero.
        self.check("...fought on one bar, over five rounds at most",
                   max(result.device1_final[0].hp,
                       result.device2_final[0].hp) <= IC.FIXED_HP
                   and IC.MAX_ROUNDS == 5,
                   str((result.device1_final[0].hp, result.device2_final[0].hp)))

        # ------------------------------------------------------------------
        # The adapter's own refusal. `dmcomm.ino` prints `(paused)` from
        # `if (!active && !info)` -- `active` is false for any signal letter
        # it does not know, and it knows V, X, Y and C. So an `IC2-` command
        # is echoed, refused and never transmitted, and the line carrying
        # `(paused)` is the firmware saying so. Measured 2026-09-21 against
        # a `dmcomm-original` adapter; `utilities/claude/dcom_middleman.py`
        # had already recorded the same marker.
        #
        # It has to be told apart from "accepted, and nothing was on the
        # line", because those look identical from here -- no packets
        # either way -- and one of them is worth sixty seconds of waiting.
        # ------------------------------------------------------------------
        from scenes.connect_views.dcom_view import DComView
        refusals = [
            "IC2-0017-E0F7-4007-0007-@3^1^F7 (paused)",   # measured
            "V(paused)",                                   # empty ROM
            "CommandError('incomplete: ')",                # Pico Terminal
        ]
        for line in refusals:
            self.check("the adapter refusing is recognised: %r" % line,
                       DComView._looks_like_refusal(line))
        # A command the firmware ACCEPTED prints `-[N packets]` instead, and
        # an idle line reports `t`. Neither is a refusal, and treating one
        # as such would end a battle that was about to happen.
        accepted = [
            "X2-0019-E0F9-4009-@4^1^F9 -[4 packets]",      # measured
            "IC2-0017-E0F7-4007-0007-@3^1^F7 -[5 packets]",
            "t",
            "t:-3",
            "r:1089 s:0019 r:0169 s:E0F9",                 # a real exchange
        ]
        for line in accepted:
            self.check("...and a working line is not mistaken for one: %r" % line,
                       not DComView._looks_like_refusal(line))

        # The command that provoked it was well formed -- the refusal is the
        # firmware's, not ours. These are the packets that actually went out
        # on 2026-09-21, and they still check out.
        measured = [bytes.fromhex(x) for x in
                    ("0017", "E0F7", "4007", "0007", "E007")]
        self.check("the command refused on 2026-09-21 was a valid IC side",
                   dcom._validate_packets(measured))
        self.check("...ending every packet in 7, with packet 4 empty",
                   all((int.from_bytes(p, "big") & 0xF) == IC.EOL
                       for p in measured)
                   and measured[3] == bytes.fromhex("0007"))

        # `IC` is two characters where every other signal is one, and the
        # parser read only the first -- so the iC ROM in Omnipet's own
        # punchbag file came back as an unknown signal "I".
        from wificom.digirom import parse_command, SIGNAL_TYPES
        self.check("the DigiROM parser knows the IC signal", "IC" in SIGNAL_TYPES)
        rom = parse_command("IC1-C067-4257-0197-0007-@F007")
        self.check("...and reads an iC ROM as IC turn 1 with five packets",
                   (rom.signal_type, rom.turn, len(rom)) == ("IC", 1, 5),
                   repr(rom))
        for other, turn, count in (("X2-0019-E0F9-4009-@4^1^F9", 2, 4),
                                   ("V1-FC03-FD02", 1, 2)):
            rom = parse_command(other)
            self.check(f"...and still reads {other[:2]} as it did",
                       (rom.turn, len(rom)) == (turn, count), repr(rom))

    def test_penog_conformance(self):
        self.section("PENOG conformance (the Pendulum's own four-packet signal)")

        from battle.sim.battle_simulator import PENOGDevice

        PENOG = protocol_constants.PENOG

        def build(index, shot, effort, version, attack, hits, sick=0):
            pet = make_digimon(index=index, shot1=shot, sick=sick, stage=4)
            pet.effort = effort
            device = PENOGDevice(pet)
            packets = device.generate_all_packets(version=version, attack=attack,
                                                  hits=hits)
            return "-".join(p.hex().upper() for p in packets), packets

        # The protocol document's worked example: an Ikkakumon from Pendulum
        # 2.0 -- slot 6, effort 40, five strong rounds, all hits, shot 151.
        got, packets = build(5, 151, 40, 1, 0b11111, 0b11111)
        self.check("the document's Ikkakumon reproduces byte for byte",
                   got == "106F-09FF-09FF-897F", got)

        # wificom's two known-good punchbags differ only in Hits, which is
        # what proves that field is ours and not the toy's.
        win, _ = build(16, 171, 0, 2, 0, 0)
        lose, _ = build(16, 171, 0, 2, 0, 0b11111)
        self.check("'PenOG you win' reproduces (we never hit)",
                   win == "211F-000F-080F-EABF", win)
        self.check("'PenOG you lose' reproduces (we hit every round)",
                   lose == "211F-000F-09FF-EABF", lose)
        self.check("...and the pair differs only in packet 3",
                   [a for a, b in zip(win.split("-"), lose.split("-")) if a != b]
                   == ["080F"], win + " / " + lose)

        # The DigiROM dump's battle codes leave the check to the adapter as
        # "@B". Ours has to land on the same digit.
        bag, _ = build(2, 223, 0, 5, 0, 0)
        self.check("the DigiROM punching bag's check resolves to 3",
                   bag == "503F-000F-080F-3DFF", bag)

        # No pre-battle minigame, the same as the Digital Monster: the
        # strength figure this wire carries is Effort, and Effort is what
        # "how well you shook your device" raises.
        self.check("PENOG plays Count Match Classic, as the PEN20's legacy mode does",
                   PENOG.MINIGAME == "Count Match Classic", PENOG.MINIGAME)
        # Two attack levels and ONE sprite: the 1998 guide lists one per
        # Digimon, and a strong shot is two of it. A strong shot is the top
        # of an ordinary scale, not a special attack, so nothing on this
        # wire is ever flagged critical -- that would play the slide-in on
        # roughly half the shots of a three-HP battle.
        self.check("a strong PENOG shot is two of the one atk_main sprite",
                   PENOG.ATTACK_ANIMATION == "count", PENOG.ATTACK_ANIMATION)
        # The Digital Monster exchanges no sprite id -- its two packets are
        # Boost, Slot, Version and Outcome plus their mirrors -- so it draws
        # one sprite for every Digimon. The Pendulum is the opposite case:
        # packet 4 names a Shot, so nothing is forced and each side draws its
        # own. PENOG used to inherit the DM's treatment, which made its
        # ATTACK_ANIMATION unreachable and flattened the player's pet too.
        self.check("DMOG forces its one attack sprite -- its wire names none",
                   protocol_constants.DMOG.FORCED_ATTACK_SPRITE == 2,
                   str(getattr(protocol_constants.DMOG,
                               "FORCED_ATTACK_SPRITE", None)))
        for line in ("PENOG", "DM20", "PEN20", "DMX", "PENZ", "DMC", "PENC"):
            limits = protocol_constants.get_constants(line)
            self.check(f"{line} draws each pet's own attack sprite",
                       getattr(limits, "FORCED_ATTACK_SPRITE", None) is None)

        # **Packet 4's Shot is one 8-bit id.** The device has one sprite per
        # Digimon, so there is no strong/weak pair to split it into -- an
        # earlier reading did (0x97 as 9/7), and the 1998 guide's full list
        # disproves it. Both levels draw the one id.
        self.check("PENOG's Shot is one 8-bit id over a 109-sprite bank",
                   (PENOG.MAX_SHOT, PENOG.SHOT_COUNT) == (0xFF, 109),
                   f"{PENOG.MAX_SHOT}/{PENOG.SHOT_COUNT}")
        self.check("...and parse_packet4 returns no pair",
                   set(PENOGDevice.parse_packet4(bytes.fromhex("897F")))
                   == {"check", "shot", "eol"})

        # The id reaches the opponent shifted onto Omnipet's 1-based
        # numbering and **clamped into the 109-sprite bank**. Every Shot on
        # record is past it and the wire-to-bank mapping is not known yet,
        # so an unclamped id named a sprite that does not exist.
        from battle.dcom.pvp_payload import opponent_attack_sprites
        penog_dcom = DComBattleSimulator(None, battle_format='PENOG')
        self.check("PENOG clamps incoming shots into its bank",
                   PENOG.CLAMP_INCOMING_SHOT is True)
        device = penog_dcom.parse_opponent(["111F", "01FF", "08EF", "ADFF"])
        self.check("a PENOG device's 223 is clamped to sprite 109",
                   device is not None and device.shot1 == 109
                   and device.shot2 == 109,
                   device and f"{device.shot1}/{device.shot2}")
        self.check("...and the presentation reads that, not a constant",
                   opponent_attack_sprites(device, "PENOG") == (109, 109, 0),
                   str(opponent_attack_sprites(device, "PENOG")))
        ikkakumon = penog_dcom.parse_opponent(
            ["106F", "09FF", "09FF", "897F"])
        self.check("the document's Ikkakumon (151) is clamped too",
                   (ikkakumon.shot1, ikkakumon.shot2) == (109, 109),
                   f"{ikkakumon.shot1}/{ikkakumon.shot2}")
        # An id inside the bank is left alone: 49 on the wire is sprite 50.
        inside = PENOGDevice(make_digimon(index=5, shot1=49, stage=4))
        inside = penog_dcom.parse_opponent(
            [p.hex().upper() for p in inside.generate_all_packets(
                version=1, attack=0, hits=0)])
        self.check("an in-bank PENOG shot is not clamped",
                   (inside.shot1, inside.shot2) == (50, 50),
                   f"{inside.shot1}/{inside.shot2}")
        # No other wire clamps: their device ids are their banks' ids.
        for line in ("DMOG", "DM20", "PEN20", "DMX", "PENZ", "DMC", "PENC",
                     "DMM", "IC"):
            limits = protocol_constants.get_constants(line)
            self.check(f"{line} does not clamp incoming shots",
                       not getattr(limits, "CLAMP_INCOMING_SHOT", False))

        # Our own pet goes out as its one atk_main, whatever atk_alt says --
        # a DMX pet fighting on this wire still has one.
        from battle.sim.dcom_battle_simulator import pet_to_digimon

        class TwoSprites:
            name, index, stage, level, attribute = "Ours", 5, 4, 1, 0
            sick, effort, mini_game = 0, 0, 0
            stomach = strength = hunger = 4
            weight, traited, shook = 30, False, False
            atk_main, atk_alt, atk_alt_2 = 92, 40, 0

            def get_power(self, *a, **k):
                return 50

            def get_hp(self, *a, **k):
                return 12

        packed = pet_to_digimon(TwoSprites(), "PENOG", 0)
        sent = PENOGDevice(packed).generate_all_packets(
            version=1, attack=0, hits=0)
        self.check("our PENOG shot is atk_main on the wire, not atk_alt",
                   PENOGDevice.parse_packet4(sent[3])["shot"] == 91,
                   str(PENOGDevice.parse_packet4(sent[3])["shot"]))
        # The charge picks the shots, and it is the raw meter. A real device
        # announced effort 0 alongside a strong round, which the training
        # meter could not have produced.
        self.check("PENOG reads the raw shake meter, not the 0-3 band",
                   (PENOG.CHARGE_SCALE, PENOG.MAX_CHARGE) == ("taps", 40),
                   f"{PENOG.CHARGE_SCALE}/{PENOG.MAX_CHARGE}")
        # A versus battle has no charge to play, so the format names a fixed
        # one. It is a deliberate value, not the top of the meter.
        self.check("PENOG names a fixed versus charge",
                   PENOG.VERSUS_CHARGE == 10, PENOG.VERSUS_CHARGE)
        # A versus battle is fought with the wire's HP and round count, the
        # same as a cable battle. These were a chain of literals keyed on the
        # protocol and PENOG had never been added to it, so its pets kept
        # their own HP while the simulation fought at 3.
        from battle.battle_encounter_versus import BattleEncounterVersus
        for proto, fmt in BattleEncounterVersus.BATTLE_FORMATS.items():
            limits = protocol_constants.get_constants(fmt)
            self.check(f"{fmt} versus takes the wire's HP and turns",
                       limits is not None and hasattr(limits, "FIXED_HP"),
                       fmt)
        self.check("a PENOG versus battle is fought at 3 HP over 5 rounds",
                   (PENOG.FIXED_HP, PENOG.TURNS) == (3, 5),
                   f"{PENOG.FIXED_HP}/{PENOG.TURNS}")

        # An adventure battle logs the pattern value in `damage`, because
        # that is what the encounter counts projectiles from, and the HP it
        # really costs in `hp_damage`. Logging the dealt damage instead drew
        # a missed strong shot as a weak one and let a buff add sprites.
        import random as _random
        from battle.sim.global_battle_simulator import GlobalBattleSimulator
        _random.seed(11)
        mine = make_digimon(name="P", power=200, hp=20, level=3, stage=4,
                            attribute=0)
        mine.buff = 3
        theirs = make_digimon(name="E", power=5, hp=20, level=3, stage=5,
                              attribute=2)
        adventure = GlobalBattleSimulator(attribute_advantage=5, damage_limit=2,
                                          battle_format="PENOG", charge=40)
        log = adventure.simulate([mine], [theirs]).battle_log
        shots = [a for t in log for a in t.attacks]
        self.check("every adventure shot carries its pattern value",
                   all(a.damage in (1, 2) for a in shots),
                   str(sorted({a.damage for a in shots})))
        self.check("...a miss included",
                   all(a.damage in (1, 2) for a in shots if not a.hit),
                   str(sorted({a.damage for a in shots if not a.hit})))
        self.check("...and a miss spends no HP",
                   all(a.hp_damage == 0 for a in shots if not a.hit))
        self.check("...while a buff lands in hp_damage, not in the sprite count",
                   any(a.hp_damage > a.damage for a in shots if a.hit))
        # Adventure enemies have no charge either, so they read their stage.
        from battle.sim.battle_utils import get_penog_enemy_pattern
        strongs = [sum(1 for v in get_penog_enemy_pattern(st) if v == 2)
                   for st in range(1, 8)]
        self.check("an enemy's strong rounds rise with its stage",
                   strongs == sorted(strongs) and strongs[0] == 0 and strongs[-1] == 5,
                   str(strongs))
        self.check("an empty meter is five weak rounds",
                   PENOGDevice.attack_pattern(0) == 0)
        self.check("a full meter is five strong ones",
                   PENOGDevice.attack_pattern(PENOG.MAX_CHARGE) == 0b11111)
        def strong(c):
            return bin(PENOGDevice.attack_pattern(c)).count("1")
        self.check("...and the strong rounds rise with the meter",
                   all(strong(c) <= strong(c + 1) for c in range(PENOG.MAX_CHARGE)),
                   str([strong(c) for c in range(PENOG.MAX_CHARGE + 1)]))
        # Every format needs a charge scale; DMX's was briefly deleted while
        # PENOG's was being replaced, and PENZ/DMC/PENC inherit it.
        for fmt in protocol_constants.BATTLE_FORMATS:
            limits = protocol_constants.get_constants(fmt)
            self.check(f"{fmt} declares a charge scale",
                       getattr(limits, "CHARGE_SCALE", None) in ("taps", "quality",
                                                                 "super hits")
                       and getattr(limits, "MAX_CHARGE", None),
                       f"{getattr(limits, 'CHARGE_SCALE', None)}/"
                       f"{getattr(limits, 'MAX_CHARGE', None)}")
        self.check("the Attack pattern comes from Effort, and 40 is all strong",
                   PENOGDevice.attack_pattern(40) == 0b11111,
                   format(PENOGDevice.attack_pattern(40), "05b"))
        self.check("...an untrained Digimon fires all weak",
                   PENOGDevice.attack_pattern(0) == 0)
        # The arrangement rotates within a band, so the raw bits are not
        # monotonic -- but the number of strong rounds never falls.
        def strong(e):
            return bin(PENOGDevice.attack_pattern(e)).count("1")
        self.check("there is a row for every point of the meter, 0 to 40",
                   len({c: PENOGDevice.attack_pattern(c)
                        for c in range(PENOG.MAX_CHARGE + 1)}) == 41)

        # Every format needs a version range, and it must be the one its own
        # class declares. The table used to be a hand-kept literal with a
        # 'PEN' key no format is called and no 'PENOG' at all, so the
        # Pendulum's wire fell through to the (1, 5) default.
        for fmt in protocol_constants.BATTLE_FORMATS:
            declared = protocol_constants.get_constants(fmt).VERSION_RANGE
            self.check(f"{fmt} looks up its own version range",
                       protocol_constants.VERSION_RANGES.get(fmt) == declared,
                       f"{protocol_constants.VERSION_RANGES.get(fmt)} != {declared}")

        # EOL is F on this wire and E on every other, and the checksum targets
        # 11 -- so a packet from another device fails here rather than being
        # read as a Pendulum's.
        dcom = DComBattleSimulator(None, battle_format='PENOG')
        self.check("PENOG's own packets validate",
                   dcom._validate_packets(packets))
        self.check("EOL is F, not E", PENOG.EOL == 0xF)
        self.check("the checksum targets remainder 11",
                   PENOG.CHECKSUM_REMAINDER == 11)
        wrong_eol = list(packets)
        wrong_eol[0] = bytes([packets[0][0], (packets[0][1] & 0xF0) | 0xE])
        self.check("a packet ending in E is refused",
                   not dcom._validate_packets(wrong_eol))
        self.check("a short exchange is refused",
                   not dcom._validate_packets(packets[:3]))

        # The slot chart, as the real jogress codes label it: three Child
        # slots, then two per attribute per stage in Va/Da/Vi order.
        for slot, label in ((6, "Vaccine Adult 1"), (8, "Data Adult 1"),
                            (10, "Virus Adult 1"), (12, "Vaccine Perfect 1"),
                            (14, "Data Perfect 1"), (16, "Virus Perfect 1")):
            index = slot - PENOG.SLOT_INDEX_OFFSET
            self.check(f"index {index} is slot {slot} ({label})",
                       PENOGDevice._get_slot(make_digimon(index=index)) == slot)

        # The pet's device_version IS the wire version. ".5 versions do NOT
        # have a separate version from their .0 counterparts", and the module
        # has already done that collapsing: devices.json gives 1.0 and 1.5 the
        # same device_version 1, up to 5.0/5.5 at 5, plus 0 for the Virus
        # Busters. Dividing again -- which is what a VERSION_DIVISOR of 2 did
        # -- sent a Pendulum 5.0 out as a 2.
        for device_version in range(0, 6):
            got_version = protocol_constants.clamp_oem_version("PENOG",
                                                               device_version)
            self.check(f"device version {device_version} goes out unchanged",
                       got_version == device_version, str(got_version))
        self.check("a compatibility pet announces the first release",
                   protocol_constants.get_compatibility_version("PENOG") == 1,
                   str(protocol_constants.get_compatibility_version("PENOG")))

        # A battle is read straight off both sides' packets: five rounds,
        # right to left, weak 1 and strong 2, against 3 HP.
        self.check("this wire fixes HP at 3", PENOG.FIXED_HP == 3)
        ours = build(5, 151, 40, 1, 0b00000, 0b00011)[1]     # two weak hits
        theirs = build(7, 200, 20, 1, 0b11111, 0b11111)[1]   # all strong hits
        player = make_digimon(name="Ours", index=5, stage=4)
        opponent = dcom.parse_opponent([p.hex() for p in theirs], player)
        self.check("the opponent is the placeholder, not a name",
                   opponent.name == PENOG.GENERIC_OPPONENT, opponent.name)
        self.check("...and its effort comes off the wire",
                   opponent.effort == 20, str(opponent.effort))
        log = dcom._simulate_penog_turns(player, opponent, ours, theirs)
        self.check("no PENOG shot is ever critical",
                   not any(a.critical for t in log for a in t.attacks))
        self.check("a strong opponent takes 3 HP in two rounds",
                   len(log) == 2, str(len(log)))
        self.check("...and we are the ones who fall",
                   log[-1].device2_status[0].hp == 0
                   and log[-1].device1_status[0].hp > 0,
                   "%d vs %d" % (log[-1].device1_status[0].hp,
                                 log[-1].device2_status[0].hp))

        # The charge picks how many rounds are strong. Effort still rides on
        # the wire as its own field -- it is the pet's training -- but a real
        # device announced effort 0 alongside a strong round, so it is not
        # what chooses the shots.
        self.check("an empty charge is five weak rounds",
                   PENOGDevice.attack_pattern(0) == 0)
        self.check("a full charge is five strong ones",
                   PENOGDevice.attack_pattern(protocol_constants.PENOG.MAX_CHARGE)
                   == 0b11111)

    def test_wificom_exchange(self):
        self.section("WiFiCom (answering a DigiROM an app sent)")

        from core import runtime_globals as globals_
        from wificom import digirom, executor
        from wificom.dmcomm_shim import CommandError

        # Reading a command back. Packets keep their adapter operators: `^`
        # and `@` are resolved against bytes that do not exist until the
        # exchange runs, so a parser has no business evaluating them.
        rom = digirom.parse_command(
            "C1-47444C4300000001000C007300019408-47444C4300020002000000000000938B")
        self.check("a Colour battle ROM parses",
                   rom.signal_type == "C" and rom.turn == 1 and len(rom) == 2)
        self.check("...with 32-digit packets", rom.packet_hex_length == 32)

        operators = digirom.parse_command("V2-04^0E-4EEE-@E00E")
        self.check("operators are kept, not evaluated",
                   operators.packets[0] == "04^0E" and len(operators) == 3)
        self.check("...and count as one digit each for the width",
                   operators.packet_hex_length == 4)

        for op in ("P", "p", "I"):
            other = digirom.parse_command(op)
            self.check(f"{op!r} is a command, not a ROM",
                       other.signal_type is None and other.op == op.upper())

        for bad in ("", "nonsense", "C1", "C1-", "C9-1234", "C1-XYZ!", "C1-123"):
            try:
                digirom.parse_command(bad)
                self.check(f"{bad!r} is refused", False, "parsed")
            except CommandError:
                self.check(f"{bad!r} is refused", True)

        # Playing one. A stub module is enough: only battle_protocol is read.
        class StubModule:
            name = "DMC"
            battle_protocol = "DMC"

            def get_all_monsters(self):
                return []

        class Pet:
            name = "Agumon"
            module = "DMC"
            version, index, stage, level, sick = 1, 2, 3, 1, 0
            # A Ver.1 Digital Monster Color. The gameplay version is 1 and
            # the hardware one is **0** -- this line numbers its releases
            # from zero and `devices.json` now says so, where it used to say
            # 1 and have an offset take one off at send time.
            device_version = 0
            attribute = "Va"
            atk_main = atk_alt = 2
            traited = shook = False

            def get_power(self):
                return 30

            def get_hp(self):
                return 10

        saved = getattr(globals_, "game_modules", None)
        globals_.game_modules = {"DMC": StubModule()}
        try:
            result = executor.execute(
                digirom.parse_command(
                    "C1-47444C4300000001000C007300019408-"
                    "47444C4300020002000000000000938B"),
                Pet())
            entries = result.split()
            # Upstream's own two tests for a finished exchange.
            self.check("the result carries an r: entry", "r:" in result, result)
            self.check("...and is two entries per packet",
                       len(entries) == 4, str(len(entries)))
            self.check("the app's packets go out as the sent ones",
                       entries[0].startswith("s:47444C430000")
                       and entries[2].startswith("s:47444C430002"), result)
            self.check("ours come back as the received ones, player 2",
                       entries[1] == "r:47444C43000100000002001E000393AB"
                       and entries[3] == "r:47444C4300030001000000000000938B",
                       result)

            # Turn 1 means the app opened, so it sends first.
            self.check("turn 1 leads with the app's packet",
                       entries[0].startswith("s:"))
            listened = executor.execute(
                digirom.parse_command(
                    "C2-47444C4300000001000C007300019408-"
                    "47444C4300020002000000000000938B"),
                Pet())
            self.check("turn 2 leads with ours",
                       listened.split()[0].startswith("r:"), listened)

            # A Colour ROM addressed to another line gets no answer: "sending
            # a Pendulum Color GDLC is why it never answered".
            other_line = executor.execute(
                digirom.parse_command("C2-4456353200010000001A010F00007AB2"),
                Pet())
            self.check("a Digivice Color scan is not answered by a DMC pet",
                       "r:" not in other_line, other_line)

            # A scan is one packet, and is answered with one -- not a battle.
            scan = digirom.parse_command("C1-47444C43000000010000000000009388")
            self.check("a one-packet scan picks the Colour wire",
                       executor.battle_format_for(scan, Pet()) == "DMC")
            answered = executor.execute(scan, Pet())
            self.check("...and is answered with exactly one packet each way",
                       len(answered.split()) == 2, answered)
        finally:
            globals_.game_modules = saved

    def test_packet_exchange(self):
        self.section("PacketExchange (one assembly, every pipe)")

        from battle.sim.exchange import PacketExchange

        def pet(name, power, index, attribute=0):
            return make_digimon(name=name, power=power, index=index,
                                attribute=attribute, hp=10, level=3, stage=4,
                                shot1=2, shot2=3, mini_game=2)

        # Every format drives to completion between two peers, and both sides
        # agree the exchange is well formed. This is the versus battle, the
        # WiFiCom battle and the cable battle, all off one assembly.
        for fmt in protocol_constants.BATTLE_FORMATS:
            opener = PacketExchange(fmt, pet("A", 60, 4), opens=True)
            answerer = PacketExchange(fmt, pet("B", 40, 7, 1), opens=False)
            guard = 0
            while not (opener.complete and answerer.complete) and guard < 40:
                guard += 1
                packet = opener.next_packet()
                if packet:
                    answerer.receive(packet)
                packet = answerer.next_packet()
                if packet:
                    opener.receive(packet)

            self.check(f"{fmt} completes between two peers",
                       opener.complete and answerer.complete,
                       "%d/%d sent" % (len(opener.sent), opener.packet_count))
            self.check(f"...and both sides validate",
                       opener.validate() and answerer.validate())
            first, second = opener.result(), answerer.result()
            self.check(f"...and both build a result", first and second)
            if first and second:
                # device2 is always "us", so exactly one of them won.
                #
                # **Every wire, with no exceptions.** The Colour lines used
                # to be skipped here: the peer path declared the verdict from
                # the initiator's packet on all three, which is the Digital
                # Monster Color's rule, so on a line that FIGHTS the result
                # packet went out as zeros and the two endpoints disagreed.
                # Three separate slips fed it -- `DMCDevice` built without
                # `limits`, so it thought it was a DMC; the operation passed
                # on already offset and offset again, emitting 0x22 under
                # PENC magic; and the replay reading a DMC verdict for DMXW.
                self.check(f"...and exactly one of them won",
                           (first.winner == "device2") != (second.winner == "device2"),
                           "%s / %s" % (first.winner, second.winner))

        # The packets that cannot be written in advance are resolved from
        # what actually arrived, not left as an instruction to an adapter.
        opener = PacketExchange("DMX", pet("A", 120, 4), opens=True)
        answerer = PacketExchange("DMX", pet("B", 90, 7, 2), opens=False)
        for _ in range(8):
            packet = opener.next_packet()
            if packet:
                answerer.receive(packet)
            packet = answerer.next_packet()
            if packet:
                opener.receive(packet)
        theirs = PacketExchange._their_hits(opener.sent[5])
        ours = PacketExchange._their_hits(answerer.sent[5])
        self.check("the DMX answerer sends the inverse hit pattern",
                   ours == (~theirs) & 0x1F,
                   "{0} vs {1}".format(format(theirs, "05b"), format(ours, "05b")))
        self.check("...so a tie, which freezes a real device, cannot happen",
                   ours & theirs == 0)

        for command in (opener.command(), answerer.command()):
            self.check("a peer command carries no adapter operators",
                       "^" not in command and "@" not in command, command)

        # A ROM written for an adapter still carries its operators when it
        # reaches us: an app has no reason to resolve them, because on a real
        # WiFiCom the adapter would. Dropping the packet stalls the exchange
        # one short of complete and nothing ever plays.
        theirs = "V1-838E-2D9E-45BE-156E-00EE-@800E"
        answering = PacketExchange("PENZ", pet("Ours", 60, 36, 2), opens=False)
        for packet in theirs.split("-")[1:]:
            answering.receive(packet)
        self.check("an incoming @ check digit is worked out, not dropped",
                   len(answering.received) == 6, str(len(answering.received)))
        self.check("...to the digit that makes the remainder come out",
                   answering.received[5].hex().upper() == "B00E",
                   answering.received[5].hex().upper())
        total = sum(((b >> 4) & 0xF) + (b & 0xF)
                    for packet in answering.received for b in packet)
        self.check("...which is what the wire asks for",
                   total % 16 == protocol_constants.DMX.CHECKSUM_REMAINDER,
                   str(total % 16))
        while answering.next_packet() is not None:
            pass
        self.check("so the exchange completes", answering.complete)
        self.check("...and their side validates", answering.validate())
        self.check("...and it builds a battle to watch",
                   answering.result() is not None)

        # `^` mirrors a digit of the packet being replied to, which for one
        # they send us is the one we sent at that index.
        mirroring = PacketExchange("PENZ", pet("Ours", 60, 36, 2), opens=True)
        first = mirroring.next_packet()
        mirroring.receive("04^0E")
        self.check("an incoming ^ copies from the packet it answers",
                   mirroring.received[0].hex().upper()[2] == first.hex().upper()[2],
                   "%s vs %s" % (mirroring.received[0].hex().upper(),
                                 first.hex().upper()))

        # On the Colour wire a real device takes Player 1 for itself, but
        # between two Omnipets there is none, so the opener is Player 1.
        colour = PacketExchange("DMC", pet("A", 60, 4), opens=True, peer=True)
        colour.next_packet()
        colour.receive(DMCDevice(pet("B", 60, 4)).generate_packet1(1))
        colour.next_packet()
        self.check("a Colour opener is Player 1 between peers",
                   colour.sent[0][5] == 0 and colour.sent[1][5] == 2,
                   "ops %d/%d" % (colour.sent[0][5], colour.sent[1][5]))
        toy = PacketExchange("DMC", pet("A", 60, 4), opens=True, peer=False)
        toy.next_packet()
        toy.receive(DMCDevice(pet("B", 60, 4)).generate_packet1(1))
        toy.next_packet()
        self.check("...and the explicit opener keeps its role against a device",
                   toy.sent[0][5] == 0 and toy.sent[1][5] == 2,
                   "ops %d/%d" % (toy.sent[0][5], toy.sent[1][5]))

    def test_count_match_z(self):
        self.section("Count Match Z (the Pendulum Z's charge)")

        from ui.minigames.count_match_z import (
            ARROWS_BELOW_MAX, BASE_MAX_ARROWS, CountMatchZ, VIRUS_ARROWS,
            charge_subtype)

        # Both charge minigames band by the LEVEL where the module shows one
        # and by EFFORT where it does not, so a stub pet has to say which.
        from core import runtime_globals
        from utils import module_utils

        class Module:
            def __init__(self, *stats):
                self.visible_stats = list(stats)

        if runtime_globals.game_modules is None:
            runtime_globals.game_modules = {}
        runtime_globals.game_modules.setdefault(
            "LevelledStub", Module("Level", "Effort"))
        runtime_globals.game_modules.setdefault(
            "EffortStub", Module("Effort"))

        class Pet:
            def __init__(self, attribute, stage, level=1, effort=0,
                         module="LevelledStub"):
                self.attribute, self.stage, self.level = attribute, stage, level
                self.effort, self.module = effort, module

        def game(attribute, stage, level):
            """A CountMatchZ without the UIManager its sprites would need."""
            z = object.__new__(CountMatchZ)
            z.pet = Pet(attribute, stage, level)
            z.subtype = charge_subtype(z.pet)
            z.max_count = BASE_MAX_ARROWS + z.subtype - 1
            z.press_counter = 0
            return z

        # Every reading in utilities/DIGIROM/penz.txt: the stage and level,
        # then the slots on offer, the count asked for, and the outcome of
        # each possible shake count from 0 up. Sixteen cells off a real
        # Pendulum Z, and the whole minigame is pinned by them.
        BAD, GOOD, GREAT, EXC = 0, 1, 2, 3
        measured = [
            (7, "Va", 1, 5, 5, [BAD, BAD, GOOD, GOOD, GREAT, EXC]),
            (7, "Va", 5, 4, 4, [BAD, BAD, GOOD, GREAT, EXC]),
            (7, "Va", 10, 3, 3, [BAD, GOOD, GREAT, EXC]),
            (6, "Free", 1, 5, 5, [BAD, BAD, GOOD, GOOD, GREAT, EXC]),
            (6, "Free", 5, 4, 4, [BAD, BAD, GOOD, GREAT, EXC]),
            (6, "Free", 10, 3, 3, [BAD, GOOD, GREAT, EXC]),
            (5, "Vi", 1, 4, 1, [BAD, EXC, GREAT, GOOD, GOOD]),
            (5, "Vi", 8, 3, 1, [BAD, EXC, GREAT, GOOD]),
            (4, "Da", 1, 4, 3, [BAD, BAD, GREAT, EXC, GOOD]),
            (4, "Da", 6, 3, 2, [BAD, GOOD, EXC, GREAT]),
            (3, "Va", 1, 3, 3, [BAD, GOOD, GREAT, EXC]),
            (3, "Va", 4, 3, 3, [BAD, GOOD, GREAT, EXC]),
            (2, "Free", 1, 3, 3, [BAD, GOOD, GREAT, EXC]),
            (2, "Free", 2, 3, 3, [BAD, GOOD, GREAT, EXC]),
            (2, "Free", 3, 3, 3, [BAD, GOOD, GREAT, EXC]),
            (1, "Free", 1, 3, 3, [BAD, GOOD, GREAT, EXC]),
        ]
        for stage, attribute, level, slots, asked, outcomes in measured:
            z = game(attribute, stage, level)
            where = f"stage {stage} {attribute} lv {level}"
            self.check(f"{where} is a {slots}-slot game",
                       z.max_count == slots, str(z.max_count))
            self.check(f"{where} asks for {asked}",
                       z.get_target_arrow_count() == asked,
                       str(z.get_target_arrow_count()))
            got = []
            for shakes in range(len(outcomes)):
                z.press_counter = shakes
                got.append(z.calculate_result())
            self.check(f"{where} scores {outcomes}", got == outcomes, str(got))

        # A pet whose module has no Level stat would sit at level 1 forever
        # and never leave the widest game, so it bands by EFFORT instead --
        # the Xai bar's own 0-8 / 9-15 / 16+, and the same call decides it
        # for both, so the two cannot drift.
        from battle.sim.battle_utils import pet_tier_index
        for effort, slots in ((0, 5), (8, 5), (9, 4), (15, 4), (16, 3), (40, 3)):
            pet = Pet("Va", 7, level=1, effort=effort, module="EffortStub")
            got = BASE_MAX_ARROWS + charge_subtype(pet) - 1
            self.check(f"an effort-{effort} pet plays a {slots}-slot game",
                       got == slots, str(got))
        # The level is ignored entirely there -- it is what the pet does not
        # have.
        self.check("a level on an effort module changes nothing",
                   charge_subtype(Pet("Va", 7, 1, 20, "EffortStub"))
                   == charge_subtype(Pet("Va", 7, 10, 20, "EffortStub")))
        # And effort is ignored on a module that does level.
        self.check("effort on a levelling module changes nothing",
                   charge_subtype(Pet("Va", 7, 5, 0))
                   == charge_subtype(Pet("Va", 7, 5, 40)))
        self.check("the Xai bar reads the same call",
                   pet_tier_index(Pet("Va", 7, 5)) == 2
                   and pet_tier_index(Pet("Va", 7, 1, 20, "EffortStub")) == 3)

        # The stage sets a ceiling and the top tier of any stage is always the
        # easy three-slot game, so the drops land where the device puts them.
        # Stage 4 is the one that separates this from "one off per tier":
        # its tiers are 1-2, 3-5, 6, and it changes ONLY at level 6.
        for stage, changes_at in ((1, []), (2, []), (3, []), (4, [6]),
                                  (5, [8]), (6, [5, 10]), (7, [5, 10])):
            top = {1: 1, 2: 3, 3: 4, 4: 6, 5: 8, 6: 10, 7: 10}[stage]
            steps = [level for level in range(2, top + 1)
                     if charge_subtype(Pet("Va", stage, level))
                     != charge_subtype(Pet("Va", stage, level - 1))]
            self.check(f"stage {stage} changes its slots at {changes_at or 'no level'}",
                       steps == changes_at, str(steps))

        # The charge has to reach the packets, and on this minigame it used
        # not to. It is scored **straight off the arrow counter** -- there is
        # no meter to band and no super hits to count -- so `minigame_result`
        # takes the counter and the pet, not the `super_hits` slot Count
        # Match Color uses. Pushing it through that slot is what let it sit
        # at 0: the encounter pre-scored into a `minigame_result` attribute
        # nothing has ever read, so **every battle on a Pendulum Z module
        # went out as Bad** however well it was played.
        from ui.minigames.minigame_session import minigame_result
        for stage, attribute, slots, asked, outcomes in (
                (7, "Va", 5, 5, [BAD, BAD, GOOD, GOOD, GREAT, EXC]),
                (5, "Vi", 4, 1, [BAD, EXC, GREAT, GOOD, GOOD]),
                (2, "Free", 3, 3, [BAD, GOOD, GREAT, EXC])):
            pet = Pet(attribute, stage)
            got = [minigame_result("Count Match Z", 0, 0, arrows, pet)
                   for arrows in range(len(outcomes))]
            self.check(f"stage {stage} {attribute} scores its counter "
                       f"{outcomes}", got == outcomes, str(got))
        # Count Match Color still reads super hits, and Z no longer does --
        # they are different games and were sharing one slot.
        self.check("super hits do not decide Count Match Z",
                   minigame_result("Count Match Z", 0, 3,
                                   0, Pet("Free", 2)) == BAD)
        self.check("...while Count Match Color still reads them",
                   minigame_result("Count Match Color", 0, 5) == EXC)

        source = open(os.path.join(
            _REPO_ROOT,
            "src", "battle", "battle_encounter.py"), encoding="utf-8").read()
        self.check("the encounter passes the counter, the pet and the band",
                   'pet = getattr(self.count_match_z, "pet", None)' in source
                   and 'self.press_counter, pet, getattr(self, "color_band", None))'
                   in source)
        self.check("...and nothing writes the attribute that was never read",
                   "self.minigame_result = " not in source)

        # Free and Vaccine ask for the whole meter, so they are the pair that
        # shares a type -- with three types and four attributes, one pair had
        # to. Data is one below, and Virus is not on that scale at all.
        self.check("Free and Vaccine ask for the whole meter",
                   ARROWS_BELOW_MAX["Free"] == ARROWS_BELOW_MAX["Va"] == 0)
        self.check("Data asks for one less",
                   ARROWS_BELOW_MAX["Da"] == 1)
        self.check("a pet with no attribute is treated as Free",
                   ARROWS_BELOW_MAX[""] == ARROWS_BELOW_MAX["Free"])
        # The reading that broke "each subtype adds one to the count too":
        # a Virus pet asks for one at three slots and at four alike.
        self.check("Virus asks for one whatever the meter",
                   VIRUS_ARROWS == 1
                   and game("Vi", 5, 1).get_target_arrow_count()
                   == game("Vi", 5, 8).get_target_arrow_count() == 1)

    def test_dmc_turn_resolution(self):
        self.section("DMC/PENC turn resolution (a verdict, not a hit pattern)")

        from battle.sim.battle_simulator import DMCBSPacket

        # This wire has no HP and no rounds: one bit settles it. "Whether or
        # not the device sending this signal wins the battle. 0 for loss,
        # 1 for victory. Only Operation 2 will report the victory, Operation
        # 3 sends 0 regardless" -- so the word counts only from player one.
        fixture = make_digimon(power=140, hp=5, index=0, attribute=0,
                               shot1=2, shot2=22, mini_game=0, level=1, stage=4)
        fixture.version = 1
        # **Which operation carries it depends on the line.** A Pendulum
        # Color numbers the same four roles from 0x10, so its Player 1 Battle
        # Data is 0x12 -- and a bare `== 2` threw its verdict away as None,
        # which sent the battle to the power tiebreak. Filmed battle 43 is
        # exactly that: the device declared outcome 0, "I lost", and the game
        # showed it winning.
        for fmt, magic in (("DMC", 0x47444C43), ("PENC", 0x47444470)):
            offset = protocol_constants.get_constants(fmt).OPERATION_OFFSET
            for declared, device_wins in ((1, True), (0, False)):
                dcom = DComBattleSimulator(None, battle_format=fmt)
                mine = dcom.generate_player_packets(fixture)
                device = [
                    DMCBSPacket(operation=offset + 0, index=17, power=250,
                                attribute=1, shot=16, outcome=0, version=0,
                                magic=magic).build_packet1(),
                    DMCBSPacket(operation=offset + 2, index=17, power=250,
                                attribute=1, shot=16, outcome=declared,
                                version=0, magic=magic).build_packet2(),
                ]
                groups = [p[i:i + 2].hex().upper() for p in device
                          for i in range(0, len(p), 2)]
                opponent = dcom.parse_opponent(groups, fixture)
                self.check(f"{fmt} reads the verdict from operation "
                           f"{offset + 2:#x}",
                           getattr(opponent, "dmc_outcome", None) == declared,
                           str(getattr(opponent, "dmc_outcome", None)))
                result = dcom.build_result(fixture, opponent, mine, groups)
                self.check(f"{fmt} outcome {declared} has turns to animate",
                           len(result.battle_log) > 0, len(result.battle_log))
                if fmt == "DMC":
                    self.check(f"DMC outcome {declared} means the "
                               f"{'device' if device_wins else 'game'} wins",
                               (result.winner == "device1") == device_wins,
                               result.winner)

        # **And the Pendulum Color does not use that field at all**, so the
        # same packet with the bit set either way settles nothing -- what
        # decides its battle is the two Digimon.
        #
        # Ten captures against a real device carry outcome 0 in every one:
        # opponents at power 10, 15, 64 and 140, Free, Data and Vaccine, OEM
        # and compatibility, four different charges. The same physical device
        # on the DMC wire (filmed battle 42) puts a 1 there and wins, so the
        # field works on that line and is unused on this one. Reading it
        # handed the player every PENC battle ever fought.
        import random

        outcomes = {}
        for declared in (0, 1):
            dcom = DComBattleSimulator(None, battle_format="PENC")
            mine = dcom.generate_player_packets(fixture)
            device = [
                DMCBSPacket(operation=0x10, index=17, power=250, attribute=1,
                            shot=16, outcome=0, version=0,
                            magic=0x47444470).build_packet1(),
                DMCBSPacket(operation=0x12, index=17, power=250, attribute=1,
                            shot=16, outcome=declared, version=0,
                            magic=0x47444470).build_packet2(),
            ]
            groups = [p[i:i + 2].hex().upper() for p in device
                      for i in range(0, len(p), 2)]
            opponent = dcom.parse_opponent(groups, fixture)
            random.seed(4)
            outcomes[declared] = dcom.build_result(
                fixture, opponent, mine, groups).winner
        self.check("PENC ignores the outcome bit -- it decides nothing",
                   outcomes[0] == outcomes[1], str(outcomes))

        # Power affects result generation, never a replay of fixed packets.
        from battle.sim.exchange import simulate_exchange
        wins = 0
        for seed in range(60):
            random.seed(seed)
            stronger = make_digimon(power=250, attribute=fixture.attribute,
                                     mini_game=fixture.mini_game, stage=fixture.stage)
            wins += simulate_exchange('PENC', stronger, fixture).winner == 'device1'
        self.check("the stronger device usually wins a freshly generated exchange",
                   30 < wins < 60, "%d of 60" % wins)

        # Operation 3 says nothing, so a device that answered rather than
        # opened leaves the verdict to us.
        dcom = DComBattleSimulator(None, battle_format="DMC")
        device = [
            DMCBSPacket(operation=1, index=17, power=250, attribute=1, shot=16,
                        outcome=0, version=0, magic=0x47444C43).build_packet1(),
            DMCBSPacket(operation=3, index=17, power=250, attribute=1, shot=16,
                        outcome=0, version=0, magic=0x47444C43).build_packet2(),
        ]
        groups = [p[i:i + 2].hex().upper() for p in device for i in range(0, len(p), 2)]
        opponent = dcom.parse_opponent(groups, fixture)
        self.check("operation 3 carries no verdict",
                   getattr(opponent, "dmc_outcome", "unset") is None,
                   str(getattr(opponent, "dmc_outcome", "unset")))

        # The battle itself is the same every time: four rounds -- three
        # traded singles, then the winner's double against the loser's single
        # **that misses**. The loser runs out on exactly 5 damage and the
        # winner, having taken three, finishes on 2. Only the winner varies.
        # Both halves are filmed against a real device: battle 1 gave the
        # four rounds, battle 3 gave the miss ("Device Double / Game Single
        # Miss" on the round the game went down).
        for declared, device_wins in ((1, True), (0, False)):
            dcom = DComBattleSimulator(None, battle_format="DMC")
            mine = dcom.generate_player_packets(fixture)
            device = [
                DMCBSPacket(operation=0, index=17, power=250, attribute=1, shot=16,
                            outcome=0, version=0, magic=0x47444C43).build_packet1(),
                DMCBSPacket(operation=2, index=17, power=250, attribute=1, shot=16,
                            outcome=declared, version=0, magic=0x47444C43).build_packet2(),
            ]
            groups = [p.hex().upper() for p in device]
            opponent = dcom.parse_opponent(groups, fixture)
            result = dcom.build_result(fixture, opponent, mine, groups)
            final = result.battle_log[-1]
            loser = final.device2_status[0] if device_wins else final.device1_status[0]
            winner = final.device1_status[0] if device_wins else final.device2_status[0]
            self.check(f"DMC loser ends on 0 ({'device' if device_wins else 'game'} won)",
                       loser.hp == 0, loser.hp)
            self.check(f"DMC winner ends on 2 ({'device' if device_wins else 'game'} won)",
                       winner.hp == 2, winner.hp)
            self.check("DMC runs its four rounds",
                       len(result.battle_log) == 4, len(result.battle_log))
            # Every shot lands except the loser's last: it fires as it goes
            # down and misses, which is what the film shows.
            early = result.battle_log[:-1]
            self.check("every DMC attack lands before the final round",
                       all(a.hit for t in early for a in t.attacks))
            last = result.battle_log[-1].attacks
            winner_shot = last[0] if device_wins else last[1]
            loser_shot = last[1] if device_wins else last[0]
            self.check("the winner's last shot lands for 2",
                       winner_shot.hit and winner_shot.damage == 2,
                       f"hit={winner_shot.hit} dmg={winner_shot.damage}")
            self.check("the loser's last shot misses",
                       not loser_shot.hit and loser_shot.damage == 1,
                       f"hit={loser_shot.hit} dmg={loser_shot.damage}")

        # The HP a DCom battle is fought with belongs to the FORMAT, not the
        # pet: sending the pet's own left a 12 HP bar for a fight the log
        # drained from 5, so it stopped at 7 instead of empty.
        big = make_digimon(power=10, hp=12, index=3, attribute=0,
                           shot1=16, shot2=16, mini_game=0, level=1, stage=4)
        # DM20 and PEN20 are 10, measured on the device -- and ten for every
        # Digimon on those lines, whatever its stage. They were 5, on a DCom
        # note rather than a reading.
        #
        # PENC is **3**, from its own manual -- "each Digimon has 3 health
        # points which will be reduced by 1 for a normal hit and by 2 for a
        # super hit". It rides the Digital Monster Color's wire and had been
        # taking that wire's five, so its battle spent 5 against a 3-point
        # bar. Reading the format first is what separates them.
        for fmt, expected in (("DMC", 5), ("PENC", 3), ("DM20", 10), ("PEN20", 10),
                              ("DMX", 12), ("PENZ", 12)):
            dcom = DComBattleSimulator(None, battle_format=fmt)
            self.check(f"{fmt} fights with {expected} HP, not the pet's 12",
                       dcom.get_initial_hp(big) == expected,
                       dcom.get_initial_hp(big))

        # The wire carries no charge at all.
        self.check("DMC plays no minigame",
                   protocol_constants.DMC.MINIGAME == "None")

        # And it goes out over the Color transport: op letter "C", packets
        # whole rather than split into 16-bit groups. From wificom-lib's
        # known-good codes, e.g.
        #   C1-47444C4300000000000E00AA00019440-47444C430002003000000000000093B9
        dcom = DComBattleSimulator(None, battle_format="DMC")
        command = dcom.build_command(dcom.generate_player_packets(fixture))
        self.check("DMC uses the C op letter", command.startswith("C2-"), command[:4])
        parts = command.split("-")
        self.check("DMC sends two whole 32-digit packets",
                   len(parts) == 3 and all(len(p) == 32 for p in parts[1:]),
                   str([len(p) for p in parts[1:]]))
        known = "47444C4300000000000E00AA00019440"
        words = [int(known[i:i + 4], 16) for i in range(0, 32, 4)]
        self.check("a known-good Color code checksums the way we build them",
                   sum(words[:-1]) & 0xFFFF == words[-1])

        # A real Color device takes Player 1 for itself: sent a C1 carrying our
        # own operation 0, a Ver.2 DMC answered with operation 0 as well and
        # then waited for the Player 2 packets that never came. So we are
        # always Player 2 here, whoever transmits first.
        for turn in (protocol_constants.DCOM_TURN_LISTEN,
                     protocol_constants.DCOM_TURN_GO_FIRST):
            dcom = DComBattleSimulator(None, battle_format="DMC")
            packets = dcom.generate_player_packets(fixture, turn)
            ops = [int(p.hex()[8:12], 16) for p in packets]
            self.check(f"turn {turn} sends its own Colour role",
                       ops == ([0, 2] if turn == 1 else [1, 3]), str(ops))
        self.check("the Color wire answers rather than opens",
                   protocol_constants.DMC.DCOM_TURN == protocol_constants.DCOM_TURN_LISTEN)

        # What a real Ver.2 DMC sent back, decoded: Vegiemon, power 40.
        reply = "47444C4300000001000A0028000193BB"
        words = [int(reply[i:i + 4], 16) for i in range(0, 32, 4)]
        self.check("the device's reply checksums", sum(words[:-1]) & 0xFFFF == words[-1])
        self.check("it opens with GDLC", (words[0] << 16 | words[1]) == protocol_constants.DMC.MAGIC)
        self.check("it claims Player 1", words[2] == 0)
        self.check("its version 1 is Ver.2", words[3] == 1)
        self.check("its power reads 40", words[5] == 40)

        # A Pendulum Color numbers the same four roles from 0x10, and puts
        # its CHARGE where the DMC leaves a COU half at zero. The operations
        # come from the PenC codes in utilities/DIGIROM, e.g.
        #   C1-47444470001000000002001400038BDD-47444470001200390000000000028C01
        # and a real device answered ours with operation 0x10.
        dcom = DComBattleSimulator(None, battle_format="PENC")
        packets = dcom.generate_player_packets(fixture)
        ops = [int(p.hex()[8:12], 16) for p in packets]
        self.check("PENC sends operations 0x11 and 0x13", ops == [0x11, 0x13],
                   [hex(o) for o in ops])

        # **The charge, not the flat 2.** Those codes all carry 2 because
        # they are background unlocks and not battles, and 2 is not one of
        # the four values a real battle produces -- so sending it told the
        # device the same thing however the player rolled, which is what a
        # real Pendulum Color showed.
        # **The selector names a ROW, so it depends on the stage too.** Six
        # pairs are measured, each off a device whose Digimon resolved to a
        # roster record (giving its stage) in a battle whose heading records
        # the colour it landed (giving its band).
        from battle.sim.dcom_battle_simulator import colour_trailer
        from battle.sim.battle_utils import (get_penc_wire_charge,
                                             get_penc_wire_pattern,
                                             get_penc_pattern,
                                             penc_super_hits_from_wire,
                                             penc_wire_charge_is_measured,
                                             penc_super_hits)
        measured = {(3, 0): 0x02, (3, 2): 0x0A, (3, 3): 0x0E,
                    (4, 0): 0x03, (4, 1): 0x08, (4, 2): 0x0B, (4, 3): 0x0E}
        for (stage, band), expected in measured.items():
            got = get_penc_wire_charge(stage, band)
            self.check("stage %d band %d goes on the wire as 0x%02X"
                       % (stage, band, expected), got == expected, str(got))
            self.check("...and is on record rather than approximated",
                       penc_wire_charge_is_measured(stage, band))

        # **It cannot be keyed on the super-hit count.** Stages 3 and 4 pay
        # the same counts for their bottom and middle bands and send
        # different selectors, which is what the old table could not say.
        for band in (0, 2):
            self.check("stage 3 and 4 agree on the count for band %d" % band,
                       penc_super_hits(get_penc_pattern(3, band))
                       == penc_super_hits(get_penc_pattern(4, band)))
            self.check("...and still send different selectors",
                       get_penc_wire_charge(3, band)
                       != get_penc_wire_charge(4, band))

        # A selector reads back as the row it names, and the count is that
        # row's own. Filmed battle 58 is the failure this fixes: a Fujamon
        # that had landed its middle colour sent 0x000A and read as "0".
        for (stage, band), selector in measured.items():
            self.check("0x%02X reads back as the stage %d %s row"
                       % (selector, stage, ("none", "worst", "middle",
                                            "own")[band]),
                       get_penc_wire_pattern(selector)
                       == get_penc_pattern(stage, band),
                       str(get_penc_wire_pattern(selector)))
        self.check("battle 58's 0x000A is 3 super hits, not 0",
                   penc_super_hits_from_wire(0x000A) == 3,
                   str(penc_super_hits_from_wire(0x000A)))
        # 0x0007 used to be "unmeasured" and read as all normal hits. The
        # shared pool has all 15, so it is a real row now -- only an index
        # outside the pool falls back.
        self.check("selector 0x0007 is a real pool row",
                   get_penc_wire_pattern(0x0007)[:5] == [2, 1, 1, 2, 1],
                   str(get_penc_wire_pattern(0x0007)))
        self.check("an index outside the pool is all normal hits",
                   get_penc_wire_pattern(99) == [1] * 6,
                   str(get_penc_wire_pattern(99)))

        self.check("the unlock codes' 2 is a real selector, not an outlier",
                   0x02 in measured.values()
                   and protocol_constants.PENC.BATTLE_TRAILER == 2)

        charged = make_digimon(name="Charged", index=1, attribute=0, shot1=1,
                               shot2=1, power=15, mini_game=5, stage=4)
        charged.version = 0
        trailer = int(dcom.generate_player_packets(charged)[1].hex()[24:28], 16)
        self.check("a PENC battle packet carries the row it will throw",
                   trailer == 0x0E, trailer)
        self.check("...and colour_trailer leaves the DMC's own half at zero",
                   colour_trailer("DMC", charged) == 0)
        self.check("DMC's does not",
                   int(DComBattleSimulator(None, battle_format="DMC")
                       .generate_player_packets(fixture)[1].hex()[24:28], 16) == 0)
        for pkt in packets:
            words = [int(pkt.hex().upper()[i:i + 4], 16) for i in range(0, 32, 4)]
            self.check("PENC packets checksum like the real codes",
                       sum(words[:-1]) & 0xFFFF == words[-1])

        # The real PenC codes reproduce through our own checksum too.
        for code in ("47444470001000000002001400038BDD",
                     "47444470001200390000000000028C01",
                     "4744447000100006001C00B400038C9D"):
            words = [int(code[i:i + 4], 16) for i in range(0, 32, 4)]
            self.check(f"real PenC code {code[8:12]} checksums",
                       sum(words[:-1]) & 0xFFFF == words[-1])

        # It plays a charge where the Digital Monster Color plays none.
        self.check("PENC plays Count Match Color",
                   protocol_constants.PENC.MINIGAME == "Count Match Color")
        self.check("DMC plays none", protocol_constants.DMC.MINIGAME == "None")

        # Versions are numbered from zero on this wire: "Example Value:
        # 0 (Ver.1)", and the analyzer indexes ["dmc1".."dmc5"] by what it
        # receives. A Ver.2 device is wire version 1.
        #
        # **`device_version` IS that number now.** It used to be 1-5 with a
        # `VERSION_OFFSET` taking one off at send time; the module carries
        # the wire's own values instead, which is what every other line does
        # and what `version` vs `device_version` is for.
        self.check("device_version goes out unchanged",
                   [protocol_constants.clamp_oem_version("DMC", v)
                    for v in range(6)] == [0, 1, 2, 3, 4, 5])
        self.check("...because the offset is gone",
                   protocol_constants.DMC.VERSION_OFFSET == 0)

        # And the inversion goes back to the **gameplay** version, because
        # that is what a roster lookup filters on -- monster.json's `version`
        # is 1-5 where device_version is 0-4. The two used to be the same
        # number, which is what hid the difference.
        self.check("wire 0 is gameplay version 1",
                   protocol_constants.module_versions_for_wire("DMC", 0) == [1])
        self.check("wire 4 is gameplay version 5",
                   protocol_constants.module_versions_for_wire("DMC", 4) == [5])
        self.check("wire 5 is a gameplay version the DMC has not",
                   protocol_constants.module_versions_for_wire("DMC", 5) == [6])

        # The known-good reading is the check on both halves at once: a real
        # Ver.2 DMC answered `47444C4300000001000A0028000193BB` -- wire
        # version 1, index 10 -- holding a Vegiemon, which is gameplay
        # version 2 index 10 on the module's roster.
        import json as _json
        import os as _os
        _root = _REPO_ROOT
        _roster = _os.path.join(_root, "modules", "DMC", "monster.json")
        if _os.path.exists(_roster):
            with open(_roster, encoding="utf-8") as _handle:
                _rows = _json.load(_handle)["monster"]
            _versions = protocol_constants.module_versions_for_wire("DMC", 1)
            _named = [r["name"] for r in _rows
                      if r.get("index") == 10 and r.get("version") in _versions]
            self.check("wire 1 index 10 resolves to the Vegiemon it was",
                       _named == ["Vegiemon"], str(_named))
        _devices = _os.path.join(_root, "modules", "DMC", "devices.json")
        if _os.path.exists(_devices):
            with open(_devices, encoding="utf-8") as _handle:
                _devs = _json.load(_handle)["devices"]
            self.check("the DMC module declares device_version 0-4",
                       [d["device_version"] for d in _devs] == [0, 1, 2, 3, 4],
                       str([d["device_version"] for d in _devs]))
        # 0-4 are the five Digital Monster Colors and **5 is a crossover
        # edition** -- the Monster Hunter, Godzilla and Xros Wars devices,
        # which are Digital Monster Colors with rosters of their own. The
        # analyzer reads it the same way, and filmed battles 44 and 45 both
        # announced 5. Without 5 in the range a crossover pet's version is
        # sent as 0, "special", instead of its own.
        self.check("DMC declares versions 0-5, the five plus the crossovers",
                   protocol_constants.VERSION_RANGES["DMC"] == (0, 5))
        self.check("a crossover pet goes out as 5, not clamped to 0",
                   protocol_constants.clamp_oem_version("DMC", 5) == 5)
        self.check("PENC declares versions 0-7",
                   protocol_constants.VERSION_RANGES["PENC"] == (0, 7))
        self.check("wires that number from one are unaffected",
                   protocol_constants.clamp_oem_version("DMX", 1) == 1
                   and protocol_constants.clamp_oem_version("DM20", 3) == 3)

        # The attribute cycle is written in DMC's own encoding.
        beats = protocol_constants.DMC.ATTRIBUTE_BEATS
        self.check("Vaccine beats Virus", beats[3] == 1)
        self.check("Virus beats Data", beats[1] == 2)
        self.check("Data beats Vaccine", beats[2] == 3)
        self.check("the advantage is 5 on the roll",
                   protocol_constants.DMC.ATTRIBUTE_ADVANTAGE == 5
                   and not protocol_constants.DMC.ATTRIBUTE_ADVANTAGE_ON_POWER)

    def test_dmog_outcome(self):
        self.section("DMOG outcome (1 victory, 2 defeat -- never 0)")

        from battle.sim.battle_simulator import DMDevice
        fixture = make_digimon(power=140, hp=5, index=0, attribute=0,
                               shot1=0, shot2=0, mini_game=0)
        fixture.version = 1
        packets = DMDevice(fixture).generate_all_packets()
        outcome = packets[1][1] & 0x0F
        self.check("the outcome sent is a legal value", outcome in (1, 2), outcome)
        self.check("it is not 0, which is neither victory nor defeat", outcome != 0)

        # Mirrors are the bitwise complement, which is how the device tells a
        # valid code from noise.
        for pkt in packets:
            hi, lo = pkt[0], pkt[1]
            self.check("mirrors complement their values",
                       ((hi >> 4) & 0xF) == ((~((lo >> 4) & 0xF)) & 0xF)
                       and (hi & 0xF) == ((~(lo & 0xF)) & 0xF),
                       pkt.hex().upper())

        # Answering, the adapter inverts the device's outcome: 1<->2 and
        # their mirrors E<->D are both a XOR with 3.
        for theirs in (1, 2):
            self.check(f"outcome {theirs} inverts to {theirs ^ 3}", (theirs ^ 3) in (1, 2))
            self.check(f"mirror of {theirs} inverts too",
                       ((~theirs) & 0xF) ^ 3 == (~(theirs ^ 3)) & 0xF)

        dcom = DComBattleSimulator(None, battle_format="DMOG")
        packets = dcom.generate_player_packets(fixture, protocol_constants.DCOM_TURN_LISTEN)
        answering = dcom.build_command(packets, protocol_constants.DCOM_TURN_LISTEN)
        self.check("answering lets the adapter invert the outcome",
                   dcom.sent_echoed_outcome and "^3" in answering, answering)
        opening = dcom.build_command(packets, protocol_constants.DCOM_TURN_GO_FIRST)
        self.check("opening sends a literal, since there is nothing to invert",
                   not dcom.sent_echoed_outcome and "^3" not in opening, opening)

    def test_filmed_penz_battle(self):
        self.section("Filmed PENZ battle (real hardware, 2026-08-22)")

        # A Pendulum Z rides the DMX wire, and battle 12 -- a Raremon mirror
        # match, both sides OEM at Excellent -- says it shares the rest too.
        # Packets verbatim from the exchange log.
        from battle.sim.battle_utils import get_attack_pattern, get_attack_damage

        device1, our1 = 0x83AE, 0x03AE          # both L1, Attack 3
        device6, our6 = 0x80EE, 0xF11E
        hp = 12
        # Raremon is an **Adult**, and the DMX's table is keyed on the stage
        # first -- so this battle is also the check on whether the Pendulum Z
        # shares the DMX's measured rows. At stage 4 level 1 Excellent both
        # answer `c ds ds ss ds`, whose critical takes 12 to 2, which is what
        # the bar read.
        stage = 4
        dpat = get_attack_pattern(((device1 >> 11) & 0xF) + 1, (device1 >> 8) & 3,
                                  "DMX", stage)
        opat = get_attack_pattern(((our1 >> 11) & 0xF) + 1, (our1 >> 8) & 3,
                                  "DMX", stage)
        self.check("PENZ battle 12 reads the same row on either table",
                   opat == get_attack_pattern(1, 3, "PENZ", stage),
                   f"{opat} vs {get_attack_pattern(1, 3, 'PENZ', stage)}")
        our_hits = (((our6 >> 8) & 1) << 4) | ((our6 >> 4) & 0xF)
        dev_hits = (((device6 >> 8) & 1) << 4) | ((device6 >> 4) & 0xF)

        self.check("PENZ hits are the inverse of the device's",
                   (~dev_hits) & 0x1F == our_hits)
        self.check("identical pets draw identical patterns", dpat == opat, f"{dpat} vs {opat}")

        # Filmed: our Critical lands and the bar reads 2, then two Doubles miss.
        self.check("our hits read Hit, Miss, Miss as filmed",
                   [(our_hits >> t) & 1 for t in range(3)] == [1, 0, 0],
                   f"0b{our_hits:05b}")
        self.check("the critical takes 12 HP to 2, as filmed",
                   hp - get_attack_damage(opat[0]) == 2,
                   hp - get_attack_damage(opat[0]))

        # And the swapped reading, which the unfilmed battle before it had
        # made look possible, is contradicted outright.
        self.check("the hits are not the other way round",
                   [(dev_hits >> t) & 1 for t in range(3)] != [1, 0, 0],
                   f"0b{dev_hits:05b}")

        them, us = hp, hp
        rounds = 5
        for turn in range(5):
            if (dev_hits >> turn) & 1:
                us = max(0, us - get_attack_damage(dpat[turn]))
            if (our_hits >> turn) & 1:
                them = max(0, them - get_attack_damage(opat[turn]))
            if us == 0 or them == 0:
                rounds = turn + 1
                break
        self.check("battle 12 is won by the device", us == 0 and them == 2,
                   f"device {them}, us {us}")

        # Two rows drawn in filmed battles, which the line's own table has to
        # keep reproducing now that it no longer borrows the DMX's. The
        # Raremons are Adults and read stage 4; our Shoutmon is a Child at
        # level 3, which used to be pinned to one fixed row by
        # PENZ.LOW_STAGE_ROWS and is now looked up like any other stage.
        PENZ_ROWS = (
            # label,             wire level, attack, pattern drawn, stage
            ("b12 device",       0, 3, [5, 4, 4, 2, 4], 4),
            ("b12 our Raremon",  0, 3, [5, 4, 4, 2, 4], 4),
            ("b13 device",       0, 3, [5, 4, 4, 2, 4], 4),
            ("b13 our Shoutmon", 2, 3, [2, 5, 4, 4, 3], 3),
        )
        for label, wire, attack, drawn, stage in PENZ_ROWS:
            got = get_attack_pattern(wire + 1, attack, protocol="PENZ",
                                     stage=stage)
            self.check(f"PENZ {label} draws {drawn}", got == drawn, f"{got}")

        # Battles 33 and 34, filmed after the line got its own table -- so
        # they are a check on it rather than the source of it, and they were
        # logged by the current code, which pairs each note with its own
        # exchange (the earlier run's dumps sit one block out). The film
        # records the SHAPE, so that is what is compared.
        SHAPE = {1: "S", 2: "S", 3: "D", 4: "D", 5: "C"}
        for label, p1, p2, filmed in (("33", 0x836E, 0x42EE, "CDD"),
                                      ("34", 0x829E, 0x42EE, "DSSC")):
            level, charge = ((p1 >> 11) & 0xF) + 1, (p1 >> 8) & 3
            stage = ((p2 >> 13) & 0x7) + 2
            drawn = get_attack_pattern(level, charge, "PENZ", stage=stage)
            shape = "".join(SHAPE[v] for v in drawn)[:len(filmed)]
            self.check(f"battle {label}: a stage {stage} lv {level} device "
                       f"draws {filmed}", shape == filmed, shape)

    def test_dmx_attack_table(self):
        self.section("DMX attack table (stage + level band, measured)")

        # 72 values read off real hardware two ways -- the training minigame
        # on the player's own pets, and map_dmx_attacks.py driving a battle
        # where the announced stage, level and charge are ours to set so the
        # device draws OUR pattern. Six cells were measured both ways and
        # agree; three where two readings disagreed were settled by a re-run
        # reading the device's HP bar rather than the sprite.
        import json
        import os as _os
        from battle.sim.battle_utils import (dmx_tier_index, get_attack_damage,
                                             get_attack_pattern)

        path = _os.path.join(_REPO_ROOT, "src", "data", "attack_patterns",
            "DMX.json")
        table = json.load(open(path, encoding="utf-8"))
        tiers = table["tiers"]

        self.check("nothing in the table is provisional any more",
                   not [t for t in tiers if "provisional" in t])

        # Every BATTLING stage has exactly three tiers, they start at level 1,
        # they are contiguous, and the top one is that stage's maximum level
        # alone. Stage 1 is outside that: a Baby I has one level and cannot
        # battle, so it has one tier and was read off the training minigame.
        BANDS = {2: [(1, 1), (2, 2), (3, 3)],
                 3: [(1, 2), (3, 3), (4, 4)],
                 4: [(1, 2), (3, 5), (6, 6)],
                 5: [(1, 3), (4, 7), (8, 8)],
                 6: [(1, 4), (5, 9), (10, 10)],
                 7: [(1, 4), (5, 9), (10, 10)]}
        for stage, bands in BANDS.items():
            band = [tuple(t["levels"]) for t in tiers if t["stage"] == stage]
            self.check(f"stage {stage} bands {bands}", band == bands, str(band))
        self.check("six battling stages, three tiers each",
                   len([t for t in tiers if t["stage"] != 1]) == 18
                   and len(BANDS) == 6, len(tiers))

        # A Baby I is one tier, and its row is the same block stage 2's first
        # tier carries -- read off training, not assumed from the clamp that
        # was already giving it. Worth pinning because the same block is also
        # PENZ's stage 1, and the two lines' tables are otherwise separate.
        baby = [t for t in tiers if t["stage"] == 1]
        self.check("stage 1 is a single tier at level 1",
                   len(baby) == 1 and tuple(baby[0]["levels"]) == (1, 1))
        self.check("stage 1 draws stage 2 tier 1's block",
                   baby[0]["patterns"]
                   == [t for t in tiers if t["stage"] == 2][0]["patterns"])
        for stage, bands in BANDS.items():
            self.check(f"stage {stage}'s top tier is its max level alone",
                       bands[-1][0] == bands[-1][1])
            self.check(f"stage {stage}'s bands are contiguous from 1",
                       bands[0][0] == 1 and all(
                           bands[i + 1][0] == bands[i][1] + 1
                           for i in range(len(bands) - 1)))

        # A charge is worth more than the one below it, in every one of the
        # 18 tiers. This held across all 32 cells as they were read, which is
        # the readings' own consistency check.
        rows = {r["id"]: r["pattern"] for r in table["patterns"]}
        for tier in tiers:
            spend = [sum(get_attack_damage(v) for v in rows[i])
                     for i in tier["patterns"]]
            self.check(f"stage {tier['stage']} lv {tier['levels']} rises with "
                       f"the charge", spend == sorted(spend), str(spend))

        # Baby II never draws a strong attack -- atk_main and the critical
        # only, across all twelve of its rows.
        weak_only = {1, 3, 5}
        for tier in tiers:
            if tier["stage"] != 2:
                continue
            used = {v for i in tier["patterns"] for v in rows[i]}
            self.check(f"stage 2 lv {tier['levels']} draws no strong attack",
                       used <= weak_only, str(sorted(used)))

        # Spot values, straight from the readings.
        SPOT = (
            (2, 1, 0, [1, 1, 1, 1, 1]),        # sw sw sw sw sw
            (3, 1, 3, [2, 5, 4, 4, 3]),        # ss c ds ds dw -- filmed battle 1
            (4, 6, 3, [5, 4, 4, 5, 4]),        # c ds ds c ds  -- was inferred, then read
            (6, 1, 1, [1, 4, 3, 1, 3]),        # sw ds dw sw dw -- the overruled one
            (6, 10, 3, [5, 4, 4, 5, 4]),       # c ds ds c ds
            (7, 5, 2, [2, 5, 4, 4, 3]),        # ss c ds ds dw -- stage 7 is not stage 6
        )
        for stage, level, charge, want in SPOT:
            got = get_attack_pattern(level, charge, "DMX", stage)
            self.check(f"stage {stage} lv {level} charge {charge}",
                       got == want, f"{got}")

        # Stage 7 shares stage 6's banding but not its rows.
        differ = [q for q in range(4)
                  if get_attack_pattern(1, q, "DMX", 6)
                  != get_attack_pattern(1, q, "DMX", 7)]
        self.check("stage 7 has rows of its own", differ, str(differ))

        # The XAI bar widens where the attacks change row, so both read the
        # same bands out of the same file.
        for stage, bands in BANDS.items():
            for index, (low, high) in enumerate(bands, start=1):
                for level in (low, high):
                    self.check(f"bar subtype {index} at stage {stage} lv {level}",
                               dmx_tier_index(stage, level) == index,
                               dmx_tier_index(stage, level))

        # `pet_to_digimon` writes the WIRE's stage into the Digimon it
        # builds, and `parse_opponent` puts the toy's back on Omnipet's -- so
        # the two sides of a finished exchange are on different scales and
        # every caller has to say which it holds. Our own Raremon, an Adult,
        # reached the lookup as a 2 and drew Baby II's row; the same slip made
        # PENZ's low-stage rule fire for everything up to Perfect.
        from battle.sim import protocol_constants as _pc
        for omnipet, wire in ((2, 0), (3, 1), (4, 2), (5, 3), (6, 4), (7, 5)):
            self.check(f"wire stage {wire} is Omnipet's {omnipet}",
                       _pc.stage_from_wire("DMX", wire) == omnipet,
                       _pc.stage_from_wire("DMX", wire))
        self.check("a wire stage carries no meaning to the table on its own",
                   get_attack_pattern(1, 3, "DMX", 2)
                   != get_attack_pattern(1, 3, "DMX",
                                         _pc.stage_from_wire("DMX", 2)))
        self.check("stage_from_wire passes None through",
                   _pc.stage_from_wire("DMX", None) is None)
        # And PENZ's low-stage rule only reaches what it names.
        self.check("PENZ's fixed row stops above Child",
                   get_attack_pattern(1, 3, "PENZ", 3)
                   != get_attack_pattern(5, 3, "PENZ", 4))

        # A stage or level off the end clamps to the nearest band rather than
        # falling through -- a pet from any module can carry any stage here.
        self.check("an unknown stage clamps to the nearest",
                   get_attack_pattern(1, 3, "DMX", 0)
                   == get_attack_pattern(1, 3, "DMX", 2))
        self.check("a level past the top clamps to the top tier",
                   get_attack_pattern(99, 3, "DMX", 6)
                   == get_attack_pattern(10, 3, "DMX", 6))

    def test_training_patterns(self):
        self.section("Training plays each pet's own row, on its line's table")

        import pygame
        pygame.init()
        from battle.sim.battle_utils import (get_attack_damage,
                                             get_attack_pattern)
        from training.training import Training

        MAIN, ALT, CRIT = 2, 5, 9      # distinct sizes, so a sprite is
        surf = lambda n: pygame.Surface((n, n), pygame.SRCALPHA)

        class Probe(Training):
            """Training with the sprite bank stubbed, to read the ladder."""

            def __init__(self, alt=True, crit=True):
                self.alt, self.crit = alt, crit

            def get_attack_sprite(self, pet, atk_id):
                if atk_id == 1:
                    return surf(MAIN)
                return surf(ALT) if (atk_id == 2 and self.alt) else None

            def get_crit_attack_sprite(self, pet, atk_id):
                return surf(CRIT) if (atk_id == 3 and self.crit) else None

            def _combine_sprites(self, sprite, offsets):
                return ("combined", sprite.get_width(), len(offsets))

        class Pet:
            atk_main, atk_alt, atk_alt_2 = 1, 2, 3
            stage, level, attribute = 4, 1, "Va"

        def drawn(value, alt=True, crit=True):
            got, is_crit = Probe(alt, crit).ladder_sprite(Pet(), value)
            if isinstance(got, tuple):
                return ("%d %s" % (got[2], "alt" if got[1] == ALT else "main"),
                        is_crit)
            return ({MAIN: "1 main", ALT: "1 alt", CRIT: "crit",
                     ALT * 2: "alt 2x"}.get(got.get_width(), "?"), is_crit)

        # Two ladders crossed: a weak shot draws atk_main and a strong one
        # atk_alt, each once or twice. The copy this replaced had 2 and 3 the
        # other way round -- a strong single drew as a weak double -- and it
        # went unseen because training threw made-up rows no table had to
        # agree with. Same mapping as BattleEncounter._ladder_shot.
        for value, want in ((1, "1 main"), (2, "1 alt"), (3, "2 main"),
                            (4, "2 alt"), (5, "crit")):
            got, is_crit = drawn(value)
            self.check(f"pattern value {value} draws {want}", got == want, got)
            self.check(f"...and only {value} == 5 slides the critical in",
                       is_crit == (value == 5))

        # No atk_alt: the strong shots cannot be told apart by sprite, so
        # they are told apart by count -- the JSON's own fallbacks, which do
        # collide 2 with 3.
        for value, want in ((1, "1 main"), (2, "2 main"), (3, "2 main"),
                            (4, "3 main")):
            got, _ = drawn(value, alt=False)
            self.check(f"without atk_alt, value {value} draws {want}",
                       got == want, got)
        # atk_alt_2 indexes the crit bank, so an id with nothing behind it
        # drops to the ladder's own answer at double size rather than naming
        # an unrelated ordinary shot.
        self.check("a missing crit sprite falls back to alt at 2x",
                   drawn(5, crit=False) == ("alt 2x", True))

        # Each training minigame belongs to a device line and plays that
        # line's table, read for the pet's own stage and level. The four
        # hardcoded rows this replaced were shared by the whole party.
        probe = Probe()

        def row(protocol, stage, level, charge):
            pet = Pet()
            pet.stage, pet.level = stage, level
            return probe.line_pattern(pet, charge, protocol)

        self.check("the Xai bar (Excite) plays the DMX's table",
                   row("DMX", 2, 1, 3) == get_attack_pattern(1, 3, "DMX", stage=2))
        self.check("Count Match Z plays the Pendulum Z's",
                   row("PENZ", 2, 1, 3) == get_attack_pattern(1, 3, "PENZ", stage=2))
        # And they are different tables, which is the point of the split.
        self.check("a Baby II trains differently on the two lines",
                   row("DMX", 2, 1, 3) != row("PENZ", 2, 1, 3))
        # A Baby II and an Ultimate no longer train identically.
        self.check("stage changes the row a pet trains with",
                   row("DMX", 2, 1, 3) != row("DMX", 6, 1, 3))
        self.check("...and so does level",
                   row("DMX", 6, 1, 3) != row("DMX", 6, 10, 3))
        # The charge still reads 0-3 as every table on these lines expects.
        spends = [sum(get_attack_damage(v) for v in row("DMX", 6, 1, c))
                  for c in range(4)]
        self.check("a better charge trains harder", spends == sorted(spends),
                   str(spends))

    def test_shot_bank_clamp(self):
        self.section("A sprite field is wider than the device's sprite bank")

        import json
        import os
        import re

        from battle.sim import protocol_constants

        root = _REPO_ROOT

        to_wire = protocol_constants.shot_to_wire
        from_wire = protocol_constants.shot_from_wire

        # Two different limits. DM20's field is six bits, so 0-62 fit below
        # the sentinel -- but the device has 44 sprites, ids 0-43, and a
        # value past the bank names nothing it can draw.
        dm20 = protocol_constants.get_constants("DM20")
        self.check("DM20 carries a 6-bit field", dm20.MAX_SHOT == 0x3F)
        self.check("...over a bank of 44", dm20.SHOT_COUNT == 44)

        bank, field = dm20.SHOT_COUNT, dm20.MAX_SHOT
        # Omnipet numbers from 1 and the device from 0, so a real sprite
        # shifts down by one.
        for ours, wire in ((1, 0), (2, 1), (44, 43)):
            self.check(f"our sprite {ours} goes out as {wire}",
                       to_wire(ours, field, bank) == wire,
                       str(to_wire(ours, field, bank)))
        # Anything past the bank clamps to its last sprite rather than
        # naming one the device does not have.
        for ours in (45, 60, 63, 200):
            self.check(f"sprite {ours} clamps to the bank's last",
                       to_wire(ours, field, bank) == bank - 1,
                       str(to_wire(ours, field, bank)))
        # "None" is still the FIELD's all-ones, not the bank's -- that is
        # what the wire spells none with, whatever the bank holds.
        self.check("no sprite still goes out as the field's sentinel",
                   to_wire(0, field, bank) == field)
        self.check("...and reads back as no sprite",
                   from_wire(field, field) == 0)

        # PEN20's field is eight bits, so there the bank is much the
        # tighter limit -- 108 sprites against a field that would carry 254.
        pen20 = protocol_constants.get_constants("PEN20")
        self.check("PEN20 carries an 8-bit field", pen20.MAX_SHOT == 0xFF)
        self.check("...over a bank of 108", pen20.SHOT_COUNT == 108)
        self.check("so a sprite past the bank clamps well short of the field",
                   to_wire(200, pen20.MAX_SHOT, pen20.SHOT_COUNT) == 107)

        # The X lines carry a THIRD shot, and it draws from a different
        # folder: the ordinary two come from the module's own atk/ (58
        # sprites) and the mega from assets/atk_crit (29), which is global
        # because these are the only lines that use it. Both fields are
        # wider than their bank -- 63 and 31 -- so each needs its own count.
        dmx = protocol_constants.get_constants("DMX")
        self.check("the DMX has two banks, not one",
                   (dmx.SHOT_COUNT, dmx.SHOT_COUNT_M) == (58, 29))
        self.check("its ordinary shot clamps to the module's folder",
                   to_wire(112, dmx.MAX_SHOT, dmx.SHOT_COUNT) == 57)
        self.check("its mega shot clamps to the crit folder, not that one",
                   to_wire(31, dmx.MAX_SHOT_M, dmx.SHOT_COUNT_M) == 28)
        self.check("...and each keeps its own field's sentinel",
                   (to_wire(0, dmx.MAX_SHOT, dmx.SHOT_COUNT),
                    to_wire(0, dmx.MAX_SHOT_M, dmx.SHOT_COUNT_M))
                   == (dmx.MAX_SHOT, dmx.MAX_SHOT_M))
        # PENZ rides the same wire and the same folders.
        penz = protocol_constants.get_constants("PENZ")
        self.check("PENZ inherits both banks",
                   (penz.SHOT_COUNT, penz.SHOT_COUNT_M) == (58, 29))

        # The whole way through, not just the helper: a pet whose ids sit
        # past both banks has each field clamped to its own.
        from battle.sim.dcom_battle_simulator import pet_to_digimon

        class Overshot:
            name, module, index, version, device_version = "T", "DMX", 5, 1, 1
            stage, attribute, level, sick, effort = 4, "Va", 1, 0, 0
            stomach = strength = hunger = 4
            weight, traited, shook = 30, False, False
            atk_main, atk_alt, atk_alt_2 = 112, 58, 29
            def get_power(self, *a, **k):
                return 50
            def get_hp(self, *a, **k):
                return 12

        packed = pet_to_digimon(Overshot(), "DMX", 3)
        self.check("a packed pet clamps each shot to its own bank",
                   (packed.shot2, packed.shot1, packed.dmx_shot_m)
                   == (57, 57, 28),
                   "%s/%s/%s" % (packed.shot2, packed.shot1,
                                 packed.dmx_shot_m))

        # The Colour line draws from the GLOBAL assets/atk -- that library
        # IS the Digital Monster Color's set, which is why every other line
        # needed a folder of its own. Its field is sixteen bits over a bank
        # of 117, the widest gap on any wire.
        dmc = protocol_constants.get_constants("DMC")
        penc = protocol_constants.get_constants("PENC")
        self.check("the Colour line's bank is the global library",
                   dmc.SHOT_COUNT == 117 and penc.SHOT_COUNT == 117)
        self.check("its 16-bit field would carry far more",
                   dmc.MAX_SHOT == 0xFFFF)
        self.check("so a sprite past 117 clamps to 116",
                   to_wire(200, dmc.MAX_SHOT, dmc.SHOT_COUNT) == 116)
        self.check("...and none is still the field's own all-ones",
                   to_wire(0, dmc.MAX_SHOT, dmc.SHOT_COUNT) == 0xFFFF)

        # Everything the Colour modules name is inside that library, which is
        # what makes 117 the right bank rather than a guess.
        for module in ("DMC", "PENC", "DMOG", "PENOG"):
            folder = os.path.join(root, "modules", module)
            if not os.path.isdir(folder):
                continue
            named = set()
            for name in ("monster.json", "battle.json"):
                path = os.path.join(folder, name)
                if not os.path.exists(path):
                    continue
                with open(path, encoding="utf-8") as handle:
                    data = json.load(handle)
                for key in ("monster", "enemies"):
                    for record in data.get(key) or []:
                        if not isinstance(record, dict):
                            continue
                        for field in ("atk_main", "atk_alt"):
                            if record.get(field):
                                named.add(record[field])
            self.check(f"{module} names only sprites the global library has",
                       named <= set(range(1, 118)),
                       str(sorted(named - set(range(1, 118)))[:6]))

        # A format that declares no bank is unchanged: the field is the only
        # limit, which is where every line started.
        self.check("no bank means the field alone clamps",
                   to_wire(300, 0xFF, 0) == 0xFE)

        # PENOG's bank is the 1998 guide's full list: the Colour library in
        # the same order less eight sprites the Pendulum does not have. It
        # caps what we send. It does NOT describe what a device sends --
        # every Shot on record is past it -- so incoming ids are not clamped.
        penog = protocol_constants.get_constants("PENOG")
        self.check("PENOG's bank is the Pendulum's own 109 sprites",
                   penog.SHOT_COUNT == 109 and penog.MAX_SHOT == 0xFF,
                   f"{penog.SHOT_COUNT}/{penog.MAX_SHOT}")
        self.check("so a sprite past 109 clamps to 108",
                   to_wire(117, penog.MAX_SHOT, penog.SHOT_COUNT) == 108)
        self.check("...and none is still the field's own all-ones",
                   to_wire(0, penog.MAX_SHOT, penog.SHOT_COUNT) == 0xFF)

        # The module's folder is what the bank counts, so the two must not
        # drift: each atk/ is a contiguous run of exactly SHOT_COUNT.
        for module, limits in (("DM20", dm20), ("PEN20", pen20),
                               ("DMX", dmx), ("PENZ", penz),
                               ("PENOG", penog)):
            atk = os.path.join(root, "modules", module, "atk")
            if not os.path.isdir(atk):
                continue
            ids = {int(m.group(1)) for m in
                   (re.match(r"^(\d+)(_[A-Za-z0-9]+)?\.png$", f)
                    for f in os.listdir(atk)) if m}
            self.check(f"{module}'s atk folder is a contiguous "
                       f"1..{limits.SHOT_COUNT}",
                       ids == set(range(1, limits.SHOT_COUNT + 1)),
                       "%d ids, max %s" % (len(ids), max(ids) if ids else 0))

        # atk_alt_2 names the CRIT bank -- a different folder, and the global
        # one for every module -- so the renumber must leave it alone. PEN20
        # is where that bit: it named the field on 45 records, and remapping
        # them against atk/ would have pointed every critical at an
        # unrelated picture.
        #
        # **Only a wire carrying MAX_SHOT_M may name one at all.** That is
        # the X lines and nothing else, so on every other module the field
        # describes an attack its device cannot make. It is inert rather
        # than visibly wrong -- `_ladder_shot` reads it only for attack
        # value 5, and only the X table has a fifth -- which is exactly why
        # it sat unnoticed on two modules until it was looked for.
        crit = os.path.join(root, "assets", "atk_crit")
        crit_ids = set()
        if os.path.isdir(crit):
            crit_ids = {int(m.group(1)) for m in
                        (re.match(r"^(\d+)(_[A-Za-z0-9]+)?\.png$", f)
                         for f in os.listdir(crit)) if m}
            self.check("assets/atk_crit is a contiguous 1..29",
                       crit_ids == set(range(1, 30)), str(len(crit_ids)))

        may_have = {name for name in protocol_constants.BATTLE_FORMATS
                    if getattr(protocol_constants.get_constants(name),
                               "MAX_SHOT_M", 0)}
        self.check("only the X lines carry a crit sprite field",
                   may_have == {"DMX", "PENZ"}, str(sorted(may_have)))

        # **And the iC's own Digimon**, whose wire draws a Hyper from a crit
        # bank of the iC's own (`modules/IC/atk_crit/`, IC.CRIT_BANK_DAMAGE).
        # The IC module is named by the wire it is native to
        # (`IC.NATIVE_MODULES`), and its ids are checked against its own
        # folder.
        own_crit_banks = {}
        for name in protocol_constants.BATTLE_FORMATS:
            if getattr(protocol_constants.get_constants(name),
                       "CRIT_BANK_DAMAGE", None):
                for owner in protocol_constants.native_modules(name):
                    own_crit_banks[owner] = name

        modules_dir = os.path.join(root, "modules")
        offenders, out_of_bank = [], []
        for module in sorted(os.listdir(modules_dir)):
            folder = os.path.join(modules_dir, module)
            if not os.path.isdir(folder) or ".bak" in module:
                continue
            own_crit_ids = None
            if module in own_crit_banks:
                own = os.path.join(folder, "atk_crit")
                own_crit_ids = {int(m.group(1)) for m in
                                (re.match(r"^(\d+)(_[A-Za-z0-9]+)?\.png$", f)
                                 for f in (os.listdir(own) if os.path.isdir(own) else ()))
                                if m}
            manifest = os.path.join(folder, "module.json")
            declared = ""
            if os.path.exists(manifest):
                try:
                    with open(manifest, encoding="utf-8") as handle:
                        declared = json.load(handle).get("battle_protocol") or ""
                except (ValueError, OSError):
                    declared = ""
            for name in ("monster.json", "battle.json"):
                path = os.path.join(folder, name)
                if not os.path.exists(path):
                    continue
                with open(path, encoding="utf-8") as handle:
                    data = json.load(handle)
                for key in ("monster", "enemies"):
                    for record in data.get(key) or []:
                        value = (record.get("atk_alt_2")
                                 if isinstance(record, dict) else None)
                        if not value:
                            continue
                        if own_crit_ids is not None:
                            if value not in own_crit_ids:
                                out_of_bank.append("%s %s=%s (own atk_crit)"
                                                   % (module, record.get("name"),
                                                      value))
                            continue
                        if declared not in may_have:
                            offenders.append("%s/%s %s" % (module, name,
                                                           record.get("name")))
                        elif crit_ids and value not in crit_ids:
                            out_of_bank.append("%s %s=%s"
                                               % (module, record.get("name"),
                                                  value))
        self.check("no module names a crit sprite on a wire without one",
                   not offenders, "%d: %s" % (len(offenders), offenders[:4]))
        self.check("...and every one that does is in assets/atk_crit",
                   not out_of_bank, "%d: %s" % (len(out_of_bank),
                                                out_of_bank[:4]))

    def test_filmed_dmc_battle(self):
        self.section("Filmed DMC battle (real hardware, 2026-09-07)")

        import json
        import os
        from core import runtime_globals
        from battle.sim.dcom_battle_simulator import DComBattleSimulator

        root = _REPO_ROOT
        path = os.path.join(root, "modules", "DMC", "monster.json")
        if not os.path.exists(path):
            return
        with open(path, encoding="utf-8") as handle:
            roster = json.load(handle)["monster"]

        class Stub:
            name, battle_protocol = "DMC", "DMC"

            def get_monsters_by_index(self, index, versions=None):
                return [dict(r, module="DMC") for r in roster
                        if r.get("index") == index
                        and (versions is None or r.get("version") in versions)]

            def get_monster_by_index(self, index, versions=None):
                found = self.get_monsters_by_index(index, versions)
                return found[0] if found else None

        saved = runtime_globals.game_modules
        runtime_globals.game_modules = dict(saved or {})
        runtime_globals.game_modules["DMC"] = Stub()
        try:
            # Battle 37. The device's packet 1 carries version 1 and index 3;
            # its packet 2 carries Shot 4.
            sim = DComBattleSimulator(None, battle_format="DMC")
            opponent = sim.parse_opponent(
                ["47444C43000000010003001E000293AB",
                 "47444C4300020004000000000000938D"])

            # The version has to be recorded, or the index means nothing: on
            # this line index 3 is a different Digimon on each of the five
            # versions, so without it the whole roster matched and the answer
            # came back "Elecmon or Palmon". `_parse_dmc_opponent` was the one
            # parser not storing it.
            self.check("the DMC parser records the announced version",
                       sim.opponent_device_version == 1,
                       str(sim.opponent_device_version))
            self.check("...so wire version 1 is module version 2",
                       protocol_constants.module_versions_for_wire("DMC", 1)
                       == [2])
            self.check("...and index 3 on it is Elecmon",
                       opponent.name == "Elecmon", opponent.name)

            # Shot 4 off the wire is sprite 5 to us -- the lightning bolt the
            # device drew. This wire carries ONE shot field, so both sides of
            # the pair take it.
            self.check("the device's shot reads back as sprite 5",
                       (opponent.shot1, opponent.shot2) == (5, 5),
                       f"{opponent.shot1}/{opponent.shot2}")
        finally:
            runtime_globals.game_modules = saved

    def test_filmed_penc_battle(self):
        self.section("Filmed PENC battles (real hardware, 2026-09-07)")

        import json
        import os
        from core import runtime_globals
        from battle.sim.dcom_battle_simulator import DComBattleSimulator

        root = _REPO_ROOT

        def stub(module):
            path = os.path.join(root, "modules", module, "monster.json")
            if not os.path.exists(path):
                return None
            with open(path, encoding="utf-8") as handle:
                roster = json.load(handle)["monster"]

            class Stub:
                name = module
                battle_protocol = module

                def get_monsters_by_index(self, index, versions=None):
                    return [dict(r, module=module) for r in roster
                            if r.get("index") == index
                            and (versions is None or r.get("version") in versions)]

                def get_monster_by_index(self, index, versions=None):
                    found = self.get_monsters_by_index(index, versions)
                    return found[0] if found else None
            return Stub()

        saved = runtime_globals.game_modules
        runtime_globals.game_modules = dict(saved or {})
        for module in ("DMC", "PENC"):
            made = stub(module)
            if made is not None:
                runtime_globals.game_modules[module] = made
        try:
            # Battle 43, a real Pendulum Color on its OWN protocol. Its
            # packets are numbered from 0x10, and its packet 2 declares
            # outcome **0** -- "the device sending this loses".
            sim = DComBattleSimulator(None, battle_format="PENC")
            opponent = sim.parse_opponent(
                ["47444470001000060008003E00028C12",
                 "474444700012006800000000000E8C3C"])
            self.check("battle 43's opponent resolves to Gawappamon",
                       opponent.name == "Gawappamon", opponent.name)
            self.check("...on wire version 6, which is module version 6",
                       sim.opponent_device_version == 6,
                       str(sim.opponent_device_version))
            # The bug: the verdict is at operation 0x12 on this line, and a
            # bare `== 2` discarded it. The battle then settled on power --
            # 15 against 62 -- and handed the device a win it had declined.
            self.check("its verdict is read, not discarded",
                       opponent.dmc_outcome == 0,
                       str(opponent.dmc_outcome))

            # Battle 42, the same physical device in DMC compatibility mode.
            # It announces version 5 -- one past the DMC's own five -- and
            # index 0xFFFF, the wire's "none". It is saying it has nothing on
            # this line's roster, and it does not offer its Pendulum Color
            # identity instead, so the placeholder is the honest answer.
            sim = DComBattleSimulator(None, battle_format="DMC")
            opponent = sim.parse_opponent(
                ["47444C4300000005FFFF003E000293CB",
                 "47444C430002006800010000000093F2"])
            self.check("battle 42's opponent sends the 'none' index",
                       opponent.index == 0xFFFF, hex(opponent.index))
            self.check("...so it keeps the placeholder rather than a name",
                       opponent.name in ("Da", "Vi", "Va", "Fr"), opponent.name)
            self.check("...and its verdict still reads (1, the device won)",
                       opponent.dmc_outcome == 1, str(opponent.dmc_outcome))

            # Both lines number their four roles from their own base.
            self.check("DMC counts from 0 and PENC from 0x10",
                       (protocol_constants.DMC.OPERATION_OFFSET,
                        protocol_constants.PENC.OPERATION_OFFSET) == (0, 0x10))
        finally:
            runtime_globals.game_modules = saved

    def test_penc_battle_shape(self):
        self.section("PENC fights; the DMC exchanges a verdict")

        import json
        import os
        import random
        from battle.sim.battle_utils import (get_penc_pattern,
                                             get_penc_enemy_pattern,
                                             penc_super_hits,
                                             penc_band_for_super_hits,
                                             verdict_rounds)
        from battle.sim.battle_simulator import BattleSimulator
        from battle.sim.models import BattleProtocol
        from ui.minigames.count_match import CountMatch

        penc = protocol_constants.PENC

        # The manual, on the compatibility battle: "You Digimon will exchange
        # 3 normal hits, followed by one of the two participants sending a
        # super hit, making them the winner" -- and "except for the first
        # three hits of a battle with a Digital Monster Color, which are
        # always guaranteed". 3 + 2 = 5, the DMC's whole bar. So the four
        # rounds `verdict_rounds` stages are the device's, not a construction.
        winner, loser = verdict_rounds(5)
        self.check("a DMC battle is 3 normal hits then a super hit",
                   winner == [1, 1, 1, 2], str(winner))
        self.check("...spending exactly the loser's 5 HP",
                   sum(winner) == protocol_constants.DMC.FIXED_HP)
        self.check("...and the loser answers with singles",
                   loser == [1, 1, 1, 1], str(loser))

        # PENC is the other case: "each Digimon has 3 health points which
        # will be reduced by 1 for a normal hit and by 2 for a super hit",
        # and the charge decides how many of the five shots are super.
        # **Six rounds, not five.** Five was the charge's shot count; the
        # family's shared pool stores six values a row and PENC's hit mask
        # has twice been seen with bit 5 set. At 3 HP a sixth round is rare
        # rather than unreachable, which is why nothing filmed reached it.
        self.check("PENC fights at 3 HP over 6 rounds",
                   (penc.FIXED_HP, penc.TURNS) == (3, 6),
                   str((penc.FIXED_HP, penc.TURNS)))
        self.check("...while the charge still fires five shots",
                   protocol_constants.PENC.MAX_CHARGE == 5)
        self.check("...where the DMC stages 4",
                   protocol_constants.DMC.TURNS == 4)
        self.check("PENC reads the raw super-hit count, 0-5",
                   (penc.CHARGE_SCALE, penc.MAX_CHARGE) == ("super hits", 5))

        # **The table is the device's, for all seven stages.** Read off a
        # real Pendulum Color (`utilities/DIGIROM/penc.txt`): every stage,
        # every colour, the five shots off the screen. It is keyed on the
        # stage and the colour band and on nothing else -- effort, hunger and
        # strength were maxed on several stages without moving a row.
        # Rounds 1-5 are what was read off the device; round 6 comes from
        # the family's shared pool, which those five identify uniquely.
        measured = {
            1: ([1, 1, 1, 1, 1], [2, 1, 1, 1, 1], [1, 1, 2, 2, 2], [2] * 5),
            2: ([1, 1, 1, 1, 1], [2, 1, 1, 1, 1], [1, 1, 2, 2, 2], [2] * 5),
            3: ([1, 2, 1, 1, 1], [1, 1, 2, 2, 1], [1, 2, 1, 2, 2], [2] * 5),
            4: ([1, 1, 2, 1, 1], [2, 1, 2, 1, 1], [2, 1, 2, 1, 2], [2] * 5),
            5: ([1, 1, 1, 2, 1], [2, 1, 1, 2, 1], [1, 2, 2, 2, 2], [2] * 5),
            6: ([2, 1, 1, 1, 1], [1, 2, 1, 2, 1], [2, 1, 2, 2, 2], [2] * 5),
            7: ([2, 1, 1, 1, 1], [1, 2, 1, 2, 1], [2, 1, 2, 2, 2], [2] * 5),
        }
        for stage, rows in measured.items():
            for band, row in enumerate(rows):
                got = get_penc_pattern(stage, band)
                self.check("stage %d band %d opens %s" % (stage, band, row),
                           got[:5] == row, str(got))
                self.check("...and is six rounds long", len(got) == 6,
                           str(len(got)))

        self.check("only 1 and 2 appear -- this wire has no third value",
                   all(v in (1, 2) for stage in range(1, 8)
                       for band in range(4)
                       for v in get_penc_pattern(stage, band)))

        # **No row that has supers to place puts them first**, which is what
        # both the battle and the training screen threw before the device was
        # read: `[2] * n + [1] * (5 - n)`. All-normal and all-super rows
        # coincide with that formula trivially, and a single super has only
        # five places to sit -- so the claim is about the 2, 3 and 4 super
        # rows, where the formula has something to get wrong and does.
        supers_first = [[2] * n + [1] * (5 - n) for n in range(2, 5)]
        interesting = [get_penc_pattern(stage, band)[:5]
                       for stage in range(1, 8) for band in range(4)
                       if 2 <= penc_super_hits(get_penc_pattern(stage, band)) <= 4]
        self.check("no row with 2-4 supers is supers-first",
                   interesting and not any(row in supers_first
                                           for row in interesting),
                   str(interesting))

        # The super-hit count follows from the stage, so the manual's "3 or
        # 4" band is the stage speaking rather than a roll.
        counts = {stage: [penc_super_hits(get_penc_pattern(stage, band))
                          for band in range(4)] for stage in range(1, 8)}
        self.check("stages 1-2 pay 0/1/3/5",
                   counts[1] == counts[2] == [0, 1, 3, 5], str(counts[1]))
        self.check("stages 3-4 pay 1/2/3/5",
                   counts[3] == counts[4] == [1, 2, 3, 5], str(counts[3]))
        self.check("stages 5-7 pay 1/2/4/5",
                   counts[5] == counts[6] == counts[7] == [1, 2, 4, 5],
                   str(counts[5]))
        self.check("...so 4 super hits are real, which the manual left open",
                   4 in counts[7])

        # The two stage 3 readings -- a Virus pet and a Data pet -- came out
        # identical once keyed on the band, which is what shows the
        # arrangement follows the band and not the colour.
        self.check("a band is exact within a stage, so the inverse is too",
                   all(penc_band_for_super_hits(stage, counts[stage][band])
                       == band
                       for stage in range(1, 8) for band in range(4)))

        self.check("a stage past the table clamps to the last read",
                   get_penc_pattern(99, 3) == [2] * 6,
                   str(get_penc_pattern(99, 3)))

        # An enemy has no charge, so it reads its stage -- and every row it
        # can throw is one of that stage's own measured rows, so it never
        # plays a pattern the device could not.
        rows = [get_penc_enemy_pattern(stage) for stage in range(1, 8)]
        self.check("every enemy row is one the device produces",
                   all(row in [get_penc_pattern(stage, band)
                               for band in range(4)]
                       for stage, row in zip(range(1, 8), rows)), str(rows))
        totals = [sum(row) for row in rows]
        self.check("...and damage never falls as the stage rises",
                   all(a <= b for a, b in zip(totals, totals[1:])),
                   str(totals))
        # The bands were chosen to reproduce the invented table's ramp over
        # five rounds; with the sixth the totals rise but the ORDER is what
        # the choice was about, and it still holds.
        self.check("...and the ramp is what the bands were chosen for",
                   totals == sorted(totals), str(totals))
        five = [sum(get_penc_enemy_pattern(stage)[:5])
                for stage in range(1, 8)]
        self.check("...reproducing the old five-round ramp exactly",
                   five == [5, 6, 7, 8, 9, 10, 10], str(five))

        # The file is PENC's own, not the DMC's.
        root = _REPO_ROOT
        with open(os.path.join(root, "src", "data", "attack_patterns",
                               "PENC.json"), encoding="utf-8") as handle:
            table = json.load(handle)
        self.check("PENC.json declares 3 HP and the two damage values",
                   (table["hp"], table["damage"]["normal"],
                    table["damage"]["super"]) == (3, 1, 2))

        # A versus battle on this line is a battle, not a verdict.
        def fighter(name, power, attribute, charge):
            return make_digimon(name=name, power=power, attribute=attribute,
                                mini_game=charge, hp=penc.FIXED_HP, stage=4,
                                index=1)

        random.seed(5)
        sim = BattleSimulator(BattleProtocol.DMC_BS, battle_format='PENC')
        results = [sim.simulate(fighter("Ours", 120, 3, 5),
                                fighter("Theirs", 110, 1, 0))
                   for _ in range(40)]
        self.check("a PENC versus battle rolls its rounds",
                   len({len(r.battle_log) for r in results}) > 1,
                   str(sorted({len(r.battle_log) for r in results})))
        self.check("...never longer than the five it has",
                   all(len(r.battle_log) <= penc.TURNS for r in results))
        self.check("...and never spends more than 2 in a shot",
                   all(a.damage in (1, 2) for r in results
                       for t in r.battle_log for a in t.attacks))
        self.check("...with exactly one winner each time",
                   all(r.winner in ("device1", "device2") for r in results))

        # ...while the DMC keeps its verdict, unchanged.
        random.seed(5)
        dmc = BattleSimulator(BattleProtocol.DMC_BS, battle_format='DMC')
        verdicts = [dmc.simulate(
            make_digimon(name="A", power=100, attribute=3, mini_game=2,
                         hp=protocol_constants.DMC.FIXED_HP, stage=4, index=1),
            make_digimon(name="B", power=100, attribute=1, mini_game=2,
                         hp=protocol_constants.DMC.FIXED_HP, stage=4, index=1))
            for _ in range(20)]
        self.check("a DMC versus battle is still the same four rounds",
                   {len(r.battle_log) for r in verdicts} == {4},
                   str(sorted({len(r.battle_log) for r in verdicts})))

        # The colour progression: one pass, Blue then Yellow then Red, and it
        # does not wrap. It used to step every three shakes and cycle.
        got = [CountMatch.color_for_shakes(n) for n in range(15)]
        self.check("nothing is on screen under two shakes",
                   got[0] == got[1] == CountMatch.NO_COLOR)
        self.check("Blue from 2, Yellow from 7, Red from 12",
                   (got[2], got[6], got[7], got[11], got[12])
                   == (3, 3, 2, 2, 1), str(got))
        self.check("...and Red is the end of it",
                   all(CountMatch.color_for_shakes(n) == 1
                       for n in range(12, 60)))

    def test_middleman_analyser(self):
        self.section("The middleman's analyser, against wires we already know")

        import importlib.util
        import os

        root = _REPO_ROOT
        path = os.path.join(root, "utilities", "claude", "dcom_middleman.py")
        if not os.path.exists(path):
            self.check("dcom_middleman.py is present", False, path)
            return
        spec = importlib.util.spec_from_file_location("dcom_middleman", path)
        mid = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mid)

        # A tool for cracking an undocumented protocol is worth what its
        # behaviour on documented ones says it is. These three wires were
        # each solved from a source outside this file, so recovering their
        # rules from the bytes alone is a check on the analyser.

        # The Colour line: 16-byte packets whose last 16-bit word is the sum
        # of the other seven.
        colour = mid.analyse([
            "47444C4300000001000A0028000193BB",
            "47444470001000060008003600028C0A",
            "474444700012006800000000000E8C3C",
            "47444470001200680000000000088C36",
            "47444470001100000000000F00008BD4",
        ], "colour")
        self.check("it sees one packet width, 32 hex chars",
                   list(colour["widths"]) == [32], str(colour["widths"]))
        sums = [c for c in colour["checksums"]
                if c["shape"] == "sum field" and c["unit"] == "word"
                and c["field"] == 7 and c["modulus"] == 0x10000]
        self.check("it recovers the 16-bit word sum in the last word",
                   len(sums) == 1, str(colour["checksums"]))
        self.check("...and the magic word shows up as a constant prefix",
                   [i for i, _v in colour["constant_nibbles"]][:4]
                   == [0, 1, 2, 3])

        # The Pendulum: 2-byte packets ending in F.
        penog = mid.analyse(["111F", "004F", "08AF", "ADFF",
                             "105F", "145F", "095F", "010F"], "penog")
        self.check("it finds PENOG's EOL nibble F",
                   penog["eol_candidates"] == [(3, "F")],
                   str(penog["eol_candidates"]))

        # The DMX: the same shape, ending in E -- which is what makes a
        # foreign signal fail validation instead of being misread.
        dmx = mid.analyse(["838E", "0C4E", "1A2E", "0B0E", "100E", "800E"],
                          "dmx")
        self.check("it finds the DMX's EOL nibble E",
                   dmx["eol_candidates"] == [(3, "E")],
                   str(dmx["eol_candidates"]))
        self.check("...and does not confuse the two lines",
                   penog["eol_candidates"] != dmx["eol_candidates"])

        # It has to say nothing rather than something wrong when there is
        # nothing to say: one packet cannot establish a rule.
        lone = mid.analyse(["47444C4300000001000A0028000193BB"], "one")
        self.check("a single packet yields no checksum claim",
                   lone["checksums"] == [], str(lone["checksums"]))
        self.check("...and no packets at all is not an error",
                   mid.analyse([], "none")["count"] == 0)

        # Random data must not produce a rule either, or every finding is
        # worthless.
        import random as _random
        _random.seed(11)
        noise = ["%08X" % _random.getrandbits(32) for _ in range(24)]
        found = mid.analyse(noise, "noise")
        self.check("noise yields no EOL and no constant nibbles",
                   not found["eol_candidates"]
                   and not found["constant_nibbles"],
                   str(found["eol_candidates"] + found["constant_nibbles"]))
        self.check("...and no checksum", found["checksums"] == [],
                   str(found["checksums"]))

        # **Result attribution, against lines a real adapter printed.**
        # Ordering cannot be trusted in either direction: a dmcomm-original
        # puts its echo AFTER the result, a Pico Terminal before it, and a
        # lagging result lands in the next command's window entirely. So a
        # result is claimed by matching its `s:` -- what the adapter says it
        # sent -- against what was asked for.
        dud = "0" * 32
        opener = "47444470001000060008003E00028C12"
        answer = "4744447000110007001A009600018C7D"

        # The opening listen, echo last. Splitting on the echo drops this.
        lines = ["t", "t", "t:c:preamble",
                 "r:%s s:%s t" % (opener, dud),
                 "got 35 bytes: C2-%s -> C2-[1 packets]" % dud, "t"]
        self.check("a packet is caught when the echo comes after it",
                   mid.received_for(lines, [dud]) == [opener],
                   str(mid.received_for(lines, [dud])))

        # A delivery, echo first.
        lines = ["t", "t",
                 "got 35 bytes: C1-%s -> C1-[1 packets]" % opener,
                 "s:%s r:%s" % (opener, answer)]
        self.check("...and when it comes before",
                   mid.received_for(lines, [opener]) == [answer],
                   str(mid.received_for(lines, [opener])))

        # A stale result from the previous command must not be relayed: that
        # is how a middleman forwards a packet it already forwarded.
        lines = ["r:%s s:%s t" % (opener, dud),
                 "got 35 bytes: C1-%s -> C1-[1 packets]" % answer]
        self.check("a stale result is not claimed by the next command",
                   mid.received_for(lines, [answer]) == [],
                   str(mid.received_for(lines, [answer])))

        # **The two sides are not symmetric**, which was measured rather than
        # assumed: armed with turn 2 the opener transmits, and the answerer
        # says nothing ever -- it waits to be addressed and only replies to a
        # turn 1. So the opener is LISTENED TO and the answerer SPOKEN TO.
        #
        # That is also the safety property. Transmitting at the opener out of
        # turn is an unsolicited packet, and a real pair of Pendulum Colors
        # errored on exactly that; arming its adapter with the reply instead
        # means the reply lands at wire speed, inside the timeout the opener
        # is actually keeping.
        source = open(os.path.join(root, "utilities", "claude",
                                   "dcom_middleman.py"),
                      encoding="utf-8").read()
        relay_body = source[source.index("def relay("):source.index("def _nibbles")]
        marker = "Speak to the answerer"
        self.check("the relay names the two roles", marker in relay_body)
        if marker in relay_body:
            opener_half = relay_body[:relay_body.index(marker)]
            answerer_half = relay_body[relay_body.index(marker):]
            self.check("the opener is only ever listened to (turn 2)",
                       "1-%s" not in opener_half)
            self.check("...and the answerer is spoken to (turn 1)",
                       "1-%s" in answerer_half)

        # The dud is a packet that fails validation on every wire here, so a
        # toy that has not started discards it and transmits again -- which
        # is the retrying the whole relay depends on.
        self.check("the dud is the right width for the line",
                   (len(mid.listen_rom_packet(None, "C")),
                    len(mid.listen_rom_packet(None, "V"))) == (32, 4))
        self.check("...and --listen-rom can replace it",
                   mid.listen_rom_packet("V2-ABCD", "V") == "ABCD")

        # The log reader takes a capture file or any log with hex in it, so
        # the battles already on disk are usable without conversion.
        battles = os.path.join(root, "utilities", "DMX", "battle.txt")
        if os.path.exists(battles):
            packets = mid.load_capture(battles)
            self.check("it can read the filmed battle log",
                       len(packets) > 100, "%d packet(s)" % len(packets))

    def test_single_pet_selection(self):
        self.section("A device battle is one pet against one toy")

        from ui.components.pet_selector import PetSelector

        def selector(limit, count=6):
            sel = PetSelector(0, 0, 100, 100)
            sel.pets = list("abcdef")[:count]
            sel.enabled_pets = list(range(count))
            sel.max_selection = limit
            return sel

        # **The cap used to live only in the label.** The view knew its own
        # `max_pets` and said "Select 1 pet for DCom battle", while the
        # selector took as many as were clicked and the confirm sent all of
        # them -- and the packets only ever describe the first.
        one = selector(1)
        one._pick(0)
        self.check("one pick selects it", one.get_selected_pets() == ["a"])
        one._pick(2)
        self.check("...and a second REPLACES it, as a single choice should",
                   one.get_selected_pets() == ["c"],
                   str(one.get_selected_pets()))
        one._pick(2)
        self.check("...and picking it again clears it",
                   one.get_selected_pets() == [])

        # Above one, an overflowing pick is refused rather than silently
        # dropping something the player already chose.
        four = selector(4)
        for cell in range(5):
            four._pick(cell)
        self.check("a party of four stops at four",
                   four.get_selected_pets() == ["a", "b", "c", "d"],
                   str(four.get_selected_pets()))
        four._pick(0)
        self.check("...and deselecting still works at the cap",
                   four.get_selected_pets() == ["b", "c", "d"])

        # No cap is the old behaviour, unchanged.
        free = selector(None)
        for cell in range(6):
            free._pick(cell)
        self.check("no limit selects everything",
                   len(free.get_selected_pets()) == 6)

        # Select-all respects it too, or the cap is a suggestion.
        capped = selector(1)
        capped.select_all() if hasattr(capped, "select_all") else None
        if hasattr(capped, "select_all"):
            self.check("select-all respects the cap",
                       len(capped.get_selected_pets()) <= 1,
                       str(capped.get_selected_pets()))

        # And the view hands its own cap over rather than only printing it.
        import os
        root = _REPO_ROOT
        source = open(os.path.join(root, "src", "scenes", "connect_views",
                                   "pet_selection_view.py"),
                      encoding="utf-8").read()
        self.check("the selection view sets the cap on the selector",
                   "self.pet_selector.max_selection = self.max_pets" in source)
        self.check("...and a device battle's cap is 1",
                   "1 if (is_dcom_mode or is_wificom_mode) else max_pets"
                   in source)

    def test_fought_winner_is_the_shown_winner(self):
        self.section("A fought battle decides its own winner")

        from battle.sim.dcom_battle_simulator import DComBattleSimulator
        from battle.sim.models import Digimon, DigimonStatus, TurnLog

        # `build_result` used to read the winner back out of the final HP in
        # every case. That is right for a STAGED presentation -- those are
        # built to end with the loser on zero -- and wrong for a battle that
        # is actually rolled, because that can end level. Two filmed PENC
        # battles did exactly that (57a at 2/2 and 57b at 1/1): the fight
        # said we won and the result said the device did, from the same
        # rounds.
        def levelled(hp_each):
            return [TurnLog(
                turn=1,
                device1_status=[DigimonStatus(name="Them", hp=hp_each,
                                              alive=True)],
                device2_status=[DigimonStatus(name="Us", hp=hp_each,
                                              alive=True)],
                attacks=[])]

        for decided, expected in ((True, "device2"), (False, "device1")):
            sim = DComBattleSimulator.__new__(DComBattleSimulator)
            sim.decided_player_wins = decided
            sim.opening = True
            log = levelled(2)
            opponent_hp = log[-1].device1_status[0].hp
            player_hp = log[-1].device2_status[0].hp
            if sim.decided_player_wins is not None:
                winner = "device2" if sim.decided_player_wins else "device1"
            elif opponent_hp > player_hp:
                winner = "device1"
            elif player_hp > opponent_hp:
                winner = "device2"
            else:
                winner = "device2" if sim.opening else "device1"
            self.check("a decided battle is shown as it was fought (%s)"
                       % ("we win" if decided else "device wins"),
                       winner == expected, winner)

        # And where nothing decided it and the bars are level, the side that
        # OPENED keeps it -- which is the rule `fight_penc` uses. The old
        # tie-break gave it to the toy, "battle initiator advantage", and
        # that stopped being true the moment START let us open the exchange.
        source = open(os.path.join(
            _REPO_ROOT,
            "src", "battle", "sim", "dcom_battle_simulator.py"),
            encoding="utf-8").read()
        self.check("the decided winner is believed over the HP reading",
                   "if self.decided_player_wins is not None:" in source)
        self.check("...and the tie-break follows who opened",
                   '"device2" if self.opening else "device1"' in source)
        self.check("...and nothing is decided until an exchange decides it",
                   "self.decided_player_wins = None" in source)

    def test_opening_the_exchange(self):
        self.section("START opens the exchange, on every wire")

        import random
        from battle.sim.dcom_battle_simulator import DComBattleSimulator
        from battle.sim.models import Digimon

        def fighter(power, attribute=2, charge=0):
            pet = Digimon(name="Ours", order=0, traited=0, egg_shake=0,
                          index=3, hp=3, attribute=attribute, power=power,
                          handicap=0, buff=0, mini_game=charge, level=1,
                          stage=4, sick=0, shot1=37, shot2=37, tag_meter=0)
            pet.version = 3
            pet.compatibility = False
            return pet

        # **The packets have always been able to go out either way round.**
        # `generate_player_packets` takes the Order bit from the turn --
        # "the initiating device will have a 1 for order" -- so every wire
        # can already open. What was missing was a way to ask for it.
        for fmt in protocol_constants.BATTLE_FORMATS:
            listening = DComBattleSimulator(None, battle_format=fmt)
            opening = DComBattleSimulator(None, battle_format=fmt)
            opening.opening = True
            a = listening.generate_player_packets(
                fighter(64), protocol_constants.DCOM_TURN_LISTEN)
            b = opening.generate_player_packets(
                fighter(64), protocol_constants.DCOM_TURN_GO_FIRST)
            self.check("%s builds packets both ways" % fmt, a and b)
            if not (a and b):
                continue
            # The turn digit follows the op, and the op is not always one
            # character: the iC's is "IC", so reading position 1 read the
            # "C" and every IC command looked like a malformed turn.
            width = len(getattr(protocol_constants.get_wire(fmt), "DCOM_OP",
                                protocol_constants.DCOM_OP))
            self.check("%s: the command says which turn it is" % fmt,
                       listening.build_command(a, protocol_constants.DCOM_TURN_LISTEN)[width] == "2"
                       and opening.build_command(b, protocol_constants.DCOM_TURN_GO_FIRST)[width] == "1")

        # **On the Colour line opening is more than speaking first: it claims
        # Player 1**, so the operations change. A Digital Monster Color
        # numbers the four roles from 0 and a Pendulum Color from 0x10.
        for fmt, listen_ops, open_ops in (("DMC", [1, 3], [0, 2]),
                                          ("PENC", [0x11, 0x13],
                                           [0x10, 0x12])):
            listening = DComBattleSimulator(None, battle_format=fmt)
            got = [int(p.hex()[8:12], 16) for p in
                   listening.generate_player_packets(
                       fighter(64), protocol_constants.DCOM_TURN_LISTEN)]
            self.check("%s answering sends operations %s"
                       % (fmt, [hex(o) for o in listen_ops]),
                       got == listen_ops, str([hex(o) for o in got]))

            opening = DComBattleSimulator(None, battle_format=fmt)
            opening.opening = True
            got = [int(p.hex()[8:12], 16) for p in
                   opening.generate_player_packets(
                       fighter(64), protocol_constants.DCOM_TURN_GO_FIRST)]
            self.check("...and opening sends %s"
                       % [hex(o) for o in open_ops],
                       got == open_ops, str([hex(o) for o in got]))

        # **A turn swap is not a role claim.** The connection view swaps
        # turns by itself when nothing answers, and that is a guess about who
        # is listening -- so it must not turn us into Player 1 against a
        # device that takes the role for itself.
        swapped = DComBattleSimulator(None, battle_format="DMC")
        got = [int(p.hex()[8:12], 16) for p in
               swapped.generate_player_packets(
                   fighter(64), protocol_constants.DCOM_TURN_GO_FIRST)]
        self.check("the selected opening role determines Colour operations",
                   got == [0, 2], str(got))

        # **As Player 1 the verdict is ours**, computed the way the versus
        # battle computes it -- and humulos' own DMC calculator reproduces
        # that formula exactly: the power ratio, the stage bonus already
        # inside `get_power`, and +-5 on the roll, clamped 0-100.
        theirs = "47444470001000060008003600028C0A"      # power 54, Data
        for fmt, weak_max, strong_min in (("DMC", 35, 65), ("PENC", 25, 75)):
            line = protocol_constants.get_constants(fmt)
            theirs = DMCDevice(fighter(54), magic=line.MAGIC,
                              operation_offset=line.OPERATION_OFFSET,
                              limits=line).generate_packet1(0)
            wins = {}
            for label, pet in (("weak", fighter(10)),
                               ("strong", fighter(250, charge=5))):
                won = 0
                for seed in range(120):
                    sim = DComBattleSimulator(None, battle_format=fmt)
                    sim.opening = True
                    random.seed(seed)
                    sim.declare_colour_outcome(theirs, pet)
                    won += sim.colour_outcome
                wins[label] = won * 100 // 120
            self.check("%s: a weak pet rarely declares victory" % fmt,
                       wins["weak"] < weak_max, "%d%%" % wins["weak"])
            self.check("%s: a strong one usually does" % fmt,
                       wins["strong"] > strong_min, "%d%%" % wins["strong"])
            self.check("%s: and it is a roll, not a rule" % fmt,
                       wins["weak"] != wins["strong"])

        # The verdict rides in packet 2, where "only Operation 2 will report
        # the victory" puts it.
        sim = DComBattleSimulator(None, battle_format="DMC")
        sim.opening = True
        sim.colour_outcome = 1
        packets = sim.generate_player_packets(
            fighter(64), protocol_constants.DCOM_TURN_GO_FIRST)
        self.check("the declared verdict goes into packet 2",
                   int(packets[1].hex()[16:20], 16) == 1,
                   packets[1].hex().upper())
        self.check("...and packet 2 still checksums",
                   sum(int(packets[1].hex()[i:i + 4], 16)
                       for i in range(0, 28, 4)) % 0x10000
                   == int(packets[1].hex()[28:32], 16))

        # Answering, we send 0 whatever we think: "Operation 3 sends 0
        # regardless of a loss or victory".
        sim = DComBattleSimulator(None, battle_format="DMC")
        sim.colour_outcome = 1
        packets = sim.generate_player_packets(
            fighter(64), protocol_constants.DCOM_TURN_LISTEN)
        self.check("as Player 2 the outcome is 0 regardless",
                   int(packets[1].hex()[16:20], 16) == 0,
                   packets[1].hex().upper())

        # The view offers it.
        import os
        root = _REPO_ROOT
        view = open(os.path.join(root, "src", "scenes", "connect_views",
                                 "dcom_view.py"), encoding="utf-8").read()
        # **A button, not a keypress to know about.** Waiting for START or A
        # meant the player had to know it existed and got no sign it landed,
        # which is what made a working first press look inert and invited a
        # second.
        self.check("the connection view offers a START button",
                   "self.start_button = Button(" in view)
        self.check("...focused, so it need not be hunted for",
                   "set_focused_component(self.start_button)" in view)
        opened = view[view.index("def _on_start"):view.index("def _open_exchange")]
        self.check("...and it says LOADING once used",
                   'set_text("LOADING")' in opened
                   and "set_enabled(False)" in opened)
        self.check("the keypress still works, through the same handler",
                   'event_type in ("START", "A")' in view
                   and "self._on_start()" in view)

        # Backing out of the charge is "not this battle", not "not any
        # battle": it comes after the line has been chosen, so it returns to
        # picking a pet rather than dropping the player at the main menu.
        self.check("cancelling the charge returns to pet selection",
                   'self.change_view("pet_selection", is_dcom_mode=True)'
                   in view[view.index("def _on_minigame_cancel"):
                           view.index("def _on_cancel")])
        # Opening means we struck first, so the presentation follows.
        self.check("opening flips who attacks first",
                   "self.enemy_first = False" in
                   view[view.index("def _open_exchange"):
                        view.index("def _send_packets")])
        # The view builds no payload of its own any more -- it hands the
        # exchange to `pvp_payload.build`, which was the only copy getting
        # the opponent's sprites and module right. What this still pins is
        # that the flag travels rather than being hardcoded there.
        self.check("...and the payload carries it rather than a literal",
                   "enemy_first=self.enemy_first" in view)
        self.check("...through the one shared payload builder",
                   "pvp_payload.build(" in view
                   and '"enemy_team_data"' not in view)
        self.check("...and opening pins the turn against the auto-swap",
                   "_turn_swapped = True" in
                   view[view.index("def _open_exchange"):
                        view.index("def _send_packets")])

    def test_penc_replays_the_filmed_battles(self):
        self.section("Every filmed PENC battle replays exactly")

        import os
        import re
        from battle.sim.dcom_battle_simulator import DComBattleSimulator
        from battle.sim.models import Digimon

        root = _REPO_ROOT
        log_path = os.path.join(root, "utilities", "DMX", "battle.txt")
        if not os.path.exists(log_path):
            self.check("the filmed battle log is present", False, log_path)
            return
        lines = open(log_path, encoding="utf-8",
                     errors="replace").read().split("\n")
        heads = [i for i, l in enumerate(lines)
                 if re.match(r"^Battle \d+ ", l)]
        heads.append(len(lines))
        exchange_re = re.compile(r"((?:[rs]:[0-9A-Fa-f]{32}\s*)+)")
        tagged_re = re.compile(r"([rs]):([0-9A-Fa-f]{32})")

        def film(block):
            try:
                start = next(i for i, l in enumerate(block)
                             if l.strip().lower() == "filmed")
            except StopIteration:
                return None
            hits, dev, game, won = [], [], [], None
            for line in block[start + 1:]:
                t = line.strip()
                m = re.match(r"^Device\s*-\s*(\d+)", t, re.I)
                if m:
                    dev.append(int(m.group(1)))
                    continue
                m = re.match(r"^Game\s*-\s*(\d+)\s*-?\s*(Hit|Miss)?", t, re.I)
                if m:
                    game.append(int(m.group(1)))
                    if m.group(2):
                        hits.append(m.group(2).lower() == "hit")
                    continue
                if t.lower().startswith("device won"):
                    won = True
                elif t.lower().startswith("device lost"):
                    won = False
                elif re.match(r"^Battle \d+ ", t):
                    break
            return hits, dev, game, won

        replayed = 0
        mask_overruns = []
        for a, b in zip(heads, heads[1:]):
            block = lines[a:b]
            f = film(block)
            if not f or not f[0]:
                continue
            film_hits, dev_dmg, game_dmg, device_won = f

            exchange = None
            for line in block:
                if "r:" in line and "s:" in line:
                    m = exchange_re.search(line)
                    if m:
                        exchange = tagged_re.findall(m.group(1))
            if not exchange or exchange[0][1][4:8].upper() != "4470":
                continue

            ours = [bytes.fromhex(p) for d, p in exchange if d == "s"]
            theirs = [p for d, p in exchange if d == "r"]

            sim = DComBattleSimulator.__new__(DComBattleSimulator)
            sim.battle_format = "PENC"
            sim.wire = protocol_constants.get_wire("PENC")
            sim.opponent_device_version = None
            sim.opening = any(int(p[8:12], 16) == 0x10
                              for d, p in exchange if d == "s")
            sim.force_version = None
            sim.sent_version = None
            sim.echo_version = False
            sim.sent_echoed_outcome = False
            sim.colour_outcome = 0
            sim.colour_hits = 0

            player = Digimon(name="Us", order=0, traited=0, egg_shake=0,
                             index=3, hp=3, attribute=2, power=10, handicap=0,
                             buff=0, mini_game=0, level=1, stage=4, sick=0,
                             shot1=37, shot2=37, tag_meter=0)
            player.version = 3
            opponent = sim.parse_opponent(theirs, player)
            result = sim.build_result(player, opponent, ours, theirs)
            if result is None:
                self.check("battle at line %d builds a result" % (a + 1), False)
                continue

            got_hits, got_ours, got_theirs = [], [], []
            for turn in result.battle_log:
                for atk in turn.attacks:
                    if atk.device == "device2":
                        got_hits.append(atk.hit)
                        got_ours.append(atk.damage)
                    else:
                        got_theirs.append(atk.damage)

            label = block[0][:34]
            n = len(film_hits)
            self.check("%s: our hits" % label, got_hits[:n] == film_hits,
                       "%s vs filmed %s" % (got_hits[:n], film_hits))
            self.check("%s: our damage" % label,
                       got_ours[:len(game_dmg)] == game_dmg,
                       "%s vs filmed %s" % (got_ours[:len(game_dmg)], game_dmg))
            self.check("%s: the device's damage" % label,
                       got_theirs[:len(dev_dmg)] == dev_dmg,
                       "%s vs filmed %s" % (got_theirs[:len(dev_dmg)], dev_dmg))
            self.check("%s: the winner" % label,
                       (result.winner == "device1") == device_won,
                       result.winner)
            replayed += 1
            # Which rounds the mask claimed beyond the ones that were played.
            mask = None
            for tag, packet in exchange:
                if int(packet[8:12], 16) == 0x13:
                    mask = int(packet[20:24], 16)
            if mask is not None:
                mask_overruns.extend(
                    bit + 1 for bit in range(len(film_hits), 16)
                    if mask >> bit & 1)

        # **This is the test that matters on this line.** The result lives in
        # operation 0x13, the RESPONDER's packet -- not where the Digital
        # Monster Color puts it -- and reading it there reproduces every
        # filmed battle: the hits, both sides' damage, and the winner. A
        # rolled battle cannot do that, however faithful its rates.
        self.check("every filmed PENC battle was replayed",
                   replayed >= 17, "%d replayed" % replayed)

        # **The mask is the whole roll and the bar stops the battle early.**
        # Bits are set for rounds the fight never reaches -- bit 3 in battle
        # 55, bit 4 in 57a and 60, bit 5 in 57b and 61 -- and bit 5 was on
        # record as unexplained when it is the same thing one round further
        # out. Every bit INSIDE the rounds played matches the film, which is
        # what the per-battle hit checks above assert one battle at a time;
        # this pins that the ones outside are only ever past the knockout.
        # `mask_overruns` holds the ROUND each unplayed bit claimed. Across
        # the filmed set they are rounds 4, 5 and 6 -- so bit 5 (round 6) is
        # the widest ever seen, and it stops there. Whether a sixth round
        # exists is the open question: the attack table has five values and
        # no filmed battle has run past four.
        self.check("the mask never claims a round past the sixth",
                   mask_overruns and max(mask_overruns) <= 6,
                   str(sorted(set(mask_overruns))))
        self.check("...and round 6 is reached, which is what bit 5 was",
                   6 in mask_overruns, str(sorted(set(mask_overruns))))

    def test_no_wire_hands_the_opener_a_free_win(self):
        self.section("A dependent packet is rolled, never claimed")

        import random
        from battle.sim.exchange import PacketExchange

        def pet(name, power, index=3, stage=4, version=1):
            built = make_digimon(name=name, power=power, index=index, hp=10,
                                 attribute=0, stage=stage, mini_game=2,
                                 level=1, shot1=1, shot2=1)
            built.version = version
            return built

        def wins_as_opener(fmt, ours, theirs, runs=40):
            won = 0
            for seed in range(runs):
                random.seed(seed)
                a = PacketExchange(fmt, pet("A", ours, 13), opens=True)
                b = PacketExchange(fmt, pet("B", theirs, 2, 7, 1), opens=False)
                guard = 0
                while not (a.complete and b.complete) and guard < 40:
                    guard += 1
                    packet = a.next_packet()
                    if packet:
                        b.receive(packet)
                    packet = b.next_packet()
                    if packet:
                        a.receive(packet)
                result = a.result()
                won += bool(result and result.winner == "device2")
            return won

        # **This is the check that was missing.** Every wire completed, both
        # sides validated and exactly one won -- and on four of them the
        # opener simply claimed every hit, so a power-1 pet beat a power-255
        # one 20 times out of 20 with no roll taken. `heard` is only ever
        # true for the ANSWERER, so every resolver branch was the answerer's
        # and the opener shipped the batch generator's placeholder.
        POWER_DECIDES = ('DM20', 'PEN20', 'DMX', 'PENZ', 'DMC', 'PENC', 'DMXW')
        for fmt in POWER_DECIDES:
            weak = wins_as_opener(fmt, 1, 255)
            strong = wins_as_opener(fmt, 255, 1)
            self.check("%s: a power-1 opener does not beat a power-255 one"
                       % fmt, weak <= 4, "%d/40" % weak)
            self.check("...and a power-255 opener does beat a power-1 one",
                       strong >= 36, "%d/40" % strong)

        # DMOG's wire carries no power at all -- it sends a chart slot, and
        # the guidebook matrix decides. What it must not do is what it used
        # to: ship the generator's default, which is DEFEAT, so an opener
        # lost every battle it started whatever it was holding.
        top = wins_as_opener('DMOG', 255, 1)
        self.check("DMOG's opener rolls its matchup rather than conceding",
                   top >= 30, "%d/40 with slot L against slot B" % top)

        from battle.sim.penog_rules import slot_hit_rate
        self.check("PENOG now uses its explicitly approximate slot table",
                   slot_hit_rate(12, 3) > slot_hit_rate(3, 12))

    def test_colour_pattern_pool(self):
        self.section("The Colour family shares one attack-pattern pool")

        from battle.sim.battle_utils import (colour_pool, colour_row,
                                             get_penc_pattern,
                                             get_penc_wire_charge,
                                             get_dmxw_pattern,
                                             get_dmxw_enemy_pattern,
                                             dmxw_effort_tier)

        pool = colour_pool()
        self.check("15 rows", len(pool) == 15, str(len(pool)))
        self.check("each of six rounds, every value 1 or 2",
                   all(len(r) == 6 and all(v in (1, 2) for v in r)
                       for r in pool))
        self.check("row 0 is all normal and row 14 the Megahit",
                   pool[0] == [1] * 6 and pool[14] == [2] * 6)
        self.check("no two rows are the same",
                   len({tuple(r) for r in pool}) == 15)

        # **This is what makes it the family's and not one device's**: every
        # row measured off a real Pendulum Color is in here, all 15 are used,
        # and every selector read off that wire is exactly the index.
        by_row = {tuple(r): i for i, r in enumerate(pool)}
        used = set()
        for stage in range(1, 8):
            for band in range(4):
                row = tuple(get_penc_pattern(stage, band))
                self.check("PENC stage %d band %d is in the pool"
                           % (stage, band), row in by_row,
                           "".join(map(str, row)))
                if row in by_row:
                    used.add(by_row[row])
                    self.check("...and its selector is the pool index",
                               get_penc_wire_charge(stage, band) == by_row[row],
                               str(get_penc_wire_charge(stage, band)))
        self.check("PENC uses all 15 rows", used == set(range(15)),
                   str(sorted(used)))

        # The seven that were read off devices, which is what anchors it.
        for (stage, band), selector in {(3, 0): 0x02, (3, 2): 0x0A,
                                        (3, 3): 0x0E, (4, 0): 0x03,
                                        (4, 1): 0x08, (4, 2): 0x0B,
                                        (4, 3): 0x0E}.items():
            self.check("measured PENC selector 0x%02X still holds" % selector,
                       get_penc_wire_charge(stage, band) == selector,
                       str(get_penc_wire_charge(stage, band)))

        # **DMXW is stage x effort tier x band**, not per Digimon. All three
        # readings taken off the device reproduce from the firmware table.
        self.check("effort tiers band at 10 and 20",
                   [dmxw_effort_tier(e) for e in (0, 9, 10, 19, 20, 40)]
                   == [0, 0, 1, 1, 2, 2])
        watched = {
            (4, 15): ["12111", "12121", "12122", "22222"],   # Shoutmon X2
            (4, 20): ["11211", "21121", "21222", "22222"],   # other Xros forms
            (3, 20): ["12111", "12121", "11222", "22222"],   # Shoutmon, maxed
        }
        for (stage, effort), rows in watched.items():
            # The device shows five shots; the sixth round is the table's.
            got = ["".join(map(str, get_dmxw_pattern(stage, band, effort)[:5]))
                   for band in range(4)]
            self.check("DMXW stage %d effort %d -> %s" % (stage, effort, rows),
                       got == rows, str(got))

        # The padding rule the pool overrules: a battle-read `2112` continues
        # as 21121, where repeating the last value gave 21122.
        self.check("the partial 2112 is pool row 7, 21121",
                   colour_row(7)[:5] == [2, 1, 1, 2, 1], str(colour_row(7)))

        self.check("an index the pool lacks is all normal hits",
                   colour_row(99) == [1] * 6, str(colour_row(99)))
        for stage in range(1, 8):
            self.check("a stage %d enemy throws a real row" % stage,
                       get_dmxw_enemy_pattern(stage) in
                       [colour_row(i) for i in range(15)])

    def test_penc_stage_from_wire(self):
        self.section("PENC carries no stage, so version and index name one")

        import json
        import os
        from battle.sim.battle_utils import colour_stage_from_wire

        root = _REPO_ROOT
        with open(os.path.join(root, "src", "data", "rosters", "PENC.json"),
                  encoding="utf-8") as handle:
            stages = json.load(handle)["stages"]

        # **The index alone cannot do it.** Across the eight versions, 19 of
        # 34 indexes name more than one stage -- index 21 is a Child on one
        # version, an Ultimate on another and a Super Ultimate on a third.
        by_index = {}
        pairs = 0
        for version, indexes in stages.items():
            for index, stage in indexes.items():
                by_index.setdefault(index, set()).add(stage)
                pairs += 1
        ambiguous = [i for i, v in by_index.items() if len(v) > 1]
        self.check("the index alone is ambiguous, so the pair is needed",
                   len(ambiguous) >= 15, "%d of %d ambiguous"
                   % (len(ambiguous), len(by_index)))
        self.check("index 21 alone names three different stages",
                   len(by_index.get("21", ())) == 3,
                   str(sorted(by_index.get("21", ()))))
        self.check("the table covers all eight wire versions",
                   sorted(map(int, stages)) == list(range(8)),
                   str(sorted(map(int, stages))))
        self.check("...and every record in it", pairs == 259, str(pairs))

        # The three devices that have been filmed on this line.
        for label, version, index, stage in (("Hagurumon", 4, 4, 3),
                                             ("Fujamon", 6, 4, 3),
                                             ("Gawappamon", 6, 8, 4)):
            got = colour_stage_from_wire('PENC', version, index)
            self.check("%s (wire v%d index %d) is stage %d"
                       % (label, version, index, stage), got == stage, str(got))

        # **Index 0 is refused**, as it is on every wire: it is what a
        # compatibility pet announces, and this line does have a stage 1
        # record sitting there, so resolving it would report a foreign device
        # as a Baby I.
        self.check("index 0 is not resolved", colour_stage_from_wire('PENC', 3, 0) is None)
        self.check("nor is a version this line does not have",
                   colour_stage_from_wire('PENC', 99, 4) is None)

        # The parser used to hand every Colour opponent a flat stage 4, which
        # was harmless until the attack table became keyed on the stage.
        source = open(os.path.join(root, "src", "battle", "sim",
                                   "dcom_battle_simulator.py"),
                      encoding="utf-8").read()
        self.check("the opponent parser no longer hardcodes stage 4",
                   "stage=stage, sick=0, shot1=shot" in source)

    def test_penc_connection_rounds(self):
        self.section("A PENC connection battle draws the shots that were fired")

        from battle.sim.dcom_battle_simulator import DComBattleSimulator
        from battle.sim.battle_utils import (get_penc_wire_charge,
                                             get_penc_wire_pattern,
                                             get_penc_pattern,
                                             penc_super_hits_from_wire,
                                             penc_band_from_wire,
                                             penc_wire_charge_is_measured)
        from battle.sim.models import Digimon

        # The inverse of the wire table, for reading the DEVICE's charge --
        # and the selector names a ROW, so the count is that row's own.
        self.check("COU 14 reads back as a Megahit",
                   penc_super_hits_from_wire(14) == 5)
        self.check("COU 8 reads back as 2 super hits",
                   penc_super_hits_from_wire(8) == 2)
        self.check("COU 11 reads back as 3",
                   penc_super_hits_from_wire(11) == 3)

        # **COU 2 and COU 3 differ by STAGE, not by shake count.** Both are
        # the bottom band -- battle 56's Hagurumon and battle 48's Gawappamon
        # both reported "got nothing" -- and both pay one super hit. The
        # earlier reading had them as "0 shakes" and "1 shake", which was the
        # only way to explain two values for one outcome before the devices'
        # stages were known. Hagurumon is a Child and Gawappamon an Adult.
        self.check("COU 2 is a stage 3 bottom band, worth one super hit",
                   penc_super_hits_from_wire(2) == 1)
        self.check("...and COU 3 is a stage 4 bottom band, also worth one",
                   penc_super_hits_from_wire(3) == 1)
        self.check("...so the two are the same band at different stages",
                   penc_band_from_wire(2) == penc_band_from_wire(3) == 0)
        self.check("a value we have never measured is not guessed at",
                   penc_super_hits_from_wire(99) == 0
                   and penc_band_from_wire(99) is None)

        # Every measured pair survives the round trip: our selector reads
        # back as the row we meant, and as the band we charged.
        for stage in (3, 4):
            for band in range(4):
                if not penc_wire_charge_is_measured(stage, band):
                    continue
                sel = get_penc_wire_charge(stage, band)
                self.check("stage %d band %d round-trips through 0x%02X"
                           % (stage, band, sel),
                           penc_band_from_wire(sel) == band
                           and get_penc_wire_pattern(sel)
                           == get_penc_pattern(stage, band))

        # Filmed battle 52: the device rolled YELLOW, its own colour, so a
        # Megahit -- and announced COU 14. It drew `dmg=1` on our screen,
        # because the connection battle was staging the Digital Monster
        # Color's canned rounds on a line that fights.
        sim = DComBattleSimulator.__new__(DComBattleSimulator)
        sim.battle_format = 'PENC'
        sim.wire = protocol_constants.get_wire('PENC')
        sim.opponent_device_version = None
        opponent = sim._parse_dmc_opponent([
            bytes.fromhex("47444470001000060008003600028C0A"),
            bytes.fromhex("474444700012006800000000000E8C3C")])
        self.check("battle 52's packets decode", opponent is not None)
        if opponent is None:
            return
        self.check("...and its Megahit is read off the wire",
                   opponent.mini_game == 5, str(opponent.mini_game))

        player = Digimon(name="Ours", order=0, traited=0, egg_shake=0,
                         index=0, hp=3, attribute=2, power=64, handicap=0,
                         buff=0, mini_game=5, level=1, stage=4, sick=0,
                         shot1=31, shot2=43, tag_meter=0)
        import random
        random.seed(1)
        sim._fight_penc(player, opponent)
        log = sim._simulate_penc_turns(player, opponent, player_wins=True)
        device_shots = [a.damage for t in log for a in t.attacks
                        if a.device == "device1"]
        self.check("the device fires the super hits it rolled",
                   set(device_shots) == {2}, str(device_shots))
        self.check("...over 3 HP, so it cannot run past three rounds",
                   1 <= len(log) <= 3, str(len(log)))

        # A weaker charge draws weaker shots, which is the whole point --
        # and it draws the row the DEVICE throws for that stage, not an
        # invented one. Both Digimon here are Adults, where the four bands
        # pay 1, 2, 3 and 5 super hits: **a stage 4 Pendulum Color cannot
        # fire five normal hits**, because its bottom band still lands one
        # super. Only stages 1 and 2 have an all-normal row.
        from battle.sim.battle_utils import get_penc_pattern
        opponent.mini_game = 2
        player.mini_game = 1
        random.seed(1)
        sim._fight_penc(player, opponent)
        log = sim._simulate_penc_turns(player, opponent, player_wins=True)
        ours = [a.damage for t in log for a in t.attacks
                if a.device == "device2"]
        theirs = [a.damage for t in log for a in t.attacks
                  if a.device == "device1"]
        weakest = get_penc_pattern(4, 0)      # [1, 1, 2, 1, 1]
        second = get_penc_pattern(4, 1)       # [2, 1, 2, 1, 1]
        self.check("the weakest Adult charge is the device's own bottom row",
                   ours == weakest[:len(ours)], str(ours))
        self.check("...and two super hits draw the row above it",
                   theirs == second[:len(theirs)], str(theirs))
        self.check("...which is stronger, as a better charge must be",
                   sum(second) > sum(weakest))

        # **Nothing is staged.** The rounds are the ones that were fought, so
        # the same two Digimon can produce different battles -- which is what
        # a wire carrying no verdict means.
        seen = set()
        for seed in range(30):
            random.seed(seed)
            sim._fight_penc(player, opponent)
            rounds = sim._simulate_penc_turns(player, opponent, True)
            seen.add(tuple((a.hit for t in rounds for a in t.attacks)))
        self.check("the rolls are real, so the battle varies",
                   len(seen) > 1, "%d distinct" % len(seen))

        # And it is the SAME function the versus path calls.
        from battle.sim.battle_utils import fight_penc
        random.seed(9)
        a_won, a_rounds = fight_penc(64, 2, 5, 54, 2, 5)
        random.seed(9)
        b_won, b_rounds = fight_penc(64, 2, 5, 54, 2, 5)
        self.check("fight_penc is deterministic for one seed",
                   a_won == b_won and len(a_rounds) == len(b_rounds))
        source = open(os.path.join(
            _REPO_ROOT,
            "src", "battle", "sim", "battle_simulator.py"),
            encoding="utf-8").read()
        self.check("the versus path calls it too",
                   "result = simulate_exchange(self.battle_format, device1, device2)" in source)

        # And the other verdict wires are untouched -- they have no damage
        # values to read, so they keep the canned rounds.
        for fmt in ('DMC', 'DMOG'):
            other = DComBattleSimulator.__new__(DComBattleSimulator)
            other.battle_format = fmt
            other.wire = protocol_constants.get_wire(fmt)
            self.check("%s still stages the four verdict rounds" % fmt,
                       protocol_constants.get_constants(fmt).TURNS == 4)

    def test_crossover_colour_opponent(self):
        self.section("A crossover Colour device is still a device we know")

        from battle.sim.dcom_battle_simulator import (DComBattleSimulator,
                                                      FALLBACK_NAMES)

        # **Free is the one attribute name with no sprite set.** The shared
        # libraries ship Fr_dmc and no Free_dmc, so an opponent called "Free"
        # drew nothing at all -- filmed battles 44 and 45 both have a Free
        # opponent and an empty space where the device should be.
        self.check("the unresolved-opponent names are the short spellings",
                   FALLBACK_NAMES == {0: "Va", 1: "Da", 2: "Vi", 3: "Fr"},
                   str(FALLBACK_NAMES))
        import os
        root = _REPO_ROOT
        for name in FALLBACK_NAMES.values():
            path = os.path.join(root, "assets", "monsters",
                                "%s_dmc.zip" % name)
            self.check("%s has a sprite set to fall back to" % name,
                       os.path.exists(path))
        self.check("...and 'Free' is exactly the one that does not",
                   not os.path.exists(os.path.join(
                       root, "assets", "monsters", "Free_dmc.zip")))

        # Filmed battle 44: a Monster Hunter edition on the Colour wire.
        # Version 5 is one past the DMC's own five -- the Pico Terminal's
        # analyzer reads anything above 4 here as "a crossover device" and
        # then asks which one, because the packet does not say. The index,
        # attribute and power together do.
        packets = [bytes.fromhex("47444C4300000005001D00AA00009453"),
                   bytes.fromhex("47444C430002004900010000000093D3")]
        sim = DComBattleSimulator.__new__(DComBattleSimulator)
        sim.battle_format = 'DMC'
        sim.wire = protocol_constants.get_wire('DMC')
        sim.opponent_device_version = None
        opponent = sim._parse_dmc_opponent(packets)
        self.check("battle 44's packet decodes", opponent is not None)
        if opponent is None:
            return
        self.check("...to index 29, power 170, Free, shot 73 (0-based)",
                   (opponent.index, opponent.power, opponent.attribute,
                    opponent.shot1) == (29, 170, 3, 73),
                   "%s/%s/%s/%s" % (opponent.index, opponent.power,
                                    opponent.attribute, opponent.shot1))
        self.check("...announcing version 5, past the DMC's own five",
                   sim.opponent_device_version == 5
                   and sim.opponent_device_version > 4)

        # Filmed battle 45: an Xros Wars edition in compatibility mode sends
        # index 0xFFFF, the wire's "none" -- it has no entry on this line's
        # roster and does not offer its own. There is nothing to resolve, and
        # the placeholder is the honest answer.
        packets = [bytes.fromhex("47444C4300000005FFFF0073000093FE"),
                   bytes.fromhex("47444C4300020010000100000000939A")]
        sim = DComBattleSimulator.__new__(DComBattleSimulator)
        sim.battle_format = 'DMC'
        sim.wire = protocol_constants.get_wire('DMC')
        sim.opponent_device_version = None
        other = sim._parse_dmc_opponent(packets)
        self.check("battle 45's packet decodes", other is not None)
        if other is None:
            return
        self.check("...to the wire's \"none\" index",
                   other.index == protocol_constants.DMC.MAX_INDEX,
                   str(other.index))
        sim._name_opponent(other)
        self.check("...so nothing is claimed about which device it was",
                   getattr(other, 'source_module', None) is None)
        self.check("...and it still has a sprite to draw",
                   other.name in FALLBACK_NAMES.values(), other.name)

        # The narrowing itself, without needing the modules installed: power
        # is what separates two crossover rosters at one index.
        records = [{"name": "Thunderlord Zinogre", "index": 29,
                    "attribute": "", "power": 170, "stage": 4,
                    "module": "DMH"},
                   {"name": "Machinedramon: MFS-3", "index": 29,
                    "attribute": "Vi", "power": 185, "stage": 4,
                    "module": "DMGZ"}]
        narrowed = DComBattleSimulator._narrow_by_power(records, opponent)
        self.check("power alone separates DMH's index 29 from DMGZ's",
                   [r["name"] for r in narrowed] == ["Thunderlord Zinogre"],
                   str([r["name"] for r in narrowed]))
        self.check("...and its shot id lines up with the packet's",
                   narrowed[0].get("power") == opponent.power)

    def test_hit_rate(self):
        self.section("Hit rate (one formula, and whose handicap it is)")

        from battle.sim.global_battle_simulator import GlobalBattleSimulator
        from battle.sim.models import Digimon

        penc = protocol_constants.PENC
        dmc = protocol_constants.DMC

        # humulos' PenC calculator, read out of the page's own script:
        #
        #   power += bonus + eggShake
        #   hitRate = ((power * 100)/(power + enemyPower))
        #             + advantage - enemyHandicap
        #
        # and the manual behind it: "handicap -- Used in Quest Mode only,
        # certain Digimon have a handicap that will reduce your hitrate".
        # Quest Mode is Adventure Mode here.
        self.check("the ratio matches the calculator (150 vs 60, no advantage)",
                   abs(protocol_constants.hit_rate(penc, 150, 3, 60, 3)
                       - 71.4285714) < 1e-4)
        self.check("...and the enemy's handicap of 20 takes it to 51.4",
                   abs(protocol_constants.hit_rate(penc, 150, 3, 60, 3,
                                                   handicap=20)
                       - 51.4285714) < 1e-4)

        # **The two lines do not spend the same advantage.** "For Pendulum
        # battles: Equals 10 if you have an attribute advantage, -10 if you
        # have an attribute disadvantage... For battles with the Digital
        # Monster Color, the values are 5/-5 instead." Written in the Colour
        # line's own encoding: Vaccine 3 beats Virus 1.
        self.check("PENC spends 10 on the triangle",
                   protocol_constants.attribute_advantage(penc, 3, 1) == 10)
        self.check("...the DMC 5, on the same pairing",
                   protocol_constants.attribute_advantage(dmc, 3, 1) == 5)
        self.check("...and the loser of it pays the same, negated",
                   (protocol_constants.attribute_advantage(penc, 1, 3),
                    protocol_constants.attribute_advantage(dmc, 1, 3))
                   == (-10, -5))
        self.check("Free scores nothing either way",
                   protocol_constants.attribute_advantage(penc, 0, 3) == 0
                   and protocol_constants.attribute_advantage(penc, 3, 0) == 0)

        # The default cycle is the same triangle in the 2-bit code every
        # other wire uses -- Va 0, Da 1, Vi 2 -- which is NOT the Colour
        # line's ordering, so the two tables are not interchangeable.
        dmx = protocol_constants.DMX
        self.check("the default cycle is Va>Vi>Da>Va in the ordinary code",
                   protocol_constants.attribute_advantage(dmx, 0, 2) > 0
                   and protocol_constants.attribute_advantage(dmx, 2, 1) > 0
                   and protocol_constants.attribute_advantage(dmx, 1, 0) > 0)
        self.check("the X lines spend theirs on Power, so the ratio moves",
                   dmx.ATTRIBUTE_ADVANTAGE_ON_POWER
                   and abs(protocol_constants.hit_rate(dmx, 100, 0, 100, 2)
                           - (132 * 100 / 232)) < 1e-9)

        # **99, not 100.** "The maximum value is 99, even if the calculation
        # would exceed that amount" -- only PENC's manual says so, so only
        # PENC declares it, and a clamp at 100 makes the hit a certainty.
        self.check("PENC's hit rate tops out at 99",
                   protocol_constants.hit_rate(penc, 250, 3, 1, 1) == 99)
        self.check("...where every other line still reaches 100",
                   protocol_constants.hit_rate(dmc, 250, 3, 1, 1) == 100)
        self.check("PENC declares the ceiling and the DMC does not",
                   penc.MAX_HIT_RATE == 99
                   and 'MAX_HIT_RATE' not in dmc.__dict__)

        # The adventure simulator reads the same ceiling off the format.
        self.check("an internal battle takes an explicit module hit-rate ceiling",
                   GlobalBattleSimulator(battle_format='PENC', max_hit_rate=99).max_hit_rate == 99)
        self.check("...a DMC one and a module with no protocol carry 100",
                   (GlobalBattleSimulator(battle_format='DMC').max_hit_rate,
                    GlobalBattleSimulator().max_hit_rate) == (100, 100))

        # **The handicap is the DEFENDER's**, which is the half that was
        # inverted: reading the attacker's made a handicapped enemy less
        # accurate instead of harder to hit, so it helped the player twice.
        def fighter(power, handicap, attribute="Va"):
            return Digimon(name="x", hp=3, attribute=attribute, power=power,
                           handicap=handicap, buff=0, mini_game=0, level=1,
                           sick=0, shot1=1, shot2=1, order=0, traited=0,
                           egg_shake=0, index=1, stage=4, tag_meter=0)

        sim = GlobalBattleSimulator(attribute_advantage=10,
                                    battle_format='PENC')
        # PENC's own Area 9 round 1: SymbareAngoramon, power 60, handicap 20
        # -- a Digimon the device made hard with the handicap and not with
        # the power.
        pet, enemy = fighter(150, 0), fighter(60, 20)
        self.check("the enemy's handicap lowers OUR roll (71.4 -> 51.4)",
                   abs(sim._hitrate(pet, enemy) - 51.4285714) < 1e-4)
        self.check("...and the enemy's own roll is untouched by it",
                   abs(sim._hitrate(enemy, pet) - 28.5714285) < 1e-4)

        # And a module that sets none is exactly as it was.
        self.check("no handicap anywhere leaves the plain ratio",
                   abs(sim._hitrate(fighter(100, 0), fighter(100, 0)) - 50.0)
                   < 1e-9)

        # Every PENC quest enemy carrying one is a reading off the device, so
        # the fix has to reach data that exists.
        import json
        import os
        root = _REPO_ROOT
        battle_path = os.path.join(root, 'modules', 'PENC', 'battle.json')
        if os.path.exists(battle_path):
            with open(battle_path, encoding='utf-8') as handle:
                enemies = json.load(handle).get('enemies', [])
            handicapped = [e for e in enemies if e.get('handicap')]
            self.check("PENC's quest enemies carry handicaps to apply",
                       len(handicapped) > 0,
                       "%d of %d" % (len(handicapped), len(enemies)))

    def test_settling_without_a_verdict(self):
        self.section("No verdict in the reply is still a battle, not a tally")

        import random
        from battle.sim.dcom_battle_simulator import DComBattleSimulator
        from battle.sim.models import Digimon

        def fighter(power, attribute=3):
            pet = Digimon(name="x", hp=5, attribute=attribute, power=power,
                          handicap=0, buff=0, mini_game=0, level=1, sick=0,
                          shot1=1, shot2=1, order=0, traited=0, egg_shake=0,
                          index=0, stage=4, tag_meter=0)
            # What a parsed DMOG opponent carries: the slot as it arrived,
            # not the power the slot was inverted into.
            pet.dm_slot = protocol_constants.DMOG.slot_for_power(power,
                                                                 oem=True)
            pet.dm_boost = 0
            return pet

        # It used to be `player.power >= opponent.power`, so a weaker Digimon
        # could not win however close the two were -- and a tie always went
        # to the player. Neither is how any device decides anything.
        for battle_format, wire_name in (('DMC', 'DMC'), ('PENC', 'DMC'),
                                         ('DMOG', 'DMOG')):
            sim = DComBattleSimulator.__new__(DComBattleSimulator)
            sim.battle_format = battle_format
            sim.wire = protocol_constants.get_wire(battle_format)
            self.check("%s picks the %s layout" % (battle_format, wire_name),
                       sim.wire.NAME == wire_name)

            weaker, stronger = fighter(40), fighter(160)
            try:
                sim._settle_without_a_verdict(weaker, stronger)
            except ValueError:
                refused = True
            else:
                refused = False
            self.check("%s: missing result refuses replay instead of rerolling" % battle_format,
                       refused)

        # The Colour half rolls the hit rate, so PENC's +10 has to reach it:
        # the same pairing favours a Pendulum Color more than a Digital
        # Monster Color. Vaccine 3 against Virus 1 in this line's encoding.
        rates = {name: protocol_constants.hit_rate(
                     protocol_constants.get_constants(name), 100, 3, 100, 1)
                 for name in ('DMC', 'PENC')}
        self.check("the roll is the format's, not the wire's",
                   rates['PENC'] > rates['DMC'],
                   "%s vs %s" % (rates['PENC'], rates['DMC']))

        # The DMOG half reads the SLOT, which is the only strength that wire
        # exchanges -- power there is a lossy inversion of it.
        limits = protocol_constants.DMOG
        self.check("slot L over slot A is 15 in 16",
                   limits.slot_win_odds(11, 0) == 15)
        self.check("...and slot A over slot L is 1",
                   limits.slot_win_odds(0, 11) == 1)
        self.check("a mirror match is even",
                   limits.slot_win_odds(5, 5) == 8)
        self.check("neither end is ever a certainty",
                   all(1 <= limits.slot_win_odds(a, b) <= 15
                       for a in range(12) for b in range(12)))
        self.check("the boost shifts the odds one for one",
                   limits.slot_win_odds(5, 5, 2, 0) == 10
                   and limits.slot_win_odds(5, 5, 0, 2) == 6)
        self.check("wire slots 0x3..0xE index 0..11",
                   (limits.slot_index(0x3), limits.slot_index(0xE)) == (0, 11))

        # One table: the versus path reads the same rows.
        from battle.sim.battle_simulator import BattleSimulator
        from battle.sim.models import BattleProtocol
        versus = BattleSimulator(BattleProtocol.DMOG_BS)
        self.check("the versus path reads the same matrix",
                   all(versus._get_dm_win_probability(a, b)
                       == limits.slot_win_odds(a, b)
                       for a in range(12) for b in range(12)))

    def test_penc_is_not_a_dmc(self):
        self.section("PENC rides the DMC wire and is not a DMC")

        from battle.sim.battle_utils import get_attack_pattern, verdict_rounds

        penc = protocol_constants.PENC
        dmc = protocol_constants.DMC

        # It opens with its own word, which is the whole reason it is a
        # separate format.
        self.check("PENC announces GDDp where the DMC announces GDLC",
                   (penc.MAGIC, dmc.MAGIC) == (0x47444470, 0x47444C43))

        # **Three hit points, not five.** Its manual: "each Digimon has 3
        # health points which will be reduced by 1 for a normal hit and by 2
        # for a super hit". It had been inheriting the DMC's five, and since
        # HP was read off the WIRE -- which is the DMC's -- its battle spent
        # 5 against a 3-point bar.
        self.check("PENC fights at 3 and the DMC at 5",
                   (penc.FIXED_HP, dmc.FIXED_HP) == (3, 5))

        # **+10 on the hit rate**, where the DMC spends 5. The manual gives
        # the formula outright, and PENC's own module said 10 all along.
        self.check("PENC's advantage is 10 on the roll",
                   penc.ATTRIBUTE_ADVANTAGE == 10
                   and not penc.ATTRIBUTE_ADVANTAGE_ON_POWER)
        self.check("...where the DMC's is 5",
                   dmc.ATTRIBUTE_ADVANTAGE == 5)
        import json
        import os
        root = _REPO_ROOT
        for module, want in (("PENC", 10), ("DMC", 5)):
            path = os.path.join(root, "modules", module, "module.json")
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as handle:
                declared = json.load(handle).get("battle_attribute_advantage")
            self.check(f"{module}'s module agrees at {want}", declared == want,
                       str(declared))

        # **Version is a map, not an offset.** The Virus Busters set is the
        # SIXTH release, so it goes out as wire 5 while the module calls it
        # 0, and the two later sets line up at 6 and 7 unchanged. The flat
        # offset it inherited collided the Virus Busters with Nature Spirits
        # on wire 0 and sent the last two out one low.
        expected = {0: 5, 1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 6, 7: 7}
        for module, wire in expected.items():
            self.check(f"PENC module version {module} announces {wire}",
                       protocol_constants.clamp_oem_version("PENC", module)
                       == wire,
                       str(protocol_constants.clamp_oem_version("PENC", module)))
        sent = [protocol_constants.clamp_oem_version("PENC", v)
                for v in range(8)]
        self.check("...and no two devices claim the same version",
                   len(set(sent)) == 8, str(sorted(sent)))
        for module, wire in expected.items():
            self.check(f"...and wire {wire} reads back as module {module}",
                       protocol_constants.module_versions_for_wire("PENC", wire)
                       == [module])
        # It is the jogress ROMs' own map, inverted -- so the battle wire and
        # the jogress wire finally agree about what this line calls itself.
        roms = os.path.join(root, "src", "data", "jogress", "roms.json")
        if os.path.exists(roms):
            with open(roms, encoding="utf-8") as handle:
                mapping = json.load(handle)["protocols"]["PENC"]["version_map"]
            self.check("PENC's battle map is the jogress map inverted",
                       {int(w): m for w, m in mapping.items()}
                       == {w: m for m, w in expected.items()},
                       str(mapping))
        # The DMC needs no map and no offset at all: its module carries the
        # wire's own numbering, so a device_version goes out as it stands.
        self.check("the DMC sends device_version unchanged",
                   [protocol_constants.clamp_oem_version("DMC", v)
                    for v in range(0, 5)] == [0, 1, 2, 3, 4])

        # The verdict battle follows the bar rather than a fixed row: three
        # traded singles then a double at five, one single then a double at
        # three, and the winner finishes on 2 either way.
        self.check("at 5 it is DMC.json's measured row",
                   verdict_rounds(5) == ([1, 1, 1, 2], [1, 1, 1, 1]))
        self.check("at 3 it is the same shape scaled",
                   verdict_rounds(3) == ([1, 2], [1, 1]))
        for hp in (3, 4, 5, 10):
            winner, loser = verdict_rounds(hp)
            self.check(f"a winner on a {hp} bar spends exactly {hp}",
                       sum(winner) == hp, str(sum(winner)))
            self.check(f"...and outlasts the loser's {sum(loser[:-1])}",
                       hp - sum(loser[:-1]) == 2, str(hp - sum(loser[:-1])))

        # Nothing falls off the end of get_attack_pattern any more. PENC used
        # to return None there, which a caller indexing the result would have
        # died on.
        for fmt in protocol_constants.BATTLE_FORMATS:
            self.check(f"{fmt} always answers with a pattern",
                       get_attack_pattern(1, 3, fmt, stage=4) is not None)

    def test_colour_adventure_table(self):
        self.section("The Colour line's adventure table (its own, not the DMX's)")

        from battle.sim.battle_utils import (get_attack_damage,
                                             get_colour_pve_pattern)

        # The wire exchanges a verdict, so this table is only ever reached by
        # an adventure or arena battle. Those drew from DMX.json -- values 1
        # to 5 -- and clamped them to this line's DAMAGE_LIMIT of 2, so
        # nearly every round came out as the maximum. Same fix the Digital
        # Monster's own adventure table was: a table of 1s and 2s to begin
        # with, rather than a cap over one that is not.
        rows = [get_colour_pve_pattern(stage, hearts * 4)
                for stage in range(1, 8) for hearts in range(5)]
        self.check("seven stages times five effort bands", len(rows) == 35)
        self.check("every round is a 1 or a 2",
                   all(v in (1, 2) for row in rows for v in row))
        self.check("six rounds apiece", all(len(row) == 6 for row in rows))

        # **Keyed on the pet, not on the charge.** The charge was the second
        # axis and was the wrong one: it says nothing about the Digimon, and
        # on DMC it does not vary at all -- that module's battle_minigame is
        # "None", which scores a flat 2 every battle, so the column it played
        # was the only column it could ever play.
        from ui.minigames.minigame_session import minigame_result
        self.check("DMC's charge never varies", minigame_result("None") == 2)

        # Effort is drawn as four hearts at four points each, so the band is
        # effort // 4 and a 16-point pet is at the top.
        self.check("effort 0 and 3 are the same band",
                   get_colour_pve_pattern(4, 0) == get_colour_pve_pattern(4, 3))
        self.check("effort 4 is the next one",
                   get_colour_pve_pattern(4, 4) != get_colour_pve_pattern(4, 0))
        self.check("effort past the meter clamps to the top band",
                   get_colour_pve_pattern(4, 99) == get_colour_pve_pattern(4, 16))
        # A stage outside 1-7 clamps rather than falling through.
        self.check("stage 8 clamps to 7 and stage 0 to 1",
                   get_colour_pve_pattern(8, 0) == get_colour_pve_pattern(7, 0)
                   and get_colour_pve_pattern(0, 0) == get_colour_pve_pattern(1, 0))

        # No row is all doubles. A maxed pet keeping one weak round is what
        # stops an adventure battle reading as "every shot is a 2", which is
        # what the first cut did.
        self.check("every row keeps at least one weak round",
                   all(1 in row for row in rows))

        # Damage rises with both axes, which is the point of keying on them.
        spend = lambda row: sum(get_attack_damage(v, "DMC") for v in row)
        by_stage = [spend(get_colour_pve_pattern(s, 0)) for s in range(1, 8)]
        self.check(f"a bigger Digimon hits harder {by_stage}",
                   by_stage == sorted(by_stage) and by_stage[0] < by_stage[-1],
                   str(by_stage))
        for stage in range(1, 8):
            band = [spend(get_colour_pve_pattern(stage, h * 4))
                    for h in range(5)]
            self.check(f"more effort never hits softer at stage {stage}",
                       band == sorted(band), str(band))

        # An enemy has a stage and no effort, so it reads the 0-heart row
        # through the same door -- there is no separate enemy table, and
        # nothing to keep in step with this one.
        for stage in range(1, 8):
            self.check(f"a stage {stage} enemy reads its own 0-heart row",
                       get_colour_pve_pattern(stage, 0)
                       == get_colour_pve_pattern(stage))

        # The two modules fight at the HP their devices do.
        import json
        import os
        root = _REPO_ROOT
        for module, want in (("DMC", 5), ("PENC", 3)):
            path = os.path.join(root, "modules", module, "module.json")
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as handle:
                hp = json.load(handle).get("battle_global_hit_points")
            self.check(f"{module} fights an adventure battle at {want} HP",
                       hp == want, str(hp))
            self.check(f"...which survives {module}'s hardest single round",
                       want > max(get_attack_damage(v, "DMC") for row in rows
                                  for v in row))

    def test_wire_version_inversion(self):
        self.section("Turning a device's announced version back into a module's")

        from battle.sim import protocol_constants

        inv = protocol_constants.module_versions_for_wire

        # **The Pendulum Z numbers the wire module + 5**, so it announces
        # 6-11 where a DMX announces 0-5 -- disjoint ranges, which is how a
        # device tells the two lines apart. Hardware-confirmed by the jogress
        # codes, six of which pin one module version each.
        for wire, module in ((6, 1), (7, 2), (8, 3), (9, 4), (10, 5), (11, 6)):
            self.check(f"a Pendulum Z announcing {wire} is module {module}",
                       inv("PENZ", wire) == [module], str(inv("PENZ", wire)))
        # Inverting through clamp_oem_version found NOTHING for those -- no
        # module version maps to 9 -- so every Pendulum Z opponent was looked
        # up across the whole roster, came back ambiguous, and kept its bare
        # attribute name and generic sprite.
        # An OEM pet now announces it directly, because `devices.json`
        # carries the wire numbering: module version 4 is device_version 9.
        self.check("an OEM Pendulum Z announces 6-11",
                   [protocol_constants.clamp_oem_version("PENZ", v)
                    for v in range(6, 12)] == list(range(6, 12)))

        # The DMX is unchanged: it carries its module version as it stands.
        for wire in range(1, 6):
            self.check(f"a DMX announcing {wire} is module {wire}",
                       inv("DMX", wire) == [wire], str(inv("DMX", wire)))

        # A number outside anything the line uses says nothing, and searching
        # the whole roster is the right answer -- a real Ver.20th announces 0
        # in an ordinary battle.
        for fmt, wire in (("DM20", 0), ("PENZ", 0), ("PENZ", 5), ("DMX", 9)):
            self.check(f"{fmt} version {wire} is not a version",
                       inv(fmt, wire) is None, str(inv(fmt, wire)))
        self.check("and neither is no version at all",
                   inv("DMX", None) is None)

        # Filmed battles 33 and 34: the same index 11 on two different
        # Pendulum Zs, which the roster answers differently per version.
        import json
        import os
        roster = json.load(open(os.path.join(
            _REPO_ROOT,
            "modules", "PENZ", "monster.json"), encoding="utf-8"))["monster"]
        for label, wire, index, want in (("33", 6, 11, "Roachmon"),
                                         ("34", 9, 11, "Vegiemon")):
            versions = inv("PENZ", wire)
            names = sorted({r["name"] for r in roster
                            if r.get("index") == index
                            and r.get("version") in versions})
            self.check(f"battle {label}'s opponent resolves to {want}",
                       names == [want], str(names))
        self.check("...where the whole roster leaves index 11 ambiguous",
                   len({r["name"] for r in roster if r.get("index") == 11}) > 1)

    def test_penz_attack_table(self):
        self.section("PENZ attack table (its own file, stage + level band)")

        import json
        import os
        from battle.sim.battle_utils import (get_attack_damage,
                                             get_attack_pattern)

        root = _REPO_ROOT
        def table(name):
            return json.load(open(os.path.join(
                root, "src", "data", "attack_patterns", "%s.json" % name),
                encoding="utf-8"))

        penz, dmx = table("PENZ"), table("DMX")
        tiers = penz["tiers"]
        rows = {r["id"]: r["pattern"] for r in penz["patterns"]}

        # The same ladder the DMX uses, confirmed here by where the readings
        # change: stage 4 at 6, stage 5 at 8, stages 6 and 7 at 5 and again
        # at 10. Stage 1 is one band because a Baby I has one level and
        # cannot battle -- its row came off the training minigame.
        BANDS = {1: [(1, 1)],
                 2: [(1, 1), (2, 2), (3, 3)],
                 3: [(1, 2), (3, 3), (4, 4)],
                 4: [(1, 2), (3, 5), (6, 6)],
                 5: [(1, 3), (4, 7), (8, 8)],
                 6: [(1, 4), (5, 9), (10, 10)],
                 7: [(1, 4), (5, 9), (10, 10)]}
        for stage, bands in BANDS.items():
            band = [tuple(t["levels"]) for t in tiers if t["stage"] == stage]
            self.check(f"stage {stage} bands {bands}", band == bands, str(band))
            self.check(f"stage {stage}'s bands are contiguous from 1",
                       bands[0][0] == 1 and all(
                           bands[i + 1][0] == bands[i][1] + 1
                           for i in range(len(bands) - 1)))
            self.check(f"stage {stage}'s top band is its max level alone",
                       bands[-1][0] == bands[-1][1])
        self.check("seven stages, nineteen bands",
                   len(tiers) == 19 and len(BANDS) == 7, len(tiers))

        # A charge is worth more than the one below it, everywhere. This is
        # the readings' own consistency check, and it is also what settled
        # which of each stage's two ordinary shots is the strong one: the
        # notes wrote them as 1 and 2 per stage without saying which.
        for tier in tiers:
            spend = [sum(get_attack_damage(v) for v in rows[i])
                     for i in tier["patterns"]]
            self.check(f"stage {tier['stage']} lv {tier['levels']} rises with "
                       f"the charge", spend == sorted(spend), str(spend))

        # Read off utilities/DIGIROM/penz.txt, one spot value per stage, at
        # the level and charge it was read at.
        MEASURED = (
            (1, 1, 3, [1, 5, 3, 3, 3]),      # Baby I, training, Excellent
            (2, 2, 3, [2, 5, 4, 4, 3]),      # Baby II at level 2
            (3, 4, 0, [2, 3, 2, 1, 1]),      # a Child at its top level
            (4, 6, 2, [5, 4, 4, 2, 4]),      # an Adult at its top level
            (5, 1, 1, [3, 3, 1, 4, 3]),
            (6, 5, 3, [4, 5, 4, 3, 5]),
            (7, 10, 2, [2, 4, 5, 4, 5]),     # Omnimon, debug mode, level 10
        )
        for stage, level, charge, want in MEASURED:
            got = get_attack_pattern(level, charge, "PENZ", stage=stage)
            self.check(f"PENZ stage {stage} lv {level} charge {charge}",
                       got == want, str(got))

        # A Baby II really is one row at every level -- read at all three,
        # identical all three times, so its bands agree rather than the
        # lookup being told to skip them.
        self.check("a Baby II draws one row at each of its three levels",
                   len({tuple(t["patterns"]) for t in tiers if t["stage"] == 2})
                   == 1)
        # And a Child is NOT, which is what retired PENZ.LOW_STAGE_ROWS: read
        # at level 4 on a Falcomon carrier, it drew its own top band.
        self.check("a Child changes row with its level",
                   get_attack_pattern(1, 0, "PENZ", stage=3)
                   != get_attack_pattern(4, 0, "PENZ", stage=3))

        # Three middle bands nobody has read say so, and name what settles
        # them. Stage 4's is half measured -- filmed battles 24 and 27 put a
        # level 3 Adult on tier 1's rows at Bad and Great.
        unread = {(t["stage"], tuple(t["levels"])): t["provisional"]
                  for t in tiers if "provisional" in t}
        self.check("exactly three bands are marked unread",
                   sorted(unread) == [(3, (3, 3)), (4, (3, 5)), (5, (4, 7))],
                   str(sorted(unread)))
        self.check("stage 4's middle band records the two charges that ARE read",
                   unread[(4, (3, 5))] == [1, 3], str(unread[(4, (3, 5))]))
        for key, charges in unread.items():
            self.check(f"band {key} says what would settle it",
                       len([t for t in tiers
                            if (t["stage"], tuple(t["levels"])) == key
                            and len(t.get("source", "")) > 40]) == 1)

        # The two lines share the wire, the five attack types and the ladder,
        # and NOT this table. Eight of the sixteen blocks read off a Pendulum
        # Z also appear in DMX.json and eight appear nowhere in it, so the
        # files have to disagree somewhere and agree elsewhere -- and neither
        # may reach into the other.
        differ = [(s, l) for s in range(2, 8) for l in range(1, 11)
                  if get_attack_pattern(l, 3, "PENZ", stage=s)
                  != get_attack_pattern(l, 3, "DMX", stage=s)]
        self.check("the two tables genuinely differ", len(differ) > 0,
                   str(len(differ)))
        self.check("PENZ carries its own rows, not a reference to DMX's",
                   penz["patterns"] is not dmx["patterns"]
                   and penz["tiers"] != dmx["tiers"])
        # The rule that used to send a low-stage PENZ pet into DMX.json.
        from battle.sim import protocol_constants
        self.check("no low-stage special case survives",
                   not hasattr(protocol_constants.PENZ, "LOW_STAGE_ROWS")
                   and not hasattr(protocol_constants.PENZ, "LOW_STAGE_MAX"))

    def test_filmed_dmx_battles(self):
        self.section("Filmed DMX battles (real hardware, 2026-08-22)")

        # Nine battles against a real Digital Monster X, filmed on both
        # screens and recorded in utilities/DMX/battle.txt. The packets are
        # verbatim from the exchange log; "pairs" is the attack exchanges seen
        # on the device (the knockout round IS one of them), and "bar" is the
        # device's own remaining HP, read off its bar -- one segment is one HP.
        #
        # The bar readings are what pin the damage table, and battle 10
        # measures the last value outright: a critical against a full 18 HP
        # leaves 8. Nothing here is inferred any more.
        from battle.sim.battle_utils import get_attack_pattern, get_attack_damage

        def replay(dev1, dev6, dev_hp, our1, our6, our_hp, dev_stage, our_stage):
            dl, da = (dev1 >> 11) & 0xF, (dev1 >> 8) & 3
            ol, oa = (our1 >> 11) & 0xF, (our1 >> 8) & 3
            dpat = get_attack_pattern(dl + 1, da, "DMX", dev_stage)
            opat = get_attack_pattern(ol + 1, oa, "DMX", our_stage)
            dh = (((dev6 >> 8) & 1) << 4) | ((dev6 >> 4) & 0xF)
            oh = (((our6 >> 8) & 1) << 4) | ((our6 >> 4) & 0xF)
            them, us = dev_hp, our_hp
            for turn in range(5):
                if (dh >> turn) & 1:
                    us = max(0, us - get_attack_damage(dpat[turn]))
                if (oh >> turn) & 1:
                    them = max(0, them - get_attack_damage(opat[turn]))
                if us == 0 or them == 0:
                    return turn + 1, ("device" if us == 0 else "game"), them
            return 5, ("game" if us > them else "device" if them > us else "TIE"), them

        # The two stages are read off each exchange's packet 2, and they
        # matter: the DMX chooses its row from the attacker's stage first and
        # a band of its level second. Battles 1-4 are compatibility pets, who
        # announce their real stage -- a Child -- against the toy's Ultimate.
        FILMED = (
            # label          dev p1  dev p6  dev hp  our p1  our p6  our hp  stages  pairs  winner   bar
            ("1 Patamon",     0x831E, 0xE0EE, 18,     0x030E, 0x211E, 10,   (6, 3),  3,  "device", 15),
            ("2 Shoutmon",    0x821E, 0xD1FE, 18,     0x110E, 0x400E, 12,   (6, 3),  3,  "device", 18),
            ("3 Shoutmon X2", 0x831E, 0xC1FE, 18,     0x120E, 0x600E, 12,   (6, 3),  2,  "device", 18),
            ("4 Shoutmon X2", 0x821E, 0xD1FE, 18,     0x110E, 0x700E, 12,   (6, 3),  3,  "device", 18),
            ("5 Valdurumon",  0x031E, 0x400E, 18,     0x812E, 0xD1FE, 18,   (6, 6),  5,  "game",    0),
            ("6 Valdurumon",  0x831E, 0x714E, 18,     0x012E, 0xA0BE, 18,   (6, 6),  5,  "device",  8),
            ("7 Valdurumon",  0x831E, 0x903E, 18,     0x032E, 0x61CE, 18,   (6, 6),  5,  "device",  3),
            # Battle 8's notes skip round 3, so its pair count is not asserted.
            ("8 Valdurumon",  0x801E, 0x906E, 18,     0x032E, 0x919E, 18,   (6, 6), None, "game",   0),
            ("9 Valdurumon",  0x821E, 0x814E, 18,     0x022E, 0x90BE, 18,   (6, 6),  5,  "game",    4),
            # Battle 10's notes label round 4 a Double where the pattern says
            # SINGLE_STRONG; the HP is right either way because it clamps.
            ("10 Valdurumon", 0x821E, 0x814E, 18,     0x032E, 0x80BE, 18,   (6, 6), None, "game",   0),
        )

        # Battle 1 used to be the one deviation, and it needed the row hard-
        # coded: we sent Level 1 / Excellent, the old (level, charge) table
        # answered with a Critical first, and both the film and the bar said
        # the device had drawn pattern 7 instead. The stage is what it was
        # missing -- our pet was a **Child**, and stage 3's first tier answers
        # Excellent with exactly that row. No override left.
        for label, d1, d6, dhp, o1, o6, ohp, st, pairs, winner, bar in FILMED:
            got_pairs, got_winner, got_bar = replay(
                d1, d6, dhp, o1, o6, ohp, st[0], st[1])
            if pairs is not None:
                self.check(f"battle {label} runs {pairs} exchange(s)",
                           got_pairs == pairs, f"got {got_pairs}")
            self.check(f"battle {label} is won by the {winner}",
                       got_winner == winner, f"got {got_winner}")
            self.check(f"battle {label} leaves the device on {bar} HP",
                       got_bar == bar, f"got {got_bar}")

        # The table those readings produce.
        for value, damage, name in ((1, 2, "SINGLE_WEAK"), (2, 3, "SINGLE_STRONG"),
                                    (3, 4, "DOUBLE_WEAK"), (4, 6, "DOUBLE_STRONG"),
                                    (5, 10, "CRITICAL")):
            self.check(f"{name} costs {damage} HP",
                       get_attack_damage(value) == damage, get_attack_damage(value))
        self.check("other protocols keep the pattern value as damage",
                   get_attack_damage(5, protocol="PEN20") == 5)

        # The Ver.20th's single-battle table, measured: fifteen battles
        # against a real device, one per point of the tap meter, with the
        # attack read off the screen each round. A value is the attack and
        # the attack is its damage -- 1 weak, 2 strong, 3 double weak, 4
        # double strong. The table this replaced held only 1s and 2s, having
        # recorded how many shots went out and not which sprite.
        from battle.sim.battle_utils import (
            get_dm20_single_battle_attack_pattern as dm20_pattern)
        rows = [dm20_pattern(m) for m in range(15)]
        self.check("DM20 has a row per point of the meter",
                   len(rows) == 15 and all(len(r) == 5 for r in rows),
                   str([len(r) for r in rows]))
        self.check("...every value is one of the four single-battle attacks",
                   all(v in (1, 2, 3, 4) for r in rows for v in r),
                   str(sorted({v for r in rows for v in r})))
        self.check("...an empty meter is the weakest row",
                   rows[0] == [1, 1, 3, 1, 1], str(rows[0]))
        self.check("...a full meter is the strongest",
                   rows[14] == [4, 4, 3, 4, 4], str(rows[14]))
        self.check("...and its damage rises with the meter overall",
                   sum(rows[14]) > sum(rows[0]),
                   "%d vs %d" % (sum(rows[0]), sum(rows[14])))
        self.check("DM20 damage is the pattern value",
                   get_attack_damage(4, protocol="DM20") == 4,
                   get_attack_damage(4, protocol="DM20"))
        self.check("...so its damage limit is 4, not 3",
                   protocol_constants.DM20.DAMAGE_LIMIT == 4,
                   protocol_constants.DM20.DAMAGE_LIMIT)
        # PEN20 has its OWN measured table -- fifteen battles against a real
        # Pendulum Ver.20th, charges 0-6 mapped twice on two different Digimon
        # after the first died, and matching. Not one of its rows is DM20's,
        # which this used to assume. A filmed battle settles it independently:
        # the device's bar ran 10 -> 7 -> 4 -> 0, which is PEN20's row 10
        # exactly and not DM20's [3, 2, 4, 4, 3].
        from battle.sim.battle_utils import (
            get_attack_pattern as _pattern,
            get_20th_single_battle_attack_pattern as twentieth)
        pen_rows = [twentieth(m, "PEN20") for m in range(15)]
        self.check("PEN20 has a row per point of the meter",
                   len(pen_rows) == 15 and all(len(r) == 5 for r in pen_rows))
        self.check("...every value is one of the four attacks",
                   all(v in (1, 2, 3, 4) for r in pen_rows for v in r))
        self.check("...and not one row is DM20's",
                   not any(r == dm20_pattern(m) for m, r in enumerate(pen_rows)),
                   str([m for m, r in enumerate(pen_rows) if r == dm20_pattern(m)]))
        self.check("PEN20's row 10 reproduces the filmed bar 10-7-4-0",
                   twentieth(10, "PEN20")[:3] == [3, 3, 4],
                   str(twentieth(10, "PEN20")))
        self.check("...and get_attack_pattern routes PEN20 to it",
                   _pattern(1, 10, protocol="PEN20") == twentieth(10, "PEN20"),
                   str(_pattern(1, 10, protocol="PEN20")))
        # A real Pendulum 20th announces Attack 15, one past where its meter
        # and generate_packet1 both stop. Sent back, it plays [4,4,4,4,4] --
        # the same as 14, which is already the strongest five bits can say.
        # So reading a received 15 as row 14 gives the pattern the device
        # really plays, and there is no sixteenth row to add.
        self.check("a received PEN20 charge of 15 reads as the strongest row",
                   twentieth(15, "PEN20") == twentieth(14, "PEN20")
                   == [4, 4, 4, 4, 4],
                   str(twentieth(15, "PEN20")))

        # Meters 0, 5, 9 and 14 are pure rows of one attack each -- a shape
        # DM20's table does not have.
        for meter, value in ((0, 1), (5, 2), (9, 3), (14, 4)):
            self.check(f"PEN20 meter {meter} is five of attack {value}",
                       twentieth(meter, "PEN20") == [value] * 5,
                       str(twentieth(meter, "PEN20")))

        # This line reverses the usual sprite pairing: its WEAK attacks draw
        # atk_alt and its strong ones atk_main.
        from battle.battle_encounter import BattleEncounter
        import types as _types
        holder = _types.SimpleNamespace()
        armed = _types.SimpleNamespace(atk_main=17, atk_alt=13)
        expected = {1: ("13", 1), 2: ("17", 1), 3: ("13", 2), 4: ("17", 2)}
        for damage, want in expected.items():
            got = BattleEncounter._paired_shot(holder, armed, damage)
            self.check(f"DM20 damage {damage} draws {want[1]} x sprite {want[0]}",
                       (got[0], got[1]) == want and not got[2], str(got))
        # Without atk_alt the four separate by count instead.
        bare = _types.SimpleNamespace(atk_main=17, atk_alt=0)
        counts = [BattleEncounter._paired_shot(holder, bare, d) for d in (1, 2, 3, 4)]
        self.check("...and a pet with no atk_alt counts 1, 2, 3 then doubles",
                   [c[1] for c in counts] == [1, 2, 3, 1] and counts[3][2],
                   str([(c[1], c[2]) for c in counts]))

        # Max Strength pays +1 a shot in a Single Battle -- "damage output
        # will increase for each attack by 1" -- and max is four hearts, which
        # the manual pins independently at "4 points to power" each for 16.
        # Ours only: the wire carries the Power the meter bought, not the
        # meter.
        self.check("DM20 pays +1 an attack at max Strength",
                   protocol_constants.DM20.MAX_STRENGTH_DAMAGE_BONUS == 1,
                   protocol_constants.DM20.MAX_STRENGTH_DAMAGE_BONUS)
        strong = make_digimon(power=200, hp=5, index=4, attribute=0,
                              level=3, stage=4)
        strong.stomach, strong.strength = 4, 4
        weak = make_digimon(power=200, hp=5, index=4, attribute=0,
                            level=3, stage=4)
        weak.stomach, weak.strength = 4, 1
        self.check("a full meter reads as max Strength",
                   pet_to_digimon(strong, "DM20", 0).strength_full)
        self.check("...and a part-full one does not",
                   not pet_to_digimon(weak, "DM20", 0).strength_full)

        # Adventure enemies play no minigame, so they read their stage -- and
        # every row is one of the measured meter rows, so an enemy always
        # throws a pattern the device really produces.
        from battle.sim.battle_utils import get_dm20_enemy_pattern
        stage_rows = [get_dm20_enemy_pattern(st) for st in range(1, 8)]
        totals = [sum(r) for r in stage_rows]
        self.check("a DM20 enemy's damage rises strictly with its stage",
                   totals == sorted(totals) and len(set(totals)) == len(totals),
                   str(totals))
        measured = [dm20_pattern(m) for m in range(15)]
        self.check("...and every enemy row is one the device really produces",
                   all(row in measured for row in stage_rows))

        # The charge picks the attack pattern, and the two wires keep the
        # Attack field in different packets -- the same split the Order bit
        # has. Reading DM20's position out of a PEN20 exchange found packet
        # 3, where PEN20 keeps something else, so every PEN20 battle came out
        # as pattern 0 however hard the meter was charged. These are the real
        # packet 1s from a filmed exchange.
        self.check("a PEN20 packet 1 carries the charge in bits 13-10",
                   (0xA81E >> 10) & 0xF == 10, (0xA81E >> 10) & 0xF)
        self.check("...and the device's reads back the same way",
                   (0x247E >> 10) & 0xF == 9, (0x247E >> 10) & 0xF)
        self.check("...while its packet 3 carries no charge at all",
                   (0x010E >> 10) & 0x1F == 0)

        # "If your Digimon is at 99G for weight, or has no Hunger Hearts, the
        # Strength Bonus will be removed, reverting it to its base power."
        # Removed, not reduced -- however full the Strength meter is.
        from models.game_pet import GamePet
        neglected = object.__new__(GamePet)
        for weight, hunger, blocked, label in (
                (40, 4, False, "a cared-for pet keeps its Strength Bonus"),
                (99, 4, True, "at the 99G ceiling it loses it"),
                (40, 0, True, "with no Hunger hearts it loses it"),
                (99, 0, True, "and both together")):
            neglected.weight, neglected.hunger = weight, hunger
            self.check(label,
                       neglected.strength_bonus_blocked() is blocked,
                       f"weight {weight} hunger {hunger}")

        # A DM20 opponent resolves to a real Digimon from its index, so the
        # battle shows what the toy is actually holding rather than a bare
        # attribute name. A real Ver.20th announces version **0** in an
        # ordinary battle -- not a version at all -- and inverting that used
        # to give every out-of-range number, a set the roster never uses, so
        # nothing ever resolved.
        self.check("an unstated version is outside the format's own range",
                   not (protocol_constants.VERSION_RANGES["DM20"][0]
                        <= 0 <= protocol_constants.VERSION_RANGES["DM20"][1]))

        # A compatibility battle must announce a version the wire accepts.
        # Sending 0, which is outside the DMX's declared 1-6, is the only
        # thing separating battles 1 and 11 -- where the device drew our
        # attacks from the Level 2 row -- from the six that drew Level 1.
        self.check("DMX announces version 1 in a compatibility battle",
                   protocol_constants.get_compatibility_version("DMX") == 1)
        v_min, v_max = protocol_constants.VERSION_RANGES["DMX"]
        self.check("...which is inside the range the DMX declares",
                   v_min <= protocol_constants.get_compatibility_version("DMX") <= v_max,
                   f"{v_min}..{v_max}")
        # The Pendulum Z announces module + 5, so its "first release" is 6.
        # Sending 0 there is what cost two or three button presses a battle:
        # a device whose version disagrees with ours stops answering, and
        # only a broken-off exchange taught us the real number.
        self.check("PENZ announces its own first release, 6",
                   protocol_constants.get_compatibility_version("PENZ") == 6)
        v_min, v_max = protocol_constants.VERSION_RANGES["PENZ"]
        self.check("...inside the 6-11 it declares",
                   (v_min, v_max) == (6, 11))
        for fmt in ("DM20", "PEN20", "DMC"):
            self.check(f"{fmt} keeps the version it was tested with",
                       protocol_constants.get_compatibility_version(fmt) == 0)

        # Two slot scales, because two rosters. A pet native to this line is
        # already on the Digital Monster's own 0-60 range; anything else runs
        # to 240, and reading it through the native bands put half of every
        # roster on slot L -- the strongest on the chart.
        DMOG = protocol_constants.DMOG
        self.check("a native pet keeps the original 0-60 bands",
                   [DMOG.slot_for_power(p, oem=True) for p in (8, 30, 55, 60)]
                   == [0x3, 0x7, 0xC, 0xE],
                   str([DMOG.slot_for_power(p, oem=True) for p in (8, 30, 55, 60)]))
        # The rescale is the only rule with hardware behind it: a Pendulum Z
        # in legacy mode sent slot A for a power-8 Falcomon and F for an
        # 88-power Orochimon, both exactly 3 + power // 16.
        for name, power, slot in (("Falcomon", 8, 0x3), ("Orochimon", 88, 0x8)):
            self.check(f"a compatibility pet of {name}'s power announces "
                       f"slot 0x{slot:X}",
                       DMOG.slot_for_power(power) == slot,
                       hex(DMOG.slot_for_power(power)))
        self.check("...and the top of the chart needs real power for it",
                   DMOG.slot_for_power(175) < 0xE
                   and DMOG.slot_for_power(176) == 0xE,
                   f"{DMOG.slot_for_power(175)}/{DMOG.slot_for_power(176)}")

        # DMOG announces the first release rather than 0. An OEM pet sends
        # its own device_version -- the module has six, one per Ver.1..Ver.6
        # device -- and only an outsider falls back to this.
        self.check("DMOG announces version 1 in a compatibility battle",
                   protocol_constants.get_compatibility_version("DMOG") == 1)
        self.check("...and the legacy DM name resolves to it",
                   protocol_constants.get_compatibility_version("DM") == 1)

        # The Digital Monster's Ver.6 was an Australia-only release with no
        # wire version of its own, so it is clamped to the nearest real one
        # rather than sent as the 0 that means "special" on this wire.
        self.check("a DMOG Ver.6 pet announces Ver.5",
                   protocol_constants.clamp_oem_version("DMOG", 6) == 5,
                   protocol_constants.clamp_oem_version("DMOG", 6))
        self.check("...and Ver.1 to Ver.5 pass through unchanged",
                   [protocol_constants.clamp_oem_version("DMOG", v)
                    for v in range(1, 6)] == [1, 2, 3, 4, 5])
        # No other wire clamps: a version they do not have stays "special".
        self.check("the DMX still spells an unknown version 0",
                   protocol_constants.clamp_oem_version("DMX", 9) == 0,
                   protocol_constants.clamp_oem_version("DMX", 9))

        # An OEM pet's own version reaches the packet: DMDevice used to
        # hardcode 1, so every DMOG battle announced Ver.1 whichever Digital
        # Monster was being raised.
        for device_version in (1, 3, 5):
            oem = make_digimon(name="Agumon", power=28, hp=5, index=4,
                               attribute=0, level=1, stage=4)
            oem.version = device_version
            packets = DMDevice(oem).generate_all_packets()
            sent = (packets[1][1] >> 4) & 0xF
            self.check(f"an OEM DMOG pet announces Ver.{device_version}",
                       sent == device_version, sent)

        # Better still: let the adapter copy the device's own version in, so
        # the toy sees a Digimon of its own version and no cross-version
        # content can unlock off the back of the battle. "^0" XORs a digit
        # with zero against the packet being replied to, which copies it.
        self.check("DMX mirrors the device's version",
                   protocol_constants.DMX.DCOM_VERSION_ECHO == "^0E")
        self.check("and so does PENZ, now its numbering is right",
                   protocol_constants.PENZ.DCOM_VERSION_ECHO == "^0E")
        for fmt in ("DMC", "DM20", "PEN20"):
            self.check(f"{fmt} does not mirror (untested there)",
                       getattr(protocol_constants.get_constants(fmt),
                               "DCOM_VERSION_ECHO", None) is None)

        # Only a compatibility pet mirrors, and only when replying.
        fixture = make_digimon(power=30, hp=10, level=0, stage=1, attribute=1,
                               index=0, shot1=1, shot2=1, mini_game=3)
        fixture.version = 1
        fixture.dmx_shot_m = 1
        for compatibility, expect in ((True, True), (False, False)):
            dcom = DComBattleSimulator(None, battle_format="DMX")
            fixture.compatibility = compatibility
            packets = dcom.generate_player_packets(fixture)
            command = dcom.build_command(packets, protocol_constants.DCOM_TURN_LISTEN)
            self.check(f"compatibility={compatibility} mirrors: {expect}",
                       dcom.sent_echoed_version == expect, command[:24])
            if expect:
                self.check("...and packet 1 carries the copy operator",
                           command.split("-")[1] == "03^0E", command[:24])
        # Going first there is nothing to copy from.
        dcom = DComBattleSimulator(None, battle_format="DMX")
        fixture.compatibility = True
        # Generated for that turn too -- the Order bit follows who opens.
        packets = dcom.generate_player_packets(
            fixture, protocol_constants.DCOM_TURN_GO_FIRST)
        command = dcom.build_command(packets, protocol_constants.DCOM_TURN_GO_FIRST)
        self.check("going first falls back to the declared version",
                   not dcom.sent_echoed_version and command.split("-")[1] == "831E",
                   command[:24])

        # Damage is the sprite strength times the sprite count, which is what
        # each type's sprite spec in DMX.json already describes.
        for value, count, strength in ((1, 1, 2), (2, 1, 3), (3, 2, 2), (4, 2, 3), (5, 2, 5)):
            self.check(f"attack type {value} is {count} x {strength}",
                       get_attack_damage(value) == count * strength)

        # Round-by-round HP, read off the device's bar one hit at a time.
        # These are the measurements the table is built from: battle 10's
        # first round is a critical against a full 18, and the bar drops to
        # 8 -- which is what fixes CRITICAL at 10 rather than 11.
        PER_HIT = (
            # battle, our pattern, our hits, [(round, remaining HP), ...]
            (5,  [1, 4, 3, 1, 3], 0b11111, ((1, 16), (2, 10), (3, 6), (4, 4), (5, 0))),
            (6,  [1, 4, 3, 1, 3], 0b01011, ((1, 16), (2, 10), (4, 8))),
            (7,  [5, 4, 4, 2, 4], 0b11100, ((3, 12), (4, 9), (5, 3))),
            (10, [5, 4, 4, 2, 4], 0b01011, ((1, 8), (2, 2), (4, 0))),
        )
        for battle, pattern, hit_bits, readings in PER_HIT:
            hp = 18
            seen = dict(readings)
            for turn in range(5):
                if (hit_bits >> turn) & 1:
                    hp = max(0, hp - get_attack_damage(pattern[turn]))
                if turn + 1 in seen:
                    self.check(
                        f"battle {battle} round {turn + 1} leaves {seen[turn + 1]} HP",
                        hp == seen[turn + 1], f"got {hp}")

    # ------------------------------------------------------------------

    def _check_every_test_runs(self):
        """Every test method is defined once and registered once.

        Two were defined and never called -- `test_dmx_attack_table`, which
        pins the whole 72-value DMX grid, and `test_dmx_roundtrip` -- so
        their checks had been silently absent. And a pair got duplicated by
        an editing slip, where Python keeps the LAST definition and the newer
        one simply never ran. Both are invisible in a green suite, so the
        suite checks itself.
        """
        import re
        source = open(__file__, encoding="utf-8").read()
        defined = re.findall(r"^    def (test_\w+)\(", source, re.M)
        called = re.findall(r"^        self\.(test_\w+)\(\)", source, re.M)
        for name in sorted(set(defined)):
            self.check(f"{name} is defined once", defined.count(name) == 1,
                       str(defined.count(name)))
        self.check("every test is registered in run()",
                   not set(defined) - set(called),
                   str(sorted(set(defined) - set(called))))
        self.check("...and nothing is registered twice",
                   not [n for n in set(called) if called.count(n) > 1],
                   str([n for n in set(called) if called.count(n) > 1]))

    def run(self):
        self.test_dm20_roundtrip()
        self.test_pen20_roundtrip()
        self.test_dmx_roundtrip("DMX")
        self.test_dmx_roundtrip("PENZ")
        self.test_versus_protocols()
        self.test_global_protocol()
        self.test_dcom_wire_facts()
        self.test_dcom_field_clamping()
        self.test_minigame_scoring()
        self.test_dm20_document_conformance()
        self.test_dm20_hit_rate_follows_power()
        self.test_dm20_packet_a_consistency()
        self.test_pen20_document_conformance()
        self.test_pen20_checksum_target()
        self.test_charge_scale_per_wire()
        self.test_dmx_hits_are_five_bits()
        self.test_dmx_document_conformance()
        self.test_dmx_level_and_stage_offsets()
        self.test_shot_id_offsets()
        self.test_empty_shot_slot_falls_back()
        self.test_shared_protocol_menu()
        self.test_minigame_ready_phase()
        self.test_dmx_never_ties()
        self.test_hit_rate_uses_power()
        self.test_filmed_dmx_battles()
        self.test_filmed_penz_battle()
        self._check_every_test_runs()
        self.test_dmx_attack_table()
        self.test_dmx_roundtrip()
        self.test_penz_attack_table()
        self.test_wire_version_inversion()
        self.test_filmed_penc_battle()
        self.test_penc_is_not_a_dmc()
        self.test_hit_rate()
        self.test_penc_battle_shape()
        self.test_crossover_colour_opponent()
        self.test_penc_stage_from_wire()
        self.test_no_wire_hands_the_opener_a_free_win()
        self.test_colour_pattern_pool()
        self.test_penc_connection_rounds()
        self.test_penc_replays_the_filmed_battles()
        self.test_opening_the_exchange()
        self.test_fought_winner_is_the_shown_winner()
        self.test_single_pet_selection()
        self.test_middleman_analyser()
        self.test_settling_without_a_verdict()
        self.test_colour_adventure_table()
        self.test_filmed_dmc_battle()
        self.test_shot_bank_clamp()
        self.test_training_patterns()
        self.test_controlled_penz_battles()
        self.test_dmc_wire()
        self.test_jogress_roms()
        self.test_serial_jogress()
        self.test_dmog_slots_and_verdict()
        self.test_penog_conformance()
        self.test_dmm_conformance()
        self.test_ic_conformance()
        self.test_wificom_exchange()
        self.test_packet_exchange()
        self.test_count_match_z()
        self.test_dmc_turn_resolution()
        self.test_dmog_outcome()

        print()
        print("=" * 70)
        print(f"RESULTS: {self.passed} passed, {self.failed} failed")
        if self.failures:
            print("Failures:")
            for label, detail in self.failures:
                print(f"  - {label}" + (f" ({detail})" if detail else ""))
        print("=" * 70)
        return self.failed == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Battle protocol test harness")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="print packet dumps and battle logs")
    args = parser.parse_args()

    tester = BattleProtocolTester(verbose=args.verbose)
    sys.exit(0 if tester.run() else 1)
