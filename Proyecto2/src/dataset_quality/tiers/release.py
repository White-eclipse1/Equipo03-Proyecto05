"""Tier 5 — publicar una version del dataset.

Empaqueta el dataset validado junto con sus dos reportes (`quality.json`,
`splits.json`) en un artefacto inmutable y content-addressed, lo sube al
almacen de objetos y añade la entrada a `versions.json` — el tercer y ultimo
contrato congelado que quedaba sin productor (Frente 6, `dvc`).

Tres propiedades que exige la tarjeta:

  - **Pipeline por etapas**: este modulo es la ultima etapa del grafo de DVC
    (`analyze -> gate -> split -> release`); `dq ingest` queda fuera porque
    escribe en MinIO/MariaDB y no es una funcion pura de archivo a archivo.
  - **Datos fuera de Git**: el `.tar.zst` va al bucket de releases, nunca al
    repositorio; lo que se versiona en Git es `dvc.lock` (el hash) y este
    `versions.json` (el registro).
  - **El mismo content hash en cualquier remote**: el archivo se arma con
    metadata determinista (mtime fijo, orden fijo de miembros), asi que el
    mismo contenido da siempre el mismo `dataset_fingerprint` sin importar a
    que remote (`dev` o `prod`) se suba despues.

Salida: `reports/versions.json` + `s3://<bucket-releases>/<version>/dataset.tar.zst`.
"""

from __future__ import annotations

import base64
import hashlib
import tarfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import zstandard
from botocore.exceptions import ClientError

from dataset_quality.models.coco import CocoDataset, load_coco
from dataset_quality.models.quality import QualityReport
from dataset_quality.models.splits import SplitsManifest
from dataset_quality.models.versions import (
    REMOTE_POR_DEFECTO,
    DatasetCounts,
    DatasetVersion,
    RemotePublication,
    VersionQualitySummary,
    VersionsManifest,
    backfill_remotes,
)
from dataset_quality.storage import (
    ensure_bucket,
    file_sha256,
    get_prod_s3_client,
    get_s3_client,
)
from dataset_quality.tiers.gate import dataset_fingerprint as fingerprint_dataset

DEFAULT_VERSIONS_PATH = Path("reports") / "versions.json"
ARCHIVE_NAME = "dataset.tar.zst"

Bump = str  # "patch" | "minor" | "major"


# Nombre del remote al que publica `dq release` mientras no se le diga otro.
# `dev` es el MinIO del compose; `prod` es el bucket de S3 de verdad. Vive en
# el modulo del contrato porque la migracion de lectura tambien lo necesita.
DEFAULT_REMOTE = REMOTE_POR_DEFECTO


def load_manifest(path: Path = DEFAULT_VERSIONS_PATH) -> VersionsManifest:
    """Lee `versions.json`, o un registro vacio si nunca se publico nada.

    A las entradas anteriores a `published_in` se les rellena el remote `dev`.
    No es inventar un dato: hasta que existio este campo, `dq release` subia a
    un unico destino — el bucket de releases de la configuracion, que es el
    MinIO local — y `storage_uri` ya guardaba la URI exacta de esa copia. Lo
    unico que faltaba era el nombre del remote. La alternativa, dejarlas en
    blanco, haria que la pantalla mostrara como "sin publicar" versiones que si
    lo estan.
    """
    if not path.is_file():
        return VersionsManifest(versions=[])

    manifest = VersionsManifest.model_validate_json(path.read_text(encoding="utf-8"))
    return backfill_remotes(manifest, DEFAULT_REMOTE)


