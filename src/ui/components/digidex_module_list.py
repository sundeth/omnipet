"""
DigidexModuleList — the digidex's module selection list.

Same look and behaviour as the pet list (DigidexList): scrollable rows with
an icon (the module's BattleIcon) on the left, the module name and a
known/total pets line, with keyboard, mouse, scroll-wheel and drag support.
"""

import os
import pygame

from core import runtime_globals
from ui.components.digidex_list import DigidexList
from utils.asset_utils import image_load, resolve_path
from utils.pygame_utils import blit_with_cache, blit_with_shadow


class DigidexModuleEntry:
    """One selectable row: a module (or the 'All' pseudo-module)."""

    def __init__(self, name, sprite=None, info="", module_name=None):
        self.name = name              # Display name ("All" or the module name)
        self.module_name = module_name  # None for the "All" entry
        self.sprite = sprite
        self.info = info              # Secondary line (e.g. "12/40 known")
        self.known = True             # Always selectable


def load_module_battle_icon(module, size):
    """The module's BattleIcon.png scaled to *size* (or None)."""
    try:
        path = os.path.join(module.folder_path, "BattleIcon.png")
        if os.path.exists(resolve_path(path)):
            icon = image_load(path).convert_alpha()
            return pygame.transform.scale(icon, (size, size))
    except Exception as exc:
        runtime_globals.game_console.log(
            f"[DigidexModuleList] icon load failed for {module.name}: {exc}")
    return None


class DigidexModuleList(DigidexList):
    """Module selector reusing the pet list's layout/interaction."""

    # Entries are prebuilt with their sprites; nothing to (un)load.
    def update_sprite_cache(self):
        pass

    def handle_event(self, event):
        # Same as the pet list, but every entry is selectable ("known").
        if not isinstance(event, tuple) or len(event) != 2:
            return False
        event_type, _ = event

        if event_type == "UP":
            self.navigate_up()
            runtime_globals.game_sound.play("menu")
            return True
        if event_type == "DOWN":
            self.navigate_down()
            runtime_globals.game_sound.play("menu")
            return True
        if event_type == "A":
            selected = self.get_selected_pet()
            if selected and self.on_selection_callback:
                self.on_selection_callback(selected)
                runtime_globals.game_sound.play("menu")
            return True
        # Scroll wheel / drag support comes from the pet list base class.
        return super().handle_event(event)

    def render(self):
        surface = pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
        if not self.pets:
            return surface

        ui_scale = self.manager.ui_scale if self.manager else 1
        item_height = int(50 * ui_scale)
        icon_size = int(40 * ui_scale)
        left_padding = int(8 * ui_scale)
        list_width = self.rect.width
        max_visible = max(1, self.rect.height // item_height)

        if self.selected_index < self.scroll_offset:
            self.scroll_offset = self.selected_index
        elif self.selected_index >= self.scroll_offset + max_visible:
            self.scroll_offset = self.selected_index - max_visible + 1

        colors = self.get_colors()
        font = self.get_font("text")

        for idx in range(self.scroll_offset, min(self.scroll_offset + max_visible, len(self.pets))):
            entry = self.pets[idx]
            y_pos = (idx - self.scroll_offset) * item_height

            if entry.sprite:
                blit_with_cache(surface, entry.sprite,
                                (left_padding, y_pos + (item_height - entry.sprite.get_height()) // 2))

            name_text = font.render(entry.name[:16], True, colors["fg"])
            blit_with_shadow(surface, name_text,
                             (left_padding + icon_size + int(5 * ui_scale), y_pos + int(8 * ui_scale)))

            if entry.info:
                info_text = font.render(entry.info, True, (200, 200, 200))
                blit_with_shadow(surface, info_text,
                                 (left_padding + icon_size + int(5 * ui_scale), y_pos + int(28 * ui_scale)))

            is_hovered = (idx == self.hover_index)
            is_selected = (idx == self.selected_index)
            # The selected row keeps its border; the hover/focus one is not
            # drawn in touch mode (focus_visible).
            show_focus = is_hovered and self.focus_visible()
            if is_selected or show_focus:
                highlight_color = colors.get("highlight", colors["line"])
                border_color = highlight_color if show_focus else colors["line"]
                border_width = max(1, int(2 * ui_scale))
                pygame.draw.rect(surface, border_color,
                                 (0, y_pos, list_width, item_height), border_width)

        return surface
