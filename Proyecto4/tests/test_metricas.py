"""Metricas desde las predicciones por muestra (VAL-04, #14): `validacion/metricas.py`."""

from __future__ import annotations

import csv
import importlib.util
import io
import json
import sys
from fractions import Fraction
from pathlib import Path

import pytest

VALIDACION = Path(__file__).resolve().parents[1] / "validacion"
sys.path.insert(0, str(VALIDACION))
_spec = importlib.util.spec_from_file_location("metricas", VALIDACION / "metricas.py")
met = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = met
_spec.loader.exec_module(met)

CLASES = ["cat", "dog", "person"]


def predicciones(casos: list[tuple[str, str, str]]) -> bytes:
    """CSV con el formato de VAL-03 a partir de (real, original, optimizado)."""
    salida = io.StringIO()
    columnas = ["sample_id", "true_class", "original_prediction", "optimized_prediction"]
    columnas += [f"prob_{m}_{c}" for m in ("original", "optimized") for c in CLASES]
    escritor = csv.DictWriter(salida, fieldnames=columnas, lineterminator="\n")
    escritor.writeheader()
    for i, (real, orig, opt) in enumerate(casos):
        fila = {"sample_id": f"s{i}", "true_class": real}
        fila["original_prediction"], fila["optimized_prediction"] = orig, opt
        for m, pred in (("original", orig), ("optimized", opt)):
            for c in CLASES:
                fila[f"prob_{m}_{c}"] = "0.8" if c == pred else "0.1"
        escritor.writerow(fila)
    return salida.getvalue().encode()


def test_metricas_a_mano():
    casos = [
        ("cat", "cat", "cat"),
        ("cat", "cat", "dog"),
        ("dog", "dog", "dog"),
        ("dog", "cat", "dog"),
        ("person", "person", "person"),
    ]
    m = met.calcular(predicciones(casos), {"clases": CLASES})
    orig, opt = m["modelos"]["original"], m["modelos"]["optimized"]

    assert orig["aciertos"] == 4 and orig["accuracy"] == Fraction(4, 5)
    # original: cat tp=2 fp=1 fn=0 -> P=2/3 R=1 F1=4/5; dog tp=1 fp=0 fn=1 -> F1=2/3
    assert orig["por_clase"]["cat"]["precision"] == Fraction(2, 3)
    assert orig["por_clase"]["cat"]["f1"] == Fraction(4, 5)
    assert orig["por_clase"]["dog"]["f1"] == Fraction(2, 3)
    assert orig["f1_macro"] == (Fraction(4, 5) + Fraction(2, 3) + 1) / 3
    assert [orig["por_clase"][c]["support"] for c in CLASES] == [2, 2, 1]
    assert orig["matriz_confusion"]["filas_real_columnas_predicha"] == [
        [2, 0, 0],
        [1, 1, 0],
        [0, 0, 1],
    ]
    assert opt["aciertos"] == 4
    assert m["caida_accuracy"]["pp"] == 0 and m["caida_accuracy"]["cumple"]


def test_clase_nunca_predicha_da_cero_sin_dividir_entre_cero():
    casos = [("cat", "dog", "dog"), ("dog", "dog", "dog"), ("person", "person", "person")]
    m = met.calcular(predicciones(casos), {"clases": CLASES})
    gato = m["modelos"]["original"]["por_clase"]["cat"]
    assert (gato["precision"], gato["recall"], gato["f1"]) == (0, 0, 0)


