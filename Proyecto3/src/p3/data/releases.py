"""Releases aprobados de P2 como entrada de P3 (F2 T05, criterios 1.1 y M2).

El registro es `Proyecto2/reports/versions.json`, el mismo que escribe
`dq release` (`dataset_quality.tiers.release`). De ahi sale todo lo que P3
guarda para la trazabilidad: version, `dataset_fingerprint`, estado de la
compuerta, `quality_report_fingerprint` y `archive_sha256`.

Un release solo se usa si:

1. su compuerta es `pass` (si no, `ReleaseNotApprovedError` -> HTTP 409), y
2. su `dataset.tar.zst` tiene exactamente el `archive_sha256` registrado, el
   COCO de adentro produce el `dataset_fingerprint` registrado y el
   `quality.json` de adentro tambien dice `pass`.

La huella se recibe como funcion para no reimplementar la de P2: dentro del
portal se pasa `p2_dataset_fingerprint`, que usa `dataset_quality`
directamente. Logica pura: aqui no se lee el entorno ni se crean clientes S3;
los bytes del archivo los trae quien llama.
"""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import zstandard
from pydantic import BaseModel, ConfigDict, Field, field_validator

ARCHIVE_NAME = "dataset.tar.zst"
COCO_MEMBER = "annotations.coco.json"
QUALITY_MEMBER = "quality.json"

Fingerprint = Callable[[bytes], str]


class ReleaseNotFoundError(LookupError):
    """El release pedido no esta en el registro de P2 (HTTP 404)."""


class ReleaseNotApprovedError(ValueError):
    """El release existe pero su compuerta de calidad no paso (HTTP 409)."""


class ReleaseIntegrityError(ValueError):
    """El archivo del release no es el que se registro al publicarlo."""


class ReleaseCounts(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    images: int
    annotations: int
    categories: int


class Release(BaseModel):
    """Vista de P3 sobre una entrada de `versions.json` (ignora campos que no usa)."""

    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)

    release_id: str = Field(validation_alias="version")
    created_at: datetime
    dataset_fingerprint: str
    quality_status: Literal["pass", "fail"]
    quality_report_fingerprint: str
    archive_sha256: str | None = None
    counts: ReleaseCounts
    published_in: tuple[str, ...] = ()

    @field_validator("published_in", mode="before")
    @classmethod
    def _solo_nombres_de_remote(cls, value: Any) -> Any:
        # En P2 cada publicacion es {remote, storage_uri, published_at}. La URI
        # de P2 puede apuntar a un bucket que ya no es el del equipo (ver
        # decisiones.md §1), asi que P3 solo conserva el nombre del remote y
        # arma la URI con el bucket configurado.
        if isinstance(value, list):
            return tuple(item["remote"] if isinstance(item, dict) else item for item in value)
        return value


@dataclass(frozen=True)
class ReleaseContent:
    """COCO y reporte de calidad de un release, ya verificados."""

    release: Release
    coco: dict[str, Any]
    quality: dict[str, Any]


def load_releases(versions_path: Path) -> list[Release]:
    """Todas las entradas del registro de P2, en el orden en que se publicaron."""
    data = json.loads(versions_path.read_text(encoding="utf-8"))
    return [Release.model_validate(item) for item in data["versions"]]


def approved_releases(releases: Iterable[Release]) -> list[Release]:
    return [release for release in releases if release.quality_status == "pass"]


def get_approved_release(releases: Iterable[Release], release_id: str) -> Release:
    for release in releases:
        if release.release_id == release_id:
            if release.quality_status != "pass":
                raise ReleaseNotApprovedError(
                    f"El release {release_id} no paso la compuerta de calidad "
                    f"(quality_status={release.quality_status}); no se puede usar para entrenar."
                )
            return release
    raise ReleaseNotFoundError(f"No existe el release {release_id} en el registro de P2.")


def archive_key(release_id: str) -> str:
    """Llave del archivo en el bucket de releases, igual que `dq release`."""
    return f"{release_id}/{ARCHIVE_NAME}"


def archive_uri(bucket: str, release_id: str) -> str:
    return f"s3://{bucket}/{archive_key(release_id)}"


def open_release_archive(
    release: Release, archive: bytes, *, fingerprint: Fingerprint
) -> ReleaseContent:
    """Extrae COCO y reporte de calidad solo si el archivo es el del release."""
    if release.archive_sha256 is None:
        raise ReleaseIntegrityError(
            f"El release {release.release_id} no registra archive_sha256: "
            "no hay forma de comprobar que el archivo sea el publicado."
        )
    actual = hashlib.sha256(archive).hexdigest()
    if actual != release.archive_sha256:
        raise ReleaseIntegrityError(
            f"SHA-256 del archivo del release {release.release_id} = {actual}; "
            f"el registro dice {release.archive_sha256}."
        )

    members = _read_members(archive, {COCO_MEMBER, QUALITY_MEMBER})
    coco_bytes = members[COCO_MEMBER]
    huella = fingerprint(coco_bytes)
    if huella != release.dataset_fingerprint:
        raise ReleaseIntegrityError(
            f"La huella del COCO del release {release.release_id} es {huella}; "
            f"el registro dice {release.dataset_fingerprint}."
        )
    quality = json.loads(members[QUALITY_MEMBER])
    if quality.get("status") != "pass":
        raise ReleaseIntegrityError(
            f"El quality.json del archivo del release {release.release_id} dice "
            f"status={quality.get('status')!r}; se exige 'pass', igual que en el registro."
        )
    return ReleaseContent(release=release, coco=json.loads(coco_bytes), quality=quality)


def coco_counts(coco: dict[str, Any]) -> dict[str, Any]:
    """Conteos crudos del COCO de un release (antes de validar cajas)."""
    names = {category["id"]: category["name"] for category in coco["categories"]}
    per_category = Counter(names[a["category_id"]] for a in coco["annotations"])
    return {
        "images": len(coco["images"]),
        "annotations": len(coco["annotations"]),
        "annotations_per_category": dict(sorted(per_category.items())),
    }


def p2_dataset_fingerprint(coco_bytes: bytes) -> str:
    """La huella de P2 (`dataset_quality.tiers.gate.dataset_fingerprint`).

    Solo funciona donde esta instalado `dataset_quality` (la app de P2, que es
    donde corre el router de P3). Se importa aqui para no volverlo dependencia
    de la logica pura ni de las pruebas de P3.
    """
    from dataset_quality.models.coco import parse_coco
    from dataset_quality.tiers.gate import dataset_fingerprint

    return dataset_fingerprint(parse_coco(coco_bytes, source=COCO_MEMBER))


def _read_members(archive: bytes, names: set[str]) -> dict[str, bytes]:
    found: dict[str, bytes] = {}
    with (
        zstandard.ZstdDecompressor().stream_reader(io.BytesIO(archive)) as stream,
        tarfile.open(fileobj=stream, mode="r|") as tar,
    ):
        for member in tar:
            if member.name in names and member.isfile():
                handle = tar.extractfile(member)
                assert handle is not None
                found[member.name] = handle.read()
    missing = names - found.keys()
    if missing:
        raise ReleaseIntegrityError(f"Al archivo del release le faltan {sorted(missing)}.")
    return found
