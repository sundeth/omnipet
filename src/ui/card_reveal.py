"""
Card pack reveal
================

The animation that opens a card pack: the pack shakes and bursts open, then
each card it gave is turned over in turn, a shiny one in a golden glow with
sparkles, its art in holo foil (`ui.card_holo`) and its own chime. It plays
over whatever scene is showing and holds the input until the player has seen
every card: A, START or a tap turns the next card (or finishes the turn in
progress), B skips to the end.

`card_utils.announce_cards` queues a pack here. A pack won in a battle or
given by an unlock waits for the main game screen, so it never covers a
battle's result; a pack bought in a shop opens at once. The main loop
(`vpet.VirtualPetGame`) updates, draws and feeds input to `REVEAL` while it
is active.
"""

import math
import random

import pygame

from core import runtime_globals
import core.constants as constants
from ui import card_holo
from ui.ui_constants import YELLOW_BRIGHT, YELLOW_BRIGHT_DARK
from utils.pygame_utils import blit_with_cache, get_font

#: Scene a deferred pack waits for (its class name).
MAIN_SCENE = "SceneMainGame"

SHINY_GOLD = (255, 220, 80)
WHITE = (255, 255, 255)

# Durations in seconds; turned into frames at the configured frame rate.
PACK_SECONDS = 0.8      # the pack shakes
BURST_SECONDS = 0.35    # it bursts open in a flash
FLIP_SECONDS = 0.45     # a card turns over


def _frames(seconds):
    return max(1, int(round(seconds * constants.FRAME_RATE)))


