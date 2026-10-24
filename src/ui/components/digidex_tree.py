import random
import pygame

from ui.components.component import UIComponent
from core import runtime_globals
from utils.pygame_utils import blit_with_shadow, get_font
from utils.sprite_utils import load_pet_sprites
from utils.module_utils import get_module
import core.constants as constants
from ui.ui_constants import BASE_RESOLUTION

class DigidexTree(UIComponent):
    """Component that renders a tree view of evolutions and manages visible-sprite loading.

    This class preserves the original tree layout and drawing logic but encapsulates it
    so the scene can simply delegate to it. The tree exposes a simple API:
    - set_pets(pets)
    - set_root(root_entry)
    - update(), draw(surface), handle_event(action)
    - on_back callback (set by scene) to return to list view
    """
    def __init__(self, x, y, width, height, unknown_sprite, sprite_size=None):
        super().__init__(x, y, width, height)
        self.font = get_font(int(16 * runtime_globals.UI_SCALE))
        self.unknown_sprite = unknown_sprite
        self.sprite_size = sprite_size or int(48 * runtime_globals.UI_SCALE)
        self.pets = []
        self.tree_root = None
        self.tree_data = {}
        self.tree_node_pos = {}
        self.tree_node_grid = {}
        self.tree_color_map = {}
        self.tree_cursor = (0, 0)
        self.on_back = None
        self.focusable = True
        
        # Cached tree surface
        self.tree_surface = None
        self.tree_surface_offset = (0, 0)  # Where (0,0) of tree is on the surface
        self.needs_tree_rebuild = True

    def set_pets(self, pets):
        self.pets = pets

    def set_root(self, root_entry, tree_data, selected_pet=None):
        self.tree_root = root_entry
        self.tree_data = tree_data
        self.selected_pet_name = selected_pet.name if selected_pet else root_entry.name
        # build layout positions
        self._build_tree_layout()
        self.tree_cursor = (0, 0)
        self.needs_tree_rebuild = True

    def _build_tree_layout(self):
        self.tree_node_grid = {}
        self.tree_node_pos = {}

        # Find all root nodes (stage 0 / eggs) by finding nodes with no parents
        all_nodes = set(self.tree_data.keys())
        for children in self.tree_data.values():
            all_nodes.update(children)
        
        # Find nodes that are not children of any other node (roots)
        children_set = set()
        for children in self.tree_data.values():
            children_set.update(children)
        
        root_nodes = [node for node in all_nodes if node not in children_set]
        
        # If no roots found (circular reference or incomplete data), use tree_root
        if not root_nodes:
            root_nodes = [self.tree_root.name]
        
        runtime_globals.game_console.log(f"[DigidexTree] Found {len(root_nodes)} root nodes: {root_nodes}")
        
        # Build tree from all roots using BFS
        stages = {}
        queue = [(root, 0) for root in root_nodes]
        visited = set()

        while queue:
            current, depth = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            stages.setdefault(depth, []).append(current)
            for child in self.tree_data.get(current, []):
                queue.append((child, depth + 1))

        # Position nodes in grid
        max_line_length = max(len(names) for names in stages.values()) if stages else 1
        for y_idx, names in stages.items():
            line_width = (len(names) - 1) * 1
            total_width = (max_line_length - 1)
            center_adjust = (total_width - line_width) // 2

            for x_idx, name in enumerate(names):
                px = x_idx + center_adjust
                py = y_idx
                self.tree_node_grid[(px, py)] = name
                self.tree_node_pos[name] = (px, py)
        
        runtime_globals.game_console.log(f"[DigidexTree] Built tree with {len(self.tree_node_pos)} nodes across {len(stages)} stages")

    def _load_all_tree_sprites(self):
        """Load all sprites for the current tree (called once when tree is built)"""
        visible_names = set(self.tree_node_pos.keys() if self.tree_root else [])

        for pet in self.pets:
            if pet.name in visible_names and not pet.sprite and pet.known:
                try:
                    module = get_module(pet.module)
                    sprites_dict = load_pet_sprites(
                        pet.name,
                        module.folder_path,
                        module.name_format,
                        size=(self.sprite_size, self.sprite_size),
                        primary_sprite_format=getattr(module, 'primary_sprite_format', 'Color'),
                        secondary_sprite_format=getattr(module, 'secondary_sprite_format', 'HD'),
                    )
                    # Frame keys are ints (see load_sprites_from_directory)
                    frame0 = sprites_dict.get(0) or sprites_dict.get("0")
                    pet.sprite = frame0 if frame0 is not None else self.unknown_sprite
                except Exception as e:
                    runtime_globals.game_console.log(f"[DigidexTree] Failed to load sprite {pet.name}: {e}")
                    pet.sprite = self.unknown_sprite

    def update(self):
        super().update()
        if self.tree_root and self.needs_tree_rebuild:
            self._load_all_tree_sprites()
            self._build_tree_surface()
            # Center on selected pet
            if hasattr(self, 'selected_pet_name') and self.selected_pet_name in self.tree_node_pos:
                self.tree_cursor = self.tree_node_pos[self.selected_pet_name]
                runtime_globals.game_console.log(f"[DigidexTree] Centered on {self.selected_pet_name} at grid pos {self.tree_cursor}")
                runtime_globals.game_console.log(f"[DigidexTree] Tree node positions: {self.tree_node_pos}")
            else:
                runtime_globals.game_console.log(f"[DigidexTree] Could not center on {getattr(self, 'selected_pet_name', 'UNKNOWN')}, defaulting to (0,0)")
                runtime_globals.game_console.log(f"[DigidexTree] Available positions: {list(self.tree_node_pos.keys())}")
            self.needs_tree_rebuild = False

    def handle_event(self, event):
        # Debug logging
        #runtime_globals.game_console.log(f"[DigidexTree] handle_event: {event}, visible={self.visible}")
        
        # Handle tuple-based events
        if not isinstance(event, tuple) or len(event) != 2:
            return False
            
        event_type, event_data = event
            
        # navigation and back handling
        if event_type == 'B' or event_type == 'BACK':
            runtime_globals.game_console.log("[DigidexTree] B/BACK pressed")
            if self.on_back:
                self.on_back()
            return True

        dx, dy = 0, 0
        if event_type == "LEFT":
            dx = -1
            #runtime_globals.game_console.log(\"[DigidexTree] LEFT pressed\")
        elif event_type == "RIGHT":
            dx = 1
            #runtime_globals.game_console.log(\"[DigidexTree] RIGHT pressed\")
        elif event_type == "UP":
            dy = -1
            #runtime_globals.game_console.log(\"[DigidexTree] UP pressed\")
        elif event_type == "DOWN":
            dy = 1
            #runtime_globals.game_console.log(\"[DigidexTree] DOWN pressed\")

        if dx != 0 or dy != 0:
            old_cursor = self.tree_cursor
            self.tree_cursor = (self.tree_cursor[0] + dx, self.tree_cursor[1] + dy)
            self.needs_redraw = True
            runtime_globals.game_console.log(f"[DigidexTree] cursor moved from {old_cursor} to {self.tree_cursor}")
            return True

        return False
    
    def handle_drag(self, event):
        """Handle drag events for panning the tree view"""
        if not isinstance(event, tuple) or len(event) != 2:
            return False
        
        event_type, event_data = event
        
        if not (runtime_globals.INPUT_MODE in [runtime_globals.MOUSE_MODE, runtime_globals.TOUCH_MODE]):
            return False
        
        if event_type == "DRAG_START":
            mouse_pos = event_data.get("pos")
            if not mouse_pos:
                return False
                
            relative_x = mouse_pos[0] - self.rect.x
            relative_y = mouse_pos[1] - self.rect.y
            
            # Check if mouse is within component bounds
            if not (0 <= relative_x < self.rect.width and 0 <= relative_y < self.rect.height):
                return False
            
            # Start drag - store last position for incremental updates
            self._drag_last_pos = mouse_pos
            self._is_dragging = True
            runtime_globals.game_console.log("[DigidexTree] Drag started")
            return True
        
        elif event_type == "DRAG_MOTION" and hasattr(self, '_is_dragging') and self._is_dragging:
            current_pos = event_data.get("pos")
            if not current_pos:
                return False
            
            # Calculate incremental movement from last position
            dx = current_pos[0] - self._drag_last_pos[0]
            dy = current_pos[1] - self._drag_last_pos[1]
            
            # Convert pixel movement to tree cursor movement
            # Drag sensitivity: pixels per grid unit
            horizontal_spacing = int(80 * runtime_globals.UI_SCALE)
            vertical_spacing = int(100 * runtime_globals.UI_SCALE)
            
            # Calculate cursor delta (drag right = pan left, so negate)
            cursor_dx = -dx / horizontal_spacing
            cursor_dy = -dy / vertical_spacing
            
            # Apply incremental movement
            self.tree_cursor = (
                self.tree_cursor[0] + cursor_dx,
                self.tree_cursor[1] + cursor_dy
            )
            self.needs_redraw = True
            
            # Update last position for next motion event
            self._drag_last_pos = current_pos
            return True
        
        elif event_type == "DRAG_END":
            if hasattr(self, '_is_dragging') and self._is_dragging:
                self._is_dragging = False
                runtime_globals.game_console.log("[DigidexTree] Drag ended")
                return True
        
        return False

    def _build_tree_surface(self):
        """Build the complete tree surface once, then we just pan it"""
        if not self.tree_root or not self.tree_data:
            return

        # Build stages
        stages = {}
        queue = [(self.tree_root.name, 0)]
        visited = set()

        while queue:
            current, depth = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            stages.setdefault(depth, []).append(current)
            for child in self.tree_data.get(current, []):
                queue.append((child, depth + 1))

        sprite_size = self.sprite_size
        vertical_spacing = int(100 * runtime_globals.UI_SCALE)
        horizontal_spacing = int(80 * runtime_globals.UI_SCALE)

        max_line_length = max(len(names) for names in stages.values())
        
        # Find actual min/max grid coordinates from tree_node_grid
        if not self.tree_node_grid:
            return
        
        all_x = [pos[0] for pos in self.tree_node_grid.keys()]
        all_y = [pos[1] for pos in self.tree_node_grid.keys()]
        min_x, max_x = min(all_x), max(all_x)
        min_y, max_y = min(all_y), max(all_y)
        
        # Calculate tree bounds with proper margins
        margin = int(50 * runtime_globals.UI_SCALE)
        tree_width = (max_x - min_x + 1) * horizontal_spacing + sprite_size + margin * 2
        tree_height = (max_y - min_y + 1) * vertical_spacing + sprite_size + margin * 2
        
        # Create surface large enough for entire tree
        self.tree_surface = pygame.Surface((tree_width, tree_height), pygame.SRCALPHA)
        
        # Offset to position the tree (accounting for min_x/min_y which may be negative or non-zero)
        offset_x = margin - min_x * horizontal_spacing
        offset_y = margin - min_y * vertical_spacing
        self.tree_surface_offset = (offset_x, offset_y)
        
        runtime_globals.game_console.log(f"[DigidexTree] Grid bounds: x({min_x},{max_x}) y({min_y},{max_y})")
        runtime_globals.game_console.log(f"[DigidexTree] Tree surface offset: {self.tree_surface_offset}")

        # 1. Draw colored lines between evolution nodes
        for (x_idx, y_idx), name in self.tree_node_grid.items():
            children = self.tree_data.get(name, [])

            px1 = x_idx * horizontal_spacing + offset_x + sprite_size // 2
            py1 = y_idx * vertical_spacing + offset_y + sprite_size // 2

            if y_idx < 3:
                color = pygame.Color(0, 128, 255)
            elif (x_idx, y_idx) in self.tree_color_map:
                color = self.tree_color_map[(x_idx, y_idx)]
            else:
                color = (random.randint(80, 255), random.randint(80, 255), random.randint(80, 255))
                self.tree_color_map[x_idx, y_idx] = color

            for child_name in children:
                child_pos = next((k for k, v in self.tree_node_grid.items() if v == child_name), None)
                if not child_pos:
                    continue

                child_x, child_y = child_pos

                px2 = child_x * horizontal_spacing + offset_x + sprite_size // 2
                py2 = child_y * vertical_spacing + offset_y + sprite_size // 2

                pygame.draw.line(self.tree_surface, color, (px1, py1), (px2, py2), int(3 * runtime_globals.UI_SCALE))

        # 2. Draw pets and names
        attr_colors = {
            "Da": (66, 165, 245),
            "Va": (102, 187, 106),
            "Vi": (237, 83, 80),
            "": (171, 71, 188),
            "???": (0, 0, 0)
        }

        for name, (px, py) in self.tree_node_pos.items():
            pet = next((p for p in self.pets if p.name == name and p.module == self.tree_root.module and p.version == self.tree_root.version), None)
            sprite = pet.sprite if pet and pet.sprite else self.unknown_sprite
            color = attr_colors.get(pet.attribute if pet else "???", (150, 150, 150))
            
            if py < 3:
                color2 = pygame.Color(0, 128, 255)
            elif (px, py) in self.tree_color_map:
                color2 = self.tree_color_map[(px, py)]
            else:
                color2 = (random.randint(80, 255), random.randint(80, 255), random.randint(80, 255))
                self.tree_color_map[px, py] = color2

            screen_x = px * horizontal_spacing + offset_x
            screen_y = py * vertical_spacing + offset_y

            # Background box
            pygame.draw.rect(
                self.tree_surface, color, 
                (screen_x - int(4 * runtime_globals.UI_SCALE), screen_y - int(4 * runtime_globals.UI_SCALE), 
                 sprite_size + int(8 * runtime_globals.UI_SCALE), sprite_size + int(8 * runtime_globals.UI_SCALE))
            )
            self.tree_surface.blit(sprite, (screen_x, screen_y))
            sprite_rect = pygame.Rect(
                screen_x - int(4 * runtime_globals.UI_SCALE), 
                screen_y - int(4 * runtime_globals.UI_SCALE), 
                sprite_size + int(8 * runtime_globals.UI_SCALE), 
                sprite_size + int(8 * runtime_globals.UI_SCALE)
            )
            pygame.draw.rect(self.tree_surface, color2, sprite_rect, int(2 * runtime_globals.UI_SCALE))

            if pet and pet.known:
                label = self.font.render(pet.name, True, color)
                blit_with_shadow(self.tree_surface, label, (screen_x, screen_y + sprite_size + int(2 * runtime_globals.UI_SCALE)))

        runtime_globals.game_console.log(f"[DigidexTree] Built tree surface: {tree_width}x{tree_height}")

    def render(self):
        # Create component surface
        surface = pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
        
        if not self.tree_surface:
            return surface

        # Calculate where to blit from the tree surface based on cursor position
        horizontal_spacing = int(80 * runtime_globals.UI_SCALE)
        vertical_spacing = int(100 * runtime_globals.UI_SCALE)
        
        # Calculate the position on tree_surface that should be at center of viewport
        center_on_tree_x = self.tree_surface_offset[0] + self.tree_cursor[0] * horizontal_spacing
        center_on_tree_y = self.tree_surface_offset[1] + self.tree_cursor[1] * vertical_spacing
        
        # Calculate source rect (what part of tree_surface to show)
        # We want center_on_tree to be at the center of our viewport
        src_x = int(center_on_tree_x - self.rect.width // 2)
        src_y = int(center_on_tree_y - self.rect.height // 2)
        
        # Don't clamp - allow negative and beyond bounds for smooth panning
        # The blit will handle out-of-bounds gracefully
        
        # Calculate destination position (may be negative if src is out of bounds)
        dest_x = 0
        dest_y = 0
        
        # Adjust if source goes negative
        if src_x < 0:
            dest_x = -src_x
            src_x = 0
        
        if src_y < 0:
            dest_y = -src_y
            src_y = 0
        
        # Calculate actual blit dimensions
        actual_width = min(self.rect.width - dest_x, self.tree_surface.get_width() - src_x)
        actual_height = min(self.rect.height - dest_y, self.tree_surface.get_height() - src_y)
        
        # Only blit if there's something to show
        if actual_width > 0 and actual_height > 0:
            src_rect = pygame.Rect(src_x, src_y, actual_width, actual_height)
            surface.blit(self.tree_surface, (dest_x, dest_y), src_rect)
        
        return surface
