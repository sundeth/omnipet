"""
Scene Connect - Network connectivity and battles (View-based architecture)
Uses view architecture similar to scene_battle.py for clean separation of concerns.
"""
import pygame
import traceback

from ui.ui_manager import UIManager
from ui.windows.window_background import WindowBackground
from core import runtime_globals

# Import views
from scenes.connect_views import (
    MainMenuView,
    PetSelectionView,
    WifiHostingView,
    WifiDiscoveryView,
    DComView,
    WiFiComWarningView,
    WiFiComView,
    XrosView,
    DiscordView,
    LinkDialogView,
    OmninetLinkView,
    ShopView,
    ShopModulesView,
    ShopGameplayView,
    ShopItemsView,
    ShopCosmeticsView,
    ShopSpecialsView,
    BattleConfirmView,
    ArenaView,
    ArenaRulesView,
    ArenaHistoryView,
    ArenaTeamCreationView,
    ArenaReclaimView,
)


#=====================================================================
# Simple Discord Client (inline implementation)
#=====================================================================
class DiscordModule:
    """Simple Discord client for online battles."""
    
    def __init__(self):
        """Initialize Discord client."""
        import json
        import os
        import core.constants as constants
        
        self.bot_url = getattr(constants, 'DISCORD_BOT_URL', 'http://localhost:5000').rstrip('/')
        self.client = self
        self.is_connected = False
        self.linked_account = None
        self.account_name = None
        self.user_id = None
        self.current_room_id = None
        
        # Load saved data
        self._load_data()
        runtime_globals.game_console.log(f"[DiscordModule] Initialized with bot URL: {self.bot_url}")
    
    def _get_save_path(self):
        import os
        return os.path.join("save", "discord_data.json")
    
    def _save_data(self):
        """Save linked account data."""
        import json
        import os
        try:
            if not os.path.exists("save"):
                os.makedirs("save")
            data = {
                "linked_account": self.linked_account,
                "account_name": self.account_name,
                "user_id": self.user_id
            }
            with open(self._get_save_path(), 'w') as f:
                json.dump(data, f)
            runtime_globals.game_console.log("[DiscordModule] Saved account data")
        except Exception as e:
            runtime_globals.game_console.log(f"[DiscordModule] Failed to save: {e}")
    
    def _load_data(self):
        """Load linked account data."""
        import json
        import os
        try:
            path = self._get_save_path()
            if os.path.exists(path):
                with open(path, 'r') as f:
                    data = json.load(f)
                    self.linked_account = data.get("linked_account")
                    self.account_name = data.get("account_name")
                    self.user_id = data.get("user_id")
                    if self.linked_account:
                        runtime_globals.game_console.log(f"[DiscordModule] Loaded saved login: {self.account_name}")
        except Exception as e:
            runtime_globals.game_console.log(f"[DiscordModule] Failed to load: {e}")
    
    def check_connection(self) -> bool:
        """Check if Discord bot is reachable."""
        import requests
        try:
            response = requests.get(f"{self.bot_url}/health", timeout=2)
            is_ok = response.status_code == 200
            runtime_globals.game_console.log(f"[DiscordModule] Connection check: {is_ok}")
            return is_ok
        except Exception as e:
            runtime_globals.game_console.log(f"[DiscordModule] Connection failed: {e}")
            return False
    
    def get_account_name(self):
        """Get linked Discord account name."""
        return self.account_name
    
    def login(self, pairing_code: str) -> bool:
        """Link account with Discord."""
        import requests
        try:
            runtime_globals.game_console.log(f"[DiscordModule] Linking with code: {pairing_code}")
            response = requests.post(
                f"{self.bot_url}/link",
                json={"code": pairing_code},
                timeout=5
            )
            if response.status_code == 200:
                data = response.json()
                self.linked_account = pairing_code.upper()
                self.account_name = data.get('username')
                self.user_id = data.get('user_id')
                self._save_data()
                runtime_globals.game_console.log(f"[DiscordModule] Linked as: {self.account_name}")
                return True
            else:
                runtime_globals.game_console.log(f"[DiscordModule] Link failed: {response.text}")
                return False
        except Exception as e:
            runtime_globals.game_console.log(f"[DiscordModule] Link exception: {e}")
            return False
    
    def logout(self):
        """Unlink account."""
        import os
        self.linked_account = None
        self.account_name = None
        self.user_id = None
        try:
            path = self._get_save_path()
            if os.path.exists(path):
                os.remove(path)
                runtime_globals.game_console.log("[DiscordModule] Saved data deleted")
        except Exception as e:
            runtime_globals.game_console.log(f"[DiscordModule] Failed to delete data: {e}")


