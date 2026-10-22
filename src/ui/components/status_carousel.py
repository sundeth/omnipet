"""
Status Carousel Component - A horizontally scrolling carousel of status boxes
Each box shows an icon and value, with auto-scrolling and manual navigation
"""
import pygame
from ui.components.component import UIComponent
from core import runtime_globals
from utils.pygame_utils import blit_with_cache
from ui.ui_constants import PURPLE_LIGHT, PURPLE, PURPLE_DARK, PURPLE_DARK_LINE
import core.constants as constants
from utils.asset_utils import image_load


#: Silhouettes already made, by (module, form, sprite preferences), None for
#: a form without art: the Status scene asks on every pet it shows, and a
#: form's sprites come out of its zip, which is slow on the Pi Zero 2W.
_SILHOUETTES = {}


def evolution_silhouette(pet):
    """The form *pet* would evolve into now (`GamePet.preview_evolution`,
    a route's % chance counted as certain), as its IDLE1 frame blacked out,
    at the art's own size. None when no route matches or it has no sprite.
    Each form's silhouette is made once (`_SILHOUETTES`)."""
    try:
        target = pet.preview_evolution()
    except Exception as exc:
        runtime_globals.game_console.log(f"[StatusCarousel] evolution preview failed: {exc}")
        return None
    if not target:
        return None
    from core import game_globals
    cfg = getattr(game_globals, "configuration", None)
    key = (pet.module, target.get("name"),
           getattr(cfg, "sprite_resolution_preference", 0),
           getattr(cfg, "enable_old_sprites", False))
    if key in _SILHOUETTES:
        return _SILHOUETTES[key]
    from utils.module_utils import get_module
    from utils.sprite_utils import load_pet_sprites
    from models.animation import PetFrame
    module = get_module(pet.module)
    frames = load_pet_sprites(
        target["name"], module.folder_path, getattr(module, "name_format", "$_dmc"),
        primary_sprite_format=getattr(module, "primary_sprite_format", "Color"),
        secondary_sprite_format=getattr(module, "secondary_sprite_format", "HD"))
    frame = frames.get(PetFrame.IDLE1.value)
    shadow = None
    if frame is not None:
        shadow = frame.copy()
        # Every pixel black, its transparency kept.
        shadow.fill((0, 0, 0, 255), special_flags=pygame.BLEND_RGBA_MIN)
    _SILHOUETTES[key] = shadow
    return shadow


