"""
PasswordView - Password entry for the Specials menu
Redeems codes.json passwords (item / pet / unlock / encounter). Opened from
the Specials hub for one module (``module_name``), it takes only that
module's codes and is titled with the module's name for them (PEN20's
"Copymon").
"""
import pygame
from ui.ui_manager import UIManager
from ui.components.title_scene import TitleScene
from ui.components.button import Button
from ui.components.background import Background
from ui.components.label import Label
from ui.components.code_entry import CodeEntry
from ui.ui_constants import BASE_RESOLUTION
from core import runtime_globals
from utils import password_utils


class PasswordView:
    """Password entry view: code boxes plus Confirm / Back buttons."""

    def __init__(self, ui_manager: UIManager, change_view_callback, module_name=None):
        self.ui_manager = ui_manager
        self.change_view = change_view_callback
        self.module_name = module_name
        self.codes_title = "Password"
        if module_name:
            from utils.specials_utils import password_title
            module = (runtime_globals.game_modules or {}).get(module_name)
            if module is not None:
                self.codes_title = password_title(module)

        self.background = None
        self.title_scene = None
        self.prompt_label = None
        self.code_entry = None
        self.status_label = None
        self.confirm_button = None
        self.back_button = None

        self._setup_ui()

    def _setup_ui(self):
        ui_width = ui_height = BASE_RESOLUTION

        self.background = Background(ui_width, ui_height)
        self.background.set_regions([(0, ui_height, "black")])
        self.ui_manager.add_component(self.background)

        self.title_scene = TitleScene(0, 9, self.codes_title.upper() if self.module_name else "SPECIALS")
        self.ui_manager.add_component(self.title_scene)

        # The title bar names a module's own codes ("COPYMON").
        prompt = "Enter Password" if self.codes_title == "Password" else "Enter Code"
        self.prompt_label = Label(0, 40, prompt, is_title=True)
        self.ui_manager.add_component(self.prompt_label)

        # Size the entry to the longest code among the party's modules,
        # shrinking the boxes as needed to keep everything on screen.
        length = max(4, min(10, password_utils.max_code_length(module_name=self.module_name)))
        margin = 10
        spacing = 4
        char_w = min(40, (ui_width - 2 * margin - spacing * (length - 1)) // length)
        char_h = max(30, min(50, char_w + 10))
        total_w = char_w * length + spacing * (length - 1)
        self.code_entry = CodeEntry(
            (ui_width - total_w) // 2, 75, length=length,
            callback=lambda _code: self._on_confirm(),
            on_focus_callback=self._clear_status,
            char_w=char_w, char_h=char_h, spacing=spacing
        )
        self.ui_manager.add_component(self.code_entry)

        self.status_label = Label(0, 135, "", is_title=False)
        self.ui_manager.add_component(self.status_label)

        btn_y = 165
        btn_w = 80
        btn_h = 30
        gap = 20

        self.confirm_button = Button(
            (ui_width // 2) - btn_w - (gap // 2), btn_y, btn_w, btn_h,
            "Confirm", self._on_confirm
        )
        self.ui_manager.add_component(self.confirm_button)

        self.back_button = Button(
            (ui_width // 2) + (gap // 2), btn_y, btn_w, btn_h,
            "Back", self._on_back
        )
        self.ui_manager.add_component(self.back_button)

        self.ui_manager.set_focused_component(self.code_entry)
        runtime_globals.game_console.log("[PasswordView] UI setup complete")

    def _clear_status(self):
        if self.status_label:
            self.status_label.set_text("")

    def _on_confirm(self):
        entered = self.code_entry.get_text()
        module, password = password_utils.find_password(
            entered, entry_pad=self.code_entry.default_char, module_name=self.module_name)

        if password is None:
            # Wrong code
            runtime_globals.game_sound.play("fail")
            self.status_label.set_text("Invalid password")
            return

        if not password_utils.can_redeem(module, password):
            # Known code on cooldown / already used
            runtime_globals.game_sound.play("cancel")
            self.status_label.set_text("Cannot be redeemed")
            return

        if not password_utils.redeem(module, password):
            # Valid code but the reward could not be applied right now
            # (e.g. encounter with no battle-ready pet).
            runtime_globals.game_sound.play("cancel")
            self.status_label.set_text("Cannot be redeemed now")
            return
        # On success redeem() plays the happy sound and switches scenes.

    def _on_back(self):
        runtime_globals.game_sound.play("cancel")
        self.change_view("specials", module_name=self.module_name)

    def cleanup(self):
        for comp in (self.background, self.title_scene, self.prompt_label,
                     self.code_entry, self.status_label,
                     self.confirm_button, self.back_button):
            if comp and comp in self.ui_manager.components:
                self.ui_manager.remove_component(comp)

    def update(self):
        pass

    def draw(self, surface: pygame.Surface):
        # Virtual keyboard overlay for the code entry (mirrors SceneLogin)
        if not runtime_globals.IS_ANDROID and self.code_entry and self.code_entry.focused:
            self.code_entry.draw_keyboard_overlay(surface)

    def handle_raw_event(self, event):
        """Physical-keyboard input forwarded by SceneBattle."""
        if self.code_entry and self.code_entry.focused:
            return self.code_entry.handle_event(event)
        return False

    def handle_event(self, event):
        if not isinstance(event, tuple) or len(event) != 2:
            return

        event_type, event_data = event

        # Virtual-keyboard overlay clicks (drawn over the bottom of the view)
        if event_type == "LCLICK" and event_data and "pos" in event_data:
            if not runtime_globals.IS_ANDROID and self.code_entry and self.code_entry.focused:
                screen_sz = self.ui_manager.get_scaled_resolution()
                if self.code_entry.handle_keyboard_click(event_data["pos"], screen_sz):
                    return True

        if event_type == "B":
            self._on_back()
            return True
        if event_type == "START":
            self._on_confirm()
            return True