#=====================================================================
# SceneConnect - View-based architecture
#=====================================================================
class SceneConnect:
    """
    Scene for network connectivity and battles.
    Uses view-based architecture for clean separation of concerns.
    """

    def __init__(self) -> None:
        """Initialize the connect scene with view architecture."""
        runtime_globals.game_console.log("[SceneConnect] Starting initialization with view architecture...")
        
        # Use RED_DARK_VARIANT theme for connect scene
        self.ui_manager = UIManager("RED_DARK_VARIANT")
        
        # Connect input manager to UI manager for mouse handling
        self.ui_manager.set_input_manager(runtime_globals.game_input)
        
        # Global background
        self.window_background = WindowBackground(False)
        
        # Discord module (shared across views)
        self.discord = DiscordModule()
        
        # Current view
        self.current_view = None
        self.current_view_name = None
        
        # View kwargs (for passing data between views)
        self.view_kwargs = {}
        
        # Selected pets (shared across views for battle flow)
        self.selected_pets = []
        
        # If a caller set runtime_globals.scene_connect_initial_view, jump
        # directly to that view (e.g. "shop_modules" after login when the
        # player hasn't bought any modules yet).  Consumed once.
        initial = getattr(runtime_globals, 'scene_connect_initial_view', None)
        runtime_globals.scene_connect_initial_view = None
        if initial:
            try:
                self._change_view(initial)
            except Exception as exc:
                runtime_globals.game_console.log(
                    f"[SceneConnect] Failed to open initial view '{initial}': {exc}; "
                    "falling back to main menu")
                self._change_view("main_menu")
        else:
            self._change_view("main_menu")
        
        runtime_globals.game_console.log("[SceneConnect] Initialized with view architecture")
    
    def _change_view(self, view_name, **kwargs):
        """Change to a new view.

        Args:
            view_name: Name of the view to change to
            **kwargs: Additional arguments to pass to the view constructor
        """
        runtime_globals.game_console.log(f"[SceneConnect] Changing view: {self.current_view_name} -> {view_name}")
        
        # Cleanup old view
        if self.current_view:
            try:
                self.current_view.cleanup()
            except Exception as e:
                runtime_globals.game_console.log(f"[SceneConnect] Error cleaning up view {self.current_view_name}: {e}")
                runtime_globals.game_console.log(f"Traceback:\n{traceback.format_exc()}")
        
        # CRITICAL: Clear ALL components from UI manager to prevent overlapping
        # This ensures a clean slate for the new view
        self.ui_manager.components.clear()
        self.ui_manager.focusable_components.clear()
        # Nothing is focused until a component registers; 0 would point past
        # the end of an empty list.
        self.ui_manager.focused_index = -1
        runtime_globals.game_console.log(f"[SceneConnect] UI manager cleared, all components removed")
        
        # Update shared state
        if 'selected_pets' in kwargs:
            self.selected_pets = kwargs.pop('selected_pets')
        
        # Create new view
        self.current_view_name = view_name
        self.view_kwargs = kwargs
        
        view_map = {
            "main_menu": MainMenuView,
            "pet_selection": PetSelectionView,
            "wifi_hosting": WifiHostingView,
            "wifi_discovery": WifiDiscoveryView,
            "dcom": DComView,
            "wificom_warning": WiFiComWarningView,
            "wificom": WiFiComView,
            "xros": XrosView,
            "discord": DiscordView,
            "link_dialog": LinkDialogView,
            "omninet_link": OmninetLinkView,
            "shop": ShopView,
            "shop_modules": ShopModulesView,
            "shop_gameplay": ShopGameplayView,
            "shop_items": ShopItemsView,
            "shop_cosmetics": ShopCosmeticsView,
            "shop_specials": ShopSpecialsView,
            "battle_confirm": BattleConfirmView,
            "arena": ArenaView,
            "arena_rules": ArenaRulesView,
            "arena_history": ArenaHistoryView,
            "arena_team_creation": ArenaTeamCreationView,
            "arena_reclaim": ArenaReclaimView,
        }
        
        view_class = view_map.get(view_name)
        if not view_class:
            runtime_globals.game_console.log(f"[SceneConnect] ERROR: Unknown view '{view_name}'")
            return
        
        try:
            # Build kwargs for view constructor
            view_kwargs = {
                'ui_manager': self.ui_manager,
                'change_view_callback': self._change_view,
                'discord_module': self.discord,
            }
            
            # Add selected_pets only to views that consume it (not pet_selection which generates it)
            if view_name in ['dcom', 'wificom', 'xros', 'wifi_hosting',
                             'wifi_discovery', 'battle_confirm']:
                view_kwargs['selected_pets'] = self.selected_pets

            # Main menu's EXIT button must use the same exit routing as a B-press
            # (no pets + a module → egg selection), so hand it the scene's exit.
            if view_name == 'main_menu':
                view_kwargs['exit_callback'] = self._exit_to_game
            
            # Merge additional kwargs
            view_kwargs.update(kwargs)
            
            # Create view
            self.current_view = view_class(**view_kwargs)
            runtime_globals.game_console.log(f"[SceneConnect] Changed to view: {view_name}")
            
        except Exception as e:
            runtime_globals.game_console.log(f"[SceneConnect] ERROR creating view {view_name}: {e}")
            runtime_globals.game_console.log(f"Traceback:\n{traceback.format_exc()}")
            raise
    
    def update(self) -> None:
        """Update the current view and UI manager."""
        # Update UI manager first
        self.ui_manager.update()
        
        # Update current view
        if self.current_view:
            try:
                self.current_view.update()
            except Exception as e:
                runtime_globals.game_console.log(f"[SceneConnect] Error updating view: {e}")
                runtime_globals.game_console.log(f"Traceback:\n{traceback.format_exc()}")
    
    def draw(self, surface: pygame.Surface) -> None:
        """Draw the current view."""
        # Clear screen with background
        self.window_background.draw(surface)
        
        # Draw UI manager (handles all UI components)
        self.ui_manager.draw(surface)
        
        # Draw current view's additional elements (like minigames, animations)
        if self.current_view:
            try:
                self.current_view.draw(surface)
            except Exception as e:
                runtime_globals.game_console.log(f"[SceneConnect] Error drawing view: {e}")
                runtime_globals.game_console.log(f"Traceback:\n{traceback.format_exc()}")
    
    def handle_event(self, event) -> None:
        """Handle input events."""
        if not isinstance(event, tuple) or len(event) != 2:
            return
        
        event_type, event_data = event
        
        # A charge minigame takes every event: it is mashed with the same
        # keys the UI manager uses for focus and buttons, so the manager must
        # not see them at all while one is running.
        if (self.current_view
                and getattr(self.current_view, 'phase', None) == "minigame"
                and getattr(self.current_view, 'minigame', None)):
            self.current_view.handle_event(event)
            return
        
        # Handle mouse motion for UI cursor
        if event_type == "MOUSE_MOTION":
            if self.current_view:
                self.current_view.handle_event(event)
            self.ui_manager.handle_event(event)
            return
        
        # Let UI manager handle events first (buttons, menus, etc.)
        if self.ui_manager.handle_event(event):
            return  # Event was handled by UI manager
        
        # Translate B press to CANCEL for views
        if event_type == "B":
            if self.current_view:
                if self.current_view.handle_event(event):
                    return
            # If not handled by a view, exit to game from main menu
            if self.current_view_name == "main_menu":
                runtime_globals.game_sound.play("cancel")
                self._exit_to_game()
            return
        
        # Delegate to current view for any additional event handling
        if self.current_view:
            self.current_view.handle_event(event)
    
    def _exit_to_game(self):
        """Leave the connect scene.

        If the player has no pets but does have a module to hatch from
        (installed in Free Mode, installed + owned in Progress Mode), send
        them to the egg selection scene to start their first pet.  Otherwise
        just go to the main game scene.
        """
        from utils.scene_utils import change_scene
        from utils import navigation_utils
        from core import game_globals

        has_pets = bool(getattr(game_globals, 'pet_list', None))

        if not has_pets and navigation_utils.has_installed_owned_modules():
            change_scene("egg")
            return

        change_scene("game")

    def __del__(self):
        """Cleanup when scene is destroyed."""
        if self.current_view:
            try:
                self.current_view.cleanup()
            except:
                pass
