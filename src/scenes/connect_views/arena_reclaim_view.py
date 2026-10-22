"""
ArenaReclaimView - Season results for a finished arena team.

Reached from ArenaView when the player has a team from a finished season
whose results were not claimed. Displays the team's final rank, score,
record and coin reward. Any input dismisses the window -- at that moment
the view:

  1. Posts ``/teams/claim-rewards`` so the server credits the coins and
     flags the finished team(s) as claimed.
  2. Mirrors the new coin balance into ``game_globals.coins`` so the
     UI doesn't lie until the next sync.
  3. Routes back to ArenaView, which will re-fetch and present the new
     season (if any).

The team's pets never left the save: they stayed in the freezer, locked
until the season ended, and are free to leave it now. The record of their
server copies (battles and wins, shared by the whole team) was added to
them when the arena hub learnt the season had ended
(``utils.arena_pets.apply_season_results``); this view says so.
"""
import threading

from ui.ui_manager import UIManager
from ui.components.title_scene import TitleScene
from ui.components.background import Background
from ui.components.label import Label
from ui.ui_constants import BASE_RESOLUTION
from core import runtime_globals, game_globals
from services.omninet_service import omninet_service


class ArenaReclaimView:
    """Display + commit the reclaim of a past arena team."""

    def __init__(self, ui_manager: UIManager, change_view_callback,
                 discord_module=None, team: dict | None = None):
        self.ui_manager = ui_manager
        self.change_view = change_view_callback
        self._team = team or {}
        self._components = []
        self._dismissed = False
        self._setup_ui()

    # ------------------------------------------------------------------

    def _add(self, comp):
        self.ui_manager.add_component(comp)
        self._components.append(comp)
        return comp

    def _setup_ui(self):
        w = h = BASE_RESOLUTION

        bg = Background(w, h)
        bg.set_regions([(0, h, "black")])
        self._add(bg)
        self._add(TitleScene(0, 9, "RESULTS"))

        season_name = self._team.get('season_name') or "Past Season"
        self._add(Label(
            w // 2, 38, season_name, is_title=True,
            color_override=(255, 255, 255), center=True,
            word_wrap=True, max_width=w - 20))

        rank = self._team.get('final_rank') or self._team.get('rank')
        rank_text = f"Rank: {rank}" if rank else "Rank: -"
        if rank == 1:
            rank_text += "  CHAMPION!"
        elif rank in (2, 3):
            rank_text += "  PODIUM!"
        self._add(Label(
            w // 2, 70, rank_text,
            color_override=(255, 215, 80), center=True))

        score = self._team.get('score', 0)
        record = (f"{self._team.get('wins', 0)}W "
                  f"{self._team.get('losses', 0)}L "
                  f"{self._team.get('draws', 0)}D")
        self._add(Label(
            w // 2, 90, f"Score: {score}  {record}",
            color_override=(120, 220, 255), center=True))

        coins = int(self._team.get('rewarded_coins') or 0)
        coin_color = (120, 220, 120) if coins > 0 else (200, 200, 200)
        coin_text = f"Reward: {coins} coins" if coins > 0 else "Reward: none"
        self._add(Label(
            w // 2, 115, coin_text,
            color_override=coin_color, center=True))

        # What the pets got from the season
        pets = self._team.get('pets') or []
        if pets and any('battles' in p for p in pets):
            battles = max(int(p.get('battles') or 0) for p in pets)
            wins = max(int(p.get('wins') or 0) for p in pets)
            self._add(Label(
                w // 2, 134, f"Each pet: +{battles} battles, {wins} won",
                color_override=(180, 200, 255), center=True,
                word_wrap=True, max_width=w - 20))

        # Freezer notice + dismissal hint
        self._add(Label(
            w // 2, 156, "Your team's pets can leave the freezer now.",
            color_override=(220, 220, 220), center=True,
            word_wrap=True, max_width=w - 20))
        self._add(Label(
            w // 2, h - 30, "Press any key or tap to continue",
            color_override=(150, 150, 150), center=True,
            word_wrap=True, max_width=w - 20))

    # ------------------------------------------------------------------
    # Dismiss + commit
    # ------------------------------------------------------------------

    def _dismiss(self):
        """Claim the rewards and route back to the arena.  Idempotent."""
        if self._dismissed:
            return
        self._dismissed = True
        runtime_globals.game_sound.play("menu")

        def _worker():
            try:
                ok, data = omninet_service.claim_team_rewards()
                if ok and isinstance(data, dict):
                    new_balance = data.get('new_balance')
                    if new_balance is not None:
                        game_globals.coins = int(new_balance)
                    claimed = int(data.get('coins_claimed') or 0)
                    if claimed:
                        runtime_globals.arena_notice = {
                            "kind": "win", "text": f"+{claimed} coins claimed!"}
                else:
                    runtime_globals.game_console.log(
                        f"[ArenaReclaim] claim failed: {data!r}")
            except Exception as exc:
                runtime_globals.game_console.log(
                    f"[ArenaReclaim] claim raised: {exc}")

            try:
                game_globals.save()
            except Exception:
                pass

            # Route back on the main thread next tick — change_view is
            # safe to call from a worker since it just flips state.
            self.change_view("arena")

        threading.Thread(target=_worker, daemon=True).start()

    # ------------------------------------------------------------------
    # Scene interface
    # ------------------------------------------------------------------

    def update(self):
        pass

    def draw(self, surface):
        pass

    def handle_event(self, event):
        # Any input dismisses
        if self._dismissed:
            return True
        if not isinstance(event, tuple) or len(event) != 2:
            return False
        event_type, _ = event
        # Filter out passive hover events
        if event_type in ("MOUSE_MOTION", "SCROLL"):
            return False
        self._dismiss()
        return True

    def cleanup(self):
        for comp in self._components:
            if comp and comp in self.ui_manager.components:
                self.ui_manager.remove_component(comp)
        self._components.clear()
        runtime_globals.game_console.log("[ArenaReclaimView] Cleanup complete")
