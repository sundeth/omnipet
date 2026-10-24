import math
import time
import pygame
import random
from core import runtime_globals
import core.constants as constants
from utils.pygame_utils import get_font, get_font_alt, sprite_load_percent
from utils.scene_utils import change_scene
from utils.asset_utils import image_load
from models.game_digidex import is_pet_unlocked
from services.omninet_service import omninet_service

# Constants
FONT_COLOR_DEFAULT = constants.FONT_COLOR_DEFAULT
PARTICLE_SPEED = 2
PARTICLE_LIFE = 30
REVEAL_TIME = 90
BEAM_PHASE_DURATION = 190
NUM_BEAMS = 22
BASE_SPRITE_SIZE = 72
CENTER_COLOR = (181, 255, 255)

class SceneEvolution:
    """The evolution cutscene: an experimental 0.9.x preview, not wired in.

    Nothing sets ``runtime_globals.evolution_pet`` (an evolution plays its
    jingle and swaps the sprite in place), and the main scene's trigger is
    switched off (``scene_maingame.EVOLUTION_CUTSCENE``). Reached without an
    evolution to show, the scene goes straight back to the game.
    """

    def __init__(self):
        self.evolutions = runtime_globals.evolution_data
        self.phase = "flash"
        self.frame_counter = 0
        #: Nothing to show: leave on the first update instead of raising.
        self._empty = not self.evolutions or runtime_globals.evolution_pet is None
        if self._empty:
            return

        # Check digidex BEFORE the scene completes so we can reward "new pet"
        # only when the evolved form has never been registered before.
        _evo = self.evolutions[0]
        _pet = runtime_globals.evolution_pet
        _module = getattr(_pet, 'module', '') if _pet else ''
        _version = getattr(_pet, 'version', 0) if _pet else 0
        self._evo_to_name = _evo.to_name
        self._evo_module = _module
        self._evo_version = _version
        self._evo_is_new_pet = not is_pet_unlocked(_evo.to_name, _module, _version)
        self._rewards_fired = False
        if self.evolutions[0].stage == 5:
            self.phase = "mega_intro"
            # 🔹 Draw the background sprite using the new method, scaled to screen width
            self.evo_background = sprite_load_percent(constants.EVO5_PATH, percent=100, keep_proportion=True, base_on="width")
            self.from_sprite_scaled = pygame.transform.scale(self.evolutions[0].from_sprite, (int(100 * runtime_globals.UI_SCALE), int(100 * runtime_globals.UI_SCALE)))
            self.to_sprite_scaled = pygame.transform.scale(self.evolutions[0].to_sprite, (int(100 * runtime_globals.UI_SCALE), int(100 * runtime_globals.UI_SCALE)))
            self.sectors = self.get_non_transparent_sectors(self.from_sprite_scaled)
            self.active_green_pixels = []
            self.active_particles = []
            self.replace_pixel = []

        self.frame_counter = 0
        self.particles = []
        self.energy_pixels = self.get_sprite_contour(self.evolutions[0].from_sprite)
        self.active_energy_pixels = []
        self.energy_index = 0

        self.font = get_font(runtime_globals.FONT_SIZE_MEDIUM)
        self.fonts = [get_font(20), get_font(26), get_font_alt(20), get_font_alt(26)]

        # Use new method for fog image, scale to screen width
        self.fog_image = sprite_load_percent(constants.FOG_PATH, percent=100, keep_proportion=True, base_on="width")
        self.fog_x, self.fog_y = 0, 0  # Starting position


        self.surface_flash = self.create_flash_surface()
        self.scroll_texts = []
        self.prepare_scrolling_texts(self.evolutions[0].from_name)

        # Background & beams
        self.bg_base = sprite_load_percent(constants.EVO2_PATH, percent=100, keep_proportion=True, base_on="width")
        self.bg_angle = 0

        if runtime_globals.evolution_pet.stage == 3:
            self.beam_sprite = sprite_load_percent(constants.EVO3_PATH, percent=100, keep_proportion=True, base_on="width")
            self.beams = []
            self.prepare_beams()

        self.rain_drops = []

        self.orb_sprite = sprite_load_percent(constants.ORB_PATH, percent=100, keep_proportion=True, base_on="width")

        self.evo_text_image = sprite_load_percent(constants.EVO1_PATH, percent=100, keep_proportion=True, base_on="width")
        self.evo_text_size = int(480 * runtime_globals.UI_SCALE)  # Initial size
        self.evo_text_angle = 0

        self.explosion_flash = None
        self.light_particles = []
        self.light_source = sprite_load_percent(constants.LIGHT_SOURCE_PATH, percent=100, keep_proportion=True, base_on="width")
        self.light_particle1 = pygame.transform.scale(self.light_source, (int(8 * runtime_globals.UI_SCALE), int(8 * runtime_globals.UI_SCALE)))
        self.light_particle2 = pygame.transform.scale(sprite_load_percent(constants.LIGHT_PARTICLE_PATH, percent=100, keep_proportion=True, base_on="width"), (int(8 * runtime_globals.UI_SCALE), int(8 * runtime_globals.UI_SCALE)))

        self.dna_particles = []  # List of falling DNA sprites
        self.dna_sprite = sprite_load_percent(constants.DNA_PATH, percent=100, keep_proportion=True, base_on="width")

        self.color_list = self.extract_sprite_colors(self.evolutions[0].to_sprite)

    # =================== Update Logic ===================
    def update(self):
        if self._empty:
            change_scene("game")
            return
        self.frame_counter += 1
        self.update_scrolling_texts()
        self.bg_angle = (self.bg_angle + 6) % 360
        self.update_fog()
        phase_methods = {
            "flash": self.update_phase_flash,
            "symbol": self.update_phase_symbol,
            "mega_intro": self.update_phase_mega_intro,
            "mega_shine": self.update_phase_mega_shine,
            "mega_energy": self.update_phase_mega_energy,
            "mega_transformation": self.update_phase_mega_transformation,
            "mega_orb": self.update_phase_mega_orb,
            "show": self.update_phase_show,
            "rain": self.update_phase_rain,
            "beams": self.update_phase_beams,
            "explode": self.update_phase_explode,
            "pre_reveal_flash": self.update_phase_pre_reveal_flash,
            "reveal": self.update_phase_reveal,
            "done": self.update_phase_done
        }

        phase_methods.get(self.phase, lambda: None)()

    def plays_own_input_sounds(self):
        return True

    def handle_event(self, event):
        if not isinstance(event, tuple) or len(event) != 2:
            return
        event_type, event_data = event
        # Evolution scene is non-interactive during animation
        pass

    def switch_phase(self, new_phase, reset_particles = True):
        self.phase = new_phase
        self.frame_counter = 0
        if reset_particles:
            self.particles = []
            self.rain_drops = []
            self.light_particles = []
        runtime_globals.game_console.log(self.phase)

    def update_phase_mega_transformation(self):
        """Handles sprite explosion and pixel replacement per sector."""

        # 🔹 Replace the last sector's green pixels with to_sprite pixels
        if self.active_green_pixels:
            for pixel in self.active_green_pixels:
                self.replace_pixel(pixel["x"], pixel["y"], self.to_sprite_scaled)

        # 🔥 Pick a random sector that hasn't been used yet
        if self.sectors:
            sector_index = random.randint(0, len(self.sectors) - 1)
            sector_x, sector_y = self.sectors.pop(sector_index)  # 🔥 Remove sector to avoid repetition
            
            self.generate_explosion_particles(sector_x, sector_y)  # 🔥 Trigger explosion particles

            # 🔹 Replace pixels in the sector with green overlay
            self.active_green_pixels.extend([
                {"x": sector_x + dx, "y": sector_y + dy, "alpha": 255} for dx in range(5) for dy in range(5)
            ])

        # 🔥 Fade and remove particles
        for particle in self.active_particles:
            particle["x"] += particle["dx"]
            particle["y"] += particle["dy"]
            particle["alpha"] = max(0, particle["alpha"] - 5)

        # 🔹 Transition once all sectors have exploded
        if not self.sectors:
            self.switch_phase("next_phase")

    def get_non_transparent_sectors(self, sprite):
        """Splits the sprite into 5x5 sectors, ignoring fully transparent sections."""
        mask = pygame.mask.from_surface(sprite)
        sectors = []
        
        for sx in range(0, 100, 5):
            for sy in range(0, 100, 5):
                # 🔹 Check if sector has at least one visible pixel
                if any(mask.get_at((sx + dx, sy + dy)) for dx in range(5) for dy in range(5)):
                    sectors.append((sx, sy))
        
        return sectors
    
    def generate_explosion_particles(self, sector_x, sector_y, color=(0, 255, 0)):
        """Creates explosion particles for mega transformation, spreading outward."""
        if len(self.particles) >= 60:  
            return  # 🔹 Limit particle count to avoid excessive rendering

        for _ in range(5):  # 🔥 Generate multiple particles per sector
            self.particles.append([
                sector_x + random.randint(0, 5),  # x position within the sector
                sector_y + random.randint(0, 5),  # y position within the sector
                random.uniform(-2, 2),  # dx (move in random outward direction)
                random.uniform(-2, 2),  # dy (move in random outward direction)
                color,  # Green explosion color
                100  # Lifetime
            ])

    def update_phase_mega_orb(self):
        """Cycles through the Orb sprite sheet for 30 frames."""
        # 🔹 Transition after 30 frames
        if self.frame_counter >= 60:
            self.switch_phase("mega_transformation")
            
    def update_phase_mega_intro(self):
        """Handles the Mega evolution intro by showcasing the pet and moving it downward."""
        
        self.generate_falling_particles((255, 165, 0), 100)
        self.update_falling_particles()

        # 🔹 Wait for 1 second before moving
        if self.frame_counter < 30:
            return
        
        #runtime_globals.evolution_pet.y += 1

        if self.frame_counter == 60:
            self.explosion_flash = pygame.Surface((runtime_globals.SCREEN_WIDTH, runtime_globals.SCREEN_HEIGHT))
            self.explosion_flash.fill((255, 255, 255))
            self.flash_alpha = 255
            self.switch_phase("mega_shine", False)

    def update_phase_mega_shine(self):
        """Handles the mega evolution shine effect."""
        if self.flash_alpha > 0 and self.explosion_flash:
            self.flash_alpha = abs(255 - (self.frame_counter % 10) * 50)
            self.explosion_flash.set_alpha(self.flash_alpha)
        elif self.flash_alpha <= 0:
            self.explosion_flash = None

        self.generate_falling_particles((255, 165, 0), 100)
        self.update_falling_particles()

        # 🔹 Transition after 2 seconds
        if self.frame_counter > 60:
            self.flash_alpha = 0
            self.switch_phase("mega_energy", False)  # 🚀 Move to the next evolution phase

    def update_phase_mega_energy(self):
        """Animates green pixels appearing along the pet's contour over 120 frames."""
        self.generate_falling_particles((255, 165, 0), 100)
        self.update_falling_particles()

        # 🔹 Spread pixel activation over 120 frames (controlled step)
        step = max(1, len(self.energy_pixels) // 120)  
        new_pixels = self.energy_pixels[self.energy_index:self.energy_index + step]
        
        self.active_energy_pixels.extend([
            {"x": x, "y": y, "alpha": 255} for x, y in new_pixels
        ])
        
        # 🔥 Move activation index forward
        self.energy_index += step

        # 🔹 Apply fading over time
        for pixel in self.active_energy_pixels:
            pixel["alpha"] = max(0, pixel["alpha"] - 5)

        # 🔹 Transition after 120 frames
        if self.energy_index >= len(self.energy_pixels):
            self.switch_phase("mega_orb")

    def get_sprite_contour(self, sprite):
        """Extracts contour pixels from a sprite using edge detection, preventing out-of-bounds errors."""
        mask = pygame.mask.from_surface(sprite)  # 🔥 Generate sprite mask
        width, height = sprite.get_width(), sprite.get_height()
        contour = []

        for x in range(width):
            for y in range(height):
                if mask.get_at((x, y)):  # 🔹 Pixel is part of the sprite
                    # 🔥 Ensure neighboring pixels are within bounds
                    neighbors = [(1,0), (-1,0), (0,1), (0,-1)]
                    if not all(
                        0 <= x + dx < width and 0 <= y + dy < height and mask.get_at((x + dx, y + dy)) 
                        for dx, dy in neighbors
                    ):
                        contour.append((x, y))  # 🔥 Store edge pixel safely

        return contour

    def update_phase_rain(self):
        """Creates and updates falling rain particles."""
        if len(self.rain_drops) < 40:  # Maintain consistent density
            self.generate_rain_particles()

        # Move rain downward
        for drop in self.rain_drops:
            drop["y"] += drop["speed"]

        # Remove drops that fall past the screen
        self.rain_drops = [drop for drop in self.rain_drops if drop["y"] < runtime_globals.SCREEN_HEIGHT]

        if self.frame_counter > 90 and self.frame_counter < 120:
            self.generate_spiral_particles()

        self.update_light_particles()
        #self.update_phase_flash()

        if self.frame_counter >= 200:  # Transition after full rain effect
            self.generate_dna_particles()
            self.switch_phase("show")

    def generate_dna_particles(self):
        """Creates DNA particles falling in a vertical stream."""
        if not self.dna_particles or self.dna_particles[-1]["y"] > 0:  
            # 🔹 Only add a new particle if there's space for it
            self.dna_particles.append({
                "x": (runtime_globals.SCREEN_WIDTH - 37) // 2,  # Keep them centered
                "y": -47,  # Start just above the screen
                "speed": 10,  
                "disappeared_rows": 0  
            })

    def update_dna_particles(self):
        """Moves DNA particles downward and truncates them as they hit the Digimon."""
        digimon_y = (72 + runtime_globals.SCREEN_HEIGHT) // 2  

        for particle in self.dna_particles:
            particle["y"] += particle["speed"]

            # 🔹 Begin truncation when hitting the Digimon
            if particle["y"] + 47 >= digimon_y:
                particle["disappeared_rows"] += particle["speed"]  
                if particle["disappeared_rows"] >= 47:
                    self.dna_particles.remove(particle)  # Fully disappears after truncation

    def generate_rain_particles(self):
        """Creates falling rain particles that originate off-screen at the top."""
        for _ in range(2):  # Maintain consistent density
            self.rain_drops.append({
                "x": random.randint(0, runtime_globals.SCREEN_WIDTH),  # Random horizontal position
                "y": random.randint(-runtime_globals.SCREEN_HEIGHT, -10),  # 🔥 Start above the screen
                "speed": random.uniform(2, 5)  # Random fall speed
            })

    def generate_spiral_particles(self):
        """Creates particles that spiral inward from outside the screen before exploding."""
        if len(self.light_particles) >= 50:
            return

        center_x, center_y = runtime_globals.SCREEN_WIDTH // 2, runtime_globals.SCREEN_HEIGHT // 2

        # Extract sprite colors for particles

        for _ in range(10):
            angle = random.uniform(0, 2 * math.pi)  
            distance = random.uniform(runtime_globals.SCREEN_WIDTH // 2, runtime_globals.SCREEN_WIDTH) 
            speed = random.uniform(3, 7)  
            color = random.choice(self.color_list)

            self.light_particles.append({
                "x": center_x + math.cos(angle) * distance,
                "y": center_y + math.sin(angle) * distance,
                "dx": -math.cos(angle) * speed,  # 🔹 Move inward
                "dy": -math.sin(angle) * speed,
                "color": color,
                "scale": 0.1,
                "lifetime": 300
            })

    def update_light_particles(self):
        """Moves particles inward and holds them at the center until explosion."""

        for particle in self.light_particles:
            particle["x"] += particle["dx"]
            particle["y"] += particle["dy"]
            particle["lifetime"] -= 1

            if self.phase in ['rain', 'explode']:
                # 🔥 Stop movement when close enough to the center
                if abs(particle["x"] - runtime_globals.SCREEN_WIDTH // 2) < 5 and abs(particle["y"] - runtime_globals.SCREEN_HEIGHT // 2) < 5:
                    particle["dx"] = 0  # Stop movement
                    particle["dy"] = 0

        if self.flash_alpha > 0 and self.explosion_flash:
            self.flash_alpha = abs(255 - (self.frame_counter % 10) * 50)
            self.explosion_flash.set_alpha(self.flash_alpha)
        elif self.flash_alpha <= 0:
            self.explosion_flash = None

        # 🔹 Explode when all particles have converged and no rain remains
        if self.phase in ['rain', 'explode'] and self.frame_counter == 160:
            self.trigger_explosion()  

        # Remove expired particles
        self.light_particles = [p for p in self.light_particles if p["lifetime"] > 0]

    def generate_falling_particles(self, color=(181, 255, 255), y = 0):
        """Creates falling particles for stage 3 show phase using self.particles."""
        if len(self.particles) >= 60:  
            return

        for _ in range(1):  # Maintain density
            self.particles.append([
                random.randint(0, runtime_globals.SCREEN_WIDTH),  # x position
                random.randint(-runtime_globals.SCREEN_HEIGHT + y, -10 + y),  # Start above screen (y)
                0,  # dx (falling straight down)
                random.uniform(2, 5),  # dy (fall speed)
                color,  # Color (same as previous)
                100  # Lifetime
            ])

    def update_falling_particles(self):
        """Moves falling particles downward and removes expired ones."""
        for particle in self.particles:
            particle[1] += particle[3]  # Move down
            particle[5] -= 1  # Reduce lifetime

        # 🔹 Remove expired particles and those that fall beyond the screen
        self.particles = [p for p in self.particles if p[5] > 0 and p[1] < runtime_globals.SCREEN_HEIGHT]

    def trigger_explosion(self):
        """Triggers a burst explosion effect when particles converge at the center."""
        center_x, center_y = runtime_globals.SCREEN_WIDTH // 2, runtime_globals.SCREEN_HEIGHT // 2

        self.light_particles.clear()  # 🔥 Ensures old particles are removed
        explosion_particles = []

        for _ in range(50):
            angle = random.uniform(0, 2 * math.pi)
            speed = max(random.uniform(5, 10), 5.5)  # 🔹 Guarantees movement
            color = (255, 255, 255)

            explosion_particles.append({
                "x": center_x,
                "y": center_y,
                "dx": math.cos(angle) * speed,  # 🔥 Prevents zero velocity
                "dy": math.sin(angle) * speed,
                "color": color,
                "lifetime": 30
            })

        self.light_particles = explosion_particles 

        self.explosion_flash = pygame.Surface((runtime_globals.SCREEN_WIDTH, runtime_globals.SCREEN_HEIGHT))
        self.explosion_flash.fill((255, 255, 255))  # Full white flash
        self.explosion_flash.set_alpha(255)

    def update_fog(self):
        """Moves the fog background seamlessly."""
        self.fog_x = (self.fog_x + 1.0) % 512 
        self.fog_y = (self.fog_y + 1.0) % 512

    def update_scrolling_texts(self):
        """Updates the movement of scrolling text effects."""
        for scroll in self.scroll_texts:
            scroll[2] += scroll[4]  # Move horizontally based on speed
            if scroll[2] < -200 or scroll[2] > runtime_globals.SCREEN_WIDTH + 200:  # Check bounds
                scroll[2] = -200 if scroll[4] > 0 else runtime_globals.SCREEN_WIDTH + 200  # Reset position
                scroll[3] = random.randint(0, runtime_globals.SCREEN_HEIGHT - 20)  # Randomize vertical placement

    def update_phase_flash(self):
        self.flash_alpha = abs(255 - (self.frame_counter % 10) * 50)
        self.surface_flash.set_alpha(self.flash_alpha)

        if self.evolutions[0].stage == 3:
            self.update_phase_symbol()

        if self.flash_alpha <= 0:
            self.explosion_flash = None

        if self.frame_counter > 60:
            if self.evolutions[0].stage == 4:
                 self.switch_phase("rain")
            elif self.evolutions[0].stage == 3:
                self.switch_phase("symbol") 
            else:
                self.switch_phase("show")

    def update_phase_symbol(self):
        """Handles the rotating symbol effect before beams phase."""
        """Handles the rotating symbol effect before beams phase."""
        self.update_symbol_animation()

        if self.frame_counter > 90:  # ~3 seconds
            self.switch_phase("beams")

    def update_symbol_animation(self):
        """Handles rotation and shrinking of Evo1 symbol."""
        if self.evo_text_size <= 0:
            pass

        self.evo_text_angle += 2
        shrink_speed = 240 / BEAM_PHASE_DURATION
        self.evo_text_size = max(1, self.evo_text_size - shrink_speed)
            
    def update_phase_beams(self):
        self.update_symbol_animation()

        for beam in self.beams:
            beam["angle"] = (beam["angle"] + beam["rotation_speed"]) % 360

        if self.frame_counter >= 30:  # After 1 second
            self.generate_light_particles()

        self.update_light_particles()

        if self.frame_counter >= BEAM_PHASE_DURATION:
            self.switch_phase("show")

    def generate_light_particles(self):
        """Creates expanding particles from the center, limiting the amount and reducing lifespan."""
        center_x, center_y = runtime_globals.SCREEN_WIDTH // 2, runtime_globals.SCREEN_HEIGHT // 2

        # 🔹 Reduce particle count by half and enforce a max limit
        particle_count = min((2 + self.frame_counter // 30) // 2, 5)  # 🔥 Reduced & capped at 5

        if len(self.light_particles) >= 50:  # 🔥 Enforce global limit of 50 particles
            return

        for _ in range(particle_count):
            angle = random.uniform(0, 2 * math.pi)
            speed = random.uniform(2, 5)
            scale = random.uniform(0.1, 0.2)

            self.light_particles.append({
                "x": center_x,
                "y": center_y,
                "dx": math.cos(angle) * speed,
                "dy": math.sin(angle) * speed,
                "scale": scale,
                "lifetime": 30  # 🔥 Reduced lifespan for faster cleanup
            })

    def generate_colored_particles(self):
        """Creates particles with randomized colors from behind the Digimon, limiting count and lifespan."""
        center_x, center_y = runtime_globals.SCREEN_WIDTH // 2, runtime_globals.SCREEN_HEIGHT // 2

        # 🔹 Reduce particle count by half and enforce a max limit
        particle_count = min((2 + self.frame_counter // 30) // 2, 5)  # 🔥 Reduced & capped at 5

        if len(self.light_particles) >= 50:  # 🔥 Enforce global limit of 50 particles
            return

        for _ in range(particle_count):
            angle = random.uniform(0, 2 * math.pi)
            speed = random.uniform(2, 5)
            color = random.choice(self.color_list)

            self.light_particles.append({
                "x": center_x,
                "y": center_y,
                "dx": math.cos(angle) * speed,
                "dy": math.sin(angle) * speed,
                "color": color,
                "scale": 0.5,
                "lifetime": 30  # 🔥 Reduced lifespan for faster cleanup
            })

    def extract_sprite_colors(self, sprite):
        """Extracts non-transparent and non-black colors from the evolved sprite."""
        colors = set()
        
        for x in range(sprite.get_width()):
            for y in range(sprite.get_height()):
                color = sprite.get_at((x, y))
                if color.a > 0 and (color.r > 10 or color.g > 10 or color.b > 10):  # Ignore transparent & black pixels
                    colors.add((color.r, color.g, color.b))

        return list(colors) if colors else [(255, 255, 255)]

    def update_phase_show(self):
        if self.evolutions[0].stage == 3:
            self.generate_falling_particles()
            self.update_falling_particles()
        elif self.evolutions[0].stage == 4:
            self.generate_dna_particles()
            self.update_dna_particles()

        if self.frame_counter > 90:
            self.switch_phase("explode")
            self.generate_particles()

    def update_phase_explode(self):
        self.particles = [p for p in self.particles if p[5] > 0]
        for p in self.particles:
            p[0] += p[2] * PARTICLE_SPEED
            p[1] += p[3] * PARTICLE_SPEED
            p[5] -= 1

        if self.frame_counter > 30:
            self.switch_phase("pre_reveal_flash")
            self.light_particles = []

    def update_phase_pre_reveal_flash(self):
        if self.frame_counter == 1:
            self.prepare_scrolling_texts(self.evolutions[0].to_name)
        if self.frame_counter > 10:
            if self.evolutions[0].stage >= 4:
                self.generate_colored_particles()
            self.switch_phase("reveal")

    def update_phase_reveal(self):
        if self.evolutions[0].stage >= 3:
            self.generate_colored_particles()
            self.update_light_particles()

        if self.frame_counter >= REVEAL_TIME:
            self.switch_phase("done")

    def update_phase_done(self):
        if self.evolutions[0].stage >= 3:
            self.generate_colored_particles()
            self.update_light_particles()

        if self.frame_counter > 60:
            # Evolution / new-pet coin rewards are granted by GamePet.evolve_to
            # and register_digidex_entry when the pet actually transforms, so
            # this animation scene no longer claims them (avoids double rewards).
            runtime_globals.game_sound.stop_all()
            change_scene("game")

    # =================== Drawing Logic ===================
    def draw(self, surface):
        surface.fill((0, 0, 0))
        if self._empty:
            return

        self.draw_fog(surface)

        phase_draw_methods = {
            "flash": self.draw_phase_flash,
            "symbol": self.draw_phase_symbol,
            "show": self.draw_phase_show,
            "mega_intro": self.draw_phase_mega_intro,
            "mega_shine": self.draw_phase_mega_shine,
            "mega_energy": self.draw_phase_mega_energy,
            "mega_orb": self.draw_phase_mega_orb,
            "mega_transformation": self.draw_phase_mega_transformation,
            "rain": self.draw_phase_rain,
            "beams": self.draw_phase_beams,
            "explode": self.draw_phase_explode,
            "pre_reveal_flash": self.draw_phase_pre_reveal_flash,
            "reveal": self.draw_phase_reveal,
            "done": self.draw_phase_done
        }

        phase_draw_methods.get(self.phase, lambda s: None)(surface)

    def draw_phase_mega_transformation(self, surface):
        """Draws scaled sprite, green overlay, and explosion particles during transformation."""
        sprite_x, sprite_y = (runtime_globals.SCREEN_WIDTH - int(100 * runtime_globals.UI_SCALE)) // 2, (runtime_globals.SCREEN_HEIGHT - int(100 * runtime_globals.UI_SCALE)) // 2
        
        # 🔹 Draw base scaled-up sprite
        surface.blit(self.evolutions[0].from_sprite, (sprite_x, sprite_y))

        # 🔹 Draw green pixels replacing exploded sectors
        for pixel in self.active_green_pixels:
            green_surface = pygame.Surface((int(5 * runtime_globals.UI_SCALE), int(5 * runtime_globals.UI_SCALE)), pygame.SRCALPHA)
            green_surface.fill((0, 255, 0))
            green_surface.set_alpha(pixel["alpha"])
            surface.blit(green_surface, (pixel["x"] + sprite_x, pixel["y"] + sprite_y))

        for p in self.particles:
            if p[5] > 0:
                pygame.draw.circle(surface, p[4], (int(p[0]), int(p[1])), int(1 * runtime_globals.UI_SCALE))

    def draw_phase_mega_intro(self, surface):
        surface.blit(self.evolutions[0].from_sprite, (runtime_globals.evolution_pet.x, runtime_globals.evolution_pet.y))

    def draw_phase_mega_shine(self, surface):
        surface.blit(self.evo_background, (0, 0))

        self.draw_falling_particles(surface)

        surface.blit(self.evolutions[0].from_sprite, (runtime_globals.evolution_pet.x, runtime_globals.evolution_pet.y))

        # 🔥 Apply the flash effect
        if self.flash_alpha > 0:
            flash_surface = pygame.Surface((runtime_globals.SCREEN_WIDTH, runtime_globals.SCREEN_HEIGHT))
            flash_surface.fill((255, 255, 255))
            flash_surface.set_alpha(self.flash_alpha)
            surface.blit(flash_surface, (0, 0))
    
    def draw_phase_mega_energy(self, surface):
        self.draw_phase_mega_shine(surface)

        for pixel in self.active_energy_pixels:
            energy_surface = pygame.Surface((3, 3))
            energy_surface.fill((0, 255, 0))
            energy_surface.set_alpha(pixel["alpha"])
            surface.blit(energy_surface, (pixel["x"] + runtime_globals.evolution_pet.x, pixel["y"] + runtime_globals.evolution_pet.y))

    def draw_phase_mega_orb(self, surface):
        """Displays the animated Orb centered on screen."""
        frame_width, frame_height = 240, 240
        orb_x, orb_y = (0,0)

        # 🔥 Extract current frame from the sprite sheet
        source_rect = pygame.Rect((self.frame_counter % 63) * frame_width, 0, frame_width, frame_height)

        # 🔹 Draw the Orb animation centered
        surface.blit(self.orb_sprite, (orb_x, orb_y), source_rect)

    def draw_phase_rain(self, surface):

        # 🔹 Render rain
        for drop in self.rain_drops:
            pygame.draw.rect(surface, (181, 255, 255), (drop["x"], drop["y"], 2, 8))

        # 🔥 Render spiraling particles
        self.draw_colored_particles(surface)

        if self.explosion_flash:
            surface.blit(self.explosion_flash, (0, 0))

    def draw_fog(self, surface):
        """Draws fog background seamlessly, preventing visible position jumps."""
        if self.evolutions[0].stage != 4:
            return

        x = int(self.fog_x)
        y = int(self.fog_y)

        surface.blit(self.fog_image, (x, y))

        # 🔹 Wrap around correctly
        surface.blit(self.fog_image, (x - 512, y))  # Left wrap
        surface.blit(self.fog_image, (x + 512, y))  # Right wrap
        surface.blit(self.fog_image, (x, y - 512))  # Top wrap
        surface.blit(self.fog_image, (x, y + 512))  # Bottom wrap
        surface.blit(self.fog_image, (x - 512, y - 512))  # Top-left corner wrap
        surface.blit(self.fog_image, (x + 512, y - 512))  # Top-right corner wrap
        surface.blit(self.fog_image, (x - 512, y + 512))  # Bottom-left corner wrap
        surface.blit(self.fog_image, (x + 512, y + 512))  # Bottom-right corner wrap
    
    def draw_phase_flash(self, surface):
        """Handles the flash effect at the start of evolution."""
        if self.evolutions[0].stage == 3:
            self.draw_symbol_animation(surface)

        if self.evolutions[0].stage <= 2:
            self.draw_scroll_texts(surface)
            for idx, evo in enumerate(self.evolutions):
                rect = self.get_side_rect(idx, BASE_SPRITE_SIZE, BASE_SPRITE_SIZE)
                surface.blit(pygame.transform.scale(evo.from_sprite, (BASE_SPRITE_SIZE, BASE_SPRITE_SIZE)), rect.topleft)
        surface.blit(self.surface_flash, (0, 0))

    def draw_phase_symbol(self, surface):
        """Renders Evo1 symbol rotation effect."""
        self.draw_symbol_animation(surface)

    def draw_symbol_animation(self, surface):
        """Renders Evo1 symbol rotation effect."""
        center_x, center_y = runtime_globals.SCREEN_WIDTH // 2, runtime_globals.SCREEN_HEIGHT // 2

        # 🔹 First, resize the image before rotating
        size = max(1, int(self.evo_text_size))
        scaled_text = pygame.transform.scale(self.evo_text_image, (size, size))

        # 🔹 Then rotate the scaled image
        rotated_text = pygame.transform.rotate(scaled_text, self.evo_text_angle)

        # 🔹 Recalculate center correctly after transformation
        text_rect = rotated_text.get_rect(center=(center_x, center_y))
        surface.blit(rotated_text, text_rect.topleft)

    def draw_phase_show(self, surface):
        """Displays the pre-evolution sprites before transformation."""
        self.draw_scroll_texts(surface)
        for idx, evo in enumerate(self.evolutions):
            rect = self.get_side_rect(idx, BASE_SPRITE_SIZE, BASE_SPRITE_SIZE)
            surface.blit(pygame.transform.scale(evo.from_sprite, (BASE_SPRITE_SIZE, BASE_SPRITE_SIZE)), rect.topleft)
            label = self.font.render(evo.from_name, True, FONT_COLOR_DEFAULT)
            surface.blit(label, (rect.x + (BASE_SPRITE_SIZE - label.get_width()) // 2, rect.y + 80))

        if self.evolutions[0].stage == 4:
            self.draw_dna_particles(surface)
        elif self.evolutions[0].stage == 3:
            self.draw_falling_particles(surface)

    def draw_falling_particles(self, surface):
        """Draws falling particles using self.particles."""
        for particle in self.particles:
            surface.blit(self.light_particle2, (int(particle[0]) - 2, int(particle[1]) - 2))

    def draw_dna_particles(self, surface):
        """Draws DNA sprites falling and truncating upon collision."""
        for particle in self.dna_particles:
            # 🔥 Apply truncation effect
            clipped_sprite = pygame.Surface((37, 47 - particle["disappeared_rows"]), pygame.SRCALPHA)
            clipped_sprite.blit(self.dna_sprite, (0, 0))

            surface.blit(clipped_sprite, (particle["x"], particle["y"]))

    def draw_phase_explode(self, surface):
        """Draws particle explosion effects during evolution."""
        surface.blit(self.light_source, ((runtime_globals.SCREEN_WIDTH - BASE_SPRITE_SIZE) // 2, (runtime_globals.SCREEN_HEIGHT - BASE_SPRITE_SIZE) // 2))
        for p in self.particles:
            if p[5] > 0:
                pygame.draw.circle(surface, p[4], (int(p[0]), int(p[1])), 1)

    def draw_phase_pre_reveal_flash(self, surface):
        """Shows a full white flash before revealing the new evolution."""
        surface.fill((255, 255, 255))

    def draw_phase_reveal(self, surface):
        """Handles the scaling effect when transitioning into the new evolved form."""
        self.draw_background(surface)
        self.draw_scroll_texts(surface)
        self.draw_colored_particles(surface)

        for idx, evo in enumerate(self.evolutions):
            rect = self.get_side_rect(idx, BASE_SPRITE_SIZE, BASE_SPRITE_SIZE)
            progress = min(self.frame_counter / REVEAL_TIME, 1.0)
            scale = max(1.0, 4.0 * math.exp(-4 * progress))  # Shrinks rapidly over time
            size = int(BASE_SPRITE_SIZE * scale)
            sprite = pygame.transform.scale(evo.to_sprite, (size, size))
            offset = (size - BASE_SPRITE_SIZE) // 2
            surface.blit(sprite, (rect.x - offset, rect.y - offset))

            label = self.font.render(evo.to_name, True, FONT_COLOR_DEFAULT)
            surface.blit(label, (rect.x + (BASE_SPRITE_SIZE - label.get_width()) // 2, rect.y + 80))

    def draw_colored_particles(self, surface):
        """Draws colored particles from behind the Digimon."""
        for particle in self.light_particles:
            tinted_sprite = self.light_particle1.copy()
            tinted_sprite.fill(particle["color"], special_flags=pygame.BLEND_MULT)

            size = 20  # Keep it consistent without scaling
            scaled_light = pygame.transform.scale(tinted_sprite, (size, size))
            light_rect = scaled_light.get_rect(center=(int(particle["x"]), int(particle["y"])))

            surface.blit(scaled_light, light_rect.topleft)


    def draw_phase_done(self, surface):
        """Final state: Draws the fully evolved Digimon after the animation completes."""
        self.draw_background(surface)
        self.draw_scroll_texts(surface)
        self.draw_colored_particles(surface)

        for idx, evo in enumerate(self.evolutions):
            rect = self.get_side_rect(idx, BASE_SPRITE_SIZE, BASE_SPRITE_SIZE)
            surface.blit(pygame.transform.scale(evo.to_sprite, (BASE_SPRITE_SIZE, BASE_SPRITE_SIZE)), rect.topleft)
            label = self.font.render(evo.to_name, True, FONT_COLOR_DEFAULT)
            surface.blit(label, (rect.x + (BASE_SPRITE_SIZE - label.get_width()) // 2, rect.y + 80))

    def draw_phase_beams(self, surface):
        self.draw_symbol_animation(surface)
        center_x, center_y = runtime_globals.SCREEN_WIDTH // 2, runtime_globals.SCREEN_HEIGHT // 2
        pygame.draw.rect(surface, CENTER_COLOR, (center_x - 5, center_y - 5, 10, 10))  # Cover center spot

        for beam in self.beams:
            rotated = pygame.transform.rotate(self.beam_sprite, -beam["angle"])
            rect = rotated.get_rect(center=(center_x, center_y))
            surface.blit(rotated, rect.topleft)

        self.draw_light_particles(surface)

    def draw_light_particles(self, surface):
        """Draws expanding light particles with proper size control."""
        for particle in self.light_particles:
            size = max(5, int(20 * particle["scale"])) 
            scaled_light = pygame.transform.scale(self.light_source, (size, size))
            light_rect = scaled_light.get_rect(center=(int(particle["x"]), int(particle["y"])))
            surface.blit(scaled_light, light_rect.topleft)

    def draw_scroll_texts(self, surface):
        for text, font, x, y, _ in self.scroll_texts:
            surface.blit(font.render(text, True, (255, 255, 255)), (x, y))

    def draw_background(self, surface):
        rotated = pygame.transform.rotate(self.bg_base, self.bg_angle)
        rect = rotated.get_rect(center=(runtime_globals.SCREEN_WIDTH // 2, runtime_globals.SCREEN_HEIGHT // 2))
        surface.blit(rotated, rect.topleft)

    # =================== Helpers ===================
    def prepare_beams(self):
        center_x = runtime_globals.SCREEN_WIDTH // 2
        center_y = runtime_globals.SCREEN_HEIGHT // 2
        for i in range(NUM_BEAMS):
            self.beams.append({"angle": (360 / NUM_BEAMS) * i, "rotation_speed": random.choice([-2, 2]), "pos": (center_x, center_y)})

    def load_and_tint_image(self, path):
        img = image_load(path).convert_alpha()
        return self.tint_surface_manual(img)
    
    def create_flash_surface(self):
        flash = pygame.Surface((runtime_globals.SCREEN_WIDTH, runtime_globals.SCREEN_HEIGHT))
        flash.fill((255, 255, 255))  # White flash effect
        flash.set_alpha(255)  # Full opacity initially
        return flash

    def add_scrolling_word(self, text, font):
        """Adds individual scrolling text entries."""
        y = random.randint(0, runtime_globals.SCREEN_HEIGHT - 50)
        x = random.randint(0, runtime_globals.SCREEN_WIDTH + 50)
        speed = random.uniform(0.5, 2.5) * random.choice([-1, 1])
        self.scroll_texts.append([text, font, x, y, speed])

    def prepare_scrolling_texts(self, word):
        """Generates scrolling text effects for evolution."""
        self.scroll_texts.clear()
        
        # Ensure at least 2 instances of the main name
        for _ in range(2):
            self.add_scrolling_word(word, get_font(20))
        
        # Fill the rest with additional names or 'Evolution'
        for _ in range(12):
            text = random.choice([word, "Evolution"])
            self.add_scrolling_word(text, random.choice(self.fonts))

    def add_scrolling_word(self, text, font):
        """Adds individual scrolling text entries."""
        y = random.randint(0, runtime_globals.SCREEN_HEIGHT - 50)
        x = random.randint(0, runtime_globals.SCREEN_WIDTH + 50)
        speed = random.uniform(0.5, 2.5) * random.choice([-1, 1])
        self.scroll_texts.append([text, font, x, y, speed])

    def tint_surface_manual(self, surface):
        """Applies a random tint to the given surface while preserving transparency."""
        tinted = surface.copy()
        px_array = pygame.PixelArray(tinted)

        # Generate random tint variations
        r_mod, g_mod, b_mod = random.randint(-50, 10), random.randint(-50, 10), random.randint(-50, 10)

        # Iterate over pixels to adjust their colors
        for x in range(tinted.get_width()):
            for y in range(tinted.get_height()):
                color = tinted.get_at((x, y))
                if color.a > 0:  # Preserve transparency
                    color.r = max(0, min(255, color.r + r_mod))
                    color.g = max(0, min(255, color.g + g_mod))
                    color.b = max(0, min(255, color.b + b_mod))
                    px_array[x, y] = color

        del px_array
        return tinted

    def get_side_rect(self, idx, w, h):
        """Determines placement for Digimon sprites during evolution animation."""
        if len(self.evolutions) == 1:
            return pygame.Rect((runtime_globals.SCREEN_WIDTH - w) // 2, (runtime_globals.SCREEN_HEIGHT - h) // 2, w, h)
        x = 32 if idx == 0 else runtime_globals.SCREEN_WIDTH - w - 32
        y = (runtime_globals.SCREEN_HEIGHT - h) // 2
        return pygame.Rect(x, y, w, h)

    def generate_particles(self):
        """Creates explosion particle effects for evolution animation."""
        self.particles.clear()
        cx, cy = runtime_globals.SCREEN_WIDTH // 2, runtime_globals.SCREEN_HEIGHT // 2

        for idx, evo in enumerate(self.evolutions):
            sprite = pygame.transform.scale(evo.from_sprite, (72, 72))
            region = self.get_side_rect(idx, 72, 72)
            sprite.set_colorkey((0, 0, 0))

            for x in range(sprite.get_width()):
                for y in range(sprite.get_height()):
                    color = sprite.get_at((x, y))
                    if color.a > 0:
                        px, py = region.x + x, region.y + y
                        angle = math.atan2(py - cy, px - cx) + random.uniform(-0.15, 0.15)
                        speed = random.uniform(1.0, 4.0)
                        dx, dy = math.cos(angle) * speed, math.sin(angle) * speed
                        life = PARTICLE_LIFE + random.randint(-35, 35)
                        self.particles.append([px, py, dx, dy, color, life])