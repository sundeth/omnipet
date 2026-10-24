"""
Scene Login
============

Handles the full Omninet authentication flow for Progress Mode:

Phases:
    menu              → Choose: Create Account, Login, Link Device, Back
    create_account    → nickname + email + password + confirm password
    login             → email + password
    verify            → 6-character code entry (for both register and login)
    link_device       → 4-character pairing code from Module Editor
    loading           → Spinner while async operations run
    complete          → Set player_id, migrate saves, load, route onward

After successful authentication the device key is stored automatically
by OmninetService, and the player_id is synchronised into game_globals
so the correct save directory is used.

Entry points:
    - SceneSetup._on_game_mode_selected() → Progress Mode selected
    - MainMenuView._on_omninet_connect()  → Connect in Progress Mode

Uses the standard UI system (UIManager, Button, Label, TextInput, etc.).
"""

import os
import threading
import pygame

from ui.ui_manager import UIManager
from ui.components.background import Background
from ui.components.title_scene import TitleScene
from ui.components.button import Button
from ui.components.label import Label
from ui.components.text_input import TextInput
from ui.components.code_entry import CodeEntry
from ui.ui_constants import BASE_RESOLUTION
from ui.windows.window_background import WindowBackground
from core import game_globals, runtime_globals
from utils.scene_utils import change_scene
from utils import navigation_utils
from services.omninet_service import omninet_service


