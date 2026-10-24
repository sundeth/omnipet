"""
Omnipet Virtual Pet Game - Main Entry Point for Nuitka Builds
Handles pygame initialization with explicit video driver setup for embedded/low-power devices.
The game logic is handled by the VirtualPetGame class in src/vpet.py
"""

import sys
import os
import pygame
import json
import platform
import logging
from datetime import datetime

# Game Version: core.version's, imported once src/ is on the path (the __main__ block)
VERSION = None

# Global scaling variables
render_surface = None
final_screen = None
scale_to_screen = False
native_width = 0
native_height = 0


def get_screen_resolution():
    """Get the current screen resolution"""
    try:
        pygame.display.init()
        info = pygame.display.Info()
        return info.current_w, info.current_h
    except:
        return 1920, 1080  # Default fallback


def try_set_video_driver():
    """Try a list of SDL video drivers in order until one works."""
    drivers = []
    if platform.system() == "Linux":
        if os.path.exists("/usr/bin/batocera-info"):
            drivers = ["kmsdrm", "x11", "wayland", "fbcon"]
        else:
            drivers = ["x11", "wayland", "fbcon"]
    elif platform.system() == "Windows":
        drivers = ["windows"]
    elif platform.system() == "Darwin":
        drivers = ["cocoa"]
    else:
        drivers = ["x11", "wayland", "fbcon"]

    for driver in drivers:
        os.environ["SDL_VIDEODRIVER"] = driver
        try:
            pygame.display.init()
            return driver
        except pygame.error:
            continue
    raise RuntimeError("No compatible SDL video driver found!")


def setup_pygame():
    """Initialize pygame with appropriate settings"""
    os.environ.setdefault("SDL_VIDEO_CENTERED", "1")  # Center window on desktop systems
    
    # Check Pygame version for compatibility
    PYGAME_VERSION = tuple(map(int, pygame.version.ver.split('.')))
    IS_PYGAME2 = PYGAME_VERSION >= (2, 0, 0)
    
    # Only set video driver if not already set
    if not os.getenv("SDL_VIDEODRIVER"):
        try:
            chosen_driver = try_set_video_driver()
            logging.info(f"[Display] Using SDL video driver: {chosen_driver}")
        except RuntimeError as e:
            logging.error(f"[Display] {e}")
            sys.exit(1)
    else:
        pygame.display.init()

    # Initialize Pygame with version-specific mixer setup
    if IS_PYGAME2:
        pygame.mixer.pre_init(frequency=44100, size=-16, channels=2, buffer=128)

    pygame.init()
    
    if not IS_PYGAME2:
        pygame.mixer.pre_init(frequency=44100, size=-16, channels=2, buffer=128)


def validate_configuration():
    """Validate configuration values and apply defaults if necessary."""
    from core import game_globals
    config = game_globals.configuration
    
    # Validate frame rate
    if config.frame_rate < 3:
        config.frame_rate = 3
    
    # Validate max pets
    if config.max_pets < 1:
        config.max_pets = 1
    
    logging.info(f"[Config] Using: frame_rate={config.frame_rate}, max_pets={config.max_pets}, debug_mode={config.debug_mode}")


