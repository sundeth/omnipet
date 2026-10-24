"""
XAI Bar minigame (DMX ruleset)
==============================

Sprite-based implementation. The bar art is picked from the pet:

    assets/XaiBar_<type>_<level>.png   (96x30 source art)

    type:  pet attribute — Va -> 1, ""(Free)/Da -> 2, Vi -> 3
    level: pets whose module shows Level as a stat take the band their
           STAGE and LEVEL put them in, read off the DMX attack table
           (battle_utils.dmx_tier_index); everyone else uses EFFORT:
               EFFORT 0-8 -> 1,  9-15 -> 2,  16+ -> 3

           The bar widens where the attacks change row, and both were read
           off the same device: a stage 6 pet steps at levels 5 and 10, but a
           stage 3 pet steps at 3 and 4, and a Baby II at 2 and 3. A flat
           `0-5 / 6-9 / 10` was stage 6's banding applied to every stage, so
           every pet below Ultimate got the wrong bar for most of its life.

The bar is integer-scaled (pixel perfect) to roughly the old widget's
footprint (148px wide at 240x240). XaiArrow travels left-to-right above
the bar, bouncing inside the bar's bounds minus a 2px (source) margin,
at the classic speed (faster for lower XAI numbers). A/LCLICK stops it;
the color of the bar under the middle of the arrow decides the result
and recolors the arrow, and the minigame reports finished half a second
later so the player sees where they landed.

The color is the charge quality the protocols carry as Bad (0), Good (1),
Great (2), Excellent (3):

    red     -> 3  Excellent      the smallest zone, and the hardest to hit
    yellow  -> 2  Great
    blue    -> 1  Good           the widest colored zone
    grey    -> 0  Bad

Red and blue used to be the other way round, which inverted the whole
minigame: a level 1 bar carries 24px of blue against 6px of red, so
stopping on the hardest zone scored Good and the easiest scored
Excellent. Every consumer reads this one number -- the DMX wire's Attack
field and Excite Training's ``selected_strength == 3`` alike -- so the
sprite table below is keyed by it rather than by the color name.

Result mapping: red=1, yellow=2, blue=3, anything else 0.
"""

import pygame

from core import runtime_globals
from utils.asset_utils import image_load
from utils.pygame_utils import blit_with_cache

BAR_SRC_W = 96
BAR_SRC_H = 30
BAR_MARGIN_SRC = 2       # px margin inside the bar (source scale)
REFERENCE_WIDTH = 148    # old widget width at 240x240 — sizing reference
STOP_HOLD_MS = 500       # linger after stopping so the result is readable

#: What each result value is called on the wire, for the log.
QUALITY = ("Bad", "Good", "Great", "Excellent")

#: Keyed by result value, not by color name (see above).
ARROW_SPRITES = {
    None: "assets/XaiArrow.png",
    3: "assets/XaiArrow_Red.png",
    2: "assets/XaiArrow_Yellow.png",
    1: "assets/XaiArrow_Blue.png",
}


def _classify_color(pixel):
    """Map a bar pixel to its result value: red 3, yellow 2, blue 1, None."""
    if len(pixel) > 3 and pixel[3] < 200:
        return None
    r, g, b = pixel[0], pixel[1], pixel[2]
    if r > 180 and g > 140 and b < 100:
        return 2  # yellow -> Great
    if r > 180 and g < 110 and b < 110:
        return 3  # red    -> Excellent
    if b > 180 and r < 110:
        return 1  # blue   -> Good
    return None


