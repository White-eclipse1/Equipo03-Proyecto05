"""Promover un archivo existente a AWS sin generar otra version."""

from __future__ import annotations

import hashlib
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

import zstandard

from dataset_quality.models.coco import CocoDataset
from dataset_quality.models.quality import QualityReport
from dataset_quality.models.splits import SplitsManifest
from dataset_quality.models.versions import DatasetVersion, VersionsManifest
from dataset_quality.settings import get_settings
from dataset_quality.storage import file_sha256, get_s3_client
from dataset_quality.tiers import release
from dataset_quality.tiers.gate import dataset_fingerprint


def verify_archive(path: Path, entry: DatasetVersion) -> None:
    """Valida el contenido contra las tres huellas del registro, sin extraerlo."""
    if entry.archive_sha256 is not None and file_sha256(path) != entry.archive_sha256:
        raise ValueError("El archivo no coincide con el SHA-256 del release")
    documents: dict[str, bytes] = {}
    required = {"annotations.coco.json", "quality.json", "splits.json"}
    with (
        path.open("rb") as raw,
        zstandard.ZstdDecompressor().stream_reader(raw) as decompressed,
        tarfile.open(fileobj=decompressed, mode="r|") as archive,
    ):
        for member in archive:
            if member.name in required:
                if member.name in documents or not member.isfile():
                    raise ValueError(f"Miembro invalido en el archivo: {member.name}")
                body = archive.extractfile(member)
                if body is None:
                    raise ValueError(f"No se pudo leer {member.name}")
                documents[member.name] = body.read()
    if set(documents) != required:
        raise ValueError("El archivo no contiene los tres documentos del release")
    dataset = CocoDataset.model_validate_json(documents["annotations.coco.json"])
    report = QualityReport.model_validate_json(documents["quality.json"])
    splits = SplitsManifest.model_validate_json(documents["splits.json"])
    if (
        dataset_fingerprint(dataset) != entry.dataset_fingerprint
        or report.dataset_fingerprint != entry.dataset_fingerprint
        or hashlib.sha256(documents["quality.json"]).hexdigest() != entry.quality_report_fingerprint
        or hashlib.sha256(documents["splits.json"]).hexdigest() != entry.splits_fingerprint
    ):
        raise ValueError("El archivo no coincide con las huellas de la version")
    counts = {
        "images": len(dataset.images),
        "annotations": len(dataset.annotations),
        "categories": len(dataset.categories),
    }
    if counts != entry.counts.model_dump() or counts != report.totals.model_dump():
        raise ValueError("Los conteos del archivo no coinciden con la version")
    if {a.image_id for a in splits.assignments} != {i.id for i in dataset.images}:
        raise ValueError("Los splits del archivo no corresponden al dataset")
    summary = release.summarize_quality(dataset, report)
    if entry.quality_status != "pass" or report.status != "pass":
        raise ValueError("No se puede promover una version con calidad en fail")
    if sum(n >= 300 for n in summary.distinct_images_per_class.values()) < 2:
        raise ValueError("PROD exige 300 imagenes distintas en al menos dos clases")
    check = next((c for c in report.checks if c.name == "min_images_per_class"), None)
    if (
        check is None
        or check.status != "pass"
        or check.severity != "error"
        or check.threshold < 300
    ):
        raise ValueError("El release no paso la compuerta del minimo de 300 imagenes")
    if entry.quality_summary is not None and entry.quality_summary != summary:
        raise ValueError("El resumen de calidad no corresponde al archivo publicado")


def run(
    version: str,
    *,
    out: Path = release.DEFAULT_VERSIONS_PATH,
    profile: str | None = None,
    archive_path: Path | None = None,
    dry_run: bool = False,
) -> DatasetVersion:
    manifest = release.load_manifest(out)
    entry = next((v for v in manifest.versions if v.version == version), None)
    if entry is None:
        raise ValueError(f"Version desconocida: {version}")
    source = next((p for p in entry.published_in if p.remote == "dev"), None)
    if source is None:
        raise ValueError("La version no esta publicada en DEV")
    bucket = get_settings().prod_bucket_releases
    uri = release.storage_uri(bucket, version)
    existing = next((p for p in entry.published_in if p.remote == "prod"), None)
    if existing is not None and existing.storage_uri != uri:
        raise ValueError("La version registra una publicacion PROD en otro destino")
    with TemporaryDirectory(prefix="dq-promote-") as directory:
        path = archive_path or Path(directory) / release.ARCHIVE_NAME
        if archive_path is None:
            location = urlsplit(source.storage_uri)
            get_s3_client().download_file(location.netloc, location.path.lstrip("/"), str(path))
        verify_archive(path, entry)
        if dry_run:
            return entry
        release.upload_archive(path, bucket, version, remote="prod", profile=profile)
    if existing is not None:
        return entry
    promoted = entry.model_copy(
        update={"published_in": [*entry.published_in, release.publication("prod", bucket, version)]}
    )
    updated = VersionsManifest(
        versions=[promoted if v.version == version else v for v in manifest.versions]
    )
    release.write_manifest(updated, out)
    return promoted
