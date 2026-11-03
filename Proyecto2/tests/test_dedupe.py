"""Eliminacion de duplicados — la unica operacion que modifica el dataset.

Lo que se prueba aqui no es que el conteo salga bien. Es que la operacion no
pueda destruir datos por accidente:

  - que derive lo que sobra del reporte y no de una cuenta propia, para que lo
    que se elimina sea exactamente lo que la pantalla mostro;
  - que se niegue a correr si el reporte ya no describe el dataset en disco;
  - que mueva a cuarentena en vez de borrar, para que un falso positivo del
    pHash se deshaga;
  - que el COCO que queda en disco siga cumpliendo el contrato.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dataset_quality.api import artifacts, duplicates
from dataset_quality.main import create_app
from dataset_quality.models.coco import CocoDataset
from dataset_quality.models.quality import CheckResult, QualityReport, QualityTotals
from dataset_quality.tiers import dedupe
from dataset_quality.tiers.gate import dataset_fingerprint


# --------------------------------------------------------------------------
# Material de prueba
# --------------------------------------------------------------------------
def coco(n_imagenes: int = 4) -> CocoDataset:
    """Dataset minimo: una caja por imagen, dos categorias."""
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


def reporte(
    dataset: CocoDataset,
    offenders: list[int],
    *,
    status: str = "fail",
    fingerprint: str | None = None,
) -> QualityReport:
    """Reporte cuya huella corresponde al dataset, salvo que se pida otra."""
    return QualityReport(
        generated_at="2026-09-14T00:00:00Z",
        dataset_fingerprint=fingerprint or dataset_fingerprint(dataset),
        config_version=1,
        status="fail",
        exit_code=1,
        totals=QualityTotals(
            images=len(dataset.images),
            annotations=len(dataset.annotations),
            categories=len(dataset.categories),
        ),
        checks=[
            CheckResult(
                name="duplicates",
                status=status,
                severity="warning",
                observed=0.5,
                threshold=0.01,
                message="copias",
                offenders=offenders,
            )
        ],
    )


@pytest.fixture
def dataset_en_disco(tmp_path: Path):
    """Un dataset real en disco: JSON, imagenes y un directorio de cuarentena."""
    imagenes = tmp_path / "images"
    imagenes.mkdir()
    datos = coco()
    for image in datos.images:
        (imagenes / image.file_name).write_bytes(b"jpeg falso " + image.file_name.encode())
    coco_path = tmp_path / "annotations.json"
    coco_path.write_text(datos.model_dump_json(), encoding="utf-8")
    return datos, coco_path, imagenes, tmp_path / "quarantine"


# --------------------------------------------------------------------------
# El plan sale del reporte, no de una cuenta propia
# --------------------------------------------------------------------------
def test_el_plan_elimina_exactamente_los_offenders_del_reporte() -> None:
    datos = coco()

    plan = dedupe.build_plan(datos, reporte(datos, offenders=[2, 4]))

    assert plan.remove_ids == [2, 4]
    assert plan.remove_files == ["img2.jpg", "img4.jpg"]


def test_el_plan_cuenta_las_cajas_que_se_van_con_las_imagenes() -> None:
    datos = coco()

    plan = dedupe.build_plan(datos, reporte(datos, offenders=[2, 4]))

    assert plan.annotations_removed == 2
    assert plan.total_images == 4
    assert plan.kept == 2


def test_sin_offenders_el_plan_esta_vacio() -> None:
    datos = coco()

    plan = dedupe.build_plan(datos, reporte(datos, offenders=[]))

    assert plan.is_empty
    assert plan.kept == 4


# --------------------------------------------------------------------------
# Negativas — lo que impide destruir datos por accidente
# --------------------------------------------------------------------------
def test_un_reporte_de_otro_dataset_aborta_la_operacion() -> None:
    """Si alguien anadio imagenes tras correr la compuerta, los ids ya no valen."""
    datos = coco()
    viejo = reporte(datos, offenders=[2], fingerprint="b" * 64)

    with pytest.raises(dedupe.DedupeError, match="no corresponde al dataset"):
        dedupe.build_plan(datos, viejo)


def test_el_check_desactivado_aborta_la_operacion() -> None:
    datos = coco()

    with pytest.raises(dedupe.DedupeError, match="desactivado"):
        dedupe.build_plan(datos, reporte(datos, offenders=[], status="skipped"))


def test_sin_el_check_de_duplicados_aborta_la_operacion() -> None:
    datos = coco()
    sin_check = reporte(datos, offenders=[])
    sin_check = sin_check.model_copy(update={"checks": []})

    with pytest.raises(dedupe.DedupeError, match="no incluye el check"):
        dedupe.build_plan(datos, sin_check)


def test_un_offender_que_no_existe_aborta_la_operacion() -> None:
    """Huella correcta pero ids fantasma: no se construye un plan a ciegas."""
    datos = coco()
    fantasma = reporte(datos, offenders=[99])

    with pytest.raises(dedupe.DedupeError, match="ya no existen"):
        dedupe.build_plan(datos, fantasma)


# --------------------------------------------------------------------------
# La ejecucion
# --------------------------------------------------------------------------
def test_las_imagenes_se_mueven_a_cuarentena_no_se_borran(dataset_en_disco) -> None:
    datos, coco_path, imagenes, quarantine = dataset_en_disco
    plan = dedupe.build_plan(datos, reporte(datos, offenders=[2]))

    resultado = dedupe.apply(plan, datos, coco_path, imagenes, quarantine)

    assert not (imagenes / "img2.jpg").exists()
    assert (quarantine / "img2.jpg").is_file()
    # Los bytes son los mismos: se movio el archivo, no se escribio otro.
    assert (quarantine / "img2.jpg").read_bytes() == b"jpeg falso img2.jpg"
    assert resultado.quarantined == ["img2.jpg"]


def test_las_imagenes_que_sobreviven_no_se_tocan(dataset_en_disco) -> None:
    datos, coco_path, imagenes, quarantine = dataset_en_disco
    plan = dedupe.build_plan(datos, reporte(datos, offenders=[2]))

    dedupe.apply(plan, datos, coco_path, imagenes, quarantine)

    assert sorted(p.name for p in imagenes.iterdir()) == ["img1.jpg", "img3.jpg", "img4.jpg"]


def test_el_coco_reescrito_pierde_las_imagenes_y_sus_cajas(dataset_en_disco) -> None:
    datos, coco_path, imagenes, quarantine = dataset_en_disco
    plan = dedupe.build_plan(datos, reporte(datos, offenders=[2, 3]))

    dedupe.apply(plan, datos, coco_path, imagenes, quarantine)

    depurado = json.loads(coco_path.read_text(encoding="utf-8"))
    assert [i["id"] for i in depurado["images"]] == [1, 4]
    assert [a["image_id"] for a in depurado["annotations"]] == [1, 4]
    # Las categorias no dependen de que imagenes queden: el vocabulario del
    # dataset no cambia porque se caiga una copia.
    assert len(depurado["categories"]) == 2


def test_el_coco_reescrito_sigue_cumpliendo_el_contrato(dataset_en_disco) -> None:
    """Se reescribe desde el modelo validado, no editando el JSON en crudo."""
    datos, coco_path, imagenes, quarantine = dataset_en_disco
    plan = dedupe.build_plan(datos, reporte(datos, offenders=[2]))

    dedupe.apply(plan, datos, coco_path, imagenes, quarantine)

    revalidado = CocoDataset.model_validate_json(coco_path.read_text(encoding="utf-8"))
    assert len(revalidado.images) == 3


def test_una_imagen_ausente_en_disco_se_reporta_y_no_rompe(dataset_en_disco) -> None:
    datos, coco_path, imagenes, quarantine = dataset_en_disco
    (imagenes / "img2.jpg").unlink()
    plan = dedupe.build_plan(datos, reporte(datos, offenders=[2]))

    resultado = dedupe.apply(plan, datos, coco_path, imagenes, quarantine)

    assert resultado.missing_on_disk == ["img2.jpg"]
    assert resultado.quarantined == []
    # El COCO se limpia igual: la entrada sobraba aunque el archivo ya no este.
    assert resultado.remaining_images == 3


def test_un_plan_vacio_no_escribe_nada(dataset_en_disco) -> None:
    datos, coco_path, imagenes, quarantine = dataset_en_disco
    antes = coco_path.read_text(encoding="utf-8")
    plan = dedupe.build_plan(datos, reporte(datos, offenders=[]))

    resultado = dedupe.apply(plan, datos, coco_path, imagenes, quarantine)

    assert resultado.removed_images == 0
    assert coco_path.read_text(encoding="utf-8") == antes
    assert not quarantine.exists()


# --------------------------------------------------------------------------
# La API — lo que llama el boton
# --------------------------------------------------------------------------
@pytest.fixture
def api(tmp_path: Path, monkeypatch, env):
    """Monta la API sobre un dataset y un reporte temporales."""
    del env
    imagenes = tmp_path / "images"
    imagenes.mkdir()
    datos = coco()
    for image in datos.images:
        (imagenes / image.file_name).write_bytes(b"jpeg falso")
    coco_path = tmp_path / "annotations.json"
    coco_path.write_text(datos.model_dump_json(), encoding="utf-8")

    reports = tmp_path / "reports"
    reports.mkdir()
    nuevos = {
        name: artifacts.Artifact(art.name, reports / art.path.name, art.model, art.produced_by)
        for name, art in artifacts.ARTIFACTS.items()
    }
    monkeypatch.setattr(artifacts, "ARTIFACTS", nuevos)
    monkeypatch.setattr(duplicates, "ARTIFACTS", nuevos)
    monkeypatch.setattr(duplicates, "RAW_ANNOTATIONS", coco_path)
    monkeypatch.setattr(duplicates, "RAW_IMAGES", imagenes)
    monkeypatch.setattr(dedupe, "QUARANTINE", tmp_path / "quarantine")

    def escribir(report: QualityReport) -> None:
        nuevos["quality"].path.write_text(report.model_dump_json(), encoding="utf-8")

    client = TestClient(create_app(), raise_server_exceptions=False)
    return client, datos, coco_path, imagenes, tmp_path / "quarantine", escribir


def test_el_plan_por_http_es_de_solo_lectura(api) -> None:
    client, datos, _, imagenes, quarantine, escribir = api
    escribir(reporte(datos, offenders=[2, 4]))

    cuerpo = client.get("/api/duplicates/plan").json()

    assert cuerpo["remove_count"] == 2
    assert cuerpo["kept"] == 2
    assert cuerpo["sample"] == ["img2.jpg", "img4.jpg"]
    # Nada se movio: pedir el plan no es ejecutarlo.
    assert (imagenes / "img2.jpg").is_file()
    assert not quarantine.exists()


def test_el_post_elimina_y_avisa_de_que_los_reportes_caducaron(api) -> None:
    client, datos, _, imagenes, quarantine, escribir = api
    escribir(reporte(datos, offenders=[2]))

    cuerpo = client.post("/api/duplicates/remove").json()

    assert cuerpo["removed_images"] == 1
    assert cuerpo["remaining_images"] == 3
    # El dataset cambio: la pantalla tiene que decirlo, no disimularlo.
    assert cuerpo["stale_reports"] is True
    assert any("dq gate" in paso for paso in cuerpo["next_steps"])
    assert (quarantine / "img2.jpg").is_file()
    assert not (imagenes / "img2.jpg").exists()


def test_un_reporte_obsoleto_da_409_y_no_toca_nada(api) -> None:
    client, datos, _, imagenes, quarantine, escribir = api
    escribir(reporte(datos, offenders=[2], fingerprint="b" * 64))

    response = client.post("/api/duplicates/remove")

    assert response.status_code == 409
    assert "dq gate" in response.json()["detail"]
    assert (imagenes / "img2.jpg").is_file()
    assert not quarantine.exists()


def test_sin_quality_json_da_503_con_instrucciones(api) -> None:
    client, *_ = api

    response = client.get("/api/duplicates/plan")

    assert response.status_code == 503
    assert "dq gate" in response.json()["detail"]


def test_sin_dataset_en_disco_da_503_que_manda_a_dvc(api, monkeypatch, tmp_path) -> None:
    client, datos, _, _, _, escribir = api
    escribir(reporte(datos, offenders=[2]))
    monkeypatch.setattr(duplicates, "RAW_ANNOTATIONS", tmp_path / "no-existe.json")

    response = client.get("/api/duplicates/plan")

    assert response.status_code == 503
    assert "dvc pull" in response.json()["detail"]
