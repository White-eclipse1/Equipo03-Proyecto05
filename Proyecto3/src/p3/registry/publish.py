"""Publicacion de versiones de modelo y registro (F7 T18, criterios 5.2, 5.3 y 6.4).

Escribe lo que lee el servicio de inferencia de F4 (`p3.inference.registry`):
`<prefix>/<version>/...` con el paquete y `<prefix>/registry.json` con las
versiones y la activa (contratos §6).

Reglas:

- Una version se registra SOLO si cada archivo existe tras subirlo (`head`, con
  el tamano esperado) y si el `model.pt` descargado de vuelta tiene el SHA-256
  local, que ademas debe ser el de `model_version.json` del paquete. Si algo
  falla, `registry.json` no se toca: nunca se marca publicado un objeto que no
  existe (6.4).
- Las versiones publicadas son inmutables.
- Activar una version exige que su objeto exista y que su SHA-256 coincida.

El almacen se inyecta (`ObjectStore`): S3 real con `boto3`, MinIO o un falso en
las pruebas. Aqui no se leen credenciales ni el entorno.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Protocol

from p3.inference.registry import REGISTRY_NAME, ModelEntry, ModelRegistry

MODEL = "model.pt"
CARD = "MODEL_CARD.md"
MODEL_VERSION = "model_version.json"


class PublishError(RuntimeError):
    """La version no se pudo publicar o activar sin romper el registro."""


class ObjectStore(Protocol):
    def put_bytes(self, bucket: str, key: str, data: bytes) -> str | None: ...

    def head(self, bucket: str, key: str) -> dict[str, Any] | None: ...

    def get_bytes(self, bucket: str, key: str, version_id: str | None = None) -> bytes: ...


def read_registry(store: ObjectStore, *, bucket: str, prefix: str) -> ModelRegistry:
    """El registro actual, o uno vacio si todavia no hay ninguno."""
    key = f"{prefix}/{REGISTRY_NAME}"
    if store.head(bucket, key) is None:
        return ModelRegistry(schema_version=1, active_version=None, versions=[])
    return ModelRegistry.model_validate_json(store.get_bytes(bucket, key))


def publish_version(
    store: ObjectStore,
    *,
    bucket: str,
    prefix: str,
    version: str,
    files: Mapping[str, bytes],
    activate: bool = False,
) -> ModelRegistry:
    prefix = prefix.rstrip("/")
    meta = json.loads(files[MODEL_VERSION])
    if meta["version"] != version:
        raise PublishError(f"El paquete es de la version {meta['version']}, no de {version}.")
    local_sha = hashlib.sha256(files[MODEL]).hexdigest()
    if local_sha != meta["files"][MODEL]["sha256"]:
        raise PublishError(
            f"SHA-256 de {MODEL} ({local_sha}) no es el de model_version.json "
            f"({meta['files'][MODEL]['sha256']})."
        )
    current = read_registry(store, bucket=bucket, prefix=prefix)
    if any(entry.version == version for entry in current.versions):
        raise PublishError(f"La version {version} ya esta publicada; las versiones son inmutables.")

    uploaded: dict[str, dict[str, Any]] = {}
    for name in sorted(files, key=lambda n: (n == MODEL_VERSION, n)):
        data = files[name]
        key = f"{prefix}/{version}/{name}"
        store.put_bytes(bucket, key, data)
        found = store.head(bucket, key)
        if found is None or found.get("size") not in (None, len(data)):
            raise PublishError(f"s3://{bucket}/{key} no existe (o esta incompleto) tras subirlo.")
        uploaded[name] = {
            "sha256": hashlib.sha256(data).hexdigest(),
            "s3_version_id": found.get("version_id"),
        }

    model_key = f"{prefix}/{version}/{MODEL}"
    downloaded = store.get_bytes(bucket, model_key, uploaded[MODEL]["s3_version_id"])
    if hashlib.sha256(downloaded).hexdigest() != local_sha:
        raise PublishError(f"SHA-256 de s3://{bucket}/{model_key} descargado no es el local.")

    entry = ModelEntry(
        version=version,
        run_id=meta["run_id"],
        manifest_id=meta["manifest_id"],
        key=model_key,
        sha256=local_sha,
        s3_version_id=uploaded[MODEL]["s3_version_id"],
        release_id=meta.get("release_id"),
        card_key=f"{prefix}/{version}/{CARD}" if CARD in files else None,
        files=uploaded,
    )
    updated = ModelRegistry(
        schema_version=1,
        active_version=version if activate else current.active_version,
        versions=[*current.versions, entry],
    )
    return _write_registry(store, bucket=bucket, prefix=prefix, registry=updated)


def activate_version(
    store: ObjectStore, *, bucket: str, prefix: str, version: str
) -> ModelRegistry:
    prefix = prefix.rstrip("/")
    current = read_registry(store, bucket=bucket, prefix=prefix)
    entry = next((e for e in current.versions if e.version == version), None)
    if entry is None:
        raise PublishError(f"La version {version} no esta en el registro.")
    if store.head(bucket, entry.key) is None:
        raise PublishError(f"s3://{bucket}/{entry.key} no existe: no se activa {version}.")
    data = store.get_bytes(bucket, entry.key, entry.s3_version_id)
    if hashlib.sha256(data).hexdigest() != entry.sha256:
        raise PublishError(f"SHA-256 de {entry.key} no es el registrado: no se activa {version}.")
    updated = current.model_copy(update={"active_version": version})
    return _write_registry(store, bucket=bucket, prefix=prefix, registry=updated)


def list_versions(store: ObjectStore, *, bucket: str, prefix: str) -> dict[str, Any]:
    """Versiones del registro con su estado real en el almacen (pagina Models)."""
    prefix = prefix.rstrip("/")
    current = read_registry(store, bucket=bucket, prefix=prefix)
    models = []
    for entry in current.versions:
        extra = entry.model_dump()
        card_key = extra.get("card_key") or f"{prefix}/{entry.version}/{CARD}"
        models.append(
            {
                "version": entry.version,
                "run_id": entry.run_id,
                "manifest_id": entry.manifest_id,
                "release_id": extra.get("release_id"),
                "active": entry.version == current.active_version,
                "s3": {
                    "uri": f"s3://{bucket}/{entry.key}",
                    "version_id": entry.s3_version_id,
                    "sha256": entry.sha256,
                    "exists": store.head(bucket, entry.key) is not None,
                },
                "card_uri": f"s3://{bucket}/{card_key}",
            }
        )
    return {"active_version": current.active_version, "models": models}


def _write_registry(
    store: ObjectStore, *, bucket: str, prefix: str, registry: ModelRegistry
) -> ModelRegistry:
    key = f"{prefix}/{REGISTRY_NAME}"
    data = (json.dumps(registry.model_dump(mode="json"), indent=2) + "\n").encode("utf-8")
    store.put_bytes(bucket, key, data)
    written = ModelRegistry.model_validate_json(store.get_bytes(bucket, key))
    if written != registry:
        raise PublishError(f"s3://{bucket}/{key} no quedo como se escribio.")
    return written
