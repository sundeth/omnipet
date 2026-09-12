import datetime
import os
import pickle
import random
import time

from models.game_configuration import GameConfiguration
from models.game_purchases import GamePurchases

#=====================================================================
# Game Mode Constants
#=====================================================================
GAME_MODE_FREE = 0       # Free Mode: all unlocked, no arena, limited shop
GAME_MODE_PROGRESS = 1   # Progression Mode: earn coins, full shop, arena access

#=====================================================================
# Game Global State
#=====================================================================

def _get_base_save_dir():
    """Get the base save directory (without game mode subfolder)."""
    from core import runtime_globals
    if runtime_globals.IS_ANDROID:
        try:
            from android.storage import app_storage_path # type: ignore
            save_dir = os.path.join(app_storage_path(), "save")
            os.makedirs(save_dir, exist_ok=True)
            return save_dir
        except Exception as e:
            print(f"[Save] Failed to get Android storage path: {e}")
            return "save"
    return "save"

def get_save_dir():
    """Get the appropriate save directory based on platform, game mode, and player.

    Returns:
        - save/Default     for Free Mode
        - save/<player_id>  for Progress Mode (when player_id is set)
        - save/_unlinked    for Progress Mode (before player_id is established)

    In Progress Mode, save/load operations are guarded by _can_access_save_dir()
    to prevent writing to the wrong folder before player_id is established.
    """
    base = _get_base_save_dir()
    if game_mode == GAME_MODE_FREE:
        subfolder = "Default"
    elif game_mode == GAME_MODE_PROGRESS:
        if player_id:
            subfolder = str(player_id)
        else:
            # No player_id yet — use a temporary placeholder folder.
            # save()/load() will refuse to operate until player_id is set.
            subfolder = "_unlinked"
    else:
        subfolder = "Default"
    save_dir = os.path.join(base, subfolder)
    os.makedirs(save_dir, exist_ok=True)
    return save_dir


def _can_access_save_dir() -> bool:
    """Check if save operations can safely proceed.

    Returns False if:
    - Game mode preference hasn't been chosen yet
    - Progress Mode is active but no player_id is set
    """
    if not has_game_mode_preference():
        return False
    if game_mode == GAME_MODE_PROGRESS and not player_id:
        return False
    return True

def migrate_legacy_saves():
    """Migrate save files from old folder structure to new structure.

    Handles three migration paths:
      1. Root save files (legacy) → Default/ folder
         (save_data*.dat, freezer.pkl, digidex.json at save/ root)
      2. Type0/ folder contents → Default/ folder
      3. Type1/ folder contents → <player_id>/ folder (only when player_id is set)

    Also copies the root digidex.json into the player's folder when applicable,
    because the old structure shared a single digidex across game modes.

    Safe to call multiple times — skips files that already exist at the destination.
    """
    base = _get_base_save_dir()
    default_dir = os.path.join(base, "Default")
    migrated = False

    # --- Migration 1: Root save files → Default/ ---
    os.makedirs(default_dir, exist_ok=True)
    for filename in os.listdir(base):
        filepath = os.path.join(base, filename)
        if not os.path.isfile(filepath):
            continue
        is_save = (
            filename == "save_data.dat"
            or (filename.startswith("save_data_") and filename.endswith(".dat"))
            or filename == "freezer.pkl"
            or filename == "digidex.json"
        )
        if is_save:
            dest = os.path.join(default_dir, filename)
            if not os.path.exists(dest):
                try:
                    os.rename(filepath, dest)
                    print(f"[Save] Migrated {filename} → Default/")
                    migrated = True
                except Exception as e:
                    print(f"[Save] Failed to migrate {filename}: {e}")

    # --- Migration 2: Type0/ → Default/ ---
    type0_dir = os.path.join(base, "Type0")
    if os.path.exists(type0_dir) and os.path.isdir(type0_dir):
        _migrate_folder_contents(type0_dir, default_dir, "Type0", "Default")
        # Remove Type0 if empty
        try:
            if not os.listdir(type0_dir):
                os.rmdir(type0_dir)
                print("[Save] Removed empty Type0/ folder")
        except Exception:
            pass
        migrated = True

    # --- Migration 3: Type1/ → <player_id>/ ---
    type1_dir = os.path.join(base, "Type1")
    if os.path.exists(type1_dir) and os.path.isdir(type1_dir) and player_id:
        player_dir = os.path.join(base, str(player_id))
        _migrate_folder_contents(type1_dir, player_dir, "Type1", str(player_id))
        # Also copy root digidex.json into the player folder if it wasn't there
        root_digidex = os.path.join(default_dir, "digidex.json")
        player_digidex = os.path.join(player_dir, "digidex.json")
        if os.path.exists(root_digidex) and not os.path.exists(player_digidex):
            import shutil
            try:
                shutil.copy2(root_digidex, player_digidex)
                print(f"[Save] Copied digidex.json → {player_id}/")
            except Exception as e:
                print(f"[Save] Failed to copy digidex to player folder: {e}")
        # Remove Type1 if empty
        try:
            if not os.listdir(type1_dir):
                os.rmdir(type1_dir)
                print("[Save] Removed empty Type1/ folder")
        except Exception:
            pass
        migrated = True

    if migrated:
        print("[Save] Legacy save migration complete.")


