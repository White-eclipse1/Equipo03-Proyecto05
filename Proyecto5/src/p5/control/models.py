from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class Action(StrEnum):
    STOP = "stop"
    FORWARD = "forward"
    LEFT = "left"
    RIGHT = "right"


@dataclass(frozen=True)
class ControlDecision:
    action: Action
    requested_speed: float
    frame_id: str
    decision_id: str
    reason_code: str


@dataclass(frozen=True)
class ControlCommand:
    speed: float
    direction: Literal["stop", "forward", "left", "right"]
    steering: float
    timestamp: float
    frame_id: str
    decision_id: str
    reason_code: str
