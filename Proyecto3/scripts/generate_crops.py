"""Genera los recortes de las clases fijadas a partir del release aprobado (F2 T07).

1. Verifica el release de punta a punta (`release_local.load_verified_release`).
2. Exige que `config/classes.yaml` cite ese mismo release y huella.
3. Valida todas las cajas contra las clases fijadas y corta cada caja valida.

Salidas:

- `Proyecto3/data/crops/<release>/<clase>/<release>_a<id>.png` y `crops.jsonl`
  (un `CropRecord` por linea): datos derivados, fuera de Git (`/data/`).
- `Proyecto3/reports/crops/<release>/exclusions.csv` y `summary.json`:
  metadatos pequenos que si se versionan como evidencia.

    cd Proyecto2
    PYTHONPATH=../Proyecto3/src .venv/Scripts/python ../Proyecto3/scripts/generate_crops.py \\
        --release 0.1.3 --profile <perfil-aws>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from release_local import ROOT, add_release_arguments, load_verified_release

from p3.data import classes, crops

P3 = ROOT / "Proyecto3"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_release_arguments(parser)
    parser.add_argument("--classes", type=Path, default=P3 / "config" / "classes.yaml")
    parser.add_argument("--out-dir", type=Path, default=P3 / "data" / "crops")
    parser.add_argument("--reports-dir", type=Path, default=P3 / "reports" / "crops")
    args = parser.parse_args()

    verified = load_verified_release(args)
    release = verified.content.release
    config = classes.load_classes(args.classes)
    if (config.release_id, config.dataset_fingerprint) != (
        release.release_id,
        release.dataset_fingerprint,
    ):
        raise SystemExit(
            f"{args.classes} fija clases del release {config.release_id} "
            f"({config.dataset_fingerprint}), no del {release.release_id}."
        )

    coco = verified.content.coco
    sizes = crops.read_image_sizes(coco["images"], verified.images_dir)
    included = {entry.category_id for entry in config.classes}
    result = crops.validate_annotations(coco, included, sizes)

    out_dir = args.out_dir / release.release_id
    records = crops.generate_crops(
        result.valid, verified.images_dir, out_dir, release_id=release.release_id
    )
    index_path = out_dir / "crops.jsonl"
    lines = [json.dumps(asdict(r), sort_keys=True, separators=(",", ":")) for r in records]
    index_path.write_text("".join(line + "\n" for line in lines), encoding="utf-8", newline="\n")

    reports_dir = args.reports_dir / release.release_id
    crops.write_exclusions_csv(result.exclusions, reports_dir / "exclusions.csv")
    per_class = Counter(r.category_name for r in records)
    originals = {
        name: len({r.source_image_id for r in records if r.category_name == name})
        for name in per_class
    }
    summary = {
        "release_id": release.release_id,
        "dataset_fingerprint": release.dataset_fingerprint,
        "archive_uri": verified.archive_uri,
        "archive_version_id": verified.archive_version_id,
        "classes": [c.category_name for c in config.classes],
        "crops": len(records),
        "crops_per_class": dict(sorted(per_class.items())),
        "originals_per_class": dict(sorted(originals.items())),
        "exclusions_per_reason": dict(sorted(Counter(e.reason for e in result.exclusions).items())),
        "crops_jsonl_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
    }
    (reports_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