def _migrate_folder_contents(source_dir: str, dest_dir: str,
                             source_name: str, dest_name: str) -> None:
    """Move all files from source_dir into dest_dir.

    Skips files that already exist at the destination to avoid data loss.

    Args:
        source_dir: Absolute or relative path of the source folder.
        dest_dir: Absolute or relative path of the destination folder.
        source_name: Display name for log messages.
        dest_name: Display name for log messages.
    """
    os.makedirs(dest_dir, exist_ok=True)
    for filename in os.listdir(source_dir):
        src = os.path.join(source_dir, filename)
        if os.path.isfile(src):
            dest = os.path.join(dest_dir, filename)
            if not os.path.exists(dest):
                try:
                    os.rename(src, dest)
                    print(f"[Save] Migrated {filename}: {source_name}/ → {dest_name}/")
                except Exception as e:
                    print(f"[Save] Failed to migrate {filename}: {e}")

GAME_MODE_FILE = "game_mode.cfg"

def load_player_id() -> bool:
    """Load the player ID from cached omninet credentials.

    Must be called after load_game_mode_preference() when in Progress Mode.
    Sets the module-level player_id from the locally cached credentials file
    (omninet_device.json) so that get_save_dir() can resolve the correct folder.

    Returns:
        True if player_id was loaded, False if not available.
    """
    global player_id
    from services.omninet_service import omninet_service
    cached_id = omninet_service.get_player_id()
    if cached_id:
        player_id = cached_id
        print(f"[Save] Loaded player ID: {player_id}")
        return True
    print("[Save] No cached player ID found")
    return False


def set_player_id(new_player_id: str) -> None:
    """Set the player ID for Progress Mode save folder.

    Called after successful server validation or login.  Updates the
    module-level variable so get_save_dir() returns the correct path.

    Args:
        new_player_id: The player's unique UUID from the Omninet server.
    """
    global player_id
    player_id = str(new_player_id)
    print(f"[Save] Player ID set to: {player_id}")


def save_game_mode_preference() -> None:
    """Write the current game_mode to a simple cfg file in the root save folder.

    The file stores a single character: '0' for Free, '1' for Progress.
    This is read at startup *before* load() so get_save_dir() points at the
    correct subfolder.
    """
    base = _get_base_save_dir()
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, GAME_MODE_FILE)
    try:
        with open(path, "w") as f:
            f.write(str(game_mode))
        print(f"[Save] Game mode preference saved: {game_mode}")
    except Exception as e:
        print(f"[Save] Failed to save game mode preference: {e}")

def has_game_mode_preference() -> bool:
    """Check whether the game_mode.cfg file exists in the root save folder."""
    base = _get_base_save_dir()
    return os.path.exists(os.path.join(base, GAME_MODE_FILE))

