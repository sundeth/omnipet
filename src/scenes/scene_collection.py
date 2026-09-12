"""
Scene Collection
================

The card collection: per-module card grids (3 columns) with owned counts and
cooldown overlays, a View window for a large card + Use action, and an NFC
Read modal for scanning physical cards.

Layout (base 240x240 UI, YELLOW_BRIGHT theme like the Library):
    y 9..28    title "COLLECTION"
    y 28..178  scrollable card area (module header + grid per module)
    y 182..    VIEW / READ / EXIT buttons

Card data + player state helpers live in utils.card_utils; NFC hardware
access lives in services.nfc_service.
"""

import pygame

from ui.ui_manager import UIManager
from ui.components.background import Background
from ui.components.title_scene import TitleScene
from ui.components.button import Button
from ui.components.reward_popup_ui import RewardPopupUI
from ui.ui_constants import BASE_RESOLUTION, YELLOW_BRIGHT, YELLOW_BRIGHT_DARK
from ui.windows.window_background import WindowBackground
from core import game_globals, runtime_globals
import core.constants as constants
from utils.scene_utils import change_scene
from utils.pygame_utils import blit_with_cache, get_font
from utils.asset_utils import image_load
from utils import card_utils
from services.nfc_service import nfc_service

# Base-unit layout constants
CONTENT_TOP = 28
CONTENT_BOTTOM = 178
GRID_MARGIN_X = 8
GRID_COLS = 3
TILE_W = 68
TILE_H = 96
TILE_GAP = 4
HEADER_H = 16


