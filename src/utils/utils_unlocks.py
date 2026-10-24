from core import game_globals, runtime_globals


def _grant_card_reward(module, unlock_data):
    """Grant an unlock's optional collection card and card pack, once.

    Unlock rewards request a shiny copy. Soul/DigiSoul Plates remain ordinary
    because that physical product family never has shiny variants. A card
    pack (``card_pack``, a cards.json pack id) is opened as a bought one is.
    """
    if not isinstance(unlock_data, dict):
        return
    pack_id = unlock_data.get("card_pack")
    if pack_id:
        from utils.card_utils import announce_cards, open_pack
        announce_cards(open_pack(module, pack_id), module, pack_id, wait_for_main=True)
    card_id = unlock_data.get("card")
    if not card_id:
        return
    from utils.card_utils import add_card_copy, get_module_cards

    collection = get_module_cards(module)
    card = next((entry for entry in (collection or {}).get("cards", [])
                 if entry.get("id") == card_id), None)
    if card is None:
        runtime_globals.game_console.log(
            f"[Unlocks] Card reward '{card_id}' is missing from {module}; skipped")
        return
    shiny = add_card_copy(module, card_id, shiny=True)
    finish = " shiny" if shiny else ""
    runtime_globals.game_message.add_slide(
        f"{card.get('name', 'Card')}{finish} card obtained!",
        (255, 255, 0), 56 * runtime_globals.UI_SCALE,
        runtime_globals.FONT_SIZE_SMALL)

def charge_egg_plates(module, pet):
    """Feed a newly started egg the DNA of its device's DigiSoul Plate.

    An egg unlock (for the egg's version, or every version) whose card
    reward is a Soul Plate charges that plate into the egg, every time an
    egg is started, not only when the unlock is first earned: the devices
    will not hatch an egg without DNA, and the DNA hatches with it, so the
    Baby I always has a route. Returns how many DNA were fed.
    """
    from utils.card_utils import charge_plate_into, get_module_cards
    module_obj = runtime_globals.game_modules.get(module)
    cards = {c.get("id"): c for c in (get_module_cards(module) or {}).get("cards", [])}
    fed = 0
    for unlock in getattr(module_obj, "unlocks", None) or []:
        if unlock.get("type") != "egg" or not unlock.get("card"):
            continue
        required = unlock.get("version")
        if required is not None and required != getattr(pet, "version", None):
            continue
        card = cards.get(unlock["card"])
        if card is not None and card.get("type") == "Soul Plate":
            fed += charge_plate_into(module, card, pet)
    return fed


# Use a single list of unlocks per module, each unlock has a "type" field
def ensure_module_key(module: str):
    if not isinstance(module, str):
        runtime_globals.game_console.log(f"[Unlocks] Invalid module key: {module} (type: {type(module)})")
        return
    if module not in game_globals.unlocks:
        game_globals.unlocks[module] = []

def unlock_item(module: str, unlock_type: str, name: str, label: str = None):
    """
    Unlocks an item (egg, background, evolution, etc) for a specific module,
    but only if it exists in the module's unlockables.
    """
    ensure_module_key(module)
    # Find the item in the module's unlocks
    module_obj = runtime_globals.game_modules.get(module)
    unlocks = getattr(module_obj, "unlocks", []) if module_obj else []
    unlock_data = None
    for unlock in unlocks:
        if unlock.get("type") == unlock_type and unlock.get("name") == name:
            unlock_data = unlock
            break
    if not unlock_data:
        # Do not unlock if not present in module's unlockables
        runtime_globals.game_console.log(f"[Unlocks] Tried to unlock missing item: {module} {unlock_type} {name}")
        return
    # Only add if not already unlocked
    if not any(isinstance(u, dict) and u.get("type") == unlock_type and u.get("name") == name for u in game_globals.unlocks[module]):
        unlock_entry = {"type": unlock_type, "name": name}
        entry_label = label if label else unlock_data.get("label", name)
        if entry_label:
            unlock_entry["label"] = entry_label
        game_globals.unlocks[module].append(unlock_entry)
        runtime_globals.game_message.add_slide(f"{entry_label} unlocked!", (255, 255, 0), 56 * runtime_globals.UI_SCALE, runtime_globals.FONT_SIZE_SMALL)

        # Progress Mode: reward coins the first time this item is unlocked.
        # (No-op in Free Mode / when logged out.)
        try:
            from utils.reward_utils import reward_unlock
            reward_unlock(module, unlock_type, name)
        except Exception as exc:
            runtime_globals.game_console.log(f"[Unlocks] reward failed: {exc}")

        _grant_card_reward(module, unlock_data)

        # --- Group unlock logic ---
        # After unlocking, check for group unlocks in this module
        for group_unlock in unlocks:
            if group_unlock.get("type") == "group" and isinstance(group_unlock.get("list"), list):
                group_list = group_unlock["list"]
                # If the just-unlocked item is in the group list
                if name in group_list:
                    # Check if all items in the group list are unlocked
                    all_unlocked = all(
                        is_unlocked(module, None, key)  # None means any type
                        if not any(u.get("name") == key for u in game_globals.unlocks[module])
                        else True
                        for key in group_list
                    )
                    # If all are unlocked, unlock the group record
                    if all_unlocked and not is_unlocked(module, "group", group_unlock["name"]):
                        group_label = group_unlock.get("label", group_unlock["name"])
                        group_entry = {"type": "group", "name": group_unlock["name"]}
                        if group_label:
                            group_entry["label"] = group_label
                        game_globals.unlocks[module].append(group_entry)
                        runtime_globals.game_message.add_slide(f"{group_label} unlocked!", (255, 255, 0), 56 * runtime_globals.UI_SCALE, runtime_globals.FONT_SIZE_SMALL)
                        _grant_card_reward(module, group_unlock)

