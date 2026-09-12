"""
Display utilities
=================

Window-size / internal-resolution management for the desktop builds.

The game renders to an internal canvas (``runtime_globals.render_surface``) at
the *internal resolution* and the main loop scales that canvas onto the actual
OS window every frame.  This lets the output window size differ from the render
resolution: in windowed mode the player can pick a window size and the canvas
is scaled to fit.

Resolution model
----------------
* **Window size** — the size of the OS window (the "output").  In fullscreen
  it equals the screen and cannot be changed; in windowed mode the player
  picks one of :data:`WINDOW_SIZE_PRESETS` (minimum 120x120 — the canvas is
  scaled, so small windows are fine).
* **Internal resolution** — what every game component renders at.  Its 1x base
  matches the window's aspect ratio with neither side below 240
  (``GameConfiguration.compute_base_resolution``); the 1x-4x "Render Res"
  multiplier scales it up.
"""

import pygame

from core import runtime_globals, game_globals


# Window-size presets offered in windowed mode.  Mostly square, plus a few
# wider 4:3 / 16:9 options.  Filtered against the desktop size at runtime so we
# never offer a window larger than the monitor.
WINDOW_SIZE_PRESETS = [
    (240, 240), (360, 360), (480, 480), (600, 600), (640, 640),
    (720, 720), (840, 840), (960, 960), (1080, 1080),
    (320, 240), (640, 480), (800, 600), (960, 540),
    (1280, 720), (1600, 900), (1920, 1080),
]


def get_desktop_size():
    """Best-effort desktop resolution (used to filter the preset list)."""
    try:
        sizes = pygame.display.get_desktop_sizes()
        if sizes:
            return sizes[0]
    except Exception:
        pass
    try:
        info = pygame.display.Info()
        if info.current_w > 0 and info.current_h > 0:
            return (info.current_w, info.current_h)
    except Exception:
        pass
    return (1920, 1080)


def available_window_presets():
    """Window-size presets that fit on the desktop, plus the current size.

    Sorted by area then width so the cycle goes small -> large.
    """
    dw, dh = get_desktop_size()
    cfg = game_globals.configuration
    presets = [(w, h) for (w, h) in WINDOW_SIZE_PRESETS if w <= dw and h <= dh]
    cur = (cfg.window_width, cfg.window_height)
    presets.append(cur)
    presets = sorted(set(presets), key=lambda s: (s[0] * s[1], s[0]))
    return presets


def _display_flags():
    cfg = game_globals.configuration
    flags = 0
    if cfg.fullscreen:
        flags |= pygame.FULLSCREEN | pygame.DOUBLEBUF
    return flags


def _invalidate_scaled_caches():
    """Drop sprite caches built for the previous render scale so the pets,
    poops and misc UI sprites are rebuilt at the new internal resolution."""
    runtime_globals.pet_sprites = {}
    try:
        from utils.pygame_utils import load_misc_sprites, clear_sprite_folder_cache
        clear_sprite_folder_cache()
        runtime_globals.misc_sprites = load_misc_sprites()
    except Exception as exc:
        runtime_globals.game_console.log(
            f"[Display] misc sprite reload failed: {exc}")


def _rebuild_render_surface():
    """Point ``runtime_globals.render_surface`` at a canvas of the current
    internal resolution and refresh the UI scaling constants.

    When the window already matches the internal resolution the window surface
    is used directly (no per-frame scaling); otherwise a dedicated canvas is
    created and the main loop scales it onto the window.
    """
    cfg = game_globals.configuration
    runtime_globals.update_resolution_constants(cfg.screen_width, cfg.screen_height)
    display = pygame.display.get_surface()
    internal = (cfg.screen_width, cfg.screen_height)
    if display is not None and display.get_size() == internal:
        runtime_globals.render_surface = display
    else:
        runtime_globals.render_surface = pygame.Surface(internal)
    # The render scale may have changed; reload sprites cached at the old size.
    _invalidate_scaled_caches()


def ensure_render_surface_matches():
    """Guarantee the render canvas is the size the scaling constants claim.

    The game draws SCREEN_WIDTH x SCREEN_HEIGHT pixels into
    ``runtime_globals.render_surface``; when the two disagree it draws into a
    corner of a canvas that is then upscaled whole, so the game appears in the
    top-left of the screen over the stale remains of the previous frame.  That
    is what a save switch did on Android, where the canvas is chosen from the
    device screen before any save has been read.  Rebuilding is cheap next to
    getting it wrong, but it drops the scaled sprite caches, so only do it when
    the sizes really differ.
    """
    cfg = game_globals.configuration
    surface = getattr(runtime_globals, 'render_surface', None)
    if surface is not None and surface.get_size() == (cfg.screen_width, cfg.screen_height):
        return
    _rebuild_render_surface()


