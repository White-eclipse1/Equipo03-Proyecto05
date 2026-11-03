"""API de versiones de modelo para la pagina Models (F7, contratos §4; criterios 5.3 y 6.4).

Corre en el servicio `p3-inference`, que tiene el perfil de AWS; el portal de P2
la reenvia (`p3.registry.proxy`).

- `GET /api/p3/models`: versiones del `registry.json` con su estado REAL en S3
  (`exists` sale de `head-object`, no del registro).
- `GET /api/p3/models/{version}/card`: la `MODEL_CARD.md` de esa version.
- `GET /api/p3/models/{version}/download`: el `model.pt` publicado, solo si es el
  registrado (`VersionId` y SHA-256), con `Content-Disposition` y `X-Model-SHA256`
  (contrato C2, F13).
- `POST /api/p3/models/{version}/activate`: cambia la version activa solo si su
  `model.pt` existe y su SHA-256 coincide (`p3.registry.publish`). El servicio
  de inferencia lee el registro en cada prediccion, asi que el cambio aplica sin
  reiniciar.

Si S3 no esta disponible (sin credenciales, perfil inexistente, sin red o acceso
denegado) responde 503 con el motivo y que configurar, nunca 500.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Response

from p3.registry.publish import (
    ObjectStore,
    PublishError,
    activate_version,
    list_versions,
    read_registry,
)
from p3.registry.s3 import VersionMismatchError

router = APIRouter(prefix="/api/p3/models", tags=["p3-models"])
Version = Annotated[str, Path(pattern=r"^\d+\.\d+\.\d+$")]


SETUP = (
    "Configura P3_AWS_PROFILE (un perfil de ~/.aws montado con P3_AWS_DIR) o P3_S3_ENDPOINT "
    "con sus llaves para el MinIO local (docs/publicacion_s3.md)."
)


@contextmanager
def s3_available() -> Iterator[None]:
    """Convierte los fallos de S3 de boto3 en un 503 que dice que configurar."""
    from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

    try:
        yield
    except NoCredentialsError as error:
        raise HTTPException(503, f"S3 sin credenciales de AWS. {SETUP}") from error
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code", "?")
        raise HTTPException(503, f"S3 rechazo la peticion ({code}). {SETUP}") from error
    except BotoCoreError as error:
        raise HTTPException(503, f"S3 no disponible: {error}. {SETUP}") from error


@dataclass(frozen=True)
class ModelsStore:
    store: ObjectStore
    bucket: str
    prefix: str


def get_models_store() -> ModelsStore:
    from p3.inference.settings import get_settings

    with s3_available():
        return _build_store(get_settings())


def _build_store(settings: Any) -> ModelsStore:
    from p3.registry.s3 import S3Store

    if settings.s3_endpoint:
        import boto3

        secret = settings.s3_secret_key.get_secret_value() if settings.s3_secret_key else None
        client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=secret,
            region_name=settings.aws_region,
        )
        store = S3Store(client)
    else:
        store = S3Store.from_profile(settings.aws_profile, settings.aws_region)
    return ModelsStore(store=store, bucket=settings.models_bucket, prefix=settings.models_prefix)


StoreDep = Annotated[ModelsStore, Depends(get_models_store)]


@router.get("")
def read_models(models: StoreDep) -> dict[str, Any]:
    with s3_available():
        return list_versions(models.store, bucket=models.bucket, prefix=models.prefix)


@router.get("/{version}/card")
def read_card(version: Version, models: StoreDep) -> Response:
    with s3_available():
        return _card(version, models)


def _card(version: str, models: ModelsStore) -> Response:
    registry = read_registry(models.store, bucket=models.bucket, prefix=models.prefix)
    entry = next((e for e in registry.versions if e.version == version), None)
    if entry is None:
        raise HTTPException(404, f"La version de modelo {version} no esta publicada.")
    card_key = entry.model_dump().get("card_key") or f"{models.prefix}/{version}/MODEL_CARD.md"
    data = models.store.get_bytes(models.bucket, card_key)
    return Response(data, media_type="text/markdown; charset=utf-8")


@router.get("/{version}/download")
def download(version: Version, models: StoreDep) -> Response:
    with s3_available():
        return _download(version, models)


def _download(version: str, models: ModelsStore) -> Response:
    """Los bytes de `model.pt` solo si son los registrados (contrato C2)."""
    registry = read_registry(models.store, bucket=models.bucket, prefix=models.prefix)
    entry = next((e for e in registry.versions if e.version == version), None)
    if entry is None:
        raise HTTPException(404, f"La version de modelo {version} no esta publicada.")
    uri = f"s3://{models.bucket}/{entry.key}"
    if models.store.head(models.bucket, entry.key) is None:
        raise HTTPException(409, f"El objeto {uri} no existe en S3.")
    try:
        data = models.store.get_bytes(models.bucket, entry.key, entry.s3_version_id)
    except VersionMismatchError as error:
        raise HTTPException(409, str(error)) from error
    actual = hashlib.sha256(data).hexdigest()
    if actual != entry.sha256:
        raise HTTPException(
            409, f"SHA-256 de {uri} = {actual}; el registro de {version} dice {entry.sha256}."
        )
    return Response(
        data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="clasificador-{version}-model.pt"',
            "X-Model-SHA256": entry.sha256,
        },
    )


@router.post("/{version}/activate")
def activate(version: Version, models: StoreDep) -> dict[str, Any]:
    with s3_available():
        return _activate(version, models)


def _activate(version: str, models: ModelsStore) -> dict[str, Any]:
    registry = read_registry(models.store, bucket=models.bucket, prefix=models.prefix)
    if all(entry.version != version for entry in registry.versions):
        raise HTTPException(404, f"La version de modelo {version} no esta publicada.")
    try:
        activate_version(models.store, bucket=models.bucket, prefix=models.prefix, version=version)
    except PublishError as error:
        raise HTTPException(409, str(error)) from error
    return list_versions(models.store, bucket=models.bucket, prefix=models.prefix)
