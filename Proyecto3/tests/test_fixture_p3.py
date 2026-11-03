"""El fixture de P3 tiene la forma que promete `docs/contratos.md` (F1 T04).

F2 (recortes) y F3 (manifiesto) prueban contra este COCO sin depender del
release real. Si alguien lo edita y pierde uno de los casos borde, esta prueba
lo dice antes de que las pruebas de F2/F3 pasen en verde sin probar nada.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "p3"
MISSING_IMAGE_ID = 27


@pytest.fixture(scope="module")
def coco() -> dict[str, Any]:
    return json.loads((FIXTURE / "annotations.coco.json").read_text(encoding="utf-8"))


def _images(coco: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {image["id"]: image for image in coco["images"]}


def _is_valid(ann: dict[str, Any], image: dict[str, Any]) -> bool:
    x, y, w, h = ann["bbox"]
    return (
        w > 0
        and h > 0
        and x >= 0
        and y >= 0
        and x + w <= image["width"]
        and y + h <= image["height"]
    )


def test_tres_clases_con_los_ids_del_release_real(coco: dict[str, Any]) -> None:
    assert {(c["id"], c["name"]) for c in coco["categories"]} == {
        (2, "person"),
        (3, "dog"),
        (4, "cat"),
    }


def test_treinta_imagenes_con_ids_unicos(coco: dict[str, Any]) -> None:
    ids = [image["id"] for image in coco["images"]]
    assert len(ids) == 30
    assert len(set(ids)) == 30
    assert len({a["id"] for a in coco["annotations"]}) == len(coco["annotations"])


def test_todas_las_imagenes_existen_salvo_la_faltante(coco: dict[str, Any]) -> None:
    for image in coco["images"]:
        existe = (FIXTURE / "images" / image["file_name"]).is_file()
        assert existe is (image["id"] != MISSING_IMAGE_ID), image["file_name"]


def test_hay_una_caja_degenerada(coco: dict[str, Any]) -> None:
    assert any(a["bbox"][2] <= 0 or a["bbox"][3] <= 0 for a in coco["annotations"])


def test_hay_una_caja_fuera_de_la_imagen(coco: dict[str, Any]) -> None:
    images = _images(coco)
    fuera = [
        a
        for a in coco["annotations"]
        if a["bbox"][2] > 0 and a["bbox"][3] > 0 and not _is_valid(a, images[a["image_id"]])
    ]
    assert fuera


def test_una_imagen_produce_recortes_de_dos_clases(coco: dict[str, Any]) -> None:
    clases_por_imagen: dict[int, set[int]] = {}
    for a in coco["annotations"]:
        clases_por_imagen.setdefault(a["image_id"], set()).add(a["category_id"])
    assert any(len(clases) >= 2 for clases in clases_por_imagen.values())


def test_hay_un_par_de_casi_duplicados_distintos_byte_a_byte(coco: dict[str, Any]) -> None:
    a = (FIXTURE / "images" / "img_025.jpg").read_bytes()
    b = (FIXTURE / "images" / "img_026.jpg").read_bytes()
    assert a != b
    images = _images(coco)
    assert (images[25]["width"], images[25]["height"]) == (
        images[26]["width"],
        images[26]["height"],
    )


def test_cada_clase_tiene_al_menos_ocho_recortes_validos(coco: dict[str, Any]) -> None:
    images = _images(coco)
    validos = Counter(
        a["category_id"]
        for a in coco["annotations"]
        if a["image_id"] != MISSING_IMAGE_ID and _is_valid(a, images[a["image_id"]])
    )
    assert all(validos[category] >= 8 for category in (2, 3, 4)), validos
