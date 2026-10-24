"""
Shop List Component - Vertical scrollable list for shop items
Inherits from BaseList and provides specialized rendering for modules, items, cosmetics, and gameplay.
"""
import os
import pygame
from ui.components.base_list import BaseList
from core import runtime_globals, game_globals
from utils.asset_utils import image_load


_COIN_SPRITE = None
_COIN_SPRITE_SOURCE = None
_DIAMOND_SPRITE = None

#: What a shop entry is priced in (Omninet's ShopSpecial.currency).
CURRENCY_COINS = "coins"
CURRENCY_CONTRIBUTION_POINTS = "contribution_points"
#: A price's colour: gold coins, blue contribution points.
PRICE_COLOURS = {CURRENCY_COINS: (255, 215, 80), CURRENCY_CONTRIBUTION_POINTS: (130, 210, 255)}


def _get_coin_sprite() -> pygame.Surface:
    """Return the shop coin sprite (loaded lazily once)."""
    global _COIN_SPRITE, _COIN_SPRITE_SOURCE
    if _COIN_SPRITE is not None:
        return _COIN_SPRITE
    try:
        path = os.path.join("assets", "ui", "Shop_Coin_1.png")
        if os.path.exists(path):
            _COIN_SPRITE_SOURCE = image_load(path).convert_alpha()
            _COIN_SPRITE = _COIN_SPRITE_SOURCE
    except Exception as e:
        runtime_globals.game_console.log(f"[ShopList] Coin sprite load error: {e}")
    return _COIN_SPRITE


def _get_diamond_sprite() -> pygame.Surface:
    """The contribution points icon (assets/ui/Shop_Diamond_1.png), loaded once."""
    global _DIAMOND_SPRITE
    if _DIAMOND_SPRITE is None:
        try:
            path = os.path.join("assets", "ui", "Shop_Diamond_1.png")
            if os.path.exists(path):
                _DIAMOND_SPRITE = image_load(path).convert_alpha()
        except Exception as e:
            runtime_globals.game_console.log(f"[ShopList] Diamond sprite load error: {e}")
    return _DIAMOND_SPRITE


def currency_icon_path(currency: str) -> str:
    """The icon file of a currency, for an Image component."""
    if currency == CURRENCY_CONTRIBUTION_POINTS:
        return "assets/ui/Shop_Diamond_1.png"
    return "assets/ui/Shop_Coin_1.png"


def _scaled_coin(size_px: int, currency: str = CURRENCY_COINS) -> pygame.Surface:
    """Return the currency's icon (the coin, or the contribution points'
    diamond) scaled to *size_px* on its longer edge."""
    src = _get_diamond_sprite() if currency == CURRENCY_CONTRIBUTION_POINTS else _get_coin_sprite()
    if src is None or size_px <= 0:
        return None
    w, h = src.get_size()
    scale = size_px / max(w, h)
    size = (max(1, int(w * scale)), max(1, int(h * scale)))
    if currency == CURRENCY_CONTRIBUTION_POINTS:
        # Pixel art: whole-pixel scaling keeps its edges.
        return pygame.transform.scale(src, size)
    return pygame.transform.smoothscale(src, size)


