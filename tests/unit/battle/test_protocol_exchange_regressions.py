"""Transcript conformance and module-owned internal combat regressions."""
import copy
import random
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'src'))
from core import runtime_globals
from battle.sim import protocol_constants as pc
from battle.sim.models import Digimon
from battle.sim.exchange import PacketExchange, simulate_exchange
from battle.sim.dcom_battle_simulator import DComBattleSimulator
from battle.sim.battle_simulator import DMCDevice, BattleSimulator
from battle.sim.global_battle_simulator import GlobalBattleSimulator
from battle.sim.penog_rules import slot_hit_rate


def mon(name='A', **kw):
    data = dict(name=name, order=0, traited=0, egg_shake=0, index=4, hp=31,
                attribute=0, power=100, handicap=0, buff=2, mini_game=2,
                level=6, stage=4, sick=0, shot1=5, shot2=9, tag_meter=0)
    data.update(kw)
    pet = Digimon(**data)
    pet.version, pet.effort = 1, 20
    return pet


def pair(fmt, a, b):
    first = PacketExchange(fmt, copy.deepcopy(a), opens=True)
    second = PacketExchange(fmt, copy.deepcopy(b), opens=False)
    for _ in range(first.packet_count):
        second.receive(first.next_packet())
        first.receive(second.next_packet())
    return first, second


def alter(packet, word, value):
    words = [int.from_bytes(packet[i:i+2], 'big') for i in range(0, 16, 2)]
    words[word] = value
    words[-1] = sum(words[:-1]) & 65535
    return b''.join(w.to_bytes(2, 'big') for w in words)


