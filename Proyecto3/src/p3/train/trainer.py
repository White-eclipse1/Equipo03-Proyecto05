"""Entrenamiento por minibatches con semillas controladas (F4 T11, criterios 2.1-2.3).

Por epoca: para cada minibatch de train, `forward -> loss -> backward ->
optimizer.step()`; despues se evalua val sin gradientes. Si el ultimo
minibatch de train tendria UNA sola muestra se omite (BatchNorm no puede
entrenar con ella); como el orden se baraja cada epoca, la muestra omitida
cambia de una epoca a otra. La historia guarda loss, accuracy y duracion de
train y val por epoca.

Early stopping (T12): tras cada epoca se vigila `config.monitor_metric` en
validacion; con `patience` epocas sin mejorar mas de `min_delta` se detiene y el
modelo que se devuelve es el de la MEJOR epoca, no el de la ultima.

Reproducibilidad: `seed_everything` siembra `random`, `numpy` y `torch` (y
CUDA) antes de construir el modelo, asi que la cabeza nueva, el orden del
DataLoader (generator sembrado) y la aumentacion salen iguales con la misma
semilla. Se piden algoritmos deterministas (`warn_only`): en CPU la corrida es
identica; en GPU algunas operaciones de cuDNN pueden variar en el ultimo
decimal, lo que queda anotado en `environment_info`.

Logica pura: recibe datasets, config y dispositivo; no lee el entorno ni habla
con MLflow o la BD.
"""

from __future__ import annotations

import platform
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import PIL
import torch
import torchvision
from torch import nn

from p3.data.dataset import CropDataset, build_loader
from p3.model.build import build_model
from p3.train.config import TrainingConfig
from p3.train.early_stopping import EarlyStopping

SGD_MOMENTUM = 0.9

EpochCallback = Callable[[dict[str, float]], None]
BatchCallback = Callable[[torch.Tensor], None]
ModelCallback = Callable[[nn.Module], None]


@dataclass
class TrainResult:
    model: nn.Module
    history: list[dict[str, float]] = field(default_factory=list)
    optimizer_steps: int = 0
    train_order: list[str] = field(default_factory=list)
    best_epoch: int = 0
    best_metrics: dict[str, float] = field(default_factory=dict)
    # Ultima epoca entrenada; `early_stopped` dice si fue por early stopping.
    stopped_epoch: int = 0
    early_stopped: bool = False


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def environment_info(device: str) -> dict[str, Any]:
    """Versiones y dispositivo de la corrida (se registran en MLflow)."""
    cuda = torch.cuda.is_available() and device.startswith("cuda")
    return {
        "python": platform.python_version(),
        "torch": torch.__version__,
        "torchvision": torchvision.__version__,
        "numpy": np.__version__,
        "pillow": PIL.__version__,
        "cuda": torch.version.cuda,
        "cudnn": torch.backends.cudnn.version() if cuda else None,
        "device": torch.cuda.get_device_name(0) if cuda else "cpu",
        "deterministic": torch.are_deterministic_algorithms_enabled(),
        "platform": platform.platform(),
    }


def build_model_for(config: TrainingConfig, *, num_classes: int, pretrained: bool) -> nn.Module:
    return build_model(
        num_classes=num_classes,
        hidden_layers=config.hidden_layers,
        dropout=config.dropout,
        pretrained=pretrained,
    )


def build_optimizer(config: TrainingConfig, model: nn.Module) -> torch.optim.Optimizer:
    params = model.parameters()
    if config.optimizer == "sgd":
        return torch.optim.SGD(params, lr=config.learning_rate, momentum=SGD_MOMENTUM)
    if config.optimizer == "adam":
        return torch.optim.Adam(params, lr=config.learning_rate)
    return torch.optim.AdamW(params, lr=config.learning_rate)


def evaluate(
    model: nn.Module, dataset: CropDataset, *, batch_size: int, device: str
) -> tuple[float, float]:
    """`(loss media, accuracy)` sin gradientes y en modo `eval`."""
    model.eval()
    loader = build_loader(dataset, batch_size=batch_size, shuffle=False, seed=0)
    loss_fn = nn.CrossEntropyLoss(reduction="sum")
    total_loss, correct, seen = 0.0, 0, 0
    with torch.no_grad():
        for images, labels, _ in loader:
            images, labels = images.to(device), labels.to(device)
            logits = model(images)
            total_loss += loss_fn(logits, labels).item()
            correct += (logits.argmax(dim=1) == labels).sum().item()
            seen += labels.numel()
    return total_loss / seen, correct / seen


def train(
    config: TrainingConfig,
    *,
    train_set: CropDataset,
    val_set: CropDataset,
    num_classes: int,
    pretrained: bool,
    device: str,
    num_workers: int = 0,
    on_epoch: EpochCallback | None = None,
    on_batch: BatchCallback | None = None,
    on_model: ModelCallback | None = None,
) -> TrainResult:
    seed_everything(config.seed)
    model = build_model_for(config, num_classes=num_classes, pretrained=pretrained).to(device)
    if on_model is not None:
        on_model(model)
    stopper = EarlyStopping(
        monitor=config.monitor_metric, patience=config.patience, min_delta=config.min_delta
    )
    optimizer = build_optimizer(config, model)
    loss_fn = nn.CrossEntropyLoss()
    loader = build_loader(
        train_set,
        batch_size=config.batch_size,
        shuffle=True,
        seed=config.seed,
        num_workers=num_workers,
        drop_last=len(train_set) % config.batch_size == 1,
    )
    result = TrainResult(model=model)

    for epoch in range(1, config.max_epochs + 1):
        started = time.perf_counter()
        model.train()
        running_loss, correct, seen = 0.0, 0, 0
        for images, labels, crop_ids in loader:
            if on_batch is not None:
                on_batch(images)
            images, labels = images.to(device), labels.to(device)
            optimizer.zero_grad()
            logits = model(images)
            loss = loss_fn(logits, labels)
            loss.backward()
            optimizer.step()
            result.optimizer_steps += 1
            result.train_order.extend(crop_ids)
            running_loss += loss.item() * labels.numel()
            correct += (logits.argmax(dim=1) == labels).sum().item()
            seen += labels.numel()

        val_loss, val_accuracy = evaluate(
            model, val_set, batch_size=config.batch_size, device=device
        )
        metrics = {
            "epoch": epoch,
            "train_loss": running_loss / seen,
            "train_accuracy": correct / seen,
            "val_loss": val_loss,
            "val_accuracy": val_accuracy,
            "epoch_seconds": time.perf_counter() - started,
        }
        result.history.append(metrics)
        if on_epoch is not None:
            on_epoch(metrics)
        result.stopped_epoch = epoch
        if stopper.step(epoch, metrics[config.monitor_metric], model.state_dict()):
            result.early_stopped = True
            break

    assert stopper.best_state is not None and stopper.best_epoch is not None
    model.load_state_dict(stopper.best_state)
    result.best_epoch = stopper.best_epoch
    result.best_metrics = dict(result.history[stopper.best_epoch - 1])
    return result
