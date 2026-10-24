"""
OmninetService - Python client for Omninet API
Handles device linking, auto-login, and API communication with Omninet server.
"""
import json
import os
import threading
import requests
from urllib.parse import urljoin
from typing import Optional, Tuple, Dict, Any

from core import runtime_globals, constants

#: What the player reads when Omninet answers with something that is not its
#: JSON (an HTML error page from a proxy, a cut-off body): the parser's own
#: text ("Expecting value: line 1 column 1") meant nothing to anyone.
UNREADABLE_ANSWER = "Omninet is not answering properly, try again later"


def _readable(exc):
    """A message for the player from an exception caught around a request."""
    if isinstance(exc, ValueError):          # json.JSONDecodeError and kin
        return UNREADABLE_ANSWER
    return "Omninet request failed, try again later"


class OmninetService:
    """API client for Omninet server communication."""

    #: Seconds a team registration or an arena battle may take: the server
    #: runs its battle engine before it answers.
    ARENA_TIMEOUT = 20
    
    # Singleton instance
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """Singleton pattern to ensure only one instance exists."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """Initialize the Omninet service."""
        if self._initialized:
            return
        
        self._initialized = True
        self._device_key: Optional[str] = None
        self._device_id: Optional[str] = None
        self._player_id: Optional[str] = None  # Cached player UUID from server
        self._user_info: Optional[Dict[str, Any]] = None
        self.last_purchase_id: Optional[str] = None  # the row purchase_item made
        self.last_coins_remaining: Optional[int] = None  # the balance it left
        self.last_points_remaining: Optional[int] = None  # contribution points it left
        self._timeout = 5  # seconds
        
        # Path for storing device credentials
        self._credentials_path = self._get_credentials_path()
        
        # Load saved credentials on init
        self._load_credentials()
    
    def _get_credentials_path(self) -> str:
        """Get the path to the credentials file.

        Uses the same base save directory as game_mode preferences so the
        device key lives outside the bundle on every platform (notably
        android.storage.app_storage_path()/save on Android).
        """
        try:
            from core.game_globals import _get_base_save_dir
            base = _get_base_save_dir()
        except Exception:
            base = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                'save',
            )
        os.makedirs(base, exist_ok=True)
        return os.path.join(base, 'omninet_device.json')
    
    def _get_base_url(self) -> str:
        """Get the Omninet server base URL.

        Always returns the production URL.  To point at a different server
        during development set the OMNIPET_OMNINET_URL environment variable
        (e.g. ``export OMNIPET_OMNINET_URL=https://dev.omnipet.app.br``).
        """
        override = os.environ.get('OMNIPET_OMNINET_URL', '').strip()
        if override:
            return override.rstrip('/')
        main_url = getattr(constants, 'OMNINET_MAIN_URL', None)
        if main_url:
            return main_url.rstrip('/')
        return 'https://dev.omnipet.app.br'
    
    def _load_credentials(self) -> None:
        """Load saved device credentials from file."""
        try:
            if os.path.exists(self._credentials_path):
                with open(self._credentials_path, 'r') as f:
                    data = json.load(f)
                    self._device_key = data.get('device_key')
                    self._device_id = data.get('device_id')
                    self._player_id = data.get('player_id')
                    runtime_globals.game_console.log("[OmninetService] Loaded saved credentials")
        except Exception as e:
            runtime_globals.game_console.log(f"[OmninetService] Failed to load credentials: {e}")
    
    def _save_credentials(self) -> None:
        """Save device credentials to file."""
        try:
            os.makedirs(os.path.dirname(self._credentials_path), exist_ok=True)
            with open(self._credentials_path, 'w') as f:
                json.dump({
                    'device_key': self._device_key,
                    'device_id': self._device_id,
                    'player_id': self._player_id,
                }, f)
            runtime_globals.game_console.log("[OmninetService] Saved credentials")
        except Exception as e:
            runtime_globals.game_console.log(f"[OmninetService] Failed to save credentials: {e}")
    
    def _clear_credentials(self) -> None:
        """Clear saved device credentials."""
        self._device_key = None
        self._device_id = None
        self._player_id = None
        self._user_info = None
        try:
            if os.path.exists(self._credentials_path):
                os.remove(self._credentials_path)
                runtime_globals.game_console.log("[OmninetService] Cleared credentials")
        except Exception as e:
            runtime_globals.game_console.log(f"[OmninetService] Failed to clear credentials: {e}")
    
    def check_availability(self) -> bool:
        """Check if Omninet server is available."""
        try:
            base_url = self._get_base_url()
            response = requests.get(urljoin(base_url, '/health'), timeout=2)
            return response.status_code == 200
        except Exception:
            return False
    
    def validate_pairing_code(self, code: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Validate a pairing code and link this device.
        
        Args:
            code: The 4-character pairing code from Module Editor
            
        Returns:
            Tuple of (success, message, user_info)
        """
        try:
            base_url = self._get_base_url()
            url = urljoin(base_url, '/api/v1/auth/validate-pairing-code')
            
            runtime_globals.game_console.log(f"[OmninetService] Validating pairing code: {code}")
            
            response = requests.post(
                url,
                json={'code': code.upper()},
                timeout=self._timeout
            )
            
            runtime_globals.game_console.log(f"[OmninetService] Response status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                self._device_key = data.get('secret_key')
                self._device_id = data.get('device_id')
                
                # Save credentials
                self._save_credentials()
                
                # Validate the device to get user info
                success, msg, user_info = self.validate_device()
                if success and user_info:
                    return True, data.get('message', 'Device linked successfully!'), user_info
                
                return True, data.get('message', 'Device linked successfully!'), None
            else:
                try:
                    error_msg = response.json().get('detail', 'Invalid or expired code')
                except ValueError:
                    error_msg = UNREADABLE_ANSWER
                runtime_globals.game_console.log(f"[OmninetService] Pairing failed: {error_msg}")
                return False, error_msg, None
                
        except requests.exceptions.Timeout:
            runtime_globals.game_console.log("[OmninetService] Request timeout")
            return False, "Connection timeout", None
        except requests.exceptions.ConnectionError:
            runtime_globals.game_console.log("[OmninetService] Connection error")
            return False, "Cannot connect to server", None
        except Exception as e:
            runtime_globals.game_console.log(f"[OmninetService] Error: {e}")
            return False, _readable(e), None
    
    def validate_device(self) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Validate saved device credentials and get user info.
        Used for auto-login on startup.
        
        Returns:
            Tuple of (success, message, user_info)
        """
        if not self._device_key:
            return False, "No device credentials", None
        
        try:
            base_url = self._get_base_url()
            url = urljoin(base_url, '/api/v1/auth/validate-device')
            
            runtime_globals.game_console.log("[OmninetService] Validating device credentials")
            
            headers = {
                'X-Device-Key': self._device_key,
                'Content-Type': 'application/json'
            }
            
            response = requests.post(
                url,
                headers=headers,
                json={},
                timeout=self._timeout
            )
            
            runtime_globals.game_console.log(f"[OmninetService] Response status: {response.status_code}")
            
            if response.status_code == 200:
                self._user_info = response.json()
                # Cache player_id from server response
                server_player_id = self._user_info.get('id')
                if server_player_id:
                    self._player_id = str(server_player_id)
                    self._save_credentials()
                runtime_globals.game_console.log(f"[OmninetService] Logged in as: {self._user_info.get('nickname')}")
                return True, "Device validated", self._user_info
            else:
                try:
                    error_msg = response.json().get('detail', 'Device validation failed')
                except ValueError:
                    error_msg = UNREADABLE_ANSWER
                runtime_globals.game_console.log(f"[OmninetService] Validation failed: {error_msg}")
                # Only a refused key is forgotten: a server error (500, a
                # restart) used to log the player out and send them through
                # the e-mailed code again.
                if response.status_code in (401, 403):
                    self._clear_credentials()
                return False, error_msg, None
                
        except requests.exceptions.Timeout:
            return False, "Connection timeout", None
        except requests.exceptions.ConnectionError:
            return False, "Cannot connect to server", None
        except Exception as e:
            runtime_globals.game_console.log(f"[OmninetService] Error: {e}")
            return False, _readable(e), None
    
    def logout(self) -> bool:
        """
        Logout and clear device credentials.
        
        Returns:
            True if logout was successful
        """
        # Revoke this device's key on the server: deleting the device is what
        # does it (DELETE /users/me/devices/{id}). It posted to
        # /auth/logout, which the server does not have, so the key stayed
        # valid for anyone holding it (online finding 2).
        if self._device_key and self._device_id:
            try:
                base_url = self._get_base_url()
                url = urljoin(base_url, f'/api/v1/users/me/devices/{self._device_id}')
                response = requests.delete(
                    url,
                    headers={'X-Device-Key': self._device_key},
                    timeout=self._timeout
                )
                runtime_globals.game_console.log(f"[OmninetService] Logout response: {response.status_code}")
            except Exception as e:
                runtime_globals.game_console.log(f"[OmninetService] Logout error: {e}")
        
        # Clear local credentials regardless of server response
        self._clear_credentials()
        return True
    
    # =========================================================================
    # Account Auth Methods (register, login, verify, resend)
    # =========================================================================

    def register(self, nickname: str, email: str, password: str) -> Tuple[bool, str]:
        """
        Register a new user account.
        On success the server sends a verification code to the email.

        Args:
            nickname: Desired display name (3-100 chars, alphanumeric/_ /-).
            email:    Valid email address.
            password: At least 6 characters.

        Returns:
            (success, message) — message is the server detail string.
        """
        try:
            base_url = self._get_base_url()
            url = urljoin(base_url, '/api/v1/auth/register')
            response = requests.post(
                url,
                json={'nickname': nickname, 'email': email, 'password': password},
                timeout=self._timeout,
            )
            data = response.json() if response.content else {}
            if response.status_code == 200:
                msg = data.get('message', 'Verification code sent')
                runtime_globals.game_console.log(f"[OmninetService] Register OK: {msg}")
                return True, msg
            detail = data.get('detail', 'Registration failed')
            runtime_globals.game_console.log(f"[OmninetService] Register fail: {detail}")
            return False, detail
        except requests.exceptions.Timeout:
            return False, "Connection timeout"
        except requests.exceptions.ConnectionError:
            return False, "Cannot connect to server"
        except Exception as e:
            runtime_globals.game_console.log(f"[OmninetService] Register error: {e}")
            return False, _readable(e)

    def verify_registration(self, email: str, code: str) -> Tuple[bool, str]:
        """
        Verify registration with the 6-char code sent to email.
        On success, a device key is created and stored automatically.

        Returns:
            (success, message)
        """
        try:
            base_url = self._get_base_url()
            url = urljoin(base_url, '/api/v1/auth/verify-registration')
            response = requests.post(
                url,
                json={'email': email, 'code': code},
                timeout=self._timeout,
            )
            data = response.json() if response.content else {}
            if response.status_code == 200:
                self._device_key = data.get('secret_key')
                self._device_id = data.get('device_id')
                self._save_credentials()
                # Validate device to get full user info + player_id
                self.validate_device()
                msg = data.get('message', 'Account verified')
                runtime_globals.game_console.log(f"[OmninetService] VerifyReg OK: {msg}")
                return True, msg
            detail = data.get('detail', 'Verification failed')
            runtime_globals.game_console.log(f"[OmninetService] VerifyReg fail: {detail}")
            return False, detail
        except requests.exceptions.Timeout:
            return False, "Connection timeout"
        except requests.exceptions.ConnectionError:
            return False, "Cannot connect to server"
        except Exception as e:
            runtime_globals.game_console.log(f"[OmninetService] VerifyReg error: {e}")
            return False, _readable(e)

    def login_request(self, email: str, password: str) -> Tuple[bool, str]:
        """
        Login with email and password.
        On success the server sends a verification code to the email.

        Returns:
            (success, message)
        """
        try:
            base_url = self._get_base_url()
            url = urljoin(base_url, '/api/v1/auth/login')
            response = requests.post(
                url,
                json={'email': email, 'password': password},
                timeout=self._timeout,
            )
            data = response.json() if response.content else {}
            if response.status_code == 200:
                msg = data.get('message', 'Verification code sent')
                runtime_globals.game_console.log(f"[OmninetService] Login OK: {msg}")
                return True, msg
            detail = data.get('detail', 'Login failed')
            runtime_globals.game_console.log(f"[OmninetService] Login fail: {detail}")
            return False, detail
        except requests.exceptions.Timeout:
            return False, "Connection timeout"
        except requests.exceptions.ConnectionError:
            return False, "Cannot connect to server"
        except Exception as e:
            runtime_globals.game_console.log(f"[OmninetService] Login error: {e}")
            return False, _readable(e)

    def verify_login(self, email: str, code: str,
                     clear_devices: bool = False) -> Tuple[bool, str]:
        """
        Verify login with the 6-char code.
        On success, a device key is created and stored automatically.

        Args:
            email:         The email used during login_request().
            code:          6-character verification code.
            clear_devices: If True, revoke all other device keys first.

        Returns:
            (success, message)
        """
        try:
            base_url = self._get_base_url()
            url = urljoin(base_url, '/api/v1/auth/verify-login')
            response = requests.post(
                url,
                json={'email': email, 'code': code,
                      'clear_devices': clear_devices},
                timeout=self._timeout,
            )
            data = response.json() if response.content else {}
            if response.status_code == 200:
                self._device_key = data.get('secret_key')
                self._device_id = data.get('device_id')
                self._save_credentials()
                # Validate device to get full user info + player_id
                self.validate_device()
                msg = data.get('message', 'Login verified')
                runtime_globals.game_console.log(f"[OmninetService] VerifyLogin OK: {msg}")
                return True, msg
            detail = data.get('detail', 'Verification failed')
            runtime_globals.game_console.log(f"[OmninetService] VerifyLogin fail: {detail}")
            return False, detail
        except requests.exceptions.Timeout:
            return False, "Connection timeout"
        except requests.exceptions.ConnectionError:
            return False, "Cannot connect to server"
        except Exception as e:
            runtime_globals.game_console.log(f"[OmninetService] VerifyLogin error: {e}")
            return False, _readable(e)

    def resend_code(self, email: str) -> Tuple[bool, str]:
        """
        Resend a verification code to the given email.

        Returns:
            (success, message)
        """
        try:
            base_url = self._get_base_url()
            url = urljoin(base_url, f'/api/v1/auth/resend-code?email={email}')
            response = requests.post(url, timeout=self._timeout)
            data = response.json() if response.content else {}
            if response.status_code == 200:
                msg = data.get('message', 'Code resent')
                runtime_globals.game_console.log(f"[OmninetService] Resend OK: {msg}")
                return True, msg
            detail = data.get('detail', 'Failed to resend code')
            runtime_globals.game_console.log(f"[OmninetService] Resend fail: {detail}")
            return False, detail
        except requests.exceptions.Timeout:
            return False, "Connection timeout"
        except requests.exceptions.ConnectionError:
            return False, "Cannot connect to server"
        except Exception as e:
            runtime_globals.game_console.log(f"[OmninetService] Resend error: {e}")
            return False, _readable(e)

    def is_logged_in(self) -> bool:
        """Check if device is linked and has valid credentials."""
        return self._device_key is not None and self._user_info is not None
    
    def get_username(self) -> Optional[str]:
        """Get the logged in user's nickname."""
        if self._user_info:
            return self._user_info.get('nickname')
        return None
    
    def get_user_info(self) -> Optional[Dict[str, Any]]:
        """Get the full user info."""
        return self._user_info
    
    def get_device_key(self) -> Optional[str]:
        """Get the device key for authenticated requests."""
        return self._device_key
    
    def has_saved_credentials(self) -> bool:
        """Check if there are saved credentials (for auto-login attempt)."""
        return self._device_key is not None

    def get_player_id(self) -> Optional[str]:
        """Get the cached player ID (UUID) from credentials.

        The player ID is extracted from the server's UserResponse on
        validate_device() or validate_pairing_code() and cached locally
        in omninet_device.json.  It is used as the save-folder name
        for Progress Mode.

        Returns:
            Player UUID string if available, None otherwise.
        """
        return self._player_id
    
    # =========================================================================
    # Shop API Methods
    # =========================================================================
    
    def _make_request(self, method: str, endpoint: str, json_data: dict = None, 
                      require_auth: bool = True, timeout: float = None) -> Tuple[bool, Any]:
        """
        Make an API request with optional authentication.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path
            json_data: Optional JSON body data
            require_auth: Whether to include device key header
            
        Returns:
            Tuple of (success, data/error_message)
        """
        try:
            base_url = self._get_base_url()
            url = urljoin(base_url, endpoint)
            
            headers = {'Content-Type': 'application/json'}
            if require_auth and self._device_key:
                headers['X-Device-Key'] = self._device_key
            
            timeout = timeout or self._timeout
            if method.upper() == 'GET':
                response = requests.get(url, headers=headers, timeout=timeout)
            elif method.upper() == 'POST':
                response = requests.post(url, headers=headers, json=json_data or {}, timeout=timeout)
            elif method.upper() == 'DELETE':
                response = requests.delete(url, headers=headers, timeout=timeout)
            else:
                return False, f"Unsupported method: {method}"
            
            if response.status_code == 200:
                try:
                    return True, response.json()
                except ValueError:
                    return False, UNREADABLE_ANSWER
            else:
                # Handle error responses
                try:
                    error_data = response.json() if response.content else {}
                    # For 422 validation errors, extract field errors
                    if response.status_code == 422 and 'detail' in error_data:
                        detail = error_data['detail']
                        if isinstance(detail, list) and len(detail) > 0:
                            # Extract first validation error message
                            first_error = detail[0]
                            if isinstance(first_error, dict):
                                msg = first_error.get('msg', str(first_error))
                                field = '.'.join(str(x) for x in first_error.get('loc', []))
                                return False, f"{field}: {msg}" if field else msg
                        elif isinstance(detail, str):
                            return False, detail
                    # For other errors, get detail or fallback
                    return False, error_data.get('detail', f'Request failed: {response.status_code}')
                except:
                    return False, f'Request failed: {response.status_code}'
                
        except requests.exceptions.Timeout:
            return False, "Connection timeout"
        except requests.exceptions.ConnectionError:
            return False, "Cannot connect to server"
        except Exception as e:
            runtime_globals.game_console.log(f"[OmninetService] Request error: {e}")
            return False, _readable(e)
    
    def get_shop_modules(self, category: str = None) -> Tuple[bool, list]:
        """Get list of modules available in shop.

        Sends the device key (when logged in) so the server can apply
        per-user pricing — namely 0 for the player's free first module in
        Progress Mode.  The listing itself is public, so a missing device
        key simply yields the standard fixed price.
        """
        endpoint = '/api/v1/shop/modules'
        if category:
            endpoint += f'?category={category}'
        success, data = self._make_request('GET', endpoint, require_auth=True)
        if success and isinstance(data, dict):
            return True, data.get('modules', [])
        return success, data if isinstance(data, list) else []
    
    def get_shop_gameplay(self) -> Tuple[bool, list]:
        """Get list of gameplay items available in shop."""
        success, data = self._make_request('GET', '/api/v1/shop/gameplay', require_auth=False)
        if success and isinstance(data, dict):
            return True, data.get('gameplay', [])
        return success, data if isinstance(data, list) else []
    
    def get_shop_items(self) -> Tuple[bool, list]:
        """Get list of items available in shop."""
        success, data = self._make_request('GET', '/api/v1/shop/items', require_auth=False)
        if success and isinstance(data, dict):
            return True, data.get('items', [])
        return success, data if isinstance(data, list) else []
    
    def get_shop_cosmetics(self) -> Tuple[bool, list]:
        """Get list of cosmetics available in shop."""
        success, data = self._make_request('GET', '/api/v1/shop/cosmetics', require_auth=False)
        if success and isinstance(data, dict):
            return True, data.get('cosmetics', [])
        return success, data if isinstance(data, list) else []
    
    def get_shop_specials(self) -> Tuple[bool, list]:
        """Get list of special items available in shop."""
        success, data = self._make_request('GET', '/api/v1/shop/specials', require_auth=False)
        if success and isinstance(data, dict):
            return True, data.get('specials', [])
        return success, data if isinstance(data, list) else []
    
    def purchase_item(self, item_type: str, item_id: str) -> Tuple[bool, str]:
        """
        Purchase an item from the shop.
        
        Args:
            item_type: Type of item (module, cosmetic, gameplay, item, special)
            item_id: The item's GUID
            
        Returns:
            Tuple of (success, message)
        """
        if not self._device_key:
            return False, "Not logged in"

        self.last_purchase_id = None
        self.last_coins_remaining = None
        self.last_points_remaining = None
        success, data = self._make_request('POST', '/api/v1/shop/purchase', {
            'purchase_type': item_type,  # Server expects 'purchase_type', not 'item_type'
            'item_id': item_id
        })

        if success and isinstance(data, dict):
            # A refused purchase (not enough coins, already owned) is HTTP 200
            # with success false: it used to be booked as bought, the coins
            # taken and the item granted locally.
            if data.get('success', True) is False:
                return False, data.get('message') or 'Purchase refused'
            # The row an item purchase made, so the account sync does not
            # count that item a second time (GamePurchases.apply_item_purchase)
            self.last_purchase_id = data.get('purchase_id')
            # The account's balance after it: what the server charged, which
            # a listing loaded earlier may not show (the free first module)
            remaining = data.get('coins_remaining')
            self.last_coins_remaining = remaining if isinstance(remaining, int) else None
            # A Special priced in contribution points leaves the coins alone
            # and answers with what is left of the points.
            points = data.get('contribution_points_remaining')
            self.last_points_remaining = points if isinstance(points, int) else None
            if self.last_points_remaining is not None and self._user_info is not None:
                self._user_info['contribution_points'] = self.last_points_remaining
            return True, data.get('message', 'Purchase successful')
        return False, data if isinstance(data, str) else 'Purchase failed'
    
    def download_module(self, module_id: str) -> Tuple[bool, Any]:
        """Download a purchased module."""
        if not self._device_key:
            return False, "Not logged in"
        return self._make_request('GET', f'/api/v1/shop/download/module/{module_id}')

    def download_module_free(self, module_id: str) -> Tuple[bool, Any]:
        """Download a module for free (Free Mode). Uses public module download endpoint."""
        return self._make_request('GET', f'/api/v1/modules/{module_id}/download', require_auth=False)

    def download_module_zip(self, module_id: str, progress_cb=None) -> Tuple[bool, Any]:
        """Download a module as raw zip bytes.

        Streams the response (so Android downloads don't time out on large
        modules) and calls progress_cb(percent_int, downloaded_bytes,
        total_bytes) when total is known.  Returns (True, bytes) on
        success or (False, error_message) on failure.
        """
        try:
            base_url = self._get_base_url()
            url = urljoin(base_url, f'/api/v1/modules/{module_id}/download')
            headers = {}
            if self._device_key:
                headers['X-Device-Key'] = self._device_key
            # Long timeout for the connect phase; per-chunk reads use the
            # same stream so a slow Android connection won't 5-second-out.
            response = requests.get(url, headers=headers, timeout=60, stream=True)
            if response.status_code != 200:
                return False, f"Server returned {response.status_code}"
            total = int(response.headers.get('Content-Length', 0) or 0)
            downloaded = 0
            chunks = []
            for chunk in response.iter_content(chunk_size=128 * 1024):
                if not chunk:
                    continue
                chunks.append(chunk)
                downloaded += len(chunk)
                if progress_cb and total > 0:
                    try:
                        progress_cb(int(downloaded * 100 / total), downloaded, total)
                    except Exception:
                        pass
            if progress_cb:
                try:
                    progress_cb(100, downloaded, downloaded)
                except Exception:
                    pass
            return True, b"".join(chunks)
        except requests.exceptions.Timeout:
            return False, "Download timeout"
        except requests.exceptions.ConnectionError:
            return False, "Cannot connect to server"
        except Exception as e:
            runtime_globals.game_console.log(
                f"[OmninetService] download_module_zip error: {e}")
            return False, _readable(e)

    def get_module_sprite(self, module_id: str, sprite_type: str):
        """Fetch a module sprite image ('icon' or 'logo'). Returns a pygame.Surface or None."""
        import io
        import pygame
        try:
            base_url = self._get_base_url()
            url = urljoin(base_url, f'/api/v1/modules/{module_id}/{sprite_type}')
            response = requests.get(url, timeout=self._timeout)
            if response.status_code == 200:
                return pygame.image.load(io.BytesIO(response.content)).convert_alpha()
        except Exception as e:
            runtime_globals.game_console.log(f"[OmninetService] Sprite fetch error ({sprite_type}): {e}")
        return None

    def get_user_purchases(self):
        """Fetch the player's full purchase history from the server.

        Returns (success, data) where data is the parsed JSON dict on
        success (typically ``{'purchases': [...], 'total': N}``).
        """
        if not self._device_key:
            return False, "Not logged in"
        return self._make_request('GET', '/api/v1/shop/purchases')

    def get_shop_sprite(self, kind: str, item_id: str):
        """Fetch a shop entry's sprite image.

        Args:
            kind: one of 'item', 'cosmetic', 'gameplay', 'special' — used
                  to build the URL ``/api/v1/shop/{kind}/{id}/sprite``.
            item_id: the shop entry's server UUID.

        Returns a pygame.Surface or None on any failure.
        """
        import io
        import pygame
        data = self.get_shop_sprite_bytes(kind, item_id)
        if not data:
            return None
        try:
            return pygame.image.load(io.BytesIO(data)).convert_alpha()
        except Exception as e:
            runtime_globals.game_console.log(
                f"[OmninetService] Shop sprite fetch error ({kind}/{item_id}): {e}")
        return None

    def get_shop_sprite_bytes(self, kind: str, item_id: str) -> Optional[bytes]:
        """The image file of a shop entry's sprite (``get_shop_sprite``), as
        the server sends it, for the game to keep: a bought item's icon, a
        background whose download carried no picture. None on any failure."""
        if not item_id:
            return None
        try:
            base_url = self._get_base_url()
            url = urljoin(base_url, f'/api/v1/shop/{kind}/{item_id}/sprite')
            response = requests.get(url, timeout=self._timeout)
            if response.status_code == 200 and response.content:
                return response.content
        except Exception as e:
            runtime_globals.game_console.log(
                f"[OmninetService] Shop sprite fetch error ({kind}/{item_id}): {e}")
        return None

    def download_gameplay(self, gameplay_id: str) -> Tuple[bool, Any]:
        """Download a purchased gameplay item."""
        if not self._device_key:
            return False, "Not logged in"
        return self._make_request('GET', f'/api/v1/shop/download/gameplay/{gameplay_id}')
    
    def download_cosmetic(self, cosmetic_id: str) -> Tuple[bool, Any]:
        """Download a purchased cosmetic."""
        if not self._device_key:
            return False, "Not logged in"
        return self._make_request('GET', f'/api/v1/shop/download/cosmetic/{cosmetic_id}')
    
    def download_item(self, item_id: str) -> Tuple[bool, Any]:
        """Download a purchased item."""
        if not self._device_key:
            return False, "Not logged in"
        return self._make_request('GET', f'/api/v1/shop/download/item/{item_id}')

    # ------------------------------------------------------------------
    # Specials and contribution points
    # ------------------------------------------------------------------

    def get_contribution_points(self) -> Optional[int]:
        """The account's contribution points as last read from the server
        (earned on the Digimon Database; a balance apart from the coins)."""
        if not self._user_info:
            return None
        value = self._user_info.get('contribution_points')
        return int(value) if isinstance(value, int) else None

    def refresh_user_info(self) -> Tuple[bool, Any]:
        """Read the account again (balances included): contribution points
        are earned outside the game, so the Specials page asks each time it
        opens. Unlike validate_device, a refusal here keeps the credentials."""
        if not self._device_key:
            return False, "Not logged in"
        success, data = self._make_request('POST', '/api/v1/auth/validate-device')
        if success and isinstance(data, dict) and data.get('id'):
            self._user_info = data
            return True, data
        return False, data

    def get_special_preview(self, item_id: str, small: bool = True):
        """A Special's preview picture as a Surface, or None. *small* asks
        for a background's 96x96 day picture (the server's default is the
        1024x1024 one, a few MB each)."""
        import io
        import pygame
        if not item_id:
            return None
        try:
            base_url = self._get_base_url()
            url = urljoin(base_url, f'/api/v1/shop/special/{item_id}/sprite')
            response = requests.get(url, params={'size': 'small'} if small else None,
                                    timeout=self._timeout)
            if response.status_code == 200 and response.content:
                return pygame.image.load(io.BytesIO(response.content)).convert_alpha()
        except Exception as e:
            runtime_globals.game_console.log(
                f"[OmninetService] Special preview error ({item_id}): {e}")
        return None

    def download_special(self, special_id: str) -> Tuple[bool, Any]:
        """Download a bought Special: for a background, every picture it has
        as base64 (day/dusk/night, normal and _high: up to ~10 MB), hence the
        long timeout."""
        if not self._device_key:
            return False, "Not logged in"
        return self._make_request('GET', f'/api/v1/shop/download/special/{special_id}',
                                  timeout=120)

    # ------------------------------------------------------------------
    # Arena / Teams / Battles / Seasons
    # ------------------------------------------------------------------

    def get_current_season(self) -> Tuple[bool, Any]:
        """Fetch the running season (404 between seasons)."""
        return self._make_request('GET', '/api/v1/seasons/current', require_auth=False)

    def get_arena_modules(self) -> Tuple[bool, Any]:
        """Modules installed on the server for this season's battles.

        Pets from any other module cannot join an arena team.
        """
        return self._make_request('GET', '/api/v1/arena/modules', require_auth=False)

    def get_user_teams(self, include_past: bool = False) -> Tuple[bool, Any]:
        """List the player's teams (current season + any with unclaimed rewards)."""
        if not self._device_key:
            return False, "Not logged in"
        endpoint = f'/api/v1/teams?include_past={"true" if include_past else "false"}'
        return self._make_request('GET', endpoint)

    def get_team(self, team_id: str) -> Tuple[bool, Any]:
        """One of the player's teams with its pets (any season)."""
        if not self._device_key:
            return False, "Not logged in"
        return self._make_request('GET', f'/api/v1/teams/{team_id}')

    def get_current_team(self) -> Tuple[bool, Any]:
        """Get the player's team for the current season (or 404 if none)."""
        if not self._device_key:
            return False, "Not logged in"
        return self._make_request('GET', '/api/v1/teams/current')

    def create_team(self, pets: list, team_name: Optional[str] = None) -> Tuple[bool, Any]:
        """
        Create an arena team.

        Args:
            pets: one dict per pet naming the species (name, module_name,
                  module_version, pet_version) and carrying its care
                  ``status``, its ``uid``, the species values the game
                  holds (``base``) and its full save copy (``pet_json``).
                  The server rebuilds stage, attribute, power, HP and
                  attacks from its own copy of the module.
            team_name: optional display name for the team.
        """
        if not self._device_key:
            return False, "Not logged in"
        # The server's engine rebuilds and checks every pet: allow it time.
        return self._make_request('POST', '/api/v1/teams', {
            'name': team_name,
            'pets': pets,
        }, timeout=max(self._timeout, self.ARENA_TIMEOUT))

    def deactivate_team(self, team_id: str) -> Tuple[bool, Any]:
        """Soft-delete (deactivate) an arena team."""
        if not self._device_key:
            return False, "Not logged in"
        return self._make_request('DELETE', f'/api/v1/teams/{team_id}')

    def claim_team_rewards(self) -> Tuple[bool, Any]:
        """Claim all unclaimed coin rewards across the player's teams."""
        if not self._device_key:
            return False, "Not logged in"
        success, data = self._make_request('POST', '/api/v1/teams/claim-rewards')
        if success and isinstance(data, dict):
            new_balance = data.get('new_balance')
            if new_balance is not None and self._user_info is not None:
                self._user_info['coins'] = new_balance
        return success, data

    def get_team_battles(self, team_id: str) -> Tuple[bool, Any]:
        """Get the battle history for one team."""
        if not self._device_key:
            return False, "Not logged in"
        return self._make_request('GET', f'/api/v1/battles/team/{team_id}/history')

    def get_battle(self, battle_id: str) -> Tuple[bool, Any]:
        """Get one battle's full data (including the simulator log for replay)."""
        if not self._device_key:
            return False, "Not logged in"
        return self._make_request('GET', f'/api/v1/battles/{battle_id}')

    def find_battle(self, team_id: str) -> Tuple[bool, Any]:
        """
        Find an opponent and execute a battle for the given team.

        On success the response includes the battle record; the client can
        then replay it from the simulator log.  Server enforces the
        per-team daily battle cap.
        """
        if not self._device_key:
            return False, "Not logged in"
        # The server fights the whole battle before answering.
        return self._make_request('POST', f'/api/v1/battles/find/{team_id}',
                                  timeout=max(self._timeout, self.ARENA_TIMEOUT))

    def get_season_standings(self, season_id: str, limit: int = 50) -> Tuple[bool, Any]:
        """A season's table (live while it runs, final once closed); the
        player's own row is flagged ``is_you``."""
        return self._make_request(
            'GET', f'/api/v1/seasons/{season_id}/standings?limit={int(limit)}',
            require_auth=bool(self._device_key))

    def get_season_winners(self, season_id: str) -> Tuple[bool, Any]:
        """A finished season's podium."""
        return self._make_request('GET', f'/api/v1/seasons/{season_id}/winners',
                                  require_auth=False)

    def get_arena_winners(self, user_id: str = None, limit: int = 30) -> Tuple[bool, Any]:
        """Every finished season's podium, newest first (one player's with
        *user_id*)."""
        query = f'?limit={int(limit)}' + (f'&user_id={user_id}' if user_id else '')
        return self._make_request('GET', f'/api/v1/arena/winners{query}', require_auth=False)

    # ------------------------------------------------------------------
    # Reward claims
    # ------------------------------------------------------------------

    def claim_reward(self, event_type: str, idempotency_key: str) -> None:
        """
        Fire-and-forget: grant the player coins for an in-game event.

        Only runs in Progress Mode (when the device key is available).
        Executes in a daemon thread so it never blocks gameplay.

        Args:
            event_type:      One of "unlock", "evolution", "new_pet", "adventure".
            idempotency_key: Stable key identifying this specific event instance.
                             The server rejects duplicate keys per player, so
                             callers must ensure uniqueness for distinct events
                             and stability (same value) for the same event.
        """
        from core import game_globals
        if not self._device_key or not game_globals.is_progress_mode():
            return

        def _worker():
            try:
                success, data = self._make_request('POST', '/api/v1/rewards/claim', {
                    'event_type': event_type,
                    'idempotency_key': idempotency_key,
                })
                if success and isinstance(data, dict):
                    # Different server endpoints name the new balance
                    # differently; accept the common variants.
                    total = (data.get('total_coins') if data.get('total_coins') is not None
                             else data.get('total') if data.get('total') is not None
                             else data.get('new_balance') if data.get('new_balance') is not None
                             else data.get('coins'))
                    if total is not None:
                        if self._user_info is not None:
                            self._user_info['coins'] = total
                        # Mirror the server balance into the local coin total —
                        # that is what the shop / HUD actually read and spend.
                        try:
                            game_globals.coins = int(total)
                            game_globals.save()
                        except Exception:
                            pass
                    runtime_globals.game_console.log(
                        f"[OmninetService] Reward claimed: {event_type} "
                        f"(+{data.get('coins_awarded', '?')} coins, total {total})"
                    )
                else:
                    runtime_globals.game_console.log(
                        f"[OmninetService] Reward claim skipped ({event_type}): {data}"
                    )
            except Exception as e:
                runtime_globals.game_console.log(
                    f"[OmninetService] Reward claim error ({event_type}): {e}"
                )

        threading.Thread(target=_worker, daemon=True).start()


# Global singleton instance
omninet_service = OmninetService()
