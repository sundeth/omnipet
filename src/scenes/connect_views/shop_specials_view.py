"""
ShopSpecialsView - Specials: unlocks bought with coins or contribution points.

Contribution points are an Omninet balance of their own, apart from the
coins: the Digimon Database credits the account whose email a contribution
carries (1 point; 2 on an entry flagged as needing data). This page shows
that balance with its diamond, lists the Specials with their price in their
own currency, buys one from that balance and downloads it.

A background Special is saved with the shop's backgrounds (the player's save
folder, game_globals.shop_backgrounds) and chosen in Settings > Background;
WindowBackground draws its day, dusk and night pictures by the clock and its
_high pictures with High-Res on. A kind of Special this Omnipet does not know
is listed but cannot be bought.

Workers build the list and the detail view themselves, as the other shop
views do (tests/game/online/README.md: wait for `state`, `_busy`).
"""
import base64
import os
import threading

import pygame

from ui.ui_manager import UIManager
from ui.components.title_scene import TitleScene
from ui.components.button import Button
from ui.components.background import Background
from ui.components.image import Image
from ui.components.label import Label
from ui.components.shop_list import (CURRENCY_CONTRIBUTION_POINTS, PRICE_COLOURS, ShopList,
                                     ShopSpecialItem, currency_icon_path)
from ui.ui_constants import BASE_RESOLUTION
from core import runtime_globals, game_globals
from services.omninet_service import omninet_service

#: The kinds of Special this Omnipet can use.
SUPPORTED_TYPES = ("background",)
_PNG = b"\x89PNG\r\n\x1a\n"
GREEN = (120, 220, 120)
RED = (255, 120, 120)


def _balance(currency):
    if currency == CURRENCY_CONTRIBUTION_POINTS:
        return int(getattr(game_globals, 'contribution_points', 0) or 0)
    return int(getattr(game_globals, 'coins', 0) or 0)


def save_background_special(special_id, name, data):
    """Write a downloaded background Special's pictures into the player's save
    folder and register it with the shop's backgrounds. Returns the number of
    pictures saved (0: nothing usable, nothing registered)."""
    out_dir = os.path.join(game_globals.get_save_dir(), "cosmetics", "backgrounds")
    os.makedirs(out_dir, exist_ok=True)
    saved = {}
    for file_name, b64 in (data.get('sprites') or {}).items():
        file_name = os.path.basename(str(file_name))
        if not file_name.lower().endswith('.png'):
            continue
        try:
            raw = base64.b64decode(b64 or "")
        except Exception:
            continue
        if not raw.startswith(_PNG):
            continue
        path = os.path.join(out_dir, file_name)
        with open(path, 'wb') as fh:
            fh.write(raw)
        saved[file_name] = path
    if not saved:
        return 0
    game_globals.shop_backgrounds[special_id] = {
        'id': special_id,
        'name': name,
        'label': (data.get('json_data') or {}).get('label') or name,
        'sprite_name': data.get('sprite_name') or '',
        'day_night': bool(data.get('day_night')),
        'high_res': bool(data.get('high_res')),
        'sprite_paths': saved,
        'source': 'special',
    }
    game_globals.save()
    return len(saved)


