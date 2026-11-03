"""`POST /api/p4/capturas`: token, partes, foto, reglas del evento e idempotencia."""

from __future__ import annotations

import json

import pytest

from conftest import RECIBIDO, TOKEN, app_con, enviar, evento_valido, jpeg
from p4.capturas.config import ConfigCapturas

FOTO = jpeg()


def test_captura_valida_se_guarda_con_los_campos_del_receptor(cliente, almacen):
    respuesta = enviar(cliente, evento_valido(FOTO), FOTO)
    assert respuesta.status_code == 201, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo == {
        "estado": "creado",
        "capture_id": "edge01-20261015T100000-0001",
        "image_key": "edge-capturas/fotos/edge01-20261015T100000-0001.jpg",
        "record_key": "edge-capturas/eventos/edge01-20261015T100000-0001.json",
        "received_at": RECIBIDO.isoformat(timespec="milliseconds"),
    }
    registro = almacen.obtener("edge01-20261015T100000-0001")
    assert registro["confidence"] == 0.93
    assert (registro["image_width"], registro["image_height"]) == (64, 48)
    assert registro["image_bytes"] == len(FOTO)
    assert almacen.foto("edge01-20261015T100000-0001") == FOTO


def test_reintento_identico_responde_duplicado_y_no_escribe(cliente, almacen):
    primera = enviar(cliente, evento_valido(FOTO), FOTO)
    segunda = enviar(cliente, evento_valido(FOTO), FOTO)
    assert (primera.status_code, segunda.status_code) == (201, 200)
    assert segunda.json() == {**primera.json(), "estado": "duplicado"}
    assert len(almacen.listar()[0]) == 1


def test_mismo_id_con_otros_datos_es_conflicto_y_no_sobrescribe(cliente, almacen):
    enviar(cliente, evento_valido(FOTO), FOTO)
    respuesta = enviar(cliente, evento_valido(FOTO, predicted_class="cat", confidence=0.6), FOTO)
    assert respuesta.status_code == 409
    assert respuesta.json()["error"] == "conflicto_capture_id"
    assert {d["campo"] for d in respuesta.json()["detalles"]} == {"predicted_class", "confidence"}
    assert almacen.obtener("edge01-20261015T100000-0001")["predicted_class"] == "dog"


def test_sin_token_401(cliente, almacen):
    respuesta = enviar(cliente, evento_valido(FOTO), FOTO, token=None)
    assert respuesta.status_code == 401
    assert respuesta.json()["error"] == "no_autorizado"
    assert almacen.listar()[0] == []


def test_token_incorrecto_401(cliente):
    assert enviar(cliente, evento_valido(FOTO), FOTO, token="otro").status_code == 401


def test_receptor_sin_token_configurado_503(almacen):
    config = ConfigCapturas(P4_ALMACEN="memoria", P4_MODELOS_ACEPTADOS="v=" + "a" * 64)
    respuesta = enviar(app_con(config, almacen), evento_valido(FOTO), FOTO)
    assert respuesta.status_code == 503
    assert respuesta.json()["error"] == "receptor_no_configurado"


@pytest.mark.parametrize(
    ("evento", "foto", "mensaje"),
    [
        (None, FOTO, "Falta la parte 'evento'"),
        ("ignorado", None, "Falta la parte 'foto'"),
        ("{no es json", FOTO, "no es JSON valido"),
        ("[1, 2]", FOTO, "debe ser un objeto JSON"),
    ],
    ids=["sin evento", "sin foto", "json roto", "json no objeto"],
)
def test_partes_faltantes_o_rotas_400(cliente, evento, foto, mensaje):
    evento = evento_valido(FOTO) if evento == "ignorado" else evento
    respuesta = enviar(cliente, evento, foto)
    assert respuesta.status_code == 400
    assert respuesta.json()["error"] == "solicitud_invalida"
    assert mensaje in respuesta.json()["detail"]


def test_evento_como_archivo_tambien_se_acepta(cliente):
    respuesta = cliente.post(
        "/api/p4/capturas",
        headers={"Authorization": f"Bearer {TOKEN}"},
        files={
            "evento": ("evento.json", json.dumps(evento_valido(FOTO)), "application/json"),
            "foto": ("captura.jpg", FOTO, "image/jpeg"),
        },
    )
    assert respuesta.status_code == 201, respuesta.text


def test_foto_que_no_es_jpeg_415(cliente):
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 100
    respuesta = enviar(cliente, evento_valido(png), png)
    assert respuesta.status_code == 415
    assert respuesta.json()["error"] == "foto_no_soportada"


def test_jpeg_corrupto_415(cliente):
    roto = FOTO[:40]
    assert enviar(cliente, evento_valido(roto), roto).status_code == 415


def test_foto_demasiado_grande_413(cliente):
    grande = FOTO + b"\0" * 200_000  # el tope de la fixture `config` es 200 000 bytes
    respuesta = enviar(cliente, evento_valido(grande), grande)
    assert respuesta.status_code == 413
    assert respuesta.json()["error"] == "foto_demasiado_grande"


def test_evento_demasiado_grande_413(cliente):
    evento = evento_valido(FOTO, image_ref="x" * 20_000)
    respuesta = enviar(cliente, evento, FOTO)
    assert respuesta.status_code == 413
    assert respuesta.json()["error"] == "evento_demasiado_grande"


