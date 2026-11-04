import json
import os
from pathlib import Path

import pytest

from p5.dataset.paquete import load_manifest
from p5.integration import __main__ as cli

WEIGHTS = os.environ.get("P5_DETECTOR_WEIGHTS")
ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "Proyecto5" / "data" / "p5-eval-v1" / "manifiesto.jsonl"
POLICY_CONFIG = ROOT / "Proyecto3" / "config" / "politica.yaml"

pytestmark = pytest.mark.skipif(not WEIGHTS, reason="P5_DETECTOR_WEIGHTS not set")


def traverse(sequence, output):
    code = cli.main(
        [
            "--weights",
            WEIGHTS,
            "--policy-config",
            str(POLICY_CONFIG),
            "--manifest",
            str(MANIFEST),
            "--sequence",
            sequence,
            "--output",
            str(output),
        ]
    )
    lines = output.read_text(encoding="utf-8").splitlines()
    return code, [json.loads(line) for line in lines]


@pytest.mark.parametrize("sequence", ["seq01", "seq06"])
def test_real_images_cross_the_whole_path_with_the_same_frame(tmp_path, sequence):
    code, traces = traverse(sequence, tmp_path / "traza.jsonl")

    expected = [row for row in load_manifest(MANIFEST) if row["sequence_id"] == sequence]
    assert code == 0
    assert [t["frame_id"] for t in traces] == [row["frame_id"] for row in expected]
    for trace, row in zip(traces, expected, strict=True):
        assert trace["errors"] == []
        assert trace["perception"]["status"] == "ok"
        assert (trace["perception"]["image_width"], trace["perception"]["image_height"]) == (
            row["image_width"],
            row["image_height"],
        )
        assert trace["t_capture_ms"] == row["t_capture_ms"]
        assert trace["decision"]["t_capture_ms"] == row["t_capture_ms"]
        assert trace["decision"]["frame_id"] == row["frame_id"]
        assert trace["command"]["frame_id"] == row["frame_id"]


def test_real_person_in_the_center_is_detected_in_some_frames(tmp_path):
    _code, traces = traverse("seq06", tmp_path / "traza.jsonl")

    rows = {row["frame_id"]: row for row in load_manifest(MANIFEST)}
    center = [t for t in traces if rows[t["frame_id"]]["road_state"] == "centro"]
    # Solo exige verla y frenar en alguno de esos cuadros. No garantiza que todos eviten
    # FORWARD: seq06-0036 y seq06-0038 avanzan. Ver "Hallazgos" en docs/B3-01_RECORRIDO.md.
    assert center
    assert any(t["perception"]["detections"] for t in center)
    assert any(t["decision"]["estado"] in {"BLOCKED", "CAUTION"} for t in center)


def test_first_frames_never_move_before_confirming_the_road(tmp_path):
    _code, traces = traverse("seq01", tmp_path / "traza.jsonl")

    assert traces[0]["decision"]["accion"] == "STOP"
    assert traces[0]["command"]["direction"] == "stop"
    assert traces[0]["command"]["speed"] == 0.0
