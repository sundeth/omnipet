import pygame
from ui.components.component import UIComponent
from core import runtime_globals
from ui.ui_constants import *
from utils.asset_utils import image_load
from utils.pygame_utils import blit_with_cache


class HPBar(UIComponent):
    def __init__(self, x, y, width, height, left_progress=1.0, right_progress=1.0,
                 left_theme="GREEN", right_theme="BLUE"):
        super().__init__(x, y, width, height)
        self.base_bar_width = 100
        self.base_bar_height = 14
        self.base_center_size = 29

        self.left_progress = max(0.0, min(1.0, left_progress))
        self.right_progress = max(0.0, min(1.0, right_progress))

        self.left_theme = left_theme.upper() if isinstance(left_theme, str) else "GREEN"
        self.right_theme = right_theme.upper() if isinstance(right_theme, str) else "BLUE"

        self.center_image = None
        self.center_image_scaled = None

        self.left_bar_surface = None
        self.right_bar_surface = None

        self.surface_needs_rebuild = True
        self.needs_redraw = True

        self.mode = None
        self._auto_themes = True
        self.top_image = None
        self.top_image_scaled = None
        self._center_sprite_name = None

        # Animation state
        self._anim_damage_left = 0
        self._anim_damage_right = 0
        self._anim_start_left = None
        self._anim_start_right = None
        self._anim_anchor_left_progress = None
        self._anim_anchor_right_progress = None
        self._flash_left_until = 0
        self._flash_right_until = 0
        self._flash_duration_ms = 160
        self._anim_duration_ms = 800

        self.left_total = 100
        self.right_total = 100
        self.left_current = int(self.left_total * self.left_progress)
        self.right_current = int(self.right_total * self.right_progress)
        
        # Track end positions of filled bars (in base coordinates)
        self.left_end_x = 0
        self.right_end_x = 0

    # -----------------------
    # Public API
    # -----------------------
    def set_values(self, left_progress: float, right_progress: float):
        left_progress = max(0.0, min(1.0, left_progress))
        right_progress = max(0.0, min(1.0, right_progress))
        if left_progress != self.left_progress or right_progress != self.right_progress:
            self.left_progress = left_progress
            self.right_progress = right_progress
            self.surface_needs_rebuild = True
            self.needs_redraw = True
            self.left_current = int(self.left_total * self.left_progress)
            self.right_current = int(self.right_total * self.right_progress)

    def set_totals(self, left_total: int, right_total: int):
        self.left_total = max(1, int(left_total))
        self.right_total = max(1, int(right_total))
        self.left_current = max(0, min(self.left_current, self.left_total))
        self.right_current = max(0, min(self.right_current, self.right_total))
        self.left_progress = self.left_current / float(self.left_total)
        self.right_progress = self.right_current / float(self.right_total)
        self.surface_needs_rebuild = True
        self.needs_redraw = True

    def set_current_hp(self, left_current: int = None, right_current: int = None):
        if left_current is not None:
            self.left_current = max(0, min(int(left_current), self.left_total))
            self.left_progress = self.left_current / float(self.left_total)
        if right_current is not None:
            self.right_current = max(0, min(int(right_current), self.right_total))
            self.right_progress = self.right_current / float(self.right_total)
        self.surface_needs_rebuild = True
        self.needs_redraw = True

    def add_damage(self, side, amount: int):
        if isinstance(side, int):
            side = 'left' if side == 0 else 'right'
        side = (side or '').lower()
        dmg = int(amount)
        if dmg <= 0:
            return 0
        now = pygame.time.get_ticks()
        if side == 'left':
            pre_progress = self.left_current / float(self.left_total)
            applied = min(dmg, self.left_current)
            self.left_current -= applied
            self.left_progress = self.left_current / float(self.left_total)
            if not self._anim_damage_left:
                self._anim_anchor_left_progress = pre_progress
            self._anim_damage_left += applied
            self._anim_start_left = now
            self._flash_left_until = now + self._flash_duration_ms
        else:
            pre_progress = self.right_current / float(self.right_total)
            applied = min(dmg, self.right_current)
            self.right_current -= applied
            self.right_progress = self.right_current / float(self.right_total)
            if not self._anim_damage_right:
                self._anim_anchor_right_progress = pre_progress
            self._anim_damage_right += applied
            self._anim_start_right = now
            self._flash_right_until = now + self._flash_duration_ms
        self.surface_needs_rebuild = True
        self.needs_redraw = True
        return applied

    def set_themes(self, left_theme: str, right_theme: str):
        lt = left_theme.upper() if isinstance(left_theme, str) else self.left_theme
        rt = right_theme.upper() if isinstance(right_theme, str) else self.right_theme
        if lt != self.left_theme or rt != self.right_theme:
            self.left_theme = lt
            self.right_theme = rt
            self.surface_needs_rebuild = True
            self.needs_redraw = True
            self._auto_themes = False

    def set_center_image(self, surface: pygame.Surface):
        self.center_image = surface
        self.center_image_scaled = None
        self.needs_redraw = True

    def set_top_image(self, surface: pygame.Surface):
        self.top_image = surface
        self.top_image_scaled = None
        self.needs_redraw = True

    def set_mode(self, mode: str, module=None):
        """Set the HPBar mode and optionally a module for adventure mode.
        
        Args:
            mode: One of 'versus', 'adventure', 'pvp_host', 'pvp_client'
            module: Module object for adventure mode to display BattleIcon
        """
        mode = (mode or "").lower()
        if mode == self.mode:
            return
        self.mode = mode
        if mode == "versus":
            self._center_sprite_name = "HPVersus"
            if self._auto_themes:
                self.left_theme = "GREEN"
                self.right_theme = "BLUE"
        elif mode == "adventure":
            # In adventure mode, always load base HPLeft sprite first
            self._center_sprite_name = "HPLeft"
            if module and hasattr(module, 'folder_path'):
                self._module = module
            else:
                self._module = None
            if self._auto_themes:
                self.left_theme = "RED"
                self.right_theme = "BLUE"
        elif mode == "pvp_host":
            self._center_sprite_name = "HPLeft"
            if self._auto_themes:
                self.left_theme = "RED"
                self.right_theme = "BLUE"
        elif mode == "pvp_client":
            self._center_sprite_name = "HPRight"
            if self._auto_themes:
                self.left_theme = "BLUE"
                self.right_theme = "RED"
        else:
            self._center_sprite_name = None

        # Load center sprite
        if self.manager:
            if self._center_sprite_name:
                # Load standard UI sprite (base sprite)
                try:
                    sprite = self.manager.load_sprite_integer_scaling("Battle", self._center_sprite_name, "")
                    if sprite:
                        self.center_image = sprite
                        self.center_image_scaled = None
                except Exception as e:
                    runtime_globals.game_console.log(f"[HPBar] Failed to load center sprite: {e}")
                
                # For adventure mode, also load BattleIcon as overlay
                if mode == "adventure" and hasattr(self, '_module') and self._module:
                    try:
                        battle_icon_path = f"{self._module.folder_path}/BattleIcon.png"
                        icon = image_load(battle_icon_path).convert_alpha()
                        self.top_image = icon
                        self.top_image_scaled = None
                        runtime_globals.game_console.log(f"[HPBar] Loaded module BattleIcon overlay for {self._module.name}")
                    except Exception as e:
                        runtime_globals.game_console.log(f"[HPBar] Failed to load module BattleIcon overlay: {e}")
                        self.top_image = None
                        
        self.surface_needs_rebuild = True
        self.needs_redraw = True

    def on_manager_set(self):
        if self.manager and self._center_sprite_name and not self.center_image:
            try:
                sprite = self.manager.load_sprite_integer_scaling("Battle", self._center_sprite_name, "")
                if sprite:
                    self.center_image = sprite
                    self.center_image_scaled = None
            except Exception as e:
                runtime_globals.game_console.log(f"[HPBar] Failed to load center sprite on manager set: {e}")
        self.surface_needs_rebuild = True
        self.needs_redraw = True

    def get_theme_colors(self, theme_name: str):
        name = (theme_name or "").upper()
        if name == "GREEN":
            return {"shadow": GREEN_DARK, "primary": GREEN, "highlight": GREEN_LIGHT}
        elif name == "BLUE":
            return {"shadow": BLUE_DARK, "primary": BLUE, "highlight": BLUE_LIGHT}
        elif name in ("YELLOW", "YELLOW_BRIGHT", "YELLOWBRIGHT", "YELLOW_BRIGHT"):
            return {"shadow": YELLOW_BRIGHT_DARK, "primary": YELLOW_BRIGHT, "highlight": YELLOW_BRIGHT_LIGHT}
        elif name == "RED":
            return {"shadow": RED_DARK, "primary": RED, "highlight": RED_LIGHT}
        else:
            return {"shadow": GREY, "primary": GREY, "highlight": GREY}

    # -----------------------
    # Build half bar surface
    # -----------------------
    def build_half_bar_surface(self, base_width, base_height, progress, theme_name, direction="right"):
        """Build a bar surface matching ExperienceBar style.
        direction: "right" fills from center->right (player bar), "left" fills from center->left (enemy bar)
        Bars touch the center component directly (full width at center edge) and taper only at outer tips.
        """
        bar_width = int(base_width)
        bar_height = int(base_height)
        surface = pygame.Surface((bar_width, bar_height), pygame.SRCALPHA)
        colors = self.get_theme_colors(theme_name)
        shadow_color = colors["shadow"]
        primary_color = colors["primary"]
        highlight_color = colors["highlight"]

        progress = max(0.0, min(1.0, progress))
        
        # Draw empty bar background using shadow color (dark variation) - extended 2px on all sides
        # Line 1: y=1 (was y=3, moved up 2px), extended 2px on sides
        line1_y = 1
        if direction == "left":
            line1_start_x = 3  # was 5, extended left 2px
            line1_end_x = 100  # stays at 100 (right edge at center)
        else:
            line1_start_x = 0  # stays at 0 (left edge at center)
            line1_end_x = 97   # was 95, extended right 2px
        pygame.draw.rect(surface, shadow_color, (line1_start_x, line1_y, line1_end_x - line1_start_x, 2))
        
        # Lines 2,3,4: y=3,5,7,9 (added y=3, was y=5,7,9, moved up 2px), extended 2px on sides
        if direction == "left":
            line234_start_x = 1   # was 3, extended left 2px
            line234_end_x = 100   # stays at 100 (right edge at center)
        else:
            line234_start_x = 0   # stays at 0 (left edge at center)
            line234_end_x = 99    # was 97, extended right 2px
        for line_y in [3, 5, 7, 9]:
            pygame.draw.rect(surface, shadow_color, (line234_start_x, line_y, line234_end_x - line234_start_x, 2))
        
        # Line 5: y=11, stays same but extended on sides, Line 6: y=13 (new, extended down 2px)
        line5_y = 11
        line5_start_x = line1_start_x
        line5_end_x = line1_end_x
        pygame.draw.rect(surface, shadow_color, (line5_start_x, line5_y, line5_end_x - line5_start_x, 2))
        
        # Line 6: y=13 (new bottom line, extended down 2px)
        line6_y = 13
        pygame.draw.rect(surface, shadow_color, (line5_start_x, line6_y, line5_end_x - line5_start_x, 2))
        
        if progress <= 0.0:
            # Return surface with end_x = 0 (no fill)
            end_x = 0
            return surface, end_x

        # For left bar: x=0 at center (touching middle component), x=100 at outer tip (tapered)
        # For right bar: x=0 at center (touching middle component), x=100 at outer tip (tapered)
        # Line 1: y=3, tapered only at outer tip
        line1_y = 3
        if direction == "left":
            # Left bar: full width at x=95-100 (center edge), tapered at x=0-5 (outer tip)
            line1_start_x = 5  # outer tip (tapered)
            line1_end_x = 100  # center edge (full width)
        else:
            # Right bar: full width at x=0-5 (center edge), tapered at x=95-100 (outer tip)
            line1_start_x = 0   # center edge (full width)
            line1_end_x = 95    # outer tip (tapered)
        line1_width = line1_end_x - line1_start_x
        fill1_width = int(line1_width * progress)
        
        # Lines 2,3,4: y=5,7,9, main body - full width at center edge
        if direction == "left":
            # Left bar: full at x=97-100, full body at x=0-97
            line234_start_x = 3   # outer tip area
            line234_end_x = 100   # center edge (full)
        else:
            # Right bar: full at x=0-3, full body at x=3-97
            line234_start_x = 0   # center edge (full)
            line234_end_x = 97    # outer tip area
        line234_width = line234_end_x - line234_start_x
        fill234_width = int(line234_width * progress)
        
        # Line 5: y=11, bottom shadow - matches line 1 taper
        line5_y = 11
        line5_start_x = line1_start_x
        line5_end_x = line1_end_x
        line5_width = line5_end_x - line5_start_x
        fill5_width = int(line5_width * progress)
        
        # Helper to position based on direction
        def get_x_pos(start_x, width, fill_w):
            if direction == "right":
                return start_x  # fill from center outward to right
            else:
                return start_x + (width - fill_w)  # fill from center outward to left
        
        # Draw Line 1: 2px shadow on edges, primary in middle
        if fill1_width > 0:
            shadow_w = 2
            x_pos = get_x_pos(line1_start_x, line1_width, fill1_width)
            if fill1_width <= shadow_w:
                pygame.draw.rect(surface, shadow_color, (x_pos, line1_y, fill1_width, 2))
            elif fill1_width >= line1_width - shadow_w:
                # Full line
                if direction == "right":
                    pygame.draw.rect(surface, shadow_color, (line1_start_x, line1_y, shadow_w, 2))
                    pygame.draw.rect(surface, primary_color, (line1_start_x + shadow_w, line1_y, line1_width - 2 * shadow_w, 2))
                    pygame.draw.rect(surface, shadow_color, (line1_end_x - shadow_w, line1_y, shadow_w, 2))
                else:
                    pygame.draw.rect(surface, shadow_color, (line1_start_x, line1_y, shadow_w, 2))
                    pygame.draw.rect(surface, primary_color, (line1_start_x + shadow_w, line1_y, line1_width - 2 * shadow_w, 2))
                    pygame.draw.rect(surface, shadow_color, (line1_end_x - shadow_w, line1_y, shadow_w, 2))
            else:
                # Partial fill
                if direction == "right":
                    pygame.draw.rect(surface, shadow_color, (line1_start_x, line1_y, shadow_w, 2))
                    pygame.draw.rect(surface, primary_color, (line1_start_x + shadow_w, line1_y, fill1_width - shadow_w, 2))
                else:
                    pygame.draw.rect(surface, primary_color, (x_pos, line1_y, fill1_width - shadow_w, 2))
                    pygame.draw.rect(surface, shadow_color, (line1_end_x - shadow_w, line1_y, shadow_w, 2))
        
        # Draw Lines 2,3,4: 2px shadow + 2px primary on edges, highlight in middle
        for line_y in [5, 7, 9]:
            if fill234_width > 0:
                shadow_w = 2
                primary_w = 2
                total_border = shadow_w + primary_w
                x_pos = get_x_pos(line234_start_x, line234_width, fill234_width)
                
                if fill234_width <= shadow_w:
                    pygame.draw.rect(surface, shadow_color, (x_pos, line_y, fill234_width, 2))
                elif fill234_width <= total_border:
                    if direction == "right":
                        pygame.draw.rect(surface, shadow_color, (line234_start_x, line_y, shadow_w, 2))
                        pygame.draw.rect(surface, primary_color, (line234_start_x + shadow_w, line_y, fill234_width - shadow_w, 2))
                    else:
                        pygame.draw.rect(surface, primary_color, (x_pos, line_y, fill234_width - shadow_w, 2))
                        pygame.draw.rect(surface, shadow_color, (line234_end_x - shadow_w, line_y, shadow_w, 2))
                elif fill234_width >= line234_width - total_border:
                    # Full line
                    pygame.draw.rect(surface, shadow_color, (line234_start_x, line_y, shadow_w, 2))
                    pygame.draw.rect(surface, primary_color, (line234_start_x + shadow_w, line_y, primary_w, 2))
                    pygame.draw.rect(surface, highlight_color, (line234_start_x + total_border, line_y, line234_width - 2 * total_border, 2))
                    pygame.draw.rect(surface, primary_color, (line234_end_x - total_border, line_y, primary_w, 2))
                    pygame.draw.rect(surface, shadow_color, (line234_end_x - shadow_w, line_y, shadow_w, 2))
                else:
                    # Partial with highlight
                    if direction == "right":
                        pygame.draw.rect(surface, shadow_color, (line234_start_x, line_y, shadow_w, 2))
                        pygame.draw.rect(surface, primary_color, (line234_start_x + shadow_w, line_y, primary_w, 2))
                        pygame.draw.rect(surface, highlight_color, (line234_start_x + total_border, line_y, fill234_width - total_border, 2))
                    else:
                        pygame.draw.rect(surface, highlight_color, (x_pos, line_y, fill234_width - total_border, 2))
                        pygame.draw.rect(surface, primary_color, (line234_end_x - total_border, line_y, primary_w, 2))
                        pygame.draw.rect(surface, shadow_color, (line234_end_x - shadow_w, line_y, shadow_w, 2))
        
        # Draw Line 5: All shadow
        if fill5_width > 0:
            x_pos = get_x_pos(line5_start_x, line5_width, fill5_width)
            pygame.draw.rect(surface, shadow_color, (x_pos, line5_y, fill5_width, 2))
        
        # Calculate and store the end x position of the filled bar
        # This is where the damage overlay should start from
        if direction == "left":
            # Left bar fills from right to left, so end position is at the left edge of fill
            end_x = get_x_pos(line234_start_x, line234_width, fill234_width)
        else:
            # Right bar fills from left to right, so end position is at the right edge of fill
            end_x = line234_start_x + fill234_width
        
        return surface, end_x

    # -----------------------
    # Rendering
    # -----------------------
    def render(self):
        # Reuse a cached render surface to avoid per-frame allocations
        target_size = (self.rect.width, self.rect.height)
        if not hasattr(self, "_render_surface") or self._render_surface is None or self._render_surface.get_size() != target_size:
            self._render_surface = pygame.Surface(target_size, pygame.SRCALPHA)
        surface = self._render_surface
        surface.fill((0, 0, 0, 0))
        scale = self.manager.ui_scale if self.manager else 1

        left_bar_w = int(self.base_bar_width * scale)
        right_bar_w = int(self.base_bar_width * scale)
        bar_h = int(self.base_bar_height * scale)
        center_s = int(self.base_center_size * scale)
        total_w = left_bar_w + center_s + right_bar_w
        left_x = (self.rect.width - total_w) // 2
        bar_y = (self.rect.height - bar_h) // 2
        center_left = left_x + left_bar_w
        right_left = center_left + center_s

        # Rebuild surfaces if needed
        if self.surface_needs_rebuild or self.left_bar_surface is None or self.right_bar_surface is None:
            left_surface, self.left_end_x = self.build_half_bar_surface(self.base_bar_width, self.base_bar_height, self.left_progress, self.left_theme, "left")
            self.left_bar_surface = pygame.transform.scale(left_surface, (left_bar_w, bar_h))
            
            right_surface, self.right_end_x = self.build_half_bar_surface(self.base_bar_width, self.base_bar_height, self.right_progress, self.right_theme, "right")
            self.right_bar_surface = pygame.transform.scale(right_surface, (right_bar_w, bar_h))
            
            self.surface_needs_rebuild = False

        # Flash and damage overlay
        now = pygame.time.get_ticks()
        
        # Check flash state for both sides
        left_flashing = getattr(self, '_flash_left_until', 0) > now
        right_flashing = getattr(self, '_flash_right_until', 0) > now
        
        # Calculate shake offset for flash animation
        # Shake: 2px up -> 2px down -> normal (3 phases over flash duration)
        def get_shake_offset(flash_until):
            if flash_until <= now:
                return 0
            time_remaining = flash_until - now
            flash_progress = 1.0 - (time_remaining / self._flash_duration_ms)  # 0.0 to 1.0
            
            if flash_progress < 0.33:  # First third: 2px up
                return int(-2 * scale)
            elif flash_progress < 0.66:  # Second third: 2px down
                return int(2 * scale)
            else:  # Final third: return to normal
                return 0
        
        left_shake_offset = get_shake_offset(self._flash_left_until)
        right_shake_offset = get_shake_offset(self._flash_right_until)
        
        # Draw left bar (or flash)
        if left_flashing:
            # Draw white bar background with shake offset during flash
            white_bar, _ = self.build_half_bar_surface(self.base_bar_width, self.base_bar_height, 0.0, self.left_theme, "left")
            white_bar_scaled = pygame.transform.scale(white_bar, (left_bar_w, bar_h))
            # Fill the bar shape with white
            for y in range(bar_h):
                for x in range(left_bar_w):
                    pixel = white_bar_scaled.get_at((x, y))
                    if pixel[3] > 0:  # if not transparent
                        white_bar_scaled.set_at((x, y), (255, 255, 255, 255))
            blit_with_cache(surface, white_bar_scaled, (left_x, bar_y + left_shake_offset))
        else:
            # Draw normal bar
            blit_with_cache(surface, self.left_bar_surface, (left_x, bar_y))
        
        # Draw right bar (or flash)
        if right_flashing:
            # Draw white bar background with shake offset during flash
            white_bar, _ = self.build_half_bar_surface(self.base_bar_width, self.base_bar_height, 0.0, self.right_theme, "right")
            white_bar_scaled = pygame.transform.scale(white_bar, (right_bar_w, bar_h))
            # Fill the bar shape with white
            for y in range(bar_h):
                for x in range(right_bar_w):
                    pixel = white_bar_scaled.get_at((x, y))
                    if pixel[3] > 0:  # if not transparent
                        white_bar_scaled.set_at((x, y), (255, 255, 255, 255))
            blit_with_cache(surface, white_bar_scaled, (right_left, bar_y + right_shake_offset))
        else:
            # Draw normal bar
            blit_with_cache(surface, self.right_bar_surface, (right_left, bar_y))

        # Draw damage overlay (only if not flashing)
        for side in ("left", "right"):
            bar_left = left_x if side == "left" else right_left
            bar_width = left_bar_w if side == "left" else right_bar_w
            bar_theme = self.left_theme if side == "left" else self.right_theme
            flash_until = getattr(self, f"_flash_{side}_until", 0)
            anim_damage = getattr(self, f"_anim_damage_{side}", 0)
            anim_start = getattr(self, f"_anim_start_{side}", None)

            # Skip damage animation during flash
            if flash_until > now:
                continue

            # Damage animation - appears at the end of filled bar and shrinks to 0
            if anim_damage > 0 and anim_start is not None:
                elapsed = now - anim_start
                anim_progress = min(1.0, elapsed / self._anim_duration_ms)
                shrink = max(0.0, 1.0 - anim_progress)
                if shrink <= 0.0:
                    setattr(self, f"_anim_damage_{side}", 0)
                    setattr(self, f"_anim_start_{side}", None)
                    setattr(self, f"_anim_anchor_{side}_progress", None)
                else:
                    colors = self.get_theme_colors(bar_theme)
                    hl = colors.get("highlight", (255, 255, 255))
                    total_hp = self.left_total if side == "left" else self.right_total
                    
                    # Use the stored end_x position from build_half_bar_surface (in base coordinates)
                    end_x_base = self.left_end_x if side == "left" else self.right_end_x
                    end_x_scaled = int(end_x_base * scale)
                    
                    # Calculate damage overlay width (damage value * shrink factor)
                    dmg_fraction = anim_damage / float(total_hp)
                    dmg_base_width = int(dmg_fraction * bar_width)
                    dmg_px = int(dmg_base_width * shrink)  # shrinks from full damage width to 0
                    
                    if dmg_px > 0:
                        # Draw damage overlay starting from the end of the filled bar
                        dmg_x = bar_left + end_x_scaled
                        # Clamp to bar boundaries
                        if side == "left":
                            # Left bar: damage extends leftward from end_x
                            dmg_x = max(bar_left, dmg_x - dmg_px)
                            dmg_px = min(dmg_px, end_x_scaled)
                        else:
                            # Right bar: damage extends rightward from end_x
                            dmg_px = min(dmg_px, bar_width - end_x_scaled)
                        
                        if dmg_px > 0:
                            pygame.draw.rect(surface, hl, (dmg_x, bar_y, dmg_px, bar_h))

        # Draw center image (base sprite at 29x29 centered)
        if self.center_image:
            # Always draw base center sprite at its native 29x29 size, centered
            center_img_size = int(29 * scale)  # 29x29 at current scale
            if not self.center_image_scaled or self.center_image_scaled.get_width() != center_img_size:
                try:
                    self.center_image_scaled = pygame.transform.scale(self.center_image, (center_img_size, center_img_size))
                except Exception as e:
                    runtime_globals.game_console.log(f"[HPBar] Failed to scale center image: {e}")
                    self.center_image_scaled = self.center_image
            
            # Center the base sprite within the center area
            img_x = center_left + (center_s - center_img_size) // 2
            img_y = bar_y + (bar_h - center_img_size) // 2
            blit_with_cache(surface, self.center_image_scaled, (img_x, img_y))
            
            # For adventure mode, draw BattleIcon overlay with 2px margin
            if self.mode == "adventure" and self.top_image:
                margin = int(2 * scale)  # 2px margin in scaled space
                overlay_size = center_img_size - (margin * 2)  # Reduce by 2*margin for internal padding
                if overlay_size > 0:
                    if not self.top_image_scaled or self.top_image_scaled.get_width() != overlay_size:
                        try:
                            self.top_image_scaled = pygame.transform.scale(self.top_image, (overlay_size, overlay_size))
                        except Exception as e:
                            runtime_globals.game_console.log(f"[HPBar] Failed to scale overlay image: {e}")
                            self.top_image_scaled = self.top_image
                    
                    # Center the overlay within the base sprite
                    overlay_x = img_x + margin
                    overlay_y = img_y + margin
                    blit_with_cache(surface, self.top_image_scaled, (overlay_x, overlay_y))
        else:
            # Draw placeholder if no center image
            placeholder = pygame.Surface((center_s, center_s), pygame.SRCALPHA)
            placeholder.fill((0, 0, 0, 0))
            pygame.draw.rect(placeholder, (60, 60, 60), placeholder.get_rect(), border_radius=4)
            blit_with_cache(surface, placeholder, (center_left, (self.rect.height - center_s) // 2))

        return surface

    def is_animating(self) -> bool:
        """Is the bar still draining, or flashing the hit that drained it?

        The battle screen waits on this before handing over to the result, so
        the blow that ends a fight is watched rather than glimpsed.
        """
        now = pygame.time.get_ticks()
        draining = ((self._anim_damage_left and self._anim_start_left)
                    or (self._anim_damage_right and self._anim_start_right))
        flashing = (self._flash_left_until > now
                    or self._flash_right_until > now)
        return bool(draining or flashing)

    def update(self):
        """Update per-frame; ensure animated HPBar keeps re-rendering while active."""
        anim_active = self.is_animating()

        # if any animation/flash is active, force redraw every frame
        if anim_active:
            self.needs_redraw = True
