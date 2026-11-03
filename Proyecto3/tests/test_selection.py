"""Seleccion del candidato por validacion (F5 T14, criterio 3.3; decisiones.md §4).

Regla predeclarada: mayor `best_val_accuracy`; desempate menor `best_val_loss`;
luego la corrida que termino primero. Solo cuentan corridas FINISHED sobre el
manifiesto congelado. El test no interviene.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from p3.train import selection

HASH = "45600f297d13f51685e051e0cbc4962beb1f7c6a4e03247cbf61a345e6fa4305"


def _run(run_id: str, acc: float, loss: float, end: int, **kw) -> selection.RunSummary:
    return selection.RunSummary(
        run_id=run_id,
        experiment_id="3",
        status=kw.get("status", "FINISHED"),
        end_time=end,
        best_val_accuracy=acc,
        best_val_loss=loss,
        best_epoch=kw.get("best_epoch", 5),
        stopped_epoch=kw.get("stopped_epoch", 9),
        manifest_id="m-0.1.3-s42-1",
        manifest_hash=kw.get("manifest_hash", HASH),
        artifact_uri=f"mlflow-artifacts:/3/{run_id}/artifacts",
        params={"optimizer": "adamw"},
        tags=kw.get("tags", {}),
    )


def _diez(**extra) -> list[selection.RunSummary]:
    return [_run(f"r{i}", 0.90 + i / 1000, 0.3, 1000 + i) for i in range(10)] + list(extra.values())


def test_gana_la_mayor_val_accuracy() -> None:
    runs = _diez(mejor=_run("mejor", 0.99, 0.5, 5000))
    assert selection.select(runs, manifest_hash=HASH).run_id == "mejor"


def test_empate_en_accuracy_gana_la_menor_val_loss() -> None:
    runs = _diez(a=_run("a", 0.99, 0.20, 5000), b=_run("b", 0.99, 0.10, 6000))
    assert selection.select(runs, manifest_hash=HASH).run_id == "b"


def test_empate_total_gana_la_que_termino_primero() -> None:
    runs = _diez(a=_run("a", 0.99, 0.10, 7000), b=_run("b", 0.99, 0.10, 6000))
    assert selection.select(runs, manifest_hash=HASH).run_id == "b"


def test_solo_cuentan_finished_del_manifiesto_congelado() -> None:
    runs = _diez(
        fallida=_run("fallida", 1.0, 0.0, 1, status="FAILED"),
        otro_manifiesto=_run("otro", 1.0, 0.0, 1, manifest_hash="0" * 64),
    )
    assert selection.select(runs, manifest_hash=HASH).run_id == "r9"
    assert {r.run_id for r in selection.valid_runs(runs, manifest_hash=HASH)} == {
        f"r{i}" for i in range(10)
    }


def test_con_menos_de_diez_corridas_validas_no_se_elige() -> None:
    runs = [*_diez()[:9], _run("fallida", 1.0, 0.0, 1, status="FAILED")]
    with pytest.raises(selection.NotEnoughRunsError, match="9"):
        selection.select(runs, manifest_hash=HASH)


def test_el_registro_sigue_el_contrato() -> None:
    ganador = _run("gana", 0.99, 0.1, 5000, best_epoch=4)
    record = selection.selection_record(
        ganador,
        candidates=10,
        checkpoint_sha256="c" * 64,
        crops_sha256="d" * 64,
        selected_at="2026-09-27T10:00:00Z",
    )
    assert record == {
        "schema_version": 1,
        "selected_at": "2026-09-27T10:00:00Z",
        "manifest_id": "m-0.1.3-s42-1",
        "manifest_hash": HASH,
        "rule": selection.RULE,
        "candidates": 10,
        "run_id": "gana",
        "checkpoint_uri": "mlflow-artifacts:/3/gana/artifacts/checkpoint/model.pt",
        "checkpoint_sha256": "c" * 64,
        "crops_jsonl_sha256": "d" * 64,
        "best_epoch": 4,
        "val_accuracy": 0.99,
        "val_loss": 0.1,
    }


def test_se_lee_un_run_de_la_api_rest_de_mlflow() -> None:
    rest = {
        "info": {
            "run_id": "abc",
            "experiment_id": "3",
            "status": "FINISHED",
            "end_time": 123,
            "artifact_uri": "mlflow-artifacts:/3/abc/artifacts",
        },
        "data": {
            "metrics": [
                {"key": "best_val_accuracy", "value": 0.97},
                {"key": "best_val_loss", "value": 0.2},
                {"key": "best_epoch", "value": 6.0},
                {"key": "stopped_epoch", "value": 11.0},
            ],
            "params": [{"key": "optimizer", "value": "sgd"}],
            "tags": [
                {"key": "manifest_id", "value": "m-0.1.3-s42-1"},
                {"key": "manifest_hash", "value": HASH},
            ],
        },
    }
    run = selection.RunSummary.from_rest(rest)
    assert (run.run_id, run.best_val_accuracy, run.best_epoch) == ("abc", 0.97, 6)
    assert run.params == {"optimizer": "sgd"}


class FakeMlflow:
    def __init__(self, runs: list[selection.RunSummary]) -> None:
        self.runs = runs
        self.tags: dict[str, dict[str, str]] = {}

    def search_runs(self, experiment: str) -> list[selection.RunSummary]:
        assert experiment == "p3-clasificador"
        return [
            selection.RunSummary(
                **{**r.__dict__, "tags": {**r.tags, **self.tags.get(r.run_id, {})}}
            )
            for r in self.runs
        ]

    def set_tag(self, run_id: str, key: str, value: str) -> None:
        self.tags.setdefault(run_id, {})[key] = value

    def artifact_bytes(self, run: selection.RunSummary, path: str) -> bytes:
        assert path == "checkpoint/model.pt"
        return f"pesos de {run.run_id}".encode()


@pytest.fixture
def client_y_mlflow() -> tuple[TestClient, FakeMlflow]:
    fake = FakeMlflow(
        _diez(mejor=_run("mejor", 0.99, 0.1, 5000, tags={"crops_jsonl_sha256": "d" * 64}))
    )
    app = FastAPI()
    app.include_router(selection.router)
    app.dependency_overrides[selection.get_mlflow] = lambda: fake
    return TestClient(app), fake


def test_post_selection_marca_el_run_y_devuelve_el_registro(client_y_mlflow) -> None:
    client, fake = client_y_mlflow
    response = client.post("/api/p3/selection", json={"manifest_id": "m-0.1.3-s42-1"})
    assert response.status_code == 201
    body = response.json()
    assert body["run_id"] == "mejor"
    assert body["candidates"] == 11
    import hashlib

    assert body["checkpoint_sha256"] == hashlib.sha256(b"pesos de mejor").hexdigest()
    assert fake.tags["mejor"]["selected"] == "true"
    assert client.get("/api/p3/selection").json()["run_id"] == "mejor"


def test_una_segunda_seleccion_da_409(client_y_mlflow) -> None:
    client, _ = client_y_mlflow
    assert (
        client.post("/api/p3/selection", json={"manifest_id": "m-0.1.3-s42-1"}).status_code == 201
    )
    segunda = client.post("/api/p3/selection", json={"manifest_id": "m-0.1.3-s42-1"})
    assert segunda.status_code == 409


def test_sin_seleccion_get_da_404(client_y_mlflow) -> None:
    client, _ = client_y_mlflow
    assert client.get("/api/p3/selection").status_code == 404


def test_manifiesto_no_congelado_da_409(client_y_mlflow) -> None:
    client, _ = client_y_mlflow
    response = client.post("/api/p3/selection", json={"manifest_id": "m-0.1.3-s7-1"})
    assert response.status_code == 409


def test_no_importa_torch_ni_mlflow() -> None:
    from pathlib import Path

    texto = Path(selection.__file__).read_text(encoding="utf-8")
    assert "import torch" not in texto and "import mlflow" not in texto


# --- MLflow caido: 503 con que revisar, nunca 500 -------------------------------------------


@pytest.mark.parametrize("metodo", ["get", "post"])
def test_si_mlflow_no_responde_selection_da_503(metodo: str) -> None:
    import urllib.error

    class Caido:
        def search_runs(self, experiment: str):
            raise urllib.error.URLError("Connection refused")

    app = FastAPI()
    app.include_router(selection.router)
    app.dependency_overrides[selection.get_mlflow] = lambda: Caido()
    client = TestClient(app, raise_server_exceptions=False)
    if metodo == "get":
        response = client.get("/api/p3/selection")
    else:
        response = client.post("/api/p3/selection", json={"manifest_id": "m-0.1.3-s42-1"})
    assert response.status_code == 503
    assert "P3_MLFLOW_URL" in response.json()["detail"]