class CardReveal:
    """Queue and play card pack reveals over the current scene."""

    def __init__(self):
        self.queue = []       # packs waiting: dicts, see `add`
        self.current = None   # the pack being shown
        self.phase = None     # "pack" | "burst" | "flip" | "shown"
        self.frame = 0
        self.card_index = 0
        self._fonts = {}
        self._sparkles = []

    # ------------------------------------------------------------------
    # Queue
    # ------------------------------------------------------------------

    def add(self, module_name, drawn, pack=None, wait_for=None):
        """Queue a pack's cards, ``[(card, shiny), ...]`` as `open_pack`
        returns them. *wait_for* is a scene class name the reveal waits
        for, or None to play at once."""
        if not drawn:
            return
        from utils import card_utils
        seen = {}
        cards = []
        for card, shiny in drawn:
            card_id = card.get("id")
            seen[card_id] = seen.get(card_id, 0) + 1
            cards.append({"card": card, "shiny": bool(shiny), "id": card_id})
        # A card is new when every copy of it came in this pack.
        for entry in cards:
            owned = card_utils.total_copies(module_name, entry["id"])
            entry["new"] = owned <= seen[entry["id"]]
        self.queue.append({
            "module": module_name,
            "cards": cards,
            "name": (pack or {}).get("name") or "Card Pack",
            "pack": pack or {},
            "wait_for": wait_for,
        })

    @property
    def active(self) -> bool:
        """Whether a reveal is on screen (it then owns the input)."""
        return self.current is not None

    def pending(self) -> bool:
        return bool(self.queue) or self.current is not None

    def clear(self):
        self.queue = []
        self.current = None
        self.phase = None

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(self, scene_name=None):
        if self.current is None:
            self._start_next(scene_name)
            return
        self.frame += 1
        if self.phase == "pack" and self.frame >= _frames(PACK_SECONDS):
            self._set_phase("burst")
            runtime_globals.game_sound.play("card_pack_open")
        elif self.phase == "burst" and self.frame >= _frames(BURST_SECONDS):
            self._start_flip()
        elif self.phase == "flip":
            if self.frame == _frames(FLIP_SECONDS) // 2:
                runtime_globals.game_sound.play("card_reveal")
            if self.frame >= _frames(FLIP_SECONDS):
                self._finish_flip()

    def _start_next(self, scene_name):
        for i, entry in enumerate(self.queue):
            if entry["wait_for"] and entry["wait_for"] != scene_name:
                continue
            self.current = self.queue.pop(i)
            self.card_index = 0
            self._set_phase("pack")
            return

    def _set_phase(self, phase):
        self.phase = phase
        self.frame = 0

    def _start_flip(self):
        self._set_phase("flip")
        self._sparkles = []

    def _finish_flip(self):
        self._set_phase("shown")
        if self._card()["shiny"]:
            runtime_globals.game_sound.play("card_shiny")
            rng = random.Random(self.card_index * 7919 + len(self.queue))
            self._sparkles = [(rng.uniform(-1.0, 1.0), rng.uniform(-1.0, 1.0),
                               rng.randrange(0, 40)) for _ in range(10)]

    def _card(self):
        return self.current["cards"][self.card_index]

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------

    def handle_event(self, event) -> bool:
        """Consume every input while a reveal is showing."""
        if self.current is None:
            return False
        event_type = event[0] if isinstance(event, tuple) and event else None
        if event_type in ("A", "START", "LCLICK"):
            self._advance()
        elif event_type == "B":
            runtime_globals.game_sound.play("cancel")
            self._close()
        return True

    def _advance(self):
        if self.phase in ("pack", "burst"):
            runtime_globals.game_sound.play("card_pack_open")
            self._start_flip()
        elif self.phase == "flip":
            self._finish_flip()
        elif self.phase == "shown":
            if self.card_index + 1 < len(self.current["cards"]):
                self.card_index += 1
                self._start_flip()
            else:
                runtime_globals.game_sound.play("menu")
                self._close()

    def _close(self):
        self.current = None
        self.phase = None
        self._sparkles = []

    # ------------------------------------------------------------------
    # Draw
    # ------------------------------------------------------------------

    def _font(self, size):
        font = self._fonts.get(size)
        if font is None:
            font = self._fonts[size] = get_font(size)
        return font

    def draw(self, surface):
        if self.current is None:
            return
        width, height = surface.get_size()
        scale = max(1.0, min(width, height) / 240.0)
        cx, cy = width // 2, height // 2

        shade = pygame.Surface((width, height))
        shade.fill((0, 0, 0))
        shade.set_alpha(215)
        surface.blit(shade, (0, 0))

        card_w, card_h = int(110 * scale), int(150 * scale)
        top = cy - card_h // 2 - int(14 * scale)

        if self.phase in ("pack", "burst"):
            self._draw_pack(surface, cx, top, card_w, card_h, scale)
        else:
            self._draw_card(surface, cx, top, card_w, card_h, scale)

        # The pack's name above, the count of cards in the corner.
        title = self._font(int(24 * scale)).render(self.current["name"], True, YELLOW_BRIGHT)
        if title.get_width() > width - int(8 * scale):
            title = self._font(int(16 * scale)).render(self.current["name"], True, YELLOW_BRIGHT)
        surface.blit(title, (cx - title.get_width() // 2, int(6 * scale)))
        if self.phase in ("flip", "shown"):
            count = self._font(int(16 * scale)).render(
                f"{self.card_index + 1}/{len(self.current['cards'])}", True, YELLOW_BRIGHT)
            surface.blit(count, (width - count.get_width() - int(6 * scale), int(26 * scale)))

    def _pack_surface(self, w, h, scale):
        """The pack's own art, or a foil wrapper in the theme colours."""
        sprite_name = self.current["pack"].get("sprite")
        if sprite_name:
            module = runtime_globals.game_modules.get(self.current["module"])
            if module is not None:
                from utils import card_utils
                art = card_utils.load_card_sprite(
                    self.current["module"], {"sprites": {"front": sprite_name}}, "front", w, h)
                if art is not None:
                    return art
        pack = pygame.Surface((w, h), pygame.SRCALPHA)
        stripe = max(2, int(6 * scale))
        for i, y in enumerate(range(0, h, stripe)):
            colour = YELLOW_BRIGHT if i % 2 == 0 else YELLOW_BRIGHT_DARK
            pack.fill(colour, (0, y, w, stripe))
        border = max(1, int(2 * scale))
        pygame.draw.rect(pack, (0, 0, 0), (0, 0, w, h), border)
        # Crimped ends of a foil pack.
        crimp = max(2, int(8 * scale))
        pack.fill((0, 0, 0), (0, crimp, w, border))
        pack.fill((0, 0, 0), (0, h - crimp - border, w, border))
        label = self._font(int(16 * scale)).render("CARDS", True, (0, 0, 0))
        plate = pygame.Rect(0, 0, label.get_width() + int(8 * scale), label.get_height() + int(4 * scale))
        plate.center = (w // 2, h // 2)
        pack.fill(YELLOW_BRIGHT, plate)
        pygame.draw.rect(pack, (0, 0, 0), plate, border)
        pack.blit(label, (plate.centerx - label.get_width() // 2, plate.centery - label.get_height() // 2))
        return pack

    def _draw_pack(self, surface, cx, top, card_w, card_h, scale):
        pack = self._pack_surface(card_w, card_h, scale)
        if self.phase == "pack":
            # The shake grows as the pack is about to open.
            grow = self.frame / _frames(PACK_SECONDS)
            dx = int(math.sin(self.frame * 1.7) * 3 * scale * grow)
            dy = int(math.cos(self.frame * 2.3) * 1 * scale * grow)
            blit_with_cache(surface, pack, (cx - pack.get_width() // 2 + dx, top + dy))
            return
        # Burst: the pack swells and fades in a white flash.
        t = self.frame / _frames(BURST_SECONDS)
        size = (int(pack.get_width() * (1 + 0.25 * t)), int(pack.get_height() * (1 + 0.25 * t)))
        swollen = pygame.transform.scale(pack, size)
        swollen.set_alpha(int(255 * (1 - t)))
        surface.blit(swollen, (cx - size[0] // 2, top + card_h // 2 - size[1] // 2))
        radius = int(card_h * (0.2 + 0.9 * t))
        flash = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
        pygame.draw.circle(flash, (255, 255, 255, int(220 * (1 - t))), (radius, radius), radius)
        surface.blit(flash, (cx - radius, top + card_h // 2 - radius))

    def _card_faces(self, card_w, card_h, scale):
        from utils import card_utils
        module_name = self.current["module"]
        card = self._card()["card"]
        front = card_utils.load_card_sprite(module_name, card, "front", card_w, card_h)
        back = card_utils.load_card_sprite(module_name, card, "back", card_w, card_h)
        if back is None:
            back = self._pack_surface(front.get_width() if front else card_w,
                                      front.get_height() if front else card_h, scale)
        if front is None:
            front = pygame.Surface(back.get_size())
            front.fill((30, 30, 30))
            pygame.draw.rect(front, YELLOW_BRIGHT, front.get_rect(), max(1, int(2 * scale)))
        return front, back

    def _draw_card(self, surface, cx, top, card_w, card_h, scale):
        entry = self._card()
        front, back = self._card_faces(card_w, card_h, scale)
        fw, fh = front.get_size()
        card_top = top + (card_h - fh) // 2
        if self.phase == "flip":
            t = self.frame / _frames(FLIP_SECONDS)
            face = back if t < 0.5 else front
            squeeze = abs(1 - 2 * t)
            w = max(1, int(face.get_width() * squeeze))
            turned = pygame.transform.scale(face, (w, face.get_height()))
            surface.blit(turned, (cx - w // 2, card_top))
            return

        if entry["shiny"]:
            # A pulsing golden glow behind a shiny card.
            pulse = 0.5 + 0.5 * math.sin(self.frame * 0.25)
            pad = int((5 + 3 * pulse) * scale)
            glow = pygame.Surface((fw + pad * 2, fh + pad * 2), pygame.SRCALPHA)
            glow.fill((*SHINY_GOLD, int(90 + 80 * pulse)))
            surface.blit(glow, (cx - fw // 2 - pad, card_top - pad))
        blit_with_cache(surface, front, (cx - fw // 2, card_top))
        if entry["shiny"]:
            # Its art in holo foil, as the collection shows it.
            card_holo.draw_holo(surface, entry["card"],
                                pygame.Rect(cx - fw // 2, card_top, fw, fh), int(scale))
            self._draw_sparkles(surface, cx, card_top + fh // 2, fw, fh, scale)

        # Name and finish under the card.
        name = entry["card"].get("name") or "Card"
        text_y = card_top + fh + int(6 * scale)
        font = self._font(int(24 * scale))
        label = font.render(name, True, YELLOW_BRIGHT)
        if label.get_width() > surface.get_width() - int(8 * scale):
            label = self._font(int(16 * scale)).render(name, True, YELLOW_BRIGHT)
        surface.blit(label, (cx - label.get_width() // 2, text_y))
        tags = []
        if entry["shiny"]:
            tags.append(("SHINY", SHINY_GOLD))
        if entry["new"]:
            tags.append(("NEW", WHITE))
        if tags:
            small = self._font(int(16 * scale))
            rendered = [small.render(text, True, colour) for text, colour in tags]
            gap = int(6 * scale)
            total = sum(r.get_width() for r in rendered) + gap * (len(rendered) - 1)
            x = cx - total // 2
            y = text_y + label.get_height() + int(2 * scale)
            for r in rendered:
                surface.blit(r, (x, y))
                x += r.get_width() + gap

    def _draw_sparkles(self, surface, cx, cy, fw, fh, scale):
        for sx, sy, phase in self._sparkles:
            t = ((self.frame + phase) % 40) / 40.0
            size = int((1 + 3 * math.sin(t * math.pi)) * scale)
            if size <= 0:
                continue
            x = int(cx + sx * (fw // 2 + 6 * scale))
            y = int(cy + sy * (fh // 2 + 6 * scale))
            surface.fill(WHITE, (x - size, y, size * 2 + 1, max(1, int(scale))))
            surface.fill(WHITE, (x, y - size, max(1, int(scale)), size * 2 + 1))
            surface.fill(SHINY_GOLD, (x - max(1, size // 2), y - max(1, size // 2),
                                      max(1, size), max(1, size)))


#: The game's one reveal, driven by the main loop.
REVEAL = CardReveal()
