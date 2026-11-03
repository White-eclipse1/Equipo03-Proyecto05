"""Frente 7 — la API que alimenta la app web.

Dos cosas que no pueden romperse sin que nadie se entere:

  - un artefacto que falta debe dar 503 con instrucciones, no 500 ni una
    pantalla vacia;
  - un artefacto que existe pero ya no cumple su contrato debe dar 500 en vez
    de llegar al navegador y pintarse mal.
"""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from dataset_quality.api import artifacts
from dataset_quality.main import create_app
from dataset_quality.models.exploration import ExplorationManifest, ExplorationPoint

QUALITY_MINIMO = {
    "schema_version": 1,
    "generated_at": "2026-09-14T00:00:00Z",
    "dataset_fingerprint": "a" * 64,
    "config_version": 1,
    "status": "fail",
    "exit_code": 1,
    "totals": {"images": 10, "annotations": 20, "categories": 2},
    "checks": [
        {
            "name": "duplicates",
            "status": "fail",
            "severity": "error",
            "observed": 0.044,
            "threshold": 0.01,
            "message": "39 pares casi identicos",
            "offenders": [15, 17],
        }
    ],
}


@pytest.fixture
def reports(tmp_path, monkeypatch):
    """Redirige `reports/` a un directorio temporal para cada prueba."""
    monkeypatch.setattr(artifacts, "REPORTS", tmp_path)
    nuevos = {
        name: artifacts.Artifact(art.name, tmp_path / art.path.name, art.model, art.produced_by)
        for name, art in artifacts.ARTIFACTS.items()
    }
    monkeypatch.setattr(artifacts, "ARTIFACTS", nuevos)
    return tmp_path


@pytest.fixture
def client(env, reports) -> TestClient:
    del env, reports
    return TestClient(create_app(), raise_server_exceptions=False)


# --------------------------------------------------------------------------
# Artefacto ausente
# --------------------------------------------------------------------------
def test_sin_artefacto_devuelve_503_y_dice_que_correr(client) -> None:
    response = client.get("/api/quality")

    assert response.status_code == 503
    assert "dq gate" in response.json()["detail"]


def test_status_dice_que_falta_sin_reventar(client) -> None:
    cuerpo = client.get("/api/status").json()

    assert cuerpo["quality"]["available"] is False
    assert cuerpo["splits"]["produced_by"] == "dq split"


# --------------------------------------------------------------------------
# Artefacto presente
# --------------------------------------------------------------------------
def test_sirve_el_artefacto_envuelto(client, reports: Path) -> None:
    (reports / "quality.json").write_text(json.dumps(QUALITY_MINIMO), encoding="utf-8")

    cuerpo = client.get("/api/quality").json()

    assert cuerpo["source"] == "pipeline"
    assert cuerpo["produced_by"] == "dq gate"
    assert cuerpo["data"]["exit_code"] == 1
    assert cuerpo["data"]["checks"][0]["observed"] == pytest.approx(0.044)


def test_status_refleja_lo_que_existe(client, reports: Path) -> None:
    (reports / "quality.json").write_text(json.dumps(QUALITY_MINIMO), encoding="utf-8")

    cuerpo = client.get("/api/status").json()

    assert cuerpo["quality"]["available"] is True
    assert cuerpo["versions"]["available"] is False


# --------------------------------------------------------------------------
# Artefacto corrupto
# --------------------------------------------------------------------------
def test_un_artefacto_que_no_cumple_su_contrato_da_500(client, reports: Path) -> None:
    """Mejor un error explicito que una pantalla pintando basura en silencio."""
    roto = {**QUALITY_MINIMO, "exit_code": 0}  # incoherente con status=fail
    (reports / "quality.json").write_text(json.dumps(roto), encoding="utf-8")

    response = client.get("/api/quality")

    assert response.status_code == 500
    assert "QualityReport" in response.json()["detail"]


def test_json_malformado_da_500_no_se_traga(client, reports: Path) -> None:
    (reports / "splits.json").write_text("{esto no es json", encoding="utf-8")

    assert client.get("/api/splits").status_code == 500


