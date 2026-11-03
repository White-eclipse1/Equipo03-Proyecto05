"""Recalcular el pipeline desde la app web.

Despues de eliminar duplicados los artefactos describen un dataset que ya no
existe. Hasta ahora la unica salida era abrir una terminal y correr `dq analyze`
y `dq gate` a mano. Esto lo pone detras de un boton.

Lo que se prueba:

  - que los dos artefactos se escriban de una sola pasada y coincidan entre si,
    porque dos recorridos separados pueden leer datasets distintos si alguien
    toca el disco entre medias;
  - que una compuerta que bloquea sea una respuesta valida y no un error HTTP:
    "el dataset no pasa" es un veredicto, no un fallo del servidor;
  - que dos pulsaciones simultaneas no se pisen;
  - que despues de recalcular, la pantalla de duplicados vuelva a funcionar.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dataset_quality import policy
from dataset_quality.api import artifacts, duplicates
from dataset_quality.api import pipeline as api_pipeline
from dataset_quality.main import create_app
from dataset_quality.models.coco import CocoDataset
from dataset_quality.models.quality import QualityReport
from dataset_quality.tiers import dedupe, pipeline

CONFIG = """
version: 1
min_images_per_class:
  enabled: true
  severity: error
  min_images: 3
  min_classes: 2
small_objects:
  enabled: false
  severity: warning
  area_ratio_threshold: 0.02
  max_ratio: 0.10
class_imbalance:
  enabled: false
  severity: warning
  max_ratio_max_min: 20.0
duplicates:
  enabled: true
  severity: error
  phash_hamming_distance: 5
  max_ratio: 0.01
degenerate_boxes:
  enabled: true
  severity: error
  max_ratio: 0.0
spatial_bias:
  enabled: false
  severity: warning
  grid_size: 3
  max_cell_share: 0.60
splits:
  seed: 42
  ratios:
    train: 0.70
    val: 0.15
    test: 0.15
  tolerance: 0.05
  group_near_duplicates: true
