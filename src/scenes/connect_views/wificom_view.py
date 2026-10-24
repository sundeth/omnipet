"""
WiFiComView - Omnipet on the air as a WiFiCom.

The pet is the toy behind a WiFiCom: an app sends a DigiROM through
wificom.dev, the pet answers it on the line the player chose, and a whole
battle plays out in the battle scene the way a DCom one does.

    choose the exact line -> battle items (iC weapons) -> charge minigame
    -> online: answer DigiROMs -> battle scene

The line is the player's choice, as in DCom: wificom.dev's request names
none, and several lines share one wire, so it cannot be read off the ROM.
The grid starts on the pet's own line. The charge is played before going
online and every DigiROM is answered with it.

A turn-1 DigiROM has the adapter open the exchange, and the pet answers it at
once. A turn-2 DigiROM has the adapter listen, so the toy has to start the
battle -- on a real one the player presses its button; here it is BATTLE!.

`services/wificom_service.py` owns the MQTT connection on its own thread;
this view only reads its state, plays what it hands over and leaves.
"""
import time

from ui.ui_manager import UIManager
from ui.components.title_scene import TitleScene
from ui.components.button import Button
from ui.components.background import Background
from ui.components.label import Label
from ui.components.menu import Menu
from ui.components.protocol_selector import ProtocolSelector
from ui.minigames.minigame_session import MinigameSession
from ui.ui_constants import BASE_RESOLUTION
from core import runtime_globals
from battle.sim import protocol_constants
from services.wificom_service import wificom_service, STATE_ONLINE

#: How long a note replaces the service's status line.
MESSAGE_SECONDS = 4.0


