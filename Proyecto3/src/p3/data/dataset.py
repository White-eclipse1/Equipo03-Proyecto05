"""Recortes del manifiesto como `Dataset` y `DataLoader` de PyTorch (F4 T09, 2.3 y M3).

Las imagenes son los PNG de `scripts/generate_crops.py` (`crops.jsonl` los
indexa por `crop_id`): ya aplican la rotacion EXIF y la escala de la caja de
F2, asi que aqui no se repite la geometria. Cada fila del manifiesto debe
tener su recorte; si falta uno se falla en vez de entrenar con menos datos.

`build_datasets` vuelve a comprobar que ningun `crop_id`, `source_image_id`
ni `dup_group_id` aparezca en dos particiones antes de construir nada, y
asigna a val y test el MISMO transform determinista.
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image
from torch.utils.data import DataLoader, Dataset

from p3.data.transforms import build_eval_transform, build_train_transform

SPLITS = ("train", "val", "test")
LEAKAGE_FIELDS = ("crop_id", "source_image_id", "dup_group_id")


class MissingCropError(LookupError):
    """Una fila del manifiesto no tiene recorte generado."""


class LeakageError(ValueError):
    """Un identificador aparece en mas de una particion."""


def load_manifest(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def load_crop_index(crops_dir: Path) -> dict[str, Path]:
    """`crop_id -> ruta del PNG`, a partir del `crops.jsonl` de `generate_crops.py`."""
    index: dict[str, Path] = {}
    for line in (crops_dir / "crops.jsonl").read_text(encoding="utf-8").splitlines():
        if line:
            record = json.loads(line)
            index[record["crop_id"]] = crops_dir / record["crop_path"]
    return index


class CropDataset(Dataset[tuple[torch.Tensor, int, str]]):
    """Devuelve `(tensor, class_index, crop_id)`."""

    def __init__(
        self,
        crop_ids: Sequence[str],
        paths: Sequence[Path],
        labels: Sequence[int],
        transform: Any,
    ) -> None:
        self.crop_ids = tuple(crop_ids)
        self.paths = tuple(paths)
        self.labels = tuple(labels)
        self.transform = transform

    def __len__(self) -> int:
        return len(self.crop_ids)

    def __getitem__(self, index: int) -> tuple[torch.Tensor, int, str]:
        with Image.open(self.paths[index]) as handle:
            image = handle.convert("RGB")
        return self.transform(image), self.labels[index], self.crop_ids[index]


def check_no_leakage(rows: Iterable[Mapping[str, Any]]) -> None:
    rows = list(rows)
    for field in LEAKAGE_FIELDS:
        splits_of: dict[object, set[str]] = defaultdict(set)
        for row in rows:
            splits_of[row[field]].add(row["split"])
        leaked = sorted(str(k) for k, v in splits_of.items() if len(v) > 1)
        if leaked:
            raise LeakageError(f"{field} en mas de una particion: {leaked[:10]}")


def build_datasets(
    rows: Iterable[Mapping[str, Any]], crop_index: Mapping[str, Path], *, image_size: int
) -> dict[str, CropDataset]:
    """Un `CropDataset` por particion; val y test comparten el transform de evaluacion."""
    rows = sorted(rows, key=lambda row: row["crop_id"])
    check_no_leakage(rows)
    missing = [row["crop_id"] for row in rows if row["crop_id"] not in crop_index]
    if missing:
        raise MissingCropError(
            f"{len(missing)} fila(s) sin recorte generado (corre generate_crops.py): {missing[:5]}"
        )

    eval_transform = build_eval_transform(image_size)
    transforms = {
        "train": build_train_transform(image_size),
        "val": eval_transform,
        "test": eval_transform,
    }
    datasets = {}
    for split in SPLITS:
        selected = [row for row in rows if row["split"] == split]
        datasets[split] = CropDataset(
            crop_ids=[row["crop_id"] for row in selected],
            paths=[crop_index[row["crop_id"]] for row in selected],
            labels=[int(row["class_index"]) for row in selected],
            transform=transforms[split],
        )
    return datasets


def seed_worker(worker_id: int) -> None:
    """Semilla de `random` y `numpy` en cada worker, derivada de la de torch."""
    del worker_id
    seed = torch.initial_seed() % 2**32
    random.seed(seed)
    np.random.seed(seed)


def build_loader(
    dataset: CropDataset,
    *,
    batch_size: int,
    shuffle: bool,
    seed: int,
    num_workers: int = 0,
    drop_last: bool = False,
) -> DataLoader[tuple[torch.Tensor, int, str]]:
    """DataLoader con orden reproducible: `generator` y `worker_init_fn` sembrados."""
    generator = torch.Generator()
    generator.manual_seed(seed)
    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=shuffle,
        num_workers=num_workers,
        generator=generator,
        worker_init_fn=seed_worker,
        persistent_workers=num_workers > 0,
        drop_last=drop_last,
    )
