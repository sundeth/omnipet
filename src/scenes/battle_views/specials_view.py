"""
SpecialsView - the Specials hub, opened from the battle main menu's SPECIALS
button.

The top strip holds one button per party module that offers something
(utils.specials_utils), its BattleIcon in the Adventure module strip's frame,
four to a page with arrows past four. Below it, the selected module's
specials -- each open shop, its codes under the module's own name for them
(PEN20's Copymon), an iC's Minigames (the training scene's Bonus list) --
are a grid of tiles, three to a row: the special's
sprite at up to 48x48 at 1x and its name under it. Two rows show at a time;
a module with more scrolls a row at a time. OPEN and BACK sit side by side
at the bottom.

``module_name`` reopens the hub on that module, as a shop or the code entry
does when it returns.
"""
import os

import pygame
from ui.ui_manager import UIManager
from ui.components.title_scene import TitleScene
from ui.components.button import Button
from ui.components.toggle_button import ToggleButton
from ui.components.button_group import ButtonGroup
from ui.components.background import Background
from ui.components.image import Image
from ui.ui_constants import BASE_RESOLUTION
from core import runtime_globals
from utils import specials_utils
from utils.pygame_utils import blit_with_cache
from utils.scene_utils import change_scene
from scenes.battle_views.module_shop_view import load_icon

#: The module strip, matching Battle_SpecialsModules_1.png
#: (utilities/claude/make_specials_sprites.py): four 46-pixel slots from x 18,
#: 6 apart, inside the frame's rail and margin.
STRIP_Y = 28
SLOT, SLOT_GAP, SLOT_X = 46, 6, 18
SLOT_Y = STRIP_Y + 4 + 2
MODULES_PER_PAGE = 4

#: The specials grid: three 76-pixel tiles to a row, two rows showing.
TILE_W, TILE_H = 76, 64
TILE_X, TILE_Y, TILE_GAP = 2, STRIP_Y + 60, 2
COLUMNS, VISIBLE_ROWS = 3, 2
ICON = 48
#: OPEN and BACK, side by side under the grid.
BUTTON_W, BUTTON_H, BUTTON_Y = 75, 20, 220