def load_game_mode_preference() -> bool:
    """Read the game mode preference file and set game_mode accordingly.
    
    Must be called *before* load() so that get_save_dir() returns the right
    subfolder.  If the file does not exist the default (Progress) is kept and
    False is returned to signal that mode selection is still needed.
    
    Returns:
        True if the preference was loaded, False if the file was missing.
    """
    global game_mode
    base = _get_base_save_dir()
    path = os.path.join(base, GAME_MODE_FILE)
    if not os.path.exists(path):
        print("[Save] No game mode preference file found, keeping default")
        return False
    try:
        with open(path, "r") as f:
            value = f.read().strip()
        if value in ("0", "1"):
            game_mode = int(value)
            print(f"[Save] Loaded game mode preference: {game_mode}")
            return True
        else:
            print(f"[Save] Invalid game mode value '{value}', keeping default")
            return False
    except Exception as e:
        print(f"[Save] Failed to load game mode preference: {e}")
        return False

def is_free_mode() -> bool:
    """Check if the game is currently in Free Mode."""
    return game_mode == GAME_MODE_FREE

def is_progress_mode() -> bool:
    """Check if the game is currently in Progression Mode."""
    return game_mode == GAME_MODE_PROGRESS


#---------------------------------------------------------------------
# Arena pet pool
#---------------------------------------------------------------------

def send_pets_to_arena(pets: list) -> None:
    """Move the given pets out of pet_list and into the arena_pets pool.

    Called after a successful arena team upload.  Hides them from the
    rest of the game until the season ends.
    """
    global pet_list, arena_pets
    pet_ids = {id(p) for p in pets}
    arena_pets.extend(p for p in pet_list if id(p) in pet_ids)
    pet_list = [p for p in pet_list if id(p) not in pet_ids]


def return_pets_from_arena() -> list:
    """Move every arena pet back into pet_list. Returns the moved pets."""
    global pet_list, arena_pets
    returned = list(arena_pets)
    pet_list.extend(returned)
    arena_pets = []
    return returned


def freezer_deposit_pets(pets: list) -> int:
    """Append *pets* to the freezer pkl in the player's current save dir.

    Used by the arena reclaim flow: when a past season is reclaimed, the
    pets that were locked to that team are returned to the player —
    spec says "transferred to the freezer", so we drop them into the
    first freezer page(s) with a free slot rather than back into the
    active party (where they'd suddenly appear during gameplay).

    Returns the number of pets actually deposited.  Silently no-ops if
    the save dir can't be accessed or the freezer file can't be read.
    Empty `pets` returns 0.
    """
    if not pets:
        return 0
    import pickle
    try:
        save_dir = get_save_dir()
    except Exception as exc:
        from core import runtime_globals
        runtime_globals.game_console.log(
            f"[freezer_deposit_pets] no save dir: {exc}")
        return 0
    file_path = os.path.join(save_dir, "freezer.pkl")

    # Load existing freezer pages (or build empty ones if no file yet)
    freezer_pages = []
    if os.path.exists(file_path):
        try:
            with open(file_path, "rb") as f:
                freezer_pages = pickle.load(f) or []
        except Exception as exc:
            from core import runtime_globals
            runtime_globals.game_console.log(
                f"[freezer_deposit_pets] load failed: {exc}")
            freezer_pages = []

    if not freezer_pages:
        # Build a minimal freezer of 10 pages.  Done lazily to avoid
        # importing GameFreezer at module load time (circular risk).
        try:
            from models.game_freezer import GameFreezer
            freezer_pages = [
                GameFreezer([], i, "default_bg", "default_module",
                            game_mode=game_mode)
                for i in range(10)
            ]
        except Exception as exc:
            from core import runtime_globals
            runtime_globals.game_console.log(
                f"[freezer_deposit_pets] could not bootstrap freezer: {exc}")
            return 0

    # Stamp pages with current game mode so the next freezer scene load
    # accepts them.
    for page in freezer_pages:
        if not hasattr(page, 'game_mode') or page.game_mode == -1:
            page.game_mode = game_mode

    deposited = 0
    remaining = list(pets)
    for page in freezer_pages:
        if not remaining:
            break
        page_pets = list(getattr(page, 'pets', []) or [])
        # Each page has a fixed slot count; treat existing length as the
        # cap if available, else default to 12.
        cap = getattr(page, 'capacity', None) or 12
        while remaining and len(page_pets) < cap:
            page_pets.append(remaining.pop(0))
            deposited += 1
        page.pets = page_pets
        if hasattr(page, 'rebuild'):
            try:
                page.rebuild()
            except Exception:
                pass

    if not deposited and remaining:
        # No room anywhere — fall back to extending the last page
        try:
            freezer_pages[-1].pets = list(
                getattr(freezer_pages[-1], 'pets', []) or []) + remaining
            deposited = len(remaining)
        except Exception:
            pass

    try:
        os.makedirs(save_dir, exist_ok=True)
        with open(file_path, "wb") as f:
            pickle.dump(freezer_pages, f)
    except Exception as exc:
        from core import runtime_globals
        runtime_globals.game_console.log(
            f"[freezer_deposit_pets] save failed: {exc}")
        return 0
    return deposited


