"""
Omnipet Virtual Pet - Android Entry Point
"""
import sys
import os

# Add src/ to sys.path.  We try multiple candidates because p4a's __file__
# resolution is inconsistent across bootstraps and emulators.  Bluestacks in
# particular can set a working directory that differs from the APK extraction
# root, so we walk up from __file__ AND from cwd to cover both cases.
_HERE = os.path.dirname(os.path.abspath(__file__)) if __file__ else os.getcwd()
for _candidate in (
    os.path.join(_HERE, 'src'),
    os.path.join(os.path.dirname(_HERE), 'src'),  # one level up from __file__
    os.path.join(os.getcwd(), 'src'),
    os.path.join(os.path.dirname(os.getcwd()), 'src'),
):
    if os.path.isdir(_candidate) and _candidate not in sys.path:
        sys.path.insert(0, _candidate)

# On Bluestacks (and some physical devices) the APK extraction dir differs
# from cwd, so Python's site module never finds sitecustomize.pyc and the
# p4a import hook that enables loading .pyc files from package directories
# is never installed.  We locate and execute it manually here, before any
# game package is imported.
if 'sitecustomize' not in sys.modules:
    import importlib.machinery as _imm
    import importlib.util as _ilu
    _sc_candidates = []
    for _sp in sys.path[:6]:
        if _sp and _sp not in ('.', ''):
            _sc_candidates.append(os.path.join(_sp, 'sitecustomize.pyc'))
            _sc_candidates.append(os.path.join(os.path.dirname(_sp), 'sitecustomize.pyc'))
    _sc_candidates.append(os.path.join(os.getcwd(), 'sitecustomize.pyc'))
    for _sc_path in _sc_candidates:
        try:
            if os.path.exists(_sc_path):
                _loader = _imm.SourcelessFileLoader('sitecustomize', _sc_path)
                _spec = _ilu.spec_from_loader('sitecustomize', _loader)
                _mod = _ilu.module_from_spec(_spec)
                sys.modules['sitecustomize'] = _mod
                _spec.loader.exec_module(_mod)
                print(f"[main_android] sitecustomize loaded from {_sc_path}")
                break
        except Exception as _sc_exc:
            print(f"[main_android] sitecustomize load failed ({_sc_path}): {_sc_exc}")
    del _imm, _ilu, _sc_candidates

# Direct .pyc import hook — works even if sitecustomize.pyc wasn't loaded.
# p4a strips all .py source files from the APK; only .pyc bytecode remains.
# Standard Python 3 can only find .pyc files inside __pycache__/; packages
# in the APK have them directly in the package directory.  This finder
# bridges the gap so every package import succeeds without sitecustomize.
class _PyonlyFinder:
    """Finds .pyc-only packages/modules when no .py source is present."""
    def find_spec(self, fullname, path, target=None):
        import importlib.machinery as _m
        import importlib.util as _u
        name = fullname.rpartition('.')[2]
        for entry in (path if path is not None else sys.path):
            try:
                pkg_dir = os.path.join(entry, name)
                init_pyc = os.path.join(pkg_dir, '__init__.pyc')
                if os.path.isfile(init_pyc):
                    loader = _m.SourcelessFileLoader(fullname, init_pyc)
                    spec = _u.spec_from_loader(fullname, loader, is_package=True)
                    if spec is not None:
                        spec.submodule_search_locations = [pkg_dir]
                    return spec
                mod_pyc = os.path.join(entry, name + '.pyc')
                if os.path.isfile(mod_pyc):
                    loader = _m.SourcelessFileLoader(fullname, mod_pyc)
                    return _u.spec_from_loader(fullname, loader)
            except Exception:
                continue
        return None

if not any(type(f).__name__ == '_PyonlyFinder' for f in sys.meta_path):
    sys.meta_path.append(_PyonlyFinder())
    print(f"[main_android] _PyonlyFinder installed (sitecustomize in modules: "
          f"{'sitecustomize' in sys.modules})")

