import random
import pygame
from ui.ui_manager import UIManager
from ui.components.button import Button
from core import runtime_globals
import core.constants as constants
from utils.pygame_utils import blit_with_shadow
from models.animation import PetFrame
from battle import combat_constants


class HeadCharge:
    """
    Head-to-Head charge minigame - extracted from head training for cleaner separation.
    Handles pattern matching, pet attacks, and strikes counter.
    """
    
    PATTERNS = [
        "ABABB", "BBAAB", "BAABB",
        "ABBAA", "BABAB", "ABABA"
    ]

    def __init__(self, ui_manager: UIManager, left_pet=None, right_pet=None, left_attack_sprite=None, right_attack_sprite=None):
        """Initialize the head charge minigame."""
        self.ui_manager = ui_manager
        if self.ui_manager is None:
            raise ValueError("UIManager cannot be None")
            
        self.left_pet = left_pet
        self.right_pet = right_pet
        self.left_attack_sprite = left_attack_sprite
        self.right_attack_sprite = right_attack_sprite

        from utils.sprite_utils import snap_pet_sprite_size
        # Snapped to the pixel-perfect ladder (36*scale lands between steps).
        self.pet_size = snap_pet_sprite_size(36 * runtime_globals.UI_SCALE)

        self.pattern = ""
        self.current_index = 0
        self.victories = 0
        self.failures = 0
        self.player_input = None
        self.is_collision = False
        self.attack_positions = []
        
        # Calculate proper sprite scale - UI scale is based on 240x240, but sprites are 2x size
        sprite_scale_factor = runtime_globals.UI_SCALE / 2
        
        # Cached sprites using UI manager - use new HeadTraining specific sprites
        self._sprite_cache = {}
        self._sprite_cache['head_training_img'] = self.ui_manager.load_sprite_non_integer_scaling(constants.HEADTRAINING_PATH, runtime_globals.UI_SCALE * 1.5)
        self._sprite_cache['vs_img'] = self.ui_manager.load_sprite_non_integer_scaling(constants.VS_PATH, runtime_globals.UI_SCALE * 1.5)
        self._sprite_cache['strikes'] = self.ui_manager.load_sprite_non_integer_scaling(constants.HEADTRAINING_STRIKE_PATH, sprite_scale_factor)
        self._sprite_cache['strikes_back'] = self.ui_manager.load_sprite_non_integer_scaling(constants.HEADTRAINING_BACK_PATH, sprite_scale_factor)

        # Cache pet sprites first so we can use them as fallbacks
        if self.left_pet and self.right_pet:
            runtime_globals.game_console.log(f"[HeadCharge] Caching pet sprites for {self.left_pet.name} vs {self.right_pet.name}")
            runtime_globals.game_console.log(f"[HeadCharge] pet_sprites keys: {[p.name for p in runtime_globals.pet_sprites.keys()]}")
            
            left_atk1 = runtime_globals.pet_sprites[self.left_pet][PetFrame.ATK1.value]
            left_atk2 = runtime_globals.pet_sprites[self.left_pet][PetFrame.ATK2.value]
            # The left pet faces right: its own right-facing frames if the set
            # has them (6R/7R.png), else these are mirrored below.
            right_pairs = runtime_globals.pet_sprites_right.get(self.left_pet) or {}
            left_atk1_right = right_pairs.get(left_atk1)
            left_atk2_right = right_pairs.get(left_atk2)
            right_atk1 = runtime_globals.pet_sprites[self.right_pet][PetFrame.ATK1.value]
            right_atk2 = runtime_globals.pet_sprites[self.right_pet][PetFrame.ATK2.value]
            
            runtime_globals.game_console.log(f"[HeadCharge] left_atk1 size: {left_atk1.get_size()}, id: {id(left_atk1)}")
            runtime_globals.game_console.log(f"[HeadCharge] left_atk2 size: {left_atk2.get_size()}, id: {id(left_atk2)}")
            runtime_globals.game_console.log(f"[HeadCharge] right_atk1 size: {right_atk1.get_size()}, id: {id(right_atk1)}")
            runtime_globals.game_console.log(f"[HeadCharge] right_atk2 size: {right_atk2.get_size()}, id: {id(right_atk2)}")
            
            # Cache scaled sprites (unflipped)
            left_pet_atk1_scaled = pygame.transform.scale(left_atk1, (self.pet_size, self.pet_size))
            left_pet_atk2_scaled = pygame.transform.scale(left_atk2, (self.pet_size, self.pet_size))
            
            # Cache both unflipped and flipped versions for left pet (left pet is drawn flipped)
            self._sprite_cache['left_pet_atk1'] = left_pet_atk1_scaled
            self._sprite_cache['left_pet_atk2'] = left_pet_atk2_scaled
            self._sprite_cache['left_pet_atk1_flipped'] = (
                pygame.transform.scale(left_atk1_right, (self.pet_size, self.pet_size))
                if left_atk1_right is not None
                else pygame.transform.flip(left_pet_atk1_scaled, True, False))
            self._sprite_cache['left_pet_atk2_flipped'] = (
                pygame.transform.scale(left_atk2_right, (self.pet_size, self.pet_size))
                if left_atk2_right is not None
                else pygame.transform.flip(left_pet_atk2_scaled, True, False))
            
            # Cache scaled sprites for right pet (unflipped)
            self._sprite_cache['right_pet_atk1'] = pygame.transform.scale(right_atk1, (self.pet_size, self.pet_size))
            self._sprite_cache['right_pet_atk2'] = pygame.transform.scale(right_atk2, (self.pet_size, self.pet_size))
            
            runtime_globals.game_console.log(f"[HeadCharge] Cached sprites - left_pet_atk1 id: {id(self._sprite_cache['left_pet_atk1'])}")
            runtime_globals.game_console.log(f"[HeadCharge] Cached sprites - left_pet_atk1_flipped id: {id(self._sprite_cache['left_pet_atk1_flipped'])}")
            runtime_globals.game_console.log(f"[HeadCharge] Cached sprites - right_pet_atk1 id: {id(self._sprite_cache['right_pet_atk1'])}")
            
            # Use provided attack sprites if available, otherwise fall back to pet ATK1 sprites
            if self.left_attack_sprite is None:
                self.left_attack_sprite = left_atk1
            if self.right_attack_sprite is None:
                self.right_attack_sprite = right_atk1
        
        # Scale attack sprites for shooting (half the pet size) and cache both versions
        if self.left_attack_sprite is not None:
            self.left_attack_sprite = pygame.transform.scale(self.left_attack_sprite, (self.pet_size//2, self.pet_size//2))
            self.left_attack_sprite_flipped = pygame.transform.flip(self.left_attack_sprite, True, False)
        else:
            self.left_attack_sprite_flipped = None
            
        if self.right_attack_sprite is not None:
            self.right_attack_sprite = pygame.transform.scale(self.right_attack_sprite, (self.pet_size//2, self.pet_size//2))
        
        # Create UP/DOWN UI buttons using UI manager's base coordinate system (240x240)
        ui_base = 240  # UI manager's base resolution
        button_size = 30  # Base size in UI coordinates
        
        # Centered X position in UI coordinates
        center_x = (ui_base - button_size) // 2

        # UP button at middle top with ArrowUp decorator
        up_y = 40  # UI coordinates
        runtime_globals.game_console.log(f"[HeadCharge] Creating UP button: UI pos=({center_x}, {up_y}), size={button_size}x{button_size}")
        self.up_button = Button(center_x, up_y, button_size, button_size, "", 
                               callback=lambda: self.handle_button_press("UP"),
                               decorators=["ArrowUp"], shadow_mode="full")
        runtime_globals.game_console.log(f"[HeadCharge] UP button created: rect={self.up_button.rect}")
        self.ui_manager.add_component(self.up_button)

        # DOWN button at middle bottom with ArrowDown decorator
        down_y = ui_base - button_size - 40  # UI coordinates
        runtime_globals.game_console.log(f"[HeadCharge] Creating DOWN button: UI pos=({center_x}, {down_y}), size={button_size}x{button_size}")
        self.down_button = Button(center_x, down_y, button_size, button_size, "", 
                                 callback=lambda: self.handle_button_press("DOWN"),
                                 decorators=["ArrowDown"], shadow_mode="full")
        runtime_globals.game_console.log(f"[HeadCharge] DOWN button created: rect={self.down_button.rect}")
        self.ui_manager.add_component(self.down_button)
            
        # Internal state
        self.phase = "charge"  # charge, attack_move, alert, result
        self.frame_counter = 0

        self.select_pattern()

    def select_pattern(self):
        """Select a new pattern for the training sequence"""
        last = runtime_globals.last_headtohead_pattern
        runtime_globals.last_headtohead_pattern = (last + 1) % 6
        self.pattern = self.PATTERNS[runtime_globals.last_headtohead_pattern]
        self.current_index = 0

    def update(self):
        """Update minigame state"""
        if self.phase == "attack_move":
            self.move_attacks()
        elif self.phase == "alert":
            self.frame_counter += 1
            if self.frame_counter > 30:  # Alert duration
                self.phase = "charge"
                self.frame_counter = 0

        mouse_enabled = (runtime_globals.INPUT_MODE == runtime_globals.MOUSE_MODE or runtime_globals.INPUT_MODE == runtime_globals.TOUCH_MODE)
        if self.phase != "result" and mouse_enabled:
            self.up_button.update()
            self.down_button.update()

    def handle_button_press(self, direction):
        """Handle button press from UI buttons"""
        if self.phase == "charge":
            if direction == "UP":
                self.player_input = "B"
                self.start_attack()
            elif direction == "DOWN":
                self.player_input = "A"
                self.start_attack()

    def handle_event(self, event):
        """Handle input events for the head charge minigame"""
        if not isinstance(event, tuple) or len(event) != 2:
            return False
        
        event_type, event_data = event
        
        if event_type == "LCLICK" and (runtime_globals.INPUT_MODE == runtime_globals.MOUSE_MODE or runtime_globals.INPUT_MODE == runtime_globals.TOUCH_MODE):
            if event_data and "pos" in event_data:
                mouse_pos = event_data["pos"]
                if self.up_button.rect.collidepoint(mouse_pos):
                    self.handle_button_press("UP")
                    return True
                elif self.down_button.rect.collidepoint(mouse_pos):
                    self.handle_button_press("DOWN")
                    return True

        if self.phase == "charge":
            if event_type == "UP":
                self.player_input = "B"
                self.start_attack()
                return True
            elif event_type == "DOWN":
                self.player_input = "A"
                self.start_attack()
                return True
        return False

    def start_attack(self):
        """Start the attack animation sequence"""
        self.phase = "attack_move"
        self.attack_positions.clear()

        left_dir = self.pattern[self.current_index]
        right_dir = self.player_input

        # Calculate attack positions
        y_up = self.left_y
        y_down = y_up + int(32 * runtime_globals.UI_SCALE)

        left_x = self.pet_size + (5 * runtime_globals.UI_SCALE)
        right_x = runtime_globals.SCREEN_WIDTH - self.pet_size - (5 * runtime_globals.UI_SCALE)

        # Use cached flipped sprite for left attack
        left_sprite = self.left_attack_sprite_flipped
        right_sprite = self.right_attack_sprite
        self.attack_positions.append([left_sprite, [left_x, y_up if left_dir == "A" else y_down]])
        self.attack_positions.append([right_sprite, [right_x, y_up if right_dir == "A" else y_down]])

        self.is_collision = (left_dir == right_dir)

    def move_attacks(self):
        """Update attack positions and check for completion"""
        finished = False
        if self.is_collision:
            finished = self.update_collision()
        else:
            finished = self.update_cross_attack()
        if finished:
            self.process_attack_result()

    def update_collision(self):
        """Update attacks for a collision (meet in center)"""
        target_x = runtime_globals.SCREEN_WIDTH // 2 - int(12 * runtime_globals.UI_SCALE)
        for atk in self.attack_positions:
            sprite, (x, y) = atk
            if x < target_x:
                x += combat_constants.ATTACK_SPEED * (30 / constants.FRAME_RATE)
            elif x > target_x:
                x -= combat_constants.ATTACK_SPEED * (30 / constants.FRAME_RATE)
            atk[1] = (x, y)
        left_x = self.attack_positions[0][1][0]
        right_x = self.attack_positions[1][1][0]
        return (
            abs(left_x - target_x) <= int(10 * runtime_globals.UI_SCALE)
            and abs(right_x - target_x) <= int(10 * runtime_globals.UI_SCALE)
        )

    def update_cross_attack(self):
        """Update attacks for cross fire (no collision)"""
        self.attack_positions[0][1] = (
            self.attack_positions[0][1][0] + combat_constants.ATTACK_SPEED * (30 / constants.FRAME_RATE),
            self.attack_positions[0][1][1]
        )
        self.attack_positions[1][1] = (
            self.attack_positions[1][1][0] - combat_constants.ATTACK_SPEED * (30 / constants.FRAME_RATE),
            self.attack_positions[1][1][1]
        )
        return (
            self.attack_positions[0][1][0] >= runtime_globals.SCREEN_WIDTH - runtime_globals.PET_WIDTH - (5 * runtime_globals.UI_SCALE)
            or self.attack_positions[1][1][0] <= runtime_globals.PET_WIDTH + (5 * runtime_globals.UI_SCALE)
        )

    def process_attack_result(self):
        """Process the result of an attack and advance to next pattern"""
        correct = self.pattern[self.current_index] != self.player_input
        if correct:
            runtime_globals.game_sound.play("attack_hit")
            self.victories += 1
        else:
            runtime_globals.game_sound.play("attack_fail")
            self.failures += 1
            
        self.current_index += 1
        if self.current_index >= len(self.pattern):
            self.phase = "result"
            self.frame_counter = 0
            runtime_globals.game_console.log(f"Head-to-Head training done: {self.victories} wins, {self.failures} fails")
        else:
            self.phase = "charge"
            self.attack_positions.clear()

    def draw(self, surface):
        """Draw the head charge minigame components"""
        if self.phase == "result":
            self.draw_result(surface)
        else:
            self.draw_strikes_counter(surface)
            self.draw_pets(surface)
            if self.phase == "attack_move":
                self.draw_attacks(surface)

            # Draw UI buttons only if mouse is available (and not on result screen)
            mouse_enabled = (runtime_globals.INPUT_MODE == runtime_globals.MOUSE_MODE or runtime_globals.INPUT_MODE == runtime_globals.TOUCH_MODE)
            if self.phase != "result" and mouse_enabled:
                self.up_button.draw(surface)
                self.down_button.draw(surface)

    def draw_strikes_counter(self, surface):
        """Draw the strikes counter using HeadTraining_Back (208x48) and HeadTraining_Strike (32x32)"""
        strikes_back = self._sprite_cache['strikes_back']
        strikes = self._sprite_cache['strikes']
        
        # Position at bottom right (not touching the border)
        margin = int(10 * runtime_globals.UI_SCALE)
        starting_x = runtime_globals.SCREEN_WIDTH - strikes_back.get_width() - margin
        starting_y = runtime_globals.SCREEN_HEIGHT - strikes_back.get_height() - margin
        
        blit_with_shadow(surface, strikes_back, (starting_x, starting_y))

        # Calculate sprite scale factor for positioning
        sprite_scale_factor = runtime_globals.UI_SCALE / 2
        
        # Strike positioning: first at 12,8, last at 156,8 with 4px distance between them
        # Strikes are 32px wide, so: first=12, second=48, third=84, fourth=120, fifth=156
        first_strike_x = int(12 * sprite_scale_factor)
        strike_y = int(8 * sprite_scale_factor)
        strike_width = int(32 * sprite_scale_factor)  # Strike sprite width scaled
        strike_spacing = int(4 * sprite_scale_factor)  # 4px spacing scaled
        
        # Draw remaining strikes (5 - current_index), removed from right to left
        strikes_remaining = 5 - self.current_index
        for i in range(strikes_remaining):
            # Calculate x position for each strike from right to left
            strike_index = strikes_remaining - 1 - i  # Strike index from right to left
            x = starting_x + first_strike_x + (strike_index * (strike_width + strike_spacing))
            y = starting_y + strike_y
            blit_with_shadow(surface, strikes, (x, y))

    def draw_pets(self, surface):
        """Draw the two pets in attack poses using cached scaled sprites"""
        # Use cached scaled pet sprites - use flipped versions for left pet
        if self.phase == "attack_move":
            left_sprite_key = 'left_pet_atk2_flipped'
            right_sprite_key = 'right_pet_atk2'
        else:
            left_sprite_key = 'left_pet_atk1_flipped'
            right_sprite_key = 'right_pet_atk1'
        
        left_sprite = self._sprite_cache.get(left_sprite_key)
        right_sprite = self._sprite_cache.get(right_sprite_key)
        
        # Debug: Log sprite IDs every 60 frames to detect changes
        if not hasattr(self, '_draw_frame_counter'):
            self._draw_frame_counter = 0
        self._draw_frame_counter += 1
        if self._draw_frame_counter % 60 == 1:
            runtime_globals.game_console.log(f"[HeadCharge.draw_pets] Frame {self._draw_frame_counter}: phase={self.phase}")
            runtime_globals.game_console.log(f"[HeadCharge.draw_pets] left_sprite ({left_sprite_key}) id={id(left_sprite)}, size={left_sprite.get_size() if left_sprite else 'None'}")
            runtime_globals.game_console.log(f"[HeadCharge.draw_pets] right_sprite ({right_sprite_key}) id={id(right_sprite)}, size={right_sprite.get_size() if right_sprite else 'None'}")
        
        if not left_sprite or not right_sprite:
            runtime_globals.game_console.log(f"[HeadCharge.draw_pets] ERROR: Missing sprite! left={left_sprite}, right={right_sprite}")
            return

        # Calculate positions to center the scaled sprites
        left_x = 0 + (5 * runtime_globals.UI_SCALE)
        self.left_y = runtime_globals.SCREEN_HEIGHT // 2 - self.pet_size // 2
        right_x = runtime_globals.SCREEN_WIDTH - self.pet_size - (5 * runtime_globals.UI_SCALE)
        self.right_y = runtime_globals.SCREEN_HEIGHT // 2 - self.pet_size // 2

        blit_with_shadow(surface, left_sprite, (left_x, self.left_y))
        blit_with_shadow(surface, right_sprite, (right_x, self.right_y))

    def draw_attacks(self, surface):
        """Draw the attack sprites moving across screen"""
        for sprite, (x, y) in self.attack_positions:
            blit_with_shadow(surface, sprite, (int(x), int(y)))

    def draw_result(self, surface):
        """Draw the final result screen with scores"""
        center_x = runtime_globals.SCREEN_WIDTH // 2
        center_y = runtime_globals.SCREEN_HEIGHT // 2
        head_training_img = self._sprite_cache['head_training_img']
        vs_img = self._sprite_cache['vs_img']

        # Draw header image
        blit_with_shadow(
            surface,
            head_training_img,
            (center_x - head_training_img.get_width() // 2, center_y - head_training_img.get_height() - int(20 * runtime_globals.UI_SCALE))
        )

        font = self.up_button.get_font(custom_size=int(48 * runtime_globals.UI_SCALE))
        
        wins_text = font.render(str(self.victories), True, constants.FONT_COLOR_DEFAULT)
        losses_text = font.render(str(self.failures), True, constants.FONT_COLOR_DEFAULT)

        # Layout: wins + VS + losses
        total_width = wins_text.get_width() + vs_img.get_width() + losses_text.get_width() + int(20 * runtime_globals.UI_SCALE)
        start_x = center_x - total_width // 2
        y = center_y + int(15 * runtime_globals.UI_SCALE)

        blit_with_shadow(surface, wins_text, (start_x, y))
        blit_with_shadow(surface, vs_img, (start_x + wins_text.get_width() + int(10 * runtime_globals.UI_SCALE), y - (4 * runtime_globals.UI_SCALE)))
        blit_with_shadow(surface, losses_text, (start_x + wins_text.get_width() + vs_img.get_width() + int(20 * runtime_globals.UI_SCALE), y))

    def is_complete(self):
        """Check if the minigame is complete"""
        return self.phase == "result"

    def check_victory(self):
        """Check if player won the minigame"""
        return self.victories > self.failures

    def get_attack_count(self):
        """
        Map victories (out of 5 hits) to attack count:
          5 wins -> 3
          4 wins -> 2  
          3 wins -> 1
          <3 wins -> 0 (defeat)
        """
        wins = max(0, min(self.victories, 5))
        if wins >= 5:
            return 3
        if wins == 4:
            return 2
        if wins == 3:
            return 1
        return 0