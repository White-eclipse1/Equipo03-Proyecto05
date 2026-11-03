"""Reenvio de `/api/p3/inference` desde la app de P2 al servicio `p3-inference` (F4 T24).

La app de P2 sirve el portal pero no tiene PyTorch; la inferencia vive en otro
contenedor. Este router pasa el cuerpo y el `Content-Type` tal cual y devuelve
el codigo y la respuesta del servicio. Solo libreria estandar.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, Response
from starlette.concurrency import run_in_threadpool

router = APIRouter(prefix="/api/p3/inference", tags=["p3-inference"])
TIMEOUT = 120


def get_upstream() -> str:
    return os.environ.get("P3_INFERENCE_URL", "http://p3-inference:8010").rstrip("/")


UpstreamDep = Annotated[str, Depends(get_upstream)]
# El id va dentro de la URL del servicio: solo letras, digitos, `-` y `_`.
InferenceId = Annotated[str, Path(pattern=r"^[0-9A-Za-z_-]{1,64}$")]


def _send(url: str, body: bytes, headers: dict[str, str]) -> Response:
    forwarded = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(forwarded, timeout=TIMEOUT) as answer:
            return Response(
                answer.read(), answer.status, media_type=answer.headers.get_content_type()
            )
    except urllib.error.HTTPError as error:
        return Response(error.read(), error.code, media_type=error.headers.get_content_type())
    except OSError:
        return Response(
            b'{"detail": "El servicio de inferencia no responde."}',
            503,
            media_type="application/json",
        )


async def _forward(request: Request, upstream: str, path: str) -> Response:
    body = await request.body()
    headers = {}
    if "content-type" in request.headers:
        headers["Content-Type"] = request.headers["content-type"]
    # urllib bloquea: se corre en un hilo para no detener el resto del portal.
    return await run_in_threadpool(_send, f"{upstream}{path}", body, headers)


@router.post("")
async def predict(request: Request, upstream: UpstreamDep) -> Response:
    return await _forward(request, upstream, "/api/p3/inference")


@router.post("/{inference_id}/send-to-annotation")
async def send_to_annotation(
    inference_id: InferenceId, request: Request, upstream: UpstreamDep
) -> Response:
    return await _forward(request, upstream, f"/api/p3/inference/{inference_id}/send-to-annotation")
