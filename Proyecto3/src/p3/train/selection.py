"""Seleccion del candidato por validacion (F5 T14, criterio 3.3; decisiones.md §4).

Regla predeclarada el 24 sep (commit `ed8cf15`), antes de cualquier corrida:

1. mayor `best_val_accuracy` (la de la epoca restaurada por early stopping);
2. desempate: menor `best_val_loss` en esa misma epoca;
3. segundo desempate: la corrida que termino primero (`end_time`).

Solo cuentan corridas `FINISHED` del experimento del barrido sobre el manifiesto
congelado, y hacen falta al menos 10. El test no interviene en ningun paso.

`POST /api/p3/selection` aplica la regla, calcula el SHA-256 del checkpoint del
ganador y deja la seleccion en MLflow (`selected=true` y `selection` con el
registro). No se puede seleccionar dos veces. `scripts/select_candidate.py`
llama a este endpoint y escribe `docs/selection.json` para commitearlo antes de
la evaluacion en test (F6).

Habla con MLflow por su API REST con la libreria estandar: la app de Proyecto2
no tiene el cliente de MLflow ni PyTorch.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict

from p3.data.frozen import FROZEN_MANIFESTS

EXPERIMENT = "p3-clasificador"
MIN_RUNS = 10
RULE = "max val_accuracy; desempate min val_loss; luego end_time mas temprano"
CHECKPOINT = "checkpoint/model.pt"


class NotEnoughRunsError(ValueError):
    """Menos de `MIN_RUNS` corridas validas: todavia no se puede elegir."""


class MlflowUnavailableError(RuntimeError):
    """MLflow fallo o no responde (no es lo mismo que "el run no existe")."""


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    experiment_id: str
    status: str
    end_time: int | None
    best_val_accuracy: float | None
    best_val_loss: float | None
    best_epoch: int | None
    stopped_epoch: int | None
    manifest_id: str | None
    manifest_hash: str | None
    artifact_uri: str
    params: dict[str, str] = field(default_factory=dict)
    tags: dict[str, str] = field(default_factory=dict)
    start_time: int | None = None

    @classmethod
    def from_rest(cls, run: dict[str, Any]) -> RunSummary:
        info, data = run["info"], run.get("data", {})
        metrics = {m["key"]: m["value"] for m in data.get("metrics", [])}
        tags = {t["key"]: t["value"] for t in data.get("tags", [])}

        def entero(key: str) -> int | None:
            return int(metrics[key]) if key in metrics else None

        return cls(
            run_id=info["run_id"],
            experiment_id=info["experiment_id"],
            status=info["status"],
            end_time=info.get("end_time"),
            best_val_accuracy=metrics.get("best_val_accuracy"),
            best_val_loss=metrics.get("best_val_loss"),
            best_epoch=entero("best_epoch"),
            stopped_epoch=entero("stopped_epoch"),
            manifest_id=tags.get("manifest_id"),
            manifest_hash=tags.get("manifest_hash"),
            artifact_uri=info["artifact_uri"],
            params={p["key"]: p["value"] for p in data.get("params", [])},
            tags=tags,
            start_time=info.get("start_time"),
        )


def valid_runs(runs: list[RunSummary], *, manifest_hash: str) -> list[RunSummary]:
    return [
        run
        for run in runs
        if run.status == "FINISHED"
        and run.manifest_hash == manifest_hash
        and run.best_val_accuracy is not None
        and run.best_val_loss is not None
    ]


def select(runs: list[RunSummary], *, manifest_hash: str, min_runs: int = MIN_RUNS) -> RunSummary:
    candidates = valid_runs(runs, manifest_hash=manifest_hash)
    if len(candidates) < min_runs:
        raise NotEnoughRunsError(
            f"Hay {len(candidates)} corridas FINISHED sobre el manifiesto congelado; "
            f"se necesitan al menos {min_runs}."
        )
    return min(
        candidates,
        key=lambda r: (-(r.best_val_accuracy or 0), r.best_val_loss, r.end_time or 0, r.run_id),
    )


def selection_record(
    winner: RunSummary,
    *,
    candidates: int,
    checkpoint_sha256: str,
    crops_sha256: str | None,
    selected_at: str,
) -> dict[str, Any]:
    """Contenido de `docs/selection.json` (contratos §5)."""
    return {
        "schema_version": 1,
        "selected_at": selected_at,
        "manifest_id": winner.manifest_id,
        "manifest_hash": winner.manifest_hash,
        "rule": RULE,
        "candidates": candidates,
        "run_id": winner.run_id,
        "checkpoint_uri": f"{winner.artifact_uri}/{CHECKPOINT}",
        "checkpoint_sha256": checkpoint_sha256,
        "crops_jsonl_sha256": crops_sha256,
        "best_epoch": winner.best_epoch,
        "val_accuracy": winner.best_val_accuracy,
        "val_loss": winner.best_val_loss,
    }


# --- Acceso a MLflow ------------------------------------------------------------------------


class MlflowAccess(Protocol):
    def search_runs(self, experiment: str) -> list[RunSummary]: ...
    def set_tag(self, run_id: str, key: str, value: str) -> None: ...
    def artifact_bytes(self, run: RunSummary, path: str) -> bytes: ...


class MlflowRest:
    """Cliente minimo de la API REST de MLflow (solo libreria estandar)."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
        return json.loads(raw) if raw else {}

    def experiment_id(self, experiment: str) -> str | None:
        """El id del experimento, o `None` si MLflow no lo tiene (p. ej. sin `dvc pull`)."""
        try:
            found = self._call(
                "GET", f"/api/2.0/mlflow/experiments/get-by-name?experiment_name={experiment}"
            )
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            raise
        return found["experiment"]["experiment_id"]

    def search_runs(self, experiment: str) -> list[RunSummary]:
        experiment_id = self.experiment_id(experiment)
        if experiment_id is None:
            return []
        runs: list[RunSummary] = []
        token = None
        while True:
            body: dict[str, Any] = {"experiment_ids": [experiment_id], "max_results": 1000}
            if token:
                body["page_token"] = token
            page = self._call("POST", "/api/2.0/mlflow/runs/search", body)
            runs += [RunSummary.from_rest(run) for run in page.get("runs", [])]
            token = page.get("next_page_token")
            if not token:
                return runs

    def get_run(self, run_id: str) -> RunSummary:
        try:
            found = self._call("GET", f"/api/2.0/mlflow/runs/get?run_id={run_id}")
        except urllib.error.HTTPError as error:
            if error.code in (400, 404):
                raise LookupError(run_id) from error
            raise MlflowUnavailableError(f"MLflow respondio {error.code}") from error
        except OSError as error:
            raise MlflowUnavailableError(f"MLflow no responde: {error}") from error
        return RunSummary.from_rest(found["run"])

    def metric_history(self, run_id: str, key: str) -> list[tuple[int, float]]:
        found = self._call(
            "GET", f"/api/2.0/mlflow/metrics/get-history?run_id={run_id}&metric_key={key}"
        )
        return [(int(m.get("step", 0)), float(m["value"])) for m in found.get("metrics", [])]

    def set_tag(self, run_id: str, key: str, value: str) -> None:
        self._call(
            "POST", "/api/2.0/mlflow/runs/set-tag", {"run_id": run_id, "key": key, "value": value}
        )

    def artifact_bytes(self, run: RunSummary, path: str) -> bytes:
        relative = run.artifact_uri.removeprefix("mlflow-artifacts:/").strip("/")
        url = f"{self.base_url}/api/2.0/mlflow-artifacts/artifacts/{relative}/{path}"
        with urllib.request.urlopen(url, timeout=300) as response:
            return response.read()