def check_encounter_unlocks(module_name: str, defeated=None):
    """Grant the unlocks a won special encounter is worth.

    Two shapes, both typed "encounter":
      * named by a defeated enemy's ``unlock`` field - the Xros Wars Event
        Battles work this way, one opening the Blue Flare Digitama and
        another the Island Zone background;
      * carrying an ``amount``, granted once that many Friends are registered
        ("obtain every friend").
    Modules that declare none are unaffected.
    """
    module_obj = runtime_globals.game_modules.get(module_name)
    if not module_obj:
        return
    unlocks = [u for u in (getattr(module_obj, "unlocks", []) or [])
               if isinstance(u, dict) and u.get("type") == "encounter"]
    if not unlocks:
        return

    wanted = {getattr(e, "unlock", None) for e in (defeated or []) if e is not None}
    wanted.discard(None)
    wanted.discard("")

    from utils.xros_utils import get_module_friends
    friend_count = len(get_module_friends(module_name))

    for unlock in unlocks:
        name = unlock.get("name")
        if not name or is_unlocked(module_name, "encounter", name):
            continue
        amount = unlock.get("amount")
        if name in wanted or (amount is not None and friend_count >= amount):
            unlock_item(module_name, "encounter", name)


def check_digidex_unlocks(module_name: str):
    """Grant any digidex unlock whose entry count has been reached.

    The digidex screen used to be the only place this ran, so the player had to
    open it before an unlock registered. Called after every evolution instead;
    it returns immediately for modules that declare no digidex unlocks, so the
    roster scan only happens where it can actually pay off.
    """
    module_obj = runtime_globals.game_modules.get(module_name)
    if not module_obj:
        return
    unlocks = getattr(module_obj, "unlocks", []) or []
    pending = [u for u in unlocks
               if isinstance(u, dict) and u.get("type") == "digidex"
               and u.get("amount") is not None
               and not is_unlocked(module_name, "digidex", u.get("name"))]
    if not pending:
        return
    from models.game_digidex import get_module_known_count
    known = get_module_known_count(module_obj)
    for unlock in pending:
        if known >= unlock["amount"]:
            unlock_item(module_name, "digidex", unlock["name"])


# --------------------------------------------------------------------------
# Connection unlocks ("versus")
# --------------------------------------------------------------------------

