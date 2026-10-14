import random
from datetime import datetime
from typing import List, Optional

from core import runtime_globals, game_globals
from models.game_quest import GameQuest, QuestType, QuestStatus, RewardType
from models.game_event import GameEvent, EventType
from models.quest_event_data import QuestData, EventData
from utils.inventory_utils import add_to_inventory, get_item_by_name


def get_all_available_quest_data() -> List[QuestData]:
    """
    Get all available quest data from modules that have pets in the party.
    """
    party_modules = set(pet.module for pet in game_globals.pet_list)
    all_quest_data = []
    for module_name, module in runtime_globals.game_modules.items():
        if module_name not in party_modules:
            continue
        quest_data = module.load_quests_json()
        all_quest_data.extend(quest_data)
    return all_quest_data


def get_all_available_event_data() -> List[EventData]:
    """
    Get all available event data from all loaded modules.
    
    Returns:
        List of all available event templates across all modules
    """
    all_event_data = []
    for module_name, module in runtime_globals.game_modules.items():
        event_data = module.load_events_json()
        all_event_data.extend(event_data)
    return all_event_data


def create_quest_instance_from_data(quest_data: QuestData, module_name: str) -> GameQuest:
    """
    Create a GameQuest instance from QuestData template.
    
    Args:
        quest_data: The quest template data
        module_name: Name of the module this quest belongs to
        
    Returns:
        GameQuest instance ready for tracking
    """
    # Handle target_amount - can be single value or range
    target_amount = quest_data.target_amount or 1
    if quest_data.target_amount_range:
        if isinstance(quest_data.target_amount_range, list) and len(quest_data.target_amount_range) >= 1:
            # For daily quests, we could randomize within the range
            target_amount = random.choice(quest_data.target_amount_range)
    
    # Generate standardized quest name based on type and target amount
    quest_type_enum = QuestType(quest_data.type)
    if quest_type_enum == QuestType.BOSS:
        quest_name = f"Defeat {target_amount} Boss{'es' if target_amount > 1 else ''}"
    elif quest_type_enum == QuestType.TRAINING:
        quest_name = f"Train {target_amount} Time{'s' if target_amount > 1 else ''}"
    elif quest_type_enum == QuestType.BATTLE:
        quest_name = f"Win {target_amount} Battle{'s' if target_amount > 1 else ''}"
    elif quest_type_enum == QuestType.FEEDING:
        quest_name = f"Eat {target_amount} Sp Item{'s' if target_amount > 1 else ''}"
    elif quest_type_enum == QuestType.EVOLUTION:
        quest_name = f"Evo {target_amount} Time{'s' if target_amount > 1 else ''}"
    elif quest_type_enum == QuestType.ARMOR_EVOLUTION:
        quest_name = f"Armor Evo {target_amount} Time{'s' if target_amount > 1 else ''}"
    elif quest_type_enum == QuestType.JOGRESS:
        quest_name = f"Jogress {target_amount} Time{'s' if target_amount > 1 else ''}"
    else:
        # Fallback to original name if type is unknown
        quest_name = quest_data.name
    
    # Handle reward_item - can be reward_item or reward_value
    reward_item = quest_data.reward_item or quest_data.reward_value or ""
    reward_amount = quest_data.reward_quantity
    
    # For EXPERIENCE and TROPHY rewards, the value should be the quantity (amount)
    # For ITEM rewards, the value should be the item name/id
    reward_type_enum = RewardType(quest_data.reward_type)
    if reward_type_enum in [RewardType.EXPERIENCE, RewardType.TROPHY, RewardType.VITAL_VALUES]:
        # For non-item rewards, the "value" is actually the quantity/amount
        reward_value = reward_amount
        reward_quantity = reward_amount
    else:
        # For item rewards, use the item name/id as value and quantity separately
        reward_value = reward_item
        reward_quantity = reward_amount
    
    return GameQuest(
        quest_id=quest_data.id,
        name=quest_name,
        module=module_name,
        quest_type=quest_type_enum,
        target_amount=target_amount,
        date_obtained=datetime.now().strftime("%Y-%m-%d"),
        reward_type=reward_type_enum,
        reward_value=reward_value,
        reward_quantity=reward_quantity
    )


