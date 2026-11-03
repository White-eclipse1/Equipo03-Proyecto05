"""Eliminacion de los casi-duplicados que encontro el Tier 2.

Es la unica operacion de la plataforma que MODIFICA el dataset crudo, asi que
se disena con tres cautelas:

**No borra bytes.** Las imagenes sobrantes se mueven a `data/quarantine/`, no
se eliminan. Un falso positivo del pHash se deshace moviendolas de vuelta; un
`rm` no se deshace.

**No decide sola cuales sobran.** El conjunto a eliminar sale de los
`offenders` del check `duplicates` de `quality.json` — exactamente los mismos
que muestra la pantalla. De cada grupo de copias sobrevive el id mas bajo, que
es el que se subio primero.

**Se niega a trabajar sobre un reporte obsoleto.** Antes de tocar nada compara
la huella del dataset en disco con la que declara el reporte. Si alguien anadio
imagenes despues de correr la compuerta, los `offenders` ya no apuntan a lo que
se cree y la operacion aborta.

Despues de correrla, todos los artefactos quedan obsoletos por definicion: el
dataset cambio. Hay que volver a correr el pipeline, y `data/raw.dvc` hay que
regenerarlo con `dvc add data/raw`.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from dataset_quality.models.coco import CocoDataset
from dataset_quality.models.quality import QualityReport
from dataset_quality.tiers.gate import dataset_fingerprint

REPO_ROOT = Path(__file__).resolve().parents[3]
QUARANTINE = REPO_ROOT / "data" / "quarantine"


class DedupeError(RuntimeError):
    """La operacion no puede ejecutarse con seguridad."""


@dataclass(frozen=True)
class DedupePlan:
    """Que se eliminaria. Construirlo no toca nada en disco."""

    remove_ids: list[int]
    remove_files: list[str]
    annotations_removed: int
    total_images: int
    fingerprint: str

    @property
    def is_empty(self) -> bool:
        return not self.remove_ids

    @property
    def kept(self) -> int:
        return self.total_images - len(self.remove_ids)


@dataclass
class DedupeResult:
    """Que se elimino de verdad."""

    removed_images: int
    removed_annotations: int
    quarantined: list[str] = field(default_factory=list)
    missing_on_disk: list[str] = field(default_factory=list)
    remaining_images: int = 0
    quarantine_dir: str = ""


def _ruta_legible(destino: Path) -> str:
    """Ruta relativa al repositorio; absoluta si cae fuera (pruebas, discos distintos)."""
    try:
        return destino.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return destino.as_posix()


def duplicates_check(report: QualityReport):
    """El check `duplicates` del reporte, o `None` si no se evaluo."""
    for check in report.checks:
        if check.name == "duplicates":
            return check
    return None


def build_plan(dataset: CocoDataset, report: QualityReport) -> DedupePlan:
    """Deriva el plan del reporte. Aborta si el reporte ya no describe el dataset."""
    actual = dataset_fingerprint(dataset)
    if actual != report.dataset_fingerprint:
        raise DedupeError(
            "El reporte de calidad no corresponde al dataset en disco "
            f"(reporte: {report.dataset_fingerprint[:12]}..., "
            f"disco: {actual[:12]}...). Vuelve a correr `dq gate` antes de deduplicar."
        )

    check = duplicates_check(report)
    if check is None:
        raise DedupeError("El reporte no incluye el check `duplicates`.")
    if check.status == "skipped":
        raise DedupeError(
            "El check `duplicates` esta desactivado en quality.yaml: "
            "no hay nada que el pipeline haya marcado como copia."
        )

    sobrantes = set(check.offenders)
    por_id = {image.id: image for image in dataset.images}
    # Un offender que ya no existe en el dataset significa que el reporte se
    # genero antes de un cambio; la comprobacion de huella ya lo habria
    # detectado, pero mas vale no construir un plan con ids fantasma.
    desconocidos = sorted(sobrantes - set(por_id))
    if desconocidos:
        raise DedupeError(f"El reporte nombra imagenes que ya no existen: {desconocidos[:5]}")

    anotaciones = sum(1 for a in dataset.annotations if a.image_id in sobrantes)

    return DedupePlan(
        remove_ids=sorted(sobrantes),
        remove_files=[por_id[i].file_name for i in sorted(sobrantes)],
        annotations_removed=anotaciones,
        total_images=len(dataset.images),
        fingerprint=actual,
    )


def apply(
    plan: DedupePlan,
    dataset: CocoDataset,
    coco_path: Path,
    images_dir: Path,
    quarantine: Path | None = None,
) -> DedupeResult:
    """Mueve las copias a cuarentena y reescribe el COCO sin ellas.

    `quarantine` se resuelve aqui y no en la firma: un valor por defecto se
    evalua al importar el modulo, y entonces el destino quedaria clavado al
    del repositorio real aunque quien llame pida otro.
    """
    quarantine = QUARANTINE if quarantine is None else quarantine
    if plan.is_empty:
        return DedupeResult(0, 0, remaining_images=plan.total_images)

    sobrantes = set(plan.remove_ids)
    quarantine.mkdir(parents=True, exist_ok=True)

    movidas: list[str] = []
    ausentes: list[str] = []
    for file_name in plan.remove_files:
        origen = images_dir / file_name
        if not origen.is_file():
            ausentes.append(file_name)
            continue
        shutil.move(str(origen), str(quarantine / file_name))
        movidas.append(file_name)

    # El COCO se reescribe desde el modelo validado, no editando el JSON en
    # crudo: asi lo que queda en disco sigue cumpliendo el contrato.
    depurado = CocoDataset.model_validate(
        {
            "images": [image.model_dump() for image in dataset.images if image.id not in sobrantes],
            "annotations": [
                annotation.model_dump()
                for annotation in dataset.annotations
                if annotation.image_id not in sobrantes
            ],
            "categories": [category.model_dump() for category in dataset.categories],
        }
    )
    coco_path.write_text(
        json.dumps(json.loads(depurado.model_dump_json(exclude_none=True)), indent=1),
        encoding="utf-8",
        newline="\n",
    )

    return DedupeResult(
        removed_images=len(plan.remove_ids),
        removed_annotations=plan.annotations_removed,
        quarantined=movidas,
        missing_on_disk=ausentes,
        remaining_images=len(depurado.images),
        quarantine_dir=_ruta_legible(quarantine),
    )
