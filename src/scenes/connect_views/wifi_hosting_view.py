"""
WifiHostingView - host or join a WiFi battle on the local network.

Host: the game answers discovery and waits for one opponent
(``battle.lan_link.LanHost``), showing its code and address. Join: the
game asks the network for hosts (``lan_link.discover``), lists the ones that
answer and connects to the one picked. Either way the open link goes to the
battle confirmation (``battle_confirm``), which runs the battle itself
(``battle.lan_battle``).

The searching and connecting run on worker threads that only leave their
result on the view; update() acts on it on the game's thread.
"""
import threading

from ui.ui_manager import UIManager
from ui.components.title_scene import TitleScene
from ui.components.button import Button
from ui.components.background import Background
from ui.components.label import Label
from ui.components.menu import Menu
from ui.ui_constants import BASE_RESOLUTION
from core import runtime_globals
from battle import lan_link


def player_name():
    """The Omninet nickname, when the game is linked; else nothing."""
    try:
        from services.omninet_service import omninet_service
        return omninet_service.get_username() or ""
    except Exception:
        return ""


class WifiHostingView:
    """WiFi hosting and joining for local network battles."""

    HOST_JOIN_OPTIONS = ["Host Battle", "Join Battle", "Back"]

    def __init__(self, ui_manager: UIManager, change_view_callback,
                 selected_pets=None, is_online_mode=False, discord_module=None):
        """Initialize the WiFi hosting view.

        Args:
            ui_manager: The UI manager instance
            change_view_callback: Callback to change to another view
            selected_pets: The pets that will fight
            is_online_mode: Whether this is online mode
        """
        self.ui_manager = ui_manager
        self.change_view = change_view_callback
        self.selected_pets = selected_pets or []
        self.is_online_mode = is_online_mode

        # host_join_menu, hosting, searching, device_list, connecting
        self.phase = "host_join_menu"

        self.host = None              # LanHost while hosting
        self.host_code = ""
        self.hosts = []               # what the last search found
        self._search_stop = None      # set to end a search early
        self._found = None            # a finished search's hosts
        self._joined = None           # a finished connect's LanConnection
        self._join_error = None
        self._joining = None          # the host being connected to

        self.background = None
        self.title_scene = None
        self.host_join_menu = None
        self.device_list_menu = None
        self.heading_label = None
        self.code_label = None
        self.address_label = None
        self.status_label = None
        self.cancel_button = None

        self._setup_ui()

    # ------------------------------------------------------------------ UI
    def _setup_ui(self):
        ui_width = ui_height = BASE_RESOLUTION

        self.background = Background(ui_width, ui_height)
        self.background.set_regions([(0, ui_height, "black")])
        self.ui_manager.add_component(self.background)

        self.title_scene = TitleScene(0, 9, "CONNECT")
        self.ui_manager.add_component(self.title_scene)

        # Opened before it is added: the manager only takes input to a
        # component that is focusable when it arrives.
        self.host_join_menu = Menu(width=BASE_RESOLUTION - 40, height=100)
        self._open_host_join_menu()
        self.ui_manager.add_component(self.host_join_menu)

        self.heading_label = Label(10, 55, "", is_title=False)
        self.code_label = Label(10, 85, "", is_title=False)
        self.address_label = Label(10, 110, "", is_title=False)
        self.status_label = Label(10, 140, "", is_title=False)
        for label in (self.heading_label, self.code_label, self.address_label, self.status_label):
            label.visible = False
            self.ui_manager.add_component(label)

        cancel_width, cancel_height = 100, 35
        self.cancel_button = Button(
            (BASE_RESOLUTION - cancel_width) // 2, 190, cancel_width, cancel_height,
            "CANCEL", self._on_cancel
        )
        self.cancel_button.visible = False
        self.ui_manager.add_component(self.cancel_button)

        self._show_phase("host_join_menu")
        runtime_globals.game_console.log("[WifiHostingView] UI setup complete")

    def _open_host_join_menu(self):
        """(Re)populate the host/join menu.

        Menu.close() runs on every selection and clears the option list, so
        coming back to this phase has to rebuild the menu -- just setting it
        visible again showed an empty box with nothing to select.
        """
        self.host_join_menu.open(
            options=list(self.HOST_JOIN_OPTIONS),
            on_select=self._on_host_join_select,
            on_cancel=self._on_host_join_back,
            auto_center=True
        )

    def _set_lines(self, heading="", code="", address="", status=""):
        for label, text in ((self.heading_label, heading), (self.code_label, code),
                            (self.address_label, address), (self.status_label, status)):
            label.set_text(text)
            label.visible = bool(text)

    def _show_phase(self, phase, status=""):
        self.phase = phase
        self.host_join_menu.visible = False
        if self.device_list_menu:
            self.device_list_menu.visible = False
        self.cancel_button.visible = phase in ("hosting", "searching", "connecting")
        self._set_lines()

        if phase == "host_join_menu":
            self._open_host_join_menu()
            self.host_join_menu.visible = True
            self.ui_manager.set_focused_component(self.host_join_menu)
        elif self.cancel_button.visible:
            self.ui_manager.set_focused_component(self.cancel_button)

        if phase == "hosting":
            addresses = lan_link.local_addresses()
            self._set_lines("Hosting WiFi battle", f"Code: {self.host_code}",
                            f"IP: {addresses[0]}" if addresses else "",
                            status or "Waiting for opponent...")
        elif phase == "searching":
            self._set_lines("Join WiFi battle", status=status or "Searching for hosts...")
        elif phase == "device_list":
            self._open_device_list(status)
        elif phase == "connecting":
            code = (self._joining or {}).get("code", "")
            self._set_lines("Join WiFi battle", status=status or f"Connecting to {code}...")

    def _open_device_list(self, status=""):
        """The hosts the search found, then "Search again" and "Back"."""
        if self.device_list_menu:
            self.ui_manager.remove_component(self.device_list_menu)
        options = [self._host_label(h) for h in self.hosts] + ["Search again", "Back"]
        self.device_list_menu = Menu(width=BASE_RESOLUTION - 40, height=100)
        self.device_list_menu.open(options=options, on_select=self._on_device_select,
                                   on_cancel=self._on_device_list_back, auto_center=False,
                                   max_visible=5)
        self.ui_manager.add_component(self.device_list_menu)
        self.device_list_menu.set_position(20, 80)
        self.ui_manager.set_focused_component(self.device_list_menu)
        # One line above the list: what happened, or what to do.
        self._set_lines(status or ("Choose a host" if self.hosts else "No host found"))

    @staticmethod
    def _host_label(host):
        name = host.get("name") or host.get("address", "")
        return f"{host.get('code', '----')} {name}"[:22]

    # -------------------------------------------------------------- actions
    def _on_host_join_select(self, index):
        if index == 0:
            runtime_globals.game_sound.play("menu")
            self._start_hosting()
        elif index == 1:
            runtime_globals.game_sound.play("menu")
            self._start_search()
        else:
            runtime_globals.game_sound.play("cancel")
            self._stop_networking()
            self.change_view("main_menu", initial_submenu="local_battle")

    def _on_host_join_back(self):
        """B on the Host/Join menu: back to choosing the pets."""
        self._stop_networking()
        self.change_view("pet_selection", is_online_mode=self.is_online_mode)

    def _start_hosting(self):
        self.host_code = lan_link.host_code()
        self.host = lan_link.LanHost({"code": self.host_code, "name": player_name(),
                                      "pets": len(self.selected_pets)})
        try:
            self.host.start()
        except OSError as exc:
            runtime_globals.game_console.log(f"[WifiHostingView] Cannot host: {exc}")
            self.host = None
            self._show_phase("host_join_menu")
            self._set_lines("Cannot host on this network")
            return
        runtime_globals.game_console.log(
            f"[WifiHostingView] Hosting {self.host_code} on port {self.host.port}"
            + (f" ({self.host.error})" if self.host.error else ""))
        self._show_phase("hosting", "Waiting for opponent..." if self.host.discoverable
                         else "Others cannot find this game")

    def _start_search(self):
        stop = threading.Event()
        self._search_stop = stop
        self._found = None

        def work():
            try:
                found = lan_link.discover(stop=stop)
            except OSError as exc:
                runtime_globals.game_console.log(f"[WifiHostingView] Search failed: {exc}")
                found = []
            if not stop.is_set():
                self._found = found

        threading.Thread(target=work, daemon=True).start()
        self._show_phase("searching")

    def _on_device_select(self, index):
        if index < len(self.hosts):
            host = self.hosts[index]
            self._joining = host
            self._joined = self._join_error = None

            def work():
                try:
                    self._joined = lan_link.connect(host["address"], host["port"])
                except OSError as exc:
                    self._join_error = str(exc) or "refused"

            threading.Thread(target=work, daemon=True).start()
            self._show_phase("connecting")
        elif index == len(self.hosts):
            self._start_search()
        else:
            self._on_device_list_back()

    def _on_device_list_back(self):
        self._show_phase("host_join_menu")

    def _on_cancel(self):
        runtime_globals.game_sound.play("cancel")
        self._stop_networking()
        self._show_phase("host_join_menu")

    def _open_battle(self, link, is_host, enemy_name):
        """The link is up: on to the battle confirmation."""
        runtime_globals.game_console.log(
            f"[WifiHostingView] Connected to {link.peer} as {'host' if is_host else 'guest'}")
        if self.host is not None:
            self.host.close()
            self.host = None
        self.change_view("battle_confirm", connection_mode="wifi", link=link,
                         is_host=is_host, enemy_name=enemy_name,
                         selected_pets=self.selected_pets)

    def _stop_networking(self):
        if self._search_stop is not None:
            self._search_stop.set()
            self._search_stop = None
        if self.host is not None:
            self.host.close()
            self.host = None
        joined, self._joined = self._joined, None
        if joined is not None:
            joined.close()
        self._joining = None

    # ------------------------------------------------------------- frames
    def update(self):
        if self.phase == "host_join_menu" and not self.host_join_menu.visible:
            # A menu closes itself after its handler returns, so a handler
            # that comes back to this phase (hosting refused) left it shut.
            self._open_host_join_menu()
            self.host_join_menu.visible = True
            self.ui_manager.set_focused_component(self.host_join_menu)
        if self.phase == "hosting" and self.host is not None:
            link = self.host.poll()
            if link is not None:
                self._open_battle(link, True, "")
        elif self.phase == "searching" and self._found is not None:
            self.hosts, self._found = self._found, None
            self._search_stop = None
            runtime_globals.game_console.log(f"[WifiHostingView] Found {len(self.hosts)} host(s)")
            self._show_phase("device_list")
        elif self.phase == "connecting":
            if self._joined is not None:
                link, self._joined = self._joined, None
                self._open_battle(link, False, (self._joining or {}).get("name")
                                  or (self._joining or {}).get("code", ""))
            elif self._join_error is not None:
                runtime_globals.game_console.log(
                    f"[WifiHostingView] Connection failed: {self._join_error}")
                self._join_error = None
                self._show_phase("device_list", "Could not connect")
        elif self._joined is not None:
            # A connect that finished after its cancel.
            self._joined.close()
            self._joined = None

    def draw(self, surface):
        pass

    def handle_event(self, event):
        if not isinstance(event, tuple) or len(event) != 2:
            return
        event_type, _event_data = event
        if event_type == "B":
            if self.phase in ("hosting", "searching", "connecting"):
                self._on_cancel()
            elif self.phase == "host_join_menu":
                self._stop_networking()
                self.change_view("pet_selection", is_online_mode=self.is_online_mode)
            return True

    def cleanup(self):
        self._stop_networking()
        components = [
            self.background, self.title_scene, self.host_join_menu, self.device_list_menu,
            self.heading_label, self.code_label, self.address_label, self.status_label,
            self.cancel_button,
        ]
        for comp in components:
            if comp and comp in self.ui_manager.components:
                self.ui_manager.remove_component(comp)
        runtime_globals.game_console.log("[WifiHostingView] Cleanup complete")
