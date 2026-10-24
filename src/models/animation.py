# Enums for defining frames and animations
from enum import Enum


class PetFrame(Enum):
    IDLE1 = 0
    IDLE2 = 1
    HAPPY = 2
    ANGRY = 3
    TRAIN1 = 4
    TRAIN2 = 5
    ATK1 = 6
    ATK2 = 7
    EAT1 = 8
    EAT2 = 9
    NOPE = 10
    #EXTRA = 11
    NAP1 = 11
    NAP2 = 12
    SICK = 13
    LOSE = 14
    SPECIAL = 15

#: The frame drawn instead when a set lacks one: a Mode Change or DigiXros
#: form has only the frames its device's battle shows (DMXW's Superior Modes
#: have no ANGRY), and a missing frame used to stop the battle (owner,
#: 2026-10-15: such forms need only the frames battle references).
FRAME_FALLBACKS = {
    PetFrame.IDLE2.value: (PetFrame.IDLE1.value,),
    PetFrame.HAPPY.value: (PetFrame.IDLE2.value, PetFrame.IDLE1.value),
    PetFrame.ANGRY.value: (PetFrame.IDLE2.value, PetFrame.IDLE1.value),
    PetFrame.TRAIN1.value: (PetFrame.ATK1.value, PetFrame.ATK2.value, PetFrame.IDLE1.value),
    PetFrame.TRAIN2.value: (PetFrame.ATK2.value, PetFrame.ATK1.value, PetFrame.IDLE1.value),
    PetFrame.ATK1.value: (PetFrame.ATK2.value, PetFrame.ANGRY.value, PetFrame.IDLE1.value),
    PetFrame.ATK2.value: (PetFrame.ATK1.value, PetFrame.ANGRY.value, PetFrame.IDLE1.value),
    PetFrame.LOSE.value: (PetFrame.SICK.value, PetFrame.IDLE1.value),
}


def frame_or_fallback(get, index):
    """``get(index)``, else the first frame of FRAME_FALLBACKS[index] the set
    has, else IDLE1; None only when the set has none of them."""
    frame = get(index)
    if frame is not None:
        return frame
    for other in FRAME_FALLBACKS.get(index, (PetFrame.IDLE1.value,)):
        frame = get(other)
        if frame is not None:
            return frame
    return get(PetFrame.IDLE1.value) if index != PetFrame.IDLE1.value else None


class EggFrame(Enum):
    IDLE1, IDLE2, HATCH, DEAD = range(4)

class Animation:
    HATCH = [PetFrame.HAPPY]
    IDLE = [PetFrame.IDLE1, PetFrame.IDLE2]
    MOVING = [PetFrame.IDLE1, PetFrame.IDLE2]
    HAPPY = [PetFrame.HAPPY, PetFrame.IDLE1]
    HAPPY2 = [PetFrame.HAPPY, PetFrame.IDLE1]
    HAPPY3 = [PetFrame.HAPPY, PetFrame.IDLE1]
    NOPE = [PetFrame.NOPE, PetFrame.NOPE]
    ANGRY = [PetFrame.ANGRY, PetFrame.IDLE1]
    TRAIN = [PetFrame.TRAIN1, PetFrame.TRAIN2]
    ATTACK = [PetFrame.ATK1, PetFrame.ATK2]
    EAT = [PetFrame.EAT1, PetFrame.EAT2]
    NAP = [PetFrame.NAP1, PetFrame.NAP2]
    TIRED = [PetFrame.NAP1, PetFrame.NAP2]
    SICK = [PetFrame.SICK, PetFrame.ANGRY]
    POOPING = [PetFrame.SICK, PetFrame.SICK]
    LOSE = [PetFrame.LOSE, PetFrame.ANGRY]
    DYING = [PetFrame.LOSE, PetFrame.LOSE]
    SPECIAL = [PetFrame.SPECIAL, PetFrame.SPECIAL]