import importlib.metadata
import json
import logging
import subprocess
import sys
from dataclasses import fields, replace
from pathlib import Path

import numpy as np
import pytest
from p3.policy.config import cargar_config
from p3.policy.politica import PoliticaDecision

from dataset_helpers import make_valid_dataset
from p5.control.adapter import VirtualControlAdapter
from p5.control.models import Action
from p5.dataset.paquete import freeze
from p5.detector.yolox import DetectorError, YoloxDetector
from p5.integration import __main__ as cli
from p5.integration import pipeline as pipeline_module
from p5.integration.pipeline import (
    FAILSAFE_REASON,
    STOP_NOT_EMITTED_REASON,
    FrameInput,
    Pipeline,
    frames_from_manifest,
    to_control_decision,
)
from test_detector import PERSON, FakeSession, raw_output, write_png

POLICY_CONFIG = Path(__file__).resolve().parents[1] / "config" / "politica.yaml"
# Persona con confianza 0.9, en el tercio central de la imagen de 416x416.
CENTER = raw_output((0, 208, 300, 100, 200, 1.0, PERSON, 0.9))
CLEAR = raw_output()


class ScriptedSession(FakeSession):
    """Una salida cruda distinta del modelo en cada corrida."""

    def __init__(self, raws):
        super().__init__()
        self.raws = iter(raws)

    def run(self, _outputs, feeds):
        self.tensors.append(feeds["images"])
        return [next(self.raws).copy()]


def policy():
    config, sha256 = cargar_config(POLICY_CONFIG)
    return PoliticaDecision(config, sha256)


def make_pipeline(session):
    return Pipeline(YoloxDetector(session), policy(), VirtualControlAdapter())


def image_file(tmp_path):
    return write_png(tmp_path / "frame.png", np.zeros((416, 416, 3), dtype=np.uint8))


def frame_input(image, index=0, **overrides):
    values = {
        "sequence_id": "seq01",
        "frame_id": f"seq01-{index:04d}",
        "t_capture_ms": index * 500.0,
        "image_size": (416, 416),
        "image_path": image,
    }
    return FrameInput(**{**values, **overrides})


def run(pipeline, image, count, first=0):
    return [pipeline.process(frame_input(image, first + i)) for i in range(count)]


def test_the_same_frame_is_traceable_through_every_stage(tmp_path):
    image = image_file(tmp_path)
    trace = make_pipeline(FakeSession(CENTER)).process(frame_input(image, 3))

    assert trace.frame_id == "seq01-0003"
    assert trace.perception["frame_id"] == "seq01-0003"
    assert trace.decision["frame_id"] == "seq01-0003"
    assert trace.command["frame_id"] == "seq01-0003"
    assert trace.command["decision_id"] == "seq01:seq01-0003"
    assert trace.sequence_id == trace.perception["sequence_id"] == trace.decision["sequence_id"]
    assert trace.t_capture_ms == 1500
    assert trace.perception["t_capture_ms"] == 1500
    assert trace.decision["t_capture_ms"] == 1500
    assert trace.command["timestamp"] > 0
    assert trace.image == str(image)
    assert trace.errors == ()


def test_real_detections_reach_the_policy_decision(tmp_path):
    trace = make_pipeline(FakeSession(CENTER)).process(frame_input(image_file(tmp_path)))

    assert trace.perception["status"] == "ok"
    assert trace.perception["detections"][0]["class_name"] == "person"
    evaluated = trace.decision["detecciones"][0]
    assert evaluated["class_name"] == "person"
    assert evaluated["nivel"] == "firme"
    assert "centro" in evaluated["zonas"]


def test_the_image_decides_the_command_across_a_sequence(tmp_path):
    session = ScriptedSession([CLEAR] * 3 + [CENTER])
    pipeline = make_pipeline(session)

    traces = run(pipeline, image_file(tmp_path), 4)

    assert [t.decision["accion"] for t in traces] == ["STOP", "STOP", "FORWARD", "SLOW"]
    assert [t.decision["estado"] for t in traces] == ["UNKNOWN", "UNKNOWN", "CLEAR", "CAUTION"]
    assert [t.command["direction"] for t in traces] == ["stop", "stop", "forward", "forward"]
    assert [t.command["speed"] for t in traces] == [0.0, 0.0, 0.6, 0.3]
    assert len(session.tensors) == 4
    assert len(pipeline.adapter.history) == 4


def test_evasion_keeps_the_steering_requested_by_the_policy(tmp_path):
    session = ScriptedSession([CLEAR] * 3 + [CENTER] * 2)

    last = run(make_pipeline(session), image_file(tmp_path), 5)[-1]

    assert last.decision["accion"] == "EVADE_RIGHT"
    assert last.decision["direccion"] == 0.5
    assert last.command["direction"] == "right"
    assert last.command["steering"] == 0.5
    assert last.command["speed"] == 0.2


def test_pipeline_logs_state_transitions_matching_the_persisted_trace(tmp_path, caplog):
    session = ScriptedSession([CLEAR] * 3 + [CENTER] * 2 + [CLEAR] * 3)
    with caplog.at_level(logging.INFO, logger="p5.policy.events"):
        traces = run(make_pipeline(session), image_file(tmp_path), 8)

    changes = [t.decision for t in traces if t.decision["cambio_estado"]]
    events = [r.policy_transition for r in caplog.records if hasattr(r, "policy_transition")]
    assert [e["frame_id"] for e in events] == [d["frame_id"] for d in changes]
    assert [(e["estado_anterior"], e["estado"]) for e in events] == [
        ("UNKNOWN", "CLEAR"),
        ("CLEAR", "CAUTION"),
        ("CAUTION", "BLOCKED"),
        ("BLOCKED", "CLEAR"),
    ]
    assert all(e["reason_code"] and e["razon"] for e in events)


