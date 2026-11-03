"""Early stopping con restauracion de la mejor epoca (F4 T12, criterio 2.4).

Vigila una metrica de VALIDACION (`val_accuracy` se maximiza, `val_loss` se
minimiza). Una epoca mejora si supera a la mejor por mas de `min_delta`; tras
`patience` epocas seguidas sin mejorar, `step` devuelve `True` y el entrenador
se detiene. Guarda una copia del `state_dict` de la mejor epoca para que el
modelo final sea ese y no el de la ultima epoca.
"""

from __future__ import annotations

from collections.abc import Mapping

import torch

MODES = {"val_accuracy": "max", "val_loss": "min"}


class EarlyStopping:
    def __init__(self, *, monitor: str, patience: int, min_delta: float) -> None:
        if monitor not in MODES:
            raise ValueError(f"monitor debe ser uno de {sorted(MODES)}; llego {monitor!r}")
        self.monitor = monitor
        self.mode = MODES[monitor]
        self.patience = patience
        self.min_delta = min_delta
        self.best_value: float | None = None
        self.best_epoch: int | None = None
        self.best_state: dict[str, torch.Tensor] | None = None
        self.stopped_epoch: int | None = None
        self._sin_mejora = 0

    def _mejora(self, value: float) -> bool:
        if self.best_value is None:
            return True
        if self.mode == "max":
            return value > self.best_value + self.min_delta
        return value < self.best_value - self.min_delta

    def step(self, epoch: int, value: float, state_dict: Mapping[str, torch.Tensor]) -> bool:
        """Registra la epoca; `True` si hay que detenerse."""
        if self._mejora(value):
            self.best_value = value
            self.best_epoch = epoch
            self.best_state = {k: v.detach().to("cpu", copy=True) for k, v in state_dict.items()}
            self._sin_mejora = 0
        else:
            self._sin_mejora += 1
        if self._sin_mejora >= self.patience:
            self.stopped_epoch = epoch
            return True
        return False
