"""
Scene Training
Handles both Dummy and Head-to-Head training modes for pets.
"""

import os
import random

import pygame

from battle.ic_attacks import is_ic_native
from ui.ui_manager import UIManager
from ui.components.title_scene import TitleScene
from ui.components.button import Button
from ui.components.pet_selector import PetSelector
from ui.components.background import Background
from ui.windows.window_background import WindowBackground
from utils.pygame_utils import rle_accelerate

from core import game_globals, runtime_globals
from training.building_smash import BuildingSmash
from training.digi_mash import DigiMash
from training.digi_whack import DigiWhack
from training.poop_dodge import PoopDodge
from training.shuffle import Shuffle
from training.count_bar_training import CountBarTraining
from training.rpm_training import RPMTraining
from training.count_training import CountMatchTraining
from training.count_classic_training import CountMatchClassicTraining
from training.count_z_training import CountMatchZTraining
from training.dummy_training import DummyTraining
from training.excite_training import ExciteTraining
from training.head_training import HeadToHeadTraining
from training.mogera_training import MogeraTraining
from training.shake_training import ShakeTraining
import core.constants as constants
from utils.pet_utils import get_selected_pets, get_training_targets
from utils.scene_utils import change_scene
from utils.asset_utils import resolve_path
from ui.ui_constants import BASE_RESOLUTION, GREEN

# Gameplay shop item IDs for training modes
TRAINING_GAMEPLAY_IDS = {
    "count_classic": "b2c3d4e5-0002-4000-b000-000000000001",  # Count Match (Classic)
    "count_z": "b2c3d4e5-0002-4000-b000-000000000002",        # Count Match (Z)
    "count": "b2c3d4e5-0002-4000-b000-000000000003",          # Count Match (Color)
    "head": "b2c3d4e5-0002-4000-b000-000000000004",           # Head Charge
    "mogera": "b2c3d4e5-0002-4000-b000-000000000005",         # Mogera
    "excite": "b2c3d4e5-0002-4000-b000-000000000006",         # Xai Bar (Excite)
    "punch": "b2c3d4e5-0002-4000-b000-000000000007",          # Punch
    "count_bar": "b2c3d4e5-0002-4000-b000-000000000008",      # Count Bar
    "rpm": "b2c3d4e5-0002-4000-b000-000000000009",            # RPM
}

#: Every training minigame the menu can offer. The menu orders them itself
#: (``order_training_modes``): ``name`` is what the alphabetical part sorts
#: on, so it follows the label drawn on the button, and ``minigames`` lists the module.json ``battle_minigame`` values that
#: put this one at the front for a pet from that module. Head Charge has no
#: battle counterpart, so no module asks for it. Adding a minigame is one
#: entry here.
TRAINING_MODES = {
    "dummy": {
        "name": "Dummy", "phase": "dummy", "cls": DummyTraining,
        "decorators": ["Dummy"], "minigames": ("Dummy Bar",),
        "min_targets": 1, "cut_corners": {'tl': True},
    },
    "head": {
        "name": "Head to Head", "phase": "headtohead", "cls": HeadToHeadTraining,
        "decorators": ["HeadToHead"], "minigames": (),
        "min_targets": 2, "cut_corners": {'tl': True},
    },
    "count": {
        "name": "Count Match Color", "phase": "count", "cls": CountMatchTraining,
        "decorators": ["CountMatch"], "minigames": ("Count Match Color",),
        "min_targets": 1, "cut_corners": {'tl': True, 'br': True},
    },
    "count_bar": {
        "name": "Count Bar", "phase": "count_bar", "cls": CountBarTraining,
        "decorators": ["CountBar"], "minigames": ("Count Bar",),
        "min_targets": 1, "cut_corners": {},
    },
    # The Digivice iC's. It shares the Count Bar's attack ladder -- the two
    # devices use the same pool of rows -- and differs in the charge: a rate
    # against the Digimon's own RPM target rather than a press count.
    "rpm": {
        "name": "RPM", "phase": "rpm", "cls": RPMTraining,
        "decorators": ["RPM"], "minigames": ("RPM",),
        "min_targets": 1, "cut_corners": {},
    },
    "count_classic": {
        "name": "Count Match Classic", "phase": "count_classic",
        "cls": CountMatchClassicTraining,
        "decorators": ["CountMatch_Classic"], "minigames": ("Count Match Classic",),
        "min_targets": 1, "cut_corners": {'tl': True},
    },
    "count_z": {
        "name": "Count Match Z", "phase": "count_z", "cls": CountMatchZTraining,
        "decorators": ["CountMatch_Z"], "minigames": ("Count Match Z",),
        "min_targets": 1, "cut_corners": {'tl': True},
    },
    "excite": {
        "name": "Excite", "phase": "excite", "cls": ExciteTraining,
        "decorators": ["Excite"], "minigames": ("Xai Bar", "Xai Roll+Bar"),
        "min_targets": 1, "cut_corners": {'tl': True, 'br': True},
    },
    "punch": {
        "name": "Punch", "phase": "punch", "cls": ShakeTraining,
        "decorators": ["Punch"], "minigames": ("Punch",),
        "min_targets": 1, "cut_corners": {},
    },
    "mogera": {
        "name": "Mogera", "phase": "mogera", "cls": MogeraTraining,
        "decorators": ["Mogera"], "minigames": ("Mogera",),
        "min_targets": 1, "cut_corners": {'tl': True, 'br': True},
    },
}

