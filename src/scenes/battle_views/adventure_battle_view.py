"""
AdventureBattleView - Adventure battle encounter
Handles the adventure battle including all phases, minigames, and result screen.
During the 'feeding', 'battle_items' and 'retire_check' phases the view owns the
menu component and suppresses the external UI border.

Battle items (utils.battle_items) are offered from a list before the battle
starts, when the player has any of the module's, and again before every
round where the module uses them every round (the Digivice iC's coliseum).
"""
import pygame
from ui.ui_manager import UIManager
from ui.components.menu import Menu
from ui.ui_constants import RED
from core import runtime_globals
from battle.battle_encounter import BattleEncounter
from utils import battle_items
from utils.pet_utils import get_battle_targets, get_battle_continue_targets
from utils.pygame_utils import get_font

_MENU_PHASES = ("feeding", "battle_items", "retire_check")


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
        # The item list shown before the battle exists (on the scene's
        # UI manager; between rounds it is the encounter's).
        self._pre_battle_menu: Menu = None

        if battle_items.offers_items_now(self.module, True, get_battle_targets()):
            self._open_pre_battle_items()
        else:
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

    def _open_menu(self, options, on_select, width=120, max_visible=None):
        """Create and open a menu via the battle encounter's ui_manager."""
        enc_ui = self.battle_encounter.ui_manager
        self._menu = Menu(width=width, height=60)
        enc_ui.add_component(self._menu)
        self._menu.open(options, on_select=on_select, max_visible=max_visible)
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
    # Battle items
    # ------------------------------------------------------------------

    def _item_rows(self, pets):
        return battle_items.battle_items(self.module, pets)

    def _use_item_row(self, rows, index, pets):
        """Use the list's *index*-th item (1-based: 0 is Fight)."""
        item, _quantity = rows[index - 1]
        notes = battle_items.use_battle_item(item, pets)
        runtime_globals.game_sound.play("happy2")
        for note in [f"{item.name} used!"] + list(notes or []):
            runtime_globals.game_message.add_slide(
                note, (255, 255, 0), 56 * runtime_globals.UI_SCALE, runtime_globals.FONT_SIZE_SMALL)

    def _open_pre_battle_items(self):
        """The list before the first battle: Fight, or an item first."""
        rows = self._item_rows(get_battle_targets())
        if not rows:
            self._close_pre_battle_items()
            return
        # A new Menu each time: a Menu closes itself after its on_select
        # returns, so one reopened from inside on_select would vanish.
        self._pre_battle_menu = Menu(width=170, height=60)
        self._pre_battle_menu.open(battle_items.menu_options(rows),
                                   on_select=self._on_pre_battle_select,
                                   on_cancel=self._close_pre_battle_items, max_visible=5)
        self.ui_manager.set_active_menu(self._pre_battle_menu)

    def _on_pre_battle_select(self, index):
        if index == 0:
            self._close_pre_battle_items()
            return
        pets = get_battle_targets()
        self._use_item_row(self._item_rows(pets), index, pets)
        self._open_pre_battle_items()

    def _close_pre_battle_items(self):
        """Fight: close the list and start the battle."""
        menu, self._pre_battle_menu = self._pre_battle_menu, None
        if menu is not None:
            menu.close()
            if self.ui_manager.active_menu is menu:
                self.ui_manager.active_menu = None
        if self.battle_encounter is None:
            self._start_battle()

    def _enter_battle_items(self):
        """The list before a later round (`battle_item_use` "round")."""
        rows = self._item_rows(get_battle_continue_targets())
        if not rows:
            self.battle_encounter.end_battle_items_and_proceed()
            return
        self._open_menu(battle_items.menu_options(rows), on_select=self._on_battle_items_select,
                        width=170, max_visible=5)

    def _on_battle_items_select(self, index):
        if index == 0:
            self._close_menu()
            self.battle_encounter.end_battle_items_and_proceed()
            return
        pets = get_battle_continue_targets()
        self._use_item_row(self._item_rows(pets), index, pets)
        rows = self._item_rows(pets)
        if not rows:
            self._close_menu()
            self.battle_encounter.end_battle_items_and_proceed()
            return
        self._close_menu()
        self._open_menu(battle_items.menu_options(rows), on_select=self._on_battle_items_select,
                        width=170, max_visible=5)

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
            # A new menu: this one closes itself once this callback returns.
            self._close_menu()
            self._open_menu(["Next", "Food"], on_select=self._on_feeding_select)
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
        elif phase == "battle_items":
            self._enter_battle_items()
        elif phase == "retire_check":
            self._enter_retire_check()

    # ------------------------------------------------------------------
    # View interface
    # ------------------------------------------------------------------

    def cleanup(self):
        self._close_menu()
        if self._pre_battle_menu is not None:
            self._pre_battle_menu.close()
            if self.ui_manager.active_menu is self._pre_battle_menu:
                self.ui_manager.active_menu = None
            self._pre_battle_menu = None

    def update(self):
        if self.battle_encounter:
            self.battle_encounter.update()
            self._sync_phase()

    def draw(self, surface: pygame.Surface):
        if not self.battle_encounter:
            self._draw_pre_battle(surface)
            return
        self.battle_encounter.draw(surface)

        # Draw the menu overlay for menu phases
        if self.battle_encounter.phase in _MENU_PHASES and self._menu:
            menu_surface = self._menu.render()
            surface.blit(menu_surface, (self._menu.rect.x, self._menu.rect.y))

    def _draw_pre_battle(self, surface):
        """Before the battle: the module's battle items to choose from."""
        menu = self._pre_battle_menu
        if menu is None or not menu.visible:
            return
        scale = runtime_globals.UI_SCALE
        font = get_font(runtime_globals.FONT_SIZE_MEDIUM)
        title = font.render("Battle items", True, RED)
        top = max(0, menu.rect.y - title.get_height() - int(6 * scale))
        surface.blit(title, ((surface.get_width() - title.get_width()) // 2, top))
        surface.blit(menu.render(), (menu.rect.x, menu.rect.y))

    def handle_event(self, event):
        if not isinstance(event, tuple) or len(event) != 2:
            return
        if not self.battle_encounter:
            # The pre-battle list is the scene's active menu, which the
            # scene's UI manager already gave this event; B fights.
            if event[0] == "B" and self._pre_battle_menu is not None:
                self._close_pre_battle_items()
            return

        phase = self.battle_encounter.phase
        event_type = event[0]

        if phase == "feeding" and self._menu:
            if event_type == "B":
                self._on_feeding_select(0)  # B = Next
            else:
                self._menu.handle_event(event)
            return

        if phase == "battle_items" and self._menu:
            if event_type == "B":
                self._on_battle_items_select(0)  # B = Fight
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