class WiFiComView:
    """The WiFiCom screen: choose the line, charge, then answer DigiROMs."""

    def __init__(self, ui_manager: UIManager, change_view_callback,
                 selected_pets=None, discord_module=None):
        """Initialize the WiFiCom view.

        Args:
            ui_manager: The UI manager instance
            change_view_callback: Callback to change to another view
            selected_pets: The pet that will fight, as a one-item list (a
                temporary evolution when one was chosen)
        """
        self.ui_manager = ui_manager
        self.change_view = change_view_callback
        self.selected_pets = selected_pets or []
        self.pet = self.selected_pets[0] if self.selected_pets else None

        # protocol_select, battle_items, minigame, online, done
        self.phase = "protocol_select"
        self.battle_format = None
        self.minigame = None
        self.charge = 0
        self._settle_at = 0
        #: A turn-2 DigiROM waiting for BATTLE!.
        self.pending = None
        #: Replaces the status line for a few seconds.
        self._message = None
        self._message_until = 0
        self._last_status = None
        self.abort = False

        self.background = None
        self.title_scene = None
        self.status_label = None
        self.pet_label = None
        self.format_label = None
        self.battle_button = None
        self.back_button = None
        self.protocol_menu = None
        self.items_menu = None

        self._setup_ui()
        if self.pet is None:
            runtime_globals.game_console.log("[WiFiComView] No pet selected")
            self.abort = True
            return
        self._show_protocol_selection()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _setup_ui(self):
        """Setup the UI components."""
        ui_width = ui_height = BASE_RESOLUTION

        self.background = Background(ui_width, ui_height)
        self.background.set_regions([(0, ui_height, "black")])
        self.ui_manager.add_component(self.background)

        self.title_scene = TitleScene(0, 9, "WIFICOM")
        self.ui_manager.add_component(self.title_scene)

        self.status_label = Label(
            ui_width // 2, 62, "", is_title=True, center=True,
            word_wrap=True, max_width=ui_width - 24, center_lines=True
        )
        self.ui_manager.add_component(self.status_label)

        pet_name = getattr(self.pet, 'name', 'No pet') if self.pet else 'No pet'
        self.pet_label = Label(
            ui_width // 2, 130, pet_name, center=True,
            word_wrap=True, max_width=ui_width - 24, center_lines=True
        )
        self.ui_manager.add_component(self.pet_label)

        self.format_label = Label(
            ui_width // 2, 150, "", center=True,
            word_wrap=True, max_width=ui_width - 24, center_lines=True
        )
        self.ui_manager.add_component(self.format_label)

        btn_width = 80
        btn_height = 26
        btn_gap = 16
        btn_y = ui_height - btn_height - 18
        battle_x = (ui_width // 2) - btn_width - (btn_gap // 2)
        back_x = (ui_width // 2) + (btn_gap // 2)

        self.battle_button = Button(
            battle_x, btn_y, btn_width, btn_height,
            "BATTLE!", self._on_battle,
            cut_corners={'tl': False, 'tr': True, 'bl': False, 'br': True}
        )
        # Only a DigiROM waiting for the toy to start it can be battled.
        self.battle_button.enabled = False
        self.ui_manager.add_component(self.battle_button)

        self.back_button = Button(
            back_x, btn_y, btn_width, btn_height,
            "BACK", self._on_back,
            cut_corners={'tl': True, 'tr': False, 'bl': True, 'br': False}
        )
        self.ui_manager.add_component(self.back_button)
        self._show_waiting_screen(False)

        runtime_globals.game_console.log("[WiFiComView] UI setup complete")

    def _show_waiting_screen(self, shown):
        """The labels and buttons of the online screen; hidden before it."""
        for component in (self.status_label, self.pet_label, self.format_label,
                          self.battle_button, self.back_button):
            if component is not None:
                component.visible = shown
                component.needs_redraw = True

    # ------------------------------------------------------------------
    # The line
    # ------------------------------------------------------------------

    def _pet_line(self):
        """The device line the pet's module belongs to, for the grid's focus.

        A line can name its module outright (`IC.NATIVE_MODULES`), so that
        is checked before the module's declared ``battle_protocol``.
        """
        module_name = getattr(self.pet, 'module', '')
        for battle_format in protocol_constants.BATTLE_FORMATS:
            if module_name in protocol_constants.native_modules(battle_format):
                return battle_format
        try:
            from utils.module_utils import get_module
            module = get_module(module_name)
            declared = protocol_constants.canonical_format(
                getattr(module, 'battle_protocol', '') if module else '')
        except Exception:  # pylint: disable=broad-except
            declared = None
        return declared if declared in protocol_constants.BATTLE_FORMATS else None

    def _show_protocol_selection(self, focus=None, note=None):
        """The device-line grid, shared with DCom and versus."""
        self.phase = "protocol_select"
        self._show_waiting_screen(False)
        self.protocol_menu = ProtocolSelector()
        self.protocol_menu.open(protocol_constants.menu_entries(_debug_mode()),
                                self._on_protocol_select,
                                on_cancel=self._on_back,
                                focus=focus or self._pet_line(), note=note)
        self.ui_manager.add_component(self.protocol_menu)
        self.ui_manager.set_active_menu(self.protocol_menu)

    def _close_menu(self, attribute):
        menu = getattr(self, attribute, None)
        if not menu:
            return
        menu.close()
        if self.ui_manager.active_menu is menu:
            self.ui_manager.active_menu = None
        self.ui_manager.remove_component(menu)
        setattr(self, attribute, None)

    def _on_protocol_select(self, battle_format):
        """Line chosen: it is the exact one every DigiROM is answered on."""
        self._close_menu('protocol_menu')
        if battle_format not in protocol_constants.BATTLE_FORMATS:
            # Offered ahead of its battle format (TWIN, in debug mode). DCom
            # can record one; a WiFiCom can only answer with a battle.
            self._show_protocol_selection(
                focus=battle_format, note=f"{battle_format} is not ready yet")
            return
        self.battle_format = battle_format
        runtime_globals.game_console.log(f"[WiFiComView] Battle format: {battle_format}")
        self._offer_battle_items()

    # ------------------------------------------------------------------
    # Battle items and the charge
    # ------------------------------------------------------------------

    def _wire_items(self):
        """The iC's weapons, which this line puts on the wire (packet 3)."""
        if self.battle_format != "IC" or not self.pet:
            return []
        from utils import battle_items
        module = runtime_globals.game_modules.get(getattr(self.pet, "module", None))
        return battle_items.wire_items(module, self.pet) if module is not None else []

    def _offer_battle_items(self):
        rows = self._wire_items()
        if not rows:
            self._start_minigame()
            return
        from utils import battle_items
        self.phase = "battle_items"
        self.items_menu = Menu(width=170, height=60)
        self.items_menu.open(battle_items.menu_options(rows), on_select=self._on_battle_item,
                             on_cancel=self._end_battle_items, max_visible=5)
        self.ui_manager.add_component(self.items_menu)
        self.ui_manager.set_active_menu(self.items_menu)

    def _on_battle_item(self, index):
        if index == 0:
            self._end_battle_items()
            return
        from utils import battle_items
        rows = self._wire_items()
        if 0 < index <= len(rows):
            item, _quantity = rows[index - 1]
            notes = battle_items.use_battle_item(item, [self.pet])
            runtime_globals.game_sound.play("happy2")
            for note in [f"{item.name} used!"] + list(notes or []):
                runtime_globals.game_message.add_slide(
                    note, (255, 255, 0), 56 * runtime_globals.UI_SCALE,
                    runtime_globals.FONT_SIZE_SMALL)
        self._close_menu('items_menu')
        self._offer_battle_items()

    def _end_battle_items(self):
        self._close_menu('items_menu')
        self._start_minigame()

    def _start_minigame(self):
        """The line's charge minigame, if it has one."""
        name = protocol_constants.get_constants(self.battle_format).MINIGAME
        if name == "None":
            self.charge = 0
            self._go_online()
            return
        self.phase = "minigame"
        self.minigame = MinigameSession(name, self.ui_manager, self.pet)

    def _finish_minigame(self):
        from battle.sim.dcom_battle_simulator import DComBattleSimulator
        self.charge = DComBattleSimulator(
            None, battle_format=self.battle_format).charge_value(self.minigame)
        runtime_globals.game_console.log(f"[WiFiComView] Charge complete: {self.charge}")
        self.minigame = None
        # A short pause so the last press of a mashed minigame cannot fall
        # through onto the BACK button drawn next.
        self._settle_at = time.monotonic() + 0.5

    def _on_minigame_cancel(self):
        """Backing out of the charge returns to picking a pet, as in DCom."""
        runtime_globals.game_sound.play("cancel")
        self.minigame = None
        self.change_view("pet_selection", is_wificom_mode=True)

    # ------------------------------------------------------------------
    # Online
    # ------------------------------------------------------------------

    def _go_online(self):
        """Bring Omnipet up as a WiFiCom, for this pet on this line."""
        self.phase = "online"
        self._show_waiting_screen(True)
        constants = protocol_constants.get_constants(self.battle_format)
        self.format_label.set_text(getattr(constants, 'DISPLAY_NAME', self.battle_format))
        self.status_label.set_text("Connecting...")
        self.ui_manager.set_focused_component(self.back_button)
        wificom_service.set_pet(self.pet, self.battle_format, self.charge)
        wificom_service.start()

    def _on_battle(self):
        """BATTLE! -- start the battle a turn-2 DigiROM is waiting for.

        Turn 2 means the adapter listens and the toy opens, as the player
        pressing the toy's button would.
        """
        rom, self.pending = self.pending, None
        if rom is None:
            return
        runtime_globals.game_sound.play("menu")
        self._play(rom)

    def _on_back(self):
        """Back -- take the service down and leave."""
        runtime_globals.game_sound.play("cancel")
        wificom_service.stop()
        self.change_view("main_menu", initial_submenu="local_battle")

    def _show_message(self, text, seconds=MESSAGE_SECONDS):
        """Show *text* in place of the service status for a moment."""
        self._message = text
        self._message_until = time.monotonic() + seconds
        runtime_globals.game_console.log(f"[WiFiComView] {text}")

    def _take_incoming(self):
        rom = wificom_service.take_incoming()
        if rom is None:
            return
        if rom.turn == protocol_constants.DCOM_TURN_GO_FIRST:
            # The adapter opens, and the toy answers when spoken to.
            self.pending = None
            self._play(rom)
            return
        self.pending = rom
        self._message = None
        runtime_globals.game_console.log(
            f"[WiFiComView] Turn-2 DigiROM waiting for BATTLE!: {rom}")
        self.battle_button.set_enabled(True)
        self.ui_manager.set_focused_component(self.battle_button)

    def _play(self, rom):
        """Answer *rom*; a whole battle goes to the battle scene."""
        played = wificom_service.play(rom)
        self.battle_button.set_enabled(False)
        if played.refused:
            self._show_message(f"Not answered: {played.refused}")
            return
        if not played.complete:
            answered = len(played.exchange.sent) if played.exchange else 0
            self._show_message(f"Answered {answered} packet(s)" if answered
                               else "The DigiROM could not be answered")
            return
        result, opponent = played.battle_result(), played.opponent()
        if result is None or opponent is None:
            self._show_message("Their packets did not check out")
            return
        self._start_battle(played, result, opponent)

    def _start_battle(self, played, result, opponent):
        """Hand the finished exchange to the battle scene, as DCom does."""
        runtime_globals.game_console.log(
            f"[WiFiComView] {played.battle_format} exchange complete: "
            f"winner {result.winner}, {len(result.battle_log)} turn(s)")
        try:
            from battle.dcom import pvp_payload
            simulator = played.exchange.simulator
            simulator.log_battle(result)
            pvp_payload.build(self.pet, opponent, result, played.battle_format,
                              simulator, minigame_result=self.charge,
                              opponent_name="WiFiCom", is_dcom_mode=True,
                              enemy_first=played.enemy_first)
            if played.battle_format == "IC":
                # The weapon sent in this battle is used up with it.
                from utils import battle_items
                battle_items.count_down(getattr(self.pet, "module", ""))
        except Exception as error:  # pylint: disable=broad-except
            import traceback
            runtime_globals.game_console.log(
                f"[WiFiComView] Could not build the battle: {error!r}\n{traceback.format_exc()}")
            self._show_message("Could not start the battle")
            return
        self.phase = "done"
        # The result is already queued; stopping publishes it on the way out,
        # and the battle need not wait for the network to see it go.
        wificom_service.stop(wait=False)
        from utils.scene_utils import change_scene
        change_scene("battle_pvp")

    # ------------------------------------------------------------------
    # Frame
    # ------------------------------------------------------------------

    def update(self):
        """Follow the minigame, then the service."""
        if self.abort:
            self.abort = False
            self.change_view("main_menu", initial_submenu="local_battle")
            return

        if self._settle_at:
            if time.monotonic() >= self._settle_at:
                self._settle_at = 0
                self._go_online()
            return

        if self.phase == "minigame" and self.minigame:
            self.minigame.update()
            if self.minigame.finished:
                self._finish_minigame()
            return

        if self.phase != "online":
            return

        if wificom_service.state == STATE_ONLINE:
            self._take_incoming()
        if self.phase != "online":
            return

        notice, wificom_service.notice = wificom_service.notice, None
        if notice:
            self._show_message(f"Not answered: {notice}")

        if self._message is not None and time.monotonic() >= self._message_until:
            self._message = None
        if self._message is not None:
            status = self._message
        elif self.pending is not None:
            status = "DigiROM received. Press BATTLE!"
        else:
            status = wificom_service.status_text
        if status != self._last_status:
            self._last_status = status
            self.status_label.set_text(status)

        waiting = self.pending is not None and wificom_service.state == STATE_ONLINE
        if self.battle_button.enabled != waiting:
            self.battle_button.set_enabled(waiting)

    def draw(self, surface):
        """The charge draws itself; everything else is UI components."""
        if self.phase == "minigame" and self.minigame:
            self.minigame.draw(surface)

    def handle_event(self, event):
        """Handle input events."""
        if not isinstance(event, tuple) or len(event) != 2:
            return False
        event_type, _ = event

        if self.phase == "minigame" and self.minigame:
            if event_type == "ESC":
                self._on_minigame_cancel()
                return True
            return self.minigame.handle_event(event)

        if self.phase == "online":
            if event_type == "START" and self.pending is not None:
                self._on_battle()
                return True
            if event_type == "B":
                self._on_back()
                return True
        return False

    def cleanup(self):
        """Cleanup when view is destroyed.

        The service is stopped here as well as in Back, because the view can
        also be left by an error or a scene change, and a live MQTT
        connection must not outlive the screen that owns it.
        """
        wificom_service.stop()

        components = [
            self.background, self.title_scene, self.status_label,
            self.pet_label, self.format_label,
            self.battle_button, self.back_button,
            self.protocol_menu, self.items_menu,
        ]
        for comp in components:
            if comp and comp in self.ui_manager.components:
                self.ui_manager.remove_component(comp)

        runtime_globals.game_console.log("[WiFiComView] Cleanup complete")


def _debug_mode():
    """Upcoming lines (TWIN) are offered in the grid only in debug mode."""
    from core import game_globals
    return bool(getattr(game_globals.configuration, "debug_mode", False))
