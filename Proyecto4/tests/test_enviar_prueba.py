"""`scripts/enviar_prueba.py` contra el receptor real en memoria (sin red ni AWS)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from conftest import app_con
from p4.capturas.almacen import AlmacenMemoria
from p4.capturas.config import ConfigCapturas

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "enviar_prueba.py"
_spec = importlib.util.spec_from_file_location("enviar_prueba", SCRIPT)
enviar_prueba = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = enviar_prueba
_spec.loader.exec_module(enviar_prueba)

TOKEN = "token-de-prueba-ci"  # valor falso, solo para pruebas
URL_LOCAL = "http://testserver/api/p4/capturas"


@pytest.fixture
def receptor(monkeypatch, tmp_path) -> TestClient:
    config = ConfigCapturas(
        P4_ALMACEN="memoria",
        P4_TOKEN_DISPOSITIVO=TOKEN,
        P4_MODELOS_ACEPTADOS=f"{enviar_prueba.MODELO}={enviar_prueba.MODELO_SHA256}",
    )
    cliente = app_con(config, AlmacenMemoria())
    monkeypatch.setenv("P4_TOKEN_DISPOSITIVO", TOKEN)
    monkeypatch.setattr(enviar_prueba, "REGISTRO_LOCAL", tmp_path)
    monkeypatch.setattr(enviar_prueba.httpx, "post", cliente.post)
    return cliente


def resultado(tmp_path: Path) -> dict:
    [carpeta] = list(tmp_path.iterdir())
    return json.loads((carpeta / "resultado.json").read_text(encoding="utf-8"))


def test_las_seis_comprobaciones_del_contrato_pasan(receptor, tmp_path):
    assert enviar_prueba.main(["--url", URL_LOCAL, "--token-de-entorno"]) == 0
    datos = resultado(tmp_path)
    assert datos["todo_ok"] is True
    assert [c["obtenido"][:2] for c in datos["casos"][:5]] == [
        [201, "creado"],
        [200, "duplicado"],
        [409, "conflicto_capture_id"],
        [422, "evento_invalido"],
        [401, "no_autorizado"],
    ]
    assert datos["casos"][5]["caso"].startswith("6.") and datos["casos"][5]["ok"]
    [carpeta] = list(tmp_path.iterdir())
    assert {p.name for p in carpeta.iterdir()} == {"foto.jpg", "evento.json", "resultado.json"}
    # El token nunca queda en el registro local.
    assert TOKEN not in "".join(p.read_text(errors="ignore") for p in carpeta.glob("*.json"))


def test_el_token_real_no_se_envia_a_otra_url(monkeypatch, tmp_path):
    def no_leer(*_):
        raise AssertionError("no debe leer el token real para una URL ajena")

    monkeypatch.setattr(enviar_prueba, "leer_token", no_leer)
    monkeypatch.setattr(enviar_prueba, "REGISTRO_LOCAL", tmp_path)
    with pytest.raises(SystemExit, match="solo se envia a"):
        enviar_prueba.main(["--url", "https://servidor-ajeno.example/api/p4/capturas"])
    assert list(tmp_path.iterdir()) == []


def test_detecta_un_reintento_que_cambia_received_at(receptor, monkeypatch, tmp_path):
    llamadas = []
    original = enviar_prueba.httpx.post

    def post_alterado(*args, **kwargs):
        respuesta = original(*args, **kwargs)
        llamadas.append(respuesta)
        if len(llamadas) == 2:  # el reintento, con otra fecha de recepcion
            cuerpo = {**respuesta.json(), "received_at": "2000-01-01T00:00:00.000+00:00"}
            return httpx.Response(respuesta.status_code, json=cuerpo)
        return respuesta

    monkeypatch.setattr(enviar_prueba.httpx, "post", post_alterado)
    assert enviar_prueba.main(["--url", URL_LOCAL, "--token-de-entorno"]) == 1
    caso6 = resultado(tmp_path)["casos"][5]
    assert caso6["ok"] is False