def test_every_trace_serializes_to_strict_json(tmp_path):
    trace = make_pipeline(FakeSession(CENTER)).process(frame_input(image_file(tmp_path)))

    payload = json.loads(trace.to_json())

    assert set(payload) == {
        "sequence_id",
        "frame_id",
        "t_capture_ms",
        "image",
        "perception",
        "decision",
        "command",
        "errors",
    }
    assert payload["decision"]["reason_code"] == trace.decision["reason_code"]


@pytest.mark.parametrize(
    ("accion", "action"),
    [
        ("STOP", Action.STOP),
        ("FORWARD", Action.FORWARD),
        ("SLOW", Action.FORWARD),
        ("EVADE_LEFT", Action.LEFT),
        ("EVADE_RIGHT", Action.RIGHT),
    ],
)
def test_every_policy_action_has_an_adapter_action(tmp_path, accion, action):
    decision = (
        policy()
        .decidir_crudo(
            {
                "sequence_id": "s",
                "frame_id": "f",
                "t_capture_ms": 0,
                "image_width": 10,
                "image_height": 10,
                "status": "ok",
                "detections": [],
            }
        )
        .model_copy(update={"accion": accion})
    )

    control = to_control_decision(decision, frame_id="f", decision_id="s:f")

    assert control.action is action
    assert control.requested_speed == decision.velocidad
    assert control.requested_steering == decision.direccion
    assert control.reason_code == decision.reason_code


def test_unreadable_image_stops_and_cancels_previous_motion(tmp_path, caplog):
    image = image_file(tmp_path)
    pipeline = make_pipeline(ScriptedSession([CLEAR] * 3))
    assert run(pipeline, image, 3)[-1].command["direction"] == "forward"

    with caplog.at_level(logging.ERROR):
        trace = pipeline.process(frame_input(tmp_path / "missing.png", 3))

    assert trace.perception["status"] == "error"
    assert trace.decision["estado"] == "FAULT"
    assert trace.decision["reason_code"] == "ERROR_PERCEPCION"
    assert trace.command["direction"] == "stop"
    assert trace.command["speed"] == 0.0
    assert [error["stage"] for error in trace.errors] == ["detector"]
    assert "integration_error stage=detector frame_id=seq01-0003" in caplog.text


def test_inference_failure_stops_and_needs_confirmation_again(tmp_path):
    image = image_file(tmp_path)
    session = ScriptedSession([CLEAR] * 3)
    pipeline = make_pipeline(session)
    run(pipeline, image, 3)

    session.raws = iter(())  # La siguiente inferencia lanza StopIteration.
    failed = pipeline.process(frame_input(image, 3))
    assert failed.command["direction"] == "stop"
    assert failed.decision["estado"] == "FAULT"
    assert [error["stage"] for error in failed.errors] == ["detector"]

    session.raws = iter([CLEAR])
    recovered = pipeline.process(frame_input(image, 4))
    assert recovered.command["direction"] == "stop"
    assert recovered.decision["reason_code"] == "PERCEPCION_NO_CONFIRMADA"


