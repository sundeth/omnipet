"""
XrosSelector — pre-battle temporary-evolution picker.

Layout:
    [pet1][pet2][pet...n]
    [Confirm]

Each box shows the pet's current choice (its normal form, or one of its
available temporary evolutions).  LEFT/RIGHT change the focused box's choice
— the same thing the < > arrows either side of it do — and UP/DOWN move the
focus down the list of boxes and on to the Confirm button.  There is no
cancel: confirming with every box on its normal form just skips the
transformation.

All sprites are pre-scaled once at construction (low-power friendly).
"""

import pygame

from core import runtime_globals
from models.animation import PetFrame
from ui.components.button import Button
from utils.asset_utils import image_load
from utils.module_utils import get_module
from utils.pygame_utils import blit_with_cache, get_font
from utils.xros_utils import load_form_sprite, xros_cost


class XrosSelector:
    def __init__(self, candidates, ui_manager):
        """
        Args:
            candidates: list of (pet, [temp_evo, ...]) — options must be non-empty.
            ui_manager: battle UI manager (used for theme colors).
        """
        self.ui_manager = ui_manager
        self.entries = []          # one per pet
        self.focus = 0             # 0..n-1 = boxes, n = confirm button
        self.confirmed = False

        sw, sh = runtime_globals.SCREEN_WIDTH, runtime_globals.SCREEN_HEIGHT
        scale = runtime_globals.UI_SCALE
        n = max(1, len(candidates))

        # Box layout: side by side, centered
        margin = int(8 * scale)
        gap = int(6 * scale)
        box_w = min(int(72 * scale), (sw - margin * 2 - gap * (n - 1)) // n)
        box_h = int(96 * scale)
        total_w = n * box_w + (n - 1) * gap
        start_x = (sw - total_w) // 2
        box_y = (sh - box_h) // 2 - int(16 * scale)

        # Pets are shown at the size they are everywhere else in the game.
        sprite_size = runtime_globals.PET_WIDTH
        self.font = get_font(int(16 * scale))

        # Screen-filling background (scaled to cover, cropped centrally).
        self.background = self._load_background(sw, sh)

        for i, (pet, options) in enumerate(candidates):
            module = get_module(pet.module)
            # Option 0 = keep normal form; 1..n = temporary evolutions
            option_sprites = []
            option_names = [pet.name]
            base = None
            try:
                base = pet.get_sprite(PetFrame.IDLE1.value)
            except Exception:
                pass
            if base is not None:
                base = pygame.transform.scale(base, (sprite_size, sprite_size))
            option_sprites.append(base)

            # A form that costs DP (`xros_cost`) shows it above its name.
            option_costs = [None]
            for evo in options:
                option_names.append(evo.get("to", "?"))
                cost = xros_cost(evo)
                option_costs.append(
                    self.font.render(f"DP {cost}", True, (255, 220, 0)) if cost else None)
                sprite = load_form_sprite(module, evo.get("to"),
                                          PetFrame.IDLE1.value, sprite_size)
                option_sprites.append(sprite)

            rect = pygame.Rect(start_x + i * (box_w + gap), box_y, box_w, box_h)
            # Hit boxes for the < > arrows drawn either side of the focused
            # box. They sit OUTSIDE the box, so without their own rects a tap
            # on an arrow landed on nothing at all. Made generously tall and
            # wide enough to be a real touch target rather than matching the
            # drawn triangle exactly.
            ah = int(8 * scale)
            pad = int(4 * scale)
            arrow_w = ah + pad * 2
            self.entries.append({
                "pet": pet,
                "options": [None] + list(options),
                "names": option_names,
                "sprites": option_sprites,
                "labels": [self.font.render(nm, True, (255, 255, 255))
                           for nm in option_names],
                "costs": option_costs,
                "index": 0,
                "rect": rect,
                "left_rect": pygame.Rect(rect.x - pad - arrow_w,
                                         rect.centery - ah * 2,
                                         arrow_w, ah * 4),
                "right_rect": pygame.Rect(rect.right + pad,
                                          rect.centery - ah * 2,
                                          arrow_w, ah * 4),
            })

        # Confirm: the game's own Button, so it matches every other button
        # rather than being a hand-drawn rectangle. Registered with the battle
        # UI manager purely to get the theme and scaling it needs — the
        # selector draws it itself, since the battle never draws that manager.
        btn_w, btn_h = 74, 22
        self.confirm_button = Button(
            0, 0, btn_w, btn_h, "CONFIRM",
            cut_corners={'tl': True, 'tr': False, 'bl': False, 'br': True},
        )
        # Attached to the manager for its theme and scale, but not registered
        # with it: the battle never draws that manager, and registering would
        # put the button into its focus list. Scaled here instead, the same way
        # the battle's own result labels are.
        ui_scale = self.ui_manager.ui_scale if self.ui_manager else 1
        self.confirm_button.manager = self.ui_manager
        self.confirm_button.base_rect = pygame.Rect(0, 0, btn_w, btn_h)
        self.confirm_button.rect = pygame.Rect(
            0, box_y + box_h + int(14 * scale), btn_w * ui_scale, btn_h * ui_scale)
        self.confirm_button.rect.centerx = sw // 2
        try:
            self.confirm_button.on_manager_set()
        except Exception:
            pass
        self.confirm_rect = self.confirm_button.rect

    @staticmethod
    def _load_background(sw, sh):
        """The xros background, scaled to cover the screen."""
        try:
            img = image_load("assets/bg_xros_background.png").convert()
        except Exception as exc:
            runtime_globals.game_console.log(f"[Xros] background load failed: {exc}")
            return None
        iw, ih = img.get_size()
        if not iw or not ih:
            return None
        # Cover: scale by the larger ratio so no edge shows, then centre-crop.
        factor = max(sw / iw, sh / ih)
        scaled = pygame.transform.scale(
            img, (max(1, int(iw * factor)), max(1, int(ih * factor))))
        canvas = pygame.Surface((sw, sh))
        canvas.blit(scaled, ((sw - scaled.get_width()) // 2,
                             (sh - scaled.get_height()) // 2))
        return canvas

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def get_selections(self):
        """[(pet, temp_evo_or_None), ...] in party order."""
        return [(e["pet"], e["options"][e["index"]]) for e in self.entries]

    def has_any_selection(self) -> bool:
        return any(e["index"] > 0 for e in self.entries)

    def _cycle(self, entry, step=1):
        entry["index"] = (entry["index"] + step) % len(entry["options"])
        runtime_globals.game_sound.play("menu")

    # ------------------------------------------------------------------
    # Input — returns "confirm" when the player confirms
    # ------------------------------------------------------------------

    def handle_event(self, event):
        if not isinstance(event, tuple) or len(event) != 2:
            return None
        event_type, event_data = event
        total = len(self.entries) + 1  # boxes + confirm

        # LEFT/RIGHT change the focused box's choice — the same thing its
        # < > arrows do, which is what they look like they should do. Moving
        # between the boxes and Confirm is UP/DOWN.
        if event_type in ("LEFT", "RIGHT"):
            if self.focus < len(self.entries):
                self._cycle(self.entries[self.focus],
                            -1 if event_type == "LEFT" else 1)
            return None
        if event_type == "DOWN":
            self.focus = min(self.focus + 1, total - 1)
            runtime_globals.game_sound.play("menu")
            return None
        if event_type == "UP":
            self.focus = max(0, self.focus - 1)
            runtime_globals.game_sound.play("menu")
            return None

        if event_type == "A":
            if self.focus < len(self.entries):
                self._cycle(self.entries[self.focus])
            else:
                self.confirmed = True
                runtime_globals.game_sound.play("menu")
                return "confirm"
            return None

        if event_type == "LCLICK" and event_data and "pos" in event_data:
            pos = event_data["pos"]
            if self.confirm_rect.collidepoint(pos):
                self.confirmed = True
                runtime_globals.game_sound.play("menu")
                return "confirm"
            # The arrows only exist on the focused box, so only its arrows are
            # clickable — left steps back through the options, right forward.
            if self.focus < len(self.entries):
                focused = self.entries[self.focus]
                if focused["left_rect"].collidepoint(pos):
                    self._cycle(focused, -1)
                    return None
                if focused["right_rect"].collidepoint(pos):
                    self._cycle(focused, 1)
                    return None
            for i, entry in enumerate(self.entries):
                if entry["rect"].collidepoint(pos):
                    self.focus = i
                    self._cycle(entry)
                    return None
        return None

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def draw(self, surface):
        colors = self.ui_manager.get_theme_colors() if self.ui_manager else \
            {"bg": (0, 60, 0), "fg": (0, 200, 80), "highlight": (120, 255, 160)}
        fg = colors.get("fg", (0, 200, 80))
        highlight = colors.get("highlight", fg)
        scale = runtime_globals.UI_SCALE
        border = max(1, int(2 * scale))

        if self.background is not None:
            blit_with_cache(surface, self.background, (0, 0))

        for i, entry in enumerate(self.entries):
            rect = entry["rect"]
            focused = (i == self.focus)

            # Box: a dimmed panel over the background, plus the theme border.
            panel = pygame.Surface(rect.size, pygame.SRCALPHA)
            panel.fill((0, 0, 0, 170))
            blit_with_cache(surface, panel, rect.topleft)
            pygame.draw.rect(surface, highlight if focused else fg, rect, border)

            # Current option sprite + name
            sprite = entry["sprites"][entry["index"]]
            if sprite:
                sx = rect.x + (rect.width - sprite.get_width()) // 2
                sy = rect.y + int(6 * scale)
                blit_with_cache(surface, sprite, (sx, sy))
            label = entry["labels"][entry["index"]]
            lx = rect.x + (rect.width - label.get_width()) // 2
            ly = rect.bottom - label.get_height() - int(4 * scale)
            blit_with_cache(surface, label, (lx, ly))
            cost = entry["costs"][entry["index"]]
            if cost is not None:
                blit_with_cache(surface, cost, (rect.x + (rect.width - cost.get_width()) // 2,
                                                ly - cost.get_height()))

            # Selection arrows on the focused box sides (theme colors)
            if focused:
                ah = int(8 * scale)
                cy = rect.centery
                left_x = rect.x - int(4 * scale)
                right_x = rect.right + int(4 * scale)
                pygame.draw.polygon(surface, highlight, [
                    (left_x, cy - ah), (left_x, cy + ah), (left_x - ah, cy)])
                pygame.draw.polygon(surface, highlight, [
                    (right_x, cy - ah), (right_x, cy + ah), (right_x + ah, cy)])

        # Confirm: the game's own Button, drawn in its focused state so it
        # matches the buttons in every other scene.
        self.confirm_button.focused = (self.focus == len(self.entries))
        try:
            blit_with_cache(surface, self.confirm_button.render(),
                            self.confirm_button.rect.topleft)
        except Exception as exc:
            runtime_globals.game_console.log(f"[Xros] confirm draw failed: {exc}")
