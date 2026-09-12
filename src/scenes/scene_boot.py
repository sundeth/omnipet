"""Scene Boot
Initial boot scene responsible for setting up the game start.
Shows the Omnipet logo, plays optional sounds, then routes to the
appropriate scene based on game state.

Navigation flow:
    1. No game mode preference → SceneSetup (first-time setup)
    2. Setup flags active → SceneSetup (incomplete setup)
    3. Progress Mode + device key → validate with server; fail → SceneError
    4. No modules + no internet → SceneError
    5. Otherwise → route_to_next_scene (tutorial → game → freezer → egg)
"""

import datetime
import os
import pygame
import socket
import threading

from ui.windows.window_background import WindowBackground
from core import game_globals, runtime_globals
import core.constants as constants
from utils.data_compat import availability as read_availability
from utils.module_utils import get_module
from utils.pet_utils import fix_positions_for_current_resolution
from utils.pygame_utils import blit_with_cache, blit_with_shadow, sprite_load_percent, get_font
from utils.scene_utils import change_scene
from utils import navigation_utils


def check_internet_connection(timeout: float = 2.0) -> bool:
    """
    Check if there is an active internet connection.
    
    Args:
        timeout: Connection timeout in seconds.
        
    Returns:
        True if internet is available, False otherwise.
    """
    try:
        # Try to connect to Google's DNS server
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
        return True
    except (socket.timeout, socket.error, OSError):
        pass
    
    # Try alternative - Cloudflare DNS
    try:
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("1.1.1.1", 53))
        return True
    except (socket.timeout, socket.error, OSError):
        pass
    
    return False