def _reposition_entities(old_w, old_h):
    """Refresh pet/poop positions baked at the previous render scale."""
    try:
        from utils.pet_utils import reposition_for_resolution
        reposition_for_resolution(old_w, old_h)
    except Exception as exc:
        runtime_globals.game_console.log(f"[Display] reposition failed: {exc}")


def apply_window_size(window_w, window_h, reposition=True):
    """Resize the OS window (windowed mode) and rescale the canvas live.

    Recomputes the internal render resolution proportional to the new window,
    recreates ``runtime_globals.render_surface`` and updates the runtime
    scaling constants + input mouse mapping.

    Returns ``True`` if the internal resolution changed, so the caller can
    rebuild its scene to pick up the new UI scale.  Does nothing in fullscreen
    (the window is locked to the screen there).

    ``reposition`` updates existing pets/poops to the new scale; skip it at
    boot (the boot scene already re-places pets after the config loads).
    """
    cfg = game_globals.configuration
    if cfg.fullscreen:
        return False

    window_w = max(120, int(window_w))
    window_h = max(120, int(window_h))

    old_internal = (cfg.screen_width, cfg.screen_height)
    cfg.window_width = window_w
    cfg.window_height = window_h
    cfg.recompute_internal_resolution()

    try:
        pygame.display.set_mode((window_w, window_h), _display_flags())
    except Exception as exc:
        runtime_globals.game_console.log(f"[Display] set_mode failed: {exc}")
        return False

    _rebuild_render_surface()

    inp = getattr(runtime_globals, 'game_input', None)
    if inp is not None:
        inp.display_width = window_w
        inp.display_height = window_h

    changed = (cfg.screen_width, cfg.screen_height) != old_internal
    if reposition:
        if changed:
            # Internal resolution changed: re-place pets (their resting Y
            # depends on scale) and poops (X scaled, Y re-seated on the ground).
            _reposition_entities(*old_internal)
        else:
            # Window-only change: pets are fine, but still re-seat the poops on
            # the ground plane in case their Y was stale.
            try:
                from utils.pet_utils import align_poops_to_ground
                align_poops_to_ground(old_internal[0])
            except Exception:
                pass

    try:
        game_globals.save()
    except Exception:
        pass

    runtime_globals.game_console.log(
        f"[Display] Window {window_w}x{window_h}, "
        f"render {cfg.screen_width}x{cfg.screen_height}")
    return changed


def apply_render_multiplier(multiplier):
    """Apply a new 1x-4x render multiplier, recomputing the internal resolution.

    Works in both windowed (internal scales relative to the window) and
    fullscreen (internal scales relative to the native screen) modes.  Returns
    ``True`` if the internal resolution changed.
    """
    cfg = game_globals.configuration
    cfg.resolution_multiplyer = max(1, min(4, int(round(multiplier))))

    if not cfg.fullscreen:
        return apply_window_size(cfg.window_width, cfg.window_height)

    # Fullscreen: window stays the native screen; only the canvas changes.
    old_internal = (cfg.screen_width, cfg.screen_height)
    display = pygame.display.get_surface()
    win_w, win_h = display.get_size() if display else (cfg.window_width, cfg.window_height)
    if runtime_globals.IS_ANDROID:
        # Android's 1x is the half-native canvas main_android picked from the
        # device screen, not a 240-based one, so the base is kept rather than
        # recomputed -- deriving it from the window here would make 2x
        # *smaller* than 1x.  It is also already a large surface, so the
        # multiplier is held to what the screen's own pixels can justify.
        bw, bh = cfg.base_resolution_width, cfg.base_resolution_height
        while cfg.resolution_multiplyer > 1 and (
                bw * cfg.resolution_multiplyer > win_w
                or bh * cfg.resolution_multiplyer > win_h):
            cfg.resolution_multiplyer -= 1
    else:
        bw, bh = cfg.compute_base_resolution(win_w, win_h)
        cfg.base_resolution_width, cfg.base_resolution_height = bw, bh
    cfg.screen_width = bw * cfg.resolution_multiplyer
    cfg.screen_height = bh * cfg.resolution_multiplyer
    _rebuild_render_surface()
    changed = (cfg.screen_width, cfg.screen_height) != old_internal
    if changed:
        _reposition_entities(*old_internal)
    try:
        game_globals.save()
    except Exception:
        pass
    return changed


