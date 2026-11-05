"""Filtro de mediana opcional antes del detector, para medir la propuesta de B1-03.

Vive fuera de `p5.detector` porque es una prueba: mientras no se adopte, el detector y la evidencia
de metricas de A3 no cambian. Ver `docs/B1-03_DETECTOR.md`.
"""

import cv2
import numpy as np

from p5.detector.models import Detection
from p5.detector.yolox import DetectorError, YoloxDetector

NO_MEDIAN_FILTER = 0


class MedianFilterDetector:
    """Filtra cada imagen y delega en el detector, con la misma interfaz que usa el recorrido."""

    def __init__(self, detector: YoloxDetector, kernel: int) -> None:
        if kernel < 3 or kernel % 2 == 0:
            raise ValueError("el filtro de mediana necesita un tamano impar desde 3")
        self._detector = detector
        self._kernel = kernel

    def read_image(self, path: str) -> np.ndarray:
        return self._detector.read_image(path)

    def detect_image(self, image: np.ndarray, *, source: str = "array") -> tuple[Detection, ...]:
        try:
            filtered = cv2.medianBlur(image, self._kernel)
        except cv2.error as error:
            # Igual que un fallo del detector: se registra y detiene, nunca es escena vacia.
            raise DetectorError(f"median filter failed for {source}: {error}") from error
        return self._detector.detect_image(filtered, source=source)
