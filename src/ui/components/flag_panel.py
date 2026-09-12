"""
Flag Panel Component - Shows pet attribute and status flags from right to left
"""

import pygame
from ui.components.component import UIComponent
from ui.components.digisoul_icon import (
    load_digisoul_sprite,
    normalize_digisoul,
)
from core import runtime_globals
from utils.pygame_utils import blit_with_cache


def _smooth_shrink(sprite, size):
    """Downscale a flag icon with bilinear filtering.

    The rest of the game scales pixel art with nearest-neighbour on purpose,
    but a flag has to be squeezed to a fraction of its size to fit the row
    (a 22px icon down to ~13px), and at that ratio nearest-neighbour drops
    whole rows and columns of pixels — which is what made the flags unreadable
    rather than merely small. Smoothing is applied HERE ONLY, so nothing else
    in the UI is affected.

    smoothscale needs a 24/32-bit surface; anything else falls back to the
    plain scale rather than failing to draw the flag at all.
    """
    try:
        return pygame.transform.smoothscale(sprite, size)
    except (ValueError, pygame.error):
        return pygame.transform.scale(sprite, size)


class FlagPanel(UIComponent):
    def __init__(self, x, y, width, height):
        super().__init__(x, y, width, height)
        self.focusable = False
        self.flags = []  # List of flag data to display
        self.flag_sprites = {}  # Cache for loaded flag sprites
        
        # Flag spacing - will be scaled
        self.base_flag_spacing = 2
        self.flag_spacing = self.base_flag_spacing
        
    def on_manager_set(self):
        """Called when component is added to a UI manager"""
        if self.manager:
            # Scale the flag spacing based on UI scale
            self.flag_spacing = self.manager.scale_value(self.base_flag_spacing)
            
    def load_flag_sprite(self, flag_name):
        """Load a flag sprite with fallback and scaling"""
        if flag_name in self.flag_sprites:
            return self.flag_sprites[flag_name]
            
        if not self.manager:
            return None
        
        if flag_name.startswith("DigiSoul:"):
            # DigiSoul art lives outside the Status sprite sheet and is 28px
            # square. Fit it to this 20px-tall row before the common flag
            # layout runs, so it does not shrink every other flag with it.
            digisoul = flag_name.split(":", 1)[1]
            sprite = load_digisoul_sprite(
                digisoul, self.manager.scale_value(self.base_rect.height))
        else:
            # Try to load with preferred scale first
            sprite = self.manager.load_sprite_integer_scaling(
                "Status", flag_name, "")

        self.flag_sprites[flag_name] = sprite
        return sprite
        
                
    def set_pet_flags(self, pet, additional_flags=None, digisoul=None):
        """Update the flags based on pet attributes and status"""
        if not pet:
            self.flags = []
            return
            
        flags = []
        
        # Attribute flag (always present)
        attribute = getattr(pet, 'attribute', '')
        if attribute == "":
            flags.append(('Free', 'Attribute: Free'))
        elif attribute == "Da":
            flags.append(('Da', 'Attribute: Dark'))
        elif attribute == "Va":
            flags.append(('Va', 'Attribute: Vaccine'))
        elif attribute == "Vi":
            flags.append(('Vi', 'Attribute: Virus'))
        else:
            # Fallback for unknown attributes
            flags.append(('Free', f'Attribute: {attribute}'))

        digisoul = normalize_digisoul(digisoul)
        if digisoul:
            flags.append((f'DigiSoul:{digisoul}', f'DigiSoul: {digisoul}'))
            
        # Status flags (only show if true)
        if getattr(pet, 'edited', False):
            flags.append(('Edited', 'This pet has been edited'))
            
        if getattr(pet, 'special', False):
            flags.append(('Special', 'This is a special pet'))
            
        if getattr(pet, 'shiny', False):
            flags.append(('Shiny', 'This pet has shiny coloring'))
            
        if getattr(pet, 'shook', False):
            flags.append(('Shook', 'This pet has been shaken'))
            
        if getattr(pet, 'traited', False):
            flags.append(('Traited', 'This pet started with traits'))
            
        # Add any additional flags provided
        if additional_flags:
            for flag in additional_flags:
                if flag == 'GCellFragment':
                    flags.append(('GCellFragment', 'This pet was hatched from a G-Cell fragment'))
            
        self.flags = flags
        self.needs_redraw = True
        
    def _layout_flags(self):
        """Place every flag inside the panel, as a list of (sprite, x, y, tooltip).

        A pet can carry seven flags where only three fit side by side at their
        natural size, and the row used to be drawn straight off the right edge
        of the panel — so the extra flags simply were not visible. The row is
        now made to fit: the gaps close up first, and only if that is still not
        enough is the whole row scaled down, by one factor so the flags stay
        the same size as each other. The result is cached until the flags or
        the panel change.
        """
        cache_key = (tuple(self.flags), self.rect.width, self.rect.height)
        if getattr(self, "_layout_cache_key", None) == cache_key:
            return self._layout_cache

        placed = []
        sprites = [(self.load_flag_sprite(name), tip) for name, tip in self.flags]
        sprites = [(s, tip) for s, tip in sprites if s]
        if sprites:
            natural = sum(s.get_width() for s, _ in sprites)
            gaps = len(sprites) - 1

            # Close the gaps before shrinking anything.
            spacing = self.flag_spacing
            while spacing > 0 and natural + gaps * spacing > self.rect.width:
                spacing -= 1

            # Still too wide: scale the row down to what is left over.
            factor = 1.0
            available = self.rect.width - gaps * spacing
            if natural > available and natural > 0:
                factor = available / natural

            x = max(0, self.rect.width - int(natural * factor) - gaps * spacing)
            for sprite, tooltip in sprites:
                if factor < 1.0:
                    size = (max(1, int(sprite.get_width() * factor)),
                            max(1, int(sprite.get_height() * factor)))
                    sprite = _smooth_shrink(sprite, size)
                y = (self.rect.height - sprite.get_height()) // 2
                placed.append((sprite, x, y, tooltip))
                x += sprite.get_width() + spacing

        self._layout_cache_key = cache_key
        self._layout_cache = placed
        return placed

    def render(self):
        # Use screen dimensions for surface
        surface = pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)

        for sprite, x, y, _ in self._layout_flags():
            blit_with_cache(surface, sprite, (x, y))


        # Draw highlight if focused and has tooltip
        # Skip in touch mode - focus highlights are for keyboard/mouse navigation only
        if self.focused and hasattr(self, 'tooltip_text') and self.tooltip_text and runtime_globals.INPUT_MODE != runtime_globals.TOUCH_MODE:
            colors = self.manager.get_theme_colors()
            highlight_color = colors.get("highlight", colors["fg"])  # Safe fallback
            pygame.draw.rect(surface, highlight_color, surface.get_rect(), 2)
            
        return surface
        
    def get_tooltip_at_position(self, local_x, local_y):
        """Get tooltip text for flag at given position.

        Shares _layout_flags with render so a flag's hitbox is always exactly
        where it was drawn.
        """
        for sprite, x, y, tooltip in self._layout_flags():
            if (x <= local_x < x + sprite.get_width()
                    and y <= local_y < y + sprite.get_height()):
                return tooltip
        return None
