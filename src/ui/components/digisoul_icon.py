"""DigiSoul family icon used by the status screen and flag row."""

import pygame

from core import constants, runtime_globals
from ui.components.component import UIComponent
from utils.asset_utils import image_load
from utils.pygame_utils import blit_with_cache


_sprite_cache = {}


def normalize_digisoul(value):
    """Return the canonical DigiSoul name, or an empty string when unknown."""
    text = str(value or "").strip()
    return next(
        (known for known in constants.DIGISOUL_DNA_TYPES
         if known.casefold() == text.casefold()),
        "",
    )


def load_digisoul_sprite(value, size):
    """Load one global DigiSoul sprite at a square pixel-art size."""
    digisoul = normalize_digisoul(value)
    size = max(1, int(size))
    if not digisoul:
        return None

    key = (digisoul, size)
    cached = _sprite_cache.get(key)
    if cached is not None:
        return cached

    path = f"assets/digisoul/{digisoul.casefold()}.png"
    try:
        sprite = image_load(path).convert_alpha()
        if sprite.get_size() != (size, size):
            sprite = pygame.transform.scale(sprite, (size, size))
    except (FileNotFoundError, pygame.error) as exc:
        runtime_globals.game_console.log(
            f"[DigiSoulIcon] Could not load {path}: {exc}")
        return None

    _sprite_cache[key] = sprite
    return sprite


class DigiSoulIcon(UIComponent):
    """A standalone DigiSoul icon for the open slot below status flags."""

    def __init__(self, x, y, size=22):
        super().__init__(x, y, size, size)
        self.focusable = False
        self.digisoul = ""
        self.set_tooltip("DigiSoul")

    def set_digisoul(self, value):
        digisoul = normalize_digisoul(value)
        if digisoul == self.digisoul:
            return
        self.digisoul = digisoul
        self.tooltip_text = f"DigiSoul: {digisoul}" if digisoul else "DigiSoul"
        self.needs_redraw = True

    def render(self):
        surface = pygame.Surface(
            (self.rect.width, self.rect.height), pygame.SRCALPHA)
        sprite = load_digisoul_sprite(
            self.digisoul, min(self.rect.width, self.rect.height))
        if sprite is not None:
            x = (self.rect.width - sprite.get_width()) // 2
            y = (self.rect.height - sprite.get_height()) // 2
            blit_with_cache(surface, sprite, (x, y))
        return surface
