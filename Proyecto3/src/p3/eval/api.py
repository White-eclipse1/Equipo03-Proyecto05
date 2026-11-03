"""API de la evaluacion final para la pagina Evaluation (F6, contratos §4; criterio 6.3).

Todo sale de MLflow: la corrida `selected=true` del barrido y sus artefactos
`evaluation/` (los registra `scripts/log_evaluation_mlflow.py`). Asi portal,
API y MLflow muestran las mismas cifras (4.2).

- `GET /api/p3/evaluation`: metricas, matriz, baseline y procedencia.
- `GET /api/p3/evaluation/predictions`: `predictions_test.csv` por muestra, para auditar.
- `GET /api/p3/evaluation/examples`: aciertos y errores de test (`errors.json`).
- `GET /api/p3/evaluation/crops/{crop_id}`: el PNG de un recorte del test del
  manifiesto elegido (miniaturas de la galeria, 4.4). Lee el manifiesto y los
  recortes en disco; 404 si el recorte no es de ese test, 503 si faltan.

Mientras la seleccion no este cerrada responde 409 y no revela nada del test.
Si MLflow no responde (o responde un error que no es 404) responde 503, no 500.
Solo lee: usa el cliente REST de `p3.train.selection`, sin torch ni el cliente
de MLflow, porque se monta en la app de P2.
"""

from __future__ import annotations

import json
import urllib.error
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, NamedTuple

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi import Path as PathParam

from p3.data.api import get_frozen
from p3.data.frozen import ManifestNotFrozenError, verify_frozen
from p3.train.selection import EXPERIMENT, MlflowDep, RunSummary, get_mlflow

router = APIRouter(prefix="/api/p3/evaluation", tags=["p3-evaluation"])

NOT_SELECTED = "La selección del modelo no está cerrada"
FOLDER = "evaluation"
PER_CLASS_FIELDS = ("class", "precision", "recall", "f1", "support")

__all__ = ["get_frozen", "get_mlflow", "router"]


class DataDirs(NamedTuple):
    manifests: Path
    crops: Path


def get_data_dirs() -> DataDirs:
    from p3.data.settings import get_settings

    settings = get_settings()
    return DataDirs(settings.manifests_dir, settings.crops_dir)


DataDirsDep = Annotated[DataDirs, Depends(get_data_dirs)]
FrozenDep = Annotated[Mapping[str, str], Depends(get_frozen)]
# `<release_id>:a<annotation_id>` (`p3.data.crops.crop_id`); tambien impide salir de la carpeta.
CropId = Annotated[str, PathParam(pattern=r"^\d+\.\d+\.\d+:a\d+$")]


def _selected(mlflow: Any) -> RunSummary:
    try:
        runs = mlflow.search_runs(EXPERIMENT)
    except OSError as error:
        raise _mlflow_down(error) from error
    run = next((r for r in runs if r.tags.get("selected") == "true"), None)
    if run is None:
        raise HTTPException(409, NOT_SELECTED)
    return run


def _artifact(mlflow: Any, run: RunSummary, name: str) -> bytes:
    try:
        return mlflow.artifact_bytes(run, f"{FOLDER}/{name}")
    except FileNotFoundError as error:
        raise _no_evaluation(run) from error
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise _no_evaluation(run) from error
        raise _mlflow_down(error) from error
    except OSError as error:
        raise _mlflow_down(error) from error


def _mlflow_down(error: OSError) -> HTTPException:
    return HTTPException(
        503, f"MLflow no esta disponible ({error}); revisa el servicio `mlflow` y P3_MLFLOW_URL."
    )


def _no_evaluation(run: RunSummary) -> HTTPException:
    return HTTPException(
        404, f"La corrida seleccionada {run.run_id} todavía no tiene la evaluación final en test."
    )


