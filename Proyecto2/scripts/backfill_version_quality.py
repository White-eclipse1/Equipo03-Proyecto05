"""Recupera metricas de un dataset historico presente como prefijo del COCO.

Exige la misma huella canonica del release antes de reutilizar sus datos.
Los objetos pequenos se miden con la politica vigente para comparar ambas
versiones bajo la misma definicion. No modifica las huellas originales.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from dataset_quality.analyzers import analyze_small_objects
from dataset_quality.models.coco import CocoDataset, load_coco
from dataset_quality.models.quality import QualityConfig
from dataset_quality.models.versions import VersionQualitySummary, VersionsManifest
from dataset_quality.tiers.gate import dataset_fingerprint
from dataset_quality.tiers.release import load_manifest, write_manifest


def backfill(version: str, dataset_path: Path, config_path: Path, out: Path) -> None:
    manifest = load_manifest(out)
    entry = next((v for v in manifest.versions if v.version == version), None)
    if entry is None:
        raise ValueError(f"Version desconocida: {version}")
    dataset = load_coco(dataset_path)
    images = dataset.images[: entry.counts.images]
    ids = {i.id for i in images}
    historical = CocoDataset(
        images=images,
        annotations=[a for a in dataset.annotations if a.image_id in ids],
        categories=dataset.categories,
    )
    if dataset_fingerprint(historical) != entry.dataset_fingerprint:
        raise ValueError("El prefijo no coincide exactamente con el dataset historico")
    from dataset_quality.analyzers import images_per_class

    config = QualityConfig.from_yaml(config_path)
    small = analyze_small_objects(historical, config.small_objects)
    summary = VersionQualitySummary(
        distinct_images_per_class=images_per_class(historical),
        small_objects_ratio=small.observed if small.status != "skipped" else None,
    )
    recovered = entry.model_copy(update={"quality_summary": summary})
    updated = VersionsManifest(
        versions=[recovered if v.version == version else v for v in manifest.versions]
    )
    write_manifest(updated, out)
    print(f"v{version}: dataset historico verificado; resumen recuperado")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    parser.add_argument("--dataset", type=Path, default=Path("data/raw/annotations.coco.json"))
    parser.add_argument("--config", type=Path, default=Path("quality.yaml"))
    parser.add_argument("--out", type=Path, default=Path("reports/versions.json"))
    args = parser.parse_args()
    backfill(args.version, args.dataset, args.config, args.out)


if __name__ == "__main__":
    main()