class SceneLogin:
    """
    Full-screen login scene for Omninet authentication.

    Supports account creation (with email verification), password login
    (with 2FA code), and device linking via pairing code.
    """

    def __init__(self) -> None:
        runtime_globals.game_console.log("[SceneLogin] Initializing")

        self.window_background = WindowBackground(True)
        self.ui_manager = UIManager("GREEN")
        self.ui_manager.show_external_border = False
        self.ui_manager.set_input_manager(runtime_globals.game_input)

        # Phase state
        self.phase = "menu"

        # Temporary data stored across phases
        self._email = ""
        self._nickname = ""
        self._verify_action = None  # "register" or "login"
        self._loading = False
        self._error_text = ""

        # Component references (set per-phase)
        self._components = []  # Track components for cleanup

        # Whether this scene was entered from connect (vs. from setup)
        self._from_connect = (runtime_globals.game_state == "connect"
                              or runtime_globals.game_state == "login")

        # Mandatory: player must log in (Progress Mode, not authenticated).
        # In this mode the Back button is hidden; only "Change to Free Play"
        # provides an exit.
        self._mandatory = (
            game_globals.is_progress_mode()
            and not omninet_service.is_logged_in()
        )

        self._build_menu()

    # =====================================================================
    # Phase builders — each one clears the UI and builds a fresh layout
    # =====================================================================

    def _clear_ui(self):
        """Remove all tracked components and reset the UI manager."""
        self.ui_manager.components.clear()
        self.ui_manager.focusable_components.clear()
        self.ui_manager.focused_index = 0
        self._components.clear()
        self._error_text = ""

    def _add(self, comp):
        """Add a component to both the UI manager and the tracking list."""
        self.ui_manager.add_component(comp)
        self._components.append(comp)
        return comp

    # ── Menu phase ────────────────────────────────────────────────────

    def _build_menu(self):
        """Build the main menu: Create Account / Login / Link Device / Back."""
        self._clear_ui()
        self.phase = "menu"

        w = h = BASE_RESOLUTION

        bg = Background(w, h)
        bg.set_regions([(0, h, "black")])
        self._add(bg)

        self._add(TitleScene(0, 9, "LOGIN"))

        self._add(Label(120, 45, "OMNINET ACCOUNT", is_title=True,
                        color_override=(255, 255, 255), center=True))

        btn_w = 180
        btn_h = 28
        btn_x = (w - btn_w) // 2
        gap = 8

        y = 80
        self._add(Button(btn_x, y, btn_w, btn_h, "Create Account",
                         self._go_create_account))
        y += btn_h + gap
        self._add(Button(btn_x, y, btn_w, btn_h, "Login",
                         self._go_login))
        y += btn_h + gap
        self._add(Button(btn_x, y, btn_w, btn_h, "Link Device",
                         self._go_link_device))
        y += btn_h + gap + 8

        if self._mandatory:
            # Progress Mode, not authenticated: hide Back, show escape hatch
            self._add(Button(btn_x, y, btn_w, btn_h, "Change to Free Play",
                             self._switch_to_free))
            y += btn_h + gap
            # Connectivity status — filled asynchronously
            self._conn_label = self._add(Label(
                120, y + 4, "Checking connection...",
                color_override=(180, 180, 180), center=True,
                word_wrap=True, max_width=w - 20))
            self._check_connection_async()
        else:
            self._add(Button(btn_x, y, btn_w, btn_h, "Back",
                             self._go_back))

        runtime_globals.game_console.log("[SceneLogin] Menu built")

    def _check_connection_async(self):
        """Background connectivity check; updates _conn_label with result."""
        def _worker():
            ok = omninet_service.check_availability()
            if not ok:
                if hasattr(self, '_conn_label') and self._conn_label:
                    self._conn_label.set_text(
                        "No internet connection found. "
                        "Use 'Change to Free Play' to continue without an account.")
                    self._conn_label.color_override = (255, 140, 80)
            else:
                if hasattr(self, '_conn_label') and self._conn_label:
                    self._conn_label.set_text("")
        threading.Thread(target=_worker, daemon=True).start()

    # ── Create Account phase ──────────────────────────────────────────

    def _go_create_account(self):
        runtime_globals.game_sound.play("menu")
        self._build_create_account()

    def _build_create_account(self):
        """Build the account creation form."""
        self._clear_ui()
        self.phase = "create_account"

        w = h = BASE_RESOLUTION
        bg = Background(w, h)
        bg.set_regions([(0, h, "black")])
        self._add(bg)

        self._add(TitleScene(0, 9, "LOGIN"))
        self._add(Label(120, 45, "CREATE ACCOUNT", is_title=True,
                        color_override=(255, 255, 255), center=True))

        field_w = 200
        field_x = (w - field_w) // 2
        # Start below the title so the first field doesn't touch "CREATE ACCOUNT"
        y = 74

        self._add(Label(field_x, y, "Nickname", color_override=(180, 180, 180)))
        y += 10
        self.inp_nickname = self._add(TextInput(
            field_x, y, field_w, placeholder="Your name", max_length=100,
            keyboard_type="default"))
        y += self._field_height() + 2

        self._add(Label(field_x, y, "Email", color_override=(180, 180, 180)))
        y += 10
        self.inp_email = self._add(TextInput(
            field_x, y, field_w, placeholder="email@example.com", max_length=255,
            keyboard_type="email"))
        y += self._field_height() + 2

        self._add(Label(field_x, y, "Password", color_override=(180, 180, 180)))
        y += 10
        self.inp_password = self._add(TextInput(
            field_x, y, field_w, placeholder="Min 6 characters", max_length=100,
            keyboard_type="default", is_password=True))
        y += self._field_height() + 2

        # Error label
        self.error_label = self._add(Label(
            120, y, "", color_override=(255, 80, 80), center=True,
            word_wrap=True, max_width=200))

        # Buttons at bottom
        btn_w = 80
        btn_h = 20
        gap = 16
        btn_y = h - btn_h - 8
        self._add(Button((w // 2) - btn_w - (gap // 2), btn_y, btn_w, btn_h,
                         "Create", self._on_create_account_submit))
        self._add(Button((w // 2) + (gap // 2), btn_y, btn_w, btn_h,
                         "Cancel", self._on_cancel))

        self.ui_manager.set_focused_component(self.inp_nickname)
        runtime_globals.game_console.log("[SceneLogin] Create Account form built")

    def _on_create_account_submit(self):
        """Validate fields and call register endpoint."""
        nickname = self.inp_nickname.get_text().strip()
        email = self.inp_email.get_text().strip()
        password = self.inp_password.get_text()

        # Client-side validation
        if len(nickname) < 3:
            self._show_error("Nickname must be 3+ characters")
            return
        if "@" not in email or "." not in email:
            self._show_error("Enter a valid email address")
            return
        if len(password) < 6:
            self._show_error("Password must be 6+ characters")
            return

        self._email = email
        self._nickname = nickname
        self._verify_action = "register"
        self._async_call(
            lambda: omninet_service.register(nickname, email, password),
            self._on_register_response,
        )

    def _on_register_response(self, result):
        success, message = result
        if success:
            runtime_globals.game_console.log("[SceneLogin] Registration sent, show verify")
            self._build_verify()
        else:
            self._show_error(message[:40])

    # ── Login phase ───────────────────────────────────────────────────

    def _go_login(self):
        runtime_globals.game_sound.play("menu")
        self._build_login()

    def _build_login(self):
        """Build the login form."""
        self._clear_ui()
        self.phase = "login"

        w = h = BASE_RESOLUTION
        bg = Background(w, h)
        bg.set_regions([(0, h, "black")])
        self._add(bg)

        self._add(TitleScene(0, 9, "LOGIN"))
        self._add(Label(120, 45, "LOGIN", is_title=True,
                        color_override=(255, 255, 255), center=True))

        field_w = 200
        field_x = (w - field_w) // 2
        y = 72

        self._add(Label(field_x, y, "Email", color_override=(180, 180, 180)))
        y += 10
        self.inp_email = self._add(TextInput(
            field_x, y, field_w, placeholder="email@example.com", max_length=255,
            keyboard_type="email"))
        y += self._field_height() + 4

        self._add(Label(field_x, y, "Password", color_override=(180, 180, 180)))
        y += 10
        self.inp_password = self._add(TextInput(
            field_x, y, field_w, placeholder="Password", max_length=100,
            keyboard_type="default", is_password=True))
        y += self._field_height() + 4

        # Error label
        self.error_label = self._add(Label(
            120, y, "", color_override=(255, 80, 80), center=True,
            word_wrap=True, max_width=200))

        # Buttons
        btn_w = 80
        btn_h = 20
        gap = 16
        btn_y = h - btn_h - 8
        self._add(Button((w // 2) - btn_w - (gap // 2), btn_y, btn_w, btn_h,
                         "Login", self._on_login_submit))
        self._add(Button((w // 2) + (gap // 2), btn_y, btn_w, btn_h,
                         "Cancel", self._on_cancel))

        self.ui_manager.set_focused_component(self.inp_email)
        runtime_globals.game_console.log("[SceneLogin] Login form built")

    def _on_login_submit(self):
        """Validate and send login request."""
        email = self.inp_email.get_text().strip()
        password = self.inp_password.get_text()

        if "@" not in email or "." not in email:
            self._show_error("Enter a valid email address")
            return
        if not password:
            self._show_error("Enter your password")
            return

        self._email = email
        self._verify_action = "login"
        self._async_call(
            lambda: omninet_service.login_request(email, password),
            self._on_login_response,
        )

    def _on_login_response(self, result):
        success, message = result
        if success:
            runtime_globals.game_console.log("[SceneLogin] Login sent, show verify")
            self._build_verify()
        elif self._is_inactive_account_error(message):
            # The account exists but was never activated — the server
            # refuses login until the emailed code is verified.  Instead of
            # dead-ending the player (whose only recourse was re-registering
            # with the same details), send a fresh activation code and drop
            # them into the verify screen as a registration verification.
            runtime_globals.game_console.log(
                "[SceneLogin] Login blocked (inactive account); resending code")
            self._verify_action = "register"
            self._async_call(
                lambda: omninet_service.resend_code(self._email),
                self._on_resend_for_activation,
            )
        else:
            self._show_error(message[:40])

    @staticmethod
    def _is_inactive_account_error(message) -> bool:
        """True when a login failure is due to an unactivated account."""
        msg = (message or "").lower()
        return ("not active" in msg or "not activated" in msg
                or "not verified" in msg)

    def _on_resend_for_activation(self, result):
        """Code (re)sent after an inactive-account login attempt.

        Move the player to the verify screen so they can finish activating;
        the verify action is already set to ``register`` so a correct code
        marks the account verified + active.
        """
        success, message = result
        self._build_verify()
        if success:
            if hasattr(self, 'error_label') and self.error_label:
                self.error_label.color_override = (255, 200, 80)
                self.error_label.set_text("Account not activated. New code sent.")
                self.ui_manager.master_ui_dirty = True
        else:
            self._show_error(message[:40])

    # ── Verify phase (shared by register + login) ─────────────────────

    def _build_verify(self):
        """Build the 6-character code verification form."""
        self._clear_ui()
        self.phase = "verify"

        w = h = BASE_RESOLUTION
        bg = Background(w, h)
        bg.set_regions([(0, h, "black")])
        self._add(bg)

        self._add(TitleScene(0, 9, "LOGIN"))

        title = "VERIFY EMAIL" if self._verify_action == "register" else "VERIFY LOGIN"
        self._add(Label(120, 45, title, is_title=True,
                        color_override=(255, 255, 255), center=True))

        # Instruction (pushed below the title so it doesn't touch "VERIFY EMAIL")
        truncated_email = self._email if len(self._email) <= 28 else self._email[:25] + "..."
        self._add(Label(120, 74, "Code sent to:", color_override=(180, 180, 180),
                        center=True))
        self._add(Label(120, 84, truncated_email, color_override=(200, 200, 200),
                        center=True))

        # Code entry (6 digits) — the emailed verification code is always
        # numeric, so use the digit-only keypad.  Narrower boxes keep all six
        # digits on screen within the 240px base resolution.
        digit_w, digit_gap = 30, 6
        code_w = digit_w * 6 + digit_gap * 5
        self.code_entry = self._add(
            CodeEntry((w - code_w) // 2, 98, length=6, numeric=True,
                      char_w=digit_w, char_h=44, spacing=digit_gap,
                      callback=lambda _t: self._on_verify_submit(),
                      on_focus_callback=self._clear_error))

        # Timer label (code-expiry countdown)
        self._verify_seconds = 5 * 60  # 5 minutes
        self._verify_frame_counter = 0
        self.timer_label = self._add(Label(
            120, 152, self._format_timer(), color_override=(150, 150, 150),
            center=True))

        # Error label
        self.error_label = self._add(Label(
            120, 165, "", color_override=(255, 80, 80), center=True,
            word_wrap=True, max_width=200))

        # Buttons
        btn_w = 70
        btn_h = 20
        btn_y = h - btn_h - 8
        self.resend_button = self._add(Button(
            (w // 2) - btn_w * 3 // 2 - 8, btn_y, btn_w, btn_h,
            "Resend", self._on_resend_code))
        self._add(Button((w // 2) - btn_w // 2, btn_y, btn_w, btn_h,
                         "Verify", self._on_verify_submit))
        self._add(Button((w // 2) + btn_w // 2 + 8, btn_y, btn_w, btn_h,
                         "Cancel", self._on_cancel))

        # A freshly sent code is still valid, so Resend stays locked until the
        # timer expires.  This keeps the player from hammering the server's
        # resend endpoint, which rate-limits and can stop sending mail entirely.
        self.resend_button.set_enabled(False)

        self.ui_manager.set_focused_component(self.code_entry)
        runtime_globals.game_console.log("[SceneLogin] Verify form built")

    def _format_timer(self):
        """Format remaining seconds as M:SS."""
        m = self._verify_seconds // 60
        s = self._verify_seconds % 60
        return f"Expires in {m}:{s:02d}"

    def _on_verify_submit(self):
        """Submit verification code."""
        code = self.code_entry.get_text()
        if len(code) != 6:
            self._show_error("Enter the 6-digit code")
            return

        if self._verify_action == "register":
            self._async_call(
                lambda: omninet_service.verify_registration(self._email, code),
                self._on_verify_response,
            )
        else:
            self._async_call(
                lambda: omninet_service.verify_login(self._email, code),
                self._on_verify_response,
            )

    def _on_verify_response(self, result):
        success, message = result
        if success:
            runtime_globals.game_console.log("[SceneLogin] Verification successful")
            runtime_globals.game_sound.play("evolution")
            self._complete_login()
        else:
            self._show_error(message[:40])

    def _on_code_expired(self):
        """Called once the verification code's 5-minute window elapses.

        The timer stops at 0:00 and never auto-restarts — the only way to get
        a new countdown is to request a fresh code via Resend, which is now
        unlocked.
        """
        if hasattr(self, 'timer_label') and self.timer_label:
            self.timer_label.color_override = (255, 140, 80)
            self.timer_label.set_text("Code expired - tap Resend")
        if hasattr(self, 'resend_button') and self.resend_button:
            self.resend_button.set_enabled(True)
        self.ui_manager.master_ui_dirty = True

    def _on_resend_code(self):
        """Resend verification code (only allowed once the prior code expired)."""
        if hasattr(self, 'resend_button') and self.resend_button \
                and not self.resend_button.enabled:
            return
        self._async_call(
            lambda: omninet_service.resend_code(self._email),
            self._on_resend_response,
        )

    def _on_resend_response(self, result):
        success, message = result
        if success:
            # Restart the expiry countdown and clear the input so the player
            # can type the new code.
            self._verify_seconds = 5 * 60
            self._verify_frame_counter = 0
            if hasattr(self, 'timer_label') and self.timer_label:
                self.timer_label.color_override = (150, 150, 150)
                self.timer_label.set_text(self._format_timer())
            if hasattr(self, 'code_entry') and self.code_entry:
                self.code_entry.reset()
            if hasattr(self, 'resend_button') and self.resend_button:
                self.resend_button.set_enabled(False)
            self._show_error("")  # Clear error
            # Force an immediate rebuild of the cached UI so the cleared boxes
            # and reset timer show right away (otherwise they only refresh when
            # the field is next focused / hovered).
            self.ui_manager.master_ui_dirty = True
            runtime_globals.game_sound.play("menu")
            # (suppressed) runtime_globals.game_message.add_slide("Code resent!", (0, 231, 58), 90)
        else:
            self._show_error(message[:40])

    # ── Link Device phase ─────────────────────────────────────────────

    def _go_link_device(self):
        runtime_globals.game_sound.play("menu")
        self._build_link_device()

    def _build_link_device(self):
        """Build the 4-character pairing code form (same as OmninetLinkView)."""
        self._clear_ui()
        self.phase = "link_device"

        w = h = BASE_RESOLUTION
        bg = Background(w, h)
        bg.set_regions([(0, h, "black")])
        self._add(bg)

        self._add(TitleScene(0, 9, "LOGIN"))
        self._add(Label(120, 45, "LINK DEVICE", is_title=True,
                        color_override=(255, 255, 255), center=True))

        self._add(Label(120, 68, "Enter code from Module Editor",
                        color_override=(180, 180, 180), center=True))

        # Code entry (4 characters) — refocus clears any prior error message
        self.code_entry = self._add(
            CodeEntry((w - 190) // 2, 90, length=4,
                      callback=lambda _t: self._on_link_submit(),
                      on_focus_callback=self._clear_error))

        # Status / error label
        self.error_label = self._add(Label(
            120, 155, "", color_override=(255, 80, 80), center=True,
            word_wrap=True, max_width=200))

        # Buttons
        btn_w = 80
        btn_h = 20
        gap = 16
        btn_y = h - btn_h - 8
        self._add(Button((w // 2) - btn_w - (gap // 2), btn_y, btn_w, btn_h,
                         "Confirm", self._on_link_submit))
        self._add(Button((w // 2) + (gap // 2), btn_y, btn_w, btn_h,
                         "Cancel", self._on_cancel))

        self.ui_manager.set_focused_component(self.code_entry)
        runtime_globals.game_console.log("[SceneLogin] Link Device form built")

    def _on_link_submit(self):
        """Validate pairing code."""
        code = self.code_entry.get_text()
        if len(code) != 4:
            self._show_error("Enter 4-character code")
            return

        self._async_call(
            lambda: omninet_service.validate_pairing_code(code),
            self._on_link_response,
        )

    def _on_link_response(self, result):
        # validate_pairing_code returns (success, message, user_info) but
        # _async_call's exception fallback returns (False, str(exc)).  Be
        # tolerant of either shape so a thrown error doesn't crash here.
        if not isinstance(result, tuple):
            self._show_error("Invalid code")
            return
        success = result[0]
        raw_message = result[1] if len(result) > 1 else ""
        user_info = result[2] if len(result) > 2 else None
        if success:
            username = user_info.get('nickname', 'User') if user_info else 'User'
            runtime_globals.game_console.log(f"[SceneLogin] Linked as: {username}")
            runtime_globals.game_sound.play("evolution")
            self._complete_login()
        else:
            # Map any technical error into a single user-friendly message.
            msg = str(raw_message).lower()
            if not raw_message or "unpack" in msg or "exception" in msg \
                    or "traceback" in msg or "error" in msg and len(msg) > 32:
                friendly = "Invalid code"
            else:
                friendly = str(raw_message)[:32]
            self._show_error(friendly)

    # ── Loading overlay ───────────────────────────────────────────────

    def _build_loading(self):
        """Show a simple loading indicator over current UI."""
        self._loading = True
        # Disable all buttons while loading
        for comp in self._components:
            if isinstance(comp, Button):
                comp.enabled = False
        self._show_error("Connecting...")

    def _end_loading(self):
        """Re-enable UI after async operation completes."""
        self._loading = False
        for comp in self._components:
            if isinstance(comp, Button):
                comp.enabled = True
        # The verify Resend button is gated on the code-expiry timer, not on
        # the loading state, so restore its real state after the blanket
        # re-enable above (otherwise a resend would immediately unlock it).
        if self.phase == "verify" and hasattr(self, 'resend_button') \
                and self.resend_button:
            self.resend_button.set_enabled(self._verify_seconds == 0)

    # ── Async helper ──────────────────────────────────────────────────

    def _async_call(self, func, on_complete):
        """Run *func* in a background thread, then call *on_complete(result)*
        on the next update cycle.

        Args:
            func:        Callable that returns a result (runs on bg thread).
            on_complete: Callable(result) invoked on the main thread.
        """
        self._build_loading()
        self._async_result = None
        self._async_callback = on_complete

        def _worker():
            try:
                result = func()
            except Exception as e:
                runtime_globals.game_console.log(f"[SceneLogin] Async error: {e}")
                result = (False, str(e))
            self._async_result = result

        threading.Thread(target=_worker, daemon=True).start()

    # ── Navigation helpers ────────────────────────────────────────────

    def _on_cancel(self):
        """Return to menu phase — or exit scene if already on menu."""
        runtime_globals.game_sound.play("cancel")
        if self.phase == "menu":
            self._go_back()
        else:
            self._build_menu()

    def _go_back(self):
        """Exit the login scene.

        In mandatory mode (Progress Mode, not logged in) the exit is blocked —
        the player must log in or switch to Free Play via the dedicated button.

        If entering from setup (first-time), go back to setup.
        If entering from connect menu, go back to connect.
        """
        if self._mandatory and not omninet_service.is_logged_in():
            self._show_error("Login required. Use 'Change to Free Play' to exit.")
            return
        runtime_globals.game_sound.play("cancel")
        # If game mode preference hasn't been saved yet, go back to setup
        if not game_globals.has_game_mode_preference():
            change_scene("setup")
        else:
            change_scene("connect")
        runtime_globals.game_console.log("[SceneLogin] Back")

    def _sync_purchases_async(self):
        """Reconcile coins, purchases and owned modules with the server in a
        background thread.

        Without this, ``GamePurchases`` only knows about purchases made on this
        device — so on a fresh login from a different machine every module
        shows up as Free, and owned modules can't be used until their files are
        downloaded and their local names recorded.  ``download_missing=True``
        also fetches owned modules absent on this device.
        """
        def _worker():
            try:
                from utils.module_utils import sync_account_data
                sync_account_data(download_missing=True)
            except Exception as exc:
                runtime_globals.game_console.log(
                    f"[SceneLogin] account sync failed: {exc}")

        threading.Thread(target=_worker, daemon=True).start()

    def _switch_to_free(self):
        """Switch to Free Play mode and route accordingly.

        Escape hatch when the player was forced into login by Progress Mode
        but does not want to create an Omninet account.
        """
        runtime_globals.game_sound.play("cancel")
        runtime_globals.game_console.log("[SceneLogin] Switching to Free Play")
        game_globals.game_mode = game_globals.GAME_MODE_FREE
        game_globals.save_game_mode_preference()
        game_globals.skip_tutorial_on_mode_switch = False
        game_globals.migrate_legacy_saves()
        save_dir = game_globals.get_save_dir()
        os.makedirs(save_dir, exist_ok=True)
        # Carry the current resolution across the save switch (→ Free Mode).
        from utils import display_utils
        display_utils.load_preserving_display()
        navigation_utils.route_to_next_scene(check_tutorial=True)

    def _complete_login(self):
        """Post-login finalisation: sync player_id, migrate saves, load, route.

        This is the critical path that bridges authentication to gameplay.
        After a successful register/login/link the OmninetService already
        holds the device key and player_id.
        """
        runtime_globals.game_console.log("[SceneLogin] Completing login")

        # 1. Sync player_id into game_globals
        player_id = omninet_service.get_player_id()
        if player_id:
            game_globals.set_player_id(player_id)
            runtime_globals.game_console.log(
                f"[SceneLogin] Player ID synced: {player_id[:8]}…")
        else:
            runtime_globals.game_console.log(
                "[SceneLogin] WARNING: No player_id from service!")

        # 2. Ensure the save directory exists (creates save/<player_id>/)
        save_dir = game_globals.get_save_dir()
        os.makedirs(save_dir, exist_ok=True)

        # 3. Migrate any legacy save data into the correct directory
        game_globals.migrate_legacy_saves()

        # 4. Load save data from the (now-correct) directory.  Carry the
        # current screen/render resolution across the save switch so the
        # Progress save's pets/poops aren't left off-screen/misplaced.
        from utils import display_utils
        display_utils.load_preserving_display()

        # 4a. Mirror the server coin balance into the local total.  load()
        # above set coins from the local save; in Progress Mode the server is
        # authoritative (rewards can be earned on other devices), so overwrite
        # with the balance fetched during device validation.
        try:
            ui = omninet_service.get_user_info()
            if ui and ui.get('coins') is not None:
                game_globals.coins = int(ui['coins'])
                if ui.get('contribution_points') is not None:
                    game_globals.contribution_points = int(ui['contribution_points'])
                game_globals.save()
        except Exception:
            pass

        # 4b. Sync purchases from the server so the shop knows what the
        # player already owns (otherwise modules would all appear as
        # "Free" even on accounts with prior purchases).
        self._sync_purchases_async()

        # 5. If still in first-time setup, clear setup flags and save
        if game_globals.setup_input or game_globals.setup_graphics:
            game_globals.setup_input = False
            game_globals.setup_graphics = False
            game_globals.save()

        # 6. Route to next scene (skip tutorial if mid-game mode switch)
        skip_tutorial = game_globals.skip_tutorial_on_mode_switch
        game_globals.skip_tutorial_on_mode_switch = False
        navigation_utils.route_to_next_scene(check_tutorial=not skip_tutorial)
        runtime_globals.game_console.log("[SceneLogin] Login complete, routed to next scene")

    # ── Error display ─────────────────────────────────────────────────

    def _show_error(self, text):
        """Display an error/status message in the current phase."""
        self._error_text = text
        if hasattr(self, 'error_label') and self.error_label:
            self.error_label.set_text(text)
        if text and text != "Connecting...":
            runtime_globals.game_sound.play("cancel")
        self.ui_manager.master_ui_dirty = True

    def _clear_error(self):
        """Hide any prior error/status message (called when refocusing input)."""
        self._error_text = ""
        if hasattr(self, 'error_label') and self.error_label:
            self.error_label.set_text("")
        self.ui_manager.master_ui_dirty = True

    # ── Field height helper ───────────────────────────────────────────

    def _field_height(self):
        """Return the base height of a TextInput (always compact)."""
        return TextInput.FIELD_HEIGHT

    # =====================================================================
    # Scene interface (update / draw / handle_event)
    # =====================================================================

    def update(self) -> None:
        """Called every frame."""
        self.ui_manager.update()

        # Process async result if available — always re-enable buttons even
        # if the callback raises, so the user is never left stuck staring at
        # disabled controls.
        if hasattr(self, '_async_result') and self._async_result is not None:
            result = self._async_result
            callback = self._async_callback
            self._async_result = None
            self._async_callback = None
            try:
                callback(result)
            except Exception as exc:
                runtime_globals.game_console.log(
                    f"[SceneLogin] async callback raised: {exc}")
                self._show_error("Invalid code")
            finally:
                self._end_loading()

        # Verify phase countdown
        if self.phase == "verify" and hasattr(self, '_verify_seconds'):
            # Tick once per second (approximate via frame rate)
            if not hasattr(self, '_verify_frame_counter'):
                self._verify_frame_counter = 0
            self._verify_frame_counter += 1
            fps = getattr(game_globals.configuration, 'frame_rate', 30)
            if self._verify_frame_counter >= fps:
                self._verify_frame_counter = 0
                if self._verify_seconds > 0:
                    self._verify_seconds -= 1
                    if hasattr(self, 'timer_label') and self.timer_label:
                        self.timer_label.set_text(self._format_timer())
                    # On hitting zero, stop the timer and unlock Resend.  It
                    # does not auto-restart — only a successful resend does.
                    if self._verify_seconds == 0:
                        self._on_code_expired()

    def draw(self, surface: pygame.Surface) -> None:
        """Draw the scene."""
        self.window_background.draw(surface)
        self.ui_manager.draw(surface)

        # Draw virtual-keyboard overlay for the focused TextInput / CodeEntry
        if not runtime_globals.IS_ANDROID:
            idx = self.ui_manager.focused_index
            if 0 <= idx < len(self.ui_manager.focusable_components):
                focused = self.ui_manager.focusable_components[idx]
                if isinstance(focused, TextInput):
                    focused.draw_keyboard_overlay(surface)
                elif isinstance(focused, CodeEntry):
                    focused.draw_keyboard_overlay(surface)

    def handle_event(self, event) -> None:
        """Handle input events."""
        if not isinstance(event, tuple) or len(event) != 2:
            # Forward raw pygame events to the focused text field so physical
            # keyboard input works (Android TEXTINPUT + desktop Backspace).
            # Return the consumption result so the caller (VirtualPetGame)
            # knows the key was handled and skips the game-action mapping.
            # Duck-type on ``type`` rather than isinstance(pygame.event.Event):
            # on some pygame builds (Android) Event is a factory function, not
            # a class, so isinstance against it raises TypeError.
            if hasattr(event, 'type'):
                idx = self.ui_manager.focused_index
                if 0 <= idx < len(self.ui_manager.focusable_components):
                    focused = self.ui_manager.focusable_components[idx]
                    if isinstance(focused, (TextInput, CodeEntry)):
                        return focused.handle_event(event)
            return False

        event_type, event_data = event

        # Global shortcuts
        if event_type == "B":
            if self.phase != "menu":
                self._on_cancel()
            else:
                self._go_back()  # Blocked internally if mandatory + not logged in
            return

        if event_type == "CANCEL" and self.phase != "menu":
            self._on_cancel()
            return

        # TAB (mapped to the SELECT action) advances to the next field on the
        # multi-input forms, so the keyboard flows naturally between fields.
        if event_type == "SELECT" and self.phase in ("create_account", "login"):
            self.ui_manager.focus_next()
            return

        if event_type == "MOUSE_MOTION":
            self.ui_manager.handle_event(event)
            return

        # Forward clicks to the virtual-keyboard overlay first
        if event_type == "LCLICK" and event_data and "pos" in event_data:
            if not runtime_globals.IS_ANDROID:
                idx = self.ui_manager.focused_index
                if 0 <= idx < len(self.ui_manager.focusable_components):
                    focused = self.ui_manager.focusable_components[idx]
                    if isinstance(focused, (TextInput, CodeEntry)):
                        screen_sz = self.ui_manager.get_scaled_resolution()
                        if focused.handle_keyboard_click(
                                event_data["pos"], screen_sz):
                            return

        # Let UI manager handle (buttons, focus navigation, etc.)
        if self.ui_manager.handle_event(event):
            return

        # Phase-specific handling
        if self.phase == "verify" and event_type == "START":
            self._on_verify_submit()
            return

        if self.phase == "link_device" and event_type == "START":
            self._on_link_submit()
            return
