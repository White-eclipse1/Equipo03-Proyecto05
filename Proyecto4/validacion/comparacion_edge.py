"""Comparacion original vs INT8 con el INT8 **medido en la Raspberry** (VAL-08, #24).

Une, por `sample_id` y en el orden del manifiesto:

- el original de VAL-02 (`comparacion_val.csv`): `model.pt` en PyTorch, que solo corre
  offline; en el dispositivo su exportacion FP32 da las mismas predicciones;
- las tres ejecuciones ONNX de la Raspberry de VAL-07
  (`evidencias/VAL-07/raspberry/resultados.csv`): `int8`, `int8_referencia` y `fp32`,
  con probabilidades = softmax de los logits registrados.

Antes de escribir exige que el contraste de VAL-07 pase (preprocesamiento identico,
mismos modelos y entradas) y que las muestras sean exactamente las de VAL-02. Escribe
`validacion/resultados/comparacion_val_edge.csv` (mismo formato que VAL-02) y su JSON,
que `predicciones_formales.py --comparacion` convierte en el archivo formal.

    cd Proyecto4
    python validacion/comparacion_edge.py
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

import comparar_modelos as comp  # noqa: E402
import contrastar_edge as ce  # noqa: E402

RAIZ = AQUI.parent  # Proyecto4/
CSV_SALIDA = comp.RESULTADOS / "comparacion_val_edge.csv"
CLASES = ["cat", "dog", "person"]


def softmax(logits: list[float]) -> list[float]:
    """Softmax estable en float64; las probabilidades se recalculan desde los logits."""
    maximo = max(logits)
    exp = [math.exp(x - maximo) for x in logits]
    total = math.fsum(exp)
    return [x / total for x in exp]


def unir(val02: list[dict[str, str]], edge: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Filas en el formato de comparar_modelos.py, con las columnas ONNX del edge."""
    por_id = {f["id"]: f for f in edge if f["tipo"] == "val"}
    if [f["sample_id"] for f in val02] != [
        f["sample_id"] for f in val02 if f["sample_id"] in por_id
    ]:
        raise SystemExit("FALLA: faltan muestras de VAL-02 en la corrida del edge")
    if len(por_id) != len(val02):
        raise SystemExit("FALLA: la corrida del edge no tiene exactamente las muestras de VAL-02")
    filas = []
    for f in val02:
        e = por_id[f["sample_id"]]
        if e["clase"] != f["true_class"]:
            raise SystemExit(f"FALLA: {f['sample_id']}: clase distinta entre VAL-02 y VAL-07")
        fila: dict[str, Any] = {
            "sample_id": f["sample_id"],
            "true_class": f["true_class"],
            "original_prediction": f["original_prediction"],
            "optimized_prediction": e["int8_prediction"],
            "fp32_prediction": e["fp32_prediction"],
            "int8_prediction": e["int8_prediction"],
            "int8_referencia_prediction": e["int8_referencia_prediction"],
        }
        for c in CLASES:
            fila[f"prob_original_{c}"] = f[f"prob_original_{c}"]
        for modelo in ("fp32", "int8", "int8_referencia"):
            probs = softmax([float(e[f"{modelo}_logit_{c}"]) for c in CLASES])
            if CLASES[probs.index(max(probs))] != e[f"{modelo}_prediction"]:
                raise SystemExit(f"FALLA: {f['sample_id']}: argmax distinto en {modelo}")
            for c, p in zip(CLASES, probs, strict=True):
                fila[f"prob_{modelo}_{c}"] = repr(p)
        filas.append(fila)
    return filas


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    edge, laptop = (
        ce.leer_corrida(ce.EVIDENCIA / "raspberry"),
        ce.leer_corrida(ce.EVIDENCIA / "laptop"),
    )
    contraste = ce.contrastar(edge, laptop, hashlib.sha256(ce.PREPROCESAR.read_bytes()).hexdigest())
    if not contraste["ok"]:
        raise SystemExit("FALLA: el contraste de VAL-07 no pasa")

    origen = comp.RESULTADOS / comp.ARCHIVO_CSV
    val02_bytes = origen.read_bytes()
    val02_json = json.loads(origen.with_suffix(".json").read_text(encoding="utf-8"))
    if hashlib.sha256(val02_bytes).hexdigest() != val02_json["csv"]["sha256"]:
        raise SystemExit("FALLA: comparacion_val.csv no es el que registra su JSON")
    val02 = list(csv.DictReader(io.StringIO(val02_bytes.decode("utf-8"))))
    filas = unir(val02, edge[1])
    datos = comp.csv_bytes(filas, CLASES)
    verificacion = comp.verificar_csv(
        datos, [{"sample_id": f["sample_id"], "true_class": f["true_class"]} for f in val02], []
    )
    if not verificacion["ok"]:
        raise SystemExit("FALLA: el CSV no tiene exactamente los IDs y etiquetas de val")

    meta_edge = edge[0]
    hw, rt = meta_edge["hardware"], meta_edge["runtime"]
    evidencia = {
        "schema_version": 1,
        "tarea": "VAL-08 (#24): comparacion con el INT8 medido en el dispositivo",
        "generado_en": datetime.now(UTC).isoformat(timespec="seconds"),
        "comando": "python validacion/comparacion_edge.py",
        "split": "val",
        "clases": CLASES,
        "fuentes": {
            "original": {
                "archivo": origen.relative_to(RAIZ).as_posix(),
                "sha256": val02_json["csv"]["sha256"],
                "nota": "model.pt en PyTorch (laptop, VAL-02); en la Raspberry su FP32 ONNX "
                "da las mismas 292 predicciones",
            },
            "edge": {
                "archivo": "evidencias/VAL-07/raspberry/resultados.csv",
                "sha256": meta_edge["resultados"]["sha256"],
                "fecha": meta_edge["fecha"],
                "probabilidades": "softmax de los logits registrados en el dispositivo",
            },
        },
        "manifiesto": val02_json["manifiesto"],
        "modelos": val02_json["modelos"],
        "verificacion": verificacion,
        "resumen": comp.resumen(filas, CLASES),
        "csv": {"archivo": CSV_SALIDA.name, "sha256": hashlib.sha256(datos).hexdigest()},
        "entorno": {
            "python": rt["python"],
            "sistema": hw["sistema_operativo"],
            "maquina": hw["arquitectura"],
            "procesador": hw["modelo_dispositivo"],
            "onnxruntime": rt["onnxruntime"],
            "proveedor_onnx": "CPUExecutionProvider",
        },
        "nota_optimizado": "INT8 ejecutado en la Raspberry Pi 4 de la demostracion "
        "(VAL-07, onnxruntime por defecto): la cifra de la rubrica",
    }
    for destino, contenido in (
        (CSV_SALIDA, datos),
        (
            CSV_SALIDA.with_suffix(".json"),
            (json.dumps(evidencia, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        ),
    ):
        temporal = destino.with_name(f".{destino.name}.tmp")
        temporal.write_bytes(contenido)
        os.replace(temporal, destino)
    r = evidencia["resumen"]
    print(f"aciertos: {r['aciertos']}; acuerdo int8/original {r['acuerdo_int8_vs_original']}")
    print(f"Escrito {CSV_SALIDA.relative_to(RAIZ).as_posix()} y su JSON")


if __name__ == "__main__":
    main()
