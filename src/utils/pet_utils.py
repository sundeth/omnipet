from core import game_globals, runtime_globals
from core import constants

def get_selected_pets():
    """
    Returns the list of currently selected pets, or all alive pets if none are selected.

    Note: eggs (stage 0) are excluded via ``stage > 0``.  Stomach is NOT used as
    an eligibility gate here — a pet with stomach 0 can still train/battle and
    use non-food items; only food (hunger/strength) is blocked, handled at the
    point of use (SceneInventory).
    """
    if runtime_globals.selected_pets:
        pet_list = [pet for pet in runtime_globals.selected_pets if pet.state != "dead" and pet.stage > 0]
    else:
        pet_list = [pet for pet in game_globals.pet_list if pet.state != "dead" and pet.stage > 0]
    return pet_list

def get_training_targets():
    """
    Returns pets eligible for training based on the current strategy.
    """
    if runtime_globals.strategy_index == 0:
        return [pet for pet in get_selected_pets() if pet.can_train()]
    else:
        return [pet for pet in get_selected_pets() if pet.can_train() and (pet.effort < 16 or (
            pet.strength < 4 and
            runtime_globals.game_modules.get(pet.module).training_strengh_gain_win > 0))]

def get_battle_targets():
    """
    Returns pets eligible to start a battle.
    """
    return [pet for pet in get_selected_pets() if pet.can_battle()]

def get_battle_continue_targets():
    """Pets that may fight the next round of an area already in progress.

    Looser than get_battle_targets(): a pet that fell sick or hit its bedtime
    partway through a run stays in it, and is only dropped once it runs out
    of the battle cost.
    """
    return [pet for pet in get_selected_pets() if pet.can_continue_battle()]

def get_battle_pvp_targets():
    """
    Returns pets eligible for battle.
    """
    return [pet for pet in get_selected_pets() if pet.can_battle_pvp()]

def can_battle_wificom(pet):
    """Whether *pet* can be put on the wire as a WiFiCom.

    Everything a PvP battle needs, plus what a real device expects to read
    off the packets:

    * the pet's module must declare a ``battle_protocol`` -- that protocol is
      the one used, so a module without one has no wire to speak;
    * the pet needs a ``device_version``, which is the hardware revision the
      protocols key off (not the gameplay ``version``);
    * the pet needs an ``index``, its id in the device's own roster.  Index 0
      is the "outsider" sentinel a compatibility battle sends, so a pet that
      has one cannot present itself as native to the line it is announcing.
    """
    if not pet.can_battle_pvp():
        return False

    from utils.module_utils import get_module
    module = get_module(getattr(pet, 'module', ''))
    if not module or not getattr(module, 'battle_protocol', ''):
        return False

    # **0 is a real device_version on the Colour line**, whose releases are
    # numbered from zero -- a Digital Monster Color Ver.1 announces 0. So the
    # test is whether the pet has one at all, not whether it is truthy; the
    # falsy reading kept every Ver.1 pet off the WiFiCom.
    if getattr(pet, 'device_version', None) is None:
        return False
    if not getattr(pet, 'index', 0):
        return False

    return True

def get_wificom_battle_targets():
    """
    Returns pets eligible for a WiFiCom battle.
    """
    return [pet for pet in get_selected_pets() if can_battle_wificom(pet)]

def pets_need_care():
    """
    Returns True if any pet needs care (callsign is active).
    """
    for pet in game_globals.pet_list:
        if pet.call_sign():
            return True
    return False

def all_pets_hatched():
    """
    Returns True if all pets are hatched (stage > 0).
    """
    return all(pet.stage > 0 for pet in game_globals.pet_list)

