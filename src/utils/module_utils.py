import os
from core.constants import MODULES_FOLDER
from models.game_module import GameModule
from core import runtime_globals, game_globals
from utils.asset_utils import resolve_path


def get_modules_dir() -> str:
    """Return the writable modules directory.

    On Android the APK-bundled modules folder is read-only, so downloaded
    modules live under android.storage.app_storage_path()/modules.
    Everywhere else, the workspace-relative 'modules/' folder is used.
    The directory is created if missing.
    """
    if runtime_globals.IS_ANDROID:
        try:
            from android.storage import app_storage_path  # type: ignore
            path = os.path.join(app_storage_path(), MODULES_FOLDER)
        except Exception:
            path = resolve_path(MODULES_FOLDER)
    else:
        path = resolve_path(MODULES_FOLDER)
    os.makedirs(path, exist_ok=True)
    return path


def load_modules():
    """
    Loads all modules from the modules directory and registers them in runtime_globals.game_modules.
    Also initializes adventure mode progress if needed.

    Uses get_modules_dir() so Android downloads (which live outside the
    APK in app_storage_path()/modules) are picked up alongside any
    bundled modules.
    """
    module_dir = get_modules_dir()
    # Build into a local dict and swap atomically at the end so a concurrent
    # reader (e.g. egg selection iterating game_modules) never sees a partial
    # or mid-rebuild dict — important because module syncing can call this
    # from a background thread.
    new_modules = {}
    if not os.path.isdir(module_dir):
        runtime_globals.game_console.log(
            f"[load_modules] modules dir missing: {module_dir}")
        runtime_globals.game_modules = new_modules
        return runtime_globals.game_modules
    for folder in os.listdir(module_dir):
        if folder.endswith(INSTALL_WORK_SUFFIXES):
            continue            # an install's work folder, not a module
        folder_path = os.path.join(module_dir, folder)
        module_json_path = os.path.join(folder_path, "module.json")
        if os.path.isdir(folder_path) and os.path.exists(module_json_path):
            # A corrupt or malformed module must never take the whole game
            # down — skip it, log the cause, and surface a player-facing
            # notice so they know which module failed.
            try:
                module = GameModule(folder_path)
                if module.adventure_mode and game_globals.battle_area.get(module.name) is None:
                    game_globals.battle_area[module.name] = 1
                    game_globals.battle_round[module.name] = 1
                new_modules[module.name] = module
            except Exception as e:
                _report_module_load_error(folder, e)
    runtime_globals.game_modules = new_modules
    runtime_globals.game_console.log(f"[SceneEggSelection] Loaded Modules: {len(new_modules)}")
    return runtime_globals.game_modules


def _report_module_load_error(module_label: str, error: Exception):
    """Log a failed module load and queue a SceneMainGame slide message.

    The slide is queued on the global ``game_message`` instance, so it
    displays whenever the player next reaches the main game screen even if
    loading happened earlier during startup.
    """
    runtime_globals.game_console.log(
        f"[load_modules] Error loading module '{module_label}': {error}")
    try:
        runtime_globals.game_message.add_slide(
            f"Error loading module {module_label}", (255, 80, 80), 90)
    except Exception:
        # Never let the error-reporting path itself break module loading.
        pass

def get_module(name):
    """
    Returns the loaded GameModule instance by name.
    """
    return runtime_globals.game_modules[name]


def safe_module_folder(module_name: str, module_id: str = "") -> str:
    """Folder name used on disk for a module — the sanitized display name
    (matching the shop's install routine), falling back to the id."""
    safe_name = "".join(c for c in (module_name or module_id)
                        if c.isalnum() or c in ('-', '_', ' ')).strip()
    return safe_name or module_id


#: Suffixes of the folders an install works in (install_zip_into): never
#: modules of their own, whatever an interrupted install left in them.
INSTALL_WORK_SUFFIXES = (".installing", ".replaced")


def _rename(src: str, dst: str, wait: float = 1.5) -> None:
    """os.rename, tried again for *wait* seconds on Windows while another
    program holds files inside *src*."""
    import time
    deadline = time.monotonic() + wait
    delay = 0.05
    while True:
        try:
            os.rename(src, dst)
            return
        except PermissionError:
            if os.name != "nt" or time.monotonic() >= deadline:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 0.5)


