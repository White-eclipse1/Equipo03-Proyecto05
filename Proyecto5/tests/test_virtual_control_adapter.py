import logging

import pytest

from p5.control.adapter import VirtualControlAdapter
from p5.control.models import Action, ControlDecision


def test_stop_forces_zero_speed():
    decision = ControlDecision(
        action=Action.STOP,
        requested_speed=0.8,
        frame_id="frame-001",
        decision_id="decision-001",
        reason_code="obstacle",
    )

    adapter = VirtualControlAdapter()

    command = adapter.apply(decision)

    assert command.speed == 0.0
    assert command.direction == "stop"
    assert command.steering == 0.0
    assert command.frame_id == "frame-001"
    assert command.decision_id == "decision-001"


def test_forward_uses_requested_speed():
    decision = ControlDecision(
        action=Action.FORWARD,
        requested_speed=0.6,
        frame_id="frame-002",
        decision_id="decision-002",
        reason_code="clear_path",
    )

    adapter = VirtualControlAdapter()

    command = adapter.apply(decision)

    assert command.speed == 0.6
    assert command.direction == "forward"
    assert command.steering == 0.0


def test_left_and_right_generate_expected_steering():
    adapter = VirtualControlAdapter()

    left = adapter.apply(
        ControlDecision(
            action=Action.LEFT,
            requested_speed=0.4,
            frame_id="frame-003",
            decision_id="decision-003",
            reason_code="avoid_right_obstacle",
        )
    )

    right = adapter.apply(
        ControlDecision(
            action=Action.RIGHT,
            requested_speed=0.4,
            frame_id="frame-004",
            decision_id="decision-004",
            reason_code="avoid_left_obstacle",
        )
    )

    assert left.steering == -1.0
    assert right.steering == 1.0


@pytest.mark.parametrize(
    ("action", "requested"),
    [(Action.LEFT, -0.5), (Action.RIGHT, 0.5), (Action.RIGHT, 1.0), (Action.FORWARD, 0.0)],
)
def test_requested_steering_is_respected(action, requested):
    command = VirtualControlAdapter().apply(
        ControlDecision(
            action=action,
            requested_speed=0.2,
            frame_id="frame-010",
            decision_id="decision-010",
            reason_code="evade",
            requested_steering=requested,
        )
    )

    assert command.steering == requested


@pytest.mark.parametrize(
    ("action", "requested"),
    [
        (Action.RIGHT, 1.5),
        (Action.LEFT, -1.5),
        (Action.RIGHT, float("nan")),
        (Action.LEFT, float("inf")),
        (Action.LEFT, 0.5),
        (Action.RIGHT, -0.5),
        (Action.RIGHT, 0.0),
        (Action.FORWARD, 0.5),
    ],
)
def test_invalid_requested_steering_is_rejected(action, requested):
    adapter = VirtualControlAdapter()

    with pytest.raises(ValueError):
        adapter.apply(
            ControlDecision(
                action=action,
                requested_speed=0.2,
                frame_id="frame-011",
                decision_id="decision-011",
                reason_code="evade",
                requested_steering=requested,
            )
        )

    assert adapter.last_command is None


def test_cancel_clears_the_active_command():
    adapter = VirtualControlAdapter()
    adapter.apply(
        ControlDecision(
            action=Action.FORWARD,
            requested_speed=0.5,
            frame_id="frame-013",
            decision_id="decision-013",
            reason_code="clear",
        )
    )

    adapter.cancel()

    assert adapter.last_command is None
    assert len(adapter.history) == 1


def test_stop_ignores_requested_steering():
    command = VirtualControlAdapter().apply(
        ControlDecision(
            action=Action.STOP,
            requested_speed=0.0,
            frame_id="frame-012",
            decision_id="decision-012",
            reason_code="stop",
            requested_steering=0.5,
        )
    )

    assert command.steering == 0.0


def test_stop_cancels_previous_motion_command():
    adapter = VirtualControlAdapter()

    adapter.apply(
        ControlDecision(
            action=Action.FORWARD,
            requested_speed=0.8,
            frame_id="frame-005",
            decision_id="decision-005",
            reason_code="clear_path",
        )
    )

    stop = adapter.apply(
        ControlDecision(
            action=Action.STOP,
            requested_speed=0.8,
            frame_id="frame-006",
            decision_id="decision-006",
            reason_code="obstacle",
        )
    )

    assert adapter.last_command == stop
    assert adapter.last_command.speed == 0.0
    assert adapter.last_command.direction == "stop"


@pytest.mark.parametrize(
    "invalid_speed",
    [
        -0.1,
        1.1,
        float("nan"),
        float("inf"),
        float("-inf"),
    ],
)
def test_invalid_motion_speed_is_rejected(invalid_speed):
    adapter = VirtualControlAdapter()

    decision = ControlDecision(
        action=Action.FORWARD,
        requested_speed=invalid_speed,
        frame_id="frame-invalid",
        decision_id="decision-invalid",
        reason_code="invalid_speed",
    )

    with pytest.raises(ValueError, match="requested_speed"):
        adapter.apply(decision)


@pytest.mark.parametrize("valid_speed", [0.0, 1.0])
def test_speed_boundaries_are_valid(valid_speed):
    adapter = VirtualControlAdapter()

    command = adapter.apply(
        ControlDecision(
            action=Action.FORWARD,
            requested_speed=valid_speed,
            frame_id="frame-boundary",
            decision_id="decision-boundary",
            reason_code="valid_speed",
        )
    )

    assert command.speed == valid_speed


def test_commands_are_recorded_in_history():
    adapter = VirtualControlAdapter()

    first = adapter.apply(
        ControlDecision(
            action=Action.FORWARD,
            requested_speed=0.5,
            frame_id="frame-008",
            decision_id="decision-008",
            reason_code="clear_path",
        )
    )

    second = adapter.apply(
        ControlDecision(
            action=Action.STOP,
            requested_speed=0.5,
            frame_id="frame-009",
            decision_id="decision-009",
            reason_code="obstacle",
        )
    )

    assert adapter.history == (first, second)
    assert adapter.history[-1].speed == 0.0


def test_command_contains_valid_timestamp():
    adapter = VirtualControlAdapter()

    command = adapter.apply(
        ControlDecision(
            action=Action.FORWARD,
            requested_speed=0.5,
            frame_id="frame-010",
            decision_id="decision-010",
            reason_code="clear_path",
        )
    )

    assert command.timestamp > 0


def test_physical_motors_are_disabled_by_default():
    adapter = VirtualControlAdapter()

    assert adapter.physical_output_enabled is False


def test_generated_command_is_logged(caplog):
    adapter = VirtualControlAdapter()

    with caplog.at_level(logging.INFO):
        adapter.apply(
            ControlDecision(
                action=Action.STOP,
                requested_speed=0.7,
                frame_id="frame-011",
                decision_id="decision-011",
                reason_code="safety_stop",
            )
        )

    assert "virtual_control_command" in caplog.text
    assert "decision-011" in caplog.text
