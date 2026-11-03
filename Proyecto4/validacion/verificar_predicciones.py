"""Verificacion independiente del archivo de predicciones por muestra (VAL-03, #13).

Pensado para el evaluador: solo usa la biblioteca estandar de Python, sin modelos, torch
ni credenciales. Une `predicciones_val.csv` con el manifiesto de validacion del P3 por
`sample_id` y comprueba, sin confiar en ninguna tabla resumida:

- una fila por muestra: sin IDs duplicados;
- las mismas muestras que `val` del manifiesto: cero faltantes sin justificar, cero
  sobrantes (las exclusiones, si las hay, deben estar documentadas con su motivo);
- `true_class`, `class_index` y `split` iguales a los del manifiesto;
- todas las clases declaradas presentes, con los conteos de `manifest.meta.json`, y
  predicciones solo dentro de esas clases;
- el vinculo con el manifiesto original por SHA-256;
- el resumen declarado (aciertos y acuerdo) recalculado desde las filas.

    cd Proyecto4
    python validacion/verificar_predicciones.py
    python validacion/verificar_predicciones.py \
        --manifiesto ../Proyecto3/data/manifests/m-0.1.3-s42-1/manifest.jsonl

Con el manifiesto completo (quien tenga acceso a los datos del P3), ademas comprueba
su SHA-256 contra el registrado y que el extracto versionado sea exactamente su `val`.
Sale con codigo 1 si alguna comprobacion falla.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

AQUI = Path(__file__).resolve().parent
RESULTADOS = AQUI / "resultados"
PREDICCIONES = RESULTADOS / "predicciones_val.csv"
CARPETA_MANIFIESTO = RESULTADOS / "manifiesto"
EXTRACTO = CARPETA_MANIFIESTO / "manifest_val.jsonl"
META = CARPETA_MANIFIESTO / "manifest.meta.json"

SPLIT = "val"
COLUMNAS_REQUERIDAS = (
    "sample_id",
    "true_class",
    "original_prediction",
    "optimized_prediction",
    "manifest_id",
    "split",
    "class_index",
)


def sha256_bytes(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


def lineas_val(manifiesto: bytes) -> list[str]:
    """Lineas `val` de un manifiesto (completo o extracto), tal cual estan en el archivo."""
    return [
        linea
        for linea in manifiesto.decode("utf-8").splitlines()
        if linea.strip() and json.loads(linea)["split"] == SPLIT
    ]


def verificar(
    predicciones: bytes,
    metadatos: dict[str, Any],
    manifiesto: bytes,
    meta: dict[str, Any],
    extracto: bytes | None = None,
) -> dict[str, Any]:
    """Todas las comprobaciones de VAL-03; `ok` solo si pasan todas.

    `manifiesto` puede ser el extracto versionado o el manifiesto completo del P3. Si es
    el completo y se pasa tambien `extracto`, se comprueba que el extracto sea su `val`.
    """
    resultado: list[dict[str, Any]] = []

    def anotar(id_: str, ok: bool, detalle: str) -> None:
        resultado.append({"id": id_, "ok": bool(ok), "detalle": detalle})

    ref = metadatos["manifiesto"]
    filas = list(csv.DictReader(io.StringIO(predicciones.decode("utf-8"))))
    columnas = set(filas[0]) if filas else set()

    # Formato y vinculo con lo declarado en los metadatos.
    faltan_columnas = [c for c in COLUMNAS_REQUERIDAS if c not in columnas]
    anotar("formato", not faltan_columnas, f"columnas requeridas ausentes: {faltan_columnas}")
    if faltan_columnas:
        return {"ok": False, "comprobaciones": resultado}
    anotar(
        "csv.sha256",
        sha256_bytes(predicciones) == metadatos["archivo"]["sha256"],
        f"SHA-256 del CSV {sha256_bytes(predicciones)}; declarado {metadatos['archivo']['sha256']}",
    )

    sha_manifiesto = sha256_bytes(manifiesto)
    if sha_manifiesto == ref["sha256"]:
        origen = "manifiesto completo del P3"
    elif sha_manifiesto == ref["extracto_val"]["sha256"]:
        origen = "extracto val versionado"
    else:
        origen = None
    anotar(
        "manifiesto.vinculo",
        origen is not None and meta["manifest_hash"] == ref["sha256"],
        f"{origen or 'manifiesto desconocido'} (SHA-256 {sha_manifiesto}); "
        f"{ref['manifest_id']} {ref['sha256'][:12]}..., manifest_hash del meta "
        f"{meta['manifest_hash'][:12]}...",
    )
    val = lineas_val(manifiesto)
    if extracto is not None and origen == "manifiesto completo del P3":
        anotar(
            "manifiesto.extracto",
            extracto.decode("utf-8").splitlines() == val,
            "el extracto versionado es, linea por linea, el val del manifiesto completo",
        )

    # Una fila por muestra y las mismas muestras que val.
    ids = [f["sample_id"] for f in filas]
    duplicados = sorted(k for k, n in Counter(ids).items() if n > 1)
    anotar("ids.duplicados", not duplicados, f"{len(ids)} filas, duplicados: {duplicados}")

    manifiesto_val = {json.loads(x)["crop_id"]: json.loads(x) for x in val}
    excluidas = {e["sample_id"]: e.get("motivo") for e in metadatos.get("exclusiones", [])}
    sin_motivo = sorted(k for k, motivo in excluidas.items() if not motivo)
    faltantes = sorted(set(manifiesto_val) - set(ids) - set(excluidas))
    sobrantes = sorted(set(ids) - set(manifiesto_val))
    excluidas_presentes = sorted(set(excluidas) & set(ids))
    anotar(
        "ids.union_con_manifiesto",
        not faltantes and not sobrantes and not sin_motivo and not excluidas_presentes,
        f"{len(manifiesto_val)} muestras val en el manifiesto; faltantes sin justificar: "
        f"{faltantes}; sobrantes: {sobrantes}; exclusiones documentadas: {len(excluidas)}"
        f"{f', sin motivo: {sin_motivo}' if sin_motivo else ''}",
    )

    # Etiquetas y particion iguales a las del manifiesto.
    distintas = [
        f["sample_id"]
        for f in filas
        if f["sample_id"] in manifiesto_val
        and (
            f["true_class"] != manifiesto_val[f["sample_id"]]["category_name"]
            or int(f["class_index"]) != manifiesto_val[f["sample_id"]]["class_index"]
            or f["split"] != SPLIT
            or f["manifest_id"] != ref["manifest_id"]
        )
    ]
    anotar(
        "etiquetas",
        not distintas,
        f"true_class, class_index, split y manifest_id iguales al manifiesto; distintas: "
        f"{distintas}",
    )

    # Clases declaradas: presentes con los conteos del meta, y predicciones validas.
    declaradas = [
        c["category_name"] for c in sorted(meta["classes"], key=lambda c: c["class_index"])
    ]
    esperado = {
        c: n - sum(1 for k in excluidas if manifiesto_val.get(k, {}).get("category_name") == c)
        for c, n in meta["counts"]["crops"][SPLIT].items()
    }
    # Una clase vaciada por exclusiones documentadas cuenta 0: no es un faltante.
    conteo = Counter(f["true_class"] for f in filas)
    obtenido = {c: conteo[c] for c in esperado} | {
        c: n for c, n in conteo.items() if c not in esperado
    }
    predichas = {f[c] for f in filas for c in ("original_prediction", "optimized_prediction")}
    anotar(
        "clases",
        obtenido == esperado and predichas <= set(declaradas) and declaradas == metadatos["clases"],
        f"declaradas {declaradas}; por clase {dict(sorted(obtenido.items()))} (meta: "
        f"{dict(sorted(esperado.items()))}); predicciones fuera de las clases: "
        f"{sorted(predichas - set(declaradas))}",
    )

    # Resumen declarado, recalculado desde las filas.
    recalculado = resumir(filas)
    anotar(
        "resumen.recalculado",
        recalculado == metadatos["resumen"],
        f"recalculado {recalculado}; declarado {metadatos['resumen']}",
    )
    return {
        "ok": all(c["ok"] for c in resultado),
        "manifiesto_usado": origen,
        "comprobaciones": resultado,
    }


def resumir(filas: list[dict[str, str]]) -> dict[str, Any]:
    """Conteos enteros que cualquiera puede recalcular desde el CSV."""
    return {
        "muestras": len(filas),
        "aciertos_original": sum(f["original_prediction"] == f["true_class"] for f in filas),
        "aciertos_optimizado": sum(f["optimized_prediction"] == f["true_class"] for f in filas),
        "acuerdo_original_optimizado": sum(
            f["original_prediction"] == f["optimized_prediction"] for f in filas
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--predicciones", type=Path, default=PREDICCIONES)
    parser.add_argument(
        "--manifiesto", type=Path, default=EXTRACTO, help="extracto val o manifiesto completo"
    )
    parser.add_argument("--meta", type=Path, default=META)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    metadatos = json.loads(args.predicciones.with_suffix(".json").read_text(encoding="utf-8"))
    informe = verificar(
        args.predicciones.read_bytes(),
        metadatos,
        args.manifiesto.read_bytes(),
        json.loads(args.meta.read_text(encoding="utf-8")),
        EXTRACTO.read_bytes() if args.manifiesto.resolve() != EXTRACTO.resolve() else None,
    )
    print(f"Manifiesto usado: {informe['manifiesto_usado']}")
    for c in informe["comprobaciones"]:
        print(f"[{'ok' if c['ok'] else 'FALLA':5}] {c['id']}: {c['detalle']}")
    print("\nVERIFICADO" if informe["ok"] else "\nNO VERIFICADO")
    if not informe["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
