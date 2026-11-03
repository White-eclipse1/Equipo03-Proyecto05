"""Evento de captura `schema_version` 1: lo que manda el dispositivo por cada foto.

Dos niveles de reglas:
- `EventoCaptura` (forma): campos obligatorios, tipos estrictos y campos
  desconocidos rechazados, para que un error de tipeo no se guarde en silencio.
- `validar_evento` (contexto): clase del modelo, version aceptada, hash de la foto
  recibida y region dentro de la foto. Necesitan la configuracion o la foto.

Todos los problemas se devuelven juntos en un 422: el dispositivo ve de una vez
que corregir.
"""

from __future__ import annotations

import json
import math
import re
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from p4.capturas.config import ConfigCapturas
from p4.capturas.errores import CapturaError, evento_invalido
from p4.capturas.foto import Foto

PATRON_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
PATRON_DISPOSITIVO = re.compile(r"[A-Za-z0-9._-]{1,64}")
PATRON_SHA256 = re.compile(r"[0-9a-f]{64}")


def fecha_con_zona(valor: str) -> datetime:
    """ISO 8601 con offset -> `datetime` con zona. `ValueError` con el motivo si no."""
    try:
        fecha = datetime.fromisoformat(valor)
    except ValueError as error:
        raise ValueError("no es una fecha ISO 8601 (ej. 2026-10-15T10:30:00-06:00)") from error
    if fecha.utcoffset() is None:
        raise ValueError("debe incluir zona horaria (ej. -06:00 o Z)")
    return fecha


class Region(BaseModel):
    """Recorte clasificado, en pixeles de la foto."""

    model_config = ConfigDict(extra="forbid", strict=True)

    x: int
    y: int
    width: int
    height: int

    @field_validator("x", "y")
    @classmethod
    def _no_negativo(cls, valor: int) -> int:
        if valor < 0:
            raise ValueError("debe ser >= 0")
        return valor

    @field_validator("width", "height")
    @classmethod
    def _positivo(cls, valor: int) -> int:
        if valor <= 0:
            raise ValueError("debe ser > 0")
        return valor


class EventoCaptura(BaseModel):
    """Campos que envia el dispositivo (todos obligatorios salvo `region`)."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1]
    capture_id: str
    captured_at: str
    predicted_class: str
    confidence: float
    device_id: str
    model_version: str
    model_sha256: str
    image_sha256: str
    image_ref: str
    region: Region | None = None

    @field_validator("capture_id")
    @classmethod
    def _id(cls, valor: str) -> str:
        if not PATRON_ID.fullmatch(valor):
            raise ValueError(
                "solo letras, digitos, '.', '_' y '-' (1 a 128), empezando por letra o digito"
            )
        return valor

    @field_validator("captured_at")
    @classmethod
    def _fecha(cls, valor: str) -> str:
        fecha_con_zona(valor)
        return valor

    @field_validator("confidence")
    @classmethod
    def _confianza(cls, valor: float) -> float:
        if not math.isfinite(valor) or not 0 <= valor <= 1:
            raise ValueError(f"debe estar entre 0 y 1; llego {valor}")
        return valor

    @field_validator("device_id")
    @classmethod
    def _dispositivo(cls, valor: str) -> str:
        if not PATRON_DISPOSITIVO.fullmatch(valor):
            raise ValueError("solo letras, digitos, '.', '_' y '-' (1 a 64)")
        return valor

    @field_validator("model_version", "image_ref")
    @classmethod
    def _no_vacio(cls, valor: str) -> str:
        if not valor.strip():
            raise ValueError("no puede estar vacio")
        return valor

    @field_validator("model_sha256", "image_sha256")
    @classmethod
    def _sha(cls, valor: str) -> str:
        if not PATRON_SHA256.fullmatch(valor):
            raise ValueError("debe ser un SHA-256 de 64 caracteres hex en minusculas")
        return valor

    def capturada_utc(self) -> datetime:
        return fecha_con_zona(self.captured_at).astimezone(UTC)

    def campos(self) -> dict[str, Any]:
        """Los campos tal como los mando el dispositivo, para guardar y comparar."""
        return self.model_dump(mode="json")


def _problema(error: dict[str, Any]) -> dict[str, str]:
    campo = ".".join(str(parte) for parte in error["loc"]) or "evento"
    tipo = error["type"]
    if tipo == "missing":
        problema = "es obligatorio"
    elif tipo == "extra_forbidden":
        problema = "campo desconocido: no forma parte del contrato"
    elif tipo == "value_error":
        problema = str(error["ctx"]["error"])
    else:
        problema = str(error["msg"])
    return {"campo": campo, "problema": problema}


def leer_evento(texto: str) -> EventoCaptura:
    """Texto de la parte `evento` -> `EventoCaptura`. 400 si no es JSON; 422 si no cumple."""
    try:
        crudo = json.loads(texto)
    except json.JSONDecodeError as error:
        raise CapturaError(
            400, "solicitud_invalida", f"La parte 'evento' no es JSON valido: {error.msg}"
        ) from error
    if not isinstance(crudo, dict):
        raise CapturaError(400, "solicitud_invalida", "La parte 'evento' debe ser un objeto JSON")
    try:
        return EventoCaptura.model_validate(crudo)
    except ValidationError as error:
        raise evento_invalido([_problema(e) for e in error.errors()]) from error


def validar_evento(evento: EventoCaptura, foto: Foto, config: ConfigCapturas) -> None:
    """Reglas que dependen de la configuracion y de la foto. 422 con todos los problemas."""
    problemas: list[dict[str, str]] = []

    clases = config.lista_clases()
    if evento.predicted_class not in clases:
        problemas.append(
            {"campo": "predicted_class", "problema": f"debe ser una de: {', '.join(clases)}"}
        )

    modelos = config.modelos()
    if evento.model_version not in modelos:
        aceptadas = ", ".join(sorted(modelos)) or "ninguna configurada en P4_MODELOS_ACEPTADOS"
        problemas.append(
            {
                "campo": "model_version",
                "problema": f"{evento.model_version} no es una version aceptada ({aceptadas})",
            }
        )
    elif modelos[evento.model_version] != evento.model_sha256:
        problemas.append(
            {"campo": "model_sha256", "problema": f"no corresponde a {evento.model_version}"}
        )

    if evento.image_sha256 != foto.sha256:
        problemas.append({"campo": "image_sha256", "problema": "no coincide con la foto recibida"})

    region = evento.region
    if region is not None and (
        region.x + region.width > foto.ancho or region.y + region.height > foto.alto
    ):
        problemas.append(
            {
                "campo": "region",
                "problema": f"queda fuera de la foto ({foto.ancho}x{foto.alto} px)",
            }
        )

    if problemas:
        raise evento_invalido(problemas)
