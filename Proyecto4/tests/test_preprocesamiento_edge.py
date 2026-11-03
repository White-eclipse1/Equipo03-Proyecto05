"""Preprocesamiento y entradas conocidas en el edge (VAL-07, #19).

`edge/verificar_preprocesamiento.py` (comprobaciones sinteticas y evaluacion) y
`validacion/contrastar_edge.py` (Raspberry contra laptop). Sin onnxruntime ni modelos.
"""

from __future__ import annotations

import copy
import csv
import importlib.util
import io
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

PROYECTO4 = Path(__file__).resolve().parents[1]


def cargar(nombre: str, ruta: Path):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = modulo
    spec.loader.exec_module(modulo)
    return modulo


vp = cargar("verificar_preprocesamiento", PROYECTO4 / "edge" / "verificar_preprocesamiento.py")
ce = cargar("contrastar_edge", PROYECTO4 / "validacion" / "contrastar_edge.py")
ORIGINAL = vp.preprocesar


def fallidas(comprobaciones: list[dict]) -> set[str]:
    return {c["id"] for c in comprobaciones if not c["ok"]}


def test_el_preprocesamiento_del_repositorio_pasa_todas_las_comprobaciones():
    comprobaciones = vp.comprobaciones_sinteticas()
    assert len(comprobaciones) == 6
    assert fallidas(comprobaciones) == set()


def bgr(imagen):
    return ORIGINAL(imagen)[:, ::-1].copy()


def sin_normalizar(imagen):
    rgb = imagen.convert("RGB").resize((224, 224), Image.Resampling.BILINEAR)
    return np.ascontiguousarray(
        (np.asarray(rgb, dtype=np.float32) / 255.0).transpose(2, 0, 1)[np.newaxis]
    )


def recorte_central(imagen):
    rgb = imagen.convert("RGB")
    lado = min(rgb.size)
    x, y = (rgb.width - lado) // 2, (rgb.height - lado) // 2
    return ORIGINAL(rgb.crop((x, y, x + lado, y + lado)))


def float64(imagen):
    return ORIGINAL(imagen).astype(np.float64)


@pytest.mark.parametrize(
    ("errado", "debe_fallar"),
    [
        (bgr, {"normalizacion.exacta", "rgb.orden_y_orientacion"}),
        (sin_normalizar, {"normalizacion.exacta", "rgb.orden_y_orientacion"}),
        (recorte_central, {"resize.sin_recorte"}),
        (float64, {"tensor.forma_tipo"}),
    ],
)
def test_detecta_preprocesamientos_incorrectos(monkeypatch, errado, debe_fallar):
    monkeypatch.setattr(vp, "preprocesar", errado)
    assert debe_fallar <= fallidas(vp.comprobaciones_sinteticas())


class SesionFalsa:
    def __init__(self, sesgo: list[float]):
        self.sesgo = np.asarray([sesgo], dtype=np.float32)

    def run(self, _salidas, entradas):
        tensor = next(iter(entradas.values()))
        assert tensor.shape == (1, 3, 224, 224) and tensor.dtype == np.float32
        return [tensor.mean(axis=(2, 3)) + self.sesgo]


def test_evaluar_registra_tensor_y_cada_ejecucion():
    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 10, 10)).save(buffer, format="PNG")
    ejecutores = {
        "int8": (SesionFalsa([0, 0, 0]), "entrada", "logits"),
        "int8_referencia": (SesionFalsa([0, 5, 0]), "entrada", "logits"),
        "fp32": (SesionFalsa([0, 0, 0]), "entrada", "logits"),
    }
    entrada = {"id": "x", "tipo": "val", "clase": "cat", "sha256": "s"}
    fila = vp.evaluar(entrada, buffer.getvalue(), ejecutores)
    assert (fila["tensor_forma"], fila["tensor_tipo"]) == ("1x3x224x224", "float32")
    assert (fila["imagen_modo"], fila["imagen_tamano"]) == ("RGB", "40x30")
    assert fila["int8_prediction"] == "cat" and fila["int8_referencia_prediction"] == "dog"
    assert len(fila["tensor_sha256"]) == 64 and set(fila) == set(vp.columnas())