def _versions(value):
    """An opponent requirement as a list of device versions, or None for any."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return [int(v) for v in value]
    return [int(value)]


def versus_record_matches(unlock, own, opponent, battle_format=None, won=None):
    """Whether one connection battle qualifies for a `versus` unlock record.

    *own* and *opponent* are {"device_version": ..., "version": ...} of the two
    sides (a physical toy has no gameplay version). The record's fields:

      device_version            the pet's own device (hardware) version
      opponent_device_version   the other side's, or ANY_OTHER_DEVICE (any
                                device but this one)
      opponent_device_versions  the other side's, any of a list (PENGZ:
                                Pendulum Color 0-7 and the Godzilla, 8)
      version                   without either device field: the pet's
                                gameplay version
      protocol                  the battle format the connection is fought on
                                ("PENC", "DMC" ...); absent: any
      outcome                   "win": won battles only; absent or "any": any
      own_names / opponent_names  the two sides' species, any of each list
                                (PEN20: Jesmon must beat an Alphamon); absent,
                                any. A side without a name never matches one.
    """
    from battle.combat_constants import ANY_OTHER_DEVICE
    dev = own.get("device_version")
    opp = opponent.get("device_version")
    dev_req = unlock.get("device_version")
    opp_req = unlock.get("opponent_device_versions") or unlock.get("opponent_device_version")
    if dev_req is not None or opp_req is not None:
        if dev_req is not None and dev != dev_req:
            return False
        if opp_req is not None:
            wanted = _versions(opp_req)
            if wanted == [ANY_OTHER_DEVICE]:
                if opp is None or opp == dev:
                    return False
            elif opp not in wanted:
                return False
    elif unlock.get("version") is not None and own.get("version") != unlock.get("version"):
        return False
    protocol = unlock.get("protocol")
    if protocol and str(protocol).upper() != str(battle_format or "").upper():
        return False
    if (unlock.get("outcome") or "any") == "win" and not won:
        return False
    for field, side in (("own_names", own), ("opponent_names", opponent)):
        names = unlock.get(field)
        if names and side.get("name") not in names:
            return False
    return True


def _versus_key(unlock):
    """The save key of one versus record's progress: its name and requirements
    (one name can repeat as alternative records, each counted on its own)."""
    return "|".join(str(unlock.get(k)) for k in (
        "name", "device_version", "opponent_device_version", "opponent_device_versions",
        "version", "protocol", "outcome"))


def record_connection_battle(module_name, sides, battle_format=None, protocol_records_only=False):
    """Count one connection battle (Versus or DCom) for *module_name*'s
    `versus` unlocks and grant each record it completes. Returns their names.

    *sides* lists the readings the battle may be taken in, as
    ``(own, opponent, won)``: a local versus between two of the module's own
    pets passes when either pet meets the record, and still counts once.

    A record with ``amount`` above 1 needs that many qualifying battles, kept
    in ``game_globals.versus_progress``; with ``distinct`` it needs that many
    different opponent device versions other than the pet's own instead
    (DMC's File Island: "all 4 other versions"). Without them a single
    qualifying battle grants it, as before. *protocol_records_only* limits it
    to records naming a ``protocol`` (a pet of another module as opponent).
    """
    module_obj = runtime_globals.game_modules.get(module_name)
    unlocks = [u for u in (getattr(module_obj, "unlocks", []) or [])
               if isinstance(u, dict) and u.get("type") == "versus" and u.get("name")
               and (u.get("protocol") or not protocol_records_only)]
    granted = []
    for unlock in unlocks:
        name = unlock["name"]
        if is_unlocked(module_name, "versus", name):
            continue
        match = next(((own, opponent) for own, opponent, won in sides
                      if versus_record_matches(unlock, own, opponent, battle_format, won)), None)
        if match is None:
            continue
        try:
            amount = int(unlock.get("amount") or 1)
        except (TypeError, ValueError):
            amount = 1
        distinct = bool(unlock.get("distinct"))
        if amount <= 1 and not distinct:
            unlock_item(module_name, "versus", name)
            granted.append(name)
            continue
        store = game_globals.versus_progress.setdefault(module_name, {})
        progress = store.setdefault(_versus_key(unlock), {"battles": 0, "opponents": []})
        progress["battles"] = int(progress.get("battles", 0)) + 1
        own, opponent = match
        opp = opponent.get("device_version")
        if opp is not None and opp != own.get("device_version") and opp not in progress.setdefault("opponents", []):
            progress["opponents"].append(opp)
        count = len(progress["opponents"]) if distinct else progress["battles"]
        runtime_globals.game_console.log(f"[Versus] {module_name} {name}: {count}/{amount}")
        if count >= amount:
            unlock_item(module_name, "versus", name)
            granted.append(name)
    return granted


def is_unlocked(module: str, unlock_type: str, name: str) -> bool:
    """
    Checks if an item is unlocked.
    If unlock_type is None, checks for any type with that name.
    """
    ensure_module_key(module)
    if unlock_type is None:
        return any(isinstance(u, dict) and u.get("name") == name for u in game_globals.unlocks[module])
    return any(isinstance(u, dict) and u.get("type") == unlock_type and u.get("name") == name for u in game_globals.unlocks[module])

def get_unlocked_backgrounds(module: str, module_backgrounds: list = None) -> list[dict]:
    """
    Returns list of unlocked background dicts (with name and label) for a module.
    module_backgrounds should be the module's 'backgrounds' list.
    """
    ensure_module_key(module)
    # Get all unlocked background names for this module
    unlocked_names = {u["name"] for u in game_globals.unlocks[module]}
    backgrounds = []
    # Use the module's backgrounds list to get labels and info
    if module_backgrounds:
        for bg in module_backgrounds:
            if bg["name"] in unlocked_names:
                backgrounds.append({"name": bg["name"], "label": bg.get("label", bg["name"])})
    else:
        # Fallback: just return unlocked names with their label if present
        backgrounds = [{"name": u["name"], "label": u.get("label", u["name"])} for u in game_globals.unlocks[module] if isinstance(u, dict) and u.get("type") == "background"]
    return backgrounds
