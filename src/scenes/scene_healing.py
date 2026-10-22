"""
Scene Healing - Heal sick pets (Dots or Skull disease)
Based on scene_sleep.py structure. Uses TEAL theme.
Only accessible when dots disease is possible for at least one module in the party.
"""
import pygame

from ui.ui_manager import UIManager
from ui.components.title_scene import TitleScene
from ui.components.button import Button
from ui.components.pet_selector import PetSelector
from ui.windows.window_background import WindowBackground
from core import runtime_globals, game_globals
from utils import ailments
from utils.pet_utils import distribute_pets_evenly, get_selected_pets
from utils.scene_utils import change_scene
from ui.ui_constants import BASE_RESOLUTION


class SceneHealing:
    def __init__(self) -> None:
        """Initialize the healing scene."""
        self.ui_manager = UIManager("TEAL")

        # UI Components
        self.title_scene = None
        self.pet_selector = None
        self.dots_button = None
        self.skull_button = None
        self.exit_button = None

        # Window background
        self.window_background = WindowBackground(False)

        self.setup_ui()

        # Focus on dots button by default
        self.ui_manager.set_focused_component(self.dots_button)

        runtime_globals.game_console.log("[SceneHealing] Healing scene initialized.")

    def setup_ui(self):
        """Setup the UI components."""
        ui_width = ui_height = BASE_RESOLUTION

        # Title
        self.title_scene = TitleScene(0, 9, "HEALING")
        self.ui_manager.add_component(self.title_scene)

        # Button layout (same as sleep scene)
        button_width = 87
        button_height = 30
        button_gap = 5
        buttons_y = 80

        total_buttons_width = (button_width * 2) + button_gap
        buttons_start_x = (ui_width - total_buttons_width) // 2

        dots_x = buttons_start_x
        skull_x = buttons_start_x + button_width + button_gap

        # Dots button
        self.dots_button = Button(
            dots_x, buttons_y, button_width, button_height,
            "Dots", self.on_dots_button, "Dots", "Healing"
        )
        self.ui_manager.add_component(self.dots_button)

        # Skull button
        self.skull_button = Button(
            skull_x, buttons_y, button_width, button_height,
            "Skull", self.on_skull_button, "Skull", "Healing"
        )
        self.ui_manager.add_component(self.skull_button)

        # Exit button
        exit_width = 90
        exit_height = 25
        exit_x = (ui_width - exit_width) // 2
        exit_y = buttons_y + button_height + 5

        self.exit_button = Button(
            exit_x, exit_y, exit_width, exit_height,
            "Exit", self.on_exit_button
        )
        self.ui_manager.add_component(self.exit_button)

        # Pet selector
        selector_y = exit_y + exit_height + 10
        selector_height = 60
        self.pet_selector = PetSelector(10, selector_y, ui_width - 20, selector_height)
        self.pet_selector.set_pets(get_selected_pets())
        self.pet_selector.set_interactive(False)
        self.update_pet_selector_state()
        self.ui_manager.add_component(self.pet_selector)

        runtime_globals.game_console.log("[SceneHealing] UI setup complete")

    def update_pet_selector_state(self):
        """Update pet selector to highlight pets matching the focused disease type."""
        if not self.pet_selector:
            return

        # Determine which disease type is focused
        focused = None
        if self.ui_manager.focused_index >= 0 and self.ui_manager.focusable_components:
            focused = self.ui_manager.focusable_components[self.ui_manager.focused_index]

        all_pets = get_selected_pets()
        enabled_indices = []

        # Skull: the injured; Dots (the default): the sick.
        kind = "injury" if focused == self.skull_button else "sick"
        for i, pet in enumerate(all_pets):
            if ailments.doses(pet, kind) > 0:
                enabled_indices.append(i)

        self.pet_selector.set_enabled_pets(enabled_indices)

    def update(self) -> None:
        """Update the scene."""
        self.window_background.update()
        self.ui_manager.update()

    def draw(self, surface: pygame.Surface) -> None:
        """Draw the scene."""
        self.window_background.draw(surface)
        self.ui_manager.draw(surface)

    def handle_event(self, event) -> None:
        """Handle events."""
        if not isinstance(event, tuple) or len(event) != 2:
            return

        event_type, event_data = event

        # Let UI manager handle first
        if self.ui_manager.handle_event(event):
            # After focus change, update pet selector highlighting
            self.update_pet_selector_state()
            return

        # Update pet selector on navigation (even if UI manager didn't consume)
        if event_type in ["LEFT", "RIGHT", "UP", "DOWN"]:
            self.update_pet_selector_state()

        if event_type == "B":
            runtime_globals.game_sound.play("cancel")
            change_scene("game")
            return

    def on_dots_button(self):
        """Heal the sick pets (Dots)."""
        self._heal_kind("sick")

    def on_skull_button(self):
        """Heal the injured pets (Skull)."""
        self._heal_kind("injury")

    def _heal_kind(self, kind):
        pets = [p for p in game_globals.pet_list if ailments.doses(p, kind) > 0]
        if not pets:
            runtime_globals.game_sound.play("cancel")
            return
        self._do_heal(pets, kind)

    def _do_heal(self, pets_to_heal, kind):
        """Heal the given list of pets by one dose of *kind*."""
        runtime_globals.game_sound.play("fail")
        distribute_pets_evenly()

        for pet in pets_to_heal:
            left = ailments.heal_dose(pet, kind)
            pet.set_state("angry")
            runtime_globals.game_console.log(f"[SceneHealing] {pet.name} healed. Doses left: {left}")

        change_scene("game")

    def on_exit_button(self):
        """Exit back to main game."""
        runtime_globals.game_sound.play("cancel")
        change_scene("game")