# --------------------------------------------------------------------------
# El contrato de exploracion
# --------------------------------------------------------------------------
def test_exploracion_ida_y_vuelta(client, reports: Path) -> None:
    manifest = ExplorationManifest(
        generated_at="2026-09-14T00:00:00Z",
        method="pca",
        variance_explained=0.361,
        method_detail="histograma de color + miniatura",
        points=[ExplorationPoint(image_id=1, x=0.5, y=-0.2, category_id=3)],
    )
    (reports / "exploration.json").write_text(manifest.model_dump_json(), encoding="utf-8")

    cuerpo = client.get("/api/exploration").json()["data"]

    assert cuerpo["variance_explained"] == pytest.approx(0.361)
    assert cuerpo["points"][0]["category_id"] == 3


# --------------------------------------------------------------------------
# En que remotes esta cada version
# --------------------------------------------------------------------------
VERSION_SIN_REMOTES = {
    "schema_version": 1,
    "versions": [
        {
            "schema_version": 1,
            "version": "0.1.0",
            "created_at": "2026-09-14T00:00:00Z",
            "dataset_fingerprint": "a" * 64,
            "quality_report_fingerprint": "b" * 64,
            "splits_fingerprint": "c" * 64,
            "storage_uri": "s3://dataset-releases/0.1.0/dataset.tar.zst",
            "quality_status": "pass",
            "counts": {"images": 10, "annotations": 20, "categories": 2},
            "notes": None,
        }
    ],
}


def test_una_version_vieja_se_sirve_como_publicada_en_dev(client, reports: Path) -> None:
    """La pantalla leia por aqui, no por el tier, y veia `published_in` vacio.

    El resultado era que versiones publicadas desde hacia meses aparecian como
    si no estuvieran en ningun sitio.
    """
    (reports / "versions.json").write_text(json.dumps(VERSION_SIN_REMOTES), encoding="utf-8")

    entrada = client.get("/api/versions").json()["data"]["versions"][0]

    assert [p["remote"] for p in entrada["published_in"]] == ["dev"]
    assert entrada["published_in"][0]["storage_uri"] == entrada["storage_uri"]


def test_la_migracion_no_reescribe_el_archivo(client, reports: Path) -> None:
    """Es una migracion de LECTURA: el disco se queda como estaba."""
    destino = reports / "versions.json"
    original = json.dumps(VERSION_SIN_REMOTES)
    destino.write_text(original, encoding="utf-8")

    client.get("/api/versions")

    assert destino.read_text(encoding="utf-8") == original


# --------------------------------------------------------------------------
# La miniatura que consume el hover del grafico
# --------------------------------------------------------------------------
def _proyeccion_con(reports: Path, images_dir: Path, file_name: str = "foto.jpg") -> None:
    """Escribe un `exploration.json` de un punto y su imagen en disco."""
    images_dir.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (640, 480), (120, 30, 200)).save(images_dir / file_name, "JPEG")

    manifest = ExplorationManifest(
        generated_at="2026-09-14T00:00:00Z",
        method="pca",
        variance_explained=0.42,
        method_detail="histograma de color + miniatura",
        points=[ExplorationPoint(image_id=7, x=0.1, y=0.2, category_id=1, file_name=file_name)],
    )
    (reports / "exploration.json").write_text(manifest.model_dump_json(), encoding="utf-8")


def test_la_miniatura_sale_en_jpeg_y_cabe_en_el_lado_pedido(
    client, reports: Path, tmp_path: Path, monkeypatch
) -> None:
    images = tmp_path / "imagenes"
    _proyeccion_con(reports, images)
    monkeypatch.setattr("dataset_quality.tiers.ingest.RAW_IMAGES", images)

    respuesta = client.get("/api/exploration/thumbnail/7")

    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"] == "image/jpeg"
    with Image.open(BytesIO(respuesta.content)) as miniatura:
        assert max(miniatura.size) <= artifacts.THUMBNAIL_PX
        # Y conserva la proporcion original (640x480 -> 4:3).
        assert miniatura.size[0] / miniatura.size[1] == pytest.approx(4 / 3, abs=0.02)


