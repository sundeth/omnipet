"""
ArenaTeamCreationView - Pick the pets of an arena team and register it.

Mirrors the look of the battle scene's VersusView / JogressView pet
pickers: a PetSelector at the bottom (focusable, scrollable), one slot box
per team place at the top showing the selected pets, and Back / Confirm
buttons.

The season decides the team size (``min_team_size`` / ``max_team_size`` in
its config: 1-3, or exactly one size). Pets are disabled in the selector
when the server cannot field them this season (their module is not
published there), when they break the season's restrictions, or when they
already fought a season in their current form (they may come back once they
evolve). The server rebuilds every Digimon from its own module data and
re-checks all of this; the client check only saves a rejected round trip.

Confirming asks twice: the second press registers the team, and the
chosen pets go to the freezer, locked until the season ends
(``game_globals.lock_pets_for_arena``).
"""
import threading
from datetime import datetime

import pygame

from ui.ui_manager import UIManager
from ui.components.title_scene import TitleScene
from ui.components.button import Button
from ui.components.background import Background
from ui.components.label import Label
from ui.components.pet_selector import PetSelector
from ui.components.team_display import TeamDisplay
from ui.ui_constants import BASE_RESOLUTION
from core import runtime_globals, game_globals
from utils import ailments
from services.omninet_service import omninet_service
from battle.arena.engine import ArenaError, TEAM_SIZE, normalize_attribute
from utils import arena_pets


# The largest arena team (the battle has three lanes); the season's config
# narrows it. A server that sends no size rule takes exactly three.
MAX_TEAM_SIZE = TEAM_SIZE
REQUIRED_TEAM_SIZE = TEAM_SIZE

_MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
           "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def team_size_range(season: dict | None) -> tuple:
    """(min, max) Digimon per team for *season*."""
    config = (season or {}).get('config') or {}
    if 'min_team_size' not in config and 'max_team_size' not in config:
        return REQUIRED_TEAM_SIZE, REQUIRED_TEAM_SIZE
    low = int(config.get('min_team_size') or 1)
    high = int(config.get('max_team_size') or MAX_TEAM_SIZE)
    low = max(1, min(MAX_TEAM_SIZE, low))
    high = max(low, min(MAX_TEAM_SIZE, high))
    return low, high


def size_text(low: int, high: int) -> str:
    return f"{low}" if low == high else f"{low}-{high}"


def _attribute_set(values) -> set:
    allowed = set()
    for value in values or []:
        try:
            allowed.add(normalize_attribute(value))
        except ArenaError:
            pass
    return allowed


def _pet_passes(pet, restrictions: dict, server_modules=None,
                season_id=None) -> tuple[bool, str]:
    """Return ``(ok, reason)`` for whether *pet* may join an arena team.

    Covers:
        * Universal arena eligibility -- a living pet that can attack and
          has power, and has not been edited.
        * The server's module list: a module the server cannot field
          (not published there) cannot battle this season
          (*server_modules* None = not loaded).
        * One season per form: a pet that already fought a season in its
          current form must evolve first (*season_id* is the running one).
        * Season restrictions (``allowed_stages`` / ``allowed_attributes``
          / ``allowed_modules``), as the server engine reads them.

    Returns ``True, ""`` if the pet is eligible, or ``False, reason``
    with a short human-readable reason ready for the status label.
    """
    if getattr(pet, 'edited', False):
        return False, "Edited pets aren't allowed"
    if getattr(pet, 'state', None) == "dead":
        return False, "Pet is dead"
    if int(getattr(pet, 'power', 0) or 0) <= 0 or int(getattr(pet, 'atk_main', 0) or 0) <= 0:
        return False, "Pet cannot battle"
    if server_modules is not None and getattr(pet, 'module', None) not in server_modules:
        return False, "Module not in this arena season"
    fought = arena_pets.fought_form(pet, season_id)
    if fought:
        return False, "Fought last season: evolve it first"

    restrictions = restrictions or {}
    stages = restrictions.get('allowed_stages')
    if stages and getattr(pet, 'stage', None) not in stages:
        return False, "Wrong stage for this season"
    attributes = restrictions.get('allowed_attributes')
    if attributes:
        try:
            attribute = normalize_attribute(getattr(pet, 'attribute', ''))
        except ArenaError:
            attribute = None
        if attribute not in _attribute_set(attributes):
            return False, "Wrong attribute for this season"
    modules = restrictions.get('allowed_modules')
    if modules and getattr(pet, 'module', None) not in modules:
        return False, "Wrong module for this season"
    return True, ""


