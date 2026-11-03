"""Tier 1 — la ingesta valida antes de escribir y no depende de Docker.

Estas pruebas no tocan MariaDB ni MinIO: comprueban la parte que decide si el
dataset entra o se rechaza, que es donde estan los errores que importan.
"""

from __future__ import annotations

import json

import pytest

from dataset_quality.models.errors import DatasetValidationError
from dataset_quality.storage import file_sha256, image_key
from dataset_quality.tables import Annotation, Base, Category, Image
from dataset_quality.tiers import ingest

VALID_COCO = {
    "images": [{"id": 1, "file_name": "a.jpg", "width": 100, "height": 80}],
    "annotations": [
        {
            "id": 1,
            "image_id": 1,
            "category_id": 1,
            "bbox": [10.0, 10.0, 20.0, 30.0],
            "area": 600.0,
            "iscrowd": 0,
        }
    ],
    "categories": [{"id": 1, "name": "car"}],
}


def write_coco(tmp_path, payload: dict):
    path = tmp_path / "annotations.coco.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# Validacion de entrada
# --------------------------------------------------------------------------
def test_coco_valido_se_carga(tmp_path) -> None:
    dataset = ingest.load_raw(write_coco(tmp_path, VALID_COCO))
    assert len(dataset.images) == 1
    assert dataset.annotations[0].bbox == (10.0, 10.0, 20.0, 30.0)


def test_archivo_inexistente_explica_que_hacer(tmp_path) -> None:
    with pytest.raises(DatasetValidationError) as error:
        ingest.load_raw(tmp_path / "no-existe.json")
    assert "export_from_mp1" in str(error.value)


def test_json_malformado_senala_la_linea(tmp_path) -> None:
    path = tmp_path / "annotations.coco.json"
    path.write_text('{"images": [', encoding="utf-8")

    with pytest.raises(DatasetValidationError) as error:
        ingest.load_raw(path)
    assert "JSON malformado" in str(error.value)


def test_coco_invalido_nombra_el_campo(tmp_path) -> None:
    roto = json.loads(json.dumps(VALID_COCO))
    roto["images"][0]["width"] = 0  # debe ser > 0

    with pytest.raises(DatasetValidationError) as error:
        ingest.load_raw(write_coco(tmp_path, roto))

    rendered = str(error.value)
    assert "images.0.width" in rendered
    assert "recibido: 0" in rendered


def test_anotacion_huerfana_se_rechaza(tmp_path) -> None:
    roto = json.loads(json.dumps(VALID_COCO))
    roto["annotations"][0]["image_id"] = 99

    with pytest.raises(DatasetValidationError):
        ingest.load_raw(write_coco(tmp_path, roto))


# --------------------------------------------------------------------------
# Archivos en disco
# --------------------------------------------------------------------------
def test_detecta_imagenes_que_faltan_en_disco(tmp_path) -> None:
    dataset = ingest.load_raw(write_coco(tmp_path, VALID_COCO))
    vacio = tmp_path / "images"
    vacio.mkdir()

    assert ingest.check_files_present(dataset, vacio) == ["a.jpg"]


def test_no_reporta_nada_si_estan_todas(tmp_path) -> None:
    dataset = ingest.load_raw(write_coco(tmp_path, VALID_COCO))
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    (images_dir / "a.jpg").write_bytes(b"jpeg")

    assert ingest.check_files_present(dataset, images_dir) == []


def test_run_aborta_si_falta_una_imagen(tmp_path, monkeypatch) -> None:
    """No debe subir ni escribir nada si la descarga quedo incompleta."""
    path = write_coco(tmp_path, VALID_COCO)
    vacio = tmp_path / "images"
    vacio.mkdir()

    def explotar(*args, **kwargs):
        raise AssertionError("no deberia intentar subir con la descarga incompleta")

    monkeypatch.setattr(ingest, "upload_images", explotar)

    with pytest.raises(DatasetValidationError) as error:
        ingest.run(path=path, images_dir=vacio)
    assert "no estan en disco" in str(error.value)


# --------------------------------------------------------------------------
# Almacenamiento de objetos
# --------------------------------------------------------------------------
def test_la_llave_lleva_prefijo_raw() -> None:
    assert image_key("img_0001.jpg") == "raw/img_0001.jpg"


def test_sha256_cambia_con_el_contenido(tmp_path) -> None:
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    a.write_bytes(b"contenido")
    b.write_bytes(b"contenido")

    assert file_sha256(a) == file_sha256(b)

    b.write_bytes(b"contenido!")
    assert file_sha256(a) != file_sha256(b)


# --------------------------------------------------------------------------
# Tablas
# --------------------------------------------------------------------------
def test_las_tablas_estan_declaradas() -> None:
    assert set(Base.metadata.tables) == {
        "categories",
        "images",
        "annotations",
        "splits",
        "dataset_versions",
        "copilot_tool_calls",
    }


def test_la_imagen_guarda_la_llave_no_el_binario() -> None:
    """El binario vive en MinIO; en la fila solo queda como encontrarlo."""
    columns = set(Image.__table__.columns.keys())

    assert {"storage_key", "size_bytes", "sha256"} <= columns
    # Ninguna columna binaria: nada de BLOB ni de `data`.
    assert not any(
        column.type.__class__.__name__ in {"LargeBinary", "BLOB"}
        for column in Image.__table__.columns
    )


def test_borrar_una_imagen_arrastra_sus_cajas() -> None:
    fk = next(iter(Annotation.__table__.c.image_id.foreign_keys))
    assert fk.ondelete == "CASCADE"


def test_no_se_puede_borrar_una_clase_en_uso() -> None:
    """Una categoria con anotaciones no debe poder desaparecer."""
    fk = next(iter(Annotation.__table__.c.category_id.foreign_keys))
    assert fk.ondelete == "RESTRICT"


def test_los_ids_del_coco_se_conservan() -> None:
    # Si la base reasignara ids, se romperia la trazabilidad con el Proyecto 1.
    for table in (Category, Image, Annotation):
        assert table.__table__.c.id.autoincrement is False
