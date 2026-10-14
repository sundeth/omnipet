"""
Skip Overlay
=============

Tiny touch-only "SKIP" pill that scenes can draw in the top-right
corner without standing up a full UIManager.  Used by SceneBoot and
SceneTutorial so touchscreen players have an obvious way to advance
past the splash / step-by-step lesson.

The overlay is positioned below the main-game menu icon strip so it
doesn't cover up tutorial highlights that live near the top of the
screen, and it is only visible / clickable when
``runtime_globals.INPUT_MODE == TOUCH_MODE`` (or IS_ANDROID) — on
keyboard / mouse / GPIO setups it draws nothing and consumes nothing.

Usage:

    self._skip = SkipOverlay(on_skip=self._handle_skip)
    ...
    def draw(self, surface):
        ...
        self._skip.draw(surface)

    def handle_event(self, event):
        if self._skip.handle_event(event):
            return
        ...
"""

import pygame

from core import runtime_globals


# Base position in 240x240 coordinates — top-right but well below the
# main-game top icon row (~y=10..25) so it doesn't overlap.
_BASE_X = 200
_BASE_Y = 40
_BASE_W = 36
_BASE_H = 18


class SkipOverlay:
    def __init__(self, on_skip, label: str = "SKIP"):
        self.on_skip = on_skip
        self.label = label

    @staticmethod
    def _is_touch() -> bool:
        return (
            runtime_globals.IS_ANDROID
            or runtime_globals.INPUT_MODE == runtime_globals.TOUCH_MODE
        )

    def _rect(self):
        scale = runtime_globals.UI_SCALE or 1
        return pygame.Rect(
            int(_BASE_X * scale),
            int(_BASE_Y * scale),
            int(_BASE_W * scale),
            int(_BASE_H * scale),
        )

    def draw(self, surface: pygame.Surface) -> None:
        if not self._is_touch():
            return
        rect = self._rect()
        # Translucent pill so it sits over any backdrop without dominating
        pill = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        pygame.draw.rect(pill, (0, 0, 0, 170), pill.get_rect(),
                         border_radius=int(rect.height // 2))
        pygame.draw.rect(pill, (240, 240, 240, 220), pill.get_rect(),
                         width=max(1, int(runtime_globals.UI_SCALE)),
                         border_radius=int(rect.height // 2))
        surface.blit(pill, rect.topleft)

        font_size = max(10, int(11 * runtime_globals.UI_SCALE))
        from utils.asset_utils import font_load
        font = font_load(None, font_size)
        text = font.render(self.label, True, (240, 240, 240))
        text_rect = text.get_rect(center=rect.center)
        surface.blit(text, text_rect)

    def handle_event(self, event) -> bool:
        """Consume an LCLICK / TAP inside the pill; return True if so."""
        if not self._is_touch():
            return False
        if not isinstance(event, tuple) or len(event) != 2:
            return False
        event_type, event_data = event
        if event_type != "LCLICK" or not event_data or "pos" not in event_data:
            return False
        if self._rect().collidepoint(event_data["pos"]):
            runtime_globals.game_sound.play("menu")
            try:
                self.on_skip()
            except Exception as exc:
                runtime_globals.game_console.log(
                    f"[SkipOverlay] on_skip raised: {exc}")
            return True
        return False
