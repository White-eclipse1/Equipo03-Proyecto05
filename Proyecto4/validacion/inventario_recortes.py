"""Inventario congelado de los recortes del P3 con el SHA-256 de cada imagen (VAL-02, #2).

El P3 fija `crops.jsonl` (y con el las dimensiones de cada recorte) por SHA-256, pero no
guarda un hash por imagen. Este script lo congela una vez, a partir de la copia en
`s3://<bucket>/datos/p3/crops/<release>/`, para que el comparador verifique cada PNG
por hash y no solo por dimensiones:

- exige el SHA-256 del manifiesto y de `crops.jsonl` (los del P3);
- calcula SHA-256, MD5 y bytes de cada recorte local;
- lee de S3 el `VersionId` y el ETag vigentes de cada objeto y exige que el ETag sea el
  MD5 del archivo (subida en una parte): la copia local es la que esta en S3;
- escribe `validacion/registros/recortes_<release>.jsonl` (una fila por recorte, con su
  particion segun el manifiesto) y `recortes_<release>.json` (resumen y SHA-256 del
  inventario).

Que esas imagenes son las que uso el P3 lo comprueba, por otro camino, la huella de
validacion del comparador (accuracy y val_loss del modelo original iguales a los de
`Proyecto3/docs/selection.json`).

    cd Proyecto4
    modelo/.venv/Scripts/python validacion/inventario_recortes.py --profile <perfil-cuenta-p4>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

import comparar_modelos as comp  # noqa: E402


def hashes(ruta: Path) -> tuple[str, str, int]:
    sha, md5, total = hashlib.sha256(), hashlib.md5(), 0
    with ruta.open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(1 << 20), b""):
            sha.update(bloque)
            md5.update(bloque)
            total += len(bloque)
    return sha.hexdigest(), md5.hexdigest(), total


def objetos_s3(s3: Any, bucket: str, prefijo: str) -> dict[str, dict[str, str]]:
    """Version vigente de cada objeto bajo `prefijo`: llave relativa -> VersionId y ETag."""
    vigentes: dict[str, dict[str, str]] = {}
    for pagina in s3.get_paginator("list_object_versions").paginate(Bucket=bucket, Prefix=prefijo):
        for v in pagina.get("Versions", []):
            if v["IsLatest"]:
                vigentes[v["Key"][len(prefijo) :]] = {
                    "version_id": v["VersionId"],
                    "etag": v["ETag"].strip('"'),
                }
    return vigentes


def inventario(
    recortes: Path, manifiesto: list[dict[str, Any]], s3: dict[str, dict[str, str]]
) -> tuple[list[dict[str, Any]], list[str], int]:
    """Filas del inventario, problemas encontrados y cuantos ETag se compararon con el MD5."""
    split_de = {f["crop_id"]: f["split"] for f in manifiesto}
    filas, problemas, etags = [], [], 0
    for r in comp.leer_jsonl(recortes / "crops.jsonl"):
        ruta = recortes / r["crop_path"]
        if not ruta.is_file():
            problemas.append(f"{r['crop_id']}: no existe {r['crop_path']}")
            continue
        sha, md5, total = hashes(ruta)
        objeto = s3.get(r["crop_path"])
        if objeto is None:
            problemas.append(f"{r['crop_id']}: {r['crop_path']} no esta en S3")
        elif "-" not in objeto["etag"]:  # ETag de una subida en una parte = MD5
            etags += 1
            if objeto["etag"] != md5:
                problemas.append(f"{r['crop_id']}: MD5 local {md5} != ETag {objeto['etag']}")
        filas.append(
            {
                "crop_id": r["crop_id"],
                "crop_path": r["crop_path"],
                "split": split_de.get(r["crop_id"], "ausente"),
                "bytes": total,
                "sha256": sha,
                "s3_version_id": objeto["version_id"] if objeto else None,
            }
        )
    return filas, problemas, etags


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--profile", required=True, help="perfil de AWS de la cuenta del P4")
    parser.add_argument("--bucket", default=comp.BUCKET)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    cfg = comp.configuracion()
    try:
        comp.exigir_sha(cfg["manifiesto"]["ruta"], cfg["manifiesto"]["sha256"], "manifiesto")
        comp.exigir_sha(cfg["recortes"] / "crops.jsonl", cfg["crops_jsonl_sha256"], "crops.jsonl")
    except comp.ComparacionError as error:
        raise SystemExit(f"FALLA: {error}") from error

    import boto3

    release = cfg["recortes"].name
    prefijo = f"datos/p3/crops/{release}/"
    s3 = boto3.Session(profile_name=args.profile).client("s3")
    filas, problemas, etags = inventario(
        cfg["recortes"],
        comp.leer_jsonl(cfg["manifiesto"]["ruta"]),
        objetos_s3(s3, args.bucket, prefijo),
    )
    if problemas:
        raise SystemExit("FALLA:\n" + "\n".join(problemas))

    datos = "".join(json.dumps(f, ensure_ascii=False) + "\n" for f in filas).encode("utf-8")
    destino = comp.REGISTROS_VAL / f"recortes_{release}.jsonl"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(datos)
    resumen = {
        "schema_version": 1,
        "tarea": "VAL-02 (#2)",
        "generado_en": datetime.now(UTC).isoformat(timespec="seconds"),
        "fuente": f"s3://{args.bucket}/{prefijo}",
        "crops_jsonl_sha256": cfg["crops_jsonl_sha256"],
        "manifiesto_sha256": cfg["manifiesto"]["sha256"],
        "recortes": len(filas),
        "por_split": dict(sorted(Counter(f["split"] for f in filas).items())),
        "etag_igual_a_md5_local": etags,
        "inventario": {"archivo": destino.name, "sha256": hashlib.sha256(datos).hexdigest()},
    }
    destino.with_suffix(".json").write_bytes(
        (json.dumps(resumen, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )
    print(json.dumps(resumen, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