class ShopSpecialsView:
    """Specials shop view with list and detail subviews."""

    STATE_LIST = "list"
    STATE_DETAIL = "detail"
    STATE_LOADING = "loading"

    def __init__(self, ui_manager: UIManager, change_view_callback, discord_module=None):
        """Initialize the shop specials view.

        Args:
            ui_manager: The UI manager instance
            change_view_callback: Callback to change to another view
            discord_module: Reference to the Discord module (unused, for compatibility)
        """
        self.ui_manager = ui_manager
        self.change_view = change_view_callback

        self.state = self.STATE_LOADING
        self.selected_item = None
        self.specials_data = []
        #: A purchase or download is running.
        self._busy = False
        #: What the detail view says under the price (bought, failed...).
        self._status = ("", GREEN)

        self.background = None
        self.title_scene = None
        self.balance_icon = None
        self.balance_label = None
        self.shop_list = None
        self.loading_label = None
        self.back_button = None
        self.detail_components = []

        self._setup_ui()
        self._load_specials_async()

    # ------------------------------------------------------------------ layout
    def _setup_ui(self):
        ui_width = ui_height = BASE_RESOLUTION

        self.background = Background(ui_width, ui_height)
        self.background.set_regions([(0, ui_height, "black")])
        self.ui_manager.add_component(self.background)

        self.title_scene = TitleScene(0, 9, "SPECIALS")
        self.ui_manager.add_component(self.title_scene)

        self._setup_balance_display()

        self.loading_label = Label(0, BASE_RESOLUTION // 2, "Loading...", is_title=False)
        self.ui_manager.add_component(self.loading_label)

        btn_height = 24
        self.back_button = Button(
            10, BASE_RESOLUTION - btn_height - 10, 60, btn_height,
            "Back", self._on_back,
            cut_corners={'tl': True, 'tr': False, 'bl': False, 'br': True}
        )
        self.ui_manager.add_component(self.back_button)

        runtime_globals.game_console.log("[ShopSpecialsView] UI setup complete")

    def _setup_balance_display(self):
        """The contribution points, with their diamond, where the other shop
        pages show the coins."""
        icon_size = 16
        label_width = 55
        margin = 10
        label_x = BASE_RESOLUTION - margin - label_width
        y = 9 + 4
        self.balance_label = Label(label_x, y, str(_balance(CURRENCY_CONTRIBUTION_POINTS)),
                                   is_title=False,
                                   color_override=PRICE_COLOURS[CURRENCY_CONTRIBUTION_POINTS])
        self.ui_manager.add_component(self.balance_label)
        self.balance_icon = Image(label_x - icon_size - 4, y - 2, icon_size, icon_size,
                                  image_path=currency_icon_path(CURRENCY_CONTRIBUTION_POINTS))
        self.ui_manager.add_component(self.balance_icon)

    # ------------------------------------------------------------------ loading
    def _load_specials_async(self):
        def fetch():
            try:
                # Points are earned on the Database, outside the game: read
                # the balance afresh each time the page opens.
                ok, info = omninet_service.refresh_user_info()
                if ok and isinstance(info, dict) and info.get('contribution_points') is not None:
                    game_globals.contribution_points = int(info['contribution_points'])
                    if info.get('coins') is not None:
                        game_globals.coins = int(info['coins'])
                success, data = omninet_service.get_shop_specials()
                self.specials_data = (data or []) if success else []
                if not success:
                    runtime_globals.game_console.log("[ShopSpecialsView] Failed to load specials")
            except Exception as e:
                runtime_globals.game_console.log(f"[ShopSpecialsView] Error loading specials: {e}")
                self.specials_data = []
            self._setup_list_view()

        threading.Thread(target=fetch, daemon=True).start()

    def _make_item(self, entry):
        special_id = str(entry.get('id', ''))
        special_type = (entry.get('special_type') or '').lower()
        item = ShopSpecialItem(
            item_id=special_id,
            name=entry.get('name', 'Unknown'),
            price=int(entry.get('price', 0) or 0),
            owned=game_globals.purchases.owns_special(special_id),
            special_type=special_type,
            day_night=bool(entry.get('day_night', False)),
            high_res=bool(entry.get('high_res', False)),
            sprite_name=entry.get('sprite_name') or '',
            currency=entry.get('currency') or 'coins',
            description=entry.get('description') or '',
            supported=special_type in SUPPORTED_TYPES,
        )
        item._sprite_fetching = False
        return item

    def _setup_list_view(self):
        if self.shop_list:
            self.ui_manager.remove_component(self.shop_list)
        if self.loading_label:
            self.ui_manager.remove_component(self.loading_label)
            self.loading_label = None

        list_top = 35
        list_height = BASE_RESOLUTION - list_top - 40
        self.shop_list = ShopList(
            5, list_top, BASE_RESOLUTION - 10, list_height,
            mode=ShopList.MODE_SPECIALS,
            on_item_selected=self._on_special_selected
        )
        items = [self._make_item(entry) for entry in self.specials_data]
        self.shop_list.set_items(items)
        self.ui_manager.add_component(self.shop_list)
        for item in items:
            if item.special_type == "background":
                self._fetch_preview_async(item)
        self.state = self.STATE_LIST

    @staticmethod
    def _thumbnail(surface, size=28):
        """The list's icon, scaled once (the list scales it to the UI)."""
        return pygame.transform.smoothscale(surface, (size, size))

    def _fetch_preview_async(self, item):
        """A background Special's day picture (96x96) as its thumbnail and
        the detail view's backdrop; cached across visits."""
        from services.shop_image_cache import shop_image_cache
        if not item.id:
            return
        cached = shop_image_cache.get(item.id, 'preview', kind='special')
        if cached is not None:
            item.preview = cached
            item.icon = self._thumbnail(cached)
            return
        if getattr(item, '_sprite_fetching', False):
            return
        item._sprite_fetching = True

        def fetch():
            try:
                surface = omninet_service.get_special_preview(item.id, small=True)
                if surface is not None:
                    shop_image_cache.put(item.id, 'preview', surface, kind='special')
                    item.preview = surface
                    item.icon = self._thumbnail(surface)
                    if self.state == self.STATE_DETAIL and self.selected_item is item:
                        self._setup_detail_view(item)
            finally:
                item._sprite_fetching = False

        threading.Thread(target=fetch, daemon=True).start()

    # ------------------------------------------------------------------ detail
    def _add_detail(self, component):
        self.ui_manager.add_component(component)
        self.detail_components.append(component)
        return component

    def _supports_text(self, item):
        if item.special_type != "background":
            return ""
        parts = ["Day, dusk, night" if item.day_night else "One scene"]
        if item.high_res:
            parts.append("HD")
        return " + ".join(parts)

    def _setup_detail_view(self, item):
        self._clear_detail_components()
        if self.shop_list:
            self.shop_list.visible = False
        if self.back_button:
            self.back_button.visible = False

        if item.special_type == "background" and item.preview is not None and self.background:
            self.background.set_image(item.preview, alpha=200)
        elif self.background:
            self.background.clear_image()

        x = 6
        y = 35
        self._add_detail(Label(x, y, item.name, is_title=True, shadow_mode="full"))
        y += 24
        if item.description:
            self._add_detail(Label(x, y, item.description, is_title=False, shadow_mode="full",
                                   word_wrap=True, max_width=BASE_RESOLUTION - 2 * x))
            y += 30
        supports = self._supports_text(item)
        if supports:
            self._add_detail(Label(x, y, supports, is_title=False, shadow_mode="full",
                                   color_override=(120, 220, 255)))
            y += 16

        currency = item.currency
        have = _balance(currency)
        if item.owned:
            self._add_detail(Label(x, y, "Already Owned", is_title=False, shadow_mode="full",
                                   color_override=GREEN))
        elif not item.supported:
            self._add_detail(Label(x, y, "Needs a newer Omnipet", is_title=False,
                                   shadow_mode="full", color_override=RED))
        else:
            colour = PRICE_COLOURS.get(currency, PRICE_COLOURS['coins'])
            self._add_detail(Label(x, y, "Price:", is_title=False, shadow_mode="full",
                                   color_override=colour))
            self._add_detail(Image(x + 50, y - 1, 14, 14, image_path=currency_icon_path(currency)))
            self._add_detail(Label(x + 68, y, str(item.price), is_title=False, shadow_mode="full",
                                   color_override=colour))
            y += 16
            if have < item.price:
                need = ("contribution points" if currency == CURRENCY_CONTRIBUTION_POINTS
                        else "coins")
                self._add_detail(Label(x, y, f"You have {have} {need}", is_title=False,
                                       shadow_mode="full", color_override=RED))
        y += 18
        text, colour = self._status
        if text:
            self._add_detail(Label(x, y, text, is_title=False, shadow_mode="full",
                                   color_override=colour, word_wrap=True,
                                   max_width=BASE_RESOLUTION - 2 * x))

        btn_width, btn_height, padding = 80, 28, 10
        btn_y = BASE_RESOLUTION - btn_height - 10
        if item.owned:
            action_text = "Download"
            action = lambda: self._on_download(item)
            enabled = item.supported and not self._busy
        else:
            action_text = "Buy"
            action = lambda: self._on_buy(item)
            enabled = item.supported and not self._busy and have >= item.price
        self._add_detail(Button(
            BASE_RESOLUTION - btn_width - padding, btn_y, btn_width, btn_height,
            action_text, action,
            cut_corners={'tl': True, 'tr': False, 'bl': False, 'br': True},
            enabled=enabled,
        ))
        self._add_detail(Button(
            padding, btn_y, 60, btn_height, "Back", self._on_detail_back,
            cut_corners={'tl': True, 'tr': False, 'bl': False, 'br': True}
        ))
        self.state = self.STATE_DETAIL

    def _clear_detail_components(self):
        for comp in self.detail_components:
            if comp in self.ui_manager.components:
                self.ui_manager.remove_component(comp)
        self.detail_components.clear()

    # ------------------------------------------------------------------ actions
    def _on_special_selected(self, item):
        runtime_globals.game_sound.play("menu")
        self.selected_item = item
        self._status = ("", GREEN)
        if item.special_type == "background" and item.preview is None:
            self._fetch_preview_async(item)
        self._setup_detail_view(item)

    def _on_buy(self, item):
        if self._busy or not item.supported or _balance(item.currency) < item.price:
            runtime_globals.game_sound.play("cancel")
            return
        runtime_globals.game_sound.play("menu")
        self._busy = True
        self._status = ("Buying...", GREEN)
        self._setup_detail_view(item)

        def do_purchase():
            try:
                success, message = omninet_service.purchase_item('special', item.id)
                if not success:
                    runtime_globals.game_sound.play("cancel")
                    self._status = (message or "Purchase refused", RED)
                    return
                # The balances the server left: points for a points Special,
                # coins otherwise (never the other one).
                if item.currency == CURRENCY_CONTRIBUTION_POINTS:
                    remaining = omninet_service.last_points_remaining
                    game_globals.contribution_points = (
                        remaining if remaining is not None
                        else game_globals.contribution_points - item.price)
                else:
                    remaining = omninet_service.last_coins_remaining
                    game_globals.coins = (remaining if remaining is not None
                                          else game_globals.coins - item.price)
                game_globals.purchases.add_special(item.id)
                game_globals.save()
                item.owned = True
                # A bought background is no use until it is on this device.
                self._status = ("Bought! Downloading...", GREEN)
                self._setup_detail_view(item)
                self._download(item)
            except Exception as e:
                runtime_globals.game_console.log(f"[ShopSpecialsView] Purchase error: {e}")
                runtime_globals.game_sound.play("cancel")
                self._status = ("Error, try again", RED)
            finally:
                self._busy = False
                if self.state == self.STATE_DETAIL and self.selected_item is item:
                    self._setup_detail_view(item)

        threading.Thread(target=do_purchase, daemon=True).start()

    def _on_download(self, item):
        if self._busy:
            return
        runtime_globals.game_sound.play("menu")
        self._busy = True
        self._status = ("Downloading...", GREEN)
        self._setup_detail_view(item)

        def do_download():
            try:
                self._download(item)
            finally:
                self._busy = False
                if self.state == self.STATE_DETAIL and self.selected_item is item:
                    self._setup_detail_view(item)

        threading.Thread(target=do_download, daemon=True).start()

    def _download(self, item):
        """Fetch a bought Special and keep it (worker thread)."""
        try:
            success, data = omninet_service.download_special(item.id)
            if not success or not isinstance(data, dict):
                runtime_globals.game_sound.play("cancel")
                self._status = ("Download failed, try again", RED)
                return
            if (data.get('special_type') or item.special_type) == "background":
                count = save_background_special(item.id, item.name, data)
                if not count:
                    runtime_globals.game_console.log(
                        f"[ShopSpecialsView] {item.name}: the download has no picture")
                    runtime_globals.game_sound.play("cancel")
                    self._status = ("Download failed, try again", RED)
                    return
                self._status = ("Ready: Settings > Background", GREEN)
        except Exception as e:
            runtime_globals.game_console.log(f"[ShopSpecialsView] Download error: {e}")
            runtime_globals.game_sound.play("cancel")
            self._status = ("Download failed, try again", RED)

    def _on_detail_back(self):
        runtime_globals.game_sound.play("cancel")
        self._clear_detail_components()
        if self.shop_list:
            self.shop_list.visible = True
        if self.back_button:
            self.back_button.visible = True
        if self.background:
            self.background.clear_image()
        self.state = self.STATE_LIST
        self.selected_item = None

    def _on_back(self):
        runtime_globals.game_sound.play("cancel")
        self.change_view("shop")

    # ------------------------------------------------------------------ frame
    def update(self):
        if self.balance_label:
            self.balance_label.set_text(str(_balance(CURRENCY_CONTRIBUTION_POINTS)))

    def draw(self, surface):
        pass

    def handle_event(self, event):
        if not isinstance(event, tuple) or len(event) != 2:
            return
        event_type, _event_data = event
        if event_type == "B":
            if self.state == self.STATE_DETAIL:
                self._on_detail_back()
            else:
                self._on_back()
            return True

    def cleanup(self):
        self._clear_detail_components()
        components = [
            self.background, self.title_scene,
            self.balance_icon, self.balance_label,
            self.shop_list, self.loading_label,
            self.back_button,
        ]
        for comp in components:
            if comp and comp in self.ui_manager.components:
                self.ui_manager.remove_component(comp)
        runtime_globals.game_console.log("[ShopSpecialsView] Cleanup complete")