def test_unexpected_error_outside_the_detector_contract_stops(tmp_path, monkeypatch, caplog):
    def explode(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(pipeline_module, "detect_frame", explode)

    with caplog.at_level(logging.ERROR):
        trace = make_pipeline(FakeSession()).process(frame_input(image_file(tmp_path)))

    assert trace.perception["status"] == "error"
    assert "boom" in trace.perception["error"]
    assert trace.decision["reason_code"] == "ERROR_PERCEPCION"
    assert trace.command["direction"] == "stop"
    assert trace.errors[0]["stage"] == "detector"
    assert "integration_error stage=detector" in caplog.text


def test_output_outside_the_contract_is_a_fault(tmp_path, monkeypatch):
    real = pipeline_module.detect_frame

    def malformed(*args, **kwargs):
        frame = real(*args, **kwargs)
        # Una caja que sale del cuadro no cumple el contrato A -> B.
        detection = replace(frame.detections[0], bbox_xyxy=(0.0, 0.0, 9999.0, 10.0))
        return replace(frame, detections=(detection,))

    monkeypatch.setattr(pipeline_module, "detect_frame", malformed)

    trace = make_pipeline(FakeSession(CENTER)).process(frame_input(image_file(tmp_path)))

    assert trace.decision["reason_code"] == "SALIDA_MALFORMADA"
    assert trace.command["direction"] == "stop"
    assert trace.errors[0]["stage"] == "contract"


def test_frame_out_of_order_is_rejected_with_stop(tmp_path):
    image = image_file(tmp_path)
    pipeline = make_pipeline(ScriptedSession([CLEAR] * 4))
    assert run(pipeline, image, 3)[-1].command["direction"] == "forward"

    trace = pipeline.process(frame_input(image, 9, t_capture_ms=0.0))

    assert trace.decision["reason_code"] == "CUADRO_FUERA_DE_ORDEN"
    assert trace.command["direction"] == "stop"
    assert trace.errors[0]["stage"] == "policy"


def real_policy(cls):
    config, sha256 = cargar_config(POLICY_CONFIG)
    return cls(config, sha256)


class FailingOncePolicy(PoliticaDecision):
    """Lanza una excepcion en el cuadro indicado y funciona en los demas."""

    fail_at = 0
    calls = 0

    def decidir_crudo(self, data):
        self.calls += 1
        if self.calls - 1 == self.fail_at:
            raise RuntimeError("policy down")
        return super().decidir_crudo(data)


class InvalidSpeedOncePolicy(PoliticaDecision):
    """En el cuadro indicado entrega una velocidad que el adaptador rechaza."""

    fail_at = 0
    calls = 0
    speed = 7.0

    def decidir_crudo(self, data):
        decision = super().decidir_crudo(data)
        self.calls += 1
        if self.calls - 1 == self.fail_at:
            return decision.model_copy(update={"accion": "FORWARD", "velocidad": self.speed})
        return decision


class FailingAdapter(VirtualControlAdapter):
    """Mientras `broken` sea verdadero, ningun comando llega, ni siquiera un STOP."""

    broken = False

    def apply(self, decision):
        if self.broken:
            raise RuntimeError("adapter down")
        return super().apply(decision)


def test_policy_failure_stops_without_a_decision(tmp_path, caplog):
    pipeline = Pipeline(
        YoloxDetector(FakeSession()), real_policy(FailingOncePolicy), VirtualControlAdapter()
    )

    with caplog.at_level(logging.ERROR):
        trace = pipeline.process(frame_input(image_file(tmp_path)))

    assert trace.decision is None
    assert trace.command["direction"] == "stop"
    assert trace.command["reason_code"] == FAILSAFE_REASON
    assert trace.command["frame_id"] == "seq01-0000"
    assert [error["stage"] for error in trace.errors] == ["policy"]
    assert "integration_error stage=policy" in caplog.text


def test_adapter_rejection_still_leaves_a_stop_as_last_command(tmp_path, caplog):
    adapter = VirtualControlAdapter()
    pipeline = Pipeline(YoloxDetector(FakeSession()), real_policy(InvalidSpeedOncePolicy), adapter)

    with caplog.at_level(logging.ERROR):
        trace = pipeline.process(frame_input(image_file(tmp_path)))

    assert trace.command["direction"] == "stop"
    assert trace.command["reason_code"] == FAILSAFE_REASON
    assert adapter.last_command.direction == "stop"
    assert [error["stage"] for error in trace.errors] == ["adapter"]
    assert "integration_error stage=adapter" in caplog.text


@pytest.mark.parametrize("policy_class", [FailingOncePolicy, InvalidSpeedOncePolicy])
def test_failure_needs_the_road_confirmed_again(tmp_path, policy_class):
    image = image_file(tmp_path)
    broken = real_policy(policy_class)
    broken.fail_at = 3
    pipeline = Pipeline(YoloxDetector(FakeSession()), broken, VirtualControlAdapter())

    traces = run(pipeline, image, 7)

    assert traces[2].command["direction"] == "forward"
    assert traces[3].command["direction"] == "stop"
    assert traces[3].errors
    # Tres cuadros libres confirman la via otra vez: el primero no basta para avanzar.
    assert [t.command["direction"] for t in traces[4:]] == ["stop", "stop", "forward"]
    assert traces[4].decision["reason_code"] == "PERCEPCION_NO_CONFIRMADA"
    assert traces[4].decision["estado_anterior"] == "FAULT"


@pytest.mark.parametrize("policy_class", [FailingOncePolicy, InvalidSpeedOncePolicy])
def test_restart_leaves_the_policy_as_a_detector_error_does(tmp_path, policy_class):
    # Si B1 cambia su reinicio por error, esta prueba avisa que el del recorrido quedo distinto.
    image = image_file(tmp_path)

    by_detector = make_pipeline(FakeSession())
    run(by_detector, image, 3)
    by_detector.process(frame_input(tmp_path / "missing.png", 3))

    broken = real_policy(policy_class)
    broken.fail_at = 3
    by_failure = Pipeline(YoloxDetector(FakeSession()), broken, VirtualControlAdapter())
    run(by_failure, image, 4)

    ignored = {"ultimo_t_ms"}
    assert broken.memoria.model_dump(exclude=ignored) == by_detector._policy.memoria.model_dump(
        exclude=ignored
    )


def test_a_failed_stop_cancels_motion_and_keeps_the_path_stopped(tmp_path, caplog):
    image = image_file(tmp_path)
    adapter = FailingAdapter()
    pipeline = Pipeline(YoloxDetector(FakeSession()), policy(), adapter)
    assert run(pipeline, image, 3)[-1].command["direction"] == "forward"

    adapter.broken = True
    with caplog.at_level(logging.WARNING):
        failed = pipeline.process(frame_input(image, 3))

    assert adapter.last_command is None
    assert [c.frame_id for c in adapter.cancelled] == ["seq01-0002"]
    assert adapter.history[-1].direction == "forward"
    assert "virtual_control_cancel" in caplog.text
    assert failed.command["direction"] == "stop"
    assert failed.command["speed"] == 0.0
    assert failed.command["steering"] == 0.0
    assert failed.command["frame_id"] == "seq01-0003"
    # La traza distingue este STOP de uno que el adaptador si recibio.
    assert failed.command["reason_code"] == STOP_NOT_EMITTED_REASON
    assert [error["stage"] for error in failed.errors] == ["adapter", "failsafe"]
    assert "integration_error stage=failsafe" in caplog.text
    assert json.loads(failed.to_json())["command"]["timestamp"] is None

    # Aunque el adaptador se recupere, este recorrido ya no vuelve a moverse.
    adapter.broken = False
    later = run(pipeline, image, 4, first=4)
    assert pipeline.halted is True
    assert [t.command["direction"] for t in later] == ["stop"] * 4
    assert adapter.last_command.direction == "stop"
    assert all(t.errors[-1]["stage"] == "failsafe" for t in later)


def test_non_finite_time_is_reported_and_the_trace_stays_strict_json(tmp_path, caplog):
    image = image_file(tmp_path)
    pipeline = make_pipeline(FakeSession())

    with caplog.at_level(logging.ERROR):
        trace = pipeline.process(frame_input(image, t_capture_ms=float("nan")))

    payload = json.loads(trace.to_json(), parse_constant=pytest.fail)
    assert payload["t_capture_ms"] is None
    assert payload["perception"]["t_capture_ms"] is None
    assert payload["decision"]["reason_code"] == "SALIDA_MALFORMADA"
    assert payload["command"]["direction"] == "stop"
    assert "trace" in [error["stage"] for error in trace.errors]
    assert "integration_error stage=trace" in caplog.text


def test_non_finite_decision_is_stopped_and_reported(tmp_path):
    broken = real_policy(InvalidSpeedOncePolicy)
    broken.speed = float("inf")
    pipeline = Pipeline(YoloxDetector(FakeSession()), broken, VirtualControlAdapter())

    trace = pipeline.process(frame_input(image_file(tmp_path)))

    payload = json.loads(trace.to_json(), parse_constant=pytest.fail)
    assert payload["decision"]["velocidad"] is None
    assert payload["command"]["direction"] == "stop"
    assert [error["stage"] for error in trace.errors] == ["adapter", "trace"]


def test_cli_keeps_going_after_a_non_finite_frame(tmp_path, monkeypatch):
    image = image_file(tmp_path)
    frames = [
        frame_input(image, 0, t_capture_ms=float("nan")),
        frame_input(image, 1),
    ]
    monkeypatch.setattr(cli, "frames_from_manifest", lambda *_a, **_k: frames)
    fake_weights(monkeypatch, FakeSession())
    output = tmp_path / "traza.jsonl"

    code = cli.main(cli_arguments(tmp_path, output))

    assert code == 1
    lines = output.read_text(encoding="utf-8").splitlines()
    payloads = [json.loads(line, parse_constant=pytest.fail) for line in lines]
    assert [p["frame_id"] for p in payloads] == ["seq01-0000", "seq01-0001"]


def test_cli_stops_motion_if_the_trace_cannot_be_written(tmp_path, monkeypatch, caplog):
    image = image_file(tmp_path)
    frames = [frame_input(image, i) for i in range(3)]
    adapters = []

    class RecordedAdapter(VirtualControlAdapter):
        def __init__(self):
            super().__init__()
            adapters.append(self)

    real_to_json = pipeline_module.FrameTrace.to_json

    def failing_to_json(self):
        if self.frame_id == "seq01-0002":
            raise OSError("disk full")
        return real_to_json(self)

    monkeypatch.setattr(pipeline_module.FrameTrace, "to_json", failing_to_json)
    monkeypatch.setattr(cli, "frames_from_manifest", lambda *_a, **_k: frames)
    monkeypatch.setattr(cli, "VirtualControlAdapter", RecordedAdapter)
    fake_weights(monkeypatch, FakeSession())

    with caplog.at_level(logging.ERROR):
        code = cli.main(cli_arguments(tmp_path, tmp_path / "traza.jsonl"))

    assert code == 1
    assert "integration_error stage=output" in caplog.text

    # El fallo de escritura primero detiene el recorrido con failsafe.
    assert any(
        command.direction == "stop" and command.reason_code == FAILSAFE_REASON
        for command in adapters[0].history
    )

    # Y el finally siempre deja el STOP de cierre como ?ltimo comando.
    assert adapters[0].last_command.direction == "stop"
    assert adapters[0].last_command.reason_code == "APPLICATION_SHUTDOWN"


def test_physical_output_stays_disabled(tmp_path):
    pipeline = make_pipeline(FakeSession())
    pipeline.process(frame_input(image_file(tmp_path)))

    assert pipeline.adapter.physical_output_enabled is False


def frozen_dataset(tmp_path):
    dataset = tmp_path / "dataset"
    make_valid_dataset(dataset)
    freeze(dataset, "v1")
    return dataset


def test_manifest_frames_expose_no_labels(tmp_path):
    names = {field.name for field in fields(FrameInput)}

    assert names == {"sequence_id", "frame_id", "t_capture_ms", "image_size", "image_path"}


def test_frames_from_manifest_resolve_images_and_select_a_sequence(tmp_path):
    dataset = frozen_dataset(tmp_path)
    manifest = dataset / "manifiesto.jsonl"
    rows = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()]
    sequence = rows[0]["sequence_id"]

    frames = frames_from_manifest(manifest, sequence_id=sequence)

    expected = [row for row in rows if row["sequence_id"] == sequence]
    assert [frame.frame_id for frame in frames] == [row["frame_id"] for row in expected]
    assert frames[0].image_path == dataset / expected[0]["image"]
    assert frames[0].image_path.is_file()
    assert frames[0].t_capture_ms == expected[0]["t_capture_ms"]
    assert frames[0].image_size == (expected[0]["image_width"], expected[0]["image_height"])
    assert len(frames_from_manifest(manifest)) == len(rows)


