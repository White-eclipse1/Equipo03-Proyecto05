"""Proyeccion 2D precomputada de las imagenes del dataset.

No es un check: no tiene umbral y no puede fallar. Produce el cuarto artefacto
de salida, que consume la pantalla de exploracion de la app web.

PCA esta implementado con numpy (centrar, covarianza, eigendescomposicion) en
lugar de traer scikit-learn: son seis lineas, el resultado es determinista, y
scikit-learn pesa mas que todas las demas dependencias juntas. Para t-SNE si
haria falta una libreria — no es algo que convenga escribir a mano — y por eso
el metodo viaja en el contrato: cuando se anada, la pantalla no cambia.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from PIL import Image, UnidentifiedImageError

from dataset_quality.models.coco import CocoDataset
from dataset_quality.models.exploration import ExplorationManifest, ExplorationPoint

HIST_BINS = 8
THUMB = 8
METHOD_DETAIL = (
    "histograma de color RGB de 8 celdas por canal mas una miniatura en escala "
    "de grises de 8x8. Agrupa por color y composicion, no por significado."
)


def feature_vector(path: Path) -> np.ndarray:
    """Vector descriptivo de una imagen: 24 numeros de color y 64 de forma."""
    with Image.open(path) as handle:
        rgb = handle.convert("RGB")
        thumbnail = np.asarray(
            rgb.convert("L").resize((THUMB, THUMB), Image.Resampling.LANCZOS),
            dtype=np.float64,
        ).ravel()
        channels = np.asarray(rgb.resize((64, 64), Image.Resampling.LANCZOS), dtype=np.float64)

    histogram = np.concatenate(
        [np.histogram(channels[:, :, c], bins=HIST_BINS, range=(0, 255))[0] for c in range(3)]
    ).astype(np.float64)
    # Normalizar: sin esto una foto grande domina solo por tener mas pixeles.
    histogram /= max(histogram.sum(), 1.0)

    return np.concatenate([histogram, thumbnail / 255.0])


def pca_2d(vectors: np.ndarray) -> tuple[np.ndarray, float]:
    """Proyecta a 2D y devuelve tambien la varianza explicada.

    La varianza explicada es la mitad util del resultado: dice si los dos ejes
    conservan informacion o si el grafico es ruido con forma de nube.
    """
    if vectors.shape[0] < 2:
        return np.zeros((vectors.shape[0], 2)), 0.0

    centered = vectors - vectors.mean(axis=0)
    eigenvalues, eigenvectors = np.linalg.eigh(np.cov(centered, rowvar=False))
    orden = np.argsort(eigenvalues)[::-1]

    total = float(eigenvalues.sum())
    explicada = float(eigenvalues[orden[:2]].sum() / total) if total > 0 else 0.0

    # El error numerico puede sacar la proporcion levemente fuera de [0, 1].
    return centered @ eigenvectors[:, orden[:2]], min(max(explicada, 0.0), 1.0)


def dominant_category(dataset: CocoDataset) -> dict[int, int]:
    """Clase de la primera caja de cada imagen. Solo sirve para colorear."""
    dominante: dict[int, int] = {}
    for annotation in dataset.annotations:
        dominante.setdefault(annotation.image_id, annotation.category_id)
    return dominante


def build(dataset: CocoDataset, images_dir: Path, seed: int = 42) -> ExplorationManifest:
    """Calcula la proyeccion de las imagenes que esten en disco.

    Una imagen ausente o ilegible se omite en vez de romper el calculo: que la
    descarga este incompleta es problema del Tier 1, no de este modulo.
    """
    dominante = dominant_category(dataset)

    ids: list[int] = []
    file_names: list[str] = []
    vectors: list[np.ndarray] = []
    for image in dataset.images:
        path = images_dir / image.file_name
        if not path.is_file():
            continue
        try:
            vectors.append(feature_vector(path))
        except (UnidentifiedImageError, OSError):
            continue
        ids.append(image.id)
        file_names.append(image.file_name)

    if vectors:
        projected, explicada = pca_2d(np.vstack(vectors))
    else:
        projected, explicada = np.zeros((0, 2)), 0.0

    return ExplorationManifest(
        generated_at=datetime.now(UTC),
        method="pca",
        seed=seed,
        variance_explained=round(explicada, 4),
        method_detail=METHOD_DETAIL,
        points=[
            ExplorationPoint(
                image_id=image_id,
                x=round(float(coords[0]), 5),
                y=round(float(coords[1]), 5),
                category_id=dominante.get(image_id),
                file_name=file_name,
            )
            for image_id, file_name, coords in zip(ids, file_names, projected, strict=True)
        ],
    )
