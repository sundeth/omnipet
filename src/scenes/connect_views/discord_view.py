"""
DiscordView - Discord online battles
Handles room browsing, hosting, and Discord-based matchmaking
"""
import time
import threading

from ui.ui_manager import UIManager
from ui.components.title_scene import TitleScene
from ui.components.button import Button
from ui.components.background import Background
from ui.components.label import Label
from ui.components.menu import Menu
from ui.ui_constants import BASE_RESOLUTION
from core import runtime_globals


class DiscordView:
    """Discord battle view for online matchmaking."""
    
    def __init__(self, ui_manager: UIManager, change_view_callback,
                 selected_pets=None, is_online_mode=True, discord_module=None):
        """Initialize the Discord view.
        
        Args:
            ui_manager: The UI manager instance
            change_view_callback: Callback to change to another view
            selected_pets: List of selected pets for battle
            is_online_mode: Whether this is online mode
            discord_module: Reference to the Discord module
        """
        self.ui_manager = ui_manager
        self.change_view = change_view_callback
        self.selected_pets = selected_pets or []
        self.is_online_mode = is_online_mode
        self.discord = discord_module
        
        # State
        self.phase = "host_join"  # host_join, browsing, hosting, polling
        self.is_host = False
        self.current_room_id = None
        self.available_rooms = []
        
        # Polling state
        self._polling = False
        self._poll_thread = None
        
        # UI Components
        self.background = None
        self.title_scene = None
        
        # Host/Join menu
        self.host_join_menu = None
        
        # Browser UI
        self.browser_title = None
        self.browser_status = None
        self.room_list_menu = None
        self.refresh_button = None
        self.back_button = None
        
        # Hosting UI
        self.host_title = None
        self.host_status = None
        self.host_cancel_button = None
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup the UI components."""
        ui_width = ui_height = BASE_RESOLUTION
        
        # Background
        self.background = Background(ui_width, ui_height)
        self.background.set_regions([(0, ui_height, "black")])
        self.ui_manager.add_component(self.background)
        
        # Title
        self.title_scene = TitleScene(0, 9, "CONNECT")
        self.ui_manager.add_component(self.title_scene)
        
        self._setup_host_join_menu()
        self._setup_browser_ui()
        self._setup_hosting_ui()
        
        self._show_phase("host_join")
        
        runtime_globals.game_console.log("[DiscordView] UI setup complete")
    
    def _setup_host_join_menu(self):
        """Setup the host/join selection menu."""
        self.host_join_menu = Menu(width=BASE_RESOLUTION - 40, height=100)
        self._open_host_join_menu()
        self.ui_manager.add_component(self.host_join_menu)

    def _open_host_join_menu(self):
        """(Re)populate the host/join menu: Menu.close() runs after every
        selection and clears its options, so coming back to this phase
        (Cancel, Back) showed an empty box."""
        self.host_join_menu.open(
            options=["Host Room", "Browse Rooms", "Back"],
            on_select=self._on_host_join_select,
            auto_center=True
        )
    
    def _setup_browser_ui(self):
        """Setup room browser UI."""
        self.browser_title = Label(0, 40, "Online Rooms", is_title=True)
        self.browser_title.visible = False
        self.ui_manager.add_component(self.browser_title)
        
        self.browser_status = Label(0, 70, "Searching...", is_title=False)
        self.browser_status.visible = False
        self.ui_manager.add_component(self.browser_status)
        
        self.room_list_menu = Menu(width=BASE_RESOLUTION - 40, height=110)
        self.room_list_menu.open(options=[], on_select=self._on_room_select, auto_center=False)
        self.room_list_menu.set_position(20, 90)
        self.room_list_menu.visible = False
        self.ui_manager.add_component(self.room_list_menu)
        
        self.refresh_button = Button(20, 205, 80, 30, "Refresh", self._on_refresh)
        self.refresh_button.visible = False
        self.ui_manager.add_component(self.refresh_button)
        
        self.back_button = Button(BASE_RESOLUTION - 100, 205, 80, 30, "Back", self._on_browser_back)
        self.back_button.visible = False
        self.ui_manager.add_component(self.back_button)
    
    def _setup_hosting_ui(self):
        """Setup room hosting UI."""
        self.host_title = Label(0, 40, "Hosting Room...", is_title=True)
        self.host_title.visible = False
        self.ui_manager.add_component(self.host_title)
        
        self.host_status = Label(0, 80, "Creating Room...", is_title=False)
        self.host_status.visible = False
        self.ui_manager.add_component(self.host_status)
        
        self.host_cancel_button = Button(
            (BASE_RESOLUTION - 120) // 2, 180, 120, 30, 
            "Cancel", self._on_host_cancel
        )
        self.host_cancel_button.visible = False
        self.ui_manager.add_component(self.host_cancel_button)
    
    def _hide_all(self):
        """Hide all phase components."""
        if self.host_join_menu: self.host_join_menu.visible = False
        if self.browser_title: self.browser_title.visible = False
        if self.browser_status: self.browser_status.visible = False
        if self.room_list_menu: self.room_list_menu.visible = False
        if self.refresh_button: self.refresh_button.visible = False
        if self.back_button: self.back_button.visible = False
        if self.host_title: self.host_title.visible = False
        if self.host_status: self.host_status.visible = False
        if self.host_cancel_button: self.host_cancel_button.visible = False
    
    def _show_phase(self, phase):
        """Show the appropriate UI for the given phase."""
        self._hide_all()
        self.phase = phase
        
        if phase == "host_join":
            self._open_host_join_menu()
            self.ui_manager.set_focused_component(self.host_join_menu)
        elif phase == "browsing":
            self.browser_title.visible = True
            self.browser_status.visible = True
            self.room_list_menu.visible = True
            self.refresh_button.visible = True
            self.back_button.visible = True
            self._refresh_rooms()
        elif phase == "hosting":
            self.host_title.visible = True
            self.host_status.visible = True
            self.host_cancel_button.visible = True
    
    def _on_host_join_select(self, index):
        """Host/Join menu selection."""
        if index == 0:  # Host
            runtime_globals.game_sound.play("menu")
            self._start_hosting()
        elif index == 1:  # Browse
            runtime_globals.game_sound.play("menu")
            self._show_phase("browsing")
        elif index == 2:  # Back
            runtime_globals.game_sound.play("cancel")
            self.change_view("main_menu")
    
    def _start_hosting(self):
        """Start hosting a Discord room."""
        self.is_host = True
        self._show_phase("hosting")
        
        # Create room in background
        threading.Thread(target=self._create_room_async, daemon=True).start()
    
    def _create_room_async(self):
        """Background thread to create a room."""
        try:
            if self.discord:
                pet = self.selected_pets[0] if self.selected_pets else None
                pet_name = getattr(pet, 'name', 'Unknown') if pet else 'Unknown'
                room_name = f"{self.discord.get_account_name()}'s Room"
                
                result = self.discord.create_room(room_name)
                if result:
                    self.current_room_id = result.get('room_id', result.get('id'))
                    self._hosting_created = True
                    self._hosting_room_id = self.current_room_id
                else:
                    self._hosting_error = "Failed to create room"
            else:
                self._hosting_error = "Discord not connected"
        except Exception as e:
            self._hosting_error = str(e)
    
    def _refresh_rooms(self):
        """Refresh the room list."""
        self.browser_status.set_text("Searching...")
        threading.Thread(target=self._fetch_rooms_async, daemon=True).start()
    
    def _fetch_rooms_async(self):
        """Background thread to fetch rooms."""
        try:
            if self.discord:
                rooms = self.discord.get_available_rooms()
                self._fetched_rooms = rooms or []
                self._rooms_updated = True
            else:
                self._fetched_rooms = []
                self._rooms_updated = True
        except Exception as e:
            runtime_globals.game_console.log(f"[DiscordView] Room fetch error: {e}")
            self._fetched_rooms = []
            self._rooms_updated = True
    
    def _on_room_select(self, index):
        """Room selected from list."""
        if index < len(self.available_rooms):
            room = self.available_rooms[index]
            runtime_globals.game_sound.play("menu")
            self._join_room(room)
    
    def _join_room(self, room):
        """Join a Discord room."""
        self.is_host = False
        self.current_room_id = room.get('room_id', room.get('id'))
        
        try:
            if self.discord and self.discord.join_room(self.current_room_id):
                runtime_globals.game_console.log(f"[DiscordView] Joined room {self.current_room_id}")
                self._start_polling()
                self.change_view("battle_confirm",
                                 connection_mode="discord",
                                 is_host=False,
                                 enemy_name=room.get('host', ''),
                                 selected_pets=self.selected_pets,
                                 is_online_mode=True,
                                 discord_room_id=self.current_room_id)
            else:
                runtime_globals.game_console.log("[DiscordView] Failed to join room")
                self.browser_status.set_text("Failed to join room")
        except Exception as e:
            runtime_globals.game_console.log(f"[DiscordView] Join error: {e}")
            self.browser_status.set_text(f"Error: {str(e)}")
    
    def _start_polling(self):
        """Start polling for room updates."""
        self._polling = True
        self._poll_thread = threading.Thread(target=self._poll_room_async, daemon=True)
        self._poll_thread.start()
    
    def _poll_room_async(self):
        """Background thread to poll room for updates."""
        while self._polling:
            try:
                if self.discord and self.current_room_id:
                    data = self.discord.poll_room()
                    if data:
                        # Check for opponent
                        if data.get('opponent') or data.get('player2'):
                            self._opponent_name = data.get('opponent') or data.get('player2')
                            self._discord_opponent_found = True
            except Exception as e:
                runtime_globals.game_console.log(f"[DiscordView] Poll error: {e}")
            time.sleep(1.0)
    
    def _on_refresh(self):
        """Refresh button clicked."""
        runtime_globals.game_sound.play("menu")
        self._refresh_rooms()
    
    def _on_browser_back(self):
        """Browser back button clicked."""
        runtime_globals.game_sound.play("cancel")
        self._show_phase("host_join")
    
    def _on_host_cancel(self):
        """Host cancel button clicked."""
        runtime_globals.game_sound.play("cancel")
        self._polling = False
        self._show_phase("host_join")
    
    def update(self):
        """Update the view."""
        # Handle room fetch result
        if getattr(self, '_rooms_updated', False):
            self._rooms_updated = False
            rooms = getattr(self, '_fetched_rooms', [])
            self.available_rooms = rooms
            
            if not rooms:
                self.browser_status.set_text("No rooms found")
                self.room_list_menu.open(options=[], on_select=self._on_room_select, auto_center=False)
            else:
                self.browser_status.set_text(f"Found {len(rooms)} room(s)")
                labels = [r.get('host', r.get('name', 'Unknown')) for r in rooms]
                self.room_list_menu.open(options=labels, on_select=self._on_room_select, auto_center=False)
                self.room_list_menu.set_position(20, 90)
        
        # Handle hosting creation result
        if getattr(self, '_hosting_created', False):
            self._hosting_created = False
            self.host_status.set_text("Room Created!\nWaiting for opponent...")
            self._start_polling()
        
        if getattr(self, '_hosting_error', None):
            error = self._hosting_error
            self._hosting_error = None
            self.host_status.set_text(f"Error: {error}")
        
        # Handle opponent found
        if getattr(self, '_discord_opponent_found', False):
            self._discord_opponent_found = False
            self.change_view("battle_confirm",
                             connection_mode="discord",
                             is_host=self.is_host,
                             enemy_name=getattr(self, '_opponent_name', '') or '',
                             selected_pets=self.selected_pets,
                             is_online_mode=True,
                             discord_room_id=self.current_room_id)
    
    def draw(self, surface):
        """Draw view-specific elements."""
        pass
    
    def handle_event(self, event):
        """Handle input events."""
        if not isinstance(event, tuple) or len(event) != 2:
            return
        
        event_type, event_data = event
        
        if event_type == "B":
            if self.phase == "browsing":
                self._on_browser_back()
            elif self.phase == "hosting":
                self._on_host_cancel()
            elif self.phase == "host_join":
                self.change_view("main_menu")
            return True
    
    def cleanup(self):
        """Cleanup when view is destroyed."""
        self._polling = False
        
        components = [
            self.background, self.title_scene, self.host_join_menu,
            self.browser_title, self.browser_status, self.room_list_menu,
            self.refresh_button, self.back_button,
            self.host_title, self.host_status, self.host_cancel_button,
        ]
        
        for comp in components:
            if comp and comp in self.ui_manager.components:
                self.ui_manager.remove_component(comp)
        
        runtime_globals.game_console.log("[DiscordView] Cleanup complete")
