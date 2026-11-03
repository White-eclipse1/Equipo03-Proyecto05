"""Generacion de recortes y registro de exclusiones (F2 T07, criterio 1.2).

Cada caja valida se convierte en un recorte PNG cuyos pixeles son exactamente
los de la caja en el original, con los 4 identificadores de origen y la bbox
original. Las cajas descartadas van a `exclusions.csv` con su motivo.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from p3.data.crops import (
    CropSource,
    Exclusion,
    crop_box,
    crop_id,
    generate_crops,
    read_image_sizes,
    validate_annotations,
    write_exclusions_csv,
)

FIXTURE = Path(__file__).parent / "fixtures" / "p3"
ROJO = (255, 0, 0)
AZUL = (0, 0, 255)


def source(
    annotation_id: int,
    bbox: tuple[float, float, float, float],
    *,
    image_id: int = 1,
    file_name: str = "a.png",
    category_id: int = 2,
    name: str = "person",
) -> CropSource:
    return CropSource(annotation_id, image_id, file_name, category_id, name, bbox)


@pytest.fixture
def lienzo(tmp_path: Path) -> Path:
    """Imagen 100x80 azul con un rectangulo rojo exacto en x 20..49, y 10..39."""
    images = tmp_path / "images"
    images.mkdir()
    image = Image.new("RGB", (100, 80), AZUL)
    image.paste(ROJO, (20, 10, 50, 40))
    image.save(images / "a.png")
    return images


# --- Identificador y caja en pixeles ------------------------------------------------------


def test_crop_id_del_contrato() -> None:
    assert crop_id("0.1.3", 1234) == "0.1.3:a1234"


def test_caja_entera_se_recorta_exacta() -> None:
    assert crop_box((20.0, 10.0, 30.0, 30.0), (100, 80)) == (20, 10, 50, 40)


def test_caja_con_decimales_cubre_todos_los_pixeles_que_toca() -> None:
    # piso a la izquierda/arriba y techo a la derecha/abajo
    assert crop_box((20.4, 10.6, 29.2, 29.1), (100, 80)) == (20, 10, 50, 40)


@pytest.mark.parametrize(
    ("bbox", "esperada"),
    [
        ((20.2, 10.2, 29.1, 29.1), (20, 10, 50, 40)),  # borde en 49.3: techo 50, no 49
        ((20.7, 10.7, 29.6, 29.6), (20, 10, 51, 41)),  # borde en 50.3: techo 51
    ],
)
def test_bordes_derecho_e_inferior_usan_techo_y_no_redondeo(
    bbox: tuple[float, float, float, float], esperada: tuple[int, int, int, int]
) -> None:
    assert crop_box(bbox, (100, 80)) == esperada


def test_caja_nunca_se_sale_del_lienzo() -> None:
    assert crop_box((0.0, 0.0, 100.0, 80.0), (100, 80)) == (0, 0, 100, 80)


def test_caja_minima_tiene_al_menos_un_pixel() -> None:
    left, top, right, bottom = crop_box((5.2, 5.2, 0.1, 0.1), (100, 80))
    assert right - left >= 1 and bottom - top >= 1


# --- Recortes -----------------------------------------------------------------------------


def test_el_recorte_tiene_exactamente_los_pixeles_de_la_caja(lienzo: Path, tmp_path: Path) -> None:
    out = tmp_path / "crops"
    [record] = generate_crops(
        [source(7, (20.0, 10.0, 30.0, 30.0))], lienzo, out, release_id="9.9.9"
    )
    with Image.open(out / record.crop_path) as crop:
        assert crop.size == (30, 30)
        assert crop.mode == "RGB"
        assert set(crop.getdata()) == {ROJO}


def test_un_desfase_de_un_pixel_se_nota(lienzo: Path, tmp_path: Path) -> None:
    out = tmp_path / "crops"
    [record] = generate_crops(
        [source(7, (19.0, 10.0, 30.0, 30.0))], lienzo, out, release_id="9.9.9"
    )
    with Image.open(out / record.crop_path) as crop:
        assert AZUL in set(crop.getdata())


def test_el_registro_conserva_los_identificadores_y_la_bbox(lienzo: Path, tmp_path: Path) -> None:
    out = tmp_path / "crops"
    [record] = generate_crops(
        [source(7, (20.5, 10.0, 29.5, 30.0), image_id=3, category_id=3, name="dog")],
        lienzo,
        out,
        release_id="9.9.9",
    )
    assert record.crop_id == "9.9.9:a7"
    assert (record.annotation_id, record.source_image_id) == (7, 3)
    assert (record.category_id, record.category_name) == (3, "dog")
    assert record.source_file_name == "a.png"
    assert record.bbox_xywh == (20.5, 10.0, 29.5, 30.0)
    assert record.crop_box_xyxy == (20, 10, 50, 40)
    assert record.crop_path == "dog/9.9.9_a7.png"
    assert (record.width, record.height) == (30, 30)


def test_un_original_da_un_recorte_por_caja(lienzo: Path, tmp_path: Path) -> None:
    out = tmp_path / "crops"
    records = generate_crops(
        [
            source(8, (60.0, 50.0, 20.0, 20.0), category_id=3, name="dog"),
            source(7, (20.0, 10.0, 30.0, 30.0)),
        ],
        lienzo,
        out,
        release_id="9.9.9",
    )
    assert [(r.annotation_id, r.category_name) for r in records] == [(7, "person"), (8, "dog")]
    with Image.open(out / records[1].crop_path) as crop:
        assert set(crop.getdata()) == {AZUL}


def test_generar_dos_veces_da_los_mismos_bytes(lienzo: Path, tmp_path: Path) -> None:
    sources = [source(7, (20.0, 10.0, 30.0, 30.0))]
    hashes = []
    for run in ("a", "b"):
        out = tmp_path / run
        [record] = generate_crops(sources, lienzo, out, release_id="9.9.9")
        hashes.append(hashlib.sha256((out / record.crop_path).read_bytes()).hexdigest())
    assert hashes[0] == hashes[1]


def test_fixture_completo_da_28_recortes_trazables(tmp_path: Path) -> None:
    coco: dict[str, Any] = json.loads(
        (FIXTURE / "annotations.coco.json").read_text(encoding="utf-8")
    )
    sizes = read_image_sizes(coco["images"], FIXTURE / "images")
    result = validate_annotations(coco, {2, 3, 4}, sizes)
    out = tmp_path / "crops"
    records = generate_crops(result.valid, FIXTURE / "images", out, release_id="0.0.0")

    assert len(records) == 28
    assert len({r.crop_id for r in records}) == 28
    anotaciones = {a["id"]: a for a in coco["annotations"]}
    for record in records:
        ann = anotaciones[record.annotation_id]
        assert record.source_image_id == ann["image_id"]
        assert record.category_id == ann["category_id"]
        assert list(record.bbox_xywh) == ann["bbox"]
        with Image.open(out / record.crop_path) as crop:
            assert crop.size == (record.width, record.height)
    # Las excluidas no producen archivo.
    assert not list(out.rglob("0.0.0_a30.png"))
    assert not list(out.rglob("0.0.0_a31.png"))


# --- exclusions.csv -----------------------------------------------------------------------


def test_exclusions_csv_con_motivos(tmp_path: Path) -> None:
    path = tmp_path / "exclusions.csv"
    write_exclusions_csv(
        [
            Exclusion(annotation_id=30, source_image_id=29, reason="degenerate_bbox"),
            Exclusion(annotation_id=27, source_image_id=27, reason="missing_image"),
        ],
        path,
    )
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows == [
        {"annotation_id": "27", "image_id": "27", "reason": "missing_image"},
        {"annotation_id": "30", "image_id": "29", "reason": "degenerate_bbox"},
    ]
    assert b"\r\n" not in path.read_bytes()


def test_exclusions_csv_vacio_conserva_el_encabezado(tmp_path: Path) -> None:
    path = tmp_path / "exclusions.csv"
    write_exclusions_csv([], path)
    assert path.read_text(encoding="utf-8") == "annotation_id,image_id,reason\n"


# --- Rotacion EXIF y tamano distinto al del COCO (hallazgos de la revision de F2) ----------


def _coco_una_caja(bbox: list[float], width: int, height: int) -> dict[str, Any]:
    return {
        "images": [{"id": 1, "file_name": "a.png", "width": width, "height": height}],
        "categories": [{"id": 2, "name": "person"}],
        "annotations": [{"id": 7, "image_id": 1, "category_id": 2, "bbox": bbox}],
    }


def test_foto_rotada_por_exif_se_recorta_como_se_anoto(tmp_path: Path) -> None:
    # Lo que se vio en P1: 80x100 de pie, con la persona (roja) en x 10..39, y 50..89.
    vista = Image.new("RGB", (80, 100), AZUL)
    vista.paste(ROJO, (10, 50, 40, 90))
    # En disco va acostada (100x80) con orientacion 6, como la guarda un celular.
    images = tmp_path / "images"
    images.mkdir()
    exif = Image.Exif()
    exif[0x0112] = 6
    vista.transpose(Image.Transpose.ROTATE_90).save(images / "a.png", exif=exif)
    # P1 guardo la cabecera (100x80) y llevo la caja a ese espacio eje por eje:
    # x por 100/80 y y por 80/100.
    coco = _coco_una_caja([12.5, 40, 37.5, 32], width=100, height=80)

    result = validate_annotations(coco, {2}, read_image_sizes(coco["images"], images))
    [record] = generate_crops(result.valid, images, tmp_path / "crops", release_id="9.9.9")
    with Image.open(tmp_path / "crops" / record.crop_path) as crop:
        assert crop.size == (30, 40)
        assert set(crop.getdata()) == {ROJO}


def test_archivo_mas_grande_que_el_coco_recorta_la_caja_escalada(tmp_path: Path) -> None:
    images = tmp_path / "images"
    images.mkdir()
    grande = Image.new("RGB", (200, 160), AZUL)
    grande.paste(ROJO, (40, 20, 100, 80))  # la caja (20, 10, 30, 30) del COCO, al doble
    grande.save(images / "a.png")
    coco = _coco_una_caja([20, 10, 30, 30], width=100, height=80)

    result = validate_annotations(coco, {2}, read_image_sizes(coco["images"], images))
    [record] = generate_crops(result.valid, images, tmp_path / "crops", release_id="9.9.9")
    assert record.bbox_xywh == (20.0, 10.0, 30.0, 30.0)
    assert record.pixel_scale == (2.0, 2.0)
    assert record.crop_box_xyxy == (40, 20, 100, 80)
    with Image.open(tmp_path / "crops" / record.crop_path) as crop:
        assert set(crop.getdata()) == {ROJO}