class SpecialTile(Button):
    """One grid cell: a special's sprite over its name, in a button frame.

    A sprite up to 48 pixels is drawn at its own size (times the UI scale),
    so pixel art keeps whole pixels; a bigger one is fitted to 48. A name
    wider than the tile scrolls back and forth, pausing at each end, as a
    Label with ``scroll_text`` does.
    """

    SCROLL_PAUSE = 60       # updates to rest at each end

    def __init__(self, x, y, width, height, special, icon, callback):
        super().__init__(x, y, width, height, "", callback)
        self.special = special
        self.source_icon = icon
        self._icon = None
        self.scroll_offset = 0
        self.scroll_direction = 1
        self.scroll_pause = self.SCROLL_PAUSE
        self._last_scroll = 0

    def _caption_room(self):
        scale = self.manager.ui_scale
        return self.rect.width - 2 * self.manager.get_border_size() - 2 * scale

    def update(self):
        super().update()
        if not self.manager or not self.visible:
            return
        now = pygame.time.get_ticks()
        if now - self._last_scroll < 16:        # ~60 steps a second
            return
        self._last_scroll = now
        overflow = self.get_font("text").size(self.special.title)[0] - self._caption_room()
        if overflow <= 0:
            return
        if self.scroll_pause > 0:
            self.scroll_pause -= 1
            return
        self.scroll_offset += self.scroll_direction * self.manager.ui_scale
        if self.scroll_offset >= overflow or self.scroll_offset <= 0:
            self.scroll_offset = max(0, min(self.scroll_offset, overflow))
            self.scroll_direction = -self.scroll_direction
            self.scroll_pause = self.SCROLL_PAUSE
        self.needs_redraw = True

    def _scaled_icon(self):
        if self.source_icon is None:
            return None
        if self._icon is None:
            scale = self.manager.ui_scale
            w, h = self.source_icon.get_size()
            if max(w, h) > ICON:
                w, h = w * ICON // max(w, h), h * ICON // max(w, h)
            self._icon = pygame.transform.scale(self.source_icon, (w * scale, h * scale))
        return self._icon

    def render(self):
        surface = super().render()
        scale = self.manager.ui_scale
        border = self.manager.get_border_size()
        colors = self.get_colors()

        icon = self._scaled_icon()
        if icon is not None:
            x = (self.rect.width - icon.get_width()) // 2
            y = border + (ICON * scale - icon.get_height()) // 2
            blit_with_cache(surface, icon, (x, y))

        # The name under the sprite: centred when it fits, else scrolled
        # within the tile (see update).
        room = self._caption_room()
        text = self.get_font("text").render(self.special.title, True, colors["fg"])
        y = self.rect.height - border - scale - text.get_height()
        if text.get_width() <= room:
            blit_with_cache(surface, text, ((self.rect.width - text.get_width()) // 2, y))
        else:
            window = pygame.Surface((room, text.get_height()), pygame.SRCALPHA)
            window.blit(text, (-self.scroll_offset, 0))
            blit_with_cache(surface, window, ((self.rect.width - room) // 2, y))
        return surface


class SpecialsView:
    """Module strip on top, the selected module's specials in a grid below."""

    def __init__(self, ui_manager: UIManager, change_view_callback, module_name=None):
        self.ui_manager = ui_manager
        self.change_view = change_view_callback

        self.entries = specials_utils.party_specials()
        names = [module.name for module, _specials in self.entries]
        self.selected = names.index(module_name) if module_name in names else 0
        self.page = self.selected // MODULES_PER_PAGE

        self.background = None
        self.title_scene = None
        self.strip_image = None
        self.module_buttons = []
        self.module_group = ButtonGroup()
        self.prev_button = None
        self.next_button = None
        self.tiles = []
        self.top_row = 0
        self.current = 0        # the tile OPEN opens: the last one focused
        self.open_button = None
        self.back_button = None

        self._setup_ui()

    # ------------------------------------------------------------------ setup

    def _setup_ui(self):
        ui_width = ui_height = BASE_RESOLUTION

        self.background = Background(ui_width, ui_height)
        self.background.set_regions([(0, ui_height, "black")])
        self.ui_manager.add_component(self.background)

        self.title_scene = TitleScene(0, 9, "SPECIALS")
        self.ui_manager.add_component(self.title_scene)

        self.strip_image = Image(0, STRIP_Y, ui_width, 58)
        strip = self.ui_manager.load_sprite_integer_scaling("Battle", "SpecialsModules", "")
        if strip:
            self.strip_image.set_image(image_surface=strip)
        self.ui_manager.add_component(self.strip_image)

        for index, (module, _specials) in enumerate(self.entries):
            slot = index % MODULES_PER_PAGE
            button = ToggleButton(
                SLOT_X + slot * (SLOT + SLOT_GAP), SLOT_Y, SLOT, SLOT, "",
                on_toggle=lambda btn, on, i=index: self._on_module_toggled(i, on))
            button.icon_sprite = self._battle_icon(module)
            self._make_navigable(button)
            self.module_buttons.append(button)
            self.module_group.add_button(button)
            self.ui_manager.add_component(button)

        if len(self.entries) > MODULES_PER_PAGE:
            self.prev_button = Button(2, SLOT_Y, 12, SLOT, "<", lambda: self._turn_page(-1))
            self.next_button = Button(226, SLOT_Y, 12, SLOT, ">", lambda: self._turn_page(1))
            self.ui_manager.add_component(self.prev_button)
            self.ui_manager.add_component(self.next_button)

        gap = 10
        left = (ui_width - 2 * BUTTON_W - gap) // 2
        self.open_button = Button(left, BUTTON_Y, BUTTON_W, BUTTON_H, "OPEN", self._on_open)
        self.ui_manager.add_component(self.open_button)
        self.back_button = Button(left + BUTTON_W + gap, BUTTON_Y, BUTTON_W, BUTTON_H,
                                  "BACK", self._on_back)
        self.ui_manager.add_component(self.back_button)

        self._show_page()
        if self.module_buttons:
            self.module_buttons[self.selected].set_toggled(True, silent=True)
        self._show_module()
        self.ui_manager.set_focused_component(self.tiles[0] if self.tiles else self.back_button)
        runtime_globals.game_console.log(
            f"[SpecialsView] {len(self.entries)} module(s) with specials")

    def _battle_icon(self, module):
        icon = load_icon(os.path.join(module.folder_path, "BattleIcon.png"))
        if icon is None:
            return None
        # A 4-pixel frame round the icon shows which module is toggled.
        size = (SLOT - 8) * self.ui_manager.ui_scale
        return pygame.transform.scale(icon, (size, size))

    def _make_navigable(self, button):
        """LEFT/RIGHT on a module button moves through the modules, turning
        the page, as on the Adventure module strip. Activating the selected
        module enters its grid rather than untoggling it."""
        original = button.handle_event

        def _handle(event):
            event_type, _ = event
            if event_type in ("LEFT", "RIGHT") and self.module_buttons:
                step = -1 if event_type == "LEFT" else 1
                self._select((self.selected + step) % len(self.module_buttons))
                self.ui_manager.set_focused_component(self.module_buttons[self.selected])
                return True
            return original(event)

        def _activate():
            if not button.enabled:
                return False
            if button.is_toggled:
                runtime_globals.game_sound.play("menu")
                if self.tiles:
                    self.ui_manager.set_focused_component(self.tiles[self.top_row * COLUMNS])
            else:
                # The toggle callback plays the sound.
                button.set_toggled(True)
            return True

        button.handle_event = _handle
        button.activate = _activate

    def _make_scrolling(self, tile, index):
        """UP/DOWN past the rows showing scrolls the grid a row."""
        original = tile.handle_event

        def _handle(event):
            event_type, _ = event
            row = index // COLUMNS
            if event_type == "DOWN" and row == self.top_row + VISIBLE_ROWS - 1 \
                    and self.top_row + VISIBLE_ROWS < self._rows():
                self._scroll(1)
                self._focus_tile(min(index + COLUMNS, len(self.tiles) - 1))
                return True
            if event_type == "UP" and row == self.top_row and self.top_row > 0:
                self._scroll(-1)
                self._focus_tile(index - COLUMNS)
                return True
            return original(event)
        tile.handle_event = _handle

    # ---------------------------------------------------------------- display

    def _show_page(self):
        first = self.page * MODULES_PER_PAGE
        for index, button in enumerate(self.module_buttons):
            button.visible = first <= index < first + MODULES_PER_PAGE
            button.needs_redraw = True

    def _rows(self):
        return (len(self.tiles) + COLUMNS - 1) // COLUMNS

    def _show_module(self):
        """Lay out the selected module's specials as tiles."""
        for tile in self.tiles:
            if tile in self.ui_manager.components:
                self.ui_manager.remove_component(tile)
        self.tiles = []
        self.top_row = 0
        self.current = 0
        specials = self.entries[self.selected][1] if self.entries else []
        for index, special in enumerate(specials):
            tile = SpecialTile(0, 0, TILE_W, TILE_H, special, load_icon(special.icon_path),
                               lambda i=index: self._open(i))
            self._make_scrolling(tile, index)
            self.tiles.append(tile)
            self.ui_manager.add_component(tile)
        self._place_tiles()
        self.open_button.set_enabled(bool(self.tiles))

    def _place_tiles(self):
        for index, tile in enumerate(self.tiles):
            row, col = divmod(index, COLUMNS)
            row -= self.top_row
            tile.visible = 0 <= row < VISIBLE_ROWS
            tile.focusable = tile.visible
            tile.set_position(TILE_X + col * (TILE_W + TILE_GAP),
                              TILE_Y + max(0, min(row, VISIBLE_ROWS - 1)) * (TILE_H + TILE_GAP))
            tile.needs_redraw = True

    def _scroll(self, rows):
        top = max(0, min(self.top_row + rows, self._rows() - VISIBLE_ROWS))
        if top != self.top_row:
            self.top_row = top
            self._place_tiles()

    def _focus_tile(self, index):
        if 0 <= index < len(self.tiles):
            self.current = index
            self.ui_manager.set_focused_component(self.tiles[index])

    def draw(self, surface: pygame.Surface):
        # A thin bar on the right while a module has more rows than show.
        rows = self._rows()
        if rows <= VISIBLE_ROWS:
            return
        scale = self.ui_manager.ui_scale
        colors = self.ui_manager.get_theme_colors()
        x, y = self.ui_manager.scale_position(236, TILE_Y)
        height = (VISIBLE_ROWS * (TILE_H + TILE_GAP) - TILE_GAP) * scale
        pygame.draw.rect(surface, colors["bg"], (x, y, 2 * scale, height))
        thumb = height * VISIBLE_ROWS // rows
        offset = (height - thumb) * self.top_row // (rows - VISIBLE_ROWS)
        pygame.draw.rect(surface, colors["fg"], (x, y + offset, 2 * scale, thumb))

    # ---------------------------------------------------------------- actions

    def _select(self, index):
        if not self.module_buttons:
            return
        self.page = index // MODULES_PER_PAGE
        self._show_page()
        # set_toggled fires _on_module_toggled, which does the rest.
        self.module_buttons[index].set_toggled(True)

    def _on_module_toggled(self, index, toggled):
        if not toggled:
            return
        runtime_globals.game_sound.play("menu")
        self.selected = index
        self._show_module()

    def _turn_page(self, step):
        pages = (len(self.module_buttons) + MODULES_PER_PAGE - 1) // MODULES_PER_PAGE
        page = (self.page + step) % pages
        self._select(page * MODULES_PER_PAGE)

    def _on_open(self):
        self._open(self.current)

    def _open(self, index):
        if not 0 <= index < len(self.tiles):
            runtime_globals.game_sound.play("cancel")
            return
        special = self.tiles[index].special
        runtime_globals.game_sound.play("menu")
        if special.kind == "shop":
            self.change_view("module_shop",
                             shop_key=(special.module.name, special.data["shop"].get("name")))
        elif special.kind == "password":
            self.change_view("password", module_name=special.module.name)
        elif special.kind == "minigames":
            # The training scene's Bonus list, whose BACK comes back here.
            runtime_globals.scene_training_initial_view = "bonus"
            runtime_globals.training_bonus_return = (
                "specials", {"module_name": special.module.name})
            change_scene("training")

    def _on_back(self):
        runtime_globals.game_sound.play("cancel")
        self.change_view("main_menu")

    # ------------------------------------------------------------- view hooks

    def cleanup(self):
        for comp in (self.background, self.title_scene, self.strip_image, *self.module_buttons,
                     self.prev_button, self.next_button, *self.tiles,
                     self.open_button, self.back_button):
            if comp and comp in self.ui_manager.components:
                self.ui_manager.remove_component(comp)

    def update(self):
        # OPEN opens the tile last focused.
        for index, tile in enumerate(self.tiles):
            if tile.focused:
                self.current = index
                break

    def handle_event(self, event):
        if not isinstance(event, tuple) or len(event) != 2:
            return
        event_type, event_data = event
        if event_type == "B":
            self._on_back()
            return True
        if event_type == "SCROLL" and self._rows() > VISIBLE_ROWS:
            direction = (event_data or {}).get("direction")
            self._scroll(-1 if direction == "UP" else 1)
            return True
