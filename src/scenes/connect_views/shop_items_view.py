"""
ShopItemsView - Browse and purchase consumable items
Shows list of items similar to inventory with icon, name, and price.
"""
import threading
import pygame
import os

from ui.ui_manager import UIManager
from ui.components.title_scene import TitleScene
from ui.components.button import Button
from ui.components.background import Background
from ui.components.image import Image
from ui.components.label import Label
from ui.components.text_panel import TextPanel
from ui.components.shop_list import ShopList, ShopInventoryItem
from ui.ui_constants import BASE_RESOLUTION
from core import runtime_globals, game_globals
from services.omninet_service import omninet_service
from utils.asset_utils import image_load


class ShopItemsView:
    """Items shop view with list and detail subviews."""
    
    STATE_LIST = "list"
    STATE_DETAIL = "detail"
    STATE_LOADING = "loading"
    
    def __init__(self, ui_manager: UIManager, change_view_callback, discord_module=None):
        """Initialize the shop items view.
        
        Args:
            ui_manager: The UI manager instance
            change_view_callback: Callback to change to another view
            discord_module: Reference to the Discord module (unused, for compatibility)
        """
        self.ui_manager = ui_manager
        self.change_view = change_view_callback
        
        self.state = self.STATE_LOADING
        self.selected_item = None
        self.items_data = []
        
        # List view components
        self.background = None
        self.title_scene = None
        self.coin_icon = None
        self.coin_label = None
        self.shop_list = None
        self.loading_label = None
        self.back_button = None
        
        # Detail view components
        self.detail_components = []
        
        self._setup_ui()
        self._load_items_async()
    
    def _setup_ui(self):
        """Setup the UI components."""
        ui_width = ui_height = BASE_RESOLUTION
        
        # Background
        self.background = Background(ui_width, ui_height)
        self.background.set_regions([(0, ui_height, "black")])
        self.ui_manager.add_component(self.background)
        
        # Title
        self.title_scene = TitleScene(0, 9, "ITEMS")
        self.ui_manager.add_component(self.title_scene)
        
        # Coin display
        self._setup_coin_display()
        
        # Loading label
        self.loading_label = Label(0, BASE_RESOLUTION // 2, "Loading...", is_title=False)
        self.ui_manager.add_component(self.loading_label)
        
        # Back button (bottom)
        btn_height = 24
        self.back_button = Button(
            10, BASE_RESOLUTION - btn_height - 10, 60, btn_height,
            "Back", self._on_back,
            cut_corners={'tl': True, 'tr': False, 'bl': False, 'br': True}
        )
        self.ui_manager.add_component(self.back_button)
        
        runtime_globals.game_console.log("[ShopItemsView] UI setup complete")
    
    def _setup_coin_display(self):
        """Setup the coin icon and amount display."""
        # Free Play has no coin economy — hide the balance entirely.
        if game_globals.is_free_mode():
            self.coin_label = None
            self.coin_icon = None
            return

        icon_size = 16
        label_width = 55
        margin = 10
        label_x = BASE_RESOLUTION - margin - label_width
        coin_y = 9 + 4
        
        coins = getattr(game_globals, 'coins', 0)
        self.coin_label = Label(label_x, coin_y, str(coins), is_title=False)
        self.ui_manager.add_component(self.coin_label)
        
        icon_x = label_x - icon_size - 4
        self.coin_icon = Image(icon_x, coin_y - 2, icon_size, icon_size, 
                               image_path="assets/ui/Shop_Coin_1.png")
        self.ui_manager.add_component(self.coin_icon)
    
    def _load_item_icon(self, sprite_name: str) -> pygame.Surface:
        """Load an item icon from the local assets/items folder.

        Returns None when no matching local file exists — the caller then
        falls back to fetching from the server (via _fetch_item_icon_async).
        """
        if not sprite_name:
            return None
        try:
            icon_path = os.path.join("assets", "items", sprite_name)
            if os.path.exists(icon_path):
                return image_load(icon_path).convert_alpha()
        except Exception as e:
            runtime_globals.game_console.log(
                f"[ShopItemsView] Failed to load icon {sprite_name}: {e}")
        return None

    def _fetch_item_icon_async(self, item, server_id: str):
        """Pull the item icon from the server when no local sprite exists.

        Result is cached in shop_image_cache so re-entering the shop
        doesn't re-fetch.
        """
        from services.shop_image_cache import shop_image_cache
        from services.omninet_service import omninet_service
        if not server_id:
            return
        cached = shop_image_cache.get(server_id, 'icon', kind='item')
        if cached is not None:
            item.icon = cached
            return
        if getattr(item, '_icon_fetching', False):
            return
        item._icon_fetching = True

        def fetch():
            try:
                surface = omninet_service.get_shop_sprite('item', server_id)
                if surface is not None:
                    shop_image_cache.put(server_id, 'icon', surface, kind='item')
                    item.icon = surface
            finally:
                item._icon_fetching = False

        threading.Thread(target=fetch, daemon=True).start()
    
    def _setup_list_view(self):
        """Setup the list view with loaded items."""
        if self.shop_list:
            self.ui_manager.remove_component(self.shop_list)
        
        # Remove loading label
        if self.loading_label:
            self.ui_manager.remove_component(self.loading_label)
            self.loading_label = None
        
        # Create shop list
        list_top = 35
        list_height = BASE_RESOLUTION - list_top - 40
        self.shop_list = ShopList(
            5, list_top, BASE_RESOLUTION - 10, list_height,
            mode=ShopList.MODE_ITEMS,
            on_item_selected=self._on_item_selected
        )
        
        # Convert API data to ShopInventoryItem objects
        items = []
        for item_data in self.items_data:
            item_id = item_data.get('id', '')
            quantity = game_globals.purchases.get_item_quantity(item_id)
            owned = quantity > 0

            # The server returns the sprite filename in `sprite_name`; the
            # old code looked for `icon`, which silently produced no icon.
            sprite_name = (item_data.get('sprite_name')
                           or item_data.get('icon')
                           or '')
            icon = self._load_item_icon(sprite_name)

            # Cache full item metadata for SceneInventory consumption.
            # Shop items apply their effect to *all* pets (cross-module),
            # so we tag them with cross_module=True for the consumer.
            json_data = item_data.get('json_data') or {}
            game_globals.shop_items_data[item_id] = {
                'id': item_id,
                'name': item_data.get('name', 'Unknown'),
                'description': item_data.get('description', ''),
                'sprite_name': sprite_name,
                'effect': json_data.get('effect', ''),
                'status': json_data.get('status', ''),
                'amount': json_data.get('amount', 1),
                'boost_time': json_data.get('boost_time', 0),
                'protocol_value': json_data.get('protocol_value', 0),
                'attack_sprite': json_data.get('attack_sprite', 0),
                'digisoul': json_data.get('digisoul', ''),
                'cross_module': True,
            }

            new_item = ShopInventoryItem(
                item_id=item_id,
                name=item_data.get('name', 'Unknown'),
                price=item_data.get('price', 0),
                owned=owned,
                icon=icon,
                description=item_data.get('description', ''),
                quantity=quantity
            )
            new_item._icon_fetching = False
            items.append(new_item)
        
        self.shop_list.set_items(items)
        self.ui_manager.add_component(self.shop_list)

        # Any item without a local icon falls back to the server fetch.
        for it in items:
            if it.icon is None:
                self._fetch_item_icon_async(it, it.id)

        self.state = self.STATE_LIST
    
    def _setup_detail_view(self, item: ShopInventoryItem):
        """Setup the detail view for a selected item."""
        self._clear_detail_components()

        # Hide list AND the persistent Back button so it can't intercept
        # clicks meant for the detail's own Back button (which returns to
        # this view's list, not the main shop).
        if self.shop_list:
            self.shop_list.visible = False
        if self.back_button:
            self.back_button.visible = False
        
        padding = 10
        y_offset = 35
        
        # Item icon — 32px so the layout below (name / effect / price /
        # action buttons) fits without overflowing into the bottom row.
        if item.icon:
            icon_size = 32
            icon_x = (BASE_RESOLUTION - icon_size) // 2
            icon_image = Image(icon_x, y_offset, icon_size, icon_size)
            icon_image.set_image(image_surface=pygame.transform.scale(
                item.icon, (icon_size, icon_size)))
            self.ui_manager.add_component(icon_image)
            self.detail_components.append(icon_image)
            y_offset += icon_size + 6
        
        # Item name (large)
        name_label = Label(0, y_offset, item.name, is_title=True)
        self.ui_manager.add_component(name_label)
        self.detail_components.append(name_label)
        y_offset += 25
        
        # Quantity if owned
        if item.quantity > 0:
            qty_label = Label(0, y_offset, f"Owned: x{item.quantity}", is_title=False)
            self.ui_manager.add_component(qty_label)
            self.detail_components.append(qty_label)
            y_offset += 18
        
        y_offset += 5
        
        # Description panel
        desc_height = 60
        desc_panel = TextPanel(padding, y_offset, BASE_RESOLUTION - padding * 2, desc_height, 
                               item.description or "No description available.")
        self.ui_manager.add_component(desc_panel)
        self.detail_components.append(desc_panel)
        y_offset += desc_height + 15
        
        # Price display — yellow Price + coin icon + value; 2px left margin
        price_x = 2  # 2 base pixels, scales via UI manager
        coins = getattr(game_globals, 'coins', 0)
        if item.price <= 0:
            price_label = Label(price_x, y_offset, "Free", is_title=False,
                                color_override=(120, 220, 120))
            self.ui_manager.add_component(price_label)
            self.detail_components.append(price_label)
        else:
            price_label = Label(price_x, y_offset, "Price:", is_title=False,
                                color_override=(255, 215, 80))
            self.ui_manager.add_component(price_label)
            self.detail_components.append(price_label)
            coin_x = price_x + 50
            coin_icon = Image(coin_x, y_offset - 1, 14, 14,
                              image_path="assets/ui/Shop_Coin_1.png")
            self.ui_manager.add_component(coin_icon)
            self.detail_components.append(coin_icon)
            val_label = Label(coin_x + 18, y_offset, str(item.price),
                              is_title=False, color_override=(255, 215, 80))
            self.ui_manager.add_component(val_label)
            self.detail_components.append(val_label)
        y_offset += 18

        # Buttons
        btn_width = 80
        btn_height = 28
        btn_y = BASE_RESOLUTION - btn_height - 10

        # Buy button — disabled when player can't afford
        buy_enabled = item.price <= 0 or coins >= item.price
        buy_button = Button(
            BASE_RESOLUTION - btn_width - padding, btn_y, btn_width, btn_height,
            "Buy", lambda: self._on_buy(item),
            cut_corners={'tl': True, 'tr': False, 'bl': False, 'br': True},
            enabled=buy_enabled,
        )
        self.ui_manager.add_component(buy_button)
        self.detail_components.append(buy_button)
        
        # Back to list button
        back_list_button = Button(
            padding, btn_y, 60, btn_height,
            "Back", self._on_detail_back,
            cut_corners={'tl': True, 'tr': False, 'bl': False, 'br': True}
        )
        self.ui_manager.add_component(back_list_button)
        self.detail_components.append(back_list_button)
        
        self.state = self.STATE_DETAIL
    
    def _clear_detail_components(self):
        """Remove all detail view components."""
        for comp in self.detail_components:
            if comp in self.ui_manager.components:
                self.ui_manager.remove_component(comp)
        self.detail_components.clear()
    
    def _load_items_async(self):
        """Load items from server in background thread."""
        def fetch_items():
            try:
                success, data = omninet_service.get_shop_items()
                if success:
                    # an empty shelf is an answer, not a failure
                    self.items_data = data or []
                else:
                    self.items_data = []
                    runtime_globals.game_console.log(f"[ShopItemsView] Failed to load items")
            except Exception as e:
                runtime_globals.game_console.log(f"[ShopItemsView] Error loading items: {e}")
                self.items_data = []
            
            self._on_items_loaded()
        
        threading.Thread(target=fetch_items, daemon=True).start()
    
    def _on_items_loaded(self):
        """Called when items are loaded from server."""
        self._setup_list_view()
    
    def _on_item_selected(self, item: ShopInventoryItem):
        """Handle item selection from list."""
        runtime_globals.game_sound.play("menu")
        self.selected_item = item
        self._setup_detail_view(item)
    
    def _on_buy(self, item: ShopInventoryItem):
        """Handle buy button click."""
        coins = getattr(game_globals, 'coins', 0)
        
        if coins < item.price:
            runtime_globals.game_sound.play("cancel")
            # (suppressed) runtime_globals.game_message.add_slide("Not enough coins!", (255, 100, 100), 90)
            return
        
        runtime_globals.game_sound.play("menu")
        
        def do_purchase():
            try:
                success, message = omninet_service.purchase_item('item', item.id)
                if success:
                    game_globals.coins -= item.price
                    game_globals.purchases.add_item(item.id, 1)
                    game_globals.save()
                    
                    item.quantity = game_globals.purchases.get_item_quantity(item.id)
                    item.owned = item.quantity > 0
                    # Purchase confirmation handled via in-view label, not game_message, 90)
                    self._setup_detail_view(item)
                else:
                    runtime_globals.game_sound.play("cancel")
                    # Failure shown via in-view label below; suppress global slide, 90)
            except Exception as e:
                runtime_globals.game_console.log(f"[ShopItemsView] Purchase error: {e}")
                runtime_globals.game_sound.play("cancel")
                # Failure shown via in-view label below; suppress global slide, 90)
        
        threading.Thread(target=do_purchase, daemon=True).start()
    
    def _on_detail_back(self):
        """Go back from detail view to list view."""
        runtime_globals.game_sound.play("cancel")
        self._clear_detail_components()

        if self.shop_list:
            self.shop_list.visible = True
        if self.back_button:
            self.back_button.visible = True

        self.state = self.STATE_LIST
        self.selected_item = None
    
    def _on_back(self):
        """Back button clicked."""
        runtime_globals.game_sound.play("cancel")
        self.change_view("shop")
    
    def update(self):
        """Update the view."""
        coins = getattr(game_globals, 'coins', 0)
        if self.coin_label:
            self.coin_label.set_text(str(coins))
    
    def draw(self, surface):
        """Draw view-specific elements."""
        pass
    
    def handle_event(self, event):
        """Handle input events."""
        if not isinstance(event, tuple) or len(event) != 2:
            return
        
        event_type, event_data = event
        
        if event_type == "B":
            if self.state == self.STATE_DETAIL:
                self._on_detail_back()
            else:
                self._on_back()
            return True
    
    def cleanup(self):
        """Cleanup when view is destroyed."""
        self._clear_detail_components()
        
        components = [
            self.background, self.title_scene,
            self.coin_icon, self.coin_label,
            self.shop_list, self.loading_label,
            self.back_button,
        ]
        
        for comp in components:
            if comp and comp in self.ui_manager.components:
                self.ui_manager.remove_component(comp)
        
        runtime_globals.game_console.log("[ShopItemsView] Cleanup complete")
