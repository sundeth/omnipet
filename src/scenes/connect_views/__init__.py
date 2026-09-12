"""
Views package for SceneConnect
Each view represents a distinct UI state in the connect scene.
"""

from .main_menu_view import MainMenuView
from .pet_selection_view import PetSelectionView
from .wifi_hosting_view import WifiHostingView
from .wifi_discovery_view import WifiDiscoveryView
from .dcom_view import DComView
from .wificom_warning_view import WiFiComWarningView
from .wificom_view import WiFiComView
from .xros_view import XrosView
from .discord_view import DiscordView
from .link_dialog_view import LinkDialogView
from .omninet_link_view import OmninetLinkView
from .shop_view import ShopView
from .shop_modules_view import ShopModulesView
from .shop_gameplay_view import ShopGameplayView
from .shop_items_view import ShopItemsView
from .shop_cosmetics_view import ShopCosmeticsView
from .shop_specials_view import ShopSpecialsView
from .battle_confirm_view import BattleConfirmView
from .arena_view import ArenaView
from .arena_rules_view import ArenaRulesView
from .arena_history_view import ArenaHistoryView
from .arena_team_creation_view import ArenaTeamCreationView
from .arena_reclaim_view import ArenaReclaimView

__all__ = [
    'MainMenuView',
    'PetSelectionView',
    'WifiHostingView',
    'WifiDiscoveryView',
    'DComView',
    'WiFiComWarningView',
    'WiFiComView',
    'XrosView',
    'DiscordView',
    'LinkDialogView',
    'OmninetLinkView',
    'ShopView',
    'ShopModulesView',
    'ShopGameplayView',
    'ShopItemsView',
    'ShopCosmeticsView',
    'ShopSpecialsView',
    'BattleConfirmView',
    'ArenaView',
    'ArenaRulesView',
    'ArenaHistoryView',
    'ArenaTeamCreationView',
    'ArenaReclaimView',
]
