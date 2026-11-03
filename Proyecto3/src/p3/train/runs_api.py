"""Corridas de MLflow para la pagina Experiments (contratos §4; F5, criterios 3.2 y 6.2).

- `GET /api/p3/runs?manifest_id=&status=&order_by=&desc=`: corridas del
  experimento del barrido, con sus parametros, mejor epoca y metricas de
  validacion. `order_by` acepta `val_accuracy`, `val_loss`, `start_time` y
  `end_time`.
- `GET /api/p3/runs/{run_id}`: lo mismo mas la historia por epoca (curvas
  train/val) y las rutas de sus artefactos.

Todo sale de la API de MLflow en vivo (`MlflowRest`), no de archivos locales.
Nunca devuelve metricas ni tags de test (`test_*`, F6): los campos se eligen uno por uno.
`/runs/{run_id}` solo sirve corridas del experimento del barrido.
Solo libreria estandar, sin MLflow ni torch.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Protocol

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from p3.train.selection import EXPERIMENT, RunSummary, get_mlflow, mlflow_available

router = APIRouter(prefix="/api/p3/runs", tags=["p3-runs"])

HISTORY = ("train_loss", "train_accuracy", "val_loss", "val_accuracy")
ARTIFACTS = {
    "checkpoint": "checkpoint/model.pt",
    "curves": "curves.png",
    "history": "history.json",
    "environment": "environment.json",
}
ORDER_KEYS = {
    "val_accuracy": lambda r: r.best_val_accuracy or 0.0,
    "val_loss": lambda r: r.best_val_loss if r.best_val_loss is not None else float("inf"),
    "start_time": lambda r: r.start_time or 0,
    "end_time": lambda r: r.end_time or 0,
}


class RunsMlflow(Protocol):
    def experiment_id(self, experiment: str) -> str | None: ...
    def search_runs(self, experiment: str) -> list[RunSummary]: ...
    def get_run(self, run_id: str) -> RunSummary: ...
    def metric_history(self, run_id: str, key: str) -> list[tuple[int, float]]: ...


MlflowDep = Annotated[RunsMlflow, Depends(get_mlflow)]
# El id va dentro de la URL de MLflow: solo letras, digitos, `-` y `_`.
RunId = Annotated[str, Path(pattern=r"^[0-9A-Za-z_-]{1,64}$")]


def _iso(ms: int | None) -> str | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _summary(run: RunSummary) -> dict[str, Any]:
    return {
        "run_id": run.run_id,
        "experiment_id": run.experiment_id,
        "status": run.status,
        "manifest_id": run.manifest_id,
        "params": run.params,
        "best_epoch": run.best_epoch,
        "stopped_epoch": run.stopped_epoch,
        "best_val_accuracy": run.best_val_accuracy,
        "best_val_loss": run.best_val_loss,
        "commit": run.tags.get("code_commit"),
        "selected": run.tags.get("selected") == "true",
        "start_time": _iso(run.start_time),
        "end_time": _iso(run.end_time),
    }


@router.get("")
def list_runs(
    mlflow: MlflowDep,
    manifest_id: str | None = None,
    status: str | None = None,
    order_by: Annotated[
        Literal["val_accuracy", "val_loss", "start_time", "end_time"] | None, Query()
    ] = None,
    desc: bool = True,
) -> dict[str, list[dict[str, Any]]]:
    with mlflow_available():
        runs = mlflow.search_runs(EXPERIMENT)
    if manifest_id is not None:
        runs = [r for r in runs if r.manifest_id == manifest_id]
    if status is not None:
        runs = [r for r in runs if r.status == status]
    if order_by is not None:
        runs = sorted(runs, key=ORDER_KEYS[order_by], reverse=desc)
    return {"runs": [_summary(r) for r in runs]}


@router.get("/{run_id}")
def read_run(run_id: RunId, mlflow: MlflowDep) -> dict[str, Any]:
    with mlflow_available():
        try:
            run = mlflow.get_run(run_id)
        except LookupError as error:
            raise HTTPException(404, f"No existe el run {run_id}") from error
        if run.experiment_id != mlflow.experiment_id(EXPERIMENT):
            raise HTTPException(404, f"El run {run_id} no es del experimento {EXPERIMENT}")
        series = {key: dict(mlflow.metric_history(run.run_id, key)) for key in HISTORY}
    epochs = sorted(set().union(*(s.keys() for s in series.values())))
    history = [
        {"epoch": epoch, **{key: series[key].get(epoch) for key in HISTORY}} for epoch in epochs
    ]
    artifacts = {name: f"{run.artifact_uri}/{path}" for name, path in ARTIFACTS.items()}
    return {**_summary(run), "history": history, "artifacts": artifacts}
