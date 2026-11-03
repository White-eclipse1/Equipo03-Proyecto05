"""Estadistica descriptiva del dataset.

Va aparte de `QualityReport` porque no es una compuerta: no tiene umbral ni
puede fallar. Es el contexto que la app web necesita para dibujar el resumen y
que un humano necesita para entender contra que se esta comparando un umbral.
"""

from __future__ import annotations

from pydantic import Field

from dataset_quality.models import StrictModel
from dataset_quality.models.quality import CheckResult, QualityTotals


class DatasetStats(StrictModel):
    """Resumen descriptivo. Sin juicio: solo describe lo que hay."""

    totals: QualityTotals

    # Imagenes DISTINTAS que contienen al menos una caja de cada clase. Es la
    # metrica que exige el curso, y no es lo mismo que contar cajas.
    images_per_class: dict[str, int] = Field(default_factory=dict)
    boxes_per_class: dict[str, int] = Field(default_factory=dict)

    annotations_per_image: float = Field(ge=0.0)
    images_without_annotations: int = Field(ge=0)

    # Area de la caja relativa a su imagen. Da la escala en la que hay que leer
    # el umbral de `small_objects`.
    #
    # Van las tres cifras y no solo una porque la distribucion esta sesgada: en
    # un dataset con muchos objetos diminutos y unos pocos enormes, la media se
    # va detras de los grandes y la mediana no dice nada de esa cola. La media
    # por encima de la mediana es, precisamente, la senal de que la cola larga
    # existe; el percentil 90 dice cuanto llega a estirarse.
    mean_box_area_ratio: float = Field(ge=0.0, le=1.0)
    median_box_area_ratio: float = Field(ge=0.0, le=1.0)
    p90_box_area_ratio: float = Field(ge=0.0, le=1.0)


class AnalysisArtifact(StrictModel):
    """Contrato del artefacto descriptivo que escribe ``dq analyze --json``.

    No es un contrato congelado de release, pero el Copilot nunca debe leerlo
    como JSON sin validar: una cifra sin un artefacto valido no es evidencia.
    """

    stats: DatasetStats
    checks: list[CheckResult]
