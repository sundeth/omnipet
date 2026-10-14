"""
ArenaHistoryView - Battle history for a team.

Shows a scrollable list of the team's battles -- attacks it made and
defences it fought -- with outcome (win, loss or draw) and score change.
WATCH fetches the selected battle and replays it in the battle scene, which
returns here afterwards.
"""
import threading
from datetime import datetime

from ui.ui_manager import UIManager
from ui.components.title_scene import TitleScene
from ui.components.button import Button
from ui.components.background import Background
from ui.components.label import Label
from ui.ui_constants import BASE_RESOLUTION
from core import runtime_globals


class ArenaHistoryView:
    """Battle history list + Watch / Back actions."""

    ROW_HEIGHT = 18
    MAX_VISIBLE_ROWS = 6

    def __init__(self, ui_manager: UIManager, change_view_callback,
                 discord_module=None, team_id: str | None = None,
                 team_name: str | None = None):
        self.ui_manager = ui_manager
        self.change_view = change_view_callback
        self._team_id = team_id
        self._team_name = team_name
        self._components = []

        # Battle list + selection state
        self._battles = []
        self._selected_index = 0
        self._row_labels = []
        self._loading = False
        self._load_error = None

        self._build_ui()
        if team_id:
            self._fetch_async()

    # ------------------------------------------------------------------

    def _add(self, comp):
        self.ui_manager.add_component(comp)
        self._components.append(comp)
        return comp

    def _build_ui(self):
        w = h = BASE_RESOLUTION

        bg = Background(w, h)
        bg.set_regions([(0, h, "black")])
        self._add(bg)
        self._add(TitleScene(0, 9, "HISTORY"))

        header = self._team_name or "Battles"
        self._add(Label(
            w // 2, 32, header, is_title=True,
            color_override=(255, 255, 255), center=True,
            word_wrap=True, max_width=w - 20))

        # Status / empty-state label
        self.status_label = self._add(Label(
            w // 2, 70, "Loading battles...",
            color_override=(180, 180, 180), center=True,
            word_wrap=True, max_width=w - 20))

        # Reserve space for up to MAX_VISIBLE_ROWS rows; rendered when data
        # arrives.  Rows are plain labels because we drive selection at the
        # view level rather than relying on the UI manager's focus system.
        list_top = 55
        for i in range(self.MAX_VISIBLE_ROWS):
            lbl = self._add(Label(
                10, list_top + i * self.ROW_HEIGHT, "",
                color_override=(220, 220, 220)))
            lbl.visible = False
            self._row_labels.append(lbl)

        # Selection arrow / pointer label (we just prefix the selected row
        # with ">" rather than adding a separate cursor).

        # Footer buttons
        btn_w, btn_h = 80, 24
        gap = 12
        total_w = 2 * btn_w + gap
        x0 = (w - total_w) // 2
        y0 = h - btn_h - 10
        self.watch_button = self._add(Button(
            x0, y0, btn_w, btn_h, "WATCH", self._on_watch))
        self.back_button = self._add(Button(
            x0 + btn_w + gap, y0, btn_w, btn_h, "BACK", self._on_back))
        self.watch_button.enabled = False

    # ------------------------------------------------------------------
    # Data fetch
    # ------------------------------------------------------------------

    def _fetch_async(self):
        from services.omninet_service import omninet_service

        self._loading = True
        self._load_error = None
        self.status_label.set_text("Loading battles...")

        def _worker():
            ok, data = omninet_service.get_team_battles(self._team_id)
            if ok and isinstance(data, dict):
                self._battles = data.get('battles', []) or []
            elif ok and isinstance(data, list):
                self._battles = data
            else:
                self._battles = []
                # kept so the empty list is not read as "no battles"
                self._load_error = data if isinstance(data, str) else "Failed to load history"
            self._loading = False
            self._render_rows()

        threading.Thread(target=_worker, daemon=True).start()

    def _render_rows(self):
        """Refresh the row labels from current battle list + selection."""
        if not self._battles:
            if self._loading:
                status = "Loading battles..."
            else:
                status = self._load_error or "No battles yet"
            self.status_label.set_text(status)
            for lbl in self._row_labels:
                lbl.visible = False
                lbl.set_text("")
            self.watch_button.enabled = False
            return

        self.status_label.set_text("")
        # Window the list around the selected index so it stays visible.
        max_rows = self.MAX_VISIBLE_ROWS
        total = len(self._battles)
        # Simple windowing: scroll so selected_index is within the window
        first = max(0, min(self._selected_index - max_rows // 2,
                           total - max_rows))
        first = max(0, first)
        for i, lbl in enumerate(self._row_labels):
            idx = first + i
            if idx >= total:
                lbl.visible = False
                lbl.set_text("")
                continue
            battle = self._battles[idx]
            line = self._format_battle_line(battle)
            prefix = ">" if idx == self._selected_index else " "
            lbl.set_text(f"{prefix} {line}")
            lbl.color_override = (
                (255, 255, 120) if idx == self._selected_index else (220, 220, 220)
            )
            lbl.visible = True
        self.watch_button.enabled = True

    def _format_battle_line(self, battle: dict) -> str:
        opponent = battle.get('opponent_nickname', '?')
        delta = battle.get('score_change', 0)
        if battle.get('is_draw'):
            outcome = "D"
        else:
            outcome = "W" if battle.get('won', False) else "L"
        # A = this team attacked, D = it was attacked while away.
        role = "A" if battle.get('role', 'attack') == 'attack' else "D"
        outcome = f"{role}:{outcome}"
        sign = "+" if delta >= 0 else ""
        date_str = battle.get('fought_at', '')
        # Truncate ISO datetime to YYYY-MM-DD
        if date_str and 'T' in date_str:
            date_str = date_str.split('T')[0]
        # Keep total width modest for the 240px display
        opponent = opponent if len(opponent) <= 12 else opponent[:11] + "."
        return f"{outcome} {sign}{delta}  {opponent}  {date_str}"

    # ------------------------------------------------------------------
    # Selection navigation
    # ------------------------------------------------------------------

    def _move_selection(self, delta: int):
        if not self._battles:
            return
        new = max(0, min(self._selected_index + delta, len(self._battles) - 1))
        if new != self._selected_index:
            self._selected_index = new
            runtime_globals.game_sound.play("menu")
            self._render_rows()

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _on_watch(self):
        if not self._battles or self._loading:
            return
        runtime_globals.game_sound.play("menu")
        battle = self._battles[self._selected_index]
        battle_id = battle.get('id')
        if not battle_id:
            self.status_label.set_text("Battle ID missing")
            return

        from services.omninet_service import omninet_service
        self.status_label.set_text("Loading battle...")

        def _worker():
            ok, data = omninet_service.get_battle(battle_id)
            if ok and isinstance(data, dict):
                from utils.arena_replay import start_replay
                problem = start_replay(
                    data, self._team_id, return_view="arena_history",
                    return_kwargs={"team_id": self._team_id,
                                   "team_name": self._team_name})
                if problem:
                    self.status_label.set_text(problem)
            else:
                err = data if isinstance(data, str) else "Failed to load battle"
                self.status_label.set_text(err)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_back(self):
        runtime_globals.game_sound.play("cancel")
        self.change_view("arena")

    # ------------------------------------------------------------------
    # Scene interface
    # ------------------------------------------------------------------

    def update(self):
        pass

    def draw(self, surface):
        pass

    def handle_event(self, event):
        if not isinstance(event, tuple) or len(event) != 2:
            return
        event_type, _ = event
        if event_type == "B":
            self._on_back()
            return True
        if event_type == "UP":
            self._move_selection(-1)
            return True
        if event_type == "DOWN":
            self._move_selection(1)
            return True

    def cleanup(self):
        for comp in self._components:
            if comp and comp in self.ui_manager.components:
                self.ui_manager.remove_component(comp)
        self._components.clear()
        self._row_labels.clear()
        runtime_globals.game_console.log("[ArenaHistoryView] Cleanup complete")