@router.get("")
def read_evaluation(mlflow: MlflowDep) -> dict[str, Any]:
    run = _selected(mlflow)
    metrics = json.loads(_artifact(mlflow, run, "metrics.json"))
    selection = json.loads(run.tags.get("selection") or "{}")
    return {
        "run_id": run.run_id,
        "manifest_id": metrics["manifest_id"],
        # Procedencia (6.3): de donde salen las cifras.
        "release_id": run.tags.get("release_id"),
        "manifest_hash": metrics.get("manifest_hash") or run.manifest_hash,
        "checkpoint_sha256": selection.get("checkpoint_sha256"),
        "selected_at": selection.get("selected_at"),
        "test_size": metrics["test_size"],
        "accuracy": metrics["accuracy"],
        "passes_threshold": metrics["passes_threshold"],
        "threshold": metrics["threshold"],
        "f1_macro": metrics["f1_macro"],
        "per_class": [{k: row[k] for k in PER_CLASS_FIELDS} for row in metrics["per_class"]],
        "confusion_matrix": metrics["confusion_matrix"],
        "majority_baseline": metrics["majority_baseline"]["accuracy"],
        "majority_class": metrics["majority_baseline"]["class"],
        "most_confused": metrics["most_confused"],
        "evaluated_at": metrics["evaluated_at"],
        "predictions_uri": f"{router.prefix}/predictions",
        "examples_uri": f"{router.prefix}/examples",
    }


@router.get("/predictions")
def read_predictions(mlflow: MlflowDep) -> Response:
    run = _selected(mlflow)
    return Response(
        _artifact(mlflow, run, "predictions_test.csv"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="predictions_test.csv"'},
    )


@router.get("/examples")
def read_examples(mlflow: MlflowDep) -> dict[str, Any]:
    run = _selected(mlflow)
    return json.loads(_artifact(mlflow, run, "errors.json"))


@router.get("/crops/{crop_id}")
def read_crop(crop_id: CropId, mlflow: MlflowDep, dirs: DataDirsDep, frozen: FrozenDep) -> Response:
    run = _selected(mlflow)
    if crop_id not in _test_crops(dirs.manifests, run.manifest_id, frozen):
        raise HTTPException(
            404, f"El recorte {crop_id} no es del test del manifiesto {run.manifest_id}."
        )
    release_id = crop_id.split(":")[0]
    path = _crop_paths(dirs.crops, release_id).get(crop_id)
    if path is None or not path.is_file():
        raise _missing_crops(release_id)
    return Response(path.read_bytes(), media_type="image/png")


def _test_crops(folder: Path, manifest_id: str, frozen: Mapping[str, str]) -> frozenset[str]:
    """Los recortes de test del manifiesto, solo si sus bytes son los congelados.

    Un manifiesto editado podria pasar recortes de train a test; por eso se
    verifica el SHA-256 (`verify_frozen`) antes de leer el split.
    """
    manifest = folder / manifest_id / "manifest.jsonl"
    if not manifest.is_file():
        raise HTTPException(
            503,
            f"El manifiesto {manifest_id} no está descargado; corre "
            f"`dvc pull data/manifests/{manifest_id}.dvc` en Proyecto3.",
        )
    try:
        return _frozen_test_crops(manifest.parent, _stamp(manifest), frozen.get(manifest_id))
    except ManifestNotFrozenError as error:
        raise HTTPException(409, str(error)) from error


def _crop_paths(folder: Path, release_id: str) -> dict[str, Path]:
    index = folder / release_id / "crops.jsonl"
    if not index.is_file():
        raise _missing_crops(release_id)
    return _crop_index(index, _stamp(index))


# Una pagina pide ~15 miniaturas: el manifiesto (1459 filas) y `crops.jsonl` se
# leen y verifican una vez por version del archivo (ruta, mtime y tamano).
def _stamp(path: Path) -> tuple[int, int]:
    info = path.stat()
    return info.st_mtime_ns, info.st_size


@lru_cache(maxsize=8)
def _frozen_test_crops(
    manifest_dir: Path, stamp: tuple[int, int], expected: str | None
) -> frozenset[str]:
    verify_frozen(manifest_dir, {manifest_dir.name: expected} if expected else {})
    with (manifest_dir / "manifest.jsonl").open(encoding="utf-8") as lines:
        rows = (json.loads(line) for line in lines if line.strip())
        return frozenset(row["crop_id"] for row in rows if row["split"] == "test")


@lru_cache(maxsize=8)
def _crop_index(index: Path, stamp: tuple[int, int]) -> dict[str, Path]:
    release = index.parent
    with index.open(encoding="utf-8") as lines:
        rows = (json.loads(line) for line in lines if line.strip())
        return {row["crop_id"]: release / row["crop_path"] for row in rows}


def _missing_crops(release_id: str) -> HTTPException:
    return HTTPException(
        503,
        f"Faltan los recortes del release {release_id}; generalos con "
        f"`scripts/generate_crops.py --release {release_id}` (README).",
    )
