"""Publicacion de versiones de modelo y registro (F7 T18, criterios 5.2, 5.3 y 6.4).

Contra un almacen falso en memoria con versionado (como un bucket S3 con
versioning): cada `put` crea un `VersionId` nuevo. Nada toca S3 real.
"""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
from pathlib import Path
from typing import Any

import pytest
import torch
from PIL import Image

from p3.inference.registry import ModelRegistry
from p3.inference.service import InferenceService
from p3.model.build import build_model, save_checkpoint
from p3.registry.publish import (
    PublishError,
    activate_version,
    list_versions,
    publish_version,
)

BUCKET = "bucket-prueba"
PREFIX = "models/clasificador"
CLASSES = ("cat", "dog", "person")


class FakeStore:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], list[tuple[str, bytes]]] = {}
        self.missing_on_head: set[str] = set()
        self.corrupt_on_get: set[str] = set()

    def put_bytes(self, bucket: str, key: str, data: bytes) -> str:
        history = self.objects.setdefault((bucket, key), [])
        version_id = f"v{len(history) + 1}-{hashlib.md5(data).hexdigest()[:6]}"
        history.append((version_id, data))
        return version_id

    def head(self, bucket: str, key: str) -> dict[str, Any] | None:
        history = self.objects.get((bucket, key))
        if not history or key in self.missing_on_head:
            return None
        version_id, data = history[-1]
        return {"version_id": version_id, "size": len(data)}

    def get_bytes(self, bucket: str, key: str, version_id: str | None = None) -> bytes:
        history = self.objects.get((bucket, key))
        if not history:
            raise FileNotFoundError(key)
        data = history[-1][1]
        if version_id is not None:
            data = next(d for v, d in history if v == version_id)
        return data + b"x" if key in self.corrupt_on_get else data

    def delete(self, bucket: str, key: str) -> None:
        self.objects.pop((bucket, key), None)


def checkpoint_bytes(seed: int) -> bytes:
    torch.manual_seed(seed)
    model = build_model(num_classes=3, hidden_layers=[], dropout=0.0, pretrained=False)
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "model.pt"
        save_checkpoint(
            path,
            model,
            class_names=CLASSES,
            hidden_layers=[],
            dropout=0.0,
            preprocessing={
                "image_size": 32,
                "resize": "resize_to_square",
                "mean": [0.485, 0.456, 0.406],
                "std": [0.229, 0.224, 0.225],
            },
        )
        return path.read_bytes()


def package(version: str, checkpoint: bytes, run_id: str = "r10") -> dict[str, bytes]:
    model_version = {
        "schema_version": 1,
        "version": version,
        "run_id": run_id,
        "manifest_id": "m-0.1.3-s42-1",
        "release_id": "0.1.3",
        "files": {"model.pt": {"sha256": hashlib.sha256(checkpoint).hexdigest()}},
    }
    return {
        "model.pt": checkpoint,
        "MODEL_CARD.md": f"# Tarjeta {version}\n".encode(),
        "model_version.json": json.dumps(model_version).encode(),
    }


def registry(store: FakeStore) -> ModelRegistry:
    return ModelRegistry.model_validate_json(store.get_bytes(BUCKET, f"{PREFIX}/registry.json"))


def publish(store: FakeStore, version: str, checkpoint: bytes, **kwargs: Any) -> ModelRegistry:
    return publish_version(
        store,
        bucket=BUCKET,
        prefix=PREFIX,
        version=version,
        files=package(version, checkpoint),
        **kwargs,
    )


@pytest.fixture(scope="module")
def checkpoints() -> tuple[bytes, bytes]:
    return checkpoint_bytes(0), checkpoint_bytes(1)


# --- Publicar -------------------------------------------------------------------------------


def test_publicar_sube_el_paquete_y_registra_la_version(checkpoints) -> None:
    store = FakeStore()
    result = publish(store, "1.0.0", checkpoints[0], activate=True)
    [entry] = result.versions
    assert entry.version == "1.0.0"
    assert entry.key == f"{PREFIX}/1.0.0/model.pt"
    assert entry.sha256 == hashlib.sha256(checkpoints[0]).hexdigest()
    assert entry.s3_version_id == store.head(BUCKET, entry.key)["version_id"]
    assert entry.run_id == "r10" and entry.manifest_id == "m-0.1.3-s42-1"
    assert result.active_version == "1.0.0"
    assert registry(store) == result
    for name in ("model.pt", "MODEL_CARD.md", "model_version.json"):
        assert store.head(BUCKET, f"{PREFIX}/1.0.0/{name}") is not None


def test_el_registro_guarda_version_id_y_sha_de_cada_archivo(checkpoints) -> None:
    store = FakeStore()
    [entry] = publish(store, "1.0.0", checkpoints[0]).versions
    files = entry.model_dump()["files"]
    card_key = f"{PREFIX}/1.0.0/MODEL_CARD.md"
    assert files["MODEL_CARD.md"]["s3_version_id"] == store.head(BUCKET, card_key)["version_id"]
    assert files["MODEL_CARD.md"]["sha256"] == hashlib.sha256(b"# Tarjeta 1.0.0\n").hexdigest()


def test_sin_activar_la_version_publicada_no_cambia_la_activa(checkpoints) -> None:
    store = FakeStore()
    publish(store, "1.0.0", checkpoints[0], activate=True)
    result = publish(store, "1.0.1", checkpoints[1], activate=False)
    assert [e.version for e in result.versions] == ["1.0.0", "1.0.1"]
    assert result.active_version == "1.0.0"


