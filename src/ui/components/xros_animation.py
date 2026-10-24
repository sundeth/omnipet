"""
XrosAnimation — the temporary-evolution (Xros / Mode Change) sequence.

The screen is split into one cell per transforming pet:
    1 pet   -> fullscreen
    2 pets  -> split along the larger screen dimension
    3-4     -> 2x2
    5-6     -> 3x2 (or 2x3 on portrait render resolutions)
    7+      -> 4x2 (or 2x4)

Timeline per cell (all cells run in sync). The segment lengths are the
lengths of the sounds that play over them, so picture and audio finish
together — matched against a recording of the real device:

    0.0 - 1.1s  evolution background only          <- xros_start (21, 1.1s)
    then        friend sprites required by the evolution, one at a time at
                0.4s each, offset to the sides of the center (left, right,
                left, ...)                          <- "menu" per friend
    +0.5s       the pet's (pre-evolution) sprite
    +1.2s       the 5-frame xros animation, spanning the cell's full width
                                                    <- xros_animation (22, 1.2s)
    +5.4s       the evolved pet, revealed by two curtains in the X's own
                colour parting from the middle over 3s, then standing for the
                remaining 2.4s                      <- xros_evolution (23, 5.4s)

xros_start is played by the selection screen the moment the player confirms,
so it covers the gap before this animation is even built; the rest are played
here as their segments begin.

Optimized for low-power devices: a single canvas holds every cell's
background (composited once at construction) and every sprite is pre-scaled
once — the per-frame draw is one canvas blit plus at most one sprite blit
per cell.
"""

import pygame

from core import constants, runtime_globals
from models.animation import PetFrame
from utils.module_utils import get_module
from utils.pygame_utils import blit_with_cache
from utils.xros_utils import (load_form_sprite, load_xros_animation_frames,
                              load_xros_background)


