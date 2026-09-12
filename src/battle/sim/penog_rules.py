"""PENOG's bundled, explicitly approximate slot/effort hit-rate model.

The prior is derived offline, not imported from another protocol at runtime.
Only slots and effort that actually appeared in this exchange are inputs.
"""
import json
from pathlib import Path

_TABLE = None


def slot_hit_rate(my_slot, their_slot, my_effort=0, their_effort=0):
    global _TABLE
    if _TABLE is None:
        path = Path(__file__).resolve().parents[2] / 'data/battle_rules/PENOG.json'
        with path.open(encoding='utf-8') as handle:
            _TABLE = json.load(handle)
    if not (3 <= my_slot <= 31 and 3 <= their_slot <= 31):
        raise ValueError('PENOG battle slot is outside the 3..31 model')
    bucket = _TABLE['effort_bucket']
    effort = max(0, min(40, my_effort)) // bucket
    other = max(0, min(40, their_effort)) // bucket
    odds = _TABLE['odds'][my_slot - 3][their_slot - 3]
    odds += (effort - other) * _TABLE['effort_step']
    return 100 * max(_TABLE['minimum'], min(_TABLE['maximum'], odds)) / _TABLE['denominator']