def create_event_instance_from_data(event_data: EventData, module_name: str) -> GameEvent:
    """
    Create a GameEvent instance from EventData template.
    
    Args:
        event_data: The event template data
        module_name: Name of the module this event belongs to
        
    Returns:
        GameEvent instance ready for triggering
    """
    return GameEvent(
        event_id=event_data.id,
        name=event_data.name,
        module=module_name,
        global_event=event_data.global_event,
        event_type=EventType(event_data.type),
        chance_percent=event_data.chance_percent,
        area=event_data.area,
        round_num=event_data.round,
        item=event_data.item,
        item_quantity=event_data.item_quantity
    )


def generate_daily_quests() -> List[GameQuest]:
    """
    Generate 3 random daily quests for the player.
    Attempts to select quests with different types when possible.
    This should be called once per day.
        
    Returns:
        List of 3 randomly selected quest instances
    """
    all_quest_data = get_all_available_quest_data()
    
    if not all_quest_data:
        return []
    
    # Organize quests by type
    quests_by_type = {}
    for quest_data in all_quest_data:
        quest_type = quest_data.type
        if quest_type not in quests_by_type:
            quests_by_type[quest_type] = []
        quests_by_type[quest_type].append(quest_data)
    
    # Get list of available types
    available_types = list(quests_by_type.keys())
    
    selected_quest_data = []
    used_types = []
    
    # Select 3 quests, preferring different types
    for i in range(3):
        # If we have unused types, pick from them
        if available_types:
            selected_type = random.choice(available_types)
            available_types.remove(selected_type)
        # If all types are used, reuse from already used types
        elif used_types:
            selected_type = random.choice(used_types)
        # Fallback: pick any type (shouldn't happen if we have data)
        else:
            selected_type = random.choice(list(quests_by_type.keys()))
        
        # Pick a random quest from the selected type
        quest_data = random.choice(quests_by_type[selected_type])
        selected_quest_data.append(quest_data)
        
        # Track this type as used
        if selected_type not in used_types:
            used_types.append(selected_type)
    
    # Convert to quest instances and set assignment date
    current_date = datetime.now().strftime("%Y-%m-%d")
    selected_instances = []
    
    for quest_data in selected_quest_data:
        # Find the module name for this quest
        module_name = "Unknown"
        for mod_name, module in runtime_globals.game_modules.items():
            mod_quest_data = module.load_quests_json()
            if any(q.id == quest_data.id for q in mod_quest_data):
                module_name = mod_name
                break
                
        quest_instance = create_quest_instance_from_data(quest_data, module_name)
        # Status is already set to PENDING by default in GameQuest constructor
        quest_instance.date_assigned = current_date
        selected_instances.append(quest_instance)
    
    return selected_instances


def get_hourly_random_event() -> Optional[GameEvent]:
    """Select using the shared event rules; animation stays in SceneMainGame."""
    from models.event_clock import EventClock
    return EventClock.choose(game_globals.pet_list, runtime_globals.game_modules,
                             game_globals.xai)


def update_quest_progress(quest_type: QuestType, progress_amount: int = 1, module_name: str = None) -> bool:
    """
    Update the progress of quests matching the given type and module.
    
    Args:
        quest_type: The type of quest to update (BOSS, TRAINING, BATTLE, FEEDING)
        progress_amount: Amount to add to current progress (default 1)
        module_name: Module name for BOSS, BATTLE, and FEEDING quests (optional for TRAINING)
        
    Returns:
        True if any quest was found and updated, False otherwise
    """
    updated_any = False
    
    for quest in game_globals.quests:
        # Skip if quest is not pending
        if quest.status != QuestStatus.PENDING:
            continue
            
        # Check if quest type matches
        if quest.type != quest_type:
            continue
            
        # For BOSS, BATTLE, and FEEDING quests, check module match
        if quest_type in [QuestType.BOSS, QuestType.BATTLE, QuestType.FEEDING]:
            if module_name and quest.module != module_name:
                continue
        
        # Update progress
        quest_completed = quest.update_progress(progress_amount)
        updated_any = True
        
        runtime_globals.game_console.log(f"Quest '{quest.name}' progress: {quest.current_amount}/{quest.target_amount}")
        
        if quest_completed:
            runtime_globals.game_console.log(f"Quest '{quest.name}' completed! Ready to claim rewards.")
    
    return updated_any


