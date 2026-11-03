"""Preprocesamiento de recortes (F4 T09, criterio 2.3).

Dos fabricas y nada mas:

- `build_eval_transform`: determinista. La usan validacion, prueba e
  inferencia; es la UNICA definicion del preprocesamiento del modelo.
- `build_train_transform`: la misma normalizacion con aumentacion aleatoria
  (recorte, espejo y color). Solo la usa la particion de train.

El recorte se lleva a `image_size x image_size` estirandolo, sin recortar
bordes: la caja COCO ya encuadra el objeto y un recorte central le quitaria
cabeza o pies a las personas. Normalizacion de ImageNet, la de los pesos
preentrenados de ResNet-18.
"""

from __future__ import annotations

import torch
from torchvision.transforms import v2

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)
# Nombre del preprocesamiento en `model_version.json` (contratos §6).
EVAL_RESIZE = "resize_to_square"


def build_eval_transform(image_size: int) -> v2.Compose:
    return v2.Compose(
        [
            v2.ToImage(),
            v2.Resize((image_size, image_size), antialias=True),
            v2.ToDtype(torch.float32, scale=True),
            v2.Normalize(IMAGENET_MEAN, IMAGENET_STD),
        ]
    )


def build_train_transform(image_size: int) -> v2.Compose:
    return v2.Compose(
        [
            v2.ToImage(),
            v2.RandomResizedCrop(
                (image_size, image_size), scale=(0.7, 1.0), ratio=(0.75, 4 / 3), antialias=True
            ),
            v2.RandomHorizontalFlip(),
            v2.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.2, hue=0.02),
            v2.ToDtype(torch.float32, scale=True),
            v2.Normalize(IMAGENET_MEAN, IMAGENET_STD),
        ]
    )