# --- Android pause behaviour ------------------------------------------------
# SDL's Android event pump blocks the calling thread for the whole time the
# activity is paused (SDL_SemWait on the resume semaphore), and pygame does
# NOT release the GIL around SDL_PumpEvents -- only event.wait() does that.
# So a backgrounded app sits inside pygame.event.get() holding the GIL.
#
# That deadlocks every resume: Activity.onResume() dispatches
# ActivityLifecycleCallbacks.onActivityResumed *before* SDLActivity posts
# nativeResume, so the pyjnius callback runs on Android's UI thread and waits
# for a GIL that only nativeResume can release -- while nativeResume is the
# next thing that same, now-frozen, UI thread was going to do.  The window
# never repaints and no input is delivered: a black, unresponsive app.
#
# It also explains why the app "never received" APP_DIDENTERBACKGROUND: the
# loop was blocked inside the pump, so the event only surfaced after resume.
#
# With the hint off SDL keeps the pump non-blocking, our loop keeps running
# (and keeps releasing the GIL) and the lifecycle events arrive on the main
# thread as they happen.  The app must not draw while paused -- SDL backs the
# EGL context up on the way out -- so the loop below idles instead.  SDL reads
# this once, in Android_CreateDevice, hence before pygame.init().
os.environ.setdefault("SDL_ANDROID_BLOCK_ON_PAUSE", "0")
os.environ["SDL_RENDER_SCALE_QUALITY"] = "0"
import pygame

