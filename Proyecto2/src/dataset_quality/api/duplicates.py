"""Endpoints para revisar y eliminar los casi-duplicados.

Son los unicos de la API que escriben. La separacion importa:

  - `GET  /api/duplicates/plan`   dice que se eliminaria. No toca nada.
  - `POST /api/duplicates/remove` lo ejecuta.

El boton de la pantalla llama al primero, ensena el numero y solo tras la
confirmacion de una persona llama al segundo. El Copilot no tiene acceso a
ninguno de los dos: el agente es de solo lectura, y que un humano pueda
disparar esto desde la interfaz no cambia esa regla.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from dataset_quality.api.artifacts import ARTIFACTS
from dataset_quality.models.coco import load_coco
from dataset_quality.models.quality import QualityReport
from dataset_quality.tiers import dedupe
from dataset_quality.tiers.ingest import RAW_ANNOTATIONS, RAW_IMAGES

router = APIRouter(prefix="/api/duplicates", tags=["duplicados"])


def _cargar() -> tuple[Any, QualityReport]:
    """Dataset y reporte, o un 503 que dice que correr."""
    reporte_path: Path = ARTIFACTS["quality"].path
    if not reporte_path.is_file():
        raise HTTPException(
            status_code=503,
            detail="Todavia no hay `quality.json`. Corre `dq gate` para saber que sobra.",
        )
    if not RAW_ANNOTATIONS.is_file():
        raise HTTPException(
            status_code=503,
            detail="No hay dataset en `data/raw/`. Corre `dvc pull data/raw.dvc`.",
        )

    dataset = load_coco(RAW_ANNOTATIONS)
    reporte = QualityReport.model_validate_json(reporte_path.read_text(encoding="utf-8"))
    return dataset, reporte


def _plan():
    dataset, reporte = _cargar()
    try:
        return dataset, dedupe.build_plan(dataset, reporte)
    except dedupe.DedupeError as error:
        # 409: el estado del repositorio impide la operacion. No es culpa de
        # la peticion, asi que no es un 400, y no es un fallo nuestro.
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/plan")
def plan() -> dict[str, Any]:
    """Que se eliminaria si se pulsa el boton. Solo lectura."""
    _, propuesta = _plan()
    return {
        "remove_count": len(propuesta.remove_ids),
        "annotations_removed": propuesta.annotations_removed,
        "total_images": propuesta.total_images,
        "kept": propuesta.kept,
        # Una muestra basta para que la persona reconozca lo que va a pasar.
        "sample": propuesta.remove_files[:12],
    }


@router.post("/remove")
def remove() -> dict[str, Any]:
    """Mueve las copias a cuarentena y reescribe el COCO sin ellas."""
    dataset, propuesta = _plan()
    if propuesta.is_empty:
        return {
            "removed_images": 0,
            "message": "No hay duplicados que eliminar.",
            "stale_reports": False,
        }

    resultado = dedupe.apply(propuesta, dataset, RAW_ANNOTATIONS, RAW_IMAGES)
    return {
        "removed_images": resultado.removed_images,
        "removed_annotations": resultado.removed_annotations,
        "remaining_images": resultado.remaining_images,
        "quarantine_dir": resultado.quarantine_dir,
        "missing_on_disk": resultado.missing_on_disk,
        # El dataset cambio: todo lo que el pipeline calculo antes ya no lo
        # describe. La pantalla tiene que decirlo, no disimularlo.
        "stale_reports": True,
        "next_steps": [
            "dq analyze --json reports/stats.json",
            "dq gate",
            "dvc add data/raw && dvc push",
        ],
        "undo": f"Las imagenes estan en `{resultado.quarantine_dir}/`; "
        "para revertir, muevelas de vuelta a `data/raw/images/` y corre `dq gate`.",
    }