def is_pet_in_arena(pet) -> bool:
    """True if this pet object is currently in the arena pool."""
    return any(p is pet for p in arena_pets)

SAVE_FILE = "save/save_data.dat"  # Legacy reference, use get_save_dir() instead
SAVE_DIR = "save"  # Legacy reference, use get_save_dir() instead
MAX_BACKUPS = 10  # Keep 10 backup files

# Persistent variables
game_background = None
background_module_name = None
background_high_res = False

pet_list = []
poop_list = []
traited = []
gcell_fragments = []

#: Modules that have been renamed. A save keys almost everything by module
#: name -- adventure progress, unlocks, victories, cards, friends, and every
#: pet's own ``module`` -- so a rename would orphan all of it without this.
#: Read on load and written back under the new name; the old name never
#: reappears. Mirrors protocol_constants.LEGACY_FORMAT_NAMES, which does the
#: same for the battle format a module declares.
LEGACY_MODULE_NAMES = {"DM": "DMOG", "PEN": "PENOG"}

unlocks = {}
showClock = False
battle_area = {}
battle_round = {}
last_adventure_module = None  # Track last played adventure module
xai = 1
xai_date = datetime.date.today()
inventory = {}
battle_effects = {}
# Password redemptions: "module@CODE" -> unix timestamp of the last
# redemption. Used to enforce codes.json cooldowns (-1 = one use only).
redeemed_codes = {}
quests = []
event = None
event_time = None
total_victories = {}  # Track total battle victories per module: {module_name: count}
purchases = GamePurchases()  # Shop purchases
configuration = GameConfiguration()  # Centralized configuration
coins = 0  # Player's coin balance
# Per-module Friend lists: {module_name: [pet_name, ...]}.  A pet is added by
# battling an enemy marked as Friend; used by Xros temporary evolutions and
# the digidex "Friends" view.
friends = {}

# The Friend Event Battle promised by an area clear, or None.
#
#   {"pet": <pet name>, "module": <module name>, "minutes": <1-5>}
#
# Set when a pet that has DigiXros forms clears an area of its OWN module. The
# main game counts the minutes down and then spends it on an encounter with one
# of that pet's own missing Friends — a pet can never unlock another pet's
# Friends. Only one is held at a time; a newer clear overrides an older promise.
friend_event_pending = None

# Card collection state (see utils.card_utils):
#   card_collection: {module_name: {card_id:
#                     {"digital": n, "physical": n, "shiny": n}}}
# ``shiny`` is a subset of digital, not an additional ownership count.
#   card_cooldowns:  {card_id: unix timestamp of last digital use}
card_collection = {}
card_cooldowns = {}

