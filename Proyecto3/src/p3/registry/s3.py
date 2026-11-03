"""`ObjectStore` de lectura y escritura sobre boto3 para publicar y activar modelos (F7).

La politica de los integrantes no incluye `s3:GetObjectVersion` (solo la del
evaluador): en vez de pedir una version concreta se descarga la actual y se
exige que su `VersionId` sea el registrado. Cada version del modelo vive en su
propia carpeta y nunca se sobrescribe, asi que la actual es la registrada; si
alguien la sobrescribiera, la descarga falla en vez de servir otro archivo.
"""

from __future__ import annotations

from typing import Any


class VersionMismatchError(RuntimeError):
    """El objeto actual no es la version registrada."""


class S3Store:
    def __init__(self, client: Any) -> None:
        self.client = client

    @classmethod
    def from_profile(cls, profile: str | None, region: str = "us-east-1") -> S3Store:
        import boto3

        return cls(boto3.Session(profile_name=profile or None).client("s3", region_name=region))

    def put_bytes(self, bucket: str, key: str, data: bytes) -> str | None:
        return self.client.put_object(Bucket=bucket, Key=key, Body=data).get("VersionId")

    def head(self, bucket: str, key: str) -> dict[str, Any] | None:
        from botocore.exceptions import ClientError

        try:
            found = self.client.head_object(Bucket=bucket, Key=key)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise
        return {"version_id": found.get("VersionId"), "size": found["ContentLength"]}

    def get_bytes(self, bucket: str, key: str, version_id: str | None = None) -> bytes:
        response = self.client.get_object(Bucket=bucket, Key=key)
        if version_id is not None and response.get("VersionId") != version_id:
            raise VersionMismatchError(
                f"s3://{bucket}/{key} tiene VersionId {response.get('VersionId')}, "
                f"no el registrado {version_id}."
            )
        return response["Body"].read()
