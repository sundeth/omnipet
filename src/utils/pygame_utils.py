import hashlib
import os
import pygame
import time
import core.constants as constants
from core import game_globals, runtime_globals
from models import game_console
from utils.asset_utils import image_load, resolve_path
from utils.module_utils import get_module

shadow_cache = {}  # {id(surface): shadow_surface} — validated by size on retrieval

def get_surface_hash(surface):
    """Generate a hash using the surface's memory address (instant, unique per object).
    
    Note: This uses object identity rather than content comparison. Since game sprites
    are loaded once and reused, this is much faster than MD5 hashing pixel data.
    """
    return id(surface)

def get_shadow(sprite, shadow_color=(0, 0, 0, 100)):
    """Return a darkened copy of sprite, cached by object identity.

    Guard against Python id() reuse: if the cached shadow's size doesn't match
    the current sprite's size, the old entry belongs to a different (now-freed)
    surface that happened to land at the same address — regenerate it.
    Transient surfaces (font renders, transform results) that share the same size
    as a recycled id are still a theoretical edge case, but size mismatch catches
    the vast majority of real-world stale-cache hits.
    """
    key = id(sprite)
    cached = shadow_cache.get(key)
    if cached is not None and cached.get_size() == sprite.get_size():
        return cached
    shadow = sprite.copy()
    shadow.fill(shadow_color, special_flags=pygame.BLEND_RGBA_MULT)
    shadow_cache[key] = shadow
    return shadow

flip_cache = {}  # {id(surface): flipped_surface} — validated by size on retrieval

def get_flipped_sprite(sprite):
    """Return sprite mirrored horizontally, cached by object identity.

    Sprites drawn facing both directions (pets on the main scene) used to be
    re-flipped every frame; the source frames are long-lived so identity
    caching works. Same id()-reuse guard as get_shadow: a size mismatch means
    the cached entry belonged to a freed surface — regenerate.
    """
    key = id(sprite)
    cached = flip_cache.get(key)
    if cached is not None and cached.get_size() == sprite.get_size():
        return cached
    flipped = pygame.transform.flip(sprite, True, False)
    flip_cache[key] = flipped
    return flipped


def blit_with_shadow(surface, sprite, pos, offset=(2, 2), shadow_color=(0, 0, 0, 100)):
    """Blit a sprite with a drop-shadow using two direct blits.

    Two direct blits to the target surface are cheaper than building a
    composite surface on every call (which also caused the wrong-shadow bug
    because the composite cache was disabled while the shadow cache was not).
    """
    if game_globals.configuration.debug_mode and game_globals.configuration.debug_blit_logging:
        global _blit_shadow_calls, _last_log_time

        _blit_shadow_calls += 1

        current_time = time.time()
        if current_time - _last_log_time >= 1:
            runtime_globals.game_console.log(f"blit_with_shadow calls per second: {_blit_shadow_calls}")
            _blit_shadow_calls = 0
            _last_log_time = current_time

    shadow = get_shadow(sprite, shadow_color)
    surface.blit(shadow, (pos[0] + offset[0], pos[1] + offset[1]))
    surface.blit(sprite, pos)

def get_font(size=24):
    from utils.asset_utils import font_load
    return font_load(constants.FONT_TTF_PATH, size)

def get_font_alt(size=24):
    from utils.asset_utils import font_load
    return font_load(constants.FONT_ALT_TTF_PATH, size)

def sprite_load(path, size=None, scale=1):
    img = image_load(path).convert_alpha()
    if size:
        return pygame.transform.scale(img, size)
    elif scale != 1:
        base_size = img.get_size()
        new_size = (int(base_size[0] * scale), int(base_size[1] * scale))
        return pygame.transform.scale(img, new_size)
    return img

def sprite_load_percent(path, percent=100, keep_proportion=True, base_on="height", alpha=True):
    img = image_load(path)
    if alpha:
        img = img.convert_alpha()
    else:
        img = img.convert()
    orig_w, orig_h = img.get_size()
    ref_size = runtime_globals.SCREEN_WIDTH if base_on == "width" else runtime_globals.SCREEN_HEIGHT
    target = int(ref_size * (percent / 100.0))
    if keep_proportion:
        scale_factor = target / orig_h if base_on == "height" else target / orig_w
        new_w = int(orig_w * scale_factor)
        new_h = int(orig_h * scale_factor)
    else:
        if base_on == "height":
            new_w = orig_w
            new_h = target
        else:
            new_w = target
            new_h = orig_h
    return pygame.transform.scale(img, (new_w, new_h))