def test_no_se_marca_publicado_un_objeto_que_no_existe(checkpoints) -> None:
    store = FakeStore()
    store.missing_on_head.add(f"{PREFIX}/1.0.0/model.pt")
    with pytest.raises(PublishError, match="no existe"):
        publish(store, "1.0.0", checkpoints[0], activate=True)
    assert (BUCKET, f"{PREFIX}/registry.json") not in store.objects


def test_sha_distinto_al_descargar_no_se_registra(checkpoints) -> None:
    store = FakeStore()
    store.corrupt_on_get.add(f"{PREFIX}/1.0.0/model.pt")
    with pytest.raises(PublishError, match="SHA-256"):
        publish(store, "1.0.0", checkpoints[0], activate=True)
    assert (BUCKET, f"{PREFIX}/registry.json") not in store.objects


def test_el_sha_del_paquete_debe_ser_el_de_model_version_json(checkpoints) -> None:
    files = package("1.0.0", checkpoints[0])
    files["model.pt"] = checkpoints[1]
    with pytest.raises(PublishError, match=r"model_version\.json"):
        publish_version(FakeStore(), bucket=BUCKET, prefix=PREFIX, version="1.0.0", files=files)


def test_una_version_publicada_es_inmutable(checkpoints) -> None:
    store = FakeStore()
    publish(store, "1.0.0", checkpoints[0])
    with pytest.raises(PublishError, match=r"1\.0\.0"):
        publish(store, "1.0.0", checkpoints[1])
    assert registry(store).versions[0].sha256 == hashlib.sha256(checkpoints[0]).hexdigest()


def test_la_version_del_paquete_debe_coincidir(checkpoints) -> None:
    with pytest.raises(PublishError, match="version"):
        publish_version(
            FakeStore(),
            bucket=BUCKET,
            prefix=PREFIX,
            version="2.0.0",
            files=package("1.0.0", checkpoints[0]),
        )


# --- Activar --------------------------------------------------------------------------------


def test_activar_una_version_publicada(checkpoints) -> None:
    store = FakeStore()
    publish(store, "1.0.0", checkpoints[0], activate=True)
    publish(store, "1.0.1", checkpoints[1])
    result = activate_version(store, bucket=BUCKET, prefix=PREFIX, version="1.0.1")
    assert result.active_version == "1.0.1" == registry(store).active_version


def test_no_se_activa_una_version_desconocida(checkpoints) -> None:
    store = FakeStore()
    publish(store, "1.0.0", checkpoints[0], activate=True)
    with pytest.raises(PublishError, match=r"9\.9\.9"):
        activate_version(store, bucket=BUCKET, prefix=PREFIX, version="9.9.9")


def test_no_se_activa_si_el_objeto_ya_no_existe(checkpoints) -> None:
    store = FakeStore()
    publish(store, "1.0.0", checkpoints[0], activate=True)
    publish(store, "1.0.1", checkpoints[1])
    store.delete(BUCKET, f"{PREFIX}/1.0.1/model.pt")
    with pytest.raises(PublishError, match="no existe"):
        activate_version(store, bucket=BUCKET, prefix=PREFIX, version="1.0.1")
    assert registry(store).active_version == "1.0.0"


def test_no_se_activa_si_el_sha_no_coincide(checkpoints) -> None:
    store = FakeStore()
    publish(store, "1.0.0", checkpoints[0], activate=True)
    publish(store, "1.0.1", checkpoints[1])
    store.corrupt_on_get.add(f"{PREFIX}/1.0.1/model.pt")
    with pytest.raises(PublishError, match="SHA-256"):
        activate_version(store, bucket=BUCKET, prefix=PREFIX, version="1.0.1")
    assert registry(store).active_version == "1.0.0"


# --- Listar para la pagina Models -----------------------------------------------------------


def test_listar_versiones_con_su_estado_real_en_el_almacen(checkpoints) -> None:
    store = FakeStore()
    publish(store, "1.0.0", checkpoints[0], activate=True)
    publish(store, "1.0.1", checkpoints[1])
    store.delete(BUCKET, f"{PREFIX}/1.0.1/model.pt")
    listing = list_versions(store, bucket=BUCKET, prefix=PREFIX)
    assert listing["active_version"] == "1.0.0"
    estado = {m["version"]: m["s3"]["exists"] for m in listing["models"]}
    assert estado == {"1.0.0": True, "1.0.1": False}
    first = listing["models"][0]
    assert first["s3"]["uri"] == f"s3://{BUCKET}/{PREFIX}/1.0.0/model.pt"
    assert first["card_uri"] == f"s3://{BUCKET}/{PREFIX}/1.0.0/MODEL_CARD.md"


def test_listar_sin_registro_devuelve_vacio() -> None:
    assert list_versions(FakeStore(), bucket=BUCKET, prefix=PREFIX) == {
        "active_version": None,
        "models": [],
    }


# --- Integracion con el servicio de inferencia (5.3) ----------------------------------------


def test_activar_otra_version_cambia_el_modelo_que_usa_la_inferencia(checkpoints) -> None:
    store = FakeStore()
    publish(store, "1.0.0", checkpoints[0], activate=True)
    publish(store, "1.0.1", checkpoints[1])
    service = InferenceService(store, bucket=BUCKET, prefix=PREFIX)
    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 30, 90)).save(buffer, format="PNG")
    image = buffer.getvalue()

    antes = service.predict(image, "image/png")
    activate_version(store, bucket=BUCKET, prefix=PREFIX, version="1.0.1")
    despues = service.predict(image, "image/png")

    assert antes.model_version == "1.0.0" and despues.model_version == "1.0.1"
    assert antes.model_sha256 == hashlib.sha256(checkpoints[0]).hexdigest()
    assert despues.model_sha256 == hashlib.sha256(checkpoints[1]).hexdigest()
    assert antes.probabilities != despues.probabilities