"""


def escribir_imagenes(destino: Path, dataset: CocoDataset) -> None:
    """Imagenes reales, no bytes falsos: el pHash necesita algo que decodificar.

    Ruido con una semilla por imagen, para que ninguna se parezca a otra y el
    check de duplicados salga limpio sin depender de la suerte.
    """
    import numpy as np
    from PIL import Image

    for image in dataset.images:
        rng = np.random.default_rng(image.id)
        pixeles = rng.integers(0, 256, size=(64, 64, 3), dtype=np.uint8)
        Image.fromarray(pixeles).save(destino / image.file_name, quality=95)


def coco(n_imagenes: int = 4) -> CocoDataset:
    return CocoDataset.model_validate(
        {
            "images": [
                {"id": i, "file_name": f"img{i}.jpg", "width": 100, "height": 100}
                for i in range(1, n_imagenes + 1)
            ],
            "annotations": [
                {
                    "id": i,
                    "image_id": i,
                    "category_id": 1 + (i % 2),
                    "bbox": [0.0, 0.0, 10.0, 10.0],
                    "area": 100.0,
                }
                for i in range(1, n_imagenes + 1)
            ],
            "categories": [{"id": 1, "name": "gato"}, {"id": 2, "name": "perro"}],
        }
    )


@pytest.fixture
def taller(tmp_path: Path):
    """Un dataset, una config y un directorio de reportes, todos temporales."""
    imagenes = tmp_path / "images"
    imagenes.mkdir()
    datos = coco()
    escribir_imagenes(imagenes, datos)
    coco_path = tmp_path / "annotations.json"
    coco_path.write_text(datos.model_dump_json(), encoding="utf-8")

    config_path = tmp_path / "quality.yaml"
    config_path.write_text(CONFIG, encoding="utf-8")

    reports = tmp_path / "reports"
    return datos, coco_path, imagenes, config_path, reports


def correr(taller):
    _, coco_path, imagenes, config_path, reports = taller
    return pipeline.refresh(
        coco_path=coco_path,
        images_dir=imagenes,
        config_path=config_path,
        stats_out=reports / "stats.json",
        quality_out=reports / "quality.json",
    )


# --------------------------------------------------------------------------
# Los dos artefactos, de una sola pasada
# --------------------------------------------------------------------------
def test_escribe_los_dos_artefactos(taller) -> None:
    *_, reports = taller

    correr(taller)

    assert (reports / "stats.json").is_file()
    assert (reports / "quality.json").is_file()


def test_los_dos_artefactos_describen_el_mismo_dataset(taller) -> None:
    """El motivo de correrlo de una pasada: que no puedan discrepar."""
    datos, *_, reports = taller

    correr(taller)

    stats = json.loads((reports / "stats.json").read_text(encoding="utf-8"))
    quality = QualityReport.model_validate_json(
        (reports / "quality.json").read_text(encoding="utf-8")
    )
    assert stats["stats"]["totals"]["images"] == quality.totals.images == len(datos.images)
    assert [c["name"] for c in stats["checks"]] == [c.name for c in quality.checks]


def test_los_analizadores_corren_una_sola_vez(taller, monkeypatch) -> None:
    """`dq analyze` y `dq gate` seguidos los recorren dos veces; esto una."""
    from dataset_quality import analyzers

    llamadas = []
    original = analyzers.run_all

    def contar(*args, **kwargs):
        llamadas.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(analyzers, "run_all", contar)
    monkeypatch.setattr(pipeline, "run_all", contar, raising=False)

    correr(taller)

    assert len(llamadas) == 1


def test_el_quality_json_se_puede_releer_con_su_modelo(taller) -> None:
    *_, reports = taller

    correr(taller)

    report = QualityReport.model_validate_json(
        (reports / "quality.json").read_text(encoding="utf-8")
    )
    assert report.schema_version == 1


def test_la_huella_del_reporte_corresponde_al_dataset_en_disco(taller) -> None:
    """Es lo que permite que el boton de duplicados vuelva a funcionar."""
    datos, *_, reports = taller

    resultado = correr(taller)

    report = QualityReport.model_validate_json(
        (reports / "quality.json").read_text(encoding="utf-8")
    )
    assert report.dataset_fingerprint == resultado.dataset_fingerprint
    assert dedupe.build_plan(datos, report).is_empty


# --------------------------------------------------------------------------
# Un veredicto negativo no es un error
# --------------------------------------------------------------------------
def test_una_compuerta_que_bloquea_devuelve_resultado_no_excepcion(taller) -> None:
    """4 imagenes con min_images=3 en 2 clases: gato tiene 2, no llega."""
    resultado = correr(taller)

    assert resultado.status == "fail"
    assert resultado.exit_code == 1
    assert "min_images_per_class" in resultado.blocking


def test_un_dataset_que_pasa_sale_con_cero(taller) -> None:
    _, coco_path, imagenes, config_path, reports = taller
    grande = coco(8)
    escribir_imagenes(imagenes, grande)
    coco_path.write_text(grande.model_dump_json(), encoding="utf-8")

    resultado = pipeline.refresh(
        coco_path=coco_path,
        images_dir=imagenes,
        config_path=config_path,
        stats_out=reports / "stats.json",
        quality_out=reports / "quality.json",
    )

    assert resultado.status == "pass"
    assert resultado.exit_code == 0
    assert resultado.blocking == []


# --------------------------------------------------------------------------
# La API — lo que llama el boton
# --------------------------------------------------------------------------
@pytest.fixture
def api(taller, monkeypatch, env):
    del env
    datos, coco_path, imagenes, config_path, reports = taller
    reports.mkdir(parents=True, exist_ok=True)

    nuevos = {
        name: artifacts.Artifact(art.name, reports / art.path.name, art.model, art.produced_by)
        for name, art in artifacts.ARTIFACTS.items()
    }
    monkeypatch.setattr(artifacts, "ARTIFACTS", nuevos)
    monkeypatch.setattr(artifacts, "REPORTS", reports)
    monkeypatch.setattr(duplicates, "ARTIFACTS", nuevos)
    monkeypatch.setattr(duplicates, "RAW_ANNOTATIONS", coco_path)
    monkeypatch.setattr(duplicates, "RAW_IMAGES", imagenes)
    monkeypatch.setattr(dedupe, "QUARANTINE", reports.parent / "quarantine")
    monkeypatch.setattr(api_pipeline, "RAW_ANNOTATIONS", coco_path)
    monkeypatch.setattr(api_pipeline, "RAW_IMAGES", imagenes)
    # La ruta de `quality.yaml` vive en `policy`: editarla desde Settings y
    # recalcular tienen que apuntar al mismo archivo.
    monkeypatch.setattr(policy, "CONFIG_PATH", config_path)
    monkeypatch.setattr(api_pipeline, "REPORTS", reports)

    client = TestClient(create_app(), raise_server_exceptions=False)
    return client, datos, coco_path, imagenes, reports


def test_el_post_recalcula_y_responde_200_aunque_la_compuerta_bloquee(api) -> None:
    client, *_, reports = api

    response = client.post("/api/pipeline/refresh")

    assert response.status_code == 200
    cuerpo = response.json()
    assert cuerpo["status"] == "fail"
    assert cuerpo["exit_code"] == 1
    assert "min_images_per_class" in cuerpo["blocking"]
    assert (reports / "quality.json").is_file()


def test_el_post_devuelve_los_conteos_nuevos(api) -> None:
    client, datos, *_ = api

    cuerpo = client.post("/api/pipeline/refresh").json()

    assert cuerpo["totals"]["images"] == len(datos.images)
    assert cuerpo["duration_seconds"] >= 0


def test_sin_dataset_da_503_que_manda_a_dvc(api, monkeypatch, tmp_path) -> None:
    client, *_ = api
    monkeypatch.setattr(api_pipeline, "RAW_ANNOTATIONS", tmp_path / "no-existe.json")

    response = client.post("/api/pipeline/refresh")

    assert response.status_code == 503
    assert "dvc pull" in response.json()["detail"]


def test_sin_config_da_503_y_dice_cual_falta(api, monkeypatch, tmp_path) -> None:
    client, *_ = api
    monkeypatch.setattr(policy, "CONFIG_PATH", tmp_path / "no-existe.yaml")

    response = client.post("/api/pipeline/refresh")

    assert response.status_code == 503
    assert "quality.yaml" in response.json()["detail"]


def test_dos_pulsaciones_simultaneas_no_se_pisan(api) -> None:
    """La segunda se rechaza con 409 en vez de escribir el mismo archivo a la vez."""
    client, *_ = api
    assert api_pipeline.LOCK.acquire(blocking=False)
    try:
        response = client.post("/api/pipeline/refresh")
    finally:
        api_pipeline.LOCK.release()

    assert response.status_code == 409
    assert "en curso" in response.json()["detail"]


# --------------------------------------------------------------------------
# El bucle completo: eliminar, recalcular, volver a mirar
# --------------------------------------------------------------------------
def test_tras_eliminar_duplicados_recalcular_devuelve_la_pantalla_a_la_vida(api) -> None:
    """Sin este paso la pantalla se queda en 409 para siempre."""
    client, datos, *_, reports = api
    # Un reporte que marca la imagen 2 como copia, con la huella correcta.
    from dataset_quality.tiers.gate import dataset_fingerprint

    (reports / "quality.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "2026-09-14T00:00:00Z",
                "dataset_fingerprint": dataset_fingerprint(datos),
                "config_version": 1,
                "status": "fail",
                "exit_code": 1,
                "totals": {"images": 4, "annotations": 4, "categories": 2},
                "checks": [
                    {
                        "name": "duplicates",
                        "status": "fail",
                        "severity": "error",
                        "observed": 0.25,
                        "threshold": 0.01,
                        "message": "una copia",
                        "offenders": [2],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert client.post("/api/duplicates/remove").json()["removed_images"] == 1
    # El reporte quedo obsoleto: la pantalla no puede hacer nada mas.
    assert client.get("/api/duplicates/plan").status_code == 409

    assert client.post("/api/pipeline/refresh").status_code == 200

    # Y vuelve a funcionar, ahora sobre el dataset de 3 imagenes.
    plan = client.get("/api/duplicates/plan")
    assert plan.status_code == 200
    assert plan.json()["total_images"] == 3
