"""El endpoint solo encola y devuelve job_id; el estado se consulta aparte (F1 T02)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from p3.worker import api, jobs


@pytest.fixture
def client(session_factory: sessionmaker[Session]) -> TestClient:
    app = FastAPI()
    app.include_router(api.router)

    def override() -> Iterator[Session]:
        with session_factory.begin() as session:
            yield session

    app.dependency_overrides[api.get_session] = override
    return TestClient(app)


def test_post_encola_sin_ejecutar(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    response = client.post("/api/p3/training/jobs", json={"kind": "dummy", "config": {}})

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    with session_factory() as session:
        stored = jobs.get_job(session, body["job_id"])
        assert stored is not None
        assert stored.status == jobs.JobStatus.QUEUED


def test_get_devuelve_estado_progreso_logs_y_error(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    job_id = client.post("/api/p3/training/jobs", json={"kind": "dummy"}).json()["job_id"]
    with session_factory.begin() as session:
        jobs.claim_next(session, worker_id="w1")
    with session_factory.begin() as session:
        jobs.report_progress(session, job_id, 0.5, "mitad")

    response = client.get(f"/api/p3/training/jobs/{job_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == job_id
    assert body["status"] == "running"
    assert body["progress"] == 0.5
    assert any("mitad" in linea for linea in body["logs"])
    assert body["error"] is None


def test_get_de_un_id_inexistente_es_404(client: TestClient) -> None:
    response = client.get("/api/p3/training/jobs/no-existe")

    assert response.status_code == 404


def test_kind_invalido_se_rechaza_nombrando_el_campo(client: TestClient) -> None:
    response = client.post("/api/p3/training/jobs", json={"kind": "minar-bitcoin"})

    assert response.status_code == 422
    assert "kind" in str(response.json()["detail"])


def test_campos_extra_se_rechazan(client: TestClient) -> None:
    response = client.post("/api/p3/training/jobs", json={"kind": "dummy", "prioridad": 9})

    assert response.status_code == 422


CONFIG_VALIDA = {
    "optimizer": "adamw",
    "batch_size": 32,
    "max_epochs": 30,
    "learning_rate": 0.0003,
    "image_size": 224,
    "hidden_layers": [256],
    "dropout": 0.3,
}


def _cuantos_trabajos(session_factory: sessionmaker[Session]) -> int:
    with session_factory() as session:
        return session.query(jobs.TrainingJob).count()


@pytest.mark.parametrize(
    ("campo", "valor"),
    [("batch_size", 0), ("learning_rate", -1), ("optimizer", "rmsprop"), ("dropout", 1.0)],
)
def test_train_con_config_invalida_da_422_nombrando_el_campo_y_no_crea_trabajo(
    client: TestClient, session_factory: sessionmaker[Session], campo: str, valor: object
) -> None:
    body = {
        "kind": "train",
        "manifest_id": "m-0.1.3-s42-1",
        "config": {**CONFIG_VALIDA, campo: valor},
    }

    response = client.post("/api/p3/training/jobs", json=body)

    assert response.status_code == 422
    assert any(campo in error["loc"] for error in response.json()["detail"])
    assert _cuantos_trabajos(session_factory) == 0


def test_train_valido_se_encola_con_la_config_efectiva(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    body = {"kind": "train", "manifest_id": "m-0.1.3-s42-1", "config": CONFIG_VALIDA}

    response = client.post("/api/p3/training/jobs", json=body)

    assert response.status_code == 202
    with session_factory() as session:
        stored = jobs.get_job(session, response.json()["job_id"])
        assert stored is not None
        assert stored.kind == "train"
        assert stored.config["manifest_id"] == "m-0.1.3-s42-1"
        assert stored.config["training"] == {
            **CONFIG_VALIDA,
            "seed": 42,
            "patience": 5,
            "min_delta": 0.001,
            "monitor_metric": "val_accuracy",
        }


def test_train_con_manifiesto_no_congelado_da_409_y_no_crea_trabajo(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    body = {"kind": "train", "manifest_id": "m-0.1.3-s99-1", "config": CONFIG_VALIDA}

    response = client.post("/api/p3/training/jobs", json=body)

    assert response.status_code == 409
    assert "congelado" in response.json()["detail"]
    assert _cuantos_trabajos(session_factory) == 0


def test_get_incluye_el_run_de_mlflow(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    job_id = client.post("/api/p3/training/jobs", json={"kind": "dummy"}).json()["job_id"]
    assert client.get(f"/api/p3/training/jobs/{job_id}").json()["mlflow_run_id"] is None
    with session_factory.begin() as session:
        jobs.set_mlflow_run_id(session, job_id, "run42")
    assert client.get(f"/api/p3/training/jobs/{job_id}").json()["mlflow_run_id"] == "run42"


def test_train_puede_ir_al_experimento_de_pruebas_y_nada_mas(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    base = {"kind": "train", "manifest_id": "m-0.1.3-s42-1", "config": CONFIG_VALIDA}

    ok = client.post("/api/p3/training/jobs", json={**base, "experiment": "p3-pruebas"})
    assert ok.status_code == 202
    with session_factory() as session:
        stored = jobs.get_job(session, ok.json()["job_id"])
        assert stored is not None and stored.config["experiment"] == "p3-pruebas"

    otro = client.post("/api/p3/training/jobs", json={**base, "experiment": "cualquiera"})
    assert otro.status_code == 422


def test_otro_manifiesto_congelado_no_entra_al_experimento_del_barrido(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    # Las 12 corridas de `p3-clasificador` son del manifiesto del barrido; un trabajo
    # con otro manifiesto ensuciaria /runs y la seleccion (F12, 1.1).
    base = {"kind": "train", "manifest_id": "m-0.1.3-s7-1", "config": CONFIG_VALIDA}

    response = client.post("/api/p3/training/jobs", json={**base, "experiment": "p3-clasificador"})
    assert response.status_code == 409
    assert "p3-pruebas" in response.json()["detail"]
    assert _cuantos_trabajos(session_factory) == 0

    ok = client.post("/api/p3/training/jobs", json={**base, "experiment": "p3-pruebas"})
    assert ok.status_code == 202


def test_sin_experimento_otro_manifiesto_tambien_se_rechaza(client: TestClient) -> None:
    # El experimento por defecto es `p3-clasificador`.
    body = {"kind": "train", "manifest_id": "m-0.1.3-s7-1", "config": CONFIG_VALIDA}
    assert client.post("/api/p3/training/jobs", json=body).status_code == 409
