import pygame
from ui.ui_constants import TEXT_FONT
import core.constants as constants
import core.runtime_globals as runtime_globals
from utils.asset_utils import font_load
from utils.pygame_utils import blit_with_shadow, get_font


class GameMessage:
    def __init__(self):
        self.messages = []  # Floating messages: [surface, [x, y], alpha, dy]
        self.slide_queue = []  # List of (text, color); layout is per-draw
        self.current_slide = None  # Current sliding message data
        self.slide_timer = 0
        self.slide_duration = constants.FRAME_RATE * 2  # 2 seconds at 30fps
        self.slide_speed = 6 * (30 / constants.FRAME_RATE)  # Pixels per frame

    def add(self, text: str, pos: tuple[int, int], color: tuple[int, int, int], font_size=None):
        font = font_load(TEXT_FONT, font_size)
        surface = font.render(text, True, color).convert_alpha()
        self.messages.append([surface, list(pos), 255, 0])

    def add_slide(self, text: str, color: tuple[int, int, int], y: int = None, font_size=None):
        """Queue a sliding alert message.

        The y / font_size arguments are kept for API compatibility but are
        standardized by the component: slides always render right below the
        top menu icons in the regular UI text size (callers were passing a
        mix of large fonts and positions that covered the screen).

        Only the text and colour are stored. The position and size are worked
        out when the slide is actually drawn (see _slide_layout), because a
        slide can be queued long before it is shown — a module that fails to
        load does so during startup, before the saved display settings have
        been applied, and then appears on the main game screen at a different
        resolution entirely. Snapshotting the layout here is what made those
        errors come out at the wrong size and in the wrong place while
        unlocks, which are queued during play, looked correct.
        """
        self.slide_queue.append((text, color))

    @staticmethod
    def _slide_layout():
        """Where a slide sits and how big it is, at the CURRENT resolution."""
        from core import game_globals
        icons_top = (20 if game_globals.showClock else 5) * runtime_globals.UI_SCALE
        y = int(icons_top + 2 * runtime_globals.MENU_ICON_SIZE
                + 2 * runtime_globals.UI_SCALE)
        return y, runtime_globals.FONT_SIZE_SMALL  # the regular UI text size

    def update(self):
        if not self.messages and not self.current_slide and not self.slide_queue:
            return

        # === Floating Messages ===
        updated_messages = []
        for surf, pos, alpha, dy in self.messages:
            dy += 0.5 * (30 / constants.FRAME_RATE)
            alpha -= 5 * (30 / constants.FRAME_RATE)
            if alpha > 0:
                surf.set_alpha(alpha)
                updated_messages.append([surf, [pos[0], pos[1] - dy], alpha, dy])
        self.messages = updated_messages

        # === Slide Messages ===
        if self.current_slide:
            surf, pos, alpha = self.current_slide
            # Messages that fit on screen stop centered; longer messages keep
            # scrolling until their end is visible, so the whole text can be
            # read before the hold + fade.
            sw = runtime_globals.SCREEN_WIDTH
            margin = int(4 * runtime_globals.UI_SCALE)
            if surf.get_width() <= sw:
                target_x = (sw - surf.get_width()) // 2
            else:
                target_x = sw - surf.get_width() - margin
            if pos[0] > target_x:
                pos[0] -= self.slide_speed
            else:
                self.slide_timer += 1
                if self.slide_timer > self.slide_duration:
                    alpha -= 10
                    if alpha <= 0:
                        self.current_slide = None
                        self.slide_timer = 0
                        return
            surf.set_alpha(alpha)
            self.current_slide = (surf, pos, alpha)
        elif self.slide_queue:
            text, color = self.slide_queue.pop(0)
            y, font_size = self._slide_layout()
            font = get_font(font_size)
            surf = font.render(text, True, color).convert_alpha()
            start_x = runtime_globals.SCREEN_WIDTH  # Start off-screen
            surf.set_alpha(255)
            self.current_slide = (surf, [start_x, y], 255)
            self.slide_timer = 0

    def draw(self, surface: pygame.Surface):
        # Floating messages
        for surf, pos, _, _ in self.messages:
            blit_with_shadow(surface, surf, pos)

        # Slide message
        if self.current_slide:
            surf, pos, _ = self.current_slide
            blit_with_shadow(surface, surf, pos)
