"""Endpoint para recalcular el pipeline desde la app web.

Existe por una razon concreta: el boton de duplicados deja los artefactos
obsoletos por definicion — el dataset cambio — y hasta ahora la unica salida
era abrir una terminal. Una app que puede modificar el dataset pero no puede
volver a medirlo deja a quien la usa a medio camino.

Lo que NO hace, deliberadamente:

  - no toca DVC. `dvc add` y `dvc push` mueven bytes a un remoto con
    credenciales y quedan registrados en el versionado; eso se decide en una
    terminal, no con un clic.
  - no devuelve un error cuando la compuerta bloquea. Un 500 diria "la
    operacion fallo"; lo que pasa es que la operacion funciono y el veredicto
    es que no. Eso viaja en el cuerpo, con 200.
"""

from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter, HTTPException

from dataset_quality import policy
from dataset_quality.api.artifacts import REPORTS
from dataset_quality.models.errors import DatasetValidationError
from dataset_quality.tiers import pipeline
from dataset_quality.tiers.ingest import RAW_ANNOTATIONS, RAW_IMAGES

# Un recorrido dura segundos y escribe dos archivos. Dos peticiones a la vez
# los escribirian entrelazados, asi que la segunda se rechaza en vez de
# esperar: quien pulso dos veces prefiere saberlo a quedarse mirando.
LOCK = threading.Lock()

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


@router.post("/refresh")
def refresh() -> dict[str, Any]:
    """Vuelve a medir el dataset y reescribe `stats.json` y `quality.json`."""
    if not RAW_ANNOTATIONS.is_file():
        raise HTTPException(
            status_code=503,
            detail="No hay dataset en `data/raw/`. Corre `dvc pull data/raw.dvc`.",
        )
    if not policy.CONFIG_PATH.is_file():
        raise HTTPException(
            status_code=503,
            detail=(
                f"Falta `quality.yaml` en {policy.CONFIG_PATH.parent}: "
                "sin politica no hay umbrales."
            ),
        )

    if not LOCK.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail="Ya hay un recalculo en curso. Espera a que termine.",
        )
    try:
        resultado = pipeline.refresh(
            coco_path=RAW_ANNOTATIONS,
            images_dir=RAW_IMAGES,
            config_path=policy.CONFIG_PATH,
            stats_out=REPORTS / "stats.json",
            quality_out=REPORTS / "quality.json",
        )
    except DatasetValidationError as error:
        # El dataset o la config no cumplen su contrato. Es un 422: lo que hay
        # en disco esta mal, y el mensaje de validacion dice exactamente donde.
        raise HTTPException(status_code=422, detail=str(error)) from error
    finally:
        LOCK.release()

    return {
        "status": resultado.status,
        "exit_code": resultado.exit_code,
        "dataset_fingerprint": resultado.dataset_fingerprint,
        "totals": resultado.totals.model_dump(),
        "blocking": resultado.blocking,
        "warnings": resultado.warnings,
        "duration_seconds": resultado.duration_seconds,
        "checks": [
            {"name": check.name, "status": check.status, "severity": check.severity}
            for check in resultado.checks
        ],
        # Lo unico que sigue pendiente en la terminal.
        "next_steps": (
            ["dvc add data/raw && dvc push"]
            if resultado.exit_code == 0
            else ["Corrige lo que bloquea y vuelve a recalcular."]
        ),
    }
