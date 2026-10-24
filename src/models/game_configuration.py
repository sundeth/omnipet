import platform
import os

import pygame


class GameConfiguration:
    """Configuration settings for the game.
    
    This class centralizes all configuration settings that were previously
    scattered across constants.py, runtime_globals.py, and game_globals.py.
    Access via game_globals.configuration.
    """

    # Default input mappings (transferred from JSON config files)
    DEFAULT_KEYBOARD_MAP = {
        "LEFT": "K_LEFT",
        "RIGHT": "K_RIGHT",
        "UP": "K_UP",
        "DOWN": "K_DOWN",
        "A": "K_RETURN",
        "START": "K_BACKSPACE",
        "X": "K_LCTRL",
        "Y": "K_SPACE",
        "R": "K_LSHIFT",
        "B": "K_ESCAPE",
        "SELECT": "K_TAB",
        # F-keys are for debug, not remappable
        "F1": "K_F1", "F2": "K_F2", "F3": "K_F3", "F4": "K_F4",
        "F5": "K_F5", "F6": "K_F6", "F7": "K_F7", "F8": "K_F8",
        "F9": "K_F9", "F10": "K_F10", "F11": "K_F11", "F12": "K_F12"
    }
    
    DEFAULT_GPIO_MAP = {
        16: "LEFT",
        13: "RIGHT",
        5: "UP",
        6: "DOWN",
        21: "A",
        20: "B",
        15: "X",
        12: "Y",
        23: "L",
        14: "R",
        26: "START",
        19: "SELECT"
    }
    
    # Valid GPIO pins for input detection
    VALID_GPIO_PINS = [16, 13, 5, 6, 21, 20, 15, 12, 23, 14, 26, 19]
    
    DEFAULT_JOYSTICK_MAP = {
        0: "A",
        1: "B",
        2: "Y",
        3: "X",
        4: "SELECT",
        6: "START",
        9: "L",
        10: "R",
        11: "UP",
        12: "DOWN",
        13: "LEFT",
        14: "RIGHT",
        15: "UP"
    }

    def __init__(self):
        # System detection
        self.current_system = self._detect_system()
        
        # Display settings
        # screen_width/height = the internal *render resolution* (the canvas the
        # game draws to; drives UI scaling).  window_width/height = the size of
        # the OS window the canvas is scaled into.  They are decoupled: in
        # windowed mode the player can pick a window size different from the
        # render resolution, and the canvas is scaled to fit.
        self.screen_width = 240
        self.screen_height = 240
        self.window_width = 240
        self.window_height = 240
        self.fullscreen = False
        self.base_resolution_width = 240
        self.base_resolution_height = 240
        self.resolution_multiplyer = 1.0
        self.resolution_multiplyer_max = 1.0
        
        # Performance settings
        self.frame_rate = 30
        self.max_pets = 4
        
        # Debug settings
        self.show_fps = False
        self.debug_mode = False
        self.debug_blit_logging = False
        self.debug_file_logging = False
        self.debug_battle_logging = False
        
        # Audio settings
        self.sound_volume = 3  # 0-10
        
        # Screen behavior
        self.screen_timeout = 60  # seconds, 0 = disabled
        self.rotated = False
        
        # Sleep schedule
        self.wake_time = None
        self.sleep_time = None
        
        # Graphics settings
        self.sprite_resolution_preference = 0  # 0=Default, 1=Color, 2=HD
        self.enable_old_sprites = False  # True = use old sprites with fallback, False = use modern priority
        
        # Input mappings (copy defaults, can be overridden by user)
        self.keyboard_map = dict(self.DEFAULT_KEYBOARD_MAP)
        self.gpio_map = dict(self.DEFAULT_GPIO_MAP)
        self.joystick_map = dict(self.DEFAULT_JOYSTICK_MAP)
        
        # Track which input type was configured (None = use all defaults)
        self.configured_input_type = None  # "keyboard", "gpio", "joystick", or None
        
        # Apply system-specific defaults
        self.setup_for_system(self.current_system)
    
    def _detect_system(self) -> str:
        """Auto-detect the current system type."""
        system = platform.system()
        
        if system == "Linux":
            if os.path.exists("/usr/bin/batocera-info"):
                return "Batocera"
            elif os.path.exists("/boot/config.txt"):
                return "Linux"  # Raspberry Pi or similar
            return "Linux"
        elif system == "Windows":
            return "PC"
        elif system == "Darwin":
            return "PC"
        else:
            return "Other"

    def setup_for_system(self, current_system: str = "PC"):
        """Adjust configuration based on the current system."""
        self.current_system = current_system
        
        if self.current_system == "Mobile":
            self.fullscreen = True
            self.frame_rate = 30
            self.screen_width = 240
            self.screen_height = 240
            self.max_pets = 4
        elif self.current_system == "PC":
            self.fullscreen = False
            self.frame_rate = 60
            self.screen_width = 640
            self.screen_height = 640
            self.max_pets = 6
        elif self.current_system == "Linux":
            self.fullscreen = True
            self.frame_rate = 30
            self.screen_width = 240
            self.screen_height = 240
            self.max_pets = 4
        elif self.current_system == "Raspberry":
            self.fullscreen = True
            self.frame_rate = 30
            self.screen_width = 240
            self.screen_height = 240
            self.max_pets = 4
        elif self.current_system == "Batocera":
            self.fullscreen = True
            self.frame_rate = 30
            self.screen_width = 320
            self.screen_height = 240
            self.max_pets = 4
        else:
            self.fullscreen = True
            self.frame_rate = 30
            self.screen_width = 240
            self.screen_height = 240
            self.max_pets = 4

        self.adjust_proportions()

        self.base_resolution_width = self.screen_width
        self.base_resolution_height = self.screen_height

        # Default the OS window to match the render resolution (1:1) until the
        # player overrides it via the Window Size setting.
        self.window_width = self.screen_width
        self.window_height = self.screen_height
    
    def adjust_proportions(self):
        """
        Adjust screen_width and screen_height to match real screen proportions.
        Only applies if fullscreen is True. Finds the closest resolution >= base values
        that matches the aspect ratio of the actual display.
        
        Example:
            Real screen: 2142x960 (aspect ~2.23:1)
            Base: 240x240
            Result: 536x240 (maintains aspect ratio, height >= 240)
        """
        if not self.fullscreen:
            return

        # Video system may not be initialized yet at import time (e.g. on Pi Zero 2W)
        if not pygame.display.get_init():
            return

        # Get actual screen resolution
        display_info = pygame.display.Info()
        real_width = display_info.current_w
        real_height = display_info.current_h
        
        # Skip if we can't get valid screen info
        if real_width <= 0 or real_height <= 0:
            return
        
        # Store the base values (minimum acceptable resolution)
        base_width = self.screen_width
        base_height = self.screen_height
        
        # Calculate aspect ratio of real screen
        aspect_ratio = real_width / real_height
        
        # Calculate new dimensions that match aspect ratio and meet minimum requirements
        if aspect_ratio > 1:
            # Landscape: wider than tall
            # Start with base height, calculate width
            new_height = base_height
            new_width = int(new_height * aspect_ratio)
            
            # Ensure width meets minimum
            if new_width < base_width:
                new_width = base_width
                new_height = int(new_width / aspect_ratio)
        elif aspect_ratio < 1:
            # Portrait: taller than wide
            # Start with base width, calculate height
            new_width = base_width
            new_height = int(new_width / aspect_ratio)
            
            # Ensure height meets minimum
            if new_height < base_height:
                new_height = base_height
                new_width = int(new_height * aspect_ratio)
        else:
            # Square: keep base values
            new_width = base_width
            new_height = base_height
        
        # Update configuration
        self.screen_width = new_width
        self.screen_height = new_height

    def compute_base_resolution(self, window_w, window_h):
        """Return the 1x internal render resolution for a given output window.

        Keeps the window's aspect ratio with neither side below 240 so a
        non-square window (e.g. 600x500) is not stretched from a square
        240x240 canvas — instead it picks the closest proportional values to
        240x240 that are not smaller than 240 on either axis.
        """
        BASE = 240
        if not window_w or not window_h or window_w <= 0 or window_h <= 0:
            return BASE, BASE
        aspect = window_w / window_h
        if aspect > 1:
            # Landscape — fix height at the base, derive width.
            h = BASE
            w = int(round(h * aspect))
            if w < BASE:
                w = BASE
                h = int(round(w / aspect))
        elif aspect < 1:
            # Portrait — fix width at the base, derive height.
            w = BASE
            h = int(round(w / aspect))
            if h < BASE:
                h = BASE
                w = int(round(h * aspect))
        else:
            w = h = BASE
        return w, h

    def recompute_internal_resolution(self):
        """Recompute the internal render resolution (screen_width/height) from
        the current window size and the 1x-4x render multiplier.

        The 1x base is proportional to the window (see compute_base_resolution)
        and the multiplier scales it up.  Stored back into base_resolution_*
        and screen_* so the rest of the engine keeps using the same fields.
        """
        bw, bh = self.compute_base_resolution(self.window_width, self.window_height)
        self.base_resolution_width = bw
        self.base_resolution_height = bh
        mult = max(1, min(4, int(round(self.resolution_multiplyer or 1))))
        self.resolution_multiplyer = mult
        self.screen_width = bw * mult
        self.screen_height = bh * mult

    def to_dict(self) -> dict:
        """Convert configuration to dictionary for saving."""
        return {
            "current_system": self.current_system,
            "screen_width": self.screen_width,
            "screen_height": self.screen_height,
            "window_width": self.window_width,
            "window_height": self.window_height,
            "fullscreen": self.fullscreen,
            "frame_rate": self.frame_rate,
            "max_pets": self.max_pets,
            "show_fps": self.show_fps,
            "debug_mode": self.debug_mode,
            "debug_blit_logging": self.debug_blit_logging,
            "debug_file_logging": self.debug_file_logging,
            "debug_battle_logging": self.debug_battle_logging,
            "sound_volume": self.sound_volume,
            "screen_timeout": self.screen_timeout,
            "rotated": self.rotated,
            "wake_time": self.wake_time,
            "sleep_time": self.sleep_time,
            "sprite_resolution_preference": self.sprite_resolution_preference,
            "enable_old_sprites": self.enable_old_sprites,
            "keyboard_map": self.keyboard_map,
            "gpio_map": self.gpio_map,
            "joystick_map": self.joystick_map,
            "configured_input_type": self.configured_input_type,
            "base_resolution_width": self.base_resolution_width,
            "base_resolution_height": self.base_resolution_height,
            "resolution_multiplyer": self.resolution_multiplyer,
            "resolution_multiplyer_max": self.resolution_multiplyer_max,
        }
    
    def from_dict(self, data: dict):
        """Load configuration from dictionary."""
        if not data:
            return
        
        # Only load values that exist in the saved data
        for key, value in data.items():
            if hasattr(self, key):
                # Special handling for maps - need to convert string keys back to int for gpio/joystick
                if key == "gpio_map" and isinstance(value, dict):
                    self.gpio_map = {int(k): v for k, v in value.items()}
                elif key == "joystick_map" and isinstance(value, dict):
                    self.joystick_map = {int(k): v for k, v in value.items()}
                else:
                    setattr(self, key, value)

        # Backfill the window size for configs saved before the setting
        # existed, or if it came through as an invalid value — default it to
        # the render resolution (1:1).
        if "window_width" not in data or not getattr(self, "window_width", 0):
            self.window_width = self.screen_width
        if "window_height" not in data or not getattr(self, "window_height", 0):
            self.window_height = self.screen_height

    def get_keyboard_pygame_map(self) -> dict:
        """Get keyboard map with pygame key constants as keys.
        Returns: {pygame_key_constant: action_name}
        """
        import pygame
        key_map = {}
        for action, key_str in self.keyboard_map.items():
            if key_str.startswith("K_"):
                key_map[getattr(pygame, key_str)] = action
        return key_map
    
    def get_reverse_keyboard_map(self) -> dict:
        """Get reverse keyboard map for looking up keys by action.
        Returns: {action_name: pygame_key_constant}
        """
        import pygame
        reverse_map = {}
        for action, key_str in self.keyboard_map.items():
            if key_str.startswith("K_"):
                reverse_map[action] = getattr(pygame, key_str)
        return reverse_map
    
    def reset_input_mappings(self, input_type: str = None):
        """Reset input mappings to defaults.
        
        Args:
            input_type: "keyboard", "gpio", "joystick", or None for all
        """
        if input_type is None or input_type == "keyboard":
            self.keyboard_map = dict(self.DEFAULT_KEYBOARD_MAP)
        if input_type is None or input_type == "gpio":
            self.gpio_map = dict(self.DEFAULT_GPIO_MAP)
        if input_type is None or input_type == "joystick":
            self.joystick_map = dict(self.DEFAULT_JOYSTICK_MAP)
        if input_type is None:
            self.configured_input_type = None
    
    # Legacy property aliases for backward compatibility
    @property
    def FRAME_RATE(self) -> int:
        """Legacy alias for frame_rate."""
        return self.frame_rate
    
    @property
    def MAX_PETS(self) -> int:
        """Legacy alias for max_pets."""
        return self.max_pets
    
    @property
    def DEBUG_MODE(self) -> bool:
        """Legacy alias for debug_mode."""
        return self.debug_mode
    
    @property
    def SHOW_FPS(self) -> bool:
        """Legacy alias for show_fps."""
        return self.show_fps
    
    @property
    def DEBUG_FILE_LOGGING(self) -> bool:
        """Legacy alias for debug_file_logging."""
        return self.debug_file_logging
    
    @property
    def DEBUG_BLIT_LOGGING(self) -> bool:
        """Legacy alias for debug_blit_logging."""
        return self.debug_blit_logging
    
    @property
    def DEBUG_BATTLE_INFO(self) -> bool:
        """Legacy alias for debug_battle_logging."""
        return self.debug_battle_logging
    
    # Sound property for compatibility with game_globals.sound
    @property
    def sound(self) -> int:
        """Legacy alias for sound_volume."""
        return self.sound_volume
    
    @sound.setter
    def sound(self, value: int):
        """Legacy setter for sound_volume."""
        self.sound_volume = value