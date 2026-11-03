"""Demostracion de 1.1: cambiar el release seleccionado cambia el COCO y los conteos.

En el bucket del equipo solo estan publicados 0.1.2 y 0.1.3, y comparten la
misma huella y los mismos conteos (docs/decisiones.md §1), asi que con ellos
el cambio de version no se nota. La rubrica pide comprobarlo "en un entorno de
prueba": este script arma, en un directorio temporal, un registro
`versions.json` y dos releases derivados del fixture (`tests/fixtures/p3/`),
empaquetados igual que `dq release`, y los lee con el MISMO codigo que usa el
portal (`p3.data.releases` + `p3.data.crops`). No toca S3 ni el registro real.

    python scripts/demo_cambio_release.py

La huella se calcula como JSON canonico: el fixture trae a proposito cajas
invalidas que el modelo COCO de P2 rechaza al completo, por lo que
`p2_dataset_fingerprint` no aplica aqui. Con el release real se usa la de P2.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

import zstandard

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from p3.data import crops, releases  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "p3"
INCLUIDAS = {2, 3, 4}  # person, dog, cat (docs/contratos.md §1)


def canonical_fingerprint(coco_bytes: bytes) -> str:
    canonical = json.dumps(json.loads(coco_bytes), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_archive(coco: dict[str, Any]) -> bytes:
    members = {
        "annotations.coco.json": json.dumps(coco).encode("utf-8"),
        "quality.json": json.dumps({"status": "pass"}).encode("utf-8"),
        "splits.json": json.dumps({"assignments": []}).encode("utf-8"),
    }
    raw = io.BytesIO()
    with (
        zstandard.ZstdCompressor().stream_writer(raw, closefd=False) as compressed,
        tarfile.open(fileobj=compressed, mode="w") as archive,
    ):
        for name in sorted(members):
            info = tarfile.TarInfo(name)
            info.size = len(members[name])
            archive.addfile(info, io.BytesIO(members[name]))
    return raw.getvalue()


def version_entry(version: str, coco: dict[str, Any], archive: bytes) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "version": version,
        "created_at": "2026-09-25T00:00:00Z",
        "dataset_fingerprint": canonical_fingerprint(json.dumps(coco).encode("utf-8")),
        "quality_report_fingerprint": hashlib.sha256(b"quality").hexdigest(),
        "quality_status": "pass",
        "counts": {
            "images": len(coco["images"]),
            "annotations": len(coco["annotations"]),
            "categories": len(coco["categories"]),
        },
        "archive_sha256": hashlib.sha256(archive).hexdigest(),
        "published_in": [{"remote": "prueba", "storage_uri": "", "published_at": ""}],
    }


def main() -> None:
    full = json.loads((FIXTURE / "annotations.coco.json").read_text(encoding="utf-8"))
    # Segundo release: el mismo dataset sin las imagenes 1 a 10.
    reduced = copy.deepcopy(full)
    reduced["images"] = [i for i in full["images"] if i["id"] > 10]
    reduced["annotations"] = [a for a in full["annotations"] if a["image_id"] > 10]

    with tempfile.TemporaryDirectory() as tmp:
        bucket = Path(tmp) / "bucket"
        entries = []
        for version, coco in (("9.0.0", full), ("9.1.0", reduced)):
            archive = build_archive(coco)
            path = bucket / releases.archive_key(version)
            path.parent.mkdir(parents=True)
            path.write_bytes(archive)
            entries.append(version_entry(version, coco, archive))
        registry = Path(tmp) / "versions.json"
        registry.write_text(json.dumps({"schema_version": 1, "versions": entries}))

        loaded = releases.load_releases(registry)
        sizes_cache: dict[int, tuple[int, int]] | None = None
        print(
            f"{'release':<8} {'sha256 archivo':<14} {'imagenes':>8} {'cajas':>6} "
            f"{'validas':>7} {'excluidas':>9}  validas por clase"
        )
        for version in ("9.0.0", "9.1.0"):
            release = releases.get_approved_release(loaded, version)
            archive = (bucket / releases.archive_key(version)).read_bytes()
            content = releases.open_release_archive(
                release, archive, fingerprint=canonical_fingerprint
            )
            if sizes_cache is None:
                sizes_cache = crops.read_image_sizes(full["images"], FIXTURE / "images")
            result = crops.validate_annotations(content.coco, INCLUIDAS, sizes_cache)
            por_clase: dict[str, int] = {}
            for crop in result.valid:
                por_clase[crop.category_name] = por_clase.get(crop.category_name, 0) + 1
            counts = releases.coco_counts(content.coco)
            print(
                f"{version:<8} {release.archive_sha256[:12]:<14} {counts['images']:>8} "
                f"{counts['annotations']:>6} {len(result.valid):>7} "
                f"{len(result.exclusions):>9}  {dict(sorted(por_clase.items()))}"
            )


if __name__ == "__main__":
    main()