def next_version(manifest: VersionsManifest, bump: Bump = "patch") -> str:
    """Siguiente semver a partir de la ultima entrada del registro.

    Sin historial, arranca en `0.1.0`. El orden cronologico ya lo garantiza
    `VersionsManifest`, asi que la ultima entrada de la lista es la mas
    reciente por construccion — no hace falta volver a ordenar aqui.
    """
    if not manifest.versions:
        return "0.1.0"

    major, minor, patch = (int(part) for part in manifest.versions[-1].version.split("."))
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def build_archive(
    *,
    coco_path: Path,
    quality_path: Path,
    splits_path: Path,
    dest: Path,
) -> Path:
    """Empaqueta los tres artefactos en un `.tar.zst` deterministico.

    Determinista quiere decir: mismo contenido -> mismos bytes de archivo,
    sin importar cuando ni donde se corra. Dos cosas lo rompen si no se
    controlan explicitamente: el orden de iteracion del filesystem (se fija
    ordenando los miembros por nombre) y el mtime de cada entrada (tar lo
    incluye en la cabecera; se fija a época 0). Sin esto, el "mismo content
    hash entre remotes" de la tarjeta seria falso en la practica aunque el
    dataset no hubiera cambiado ni un byte.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    members = sorted(
        [
            (coco_path, "annotations.coco.json"),
            (quality_path, "quality.json"),
            (splits_path, "splits.json"),
        ],
        key=lambda pair: pair[1],
    )

    compressor = zstandard.ZstdCompressor(level=19)
    with (
        dest.open("wb") as raw,
        compressor.stream_writer(raw) as compressed,
        tarfile.open(fileobj=compressed, mode="w") as archive,
    ):
        for source, arcname in members:
            info = archive.gettarinfo(source, arcname=arcname)
            info.mtime = 0
            info.mode = 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            with source.open("rb") as handle:
                archive.addfile(info, handle)

    return dest


def storage_uri(bucket: str, version: str) -> str:
    return f"s3://{bucket}/{version}/{ARCHIVE_NAME}"


def build_entry(
    *,
    version: str,
    dataset_fingerprint: str,
    quality_report: QualityReport,
    quality_report_fingerprint: str,
    splits_fingerprint: str,
    bucket: str,
    notes: str | None,
    published_in: list[RemotePublication] | None = None,
    quality_summary: VersionQualitySummary | None = None,
    archive_sha256: str | None = None,
) -> DatasetVersion:
    """Ensambla la entrada de `versions.json`. Funcion pura: sin disco ni red.

    `published_in` llega vacio a proposito cuando la subida todavia no ocurrio:
    la entrada describe la version, y donde esta publicada es un hecho aparte
    que solo se registra despues de que el upload haya terminado bien. Un
    `--dry-run` no publica nada y por eso no registra ningun remote.
    """
    return DatasetVersion(
        version=version,
        created_at=datetime.now(UTC),
        published_in=published_in or [],
        dataset_fingerprint=dataset_fingerprint,
        quality_report_fingerprint=quality_report_fingerprint,
        splits_fingerprint=splits_fingerprint,
        storage_uri=storage_uri(bucket, version),
        quality_status=quality_report.status,
        counts=DatasetCounts(
            images=quality_report.totals.images,
            annotations=quality_report.totals.annotations,
            categories=quality_report.totals.categories,
        ),
        notes=notes,
        quality_summary=quality_summary,
        archive_sha256=archive_sha256,
    )


def summarize_quality(dataset: CocoDataset, report: QualityReport) -> VersionQualitySummary:
    """Imagenes por clase tras colapsar las copias identificadas en el reporte."""
    from dataset_quality.analyzers.structural import images_per_class

    duplicates = next((c for c in report.checks if c.name == "duplicates"), None)
    removed = set(duplicates.offenders) if duplicates and duplicates.status != "skipped" else set()
    distinct = dataset.model_copy(
        update={
            "annotations": [a for a in dataset.annotations if a.image_id not in removed],
        }
    )
    small = next((c for c in report.checks if c.name == "small_objects"), None)
    return VersionQualitySummary(
        distinct_images_per_class=images_per_class(distinct),
        small_objects_ratio=small.observed if small and small.status != "skipped" else None,
    )


def append_entry(manifest: VersionsManifest, entry: DatasetVersion) -> VersionsManifest:
    """Añade una entrada al registro. El validador exige orden cronologico."""
    return VersionsManifest(versions=[*manifest.versions, entry])


def write_manifest(manifest: VersionsManifest, path: Path = DEFAULT_VERSIONS_PATH) -> Path:
    """Escribe `versions.json`. El archivo se puede releer con su propio modelo."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8", newline="\n")
    return path