#: The Digivice iC's own minigames, listed under BONUS. On the devices they
#: earn Fight Money rather than train, so they belong to no battle protocol
#: and are never sold: the BONUS button shows while an iC Digimon is in the
#: party, and only iC Digimon play them. Device order, 10X then 20X, under
#: the books' names (Master Book scans 63-64; the 20X booklet pp. 23-24).
#: ``cls`` is None until the minigame is written: its button is there, and
#: choosing it plays the cancel sound. ``label`` stands in for the button
#: art until that exists. The buttons have square corners: their art fills
#: them.
BONUS_MODES = {
    "building_smash": {
        "name": "Building Smash", "label": "BUILDING\nSMASH", "cls": BuildingSmash,
        "decorators": ["BuildingSmash"], "min_targets": 1, "cut_corners": {},
    },
    "poop_dodge": {
        "name": "Poop Dodge", "label": "POOP\nDODGE", "cls": PoopDodge,
        "decorators": ["PoopDodge"], "min_targets": 1, "cut_corners": {},
    },
    "shuffle": {
        "name": "Shuffle", "label": "SHUFFLE", "cls": Shuffle,
        "decorators": ["Shuffle"], "min_targets": 1, "cut_corners": {},
    },
    "digi_whack": {
        "name": "Digi Whack", "label": "DIGI\nWHACK", "cls": DigiWhack,
        "decorators": ["DigiWhack"], "min_targets": 1, "cut_corners": {},
    },
    "digi_mash": {
        "name": "Digi Mash", "label": "DIGI\nMASH", "cls": DigiMash,
        "decorators": ["DigiMash"], "min_targets": 1, "cut_corners": {},
    },
    "gotcha": {
        "name": "Gotcha!", "label": "GOTCHA!", "cls": None,
        "decorators": ["Gotcha"], "min_targets": 1, "cut_corners": {},
    },
}

#: Two rows of three minigames a page; the third row holds MORE/RANDOM/EXIT.
COLUMNS = 3
MODES_PER_PAGE = 6

#: BONUS sits at the top right, level with the title strip (16 high at y 9).
BONUS_BUTTON = (181, 9, 54, 16)


def bonus_targets():
    """The training targets that may play the Bonus minigames: iC Digimon.
    The selected pets (or the whole party when none is selected) that can
    train -- the pets the minigames themselves are played by (ICMinigame)."""
    return [pet for pet in get_training_targets() if is_ic_native(pet)]


def order_training_modes(owned_keys, pets, modules, dummy_first=False):
    """Order the minigames the menu shows.

    The minigames the pets' own modules battle with come first, in the order
    of the pets that ask for them, and everything else follows alphabetically.
    ``dummy_first`` replaces that first part with Dummy alone, which is what
    the tutorial points at.

    Args:
        owned_keys: TRAINING_MODES keys the player may use.
        pets: the pets whose modules decide the front of the list.
        modules: module name -> loaded GameModule.
        dummy_first: put Dummy first and ignore the pets' modules.
    """
    owned = [key for key in TRAINING_MODES if key in owned_keys]
    front = []
    if dummy_first:
        if "dummy" in owned:
            front.append("dummy")
    else:
        for pet in pets:
            module = modules.get(getattr(pet, "module", None))
            minigame = getattr(module, "battle_minigame", None)
            for key in owned:
                if minigame in TRAINING_MODES[key]["minigames"] and key not in front:
                    front.append(key)
    rest = sorted((key for key in owned if key not in front),
                  key=lambda key: TRAINING_MODES[key]["name"].lower())
    return front + rest