class ExchangeRegression(unittest.TestCase):
    def setUp(self):
        self.console = patch.object(runtime_globals, 'game_console', SimpleNamespace(log=lambda *a: None))
        self.console.start()
        self.addCleanup(self.console.stop)

    def test_every_protocol_agrees_on_turns_hp_and_winner(self):
        for fmt in pc.BATTLE_FORMATS:
            for seed in range(20):
                with self.subTest(fmt=fmt, seed=seed):
                    random.seed(seed)
                    a = mon(power=30 + seed * 7, attribute=seed % 3, mini_game=seed % 4)
                    b = mon('B', power=200 - seed * 5, attribute=(seed + 1) % 3, mini_game=(seed + 2) % 4)
                    first, second = pair(fmt, a, b)
                    self.assertTrue(first.validate())
                    self.assertTrue(second.validate())
                    with patch('random.randint', side_effect=AssertionError('replay rerolled')):
                        x, y = first.result(), second.result()
                    self.assertIsNotNone(x)
                    self.assertIsNotNone(y)
                    self.assertEqual(x.device1_final[0].hp, y.device2_final[0].hp)
                    self.assertEqual(x.device2_final[0].hp, y.device1_final[0].hp)
                    self.assertEqual(x.winner, {'device1': 'device2', 'device2': 'device1', 'draw': 'draw'}[y.winner])
                    self.assertEqual(len(x.battle_log), len(y.battle_log))
                    for xt, yt in zip(x.battle_log, y.battle_log):
                        self.assertEqual([(a.hit, a.damage, a.hp_damage) for a in xt.attacks],
                                         [(a.hit, a.damage, a.hp_damage) for a in reversed(yt.attacks)])

    def test_local_versus_is_the_same_exchange_and_replay(self):
        for fmt in pc.BATTLE_FORMATS:
            with self.subTest(fmt=fmt):
                a, b = mon(), mon('B', power=75)
                random.seed(23)
                expected = pair(fmt, a, b)[1].result()
                random.seed(23)
                actual = BattleSimulator(pc.versus_protocol(fmt), battle_format=fmt).simulate(a, b)
                self.assertEqual(actual.device1_packets, expected.device1_packets)
                self.assertEqual(actual.device2_packets, expected.device2_packets)
                self.assertEqual(actual.winner, expected.winner)
                self.assertEqual([t.device1_status[0].hp for t in actual.battle_log],
                                 [t.device1_status[0].hp for t in expected.battle_log])

    def test_stock_adapter_commands_match_the_shared_exchange(self):
        from wificom.digirom import parse_command
        for fmt in pc.BATTLE_FORMATS:
            with self.subTest(fmt=fmt):
                opens = PacketExchange.cable_opens(fmt)
                cable = PacketExchange(fmt, mon(), opens=opens)
                peer = PacketExchange(fmt, mon('B', power=120), opens=not opens)
                templates = parse_command(cable.cable_command()).packets
                sent = []
                for i, template in enumerate(templates):
                    if not opens:
                        cable.receive(peer.next_packet())
                    # The stock @/^ interpreter reads the last peer packet
                    # and the adapter's own preceding checksum nibbles.
                    context = SimpleNamespace(sent=cable.received, received=sent)
                    packet = bytes.fromhex(PacketExchange._resolve_incoming(context, template, i))
                    sent.append(packet)
                    peer.receive(packet)
                    if opens:
                        cable.receive(peer.next_packet())
                replay = PacketExchange.from_transcript(fmt, mon(), sent, cable.received,
                                                       simulator=cable.simulator)
                with patch('random.randint', side_effect=AssertionError('cable replay rerolled')):
                    a, b = replay.result(), peer.result()
                self.assertIsNotNone(a)
                self.assertIsNotNone(b)
                self.assertEqual(a.device1_final[0].hp, b.device2_final[0].hp)
                self.assertEqual(a.device2_final[0].hp, b.device1_final[0].hp)
                self.assertNotEqual(a.winner, b.winner)
                with self.assertRaises(ValueError):
                    PacketExchange(fmt, mon(), opens=not opens).cable_command()

    def test_pen20_reads_its_own_power_and_attribute_positions(self):
        first, second = pair('PEN20', mon(), mon('B', power=173, attribute=2))
        self.assertEqual(first._opponent_stats(), (173, 2))
        self.assertEqual(second._opponent_stats(), (100, 0))

    def test_colour_operation_validation(self):
        for fmt in ('DMC', 'PENC', 'DMXW'):
            sim = DComBattleSimulator(None, battle_format=fmt)
            a, b = pair(fmt, mon(), mon('B'))
            valid = b.sent
            base = pc.get_constants(fmt).OPERATION_OFFSET
            cases = [valid[:1], valid * 2, valid[::-1], [valid[0], valid[0]],
                     [valid[0], alter(valid[1], 2, base + 2)],
                     [alter(valid[0], 6, 4), valid[1]],
                     [valid[0], valid[1][:-1]]]
            for packets in cases:
                with self.subTest(fmt=fmt, packets=packets):
                    self.assertFalse(sim._validate_packets(packets))
                    self.assertIsNone(sim.build_result(mon(), mon('B'), a.sent,
                                                      [p.hex() for p in packets]))
            self.assertTrue(sim._validate_packets(valid))
            # Unknown version/index is not a malformed packet.
            unknown = alter(alter(valid[0], 3, 600), 4, 600)
            self.assertTrue(sim._validate_packets([unknown, valid[1]]))
        sim = DComBattleSimulator(None, battle_format='DMC')
        a, b = pair('DMC', mon(), mon('B'))
        self.assertFalse(sim._validate_packets([b.sent[0], alter(b.sent[1], 4, 1)]))
        self.assertFalse(sim._validate_packets([a.sent[0], alter(a.sent[1], 4, 2)]))

    def test_documented_dmc_digirom(self):
        sim = DComBattleSimulator(None, battle_format='DMC')
        packets = [bytes.fromhex(s) for s in ('47444C4300010000001100FA00019494',
                                             '47444C4300030010000000000000939A')]
        self.assertTrue(sim._validate_packets(packets))
        groups = [p[i:i+2] for p in packets for i in range(0, 16, 2)]
        self.assertTrue(sim._validate_packets(groups))

    def test_dmog_mirrors_and_turn_gating(self):
        first = PacketExchange('DMOG', mon(), opens=True)
        self.assertIsNotNone(first.next_packet())
        self.assertIsNone(first.next_packet())
        for seed in range(10):
            random.seed(seed)
            a, b = pair('DMOG', mon(), mon('B'))
            for p in a.sent + b.sent:
                self.assertEqual(p[0] ^ p[1], 255)
        self.assertFalse(a.simulator._validate_packets([bytes.fromhex('0003'), bytes.fromhex('0001')]))

    def test_bad_identity_and_abort_cannot_produce_a_response_or_battle(self):
        for fmt in ('DMC', 'PENC', 'DMXW'):
            exchange = PacketExchange(fmt, mon(), opens=False)
            line = pc.get_constants(fmt)
            identity = DMCDevice(mon('B'), magic=line.MAGIC,
                                 operation_offset=line.OPERATION_OFFSET, limits=line).generate_packet1(0)
            exchange.receive(identity[:-1] + bytes([identity[-1] ^ 1]))
            self.assertTrue(exchange.aborted)
            self.assertIsNone(exchange.next_packet())
            self.assertIsNone(exchange.result())
        first, _ = pair('DMX', mon(), mon('B'))
        first.receive('FF00')
        self.assertIsNone(first.result())

    def test_unknown_color_flags_are_not_dmc_rules(self):
        first, second = pair('DMXW', mon(), mon('B'))
        # DMXW bit 1 is not victory. It must not turn an initiator loss into a win.
        packet = alter(second.sent[1], 4, 2)
        transcript = PacketExchange.from_transcript('DMXW', mon(), first.sent,
                                                   [second.sent[0], packet])
        self.assertEqual(transcript.result().winner, 'device1')

    def test_penog_estimate_depends_on_slots_and_effort_and_complements(self):
        self.assertGreater(slot_hit_rate(12, 3), slot_hit_rate(3, 12))
        self.assertGreater(slot_hit_rate(6, 6, 40, 0), 50)
        for a in range(3, 32):
            for b in range(3, 32):
                self.assertAlmostEqual(slot_hit_rate(a, b, 20, 0) + slot_hit_rate(b, a, 0, 20), 100)

    def test_internal_damage_uses_patterns_and_bonuses_for_both_sides(self):
        sim = GlobalBattleSimulator(pvp_mode=True, damage_limit=4)
        a, b = mon(attribute='Va', hp=100, buff=2), mon('B', attribute='Va', hp=100, buff=2)
        with patch.object(sim, '_pattern_for', return_value=[3] * 5), patch('random.randint', return_value=0):
            result = sim.simulate([a], [b])
        self.assertEqual([attack.hp_damage for attack in result.battle_log[0].attacks], [5, 5])
        self.assertEqual(GlobalBattleSimulator(battle_format='PENC').max_hit_rate, 100)
        self.assertEqual(GlobalBattleSimulator(battle_format='DMX', max_hit_rate=87).max_hit_rate, 87)

    def test_internal_forced_tie_does_not_always_award_team_two(self):
        sim = GlobalBattleSimulator(pvp_mode=True, max_hit_rate=0)
        a, b = mon(hp=100, attribute='Va'), mon('B', hp=100, attribute='Va')
        for selected in ('device1', 'device2'):
            with patch('random.choice', return_value=selected) as choose:
                self.assertEqual(sim.simulate([a], [b]).winner, selected)
            choose.assert_called_once_with(('device1', 'device2'))

    def test_a_module_with_no_protocol_plays_the_dmx_ruleset(self):
        """No battle protocol is the standard DMX ruleset: the row comes from
        the stage, the level and the 0-3 minigame result. It used to match no
        table and throw five Singles."""
        from battle.sim.battle_utils import get_attack_pattern
        for declared in ('None', '', None):
            sim = GlobalBattleSimulator(battle_format=declared)
            for stage, level, result in ((3, 1, 0), (4, 6, 2), (6, 9, 3)):
                pet = mon(stage=stage, level=level, mini_game=result)
                for is_enemy in (False, True):
                    self.assertEqual(
                        sim._pattern_for(pet, is_enemy=is_enemy),
                        get_attack_pattern(level, result, protocol='DMX', stage=stage),
                        (declared, stage, level, result, is_enemy))
            self.assertEqual([sim._hp_cost(v) for v in range(1, 6)], [1, 2, 3, 4, 5])
        sim = GlobalBattleSimulator(battle_format='None')
        rows = {tuple(sim._pattern_for(mon(stage=5, level=6, mini_game=result)))
                for result in range(4)}
        self.assertGreater(len(rows), 1, 'the minigame result must pick the row')
        self.assertNotIn((1, 1, 1, 1, 1), rows)

    def test_dmxw_adventure_plays_dmxw_rules_and_its_pets_are_oem(self):
        """The DMXW module declares its own line: adventure rows by stage,
        effort tier and Xai Bar band on 3 HP, and its pets send their own
        index on the DMXW wire."""
        import json
        from battle.sim.battle_utils import get_dmxw_pattern, get_dmxw_enemy_pattern
        from battle.sim.dcom_battle_simulator import is_oem_pet
        from battle.battle_encounter import BattleEncounter
        manifest = Path(__file__).resolve().parents[3] / 'modules' / 'DMXW' / 'module.json'
        if not manifest.exists():
            self.skipTest('DMXW module not installed')
        data = json.loads(manifest.read_text(encoding='utf-8'))
        self.assertEqual(data['battle_protocol'], 'DMXW')
        self.assertEqual(data['battle_minigame'], pc.DMXW.MINIGAME)
        self.assertEqual(data['battle_global_hit_points'], pc.DMXW.FIXED_HP)

        for stage, effort, band in ((3, 0, 0), (4, 12, 2), (5, 25, 3)):
            sim = GlobalBattleSimulator(battle_format='DMXW', charge=band)
            pet = mon(stage=stage, mini_game=band)
            pet.effort = effort
            self.assertEqual(sim._pattern_for(pet), get_dmxw_pattern(stage, band, effort))
            self.assertEqual(sim._pattern_for(pet, is_enemy=True), get_dmxw_enemy_pattern(stage))
            self.assertEqual(len(sim._pattern_for(pet)), pc.DMXW.TURNS)
        self.assertEqual([sim._hp_cost(v) for v in (1, 2)], [1, 2])

        encounter = BattleEncounter.__new__(BattleEncounter)
        encounter.module = SimpleNamespace(battle_protocol='DMXW', battle_damage_limit=99)
        self.assertEqual(encounter._attack_animation_style(), pc.DMXW.ATTACK_ANIMATION)

        module = SimpleNamespace(name='DMXW', battle_protocol='DMXW')
        with patch.dict(runtime_globals.game_modules, {'DMXW': module}, clear=True), \
                patch('utils.module_utils.get_module', {'DMXW': module}.get):
            self.assertTrue(is_oem_pet(SimpleNamespace(module='DMXW'), 'DMXW'))
            self.assertFalse(is_oem_pet(SimpleNamespace(module='DMXW'), 'DMC'))
        # One device, one wire version: the module's device_version 5 goes out as 0.
        self.assertEqual(pc.clamp_oem_version('DMXW', 5), 0)


if __name__ == '__main__':
    unittest.main()
