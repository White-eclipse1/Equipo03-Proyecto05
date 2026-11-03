"""Utilidades de prueba del receptor: foto JPEG sintetica, evento valido y app minima."""

from __future__ import annotations

import hashlib
import io
import json
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from p4.capturas import api
from p4.capturas.almacen import AlmacenMemoria
from p4.capturas.config import ConfigCapturas

TOKEN = "token-de-prueba"  # valor falso, solo para pruebas
VERSION = "1.0.0-prueba"
SHA_MODELO = "a" * 64
RECIBIDO = datetime(2026, 10, 15, 16, 0, 0, 250000, tzinfo=UTC)


def jpeg(ancho: int = 64, alto: int = 48, color: tuple[int, int, int] = (200, 30, 30)) -> bytes:
    salida = io.BytesIO()
    Image.new("RGB", (ancho, alto), color).save(salida, format="JPEG")
    return salida.getvalue()


def evento_valido(foto: bytes, **cambios: Any) -> dict[str, Any]:
    evento: dict[str, Any] = {
        "schema_version": 1,
        "capture_id": "edge01-20261015T100000-0001",
        "captured_at": "2026-10-15T10:00:00-06:00",
        "predicted_class": "dog",
        "confidence": 0.93,
        "device_id": "edge01",
        "model_version": VERSION,
        "model_sha256": SHA_MODELO,
        "image_sha256": hashlib.sha256(foto).hexdigest(),
        "image_ref": "capturas/edge01-20261015T100000-0001.jpg",
        "region": None,
    }
    evento.update(cambios)
    return evento


def enviar(cliente: TestClient, evento: Any, foto: bytes | None, token: str | None = TOKEN):
    """Envia como lo hara el dispositivo: `evento` como texto y `foto` como archivo."""
    cabeceras = {"Authorization": f"Bearer {token}"} if token is not None else {}
    datos = (
        {}
        if evento is None
        else {"evento": evento if isinstance(evento, str) else json.dumps(evento)}
    )
    archivos = {} if foto is None else {"foto": ("captura.jpg", foto, "image/jpeg")}
    return cliente.post("/api/p4/capturas", headers=cabeceras, data=datos, files=archivos)


@pytest.fixture
def config() -> ConfigCapturas:
    return ConfigCapturas(
        P4_ALMACEN="memoria",
        P4_TOKEN_DISPOSITIVO=TOKEN,
        P4_MODELOS_ACEPTADOS=f"{VERSION}={SHA_MODELO}",
        P4_MAX_FOTO_BYTES=200_000,
    )


@pytest.fixture
def almacen() -> AlmacenMemoria:
    return AlmacenMemoria()


def app_con(config: ConfigCapturas, almacen: Any) -> TestClient:
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.obtener_config] = lambda: config
    app.dependency_overrides[api.obtener_almacen] = lambda: almacen
    return TestClient(app)


@pytest.fixture
def cliente(config: ConfigCapturas, almacen: AlmacenMemoria, monkeypatch) -> TestClient:
    monkeypatch.setattr(api, "ahora", lambda: RECIBIDO)
    return app_con(config, almacen)
