"""Comparacion de recursos y calidad en el edge (VAL-06, #18): `validacion/recursos.py`."""

from __future__ import annotations

import csv
import importlib.util
import io
import json
import random
import statistics
import sys
from fractions import Fraction
from pathlib import Path

import pytest

VALIDACION = Path(__file__).resolve().parents[1] / "validacion"
sys.path.insert(0, str(VALIDACION))
_spec = importlib.util.spec_from_file_location("recursos", VALIDACION / "recursos.py")
rec = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = rec
_spec.loader.exec_module(rec)


def test_percentil_por_interpolacion_lineal_a_mano():
    assert rec.percentil([4.0, 1.0, 3.0, 2.0], 50) == 2.5  # h = 1.5
    assert rec.percentil([1.0, 2.0, 3.0, 4.0], 95) == pytest.approx(3.85)  # h = 2.85
    assert rec.percentil([7.0], 95) == 7.0
    assert rec.percentil([1.0, 2.0], 100) == 2.0
    with pytest.raises(ValueError):
        rec.percentil([], 50)


def test_percentil_igual_a_statistics_inclusive():
    azar = random.Random(7)
    for n in (100, 101, 200, 333):
        valores = [azar.uniform(100, 200) for _ in range(n)]
        cuantiles = statistics.quantiles(valores, n=100, method="inclusive")
        assert rec.percentil(valores, 50) == pytest.approx(cuantiles[49], abs=1e-12)
        assert rec.percentil(valores, 95) == pytest.approx(cuantiles[94], abs=1e-12)


def filas_benchmark(modelo: str, medidas: list[float], invalidas: int = 0) -> list[dict]:
    filas = [
        {
            "modelo": modelo,
            "fase": "calentamiento",
            "valido": "True",
            "ms_total": "999",
            "ms_preprocesamiento": "1",
            "ms_inferencia": "1",
        }
        for _ in range(10)
    ]
    filas += [
        {
            "modelo": modelo,
            "fase": "medicion",
            "valido": "True",
            "ms_total": str(m),
            "ms_preprocesamiento": "1",
            "ms_inferencia": str(m - 1),
        }
        for m in medidas
    ]
    filas += [
        {
            "modelo": modelo,
            "fase": "medicion",
            "valido": "False",
            "ms_total": "",
            "ms_preprocesamiento": "",
            "ms_inferencia": "",
        }
        for _ in range(invalidas)
    ]
    return filas


def test_latencia_excluye_calentamientos_e_invalidas():
    filas = filas_benchmark("int8", [float(x) for x in range(1, 101)], invalidas=3)
    lat = rec.latencia(filas, "int8")
    assert lat["mediciones_validas"] == 100
    assert lat["calentamientos_excluidos"] == 10
    assert lat["ms_total"]["max"] == 100.0  # los 999 ms de calentamiento no cuentan
    assert lat["ms_total"]["p50"] == 50.5


def test_reduccion_exacta_con_enteros():
    assert rec.reduccion(44783563, 11295280) == Fraction(44783563 - 11295280, 44783563) * 100
    assert rec.reduccion(200, 100) == 50
    assert rec.reduccion(190.0, 114.0) == pytest.approx(40.0)


def registro_linaje_benchmark(int8_dispositivo: str = "b" * 64):
    registro = {
        "entrada": {"bytes": 1000, "sha256": "p" * 64},
        "salidas": {
            "fp32": {"bytes": 990, "sha256": "f" * 64},
            "int8": {"bytes": 250, "sha256": "b" * 64},
        },
    }
    linaje = {
        "ficha": {
            "publicacion": {
                "objetos": {
                    "modelos/clasificador-p3/1.0.0/model.pt": {"bytes": 1000, "sha256": "p" * 64},
                    "x/model_fp32.onnx": {"bytes": 990, "sha256": "f" * 64},
                    "x/model_int8.onnx": {"bytes": 250, "sha256": "b" * 64},
                }
            }
        }
    }
    benchmark = {
        "modelos": {
            "fp32": {"bytes": 990, "sha256": "f" * 64, "pico_memoria_mb": 180.0},
            "int8": {"bytes": 250, "sha256": int8_dispositivo, "pico_memoria_mb": 110.0},
        }
    }
    return registro, linaje, benchmark


def test_tamanos_coinciden_en_las_tres_fuentes_o_se_rechazan():
    tamano, problemas = rec.tamanos(*registro_linaje_benchmark())
    assert problemas == []
    assert tamano["model_int8.onnx"]["fuentes_coincidentes"] == [
        "raspberry_val05",
        "registro_conversion",
        "s3_val01",
    ]
    _, problemas = rec.tamanos(*registro_linaje_benchmark(int8_dispositivo="c" * 64))
    assert len(problemas) == 1 and "model_int8.onnx" in problemas[0]


@pytest.mark.parametrize(("int8_max", "sin_solape"), [(150.0, True), (195.0, False)])
def test_aceleracion_solo_si_las_distribuciones_no_se_solapan(int8_max, sin_solape):
    registro, linaje, benchmark = registro_linaje_benchmark()
    tamano, _ = rec.tamanos(registro, linaje, benchmark)
    lat = {
        "fp32": rec.latencia(
            filas_benchmark("fp32", [190.0 + i / 100 for i in range(100)]), "fp32"
        ),
        "int8": rec.latencia(filas_benchmark("int8", [114.0] * 99 + [int8_max]), "int8"),
    }
    cal = {"caida_accuracy_pp": 1.0, "accuracy": {}, "f1_macro": {}}
    comparacion = rec.comparar(tamano, lat, benchmark, cal)
    assert comparacion["latencia_edge"]["distribuciones_sin_solape"] is sin_solape
    assert comparacion["tamano"]["reduccion_vs_model_pt_pct"] == 75


@pytest.mark.skipif(not rec.JSON_SALIDA.is_file(), reason="sin evidencia generada")
def test_la_evidencia_versionada_se_recalcula_desde_los_tiempos_crudos():
    """La verificacion del issue: p50/p95 directamente desde el CSV de la Raspberry."""
    evidencia = json.loads(rec.JSON_SALIDA.read_text("utf-8"))
    filas = list(csv.DictReader(io.StringIO((rec.vb.EVIDENCIA / "tiempos.csv").read_text("utf-8"))))
    for modelo in ("fp32", "int8"):
        assert rec.latencia(filas, modelo) == evidencia["latencia_edge"][modelo]
        assert evidencia["latencia_edge"][modelo]["mediciones_validas"] >= 100
        assert evidencia["latencia_edge"][modelo]["calentamientos_excluidos"] >= 10
    comparacion = evidencia["comparacion"]
    assert comparacion["latencia_edge"]["distribuciones_sin_solape"] is True
    assert comparacion["tamano"]["reduccion_vs_model_pt_pct"] == pytest.approx(
        float(Fraction(44783563 - 11295280, 44783563) * 100)
    )
    assert comparacion["calidad"]["particion"] == "val"
    assert comparacion["calidad"]["cumple_2pp"] is True
    assert evidencia["dispositivo"]["arquitectura"] == "aarch64"
