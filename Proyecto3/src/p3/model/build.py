"""ResNet-18 con cabeza MLP propia (F4 T10, criterios 2.1 y M4).

- Backbone: `torchvision.models.resnet18` con pesos `IMAGENET1K_V1`
  (decisiones.md §3; origen y licencia en docs/modelo.md).
- Cabeza: reemplaza `fc` por `Linear -> ReLU -> Dropout` por cada entrada de
  `hidden_layers` y una `Linear` final a `num_classes`. Con `hidden_layers=[]`
  queda `Dropout -> Linear`.
- Todas las capas son entrenables (fine-tuning completo).

El checkpoint guarda, ademas de los pesos, todo lo que hace falta para
recargarlo en un proceso limpio (M4): arquitectura, mapa de clases en el orden
de salida y preprocesamiento.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, BinaryIO

import torch
from torch import nn
from torchvision.models import ResNet18_Weights, resnet18

PRETRAINED_WEIGHTS = ResNet18_Weights.IMAGENET1K_V1
ARCHITECTURE = "resnet18"


def build_head(
    in_features: int, hidden_layers: Sequence[int], dropout: float, num_classes: int
) -> nn.Sequential:
    layers: list[nn.Module] = []
    size = in_features
    for hidden in hidden_layers:
        layers += [nn.Linear(size, hidden), nn.ReLU(inplace=True), nn.Dropout(dropout)]
        size = hidden
    if not hidden_layers:
        layers.append(nn.Dropout(dropout))
    layers.append(nn.Linear(size, num_classes))
    return nn.Sequential(*layers)


def build_model(
    *, num_classes: int, hidden_layers: Sequence[int], dropout: float, pretrained: bool
) -> nn.Module:
    """ResNet-18 con la cabeza del clasificador. `pretrained` descarga/usa IMAGENET1K_V1."""
    model = resnet18(weights=PRETRAINED_WEIGHTS if pretrained else None)
    model.fc = build_head(model.fc.in_features, hidden_layers, dropout, num_classes)
    for parameter in model.parameters():
        parameter.requires_grad = True
    return model


def save_checkpoint(
    path: Path,
    model: nn.Module,
    *,
    class_names: Sequence[str],
    hidden_layers: Sequence[int],
    dropout: float,
    preprocessing: Mapping[str, Any],
) -> None:
    """Pesos + arquitectura + mapa de clases + preprocesamiento en un solo archivo."""
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "state_dict": model.state_dict(),
            "architecture": {
                "name": ARCHITECTURE,
                "hidden_layers": list(hidden_layers),
                "dropout": dropout,
                "num_classes": len(class_names),
                "pretrained_weights": f"ResNet18_Weights.{PRETRAINED_WEIGHTS.name}",
            },
            "class_names": list(class_names),
            "preprocessing": dict(preprocessing),
        },
        path,
    )


def load_checkpoint(
    path: Path | BinaryIO, map_location: str = "cpu"
) -> tuple[nn.Module, dict[str, Any]]:
    """Reconstruye el modelo en modo `eval` y devuelve sus metadatos (ruta o bytes)."""
    checkpoint = torch.load(path, map_location=map_location, weights_only=True)
    arch = checkpoint["architecture"]
    if arch["name"] != ARCHITECTURE:
        raise ValueError(f"Arquitectura desconocida en {path}: {arch['name']}")
    model = build_model(
        num_classes=arch["num_classes"],
        hidden_layers=arch["hidden_layers"],
        dropout=arch["dropout"],
        pretrained=False,
    )
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()
    meta = {key: checkpoint[key] for key in ("architecture", "class_names", "preprocessing")}
    return model, meta
