import logging
from pathlib import Path
from typing import Any, Self

import cv2
import numpy as np
import onnxruntime

from p5.detector.coco_classes import COCO_CLASSES
from p5.detector.models import Detection, DetectionResult

logger = logging.getLogger(__name__)

CPU_PROVIDER = "CPUExecutionProvider"
DEFAULT_SCORE_THRESHOLD = 0.10
DEFAULT_NMS_THRESHOLD = 0.45

_STRIDES = (8, 16, 32)
_PAD_VALUE = 114
_BOX_CHANNELS = 5  # cx, cy, w, h y objectness, antes de las clases.


class DetectorError(RuntimeError):
    pass


def _failure(stage: str, source: str, detail: object) -> DetectorError:
    logger.error("detector_error stage=%s source=%s detail=%s", stage, source, detail)
    return DetectorError(f"{stage} failed for {source}: {detail}")


def preprocess(image: np.ndarray, input_size: tuple[int, int]) -> tuple[np.ndarray, float]:
    """Redimensiona sin deformar y rellena abajo y a la derecha, como el demo de YOLOX.

    Conserva BGR y valores 0-255: estos pesos no usan media ni desviacion.
    """
    input_height, input_width = input_size
    height, width = image.shape[:2]
    ratio = min(input_height / height, input_width / width)
    new_height = max(1, int(height * ratio))
    new_width = max(1, int(width * ratio))

    resized = cv2.resize(image, (new_width, new_height), interpolation=cv2.INTER_LINEAR)
    padded = np.full((input_height, input_width, 3), _PAD_VALUE, dtype=np.uint8)
    padded[:new_height, :new_width] = resized

    return padded.transpose(2, 0, 1).astype(np.float32), ratio


def _decode(raw: np.ndarray, input_size: tuple[int, int]) -> np.ndarray:
    """Convierte la salida por celda de la malla en cajas cx, cy, w, h en pixeles de entrada."""
    grids = []
    strides = []
    for stride in _STRIDES:
        rows = input_size[0] // stride
        cols = input_size[1] // stride
        xv, yv = np.meshgrid(np.arange(cols), np.arange(rows))
        grids.append(np.stack((xv, yv), axis=2).reshape(-1, 2))
        strides.append(np.full((rows * cols, 1), stride))
    grid = np.concatenate(grids)
    stride = np.concatenate(strides)

    decoded = raw.astype(np.float64)
    decoded[:, :2] = (decoded[:, :2] + grid) * stride
    with np.errstate(over="ignore"):
        decoded[:, 2:4] = np.exp(decoded[:, 2:4]) * stride
    return decoded


def _nms(boxes: np.ndarray, scores: np.ndarray, threshold: float) -> list[int]:
    x1, y1, x2, y2 = boxes.T
    areas = (x2 - x1 + 1) * (y2 - y1 + 1)
    order = np.argsort(-scores, kind="stable")

    keep = []
    while order.size > 0:
        best, rest = order[0], order[1:]
        keep.append(int(best))
        width = np.maximum(0.0, np.minimum(x2[best], x2[rest]) - np.maximum(x1[best], x1[rest]) + 1)
        height = np.maximum(
            0.0, np.minimum(y2[best], y2[rest]) - np.maximum(y1[best], y1[rest]) + 1
        )
        intersection = width * height
        iou = intersection / (areas[best] + areas[rest] - intersection)
        order = rest[iou <= threshold]
    return keep


