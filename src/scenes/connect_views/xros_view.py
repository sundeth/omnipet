"""
XrosView - temporary evolution before a connection battle.

Sits between pet selection and the DCom exchange.  A DigiXros / Mode Change
form is a battle-only object (``XrosPet``), and the packets sent to the real
toy are built from the pet that is actually fighting -- so the choice has to
be made before the exchange, not inside the battle scene the way an adventure
battle does it.

Nothing happens here when the chosen pet has no form available: the view
hands straight on to the next one, so the flow is unchanged for every pet
that cannot transform.
"""
import pygame

from core import runtime_globals
from ui.ui_manager import UIManager
from ui.components.xros_animation import XrosAnimation
from ui.components.xros_selector import XrosSelector
from utils.xros_utils import get_available_temp_evolutions, make_xros_pet


class XrosView:
    """Temporary-evolution chooser for the connection battle flow."""

    def __init__(self, ui_manager: UIManager, change_view_callback,
                 selected_pets=None, next_view="dcom", next_view_kwargs=None,
                 discord_module=None):
        """
        Args:
            ui_manager: The UI manager instance
            change_view_callback: Callback to change to another view
            selected_pets: Pets chosen for the battle
            next_view: View to open once the choice is made
            next_view_kwargs: Extra arguments for that view
        """
        self.ui_manager = ui_manager
        self.change_view = change_view_callback
        self.selected_pets = list(selected_pets or [])
        self.next_view = next_view
        self.next_view_kwargs = dict(next_view_kwargs or {})

        self.selector = None
        self.animation = None
        self.done = False
        # Set when there is nothing to choose. The hand-off waits for the
        # first update(): changing views from inside a constructor leaves the
        # scene overwriting the new view with this one.
        self.skip = False

        candidates = []
        for pet in self.selected_pets:
            options = get_available_temp_evolutions(pet)
            if options:
                candidates.append((pet, options))

        if not candidates:
            runtime_globals.game_console.log(
                "[XrosView] No temporary evolution available; skipping")
            self.skip = True
            return

        runtime_globals.game_console.log(
            f"[XrosView] Selection opened for {len(candidates)} pet(s)")
        self.selector = XrosSelector(candidates, self.ui_manager)

    # ------------------------------------------------------------------

    def _continue(self):
        """Hand the (possibly evolved) pets to the next view."""
        if self.done:
            return
        self.done = True
        self.change_view(self.next_view, selected_pets=self.selected_pets,
                         **self.next_view_kwargs)

    def _on_confirm(self):
        """Apply the chosen forms and play the transformation animation."""
        selections = [(pet, evo) for pet, evo in self.selector.get_selections() if evo]
        self.selector = None

        if not selections:
            self._continue()
            return

        # Starts the moment the choice is made and runs over the animation's
        # opening background segment, which is exactly as long as this sound.
        runtime_globals.game_sound.play("xros_start")

        try:
            # Build the animation FIRST (it captures the pre-evolution
            # sprites), then create each pet's battle-only evolved form. The
            # party pets themselves are left exactly as they are.
            self.animation = XrosAnimation(selections)
            for pet, evo in selections:
                form = make_xros_pet(pet, evo)
                if form is None:
                    continue
                # The form is what fights, so it is what the packets and the
                # battle scene are built from.
                index = self.selected_pets.index(pet)
                self.selected_pets[index] = form
        except Exception as exc:
            runtime_globals.game_console.log(f"[XrosView] apply failed: {exc}")
            self.animation = None
            self._continue()

    # ------------------------------------------------------------------

    def update(self):
        if self.skip:
            self.skip = False
            self._continue()
            return
        if self.animation:
            self.animation.update()
            if self.animation.finished:
                self.animation = None
                self._continue()

    def draw(self, surface: pygame.Surface):
        if self.animation:
            self.animation.draw(surface)
        elif self.selector:
            surface.fill((0, 0, 0))
            self.selector.draw(surface)

    def handle_event(self, event):
        if not isinstance(event, tuple) or len(event) != 2:
            return False

        # Input is blocked while the transformation plays.
        if self.animation:
            return True

        if not self.selector:
            return False

        event_type, _ = event
        if event_type == "B":
            # Nothing has been applied yet, so backing out needs no revert.
            runtime_globals.game_sound.play("cancel")
            self.change_view("pet_selection", is_dcom_mode=True)
            return True

        if self.selector.handle_event(event) == "confirm":
            self._on_confirm()
        return True

    def cleanup(self):
        self.selector = None
        self.animation = None
