"""Inferencia con el paquete de la version activa descargado de S3 (F4 T24, 6.5 y M4).

Nunca usa un checkpoint local del entrenamiento: en cada prediccion lee el
registro (`registry.json`) del almacen de objetos, toma la version activa,
descarga su `model.pt`, comprueba que su SHA-256 sea el registrado y lo carga
con `load_checkpoint`. El paquete queda en memoria por `(version, sha256)`:
activar otra version cambia el modelo sin reiniciar el servicio.

El preprocesamiento es `build_eval_transform`, el mismo de validacion y
prueba. La imagen se abre como se ve en un navegador (rotacion EXIF aplicada)
y, si llega una caja, se recorta con la misma regla de pixeles que los
recortes de entrenamiento.

El almacen se inyecta (`ObjectStore`): S3 real, MinIO o un falso en las pruebas.
"""

from __future__ import annotations

import hashlib
import io
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

import torch
from PIL import Image, ImageOps, UnidentifiedImageError
from torch import nn

from p3.data.crops import crop_box
from p3.data.transforms import EVAL_RESIZE, build_eval_transform
from p3.inference.registry import REGISTRY_NAME, ModelEntry, ModelRegistry
from p3.model.build import load_checkpoint

MAX_BYTES = 10 * 1024 * 1024
ACCEPTED_TYPES = {"image/jpeg": "JPEG", "image/png": "PNG"}


class InferenceError(ValueError):
    status_code = 400


class UnsupportedMediaError(InferenceError):
    status_code = 415


class PayloadTooLargeError(InferenceError):
    status_code = 413


class InvalidBoxError(InferenceError):
    status_code = 422


class ModelUnavailableError(RuntimeError):
    """No hay version activa o su objeto no existe (HTTP 409)."""


class StorageUnavailableError(ModelUnavailableError):
    """S3 no esta disponible: sin credenciales, perfil inexistente, sin red o acceso
    denegado (HTTP 503). Es configuracion, no falta de modelo."""


class ModelIntegrityError(RuntimeError):
    """El objeto descargado no es el registrado (HTTP 409)."""


class ObjectStore(Protocol):
    def get_bytes(self, bucket: str, key: str, version_id: str | None = None) -> bytes: ...


@dataclass(frozen=True)
class LoadedModel:
    entry: ModelEntry
    model: nn.Module
    class_names: tuple[str, ...]
    image_size: int
    transform: object


@dataclass(frozen=True)
class Prediction:
    model_version: str
    model_sha256: str
    run_id: str
    predicted_class: str
    probabilities: dict[str, float] = field(default_factory=dict)


class InferenceService:
    def __init__(self, store: ObjectStore, *, bucket: str, prefix: str) -> None:
        self._store = store
        self._bucket = bucket
        self._prefix = prefix.rstrip("/")
        self._cache: dict[tuple[str, str], LoadedModel] = {}
        self._lock = threading.Lock()

    def registry(self) -> ModelRegistry:
        data = self._store.get_bytes(self._bucket, f"{self._prefix}/{REGISTRY_NAME}")
        return ModelRegistry.model_validate_json(data)

    def active_model(self) -> LoadedModel:
        entry = self.registry().active()
        if entry is None:
            raise ModelUnavailableError("No hay una version de modelo activa.")
        key = (entry.version, entry.sha256)
        with self._lock:
            if key not in self._cache:
                self._cache[key] = self._load(entry)
            return self._cache[key]

    def _load(self, entry: ModelEntry) -> LoadedModel:
        data = self._store.get_bytes(self._bucket, entry.key, entry.s3_version_id)
        actual = hashlib.sha256(data).hexdigest()
        if actual != entry.sha256:
            raise ModelIntegrityError(
                f"SHA-256 de s3://{self._bucket}/{entry.key} = {actual}; "
                f"el registro de la version {entry.version} dice {entry.sha256}."
            )
        model, meta = load_checkpoint(io.BytesIO(data))
        preprocessing = meta["preprocessing"]
        if preprocessing.get("resize", EVAL_RESIZE) != EVAL_RESIZE:
            raise ModelIntegrityError(f"Preprocesamiento desconocido: {preprocessing}")
        image_size = int(preprocessing["image_size"])
        return LoadedModel(
            entry=entry,
            model=model,
            class_names=tuple(meta["class_names"]),
            image_size=image_size,
            transform=build_eval_transform(image_size),
        )

    def predict(
        self,
        data: bytes,
        content_type: str,
        bbox_xywh: Sequence[float] | None = None,
    ) -> Prediction:
        image = open_image(data, content_type)
        if bbox_xywh is not None:
            image = image.crop(_checked_box(bbox_xywh, image.size))
        loaded = self.active_model()
        tensor = loaded.transform(image).unsqueeze(0)  # type: ignore[operator]
        with torch.no_grad():
            probabilities = torch.softmax(loaded.model(tensor), dim=1)[0].tolist()
        by_class = dict(zip(loaded.class_names, probabilities, strict=True))
        return Prediction(
            model_version=loaded.entry.version,
            model_sha256=loaded.entry.sha256,
            run_id=loaded.entry.run_id,
            predicted_class=max(by_class, key=by_class.__getitem__),
            probabilities=by_class,
        )


def open_image(data: bytes, content_type: str) -> Image.Image:
    """Valida tamano y tipo y devuelve la imagen como se muestra (EXIF aplicado)."""
    if len(data) > MAX_BYTES:
        raise PayloadTooLargeError(f"La imagen pesa {len(data)} bytes; el limite es {MAX_BYTES}.")
    expected = ACCEPTED_TYPES.get(content_type.split(";")[0].strip().lower())
    if expected is None:
        raise UnsupportedMediaError(f"Tipo {content_type!r} no admitido; usa JPEG o PNG.")
    try:
        with Image.open(io.BytesIO(data)) as handle:
            if handle.format != expected:
                raise UnsupportedMediaError(f"El archivo es {handle.format}, no {expected}.")
            return ImageOps.exif_transpose(handle).convert("RGB")
    except (UnidentifiedImageError, OSError) as error:
        raise UnsupportedMediaError("El archivo no es una imagen valida.") from error


def _checked_box(bbox: Sequence[float], size: tuple[int, int]) -> tuple[int, int, int, int]:
    if len(bbox) != 4:
        raise InvalidBoxError("bbox_xywh debe tener 4 numeros: x, y, ancho, alto.")
    x, y, w, h = (float(v) for v in bbox)
    width, height = size
    if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > width or y + h > height:
        raise InvalidBoxError(f"La caja {list(bbox)} no cabe en la imagen de {width}x{height}.")
    return crop_box((x, y, w, h), size)
