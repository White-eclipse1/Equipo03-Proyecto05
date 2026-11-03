"""Release aprobado verificado de punta a punta, para los scripts de F2/F3.

Comun a `count_classes.py` y `generate_crops.py`:

1. compuerta `pass` en el registro de P2 (`versions.json`);
2. `dataset.tar.zst` descargado del bucket de releases (solo lectura) con el
   SHA-256 y la huella de P2 registrados;
3. el COCO de DVC (`Proyecto2/data/raw`, `dvc pull -r prod`) con la MISMA
   huella, para que las imagenes locales sean las del release.

Corre con el entorno de Proyecto2 (`boto3`, `dataset_quality`).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import boto3

from p3.data import releases

ROOT = Path(__file__).resolve().parents[2]
P2 = ROOT / "Proyecto2"
DEFAULT_BUCKET = "dataset-quality-releases-750702272375"


@dataclass(frozen=True)
class VerifiedRelease:
    content: releases.ReleaseContent
    archive_uri: str
    archive_version_id: str | None
    images_dir: Path


def add_release_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--release", required=True)
    parser.add_argument("--profile", required=True, help="perfil de ~/.aws (solo lectura basta)")
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--raw-dir", type=Path, default=P2 / "data" / "raw")
    parser.add_argument("--registry", type=Path, default=P2 / "reports" / "versions.json")


def load_verified_release(args: argparse.Namespace) -> VerifiedRelease:
    release = releases.get_approved_release(releases.load_releases(args.registry), args.release)
    s3 = boto3.Session(profile_name=args.profile).client("s3", region_name=args.region)
    obj = s3.get_object(Bucket=args.bucket, Key=releases.archive_key(release.release_id))
    content = releases.open_release_archive(
        release, obj["Body"].read(), fingerprint=releases.p2_dataset_fingerprint
    )

    local_fingerprint = releases.p2_dataset_fingerprint(
        (args.raw_dir / "annotations.coco.json").read_bytes()
    )
    if local_fingerprint != release.dataset_fingerprint:
        raise SystemExit(
            f"El COCO de {args.raw_dir} (huella {local_fingerprint}) no es el del release "
            f"{release.release_id} ({release.dataset_fingerprint}): corre `dvc pull -r prod`."
        )
    return VerifiedRelease(
        content=content,
        archive_uri=releases.archive_uri(args.bucket, release.release_id),
        archive_version_id=obj.get("VersionId"),
        images_dir=args.raw_dir / "images",
    )