def complete_quest(quest_id: str) -> Optional[dict]:
    """
    Complete a quest and return its reward information.
    
    Args:
        quest_id: The ID of the quest to complete
        
    Returns:
        Dictionary with reward information, None if quest not found
    """
    
    for quest in game_globals.quests:
        if quest.id == quest_id and quest.status == QuestStatus.SUCCESS:
            # Give rewards
            if quest.reward_type == RewardType.ITEM:
                add_to_inventory(get_item_by_name(quest.module, quest.reward_value).id, quest.reward_quantity)
                runtime_globals.game_console.log(f"Received {quest.reward_quantity}x {quest.reward_value}")
            elif quest.reward_type == RewardType.VITAL_VALUES:
                # Apply vital values to all pets
                for pet in game_globals.pet_list:
                    pet.vital_values = min(pet.vital_values + quest.reward_quantity, 999999)  # Cap at 999999
                runtime_globals.game_console.log(f"All pets received +{quest.reward_quantity} vital values")
            elif quest.reward_type == RewardType.TROPHY:
                # Add trophies to all pets
                for pet in game_globals.pet_list:
                    pet.trophies += quest.reward_quantity
                runtime_globals.game_console.log(f"All pets received +{quest.reward_quantity} trophies")
            elif quest.reward_type == RewardType.EXPERIENCE:
                # Add experience to all pets using the GamePet method
                for pet in game_globals.pet_list:
                    pet.add_experience(quest.reward_quantity)
                runtime_globals.game_console.log(f"All pets received +{quest.reward_quantity} experience")
            
            # Mark quest as finished
            quest.status = QuestStatus.FINISHED
            
            return {
                "reward_type": quest.reward_type.name,
                "reward_value": quest.reward_value,
                "reward_quantity": quest.reward_quantity
            }
    
    return None


def update_evolution_quest_progress(evolution_type: str, module_name: str = None) -> bool:
    """
    Updates quest progress for evolution-related quests.
    
    Args:
        evolution_type: Type of evolution ("normal", "armor", "jogress")
        module_name: Module name for the evolution
        
    Returns:
        True if any quest was updated, False otherwise
    """
    # Map evolution types to quest types
    quest_type_map = {
        "normal": QuestType.EVOLUTION,
        "armor": QuestType.ARMOR_EVOLUTION,
        "jogress": QuestType.JOGRESS
    }
    
    quest_type = quest_type_map.get(evolution_type)
    if not quest_type:
        return False
        
    return update_quest_progress(quest_type, 1, module_name)


def get_completed_quests() -> list:
    """
    Get all completed quests that are ready to claim rewards.
    
    Returns:
        List of completed quests
    """
    return [quest for quest in game_globals.quests if quest.status == QuestStatus.SUCCESS]


def claim_all_completed_quests() -> List[dict]:
    """
    Claim rewards for all completed quests.
    
    Returns:
        List of reward information for all claimed quests
    """
    completed_quests = get_completed_quests()
    rewards = []
    
    for quest in completed_quests:
        reward = complete_quest(quest.id)
        if reward:
            rewards.append(reward)
    
    return rewards


def trigger_event(event: GameEvent) -> dict:
    """
    Trigger an event and return its result.
    
    Args:
        event: The GameEvent to trigger
        
    Returns:
        Dictionary with event result information
    """
    runtime_globals.game_console.log(f"Event triggered: {event.name}")
    
    result = {
        "event_name": event.name,
        "event_type": event.type.name,
        "success": True
    }
    
    if event.type.name == "ITEM_PACKAGE":
        result["item_received"] = event.item
        result["item_quantity"] = event.item_quantity
    elif event.type.name == "ENEMY_BATTLE":
        result["battle_area"] = event.area
        result["battle_round"] = event.round
    
    return result


def force_complete_quest(quest_id: str) -> bool:
    """
    Force a quest to be completed by setting its status to SUCCESS and updating progress.
    
    Args:
        quest_id: The ID of the quest to force complete.
    
    Returns:
        True if the quest was successfully completed, False otherwise.
    """
    for quest in game_globals.quests:
        if quest.id == quest_id:
            quest.status = QuestStatus.SUCCESS
            quest.current_amount = quest.target_amount
            runtime_globals.game_console.log(f"Quest '{quest.name}' forcibly completed.")
            return True
    runtime_globals.game_console.log(f"Quest with ID '{quest_id}' not found.")
    return False
