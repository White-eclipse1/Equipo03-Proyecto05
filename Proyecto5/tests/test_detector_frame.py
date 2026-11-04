import json
import logging
import math
from pathlib import Path

import cv2
import numpy as np
import pytest
from p3.policy.config import cargar_config
from p3.policy.contrato import Cuadro
from p3.policy.politica import PoliticaDecision

from dataset_helpers import make_valid_dataset
from p5.dataset.paquete import freeze, load_manifest
from p5.detector import yolox
from p5.detector.frame import PerceptionFrame, detect_frame
from p5.detector.models import Detection
from p5.detector.yolox import YoloxDetector
from test_detector import PERSON, FakeSession, raw_output, write_png

ROOT = Path(__file__).resolve().parents[2]
POLICY_CONFIG = ROOT / "Proyecto3" / "config" / "politica.yaml"
EXAMPLES = ROOT / "Proyecto5" / "docs" / "examples" / "a1-03"
META = {"sequence_id": "seq02", "frame_id": "seq02-0004", "t_capture_ms": 1500}


def policy():
    config, sha256 = cargar_config(POLICY_CONFIG)
    return PoliticaDecision(config, sha256)


def frame_image(tmp_path, width=64, height=48):
    return write_png(tmp_path / "frame.png", np.zeros((height, width, 3), dtype=np.uint8))


def detect(session, path, **overrides):
    arguments = {**META, "image_size": (640, 480), **overrides}
    return detect_frame(YoloxDetector(session), path, **arguments)


def test_detections_produce_an_ok_frame_with_the_contract_fields(tmp_path):
    raw = raw_output((0, 100, 100, 50, 50, 1.0, PERSON, 0.9))

    frame = detect(FakeSession(raw), frame_image(tmp_path, 416, 416))

    payload = frame.to_dict()
    assert set(payload) == {
        "sequence_id",
        "frame_id",
        "t_capture_ms",
        "image_width",
        "image_height",
        "status",
        "detections",
        "error",
    }
    assert payload["sequence_id"] == "seq02"
    assert payload["frame_id"] == "seq02-0004"
    assert payload["t_capture_ms"] == 1500
    assert payload["status"] == "ok"
    assert payload["error"] is None
    assert payload["detections"][0]["class_name"] == "person"
    Cuadro.model_validate(payload)


def test_scene_without_objects_is_ok_with_an_empty_list(tmp_path):
    payload = detect(FakeSession(), frame_image(tmp_path)).to_dict()

    assert payload["status"] == "ok"
    assert payload["detections"] == ()
    assert payload["error"] is None
    Cuadro.model_validate(payload)


def test_reported_size_comes_from_the_image_when_it_can_be_read(tmp_path):
    frame = detect(FakeSession(), frame_image(tmp_path, 64, 48), image_size=(640, 480))

    assert (frame.image_width, frame.image_height) == (64, 48)


@pytest.mark.parametrize("content", [None, b"", b"not an image"])
def test_unreadable_image_is_an_explicit_error(tmp_path, content, caplog):
    path = tmp_path / "frame.jpg"
    if content is not None:
        path.write_bytes(content)

    with caplog.at_level(logging.ERROR):
        frame = detect(FakeSession(), path)

    assert frame.status == "error"
    assert frame.detections == ()
    assert "frame.jpg" in frame.error
    # El contrato exige dimensiones aun con error, y no hay imagen de donde leerlas.
    assert (frame.image_width, frame.image_height) == (640, 480)
    assert "detector_error stage=read" in caplog.text
    Cuadro.model_validate(frame.to_dict())


def test_inference_failure_is_an_explicit_error_with_the_real_size(tmp_path):
    frame = detect(FakeSession(error=RuntimeError("boom")), frame_image(tmp_path, 64, 48))

    assert frame.status == "error"
    assert "boom" in frame.error
    assert (frame.image_width, frame.image_height) == (64, 48)
    Cuadro.model_validate(frame.to_dict())


def test_invalid_model_output_is_an_explicit_error(tmp_path):
    raw = np.full((1, 3549, 85), np.nan, dtype=np.float32)

    frame = detect(FakeSession(raw), frame_image(tmp_path))

    assert frame.status == "error"
    assert "non-finite" in frame.error
    Cuadro.model_validate(frame.to_dict())


def test_preprocess_failure_is_an_explicit_error(tmp_path, monkeypatch):
    def broken_resize(*_args, **_kwargs):
        raise cv2.error("resize failed")

    path = frame_image(tmp_path)
    monkeypatch.setattr(yolox.cv2, "resize", broken_resize)

    frame = detect(FakeSession(), path)

    assert frame.status == "error"
    assert "resize failed" in frame.error
    Cuadro.model_validate(frame.to_dict())


