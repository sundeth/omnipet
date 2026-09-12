import pygame
from ui.ui_manager import UIManager
import core.constants as constants
from core import runtime_globals


class ShakeDetector:
    """
    Detects shake gestures from mouse/touch input for devices without accelerometer.
    Uses rapid left-right movement patterns to simulate shake gestures.
    """
    
    def __init__(self):
        self.positions = []  # Store recent mouse positions
        self.max_history = 10  # Keep last 10 positions
        self.shake_threshold = 100  # Minimum distance for shake detection (increased to avoid false positives)
        self.direction_changes = 0  # Count direction changes
        self.min_direction_changes = 2  # Minimum changes to detect shake (lowered from 3 to 2)
        self.last_direction = None
        self.shake_cooldown = 0  # Prevent too frequent shake detection
        
    def update(self):
        """Update the shake detector each frame."""
        if self.shake_cooldown > 0:
            self.shake_cooldown -= 1
            
    def add_mouse_position(self, pos):
        """Add a mouse position and check for shake patterns."""
        if self.shake_cooldown > 0:
            return False
            
        self.positions.append(pos)
        
        # Keep only recent positions
        if len(self.positions) > self.max_history:
            self.positions.pop(0)
            
        # Need at least 3 positions to detect direction changes
        if len(self.positions) < 3:
            return False
            
        # Check for rapid left-right movement
        return self._detect_shake_pattern()
        
    def _detect_shake_pattern(self):
        """Analyze recent positions for shake patterns."""
        if len(self.positions) < 3:
            return False
            
        # Calculate horizontal movement direction changes
        direction_changes = 0
        total_distance = 0
        
        for i in range(1, len(self.positions)):
            prev_pos = self.positions[i-1]
            curr_pos = self.positions[i]
            
            # Calculate horizontal movement
            dx = curr_pos[0] - prev_pos[0]
            total_distance += abs(dx)
            
            # Determine direction (only care about significant movement)
            if abs(dx) > 5:  # Minimum movement threshold
                current_direction = 1 if dx > 0 else -1
                
                if self.last_direction is not None and current_direction != self.last_direction:
                    direction_changes += 1
                    
                self.last_direction = current_direction
        
        # Check if we have enough rapid direction changes and sufficient distance
        if direction_changes >= self.min_direction_changes and total_distance > self.shake_threshold:
            self._trigger_shake()
            return True
            
        return False
        
    def _trigger_shake(self):
        """Trigger a shake event and set cooldown."""
        self.positions.clear()
        self.direction_changes = 0
        self.last_direction = None
        self.shake_cooldown = 15  # Prevent rapid re-triggering (about 0.5 seconds at 30fps)
        
    def handle_pygame_event(self, event):
        """Handle pygame events for shake detection."""
        shake_detected = False
        
        # Handle mouse movement
        if event.type == pygame.MOUSEMOTION:
            shake_detected = self.add_mouse_position(event.pos)
            
        # Handle touch events (if available)
        elif hasattr(pygame, 'FINGERMOTION') and event.type == pygame.FINGERMOTION:
            # Convert normalized touch coordinates to screen coordinates
            touch_x = int(event.x * runtime_globals.SCREEN_WIDTH)
            touch_y = int(event.y * runtime_globals.SCREEN_HEIGHT)
            shake_detected = self.add_mouse_position((touch_x, touch_y))
            
        return shake_detected