def test_unknown_sequence_is_rejected(tmp_path):
    dataset = frozen_dataset(tmp_path)

    with pytest.raises(ValueError, match="nope"):
        frames_from_manifest(dataset / "manifiesto.jsonl", sequence_id="nope")


def test_altered_manifest_is_rejected(tmp_path):
    dataset = frozen_dataset(tmp_path)
    manifest = dataset / "manifiesto.jsonl"
    manifest.write_bytes(manifest.read_bytes() + b"\n")

    with pytest.raises(ValueError):
        frames_from_manifest(manifest)


def cli_dataset(tmp_path):
    """Dataset congelado cuyas imagenes son PNG reales, como exige el detector."""
    dataset = frozen_dataset(tmp_path)
    for path in dataset.glob("secuencias/*/*.jpg"):
        write_png(path, np.zeros((296, 400, 3), dtype=np.uint8))
    return dataset


def cli_arguments(dataset, output, *extra):
    return [
        "--weights",
        "unused.onnx",
        "--policy-config",
        str(POLICY_CONFIG),
        "--manifest",
        str(dataset / "manifiesto.jsonl"),
        "--output",
        str(output),
        *extra,
    ]


def fake_weights(monkeypatch, session):
    monkeypatch.setattr(YoloxDetector, "from_weights", lambda *_a, **_k: YoloxDetector(session))


