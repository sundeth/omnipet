"""
Virtual Pet - Game Logic
Handles the Virtual Pet game logic, scene management, and game state.
Display and audio initialization is handled by main.py
"""

import pygame
import time

# Scenes
from core import game_globals, runtime_globals
from input.system_stats import get_system_stats
from utils.module_utils import load_modules
from utils.pygame_utils import blit_with_cache, load_misc_sprites
from utils.asset_utils import image_load
from scenes.scene_battle import SceneBattle
from scenes.scene_battle_pvp import SceneBattlePvP
from scenes.scene_boot import SceneBoot
from scenes.scene_connect import SceneConnect
from scenes.scene_digidex import SceneDigidex
from scenes.scene_eggselection import SceneEggSelection
from scenes.scene_evolution import SceneEvolution
from scenes.scene_freezerbox import SceneFreezerBox
from scenes.scene_library import SceneLibrary
from scenes.scene_collection import SceneCollection
from scenes.scene_settingsmenu import SceneSettingsMenu
from scenes.scene_setup import SceneSetup
from scenes.scene_tutorial import SceneTutorial
from scenes.scene_error import SceneError
from scenes.scene_login import SceneLogin
from scenes.scene_sleep import SceneSleep
from scenes.scene_healing import SceneHealing
from scenes.scene_status import SceneStatus
from scenes.scene_maingame import SceneMainGame
from scenes.scene_inventory import SceneInventory
from scenes.scene_training import SceneTraining
from scenes.scene_debug import SceneDebug

# Game Version
runtime_globals.VERSION = "1.0.0 Beta 3"

# Global timing variable for system stats updates
last_stats_update = time.time()
cached_stats = get_system_stats()  # Initialize with actual values


