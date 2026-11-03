"""Cuenta originales validos por clase en un release aprobado y fija las clases (F2 T06).

Recorrido, todo verificado contra el registro de P2 (`versions.json`):

1. El release debe tener compuerta `pass` (`get_approved_release`).
2. Su `dataset.tar.zst` se descarga del bucket de releases y se acepta solo si
   el SHA-256 y la huella de P2 del COCO coinciden con el registro.
3. Las imagenes vienen de DVC (`Proyecto2/data/raw`, `dvc pull -r prod`): el
   COCO local debe tener la MISMA huella, o las imagenes no son de ese release.
4. Se validan TODAS las cajas (`validate_annotations`) y se cuentan originales
   distintos con al menos una caja valida por categoria.
5. `select_classes` aplica el umbral de 300; con `--write` se escribe
   `config/classes.yaml`.

Corre con el entorno de Proyecto2 (tiene `boto3` y `dataset_quality`, que da
la huella de P2) y `Proyecto3/src` en el path:

    cd Proyecto2
    PYTHONPATH=../Proyecto3/src .venv/Scripts/python ../Proyecto3/scripts/count_classes.py \\
        --release 0.1.3 --profile <perfil-aws> [--write]

Solo LEE de S3. Las credenciales salen del perfil de `~/.aws`, nunca del repo.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from release_local import ROOT, add_release_arguments, load_verified_release

from p3.data import classes, crops


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_release_arguments(parser)
    parser.add_argument("--min-originals", type=int, default=classes.MIN_ORIGINALS)
    parser.add_argument(
        "--decided-at",
        type=date.fromisoformat,
        default=datetime.now().astimezone().date(),
        help="fecha de la decision (por defecto hoy en hora local, como la del commit)",
    )
    parser.add_argument(
        "--write", type=Path, nargs="?", const=ROOT / "Proyecto3" / "config" / "classes.yaml"
    )
    args = parser.parse_args()

    verified = load_verified_release(args)
    content = verified.content
    release = content.release
    sizes_dir = verified.images_dir

    coco = content.coco
    names = {c["id"]: c["name"] for c in coco["categories"]}
    sizes = crops.read_image_sizes(coco["images"], sizes_dir)
    result = crops.validate_annotations(coco, set(names), sizes)
    originals = classes.originals_per_category(result.valid)
    decisions = classes.select_classes(originals, names, min_originals=args.min_originals)

    reasons: dict[str, int] = {}
    for exclusion in result.exclusions:
        reasons[exclusion.reason] = reasons.get(exclusion.reason, 0) + 1
    report = {
        "release_id": release.release_id,
        "dataset_fingerprint": release.dataset_fingerprint,
        "quality_status": release.quality_status,
        "quality_report_fingerprint": release.quality_report_fingerprint,
        "archive": {
            "uri": verified.archive_uri,
            "version_id": verified.archive_version_id,
            "sha256": release.archive_sha256,
        },
        "local_coco_fingerprint_matches": True,
        "images_in_coco": len(coco["images"]),
        "images_readable": len(sizes),
        "annotations": len(coco["annotations"]),
        "valid_boxes": len(result.valid),
        "exclusions_by_reason": dict(sorted(reasons.items())),
        "min_originals": args.min_originals,
        "classes": [
            {
                "category_id": d.category_id,
                "category_name": d.category_name,
                "originals_with_valid_box": d.originals,
                "valid_boxes": sum(1 for c in result.valid if c.category_id == d.category_id),
                "included": d.included,
                "reason": d.reason,
            }
            for d in decisions
        ],
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))

    if args.write:
        config = classes.build_config(
            decisions,
            release_id=release.release_id,
            dataset_fingerprint=release.dataset_fingerprint,
            decided_at=args.decided_at,
            min_originals=args.min_originals,
        )
        args.write.parent.mkdir(parents=True, exist_ok=True)
        classes.dump_classes(config, args.write)
        print(f"Escrito {args.write}")


if __name__ == "__main__":
    main()
