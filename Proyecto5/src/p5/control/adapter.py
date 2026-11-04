import logging
from collections.abc import Callable
from math import isfinite
from time import time

from p5.control.models import Action, ControlCommand, ControlDecision

logger = logging.getLogger(__name__)


class VirtualControlAdapter:
    physical_output_enabled = False

    def __init__(self, clock: Callable[[], float] = time) -> None:
        self._clock = clock
        self._last_command: ControlCommand | None = None
        self._history: list[ControlCommand] = []
        self._cancelled: list[ControlCommand] = []

    @property
    def last_command(self) -> ControlCommand | None:
        return self._last_command

    @property
    def history(self) -> tuple[ControlCommand, ...]:
        return tuple(self._history)

    @property
    def cancelled(self) -> tuple[ControlCommand, ...]:
        """Comandos anulados por `cancel`. El historial solo tiene comandos emitidos."""
        return tuple(self._cancelled)

    def apply(self, decision: ControlDecision) -> ControlCommand:
        if decision.action == Action.STOP:
            command = ControlCommand(
                speed=0.0,
                direction="stop",
                steering=0.0,
                timestamp=self._clock(),
                frame_id=decision.frame_id,
                decision_id=decision.decision_id,
                reason_code=decision.reason_code,
            )
            return self._record(command)

        self._validate_speed(decision.requested_speed)
        self._validate_limit(decision.valid_until_ms)

        command = ControlCommand(
            speed=decision.requested_speed,
            direction=decision.action.value,
            steering=self._resolve_steering(decision),
            timestamp=self._clock(),
            frame_id=decision.frame_id,
            decision_id=decision.decision_id,
            reason_code=decision.reason_code,
            valid_until_ms=decision.valid_until_ms,
        )

        return self._record(command)

    def is_expired(self, now_ms: float) -> bool:
        """Dice si el comando de movimiento vigente ya vencio. No depende de un cuadro nuevo.

        Un reloj no finito cuenta como vencido: sin hora confiable, lo seguro es detenerse.
        """
        command = self._last_command
        if command is None or command.direction == "stop" or command.valid_until_ms is None:
            return False
        return not isfinite(now_ms) or now_ms >= command.valid_until_ms

    def cancel(self) -> None:
        """Anula el comando vigente sin generar otro, si un STOP no se pudo emitir."""
        command = self._last_command
        self._last_command = None
        if command is None:
            return
        self._cancelled.append(command)
        logger.warning(
            "virtual_control_cancel direction=%s frame_id=%s decision_id=%s",
            command.direction,
            command.frame_id,
            command.decision_id,
        )

    def _record(self, command: ControlCommand) -> ControlCommand:
        self._last_command = command
        self._history.append(command)

        logger.info(
            "virtual_control_command direction=%s speed=%.3f steering=%.3f "
            "frame_id=%s decision_id=%s reason_code=%s",
            command.direction,
            command.speed,
            command.steering,
            command.frame_id,
            command.decision_id,
            command.reason_code,
        )

        return command

    @staticmethod
    def _validate_speed(speed: float) -> None:
        if not isfinite(speed) or not 0.0 <= speed <= 1.0:
            raise ValueError("requested_speed must be finite and between 0.0 and 1.0")

    @staticmethod
    def _validate_limit(valid_until_ms: float | None) -> None:
        if valid_until_ms is not None and not isfinite(valid_until_ms):
            raise ValueError("valid_until_ms must be finite")

    @classmethod
    def _resolve_steering(cls, decision: ControlDecision) -> float:
        steering = decision.requested_steering
        if steering is None:
            return cls._steering_for(decision.action)
        if not isfinite(steering) or not -1.0 <= steering <= 1.0:
            raise ValueError("requested_steering must be finite and between -1.0 and 1.0")
        expected = cls._steering_for(decision.action)
        if (steering > 0) - (steering < 0) != (expected > 0) - (expected < 0):
            raise ValueError("requested_steering does not match the action direction")
        return steering

    @staticmethod
    def _steering_for(action: Action) -> float:
        if action == Action.LEFT:
            return -1.0
        if action == Action.RIGHT:
            return 1.0
        return 0.0
