"""
ProtocolSelector - the device-line picker, laid out as a grid around CANCEL.

The battle formats outgrew a vertical Menu: at eleven lines plus Cancel the
list was taller than the screen. Here every option is a 32x32 box (at 1x)
showing its device icon with the line's name over it. CANCEL holds the
centre box, where the cursor starts, and the lines fill the rest in reading
order -- left to right, top to bottom -- in the order they are given:

    DMOG   PENOG  PROG    PENX   ACCEL
    DMM    IC     TWIN    XWM    DM20
    PEN20  DMX    CANCEL  PENZ   DMC
    PENC   DMXW   .       .      .
    .      .      .       .      .

The grid is the smallest odd one, never taller than wide, that holds every
option, so CANCEL stays in its middle and the cells after the last line are
left empty; 5x5 (24 lines) is the most that fits the screen at 32px a box.
Icons are ``assets/devices/<line>.png``; a line without one shows its name
alone. A line can be shown disabled -- greyed out, focusable so its caption
can be read, but not chosen.

Names use the ordinary text font, because font_load will not draw anything
smaller -- so a five-letter name is a little wider than its box. The name
plate is sized to the name and may reach into the gap, which is why the gap
is wider than the plate can ever reach and only the focused box is outlined.
CANCEL's name would not fit at all, so its box holds an X; the caption under
the grid spells out whatever is focused.

Modal in the same way Menu is: open it, add it to the UIManager and pass it
to ``set_active_menu``, and the manager routes every event here while it is
visible and draws it on top of the view.
"""
import pygame

from core import runtime_globals
from ui.components.component import UIComponent
from ui.ui_constants import BASE_RESOLUTION
from utils.asset_utils import image_load
from utils.pygame_utils import blit_with_cache

#: Where the device icons live, one ``<line>.png`` each.
ICON_DIR = "assets/devices"

#: The centre option's name and caption.
CANCEL_NAME = "CANCEL"
CANCEL_LABEL = "Cancel"

#: The caption after choosing a disabled box.
DISABLED_NOTE = "Coming soon"

#: Box names for lines whose own is wider than a box can show at the
#: smallest size font_load draws; the caption still spells the line out.
SHORT_NAMES = {"PENPROG": "PROG"}


def grid_size(count):
    """The smallest odd ``(columns, rows)`` grid with room for *count* boxes.

    It widens before it grows taller, because the screen has a title above
    the grid and nothing beside it.
    """
    columns = rows = 1
    while columns * rows < count:
        if columns == rows:
            columns += 2
        else:
            rows += 2
    return columns, rows


