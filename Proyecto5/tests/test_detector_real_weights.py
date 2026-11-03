import json
import os
from pathlib import Path

import numpy as np
import pytest

from p5.detector import __main__ as cli
from p5.detector.yolox import YoloxDetector

WEIGHTS = os.environ.get("P5_DETECTOR_WEIGHTS")
EVIDENCE = Path(__file__).resolve().parents[2] / "Proyecto4" / "evidencias"
STREET = EVIDENCE / "EDGE-02" / "manual" / "edge01-0dc81034998343b680ecc8aeb4452834.jpg"
NO_PEOPLE = EVIDENCE / "EDGE-01" / "camara-nueva.jpg"

pytestmark = pytest.mark.skipif(not WEIGHTS, reason="P5_DETECTOR_WEIGHTS not set")


@pytest.fixture(scope="module")
def detector():
    return YoloxDetector.from_weights(WEIGHTS, score_threshold=0.3)


def test_real_session_runs_only_on_cpu(detector):
    assert detector._session.get_providers() == ["CPUExecutionProvider"]


def test_detects_people_in_a_full_street_image(detector):
    result = detector.detect_file(STREET)

    assert (result.image_width, result.image_height) == (1920, 1080)
    people = [d for d in result.detections if d.class_name == "person" and d.confidence >= 0.5]
    assert len(people) >= 4
    for detection in result.detections:
        x1, y1, x2, y2 = detection.bbox_xyxy
        assert 0 <= x1 < x2 <= result.image_width
        assert 0 <= y1 < y2 <= result.image_height


def test_detections_change_with_the_objects_in_the_image(detector):
    street = detector.detect_file(STREET).detections
    no_people = detector.detect_file(NO_PEOPLE).detections

    assert "person" in {d.class_name for d in street}
    assert "person" not in {d.class_name for d in no_people}


def test_plain_image_has_no_detections(detector):
    assert detector.detect_image(np.full((480, 640, 3), 128, dtype=np.uint8)) == ()


def test_cli_runs_with_real_weights(capsys):
    code = cli.main(["--weights", WEIGHTS, "--image", str(STREET), "--score-threshold", "0.5"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["image_width"] == 1920
    assert {d["class_name"] for d in payload["detections"]} >= {"person"}
