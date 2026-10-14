"""
ShopModulesView - Browse and purchase game modules
Shows list of available modules with details view for purchase/download.
"""
import threading
import pygame


# Pricing decisions live on the server.  The shop listing endpoint returns
# the correct per-user ``price`` (0 for the player's first module, the
# fixed price for everything else); the client just renders it.

from ui.ui_manager import UIManager
from ui.components.title_scene import TitleScene
from ui.components.button import Button
from ui.components.background import Background
from ui.components.image import Image
from ui.components.label import Label
from ui.components.text_panel import TextPanel
from ui.components.shop_list import ShopList, ShopModuleItem
from ui.ui_constants import BASE_RESOLUTION
from core import runtime_globals, game_globals
from services.omninet_service import omninet_service
from services.shop_image_cache import shop_image_cache
from utils.asset_utils import image_load
from utils.module_utils import get_modules_dir, load_modules


class ShopModulesView:
    """Module shop view with list and detail subviews."""
    
    STATE_LIST = "list"
    STATE_DETAIL = "detail"
    STATE_LOADING = "loading"
    
    def __init__(self, ui_manager: UIManager, change_view_callback, discord_module=None):
        """Initialize the shop modules view.
        
        Args:
            ui_manager: The UI manager instance
            change_view_callback: Callback to change to another view
            discord_module: Reference to the Discord module (unused, for compatibility)
        """
        self.ui_manager = ui_manager
        self.change_view = change_view_callback
        
        self.state = self.STATE_LOADING
        self.selected_item = None
        self.modules_data = []
        
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
        self._detail_back_button = None
        self._downloading = False  # True while a module download is in progress

        self._setup_ui()
        self._load_modules_async()
    
    def _setup_ui(self):
        """Setup the UI components."""
        ui_width = ui_height = BASE_RESOLUTION
        
        # Background
        self.background = Background(ui_width, ui_height)
        self.background.set_regions([(0, ui_height, "black")])
        self.ui_manager.add_component(self.background)
        
        # Title
        self.title_scene = TitleScene(0, 9, "MODULES")
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
        
        runtime_globals.game_console.log("[ShopModulesView] UI setup complete")
    
    def _setup_coin_display(self):
        """Setup the coin icon and amount display.

        Free Play hides coins entirely — there's no economy in that mode
        (modules are free, items aren't reachable from the shop UI for
        Free Mode players), so showing a balance is misleading clutter.
        """
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
        """Setup the list view with loaded modules."""
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
            mode=ShopList.MODE_MODULES,
            on_item_selected=self._on_module_selected
        )
        
        # Convert API data to ShopModuleItem objects
        items = []
        for mod in self.modules_data:
            owned = game_globals.purchases.owns_module(mod.get('id', ''))
            installed = mod.get('name', '') in runtime_globals.game_modules
            items.append(ShopModuleItem(
                item_id=mod.get('id', ''),
                name=mod.get('name', 'Unknown'),
                price=mod.get('price', 0),
                owned=owned,
                installed=installed,
                creator=mod.get('author', ''),
                version=mod.get('version', '1.0'),
                official=mod.get('official', False),
                description=mod.get('description', ''),
                size_mb=mod.get('size_mb', 0),
                contributors=mod.get('contributors', ''),
                updated_at=mod.get('updated_at', ''),
                category=mod.get('category', '')
            ))
        
        self.shop_list.set_items(items)
        self.ui_manager.add_component(self.shop_list)
        self.ui_manager.set_focused_component(self.shop_list)

        for item in items:
            self._fetch_item_icon(item)

        self.state = self.STATE_LIST
    
    DETAIL_PADDING = 10
    DETAIL_TOP = 35

    def _add_detail_logo(self, item: ShopModuleItem):
        """Draw the module's logo in the detail view's logo area."""
        logo_img = Image(BASE_RESOLUTION - self.DETAIL_PADDING - 80, self.DETAIL_TOP, 80, 88,
                         image_surface=item.logo, top_align=True)
        self.ui_manager.add_component(logo_img)
        self.detail_components.append(logo_img)

    def _show_late_logo(self, item: ShopModuleItem):
        """A logo arrived after the detail view was built."""
        if self.state != self.STATE_DETAIL or self.selected_item is not item:
            return
        if self._downloading:
            # rebuilding would reset the download's status line and button
            self._add_detail_logo(item)
        else:
            self._setup_detail_view(item)

    def _setup_detail_view(self, item: ShopModuleItem):
        """Setup the detail view for a selected module."""
        self._clear_detail_components()
        
        # Hide list and the persistent back button so it doesn't intercept clicks
        if self.shop_list:
            self.shop_list.visible = False
        if self.back_button:
            self.back_button.visible = False
        
        padding = self.DETAIL_PADDING
        y_offset = self.DETAIL_TOP

        # Logo area (right side, 80x88 in base units)
        if item.logo:
            self._add_detail_logo(item)
        elif not item._logo_fetching:
            self._fetch_item_logo(item)

        # Module name (large)
        name_label = Label(0, y_offset, item.name, is_title=True)
        self.ui_manager.add_component(name_label)
        self.detail_components.append(name_label)
        y_offset += 25
        
        # Official badge
        if item.official:
            official_label = Label(padding, y_offset, "Official Module", is_title=False)
            self.ui_manager.add_component(official_label)
            self.detail_components.append(official_label)
            y_offset += 18
        
        # Author
        if item.creator:
            author_label = Label(padding, y_offset, f"Author: {item.creator}", is_title=False)
            self.ui_manager.add_component(author_label)
            self.detail_components.append(author_label)
            y_offset += 16
        
        # Contributors
        if item.contributors:
            contrib_label = Label(padding, y_offset, f"Contributors: {item.contributors[:40]}", is_title=False)
            self.ui_manager.add_component(contrib_label)
            self.detail_components.append(contrib_label)
            y_offset += 16
        
        # Version and size
        info_text = f"v{item.version}"
        if item.size_mb > 0:
            info_text += f" | {item.size_mb:.1f} MB"
        info_label = Label(padding, y_offset, info_text, is_title=False)
        self.ui_manager.add_component(info_label)
        self.detail_components.append(info_label)
        y_offset += 16
        
        # Last updated
        if item.updated_at:
            updated_label = Label(padding, y_offset, f"Updated: {item.updated_at[:10]}", is_title=False)
            self.ui_manager.add_component(updated_label)
            self.detail_components.append(updated_label)
            y_offset += 16
        
        y_offset += 5

        # Bottom-anchored geometry: buttons at the very bottom, the
        # price/status line right above them, and the description panel
        # stretched to fill everything in between.
        btn_width = 80
        btn_height = 28
        btn_y = BASE_RESOLUTION - btn_height - 10
        status_y = btn_y - 20

        # Description panel (fills the remaining space; overflowing text
        # auto-scrolls slowly -- see TextPanel).
        desc_height = max(30, status_y - y_offset - 4)
        desc_panel = TextPanel(padding, y_offset, BASE_RESOLUTION - padding * 2, desc_height,
                               item.description or "No description available.")
        self.ui_manager.add_component(desc_panel)
        self.detail_components.append(desc_panel)
        y_offset = status_y

        # Determine installation state
        installed_module = runtime_globals.game_modules.get(item.name)
        installed_version = installed_module.version if installed_module else None
        is_free = game_globals.is_free_mode()
        can_access = item.owned or is_free
        coins = getattr(game_globals, 'coins', 0)

        # Price block — yellow label, coin icon + value, "Free" when zero,
        # green "Already Owned" / "Purchase Successful" when applicable.
        # The server already decided the price (0 = the player's free
        # first module, fixed price otherwise); we just render it.
        price_x = 2  # 2 base px from the left border
        just_purchased = getattr(item, '_just_purchased', False)
        if is_free:
            # Free Mode has no purchases, so "owned" is meaningless here --
            # surface local installation state instead.
            price_text = "Installed" if installed_module is not None else "Free"
            price_color = (120, 220, 120)
            show_coin = False
        elif item.owned:
            price_text = "Purchase Successful" if just_purchased else "Already Owned"
            price_color = (120, 220, 120)
            show_coin = False
        elif item.price <= 0:
            price_text = "Free"
            price_color = (120, 220, 120)
            show_coin = False
        else:
            price_text = "Price:"
            price_color = (255, 215, 80)  # yellow
            show_coin = True

        # max_width keeps the longest status this line carries -- a sprite
        # sync reporting a percentage and a Digimon name -- inside the screen:
        # the label shrinks its font rather than running off the right edge.
        price_label = Label(price_x, y_offset, price_text, is_title=False,
                            color_override=price_color,
                            max_width=BASE_RESOLUTION - price_x * 2)
        self.ui_manager.add_component(price_label)
        self.detail_components.append(price_label)
        # The price line doubles as the download status label ("Downloading
        # x%" / "Error, try again" / "Checking" / "Installed"/"Owned").
        self._status_label = price_label

        # Coin icon + value (only when actually charging the player)
        if show_coin:
            from ui.components.image import Image as _Image
            coin_icon_x = price_x + 50
            coin_icon = _Image(coin_icon_x, y_offset - 1, 14, 14,
                               image_path="assets/ui/Shop_Coin_1.png")
            self.ui_manager.add_component(coin_icon)
            self.detail_components.append(coin_icon)
            value_label = Label(coin_icon_x + 18, y_offset, str(item.price),
                                is_title=False, color_override=(255, 215, 80))
            self.ui_manager.add_component(value_label)
            self.detail_components.append(value_label)

        # Action button: Purchase / Download / Update / Updated
        if not can_access:
            action_text = "Purchase"
            action_callback = lambda: self._on_buy(item)
            # Disable buy if the player can't afford the price the server
            # set.  Price 0 (free first module) is always allowed.
            button_enabled = item.price <= 0 or coins >= item.price
        elif installed_version is not None and installed_version == item.version:
            action_text = "Updated"
            action_callback = None
            button_enabled = False
        elif installed_version is not None and installed_version != item.version:
            action_text = "Update"
            action_callback = lambda: (self._on_download(item) if item.owned else self._on_free_download(item))
            button_enabled = True
        else:
            action_text = "Download"
            action_callback = lambda: (self._on_download(item) if item.owned else self._on_free_download(item))
            button_enabled = True

        action_button = Button(
            BASE_RESOLUTION - btn_width - padding, btn_y, btn_width, btn_height,
            action_text, action_callback,
            cut_corners={'tl': True, 'tr': False, 'bl': False, 'br': True},
            enabled=button_enabled
        )
        self.ui_manager.add_component(action_button)
        self.detail_components.append(action_button)
        # Track for in-place updates from the download worker.
        self._action_button = action_button
        
        # Back to list button
        back_list_button = Button(
            padding, btn_y, 60, btn_height,
            "Back", self._on_detail_back,
            cut_corners={'tl': True, 'tr': False, 'bl': False, 'br': True}
        )
        self.ui_manager.add_component(back_list_button)
        self.detail_components.append(back_list_button)
        # Track for disabling while a download is in progress.
        self._detail_back_button = back_list_button
        
        self.state = self.STATE_DETAIL
    
    def _clear_detail_components(self):
        """Remove all detail view components."""
        for comp in self.detail_components:
            if comp in self.ui_manager.components:
                self.ui_manager.remove_component(comp)
        self.detail_components.clear()
    
    def _load_modules_async(self):
        """Load modules from server in background thread."""
        def fetch_modules():
            try:
                success, data = omninet_service.get_shop_modules()
                if success:
                    # an empty shelf is an answer, not a failure
                    self.modules_data = data or []
                else:
                    self.modules_data = []
                    runtime_globals.game_console.log(f"[ShopModulesView] Failed to load modules")
            except Exception as e:
                runtime_globals.game_console.log(f"[ShopModulesView] Error loading modules: {e}")
                self.modules_data = []
            
            # Schedule UI update on main thread
            self._on_modules_loaded()
        
        threading.Thread(target=fetch_modules, daemon=True).start()
    
    def _on_modules_loaded(self):
        """Called when modules are loaded from server."""
        self._setup_list_view()

    def _fetch_item_icon(self, item):
        """Fetch BattleIcon.png for a list item in the background.

        Hits the in-memory cache first so re-entering the shop doesn't
        re-pull sprites that were already loaded earlier in the session.
        """
        if item.icon is not None:
            return
        cached = shop_image_cache.get(item.id, 'icon')
        if cached is not None:
            item.icon = cached
            return
        if item._icon_fetching:
            return
        item._icon_fetching = True

        def fetch():
            try:
                surface = omninet_service.get_module_sprite(item.id, 'icon')
                if surface is not None:
                    shop_image_cache.put(item.id, 'icon', surface)
                item.icon = surface
            finally:
                item._icon_fetching = False

        threading.Thread(target=fetch, daemon=True).start()

    def _fetch_item_logo(self, item):
        """Fetch logo.png for a detail item in the background."""
        if item.logo is not None:
            return
        cached = shop_image_cache.get(item.id, 'logo')
        if cached is not None:
            item.logo = cached
            self._show_late_logo(item)
            return
        if item._logo_fetching:
            return
        item._logo_fetching = True

        def fetch():
            try:
                surface = omninet_service.get_module_sprite(item.id, 'logo')
                if surface is not None:
                    shop_image_cache.put(item.id, 'logo', surface)
                item.logo = surface
                if surface:
                    self._show_late_logo(item)
            finally:
                item._logo_fetching = False

        threading.Thread(target=fetch, daemon=True).start()
    
    def _on_module_selected(self, item: ShopModuleItem):
        """Handle module selection from list."""
        runtime_globals.game_sound.play("menu")
        self.selected_item = item
        self._setup_detail_view(item)
    
    def _on_buy(self, item: ShopModuleItem):
        """Handle buy button click."""
        coins = getattr(game_globals, 'coins', 0)
        
        if coins < item.price:
            runtime_globals.game_sound.play("cancel")
            # (suppressed) runtime_globals.game_message.add_slide("Not enough coins!", (255, 100, 100), 90)
            return
        
        runtime_globals.game_sound.play("menu")
        
        # Attempt purchase via API
        def do_purchase():
            try:
                success, message = omninet_service.purchase_item('module', item.id)
                if success:
                    # Update local state
                    game_globals.coins -= item.price
                    game_globals.purchases.add_module(item.id, item.name)
                    game_globals.save()
                    
                    item.owned = True
                    item._just_purchased = True
                    # Purchase confirmation shown by in-view label

                    # Refresh detail view
                    self._setup_detail_view(item)
                else:
                    runtime_globals.game_sound.play("cancel")
                    # Failure shown via in-view label below; suppress global slide, 90)
            except Exception as e:
                runtime_globals.game_console.log(f"[ShopModulesView] Purchase error: {e}")
                runtime_globals.game_sound.play("cancel")
                # Failure shown via in-view label below; suppress global slide, 90)
        
        threading.Thread(target=do_purchase, daemon=True).start()
    
    def _set_action_button_text(self, text, enabled=False):
        """In-place update of the detail action button from any thread.

        Rendering happens on the main thread; mutating these attrs is
        safe because they're only read by the next paint cycle.
        """
        btn = getattr(self, "_action_button", None)
        if btn is None:
            return
        try:
            btn.set_text(text)
            btn.set_enabled(enabled)
        except Exception:
            pass

    def _install_module_zip(self, item: 'ShopModuleItem', zip_bytes: bytes) -> bool:
        """Unpack the downloaded zip into modules/<name>/ (utils.module_utils:
        the installed module is only replaced once the new one is good).

        Returns True on success.
        """
        from utils.module_utils import install_zip_into, safe_module_folder
        import os
        target_dir = os.path.join(get_modules_dir(), safe_module_folder(item.name, item.id))
        return install_zip_into(target_dir, zip_bytes, item.name)

    def _set_back_enabled(self, enabled: bool):
        """Enable/disable the detail Back button (used to lock it mid-download)."""
        btn = getattr(self, "_detail_back_button", None)
        if btn is not None:
            try:
                btn.set_enabled(enabled)
            except Exception:
                pass

    # Status-label colors for the download lifecycle.
    STATUS_YELLOW = (255, 215, 80)
    STATUS_RED = (255, 100, 100)
    STATUS_GREEN = (120, 220, 120)

    def _set_status_label(self, text: str, color):
        """Update the price/status line under the description panel."""
        lbl = getattr(self, "_status_label", None)
        if lbl is None:
            return
        try:
            lbl.color_override = color
            lbl.set_text(text)
            lbl.needs_redraw = True
        except Exception:
            pass

    def _run_download(self, item: 'ShopModuleItem', mark_owned: bool):
        """Worker shared by paid + free downloads.

        The action button keeps its label and just goes disabled; all
        progress/error feedback is shown on the status label, which is far
        easier to read than text inside a greyed-out button.
        """
        runtime_globals.game_sound.play("menu")
        btn = getattr(self, "_action_button", None)
        orig_label = getattr(btn, 'text', 'Download') if btn is not None else 'Download'
        self._set_action_button_text(orig_label, enabled=False)
        self._set_status_label("Downloading 0%", self.STATUS_YELLOW)
        # Lock the Back button (and the B shortcut) until the download finishes.
        self._downloading = True
        self._set_back_enabled(False)

        def progress(pct, _dl, _total):
            self._set_status_label(f"Downloading {pct}%", self.STATUS_YELLOW)

        def sync_progress(text, done=None, total=None):
            """Status line for the sprite sync that follows the install.

            The sync is several network round trips long and used to show one
            unchanging word for all of them, which reads as a hung game -- the
            point here is that something moves. The service prefixes the module
            name, which this screen is already showing, so only the tail is
            kept and the percentage takes the space that frees.
            """
            detail = text.split(": ", 1)[-1]
            if total:
                self._set_status_label(
                    f"{done * 100 // total}% {detail}", self.STATUS_YELLOW)
            else:
                self._set_status_label(detail.capitalize(), self.STATUS_YELLOW)

        def fail(log_message):
            runtime_globals.game_console.log(f"[ShopModulesView] {log_message}")
            self._set_status_label("Error, try again", self.STATUS_RED)
            # Re-enable the button so "try again" is actually possible.
            self._set_action_button_text(orig_label, enabled=True)
            runtime_globals.game_sound.play("cancel")

        def worker():
            try:
                success, data = omninet_service.download_module_zip(
                    item.id, progress_cb=progress)
                if not success or not isinstance(data, (bytes, bytearray)):
                    err = data if isinstance(data, str) else "Download failed"
                    fail(f"Download failed for {item.name}: {err}")
                    return
                if not self._install_module_zip(item, bytes(data)):
                    fail(f"Install failed for {item.name}")
                    return
                if mark_owned:
                    game_globals.purchases.add_module(item.id, item.name)
                    game_globals.save()
                    item.owned = True
                item.installed = True
                # Refresh the in-memory module registry so the new module
                # shows up everywhere (egg picker, modules screen, etc.).
                try:
                    load_modules()
                except Exception as e:
                    runtime_globals.game_console.log(
                        f"[ShopModulesView] load_modules() failed post-install: {e}")
                # Update the local sprite assets for this freshly-downloaded
                # module from the Digimon Database. Skipped entirely if the
                # database is unreachable / there's no internet.
                try:
                    from services.sprite_sync_service import sprite_sync_service
                    mod = runtime_globals.game_modules.get(item.name)
                    if mod is not None and sprite_sync_service.is_available():
                        self._set_status_label("Checking sprites", self.STATUS_YELLOW)
                        n = sprite_sync_service.update_module(
                            mod, progress_cb=sync_progress)
                        runtime_globals.game_console.log(
                            f"[ShopModulesView] Sprite sync for {item.name}: {n} updated")
                except Exception as e:
                    runtime_globals.game_console.log(
                        f"[ShopModulesView] Sprite sync failed: {e}")
                self._set_status_label(
                    "Installed" if game_globals.is_free_mode() else "Owned",
                    self.STATUS_GREEN)
                self._set_action_button_text("Updated", enabled=False)
            except Exception as e:
                fail(f"Download worker error: {e}")
            finally:
                # Download finished (success or failure): unlock Back.
                self._downloading = False
                self._set_back_enabled(True)

        threading.Thread(target=worker, daemon=True).start()

    def _on_download(self, item: ShopModuleItem):
        """Handle download button click for owned/paid modules."""
        self._run_download(item, mark_owned=False)

    def _on_free_download(self, item: ShopModuleItem):
        """Handle free download in Free Mode (no purchase required)."""
        self._run_download(item, mark_owned=True)
    
    def _on_detail_back(self):
        """Go back from detail view to list view."""
        # Don't allow leaving the detail view mid-download.
        if getattr(self, "_downloading", False):
            return
        runtime_globals.game_sound.play("cancel")
        self._clear_detail_components()

        if self.shop_list:
            self.shop_list.visible = True
            self.ui_manager.set_focused_component(self.shop_list)
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
        
        runtime_globals.game_console.log("[ShopModulesView] Cleanup complete")
