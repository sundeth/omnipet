"""
ArenaStandingsView - The running season's table.

Lists the season's teams by rank (teams that have fought first, then score,
wins and the earlier team -- the order the final ranks and prizes follow)
with score and record; the player's own row is highlighted and the list
opens on it. UP / DOWN scroll; the selected row's Digimon are shown under
the list. The season's prizes are noted at the top.
"""
import threading

from ui.ui_manager import UIManager
from ui.components.title_scene import TitleScene
from ui.components.button import Button
from ui.components.background import Background
from ui.components.label import Label
from ui.ui_constants import BASE_RESOLUTION
from core import runtime_globals


def prize_text(season: dict) -> str:
    """``PRIZES 50/25/10 COINS`` for *season* (multiplier applied)."""
    config = (season or {}).get('config') or {}
    prizes = config.get('rank_prizes')
    if not prizes:
        return ""
    multiplier = float((season or {}).get('reward_multiplier') or 1.0)
    coins = [int(round(int(c) * multiplier)) for c in prizes[:5]]
    more = "/..." if len(prizes) > 5 else ""
    # One line on the 240 px screen, even with five prize places.
    return "PRIZES " + "/".join(str(c) for c in coins) + more + " COINS"


class ArenaStandingsView:
    """Season table + Back."""

    ROW_HEIGHT = 16
    MAX_VISIBLE_ROWS = 8

    def __init__(self, ui_manager: UIManager, change_view_callback,
                 discord_module=None, season: dict | None = None):
        self.ui_manager = ui_manager
        self.change_view = change_view_callback
        self._season = season or {}
        self._components = []
        self._rows = []
        self._selected_index = 0
        self._row_labels = []
        self._loading = False
        self._build_ui()
        if self._season.get('id'):
            self._fetch_async()
        else:
            self.status_label.set_text("No season")

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
        self._add(TitleScene(0, 9, "RANKS"))

        self._add(Label(
            w // 2, 30, prize_text(self._season) or (self._season.get('name') or ""),
            color_override=(255, 215, 80), center=True,
            word_wrap=True, max_width=w - 20))

        self.status_label = self._add(Label(
            w // 2, 80, "Loading ranks...",
            color_override=(180, 180, 180), center=True,
            word_wrap=True, max_width=w - 20))

        list_top = 46
        for i in range(self.MAX_VISIBLE_ROWS):
            lbl = self._add(Label(
                8, list_top + i * self.ROW_HEIGHT, "",
                color_override=(220, 220, 220)))
            lbl.visible = False
            self._row_labels.append(lbl)

        self.detail_label = self._add(Label(
            w // 2, list_top + self.MAX_VISIBLE_ROWS * self.ROW_HEIGHT + 4, "",
            color_override=(160, 200, 255), center=True,
            word_wrap=True, max_width=w - 20))

        btn_w, btn_h = 80, 24
        self._add(Button(
            (w - btn_w) // 2, h - btn_h - 8, btn_w, btn_h, "BACK", self._on_back,
            cut_corners={'tl': True, 'tr': False, 'bl': False, 'br': True}))

    # ------------------------------------------------------------------

    def _fetch_async(self):
        from services.omninet_service import omninet_service
        self._loading = True

        def _worker():
            ok, data = omninet_service.get_season_standings(self._season.get('id'))
            if ok and isinstance(data, list):
                self._rows = data
                mine = next((i for i, r in enumerate(data) if r.get('is_you')), 0)
                self._selected_index = mine
                self.status_label.set_text("" if data else "No teams yet")
            else:
                self._rows = []
                self.status_label.set_text(data if isinstance(data, str) else "Ranks unavailable")
            self._loading = False
            self._render_rows()

        threading.Thread(target=_worker, daemon=True).start()

    @staticmethod
    def format_row(row: dict) -> str:
        name = row.get('nickname') or "?"
        name = name if len(name) <= 11 else name[:10] + "."
        return (f"{row.get('rank', '?'):>2}. {name:<11} {row.get('score', 0):>4} "
                f"{row.get('wins', 0)}-{row.get('losses', 0)}-{row.get('draws', 0)}")

    def _render_rows(self):
        rows = self._rows
        max_rows = self.MAX_VISIBLE_ROWS
        first = max(0, min(self._selected_index - max_rows // 2, len(rows) - max_rows))
        for i, lbl in enumerate(self._row_labels):
            idx = first + i
            if idx >= len(rows):
                lbl.visible = False
                lbl.set_text("")
                continue
            row = rows[idx]
            prefix = ">" if idx == self._selected_index else " "
            lbl.set_text(prefix + self.format_row(row))
            if row.get('is_you'):
                lbl.color_override = (120, 230, 120)
            elif idx == self._selected_index:
                lbl.color_override = (255, 255, 120)
            else:
                lbl.color_override = (220, 220, 220)
            lbl.visible = True
        if rows:
            pets = rows[self._selected_index].get('pets') or []
            self.detail_label.set_text(", ".join(pets))
        else:
            self.detail_label.set_text("")

    def _move_selection(self, delta: int):
        if not self._rows:
            return
        new = max(0, min(self._selected_index + delta, len(self._rows) - 1))
        if new != self._selected_index:
            self._selected_index = new
            runtime_globals.game_sound.play("menu")
            self._render_rows()

    def _on_back(self):
        runtime_globals.game_sound.play("cancel")
        self.change_view("arena")

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
        runtime_globals.game_console.log("[ArenaStandingsView] Cleanup complete")
