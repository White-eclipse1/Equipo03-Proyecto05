"""`GET /api/p3/runs` y `/runs/{id}`: corridas reales de MLflow para Experiments (contratos §4, F5).

El MLflow es un falso con la misma interfaz que `MlflowRest`.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from p3.train import runs_api, selection
from p3.train.selection import MlflowUnavailableError, RunSummary

HASH = "45600f297d13f51685e051e0cbc4962beb1f7c6a4e03247cbf61a345e6fa4305"


def _run(run_id: str, acc: float, loss: float, **kw) -> RunSummary:
    return RunSummary(
        run_id=run_id,
        experiment_id="3",
        status=kw.get("status", "FINISHED"),
        end_time=kw.get("end", 1_790_000_000_000),
        best_val_accuracy=acc,
        best_val_loss=loss,
        best_epoch=3,
        stopped_epoch=8,
        manifest_id=kw.get("manifest_id", "m-0.1.3-s42-1"),
        manifest_hash=HASH,
        artifact_uri=f"mlflow-artifacts:/3/{run_id}/artifacts",
        params={"optimizer": "sgd", "batch_size": "32"},
        tags={"code_commit": "250bedc" + "0" * 33, **kw.get("tags", {})},
        start_time=kw.get("start", 1_789_999_000_000),
    )


class FakeMlflow:
    def __init__(self) -> None:
        self.runs = [
            _run("a", 0.95, 0.20, start=1),
            _run("b", 0.99, 0.10, start=2, tags={"selected": "true"}),
            _run("c", 0.97, 0.05, start=3),
            _run("fallida", 0.0, 9.0, status="FAILED", start=4),
            _run("otro", 0.91, 0.3, manifest_id="m-otro", start=5),
        ]
        # Una corrida de otro experimento (p. ej. `p3-pruebas`): no es del barrido.
        self.ajena = RunSummary(**{**_run("ajena", 0.5, 1.0).__dict__, "experiment_id": "7"})

    def experiment_id(self, experiment: str) -> str:
        assert experiment == "p3-clasificador"
        return "3"

    def search_runs(self, experiment: str) -> list[RunSummary]:
        assert experiment == "p3-clasificador"
        return list(self.runs)

    def get_run(self, run_id: str) -> RunSummary:
        for run in [*self.runs, self.ajena]:
            if run.run_id == run_id:
                return run
        raise LookupError(run_id)

    def metric_history(self, run_id: str, key: str) -> list[tuple[int, float]]:
        base = {"train_loss": 1.0, "val_loss": 0.9, "train_accuracy": 0.5, "val_accuracy": 0.4}[key]
        return [(3, base + 0.3), (1, base + 0.1), (2, base + 0.2)]  # desordenado a proposito


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(runs_api.router)
    fake = FakeMlflow()
    app.dependency_overrides[runs_api.get_mlflow] = lambda: fake
    return TestClient(app)


def test_lista_las_corridas_con_los_campos_del_contrato(client: TestClient) -> None:
    body = client.get("/api/p3/runs").json()
    assert {r["run_id"] for r in body["runs"]} == {"a", "b", "c", "fallida", "otro"}
    b = next(r for r in body["runs"] if r["run_id"] == "b")
    assert b["status"] == "FINISHED"
    assert b["manifest_id"] == "m-0.1.3-s42-1"
    assert b["params"] == {"optimizer": "sgd", "batch_size": "32"}
    assert (b["best_epoch"], b["stopped_epoch"]) == (3, 8)
    assert (b["best_val_accuracy"], b["best_val_loss"]) == (0.99, 0.10)
    assert b["commit"].startswith("250bedc")
    assert b["experiment_id"] == "3"
    assert b["selected"] is True
    assert b["start_time"].endswith("Z") and b["end_time"].endswith("Z")


def test_filtra_por_manifiesto_y_estado(client: TestClient) -> None:
    body = client.get("/api/p3/runs?manifest_id=m-0.1.3-s42-1&status=FINISHED").json()
    assert {r["run_id"] for r in body["runs"]} == {"a", "b", "c"}


@pytest.mark.parametrize(
    ("order_by", "desc", "esperado"),
    [
        ("val_accuracy", "true", ["b", "c", "a"]),
        ("val_accuracy", "false", ["a", "c", "b"]),
        ("val_loss", "false", ["c", "b", "a"]),
        ("start_time", "true", ["c", "b", "a"]),
    ],
)
def test_ordena(client: TestClient, order_by: str, desc: str, esperado: list[str]) -> None:
    url = f"/api/p3/runs?status=FINISHED&manifest_id=m-0.1.3-s42-1&order_by={order_by}&desc={desc}"
    assert [r["run_id"] for r in client.get(url).json()["runs"]] == esperado


def test_un_orden_desconocido_da_422(client: TestClient) -> None:
    assert client.get("/api/p3/runs?order_by=test_accuracy").status_code == 422


def test_el_detalle_trae_la_historia_por_epoca_ordenada_y_los_artefactos(
    client: TestClient,
) -> None:
    body = client.get("/api/p3/runs/b").json()
    assert body["run_id"] == "b"
    assert [h["epoch"] for h in body["history"]] == [1, 2, 3]
    assert body["history"][0] == {
        "epoch": 1,
        "train_loss": 1.1,
        "train_accuracy": 0.6,
        "val_loss": 1.0,
        "val_accuracy": 0.5,
    }
    assert body["artifacts"]["checkpoint"] == "mlflow-artifacts:/3/b/artifacts/checkpoint/model.pt"
    assert body["artifacts"]["curves"] == "mlflow-artifacts:/3/b/artifacts/curves.png"


def test_un_run_inexistente_da_404(client: TestClient) -> None:
    assert client.get("/api/p3/runs/no-existe").status_code == 404


def test_no_importa_torch_ni_mlflow() -> None:
    from pathlib import Path

    texto = Path(runs_api.__file__).read_text(encoding="utf-8")
    assert "import torch" not in texto and "import mlflow" not in texto


def test_un_id_invalido_da_422(client: TestClient) -> None:
    assert client.get("/api/p3/runs/a&b").status_code == 422
    assert client.get("/api/p3/runs/" + "x" * 65).status_code == 422


def test_un_run_de_otro_experimento_da_404(client: TestClient) -> None:
    assert client.get("/api/p3/runs/ajena").status_code == 404


def test_nunca_muestra_metricas_ni_tags_de_test() -> None:
    # r10 tiene en MLflow las metricas y tags `test_*` de la evaluacion final (F6).
    rest = {
        "info": {
            "run_id": "r10",
            "experiment_id": "3",
            "status": "FINISHED",
            "start_time": 1,
            "end_time": 2,
            "artifact_uri": "mlflow-artifacts:/3/r10/artifacts",
        },
        "data": {
            "metrics": [
                {"key": "best_val_accuracy", "value": 0.99},
                {"key": "best_val_loss", "value": 0.1},
                {"key": "test_accuracy", "value": 0.98},
                {"key": "test_f1_macro", "value": 0.97},
            ],
            "params": [{"key": "optimizer", "value": "sgd"}],
            "tags": [
                {"key": "manifest_id", "value": "m-0.1.3-s42-1"},
                {"key": "selected", "value": "true"},
                {"key": "test_evaluated_at", "value": "2026-09-27T00:00:00Z"},
            ],
        },
    }
    fake = FakeMlflow()
    fake.runs = [RunSummary.from_rest(rest)]
    app = FastAPI()
    app.include_router(runs_api.router)
    app.dependency_overrides[runs_api.get_mlflow] = lambda: fake
    client = TestClient(app)
    for url in ("/api/p3/runs", "/api/p3/runs/r10"):
        answer = client.get(url)
        assert answer.status_code == 200
        assert "test_" not in answer.text, url


def test_si_mlflow_falla_responde_503_y_no_404(client: TestClient) -> None:
    def falla(run_id: str) -> RunSummary:
        raise MlflowUnavailableError("MLflow respondio 500")

    fake = FakeMlflow()
    fake.get_run = falla  # type: ignore[method-assign]
    app = FastAPI()
    app.include_router(runs_api.router)
    app.dependency_overrides[runs_api.get_mlflow] = lambda: fake
    assert TestClient(app).get("/api/p3/runs/b").status_code == 503


@pytest.mark.parametrize(
    ("code", "esperado"), [(404, LookupError), (400, LookupError), (500, MlflowUnavailableError)]
)
def test_get_run_solo_traduce_400_y_404_a_inexistente(
    monkeypatch: pytest.MonkeyPatch, code: int, esperado: type[Exception]
) -> None:
    import urllib.error

    def call(*_args, **_kw):
        raise urllib.error.HTTPError("http://mlflow", code, "error", {}, None)  # type: ignore[arg-type]

    rest = selection.MlflowRest("http://mlflow:5000")
    monkeypatch.setattr(rest, "_call", call)
    with pytest.raises(esperado):
        rest.get_run("abc")


# --- MLflow sin el experimento (clon limpio sin `dvc pull` del snapshot) ---------------------


def _rest_sin_experimento(monkeypatch: pytest.MonkeyPatch) -> selection.MlflowRest:
    import urllib.error

    def call(method: str, path: str, *_args, **_kw):
        if "experiments/get-by-name" in path:
            # Asi responde MLflow: 404 RESOURCE_DOES_NOT_EXIST.
            raise urllib.error.HTTPError("http://mlflow", 404, "not found", {}, None)  # type: ignore[arg-type]
        raise AssertionError(f"no deberia llamar {path}")

    rest = selection.MlflowRest("http://mlflow:5000")
    monkeypatch.setattr(rest, "_call", call)
    return rest


def test_experimento_inexistente_es_una_lista_vacia(monkeypatch: pytest.MonkeyPatch) -> None:
    rest = _rest_sin_experimento(monkeypatch)
    assert rest.experiment_id("p3-clasificador") is None
    assert rest.search_runs("p3-clasificador") == []


def test_experimento_inexistente_otros_errores_siguen_subiendo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import urllib.error

    def call(*_args, **_kw):
        raise urllib.error.HTTPError("http://mlflow", 500, "boom", {}, None)  # type: ignore[arg-type]

    rest = selection.MlflowRest("http://mlflow:5000")
    monkeypatch.setattr(rest, "_call", call)
    with pytest.raises(urllib.error.HTTPError):
        rest.search_runs("p3-clasificador")


def _app_con(rest: selection.MlflowRest) -> TestClient:
    from p3.eval import api as evaluation_api

    app = FastAPI()
    app.include_router(runs_api.router)
    app.include_router(selection.router)
    app.include_router(evaluation_api.router)
    app.dependency_overrides[runs_api.get_mlflow] = lambda: rest
    return TestClient(app, raise_server_exceptions=False)


def test_sin_experimento_runs_es_vacio_y_no_500(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _app_con(_rest_sin_experimento(monkeypatch)).get("/api/p3/runs")
    assert response.status_code == 200
    assert response.json() == {"runs": []}


def test_sin_experimento_un_run_es_404(monkeypatch: pytest.MonkeyPatch) -> None:
    rest = _rest_sin_experimento(monkeypatch)
    ajeno = RunSummary(**{**_run("x", 0.5, 1.0).__dict__, "experiment_id": "7"})
    monkeypatch.setattr(rest, "get_run", lambda run_id: ajeno)
    assert _app_con(rest).get("/api/p3/runs/x").status_code == 404


def test_sin_experimento_seleccion_404_y_evaluacion_409(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _app_con(_rest_sin_experimento(monkeypatch))
    assert client.get("/api/p3/selection").status_code == 404
    evaluation = client.get("/api/p3/evaluation")
    assert evaluation.status_code == 409
    assert "no está cerrada" in evaluation.json()["detail"]


def test_si_mlflow_no_responde_la_lista_da_503() -> None:
    import urllib.error

    fake = FakeMlflow()

    def caido(experiment: str) -> list[RunSummary]:
        raise urllib.error.URLError("Connection refused")

    fake.search_runs = caido  # type: ignore[method-assign]
    app = FastAPI()
    app.include_router(runs_api.router)
    app.dependency_overrides[runs_api.get_mlflow] = lambda: fake
    response = TestClient(app, raise_server_exceptions=False).get("/api/p3/runs")
    assert response.status_code == 503
    assert "P3_MLFLOW_URL" in response.json()["detail"]
