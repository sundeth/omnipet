"""
Xros / Temporary evolution utilities
====================================

Temporary evolutions ("temporary-evolution" in monster.json) are battle-only
transformations (Mode Change / Xros).  The pet transforms when its
requirements are met, keeps the form for the whole battle (including all
sequential rounds) and reverts when the battle ends.

Requirements checked at selection time:
    strength  — [min, max] range on the pet's strength stat (999999 = no cap)
    unlock    — a module unlock name the player must have obtained
    friend    — pet names that must be registered in the player's digidex
    megahit   — battle-time condition; does NOT gate the pre-battle selection

While transformed the pet uses the target form's sprites and power, plus its
attack / hp when the target defines non-default (non-zero) values.
"""

import os
import pygame

from core import runtime_globals
from utils.asset_utils import image_load, resolve_path
from utils.data_compat import availability as read_availability
from utils.module_utils import get_module
from utils.utils_unlocks import is_unlocked


# =====================================================================
# Requirement checks
# =====================================================================

def _strength_ok(evo, pet) -> bool:
    rng = evo.get("strength")
    if not rng:
        return True
    lo = rng[0] if len(rng) > 0 else -1
    hi = rng[1] if len(rng) > 1 else 999999
    value = getattr(pet, "strength", 0) or 0
    if lo not in (-1, None) and value < lo:
        return False
    if hi not in (-1, None) and hi != 999999 and value > hi:
        return False
    return True


def _unlock_ok(evo, pet) -> bool:
    name = evo.get("unlock")
    if not name:
        return True
    try:
        return is_unlocked(pet.module, None, name)
    except Exception:
        return False


def get_module_friends(module_name):
    """The player's Friend list for a module (pets met by battling
    Friend-flagged enemies).  Stored in the save file."""
    from core import game_globals
    friends = getattr(game_globals, "friends", None) or {}
    return friends.get(module_name, [])


def register_friend(module_name, friend_name) -> bool:
    """Record a Friend as met: digidex entry + the module's Friend list.

    Called only when the player WINS the Friend encounter — losing leaves the
    Friend unregistered so it stays in the pool for another attempt.
    Returns True when this was a new Friend.
    """
    from core import game_globals
    if not hasattr(game_globals, "friends") or game_globals.friends is None:
        game_globals.friends = {}
    module_list = game_globals.friends.setdefault(module_name, [])
    if friend_name in module_list:
        return False

    module_list.append(friend_name)
    runtime_globals.game_console.log(f"[Friend] {friend_name} registered ({module_name})")

    # The Friend also belongs in the digidex, under its own roster version.
    module = get_module(module_name)
    entry = _find_friend_monster(module, friend_name)
    if entry:
        try:
            from models.game_digidex import register_digidex_entry
            register_digidex_entry(friend_name, module_name, entry.get("version", 1))
        except Exception as exc:
            runtime_globals.game_console.log(f"[Friend] digidex add failed: {exc}")
    try:
        runtime_globals.game_message.add_slide(
            f"{friend_name} became a friend!", (255, 255, 0))
    except Exception:
        pass
    return True


def _find_friend_monster(module, name):
    """The monster.json record for a Friend, or None."""
    if not module or not name:
        return None
    for entry in module.get_all_monsters():
        if entry.get("name") == name and read_availability(entry) == "Friend":
            return entry
    return None


def get_pet_friend_names(pet) -> list:
    """Every Friend named across this pet's DigiXros forms, without repeats.

    A pet can only ever unlock the Friends its own forms ask for, which is
    what keeps one pet from opening another's roster.
    """
    names = []
    for evo in (getattr(pet, "temp_evolve", None) or []):
        for name in (evo.get("friend") or []):
            if name not in names:
                names.append(name)
    return names


def pet_has_xros_friends(pet) -> bool:
    """Whether this pet has a DigiXros form that asks for Friends at all."""
    return bool(get_pet_friend_names(pet))


# =====================================================================
# Friend Event Battles
#
# Clearing an adventure area with a pet that has DigiXros forms promises that
# pet an encounter with one of ITS OWN missing Friends, a few minutes later.
# Separate from the hourly XAI events: this one is earned, not rolled.
# =====================================================================

