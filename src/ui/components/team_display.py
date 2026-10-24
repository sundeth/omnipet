"""
Team Display Component
=======================

Three hexagonal slots that show the player's currently picked arena team.
Mirrors VersusDisplay's layout / drawing pattern but uses three slots
side-by-side instead of two (and no "versus" sprite between them).

Used by ArenaTeamCreationView to give the picker the same look-and-feel
as the battle-scene VersusView / JogressView pickers.
"""

import math

import pygame

from ui.components.component import UIComponent
from core import runtime_globals
from models.animation import PetFrame
from ui.ui_constants import *


class TeamDisplay(UIComponent):
    SLOTS = 3

    def __init__(self, x, y, width, height):
        super().__init__(x, y, width, height)

        self.slot_pets = [None] * self.SLOTS
        # Theme used to colour each filled slot (cycles BLUE / GREEN / RED-ish)
        self.slot_themes = ["BLUE", "GREEN", "PURPLE"]

        # Base visual settings (will be scaled by the manager)
        self.base_hexagon_size = 28
        self.base_spacing = 8
        self.base_border_width = 2

        self.hexagon_size = self.base_hexagon_size
        self.spacing = self.base_spacing
        self.border_width = self.base_border_width

        self.slot_centers = [None] * self.SLOTS

        self.default_fill = None
        self.default_border = None

        self.needs_layout_update = True
        self.cached_surface = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_pet_slot(self, slot_index, pet):
        if 0 <= slot_index < self.SLOTS:
            if self.slot_pets[slot_index] != pet:
                self.slot_pets[slot_index] = pet
                self.needs_redraw = True

    def clear_slot(self, slot_index):
        self.set_pet_slot(slot_index, None)

    def clear_all_slots(self):
        self.slot_pets = [None] * self.SLOTS
        self.needs_redraw = True

    def set_slot_count(self, count):
        """Show *count* slots (1-3): a season of solo or paired Digimon
        draws only the slots its teams can fill."""
        count = max(1, min(3, int(count)))
        if count != self.SLOTS:
            self.SLOTS = count
            self.slot_pets = (list(self.slot_pets) + [None] * count)[:count]
            self.slot_centers = [None] * count
            self.needs_layout_update = True
            self.needs_redraw = True

    def set_pets(self, pets):
        """Replace all slots from an ordered iterable of up to SLOTS pets."""
        pets = list(pets)[: self.SLOTS]
        new_state = pets + [None] * (self.SLOTS - len(pets))
        if new_state != self.slot_pets:
            self.slot_pets = new_state
            self.needs_redraw = True

    def get_slot_pet(self, slot_index):
        if 0 <= slot_index < self.SLOTS:
            return self.slot_pets[slot_index]
        return None

    # ------------------------------------------------------------------
    # Theme / layout
    # ------------------------------------------------------------------

    def _theme_colors(self, theme_name):
        if not self.manager:
            return {"bg": (40, 40, 80), "fg": (255, 255, 255)}
        if theme_name == "GREEN":
            return {"bg": GREEN_DARK, "fg": GREEN}
        if theme_name == "BLUE":
            return {"bg": BLUE_DARK, "fg": BLUE}
        if theme_name == "PURPLE":
            try:
                return {"bg": PURPLE, "fg": YELLOW}
            except NameError:
                pass
        return self.manager.get_theme_colors()

    def _update_default_colors(self):
        if not self.manager:
            return
        theme = self.manager.get_theme_colors()
        new_fill = theme.get("bg", (40, 40, 80))
        new_border = theme.get("fg", (255, 255, 255))
        if self.default_fill != new_fill or self.default_border != new_border:
            self.default_fill = new_fill
            self.default_border = new_border
            self.needs_redraw = True

    def on_manager_set(self):
        if self.manager:
            self.hexagon_size = self.manager.scale_value(self.base_hexagon_size)
            self.spacing = self.manager.scale_value(self.base_spacing)
            self.border_width = self.manager.scale_value(self.base_border_width)
        self._update_default_colors()
        self.needs_layout_update = True

    def update(self):
        if self.needs_layout_update:
            self._update_layout()
        if self.manager:
            self._update_default_colors()

    def _update_layout(self):
        if not getattr(self, 'base_rect', None):
            return
        avail_w = self.base_rect.width
        avail_h = self.base_rect.height

        # Largest radius that fits all SLOTS hexagons horizontally with spacing
        max_r_horiz = (avail_w - (self.SLOTS - 1) * self.base_spacing) // (self.SLOTS * 2)
        max_r_vert = avail_h // 2
        radius = max(8, min(max_r_horiz, max_r_vert, self.base_hexagon_size))
        self.base_hexagon_size = radius

        total_w = self.SLOTS * (radius * 2) + (self.SLOTS - 1) * self.base_spacing
        start_x = (avail_w - total_w) // 2
        y = avail_h // 2

        for i in range(self.SLOTS):
            cx = start_x + radius + i * ((radius * 2) + self.base_spacing)
            self.slot_centers[i] = (cx, y)

        self.needs_layout_update = False
        self.needs_redraw = True

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------

    def render(self):
        if (self.cached_surface is None
                or self.cached_surface.get_size() != (self.rect.width, self.rect.height)):
            self.cached_surface = pygame.Surface(
                (self.rect.width, self.rect.height), pygame.SRCALPHA)
        surface = self.cached_surface
        surface.fill((0, 0, 0, 0))

        if not all(self.slot_centers):
            return surface

        scaled_radius = (self.manager.scale_value(self.base_hexagon_size)
                         if self.manager else self.base_hexagon_size)
        scaled_border = (self.manager.scale_value(self.base_border_width)
                         if self.manager else self.base_border_width)

        for i, center in enumerate(self.slot_centers):
            self._draw_hexagon(surface, i, center, scaled_radius, scaled_border)

        return surface

    def _draw_hexagon(self, surface, slot_index, center, radius, border_width):
        pet = self.slot_pets[slot_index]
        if pet is not None:
            theme = self._theme_colors(self.slot_themes[slot_index % len(self.slot_themes)])
            fill_color = theme.get("bg", self.default_fill or (40, 40, 80))
            border_color = theme.get("fg", self.default_border or (255, 255, 255))
        else:
            fill_color = self.default_fill or (40, 40, 80)
            border_color = self.default_border or (128, 128, 128)

        scaled_center = (
            self.manager.scale_value(center[0]) if self.manager else center[0],
            self.manager.scale_value(center[1]) if self.manager else center[1],
        )

        points = []
        for k in range(6):
            angle = (math.pi / 3 * k) + (math.pi / 6)
            x = scaled_center[0] + radius * math.cos(angle)
            y = scaled_center[1] + radius * math.sin(angle)
            points.append((int(x), int(y)))
        if len(points) >= 3:
            pygame.draw.polygon(surface, fill_color, points)
            if border_color:
                pygame.draw.polygon(surface, border_color, points, border_width)

        if pet and hasattr(pet, 'get_sprite'):
            try:
                state_attr = getattr(pet, 'state', None)
                frame = (PetFrame.NAP2.value if state_attr == "nap"
                         else PetFrame.IDLE1.value)
                sprite = pet.get_sprite(frame)
                if sprite:
                    sprite_padding = max(4, radius // 8)
                    available_radius = radius - sprite_padding
                    sw, sh = sprite.get_size()
                    sf = min((available_radius * 2) / sw, (available_radius * 2) / sh)
                    if sf < 1.0:
                        sprite = pygame.transform.scale(
                            sprite,
                            (max(1, int(sw * sf)), max(1, int(sh * sf)))
                        )
                    sr = sprite.get_rect(center=scaled_center)
                    from utils.pygame_utils import blit_with_cache
                    blit_with_cache(surface, sprite, sr.topleft)
            except Exception as exc:
                runtime_globals.game_console.log(
                    f"[TeamDisplay] Sprite blit failed for slot {slot_index}: {exc}")
