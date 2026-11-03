"""API de inferencia (F4 T24, criterio 6.5; contratos §4).

Corre en el servicio `p3-inference` (imagen con PyTorch); la app de P2 le
reenvia `/api/p3/inference` con `p3.inference.proxy`.

- `POST /api/p3/inference`: multipart con `file` (JPEG o PNG, <= 10 MB) y
  `bbox_xywh` opcional (JSON `[x, y, ancho, alto]` en pixeles de la imagen como se
  ve). Predice con la version activa y guarda la inferencia.
- `POST /api/p3/inference/{id}/send-to-annotation`: sube esa misma imagen a la
  cola de anotacion de P1; si ya se envio, devuelve el mismo elemento.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from p3.inference import records
from p3.inference.annotation import AnnotationQueue, AnnotationUnavailableError
from p3.inference.service import (
    InferenceError,
    InferenceService,
    ModelIntegrityError,
    ModelUnavailableError,
    StorageUnavailableError,
)

router = APIRouter(prefix="/api/p3/inference", tags=["p3-inference"])


def get_service() -> InferenceService:
    from p3.inference.settings import get_inference_service

    try:
        return get_inference_service()
    except StorageUnavailableError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error


def get_session() -> Iterator[Session]:
    from p3.inference.settings import get_session_factory

    with get_session_factory().begin() as session:
        yield session


def get_annotation() -> AnnotationQueue:
    from p3.inference.settings import get_annotation_queue

    return get_annotation_queue()


ServiceDep = Annotated[InferenceService, Depends(get_service)]
SessionDep = Annotated[Session, Depends(get_session)]
AnnotationDep = Annotated[AnnotationQueue, Depends(get_annotation)]


def _parse_bbox(raw: str | None) -> list[float] | None:
    if raw is None or raw == "":
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise HTTPException(422, "bbox_xywh debe ser JSON: [x, y, ancho, alto].") from error
    if not isinstance(value, list) or len(value) != 4:
        raise HTTPException(422, "bbox_xywh debe tener 4 numeros: [x, y, ancho, alto].")
    return [float(v) for v in value]


@router.post("")
async def predict(
    inference: ServiceDep,
    session: SessionDep,
    file: Annotated[UploadFile, File()],
    bbox_xywh: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    data = await file.read()
    bbox = _parse_bbox(bbox_xywh)
    content_type = file.content_type or "application/octet-stream"
    try:
        # PyTorch bloquea: la prediccion corre en un hilo.
        result = await run_in_threadpool(inference.predict, data, content_type, bbox)
    except InferenceError as error:
        raise HTTPException(error.status_code, str(error)) from error
    except StorageUnavailableError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error
    except (ModelUnavailableError, ModelIntegrityError) as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error

    record = records.new_inference(
        filename=file.filename or "imagen",
        content_type=content_type,
        image=data,
        bbox_xywh=bbox,
        model_version=result.model_version,
        model_sha256=result.model_sha256,
        run_id=result.run_id,
        predicted_class=result.predicted_class,
        probabilities=result.probabilities,
    )
    session.add(record)
    session.flush()
    return {
        "inference_id": record.id,
        "model_version": result.model_version,
        "model_sha256": result.model_sha256,
        "run_id": result.run_id,
        "predicted_class": result.predicted_class,
        "probabilities": result.probabilities,
    }


@router.post("/{inference_id}/send-to-annotation")
def send_to_annotation(
    inference_id: str, session: SessionDep, queue: AnnotationDep
) -> JSONResponse:
    record = session.get(records.Inference, inference_id)
    if record is None:
        raise HTTPException(404, f"No existe la inferencia {inference_id}")
    if record.annotation_image_id is not None:
        item = {"image_id": record.annotation_image_id, "status": "pending"}
        return JSONResponse({"annotation_queue_item": item}, status_code=200)
    try:
        created = queue.upload(record.filename, record.content_type, record.image)
    except AnnotationUnavailableError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error
    record.annotation_image_id = int(created["id"])
    item = {"image_id": record.annotation_image_id, "status": created.get("status", "pending")}
    return JSONResponse({"annotation_queue_item": item}, status_code=201)
