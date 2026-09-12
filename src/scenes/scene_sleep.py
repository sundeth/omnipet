import pygame
from datetime import datetime

from ui.ui_manager import UIManager
from ui.components.title_scene import TitleScene
from ui.components.sleep_scene_background import SleepSceneBackground
from ui.components.button import Button
from ui.components.pet_selector import PetSelector
from ui.windows.window_background import WindowBackground
from core import runtime_globals, game_globals
import core.constants as constants
from utils.pet_utils import distribute_pets_evenly, get_selected_pets
from utils.scene_utils import change_scene
from ui.ui_constants import BASE_RESOLUTION

SLEEP_RECOVERY_HOURS = constants.SLEEP_RECOVERY_HOURS

#=====================================================================
# SceneSleep
#=====================================================================
class SceneSleep:
    def _determine_initial_state(self):
        """Determine initial scene state based on pet nap states."""
        # Check if any pets are currently napping
        sleeping_pets = [pet for pet in game_globals.pet_list if pet.state == "nap"]
        
        if len(sleeping_pets) > 0:
            return "sleep"
        else:
            return "wake"
    
    def __init__(self) -> None:
        """Initialize the sleep menu scene with new UI system."""
        
        # Scene state management for theme animations  
        self.scene_state = self._determine_initial_state()  # "sleep", "wake", "sleep_to_wake", "wake_to_sleep"
        self.is_animating = False
        self.animation_frame_counter = 0
        # Use frame rate from constants for exactly 1 second animation
        self.animation_duration_frames = game_globals.configuration.frame_rate  # About 1 second at current frame rate
        
        # Post-animation pause system
        self.is_pausing_after_animation = False
        self.pause_frame_counter = 0
        self.pause_duration_frames = game_globals.configuration.frame_rate // 3  # About 1/3 second pause
        
        # Use appropriate theme based on initial state
        initial_theme = "BLUE" if self.scene_state == "sleep" else "YELLOW"
        self.ui_manager = UIManager(initial_theme)
        
        # UI Components
        self.title_scene = None
        self.background = None
        self.pet_selector = None
        self.sleep_button = None
        self.wake_button = None
        self.selection_all_button = None
        self.exit_button = None
        
        # Window background for areas not covered by UI
        self.window_background = WindowBackground(False)
        
        self.setup_ui()
        
        # Focus on the opposite function button based on current scene state
        if self.scene_state == "sleep":
            # If we start in sleep mode, focus on wake button
            self.ui_manager.set_focused_component(self.wake_button)
        else:
            # If we start in wake mode, focus on sleep button
            self.ui_manager.set_focused_component(self.sleep_button)
        
        runtime_globals.game_console.log("[SceneSleep] Sleep menu initialized with new UI system.")

    def setup_ui(self):
        """Setup the UI components for the sleep menu."""
        try:
            # Use base 240x240 resolution for UI layout
            ui_width = ui_height = BASE_RESOLUTION
            scale = self.ui_manager.ui_scale
            
            # Create and add the animated background that covers the full UI area
            self.background = SleepSceneBackground(0, 0, ui_width, ui_height)
            # Set initial background mode based on scene state
            initial_bg_mode = "wake" if self.scene_state == "wake" else "sleep"
            self.background.set_mode(initial_bg_mode)
            self.ui_manager.add_component(self.background)
            
            # Create and add the title scene at top
            self.title_scene = TitleScene(0, 9, "SLEEP")
            # Set initial title mode based on scene state
            initial_title_mode = "wake" if self.scene_state == "wake" else "sleep"
            self.title_scene.set_mode(initial_title_mode)
            self.ui_manager.add_component(self.title_scene)
            
            # Calculate button dimensions and positions
            button_width = 87  # Base width
            button_height = 30  # Base height
            button_gap = 5     # Gap between Sleep/Wake buttons
            buttons_y = 80    # Y position for Sleep/Wake buttons (moved up)
            
            # Calculate center positions for Sleep/Wake buttons
            total_buttons_width = (button_width * 2) + button_gap
            buttons_start_x = (ui_width - total_buttons_width) // 2
            
            sleep_x = buttons_start_x
            wake_x = buttons_start_x + button_width + button_gap
            
            # Create Sleep button with icon
            self.sleep_button = Button(
                sleep_x, buttons_y, button_width, button_height,
                "Sleep", self.on_sleep_button, "Sleep", "Sleep"
            )
            self.ui_manager.add_component(self.sleep_button)
            
            # Create Wake button with icon
            self.wake_button = Button(
                wake_x, buttons_y, button_width, button_height,
                "Wake", self.on_wake_button, "Wakes", "Sleep"
            )
            self.ui_manager.add_component(self.wake_button)
            
            
            # Create Exit button (centered below Sleep/Wake buttons)
            exit_width = 90
            exit_height = 25
            exit_x = (ui_width - exit_width) // 2
            exit_y = buttons_y + button_height + 5
            
            self.exit_button = Button(
                exit_x, exit_y, exit_width, exit_height,
                "Exit", self.on_exit_button
            )
            self.ui_manager.add_component(self.exit_button)
            
            # Create and add the pet selector below exit button
            selector_y = exit_y + exit_height + 10  # Position below exit button
            selector_height = 60  # Height for pet selector
            self.pet_selector = PetSelector(10, selector_y, ui_width - 20, selector_height)
            # Set pets and update enabled state
            self.pet_selector.set_pets(get_selected_pets())
            # Allow player to select which pets are affected by sleep/wake
            self.pet_selector.set_interactive(True)
            self.update_pet_selector_state()
            self.ui_manager.add_component(self.pet_selector)
            
            runtime_globals.game_console.log("[SceneSleepMenu] UI setup completed successfully")
            
        except Exception as e:
            runtime_globals.game_console.log(f"[SceneSleepMenu] ERROR in setup_ui: {e}")
            import traceback
            runtime_globals.game_console.log(f"[SceneSleepMenu] Traceback: {traceback.format_exc()}")
            raise
                
    def update_theme_and_background(self):
        """Update theme and background based on current scene state."""
        if self.scene_state == "sleep":
            self.ui_manager.set_theme("BLUE")
        else:
            self.ui_manager.set_theme("YELLOW")
            
        # Update background mode to match the logical scene state
        if self.background:
            self.background.set_mode(self.scene_state)

    def update(self) -> None:
        """Update the sleep menu scene."""
        self.window_background.update()
        self.ui_manager.update()
        
        # Handle state transitions and animations
        if self.is_animating:
            self.animation_frame_counter += 1
            
            # Update background animation based on current transition state
            if self.scene_state == "sleep_to_wake":
                progress = self.animation_frame_counter / self.animation_duration_frames
                # Animate background from sleep position (0) to wake position (-223)
                current_offset = int(0 + (-223 - 0) * progress)
                if self.background:
                    self.background.background_y_offset = current_offset
                    self.background.needs_redraw = True
                    
            elif self.scene_state == "wake_to_sleep":
                progress = self.animation_frame_counter / self.animation_duration_frames
                # Animate background from wake position (-223) to sleep position (0)
                current_offset = int(-223 + (0 - (-223)) * progress)
                if self.background:
                    self.background.background_y_offset = current_offset
                    self.background.needs_redraw = True
            
            # Check if animation is complete
            if self.animation_frame_counter >= self.animation_duration_frames:
                self.finish_animation()
        
        # Handle post-animation pause
        elif self.is_pausing_after_animation:
            self.pause_frame_counter += 1
            
            # Check if pause is complete
            if self.pause_frame_counter >= self.pause_duration_frames:
                self.finish_pause_and_execute_action()
                
    def start_theme_transition(self, target_state):
        """Start theme transition animation"""
        if self.is_animating:
            return  # Already animating
            
        # Determine transition type
        if self.scene_state == "sleep" and target_state == "wake":
            self.scene_state = "sleep_to_wake"
        elif self.scene_state == "wake" and target_state == "sleep":
            self.scene_state = "wake_to_sleep"
        else:
            return  # Invalid transition
            
        self.is_animating = True
        self.animation_frame_counter = 0
        
        # Start color animation in UI manager
        target_theme = "YELLOW" if target_state == "wake" else "BLUE"
        self.ui_manager.start_color_animation(target_theme, callback=self.on_color_animation_complete)
        
        # Update title scene background mode
        if self.title_scene:
            self.title_scene.set_mode(target_state)
        
        runtime_globals.game_console.log(f"[SceneSleepMenu] Started theme transition from {self.scene_state}")
        
    def finish_animation(self):
        """Complete the current animation and start pause before executing action"""
        # Set final scene state
        if self.scene_state == "sleep_to_wake":
            final_state = "wake"
        elif self.scene_state == "wake_to_sleep":
            final_state = "sleep"
        else:
            return
            
        self.scene_state = final_state
        self.is_animating = False
        self.animation_frame_counter = 0
        
        # Set final background position
        if self.background:
            self.background.set_mode(final_state)
            
        # Update pet selector to show correct enabled/disabled pets
        self.update_pet_selector_state()
            
        runtime_globals.game_console.log(f"[SceneSleepMenu] Animation complete, final state: {final_state}")
        
        # Start pause before executing action
        self.is_pausing_after_animation = True
        self.pause_frame_counter = 0
    
    def finish_pause_and_execute_action(self):
        """Complete the pause and execute the sleep/wake action"""
        self.is_pausing_after_animation = False
        self.pause_frame_counter = 0
        
        runtime_globals.game_console.log("[SceneSleepMenu] Pause complete, executing action")
        
        # Execute the actual sleep/wake action and return to main game
        if self.scene_state == "sleep":
            self.put_pets_to_sleep()
        else:
            self.wake_pets()
    
    def update_pet_selector_state(self):
        """Update pet selector to show which pets can perform the current action."""
        if not self.pet_selector:
            return
            
        # Determine which pets can perform the action based on current scene state
        if self.scene_state == "wake":
            # Show pets that can be put to sleep as enabled (ignore selection filter)
            enabled_pets = self.pets_can_sleep_list(ignore_selection=True)
        else:  # sleep state
            # Show pets that can be woken up as enabled (ignore selection filter)
            enabled_pets = self.pets_can_wake_list(ignore_selection=True)
            
        # Convert pet objects to indices
        all_pets = get_selected_pets()
        enabled_indices = []
        for i, pet in enumerate(all_pets):
            if pet in enabled_pets:
                enabled_indices.append(i)
                
        self.pet_selector.set_enabled_pets(enabled_indices)
    
    def on_color_animation_complete(self):
        """Called when color animation finishes"""
        runtime_globals.game_console.log("[SceneSleepMenu] Color animation completed")

    def pets_can(self):
        """Get pets that can perform the current action."""
        if self.scene_state == "sleep":
            return self.pets_can_sleep()
        else:
            return self.pets_can_wake()

    def pets_can_sleep(self):
        """Get pets that can be put to sleep (respecting selection)."""
        return self.pets_can_sleep_list(ignore_selection=False)

    def pets_can_sleep_list(self, ignore_selection=False):
        """Helper to get list of eligible sleepers."""
        all_pets = get_selected_pets()
        eligible = [
            pet for pet in all_pets
            if pet.stage > 0 and pet.state != "nap" and pet.state != "dead" and pet.sleeps and pet.wakes
        ]
        
        # Optionally filter by current selection in the pet selector
        if not ignore_selection and self.pet_selector:
            selected_indices = getattr(self.pet_selector, "selected_pets", None)
            if selected_indices:
                return [pet for i, pet in enumerate(all_pets) if pet in eligible and i in selected_indices]
        
        return eligible

    def pets_can_wake(self):
        """Get pets that can be woken up (respecting selection)."""
        return self.pets_can_wake_list(ignore_selection=False)

    def pets_can_wake_list(self, ignore_selection=False):
        """Helper to get list of eligible wakers.
        
        Rules:
        - care_block_actions_when_sleeping == False: can always wake
        - care_block_actions_when_sleeping == True:
            - During normal sleep hours (should_sleep): cannot wake
            - Outside normal sleep hours: can wake
        """
        from utils.module_utils import get_module
        all_pets = get_selected_pets()
        eligible = []
        for pet in all_pets:
            if pet.state != "nap":
                continue
            module = get_module(pet.module)
            block = getattr(module, 'care_block_actions_when_sleeping', True)
            # If blocking is on and pet is in its normal sleep window, cannot wake
            if block and pet.should_sleep():
                continue
            eligible.append(pet)
        
        # Optionally filter by current selection in the pet selector
        if not ignore_selection and self.pet_selector:
            selected_indices = getattr(self.pet_selector, "selected_pets", None)
            if selected_indices:
                return [pet for i, pet in enumerate(all_pets) if pet in eligible and i in selected_indices]
        
        return eligible
    
    def draw(self, surface: pygame.Surface) -> None:
        """Draw the sleep menu scene."""
        # Draw window background first
        self.window_background.draw(surface)
        
        # Draw UI components on top
        self.ui_manager.draw(surface)
        
    def handle_event(self, event) -> None:
        """Handle events in the sleep menu scene."""
        if not isinstance(event, tuple) or len(event) != 2:
            return
        
        event_type, event_data = event
        
        # Handle events through UI manager first
        if self.ui_manager.handle_event(event):
            return
        
        # Block input during animations and pause
        if self.is_animating or self.is_pausing_after_animation:
            return
            
        if event_type == "B":
            runtime_globals.game_sound.play("cancel")
            change_scene("game")
            return
            
    # Button callback methods
    def on_sleep_button(self):
        """Handle Sleep button press."""
        runtime_globals.game_sound.play("menu")
        
        # If already in sleep state, just put pets to sleep immediately
        if self.scene_state == "sleep":
            self.put_pets_to_sleep()
        else:
            # Validate there are pets that can be put to sleep before animating
            if not self.pets_can_sleep():
                runtime_globals.game_sound.play("cancel")
                return
            # Start transition animation to sleep state
            self.start_theme_transition("sleep")
        
    def on_wake_button(self):
        """Handle Wake button press."""
        runtime_globals.game_sound.play("menu")
        
        # If already in wake state, just wake pets immediately
        if self.scene_state == "wake":
            self.wake_pets()
        else:
            # Validate there are sleeping pets that can be woken before animating
            if not self.pets_can_wake():
                runtime_globals.game_sound.play("cancel")
                return
            # Start transition animation to wake state
            self.start_theme_transition("wake")
        
    def on_exit_button(self):
        """Handle Exit button press."""
        runtime_globals.game_sound.play("cancel")
        change_scene("game")

    def put_pets_to_sleep(self) -> None:
        """Put eligible pets to sleep."""
        now = datetime.now()
        pets = self.pets_can_sleep()
        if len(pets) > 0:
            runtime_globals.game_sound.play("menu")
        else:
            runtime_globals.game_sound.play("cancel")
            return
        
        for pet in pets:
            # Turning the lights off during the bedtime-call window answers
            # that call before the pet enters its nap state.
            pet.answer_call("sleep")
            pet.set_state("nap")
            pet.sleep_start_time = now
        runtime_globals.game_console.log("[SceneSleepMenu] Pets put to sleep manually.")
        distribute_pets_evenly()
        change_scene("game")

    def wake_pets(self) -> None:
        """Wake up sleeping pets."""
        now = datetime.now()
        pets = self.pets_can_wake()
        if len(pets) > 0:
            runtime_globals.game_sound.play("menu")
        else:
            runtime_globals.game_sound.play("cancel")
            return

        for pet in pets:
            if pet.state == "nap":
                slept_hours = 0
                if hasattr(pet, "sleep_start_time"):
                    slept_hours = (now - pet.sleep_start_time).total_seconds() // 3600

                pet.set_state("idle")

                if slept_hours >= SLEEP_RECOVERY_HOURS:
                    pet.dp = pet.energy
                    runtime_globals.game_console.log(f"[SceneSleepMenu] {pet.name} fully recharged DP after sleeping {slept_hours}h.")

        runtime_globals.game_console.log("[SceneSleepMenu] Pets woke up manually.")
        distribute_pets_evenly()
        change_scene("game")
