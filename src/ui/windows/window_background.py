import pygame
import time
import os

from core import runtime_globals, game_globals
from utils.module_utils import get_module
from utils.pygame_utils import blit_with_cache, sprite_load_percent
from utils.asset_utils import resolve_path
from core import constants


class WindowBackground:
    def __init__(self, boot=False):
        self.time_of_day = "day"
        self.image = None
        self.last_check_time = 0
        self.last_background = None
        self.last_module = None
        self.last_image_path = None
        self.center = None
        self.update()
        self.load_sprite(boot)

    def draw(self, surface):
        if self.image:
            #surface.blit(self.image, self.center)
            blit_with_cache(surface, self.image, self.center)

    def update(self):
        now = time.time()

        # Exit early if nothing has changed and we checked recently
        if (game_globals.game_background == self.last_background and
            game_globals.background_module_name == self.last_module and
            now - self.last_check_time < 60):
            return

        self.last_check_time = now

        # Check if we need to reload background
        current_hour = time.localtime().tm_hour
        new_time_of_day = (
            "day" if 6 <= current_hour < 16
            else "dusk" if 16 <= current_hour < 19
            else "night"
        )

        background_changed = (
            game_globals.game_background != self.last_background or
            game_globals.background_module_name != self.last_module
        )
        time_changed = new_time_of_day != self.time_of_day

        if background_changed or time_changed:
            self.time_of_day = new_time_of_day
            self.load_sprite(False)

    #: Always available, and what the login scene shows.
    DEFAULT_BACKGROUND = "assets/Splash.png"

    @staticmethod
    def _safe_module(name):
        """The module, or None — an old save can name one that is gone."""
        if not name:
            return None
        try:
            return get_module(name)
        except Exception:
            return None

    def _paths_for(self, module, name):
        """Candidate files for one background, best first."""
        if module is None or not name:
            return []
        day_night = True
        for bg in getattr(module, "backgrounds", []):
            if bg.get("name") == name:
                day_night = bg.get("day_night", True)
                break
        base = f"bg_{name}{f'_{self.time_of_day}' if day_night else ''}"
        folder = os.path.join(module.folder_path, "backgrounds")
        high = os.path.join(folder, f"{base}_high.png")
        normal = os.path.join(folder, f"{base}.png")
        out = []
        if game_globals.background_high_res and os.path.exists(resolve_path(high)):
            out.append(high)
        out.append(normal)
        # A day/night background whose current slice is missing still has its
        # other slices; better the wrong time of day than no background.
        for slice_name in ("day", "dusk", "night", ""):
            alt = os.path.join(folder, f"bg_{name}{f'_{slice_name}' if slice_name else ''}.png")
            if alt not in out:
                out.append(alt)
        return out

    def _candidates(self, boot):
        """Every background worth trying, in order of preference.

        The saved background first, then anything else the player has unlocked
        (an old save can point at a background a newer build renamed, or at a
        module that is no longer installed), and finally the splash image so
        there is ALWAYS something behind the scene.
        """
        if boot:
            yield self.DEFAULT_BACKGROUND
            return

        name = game_globals.game_background
        module_name = game_globals.background_module_name
        module = self._safe_module(module_name)
        yield from self._paths_for(module, name)

        # Other backgrounds this player has earned, same module first.
        try:
            from utils.utils_unlocks import get_unlocked_backgrounds
            seen = {(module_name, name)}
            ordered = [module_name] + [m for m in runtime_globals.game_modules if m != module_name]
            for mod_name in ordered:
                mod = self._safe_module(mod_name)
                if mod is None:
                    continue
                for bg in get_unlocked_backgrounds(mod_name, getattr(mod, "backgrounds", [])):
                    key = (mod_name, bg.get("name"))
                    if key in seen:
                        continue
                    seen.add(key)
                    yield from self._paths_for(mod, bg.get("name"))
        except Exception as exc:
            runtime_globals.game_console.log(f"[Background] unlock scan failed: {exc}")

        yield self.DEFAULT_BACKGROUND

    def load_sprite(self, boot):
        first = None
        for path in self._candidates(boot):
            if first is None:
                first = path
                # Already showing the preferred background — nothing to do.
                if path == self.last_image_path and self.image is not None:
                    return
            if not os.path.exists(resolve_path(path)):
                continue
            try:
                # Cover the screen, keeping proportions, on both orientations.
                base_on = "width" if runtime_globals.SCREEN_WIDTH >= runtime_globals.SCREEN_HEIGHT else "height"
                self.image = sprite_load_percent(path, percent=100, keep_proportion=True,
                                                 base_on=base_on, alpha=False)
                self.last_background = game_globals.game_background
                self.last_module = game_globals.background_module_name
                self.last_image_path = path
                self.center = self.image.get_rect(
                    center=(runtime_globals.SCREEN_WIDTH // 2, runtime_globals.SCREEN_HEIGHT // 2))
                if path != first:
                    runtime_globals.game_console.log(
                        f"[Background] {first} unavailable, fell back to {path}")
                return
            except Exception as exc:
                runtime_globals.game_console.log(f"[!] Error loading background {path}: {exc}")

        runtime_globals.game_console.log("[!] No background could be loaded at all")
        self.image = None
