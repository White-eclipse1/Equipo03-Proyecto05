from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Detection:
    class_name: str
    confidence: float
    # Pixeles de la imagen original, con origen arriba a la izquierda.
    bbox_xyxy: tuple[float, float, float, float]


@dataclass(frozen=True)
class DetectionResult:
    image_path: str
    image_width: int
    image_height: int
    detections: tuple[Detection, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