def refresh_pet_evolutions(pets=None) -> int:
    """Re-read every pet's evolution routes from its module.

    A pet copies its ``evolve`` and ``temporary-evolution`` lists out of the
    module when it is created, so a pet already in a save keeps whatever those
    lists said at the time — a module that later fixes a broken route cannot
    reach it. Running this at boot lets a player repair such a pet by updating
    the module and restarting.

    Deliberately narrow: ONLY the two evolution lists are replaced. Stats, care
    values and progress are the player's and are never touched from here.

    Returns how many pets were updated.
    """
    from core import runtime_globals
    from utils.module_utils import get_module

    if pets is None:
        pets = list(game_globals.pet_list)
    updated = 0
    for pet in pets:
        try:
            module = get_module(pet.module)
        except Exception:
            continue  # module no longer installed — leave the pet as it is
        if module is None:
            continue
        try:
            data = module.get_monster(pet.name, pet.version)
        except Exception:
            data = None
        if not data:
            runtime_globals.game_console.log(
                f"[Pets] {pet.name} v{pet.version} not found in {pet.module}; evolutions left alone")
            continue

        from utils.jogress_utils import normalize_evolutions
        new_evolve = normalize_evolutions(data.get("evolve") or [])
        new_temp = data.get("temporary-evolution") or []
        if new_evolve != getattr(pet, "evolve", None) or new_temp != getattr(pet, "temp_evolve", None):
            pet.evolve = new_evolve
            pet.temp_evolve = new_temp
            updated += 1
            runtime_globals.game_console.log(
                f"[Pets] Refreshed evolutions for {pet.name} v{pet.version} ({pet.module})")
    return updated


def refresh_pet_sizes():
    """Resize the pets after the party has changed.

    PET_WIDTH/PET_HEIGHT are derived from how many pets are in the party, so
    hatching, losing or freezing one changes the size every pet should be
    drawn at. Recompute the constants, drop the sprite cache so the art is
    reloaded at the new size, and re-space the row.

    Safe to call when nothing actually changed: the reload is skipped unless
    the slot size really moved.
    """
    from core import runtime_globals as rg

    previous = rg.PET_WIDTH, rg.PET_HEIGHT
    # Recompute the DERIVED sizes only — pass the resolution already in force
    # rather than letting it fall back to the saved configuration. Android
    # renders at half the device resolution, decided in main_android before
    # the save is read, so a no-argument call here would replace that with the
    # config's value and shrink the whole game into a corner of the screen.
    rg.update_resolution_constants(rg.SCREEN_WIDTH, rg.SCREEN_HEIGHT)
    if (rg.PET_WIDTH, rg.PET_HEIGHT) == previous:
        return

    rg.pet_sprites = {}
    for pet in game_globals.pet_list:
        try:
            pet.load_sprite()
        except Exception as exc:
            rg.game_console.log(f"[Pets] sprite reload failed for {pet.name}: {exc}")
    distribute_pets_evenly()


def distribute_pets_evenly():
    """
    Evenly distributes pets horizontally around the screen center.

    The layout was designed for a square canvas; spreading over the full
    width of a wide (e.g. phone landscape) render pushes pets out to the
    corners.  Distribute over a centered square-equivalent span instead:
    the full width on square screens (unchanged behavior), the central
    SCREEN_HEIGHT-wide region on wide ones — widened as needed so many
    pets still get at least 1.5x their sprite width per section.
    """
    pet_list = [pet for pet in game_globals.pet_list if pet.state != "dead"]
    count = len(pet_list)
    if count == 0:
        return
    if count == 1:
        pet_list[0].x = (runtime_globals.SCREEN_WIDTH - runtime_globals.PET_WIDTH) // 2
        pet_list[0].subpixel_x = float(pet_list[0].x)
        return
    span = min(runtime_globals.SCREEN_WIDTH,
               max(runtime_globals.SCREEN_HEIGHT,
                   count * runtime_globals.PET_WIDTH * 1.5))
    left = (runtime_globals.SCREEN_WIDTH - span) / 2
    section_width = span / count
    center_positions = [(left + section_width * i + section_width / 2) for i in range(count)]
    for i, pet in enumerate(pet_list):
        pet.x = int(center_positions[i] - runtime_globals.PET_WIDTH / 2)
        pet.subpixel_x = float(pet.x)