def _version(pet) -> int:
    """The pet's species version as monster.json writes it (0 included)."""
    try:
        return int(getattr(pet, 'version', 1))
    except (TypeError, ValueError):
        return 1


def _pet_to_upload(pet) -> dict:
    """What the /teams endpoint takes for one pet: who it is and its care.

    The battle uses the species stats (stage, attribute, power, HP,
    attacks) from the server's own module copy; the game's own values ride
    in ``base`` only so the server can refuse a pet whose data was edited.
    ``uid`` follows the Digimon across seasons and ``pet_json`` is its full
    save copy, which the server keeps with the team.
    """
    try:
        from utils.module_utils import get_module
        module_version = str(get_module(pet.module).version)
    except Exception:
        module_version = None
    return {
        'name': pet.name,
        'module_name': pet.module,
        'module_version': module_version,
        # Version 0 is a real version (PENC's Agumon): never `or 1`.
        'pet_version': _version(pet),
        'uid': arena_pets.pet_uid(pet),
        'base': arena_pets.pet_base(pet),
        'pet_json': arena_pets.pet_snapshot(pet),
        'status': {
            'level': int(getattr(pet, 'level', 1) or 1),
            'strength': int(getattr(pet, 'strength', 0) or 0),
            'hunger': int(getattr(pet, 'hunger', 0) or 0),
            'weight': int(getattr(pet, 'weight', 0) or 0),
            'effort': int(getattr(pet, 'effort', 0) or 0),
            'traited': bool(getattr(pet, 'traited', False)),
            'shook': bool(getattr(pet, 'shook', False)),
            'vital_values': int(getattr(pet, 'vital_values', 0) or 0),
            'sick': ailments.ailing(pet),
            'state': getattr(pet, 'state', ''),
            'edited': bool(getattr(pet, 'edited', False)),
        },
    }