def sprite_load_percent_wh(path, percent_w=100, percent_h=100, keep_proportion=True):
    img = image_load(path).convert_alpha()
    orig_w, orig_h = img.get_size()
    target_w = int(runtime_globals.SCREEN_WIDTH * (percent_w / 100.0))
    target_h = int(runtime_globals.SCREEN_HEIGHT * (percent_h / 100.0))
    if keep_proportion:
        scale_factor = min(target_w / orig_w, target_h / orig_h)
        new_w = int(orig_w * scale_factor)
        new_h = int(orig_h * scale_factor)
    else:
        new_w = target_w
        new_h = target_h
    return pygame.transform.scale(img, (new_w, new_h))

class LazySpriteFolder:
    """Dict-like attack-sprite folder that loads sprites on first access.

    Folders like assets/atk hold hundreds of sprites but an encounter only
    ever uses a handful of attack ids, so eagerly loading + scaling whole
    folders made every training/battle start pay seconds of disk work. The
    folder is listed once; each sprite is loaded and scaled the first time
    its id is requested and kept for subsequent lookups.

    Exposes the dict surface callers actually use: .get() and truthiness.
    """

    def __init__(self, folder, target_height):
        self._folder = folder
        self._target_height = int(target_height)
        self._sprites = {}
        self._files = {}
        # resolve_path handles Android's APP_ROOT; identity on desktop and
        # for already-absolute module folders.
        resolved = resolve_path(folder)
        if os.path.isdir(resolved):
            try:
                for filename in os.listdir(resolved):
                    if filename.endswith(".png"):
                        self._files[filename[:-4]] = filename
            except OSError as e:
                runtime_globals.game_console.log(
                    f"[!] Error listing sprites in {folder}: {e}")

    def __bool__(self):
        return bool(self._files)

    def get(self, key, default=None):
        key = str(key)
        sprite = self._sprites.get(key)
        if sprite is not None:
            return sprite
        filename = self._files.get(key)
        if filename is None:
            return default
        try:
            # image_load re-resolves against APP_ROOT, so pass the
            # unresolved path to stay portable.
            sprite = image_load(os.path.join(self._folder, filename)).convert_alpha()
            orig_w, orig_h = sprite.get_size()
            if orig_h > 0 and orig_h != self._target_height:
                target_width = int(orig_w * (self._target_height / orig_h))
                sprite = pygame.transform.scale(sprite, (target_width, self._target_height))
        except Exception as e:
            runtime_globals.game_console.log(
                f"[!] Error loading sprite {filename} from {self._folder}: {e}")
            return default
        self._sprites[key] = sprite
        return sprite


# Lazy folders cached per (folder, target size); the size is part of the key
# so a render-scale change naturally builds fresh entries.
_sprite_folder_cache = {}


def _lazy_sprite_folder(folder, target_height):
    key = (folder, int(target_height))
    inst = _sprite_folder_cache.get(key)
    if inst is None:
        inst = LazySpriteFolder(folder, target_height)
        _sprite_folder_cache[key] = inst
    return inst


def clear_sprite_folder_cache():
    """Drop cached attack-sprite folders (call when the render scale changes)."""
    _sprite_folder_cache.clear()


def load_attack_sprites():
    """Attack sprites from the global assets/atk folder (lazy, cached).

    Half pet height, proportional width.
    """
    return _lazy_sprite_folder(constants.ATK_FOLDER, 24 * runtime_globals.UI_SCALE)


def load_crit_attack_sprites():
    """Critical-attack sprites from assets/atk_crit (lazy, cached).

    Keyed by filename stem (e.g. '30', '30_dot'), displayed at 2x the normal
    attack sprite size. Callers should use _dot-aware lookup just like
    get_attack_sprite does:
      - Dot-format module: try f'{id}_dot' first, then f'{id}'
      - Other formats:     look up str(id) directly
    """
    return _lazy_sprite_folder(constants.ATK_CRIT_FOLDER, 48 * runtime_globals.UI_SCALE)