def main():
    # Initialize pygame
    pygame.init()

    # Use fullscreen with device/native resolution on Android
    try:
        screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    except Exception:
        screen = pygame.display.set_mode((800, 480))

    pygame.display.set_caption("Omnipet")

    try:
        # Import and configure Android environment BEFORE any other game imports
        from core import runtime_globals
        runtime_globals.APP_ROOT = os.getcwd()
        runtime_globals.IS_ANDROID = True
        runtime_globals.INPUT_MODE = runtime_globals.TOUCH_MODE
        from core import game_globals
        game_globals.showClock = False

        # Update runtime resolution based on actual device screen size
        width, height = screen.get_size()

        # Run the game at half the native resolution for performance, then upscale
        game_width  = (width  // 2) & ~1
        game_height = (height // 2) & ~1

        # The configuration is the engine's authority on the render
        # resolution everywhere else, so record what was actually chosen here.
        # Left at the imported default (a 240-based canvas derived from the
        # screen's aspect) the two disagree, and every recompute that reads the
        # configuration -- a save switch, a login, the graphics test -- resets
        # SCREEN_WIDTH/HEIGHT to a value the offscreen canvas cannot follow,
        # drawing the game into a corner of it.  It is also what a save records
        # as the resolution it was written at, which is how the poops are
        # re-placed on the next boot.
        cfg = game_globals.configuration
        cfg.fullscreen = True
        cfg.window_width, cfg.window_height = width, height
        cfg.screen_width, cfg.screen_height = game_width, game_height
        cfg.base_resolution_width, cfg.base_resolution_height = game_width, game_height
        cfg.resolution_multiplyer = 1

        # Update runtime globals to use the game's internal resolution (half)
        runtime_globals.update_resolution_constants(game_width, game_height)

        # Create an offscreen surface at game resolution to render into.
        # Published as runtime_globals.render_surface so a live render-res
        # change (display_utils.apply_render_multiplier rebuilds the canvas)
        # is picked up by the loop below -- otherwise the game keeps drawing
        # into this stale-size surface and only fills part of the screen.
        offscreen = pygame.Surface((game_width, game_height))
        runtime_globals.render_surface = offscreen

        # Now import game after environment is configured
        from vpet import VirtualPetGame
        game = VirtualPetGame()

        # Background service controller
        from services import android_background_service as bg_service

        # If a previous session left the service running, stop it now.
        bg_service.stop_service()

        # Notifications are disabled for now (service_main.NOTIFICATIONS_ENABLED),
        # so don't ask for POST_NOTIFICATIONS — prompting for a permission the
        # build never uses only costs the player a dialog. Restore this call
        # alongside the background-service work.

        # SDL2 lifecycle events on Android.  SDL sends the APP_* pair on every
        # pause/resume; the WINDOW_* ones come straight out of nativePause /
        # nativeResume and act as a backstop on devices that route the APP_*
        # events differently.
        def _events(*names):
            return tuple(ev for ev in (getattr(pygame, n, None) for n in names)
                         if ev is not None)

        BACKGROUND_EVENTS = _events(
            "APP_WILLENTERBACKGROUND", "APP_DIDENTERBACKGROUND",
            "WINDOWMINIMIZED", "WINDOWHIDDEN")
        FOREGROUND_EVENTS = _events(
            "APP_WILLENTERFOREGROUND", "APP_DIDENTERFOREGROUND",
            "WINDOWRESTORED", "WINDOWSHOWN")
        APP_TERMINATING = getattr(pygame, "APP_TERMINATING", None)

        # Main game loop
        clock = pygame.time.Clock()
        running = True
        paused = False           # activity backgrounded: don't tick, don't draw
        service_running = False  # the background service owns the save file
        present_failures = 0
        last_periodic_save = pygame.time.get_ticks()
        _last_frame_ticks = None  # None skips the gap check on the first iteration
        PERIODIC_SAVE_MS = 30_000
        PAUSED_IDLE_MS = 250
        # ~2 s of failed frames at 30 fps before we assume SDL's window is
        # genuinely gone rather than momentarily unavailable.
        PRESENT_FAILURES_BEFORE_REACQUIRE = 60

        # Set from the JVM UI thread by the lifecycle callbacks below.
        _lifecycle = {"pause": False, "resume": False}

        def _enter_background():
            """Save, hand the pets to the service, and stop drawing."""
            nonlocal paused, service_running
            if paused:
                return
            paused = True
            try:
                game.save()
            except Exception as save_exc:
                print(f"[main_android] save() on pause failed: {save_exc}")
            try:
                service_running = bool(bg_service.start_service())
            except Exception as svc_exc:
                print(f"[main_android] start_service() failed: {svc_exc}")
                service_running = False
            print(f"[main_android] backgrounded (service: {service_running})")

        def _leave_background():
            """Take the pets back from the service and resume drawing."""
            nonlocal paused, service_running, present_failures
            if not paused and not service_running:
                return  # not a resume -- window event during normal play
            paused = False
            present_failures = 0
            try:
                bg_service.stop_service()
            except Exception as exc:
                print(f"[main_android] stop_service() failed: {exc}")
            if service_running:
                # Only worth re-reading the save when the service was the one
                # advancing it; game_globals.load() replaces every pet object.
                service_running = False
                try:
                    bg_service.reload_state_from_disk()
                except Exception as rel_exc:
                    print(f"[main_android] reload_state_from_disk failed: {rel_exc}")
            print("[main_android] foregrounded")

        # These run on Android's UI thread and must stay one assignment long.
        # Anything heavier (a save, a JNI call, an import) blocks the UI thread
        # inside onPause/onResume waiting for the GIL -- see the note at the
        # top of this file.  The real work happens on the main thread below.
        def _on_pause_from_jvm():
            _lifecycle["pause"] = True

        def _on_resume_from_jvm():
            _lifecycle["resume"] = True

        # Install Android-native lifecycle callbacks.
        bg_service.install_lifecycle_hooks(
            on_pause=_on_pause_from_jvm,
            on_resume=_on_resume_from_jvm,
        )

        while running:
            # --- Lifecycle signals raised on the JVM thread ---
            if _lifecycle["pause"]:
                _lifecycle["pause"] = False
                _enter_background()
            if _lifecycle["resume"]:
                _lifecycle["resume"] = False
                _leave_background()

            # --- Suspension gap detection (resume fallback) ---
            # A tick jump while we believed ourselves to be in the foreground
            # means the OS froze the process without any lifecycle event
            # reaching us.  Only checked when not paused: a frozen *paused*
            # process is normal, and resuming on that would start drawing
            # into a backed-up EGL context.
            _now_ticks = pygame.time.get_ticks()
            if (not paused and _last_frame_ticks is not None
                    and _now_ticks - _last_frame_ticks > 3000):
                _leave_background()
            _last_frame_ticks = _now_ticks

            for event in pygame.event.get():
                if event.type in BACKGROUND_EVENTS:
                    _enter_background()
                    continue
                if event.type in FOREGROUND_EVENTS:
                    _leave_background()
                    continue
                if event.type == pygame.QUIT:
                    running = False
                elif APP_TERMINATING is not None and event.type == APP_TERMINATING:
                    # Can arrive while paused, so it is handled before the
                    # backgrounded check below.
                    _enter_background()
                    running = False
                elif paused:
                    continue  # backgrounded: nothing else is worth handling
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    running = False
                else:
                    game.handle_event(event)

            if paused:
                # The service is ticking the pets; touching the GL surface
                # here would blank or crash it.  Idle instead -- time.wait()
                # releases the GIL, which is what keeps the JVM lifecycle
                # callbacks above (and Android's UI thread) responsive.
                pygame.time.wait(PAUSED_IDLE_MS)
                _last_frame_ticks = pygame.time.get_ticks()
                continue

            game.update()

            # Periodic auto-save while running.
            now = pygame.time.get_ticks()
            if now - last_periodic_save >= PERIODIC_SAVE_MS:
                try:
                    game.save()
                except Exception as save_exc:
                    print(f"[main_android] periodic save() failed: {save_exc}")
                last_periodic_save = now

            # Render the game into the internal canvas.  Read it from
            # runtime_globals each frame: a live Render Res change replaces
            # the canvas with one at the new internal resolution.
            canvas = runtime_globals.render_surface
            if canvas is None:
                canvas = runtime_globals.render_surface = offscreen

            try:
                game.draw(canvas, clock)
                sw, sh = screen.get_size()
                if sw <= 0 or sh <= 0:
                    raise pygame.error(f"zero-size window surface ({sw}x{sh})")
                # When the canvas IS the window surface (a render
                # resolution equal to the device's), the frame is already
                # where it has to be -- filling or blitting here would erase
                # what was just drawn.
                if canvas is not screen:
                    screen.fill((0, 0, 0))
                    if canvas.get_size() != (sw, sh):
                        pygame.transform.scale(canvas, (sw, sh), screen)
                    else:
                        screen.blit(canvas, (0, 0))
                pygame.display.flip()
                present_failures = 0
            except pygame.error as draw_exc:
                # SDL's window surface went away without a lifecycle event we
                # recognised.  It normally comes back on its own, so retry the
                # frame; only re-acquire the display once it clearly hasn't.
                present_failures += 1
                if present_failures == 1:
                    print(f"[main_android] frame present failed: {draw_exc}")
                if present_failures >= PRESENT_FAILURES_BEFORE_REACQUIRE:
                    present_failures = 0
                    try:
                        canvas_was_display = runtime_globals.render_surface is screen
                        screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
                        if canvas_was_display:
                            # The canvas aliased the old window surface --
                            # rebuild it against the new display.
                            from utils import display_utils
                            display_utils._rebuild_render_surface()
                        print(f"[main_android] display re-acquired at "
                              f"{screen.get_size()}")
                    except Exception as disp_exc:
                        print(f"[main_android] display re-acquire failed: {disp_exc}")
            clock.tick(game_globals.configuration.frame_rate)

        game.save()

        # Foreground loop is exiting (user quit or OS terminating). Hand
        # ticking off to the background service so pets keep advancing.
        try:
            bg_service.start_service()
        except Exception as bg_exc:
            print(f"[main_android] Failed to start background service on exit: {bg_exc}")

    except Exception as e:
        # Show error screen with crash info + diagnostic data for debugging
        import traceback
        font = pygame.font.Font(None, 32)

        tb_text = traceback.format_exc()
        error_lines = [
            "Oops, the game crashed!",
            "",
            str(e)[:70],
            "",
            f"cwd: {os.getcwd()[:65]}",
            f"file: {(str(__file__) if __file__ else 'None')[:65]}",
        ]
        for i, p in enumerate(sys.path[:4]):
            error_lines.append(f"path[{i}]: {str(p)[:65]}")
        sc_ok = 'sitecustomize' in sys.modules
        hook_ok = any(type(f).__name__ == '_PyonlyFinder' for f in sys.meta_path)
        error_lines.append(f"sc:{sc_ok} hook:{hook_ok}")
        error_lines.append("")
        error_lines.extend(tb_text.split('\n'))

        # Touch dismisses the crash screen too -- on a phone there is no key
        # to press, and a screen that ignores every tap is indistinguishable
        # from a hung app.
        DISMISS_EVENTS = (pygame.QUIT, pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN,
                          pygame.FINGERDOWN)

        running = True
        while running:
            for event in pygame.event.get():
                if event.type in DISMISS_EVENTS:
                    running = False

            screen.fill((120, 0, 0))  # Dark red background
            y = 10
            for line in error_lines[:30]:
                text = font.render(line[:70], True, (255, 255, 255))
                screen.blit(text, (10, y))
                y += 28

            pygame.display.flip()
            clock = pygame.time.Clock()
            clock.tick(30)

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
