"""Seleccion de clases antes de experimentar (F2 T06, criterios 1.2 y 3.1).

Una clase entra solo si tiene al menos 300 imagenes ORIGINALES distintas con
alguna caja valida en el release aprobado; se cuentan originales, no
recortes. El resultado se guarda en `config/classes.yaml` con un esquema
estricto: `class_index` es el orden alfabetico del nombre (contratos §1).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from p3.data import classes
from p3.data.classes import ClassDecision, ClassesConfig, NotEnoughClassesError
from p3.data.crops import CropSource, read_image_sizes, validate_annotations

FIXTURE = Path(__file__).parent / "fixtures" / "p3"
NAMES = {2: "person", 3: "dog", 4: "cat", 5: "bicycle"}
FINGERPRINT = "f" * 64


def crop(annotation_id: int, image_id: int, category_id: int) -> CropSource:
    return CropSource(
        annotation_id=annotation_id,
        source_image_id=image_id,
        source_file_name=f"img_{image_id}.jpg",
        category_id=category_id,
        category_name=NAMES[category_id],
        bbox_xywh=(0.0, 0.0, 10.0, 10.0),
    )


def valid_config(**overrides) -> dict:
    data = {
        "schema_version": 1,
        "release_id": "0.1.3",
        "dataset_fingerprint": FINGERPRINT,
        "min_originals": 300,
        "decided_at": "2026-09-25",
        "classes": [
            {"class_index": 0, "category_id": 4, "category_name": "cat", "originals": 310},
            {"class_index": 1, "category_id": 3, "category_name": "dog", "originals": 340},
            {"class_index": 2, "category_id": 2, "category_name": "person", "originals": 400},
        ],
        "excluded": [
            {
                "category_id": 5,
                "category_name": "bicycle",
                "originals": 240,
                "reason": "240 originales distintos < 300",
            }
        ],
    }
    data.update(overrides)
    return data


# --- Conteo de originales ---------------------------------------------------------------


def test_cuenta_originales_distintos_y_no_recortes() -> None:
    valid = [crop(1, 10, 2), crop(2, 10, 2), crop(3, 11, 2), crop(4, 10, 3)]
    assert classes.originals_per_category(valid) == {2: 2, 3: 1}


def test_en_el_fixture_solo_cuentan_las_cajas_validas() -> None:
    coco = json.loads((FIXTURE / "annotations.coco.json").read_text(encoding="utf-8"))
    sizes = read_image_sizes(coco["images"], FIXTURE / "images")
    result = validate_annotations(coco, {2, 3, 4}, sizes)
    # La imagen 28 tiene person y dog: cuenta para las dos clases. Las imagenes
    # 27 (faltante), 29 (degenerada) y 30 (fuera de la imagen) no cuentan.
    assert classes.originals_per_category(result.valid) == {4: 10, 3: 9, 2: 9}


# --- Seleccion por umbral ----------------------------------------------------------------


def test_incluye_desde_300_y_excluye_299_con_motivo() -> None:
    decisions = classes.select_classes({2: 300, 3: 450, 4: 299}, NAMES)
    by_name = {d.category_name: d for d in decisions}
    assert by_name["person"].included and by_name["person"].reason is None
    assert by_name["dog"].included
    assert not by_name["cat"].included
    assert "299" in by_name["cat"].reason and "300" in by_name["cat"].reason


def test_categoria_sin_cajas_validas_cuenta_cero_originales() -> None:
    decisions = classes.select_classes({2: 400, 3: 400}, NAMES)
    bicycle = next(d for d in decisions if d.category_name == "bicycle")
    assert bicycle == ClassDecision(5, "bicycle", 0, False, "0 originales distintos < 300")


def test_falla_si_quedan_menos_de_dos_clases() -> None:
    with pytest.raises(NotEnoughClassesError, match="2 clases"):
        classes.select_classes({2: 500, 3: 10, 4: 299}, NAMES)


def test_umbral_configurable() -> None:
    decisions = classes.select_classes({2: 9, 3: 9, 4: 10}, NAMES, min_originals=8)
    assert [d.category_name for d in decisions if d.included] == ["cat", "dog", "person"]


# --- classes.yaml ---------------------------------------------------------------------------


def test_class_index_es_el_orden_alfabetico_del_nombre() -> None:
    decisions = classes.select_classes({2: 400, 3: 340, 4: 310, 5: 240}, NAMES)
    config = classes.build_config(
        decisions, release_id="0.1.3", dataset_fingerprint=FINGERPRINT, decided_at=date(2026, 9, 25)
    )
    assert [(c.class_index, c.category_name, c.category_id) for c in config.classes] == [
        (0, "cat", 4),
        (1, "dog", 3),
        (2, "person", 2),
    ]
    assert [(e.category_name, e.originals) for e in config.excluded] == [("bicycle", 240)]


def test_yaml_ida_y_vuelta(tmp_path: Path) -> None:
    config = ClassesConfig.model_validate(valid_config())
    path = tmp_path / "classes.yaml"
    classes.dump_classes(config, path)
    assert classes.load_classes(path) == config


@pytest.mark.parametrize(
    ("overrides", "campo"),
    [
        (
            {
                "classes": [
                    {"class_index": 1, "category_id": 4, "category_name": "cat", "originals": 310},
                    {"class_index": 0, "category_id": 3, "category_name": "dog", "originals": 340},
                ]
            },
            "class_index",
        ),
        (
            {
                "classes": [
                    {"class_index": 0, "category_id": 4, "category_name": "cat", "originals": 299},
                    {"class_index": 1, "category_id": 3, "category_name": "dog", "originals": 340},
                ]
            },
            "originals",
        ),
        (
            {
                "classes": [
                    {"class_index": 0, "category_id": 4, "category_name": "cat", "originals": 310}
                ]
            },
            "classes",
        ),
        (
            {
                "classes": [
                    {"class_index": 0, "category_id": 4, "category_name": "cat", "originals": 310},
                    {"class_index": 1, "category_id": 4, "category_name": "dog", "originals": 340},
                ]
            },
            "category_id",
        ),
        ({"dataset_fingerprint": "corta"}, "dataset_fingerprint"),
        ({"extra": 1}, "extra"),
    ],
)
def test_classes_yaml_invalido_se_rechaza_nombrando_el_campo(overrides: dict, campo: str) -> None:
    with pytest.raises(ValidationError, match=campo):
        ClassesConfig.model_validate(valid_config(**overrides))