class XrosAnimation:
    # Segment lengths in seconds, matched to the sound that plays over each.
    SEG_BG = 1.1        # length of xros_start (21.wav)
    SEG_PER_FRIEND = 0.4  # each friend gets its own beat, with a menu blip
    SEG_PET = 0.5
    SEG_ANIM = 1.2      # length of xros_animation (22.wav)
    SEG_EVOLVED = 5.4   # length of xros_evolution (23.wav)
    SEG_CURTAIN = 3.0   # of SEG_EVOLVED, spent parting the curtains; the
                        # remaining 2.4s is the evolved form standing there

    def __init__(self, selections):
        """
        Args:
            selections: list of (pet, temp_evo) for pets that ARE transforming.
                Must be called BEFORE apply_temp_evolution so the pets' current
                sprites are still their pre-evolution forms.
        """
        fps = constants.FRAME_RATE
        self.frame = 0
        # Which sound cues have already fired, and which friend is showing.
        self._anim_sound_played = False
        self._evolved_sound_played = False
        self._friend_shown = -1

        # The friends segment is as long as it needs to be: every friend gets
        # its own beat, so a form that fuses five of them takes longer than one
        # that fuses two. All cells run in sync, so the longest list sets it.
        self.max_friends = max(
            (len(evo.get("friend") or []) for _, evo in selections), default=0)

        # Segment boundaries in frames
        self.t_friends = int(self.SEG_BG * fps)
        self.t_pet = self.t_friends + int(self.max_friends * self.SEG_PER_FRIEND * fps)
        self.t_anim = self.t_pet + int(self.SEG_PET * fps)
        self.t_evolved = self.t_anim + int(self.SEG_ANIM * fps)
        self.t_end = self.t_evolved + int(self.SEG_EVOLVED * fps)
        self.friends_frames = max(1, self.t_pet - self.t_friends)
        self.anim_frames = max(1, self.t_evolved - self.t_anim)

        sw, sh = runtime_globals.SCREEN_WIDTH, runtime_globals.SCREEN_HEIGHT
        cols, rows = self._grid(len(selections), sw, sh)
        cell_w, cell_h = sw // cols, sh // rows
        # Pets (friends, the pet itself, the evolved form) are drawn at the
        # size they are everywhere else in the game rather than scaled to the
        # cell — they were coming out far too big.
        sprite_size = min(runtime_globals.PET_WIDTH, cell_w, cell_h)

        # Single static canvas with every cell's background composited once.
        self.canvas = pygame.Surface((sw, sh))
        self.canvas.fill((0, 0, 0))

        self.cells = []
        for i, (pet, evo) in enumerate(selections):
            col, row = i % cols, i // cols
            cx = col * cell_w + cell_w // 2
            cy = row * cell_h + cell_h // 2
            module = get_module(pet.module)

            bg = load_xros_background(module, evo.get("background"), (cell_w, cell_h))
            if bg:
                self.canvas.blit(bg, (col * cell_w, row * cell_h))

            # Friend sprites (may be empty)
            friends = []
            for fname in (evo.get("friend") or []):
                sprite = load_form_sprite(module, fname, PetFrame.IDLE1.value, sprite_size)
                if sprite:
                    friends.append(sprite)

            # Pre-evolution sprite (pet still has its normal sprites here)
            base = None
            try:
                base = pygame.transform.scale(
                    pet.get_sprite(PetFrame.IDLE1.value), (sprite_size, sprite_size))
            except Exception:
                pass

            # The X sweep spans the full cell width; its height follows from
            # the artwork, so it need not reach the top and bottom.
            frames = load_xros_animation_frames(module, evo.get("animation"),
                                                sprite_size, fit_width=cell_w)
            evolved = load_form_sprite(module, evo.get("to"), PetFrame.HAPPY.value, sprite_size)

            self.cells.append({
                "center": (cx, cy),
                "half_w": cell_w // 4,
                "friends": friends,
                "base": base,
                "frames": frames,
                "evolved": evolved,
                # The curtain that opens over the evolved form covers exactly
                # the area the X swept, in the X's own colour.
                "curtain_size": (frames[-1].get_size() if frames else (cell_w, cell_h)),
                "curtain_color": self._curtain_color(frames),
            })

    @staticmethod
    def _curtain_color(frames):
        """The X's own colour, read from the centre of its last frame.

        The centre pixel is the X's crossing point, so it is the colour of the
        sweep itself. If that pixel happens to be transparent, the nearest
        opaque pixel along the centre row is used instead.
        """
        if not frames:
            return (220, 40, 40)
        last = frames[-1]
        w, h = last.get_size()
        cx, cy = w // 2, h // 2
        try:
            for dx in range(0, max(1, w // 2)):
                for x in ((cx - dx), (cx + dx)):
                    if 0 <= x < w:
                        pixel = last.get_at((x, cy))
                        if pixel.a > 0:
                            return (pixel.r, pixel.g, pixel.b)
        except Exception:
            pass
        return (220, 40, 40)

    @staticmethod
    def _grid(n, sw, sh):
        """Grid dimensions for n cells on a sw x sh render surface."""
        if n <= 1:
            return 1, 1
        landscape = sw >= sh
        if n == 2:
            return (2, 1) if landscape else (1, 2)
        per_line = (n + 1) // 2  # two lines of ceil(n/2)
        return (per_line, 2) if landscape else (2, per_line)

    # ------------------------------------------------------------------

    @property
    def finished(self) -> bool:
        return self.frame >= self.t_end

    def _friend_beat(self, f):
        """Which friend is on screen at frame f (shared by every cell)."""
        if not self.max_friends:
            return 0
        return min(self.max_friends - 1,
                   (f - self.t_friends) * self.max_friends // self.friends_frames)

    def update(self):
        self.frame += 1
        f = self.frame

        # A blip as each friend arrives.
        if self.t_friends <= f < self.t_pet and self.max_friends:
            beat = self._friend_beat(f)
            if beat != self._friend_shown:
                self._friend_shown = beat
                runtime_globals.game_sound.play("menu")

        # The slash animation and the reveal each have their own sound, and
        # each segment is exactly as long as its sound.
        if not self._anim_sound_played and f >= self.t_anim:
            self._anim_sound_played = True
            runtime_globals.game_sound.play("xros_animation")

        if not self._evolved_sound_played and f >= self.t_evolved:
            self._evolved_sound_played = True
            runtime_globals.game_sound.play("xros_evolution")

    def draw(self, surface):
        # Backgrounds: one blit for the whole screen.
        blit_with_cache(surface, self.canvas, (0, 0))

        f = self.frame
        for cell in self.cells:
            cx, cy = cell["center"]

            if f < self.t_friends:
                continue  # background only

            if f < self.t_pet:
                # Friends, one at a time, offset left / right of the center.
                friends = cell["friends"]
                if not friends:
                    continue
                # Shared beat, so every cell changes friend on the same frame
                # the blip plays; a cell with fewer friends holds its last.
                idx = min(len(friends) - 1, self._friend_beat(f))
                sprite = friends[idx]
                offset = -cell["half_w"] if idx % 2 == 0 else cell["half_w"]
                self._blit_center(surface, sprite, cx + offset, cy)

            elif f < self.t_anim:
                self._blit_center(surface, cell["base"], cx, cy)

            elif f < self.t_evolved:
                # Only background + the xros animation frames.
                frames = cell["frames"]
                if not frames:
                    continue
                idx = min(len(frames) - 1,
                          (f - self.t_anim) * len(frames) // self.anim_frames)
                self._blit_center(surface, frames[idx], cx, cy)

            else:
                # The evolved form is revealed by two curtains parting from
                # the middle over the area the X swept, then simply stands
                # there for the rest of the sound.
                self._blit_center(surface, cell["evolved"], cx, cy)
                opening = int(self.SEG_CURTAIN * constants.FRAME_RATE)
                progress = (f - self.t_evolved) / max(1, opening)
                if progress < 1.0:
                    cw, ch = cell["curtain_size"]
                    half = ch // 2
                    visible = max(0, int(half * (1.0 - progress)))
                    if visible:
                        left = cx - cw // 2
                        top = cy - half
                        panel = pygame.Surface((cw, visible))
                        panel.fill(cell["curtain_color"])
                        # Upper curtain rises, lower curtain drops.
                        blit_with_cache(surface, panel, (left, top))
                        blit_with_cache(surface, panel,
                                        (left, top + ch - visible))

    @staticmethod
    def _blit_center(surface, sprite, cx, cy):
        if sprite is None:
            return
        blit_with_cache(surface, sprite,
                        (cx - sprite.get_width() // 2, cy - sprite.get_height() // 2))
