"""Cliente de la cola de anotacion de P1 (F4 T24, criterio 6.5).

"Enviar a la cola de anotacion" crea una imagen nueva en el flujo existente de
P1 con su endpoint de carga (`POST /api/images/upload`, campo `file`), que la
deja en estado `pending` para anotarla. Solo libreria estandar.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from typing import Any, Protocol


class AnnotationQueue(Protocol):
    def upload(self, filename: str, content_type: str, data: bytes) -> dict[str, Any]: ...


class AnnotationUnavailableError(RuntimeError):
    """P1 no responde o rechazo la imagen (HTTP 502)."""


# Arranque ligero de P1 (README, "Cola de anotacion"): sin el seeder, que descarga
# el dataset de Hugging Face.
START_P1 = (
    "cd Proyecto1 && npm install && cp -n .env.example .env && docker compose up -d --wait "
    "&& npm run db:migrate && npm run dev:api"
)


class P1Annotation:
    def __init__(self, base_url: str, timeout: float = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def upload(self, filename: str, content_type: str, data: bytes) -> dict[str, Any]:
        boundary = uuid.uuid4().hex
        safe_name = filename.replace('"', "")
        body = (
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="{safe_name}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode()
            + data
            + f"\r\n--{boundary}--\r\n".encode()
        )
        request = urllib.request.Request(
            f"{self.base_url}/api/images/upload",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read())["data"]
        except urllib.error.HTTPError as error:
            raise AnnotationUnavailableError(
                f"P1 respondio {error.code} al subir la imagen a su cola de anotacion "
                f"({self.base_url}/api/images/upload); revisa los logs de su API."
            ) from error
        except OSError as error:
            raise AnnotationUnavailableError(
                f"P1 (la cola de anotacion) no responde en {self.base_url} "
                f"(P3_ANNOTATION_URL): {error}. Levantalo con: {START_P1}"
            ) from error
