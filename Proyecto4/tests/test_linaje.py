"""Verificacion del linaje del modelo (VAL-01, #1; M1): `modelo/verificar_linaje.py`."""

from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "modelo" / "verificar_linaje.py"
_spec = importlib.util.spec_from_file_location("verificar_linaje", SCRIPT)
linaje = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = linaje  # dataclasses busca el modulo ahi
_spec.loader.exec_module(linaje)

COMPROBACIONES_REGISTROS = {
    "origen.version",
    "origen.run_id",
    "origen.checkpoint",
    "origen.sha256_registros",
    "variante.version",
    "variante.sha256_registros",
    "clases.orden",
    "preprocesamiento",
    "conversion.referencia",
    "conversion.entrada_salida",
    "paquete.reconstruido",
    "calibracion.train",
    "origen.no_externo",
}


def correr() -> tuple[dict[str, str], dict]:
    c = linaje.Comprobaciones()
    ctx = linaje.comprobar_registros(c)
    return {x.id: x.estado for x in c}, ctx


def fallidas(estados: dict[str, str]) -> set[str]:
    return {id_ for id_, estado in estados.items() if estado == linaje.FALLA}


def alterar(monkeypatch: pytest.MonkeyPatch, lector: str, nombre: str, cambio) -> None:
    """Aplica `cambio` a lo que devuelve `linaje.<lector>` para el archivo `nombre`."""
    original = getattr(linaje, lector)

    def leer(ruta: Path):
        datos = original(ruta)
        if ruta.name == nombre:
            datos = copy.deepcopy(datos)
            datos = cambio(datos) or datos
        return datos

    monkeypatch.setattr(linaje, lector, leer)


def test_linaje_en_registros_completo_y_sin_fallas():
    estados, ctx = correr()
    assert set(estados) == COMPROBACIONES_REGISTROS
    assert fallidas(estados) == set()
    ficha = ctx["ficha"]
    assert ficha["original"]["version"] == "1.0.0"
    assert ficha["original"]["run_id"] == "9f9b62c202f0446a8a4b411a10321eff"
    assert ficha["variante"]["version"] == "1.0.0-int8-e05.1"
    assert ficha["class_map"] == {"0": "cat", "1": "dog", "2": "person"}
    assert ficha["preprocesamiento"]["image_size"] == 224


def test_detecta_variante_con_otro_hash(monkeypatch):
    def cambio(registro):
        registro["salidas"]["int8"]["sha256"] = "0" * 64

    alterar(monkeypatch, "leer_json", "registro_conversion.json", cambio)
    estados, _ = correr()
    # El paquete declara el SHA-256 de la variante: tampoco se reconstruye.
    assert {"variante.sha256_registros", "paquete.reconstruido"} <= fallidas(estados)


def test_detecta_orden_de_clases_distinto(monkeypatch):
    def cambio(clases):
        clases["classes"][0]["class_index"], clases["classes"][1]["class_index"] = 1, 0

    alterar(monkeypatch, "leer_yaml", "classes.yaml", cambio)
    estados, _ = correr()
    assert {"clases.orden", "paquete.reconstruido"} <= fallidas(estados)


def test_detecta_origen_distinto_al_seleccionado_en_p3(monkeypatch):
    def cambio(seleccion):
        seleccion["run_id"] = "otro-run"
        seleccion["checkpoint_sha256"] = "f" * 64

    alterar(monkeypatch, "leer_json", "selection.json", cambio)
    estados, _ = correr()
    assert {"origen.run_id", "origen.sha256_registros"} <= fallidas(estados)


def test_detecta_preprocesamiento_distinto_en_el_edge(monkeypatch):
    def cambio(valores):
        valores["TAMANO"] = 160

    alterar(monkeypatch, "constantes", "preprocesar.py", cambio)
    estados, _ = correr()
    assert "preprocesamiento" in fallidas(estados)


def test_detecta_calibracion_con_muestra_de_test(monkeypatch):
    test_csv = linaje.P3 / "reports" / "evaluation"
    test_csv = next(test_csv.glob("*/predictions_test.csv"))
    id_test = linaje.leer_texto(test_csv).splitlines()[1].split(",", 1)[0]

    def cambio(texto):
        lineas = texto.splitlines()
        lineas[0] = lineas[0].replace(lineas[0].split('"')[3], id_test)
        return "\n".join(lineas) + "\n"

    alterar(monkeypatch, "leer_texto", "calibracion_ids.jsonl", cambio)
    estados, _ = correr()
    assert "calibracion.train" in fallidas(estados)


class CuerpoFalso:
    def __init__(self, datos: bytes):
        self.datos = datos

    def iter_chunks(self, tamano: int):
        for inicio in range(0, len(self.datos), tamano):
            yield self.datos[inicio : inicio + tamano]


class S3Falso:
    def __init__(self, objetos: dict[str, bytes]):
        self.objetos = objetos

    def get_object(self, Bucket: str, Key: str):  # noqa: N803 (firma de boto3)
        return {"Body": CuerpoFalso(self.objetos[Key]), "VersionId": f"v-{Key}", "Metadata": {}}


def test_s3_detecta_binarios_sustituidos():
    """Registros y paquete correctos pero pesos ajenos: fallan solo los binarios."""
    c = linaje.Comprobaciones()
    ctx = linaje.comprobar_registros(c)
    salidas = ctx["registro"]["salidas"]
    edge = f"{linaje.PREFIJO_EDGE}/{linaje.VARIANTE}"
    objetos = {
        f"{linaje.PREFIJO_P3}/{linaje.VERSION_P3}/model.pt": b"pesos de otro modelo",
        f"{edge}/{salidas['int8']['archivo']}": b"onnx ajeno",
        f"{edge}/{salidas['fp32']['archivo']}": b"onnx ajeno",
        f"{edge}/model_package.json": ctx["paquete"],
        f"{edge}/registro_conversion.json": (
            linaje.REGISTROS / "registro_conversion.json"
        ).read_bytes(),
        f"{edge}/calibracion_ids.jsonl": (linaje.REGISTROS / "calibracion_ids.jsonl").read_bytes(),
    }

    linaje.comprobar_s3(c, ctx, S3Falso(objetos), "bucket-de-prueba")
    estados = {x.id: x.estado for x in c}
    assert fallidas(estados) == {"s3.model.pt", "s3.model_int8.onnx", "s3.model_fp32.onnx"}
    for id_ in (
        "s3.model_package.json",
        "s3.registro_conversion.json",
        "s3.calibracion_ids.jsonl",
        "s3.paquete_contenido",
    ):
        assert estados[id_] == linaje.OK
    assert ctx["ficha"]["publicacion"]["bucket"] == "bucket-de-prueba"