def reposition_for_resolution(old_w=None, old_h=None):
    """Refresh pet and poop on-screen positions after a render/window
    resolution change.

    Pet coordinates — the vertical resting position especially — are derived
    from ``SCREEN_HEIGHT`` / ``UI_SCALE`` when the pet spawns (see
    ``GamePet.begin_position``), and poops store absolute pixel positions.
    Both go stale when the resolution changes, so we recompute the pets from
    the new scale (then re-spread them) and re-seat the poops on the pets'
    ground plane, scaling their horizontal position from the old width.

    Args:
        old_w, old_h: the SCREEN_WIDTH/HEIGHT *before* the change, used to
            scale poops' horizontal position.  Omit to leave X as-is.
    """
    for pet in (getattr(game_globals, 'pet_list', None) or []):
        if hasattr(pet, 'begin_position'):
            pet.begin_position()
        if hasattr(pet, 'dirty'):
            pet.dirty = True
    # begin_position centres every pet; spread them back out evenly.
    distribute_pets_evenly()

    align_poops_to_ground(old_w)


def _ground_baseline_y():
    """Y of the line the pets stand on (bottom of the pet sprites), matching
    GamePet.begin_position — pet.y + PET_HEIGHT."""
    scale = runtime_globals.UI_SCALE
    if constants.MAX_PETS > 2:
        return int(174 * scale)
    return int(190 * scale - 5)


def _poop_sprite_size(poop):
    """(width, height) of a poop's current sprite, scaled to the active res."""
    key = "JumboPoop1" if getattr(poop, 'jumbo', False) else "Poop1"
    sprites = getattr(runtime_globals, 'misc_sprites', None) or {}
    sprite = sprites.get(key)
    if sprite:
        return sprite.get_width(), sprite.get_height()
    est = int(24 * runtime_globals.UI_SCALE)
    return est, est


def align_poops_to_ground(old_w=None):
    """Seat every poop on the pets' ground plane for the current resolution.

    A poop's bottom edge is placed on the same line as the pets' feet so they
    share a plane (``pet.y + pet_height == poop.y + poop_height``).  The
    horizontal position is scaled from ``old_w`` (when given) and clamped to
    the visible area; the vertical position is recomputed, not scaled, so it
    is always correct regardless of the resolution the poop was created at.
    """
    poops = getattr(game_globals, 'poop_list', None) or []
    if not poops:
        return
    sw = runtime_globals.SCREEN_WIDTH
    ground = _ground_baseline_y()
    ratio = (sw / old_w) if (old_w and old_w != sw) else 1.0
    for poop in poops:
        pw, ph = _poop_sprite_size(poop)
        # Bottom of the poop aligns with the bottom of the pets.
        poop.y = int(ground - ph)
        if ratio != 1.0:
            poop.x = int(poop.x * ratio)
        poop.x = max(0, min(int(poop.x), max(0, sw - pw)))
        if hasattr(poop, 'dirty'):
            poop.dirty = True


def fix_positions_for_current_resolution():
    """Re-place pets and poops so they're consistent with the current render
    resolution after loading a save.

    Pets are recomputed from scratch (their resting Y depends on the current
    scale); poops store absolute pixels, so they're scaled from the resolution
    the save was written at (``runtime_globals.save_render_resolution``) to the
    current one.  Works on every platform — call it once the display is
    finalized (e.g. from the boot scene before entering the game).
    """
    old = getattr(runtime_globals, 'save_render_resolution', None)
    if not old:
        old = (runtime_globals.SCREEN_WIDTH, runtime_globals.SCREEN_HEIGHT)
    reposition_for_resolution(old[0], old[1])


def draw_pet_outline(surface, frame, x, y, color=(255, 255, 0)):
    """
    Draws an outline around a pet sprite frame.
    """
    import pygame
    mask = pygame.mask.from_surface(frame)
    outline = mask.outline()
    if outline:
        outline = [(x + px, y + py) for px, py in outline]
        pygame.draw.lines(surface, color, True, outline, 2)