import json
import logging
from pathlib import Path

import numpy as np
import pytest
from p3.policy.config import cargar_config
from p3.policy.politica import PoliticaDecision

from p5.control.adapter import VirtualControlAdapter
from p5.control.models import Action, ControlDecision
from p5.integration.pipeline import FrameInput, Pipeline

CONFIG = Path(__file__).resolve().parents[2] / "Proyecto3" / "config" / "politica.yaml"
PERIOD_MS = 100.0
VALIDITY_MS = 500.0


class EmptySceneDetector:
    def __init__(self):
        self.reads = []

    def read_image(self, source):
        self.reads.append(source)
        return np.zeros((296, 400, 3), dtype=np.uint8)

    def detect_image(self, image, *, source):
        return ()


def frame(number, t_ms=None):
    return FrameInput(
        sequence_id="seq",
        frame_id=f"seq-{number:04d}",
        t_capture_ms=number * PERIOD_MS if t_ms is None else t_ms,
        image_size=(400, 296),
        image_path=Path(f"seq-{number:04d}.jpg"),
    )


def make_pipeline(adapter=None, detector=None):
    config, sha = cargar_config(CONFIG)
    return Pipeline(
        detector or EmptySceneDetector(),
        PoliticaDecision(config, config_sha256=sha),
        adapter or VirtualControlAdapter(),
    )


def moving_pipeline(**kwargs):
    """Avanzando: la politica confirma la via en el tercer cuadro libre."""
    pipeline = make_pipeline(**kwargs)
    for number in range(1, 4):
        trace = pipeline.process(frame(number))
    assert trace.command["direction"] == "forward"
    return pipeline


def forward(valid_until_ms=None):
    return ControlDecision(
        action=Action.FORWARD,
        requested_speed=0.6,
        frame_id="f-1",
        decision_id="d-1",
        reason_code="VIA_LIBRE",
        valid_until_ms=valid_until_ms,
    )


# Adaptador


def test_command_records_when_it_expires():
    command = VirtualControlAdapter().apply(forward(valid_until_ms=800.0))

    assert command.valid_until_ms == 800.0


def test_stop_never_expires():
    adapter = VirtualControlAdapter()

    command = adapter.apply(
        ControlDecision(
            action=Action.STOP,
            requested_speed=0.0,
            frame_id="f-1",
            decision_id="d-1",
            reason_code="stop",
            valid_until_ms=800.0,
        )
    )

    assert command.valid_until_ms is None
    assert adapter.is_expired(10_000.0) is False


@pytest.mark.parametrize(
    ("now_ms", "expired"),
    [(799.0, False), (800.0, True), (801.0, True)],
)
def test_motion_expires_exactly_at_its_limit(now_ms, expired):
    adapter = VirtualControlAdapter()
    adapter.apply(forward(valid_until_ms=800.0))

    assert adapter.is_expired(now_ms) is expired


def test_nothing_expires_without_a_command():
    assert VirtualControlAdapter().is_expired(10_000.0) is False


def test_motion_without_a_limit_does_not_expire():
    adapter = VirtualControlAdapter()
    adapter.apply(forward())

    assert adapter.is_expired(10_000.0) is False


@pytest.mark.parametrize("now_ms", [float("nan"), float("inf")])
def test_an_invalid_clock_counts_as_expired(now_ms):
    adapter = VirtualControlAdapter()
    adapter.apply(forward(valid_until_ms=800.0))

    assert adapter.is_expired(now_ms) is True


@pytest.mark.parametrize("limit", [float("nan"), float("inf")])
def test_invalid_limit_is_rejected(limit):
    adapter = VirtualControlAdapter()

    with pytest.raises(ValueError, match="valid_until_ms"):
        adapter.apply(forward(valid_until_ms=limit))

    assert adapter.last_command is None


def test_adapter_clock_can_be_controlled():
    adapter = VirtualControlAdapter(clock=lambda: 123.0)

    assert adapter.apply(forward()).timestamp == 123.0


# Watchdog: C8, primera parte


def test_command_from_the_pipeline_carries_the_policy_limit():
    pipeline = moving_pipeline()

    command = pipeline.adapter.last_command

    assert command.valid_until_ms == 3 * PERIOD_MS + VALIDITY_MS


def test_nothing_happens_before_the_limit():
    pipeline = moving_pipeline()

    assert pipeline.tick(3 * PERIOD_MS + VALIDITY_MS - 1) is None
    assert pipeline.adapter.last_command.direction == "forward"


def test_watchdog_stops_without_a_new_frame(caplog):
    detector = EmptySceneDetector()
    pipeline = moving_pipeline(detector=detector)
    reads = len(detector.reads)
    limit = 3 * PERIOD_MS + VALIDITY_MS

    with caplog.at_level(logging.WARNING):
        event = pipeline.tick(limit)

    # El STOP llega al adaptador, y no hizo falta ningun cuadro.
    assert len(detector.reads) == reads
    command = pipeline.adapter.last_command
    assert command.direction == "stop"
    assert command.speed == 0.0
    assert command.reason_code == "WATCHDOG_VENCIDO"
    assert pipeline.adapter.history[-1] == command
    # El evento queda registrado.
    assert event.t_ms == limit
    assert event.expired_frame_id == "seq-0003"
    assert event.valid_until_ms == limit
    assert event.command["reason_code"] == "WATCHDOG_VENCIDO"
    assert event.errors == ()
    assert "watchdog_expired" in caplog.text
    assert json.loads(event.to_json())["expired_frame_id"] == "seq-0003"