# Pets currently uploaded to an active arena team are kept in this side list
# instead of pet_list while the season is running.  Functions that walk
# pet_list (battle, training, feeding, evolution, UI) therefore skip them
# automatically.  When the team's season closes (or the team is deactivated),
# pets are moved back to pet_list with their state preserved.
arena_pets = []
setup_input = True
setup_graphics = True
setup_game_mode = False  # Jump directly to mode selection, bypassing welcome
skip_tutorial_on_mode_switch = False  # Set when player has pets and switches mode from settings
show_tutorial = True
game_mode = GAME_MODE_PROGRESS  # Default to Progression Mode
player_id = None  # Player UUID for Progress Mode save folder (loaded from omninet credentials)

# Shop metadata caches — populated when the relevant shop view loads its
# listings so that downstream code (SceneInventory, the settings
# background selector, the training menu) can look up details for any
# purchased item without re-fetching from the server.  Keyed by the
# shop item's UUID string.
shop_items_data = {}        # id -> {name, sprite_name, description, ...}
shop_backgrounds = {}       # id -> {name, sprite_name, day_night, high_res, label}
shop_gameplay_data = {}     # id -> {name, description, item_type}

# Note: Python doesn't support module-level properties directly.
# Code should access these via configuration.* or use the helper functions.
# For backward compatibility, we define module-level variables that are updated
# during save/load operations.

# Internal timer for autosave
_last_save_time = time.time()
AUTOSAVE_INTERVAL_SECONDS = 60  # 5 minutes

def get_next_save_number():
    """Get the next save file number for backup rotation (1 to MAX_BACKUPS)."""
    save_dir = get_save_dir()
    if not os.path.exists(save_dir):
        return 1

    # Get the highest number and increment by 1
    latest_save = get_latest_save_file()
    if latest_save == None:
        next_number = 1
    else:
        latest_save = os.path.basename(latest_save)
        next_number = int(latest_save.replace("save_data_", "").replace(".dat", "")) + 1
    
    # If we exceed MAX_BACKUPS, wrap around to 1
    if next_number > MAX_BACKUPS:
        return 1
    
    return next_number

def get_latest_save_file():
    """Get the path to the most recent save file."""
    save_dir = get_save_dir()
    if not os.path.exists(save_dir):
        return None
    
    # Check if old save_data.dat exists and migrate it first
    old_save_path = os.path.join(save_dir, "save_data.dat")
    if os.path.exists(old_save_path):
        new_save_path = os.path.join(save_dir, "save_data_1.dat")
        try:
            os.rename(old_save_path, new_save_path)
            print(f"[Save] Migrated save_data.dat to save_data_1.dat")
        except Exception as e:
            print(f"[Save] Failed to migrate save_data.dat: {e}")
    
    # Find existing numbered save files
    save_files = []
    for filename in os.listdir(save_dir):
        if filename.startswith("save_data_") and filename.endswith(".dat"):
            try:
                number_part = filename.replace("save_data_", "").replace(".dat", "")
                full_path = os.path.join(save_dir, filename)
                save_files.append((int(number_part), full_path))
            except ValueError:
                continue
    
    if not save_files:
        return None

    # Return the most recent file
    save_files.sort(key=lambda x: os.path.getmtime(x[1]), reverse=True)
    return save_files[0][1]

def cleanup_old_saves():
    """Remove old backup saves beyond MAX_BACKUPS."""
    save_dir = get_save_dir()
    if not os.path.exists(save_dir):
        return
    
    # Find all numbered save files
    save_files = []
    for filename in os.listdir(save_dir):
        if filename.startswith("save_data_") and filename.endswith(".dat"):
            try:
                number_part = filename.replace("save_data_", "").replace(".dat", "")
                full_path = os.path.join(save_dir, filename)
                save_files.append((int(number_part), full_path))
            except ValueError:
                continue
    
    # Keep only the most recent MAX_BACKUPS files
    if len(save_files) > MAX_BACKUPS:
        save_files.sort(key=lambda x: os.path.getmtime(x[1]), reverse=True)
        files_to_remove = save_files[MAX_BACKUPS:]
        
        for _, file_path in files_to_remove:
            try:
                os.remove(file_path)
                print(f"[Save] Removed old backup: {os.path.basename(file_path)}")
            except Exception as e:
                print(f"[Save] Failed to remove old backup {file_path}: {e}")

