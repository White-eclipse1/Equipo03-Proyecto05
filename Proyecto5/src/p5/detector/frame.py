import json
from dataclasses import asdict, dataclass
from math import isfinite
from pathlib import Path
from typing import Any, Literal

from p5.detector.models import Detection
from p5.detector.yolox import DetectorError, YoloxDetector


@dataclass(frozen=True)
class PerceptionFrame:
    """Un cuadro del contrato A -> B. Ver `docs/A1-03_CONTRATO.md`."""

    sequence_id: str
    frame_id: str
    # Tiempo relativo al inicio de la secuencia.
    t_capture_ms: float
    image_width: int
    image_height: int
    status: Literal["ok", "error"]
    detections: tuple[Detection, ...]
    error: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), allow_nan=False)


def detect_frame(
    detector: YoloxDetector,
    image_path: str | Path,
    *,
    sequence_id: str,
    frame_id: str,
    t_capture_ms: float,
    image_size: tuple[int, int],
) -> PerceptionFrame:
    """Detecta sobre una imagen y entrega el cuadro del contrato.

    Un fallo del detector produce `status="error"`, nunca una lista vacia indistinguible
    de una escena despejada. `image_size` es (ancho, alto) esperado: solo se usa si la
    imagen no se puede leer, porque el contrato exige dimensiones tambien en un error.
    """
    if not sequence_id or not frame_id:
        raise ValueError("sequence_id and frame_id must not be empty")
    if not isfinite(t_capture_ms) or t_capture_ms < 0:
        raise ValueError("t_capture_ms must be finite and not negative")
    width, height = image_size
    if width <= 0 or height <= 0:
        raise ValueError("image_size must be positive")

    source = str(image_path)
    status: Literal["ok", "error"] = "ok"
    detections: tuple[Detection, ...] = ()
    error = None
    try:
        image = detector.read_image(source)
        height, width = image.shape[:2]
        detections = detector.detect_image(image, source=source)
    except DetectorError as failure:
        status = "error"
        error = str(failure)

    return PerceptionFrame(
        sequence_id=sequence_id,
        frame_id=frame_id,
        t_capture_ms=t_capture_ms,
        image_width=width,
        image_height=height,
        status=status,
        detections=detections,
        error=error,
    )
