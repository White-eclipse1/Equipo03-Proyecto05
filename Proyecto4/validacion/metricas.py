"""Metricas de calidad del original y del optimizado en validacion (VAL-04, #14; rubrica 1.3).

Se calculan **exclusivamente** desde el archivo de predicciones por muestra de VAL-03
(`validacion/resultados/predicciones_val.csv`), despues de verificarlo contra el
manifiesto con `verificar_predicciones.py`. Solo usa la biblioteca estandar: cualquiera
puede recalcularlas.

Para cada modelo: accuracy, F1 macro, y precision, recall, F1 y support por clase
(`cat`, `dog`, `person`), mas la matriz de confusion. La caida de accuracy se calcula en
puntos porcentuales con fracciones exactas (`fractions.Fraction`) y se compara con el
limite de 2 pp **sin redondear**. Los errores relevantes son las muestras en que algun
modelo falla o en que los dos no coinciden.

Todas las cifras son de la particion `val` del manifiesto `m-0.1.3-s42-1`. Las del test
del P3 se citan aparte, solo como referencia y sin compararlas.

    cd Proyecto4
    python validacion/metricas.py

Escribe `validacion/resultados/metricas_val.json` y `metricas_val.csv` (tabla antes y
despues) solo si la verificacion previa y las comprobaciones de consistencia pasan.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import sys
from collections import Counter
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from typing import Any

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

import verificar_predicciones as ver  # noqa: E402

RAIZ = AQUI.parent  # Proyecto4/
P3 = RAIZ.parent / "Proyecto3"
JSON_SALIDA = ver.RESULTADOS / "metricas_val.json"
CSV_SALIDA = ver.RESULTADOS / "metricas_val.csv"

MODELOS = ("original", "optimized")
LIMITE_PP = Fraction(2)


def division(a: int | Fraction, b: int | Fraction) -> Fraction:
    """a / b exacta, con 0 cuando b es 0 (precision de una clase que nunca se predice)."""
    return Fraction(a) / Fraction(b) if b else Fraction(0)


def a_json(valor: Any) -> Any:
    """Convierte las fracciones exactas a float solo al escribir (sin redondeo intermedio)."""
    if isinstance(valor, Fraction):
        return float(valor)
    if isinstance(valor, dict):
        return {k: a_json(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [a_json(v) for v in valor]
    return valor


def metricas_modelo(filas: list[dict[str, str]], modelo: str, clases: list[str]) -> dict:
    columna = f"{modelo}_prediction"
    confusion = Counter((f["true_class"], f[columna]) for f in filas)
    por_clase = {}
    for c in clases:
        tp = confusion[(c, c)]
        fp = sum(confusion[(t, c)] for t in clases if t != c)
        fn = sum(confusion[(c, p)] for p in clases if p != c)
        precision, recall = division(tp, tp + fp), division(tp, tp + fn)
        por_clase[c] = {
            "precision": precision,
            "recall": recall,
            "f1": division(2 * precision * recall, precision + recall),
            "support": tp + fn,
            "tp": tp,
            "fp": fp,
            "fn": fn,
        }
    aciertos = sum(confusion[(c, c)] for c in clases)
    return {
        "muestras": len(filas),
        "aciertos": aciertos,
        "accuracy": division(aciertos, len(filas)),
        "accuracy_fraccion": f"{aciertos}/{len(filas)}",
        "f1_macro": sum((x["f1"] for x in por_clase.values()), Fraction(0)) / len(clases),
        "por_clase": por_clase,
        "matriz_confusion": {
            "etiquetas": clases,
            "filas_real_columnas_predicha": [[confusion[(t, p)] for p in clases] for t in clases],
        },
    }


def caida_accuracy(original: dict, optimizado: dict) -> dict[str, Any]:
    """Caida en puntos porcentuales, exacta; se compara con 2 pp sin redondear."""
    n = original["muestras"]
    caida = Fraction(original["aciertos"] - optimizado["aciertos"], n) * 100
    return {
        "pp": caida,
        "pp_fraccion": f"{caida.numerator}/{caida.denominator}",
        "limite_pp": LIMITE_PP,
        "cumple": caida <= LIMITE_PP,
        "nota": "(aciertos_original - aciertos_optimizado) / muestras * 100, con fracciones "
        "exactas; la comparacion con el limite no redondea",
    }


def cambios_por_clase(original: dict, optimizado: dict, clases: list[str]) -> dict[str, Any]:
    """Diferencia optimizado - original por clase, en puntos porcentuales."""
    return {
        c: {
            metrica: (optimizado["por_clase"][c][metrica] - original["por_clase"][c][metrica]) * 100
            for metrica in ("precision", "recall", "f1")
        }
        for c in clases
    }


def errores_relevantes(
    filas: list[dict[str, str]], referencia: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    """Muestras en que algun modelo falla o los dos no coinciden, con su tipo."""
    errores = []
    for f in filas:
        real, orig, opt = f["true_class"], f["original_prediction"], f["optimized_prediction"]
        if orig == real == opt:
            continue
        if orig == real:
            tipo = "regresion"  # el original acierta y el optimizado no
        elif opt == real:
            tipo = "correccion"  # el original falla y el optimizado acierta
        else:
            tipo = "ambos_fallan"
        error = {
            "sample_id": f["sample_id"],
            "tipo": tipo,
            "true_class": real,
            "original_prediction": orig,
            "optimized_prediction": opt,
            "prob_original_real": float(f[f"prob_original_{real}"]),
            "prob_original_predicha": float(f[f"prob_original_{orig}"]),
            "prob_optimized_real": float(f[f"prob_optimized_{real}"]),
            "prob_optimized_predicha": float(f[f"prob_optimized_{opt}"]),
        }
        if referencia is not None:
            error["int8_referencia_prediction_val02"] = referencia.get(f["sample_id"])
        errores.append(error)
    return errores


def referencia_val02(fuente: dict[str, Any]) -> dict[str, str] | None:
    """Columna `int8_referencia` de la comparacion de la que salio VAL-03 (VAL-02 o el edge).

    Solo si el archivo es el que registra VAL-03 (SHA-256). No interviene en ninguna
    metrica: solo da contexto a los errores (kernel entero fusionado contra aritmetica de
    referencia del grafo).
    """
    ruta = RAIZ / fuente["comparacion_csv"]["archivo"]
    if not ruta.is_file():
        return None
    datos = ruta.read_bytes()
    if hashlib.sha256(datos).hexdigest() != fuente["comparacion_csv"]["sha256"]:
        return None
    filas = csv.DictReader(io.StringIO(datos.decode("utf-8")))
    return {f["sample_id"]: f["int8_referencia_prediction"] for f in filas}


def test_p3() -> dict[str, Any] | None:
    """Cifras de test del P3 para el original, solo como referencia (otra particion)."""
    seleccion = json.loads((P3 / "docs" / "selection.json").read_text(encoding="utf-8"))
    ruta = P3 / "reports" / "evaluation" / seleccion["run_id"] / "metrics.json"
    if not ruta.is_file():
        return None
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    return {
        "particion": "test del P3 (145 muestras): NO es la validacion de VAL-04",
        "fuente": ruta.relative_to(RAIZ.parent).as_posix(),
        "modelo": "original (solo se evaluo el original en test)",
        "accuracy": datos["accuracy"],
        "f1_macro": datos["f1_macro"],
        "uso": "solo referencia; no se compara con las cifras de val ni se usa para decidir",
    }


def tabla_antes_despues(metricas: dict[str, Any], clases: list[str]) -> bytes:
    """CSV: una fila por metrica con original, optimizado y diferencia en pp."""
    orig, opt = metricas["modelos"]["original"], metricas["modelos"]["optimized"]
    filas = [
        ("global", "accuracy", orig["accuracy"], opt["accuracy"]),
        ("global", "f1_macro", orig["f1_macro"], opt["f1_macro"]),
    ]
    for c in clases:
        for m in ("precision", "recall", "f1"):
            filas.append((c, m, orig["por_clase"][c][m], opt["por_clase"][c][m]))
        filas.append(
            (c, "support", orig["por_clase"][c]["support"], opt["por_clase"][c]["support"])
        )
    salida = io.StringIO()
    escritor = csv.writer(salida, lineterminator="\n")
    escritor.writerow(["ambito", "metrica", "original", "optimizado", "diferencia_pp"])
    for ambito, metrica, a, b in filas:
        diferencia = "" if metrica == "support" else repr(float((b - a) * 100))
        escritor.writerow([ambito, metrica, repr(a_json(a)), repr(a_json(b)), diferencia])
    return salida.getvalue().encode("utf-8")


def calcular(
    predicciones: bytes, metadatos: dict[str, Any], referencia: dict[str, str] | None = None
) -> dict[str, Any]:
    filas = list(csv.DictReader(io.StringIO(predicciones.decode("utf-8"))))
    clases = metadatos["clases"]
    modelos = {m: metricas_modelo(filas, m, clases) for m in MODELOS}
    return {
        "particion": "val",
        "clases": clases,
        "modelos": modelos,
        "caida_accuracy": caida_accuracy(modelos["original"], modelos["optimized"]),
        "cambio_por_clase_pp": cambios_por_clase(modelos["original"], modelos["optimized"], clases),
        "errores_relevantes": errores_relevantes(filas, referencia),
    }


def consistencia(metricas: dict[str, Any], metadatos: dict[str, Any]) -> list[str]:
    """Contrastes con lo que declara VAL-03 (vacia si todo cuadra)."""
    problemas = []
    resumen = metadatos["resumen"]
    for modelo, clave in (("original", "aciertos_original"), ("optimized", "aciertos_optimizado")):
        m = metricas["modelos"][modelo]
        if m["aciertos"] != resumen[clave]:
            problemas.append(f"{modelo}: {m['aciertos']} aciertos; VAL-03 declara {resumen[clave]}")
        if sum(x["support"] for x in m["por_clase"].values()) != m["muestras"]:
            problemas.append(f"{modelo}: el support por clase no suma las muestras")
    faltan = [c for c in ("cat", "dog", "person") if c not in metricas["clases"]]
    if faltan:
        problemas.append(f"clases sin reportar: {faltan}")
    return problemas


def escribir(archivos: dict[Path, bytes]) -> None:
    temporales = {}
    try:
        for destino, contenido in archivos.items():
            temporales[destino] = destino.with_name(f".{destino.name}.tmp")
            temporales[destino].write_bytes(contenido)
        for destino, temporal in temporales.items():
            os.replace(temporal, destino)
    finally:
        for temporal in temporales.values():
            temporal.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--predicciones", type=Path, default=ver.PREDICCIONES)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    predicciones = args.predicciones.read_bytes()
    metadatos = json.loads(args.predicciones.with_suffix(".json").read_text(encoding="utf-8"))
    informe = ver.verificar(
        predicciones,
        metadatos,
        ver.EXTRACTO.read_bytes(),
        json.loads(ver.META.read_text(encoding="utf-8")),
    )
    if not informe["ok"]:
        fallidas = [c["id"] for c in informe["comprobaciones"] if not c["ok"]]
        raise SystemExit(f"FALLA: el archivo de predicciones no se verifica: {fallidas}")

    metricas = calcular(predicciones, metadatos, referencia_val02(metadatos["fuente"]))
    problemas = consistencia(metricas, metadatos)
    if problemas:
        raise SystemExit("FALLA: no se escribio evidencia: " + "; ".join(problemas))

    tabla = tabla_antes_despues(metricas, metricas["clases"])
    evidencia = {
        "schema_version": 1,
        "tarea": "VAL-04 (#14)",
        "generado_en": datetime.now(UTC).isoformat(timespec="seconds"),
        "comando": "python validacion/metricas.py",
        "fuente": {
            "predicciones": args.predicciones.relative_to(RAIZ).as_posix(),
            "sha256": hashlib.sha256(predicciones).hexdigest(),
            "manifest_id": metadatos["manifiesto"]["manifest_id"],
            "verificacion": "verificar_predicciones.verificar: ok",
            "optimizado": metadatos["modelos"]["optimizado"]["maquina"],
        },
        **a_json(metricas),
        "referencia_test_p3": test_p3(),
        "tabla_antes_despues": {
            "archivo": CSV_SALIDA.name,
            "sha256": hashlib.sha256(tabla).hexdigest(),
        },
    }
    escribir(
        {
            CSV_SALIDA: tabla,
            JSON_SALIDA: (json.dumps(evidencia, ensure_ascii=False, indent=2) + "\n").encode(),
        }
    )

    for modelo in MODELOS:
        m = metricas["modelos"][modelo]
        print(
            f"{modelo:9} accuracy {m['accuracy_fraccion']} = {float(m['accuracy']):.6f}  F1 macro "
            f"{float(m['f1_macro']):.6f}"
        )
    caida = metricas["caida_accuracy"]
    pp = float(caida["pp"])
    print(f"caida: {caida['pp_fraccion']} pp = {pp:.6f} pp; <= 2 pp: {caida['cumple']}")
    print(f"errores relevantes: {len(metricas['errores_relevantes'])}")


if __name__ == "__main__":
    main()
