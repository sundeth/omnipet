"""
Scene Collection
================

The card collection: per-module card grids (3 columns) with owned counts,
names and cooldown overlays; a View page for one card with its Use action (a
Collectible card has no use: VIEW opens its close-up, front and back, the
whole screen); a Read page for scanning physical cards over NFC; and a page
to choose which Digimon a card is read for.

A card is read for one Digimon of its own module, whose version decides the
version-specific results (the Digivice iC 10X, 20X and Burst give different
things for the same plate) and who receives its DigiSoul. With one Digimon of
the module in the party it is chosen without asking; with none, only the
results that need no Digimon are given.

A card the player has not obtained shows its number and its back, never its
name; one obtained shows its name and how many copies the player has (x3),
with P for a physical copy and S for shiny ones. A shiny card's art shimmers
(ui.card_holo). FILTER (or SELECT) narrows the grid to one module and can
hide the cards not obtained yet. The grid scrolls with the arrows, the mouse
wheel (a row a notch) and a drag, with a bar at its right showing where it is.

Layout (base 240x240 UI, YELLOW_BRIGHT theme like the Library; every
resolution draws this square at a whole UI scale, its fonts sized to match):
    y 9..25    title "CARDS" (COLLECTION runs into the title bar's chevrons;
               owner, 2026-10-21: "good as just cards"), FILTER at the top right
    y 30..194  the page: card grid, one card, the scan, or the Digimon choice
    y 198..223 VIEW / READ / EXIT, or the page's own USE / BACK: the bottom
               row of the adventure screens (y 198, 25 high, 9 from the edges)

Card data + player state helpers live in utils.card_utils; NFC hardware
access lives in services.nfc_service; a pack's reveal in ui.card_reveal.
"""

import pygame

from ui.ui_manager import UIManager
from ui.components.background import Background
from ui.components.title_scene import TitleScene
from ui.components.button import Button
from ui.components.menu import Menu
from ui.components.pet_selector import PetSelector
from ui.components.reward_popup_ui import RewardPopupUI
from ui.ui_constants import BASE_RESOLUTION, YELLOW_BRIGHT, YELLOW_BRIGHT_DARK
from ui.windows.window_background import WindowBackground
from ui import card_holo
from core import game_globals, runtime_globals
import core.constants as constants
from utils.scene_utils import change_scene
from utils.pygame_utils import blit_with_cache, get_font, rle_accelerate
from utils.asset_utils import image_load
from utils import card_utils
from services.nfc_service import nfc_service

# Base-unit layout constants
CONTENT_TOP = 30
CONTENT_BOTTOM = 194
GRID_COLS = 3
TILE_W = 68
TILE_H = 96
NAME_H = 13           # the name strip at the bottom of a tile (at least)
TILE_GAP = 4
GRID_W = GRID_COLS * TILE_W + (GRID_COLS - 1) * TILE_GAP
GRID_MARGIN_X = (BASE_RESOLUTION - GRID_W) // 2    # the grid sits centred
HEADER_H = 18         # a module's header line (at least)
SCROLLBAR_X = GRID_MARGIN_X + GRID_W + 5           # in the right margin
BUTTON_Y = 198
BUTTON_H = 25
BUTTON_MARGIN_X = 9
BUTTON_GAP = 10

SHINY_GOLD = (255, 220, 80)
#: Seconds a long name waits before it starts to scroll, and its speed
#: (base pixels a second) -- the item lists' pace.
MARQUEE_DELAY = 1.0
MARQUEE_SPEED = 20
#: How fast the grid glides to where the wheel or the arrows sent it (base
#: pixels a second): the item lists' scroll speed (BaseList).
SCROLL_SPEED = 300