class StatusCarousel(UIComponent):
    def __init__(self, x, y, width, height, pet_data=None):
        super().__init__(x, y, width, height)
        self.pet_data = pet_data or {}
        self.boxes = []  # List of status boxes to display
        self.focusable = True
        self.focused_box_index = -1  # Which box is currently focused
        self.scroll_offset = 0  # Current scroll position
        self.auto_scroll_enabled = True
        self.auto_scroll_speed = 20  # pixels per second
        self.last_scroll_time = 0
        
        # Mark as dynamic since carousel auto-scrolls and animates
        self.is_dynamic = True
        
        # Box dimensions and spacing - these will be scaled in setup_scaling()
        self.base_box_width = 60
        self.base_box_spacing = 8
        self.base_margin_x = 4
        self.base_padding_x = 0  # Base horizontal padding
        self.base_padding_y = 0  # Base vertical padding
        
        # Actual scaled dimensions (set in setup_scaling)
        self.box_width = self.base_box_width
        self.box_height = height - 4  # Leave small margin
        self.box_spacing = self.base_box_spacing
        self.margin_x = self.base_margin_x
        self.padding_x = self.base_padding_x  # Scaled padding
        self.padding_y = self.base_padding_y
        
        # Drag support
        self.dragging = False
        self.drag_start_x = 0
        self.drag_start_offset = 0
        
        # Animation
        self.target_scroll_offset = 0
        self.scroll_animation_speed = 300  # pixels per second
        
        # Status icon cache
        self.status_icons = {}
        
        # Pre-rendered surface optimization
        self.content_surface = None
        self.surface_needs_rebuild = True
        self.last_scroll_floor = -1  # Track which "page" we're on for surface rebuilding
        
        # Setup scaling when manager is available
        self.setup_scaling()
        
        # Build initial boxes
        self.rebuild_boxes()
        
    def setup_scaling(self):
        """Setup component scaling based on UI manager scale"""
        if self.manager:
            scale = self.manager.ui_scale
        else:
            scale = 1.0
            
        # Scale box dimensions
        self.box_width = int(self.base_box_width * scale)
        self.box_spacing = int(self.base_box_spacing * scale)
        self.margin_x = int(self.base_margin_x * scale)
        self.padding_x = int(self.base_padding_x * scale)
        self.padding_y = int(self.base_padding_y * scale)
        
        # Calculate box height properly accounting for UI scaling
        # The component rect height is already scaled by UI manager, so we need to work backwards
        base_component_height = self.rect.height // scale if scale > 0 else self.rect.height
        base_margin_y = 4  # Base margin in unscaled pixels
        base_box_height = base_component_height - base_margin_y
        
        # Now scale the box height properly
        self.box_height = int(base_box_height * scale)
        
        # Ensure box height is always positive and reasonable
        min_box_height = int(20 * scale)  # Minimum 20 pixels at base scale
        self.box_height = max(min_box_height, self.box_height)
        
        # Clear icon cache when scale changes to force re-scaling
        self.status_icons.clear()
        self.surface_needs_rebuild = True
        
    def on_manager_set(self):
        """Called when the UI manager is set - update scaling"""
        self.setup_scaling()
        
    def set_pet_data(self, pet_data):
        """Update the pet data and rebuild boxes"""
        self.pet_data = pet_data
        self.rebuild_boxes()
        self.surface_needs_rebuild = True
        
    def rebuild_boxes(self):
        """Rebuild the status boxes based on current pet data"""
        self.boxes = []
        
        if not self.pet_data:
            return
        
        # Get module info for visible stats and configuration
        module = self.pet_data.get('module')
        visible_stats = self.pet_data.get('visible_stats', [])
        use_condition_hearts = self.pet_data.get('use_condition_hearts', False)
        condition_heart_meter_visible = self.pet_data.get('condition_heart_meter_visible', False)
        
        # Define available status types - only the ones you specified
        # These are the only status types that can appear in the carousel
        status_types = [
            ("trophies", "Trophies", "trophies", "Trophies"),
            ("vital_values", "Vital Values", "vital_values", "Vital Values"),
            ("mistakes", "Mistakes", "mistakes", "Mistakes/Condition Hearts"),
            ("sleep_disturbances", "Sleep Disturbances", "sleep_disturbances", "Sleep Disturbances"),
            ("overfeed", "Overfeed", "overfeed", "Overfeed"),
            ("injuries", "Injuries", "injuries", "Injuries"),
            ("sicknesses", "Sicknesses", "sicknesses", "Sicknesses"),
            ("virus", "Virus", "virus", "Virus"),
            ("evolution_timer", "Evolution Timer", "evolution_timer", "Evolution Timer"),
            ("next_evolution", "Next Evolution", "next_evolution", "Next Evolution"),
            ("sleeps", "Sleeps", "sleeps", "Sleeps"),
            ("wakes", "Wakes", "wakes", "Wakes"),
            ("poop_time", "Poop Time", "poop_time", "Poop Time"),
            ("feed_time", "Feed Time", "feed_time", "Feed Time"),
        ]
        
        # Create boxes for available stats based on visible_stats
        for stat_id, display_name, data_key, visible_stat_name in status_types:
            # Check if this stat should be visible
            if visible_stat_name not in visible_stats:
                continue
                
            # Next Evolution draws the coming form's silhouette, or "?".
            if stat_id == "next_evolution":
                self.boxes.append({
                    'id': stat_id,
                    'name': display_name,
                    'value': '',
                    'sprite': self.pet_data.get(data_key),
                })
                continue

            # Special handling for Trophies and Vital Values - only show if Level is also visible
            if stat_id in ["trophies", "vital_values"] and "Level" not in visible_stats:
                continue
                
            # Special handling for Mistakes/Condition Hearts
            if stat_id == "mistakes":
                # Skip condition hearts if dedicated condition heart meter is visible
                if use_condition_hearts and condition_heart_meter_visible:
                    continue
                    
                if use_condition_hearts:
                    # Use condition hearts instead of mistakes
                    if "Mistakes/Condition Hearts" in visible_stats:
                        raw_value = self.pet_data.get('condition_hearts', 0)
                        value = self.format_status_value("Heart", raw_value, self.pet_data)
                        icon_name = "Heart"  # Will use Heart Full icon
                        self.boxes.append({
                            'id': 'condition_hearts',
                            'name': icon_name,
                            'value': value,
                            'icon': None  # Will be loaded on demand
                        })
                    continue
                else:
                    # Use mistakes with Mistakes icon
                    if "Mistakes/Condition Hearts" in visible_stats:
                        raw_value = self.pet_data.get('mistakes', 0)
                        value = self.format_status_value("Mistakes", raw_value, self.pet_data)
                        icon_name = "Mistakes"
                        self.boxes.append({
                            'id': stat_id,
                            'name': icon_name,
                            'value': value,
                            'icon': None  # Will be loaded on demand
                        })
                    continue
            
            try:
                # Get raw value and format it
                raw_value = self.pet_data.get(data_key, 0)
                value = self.format_status_value(display_name, raw_value, self.pet_data)
                
                self.boxes.append({
                    'id': stat_id,
                    'name': display_name,
                    'value': value,
                    'icon': None  # Will be loaded on demand
                })
            except (KeyError, AttributeError, TypeError):
                # Skip stats that aren't available
                continue
        
        # Reset focus if we have boxes or if no boxes exist
        if self.boxes:
            if self.focused_box_index >= len(self.boxes):
                self.focused_box_index = 0
        else:
            self.focused_box_index = -1
        
        # Mark surface for rebuild when boxes change
        self.surface_needs_rebuild = True
        self.needs_redraw = True
        
        # Force recreation of content surface
        self.content_surface = None
    
    def format_status_value(self, status_name, value, pet_data):
        """Format status value with appropriate display"""
        if status_name == "Heart" and pet_data.get("use_condition_hearts", False):
            # Display as hearts - use heart symbols
            hearts = int(value) if value is not None else 0
            max_hearts = 4  # Typical max hearts
            filled = "♥" * hearts
            empty = "♡" * (max_hearts - hearts)
            return filled + empty
        elif status_name == "Evolution Timer":
            # Special handling for evolution timer - calculate remaining time
            return self.format_evolution_timer(pet_data)
        elif status_name in ["Sleeps", "Wakes", "Poop Time", "Feed Time"]:
            # These are already formatted as strings or None, return directly
            return str(value) if value is not None else ""
        elif status_name == "Weight":
            # Add weight unit
            return f"{value}g" if value is not None else "0g"
        elif status_name == "Age":
            # Add age unit
            return f"{value}d" if value is not None else "0d"
        elif status_name in ["Hunger", "Strength", "Effort"]:
            # Format as x/4
            return f"{value}/4" if value is not None else "0/4"
        elif status_name == "DP":
            # Format as x/14
            return f"{value}/14" if value is not None else "0/14"
        elif isinstance(value, float):
            # Round float values
            return str(int(value)) if value is not None else "0"
        else:
            # Default formatting
            return str(value) if value is not None else "0"
    
    def format_evolution_timer(self, pet_data):
        """Calculate and format remaining evolution time"""
        # Get evolution timer (in minutes) and current pet timer (in frames)
        evolution_time_minutes = pet_data.get('evolution_timer')  # This would be pet.time in minutes
        current_timer_frames = pet_data.get('timer', 0)  # This would be pet.timer in frames
        evolve_flag = pet_data.get('evolve', False)  # This would be pet.evolve
        
        if evolution_time_minutes is None or evolution_time_minutes < 0 or not evolve_flag:
            return ""
        
        # Convert evolution time from minutes to seconds
        evolution_time_seconds = evolution_time_minutes * 60
        
        # Convert current timer from frames to seconds
        current_time_seconds = current_timer_frames // constants.FRAME_RATE
        
        # Calculate remaining time
        remaining_seconds = evolution_time_seconds - current_time_seconds
        
        if remaining_seconds <= 0:
            return "00:00"
        
        # Format as HH:MM
        hours = remaining_seconds // 3600
        minutes = (remaining_seconds % 3600) // 60
        return f"{hours:02d}:{minutes:02d}"
            
    def load_status_icon(self, status_name):
        """Load status icon with scaling support"""
        if status_name in self.status_icons:
            return self.status_icons[status_name]
            
        if not self.manager:
            return None
            
        # NEW SYSTEM: Always load _1 sprites and scale them
        icon_mapping = {
            "Trophies": "Trophies",
            "Vital Values": "Vital Values", 
            "Mistakes": "Mistakes",
            "Heart": "Heart_Full",  # For condition hearts
            "Sleep Disturbances": "Sleep Disturbance",  # Note: singular in filename
            "Overfeed": "Overfeed",
            "Injuries": "Injuries",
            "Sicknesses": "Sicknesses",
            "Virus": "Virus",
            "Evolution Timer": "Evolution Timer",
            "Sleeps": "Sleeps",
            "Wakes": "Wakes",
            "Poop Time": "Poop Time",
            "Feed Time": "Feed Time",
        }
        
        icon_filename = icon_mapping.get(status_name, status_name)
        
        # Load _1 sprite and scale it
        icon_path = f"assets/ui/Status_{icon_filename}_1.png"
        try:
            icon = image_load(icon_path).convert_alpha()
            
            # Apply integer scaling if needed
            if self.manager.ui_scale > 1:
                original_size = icon.get_size()
                new_size = (original_size[0] * self.manager.ui_scale, original_size[1] * self.manager.ui_scale)
                icon = pygame.transform.scale(icon, new_size)
        except (pygame.error, FileNotFoundError) as e:
            runtime_globals.game_console.log(f"[StatusCarousel] Could not load icon: {icon_path} - {e}")
            return None
        
        # Scale down the icon to fit with the larger font
        # Calculate target icon size based on box dimensions and font space needed
        font_size = self.manager.get_text_font_size()
        icon_margin = int(4 * self.manager.ui_scale)
        text_margin = int(2 * self.manager.ui_scale)
        
        # Reserve space for text: font height + margins
        text_space_needed = font_size + (2 * text_margin)
        
        # Available space for icon: box height - text space - top margin
        available_icon_height = self.box_height - text_space_needed
        
        # Also consider box width for aspect ratio
        max_icon_width = self.box_width
        
        # Scale icon to fit within available space while maintaining aspect ratio
        if icon:
            original_size = icon.get_size()
            if original_size[0] > 0 and original_size[1] > 0:
                # Ensure we have positive available space for icon
                if available_icon_height <= 0 or max_icon_width <= 0:
                    # If no space available, use a minimal icon size
                    available_icon_height = max(1, available_icon_height)
                    max_icon_width = max(1, max_icon_width)
                
                # Calculate scale factor to fit within both width and height constraints
                width_scale = max_icon_width / original_size[0]
                height_scale = available_icon_height / original_size[1]
                scale_factor = min(width_scale, height_scale, 1.0)  # Don't scale up
                
                if scale_factor < 1.0 and scale_factor > 0:
                    new_width = max(1, int(original_size[0] * scale_factor))
                    new_height = max(1, int(original_size[1] * scale_factor))
                    # Nearest-neighbor: keeps the pixel-art icons sharp
                    # (smoothscale blurred their edges).
                    icon = pygame.transform.scale(icon, (new_width, new_height))
        
        # Cache the final scaled icon
        self.status_icons[status_name] = icon
        return icon
                
    def build_content_surface(self):
        """Build the pre-rendered content surface with all boxes"""
        if not self.boxes:
            self.content_surface = None
            return
            
        # Check if all boxes fit in the available space
        total_content_width = self.get_total_content_width()
        available_width = self.rect.width - (2 * self.padding_x)
        all_boxes_fit = total_content_width <= available_width
        
        # Get font for text using centralized method
        font = self.get_font("text")
        
        if all_boxes_fit:
            # When all boxes fit, spread them evenly and don't duplicate
            surface_width = available_width
            surface_height = self.box_height
            
            # Create the content surface
            # Reuse content_surface if size matches; else recreate
            if getattr(self, 'content_surface', None) is None or self.content_surface.get_size() != (surface_width, surface_height):
                self.content_surface = pygame.Surface((surface_width, surface_height), pygame.SRCALPHA)
            
            # Calculate spacing for even distribution
            if len(self.boxes) == 1:
                # Single box: center it
                start_x = (available_width - self.box_width) // 2
                box_spacing_override = 0
            else:
                # Multiple boxes: distribute evenly across available width
                # Each box gets an equal portion of the available space
                space_per_box = available_width // len(self.boxes)
                box_spacing_override = 0  # Not used in this mode
                start_x = 0
            
            # Render boxes with even spacing
            for i, box in enumerate(self.boxes):
                if len(self.boxes) == 1:
                    box_x = start_x
                else:
                    # Center each box in its allocated space
                    space_per_box = available_width // len(self.boxes)
                    box_center_in_space = space_per_box // 2
                    box_x = (i * space_per_box) + box_center_in_space - (self.box_width // 2)
                box_y = 0
                
                # Create box surface
                box_surface = self.create_box_surface(box, i, font)
                
                # Blit box to content surface (internal rendering, no tracking needed)
                self.content_surface.blit(box_surface, (box_x, box_y))
        else:
            # When boxes don't fit, use scrolling mode with duplication
            total_width = self.get_total_content_width()
            # Add proper spacing between the two surface cycles to match box spacing
            cycle_gap = self.box_spacing
            extra_width = total_width + cycle_gap  # Space for second cycle plus gap
            surface_width = total_width + extra_width
            surface_height = self.box_height
            
            # Create the content surface
            if getattr(self, 'content_surface', None) is None or self.content_surface.get_size() != (surface_width, surface_height):
                self.content_surface = pygame.Surface((surface_width, surface_height), pygame.SRCALPHA)
            
            # Render all boxes twice (original + wrapped) for seamless scrolling
            for cycle in range(2):
                cycle_offset = cycle * (total_width + cycle_gap)
                
                for i, box in enumerate(self.boxes):
                    box_x = cycle_offset + (i * (self.box_width + self.box_spacing))
                    box_y = 0
                    
                    # Skip if this box would be outside our surface
                    if box_x + self.box_width > surface_width:
                        break
                        
                    # Create box surface with current focus state
                    # The box_index remains the same for both cycles as it's the logical box position
                    box_surface = self.create_box_surface(box, i, font)
                    
                    # Blit box to content surface (internal rendering, no tracking needed)
                    self.content_surface.blit(box_surface, (box_x, box_y))
        
        self.surface_needs_rebuild = False
    
    def create_box_surface(self, box, box_index, font):
        """Create a single box surface with icon and text"""
        box_surface = pygame.Surface((self.box_width, self.box_height), pygame.SRCALPHA)
        
        # Draw box background
        # Show focus for keyboard navigation OR mouse hover
        is_focused = (box_index == self.focused_box_index and 
                     (self.focused or self.focused_box_index >= 0))
        border_radius = int(2 * (self.manager.ui_scale if self.manager else 1.0))
        border_width = int(2 * (self.manager.ui_scale if self.manager else 1.0))
        if is_focused:
            pygame.draw.rect(box_surface, PURPLE, (0, 0, self.box_width, self.box_height), border_radius=border_radius)
            pygame.draw.rect(box_surface, PURPLE_LIGHT, (0, 0, self.box_width, self.box_height), width=border_width, border_radius=border_radius)
        else:
            pygame.draw.rect(box_surface, PURPLE_DARK, (0, 0, self.box_width, self.box_height), border_radius=border_radius)
            pygame.draw.rect(box_surface, PURPLE_DARK_LINE, (0, 0, self.box_width, self.box_height), width=1, border_radius=border_radius)
        
        if box['id'] == 'next_evolution':
            self._draw_next_evolution(box_surface, box, is_focused)
            return box_surface

        # Load and draw icon
        icon = self.load_status_icon(box['name'])
        if icon:
            icon_x = (self.box_width - icon.get_width()) // 2
            icon_margin = int(4 * (self.manager.ui_scale if self.manager else 1.0))
            icon_y = icon_margin
            blit_with_cache(box_surface, icon, (icon_x, icon_y))
            text_y = icon_y + icon.get_height() + int(2 * (self.manager.ui_scale if self.manager else 1.0))
        else:
            text_y = int(8 * (self.manager.ui_scale if self.manager else 1.0))
            
        # Draw value text
        text_surface = font.render(box['value'], True, PURPLE_LIGHT if is_focused else PURPLE)
        text_x = (self.box_width - text_surface.get_width()) // 2
        text_margin = int(2 * (self.manager.ui_scale if self.manager else 1.0))
        text_y = max(text_y, self.box_height - text_surface.get_height() - text_margin)
        blit_with_cache(box_surface, text_surface, (text_x, text_y))
        
        return box_surface
                
    def _draw_next_evolution(self, box_surface, box, is_focused):
        """The coming form's silhouette at a whole multiple (or exact
        fraction) of its own size, filling the box; "?" when there is none."""
        scale = self.manager.ui_scale if self.manager else 1
        margin = int(2 * scale)
        sprite = box.get('sprite')
        if sprite is not None:
            from utils.sprite_utils import scale_sprite_pixel_perfect
            if box.get('_scaled') is None:
                box['_scaled'] = scale_sprite_pixel_perfect(
                    sprite, (self.box_width - 2 * margin, self.box_height - 2 * margin))
            scaled = box['_scaled']
            blit_with_cache(box_surface, scaled, ((self.box_width - scaled.get_width()) // 2,
                                                  (self.box_height - scaled.get_height()) // 2))
            return
        # A big "?": the title font at 1.5x, about a silhouette's height.
        title_size = self.manager.get_title_font_size() if self.manager else 24
        font = self.get_font("title", custom_size=title_size * 3 // 2)
        text = font.render("?", True, PURPLE_LIGHT if is_focused else PURPLE)
        blit_with_cache(box_surface, text, ((self.box_width - text.get_width()) // 2,
                                            (self.box_height - text.get_height()) // 2))

    def get_visible_box_count(self):
        """Calculate how many boxes can fit in the visible area"""
        available_width = self.rect.width - 2 * self.margin_x
        return available_width // (self.box_width + self.box_spacing)
        
    def get_total_content_width(self):
        """Calculate total width of all boxes"""
        if not self.boxes:
            return 0
        return len(self.boxes) * (self.box_width + self.box_spacing) - self.box_spacing
        
    def update(self):
        """Update carousel animations and auto-scroll"""
        current_time = pygame.time.get_ticks()
        dt = (current_time - self.last_scroll_time) / 1000.0 if self.last_scroll_time > 0 else 0
        self.last_scroll_time = current_time
        
        if dt > 0.1:  # Cap delta time to prevent large jumps
            dt = 0.1
        
        # Handle mouse hover for individual box focus
        self.handle_mouse_hover()
        
        # Check if all boxes can fit in the visible area
        total_content_width = self.get_total_content_width()
        available_width = self.rect.width - (2 * self.padding_x)
        all_boxes_fit = total_content_width <= available_width
        
        # Auto-scroll when not focused or dragging and no mouse hover and not all boxes fit
        if (self.auto_scroll_enabled and not self.focused and not self.dragging and 
            self.boxes and not all_boxes_fit):
            old_scroll_offset = self.scroll_offset
            self.scroll_offset += self.auto_scroll_speed * dt
            
            # Loop scroll offset - account for the gap between cycles
            cycle_gap = self.box_spacing
            cycle_length = total_content_width + cycle_gap
            if cycle_length > 0 and self.scroll_offset >= cycle_length:
                self.scroll_offset = 0
                self.target_scroll_offset = 0
            
            # Keep target in sync with auto-scroll
            self.target_scroll_offset = self.scroll_offset
            
            # Check if we need to rebuild surface for focus changes
            current_scroll_floor = int(self.scroll_offset // self.rect.width)
            if current_scroll_floor != self.last_scroll_floor:
                self.surface_needs_rebuild = True
                self.last_scroll_floor = current_scroll_floor
            
            # Mark for redraw when auto-scrolling
            self.needs_redraw = True
        
        # If all boxes fit, ensure scroll offset is 0
        elif all_boxes_fit:
            if self.scroll_offset != 0 or self.target_scroll_offset != 0:
                self.scroll_offset = 0
                self.target_scroll_offset = 0
                self.needs_redraw = True
                
        # Animate scroll to target position (only when not auto-scrolling)
        elif abs(self.scroll_offset - self.target_scroll_offset) > 1:
            diff = self.target_scroll_offset - self.scroll_offset
            move_amount = min(abs(diff), self.scroll_animation_speed * dt)
            if diff > 0:
                self.scroll_offset += move_amount
            else:
                self.scroll_offset -= move_amount
            
            # Check if we need to rebuild surface for focus changes
            current_scroll_floor = int(self.scroll_offset // self.rect.width)
            if current_scroll_floor != self.last_scroll_floor:
                self.surface_needs_rebuild = True
                self.last_scroll_floor = current_scroll_floor
            
            self.needs_redraw = True
            
        # Reset animation speed after manual scroll animation completes
        if hasattr(self, '_manual_scroll_time') and hasattr(self, '_original_scroll_speed'):
            # If scroll animation is complete or enough time has passed, reset speed
            if (abs(self.scroll_offset - self.target_scroll_offset) <= 1 or 
                current_time - self._manual_scroll_time > 1000):  # 1 second timeout
                self.scroll_animation_speed = self._original_scroll_speed
                delattr(self, '_manual_scroll_time')
                delattr(self, '_original_scroll_speed')
                
    def handle_mouse_hover(self):
        """Handle mouse hover for individual box selection"""
        if not (runtime_globals.INPUT_MODE in [runtime_globals.MOUSE_MODE, runtime_globals.TOUCH_MODE]):
            return
        
        # Disable mouse hover during drag to prevent focus changes
        if hasattr(self, '_is_dragging') and self._is_dragging:
            return
        
        # Also check if InputManager is currently dragging
        if hasattr(runtime_globals.game_input, 'is_dragging') and runtime_globals.game_input.is_dragging():
            return

        mouse_pos = runtime_globals.game_input.get_mouse_position()

        # Convert to component-relative coordinates
        relative_x = mouse_pos[0] - self.rect.x
        relative_y = mouse_pos[1] - self.rect.y

        # Check if mouse is within component bounds
        if not (0 <= relative_x < self.rect.width and 0 <= relative_y < self.rect.height):
            # Mouse is outside component - resume auto-scroll if not manually focused and content overflows
            if not self.focused:
                total_content_width = self.get_total_content_width()
                available_width = self.rect.width - (2 * self.padding_x)
                if total_content_width > available_width:
                    self.auto_scroll_enabled = True
            return

        # Mouse is over the component - ALWAYS stop auto-scroll regardless of overflow
        # This prevents any automatic scrolling when user is interacting with mouse
        self.auto_scroll_enabled = False

        # Check if mouse is within the padded content area
        if (relative_x < self.padding_x or relative_x >= self.rect.width - self.padding_x or
            relative_y < self.padding_y or relative_y >= self.rect.height - self.padding_y):
            # Mouse is over component but outside content area - clear hover focus
            if not self.focused and self.focused_box_index >= 0:
                old_focused = self.focused_box_index
                self.focused_box_index = -1
                
                # Rebuild surface if focus changed
                if old_focused != self.focused_box_index:
                    self.surface_needs_rebuild = True
                
                self.needs_redraw = True
            return

        # Calculate mouse position within content area
        content_x = relative_x - self.padding_x
        
        # Check if all boxes fit (different positioning logic)
        total_content_width = self.get_total_content_width()
        available_width = self.rect.width - (2 * self.padding_x)
        all_boxes_fit = total_content_width <= available_width
        
        if all_boxes_fit:
            # For evenly distributed boxes - only focus visible boxes
            for i, box in enumerate(self.boxes):
                if len(self.boxes) == 1:
                    # Single box: centered
                    box_start = (available_width - self.box_width) // 2
                    box_end = box_start + self.box_width
                else:
                    # Multiple boxes: each centered in its allocated space
                    space_per_box = available_width // len(self.boxes)
                    box_center_in_space = space_per_box // 2
                    box_start = (i * space_per_box) + box_center_in_space - (self.box_width // 2)
                    box_end = box_start + self.box_width
                
                if box_start <= content_x < box_end:
                    # Mouse is over this box
                    if self.focused_box_index != i:
                        old_focused = self.focused_box_index
                        self.focused_box_index = i
                        
                        # Rebuild surface if focus changed
                        if old_focused != self.focused_box_index:
                            self.surface_needs_rebuild = True
                        
                        self.needs_redraw = True
                    return
        else:
            # For scrolling boxes - check both surface cycles for mouse interaction
            # Do not change scroll position, only focus what's already visible
            cycle_gap = self.box_spacing
            cycle_length = total_content_width + cycle_gap
            
            # Check both cycles for visible boxes
            for cycle in range(2):
                cycle_offset = cycle * cycle_length
                
                for i, box in enumerate(self.boxes):
                    box_x = cycle_offset + (i * (self.box_width + self.box_spacing)) - self.scroll_offset
                    
                    # Check if this box is currently visible on screen (more generous bounds)
                    if (box_x + self.box_width > 0 and 
                        box_x < available_width):
                        # Box is visible, check if mouse is over it
                        box_start = box_x
                        box_end = box_x + self.box_width
                        
                        if box_start <= content_x < box_end:
                            # Mouse is over this visible box
                            if self.focused_box_index != i:
                                old_focused = self.focused_box_index
                                self.focused_box_index = i
                                
                                # Rebuild surface if focus changed
                                if old_focused != self.focused_box_index:
                                    self.surface_needs_rebuild = True
                                
                                self.needs_redraw = True
                            return
        
        # Mouse is over component but not over any visible box - clear box focus if not manually focused
        if not self.focused and self.focused_box_index >= 0:
            old_focused = self.focused_box_index
            self.focused_box_index = -1
            
            # Rebuild surface if focus changed
            if old_focused != self.focused_box_index:
                self.surface_needs_rebuild = True
                
            self.needs_redraw = True
                
    def handle_event(self, event):
        """Handle input events"""
        if not isinstance(event, tuple) or len(event) != 2:
            return False
            
        event_type, event_data = event
        
        if not self.focused or not self.boxes:
            return False
            
        if event_type == "LEFT":
            self.move_focus(-1)
            return True
        elif event_type == "RIGHT":
            self.move_focus(1)
            return True
        elif event_type == "A":
            # Show tooltip for focused box
            if 0 <= self.focused_box_index < len(self.boxes):
                box = self.boxes[self.focused_box_index]
                if self.manager and hasattr(self.manager, 'show_tooltip'):
                    self.manager.show_tooltip(f"{box['name']}: {box['value']}")
            return True
        elif event_type == "LCLICK":
            # Handle left clicks for box interaction
            if event_data and "pos" in event_data:
                return self.handle_mouse_click(event_data["pos"], "LCLICK")
        elif event_type == "DRAG_START":
            # Start drag interaction
            if event_data and "pos" in event_data:
                mouse_x = event_data["pos"][0]
                # Only start drag if outside component bounds (for scrolling)
                if not self.rect.collidepoint(event_data["pos"]):
                    self.start_drag(mouse_x)
                    return True
        elif event_type == "DRAG_MOTION":
            # Continue drag
            if self.dragging and event_data and "pos" in event_data:
                self.update_drag(event_data["pos"][0])
                return True
        elif event_type == "DRAG_END":
            # End drag
            if self.dragging:
                self.end_drag()
                return True
        elif event_type == "SCROLL":
            # Handle scroll wheel
            if event_data and "amount" in event_data:
                return self.handle_scroll(event_data["amount"])
            
        return False
    
    def handle_mouse_click(self, mouse_pos, action):
        """Handle mouse clicks for UI manager compatibility"""
        if not self.boxes:
            return False
            
        # Convert to local coordinates
        local_x = mouse_pos[0] - self.rect.x
        local_y = mouse_pos[1] - self.rect.y
        
        # Check if click is within padded area
        if (local_x < self.padding_x or local_x >= self.rect.width - self.padding_x or
            local_y < self.padding_y or local_y >= self.rect.height - self.padding_y):
            return False
        
        # Calculate click position within content area
        content_x = local_x - self.padding_x
        
        # Check if all boxes fit (different positioning logic)
        total_content_width = self.get_total_content_width()
        available_width = self.rect.width - (2 * self.padding_x)
        all_boxes_fit = total_content_width <= available_width
        
        if all_boxes_fit:
            # For evenly distributed boxes
            for i, box in enumerate(self.boxes):
                if len(self.boxes) == 1:
                    # Single box: centered
                    box_start = (available_width - self.box_width) // 2
                    box_end = box_start + self.box_width
                else:
                    # Multiple boxes: each centered in its allocated space
                    space_per_box = available_width // len(self.boxes)
                    box_center_in_space = space_per_box // 2
                    box_start = (i * space_per_box) + box_center_in_space - (self.box_width // 2)
                    box_end = box_start + self.box_width
                
                if box_start <= content_x < box_end:
                    old_focused = self.focused_box_index
                    self.focused_box_index = i
                    
                    # Rebuild surface if focus changed
                    if old_focused != self.focused_box_index:
                        self.surface_needs_rebuild = True
                    
                    # Show tooltip
                    if self.manager and hasattr(self.manager, 'show_tooltip'):
                        self.manager.show_tooltip(f"{box['name']}: {box['value']}")
                    
                    self.needs_redraw = True
                    return True
        else:
            # For scrolling boxes - check both surface cycles for mouse clicks
            # Do NOT scroll to show boxes, only interact with what's visible
            cycle_gap = self.box_spacing
            cycle_length = total_content_width + cycle_gap
            
            # Check both cycles for visible boxes
            for cycle in range(2):
                cycle_offset = cycle * cycle_length
                
                for i, box in enumerate(self.boxes):
                    box_x = cycle_offset + (i * (self.box_width + self.box_spacing)) - self.scroll_offset
                    
                    # Check if this box is currently visible on screen (more generous bounds)
                    if (box_x + self.box_width > 0 and 
                        box_x < available_width):
                        # Box is visible, check if click is on it
                        box_start = box_x
                        box_end = box_x + self.box_width
                        
                        if box_start <= content_x < box_end:
                            old_focused = self.focused_box_index
                            self.focused_box_index = i
                            
                            # DO NOT scroll to show box - just focus it
                            # self.scroll_to_show_box(i)  # REMOVED
                            
                            # Rebuild surface if focus changed
                            if old_focused != self.focused_box_index:
                                self.surface_needs_rebuild = True
                            
                            # Show tooltip
                            if self.manager and hasattr(self.manager, 'show_tooltip'):
                                self.manager.show_tooltip(f"{box['name']}: {box['value']}")
                            
                            self.needs_redraw = True
                            return True
        
        return False
    
    def handle_scroll(self, action):
        """Handle scroll wheel for UI manager compatibility"""
        if not self.boxes:
            return False
            
        # Get scroll direction from action
        direction = 0
        if hasattr(action, 'y'):
            direction = action.y
        elif isinstance(action, (int, float)):
            direction = action
        elif isinstance(action, str):
            # Handle string-based scroll actions
            if action in ["SCROLL_UP", "UP"]:
                direction = 1
            elif action in ["SCROLL_DOWN", "DOWN"]:
                direction = -1
            else:
                # Try to parse as number
                try:
                    direction = float(action)
                except (ValueError, TypeError):
                    return False
        else:
            return False
        
        # Scroll by one box width
        scroll_amount = self.box_width + self.box_spacing
        
        if direction > 0:  # Scroll up/left
            self.target_scroll_offset -= scroll_amount
        else:  # Scroll down/right
            self.target_scroll_offset += scroll_amount
            
        # Clamp to valid range
        max_scroll = max(0, len(self.boxes) * (self.box_width + self.box_spacing) - self.rect.width + (2 * self.padding_x))
        self.target_scroll_offset = max(0, min(self.target_scroll_offset, max_scroll))
        
        return True
    
    def handle_drag(self, event):
        """Handle drag for UI manager compatibility"""
        if not isinstance(event, tuple) or len(event) != 2:
            return False
        
        event_type, event_data = event
        
        if not (runtime_globals.INPUT_MODE in [runtime_globals.MOUSE_MODE, runtime_globals.TOUCH_MODE]):
            return False
            
        if not self.boxes:
            return False
        
        mouse_pos = event_data.get("pos")
        if not mouse_pos:
            return False
        
        # Check if mouse is over the component - if so, disable dragging
        if self.rect.collidepoint(mouse_pos):
            # Mouse is over component - disable drag, only allow wheel scroll
            return False
        
        # Handle drag start (only when mouse is outside component)
        if event_type == "DRAG_START":
            self.start_drag(mouse_pos[0])
            return True
        
        # Handle drag continue
        elif event_type == "DRAG_MOTION" and self.dragging:
            self.update_drag(mouse_pos[0])
            return True
        
        # Handle drag end
        elif event_type == "DRAG_END" and self.dragging:
            self.end_drag()
            return True
            
        return False
        
    def start_drag(self, mouse_x):
        """Start dragging the carousel"""
        self.dragging = True
        self.auto_scroll_enabled = False
        self.drag_start_x = mouse_x
        self.drag_start_offset = self.scroll_offset
        
    def update_drag(self, mouse_x):
        """Update drag position"""
        if self.dragging:
            drag_distance = self.drag_start_x - mouse_x  # Inverted for natural scroll
            self.target_scroll_offset = self.drag_start_offset + drag_distance
            self.scroll_offset = self.target_scroll_offset
            
    def end_drag(self):
        """End dragging"""
        self.dragging = False
        
    def move_focus(self, direction):
        """Move focus to next/previous box"""
        if not self.boxes:
            return
            
        # Only disable auto-scroll when all boxes fit
        total_content_width = self.get_total_content_width()
        available_width = self.rect.width - (2 * self.padding_x)
        all_boxes_fit = total_content_width <= available_width
        
        if all_boxes_fit:
            self.auto_scroll_enabled = False
            
        old_index = self.focused_box_index
        
        if self.focused_box_index < 0:
            # First navigation - start from appropriate end based on direction
            if direction > 0:  # RIGHT - start from first box
                self.focused_box_index = 0
            else:  # LEFT - start from last box
                self.focused_box_index = len(self.boxes) - 1
        else:
            self.focused_box_index = (self.focused_box_index + direction) % len(self.boxes)
        
        # Rebuild surface if focus changed
        if old_index != self.focused_box_index:
            self.surface_needs_rebuild = True
            self.needs_redraw = True
            
        # Scroll to ensure focused box is visible (only for overflow case)
        if not all_boxes_fit:
            self.scroll_to_show_box(self.focused_box_index)
        
    def scroll_to_show_box(self, box_index):
        """Smoothly scroll to center the specified box in the visible area"""
        if box_index < 0 or box_index >= len(self.boxes):
            return
            
        # Check if all boxes fit (no scrolling needed)
        total_content_width = self.get_total_content_width()
        available_width = self.rect.width - (2 * self.padding_x)
        all_boxes_fit = total_content_width <= available_width
        
        if all_boxes_fit:
            # No scrolling needed when all boxes fit
            return
            
        # Calculate the position of the target box in the infinite scroll system
        box_x = box_index * (self.box_width + self.box_spacing)
        visible_width = available_width
        
        # Center the box in the visible area
        # Calculate the scroll offset that would center this box
        box_center = box_x + (self.box_width // 2)
        visible_center = visible_width // 2
        target_scroll = box_center - visible_center
        
        # In infinite scroll, we need to ensure smooth scrolling without jumping
        cycle_gap = self.box_spacing
        cycle_length = total_content_width + cycle_gap
        
        # Normalize the target scroll to avoid large jumps in infinite scroll
        if cycle_length > 0:
            # Find the scroll position closest to current that shows the centered box
            # Try different cycle positions to find the smoothest transition
            best_scroll = target_scroll
            best_distance = abs(target_scroll - self.scroll_offset)
            
            for cycle_offset in [-2, -1, 0, 1, 2]:  # Check more cycles for better smoothness
                candidate_scroll = target_scroll + (cycle_offset * cycle_length)
                distance = abs(candidate_scroll - self.scroll_offset)
                
                if distance < best_distance:
                    best_distance = distance
                    best_scroll = candidate_scroll
            
            # Use animated scrolling instead of instant jump
            self.target_scroll_offset = best_scroll
            
            # Enable smooth animation for manual navigation
            # Increase animation speed for more responsive feel
            old_speed = self.scroll_animation_speed
            self.scroll_animation_speed = 500  # Faster for manual navigation
            
            # Reset animation speed after a delay (will be handled in update)
            self._manual_scroll_time = pygame.time.get_ticks()
            self._original_scroll_speed = old_speed
        else:
            self.target_scroll_offset = target_scroll
            
    def get_first_visible_box_index(self):
        """Get the index of the first visible box in the current scroll position"""
        if not self.boxes:
            return -1
            
        # Check if all boxes fit (different positioning logic)
        total_content_width = self.get_total_content_width()
        available_width = self.rect.width - (2 * self.padding_x)
        all_boxes_fit = total_content_width <= available_width
        
        if all_boxes_fit:
            # All boxes are visible, return first box
            return 0
        
        # For scrolling boxes, find the first box that's visible across both cycles
        cycle_gap = self.box_spacing
        cycle_length = total_content_width + cycle_gap
        
        # Check both cycles for the first visible box
        for cycle in range(2):
            cycle_offset = cycle * cycle_length
            
            for i in range(len(self.boxes)):
                box_x = cycle_offset + (i * (self.box_width + self.box_spacing)) - self.scroll_offset
                
                # Check if this box is at least partially visible (more generous bounds)
                if (box_x + self.box_width > 0 and 
                    box_x < available_width):
                    return i
                
        # Fallback to first box
        return 0
            
    def on_focus_gained(self):
        """Called when component gains focus"""
        self.auto_scroll_enabled = False
        old_focused = self.focused_box_index
        
        # When gaining keyboard focus, select the first visible box for proper highlighting
        # This ensures there's always a focused element when using keyboard navigation
        if self.boxes and self.focused_box_index < 0:
            self.focused_box_index = self.get_first_visible_box_index()
            
            # DO NOT scroll when gaining focus - just focus the currently visible box
            # The user should not experience unwanted scrolling when component gains focus
        
        # Rebuild surface if focus state changed
        if old_focused != self.focused_box_index:
            self.surface_needs_rebuild = True
            self.needs_redraw = True
            
    def on_focus_lost(self):
        """Called when component loses focus"""
        # Re-enable auto-scroll only if content overflows
        total_content_width = self.get_total_content_width()
        available_width = self.rect.width - (2 * self.padding_x)
        if total_content_width > available_width:
            self.auto_scroll_enabled = True
        
        old_focused = self.focused_box_index
        self.focused_box_index = -1
        
        # Rebuild surface if focus state changed
        if old_focused != self.focused_box_index:
            self.surface_needs_rebuild = True
            self.needs_redraw = True
    
    def get_focused_sub_rect(self):
        """Get the rect of the currently focused box for highlighting"""
        # Only highlight individual boxes when a specific box is focused
        # This prevents double highlighting (component + box) when using keyboard navigation
        if not self.boxes or self.focused_box_index < 0 or self.focused_box_index >= len(self.boxes):
            # No specific box is focused - let UI manager handle component-level highlighting
            return None
            
        # A specific box is focused - return its rect for precise highlighting
        # Check if all boxes fit (different positioning logic)
        total_content_width = self.get_total_content_width()
        available_width = self.rect.width - (2 * self.padding_x)
        all_boxes_fit = total_content_width <= available_width
        
        if all_boxes_fit:
            # For evenly distributed boxes
            if len(self.boxes) == 1:
                # Single box: centered
                box_x = self.padding_x + (available_width - self.box_width) // 2
            else:
                # Multiple boxes: each centered in its allocated space
                space_per_box = available_width // len(self.boxes)
                box_center_in_space = space_per_box // 2
                box_x = self.padding_x + (self.focused_box_index * space_per_box) + box_center_in_space - (self.box_width // 2)
        else:
            # For scrolling boxes - use scroll offset
            box_x = self.padding_x + self.focused_box_index * (self.box_width + self.box_spacing) - self.scroll_offset
            
        box_y = self.padding_y
        
        # Create the sub-rect in screen coordinates
        sub_rect = pygame.Rect(
            self.rect.x + box_x,
            self.rect.y + box_y,
            self.box_width,
            self.box_height
        )
        
        return sub_rect
        
    def get_mouse_sub_rect(self, mouse_pos):
        """Get the rect for the status box under the mouse cursor"""
        if not self.boxes:
            return None
            
        # Convert to component-relative coordinates
        relative_x = mouse_pos[0] - self.rect.x
        relative_y = mouse_pos[1] - self.rect.y

        # Check if mouse is within component bounds
        if not (0 <= relative_x < self.rect.width and 0 <= relative_y < self.rect.height):
            return None

        # Check if mouse is within the padded content area
        if (relative_x < self.padding_x or relative_x >= self.rect.width - self.padding_x or
            relative_y < self.padding_y or relative_y >= self.rect.height - self.padding_y):
            return None

        # Calculate mouse position within content area
        content_x = relative_x - self.padding_x
        
        # Check if all boxes fit (different positioning logic)
        total_content_width = self.get_total_content_width()
        available_width = self.rect.width - (2 * self.padding_x)
        all_boxes_fit = total_content_width <= available_width
        
        if all_boxes_fit:
            # For evenly distributed boxes
            for i, box in enumerate(self.boxes):
                if len(self.boxes) == 1:
                    # Single box: centered
                    box_start = (available_width - self.box_width) // 2
                    box_end = box_start + self.box_width
                else:
                    # Multiple boxes: each centered in its allocated space
                    space_per_box = available_width // len(self.boxes)
                    box_center_in_space = space_per_box // 2
                    box_start = (i * space_per_box) + box_center_in_space - (self.box_width // 2)
                    box_end = box_start + self.box_width
                
                if box_start <= content_x < box_end:
                    # Return the rect for this box in screen coordinates
                    return pygame.Rect(
                        self.rect.x + self.padding_x + box_start,
                        self.rect.y + self.padding_y,
                        self.box_width,
                        self.box_height
                    )
        else:
            # For scrolling boxes - use scroll offset and check both surface cycles
            content_x_with_scroll = content_x + self.scroll_offset
            total_content_width = self.get_total_content_width()
            cycle_gap = self.box_spacing
            cycle_length = total_content_width + cycle_gap
            
            # Check both cycles for mouse intersection
            for cycle in range(2):
                cycle_offset = cycle * cycle_length
                
                for i, box in enumerate(self.boxes):
                    box_start = cycle_offset + (i * (self.box_width + self.box_spacing))
                    box_end = box_start + self.box_width
                    
                    if box_start <= content_x_with_scroll < box_end:
                        # Check if this box is actually visible on screen
                        box_screen_x = box_start - self.scroll_offset
                        if (box_screen_x >= 0 and 
                            box_screen_x + self.box_width <= available_width):
                            # Return the rect for this visible box in screen coordinates
                            return pygame.Rect(
                                self.rect.x + self.padding_x + box_screen_x,
                                self.rect.y + self.padding_y,
                                self.box_width,
                                self.box_height
                            )
        
        return None
        
    def render(self):
        """Render the carousel using optimized pre-rendered surface"""
        surface = pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
        
        if not self.boxes:
            return surface
        
        # Build content surface if needed
        if self.surface_needs_rebuild or self.content_surface is None:
            self.build_content_surface()
            
        if self.content_surface is None:
            return surface
            
        # Calculate visible drawing area with padding
        visible_start_x = self.padding_x
        visible_width = self.rect.width - (2 * self.padding_x)
        visible_start_y = self.padding_y
        
        # Calculate source rect from content surface based on scroll offset
        total_width = self.get_total_content_width()
        if total_width > 0:
            # Check if all boxes fit to determine scroll behavior
            all_boxes_fit = total_width <= (self.rect.width - (2 * self.padding_x))
            
            if all_boxes_fit:
                # For static layout, no scroll offset normalization needed
                normalized_offset = 0
            else:
                # For scrolling layout, normalize using cycle length (total_width + gap)
                cycle_gap = self.box_spacing
                cycle_length = total_width + cycle_gap
                normalized_offset = self.scroll_offset % cycle_length
            
            # Create source rect
            source_rect = pygame.Rect(
                int(normalized_offset),
                0,
                min(visible_width, self.content_surface.get_width() - int(normalized_offset)),
                self.box_height
            )
            
            # Blit the visible portion
            if source_rect.width > 0:
                surface.blit(
                    self.content_surface,
                    (visible_start_x, visible_start_y),
                    source_rect
                )
                
                # Handle wrapping if we need to show content from the beginning
                if source_rect.width < visible_width and normalized_offset > 0:
                    remaining_width = visible_width - source_rect.width
                    wrap_source_rect = pygame.Rect(0, 0, remaining_width, self.box_height)
                    surface.blit(
                        self.content_surface,
                        (visible_start_x + source_rect.width, visible_start_y),
                        wrap_source_rect
                    )
            
        return surface