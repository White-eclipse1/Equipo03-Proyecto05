"""`GET /api/p3/evaluation` para la pagina Evaluation (F6, contratos §4; criterio 6.3).

Lee de MLflow (la corrida `selected=true` y sus artefactos `evaluation/`), no de
archivos locales, para que portal, API y MLflow digan lo mismo (4.2). Mientras
no haya seleccion responde 409: el test no se revela antes de cerrarla.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from p3.eval import api
from p3.train.selection import RunSummary

METRICS = {
    "test_size": 145,
    "accuracy": 142 / 145,
    "passes_threshold": True,
    "threshold": 0.85,
    "f1_macro": 0.9743519475145314,
    "per_class": [
        {"class": "cat", "precision": 1.0, "recall": 0.9375, "f1": 0.9677, "support": 32},
        {"class": "dog", "precision": 0.9268, "recall": 1.0, "f1": 0.962, "support": 38},
        {"class": "person", "precision": 1.0, "recall": 0.9867, "f1": 0.9933, "support": 75},
    ],
    "confusion_matrix": {
        "labels": ["cat", "dog", "person"],
        "rows_true_cols_pred": [[30, 2, 0], [0, 38, 0], [0, 1, 74]],
    },
    "majority_baseline": {"class": "person", "accuracy": 75 / 145},
    "most_confused": {"true": "cat", "predicted": "dog", "count": 2},
    "run_id": "r10",
    "manifest_id": "m-0.1.3-s42-1",
    "manifest_hash": "45600f29",
    "evaluated_at": "2026-09-28T02:25:07Z",
    "code_commit": "a7ec1dc",
}
CSV = (
    "crop_id,clase_real,clase_predicha,prob_cat,prob_dog,prob_person\n"
    "0.1.3:a1,cat,cat,0.9,0.05,0.05\n"
)
EXAMPLES = {"correct": [{"crop_id": "0.1.3:a1"}], "errors": []}


def run(run_id: str, *, selected: bool) -> RunSummary:
    return RunSummary(
        run_id=run_id,
        experiment_id="3",
        status="FINISHED",
        end_time=1,
        best_val_accuracy=0.99,
        best_val_loss=0.02,
        best_epoch=6,
        stopped_epoch=11,
        manifest_id="m-0.1.3-s42-1",
        manifest_hash="45600f29",
        artifact_uri=f"mlflow-artifacts:/3/{run_id}/artifacts",
        tags={"selected": "true"} if selected else {},
    )


class FakeMlflow:
    def __init__(self, runs: list[RunSummary], artifacts: dict[tuple[str, str], bytes]) -> None:
        self.runs = runs
        self.artifacts = artifacts

    def search_runs(self, experiment: str) -> list[RunSummary]:
        return self.runs

    def set_tag(self, run_id: str, key: str, value: str) -> None:  # pragma: no cover
        raise AssertionError("la API de evaluacion no escribe en MLflow")

    def artifact_bytes(self, run: RunSummary, path: str) -> bytes:
        try:
            return self.artifacts[(run.run_id, path)]
        except KeyError:
            raise FileNotFoundError(path) from None


def client_with(fake: FakeMlflow) -> TestClient:
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_mlflow] = lambda: fake
    return TestClient(app)


def evaluated() -> FakeMlflow:
    return FakeMlflow(
        [run("r08", selected=False), run("r10", selected=True)],
        {
            ("r10", "evaluation/metrics.json"): json.dumps(METRICS).encode(),
            ("r10", "evaluation/predictions_test.csv"): CSV.encode(),
            ("r10", "evaluation/errors.json"): json.dumps(EXAMPLES).encode(),
            # Un artefacto de otra corrida nunca debe leerse.
            ("r08", "evaluation/metrics.json"): json.dumps(METRICS | {"accuracy": 0.1}).encode(),
        },
    )


def test_sin_seleccion_cerrada_responde_409_sin_revelar_el_test() -> None:
    fake = FakeMlflow([run("r08", selected=False), run("r10", selected=False)], {})
    for path in (
        "/api/p3/evaluation",
        "/api/p3/evaluation/predictions",
        "/api/p3/evaluation/examples",
    ):
        response = client_with(fake).get(path)
        assert response.status_code == 409, path
        assert response.json() == {"detail": "La selección del modelo no está cerrada"}


def test_con_seleccion_pero_sin_evaluacion_responde_404() -> None:
    fake = FakeMlflow([run("r10", selected=True)], {})
    response = client_with(fake).get("/api/p3/evaluation")
    assert response.status_code == 404
    assert "evaluación final" in response.json()["detail"]


def test_evaluacion_con_la_forma_del_contrato() -> None:
    body = client_with(evaluated()).get("/api/p3/evaluation").json()
    assert body["run_id"] == "r10"
    assert body["manifest_id"] == "m-0.1.3-s42-1"
    assert body["test_size"] == 145
    assert body["accuracy"] == 142 / 145
    assert body["f1_macro"] == METRICS["f1_macro"]
    assert body["majority_baseline"] == 75 / 145
    assert body["confusion_matrix"] == METRICS["confusion_matrix"]
    assert [row["class"] for row in body["per_class"]] == ["cat", "dog", "person"]
    assert set(body["per_class"][0]) == {"class", "precision", "recall", "f1", "support"}
    assert body["predictions_uri"] == "/api/p3/evaluation/predictions"
    assert body["examples_uri"] == "/api/p3/evaluation/examples"
    assert body["passes_threshold"] is True
    assert body["most_confused"] == METRICS["most_confused"]
    assert body["evaluated_at"] == METRICS["evaluated_at"]


def test_solo_lee_la_corrida_seleccionada() -> None:
    body = client_with(evaluated()).get("/api/p3/evaluation").json()
    assert body["accuracy"] != 0.1


def test_predicciones_por_muestra_en_csv_para_auditar() -> None:
    response = client_with(evaluated()).get("/api/p3/evaluation/predictions")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.text == CSV


def test_ejemplos_de_aciertos_y_errores() -> None:
    response = client_with(evaluated()).get("/api/p3/evaluation/examples")
    assert response.status_code == 200
    assert response.json() == EXAMPLES


@pytest.mark.parametrize("modulo", ["torch", "mlflow"])
def test_la_api_no_carga_torch_ni_el_cliente_de_mlflow(modulo: str) -> None:
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(api))
    imported: set[Any] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert modulo not in imported


# --- MLflow no disponible: 503 con motivo, nunca 500 -----------------------------------------


class DownMlflow(FakeMlflow):
    def __init__(self, error: Exception, *, on_artifacts: bool = False) -> None:
        base = evaluated()
        super().__init__(base.runs, base.artifacts)
        self.error = error
        self.on_artifacts = on_artifacts

    def search_runs(self, experiment: str) -> list[RunSummary]:
        if not self.on_artifacts:
            raise self.error
        return super().search_runs(experiment)

    def artifact_bytes(self, run: RunSummary, path: str) -> bytes:
        raise self.error


def mlflow_errors() -> list[tuple[Exception, bool]]:
    import urllib.error

    return [
        (urllib.error.URLError("connection refused"), False),
        (urllib.error.HTTPError("http://mlflow", 500, "boom", {}, None), False),
        (urllib.error.URLError("connection refused"), True),
        (urllib.error.HTTPError("http://mlflow", 500, "boom", {}, None), True),
    ]


@pytest.mark.parametrize(
    ("error", "on_artifacts"),
    mlflow_errors(),
    ids=["busqueda-sin-red", "busqueda-500", "artefacto-sin-red", "artefacto-500"],
)
@pytest.mark.parametrize("path", ["", "/predictions", "/examples"])
def test_mlflow_no_disponible_responde_503(error, on_artifacts: bool, path: str) -> None:
    fake = DownMlflow(error, on_artifacts=on_artifacts)
    client = TestClient(client_with(fake).app, raise_server_exceptions=False)
    response = client.get(f"/api/p3/evaluation{path}")
    assert response.status_code == 503
    assert "MLflow" in response.json()["detail"]


def test_el_404_de_mlflow_sigue_siendo_sin_evaluacion_y_no_503() -> None:
    import urllib.error

    fake = DownMlflow(
        urllib.error.HTTPError("http://mlflow", 404, "nf", {}, None), on_artifacts=True
    )
    response = client_with(fake).get("/api/p3/evaluation")
    assert response.status_code == 404
    assert "evaluación final" in response.json()["detail"]