def _blit_price_or_owned(surface, item, font, row_y, row_height, right_edge, padding):
    """Draw a green ``Installed``/``Owned`` label, ``Free`` (Free Mode), or
    ``<coin icon> N`` on the right.

    Free Mode has no purchases, so "Owned" is meaningless there — what
    matters is whether the module is installed locally.  Progress Mode
    keeps showing purchase state ("Owned").

    Returns the x of the leftmost pixel drawn (useful for callers that
    want to avoid overlapping the price area).
    """
    is_free_mode = game_globals.is_free_mode()
    if is_free_mode:
        label = "Installed" if getattr(item, 'installed', False) else None
    else:
        label = "Owned" if item.owned else None
    if label:
        text_surf = font.render(label, True, (120, 220, 120))
        x = right_edge - padding - text_surf.get_width()
        y = row_y + (row_height - text_surf.get_height()) // 2
        surface.blit(text_surf, (x, y))
        return x

    # Free Mode has no economy — render "Free" in green instead of the
    # coin price.  Also covers items the server priced at 0 in any mode.
    if is_free_mode or item.price <= 0:
        text_surf = font.render("Free", True, (120, 220, 120))
        x = right_edge - padding - text_surf.get_width()
        y = row_y + (row_height - text_surf.get_height()) // 2
        surface.blit(text_surf, (x, y))
        return x

    # Progress Mode, not owned: <coin> NN in gold, or <diamond> NN in blue
    # for a price in contribution points.
    currency = getattr(item, 'currency', CURRENCY_COINS) or CURRENCY_COINS
    value_surf = font.render(str(item.price), True,
                             PRICE_COLOURS.get(currency, PRICE_COLOURS[CURRENCY_COINS]))
    icon_size = max(8, value_surf.get_height())
    coin = _scaled_coin(icon_size, currency)
    gap = 2
    total_w = (coin.get_width() if coin else 0) + gap + value_surf.get_width()
    x = right_edge - padding - total_w
    y = row_y + (row_height - value_surf.get_height()) // 2
    if coin:
        coin_y = row_y + (row_height - coin.get_height()) // 2
        surface.blit(coin, (x, coin_y))
    value_x = x + (coin.get_width() if coin else 0) + gap
    surface.blit(value_surf, (value_x, y))
    return x


class ShopListItem:
    """Base class for shop list items."""
    #: What the price is paid with (CURRENCY_COINS unless a Special says).
    currency = CURRENCY_COINS

    def __init__(self, item_id: str, name: str, price: int, owned: bool = False):
        self.id = item_id
        self.name = name
        self.price = price
        self.owned = owned


class ShopModuleItem(ShopListItem):
    """Module item for shop list."""
    def __init__(self, item_id: str, name: str, price: int, owned: bool = False,
                 creator: str = "", version: str = "", official: bool = False,
                 description: str = "", size_mb: float = 0, contributors: str = "",
                 updated_at: str = "", category: str = "", installed: bool = False):
        super().__init__(item_id, name, price, owned)
        self.installed = installed
        self.creator = creator
        self.version = version
        self.official = official
        self.description = description
        self.size_mb = size_mb
        self.contributors = contributors
        self.updated_at = updated_at
        self.category = category
        # Sprites fetched async from server
        self.icon = None   # BattleIcon.png - shown in list
        self.logo = None   # logo.png - shown in detail view
        self._icon_fetching = False
        self._logo_fetching = False


class ShopGameplayItem(ShopListItem):
    """Gameplay item for shop list."""
    def __init__(self, item_id: str, name: str, price: int, owned: bool = False,
                 item_type: str = "", description: str = ""):
        super().__init__(item_id, name, price, owned)
        self.item_type = item_type
        self.description = description


class ShopInventoryItem(ShopListItem):
    """Inventory-style item for shop list (consumables)."""
    def __init__(self, item_id: str, name: str, price: int, owned: bool = False,
                 icon: pygame.Surface = None, description: str = "", quantity: int = 0):
        super().__init__(item_id, name, price, owned)
        self.icon = icon
        self.description = description
        self.quantity = quantity


class ShopCosmeticItem(ShopListItem):
    """Cosmetic item for shop list."""
    def __init__(self, item_id: str, name: str, price: int, owned: bool = False,
                 icon: pygame.Surface = None, preview: pygame.Surface = None,
                 cosmetic_type: str = "", day_night: bool = True,
                 high_res: bool = False, sprite_name: str = ""):
        super().__init__(item_id, name, price, owned)
        self.icon = icon
        self.preview = preview
        self.cosmetic_type = cosmetic_type
        self.day_night = day_night
        self.high_res = high_res
        self.sprite_name = sprite_name


