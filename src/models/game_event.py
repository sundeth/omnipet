from enum import Enum


class EventType(Enum):
    ENEMY_BATTLE = 0
    ITEM_PACKAGE = 1
    # Resolved when the event fires: a Friend battle and a pooled encounter
    # become an ENEMY_BATTLE against the one chosen (utils.event_utils).
    FRIEND_BATTLE = 2
    POOL_BATTLE = 3
    # Every round of a special-encounter area in turn, a reward at the end.
    BATTLE_RUN = 4
    # Opens a shop.json shop marked ``event_only``.
    SHOP_ACCESS = 5
    # The Vital Bracelet's random battle: a character of the pet's own card
    # (utils.card_battle).
    CARD_BATTLE = 6


class GameEvent:
    """
    Represents a random event that can occur during gameplay.

    A BATTLE_RUN fights every special-encounter round of ``area`` in turn and
    pays ``item`` x ``item_quantity`` after ``reward_round`` (0: the last). A
    SHOP_ACCESS opens ``shop`` for ``access_minutes`` (0: for good). A
    CARD_BATTLE meets ``opponent``, the monster of ``opponent_version`` drawn
    when the event fired, and pays by its ``event_id``'s rules.
    """

    def __init__(self, event_id: str, name: str, module: str, global_event: bool,
                 event_type: EventType, chance_percent: int, area: int, round_num: int,
                 item: str = "", item_quantity: int = 1, shop: str = "",
                 access_minutes: int = 0, reward_round: int = 0,
                 opponent: str = "", opponent_version: int = 0):
        self.id = event_id
        self.name = name
        self.module = module
        self.global_event = global_event
        self.type = event_type
        self.chance_percent = chance_percent
        self.area = area
        self.round = round_num
        self.item = item
        self.item_quantity = item_quantity
        self.shop = shop
        self.access_minutes = access_minutes
        self.reward_round = reward_round
        self.opponent = opponent
        self.opponent_version = opponent_version

    def __str__(self) -> str:
        if self.type == EventType.ITEM_PACKAGE:
            return f"{self.name}: {self.item} x{self.item_quantity}"
        if self.type == EventType.SHOP_ACCESS:
            return f"{self.name}: {self.shop} opens"
        if self.type == EventType.CARD_BATTLE:
            return f"{self.name}: {self.opponent}"
        if self.type == EventType.BATTLE_RUN:
            return f"{self.name}: Battle run in Area {self.area}"
        return f"{self.name}: Battle Event in Area {self.area}"
