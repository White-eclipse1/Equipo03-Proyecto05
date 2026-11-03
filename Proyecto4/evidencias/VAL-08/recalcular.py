"""Recalculo independiente del paquete de evidencia de calidad y recursos (VAL-08, #24).

Usa **solo los archivos de este paquete** y la biblioteca estandar de Python (3.11 o
superior); no importa nada del repositorio, no usa red ni modelos. Desde la carpeta del
paquete:

    python recalcular.py

1. Integridad: el SHA-256 de cada archivo coincide con `SHA256SUMS.txt`.
2. Modelo: identidad del original y del optimizado (version, run_id, archivo, SHA-256,
   bytes) igual en la ficha, el registro de conversion y la verificacion de linaje;
   reduccion de tamano recalculada con fracciones exactas.
3. Validacion: las predicciones por muestra se **reconstruyen desde los datos primarios**
   (probabilidades del original de VAL-02 y logits del INT8 registrados en la Raspberry,
   VAL-07; argmax con el primer indice en caso de empate) y se unen con el manifiesto por
   `sample_id`: sin duplicados ni faltantes, mismas etiquetas. Accuracy, F1 macro, F1 y
   support por clase y caida en pp (fracciones exactas, sin redondear antes de comparar
   con 2 pp), contra lo declarado.
4. Benchmark: desde los tiempos crudos de la Raspberry (VAL-05), calentamientos excluidos,
   al menos 100 mediciones validas por modelo, p50/p95 por interpolacion lineal (tipo 7),
   contra lo declarado; hardware, runtime y condiciones presentes.

Sale con codigo 1 si algo no coincide.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import sys
from collections import Counter
from fractions import Fraction
from pathlib import Path
from typing import Any

AQUI = Path(__file__).resolve().parent
CLASES = ("cat", "dog", "person")
TOLERANCIA = 1e-9


def leer(ruta: str) -> bytes:
    return (AQUI / ruta).read_bytes()


def leer_json(ruta: str) -> Any:
    return json.loads(leer(ruta).decode("utf-8"))


def leer_csv(ruta: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(leer(ruta).decode("utf-8"))))


def argmax(valores: list[float]) -> int:
    """Primer indice del maximo (como numpy.argmax)."""
    return valores.index(max(valores))


def percentil(valores: list[float], p: float) -> float:
    """Interpolacion lineal entre observaciones ordenadas (Hyndman y Fan tipo 7)."""
    x = sorted(valores)
    h = (len(x) - 1) * p / 100
    piso = math.floor(h)
    if piso + 1 >= len(x):
        return x[-1]
    return x[piso] + (h - piso) * (x[piso + 1] - x[piso])


def division(a: int, b: int) -> Fraction:
    return Fraction(a, b) if b else Fraction(0)


def metricas(reales: list[str], predichas: list[str]) -> dict[str, Any]:
    confusion = Counter(zip(reales, predichas, strict=True))
    por_clase = {}
    for c in CLASES:
        tp = confusion[(c, c)]
        fp = sum(confusion[(t, c)] for t in CLASES if t != c)
        fn = sum(confusion[(c, p)] for p in CLASES if p != c)
        precision, recall = division(tp, tp + fp), division(tp, tp + fn)
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else Fraction(0)
        por_clase[c] = {"precision": precision, "recall": recall, "f1": f1, "support": tp + fn}
    aciertos = sum(confusion[(c, c)] for c in CLASES)
    return {
        "aciertos": aciertos,
        "accuracy": Fraction(aciertos, len(reales)),
        "f1_macro": sum((x["f1"] for x in por_clase.values()), Fraction(0)) / len(CLASES),
        "por_clase": por_clase,
    }


class Informe:
    def __init__(self) -> None:
        self.filas: list[tuple[str, bool, str]] = []

    def __call__(self, id_: str, ok: bool, detalle: str) -> None:
        self.filas.append((id_, bool(ok), detalle))

    @property
    def ok(self) -> bool:
        return all(ok for _, ok, _ in self.filas)


def integridad(anotar: Informe) -> None:
    lineas = leer("SHA256SUMS.txt").decode("utf-8").splitlines()
    distintos, faltan = [], []
    for linea in lineas:
        digest, nombre = linea.split("  ", 1)
        ruta = AQUI / nombre
        if not ruta.is_file():
            faltan.append(nombre)
        elif hashlib.sha256(ruta.read_bytes()).hexdigest() != digest:
            distintos.append(nombre)
    anotar(
        "integridad",
        not distintos and not faltan and lineas,
        f"{len(lineas)} archivos contra SHA256SUMS.txt; distintos {distintos}; faltan {faltan}",
    )


def modelo(anotar: Informe) -> dict[str, Any]:
    ficha = leer_json("modelo/ficha_modelos.json")
    registro = leer_json("modelo/registro_conversion.json")
    linaje = leer_json("modelo/linaje_verificacion.json")
    orig, opt = ficha["original"], ficha["optimizado"]
    anotar(
        "modelo.identidad",
        orig["sha256"] == registro["entrada"]["sha256"] == linaje["ficha"]["original"]["sha256"]
        and orig["run_id"] == registro["entrada"]["run_id"] == linaje["ficha"]["original"]["run_id"]
        and opt["sha256"]
        == registro["salidas"]["int8"]["sha256"]
        == linaje["ficha"]["variante"]["sha256"]
        and opt["version"] == linaje["ficha"]["variante"]["version"]
        and linaje["linaje_verificado"],
        f"original {orig['version']} run {orig['run_id'][:12]}... {orig['archivo']} "
        f"{orig['sha256'][:12]}...; optimizado {opt['version']} {opt['archivo']} "
        f"{opt['sha256'][:12]}...; linaje VAL-01 verificado: {linaje['linaje_verificado']}",
    )
    reduccion = Fraction(orig["bytes"] - opt["bytes"], orig["bytes"]) * 100
    declarada = ficha["reduccion_tamano_pct"]
    anotar(
        "modelo.tamano",
        orig["bytes"] == registro["entrada"]["bytes"]
        and opt["bytes"] == registro["salidas"]["int8"]["bytes"]
        and abs(float(reduccion) - declarada) < TOLERANCIA,
        f"{orig['bytes']} -> {opt['bytes']} bytes: reduccion {float(reduccion):.4f} % "
        f"(declarada {declarada:.4f} %)",
    )
    return {"reduccion": reduccion, "original": orig, "optimizado": opt}


def validacion(anotar: Informe) -> dict[str, Any]:
    meta = leer_json("validacion/manifest.meta.json")
    manifiesto = [
        json.loads(x) for x in leer("validacion/manifest_val.jsonl").decode().splitlines()
    ]
    anotar(
        "validacion.manifiesto",
        hashlib.sha256(leer("validacion/manifest_val.jsonl")).hexdigest()
        == leer_json("validacion/predicciones_val.json")["manifiesto"]["extracto_val"]["sha256"]
        and all(m["split"] == "val" for m in manifiesto),
        f"{meta['manifest_id']} (manifiesto completo {meta['manifest_hash'][:12]}...): "
        f"{len(manifiesto)} lineas val",
    )

    # Predicciones reconstruidas desde los datos primarios.
    original = {
        f["sample_id"]: f for f in leer_csv("validacion/primarios/comparacion_val_val02.csv")
    }
    edge = {f["id"]: f for f in leer_csv("validacion/primarios/resultados_raspberry_val07.csv")}
    formales = leer_csv("validacion/predicciones_val.csv")
    ids = [f["sample_id"] for f in formales]
    etiqueta = {m["crop_id"]: m["category_name"] for m in manifiesto}
    reconstruidas, distintas = [], []
    for m in manifiesto:
        cid = m["crop_id"]
        o = CLASES[argmax([float(original[cid][f"prob_original_{c}"]) for c in CLASES])]
        i = CLASES[argmax([float(edge[cid][f"int8_logit_{c}"]) for c in CLASES])]
        reconstruidas.append((cid, m["category_name"], o, i))
    por_id = {f["sample_id"]: f for f in formales}
    for cid, real, o, i in reconstruidas:
        f = por_id.get(cid, {})
        if (f.get("true_class"), f.get("original_prediction"), f.get("optimized_prediction")) != (
            real,
            o,
            i,
        ):
            distintas.append(cid)
    anotar(
        "validacion.predicciones",
        len(ids) == len(set(ids)) == len(manifiesto)
        and set(ids) == set(etiqueta)
        and not distintas,
        f"{len(ids)} filas, {len(set(ids))} unicas, mismas muestras que el manifiesto; "
        f"reconstruidas desde VAL-02 (original) y la Raspberry (INT8): distintas {distintas}",
    )

    reales = [r for _, r, _, _ in reconstruidas]
    calc = {
        "original": metricas(reales, [o for _, _, o, _ in reconstruidas]),
        "optimized": metricas(reales, [i for _, _, _, i in reconstruidas]),
    }
    declarado = leer_json("validacion/metricas_val.json")
    diferencias = []
    for modelo_, m in calc.items():
        d = declarado["modelos"][modelo_]
        pares = [
            ("aciertos", m["aciertos"], d["aciertos"]),
            ("accuracy", m["accuracy"], d["accuracy"]),
            ("f1_macro", m["f1_macro"], d["f1_macro"]),
        ]
        for c in CLASES:
            for k in ("precision", "recall", "f1", "support"):
                pares.append((f"{c}.{k}", m["por_clase"][c][k], d["por_clase"][c][k]))
        diferencias += [
            f"{modelo_}.{n}" for n, a, b in pares if abs(float(a) - float(b)) > TOLERANCIA
        ]
    caida = (calc["original"]["accuracy"] - calc["optimized"]["accuracy"]) * 100
    anotar(
        "validacion.metricas",
        not diferencias
        and f"{caida.numerator}/{caida.denominator}" == declarado["caida_accuracy"]["pp_fraccion"]
        and (caida <= 2) == declarado["caida_accuracy"]["cumple"],
        f"accuracy {calc['original']['aciertos']}/{len(reales)} -> "
        f"{calc['optimized']['aciertos']}/{len(reales)}; caida "
        f"{caida.numerator}/{caida.denominator} = {float(caida):.4f} pp (<= 2: {caida <= 2}); "
        f"distintas de lo declarado {diferencias}",
    )
    return {"calc": calc, "caida": caida, "muestras": len(reales)}


def benchmark(anotar: Informe) -> dict[str, Any]:
    tiempos = leer_csv("benchmark/tiempos.csv")
    datos = leer_json("benchmark/benchmark.json")
    recursos = leer_json("benchmark/recursos_edge.json")
    anotar(
        "benchmark.crudo",
        hashlib.sha256(leer("benchmark/tiempos.csv")).hexdigest() == datos["tiempos"]["sha256"],
        f"tiempos.csv ({len(tiempos)} filas) es el que registro la Raspberry",
    )
    resultado = {}
    for m in ("fp32", "int8"):
        calentamientos = [f for f in tiempos if f["modelo"] == m and f["fase"] == "calentamiento"]
        validas = [
            float(f["ms_total"])
            for f in tiempos
            if f["modelo"] == m and f["fase"] == "medicion" and f["valido"] == "True"
        ]
        p50, p95 = percentil(validas, 50), percentil(validas, 95)
        declarado = recursos["latencia_edge"][m]["ms_total"]
        anotar(
            f"benchmark.{m}",
            len(calentamientos) >= 10
            and len(validas) >= 100
            and abs(p50 - declarado["p50"]) < TOLERANCIA
            and abs(p95 - declarado["p95"]) < TOLERANCIA,
            f"{len(calentamientos)} calentamientos excluidos, {len(validas)} mediciones validas; "
            f"p50 {p50:.3f} ms, p95 {p95:.3f} ms (declarado {declarado['p50']:.3f} / "
            f"{declarado['p95']:.3f})",
        )
        resultado[m] = {"p50": p50, "p95": p95, "n": len(validas)}
    hw = datos["hardware"]
    anotar(
        "benchmark.condiciones",
        hw.get("arquitectura") == "aarch64"
        and bool(hw.get("modelo_dispositivo"))
        and bool(datos["runtime"].get("onnxruntime"))
        and bool(datos.get("condiciones_inicio"))
        and bool(datos.get("condiciones_fin")),
        f"{hw.get('modelo_dispositivo')}, {hw.get('sistema_operativo')}, onnxruntime "
        f"{datos['runtime'].get('onnxruntime')}; condiciones de inicio y fin registradas",
    )
    return resultado


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    anotar = Informe()
    integridad(anotar)
    mod = modelo(anotar)
    val = validacion(anotar)
    ben = benchmark(anotar)
    for id_, ok, detalle in anotar.filas:
        print(f"[{'ok' if ok else 'FALLA':5}] {id_}: {detalle}")
    o, i = val["calc"]["original"], val["calc"]["optimized"]
    print("\nResumen recalculado (solo con los archivos del paquete):")
    print(
        f"  tamano       {mod['original']['bytes']} -> {mod['optimizado']['bytes']} B "
        f"(-{float(mod['reduccion']):.2f} %)"
    )
    print(
        f"  accuracy     {float(o['accuracy']) * 100:.3f} % -> {float(i['accuracy']) * 100:.3f} % "
        f"(-{float(val['caida']):.4f} pp)"
    )
    print(
        f"  F1 macro     {float(o['f1_macro']) * 100:.3f} % -> {float(i['f1_macro']) * 100:.3f} %"
    )
    print(
        f"  latencia p50 {ben['fp32']['p50']:.2f} -> {ben['int8']['p50']:.2f} ms; "
        f"p95 {ben['fp32']['p95']:.2f} -> {ben['int8']['p95']:.2f} ms"
    )
    print("\nVERIFICADO" if anotar.ok else "\nNO VERIFICADO")
    return 0 if anotar.ok else 1


if __name__ == "__main__":
    sys.exit(main())
