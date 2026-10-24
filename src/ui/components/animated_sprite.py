"""
Animated Sprite UI Component
Full-screen animated sprite component with background colors and blurred overlays.
"""

import pygame
import core.constants as constants
import ui.ui_constants as ui_constants
from ui.components.component import UIComponent
from core import runtime_globals
from utils.pygame_utils import blit_with_cache


class AnimatedSprite(UIComponent):
    """
    A full-screen animated sprite component that can display one or more sprites
    with corresponding background colors, blur effects, and frame animation.
    Includes predefined combat animations.
    """
    
    def __init__(self, ui_manager):
        # Always full-screen, no position needed
        super().__init__(0, 0, runtime_globals.SCREEN_WIDTH, runtime_globals.SCREEN_HEIGHT)
        self.ui_manager = ui_manager
        
        # Mark as dynamic since this is an animated component
        self.is_dynamic = True
        
        # Animation data
        self.sprites = []  # List of pygame.Surface sprites
        self.background_colors = []  # List of background colors (tuples)
        self.frame_rate = 3  # Default 3 Hz frequency
        self.animation_duration = 0  # Duration in seconds
        
        # Animation state
        self.is_playing = False
        self.start_time = 0
        self.current_frame = 0
        self.frame_counter = 0
        self._frame_interval = 1  # Precomputed frame interval in ticks
        
        # Special modes
        self.manual_mode = False  # For countdown mode where frames are controlled manually
        
        # Caching
        self._surface_cache = {}  # Cache for rendered surfaces
        self._overlay_cache = {}  # Cache for blurred overlays
        self._last_screen_size = (0, 0)
        # Predefined colors (use shared UI constants)
        # NOTE: we store them as attributes for backwards compatibility with
        # existing code that accessed self.COMBAT_BLUE/self.BLACK/self.YELLOW
        # while the canonical values live in `game.components.ui.ui_constants`.
        self.COMBAT_BLUE = ui_constants.COMBAT_BLUE
        # Use the animation-specific black and yellow to avoid modifying
        # general-purpose UI color names elsewhere in the project.
        self.BLACK = ui_constants.ANIM_BLACK
        self.YELLOW = ui_constants.COMBAT_YELLOW
        
    def set_animation_data(self, sprites, background_colors=None, frame_rate=3):
        """
        Set the sprites and background colors for animation.
        
        Args:
            sprites: List of pygame.Surface sprites to animate
            background_colors: List of background colors (tuples). If None, uses black.
            frame_rate: Animation frame rate in Hz (default 3)
        """
        self.sprites = sprites if isinstance(sprites, list) else [sprites]
        
        if background_colors is None:
            self.background_colors = [(0, 0, 0)] * len(self.sprites)
        elif isinstance(background_colors, list):
            self.background_colors = background_colors
        else:
            self.background_colors = [background_colors] * len(self.sprites)
            
        # Ensure we have the same number of colors as sprites
        while len(self.background_colors) < len(self.sprites):
            self.background_colors.append((0, 0, 0))
            
        self.frame_rate = frame_rate
        # Precompute frame interval to avoid per-frame division
        try:
            self._frame_interval = max(1, int(constants.FRAME_RATE / max(1, frame_rate)))
        except Exception:
            self._frame_interval = 1
        
        # Clear caches when animation data changes
        self._surface_cache.clear()
        self._overlay_cache.clear()
        
    def play(self, duration_seconds):
        """
        Start playing the animation for the specified duration.
        
        Args:
            duration_seconds: How long to play the animation in seconds
        """
        if not self.sprites:
            return
            
        self.is_playing = True
        self.manual_mode = False  # Disable manual mode for timed animations
        self.animation_duration = duration_seconds
        self.start_time = pygame.time.get_ticks()
        self.current_frame = 0
        self.frame_counter = 0
        
    def stop(self):
        """Stop the animation."""
        self.is_playing = False
        self.manual_mode = False
        self.current_frame = 0
        self.frame_counter = 0
        
    def is_animation_playing(self):
        """Check if the animation is currently playing."""
        return self.is_playing
        
    def update(self):
        """Update animation state."""
        if not self.is_playing or not self.sprites:
            return
        
        # Skip automatic updates in manual mode
        if self.manual_mode:
            return
            
        current_time = pygame.time.get_ticks()
        elapsed_time = (current_time - self.start_time) / 1000.0
        
        # Check if animation duration has elapsed
        if elapsed_time >= self.animation_duration:
            self.stop()
            return
            
        # Calculate frame timing
        if len(self.sprites) > 1:
            # Use precomputed frame interval
            self.frame_counter += 1
            if self.frame_counter >= self._frame_interval:
                self.frame_counter = 0
                nxt = self.current_frame + 1
                if nxt >= len(self.sprites):
                    nxt = 0
                self.current_frame = nxt
        else:
            self.current_frame = 0
            
    def _create_blurred_overlay(self, sprite, cache_key):
        """Create a blurred, semi-transparent overlay that fills the screen."""
        if not sprite:
            return None
            
        # Check if screen size changed
        current_screen_size = (runtime_globals.SCREEN_WIDTH, runtime_globals.SCREEN_HEIGHT)
        if current_screen_size != self._last_screen_size:
            self._overlay_cache.clear()
            self._last_screen_size = current_screen_size
            
        # Check cache
        overlay = self._overlay_cache.get(cache_key)
        if overlay is not None:
            return overlay
            
        try:
            # Only create overlay if UI scale >= 2
            ui_scale = getattr(self.ui_manager, 'ui_scale', 1)
            if ui_scale < 2:
                return None
                
            sw, sh = sprite.get_width(), sprite.get_height()
            if sw <= 0 or sh <= 0:
                return None
                
            # Scale sprite to fill screen proportionally
            scale = max(runtime_globals.SCREEN_WIDTH / sw, runtime_globals.SCREEN_HEIGHT / sh)
            new_size = (int(sw * scale), int(sh * scale))
            overlay = pygame.transform.smoothscale(sprite, new_size)
            
            # Apply blur effect by downscaling and upscaling
            # Fewer iterations to reduce processing cost
            blur_iterations = 2
            blur_factor = 0.2  # Scale down to 20% for blur effect
            for _ in range(blur_iterations):
                blur_w = max(1, int(overlay.get_width() * blur_factor))
                blur_h = max(1, int(overlay.get_height() * blur_factor))
                overlay = pygame.transform.smoothscale(overlay, (blur_w, blur_h))
                overlay = pygame.transform.smoothscale(overlay, new_size)
            
            # Set 50% opacity
            overlay = overlay.convert_alpha()
            overlay.set_alpha(128)
            
            # Cache the overlay
            self._overlay_cache[cache_key] = overlay
            return overlay
            
        except Exception as e:
            print(f"[AnimatedSprite] Error creating overlay for {cache_key}: {e}")
            return None
    
    def _render_frame(self, frame_index):
        """Render a single frame with background and overlay."""
        if frame_index >= len(self.sprites) or frame_index >= len(self.background_colors):
            return None
            
        sprite = self.sprites[frame_index]
        bg_color = self.background_colors[frame_index]
        
        # Create cache key
        cache_key = (frame_index, bg_color, runtime_globals.SCREEN_WIDTH, runtime_globals.SCREEN_HEIGHT)
        
        # Check cache
        surface = self._surface_cache.get(cache_key)
        if surface is not None:
            return surface
            
        # Each cached frame needs its own surface: rendering every frame into a
        # shared target makes all cache keys alias whatever rendered last, which
        # froze two-frame animations (battle/impact flashes) on a single frame.
        # Rendered once per key, so there is no per-frame allocation cost.
        target_size = (runtime_globals.SCREEN_WIDTH, runtime_globals.SCREEN_HEIGHT)
        surface = pygame.Surface(target_size)
        
        # Fill with background color
        surface.fill(bg_color)
        
        # Draw blurred overlay if applicable
        overlay = self._create_blurred_overlay(sprite, f"overlay_{frame_index}")
        if overlay:
            overlay_rect = overlay.get_rect(center=(runtime_globals.SCREEN_WIDTH // 2, runtime_globals.SCREEN_HEIGHT // 2))
            from utils.pygame_utils import blit_with_cache
            blit_with_cache(surface, overlay, overlay_rect.topleft)
        
        # Draw centered sprite
        if sprite:
            sprite_rect = sprite.get_rect(center=(runtime_globals.SCREEN_WIDTH // 2, runtime_globals.SCREEN_HEIGHT // 2))
            from utils.pygame_utils import blit_with_cache
            blit_with_cache(surface, sprite, sprite_rect.topleft)
        
        self._surface_cache[cache_key] = surface
        return surface
    
    def draw(self, surface, ui_local=False):
        """Draw the animated sprite component.
        
        Args:
            surface: Target surface to draw on
            ui_local: If True, use UI-local coordinates (ignored for full-screen sprite)
        """
        if not self.is_playing or not self.sprites:
            return
            
        # Render current frame (always at 0,0 for full-screen sprite)
        frame_surface = self._render_frame(self.current_frame)
        if frame_surface:
            blit_with_cache(surface, frame_surface, (0, 0))
    
    def clear_cache(self):
        """Clear all cached surfaces."""
        self._surface_cache.clear()
        self._overlay_cache.clear()
    
    def set_single_sprite(self, sprite, background_color=(0, 0, 0), duration_seconds=1.0):
        """
        Convenience method to set up a single sprite animation.
        
        Args:
            sprite: Single pygame.Surface sprite
            background_color: Background color tuple (default black)
            duration_seconds: How long to display the sprite
        """
        self.set_animation_data([sprite], [background_color])
        self.play(duration_seconds)
    
    def set_flashing_sprites(self, sprite1, sprite2, bg_color1=(0, 0, 0), bg_color2=(255, 255, 255), 
                           duration_seconds=1.0, flash_rate=3):
        """
        Convenience method to set up a flashing animation between two sprites.
        
        Args:
            sprite1: First pygame.Surface sprite
            sprite2: Second pygame.Surface sprite  
            bg_color1: Background color for first sprite
            bg_color2: Background color for second sprite
            duration_seconds: How long to flash
            flash_rate: Flash frequency in Hz
        """
        self.set_animation_data([sprite1, sprite2], [bg_color1, bg_color2], flash_rate)
        self.play(duration_seconds)
    
    def _load_combat_sprite(self, name):
        """Load a combat sprite using the UI manager."""
        return self.ui_manager.load_sprite_integer_scaling(name=name, prefix="Combat")
    
    def _load_combat_sprites(self, *names):
        """Load multiple combat sprites."""
        return [self._load_combat_sprite(name) for name in names]

    # The Digivice iC minigames' own screens (utilities/IC/ui_screens.py):
    # the LCD's 32 x 32 dots in the middle of the screen, where the minigame
    # draws its LCD, on their own paper -- which also fills what is left of
    # a screen they do not cover.
    def _play_screens(self, names, duration_seconds, frame_rate=2):
        sprites = self._load_combat_sprites(*names)
        paper = tuple(sprites[0].get_at((0, 0)))[:3] if sprites and sprites[0] else (0, 0, 0)
        self.set_animation_data(sprites, [paper] * len(sprites), frame_rate=frame_rate)
        self.play(duration_seconds)

    def play_ic20_ready(self, duration_seconds=1.0):
        """The iC 20X's READY (Combat_IC20Ready)."""
        self._play_screens(["IC20Ready"], duration_seconds)

    def play_ic20_start(self, duration_seconds=1.0):
        """The iC 20X's START (Combat_IC20Start)."""
        self._play_screens(["IC20Start"], duration_seconds)

    def play_ic20_clear(self, duration_seconds=1.0):
        """The iC 20X's CLEAR!, a stage of its minigame cleared (Combat_IC20Clear)."""
        self._play_screens(["IC20Clear"], duration_seconds)

    def play_shuffle_title(self, duration_seconds=1.0):
        """The iC 10X Shuffle's SHUFFLE, its two frames twice a second."""
        self._play_screens(["ShuffleTitle1", "ShuffleTitle2"], duration_seconds)

    def play_shuffle_select(self, duration_seconds=1.0):
        """The iC 10X Shuffle's SELECT!, its two frames twice a second."""
        self._play_screens(["ShuffleSelect1", "ShuffleSelect2"], duration_seconds)
    
    # Predefined combat animations
    def play_battle(self, duration_seconds=1.0):
        """Play battle animation (Combat_Battle1/Battle2 with combat blue background)."""
        sprites = self._load_combat_sprites("Battle1", "Battle2")
        backgrounds = [self.COMBAT_BLUE, self.COMBAT_BLUE]
        self.set_animation_data(sprites, backgrounds, frame_rate=2)  # 5 FPS for faster alternation
        self.play(duration_seconds)
    
    def play_bad(self, duration_seconds=1.0):
        """Play bad result animation."""
        sprite = self._load_combat_sprite("Bad")
        self.set_single_sprite(sprite, self.COMBAT_BLUE, duration_seconds)
    
    def play_good(self, duration_seconds=1.0):
        """Play good result animation."""
        sprite = self._load_combat_sprite("Good")
        self.set_single_sprite(sprite, self.COMBAT_BLUE, duration_seconds)
    
    def play_great(self, duration_seconds=1.0):
        """Play great result animation."""
        sprite = self._load_combat_sprite("Great")
        self.set_single_sprite(sprite, self.COMBAT_BLUE, duration_seconds)
    
    def play_excellent(self, duration_seconds=1.0):
        """Play excellent result animation."""
        sprite = self._load_combat_sprite("Excellent")
        self.set_single_sprite(sprite, self.COMBAT_BLUE, duration_seconds)
    
    def play_lose(self, duration_seconds=1.0):
        """Play lose animation (Combat_Lose1/Lose2 with combat blue background)."""
        sprites = self._load_combat_sprites("Lose1", "Lose2")
        backgrounds = [self.COMBAT_BLUE, self.COMBAT_BLUE]
        self.set_animation_data(sprites, backgrounds, frame_rate=2)
        self.play(duration_seconds)
    
    def play_win(self, duration_seconds=1.0):
        """Play win animation (Combat_Win1/Win2 with combat blue background)."""
        sprites = self._load_combat_sprites("Win1", "Win2")
        backgrounds = [self.COMBAT_BLUE, self.COMBAT_BLUE]
        self.set_animation_data(sprites, backgrounds, frame_rate=2)
        self.play(duration_seconds)
    
    def play_clear(self, duration_seconds=1.0):
        """Play clear animation (Combat_Clear1/Clear2 with combat blue background)."""
        sprites = self._load_combat_sprites("Clear1", "Clear2")
        backgrounds = [self.COMBAT_BLUE, self.COMBAT_BLUE]
        self.set_animation_data(sprites, backgrounds, frame_rate=2)
        self.play(duration_seconds)
    
    def play_warning(self, duration_seconds=1.0):
        """Play warning animation (Combat_Warning1/Warning2 with combat blue background)."""
        sprites = self._load_combat_sprites("Warning1", "Warning2")
        backgrounds = [self.COMBAT_BLUE, self.COMBAT_BLUE]
        self.set_animation_data(sprites, backgrounds, frame_rate=2)
        self.play(duration_seconds)
    
    def play_impact(self, duration_seconds=1.0):
        """Play impact animation (Combat_Impact1/Impact2 with black/yellow background)."""
        sprites = self._load_combat_sprites("Impact1", "Impact2")
        backgrounds = [self.BLACK, self.YELLOW]
        self.set_animation_data(sprites, backgrounds, frame_rate=3)
        self.play(duration_seconds)
    
    def play_megahit(self, duration_seconds=1.0):
        """Play megahit animation."""
        sprite = self._load_combat_sprite("MegaHit")
        self.set_single_sprite(sprite, self.COMBAT_BLUE, duration_seconds)
    
    def play_ready(self, duration_seconds=1.0):
        """Play ready animation."""
        sprite = self._load_combat_sprite("Ready")
        self.set_single_sprite(sprite, self.COMBAT_BLUE, duration_seconds)
    
    def play_versus_result(self, duration_seconds=1.0):
        """Play versus result animation (VersusResult1/VersusResult2 with combat blue background)."""
        sprites = self._load_combat_sprites("VersusResult1", "VersusResult2")
        backgrounds = [self.COMBAT_BLUE, self.COMBAT_BLUE]
        self.set_animation_data(sprites, backgrounds, frame_rate=2)
        self.play(duration_seconds)
    
    def play_battle_level(self, duration_seconds=1.0):
        """Play battle level screen.
        
        Args:
            duration_seconds: How long to display the level screen
        """
        # Load BattleLevel sprite from assets/ui with Combat prefix
        sprite = self.ui_manager.load_sprite_integer_scaling(prefix="Combat", name="Level")
        self.set_single_sprite(sprite, self.COMBAT_BLUE, duration_seconds)

    def play_retire(self, duration_seconds=1.0):
        """Play retire animation (Combat_Retire with combat blue background)."""
        sprite = self._load_combat_sprite("Retire")
        self.set_single_sprite(sprite, self.COMBAT_BLUE, duration_seconds)
    
    # Special countdown mode
    def setup_countdown_ready(self):
        """Set up countdown ready mode (ready0, ready1, ready2, ready3)."""
        sprites = self._load_combat_sprites("Ready0", "Ready1", "Ready2", "Ready3")
        backgrounds = [self.COMBAT_BLUE] * 4
        self.set_animation_data(sprites, backgrounds)
        self.manual_mode = True
        self.is_playing = True
        self.current_frame = 0
    
    def setup_countdown_count(self):
        """Set up countdown count mode (count1, count2, count3, count4)."""
        sprites = self._load_combat_sprites("Count1", "Count2", "Count3", "Count4")
        backgrounds = [self.COMBAT_BLUE] * 4
        self.set_animation_data(sprites, backgrounds)
        self.manual_mode = True
        self.is_playing = True
        self.current_frame = 0
    
    def setup_countdown_ready_bw(self):
        """Set up countdown ready mode for BW (black and white) sprites - Combat_ReadyBW_1."""
        sprites = self._load_combat_sprites("ReadyBW")
        backgrounds = [self.COMBAT_BLUE]
        self.set_animation_data(sprites, backgrounds)
        self.manual_mode = True
        self.is_playing = True
        self.current_frame = 0
    
    def setup_countdown_count_bw(self):
        """Set up countdown count mode for BW (black and white) sprites - Combat_CountBW_1."""
        sprites = self._load_combat_sprites("CountBW")
        backgrounds = [self.COMBAT_BLUE]
        self.set_animation_data(sprites, backgrounds)
        self.manual_mode = True
        self.is_playing = True
        self.current_frame = 0
    
    def setup_countdown_classic(self):
        """Set up countdown classic mode - Combat_CountClassic_1."""
        sprites = self._load_combat_sprites("CountClassic")
        backgrounds = [self.COMBAT_BLUE]
        self.set_animation_data(sprites, backgrounds)
        self.manual_mode = True
        self.is_playing = True
        self.current_frame = 0
    
    def next_countdown_frame(self):
        """Advance to the next frame in countdown mode."""
        if self.manual_mode and self.sprites:
            self.current_frame = (self.current_frame + 1) % len(self.sprites)
            # Clear surface cache to force redraw
            self._surface_cache.clear()
    
    def previous_countdown_frame(self):
        """Go back to the previous frame in countdown mode."""
        if self.manual_mode and self.sprites:
            self.current_frame = (self.current_frame - 1) % len(self.sprites)
            # Clear surface cache to force redraw
            self._surface_cache.clear()
    
    def set_countdown_frame(self, frame_index):
        """Set specific frame in countdown mode."""
        if self.manual_mode and self.sprites and 0 <= frame_index < len(self.sprites):
            self.current_frame = frame_index
            # Clear surface cache to force redraw
            self._surface_cache.clear()
    
    def get_countdown_frame(self):
        """Get current frame index in countdown mode."""
        return self.current_frame if self.manual_mode else 0