def upload_archive(
    archive_path: Path,
    bucket: str,
    version: str,
    *,
    remote: str = DEFAULT_REMOTE,
    profile: str | None = None,
) -> None:
    """Publica los mismos bytes sin sobrescribir un release distinto."""
    if remote == "dev":
        ensure_bucket(bucket)
        client = get_s3_client()
    elif remote == "prod":
        client = get_prod_s3_client(profile)
    else:
        raise ValueError(f"Remote desconocido: {remote}")
    key = f"{version}/{ARCHIVE_NAME}"
    expected = file_sha256(archive_path)

    def verify_existing() -> bool:
        try:
            response = client.get_object(Bucket=bucket, Key=key)
        except ClientError as error:
            if error.response["Error"]["Code"] in {"404", "NoSuchKey"}:
                return False
            raise
        with response["Body"] as body:
            digest = hashlib.sha256()
            while chunk := body.read(1024 * 1024):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise ValueError(f"La version {version} ya existe en {remote} con otro contenido")
        return True

    if verify_existing():
        return
    try:
        with archive_path.open("rb") as body:
            client.put_object(
                Bucket=bucket,
                Key=key,
                Body=body,
                IfNoneMatch="*",
                ChecksumSHA256=base64.b64encode(bytes.fromhex(expected)).decode("ascii"),
                Metadata={"sha256": expected},
            )
    except ClientError as error:
        if error.response["Error"]["Code"] not in {"412", "PreconditionFailed"}:
            raise
    if not verify_existing():
        raise ValueError(f"No se pudo verificar la copia de {version} en {remote}")


def publication(remote: str, bucket: str, version: str) -> RemotePublication:
    """El registro de que esta version quedo publicada en `remote`."""
    return RemotePublication(
        remote=remote,
        storage_uri=storage_uri(bucket, version),
        published_at=datetime.now(UTC),
    )


@dataclass
class ReleaseResult:
    entry: DatasetVersion
    manifest: VersionsManifest
    archive_path: Path


def run(
    *,
    coco_path: Path,
    quality_report_path: Path,
    splits_path: Path,
    dataset_fingerprint: str,
    bucket: str,
    bump: Bump = "patch",
    version: str | None = None,
    notes: str | None = None,
    remote: str = DEFAULT_REMOTE,
    out: Path = DEFAULT_VERSIONS_PATH,
    archive_dir: Path = Path("reports") / "releases",
    upload: bool = True,
    profile: str | None = None,
) -> ReleaseResult:
    """Empaqueta, sube y registra una version. `upload=False` es `--dry-run`."""
    quality_report = QualityReport.model_validate_json(
        quality_report_path.read_text(encoding="utf-8")
    )
    # Solo se valida la forma antes de empaquetar: un splits.json corrupto no
    # debe terminar dentro de un release inmutable.
    splits = SplitsManifest.model_validate_json(splits_path.read_text(encoding="utf-8"))
    dataset = load_coco(coco_path)
    actual = fingerprint_dataset(dataset)
    if actual != dataset_fingerprint or actual != quality_report.dataset_fingerprint:
        raise ValueError("El reporte de calidad o la huella no corresponden al dataset actual")
    if quality_report.totals.model_dump() != {
        "images": len(dataset.images),
        "annotations": len(dataset.annotations),
        "categories": len(dataset.categories),
    }:
        raise ValueError("Los conteos de calidad no corresponden al dataset actual")
    if {a.image_id for a in splits.assignments} != {i.id for i in dataset.images}:
        raise ValueError("Los splits no corresponden a las imagenes del dataset actual")

    manifest = load_manifest(out)
    resolved_version = version or next_version(manifest, bump)
    if any(entry.version == resolved_version for entry in manifest.versions):
        raise ValueError(f"Version duplicada: {resolved_version}")

    archive_path = build_archive(
        coco_path=coco_path,
        quality_path=quality_report_path,
        splits_path=splits_path,
        dest=archive_dir / resolved_version / ARCHIVE_NAME,
    )

    entry = build_entry(
        version=resolved_version,
        dataset_fingerprint=dataset_fingerprint,
        quality_report=quality_report,
        quality_report_fingerprint=file_sha256(quality_report_path),
        splits_fingerprint=file_sha256(splits_path),
        bucket=bucket,
        notes=notes,
        quality_summary=summarize_quality(dataset, quality_report),
        archive_sha256=file_sha256(archive_path),
    )

    if upload:
        if remote == DEFAULT_REMOTE and profile is None:
            upload_archive(archive_path, bucket, resolved_version)
        else:
            upload_archive(archive_path, bucket, resolved_version, remote=remote, profile=profile)
        # El remote se registra DESPUES del upload: si la subida falla, la
        # excepcion sube y no queda escrito que la version esta publicada.
        entry = entry.model_copy(
            update={"published_in": [publication(remote, bucket, resolved_version)]}
        )
        new_manifest = append_entry(manifest, entry)
        write_manifest(new_manifest, out)
    else:
        new_manifest = append_entry(manifest, entry)

    return ReleaseResult(entry=entry, manifest=new_manifest, archive_path=archive_path)