def promise_friend_event(module_name, pets) -> bool:
    """Queue a Friend encounter after an area clear. True when one was set.

    Only pets of the module whose area was cleared count, and only those with
    a DigiXros form that asks for Friends. One of them is picked at random and
    owns the promise; a later clear overrides an earlier one.
    """
    from core import game_globals

    candidates = [p for p in (pets or [])
                  if getattr(p, "module", None) == module_name
                  and pet_has_xros_friends(p)]
    if not candidates:
        return False

    import random as _random
    pet = _random.choice(candidates)
    game_globals.friend_event_pending = {
        "pet": pet.name,
        "module": module_name,
        "minutes": _random.randint(1, 5),
    }
    runtime_globals.game_console.log(
        f"[Friend] {pet.name} ({module_name}) owes a Friend encounter in "
        f"{game_globals.friend_event_pending['minutes']} min")
    return True


def tick_friend_event():
    """Count the promise down one minute; returns a GameEvent when it fires.

    Returns None while the timer is still running, and also when the promise
    can no longer be kept — the pet left the party, died, fell asleep or sick,
    cannot pay the battle cost, or has already met every Friend it needs. In
    those cases the promise is dropped rather than held forever.
    """
    from core import game_globals

    pending = getattr(game_globals, "friend_event_pending", None)
    if not isinstance(pending, dict):
        return None

    pending["minutes"] = pending.get("minutes", 0) - 1
    if pending["minutes"] > 0:
        return None

    game_globals.friend_event_pending = None
    return _build_friend_event(pending.get("module"), pending.get("pet"))


def _build_friend_event(module_name, pet_name):
    """The encounter the promise resolves to, or None if it cannot be kept."""
    from core import game_globals
    from models.game_event import GameEvent, EventType
    import random as _random

    pet = next((p for p in game_globals.pet_list
                if p.name == pet_name and p.module == module_name), None)
    if pet is None:
        runtime_globals.game_console.log(f"[Friend] {pet_name} left the party; promise dropped")
        return None
    if pet.state in ("dead", "nap") or getattr(pet, "sick", 0) > 0:
        runtime_globals.game_console.log(f"[Friend] {pet_name} is in no shape to battle; promise dropped")
        return None
    if not pet.can_battle():
        runtime_globals.game_console.log(
            f"[Friend] {pet_name} cannot battle ({pet.battle_block_reason()}); promise dropped")
        return None

    wanted = [n for n in get_pet_friend_names(pet)
              if n not in get_module_friends(module_name)]
    if not wanted:
        runtime_globals.game_console.log(f"[Friend] {pet_name} has met every Friend it needs")
        return None

    module = get_module(module_name)
    # Only a Friend with an encounter to fight can be offered.
    playable = [(n, enc) for n, enc in
                ((n, find_friend_encounter(module, n)) for n in wanted) if enc]
    if not playable:
        runtime_globals.game_console.log(
            f"[Friend] none of {pet_name}'s missing Friends has an encounter")
        return None

    name, enc = _random.choice(playable)
    runtime_globals.game_console.log(
        f"[Friend] {pet_name} meets {name} at area {enc['area']} round {enc['round']}")
    return GameEvent(
        event_id=f"friend:{module_name}:{name}", name=name,
        module=module_name, global_event=False,
        event_type=EventType.ENEMY_BATTLE, chance_percent=100,
        area=enc["area"], round_num=enc["round"],
    )


def find_friend_encounter(module, name):
    """The special encounter that awards ``name``, as {name, area, round}."""
    if not module or not name:
        return None
    for enc in module.get_friend_encounters():
        if enc.get("name") == name:
            return enc
    return None


def _friends_ok(evo, pet) -> bool:
    friends = evo.get("friend") or []
    if not friends:
        return True
    module_friends = get_module_friends(pet.module)
    return all(fname in module_friends for fname in friends)


