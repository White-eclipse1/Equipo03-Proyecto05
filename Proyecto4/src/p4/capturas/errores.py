"""Errores del receptor con un cuerpo uniforme.

`{"error": <codigo>, "detail": <mensaje>, "detalles": [...]}`: `detail` es la
misma clave que usa FastAPI, asi el portal muestra el mensaje sin casos
especiales; `error` es estable para que el dispositivo decida si reintenta.
"""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse


class CapturaError(Exception):
    def __init__(
        self,
        status: int,
        codigo: str,
        mensaje: str,
        detalles: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(mensaje)
        self.status = status
        self.codigo = codigo
        self.mensaje = mensaje
        self.detalles = detalles or []

    def respuesta(self) -> JSONResponse:
        return JSONResponse(
            status_code=self.status,
            content={"error": self.codigo, "detail": self.mensaje, "detalles": self.detalles},
        )


def evento_invalido(problemas: list[dict[str, Any]]) -> CapturaError:
    primero = problemas[0]
    return CapturaError(
        422, "evento_invalido", f"{primero['campo']}: {primero['problema']}", problemas
    )
