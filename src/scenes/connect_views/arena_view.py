"""
ArenaView - Omninet arena hub.

Layout (based on the design sketch at Arena.png):

    [Title bar: ARENA]
    YOUR TEAM                 RANK   3/8
    [pet] [pet] [pet]         SCORE  125
    name  name  name          RECORD 5-2-1
    TIME LEFT: X DAYS Y HOURS
    [   FIND BATTLE (7 LEFT)   ]
    <last battle / what just happened>
    <defences, or when the next attacks arrive>
    [RULES] [RANKS] [HISTORY] [BACK]

If the player has no current-season team the team area is replaced with a
"Create Team" button (when a season is active) or an unselectable
"Season Not Started" placeholder when no season exists.

A team from a finished season whose results were not seen yet takes the
view over with a RESULTS button (coins are claimed there). Team pets never
leave the save: they sit locked in the freezer until their season ends.
When the server reports a season finished, the record of the team's server
copies is added to the pets and their locks are released
(``utils.arena_pets.apply_season_results``).
"""
import threading
import time
from datetime import datetime, date

from ui.ui_manager import UIManager
from ui.components.title_scene import TitleScene
from ui.components.button import Button
from ui.components.background import Background
from ui.components.label import Label
from ui.components.label_value import LabelValue
from ui.components.team_display import TeamDisplay
from ui.ui_constants import BASE_RESOLUTION
from core import runtime_globals, game_globals
from services.omninet_service import UNREADABLE_ANSWER, omninet_service

#: Colours of the result line: win, loss, draw, neutral.
_RESULT_COLORS = {"win": (120, 230, 120), "loss": (255, 120, 100),
                  "draw": (220, 220, 140), "info": (180, 200, 255)}


def _parse_time(value):
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    return moment


