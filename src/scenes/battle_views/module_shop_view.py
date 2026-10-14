"""
ModuleShopView - one module shop (shop.json), opened from the Specials hub.

Lists what the shop sells with its price -- items, and card packs that are
opened when bought -- shows the balance of the shop's currency and buys with
it (``shop_key=(module_name, shop_name)``). Back
returns to the hub on the same module. Balances, unlocks and buying are
utils.currency_utils'.
"""
import os

import pygame
from ui.ui_manager import UIManager
from ui.components.title_scene import TitleScene
from ui.components.button import Button
from ui.components.background import Background
from ui.components.item_list import ItemList
from ui.components.text_panel import TextPanel
from ui.ui_constants import BASE_RESOLUTION
from core import runtime_globals
from utils import currency_utils
from utils.asset_utils import image_load


class ListRow:
    """One ItemList row: what the list draws (`game_item.name`, `icon`,
    `amount_text`) and what a view acts on. Shared with SpecialsView."""

    class _Named:
        def __init__(self, name, description=""):
            self.name = name
            self.description = description

    def __init__(self, name, icon, amount_text, description="", **data):
        self.id = None
        self.game_item = self._Named(name, description)
        self.icon = icon
        self.quantity = 0
        self.amount_text = amount_text
        self.__dict__.update(data)


def load_icon(path):
    """A sprite, or None when it is missing or unreadable."""
    if not path or not os.path.exists(path):
        return None
    try:
        return image_load(path).convert_alpha()
    except Exception:
        return None


def _item_icon(module, sprite_name):
    if not sprite_name:
        return None
    file_name = sprite_name if sprite_name.lower().endswith(".png") else sprite_name + ".png"
    return load_icon(os.path.join(module.folder_path, "items", file_name))


