"""Cierra las dos casillas de F4 T24 que dependen de F6 y F7, con el stack levantado.

1. El modelo que usa el portal es el publicado en S3: lee `registry.json` del
   bucket (perfil de `~/.aws`, solo lectura), descarga el `model.pt` activo,
   calcula su SHA-256 y exige que coincida con el registro, con `selection.json`
   y con el `model_sha256` que devuelve `POST /api/p3/inference`.
2. Las predicciones del portal coinciden con `predictions_test.csv` de F6: manda
   por el portal los recortes de test (o una muestra con `--n`) y compara la
   clase predicha y las probabilidades.

Solo lee: no publica ni activa nada. Imprime el resultado para pegarlo como
evidencia en `docs/fases/F4-modelo-entrenador.md`.

    python scripts/verify_inference.py --profile <perfil-aws> \
        --predictions <predictions_test.csv> [--n 20]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import urllib.request
import uuid
from pathlib import Path

PROYECTO3 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROYECTO3 / "src"))
BUCKET = "dataset-quality-releases-750702272375"
PREFIX = "models/clasificador"


def predict(api: str, path: Path) -> dict:
    boundary = uuid.uuid4().hex
    body = (
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
            "Content-Type: image/png\r\n\r\n"
        ).encode()
        + path.read_bytes()
        + f"\r\n--{boundary}--\r\n".encode()
    )
    request = urllib.request.Request(
        f"{api}/api/p3/inference",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read())


def crop_path(crop_id: str, class_name: str) -> Path:
    release, annotation = crop_id.split(":a")
    return PROYECTO3 / "data" / "crops" / release / class_name / f"{release}_a{annotation}.png"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--selection", type=Path, default=PROYECTO3 / "docs" / "selection.json")
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--n", type=int, default=0, help="0 = todos los recortes de test")
    parser.add_argument("--tolerance", type=float, default=1e-4)
    args = parser.parse_args()

    import boto3

    s3 = boto3.Session(profile_name=args.profile).client("s3", region_name="us-east-1")
    registry = json.loads(
        s3.get_object(Bucket=BUCKET, Key=f"{PREFIX}/registry.json")["Body"].read()
    )
    active = next(v for v in registry["versions"] if v["version"] == registry["active_version"])
    # Mismo criterio que el servicio: por VersionId si las credenciales lo permiten; si no,
    # la version actual, que debe ser la registrada.
    from p3.inference.settings import S3ObjectStore

    store = S3ObjectStore.from_client(s3)
    downloaded = hashlib.sha256(
        store.get_bytes(BUCKET, active["key"], active.get("s3_version_id"))
    ).hexdigest()
    obj = {"VersionId": active.get("s3_version_id")}
    selection = json.loads(args.selection.read_text(encoding="utf-8"))
    print(
        f"version activa {active['version']}: s3://{BUCKET}/{active['key']} "
        f"VersionId={obj.get('VersionId')}"
    )
    print(f"  SHA-256 descargado  {downloaded}")
    print(f"  SHA-256 registro    {active['sha256']}")
    print(f"  SHA-256 seleccion   {selection['checkpoint_sha256']}")
    problems = []
    if not downloaded == active["sha256"] == selection["checkpoint_sha256"]:
        problems.append("el SHA-256 del objeto no coincide con el registro o la seleccion")

    with args.predictions.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if args.n:
        rows = rows[: args.n]
    classes = [k.removeprefix("prob_") for k in rows[0] if k.startswith("prob_")]
    iguales = 0
    for row in rows:
        path = crop_path(row["crop_id"], row["clase_real"])
        answer = predict(args.api, path)
        if answer["model_sha256"] != downloaded:
            problems.append(
                f"{row['crop_id']}: el portal uso otro modelo ({answer['model_sha256']})"
            )
            continue
        same_class = answer["predicted_class"] == row["clase_predicha"]
        same_probs = all(
            abs(answer["probabilities"][c] - float(row[f"prob_{c}"])) <= args.tolerance
            for c in classes
        )
        if same_class and same_probs:
            iguales += 1
        else:
            problems.append(
                f"{row['crop_id']}: portal {answer['predicted_class']} "
                f"vs csv {row['clase_predicha']}"
            )
    print(f"{iguales}/{len(rows)} predicciones del portal coinciden con {args.predictions.name}")
    for problem in problems[:10]:
        print("  PROBLEMA:", problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