class YoloxDetector:
    """Detector YOLOX en ONNX Runtime, restringido a CPU."""

    def __init__(
        self,
        session: Any,
        *,
        score_threshold: float = DEFAULT_SCORE_THRESHOLD,
        nms_threshold: float = DEFAULT_NMS_THRESHOLD,
    ) -> None:
        if not 0.0 <= score_threshold <= 1.0:
            raise ValueError("score_threshold must be between 0.0 and 1.0")
        if not 0.0 <= nms_threshold <= 1.0:
            raise ValueError("nms_threshold must be between 0.0 and 1.0")

        providers = session.get_providers()
        if providers != [CPU_PROVIDER]:
            raise _failure("load", "session", f"expected CPU only, got {providers}")

        model_input = session.get_inputs()[0]
        self._session = session
        self._input_name = model_input.name
        self._input_size = self._parse_input_size(model_input.shape)
        self._score_threshold = score_threshold
        self._nms_threshold = nms_threshold

    @classmethod
    def from_weights(
        cls,
        weights: str | Path,
        *,
        score_threshold: float = DEFAULT_SCORE_THRESHOLD,
        nms_threshold: float = DEFAULT_NMS_THRESHOLD,
    ) -> Self:
        path = Path(weights)
        if not path.is_file():
            raise _failure("load", str(path), "weights file not found")
        try:
            session = onnxruntime.InferenceSession(str(path), providers=[CPU_PROVIDER])
        except Exception as error:
            raise _failure("load", str(path), error) from error
        return cls(session, score_threshold=score_threshold, nms_threshold=nms_threshold)

    def detect_file(self, path: str | Path) -> DetectionResult:
        image = self.read_image(str(path))
        detections = self.detect_image(image, source=str(path))
        return DetectionResult(
            image_path=str(path),
            image_width=image.shape[1],
            image_height=image.shape[0],
            detections=detections,
        )

    def detect_image(self, image: np.ndarray, *, source: str = "array") -> tuple[Detection, ...]:
        """Detecta sobre una imagen BGR completa. Una escena sin objetos devuelve `()`."""
        if image.ndim != 3 or image.shape[2] != 3 or image.size == 0:
            raise _failure("preprocess", source, f"expected HxWx3 image, got {image.shape}")

        tensor, ratio = self._preprocess(image, source)
        raw = self._infer(tensor, source)
        return self._postprocess(raw, ratio, image.shape[:2], source)

    def _preprocess(self, image: np.ndarray, source: str) -> tuple[np.ndarray, float]:
        try:
            return preprocess(image, self._input_size)
        except cv2.error as error:
            raise _failure("preprocess", source, error) from error

    def _infer(self, tensor: np.ndarray, source: str) -> np.ndarray:
        try:
            return self._session.run(None, {self._input_name: tensor[np.newaxis]})[0]
        except Exception as error:
            raise _failure("inference", source, error) from error

    def _postprocess(
        self, raw: np.ndarray, ratio: float, image_size: tuple[int, int], source: str
    ) -> tuple[Detection, ...]:
        cells = sum(
            (self._input_size[0] // stride) * (self._input_size[1] // stride) for stride in _STRIDES
        )
        expected_shape = (1, cells, _BOX_CHANNELS + len(COCO_CLASSES))
        if raw.shape != expected_shape:
            raise _failure(
                "postprocess", source, f"output shape {raw.shape}, expected {expected_shape}"
            )

        decoded = _decode(raw[0], self._input_size)
        if not np.isfinite(decoded).all():
            raise _failure("postprocess", source, "non-finite model output")
        probabilities = decoded[:, 4:]
        if probabilities.min() < 0.0 or probabilities.max() > 1.0:
            raise _failure("postprocess", source, "scores outside [0, 1]")

        class_indices = probabilities[:, 1:].argmax(axis=1)
        scores = probabilities[:, 0] * probabilities[np.arange(cells), class_indices + 1]
        candidates = scores > self._score_threshold
        if not candidates.any():
            return ()

        centers, sizes = decoded[candidates, :2], decoded[candidates, 2:4]
        boxes = np.concatenate((centers - sizes / 2, centers + sizes / 2), axis=1) / ratio
        kept_scores = scores[candidates]
        kept_classes = class_indices[candidates]

        height, width = image_size
        boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, width)
        boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, height)

        detections = []
        for index in _nms(boxes, kept_scores, self._nms_threshold):
            x1, y1, x2, y2 = (float(value) for value in boxes[index])
            # Una caja que solo cae en el relleno queda sin area al recortarla.
            if x2 > x1 and y2 > y1:
                detections.append(
                    Detection(
                        class_name=COCO_CLASSES[kept_classes[index]],
                        confidence=float(kept_scores[index]),
                        bbox_xyxy=(x1, y1, x2, y2),
                    )
                )
        return tuple(detections)

    @staticmethod
    def _parse_input_size(shape: list[Any]) -> tuple[int, int]:
        if len(shape) != 4 or not all(isinstance(dim, int) and dim > 0 for dim in shape[2:]):
            raise _failure("load", "session", f"unsupported model input shape {shape}")
        height, width = shape[2], shape[3]
        if height % _STRIDES[-1] or width % _STRIDES[-1]:
            raise _failure("load", "session", f"model input {shape} not divisible by stride")
        return height, width

    @staticmethod
    def read_image(path: str) -> np.ndarray:
        # `imread` no abre rutas con caracteres no ASCII en Windows.
        try:
            image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        except (OSError, cv2.error) as error:
            raise _failure("read", path, error) from error
        if image is None:
            raise _failure("read", path, "file is not a decodable image")
        return image
