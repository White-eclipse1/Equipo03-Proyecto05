"""Verificacion de la evidencia del benchmark en el edge (VAL-05, #17; rubrica 3.2).

Solo biblioteca estandar. Comprueba `evidencias/VAL-05/tiempos.csv` y `benchmark.json`
tal como los devuelve la Raspberry:

- el CSV es el que registra el JSON (SHA-256) y trae milisegundos por repeticion;
- por cada modelo medido: al menos 10 calentamientos marcados y al menos 100 mediciones
  validas, y que los calentamientos van antes de las mediciones;
- la identidad de cada modelo (version y SHA-256) es la de la conversion verificada en
  VAL-01, y el INT8 es el que corre en el dispositivo;
- el dispositivo y el runtime estan documentados (hardware, onnxruntime, entrada);
- el `preprocesar.py` que corrio en el dispositivo es el del repositorio (SHA-256).

Un modelo que no pudo cargar en el dispositivo no es una falla si su error quedo
registrado: es la evidencia de incompatibilidad que pide la rubrica (3.1).

    cd Proyecto4
    python validacion/verificar_benchmark.py
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import sys
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[1]  # Proyecto4/
EVIDENCIA = RAIZ / "evidencias" / "VAL-05"
REGISTRO = RAIZ / "modelo" / "registros" / "registro_conversion.json"
PREPROCESAR = RAIZ / "modelo" / "preprocesar.py"
MINIMO_CALENTAMIENTOS = 10
MINIMO_MEDICIONES = 100


def verificar(
    tiempos: bytes,
    evidencia: dict[str, Any],
    registro: dict[str, Any],
    preprocesar_sha256: str | None = None,
) -> dict:
    resultado: list[dict[str, Any]] = []

    def anotar(id_: str, ok: bool, detalle: str) -> None:
        resultado.append({"id": id_, "ok": bool(ok), "detalle": detalle})

    sha = hashlib.sha256(tiempos).hexdigest()
    anotar(
        "tiempos.sha256",
        sha == evidencia["tiempos"]["sha256"],
        f"SHA-256 del CSV {sha}; declarado {evidencia['tiempos']['sha256']}",
    )
    filas = list(csv.DictReader(io.StringIO(tiempos.decode("utf-8"))))
    esperados = {
        "int8": registro["salidas"]["int8"]["sha256"],
        "fp32": registro["salidas"]["fp32"]["sha256"],
    }

    for modelo, datos in evidencia["modelos"].items():
        propias = [f for f in filas if f["modelo"] == modelo]
        if datos.get("estado") != "ok":
            anotar(
                f"{modelo}.incompatibilidad",
                bool(datos.get("error") or datos.get("stderr_final")),
                f"no se midio en el dispositivo; error registrado: "
                f"{datos.get('error') or datos.get('stderr_final', '')[-300:]}",
            )
            continue
        anotar(
            f"{modelo}.identidad",
            datos.get("sha256") is not None and datos.get("sha256") == esperados.get(modelo),
            f"{datos.get('version')} SHA-256 {datos.get('sha256')}; conversion "
            f"{esperados.get(modelo)}",
        )
        calentamientos = [f for f in propias if f["fase"] == "calentamiento"]
        mediciones = [f for f in propias if f["fase"] == "medicion"]
        validas = [f for f in mediciones if f["valido"] == "True"]
        ultimo_calentamiento = max((int(f["indice"]) for f in calentamientos), default=-1)
        primera_medicion = min((int(f["indice"]) for f in mediciones), default=-1)
        anotar(
            f"{modelo}.conteos",
            len(calentamientos) >= MINIMO_CALENTAMIENTOS
            and len(validas) >= MINIMO_MEDICIONES
            and ultimo_calentamiento < primera_medicion,
            f"{len(calentamientos)} calentamientos (min {MINIMO_CALENTAMIENTOS}), "
            f"{len(validas)}/{len(mediciones)} mediciones validas (min {MINIMO_MEDICIONES}); "
            "calentamientos antes de las mediciones",
        )
        tiempos_ok = all(
            math.isfinite(float(f["ms_total"]))
            and float(f["ms_total"]) > 0
            and abs(float(f["ms_preprocesamiento"]) + float(f["ms_inferencia"]))
            <= float(f["ms_total"])
            for f in validas
        )
        anotar(
            f"{modelo}.milisegundos",
            tiempos_ok,
            "cada medicion valida trae ms_total > 0, con preprocesamiento + inferencia "
            "dentro del total",
        )

    hardware, runtime = evidencia.get("hardware", {}), evidencia.get("runtime", {})
    anotar(
        "dispositivo",
        bool(hardware.get("modelo_dispositivo"))
        and hardware.get("arquitectura") == "aarch64"
        and bool(runtime.get("onnxruntime"))
        and evidencia.get("entrada", {}).get("forma") == [1, 3, 224, 224],
        f"{hardware.get('modelo_dispositivo')} ({hardware.get('arquitectura')}), "
        f"{hardware.get('sistema_operativo')}; onnxruntime {runtime.get('onnxruntime')}; "
        f"entrada {evidencia.get('entrada', {}).get('forma')}",
    )
    codigo = evidencia.get("codigo", {})
    if preprocesar_sha256 is not None:
        anotar(
            "preprocesamiento",
            codigo.get("preprocesar.py") == preprocesar_sha256,
            f"preprocesar.py en el dispositivo {codigo.get('preprocesar.py')}; en el repo "
            f"(el validado en VAL-01/VAL-02) {preprocesar_sha256}",
        )
    anotar(
        "int8.medido",
        evidencia["modelos"].get("int8", {}).get("estado") == "ok",
        "la variante optimizada se midio en el dispositivo",
    )
    return {"ok": all(c["ok"] for c in resultado), "comprobaciones": resultado}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--evidencia", type=Path, default=EVIDENCIA)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    informe = verificar(
        (args.evidencia / "tiempos.csv").read_bytes(),
        json.loads((args.evidencia / "benchmark.json").read_text(encoding="utf-8")),
        json.loads(REGISTRO.read_text(encoding="utf-8")),
        hashlib.sha256(PREPROCESAR.read_bytes()).hexdigest(),
    )
    for c in informe["comprobaciones"]:
        print(f"[{'ok' if c['ok'] else 'FALLA':5}] {c['id']}: {c['detalle']}")
    print("\nVERIFICADO" if informe["ok"] else "\nNO VERIFICADO")
    if not informe["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
