import json
import logging
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from p5.detector import __main__ as cli
from p5.detector import yolox
from p5.detector.coco_classes import COCO_CLASSES
from p5.detector.models import Detection, DetectionResult
from p5.detector.yolox import DetectorError, YoloxDetector, preprocess

INPUT_SIZE = (416, 416)
GRID_CELLS = 3549  # 52*52 + 26*26 + 13*13 para una entrada de 416x416.
PERSON, DOG = COCO_CLASSES.index("person"), COCO_CLASSES.index("dog")


class FakeSession:
    def __init__(self, raw=None, error=None, shape=(1, 3, 416, 416)):
        self.raw = np.zeros((1, GRID_CELLS, 85), dtype=np.float32) if raw is None else raw
        self.error = error
        self.shape = list(shape)
        self.tensors = []

    def get_inputs(self):
        return [SimpleNamespace(name="images", shape=self.shape)]

    def get_providers(self):
        return ["CPUExecutionProvider"]

    def run(self, _outputs, feeds):
        self.tensors.append(feeds["images"])
        if self.error is not None:
            raise self.error
        return [self.raw.copy()]


def raw_output(*boxes):
    """Salida cruda con una caja por tupla (celda, cx, cy, w, h, obj, clase, score).

    Las coordenadas estan en pixeles de la entrada de 416x416, y `celda` es una celda
    distinta de la malla de stride 8 para cada caja.
    """
    raw = np.zeros((1, GRID_CELLS, 85), dtype=np.float32)
    for cell, cx, cy, width, height, objectness, class_index, score in boxes:
        row, col = divmod(cell, 52)
        raw[0, cell, 0] = cx / 8 - col
        raw[0, cell, 1] = cy / 8 - row
        raw[0, cell, 2] = np.log(width / 8)
        raw[0, cell, 3] = np.log(height / 8)
        raw[0, cell, 4] = objectness
        raw[0, cell, 5 + class_index] = score
    return raw


def image(width=416, height=416):
    return np.full((height, width, 3), 200, dtype=np.uint8)


def write_png(path, pixels):
    ok, encoded = cv2.imencode(".png", pixels)
    assert ok
    path.write_bytes(encoded.tobytes())
    return path


def test_preprocess_letterboxes_without_normalizing():
    pixels = np.zeros((100, 200, 3), dtype=np.uint8)
    pixels[..., 0] = 10
    pixels[..., 1] = 20
    pixels[..., 2] = 30

    tensor, ratio = preprocess(pixels, INPUT_SIZE)

    assert ratio == pytest.approx(2.08)
    assert tensor.shape == (3, 416, 416)
    assert tensor.dtype == np.float32
    # Canales BGR y valores 0-255 sin media ni desviacion.
    assert tensor[:, 0, 0].tolist() == [10.0, 20.0, 30.0]
    assert tensor[:, 207, 415].tolist() == [10.0, 20.0, 30.0]
    # El relleno va abajo y a la derecha, no centrado.
    assert tensor[:, 208, 0].tolist() == [114.0, 114.0, 114.0]


def test_preprocess_keeps_at_least_one_pixel_on_extreme_aspect_ratio():
    tensor, _ = preprocess(np.zeros((1, 5000, 3), dtype=np.uint8), INPUT_SIZE)

    assert tensor.shape == (3, 416, 416)


def test_detects_box_class_and_confidence_in_original_pixels():
    raw = raw_output((0, 104, 104, 52, 104, 0.9, PERSON, 0.8))
    detector = YoloxDetector(FakeSession(raw))

    # Imagen de 832x832: la entrada es la mitad, asi que las cajas se duplican.
    detections = detector.detect_image(image(832, 832))

    assert len(detections) == 1
    assert detections[0].class_name == "person"
    assert detections[0].confidence == pytest.approx(0.72)
    assert detections[0].bbox_xyxy == pytest.approx((156.0, 104.0, 260.0, 312.0))


def test_scene_without_objects_returns_empty_tuple():
    assert YoloxDetector(FakeSession()).detect_image(image()) == ()


def test_score_threshold_is_configurable():
    raw = raw_output((0, 100, 100, 50, 50, 1.0, PERSON, 0.2))

    assert len(YoloxDetector(FakeSession(raw)).detect_image(image())) == 1
    assert YoloxDetector(FakeSession(raw), score_threshold=0.3).detect_image(image()) == ()


def test_nms_removes_overlap_across_classes_and_keeps_separate_boxes():
    raw = raw_output(
        (0, 100, 100, 80, 80, 1.0, PERSON, 0.9),
        (1, 102, 102, 80, 80, 1.0, DOG, 0.6),
        (2, 300, 300, 80, 80, 1.0, DOG, 0.7),
    )

    detections = YoloxDetector(FakeSession(raw)).detect_image(image())

    assert [d.class_name for d in detections] == ["person", "dog"]
    assert [d.confidence for d in detections] == pytest.approx([0.9, 0.7])