class SceneCollection:
    """Card collection scene with per-module grids, View window and NFC Read modal."""

    def __init__(self) -> None:
        self.window_background = WindowBackground()
        self.ui_manager = UIManager(theme="YELLOW_BRIGHT")
        self.ui_manager.set_input_manager(runtime_globals.game_input)

        self.scale = self.ui_manager.ui_scale
        self.off_x = self.ui_manager.ui_offset_x
        self.off_y = self.ui_manager.ui_offset_y

        self.font_small = get_font(runtime_globals.FONT_SIZE_SMALL)
        self.font_medium = get_font(runtime_globals.FONT_SIZE_MEDIUM)

        # Mode: "grid" | "view" | "read"
        self.mode = "grid"
        self.selection = 0
        self.scroll_y = 0  # base units
        self.view_focus = 0  # 0 = Use, 1 = Back
        self.frame_counter = 0

        # Card the view window shows: (module_name, card)
        self.view_card = None

        # NFC read state
        self.nfc_frames = self._load_nfc_frames()
        self.read_result_handled = False

        # Layout entries built from the modules' card data
        self.entries = []       # {"kind": "header"/"card", ...}
        self.card_entries = []  # cards only, selection indexes into this
        self.total_height = 0
        self._build_layout()

        self._setup_ui()
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

        self.title_scene = TitleScene(0, 9, "COLLECTION")
        self.ui_manager.add_component(self.title_scene)

        button_y = 182
        button_w = 70
        button_h = 30
        spacing = 5
        start_x = (ui_width - (button_w * 3 + spacing * 2)) // 2

        self.view_button = Button(start_x, button_y, button_w, button_h,
                                  "VIEW", self._on_view)
        self.ui_manager.add_component(self.view_button)

        self.read_button = Button(start_x + button_w + spacing, button_y,
                                  button_w, button_h, "READ", self._on_read)
        self.ui_manager.add_component(self.read_button)

        self.exit_button = Button(start_x + (button_w + spacing) * 2, button_y,
                                  button_w, button_h, "EXIT", self._on_exit)
        self.ui_manager.add_component(self.exit_button)

        popup_width, popup_height = 200, 80
        self.reward_popup = RewardPopupUI((ui_width - popup_width) // 2, 60,
                                          popup_width, popup_height)
        self.ui_manager.add_component(self.reward_popup)

        self.ui_manager.set_focused_component(self.view_button)

    def _build_layout(self):
        """Build the scrollable layout: a header + tile grid per module."""
        self.entries = []
        self.card_entries = []
        y = 0
        for module_name, data in card_utils.modules_with_cards():
            cards = card_utils.ordered_cards(data["cards"])
            total, unique, copies = card_utils.module_collection_stats(module_name, cards)
            self.entries.append({
                "kind": "header",
                "y": y,
                "text": f"{module_name}  {unique}/{total} · {copies} cards",
            })
            y += HEADER_H
            for i, card in enumerate(cards):
                col = i % GRID_COLS
                row = i // GRID_COLS
                entry = {
                    "kind": "card",
                    "module": module_name,
                    "card": card,
                    "x": GRID_MARGIN_X + col * (TILE_W + TILE_GAP),
                    "y": y + row * (TILE_H + TILE_GAP),
                }
                self.entries.append(entry)
                self.card_entries.append(entry)
            rows = (len(cards) + GRID_COLS - 1) // GRID_COLS
            y += rows * (TILE_H + TILE_GAP) + 6
        self.total_height = y

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
    # Button callbacks
    # ------------------------------------------------------------------

    def _on_view(self):
        if not self.card_entries:
            runtime_globals.game_sound.play("cancel")
            return
        entry = self.card_entries[self.selection]
        self.view_card = (entry["module"], entry["card"])
        self.view_focus = 1  # default focus on Back
        self.mode = "view"
        runtime_globals.game_sound.play("menu")

    def _on_read(self):
        if not nfc_service.available():
            runtime_globals.game_sound.play("cancel")
            return
        self.mode = "read"
        self.read_result_handled = False
        nfc_service.start()
        runtime_globals.game_sound.play("menu")

    def _on_exit(self):
        runtime_globals.game_sound.play("cancel")
        change_scene("library")

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(self) -> None:
        self.frame_counter += 1
        self.ui_manager.update()

        if self.mode == "read" and not self.read_result_handled:
            result = nfc_service.get_result()
            if result:
                self.read_result_handled = True
                self._handle_nfc_result(result)

    def _handle_nfc_result(self, result):
        """A tag was scanned: register/apply a known card, or a random effect."""
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
            # Known physical card: add to the collection, show it, apply its
            # effects (physical copies never cool down).
            card_utils.add_card_copy(module_name, card.get("id"), physical=True)
            self._build_layout()
            runtime_globals.game_sound.play("happy")
            self.view_card = (module_name, card)
            self.view_focus = 1
            self.mode = "view"
            effects = card_utils.resolve_card_effects(module_name, card)
            self._apply_outcome(card_utils.apply_card_effects(module_name, effects))
        else:
            # Unknown tag: pick a random effect from any module's table.
            module_name, effects = card_utils.random_effect_group()
            self.mode = "grid"
            if effects:
                runtime_globals.game_sound.play("happy")
                self._apply_outcome(card_utils.apply_card_effects(module_name, effects))
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
        """Use the viewed card's digital copy (starts the 1h cooldown)."""
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
        card_utils.start_cooldown(card_id)
        runtime_globals.game_sound.play("menu")
        self._apply_outcome(card_utils.apply_card_effects(module_name, effects))

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------

    def handle_event(self, event) -> None:
        if not isinstance(event, tuple) or len(event) != 2:
            return
        event_type, event_data = event

        if self.reward_popup and self.reward_popup.is_active():
            if self.reward_popup.handle_event(event):
                return

        if self.mode == "view":
            self._handle_view_event(event_type, event_data)
            return
        if self.mode == "read":
            self._handle_read_event(event_type, event_data)
            return

        # Grid mode: navigation before the UI manager so arrows move the
        # card selection instead of the button focus.
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
        if event_type == "B":
            self._on_exit()
            return
        if event_type == "LCLICK" and event_data and "pos" in event_data:
            # Click on a card tile selects it (second click opens view)
            if self._select_card_at(event_data["pos"]):
                return

        self.ui_manager.handle_event(event)

    def _handle_view_event(self, event_type, event_data):
        can_use = self._view_card_usable()
        if event_type == "B":
            runtime_globals.game_sound.play("cancel")
            self.mode = "grid"
        elif event_type in ("LEFT", "RIGHT") and can_use:
            self.view_focus = 1 - self.view_focus
            runtime_globals.game_sound.play("menu")
        elif event_type == "A":
            if self.view_focus == 0 and can_use:
                self._use_view_card()
            else:
                runtime_globals.game_sound.play("cancel")
                self.mode = "grid"
        elif event_type == "LCLICK" and event_data and "pos" in event_data:
            use_rect, back_rect = self._view_button_rects()
            pos = event_data["pos"]
            if can_use and use_rect.collidepoint(pos):
                self._use_view_card()
            elif back_rect.collidepoint(pos):
                runtime_globals.game_sound.play("cancel")
                self.mode = "grid"

    def _handle_read_event(self, event_type, event_data):
        if event_type in ("B", "A"):
            nfc_service.stop()
            runtime_globals.game_sound.play("cancel")
            self.mode = "grid"
        elif event_type == "LCLICK" and event_data and "pos" in event_data:
            if self._read_back_rect().collidepoint(event_data["pos"]):
                nfc_service.stop()
                runtime_globals.game_sound.play("cancel")
                self.mode = "grid"

    def _view_card_usable(self):
        if not self.view_card:
            return False
        module_name, card = self.view_card
        owned = card_utils.get_owned(module_name, card.get("id"))
        return owned["digital"] > 0

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

    def _scroll_to_selection(self):
        entry = self.card_entries[self.selection]
        view_h = CONTENT_BOTTOM - CONTENT_TOP
        if entry["y"] < self.scroll_y:
            self.scroll_y = max(0, entry["y"] - HEADER_H)
        elif entry["y"] + TILE_H > self.scroll_y + view_h:
            self.scroll_y = entry["y"] + TILE_H - view_h
        max_scroll = max(0, self.total_height - view_h)
        self.scroll_y = max(0, min(self.scroll_y, max_scroll))

    # ------------------------------------------------------------------
    # Draw
    # ------------------------------------------------------------------

    def draw(self, surface: pygame.Surface) -> None:
        self.window_background.draw(surface)
        self.ui_manager.draw(surface)
        self._draw_card_area(surface)

        if self.mode == "view":
            self._draw_view_window(surface)
        elif self.mode == "read":
            self._draw_read_modal(surface)

        # Reward popup renders through the UI manager, but modals draw over
        # it — re-draw on top while active so rewards stay visible.
        if self.reward_popup and self.reward_popup.is_active():
            popup_surface = self.reward_popup.render()
            blit_with_cache(surface, popup_surface, self.reward_popup.rect.topleft)

    def _sx(self, base_x):
        return self.off_x + int(base_x * self.scale)

    def _sy(self, base_y):
        return self.off_y + int(base_y * self.scale)

    def _draw_card_area(self, surface):
        if not self.entries:
            text = self.font_medium.render("No cards available", True, (200, 200, 200))
            surface.blit(text, (self._sx(120) - text.get_width() // 2, self._sy(96)))
            return

        clip_rect = pygame.Rect(
            self._sx(0), self._sy(CONTENT_TOP),
            int(BASE_RESOLUTION * self.scale), int((CONTENT_BOTTOM - CONTENT_TOP) * self.scale))
        old_clip = surface.get_clip()
        surface.set_clip(clip_rect)

        view_top = self.scroll_y
        view_bottom = self.scroll_y + (CONTENT_BOTTOM - CONTENT_TOP)

        for entry in self.entries:
            ey = entry["y"]
            eh = HEADER_H if entry["kind"] == "header" else TILE_H
            if ey + eh < view_top or ey > view_bottom:
                continue
            screen_y = self._sy(CONTENT_TOP + ey - self.scroll_y)
            if entry["kind"] == "header":
                text = self.font_small.render(entry["text"], True, YELLOW_BRIGHT)
                surface.blit(text, (self._sx(GRID_MARGIN_X), screen_y))
            else:
                self._draw_card_tile(surface, entry, screen_y)

        surface.set_clip(old_clip)

    def _draw_card_tile(self, surface, entry, screen_y):
        module_name, card = entry["module"], entry["card"]
        card_id = card.get("id")
        screen_x = self._sx(entry["x"])
        tile_w = int(TILE_W * self.scale)
        tile_h = int(TILE_H * self.scale)
        owned = card_utils.get_owned(module_name, card_id)
        total = owned["digital"] + owned["physical"]
        selected = (self.card_entries[self.selection] is entry) if self.card_entries else False

        # Sprite: front when owned, back (or placeholder) when not
        side = "front" if total > 0 else "back"
        sprite = card_utils.load_card_sprite(module_name, card, side,
                                             tile_w - 2, tile_h - 2)
        if sprite is None and side == "back":
            sprite = card_utils.load_card_sprite(module_name, card, "front",
                                                 tile_w - 2, tile_h - 2)
            if sprite is not None and total == 0:
                # No back art: darken the front as the unowned placeholder
                sprite = sprite.copy()
                sprite.fill((40, 40, 40), special_flags=pygame.BLEND_RGB_MULT)

        if sprite is not None:
            sx = screen_x + (tile_w - sprite.get_width()) // 2
            sy = screen_y + (tile_h - sprite.get_height()) // 2
            blit_with_cache(surface, sprite, (sx, sy))
        else:
            pygame.draw.rect(surface, (40, 40, 40), (screen_x, screen_y, tile_w, tile_h))

        if total == 0:
            number = card.get("number") or 0
            label = card.get("name", "?") if card.get("type") == "Soul Plate" else f"#{number}"
            text = self.font_small.render(label, True, (160, 160, 160))
            surface.blit(text, (screen_x + (tile_w - text.get_width()) // 2,
                                screen_y + tile_h - text.get_height() - 2))
        else:
            # Copy count bottom-right
            count_text = self.font_small.render(f"x{total}", True, (255, 255, 255))
            tx = screen_x + tile_w - count_text.get_width() - 2
            ty = screen_y + tile_h - count_text.get_height() - 2
            pygame.draw.rect(surface, (0, 0, 0),
                             (tx - 2, ty, count_text.get_width() + 4, count_text.get_height()))
            surface.blit(count_text, (tx, ty))

            # Physical badge top-left
            if owned["physical"] > 0:
                badge = self.font_small.render("P", True, (0, 0, 0))
                bw = badge.get_width() + int(4 * self.scale)
                bh = badge.get_height()
                pygame.draw.rect(surface, YELLOW_BRIGHT, (screen_x, screen_y, bw, bh))
                surface.blit(badge, (screen_x + int(2 * self.scale), screen_y))

            if owned["shiny"] > 0:
                badge = self.font_small.render(
                    f"S{owned['shiny']}", True, (0, 0, 0))
                bw = badge.get_width() + int(4 * self.scale)
                bh = badge.get_height()
                bx = screen_x + tile_w - bw
                pygame.draw.rect(surface, (255, 220, 80),
                                 (bx, screen_y, bw, bh))
                surface.blit(badge, (bx + int(2 * self.scale), screen_y))

            # Cooldown overlay (digital use): covers the remaining fraction,
            # shrinking downward until usable again.
            if owned["digital"] > 0:
                frac = card_utils.cooldown_fraction(card_id)
                if frac > 0:
                    overlay_h = int(tile_h * frac)
                    overlay = pygame.Surface((tile_w, overlay_h))
                    overlay.fill((0, 0, 0))
                    overlay.set_alpha(160)
                    surface.blit(overlay, (screen_x, screen_y))

        if selected:
            pygame.draw.rect(surface, YELLOW_BRIGHT,
                             (screen_x - 1, screen_y - 1, tile_w + 2, tile_h + 2),
                             max(1, int(self.scale)))

    # ------------------------------------------------------------------
    # View window
    # ------------------------------------------------------------------

    def _view_button_rects(self):
        """Screen-space rects for the view window's Use and Back buttons."""
        bw, bh = int(60 * self.scale), int(22 * self.scale)
        gap = int(10 * self.scale)
        cx = self._sx(BASE_RESOLUTION // 2)
        y = self._sy(196)
        use_rect = pygame.Rect(cx - bw - gap // 2, y, bw, bh)
        back_rect = pygame.Rect(cx + gap // 2, y, bw, bh)
        return use_rect, back_rect

    def _draw_view_window(self, surface):
        module_name, card = self.view_card
        card_id = card.get("id")
        owned = card_utils.get_owned(module_name, card_id)
        total = owned["digital"] + owned["physical"]

        overlay = pygame.Surface(surface.get_size())
        overlay.fill((0, 0, 0))
        overlay.set_alpha(200)
        surface.blit(overlay, (0, 0))

        # Card name + counts
        name = card.get("name") or "?"
        title = self.font_medium.render(name, True, YELLOW_BRIGHT)
        surface.blit(title, (self._sx(120) - title.get_width() // 2, self._sy(12)))
        details = []
        if owned["physical"]:
            details.append(f"{owned['physical']} physical")
        if owned["shiny"]:
            details.append(f"{owned['shiny']} shiny")
        info = f"x{total}" + (f"  ({', '.join(details)})" if details else "")
        info_text = self.font_small.render(info, True, (220, 220, 220))
        surface.blit(info_text, (self._sx(120) - info_text.get_width() // 2, self._sy(26)))

        # Large card sprite
        max_w, max_h = int(120 * self.scale), int(150 * self.scale)
        sprite = card_utils.load_card_sprite(module_name, card, "front", max_w, max_h)
        if sprite is not None:
            sx = self._sx(120) - sprite.get_width() // 2
            sy = self._sy(40)
            if total == 0:
                sprite = sprite.copy()
                sprite.fill((40, 40, 40), special_flags=pygame.BLEND_RGB_MULT)
            blit_with_cache(surface, sprite, (sx, sy))

            # Cooldown overlay on the large card
            if owned["digital"] > 0:
                frac = card_utils.cooldown_fraction(card_id)
                if frac > 0:
                    cd = pygame.Surface((sprite.get_width(), int(sprite.get_height() * frac)))
                    cd.fill((0, 0, 0))
                    cd.set_alpha(170)
                    surface.blit(cd, (sx, sy))
                    remaining = int(card_utils.cooldown_remaining(card_id))
                    cd_label = self.font_small.render(
                        f"{remaining // 60}:{remaining % 60:02d}", True, (255, 255, 255))
                    surface.blit(cd_label, (self._sx(120) - cd_label.get_width() // 2,
                                            sy + int(4 * self.scale)))

        # Buttons: Use (digital only) + Back
        can_use = owned["digital"] > 0
        use_rect, back_rect = self._view_button_rects()
        if can_use:
            ready = card_utils.cooldown_remaining(card_id) <= 0
            self._draw_modal_button(surface, use_rect, "USE",
                                    focused=(self.view_focus == 0), enabled=ready)
        else:
            self.view_focus = 1
        self._draw_modal_button(surface, back_rect, "BACK",
                                focused=(self.view_focus == 1), enabled=True)

        if owned["physical"] > 0 and owned["digital"] == 0:
            note = self.font_small.render("Physical card - view only", True, (180, 180, 180))
            surface.blit(note, (self._sx(120) - note.get_width() // 2, self._sy(222)))

    def _draw_modal_button(self, surface, rect, label, focused, enabled):
        bg = YELLOW_BRIGHT_DARK if focused else (30, 30, 30)
        fg = (0, 0, 0) if focused else (YELLOW_BRIGHT if enabled else (110, 110, 110))
        pygame.draw.rect(surface, bg, rect)
        pygame.draw.rect(surface, YELLOW_BRIGHT if enabled else (110, 110, 110), rect,
                         max(1, int(self.scale)))
        text = self.font_small.render(label, True, fg)
        surface.blit(text, (rect.centerx - text.get_width() // 2,
                            rect.centery - text.get_height() // 2))

    # ------------------------------------------------------------------
    # Read modal
    # ------------------------------------------------------------------

    def _read_back_rect(self):
        bw, bh = int(60 * self.scale), int(22 * self.scale)
        return pygame.Rect(self._sx(120) - bw // 2, self._sy(160), bw, bh)

    def _draw_read_modal(self, surface):
        overlay = pygame.Surface(surface.get_size())
        overlay.fill((0, 0, 0))
        overlay.set_alpha(200)
        surface.blit(overlay, (0, 0))

        # Modal panel
        panel = pygame.Rect(self._sx(40), self._sy(56),
                            int(160 * self.scale), int(136 * self.scale))
        pygame.draw.rect(surface, (20, 20, 20), panel)
        pygame.draw.rect(surface, YELLOW_BRIGHT, panel, max(1, int(self.scale)))

        title = self.font_medium.render("SCAN CARD", True, YELLOW_BRIGHT)
        surface.blit(title, (self._sx(120) - title.get_width() // 2, self._sy(64)))

        # 3-frame NFC animation (~3 fps)
        if self.nfc_frames:
            frame_idx = (self.frame_counter // max(1, constants.FRAME_RATE // 3)) % len(self.nfc_frames)
            frame = self.nfc_frames[frame_idx]
            surface.blit(frame, (self._sx(120) - frame.get_width() // 2, self._sy(88)))

        hint = self.font_small.render("Hold a card near the reader", True, (220, 220, 220))
        surface.blit(hint, (self._sx(120) - hint.get_width() // 2, self._sy(142)))

        self._draw_modal_button(surface, self._read_back_rect(), "BACK",
                                focused=True, enabled=True)
