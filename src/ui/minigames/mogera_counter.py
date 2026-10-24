"""
Mogera Counter Minigame - Phase 1 of Mogera Training
Players must counter 5 random attacks (top/bottom) by pressing UP/DOWN in time
"""
import random
import pygame
from ui.ui_manager import UIManager
from ui.components.button import Button
from core import game_globals, runtime_globals
from models.animation import PetFrame
import core.constants as constants
from utils.pygame_utils import blit_with_shadow, load_attack_sprites, module_attack_sprites
from utils.module_utils import get_module
from utils.sprite_utils import snap_pet_sprite_size


class MogeraCounter:
    """Counter minigame for Mogera training phase 1"""

    def __init__(self, ui_manager: UIManager, pet):
        self.ui_manager = ui_manager
        self.pet = pet
        self.phase = "active"
        self.frame_counter = 0
        
        # Attack configuration
        self.total_attacks = 5
        self.countered_attacks = 0
        self.attacks = self._generate_attacks()
        self.current_attack_index = 0
        self.attack_x = -1000  # Start off screen, will be set to 0 after delay
        
        # Frame-rate independent speeds (baseline 30fps, pixels per second approach)
        # At 30fps: 3 pixels per frame = 90 pixels per second
        # Scale to actual frame rate: pixels_per_second * (1 / frame_rate)
        self.attack_speed = 4 * runtime_globals.UI_SCALE * (30.0 / constants.FRAME_RATE)  # Slightly slower for more reaction time
        self.counter_attack_speed = 4 * runtime_globals.UI_SCALE * (30.0 / constants.FRAME_RATE)
        
        # Attack delay system - wait between attacks
        self.attack_delay_duration = int(1.0 * constants.FRAME_RATE)  # 1 second delay between attacks at any frame rate
        self.attack_delay_timer = self.attack_delay_duration  # Start with delay so first attack shows after delay
        
        # Pet state - stays in TRAIN1 until input, then TRAIN2 while counter attack moves
        self.pet_frame = PetFrame.TRAIN1
        self.has_countered_current = False  # Track if current attack was countered
        
        # Counter attack animation (pet's attack moving towards incoming attack)
        self.counter_attack_sprite = None
        self.counter_attack_x = 0
        self.counter_attack_y = 0
        self.is_counter_attack_moving = False
        self.counter_attack_lane = None  # 'top' or 'bottom' to track collision lane
        self.counter_input_locked = False  # Prevent multiple inputs per attack
        
        # Hit animation
        self.last_attack_result = None  # "hit", "miss", or None
        self.hit_animation_timer = 0
        self.hit_animation_duration = int(15 * (constants.FRAME_RATE / 30))  # 0.5 seconds at any frame rate
        self.hit_x = 0
        self.hit_y = 0
        
        # Load sprites
        sprite_scale = runtime_globals.UI_SCALE
        self.antigrav1_sprite = ui_manager.load_sprite_non_integer_scaling("assets/AntiG1.png", sprite_scale)
        self.antigrav2_sprite = ui_manager.load_sprite_non_integer_scaling("assets/AntiG2.png", sprite_scale)
        self.hit1_sprite = ui_manager.load_sprite_non_integer_scaling("assets/TrainingHit1.png", sprite_scale)
        self.hit2_sprite = ui_manager.load_sprite_non_integer_scaling("assets/TrainingHit2.png", sprite_scale)
        
        # Get pet's attack sprite
        self.attack_sprites = load_attack_sprites()
        self.module_attack_sprites = module_attack_sprites(pet.module)

        # Cache for scaled pet frames per UI scale
        self._pet_frame_cache = {}
        self._cached_pet_size = snap_pet_sprite_size(48 * runtime_globals.UI_SCALE)
        
        # Create arrow buttons for mouse mode using UI manager's base coordinate system (240x240)
        ui_base = 240  # UI manager's base resolution
        button_size = 30  # Base size in UI coordinates
        center_x = ui_base // 2 - button_size // 2  # Center horizontally
        
        # UP button at middle top (same position as head_charge.py)
        up_y = 40  # UI coordinates
        self.arrow_up_button = Button(
            center_x, up_y, 
            button_size, button_size, "",
            callback=lambda: self.handle_button_press(("UP", None)),
            decorators=["ArrowUp"], shadow_mode="full"
        )
        ui_manager.add_component(self.arrow_up_button)
        
        # DOWN button at middle bottom (same position as head_charge.py)
        down_y = ui_base - button_size - 40  # UI coordinates
        self.arrow_down_button = Button(
            center_x, down_y,
            button_size, button_size, "",
            callback=lambda: self.handle_button_press(("DOWN", None)),
            decorators=["ArrowDown"], shadow_mode="full"
        )
        ui_manager.add_component(self.arrow_down_button)

    def _generate_attacks(self):
        """Generate 5 random attacks (top or bottom)"""
        return [random.choice(["top", "bottom"]) for _ in range(self.total_attacks)]
    
    def _is_dot_pet(self):
        enable_old = getattr(game_globals.configuration, 'enable_old_sprites', False)
        if not enable_old:
            return False
        mod = get_module(self.pet.module)
        if mod is None:
            return False
        return getattr(mod, 'primary_sprite_format', 'Color') == 'Dot' or getattr(mod, 'secondary_sprite_format', 'HD') == 'Dot'

    def get_attack_sprite(self):
        """Get pet's attack sprite sized to match AntiG sprites"""
        atk_id = str(self.pet.atk_main)
        is_dot = self._is_dot_pet()
        target_size = (self.antigrav1_sprite.get_width(), self.antigrav1_sprite.get_height())

        if self.module_attack_sprites:
            if is_dot:
                dot_sprite = self.module_attack_sprites.get(f"{atk_id}_dot")
                if dot_sprite:
                    return pygame.transform.scale(dot_sprite, target_size)
            sprite = self.module_attack_sprites.get(atk_id)
            if sprite:
                return pygame.transform.scale(sprite, target_size)

        if is_dot:
            dot_sprite = self.attack_sprites.get(f"{atk_id}_dot")
            if dot_sprite:
                return pygame.transform.scale(dot_sprite, target_size)
        default_sprite = self.attack_sprites.get(atk_id)
        if default_sprite:
            return pygame.transform.scale(default_sprite, target_size)
        return None

    #========================
    # Update Methods
    #========================

    def update(self):
        """Main update dispatcher"""
        self.frame_counter += 1
        
        if self.phase == "active":
            self.update_active()
        elif self.phase == "complete":
            pass

    def update_active(self):
        """Update during active counter phase"""
        if self.current_attack_index >= self.total_attacks:
            self.phase = "complete"
            return
        
        # Handle attack delay timer - wait before showing next attack
        if self.attack_delay_timer > 0:
            self.attack_delay_timer -= 1
            # When delay finishes, start the attack from the left edge
            if self.attack_delay_timer == 0:
                self.attack_x = 0
            return  # Don't update anything during delay
        
        # Move incoming attack from left to right (only if it's on screen)
        if self.attack_x >= 0:
            self.attack_x += self.attack_speed
        
        # Calculate pet position for collision detection
        pet_size = snap_pet_sprite_size(48 * runtime_globals.UI_SCALE)
        pet_x = runtime_globals.SCREEN_WIDTH - pet_size - int(20 * runtime_globals.UI_SCALE)
        
        # Check if attack hit the pet without being countered
        if self.attack_x >= pet_x and not self.has_countered_current:
            self.has_countered_current = True  # Mark as processed
            self.counter_input_locked = True
            self.last_attack_result = "miss"
            self.hit_animation_timer = self.hit_animation_duration
            self.hit_x = pet_x
            current_attack = self.attacks[self.current_attack_index]
            pet_y = runtime_globals.SCREEN_HEIGHT // 2 - pet_size // 2
            if current_attack == "top":
                self.hit_y = pet_y + pet_size // 3
            else:
                self.hit_y = pet_y + (pet_size * 2) // 3
            runtime_globals.game_console.log(f"[DEBUG] ATTACK HIT PET - Attack #{self.current_attack_index + 1}, hit_pos=({self.hit_x}, {self.hit_y})")
            runtime_globals.game_sound.play("fail")
        
        # Move counter attack if active
        if self.is_counter_attack_moving:
            self.counter_attack_x -= self.counter_attack_speed
            
            # Check if counter attack reached the incoming attack (collision)
            # Use sprite widths for accurate collision detection
            counter_sprite_width = self.counter_attack_sprite.get_width() if self.counter_attack_sprite else int(24 * runtime_globals.UI_SCALE)
            current_attack = self.attacks[self.current_attack_index]
            attack_sprite = self.antigrav1_sprite if current_attack == "top" else self.antigrav2_sprite
            attack_sprite_width = attack_sprite.get_width()
            
            # Check if sprites touch/overlap (counter's left edge + width >= attack's left edge)
            lanes_match = self.counter_attack_lane == current_attack
            if lanes_match and self.counter_attack_x + counter_sprite_width >= self.attack_x and self.counter_attack_x <= self.attack_x + attack_sprite_width:
                # Collision! Calculate position BEFORE moving sprites off screen
                collision_x = (self.counter_attack_x + counter_sprite_width + self.attack_x) // 2
                collision_y = int(self.counter_attack_y + counter_sprite_width // 2)
                
                runtime_globals.game_console.log(f"[DEBUG] COLLISION DETECTED - counter_x={int(self.counter_attack_x)}, attack_x={int(self.attack_x)}, collision_pos=({collision_x}, {collision_y})")
                
                # Now remove both sprites
                self.is_counter_attack_moving = False
                self.counter_attack_sprite = None  # Remove counter sprite
                original_attack_x = self.attack_x  # Store for debug
                self.attack_x = -1000  # Move attack off screen so it doesn't draw
                self.countered_attacks += 1  # Count successful counter
                self.last_attack_result = "hit"
                self.hit_animation_timer = self.hit_animation_duration
                self.hit_x = collision_x
                self.hit_y = collision_y
                self.has_countered_current = True  # Mark as processed
                self.counter_attack_lane = None
                
                runtime_globals.game_console.log(f"[DEBUG] HIT ANIMATION SET - hit_timer={self.hit_animation_timer}, hit_pos=({self.hit_x}, {self.hit_y}), countered_total={self.countered_attacks}")
                runtime_globals.game_sound.play("attack_hit")
            
            # Check if counter attack went off near left edge without hitting (miss)
            # Use 20px on 240 baseline = 20 * UI_SCALE
            elif self.counter_attack_x < int(20 * runtime_globals.UI_SCALE):
                # Miss! Counter attack went off screen without hitting
                self.is_counter_attack_moving = False
                self.counter_attack_sprite = None  # Remove counter sprite
                self.counter_attack_lane = None
                # Don't mark has_countered_current here - let incoming attack continue
                runtime_globals.game_console.log(f"[DEBUG] COUNTER WENT OFF SCREEN - counter_x={int(self.counter_attack_x)}, attack_x={int(self.attack_x)}, attack continues")
                runtime_globals.game_sound.play("fail")
        
        # Check if we should move to next attack
        # Move on when: attack went off screen (missed), or hit animation finished (hit or wrong input)
        should_next = False
        if self.has_countered_current and self.hit_animation_timer == 0 and not self.is_counter_attack_moving:
            # Counter succeeded or failed, hit animation done
            should_next = True
        elif not self.has_countered_current and self.attack_x > runtime_globals.SCREEN_WIDTH:
            # Attack went off screen without being countered (shouldn't happen but failsafe)
            should_next = True
        
        if should_next:
            self._next_attack()
        
        # Update hit animation timer
        if self.hit_animation_timer > 0:
            self.hit_animation_timer -= 1
            if self.hit_animation_timer == 0:
                self.last_attack_result = None
        
        # Update buttons for mouse support
        mouse_enabled = (runtime_globals.INPUT_MODE ==  runtime_globals.MOUSE_MODE or runtime_globals.INPUT_MODE == runtime_globals.TOUCH_MODE)
        if mouse_enabled:
            self.arrow_up_button.update()
            self.arrow_down_button.update()

    def _next_attack(self):
        """Move to the next attack"""
        runtime_globals.game_console.log(f"[DEBUG] NEXT ATTACK - Moving from #{self.current_attack_index + 1} to #{self.current_attack_index + 2}")
        self.current_attack_index += 1
        
        # Set attack off screen and start delay timer
        self.attack_x = -1000  # Off screen
        self.attack_delay_timer = self.attack_delay_duration  # Start delay before next attack
        
        self.has_countered_current = False
        self.counter_input_locked = False
        # Reset to TRAIN1 for the next incoming attack
        self.pet_frame = PetFrame.TRAIN1
        self.is_counter_attack_moving = False
        self.counter_attack_sprite = None
        self.counter_attack_lane = None
        
        if self.current_attack_index >= self.total_attacks:
            self.phase = "complete"
            runtime_globals.game_console.log(f"[DEBUG] COUNTER PHASE COMPLETE - Total countered: {self.countered_attacks}/5")

    #========================
    # Event Handling
    #========================

    def handle_button_press(self, direction):
        """Handle button press from UI buttons"""
        return self.handle_event(direction)

    def handle_event(self, event):
        """Handle player input for countering attacks"""
        if self.phase != "active" or self.current_attack_index >= self.total_attacks:
            return False
        
        event_type, event_data = event
        
        # Handle LCLICK by checking button positions
        if event_type == "LCLICK":
            if event_data and "pos" in event_data:
                mouse_pos = event_data["pos"]
                # Check if mouse is over UP button
                if self.arrow_up_button.rect.collidepoint(mouse_pos):
                    return self._process_counter_input("UP")
                # Check if mouse is over DOWN button
                elif self.arrow_down_button.rect.collidepoint(mouse_pos):
                    return self._process_counter_input("DOWN")
            return False
        elif event_type in ("UP", "DOWN"):
            # Only process keyboard UP/DOWN inputs
            return self._process_counter_input(event_type)
        
        return False
    
    def _process_counter_input(self, direction):
        """Process counter input (UP or DOWN)"""
        # Can only counter once per attack
        if self.has_countered_current or self.counter_input_locked:
            return False
        
        # Can't input during delay or before attack appears
        if self.attack_delay_timer > 0 or self.attack_x < 0:
            return False
        
        # Player can input from when attack appears until it hits
        if self.attack_x >= 0:
            current_attack = self.attacks[self.current_attack_index]
            lane_from_direction = "top" if direction.upper() == "UP" else "bottom"
            
            # Check for correct input
            if (direction == "UP" and current_attack == "top") or \
               (direction == "DOWN" and current_attack == "bottom"):
                # Success! Launch counter attack
                self.has_countered_current = True
                self.counter_input_locked = True
                
                # Change to TRAIN2 animation and stay in it
                self.pet_frame = PetFrame.TRAIN2
                
                if self._launch_counter_attack(current_attack):
                    runtime_globals.game_console.log(f"[DEBUG] COUNTER LAUNCHED - Attack #{self.current_attack_index + 1}, type={current_attack}, counter_start_x={int(self.counter_attack_x)}, attack_x={int(self.attack_x)}")
                
                # Play sound
                runtime_globals.game_sound.play("attack")  # Pet attack sound
                return True
            else:
                # Wrong input - DO NOT mark as countered, let incoming attack continue
                # Fire counter attack down the lane the player selected for visual feedback
                self.counter_input_locked = True
                if self._launch_counter_attack(lane_from_direction):
                    runtime_globals.game_console.log(
                        f"[DEBUG] WRONG INPUT - Attack #{self.current_attack_index + 1}, expected={current_attack}, got={direction}, counter_lane={lane_from_direction}"
                    )
                else:
                    runtime_globals.game_console.log(
                        f"[DEBUG] WRONG INPUT (NO SPRITE) - Attack #{self.current_attack_index + 1}, expected={current_attack}, got={direction}"
                    )
                runtime_globals.game_sound.play("attack")
                return False
        
        return False

    def _launch_counter_attack(self, lane):
        """Create and launch the counter attack projectile on the requested lane."""
        attack_sprite = self.get_attack_sprite()
        if not attack_sprite:
            runtime_globals.game_console.log(f"[MogeraCounter] Warning: No attack sprite found for pet {self.pet.name}")
            return False

        self.counter_attack_sprite = attack_sprite
        pet_size = snap_pet_sprite_size(48 * runtime_globals.UI_SCALE)
        pet_x = runtime_globals.SCREEN_WIDTH - pet_size - int(20 * runtime_globals.UI_SCALE)
        pet_y = runtime_globals.SCREEN_HEIGHT // 2 - pet_size // 2

        if lane == "top":
            self.counter_attack_y = pet_y + pet_size // 3 - attack_sprite.get_height() // 2
        else:
            self.counter_attack_y = pet_y + (pet_size * 2) // 3 - attack_sprite.get_height() // 2

        self.counter_attack_x = pet_x
        self.counter_attack_lane = lane
        self.is_counter_attack_moving = True
        return True

    #========================
    # Draw Methods
    #========================

    def draw(self, surface):
        """Main draw dispatcher"""
        if self.phase == "active":
            self.draw_active(surface)
        elif self.phase == "complete":
            self.draw_active(surface)  # Show final state

    def draw_active(self, surface):
        """Draw during active counter phase"""
        # Draw pet on the right side - positioned to align with attacks
        pet_size = snap_pet_sprite_size(48 * runtime_globals.UI_SCALE)
        if pet_size != self._cached_pet_size:
            self._pet_frame_cache.clear()
            self._cached_pet_size = pet_size
        pet_x = runtime_globals.SCREEN_WIDTH - pet_size - int(20 * runtime_globals.UI_SCALE)
        pet_y = runtime_globals.SCREEN_HEIGHT // 2 - pet_size // 2

        # Get pet sprite using the current frame (TRAIN1 or TRAIN2), cached scaling
        try:
            pet_sprite = runtime_globals.pet_sprites[self.pet][self.pet_frame.value]
            cached = self._pet_frame_cache.get(self.pet_frame.value)
            if cached is None or cached.get_size() != (pet_size, pet_size):
                cached = pygame.transform.scale(pet_sprite, (pet_size, pet_size))
                self._pet_frame_cache[self.pet_frame.value] = cached
            blit_with_shadow(surface, cached, (pet_x, pet_y))
        except (KeyError, IndexError) as e:
            runtime_globals.game_console.log(f"[MogeraCounter] Error loading pet sprite frame {self.pet_frame.value}: {e}")
            # Fallback to IDLE1 if frame not available
            try:
                pet_sprite = runtime_globals.pet_sprites[self.pet][PetFrame.IDLE1.value]
                cached = self._pet_frame_cache.get(PetFrame.IDLE1.value)
                if cached is None or cached.get_size() != (pet_size, pet_size):
                    cached = pygame.transform.scale(pet_sprite, (pet_size, pet_size))
                    self._pet_frame_cache[PetFrame.IDLE1.value] = cached
                blit_with_shadow(surface, cached, (pet_x, pet_y))
            except:
                pass  # Give up if even IDLE1 doesn't work
        
        # Draw current attack if active (not during delay, not off screen)
        if self.current_attack_index < self.total_attacks and self.attack_x >= 0 and self.attack_delay_timer == 0:
            current_attack = self.attacks[self.current_attack_index]
            attack_sprite = self.antigrav1_sprite if current_attack == "top" else self.antigrav2_sprite
            
            # Position attack to align with pet vertically - closer to pet
            # Top attacks align with top third of pet, bottom with bottom third
            if current_attack == "top":
                attack_y = pet_y + pet_size // 3 - attack_sprite.get_height() // 2
            else:  # bottom
                attack_y = pet_y + (pet_size * 2) // 3 - attack_sprite.get_height() // 2
            
            blit_with_shadow(surface, attack_sprite, (int(self.attack_x), int(attack_y)))
        
        # Draw counter attack sprite if moving (pet's attack moving left towards incoming attack)
        if self.is_counter_attack_moving and self.counter_attack_sprite:
            blit_with_shadow(surface, self.counter_attack_sprite, (int(self.counter_attack_x), int(self.counter_attack_y)))
        
        # Draw hit animation at stored position (centered on collision point)
        if self.hit_animation_timer > 0:
            # Alternate between hit sprites
            hit_sprite = self.hit2_sprite if self.hit_animation_timer % int(10 * (constants.FRAME_RATE / 30)) < int(5 * (constants.FRAME_RATE / 30)) else self.hit1_sprite
            
            # Draw centered on collision point
            hit_x = self.hit_x - hit_sprite.get_width() // 2
            hit_y = self.hit_y - hit_sprite.get_height() // 2
            
            if self.frame_counter % 30 == 0:  # Log every 30 frames
                runtime_globals.game_console.log(f"[DEBUG] DRAWING HIT ANIMATION - timer={self.hit_animation_timer}, draw_pos=({int(hit_x)}, {int(hit_y)}), stored_pos=({self.hit_x}, {self.hit_y})")
            
            blit_with_shadow(surface, hit_sprite, (int(hit_x), int(hit_y)))
        
        # Draw arrow buttons if mouse is enabled
        mouse_enabled = (runtime_globals.INPUT_MODE == runtime_globals.MOUSE_MODE or runtime_globals.INPUT_MODE == runtime_globals.TOUCH_MODE)
        if mouse_enabled:
            self.arrow_up_button.draw(surface)
            self.arrow_down_button.draw(surface)

    def is_complete(self):
        """Check if the counter phase is complete"""
        return self.phase == "complete"

    def get_countered_count(self):
        """Get the number of successfully countered attacks"""
        return self.countered_attacks
