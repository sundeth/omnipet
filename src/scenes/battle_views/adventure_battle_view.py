"""
AdventureBattleView - Adventure battle encounter
Handles the adventure battle including all phases, minigames, and result screen.
During the 'feeding' and 'retire_check' phases the view owns the menu component
and suppresses the external UI border.
"""
import pygame
from ui.ui_manager import UIManager
from ui.components.menu import Menu
from core import runtime_globals
from battle.battle_encounter import BattleEncounter

_MENU_PHASES = ("feeding", "retire_check")


class AdventureBattleView:
    """Adventure battle encounter view."""

    def __init__(self, ui_manager: UIManager, change_view_callback, module, area, round_num,
                 is_special_encounter=False, encounter_name=None):
        self.ui_manager = ui_manager
        self.change_view = change_view_callback
        self.module = module
        self.area = area
        self.round_num = round_num
        self.is_special_encounter = is_special_encounter
        self.encounter_name = encounter_name

        self.battle_encounter = None

        # Menu overlay state (owned by this view)
        self._menu: Menu = None
        self._tracked_phase: str = None

        self._start_battle()

    def _start_battle(self):
        """Start the adventure battle."""
        runtime_globals.game_console.log(
            f"[AdventureBattleView] Starting battle: {self.module.name} Area {self.area}, Round {self.round_num}"
        )
        self.battle_encounter = BattleEncounter(
            self.module.name,
            self.area,
            self.round_num,
            1,
            is_special_encounter=self.is_special_encounter,
            encounter_name=self.encounter_name,
        )
        # A battle wakes a sleeping pet in every mode, as training and versus
        # already did; check_disturbed_sleep does nothing to one awake.
        for pet in self.battle_encounter.pets_in_battle():
            pet.check_disturbed_sleep()
        runtime_globals.game_console.log("[AdventureBattleView] Battle encounter created")

    # ------------------------------------------------------------------
    # Menu helpers
    # ------------------------------------------------------------------

    def _open_menu(self, options, on_select):
        """Create and open a menu via the battle encounter's ui_manager."""
        enc_ui = self.battle_encounter.ui_manager
        self._menu = Menu(width=120, height=60)
        enc_ui.add_component(self._menu)
        self._menu.open(options, on_select=on_select)
        enc_ui.set_active_menu(self._menu)
        enc_ui.show_external_border = False

    def _close_menu(self):
        """Close and remove the active menu, restore border."""
        if self._menu:
            enc_ui = self.battle_encounter.ui_manager
            self._menu.close()
            enc_ui.remove_component(self._menu)
            if enc_ui.active_menu is self._menu:
                enc_ui.active_menu = None
            self._menu = None
        if self.battle_encounter:
            self.battle_encounter.ui_manager.show_external_border = True

    # ------------------------------------------------------------------
    # Feeding phase callbacks
    # ------------------------------------------------------------------

    def _enter_feeding(self):
        self._open_menu(["Next", "Food"], on_select=self._on_feeding_select)
        runtime_globals.game_console.log("[AdventureBattleView] Feeding menu opened")

    def _on_feeding_select(self, index):
        if index == 1:
            # Protein — feed and keep menu open for another round of feeding
            self.battle_encounter.feed_protein_to_team()
            enc_ui = self.battle_encounter.ui_manager
            self._menu.open(["Next", "Food"], on_select=self._on_feeding_select)
            enc_ui.set_active_menu(self._menu)
        else:
            # Next — proceed
            self._close_menu()
            self.battle_encounter.end_feeding_and_proceed()

    # ------------------------------------------------------------------
    # Retire-check phase callbacks
    # ------------------------------------------------------------------

    def _enter_retire_check(self):
        self._open_menu(["Retire", "Continue"], on_select=self._on_retire_select)
        runtime_globals.game_console.log("[AdventureBattleView] Retire-check menu opened")

    def _on_retire_select(self, index):
        self._close_menu()
        if index == 0:
            self.battle_encounter.do_retire()
        else:
            self.battle_encounter.do_continue_battle()

    # ------------------------------------------------------------------
    # Phase tracking
    # ------------------------------------------------------------------

    def _sync_phase(self):
        """Detect phase transitions and open/close menus accordingly."""
        if not self.battle_encounter:
            return
        phase = self.battle_encounter.phase
        if phase == self._tracked_phase:
            return

        prev = self._tracked_phase
        self._tracked_phase = phase

        # Leaving a menu phase — clean up if still open
        if prev in _MENU_PHASES and self._menu:
            self._close_menu()

        # Entering a menu phase — open the appropriate menu
        if phase == "feeding":
            self._enter_feeding()
        elif phase == "retire_check":
            self._enter_retire_check()

    # ------------------------------------------------------------------
    # View interface
    # ------------------------------------------------------------------

    def cleanup(self):
        self._close_menu()

    def update(self):
        if self.battle_encounter:
            self.battle_encounter.update()
            self._sync_phase()

    def draw(self, surface: pygame.Surface):
        if not self.battle_encounter:
            return
        self.battle_encounter.draw(surface)

        # Draw the menu overlay for menu phases
        if self.battle_encounter.phase in _MENU_PHASES and self._menu:
            menu_surface = self._menu.render()
            surface.blit(menu_surface, (self._menu.rect.x, self._menu.rect.y))

    def handle_event(self, event):
        if not isinstance(event, tuple) or len(event) != 2:
            return
        if not self.battle_encounter:
            return

        phase = self.battle_encounter.phase
        event_type = event[0]

        if phase == "feeding" and self._menu:
            if event_type == "B":
                self._on_feeding_select(0)  # B = Next
            else:
                self._menu.handle_event(event)
            return

        if phase == "retire_check" and self._menu:
            if event_type == "B":
                self._on_retire_select(0)  # B = Retire
            else:
                self._menu.handle_event(event)
            return

        self.battle_encounter.handle_event(event)
