from dataclasses import dataclass, asdict
from enum import Enum, auto
from typing import List

@dataclass
class Digimon:
    name: str                  # Name of the Digimon
    order: int                 # Order in the team (0 for single battles)
    traited: int               # Whether the Digimon has a trait applied (0 or 1)
    egg_shake: int             # Egg shake count (if applicable)
    index: int                 # Index of the Digimon
    hp: int                    # Current HP of the Digimon
    attribute: int             # Attribute (0=Vaccine, 1=Data, 2=Virus, 3=Free)
    power: int                 # Power level of the Digimon
    handicap: int              # Handicap applied to the Digimon
    buff: int                  # Buff applied to the Digimon
    mini_game: int             # Mini-game score or multiplier
    level: int                 # Level of the Digimon
    stage: int                 # Evolution stage
    sick: int                  # Whether the Digimon is sick (0=healthy, 1=sick)
    shot1: int                 # ID of the first attack sprite
    shot2: int 
    tag_meter: int


@dataclass
class DigimonStatus:
    name: str
    hp: int
    alive: bool

    def to_dict(self):
        return asdict(self)

@dataclass
class AttackLog:
    turn: int
    device: str  # "device1" or "device2"
    attacker: int  # Index of the attacker
    defender: int  # Index of the defender (-1 if no defender)
    hit: bool
    #: On most wires this is the HP the attack costs. On the DMX wire it is
    #: the attack TYPE id (1-5), because the encounter counts projectiles
    #: from it -- there, the HP cost is a separate scale and lives in
    #: ``hp_damage``. Anything applying damage should prefer that.
    damage: int
    critical: bool
    #: HP the attack actually costs, where that differs from ``damage``.
    #: None means the two are the same.
    hp_damage: int = None

    def to_dict(self):
        return asdict(self)

@dataclass
class TurnLog:
    turn: int
    device1_status: List[DigimonStatus]
    device2_status: List[DigimonStatus]
    attacks: List[AttackLog]

    def to_dict(self):
        return {
            "turn": self.turn,
            "device1_status": [ds.to_dict() for ds in self.device1_status],
            "device2_status": [ds.to_dict() for ds in self.device2_status],
            "attacks": [atk.to_dict() for atk in self.attacks],
        }

@dataclass
class BattleResult:
    winner: str  # "device1", "device2", or "draw"
    device1_final: List[DigimonStatus]
    device2_final: List[DigimonStatus]
    battle_log: List[TurnLog]
    device1_packets: List[List[bytes]]
    device2_packets: List[List[bytes]]

    def to_dict(self):
        # Note: packets are bytes, which are not JSON serializable.
        # We'll convert them to lists of ints or hex strings.
        def serialize_packets(packets):
            return [
                [pkt.hex() if isinstance(pkt, bytes) else pkt for pkt in packet_list]
                for packet_list in packets
            ]
        return {
            "winner": self.winner,
            "device1_final": [ds.to_dict() for ds in self.device1_final],
            "device2_final": [ds.to_dict() for ds in self.device2_final],
            "battle_log": [tl.to_dict() for tl in self.battle_log],
            "device1_packets": serialize_packets(self.device1_packets),
            "device2_packets": serialize_packets(self.device2_packets),
        }


def _restore_packets(packet_lists):
    restored = []
    for pkt_list in packet_lists or []:
        new_list = []
        for pkt in pkt_list:
            if isinstance(pkt, str):
                try:
                    new_list.append(bytes.fromhex(pkt))
                except Exception:
                    new_list.append(pkt)
            else:
                new_list.append(pkt)
        restored.append(new_list)
    return restored


def battle_result_from_serialized(serialized):
    """Reconstruct a BattleResult from a serialized dict or a list of turn dicts.

    Accepts either the dict produced by BattleResult.to_dict() or a plain list
    of turn dicts. Returns a BattleResult instance.
    """
    # Helper restorers
    def _make_status(d):
        return DigimonStatus(name=d.get('name', ''), hp=int(d.get('hp', 0)), alive=bool(d.get('alive', False)))

    def _make_attack(d):
        return AttackLog(
            turn=int(d.get('turn', 0)),
            device=d.get('device', ''),
            attacker=int(d.get('attacker', -1)),
            defender=int(d.get('defender', -1)),
            hit=bool(d.get('hit', False)),
            damage=int(d.get('damage', 0)),
            # Older logs predate the field — fall back to inferring crit from
            # the damage value so historical fights still trigger the slide.
            critical=bool(d.get('critical', d.get('damage', 0) == 5)),
            # Older logs have no hp_damage; None means "same as damage".
            hp_damage=d.get('hp_damage'),
        )

    def _make_turn(t):
        device1 = [_make_status(s) for s in t.get('device1_status', [])]
        device2 = [_make_status(s) for s in t.get('device2_status', [])]
        attacks = [_make_attack(a) for a in t.get('attacks', [])]
        return TurnLog(turn=int(t.get('turn', 0)), device1_status=device1, device2_status=device2, attacks=attacks)

    # If it's a dict shaped like BattleResult.to_dict()
    if isinstance(serialized, dict) and 'battle_log' in serialized:
        winner = serialized.get('winner', 'draw')
        device1_final = [_make_status(s) for s in serialized.get('device1_final', [])]
        device2_final = [_make_status(s) for s in serialized.get('device2_final', [])]
        battle_log = [_make_turn(t) for t in serialized.get('battle_log', [])]
        device1_packets = _restore_packets(serialized.get('device1_packets', []))
        device2_packets = _restore_packets(serialized.get('device2_packets', []))

        return BattleResult(
            winner=winner,
            device1_final=device1_final,
            device2_final=device2_final,
            battle_log=battle_log,
            device1_packets=device1_packets,
            device2_packets=device2_packets
        )

    # If it's a list of turn dicts, wrap into a BattleResult with minimal metadata
    if isinstance(serialized, list):
        battle_log = [_make_turn(t) for t in serialized]
        return BattleResult(
            winner='draw',
            device1_final=[],
            device2_final=[],
            battle_log=battle_log,
            device1_packets=[],
            device2_packets=[]
        )

    # Unknown shape: raise ValueError so callers can fallback
    raise ValueError('Unsupported serialized battle result shape')

class AttributeEnum(Enum):
    FREE = 0
    VIRUS = 1
    DATA = 2
    VACCINE = 3

class BattleProtocol(Enum):
    DMOG_BS = auto()   # Digital Monster Original (slot-based)
    PENOG_BS = auto()  # Digimon Pendulum (original), its own 4-packet battle
    DM20_BS = auto()
    DMC_BS = auto()
    DMX_BS = auto()
    PEN20_BS = auto()