class ModuleShopView:
    """One shop's stock with a description, the balance, and Buy and Back."""

    def __init__(self, ui_manager: UIManager, change_view_callback, shop_key=None):
        self.ui_manager = ui_manager
        self.change_view = change_view_callback
        self.module = None
        self.shop = None
        module_name, shop_name = tuple(shop_key) if shop_key else (None, None)
        module = (runtime_globals.game_modules or {}).get(module_name)
        for shop in currency_utils.available_shops(module):
            if shop.get("name") == shop_name:
                self.module, self.shop = module, shop
                break
        self.module_name = module_name

        self.background = None
        self.title_scene = None
        self.item_list = None
        self.text_panel = None
        self.balance_panel = None
        self.buy_button = None
        self.back_button = None
        self._shown_index = None
        self._status = ""

        self._setup_ui()

    # ------------------------------------------------------------------ setup

    def _icon(self, offer):
        if offer.kind == "item":
            return _item_icon(self.module, offer.item.sprite_name)
        # A pack's art is a card shape: centre it in a square so the list's
        # square icon slot does not squash it.
        art = load_icon(os.path.join(self.module.folder_path, offer.pack.get("sprite") or ""))
        if art is None:
            return None
        side = max(art.get_size())
        square = pygame.Surface((side, side), pygame.SRCALPHA)
        square.blit(art, ((side - art.get_width()) // 2, (side - art.get_height()) // 2))
        return square

    def _rows(self):
        if self.shop is None:
            return []
        unit = currency_utils.currency_unit(self.module.name, self.shop.get("currency", ""))
        return [ListRow(offer.name, self._icon(offer), f"{offer.price}{unit}",
                        description=offer.description, offer=offer)
                for offer in currency_utils.shop_stock(self.module, self.shop)]

    def _setup_ui(self):
        ui_width = ui_height = BASE_RESOLUTION

        self.background = Background(ui_width, ui_height)
        self.background.set_regions([(0, ui_height, "black")])
        self.ui_manager.add_component(self.background)

        # A shop's name is too long for the title bar; Specials names it.
        self.title_scene = TitleScene(0, 9, "SHOP")
        self.ui_manager.add_component(self.title_scene)

        self.item_list = ItemList(0, 27, 156, 210, on_item_activated=self._on_row_activated)
        self.item_list.amount_cuts = 5   # room for "9990P"
        self.item_list.set_background_visible(False)
        self.item_list.set_border_visible(False)
        self.item_list.set_items(self._rows())
        self.ui_manager.add_component(self.item_list)

        self.text_panel = TextPanel(158, 24, 78, 106)
        self.ui_manager.add_component(self.text_panel)

        self.balance_panel = TextPanel(158, 133, 78, 48)
        self.ui_manager.add_component(self.balance_panel)

        button_width, button_height = 80, 23
        self.buy_button = Button(158, 186, button_width, button_height, "BUY", self._on_buy)
        self.ui_manager.add_component(self.buy_button)

        self.back_button = Button(158, 212, button_width, button_height, "BACK", self._on_back)
        self.ui_manager.add_component(self.back_button)

        if not self.item_list.items:
            self.text_panel.set_text("Nothing on sale")
            self.buy_button.set_enabled(False)
        self._refresh()
        self.ui_manager.set_focused_component(self.item_list)
        runtime_globals.game_console.log("[ModuleShopView] UI setup complete")

    # ---------------------------------------------------------------- display

    def _selected(self):
        items = self.item_list.items if self.item_list else []
        index = self.item_list.selected_index if self.item_list else -1
        return items[index] if 0 <= index < len(items) else None

    def _refresh(self):
        row = self._selected()
        self._shown_index = self.item_list.selected_index if self.item_list else None
        if row is not None:
            self.text_panel.set_text(row.game_item.description)
        if self.shop is None:
            return
        currency_name = self.shop.get("currency", "")
        balance = currency_utils.get_balance(self.module.name, currency_name)
        text = currency_utils.format_amount(self.module.name, currency_name, balance)
        if self._status:
            text = f"{self._status}\n{text}"
        self.balance_panel.set_text(text)

    # ---------------------------------------------------------------- actions

    def _on_row_activated(self, item, index, use_immediately=False):
        self._status = ""
        self._refresh()
        if use_immediately:
            self._on_buy()

    def _on_buy(self):
        row = self._selected()
        if row is None:
            runtime_globals.game_sound.play("cancel")
            return
        offer = row.offer
        from utils.inventory_utils import MAX_ITEM_STACK, is_full
        if offer.kind == "item" and is_full(offer.item.id):
            runtime_globals.game_sound.play("cancel")
            self._status = f"You have {MAX_ITEM_STACK}!"
            self._refresh()
            return
        cards = currency_utils.buy(self.module, self.shop, offer)
        if cards is None:
            runtime_globals.game_sound.play("fail")
            self._status = "Not enough!"
            self._refresh()
            return
        runtime_globals.game_sound.play("happy2")
        if offer.kind == "card_pack":
            from utils.card_utils import announce_cards
            announce_cards(cards)
        else:
            runtime_globals.game_message.add_slide(
                f"{offer.name} obtained!", (255, 255, 0),
                56 * runtime_globals.UI_SCALE, runtime_globals.FONT_SIZE_SMALL)
        runtime_globals.game_console.log(
            f"[ModuleShopView] Bought {offer.name} for {offer.price} "
            f"{self.shop.get('currency', '')} at {self.shop.get('name')}")
        self._status = ""
        self._refresh()

    def _on_back(self):
        runtime_globals.game_sound.play("cancel")
        self.change_view("specials", module_name=self.module_name)

    # ------------------------------------------------------------- view hooks

    def cleanup(self):
        for comp in (self.background, self.title_scene, self.item_list, self.text_panel,
                     self.balance_panel, self.buy_button, self.back_button):
            if comp and comp in self.ui_manager.components:
                self.ui_manager.remove_component(comp)

    def update(self):
        # The list does not report keyboard moves, so follow its selection.
        if self.item_list and self.item_list.selected_index != self._shown_index:
            self._status = ""
            self._refresh()

    def draw(self, surface: pygame.Surface):
        pass

    def handle_event(self, event):
        if not isinstance(event, tuple) or len(event) != 2:
            return
        event_type, _ = event
        if event_type == "B":
            self._on_back()
            return True
