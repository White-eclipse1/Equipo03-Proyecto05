"""Lecturas para Capturas Edge: listado ordenado, detalle, foto y exportacion."""

from __future__ import annotations

import csv
import io

from conftest import app_con, enviar, evento_valido, jpeg
from p4.capturas.almacen import AlmacenAusente

# Mismo instante en zonas distintas no es "mas reciente": se ordena en UTC.
CAPTURAS = [
    ("edge01-a", "2026-10-15T10:00:00-06:00", (255, 0, 0)),  # 16:00 UTC
    ("edge01-b", "2026-10-15T17:30:00+00:00", (0, 255, 0)),  # 17:30 UTC, la mas reciente
    ("edge01-c", "2026-10-15T09:00:00-06:00", (0, 0, 255)),  # 15:00 UTC, la mas antigua
]


def cargar(cliente) -> dict[str, bytes]:
    fotos = {}
    for cid, fecha, color in CAPTURAS:
        foto = jpeg(color=color)
        fotos[cid] = foto
        respuesta = enviar(cliente, evento_valido(foto, capture_id=cid, captured_at=fecha), foto)
        assert respuesta.status_code == 201, respuesta.text
    return fotos


def test_listado_vacio(cliente):
    assert cliente.get("/api/p4/capturas").json() == {"items": [], "total": 0, "errores": []}


def test_listado_de_mas_reciente_a_mas_antigua_en_utc(cliente):
    cargar(cliente)
    cuerpo = cliente.get("/api/p4/capturas").json()
    assert [i["capture_id"] for i in cuerpo["items"]] == ["edge01-b", "edge01-a", "edge01-c"]
    assert cuerpo["total"] == 3


def test_limite_recorta_pero_total_cuenta_todo(cliente):
    cargar(cliente)
    cuerpo = cliente.get("/api/p4/capturas?limite=1").json()
    assert [i["capture_id"] for i in cuerpo["items"]] == ["edge01-b"]
    assert cuerpo["total"] == 3


def test_detalle_y_404(cliente):
    cargar(cliente)
    registro = cliente.get("/api/p4/capturas/edge01-a").json()
    assert registro["captured_at"] == "2026-10-15T10:00:00-06:00"
    assert registro["image_key"] == "edge-capturas/fotos/edge01-a.jpg"
    faltante = cliente.get("/api/p4/capturas/no-existe")
    assert faltante.status_code == 404
    assert faltante.json()["error"] == "captura_no_encontrada"


def test_id_con_caracteres_invalidos_no_llega_al_almacen(cliente):
    assert cliente.get("/api/p4/capturas/-malo").status_code == 422


def test_foto_son_los_mismos_bytes(cliente):
    fotos = cargar(cliente)
    respuesta = cliente.get("/api/p4/capturas/edge01-c/foto")
    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"] == "image/jpeg"
    assert respuesta.content == fotos["edge01-c"]


def test_exportar_csv_con_todas_las_columnas(cliente):
    cargar(cliente)
    enviar(
        cliente,
        evento_valido(
            jpeg(),
            capture_id="edge01-r",
            captured_at="2026-10-15T08:00:00-06:00",
            region={"x": 1, "y": 2, "width": 3, "height": 4},
        ),
        jpeg(),
    )
    respuesta = cliente.get("/api/p4/capturas/exportar?formato=csv")
    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"].startswith("text/csv")
    assert "capturas-edge-" in respuesta.headers["content-disposition"]
    filas = list(csv.DictReader(io.StringIO(respuesta.text)))
    assert [f["capture_id"] for f in filas] == ["edge01-b", "edge01-a", "edge01-c", "edge01-r"]
    con_region = filas[-1]
    assert (con_region["region_x"], con_region["region_height"]) == ("1", "4")
    assert filas[0]["confidence"] == "0.93"
    assert filas[0]["region_x"] == ""


def test_exportar_json(cliente):
    cargar(cliente)
    respuesta = cliente.get("/api/p4/capturas/exportar")
    cuerpo = respuesta.json()
    assert cuerpo["total"] == 3
    assert [i["capture_id"] for i in cuerpo["items"]] == ["edge01-b", "edge01-a", "edge01-c"]
    assert respuesta.headers["x-capturas-con-error"] == "0"


def test_almacen_no_configurado_responde_503_en_todo(config):
    cliente = app_con(config, AlmacenAusente("El receptor no tiene P4_BUCKET configurado"))
    foto = jpeg()
    rutas = [
        cliente.get("/api/p4/capturas"),
        cliente.get("/api/p4/capturas/edge01-a"),
        cliente.get("/api/p4/capturas/edge01-a/foto"),
        cliente.get("/api/p4/capturas/exportar"),
        enviar(cliente, evento_valido(foto), foto),
    ]
    for respuesta in rutas:
        assert respuesta.status_code == 503, respuesta.text
        assert respuesta.json() == {
            "error": "almacen_no_disponible",
            "detail": "El receptor no tiene P4_BUCKET configurado",
            "detalles": [],
        }


def test_registro_con_fecha_invalida_no_tumba_el_listado_ni_la_exportacion(cliente, almacen):
    cargar(cliente)
    # Un registro que llego a S3 por fuera del receptor, con captured_at sin zona.
    roto = {**almacen.obtener("edge01-a"), "capture_id": "edge01-roto"}
    roto["captured_at"] = "2026-10-15T10:00:00"
    almacen._registros["edge01-roto"] = roto
    sin_fecha = {k: v for k, v in roto.items() if k != "captured_at"}
    almacen._registros["edge01-sin-fecha"] = {**sin_fecha, "capture_id": "edge01-sin-fecha"}

    listado = cliente.get("/api/p4/capturas")
    assert listado.status_code == 200
    cuerpo = listado.json()
    assert [i["capture_id"] for i in cuerpo["items"]] == ["edge01-b", "edge01-a", "edge01-c"]
    assert sorted(e["llave"] for e in cuerpo["errores"]) == ["edge01-roto", "edge01-sin-fecha"]

    for formato in ("csv", "json"):
        exportacion = cliente.get(f"/api/p4/capturas/exportar?formato={formato}")
        assert exportacion.status_code == 200
        assert exportacion.headers["x-capturas-con-error"] == "2"