def fill_order(columns, rows):
    """The centre cell, for CANCEL, then every other cell in reading order."""
    centre = (columns // 2, rows // 2)
    return [centre] + [(col, row) for row in range(rows) for col in range(columns)
                       if (col, row) != centre]


class ProtocolSelector(UIComponent):
    """Grid of device lines with CANCEL in the middle."""

    #: Base (1x) geometry.
    CELL = 32
    #: A name plate may reach into the gap beside its box, never above or
    #: below it, so the columns are further apart than the rows.
    COLUMN_GAP = 6
    ROW_GAP = 4
    PADDING = 6
    CAPTION_HEIGHT = 14
    #: The narrowest the panel gets, so the caption under the grid has room.
    MIN_WIDTH = 200
    #: The scene title's band; the panel is centred in the space below it.
    TITLE_CLEARANCE = 30
    #: Opacity of the plate behind a name and of the name itself; the
    #: focused box shows its name at full strength.
    PLATE_ALPHA = 150
    NAME_ALPHA = 190
    FOCUS_FILL_ALPHA = 60
    #: How much of a disabled box is covered by the well colour.
    DISABLED_VEIL_ALPHA = 170
    #: CANCEL's X: how many pixels long each stroke is, at 1x.
    CROSS_SPAN = 14

    def __init__(self):
        super().__init__(0, 0, self.MIN_WIDTH, self.CELL)
        self.visible = False

        #: [(line or None, name, caption)], CANCEL first.
        self.entries = []
        self.enabled = []
        self.icons = []
        #: (column, row) of each entry, and the reverse.
        self.cells = []
        self.index_at_cell = {}
        self.columns = self.rows = 1
        self.cursor = 0
        #: Shown in the caption in place of the focused label until the
        #: cursor moves.
        self.note = None

        self.on_select = None   # called with the chosen line
        self.on_cancel = None   # called with nothing

        self._scaled_icons = {}
        self._render_key = None

    # ------------------------------------------------------------------
    # Opening and closing
    # ------------------------------------------------------------------

    def open(self, entries, on_select, on_cancel=None, focus=None, note=None):
        """Show the grid.

        Args:
            entries: ``[(line, caption[, enabled]), ...]`` in the order they
                fill the grid, as ``protocol_constants.menu_entries()``
                gives them. A disabled line is shown but cannot be chosen.
            on_select: called with the chosen line.
            on_cancel: called when CANCEL is chosen, B is pressed or the
                player clicks outside the panel.
            focus: the line to start on; CANCEL, the centre, when None or
                not offered.
            note: a caption to show until the cursor first moves, in place
                of the focused line's.
        """
        entries = [(entry[0], entry[1], entry[2] if len(entry) > 2 else True)
                   for entry in entries]
        self.entries = [(None, CANCEL_NAME, CANCEL_LABEL)]
        self.entries += [(key, SHORT_NAMES.get(key, key), caption)
                         for key, caption, _ in entries]
        self.enabled = [True] + [bool(enabled) for _, _, enabled in entries]
        self.icons = [None] + [self._load_icon(key) for key, _, _ in entries]
        self._scaled_icons = {}
        self.on_select = on_select
        self.on_cancel = on_cancel

        self.columns, self.rows = grid_size(len(self.entries))
        self.cells = fill_order(self.columns, self.rows)[:len(self.entries)]
        self.index_at_cell = {cell: i for i, cell in enumerate(self.cells)}

        keys = [key for key, _, _ in self.entries]
        self.cursor = keys.index(focus) if focus in keys[1:] else 0
        self.note = note

        width, height = self._panel_size()
        below_title = BASE_RESOLUTION - self.TITLE_CLEARANCE
        y = self.TITLE_CLEARANCE + (below_title - height) // 2
        self.set_size(width, height)
        self.set_position((BASE_RESOLUTION - width) // 2,
                          max(0, min(y, BASE_RESOLUTION - height)))

        self.visible = True
        self.needs_redraw = True
        runtime_globals.game_console.log(
            f"[ProtocolSelector] Opened {self.columns}x{self.rows} with "
            f"{len(entries)} lines, focus {keys[self.cursor]}")

    def close(self):
        """Hide the grid and stop being the manager's active menu."""
        self.visible = False
        self.needs_redraw = True
        if self.manager and self.manager.active_menu is self:
            self.manager.active_menu = None

    @staticmethod
    def _load_icon(line):
        try:
            return image_load(f"{ICON_DIR}/{line}.png")
        except (pygame.error, OSError):
            runtime_globals.game_console.log(f"[ProtocolSelector] No icon for {line}")
            return None

    def _grid_width(self):
        return self.columns * self.CELL + (self.columns - 1) * self.COLUMN_GAP

    def _grid_height(self):
        return self.rows * self.CELL + (self.rows - 1) * self.ROW_GAP

    def _panel_size(self):
        width = max(self.MIN_WIDTH, self._grid_width() + 2 * self.PADDING)
        height = self._grid_height() + self.CAPTION_HEIGHT + 2 * self.PADDING
        return min(width, BASE_RESOLUTION), height

    def _scale(self):
        return self.manager.ui_scale if self.manager else 1

    def _cell_origin(self, col, row):
        """Top-left of a cell in base pixels, relative to the panel."""
        left = (self.base_rect.width if self.base_rect else self.rect.width) - self._grid_width()
        return (left // 2 + col * (self.CELL + self.COLUMN_GAP),
                self.PADDING + row * (self.CELL + self.ROW_GAP))

    # ------------------------------------------------------------------
    # Cursor
    # ------------------------------------------------------------------

    @property
    def focused_format(self):
        """The line under the cursor, or None on CANCEL."""
        return self.entries[self.cursor][0] if self.entries else None

    def _set_cursor(self, index):
        if index != self.cursor:
            self.cursor = index
            self.note = None
            self.needs_redraw = True

    def _move(self, dx, dy):
        """Step to the next box that way, skipping gaps and wrapping round."""
        col, row = self.cells[self.cursor]
        span = self.columns if dx else self.rows
        for step in range(1, span):
            cell = ((col + dx * step) % self.columns, (row + dy * step) % self.rows)
            index = self.index_at_cell.get(cell)
            if index is not None:
                self._set_cursor(index)
                return True
        return False

    def _index_at(self, pos):
        """The entry under a screen position, or None."""
        scale = self._scale()
        for index, (col, row) in enumerate(self.cells):
            x, y = self._cell_origin(col, row)
            box = pygame.Rect(self.rect.x + x * scale, self.rect.y + y * scale,
                              self.CELL * scale, self.CELL * scale)
            if box.collidepoint(pos):
                return index
        return None

    def _activate(self):
        """Choose the box under the cursor."""
        if not self.enabled[self.cursor]:
            runtime_globals.game_sound.play("cancel")
            self.note = DISABLED_NOTE
            self.needs_redraw = True
            return
        line = self.focused_format
        # Closed before the callback runs, so a callback that opens the next
        # menu is not undone by this one closing after it.
        self.close()
        if line is None:
            runtime_globals.game_sound.play("cancel")
            if self.on_cancel:
                self.on_cancel()
            return
        runtime_globals.game_sound.play("menu")
        if self.on_select:
            self.on_select(line)

    def _cancel(self):
        runtime_globals.game_sound.play("cancel")
        self.close()
        if self.on_cancel:
            self.on_cancel()

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------

    def handle_event(self, event):
        """Blocks every event while visible, as Menu does."""
        if not self.visible or not self.entries:
            return False
        if not isinstance(event, tuple) or len(event) != 2:
            return False
        event_type, event_data = event

        direction = {"UP": (0, -1), "DOWN": (0, 1),
                     "LEFT": (-1, 0), "RIGHT": (1, 0)}.get(event_type)
        if direction:
            if self._move(*direction):
                runtime_globals.game_sound.play("menu")
        elif event_type == "A":
            self._activate()
        elif event_type == "B":
            self._cancel()
        elif event_type in ("LCLICK", "MOUSE_MOTION") and event_data and "pos" in event_data:
            pos = event_data["pos"]
            index = self._index_at(pos)
            if index is not None:
                self._set_cursor(index)
                if event_type == "LCLICK":
                    self._activate()
            elif event_type == "LCLICK" and not self.rect.collidepoint(pos):
                self._cancel()
        return True

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def render(self):
        """The panel, rebuilt only when the cursor, note, size or theme changed.

        The manager calls this every frame for its active menu.
        """
        colors = self.manager.get_theme_colors() if self.manager else {}
        key = (self.cursor, self.note, self.rect.size, tuple(sorted(colors.items())))
        if self.cached_surface is None or self.needs_redraw or key != self._render_key:
            self.cached_surface = self._render_panel(colors)
            self._render_key = key
            self.needs_redraw = False
        return self.cached_surface

    def _icon(self, index, scale):
        icon = self.icons[index]
        if icon is None or scale == 1:
            return icon
        scaled = self._scaled_icons.get((index, scale))
        if scaled is None:
            size = (icon.get_width() * scale, icon.get_height() * scale)
            scaled = self._scaled_icons[(index, scale)] = pygame.transform.scale(icon, size)
        return scaled

    def _render_panel(self, colors):
        bg = colors.get("bg", (0, 0, 0))
        fg = colors.get("fg", (255, 255, 255))
        highlight = colors.get("highlight", fg)
        well = colors.get("black", (31, 32, 38))
        scale = self._scale()

        surface = pygame.Surface(self.rect.size, pygame.SRCALPHA)
        surface.fill(bg)
        pygame.draw.rect(surface, fg, surface.get_rect(), 2 * scale)

        font = self.get_font("text")
        cell_size = self.CELL * scale
        # A plate may reach this far into the gap on each side, which leaves
        # room for the focused outline beside it.
        plate_limit = cell_size + (self.COLUMN_GAP - 2) * scale

        for index, (col, row) in enumerate(self.cells):
            x, y = self._cell_origin(col, row)
            box = pygame.Rect(x * scale, y * scale, cell_size, cell_size)
            focused = index == self.cursor
            color = highlight if focused else fg

            surface.fill(well, box)
            if focused:
                tint = pygame.Surface(box.size, pygame.SRCALPHA)
                tint.fill((*highlight, self.FOCUS_FILL_ALPHA))
                blit_with_cache(surface, tint, box.topleft)
                # Only the focused box is outlined, in the gap outside it, so
                # it never covers an icon's edge. Drawn before the name so a
                # plate wider than the box lies over it rather than under.
                pygame.draw.rect(surface, highlight, box.inflate(4 * scale, 4 * scale), 2 * scale)

            if self.entries[index][0] is None:
                self._draw_cross(surface, box, color, scale)
            else:
                icon = self._icon(index, scale)
                name = self._clip(font.render(self.entries[index][1], True, highlight),
                                  plate_limit - 2 * scale)
                if icon is None:
                    # Nothing to cover: the name is the whole box.
                    blit_with_cache(surface, name, name.get_rect(center=box.center).topleft)
                else:
                    blit_with_cache(surface, icon, icon.get_rect(center=box.center).topleft)
                    self._draw_plate(surface, box, name, focused, scale)

            if not self.enabled[index]:
                veil = pygame.Surface(box.size, pygame.SRCALPHA)
                veil.fill((*well, self.DISABLED_VEIL_ALPHA))
                blit_with_cache(surface, veil, box.topleft)

        caption_text = self.note or self.entries[self.cursor][2]
        caption_color = highlight if self.note or self.enabled[self.cursor] else fg
        caption = self._clip(font.render(caption_text, True, caption_color),
                             surface.get_width() - 2 * self.PADDING * scale)
        caption_top = (self.PADDING + self._grid_height()) * scale
        caption_rect = caption.get_rect(
            center=(surface.get_width() // 2,
                    caption_top + self.CAPTION_HEIGHT * scale // 2 + scale))
        blit_with_cache(surface, caption, caption_rect.topleft)
        return surface

    def _draw_plate(self, surface, box, name, focused, scale):
        """The name over the foot of the icon, on a see-through plate."""
        plate = pygame.Surface((max(box.width, name.get_width() + 2 * scale),
                                name.get_height() + scale), pygame.SRCALPHA)
        plate.fill((0, 0, 0, self.PLATE_ALPHA))
        plate_rect = plate.get_rect(midbottom=box.midbottom)
        blit_with_cache(surface, plate, plate_rect.topleft)
        if not focused:
            name.set_alpha(self.NAME_ALPHA)
        blit_with_cache(surface, name, name.get_rect(center=plate_rect.center).topleft)

    def _draw_cross(self, surface, box, color, scale):
        """CANCEL's X, drawn in whole pixels so it stays as crisp as the icons."""
        span = self.CROSS_SPAN
        left = box.x + (self.CELL - span) // 2 * scale
        top = box.y + (self.CELL - span) // 2 * scale
        for step in range(span - 1):
            for x in (step, span - 2 - step):
                surface.fill(color, (left + x * scale, top + step * scale,
                                     2 * scale, 2 * scale))

    @staticmethod
    def _clip(text, width):
        """*text* cut to *width* pixels, as Grid does with long captions."""
        if text.get_width() <= width:
            return text
        return text.subsurface(pygame.Rect(0, 0, max(1, width), text.get_height())).copy()