def _load_module_sprites_from_folder(module, folder_name):
    """
    Shared loader: dict-like attack sprites from `<module_folder>/<folder_name>/`
    (lazy, cached). Keys are exact filename stems (normal and _dot variants);
    dot vs. non-dot selection happens at lookup time based on the pet's
    current sprite type. Falsy when the module or folder doesn't exist.
    """
    mod = get_module(module)
    if not mod:
        game_console.log(f"[!] Module {module} not found for attack sprites ({folder_name}).")
        return {}

    folder = os.path.join(mod.folder_path, folder_name)
    # atk_crit sprites are displayed at 2× the normal attack size
    target_height = runtime_globals.PET_HEIGHT if folder_name == "atk_crit" else runtime_globals.PET_HEIGHT // 2
    return _lazy_sprite_folder(folder, target_height)


def module_attack_sprites(module):
    """Returns attack sprites for the module from its 'atk' folder."""
    return _load_module_sprites_from_folder(module, "atk")


def module_crit_attack_sprites(module):
    """Returns critical-attack sprites for the module from its 'atk_crit' folder.
    Returns an empty dict if the module has no atk_crit folder.
    """
    return _load_module_sprites_from_folder(module, "atk_crit")


def load_misc_sprites():
    global misc_sprites
    sprite_files = [
        "Cheer.png", "Cheer_dot.png", "Cheer_hd.png",
        "Mad1.png", "Mad2.png",
        "Mad1_hd.png", "Mad2_hd.png",
        "Sick1.png", "Sick2.png",
        "Sick1_dot.png", "Sick2_dot.png",
        "Sick1_hd.png", "Sick2_hd.png",
        "Sleep1.png", "Sleep2.png",
        "Sleep1_hd.png", "Sleep2_hd.png",
        "Poop1.png", "Poop2.png",
        "Poop1_dot.png", "Poop2_dot.png",
        "Poop1_hd.png", "Poop2_hd.png",
        "JumboPoop1.png", "JumboPoop2.png",
        "JumboPoop1_dot.png", "JumboPoop2_dot.png",
        "Wash.png", "CallSignInverted.png", "SickInverted.png", "PoopInverted.png",
        "Dots1.png", "Dots2.png",
    ]
    misc_sprites = {}
    for filename in sprite_files:
        path = os.path.join("assets", filename)
        try:
            sprite = sprite_load(path)
            misc_sprites[filename.split('.')[0]] = pygame.transform.scale(
                sprite, (sprite.get_width() * runtime_globals.UI_SCALE, sprite.get_height() * runtime_globals.UI_SCALE)
            )
            
        except Exception as e:
            runtime_globals.game_console.log(f"[!] Error loading {filename} from '{path}': {e}")
    return misc_sprites

# Counter and timer for logging
_blit_shadow_calls = 0
_last_log_time = time.time()

# Counter and timer for logging
_blit_cache_calls = 0
_last_cache_log_time = time.time()

blit_cache = {}

def rle_accelerate(surface):
    """Run-length encode a large alpha surface drawn far more often than it
    changes (a cached overlay, a border). Blitting it then skips transparent
    runs and copies opaque ones instead of blending every pixel; the picture
    is the same (half-transparent pixels may round one level apart). On the
    Pi Zero 2W, whose pygame has no NEON blitters, blending one 240x240
    overlay cost 17 ms a frame. Drawing into the surface later still works:
    SDL decodes it and encodes it again at the next blit."""
    if surface is not None:
        try:
            surface.set_alpha(255, pygame.RLEACCEL)
        except pygame.error:
            pass
    return surface


def blit_with_cache(surface, sprite, pos):
    """
    Blits a sprite and logs the number of calls per second.
    
    Note: The "cache" in the name is legacy - we now just blit directly since
    Pygame's internal blit is already highly optimized. Caching sprites by copying
    them doesn't provide any benefit and just wastes memory.
    """
    if game_globals.configuration.debug_mode and game_globals.configuration.debug_blit_logging:
        global _blit_cache_calls, _last_cache_log_time

        # Increment the counter
        _blit_cache_calls += 1

        # Log the count every second
        current_time = time.time()
        if current_time - _last_cache_log_time >= 1:
            runtime_globals.game_console.log(f"blit_with_cache calls per second: {_blit_cache_calls}")
            _blit_cache_calls = 0
            _last_cache_log_time = current_time

    # Perform the blit - Pygame's internal blit is already optimized
    surface.blit(sprite, pos)