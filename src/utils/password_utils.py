"""
Password (codes.json) redemption logic for the Specials menu.

A password belongs to a module and grants an item, a pet, an unlock, or a
special encounter. Redemptions are recorded in game_globals.redeemed_codes
("module@CODE" -> unix timestamp) to enforce the per-code cooldown:
0 = no cooldown, N = minutes between redemptions, -1 = one use only.
"""

import time

from core import game_globals, runtime_globals
from utils.module_utils import get_module


def _party_modules():
    """Names of modules the current party's pets belong to."""
    return {pet.module for pet in game_globals.pet_list}


def modules_with_passwords(module_name=None):
    """Modules (objects) that have passwords AND a party pet using them;
    only *module_name* when given (the Specials hub opens one module's)."""
    modules = []
    for name in _party_modules():
        if module_name is not None and name != module_name:
            continue
        module = get_module(name)
        if module and module.has_passwords():
            modules.append(module)
    return modules


def any_party_module_has_passwords() -> bool:
    return bool(modules_with_passwords())


def max_code_length(default: int = 6, module_name=None) -> int:
    """Longest password code among the party's modules (for the entry UI)."""
    longest = 0
    for module in modules_with_passwords(module_name):
        for pw in module.passwords:
            longest = max(longest, len(str(pw.get("code", ""))))
    return longest if longest else default


def find_password(entered: str, entry_pad: str = "", module_name=None):
    """Match an entered code against the party modules' passwords, or only
    *module_name*'s.

    The code entry pads short codes with its default character, so a
    password matches when it is a prefix of *entered* and the remainder is
    entirely *entry_pad* characters.

    Returns (module, password) or (None, None).
    """
    entered = (entered or "").strip().upper()
    for module in modules_with_passwords(module_name):
        for pw in module.passwords:
            code = str(pw.get("code", "")).strip().upper()
            if not code or len(code) > len(entered):
                continue
            rest = entered[len(code):]
            if entered.startswith(code) and (not rest or (entry_pad and set(rest) <= {entry_pad})):
                return module, pw
    return None, None


def can_redeem(module, password) -> bool:
    """Check the cooldown for a matched password (0=none, -1=once, N=minutes)."""
    key = f"{module.name}@{str(password.get('code', '')).strip().upper()}"
    last = game_globals.redeemed_codes.get(key)
    if last is None:
        return True
    cooldown = int(password.get("cooldown", 0))
    if cooldown == 0:
        return True
    if cooldown < 0:
        return False  # one use only
    return (time.time() - last) >= cooldown * 60


def _record_redemption(module, password):
    key = f"{module.name}@{str(password.get('code', '')).strip().upper()}"
    game_globals.redeemed_codes[key] = time.time()


def _slide(text):
    runtime_globals.game_message.add_slide(
        text, (255, 255, 0), 56 * runtime_globals.UI_SCALE,
        runtime_globals.FONT_SIZE_SMALL)


def _all_pets_happy():
    for pet in game_globals.pet_list:
        try:
            pet.set_state("happy")
        except Exception:
            pass


def redeem(module, password) -> bool:
    """Apply a matched, redeemable password.

    Returns True when the reward was granted (redemption recorded, happy
    sound played and — for item/pet/unlock — the player sent to the main
    game scene). Returns False when the reward could not be applied (bad
    data, or an encounter with no battle-ready pet); the caller should play
    the cancel sound and stay on the input view.
    """
    from utils.scene_utils import change_scene

    ptype = password.get("type")

    if ptype == "pet":
        return _redeem_pet(module, password, change_scene)
    if ptype == "item":
        return _redeem_item(module, password, change_scene)
    if ptype == "unlock":
        return _redeem_unlock(module, password, change_scene)
    if ptype == "encounter":
        return _redeem_encounter(module, password, change_scene)

    runtime_globals.game_console.log(f"[Password] Unknown type {ptype!r}")
    return False


def _redeem_pet(module, password, change_scene) -> bool:
    from models.game_pet import GamePet
    from models.game_digidex import register_digidex_entry

    name = password.get("pet")
    version = int(password.get("version", 1))
    data = module.get_monster(name, version)
    if data is None:
        runtime_globals.game_console.log(
            f"[Password] Pet {name!r} v{version} not found in {module.name}")
        return False

    data = dict(data)
    data["module"] = module.name
    # A Copymon is a doll of a Digimon from some other device, so the password
    # says what hardware it counts as rather than inheriting the gameplay
    # version - battle protocols key off device_version.
    if password.get("device_version") is not None:
        data["device_version"] = int(password["device_version"])
    pet = GamePet(data)
    # Password pets are marked as modded so they can't enter PvP battles.
    pet.edited = True
    register_digidex_entry(pet.name, pet.module, pet.version)

    if len(game_globals.pet_list) < game_globals.configuration.max_pets:
        game_globals.pet_list.append(pet)
        destination = "party"
    else:
        deposited = game_globals.freezer_deposit_pets([pet])
        if not deposited:
            runtime_globals.game_console.log("[Password] Freezer deposit failed")
            return False
        destination = "Freezer"

    _record_redemption(module, password)
    runtime_globals.game_sound.play("happy")
    _all_pets_happy()
    _slide(f"{pet.name} added to {destination}!")
    change_scene("game")
    return True


def _redeem_item(module, password, change_scene) -> bool:
    from utils.inventory_utils import add_to_inventory, get_item_by_name

    item_name = password.get("item")
    amount = int(password.get("amount", 1) or 1)
    item = get_item_by_name(module.name, item_name)
    if item is None:
        runtime_globals.game_console.log(
            f"[Password] Item {item_name!r} not found in {module.name}")
        return False

    add_to_inventory(item.id, amount)
    _record_redemption(module, password)
    runtime_globals.game_sound.play("happy")
    _all_pets_happy()
    _slide(f"{item.name} added to Inventory!")
    change_scene("game")
    return True


def _redeem_unlock(module, password, change_scene) -> bool:
    from utils.utils_unlocks import unlock_item, is_unlocked

    unlock_name = password.get("unlock")
    unlock_data = next(
        (u for u in getattr(module, "unlocks", []) if u.get("name") == unlock_name), None)
    if unlock_data is None:
        runtime_globals.game_console.log(
            f"[Password] Unlock {unlock_name!r} not found in {module.name}")
        return False
    if is_unlocked(module.name, unlock_data.get("type"), unlock_name):
        # Already unlocked: nothing to grant, treat as not redeemable.
        return False

    # unlock_item queues its own "X unlocked!" message slide.
    unlock_item(module.name, unlock_data.get("type"), unlock_name)
    _record_redemption(module, password)
    runtime_globals.game_sound.play("happy")
    _all_pets_happy()
    change_scene("game")
    return True


def _redeem_encounter(module, password, change_scene) -> bool:
    if not any(pet.can_battle() for pet in game_globals.pet_list):
        runtime_globals.game_console.log("[Password] No pet can battle the encounter")
        return False

    area = int(password.get("area", 1) or 1)
    _record_redemption(module, password)
    runtime_globals.game_sound.play("happy")
    runtime_globals.special_encounter = [module.name, area, 1]
    change_scene("battle")
    return True
