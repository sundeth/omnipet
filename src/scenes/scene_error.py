"""
Scene Error
Displays an error message with configurable action buttons.

Supports dual-button actions (A/B for different outcomes) and a
confirmation flow for destructive operations like switching game modes.
"""

import pygame

from ui.ui_manager import UIManager
from ui.components.background import Background
from ui.components.label import Label
from ui.windows.window_background import WindowBackground
from core import game_globals, runtime_globals
from utils.scene_utils import change_scene
from ui.ui_constants import BASE_RESOLUTION


class SceneError:
    """
    Error scene with configurable actions.

    Configuration (set via set_error before transitioning):

        Simple mode (backward-compatible):
            return_scene → A/START returns to that scene.

        Dual-action mode:
            action_a → (target, label) for the A button.
            action_b → (target, label) for the B button.
            Targets can be scene names ("boot", "setup") or special actions:
                "switch_free" — confirmation flow to switch to Free Mode.
    """

    # Class-level parameters set before scene transition
    error_message = "An error has occurred."
    bottom_message = None  # Custom bottom message (optional)
    return_scene = None    # Scene to return to (simple mode)
    action_a = None        # (target, label) for A button
    action_b = None        # (target, label) for B button

    @classmethod
    def set_error(cls, message: str, return_scene: str = None,
                  bottom_message: str = None,
                  action_a: tuple = None, action_b: tuple = None):
        """
        Set the error parameters before transitioning to this scene.

        Args:
            message: The error message to display.
            return_scene: The scene to return to on A press (simple mode).
            bottom_message: Custom bottom message. If None, auto-generates.
            action_a: (target, label) for A button, or None.
            action_b: (target, label) for B button, or None.
        """
        cls.error_message = message
        cls.return_scene = return_scene
        cls.bottom_message = bottom_message
        cls.action_a = action_a
        cls.action_b = action_b

    def __init__(self) -> None:
        """Initialize the error scene."""
        # Use RED theme for errors
        self.ui_manager = UIManager("RED")
        self.ui_manager.set_input_manager(runtime_globals.game_input)

        # Read class-level config
        self.message = SceneError.error_message
        self.return_scene = SceneError.return_scene
        self.custom_bottom_message = SceneError.bottom_message
        self.action_a = SceneError.action_a
        self.action_b = SceneError.action_b

        # State machine: "error" (main screen) or "confirm" (confirmation prompt)
        self.state = "error"
        self.confirm_message = ""
        self.confirm_bottom = ""
        self.pending_action = None  # Callable for confirmed action

        # Build display text
        self.bottom_text = self._build_bottom_message()

        # Background
        self.window_background = WindowBackground(True)

        # Build UI
        self._build_ui()

        runtime_globals.game_console.log(f"[SceneError] Initialized: {self.message}")

    # -----------------------------------------------------------------
    # Bottom message helpers
    # -----------------------------------------------------------------

    def _build_bottom_message(self) -> str:
        """Build the bottom instruction message from configuration."""
        if self.custom_bottom_message:
            return self.custom_bottom_message

        # Dual-action mode
        if self.action_a or self.action_b:
            parts = []
            if self.action_a:
                parts.append(f"A: {self.action_a[1]}")
            if self.action_b:
                parts.append(f"B: {self.action_b[1]}")
            return "  ".join(parts)

        # Simple return_scene mode
        if self.return_scene:
            scene_name = self.return_scene.replace("_", " ").title()
            return f"Press A to return to {scene_name}"

        return "Restart the game"

    # -----------------------------------------------------------------
    # UI construction
    # -----------------------------------------------------------------

    def _build_ui(self):
        """Build or rebuild all UI components for the current state."""
        # Recreate UIManager to clear old components
        self.ui_manager = UIManager("RED")
        self.ui_manager.set_input_manager(runtime_globals.game_input)

        ui_width = ui_height = BASE_RESOLUTION
        theme_colors = self.ui_manager.get_theme_colors()
        error_color = theme_colors.get("highlight", (255, 100, 100))
        text_color = theme_colors.get("text", (255, 255, 255))
        dim_color = (150, 150, 150)

        # Background
        self.background = Background(ui_width, ui_height)
        self.background.set_regions([(0, ui_height, "black")])
        self.ui_manager.add_component(self.background)

        # Title — "ERROR" or "CONFIRM" depending on state
        is_confirm = self.state == "confirm"
        title_text = "CONFIRM" if is_confirm else "ERROR"
        self.title_label = Label(
            x=ui_width // 2, y=20,
            text=title_text,
            is_title=True,
            color_override=error_color,
            center=True
        )
        self.ui_manager.add_component(self.title_label)

        # Message body (word-wrapped)
        display_msg = self.confirm_message if is_confirm else self.message
        self._create_message_labels(ui_width, text_color, display_msg)

        # Bottom instruction
        bottom = self.confirm_bottom if is_confirm else self.bottom_text
        self.bottom_label = Label(
            x=ui_width // 2, y=ui_height - 45,
            text=bottom,
            color_override=dim_color,
            center=True,
            word_wrap=True,
            max_width=ui_width - 10
        )
        self.ui_manager.add_component(self.bottom_label)

    def _create_message_labels(self, ui_width: int, text_color: tuple,
                                msg: str):
        """Create labels for the message body with word wrapping."""
        max_chars_per_line = 28
        words = msg.split()
        lines = []
        current_line = ""
        
        for word in words:
            test_line = f"{current_line} {word}".strip() if current_line else word
            if len(test_line) <= max_chars_per_line:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        
        if current_line:
            lines.append(current_line)
        
        # Create labels for each line
        line_height = 25
        start_y = 80  # Start below title
        
        self.message_labels = []
        for i, line in enumerate(lines):
            label = Label(
                x=ui_width // 2, y=start_y + i * line_height,
                text=line,
                color_override=text_color,
                center=True
            )
            self.ui_manager.add_component(label)
            self.message_labels.append(label)

    # -----------------------------------------------------------------
    # Update / Draw
    # -----------------------------------------------------------------

    def update(self) -> None:
        """Update the error scene."""
        self.ui_manager.update()

    def draw(self, surface: pygame.Surface) -> None:
        """Draw the error scene."""
        self.window_background.draw(surface)
        self.ui_manager.draw(surface)

    # -----------------------------------------------------------------
    # Input handling
    # -----------------------------------------------------------------

    def handle_event(self, event) -> bool:
        """Handle input events based on current state."""
        event_type, event_data = event

        if self.state == "confirm":
            return self._handle_confirm_event(event_type)
        return self._handle_error_event(event_type)

    def _handle_error_event(self, event_type: str) -> bool:
        """Handle input on the main error screen."""
        # Dual-action mode
        if self.action_a or self.action_b:
            if event_type in ("A", "START", "LCLICK") and self.action_a:
                self._execute_action(self.action_a[0])
                return True
            if event_type == "B" and self.action_b:
                self._execute_action(self.action_b[0])
                return True
            return False

        # Simple return_scene mode
        if self.return_scene:
            if event_type in ("A", "START", "LCLICK", "B"):
                change_scene(self.return_scene)
                return True

        return False

    def _handle_confirm_event(self, event_type: str) -> bool:
        """Handle input on the confirmation screen.

        A/START confirms the pending action, B cancels back to the error screen.
        """
        if event_type in ("A", "START", "LCLICK"):
            if self.pending_action:
                runtime_globals.game_console.log("[SceneError] Confirmation accepted")
                self.pending_action()
            return True

        if event_type == "B":
            runtime_globals.game_console.log("[SceneError] Confirmation cancelled")
            self.state = "error"
            self._build_ui()
            return True

        return False

    # -----------------------------------------------------------------
    # Action execution
    # -----------------------------------------------------------------

    def _execute_action(self, target: str) -> None:
        """Execute an action by target string.

        Args:
            target: A scene name string (routes there directly) or a
                    special action keyword like "switch_free".
        """
        if target == "switch_free":
            self._prompt_switch_to_free()
        else:
            change_scene(target)

    def _prompt_switch_to_free(self) -> None:
        """Show confirmation prompt for switching to Free Mode."""
        self.state = "confirm"
        self.confirm_message = (
            "Switch to Free Mode? "
            "Progress data will not be deleted."
        )
        self.confirm_bottom = "A: Confirm  B: Cancel"
        self.pending_action = self._do_switch_to_free
        self._build_ui()
        runtime_globals.game_console.log(
            "[SceneError] Prompting switch to Free Mode")

    def _do_switch_to_free(self) -> None:
        """Execute the switch to Free Mode and reboot."""
        game_globals.game_mode = game_globals.GAME_MODE_FREE
        game_globals.save_game_mode_preference()
        game_globals.player_id = None
        runtime_globals.game_console.log("[SceneError] Switched to Free Mode")
        # Load the Free Mode save, as the login scene's switch does: the boot
        # only routes, so the Progress Mode party stayed in memory (and would
        # have been saved into the Free folder).
        try:
            import os
            from utils import display_utils
            game_globals.skip_tutorial_on_mode_switch = False
            game_globals.migrate_legacy_saves()
            os.makedirs(game_globals.get_save_dir(), exist_ok=True)
            display_utils.load_preserving_display()
        except Exception as exc:
            runtime_globals.game_console.log(f"[SceneError] Free Mode save load failed: {exc}")
        # Reboot to route from the Default save folder
        change_scene("boot")
