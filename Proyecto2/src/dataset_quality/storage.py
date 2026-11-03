"""Acceso al almacenamiento de objetos (MinIO en local, S3 en AWS)."""

from __future__ import annotations

import hashlib
import mimetypes
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from dataset_quality.settings import Settings, get_settings

if TYPE_CHECKING:  # pragma: no cover - solo para tipado
    from mypy_boto3_s3.client import S3Client
else:
    S3Client = object


@lru_cache
def get_s3_client() -> S3Client:
    """Cliente S3 apuntando a MinIO (o al S3 real segun `.env`)."""
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.minio_endpoint_url,
        aws_access_key_id=settings.minio_root_user,
        aws_secret_access_key=settings.minio_root_password.get_secret_value(),
        config=Config(signature_version="s3v4", retries={"max_attempts": 2}),
        region_name="us-east-1",
    )


def get_prod_s3_client(profile: str | None = None) -> S3Client:
    """S3 real, con credenciales AWS independientes del MinIO local."""
    return boto3.Session(profile_name=profile).client(
        "s3",
        region_name=get_settings().prod_region,
        config=Config(signature_version="s3v4", retries={"max_attempts": 2}),
    )


def check_object_storage(settings: Settings | None = None) -> None:
    """Lanza una excepcion si falta algun bucket o MinIO no responde."""
    settings = settings or get_settings()
    client = get_s3_client()
    for bucket in settings.buckets:
        client.head_bucket(Bucket=bucket)


CHUNK = 1024 * 1024
RAW_PREFIX = "raw"


def image_key(file_name: str) -> str:
    """Llave del objeto para una imagen del dataset crudo."""
    return f"{RAW_PREFIX}/{file_name}"


def file_sha256(path: Path) -> str:
    """Huella del contenido, leyendo por trozos para no cargar el archivo entero."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def object_size(bucket: str, key: str) -> int | None:
    """Tamano del objeto, o `None` si no existe."""
    try:
        return int(get_s3_client().head_object(Bucket=bucket, Key=key)["ContentLength"])
    except ClientError as error:
        # 404 y 403 significan "no esta ahi para nosotros"; el resto es un fallo real.
        if error.response.get("Error", {}).get("Code") in {"404", "403", "NoSuchKey"}:
            return None
        raise


def upload_image(path: Path, bucket: str, key: str, *, skip_if_same_size: bool = True) -> bool:
    """Sube una imagen. Devuelve True si subio, False si ya estaba.

    Saltarse las que ya estan hace que la ingesta se pueda repetir sin volver a
    empujar cientos de megabytes por la red.
    """
    if skip_if_same_size:
        existing = object_size(bucket, key)
        if existing is not None and existing == path.stat().st_size:
            return False

    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    get_s3_client().upload_file(str(path), bucket, key, ExtraArgs={"ContentType": content_type})
    return True


def ensure_bucket(bucket: str) -> None:
    """Crea el bucket si no existe. El job `minio-init` ya lo hace; esto cubre
    el caso de correr la ingesta contra un MinIO levantado a mano."""
    client = get_s3_client()
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") not in {"404", "NoSuchBucket"}:
            raise
        client.create_bucket(Bucket=bucket)
