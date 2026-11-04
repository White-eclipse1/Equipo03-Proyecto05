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
    # En [-1, 1], negativo = izquierda. None usa el giro completo de la accion.
    requested_steering: float | None = None
    # Vigencia en el reloj de la secuencia (`t_capture_ms`). None no vence.
    valid_until_ms: float | None = None


@dataclass(frozen=True)
class ControlCommand:
    speed: float
    direction: Literal["stop", "forward", "left", "right"]
    steering: float
    timestamp: float
    frame_id: str
    decision_id: str
    reason_code: str
    # A partir de este instante, un comando de movimiento vale como STOP. None no vence.
    valid_until_ms: float | None = None
