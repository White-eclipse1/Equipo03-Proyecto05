"""Modelos COCO: el JSON malformado se rechaza nombrando el campo (Frente 2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dataset_quality.models.coco import CocoAnnotation, CocoDataset, load_coco, parse_coco
from dataset_quality.models.errors import DatasetValidationError

FIXTURES = Path(__file__).parent / "fixtures"


def test_carga_un_dataset_coco_valido() -> None:
    dataset = load_coco(FIXTURES / "coco_valido.json")

    assert len(dataset.images) == 3
    assert len(dataset.categories) == 2
    assert len(dataset.annotations) == 4
    # Campos extra del estandar (info, licenses) no rompen la carga.
    assert "licenses" in dataset.model_extra


def test_bbox_degenerada_se_rechaza_nombrando_el_campo() -> None:
    with pytest.raises(DatasetValidationError) as error:
        load_coco(FIXTURES / "coco_invalido_bbox.json")

    mensaje = str(error.value)
    assert "annotations.0.bbox" in mensaje
    assert "ancho" in mensaje


def test_referencia_a_categoria_inexistente_se_rechaza() -> None:
    with pytest.raises(DatasetValidationError) as error:
        load_coco(FIXTURES / "coco_invalido_referencia.json")

    assert "annotations.0" in str(error.value)
    assert "categoria inexistente" in str(error.value)


def test_id_de_imagen_duplicado_se_rechaza() -> None:
    raw = """
    {
      "images": [
        {"id": 1, "file_name": "a.jpg", "width": 10, "height": 10},
        {"id": 1, "file_name": "b.jpg", "width": 10, "height": 10}
      ],
      "categories": [{"id": 1, "name": "x"}],
      "annotations": []
    }
    """
    with pytest.raises(DatasetValidationError) as error:
        parse_coco(raw, source="duplicado.json")

    assert "duplicado" in str(error.value)


def test_iscrowd_fuera_de_rango_se_rechaza() -> None:
    raw = """
    {
      "images": [{"id": 1, "file_name": "a.jpg", "width": 10, "height": 10}],
      "categories": [{"id": 1, "name": "x"}],
      "annotations": [
        {"id": 1, "image_id": 1, "category_id": 1, "bbox": [0,0,5,5], "area": 25, "iscrowd": 2}
      ]
    }
    """
    with pytest.raises(DatasetValidationError) as error:
        parse_coco(raw, source="iscrowd.json")

    assert "annotations.0.iscrowd" in str(error.value)


def test_area_incoherente_con_bbox_se_rechaza() -> None:
    raw = """
    {
      "images": [{"id": 1, "file_name": "a.jpg", "width": 10, "height": 10}],
      "categories": [{"id": 1, "name": "x"}],
      "annotations": [
        {"id": 1, "image_id": 1, "category_id": 1, "bbox": [0,0,5,5], "area": 999, "iscrowd": 0}
      ]
    }
    """
    with pytest.raises(DatasetValidationError) as error:
        parse_coco(raw, source="area.json")

    assert "annotations.0" in str(error.value)


def test_json_malformado_no_propaga_un_traceback_crudo() -> None:
    with pytest.raises(DatasetValidationError) as error:
        parse_coco("{ esto no es json", source="roto.json")

    assert "JSON malformado" in str(error.value)


def test_bbox_out_of_bounds_marca_las_anotaciones_que_se_salen_de_la_imagen() -> None:
    dataset = CocoDataset(
        images=[{"id": 1, "file_name": "a.jpg", "width": 100, "height": 100}],
        categories=[{"id": 1, "name": "x"}],
        annotations=[
            CocoAnnotation(
                id=1, image_id=1, category_id=1, bbox=(90, 90, 50, 50), area=2500, iscrowd=0
            ),
            CocoAnnotation(
                id=2, image_id=1, category_id=1, bbox=(0, 0, 10, 10), area=100, iscrowd=0
            ),
        ],
    )

    assert dataset.bbox_out_of_bounds() == [1]