def first_sequence(dataset):
    line = (dataset / "manifiesto.jsonl").read_text(encoding="utf-8").splitlines()[0]
    return json.loads(line)["sequence_id"]


def test_cli_writes_one_trace_per_frame_in_a_configurable_folder(tmp_path, monkeypatch, capsys):
    dataset = cli_dataset(tmp_path)
    sequence = first_sequence(dataset)
    output = tmp_path / "nueva" / "carpeta" / "traza.jsonl"
    fake_weights(monkeypatch, FakeSession())

    code = cli.main(cli_arguments(dataset, output, "--sequence", sequence))

    assert code == 0
    lines = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert lines
    assert {line["sequence_id"] for line in lines} == {sequence}
    assert all(line["frame_id"] == line["command"]["frame_id"] for line in lines)
    assert f"frames={len(lines)} errors=0" in capsys.readouterr().out


def test_cli_fails_when_a_frame_fails_but_keeps_the_evidence(tmp_path, monkeypatch):
    dataset = cli_dataset(tmp_path)
    output = tmp_path / "traza.jsonl"
    fake_weights(monkeypatch, FakeSession(error=RuntimeError("boom")))

    code = cli.main(cli_arguments(dataset, output, "--sequence", first_sequence(dataset)))

    assert code == 1
    lines = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert lines
    assert all(line["command"]["direction"] == "stop" for line in lines)
    assert all(line["errors"][0]["stage"] == "detector" for line in lines)


def test_cli_never_overwrites_an_existing_trace(tmp_path, monkeypatch, caplog):
    dataset = cli_dataset(tmp_path)
    output = tmp_path / "traza.jsonl"
    output.write_bytes(b"evidencia anterior\n")
    session = FakeSession()
    fake_weights(monkeypatch, session)

    with caplog.at_level(logging.ERROR):
        code = cli.main(cli_arguments(dataset, output))

    assert code == 1
    assert output.read_bytes() == b"evidencia anterior\n"
    assert "integration_error stage=output" in caplog.text
    assert session.tensors == []


def test_cli_trace_uses_the_same_line_ending_on_every_platform(tmp_path, monkeypatch):
    dataset = cli_dataset(tmp_path)
    output = tmp_path / "traza.jsonl"
    fake_weights(monkeypatch, FakeSession())

    assert cli.main(cli_arguments(dataset, output, "--sequence", first_sequence(dataset))) == 0

    content = output.read_bytes()
    assert content.endswith(b"\n")
    assert b"\r" not in content


def test_cli_startup_failure_emits_no_commands(tmp_path, monkeypatch, caplog):
    dataset = cli_dataset(tmp_path)
    output = tmp_path / "traza.jsonl"

    def no_weights(*_args, **_kwargs):
        raise DetectorError("load failed")

    monkeypatch.setattr(YoloxDetector, "from_weights", no_weights)

    with caplog.at_level(logging.ERROR):
        code = cli.main(cli_arguments(dataset, output))

    assert code == 1
    assert not output.exists()
    assert "integration_error stage=startup" in caplog.text


def test_cli_rejects_an_invalid_policy_config(tmp_path, monkeypatch):
    dataset = cli_dataset(tmp_path)
    output = tmp_path / "traza.jsonl"
    bad = tmp_path / "politica.yaml"
    bad.write_text("campo_desconocido: 1\n", encoding="utf-8")
    fake_weights(monkeypatch, FakeSession())

    arguments = [*cli_arguments(dataset, output), "--policy-config", str(bad)]

    assert cli.main(arguments) == 1
    assert not output.exists()


def p5_is_installed():
    try:
        importlib.metadata.distribution("p5")
    except importlib.metadata.PackageNotFoundError:
        return False
    return True


