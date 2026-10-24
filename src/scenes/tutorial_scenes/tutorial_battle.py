"""
Tutorial Battle Scene
Inherits from SceneBattle and overrides input handling for tutorial control.
"""

from scenes.scene_battle import SceneBattle
from core import runtime_globals


class TutorialBattle(SceneBattle):
    """
    Tutorial-controlled version of SceneBattle.
    Overrides view creation to inject tutorial-controlled views.
    """
    
    def __init__(self) -> None:
        """Initialize the tutorial battle scene."""
        super().__init__()
        
        # Tutorial control flags
        self.allow_adventure_selection = False
        self.allow_go_selection = False
        self.allow_fight_selection = False
        self.battle_in_progress = False  # True when battle is running
        self.on_adventure_callback = None
        self.on_go_callback = None
        self.on_fight_callback = None
        self.on_battle_complete_callback = None
        
        # Track which tutorial module to force-load
        self.force_tutorial_module = True
        
        runtime_globals.game_console.log("[TutorialBattle] Tutorial battle scene initialized")
    
    def set_allow_adventure_selection(self, allow: bool, callback=None):
        """Set whether adventure mode selection is allowed."""
        self.allow_adventure_selection = allow
        self.on_adventure_callback = callback
        
        # When allowing adventure selection, disable other buttons
        if allow:
            self._disable_non_adventure_buttons()
        
        # Replace the adventure button callback in the current view
        if self.current_view and hasattr(self.current_view, 'adventure_button') and self.current_view.adventure_button:
            if allow:
                # Store original and replace (button uses on_click_callback, not on_click)
                if not hasattr(self, '_original_adventure_callback'):
                    self._original_adventure_callback = self.current_view.adventure_button.on_click_callback
                self.current_view.adventure_button.on_click_callback = self._tutorial_on_adventure
                runtime_globals.game_console.log("[TutorialBattle] Adventure button callback replaced")
    
    def _disable_non_adventure_buttons(self):
        """Disable focusability of all buttons except adventure."""
        if not self.current_view:
            return
        
        # Disable jogress, versus, armor, exit buttons
        buttons_to_disable = ['jogress_button', 'versus_button', 'armor_button', 'exit_button']
        
        for attr in buttons_to_disable:
            button = getattr(self.current_view, attr, None)
            if button:
                button.focusable = False
                runtime_globals.game_console.log(f"[TutorialBattle] Disabled focusability for {attr}")
        
        # Ensure adventure button IS focusable and focused
        if hasattr(self.current_view, 'adventure_button') and self.current_view.adventure_button:
            self.current_view.adventure_button.focusable = True
            self.ui_manager.set_focused_component(self.current_view.adventure_button)
            runtime_globals.game_console.log("[TutorialBattle] Focused on adventure button")
    
    def set_allow_go_selection(self, allow: bool, callback=None):
        """Set whether GO button selection is allowed."""
        self.allow_go_selection = allow
        self.on_go_callback = callback
        
        runtime_globals.game_console.log(f"[TutorialBattle] set_allow_go_selection: allow={allow}, view={self.current_view_name}")
        
        # Hook GO button if view is already adventure_module_selection
        if allow and self.current_view_name == "adventure_module_selection":
            self._hook_go_button()
    
    def set_allow_fight_selection(self, allow: bool, callback=None):
        """Set whether Fight button selection is allowed."""
        self.allow_fight_selection = allow
        self.on_fight_callback = callback
        
        # Hook Fight button if view is already adventure_area_selection
        if allow and self.current_view_name == "adventure_area_selection":
            self._hook_fight_button()
    
    def set_on_battle_complete(self, callback):
        """Set callback for when battle is complete."""
        self.on_battle_complete_callback = callback
    
    def _tutorial_on_adventure(self):
        """Tutorial-controlled adventure button handler."""
        runtime_globals.game_console.log("[TutorialBattle] Adventure button clicked")
        runtime_globals.game_console.log(f"[TutorialBattle] Before original callback: view={self.current_view_name}")
        # Call original FIRST to change view
        if hasattr(self, '_original_adventure_callback') and self._original_adventure_callback:
            self._original_adventure_callback()
        runtime_globals.game_console.log(f"[TutorialBattle] After original callback: view={self.current_view_name}")
        # Then notify tutorial AFTER view has changed
        if self.on_adventure_callback:
            self.on_adventure_callback()
    
    def _tutorial_on_go(self):
        """Tutorial-controlled GO button handler."""
        runtime_globals.game_console.log("[TutorialBattle] GO button clicked")
        # Whatever moved the selection (a page change selects the page's
        # first module), GO starts the Tutorial's adventure.
        tutorial = self._tutorial_module()
        if tutorial is not None and getattr(self.current_view, 'selected_module', None) is not tutorial:
            self.current_view.selected_module = tutorial
        # Call original FIRST to change view
        if hasattr(self, '_original_go_callback') and self._original_go_callback:
            self._original_go_callback()
        # Then notify tutorial AFTER view has changed
        if self.on_go_callback:
            self.on_go_callback()
    
    def _tutorial_on_fight(self):
        """Tutorial-controlled Fight button handler."""
        runtime_globals.game_console.log("[TutorialBattle] Fight button clicked")
        # Mark battle as in progress - this allows events to pass through
        self.battle_in_progress = True
        # Notify tutorial FIRST
        if self.on_fight_callback:
            self.on_fight_callback()
        # Then call original to start battle
        if hasattr(self, '_original_fight_callback') and self._original_fight_callback:
            self._original_fight_callback()
    
    def _change_view(self, view_name, **kwargs):
        """Override view change to inject tutorial module for module selection."""
        runtime_globals.game_console.log(f"[TutorialBattle] _change_view called: {view_name}")
        # Call parent to change view
        super()._change_view(view_name, **kwargs)
        runtime_globals.game_console.log(f"[TutorialBattle] View changed, current_view_name={self.current_view_name}")
        
        # After view is created, modify it for tutorial
        if view_name == "adventure_module_selection" and self.force_tutorial_module:
            self._setup_tutorial_module_selection()
        
        # If this is the battle view, patch the battle_encounter's change_scene function
        if view_name == "adventure_battle":
            self._patch_battle_encounter()
        
        # If GO selection was already allowed before view change, hook it now
        if view_name == "adventure_module_selection" and self.allow_go_selection and self.on_go_callback:
            self._hook_go_button()
        
        # If Fight selection was already allowed before view change, hook it now
        if view_name == "adventure_area_selection" and self.allow_fight_selection and self.on_fight_callback:
            self._hook_fight_button()
    
    def _patch_battle_encounter(self):
        """Patch the battle encounter's scene exit to notify tutorial instead."""
        if not self.current_view or not hasattr(self.current_view, 'battle_encounter'):
            return
        
        encounter = self.current_view.battle_encounter
        if not encounter:
            return
        
        # Monkey-patch the change_scene function in the battle_encounter module.
        # The encounter lives in battle.battle_encounter and calls the
        # change_scene it imported from utils.scene_utils, so replacing the
        # name in that module's namespace intercepts its "game" transition.
        import battle.battle_encounter as battle_encounter_module
        original_change_scene = battle_encounter_module.change_scene

        # Store original so we can restore it later
        if not hasattr(self, '_original_change_scene'):
            self._original_change_scene = original_change_scene

        def patched_change_scene(scene_name: str, **kwargs):
            """Patched change_scene that intercepts game scene transitions."""
            if scene_name == "game":
                runtime_globals.game_console.log("[TutorialBattle] Battle exit intercepted via patched change_scene")
                # Restore immediately so the patch never leaks into the real
                # game (otherwise the next real battle's exit would be hijacked).
                battle_encounter_module.change_scene = self._original_change_scene
                self.battle_in_progress = False
                if self.on_battle_complete_callback:
                    self.on_battle_complete_callback()
            else:
                # For other scenes, call original
                original_change_scene(scene_name, **kwargs)

        battle_encounter_module.change_scene = patched_change_scene
        runtime_globals.game_console.log("[TutorialBattle] Patched battle_encounter.change_scene")

    def _restore_change_scene(self):
        """Undo the battle_encounter.change_scene monkey-patch, if active."""
        if hasattr(self, '_original_change_scene'):
            import battle.battle_encounter as battle_encounter_module
            battle_encounter_module.change_scene = self._original_change_scene
    
    def _hook_go_button(self):
        """Hook the GO button callback in the current view."""
        runtime_globals.game_console.log(f"[TutorialBattle] _hook_go_button: current_view={self.current_view}, has_go_button={hasattr(self.current_view, 'go_button') if self.current_view else 'N/A'}")
        if self.current_view and hasattr(self.current_view, 'go_button') and self.current_view.go_button:
            if not hasattr(self, '_original_go_callback') or self._original_go_callback is None:
                self._original_go_callback = self.current_view.go_button.on_click_callback
            self.current_view.go_button.on_click_callback = self._tutorial_on_go
            runtime_globals.game_console.log("[TutorialBattle] GO button callback hooked in view")
        else:
            runtime_globals.game_console.log("[TutorialBattle] WARNING: Could not hook GO button - button not found")
    
    def _hook_fight_button(self):
        """Hook the Fight button callback in the current view."""
        if self.current_view and hasattr(self.current_view, 'fight_button') and self.current_view.fight_button:
            if not hasattr(self, '_original_fight_callback') or self._original_fight_callback is None:
                self._original_fight_callback = self.current_view.fight_button.on_click_callback
            self.current_view.fight_button.on_click_callback = self._tutorial_on_fight
            runtime_globals.game_console.log("[TutorialBattle] Fight button callback hooked in view")
    
    def _setup_tutorial_module_selection(self):
        """Setup the module selection view to only show tutorial module."""
        if not self.current_view:
            return
        
        # Find and pre-select the Tutorial module; every other module's button
        # is disabled, or a stray press toggles it and GO starts that module's
        # real adventure (its own area style, its own battle) under the tutorial
        if hasattr(self.current_view, 'module_buttons'):
            for button in self.current_view.module_buttons:
                if hasattr(button, 'module') and button.module:
                    if button.module.name == "Tutorial":
                        # Toggle this button on
                        button.set_toggled(True)
                        self.current_view.selected_module = button.module

                        # Update adventure panel
                        if hasattr(self.current_view, 'adventure_panel') and self.current_view.adventure_panel:
                            self.current_view.adventure_panel.set_module(button.module)

                        runtime_globals.game_console.log("[TutorialBattle] Tutorial module pre-selected")
                    else:
                        button.set_enabled(False)
        # LEFT/RIGHT on a module button cycles modules (paging included)
        self.current_view._navigate_module = self._refuse_module_change

    def _refuse_module_change(self, direction):
        """The tutorial's adventure is the Tutorial module's only."""
        runtime_globals.game_sound.play("cancel")

    def _tutorial_module(self):
        """The Tutorial module of the module selection view, if shown."""
        for button in getattr(self.current_view, 'module_buttons', None) or []:
            module = getattr(button, 'module', None)
            if module and module.name == "Tutorial":
                return module
        return None
    
    def handle_event(self, event) -> bool:
        """
        Handle input events with tutorial control.
        """
        if not isinstance(event, tuple) or len(event) != 2:
            return True
        
        event_type, event_data = event
        
        # If battle is in progress, let events through but intercept scene exit.
        # The player can confirm/skip the result with A / LCLICK / B; any of
        # these should resume the tutorial rather than drop to the main game.
        # (Battles that end on their own are caught by the change_scene patch.)
        if self.battle_in_progress:
            if event_type in ("A", "B", "LCLICK") and self._is_in_result_phase():
                runtime_globals.game_console.log("[TutorialBattle] Battle complete, notifying tutorial")
                # Restore the patch so it can't leak into the real game.
                self._restore_change_scene()
                self.battle_in_progress = False
                if self.on_battle_complete_callback:
                    self.on_battle_complete_callback()
                return True
            # Let all other events pass through to the battle
            return super().handle_event(event)
        
        # B is each view's way out (to the main game, or the view before),
        # which would leave the tutorial behind: refuse it, as TutorialStatus
        # does while exit is not allowed.
        if event_type == "B":
            runtime_globals.game_sound.play("cancel")
            return True

        # If adventure selection is allowed, let the UI manager handle button clicks
        if self.allow_adventure_selection or self.allow_go_selection or self.allow_fight_selection:
            return super().handle_event(event)
        
        # Block most inputs when not explicitly allowed
        if event_type in ["A", "B", "LCLICK"]:
            return True
        
        # Allow navigation for visual feedback
        if event_type in ["UP", "DOWN", "LEFT", "RIGHT"]:
            return super().handle_event(event)
        
        # Allow mouse motion for hover effects
        if event_type == "MOUSE_MOTION":
            return super().handle_event(event)
        
        return True
    
    def _is_in_result_phase(self):
        """Check if the battle encounter is in the result phase."""
        if self.current_view and hasattr(self.current_view, 'battle_encounter'):
            encounter = self.current_view.battle_encounter
            if encounter and hasattr(encounter, 'phase'):
                return encounter.phase == "result"
        return False
    
    # Helper methods to get button positions for focus
    def get_adventure_button_rect(self):
        """Get the Adventure button bounds in base 240 coordinates."""
        # Based on adventure_view.py: x=21, y=120, width=199, height=34
        return (21, 120, 199, 34)
    
    def get_jogress_button_rect(self):
        """Get the Jogress button bounds in base 240 coordinates."""
        return (19, 60, 61, 56)
    
    def get_versus_button_rect(self):
        """Get the Versus button bounds in base 240 coordinates."""
        return (19 + 61 + 9, 60, 61, 56)
    
    def get_armor_button_rect(self):
        """Get the Armor button bounds in base 240 coordinates."""
        return (19 + (61 + 9) * 2, 60, 61, 56)
    
    def get_exit_button_rect(self):
        """Get the Exit button bounds in base 240 coordinates."""
        # exit: x = (240 - 75) // 2 = 82, y ~= 157, width = 75, height = 25
        return (82, 157, 75, 25)
    
    def get_go_button_rect(self):
        """Get the GO button bounds in base 240 coordinates."""
        # From adventure_module_selection_view.py: (179, 43, 52, 55)
        return (179, 43, 52, 55)
    
    def get_fight_button_rect(self):
        """Get the Fight button bounds in base 240 coordinates."""
        # From adventure_area_selection_view.py: (9, 198, 145, 25)
        return (9, 198, 145, 25)
