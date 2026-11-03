"""Estadistica descriptiva del dataset.

No es una compuerta: no tiene umbral y no puede fallar. Da el contexto sin el
cual un umbral no significa nada — saber que el 41% de las cajas son diminutas
solo es util si tambien se sabe cuantas cajas hay y como se reparten.
"""

from __future__ import annotations

from collections import defaultdict
from statistics import fmean, median

from dataset_quality.analyzers.structural import images_per_class
from dataset_quality.models.coco import CocoDataset
from dataset_quality.models.quality import QualityTotals
from dataset_quality.models.stats import DatasetStats


def percentile(values: list[float], fraction: float) -> float:
    """Percentil por interpolacion lineal entre los dos valores vecinos.

    No se usa `statistics.quantiles` porque exige dos puntos y devuelve los
    cortes de una particion completa; aqui hace falta un solo corte y con una
    sola caja el percentil es esa caja.
    """
    if not values:
        return 0.0
    ordenados = sorted(values)
    if len(ordenados) == 1:
        return ordenados[0]

    posicion = fraction * (len(ordenados) - 1)
    bajo = int(posicion)
    alto = min(bajo + 1, len(ordenados) - 1)
    return ordenados[bajo] + (ordenados[alto] - ordenados[bajo]) * (posicion - bajo)


def describe(dataset: CocoDataset) -> DatasetStats:
    """Resume el dataset sin emitir ningun juicio sobre el."""
    names = {category.id: category.name for category in dataset.categories}

    boxes_per_class: dict[str, int] = defaultdict(int)
    anotadas: set[int] = set()
    ratios: list[float] = []
    sizes = {image.id: image.width * image.height for image in dataset.images}

    for annotation in dataset.annotations:
        boxes_per_class[names[annotation.category_id]] += 1
        anotadas.add(annotation.image_id)
        ratios.append(annotation.area / sizes[annotation.image_id])

    total_images = len(dataset.images)

    return DatasetStats(
        totals=QualityTotals(
            images=total_images,
            annotations=len(dataset.annotations),
            categories=len(dataset.categories),
        ),
        images_per_class=images_per_class(dataset),
        boxes_per_class={name: boxes_per_class.get(name, 0) for name in sorted(names.values())},
        annotations_per_image=len(dataset.annotations) / total_images if total_images else 0.0,
        images_without_annotations=total_images - len(anotadas),
        mean_box_area_ratio=fmean(ratios) if ratios else 0.0,
        median_box_area_ratio=median(ratios) if ratios else 0.0,
        p90_box_area_ratio=percentile(ratios, 0.90),
    )