class VirtualPetGame:
    """
    Main Virtual Pet Game class.
    Handles scene management, updating, drawing, and event handling.
    """

    def __init__(self) -> None:
        runtime_globals.misc_sprites = load_misc_sprites()
        load_modules()
        # Only load save data if game mode preference exists;
        # otherwise setup scene will handle mode selection first.
        if game_globals.load_game_mode_preference():
            # For Progress Mode, load the cached player ID from omninet
            # credentials so get_save_dir() returns the correct folder.
            if game_globals.is_progress_mode():
                game_globals.load_player_id()
            # Migrate legacy save folder structure (Type0→Default, Type1→<player_id>)
            game_globals.migrate_legacy_saves()
            if runtime_globals.IS_ANDROID:
                # The phone's render resolution was settled from the device
                # screen before this point; a save's own display fields
                # describe whatever wrote it, so they are carried across
                # rather than applied.  Desktop wants the saved window size
                # and reconciles it just below.
                from utils import display_utils
                display_utils.load_keeping_device_display()
            else:
                game_globals.load()

        # The window was created at launch with default config (the save wasn't
        # loaded yet); now that the configuration is in, resize the window to
        # the saved size so a restart honours it.  No-op fullscreen / Android.
        if not runtime_globals.IS_ANDROID:
            try:
                from utils import display_utils
                display_utils.reconcile_window_from_config()
            except Exception as exc:
                runtime_globals.game_console.log(
                    f"[VirtualPetGame] window reconcile failed: {exc}")

        # Pet size comes from how many pets are in the party, and the party is
        # only known once the save has been read — the sprites loaded above
        # used the pre-load estimate. Resize them now that both the party and
        # the final window size are settled (a no-op if the estimate was right).
        try:
            from utils.pet_utils import refresh_pet_sizes
            refresh_pet_sizes()
        except Exception as exc:
            runtime_globals.game_console.log(
                f"[VirtualPetGame] pet resize after load failed: {exc}")

        # Take the evolution routes from the modules as they are NOW. A pet
        # keeps the routes it was created with, so without this a module fix
        # can never reach a pet already in the save — updating the module and
        # restarting is how a player repairs one. Only the evolution lists are
        # touched; nothing else about the pet is overwritten.
        try:
            from utils.pet_utils import refresh_pet_evolutions
            n = refresh_pet_evolutions()
            if n:
                runtime_globals.game_console.log(
                    f"[Init] Refreshed evolution data on {n} pet(s) from their modules")
        except Exception as exc:
            runtime_globals.game_console.log(
                f"[VirtualPetGame] evolution refresh failed: {exc}")

        # Reload input mappings after configuration is loaded
        from input.input_manager import reload_input_mappings
        reload_input_mappings(runtime_globals.game_input)

        self.scene = SceneBoot()
        print("[Init] Omnibot initialized with SceneBoot")
        self.rotated = False
        from utils.asset_utils import font_load
        from ui.ui_constants import TEXT_FONT
        self.stat_font = font_load(TEXT_FONT, 16)
        
        # Load mouse pointer sprite (only on desktop)
        self.mouse_pointer = None
        self._mouse_pointer_orig = None
        self._mouse_pointer_size = None
        if not runtime_globals.IS_ANDROID:
            try:
                pointer_path = "assets/Pointer.png"
                self._mouse_pointer_orig = image_load(pointer_path).convert_alpha()
                self._update_mouse_pointer_scale()
                print(f"[Init] Mouse pointer sprite loaded: {pointer_path}")
            except (pygame.error, FileNotFoundError) as e:
                print(f"[Init] Could not load mouse pointer sprite: {e}")
                self.mouse_pointer = None
        else:
            # Hide mouse cursor on Android
            try:
                pygame.mouse.set_visible(False)
            except Exception:
                pass
        # Clock is now managed by main.py
        if runtime_globals.IS_ANDROID:
            try:
                from plyer import accelerometer # type: ignore
                accelerometer.enable()
                self._accel_enabled = True
                print("[Input] Android accelerometer enabled")
            except Exception as e:
                self._accel_enabled = False
                print("[Input] Failed to enable accelerometer:", e)

    def _update_mouse_pointer_scale(self):
        """Scale the pointer for the current render scale so it stays a
        constant on-screen size.

        The pointer is drawn on the render canvas, which is then scaled to the
        window.  ``16 * UI_SCALE`` canvas pixels works out to a constant
        fraction of the window after that scaling, so the pointer looks the
        same regardless of render resolution (it was previously fixed at the
        startup scale and went tiny at 4x)."""
        if self._mouse_pointer_orig is None:
            return
        size = max(8, int(16 * runtime_globals.UI_SCALE))
        if self._mouse_pointer_size == size and self.mouse_pointer is not None:
            return
        self.mouse_pointer = pygame.transform.scale(
            self._mouse_pointer_orig, (size, size))
        self._mouse_pointer_size = size

    def update(self) -> None:
        """
        Updates the current scene and handles scene transitions if needed.
        """
        self.scene.update()

        # Poll joystick actions (including analog stick directions)
        #for action in runtime_globals.game_input.get_just_pressed_joystick():
        #    self.scene.handle_event(action)

        if runtime_globals.game_state_update:
            self.change_scene()

        if game_globals.configuration.rotated:
            game_globals.configuration.rotated = False
            self.rotated = not self.rotated

        # Handle shake detection
        # On Raspberry Pi: check I2C accelerometer via shake_detector
        # On Android: poll plyer accelerometer via input_manager
        if runtime_globals.IS_ANDROID:
            shake_action = runtime_globals.game_input.poll_accelerometer()
            if shake_action:
                from input.input_event import create_simple_event
                self.scene.handle_event(create_simple_event(shake_action))
        else:
            if runtime_globals.shake_detector.check_for_shake():
                from input.input_event import create_simple_event
                self.scene.handle_event(create_simple_event("SHAKE"))
            
        # Handle autosave
        game_globals.autosave()

    def draw(self, surface: pygame.Surface, clock: pygame.time.Clock = None) -> None:
        """
        Draws the current scene to the given surface.
        """
        self.scene.draw(surface)

        global last_stats_update, cached_stats

        # Draw debug stats if DEBUG_MODE is enabled and clock is provided
        if game_globals.configuration.show_fps and clock is not None:
            now = time.time()
            if now - last_stats_update >= 3:  # Update stats every 3 seconds
                cached_stats = get_system_stats()
                last_stats_update = now
            draw_system_stats(clock, surface, cached_stats, self.stat_font)

        # Keep the pointer a constant on-screen size as the render scale
        # changes (e.g. after a Render Res change).
        self._update_mouse_pointer_scale()

        # Draw mouse pointer only when in mouse mode AND the cursor is
        # actually over the game window — pygame.mouse.get_focused() is False
        # once the pointer leaves the window, so we stop drawing the icon then.
        if (runtime_globals.INPUT_MODE == runtime_globals.MOUSE_MODE and
            self.mouse_pointer is not None and pygame.mouse.get_focused()):
            mouse_pos = runtime_globals.game_input.get_mouse_position()
            if mouse_pos != (0, 0):  # Only draw if mouse position is valid
                # Draw pointer slightly offset so the tip points to the actual position
                pointer_x = mouse_pos[0] - 2
                pointer_y = mouse_pos[1] - 2
                # Ensure pointer stays within screen bounds
                #pointer_x = max(0, min(pointer_x, runtime_globals.SCREEN_WIDTH - self.mouse_pointer.get_width()))
                #pointer_y = max(0, min(pointer_y, runtime_globals.SCREEN_HEIGHT - self.mouse_pointer.get_height()))
                blit_with_cache(surface, self.mouse_pointer, (pointer_x, pointer_y))

        if self.rotated:
            rotated_surface = pygame.transform.rotate(surface, 180)  # Rotate only the surface
            surface.blit(rotated_surface, (0, 0))

    def handle_event(self, event: pygame.event.Event) -> None:
        """
        Delegates event handling to the current scene.
        """
        # Special handling for setup scene raw input detection
        if hasattr(self.scene, 'handle_raw_pygame_event'):
            if self.scene.handle_raw_pygame_event(event):
                return  # Setup scene consumed the raw event

        # Physical Backspace must edit a focused text field (delete a char)
        # before the input manager maps it to the game action it's bound to
        # (Backspace → START by default).  The scene only consumes the key
        # when a text component is focused, so gameplay scenes are unaffected
        # and fall through to the normal mapping below.
        if event.type == pygame.KEYDOWN and event.key == pygame.K_BACKSPACE:
            if self.scene.handle_event(event):
                return

        input_event = runtime_globals.game_input.process_event(event)

        # The attention sounds are calls for the player — once they respond,
        # whatever they pressed, the call has been answered and the sound has
        # no reason to keep going. Silenced here because this is the one place
        # every player input passes through, whatever the scene.
        # (guarded on sounds_loaded so the first press doesn't trigger the
        # lazy load just to ask whether anything is playing)
        if input_event and runtime_globals.game_sound.sounds_loaded:
            for _call in ("need_attention", "alarm"):
                if runtime_globals.game_sound.is_playing(_call):
                    runtime_globals.game_sound.stop(_call)

        # Pass the input event tuple to the scene if we got one
        if input_event:
            if self.scene.handle_event(input_event):
                return

        # Forward raw text-input events to the scene so a focused
        # TextInput / CodeEntry can capture physical keyboard input.
        # TEXTINPUT events are always forwarded (printable characters never
        # double as game actions).  KEYDOWN events are only forwarded when
        # the input manager didn't already convert them into a game action,
        # to avoid double-handling things like UP / DOWN.
        if event.type == pygame.TEXTINPUT or (
            event.type == pygame.KEYDOWN and not input_event
        ):
            try:
                self.scene.handle_event(event)
            except Exception:
                pass
        
        if not runtime_globals.IS_ANDROID:
            # Handle analog joystick inputs (they come through get_just_pressed_joystick)
            for action in runtime_globals.game_input.get_just_pressed_joystick():
                # Convert analog actions to directional events
                if action in ("ANALOG_UP", "ANALOG_DOWN", "ANALOG_LEFT", "ANALOG_RIGHT"):
                    from input.input_event import create_simple_event
                    directional = action.replace("ANALOG_", "")
                    self.scene.handle_event(create_simple_event(directional))

    def change_scene(self) -> None:
        """
        Handles changing the current scene based on runtime_globals.game_state.
        """
        runtime_globals.game_state_update = False
        state = runtime_globals.game_state

        scene_mapping = {
            "egg": SceneEggSelection,
            "game": SceneMainGame,
            "settings": SceneSettingsMenu,
            "setup": SceneSetup,
            "tutorial": SceneTutorial,
            "error": SceneError,
            "login": SceneLogin,
            "status": SceneStatus,
            "feeding": SceneInventory,
            "training": SceneTraining,
            "sleepmenu": SceneSleep,
            "healing": SceneHealing,
            "battle": SceneBattle,
            "battle_pvp": SceneBattlePvP,
            "connect": SceneConnect,
            "digidex": SceneDigidex,
            "evolution": SceneEvolution,
            "freezer": SceneFreezerBox,
            "library": SceneLibrary,
            "collection": SceneCollection,
            "debug": SceneDebug,
        }

        scene_class = scene_mapping.get(state)
        if scene_class and type(self.scene) is not scene_class:  # Prevent redundant scene switches
            print(f"[Scene] Switching to {scene_class.__name__}")
            self.scene = scene_class()

    def save(self) -> None:
        """
        Saves the current game state.
        """
        game_globals.save()
        runtime_globals.game_console.log("[VirtualPetGame] Game state saved.")