def test_boxes_are_clipped_to_the_image():
    raw = raw_output((0, 10, 400, 100, 100, 1.0, PERSON, 0.9))

    [detection] = YoloxDetector(FakeSession(raw)).detect_image(image())

    assert detection.bbox_xyxy == pytest.approx((0.0, 350.0, 60.0, 416.0))


def test_box_entirely_outside_the_image_is_dropped():
    # Imagen de 416x100: la caja cae en el relleno, debajo de la imagen real.
    raw = raw_output((0, 100, 300, 50, 50, 1.0, PERSON, 0.9))

    assert YoloxDetector(FakeSession(raw)).detect_image(image(416, 100)) == ()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (np.zeros((1, 10, 85), dtype=np.float32), "shape"),
        (np.full((1, GRID_CELLS, 85), np.nan, dtype=np.float32), "non-finite"),
        (np.full((1, GRID_CELLS, 85), 2.0, dtype=np.float32), "outside"),
    ],
)
def test_invalid_model_output_raises_and_logs(raw, expected, caplog):
    detector = YoloxDetector(FakeSession(raw))

    with caplog.at_level(logging.ERROR), pytest.raises(DetectorError, match=expected):
        detector.detect_image(image())

    assert "detector_error stage=postprocess" in caplog.text


def test_runtime_failure_raises_and_logs(caplog):
    detector = YoloxDetector(FakeSession(error=RuntimeError("boom")))

    with caplog.at_level(logging.ERROR), pytest.raises(DetectorError, match="boom"):
        detector.detect_image(image())

    assert "detector_error stage=inference" in caplog.text


@pytest.mark.parametrize(
    "pixels",
    [np.zeros((10, 10), dtype=np.uint8), np.zeros((0, 10, 3), dtype=np.uint8)],
)
def test_invalid_image_array_raises(pixels):
    with pytest.raises(DetectorError, match="HxWx3"):
        YoloxDetector(FakeSession()).detect_image(pixels)


@pytest.mark.parametrize("shape", [(1, 3, "h", "w"), (1, 3, 100, 416), (1, 3, 416)])
def test_unsupported_model_input_raises(shape):
    with pytest.raises(DetectorError, match="input"):
        YoloxDetector(FakeSession(shape=shape))


@pytest.mark.parametrize("kwargs", [{"score_threshold": 1.5}, {"nms_threshold": -0.1}])
def test_invalid_thresholds_are_rejected(kwargs):
    with pytest.raises(ValueError, match="threshold"):
        YoloxDetector(FakeSession(), **kwargs)


def test_prediction_depends_on_pixels_not_on_the_file_name(tmp_path):
    raw = raw_output((0, 100, 100, 50, 50, 1.0, PERSON, 0.9))
    pixels = (np.arange(30000) % 256).astype(np.uint8).reshape(100, 100, 3)
    session = FakeSession(raw)
    detector = YoloxDetector(session)

    first = detector.detect_file(write_png(tmp_path / "dog.png", pixels))
    second = detector.detect_file(write_png(tmp_path / "person_0.99.png", pixels))
    # Un archivo de etiquetas al lado de la imagen no cambia nada.
    (tmp_path / "dog.txt").write_text("0 0.5 0.5 1 1", encoding="utf-8")
    third = detector.detect_file(tmp_path / "dog.png")

    assert first.detections == second.detections == third.detections
    assert np.array_equal(session.tensors[0], session.tensors[1])


def test_detect_file_reports_original_size_and_accepts_non_ascii_paths(tmp_path):
    path = write_png(tmp_path / "señal ñ.png", np.zeros((48, 64, 3), dtype=np.uint8))

    result = YoloxDetector(FakeSession()).detect_file(path)

    assert (result.image_width, result.image_height) == (64, 48)
    assert result.detections == ()


@pytest.mark.parametrize("content", [None, b"", b"not an image"])
def test_unreadable_image_raises_and_logs(tmp_path, content, caplog):
    path = tmp_path / "frame.jpg"
    if content is not None:
        path.write_bytes(content)

    with caplog.at_level(logging.ERROR), pytest.raises(DetectorError):
        YoloxDetector(FakeSession()).detect_file(path)

    assert "detector_error stage=read" in caplog.text
    assert "frame.jpg" in caplog.text


def test_from_weights_requests_only_the_cpu_provider(tmp_path, monkeypatch):
    weights = tmp_path / "model.onnx"
    weights.write_bytes(b"x")
    calls = []

    def fake_session(path, providers):
        calls.append((path, providers))
        return FakeSession()

    monkeypatch.setattr(yolox.onnxruntime, "InferenceSession", fake_session)

    YoloxDetector.from_weights(weights)

    assert calls == [(str(weights), ["CPUExecutionProvider"])]