class ShopSpecialItem(ShopCosmeticItem):
    """A Special: priced in coins or contribution points; a background one
    draws like a background cosmetic."""
    def __init__(self, item_id: str, name: str, price: int, owned: bool = False,
                 icon: pygame.Surface = None, preview: pygame.Surface = None,
                 special_type: str = "", day_night: bool = False, high_res: bool = False,
                 sprite_name: str = "", currency: str = CURRENCY_COINS,
                 description: str = "", supported: bool = True):
        super().__init__(item_id, name, price, owned, icon=icon, preview=preview,
                         cosmetic_type=(special_type or "Special").capitalize(),
                         day_night=day_night, high_res=high_res, sprite_name=sprite_name)
        self.special_type = special_type or ""
        self.currency = currency or CURRENCY_COINS
        self.description = description or ""
        #: False for a kind of Special this Omnipet cannot use yet.
        self.supported = supported


class ShopList(BaseList):
    """Generic shop list supporting different item types."""
    
    # List display modes
    MODE_MODULES = "modules"
    MODE_GAMEPLAY = "gameplay"
    MODE_ITEMS = "items"
    MODE_COSMETICS = "cosmetics"
    MODE_SPECIALS = "specials"
    
    def __init__(self, x, y, width, height, mode=MODE_MODULES, on_item_selected=None):
        """Initialize the shop list with vertical orientation.
        
        Args:
            x, y, width, height: Component dimensions
            mode: Display mode (modules, gameplay, items, cosmetics)
            on_item_selected: Callback when an item is selected (receives item)
        """
        super().__init__(x, y, width, height, orientation="vertical")
        
        self.mode = mode
        self.on_item_selected_callback = on_item_selected
        
        # Custom settings for shop list
        if mode in (self.MODE_ITEMS, self.MODE_COSMETICS, self.MODE_SPECIALS):
            self.base_item_size = 36  # Height for icon-based items
        else:
            self.base_item_size = 44  # Height for text-based items (modules, gameplay)
        
        self.base_item_spacing = 6
        self.base_arrow_size = 12
        self.base_margin = 2
        
        # Visual settings
        self.cut_width = 8
        # ShopList draws its own per-item polygons; both the global
        # items-area background and the 1px theme-colored border around
        # that area are undesired here.
        self.show_background = False
        self.show_border = False
        
        # Text scrolling for long names
        self.text_scroll_speed = 20 * (30 / (runtime_globals.FRAME_RATE if hasattr(runtime_globals, 'FRAME_RATE') else 30))
        self.text_scroll_offset = {}
        self.text_scroll_delay = 1000
        self.text_scroll_start_time = {}
    
    def on_item_activated(self, item):
        """Called when an item is activated (clicked/selected)."""
        if self.on_item_selected_callback:
            self.on_item_selected_callback(item)
    
    def _on_item_clicked(self, index, was_already_selected=False):
        """Called by base_list when an item is clicked with the mouse (correct mouse_over_index)."""
        if 0 <= index < len(self.items):
            self.on_item_activated(self.items[index])

    def _on_item_activated(self, index, interaction_type="keyboard"):
        """Called by base_list when an item is activated via keyboard (A/ENTER)."""
        if 0 <= index < len(self.items):
            self.on_item_activated(self.items[index])

    def handle_mouse_click(self, mouse_pos, action):
        """Called by UIManager on LCLICK — delegates to base_list's position-based click handler."""
        if not (runtime_globals.INPUT_MODE in [runtime_globals.MOUSE_MODE, runtime_globals.TOUCH_MODE]):
            return False
        if hasattr(runtime_globals, 'game_input') and hasattr(runtime_globals.game_input, 'is_dragging'):
            if runtime_globals.game_input.is_dragging():
                return False
        return self._handle_mouse_click(mouse_pos)

    def handle_event(self, event):
        """Delegate to base_list; activation is handled via _on_item_clicked/_on_item_activated."""
        return super().handle_event(event)
    
    def _draw_items(self, surface):
        """Draw shop items based on current mode."""
        if not self.items or not self.items_rect:
            return
        
        if self.mode == self.MODE_MODULES:
            self._draw_module_items(surface)
        elif self.mode == self.MODE_GAMEPLAY:
            self._draw_gameplay_items(surface)
        elif self.mode == self.MODE_ITEMS:
            self._draw_inventory_items(surface)
        elif self.mode in (self.MODE_COSMETICS, self.MODE_SPECIALS):
            self._draw_cosmetic_items(surface)
    
    def _get_item_colors(self, index: int):
        """Get colors based on selection and focus state."""
        colors = self.manager.get_theme_colors()
        
        is_selected = (index == self.active_index)
        is_hovered = (index == self.mouse_over_index)
        is_keyboard_focused = (self.focused and index == self.selected_index)
        is_focus_highlighted = (is_hovered or is_keyboard_focused) and runtime_globals.INPUT_MODE != runtime_globals.TOUCH_MODE
        
        if is_selected:
            fill_color = colors["fg"]
            text_color = colors["bg"]
            border_color = colors["bg"]
        else:
            fill_color = colors["bg"]
            text_color = colors["fg"]
            border_color = colors["fg"]
        
        if is_focus_highlighted:
            border_color = colors["highlight"]
            text_color = colors["highlight"]
        
        return fill_color, text_color, border_color
    
    def _draw_item_background(self, surface, item_y, fill_color, border_color):
        """Draw item background rectangle."""
        border_size = self.manager.get_border_size()
        
        # Simple rectangle with small cut corners
        rect = pygame.Rect(self.items_rect.x, item_y, self.items_rect.width, self.item_size)
        cut = self.manager.scale_value(self.cut_width)

        # rect.right equals the surface width (items_rect spans the whole
        # component), and pixels are drawn ON the polygon points -- an edge
        # at x == width falls outside the surface and the right border gets
        # clipped away entirely.  Keep it on the last drawable column.
        right = rect.right - 1
        points = [
            (rect.x + cut, rect.y),
            (right, rect.y),
            (right, rect.bottom - cut),
            (right - cut, rect.bottom),
            (rect.x, rect.bottom),
            (rect.x, rect.y + cut),
        ]
        
        pygame.draw.polygon(surface, fill_color, points)
        pygame.draw.polygon(surface, border_color, points, border_size)
    
    def _draw_module_items(self, surface):
        """Draw module items: name, creator, version, price/owned."""
        item_total_size = self.item_size + self.item_spacing
        first_visible = max(0, int(self.scroll_offset // item_total_size))
        last_visible = min(len(self.items), first_visible + self.get_visible_item_count() + 2)

        for i in range(first_visible, last_visible):
            if i >= len(self.items):
                break

            item = self.items[i]
            item_y = self.items_rect.y + (i * item_total_size) - self.scroll_offset

            if item_y + self.item_size < self.items_rect.y or item_y > self.items_rect.y + self.items_rect.height:
                continue

            fill_color, text_color, border_color = self._get_item_colors(i)
            self._draw_item_background(surface, item_y, fill_color, border_color)

            # Fonts
            name_font = self.get_font("text", custom_size=18 * self.manager.ui_scale)
            small_font = self.get_font("text", custom_size=16 * self.manager.ui_scale)

            padding = self.manager.scale_value(6)

            # Icon (left side, proportionally scaled to fit item height)
            icon_offset = 0
            if hasattr(item, 'icon') and item.icon:
                icon_max = self.item_size - padding * 2
                orig_w, orig_h = item.icon.get_size()
                scale = min(icon_max / orig_w, icon_max / orig_h)
                icon_w = int(orig_w * scale)
                icon_h = int(orig_h * scale)
                scaled_icon = pygame.transform.scale(item.icon, (icon_w, icon_h))
                icon_x = self.items_rect.x + padding
                icon_y = item_y + (self.item_size - icon_h) // 2
                surface.blit(scaled_icon, (icon_x, icon_y))
                icon_offset = icon_w + padding

            text_left = self.items_rect.x + padding + icon_offset

            # Draw official badge if applicable
            badge_offset = 0
            if hasattr(item, 'official') and item.official:
                badge_text = "★"
                badge_surface = small_font.render(badge_text, True, text_color)
                surface.blit(badge_surface, (text_left, item_y + padding))
                badge_offset = badge_surface.get_width() + 4

            # Name (top left, after icon)
            name_text = item.name[:20] + "..." if len(item.name) > 20 else item.name
            name_surface = name_font.render(name_text, True, text_color)
            surface.blit(name_surface, (text_left + badge_offset, item_y + padding))

            # Price / Owned (top right) — coin icon + yellow value, green Owned
            _blit_price_or_owned(surface, item, small_font, item_y + padding - 2,
                                  small_font.get_height() + 4,
                                  self.items_rect.right, padding)

            # Creator and version (bottom left, after icon)
            creator_text = f"by {item.creator}" if hasattr(item, 'creator') and item.creator else ""
            version_text = f"v{item.version}" if hasattr(item, 'version') and item.version else ""
            info_text = f"{creator_text} {version_text}".strip()
            if info_text:
                info_surface = small_font.render(info_text[:30], True, text_color)
                surface.blit(info_surface, (text_left, item_y + self.item_size - padding - info_surface.get_height()))
    
    def _draw_gameplay_items(self, surface):
        """Draw gameplay items: name and type."""
        item_total_size = self.item_size + self.item_spacing
        first_visible = max(0, int(self.scroll_offset // item_total_size))
        last_visible = min(len(self.items), first_visible + self.get_visible_item_count() + 2)
        
        for i in range(first_visible, last_visible):
            if i >= len(self.items):
                break
            
            item = self.items[i]
            item_y = self.items_rect.y + (i * item_total_size) - self.scroll_offset
            
            if item_y + self.item_size < self.items_rect.y or item_y > self.items_rect.y + self.items_rect.height:
                continue
            
            fill_color, text_color, border_color = self._get_item_colors(i)
            self._draw_item_background(surface, item_y, fill_color, border_color)
            
            name_font = self.get_font("text", custom_size=18 * self.manager.ui_scale)
            small_font = self.get_font("text", custom_size=16 * self.manager.ui_scale)
            
            padding = self.manager.scale_value(6)
            
            # Name (top left)
            name_text = item.name[:25] + "..." if len(item.name) > 25 else item.name
            name_surface = name_font.render(name_text, True, text_color)
            surface.blit(name_surface, (self.items_rect.x + padding, item_y + padding))
            
            # Price / Owned (top right) — coin icon + yellow value, green Owned
            _blit_price_or_owned(surface, item, small_font, item_y + padding - 2,
                                  small_font.get_height() + 4,
                                  self.items_rect.right, padding)
            
            # Type (bottom left)
            if hasattr(item, 'item_type') and item.item_type:
                type_surface = small_font.render(item.item_type, True, text_color)
                surface.blit(type_surface, (self.items_rect.x + padding, item_y + self.item_size - padding - type_surface.get_height()))
    
    def _draw_inventory_items(self, surface):
        """Draw inventory-style items with icon, name, and price."""
        item_total_size = self.item_size + self.item_spacing
        first_visible = max(0, int(self.scroll_offset // item_total_size))
        last_visible = min(len(self.items), first_visible + self.get_visible_item_count() + 2)
        
        icon_size = self.manager.scale_value(28)
        
        for i in range(first_visible, last_visible):
            if i >= len(self.items):
                break
            
            item = self.items[i]
            item_y = self.items_rect.y + (i * item_total_size) - self.scroll_offset
            
            if item_y + self.item_size < self.items_rect.y or item_y > self.items_rect.y + self.items_rect.height:
                continue
            
            fill_color, text_color, border_color = self._get_item_colors(i)
            self._draw_item_background(surface, item_y, fill_color, border_color)
            
            name_font = self.get_font("text", custom_size=16 * self.manager.ui_scale)
            small_font = self.get_font("text", custom_size=16 * self.manager.ui_scale)
            
            padding = self.manager.scale_value(4)
            
            # Icon (left side)
            icon_x = self.items_rect.x + padding
            icon_y = item_y + (self.item_size - icon_size) // 2
            
            if hasattr(item, 'icon') and item.icon:
                scaled_icon = pygame.transform.scale(item.icon, (icon_size, icon_size))
                surface.blit(scaled_icon, (icon_x, icon_y))
            
            text_x = icon_x + icon_size + padding
            
            # Name
            name_text = item.name[:18] + "..." if len(item.name) > 18 else item.name
            name_surface = name_font.render(name_text, True, text_color)
            surface.blit(name_surface, (text_x, item_y + padding + 2))
            
            # Price / quantity / Owned (bottom right)
            if item.owned and hasattr(item, 'quantity') and item.quantity > 0:
                qty_surf = small_font.render(f"x{item.quantity}", True, (120, 220, 120))
                qx = self.items_rect.right - padding - qty_surf.get_width()
                qy = item_y + self.item_size - padding - qty_surf.get_height()
                surface.blit(qty_surf, (qx, qy))
            else:
                row_top = item_y + self.item_size - padding - small_font.get_height() - 2
                _blit_price_or_owned(surface, item, small_font, row_top,
                                      small_font.get_height() + 4,
                                      self.items_rect.right, padding)
    
    def _draw_cosmetic_items(self, surface):
        """Draw cosmetic items with small icon and name."""
        item_total_size = self.item_size + self.item_spacing
        first_visible = max(0, int(self.scroll_offset // item_total_size))
        last_visible = min(len(self.items), first_visible + self.get_visible_item_count() + 2)
        
        icon_size = self.manager.scale_value(28)
        
        for i in range(first_visible, last_visible):
            if i >= len(self.items):
                break
            
            item = self.items[i]
            item_y = self.items_rect.y + (i * item_total_size) - self.scroll_offset
            
            if item_y + self.item_size < self.items_rect.y or item_y > self.items_rect.y + self.items_rect.height:
                continue
            
            fill_color, text_color, border_color = self._get_item_colors(i)
            self._draw_item_background(surface, item_y, fill_color, border_color)
            
            name_font = self.get_font("text", custom_size=16 * self.manager.ui_scale)
            small_font = self.get_font("text", custom_size=16 * self.manager.ui_scale)
            
            padding = self.manager.scale_value(4)
            
            # Icon (left side)
            icon_x = self.items_rect.x + padding
            icon_y = item_y + (self.item_size - icon_size) // 2
            
            if hasattr(item, 'icon') and item.icon:
                scaled_icon = pygame.transform.scale(item.icon, (icon_size, icon_size))
                surface.blit(scaled_icon, (icon_x, icon_y))
            
            text_x = icon_x + icon_size + padding
            
            # Name and type
            name_text = item.name[:20] + "..." if len(item.name) > 20 else item.name
            name_surface = name_font.render(name_text, True, text_color)
            surface.blit(name_surface, (text_x, item_y + padding + 2))
            
            if hasattr(item, 'cosmetic_type') and item.cosmetic_type:
                type_surface = small_font.render(item.cosmetic_type, True, text_color)
                surface.blit(type_surface, (text_x, item_y + self.item_size - padding - type_surface.get_height()))
            
            # Price / Owned (right) — coin icon + yellow value, green Owned
            _blit_price_or_owned(surface, item, small_font, item_y,
                                  self.item_size, self.items_rect.right, padding)
