"""Los cinco analizadores de calidad (Frente 3) y la descriptiva.

Los analizadores solo MIDEN. La decision de bloquear un release es del Frente 4:
esta separacion es deliberada, porque cambiar un umbral no debe obligar a
recalcular las metricas.
"""

from __future__ import annotations

from pathlib import Path

from dataset_quality.analyzers.descriptive import describe, percentile
from dataset_quality.analyzers.duplicates import (
    analyze_duplicates,
    compute_hashes,
    duplicate_groups,
    find_pairs,
    hamming,
    perceptual_hash,
)
from dataset_quality.analyzers.structural import (
    analyze_class_imbalance,
    analyze_degenerate_boxes,
    analyze_min_images_per_class,
    analyze_small_objects,
    analyze_spatial_bias,
    images_per_class,
)
from dataset_quality.models.coco import CocoDataset
from dataset_quality.models.quality import CheckResult, QualityConfig

__all__ = [
    "CheckResult",
    "analyze_class_imbalance",
    "analyze_degenerate_boxes",
    "analyze_duplicates",
    "analyze_min_images_per_class",
    "analyze_small_objects",
    "analyze_spatial_bias",
    "compute_hashes",
    "describe",
    "duplicate_groups",
    "find_pairs",
    "hamming",
    "images_per_class",
    "percentile",
    "perceptual_hash",
    "run_all",
]


def run_all(dataset: CocoDataset, config: QualityConfig, images_dir: Path) -> list[CheckResult]:
    """Corre los cinco analizadores en el orden que declara `QualityConfig`.

    Los desactivados devuelven `status="skipped"` en vez de desaparecer: el
    reporte debe decir que una regla no se evaluo, no callarselo.
    """
    return [
        analyze_min_images_per_class(dataset, config.min_images_per_class),
        analyze_small_objects(dataset, config.small_objects),
        analyze_class_imbalance(dataset, config.class_imbalance),
        analyze_duplicates(dataset, config.duplicates, images_dir),
        analyze_degenerate_boxes(dataset, config.degenerate_boxes),
        analyze_spatial_bias(dataset, config.spatial_bias),
    ]
