
"""
Scene Settings Menu
Hierarchical settings menu with sections and sub-options.
Sections: Gameplay, Display, Audio, Input, Backgrounds, Secrets.
B button returns to parent section or exits to game from top level.
Uses OptionRow components that support keyboard LEFT/RIGHT and clickable arrows.
"""

# Standard library imports
import datetime

# Third-party imports
import pygame

# Project imports
from core import game_globals, runtime_globals
from utils.scene_utils import change_scene
from utils.utils_unlocks import get_unlocked_backgrounds, is_unlocked

from ui.ui_manager import UIManager
from ui.components.background import Background
from ui.components.title_scene import TitleScene
from ui.components.button import Button
from ui.components.option_row import OptionRow
from ui.ui_constants import BASE_RESOLUTION, YELLOW_BRIGHT
from ui.windows.window_background import WindowBackground
from ui.components.label import Label


# ---------------------------------------------------------------------------
# Section / option definitions
# ---------------------------------------------------------------------------

def _get_sections():
    """Return ordered section definitions (built at scene init time)."""
    cfg = game_globals.configuration

    _SCREEN_TIMEOUT_CHOICES = [0, 10, 20, 30, 60, 120]
    _SPRITE_LABELS = {0: "Default", 1: "Color", 2: "HD"}

    def _cycle_timeout(increase):
        cur = cfg.screen_timeout
        try:
            idx = _SCREEN_TIMEOUT_CHOICES.index(cur)
        except ValueError:
            idx = 0
        idx = (idx + (1 if increase else -1)) % len(_SCREEN_TIMEOUT_CHOICES)
        cfg.screen_timeout = _SCREEN_TIMEOUT_CHOICES[idx]

    def _cycle_volume(increase):
        v = cfg.sound_volume + (1 if increase else -1)
        cfg.sound_volume = v % 11

    def _cycle_max_pets(increase):
        v = cfg.max_pets + (1 if increase else -1)
        new_value = max(1, min(10, v))
        if new_value == cfg.max_pets:
            return
        cfg.max_pets = new_value
        # PET_WIDTH/HEIGHT derive from max_pets — recompute immediately and
        # reload the cached pet sprites so the change doesn't need a reboot.
        # The resolution in force is passed explicitly: on Android it is half
        # the device's and is NOT what the configuration holds, so a
        # no-argument call would resize the whole render surface here.
        from core import runtime_globals as rg
        from core import game_globals
        rg.update_resolution_constants(rg.SCREEN_WIDTH, rg.SCREEN_HEIGHT)
        rg.pet_sprites = {}
        for pet in game_globals.pet_list:
            try:
                pet.load_sprite()
            except Exception as exc:
                rg.game_console.log(f"[Settings] pet sprite reload failed: {exc}")
        try:
            from utils.pet_utils import distribute_pets_evenly
            distribute_pets_evenly()
        except Exception as exc:
            rg.game_console.log(f"[Settings] pet reposition failed: {exc}")

    def _cycle_render_res(increase):
        # Render Res = the 1x-4x internal-resolution multiplier.  Clamp (no
        # wrap) between 1x and 4x.  apply_render_multiplier recomputes the
        # internal resolution proportional to the window and rescales the
        # canvas live; the scene rebuilds its UI when the scale changes
        # (see SceneSettingsMenu.update).
        from utils import display_utils
        cur = max(1, min(4, int(round(cfg.resolution_multiplyer or 1))))
        new = max(1, min(4, cur + (1 if increase else -1)))
        if new == cur:
            return
        display_utils.apply_render_multiplier(new)

    def _cycle_sprite_pref(increase):
        v = cfg.sprite_resolution_preference + (1 if increase else -1)
        cfg.sprite_resolution_preference = v % 3
        # Clear sprite cache when preference changes so new sprites will reload
        runtime_globals.pet_sprites = {}
        runtime_globals.game_console.log("[Settings] Sprite preference changed, cache cleared")
    
    def _toggle_old_sprites(increase):
        """Toggle between old sprite loading (with fallback) and new priority-based loading."""
        cfg.enable_old_sprites = not cfg.enable_old_sprites
        # Clear sprite cache when setting changes so new sprites will reload
        runtime_globals.pet_sprites = {}
        runtime_globals.game_console.log(f"[Settings] Old sprites set to {cfg.enable_old_sprites}, cache cleared")

    def _fmt_time(t):
        if t is None:
            return "Off"
        return t.strftime("%H:%M")

    def _change_time(current, increase, start_hour, end_hour, is_sleep=False):
        time_slots = []
        if is_sleep:
            time_slots.append(datetime.time(12, 30))
            for hour in range(13, 24):
                time_slots.append(datetime.time(hour, 0))
                time_slots.append(datetime.time(hour, 30))
            time_slots.append(datetime.time(0, 0))
        else:
            time_slots.append(datetime.time(0, 30))
            for hour in range(1, end_hour + 1):
                time_slots.append(datetime.time(hour, 0))
                if hour < end_hour:
                    time_slots.append(datetime.time(hour, 30))
        if not time_slots:
            return None
        if current is None:
            return time_slots[0] if increase else None
        try:
            current_idx = time_slots.index(current)
        except ValueError:
            cur_dt = datetime.datetime(2000, 1, 1, current.hour, current.minute)
            current_idx = min(range(len(time_slots)),
                              key=lambda i: abs((datetime.datetime(2000, 1, 1, time_slots[i].hour, time_slots[i].minute) - cur_dt).total_seconds()))
        new_idx = current_idx + (1 if increase else -1)
        if new_idx < 0 or new_idx >= len(time_slots):
            return None
        return time_slots[new_idx]

    def _cycle_wake(increase):
        cfg.wake_time = _change_time(cfg.wake_time, increase, 0, 12, is_sleep=False)

    def _cycle_sleep(increase):
        cfg.sleep_time = _change_time(cfg.sleep_time, increase, 12, 0, is_sleep=True)

    main_options = [
        {"key": "gameplay",     "label": "Gameplay",     "type": "action"},
        {"key": "display",      "label": "Display",      "type": "action"},
        {"key": "audio",        "label": "Audio",        "type": "action"},
        {"key": "input",        "label": "Input",        "type": "action"},
        {"key": "background",   "label": "Backgrounds",  "type": "action"},
        {"key": "unlockables",  "label": "Secrets",      "type": "action"},
    ]
    if runtime_globals.IS_ANDROID:
        main_options.append({"key": "system", "label": "System", "type": "action"})

    sections = [
        {
            "key": "main",
            "title": "SETTINGS",
            "options": main_options,
        },
        {
            "key": "gameplay",
            "title": "GAMEPLAY",
            "options": [
                {"key": "max_pets",      "label": "Max Pets",      "type": "cycle",
                 "get": lambda: str(cfg.max_pets),
                 "set": _cycle_max_pets},
                {"key": "global_wake",   "label": "Wake",          "type": "cycle",
                 "get": lambda: _fmt_time(cfg.wake_time),
                 "set": _cycle_wake},
                {"key": "global_sleep",  "label": "Sleep",         "type": "cycle",
                 "get": lambda: _fmt_time(cfg.sleep_time),
                 "set": _cycle_sleep},
                {"key": "game_mode",     "label": "Change Mode",   "type": "action"},
                {"key": "replay_tutorial", "label": "Replay Tutorial", "type": "action"},
            ],
        },
        {
            "key": "display",
            "title": "DISPLAY",
            "options": [
                {"key": "render_res",   "label": "Render Res",    "type": "cycle",
                 "get": lambda: f"{max(1, min(4, int(round(cfg.resolution_multiplyer or 1))))}x",
                 "set": _cycle_render_res},
                {"key": "window_size",  "label": "Window Size",   "type": "action",
                 "enabled": not cfg.fullscreen},
                {"key": "show_clock",    "label": "Show Clock",    "type": "toggle",
                 "get": lambda: "ON" if game_globals.showClock else "OFF",
                 "set": lambda inc: setattr(game_globals, 'showClock', not game_globals.showClock)},
                {"key": "show_fps",      "label": "Show FPS",      "type": "toggle",
                 "get": lambda: "ON" if cfg.show_fps else "OFF",
                 "set": lambda inc: setattr(cfg, 'show_fps', not cfg.show_fps)},
                {"key": "screen_timeout","label": "Timeout",       "type": "cycle",
                 "get": lambda: "OFF" if cfg.screen_timeout == 0 else f"{cfg.screen_timeout}s",
                 "set": _cycle_timeout},
                {"key": "sprite_pref",   "label": "Sprites",       "type": "cycle",
                 "get": lambda: _SPRITE_LABELS.get(cfg.sprite_resolution_preference, "Default"),
                 "set": _cycle_sprite_pref},
                {"key": "old_sprites",   "label": "Old Sprites",    "type": "toggle",
                 "get": lambda: "ON" if cfg.enable_old_sprites else "OFF",
                 "set": _toggle_old_sprites},
            ],
        },
        {
            "key": "audio",
            "title": "AUDIO",
            "options": [
                {"key": "volume",  "label": "Volume",  "type": "cycle",
                 "get": lambda: f"{cfg.sound_volume * 10}%",
                 "set": _cycle_volume},
            ],
        },
        {
            "key": "input",
            "title": "INPUT",
            "options": [
                {"key": "remap_input",    "label": "Remap Input",    "type": "action"},
                {"key": "test_graphics",  "label": "Test Graphics",  "type": "action"},
            ],
        },
    ]
    if runtime_globals.IS_ANDROID:
        from services import android_progress
        sections.append({
            "key": "system", "title": "SYSTEM", "options": [
                {"key": "notification_status", "label": "Notifications", "type": "cycle",
                 "get": android_progress.notification_status, "set": lambda inc: None},
                {"key": "notification_settings", "label": "Notification Settings", "type": "action"},
            ],
        })
    return {s["key"]: s for s in sections}


