import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from p5.casos import runner
from p5.casos.filtro import MedianFilterDetector
from p5.detector.frame import detect_frame
from p5.detector.yolox import DetectorError, YoloxDetector

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
GRID_CELLS = 3549


class FakeSession:
    def __init__(self):
        self.tensors = []

    def get_inputs(self):
        return [SimpleNamespace(name="images", shape=[1, 3, 416, 416])]

    def get_providers(self):
        return ["CPUExecutionProvider"]

    def run(self, _outputs, feeds):
        self.tensors.append(feeds["images"])
        return [np.zeros((1, GRID_CELLS, 85), dtype=np.float32)]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def noisy_image():
    generator = np.random.default_rng(0)
    return generator.integers(0, 256, (296, 400, 3), dtype=np.uint8)


def test_the_runner_does_not_filter_by_default(monkeypatch):
    plain = YoloxDetector(FakeSession())
    monkeypatch.setattr(runner.YoloxDetector, "from_weights", lambda weights: plain)
    assert runner.load_detector(Path("pesos.onnx")) is plain
    assert isinstance(runner.load_detector(Path("pesos.onnx"), 3), MedianFilterDetector)


def test_the_median_filter_reaches_the_model():
    session = FakeSession()
    image = noisy_image()
    MedianFilterDetector(YoloxDetector(session), 3).detect_image(image)
    expected = FakeSession()
    YoloxDetector(expected).detect_image(cv2.medianBlur(image, 3))
    assert np.array_equal(session.tensors[0], expected.tensors[0])


@pytest.mark.parametrize("kernel", [-1, 0, 1, 2, 4])
def test_invalid_median_kernels_are_rejected(kernel):
    with pytest.raises(ValueError, match="impar"):
        MedianFilterDetector(YoloxDetector(FakeSession()), kernel)


def test_a_failing_filter_is_a_detector_failure_and_not_an_empty_scene():
    detector = MedianFilterDetector(YoloxDetector(FakeSession()), 3)
    with pytest.raises(DetectorError, match="median filter"):
        detector.detect_image(np.zeros((0, 0, 3), dtype=np.uint8))


def test_the_filter_keeps_what_the_frame_contract_needs(tmp_path):
    path = tmp_path / "cuadro.png"
    cv2.imwrite(str(path), noisy_image())
    frame = detect_frame(
        MedianFilterDetector(YoloxDetector(FakeSession()), 3),
        path,
        sequence_id="s",
        frame_id="s-1",
        t_capture_ms=0,
        image_size=(400, 296),
    )
    assert frame.status == "ok"
    assert frame.detections == ()


def test_the_comparison_refuses_the_evaluation_package(tmp_path):
    script = load_script("ajuste_detector")
    (tmp_path / "secuencias.json").write_text(
        json.dumps({"package": "evaluacion"}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="solo se ajusta"):
        script.main(["--dataset", str(tmp_path), "--output", str(tmp_path / "salida.json")])


def test_the_selection_prefers_safety_then_cost_then_progress():
    script = load_script("ajuste_detector")
    results = {
        "insegura": {"no_permitidas": 1, "inferencias_por_cuadro": 1, "sin_avance": 0},
        "cara": {"no_permitidas": 0, "inferencias_por_cuadro": 2, "sin_avance": 2},
        "barata": {"no_permitidas": 0, "inferencias_por_cuadro": 1, "sin_avance": 7},
        "barata_mejor": {"no_permitidas": 0, "inferencias_por_cuadro": 1, "sin_avance": 6},
    }
    assert script.select(results) == "barata_mejor"


def test_a_person_only_counts_when_a_firm_person_box_overlaps_it():
    script = load_script("ajuste_detector")
    target = [{"class_name": "person", "bbox_xyxy": [100, 0, 150, 140]}]
    box = (100.0, 0.0, 150.0, 140.0)
    assert script.firm_people([("person", 0.8, box)], target) == 1
    assert script.firm_people([("person", 0.4, box)], target) == 0
    assert script.firm_people([("tv", 0.9, box)], target) == 0
    assert script.firm_people([("person", 0.9, (300.0, 0.0, 350.0, 140.0))], target) == 0


@pytest.mark.parametrize(
    ("final", "raw", "stage"),
    [
        (0.8, 0.8, "firme"),
        (0.4, 0.4, "debil"),
        (0.15, 0.15, "bajo_umbral_bajo"),
        (0.0, 0.5, "perdida_por_clase_o_nms"),
        (0.0, 0.03, "sin_evidencia_del_modelo"),
    ],
)
def test_each_lost_person_gets_the_stage_that_explains_it(final, raw, stage):
    assert load_script("diagnostico_perdidas").classify(final, raw) == stage