class CountMatch:
    """
    Count Match minigame - displays ready and count sprites based on pet attribute.
    Handles the visual display and input for the counting phase.
    """

    #: This minigame draws the alert phase itself, showing an attribute
    #: specific ready sprite, instead of leaving it to the animated sprite.
    HAS_READY_PHASE = True
    
    def __init__(self, ui_manager: UIManager, pet=None, animated_sprite=None):
        """Initialize the count match minigame."""
        self.ui_manager = ui_manager
        if self.ui_manager is None:
            raise ValueError("UIManager cannot be None")
            
        self.pet = pet
        self.phase = "ready"  # ready, count
        self.press_counter = 0
        self.rotation_index = 3
        
        # Use the provided AnimatedSprite component instead of loading our own sprites
        self.animated_sprite = animated_sprite
        
        # Shake detection for mouse/touch fallback
        self.shake_detector = ShakeDetector()

        self.set_phase("ready")

    #: Shakes needed to reach each colour, and the colour it reaches.
    #: "The order of appearance for the colors is Blue, then Yellow, then
    #: Red", and the manual's own chart names the counts: Blue at 2, Yellow
    #: at 7, Red at 12. Colours are 1=Red 2=Yellow 3=Blue, which is why the
    #: progression counts DOWN.
    #:
    #: Two rows of that chart record 6 for Yellow and 11 for Red rather than
    #: 7 and 12; the other three say 7 and 12, so the odd ones are read as
    #: the boundary being seen a shake early rather than as a per-attribute
    #: threshold -- the attribute changes which colour pays what, not when
    #: the colours arrive.
    COLOR_THRESHOLDS = ((12, 1), (7, 2), (2, 3))

    #: Shown before the first colour is reached. "If you do not shake at
    #: least two times, you will only get 0 or 1 Super Hits" -- so under two
    #: shakes there is no colour on screen at all, which is what this frame
    #: is for.
    NO_COLOR = 4

    @classmethod
    def color_for_shakes(cls, shakes):
        """The colour *shakes* has reached, or NO_COLOR below the first.

        **One pass, and it does not wrap.** This used to step one colour
        every three shakes and then cycle 3->2->1->3->2->1, so a player who
        kept shaking rolled past the colour they had earned and back round to
        it -- and the counts never lined up with the device's anyway. The
        device runs Blue, then Yellow, then Red and stops on Red.
        """
        for needed, color in cls.COLOR_THRESHOLDS:
            if shakes >= needed:
                return color
        return cls.NO_COLOR

    def get_pet_attribute_ready_frame(self):
        """Ready frame for the pet's target color.

        Ready0 is the generic sprite; Ready1/2/3 are the colored ones that
        match the Count1/2/3 colors the player must land on:
        Free/Vaccine -> Ready1 (red), Data -> Ready2 (yellow),
        Virus -> Ready3 (green).
        """
        if not self.pet:
            return 1

        attr = getattr(self.pet, "attribute", "")

        if attr == "Da":
            return 2  # Data -> Ready2 (yellow)
        elif attr == "Vi":
            return 3  # Virus -> Ready3 (green)
        return 1      # ""/Va (Free/Vaccine) -> Ready1 (red)

    def set_phase(self, phase):
        """Set the current phase (ready or count)."""
        self.phase = phase
        self.animated_sprite.stop()
        if phase == "count":
            # Reset counters when starting count phase
            self.press_counter = 0
            self.rotation_index = 4  # Start at 4 so first shake goes to 3
            # Setup count mode in animated sprite
            if self.animated_sprite:
                self.animated_sprite.setup_countdown_count()
                self.animated_sprite.current_frame = 3  # Start with Count4 (index 3)
        elif phase == "ready":
            # Setup ready mode in animated sprite
            if self.animated_sprite:
                self.animated_sprite.setup_countdown_ready()
                ready_frame = self.get_pet_attribute_ready_frame()
                self.animated_sprite.current_frame = ready_frame

    def handle_event(self, event):
        """Handle input events for the minigame."""
        if not isinstance(event, tuple) or len(event) != 2:
            return False
        
        event_type, event_data = event
        
        if self.phase == "count" and event_type in ("Y", "SHAKE"):
            self.press_counter += 1
            self.rotation_index = self.color_for_shakes(self.press_counter)

            # Update animated sprite frame based on rotation_index
            if self.animated_sprite:
                # Map rotation_index to frame index:
                # rotation_index 4 -> frame 3 (Count4) - before any colour
                # rotation_index 1-3 -> frame 0-2 (Count1-Count3)
                if self.rotation_index == 4:
                    self.animated_sprite.current_frame = 3  # Count4
                else:
                    self.animated_sprite.current_frame = self.rotation_index - 1  # Count1,Count2,Count3
            return True
        return False
        
    def update(self):
        """Update the minigame state each frame."""
        # Fast path: if not counting, only update cooldowns
        self.shake_detector.update()
        if self.phase != "count":
            return

        # Detect shake from mouse/touch motion and generate SHAKE events
        # Minimize work by short-circuiting when mouse position hasn't changed
        last_pos = getattr(self, '_last_mouse_pos', None)
        mouse_pos = pygame.mouse.get_pos()
        if mouse_pos == last_pos:
            return

        # Feed new mouse position to shake detector and synthesize event only on detection
        if self.shake_detector.add_mouse_position(mouse_pos):
            self.handle_event(("SHAKE", None))
        self._last_mouse_pos = mouse_pos

    def get_press_counter(self):
        """Get the current press counter."""
        return self.press_counter

    def get_rotation_index(self):
        """Get the current rotation index."""
        return self.rotation_index

    def draw(self, surface):
        """Draw the count match minigame components using AnimatedSprite."""
        # Only draw if we have a valid phase
        self.animated_sprite.draw(surface)
        
    def draw_ready(self, surface):
        """Draw the ready sprite using AnimatedSprite component."""
        self.animated_sprite.draw(surface)

    def draw_count(self, surface):
        """Draw the count sprite using AnimatedSprite component.""" 
        self.animated_sprite.draw(surface)