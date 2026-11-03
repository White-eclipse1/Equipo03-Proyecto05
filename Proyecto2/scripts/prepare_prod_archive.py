"""Reconstruye exactamente el release validado con datos recuperados por DVC."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dataset_quality.analyzers import run_all
from dataset_quality.models.coco import load_coco
from dataset_quality.models.quality import QualityConfig
from dataset_quality.tiers import promote, release
from dataset_quality.tiers.gate import blocking, dataset_fingerprint


def prepare(version: str) -> Path:
    manifest = release.load_manifest()
    entry = next((v for v in manifest.versions if v.version == version), None)
    if entry is None or entry.archive_sha256 is None:
        raise ValueError("La version debe existir y registrar el SHA-256 del archivo original")
    coco = Path("data/raw/annotations.coco.json")
    dataset = load_coco(coco)
    if dataset_fingerprint(dataset) != entry.dataset_fingerprint:
        raise ValueError("El dataset recuperado de PROD no coincide con el validado localmente")
    checks = run_all(dataset, QualityConfig.from_yaml(Path("quality.yaml")), coco.parent / "images")
    if blocking(checks):
        raise ValueError("El dataset recuperado no pasa la compuerta de calidad vigente")
    # La deduplicacion local escribe exactamente esta representacion del COCO.
    coco.write_text(
        json.dumps(json.loads(dataset.model_dump_json(exclude_none=True)), indent=1),
        encoding="utf-8",
        newline="\n",
    )
    archive = release.build_archive(
        coco_path=coco,
        quality_path=Path("reports/quality.json"),
        splits_path=Path("reports/splits.json"),
        dest=Path("reports/releases") / version / release.ARCHIVE_NAME,
    )
    promote.verify_archive(archive, entry)
    print(f"v{version}: dataset y archivo identicos al release validado localmente")
    return archive


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    prepare(parser.parse_args().version)
