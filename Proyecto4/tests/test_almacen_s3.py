"""`AlmacenS3`: idempotencia con escrituras condicionales, fallas visibles y listado."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import boto3
import pytest
from botocore.exceptions import EndpointConnectionError
from botocore.stub import ANY, Stubber

from conftest import RECIBIDO, evento_valido, jpeg
from p4.capturas.almacen import (
    AlmacenNoDisponibleError,
    AlmacenS3,
    CapturaNoEncontradaError,
    ConflictoCapturaError,
)
from p4.capturas.evento import EventoCaptura
from p4.capturas.foto import inspeccionar_foto
from s3_falso import Objeto, S3Falso, error_s3

BUCKET = "bucket-de-prueba"
PREFIJO = "edge-capturas/"
FOTO = inspeccionar_foto(jpeg(), 1_000_000)
EVENTO = EventoCaptura.model_validate(evento_valido(FOTO.datos))
CID = EVENTO.capture_id
FOTO_KEY = f"{PREFIJO}fotos/{CID}.jpg"
REG_KEY = f"{PREFIJO}eventos/{CID}.json"


@pytest.fixture
def s3() -> S3Falso:
    return S3Falso()


@pytest.fixture
def almacen(s3) -> AlmacenS3:
    return AlmacenS3(s3, BUCKET, PREFIJO)


def test_parametros_validos_para_la_api_real_de_s3():
    """Stubber rechaza parametros que no existen en el modelo de botocore (p. ej. IfNoneMatch)."""
    cliente = boto3.client(
        "s3", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x"
    )
    with Stubber(cliente) as stub:
        stub.add_response(
            "put_object",
            {},
            {
                "Bucket": BUCKET,
                "Key": FOTO_KEY,
                "Body": FOTO.datos,
                "ContentType": "image/jpeg",
                "Metadata": {"sha256": FOTO.sha256, "capture-id": CID},
                "IfNoneMatch": "*",
            },
        )
        stub.add_response(
            "put_object",
            {},
            {
                "Bucket": BUCKET,
                "Key": REG_KEY,
                "Body": ANY,
                "ContentType": "application/json",
                "IfNoneMatch": "*",
            },
        )
        guardado = AlmacenS3(cliente, BUCKET, PREFIJO).guardar(EVENTO, FOTO, RECIBIDO)
        stub.assert_no_pending_responses()
    assert guardado.estado == "creado"


def test_guarda_foto_y_registro(almacen, s3):
    guardado = almacen.guardar(EVENTO, FOTO, RECIBIDO)
    assert guardado.estado == "creado"
    assert s3.escrituras == [FOTO_KEY, REG_KEY]  # la foto primero
    assert s3.objetos[FOTO_KEY].cuerpo == FOTO.datos
    assert s3.objetos[FOTO_KEY].metadatos["sha256"] == FOTO.sha256
    registro = json.loads(s3.objetos[REG_KEY].cuerpo)
    assert registro == {
        **evento_valido(FOTO.datos),
        "received_at": RECIBIDO.isoformat(timespec="milliseconds"),
        "image_key": FOTO_KEY,
        "image_bytes": FOTO.bytes,
        "image_width": 64,
        "image_height": 48,
    }


def test_reintento_identico_es_duplicado_sin_escribir(almacen, s3):
    almacen.guardar(EVENTO, FOTO, RECIBIDO)
    despues = datetime(2026, 10, 15, 18, 0, tzinfo=UTC)
    guardado = almacen.guardar(EVENTO, FOTO, despues)
    assert guardado.estado == "duplicado"
    assert guardado.registro["received_at"] == RECIBIDO.isoformat(timespec="milliseconds")
    assert s3.escrituras == [FOTO_KEY, REG_KEY]


def test_otra_foto_con_el_mismo_id_es_conflicto(almacen, s3):
    almacen.guardar(EVENTO, FOTO, RECIBIDO)
    otra = inspeccionar_foto(jpeg(color=(0, 0, 0)), 1_000_000)
    evento = EventoCaptura.model_validate(evento_valido(otra.datos))
    with pytest.raises(ConflictoCapturaError) as conflicto:
        almacen.guardar(evento, otra, RECIBIDO)
    assert conflicto.value.diferencias[0]["campo"] == "image_sha256"
    assert s3.objetos[FOTO_KEY].cuerpo == FOTO.datos


def test_otros_datos_con_el_mismo_id_es_conflicto(almacen, s3):
    almacen.guardar(EVENTO, FOTO, RECIBIDO)
    evento = EventoCaptura.model_validate(evento_valido(FOTO.datos, confidence=0.5))
    with pytest.raises(ConflictoCapturaError) as conflicto:
        almacen.guardar(evento, FOTO, RECIBIDO)
    assert conflicto.value.diferencias == [
        {"campo": "confidence", "guardado": 0.93, "recibido": 0.5}
    ]
    assert json.loads(s3.objetos[REG_KEY].cuerpo)["confidence"] == 0.93


def test_falla_a_la_mitad_se_completa_con_el_reintento(almacen, s3):
    s3.fallar_llave[REG_KEY] = error_s3("InternalError", 500, "PutObject")
    with pytest.raises(AlmacenNoDisponibleError):
        almacen.guardar(EVENTO, FOTO, RECIBIDO)
    assert FOTO_KEY in s3.objetos  # la foto quedo, el registro no
    assert REG_KEY not in s3.objetos

    guardado = almacen.guardar(EVENTO, FOTO, RECIBIDO)
    assert guardado.estado == "creado"
    assert json.loads(s3.objetos[REG_KEY].cuerpo)["image_key"] == FOTO_KEY


def test_error_de_s3_al_guardar_es_no_disponible(almacen, s3):
    s3.fallar["put_object"] = error_s3("InternalError", 500, "PutObject")
    with pytest.raises(AlmacenNoDisponibleError, match="InternalError"):
        almacen.guardar(EVENTO, FOTO, RECIBIDO)
    assert s3.objetos == {}


def test_sin_red_es_no_disponible(almacen, s3):
    s3.fallar["put_object"] = EndpointConnectionError(endpoint_url="https://s3.amazonaws.com")
    with pytest.raises(AlmacenNoDisponibleError, match="EndpointConnectionError"):
        almacen.guardar(EVENTO, FOTO, RECIBIDO)


def test_permiso_denegado_es_no_disponible_y_no_conflicto(almacen, s3):
    s3.fallar["put_object"] = error_s3("AccessDenied", 403, "PutObject")
    with pytest.raises(AlmacenNoDisponibleError, match="AccessDenied"):
        almacen.guardar(EVENTO, FOTO, RECIBIDO)


def test_obtener_y_foto_inexistentes(almacen):
    with pytest.raises(CapturaNoEncontradaError):
        almacen.obtener("no-existe")
    with pytest.raises(CapturaNoEncontradaError):
        almacen.foto("no-existe")


def test_listado_pagina_y_reporta_registros_ilegibles(almacen, s3):
    s3.por_pagina = 2
    for i in range(5):
        foto = inspeccionar_foto(jpeg(color=(i * 40, 0, 0)), 1_000_000)
        evento = EventoCaptura.model_validate(evento_valido(foto.datos, capture_id=f"edge01-{i}"))
        almacen.guardar(evento, foto, RECIBIDO)
    s3.objetos[f"{PREFIJO}eventos/roto.json"] = Objeto(b"{no json", {})
    s3.objetos[f"{PREFIJO}eventos/sin-id.json"] = Objeto(b"{}", {})
    registros, errores = almacen.listar()
    assert sorted(r["capture_id"] for r in registros) == [f"edge01-{i}" for i in range(5)]
    assert sorted(e["llave"] for e in errores) == [
        f"{PREFIJO}eventos/roto.json",
        f"{PREFIJO}eventos/sin-id.json",
    ]


def test_listado_con_s3_caido_es_no_disponible(almacen, s3):
    s3.fallar["list_objects_v2"] = error_s3("ServiceUnavailable", 503, "ListObjectsV2")
    with pytest.raises(AlmacenNoDisponibleError):
        almacen.listar()
