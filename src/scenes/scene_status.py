"""
Scene Status
A status scene showing pet information using the new UI components.
"""

import pygame
from core import game_globals, runtime_globals, constants
from utils.module_utils import get_module
from ui.ui_manager import UIManager
from ui.components.pet_list import PetList
from ui.components.background import Background
from ui.components.label import Label
from ui.components.label_value import LabelValue
from ui.ui_constants import YELLOW
from ui.components.heart import HeartMeter
from ui.components.dp_bar import DPBar
from ui.components.gcell_bar import GCellBar
from ui.components.reliability_meter import ReliabilityMeter
from ui.components.status_carousel import StatusCarousel
from ui.components.experience_bar import ExperienceBar
from ui.components.numeric_meter import NumericMeter
from ui.components.heart_meter_condition import HeartMeterCondition
from ui.components.flag_panel import FlagPanel
from ui.components.digisoul_icon import DigiSoulIcon, normalize_digisoul
from ui.windows.window_background import WindowBackground
from utils.scene_utils import change_scene


def digisoul_below_flags_available(visible_stats, use_condition_hearts=False):
    """Whether the right-column row immediately below flags is unused."""
    if any(stat in visible_stats for stat in (
            "Level", "Experience", "Trophies", "Vital Values")):
        return False
    if (use_condition_hearts
            and "Mistakes/Condition Hearts" in visible_stats):
        return False
    return True


