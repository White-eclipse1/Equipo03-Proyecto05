"""Procedencia de la evaluacion y miniaturas de los ejemplos (F12; criterios 6.3 y 4.4).

`GET /api/p3/evaluation` dice de donde sale cada cifra: release, manifiesto y su
hash, checkpoint y cuando se cerro la seleccion. `GET /api/p3/evaluation/crops/
{crop_id}` sirve el PNG de un recorte del **test del manifiesto elegido**, para
que la galeria de Evaluation muestre la imagen de cada acierto y error.

Antes de cerrar la seleccion responde 409, como el resto de la evaluacion; un
recorte que no es del test de ese manifiesto da 404; si faltan el manifiesto o
los recortes en disco, 503 con el comando que falta.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from p3.eval import api
from p3.train.selection import RunSummary

MANIFEST = "m-0.1.3-s42-1"
SELECTION = {
    "schema_version": 1,
    "selected_at": "2026-09-27T03:39:45Z",
    "manifest_id": MANIFEST,
    "manifest_hash": "45600f29" + "0" * 56,
    "run_id": "r10",
    "checkpoint_sha256": "e4acca42" + "0" * 56,
}
METRICS = {
    "test_size": 2,
    "accuracy": 0.5,
    "passes_threshold": False,
    "threshold": 0.85,
    "f1_macro": 0.5,
    "per_class": [],
    "confusion_matrix": {"labels": ["cat", "dog"], "rows_true_cols_pred": [[1, 0], [1, 0]]},
    "majority_baseline": {"class": "cat", "accuracy": 0.5},
    "most_confused": {"true": "dog", "predicted": "cat", "count": 1},
    "manifest_id": MANIFEST,
    "manifest_hash": SELECTION["manifest_hash"],
    "evaluated_at": "2026-09-28T02:25:07Z",
}
PNG = b"\x89PNG\r\n\x1a\n" + b"recorte"
ROWS = [
    {"crop_id": "0.1.3:a1", "split": "test", "category_name": "cat"},
    {"crop_id": "0.1.3:a2", "split": "train", "category_name": "dog"},
]
MANIFEST_BYTES = "".join(json.dumps(r) + "\n" for r in ROWS).encode("utf-8")
# El manifiesto de la prueba es el "congelado": su SHA-256 es el registrado.
FROZEN = {MANIFEST: hashlib.sha256(MANIFEST_BYTES).hexdigest()}


def run(run_id: str, *, selected: bool) -> RunSummary:
    tags = {"release_id": "0.1.3", "manifest_id": MANIFEST}
    if selected:
        tags |= {"selected": "true", "selection": json.dumps(SELECTION)}
    return RunSummary(
        run_id=run_id,
        experiment_id="3",
        status="FINISHED",
        end_time=1,
        best_val_accuracy=0.99,
        best_val_loss=0.02,
        best_epoch=6,
        stopped_epoch=11,
        manifest_id=MANIFEST,
        manifest_hash=SELECTION["manifest_hash"],
        artifact_uri=f"mlflow-artifacts:/3/{run_id}/artifacts",
        tags=tags,
    )


class FakeMlflow:
    def __init__(self, runs: list[RunSummary]) -> None:
        self.runs = runs

    def search_runs(self, experiment: str) -> list[RunSummary]:
        return self.runs

    def artifact_bytes(self, run: RunSummary, path: str) -> bytes:
        if run.run_id == "r10" and path == "evaluation/metrics.json":
            return json.dumps(METRICS).encode()
        raise FileNotFoundError(path)


@pytest.fixture
def data(tmp_path: Path) -> tuple[Path, Path]:
    manifests, crops = tmp_path / "manifests", tmp_path / "crops"
    rows = ROWS
    (manifests / MANIFEST).mkdir(parents=True)
    (manifests / MANIFEST / "manifest.jsonl").write_bytes(MANIFEST_BYTES)
    meta = {"manifest_id": MANIFEST, "manifest_hash": FROZEN[MANIFEST]}
    (manifests / MANIFEST / "manifest.meta.json").write_text(json.dumps(meta), encoding="utf-8")
    release = crops / "0.1.3"
    for row, folder in zip(rows, ("cat", "dog"), strict=True):
        (release / folder).mkdir(parents=True)
        name = row["crop_id"].replace(":", "_") + ".png"
        (release / folder / name).write_bytes(PNG + row["crop_id"].encode())
    index = [
        {"crop_id": "0.1.3:a1", "crop_path": "cat/0.1.3_a1.png"},
        {"crop_id": "0.1.3:a2", "crop_path": "dog/0.1.3_a2.png"},
        # Esta en el indice pero no en el manifiesto.
        {"crop_id": "0.1.3:a9", "crop_path": "cat/0.1.3_a9.png"},
    ]
    (release / "crops.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in index), encoding="utf-8"
    )
    return manifests, crops


def client_with(fake: FakeMlflow, dirs: tuple[Path, Path]) -> TestClient:
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_mlflow] = lambda: fake
    app.dependency_overrides[api.get_data_dirs] = lambda: api.DataDirs(*dirs)
    app.dependency_overrides[api.get_frozen] = lambda: FROZEN
    return TestClient(app, raise_server_exceptions=False)


def selected() -> FakeMlflow:
    return FakeMlflow([run("r08", selected=False), run("r10", selected=True)])


# --- Procedencia en GET /api/p3/evaluation --------------------------------------------------


def test_la_evaluacion_dice_release_manifiesto_checkpoint_y_seleccion(data) -> None:
    body = client_with(selected(), data).get("/api/p3/evaluation").json()
    assert body["run_id"] == "r10"
    assert body["manifest_id"] == MANIFEST
    assert body["release_id"] == "0.1.3"
    assert body["manifest_hash"] == SELECTION["manifest_hash"]
    assert body["checkpoint_sha256"] == SELECTION["checkpoint_sha256"]
    assert body["selected_at"] == SELECTION["selected_at"]


# --- GET /api/p3/evaluation/crops/{crop_id} -------------------------------------------------


def test_sirve_el_png_de_un_recorte_del_test(data) -> None:
    response = client_with(selected(), data).get("/api/p3/evaluation/crops/0.1.3:a1")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == PNG + b"0.1.3:a1"


def test_antes_de_cerrar_la_seleccion_responde_409(data) -> None:
    fake = FakeMlflow([run("r10", selected=False)])
    response = client_with(fake, data).get("/api/p3/evaluation/crops/0.1.3:a1")
    assert response.status_code == 409
    assert response.json() == {"detail": "La selección del modelo no está cerrada"}


@pytest.mark.parametrize("crop_id", ["0.1.3:a2", "0.1.3:a9", "0.1.3:a777"])
def test_un_recorte_que_no_es_del_test_responde_404(data, crop_id: str) -> None:
    # a2 es de train, a9 esta en el indice pero no en el manifiesto, a777 no existe.
    response = client_with(selected(), data).get(f"/api/p3/evaluation/crops/{crop_id}")
    assert response.status_code == 404
    assert crop_id in response.json()["detail"]


@pytest.mark.parametrize("crop_id", ["..%2F..%2Fsecreto", "0.1.3:a1.png", "a1", "0.1.3:a1%2F.."])
def test_un_id_que_no_es_de_recorte_no_sale_de_la_carpeta(data, crop_id: str) -> None:
    response = client_with(selected(), data).get(f"/api/p3/evaluation/crops/{crop_id}")
    assert response.status_code in (404, 422)


def test_sin_el_manifiesto_descargado_responde_503_con_dvc_pull(data) -> None:
    manifests, _ = data
    (manifests / MANIFEST / "manifest.jsonl").unlink()
    response = client_with(selected(), data).get("/api/p3/evaluation/crops/0.1.3:a1")
    assert response.status_code == 503
    assert "dvc pull" in response.json()["detail"]


def test_sin_los_recortes_responde_503_con_generate_crops(data) -> None:
    _, crops = data
    (crops / "0.1.3" / "crops.jsonl").unlink()
    response = client_with(selected(), data).get("/api/p3/evaluation/crops/0.1.3:a1")
    assert response.status_code == 503
    assert "generate_crops.py" in response.json()["detail"]


def test_si_falta_el_png_del_recorte_responde_503(data) -> None:
    _, crops = data
    (crops / "0.1.3" / "cat" / "0.1.3_a1.png").unlink()
    response = client_with(selected(), data).get("/api/p3/evaluation/crops/0.1.3:a1")
    assert response.status_code == 503
    assert "generate_crops.py" in response.json()["detail"]


def test_usa_el_manifiesto_de_la_corrida_elegida(data) -> None:
    # Otro manifiesto donde a2 SI es de test: no cambia nada, la corrida elegida usa MANIFEST.
    manifests, _ = data
    other = manifests / "m-0.1.3-s7-1"
    other.mkdir()
    (other / "manifest.jsonl").write_text(
        json.dumps({"crop_id": "0.1.3:a2", "split": "test"}) + "\n", encoding="utf-8"
    )
    response = client_with(selected(), data).get("/api/p3/evaluation/crops/0.1.3:a2")
    assert response.status_code == 404


def test_un_manifiesto_editado_no_decide_que_es_test(data) -> None:
    # Revision de Edith (#29): si alguien pasa a2 (de train) a test, el manifiesto ya
    # no es el congelado y no se sirve nada: no se exponen recortes de train como test.
    manifests, _ = data
    edited = [dict(r, split="test") for r in ROWS]
    (manifests / MANIFEST / "manifest.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in edited), encoding="utf-8"
    )
    response = client_with(selected(), data).get("/api/p3/evaluation/crops/0.1.3:a2")
    assert response.status_code == 409
    assert "SHA-256" in response.json()["detail"]