def test_detector_rejects_a_session_running_outside_cpu():
    session = FakeSession()
    session.get_providers = lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"]

    with pytest.raises(DetectorError, match="CPU"):
        YoloxDetector(session)


def test_from_weights_missing_file_raises_and_logs(tmp_path, caplog):
    with caplog.at_level(logging.ERROR), pytest.raises(DetectorError, match="not found"):
        YoloxDetector.from_weights(tmp_path / "missing.onnx")

    assert "detector_error stage=load" in caplog.text


def test_from_weights_corrupt_file_raises_and_logs(tmp_path, caplog):
    weights = tmp_path / "corrupt.onnx"
    weights.write_bytes(b"not an onnx model")

    with caplog.at_level(logging.ERROR), pytest.raises(DetectorError):
        YoloxDetector.from_weights(weights)

    assert "detector_error stage=load" in caplog.text


def test_result_serializes_to_plain_json():
    result = DetectionResult(
        image_path="frame.jpg",
        image_width=640,
        image_height=480,
        detections=(Detection("person", 0.87, (1.0, 2.0, 3.0, 4.0)),),
    )

    assert json.loads(json.dumps(result.to_dict())) == {
        "image_path": "frame.jpg",
        "image_width": 640,
        "image_height": 480,
        "detections": [
            {"class_name": "person", "confidence": 0.87, "bbox_xyxy": [1.0, 2.0, 3.0, 4.0]}
        ],
    }


def test_coco_classes_cover_the_policy_obstacle_classes():
    obstacles = {"person", "bicycle", "car", "motorcycle", "bus", "truck", "cat", "dog"}

    assert len(COCO_CLASSES) == 80
    assert obstacles <= set(COCO_CLASSES)


def test_cli_prints_json_and_uses_the_given_paths(tmp_path, monkeypatch, capsys):
    path = write_png(tmp_path / "frame.png", image(64, 48))
    raw = raw_output((0, 100, 100, 50, 50, 1.0, PERSON, 0.9))
    received = {}

    def fake_from_weights(weights, **kwargs):
        received.update(weights=weights, **kwargs)
        return YoloxDetector(FakeSession(raw), **kwargs)

    monkeypatch.setattr(cli.YoloxDetector, "from_weights", fake_from_weights)

    code = cli.main(["--weights", "w.onnx", "--image", str(path), "--score-threshold", "0.4"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert received == {
        "weights": "w.onnx",
        "score_threshold": 0.4,
        "nms_threshold": 0.45,
        "median_kernel": 3,
    }
    assert payload["image_path"] == str(path)
    assert payload["detections"][0]["class_name"] == "person"


def cli_tensor(tmp_path, monkeypatch, capsys, *extra):
    """Corre el comando con una sesion simulada y devuelve lo que recibio el modelo."""
    weights = tmp_path / "w.onnx"
    weights.write_bytes(b"pesos")
    path = tmp_path / "frame.png"
    pixels = np.random.default_rng(0).integers(0, 256, (120, 160, 3), dtype=np.uint8)
    cv2.imwrite(str(path), pixels)
    session = FakeSession()
    monkeypatch.setattr(yolox.onnxruntime, "InferenceSession", lambda *_a, **_k: session)

    code = cli.main(["--weights", str(weights), "--image", str(path), *extra])

    assert code == 0
    assert json.loads(capsys.readouterr().out)["detections"] == []
    return session.tensors[0], pixels


def test_cli_with_filter_zero_sends_the_original_image_to_the_model(tmp_path, monkeypatch, capsys):
    tensor, pixels = cli_tensor(tmp_path, monkeypatch, capsys, "--filtro-mediana", "0")

    expected, _ratio = preprocess(pixels, INPUT_SIZE)
    assert np.array_equal(tensor[0], expected)


def test_cli_filters_the_image_by_default(tmp_path, monkeypatch, capsys):
    tensor, pixels = cli_tensor(tmp_path, monkeypatch, capsys)

    filtered, _ratio = preprocess(cv2.medianBlur(pixels, 3), INPUT_SIZE)
    original, _ratio = preprocess(pixels, INPUT_SIZE)
    assert np.array_equal(tensor[0], filtered)
    assert not np.array_equal(tensor[0], original)


def test_cli_rejects_an_invalid_filter_without_printing_json(tmp_path, monkeypatch, capsys):
    weights = tmp_path / "w.onnx"
    weights.write_bytes(b"pesos")
    monkeypatch.setattr(yolox.onnxruntime, "InferenceSession", lambda *_a, **_k: FakeSession())

    code = cli.main(["--weights", str(weights), "--image", "frame.png", "--filtro-mediana", "4"])

    assert code == 1
    assert capsys.readouterr().out == ""


def test_cli_returns_non_zero_and_prints_no_json_on_error(tmp_path, capsys):
    code = cli.main(["--weights", str(tmp_path / "missing.onnx"), "--image", "frame.jpg"])

    assert code == 1
    assert capsys.readouterr().out == ""
