"""
BattleConfirmView - the last screen before a WiFi or online battle.

Both games arrive here with a link to each other -- a local connection
(``battle.lan_link``) for WiFi, a Discord relay room (``battle.relay_link``)
for an online battle -- and run the battle's handshake
(``battle.lan_battle.Session``): each says hello with its team, each player
presses START, the host fights the battle and sends the result, and both
open the PvP battle scene on it. Cancel (or the opponent leaving) ends it.
"""
from ui.ui_manager import UIManager
from ui.components.title_scene import TitleScene
from ui.components.button import Button
from ui.components.background import Background
from ui.components.label import Label
from ui.components.text_panel import TextPanel
from ui.ui_constants import BASE_RESOLUTION
from core import runtime_globals
from utils.scene_utils import change_scene


class BattleConfirmView:
    """Pre-battle confirmation for a WiFi or online battle."""

    STATUS = {
        "hello": "Connecting...",
        "confirm": "Press START to battle",
        "waiting": "Waiting for opponent...",
    }

    def __init__(self, ui_manager: UIManager, change_view_callback,
                 connection_mode="wifi", link=None, is_host=False, enemy_name="",
                 selected_pets=None, discord_module=None, discord_room_id=None,
                 **_other_modes):
        """Initialize the battle confirm view.

        Args:
            ui_manager: The UI manager instance
            change_view_callback: Callback to change to another view
            connection_mode: "wifi" or "discord"
            link: The open LanConnection to the other game (WiFi)
            is_host: Whether this game hosted (it then fights the battle)
            enemy_name: What the joining list called the host, until its
                hello names it
            selected_pets: The pets that fight
            discord_module: The Discord client (online battles)
            discord_room_id: The relay room both players are in (online)
        """
        self.ui_manager = ui_manager
        self.change_view = change_view_callback
        self.connection_mode = connection_mode
        self.is_host = is_host
        self.enemy_name = enemy_name
        self.selected_pets = list(selected_pets or [])
        self.discord = discord_module
        self.session = None
        self._started = False

        name = None
        if connection_mode == "discord" and link is None and discord_room_id and discord_module:
            link = discord_module.room_link(discord_room_id, is_host)
            name = discord_module.get_account_name() or ""
        if connection_mode in ("wifi", "discord") and link is not None and self.selected_pets:
            from battle.lan_battle import Session
            from core.version import VERSION
            from scenes.connect_views.wifi_hosting_view import player_name
            self.session = Session(link, is_host, self.selected_pets,
                                   name=player_name() if name is None else name, game=VERSION)
        elif link is not None:
            link.close()

        self.background = None
        self.title_scene = None
        self.info_panel = None
        self.status_label = None
        self.start_button = None
        self.cancel_button = None
        self._shown_state = None

        self._setup_ui()

    def _setup_ui(self):
        ui_width = ui_height = BASE_RESOLUTION

        self.background = Background(ui_width, ui_height)
        self.background.set_regions([(0, ui_height, "black")])
        self.ui_manager.add_component(self.background)

        self.title_scene = TitleScene(
            0, 9, "ONLINE BATTLE" if self.connection_mode == "discord" else "WIFI BATTLE")
        self.ui_manager.add_component(self.title_scene)

        self.info_panel = TextPanel(20, 45, ui_width - 40, 95, self._info_text())
        self.ui_manager.add_component(self.info_panel)

        self.status_label = Label(20, 148, "", is_title=False)
        self.ui_manager.add_component(self.status_label)

        btn_y, btn_w, btn_h, gap = 180, 80, 30, 20
        self.start_button = Button(
            (BASE_RESOLUTION // 2) - btn_w - (gap // 2), btn_y, btn_w, btn_h,
            "START", self._on_start
        )
        self.ui_manager.add_component(self.start_button)

        self.cancel_button = Button(
            (BASE_RESOLUTION // 2) + (gap // 2), btn_y, btn_w, btn_h,
            "CANCEL", self._on_cancel
        )
        self.ui_manager.add_component(self.cancel_button)

        self._refresh()
        runtime_globals.game_console.log(
            f"[BattleConfirmView] Ready - mode={self.connection_mode} host={self.is_host}")

    # ------------------------------------------------------------- display
    def _info_text(self):
        mine = ", ".join(getattr(p, "name", "?") for p in self.selected_pets)
        session = self.session
        if session is None or session.opponent is None:
            opponent = self.enemy_name or "?"
            theirs = "..."
        else:
            opponent = session.opponent["name"] or self.enemy_name or "Rival"
            theirs = ", ".join(e["name"] for e in session.opponent["team"])
        return f"Opponent: {opponent}. Their team: {theirs}. Your team: {mine}."

    def _refresh(self):
        """Show the session's state (once per change)."""
        session = self.session
        if session is None:
            state, status = "unavailable", "Battle not available"
        else:
            state = session.state
            status = session.error if state == "closed" else self.STATUS.get(state, "")
        if state == self._shown_state:
            return
        self._shown_state = state
        self.status_label.set_text(status)
        self.info_panel.set_text(self._info_text())
        self.start_button.set_enabled(state == "confirm")
        self.cancel_button.set_text("BACK" if state in ("closed", "unavailable") else "CANCEL")

    # ------------------------------------------------------------- actions
    def _on_start(self):
        if self.session is not None and self.session.press_start():
            runtime_globals.game_sound.play("menu")
            runtime_globals.game_console.log("[BattleConfirmView] START pressed")
            self._refresh()

    def _on_cancel(self):
        runtime_globals.game_sound.play("cancel")
        if self.session is not None:
            self.session.cancel()
        if self.connection_mode == "discord":
            self.change_view("discord", selected_pets=self.selected_pets, is_online_mode=True)
        else:
            self.change_view("wifi_hosting", selected_pets=self.selected_pets)

    def _start_battle(self):
        """The log is in: open the battle scene on it from this game's seat."""
        from battle.lan_battle import pvp_battle_data
        self._started = True
        try:
            data = pvp_battle_data(self.session.log, self.selected_pets, self.is_host,
                                   online=self.connection_mode == "discord")
        except Exception as exc:  # pylint: disable=broad-except
            runtime_globals.game_console.log(f"[BattleConfirmView] Cannot show the battle: {exc}")
            self.session.error = "Battle could not be shown"
            self.session.log = None
            self.session.close()
            self._refresh()
            return
        self.session.close()
        runtime_globals.pvp_battle_data = data
        runtime_globals.game_console.log(
            f"[BattleConfirmView] Battle: {data['simulation_data']['victory_status']}")
        change_scene("battle_pvp")

    def update(self):
        if self.session is None or self._started:
            return
        if self.session.update() == "battle":
            self._start_battle()
            return
        self._refresh()

    def draw(self, surface):
        pass

    def handle_event(self, event):
        if not isinstance(event, tuple) or len(event) != 2:
            return
        event_type, _event_data = event
        if event_type == "B":
            self._on_cancel()
            return True
        if event_type in ("A", "START"):
            self._on_start()
            return True

    def cleanup(self):
        if self.session is not None and not self._started:
            self.session.cancel()
        components = [
            self.background, self.title_scene, self.info_panel, self.status_label,
            self.start_button, self.cancel_button,
        ]
        for comp in components:
            if comp and comp in self.ui_manager.components:
                self.ui_manager.remove_component(comp)
        runtime_globals.game_console.log("[BattleConfirmView] Cleanup complete")