class XaiBar:
    """XAI bar minigame for the DMX ruleset."""

    def __init__(self, x, y, xai_number, pet):
        # x is kept for API compatibility; the widget centers itself so the
        # pixel-perfect scaled bar always sits nicely regardless of caller.
        self.xai_number = xai_number
        self.pet = pet

        # Integer scale approximating the old 148/240 footprint
        target_w = runtime_globals.SCREEN_WIDTH * (REFERENCE_WIDTH / 240.0)
        self.scale = max(1, round(target_w / BAR_SRC_W))

        bar_type = self._bar_type(pet)
        bar_level = self._bar_level(pet)
        self.bar_name = f"XaiBar_{bar_type}_{bar_level}"
        self._last_src_x = None
        self.bar_source = image_load(
            f"assets/{self.bar_name}.png").convert_alpha()

        k = self.scale
        self.width = BAR_SRC_W * k
        self.height = BAR_SRC_H * k
        self.bar_sprite = pygame.transform.scale(self.bar_source,
                                                 (self.width, self.height))

        self.x = (runtime_globals.SCREEN_WIDTH - self.width) // 2
        self.y = y

        # Arrow sprites at the same integer scale as the bar
        self.arrow_sprites = {}
        for key, path in ARROW_SPRITES.items():
            try:
                sprite = image_load(path).convert_alpha()
                self.arrow_sprites[key] = pygame.transform.scale(
                    sprite, (sprite.get_width() * k, sprite.get_height() * k))
            except Exception as exc:
                runtime_globals.game_console.log(f"[XaiBar] arrow load failed {path}: {exc}")
        self.arrow_sprite = self.arrow_sprites.get(None)
        arrow_h = self.arrow_sprite.get_height() if self.arrow_sprite else 8 * k

        # Arrow rides just above the bar (outside it)
        self.arrow_y = self.y - arrow_h - 2 * k

        # The arrow CENTER travels within the bar minus the 2px source margin
        margin = BAR_MARGIN_SRC * k
        self.arrow_min_cx = self.x + margin
        self.arrow_max_cx = self.x + self.width - margin

        self.arrow_cx = float(self.arrow_min_cx)
        self.arrow_dir = 1
        self.arrow_animating = False
        self.stopped = False
        self.selected_strength = None
        self.result_color = None
        self._stop_tick = None
        self._last_update_ms = None
        self._drawn_cx = None

    # ------------------------------------------------------------------
    # Bar selection
    # ------------------------------------------------------------------

    @staticmethod
    def _bar_type(pet):
        """The column pattern, which is the attribute.

        Free shares Data's rather than Vaccine's -- read off the device on a
        Free Yarmon and a Data Herissmon, both type 2, against a Vaccine
        Varudurumon's 1 and a Virus Agumon X's 3.
        """
        attr = getattr(pet, "attribute", "") if pet else ""
        if attr == "Va":
            return 1
        if attr == "Vi":
            return 3
        return 2  # Da, and "" (Free) with it

    @staticmethod
    def _bar_level(pet):
        """Which of the three bar arts this pet plays.

        Devices that level their Digimon scale the bar off the level and the
        rest off effort, and `battle_utils.pet_tier_index` is where that
        decision lives -- Count Match Z widens on the same ladder, so a copy
        here would be a second place for the two to disagree.
        """
        from battle.sim.battle_utils import pet_tier_index
        return pet_tier_index(pet)

    # ------------------------------------------------------------------
    # Game flow
    # ------------------------------------------------------------------

    def start(self):
        self.arrow_animating = True
        self.stopped = False
        self.arrow_dir = 1
        self.arrow_cx = float(self.arrow_min_cx)
        self.selected_strength = None
        self.result_color = None
        self.arrow_sprite = self.arrow_sprites.get(None)
        self._stop_tick = None
        self._last_update_ms = None
        self._drawn_cx = None

    def stop(self):
        """Freeze the arrow, read the color under it, recolor the arrow."""
        if self.stopped:
            return
        self.arrow_animating = False
        self.stopped = True
        self._stop_tick = pygame.time.get_ticks()
        self._last_update_ms = None
        # Use the last-rendered position so the result matches what the
        # player actually saw, regardless of update/draw ordering.
        if self._drawn_cx is not None:
            self.arrow_cx = self._drawn_cx

        self.result_color = self._sample_color_at(self.arrow_cx)
        self.selected_strength = self.result_color or 0
        colored = self.arrow_sprites.get(self.result_color)
        if colored is not None:
            self.arrow_sprite = colored

        runtime_globals.game_console.log(
            f"[XaiBar] stopped on {QUALITY[self.selected_strength]} "
            f"({self.selected_strength}) -- bar {self.bar_name}, "
            f"arrow at {self.arrow_cx:.1f}, source px {self._last_src_x}")

    def is_finished(self):
        """True once the post-stop hold (0.5s) has elapsed."""
        return (self.stopped and self._stop_tick is not None
                and pygame.time.get_ticks() - self._stop_tick >= STOP_HOLD_MS)

    def _sample_color_at(self, center_x):
        """Classify the bar color under the arrow center.

        Samples the SOURCE sprite column (pixel-perfect scaling makes the
        mapping exact), scanning bottom-up so bottom-anchored color zones
        are found even when they don't span the full bar height.
        """
        src_x = int((center_x - self.x) / self.scale)
        src_x = max(0, min(BAR_SRC_W - 1, src_x))
        self._last_src_x = src_x
        for src_y in range(BAR_SRC_H - 1 - BAR_MARGIN_SRC, BAR_MARGIN_SRC - 1, -1):
            value = _classify_color(self.bar_source.get_at((src_x, src_y)))
            if value is not None:
                return value
        return None

    def update(self):
        if not self.arrow_animating:
            return
        # Real delta-time movement, same speed rule as the old bar:
        # lower XAI numbers move faster.
        now = pygame.time.get_ticks()
        if self._last_update_ms is None:
            self._last_update_ms = now
        dt_ms = min(100, max(1, now - self._last_update_ms))
        self._last_update_ms = now

        # Expressed as how long the arrow takes to cross the bar rather than a
        # pixel rate, so it plays the same at any resolution. A low XAI is the
        # hard roll and still sweeps fastest; the old rate left the easy end
        # taking about five seconds per pass, which just felt stalled.
        travel = max(1.0, float(self.arrow_max_cx - self.arrow_min_cx))
        crossing_s = 0.55 + (max(1, min(7, self.xai_number)) - 1) * 0.15
        speed_pps = travel / crossing_s
        self.arrow_cx += self.arrow_dir * speed_pps * dt_ms / 1000.0

        if self.arrow_cx <= self.arrow_min_cx:
            self.arrow_cx = float(self.arrow_min_cx)
            self.arrow_dir = 1
        elif self.arrow_cx >= self.arrow_max_cx:
            self.arrow_cx = float(self.arrow_max_cx)
            self.arrow_dir = -1

    def get_result(self):
        """Result value (0-3): red=3, yellow=2, blue=1, no color=0."""
        return self.selected_strength if self.selected_strength is not None else 0

    def handle_event(self, event):
        if not isinstance(event, tuple) or len(event) != 2:
            return False
        event_type, _ = event
        if event_type in ("A", "LCLICK") and self.arrow_animating:
            self.stop()
            return True
        return False

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def draw(self, surface):
        blit_with_cache(surface, self.bar_sprite, (self.x, self.y))

        if self.arrow_sprite:
            if self.arrow_animating or self.stopped:
                cx = self.arrow_cx
                self._drawn_cx = self.arrow_cx
            else:
                cx = (self.arrow_min_cx + self.arrow_max_cx) / 2
            arrow_x = int(cx) - self.arrow_sprite.get_width() // 2
            blit_with_cache(surface, self.arrow_sprite, (arrow_x, self.arrow_y))