@pytest.mark.skipif(not p5_is_installed(), reason="p5 no esta instalado en este entorno")
def test_installed_command_finds_the_policy_without_the_pytest_path(tmp_path):
    # pytest agrega Proyecto3/src a su propio sys.path: un proceso nuevo no lo hereda.
    result = subprocess.run(
        [sys.executable, "-c", "import p3.policy.politica; import p5.integration.pipeline"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_policy_timing_reaches_control_decision():
    decision = (
        policy()
        .decidir_crudo(
            {
                "sequence_id": "s-time",
                "frame_id": "f-time",
                "t_capture_ms": 1000.0,
                "image_width": 10,
                "image_height": 10,
                "status": "ok",
                "detections": [],
            }
        )
        .model_copy(
            update={
                "accion": "FORWARD",
                "velocidad": 0.5,
                "direccion": 0.0,
                "valido_hasta_ms": 1250.0,
            }
        )
    )

    control = to_control_decision(
        decision,
        frame_id="f-time",
        decision_id="s-time:f-time",
    )

    assert control.t_capture_ms == 1000.0
    assert control.valid_until_ms == 1250.0


def test_watchdog_timeout_restarts_policy_confirmation_without_new_frame(tmp_path):
    image = image_file(tmp_path)
    now = {"ms": 0.0}

    adapter = VirtualControlAdapter(clock_ms=lambda: now["ms"])
    pipeline = Pipeline(
        YoloxDetector(ScriptedSession([CLEAR] * 6)),
        policy(),
        adapter,
    )

    # Tres cuadros frescos confirman la vía y permiten avanzar.
    initial = []
    for index, capture_ms in enumerate((0.0, 100.0, 200.0)):
        now["ms"] = capture_ms
        initial.append(
            pipeline.process(
                frame_input(
                    image,
                    index,
                    t_capture_ms=capture_ms,
                )
            )
        )

    assert initial[-1].command["direction"] == "forward"

    # Se interrumpe la llegada de cuadros y vence el comando.
    deadline = adapter.last_command.valid_until_ms
    assert deadline is not None

    now["ms"] = deadline

    stop = pipeline.check_watchdog()

    assert stop is not None
    assert stop["direction"] == "stop"
    assert stop["reason_code"] == "watchdog_timeout"

    # No llegó ningún cuadro para provocar el STOP.
    assert len(initial) == 3

    # Tras el timeout, la política debe reconfirmar la vía.
    recovered = []
    for offset in (1.0, 2.0, 3.0):
        now["ms"] = deadline + offset
        recovered.append(
            pipeline.process(
                frame_input(
                    image,
                    3 + int(offset),
                    t_capture_ms=now["ms"],
                )
            )
        )

    assert [trace.command["direction"] for trace in recovered] == [
        "stop",
        "stop",
        "forward",
    ]
    assert recovered[0].decision["reason_code"] == "PERCEPCION_NO_CONFIRMADA"


def test_late_fresh_frame_cannot_bypass_expired_previous_command(tmp_path):
    image = image_file(tmp_path)
    now = {"ms": 0.0}

    adapter = VirtualControlAdapter(clock_ms=lambda: now["ms"])
    pipeline = Pipeline(
        YoloxDetector(ScriptedSession([CLEAR] * 4)),
        policy(),
        adapter,
    )

    # Tres cuadros confirman la vía.
    for index, capture_ms in enumerate((0.0, 100.0, 200.0)):
        now["ms"] = capture_ms
        trace = pipeline.process(frame_input(image, index, t_capture_ms=capture_ms))

    assert trace.command["direction"] == "forward"

    expired_decision_id = adapter.last_command.decision_id

    # No se llamó check_watchdog() manualmente.
    # El siguiente cuadro llega mucho después del vencimiento.
    now["ms"] = 2200.0

    late = pipeline.process(
        frame_input(
            image,
            3,
            t_capture_ms=2200.0,
        )
    )

    # El Pipeline debe haber detectado primero el vencimiento.
    watchdog_commands = [
        command for command in adapter.history if command.reason_code == "watchdog_timeout"
    ]

    assert len(watchdog_commands) == 1
    assert watchdog_commands[0].decision_id == expired_decision_id
    assert watchdog_commands[0].direction == "stop"

    # Y el cuadro nuevo ya entra con la confirmación reiniciada.
    assert late.command["direction"] == "stop"
    assert late.decision["reason_code"] == "PERCEPCION_NO_CONFIRMADA"


def test_stale_frames_do_not_reach_detector_or_policy(tmp_path):
    image = image_file(tmp_path)
    now = {"ms": 0.0}

    session = ScriptedSession([CLEAR] * 7)
    adapter = VirtualControlAdapter(clock_ms=lambda: now["ms"])
    pipeline = Pipeline(
        YoloxDetector(session),
        policy(),
        adapter,
    )

    # Tres cuadros frescos confirman la v?a.
    for index, capture_ms in enumerate((0.0, 100.0, 200.0)):
        now["ms"] = capture_ms
        trace = pipeline.process(frame_input(image, index, t_capture_ms=capture_ms))

    assert trace.command["direction"] == "forward"
    assert len(session.tensors) == 3

    # El reloj avanza, pero llegan tres cuadros demasiado antiguos.
    now["ms"] = 2200.0
    stale = []

    for index, capture_ms in enumerate((300.0, 400.0, 500.0), start=3):
        stale.append(pipeline.process(frame_input(image, index, t_capture_ms=capture_ms)))

    # Los cuadros vencidos deben rechazarse antes del detector y la pol?tica.
    assert len(session.tensors) == 3
    assert all(trace.command["direction"] == "stop" for trace in stale)
    assert all(trace.decision is None for trace in stale)
    assert all(trace.errors[0]["stage"] == "stale" for trace in stale)

    # Como los cuadros viejos no contaron, el siguiente cuadro fresco
    # todav?a debe empezar la reconfirmaci?n de la v?a.
    fresh = pipeline.process(
        frame_input(
            image,
            6,
            t_capture_ms=2200.0,
        )
    )

    assert len(session.tensors) == 4
    assert fresh.command["direction"] == "stop"
    assert fresh.decision["reason_code"] == "PERCEPCION_NO_CONFIRMADA"


def test_future_frame_is_rejected_before_detector_and_policy(tmp_path):
    image = image_file(tmp_path)
    now = {"ms": 1000.0}

    session = ScriptedSession([CLEAR])
    adapter = VirtualControlAdapter(clock_ms=lambda: now["ms"])
    pipeline = Pipeline(
        YoloxDetector(session),
        policy(),
        adapter,
    )

    future = pipeline.process(
        frame_input(
            image,
            0,
            t_capture_ms=3_601_000.0,
        )
    )

    assert session.tensors == []
    assert future.decision is None
    assert future.command["direction"] == "stop"
    assert future.errors[0]["stage"] == "stale"
    assert adapter.last_command.direction == "stop"


def test_emergency_stop_is_latched_and_clear_frame_cannot_rearm(tmp_path):
    image = image_file(tmp_path)
    pipeline = make_pipeline(ScriptedSession([CLEAR] * 4))

    # Primero confirmamos vía libre y avanzamos.
    assert run(pipeline, image, 3)[-1].command["direction"] == "forward"

    # La emergencia debe detener inmediatamente, sin necesitar otro frame.
    emergency = pipeline.trigger_emergency()

    assert emergency["direction"] == "stop"
    assert emergency["speed"] == 0.0
    assert emergency["reason_code"] == "EMERGENCY_STOP"
    assert pipeline.emergency_latched is True

    # Aunque llegue un cuadro despejado, la emergencia sigue enclavada.
    trace = pipeline.process(frame_input(image, 3))

    assert trace.command["direction"] == "stop"
    assert trace.command["reason_code"] == "EMERGENCY_LATCHED"
    assert pipeline.emergency_latched is True


def test_rearm_requires_explicit_request_and_fresh_perception(tmp_path):
    image = image_file(tmp_path)
    now = {"ms": 0.0}

    adapter = VirtualControlAdapter(clock_ms=lambda: now["ms"])
    pipeline = Pipeline(
        YoloxDetector(ScriptedSession([CLEAR] * 6)),
        policy(),
        adapter,
    )

    # Confirma vía libre y comienza a avanzar.
    for index, capture_ms in enumerate((0.0, 100.0, 200.0)):
        now["ms"] = capture_ms
        trace = pipeline.process(frame_input(image, index, t_capture_ms=capture_ms))

    assert trace.command["direction"] == "forward"

    pipeline.trigger_emergency()
    assert pipeline.emergency_latched is True

    # Un frame despejado por sí solo NO rearma.
    now["ms"] = 300.0
    blocked = pipeline.process(frame_input(image, 3, t_capture_ms=300.0))

    assert blocked.command["direction"] == "stop"
    assert pipeline.emergency_latched is True

    # El rearme debe pedirse explícitamente.
    pipeline.request_rearm()

    # Una percepción vieja tampoco puede completar el rearme.
    now["ms"] = 1000.0
    stale = pipeline.process(frame_input(image, 4, t_capture_ms=300.0))

    assert stale.command["direction"] == "stop"
    assert pipeline.emergency_latched is True

    # Una percepción fresca válida completa el rearme,
    # pero todavía debe reconfirmar la vía.
    fresh = pipeline.process(frame_input(image, 5, t_capture_ms=1000.0))

    assert pipeline.emergency_latched is False
    assert fresh.command["direction"] == "stop"
    assert fresh.decision["reason_code"] == "PERCEPCION_NO_CONFIRMADA"

    # Todavía hacen falta dos cuadros más para volver a avanzar.
    now["ms"] = 1100.0
    second = pipeline.process(frame_input(image, 6, t_capture_ms=1100.0))

    now["ms"] = 1200.0
    third = pipeline.process(frame_input(image, 7, t_capture_ms=1200.0))

    assert second.command["direction"] == "stop"
    assert third.command["direction"] == "forward"


def test_rearm_does_not_unlock_on_unreadable_image(tmp_path):
    image = image_file(tmp_path)
    pipeline = make_pipeline(ScriptedSession([CLEAR] * 4))

    # Confirma vía y comienza a avanzar.
    assert run(pipeline, image, 3)[-1].command["direction"] == "forward"

    pipeline.trigger_emergency()
    pipeline.request_rearm()

    # La imagen ilegible no puede completar el rearme.
    failed = pipeline.process(frame_input(tmp_path / "missing-rearm.png", 3))

    assert failed.perception["status"] == "error"
    assert failed.command["direction"] == "stop"
    assert failed.command["reason_code"] == "EMERGENCY_LATCHED"
    assert pipeline.emergency_latched is True

    # Una percepción válida posterior sí puede completar el rearme,
    # pero todavía queda detenido mientras reconfirma la vía.
    recovered = pipeline.process(frame_input(image, 4))

    assert pipeline.emergency_latched is False
    assert recovered.command["direction"] == "stop"
    assert recovered.decision["reason_code"] == "PERCEPCION_NO_CONFIRMADA"


def test_shutdown_emits_final_stop_and_prevents_more_motion(tmp_path):
    image = image_file(tmp_path)
    pipeline = make_pipeline(ScriptedSession([CLEAR] * 4))

    # Confirma vía libre y comienza a avanzar.
    assert run(pipeline, image, 3)[-1].command["direction"] == "forward"

    shutdown = pipeline.shutdown()

    assert shutdown["direction"] == "stop"
    assert shutdown["speed"] == 0.0
    assert shutdown["reason_code"] == "APPLICATION_SHUTDOWN"
    assert pipeline.adapter.last_command.direction == "stop"
    assert pipeline.halted is True

    # Tras el cierre, aunque llegue otro cuadro, no puede volver a moverse.
    trace = pipeline.process(frame_input(image, 3))

    assert trace.command["direction"] == "stop"


def test_cli_emits_final_stop_on_normal_shutdown(tmp_path, monkeypatch):
    image = image_file(tmp_path)
    frames = [frame_input(image, i) for i in range(3)]
    adapters = []

    class RecordedAdapter(VirtualControlAdapter):
        def __init__(self):
            super().__init__()
            adapters.append(self)

    monkeypatch.setattr(cli, "frames_from_manifest", lambda *_a, **_k: frames)
    monkeypatch.setattr(cli, "VirtualControlAdapter", RecordedAdapter)
    fake_weights(monkeypatch, FakeSession())

    output = tmp_path / "traza.jsonl"

    code = cli.main(cli_arguments(tmp_path, output))

    assert code == 0
    assert adapters

    # Antes de cerrar, los 3 cuadros libres alcanzaron FORWARD.
    assert any(command.direction == "forward" for command in adapters[0].history)

    # El último comando de toda la aplicación debe ser el STOP de cierre.
    final = adapters[0].last_command
    assert final.direction == "stop"
    assert final.speed == 0.0
    assert final.reason_code == "APPLICATION_SHUTDOWN"


def test_rearm_requires_a_frame_newer_than_the_one_before_emergency(tmp_path):
    image = image_file(tmp_path)
    pipeline = make_pipeline(ScriptedSession([CLEAR] * 5))

    # La vía queda confirmada hasta t=200 ms.
    for index, capture_ms in enumerate((0.0, 100.0, 200.0)):
        trace = pipeline.process(frame_input(image, index, t_capture_ms=capture_ms))

    assert trace.command["direction"] == "forward"

    pipeline.trigger_emergency()
    pipeline.request_rearm()

    # La imagen es válida, pero pertenece al mismo instante que el último
    # cuadro aceptado antes de la emergencia: no es percepción fresca.
    old = pipeline.process(frame_input(image, 3, t_capture_ms=200.0))

    assert old.command["direction"] == "stop"
    assert old.command["reason_code"] == "EMERGENCY_LATCHED"
    assert pipeline.emergency_latched is True

    # Un cuadro realmente posterior sí puede comenzar el rearme seguro.
    fresh = pipeline.process(frame_input(image, 4, t_capture_ms=300.0))

    assert pipeline.emergency_latched is False
    assert fresh.command["direction"] == "stop"
    assert fresh.decision["reason_code"] == "PERCEPCION_NO_CONFIRMADA"


def test_emergency_adapter_failure_cancels_motion_and_does_not_escape(tmp_path):
    image = image_file(tmp_path)
    adapter = FailingAdapter()
    pipeline = Pipeline(YoloxDetector(ScriptedSession([CLEAR] * 3)), policy(), adapter)

    # Hay movimiento activo antes de la emergencia.
    assert run(pipeline, image, 3)[-1].command["direction"] == "forward"

    adapter.broken = True

    emergency = pipeline.trigger_emergency()

    # Si ni siquiera puede emitirse el STOP, el recorrido se invalida
    # y el movimiento anterior se cancela.
    assert emergency["direction"] == "stop"
    assert emergency["speed"] == 0.0
    assert emergency["reason_code"] == STOP_NOT_EMITTED_REASON
    assert pipeline.emergency_latched is True
    assert pipeline.halted is True
    assert adapter.last_command is None


def test_shutdown_adapter_failure_cancels_motion_and_does_not_escape(tmp_path):
    image = image_file(tmp_path)
    adapter = FailingAdapter()
    pipeline = Pipeline(YoloxDetector(ScriptedSession([CLEAR] * 3)), policy(), adapter)

    assert run(pipeline, image, 3)[-1].command["direction"] == "forward"

    adapter.broken = True

    shutdown = pipeline.shutdown()

    assert shutdown["direction"] == "stop"
    assert shutdown["speed"] == 0.0
    assert shutdown["reason_code"] == STOP_NOT_EMITTED_REASON
    assert pipeline.halted is True
    assert adapter.last_command is None


@pytest.mark.parametrize("failure_type", [RuntimeError, KeyboardInterrupt])
def test_cli_shutdown_runs_on_unexpected_failure_or_interrupt(tmp_path, monkeypatch, failure_type):
    image = image_file(tmp_path)
    frames = [frame_input(image, i) for i in range(4)]
    adapters = []

    class RecordedAdapter(VirtualControlAdapter):
        def __init__(self):
            super().__init__()
            adapters.append(self)

    real_process = Pipeline.process
    calls = {"count": 0}

    def interrupted_process(self, frame):
        # Los primeros 3 cuadros confirman la vía y dejan FORWARD activo.
        if calls["count"] == 3:
            raise failure_type("interrupción inesperada")
        calls["count"] += 1
        return real_process(self, frame)

    monkeypatch.setattr(cli, "frames_from_manifest", lambda *_a, **_k: frames)
    monkeypatch.setattr(cli, "VirtualControlAdapter", RecordedAdapter)
    monkeypatch.setattr(Pipeline, "process", interrupted_process)
    fake_weights(monkeypatch, FakeSession())

    output = tmp_path / "traza.jsonl"

    with pytest.raises(failure_type):
        cli.main(cli_arguments(tmp_path, output))

    assert adapters
    assert any(command.direction == "forward" for command in adapters[0].history)

    # Aunque la excepción/interrupción se propague, el finally debe cerrar con STOP.
    final = adapters[0].last_command
    assert final.direction == "stop"
    assert final.speed == 0.0
    assert final.reason_code == "APPLICATION_SHUTDOWN"


def test_cli_returns_error_when_final_shutdown_stop_is_not_emitted(tmp_path, monkeypatch):
    image = image_file(tmp_path)
    frames = [frame_input(image, i) for i in range(3)]
    adapters = []

    class ShutdownFailingAdapter(VirtualControlAdapter):
        def __init__(self):
            super().__init__()
            adapters.append(self)

        def apply(self, decision):
            # El recorrido funciona normalmente; solo falla el STOP final.
            if decision.frame_id == "shutdown":
                raise RuntimeError("shutdown adapter failure")
            return super().apply(decision)

    monkeypatch.setattr(cli, "frames_from_manifest", lambda *_a, **_k: frames)
    monkeypatch.setattr(cli, "VirtualControlAdapter", ShutdownFailingAdapter)
    fake_weights(monkeypatch, FakeSession())

    output = tmp_path / "traza.jsonl"

    code = cli.main(cli_arguments(tmp_path, output))

    assert adapters
    assert any(command.direction == "forward" for command in adapters[0].history)

    # El STOP final no pudo llegar al adaptador.
    assert adapters[0].last_command is None

    # El CLI no puede reportar éxito.
    assert code == 1
