"""Paquete de entradas conocidas para verificar el preprocesamiento en el edge (VAL-07, #19).

Junta en `validacion/entradas_edge/` (ignorado por Git) las entradas que se pasan por el
mismo `edge/verificar_preprocesamiento.py` en la Raspberry y en la laptop:

- los 292 recortes `val` del manifiesto del P3, tal cual (verificados contra el
  inventario congelado de VAL-02), con su clase real;
- las 3 fotos de la camara de EDGE-03 (`cat`, `dog`, `person`), con la clase que
  presento el operador.

Escribe `entradas.jsonl` (id, tipo, archivo, SHA-256, bytes, clase) dentro del paquete y
una copia versionada en `validacion/registros/entradas_edge.jsonl`, y comprime el paquete
en `validacion/entradas_edge.zip` (ignorado) para llevarlo al dispositivo. Las entradas
sinteticas no van en el paquete: el script del edge las genera igual en cualquier maquina.

    cd Proyecto4
    python validacion/preparar_entradas_edge.py
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

import comparar_modelos as comp  # noqa: E402

RAIZ = AQUI.parent  # Proyecto4/
PAQUETE = AQUI / "entradas_edge"
ZIP = AQUI / "entradas_edge.zip"
INDICE_VERSIONADO = AQUI / "registros" / "entradas_edge.jsonl"
FOTOS_EDGE03 = RAIZ / "evidencias" / "EDGE-03"


def sha256(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = comp.configuracion()
    try:
        comp.exigir_sha(cfg["manifiesto"]["ruta"], cfg["manifiesto"]["sha256"], "manifiesto")
        comp.exigir_sha(cfg["recortes"] / "crops.jsonl", cfg["crops_jsonl_sha256"], "crops.jsonl")
        inventario = comp.cargar_inventario(cfg["inventario"])
    except comp.ComparacionError as error:
        raise SystemExit(f"FALLA: {error}") from error

    clases = ["cat", "dog", "person"]
    muestras, faltantes = comp.muestras_val(
        comp.leer_jsonl(cfg["manifiesto"]["ruta"]), cfg["recortes"], clases
    )
    if faltantes or comp.hashes_distintos(muestras, inventario):
        raise SystemExit("FALLA: recortes de val faltantes o distintos al inventario")

    if PAQUETE.exists():
        shutil.rmtree(PAQUETE)
    entradas = []
    for m in muestras:
        datos = m["ruta"].read_bytes()
        archivo = f"val/{m['ruta'].parent.name}/{m['ruta'].name}"
        entradas.append(
            {
                "id": m["sample_id"],
                "tipo": "val",
                "archivo": archivo,
                "sha256": sha256(datos),
                "bytes": len(datos),
                "clase": m["true_class"],
                "origen": "recorte val del manifiesto m-0.1.3-s42-1",
            }
        )
        (PAQUETE / archivo).parent.mkdir(parents=True, exist_ok=True)
        (PAQUETE / archivo).write_bytes(datos)
    for clase in clases:
        for foto in sorted((FOTOS_EDGE03 / clase).glob("*.jpg")):
            datos = foto.read_bytes()
            archivo = f"camara/{clase}/{foto.name}"
            entradas.append(
                {
                    "id": foto.stem,
                    "tipo": "camara",
                    "archivo": archivo,
                    "sha256": sha256(datos),
                    "bytes": len(datos),
                    "clase": clase,
                    "origen": "foto de la camara del edge (EDGE-03), clase presentada",
                }
            )
            (PAQUETE / archivo).parent.mkdir(parents=True, exist_ok=True)
            (PAQUETE / archivo).write_bytes(datos)

    indice = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entradas).encode("utf-8")
    (PAQUETE / "entradas.jsonl").write_bytes(indice)
    INDICE_VERSIONADO.write_bytes(indice)
    ZIP.unlink(missing_ok=True)
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as z:
        for ruta in sorted(PAQUETE.rglob("*")):
            if ruta.is_file():
                z.write(ruta, f"entradas_edge/{ruta.relative_to(PAQUETE).as_posix()}")
    print(f"{len(entradas)} entradas ({len(muestras)} val, {len(entradas) - len(muestras)} camara)")
    print(f"indice SHA-256 {sha256(indice)}")
    print(
        f"zip {ZIP.relative_to(RAIZ).as_posix()}: {ZIP.stat().st_size} bytes, SHA-256 "
        f"{sha256(ZIP.read_bytes())}"
    )


if __name__ == "__main__":
    main()
