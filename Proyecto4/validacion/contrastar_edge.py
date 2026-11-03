"""Contraste del preprocesamiento y las predicciones: Raspberry contra laptop (VAL-07, #19).

Solo biblioteca estandar. Lee las dos corridas de `edge/verificar_preprocesamiento.py`
(`evidencias/VAL-07/raspberry/` y `evidencias/VAL-07/laptop/`) y la columna del original
de VAL-02, y comprueba:

- las comprobaciones sinteticas del preprocesamiento pasan en los dos lados;
- mismos modelos (SHA-256), mismas entradas (indice) y `preprocesar.py` del repositorio;
- el tensor preprocesado de cada entrada es **identico bit a bit** en los dos lados
  (mismo preprocesamiento en el dispositivo que offline);
- forma `1x3x224x224` y tipo float32 en todas las entradas;
- mapeo de clases: en el edge, cada clase de val se predice sobre todo como si misma y
  las fotos de la camara dan la clase presentada;
- predicciones del edge contra las offline por ejecucion (`fp32`, `int8_referencia`,
  `int8`), con la diferencia maxima de logits, y si en el edge `int8` coincide con
  `int8_referencia` (prueba de la hipotesis de saturacion de VAL-02).

Las diferencias no son fallas en si: se cuentan y se listan para explicarlas. Falla si
el preprocesamiento o la identidad de modelos y entradas no coinciden.

    cd Proyecto4
    python validacion/contrastar_edge.py

Escribe `validacion/resultados/contraste_edge.json` y `entradas_conocidas.csv` (tabla de
entradas y resultados) solo si las comprobaciones pasan.
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
from pathlib import Path
from typing import Any

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent  # Proyecto4/
EVIDENCIA = RAIZ / "evidencias" / "VAL-07"
RESULTADOS = AQUI / "resultados"
COMPARACION = RESULTADOS / "comparacion_val.csv"
PREPROCESAR = RAIZ / "modelo" / "preprocesar.py"
JSON_SALIDA = RESULTADOS / "contraste_edge.json"
TABLA_SALIDA = RESULTADOS / "entradas_conocidas.csv"

CLASES = ("cat", "dog", "person")
EJECUCIONES = ("int8", "int8_referencia", "fp32")
# Entradas de la tabla: las 5 muestras relevantes de VAL-04 y la primera de cada clase.
RELEVANTES = ("0.1.3:a1647", "0.1.3:a322", "0.1.3:a448", "0.1.3:a554", "0.1.3:a559")


def leer_corrida(carpeta: Path) -> tuple[dict[str, Any], list[dict[str, str]], bytes]:
    datos = (carpeta / "resultados.csv").read_bytes()
    meta = json.loads((carpeta / "resultados.json").read_text(encoding="utf-8"))
    return meta, list(csv.DictReader(io.StringIO(datos.decode("utf-8")))), datos


def logits(fila: dict[str, str], ejecucion: str) -> list[float]:
    return [float(fila[f"{ejecucion}_logit_{c}"]) for c in CLASES]


def contrastar(
    edge: tuple[dict, list[dict], bytes],
    laptop: tuple[dict, list[dict], bytes],
    preprocesar_sha256: str,
) -> dict[str, Any]:
    resultado: list[dict[str, Any]] = []

    def anotar(id_: str, ok: bool, detalle: str) -> None:
        resultado.append({"id": id_, "ok": bool(ok), "detalle": detalle})

    (m_edge, f_edge, csv_edge), (m_lap, f_lap, csv_lap) = edge, laptop
    for nombre, meta, datos in (("edge", m_edge, csv_edge), ("laptop", m_lap, csv_lap)):
        anotar(
            f"{nombre}.resultados_sha256",
            hashlib.sha256(datos).hexdigest() == meta["resultados"]["sha256"],
            f"resultados.csv de {meta['maquina']} es el que registra su JSON",
        )
        sinteticas = meta["preprocesamiento"]["comprobaciones_sinteticas"]
        anotar(
            f"{nombre}.preprocesamiento_sintetico",
            bool(sinteticas) and all(c["ok"] for c in sinteticas),
            f"{meta['maquina']}: "
            + ", ".join(f"{c['id']}={'ok' if c['ok'] else 'FALLA'}" for c in sinteticas),
        )
    anotar(
        "edge.dispositivo",
        m_edge["hardware"].get("arquitectura") == "aarch64"
        and bool(m_edge["hardware"].get("modelo_dispositivo")),
        f"{m_edge['hardware'].get('modelo_dispositivo')} "
        f"({m_edge['hardware'].get('arquitectura')}), "
        f"onnxruntime {m_edge['runtime'].get('onnxruntime')}",
    )
    anotar(
        "identidad",
        {k: v["sha256"] for k, v in m_edge["modelos"].items()}
        == {k: v["sha256"] for k, v in m_lap["modelos"].items()}
        and m_edge["entradas"]["indice_sha256"] == m_lap["entradas"]["indice_sha256"]
        and m_edge["codigo"]["preprocesar.py"]
        == m_lap["codigo"]["preprocesar.py"]
        == preprocesar_sha256,
        "mismos modelos, mismo indice de entradas y preprocesar.py del repositorio "
        "en los dos lados",
    )
    sinteticas_iguales = [
        c["id"]
        for c, d in zip(
            m_edge["preprocesamiento"]["comprobaciones_sinteticas"],
            m_lap["preprocesamiento"]["comprobaciones_sinteticas"],
            strict=True,
        )
        if c.get("tensor_sha256") != d.get("tensor_sha256")
    ]
    anotar(
        "sintetico.bit_a_bit",
        not sinteticas_iguales,
        f"tensores sinteticos identicos en los dos lados; distintos: {sinteticas_iguales}",
    )

    por_id = {f["id"]: f for f in f_lap}
    pares = [(e, por_id.get(e["id"])) for e in f_edge]
    faltan = [e["id"] for e, lap in pares if lap is None] + sorted(
        set(por_id) - {e["id"] for e in f_edge}
    )
    tensores_distintos = [
        e["id"] for e, lap in pares if lap and e["tensor_sha256"] != lap["tensor_sha256"]
    ]
    anotar(
        "entradas.mismas",
        not faltan and len(f_edge) == len(f_lap),
        f"{len(f_edge)} entradas en el edge y {len(f_lap)} offline; sin pareja: {faltan}",
    )
    anotar(
        "tensor.bit_a_bit",
        not tensores_distintos,
        f"{len(pares) - len(tensores_distintos)}/{len(pares)} tensores preprocesados identicos "
        f"(SHA-256); distintos: {tensores_distintos[:20]}",
    )
    formas = Counter((f["tensor_forma"], f["tensor_tipo"]) for f in f_edge)
    anotar(
        "tensor.forma_tipo",
        set(formas) == {("1x3x224x224", "float32")},
        f"formas y tipos del tensor en el edge: {dict(formas)}",
    )

    # Mapeo de clases en el edge: diagonal dominante en val y camara con su clase.
    mapeo = {}
    for ejecucion in EJECUCIONES:
        confusion = Counter(
            (f["clase"], f[f"{ejecucion}_prediction"]) for f in f_edge if f["tipo"] == "val"
        )
        mapeo[ejecucion] = {
            real: {pred: confusion[(real, pred)] for pred in CLASES} for real in CLASES
        }
    camara = {f["id"]: (f["clase"], f["int8_prediction"]) for f in f_edge if f["tipo"] == "camara"}
    diagonal = all(
        mapeo[e][c][c] > sum(n for p, n in mapeo[e][c].items() if p != c)
        for e in EJECUCIONES
        for c in CLASES
    )
    anotar(
        "clases.mapeo",
        diagonal and all(real == pred for real, pred in camara.values()),
        f"en val cada clase se predice sobre todo como si misma (int8, int8_referencia, fp32); "
        f"camara (presentada -> int8): {sorted(camara.values())}",
    )

    # Predicciones y logits: edge contra offline, y int8 contra referencia en el edge.
    predicciones = {}
    for ejecucion in EJECUCIONES:
        distintas = [
            {
                "id": e["id"],
                "edge": e[f"{ejecucion}_prediction"],
                "laptop": lap[f"{ejecucion}_prediction"],
            }
            for e, lap in pares
            if lap and e[f"{ejecucion}_prediction"] != lap[f"{ejecucion}_prediction"]
        ]
        dif = max(
            (
                abs(a - b)
                for e, lap in pares
                if lap
                for a, b in zip(logits(e, ejecucion), logits(lap, ejecucion), strict=True)
            ),
            default=0.0,
        )
        val = [e for e in f_edge if e["tipo"] == "val"]
        predicciones[ejecucion] = {
            "edge_aciertos_val": sum(e[f"{ejecucion}_prediction"] == e["clase"] for e in val),
            "laptop_aciertos_val": sum(
                lap[f"{ejecucion}_prediction"] == lap["clase"]
                for lap in f_lap
                if lap["tipo"] == "val"
            ),
            "muestras_val": len(val),
            "coinciden_edge_laptop": len(pares) - len(distintas),
            "distintas_edge_laptop": distintas,
            "max_dif_logit_edge_laptop": dif,
        }
    hipotesis = {
        lado: sum(f["int8_prediction"] == f["int8_referencia_prediction"] for f in filas)
        for lado, filas in (("edge", f_edge), ("laptop", f_lap))
    }
    return {
        "ok": all(c["ok"] for c in resultado),
        "comprobaciones": resultado,
        "mapeo_clases_edge": mapeo,
        "predicciones": predicciones,
        "int8_igual_a_referencia": {**hipotesis, "entradas": len(f_edge)},
    }


def tabla(f_edge: list[dict], f_lap: list[dict], original: dict[str, str] | None) -> bytes:
    """Tabla de entradas conocidas: camara, muestras relevantes y una correcta por clase."""
    por_id = {f["id"]: f for f in f_lap}
    elegidas = [f for f in f_edge if f["tipo"] == "camara"]
    elegidas += [f for f in f_edge if f["id"] in RELEVANTES]
    for clase in CLASES:
        elegidas.append(
            next(
                f
                for f in f_edge
                if f["tipo"] == "val" and f["clase"] == clase and f["id"] not in RELEVANTES
            )
        )
    salida = io.StringIO()
    escritor = csv.writer(salida, lineterminator="\n")
    escritor.writerow(
        [
            "id",
            "tipo",
            "clase",
            "tensor_igual_edge_laptop",
            "original_val02",
            "fp32_edge",
            "fp32_laptop",
            "int8_referencia_edge",
            "int8_referencia_laptop",
            "int8_edge",
            "int8_laptop",
        ]
    )
    for f in elegidas:
        lap = por_id[f["id"]]
        escritor.writerow(
            [
                f["id"],
                f["tipo"],
                f["clase"],
                f["tensor_sha256"] == lap["tensor_sha256"],
                (original or {}).get(f["id"], ""),
                f["fp32_prediction"],
                lap["fp32_prediction"],
                f["int8_referencia_prediction"],
                lap["int8_referencia_prediction"],
                f["int8_prediction"],
                lap["int8_prediction"],
            ]
        )
    return salida.getvalue().encode("utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--edge", type=Path, default=EVIDENCIA / "raspberry")
    parser.add_argument("--laptop", type=Path, default=EVIDENCIA / "laptop")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    edge, laptop = leer_corrida(args.edge), leer_corrida(args.laptop)
    informe = contrastar(edge, laptop, hashlib.sha256(PREPROCESAR.read_bytes()).hexdigest())
    for c in informe["comprobaciones"]:
        print(f"[{'ok' if c['ok'] else 'FALLA':5}] {c['id']}: {c['detalle']}")
    for ejecucion, p in informe["predicciones"].items():
        print(
            f"{ejecucion}: edge {p['edge_aciertos_val']}/{p['muestras_val']}, laptop "
            f"{p['laptop_aciertos_val']}/{p['muestras_val']}; coinciden "
            f"{p['coinciden_edge_laptop']}; max |dlogit| {p['max_dif_logit_edge_laptop']:.3g}"
        )
    h = informe["int8_igual_a_referencia"]
    print(f"int8 == int8_referencia: edge {h['edge']}/{h['entradas']}, laptop {h['laptop']}")
    if not informe["ok"]:
        raise SystemExit("FALLA: no se escribio evidencia")

    original = None
    if COMPARACION.is_file():
        filas = csv.DictReader(io.StringIO(COMPARACION.read_text(encoding="utf-8")))
        original = {f["sample_id"]: f["original_prediction"] for f in filas}
    datos_tabla = tabla(edge[1], laptop[1], original)
    evidencia = {
        "schema_version": 1,
        "tarea": "VAL-07 (#19)",
        "generado_en": datetime.now(UTC).isoformat(timespec="seconds"),
        "comando": "python validacion/contrastar_edge.py",
        "corridas": {
            nombre: {
                "maquina": meta["maquina"],
                "fecha": meta["fecha"],
                "dispositivo": meta["hardware"].get("modelo_dispositivo")
                or meta["hardware"].get("sistema_operativo"),
                "arquitectura": meta["hardware"].get("arquitectura"),
                "runtime": meta["runtime"],
                "resultados_sha256": meta["resultados"]["sha256"],
            }
            for nombre, (meta, _, _) in (("edge", edge), ("laptop", laptop))
        },
        **informe,
        "tabla_entradas_conocidas": {
            "archivo": TABLA_SALIDA.name,
            "sha256": hashlib.sha256(datos_tabla).hexdigest(),
        },
    }
    for destino, contenido in (
        (TABLA_SALIDA, datos_tabla),
        (JSON_SALIDA, (json.dumps(evidencia, ensure_ascii=False, indent=2) + "\n").encode()),
    ):
        temporal = destino.with_name(f".{destino.name}.tmp")
        temporal.write_bytes(contenido)
        os.replace(temporal, destino)
    print(f"Escrito {JSON_SALIDA.relative_to(RAIZ).as_posix()} y {TABLA_SALIDA.name}")


if __name__ == "__main__":
    main()