def test_policy_tells_an_empty_scene_from_a_detector_error(tmp_path):
    decisions = policy()
    path = frame_image(tmp_path)
    empty = [
        detect(FakeSession(), path, frame_id=f"seq02-{i}", t_capture_ms=i * 100) for i in range(3)
    ]
    failed = detect(
        FakeSession(error=RuntimeError("boom")), path, frame_id="seq02-3", t_capture_ms=300
    )

    results = [decisions.decidir_crudo(frame.to_dict()) for frame in [*empty, failed]]

    assert results[2].reason_code == "VIA_LIBRE"
    assert results[3].reason_code == "ERROR_PERCEPCION"
    assert results[3].velocidad == 0


def test_frozen_manifest_rows_feed_the_contract(tmp_path):
    dataset = tmp_path / "dataset"
    make_valid_dataset(dataset)
    freeze(dataset, "v1")
    row = load_manifest(dataset / "manifiesto.jsonl")[0]

    # Los JPEG de `dataset_helpers` no se pueden decodificar: las dimensiones del error
    # salen del manifiesto.
    frame = detect_frame(
        YoloxDetector(FakeSession()),
        dataset / row["image"],
        sequence_id=row["sequence_id"],
        frame_id=row["frame_id"],
        t_capture_ms=row["t_capture_ms"],
        image_size=(row["image_width"], row["image_height"]),
    )

    cuadro = Cuadro.model_validate(frame.to_dict())
    assert (cuadro.sequence_id, cuadro.frame_id) == (row["sequence_id"], row["frame_id"])
    assert cuadro.t_capture_ms == row["t_capture_ms"]
    assert cuadro.status == "error"
    assert (cuadro.image_width, cuadro.image_height) == (row["image_width"], row["image_height"])


def test_frames_round_trip_through_jsonl(tmp_path):
    raw = raw_output((0, 100, 100, 50, 50, 1.0, PERSON, 0.9))
    frames = [
        detect(FakeSession(raw), frame_image(tmp_path, 416, 416)),
        detect(FakeSession(), frame_image(tmp_path), frame_id="seq02-0005", t_capture_ms=2000),
        detect(FakeSession(), tmp_path / "missing.jpg", frame_id="seq02-0006", t_capture_ms=2500),
    ]

    lines = "\n".join(frame.to_json() for frame in frames).splitlines()

    assert len(lines) == 3
    parsed = [Cuadro.model_validate_json(line) for line in lines]
    assert [cuadro.status for cuadro in parsed] == ["ok", "ok", "error"]
    assert [len(cuadro.detections) for cuadro in parsed] == [1, 0, 0]


def test_to_json_rejects_values_that_are_not_valid_json():
    frame = PerceptionFrame(
        sequence_id="s",
        frame_id="f",
        t_capture_ms=0,
        image_width=1,
        image_height=1,
        status="ok",
        detections=(Detection("person", math.nan, (0.0, 0.0, 1.0, 1.0)),),
        error=None,
    )

    with pytest.raises(ValueError):
        frame.to_json()


@pytest.mark.parametrize(
    "overrides",
    [
        {"sequence_id": ""},
        {"frame_id": ""},
        {"t_capture_ms": -1},
        {"t_capture_ms": math.nan},
        {"t_capture_ms": math.inf},
        {"image_size": (0, 480)},
        {"image_size": (640, -1)},
    ],
)
def test_invalid_frame_metadata_is_rejected(tmp_path, overrides):
    with pytest.raises(ValueError):
        detect(FakeSession(), frame_image(tmp_path), **overrides)


@pytest.mark.parametrize(
    ("name", "status", "has_detections"),
    [("frame_ok", "ok", True), ("frame_empty", "ok", False), ("frame_error", "error", False)],
)
def test_published_examples_follow_the_contract(name, status, has_detections):
    payload = json.loads((EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))

    cuadro = Cuadro.model_validate(payload)

    assert cuadro.status == status
    assert bool(cuadro.detections) is has_detections
    assert (cuadro.error is not None) is (status == "error")


def test_policy_consumes_the_published_examples_without_changes():
    def load(name):
        return json.loads((EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))

    ok = policy().decidir_crudo(load("frame_ok"))
    empty = policy().decidir_crudo(load("frame_empty"))
    failed = policy().decidir_crudo(load("frame_error"))

    assert ok.reason_code != "SALIDA_MALFORMADA"
    assert empty.reason_code == "PERCEPCION_NO_CONFIRMADA"
    assert failed.reason_code == "ERROR_PERCEPCION"
