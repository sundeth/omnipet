"""
AdventureAreaSelectionView - Area selection for adventure battles
Shows area selection component and fight/back buttons.
Supports three adventure_style modes:
  - "Area Selection": full area/round picker (default)
  - "Next and Reset": two buttons replace the area selector
  - "Random": should not reach this view (handled in module selection)
"""
import pygame
from ui.ui_manager import UIManager
from ui.components.title_scene import TitleScene
from ui.components.button import Button
from ui.components.background import Background
from ui.components.adventure_panel import AdventurePanel
from ui.components.area_selection import AreaSelection
from ui.components.pet_selector import PetSelector
from ui.ui_constants import BASE_RESOLUTION
from core import runtime_globals, game_globals
from utils.pet_utils import get_battle_targets
from utils import currency_utils


def no_money():
    """The iC's "No Money": the player cannot pay an area's entry fee."""
    runtime_globals.game_sound.play("fail")
    runtime_globals.game_message.add_slide(
        "No Money", (255, 80, 80), 56 * runtime_globals.UI_SCALE,
        runtime_globals.FONT_SIZE_SMALL)


def pay_entry_or_refuse(module, area, round_num) -> bool:
    """Charge the entry fee when a battle enters *area* (round 1). False,
    with "No Money", when the balance does not cover it."""
    if int(round_num or 1) != 1:
        return True
    if currency_utils.pay_entry(module, area, get_battle_targets()):
        return True
    no_money()
    return False


