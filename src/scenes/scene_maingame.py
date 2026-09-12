"""
Scene Main Game
The main scene where pets live, eat, sleep, move, and interact.
"""
import platform
import random
import pygame
import datetime
import math
import os
import time

from ui.ui_constants import TEXT_FONT
from ui.windows.window_background import WindowBackground
from ui.windows.window_clock import WindowClock
from ui.windows.window_mainmenu import WindowMenu
from core import game_globals, runtime_globals
import core.constants as constants
from models.game_evolution_entity import GameEvolutionEntity
from utils.pet_utils import all_pets_hatched, distribute_pets_evenly, draw_pet_outline, get_selected_pets
from utils.pygame_utils import blit_with_cache, get_flipped_sprite, get_font
from utils.scene_utils import change_scene
from utils.inventory_utils import add_to_inventory, get_item_by_name
from utils.module_utils import get_module
from utils.quest_event_utils import generate_daily_quests, get_hourly_random_event
from utils.inventory_utils import add_to_inventory
from utils.asset_utils import image_load

#=====================================================================
# SceneMainGame
#=====================================================================
class SceneMainGame:
    """
    Handles the main game scene, including pets, menu navigation, and interactions.
    """

    def __init__(self) -> None:
        """
        Initializes the main game scene.
        """
        self.background = WindowBackground()
        self.menu = WindowMenu()
        self.clock = WindowClock()
        self.fade_out_timer = 1800
        self.selection_mode = "menu"
        self.pet_selection_index = 0
        # Pet under the mouse cursor (mouse mode only), for the hover outline.
        self.hovered_pet_index = -1
        self.fade_alpha = 0
        self.lock_inputs = False
        self.lock_updates = False
        HEARTS_SIZE = int(8 * runtime_globals.UI_SCALE)
        self.sprites = {
            "heart_empty": pygame.transform.scale(image_load(constants.HEART_EMPTY_ICON_PATH).convert_alpha(), (HEARTS_SIZE, HEARTS_SIZE)),
            "heart_half": pygame.transform.scale(image_load(constants.HEART_HALF_ICON_PATH).convert_alpha(), (HEARTS_SIZE, HEARTS_SIZE)),
            "heart_full": pygame.transform.scale(image_load(constants.HEART_FULL_ICON_PATH).convert_alpha(), (HEARTS_SIZE, HEARTS_SIZE))
        }

        self.cleaning = False
        self.cleaning_x = runtime_globals.SCREEN_WIDTH
        self.cleaning_speed = constants.CLEANING_SPEED * runtime_globals.UI_SCALE * (30 / constants.FRAME_RATE)
        self._hearts_cache = {}
        self._fade_overlay_cache = None  # Cache fade overlay surface

        today = datetime.date.today()
        if game_globals.xai_date < today:
            game_globals.xai = random.randint(1, 7)
            game_globals.xai_date = today
            # Reset daily quests when day changes
            game_globals.quests = []
            runtime_globals.game_console.log(f"[SceneMainGame] New day detected, XAI set to {game_globals.xai}, quests reset")

        self.food_anims = {}  # {pet_index: [frames]} for animated food sprites
        self.load()

        self.frame_counter = 0  # Tracks frames for time updates
        # Ensure the global last-input frame is synced when the scene is created
        runtime_globals.last_input_frame = self.frame_counter
        self._screensaver_cache = None
        # Screensaver rendering caches (create fonts/sprites once)
        from utils.asset_utils import font_load
        try:
            self._ss_time_font = font_load(TEXT_FONT, int(72 * runtime_globals.UI_SCALE))
        except Exception:
            self._ss_time_font = font_load(TEXT_FONT, int(72 * runtime_globals.UI_SCALE))
        # Use module font for smaller text where available
        try:
            self._ss_call_font = get_font(runtime_globals.FONT_SIZE_MEDIUM)
            self._ss_poop_font = get_font(runtime_globals.FONT_SIZE_SMALL)
        except Exception:
            self._ss_call_font = font_load(TEXT_FONT, int(28 * runtime_globals.UI_SCALE))
            self._ss_poop_font = font_load(TEXT_FONT, int(24 * runtime_globals.UI_SCALE))

        # Latched screensaver alert flags. Alerts can only be cleared through
        # the menus, which dismisses the screensaver — so once a flag latches
        # True while the screensaver is up, we stop re-validating it. The
        # flags reset on every screensaver entry and OFF→ON transitions are
        # polled about once per second (not per frame).
        self._ss_active = False
        self._ss_show_alert = False
        self._ss_show_poop = False
        self._ss_show_sick = False
        self._ss_last_check_frame = 0
        self._ss_time_str = ""

        # Screensaver position randomizer: change position every minute (frame-based)
        self._ss_position = (0, 0)  # offset from center (x_offset, y_offset)
        self._ss_last_position_frame = self.frame_counter

        # Event system variables
        self.event_stage = 0  # 0 = no event, 1 = alert/choice, 2 = animation
        self.event_alert_blink = 0  # Counter for blinking alert icon
        self.event_alert_timeout = 0  # Frame counter for 1-minute timeout
        self.event_gift_x = -100  # X position for gift animation
        self.event_gift_timer = 0  # Timer for gift animation phases
        self.event_sound_played = False  # Track if alert sound was played

        # A Friend just won in a special encounter comes back to the main
        # screen to show itself off. It is a throwaway pet drawn for a second,
        # deliberately NOT part of the party.
        self.friend_show = None
        self.friend_show_frames = 0

        # Cached event sprites to avoid loading/scaling every frame
        self.event_sprites = {
            'alert': None,
            'gift': None
        }

        if game_globals.quests is None or len(game_globals.quests) == 0:
            game_globals.quests = generate_daily_quests()

        # Initialize event timer if not set
        if game_globals.event_time is None:
            game_globals.event_time = 60  # 60 minutes until first event check

    def update(self) -> None:
        """
        Updates all game objects (pets, background, poops, cleaning effect).
        """
        if self.lock_updates:
            self.check_evolution_start()
            return

        # Increment the frame counter
        self.frame_counter += 1
        # Ensure last_input_frame exists (use frames to avoid frequent time.time() calls)
        if not hasattr(runtime_globals, 'last_input_frame'):
            runtime_globals.last_input_frame = self.frame_counter

        # Update pets and poops only if necessary
        for pet in game_globals.pet_list:
            pet.update()

        for poop in game_globals.poop_list:
            poop.update()

        # Handle fade-out timer
        if self.fade_out_timer > 0:
            self.fade_out_timer -= 1
            if self.fade_out_timer <= 0:
                runtime_globals.main_menu_index = -1
                runtime_globals.selected_pets = []

        # Update cleaning animation only if active
        if self.cleaning:
            self.update_cleaning()

        # Update event system
        self.update_events()

        # Show off a Friend just won in a special encounter
        self.update_friend_celebration()

        # Check evolution start
        self.check_evolution_start()

        # Track the pet under the mouse cursor for the hover outline
        # (mouse mode only -- touch has no hover, GPIO/keyboard use the
        # pet-selection highlight instead).
        if runtime_globals.INPUT_MODE == runtime_globals.MOUSE_MODE:
            self.hovered_pet_index = self.get_pet_index_at(
                runtime_globals.game_input.get_mouse_position())
        elif self.hovered_pet_index != -1:
            self.hovered_pet_index = -1

        # Update background and game messages
        self.background.update()
        runtime_globals.game_message.update()

    def check_evolution_start(self):
        """Begins evolution sequence when a pet is ready to evolve."""
        if runtime_globals.evolution_pet:
            # Update last input frame so screensaver will dismiss at next draw
            runtime_globals.last_input_frame = self.frame_counter
            self.start_evolution_sequence()

    def start_evolution_sequence(self):
        """Handles the epic evolution sequence based on music timing."""
        if self.lock_inputs:
            music_time = runtime_globals.game_sound.get_music_position()

            if music_time >= 5:
                self.lock_updates = True
                self.move_evolving_pet_to_center()

            if music_time >= 12:
                self.fade_out_except_evolving_pet()

            if music_time >= 18:
                evo = GameEvolutionEntity(
                    from_name = "MetalGreymon",
                    from_attribute = "Da",
                    from_sprite = runtime_globals.pet_sprites[game_globals.pet_list[0]][0],
                    to_attribute = "Vi",
                    to_name = "WarGreymon",
                    to_sprite = runtime_globals.pet_sprites[game_globals.pet_list[1]][0],
                    stage = 5)
                
                runtime_globals.evolution_data = [evo]
                change_scene("evolution")
        else:
            runtime_globals.game_sound.play("evolution_2020")  # 🔥 Start with fade-in
            self.lock_inputs = True

    def move_evolving_pet_to_center(self):
        """Moves the evolving pet toward the center of the screen."""
        pet = runtime_globals.evolution_pet
        if pet.x < (runtime_globals.SCREEN_WIDTH - runtime_globals.PET_WIDTH) // 2:
            pet.x += 1  # 🔥 Gradually move to center
            pet.direction = 1
            pet.set_state("moving")
        elif pet.x > (runtime_globals.SCREEN_WIDTH - runtime_globals.PET_WIDTH) // 2:
            pet.x -= 1
            pet.direction = -1
            pet.set_state("moving")
        else:
            pet.x = (runtime_globals.SCREEN_WIDTH - runtime_globals.PET_WIDTH) // 2
            pet.direction = -1
            pet.set_state("idle")

    def fade_out_except_evolving_pet(self):
        """Gradually dims the screen, leaving only the evolving pet visible."""
        self.fade_alpha = min(self.fade_alpha + 5, 255)

    def update_cleaning(self) -> None:
        """
        Updates the screen cleaning animation.
        """
        if not self.cleaning:
            return

        self.cleaning_x -= self.cleaning_speed
        for poop in game_globals.poop_list:
            poop.x -= self.cleaning_speed

        if self.cleaning_x <= -runtime_globals.misc_sprites["Wash"].get_width():
            game_globals.poop_list.clear()
            self.cleaning = False
            self.cleaning_x = runtime_globals.SCREEN_WIDTH
            runtime_globals.game_sound.play("happy")
            for pet in game_globals.pet_list:
                # The iC Reliability penalty is per pair accumulated since
                # the last flush, so cleaning begins a new episode.
                pet.unflushed_poops = 0
                module = get_module(pet.module)
                if module.care_flush_disturbance_sleep:
                    pet.check_disturbed_sleep()
                if not pet._is_blocked_by_sleep():
                    pet.set_state("happy2")
            runtime_globals.game_console.log("[SceneMainGame] Cleaning complete.")

    def update_friend_celebration(self) -> None:
        """Show a newly won Friend for a moment, then let it go.

        The Friend is already recorded in the save by the time the battle
        hands back; this is only the little celebration — two seconds of it.
        It is built as a throwaway GamePet so it animates like any other pet,
        and is never added to the party.
        """
        pending = getattr(runtime_globals, "friend_celebration", None)
        if pending and self.friend_show is None:
            runtime_globals.friend_celebration = None
            try:
                from utils.xros_utils import _find_friend_monster
                from models.game_pet import GamePet
                module = get_module(pending["module"])
                entry = _find_friend_monster(module, pending["name"])
                if entry:
                    data = dict(entry)
                    data["module"] = pending["module"]
                    pet = GamePet(data)
                    pet.x = (runtime_globals.SCREEN_WIDTH - runtime_globals.PET_WIDTH) // 2
                    pet.set_state("happy2")
                    self.friend_show = pet
                    self.friend_show_frames = int(2 * game_globals.configuration.frame_rate)
                    runtime_globals.game_sound.play("happy")
            except Exception as exc:
                runtime_globals.game_console.log(f"[Friend] celebration failed: {exc}")

        if self.friend_show is not None:
            self.friend_show.update()
            self.friend_show_frames -= 1
            if self.friend_show_frames <= 0:
                # Drop the sprite cache entry with it — nothing else refers to
                # this pet, and pet_sprites is keyed by the object.
                runtime_globals.pet_sprites.pop(self.friend_show, None)
                self.friend_show = None

    def update_events(self) -> None:
        """
        Updates the event system - checks for new events every hour based on XAI and pet awakeness.
        """
        # One tick a minute drives both event systems.
        minute_tick = self.frame_counter % (game_globals.configuration.frame_rate * 60) == 0

        # --- Friend Event Battles (earned by clearing an area) ---------------
        # Independent of the XAI roll: the promise was made by a pet that
        # cleared an area and simply counts down. The timer is paused while
        # another event is on screen, so the promise is never spent on a
        # moment when it could not be shown.
        if minute_tick and self.event_stage == 0 and game_globals.event is None:
            from utils.xros_utils import tick_friend_event
            friend_event = tick_friend_event()
            if friend_event is not None:
                game_globals.event = friend_event

        # --- XAI random events (rolled, roughly hourly) ----------------------
        if game_globals.event is None:
            if self.event_stage == 0:
                if minute_tick:
                    game_globals.event_time -= 1
                    if game_globals.event_time <= 0:
                        # Something has to be up and about for an event to
                        # interrupt it; a party that is all asleep or dead is
                        # left alone.
                        anyone_active = any(
                            pet.state not in ("dead", "nap")
                            for pet in game_globals.pet_list)

                        if anyone_active:
                            # Time to check for an event with XAI-based probability
                            game_globals.event = get_hourly_random_event()
                            runtime_globals.game_console.log(f"[Event] Event check with XAI {game_globals.xai}")
                        else:
                            runtime_globals.game_console.log(f"[Event] Skipping event check - no pet is awake")

                        # Roughly hourly, with a little slack so the check
                        # doesn't land on the same minute every time.
                        game_globals.event_time = random.randint(45, 75)
        elif game_globals.event is not None and self.event_stage == 0:
            if game_globals.event:
                self.event_stage = 1  # Move to alert stage
                self.event_sound_played = False
                self.event_alert_timeout = 0
                runtime_globals.game_console.log(f"[Event] New event: {game_globals.event.name}")
        
        # Stage 2: Alert stage - blink alert icon and wait for player input
        elif game_globals.event is not None and self.event_stage == 1:
            # Play alert sound once
            if not self.event_sound_played:
                runtime_globals.game_sound.play("need_attention")
                self.event_sound_played = True
            
            # Blink counter for alert icon
            self.event_alert_blink += 1
            
            # 1-minute timeout: dismiss event if player doesn't respond
            self.event_alert_timeout += 1
            if self.event_alert_timeout >= game_globals.configuration.frame_rate * 60:
                runtime_globals.game_console.log(f"[Event] Event timed out after 1 minute: {game_globals.event.name}")
                game_globals.event = None
                self.event_stage = 0
                self.event_alert_timeout = 0
                return
        
        # Stage 3: Animation stage - handle event execution
        elif game_globals.event is not None and self.event_stage == 2:
            from models.game_event import EventType
            
            if game_globals.event.type == EventType.ITEM_PACKAGE:
                self.update_gift_animation()
            elif game_globals.event.type == EventType.ENEMY_BATTLE:
                # Change to battle scene
                runtime_globals.game_console.log(f"[Event] Starting battle event: {game_globals.event.name}")
                # Set battle parameters based on event
                # The event names which enemy it is about (a Friend encounter picks
                # a specific one), so carry it through rather than letting the
                # battle re-resolve by area alone.
                runtime_globals.special_encounter = [game_globals.event.module,
                                                     game_globals.event.area,
                                                     game_globals.event.round,
                                                     game_globals.event.name]
                change_scene("battle")
                # Reset event
                game_globals.event = None
                self.event_stage = 0

    def update_gift_animation(self) -> None:
        """
        Handles the gift animation for ITEM_PACKAGE events.
        """
        gift_move_duration = 4 * game_globals.configuration.frame_rate  # 4 seconds
        if self.event_gift_timer < gift_move_duration:
            # Smooth movement using easing
            progress = self.event_gift_timer / gift_move_duration
            # Ease-out cubic for smoother deceleration
            eased_progress = 1 - (1 - progress) ** 3
            start_x = -100
            end_x = runtime_globals.SCREEN_WIDTH // 2 - 24  # Center position
            self.event_gift_x = start_x + (end_x - start_x) * eased_progress
            self.event_gift_timer += 1
        
        # Phase 2: Gift "opens" - show item only (2 seconds)
        elif self.event_gift_timer < gift_move_duration + (2 * game_globals.configuration.frame_rate):
            self.event_gift_x = runtime_globals.SCREEN_WIDTH // 2 - 24  # Keep centered

            # On first frame of this phase, add item to inventory using utils
            if self.event_gift_timer == gift_move_duration:
                item_name = game_globals.event.item
                item_quantity = game_globals.event.item_quantity
                module_name = game_globals.event.module
                
                # Get the item object to use its ID instead of name
                item_obj = get_item_by_name(module_name, item_name)
                if item_obj:
                    add_to_inventory(item_obj.id, item_quantity)
                    runtime_globals.game_console.log(f"[Event] Received {item_quantity}x {item_name} (ID: {item_obj.id})")
                else:
                    # Fallback: use item name as ID if item object not found
                    add_to_inventory(item_name, item_quantity)
                    runtime_globals.game_console.log(f"[Event] Received {item_quantity}x {item_name} (fallback)")

            self.event_gift_timer += 1
        
        # Phase 3: Animation complete, make pets happy and cleanup
        else:
            # Make all pets happy and play sound only once when cleaning up
            if self.event_gift_timer == gift_move_duration + (2 * game_globals.configuration.frame_rate):
                for pet in game_globals.pet_list:
                    pet.set_state("happy2")
                runtime_globals.game_sound.play("happy")
            
            # Reset event system
            game_globals.event = None
            self.event_stage = 0
            self.event_gift_timer = 0
            self.event_gift_x = -100

    def load(self):
        """
        Loads the scene, preparing pets, background, and any necessary resources.
        """
        # Reload pet sprites in case settings changed
        for pet in getattr(game_globals, "pet_list", []):
            if pet and pet not in runtime_globals.pet_sprites:
                pet.load_sprite()

        # Keep poops seated on the pets' ground plane for the current
        # resolution.  Their absolute Y can go stale after a resolution change
        # (e.g. via the settings menu); this is idempotent and leaves pets
        # untouched, so it's safe on every entry to the game scene.
        try:
            from utils.pet_utils import align_poops_to_ground
            align_poops_to_ground()
        except Exception:
            pass

        # Prepare food animations for pets that are eating
        self.food_anims = {}
        for pet_index, food_info in getattr(runtime_globals, "game_pet_eating", {}).items():
            # Use preloaded anim_frames if available, otherwise fallback to icon sprite
            anim_frames = food_info.get("anim_frames")
            icon = food_info.get("sprite")
            if anim_frames and isinstance(anim_frames, list) and len(anim_frames) == 4:
                frames = anim_frames
            else:
                # Fallback: use the icon itself as all frames
                frames = [icon] * 4
            # Pre-scale the display frames once — draw_food_anims used to run
            # pygame.transform.scale on every frame while a pet was eating.
            # Draw at half the source size (// 8 instead of the old // 4;
            # max_pets == 4 used to draw them unscaled).
            scaled_frames = []
            for f in frames:
                food_size = f.get_height()
                food_size = max(1, food_size * max(game_globals.configuration.max_pets, 2) // 8)
                scaled_frames.append(pygame.transform.scale(f, (food_size, food_size)))
            self.food_anims[pet_index] = scaled_frames

        # Also sync last-input-frame when the scene is (re)loaded so screensaver timing is correct
        runtime_globals.last_input_frame = getattr(self, 'frame_counter', 0)

    def _render_screensaver_surface(self):
        """Render the full screensaver surface (clock + latched alert icons).

        Called only when the cached surface was invalidated (minute change,
        position change, or an alert latching on) — never per frame.
        """
        surf = pygame.Surface((runtime_globals.SCREEN_WIDTH, runtime_globals.SCREEN_HEIGHT))
        surf.fill((0, 0, 0))

        time_str = self._ss_time_str or datetime.datetime.now().strftime("%H:%M")
        text = self._ss_time_font.render(time_str, True, constants.FONT_COLOR_DEFAULT)

        # Use randomized offset from center (set once per minute)
        offset_x, offset_y = getattr(self, '_ss_position', (0, 0))
        center_x = (runtime_globals.SCREEN_WIDTH // 2) + offset_x
        center_y = (runtime_globals.SCREEN_HEIGHT // 2) + offset_y
        x = center_x - (text.get_width() // 2)
        y = center_y - (text.get_height() // 2)
        blit_with_cache(surf, text, (x, y))

        # Alert icons under the clock — driven by the latched flags.
        group_y = y + text.get_height()
        if self._ss_show_poop:
            poop_sprite = runtime_globals.misc_sprites.get('PoopInverted')
            if poop_sprite:
                blit_with_cache(surf, poop_sprite, (x, group_y))

        if self._ss_show_sick:
            sick_sprite = runtime_globals.misc_sprites.get('SickInverted')
            if sick_sprite:
                blit_with_cache(surf, sick_sprite, (center_x - (sick_sprite.get_width() // 2), group_y))

        if self._ss_show_alert:
            call_sprite = runtime_globals.misc_sprites.get('CallSignInverted')
            if call_sprite:
                blit_with_cache(surf, call_sprite, (x + text.get_width() - call_sprite.get_width(), group_y))

        return surf

    def update_mouse_hover(self):
        """Update menu selection based on mouse hover and handle pet area clicks."""
        if not (runtime_globals.INPUT_MODE == runtime_globals.MOUSE_MODE) or self.lock_inputs:
            return

        mouse_pos = runtime_globals.game_input.get_mouse_position()
        # Menu hitboxes are static — skip the hit-test while the mouse is still.
        if mouse_pos == getattr(self, '_last_menu_hover_pos', None):
            return
        self._last_menu_hover_pos = mouse_pos
        # Ask WindowMenu for the hovered index using its authoritative hitboxes
        hovered_index = self.menu.get_menu_index_at(mouse_pos)
        
        # Index 9 is the call sign icon — never selectable via mouse
        if hovered_index == 9:
            hovered_index = -1
        
        # Update menu index based on hover (-1 if not hovering any)
        if hovered_index != runtime_globals.main_menu_index:
            runtime_globals.main_menu_index = hovered_index

    def get_pet_index_at(self, mouse_pos):
        """Return the index of the pet whose sprite rect contains mouse_pos, or -1."""
        for i, pet in enumerate(game_globals.pet_list):
            rect = pygame.Rect(pet.x, pet.y,
                               runtime_globals.PET_WIDTH, runtime_globals.PET_HEIGHT)
            if rect.collidepoint(mouse_pos):
                return i
        return -1

    def is_mouse_in_pet_area(self, mouse_pos):
        """Check if mouse is in the pet area (from pet Y to pet Y + height across full screen width)."""
        if not game_globals.pet_list:
            return False
        
        mouse_x, mouse_y = mouse_pos
        
        # Find the pet area bounds - use Y range from pets
        min_pet_y = min(pet.y for pet in game_globals.pet_list)
        max_pet_y = max(pet.y + runtime_globals.PET_HEIGHT for pet in game_globals.pet_list)
        
        # Pet area spans full screen width, from minimum pet Y to maximum pet Y + height
        pet_area_rect = pygame.Rect(0, min_pet_y, runtime_globals.SCREEN_WIDTH, max_pet_y - min_pet_y)
        
        return pet_area_rect.collidepoint(mouse_x, mouse_y)

    def draw(self, surface: pygame.Surface) -> None:
        """
        Draws the cached static surface and dynamic elements like pets, poops, and animations.
        """
        # Update menu selection based on mouse hover (desktop only).
        # Touch should be click-driven, so we intentionally do NOT update
        # hover state when in TOUCH_MODE.
        if runtime_globals.INPUT_MODE == runtime_globals.MOUSE_MODE:
            self.update_mouse_hover()
        
        # Screensaver: check timeout (seconds) using frame-based timing to avoid frequent time.time() calls
        timeout = game_globals.configuration.screen_timeout
        last_frame = getattr(runtime_globals, 'last_input_frame', self.frame_counter)
        elapsed_frames = self.frame_counter - last_frame
        timeout_frames = int(timeout * constants.FRAME_RATE) if timeout and timeout > 0 else 0

        if (timeout and timeout > 0 and elapsed_frames >= timeout_frames
                and not getattr(self, '_screensaver_disabled', False)):
            # Entering the screensaver: reset latched alert flags and force an
            # immediate condition check + render.
            if not self._ss_active:
                self._ss_active = True
                self._ss_show_alert = False
                self._ss_show_poop = False
                self._ss_show_sick = False
                self._ss_time_str = datetime.datetime.now().strftime("%H:%M")
                self._ss_last_check_frame = self.frame_counter - constants.FRAME_RATE
                self._screensaver_cache = None

            # Poll OFF→ON transitions about once per second. Latched flags are
            # never re-validated: clearing them requires the menus, which
            # dismisses the screensaver (and resets the flags on re-entry).
            if (self.frame_counter - self._ss_last_check_frame) >= constants.FRAME_RATE:
                self._ss_last_check_frame = self.frame_counter
                changed = False
                if not self._ss_show_alert and self.menu.check_alert():
                    self._ss_show_alert = True
                    changed = True
                if not self._ss_show_poop and game_globals.poop_list:
                    self._ss_show_poop = True
                    changed = True
                if not self._ss_show_sick and any(p.sick > 0 for p in game_globals.pet_list):
                    self._ss_show_sick = True
                    changed = True
                # The screensaver clock has no seconds, so it changes 1/min.
                time_str = datetime.datetime.now().strftime("%H:%M")
                if time_str != self._ss_time_str:
                    self._ss_time_str = time_str
                    changed = True
                if changed:
                    self._screensaver_cache = None

            # Change screensaver position once per minute (frame-based). If position changes, invalidate cache.
            minute_frames = constants.FRAME_RATE * 60
            if (self.frame_counter - getattr(self, '_ss_last_position_frame', 0)) >= minute_frames:
                # pick a new random offset but keep clock roughly on-screen
                max_x = int(runtime_globals.SCREEN_WIDTH * 0.25)
                max_y = int(runtime_globals.SCREEN_HEIGHT * 0.15)
                new_pos = (random.randint(-max_x, max_x), random.randint(-max_y, max_y))
                if new_pos != getattr(self, '_ss_position', (0, 0)):
                    self._ss_position = new_pos
                    self._screensaver_cache = None
                self._ss_last_position_frame = self.frame_counter

            if self._screensaver_cache is None:
                try:
                    self._screensaver_cache = self._render_screensaver_surface()
                except Exception:
                    # Fallback simple render if anything fails
                    s = pygame.Surface((runtime_globals.SCREEN_WIDTH, runtime_globals.SCREEN_HEIGHT))
                    s.fill((0, 0, 0))
                    self._screensaver_cache = s

            blit_with_cache(surface, self._screensaver_cache, (0, 0))
            return
        elif self._ss_active:
            # Leaving the screensaver — latches re-arm on next entry.
            self._ss_active = False

        # Draw the static layers directly: the background is one cached blit,
        # the menu is two cached strips, the clock is one cached bar. Each
        # keeps its own cache, so nothing full-screen is rebuilt per second
        # (the old composite re-allocated a screen-sized surface every second
        # just because the clock shows seconds).
        self.background.draw(surface)
        self.menu.draw(surface)
        if game_globals.showClock:
            self.clock.draw(surface)

        # Draw pets and their overlays
        pets = game_globals.pet_list
        selected_pets = set(runtime_globals.selected_pets) if runtime_globals.selected_pets else set()
        show_hearts = runtime_globals.show_hearts

        for i, pet in enumerate(pets):
            self.draw_pet(surface, pet, i, selected_pets, show_hearts)

        # Draw poops only if present
        if game_globals.poop_list:
            for poop in game_globals.poop_list:
                poop.draw(surface)

        # Draw cleaning animation only if active
        if self.cleaning:
            self.draw_cleaning(surface)

        # Draw fade overlay and evolved pets only if fading
        if self.lock_inputs and self.fade_alpha > 0:
            self.draw_fade_overlay(surface)
            for i, pet in enumerate(pets):
                self.draw_pet_evolved(surface, pet, i)

        # Draw food animation for eating pets
        self.draw_food_anims(surface)

        # A newly won Friend, celebrating over the top of the party
        if self.friend_show is not None:
            self.friend_show.draw(surface)

        # Draw event animations and alerts
        self.draw_events(surface)

        # Draw game messages last
        runtime_globals.game_message.draw(surface)

    def draw_pet(self, surface: pygame.Surface, pet, index: int, selected_pets: set, show_hearts: bool) -> None:
        """
        Draws a single pet with selection/outline indicators.
        """
        pet.draw(surface)

        # Only fetch (and flip) the frame when an outline is actually drawn —
        # the common case draws no outline and used to pay a flip per pet per
        # frame anyway.
        is_selected = pet in selected_pets
        is_highlighted = (self.selection_mode == "pet" and index == self.pet_selection_index)
        is_hovered = index == self.hovered_pet_index
        if is_selected or is_highlighted or is_hovered:
            frame_enum = pet.animation_frames[pet.frame_index]
            frame = runtime_globals.pet_sprites[pet][frame_enum.value]
            if pet.direction == 1:
                frame = get_flipped_sprite(frame)

            if is_selected:
                draw_pet_outline(surface, frame, pet.x, pet.y, color=constants.FONT_COLOR_BLUE)  # blue outline
            if is_highlighted:
                draw_pet_outline(surface, frame, pet.x, pet.y, color=constants.FONT_COLOR_YELLOW)  # yellow highlight
            elif is_hovered:
                draw_pet_outline(surface, frame, pet.x, pet.y, color=constants.FONT_COLOR_YELLOW)  # mouse hover

        if show_hearts and pet.stage > 0:
            module = get_module(pet.module)
            care_fixed_4_hearts = getattr(module, 'care_fixed_4_hearts', True) if module else True
            if care_fixed_4_hearts:
                total_hearts = 4
                factor = 1
            else:
                stomach = getattr(pet, 'stomach', 4)
                total_hearts = max(1, min(4, stomach // 2))
                factor = 2
            heart_size = int(8 * runtime_globals.UI_SCALE)
            hearts_width = total_hearts * heart_size
            hearts_x = pet.x + runtime_globals.PET_WIDTH // 2 - hearts_width // 2
            hearts_y = pet.y + runtime_globals.PET_HEIGHT
            self.draw_hearts(surface, hearts_x, hearts_y, pet.hunger, total_hearts, factor)
            self.draw_hearts(surface, hearts_x, hearts_y + int(6 * runtime_globals.UI_SCALE), pet.strength, total_hearts, factor)

    def draw_cleaning(self, surface: pygame.Surface) -> None:
        """
        Draws the cleaning animation.
        """
        wash_sprite = runtime_globals.misc_sprites.get("Wash")
        if wash_sprite:
            pet_x = (24 * runtime_globals.UI_SCALE) + (runtime_globals.SCREEN_HEIGHT - runtime_globals.PET_HEIGHT) // 2
            surface.blit(wash_sprite, (self.cleaning_x, pet_x - (wash_sprite.get_height() - runtime_globals.PET_HEIGHT)))

    def draw_fade_overlay(self, surface: pygame.Surface) -> None:
        """
        Draws the fade overlay, caching the surface for efficiency.
        """
        if not self._fade_overlay_cache:
            fade_overlay = pygame.Surface((runtime_globals.SCREEN_WIDTH, runtime_globals.SCREEN_HEIGHT))
            fade_overlay.fill((0, 0, 0))
            self._fade_overlay_cache = fade_overlay
        if self._fade_overlay_cache.get_alpha() != self.fade_alpha:
            self._fade_overlay_cache.set_alpha(self.fade_alpha)
        blit_with_cache(surface, self._fade_overlay_cache, (0, 0))

    def draw_food_anims(self, surface: pygame.Surface) -> None:
        """
        Draws food animations for eating pets.
        """
        game_pet_eating = getattr(runtime_globals, "game_pet_eating", None)
        if game_pet_eating:
            for idx, pet in enumerate(game_globals.pet_list):
                if idx in game_pet_eating and pet.state == "eat":
                    anim_frames = self.food_anims.get(idx)
                    if anim_frames:
                        frame_duration = game_globals.configuration.frame_rate
                        total_frames = 4
                        total_anim_time = frame_duration * total_frames
                        # Clamp frame_idx to last frame if animation_counter exceeds total_anim_time
                        if pet.animation_counter >= total_anim_time:
                            frame_idx = total_frames - 1
                        else:
                            frame_idx = (pet.animation_counter // frame_duration) % total_frames
                        # Frames are pre-scaled in load()
                        food_sprite = anim_frames[frame_idx]
                        x = pet.x
                        # Prevent food from overlapping menu icons
                        y_offset = 20 * runtime_globals.UI_SCALE if game_globals.showClock else 5 * runtime_globals.UI_SCALE
                        y_min = y_offset + 2 * runtime_globals.MENU_ICON_SIZE
                        food_size = food_sprite.get_height()
                        y = max(y_min, pet.y - (food_size // 2))
                        surface.blit(food_sprite, (x, y))
                elif idx in self.food_anims:
                    # Clean up if pet is no longer eating
                    game_pet_eating.pop(idx, None)
                    self.food_anims.pop(idx, None)

    def draw_events(self, surface: pygame.Surface) -> None:
        """
        Draws event-related graphics: alert icon and gift animation.
        """
        # Stage 1: Draw blinking alert icon when event is available
        if game_globals.event is not None and self.event_stage == 1:
            # Blink every 30 frames (1 second at 30fps)
            if (self.event_alert_blink // 30) % 2 == 0:
                # Load and cache alert sprite if not already cached
                if not self.event_sprites['alert']:
                    alert_sprite = image_load(constants.ALERT_ICON_PATH).convert_alpha()
                    self.event_sprites['alert'] = pygame.transform.scale(alert_sprite, 
                                                        (int(32 * runtime_globals.UI_SCALE), int(32 * runtime_globals.UI_SCALE)))
                
                # Position in top-right corner
                x = 4 * runtime_globals.UI_SCALE
                y = 68 * runtime_globals.UI_SCALE if game_globals.showClock else 52 * runtime_globals.UI_SCALE
                surface.blit(self.event_sprites['alert'], (x, y))
        
        # Stage 2: Draw gift animation for ITEM_PACKAGE events
        elif game_globals.event is not None and self.event_stage == 2:
            from models.game_event import EventType
            
            if game_globals.event.type == EventType.ITEM_PACKAGE:
                gift_move_duration = 4 * game_globals.configuration.frame_rate  # 4 seconds
                
                # Phase 1: Show gift sprite moving to center
                if self.event_gift_timer < gift_move_duration:
                    # Load and cache gift sprite if not already cached
                    if not self.event_sprites['gift']:
                        gift_sprite = image_load(constants.GIFT_PATH).convert_alpha()
                        self.event_sprites['gift'] = pygame.transform.scale(gift_sprite,
                                                           (int(48 * runtime_globals.UI_SCALE), int(48 * runtime_globals.UI_SCALE)))

                    # Calculate Y position with floating effect
                    base_y = runtime_globals.SCREEN_HEIGHT // 2 - self.event_sprites['gift'].get_height() // 2
                    float_offset = int(5 * runtime_globals.UI_SCALE * 
                                     pygame.math.Vector2(0, 1).rotate(self.event_gift_timer * 3).y)
                    y = base_y + float_offset
                    
                    surface.blit(self.event_sprites['gift'], (int(self.event_gift_x), y))
                
                # Phase 2: Show item sprite only (gift "opened")
                else:
                    item_name = game_globals.event.item
                    item_sprite = None
                    
                    # Try to load item sprite from modules
                    item_sprite_path = f"modules/{game_globals.event.module}/items/{item_name}.png"
                    if os.path.exists(item_sprite_path):
                        item_sprite = image_load(item_sprite_path).convert_alpha()
                        item_sprite = pygame.transform.scale(item_sprite, (int(48 * runtime_globals.UI_SCALE), int(48 * runtime_globals.UI_SCALE)))

                    
                    # Calculate center position
                    center_x = runtime_globals.SCREEN_WIDTH // 2
                    center_y = runtime_globals.SCREEN_HEIGHT // 2
                    
                    if item_sprite:
                        # Show item sprite with floating effect
                        float_offset = int(8 * runtime_globals.UI_SCALE * 
                                         pygame.math.Vector2(0, 1).rotate(self.event_gift_timer * 2).y)
                        item_x = center_x - item_sprite.get_width() // 2
                        item_y = center_y - item_sprite.get_height() // 2 + float_offset
                        surface.blit(item_sprite, (item_x, item_y))
                        
                        # Show quantity text below item
                        from utils.asset_utils import font_load
                        font = font_load(TEXT_FONT, int(20 * runtime_globals.UI_SCALE))
                        quantity_text = font.render(f"+{game_globals.event.item_quantity}", True, constants.FONT_COLOR_DEFAULT)
                        text_x = center_x - quantity_text.get_width() // 2
                        text_y = item_y + item_sprite.get_height() + 5
                        surface.blit(quantity_text, (text_x, text_y))
                    else:
                        # Fallback: show item name and quantity as text
                        from utils.asset_utils import font_load
                        font = font_load(TEXT_FONT, int(24 * runtime_globals.UI_SCALE))
                        text_surface = font.render(f"+{game_globals.event.item_quantity} {item_name}", 
                                                 True, constants.FONT_COLOR_DEFAULT)
                        text_x = center_x - text_surface.get_width() // 2
                        text_y = center_y - text_surface.get_height() // 2
                        surface.blit(text_surface, (text_x, text_y))

    def draw_hearts(self, surface: pygame.Surface, x: int, y: int, value: int, total_hearts: int = 4, factor: int = 1) -> None:
        """
        Draws heart icons to represent hunger or strength.
        total_hearts controls how many hearts to show (2, 3, or 4 depending on module).
        factor controls how many value points equal one full heart.
        Uses a cache to avoid redrawing every frame.
        """
        cache_key = (x, y, value, total_hearts, factor)
        now = time.time()
        cache_entry = self._hearts_cache.get(cache_key)

        # Refresh cache if older than 1 second or not present
        if not cache_entry or now - cache_entry[1] > 1:
            heart_size = int(8 * runtime_globals.UI_SCALE)
            heart_surface = pygame.Surface((total_hearts * heart_size, heart_size), pygame.SRCALPHA)
            # Round value up to nearest half-heart step so e.g. 3.25 displays as 3.5 (half heart)
            step = factor * 0.5
            rounded_value = math.ceil(value / step) * step if step > 0 else value
            for i in range(total_hearts):
                heart_x = i * heart_size
                if rounded_value >= (i + 1) * factor:
                    heart_sprite = self.sprites["heart_full"]
                elif rounded_value >= i * factor + (factor / 2):
                    heart_sprite = self.sprites["heart_half"]
                else:
                    heart_sprite = self.sprites["heart_empty"]
                heart_surface.blit(heart_sprite, (heart_x, 0))
            self._hearts_cache[cache_key] = (heart_surface, now)
        else:
            heart_surface = cache_entry[0]

        blit_with_cache(surface, heart_surface, (x, y))

    def handle_event(self, event) -> None:
        """
        Handles keyboard and GPIO button inputs in the main game scene.
        """
        event_type, event_data = event
        
        # Reset timers on any input
        self.fade_out_timer = 60 * constants.FRAME_RATE
        runtime_globals.last_input_frame = getattr(self, 'frame_counter', 0)

        if self.lock_inputs:
            return

        # Handle mouse/touch clicks in pet area to toggle hearts view and menu
        # clicks. An event alert takes priority: this block used to swallow the
        # click (toggling the hearts view) and return before the event handler
        # below ever saw it, so an event could only be accepted with A.
        event_active = self.event_stage > 0 and game_globals.event
        if event_type == "LCLICK" and not event_active:
            if event_data and "pos" in event_data:
                mouse_pos = event_data["pos"]
                
                # Check if clicking on a menu item using WindowMenu hitboxes
                clicked_index = self.menu.get_menu_index_at(mouse_pos)
                if clicked_index >= 0:
                    # Update menu index to the clicked item and log
                    runtime_globals.main_menu_index = clicked_index
                    runtime_globals.game_console.log(f"[SceneMainGame] Menu item {clicked_index} clicked")
                    # Don't return here - let handle_action_keys process the click action
                else:
                    # Check if any dying pet needs B presses - LCLICK in the
                    # pet area counts as a B press
                    dying_pet_saved = False
                    if self.is_mouse_in_pet_area(mouse_pos):
                        for pet in game_globals.pet_list:
                            if pet.death_save_b_counter > 0:
                                pet.death_save_b_counter -= 1
                                dying_pet_saved = True
                                if pet.death_save_b_counter == 0:
                                    runtime_globals.game_console.log(f"[Death Save] {pet.name} B-press requirement met (touch)!")
                    if not dying_pet_saved:
                        # Click directly on a pet toggles its selection (same
                        # as A on keyboard/joystick); clicking anywhere else
                        # outside the menu toggles the hearts view.
                        clicked_pet = self.get_pet_index_at(mouse_pos)
                        if clicked_pet >= 0:
                            self.toggle_pet_selection(clicked_pet)
                            runtime_globals.game_sound.play("menu")
                        else:
                            runtime_globals.show_hearts = not runtime_globals.show_hearts
                            runtime_globals.game_sound.play("menu")
                            runtime_globals.game_console.log(f"[SceneMainGame] Hearts view toggled: {runtime_globals.show_hearts}")
                    return
                
        # Handle event system inputs
        if self.event_stage > 0 and game_globals.event:
            if self.event_stage == 1 and event_type in ["A", "B", "LCLICK"]:
                # Alert stage - any button to proceed to animation
                self.event_stage = 2
                self.event_gift_timer = 0
                runtime_globals.game_sound.play("menu")
                runtime_globals.game_console.log(f"[Events] Proceeding to animation for event: {game_globals.event.name}")
                return
            elif self.event_stage == 2:
                # Animation stage input handling
                from models.game_event import EventType
                if game_globals.event.type == EventType.ITEM_PACKAGE:
                    gift_move_duration = 4 * constants.FRAME_RATE  # 4 seconds
                    if event_type in ["A", "LCLICK"] and self.event_gift_timer > gift_move_duration:  # Accept item after gift opens
                        # Complete event (cleanup handled in update_gift_animation)
                        pass  # Let the animation finish naturally
                    elif event_type in ["B", "RCLICK"]:
                        # Decline item - immediate cleanup
                        game_globals.event = None
                        game_globals.event_time = None
                        self.event_stage = 0
                        self.event_gift_timer = 0
                        runtime_globals.game_sound.play("menu")
                        runtime_globals.game_console.log(f"[Events] Declined event")
                        return
                else:
                    # Other event types - A to complete after 0.5 seconds
                    if event_type in ["A", "LCLICK"] and self.event_gift_timer > constants.FRAME_RATE // 2:
                        game_globals.event = None
                        game_globals.event_time = None
                        self.event_stage = 0
                        self.event_gift_timer = 0
                        runtime_globals.game_sound.play("menu")
                        runtime_globals.game_console.log(f"[Events] Completed event")
                        return
            # Return early if in event mode to prevent normal input processing
            if self.event_stage > 0:
                return

        if event_type == "Y" or event_type == "SHAKE":
            for pet in game_globals.pet_list:
                if pet.stage == 0:
                    pet.shake_counter += 1
                # Handle death save shake counter
                if pet.death_save_shake_counter > 0:
                    pet.death_save_shake_counter -= 1
                    if pet.death_save_shake_counter == 0:
                        runtime_globals.game_console.log(f"[Death Save] {pet.name} shake requirement met!")
            
        if event_type in ["B", "RCLICK"]:
            for pet in game_globals.pet_list:
                # Handle death save B-press counter
                if pet.death_save_b_counter > 0:
                    pet.death_save_b_counter -= 1
                    if pet.death_save_b_counter == 0:
                        runtime_globals.game_console.log(f"[Death Save] {pet.name} B-press requirement met!")

        if event_type == "SELECT":
            self.selection_mode = "pet" if self.selection_mode == "menu" else "menu"
            runtime_globals.game_sound.play("menu")
            runtime_globals.game_console.log(f"[SceneMainGame] Switched selection mode to {self.selection_mode}")
            return

        self.handle_debug_keys(event_type)

        if self.selection_mode == "menu":
            self.handle_navigation_keys(event_type)
            self.handle_action_keys(event_type)
        elif self.selection_mode == "pet":
            self.handle_pet_selection_keys(event_type)

    def handle_debug_keys(self, event_type) -> None:
        """
        Debugging shortcuts (F11, F12).
        """
        if event_type == "F11":
            # Open test scene
            runtime_globals.game_sound.play("menu")
            change_scene("test")
            runtime_globals.game_console.log("[DEBUG] Opening test scene")
        elif event_type == "F12" and game_globals.configuration.debug_mode:
            # Open debug scene
            runtime_globals.game_sound.play("menu")
            change_scene("debug")
            runtime_globals.game_console.log("[DEBUG] Opening debug scene")

    def handle_navigation_keys(self, event_type) -> None:
        """Handles cyclic LEFT, RIGHT, UP, DOWN for menu navigation."""
        rows, cols = 2, 5  # 🔹 Menu layout (2 rows × 5 columns)
        max_index = rows * cols - 1  # 🔹 Maximum valid index (8)
        if runtime_globals.main_menu_index < 0 and event_type in ["LEFT","RIGHT","UP","DOWN"]:
            runtime_globals.game_sound.play("menu")
            runtime_globals.main_menu_index = 0
        elif event_type == "LEFT":
            runtime_globals.game_sound.play("menu")
            if runtime_globals.main_menu_index in [0, 5, -1]:  
                runtime_globals.main_menu_index = runtime_globals.main_menu_index + 4
            else:
                runtime_globals.main_menu_index -= 1

        elif event_type == "RIGHT":
            runtime_globals.game_sound.play("menu")
            if runtime_globals.main_menu_index in [4, 8, -1]:  
                runtime_globals.main_menu_index = runtime_globals.main_menu_index - 4
            else:
                runtime_globals.main_menu_index += 1

        elif event_type == "UP":
            runtime_globals.game_sound.play("menu")
            if runtime_globals.main_menu_index in range(0, cols) or runtime_globals.main_menu_index == -1:
                runtime_globals.main_menu_index += 5  # 🔹 Wrap from top to bottom
            else:
                runtime_globals.main_menu_index -= 5

        elif event_type == "DOWN":
            runtime_globals.game_sound.play("menu")
            if runtime_globals.main_menu_index in range(5, max_index + 1) or runtime_globals.main_menu_index == -1:
                runtime_globals.main_menu_index -= 5  # 🔹 Wrap from bottom to top
            else:
                runtime_globals.main_menu_index += 5

        # 🔹 Handle `-1` case correctly
        if runtime_globals.main_menu_index == 9:
            runtime_globals.main_menu_index = -1

        if runtime_globals.main_menu_index != -1:
            runtime_globals.main_menu_index %= (max_index + 1)  # 🔥 Ensure cyclic behavior

    def _any_pet_dying_or_dead(self):
        """Return True if any pet is dying or dead."""
        return any(pet.state == "dead" or getattr(pet, 'dying', False) for pet in game_globals.pet_list)

    def handle_action_keys(self, event_type) -> None:
        """
        Handles Enter, Escape, and equivalent GPIO button actions for menu selection.
        """
        index = runtime_globals.main_menu_index
        blocked = self._any_pet_dying_or_dead()

        if event_type in ["A", "LCLICK"]:
            if blocked and index != 7:
                # Only library (index 7) is allowed when a pet is dying/dead
                runtime_globals.game_sound.play("cancel")
                return
            if index == 0:
                self.start_scene("status")
            elif index == 1:
                self.start_scene("feeding")
            elif index == 2:
                self.start_training()
            elif index == 3:
                self.start_battle()
            elif index == 4:
                self.start_cleaning()
            elif index == 5:
                self.start_scene("sleepmenu")
            elif index == 6:
                self.heal_sick_pets()
            elif index == 7:
                self.start_scene("library")
            elif index == 8:
                self.start_connect()
        elif event_type == "B" and index >= 0:
            runtime_globals.game_sound.play("cancel")
            runtime_globals.main_menu_index = -1  # Deselect menu
        elif event_type in ["START", "RCLICK"] or (platform.system() == "Windows" and event_type == "B"):  # Maps to ESC (PC) & "START" button (Pi)
            if blocked:
                runtime_globals.game_sound.play("cancel")
                return
            # start_scene already plays the "menu" sound — playing "cancel"
            # here too made both sounds fire together.
            self.start_scene("settings")

        elif event_type == "L":  # Rotate screen upside-down
            runtime_globals.game_sound.play("menu")
            game_globals.configuration.rotated = True

        elif event_type == "R":
            runtime_globals.game_sound.play("menu")
            distribute_pets_evenly()

        elif event_type == "X":
            runtime_globals.game_sound.play("menu")
            runtime_globals.show_hearts = not runtime_globals.show_hearts


    def start_scene(self, scene_name: str) -> None:
        """
        Helper to start a new scene.
        Forces all non-sleeping/non-dead pets to idle before switching.
        """
        # Force non-sleeping/dead pets to idle to cancel eating/other animations
        for pet in game_globals.pet_list:
            if pet.state not in ("nap", "dead") and not pet.should_sleep():
                pet.set_state("idle")
        runtime_globals.game_sound.play("menu")
        runtime_globals.game_state = scene_name
        runtime_globals.game_state_update = True
        runtime_globals.game_console.log(f"[SceneMainGame] Switched to {scene_name}")

    def handle_pet_selection_keys(self, event_type) -> None:
        total_pets = len(game_globals.pet_list)

        if event_type == "LEFT":
            self.pet_selection_index = (self.pet_selection_index - 1) % total_pets
            runtime_globals.game_sound.play("menu")

        elif event_type == "RIGHT":
            self.pet_selection_index = (self.pet_selection_index + 1) % total_pets
            runtime_globals.game_sound.play("menu")

        elif event_type == "A":
            self.toggle_pet_selection(self.pet_selection_index)
            runtime_globals.game_sound.play("menu")


    def toggle_pet_selection(self, pet_index: int) -> None:
        """
        Toggles pet selection on Enter press.
        """
        pet = game_globals.pet_list[pet_index]
        if pet in runtime_globals.selected_pets:
            runtime_globals.selected_pets.remove(pet)
            runtime_globals.game_console.log(f"[SceneMainGame] Deselected {pet.name}")
        else:
            runtime_globals.selected_pets.append(pet)
            runtime_globals.game_console.log(f"[SceneMainGame] Selected {pet.name}")

    def start_training(self) -> None:
        """
        Checks if training is possible and starts it.
        """
        can_train = any(pet.can_train() for pet in get_selected_pets())
        if can_train:
            self.start_scene("training")
        else:
            runtime_globals.game_sound.play("cancel")
            runtime_globals.game_console.log("[SceneMainGame] Cannot start training: no eligible pets.")

    def start_battle(self) -> None:
        """
        Checks if battle is possible and starts it.
        """
        can_train = any(pet.can_battle() for pet in get_selected_pets())
        if can_train:
            self.start_scene("battle")
        else:
            runtime_globals.game_sound.play("cancel")
            runtime_globals.game_console.log("[SceneMainGame] Cannot start battle: no eligible pets.")

    def start_connect(self) -> None:
        """
        Opens the connect scene.
        """
        self.start_scene("connect")

    def start_cleaning(self) -> None:
        """
        Starts the screen cleaning action if there are poops.
        """
        if not game_globals.poop_list:
            runtime_globals.game_sound.play("cancel")
            return
        runtime_globals.game_sound.play("menu")
        self.cleaning = True
        self.cleaning_x = runtime_globals.SCREEN_WIDTH

    def heal_sick_pets(self) -> None:
        """
        Heals sick pets. If both Dots and Skull types exist, opens healing scene.
        Otherwise heals directly.
        """
        sick_pets = [pet for pet in game_globals.pet_list if pet.sick > 0]

        if not sick_pets:
            runtime_globals.game_sound.play("cancel")
            runtime_globals.game_console.log("[SceneMainGame] No sick pets to heal.")
            return

        # Check if there are both dots and non-dots sick pets
        has_dots = any(getattr(pet, 'sick_type', '') == 'dots' for pet in sick_pets)
        has_skull = any(getattr(pet, 'sick_type', '') != 'dots' for pet in sick_pets)

        if has_dots and has_skull:
            # Open healing scene for selection
            self.start_scene("healing")
            return

        # Only one type — heal all directly
        self._do_heal(sick_pets)

    def _do_heal(self, pets_to_heal) -> None:
        """Heal the given list of pets by 1 sickness point."""
        runtime_globals.game_sound.play("fail")
        distribute_pets_evenly()

        for pet in pets_to_heal:
            pet.sick = max(0, pet.sick - 1)
            if pet.sick == 0:
                pet.sick_type = ""
            pet.set_state("angry")
            runtime_globals.game_console.log(f"[SceneMainGame] {pet.name} healed. Remaining sickness: {pet.sick}")
