import pygame
import time
import os

from core import runtime_globals
import core.constants as constants
from utils.pygame_utils import blit_with_cache, get_font, sprite_load_percent

class WindowClock:
    """
    Displays the current time and a battery icon in the top bar.
    """

    def __init__(self):
        self.font = get_font(runtime_globals.FONT_SIZE_SMALL)
        self.x = int(10 * runtime_globals.UI_SCALE)
        self.y = 0
        self.height = int(22 * runtime_globals.UI_SCALE)
        self.padding = 0

        self.battery_icons = self.load_battery_icons()
        self.current_icon_key = "battery_full"
        self.battery_icon = self.battery_icons.get(self.current_icon_key)
        self.last_battery_update = 0

        self.last_time_update = 0
        self.last_time_string = ""
        self.time_surface = None

        # Persistent bar surface: the whole top bar (black strip + time +
        # battery) is composited here and only re-rendered when the time
        # string or battery icon changes. draw() is then a single small blit,
        # so the scene never needs to rebuild anything clock-related.
        self.bar_surface = pygame.Surface((runtime_globals.SCREEN_WIDTH, self.height))
        self._bar_dirty = True

        self.battery = runtime_globals.i2c  # I2C Battery instance

    def load_battery_icons(self):
        names = [
            "battery_charging",
            "battery_empty",
            "battery_low",
            "battery_half",
            "battery_full"
        ]
        icons = {}
        for name in names:
            try:
                path = os.path.join("assets", f"{name}.png")
                # Use the new sprite loading method, scale to UI bar height, keep proportions
                icons[name] = sprite_load_percent(path, percent=(self.height / runtime_globals.SCREEN_HEIGHT) * 100, keep_proportion=True, base_on="height")
            except Exception:
                runtime_globals.game_console.log(f"⚠️ Failed to load {name}.png")
                icons[name] = None
        return icons

    def select_icon_key(self, percent, charging):
        if charging:
            return "battery_charging"
        elif percent <= 5.0:
            return "battery_empty"
        elif percent <= 33.3:
            return "battery_low"
        elif percent <= 66.7:
            return "battery_half"
        else:
            return "battery_full"

    def update_battery_icon(self):
        now = time.time()
        if now - self.last_battery_update < 5:
            return

        percent, charging = self.battery.get_battery_info()
        icon_key = self.select_icon_key(percent, charging)

        icon = self.battery_icons.get(icon_key)
        if icon is not None:
            self.battery_icon = icon
            self.current_icon_key = icon_key

        self.last_battery_update = now

    def _rebuild_bar(self):
        """Re-composite the bar surface (called only when its content changed)."""
        bar = self.bar_surface
        bar.fill((0, 0, 0))
        if self.time_surface:
            bar.blit(self.time_surface, (self.x, self.padding))
        if self.battery_icon:
            battery_x = runtime_globals.SCREEN_WIDTH - self.battery_icon.get_width() - self.padding
            battery_y = (self.height - self.battery_icon.get_height()) // 2
            bar.blit(self.battery_icon, (battery_x, battery_y))
        self._bar_dirty = False

    def draw(self, surface):
        now = time.time()

        # Only update time string and surface once per second
        if now - self.last_time_update >= 1:
            time_string = time.strftime("%H:%M:%S")
            if time_string != self.last_time_string:
                self.last_time_string = time_string
                self.time_surface = self.font.render(time_string, True, constants.FONT_COLOR_DEFAULT)
                self._bar_dirty = True
            self.last_time_update = now

        # Battery polling is rate-limited internally (5s)
        prev_icon_key = self.current_icon_key
        self.update_battery_icon()
        if self.current_icon_key != prev_icon_key:
            self._bar_dirty = True

        if self._bar_dirty:
            self._rebuild_bar()

        blit_with_cache(surface, self.bar_surface, (0, self.y))