# Display fields that describe the device's output, not per-save gameplay.
# They live in each save's configuration but must not change just because the
# player switched to another save (game mode).
_DISPLAY_CONFIG_FIELDS = (
    "screen_width", "screen_height",
    "window_width", "window_height",
    "resolution_multiplyer",
    "base_resolution_width", "base_resolution_height",
    "fullscreen",
)


def _snapshot_display_config():
    cfg = game_globals.configuration
    return {f: getattr(cfg, f) for f in _DISPLAY_CONFIG_FIELDS}


def _restore_display_config(snapshot):
    cfg = game_globals.configuration
    for f, v in snapshot.items():
        setattr(cfg, f, v)


def load_preserving_display():
    """Load the active save while keeping the current screen/render resolution.

    Display settings are device-global, but they are stored in each save's
    configuration — so switching saves (a game-mode change) would otherwise
    jump to the other save's resolution, leaving its pets off-screen and its
    poops misplaced.  We carry the live display config across the load and
    re-place the loaded save's pets/poops for the kept resolution.
    """
    snap = _snapshot_display_config()
    game_globals.load()
    # Resolution the freshly-loaded entities were saved at (before we restore).
    old_w = game_globals.configuration.screen_width
    old_h = game_globals.configuration.screen_height
    _restore_display_config(snap)
    runtime_globals.update_resolution_constants(
        game_globals.configuration.screen_width,
        game_globals.configuration.screen_height)
    ensure_render_surface_matches()
    # Re-place the loaded pets/poops for the carried resolution.
    try:
        from utils.pet_utils import reposition_for_resolution
        reposition_for_resolution(old_w, old_h)
    except Exception as exc:
        runtime_globals.game_console.log(
            f"[Display] reposition after mode switch failed: {exc}")
    # Persist the carried display + corrected positions into this save.
    try:
        game_globals.save()
    except Exception:
        pass


def load_keeping_device_display():
    """Load the active save at boot, keeping the display the device decided on.

    The display fields live in every save but describe whichever device wrote
    it, and the window is already open by the time a save is read.  On Android
    the render resolution comes from the device screen (main_android), so a
    save written on another machine -- or on this one before that resolution
    was recorded -- would replace it with one the canvas cannot follow.

    Nothing is repositioned or saved here: the boot scene re-places the pets
    and poops once the display is final, and it needs
    ``runtime_globals.save_render_resolution`` (set by the load, deliberately
    left alone) to know what the save's coordinates were written against.
    """
    snap = _snapshot_display_config()
    game_globals.load()
    _restore_display_config(snap)
    runtime_globals.update_resolution_constants(
        game_globals.configuration.screen_width,
        game_globals.configuration.screen_height)
    ensure_render_surface_matches()


def reconcile_window_from_config():
    """Re-apply the saved window size once the configuration has been loaded.

    The window is created at launch with default config (the per-player save
    isn't loaded yet), so the saved window size is applied here afterwards so a
    restart honours it.  In fullscreen the window is locked to the screen, so
    only the canvas is reconciled; on Android the device's own resolution wins
    and the save's is carried across instead (load_keeping_device_display).
    """
    from core import runtime_globals
    cfg = game_globals.configuration
    if runtime_globals.IS_ANDROID:
        return
    if cfg.fullscreen:
        # The window is the screen and cannot be resized, but the canvas was
        # created from the pre-load configuration -- make it follow whatever
        # render resolution the save turned out to carry.  A no-op when the
        # save was written on this screen, which is the ordinary case.
        ensure_render_surface_matches()
        return
    # Skip the pet/poop reposition here — the boot scene re-places pets right
    # after the configuration loads.
    apply_window_size(cfg.window_width, cfg.window_height, reposition=False)


def present(display=None):
    """Scale the internal render canvas onto the window and flip.

    Call once per frame after drawing to ``runtime_globals.render_surface``.
    Handles both fullscreen (canvas -> native screen) and windowed window
    sizes that differ from the render resolution.  When the canvas *is* the
    window surface (1:1) it simply flips.
    """
    render = runtime_globals.render_surface
    if display is None:
        display = pygame.display.get_surface()
    if render is not None and display is not None and render is not display:
        if render.get_size() != display.get_size():
            pygame.transform.scale(render, display.get_size(), display)
        else:
            display.blit(render, (0, 0))
    pygame.display.flip()