def test_un_image_id_que_no_esta_en_la_proyeccion_da_404(
    client, reports: Path, tmp_path: Path, monkeypatch
) -> None:
    images = tmp_path / "imagenes"
    _proyeccion_con(reports, images)
    monkeypatch.setattr("dataset_quality.tiers.ingest.RAW_IMAGES", images)

    respuesta = client.get("/api/exploration/thumbnail/999")

    assert respuesta.status_code == 404
    assert "999" in respuesta.json()["detail"]


def test_el_nombre_de_archivo_sale_del_manifiesto_no_de_la_url(
    client, reports: Path, tmp_path: Path, monkeypatch
) -> None:
    """La ruta servida solo puede ser una que el pipeline ya registro.

    Aunque el COCO traiga un `file_name` con componentes de directorio, lo
    servido se queda dentro de `data/raw/images/`.
    """
    images = tmp_path / "imagenes"
    images.mkdir(parents=True)
    Image.new("RGB", (32, 32), (10, 10, 10)).save(images / "secreta.jpg", "JPEG")
    (tmp_path / "secreta.jpg").write_bytes(b"no soy una imagen del dataset")

    manifest = ExplorationManifest(
        generated_at="2026-09-14T00:00:00Z",
        method="pca",
        variance_explained=0.42,
        method_detail="histograma de color + miniatura",
        points=[
            ExplorationPoint(image_id=7, x=0.1, y=0.2, category_id=1, file_name="../secreta.jpg")
        ],
    )
    (reports / "exploration.json").write_text(manifest.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr("dataset_quality.tiers.ingest.RAW_IMAGES", images)

    respuesta = client.get("/api/exploration/thumbnail/7")

    # `../` se descarta: sirve `imagenes/secreta.jpg`, no el archivo de fuera.
    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"] == "image/jpeg"


def test_una_proyeccion_sin_file_name_lo_dice_en_vez_de_romper(
    client, reports: Path, tmp_path: Path, monkeypatch
) -> None:
    """Retrocompatibilidad: un `exploration.json` anterior a `file_name`."""
    images = tmp_path / "imagenes"
    images.mkdir(parents=True)
    manifest = ExplorationManifest(
        generated_at="2026-09-14T00:00:00Z",
        method="pca",
        variance_explained=0.42,
        method_detail="histograma de color + miniatura",
        points=[ExplorationPoint(image_id=7, x=0.1, y=0.2, category_id=1)],
    )
    (reports / "exploration.json").write_text(manifest.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr("dataset_quality.tiers.ingest.RAW_IMAGES", images)

    respuesta = client.get("/api/exploration/thumbnail/7")

    assert respuesta.status_code == 503
    assert "dq analyze" in respuesta.json()["detail"]


def test_si_la_imagen_ya_no_esta_en_disco_da_404(
    client, reports: Path, tmp_path: Path, monkeypatch
) -> None:
    images = tmp_path / "imagenes"
    _proyeccion_con(reports, images)
    (images / "foto.jpg").unlink()
    monkeypatch.setattr("dataset_quality.tiers.ingest.RAW_IMAGES", images)

    assert client.get("/api/exploration/thumbnail/7").status_code == 404


def test_un_image_id_repetido_se_rechaza() -> None:
    """Dos puntos para la misma imagen significan que el calculo se corrio dos veces."""
    with pytest.raises(ValueError, match="repetido"):
        ExplorationManifest(
            generated_at="2026-09-14T00:00:00Z",
            method="pca",
            variance_explained=0.5,
            method_detail="x",
            points=[
                ExplorationPoint(image_id=1, x=0.0, y=0.0),
                ExplorationPoint(image_id=1, x=1.0, y=1.0),
            ],
        )


def test_la_varianza_explicada_es_una_proporcion() -> None:
    for invalida in (-0.1, 1.5):
        with pytest.raises(ValueError):
            ExplorationManifest(
                generated_at="2026-09-14T00:00:00Z",
                method="pca",
                variance_explained=invalida,
                method_detail="x",
                points=[],
            )


# --------------------------------------------------------------------------
# La SPA
# --------------------------------------------------------------------------
def test_una_ruta_de_navegacion_no_choca_con_la_api(client) -> None:
    """El catch-all de la SPA no puede tragarse `/api/*` ni `/health`."""
    assert client.get("/health").status_code in {200, 503}
    assert client.get("/api/status").status_code == 200