def corrida(maquina: str, arquitectura: str, filas: list[dict]) -> tuple[dict, list[dict], bytes]:
    salida = io.StringIO()
    escritor = csv.DictWriter(salida, fieldnames=list(filas[0]), lineterminator="\n")
    escritor.writeheader()
    escritor.writerows(filas)
    datos = salida.getvalue().encode()
    meta = {
        "maquina": maquina,
        "hardware": {"arquitectura": arquitectura, "modelo_dispositivo": "Raspberry Pi 4"},
        "runtime": {"onnxruntime": "1.31.0"},
        "codigo": {"preprocesar.py": "p" * 64},
        "modelos": {"int8": {"sha256": "i"}, "fp32": {"sha256": "f"}},
        "entradas": {"indice_sha256": "e"},
        "preprocesamiento": {
            "comprobaciones_sinteticas": [{"id": "a", "ok": True, "tensor_sha256": "t"}]
        },
        "resultados": {"sha256": __import__("hashlib").sha256(datos).hexdigest()},
    }
    return meta, list(csv.DictReader(io.StringIO(datos.decode()))), datos


def fila(id_: str, tipo: str, clase: str, int8: str | None = None, tensor: str = "t") -> dict:
    datos = {
        "id": id_,
        "tipo": tipo,
        "clase": clase,
        "tensor_forma": "1x3x224x224",
        "tensor_tipo": "float32",
        "tensor_sha256": tensor,
    }
    for ejecucion in ce.EJECUCIONES:
        prediccion = int8 if (ejecucion == "int8" and int8) else clase
        datos[f"{ejecucion}_prediction"] = prediccion
        for c in ce.CLASES:
            datos[f"{ejecucion}_logit_{c}"] = "1.0" if c == prediccion else "0.0"
    return datos


FILAS = [fila(f"v{i}", "val", c) for i, c in enumerate(ce.CLASES * 3)] + [
    fila("foto", "camara", "dog")
]


def test_contraste_aceptado_y_diferencias_contadas_sin_fallar():
    edge_filas = copy.deepcopy(FILAS)
    edge_filas[0] = fila("v0", "val", "cat", int8="person")  # el INT8 cambia en el edge
    informe = ce.contrastar(
        corrida("raspberry", "aarch64", edge_filas), corrida("laptop", "AMD64", FILAS), "p" * 64
    )
    assert informe["ok"], fallidas(informe["comprobaciones"])
    int8 = informe["predicciones"]["int8"]
    assert int8["distintas_edge_laptop"] == [{"id": "v0", "edge": "person", "laptop": "cat"}]
    assert int8["max_dif_logit_edge_laptop"] == 1.0
    assert informe["int8_igual_a_referencia"] == {"edge": 9, "laptop": 10, "entradas": 10}


def test_contraste_rechaza_tensor_distinto_otra_maquina_y_otro_preprocesamiento():
    distinto = copy.deepcopy(FILAS)
    distinto[3]["tensor_sha256"] = "otro"
    informe = ce.contrastar(
        corrida("raspberry", "aarch64", distinto), corrida("laptop", "AMD64", FILAS), "p" * 64
    )
    assert fallidas(informe["comprobaciones"]) == {"tensor.bit_a_bit"}

    informe = ce.contrastar(
        corrida("laptop", "AMD64", FILAS), corrida("laptop", "AMD64", FILAS), "p" * 64
    )
    assert "edge.dispositivo" in fallidas(informe["comprobaciones"])

    informe = ce.contrastar(
        corrida("raspberry", "aarch64", FILAS), corrida("laptop", "AMD64", FILAS), "q" * 64
    )
    assert "identidad" in fallidas(informe["comprobaciones"])


def test_contraste_rechaza_mapeo_de_clases_roto():
    cambiadas = [fila(f["id"], f["tipo"], f["clase"], int8="person") for f in FILAS]
    informe = ce.contrastar(
        corrida("raspberry", "aarch64", cambiadas), corrida("laptop", "AMD64", FILAS), "p" * 64
    )
    assert "clases.mapeo" in fallidas(informe["comprobaciones"])


@pytest.mark.skipif(
    not (ce.EVIDENCIA / "raspberry" / "resultados.json").is_file(), reason="sin corrida del edge"
)
def test_la_evidencia_de_la_raspberry_se_contrasta_con_la_laptop():
    """Lo versionado en evidencias/VAL-07/: preprocesamiento identico y mapeo de clases."""
    import hashlib

    informe = ce.contrastar(
        ce.leer_corrida(ce.EVIDENCIA / "raspberry"),
        ce.leer_corrida(ce.EVIDENCIA / "laptop"),
        hashlib.sha256(ce.PREPROCESAR.read_bytes()).hexdigest(),
    )
    assert informe["ok"], fallidas(informe["comprobaciones"])
    assert informe["predicciones"]["fp32"]["distintas_edge_laptop"] == []
    assert informe["predicciones"]["int8_referencia"]["distintas_edge_laptop"] == []
    h = informe["int8_igual_a_referencia"]
    assert h["edge"] == h["entradas"] == 295