def save() -> None:
    """
    Saves the current global game state to a file with backup rotation.
    Will not save if game mode preference has not been set yet,
    or if in Progress Mode without a player_id.
    """
    if not _can_access_save_dir():
        print("[Save] Skipping save - save directory not accessible")
        return
    
    # Ensure save directory exists
    save_dir = get_save_dir()
    if not os.path.exists(save_dir):
        try:
            os.makedirs(save_dir)
            print(f"[Save] Created save directory: {save_dir}")
        except Exception as e:
            print(f"[Save] Failed to create save directory: {e}")
            return

    data = {
        "pet_list": pet_list,
        "poop_list": poop_list,
        "traited": traited,
        "gcell_fragments": gcell_fragments,
        "game_background": game_background,
        "battle_area": battle_area,
        "battle_round": battle_round,
        "last_adventure_module": last_adventure_module,
        "background_module_name": background_module_name,
        "unlocks": unlocks,
        "showClock": showClock,
        "xai": xai,
        "xai_date": xai_date,
        "inventory": inventory,
        "battle_effects": battle_effects,
        "redeemed_codes": redeemed_codes,
        "background_high_res": background_high_res,
        "quests": quests,
        "event": event,
        "event_time": event_time,
        "total_victories": total_victories,
        "purchases": purchases.to_dict(),
        "coins": coins,
        "friends": friends,
        "friend_event_pending": friend_event_pending,
        "card_collection": card_collection,
        "card_cooldowns": card_cooldowns,
        "configuration": configuration.to_dict(),
        "setup_input": setup_input,
        "setup_graphics": setup_graphics,
        "show_tutorial": show_tutorial,
        "game_mode": game_mode,
        "player_id": player_id if game_mode == GAME_MODE_PROGRESS else None,
    }

    # Get the next save number and create the filename
    save_number = get_next_save_number()
    save_path = os.path.join(save_dir, f"save_data_{save_number}.dat")

    try:
        with open(save_path, "wb") as f:
            pickle.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        
        print(f"[Save] Game saved successfully to: {os.path.basename(save_path)}")
        
        # Clean up old saves
        cleanup_old_saves()
        
    except Exception as e:
        print(f"[Save] Failed to save game: {e}")

def _rename_saved_modules() -> None:
    """Move a renamed module's saved state onto its new name.

    Everything a save holds about a module is keyed by its name, so renaming
    one on disk would otherwise lose the player's adventure progress, its
    unlocks and its card collection, and leave every pet raised on it
    pointing at a module that no longer loads.

    An entry already under the new name wins -- the player has played since
    the rename, and that is the current state.
    """
    global pet_list, unlocks, battle_area, battle_round, total_victories
    global friends, card_collection, card_cooldowns
    global last_adventure_module, background_module_name

    renamed = []
    for old_name, new_name in LEGACY_MODULE_NAMES.items():
        for container in (unlocks, battle_area, battle_round, total_victories,
                          friends, card_collection, card_cooldowns):
            if isinstance(container, dict) and old_name in container:
                value = container.pop(old_name)
                container.setdefault(new_name, value)
                renamed.append(f"{old_name}->{new_name}")

        for pet in (pet_list or []):
            if getattr(pet, "module", None) == old_name:
                pet.module = new_name
                renamed.append(f"pet {getattr(pet, 'name', '?')}")

        if last_adventure_module == old_name:
            last_adventure_module = new_name
        if background_module_name == old_name:
            background_module_name = new_name

    if renamed:
        print(f"[Save] Migrated renamed modules: {len(renamed)} entry/entries "
              f"({', '.join(sorted(set(renamed))[:6])})")


