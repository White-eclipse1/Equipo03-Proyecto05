"""Exportacion de los eventos guardados (evidencia recalculable para el evaluador)."""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from typing import Any

from p4.capturas.evento import fecha_con_zona

COLUMNAS = [
    "capture_id",
    "captured_at",
    "received_at",
    "device_id",
    "predicted_class",
    "confidence",
    "model_version",
    "model_sha256",
    "image_sha256",
    "image_ref",
    "image_key",
    "image_bytes",
    "image_width",
    "image_height",
    "region_x",
    "region_y",
    "region_width",
    "region_height",
]


def ordenar(
    registros: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """De mas reciente a mas antigua por `captured_at` en UTC (desempate: recepcion, ID).

    Un registro sin fecha valida con zona no se puede ordenar: va a la segunda lista
    (los mismos `errores` que reporta el listado) y no tumba a los demas.
    """
    validos: list[tuple[tuple[datetime, str, str], dict[str, Any]]] = []
    errores: list[dict[str, str]] = []
    for registro in registros:
        cid = registro.get("capture_id")
        try:
            capturada = fecha_con_zona(registro["captured_at"]).astimezone(UTC)
        except (KeyError, TypeError, ValueError) as error:
            errores.append(
                {"llave": str(cid), "problema": f"captured_at no se puede ordenar: {error}"}
            )
            continue
        validos.append(((capturada, str(registro.get("received_at", "")), str(cid)), registro))
    validos.sort(key=lambda par: par[0], reverse=True)
    return [registro for _, registro in validos], errores


def _fila(registro: dict[str, Any]) -> dict[str, Any]:
    fila = {columna: registro.get(columna) for columna in COLUMNAS}
    region = registro.get("region") or {}
    for lado in ("x", "y", "width", "height"):
        fila[f"region_{lado}"] = region.get(lado)
    return fila


def a_csv(registros: list[dict[str, Any]]) -> str:
    salida = io.StringIO()
    escritor = csv.DictWriter(salida, fieldnames=COLUMNAS, lineterminator="\n")
    escritor.writeheader()
    escritor.writerows(_fila(r) for r in registros)
    return salida.getvalue()


def a_json(registros: list[dict[str, Any]], errores: list[dict[str, str]], ahora: datetime) -> str:
    return json.dumps(
        {
            "exportado_en": ahora.astimezone(UTC).isoformat(timespec="seconds"),
            "total": len(registros),
            "items": registros,
            "errores": errores,
        },
        ensure_ascii=False,
        indent=2,
    )


def nombre_archivo(ahora: datetime, extension: str) -> str:
    return f"capturas-edge-{ahora.astimezone(UTC):%Y%m%dT%H%M%SZ}.{extension}"
