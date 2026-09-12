"""
WiFiComWarningView - the risk notice shown before joining wificom.dev.

Omnipet presents itself to the service as if it were a real device, which not
every project or community is happy about. The player is told so once, before
anything connects, and has to say yes.
"""
from ui.ui_manager import UIManager
from ui.components.button import Button
from ui.components.background import Background
from ui.components.label import Label
from ui.ui_constants import BASE_RESOLUTION, YELLOW_BRIGHT
from core import runtime_globals


#: What the player is agreeing to. Kept as one block so it wraps to whatever
#: width the screen gives it rather than carrying hand-placed line breaks.
WARNING_TEXT = (
    "Omnipet joins wificom.dev as if it were a real device. Some projects "
    "and communities do not allow simulated pets, and connecting anyway may "
    "be treated as cheating. Check that Omnipet is welcome before you "
    "connect. Do you understand the risks and want to continue?"
)


class WiFiComWarningView:
    """Risk notice with YES / NO."""

    def __init__(self, ui_manager: UIManager, change_view_callback,
                 discord_module=None):
        """Initialize the warning view.

        Args:
            ui_manager: The UI manager instance
            change_view_callback: Callback to change to another view
        """
        self.ui_manager = ui_manager
        self.change_view = change_view_callback

        # UI Components
        self.background = None
        self.warning_label = None
        self.body_label = None
        self.yes_button = None
        self.no_button = None

        self._setup_ui()

    def _setup_ui(self):
        """Setup the UI components."""
        ui_width = ui_height = BASE_RESOLUTION

        self.background = Background(ui_width, ui_height)
        self.background.set_regions([(0, ui_height, "black")])
        self.ui_manager.add_component(self.background)

        # The heading is the warning itself, so it stands in for the usual
        # scene title rather than sitting under one.
        self.warning_label = Label(
            ui_width // 2, 16, "WARNING!", is_title=True,
            color_override=YELLOW_BRIGHT, center=True
        )
        self.ui_manager.add_component(self.warning_label)

        # `center_lines` centres each wrapped line; `center` on its own only
        # centres the block, which is always the full wrap width.
        body_margin = 14
        self.body_label = Label(
            ui_width // 2, 52, WARNING_TEXT, center=True,
            word_wrap=True, max_width=ui_width - (2 * body_margin),
            center_lines=True
        )
        self.ui_manager.add_component(self.body_label)

        # Buttons
        btn_width = 70
        btn_height = 26
        btn_gap = 20
        btn_y = ui_height - btn_height - 18
        yes_x = (ui_width // 2) - btn_width - (btn_gap // 2)
        no_x = (ui_width // 2) + (btn_gap // 2)

        self.yes_button = Button(
            yes_x, btn_y, btn_width, btn_height,
            "YES", self._on_yes,
            cut_corners={'tl': False, 'tr': True, 'bl': False, 'br': True}
        )
        self.ui_manager.add_component(self.yes_button)

        self.no_button = Button(
            no_x, btn_y, btn_width, btn_height,
            "NO", self._on_no,
            cut_corners={'tl': True, 'tr': False, 'bl': True, 'br': False}
        )
        self.ui_manager.add_component(self.no_button)

        # Open on NO: agreeing to this should be a deliberate press.
        self.ui_manager.set_focused_component(self.no_button)

        runtime_globals.game_console.log("[WiFiComWarningView] UI setup complete")

    def _on_yes(self):
        """Accepted: go on to pick the pet that will fight."""
        runtime_globals.game_sound.play("menu")
        self.change_view("pet_selection", is_wificom_mode=True)

    def _on_no(self):
        """Declined: back to the local battle menu."""
        runtime_globals.game_sound.play("cancel")
        self.change_view("main_menu", initial_submenu="local_battle")

    def update(self):
        """Update the view."""
        pass

    def draw(self, surface):
        """Draw additional elements."""
        pass

    def handle_event(self, event):
        """Handle input events."""
        if not isinstance(event, tuple) or len(event) != 2:
            return

        event_type, _ = event

        if event_type == "B":
            self._on_no()
            return True

    def cleanup(self):
        """Cleanup when view is destroyed."""
        components = [
            self.background, self.warning_label, self.body_label,
            self.yes_button, self.no_button,
        ]

        for comp in components:
            if comp and comp in self.ui_manager.components:
                self.ui_manager.remove_component(comp)

        runtime_globals.game_console.log("[WiFiComWarningView] Cleanup complete")