class SceneCollection:
    """Card collection scene: grid, View, Read and Digimon-choice pages."""

    def __init__(self) -> None:
        self.window_background = WindowBackground()
        self.ui_manager = UIManager(theme="YELLOW_BRIGHT")
        self.ui_manager.set_input_manager(runtime_globals.game_input)

        self.scale = self.ui_manager.ui_scale
        self.off_x = self.ui_manager.ui_offset_x
        self.off_y = self.ui_manager.ui_offset_y

        # Fonts follow the UI's whole scale, as the layout does: the global
        # FONT_SIZE_* follow the screen height, which outgrows the layout at
        # 240x320, 1400x640 or 1920x1080.
        self.font_small = get_font(int(24 * self.scale))
        self.font_medium = get_font(int(28 * self.scale))
        self.font_name = get_font(max(8, int(16 * self.scale)))
        # The header line and a tile's name strip hold the name font as it
        # comes out (a pixel font snaps to whole multiples of its size, at
        # least the readable floor): base units, never less than the layout's.
        self.header_h = max(HEADER_H, -(-self.font_name.get_linesize() // self.scale) + 1)
        self.name_h = max(NAME_H, -(-self.font_name.get_height() // self.scale))
        # Rendered labels and darkened card faces, kept between frames (the
        # grid redraws every frame; the Pi Zero feels each render).
        self._label_cache = {}
        self._dark_cache = {}
        self._rle_faces = set()

        # Mode: "grid" | "view" | "closeup" | "read" | "pick"
        self.mode = "grid"
        self.selection = 0
        self.scroll_y = 0        # base units, as drawn
        self.scroll_target = 0   # where the wheel or the arrows sent it
        self._drag = None        # (pointer y, scroll_y) while the grid is dragged
        self.frame_counter = 0
        self._marquee_start = 0
        self.closeup_side = "front"
        self._closeup_rect = None

        # Module the grid shows, or None for every module; and whether it
        # hides the cards not obtained yet.
        self.module_filter = None
        self.obtained_only = False

        # Card the View page shows: (module_name, card)
        self.view_card = None
        # The Digimon choice: what to do with the chosen pet, and the page
        # to go back to when the player backs out.
        self._pick_then = None
        self._pick_return = "grid"
        self._pick_title = ""

        # NFC read state
        self.nfc_frames = self._load_nfc_frames()
        self.read_result_handled = False

        # Layout entries built from the modules' card data
        self.entries = []       # {"kind": "header"/"card", ...}
        self.card_entries = []  # cards only, selection indexes into this
        self.total_height = 0
        self._build_layout()

        self._setup_ui()
        self._set_mode("grid")
        runtime_globals.game_console.log(
            f"[SceneCollection] {len(self.card_entries)} cards across "
            f"{len(card_utils.modules_with_cards())} module(s)")

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _setup_ui(self):
        ui_width = ui_height = BASE_RESOLUTION

        self.background = Background(ui_width, ui_height)
        self.background.set_regions([(0, ui_height, "black")])
        self.ui_manager.add_component(self.background)

        self.title_scene = TitleScene(0, 9, "CARDS")
        self.ui_manager.add_component(self.title_scene)

        self.filter_button = Button(ui_width - 55 - 5, 5, 55, 20, "FILTER", self._on_filter)
        self.ui_manager.add_component(self.filter_button)

        # The bottom row spans the screen less BUTTON_MARGIN_X a side.
        row_w = ui_width - 2 * BUTTON_MARGIN_X
        side_w = 66
        middle_w = row_w - 2 * (side_w + BUTTON_GAP)
        self.view_button = Button(BUTTON_MARGIN_X, BUTTON_Y, side_w, BUTTON_H,
                                  "VIEW", self._on_view)
        self.read_button = Button(BUTTON_MARGIN_X + side_w + BUTTON_GAP, BUTTON_Y,
                                  middle_w, BUTTON_H, "READ", self._on_read)
        self.exit_button = Button(ui_width - BUTTON_MARGIN_X - side_w, BUTTON_Y, side_w, BUTTON_H,
                                  "EXIT", self._on_exit)

        # The View page: USE (or VIEW, a Collectible's close-up) and BACK.
        pair_w = (row_w - BUTTON_GAP) // 2
        self.use_button = Button(BUTTON_MARGIN_X, BUTTON_Y, pair_w, BUTTON_H,
                                 "USE", self._view_action)
        self.view_back_button = Button(ui_width - BUTTON_MARGIN_X - pair_w, BUTTON_Y,
                                       pair_w, BUTTON_H, "BACK", self._back)
        # The Read and Digimon-choice pages: BACK alone.
        self.back_button = Button((ui_width - 80) // 2, BUTTON_Y, 80, BUTTON_H, "BACK", self._back)

        for button in (self.view_button, self.read_button, self.exit_button,
                       self.use_button, self.view_back_button, self.back_button):
            self.ui_manager.add_component(button)

        # The Digimon choice: the party, the card's module's pets enabled.
        self.pet_selector = PetSelector(10, 92, ui_width - 20, 50)
        self.pet_selector.set_pets(game_globals.pet_list)
        self.pet_selector.set_interactive(True)
        self.pet_selector.max_selection = 1
        self.pet_selector.activation_callback = self._on_pet_chosen
        self.ui_manager.add_component(self.pet_selector)

        popup_width, popup_height = 200, 80
        self.reward_popup = RewardPopupUI((ui_width - popup_width) // 2, 60,
                                          popup_width, popup_height)
        self.ui_manager.add_component(self.reward_popup)

    def _set_mode(self, mode):
        """Show the page's buttons and give the page its focus."""
        self.mode = mode
        self._drag = None
        groups = {
            "grid": (self.filter_button, self.view_button, self.read_button, self.exit_button),
            "view": (self.use_button, self.view_back_button),
            "read": (self.back_button,),
            "pick": (self.pet_selector, self.back_button),
            "closeup": (),
        }
        shown = groups.get(mode, ())
        if mode == "view" and not self._view_card_usable():
            # Nothing to do with the card: BACK alone, centred.
            shown = (self.back_button,)
        for component in (self.filter_button, self.view_button, self.read_button,
                          self.exit_button, self.use_button, self.view_back_button,
                          self.back_button, self.pet_selector):
            visible = component in shown
            if component.visible != visible:
                component.visible = visible
                component.needs_redraw = True
        self.ui_manager.master_ui_dirty = True

        if mode == "grid":
            self.ui_manager.set_focused_component(self.view_button)
        elif mode == "view":
            self._refresh_view_buttons()
        elif mode == "read":
            self.ui_manager.set_focused_component(self.back_button)
        elif mode == "pick":
            self.ui_manager.set_focused_component(self.pet_selector)

    def _build_layout(self):
        """Build the scrollable layout: a header + tile grid per module (the
        header counts the whole module, also when only the obtained cards
        are shown). The selected card stays selected while it is shown;
        otherwise the first card is."""
        selected = self._selected_key()
        self.entries = []
        self.card_entries = []
        y = 0
        for module_name, data in card_utils.modules_with_cards():
            if self.module_filter and module_name != self.module_filter:
                continue
            cards = card_utils.ordered_cards(data["cards"])
            total, unique, copies = card_utils.module_collection_stats(module_name, cards)
            if self.obtained_only:
                cards = [card for card in cards if self._owned_total(module_name, card) > 0]
                if not cards:
                    continue
            self.entries.append({
                "kind": "header",
                "y": y,
                "text": f"{module_name}  {unique}/{total}  ({copies} cards)",
            })
            y += self.header_h
            for i, card in enumerate(cards):
                col = i % GRID_COLS
                row = i // GRID_COLS
                entry = {
                    "kind": "card",
                    "module": module_name,
                    "card": card,
                    "row": row,
                    "x": GRID_MARGIN_X + col * (TILE_W + TILE_GAP),
                    "y": y + row * (TILE_H + TILE_GAP),
                }
                self.entries.append(entry)
                self.card_entries.append(entry)
            rows = (len(cards) + GRID_COLS - 1) // GRID_COLS
            y += rows * (TILE_H + TILE_GAP) + 6
        self.total_height = y
        keys = [(entry["module"], entry["card"].get("id")) for entry in self.card_entries]
        self.selection = keys.index(selected) if selected in keys else 0
        self.scroll_target = min(self.scroll_target, self._max_scroll())
        self.scroll_y = min(self.scroll_y, self._max_scroll())

    def _selected_key(self):
        """(module, card id) of the selected card, or None."""
        if 0 <= self.selection < len(self.card_entries):
            entry = self.card_entries[self.selection]
            return entry["module"], entry["card"].get("id")
        return None

    def _max_scroll(self):
        return max(0, self.total_height - (CONTENT_BOTTOM - CONTENT_TOP))

    def _load_nfc_frames(self):
        """Library_NFC1-3 recolored to the library theme yellow, UI-scaled."""
        frames = []
        for i in (1, 2, 3):
            try:
                sprite = image_load(f"assets/ui/Library_NFC{i}.png").convert_alpha()
                sprite = self._recolor_to_theme(sprite, YELLOW_BRIGHT)
                size = 48 * self.scale
                frames.append(pygame.transform.scale(sprite, (size, size)))
            except Exception as exc:
                runtime_globals.game_console.log(f"[Collection] NFC frame {i} load failed: {exc}")
        return frames

    @staticmethod
    def _recolor_to_theme(sprite, target_rgb):
        """Map every opaque pixel to the theme color, keeping luminance + alpha.

        The shipped Library_NFC sprites use a placeholder color; this converts
        each pixel's brightness into a shade of the theme yellow.
        """
        recolored = sprite.copy()
        tr, tg, tb = target_rgb
        w, h = recolored.get_size()
        recolored.lock()
        for x in range(w):
            for y in range(h):
                r, g, b, a = recolored.get_at((x, y))
                if a == 0:
                    continue
                lum = max(r, g, b) / 255.0
                recolored.set_at((x, y), (int(tr * lum), int(tg * lum), int(tb * lum), a))
        recolored.unlock()
        return recolored

    # ------------------------------------------------------------------
    # Card helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _owned_total(module_name, card):
        owned = card_utils.get_owned(module_name, card.get("id"))
        return owned["digital"] + owned["physical"]

    @staticmethod
    def _number_text(card):
        """The number printed on the card ("#04"), or "?" for a card with
        none (a Soul Plate)."""
        label = card.get("number_label")
        if label not in (None, ""):
            return f"#{label}"
        number = card.get("number")
        if card.get("type") == "Soul Plate" or number in (None, ""):
            return "?"
        return f"#{number}"

    def _card_name(self, module_name, card):
        """The card's name, or ??? until the player has one."""
        if self._owned_total(module_name, card) <= 0:
            return "???"
        return card.get("name") or "?"

    def _card_face(self, module_name, card, max_w, max_h):
        """The front of an owned card; the back (or the front darkened) of
        one the player does not have."""
        if self._owned_total(module_name, card) > 0:
            return self._fast(card_utils.load_card_sprite(module_name, card, "front", max_w, max_h))
        sprite = card_utils.load_card_sprite(module_name, card, "back", max_w, max_h)
        if sprite is not None:
            return self._fast(sprite)
        key = (module_name, card.get("id"), int(max_w), int(max_h))
        if key not in self._dark_cache:
            sprite = card_utils.load_card_sprite(module_name, card, "front", max_w, max_h)
            if sprite is not None:
                sprite = sprite.copy()
                sprite.fill((40, 40, 40), special_flags=pygame.BLEND_RGB_MULT)
            self._dark_cache[key] = sprite
        return self._fast(self._dark_cache[key])

    def _fast(self, sprite):
        """RLE-encode a card face the first time it is drawn: the grid blits
        up to nine of them a frame, and a per-pixel alpha blit is what the
        Pi Zero 2W's pygame (no NEON) pays most for. Same picture
        (`pygame_utils.rle_accelerate`); nothing draws into card faces."""
        if sprite is not None and id(sprite) not in self._rle_faces:
            self._rle_faces.add(id(sprite))
            rle_accelerate(sprite)
        return sprite

    def _label(self, font, text, colour=YELLOW_BRIGHT):
        """*text* rendered in *font*, from the cache when drawn before."""
        key = (id(font), text, colour)
        label = self._label_cache.get(key)
        if label is None:
            if len(self._label_cache) > 512:
                self._label_cache.clear()
            label = self._label_cache[key] = font.render(text, True, colour)
        return label

    def _marquee_offset(self, text_w, max_w):
        """How far a name too long for its box has scrolled: it waits, then
        runs left and comes round again (all long names together)."""
        delay = int(MARQUEE_DELAY * constants.FRAME_RATE)
        elapsed = self.frame_counter - self._marquee_start - delay
        if elapsed <= 0 or text_w <= max_w:
            return 0
        speed = MARQUEE_SPEED * self.scale / max(1, constants.FRAME_RATE)
        loop = text_w + int(24 * self.scale)
        return int(elapsed * speed) % loop

    def _blit_text_in_box(self, surface, text_surface, rect, center=True):
        """Blit text inside *rect*: centred when it fits, else scrolling."""
        text_w = text_surface.get_width()
        y = rect.y + (rect.height - text_surface.get_height()) // 2
        if text_w <= rect.width:
            x = rect.x + ((rect.width - text_w) // 2 if center else 0)
            surface.blit(text_surface, (x, y))
            return
        old_clip = surface.get_clip()
        surface.set_clip(rect.clip(old_clip) if old_clip else rect)
        offset = self._marquee_offset(text_w, rect.width)
        loop = text_w + int(24 * self.scale)
        surface.blit(text_surface, (rect.x - offset, y))
        if offset > loop - rect.width:
            surface.blit(text_surface, (rect.x - offset + loop, y))
        surface.set_clip(old_clip)

    # ------------------------------------------------------------------
    # Button callbacks
    # ------------------------------------------------------------------

    def _on_view(self):
        if not self.card_entries:
            runtime_globals.game_sound.play("cancel")
            return
        entry = self.card_entries[self.selection]
        self.view_card = (entry["module"], entry["card"])
        self._marquee_start = self.frame_counter
        self._set_mode("view")
        runtime_globals.game_sound.play("menu")

    def _on_read(self):
        if not nfc_service.available():
            runtime_globals.game_sound.play("cancel")
            return
        self.read_result_handled = False
        nfc_service.start()
        self._set_mode("read")
        runtime_globals.game_sound.play("menu")

    def _on_exit(self):
        runtime_globals.game_sound.play("cancel")
        change_scene("library")

    def _back(self):
        """BACK on a page: the View page and the scan return to the grid,
        the Digimon choice to where it was asked from."""
        runtime_globals.game_sound.play("cancel")
        if self.mode == "read":
            nfc_service.stop()
            self._set_mode("grid")
        elif self.mode == "pick":
            self._pick_then = None
            self._set_mode(self._pick_return)
        else:
            self._set_mode("grid")

    def _filter_options(self):
        """The FILTER menu: the obtained-only switch (showing its state),
        then every module ("All") or one module's cards."""
        names = [name for name, _data in card_utils.modules_with_cards()]
        switch = f"Obtained: {'ON' if self.obtained_only else 'OFF'}"
        return [switch, "All"] + names, names

    def _on_filter(self):
        """FILTER: every module or one module's cards, and whether the cards
        not obtained yet are shown."""
        options, names = self._filter_options()
        menu = Menu(width=140, height=min(150, 20 + len(options) * 20))
        menu.open(options=options, on_select=lambda i: self._on_filter_option(i, names),
                  on_cancel=lambda: None, max_visible=6)
        menu.set_selected_index(names.index(self.module_filter) + 2
                                if self.module_filter in names else 1)
        self.ui_manager.set_active_menu(menu)
        runtime_globals.game_sound.play("menu")

    def _on_filter_option(self, index, names):
        if index == 0:
            self._apply_filter(self.module_filter, obtained_only=not self.obtained_only)
        else:
            self._apply_filter(None if index == 1 else names[index - 2])

    def _apply_filter(self, module_name, obtained_only=None):
        """Show *module_name*'s cards (None: every module's), and only the
        obtained ones when *obtained_only* (None keeps the switch)."""
        self.module_filter = module_name
        if obtained_only is not None:
            self.obtained_only = obtained_only
        self.scroll_y = self.scroll_target = 0
        self._marquee_start = self.frame_counter
        self._build_layout()
        if self.card_entries:
            self._scroll_to_selection(instant=True)
        runtime_globals.game_console.log(
            f"[SceneCollection] Filter: {module_name or 'All'}"
            f"{', obtained only' if self.obtained_only else ''}")

    # ------------------------------------------------------------------
    # Reading a card for a Digimon
    # ------------------------------------------------------------------

    def _choose_pet(self, module_name, title, then, return_mode):
        """Ask which of the module's Digimon a card is read for, then call
        *then(pet)*: at once with the only one there is, or None when the
        party has none of the module's Digimon."""
        candidates = card_utils.party_pets_of(module_name)
        if len(candidates) <= 1:
            then(candidates[0] if candidates else None)
            return
        pets = list(game_globals.pet_list)
        self.pet_selector.set_pets(pets)
        self.pet_selector.set_enabled_pets([i for i, pet in enumerate(pets) if pet in candidates])
        self.pet_selector.focused_cell = next(i for i, pet in enumerate(pets) if pet in candidates)
        self._pick_then = then
        self._pick_return = return_mode
        self._pick_title = title
        self._set_mode("pick")

    def _on_pet_chosen(self):
        cell = self.pet_selector.get_activation_cell()
        if cell not in self.pet_selector.enabled_pets or cell >= len(self.pet_selector.pets):
            runtime_globals.game_sound.play("cancel")
            return True
        pet = self.pet_selector.pets[cell]
        then, self._pick_then = self._pick_then, None
        if then:
            then(pet)
        self._set_mode(self._pick_return)
        return True

    def _apply_card(self, module_name, card, effects, pet, start_cooldown=False):
        """Read a card's effects for *pet* (None: no Digimon of its module)."""
        if start_cooldown:
            card_utils.start_cooldown(card.get("id"))
        runtime_globals.game_sound.play("happy")
        runtime_globals.game_console.log(
            f"[SceneCollection] {card.get('name')} read for "
            f"{pet.name if pet is not None else 'no Digimon'} ({module_name})")
        self._apply_outcome(card_utils.apply_card_effects(module_name, effects, pet))
        if self.mode == "view":
            self._refresh_view_buttons()

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(self) -> None:
        self.frame_counter += 1
        self.ui_manager.update()

        # The grid glides to where the wheel or the arrows sent it; a drag
        # moves it directly.
        if self._drag is None and self.scroll_y != self.scroll_target:
            # (a quarter of the way a frame when that is faster: a long
            # jump does not crawl)
            diff = self.scroll_target - self.scroll_y
            step = max(SCROLL_SPEED / max(1, constants.FRAME_RATE), abs(diff) / 4)
            self.scroll_y = self.scroll_target if abs(diff) <= step \
                else self.scroll_y + (step if diff > 0 else -step)

        if self.mode == "read" and not self.read_result_handled:
            result = nfc_service.get_result()
            if result:
                self.read_result_handled = True
                self._handle_nfc_result(result)

    def _handle_nfc_result(self, result):
        """A tag was scanned: register and read a known card, or a random
        effect from an unknown one."""
        nfc_service.stop()
        payload = result.get("card")
        module_name = card = None
        if payload:
            module_name, card = card_utils.find_card_by_id(payload.get("id"))
            if card is None and payload.get("value"):
                value = str(payload["value"]).split("-")[0]
                module_name, card = card_utils.find_card_by_value(
                    value, payload.get("number"))

        if card is not None:
            # Known physical card: add it to the collection, show it, and
            # read it for one of its module's Digimon (physical copies never
            # cool down).
            card_utils.add_card_copy(module_name, card.get("id"), physical=True)
            self._build_layout()
            self.view_card = (module_name, card)
            self._set_mode("view")
            effects = card_utils.resolve_card_effects(module_name, card)
            if effects:
                self._choose_pet(module_name, card.get("name") or "Card",
                                 lambda pet: self._apply_card(module_name, card, effects, pet),
                                 "view")
            else:
                runtime_globals.game_sound.play("happy")
        else:
            # Unknown tag: pick a random effect from any module's table.
            module_name, effects = card_utils.random_effect_group()
            self._set_mode("grid")
            if effects:
                self._choose_pet(module_name, "Card",
                                 lambda pet: self._apply_outcome(
                                     card_utils.apply_card_effects(module_name, effects, pet)),
                                 "grid")
                runtime_globals.game_sound.play("happy")
            else:
                runtime_globals.game_sound.play("cancel")

    def _apply_outcome(self, outcome):
        """Route an apply_card_effects outcome to popup / scene change / sound."""
        if outcome["encounter"]:
            module_name, area, round_num = outcome["encounter"]
            runtime_globals.special_encounter = [module_name, area, round_num]
            change_scene("battle")
            return
        if outcome["unlock"] == "done":
            # Unlocks take effect on the main game scene.
            change_scene("game")
            return
        if outcome["unlock"] == "already":
            runtime_globals.game_sound.play("cancel")
        if outcome["rewards"]:
            self.reward_popup.add_rewards(outcome["rewards"])

    def _use_view_card(self):
        """Use the viewed card's digital copy (starts the 1h cooldown once it
        has been read for a Digimon)."""
        module_name, card = self.view_card
        card_id = card.get("id")
        owned = card_utils.get_owned(module_name, card_id)
        if owned["digital"] <= 0 or card_utils.cooldown_remaining(card_id) > 0:
            runtime_globals.game_sound.play("cancel")
            return
        effects = card_utils.resolve_card_effects(module_name, card)
        if not effects:
            runtime_globals.game_sound.play("cancel")
            return
        runtime_globals.game_sound.play("menu")
        self._choose_pet(module_name, card.get("name") or "Card",
                         lambda pet: self._apply_card(module_name, card, effects, pet,
                                                      start_cooldown=True),
                         "view")

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------

    def handle_event(self, event) -> None:
        if not isinstance(event, tuple) or len(event) != 2:
            return
        event_type, event_data = event
        if self._drag is not None and event_type not in ("DRAG_MOTION", "DRAG_END"):
            # A key, the wheel or a right click ends a drag without DRAG_END.
            self._drag = None

        if self.reward_popup and self.reward_popup.is_active():
            if self.reward_popup.handle_event(event):
                return

        menu = self.ui_manager.active_menu
        if menu is not None and menu.visible:
            self.ui_manager.handle_event(event)
            return

        if self.mode == "closeup":
            self._handle_closeup_event(event_type, event_data)
            return
        if self.mode in ("view", "read", "pick"):
            if event_type == "B":
                self._back()
                return
            self.ui_manager.handle_event(event)
            return

        # Grid: navigation before the UI manager so arrows move the card
        # selection instead of the button focus.
        if event_type in ("LEFT", "RIGHT", "UP", "DOWN") and self.card_entries:
            delta = {"LEFT": -1, "RIGHT": 1,
                     "UP": -GRID_COLS, "DOWN": GRID_COLS}[event_type]
            new_sel = self.selection + delta
            if 0 <= new_sel < len(self.card_entries):
                self.selection = new_sel
                self._scroll_to_selection()
                runtime_globals.game_sound.play("menu")
            return
        if event_type == "A":
            self._on_view()
            return
        if event_type == "START":
            self._on_read()
            return
        if event_type == "SELECT":
            self._on_filter()
            return
        if event_type == "B":
            self._on_exit()
            return
        if event_type == "LCLICK" and event_data and "pos" in event_data:
            # Click on a card tile selects it (second click opens view)
            if self._select_card_at(event_data["pos"]):
                return
        if event_type == "SCROLL" and event_data:
            amount = int(event_data.get("amount", 1) or 1)
            self._scroll_rows(-amount if event_data.get("direction") == "UP" else amount)
            return
        if event_type in ("DRAG_START", "DRAG_MOTION", "DRAG_END") and self._handle_drag(
                event_type, event_data or {}):
            return

        self.ui_manager.handle_event(event)

    def _scroll_rows(self, rows):
        """The mouse wheel: the grid glides a row a notch (the item lists
        scroll an item a notch); the selection stays where it is."""
        target = max(0, min(self.scroll_target + rows * (TILE_H + TILE_GAP), self._max_scroll()))
        if target != self.scroll_target:
            self.scroll_target = target
            runtime_globals.game_sound.play("menu")

    def _handle_drag(self, event_type, event_data):
        """A drag (mouse or touch) started on the grid moves it with the
        pointer, as the item lists do. A drag ends without a click, so it
        never selects a card. True when the drag is the grid's."""
        pos = event_data.get("pos")
        if event_type == "DRAG_START":
            if not pos or not self.card_entries:
                return False
            y = (pos[1] - self.off_y) / self.scale
            x = (pos[0] - self.off_x) / self.scale
            if not (CONTENT_TOP <= y <= CONTENT_BOTTOM and 0 <= x <= BASE_RESOLUTION):
                return False
            self._drag = (pos[1], self.scroll_y)
            self.scroll_target = self.scroll_y
            return True
        if self._drag is None:
            return False
        if event_type == "DRAG_MOTION" and pos:
            start_y, start_scroll = self._drag
            scroll = start_scroll + (start_y - pos[1]) / self.scale
            self.scroll_y = self.scroll_target = max(0, min(scroll, self._max_scroll()))
        elif event_type == "DRAG_END":
            self._drag = None
        return True

    def _view_card_usable(self):
        if not self.view_card:
            return False
        module_name, card = self.view_card
        owned = card_utils.get_owned(module_name, card.get("id"))
        if card_utils.is_collectible(card):
            return owned["digital"] + owned["physical"] > 0
        return owned["digital"] > 0

    def _refresh_view_buttons(self):
        """USE for a digital copy (greyed while it cools down), VIEW for a
        Collectible, nothing for a card the player cannot use."""
        if not self.view_card:
            return
        module_name, card = self.view_card
        if not self._view_card_usable():
            self.ui_manager.set_focused_component(self.back_button)
            return
        collectible = card_utils.is_collectible(card)
        self.use_button.set_text("VIEW" if collectible else "USE")
        ready = collectible or card_utils.cooldown_remaining(card.get("id")) <= 0
        self.use_button.set_enabled(ready)
        self.ui_manager.set_focused_component(
            self.use_button if ready else self.view_back_button)

    def _view_action(self):
        """The View page's left button: USE, or VIEW for a Collectible."""
        if not self.view_card or not self._view_card_usable():
            runtime_globals.game_sound.play("cancel")
            return
        module_name, card = self.view_card
        if card_utils.is_collectible(card):
            self.closeup_side = "front"
            self._set_mode("closeup")
            runtime_globals.game_sound.play("menu")
            return
        self._use_view_card()

    def _handle_closeup_event(self, event_type, event_data):
        """The close-up: LEFT/RIGHT (or A, or a click on the card) turn the
        card over where it has a back; B (or a click off the card) returns
        to the View page."""
        module_name, card = self.view_card
        has_back = card_utils.load_card_sprite(module_name, card, "back", 8, 8) is not None
        if event_type == "B":
            runtime_globals.game_sound.play("cancel")
            self._set_mode("view")
        elif event_type in ("LEFT", "RIGHT", "A") and has_back:
            self.closeup_side = "back" if self.closeup_side == "front" else "front"
            runtime_globals.game_sound.play("menu")
        elif event_type == "A":
            runtime_globals.game_sound.play("cancel")
            self._set_mode("view")
        elif event_type == "LCLICK" and event_data and "pos" in event_data:
            # A click on the card turns it over; anywhere else, back out.
            rect = self._closeup_rect
            if has_back and rect is not None and rect.collidepoint(event_data["pos"]):
                self.closeup_side = "back" if self.closeup_side == "front" else "front"
                runtime_globals.game_sound.play("menu")
            else:
                runtime_globals.game_sound.play("cancel")
                self._set_mode("view")

    def _select_card_at(self, pos):
        """Select (or open) the card tile under a click. True when handled."""
        x = (pos[0] - self.off_x) / self.scale
        y = (pos[1] - self.off_y) / self.scale
        if not (CONTENT_TOP <= y <= CONTENT_BOTTOM):
            return False
        y += self.scroll_y - CONTENT_TOP
        for i, entry in enumerate(self.card_entries):
            if (entry["x"] <= x <= entry["x"] + TILE_W
                    and entry["y"] <= y <= entry["y"] + TILE_H):
                if self.selection == i:
                    self._on_view()
                else:
                    self.selection = i
                    runtime_globals.game_sound.play("menu")
                return True
        return True  # clicks inside the card area never fall through

    def _scroll_to_selection(self, instant=False):
        """Bring the selected card into view (with its module's header when
        it is in the first row): the grid glides there, or jumps when
        *instant*."""
        entry = self.card_entries[self.selection]
        view_h = CONTENT_BOTTOM - CONTENT_TOP
        target = self.scroll_target
        if entry["y"] < target:
            target = entry["y"] - (self.header_h if entry.get("row") == 0 else TILE_GAP)
        elif entry["y"] + TILE_H > target + view_h:
            target = entry["y"] + TILE_H - view_h
        self.scroll_target = max(0, min(target, self._max_scroll()))
        if instant:
            self.scroll_y = self.scroll_target

    # ------------------------------------------------------------------
    # Draw
    # ------------------------------------------------------------------

    def draw(self, surface: pygame.Surface) -> None:
        self.window_background.draw(surface)
        self.ui_manager.draw(surface)

        if self.mode == "grid":
            self._draw_card_area(surface)
        elif self.mode == "view":
            self._draw_view_page(surface)
        elif self.mode == "read":
            self._draw_read_page(surface)
        elif self.mode == "pick":
            self._draw_pick_page(surface)
        elif self.mode == "closeup":
            self._draw_closeup(surface)

        # The filter menu and the reward popup draw through the UI manager,
        # under the page drawn above: draw them again on top.
        menu = self.ui_manager.active_menu
        if menu is not None and menu.visible:
            blit_with_cache(surface, menu.render(), (menu.rect.x, menu.rect.y))
        if self.reward_popup and self.reward_popup.is_active():
            popup_surface = self.reward_popup.render()
            blit_with_cache(surface, popup_surface, self.reward_popup.rect.topleft)

    def _sx(self, base_x):
        return self.off_x + int(base_x * self.scale)

    def _sy(self, base_y):
        return self.off_y + int(base_y * self.scale)

    def _badge(self, surface, text, colour, right, bottom=None, top=None):
        """A small label on a dark plate, in the theme's style."""
        label = self._label(self.font_name, text, colour)
        pad = max(1, int(2 * self.scale))
        w, h = label.get_width() + pad * 2, label.get_height()
        y = top if top is not None else bottom - h
        surface.fill((0, 0, 0), (right - w, y, w, h))
        surface.blit(label, (right - w + pad, y))
        return w

    def _draw_card_area(self, surface):
        if not self.entries:
            obtained = self.obtained_only and card_utils.modules_with_cards()
            text = self._label(self.font_medium,
                               "No cards obtained" if obtained else "No cards available")
            middle = self._sy((CONTENT_TOP + CONTENT_BOTTOM) // 2)
            surface.blit(text, (self._sx(120) - text.get_width() // 2,
                                middle - text.get_height() // 2))
            return

        clip_rect = pygame.Rect(
            self._sx(0), self._sy(CONTENT_TOP),
            int(BASE_RESOLUTION * self.scale), int((CONTENT_BOTTOM - CONTENT_TOP) * self.scale))
        old_clip = surface.get_clip()
        surface.set_clip(clip_rect.clip(old_clip) if old_clip else clip_rect)

        view_top = self.scroll_y
        view_bottom = self.scroll_y + (CONTENT_BOTTOM - CONTENT_TOP)

        for entry in self.entries:
            ey = entry["y"]
            eh = self.header_h if entry["kind"] == "header" else TILE_H
            if ey + eh < view_top or ey > view_bottom:
                continue
            screen_y = self._sy(CONTENT_TOP + ey - self.scroll_y)
            if entry["kind"] == "header":
                # In the tiles' name font: the larger one ran into the grid.
                text = self._label(self.font_name, entry["text"])
                box = pygame.Rect(self._sx(GRID_MARGIN_X), screen_y,
                                  int(GRID_W * self.scale), int(self.header_h * self.scale))
                self._blit_text_in_box(surface, text, box, center=False)
            else:
                self._draw_card_tile(surface, entry, screen_y)

        surface.set_clip(old_clip)
        self._draw_scrollbar(surface)

    def _draw_scrollbar(self, surface):
        """Where the grid is: a thin track in the right margin, its thumb
        as tall as the share of the grid on screen."""
        view_h = CONTENT_BOTTOM - CONTENT_TOP
        max_scroll = self._max_scroll()
        if max_scroll <= 0:
            return
        unit = max(1, int(self.scale))
        track = pygame.Rect(self._sx(SCROLLBAR_X + 1), self._sy(CONTENT_TOP), unit,
                            int(view_h * self.scale))
        surface.fill(YELLOW_BRIGHT_DARK, track)
        thumb_h = max(int(12 * self.scale), track.height * view_h // self.total_height)
        share = min(1.0, max(0.0, self.scroll_y / max_scroll))
        thumb_y = track.y + int((track.height - thumb_h) * share)
        surface.fill(YELLOW_BRIGHT, (track.x - unit, thumb_y, unit * 3, thumb_h))

    def _draw_card_tile(self, surface, entry, screen_y):
        module_name, card = entry["module"], entry["card"]
        card_id = card.get("id")
        screen_x = self._sx(entry["x"])
        tile_w = int(TILE_W * self.scale)
        tile_h = int(TILE_H * self.scale)
        name_h = int(self.name_h * self.scale)
        image_h = tile_h - name_h
        owned = card_utils.get_owned(module_name, card_id)
        total = owned["digital"] + owned["physical"]
        selected = (self.card_entries[self.selection] is entry) if self.card_entries else False

        sprite = self._card_face(module_name, card, tile_w - 2, image_h - 2)
        if sprite is not None:
            sx = screen_x + (tile_w - sprite.get_width()) // 2
            sy = screen_y + (image_h - sprite.get_height()) // 2
            blit_with_cache(surface, sprite, (sx, sy))
            if owned["shiny"] > 0:
                card_holo.draw_holo(surface, card, pygame.Rect((sx, sy), sprite.get_size()),
                                    self.scale)
        else:
            surface.fill((40, 40, 40), (screen_x, screen_y, tile_w, image_h))

        # The name strip: the name of a card the player has, else its number.
        strip = pygame.Rect(screen_x, screen_y + image_h, tile_w, name_h)
        surface.fill((0, 0, 0), strip)
        if total > 0:
            label = self._label(self.font_name, card.get("name") or "?")
        else:
            label = self._label(self.font_name, self._number_text(card))
        self._blit_text_in_box(surface, label, strip.inflate(-int(4 * self.scale), 0))

        if total > 0:
            image_bottom = screen_y + image_h
            self._badge(surface, f"x{total}", YELLOW_BRIGHT, screen_x + tile_w, bottom=image_bottom)
            if owned["physical"] > 0:
                label = self._label(self.font_name, "P")
                pad = max(1, int(2 * self.scale))
                surface.fill((0, 0, 0), (screen_x, screen_y, label.get_width() + pad * 2,
                                         label.get_height()))
                surface.blit(label, (screen_x + pad, screen_y))
            if owned["shiny"] > 0:
                self._badge(surface, f"S{owned['shiny']}", SHINY_GOLD,
                            screen_x + tile_w, top=screen_y)

            # Cooldown overlay (digital use): covers the remaining fraction,
            # shrinking downward until usable again.
            if owned["digital"] > 0:
                frac = card_utils.cooldown_fraction(card_id)
                if frac > 0:
                    overlay = pygame.Surface((tile_w, int(image_h * frac)))
                    overlay.fill((0, 0, 0))
                    overlay.set_alpha(160)
                    surface.blit(overlay, (screen_x, screen_y))

        if selected:
            pygame.draw.rect(surface, YELLOW_BRIGHT,
                             (screen_x - 1, screen_y - 1, tile_w + 2, tile_h + 2),
                             max(1, int(self.scale)))

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------

    def _draw_view_page(self, surface):
        """One card: its name (??? until obtained), number and copies, the
        card, and its cooldown."""
        module_name, card = self.view_card
        card_id = card.get("id")
        owned = card_utils.get_owned(module_name, card_id)
        total = owned["digital"] + owned["physical"]

        name_box = pygame.Rect(self._sx(8), self._sy(CONTENT_TOP + 2),
                               int((BASE_RESOLUTION - 16) * self.scale), 0)
        title = self._label(self.font_medium, self._card_name(module_name, card))
        name_box.height = title.get_height()
        self._blit_text_in_box(surface, title, name_box)

        details = [self._number_text(card)] if self._number_text(card) != "?" else []
        if total > 0:
            details.append(f"x{total}")
            if owned["physical"]:
                details.append(f"{owned['physical']} physical")
            if owned["shiny"]:
                details.append(f"{owned['shiny']} shiny")
        else:
            details.append("not obtained")
        info = self._label(self.font_small, "  ".join(details))
        info_box = pygame.Rect(name_box.x, name_box.bottom + int(1 * self.scale),
                               name_box.width, info.get_height())
        self._blit_text_in_box(surface, info, info_box)

        top = info_box.bottom + int(3 * self.scale)
        bottom = self._sy(CONTENT_BOTTOM)
        max_w, max_h = int(150 * self.scale), bottom - top
        sprite = self._card_face(module_name, card, max_w, max_h)
        if sprite is None:
            return
        sx = self._sx(120) - sprite.get_width() // 2
        blit_with_cache(surface, sprite, (sx, top))
        if owned["shiny"] > 0:
            card_holo.draw_holo(surface, card, pygame.Rect((sx, top), sprite.get_size()),
                                self.scale)

        # Cooldown overlay on the large card
        if owned["digital"] > 0:
            frac = card_utils.cooldown_fraction(card_id)
            if frac > 0:
                cd = pygame.Surface((sprite.get_width(), int(sprite.get_height() * frac)))
                cd.fill((0, 0, 0))
                cd.set_alpha(170)
                surface.blit(cd, (sx, top))
                remaining = int(card_utils.cooldown_remaining(card_id))
                label = f"{remaining // 3600}:{remaining % 3600 // 60:02d}:{remaining % 60:02d}" \
                    if remaining >= 3600 else f"{remaining // 60}:{remaining % 60:02d}"
                cd_label = self.font_small.render(label, True, YELLOW_BRIGHT)
                surface.blit(cd_label, (self._sx(120) - cd_label.get_width() // 2,
                                        top + int(4 * self.scale)))
            elif not self.use_button.enabled and not card_utils.is_collectible(card):
                # The cooldown just ended: offer USE again.
                self._refresh_view_buttons()
        if owned["physical"] > 0 and owned["digital"] == 0 and not card_utils.is_collectible(card):
            note = self.font_small.render("Physical card: view only", True, YELLOW_BRIGHT)
            surface.blit(note, (self._sx(120) - note.get_width() // 2,
                                bottom - note.get_height()))

    def _draw_closeup(self, surface):
        """A Collectible card up close: the whole screen, front or back."""
        module_name, card = self.view_card
        width, height = surface.get_size()
        surface.fill((0, 0, 0))
        side = self.closeup_side
        margin = int(6 * self.scale)
        sprite = card_utils.load_card_sprite(module_name, card, side,
                                             width - 2 * margin, height - 2 * margin)
        if sprite is None and side == "back":
            side = "front"
            sprite = card_utils.load_card_sprite(module_name, card, "front",
                                                 width - 2 * margin, height - 2 * margin)
        self._closeup_rect = None
        if sprite is not None:
            pos = ((width - sprite.get_width()) // 2, (height - sprite.get_height()) // 2)
            self._closeup_rect = pygame.Rect(pos, sprite.get_size())
            blit_with_cache(surface, self._fast(sprite), pos)
            if side == "front" and card_utils.get_owned(module_name, card.get("id"))["shiny"] > 0:
                card_holo.draw_holo(surface, card, self._closeup_rect, self.scale)

    def _draw_read_page(self, surface):
        title = self._label(self.font_medium, "SCAN CARD")
        surface.blit(title, (self._sx(120) - title.get_width() // 2, self._sy(48)))

        # 3-frame NFC animation (~3 fps)
        if self.nfc_frames:
            frame_idx = (self.frame_counter // max(1, constants.FRAME_RATE // 3)) % len(self.nfc_frames)
            frame = self.nfc_frames[frame_idx]
            surface.blit(frame, (self._sx(120) - frame.get_width() // 2, self._sy(78)))

        hint = self._label(self.font_name, "Hold a card near the reader")
        box = pygame.Rect(self._sx(8), self._sy(140), int((BASE_RESOLUTION - 16) * self.scale),
                          hint.get_height())
        self._blit_text_in_box(surface, hint, box)

    def _draw_pick_page(self, surface):
        # The question and the card's name stacked above the party row
        # (y 92..142), the focused Digimon under it.
        width = int((BASE_RESOLUTION - 16) * self.scale)
        title = self._label(self.font_medium, "Read for which Digimon?")
        if title.get_width() > width:
            title = self._label(self.font_small, "Read for which Digimon?")
        box = pygame.Rect(self._sx(8), self._sy(CONTENT_TOP + 4), width, title.get_height())
        self._blit_text_in_box(surface, title, box)
        name = self._label(self.font_name, self._pick_title)
        box = pygame.Rect(self._sx(8), box.bottom + int(2 * self.scale), width, name.get_height())
        self._blit_text_in_box(surface, name, box)
        cell = self.pet_selector.focused_cell
        pets = self.pet_selector.pets
        if 0 <= cell < len(pets) and pets[cell] is not None:
            pet = pets[cell]
            label = self._label(self.font_name,
                                f"{pet.name} ({pet.module} v{getattr(pet, 'version', '?')})")
            box = pygame.Rect(self._sx(8), self._sy(146), width, label.get_height())
            self._blit_text_in_box(surface, label, box)
