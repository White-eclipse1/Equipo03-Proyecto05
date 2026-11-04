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
    # Tiempo relativo de captura recibido desde la politica B1.
    t_capture_ms: float | None = None
    # Instante hasta el que un comando de movimiento sigue siendo valido.
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
    valid_until_ms: float | None = None
