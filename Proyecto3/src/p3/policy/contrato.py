"""Contrato A -> B: un cuadro con sus detecciones, tal como lo consume la politica.

Propuesta de B1 para A1-03 (ver `docs/politica.md` §Contrato). Cajas `xyxy` en
pixeles del cuadro ORIGINAL, origen en la esquina superior izquierda, x crece a
la derecha e y hacia abajo. Un cuadro sin objetos es `status="ok"` con lista
vacia; un fallo del detector es `status="error"` con mensaje y sin detecciones,
para que nunca se confunda con una escena despejada.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Margen para el redondeo del posprocesamiento del detector en el borde del cuadro.
TOLERANCIA_BORDE_PX = 1.0

Coordenada = float


class Deteccion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    class_name: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    bbox_xyxy: tuple[Coordenada, Coordenada, Coordenada, Coordenada]

    @model_validator(mode="after")
    def _caja_ordenada(self) -> Deteccion:
        x1, y1, x2, y2 = self.bbox_xyxy
        if not (x2 > x1 and y2 > y1):
            raise ValueError("bbox_xyxy debe cumplir x2 > x1 e y2 > y1")
        return self


class Cuadro(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, allow_inf_nan=False, coerce_numbers_to_str=True
    )

    sequence_id: str = Field(min_length=1)
    frame_id: str = Field(min_length=1)
    # Tiempo relativo al inicio de la secuencia; la politica exige que crezca.
    t_capture_ms: float = Field(ge=0)
    image_width: int = Field(gt=0)
    image_height: int = Field(gt=0)
    status: Literal["ok", "error"]
    # Obligatorio si status=ok (ver `_detections_explicito`); con status=error puede
    # omitirse y queda vacio.
    detections: tuple[Deteccion, ...] = ()
    error: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _detections_explicito(cls, datos: object) -> object:
        # Omitir `detections` NO significa "sin objetos": eso es la lista vacia [].
        if isinstance(datos, dict) and datos.get("status") == "ok" and "detections" not in datos:
            raise ValueError("status=ok exige `detections` explicito ([] si no hay objetos)")
        return datos

    @model_validator(mode="after")
    def _estado_coherente(self) -> Cuadro:
        if self.status == "error":
            if not self.error:
                raise ValueError("status=error exige un mensaje en `error`")
            if self.detections:
                raise ValueError("status=error no admite detecciones")
        elif self.error is not None:
            raise ValueError("status=ok no admite `error`")
        tol = TOLERANCIA_BORDE_PX
        ancho, alto = self.image_width + tol, self.image_height + tol
        for i, det in enumerate(self.detections):
            x1, y1, x2, y2 = det.bbox_xyxy
            if x1 < -tol or y1 < -tol or x2 > ancho or y2 > alto:
                raise ValueError(f"detections[{i}].bbox_xyxy sale del cuadro")
        return self
