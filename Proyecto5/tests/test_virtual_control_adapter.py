import logging

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


def test_negative_speed_is_never_sent():
    decision = ControlDecision(
        action=Action.FORWARD,
        requested_speed=-1.0,
        frame_id="frame-007",
        decision_id="decision-007",
        reason_code="invalid_speed",
    )

    adapter = VirtualControlAdapter()

    command = adapter.apply(decision)

    assert command.speed == 0.0


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