def _parse_server_time(value) -> float | None:
    """A server ISO datetime as unix time, or None."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    except (TypeError, ValueError):
        return None


def format_local_moment(unix_time) -> str:
    """``OCT 20 14:00`` in local time, for lock and season messages."""
    if not unix_time:
        return "?"
    moment = datetime.fromtimestamp(unix_time)
    return f"{_MONTHS[moment.month - 1]} {moment.day:02d} {moment.hour:02d}:{moment.minute:02d}"


class ArenaTeamCreationView:
    """Choose the season's number of pets, validate, send to /teams."""

    def __init__(self, ui_manager: UIManager, change_view_callback,
                 discord_module=None, season: dict | None = None):
        self.ui_manager = ui_manager
        self.change_view = change_view_callback
        self._season = season or {}
        self._restrictions = (self._season or {}).get('restrictions') or {}
        self._min_size, self._max_size = team_size_range(self._season)

        self._components = []
        self._selected_pet_indices = []  # ordered list of indices into pet_list
        self._submitting = False
        # The first CONFIRM only warns about the freezer lock; the second
        # registers the team.
        self._armed = False
        # Module names the server can battle with this season; None until
        # the list arrives, and Confirm stays off until it does.
        self._server_modules = None

        self._setup_ui()
        self._load_server_modules()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _add(self, comp):
        self.ui_manager.add_component(comp)
        self._components.append(comp)
        return comp

    def _setup_ui(self):
        """Layout mirrors scene_battle's VersusView: team display at top,
        BACK / CONFIRM beneath it, PetSelector along the bottom of the
        screen.  The display shows one hexagonal slot per team place.
        """
        ui_width = ui_height = BASE_RESOLUTION
        cut = {'tl': True, 'tr': False, 'bl': False, 'br': True}

        # Black fill backdrop
        bg = Background(ui_width, ui_height)
        bg.set_regions([(0, ui_height, "black")])
        self._add(bg)
        self._add(TitleScene(0, 9, "TEAM"))

        # Team display — same position/size as VersusView's VersusDisplay
        display_width = 200
        display_height = 80
        display_x = (ui_width - display_width) // 2
        display_y = 40
        self.team_display = self._add(TeamDisplay(
            display_x, display_y, display_width, display_height))
        self.team_display.set_slot_count(self._max_size)

        # Buttons — directly under the display, centered, sizes match versus
        back_button_width = 60
        confirm_button_width = 80
        button_height = 25
        button_spacing = 5
        total_button_width = (
            back_button_width + confirm_button_width + button_spacing
        )
        buttons_start_x = (ui_width - total_button_width) // 2
        buttons_y = display_y + display_height + 10

        self.back_button = self._add(Button(
            buttons_start_x, buttons_y, back_button_width, button_height,
            "BACK", self._on_back, cut_corners=cut))
        confirm_x = buttons_start_x + back_button_width + button_spacing
        self.confirm_button = self._add(Button(
            confirm_x, buttons_y, confirm_button_width, button_height,
            "CONFIRM", self._on_confirm, cut_corners=cut, enabled=False))

        # Status / info line just under the buttons
        self.status_label = self._add(Label(
            ui_width // 2, buttons_y + button_height + 6,
            self._rules_summary(),
            color_override=(180, 180, 180), center=True,
            word_wrap=True, max_width=ui_width - 20))

        # Pet selector — same position math as VersusView
        selector_y = buttons_y + button_height + 18
        selector_height = ui_height - selector_y - 6
        self.pet_selector = self._add(PetSelector(
            10, selector_y, ui_width - 20, selector_height))
        self.pet_selector.set_pets(list(getattr(game_globals, 'pet_list', [])))
        self.pet_selector.set_interactive(True)
        self.pet_selector.activation_callback = self._on_pet_activate
        self.pet_selector.disabled_callback = self._on_disabled_pet

        self._reject_reasons = {}
        self._apply_eligibility()
        self.ui_manager.set_focused_component(self.pet_selector)

    def _team_ready(self) -> bool:
        return (self._server_modules is not None
                and self._min_size <= len(self._selected_pet_indices) <= self._max_size)

    def _apply_eligibility(self):
        """Disable pets that fail eligibility (universal arena gates, the
        server's module list, one season per form, season filters). Reasons
        are stashed per index so the status label can explain why a tap
        was rejected."""
        self._reject_reasons = {}
        eligible = []
        season_id = self._season.get('id')
        for i, pet in enumerate(self.pet_selector.pets):
            ok, reason = _pet_passes(pet, self._restrictions, self._server_modules, season_id)
            if ok:
                eligible.append(i)
            else:
                self._reject_reasons[i] = reason
        self.pet_selector.enabled_pets = eligible
        self._selected_pet_indices = [i for i in self._selected_pet_indices if i in eligible]
        self.pet_selector.selected_pets = list(self._selected_pet_indices)
        self.pet_selector.needs_redraw = True
        if eligible and self.pet_selector.focused_cell not in eligible:
            self.pet_selector.focused_cell = eligible[0]
        self._refresh_team_display()
        self._disarm()
        self.confirm_button.set_enabled(self._team_ready())

    def _load_server_modules(self):
        self.status_label.set_text("Checking arena modules...")

        def _worker():
            ok, data = omninet_service.get_arena_modules()
            if ok and isinstance(data, dict):
                self._server_modules = {m.get('name') for m in data.get('modules') or []}
                self._apply_eligibility()
                if self.pet_selector.enabled_pets:
                    self.status_label.set_text(self._rules_summary())
                else:
                    self.status_label.set_text("None of your pets can join this season")
            else:
                msg = data if isinstance(data, str) else "Arena modules unavailable"
                self.status_label.set_text(str(msg)[:48])

        threading.Thread(target=_worker, daemon=True).start()

    def _rules_summary(self) -> str:
        count = f"Pick {size_text(self._min_size, self._max_size)} pets."
        if not self._restrictions:
            return count
        parts = []
        if self._restrictions.get('allowed_stages'):
            parts.append("stage")
        if self._restrictions.get('allowed_attributes'):
            parts.append("attr")
        if self._restrictions.get('allowed_modules'):
            parts.append("module")
        return "Season filter: " + " / ".join(parts) + f". {count}"

    def _disarm(self):
        if self._armed:
            self._armed = False
            self.confirm_button.set_text("CONFIRM")

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def _on_pet_activate(self):
        pet_index = self.pet_selector.get_activation_cell()
        if pet_index < 0 or pet_index >= len(self.pet_selector.pets):
            return False
        if pet_index not in self.pet_selector.enabled_pets:
            reason = self._reject_reasons.get(pet_index, "Pet not eligible")
            self.status_label.set_text(reason)
            runtime_globals.game_sound.play("cancel")
            return False
        self._toggle_pet(pet_index)
        return True

    def _on_disabled_pet(self, pet_index: int):
        """A pet that cannot join: say why."""
        self.status_label.set_text(self._reject_reasons.get(pet_index, "Pet not eligible"))
        runtime_globals.game_sound.play("cancel")

    def _toggle_pet(self, pet_index: int):
        if pet_index in self._selected_pet_indices:
            self._selected_pet_indices.remove(pet_index)
            runtime_globals.game_sound.play("cancel")
        else:
            if len(self._selected_pet_indices) >= self._max_size:
                self.status_label.set_text(f"Team is full (max {self._max_size})")
                runtime_globals.game_sound.play("cancel")
                return
            self._selected_pet_indices.append(pet_index)
            runtime_globals.game_sound.play("menu")
        self._refresh_team_display()
        # Mirror selection back onto the PetSelector so its visual highlight
        # reflects the team membership.
        self.pet_selector.selected_pets = list(self._selected_pet_indices)
        self.pet_selector.needs_redraw = True
        self._disarm()
        self.confirm_button.set_enabled(self._team_ready())
        self.status_label.set_text(self._rules_summary())

    def _refresh_team_display(self):
        """Push the current selection onto the hexagonal team display."""
        if not self.team_display:
            return
        pets = [self.pet_selector.pets[i] for i in self._selected_pet_indices]
        self.team_display.set_pets(pets)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _lock_until(self):
        return _parse_server_time(self._season.get('ends_at'))

    def _on_confirm(self):
        if self._submitting:
            return
        count = len(self._selected_pet_indices)
        if not self._min_size <= count <= self._max_size:
            runtime_globals.game_sound.play("cancel")
            self.status_label.set_text(
                f"Pick {size_text(self._min_size, self._max_size)} pets to continue.")
            return
        if not self._armed:
            # First press: say what registering does before doing it.
            runtime_globals.game_sound.play("menu")
            self._armed = True
            self.confirm_button.set_text("SURE?")
            until = self._lock_until()
            when = format_local_moment(until) if until else "the season ends"
            self.status_label.set_text(
                f"Locks {'it' if count == 1 else 'them'} in the freezer until {when}. "
                "Press again.")
            return

        runtime_globals.game_sound.play("menu")
        self._submitting = True
        self.confirm_button.set_enabled(False)
        self.back_button.set_enabled(False)
        self.status_label.set_text("Registering team...")

        chosen = [self.pet_selector.pets[i] for i in self._selected_pet_indices]
        pets = [_pet_to_upload(pet) for pet in chosen]

        def _worker():
            try:
                ok, data = omninet_service.create_team(pets, team_name=None)
            except Exception as exc:
                ok, data = False, str(exc)
            if ok:
                # The pets stay in the save: they go to the freezer, locked
                # until the season the server reported ends.
                team = data if isinstance(data, dict) else {}
                until = _parse_server_time(team.get('season_ends_at'))
                lock = {
                    'until': until or 0,
                    'team_id': str(team.get('id') or ''),
                    'season_id': str(team.get('season_id') or ''),
                    'season_name': team.get('season_name') or '',
                }
                try:
                    arena_pets.mark_team(chosen, team)
                    stored = until is not None and game_globals.lock_pets_for_arena(chosen, lock)
                except Exception as exc:
                    runtime_globals.game_console.log(
                        f"[ArenaTeamCreation] freezer lock failed: {exc}")
                    stored = False
                if not stored:
                    runtime_globals.game_console.log(
                        "[ArenaTeamCreation] team created but pets stayed in the party")
                runtime_globals.arena_notice = (
                    f"Team registered! Locked until {format_local_moment(until)}."
                    if stored else "Team registered.")
                self.change_view("arena")
            else:
                msg = data if isinstance(data, str) else "Failed to create team"
                runtime_globals.game_sound.play("cancel")
                self.status_label.set_text(str(msg)[:80])
                self._submitting = False
                self._disarm()
                self.confirm_button.set_enabled(self._team_ready())
                self.back_button.set_enabled(True)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_back(self):
        runtime_globals.game_sound.play("cancel")
        self.change_view("arena")

    # ------------------------------------------------------------------
    # Scene interface
    # ------------------------------------------------------------------

    def update(self):
        pass

    def draw(self, surface: pygame.Surface):
        pass

    def handle_event(self, event):
        if not isinstance(event, tuple) or len(event) != 2:
            return
        event_type, _ = event
        if event_type == "B":
            self._on_back()
            return True

    def cleanup(self):
        for comp in self._components:
            if comp and comp in self.ui_manager.components:
                self.ui_manager.remove_component(comp)
        self._components.clear()
        runtime_globals.game_console.log("[ArenaTeamCreationView] Cleanup complete")