def load() -> None:
    """
    Loads the global game state from the most recent save file, with fallback to previous saves.
    Will not load if game mode preference has not been set yet,
    or if in Progress Mode without a player_id.
    """
    global pet_list, poop_list, traited, gcell_fragments, unlocks, battle_area, battle_round, last_adventure_module, xai, xai_date, background_high_res
    global game_background, background_module_name, showClock, inventory, battle_effects, redeemed_codes
    global quests, event, event_time, total_victories, purchases, coins, configuration, setup_input, setup_graphics, show_tutorial, game_mode
    global friends, friend_event_pending, card_collection, card_cooldowns

    if not _can_access_save_dir():
        print("[Save] Skipping load - save directory not accessible")
        return

    # Get all available save files in order (newest first)
    save_files_to_try = []
    
    save_dir = get_save_dir()
    if not os.path.exists(save_dir):
        try:
            os.makedirs(save_dir)
            print(f"[Save] Created save directory: {save_dir}")
        except Exception as e:
            print(f"[Save] Failed to create save directory: {e}")
            return

    # Check if old save_data.dat exists and migrate it first
    old_save_path = os.path.join(save_dir, "save_data.dat")
    if os.path.exists(old_save_path):
        new_save_path = os.path.join(save_dir, "save_data_1.dat")
        try:
            os.rename(old_save_path, new_save_path)
            print(f"[Save] Migrated save_data.dat to save_data_1.dat")
        except Exception as e:
            print(f"[Save] Failed to migrate save_data.dat: {e}")

    # Find all numbered save files
    all_saves = []
    for filename in os.listdir(save_dir):
        if filename.startswith("save_data_") and filename.endswith(".dat"):
            try:
                number_part = filename.replace("save_data_", "").replace(".dat", "")
                full_path = os.path.join(save_dir, filename)
                all_saves.append((int(number_part), full_path))
            except ValueError:
                continue
    
    # Sort by modification time (newest first)
    all_saves.sort(key=lambda x: os.path.getmtime(x[1]), reverse=True)
    save_files_to_try = [save_path for _, save_path in all_saves]

    # Try to load each save file in order
    for save_path in save_files_to_try:
        try:
            with open(save_path, "rb") as f:
                data = pickle.load(f)

                # Load pet list with error handling
                loaded_pet_list = data.get("pet_list", [])
                valid_pets = []
                
                for pet in loaded_pet_list:
                    if pet is None:
                        continue
                        
                    try:
                        # Test basic pet attributes safely
                        if (hasattr(pet, 'name') and hasattr(pet, 'module') and 
                            hasattr(pet, 'stage') and hasattr(pet, 'state')):
                            
                            # Initialize missing attributes for compatibility
                            if not hasattr(pet, 'trophies'):
                                pet.trophies = 0
                            if not hasattr(pet, 'vital_values'):
                                pet.vital_values = 0
                            # Ensure PvP counters exist for compatibility with older saves
                            if not hasattr(pet, 'pvp_battles'):
                                pet.pvp_battles = 0
                            if not hasattr(pet, 'pvp_wins'):
                                pet.pvp_wins = 0
                            
                            # Apply any patches from the pet class
                            if hasattr(pet, 'patch'):
                                pet.patch()
                                
                            valid_pets.append(pet)
                            print(f"[Game] Successfully loaded pet: {pet.name}")
                        else:
                            print(f"[Game] Pet missing required attributes, skipping")
                            continue
                            
                    except Exception as e:
                        print(f"[Game] Failed to load pet (removing from save): {e}")
                        continue
                
                pet_list = valid_pets
                poop_list = data.get("poop_list", [])
                for poop in poop_list:
                    poop.patch()  # Ensure all poops have necessary attributes

                traited = data.get("traited", [])
                gcell_fragments = data.get("gcell_fragments", [])
                game_background = data.get("game_background", None)
                battle_area = data.get("battle_area", {})
                battle_round = data.get("battle_round", {})
                last_adventure_module = data.get("last_adventure_module", None)
                background_module_name = data.get("background_module_name", None)
                unlocks = data.get("unlocks", {})
                showClock = data.get("showClock", False)
                xai = data.get("xai", random.randint(1, 7))
                xai_date = data.get("xai_date", datetime.date.today())
                inventory = data.get("inventory", {})
                battle_effects = data.get("battle_effects", {})
                redeemed_codes = data.get("redeemed_codes", {})
                background_high_res = data.get("background_high_res", False)
                quests = data.get("quests", [])
                event = data.get("event", None)
                event_time = data.get("event_time", None)
                total_victories = data.get("total_victories", {})
                purchases = GamePurchases.from_dict(data.get("purchases", None))
                coins = data.get("coins", 0)
                friends = data.get("friends", {})
                # Saves from before the rework stored a list of module names;
                # that promise no longer carries enough to act on, so it is
                # dropped and the next area clear queues a fresh one.
                _pending = data.get("friend_event_pending", None)
                friend_event_pending = _pending if isinstance(_pending, dict) else None
                card_collection = data.get("card_collection", {})
                card_cooldowns = data.get("card_cooldowns", {})
                setup_input = data.get("setup_input", True)
                setup_graphics = data.get("setup_graphics", True)
                show_tutorial = data.get("show_tutorial", True)
                game_mode = data.get("game_mode", GAME_MODE_PROGRESS)

                # A module renamed on disk takes its saved state with it.
                _rename_saved_modules()

                # Verify player_id for Progress Mode saves
                saved_player_id = data.get("player_id", None)
                if game_mode == GAME_MODE_PROGRESS and player_id:
                    if saved_player_id and str(saved_player_id) != str(player_id):
                        print(f"[Game] WARNING: Save file player_id mismatch! "
                              f"File: {saved_player_id}, Current: {player_id}")

                # Load configuration - handle both old dict format and new format
                saved_config = data.get("configuration", None)
                if saved_config:
                    if isinstance(saved_config, dict):
                        configuration.from_dict(saved_config)
                    elif isinstance(saved_config, GameConfiguration):
                        # Old format - copy values from saved object
                        configuration.from_dict(saved_config.to_dict() if hasattr(saved_config, 'to_dict') else {})

                # Remember the render resolution this save was written at so the
                # pets/poops (absolute pixel coords) can be re-placed for the
                # current dimensions once the display is finalized.
                try:
                    from core import runtime_globals as _rg
                    _rg.save_render_resolution = (
                        configuration.screen_width, configuration.screen_height)
                except Exception:
                    pass

                # Sprites were loaded in __setstate__ before configuration was applied.
                # Reload them now that enable_old_sprites and sprite_resolution_preference are correct.
                for pet in pet_list:
                    try:
                        pet.load_sprite()
                    except Exception as e:
                        print(f"[Game] Failed to reload sprite for {getattr(pet, 'name', 'unknown')}: {e}")

                print(f"[Game] Successfully loaded save file: {os.path.basename(save_path)} with {len(pet_list)} valid pets")
                return  # Successfully loaded, exit the function
                
        except Exception as e:
            print(f"[Game] Failed to load save file {os.path.basename(save_path)}: {e}")
            continue  # Try the next save file
    
    # If we get here, all save files failed to load
    print(f"[Game] All save files failed to load. Starting with fresh game state.")
    # Reset to default values
    pet_list = []
    poop_list = []
    traited = []
    gcell_fragments = []
    game_background = None
    battle_area = {}
    battle_round = {}
    last_adventure_module = None
    background_module_name = None
    unlocks = {}
    showClock = False
    xai = random.randint(1, 7)
    xai_date = datetime.date.today()
    inventory = {}
    battle_effects = {}
    redeemed_codes = {}
    background_high_res = False
    total_victories = {}
    purchases = GamePurchases()
    coins = 0
    friends = {}
    friend_event_pending = None
    card_collection = {}
    card_cooldowns = {}
    # Configuration keeps its system-detected defaults

def autosave() -> None:
    """
    Automatically saves the game if the autosave interval has passed.
    Will not save if save directory is not accessible.
    """
    if not _can_access_save_dir():
        return
    
    global _last_save_time
    now = time.time()

    if now - _last_save_time >= AUTOSAVE_INTERVAL_SECONDS:
        save()
        _last_save_time = now
