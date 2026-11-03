"""Tier 4 — splits estratificados.

Reparte las imagenes en train/val/test con tres propiedades exigidas por la
tarjeta del Frente 5:

  - **Estratificado dentro de tolerancia**: la proporcion de cada clase en
    cada split se parece a su proporcion global.
  - **Reproducible por semilla**: la misma `seed` da siempre el mismo reparto.
  - **Cero fuga de near-duplicates**: dos imagenes casi identicas (pHash del
    Frente 3) nunca caen en splits distintos.

La tercera propiedad no se comprueba al final, se hace estructuralmente
imposible: la unidad que se reparte no es la imagen, es el GRUPO de
casi-duplicados (`analyzers.duplicates.duplicate_groups`). Un grupo entero va
a un solo split, asi que no hay fuga que un chequeo a posteriori pueda
olvidar.

Salida: `reports/splits.json` (contrato congelado en `models.splits`).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from dataset_quality.analyzers.duplicates import compute_hashes, duplicate_groups
from dataset_quality.analyzers.structural import images_per_class
from dataset_quality.models.coco import CocoDataset
from dataset_quality.models.quality import QualityConfig, SplitsConfig
from dataset_quality.models.splits import (
    ClassSplitCounts,
    SplitAssignment,
    SplitName,
    SplitRatios,
    SplitsManifest,
)

DEFAULT_SPLITS_PATH = Path("reports") / "splits.json"

SIN_ANOTAR = "__sin_anotar__"
_SPLIT_ORDER: tuple[SplitName, ...] = ("train", "val", "test")


@dataclass(frozen=True)
class Unit:
    """La unidad de reparto: un grupo de imagenes que viaja junta a un split.

    Casi siempre `image_ids` tiene un solo elemento; tiene mas de uno cuando
    el pHash encontro casi-duplicados entre ellas.
    """

    image_ids: tuple[int, ...]
    stratum: str

    @property
    def anchor(self) -> int:
        """El menor `image_id` del grupo — para un orden determinista."""
        return min(self.image_ids)


def stratum_labels(dataset: CocoDataset) -> dict[int, str]:
    """Etiqueta de estratificacion por imagen: su clase menos frecuente.

    Una imagen puede tener cajas de varias clases; usar la MINORITARIA (la de
    menor conteo global) protege a las clases raras — son las que mas se
    perjudican si quedan mal representadas en val/test. Las imagenes sin
    ninguna anotacion forman su propio estrato en vez de desaparecer.
    """
    per_class = images_per_class(dataset)
    category_names = {category.id: category.name for category in dataset.categories}

    classes_by_image: dict[int, set[int]] = {}
    for annotation in dataset.annotations:
        classes_by_image.setdefault(annotation.image_id, set()).add(annotation.category_id)

    labels: dict[int, str] = {}
    for image in dataset.images:
        category_ids = classes_by_image.get(image.id)
        if not category_ids:
            labels[image.id] = SIN_ANOTAR
            continue
        names = (category_names[cid] for cid in category_ids)
        labels[image.id] = min(names, key=lambda name: (per_class[name], name))
    return labels


def build_units(
    dataset: CocoDataset,
    config: SplitsConfig,
    images_dir: Path,
    phash_hamming_distance: int,
) -> list[Unit]:
    """Agrupa imagenes en unidades de reparto.

    `phash_hamming_distance` es el mismo umbral que declara `duplicates` en
    quality.yaml (Frente 3): "casi identica" es una sola nocion, no dos
    politicas por mantener sincronizadas.

    Si `group_near_duplicates` esta activo, calcula los grupos de pHash sobre
    las imagenes disponibles en `images_dir` y colapsa cada grupo en una sola
    unidad. La etiqueta de estrato de un grupo es la minoritaria entre las de
    sus miembros, para no perder la proteccion de la clase rara al fusionar.
    """
    labels = stratum_labels(dataset)
    per_class = images_per_class(dataset)

    if not config.group_near_duplicates:
        return [Unit(image_ids=(image_id,), stratum=label) for image_id, label in labels.items()]

    hashes = compute_hashes(dataset, images_dir)
    grouped_ids: set[int] = set()
    units: list[Unit] = []

    for group in duplicate_groups(hashes, phash_hamming_distance):
        grouped_ids |= group
        stratum = min(
            (labels[image_id] for image_id in group),
            key=lambda name: (per_class.get(name, 0), name) if name != SIN_ANOTAR else (-1, name),
        )
        units.append(Unit(image_ids=tuple(sorted(group)), stratum=stratum))

    for image_id, label in labels.items():
        if image_id not in grouped_ids:
            units.append(Unit(image_ids=(image_id,), stratum=label))

    return units


def assign(units: list[Unit], ratios: SplitRatios, seed: int) -> list[SplitAssignment]:
    """Reparte las unidades en train/val/test, estrato por estrato.

    Por estrato: orden determinista por `anchor` (nunca el orden de un `set`,
    que varia entre procesos), baraja con una instancia propia de `Random`
    (no la global, para no contaminar el estado del proceso) y reparte por
    largest remainder — cuotas enteras con los restos para las fracciones mas
    grandes — que es lo que evita perder o duplicar unidades por redondeo.
    """
    rng = random.Random(seed)
    target = {"train": ratios.train, "val": ratios.val, "test": ratios.test}

    by_stratum: dict[str, list[Unit]] = {}
    for unit in units:
        by_stratum.setdefault(unit.stratum, []).append(unit)

    assignments: list[SplitAssignment] = []
    for stratum in sorted(by_stratum):
        members = sorted(by_stratum[stratum], key=lambda unit: unit.anchor)
        rng.shuffle(members)

        for unit, split_name in zip(members, _largest_remainder(len(members), target), strict=True):
            for image_id in unit.image_ids:
                assignments.append(SplitAssignment(image_id=image_id, split=split_name))

    return assignments


def _largest_remainder(total: int, target: dict[SplitName, float]) -> list[SplitName]:
    """Asigna `total` elementos a los splits segun `target`, por largest remainder.

    Cuotas enteras (`floor`) mas los restos mayores hasta agotar `total`; con
    menos elementos que splits, los primeros en la lista se quedan con uno.
    Devuelve la secuencia de splits en el orden en que se deben ir asignando
    los elementos ya barajados (no agrupados): la lista tiene `total`
    entradas, tantas de cada split como le toco.
    """
    exact = {name: total * share for name, share in target.items()}
    floors = {name: int(value) for name, value in exact.items()}
    remainder = total - sum(floors.values())

    remainders_desc = sorted(
        _SPLIT_ORDER, key=lambda name: exact[name] - floors[name], reverse=True
    )
    for name in remainders_desc[:remainder]:
        floors[name] += 1

    sequence: list[SplitName] = []
    for name in _SPLIT_ORDER:
        sequence.extend([name] * floors[name])
    return sequence


def class_breakdown(
    dataset: CocoDataset, assignments: list[SplitAssignment]
) -> dict[str, ClassSplitCounts]:
    """Como quedo cada clase repartida entre las tres particiones.

    Recorre las imagenes (no las cajas): la metrica de estratificacion es
    sobre imagenes por clase, igual que `images_per_class`.

    Devuelve conteos y desviacion en una sola pasada porque salen del mismo
    recorrido; separarlos obligaria a recorrer el dataset dos veces para
    responder dos mitades de la misma pregunta.
    """
    category_names = {category.id: category.name for category in dataset.categories}
    classes_by_image: dict[int, set[str]] = {}
    for annotation in dataset.annotations:
        classes_by_image.setdefault(annotation.image_id, set()).add(
            category_names[annotation.category_id]
        )

    split_by_image = {a.image_id: a.split for a in assignments}
    total_by_class: dict[str, int] = {}
    split_totals: dict[SplitName, int] = {name: 0 for name in _SPLIT_ORDER}
    per_split_class: dict[tuple[SplitName, str], int] = {}

    for image_id, classes in classes_by_image.items():
        split = split_by_image.get(image_id)
        if split is None:
            continue
        split_totals[split] += 1
        for name in classes:
            total_by_class[name] = total_by_class.get(name, 0) + 1
            key = (split, name)
            per_split_class[key] = per_split_class.get(key, 0) + 1

    total_images = sum(total_by_class.values()) or 1
    result: dict[str, ClassSplitCounts] = {}
    for name, global_count in sorted(total_by_class.items()):
        global_share = global_count / total_images
        worst = 0.0
        conteos: dict[SplitName, int] = {}
        for split in _SPLIT_ORDER:
            conteos[split] = per_split_class.get((split, name), 0)
            denom = split_totals[split]
            if denom == 0:
                continue
            worst = max(worst, abs(conteos[split] / denom - global_share))

        result[name] = ClassSplitCounts(
            train=conteos["train"],
            val=conteos["val"],
            test=conteos["test"],
            total=global_count,
            max_deviation=round(worst, 5),
        )
    return result


def deviation(dataset: CocoDataset, assignments: list[SplitAssignment]) -> dict[str, float]:
    """Desviacion maxima por clase. Lo mismo que `class_breakdown`, sin conteos."""
    return {
        name: counts.max_deviation for name, counts in class_breakdown(dataset, assignments).items()
    }


def build_manifest(dataset: CocoDataset, config: QualityConfig, images_dir: Path) -> SplitsManifest:
    """Ensambla el `SplitsManifest`. El validador del modelo rechaza la fuga."""
    units = build_units(
        dataset, config.splits, images_dir, config.duplicates.phash_hamming_distance
    )
    return _manifest_from_units(units, config.splits, dataset)


def _manifest_from_units(
    units: list[Unit], config: SplitsConfig, dataset: CocoDataset
) -> SplitsManifest:
    assignments = assign(units, config.ratios, config.seed)

    counts: dict[SplitName, int] = {name: 0 for name in _SPLIT_ORDER}
    for assignment in assignments:
        counts[assignment.split] += 1

    return SplitsManifest(
        generated_at=datetime.now(UTC),
        seed=config.seed,
        ratios=config.ratios,
        counts=counts,
        assignments=assignments,
        per_class=class_breakdown(dataset, assignments),
        grouped_near_duplicates=sum(1 for unit in units if len(unit.image_ids) > 1),
    )


def write_manifest(manifest: SplitsManifest, path: Path = DEFAULT_SPLITS_PATH) -> Path:
    """Escribe `splits.json`. El archivo se puede releer con su propio modelo."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8", newline="\n")
    return path


@dataclass
class SplitRunResult:
    manifest: SplitsManifest
    deviations: dict[str, float] = field(default_factory=dict)
    duplicate_group_count: int = 0


def run(
    dataset: CocoDataset,
    config: QualityConfig,
    images_dir: Path,
    out: Path = DEFAULT_SPLITS_PATH,
) -> SplitRunResult:
    """Construye el manifiesto, lo escribe y devuelve metricas para el CLI."""
    units = build_units(
        dataset, config.splits, images_dir, config.duplicates.phash_hamming_distance
    )
    manifest = _manifest_from_units(units, config.splits, dataset)
    write_manifest(manifest, out)

    # Ya no se recalcula nada: el manifiesto lleva las dos metricas dentro.
    return SplitRunResult(
        manifest=manifest,
        deviations={name: counts.max_deviation for name, counts in manifest.per_class.items()},
        duplicate_group_count=manifest.grouped_near_duplicates,
    )
