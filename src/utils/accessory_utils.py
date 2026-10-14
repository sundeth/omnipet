"""
Accessories a pet wears, and the C'mon Switch's close-up.

An `accessory` item (utils.item_effects) is worn until it is used on the pet
again: `GamePet.accessory` holds its id. The Digivice iC's Afro, Dragon Head,
Helmet, Poop Cap and Sunglasses "walk around on the Digimon", its Aura "wraps"
it (Ultimates only, the item's `min_stage`). The device redraws its Digimon
wearing them; here the item's own art is drawn on the pet's sprite, placed by
the sprite's ink:

    head   a hat: centred over the top of the sprite, sitting a third into it;
    face   glasses: across the upper part of the head;
    aura   a glow around the sprite's outline, drawn behind it and pulsing.

The C'mon Switch brings the Digimon up to the screen: its sprite grows in
three steps until its face fills the screen, as the 20X booklet shows (p.14).
Any input ends it, or `CLOSEUP_SECONDS`.
"""

import os
import time

import pygame

from core import runtime_globals
from utils.asset_utils import image_load

#: How long the close-up lasts when nothing ends it.
CLOSEUP_SECONDS = 6.0
#: The close-up's zoom steps: (from this many seconds, zoom).
CLOSEUP_STEPS = ((0.0, 1.5), (1.2, 2.5), (2.4, 4.0))

_icons = {}       # item id -> the item's art (unscaled), or None
_scaled = {}      # (item id, width, flipped) -> surface
_ink = {}         # frame -> (bounding rect, head centre x)


def _item(item_id):
    from utils.inventory_utils import get_item_by_id
    return get_item_by_id(item_id) if item_id else None


def _icon(item):
    if item.id not in _icons:
        from utils.module_utils import get_module
        module = get_module(item.module)
        surface = None
        if module is not None:
            name = item.sprite_name if item.sprite_name.lower().endswith(".png") else item.sprite_name + ".png"
            path = os.path.join(module.folder_path, "items", name)
            if os.path.exists(path):
                surface = image_load(path).convert_alpha()
                # Trimmed to its ink, so its size and place are the drawing's.
                surface = surface.subsurface(surface.get_bounding_rect()).copy()
        _icons[item.id] = surface
    return _icons[item.id]


def _sized(item, width, flipped):
    key = (item.id, width, flipped)
    if key not in _scaled:
        icon = _icon(item)
        if icon is None:
            _scaled[key] = None
        else:
            height = max(1, round(icon.get_height() * width / icon.get_width()))
            surface = pygame.transform.scale(icon, (width, height))
            _scaled[key] = pygame.transform.flip(surface, True, False) if flipped else surface
    return _scaled[key]


def _ink_of(frame):
    """The frame's ink: its bounding rect and the middle of its top quarter
    (the head, for a pet leaning one way), cached per frame."""
    if frame not in _ink:
        if len(_ink) > 512:
            _ink.clear()
        mask = pygame.mask.from_surface(frame)
        rect = mask.get_bounding_rects()
        box = rect[0].unionall(rect[1:]) if rect else frame.get_rect()
        top = pygame.Rect(box.x, box.y, box.w, max(1, box.h // 4))
        xs = [x for x in range(top.left, top.right) for y in range(top.top, top.bottom) if mask.get_at((x, y))]
        _ink[frame] = (box, (sum(xs) / len(xs)) if xs else box.centerx)
    return _ink[frame]


def worn(pet):
    """The accessory item *pet* wears and can wear now, or None."""
    item = _item(getattr(pet, "accessory", None))
    if item is None or getattr(pet, "state", "") == "dead":
        return None
    if int(pet.stage or 0) < int(getattr(item, "min_stage", 0) or 0):
        return None
    return item


def draw_behind(surface, pet, frame, pos):
    """An aura, under the pet's sprite."""
    item = worn(pet)
    if item is None or item.status != "aura":
        return
    phase = (time.monotonic() * 2.0) % 2.0
    alpha = int(110 + 90 * (phase if phase < 1 else 2 - phase))
    glow = pygame.mask.from_surface(frame).to_surface(setcolor=(255, 200, 60, alpha), unsetcolor=(0, 0, 0, 0))
    step = max(1, int(2 * runtime_globals.UI_SCALE))
    for dx, dy in ((-step, 0), (step, 0), (0, -step), (0, step),
                   (-step, -step), (step, -step), (-step, step), (step, step)):
        surface.blit(glow, (pos[0] + dx, pos[1] + dy))


def draw_over(surface, pet, frame, pos):
    """A hat or glasses, over the pet's sprite."""
    item = worn(pet)
    if item is None or item.status not in ("head", "face"):
        return
    box, head_x = _ink_of(frame)
    if item.status == "head":
        width = int(min(max(box.w * 0.62, runtime_globals.PET_WIDTH * 0.45), runtime_globals.PET_WIDTH * 0.8))
    else:
        width = int(min(max(box.w * 0.62, runtime_globals.PET_WIDTH * 0.45), runtime_globals.PET_WIDTH * 0.7))
    art = _sized(item, width, getattr(pet, "direction", 0) == 1)
    if art is None:
        return
    x = pos[0] + int(head_x - art.get_width() / 2)
    if item.status == "head":
        y = pos[1] + box.top - int(art.get_height() * 0.66)
    else:
        y = pos[1] + box.top + int(box.h * 0.22) - art.get_height() // 2
    surface.blit(art, (x, max(0, y)))


# C'mon Switch -----------------------------------------------------------------

def start_closeup(pet):
    runtime_globals.pet_closeup = {"pet": pet, "start": time.monotonic()}


def closeup_active():
    closeup = getattr(runtime_globals, "pet_closeup", None)
    if not closeup:
        return False
    if time.monotonic() - closeup["start"] > CLOSEUP_SECONDS:
        runtime_globals.pet_closeup = None
        return False
    return True


def end_closeup():
    runtime_globals.pet_closeup = None


def draw_closeup(surface):
    """The close-up over the whole screen, while it lasts."""
    if not closeup_active():
        return
    closeup = runtime_globals.pet_closeup
    pet = closeup["pet"]
    sprites = runtime_globals.pet_sprites.get(pet)
    if not sprites or sprites[0] is None:
        return
    elapsed = time.monotonic() - closeup["start"]
    zoom = [z for t, z in CLOSEUP_STEPS if elapsed >= t][-1]
    frame = sprites[0]
    box, head_x = _ink_of(frame)
    big = pygame.transform.scale(frame, (int(frame.get_width() * zoom), int(frame.get_height() * zoom)))
    sw, sh = surface.get_size()
    shade = pygame.Surface((sw, sh), pygame.SRCALPHA)
    shade.fill((0, 0, 0, 170))
    surface.blit(shade, (0, 0))
    # The sprite's head is followed to the screen's middle as it grows.
    focus_y = box.top + box.h * (0.5 - 0.35 * (zoom - 1.5) / 2.5)
    x = sw // 2 - int(head_x * zoom)
    y = sh // 2 - int(focus_y * zoom)
    surface.blit(big, (x, y))
