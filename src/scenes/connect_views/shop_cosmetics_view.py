"""
ShopCosmeticsView - Browse and purchase cosmetic items (backgrounds, etc.)
Shows list with small icons and larger preview in detail view.
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
from ui.components.shop_list import ShopList, ShopCosmeticItem
from ui.ui_constants import BASE_RESOLUTION
from core import runtime_globals, game_globals
from services.omninet_service import omninet_service
from utils.asset_utils import image_load


class ShopCosmeticsView:
    """Cosmetics shop view with list and detail subviews."""
    
    STATE_LIST = "list"
    STATE_DETAIL = "detail"
    STATE_LOADING = "loading"
    
    def __init__(self, ui_manager: UIManager, change_view_callback, discord_module=None):
        """Initialize the shop cosmetics view.
        
        Args:
            ui_manager: The UI manager instance
            change_view_callback: Callback to change to another view
            discord_module: Reference to the Discord module (unused, for compatibility)
        """
        self.ui_manager = ui_manager
        self.change_view = change_view_callback
        
        self.state = self.STATE_LOADING
        self.selected_item = None
        self.cosmetics_data = []
        
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
        self._load_cosmetics_async()
    
    def _setup_ui(self):
        """Setup the UI components."""
        ui_width = ui_height = BASE_RESOLUTION
        
        # Background
        self.background = Background(ui_width, ui_height)
        self.background.set_regions([(0, ui_height, "black")])
        self.ui_manager.add_component(self.background)
        
        # Title
        self.title_scene = TitleScene(0, 9, "COSMETICS")
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
        
        runtime_globals.game_console.log("[ShopCosmeticsView] UI setup complete")
    
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
    
    def _load_cosmetic_preview(self, preview_path: str) -> pygame.Surface:
        """Load a cosmetic preview image from local assets only.

        Returns None when no local file matches — the caller should then
        fall back to ``_fetch_cosmetic_sprite_async`` to pull it from the
        server.
        """
        if not preview_path:
            return None

        try:
            # Try loading from backgrounds folder first
            bg_path = os.path.join("assets", "ui", "backgrounds", preview_path)
            if os.path.exists(bg_path):
                return image_load(bg_path).convert_alpha()

            # Try direct path
            if os.path.exists(preview_path):
                return image_load(preview_path).convert_alpha()
        except Exception as e:
            runtime_globals.game_console.log(
                f"[ShopCosmeticsView] Failed to load preview {preview_path}: {e}")

        return None

    def _fetch_cosmetic_sprite_async(self, item):
        """Pull the cosmetic sprite from the server when no local file.

        Server returns the full background PNG; we use the same surface
        as both the small list thumbnail (downscaled) and the detail
        preview / full-screen backdrop.  Cached so re-entering the shop
        doesn't re-fetch.
        """
        from services.shop_image_cache import shop_image_cache
        from services.omninet_service import omninet_service
        if not item.id:
            return
        cached = shop_image_cache.get(item.id, 'preview', kind='cosmetic')
        if cached is not None:
            item.preview = cached
            item.icon = self._create_thumbnail(cached, 28)
            return
        if getattr(item, '_sprite_fetching', False):
            return
        item._sprite_fetching = True

        def fetch():
            try:
                surface = omninet_service.get_shop_sprite('cosmetic', item.id)
                if surface is not None:
                    shop_image_cache.put(item.id, 'preview', surface, kind='cosmetic')
                    item.preview = surface
                    item.icon = self._create_thumbnail(surface, 28)
                    # If this is the currently focused detail item, repaint
                    # so the new sprite actually appears.
                    if (self.state == self.STATE_DETAIL
                            and self.selected_item is item):
                        self._setup_detail_view(item)
            finally:
                item._sprite_fetching = False

        threading.Thread(target=fetch, daemon=True).start()
    
    def _create_thumbnail(self, preview: pygame.Surface, size: int) -> pygame.Surface:
        """Create a thumbnail from the preview image."""
        if not preview:
            return None
        
        # Scale to thumbnail size maintaining aspect ratio
        orig_w, orig_h = preview.get_size()
        scale = min(size / orig_w, size / orig_h)
        new_w = int(orig_w * scale)
        new_h = int(orig_h * scale)
        
        return pygame.transform.scale(preview, (new_w, new_h))
    
    def _setup_list_view(self):
        """Setup the list view with loaded cosmetics."""
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
            mode=ShopList.MODE_COSMETICS,
            on_item_selected=self._on_cosmetic_selected
        )
        
        # Convert API data to ShopCosmeticItem objects
        items = []
        for cosm in self.cosmetics_data:
            cosm_id = cosm.get('id', '')
            owned = game_globals.purchases.owns_cosmetic(cosm_id)

            # Server delivers the asset filename in `sprite_name`; the old
            # local-only path used `preview` which doesn't exist in the API.
            sprite_name = (cosm.get('sprite_name')
                           or cosm.get('preview')
                           or '')
            preview = self._load_cosmetic_preview(sprite_name)
            icon = self._create_thumbnail(preview, 28) if preview else None

            new_item = ShopCosmeticItem(
                item_id=cosm_id,
                name=cosm.get('name', 'Unknown'),
                price=cosm.get('price', 0),
                owned=owned,
                icon=icon,
                preview=preview,
                cosmetic_type=cosm.get('cosmetic_type') or cosm.get('type', 'Background'),
                day_night=bool(cosm.get('day_night', True)),
                high_res=bool(cosm.get('high_res', False)),
                sprite_name=sprite_name,
            )
            new_item._sprite_fetching = False
            items.append(new_item)

        self.shop_list.set_items(items)
        self.ui_manager.add_component(self.shop_list)

        # Anything missing a local preview gets pulled from the server.
        for it in items:
            if it.preview is None:
                self._fetch_cosmetic_sprite_async(it)

        self.state = self.STATE_LIST
    
    def _setup_detail_view(self, item: ShopCosmeticItem):
        """Setup the detail view for a selected cosmetic."""
        self._clear_detail_components()

        # Hide list
        if self.shop_list:
            self.shop_list.visible = False
        if self.back_button:
            self.back_button.visible = False

        # Kick off / re-trigger the server fetch if we still don't have a
        # preview surface — the worker calls _setup_detail_view again on
        # completion so the new image lands in this view.
        if item.preview is None:
            self._fetch_cosmetic_sprite_async(item)

        # For Background-type cosmetics, render the preview full-screen
        # behind the rest of the UI by attaching it to self.background.
        # Dim it slightly so the foreground labels remain readable.
        is_background_type = (item.cosmetic_type or '').lower() == 'background'
        if is_background_type and item.preview and self.background:
            self.background.set_image(item.preview, alpha=200)
        elif self.background:
            self.background.clear_image()

        padding = 10
        y_offset = 35

        # Large preview image (skip for background type — we already use it
        # as the full-screen backdrop above)
        if item.preview and not is_background_type:
            preview_size = 120
            preview_x = (BASE_RESOLUTION - preview_size) // 2

            # Create preview surface
            preview_scaled = pygame.transform.scale(item.preview, (preview_size, preview_size))
            preview_image = Image(preview_x, y_offset, preview_size, preview_size)
            preview_image.set_image(preview_scaled)
            self.ui_manager.add_component(preview_image)
            self.detail_components.append(preview_image)
            y_offset += preview_size + 10
        
        # Cosmetic name (large)
        name_label = Label(0, y_offset, item.name, is_title=True)
        self.ui_manager.add_component(name_label)
        self.detail_components.append(name_label)
        y_offset += 25
        
        # Type
        type_label = Label(0, y_offset, f"Type: {item.cosmetic_type}", is_title=False)
        self.ui_manager.add_component(type_label)
        self.detail_components.append(type_label)
        y_offset += 16

        # Day/Night + HD support badges (background-only fields)
        if (item.cosmetic_type or '').lower() == 'background':
            badges = []
            if getattr(item, 'day_night', True):
                badges.append("Day/Night")
            if getattr(item, 'high_res', False):
                badges.append("HD")
            if badges:
                badge_label = Label(0, y_offset,
                                    "Supports: " + " + ".join(badges),
                                    is_title=False,
                                    color_override=(120, 220, 255))
                self.ui_manager.add_component(badge_label)
                self.detail_components.append(badge_label)
                y_offset += 14

        # Price display — yellow Price + coin icon + value (2*scale margin)
        scale = self.ui_manager.ui_scale if self.ui_manager else 1
        price_x = max(2, int(2))  # 2 base px
        coins = getattr(game_globals, 'coins', 0)
        if item.owned:
            price_label = Label(price_x, y_offset, "Already Owned",
                                is_title=False, color_override=(120, 220, 120))
            self.ui_manager.add_component(price_label)
            self.detail_components.append(price_label)
        elif item.price <= 0:
            price_label = Label(price_x, y_offset, "Free", is_title=False,
                                color_override=(120, 220, 120))
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

        # Buy/Download button — disabled when player can't afford
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
    
    def _load_cosmetics_async(self):
        """Load cosmetics from server in background thread."""
        def fetch_cosmetics():
            try:
                success, data = omninet_service.get_shop_cosmetics()
                if success:
                    # an empty shelf is an answer, not a failure
                    self.cosmetics_data = data or []
                else:
                    self.cosmetics_data = []
                    runtime_globals.game_console.log(f"[ShopCosmeticsView] Failed to load cosmetics")
            except Exception as e:
                runtime_globals.game_console.log(f"[ShopCosmeticsView] Error loading cosmetics: {e}")
                self.cosmetics_data = []
            
            self._on_cosmetics_loaded()
        
        threading.Thread(target=fetch_cosmetics, daemon=True).start()
    
    def _on_cosmetics_loaded(self):
        """Called when cosmetics are loaded from server."""
        self._setup_list_view()
    
    def _on_cosmetic_selected(self, item: ShopCosmeticItem):
        """Handle cosmetic selection from list."""
        runtime_globals.game_sound.play("menu")
        self.selected_item = item
        self._setup_detail_view(item)
    
    def _on_buy(self, item: ShopCosmeticItem):
        """Handle buy button click."""
        coins = getattr(game_globals, 'coins', 0)
        
        if coins < item.price:
            runtime_globals.game_sound.play("cancel")
            # (suppressed) runtime_globals.game_message.add_slide("Not enough coins!", (255, 100, 100), 90)
            return
        
        runtime_globals.game_sound.play("menu")
        
        def do_purchase():
            try:
                success, message = omninet_service.purchase_item('cosmetic', item.id)
                if success:
                    # the balance the server left, not the listed price
                    remaining = omninet_service.last_coins_remaining
                    game_globals.coins = (remaining if remaining is not None
                                          else game_globals.coins - item.price)
                    game_globals.purchases.add_cosmetic(item.id)
                    game_globals.save()
                    
                    item.owned = True
                    # Purchase confirmation handled via in-view label, not game_message, 90)
                    self._setup_detail_view(item)
                else:
                    runtime_globals.game_sound.play("cancel")
                    # Failure shown via in-view label below; suppress global slide, 90)
            except Exception as e:
                runtime_globals.game_console.log(f"[ShopCosmeticsView] Purchase error: {e}")
                runtime_globals.game_sound.play("cancel")
                # Failure shown via in-view label below; suppress global slide, 90)
        
        threading.Thread(target=do_purchase, daemon=True).start()
    
    def _on_download(self, item: ShopCosmeticItem):
        """Download a purchased cosmetic.

        For background cosmetics: decode the sprite bytes from the server,
        save them under ``save/cosmetics/backgrounds/<name>.png`` and
        register the cosmetic in ``game_globals.shop_backgrounds`` so the
        settings background selector can list it.
        """
        runtime_globals.game_sound.play("menu")

        def do_download():
            try:
                import base64, io, os
                from services.shop_image_cache import shop_image_cache
                success, data = omninet_service.download_cosmetic(item.id)
                if not success or not isinstance(data, dict):
                    runtime_globals.game_sound.play("cancel")
                    return

                is_background = (item.cosmetic_type or '').lower() == 'background'
                if is_background:
                    # the player's own save folder: bought per account
                    out_dir = os.path.join(game_globals.get_save_dir(), "cosmetics", "backgrounds")
                    os.makedirs(out_dir, exist_ok=True)
                    sprites = data.get('sprites') or {}
                    if not sprites:
                        base = item.sprite_name or ''
                        sprites = {f"{base if base.startswith('bg_') else 'bg_' + base}.png": ""}

                    def picture(raw):
                        try:
                            return pygame.image.load(io.BytesIO(raw)).convert_alpha() if raw else None
                        except Exception:
                            return None

                    saved_paths = {}
                    preview = None
                    for sprite_name, b64 in sprites.items():
                        try:
                            raw = base64.b64decode(b64 or "")
                        except Exception:
                            raw = b""
                        surf = picture(raw)
                        if surf is None:
                            # Omninet's download names the files but leaves
                            # their pictures empty: the shop's own picture of
                            # the background stands in (it wrote 0-byte files
                            # that never drew, 2026-10-22).
                            if preview is None:
                                preview = omninet_service.get_shop_sprite_bytes('cosmetic', item.id) or b""
                            raw = preview
                            surf = picture(raw)
                        if surf is None:
                            continue
                        out_path = os.path.join(out_dir, sprite_name)
                        with open(out_path, 'wb') as f:
                            f.write(raw)
                        saved_paths[sprite_name] = out_path
                        # Also cache the surface so the settings selector
                        # can blit instantly without re-reading from disk.
                        shop_image_cache.put(item.id, sprite_name, surf, kind='background')
                    if not saved_paths:
                        runtime_globals.game_console.log(
                            f"[ShopCosmeticsView] {item.name}: the download has no picture")
                        runtime_globals.game_sound.play("cancel")
                        return

                    game_globals.shop_backgrounds[item.id] = {
                        'id': item.id,
                        'name': item.name,
                        'label': item.name,
                        'sprite_name': item.sprite_name or '',
                        'day_night': bool(item.day_night),
                        'high_res': bool(item.high_res),
                        'sprite_paths': saved_paths,
                    }
                    try:
                        game_globals.save()
                    except Exception:
                        pass
            except Exception as e:
                runtime_globals.game_console.log(
                    f"[ShopCosmeticsView] Download error: {e}")
                runtime_globals.game_sound.play("cancel")

        threading.Thread(target=do_download, daemon=True).start()
    
    def _on_detail_back(self):
        """Go back from detail view to list view."""
        runtime_globals.game_sound.play("cancel")
        self._clear_detail_components()

        if self.shop_list:
            self.shop_list.visible = True
        if self.back_button:
            self.back_button.visible = True
        # Drop the full-screen background preview so the list view returns
        # to its plain black backdrop.
        if self.background:
            self.background.clear_image()

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
        
        runtime_globals.game_console.log("[ShopCosmeticsView] Cleanup complete")