def _short_delta(seconds: float) -> str:
    minutes = max(1, int(seconds // 60))
    if minutes >= 24 * 60:
        return f"{minutes // (24 * 60)}d {(minutes // 60) % 24}h"
    if minutes >= 60:
        return f"{minutes // 60}h {minutes % 60}m"
    return f"{minutes}m"


def short_name(name: str) -> str:
    """A pet name short enough for the hub's team row (6 characters)."""
    return name if len(name) <= 6 else name[:5] + "."


def _name_centers(count: int) -> list:
    """x of each team slot's centre in the hub (TeamDisplay at x=4, 140
    wide: hexagons of radius 20, 8 apart, centred)."""
    count = max(1, min(3, count))
    total = count * 40 + (count - 1) * 8
    start = 4 + (140 - total) // 2
    return [start + 20 + i * 48 for i in range(count)]


def _sprite_pets(team: dict) -> list:
    """Throwaway pets to draw a team's sprites (from its battle entries)."""
    from utils.arena_replay import _local_pet
    pets = []
    for row in (team or {}).get('pets') or []:
        entry = ((row or {}).get('extra_data') or {}).get('arena_entry')
        if not entry:
            entry = {"module": row.get('module_name'), "name": row.get('name'),
                     "version": int(row.get('pet_version') if row.get('pet_version') not in (None, "") else 1),
                     "level": row.get('level', 1)}
        try:
            pets.append(_local_pet(entry))
        except Exception:  # module not installed here: the name still shows
            pets.append(None)
    return pets


#: The season line when Omninet could not be asked (a failed fetch, not the
#: server's 404 between seasons).
SEASON_UNREACHABLE = "Cannot reach Omninet"
#: What OmninetService returns when no answer came, or one it cannot read.
_FETCH_FAILURES = ("Cannot connect to server", "Connection timeout", UNREADABLE_ANSWER,
                   "Omninet request failed, try again later")


def season_fetch_failed(message) -> bool:
    """Whether a refused current-season request failed to reach Omninet
    (no answer, a gateway error, a page it cannot read) rather than being
    told that no season is running (404 "No arena season is running")."""
    text = str(message or "")
    return text in _FETCH_FAILURES or text.startswith("Request failed: 5")


class ArenaView:
    """Arena hub view — team summary, rank, find battle, sub-view navigation."""

    def __init__(self, ui_manager: UIManager, change_view_callback, discord_module=None):
        self.ui_manager = ui_manager
        self.change_view = change_view_callback

        # Components
        self._components = []

        # Server data (filled in by background fetch)
        self._season = None
        #: The season could not be fetched (no answer, an error page), as
        #: opposed to the server saying no season is running.
        self._season_unreachable = False
        self._team = None
        # Finished-season team whose results were not seen yet. When set,
        # the view shows those results before anything else.
        self._pending_team = None
        self._loading = True
        self._fetch_lock = threading.Lock()
        self._finding_battle = False
        # A finished team whose season the server has not closed yet (its
        # clock runs once a minute), and when to look again by itself: at
        # the next attack day, or every few seconds while results are due.
        self._closing_team = None
        self._refresh_at = None
        # What the last action left to say (a battle result, a registered
        # team), shown once.
        self._notice = getattr(runtime_globals, 'arena_notice', None)
        runtime_globals.arena_notice = None

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
            10, 30, "YOUR TEAM",
            color_override=(220, 220, 220)))

        # The team's sprites, and its pets' names centred under them.
        self.team_display = self._add(TeamDisplay(4, 42, 140, 40))
        self.team_display.visible = False
        self.pet_labels = []
        for x in _name_centers(3):
            lbl = self._add(Label(
                x, 84, "", color_override=(255, 255, 255),
                center=True))
            self.pet_labels.append(lbl)

        # Create Team / Season Not Started button — hidden until needed.
        self.create_team_button = self._add(Button(
            10, 50, 130, 28, "CREATE TEAM", self._on_create_team))
        self.create_team_button.visible = False

        # ── Rank / Score / Record (right) ─────────────────────────────
        # Anchored to the right side.  LabelValue draws label on the left
        # and value on the right of its rect, so we size the rect to span
        # from the team area's right edge to the screen edge.
        rank_x = 148
        rank_w = w - rank_x - 8
        self.rank_value = self._add(LabelValue(
            rank_x, 32, rank_w, 18, "RANK", "-",
            color_override=(220, 220, 220),
            value_color=(255, 215, 80)))
        self.score_value = self._add(LabelValue(
            rank_x, 52, rank_w, 18, "SCORE", "0",
            color_override=(220, 220, 220),
            value_color=(120, 220, 255)))
        self.record_value = self._add(LabelValue(
            rank_x, 72, rank_w, 18, "W-L-D", "-",
            color_override=(220, 220, 220),
            value_color=(200, 200, 200)))

        # ── Season / time-left line ──────────────────────────────────
        self.time_label = self._add(Label(
            w // 2, 102, "Loading season...",
            color_override=(180, 180, 180), center=True,
            word_wrap=True, max_width=w - 20))

        # ── Find Battle (large button) ───────────────────────────────
        find_w = w - 16
        cut = {'tl': True, 'tr': False, 'bl': False, 'br': True}
        self.find_button = self._add(Button(
            8, 120, find_w, 30, "FIND BATTLE", self._on_find_battle,
            cut_corners=cut, enabled=False))

        # ── Status / result line and info line ───────────────────────
        self.status_label = self._add(Label(
            w // 2, 156, "", color_override=(255, 140, 80), center=True,
            word_wrap=True, max_width=w - 20))
        self.info_label = self._add(Label(
            w // 2, 184, "", color_override=(170, 170, 170), center=True,
            word_wrap=True, max_width=w - 20))

        # ── Footer buttons: RULES / RANKS / HISTORY / BACK ───────────
        btn_w = 54
        btn_h = 22
        gap = 4
        total_w = 4 * btn_w + 3 * gap
        x0 = (w - total_w) // 2
        y0 = h - btn_h - 8
        # History starts disabled — we don't know yet whether the player has
        # a team, and enabling-then-disabling on data load produces a flicker
        # on hover.  _render_state() flips it on if a team exists.
        self.rules_button = self._add(Button(
            x0, y0, btn_w, btn_h, "RULES", self._on_rules,
            cut_corners=cut))
        self.ranks_button = self._add(Button(
            x0 + (btn_w + gap), y0, btn_w, btn_h, "RANKS", self._on_ranks,
            cut_corners=cut, enabled=False))
        self.history_button = self._add(Button(
            x0 + 2 * (btn_w + gap), y0, btn_w, btn_h, "HISTORY", self._on_history,
            cut_corners=cut, enabled=False))
        self.back_button = self._add(Button(
            x0 + 3 * (btn_w + gap), y0, btn_w, btn_h, "BACK", self._on_back,
            cut_corners=cut))

        self._show_notice()

    def _show_notice(self):
        notice = self._notice
        if not notice:
            return
        if isinstance(notice, dict):
            self.status_label.color_override = _RESULT_COLORS.get(
                notice.get('kind'), _RESULT_COLORS['info'])
            self.status_label.set_text(notice.get('text', ''))
        else:
            self.status_label.color_override = _RESULT_COLORS['info']
            self.status_label.set_text(str(notice))

    def _say(self, text, kind=None):
        """Put *text* on the status line (an error unless *kind* says)."""
        self.status_label.color_override = (_RESULT_COLORS.get(kind) if kind
                                            else (255, 140, 80))
        self.status_label.set_text(text)

    # ------------------------------------------------------------------
    # Background data fetch
    # ------------------------------------------------------------------

    def _refresh_async(self):
        if not self._fetch_lock.acquire(blocking=False):
            return
        self._loading = True
        self.time_label.set_text("Loading season...")
        if not self._notice:
            self.status_label.set_text("")

        def _worker():
            sprites = None
            try:
                ok_s, season = omninet_service.get_current_season()
                if ok_s and isinstance(season, dict):
                    self._season = season
                    self._season_unreachable = False
                else:
                    self._season = None
                    self._season_unreachable = not ok_s and season_fetch_failed(season)

                ok_t, team = omninet_service.get_current_team()
                if ok_t and isinstance(team, dict):
                    self._team = team
                    self._lock_loose_pets(team)
                    sprites = _sprite_pets(team)
                else:
                    self._team = None

                # Finished seasons: their results go onto the pets, and
                # unclaimed results are shown first.
                self._pending_team = self._fetch_pending_past_team()
                if self._pending_team:
                    sprites = _sprite_pets(self._pending_team)
            except Exception as exc:
                runtime_globals.game_console.log(f"[ArenaView] Refresh error: {exc}")
            finally:
                self._loading = False
                self._fetch_lock.release()
                self._drop_sprites()
                self._sprites = sprites
                self._render_state()

        threading.Thread(target=_worker, daemon=True).start()

    def _lock_loose_pets(self, team: dict) -> None:
        """Lock party pets that are on the current team but still free.

        A registration whose answer never arrived (a timeout) leaves the
        team on the server and its pets in the party; the team's rows name
        the pets by uid, so they are found and locked here.
        """
        try:
            from utils import arena_pets
            from scenes.connect_views.arena_team_creation_view import _parse_server_time
            uids = {row.get('uid') for row in team.get('pets') or [] if row.get('uid')}
            loose = [p for p in game_globals.pet_list
                     if getattr(p, 'uid', None) in uids and not game_globals.is_pet_arena_locked(p)]
            if not loose:
                return
            until = _parse_server_time(team.get('season_ends_at'))
            if until is None:
                return
            arena_pets.mark_team(loose, team)
            lock = {'until': until, 'team_id': str(team.get('id') or ''),
                    'season_id': str(team.get('season_id') or ''),
                    'season_name': team.get('season_name') or ''}
            if game_globals.lock_pets_for_arena(loose, lock):
                runtime_globals.game_console.log(
                    f"[ArenaView] locked {len(loose)} team pets left in the party")
        except Exception as exc:  # pylint: disable=broad-except
            runtime_globals.game_console.log(f"[ArenaView] lock check failed: {exc}")

    def _fetch_pending_past_team(self) -> dict | None:
        """Return the first finished-season team with unclaimed results.

        Every finished team some local pets still wait on gives them its
        record and releases them (the lock's own end time is only an upper
        bound: a season may close early).
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
        now = datetime.now().astimezone()
        self._closing_team = next(
            (t for t in teams if isinstance(t, dict) and t.get('season_status') == 'active'
             and _parse_time(t.get('season_ends_at')) is not None
             and _parse_time(t.get('season_ends_at')) <= now), None)
        self._apply_finished(finished)
        for team in finished:
            if not team.get('reward_claimed'):
                return self._with_team_details(team)
        return None

    def _apply_finished(self, finished: list) -> None:
        """Add finished teams' records to the pets still waiting on them."""
        try:
            from utils import arena_pets
            waiting = arena_pets.pending_team_ids()
            details = []
            for team in finished:
                if str(team.get('id')) in waiting:
                    detail = self._with_team_details(dict(team, pets=None))
                    if detail.get('pets'):
                        details.append(detail)
            applied = arena_pets.apply_season_results(details) if details else []
            # Pets whose team the server lists as finished but sent no rows
            # for still leave the lock (the old release behaviour).
            game_globals.release_arena_locks([t.get('id') for t in finished])
            if applied:
                battles = sum(a['battles'] for a in applied)
                runtime_globals.game_console.log(
                    f"[ArenaView] season results applied to {len(applied)} pets "
                    f"({battles} battles)")
                self._notice = {"kind": "info", "text":
                                f"Season over: {len(applied)} pets back with "
                                f"+{battles // max(1, len(applied))} battles each."}
                self._show_notice()
        except Exception as exc:
            runtime_globals.game_console.log(f"[ArenaView] season results error: {exc}")

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
        for key in ('attacks', 'defences', 'defence_wins'):
            if detail.get(key) is not None:
                merged[key] = detail[key]
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
        self._schedule_refresh()
        if has_season:
            self.time_label.set_text(self._format_time_left(self._season))
        elif self._closing_team:
            self.time_label.set_text("Season over: results in a moment...")
        elif self._season_unreachable:
            # A failed fetch read "No active season" too.
            self.time_label.set_text(SEASON_UNREACHABLE)
        else:
            self.time_label.set_text("No active season")

        # ── Team area ─────────────────────────────────────────────────
        if has_team:
            self.team_header_label.visible = True
            self.create_team_button.visible = False
            self.create_team_button.set_enabled(False)
            self._show_team(self._team, getattr(self, '_sprites', None))
        else:
            self._show_team(None, None)
            self.team_header_label.visible = False
            self.create_team_button.visible = True
            if has_season:
                self.create_team_button.set_text("CREATE TEAM")
                self.create_team_button.set_enabled(True)
            else:
                self.create_team_button.set_text("SEASON NOT STARTED")
                self.create_team_button.set_enabled(False)

        # ── Rank / Score / Record ─────────────────────────────────────
        if has_team:
            rank = self._team.get('rank')
            total = self._team.get('season_teams')
            if rank and total:
                self.rank_value.set_value(f"{rank}/{total}")
            else:
                self.rank_value.set_value(str(rank) if rank else "-")
            self.score_value.set_value(str(self._team.get('score', 0)))
            self.record_value.set_value(
                f"{self._team.get('wins', 0)}-{self._team.get('losses', 0)}"
                f"-{self._team.get('draws', 0)}")
        else:
            self.rank_value.set_value("-")
            self.score_value.set_value("0")
            self.record_value.set_value("-")

        # ── Find Battle button — only when we have a team ─────────────
        self.find_button.on_click_callback = self._on_find_battle
        if has_team:
            remaining = self._team.get('daily_battles_remaining')
            if remaining is None:
                self.find_button.set_text("FIND BATTLE")
                self.find_button.set_enabled(True)
            else:
                self.find_button.set_text(f"FIND BATTLE ({remaining} LEFT)")
                self.find_button.set_enabled(remaining > 0)
        else:
            self.find_button.set_text("FIND BATTLE")
            self.find_button.set_enabled(False)

        self.info_label.set_text(self._info_text() if has_team else (
            "Register a team to battle." if has_season else ""))

        # ── Footer ────────────────────────────────────────────────────
        self.rules_button.set_enabled(has_season)
        self.ranks_button.set_enabled(has_season)
        self.history_button.set_enabled(has_team)

    def _info_text(self) -> str:
        """New defences, defences so far, or when the next attacks arrive."""
        team = self._team or {}
        try:
            from utils import arena_pets
            new = arena_pets.unseen_defences(team)
        except Exception:  # pylint: disable=broad-except
            new = 0
        if new:
            return f"Attacked {new}x while away! See HISTORY."
        remaining = team.get('daily_battles_remaining')
        if remaining == 0:
            nxt = _parse_time(team.get('next_attacks_at'))
            if nxt is not None:
                now = datetime.now(nxt.tzinfo)
                return f"No attacks left. New ones in {_short_delta((nxt - now).total_seconds())}."
            return "No attacks left today."
        defences = team.get('defences')
        if defences:
            return f"Defended {defences}x, won {team.get('defence_wins', 0)}."
        if defences == 0:
            return "Not attacked yet."
        return ""

    def _show_team(self, team, sprites):
        """The team's names (and sprites when the modules are installed)."""
        rows = (team or {}).get('pets') or []
        centers = _name_centers(len(rows) or 3)
        for i, lbl in enumerate(self.pet_labels):
            if i < len(rows):
                lbl._center_origin = centers[i]
                lbl.set_text(short_name(rows[i].get('name', '?')))
                lbl._apply_center()
            else:
                lbl.set_text("")
        if team and sprites and any(sprites):
            self.team_display.set_slot_count(len(rows) or 1)
            self.team_display.set_pets([p for p in sprites])
            self.team_display.visible = True
        else:
            self.team_display.visible = False

    def _render_pending_state(self, pending: dict):
        """Layout when the player owes a reclaim from a past season.

        - Show the past team's pet names, rank, score (read-only).
        - Replace Find Battle with SEASON RESULTS.
        - Disable Rules / Ranks (their data points at the current season,
          which the player can't engage with yet); History shows the
          finished team's battles.
        - Hide / disable Create Team.
        """
        self.team_header_label.visible = True
        self.create_team_button.visible = False
        self.create_team_button.set_enabled(False)
        self._show_team(pending, getattr(self, '_sprites', None))

        rank = pending.get('rank') or pending.get('final_rank')
        self.rank_value.set_value(str(rank) if rank else "-")
        self.score_value.set_value(str(pending.get('score', 0)))
        self.record_value.set_value(
            f"{pending.get('wins', 0)}-{pending.get('losses', 0)}-{pending.get('draws', 0)}")

        season_name = pending.get('season_name') or "Previous season"
        self.time_label.set_text(f"{season_name} has ended.")

        # Find Battle slot becomes the results entry point
        self.find_button.set_text("SEASON RESULTS")
        self.find_button.set_enabled(True)
        self.find_button.on_click_callback = self._on_reclaim

        # Rules / Ranks pertain to the live season — off until reclaim; the
        # finished team's battles can still be watched.
        self.rules_button.set_enabled(False)
        self.ranks_button.set_enabled(False)
        self.history_button.set_enabled(bool(pending.get('id')))
        coins = int(pending.get('rewarded_coins') or 0)
        self.info_label.set_text(f"{coins} coins waiting for you." if coins
                                 else "See how your team finished.")
        if not self._notice:
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
            self._say("See your last season's results first.")
            return
        if not self._season:
            self._say(SEASON_UNREACHABLE if self._season_unreachable else "No active season")
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
        self.find_button.set_enabled(False)
        self._say("Finding an opponent...", "info")
        team_id = self._team.get('id')

        def _worker():
            ok, data = omninet_service.find_battle(team_id)
            self._finding_battle = False
            if ok and isinstance(data, dict) and data.get('battle_found'):
                battle = data.get('battle') or {}
                notice = battle_notice(battle, team_id)
                runtime_globals.arena_notice = notice
                from utils.arena_replay import start_replay
                problem = start_replay(battle, team_id, return_view="arena")
                if problem:
                    # The battle counted; only the playback is unavailable.
                    runtime_globals.arena_notice = None
                    self._notice = dict(notice, text=f"{notice['text']} ({problem})")
                    self._show_notice()
                    self._refresh_async()
            else:
                message = data.get('message') if isinstance(data, dict) else str(data)
                runtime_globals.game_sound.play("cancel")
                self._say(message or "No opponent found")
                self.find_button.set_enabled(True)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_rules(self):
        runtime_globals.game_sound.play("menu")
        self.change_view("arena_rules", season=self._season)

    def _on_ranks(self):
        if not self._season:
            return
        runtime_globals.game_sound.play("menu")
        self.change_view("arena_standings", season=self._season)

    def _on_history(self):
        team = self._pending_team or self._team
        if not team:
            return
        runtime_globals.game_sound.play("menu")
        try:
            from utils import arena_pets
            arena_pets.mark_defences_seen(team.get('id'), team.get('defences'))
        except Exception:  # pylint: disable=broad-except
            pass
        self.change_view("arena_history",
                         team_id=team.get('id'),
                         team_name=team.get('name') or team.get('season_name'))

    def _on_back(self):
        runtime_globals.game_sound.play("cancel")
        # The Arena submenu is gone — Back drops the user back at the main
        # menu (Arena is reached directly from there now).
        self.change_view("main_menu")

    # ------------------------------------------------------------------
    # Scene interface
    # ------------------------------------------------------------------

    def _schedule_refresh(self):
        """Look again by itself when something is due: a closing season's
        results (every 10 s) or the next attack day."""
        due = None
        if self._closing_team:
            due = time.time() + 10
        elif self._team and self._team.get('daily_battles_remaining') == 0:
            nxt = _parse_time(self._team.get('next_attacks_at'))
            if nxt is not None:
                due = nxt.timestamp() + 2
        self._refresh_at = due

    def update(self):
        due = self._refresh_at
        if due is not None and not self._loading and not self._finding_battle                 and time.time() >= due:
            self._refresh_at = None
            self._refresh_async()

    def draw(self, surface):
        pass

    def handle_event(self, event):
        if not isinstance(event, tuple) or len(event) != 2:
            return
        event_type, _ = event
        if event_type == "B":
            self._on_back()
            return True

    def _drop_sprites(self):
        """Forget the throwaway sprite pets' art (GamePet keeps it in the
        global sprite cache, keyed by the pet)."""
        for pet in getattr(self, '_sprites', None) or []:
            if pet is not None:
                runtime_globals.pet_sprites.pop(pet, None)
        self._sprites = None

    def cleanup(self):
        for comp in self._components:
            if comp and comp in self.ui_manager.components:
                self.ui_manager.remove_component(comp)
        self._components.clear()
        self.team_display.set_pets([])
        self._drop_sprites()
        runtime_globals.game_console.log("[ArenaView] Cleanup complete")


def battle_notice(battle: dict, team_id) -> dict:
    """The hub's line about a battle this team just fought."""
    is_attacker = str(battle.get('team1_id')) == str(team_id)
    result = battle.get('result')
    log = battle.get('battle_log') or {}
    other = (log.get('defender') if is_attacker else log.get('attacker')) or {}
    nickname = other.get('nickname') or "a rival"
    change = battle.get('team1_score_change' if is_attacker else 'team2_score_change') or 0
    sign = "+" if change >= 0 else ""
    if result == 'draw':
        kind, word = "draw", "DRAW"
    elif (result == 'team1_win') == is_attacker:
        kind, word = "win", "WIN"
    else:
        kind, word = "loss", "LOSS"
    return {"kind": kind, "text": f"{word} vs {nickname}  {sign}{change}"}
