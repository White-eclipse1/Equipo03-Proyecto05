"""Archivo formal de predicciones por muestra para el evaluador (VAL-03, #13; rubrica 1.3).

A partir de la comparacion de VAL-02 (`comparacion_val.csv`, sin volver a correr
modelos) y del manifiesto del P3, escribe en `validacion/resultados/`:

- `predicciones_val.csv`: una fila por muestra de `val`, unida al manifiesto por
  `sample_id`, con `true_class`, `original_prediction`, `optimized_prediction`, las
  columnas del manifiesto que la vinculan (`manifest_id`, `split`, `class_index`) y las
  probabilidades sin redondear de los dos modelos;
- `predicciones_val.json`: procedencia (manifiesto, modelos, runtime y CPU del
  optimizado, comparacion de origen), exclusiones, resumen y la verificacion;
- `manifiesto/manifest_val.jsonl` y `manifiesto/manifest.meta.json`: las lineas `val`
  del manifiesto, byte a byte, y su meta, para verificar sin acceso a los datos del P3.

`optimized_prediction` es la columna `int8` de la comparacion de origen: con
`--comparacion validacion/resultados/comparacion_val_edge.csv` (VAL-08) es el INT8
ejecutado en la Raspberry; con la de VAL-02, el de la laptop. Antes de escribir, exige
los SHA-256 de origen y corre
`verificar_predicciones.verificar` con el manifiesto completo; si algo falla no toca
la evidencia existente.

    cd Proyecto4
    modelo/.venv/Scripts/python validacion/predicciones_formales.py
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

import comparar_modelos as comp  # noqa: E402
import verificar_predicciones as ver  # noqa: E402

COMPARACION = comp.RESULTADOS / comp.ARCHIVO_CSV


def construir(
    comparacion: list[dict[str, str]], manifiesto_val: dict[str, dict[str, Any]], clases: list[str]
) -> list[dict[str, Any]]:
    """Filas formales: la comparacion de VAL-02 unida al manifiesto por `sample_id`."""
    filas = []
    for c in comparacion:
        m = manifiesto_val[c["sample_id"]]
        fila = {
            "sample_id": c["sample_id"],
            "true_class": c["true_class"],
            "original_prediction": c["original_prediction"],
            "optimized_prediction": c["int8_prediction"],
            "manifest_id": m["manifest_id"],
            "split": m["split"],
            "class_index": m["class_index"],
        }
        for clase in clases:
            fila[f"prob_original_{clase}"] = c[f"prob_original_{clase}"]
        for clase in clases:
            fila[f"prob_optimized_{clase}"] = c[f"prob_int8_{clase}"]
        filas.append(fila)
    return filas


def csv_bytes(filas: list[dict[str, Any]]) -> bytes:
    salida = io.StringIO()
    escritor = csv.DictWriter(salida, fieldnames=list(filas[0]), lineterminator="\n")
    escritor.writeheader()
    escritor.writerows(filas)
    return salida.getvalue().encode("utf-8")


def escribir_todo(archivos: dict[Path, bytes]) -> None:
    """Temporales y `os.replace` por archivo: nada queda a medias si algo se corta."""
    temporales = {}
    try:
        for destino, contenido in archivos.items():
            destino.parent.mkdir(parents=True, exist_ok=True)
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
    parser.add_argument(
        "--comparacion",
        type=Path,
        default=COMPARACION,
        help="CSV de comparar_modelos.py (su .json al lado); VAL-07: la corrida del edge",
    )
    args = parser.parse_args()
    args.comparacion = args.comparacion.resolve()
    sys.stdout.reconfigure(encoding="utf-8")

    cfg = comp.configuracion()
    ruta_manifiesto = cfg["manifiesto"]["ruta"]
    ruta_meta = ruta_manifiesto.with_name("manifest.meta.json")
    try:
        comp.exigir_sha(ruta_manifiesto, cfg["manifiesto"]["sha256"], "manifiesto")
    except comp.ComparacionError as error:
        raise SystemExit(f"FALLA: {error}") from error
    manifiesto = ruta_manifiesto.read_bytes()
    meta_bytes = ruta_meta.read_bytes()
    meta = json.loads(meta_bytes)
    if meta["manifest_hash"] != cfg["manifiesto"]["sha256"]:
        raise SystemExit(f"FALLA: {ruta_meta} no es el meta del manifiesto")

    comparacion_bytes = args.comparacion.read_bytes()
    comparacion_json = json.loads(args.comparacion.with_suffix(".json").read_text("utf-8"))
    if comparacion_json["csv"]["sha256"] != hashlib.sha256(comparacion_bytes).hexdigest():
        raise SystemExit("FALLA: el CSV de la comparacion no es el que registra su JSON")

    lineas = ver.lineas_val(manifiesto)
    extracto = ("\n".join(lineas) + "\n").encode("utf-8")
    manifiesto_val = {}
    for linea in lineas:
        fila = json.loads(linea)
        manifiesto_val[fila["crop_id"]] = {**fila, "manifest_id": meta["manifest_id"]}
    clases = [c["category_name"] for c in sorted(meta["classes"], key=lambda c: c["class_index"])]

    comparacion = list(csv.DictReader(io.StringIO(comparacion_bytes.decode("utf-8"))))
    filas = construir(comparacion, manifiesto_val, clases)
    datos = csv_bytes(filas)
    entorno = comparacion_json["entorno"]
    raiz_repo = comp.RAIZ.parent
    metadatos = {
        "schema_version": 1,
        "tarea": "VAL-03 (#13)",
        "generado_en": datetime.now(UTC).isoformat(timespec="seconds"),
        "comando": "modelo/.venv/Scripts/python validacion/predicciones_formales.py",
        "verificar": "python validacion/verificar_predicciones.py",
        "archivo": {
            "nombre": ver.PREDICCIONES.name,
            "sha256": hashlib.sha256(datos).hexdigest(),
            "filas": len(filas),
            "columnas": list(filas[0]),
        },
        "columnas": {
            "sample_id": "crop_id del manifiesto del P3",
            "true_class": "category_name del manifiesto",
            "original_prediction": "clase predicha por model.pt 1.0.0 del P3 (PyTorch)",
            "optimized_prediction": "clase predicha por la variante INT8 (onnxruntime)",
            "manifest_id, split, class_index": "columnas del manifiesto para la union",
            "prob_original_<clase>, prob_optimized_<clase>": "softmax sin redondear",
        },
        "clases": clases,
        "manifiesto": {
            "manifest_id": meta["manifest_id"],
            "sha256": cfg["manifiesto"]["sha256"],
            "ubicaciones": [
                ruta_manifiesto.relative_to(raiz_repo).as_posix()
                + " (DVC: Proyecto3/data/manifests/m-0.1.3-s42-1.dvc)",
                f"s3://{comp.BUCKET}/datos/p3/manifests/{meta['manifest_id']}/manifest.jsonl",
            ],
            "referencia_p3": "Proyecto3/docs/selection.json (manifest_hash)",
            "extracto_val": {
                "archivo": ver.EXTRACTO.relative_to(comp.RAIZ).as_posix(),
                "sha256": hashlib.sha256(extracto).hexdigest(),
                "lineas": len(lineas),
                "nota": "lineas val del manifiesto, byte a byte y en su orden",
            },
            "meta": {
                "archivo": ver.META.relative_to(comp.RAIZ).as_posix(),
                "sha256": hashlib.sha256(meta_bytes).hexdigest(),
            },
        },
        "exclusiones": [],
        "exclusiones_previas_al_manifiesto": {
            "fuente": "manifest.meta.json -> exclusions",
            "anotaciones": len(meta["exclusions"]),
            "motivos": sorted({e["reason"] for e in meta["exclusions"]}),
            "categorias": [c["category_name"] for c in meta["excluded_categories"]],
            "nota": "el P3 dejo fuera car y bicycle antes de armar el manifiesto; no son "
            "muestras de val, ver Proyecto3/docs/clases.md",
        },
        "modelos": {
            "original": comparacion_json["modelos"]["original"],
            "optimizado": {
                **comparacion_json["modelos"]["int8"],
                "runtime": f"onnxruntime {entorno['onnxruntime']} {entorno['proveedor_onnx']}, "
                "optimizaciones por defecto",
                "maquina": f"{entorno['procesador']} ({entorno['sistema']} {entorno['maquina']})",
                "nota": comparacion_json.get(
                    "nota_optimizado",
                    "corrida en la laptop de VAL; VAL-07 (#19) la regenera en el "
                    "dispositivo, que es la cifra de la rubrica",
                ),
            },
        },
        "fuente": {
            "comparacion_csv": {
                "archivo": args.comparacion.relative_to(comp.RAIZ).as_posix(),
                "sha256": comparacion_json["csv"]["sha256"],
            },
            "comparacion_json_generado_en": comparacion_json["generado_en"],
        },
        "resumen": ver.resumir([{k: str(v) for k, v in f.items()} for f in filas]),
    }
    informe = ver.verificar(datos, metadatos, manifiesto, meta, extracto)
    metadatos["verificacion"] = informe
    for c in informe["comprobaciones"]:
        print(f"[{'ok' if c['ok'] else 'FALLA':5}] {c['id']}")
    if not informe["ok"]:
        raise SystemExit("FALLA: no se escribio evidencia; la anterior queda intacta")

    escribir_todo(
        {
            ver.EXTRACTO: extracto,
            ver.META: meta_bytes,
            ver.PREDICCIONES: datos,
            ver.PREDICCIONES.with_suffix(".json"): (
                json.dumps(metadatos, ensure_ascii=False, indent=2) + "\n"
            ).encode("utf-8"),
        }
    )
    print(f"\n{metadatos['resumen']}")
    print(f"Escrito {ver.PREDICCIONES.relative_to(comp.RAIZ).as_posix()} y su manifiesto")


if __name__ == "__main__":
    main()
