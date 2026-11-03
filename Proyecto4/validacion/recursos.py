"""Comparacion auditable de recursos y calidad en el edge (VAL-06, #18; rubrica 3.2 y 3.3).

Solo biblioteca estandar. Convierte las mediciones crudas de la Raspberry (VAL-05) y la
calidad de VAL-04 en un reporte antes/despues:

- **Tamano**: bytes y SHA-256 de `model.pt` (original del P3), `model_fp32.onnx` y
  `model_int8.onnx`, contrastados entre el registro de conversion, el recalculo sobre S3
  de VAL-01 y lo que leyo la propia Raspberry; reduccion con fracciones exactas.
- **Latencia en el edge**: p50 y p95 recalculados de `evidencias/VAL-05/tiempos.csv`,
  solo con las mediciones validas (`fase == medicion`, `valido == True`), sin
  calentamientos. Percentil por **interpolacion lineal** entre las observaciones
  ordenadas (Hyndman y Fan tipo 7; `numpy.percentile` por defecto y
  `statistics.quantiles(method="inclusive")`): para p en [0, 100], posicion
  h = (n - 1) * p / 100 y valor x[floor(h)] + (h - floor(h)) * (x[floor(h)+1] - x[floor(h)]).
  El tiempo es preprocesamiento + inferencia local; el benchmark no hace llamadas de
  red, asi que no hay tiempo de AWS que separar.
- **Memoria y carga**: memoria pico por proceso y carga de la sesion, informativas.
- **Calidad**: accuracy y F1 macro de VAL-04 (misma validacion), para el intercambio.

Solo compara original y optimizado **medidos en el mismo dispositivo** (FP32 contra
INT8, VAL-05). Nunca usa tiempos de la laptop.

    cd Proyecto4
    python validacion/recursos.py

Escribe `validacion/resultados/recursos_edge.json` y `recursos_edge.csv` (antes/despues)
solo si la verificacion de VAL-05 y las comprobaciones de consistencia pasan.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import sys
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from typing import Any

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

import verificar_benchmark as vb  # noqa: E402

RAIZ = AQUI.parent  # Proyecto4/
RESULTADOS = AQUI / "resultados"
REGISTRO = RAIZ / "modelo" / "registros" / "registro_conversion.json"
LINAJE = RAIZ / "modelo" / "registros" / "linaje_verificacion.json"
METRICAS = RESULTADOS / "metricas_val.json"
JSON_SALIDA = RESULTADOS / "recursos_edge.json"
CSV_SALIDA = RESULTADOS / "recursos_edge.csv"

METODO_PERCENTIL = (
    "interpolacion lineal entre observaciones ordenadas (Hyndman y Fan tipo 7; igual a "
    "numpy.percentile por defecto y a statistics.quantiles(method='inclusive')): "
    "h = (n - 1) * p / 100; x[floor(h)] + (h - floor(h)) * (x[floor(h)+1] - x[floor(h)])"
)
COMPONENTES = ("ms_total", "ms_preprocesamiento", "ms_inferencia")


def percentil(valores: list[float], p: float) -> float:
    """Percentil p (0-100) por interpolacion lineal (tipo 7)."""
    if not valores:
        raise ValueError("sin valores")
    x = sorted(valores)
    h = (len(x) - 1) * p / 100
    piso = math.floor(h)
    if piso + 1 >= len(x):
        return x[-1]
    return x[piso] + (h - piso) * (x[piso + 1] - x[piso])


def mediciones_validas(filas: list[dict[str, str]], modelo: str) -> list[dict[str, str]]:
    """Solo las mediciones validas del modelo: sin calentamientos ni repeticiones fallidas."""
    return [
        f
        for f in filas
        if f["modelo"] == modelo and f["fase"] == "medicion" and f["valido"] == "True"
    ]


def latencia(filas: list[dict[str, str]], modelo: str) -> dict[str, Any]:
    validas = mediciones_validas(filas, modelo)
    resultado: dict[str, Any] = {
        "mediciones_validas": len(validas),
        "calentamientos_excluidos": sum(
            f["modelo"] == modelo and f["fase"] == "calentamiento" for f in filas
        ),
    }
    for componente in COMPONENTES:
        valores = [float(f[componente]) for f in validas]
        resultado[componente] = {
            "p50": percentil(valores, 50),
            "p95": percentil(valores, 95),
            "min": min(valores),
            "max": max(valores),
            # fsum es exacta y da lo mismo en cualquier Python; sum() de floats cambio en 3.12.
            "media": math.fsum(valores) / len(valores),
        }
    return resultado


def reduccion(antes: int | float, despues: int | float) -> Fraction | float:
    """(antes - despues) / antes * 100; exacta si recibe enteros."""
    if isinstance(antes, int) and isinstance(despues, int):
        return Fraction(antes - despues, antes) * 100
    return (antes - despues) / antes * 100


def tamanos(registro: dict, linaje: dict, benchmark: dict) -> tuple[dict[str, Any], list[str]]:
    """Bytes y SHA-256 de cada artefacto en cada fuente; problemas si no coinciden."""
    s3 = {
        llave.rsplit("/", 1)[-1]: objeto
        for llave, objeto in linaje["ficha"].get("publicacion", {}).get("objetos", {}).items()
    }
    fuentes = {
        "model.pt": {
            "registro_conversion": (registro["entrada"]["bytes"], registro["entrada"]["sha256"]),
            "s3_val01": (s3.get("model.pt", {}).get("bytes"), s3.get("model.pt", {}).get("sha256")),
        },
    }
    for clave, archivo in (("fp32", "model_fp32.onnx"), ("int8", "model_int8.onnx")):
        dispositivo = benchmark["modelos"].get(clave, {})
        fuentes[archivo] = {
            "registro_conversion": (
                registro["salidas"][clave]["bytes"],
                registro["salidas"][clave]["sha256"],
            ),
            "s3_val01": (s3.get(archivo, {}).get("bytes"), s3.get(archivo, {}).get("sha256")),
            "raspberry_val05": (dispositivo.get("bytes"), dispositivo.get("sha256")),
        }
    problemas, resultado = [], {}
    for archivo, por_fuente in fuentes.items():
        distintos = {v for v in por_fuente.values()}
        if len(distintos) != 1 or None in next(iter(distintos)):
            problemas.append(f"{archivo}: las fuentes no coinciden: {por_fuente}")
        bytes_, sha = next(iter(por_fuente.values()))
        resultado[archivo] = {
            "bytes": bytes_,
            "mib": bytes_ / 2**20 if bytes_ else None,
            "sha256": sha,
            "fuentes_coincidentes": sorted(por_fuente),
        }
    return resultado, problemas


def calidad(metricas: dict[str, Any]) -> dict[str, Any]:
    orig, opt = metricas["modelos"]["original"], metricas["modelos"]["optimized"]
    return {
        "fuente": "validacion/resultados/metricas_val.json (VAL-04)",
        "particion": metricas["particion"],
        "accuracy": {"original": orig["accuracy"], "optimizado": opt["accuracy"]},
        "f1_macro": {"original": orig["f1_macro"], "optimizado": opt["f1_macro"]},
        "caida_accuracy_pp": metricas["caida_accuracy"]["pp"],
        "caida_accuracy_pp_fraccion": metricas["caida_accuracy"]["pp_fraccion"],
        "cumple_2pp": metricas["caida_accuracy"]["cumple"],
        "optimizado_medido_en": metricas["fuente"]["optimizado"],
        "nota": "accuracy del INT8 tal como se ejecuto en "
        f"{metricas['fuente']['optimizado']}, sobre la misma validacion que el original",
    }


def comparar(tamano: dict, lat: dict, benchmark: dict, cal: dict) -> dict[str, Any]:
    pt, fp32, int8 = (
        tamano[a]["bytes"] for a in ("model.pt", "model_fp32.onnx", "model_int8.onnx")
    )
    rf, ri = lat["fp32"]["ms_total"], lat["int8"]["ms_total"]
    sin_solape = ri["max"] < rf["min"]
    mem = {m: benchmark["modelos"][m].get("pico_memoria_mb") for m in ("fp32", "int8")}
    return {
        "tamano": {
            "reduccion_vs_model_pt_pct": reduccion(pt, int8),
            "reduccion_vs_fp32_onnx_pct": reduccion(fp32, int8),
            "veces_menor_vs_model_pt": Fraction(pt, int8),
        },
        "latencia_edge": {
            "condiciones": "FP32 e INT8 en la misma Raspberry, mismo runtime, imagenes y orden",
            "p50_reduccion_pct": reduccion(rf["p50"], ri["p50"]),
            "p95_reduccion_pct": reduccion(rf["p95"], ri["p95"]),
            "aceleracion_p50": rf["p50"] / ri["p50"],
            "aceleracion_p95": rf["p95"] / ri["p95"],
            "inferencia_p50_reduccion_pct": reduccion(
                lat["fp32"]["ms_inferencia"]["p50"], lat["int8"]["ms_inferencia"]["p50"]
            ),
            "distribuciones_sin_solape": sin_solape,
            "nota_variabilidad": f"la medicion INT8 mas lenta ({ri['max']:.3f} ms) es menor "
            f"que la FP32 mas rapida ({rf['min']:.3f} ms): la diferencia no esta dentro de la "
            "variabilidad"
            if sin_solape
            else "las distribuciones se solapan: revisar antes de declarar aceleracion",
        },
        "memoria_pico": {
            "fp32_mb": mem["fp32"],
            "int8_mb": mem["int8"],
            "reduccion_pct": reduccion(mem["fp32"], mem["int8"]) if all(mem.values()) else None,
            "nota": "ru_maxrss de cada proceso (Python + onnxruntime + modelo); una sola corrida",
        },
        "calidad": cal,
    }


def tabla(tamano: dict, lat: dict, benchmark: dict, cal: dict) -> bytes:
    """Antes/despues. `cambio` es relativo (%) en recursos y absoluto (pp) en calidad."""
    m = benchmark["modelos"]
    recursos = [
        (
            "tamano",
            "bytes_model_pt_vs_int8",
            tamano["model.pt"]["bytes"],
            tamano["model_int8.onnx"]["bytes"],
        ),
        (
            "tamano",
            "bytes_fp32_onnx_vs_int8",
            tamano["model_fp32.onnx"]["bytes"],
            tamano["model_int8.onnx"]["bytes"],
        ),
    ]
    for componente in COMPONENTES:
        for estadistico in ("p50", "p95"):
            recursos.append(
                (
                    "latencia_edge_ms",
                    f"{componente}_{estadistico}",
                    lat["fp32"][componente][estadistico],
                    lat["int8"][componente][estadistico],
                )
            )
    recursos += [
        ("memoria", "pico_mb", m["fp32"].get("pico_memoria_mb"), m["int8"].get("pico_memoria_mb")),
        ("carga", "ms_carga_sesion", m["fp32"].get("ms_carga"), m["int8"].get("ms_carga")),
    ]
    calidad_val = [
        ("calidad_val", "accuracy", cal["accuracy"]["original"], cal["accuracy"]["optimizado"]),
        ("calidad_val", "f1_macro", cal["f1_macro"]["original"], cal["f1_macro"]["optimizado"]),
    ]
    salida = io.StringIO()
    escritor = csv.writer(salida, lineterminator="\n")
    escritor.writerow(["ambito", "metrica", "original", "optimizado", "cambio", "unidad_cambio"])
    for ambito, metrica, antes, despues in recursos:
        cambio = "" if not antes else repr(-float(reduccion(antes, despues)))
        escritor.writerow([ambito, metrica, repr(antes), repr(despues), cambio, "% relativo"])
    for ambito, metrica, antes, despues in calidad_val:
        # La caida de accuracy es la exacta de VAL-04 (fracciones), no una resta de floats.
        cambio = -cal["caida_accuracy_pp"] if metrica == "accuracy" else (despues - antes) * 100
        escritor.writerow([ambito, metrica, repr(antes), repr(despues), repr(cambio), "pp"])
    return salida.getvalue().encode("utf-8")


def a_json(valor: Any) -> Any:
    if isinstance(valor, Fraction):
        return float(valor)
    if isinstance(valor, dict):
        return {k: a_json(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [a_json(v) for v in valor]
    return valor


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--evidencia", type=Path, default=vb.EVIDENCIA)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    tiempos = (args.evidencia / "tiempos.csv").read_bytes()
    benchmark = json.loads((args.evidencia / "benchmark.json").read_text(encoding="utf-8"))
    registro = json.loads(REGISTRO.read_text(encoding="utf-8"))
    informe = vb.verificar(
        tiempos, benchmark, registro, hashlib.sha256(vb.PREPROCESAR.read_bytes()).hexdigest()
    )
    if not informe["ok"]:
        fallidas = [c["id"] for c in informe["comprobaciones"] if not c["ok"]]
        raise SystemExit(f"FALLA: la evidencia de VAL-05 no se verifica: {fallidas}")
    if any(benchmark["modelos"].get(m, {}).get("estado") != "ok" for m in ("fp32", "int8")):
        raise SystemExit("FALLA: este reporte compara FP32 e INT8 medidos en el dispositivo")

    tamano, problemas = tamanos(registro, json.loads(LINAJE.read_text("utf-8")), benchmark)
    filas = list(csv.DictReader(io.StringIO(tiempos.decode("utf-8"))))
    lat = {m: latencia(filas, m) for m in ("fp32", "int8")}
    problemas += [
        f"{m}: {lat[m]['mediciones_validas']} mediciones validas (< {vb.MINIMO_MEDICIONES})"
        for m in lat
        if lat[m]["mediciones_validas"] < vb.MINIMO_MEDICIONES
    ]
    metricas = json.loads(METRICAS.read_text(encoding="utf-8"))
    if metricas["particion"] != "val":
        problemas.append("las metricas de VAL-04 no son de validacion")
    if problemas:
        raise SystemExit("FALLA: no se escribio evidencia: " + "; ".join(problemas))

    cal = calidad(metricas)
    datos_tabla = tabla(tamano, lat, benchmark, cal)
    hardware = benchmark["hardware"]
    evidencia = {
        "schema_version": 1,
        "tarea": "VAL-06 (#18)",
        "generado_en": datetime.now(UTC).isoformat(timespec="seconds"),
        "comando": "python validacion/recursos.py",
        "fuentes": {
            "tiempos": {
                "archivo": (args.evidencia / "tiempos.csv").relative_to(RAIZ).as_posix(),
                "sha256": hashlib.sha256(tiempos).hexdigest(),
                "verificacion": "verificar_benchmark.verificar: ok",
            },
            "metricas_val04": METRICAS.relative_to(RAIZ).as_posix(),
            "tamanos": "registro_conversion.json, linaje_verificacion.json (S3) y benchmark.json",
        },
        "dispositivo": {
            "modelo": hardware["modelo_dispositivo"],
            "arquitectura": hardware["arquitectura"],
            "sistema_operativo": hardware["sistema_operativo"],
            "runtime": f"onnxruntime {benchmark['runtime']['onnxruntime']} CPUExecutionProvider",
            "fecha_benchmark": benchmark["fecha"],
        },
        "metodo_percentil": METODO_PERCENTIL,
        "tiempo_medido": "preprocesamiento + inferencia local (sin captura, sin carga del "
        "modelo y sin envio: el benchmark no hace llamadas de red)",
        "tamanos": tamano,
        "latencia_edge": lat,
        "comparacion": comparar(tamano, lat, benchmark, cal),
        "tabla_antes_despues": {
            "archivo": CSV_SALIDA.name,
            "sha256": hashlib.sha256(datos_tabla).hexdigest(),
        },
    }
    for destino, contenido in (
        (CSV_SALIDA, datos_tabla),
        (
            JSON_SALIDA,
            (json.dumps(a_json(evidencia), ensure_ascii=False, indent=2) + "\n").encode(),
        ),
    ):
        temporal = destino.with_name(f".{destino.name}.tmp")
        temporal.write_bytes(contenido)
        os.replace(temporal, destino)

    c = a_json(evidencia["comparacion"])
    print(
        f"tamano: -{c['tamano']['reduccion_vs_model_pt_pct']:.4f} % vs model.pt, "
        f"-{c['tamano']['reduccion_vs_fp32_onnx_pct']:.4f} % vs FP32 ONNX"
    )
    for m in ("fp32", "int8"):
        t = lat[m]["ms_total"]
        print(f"{m}: n={lat[m]['mediciones_validas']} p50 {t['p50']:.3f} ms, p95 {t['p95']:.3f} ms")
    print(
        f"latencia p50 -{c['latencia_edge']['p50_reduccion_pct']:.2f} %, "
        f"p95 -{c['latencia_edge']['p95_reduccion_pct']:.2f} %; sin solape: "
        f"{c['latencia_edge']['distribuciones_sin_solape']}"
    )
    print(f"calidad: caida {cal['caida_accuracy_pp']:.4f} pp (<= 2: {cal['cumple_2pp']})")


if __name__ == "__main__":
    main()
