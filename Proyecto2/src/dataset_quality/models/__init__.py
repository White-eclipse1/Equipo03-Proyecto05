"""Modelos Pydantic v2 de la frontera de datos (Frente 2 de la rubrica).

Cubre el COCO crudo que produce el proyecto de anotacion (MP1), la
configuracion de calidad (`quality.yaml`) y los tres contratos de salida que
consumen los frentes siguientes: `quality.json`, `splits.json` y
`versions.json`. Todos comparten una base estricta: campos desconocidos
rechazados y valores inmutables una vez validados.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from dataset_quality.models.errors import DatasetValidationError, FieldIssue, from_pydantic


class StrictModel(BaseModel):
    """Base comun: sin campos extra, inmutable, strings sin espacios colgantes."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


__all__ = [
    "DatasetValidationError",
    "FieldIssue",
    "StrictModel",
    "from_pydantic",
]
