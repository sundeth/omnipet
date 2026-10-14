# -*- coding: utf-8 -*-
"""Driving the online scenes for the tests in this folder (not a test file).

Worker threads in the connect views change views and labels themselves, so
the tests never run frames while a worker may still be running: they wait
for its effect first (`wait_for`, a bounded wall-clock poll without frames)
and only then step the game (`env.frames`).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SUPPORT = os.path.join(os.path.dirname(os.path.dirname(HERE)), "support")
if SUPPORT not in sys.path:
    sys.path.insert(0, SUPPORT)

from fake_omninet import wait_for  # noqa: E402,F401


def components(game):
    """Every component of the scene's UI managers (views included)."""
    from harness import managers
    out = []
    for mgr in managers(game.scene):
        out.extend(mgr.components)
    return out


def buttons(game, visible=True):
    from ui.components.button import Button
    return [c for c in components(game) if isinstance(c, Button)
            and (not visible or getattr(c, "visible", True))]


def button(game, text):
    """The visible button whose text is *text* (case-insensitive), or None."""
    want = text.casefold()
    for b in buttons(game):
        if str(getattr(b, "text", "")).casefold() == want:
            return b
    return None


def labels(game):
    """Texts of the visible labels, in order."""
    from ui.components.label import Label
    return [str(getattr(c, "text", "")) for c in components(game)
            if isinstance(c, Label) and getattr(c, "visible", True)]


def tap_button(env, game, text, frames=2):
    """Tap the button labelled *text*; fails loudly when it is missing or
    disabled (a disabled button ignores the tap in the game too)."""
    b = button(game, text)
    if b is None:
        raise AssertionError(f"no visible button {text!r}; have "
                             f"{[getattr(x, 'text', '') for x in buttons(game)]}")
    if not getattr(b, "enabled", True):
        raise AssertionError(f"button {text!r} is disabled")
    env.tap(game, b.rect.center)
    if frames:
        env.frames(game, frames)
    return b


def type_text(game, text):
    """Type *text* into the focused field as a keyboard does (TEXTINPUT)."""
    import pygame
    for ch in text:
        game.scene.handle_event(pygame.event.Event(pygame.TEXTINPUT, text=ch))


def type_into(env, game, field, text, release=True):
    """Tap *field* (a TextInput or CodeEntry) to focus it, type, then tap an
    empty spot so the on-screen keyboard (touch mode) closes again: while it
    is open it covers the buttons at the bottom of the form."""
    pos = field.rect.center
    if hasattr(field, "_get_char_rect"):         # CodeEntry: tap its first box
        box = field._get_char_rect(0)
        pos = (field.rect.x + box.centerx, field.rect.y + box.centery)
    env.tap(game, pos)
    env.frames(game, 1)
    if not getattr(field, "focused", False):
        raise AssertionError(f"tapping {type(field).__name__} did not focus it")
    type_text(game, text)
    if release:
        env.tap(game, (3, 40))
        env.frames(game, 1)
        if getattr(field, "focused", False):
            raise AssertionError("a tap outside did not close the keyboard")


def view(game):
    """The connect scene's current view name, once that view exists.

    SceneConnect._change_view sets the name before it builds the view, and
    workers call it from their own thread: until the new view object is in
    place this answers None (and None on any other scene)."""
    scene = game.scene
    name = getattr(scene, "current_view_name", None)
    current = getattr(scene, "current_view", None)
    if name is None or current is None:
        return None
    expected = {"main_menu": "MainMenuView", "shop": "ShopView", "shop_modules": "ShopModulesView",
                "shop_items": "ShopItemsView", "shop_cosmetics": "ShopCosmeticsView",
                "shop_gameplay": "ShopGameplayView", "shop_specials": "ShopSpecialsView",
                "arena": "ArenaView", "arena_rules": "ArenaRulesView",
                "arena_history": "ArenaHistoryView", "arena_team_creation": "ArenaTeamCreationView",
                "arena_reclaim": "ArenaReclaimView"}.get(name)
    if expected and type(current).__name__ != expected:
        return None
    return name


def scene_name(game):
    return type(game.scene).__name__


def busy_workers():
    """The game's worker threads still running (Python names an unnamed
    thread "Thread-N (target)"; the fake server's own threads are left out)."""
    import threading
    return [t for t in threading.enumerate()
            if t.is_alive() and t is not threading.current_thread()
            and t.name.startswith("Thread-") and "(" in t.name
            and "process_request_thread" not in t.name]


def idle(timeout=5.0):
    """Wait (bounded) until no game worker thread is running."""
    return wait_for(lambda: not busy_workers(), timeout)


def settle(env, game, cond, timeout=10.0, frames=2):
    """Wait (no frames) until *cond* and the workers are done, then step
    *frames*; returns cond()."""
    ok = wait_for(cond, timeout)
    idle()
    if frames:
        env.frames(game, frames)
    return ok


def pump(env, game, cond, max_frames=120):
    """Step frames until *cond* (for effects that need update() to run)."""
    for _ in range(max_frames):
        if cond():
            return True
        env.frames(game, 1)
    return bool(cond())


def progress_mode(env, player_id=None):
    """Progress Mode with the mode preference saved (as after setup)."""
    gg = env.gg
    gg.game_mode = gg.GAME_MODE_PROGRESS
    gg.player_id = player_id
    with_quiet(gg.save_game_mode_preference)


def with_quiet(fn, *a, **k):
    from harness import quiet
    with quiet():
        return fn(*a, **k)


def connect(env, view_name=None, **kwargs):
    """A game on the connect scene, opened on *view_name* when given (as
    `runtime_globals.scene_connect_initial_view` does after a login)."""
    if view_name:
        env.rg.scene_connect_initial_view = (view_name, kwargs) if kwargs else view_name
    game = env.game("connect")
    env.frames(game, 1)
    return game


def tap_row(env, game, shop_list, index):
    """Tap row *index* of a ShopList (or any vertical BaseList)."""
    env.frames(game, 1)                      # items_rect is laid out on draw
    r = shop_list.get_item_rect(index)
    if r is None:
        raise AssertionError(f"list has no row {index}")
    env.tap(game, (shop_list.rect.x + r.centerx, shop_list.rect.y + r.centery))
    env.frames(game, 2)


def tap_pet(env, game, selector, index):
    """Tap cell *index* of a PetSelector (the arena team picker)."""
    env.frames(game, 1)
    bx, by = selector.cell_positions[index]
    mgr = selector.manager
    x = selector.rect.x + (mgr.scale_value(bx) if mgr else bx)
    y = selector.rect.y + (mgr.scale_value(by) if mgr else by)
    env.tap(game, (int(x), int(y)))
    env.frames(game, 1)


def freezer_pets(env):
    """Every pet in the save's freezer file."""
    import pickle
    path = os.path.join(env.gg.get_save_dir(), "freezer.pkl")
    if not os.path.exists(path):
        return []
    with open(path, "rb") as f:
        pages = pickle.load(f) or []
    return [p for page in pages for p in (getattr(page, "pets", None) or [])]


def detail_settled(env, game, shop_view, timeout=10.0):
    """Wait until a shop detail's background sprite fetches (the module
    logo) have landed: a late logo rebuilds the whole detail view."""
    item = shop_view.selected_item
    ok = wait_for(lambda: not getattr(item, "_logo_fetching", False)
                  and not getattr(item, "_sprite_fetching", False), timeout)
    env.frames(game, 1)
    return ok