def setup_display():
    """Setup the display window with proper resolution and fullscreen detection"""
    global render_surface, final_screen, scale_to_screen, native_width, native_height

    # Import game modules
    from core import game_globals, runtime_globals
    config = game_globals.configuration

    # adjust_proportions() requires an initialised video system (pygame.display.Info()).
    # Defer the call until here so it runs after pygame.init().
    config.adjust_proportions()

    # Validate configuration
    validate_configuration()
    
    # Determine if we should run in fullscreen
    fullscreen_requested = (
        "--fullscreen" in sys.argv or
        "-f" in sys.argv or
        os.getenv("OMNIPET_FULLSCREEN", "").lower() in ("1", "true", "yes") or
        config.fullscreen or
        os.getenv("SDL_VIDEODRIVER") == "kmsdrm" or
        (platform.system() == "Linux" and os.path.exists("/usr/bin/batocera-info"))
    )
    
    # Get screen resolution from configuration
    screen_width = config.screen_width
    screen_height = config.screen_height
    
    # Sanity checks
    if not screen_width or screen_width < 100:
        screen_width = 240
    if not screen_height or screen_height < 100:
        screen_height = 240
    
    logging.info(f"[Display] Using resolution: {screen_width}x{screen_height}")

    if fullscreen_requested:
        native_width, native_height = get_screen_resolution()
        scale_to_screen = True
        logging.info(f"[Display] Scaling {screen_width}x{screen_height} -> {native_width}x{native_height}")
    else:
        scale_to_screen = False

    # Update runtime globals with base resolution
    runtime_globals.update_resolution_constants(width=screen_width, height=screen_height)

    # Check Pygame version for compatibility
    PYGAME_VERSION = tuple(map(int, pygame.version.ver.split('.')))
    IS_PYGAME2 = PYGAME_VERSION >= (2, 0, 0)

    if fullscreen_requested:
        screen_mode = pygame.FULLSCREEN | pygame.DOUBLEBUF
        logging.info(f"[Display] Running in fullscreen mode")
    else:
        screen_mode = 0
        logging.info(f"[Display] Running in windowed mode")

    bit_depth = 32 if IS_PYGAME2 else 16

    # The final screen always uses native resolution if scaling is enabled
    final_screen = pygame.display.set_mode(
        (native_width if scale_to_screen else (config.window_width or screen_width),
         native_height if scale_to_screen else (config.window_height or screen_height)),
        screen_mode,
        bit_depth
    )

    # Render canvas = internal resolution; scaled onto the window each frame.
    if final_screen.get_size() == (screen_width, screen_height):
        render_surface = final_screen
    else:
        render_surface = pygame.Surface((screen_width, screen_height))
    runtime_globals.render_surface = render_surface

    pygame.display.set_caption(f"Omnipet {VERSION}")
    pygame.mouse.set_visible(False)
    from input.input_manager import GPIO_PRESS_EVENT, GPIO_RELEASE_EVENT
    pygame.event.set_allowed([
        pygame.QUIT,
        pygame.KEYDOWN,
        pygame.JOYBUTTONDOWN,
        pygame.JOYBUTTONUP,
        pygame.JOYAXISMOTION,
        pygame.JOYHATMOTION,
        pygame.JOYDEVICEADDED,
        pygame.JOYDEVICEREMOVED,
        pygame.MOUSEBUTTONDOWN,
        pygame.MOUSEBUTTONUP,
        pygame.MOUSEMOTION,
        pygame.MOUSEWHEEL,
        GPIO_PRESS_EVENT,
        GPIO_RELEASE_EVENT,
    ])
    return render_surface, screen_width, screen_height


def main():
    """Main function to initialize and run the game"""
    logging.info("[Init] Starting Omnipet Virtual Pet Game...")
    
    # Setup pygame and display
    setup_pygame()
    screen, screen_width, screen_height = setup_display()
    
    # Import game modules after pygame setup
    from core import game_globals
    from vpet import VirtualPetGame
    
    # Initialize and run the game
    try:
        game = VirtualPetGame()
        
        # Build module documentation
        try:
            from utils.document_utils import build_module_documentation
            project_root = os.path.dirname(__file__)
            logging.info("[Init] Building module documentation...")
            build_module_documentation(project_root)
        except Exception as e:
            logging.warning(f"[Init] Failed to build module documentation: {e}")
        
        logging.info("[Init] Game initialized successfully")
        logging.info("[Game] Starting main game loop...")
        
        running = True
        clock = pygame.time.Clock()
        
        while running:
            # Handle pygame events
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    game.save()
                    running = False
                else:
                    game.handle_event(event)
            
            # Update game state
            game.update()
            
            # Draw to the internal render canvas, then scale it onto the
            # window (handles fullscreen and windowed window sizes that differ
            # from the render resolution).
            from core import runtime_globals
            from utils import display_utils
            game.draw(runtime_globals.render_surface, clock)
            display_utils.present()

            # Maintain framerate
            clock.tick(game_globals.configuration.frame_rate)
        
        logging.info("[Game] Shutting down...")
        
    except Exception as e:
        logging.critical("An unhandled exception occurred in the main loop.", exc_info=True)
        import traceback
        traceback.print_exc()
    finally:
        pygame.quit()
        logging.info("[Game] Goodbye!")


