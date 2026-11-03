import logging
from time import time

from p5.control.models import Action, ControlCommand, ControlDecision

logger = logging.getLogger(__name__)


class VirtualControlAdapter:
    physical_output_enabled = False

    def __init__(self) -> None:
        self._last_command: ControlCommand | None = None
        self._history: list[ControlCommand] = []

    @property
    def last_command(self) -> ControlCommand | None:
        return self._last_command

    @property
    def history(self) -> tuple[ControlCommand, ...]:
        return tuple(self._history)

    def apply(self, decision: ControlDecision) -> ControlCommand:
        if decision.action == Action.STOP:
            command = ControlCommand(
                speed=0.0,
                direction="stop",
                steering=0.0,
                timestamp=time(),
                frame_id=decision.frame_id,
                decision_id=decision.decision_id,
                reason_code=decision.reason_code,
            )
            return self._record(command)

        command = ControlCommand(
            speed=max(0.0, decision.requested_speed),
            direction=decision.action.value,
            steering=self._steering_for(decision.action),
            timestamp=time(),
            frame_id=decision.frame_id,
            decision_id=decision.decision_id,
            reason_code=decision.reason_code,
        )

        return self._record(command)

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
    def _steering_for(action: Action) -> float:
        if action == Action.LEFT:
            return -1.0
        if action == Action.RIGHT:
            return 1.0
        return 0.0
