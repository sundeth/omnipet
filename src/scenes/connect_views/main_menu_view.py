"""
MainMenuView - Main connect menu with sub-menus
Shows Arena, LocalBattle, Shop, Config, Guide, and Exit buttons
"""
import threading
import time
import requests
from urllib.parse import urljoin

from ui.ui_manager import UIManager
from ui.components.title_scene import TitleScene
from ui.components.button import Button
from ui.components.label import Label
from ui.components.background import Background
from ui.components.tooltip_bar import TooltipBar
from ui.ui_constants import BASE_RESOLUTION
from core import runtime_globals, game_globals, constants
from utils.scene_utils import change_scene
from services.omninet_service import omninet_service


class MainMenuView:
    """Main connect menu view with Arena, LocalBattle, Shop, Config sub-menus."""
    
    def __init__(self, ui_manager: UIManager, change_view_callback, discord_module=None, initial_submenu=None, exit_callback=None):
        """Initialize the main menu view.

        Args:
            ui_manager: The UI manager instance
            change_view_callback: Callback to change to another view
            discord_module: Reference to the Discord module for account checks
            initial_submenu: Optional submenu to show initially ('arena', 'local_battle', 'config', or None for main)
            exit_callback: Called to leave the connect scene; routes to egg
                selection vs. main game (no pets + a module → egg).
        """
        self.ui_manager = ui_manager
        self.change_view = change_view_callback
        self.discord = discord_module
        self.exit_callback = exit_callback
        
        # Sub-menu state
        self.current_submenu = None  # None, 'arena', 'local_battle', 'config'
        
        # Component lists for each submenu (for easy show/hide)
        self.main_menu_components = []
        self.arena_submenu_components = []
        self.local_battle_submenu_components = []
        self.config_submenu_components = []
        
        # Availability flags (set by background threads)
        # None = not checked yet, True = available, False = unavailable
        self._shop_available = None
        self._wifi_available = None
        self._dcom_available = None
        self._wificom_available = None
        
        # Periodic check timers
        self.last_wifi_check_time = 0
        self.last_dcom_check_time = 0
        self.last_wificom_check_time = 0
        self.wifi_check_interval = 3.0
        self.dcom_check_interval = 3.0
        self.wificom_check_interval = 3.0
        
        # UI Components (shared across all views)
        self.background = None
        self.title_scene = None
        
        # Main menu buttons
        self.arena_button = None
        self.local_battle_button = None
        self.shop_button = None
        self.config_button = None
        self.guide_button = None
        self.exit_button = None
        
        # Arena sub-menu buttons
        self.arena_omninet_button = None
        self.arena_discord_button = None
        self.arena_back_button = None
        
        # Local Battle sub-menu buttons
        self.local_wificom_button = None
        self.local_wifi_button = None
        self.local_dcom_button = None
        self.local_back_button = None
        self.local_battle_tooltip = None
        
        # Config sub-menu buttons
        self.config_back_button = None
        
        # Config sub-menu labels for Omninet
        self.config_omninet_title_label = None
        self.config_omninet_status_label = None
        self.config_omninet_account_label = None
        self.config_omninet_button = None
        
        # Config sub-menu labels for Discord
        self.config_discord_title_label = None
        self.config_discord_status_label = None
        self.config_discord_account_label = None
        self.config_discord_button = None
        
        # Omninet module state
        self._omninet_available = None
        self._omninet_username = None
        self.last_omninet_check_time = 0
        self.omninet_check_interval = 3.0
        
        # Store initial submenu parameter
        self.initial_submenu = initial_submenu
        
        self._setup_ui()
        
        # Start background availability checks
        threading.Thread(target=self._check_shop_availability_async, daemon=True).start()
        
    def _setup_ui(self):
        """Setup the UI components for the main menu."""
        ui_width = ui_height = BASE_RESOLUTION
        
        # Background
        self.background = Background(ui_width, ui_height)
        self.background.set_regions([(0, ui_height, "black")])
        self.ui_manager.add_component(self.background)
        
        # Title
        self.title_scene = TitleScene(0, 9, "CONNECT")
        self.ui_manager.add_component(self.title_scene)
        
        # Setup main menu and sub-menu buttons
        self._setup_main_menu_buttons()
        self._setup_arena_submenu_buttons()
        self._setup_local_battle_submenu_buttons()
        self._setup_config_submenu_buttons()
        
        # Show initial view based on parameter
        if self.initial_submenu == "arena":
            self._show_arena_submenu()
        elif self.initial_submenu == "local_battle":
            self._show_local_battle_submenu()
        elif self.initial_submenu == "config":
            self._show_config_submenu()
        else:
            self._show_main_menu()
        
        runtime_globals.game_console.log("[MainMenuView] UI setup complete")
    
    def _setup_main_menu_buttons(self):
        """Setup main menu buttons."""
        main_button_width = 95
        main_button_height = 74
        
        title_bottom = 29
        vertical_gap = (BASE_RESOLUTION - title_bottom - (2 * main_button_height)) // 3
        
        top_row_y = title_bottom + vertical_gap
        bottom_row_y = top_row_y + main_button_height + vertical_gap
        
        horizontal_margin = 17
        horizontal_gap = (BASE_RESOLUTION - (2 * horizontal_margin) - (2 * main_button_width))
        
        left_button_x = horizontal_margin
        right_button_x = left_button_x + main_button_width + horizontal_gap
        
        # Arena button
        self.arena_button = Button(
            left_button_x, top_row_y, main_button_width, main_button_height, "", 
            self._on_arena_selected,
            decorators=["Connect_Arena"],
            cut_corners={'tl': False, 'tr': False, 'bl': True, 'br': True}
        )
        self.arena_button.visible = False
        self.ui_manager.add_component(self.arena_button)
        self.main_menu_components.append(self.arena_button)
        
        # LocalBattle button
        self.local_battle_button = Button(
            right_button_x, top_row_y, main_button_width, main_button_height, "", 
            self._on_local_battle_selected,
            decorators=["Connect_LocalBattle"],
            cut_corners={'tl': True, 'tr': True, 'bl': False, 'br': False}
        )
        self.local_battle_button.visible = False
        self.ui_manager.add_component(self.local_battle_button)
        self.main_menu_components.append(self.local_battle_button)
        
        # Shop button (starts with loading indicator)
        self.shop_button = Button(
            left_button_x, bottom_row_y, main_button_width, main_button_height, "", 
            self._on_shop_selected,
            decorators=["Connect_Shop", "Connect_Loading"],
            cut_corners={'tl': True, 'tr': True, 'bl': True, 'br': True}
        )
        self.shop_button.enabled = False
        self.shop_button.visible = False
        self.ui_manager.add_component(self.shop_button)
        self.main_menu_components.append(self.shop_button)
        
        # Small buttons bottom right
        small_button_width = 61
        small_button_heights = (main_button_height // 3) - 4
        small_button_gap = 2
        
        small_btn_y_start = bottom_row_y
        small_left_bt_x = right_button_x
        small_center_x = right_button_x + (main_button_width // 2) - (small_button_width // 2)
        small_right_x = right_button_x + main_button_width - small_button_width
        
        # Config button
        self.config_button = Button(
            small_left_bt_x, small_btn_y_start, small_button_width, small_button_heights,
            "CONFIG", self._on_config_selected,
            cut_corners={'tl': True, 'tr': False, 'bl': False, 'br': True}
        )
        self.config_button.visible = False
        self.ui_manager.add_component(self.config_button)
        self.main_menu_components.append(self.config_button)
        
        # Discord button (replaces the old GUIDE button — see _on_discord_selected)
        guide_y = small_btn_y_start + small_button_heights + small_button_gap
        self.guide_button = Button(
            small_center_x, guide_y, small_button_width, small_button_heights,
            "DISCORD", self._on_discord_selected,
            cut_corners={'tl': True, 'tr': False, 'bl': False, 'br': True}
        )
        self.guide_button.visible = False
        self.ui_manager.add_component(self.guide_button)
        self.main_menu_components.append(self.guide_button)
        
        # Exit button
        exit_y = guide_y + small_button_heights + small_button_gap
        self.exit_button = Button(
            small_right_x, exit_y, small_button_width, small_button_heights,
            "EXIT", self._on_exit,
            cut_corners={'tl': True, 'tr': False, 'bl': False, 'br': True}
        )
        self.exit_button.visible = False
        self.ui_manager.add_component(self.exit_button)
        self.main_menu_components.append(self.exit_button)
    
    def _setup_arena_submenu_buttons(self):
        """Setup Arena sub-menu buttons."""
        submenu_btn_width = 120
        submenu_btn_height = 40
        submenu_x = (BASE_RESOLUTION - submenu_btn_width) // 2
        submenu_y_start = 60
        
        self.arena_omninet_button = Button(
            submenu_x, submenu_y_start, submenu_btn_width, submenu_btn_height,
            "OMNINET", self._on_omninet_selected
        )
        self.arena_omninet_button.visible = False
        self.ui_manager.add_component(self.arena_omninet_button)
        self.arena_submenu_components.append(self.arena_omninet_button)
        
        self.arena_discord_button = Button(
            submenu_x, submenu_y_start + 50, submenu_btn_width, submenu_btn_height,
            "DISCORD", self._on_discord_selected
        )
        self.arena_discord_button.visible = False
        self.ui_manager.add_component(self.arena_discord_button)
        self.arena_submenu_components.append(self.arena_discord_button)
        
        self.arena_back_button = Button(
            submenu_x, submenu_y_start + 100, submenu_btn_width, submenu_btn_height,
            "BACK", self._on_arena_back
        )
        self.arena_back_button.visible = False
        self.ui_manager.add_component(self.arena_back_button)
        self.arena_submenu_components.append(self.arena_back_button)
    
    def _setup_local_battle_submenu_buttons(self):
        """Setup Local Battle sub-menu buttons."""
        main_button_width = 95
        main_button_height = 74
        
        title_bottom = 29
        vertical_gap = (BASE_RESOLUTION - title_bottom - (2 * main_button_height)) // 3
        
        top_row_y = title_bottom + vertical_gap
        bottom_row_y = top_row_y + main_button_height + vertical_gap
        
        horizontal_margin = 17
        horizontal_gap = (BASE_RESOLUTION - (2 * horizontal_margin) - (2 * main_button_width))
        
        left_button_x = horizontal_margin
        right_button_x = left_button_x + main_button_width + horizontal_gap
        
        small_button_width = 61
        small_button_heights = (main_button_height // 3) - 4
        
        # WiFiCom button
        self.local_wificom_button = Button(
            left_button_x, top_row_y, main_button_width, main_button_height,
            "", self._on_wificom_selected,
            decorators=["Connect_WifiCom", "Connect_Loading"],
            cut_corners={'tl': False, 'tr': True, 'bl': False, 'br': True}
        )
        self.local_wificom_button.visible = False
        self.local_wificom_button.enabled = False
        self.ui_manager.add_component(self.local_wificom_button)
        self.local_battle_submenu_components.append(self.local_wificom_button)
        
        # DCom button
        self.local_dcom_button = Button(
            right_button_x, top_row_y, main_button_width, main_button_height,
            "", self._on_dcom_selected,
            decorators=["Connect_DCom", "Connect_Loading"],
            cut_corners={'tl': True, 'tr': False, 'bl': True, 'br': False}
        )
        self.local_dcom_button.visible = False
        self.local_dcom_button.enabled = False
        self.ui_manager.add_component(self.local_dcom_button)
        self.local_battle_submenu_components.append(self.local_dcom_button)
        
        # WiFi button, below WiFiCom
        self.local_wifi_button = Button(
            left_button_x, bottom_row_y, main_button_width, main_button_height,
            "", self._on_wifi_selected,
            decorators=["Connect_LocalWifi", "Connect_Loading"],
            cut_corners={'tl': False, 'tr': True, 'bl': False, 'br': True}
        )
        self.local_wifi_button.visible = False
        self.local_wifi_button.enabled = False
        self.ui_manager.add_component(self.local_wifi_button)
        self.local_battle_submenu_components.append(self.local_wifi_button)
        
        # Back button
        self.local_back_button = Button(
            right_button_x, bottom_row_y, small_button_width, small_button_heights,
            "BACK", self._on_local_battle_back,
            cut_corners={'tl': True, 'tr': False, 'bl': False, 'br': True}
        )
        self.local_back_button.visible = False
        self.ui_manager.add_component(self.local_back_button)
        self.local_battle_submenu_components.append(self.local_back_button)
        
        # Tooltip bar for the highlighted option.  It sizes and places
        # itself along the bottom edge of the UI area.
        self.local_battle_tooltip = TooltipBar()
        self.local_battle_tooltip.visible = False
        self.ui_manager.add_component(self.local_battle_tooltip)
        self.local_battle_submenu_components.append(self.local_battle_tooltip)
    
    def _setup_config_submenu_buttons(self):
        """Setup Config sub-menu buttons and labels."""
        submenu_btn_width = 120
        submenu_btn_height = 22  # Reduced from 30 to fit better
        
        # Starting positions
        start_y = 28
        left_margin = 20
        btn_x = (BASE_RESOLUTION - submenu_btn_width) // 2
        
        # Omninet Section
        omninet_y = start_y
        
        # Omninet title
        self.config_omninet_title_label = Label(
            left_margin, omninet_y, "Omninet", is_title=True, shadow_mode="full"
        )
        self.config_omninet_title_label.visible = False
        self.ui_manager.add_component(self.config_omninet_title_label)
        self.config_submenu_components.append(self.config_omninet_title_label)
        
        # Omninet status (spacing below title)
        self.config_omninet_status_label = Label(
            left_margin, omninet_y + 20, "Status: Checking...", shadow_mode="full"
        )
        self.config_omninet_status_label.visible = False
        self.ui_manager.add_component(self.config_omninet_status_label)
        self.config_submenu_components.append(self.config_omninet_status_label)
        
        # Omninet account
        self.config_omninet_account_label = Label(
            left_margin, omninet_y + 33, "Account: None", shadow_mode="full"
        )
        self.config_omninet_account_label.visible = False
        self.ui_manager.add_component(self.config_omninet_account_label)
        self.config_submenu_components.append(self.config_omninet_account_label)
        
        # Omninet connect/disconnect button
        self.config_omninet_button = Button(
            btn_x, omninet_y + 47, submenu_btn_width, submenu_btn_height,
            "CONNECT", self._on_omninet_connect
        )
        self.config_omninet_button.visible = False
        self.ui_manager.add_component(self.config_omninet_button)
        self.config_submenu_components.append(self.config_omninet_button)
        
        # Discord Section (spacing from Omninet)
        discord_y = omninet_y + 82
        
        # Discord title
        self.config_discord_title_label = Label(
            left_margin, discord_y, "Discord", is_title=True, shadow_mode="full"
        )
        self.config_discord_title_label.visible = False
        self.ui_manager.add_component(self.config_discord_title_label)
        self.config_submenu_components.append(self.config_discord_title_label)
        
        # Discord status (spacing below title)
        self.config_discord_status_label = Label(
            left_margin, discord_y + 20, "Status: Not connected", shadow_mode="full"
        )
        self.config_discord_status_label.visible = False
        self.ui_manager.add_component(self.config_discord_status_label)
        self.config_submenu_components.append(self.config_discord_status_label)
        
        # Discord account
        self.config_discord_account_label = Label(
            left_margin, discord_y + 33, "Account: None", shadow_mode="full"
        )
        self.config_discord_account_label.visible = False
        self.ui_manager.add_component(self.config_discord_account_label)
        self.config_submenu_components.append(self.config_discord_account_label)
        
        # Discord link/unlink button
        self.config_discord_button = Button(
            btn_x, discord_y + 47, submenu_btn_width, submenu_btn_height,
            "LINK", self._on_link_selected
        )
        self.config_discord_button.visible = False
        self.ui_manager.add_component(self.config_discord_button)
        self.config_submenu_components.append(self.config_discord_button)
        
        # Back button at the bottom
        back_y = 200
        self.config_back_button = Button(
            btn_x, back_y, submenu_btn_width, submenu_btn_height,
            "BACK", self._on_config_back
        )
        self.config_back_button.visible = False
        self.ui_manager.add_component(self.config_back_button)
        self.config_submenu_components.append(self.config_back_button)
    
    def _hide_all_components(self):
        """Hide all submenu components by iterating over component lists."""
        for component in self.main_menu_components:
            component.visible = False
        for component in self.arena_submenu_components:
            component.visible = False
        for component in self.local_battle_submenu_components:
            component.visible = False
        for component in self.config_submenu_components:
            component.visible = False
    
    def _update_config_status(self):
        """Update the config submenu status labels and buttons."""
        # Update Omninet status from service
        omninet_username = omninet_service.get_username()
        
        # Free Mode: hide Omninet connect button entirely
        is_free = game_globals.is_free_mode()
        
        if self._omninet_available is None:
            self.config_omninet_status_label.set_text("Status: Checking...")
            self.config_omninet_account_label.set_text("Account: None")
            self.config_omninet_button.set_text("CONNECT")
            self.config_omninet_button.enabled = False
        elif self._omninet_available:
            if omninet_username:
                self.config_omninet_status_label.set_text("Status: Connected")
                self.config_omninet_account_label.set_text(f"Account: {omninet_username}")
                self.config_omninet_button.set_text("DISCONNECT")
                self.config_omninet_button.enabled = True
            else:
                self.config_omninet_status_label.set_text("Status: Available")
                self.config_omninet_account_label.set_text("Account: None")
                self.config_omninet_button.set_text("CONNECT")
                self.config_omninet_button.enabled = True
        else:
            self.config_omninet_status_label.set_text("Status: Offline")
            self.config_omninet_account_label.set_text("Account: None")
            self.config_omninet_button.set_text("CONNECT")
            self.config_omninet_button.enabled = False
        
        # Free Mode has no Omninet account: show only the connection status
        # and hide the account row and connect button (they rendered as empty
        # theme-colored rectangles over the section).
        if is_free:
            if self._omninet_available is None:
                self.config_omninet_status_label.set_text("Status: Checking...")
            elif self._omninet_available:
                self.config_omninet_status_label.set_text("Status: Online")
            else:
                self.config_omninet_status_label.set_text("Status: Offline")
            self.config_omninet_account_label.visible = False
            self.config_omninet_button.visible = False
            self.config_omninet_button.enabled = False
            self.config_omninet_button.focusable = False

        # Update Discord status.  Discord battles are available in Free Mode
        # too, so the button stays enabled regardless of game mode.
        discord_name = self.discord.get_account_name() if self.discord else None
        if discord_name:
            self.config_discord_status_label.set_text("Status: Linked")
            self.config_discord_account_label.set_text(f"Account: {discord_name}")
            self.config_discord_button.set_text("UNLINK")
        else:
            self.config_discord_status_label.set_text("Status: Not linked")
            self.config_discord_account_label.set_text("Account: None")
            self.config_discord_button.set_text("LINK")
        self.config_discord_button.enabled = True
        self.config_discord_button.focusable = True
    
    def _show_main_menu(self):
        """Show main menu buttons."""
        self._hide_all_components()
        self.current_submenu = None
        
        for component in self.main_menu_components:
            component.visible = True
        
        # Set initial keyboard focus on Local Battle
        if self.local_battle_button:
            self.ui_manager.set_focused_component(self.local_battle_button)
        
        # Disable Arena and Local Battle if no pets available
        has_pets = len(game_globals.pet_list) > 0
        if self.arena_button:
            # Arena is blocked in Free Mode
            arena_available = has_pets and not game_globals.is_free_mode()
            self.arena_button.enabled = arena_available
            self.arena_button.focusable = arena_available
        if self.local_battle_button:
            self.local_battle_button.enabled = has_pets
            self.local_battle_button.focusable = has_pets
        
        # Disable Exit if no modules installed (force user to buy a module)
        has_modules = self._has_installed_modules()
        if self.exit_button:
            self.exit_button.enabled = has_modules
            self.exit_button.focusable = has_modules

        # Discord button: enabled only when a Discord account is linked AND
        # the Discord bot/service is reachable.  Connectivity is checked
        # asynchronously so the menu stays responsive; until then we
        # disable based on the cached linked-account state.
        if self.guide_button:
            discord_linked = bool(
                self.discord and getattr(self.discord, 'account_name', None)
            )
            self.guide_button.enabled = discord_linked
            self.guide_button.focusable = discord_linked
            if discord_linked:
                self._check_discord_availability_async()
    
    def _has_installed_modules(self) -> bool:
        """Check if there are any playable modules installed (excluding Tutorial)."""
        for module_name, module in runtime_globals.game_modules.items():
            if module_name.lower() == "tutorial":
                continue
            # Check if module has any eggs (playable content)
            eggs = module.get_monsters_by_stage(0)
            if eggs:
                return True
        return False
    
    def _show_arena_submenu(self):
        """Show Arena sub-menu."""
        self._hide_all_components()
        self.current_submenu = 'arena'
        
        for component in self.arena_submenu_components:
            component.visible = True
    
    def _show_local_battle_submenu(self):
        """Show Local Battle sub-menu."""
        self._hide_all_components()
        self.current_submenu = 'local_battle'
        
        for component in self.local_battle_submenu_components:
            component.visible = True
        
        # Reset buttons to loading state
        self.local_wificom_button.decorators = ["Connect_WifiCom", "Connect_Loading"]
        self.local_wificom_button.enabled = False
        self.local_wificom_button.focusable = False
        if hasattr(self.local_wificom_button, 'on_manager_set'):
            self.local_wificom_button.on_manager_set()
        self.local_wificom_button.needs_redraw = True
        
        self.local_wifi_button.decorators = ["Connect_LocalWifi", "Connect_Loading"]
        self.local_wifi_button.enabled = False
        self.local_wifi_button.focusable = False
        if hasattr(self.local_wifi_button, 'on_manager_set'):
            self.local_wifi_button.on_manager_set()
        self.local_wifi_button.needs_redraw = True
        
        self.local_dcom_button.decorators = ["Connect_DCom", "Connect_Loading"]
        self.local_dcom_button.enabled = False
        self.local_dcom_button.focusable = False
        if hasattr(self.local_dcom_button, 'on_manager_set'):
            self.local_dcom_button.on_manager_set()
        self.local_dcom_button.needs_redraw = True
        
        # Reset availability flags and trigger checks
        self._wifi_available = None
        self._dcom_available = None
        self._wificom_available = None
        self.last_wifi_check_time = 0
        self.last_dcom_check_time = 0
        self.last_wificom_check_time = 0
        runtime_globals.game_console.log("[MainMenuView] Starting WiFi, DCom and WiFiCom availability checks...")
        threading.Thread(target=self._check_wifi_availability_async, daemon=True).start()
        threading.Thread(target=self._check_dcom_availability_async, daemon=True).start()
        threading.Thread(target=self._check_wificom_availability_async, daemon=True).start()
        
        # Set initial keyboard focus on Local WiFi.  WiFiCom sits above it
        # but cannot be used yet, so it does not take the opening focus.
        if self.local_wifi_button:
            self.ui_manager.set_focused_component(self.local_wifi_button)
    
    def _show_config_submenu(self):
        """Show Config sub-menu."""
        self._hide_all_components()
        self.current_submenu = 'config'
        
        runtime_globals.game_console.log("[MainMenuView] Showing config submenu components...")

        # Show all config components FIRST, then let the status update apply
        # its per-mode adjustments (doing it the other way round re-showed
        # components the status update had hidden, leaving broken rectangles
        # over the settings in Free Mode).
        for component in self.config_submenu_components:
            component.visible = True
        self._update_config_status()
        
        # Start checking Omninet availability if not checked yet
        if self._omninet_available is None:
            runtime_globals.game_console.log("[MainMenuView] Starting Omninet availability check...")
            threading.Thread(target=self._check_omninet_availability_async, daemon=True).start()
    
    # === Background availability checks ===
    
    def _check_shop_availability_async(self):
        """Background thread to check OmniNet availability."""
        runtime_globals.game_console.log("[MainMenuView] Checking OmniNet availability...")
        
        available = False
        local_url = getattr(constants, 'OMNINET_LOCAL_URL', None)
        if local_url:
            try:
                response = requests.get(urljoin(local_url, '/health'), timeout=2)
                if response.status_code == 200:
                    available = True
            except Exception:
                pass
        
        if not available:
            main_url = getattr(constants, 'OMNINET_MAIN_URL', None)
            if main_url:
                try:
                    response = requests.get(urljoin(main_url, '/health'), timeout=2)
                    if response.status_code == 200:
                        available = True
                except Exception:
                    pass
        
        self._shop_available = available
    
    def _check_wifi_availability_async(self):
        """Background thread to check WiFi availability."""
        runtime_globals.game_console.log("[MainMenuView] Checking WiFi availability...")
        try:
            import socket
            socket.create_connection(("8.8.8.8", 53), timeout=2)
            self._wifi_available = True
        except Exception:
            self._wifi_available = False
    
    def _check_wificom_availability_async(self):
        """Background thread to check WiFiCom availability.

        Two conditions, both of which the player can fix: the secrets
        file from the wificom.dev webapp has to be in place, and the
        machine has to be able to reach the internet.  Credentials are
        re-read each time so dropping the file in is picked up without a
        restart.
        """
        runtime_globals.game_console.log("[MainMenuView] Checking WiFiCom availability...")
        try:
            from services.wificom_service import (credentials_available,
                                                  internet_available,
                                                  transport_available)
            available = (transport_available()
                         and credentials_available()
                         and internet_available())
            self._wificom_available = available
        except Exception as e:
            runtime_globals.game_console.log(f"[MainMenuView] WiFiCom check failed: {e}")
            self._wificom_available = False
    
    def _check_dcom_availability_async(self):
        """Background thread to check DCom availability."""
        runtime_globals.game_console.log("[MainMenuView] Checking DCom availability...")
        
        available = False
        port_count = 0
        
        try:
            # Use the DComController device discovery logic to filter actual DCom devices
            from battle.dcom.dcom_controller import DComController
            controller = DComController()
            devices = controller.find_dcom_devices()
            port_count = len(devices)
            if devices:
                available = True
                runtime_globals.game_console.log(f"[MainMenuView] DCom device(s) detected: {port_count} device(s)")
                for port, desc in devices:
                    runtime_globals.game_console.log(f"  - {port}: {desc}")
            else:
                runtime_globals.game_console.log("[MainMenuView] No DCom devices detected")
        except Exception as e:
            runtime_globals.game_console.log(f"[MainMenuView] DCom check failed: {e}")
        
        self._dcom_available = available
    
    # === Button callbacks ===
    
    def _on_arena_selected(self):
        """Arena button clicked — go straight into the arena view.

        The intermediate submenu (Local Battle / Omninet) was redundant
        for the arena entry point; arena is always Omninet, so we route
        directly to ArenaView (after gating on Progress Mode + login).
        """
        runtime_globals.game_sound.play("menu")
        if not game_globals.is_progress_mode():
            runtime_globals.game_console.log("[MainMenuView] Arena requires Progress Mode")
            return
        if not omninet_service.is_logged_in():
            self.change_view("link_dialog", is_online_mode=True, return_view="arena")
            return
        self.change_view("arena")
    
    def _on_local_battle_selected(self):
        """Local Battle button clicked."""
        runtime_globals.game_sound.play("menu")
        self._show_local_battle_submenu()
    
    def _on_shop_selected(self):
        """Shop button clicked."""
        # Free Mode: allow shop without Omninet login
        if not game_globals.is_free_mode() and not omninet_service.is_logged_in():
            runtime_globals.game_console.log("[MainMenuView] Not logged in to Omninet, showing message")
            runtime_globals.game_sound.play("cancel")
            runtime_globals.tooltip = "You need to be logged in to Omninet to access the shop. Go to Config to login."
            return
        
        runtime_globals.game_sound.play("menu")
        self.change_view("shop")
    
    def _on_config_selected(self):
        """Config button clicked."""
        runtime_globals.game_sound.play("menu")
        self._show_config_submenu()
    
    def _on_guide_selected(self):
        """Guide button clicked."""
        runtime_globals.game_sound.play("menu")
        runtime_globals.game_console.log("[MainMenuView] Guide selected - not implemented")
    
    def _on_exit(self):
        """Exit button clicked."""
        runtime_globals.game_sound.play("cancel")
        # Route through the scene's exit so the no-pets + module → egg
        # selection check applies (same as a B-press exit).
        if self.exit_callback:
            self.exit_callback()
        else:
            change_scene("game")
    
    def _on_omninet_selected(self):
        """OmniNet (Arena) button clicked."""
        runtime_globals.game_sound.play("menu")

        # Arena is Progress-Mode-only; Free Mode players get a no-op.
        if not game_globals.is_progress_mode():
            runtime_globals.game_console.log("[MainMenuView] Arena requires Progress Mode")
            return

        # Need to be logged into Omninet; otherwise route through the link flow.
        if not omninet_service.is_logged_in():
            self.change_view("link_dialog", is_online_mode=True, return_view="arena")
            return

        self.change_view("arena")
    
    def _check_discord_availability_async(self):
        """Probe the Discord bot in the background; disable button on failure."""
        import threading

        def _worker():
            try:
                reachable = self.discord.check_connection() if self.discord else False
            except Exception:
                reachable = False
            if not reachable and self.guide_button:
                self.guide_button.enabled = False
                self.guide_button.focusable = False

        threading.Thread(target=_worker, daemon=True).start()

    def _on_discord_selected(self):
        """Discord button clicked.

        Requires both a linked Discord account and a reachable Discord bot.
        The button itself is disabled when either is missing (see
        _check_discord_availability_async), but we double-check here in case
        the user managed to activate it while the async probe was in flight.
        """
        runtime_globals.game_sound.play("menu")

        if not self.discord or not self.discord.get_account_name():
            # Not linked yet — send through the link dialog and come back.
            self.change_view("link_dialog", is_online_mode=True,
                             return_view="main_menu")
            return

        # Verify the bot is reachable before entering the pet picker.
        try:
            reachable = self.discord.check_connection()
        except Exception:
            reachable = False
        if not reachable:
            runtime_globals.game_console.log(
                "[MainMenuView] Discord bot unreachable; ignoring click")
            runtime_globals.game_sound.play("cancel")
            return

        self.change_view("pet_selection", is_online_mode=True)
    
    def _on_arena_back(self):
        """Arena sub-menu back button clicked."""
        runtime_globals.game_sound.play("cancel")
        self._show_main_menu()
    
    def _on_wificom_selected(self):
        """WiFiCom button clicked.

        Straight to the risk notice: nothing connects until the player
        has read it and said yes.
        """
        runtime_globals.game_sound.play("menu")
        self.change_view("wificom_warning")
    
    def _on_wifi_selected(self):
        """WiFi button clicked."""
        runtime_globals.game_sound.play("menu")
        self.change_view("wifi_hosting", is_online_mode=False)
    
    def _on_dcom_selected(self):
        """DCom button clicked."""
        runtime_globals.game_sound.play("menu")
        # Go to pet selection first, then to DCom
        self.change_view("pet_selection", is_dcom_mode=True)
    
    def _on_local_battle_back(self):
        """Local Battle sub-menu back button clicked."""
        runtime_globals.game_sound.play("cancel")
        self._show_main_menu()
    
    def _on_link_selected(self):
        """Discord Link button clicked."""
        runtime_globals.game_sound.play("menu")
        
        if self.discord and self.discord.get_account_name():
            # Unlink
            self.discord.logout()
            self._update_config_status()
        else:
            # Show link dialog
            self.change_view("link_dialog", is_online_mode=False, return_view="main_menu")
    
    def _on_omninet_connect(self):
        """Omninet Connect/Disconnect button clicked.

        In Free Mode the button reads CHANGE MODE and opens the game-mode
        selection instead (Omninet accounts are Progress-Mode-only).
        """
        runtime_globals.game_sound.play("menu")

        if game_globals.is_free_mode():
            game_globals.setup_input = False
            game_globals.setup_graphics = False
            game_globals.setup_game_mode = True
            game_globals.skip_tutorial_on_mode_switch = bool(game_globals.pet_list)
            change_scene("setup")
            return

        if omninet_service.is_logged_in():
            # Disconnect: drop the device key and bounce the player into the
            # login scene so they can sign in again or switch modes.  No
            # main-scene message slide — see the connect/login messaging
            # audit rule.
            omninet_service.logout()
            self._omninet_username = None
            self._update_config_status()
            runtime_globals.game_console.log("[MainMenuView] Disconnected from Omninet")
            change_scene("login")
            return
        else:
            # Progress Mode: redirect to SceneLogin for full login flow
            if game_globals.is_progress_mode():
                runtime_globals.game_console.log(
                    "[MainMenuView] Progress Mode â€” redirecting to SceneLogin")
                change_scene("login")
            else:
                # Free Mode: use inline pairing code view
                runtime_globals.game_console.log("[MainMenuView] Opening Omninet link view")
                self.change_view("omninet_link", return_view="main_menu")
    
    def _check_omninet_availability_async(self):
        """Background thread to check Omninet availability."""
        runtime_globals.game_console.log("[MainMenuView] Checking Omninet availability...")
        
        available = False
        
        # First check if server is available
        local_url = getattr(constants, 'OMNINET_LOCAL_URL', 'http://localhost:8000')
        try:
            runtime_globals.game_console.log(f"[MainMenuView] Trying Omninet at {local_url}/health")
            response = requests.get(urljoin(local_url, '/health'), timeout=2)
            runtime_globals.game_console.log(f"[MainMenuView] Response status: {response.status_code}")
            if response.status_code == 200:
                available = True
                runtime_globals.game_console.log(f"[MainMenuView] Omninet available at {local_url}")
        except Exception as e:
            runtime_globals.game_console.log(f"[MainMenuView] Connection failed: {e}")
        
        # Try main URL if local failed
        if not available:
            main_url = getattr(constants, 'OMNINET_MAIN_URL', None)
            if main_url:
                try:
                    response = requests.get(urljoin(main_url, '/health'), timeout=2)
                    if response.status_code == 200:
                        available = True
                        runtime_globals.game_console.log(f"[MainMenuView] Omninet available at {main_url}")
                except Exception:
                    pass
        
        # If server is available and we have saved credentials, try auto-login
        if available and omninet_service.has_saved_credentials():
            runtime_globals.game_console.log("[MainMenuView] Attempting auto-login with saved credentials...")
            success, msg, user_info = omninet_service.validate_device()
            if success and user_info:
                runtime_globals.game_console.log(f"[MainMenuView] Auto-login successful: {user_info.get('nickname')}")
            else:
                runtime_globals.game_console.log(f"[MainMenuView] Auto-login failed: {msg}")
        
        if not available:
            runtime_globals.game_console.log("[MainMenuView] Omninet is offline")
        
        self._omninet_available = available
    
    def _on_config_back(self):
        """Config sub-menu back button clicked."""
        runtime_globals.game_sound.play("cancel")
        self._show_main_menu()
    
    # === View methods ===
    
    def update(self):
        """Update the view."""
        # Handle shop availability result
        if self._shop_available is not None and self.shop_button:
            if self._shop_available:
                self.shop_button.decorators = ["Connect_Shop"]
                self.shop_button.enabled = True
            else:
                self.shop_button.decorators = ["Connect_Shop", "Connect_Offline"]
                self.shop_button.enabled = False
            
            if hasattr(self.shop_button, 'on_manager_set'):
                self.shop_button.on_manager_set()
            self.shop_button.needs_redraw = True
            self._shop_available = None
        
        # Handle WiFi availability result
        if self._wifi_available is not None and self.local_wifi_button and self.local_wifi_button.visible:
            runtime_globals.game_console.log(f"[MainMenuView] WiFi availability: {self._wifi_available}")
            if self._wifi_available:
                self.local_wifi_button.decorators = ["Connect_LocalWifi"]
                self.local_wifi_button.enabled = True
                self.local_wifi_button.focusable = True
            else:
                self.local_wifi_button.decorators = ["Connect_LocalWifi", "Connect_Offline"]
                self.local_wifi_button.enabled = False
                self.local_wifi_button.focusable = False
            
            if hasattr(self.local_wifi_button, 'on_manager_set'):
                self.local_wifi_button.on_manager_set()
            self.local_wifi_button.needs_redraw = True
            self._wifi_available = None
        
        # Handle DCom availability result
        if self._dcom_available is not None and self.local_dcom_button and self.local_dcom_button.visible:
            runtime_globals.game_console.log(f"[MainMenuView] DCom availability: {self._dcom_available}")
            if self._dcom_available:
                self.local_dcom_button.decorators = ["Connect_DCom"]
                self.local_dcom_button.enabled = True
                self.local_dcom_button.focusable = True
            else:
                self.local_dcom_button.decorators = ["Connect_DCom", "Connect_Offline"]
                self.local_dcom_button.enabled = False
                self.local_dcom_button.focusable = False
            
            if hasattr(self.local_dcom_button, 'on_manager_set'):
                self.local_dcom_button.on_manager_set()
            self.local_dcom_button.needs_redraw = True
            self._dcom_available = None
        
        # Handle WiFiCom availability result
        if self._wificom_available is not None and self.local_wificom_button and self.local_wificom_button.visible:
            runtime_globals.game_console.log(f"[MainMenuView] WiFiCom availability: {self._wificom_available}")
            if self._wificom_available:
                self.local_wificom_button.decorators = ["Connect_WifiCom"]
                self.local_wificom_button.enabled = True
                self.local_wificom_button.focusable = True
            else:
                self.local_wificom_button.decorators = ["Connect_WifiCom", "Connect_Offline"]
                self.local_wificom_button.enabled = False
                self.local_wificom_button.focusable = False
            
            if hasattr(self.local_wificom_button, 'on_manager_set'):
                self.local_wificom_button.on_manager_set()
            self.local_wificom_button.needs_redraw = True
            self._wificom_available = None
        
        # Handle Omninet availability result
        if self._omninet_available is not None and self.current_submenu == 'config':
            runtime_globals.game_console.log(f"[MainMenuView] Omninet availability: {self._omninet_available}")
            self._update_config_status()
            self._omninet_available = None
        
        # Periodic checks when in local battle submenu
        if self.current_submenu == 'local_battle':
            current_time = time.time()
            
            if current_time - self.last_wifi_check_time >= self.wifi_check_interval:
                self.last_wifi_check_time = current_time
                threading.Thread(target=self._check_wifi_availability_async, daemon=True).start()
            
            if current_time - self.last_dcom_check_time >= self.dcom_check_interval:
                self.last_dcom_check_time = current_time
                threading.Thread(target=self._check_dcom_availability_async, daemon=True).start()
            
            if current_time - self.last_wificom_check_time >= self.wificom_check_interval:
                self.last_wificom_check_time = current_time
                threading.Thread(target=self._check_wificom_availability_async, daemon=True).start()
            
            # Feed the tooltip bar the highlighted option's description
            if self.local_battle_tooltip:
                focused = None
                if 0 <= self.ui_manager.focused_index < len(self.ui_manager.focusable_components):
                    focused = self.ui_manager.focusable_components[self.ui_manager.focused_index]
                
                if focused == self.local_wificom_button:
                    self.local_battle_tooltip.set_text(
                        "Connects to real devices over the internet through wificom.dev, requires an internet connection"
                    )
                    self.local_battle_tooltip.visible = True
                elif focused == self.local_wifi_button:
                    self.local_battle_tooltip.set_text(
                        "Connects to another Omnipet in the local network, requires Wifi connection"
                    )
                    self.local_battle_tooltip.visible = True
                elif focused == self.local_dcom_button:
                    self.local_battle_tooltip.set_text(
                        "Connects to a real device using a D-Com, requires serial connection support"
                    )
                    self.local_battle_tooltip.visible = True
                else:
                    # Clearing the text as well as hiding restarts the read
                    # pause when the player comes back to an option.
                    self.local_battle_tooltip.set_text("")
                    self.local_battle_tooltip.visible = False
    
    def draw(self, surface):
        """Draw additional elements (if any)."""
        pass
    
    def handle_event(self, event):
        """Handle input events."""
        if not isinstance(event, tuple) or len(event) != 2:
            return
        
        event_type, event_data = event
        
        # Handle back/cancel button in sub-menus
        if event_type == "B":
            if self.current_submenu:
                runtime_globals.game_sound.play("cancel")
                self._show_main_menu()
                return True
    
    def cleanup(self):
        """Cleanup when view is destroyed."""
        # Remove all components from UI manager using the component lists
        all_components = [self.background, self.title_scene]
        all_components.extend(self.main_menu_components)
        all_components.extend(self.arena_submenu_components)
        all_components.extend(self.local_battle_submenu_components)
        all_components.extend(self.config_submenu_components)
        
        for comp in all_components:
            if comp and comp in self.ui_manager.components:
                self.ui_manager.remove_component(comp)
        
        runtime_globals.game_console.log("[MainMenuView] Cleanup complete")
