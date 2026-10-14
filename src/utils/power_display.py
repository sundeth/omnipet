"""
The power the status screens show, and its colour.

Under the "Effort Tiers" power bonus rule (Digimon World's training,
`core.pet_stats.effort_tier_bonus`) the shown power includes the tier the
pet has reached, and its colour steps up with each tier
(`constants.EFFORT_TIER_COLORS`), so the player can see training pay off.
Every other rule shows the power as before, in the usual yellow.
"""

from core import constants, pet_stats
from utils.module_utils import get_module


def power_display(pet, items=True):
    """``(text, colour)`` for *pet*'s power: its species power, with its
    item bonus when *items*, and, under Effort Tiers, its tier bonus."""
    power = int(getattr(pet, "power", 0) or 0)
    if items:
        bonus = getattr(pet, "bonus_stats", None) or [0, 0, 0]
        power += int(bonus[2] if len(bonus) > 2 else 0)
    color = constants.EFFORT_TIER_COLORS[0]
    try:
        module = get_module(pet.module)
    except Exception:
        module = None
    if module is not None and getattr(module, "power_bonus_rule", "") == "Effort Tiers":
        tiers = getattr(module, "effort_power_tiers", None)
        stage = getattr(pet, "stage", 0)
        effort = getattr(pet, "effort", 0)
        power += pet_stats.effort_tier_bonus(tiers, stage, effort)
        level = pet_stats.effort_tier_level(tiers, stage, effort)
        color = constants.EFFORT_TIER_COLORS[min(level, len(constants.EFFORT_TIER_COLORS) - 1)]
    return str(power), color