def _move_into_place(src: str, dst: str) -> None:
    """Put the unpacked module folder *src* at *dst*.

    Windows refuses to rename a folder while a virus scanner or the search
    indexer still holds the files just written into it, for up to a minute
    ("[WinError 5] Access denied": 7 of the 15 dev shop modules failed to
    install so on 2026-10-22). After a moment the files are copied instead:
    reading them is allowed meanwhile."""
    import shutil
    try:
        _rename(src, dst)
    except PermissionError:
        if os.name != "nt":
            raise
        try:
            shutil.copytree(src, dst)
        except Exception:
            shutil.rmtree(dst, ignore_errors=True)
            raise


def install_zip_into(target_dir: str, zip_bytes: bytes, log_name: str = "") -> bool:
    """Unpack a module zip into *target_dir*, replacing what is there only once
    the new one is known good.

    The zip goes into a sibling folder first (a single wrapping folder
    inside it is the module's root); only once module.json is there is the
    installed module swapped out. A broken or cut-off download used to
    delete the module the player had before it was found to be bad.
    """
    import io
    import zipfile
    import shutil
    staging = target_dir + ".installing"
    retired = target_dir + ".replaced"
    try:
        shutil.rmtree(staging, ignore_errors=True)
        os.makedirs(staging, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            zf.extractall(staging)
        root = staging
        entries = os.listdir(staging)
        if (len(entries) == 1
                and os.path.isdir(os.path.join(staging, entries[0]))
                and not os.path.exists(os.path.join(staging, 'module.json'))):
            root = os.path.join(staging, entries[0])
        if not os.path.exists(os.path.join(root, 'module.json')):
            raise ValueError("the download has no module.json")
        shutil.rmtree(retired, ignore_errors=True)
        if os.path.isdir(target_dir):
            _rename(target_dir, retired)
        try:
            _move_into_place(root, target_dir)
        except OSError:
            if os.path.isdir(retired) and not os.path.isdir(target_dir):
                _rename(retired, target_dir)          # put the old one back
            raise
        shutil.rmtree(retired, ignore_errors=True)
        return True
    except Exception as e:
        runtime_globals.game_console.log(f"[ModuleSync] install error for {log_name or target_dir}: {e}")
        return False
    finally:
        # (what a scanner still holds stays until the next install of it)
        shutil.rmtree(staging, ignore_errors=True)


def install_module_zip(module_id: str, module_name: str, zip_bytes: bytes) -> bool:
    """Extract a downloaded module zip into ``modules/<name>/`` (keeping the
    installed one if the download is bad). Returns True when a valid
    module.json ends up at the folder root."""
    modules_dir = get_modules_dir()
    target_dir = os.path.join(modules_dir, safe_module_folder(module_name, module_id))
    return install_zip_into(target_dir, zip_bytes, module_name)


def sync_owned_modules(download_missing: bool = True) -> bool:
    """Reconcile owned modules with what's installed locally.

    Always records the local name of every owned + installed module into
    ``purchases.module_names`` (keyed by the module's actual module.json name,
    matched via the install folder) so ownership checks — which egg selection
    and the connect-exit routing rely on — work reliably.

    When ``download_missing`` is True it also downloads + installs any owned
    module that is absent or out of date (slow — best run off the main thread).
    When False it only reconciles names for already-installed modules, which is
    fast and safe to run synchronously before routing.

    Progress Mode and a logged-in device are required.  Returns True if the
    module registry was reloaded (something installed).
    """
    from services.omninet_service import omninet_service
    if not game_globals.is_progress_mode() or not omninet_service.is_logged_in():
        return False
    purchases = getattr(game_globals, 'purchases', None)
    owned_ids = list(getattr(purchases, 'modules', None) or [])
    if purchases is None or not owned_ids:
        return False

    # Map the server module id -> display name from the shop listing.
    try:
        ok, listing = omninet_service.get_shop_modules()
    except Exception as exc:
        runtime_globals.game_console.log(f"[ModuleSync] listing failed: {exc}")
        return False
    if not ok or not isinstance(listing, list):
        return False
    id_to_info = {}
    for entry in listing:
        if isinstance(entry, dict):
            mid = str(entry.get('id') or '')
            nm = entry.get('name')
            if mid and nm:
                id_to_info[mid] = (nm, entry.get('version', '1.0'))

    # Index installed modules by their on-disk folder name so we can match a
    # server module to its installed copy regardless of whether the shop
    # display name matches the module.json name.
    def _installed_by_folder():
        out = {}
        for mod in runtime_globals.game_modules.values():
            folder = os.path.basename(str(getattr(mod, 'folder_path', '')).rstrip('/\\'))
            if folder:
                out[folder] = mod
        return out

    installed_by_folder = _installed_by_folder()

    changed = False
    for mid in owned_ids:
        info = id_to_info.get(str(mid))
        if not info:
            continue
        name, server_version = info
        folder = safe_module_folder(name, mid)
        existing = installed_by_folder.get(folder)
        # Only (re)download when missing or the server has a different version
        # — the same rule the shop uses.
        if existing is not None and str(getattr(existing, 'version', '')) == str(server_version):
            continue
        if not download_missing:
            # Reconcile-names-only pass: don't fetch anything here.
            continue
        try:
            ok_dl, data = omninet_service.download_module_zip(mid)
        except Exception as exc:
            runtime_globals.game_console.log(
                f"[ModuleSync] download failed for {name}: {exc}")
            continue
        if ok_dl and isinstance(data, (bytes, bytearray)):
            if install_module_zip(mid, name, bytes(data)):
                changed = True
                action = "Updated" if existing is not None else "Installed"
                runtime_globals.game_console.log(
                    f"[ModuleSync] {action} owned module: {name} (v{server_version})")

    if changed:
        try:
            load_modules()
            installed_by_folder = _installed_by_folder()
        except Exception as exc:
            runtime_globals.game_console.log(
                f"[ModuleSync] load_modules failed: {exc}")

    # Record the *actual loaded module name* (the game_modules key) for every
    # owned + installed module, so ownership checks (owns_module_name, which
    # egg selection and the connect-exit routing use) match reliably even when
    # the shop name differs from the module.json name.
    names_added = False
    for mid in owned_ids:
        info = id_to_info.get(str(mid))
        if not info:
            continue
        name, _ = info
        mod = installed_by_folder.get(safe_module_folder(name, mid))
        if mod is not None and mod.name not in purchases.module_names:
            purchases.add_module(mid, mod.name)
            names_added = True

    if changed or names_added:
        try:
            game_globals.save()
        except Exception:
            pass
    return changed


def _apply_purchase_entries(purchases, entries) -> dict:
    """Merge server purchase rows into the local GamePurchases object.

    Records ownership ids per category (module names are reconciled separately
    by sync_owned_modules once the listing maps id -> name)."""
    added = {'module': 0, 'cosmetic': 0, 'gameplay': 0, 'item': 0, 'special': 0}
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        ptype = (entry.get('purchase_type') or '').lower()
        item_id = entry.get('item_id') or entry.get('id')
        if not item_id:
            continue
        item_id = str(item_id)
        if ptype == 'module':
            purchases.add_module(item_id)
            added['module'] += 1
        elif ptype == 'cosmetic':
            purchases.add_cosmetic(item_id)
            added['cosmetic'] += 1
        elif ptype == 'gameplay':
            purchases.add_gameplay(item_id)
            added['gameplay'] += 1
        elif ptype == 'item':
            # Items are bought again and again, one row each, and used up in
            # the game: each row counts once. It used to set every used item
            # back to 1 at each login (online finding 7).
            purchase_id = entry.get('id')
            if not getattr(purchases, 'item_purchases_tracked', True):
                # A save from before the rows were counted holds what it has.
                if purchase_id:
                    purchases.item_purchase_ids.add(str(purchase_id))
                continue
            if purchases.apply_item_purchase(item_id, purchase_id):
                added['item'] += 1
        elif ptype == 'special':
            purchases.add_special(item_id)
            added['special'] += 1
    purchases.item_purchases_tracked = True
    return added


#: The effect fields of a shop item, as `GET /shop/download/item/{id}` gives
#: them in `json_data` (Omninet storage/items/items.json).
SHOP_ITEM_EFFECT_FIELDS = ('effect', 'status', 'amount', 'boost_time', 'protocol_value',
                           'attack_sprite', 'digisoul')


def ensure_shop_item_data(item_id) -> bool:
    """Fill a bought shop item's effect from the server when the game lacks it.

    The listing (`GET /shop/items`) carries no effect data, and without it the
    inventory refuses the item ("has no implemented effect"): online finding
    5. Network: call off the main thread. True when the effect is known."""
    from services.omninet_service import omninet_service
    meta = game_globals.shop_items_data.setdefault(item_id, {'id': item_id, 'cross_module': True})
    if shop_item_effect_known(meta):
        return True
    ok, data = omninet_service.download_item(item_id)
    if not ok or not isinstance(data, dict):
        runtime_globals.game_console.log(f"[Shop] item {item_id}: no effect data ({data})")
        return False
    json_data = data.get('json_data') or {}
    meta.setdefault('name', data.get('name') or json_data.get('name', 'Item'))
    meta.setdefault('description', json_data.get('description', ''))
    meta.setdefault('sprite_name', json_data.get('sprite_name', ''))
    for key in SHOP_ITEM_EFFECT_FIELDS:
        if key in json_data:
            meta[key] = json_data[key]
    meta['cross_module'] = True
    return shop_item_effect_known(meta)


def shop_item_icon_path(meta) -> str:
    """Where a bought shop item's icon is kept: the player's save folder,
    `shop_items/<sprite_name>.png` ("" when the item names no sprite). The
    game ships no shop icons (assets/items holds the core foods only)."""
    name = os.path.basename(str((meta or {}).get('sprite_name') or ''))
    if not name:
        return ''
    if not name.lower().endswith('.png'):
        name += '.png'
    return os.path.join(game_globals.get_save_dir(), 'shop_items', name)


def ensure_shop_item_icon(item_id) -> bool:
    """Keep a bought shop item's icon, from `GET /shop/item/{id}/sprite`, so
    the inventory can draw it (it drew an empty square). Network: call off
    the main thread. True when the icon is on disk."""
    from services.omninet_service import omninet_service
    path = shop_item_icon_path(game_globals.shop_items_data.get(item_id))
    if not path:
        return False
    if os.path.isfile(path) and os.path.getsize(path) > 0:
        return True
    data = omninet_service.get_shop_sprite_bytes('item', item_id)
    if not data:
        runtime_globals.game_console.log(f"[Shop] item {item_id}: no icon")
        return False
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            f.write(data)
    except OSError as exc:
        runtime_globals.game_console.log(f"[Shop] item {item_id}: icon not saved ({exc})")
        return False
    return True


def shop_item_effect_known(meta) -> bool:
    """An item's effect is known when it has one: an `effect`, or a `status`
    (an empty effect with a status is a plain status change, item_effects)."""
    return bool(meta and (meta.get('effect') or meta.get('status')))


def sync_account_data(download_missing: bool = False) -> None:
    """Reconcile coins, purchases and owned modules with the server.

    Run after authentication (boot auto-login or manual login).  With
    ``download_missing=False`` it only reconciles fast (coins, purchase ids,
    and the names of already-installed owned modules) — safe to call on the
    main thread before routing.  With True it also downloads owned modules
    missing locally (slow — run off the main thread).
    """
    from services.omninet_service import omninet_service
    if not game_globals.is_progress_mode() or not omninet_service.is_logged_in():
        return

    # Coins — the server is authoritative in Progress Mode.
    try:
        ui = omninet_service.get_user_info()
        if ui and ui.get('coins') is not None:
            game_globals.coins = int(ui['coins'])
        # Contribution points, a balance of their own (Shop > Specials).
        if ui and ui.get('contribution_points') is not None:
            game_globals.contribution_points = int(ui['contribution_points'])
    except Exception:
        pass

    # Purchases — pull the server's ownership list into the local record.
    purchases = getattr(game_globals, 'purchases', None)
    if purchases is not None:
        try:
            ok, data = omninet_service.get_user_purchases()
            if ok and isinstance(data, dict):
                added = _apply_purchase_entries(purchases, data.get('purchases') or [])
                runtime_globals.game_console.log(
                    f"[AccountSync] Synced purchases from server: {added}")
        except Exception as exc:
            runtime_globals.game_console.log(
                f"[AccountSync] purchases pull failed: {exc}")

    # Owned modules: reconcile local names (and download missing if asked).
    try:
        sync_owned_modules(download_missing=download_missing)
    except Exception as exc:
        runtime_globals.game_console.log(
            f"[AccountSync] module sync failed: {exc}")

    # Held shop items whose effect the game does not know yet (bought on
    # another device, or before the effect was fetched): the slow pass only.
    if download_missing and purchases is not None:
        for item_id, quantity in list(purchases.items.items()):
            if quantity > 0 and not shop_item_effect_known(game_globals.shop_items_data.get(item_id)):
                try:
                    ensure_shop_item_data(item_id)
                except Exception as exc:
                    runtime_globals.game_console.log(
                        f"[AccountSync] item {item_id} data failed: {exc}")
            if quantity > 0:
                try:
                    ensure_shop_item_icon(item_id)
                except Exception as exc:
                    runtime_globals.game_console.log(
                        f"[AccountSync] item {item_id} icon failed: {exc}")

    try:
        game_globals.save()
    except Exception:
        pass