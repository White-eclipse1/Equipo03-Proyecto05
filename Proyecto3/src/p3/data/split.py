"""Manifiesto 70/20/10 de recortes, agrupado y reproducible (F3 T08, criterios 1.3 y M3).

Reparto:

1. **Unidades indivisibles.** Todos los recortes de un original viajan juntos, y
   todos los originales de un grupo de casi duplicados (`dup_group_id`, pHash de
   P2) tambien: la unidad es el grupo.
2. **Estratos.** Cada unidad se estratifica por su clase mas minoritaria (menos
   recortes en todo el release), como hace P2 con sus splits, para no dejar sin
   representacion a la clase rara.
3. **Asignacion.** Por estrato, en orden determinista: se ordenan las unidades por
   `dup_group_id`, se barajan con `random.Random(seed)` y cada una va a la
   particion a la que mas recortes le faltan para su objetivo (greedy por
   deficit). Asi las proporciones se cumplen en recortes, que es lo que pide la
   rubrica, aunque las unidades tengan tamanos distintos.

Misma semilla y mismo release dan el mismo manifiesto byte a byte: nada depende
del orden de entrada, de un `set` ni del reloj. `check_manifest` revisa los
invariantes de `docs/contratos.md` §2 sobre cualquier manifiesto.

Logica pura: recibe los recortes validados, los grupos y la semilla; no lee
archivos ni el entorno.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import Counter, defaultdict
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from p3.data.crops import CropSource, crop_id

SPLITS = ("train", "val", "test")
DEFAULT_RATIOS: Mapping[str, float] = {"train": 0.7, "val": 0.2, "test": 0.1}
TOLERANCE_PP = 5

Row = dict[str, Any]


class SplitError(ValueError):
    """El manifiesto no se puede generar cumpliendo los invariantes."""


@dataclass(frozen=True)
class ManifestRelease:
    release_id: str
    dataset_fingerprint: str


def dup_group_ids(image_ids: Collection[int], groups: Iterable[Collection[int]]) -> dict[int, str]:
    """`dup_group_id` de cada imagen: `g<menor image_id del grupo>`.

    `groups` son los grupos de casi duplicados (p. ej. de
    `dataset_quality.analyzers.duplicates.duplicate_groups`); una imagen que no
    esta en ninguno forma su propio grupo.
    """
    assigned: dict[int, str] = {}
    for group in groups:
        members = sorted(group)
        label = f"g{members[0]}"
        for image_id in members:
            if image_id in assigned and assigned[image_id] != label:
                raise SplitError(f"La imagen {image_id} aparece en dos grupos de duplicados.")
            assigned[image_id] = label
    return {image_id: assigned.get(image_id, f"g{image_id}") for image_id in sorted(image_ids)}


def build_manifest(
    sources: Iterable[CropSource],
    *,
    release: ManifestRelease,
    class_index: Mapping[int, int],
    dup_groups: Mapping[int, str],
    seed: int,
    ratios: Mapping[str, float] = DEFAULT_RATIOS,
) -> list[Row]:
    """Filas del manifiesto (contratos §2), ordenadas por `crop_id`."""
    sources = sorted(sources, key=lambda s: s.annotation_id)
    by_unit: dict[str, list[CropSource]] = defaultdict(list)
    for source in sources:
        by_unit[dup_groups[source.source_image_id]].append(source)

    crops_per_class = Counter(s.category_name for s in sources)
    strata: dict[str, list[str]] = defaultdict(list)
    for unit in sorted(by_unit):
        names = {s.category_name for s in by_unit[unit]}
        stratum = min(names, key=lambda name: (crops_per_class[name], name))
        strata[stratum].append(unit)

    rng = random.Random(seed)
    split_of_unit: dict[str, str] = {}
    for stratum in sorted(strata):
        units = strata[stratum]
        rng.shuffle(units)
        total = sum(len(by_unit[u]) for u in units)
        assigned = dict.fromkeys(SPLITS, 0)
        for unit in units:
            split = max(SPLITS, key=lambda s: ratios[s] * total - assigned[s])
            split_of_unit[unit] = split
            assigned[split] += len(by_unit[unit])

    rows = [
        {
            "crop_id": crop_id(release.release_id, s.annotation_id),
            "source_image_id": s.source_image_id,
            "source_file_name": s.source_file_name,
            "annotation_id": s.annotation_id,
            "category_id": s.category_id,
            "category_name": s.category_name,
            "class_index": class_index[s.category_id],
            "bbox_xywh": list(s.bbox_xywh),
            "dup_group_id": dup_groups[s.source_image_id],
            "split": split_of_unit[dup_groups[s.source_image_id]],
            "release_id": release.release_id,
            "release_hash": release.dataset_fingerprint,
        }
        for s in sources
    ]
    rows.sort(key=lambda row: row["crop_id"])

    for split in ("val", "test"):
        present = {row["category_name"] for row in rows if row["split"] == split}
        missing = sorted(set(crops_per_class) - present)
        if missing:
            raise SplitError(
                f"Las clases {missing} no quedaron en {split}: no hay unidades suficientes "
                f"para repartirlas en 70/20/10."
            )
    return rows


def manifest_jsonl(rows: Iterable[Row]) -> str:
    """Una fila por linea, JSON canonico (claves ordenadas, sin espacios), en orden de
    `crop_id` y con `\\n` al final de cada linea (contratos §0)."""
    ordered = sorted(rows, key=lambda row: row["crop_id"])
    return "".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n" for r in ordered)


def manifest_hash(rows: Iterable[Row]) -> str:
    """SHA-256 de `manifest_jsonl`: el hash del archivo `manifest.jsonl`."""
    return hashlib.sha256(manifest_jsonl(rows).encode("utf-8")).hexdigest()


def manifest_counts(rows: Iterable[Row]) -> dict[str, dict[str, dict[str, int]]]:
    """Recortes y originales distintos por particion y clase."""
    rows = list(rows)
    names = sorted({row["category_name"] for row in rows})
    crops: dict[str, dict[str, int]] = {s: dict.fromkeys(names, 0) for s in SPLITS}
    originals: dict[str, dict[str, set[int]]] = {s: {n: set() for n in names} for s in SPLITS}
    for row in rows:
        crops[row["split"]][row["category_name"]] += 1
        originals[row["split"]][row["category_name"]].add(row["source_image_id"])
    return {
        "crops": crops,
        "originals": {s: {n: len(ids) for n, ids in by.items()} for s, by in originals.items()},
    }


def check_manifest(
    rows: Iterable[Row],
    *,
    ratios: Mapping[str, float] = DEFAULT_RATIOS,
    tolerance_pp: float = TOLERANCE_PP,
) -> list[str]:
    """Violaciones de los invariantes de contratos §2 (lista vacia si no hay)."""
    rows = list(rows)
    problems: list[str] = []
    for field in ("crop_id", "source_image_id", "dup_group_id"):
        splits_of: dict[object, set[str]] = defaultdict(set)
        for row in rows:
            splits_of[row[field]].add(row["split"])
        leaked = sorted(str(k) for k, v in splits_of.items() if len(v) > 1)
        if leaked:
            problems.append(f"{field} en mas de una particion: {leaked[:10]}")

    total = len(rows)
    per_split = Counter(row["split"] for row in rows)
    for split in SPLITS:
        share = per_split[split] / total if total else 0.0
        if abs(share - ratios[split]) * 100 > tolerance_pp:
            problems.append(
                f"{split}: {share:.1%} de los recortes, objetivo {ratios[split]:.0%} "
                f"+-{tolerance_pp} pp"
            )

    names = {row["category_name"] for row in rows}
    for split in ("val", "test"):
        present = {row["category_name"] for row in rows if row["split"] == split}
        for name in sorted(names - present):
            problems.append(f"la clase {name} no tiene recortes en {split}")
    return problems
