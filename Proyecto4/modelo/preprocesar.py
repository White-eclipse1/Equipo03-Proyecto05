"""Preprocesamiento del modelo para el dispositivo edge: numpy + Pillow, sin PyTorch.

Reproduce `build_eval_transform` del Proyecto 3 (`Proyecto3/src/p3/data/transforms.py`):
RGB, estirado a `tamano x tamano` sin recortar bordes (bilineal con antialias),
escala a [0, 1] y normalizacion de ImageNet. Sale en NCHW float32 con lote 1.

La variante INT8 recibe esta misma entrada en float32: la cuantizacion de la
entrada ocurre dentro del grafo (`QuantizeLinear`), el dispositivo no cuantiza a mano.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

MEDIA = np.array([0.485, 0.456, 0.406], dtype=np.float32)
DESVIACION = np.array([0.229, 0.224, 0.225], dtype=np.float32)
TAMANO = 224


def preprocesar(imagen: Image.Image, tamano: int = TAMANO) -> np.ndarray:
    """Imagen PIL -> tensor `[1, 3, tamano, tamano]` float32 listo para el modelo."""
    rgb = imagen.convert("RGB").resize((tamano, tamano), Image.Resampling.BILINEAR)
    x = np.asarray(rgb, dtype=np.float32) / 255.0
    x = (x - MEDIA) / DESVIACION
    return np.ascontiguousarray(x.transpose(2, 0, 1)[np.newaxis], dtype=np.float32)


def softmax(logits: np.ndarray) -> np.ndarray:
    z = logits - logits.max(axis=-1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=-1, keepdims=True)