class SceneStatus:

    def __init__(self) -> None:
        """
        Initialize the status scene.
        """
        try:
            # Initialize UI Manager with purple theme
            self.ui_manager = UIManager("PURPLE")
            
            # Connect input manager to UI manager for mouse handling
            self.ui_manager.set_input_manager(runtime_globals.game_input)
            
            # Get screen dimensions
            self.screen_width = runtime_globals.SCREEN_WIDTH
            self.screen_height = runtime_globals.SCREEN_HEIGHT
            
            # Current selected pet
            self.selected_pet = None
            
            # UI Components
            self.pet_list = None
            self.pet_name_label = None
            self.stage_label = None
            self.age_label = None
            self.weight_label = None
            self.level_label = None
            self.exp_label = None
            
            # Numeric meters for alternative stats
            self.trophy_meter = None
            self.vital_values_meter = None
            
            # Condition heart meter for modules that use condition hearts
            self.condition_heart_meter = None
            
            # Flag panel for pet attributes and status
            self.flag_panel = None
            self.digisoul_icon = None
            
            # Status components
            self.hunger_meter = None
            self.strength_meter = None  # Changed from vitamin_meter
            self.reliability_meter = None
            self.effort_meter = None
            self.gcell_bar = None
            self.dp_bar = None
            self.experience_bar = None
            self.status_carousel = None
            
            # Stat labels
            self.power_label = None
            self.power_value = None
            self.battles_label = None
            self.battles_value = None
            self.win_rate_label = None
            self.win_rate_value = None
            self.total_label = None
            self.total_value = None
            
            # Flag sprites
            self.flag_sprites = {}
            
            # Scrollable stats panel
            self.scrollable_panel = None
            
            # Window background
            self.window_background = WindowBackground(False)
            
            self.setup_ui()
            
            runtime_globals.game_console.log("[SceneStatus] Status scene initialized with new UI system.")
            
        except Exception as e:
            runtime_globals.game_console.log(f"[SceneStatus] CRITICAL ERROR during initialization: {e}")
            import traceback
            runtime_globals.game_console.log(f"[SceneStatus] Full traceback: {traceback.format_exc()}")
            # Re-raise the exception so the game doesn't continue in a broken state
            raise

    def setup_ui(self):
        try:
            # Use base 240x240 resolution for UI layout
            from ui.ui_constants import BASE_RESOLUTION
            ui_width = ui_height = BASE_RESOLUTION
            scale = self.ui_manager.ui_scale
              # Enable full shadows for the entire UI
            
            # Pet list height (fixed component size)
            pet_list_height = 44
            
            # Calculate margins and column layout for base resolution
            margin = 12
            column_gap = 10
            content_width = ui_width - (2 * margin)
            column_width = (content_width - column_gap) // 2
            
            # Define Y positions for different sections
            pet_info_start_y = pet_list_height + 15
            
            # Create and add the background with component-based regions
            background = Background(ui_width, ui_height)
            
            # Calculate region boundaries based on component positions
            region1_end = pet_list_height + 10  # Pet list + small padding
            region2_end = region1_end + 71  # Pet info section
            region3_end = region2_end + 72  # Stats section
            region4_end = ui_height         # Carousel area
            
            background.set_regions([
                (0, region1_end, "bg"),           # Dark purple top
                (region1_end, region2_end, "black"),   # Black middle-top
                (region2_end, region3_end, "bg"), # Dark purple middle-bottom
                (region3_end, region4_end, "black"),    # Black before carousel
            ])
            
            self.ui_manager.add_component(background)
            runtime_globals.game_console.log("[SceneStatus] Background component added successfully")
            
            # Create and add the PetList component
            pet_list = PetList(0, 7, ui_width, pet_list_height, game_globals.pet_list, self.on_pet_selected)
            self.pet_list = self.ui_manager.add_component(pet_list)
            runtime_globals.game_console.log(f"[SceneStatus] PetList component added successfully with {len(game_globals.pet_list)} pets")
            
            # Pet information labels (only create them, will populate when pet is selected)
            current_y = pet_info_start_y - 3
            
            # Pet name label (spans both columns)
            self.pet_name_label = Label(
                margin, current_y, "", is_title=True, scroll_text=True
            )
            self.pet_name_label.set_tooltip("The pet's name.")
            self.ui_manager.add_component(self.pet_name_label)
            current_y += 26
            
            # Stage label (left column)
            self.stage_label = Label(
                margin, current_y, "Stage: -", is_title=False
            )
            self.stage_label.set_tooltip("The current stage of the pet's life")
            self.ui_manager.add_component(self.stage_label)
            
            # Flag panel (right side, aligned with stage label)
            flag_width = column_width - 10  # Leave some margin
            flag_height = 20  # Height for flag sprites
            flag_x = margin + column_width + column_gap + 10  # Right column with some offset
            
            self.flag_panel = FlagPanel(flag_x, current_y, flag_width, flag_height)
            self.flag_panel.set_tooltip("Pet attributes and status flags")
            self.ui_manager.add_component(self.flag_panel)
            
            current_y += 15

            # The right-column row immediately below the flags is normally
            # used by Level/Experience-style stats. When that row is free, a
            # module can use it for the pet's native DigiSoul family instead.
            digisoul_size = 22
            self.digisoul_icon = DigiSoulIcon(
                flag_x + flag_width - digisoul_size,
                current_y + 5,
                digisoul_size,
            )
            self.digisoul_icon.visible = False
            self.ui_manager.add_component(self.digisoul_icon)

            # Age label (right column) - will be shown based on module visible_stats
            self.age_label = Label(
                margin, current_y, "Age: -", is_title=False, color_override=YELLOW
            )
            self.age_label.set_tooltip("The amount of days the pet has been alive")
            self.age_label.visible = False  # Hidden by default, shown based on visible_stats
            self.ui_manager.add_component(self.age_label)
            current_y += 15
            
            # Weight label (left column) - will be shown based on module visible_stats
            self.weight_label = Label(
                margin, current_y, "Weight: -", is_title=False, color_override=YELLOW
            )
            self.weight_label.set_tooltip("The amount of data in the pet, higher weight can lead to sickness")
            self.weight_label.visible = False  # Hidden by default, shown based on visible_stats
            self.ui_manager.add_component(self.weight_label)
            
            # Level label (right column, aligned with weight) - will be shown based on module visible_stats
            level_x = margin + column_width + column_gap
            self.level_label = Label(
                level_x, current_y, "Lv: -", is_title=False, color_override=YELLOW
            )
            self.level_label.set_tooltip("The pet's current level")
            self.level_label.visible = False  # Hidden by default, shown based on visible_stats
            self.ui_manager.add_component(self.level_label)
            
            # Experience Bar (right of level label) - will be shown based on module visible_stats
            exp_bar_width = 66  # Base width at 1x scale
            exp_bar_height = 14  # Base height at 1x scale
            # Position to the right of level label, with some spacing
            exp_bar_x = level_x + 42  # Adjust based on typical "Level: X" width
            exp_bar_y = current_y - 4  # Slightly adjust vertical alignment
            
            self.experience_bar = ExperienceBar(exp_bar_x, exp_bar_y, exp_bar_width, exp_bar_height)
            self.experience_bar.set_tooltip("Experience progress towards next level")
            self.experience_bar.visible = False  # Hidden by default, shown based on visible_stats
            self.ui_manager.add_component(self.experience_bar)
            
            # Trophy Meter (alternative to level label) - will be shown based on module visible_stats
            trophy_width = 47
            trophy_height = 24
            
            self.trophy_meter = NumericMeter(level_x - 7, current_y - 10, trophy_width, trophy_height, "Trophies", 0, max_digits=3)
            self.trophy_meter.set_tooltip("Number of trophies earned by this pet")
            self.trophy_meter.visible = False  # Hidden by default, shown based on visible_stats
            self.ui_manager.add_component(self.trophy_meter)
            
            # Vital Values Meter (alternative to experience bar) - will be shown based on module visible_stats
            vital_width = 67
            vital_height = 24
            vital_x = level_x + 43  # Align with level label position
            
            self.vital_values_meter = NumericMeter(vital_x, current_y - 10, vital_width, vital_height, "Vital Values", 0, max_digits=5)
            self.vital_values_meter.set_tooltip("Vital values accumulated by this pet")
            self.vital_values_meter.visible = False  # Hidden by default, shown based on visible_stats
            self.ui_manager.add_component(self.vital_values_meter)
            
            # Condition Heart Meter (alternative to level/experience/trophy/vital components) - will be shown based on module visible_stats
            condition_width = column_width - 20
            condition_height = 24
            condition_x = margin + column_width + column_gap + 10
            
            self.condition_heart_meter = HeartMeterCondition(condition_x, current_y - 10, condition_width, condition_height, 0, 4)
            self.condition_heart_meter.set_tooltip("Condition hearts - care quality indicator")
            self.condition_heart_meter.visible = False  # Hidden by default, shown based on visible_stats
            self.ui_manager.add_component(self.condition_heart_meter)
            
            runtime_globals.game_console.log("[SceneStatus] Labels created successfully")

            # Add Heart components for hunger, strength, and effort below weight label
            heart_gap = 8
            heart_height = 24
            heart_width = 85
            heart_y = current_y + 15

            self.hunger_meter = HeartMeter(margin, heart_y, heart_width, heart_height, "Hunger", 0, 4, 1)
            self.hunger_meter.set_tooltip("Hunger - basic need stat, keep your pet well fed to avoid penalties")
            self.hunger_meter.visible = False  # Hidden by default, shown based on visible_stats
            self.ui_manager.add_component(self.hunger_meter)
            heart_y += 22

            self.strength_meter = HeartMeter(margin, heart_y, heart_width, heart_height, "Vitamin", 0, 4, 1)
            self.strength_meter.set_tooltip("Strength - basic need stat, keep at maximum to gain bonuses")
            self.strength_meter.visible = False  # Hidden by default, shown based on visible_stats
            self.ui_manager.add_component(self.strength_meter)

            # Reliability replaces Strength in this slot on devices such as
            # the iC, which have the former care stat and no protein meter.
            self.reliability_meter = ReliabilityMeter(
                margin, heart_y, heart_width, heart_height, constants.RELIABILITY_MIN
            )
            self.reliability_meter.set_tooltip(
                "Reliability - trust between the pet and player, from 0 to 31"
            )
            self.reliability_meter.visible = False
            self.ui_manager.add_component(self.reliability_meter)
            heart_y += 22

            self.effort_meter = HeartMeter(margin, heart_y, heart_width, heart_height, "Effort", 0, 4, 4)
            self.effort_meter.set_tooltip("Effort - gained through training, can increase power")
            self.effort_meter.visible = False  # Hidden by default, shown based on visible_stats
            self.ui_manager.add_component(self.effort_meter)

            # G-Cell Bar (alternative to effort meter)
            self.gcell_bar = GCellBar(margin, heart_y, heart_width + 3, heart_height)
            self.gcell_bar.set_tooltip("G-Cells - evolution requirement indicator with 4 levels.")
            self.gcell_bar.visible = False  # Hidden by default, shown based on visible_stats
            self.ui_manager.add_component(self.gcell_bar)

            # Add DP Bar in second column, aligned with hunger meter
            dp_start_y = current_y + 13
            dp_width = column_width
            dp_height = heart_height
            dp_x = margin + column_width + column_gap
            
            self.dp_bar = DPBar(dp_x, dp_start_y, dp_width, dp_height, 0, 14)
            self.dp_bar.set_tooltip("DP - earned through sleeping and eating certain items. Required to battle.")
            self.dp_bar.visible = False  # Hidden by default, shown based on visible_stats
            self.ui_manager.add_component(self.dp_bar)
            
            # Add stat labels in second column below DP bar
            stats_start_y = dp_start_y + dp_height
            stats_gap = -3
            value_width = 40  # Fixed width for right alignment
            
            # Power label+value combined
            self.power_combined = LabelValue(dp_x, stats_start_y, dp_width, 15, "Power:", "0",
                                           tooltip_text="The Digimon's battle strength. Higher power means higher chance to hit in battle.")
            self.power_combined.visible = False  # Hidden by default, shown based on visible_stats
            self.ui_manager.add_component(self.power_combined)
            stats_start_y += 15 + stats_gap

            # Battles label+value combined  
            self.battles_combined = LabelValue(dp_x, stats_start_y, dp_width, 15, "Battles:", "0", tooltip_text="Total number of battles fought by this pet.")
            self.battles_combined.visible = False  # Hidden by default, shown based on visible_stats
            self.ui_manager.add_component(self.battles_combined)
            stats_start_y += 15 + stats_gap

            # Win Rate label+value combined
            self.win_rate_combined = LabelValue(dp_x, stats_start_y, dp_width, 15, "Win Rate:", "0%",
                                              tooltip_text="Percentage of battles won. Shows how successful this pet is in combat.")
            self.win_rate_combined.visible = False  # Hidden by default, shown based on visible_stats
            self.ui_manager.add_component(self.win_rate_combined)
            stats_start_y += 15 + stats_gap
            
            # Total label+value combined
            self.total_combined = LabelValue(dp_x, stats_start_y, dp_width, 15, "Total:", "0%", 
                                           tooltip_text="Total win rate throughout the pet's life.")
            self.total_combined.visible = False  # Hidden by default, shown based on visible_stats
            self.ui_manager.add_component(self.total_combined)

            # Add status carousel at the bottom
            carousel_height = 38
            carousel_y = ui_height - carousel_height
            carousel_width = ui_width - (2 * margin)
            
            self.status_carousel = StatusCarousel(margin, carousel_y, carousel_width, carousel_height)
            self.ui_manager.add_component(self.status_carousel)

            # Store layout info for future components
            self.layout_info = {
                'scale': scale,
                'margin': margin,
                'column_gap': column_gap,
                'column_width': column_width,
                'content_width': content_width,
                'current_y': stats_start_y + 30,
                'region_boundaries': [region1_end, region2_end, region3_end, region4_end]
            }
            
            # Select the first pet if available and set it as active
            if game_globals.pet_list:
                try:
                    self.pet_list.set_active_pet(0)  # Set first pet as active
                    self.on_pet_selected(game_globals.pet_list[0])
                    runtime_globals.game_console.log(f"[SceneStatus] First pet selected: {game_globals.pet_list[0].name}")
                except Exception as e:
                    runtime_globals.game_console.log(f"[SceneStatus] Error selecting first pet: {e}")
            
            runtime_globals.game_console.log("[SceneStatus] UI setup completed successfully")
            
        except Exception as e:
            runtime_globals.game_console.log(f"[SceneStatus] ERROR in setup_ui: {e}")
            import traceback
            runtime_globals.game_console.log(f"[SceneStatus] Traceback: {traceback.format_exc()}")
            raise
    
    def adjust_background_regions(self, region1_end=None, region2_end=None, region3_end=None, region4_end=None):
        """
        Helper method to adjust background regions when other components are added
        
        Example usage:
        # When adding a component at Y=200, adjust the second region to end at Y=250
        self.adjust_background_regions(region2_end=250)
        
        # Adjust multiple regions at once
        self.adjust_background_regions(region1_end=150, region3_end=400)
        """
        # Get the background component (should be the first one)
        if self.ui_manager.components:
            background = self.ui_manager.components[0]
            if isinstance(background, Background):
                # Use current values if not specified
                current_regions = background.regions
                if len(current_regions) >= 4:
                    current_r1 = current_regions[0][1] if region1_end is None else region1_end
                    current_r2 = current_regions[1][1] if region2_end is None else region2_end
                    current_r3 = current_regions[2][1] if region3_end is None else region3_end
                    current_r4 = current_regions[3][1] if region4_end is None else region4_end
                else:
                    # Default values
                    scale = self.ui_manager.ui_scale + 1
                    current_r1 = region1_end or (130 * scale)
                    current_r2 = region2_end or (280 * scale)
                    current_r3 = region3_end or (380 * scale)
                    current_r4 = region4_end or self.screen_height
                
                background.set_regions([
                    (0, current_r1, "dark_bg"),
                    (current_r1, current_r2, "black"),
                    (current_r2, current_r3, "dark_bg"),
                    (current_r3, current_r4, "black")
                ])

    def update(self) -> None:
        """
        Update the status scene.
        """
        self.window_background.update()
        self.ui_manager.update()

    def draw(self, surface) -> None:
        """
        Draw the status scene.
        """
        # Draw window background first
        self.window_background.draw(surface)
        
        # Draw UI components on top
        self.ui_manager.draw(surface)
        
    def handle_event(self, event) -> None:
        """
        Handle events in the status scene.
        """
        if not isinstance(event, tuple) or len(event) != 2:
            return
        
        event_type, event_data = event
        
        # Handle events through UI manager first
        if self.ui_manager.handle_event(event):
            return
        
        if event_type == "B":
            runtime_globals.game_sound.play("cancel")
            change_scene("game")
            return

    def on_pet_selected(self, pet):
        """Update the display when a pet is selected"""
        self.selected_pet = pet

        if not pet:
            return

        # Update pet name
        self.pet_name_label.set_text(pet.name.upper())
        self.pet_name_label.set_tooltip(f"Module: {pet.module}, Version: {pet.version}")

        # Update stage
        stage_text = f"Stage: {constants.STAGES[pet.stage]}"
        self.stage_label.set_text(stage_text)

        # Get module configuration before laying out flags: DigiSoul can use
        # the otherwise-empty right-column row directly below them.
        module = get_module(pet.module)
        visible_stats = module.visible_stats if module else []

        # Update flag panel (including G-Cell fragment flag if applicable)
        flags = []
        if hasattr(pet, 'gcell_fragment') and pet.gcell_fragment:
            flags.append('GCellFragment')

        shows_digisoul = any(
            str(stat).casefold() == "digisoul" for stat in visible_stats)
        digisoul = normalize_digisoul(getattr(pet, 'digisoul', ''))
        uses_condition_hearts = (
            getattr(module, 'use_condition_hearts', False) if module else False)
        show_digisoul_below = bool(
            shows_digisoul and digisoul
            and digisoul_below_flags_available(
                visible_stats, uses_condition_hearts))
        self.flag_panel.set_pet_flags(
            pet,
            additional_flags=flags,
            digisoul=(digisoul if shows_digisoul and not show_digisoul_below
                      else None),
        )
        self.digisoul_icon.set_digisoul(
            digisoul if show_digisoul_below else None)
        self.digisoul_icon.visible = show_digisoul_below

        # Update age if it's in visible stats
        if "Age" in visible_stats:
            age_text = f"Age: {pet.age}d"
            self.age_label.set_text(age_text)
            self.age_label.visible = True
        else:
            self.age_label.visible = False

        # Update weight if it's in visible stats
        if "Weight" in visible_stats:
            weight_text = f"Weight: {pet.weight}g"
            self.weight_label.set_text(weight_text)
            self.weight_label.visible = True
        else:
            self.weight_label.visible = False

        # Update level if it's in visible stats
        if "Level" in visible_stats:
            level_text = f"Lv: {pet.level}"
            self.level_label.set_text(level_text)
            self.level_label.visible = True
        else:
            self.level_label.visible = False
            
        # Update experience bar if it's in visible stats
        if "Experience" in visible_stats:
            self.experience_bar.set_experience(pet.experience, pet.level, pet.stage)
            self.experience_bar.visible = True
        else:
            self.experience_bar.visible = False
            
        # Show trophy meter if Trophies is in visible stats but Level is not
        if "Trophies" in visible_stats and "Level" not in visible_stats:
            self.trophy_meter.set_value(getattr(pet, 'trophies', 0))
            self.trophy_meter.visible = True
        else:
            self.trophy_meter.visible = False
            
        # Show vital values meter if Vital Values is in visible stats but Experience is not
        if "Vital Values" in visible_stats and "Experience" not in visible_stats:
            self.vital_values_meter.set_value(getattr(pet, 'vital_values', 0))
            self.vital_values_meter.visible = True
        else:
            self.vital_values_meter.visible = False

        # Show condition heart meter if module uses condition hearts and has Mistakes/Condition Hearts in visible stats,
        # but no Level/Experience/Trophies/Vital Values
        module = get_module(pet.module)
        uses_condition_hearts = getattr(module, 'use_condition_hearts', False) if module else False
        has_condition_stats = ("Mistakes/Condition Hearts" in visible_stats)
        has_other_stats = any(stat in visible_stats for stat in ["Level", "Experience", "Trophies", "Vital Values"])
        
        if uses_condition_hearts and has_condition_stats and not has_other_stats:
            condition_hearts_value = getattr(pet, 'condition_hearts', 0)
            condition_hearts_max = getattr(pet, 'condition_hearts_max', 4)
            self.condition_heart_meter.set_value(condition_hearts_value, condition_hearts_max)
            self.condition_heart_meter.visible = True
        else:
            self.condition_heart_meter.visible = False

        # Update Heart meters and DP bar based on module visible_stats
        if "Hunger" in visible_stats:
            self.hunger_meter.set_value(pet.hunger)
            stomach = getattr(pet, 'stomach', 4)
            care_fixed_4_hearts = getattr(module, 'care_fixed_4_hearts', True)
            if stomach <= 0:
                # No stomach capacity — the pet can't eat, so show no hearts.
                self.hunger_meter.factor = 1
                self.hunger_meter.set_max_value(0)
            elif care_fixed_4_hearts:
                self.hunger_meter.factor = 1
                self.hunger_meter.set_max_value(4)
            else:
                # Dynamic hearts based on stomach (1-4)
                self.hunger_meter.factor = 2
                self.hunger_meter.set_max_value(max(1, min(4, stomach // 2)))
            self.hunger_meter.visible = True
        else:
            self.hunger_meter.visible = False

        if "Strength" in visible_stats:
            self.strength_meter.set_value(pet.strength)
            stomach = getattr(pet, 'stomach', 4)
            care_fixed_4_hearts = getattr(module, 'care_fixed_4_hearts', True)
            if stomach <= 0:
                # No stomach capacity — the pet can't eat, so show no hearts.
                self.strength_meter.factor = 1
                self.strength_meter.set_max_value(0)
            elif care_fixed_4_hearts:
                self.strength_meter.factor = 1
                self.strength_meter.set_max_value(4)
            else:
                # Dynamic hearts based on stomach (1-4)
                self.strength_meter.factor = 2
                self.strength_meter.set_max_value(max(1, min(4, stomach // 2)))
            self.strength_meter.visible = True
            self.reliability_meter.visible = False
        elif "Reliability" in visible_stats:
            self.reliability_meter.set_value(
                getattr(pet, 'reliability', constants.RELIABILITY_MIN)
            )
            self.reliability_meter.visible = True
            self.strength_meter.visible = False
        else:
            self.strength_meter.visible = False
            self.reliability_meter.visible = False
            
        # Show G-Cell bar if G-Cell is in visible stats and Effort is not
        if "G-Cells" in visible_stats and "Effort" not in visible_stats:
            self.gcell_bar.set_pet(pet)
            self.gcell_bar.visible = True
            self.effort_meter.visible = False
        elif "Effort" in visible_stats:
            self.effort_meter.set_value(pet.effort)
            self.effort_meter.visible = True
            self.gcell_bar.visible = False
        else:
            self.effort_meter.visible = False
            self.gcell_bar.visible = False
            
        # Update DP bar and stats based on visible_stats
        if "DP" in visible_stats:
            self.dp_bar.set_value(pet.dp)
            self.dp_bar.visible = True
        else:
            self.dp_bar.visible = False
            
        if "Power" in visible_stats:
            self.power_combined.visible = True
            power = str(pet.power + getattr(pet, 'bonus_stats', [0,0,0])[2])
            # Stars are a Vital Bracelet idea, but the pet carrying one is
            # what decides whether to show it - not the module's ruleset.
            if getattr(pet, 'star', 0) > 0:
                power += f"({pet.star}★)"
            self.power_combined.set_value(power)
        else:
            self.power_combined.visible = False
            
        if "Battles" in visible_stats:
            self.battles_combined.visible = True
            self.battles_combined.set_value(str(pet.battles))
        else:
            self.battles_combined.visible = False
            
        if "Win Rate" in visible_stats:
            self.win_rate_combined.visible = True
            win_rate = (pet.win * 100) // pet.battles if pet.battles > 0 else 0
            self.win_rate_combined.set_value(f"{win_rate}%")
        else:
            self.win_rate_combined.visible = False
            
        if "Total Win Rate" in visible_stats:
            self.total_combined.visible = True
            total_win_rate = (pet.totalWin * 100) // pet.totalBattles if pet.totalBattles > 0 else 0
            self.total_combined.set_value(f"{total_win_rate}%")
        else:
            self.total_combined.visible = False
            
        # Update status carousel with pet data
        # Get module to check visible stats and configuration
        module = get_module(pet.module)
        visible_stats = module.visible_stats if module else []
        use_condition_hearts = module.use_condition_hearts if module else False
        
        # Check if condition heart meter is visible (which means carousel shouldn't show condition hearts)
        has_condition_stats = ("Mistakes/Condition Hearts" in visible_stats)
        has_other_stats = any(stat in visible_stats for stat in ["Level", "Experience", "Trophies", "Vital Values"])
        condition_heart_meter_visible = use_condition_hearts and has_condition_stats and not has_other_stats
        
        pet_data = {
            'module': pet.module,
            'visible_stats': visible_stats,
            'use_condition_hearts': use_condition_hearts,
            'condition_heart_meter_visible': condition_heart_meter_visible,  # Tell carousel to skip condition hearts
            'trophies': getattr(pet, 'trophies', 0),
            'vital_values': getattr(pet, 'vital_values', 0),
            'mistakes': getattr(pet, 'mistakes', 0),
            'condition_hearts': getattr(pet, 'condition_hearts', 0),
            'sleep_disturbances': getattr(pet, 'sleep_disturbances', 0),
            'overfeed': getattr(pet, 'overfeed', 0),
            'injuries': getattr(pet, 'injuries', 0),
            'evolution_timer': getattr(pet, 'time', '00:00'),
            'timer': getattr(pet, 'timer', 0),
            'evolve': getattr(pet, 'evolve', False),
            'sleeps': getattr(pet, 'sleeps', '00:00'),
            'wakes': getattr(pet, 'wakes', '00:00'),
            'poop_time': getattr(pet, 'poop_timer', '00:00'),
            'feed_time': getattr(pet, 'hunger_loss', '00:00')
        }
        self.status_carousel.set_pet_data(pet_data)