def test_watchdog_only_fires_once():
    pipeline = moving_pipeline()
    limit = 3 * PERIOD_MS + VALIDITY_MS

    assert pipeline.tick(limit) is not None
    stops = len(pipeline.adapter.history)

    assert pipeline.tick(limit + 1000) is None
    assert len(pipeline.adapter.history) == stops


def test_road_must_be_confirmed_again_after_the_watchdog():
    pipeline = moving_pipeline()
    limit = 3 * PERIOD_MS + VALIDITY_MS
    pipeline.tick(limit)

    directions = [
        pipeline.process(frame(number, limit + (number - 3) * PERIOD_MS)).command["direction"]
        for number in range(4, 7)
    ]

    assert directions == ["stop", "stop", "forward"]


def test_watchdog_with_a_failed_stop_keeps_the_path_halted():
    class BrokenAdapter(VirtualControlAdapter):
        broken = False

        def apply(self, decision):
            if self.broken:
                raise RuntimeError("adaptador caido")
            return super().apply(decision)

    adapter = BrokenAdapter()
    pipeline = moving_pipeline(adapter=adapter)
    adapter.broken = True

    event = pipeline.tick(3 * PERIOD_MS + VALIDITY_MS)

    assert pipeline.halted is True
    assert adapter.last_command is None
    assert event.command["reason_code"] == "STOP_NO_EMITIDO"
    assert [error["stage"] for error in event.errors] == ["failsafe"]


def test_invalid_clock_stops_the_motion():
    pipeline = moving_pipeline()

    event = pipeline.tick(float("nan"))

    assert pipeline.adapter.last_command.direction == "stop"
    assert event.t_ms is None
    assert json.loads(event.to_json())["t_ms"] is None


# Cuadro vencido: C8, segunda parte


@pytest.mark.parametrize(
    ("age_ms", "stale"),
    [(VALIDITY_MS - 1, False), (VALIDITY_MS, True), (VALIDITY_MS + 1, True)],
)
def test_frame_expires_exactly_at_the_limit(age_ms, stale):
    pipeline = moving_pipeline()

    trace = pipeline.process(frame(4), now_ms=frame(4).t_capture_ms + age_ms)

    assert (trace.command["reason_code"] == "CUADRO_VENCIDO") is stale
    assert ("stale" in [error["stage"] for error in trace.errors]) is stale


def test_stale_frame_is_rejected_and_cancels_motion(caplog):
    detector = EmptySceneDetector()
    pipeline = moving_pipeline(detector=detector)
    reads = len(detector.reads)

    with caplog.at_level(logging.ERROR):
        trace = pipeline.process(frame(4), now_ms=frame(4).t_capture_ms + VALIDITY_MS)

    # Datos viejos: ni siquiera se le pasan al detector.
    assert len(detector.reads) == reads
    assert trace.decision is None
    assert trace.perception["status"] == "error"
    assert trace.perception["detections"] == []
    assert trace.command["direction"] == "stop"
    assert pipeline.adapter.last_command.direction == "stop"
    assert "stage=stale" in caplog.text
    assert json.loads(trace.to_json())["frame_id"] == "seq-0004"


def test_stale_frame_does_not_restart_motion_and_needs_confirmation():
    pipeline = moving_pipeline()
    now = frame(4).t_capture_ms + VALIDITY_MS
    pipeline.process(frame(4), now_ms=now)

    directions = [
        pipeline.process(frame(number, now + number), now_ms=now + number).command["direction"]
        for number in range(5, 8)
    ]

    assert directions == ["stop", "stop", "forward"]


def test_frame_without_a_clock_keeps_working_as_before():
    pipeline = moving_pipeline()

    trace = pipeline.process(frame(4))

    assert trace.command["direction"] == "forward"
    assert trace.errors == ()


def test_invalid_clock_rejects_the_frame():
    pipeline = moving_pipeline()

    trace = pipeline.process(frame(4), now_ms=float("nan"))

    assert trace.command["reason_code"] == "CUADRO_VENCIDO"
    assert json.loads(trace.to_json())["errors"][0]["stage"] == "stale"


# C8 completo y reproducible


def run_c8():
    pipeline = moving_pipeline()
    limit = 3 * PERIOD_MS + VALIDITY_MS
    before = pipeline.tick(limit - 1)
    event = pipeline.tick(limit)
    # Llega un cuadro capturado justo una vigencia antes, que ya no vale.
    stale = pipeline.process(frame(4, t_ms=limit - VALIDITY_MS), now_ms=limit)
    return (
        before,
        event.command["reason_code"],
        stale.command["reason_code"],
        [
            (c.direction, c.speed, c.reason_code, c.frame_id, c.valid_until_ms)
            for c in pipeline.adapter.history
        ],
    )


def test_c8_is_reproducible():
    first = run_c8()

    assert first == run_c8()
    before, event_reason, stale_reason, history = first
    assert before is None
    assert event_reason == "WATCHDOG_VENCIDO"
    assert stale_reason == "CUADRO_VENCIDO"
    assert history[-1][0] == "stop"
    assert "forward" not in [entry[0] for entry in history[-2:]]