def get_available_temp_evolutions(pet):
    """Return the pet's temporary evolutions whose requirements are met now."""
    result = []
    for evo in (getattr(pet, "temp_evolve", None) or []):
        if not evo.get("to"):
            continue
        if _strength_ok(evo, pet) and _unlock_ok(evo, pet) and _friends_ok(evo, pet):
            result.append(evo)
    return result


# =====================================================================
# The battle-only evolved form
# =====================================================================

class XrosPet:
    """A battle-only stand-in for a pet in a temporary evolution.

    The party pet is NEVER modified. This object carries only the stats the
    evolved form changes and forwards everything else — care values, state,
    position, and every method that records a battle result — straight to the
    real pet. So the outcome of the fight lands on the pet as usual, while the
    form itself lives and dies with this object.

    That is the whole point: the previous version swapped the fields on the
    pet itself and kept a backup to undo later. Pets are pickled whole, so
    closing the game mid-battle saved the evolved stats — and the pet was
    stuck in that form for good. Nothing here can outlive the battle, because
    nothing here is ever written to the pet.
    """

    #: What the evolved form owns. Everything else belongs to the real pet.
    _OWN = frozenset((
        "pet", "evo", "name", "power", "attack", "hp",
        "atk_main", "atk_alt", "atk_alt_2", "sprite_format",
    ))

    def __init__(self, pet, evo, data):
        set_ = object.__setattr__
        set_(self, "pet", pet)
        set_(self, "evo", dict(evo))
        set_(self, "name", data.get("name") or pet.name)
        set_(self, "sprite_format", getattr(pet, "sprite_format", None))
        # A zero in the target's record means "unchanged", the same rule the
        # in-place version used.
        for field in ("power", "attack", "hp"):
            set_(self, field, data.get(field) or getattr(pet, field, 0))
        if data.get("atk_main"):
            set_(self, "atk_main", data["atk_main"])
            set_(self, "atk_alt", data.get("atk_alt") or data["atk_main"])
            set_(self, "atk_alt_2", data.get("atk_alt_2", 0))
        else:
            for field in ("atk_main", "atk_alt", "atk_alt_2"):
                set_(self, field, getattr(pet, field, 0))
        self.load_sprite()

    # -- delegation ----------------------------------------------------

    def __getattr__(self, item):
        # Only reached for attributes this object does not own.
        try:
            pet = object.__getattribute__(self, "pet")
        except AttributeError:
            raise AttributeError(item) from None
        return getattr(pet, item)

    def __setattr__(self, key, value):
        if key in self._OWN:
            object.__setattr__(self, key, value)
        else:
            # Battle results (win counts, DP, sickness, state...) belong to the
            # pet and are written straight through to it.
            setattr(self.pet, key, value)

    def __repr__(self):
        return f"<XrosPet {self.name} over {self.pet.name}>"

    # -- the few things that must see the EVOLVED stats ----------------

    def get_power(self, bonus=0):
        # GamePet's own rules, run against this object: `self.power` resolves
        # here while stage / traited / strength come from the real pet.
        from models.game_pet import GamePet
        return GamePet.get_power(self, bonus)

    def get_hp(self):
        from models.game_pet import GamePet
        return GamePet.get_hp(self)

    def get_sprite(self, index):
        return runtime_globals.pet_sprites[self][index]

    def draw(self, surface):
        from models.game_pet import GamePet
        return GamePet.draw(self, surface)

    def load_sprite(self):
        """Load the evolved form's sprites under THIS object's key.

        Deliberately not GamePet.load_sprite: that one also restores a
        Burpmon sprite and stamps sprite_format, and both would land on the
        real pet through the delegation.
        """
        from utils.sprite_utils import (convert_sprites_to_list,
                                        load_pet_sprites_resolved)
        module_obj = get_module(self.pet.module)
        if not module_obj:
            return
        sprites, resolved = load_pet_sprites_resolved(
            self.name,
            module_obj.folder_path,
            getattr(module_obj, "name_format", "$_dmc"),
            size=(runtime_globals.PET_WIDTH, runtime_globals.PET_HEIGHT),
            primary_sprite_format=getattr(module_obj, "primary_sprite_format", "Color"),
            secondary_sprite_format=getattr(module_obj, "secondary_sprite_format", "HD"),
            pixel_perfect=True,
        )
        if resolved:
            object.__setattr__(self, "sprite_format", resolved)
        sprite_list = convert_sprites_to_list(sprites)
        if not sprite_list or all(s is None for s in sprite_list):
            # Fall back to the pet's own sprites rather than drawing nothing.
            sprite_list = runtime_globals.pet_sprites.get(self.pet) or []
        runtime_globals.pet_sprites[self] = list(sprite_list)

    def release(self):
        """Drop this form's sprites; the pet was never touched."""
        runtime_globals.pet_sprites.pop(self, None)


