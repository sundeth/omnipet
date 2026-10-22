from enum import Enum
from datetime import datetime


class QuestType(Enum):
    BOSS = 0
    TRAINING = 1
    BATTLE = 2
    FEEDING = 3
    EVOLUTION = 4
    ARMOR_EVOLUTION = 5
    JOGRESS = 6
    # Nothing to do: offered every day, ready to claim (World's Meat Farm,
    # "Here's your Meat for today"). quest_event_utils.generate_daily_quests.
    DAILY_GIFT = 7


class QuestStatus(Enum):
    PENDING = 0
    SUCCESS = 1
    FAILED = 2
    FINISHED = 3


class RewardType(Enum):
    ITEM = 0
    TROPHY = 1
    EXPERIENCE = 2
    VITAL_VALUES = 3


class GameQuest:
    """
    Represents a quest in the game with progress tracking and rewards.
    """
    
    def __init__(self, quest_id: str, name: str, module: str, quest_type: QuestType, 
                 target_amount: int, reward_type: RewardType, reward_value: str, 
                 reward_quantity: int, date_obtained: datetime = None):
        self.id = quest_id
        self.name = name
        self.module = module
        self.type = quest_type
        self.target_amount = target_amount
        self.current_amount = 0
        self.status = QuestStatus.PENDING
        self.date_obtained = date_obtained or datetime.now()
        self.reward_type = reward_type
        self.reward_value = reward_value
        self.reward_quantity = reward_quantity
    
    def update_progress(self, amount: int = 1) -> bool:
        """
        Updates quest progress and returns True if quest is completed.
        """
        if self.status != QuestStatus.PENDING:
            return False
            
        self.current_amount += amount
        
        if self.current_amount >= self.target_amount:
            self.status = QuestStatus.SUCCESS
            return True
            
        return False
    
    def is_expired(self, current_date: datetime) -> bool:
        """
        Checks if the quest has expired (older than 1 day).
        """
        return (current_date - self.date_obtained).days >= 1
    
    def get_progress_percentage(self) -> float:
        """
        Returns progress as a percentage (0.0 to 1.0).
        """
        if self.target_amount == 0:
            return 1.0
        return min(self.current_amount / self.target_amount, 1.0)
    
    def __str__(self) -> str:
        return f"{self.name} ({self.current_amount}/{self.target_amount}) - {self.status.name}"
