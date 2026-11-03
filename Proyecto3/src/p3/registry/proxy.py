"""Reenvio de `/api/p3/models` desde la app de P2 al servicio `p3-inference` (F7).

Mismo patron que `p3.inference.proxy`: la app de P2 no tiene acceso de escritura
a S3; pasa la peticion tal cual y devuelve el codigo y el cuerpo del servicio.
Solo libreria estandar.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Response
from starlette.concurrency import run_in_threadpool

router = APIRouter(prefix="/api/p3/models", tags=["p3-models"])
TIMEOUT = 120
Version = Annotated[str, Path(pattern=r"^\d+\.\d+\.\d+$")]

__all__ = ["Response", "get_upstream", "router", "send"]


def get_upstream() -> str:
    return os.environ.get("P3_INFERENCE_URL", "http://p3-inference:8010").rstrip("/")


UpstreamDep = Annotated[str, Depends(get_upstream)]


# Encabezados del servicio que llegan al navegador: los de la descarga (contrato C2).
FORWARDED_HEADERS = ("Content-Disposition", "X-Model-SHA256")


def send(method: str, url: str, body: bytes, headers: dict[str, str]) -> Response:
    request = urllib.request.Request(url, data=body or None, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
            kept = {
                name: answer.headers[name] for name in FORWARDED_HEADERS if answer.headers[name]
            }
            return Response(
                answer.read(),
                answer.status,
                headers=kept,
                media_type=answer.headers.get_content_type(),
            )
    except urllib.error.HTTPError as error:
        return Response(error.read(), error.code, media_type=error.headers.get_content_type())
    except OSError:
        return Response(
            b'{"detail": "El servicio de modelos no responde."}',
            503,
            media_type="application/json",
        )


async def _forward(method: str, upstream: str, path: str) -> Response:
    # `send` se busca en el modulo en cada llamada para poder sustituirlo en pruebas.
    return await run_in_threadpool(send, method, f"{upstream}{path}", b"", {})


@router.get("")
async def read_models(upstream: UpstreamDep) -> Response:
    return await _forward("GET", upstream, "/api/p3/models")


@router.get("/{version}/card")
async def read_card(version: Version, upstream: UpstreamDep) -> Response:
    return await _forward("GET", upstream, f"/api/p3/models/{version}/card")


@router.get("/{version}/download")
async def download(version: Version, upstream: UpstreamDep) -> Response:
    return await _forward("GET", upstream, f"/api/p3/models/{version}/download")


@router.post("/{version}/activate")
async def activate(version: Version, upstream: UpstreamDep) -> Response:
    return await _forward("POST", upstream, f"/api/p3/models/{version}/activate")
