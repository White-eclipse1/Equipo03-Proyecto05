"""`versions.json`: el contrato de salida congelado del registro de versiones.

Cada entrada representa una publicacion inmutable y content-addressed del
dataset (Frente 6, `dvc`) hacia el almacenamiento de objetos. Como en
`splits.py`, aqui solo se fija la forma exacta para desbloquear a los frentes
que la consumen (7 y 8).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from dataset_quality.models import StrictModel

_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


class DatasetCounts(StrictModel):
    """Conteos del dataset en esta version."""

    images: int = Field(ge=0)
    annotations: int = Field(ge=0)
    categories: int = Field(ge=0)


class VersionQualitySummary(StrictModel):
    """Metricas de esta version; nunca se toman de los reportes vigentes."""

    distinct_images_per_class: dict[str, Annotated[int, Field(ge=0)]]
    small_objects_ratio: float | None = Field(default=None, ge=0.0, le=1.0)


class RemotePublication(StrictModel):
    """Un remote donde esta publicada una version, y cuando se subio ahi.

    `storage_uri` se repite aqui a proposito en vez de derivarlo del bucket de
    la entrada: el mismo release puede vivir en buckets con nombres distintos
    segun el remote (`dev` es MinIO local, `prod` es S3 de verdad), y la unica
    forma honesta de decir donde esta cada copia es guardar su URI.
    """

    remote: str = Field(min_length=1)
    storage_uri: str = Field(min_length=1)
    published_at: datetime

    @field_validator("storage_uri")
    @classmethod
    def _storage_uri_es_s3(cls, value: str) -> str:
        if not value.startswith("s3://"):
            raise ValueError(f"debe empezar con 's3://' (recibido: {value!r})")
        return value


class DatasetVersion(StrictModel):
    """Una version publicada e inmutable del dataset."""

    schema_version: Literal[1] = 1
    version: str
    created_at: datetime
    dataset_fingerprint: str
    quality_report_fingerprint: str
    splits_fingerprint: str
    storage_uri: str = Field(min_length=1)
    quality_status: Literal["pass", "fail"]
    counts: DatasetCounts
    notes: str | None = None
    quality_summary: VersionQualitySummary | None = None
    archive_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    # En que remotes esta publicada esta version. Anadido opcional: un
    # `versions.json` escrito antes de que existiera sigue validando, por eso
    # `schema_version` sigue en 1.
    #
    # Sin esto, `storage_uri` decia a que URI se subio el archivo pero no a que
    # remote, y la pantalla no podia distinguir una version que solo existe en
    # el MinIO local de una promovida a S3 — que es justo la diferencia entre
    # "lo probe en mi maquina" y "esta publicado".
    published_in: list[RemotePublication] = Field(default_factory=list)

    @field_validator("version")
    @classmethod
    def _version_semver(cls, value: str) -> str:
        if not _SEMVER.match(value):
            raise ValueError(f"debe tener forma semver X.Y.Z (recibido: {value!r})")
        return value

    @field_validator("dataset_fingerprint", "quality_report_fingerprint", "splits_fingerprint")
    @classmethod
    def _fingerprint_sha256(cls, value: str) -> str:
        if not _SHA256_HEX.match(value):
            mensaje = "debe ser un sha256 hexadecimal de 64 caracteres"
            raise ValueError(f"{mensaje} (recibido: {value!r})")
        return value

    @field_validator("storage_uri")
    @classmethod
    def _storage_uri_es_s3(cls, value: str) -> str:
        if not value.startswith("s3://"):
            raise ValueError(f"debe empezar con 's3://' (recibido: {value!r})")
        return value

    @model_validator(mode="after")
    def _un_registro_por_remote(self) -> DatasetVersion:
        nombres = [publicacion.remote for publicacion in self.published_in]
        if len(nombres) != len(set(nombres)):
            repetidos = sorted({name for name in nombres if nombres.count(name) > 1})
            raise ValueError(
                f"la version esta registrada dos veces en el mismo remote: {repetidos}"
            )
        return self


class VersionsManifest(StrictModel):
    """Contrato congelado de `versions.json`: el registro completo de versiones."""

    schema_version: Literal[1] = 1
    versions: list[DatasetVersion]

    @model_validator(mode="after")
    def _versiones_unicas_y_en_orden(self) -> VersionsManifest:
        nombres = [entry.version for entry in self.versions]
        if len(nombres) != len(set(nombres)):
            duplicadas = sorted({name for name in nombres if nombres.count(name) > 1})
            raise ValueError(f"version duplicada en el registro: {duplicadas}")

        fechas = [entry.created_at for entry in self.versions]
        if fechas != sorted(fechas):
            raise ValueError("versions debe estar en orden cronologico por created_at")
        return self


# Remote al que publicaba `dq release` antes de que existiera `published_in`, y
# al que sigue publicando si no se le dice otro.
REMOTE_POR_DEFECTO = "dev"


def backfill_remotes(
    manifest: VersionsManifest, remote: str = REMOTE_POR_DEFECTO
) -> VersionsManifest:
    """Rellena `published_in` en las entradas anteriores a ese campo.

    No inventa un dato: hasta que el campo existio, `dq release` subia a un
    unico destino y `storage_uri` ya guardaba la URI exacta de esa copia; lo
    unico que faltaba era el nombre del remote. Dejarlas en blanco haria que la
    pantalla mostrara como "sin publicar" versiones que si lo estan.

    Es una migracion de LECTURA y esta aqui, en una funcion, y no en un
    validador del modelo: un validador tambien rellenaria las entradas que
    `dq release --dry-run` construye a proposito sin publicar nada, y entonces
    un ensayo en seco diria que publico.
    """
    return VersionsManifest(
        versions=[
            entry
            if entry.published_in
            else entry.model_copy(
                update={
                    "published_in": [
                        RemotePublication(
                            remote=remote,
                            storage_uri=entry.storage_uri,
                            published_at=entry.created_at,
                        )
                    ]
                }
            )
            for entry in manifest.versions
        ]
    )
