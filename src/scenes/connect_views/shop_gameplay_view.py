"""
ShopGameplayView - Browse and purchase gameplay features
Shows list of available gameplay items with details view.
"""
import threading

from ui.ui_manager import UIManager
from ui.components.title_scene import TitleScene
from ui.components.button import Button
from ui.components.background import Background
from ui.components.image import Image
from ui.components.label import Label
from ui.components.text_panel import TextPanel
from ui.components.shop_list import ShopList, ShopGameplayItem
from ui.ui_constants import BASE_RESOLUTION
from core import runtime_globals, game_globals
from services.omninet_service import omninet_service


class ShopGameplayView:
    """Gameplay shop view with list and detail subviews."""
    
    STATE_LIST = "list"
    STATE_DETAIL = "detail"
    STATE_LOADING = "loading"
    
    def __init__(self, ui_manager: UIManager, change_view_callback, discord_module=None):
        """Initialize the shop gameplay view.
        
        Args:
            ui_manager: The UI manager instance
            change_view_callback: Callback to change to another view
            discord_module: Reference to the Discord module (unused, for compatibility)
        """
        self.ui_manager = ui_manager
        self.change_view = change_view_callback
        
        self.state = self.STATE_LOADING
        self.selected_item = None
        self.gameplay_data = []
        
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
        self._load_gameplay_async()
    
    def _setup_ui(self):
        """Setup the UI components."""
        ui_width = ui_height = BASE_RESOLUTION
        
        # Background
        self.background = Background(ui_width, ui_height)
        self.background.set_regions([(0, ui_height, "black")])
        self.ui_manager.add_component(self.background)
        
        # Title
        self.title_scene = TitleScene(0, 9, "GAMEPLAY")
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
        
        runtime_globals.game_console.log("[ShopGameplayView] UI setup complete")
    
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
    
    def _setup_list_view(self):
        """Setup the list view with loaded gameplay items."""
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
            mode=ShopList.MODE_GAMEPLAY,
            on_item_selected=self._on_gameplay_selected
        )
        
        # Convert API data to ShopGameplayItem objects
        items = []
        for gp in self.gameplay_data:
            owned = game_globals.purchases.owns_gameplay(gp.get('id', ''))
            items.append(ShopGameplayItem(
                item_id=gp.get('id', ''),
                name=gp.get('name', 'Unknown'),
                price=gp.get('price', 0),
                owned=owned,
                item_type=gp.get('type', ''),
                description=gp.get('description', '')
            ))
        
        self.shop_list.set_items(items)
        self.ui_manager.add_component(self.shop_list)
        
        self.state = self.STATE_LIST
    
    def _setup_detail_view(self, item: ShopGameplayItem):
        """Setup the detail view for a selected gameplay item."""
        self._clear_detail_components()
        
        # Hide list
        if self.shop_list:
            self.shop_list.visible = False
        if self.back_button:
            self.back_button.visible = False
        
        padding = 10
        y_offset = 35
        
        # Item name (large)
        name_label = Label(0, y_offset, item.name, is_title=True)
        self.ui_manager.add_component(name_label)
        self.detail_components.append(name_label)
        y_offset += 25
        
        # Type
        if item.item_type:
            type_label = Label(padding, y_offset, f"Type: {item.item_type}", is_title=False)
            self.ui_manager.add_component(type_label)
            self.detail_components.append(type_label)
            y_offset += 20
        
        y_offset += 5
        
        # Description panel
        desc_height = 80
        desc_panel = TextPanel(padding, y_offset, BASE_RESOLUTION - padding * 2, desc_height, 
                               item.description or "No description available.")
        self.ui_manager.add_component(desc_panel)
        self.detail_components.append(desc_panel)
        y_offset += desc_height + 15
        
        # Price display — yellow Price + coin icon + value; 2px left margin
        price_x = 2
        coins = getattr(game_globals, 'coins', 0)
        if item.owned:
            price_label = Label(price_x, y_offset, "Already Owned",
                                is_title=False, color_override=(120, 220, 120))
            self.ui_manager.add_component(price_label)
            self.detail_components.append(price_label)
        elif item.price <= 0:
            price_label = Label(price_x, y_offset, "Free",
                                is_title=False, color_override=(120, 220, 120))
            self.ui_manager.add_component(price_label)
            self.detail_components.append(price_label)
        else:
            price_label = Label(price_x, y_offset, "Price:",
                                is_title=False, color_override=(255, 215, 80))
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

        # Buy/Download button — Buy disabled when player can't afford
        if item.owned:
            action_text = "Download"
            action_callback = lambda: self._on_download(item)
            action_enabled = True
        else:
            action_text = "Buy"
            action_callback = lambda: self._on_buy(item)
            action_enabled = item.price <= 0 or coins >= item.price

        action_button = Button(
            BASE_RESOLUTION - btn_width - padding, btn_y, btn_width, btn_height,
            action_text, action_callback,
            cut_corners={'tl': True, 'tr': False, 'bl': False, 'br': True},
            enabled=action_enabled,
        )
        self.ui_manager.add_component(action_button)
        self.detail_components.append(action_button)
        
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
    
    def _load_gameplay_async(self):
        """Load gameplay items from server in background thread."""
        def fetch_gameplay():
            try:
                success, data = omninet_service.get_shop_gameplay()
                if success:
                    # an empty shelf is an answer, not a failure
                    self.gameplay_data = data or []
                else:
                    self.gameplay_data = []
                    runtime_globals.game_console.log(f"[ShopGameplayView] Failed to load gameplay")
            except Exception as e:
                runtime_globals.game_console.log(f"[ShopGameplayView] Error loading gameplay: {e}")
                self.gameplay_data = []
            
            self._on_gameplay_loaded()
        
        threading.Thread(target=fetch_gameplay, daemon=True).start()
    
    def _on_gameplay_loaded(self):
        """Called when gameplay items are loaded from server."""
        self._setup_list_view()
    
    def _on_gameplay_selected(self, item: ShopGameplayItem):
        """Handle gameplay selection from list."""
        runtime_globals.game_sound.play("menu")
        self.selected_item = item
        self._setup_detail_view(item)
    
    def _on_buy(self, item: ShopGameplayItem):
        """Handle buy button click."""
        coins = getattr(game_globals, 'coins', 0)
        
        if coins < item.price:
            runtime_globals.game_sound.play("cancel")
            # (suppressed) runtime_globals.game_message.add_slide("Not enough coins!", (255, 100, 100), 90)
            return
        
        runtime_globals.game_sound.play("menu")
        
        def do_purchase():
            try:
                success, message = omninet_service.purchase_item('gameplay', item.id)
                if success:
                    game_globals.coins -= item.price
                    game_globals.purchases.add_gameplay(item.id)
                    game_globals.save()
                    
                    item.owned = True
                    # Purchase confirmation handled via in-view label, not game_message, 90)
                    self._setup_detail_view(item)
                else:
                    runtime_globals.game_sound.play("cancel")
                    # Failure shown via in-view label below; suppress global slide, 90)
            except Exception as e:
                runtime_globals.game_console.log(f"[ShopGameplayView] Purchase error: {e}")
                runtime_globals.game_sound.play("cancel")
                # Failure shown via in-view label below; suppress global slide, 90)
        
        threading.Thread(target=do_purchase, daemon=True).start()
    
    def _on_download(self, item: ShopGameplayItem):
        """Handle download button click."""
        runtime_globals.game_sound.play("menu")
        # (suppressed) runtime_globals.game_message.add_slide("Downloading...", (255, 255, 255), 60)
        
        def do_download():
            try:
                success, data = omninet_service.download_gameplay(item.id)
                if success:
                    pass
                else:
                    runtime_globals.game_sound.play("cancel")
            except Exception as e:
                runtime_globals.game_console.log(f"[ShopGameplayView] Download error: {e}")
                runtime_globals.game_sound.play("cancel")
                # (suppressed) runtime_globals.game_message.add_slide("Download failed", (255, 100, 100), 90)
        
        threading.Thread(target=do_download, daemon=True).start()
    
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
        
        runtime_globals.game_console.log("[ShopGameplayView] Cleanup complete")
