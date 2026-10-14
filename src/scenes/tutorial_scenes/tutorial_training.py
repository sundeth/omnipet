"""
Tutorial Training Scene
Inherits from SceneTraining and overrides input handling for tutorial control.
"""

from scenes.scene_training import SceneTraining
from core import runtime_globals


class TutorialTraining(SceneTraining):
    """
    Tutorial-controlled version of SceneTraining.
    Overrides input handling to give tutorial full control.
    """

    # Dummy in the first slot of the only page, RANDOM and MORE disabled, and
    # no memory of the minigame last played: the focus step points at (36, 25).
    TUTORIAL_LAYOUT = True

    def __init__(self) -> None:
        """Initialize the tutorial training scene."""
        super().__init__()
        
        # Tutorial control flags
        self.allow_exit = False
        self.allow_button_selection = False
        self.on_training_selected_callback = None
        self.on_training_complete_callback = None
        self.on_charge_phase_started_callback = None
        self.on_training_animation_complete_callback = None
        self.tutorial_training_mode = False  # When True, use TutorialDummyTraining
        self.tutorial_controlled = False  # When True, prevent auto scene change after training
        self.target_strength = 14  # Target strength for tutorial
        self._last_phase = None  # Track phase transitions
        
        runtime_globals.game_console.log("[TutorialTraining] Tutorial training scene initialized")
    
    def set_allow_exit(self, allow: bool):
        """Set whether exiting is allowed."""
        self.allow_exit = allow
    
    def set_allow_button_selection(self, allow: bool, callback=None):
        """Set whether button selection is allowed and optional callback."""
        self.allow_button_selection = allow
        self.on_training_selected_callback = callback
        
        # When allowing button selection in tutorial, disable all buttons except dummy
        if allow:
            self._disable_non_dummy_buttons()
    
    def _disable_non_dummy_buttons(self):
        """Disable focusability of all training buttons except dummy."""
        others = [button for key, button in self.mode_buttons.items() if key != "dummy"]
        others += [self.more_button, self.random_button, self.exit_button,
                   self.prev_page_button, self.next_page_button]
        for button in others:
            if button:
                button.focusable = False
        runtime_globals.game_console.log("[TutorialTraining] Disabled every button except dummy")

        # Ensure dummy button IS focusable and focused
        if self.dummy_button:
            self.dummy_button.focusable = True
            self.ui_manager.set_focused_component(self.dummy_button)
            runtime_globals.game_console.log("[TutorialTraining] Focused on dummy button")
    
    def set_on_training_complete(self, callback):
        """Set callback for when training completes."""
        self.on_training_complete_callback = callback
    
    def set_on_charge_phase_started(self, callback):
        """Set callback for when charge phase starts."""
        self.on_charge_phase_started_callback = callback
    
    def set_tutorial_training_mode(self, enabled: bool, target_strength: int = 14):
        """Enable tutorial training mode - uses TutorialDummyTraining instead."""
        self.tutorial_training_mode = enabled
        self.target_strength = target_strength
    
    def on_dummy_training(self):
        """Override to use TutorialDummyTraining in tutorial mode."""
        from utils.pet_utils import get_training_targets
        
        if len(get_training_targets()) > 0:
            runtime_globals.game_sound.play("menu")
            self.hide_menu_buttons()
            self.phase = "dummy"
            
            if self.tutorial_training_mode:
                # Use tutorial version that waits for player
                from scenes.tutorial_scenes.tutorial_dummy_training import TutorialDummyTraining
                self.mode = TutorialDummyTraining(
                    self.ui_manager, 
                    tutorial_mode=True, 
                    target_strength=self.target_strength
                )
                # Set callback for when charging is complete
                self.mode.set_on_charge_complete(self._on_charge_complete)
                runtime_globals.game_console.log("[TutorialTraining] Using TutorialDummyTraining")
            else:
                # Use normal training
                from training.dummy_training import DummyTraining
                self.mode = DummyTraining(self.ui_manager)
            
            self.create_training_exit_button()
            
            # If tutorial controlled, disable exit button focusability
            if self.tutorial_controlled and self.training_exit_button:
                self.training_exit_button.focusable = False
                self.training_exit_button.visible = False
                runtime_globals.game_console.log("[TutorialTraining] Exit button disabled during tutorial")
            
            runtime_globals.game_console.log("Starting Dummy Training.")
            for pet in get_training_targets():
                pet.check_disturbed_sleep()
        else:
            # No eligible pet — log why so the cause is visible (can_train needs
            # stage>0, not dead, atk_main>0 and the pet not being sleep-blocked).
            from utils.pet_utils import get_selected_pets
            selected = get_selected_pets()
            runtime_globals.game_console.log(
                f"[TutorialTraining] Dummy blocked — no training targets "
                f"(selected pets: {len(selected)})")
            for pet in selected:
                try:
                    runtime_globals.game_console.log(
                        f"[TutorialTraining]   {pet.name}: stage={pet.stage} "
                        f"state={pet.state} atk_main={pet.atk_main} "
                        f"sleep_blocked={pet._is_blocked_by_sleep()}")
                except Exception:
                    pass
            runtime_globals.game_sound.play("cancel")
    
    def _on_charge_complete(self):
        """Called when tutorial charging is complete."""
        if self.on_training_complete_callback:
            self.on_training_complete_callback()
    
    def handle_event(self, event) -> bool:
        """
        Handle input events with tutorial control.
        Only allows actions that the tutorial has enabled.
        """
        if not isinstance(event, tuple) or len(event) != 2:
            return False
        event_type, event_data = event

        # Tutorial input is routed before SceneTraining, so enforce the same
        # non-skippable READY lock here as the normal training scene.
        if self.mode and getattr(self.mode, "phase", None) == "alert":
            return True

        # Handle exit - only if allowed
        if event_type == "B":
            if self.allow_exit:
                from utils.scene_utils import change_scene
                change_scene("game")
                return True
            else:
                # Block exit
                return True
        
        # Handle A button or click - select training or charge during training
        if event_type in ["A", "LCLICK"]:
            # During charge phase in tutorial mode, pass events to the training mode
            if self.mode and hasattr(self.mode, 'phase') and self.mode.phase == "charge":
                # Pass to parent to let the minigame handle charging
                return super().handle_event(event)
            
            if self.allow_button_selection:
                # Let the parent handle it
                result = super().handle_event(event)
                # Notify tutorial
                if self.on_training_selected_callback:
                    self.on_training_selected_callback()
                return result
            else:
                # Block selection
                if hasattr(runtime_globals, 'game_sound') and runtime_globals.game_sound:
                    runtime_globals.game_sound.play("cancel")
                return True
        
        # Allow navigation
        if event_type in ["UP", "DOWN", "LEFT", "RIGHT"]:
            return super().handle_event(event)
        
        return True
    
    def update(self):
        """Override update to detect phase transitions and tutorial completion."""
        # Check for phase transition to charge
        if self.mode and hasattr(self.mode, 'phase'):
            old_phase = self._last_phase
            current_phase = self.mode.phase
            
            # Detect transition to charge phase
            if old_phase == "alert" and current_phase == "charge":
                if self.on_charge_phase_started_callback:
                    self.on_charge_phase_started_callback()
            
            self._last_phase = current_phase
            
            # Intercept finish_training to prevent scene change during tutorial
            if self.tutorial_controlled and current_phase == "result":
                # Wrap the mode's finish_training if not already wrapped
                if not getattr(self.mode, '_finish_wrapped', False):
                    self._wrap_finish_training()
        
        # Call parent update
        super().update()
    
    def _wrap_finish_training(self):
        """Wrap the mode's finish_training to prevent scene change during tutorial."""
        if not self.mode:
            return
        
        original_finish = self.mode.finish_training
        scene_ref = self  # Capture reference
        
        def wrapped_finish_training():
            # Do everything except the change_scene call
            from models.game_quest import QuestType
            from utils.quest_event_utils import update_quest_progress
            from utils.pet_utils import distribute_pets_evenly
            
            won = scene_ref.mode.check_victory()
            if won:
                runtime_globals.game_sound.play("attack_fail")
                # Only update quest if quests are available - tutorial may not have quests
                try:
                    update_quest_progress(QuestType.TRAINING, 1)
                except Exception as e:
                    runtime_globals.game_console.log(f"[TutorialTraining] Quest update skipped: {e}")
            else:
                runtime_globals.game_sound.play("fail")
            
            # Check for trophy conditions
            scene_ref.mode.check_and_award_trophies()
            
            # Apply training results to pets
            for pet in scene_ref.mode.pets:
                pet.finish_training(won, grade=scene_ref.mode.get_attack_count(), phase2=scene_ref.mode.phase2_reached)
            
            distribute_pets_evenly()
            
            # Don't call change_scene - let tutorial handle it
            runtime_globals.game_console.log("[TutorialTraining] Training finished, waiting for tutorial")
            
            # Notify tutorial that training animation is done
            if scene_ref.on_training_animation_complete_callback:
                scene_ref.on_training_animation_complete_callback()
        
        self.mode.finish_training = wrapped_finish_training
        self.mode._finish_wrapped = True
        runtime_globals.game_console.log("[TutorialTraining] Wrapped finish_training to prevent scene change")
    
    def set_tutorial_controlled(self, enabled: bool):
        """Set whether training is controlled by tutorial (prevents auto scene change)."""
        self.tutorial_controlled = enabled
    
    def set_on_training_animation_complete(self, callback):
        """Set callback for when training animation completes."""
        self.on_training_animation_complete_callback = callback
    
    def on_training_exit(self):
        """Override training exit button - block during tutorial."""
        if self.tutorial_controlled:
            # Block exit during tutorial - hide button to prevent event capture
            runtime_globals.game_console.log("[TutorialTraining] Exit blocked during tutorial")
            if hasattr(runtime_globals, 'game_sound') and runtime_globals.game_sound:
                runtime_globals.game_sound.play("cancel")
            # Hide button so it doesn't consume mouse events
            if self.training_exit_button:
                self.training_exit_button.visible = False
                self.training_exit_button.focusable = False
            return
        # Otherwise call parent
        super().on_training_exit()
    
    def on_exit_training(self):
        """Override exit training button - block during tutorial."""
        if self.tutorial_controlled:
            # Block exit during tutorial - hide button to prevent event capture
            runtime_globals.game_console.log("[TutorialTraining] Exit blocked during tutorial")
            if hasattr(runtime_globals, 'game_sound') and runtime_globals.game_sound:
                runtime_globals.game_sound.play("cancel")
            # Hide button so it doesn't consume mouse events
            if self.training_exit_button:
                self.training_exit_button.visible = False
                self.training_exit_button.focusable = False
            return
        # Otherwise call parent
        super().on_exit_training()
    
    def get_dummy_training_rect(self):
        """Get the dummy training button bounds in base 240 coordinates."""
        # Based on scene_training.py layout
        # Buttons at start_x=36, start_y=25, size=54x54, spacing=2
        # Dummy is always first button at grid position (0, 0)
        start_x = 36
        start_y = 25
        button_size = 54
        return (start_x, start_y, button_size, button_size)