def make_xros_pet(pet, evo):
    """Build the battle-only evolved form for *pet*, or None if unavailable."""
    module = get_module(pet.module)
    data = module.get_monster(evo.get("to"), pet.version) if module else None
    if not data:
        runtime_globals.game_console.log(
            f"[Xros] Target '{evo.get('to')}' not found in {pet.module}")
        return None
    form = XrosPet(pet, evo, data)
    runtime_globals.game_console.log(
        f"[Xros] {pet.name} fights as {form.name} ({evo.get('type')})")
    return form


# =====================================================================
# Asset loading for the xros animation
# =====================================================================

def _scale_to_fit(surface, max_w, max_h):
    w, h = surface.get_size()
    if w <= 0 or h <= 0:
        return surface
    scale = min(max_w / w, max_h / h)
    if scale == 1:
        return surface
    return pygame.transform.scale(surface, (max(1, int(w * scale)), max(1, int(h * scale))))


def load_xros_background(module, bg_name, cell_size):
    """Background image from the module's backgrounds folder, scaled to the cell."""
    if not module or not bg_name:
        return None
    for ext in (".png", ".jpg", ".jpeg", ".bmp"):
        path = os.path.join(module.folder_path, "backgrounds", bg_name + ext)
        try:
            if os.path.exists(resolve_path(path)):
                img = image_load(path).convert()
                return pygame.transform.scale(img, cell_size)
        except Exception as exc:
            runtime_globals.game_console.log(f"[Xros] bg load failed {path}: {exc}")
    return None


def load_xros_animation_frames(module, anim_name, sprite_size, fit_width=None):
    """The 5 animation frames ("name_1".."name_5").

    With ``fit_width`` the frames are scaled to exactly that width, keeping
    their aspect ratio — the X sweep is meant to span the screen, and is
    allowed to fall short of the top and bottom. Otherwise they are fitted
    inside a sprite_size box as before.
    """
    frames = []
    if not module or not anim_name:
        return frames
    for i in range(1, 6):
        path = os.path.join(module.folder_path, "animations", f"{anim_name}_{i}.png")
        try:
            if os.path.exists(resolve_path(path)):
                img = image_load(path).convert_alpha()
                if fit_width:
                    w, h = img.get_size()
                    if w > 0:
                        img = pygame.transform.scale(
                            img, (int(fit_width), max(1, int(h * fit_width / w))))
                    frames.append(img)
                else:
                    frames.append(_scale_to_fit(img, sprite_size, sprite_size))
        except Exception as exc:
            runtime_globals.game_console.log(f"[Xros] anim load failed {path}: {exc}")
    return frames


def load_form_sprite(module, pet_name, frame_id, sprite_size):
    """One frame of a monster's sprite set, scaled to sprite_size (or None)."""
    if not module or not pet_name:
        return None
    try:
        from utils.sprite_utils import load_pet_sprites
        sprites = load_pet_sprites(
            pet_name,
            module.folder_path,
            getattr(module, 'name_format', '$_dmc'),
            size=(sprite_size, sprite_size),
            primary_sprite_format=getattr(module, 'primary_sprite_format', 'Color'),
            secondary_sprite_format=getattr(module, 'secondary_sprite_format', 'HD'),
        )
        if sprites:
            return sprites.get(frame_id) or next(iter(sprites.values()), None)
    except Exception as exc:
        runtime_globals.game_console.log(f"[Xros] sprite load failed {pet_name}: {exc}")
    return None
