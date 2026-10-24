"""
Progress-Mode coin rewards
==========================

Thin helpers that fire the server-side coin grants for in-game milestones.

All of them route through ``OmninetService.claim_reward``, which is a no-op
unless the player is in Progress Mode *and* the device is logged in — so Free
Mode play (which is fully offline) never touches the network here.

Idempotency keys encode the dedup policy the server enforces per player:
    * unlock / new_pet / area_clear / adventure  → stable key = "first time only"
    * evolution                                   → unique key = "every time"

Server reward values (configured server-side):
    reward_coins_unlock     = 5
    reward_coins_evolution  = 2
    reward_coins_new_pet    = 3
    reward_coins_adventure  = 10   (whole-module adventure completion)
    reward_coins_area_clear = 1    (per-area boss clear)
"""

import uuid

from core import runtime_globals


def _claim(event_type: str, idempotency_key: str) -> None:
    try:
        from services.omninet_service import omninet_service
        omninet_service.claim_reward(event_type, idempotency_key)
    except Exception as exc:
        runtime_globals.game_console.log(
            f"[Reward] claim failed ({event_type}): {exc}")


def reward_unlock(module: str, unlock_type: str, name: str) -> None:
    """First-time unlock of a module item (egg, background, evolution, …)."""
    _claim("unlock", f"unlock:{module}:{unlock_type}:{name}")


def reward_evolution(module: str = "", name: str = "") -> None:
    """One grant per pet evolution.

    Uses a unique key so every evolution counts (jogress and armor evolutions
    included).  PenC jogress — where two pets evolve into two distinct pets —
    calls this twice, doubling the reward.
    """
    _claim("evolution", f"evolution:{module}:{name}:{uuid.uuid4().hex}")


def reward_new_pet(module: str, name: str, version: int) -> None:
    """First-time discovery of a pet (per module + pet + version)."""
    _claim("new_pet", f"new_pet:{module}:{name}:{version}")


def reward_area_clear(module: str, area) -> None:
    """First-time clear of an adventure area by defeating its boss."""
    _claim("area_clear", f"area_clear:{module}:{area}")


def reward_adventure_complete(module: str) -> None:
    """First-time completion of a module's entire adventure mode."""
    _claim("adventure", f"adventure:{module}")
