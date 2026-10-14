from typing import List, Optional
from dataclasses import dataclass


@dataclass
class QuestData:
    """
    Data class for quest definitions loaded from JSON.
    This represents the template/definition of a quest, not an active quest instance.
    """
    id: str
    name: str
    type: int
    target_amount_range: Optional[List[int]] = None
    target_amount: Optional[int] = None
    reward_type: int = 0
    reward_value: Optional[str] = None
    reward_item: Optional[str] = None
    reward_quantity: int = 1
    reward_amount: int = 1


@dataclass
class EventData:
    """
    Data class for event definitions loaded from JSON.
    This represents the template/definition of an event, not an active event instance.

    ``type`` (models.game_event.EventType): 0 a special encounter (``area``/
    ``round``), 1 an item (``item`` x ``item_quantity``), 2 a battle with one
    of the Friends the party still needs, 3 a special encounter drawn from
    ``pools`` by a monster field of the pet (``pool_field``), 4 a run of
    special encounters, every round of ``area`` in turn, paying ``item`` after
    ``reward_round`` (0: the last), 5 access to the shop.json shop ``shop``
    for ``access_minutes`` (0: for good), 6 a card battle (the Vital
    Bracelet's random battle, utils.card_battle): a monster of the pet's own
    version by its ``encounter_chances``, each win paying the next item of
    ``item_sequence`` ("" a win without one).

    ``trigger``: "random" (the hourly XAI roll, ``chance_percent`` a weight
    among the module's random events), "adventure" (after an adventure
    battle), "area_clear" (after an adventure area is cleared), "connection"
    (after a battle with another device or pet) -- these three roll
    ``chance_percent`` as a chance in 100 -- or "schedule" (at the times of
    the pet's ``encounter_time_group`` in the module's schedule). A battle
    trigger takes ``outcome`` ("win", "loss", "any"); a connection one may
    name the ``opponent_device_version`` it needs. ``versions`` limits the
    event to pets of those versions, ``trigger_areas`` an adventure or area
    clear event to battles in those adventure areas (Digimon World's
    recruits, met in their own region). ``until_friend`` ends a special
    encounter event once its Digimon is the module's Friend (a recruit
    with nothing more to give). ``delay_minutes`` [min, max] holds a
    battle-triggered event back that long (a Friend battle's 1-5 minutes).
    See utils.event_utils.
    """
    id: str
    name: str
    global_event: bool = False
    type: int = 0
    chance_percent: float = 1
    area: int = 1
    round: int = 1
    item: str = ""
    item_quantity: int = 1
    trigger: str = "random"
    outcome: str = "win"
    opponent_device_version: Optional[int] = None
    versions: Optional[List[int]] = None
    pools: Optional[dict] = None
    pool_field: str = ""
    shop: str = ""
    access_minutes: int = 0
    reward_round: int = 0
    delay_minutes: Optional[List[int]] = None
    item_sequence: Optional[List[str]] = None
    trigger_areas: Optional[List[int]] = None
    until_friend: bool = False