class AdventureAreaSelectionView:
    """Adventure area selection view."""
    
    def __init__(self, ui_manager: UIManager, change_view_callback, module, 
                 available_area=None, available_round=None, area_round_limits=None):
        self.ui_manager = ui_manager
        self.change_view = change_view_callback
        self.module = module
        self.available_area = available_area
        self.available_round = available_round
        self.area_round_limits = area_round_limits if area_round_limits is not None else {}
        self.adventure_style = getattr(module, 'adventure_style', 'Area Selection')

        # Areas the module gates behind an unlock stay out of the picker until
        # that unlock is earned, so they cannot be selected or advanced into.
        self.area_round_limits = self._drop_locked_areas(self.area_round_limits)
        
        # UI Components
        self.background = None
        self.title_scene = None
        self.adventure_panel = None
        self.area_selection = None
        self.pet_selector = None
        self.fight_button = None
        self.back_button = None
        # Next and Reset style buttons
        self.next_button = None
        self.reset_button = None
        
        self._setup_ui()
        
    def _drop_locked_areas(self, limits):
        """Remove areas still locked for every pet heading into the battle."""
        if not limits or not hasattr(self.module, "is_area_unlocked"):
            return limits
        if not self.module.get_area_locks():
            return limits
        versions = {getattr(pet, "version", None) for pet in get_battle_targets()}
        versions.discard(None)
        if not versions:
            versions = {None}
        return {area: rounds for area, rounds in limits.items()
                if any(self.module.is_area_unlocked(area, v) for v in versions)}

    def _setup_ui(self):
        """Setup the UI components."""
        ui_width = ui_height = BASE_RESOLUTION
        
        # Background
        self.background = Background(ui_width, ui_height)
        self.background.set_regions([(0, ui_height, "black")])
        self.ui_manager.add_component(self.background)
        
        # Title
        self.title_scene = TitleScene(0, 9, "BATTLE")
        self.ui_manager.add_component(self.title_scene)
        
        # Adventure panel (shows module info)
        self.adventure_panel = AdventurePanel(8, 43, 224, 55)
        self.adventure_panel.set_module(
            self.module,
            self.available_area,
            self.available_round,
            self.area_round_limits
        )
        self.ui_manager.add_component(self.adventure_panel)
        
        if self.adventure_style == "Next and Reset":
            self._setup_next_reset_ui()
        else:
            self._setup_area_selection_ui()
        
        # Pet selector at bottom (shows battle-ready pets)
        pet_selector_width = 224
        pet_selector_height = 40
        pet_selector_x = 8
        pet_selector_y = 152
        
        self.pet_selector = PetSelector(pet_selector_x, pet_selector_y, pet_selector_width, pet_selector_height)
        battle_ready_pets = get_battle_targets()
        self.pet_selector.set_pets(battle_ready_pets)
        self.pet_selector.set_interactive(False)
        self.pet_selector.focusable = False
        self.ui_manager.add_component(self.pet_selector)
        
        # Back button (always present)
        button_height = 25
        button_y = 198
        back_button_width = 66
        back_button_x = 9 + 145 + 10
        
        self.back_button = Button(
            back_button_x, button_y, back_button_width, button_height,
            "BACK", self._on_back,
            cut_corners={'tl': False, 'tr': False, 'bl': False, 'br': True}
        )
        self.ui_manager.add_component(self.back_button)
        
        runtime_globals.game_console.log(f"[AdventureAreaSelectionView] UI setup complete for {self.module.name} (style: {self.adventure_style})")
    
    def _entry_price(self, area):
        """An area's entry fee as shown ("100P"), or "" when it is free."""
        currency, cost = currency_utils.entry_cost(self.module, area, get_battle_targets())
        if cost <= 0:
            return ""
        unit = currency_utils.currency_unit(self.module.name, currency)
        return f"{cost}{unit}" if unit else f"{cost} {currency}"

    def _setup_area_selection_ui(self):
        """Setup UI for 'Area Selection' style (default): full area/round picker + FIGHT button."""
        self.area_selection = AreaSelection(
            8, 90, 224, 60,
            self.module,
            on_select=self._on_area_selected,
            available_area=self.available_area,
            available_round=self.available_round,
            area_round_limits=self.area_round_limits
        )
        self.area_selection.set_entry_prices(
            {area: price for area in self.area_round_limits
             if (price := self._entry_price(area))})
        self.ui_manager.add_component(self.area_selection)
        
        # Fight button
        fight_button_width = 145
        button_height = 25
        button_y = 198
        
        self.fight_button = Button(
            9, button_y, fight_button_width, button_height,
            "FIGHT", self._on_fight,
            cut_corners={'tl': False, 'tr': False, 'bl': True, 'br': False}
        )
        self.ui_manager.add_component(self.fight_button)
        
        self.ui_manager.set_focused_component(self.fight_button)
    
    def _setup_next_reset_ui(self):
        """Setup UI for 'Next and Reset' style: NEXT and RESET buttons replace the area selector."""
        button_width = 224
        button_height = 25
        button_x = 8
        area_y = 100  # Where area selection would normally be
        spacing = 4
        
        # The next battle's entry fee, when it enters an area that charges.
        area = game_globals.battle_area.get(self.module.name, 1)
        price = (self._entry_price(area)
                 if game_globals.battle_round.get(self.module.name, 1) == 1 else "")
        self.next_button = Button(
            button_x, area_y, button_width, button_height,
            f"NEXT  {price}" if price else "NEXT", self._on_next,
            cut_corners={'tl': False, 'tr': False, 'bl': True, 'br': False}
        )
        self.ui_manager.add_component(self.next_button)
        
        self.reset_button = Button(
            button_x, area_y + button_height + spacing, button_width, button_height,
            "RESET", self._on_reset,
            cut_corners={'tl': False, 'tr': False, 'bl': False, 'br': True}
        )
        self.ui_manager.add_component(self.reset_button)
        
        self.ui_manager.set_focused_component(self.next_button)
    
    def _on_area_selected(self, area, round_num):
        """Handle area selection."""
        runtime_globals.game_console.log(f"[AdventureAreaSelectionView] Area selected: Area {area}, Round {round_num}")
    
    def _on_fight(self):
        """Handle FIGHT button press (Area Selection style)."""
        if not self.area_selection or not self.module:
            runtime_globals.game_sound.play("cancel")
            return
        
        area, round_num = self.area_selection.get_selected_area_round()
        self._start_battle(area, round_num)
    
    def _on_next(self):
        """Handle NEXT button press (Next and Reset style).
        Battles the current area/round. If sequential rounds, fights all rounds of the area."""
        if not self.module:
            runtime_globals.game_sound.play("cancel")
            return
        
        area = game_globals.battle_area.get(self.module.name, 1)
        round_num = game_globals.battle_round.get(self.module.name, 1)
        
        # Clamp area to max available in module
        max_area = max(self.area_round_limits.keys()) if self.area_round_limits else 1
        if area > max_area:
            area = max_area
            round_count = self.area_round_limits.get(area, 1)
            round_num = min(round_num, round_count)
        
        self._start_battle(area, round_num)
    
    def _on_reset(self):
        """Handle RESET button press (Next and Reset style).
        Resets progress to area 1, round 1."""
        if not self.module:
            runtime_globals.game_sound.play("cancel")
            return
        
        runtime_globals.game_sound.play("menu")
        game_globals.battle_area[self.module.name] = 1
        game_globals.battle_round[self.module.name] = 1
        game_globals.save()
        
        # Refresh the adventure panel to show updated progress
        if self.adventure_panel:
            self.adventure_panel.set_module(
                self.module, 1, 1, self.area_round_limits
            )
        
        runtime_globals.game_console.log(f"[AdventureAreaSelectionView] Reset progress for {self.module.name} to Area 1, Round 1")
    
    def _start_battle(self, area, round_num):
        """Common method to start a battle. Entering an area that charges
        pays its fee first, or is refused with "No Money"."""
        if not pay_entry_or_refuse(self.module, area, round_num):
            return
        game_globals.last_adventure_module = self.module.name
        game_globals.save()
        
        runtime_globals.game_sound.play("menu")
        runtime_globals.game_console.log(f"[AdventureAreaSelectionView] Starting battle: Area {area}, Round {round_num}")
        self.change_view("adventure_battle", module=self.module, area=area, round_num=round_num)
    
    def _on_back(self):
        """Handle BACK button press."""
        runtime_globals.game_sound.play("cancel")
        self.change_view("adventure_module_selection")
    
    def cleanup(self):
        """Remove all UI components."""
        if self.background:
            self.ui_manager.remove_component(self.background)
        if self.title_scene:
            self.ui_manager.remove_component(self.title_scene)
        if self.adventure_panel:
            self.ui_manager.remove_component(self.adventure_panel)
        if self.area_selection:
            self.ui_manager.remove_component(self.area_selection)
        if self.pet_selector:
            self.ui_manager.remove_component(self.pet_selector)
        if self.fight_button:
            self.ui_manager.remove_component(self.fight_button)
        if self.back_button:
            self.ui_manager.remove_component(self.back_button)
        if self.next_button:
            self.ui_manager.remove_component(self.next_button)
        if self.reset_button:
            self.ui_manager.remove_component(self.reset_button)
    
    def update(self):
        """Update the view."""
        pass
    
    def draw(self, surface: pygame.Surface):
        """Draw the view."""
        pass
    
    def handle_event(self, event):
        """Handle input events."""
        if not isinstance(event, tuple) or len(event) != 2:
            return
        event_type, event_data = event
        if event_type == "B":
            self._on_back()