#=====================================================================
# SceneTraining (Training Menu)
#=====================================================================

class SceneTraining:
    #: The tutorial shows Dummy first, never pages, and ignores the minigame
    #: last played, so the button it points at is always where it expects.
    TUTORIAL_LAYOUT = False

    def __init__(self) -> None:
        # Use GREEN theme for training
        self.ui_manager = UIManager("GREEN")

        # UI Components for menu phase
        self.background = None
        self.title_scene = None
        self.pet_selector = None
        self.mode_keys = []       # ordered TRAINING_MODES keys on offer
        self.mode_buttons = {}    # key -> Button
        self.dummy_button = None
        self.more_button = None
        self.random_button = None
        self.exit_button = None
        self.prev_page_button = None
        self.next_page_button = None
        self.bonus_button = None
        self.page = 0

        # "main" lists TRAINING_MODES, "bonus" the iC's BONUS_MODES. The
        # Battle scene's Specials hub opens the Bonus list directly, and
        # BACK then returns there (bonus_return: the Battle view and its
        # arguments) instead of to the main list.
        self.view = "main"
        initial_view = runtime_globals.scene_training_initial_view
        self.bonus_return = runtime_globals.training_bonus_return
        runtime_globals.scene_training_initial_view = None
        runtime_globals.training_bonus_return = None

        # Training phase UI components
        self.training_exit_button = None

        # Legacy background for training phase
        self.window_background = WindowBackground(False)

        self.phase = "menu"
        self.mode = None

        # Create static background surface with border for menu phase
        self.static_border_surface = None
        self.create_static_background()

        # Set up modern UI for menu
        self.setup_ui()
        if initial_view == "bonus" and not self.TUTORIAL_LAYOUT:
            self.show_view("bonus")

        runtime_globals.game_console.log("[SceneTraining] Training scene initialized.")

    def owns_training_mode(self, mode_key: str) -> bool:
        """Check if the player owns a training mode.

        Args:
            mode_key: Key for the training mode (e.g., 'count', 'head', 'mogera')

        Returns:
            True if the player owns the training mode, False otherwise.
            Dummy training is always available.
            In Free Mode, all training modes are unlocked.
        """
        if mode_key == "dummy":
            return True  # Dummy is always available

        if game_globals.is_free_mode():
            return True  # Free Mode: all training modes unlocked

        gameplay_id = TRAINING_GAMEPLAY_IDS.get(mode_key)
        if not gameplay_id:
            return False

        return game_globals.purchases.owns_gameplay(gameplay_id)

    def create_static_background(self):
        """Create a static surface with GREEN border around the screen"""
        # Get screen dimensions and UI information
        screen_width, screen_height = runtime_globals.SCREEN_WIDTH, runtime_globals.SCREEN_HEIGHT
        ui_scale = self.ui_manager.ui_scale

        # Calculate border size (2 pixels * ui_scale)
        border_size = 2 * ui_scale

        # Create surface for just the GREEN border
        self.static_border_surface = pygame.Surface((screen_width, screen_height), pygame.SRCALPHA)
        self.static_border_surface.fill((0, 0, 0, 0))  # Transparent

        # Draw GREEN border around the UI area
        for i in range(border_size):
            border_rect = pygame.Rect(0, 0,
                                    screen_width, screen_height)
            pygame.draw.rect(self.static_border_surface, GREEN, border_rect, border_size)

        # Blit position is always (0, 0) since surface covers entire screen
        self.static_border_pos = (0, 0)
        # Transparent but for the border, and blitted every frame: RLE skips
        # the transparent runs (it cost the Pi Zero 2W 17 ms a frame).
        rle_accelerate(self.static_border_surface)

    def setup_ui(self):
        """Setup the UI components for the training menu."""
        try:
            # Use base 240x240 resolution for UI layout
            ui_width = ui_height = BASE_RESOLUTION

            # Create and add the UI background that covers the full UI area
            self.background = Background(ui_width, ui_height)
            # Set single black region covering entire UI
            self.background.set_regions([(0, ui_height, "black")])
            self.ui_manager.add_component(self.background)

            # Create and add the title scene at top left
            self.title_scene = TitleScene(0, 9, "TRAINING")
            self.ui_manager.add_component(self.title_scene)

            # Create and add the pet selector at bottom right (60% of UI width)
            selector_width = int(ui_width * 0.6)  # 60% of UI width
            selector_height = 46
            selector_x = ui_width - selector_width - 5  # Right aligned with margin
            selector_y = ui_height - selector_height - 5  # Bottom aligned with margin

            self.pet_selector = PetSelector(selector_x, selector_y, selector_width, selector_height)
            # Set pets and make it static for now
            self.pet_selector.set_pets(get_training_targets())
            self.pet_selector.set_interactive(False)  # Static display for now
            self.ui_manager.add_component(self.pet_selector)

            # A 3x3 grid of 54x54 buttons: the top two rows are a page of
            # minigames, the bottom row MORE / RANDOM / EXIT.
            self.button_size = 54
            self.button_spacing = 2
            self.start_x = 36  # Left margin
            self.start_y = 25  # Below title

            self.bonus_button = Button(*BONUS_BUTTON, "BONUS", lambda: self.show_view("bonus"))
            self.ui_manager.add_component(self.bonus_button)

            control_y = self._slot_y(2)
            control_corners = {'tl': True, 'tr': False, 'bl': False, 'br': True}
            self.more_button = Button(
                self._slot_x(0), control_y, self.button_size, self.button_size,
                "MORE", self.on_more,
                cut_corners=dict(control_corners)
            )
            self.random_button = Button(
                self._slot_x(1), control_y, self.button_size, self.button_size,
                "RANDOM", self.on_random,
                cut_corners=dict(control_corners)
            )
            self.exit_button = Button(
                self._slot_x(2), control_y, self.button_size, self.button_size,
                "EXIT", self.on_exit_button,
                cut_corners=dict(control_corners)
            )
            for button in (self.more_button, self.random_button, self.exit_button):
                self.ui_manager.add_component(button)

            # Page arrows for mouse and touch, in the margins beside the second
            # row. Joysticks page by pressing past the edge of the grid instead.
            arrow_width = 16
            arrow_y = self._slot_y(1)
            self.prev_page_button = Button(
                self.start_x - self.button_spacing - arrow_width, arrow_y,
                arrow_width, self.button_size,
                "<", lambda: self.change_page(-1)
            )
            self.next_page_button = Button(
                self._slot_x(COLUMNS - 1) + self.button_size + self.button_spacing, arrow_y,
                arrow_width, self.button_size,
                ">", lambda: self.change_page(1)
            )
            for button in (self.prev_page_button, self.next_page_button):
                button.visible = False
                self.ui_manager.add_component(button)

            self.random_button.set_enabled(not self.TUTORIAL_LAYOUT)
            self.show_view("main")

        except Exception as e:
            runtime_globals.game_console.log(f"[SceneTraining] ERROR in setup_ui: {e}")
            import traceback
            runtime_globals.game_console.log(f"[SceneTraining] Traceback: {traceback.format_exc()}")
            raise

    #-----------------------------------------------------------------
    # Main and Bonus lists
    #-----------------------------------------------------------------

    def _modes(self):
        return BONUS_MODES if self.view == "bonus" else TRAINING_MODES

    def _view_keys(self):
        if self.view == "bonus":
            return list(BONUS_MODES)
        owned = [key for key in TRAINING_MODES if self.owns_training_mode(key)]
        return order_training_modes(
            owned, get_selected_pets(), runtime_globals.game_modules,
            dummy_first=self.TUTORIAL_LAYOUT)

    def _bonus_available(self):
        """BONUS shows only when one of the pets that would play is an iC
        Digimon: a non-iC Digimon selected, with an iC one elsewhere in the
        party, could enter none of the minigames (owner, 2026-10-07)."""
        return self.view == "main" and not self.TUTORIAL_LAYOUT and bool(bonus_targets())

    def _update_bonus_button(self):
        show = self._bonus_available()
        if self.bonus_button.visible != show:
            self.bonus_button.needs_redraw = True
        self.bonus_button.visible = self.bonus_button.focusable = show

    def show_view(self, view):
        """Fill the grid with the main list or the Bonus list.

        Each list opens on the minigame last played from it, on whichever
        page that now sits; the Bonus list's BACK replaces EXIT.
        """
        if view == "bonus" and self.view == "main":
            runtime_globals.game_sound.play("menu")
        for button in self.mode_buttons.values():
            self.ui_manager.remove_component(button)
        self.view = view
        self.mode_keys = self._view_keys()
        self.mode_buttons = {}
        for slot, key in enumerate(self.mode_keys):
            button = self._create_mode_button(key, slot % MODES_PER_PAGE)
            self.mode_buttons[key] = button
            self.ui_manager.add_component(button)
        self.dummy_button = self.mode_buttons.get("dummy")

        bonus = view == "bonus"
        self.title_scene.set_text("BONUS" if bonus else "TRAINING")
        self.exit_button.set_text("BACK" if bonus else "EXIT")
        self._update_bonus_button()
        self.more_button.set_enabled(self._paging_enabled())

        focus_key = None if self.TUTORIAL_LAYOUT else self._remembered_focus()
        if focus_key not in self.mode_buttons:
            focus_key = self.mode_keys[0] if self.mode_keys else None
        self.page = self.mode_keys.index(focus_key) // MODES_PER_PAGE if focus_key else 0
        self._apply_page()
        if focus_key:
            self.ui_manager.set_focused_component(self.mode_buttons[focus_key])
        self._update_page_arrows()
        runtime_globals.game_console.log(
            f"[SceneTraining] {view} list: {len(self.mode_keys)} minigames "
            f"over {self._page_count()} page(s): {self.mode_keys}")

    def _remembered_focus(self):
        if self.view == "bonus":
            return runtime_globals.training_bonus_focus
        return runtime_globals.training_focus

    def _remember_focus(self, key):
        if self.TUTORIAL_LAYOUT:
            return
        if self.view == "bonus":
            runtime_globals.training_bonus_focus = key
        else:
            runtime_globals.training_focus = key

    def on_exit_button(self):
        """EXIT leaves the scene; on the Bonus list it reads BACK."""
        if self.view == "bonus" and not self.mode:
            runtime_globals.game_sound.play("cancel")
            self.leave_bonus()
            return
        else:
            self.on_exit_training()

    def leave_bonus(self):
        """Back to wherever the Bonus list was opened from."""
        self._save_training_focus()
        if self.bonus_return:
            runtime_globals.scene_battle_initial_view = self.bonus_return
            change_scene("battle")
        else:
            self.show_view("main")

    #-----------------------------------------------------------------
    # Pages
    #-----------------------------------------------------------------

    def _slot_x(self, column):
        return self.start_x + column * (self.button_size + self.button_spacing)

    def _slot_y(self, row):
        return self.start_y + row * (self.button_size + self.button_spacing)

    def _create_mode_button(self, key, slot):
        """Build a minigame's button at its slot on whichever page it is on.

        A Bonus minigame whose button art is not drawn yet shows its label.
        """
        spec = self._modes()[key]
        decorators = list(spec["decorators"])
        if key == "excite":
            # Excite also shows the current XAI number
            decorators.append(f"Xai_{game_globals.xai}")
        text = ""
        if "label" in spec and not all(
                os.path.exists(resolve_path(f"assets/ui/Training_{name}_1.png"))
                for name in decorators):
            text, decorators = spec["label"], []
        return Button(
            self._slot_x(slot % COLUMNS), self._slot_y(slot // COLUMNS),
            self.button_size, self.button_size,
            text, lambda k=key: self.select_training(k),
            cut_corners=dict(spec["cut_corners"]),
            decorators=decorators
        )

    def _page_count(self):
        return max(1, -(-len(self.mode_keys) // MODES_PER_PAGE))

    def _paging_enabled(self):
        return self._page_count() > 1 and not self.TUTORIAL_LAYOUT

    def _page_keys(self, page=None):
        page = self.page if page is None else page
        return self.mode_keys[page * MODES_PER_PAGE:(page + 1) * MODES_PER_PAGE]

    def _apply_page(self):
        """Show the current page's minigames and hide every other page's."""
        visible = set(self._page_keys())
        for key, button in self.mode_buttons.items():
            button.visible = key in visible
            button.needs_redraw = True

    def _update_page_arrows(self):
        """The arrows are for pointers only, and only when there is a page to go to."""
        pointer = runtime_globals.INPUT_MODE in (runtime_globals.MOUSE_MODE,
                                                 runtime_globals.TOUCH_MODE)
        show = pointer and self._paging_enabled()
        for button in (self.prev_page_button, self.next_page_button):
            if button and button.visible != show:
                button.visible = show
                button.needs_redraw = True

    def _focused_component(self):
        idx = self.ui_manager.focused_index
        components = self.ui_manager.focusable_components
        return components[idx] if 0 <= idx < len(components) else None

    def _focused_mode_key(self):
        focused = self._focused_component()
        for key, button in self.mode_buttons.items():
            if button is focused:
                return key
        return None

    def change_page(self, step, row=None, column=None):
        """Turn ``step`` pages, wrapping round at either end.

        A minigame that had the focus hands it to the one at the same place on
        the new page — or to ``row``/``column`` when given — so the focus never
        sits on a button that is no longer drawn. Anything else keeps it, so
        MORE and the arrows can be pressed again.
        """
        if not self._paging_enabled():
            runtime_globals.game_sound.play("cancel")
            return False

        focused_key = self._focused_mode_key()
        if focused_key is not None:
            slot = self.mode_keys.index(focused_key) % MODES_PER_PAGE
            row = slot // COLUMNS if row is None else row
            column = slot % COLUMNS if column is None else column

        self.page = (self.page + step) % self._page_count()
        self._apply_page()
        runtime_globals.game_sound.play("menu")

        if focused_key is not None:
            page_keys = self._page_keys()
            row_keys = page_keys[row * COLUMNS:(row + 1) * COLUMNS]
            if row_keys:
                target = row_keys[min(column, len(row_keys) - 1)]
            else:
                target = page_keys[min(row * COLUMNS + column, len(page_keys) - 1)]
            self.ui_manager.set_focused_component(self.mode_buttons[target])
        return True

    def _page_at_edge(self, direction):
        """LEFT/RIGHT past the edge of the grid turns the page.

        The edge is the first column going left, and going right the last
        button in its row — a short row ends early, and there is nothing
        further right to move to.
        """
        key = self._focused_mode_key()
        if key is None or not self._paging_enabled():
            return False
        index = self.mode_keys.index(key)
        slot = index % MODES_PER_PAGE
        row, column = divmod(slot, COLUMNS)
        if direction == "LEFT" and column == 0:
            return self.change_page(-1, row=row, column=COLUMNS - 1)
        if direction == "RIGHT" and (column == COLUMNS - 1 or index == len(self.mode_keys) - 1):
            return self.change_page(1, row=row, column=0)
        return False

    def on_more(self):
        """MORE turns to the next page, back round to the first after the last."""
        self.change_page(1)

    def on_random(self):
        """RANDOM starts any minigame on the list the current pets are able to play."""
        modes = self._modes()
        targets = len(self._targets())
        playable = [key for key in self.mode_keys
                    if targets >= modes[key]["min_targets"] and modes[key]["cls"] is not None]
        if not playable:
            runtime_globals.game_sound.play("cancel")
            return
        key = random.choice(playable)
        runtime_globals.game_console.log(f"[SceneTraining] Random picked {modes[key]['name']}")
        self.select_training(key)

    #-----------------------------------------------------------------
    # Menu visibility
    #-----------------------------------------------------------------

    def _menu_components(self):
        return [*self.mode_buttons.values(), self.more_button, self.random_button,
                self.exit_button, self.prev_page_button, self.next_page_button,
                self.bonus_button, self.pet_selector, self.title_scene, self.background]

    def hide_menu_buttons(self):
        """Hide all menu buttons when entering training phase."""
        for component in self._menu_components():
            if component is not None:
                component.visible = False
                component.focusable = False

    def show_menu_buttons(self):
        """Show the menu again, on the page it was left on."""
        for component in (self.pet_selector, self.title_scene, self.background):
            if component is not None:
                component.visible = True
        for button in (*self.mode_buttons.values(), self.more_button, self.random_button,
                       self.exit_button, self.prev_page_button, self.next_page_button):
            if button is not None:
                button.visible = True
                # A disabled button stays out of the focus order.
                button.focusable = button.enabled
        self._update_bonus_button()
        self._apply_page()
        self._update_page_arrows()

    #-----------------------------------------------------------------
    # Starting a minigame
    #-----------------------------------------------------------------

    def select_training(self, key):
        """A minigame was chosen, from its button or by RANDOM.

        Remembered and focused before it starts, so the menu comes back to it
        — on its own page — whether the player backs out of the minigame or
        finishes it and returns to the scene later.
        """
        if key not in self.mode_buttons:
            return
        self._remember_focus(key)
        self.page = self.mode_keys.index(key) // MODES_PER_PAGE
        self._apply_page()
        self.ui_manager.set_focused_component(self.mode_buttons[key])
        if key == "dummy":
            self.on_dummy_training()  # the tutorial substitutes its own
        else:
            self.start_training(key)

    def on_dummy_training(self):
        """Handle Dummy training button press."""
        self.start_training("dummy")

    def _targets(self):
        """The pets the current list's minigames are played by."""
        return bonus_targets() if self.view == "bonus" else get_training_targets()

    def _sync_pet_selector(self):
        """Show the current targets in the pet row, only when they changed.

        set_pets lays the row out again and marks it for redraw, which
        rebuilds the whole menu's cached surface: done every frame it cost
        the Pi Zero 2W about 30 ms a frame (19 fps). The row draws each pet's
        idle or nap frame, so a pet falling asleep or evolving counts as a
        change.
        """
        targets = self._targets()
        key = [(id(pet), getattr(pet, "name", None), getattr(pet, "state", None) == "nap")
               for pet in targets]
        if key != getattr(self, "_pet_selector_key", None):
            self._pet_selector_key = key
            self.pet_selector.set_pets(targets)

    def start_training(self, key):
        """Hand the screen to a minigame, if enough pets can train for it."""
        spec = self._modes()[key]
        targets = self._targets()
        if len(targets) < spec["min_targets"]:
            runtime_globals.game_sound.play("cancel")
            return
        if spec["cls"] is None:
            runtime_globals.game_sound.play("cancel")
            runtime_globals.game_console.log(f"[SceneTraining] {spec['name']} is not playable yet.")
            return
        runtime_globals.game_sound.play("menu")
        self.hide_menu_buttons()
        self.phase = spec.get("phase", key)
        self.mode = spec["cls"](self.ui_manager)
        self.create_training_exit_button()  # Create exit button for training phase
        runtime_globals.game_console.log(f"Starting {spec['name']} Training.")
        for pet in targets:
            pet.check_disturbed_sleep()
        # Entering a training moves the Godzilla devices' encounter rotation on.
        from utils.event_utils import advance_rotation
        advance_rotation(targets)

    def on_exit_training(self):
        """Handle EXIT button press."""
        if self.mode:
            if getattr(self.mode, "phase", None) == "alert":
                return
            runtime_globals.game_sound.play("cancel")
            self.mode.handle_event(("B", None))
        else:
            runtime_globals.game_sound.play("cancel")
            self._save_training_focus()
            change_scene("game")

    def on_training_exit(self):
        """Handle training exit button press - send B key to current training mode."""
        if self.mode:
            if getattr(self.mode, "phase", None) == "alert":
                return
            self.mode.handle_event(("B", None))

    def create_training_exit_button(self):
        """Create the exit button for training phases using screen coordinates."""
        if not self.training_exit_button:
            # Calculate screen position (top right corner with margin)
            button_size = 30  # 30x30 at 1x scale
            margin = 10

            # Position at top right corner of screen
            screen_x = 10 + margin
            screen_y = margin

            self.training_exit_button = Button(
                0, 0, button_size, button_size,  # Base size, position will be set via screen coords
                "", self.on_training_exit,
                decorators=["ExitButton_Green"],
                shadow_mode="full"
            )

            # Enable screen coordinates and set position
            self.training_exit_button.use_screen_coordinates = True
            self.ui_manager.add_component(self.training_exit_button)

            # Set screen position after adding to manager (so scaling is applied)
            self.training_exit_button.set_screen_coordinates(True, screen_x, screen_y)
            self.training_exit_button.focusable = True

    def remove_training_exit_button(self):
        """Remove the training exit button."""
        if self.training_exit_button:
            # Remove from UI manager components list and focusable list
            if self.training_exit_button in self.ui_manager.components:
                self.ui_manager.components.remove(self.training_exit_button)
            if self.training_exit_button in self.ui_manager.focusable_components:
                self.ui_manager.focusable_components.remove(self.training_exit_button)
            self.training_exit_button = None

    def update(self):
        if self.phase == "menu":
            # The input mode can change at any time; the arrows follow it.
            self._update_page_arrows()
            # Update UI manager for menu phase
            self.ui_manager.update()
            # Update pet selector with current targets (the Bonus list's are
            # its iC Digimon)
            if self.pet_selector:
                self._sync_pet_selector()
            # A pet that can no longer train (asleep, sick...) takes BONUS
            # with it.
            if self.bonus_button:
                self._update_bonus_button()

        elif self.mode:
            self.mode.update()

            # Update the training exit button if it exists
            if self.training_exit_button:
                self.training_exit_button.update()

            # Check if training mode completed and return to menu
            if hasattr(self.mode, 'phase') and self.mode.phase == "exit":
                self.phase = "menu"
                self.mode = None
                self.remove_training_exit_button()
                self.show_menu_buttons()

    def draw(self, surface: pygame.Surface):
        # Always draw the window background first (all states)
        self.window_background.draw(surface)

        # Draw the GREEN border on top
        surface.blit(self.static_border_surface, self.static_border_pos)

        if self.phase == "menu":
            # Draw UI components on top
            self.ui_manager.draw(surface)

        elif self.mode:
            # Use legacy system for training phases
            self.mode.draw(surface)

            # Draw training exit button AFTER training mode so it appears on top
            # Only draw it during phases where we want it visible (not alert/impact which cover full screen)
            if (self.training_exit_button and
                (runtime_globals.INPUT_MODE == runtime_globals.MOUSE_MODE or runtime_globals.INPUT_MODE == runtime_globals.TOUCH_MODE) and
                self.mode.phase not in ["alert", "impact", "result", "currency"]):
                self.training_exit_button.draw(surface)

    def plays_own_input_sounds(self):
        """A running minigame reads presses as play (dispatch_input leaves it be)."""
        return self.phase != "menu" and self.mode is not None

    def handle_event(self, event):
        if self.phase == "menu":
            self.handle_menu_input(event)
        elif self.mode:
            # READY is non-skippable: do not let exit controls, buffered
            # minigame actions, or hidden UI components consume alert input.
            if getattr(self.mode, "phase", None) == "alert":
                return
            # The currency screen after any minigame's result: a button
            # moves on, whatever the minigame does with its own input.
            if getattr(self.mode, "phase", None) == "currency":
                if event[0] in ("A", "B", "START", "LCLICK"):
                    self.mode.finish_training()
                return

            # Only route click events to the UIManager when the click actually lands
            # on the exit button's rect.  Routing all events (including A keypresses
            # and off-target clicks) would let the focused exit button steal inputs
            # that should go to the active training minigame.
            if self.training_exit_button and (runtime_globals.INPUT_MODE == runtime_globals.MOUSE_MODE or runtime_globals.INPUT_MODE == runtime_globals.TOUCH_MODE):
                event_type, event_data = event
                if event_type == "LCLICK" and event_data and "pos" in event_data:
                    if self.training_exit_button.rect.collidepoint(event_data["pos"]):
                        if self.ui_manager.handle_event(event):
                            return  # Exit button consumed the click

            # Pass event to training mode
            self.mode.handle_event(event)

    def _save_training_focus(self):
        """Remember the focused minigame, if one is focused, for the next visit."""
        key = self._focused_mode_key()
        if key:
            self._remember_focus(key)

    def handle_menu_input(self, event):
        event_type, event_data = event

        # Pressing past the edge of the grid turns the page; this has to come
        # before the UI manager, which would move the focus instead.
        if event_type in ("LEFT", "RIGHT") and self._page_at_edge(event_type):
            return

        # Handle pygame events through UI manager first
        if self.ui_manager.handle_event(event):
            return

        # The wheel turns pages: up for the previous one, down for the next.
        if event_type == "SCROLL" and event_data and self._paging_enabled():
            self.change_page(-1 if event_data.get("direction") == "UP" else 1)
            return

        # Handle string action events (from input manager)
        if event_type == "B":
            runtime_globals.game_sound.play("cancel")
            if self.view == "bonus":
                self.leave_bonus()
                return
            self._save_training_focus()
            change_scene("game")
            return
