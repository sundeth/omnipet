import pygame
from core import game_globals, runtime_globals
import core.constants as constants
from utils.pygame_utils import blit_with_shadow, get_font
from utils.scene_utils import change_scene
from utils.asset_utils import image_load

PAGE_MARGIN = 0

class WindowPetSelector:
    """
    Window to select a pet from a list, re-rendered every frame (no caching).
    """

    def __init__(self) -> None:
        self.pets = game_globals.pet_list
        self.selected_index = 0
        self.scroll_offset = 0
        self.font = get_font(runtime_globals.FONT_SIZE_MEDIUM_LARGE)
        self.max_visible_items = (runtime_globals.SCREEN_HEIGHT - 2 * PAGE_MARGIN) // self.ITEM_HEIGHT

        # Preload module flags (scaled only once)
        self.module_flags = {}
        for pet in self.pets:
            if pet and pet.module not in self.module_flags:
                flag_path = getattr(runtime_globals.game_modules[pet.module], "flag_path", None)
                if flag_path:
                    flag = image_load(flag_path).convert_alpha()
                    self.module_flags[pet.module] = pygame.transform.scale(
                        flag, (runtime_globals.OPTION_ICON_SIZE, runtime_globals.OPTION_ICON_SIZE)
                    )
                else:
                    self.module_flags[pet.module] = pygame.transform.scale(
                        runtime_globals.game_module_flag[pet.module],
                        (runtime_globals.OPTION_ICON_SIZE, runtime_globals.OPTION_ICON_SIZE)
                    )

    @property
    def LEFT_PADDING(self):
        return int(12 * runtime_globals.UI_SCALE)

    @property
    def ITEM_HEIGHT(self):
        return int(60 * runtime_globals.UI_SCALE)

    def handle_event(self, event) -> None:
        if not isinstance(event, tuple) or len(event) != 2:
            return False
        
        event_type, event_data = event
        
        if event_type == "DOWN":
            runtime_globals.game_sound.play("menu")
            self.selected_index = (self.selected_index + 1) % len(self.pets)
            self.adjust_scroll()
        elif event_type == "LEFT":
            runtime_globals.game_sound.play("menu")
            self.selected_index = (self.selected_index - 4) % len(self.pets)
            self.adjust_scroll()
        elif event_type == "RIGHT":
            runtime_globals.game_sound.play("menu")
            self.selected_index = (self.selected_index + 4) % len(self.pets)
            self.adjust_scroll()
        elif event_type == "UP":
            runtime_globals.game_sound.play("menu")
            self.selected_index = (self.selected_index - 1) % len(self.pets)
            self.adjust_scroll()
        elif event_type == "A":
            runtime_globals.game_sound.play("menu")
            return True
        elif event_type == "B":
            runtime_globals.game_sound.play("cancel")
            change_scene("game")
        return False

    def update(self):
        """Update method called every frame to handle mouse hover."""
        if (runtime_globals.INPUT_MODE == runtime_globals.MOUSE_MODE):
            mouse_pos = runtime_globals.game_input.get_mouse_position()
            self.check_mouse_hover(mouse_pos)

    def check_mouse_hover(self, mouse_pos):
        """Check if mouse is hovering over any pet item and update selection accordingly."""
        mouse_x, mouse_y = mouse_pos
        y_start = PAGE_MARGIN
        
        for idx in range(self.scroll_offset, min(self.scroll_offset + self.max_visible_items, len(self.pets))):
            y_pos = y_start + (idx - self.scroll_offset) * self.ITEM_HEIGHT
            
            # Check if mouse is within this item's bounds
            item_rect = pygame.Rect(
                PAGE_MARGIN, 
                y_pos, 
                runtime_globals.SCREEN_WIDTH - PAGE_MARGIN * 2, 
                self.ITEM_HEIGHT
            )
            
            if item_rect.collidepoint(mouse_x, mouse_y):
                if self.selected_index != idx:
                    self.selected_index = idx
                break

    def adjust_scroll(self) -> None:
        if self.selected_index < self.scroll_offset:
            self.scroll_offset = self.selected_index
        elif self.selected_index >= self.scroll_offset + self.max_visible_items:
            self.scroll_offset = self.selected_index - self.max_visible_items + 1

    def draw(self, surface: pygame.Surface) -> None:
        """
        Redraw everything directly, no caching.
        """
        y_start = PAGE_MARGIN
        for idx in range(self.scroll_offset, min(self.scroll_offset + self.max_visible_items, len(self.pets))):
            pet = self.pets[idx]
            y_pos = y_start + (idx - self.scroll_offset) * self.ITEM_HEIGHT

            attr_colors = {
                "Da": (66, 165, 245),
                "Va": (102, 187, 106),
                "Vi": (237, 83, 80),
                "": (171, 71, 188),
                "???": (0, 0, 0)
            }
            color = attr_colors.get(pet.attribute, (150, 150, 150)) if pet else (150, 150, 150)
            pygame.draw.rect(
                surface,
                color,
                (PAGE_MARGIN + self.LEFT_PADDING, y_pos + int(6 * runtime_globals.UI_SCALE), runtime_globals.OPTION_ICON_SIZE, runtime_globals.OPTION_ICON_SIZE)
            )

            if pet.get_sprite(0):
                sprite = pygame.transform.scale(pet.get_sprite(0), (runtime_globals.OPTION_ICON_SIZE, runtime_globals.OPTION_ICON_SIZE))
                blit_with_shadow(surface, sprite, (PAGE_MARGIN + self.LEFT_PADDING, y_pos + int(6 * runtime_globals.UI_SCALE)))

                flag = self.module_flags.get(pet.module)
                if flag:
                    blit_with_shadow(surface, flag, (PAGE_MARGIN + self.LEFT_PADDING, y_pos + int(6 * runtime_globals.UI_SCALE)))

            name_text = self.font.render(f"{pet.name}", True, constants.FONT_COLOR_DEFAULT)
            stage_name = constants.stage_name(pet.stage)
            attribute_text = self.font.render(f"{stage_name} | {pet.attribute}", True, (200, 200, 200))

            blit_with_shadow(surface, name_text, (PAGE_MARGIN + self.ITEM_HEIGHT + self.LEFT_PADDING, y_pos))
            blit_with_shadow(surface, attribute_text, (PAGE_MARGIN + self.ITEM_HEIGHT + self.LEFT_PADDING, y_pos + int(25 * runtime_globals.UI_SCALE)))

            if idx == self.selected_index:
                pygame.draw.rect(
                    surface,
                    constants.FONT_COLOR_GREEN,
                    (PAGE_MARGIN, y_pos, runtime_globals.SCREEN_WIDTH - PAGE_MARGIN * 2, self.ITEM_HEIGHT),
                    2
                )

    def get_selected_pet(self):
        return self.pets[self.selected_index]
