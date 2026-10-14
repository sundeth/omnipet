"""
ArenaView - Omninet arena hub.

Layout (based on the design sketch at Arena.png):

    [Title bar: ARENA]
    YOUR TEAM                 RANK
    [pet] [pet] [pet]         <rank>
                              <score>
    TIME LEFT: X DAYS Y HOURS
    [   FIND BATTLE 0/3   ]
    [RULES] [HISTORY] [BACK]

If the player has no current-season team the team area is replaced with a
"Create Team" button (when a season is active) or an unselectable
"Season Not Started" placeholder when no season exists.

A team from a finished season whose results were not seen yet takes the
view over with a RESULTS button (coins are claimed there). Team pets never
leave the save: they sit locked in the freezer until their season ends, and
a season the server reports finished releases them early.
"""
import threading
from datetime import datetime, date

from ui.ui_manager import UIManager
from ui.components.title_scene import TitleScene
from ui.components.button import Button
from ui.components.background import Background
from ui.components.label import Label
from ui.components.label_value import LabelValue
from ui.ui_constants import BASE_RESOLUTION
from core import runtime_globals, game_globals
from services.omninet_service import omninet_service


class ArenaView:
    """Arena hub view — team summary, rank, find battle, sub-view navigation."""

    def __init__(self, ui_manager: UIManager, change_view_callback, discord_module=None):
        self.ui_manager = ui_manager
        self.change_view = change_view_callback

        # Components
        self._components = []

        # Server data (filled in by background fetch)
        self._season = None
        self._team = None
        # Finished-season team whose results (and coins) were not claimed.
        # When set, the view shows those results before anything else.
        self._pending_team = None
        self._loading = True
        self._fetch_lock = threading.Lock()
        self._finding_battle = False

        self._build_ui()
        self._refresh_async()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _add(self, comp):
        self.ui_manager.add_component(comp)
        self._components.append(comp)
        return comp

    def _build_ui(self):
        """Create static layout — values are filled in by _render_state()."""
        w = h = BASE_RESOLUTION

        # Background + title
        bg = Background(w, h)
        bg.set_regions([(0, h, "black")])
        self._add(bg)
        self._add(TitleScene(0, 9, "ARENA"))

        # ── Team area (left) ──────────────────────────────────────────
        # "YOUR TEAM" label sits above the pet row.  When the team area
        # holds a Create Team / Season Not Started placeholder it is also
        # used as the section header.
        self.team_header_label = self._add(Label(
            10, 32, "YOUR TEAM",
            color_override=(220, 220, 220)))

        # Pet row labels — three slots, populated from team data.
        # We use simple labels for now; sprite display can be layered on top.
        self.pet_labels = []
        for i in range(3):
            lbl = self._add(Label(
                10 + i * 50, 60, "", color_override=(255, 255, 255),
                center=False))
            self.pet_labels.append(lbl)

        # Create Team / Season Not Started button — hidden until needed.
        self.create_team_button = self._add(Button(
            10, 50, 130, 28, "CREATE TEAM", self._on_create_team))
        self.create_team_button.visible = False

        # ── Rank / Score (right) ──────────────────────────────────────
        # Anchored to the right side.  LabelValue draws label on the left
        # and value on the right of its rect, so we size the rect to span
        # from the team area's right edge to the screen edge.
        rank_x = 150
        rank_w = w - rank_x - 8
        self.rank_value = self._add(LabelValue(
            rank_x, 32, rank_w, 18, "RANK", "-",
            color_override=(220, 220, 220),
            value_color=(255, 215, 80)))
        self.score_value = self._add(LabelValue(
            rank_x, 56, rank_w, 18, "SCORE", "0",
            color_override=(220, 220, 220),
            value_color=(120, 220, 255)))

        # ── Season / time-left line ──────────────────────────────────
        self.time_label = self._add(Label(
            w // 2, 100, "Loading season...",
            color_override=(180, 180, 180), center=True,
            word_wrap=True, max_width=w - 20))

        # ── Find Battle (large button) ───────────────────────────────
        find_w = w - 16
        cut = {'tl': True, 'tr': False, 'bl': False, 'br': True}
        self.find_button = self._add(Button(
            8, 130, find_w, 30, "FIND BATTLE", self._on_find_battle,
            cut_corners=cut, enabled=False))

        # ── Status / error line ──────────────────────────────────────
        self.status_label = self._add(Label(
            w // 2, 170, "", color_override=(255, 140, 80), center=True,
            word_wrap=True, max_width=w - 20))

        # ── Footer buttons: RULES / HISTORY / BACK ───────────────────
        btn_w = 64
        btn_h = 22
        gap = 6
        total_w = 3 * btn_w + 2 * gap
        x0 = (w - total_w) // 2
        y0 = h - btn_h - 10
        # History starts disabled — we don't know yet whether the player has
        # a team, and enabling-then-disabling on data load produces a flicker
        # on hover.  _render_state() flips it on if a team exists.
        self.rules_button = self._add(Button(
            x0, y0, btn_w, btn_h, "RULES", self._on_rules,
            cut_corners=cut))
        self.history_button = self._add(Button(
            x0 + btn_w + gap, y0, btn_w, btn_h, "HISTORY", self._on_history,
            cut_corners=cut, enabled=False))
        self.back_button = self._add(Button(
            x0 + 2 * (btn_w + gap), y0, btn_w, btn_h, "BACK", self._on_back,
            cut_corners=cut))

    # ------------------------------------------------------------------
    # Background data fetch
    # ------------------------------------------------------------------

    def _refresh_async(self):
        if not self._fetch_lock.acquire(blocking=False):
            return
        self._loading = True
        self.time_label.set_text("Loading season...")
        self.status_label.set_text("")

        def _worker():
            try:
                ok_s, season = omninet_service.get_current_season()
                if ok_s and isinstance(season, dict):
                    self._season = season
                else:
                    self._season = None

                ok_t, team = omninet_service.get_current_team()
                if ok_t and isinstance(team, dict):
                    self._team = team
                else:
                    self._team = None

                # Finished seasons: show unclaimed results first, and free
                # any freezer locks those seasons still hold.
                self._pending_team = self._fetch_pending_past_team()
            except Exception as exc:
                runtime_globals.game_console.log(f"[ArenaView] Refresh error: {exc}")
            finally:
                self._loading = False
                self._fetch_lock.release()
                self._render_state()

        threading.Thread(target=_worker, daemon=True).start()

    def _fetch_pending_past_team(self) -> dict | None:
        """Return the first finished-season team with unclaimed results.

        Also releases the freezer locks of every finished season's team: the
        lock's own end time is only an upper bound.
        """
        try:
            ok, payload = omninet_service.get_user_teams(include_past=True)
        except Exception as exc:
            runtime_globals.game_console.log(
                f"[ArenaView] past-teams fetch error: {exc}")
            return None
        if not ok:
            return None
        teams = payload if isinstance(payload, list) else (
            payload.get('teams') if isinstance(payload, dict) else None
        )
        if not teams:
            return None

        finished = [t for t in teams if isinstance(t, dict)
                    and t.get('season_status') == 'completed']
        try:
            released = game_globals.release_arena_locks([t.get('id') for t in finished])
            if released:
                runtime_globals.game_console.log(
                    f"[ArenaView] released {released} pets from finished seasons")
        except Exception as exc:
            runtime_globals.game_console.log(f"[ArenaView] lock release error: {exc}")
        for team in finished:
            if not team.get('reward_claimed'):
                return self._with_team_details(team)
        return None

    def _with_team_details(self, team: dict) -> dict:
        """List rows carry only a pet count: fetch the team's pets (and final
        rank) for the results screen. The row is kept if the fetch fails."""
        if team.get('pets') or not team.get('id'):
            return team
        try:
            ok, detail = omninet_service.get_team(team['id'])
        except Exception as exc:
            runtime_globals.game_console.log(f"[ArenaView] team fetch error: {exc}")
            return team
        if not ok or not isinstance(detail, dict):
            return team
        merged = dict(team)
        merged['pets'] = detail.get('pets') or []
        if merged.get('rank') is None:
            merged['rank'] = detail.get('final_rank', detail.get('rank'))
        return merged

    def _render_state(self):
        """Update labels + button enablement after a fetch completes."""
        has_season = bool(self._season)
        has_team = bool(self._team)
        pending = self._pending_team

        # When a past-season team is still waiting to be reclaimed we
        # take over the view entirely — the player has to deal with that
        # before anything related to the new season can happen.
        if pending:
            self._render_pending_state(pending)
            return

        # ── Time / season info ────────────────────────────────────────
        if has_season:
            self.time_label.set_text(self._format_time_left(self._season))
        else:
            self.time_label.set_text("No active season")

        # ── Team area ─────────────────────────────────────────────────
        if has_team:
            self.team_header_label.visible = True
            self.create_team_button.visible = False
            self.create_team_button.enabled = False
            pets = self._team.get('pets') or []
            for i, lbl in enumerate(self.pet_labels):
                if i < len(pets):
                    name = pets[i].get('name', '?')
                    short = name if len(name) <= 7 else name[:6] + "."
                    lbl.set_text(short)
                else:
                    lbl.set_text("")
        else:
            for lbl in self.pet_labels:
                lbl.set_text("")
            self.team_header_label.visible = False
            self.create_team_button.visible = True
            if has_season:
                self.create_team_button.text = "CREATE TEAM"
                self.create_team_button.enabled = True
            else:
                self.create_team_button.text = "SEASON NOT STARTED"
                self.create_team_button.enabled = False

        # ── Rank / Score ──────────────────────────────────────────────
        if has_team:
            rank = self._team.get('rank')
            self.rank_value.set_value(str(rank) if rank else "-")
            self.score_value.set_value(str(self._team.get('score', 0)))
        else:
            self.rank_value.set_value("-")
            self.score_value.set_value("0")

        # ── Find Battle button — only when we have a team ─────────────
        self.find_button.on_click_callback = self._on_find_battle
        if has_team:
            remaining = self._team.get('daily_battles_remaining')
            if remaining is None:
                self.find_button.text = "FIND BATTLE"
                self.find_button.enabled = True
            else:
                self.find_button.text = f"FIND BATTLE ({remaining} LEFT)"
                self.find_button.enabled = remaining > 0
        else:
            self.find_button.text = "FIND BATTLE"
            self.find_button.enabled = False

        # ── Footer ────────────────────────────────────────────────────
        self.rules_button.enabled = has_season
        self.history_button.enabled = has_team

    def _render_pending_state(self, pending: dict):
        """Layout when the player owes a reclaim from a past season.

        - Show the past team's pet names, rank, score (read-only).
        - Replace Find Battle with RECLAIM TEAM.
        - Disable Rules / History (their data points at the current
          season, which the player can't engage with yet).
        - Hide / disable Create Team.
        """
        self.team_header_label.visible = True
        self.create_team_button.visible = False
        self.create_team_button.enabled = False

        pets = pending.get('pets') or []
        for i, lbl in enumerate(self.pet_labels):
            if i < len(pets):
                name = pets[i].get('name', '?')
                short = name if len(name) <= 7 else name[:6] + "."
                lbl.set_text(short)
            else:
                lbl.set_text("")

        rank = pending.get('rank')
        self.rank_value.set_value(str(rank) if rank else "-")
        self.score_value.set_value(str(pending.get('score', 0)))

        season_name = pending.get('season_name') or "Previous season"
        self.time_label.set_text(f"{season_name} has ended.")

        # Find Battle slot becomes the results entry point
        self.find_button.text = "SEASON RESULTS"
        self.find_button.enabled = True
        self.find_button.on_click_callback = self._on_reclaim

        # Rules / History pertain to live seasons — both off until reclaim
        self.rules_button.enabled = False
        self.history_button.enabled = False
        self.status_label.set_text("")

    def _format_time_left(self, season: dict) -> str:
        """Format the season's time-left string as 'TIME LEFT: X DAYS Y HOURS'."""
        end_str = season.get('ends_at') or season.get('end_date', '')
        if not end_str:
            return "Season info unavailable"
        try:
            # Accept either "YYYY-MM-DD" date or full ISO datetime
            if 'T' in end_str:
                end_dt = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
            else:
                end_dt = datetime.combine(date.fromisoformat(end_str), datetime.min.time())
                # Treat end_date as end-of-day
                end_dt = end_dt.replace(hour=23, minute=59, second=59)
            now = datetime.now() if end_dt.tzinfo is None else datetime.now(end_dt.tzinfo)
            delta = end_dt - now
            if delta.total_seconds() <= 0:
                return "Season ended"
            days = delta.days
            hours = delta.seconds // 3600
            if days == 0 and hours == 0:
                return f"TIME LEFT: {max(1, delta.seconds // 60)} MINUTES"
            return f"TIME LEFT: {days} DAYS {hours} HOURS"
        except Exception:
            return f"Ends {end_str}"

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _on_create_team(self):
        runtime_globals.game_sound.play("menu")
        # Spec: the player cannot enter a new season if they still have
        # unclaimed pets/rewards from previous seasons.  The view should
        # already be in pending-state when this is true, but guard the
        # entry point anyway in case a stale UI click slips through.
        if self._pending_team:
            self.status_label.set_text(
                "See your last season's results first.")
            return
        if not self._season:
            self.status_label.set_text("No active season")
            return
        self.change_view("arena_team_creation", season=self._season)

    def _on_reclaim(self):
        """Open the results view for the finished-season team."""
        if not self._pending_team:
            return
        runtime_globals.game_sound.play("menu")
        self.change_view("arena_reclaim", team=self._pending_team)

    def _on_find_battle(self):
        if self._pending_team:
            # Defensive: render_state should have repointed the button
            # at _on_reclaim already, but if a click raced past, route
            # through the reclaim flow instead of attempting a battle
            # for a team the player owes coins on.
            self._on_reclaim()
            return
        if self._finding_battle or not self._team:
            return
        runtime_globals.game_sound.play("menu")
        self._finding_battle = True
        self.find_button.enabled = False
        self.status_label.set_text("Finding battle...")
        team_id = self._team.get('id')

        def _worker():
            ok, data = omninet_service.find_battle(team_id)
            self._finding_battle = False
            if ok and isinstance(data, dict) and data.get('battle_found'):
                from utils.arena_replay import start_replay
                problem = start_replay(data.get('battle') or {}, team_id,
                                       return_view="arena")
                if problem:
                    # The battle counted; only the playback is unavailable.
                    self.status_label.set_text(f"Battle done. {problem}")
                    self._refresh_async()
            else:
                message = data.get('message') if isinstance(data, dict) else str(data)
                self.status_label.set_text(message or "No opponent found")
                self.find_button.enabled = True

        threading.Thread(target=_worker, daemon=True).start()

    def _on_rules(self):
        runtime_globals.game_sound.play("menu")
        self.change_view("arena_rules", season=self._season)

    def _on_history(self):
        if not self._team:
            return
        runtime_globals.game_sound.play("menu")
        self.change_view("arena_history",
                         team_id=self._team.get('id'),
                         team_name=self._team.get('name'))

    def _on_back(self):
        runtime_globals.game_sound.play("cancel")
        # The Arena submenu is gone — Back drops the user back at the main
        # menu (Arena is reached directly from there now).
        self.change_view("main_menu")

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

    def cleanup(self):
        for comp in self._components:
            if comp and comp in self.ui_manager.components:
                self.ui_manager.remove_component(comp)
        self._components.clear()
        runtime_globals.game_console.log("[ArenaView] Cleanup complete")
