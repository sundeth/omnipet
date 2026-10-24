import pygame
from core import runtime_globals
import core.constants as constants
from utils.pygame_utils import blit_with_cache, sprite_load

class XaiRoll:
    """XAI rolling minigame for DMX ruleset"""
    FRAME_COUNT = 7

    #: How long the roll spins unattended before stopping itself. A player who
    #: never presses anything would otherwise sit in front of a roll that spins
    #: forever, with no way to reach the bar phase.
    AUTO_STOP_MS = 5000

    def __init__(self, x, y, width, height, xai_number):
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.xai_number = max(1, min(self.FRAME_COUNT, xai_number))
        # Load the sprite sheet at its original size (no scaling)
        self.sprite_sheet = sprite_load(constants.XAI_ICON_PATH)
        self.current_frame = self.xai_number - 1
        self.rolling = False
        self.roll_timer = 0
        self.roll_speed = int(5 * (constants.FRAME_RATE / 30)) # frames per sprite change

        # Animation state for stop effect
        self.stopping = False
        self.auto_stopped = False   # True when the roll timed out on its own
        self._roll_started_ms = 0
        self.stop_target_frame = None
        self.rect_anim_progress = 0
        self.rect_anim_speed = 2 * (30 / constants.FRAME_RATE)  # pixels per frame
        self.rect_anim_max = self.height // 2
        self.rect_anim_phase = 0  # 0: expanding, 1: shrinking

        # Cache scaled sprites
        self.scaled_sprites = []
        sheet_width, sheet_height = self.sprite_sheet.get_size()
        frame_width = sheet_width // self.FRAME_COUNT
        frame_height = sheet_height
        for i in range(self.FRAME_COUNT):
            frame_rect = pygame.Rect(i * frame_width, 0, frame_width, frame_height)
            icon = self.sprite_sheet.subsurface(frame_rect)
            icon = pygame.transform.scale(icon, (self.width, self.height))
            self.scaled_sprites.append(icon)

        # Cache for rectangle effect surfaces by height
        self._rect_cache = {}

    def roll(self):
        self.rolling = True
        self.stopping = False
        self.roll_timer = 0
        self.auto_stopped = False
        self._roll_started_ms = pygame.time.get_ticks()

    def stop(self, xai_number=None):
        # Begin stop animation
        self.stopping = True
        self.rolling = True  # keep rolling during animation
        self.rect_anim_progress = 0
        self.rect_anim_phase = 0
        if xai_number is not None:
            self.stop_target_frame = max(1, min(self.FRAME_COUNT, xai_number)) - 1
        else:
            self.stop_target_frame = self.current_frame

    def update(self):
        # Nobody pressed anything: stop on whichever face is showing, exactly
        # as a press would have. Checked before the frame advances so the roll
        # lands on the face the player was looking at.
        if (self.rolling and not self.stopping and self._roll_started_ms
                and pygame.time.get_ticks() - self._roll_started_ms >= self.AUTO_STOP_MS):
            self.auto_stopped = True
            self.stop()

        if self.rolling:
            # Use integer tick progression to avoid per-frame modulo cost
            self.roll_timer += 1
            if self.roll_timer >= self.roll_speed:
                self.roll_timer = 0
                nxt = self.current_frame + 1
                if nxt >= self.FRAME_COUNT:
                    nxt = 0
                self.current_frame = nxt

        if self.stopping:
            if self.rect_anim_phase == 0:
                # Expand rectangles
                self.rect_anim_progress += self.rect_anim_speed
                if self.rect_anim_progress >= self.rect_anim_max:
                    self.rect_anim_progress = self.rect_anim_max
                    # Switch to stopped frame and start shrinking
                    self.current_frame = self.stop_target_frame
                    self.rolling = False
                    self.rect_anim_phase = 1
            elif self.rect_anim_phase == 1:
                # Shrink rectangles
                self.rect_anim_progress -= self.rect_anim_speed
                if self.rect_anim_progress <= 0:
                    self.rect_anim_progress = 0
                    self.stopping = False  # Animation done

        # Play sound every half second while rolling
        if self.rolling:
            if not hasattr(self, "_last_sound_tick"):
                self._last_sound_tick = pygame.time.get_ticks()
            now = pygame.time.get_ticks()
            if now - self._last_sound_tick >= 500:
                runtime_globals.game_sound.play("cancel")
                self._last_sound_tick = now
        else:
            if hasattr(self, "_last_sound_tick"):
                del self._last_sound_tick

    def draw(self, surface):
        icon = self.scaled_sprites[self.current_frame]
        #surface.blit(icon, (self.x, self.y))
        blit_with_cache(surface, icon, (self.x, self.y))

        if self.stopping and self.rect_anim_progress > 0:
            # Draw expanding/shrinking rectangles from top and bottom
            rect_height = self.rect_anim_progress
            # Build or reuse cached solid surfaces of requested height
            surf = self._rect_cache.get(int(rect_height))
            if surf is None or surf.get_height() != int(rect_height):
                surf = pygame.Surface((self.width, int(rect_height)))
                surf.fill((0, 0, 0))
                self._rect_cache[int(rect_height)] = surf
            # Top band
            blit_with_cache(surface, surf, (self.x, self.y))
            # Bottom band
            blit_with_cache(surface, surf, (self.x, self.y + self.height - int(rect_height)))

    def get_result(self):
        """Get the current XAI number result (1-7)"""
        return self.current_frame + 1

    def handle_event(self, event):
        """Handle input events for the XAI roll minigame"""
        if not isinstance(event, tuple) or len(event) != 2:
            return False
        
        event_type, event_data = event
        
        if event_type in ("A", "LCLICK"):
            if not self.rolling:
                self.roll()
            elif not self.stopping:
                self.stop()
            return True
        return False