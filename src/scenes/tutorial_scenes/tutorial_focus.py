"""
Tutorial Focus Overlay
Creates a darkened overlay with a focused (highlighted) region.

The focus system works in BASE 240x240 UI coordinates. All positions
should be specified in base coordinates and will be automatically scaled
to match the actual screen resolution.
"""

import pygame
from core import game_globals, runtime_globals


class TutorialFocus:
    """
    Focus overlay that darkens the screen except for a highlighted region.
    Supports fade in/out and multiple focus areas.
    
    All coordinates are in BASE 240x240 UI space. The overlay handles
    scaling and centering automatically based on the current UI_SCALE.
    """
    
    STATE_OFF = 0
    STATE_FADE_IN = 1
    STATE_ACTIVE = 2
    STATE_FADE_OUT = 3
    
    def __init__(self):
        """Initialize the focus overlay."""
        self.state = self.STATE_OFF
        self.focus_rects = []  # List of (x, y, w, h) in base UI coordinates (240x240)
        self.alpha = 0
        self.max_alpha = 180  # Semi-transparent darkness
        self.fade_frames = game_globals.configuration.frame_rate // 4
        self.fade_counter = 0
        
        # Overlay surface (covers entire screen)
        self.overlay_surface = None
        
        # Positioning mode: "global" (full screen) or "ui_manager" (centered UI)
        self.positioning_mode = "global"
        self.ui_manager_ref = None  # Reference to UIManager when in ui_manager mode
        
    def focus_on(self, x: int, y: int, w: int, h: int, padding: int = 4):
        """
        Focus on a specific UI region.
        
        Args:
            x, y, w, h: Region in base UI coordinates (240x240)
            padding: Extra padding around the focus area
        """
        self.focus_rects = [(x - padding, y - padding, w + padding * 2, h + padding * 2)]
        # Always transition to fade-in when focus_on is called, even if currently fading out
        if self.state in [self.STATE_OFF, self.STATE_FADE_OUT]:
            self.state = self.STATE_FADE_IN
            self.fade_counter = 0
        self._rebuild_overlay()
    
    def set_positioning_mode(self, mode: str, ui_manager=None):
        """
        Set the positioning mode for focus overlay.
        
        Args:
            mode: "global" (full screen) or "ui_manager" (centered UI)
            ui_manager: UIManager reference (required for ui_manager mode)
        """
        self.positioning_mode = mode
        self.ui_manager_ref = ui_manager
        # Rebuild overlay if active
        if self.state != self.STATE_OFF:
            self._rebuild_overlay()
        
    def focus_on_multiple(self, rects: list, padding: int = 4):
        """
        Focus on multiple UI regions.
        
        Args:
            rects: List of (x, y, w, h) tuples in base UI coordinates (240x240)
            padding: Extra padding around each focus area
        """
        self.focus_rects = [(x - padding, y - padding, w + padding * 2, h + padding * 2) 
                           for x, y, w, h in rects]
        if self.state == self.STATE_OFF:
            self.state = self.STATE_FADE_IN
            self.fade_counter = 0
        self._rebuild_overlay()
        
    def focus_off(self):
        """Turn off the focus overlay."""
        if self.state in [self.STATE_FADE_IN, self.STATE_ACTIVE]:
            self.state = self.STATE_FADE_OUT
            self.fade_counter = 0
        
    def _rebuild_overlay(self):
        """Rebuild the overlay surface with focus cutouts."""
        # Get positioning parameters based on mode
        if self.positioning_mode == "ui_manager" and self.ui_manager_ref:
            # Use UIManager's centered UI positioning
            ui_scale = self.ui_manager_ref.ui_scale
            screen_width = self.ui_manager_ref.ui_width
            screen_height = self.ui_manager_ref.ui_height
            screen_offset_x = self.ui_manager_ref.ui_offset_x
            screen_offset_y = self.ui_manager_ref.ui_offset_y
        else:
            # Use global full-screen positioning (maingame)
            ui_scale = runtime_globals.UI_SCALE
            screen_width = runtime_globals.SCREEN_WIDTH
            screen_height = runtime_globals.SCREEN_HEIGHT
            screen_offset_x = 0
            screen_offset_y = 0
        
        # Calculate UI area size and offset
        ui_size = int(240 * ui_scale)
        ui_offset_x = screen_offset_x + (screen_width - ui_size) // 2
        ui_offset_y = screen_offset_y + (screen_height - ui_size) // 2
        
        # Create full-screen overlay
        total_width = runtime_globals.SCREEN_WIDTH
        total_height = runtime_globals.SCREEN_HEIGHT
        self.overlay_surface = pygame.Surface((total_width, total_height), pygame.SRCALPHA)
        self.overlay_surface.fill((0, 0, 0, self.max_alpha))
        
        # Cut out focus regions (make them transparent)
        for rect in self.focus_rects:
            x, y, w, h = rect
            # Convert from base 240x240 coordinates to screen coordinates
            screen_rect = pygame.Rect(
                ui_offset_x + int(x * ui_scale),
                ui_offset_y + int(y * ui_scale),
                int(w * ui_scale),
                int(h * ui_scale)
            )
            # Draw transparent rectangle (cut out)
            pygame.draw.rect(self.overlay_surface, (0, 0, 0, 0), screen_rect)
            
            # Draw highlight border around focus area
            border_width = max(2, int(2 * ui_scale))
            pygame.draw.rect(self.overlay_surface, (255, 255, 0, 200),
                           screen_rect, width=border_width)
        # Blitted every frame: RLE skips the cut-out holes' transparent runs.
        from utils.pygame_utils import rle_accelerate
        rle_accelerate(self.overlay_surface)
    
    def update(self):
        """Update focus overlay animation."""
        if self.state == self.STATE_FADE_IN:
            self.fade_counter += 1
            self.alpha = min(self.max_alpha, int(self.max_alpha * self.fade_counter / self.fade_frames))
            if self.fade_counter >= self.fade_frames:
                self.state = self.STATE_ACTIVE
                self.alpha = self.max_alpha
                
        elif self.state == self.STATE_FADE_OUT:
            self.fade_counter += 1
            self.alpha = max(0, int(self.max_alpha * (1 - self.fade_counter / self.fade_frames)))
            if self.fade_counter >= self.fade_frames:
                self.state = self.STATE_OFF
                self.alpha = 0
                self.focus_rects = []
    
    def draw(self, surface: pygame.Surface):
        """Draw the focus overlay."""
        if self.state == self.STATE_OFF or self.overlay_surface is None:
            return
        
        if self.alpha >= self.max_alpha:
            # Steady: the overlay as built (copying and re-fading a
            # full-screen surface every frame cost the Pi Zero 2W dearly).
            alpha_surface = self.overlay_surface
        else:
            # Create alpha-adjusted surface
            alpha_surface = self.overlay_surface.copy()
            # Adjust alpha based on current fade state
            alpha_ratio = self.alpha / self.max_alpha
            alpha_surface.fill((255, 255, 255, int(alpha_ratio * 255)),
                              special_flags=pygame.BLEND_RGBA_MULT)

        # Draw at (0, 0) since overlay is now full-screen
        surface.blit(alpha_surface, (0, 0))
    
    def is_active(self) -> bool:
        """Check if focus overlay is currently showing."""
        return self.state != self.STATE_OFF
    
    def is_fully_visible(self) -> bool:
        """Check if focus overlay has completed fading in."""
        return self.state == self.STATE_ACTIVE
    
    def is_click_inside_focus(self, screen_x: int, screen_y: int) -> bool:
        """
        Check if a screen coordinate click is inside any focused region.
        
        Args:
            screen_x, screen_y: Click position in screen coordinates
            
        Returns:
            True if click is inside a focused region, False otherwise
        """
        if self.state == self.STATE_OFF or not self.focus_rects:
            return True  # No focus active, allow all clicks
        
        # Get positioning parameters based on mode
        if self.positioning_mode == "ui_manager" and self.ui_manager_ref:
            ui_scale = self.ui_manager_ref.ui_scale
            screen_width = self.ui_manager_ref.ui_width
            screen_height = self.ui_manager_ref.ui_height
            screen_offset_x = self.ui_manager_ref.ui_offset_x
            screen_offset_y = self.ui_manager_ref.ui_offset_y
        else:
            ui_scale = runtime_globals.UI_SCALE
            screen_width = runtime_globals.SCREEN_WIDTH
            screen_height = runtime_globals.SCREEN_HEIGHT
            screen_offset_x = 0
            screen_offset_y = 0
        
        # Calculate UI area offset
        ui_size = int(240 * ui_scale)
        ui_offset_x = screen_offset_x + (screen_width - ui_size) // 2
        ui_offset_y = screen_offset_y + (screen_height - ui_size) // 2
        
        # Check if click is inside any focus rect
        for rect in self.focus_rects:
            x, y, w, h = rect
            # Convert from base 240x240 coordinates to screen coordinates
            screen_rect = pygame.Rect(
                ui_offset_x + int(x * ui_scale),
                ui_offset_y + int(y * ui_scale),
                int(w * ui_scale),
                int(h * ui_scale)
            )
            if screen_rect.collidepoint(screen_x, screen_y):
                return True
        
        return False