@pytest.mark.parametrize(
    ("aciertos_original", "aciertos_optimizado", "muestras", "cumple", "fraccion"),
    [
        (100, 98, 100, True, "2"),  # justo en el limite: cumple
        (100, 97, 100, False, "3"),
        (291, 288, 292, True, "75/73"),  # INT8 en la laptop (VAL-02): 1.0273... pp
        (291, 290, 292, True, "25/73"),  # INT8 en la Raspberry (VAL-07): 0.3424... pp
        # 2.0004 pp: redondeado a 2 decimales seria 2.00 y "cumpliria"; exacto, no cumple.
        (4999, 4899, 4999, False, "10000/4999"),
    ],
)
def test_caida_exacta_sin_redondear(
    aciertos_original, aciertos_optimizado, muestras, cumple, fraccion
):
    caida = met.caida_accuracy(
        {"muestras": muestras, "aciertos": aciertos_original},
        {"muestras": muestras, "aciertos": aciertos_optimizado},
    )
    assert Fraction(caida["pp_fraccion"]) == Fraction(fraccion)
    assert caida["cumple"] is cumple


def test_tipos_de_error_y_contexto_de_referencia():
    casos = [
        ("cat", "cat", "person"),  # regresion
        ("cat", "dog", "cat"),  # correccion
        ("dog", "cat", "person"),  # ambos fallan
        ("dog", "dog", "dog"),  # no es error
    ]
    filas = list(csv.DictReader(io.StringIO(predicciones(casos).decode())))
    errores = met.errores_relevantes(filas, {"s0": "cat"})
    assert [(e["sample_id"], e["tipo"]) for e in errores] == [
        ("s0", "regresion"),
        ("s1", "correccion"),
        ("s2", "ambos_fallan"),
    ]
    assert errores[0]["prob_optimized_predicha"] == 0.8
    assert errores[0]["int8_referencia_prediction_val02"] == "cat"
    assert errores[1]["int8_referencia_prediction_val02"] is None


def test_consistencia_con_lo_declarado_en_val03():
    casos = [("cat", "cat", "cat"), ("dog", "dog", "cat"), ("person", "person", "person")]
    m = met.calcular(predicciones(casos), {"clases": CLASES})
    bien = {"resumen": {"aciertos_original": 3, "aciertos_optimizado": 2}}
    assert met.consistencia(m, bien) == []
    mal = {"resumen": {"aciertos_original": 3, "aciertos_optimizado": 3}}
    assert len(met.consistencia(m, mal)) == 1


def test_tabla_antes_despues_reporta_cada_clase_y_diferencias_exactas():
    casos = [("cat", "cat", "cat"), ("dog", "dog", "cat"), ("person", "person", "person")]
    m = met.calcular(predicciones(casos), {"clases": CLASES})
    filas = list(csv.DictReader(io.StringIO(met.tabla_antes_despues(m, CLASES).decode())))
    ambitos = {f["ambito"] for f in filas}
    assert ambitos == {"global", "cat", "dog", "person"}
    accuracy = next(f for f in filas if f["metrica"] == "accuracy")
    assert float(accuracy["diferencia_pp"]) == float(Fraction(-100, 3))


@pytest.mark.skipif(not met.JSON_SALIDA.is_file(), reason="sin evidencia generada")
def test_la_evidencia_versionada_se_recalcula_desde_las_predicciones():
    """Lo que pide la verificacion del issue: todo sale del archivo de predicciones."""
    evidencia = json.loads(met.JSON_SALIDA.read_text("utf-8"))
    predicciones_reales = met.ver.PREDICCIONES.read_bytes()
    metadatos = json.loads(met.ver.PREDICCIONES.with_suffix(".json").read_text("utf-8"))
    recalculado = met.a_json(met.calcular(predicciones_reales, metadatos, None))
    for clave in ("modelos", "caida_accuracy", "cambio_por_clase_pp"):
        assert recalculado[clave] == evidencia[clave], clave
    tabla = met.tabla_antes_despues(met.calcular(predicciones_reales, metadatos), CLASES)
    assert tabla == met.CSV_SALIDA.read_bytes()
    # INT8 medido en la Raspberry (VAL-07/VAL-08): 291 -> 290 aciertos de 292.
    assert evidencia["caida_accuracy"]["pp_fraccion"] == "25/73"
    assert evidencia["caida_accuracy"]["cumple"] is True
    assert evidencia["particion"] == "val"