def get_mlflow() -> MlflowAccess:
    return MlflowRest(os.environ.get("P3_MLFLOW_URL", "http://mlflow:5000"))


@contextmanager
def mlflow_available() -> Iterator[None]:
    """MLflow sin red o con un error que no es 404 -> 503 con que revisar, nunca 500."""
    try:
        yield
    except (OSError, MlflowUnavailableError) as error:
        raise HTTPException(
            503,
            f"MLflow no esta disponible ({error}); revisa el servicio `mlflow` y P3_MLFLOW_URL.",
        ) from error


# --- API ------------------------------------------------------------------------------------

router = APIRouter(prefix="/api/p3/selection", tags=["p3-selection"])
MlflowDep = Annotated[MlflowAccess, Depends(get_mlflow)]


class SelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest_id: str


def _current(runs: list[RunSummary]) -> RunSummary | None:
    return next((r for r in runs if r.tags.get("selected") == "true"), None)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_selection(body: SelectionRequest, mlflow: MlflowDep) -> dict[str, Any]:
    manifest_hash = FROZEN_MANIFESTS.get(body.manifest_id)
    if manifest_hash is None:
        raise HTTPException(409, f"El manifiesto {body.manifest_id} no esta congelado.")
    with mlflow_available():
        runs = mlflow.search_runs(EXPERIMENT)
    previous = _current(runs)
    if previous is not None:
        raise HTTPException(
            409, f"La seleccion ya esta cerrada: run {previous.run_id}. No se vuelve a elegir."
        )
    try:
        winner = select(runs, manifest_hash=manifest_hash)
    except NotEnoughRunsError as error:
        raise HTTPException(409, str(error)) from error
    with mlflow_available():
        checkpoint = mlflow.artifact_bytes(winner, CHECKPOINT)
    record = selection_record(
        winner,
        candidates=len(valid_runs(runs, manifest_hash=manifest_hash)),
        checkpoint_sha256=hashlib.sha256(checkpoint).hexdigest(),
        crops_sha256=winner.tags.get("crops_jsonl_sha256"),
        selected_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    with mlflow_available():
        mlflow.set_tag(winner.run_id, "selection", json.dumps(record))
        mlflow.set_tag(winner.run_id, "selected", "true")
    return record


@router.get("")
def read_selection(mlflow: MlflowDep) -> dict[str, Any]:
    with mlflow_available():
        current = _current(mlflow.search_runs(EXPERIMENT))
    if current is None:
        raise HTTPException(404, "Todavia no hay un candidato seleccionado.")
    return json.loads(current.tags["selection"])