#=====================================================================
# SceneBoot
#=====================================================================
class SceneBoot:
    """
    Boot scene for the Virtual Pet game.
    Shows background while initializing the next scene.
    """

    def __init__(self) -> None:
        """
        Initializes the boot scene with a temporary timer.
        """
        self.background = WindowBackground(True)
        # Use "Fit" method for logo image for both landscape and portrait devices
        if runtime_globals.SCREEN_WIDTH >= runtime_globals.SCREEN_HEIGHT:
            self.logo = sprite_load_percent(constants.OMNIPET_LOGO_PATH, percent=100, keep_proportion=True, base_on="height")
        else:
            self.logo = sprite_load_percent(constants.OMNIPET_LOGO_PATH, percent=100, keep_proportion=True, base_on="width")

        self.boot_timer = int(120 * (game_globals.configuration.frame_rate / 30))
        self.f12_press_count = 0  # Track F12 presses for debug toggle

        # Sprite-database sync state (background thread updates these).
        self._sync_active = False
        self._sync_current = ""
        self._sync_thread = None
        self._sync_skipped = False  # Set when the user skips the sync wait
        self._sync_abort = False    # Cooperative stop flag for the worker
        self._sync_started_ms = 0
        # Hard cap on how long boot waits for the sprite DB.  A slow/hanging
        # server (responsive enough to pass the availability probe but then
        # stalling on sprite requests) must never freeze the boot screen — we
        # give up after this and continue (sprites just aren't refreshed).
        self._sync_max_ms = 12000

        # Eagerly load sound effects now that the Android environment
        # (IS_ANDROID / APP_ROOT) is configured.  GameSound was
        # instantiated when runtime_globals was first imported — too
        # early to safely resolve paths on Android — so we defer the
        # preload to here.  No-op on subsequent boot scene re-entries.
        try:
            runtime_globals.game_sound.load_sounds()
        except Exception as exc:
            runtime_globals.game_console.log(
                f"[SceneBoot] sound preload failed: {exc}")

        # Kick off the sprite-database sync for all installed modules. Runs in
        # the background; the scene shows progress and waits for it to finish
        # before transitioning. Skipped entirely if the DB / internet is down.
        self._start_sprite_sync()

        runtime_globals.game_console.log("[SceneBoot] Initialized")

    @staticmethod
    def _sprite_sync_marker_path() -> str:
        """Path of the file recording the last completed sprite-sync date."""
        from core import game_globals
        return os.path.join(game_globals._get_base_save_dir(), "sprite_sync.date")

    def _sprite_synced_today(self) -> bool:
        try:
            with open(self._sprite_sync_marker_path(), "r") as f:
                return f.read().strip() == datetime.date.today().isoformat()
        except Exception:
            return False

    def _record_sprite_sync_done(self) -> None:
        try:
            with open(self._sprite_sync_marker_path(), "w") as f:
                f.write(datetime.date.today().isoformat())
        except Exception as exc:
            runtime_globals.game_console.log(
                f"[SceneBoot] could not record sprite sync date: {exc}")

    def _start_sprite_sync(self) -> None:
        """Start the background sprite-database update for every module.

        Runs at most once per calendar day: a completed pass writes a marker
        file, and later boots on the same day skip the sync entirely (no
        availability probe, no wait). Aborted/offline runs don't write the
        marker, so the next boot retries.
        """
        modules = list(runtime_globals.game_modules.values()) if runtime_globals.game_modules else []
        if not modules:
            return
        if self._sprite_synced_today():
            runtime_globals.game_console.log(
                "[SceneBoot] Sprite database already checked today; skipping")
            return

        self._sync_active = True
        self._sync_started_ms = pygame.time.get_ticks()

        def worker():
            completed = False
            try:
                from services.sprite_sync_service import sprite_sync_service
                # Quick availability probe (short timeout); if the database is
                # offline/unreachable we skip the sync entirely rather than
                # stalling on it.
                if not sprite_sync_service.is_available():
                    runtime_globals.game_console.log(
                        "[SceneBoot] Sprite database unavailable; skipping sync")
                    return
                def progress(text):
                    self._sync_current = text

                completed = True
                for module in modules:
                    # Stop promptly once boot has given up waiting (slow server).
                    if self._sync_abort:
                        runtime_globals.game_console.log(
                            "[SceneBoot] Sprite sync aborted (boot continued)")
                        completed = False
                        break
                    name = getattr(module, "name", "")
                    self._sync_current = f"{name}: checking..."
                    try:
                        n = sprite_sync_service.update_module(module, progress_cb=progress)
                        if n:
                            runtime_globals.game_console.log(
                                f"[SceneBoot] {name}: {n} sprite(s) updated")
                    except Exception as e:
                        runtime_globals.game_console.log(
                            f"[SceneBoot] sync error for {name}: {e}")
            except Exception as e:
                completed = False
                runtime_globals.game_console.log(f"[SceneBoot] sprite sync failed: {e}")
            finally:
                if completed:
                    self._record_sprite_sync_done()
                self._sync_active = False

        self._sync_thread = threading.Thread(target=worker, daemon=True)
        self._sync_thread.start()

    def update(self) -> None:
        """
        Updates the boot scene, transitioning to the appropriate next scene after the timer expires.
        """
        self.boot_timer -= 1

        # Hold the boot scene while the sprite database is being updated,
        # unless the user chose to skip the wait.
        if self._sync_active and not self._sync_skipped:
            # Bail out if the sync has run past its cap — a slow/hanging server
            # must not freeze boot.  We tell the worker to stop and continue;
            # if the game server is also down, _validate_progress_mode will
            # surface the error screen (with a switch-to-Free-Mode option).
            if pygame.time.get_ticks() - self._sync_started_ms > self._sync_max_ms:
                runtime_globals.game_console.log(
                    "[SceneBoot] Sprite sync exceeded time budget; continuing")
                self._sync_abort = True
                self._sync_skipped = True
            else:
                return

        if self.boot_timer <= 0:
            self.transition_to_next_scene()

    def draw(self, surface: pygame.Surface) -> None:
        """
        Draws the boot background + logo, plus the sprite-update status below it
        while syncing.
        """
        self.background.draw(surface)
        # Center the logo image (always shown)
        sprite_rect = self.logo.get_rect(center=(runtime_globals.SCREEN_WIDTH // 2, runtime_globals.SCREEN_HEIGHT // 2))
        blit_with_cache(surface, self.logo, sprite_rect)
        if self._sync_active:
            self._draw_sync_status(surface)

    def _draw_sync_status(self, surface: pygame.Surface) -> None:
        """Draw 'Updating Sprite Database' + current module name near the bottom
        of the screen (the logo fills the screen, so this overlays its lower
        area where it stays visible)."""
        cx = runtime_globals.SCREEN_WIDTH // 2
        scale = getattr(runtime_globals, "UI_SCALE", 1)
        margin = int(10 * scale)

        title = get_font(int(20 * scale)).render("Updating Sprite Database", True, (255, 255, 255))
        sub = get_font(int(16 * scale)).render(self._sync_current or "...", True, (220, 220, 220))
        skip = get_font(int(16 * scale)).render("Press any button to skip", True, (200, 200, 200))

        skip_rect = skip.get_rect(midbottom=(cx, runtime_globals.SCREEN_HEIGHT - margin))
        sub_rect = sub.get_rect(midbottom=(cx, skip_rect.top - int(4 * scale)))
        title_rect = title.get_rect(midbottom=(cx, sub_rect.top - int(4 * scale)))

        blit_with_shadow(surface, title, title_rect.topleft)
        blit_with_shadow(surface, sub, sub_rect.topleft)
        blit_with_shadow(surface, skip, skip_rect.topleft)

    def handle_event(self, event) -> None:
        """Handle key press events. A/B/START/LCLICK skips boot. F12 x3 toggles debug."""

        event_type, event_data = event

        if event_type in ["A", "B", "START", "LCLICK"]:
            runtime_globals.game_sound.play("menu")
            if self._sync_active and not self._sync_skipped:
                self._sync_skipped = True
                runtime_globals.game_console.log("[SceneBoot] Skipped sprite database update")
            runtime_globals.game_console.log("[SceneBoot] Skipped boot timer")
            self.boot_timer = 0
        elif event_type == "F12":
            self.f12_press_count += 1
            runtime_globals.game_console.log(f"[SceneBoot] F12 pressed ({self.f12_press_count}/3)")
            if self.f12_press_count >= 3:
                game_globals.configuration.debug_mode = not game_globals.configuration.debug_mode
                status = "enabled" if game_globals.configuration.debug_mode else "disabled"
                runtime_globals.game_sound.play("attack_fail")
                runtime_globals.game_console.log(f"[SceneBoot] Debug mode {status}")
                self.f12_press_count = 0

    def transition_to_next_scene(self) -> None:
        """Route to the appropriate next scene based on game state.

        Priority:
            1. No game mode → setup
            2. Setup flags → setup
            3. Progress Mode + device key → validate on server
            4. No modules + no internet → error
            5. Refresh pets → route_to_next_scene
        """
        # 1. No game mode chosen yet → first-time setup
        if not game_globals.has_game_mode_preference():
            change_scene("setup")
            runtime_globals.game_console.log("[SceneBoot] → Setup (no game mode)")
            return

        # 2. Setup flags still pending (input or graphics)
        if game_globals.setup_input or game_globals.setup_graphics:
            change_scene("setup")
            runtime_globals.game_console.log("[SceneBoot] → Setup (setup flags)")
            return

        # 3. Progress Mode: validate device credentials with server
        if game_globals.is_progress_mode() and navigation_utils.has_device_key():
            self._validate_progress_mode()
            return

        # 4. No modules + no internet → error
        if not navigation_utils.has_modules_installed():
            if not check_internet_connection():
                from scenes.scene_error import SceneError
                SceneError.set_error(
                    message="NO MODULE DETECTED",
                    bottom_message="Connect to the internet or install a module manually"
                )
                change_scene("error")
                runtime_globals.game_console.log("[SceneBoot] → Error (no modules, no internet)")
                return

        # 5. Refresh pets and route to next scene
        self._refresh_pets()
        navigation_utils.route_to_next_scene(check_tutorial=True)

    def _validate_progress_mode(self) -> None:
        """Validate server credentials for Progress Mode.

        On success, syncs player_id and continues to normal routing.
        On failure, shows SceneError with retry / switch-to-free-mode options.
        """
        from services.omninet_service import omninet_service

        runtime_globals.game_console.log("[SceneBoot] Validating device credentials")
        success, message, user_info = omninet_service.validate_device()

        if success:
            # Sync player_id into game_globals (server may have refreshed it)
            server_id = omninet_service.get_player_id()
            if server_id:
                game_globals.set_player_id(server_id)
            runtime_globals.game_console.log("[SceneBoot] Server validation OK")

            # Reconcile coins / purchases / installed-module names with the
            # server so routing recognises modules the player owns (otherwise a
            # no-pets load wrongly bounces to the shop).  This is fast (no
            # downloads); fetching any module missing locally happens in the
            # background so boot isn't blocked.
            try:
                from utils.module_utils import sync_account_data, sync_owned_modules
                sync_account_data(download_missing=False)
                threading.Thread(
                    target=lambda: sync_owned_modules(download_missing=True),
                    daemon=True).start()
            except Exception as exc:
                runtime_globals.game_console.log(
                    f"[SceneBoot] account sync failed: {exc}")

            # Still check modules
            if not navigation_utils.has_modules_installed():
                if not check_internet_connection():
                    from scenes.scene_error import SceneError
                    SceneError.set_error(
                        message="NO MODULE DETECTED",
                        bottom_message="Connect to the internet or install a module manually"
                    )
                    change_scene("error")
                    return

            self._refresh_pets()
            navigation_utils.route_to_next_scene(check_tutorial=True)
        else:
            runtime_globals.game_console.log(
                f"[SceneBoot] Server validation failed: {message}")
            from scenes.scene_error import SceneError
            SceneError.set_error(
                message=f"SERVER: {message}",
                action_a=("boot", "Retry"),
                action_b=("switch_free", "Free Mode"),
            )
            change_scene("error")

    def _refresh_pets(self) -> None:
        """Refresh pet data from modules before entering the game scene.

        Reloads evolution data and states, then re-places pets and poops so
        their (absolute pixel) positions are consistent with the current render
        resolution — important when a save written at another resolution is
        loaded (e.g. after a game-mode switch).
        """
        for pet in game_globals.pet_list:
            module = get_module(pet.module)
            pet_data = module.get_monster(pet.name, pet.version)
            if pet_data:
                pet.evolve = pet_data.get("evolve", [])
                pet.temp_evolve = pet_data.get("temporary-evolution") or []
                pet.availability = read_availability(pet_data)
            if pet.state not in ["dead", "hatch", "nap"]:
                pet.set_state("idle")
            pet.patch()
        # Re-place pets (resting Y depends on scale) + scale poops from the
        # resolution the save was written at to the current one.  Runs even
        # with no pets so stray poops are still corrected.
        fix_positions_for_current_resolution()