class SceneSettingsMenu:
    """Hierarchical settings menu with section-based navigation."""

    def __init__(self) -> None:
        self.window_background = WindowBackground(False)

        self.ui_manager = UIManager(theme="GRAY")
        self.ui_manager.set_input_manager(runtime_globals.game_input)

        self.sections = _get_sections()
        self.nav_stack = ["main"]

        # Unlockables / background state
        self.unlockables_data = []
        self.current_unlock_module_index = 0
        self.current_unlock_item_index = 0

        self.unlocked_backgrounds = []
        for module in runtime_globals.game_modules.values():
            for bg in get_unlocked_backgrounds(module.name, getattr(module, "backgrounds", [])):
                self.unlocked_backgrounds.append((module.name, bg["name"], bg.get("label", bg["name"])))
        # Shop-purchased backgrounds — surfaced through the synthetic
        # "shop" module name so the selector can render them alongside
        # per-module backgrounds without a deeper refactor.
        for bg in (getattr(game_globals, 'shop_backgrounds', None) or {}).values():
            name = bg.get('name') or bg.get('id', '')
            label = bg.get('label', name)
            self.unlocked_backgrounds.append(("shop", name, label))
        self.current_bg_index = self._get_current_background_index()

        # Persistent components
        self.ui_background = Background(BASE_RESOLUTION, BASE_RESOLUTION)
        self.ui_background.set_regions([(0, BASE_RESOLUTION, "black")])
        self.ui_manager.add_component(self.ui_background)

        self.title_scene = TitleScene(0, 9, "SETTINGS")
        self.ui_manager.add_component(self.title_scene)

        # Dynamic components for the current view
        self._dynamic_components = []
        self._option_rows = []  # OptionRow references for the current section

        # Background-mode components
        self._bg_name_label = None
        self._bg_highres_label = None
        self._bg_left_button = None
        self._bg_right_button = None
        self._bg_select_button = None
        self._bg_back_button = None
        self._bg_instruction_labels = []

        # Unlockables-mode components
        self._unlock_header_label = None
        self._unlock_item_labels = []
        self._unlock_left_button = None
        self._unlock_right_button = None
        self._unlock_back_button = None
        self._unlock_up_button = None
        self._unlock_down_button = None
        self._unlock_instruction_labels = []

        # Window-size dialog state
        self._winsize_presets = []
        self._winsize_index = 0
        self._winsize_label = None

        self._load_unlockables()
        self._build_section_view()

        runtime_globals.game_console.log("[SceneSettingsMenu] Initialized (GRAY theme, OptionRow).")

    # ------------------------------------------------------------------
    # View builders
    # ------------------------------------------------------------------

    def _clear_dynamic(self):
        for comp in self._dynamic_components:
            self.ui_manager.remove_component(comp)
        self._dynamic_components.clear()
        self._option_rows = []
        self._bg_name_label = None
        self._bg_highres_label = None
        self._bg_left_button = None
        self._bg_right_button = None
        self._bg_select_button = None
        self._bg_back_button = None
        self._bg_instruction_labels = []
        self._unlock_header_label = None
        self._unlock_item_labels = []
        self._unlock_left_button = None
        self._unlock_right_button = None
        self._unlock_back_button = None
        self._unlock_up_button = None
        self._unlock_down_button = None
        self._unlock_instruction_labels = []
        self._winsize_label = None

    def _add_dynamic(self, comp):
        self._dynamic_components.append(comp)
        self.ui_manager.add_component(comp)

    def _current_section_key(self):
        return self.nav_stack[-1]

    def _build_section_view(self):
        self._clear_dynamic()
        key = self._current_section_key()
        if key == "background":
            self._build_background_view()
        elif key == "unlockables":
            self._build_unlockables_view()
        elif key == "window_size":
            self._build_window_size_view()
        else:
            self._build_option_list_view(key)

    # ------------------------------------------------------------------
    # Generic option list (uses OptionRow)
    # ------------------------------------------------------------------

    def _build_option_list_view(self, section_key):
        section = self.sections.get(section_key)
        if not section:
            return
        self.title_scene.set_text(section["title"])

        row_width = 224
        start_x = 8
        start_y = 40
        # Auto-tighten the row layout when the list would overlap the
        # bottom-right BACK button (which sits at y >= 202).  Without
        # this the 7th row in the main settings (Android-only "System"
        # entry) draws under the BACK button.
        bottom_limit = BASE_RESOLUTION - 40   # leave room for BACK
        opts = section["options"]
        available = bottom_limit - start_y
        per_row = max(20, available // max(len(opts), 1))
        per_row = min(per_row, 26)
        row_height = per_row - 2
        row_spacing = 2
        self._option_rows = []
        self._option_defs = opts

        for i, opt in enumerate(self._option_defs):
            y = start_y + i * (row_height + row_spacing)
            row = OptionRow(
                start_x, y, row_width, row_height,
                label=opt["label"],
                option_type=opt["type"],
                get_value=opt.get("get"),
                set_value=opt.get("set"),
                on_activate=lambda o=opt: self._on_option_activate(o),
                cut_corners={"tl": True, "tr": False, "bl": False, "br": True},
                enabled=opt.get("enabled", True),
            )
            self._option_rows.append(row)
            self._add_dynamic(row)

        if self._option_rows:
            self.ui_manager.set_focused_component(self._option_rows[0])

        # Back button (mouse/touch only; keyboard/gamepad users use the B button)
        back_btn = Button(
            BASE_RESOLUTION - 68, BASE_RESOLUTION - 38, 60, 28,
            "BACK", self._go_back,
        )
        back_btn.visible = self._mouse_enabled()
        self._add_dynamic(back_btn)

    def _refresh_option_texts(self):
        for row in self._option_rows:
            row.needs_redraw = True

    # ------------------------------------------------------------------
    # Background view
    # ------------------------------------------------------------------

    def _build_background_view(self):
        self.title_scene.set_text("BACKGROUND")
        self.ui_background.visible = False
        self.current_bg_index = self._get_current_background_index()

        self._bg_name_label = Label(6, 80, "", shadow_mode="full", is_title=True, color_override=YELLOW_BRIGHT)
        self._add_dynamic(self._bg_name_label)

        self._bg_highres_label = Label(6, 110, "", shadow_mode="full")
        self._add_dynamic(self._bg_highres_label)

        mouse = self._mouse_enabled()
        nav_y = 200
        nw, nh, ns = 52, 32, 6
        lx = 6

        self._bg_left_button = Button(lx, nav_y, nw, nh, "", lambda: self._change_background(False), icon_name="Left", icon_prefix="Settings")
        self._bg_left_button.visible = mouse
        self._add_dynamic(self._bg_left_button)

        rx = lx + nw + ns
        self._bg_right_button = Button(rx, nav_y, nw, nh, "", lambda: self._change_background(True), icon_name="Right", icon_prefix="Settings")
        self._bg_right_button.visible = mouse
        self._add_dynamic(self._bg_right_button)

        sx = rx + nw + ns
        self._bg_select_button = Button(sx, nav_y, nw, nh, "SEL", self._toggle_highres)
        self._bg_select_button.visible = mouse
        self._add_dynamic(self._bg_select_button)

        bx = sx + nw + ns
        self._bg_back_button = Button(bx, nav_y, nw, nh, "BACK", self._go_back)
        self._bg_back_button.visible = mouse
        self._add_dynamic(self._bg_back_button)

        self._bg_instruction_labels = []
        instr_y = nav_y + 2
        for i, txt in enumerate(["LEFT/RIGHT: Change", "SELECT: Hi-Res", "B: Back"]):
            lbl = Label(6, instr_y + i * 10, txt, shadow_mode="full")
            lbl.visible = not mouse
            self._bg_instruction_labels.append(lbl)
            self._add_dynamic(lbl)

        self._update_background_labels()

    def _update_background_labels(self):
        if self.unlocked_backgrounds and self._bg_name_label:
            _, name, label = self.unlocked_backgrounds[self.current_bg_index]
            self._bg_name_label.set_text(label)
            self._bg_highres_label.set_text(f"High-Res: {'ON' if game_globals.background_high_res else 'OFF'}")

    def _change_background(self, increase):
        if not self.unlocked_backgrounds:
            return
        self.current_bg_index = (self.current_bg_index + (1 if increase else -1)) % len(self.unlocked_backgrounds)
        mod, name, label = self.unlocked_backgrounds[self.current_bg_index]
        game_globals.game_background = name
        game_globals.background_module_name = mod
        self.window_background.load_sprite(False)
        self._update_background_labels()

    def _toggle_highres(self):
        game_globals.background_high_res = not game_globals.background_high_res
        self.window_background.load_sprite(False)
        runtime_globals.game_sound.play("menu")
        self._update_background_labels()

    def _get_current_background_index(self):
        if not game_globals.game_background:
            return 0
        for i, (mod, name, _) in enumerate(self.unlocked_backgrounds):
            if name == game_globals.game_background and mod == game_globals.background_module_name:
                return i
        return 0

    # ------------------------------------------------------------------
    # Unlockables / Secrets view
    # ------------------------------------------------------------------

    def _build_unlockables_view(self):
        self.title_scene.set_text("SECRETS")

        self._unlock_header_label = Label(0, 40, "", shadow_mode="full", color_override=YELLOW_BRIGHT)
        self._add_dynamic(self._unlock_header_label)

        self._unlock_item_labels = []
        for i in range(5):
            lbl = Label(20, 70 + i * 25, "", shadow_mode="full")
            self._unlock_item_labels.append(lbl)
            self._add_dynamic(lbl)

        mouse = self._mouse_enabled()
        nav_y = 200
        nw, nh, ns = 52, 32, 6

        self._unlock_left_button = Button(6, nav_y, nw, nh, "", self._unlockables_prev_module, icon_name="Left", icon_prefix="Settings")
        self._unlock_left_button.visible = mouse
        self._add_dynamic(self._unlock_left_button)

        self._unlock_right_button = Button(6 + nw + ns, nav_y, nw, nh, "", self._unlockables_next_module, icon_name="Right", icon_prefix="Settings")
        self._unlock_right_button.visible = mouse
        self._add_dynamic(self._unlock_right_button)

        self._unlock_back_button = Button(BASE_RESOLUTION - nw - 6, nav_y, nw, nh, "BACK", self._go_back)
        self._unlock_back_button.visible = mouse
        self._add_dynamic(self._unlock_back_button)

        # Scroll the list by touch or mouse too (UP/DOWN and the wheel do it
        # from keys): past the first five names nothing else showed them.
        aw = 26
        ax = 6 + 2 * nw + 2 * ns
        self._unlock_up_button = Button(ax, nav_y, aw, nh, "", lambda: self._scroll_unlockables(-1),
                                        decorators=["ArrowUp"])
        self._unlock_up_button.visible = mouse
        self._add_dynamic(self._unlock_up_button)
        self._unlock_down_button = Button(ax + aw + 2, nav_y, aw, nh, "", lambda: self._scroll_unlockables(1),
                                          decorators=["ArrowDown"])
        self._unlock_down_button.visible = mouse
        self._add_dynamic(self._unlock_down_button)

        self._unlock_instruction_labels = []
        instr_y = nav_y + 2
        for i, txt in enumerate(["LEFT/RIGHT: Module", "UP/DOWN: Scroll", "B: Back"]):
            lbl = Label(6, instr_y + i * 10, txt, shadow_mode="full")
            lbl.visible = not mouse
            self._unlock_instruction_labels.append(lbl)
            self._add_dynamic(lbl)

        self._update_unlockables_labels()

    def _update_unlockables_labels(self):
        if not self.unlockables_data:
            if self._unlock_header_label:
                self._unlock_header_label.set_text("No modules found")
            for lbl in self._unlock_item_labels:
                lbl.set_text("")
            return
        mod_data = self.unlockables_data[self.current_unlock_module_index]
        unlocked = mod_data["unlocked"]
        if not unlocked:
            self._unlock_header_label.set_text(f"No items unlocked for {mod_data['name']}")
            for lbl in self._unlock_item_labels:
                lbl.set_text("")
            return
        self._unlock_header_label.set_text(f"{mod_data['name']}: {len(unlocked)} of {len(mod_data['all'])} unlocked")
        vis_start = max(0, self.current_unlock_item_index - 2)
        vis_items = unlocked[vis_start:vis_start + 5]
        for i in range(5):
            if i < len(vis_items):
                self._unlock_item_labels[i].set_text(vis_items[i].get("label", vis_items[i].get("name", "???")))
            else:
                self._unlock_item_labels[i].set_text("")

    def _scroll_unlockables(self, step):
        """Move the Secrets list by *step* names, wrapping like UP/DOWN."""
        n = len(self.unlockables_data)
        if not n:
            return False
        unlocked = self.unlockables_data[self.current_unlock_module_index]["unlocked"]
        if not unlocked:
            return False
        self.current_unlock_item_index = (self.current_unlock_item_index + step) % len(unlocked)
        runtime_globals.game_sound.play("menu")
        self._update_unlockables_labels()
        return True

    def _unlockables_prev_module(self):
        n = len(self.unlockables_data)
        if n:
            self.current_unlock_module_index = (self.current_unlock_module_index - 1) % n
            self.current_unlock_item_index = 0
            runtime_globals.game_sound.play("menu")
            self._update_unlockables_labels()

    def _unlockables_next_module(self):
        n = len(self.unlockables_data)
        if n:
            self.current_unlock_module_index = (self.current_unlock_module_index + 1) % n
            self.current_unlock_item_index = 0
            runtime_globals.game_sound.play("menu")
            self._update_unlockables_labels()

    def _load_unlockables(self):
        self.unlockables_data = []
        for module in runtime_globals.game_modules.values():
            unlocks = getattr(module, "unlocks", [])
            unlocked_items = [u for u in unlocks if is_unlocked(module.name, u.get("type", ""), u.get("name", ""))]
            self.unlockables_data.append({
                "name": module.name,
                "icon": runtime_globals.game_module_flag.get(module.name, None),
                "unlocked": unlocked_items,
                "all": unlocks,
            })
        self.current_unlock_module_index = 0
        self.current_unlock_item_index = 0

    # ------------------------------------------------------------------
    # Window size dialog
    # ------------------------------------------------------------------

    def _build_window_size_view(self):
        """Pick the output window size from a preset list (windowed only).

        Cycling only previews the value; the change is committed on Apply,
        which resizes the window live and rescales the canvas.
        """
        from utils import display_utils
        cfg = game_globals.configuration
        self.title_scene.set_text("WINDOW SIZE")
        self.ui_background.visible = True

        self._winsize_presets = display_utils.available_window_presets()
        cur = (cfg.window_width, cfg.window_height)
        try:
            self._winsize_index = self._winsize_presets.index(cur)
        except ValueError:
            self._winsize_index = 0

        self._winsize_label = Label(120, 64, "", is_title=True, center=True,
                                    color_override=YELLOW_BRIGHT, shadow_mode="full")
        self._add_dynamic(self._winsize_label)

        self._add_dynamic(Label(120, 92, "Output window", center=True,
                                color_override=(190, 190, 190)))
        self._add_dynamic(Label(120, 104, "Game is scaled to fit", center=True,
                                color_override=(150, 150, 150)))

        mouse = self._mouse_enabled()
        nav_y = 126
        aw, ah = 36, 30
        left_btn = Button(28, nav_y, aw, ah, "", lambda: self._cycle_window_size(False),
                          icon_name="Left", icon_prefix="Settings")
        left_btn.visible = mouse
        self._add_dynamic(left_btn)
        right_btn = Button(BASE_RESOLUTION - 28 - aw, nav_y, aw, ah, "",
                           lambda: self._cycle_window_size(True),
                           icon_name="Right", icon_prefix="Settings")
        right_btn.visible = mouse
        self._add_dynamic(right_btn)

        ay = BASE_RESOLUTION - 38
        self._add_dynamic(Button(28, ay, 78, 28, "Apply", self._apply_window_size))
        self._add_dynamic(Button(BASE_RESOLUTION - 28 - 78, ay, 78, 28, "Cancel",
                                 self._go_back))

        instr_y = nav_y - 2
        for i, txt in enumerate(["LEFT/RIGHT: Change", "START: Apply", "B: Cancel"]):
            lbl = Label(6, instr_y + i * 10, txt, shadow_mode="full")
            lbl.visible = not mouse
            self._add_dynamic(lbl)

        self._update_window_size_label()

    def _update_window_size_label(self):
        if not (self._winsize_label and self._winsize_presets):
            return
        w, h = self._winsize_presets[self._winsize_index]
        cfg = game_globals.configuration
        tag = "  (current)" if (w, h) == (cfg.window_width, cfg.window_height) else ""
        self._winsize_label.set_text(f"{w} x {h}{tag}")

    def _cycle_window_size(self, increase):
        if not self._winsize_presets:
            return
        n = len(self._winsize_presets)
        self._winsize_index = (self._winsize_index + (1 if increase else -1)) % n
        runtime_globals.game_sound.play("menu")
        self._update_window_size_label()

    def _apply_window_size(self):
        if not self._winsize_presets:
            return
        from utils import display_utils
        w, h = self._winsize_presets[self._winsize_index]
        runtime_globals.game_sound.play("menu")
        display_utils.apply_window_size(w, h)
        # Return to the Display section.  If the internal resolution changed,
        # update() rebuilds the whole UI at the new scale on the next frame.
        if len(self.nav_stack) > 1:
            self.nav_stack.pop()
        self._build_section_view()

    def _rebuild_ui(self):
        """Recreate the UI manager and current view at the current render
        resolution.  Called after a live resolution change so every component
        is rebuilt at the new UI scale."""
        self.window_background = WindowBackground(False)
        self.ui_manager = UIManager(theme="GRAY")
        self.ui_manager.set_input_manager(runtime_globals.game_input)

        self.ui_background = Background(BASE_RESOLUTION, BASE_RESOLUTION)
        self.ui_background.set_regions([(0, BASE_RESOLUTION, "black")])
        self.ui_manager.add_component(self.ui_background)

        self.title_scene = TitleScene(0, 9, "SETTINGS")
        self.ui_manager.add_component(self.title_scene)

        self._dynamic_components = []
        self._option_rows = []
        self._build_section_view()

    # ------------------------------------------------------------------
    # Navigation helpers
    # ------------------------------------------------------------------

    def _mouse_enabled(self):
        return runtime_globals.INPUT_MODE in (
            runtime_globals.MOUSE_MODE, runtime_globals.TOUCH_MODE)

    def _navigate_to(self, section_key):
        runtime_globals.game_sound.play("menu")
        self.nav_stack.append(section_key)
        self._build_section_view()

    def _go_back(self):
        runtime_globals.game_sound.play("cancel")
        if self._current_section_key() == "background":
            self.ui_background.visible = True
        if len(self.nav_stack) > 1:
            self.nav_stack.pop()
            self._build_section_view()
        else:
            change_scene("game")

    # ------------------------------------------------------------------
    # Option activation (A / click on action rows)
    # ------------------------------------------------------------------

    def _on_option_activate(self, opt):
        key = opt["key"]

        # Sub-sections
        if key in self.sections:
            self._navigate_to(key)
            return
        if key == "background":
            self._navigate_to("background")
            return
        if key == "unlockables":
            self._navigate_to("unlockables")
            return
        if key == "window_size":
            # Locked in fullscreen (the window equals the screen there).
            if game_globals.configuration.fullscreen:
                return
            self._navigate_to("window_size")
            return

        # Actions that leave the scene
        if key == "game_mode":
            runtime_globals.game_sound.play("menu")
            game_globals.setup_input = False
            game_globals.setup_graphics = False
            game_globals.setup_game_mode = True
            game_globals.skip_tutorial_on_mode_switch = bool(game_globals.pet_list)
            change_scene("setup")
            return
        if key == "remap_input":
            runtime_globals.game_sound.play("menu")
            game_globals.setup_input = True
            game_globals.setup_graphics = False
            change_scene("setup")
            return
        if key == "test_graphics":
            runtime_globals.game_sound.play("menu")
            game_globals.setup_input = False
            game_globals.setup_graphics = True
            change_scene("setup")
            return
        if key == "replay_tutorial":
            runtime_globals.game_sound.play("menu")
            game_globals.show_tutorial = True
            change_scene("tutorial")
            return
        if key == "notification_settings":
            from services import android_progress
            android_progress.open_notification_settings()
            return

    # ------------------------------------------------------------------
    # Core scene interface
    # ------------------------------------------------------------------

    def update(self) -> None:
        # A live Render Res / Window Size change alters the internal render
        # resolution; rebuild the UI so every component picks up the new scale.
        cur = (runtime_globals.SCREEN_WIDTH, runtime_globals.SCREEN_HEIGHT)
        if self.ui_manager.screen_size != cur:
            runtime_globals.game_console.log(
                "[SceneSettingsMenu] Render resolution changed; rebuilding UI")
            self._rebuild_ui()
        self.ui_manager.update()

    def draw(self, surface: pygame.Surface) -> None:
        self.window_background.draw(surface)
        self.ui_manager.draw(surface)

    def handle_event(self, event) -> None:
        if not isinstance(event, tuple) or len(event) != 2:
            return
        event_type, event_data = event
        section = self._current_section_key()

        # ---- Background mode ----
        if section == "background":
            if event_type == "B":
                self._go_back()
                return
            if not self._mouse_enabled():
                if event_type in ("LEFT", "RIGHT"):
                    self._change_background(event_type == "RIGHT")
                    return
                if event_type == "SELECT":
                    self._toggle_highres()
                    return

        # ---- Window size dialog ----
        elif section == "window_size":
            if event_type == "B":
                self._go_back()
                return
            if event_type == "START":
                self._apply_window_size()
                return
            if not self._mouse_enabled() and event_type in ("LEFT", "RIGHT"):
                self._cycle_window_size(event_type == "RIGHT")
                return

        # ---- Unlockables mode ----
        elif section == "unlockables":
            if event_type == "B":
                self._go_back()
                return
            if event_type == "SCROLL" and event_data:
                # The mouse wheel scrolls the list, as UP/DOWN do.
                self._scroll_unlockables(-1 if event_data.get("direction") == "UP" else 1)
                return
            if not self._mouse_enabled():
                n = len(self.unlockables_data)
                if event_type == "LEFT" and n:
                    self.current_unlock_module_index = (self.current_unlock_module_index - 1) % n
                    self.current_unlock_item_index = 0
                    runtime_globals.game_sound.play("menu")
                    self._update_unlockables_labels()
                    return
                if event_type == "RIGHT" and n:
                    self.current_unlock_module_index = (self.current_unlock_module_index + 1) % n
                    self.current_unlock_item_index = 0
                    runtime_globals.game_sound.play("menu")
                    self._update_unlockables_labels()
                    return
                if n and self.unlockables_data[self.current_unlock_module_index]["unlocked"]:
                    unlocked = self.unlockables_data[self.current_unlock_module_index]["unlocked"]
                    if event_type == "UP":
                        self._scroll_unlockables(-1)
                        return
                    if event_type == "DOWN":
                        self._scroll_unlockables(1)
                        return

        # ---- Normal section: B goes back ----
        else:
            if event_type == "B":
                self._go_back()
                return

        # Delegate everything else to UI manager
        # (OptionRow handles LEFT/RIGHT/A/LCLICK internally)
        self.ui_manager.handle_event(event)