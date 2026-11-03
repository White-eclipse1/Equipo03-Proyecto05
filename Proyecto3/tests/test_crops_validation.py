"""Validacion de cajas COCO antes de recortar (F2 T07, criterio 1.2).

Cada anotacion del release termina en exactamente uno de dos lados: una caja
valida lista para recortar, que conserva sus 4 identificadores de origen y la
bbox original, o una exclusion con motivo (`docs/contratos.md` §2). Las
pruebas usan el fixture de `tests/fixtures/p3/` para los casos borde reales y
COCOs sinteticos para cada regla por separado.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from p3.data.crops import (
    CropSource,
    Exclusion,
    ImageGeometry,
    read_image_sizes,
    validate_annotations,
)

FIXTURE = Path(__file__).parent / "fixtures" / "p3"
INCLUIDAS = {2, 3, 4}  # person, dog, cat
FIXTURE_SIZE = (128, 96)
ORIENTATION = 0x0112


@pytest.fixture(scope="module")
def coco() -> dict[str, Any]:
    return json.loads((FIXTURE / "annotations.coco.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def sizes(coco: dict[str, Any]) -> dict[int, ImageGeometry]:
    return read_image_sizes(coco["images"], FIXTURE / "images")


def _coco(bbox: list[Any], *, category_id: int = 2, width: int = 100, height: int = 80) -> dict:
    """COCO minimo de una imagen y una anotacion."""
    return {
        "images": [{"id": 1, "file_name": "a.jpg", "width": width, "height": height}],
        "categories": [{"id": 2, "name": "person"}, {"id": 5, "name": "bicycle"}],
        "annotations": [{"id": 7, "image_id": 1, "category_id": category_id, "bbox": bbox}],
    }


def _motivo(coco: dict, sizes: dict[int, ImageGeometry], incluidas=frozenset({2})) -> str:
    result = validate_annotations(coco, incluidas, sizes)
    assert result.valid == ()
    [exclusion] = result.exclusions
    return exclusion.reason


# --- Tamanos reales de las imagenes -------------------------------------------------------


def test_read_image_sizes_lee_las_dimensiones_reales_del_archivo(
    sizes: dict[int, ImageGeometry],
) -> None:
    assert len(sizes) == 29
    assert {(g.width, g.height) for g in sizes.values()} == {FIXTURE_SIZE}
    assert not any(g.exif_transposed for g in sizes.values())


def test_read_image_sizes_omite_la_imagen_que_falta(sizes: dict[int, ImageGeometry]) -> None:
    assert 27 not in sizes


def test_read_image_sizes_omite_un_archivo_que_no_es_imagen(tmp_path: Path) -> None:
    (tmp_path / "roto.jpg").write_bytes(b"esto no es un jpg")
    Image.new("RGB", (40, 30)).save(tmp_path / "bien.jpg")
    images = [
        {"id": 1, "file_name": "roto.jpg", "width": 40, "height": 30},
        {"id": 2, "file_name": "bien.jpg", "width": 40, "height": 30},
    ]
    assert read_image_sizes(images, tmp_path) == {2: ImageGeometry(40, 30)}


def test_read_image_sizes_aplica_la_rotacion_exif(tmp_path: Path) -> None:
    # Guardada 100x80 con orientacion 6: se muestra (y se anoto en P1) como 80x100.
    exif = Image.Exif()
    exif[ORIENTATION] = 6
    Image.new("RGB", (100, 80)).save(tmp_path / "rotada.jpg", exif=exif)
    images = [{"id": 1, "file_name": "rotada.jpg", "width": 100, "height": 80}]
    assert read_image_sizes(images, tmp_path) == {1: ImageGeometry(80, 100, exif_transposed=True)}


# --- Fixture: los casos borde reales -------------------------------------------------------


def test_fixture_deja_10_cat_9_dog_9_person(
    coco: dict[str, Any], sizes: dict[int, ImageGeometry]
) -> None:
    result = validate_annotations(coco, INCLUIDAS, sizes)
    assert Counter(c.category_name for c in result.valid) == {"cat": 10, "dog": 9, "person": 9}


def test_fixture_excluye_faltante_degenerada_y_fuera_de_imagen(
    coco: dict[str, Any], sizes: dict[int, ImageGeometry]
) -> None:
    result = validate_annotations(coco, INCLUIDAS, sizes)
    assert result.exclusions == (
        Exclusion(annotation_id=27, source_image_id=27, reason="missing_image"),
        Exclusion(annotation_id=30, source_image_id=29, reason="degenerate_bbox"),
        Exclusion(annotation_id=31, source_image_id=30, reason="bbox_out_of_bounds"),
    )


def test_caja_valida_conserva_los_identificadores_y_la_bbox_original(
    coco: dict[str, Any], sizes: dict[int, ImageGeometry]
) -> None:
    result = validate_annotations(coco, INCLUIDAS, sizes)
    [dog] = [c for c in result.valid if c.annotation_id == 29]
    assert dog == CropSource(
        annotation_id=29,
        source_image_id=28,
        source_file_name="img_028.jpg",
        category_id=3,
        category_name="dog",
        bbox_xywh=(70.0, 15.0, 50.0, 50.0),
    )


def test_un_original_produce_un_recorte_por_caja_con_su_propia_etiqueta(
    coco: dict[str, Any], sizes: dict[int, ImageGeometry]
) -> None:
    result = validate_annotations(coco, INCLUIDAS, sizes)
    de_la_28 = {(c.annotation_id, c.category_name) for c in result.valid if c.source_image_id == 28}
    assert de_la_28 == {(28, "person"), (29, "dog")}


def test_la_etiqueta_sale_de_la_categoria_de_la_caja(
    coco: dict[str, Any], sizes: dict[int, ImageGeometry]
) -> None:
    categoria_de = {a["id"]: a["category_id"] for a in coco["annotations"]}
    nombre_de = {c["id"]: c["name"] for c in coco["categories"]}
    result = validate_annotations(coco, INCLUIDAS, sizes)
    for crop in result.valid:
        assert crop.category_id == categoria_de[crop.annotation_id]
        assert crop.category_name == nombre_de[crop.category_id]


def test_cada_anotacion_cae_exactamente_en_un_lado_y_en_orden(
    coco: dict[str, Any], sizes: dict[int, ImageGeometry]
) -> None:
    result = validate_annotations(coco, INCLUIDAS, sizes)
    validas = [c.annotation_id for c in result.valid]
    excluidas = [e.annotation_id for e in result.exclusions]
    assert validas == sorted(validas)
    assert excluidas == sorted(excluidas)
    assert sorted(validas + excluidas) == sorted(a["id"] for a in coco["annotations"])


# --- Categorias no incluidas ---------------------------------------------------------------


def test_categoria_no_incluida_se_excluye_con_motivo(
    coco: dict[str, Any], sizes: dict[int, ImageGeometry]
) -> None:
    result = validate_annotations(coco, {2, 3}, sizes)
    cats = [a for a in coco["annotations"] if a["category_id"] == 4]
    excluidas = [e for e in result.exclusions if e.reason == "excluded_category"]
    assert {e.annotation_id for e in excluidas} == {a["id"] for a in cats}
    assert all(c.category_id in {2, 3} for c in result.valid)


# --- Cajas degeneradas ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "bbox",
    [
        [10, 10, 0, 20],
        [10, 10, 20, 0],
        [10, 10, -5, 20],
        [10, 10, 20, -5],
        [10, 10, math.nan, 20],
        [10, 10, 20, math.inf],
        [math.nan, 10, 20, 20],
        [10, 10, 20],
        [10, 10, 20, 20, 5],
        None,
        [10, 10, "20", 20],
    ],
)
def test_caja_degenerada_o_malformada_se_rechaza(bbox: Any) -> None:
    assert _motivo(_coco(bbox), {1: ImageGeometry(100, 80)}) == "degenerate_bbox"


# --- Cajas fuera de la imagen ------------------------------------------------------------


@pytest.mark.parametrize(
    "bbox",
    [
        [-1, 10, 20, 20],
        [10, -0.5, 20, 20],
        [90, 10, 20, 20],
        [10, 70, 20, 20.5],
    ],
)
def test_caja_fuera_de_la_imagen_se_rechaza(bbox: list[float]) -> None:
    assert _motivo(_coco(bbox), {1: ImageGeometry(100, 80)}) == "bbox_out_of_bounds"


def test_caja_que_toca_exactamente_los_bordes_es_valida() -> None:
    result = validate_annotations(_coco([0, 0, 100, 80]), {2}, {1: ImageGeometry(100, 80)})
    assert [c.bbox_xywh for c in result.valid] == [(0.0, 0.0, 100.0, 80.0)]
    assert result.exclusions == ()


# --- Coordenadas del COCO frente al archivo real ----------------------------------------
# Las cajas se dibujaron en P1 sobre la imagen que mostraba el navegador: con la rotacion
# EXIF aplicada y con el tamano que registra el COCO. Los limites se revisan en ese espacio
# y la caja se escala al archivo real para recortar.


def test_los_limites_se_revisan_en_las_coordenadas_del_coco() -> None:
    # El archivo mide 200x160 (el doble), pero la caja se sale de los 100x80 del COCO.
    coco = _coco([50, 40, 60, 20])
    assert _motivo(coco, {1: ImageGeometry(200, 160)}) == "bbox_out_of_bounds"


def test_archivo_mas_grande_que_el_coco_escala_la_caja() -> None:
    result = validate_annotations(_coco([20, 10, 30, 30]), {2}, {1: ImageGeometry(200, 160)})
    [crop] = result.valid
    assert crop.bbox_xywh == (20.0, 10.0, 30.0, 30.0)
    assert crop.pixel_scale == (2.0, 2.0)


def test_diferencia_pequena_de_proporcion_se_escala_por_eje() -> None:
    # Caso real (imagen 8 del release): 728x425 en el COCO, 726x448 en disco (5.7 %).
    coco = _coco([133, 45, 294, 341], width=728, height=425)
    [crop] = validate_annotations(coco, {2}, {1: ImageGeometry(726, 448)}).valid
    assert crop.pixel_scale == pytest.approx((726 / 728, 448 / 425))


def test_proporcion_muy_distinta_se_excluye() -> None:
    # 100x80 en el COCO y 100x100 en disco: 25 % de deformacion, no es la misma imagen.
    assert _motivo(_coco([10, 10, 20, 20]), {1: ImageGeometry(100, 100)}) == "size_mismatch"


def test_imagen_rotada_por_exif_escala_por_eje_desde_la_cabecera() -> None:
    # P1 mostro la foto de pie (3000x4000) pero guardo el tamano de la cabecera (4000x3000)
    # y llevo la caja a ese espacio eje por eje. Verificado a ojo en las anotaciones 39, 43,
    # 47, 57, 59 y 61 del release 0.1.3.
    coco = _coco([100, 100, 400, 300], width=4000, height=3000)
    geometry = ImageGeometry(3000, 4000, exif_transposed=True)
    [crop] = validate_annotations(coco, {2}, {1: geometry}).valid
    assert crop.pixel_scale == pytest.approx((3000 / 4000, 4000 / 3000))


def test_imagen_rotada_por_exif_revisa_limites_en_el_espacio_del_coco() -> None:
    geometry = ImageGeometry(3000, 4000, exif_transposed=True)
    dentro = _coco([3500, 100, 400, 300], width=4000, height=3000)
    assert validate_annotations(dentro, {2}, {1: geometry}).exclusions == ()
    fuera = _coco([100, 2800, 100, 300], width=4000, height=3000)
    assert _motivo(fuera, {1: geometry}) == "bbox_out_of_bounds"


# --- Imagenes faltantes --------------------------------------------------------------------


def test_imagen_sin_archivo_se_rechaza() -> None:
    assert _motivo(_coco([10, 10, 20, 20]), {}) == "missing_image"


def test_anotacion_que_apunta_a_una_imagen_inexistente_en_el_coco_se_rechaza() -> None:
    coco = _coco([10, 10, 20, 20])
    coco["annotations"][0]["image_id"] = 99
    result = validate_annotations(coco, {2}, {1: ImageGeometry(100, 80)})
    assert result.exclusions == (
        Exclusion(annotation_id=7, source_image_id=99, reason="missing_image"),
    )


# --- Prioridad de motivos ------------------------------------------------------------------


def test_categoria_excluida_gana_sobre_cualquier_otro_motivo() -> None:
    assert _motivo(_coco([10, 10, 0, 20], category_id=5), {}) == "excluded_category"


def test_imagen_faltante_gana_sobre_caja_degenerada() -> None:
    assert _motivo(_coco([10, 10, 0, 20]), {}) == "missing_image"


def test_no_modifica_el_coco_de_entrada(
    coco: dict[str, Any], sizes: dict[int, ImageGeometry]
) -> None:
    antes = json.dumps(coco, sort_keys=True)
    validate_annotations(coco, INCLUIDAS, sizes)
    assert json.dumps(coco, sort_keys=True) == antes
