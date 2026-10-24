# game_enemy.py
import os
from dataclasses import dataclass

from models.animation import PetFrame
import core.constants as constants
from utils.sprite_utils import convert_sprites_to_list, load_enemy_sprites, pair_right_frames, right_facing
from core import runtime_globals


@dataclass
class GameEnemy:
    name: str
    power: int
    attribute: str
    area: int
    round: int
    version: int
    atk_main: int
    atk_alt: int
    atk_alt_2: int
    handicap: int
    id: int
    stage: int
    hp: int
    unlock: str
    prize: str
    mini_game: int = 0
    special_encounter: bool = False
    # Battling this enemy registers it in the player's per-module Friend list
    # (used by Xros temporary evolutions and the digidex Friends view).
    friend: bool = False
    # A shop.json currency this enemy charges and pays in: on a round 1 enemy
    # `currency_cost` is its area's entry fee, and `currency_reward` is paid
    # for beating it (the round's biggest, once). utils.currency_utils.
    currency: str = ""
    currency_cost: int = 0
    currency_reward: int = 0
    # A card pack (cards.json pack id) won for beating this enemy, as `prize`
    # is an item; and the percent chance either drops (absent: always).
    prize_card_pack: str = ""
    prize_chance: int = 100
    # The attacks this enemy throws in the adventure, one per round, on the
    # module's battle scale (Colour lines: 1 a normal shot, 2 a super one).
    # The quest tables of the Pendulum Colors name one per round; absent,
    # the enemy's pattern comes from its stage as before.
    attack_pattern: list = None

    def load_sprite(self, module_path: str, boss: bool = False):
        """
        Loads specific animation frames for the enemy using the new sprite loading utility.

        Args:
            module_path (str): Path to the module directory.
            boss (bool): Whether this enemy is a boss (applies scaling).
        """
        # Determine module name from path to get module object for name_format
        module_name = module_path
        module_path = os.path.join("modules", module_name)
        
        # Try to get module object to access name_format and sprite formats
        try:
            from utils.module_utils import get_module
            module_obj = get_module(module_name)
            name_format = getattr(module_obj, 'name_format', '$_dmc') if module_obj else '$_dmc'
            primary_format = getattr(module_obj, 'primary_sprite_format', 'Color') if module_obj else 'Color'
            secondary_format = getattr(module_obj, 'secondary_sprite_format', 'HD') if module_obj else 'HD'
        except:
            name_format = '$_dmc'  # Default fallback
            primary_format = 'Color'
            secondary_format = 'HD'
        
        # Calculate size based on boss status. Boss size is pre-snapped to the
        # pixel-perfect ladder in runtime_globals (PET size * BOSS_MULTIPLIER
        # would land between the 48-multiple steps).
        if boss:
            size = (runtime_globals.PET_WIDTH_BOSS, runtime_globals.PET_HEIGHT_BOSS)
        else:
            size = (runtime_globals.PET_WIDTH, runtime_globals.PET_HEIGHT)
        
        # Load sprites using the new utility function
        right = {}
        sprites_dict = load_enemy_sprites(
            self.name,
            module_path,
            name_format,
            size=size,
            primary_sprite_format=primary_format,
            secondary_sprite_format=secondary_format,
            # Same rule as pets: a whole multiple of the art's own size, so an
            # HD enemy is not squashed to fit a square slot.
            pixel_perfect=True,
            right=right
        )
        # Its own right-facing frames ({left surface: right surface}).
        self.right_frames = pair_right_frames(sprites_dict, right)
        
        # Convert to the expected format
        sprite_list = convert_sprites_to_list(sprites_dict)
        
        # Initialize frames array
        max_index = max(frame.value for frame in PetFrame)
        self.frames = [None] * (max_index + 1)
        
        # Populate frames array with loaded sprites (keeping None for missing frames)
        for i, sprite in enumerate(sprite_list):
            if i < len(self.frames):
                self.frames[i] = sprite

    def get_sprite(self, index: int):
        if hasattr(self, "frames") and 0 <= index < len(self.frames):
            return self.frames[index]
        return None

    def get_right_sprite(self, index: int):
        """Frame *index* facing right: the set's own right-facing drawing
        (``<n>R.png``), else the frame mirrored. None when it is missing."""
        frame = self.get_sprite(index)
        if frame is None:
            return None
        return right_facing(frame, getattr(self, "right_frames", None))