def main() -> None:
    """
    Main loop of the Virtual Pet game.
    This function is now handled by main.py
    """
    pass


cached_stats_surface = None
last_stats_values = None

def draw_system_stats(clock, surface, stats, font):
    """Efficiently draws FPS, CPU temp, memory, and CPU usage."""
    global cached_stats_surface, last_stats_values

    # Show system stats only when DEBUG_MODE is enabled, but FPS can be shown independently
    show_system_stats = game_globals.configuration.debug_mode
    show_fps_only = game_globals.configuration.show_fps and not game_globals.configuration.debug_mode

    if not show_system_stats and not show_fps_only:
        return

    temp, cpu_usage, memory_usage = stats
    fps = int(clock.get_fps())
    stats_tuple = (fps, temp, cpu_usage, memory_usage, show_system_stats, show_fps_only)

    # Only update cached surface if stats changed or display mode changed
    if cached_stats_surface is None or stats_tuple != last_stats_values:
        surface_height = 60 if show_system_stats else 20
        cached_stats_surface = pygame.Surface((140, surface_height), pygame.SRCALPHA)
        y = 0
        
        # Always show FPS if SHOW_FPS is enabled OR if DEBUG_MODE is enabled
        if game_globals.configuration.show_fps or game_globals.configuration.debug_mode:
            cached_stats_surface.blit(font.render(f"FPS: {fps}", True, (255, 255, 255)), (0, y))
            y += 16
            
        # Only show other system stats if DEBUG_MODE is enabled
        if show_system_stats:
            if temp is not None:
                cached_stats_surface.blit(font.render(f"Temp: {temp:.1f}°C", True, (255, 255, 255)), (0, y))
                y += 16
            if cpu_usage is not None:
                cached_stats_surface.blit(font.render(f"CPU: {cpu_usage:.1f}%", True, (255, 255, 255)), (0, y))
                y += 16
            if memory_usage is not None:
                cached_stats_surface.blit(font.render(f"RAM: {memory_usage:.1f}%", True, (255, 255, 255)), (0, y))
        last_stats_values = stats_tuple

    # Blit the cached stats surface
    blit_with_cache(surface, cached_stats_surface, (4, 64))