if __name__ == "__main__":
    # Determine if the application is running in a "frozen" state (e.g., compiled by Nuitka).
    # Nuitka sets sys.frozen=True and may also set sys._MEIPASS for extraction directory
    is_frozen = getattr(sys, 'frozen', False)
    
    # For Nuitka debugging - let's check multiple possible indicators
    nuitka_indicators = {
        'sys.frozen': getattr(sys, 'frozen', 'Not set'),
        'sys._MEIPASS': getattr(sys, '_MEIPASS', 'Not set'),
        'sys.executable': sys.executable,
        '__file__': __file__ if '__file__' in globals() else 'Not set',
        'os.path.basename(sys.executable)': os.path.basename(sys.executable),
        'hasattr(sys, "_getframe")': hasattr(sys, "_getframe"),
        '__compiled__' in globals(): '__compiled__' in globals()
    }
    
    print(f"[Debug] Nuitka detection indicators:")
    for key, value in nuitka_indicators.items():
        print(f"[Debug]   {key}: {value}")

    # Improved frozen detection for Nuitka
    # Nuitka doesn't always set sys.frozen, so we need multiple detection methods
    executable_name = os.path.basename(sys.executable).lower()
    is_python_interpreter = executable_name in ('python.exe', 'pythonw.exe', 'python', 'pythonw', 'python3', 'python3.exe')
    
    possible_frozen_indicators = [
        getattr(sys, 'frozen', False),  # Standard frozen attribute
        '__compiled__' in globals(),     # Nuitka specific global
        executable_name.endswith('.exe') and not is_python_interpreter,  # Running from .exe (but not python.exe)
        not __file__.endswith('.py') if '__file__' in globals() else False  # Not running from .py file
    ]
    
    is_frozen = any(possible_frozen_indicators)
    print(f"[Debug] Final frozen determination: {is_frozen} (based on: {possible_frozen_indicators})")

    # Try multiple methods to detect the correct base directory
    if is_frozen:
        # For Nuitka builds, check if there's an extraction directory first
        if hasattr(sys, '_MEIPASS'):
            # Nuitka with temporary extraction
            base_dir = sys._MEIPASS
            print(f"[Nuitka] Using temporary extraction directory: {base_dir}")
        elif '__compiled__' in globals():
            # Nuitka: the folder of the running omnipet.exe. A standalone
            # build's __compiled__.containing_dir is the folder above it
            # (2026-10-22: the game looked for assets/ one level too high),
            # so take the first candidate that holds the game's assets.
            candidates = [os.path.dirname(os.path.abspath(sys.argv[0])), os.path.dirname(sys.executable)]
            try:
                import __main__
                candidates.append(__main__.__compiled__.containing_dir)
            except Exception:
                pass
            base_dir = next((d for d in candidates if os.path.isdir(os.path.join(d, "assets"))),
                            candidates[0])
            print(f"[Nuitka] Using program directory: {base_dir}")
        else:
            # Standard frozen executable directory
            base_dir = os.path.dirname(sys.executable)
            print(f"[Frozen] Using executable directory: {base_dir}")
    else:
        # If not frozen, it's running as a script, so the base is the script's directory.
        # BUT: If we're running from a Nuitka executable that doesn't set frozen properly,
        # we need to detect this case
        if os.path.basename(sys.executable).lower() == 'omnipet.exe':
            # We're likely running from a Nuitka executable
            base_dir = os.path.dirname(sys.executable)
            print(f"[Nuitka-Alt] Detected Nuitka executable, using executable directory: {base_dir}")
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            print(f"[Script] Using script directory: {base_dir}")

    # Change the current working directory to the base directory.
    # This is crucial for ensuring that relative paths for assets or configs are resolved correctly.
    os.chdir(base_dir)

    # CRITICAL: Set up Python path IMMEDIATELY to handle both source and compiled structures
    # Add directories to Python path to support both absolute and relative imports
    # Add base directory for top-level imports
    sys.path.insert(0, base_dir)
    
    # Add src directory so internal imports (core, components, scenes, vpet) resolve
    src_dir = os.path.join(base_dir, 'src')
    if os.path.exists(src_dir):
        sys.path.insert(0, src_dir)
        print(f"[Path] Added src directory: {src_dir}")
    else:
        # For Nuitka, check alternative locations
        possible_src_dirs = [
            os.path.join(base_dir, 'main_nuitka.dist', 'src'),
            os.path.dirname(__file__),
        ]
        for potential_dir in possible_src_dirs:
            if os.path.exists(potential_dir) and os.path.exists(os.path.join(potential_dir, 'core')):
                sys.path.insert(0, potential_dir)
                print(f"[Path] Added src directory (fallback): {potential_dir}")
                break
        else:
            print(f"[Error] Could not find src directory with core/ in any expected location")
    
    from core.version import VERSION

    # Debug output for troubleshooting
    print(f"[Debug] Working directory: {os.getcwd()}")
    print(f"[Debug] Python path entries: {[p for p in sys.path if 'src' in p or p == base_dir]}")

    # Setup logging
    log_dir = os.path.join(base_dir, 'logs')
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    logging.basicConfig(filename=os.path.join(log_dir, 'omnipet.log'), level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logging.info("Application starting...")
    
    # Log system information
    PYGAME_VERSION = tuple(map(int, pygame.version.ver.split('.')))
    IS_PYGAME2 = PYGAME_VERSION >= (2, 0, 0)
    
    logging.info(f"[System] Omnipet Virtual Pet v{VERSION}")
    logging.info(f"[System] Detected Pygame version: {pygame.version.ver}")
    logging.info(f"[System] Platform: {platform.system()} {platform.release()}")
    
    main()
