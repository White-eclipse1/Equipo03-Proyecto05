"""Benchmark en el edge (VAL-05, #17): `edge/benchmark.py` y `validacion/verificar_benchmark.py`.

Sin onnxruntime ni modelos: el runtime se sustituye por una funcion falsa. Estas pruebas
no sustituyen la medicion fisica en la Raspberry.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
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


bench = cargar("benchmark_edge", PROYECTO4 / "edge" / "benchmark.py")
ver = cargar("verificar_benchmark", PROYECTO4 / "validacion" / "verificar_benchmark.py")
REGISTRO = json.loads((PROYECTO4 / "modelo/registros/registro_conversion.json").read_text("utf-8"))


def jpeg(color: tuple[int, int, int]) -> bytes:
    salida = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(salida, format="JPEG")
    return salida.getvalue()


IMAGENES = [
    {"nombre": f"{c}/x.jpg", "datos": jpeg(color)}
    for c, color in (("cat", (200, 0, 0)), ("dog", (0, 200, 0)), ("person", (0, 0, 200)))
]


def ejecutar_falso(tensor: np.ndarray) -> np.ndarray:
    """Logits que dependen de la imagen: predice el canal con mas intensidad."""
    assert tensor.shape == (1, 3, 224, 224) and tensor.dtype == np.float32
    return tensor.mean(axis=(2, 3))


def test_identidad_de_los_modelos_es_la_de_la_conversion():
    for modelo in ("int8", "fp32"):
        assert bench.MODELOS[modelo]["sha256"] == REGISTRO["salidas"][modelo]["sha256"]
        assert bench.MODELOS[modelo]["archivo"] == REGISTRO["salidas"][modelo]["archivo"]
    assert bench.MODELOS["int8"]["version"] == REGISTRO["configuracion"]["variante"]["version"]


def test_calentamientos_marcados_antes_de_las_mediciones():
    filas = bench.medir("int8", ejecutar_falso, IMAGENES, 10, 100, lambda: 51.5)
    assert [f["fase"] for f in filas] == ["calentamiento"] * 10 + ["medicion"] * 100
    assert [f["indice"] for f in filas] == list(range(110))
    assert filas[10]["repeticion"] == 0 and filas[-1]["repeticion"] == 99
    # Recorre las imagenes en orden fijo y la prediccion reacciona a cada una.
    assert [f["imagen"] for f in filas[:4]] == [
        "cat/x.jpg",
        "dog/x.jpg",
        "person/x.jpg",
        "cat/x.jpg",
    ]
    assert [f["clase_predicha"] for f in filas[:3]] == ["cat", "dog", "person"]
    for f in filas:
        assert f["valido"] and f["ms_total"] > 0 and f["temperatura_c"] == 51.5
        assert f["ms_preprocesamiento"] + f["ms_inferencia"] <= f["ms_total"]


def test_una_repeticion_que_falla_queda_registrada_como_invalida():
    llamadas = []

    def falla_una_vez(tensor):
        llamadas.append(1)
        if len(llamadas) == 12:
            raise RuntimeError("fallo del runtime")
        return ejecutar_falso(tensor)

    filas = bench.medir("int8", falla_una_vez, IMAGENES, 10, 100, lambda: None)
    invalidas = [f for f in filas if not f["valido"]]
    assert len(invalidas) == 1 and "RuntimeError" in invalidas[0]["error"]
    resumen = bench.resumen_modelo({"estado": "ok", "filas": filas})
    assert (resumen["mediciones_validas"], resumen["cumple_minimos"]) == (99, False)


def test_rechaza_menos_de_los_minimos():
    with pytest.raises(SystemExit, match="Minimo"):
        bench.main(["--repeticiones", "99"])
    with pytest.raises(SystemExit, match="Minimo"):
        bench.main(["--calentamientos", "9"])


def test_condiciones_no_fallan_fuera_de_la_raspberry():
    estado = bench.condiciones()
    assert "temperatura_c" in estado and "cpufreq" in estado
    assert bench.hardware()["nucleos"]


def evidencia(modelos: dict, arquitectura: str = "aarch64") -> tuple[bytes, dict]:
    """benchmark.json y tiempos.csv como los escribe la Raspberry."""
    resultados = [{"modelo": m, **datos} for m, datos in modelos.items()]
    tiempos = bench.tiempos_csv(resultados)
    return tiempos, {
        "hardware": {
            "modelo_dispositivo": "Raspberry Pi 4 Model B Rev 1.5",
            "arquitectura": arquitectura,
            "sistema_operativo": "Debian GNU/Linux 13 (trixie)",
        },
        "runtime": {"onnxruntime": "1.31.0"},
        "entrada": {"forma": [1, 3, 224, 224]},
        "tiempos": {"sha256": hashlib.sha256(tiempos).hexdigest()},
        "modelos": {
            r["modelo"]: {
                **bench.MODELOS[r["modelo"]],
                **{k: v for k, v in r.items() if k not in ("filas", "modelo")},
            }
            for r in resultados
        },
    }


def medido(modelo: str, calentamientos: int = 10, repeticiones: int = 100) -> dict:
    return {
        "estado": "ok",
        "sha256": bench.MODELOS[modelo]["sha256"],
        "filas": bench.medir(modelo, ejecutar_falso, IMAGENES, calentamientos, repeticiones),
    }


def fallidas(informe: dict) -> set[str]:
    return {c["id"] for c in informe["comprobaciones"] if not c["ok"]}


def test_evidencia_completa_de_los_dos_modelos_se_verifica():
    tiempos, datos = evidencia({"int8": medido("int8"), "fp32": medido("fp32")})
    informe = ver.verificar(tiempos, datos, REGISTRO)
    assert informe["ok"], fallidas(informe)
    filas = list(csv.DictReader(io.StringIO(tiempos.decode())))
    assert len(filas) == 220 and float(filas[0]["ms_total"]) > 0


def test_original_que_no_corre_con_su_error_registrado_es_evidencia_valida():
    error = {"estado": "error", "error": "MemoryError: no cabe en la RAM", "filas": []}
    tiempos, datos = evidencia({"int8": medido("int8"), "fp32": error})
    informe = ver.verificar(tiempos, datos, REGISTRO)
    assert informe["ok"], fallidas(informe)
    assert "fp32.incompatibilidad" in {c["id"] for c in informe["comprobaciones"]}


@pytest.mark.parametrize(
    ("cambio", "falla"),
    [
        ({"calentamientos": 9}, "int8.conteos"),
        ({"repeticiones": 99}, "int8.conteos"),
    ],
)
def test_detecta_conteos_insuficientes(cambio, falla):
    tiempos, datos = evidencia({"int8": medido("int8", **cambio)})
    assert falla in fallidas(ver.verificar(tiempos, datos, REGISTRO))


def test_detecta_otro_modelo_csv_alterado_y_corrida_fuera_del_dispositivo():
    otro = medido("int8") | {"sha256": "0" * 64}
    tiempos, datos = evidencia({"int8": otro})
    assert "int8.identidad" in fallidas(ver.verificar(tiempos, datos, REGISTRO))

    tiempos, datos = evidencia({"int8": medido("int8")})
    alterado = tiempos.replace(b"True", b"False", 1)
    assert "tiempos.sha256" in fallidas(ver.verificar(alterado, datos, REGISTRO))

    tiempos, datos = evidencia({"int8": medido("int8")}, arquitectura="AMD64")
    assert "dispositivo" in fallidas(ver.verificar(tiempos, datos, REGISTRO))

    sin_int8 = {"estado": "error", "error": "no cargo", "filas": []}
    tiempos, datos = evidencia({"int8": sin_int8})
    assert "int8.medido" in fallidas(ver.verificar(tiempos, datos, REGISTRO))


def test_detecta_preprocesamiento_distinto_al_del_repositorio():
    tiempos, datos = evidencia({"int8": medido("int8")})
    datos["codigo"] = {"preprocesar.py": "a" * 64}
    igual = ver.verificar(tiempos, datos, REGISTRO, "a" * 64)
    assert igual["ok"], fallidas(igual)
    assert "preprocesamiento" in {c["id"] for c in igual["comprobaciones"]}
    assert fallidas(ver.verificar(tiempos, datos, REGISTRO, "b" * 64)) == {"preprocesamiento"}


@pytest.mark.skipif(not (ver.EVIDENCIA / "benchmark.json").is_file(), reason="sin evidencia")
def test_la_evidencia_de_la_raspberry_se_verifica():
    """La corrida fisica versionada en evidencias/VAL-05/ (rubrica 3.2)."""
    datos = json.loads((ver.EVIDENCIA / "benchmark.json").read_text("utf-8"))
    informe = ver.verificar(
        (ver.EVIDENCIA / "tiempos.csv").read_bytes(),
        datos,
        REGISTRO,
        hashlib.sha256(ver.PREPROCESAR.read_bytes()).hexdigest(),
    )
    assert informe["ok"], fallidas(informe)
    assert datos["hardware"]["modelo_dispositivo"].startswith("Raspberry Pi 4")
    for modelo in ("int8", "fp32"):
        resumen = datos["modelos"][modelo]["resumen"]
        assert resumen["calentamientos"] >= 10 and resumen["mediciones_validas"] >= 100
