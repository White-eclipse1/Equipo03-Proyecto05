"""Dataset, DataLoader y transforms (F4 T09, criterios 2.3 y M3).

- val, test e inferencia comparten UNA funcion de preprocesamiento determinista;
- la aumentacion aleatoria solo existe en train;
- cada Dataset solo contiene recortes de su particion;
- misma semilla -> mismo orden de muestras.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import torch
from PIL import Image

from p3.data import dataset, transforms

SPLITS = {"train": 12, "val": 4, "test": 4}


@pytest.fixture
def crops_dir(tmp_path: Path) -> tuple[Path, list[dict[str, object]]]:
    """Recortes sinteticos + `crops.jsonl` con el formato de `generate_crops.py`."""
    rows: list[dict[str, object]] = []
    index: list[dict[str, object]] = []
    annotation_id = 1
    for split, n in SPLITS.items():
        for i in range(n):
            class_index = i % 3
            name = ("cat", "dog", "person")[class_index]
            crop_id = f"9.9.9:a{annotation_id}"
            relative = f"{name}/9.9.9_a{annotation_id}.png"
            path = tmp_path / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            color = (annotation_id * 7 % 255, annotation_id * 13 % 255, annotation_id * 29 % 255)
            Image.new("RGB", (40 + annotation_id, 30 + 2 * annotation_id), color).save(path)
            rows.append(
                {
                    "crop_id": crop_id,
                    "annotation_id": annotation_id,
                    "source_image_id": annotation_id,
                    "category_name": name,
                    "class_index": class_index,
                    "split": split,
                    "dup_group_id": f"g{annotation_id}",
                }
            )
            index.append({"crop_id": crop_id, "crop_path": relative})
            annotation_id += 1
    (tmp_path / "crops.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in index), encoding="utf-8"
    )
    return tmp_path, rows


def _datasets(crops: tuple[Path, list[dict[str, object]]], image_size: int = 32):
    root, rows = crops
    return dataset.build_datasets(rows, dataset.load_crop_index(root), image_size=image_size)


def test_val_test_e_inferencia_comparten_el_mismo_preprocesamiento(crops_dir) -> None:
    datasets = _datasets(crops_dir)
    assert datasets["val"].transform is datasets["test"].transform
    assert datasets["train"].transform is not datasets["val"].transform
    # La inferencia usa la misma fabrica: mismo tensor para la misma imagen.
    image = Image.open(datasets["val"].paths[0]).convert("RGB")
    assert torch.equal(datasets["val"].transform(image), transforms.build_eval_transform(32)(image))


def test_el_transform_de_evaluacion_es_determinista(crops_dir) -> None:
    val = _datasets(crops_dir)["val"]
    torch.manual_seed(0)
    first, _, _ = val[0]
    # Varias semillas: una aumentacion con probabilidad 0.5 no pasa por casualidad.
    for seed in range(1, 9):
        torch.manual_seed(seed)
        assert torch.equal(first, val[0][0])
    assert first.shape == (3, 32, 32)


def test_el_transform_de_evaluacion_no_tiene_operaciones_aleatorias() -> None:
    nombres = [type(t).__name__ for t in transforms.build_eval_transform(32).transforms]
    assert not [n for n in nombres if n.startswith("Random") or n == "ColorJitter"], nombres


def test_la_aumentacion_aleatoria_solo_esta_en_train(crops_dir) -> None:
    train = _datasets(crops_dir)["train"]
    torch.manual_seed(0)
    variantes = [train[0][0] for _ in range(6)]
    assert any(not torch.equal(variantes[0], v) for v in variantes[1:])


def test_el_preprocesamiento_normaliza_con_imagenet(crops_dir) -> None:
    val = _datasets(crops_dir)["val"]
    blanco = Image.new("RGB", (50, 20), (255, 255, 255))
    tensor = val.transform(blanco)
    esperado = [
        (1 - m) / s for m, s in zip(transforms.IMAGENET_MEAN, transforms.IMAGENET_STD, strict=True)
    ]
    assert torch.allclose(tensor[:, 0, 0], torch.tensor(esperado), atol=1e-5)


def test_cada_dataset_solo_tiene_su_particion(crops_dir) -> None:
    datasets = _datasets(crops_dir)
    ids = {split: set(ds.crop_ids) for split, ds in datasets.items()}
    assert {split: len(v) for split, v in ids.items()} == SPLITS
    assert not ids["train"] & ids["val"]
    assert not ids["train"] & ids["test"]
    assert not ids["val"] & ids["test"]


def test_la_etiqueta_es_el_class_index_del_manifiesto(crops_dir) -> None:
    _, rows = crops_dir
    test = _datasets(crops_dir)["test"]
    esperado = {r["crop_id"]: r["class_index"] for r in rows}
    for i, crop_id in enumerate(test.crop_ids):
        assert test[i][1] == esperado[crop_id]


def test_una_fila_sin_recorte_generado_falla(crops_dir) -> None:
    root, rows = crops_dir
    index = dataset.load_crop_index(root)
    del index[rows[0]["crop_id"]]
    with pytest.raises(dataset.MissingCropError, match=str(rows[0]["crop_id"])):
        dataset.build_datasets(rows, index, image_size=32)


# Fijos a proposito (no `dataset.LEAKAGE_FIELDS`): si alguien quita un campo del codigo,
# su caso sigue aqui y falla.
@pytest.mark.parametrize("campo", ["crop_id", "source_image_id", "dup_group_id"])
def test_una_fuga_entre_particiones_se_rechaza(crops_dir, campo: str) -> None:
    # Una fila nueva en otra particion que comparte SOLO `campo` con rows[0]: cada
    # identificador (recorte, original y grupo de casi duplicados) se vigila por separado.
    root, rows = crops_dir
    original = rows[0]
    otra = next(s for s in dataset.SPLITS if s != original["split"])
    fugado = dict(
        original,
        crop_id="9.9.9:a999",
        source_image_id=999_999,
        dup_group_id="g999999",
        split=otra,
    )
    fugado[campo] = original[campo]
    index = dataset.load_crop_index(root)
    index["9.9.9:a999"] = index[original["crop_id"]]
    with pytest.raises(dataset.LeakageError, match=campo):
        dataset.build_datasets([*rows, fugado], index, image_size=32)


def _orden(ds, seed: int) -> list[str]:
    loader = dataset.build_loader(ds, batch_size=4, shuffle=True, seed=seed)
    return [crop_id for batch in loader for crop_id in batch[2]]


def test_misma_semilla_mismo_orden_de_muestras(crops_dir) -> None:
    train = _datasets(crops_dir)["train"]
    assert _orden(train, seed=42) == _orden(train, seed=42)
    assert _orden(train, seed=42) != _orden(train, seed=7)


def test_el_loader_de_evaluacion_no_baraja(crops_dir) -> None:
    val = _datasets(crops_dir)["val"]
    loader = dataset.build_loader(val, batch_size=3, shuffle=False, seed=1)
    assert [c for batch in loader for c in batch[2]] == list(val.crop_ids)