ACEPTADOS = {
    "fecha en UTC con Z": {"captured_at": "2026-10-15T16:00:00Z"},
    "fecha con fraccion": {"captured_at": "2026-10-15T10:00:00.125-06:00"},
    "confianza 0": {"confidence": 0},
    "confianza 1.0": {"confidence": 1.0},
    "region dentro de la foto": {"region": {"x": 0, "y": 0, "width": 64, "height": 48}},
}


@pytest.mark.parametrize("cambios", ACEPTADOS.values(), ids=ACEPTADOS.keys())
def test_variantes_validas(cliente, cambios):
    respuesta = enviar(cliente, evento_valido(FOTO, **cambios), FOTO)
    assert respuesta.status_code == 201, respuesta.text


def sin(campo: str) -> dict[str, object]:
    evento = evento_valido(FOTO)
    evento.pop(campo)
    return evento


RECHAZADOS = {
    "fecha sin zona": (evento_valido(FOTO, captured_at="2026-10-15T10:00:00"), "captured_at"),
    "fecha invalida": (evento_valido(FOTO, captured_at="ayer"), "captured_at"),
    "confianza mayor a 1": (evento_valido(FOTO, confidence=1.2), "confidence"),
    "confianza negativa": (evento_valido(FOTO, confidence=-0.1), "confidence"),
    "confianza en texto": (evento_valido(FOTO, confidence="0.9"), "confidence"),
    "confianza booleana": (evento_valido(FOTO, confidence=True), "confidence"),
    "sin model_version": (sin("model_version"), "model_version"),
    "model_version vacia": (evento_valido(FOTO, model_version=" "), "model_version"),
    "version no aceptada": (evento_valido(FOTO, model_version="9.9.9"), "model_version"),
    "sha de otro modelo": (evento_valido(FOTO, model_sha256="b" * 64), "model_sha256"),
    "sha en mayusculas": (evento_valido(FOTO, model_sha256="A" * 64), "model_sha256"),
    "clase fuera del modelo": (evento_valido(FOTO, predicted_class="bird"), "predicted_class"),
    "id con diagonal": (evento_valido(FOTO, capture_id="edge01/0001"), "capture_id"),
    "id empieza con guion": (evento_valido(FOTO, capture_id="-0001"), "capture_id"),
    "id de 129": (evento_valido(FOTO, capture_id="a" * 129), "capture_id"),
    "dispositivo vacio": (evento_valido(FOTO, device_id=""), "device_id"),
    "image_ref vacio": (evento_valido(FOTO, image_ref=""), "image_ref"),
    "sha de otra foto": (evento_valido(FOTO, image_sha256="c" * 64), "image_sha256"),
    "schema_version 2": (evento_valido(FOTO, schema_version=2), "schema_version"),
    "campo desconocido": (evento_valido(FOTO, confianza=0.9), "confianza"),
    "region negativa": (
        evento_valido(FOTO, region={"x": -1, "y": 0, "width": 5, "height": 5}),
        "region.x",
    ),
    "region sin alto": (
        evento_valido(FOTO, region={"x": 0, "y": 0, "width": 5}),
        "region.height",
    ),
    "region fuera de la foto": (
        evento_valido(FOTO, region={"x": 60, "y": 0, "width": 10, "height": 5}),
        "region",
    ),
}


@pytest.mark.parametrize(("evento", "campo"), RECHAZADOS.values(), ids=RECHAZADOS.keys())
def test_variantes_invalidas_422_con_el_campo(cliente, almacen, evento, campo):
    respuesta = enviar(cliente, evento, FOTO)
    assert respuesta.status_code == 422, respuesta.text
    assert respuesta.json()["error"] == "evento_invalido"
    assert campo in [d["campo"] for d in respuesta.json()["detalles"]]
    assert almacen.listar()[0] == []


def test_todos_los_problemas_llegan_juntos(cliente):
    evento = evento_valido(
        FOTO, predicted_class="bird", model_version="9.9.9", image_sha256="c" * 64
    )
    respuesta = enviar(cliente, evento, FOTO)
    campos = [d["campo"] for d in respuesta.json()["detalles"]]
    assert campos == ["predicted_class", "model_version", "image_sha256"]


def test_sin_modelos_configurados_lo_dice(almacen):
    config = ConfigCapturas(P4_ALMACEN="memoria", P4_TOKEN_DISPOSITIVO=TOKEN)
    respuesta = enviar(app_con(config, almacen), evento_valido(FOTO), FOTO)
    assert respuesta.status_code == 422
    assert "P4_MODELOS_ACEPTADOS" in respuesta.json()["detail"]


def jpeg_que_declara(ancho: int, alto: int) -> bytes:
    """JPEG chiquito cuyo encabezado (SOF0) dice medir `ancho x alto`: una foto "bomba"."""
    datos = bytearray(FOTO)
    sof = datos.index(b"\xff\xc0")
    datos[sof + 5 : sof + 7] = alto.to_bytes(2, "big")
    datos[sof + 7 : sof + 9] = ancho.to_bytes(2, "big")
    return bytes(datos)


@pytest.mark.parametrize(
    ("ancho", "alto"),
    [(65000, 65000), (8000, 8000)],
    ids=["bomba que Pillow rechaza", "sobre el tope del receptor"],
)
def test_foto_bomba_es_415_y_no_500(cliente, almacen, ancho, alto):
    bomba = jpeg_que_declara(ancho, alto)
    assert len(bomba) < 2000
    respuesta = enviar(cliente, evento_valido(bomba), bomba)
    assert respuesta.status_code == 415, respuesta.text
    assert respuesta.json()["error"] == "foto_no_soportada"
    assert almacen.listar()[0] == []
