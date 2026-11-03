"""`TrainingConfig`: la configuracion de una corrida (F4 T11, criterio 2.2; contratos §3).

Se valida ANTES de crear el trabajo: la API de P2 la usa en el cuerpo de
`POST /api/p3/training/jobs` y un valor fuera de rango responde 422 nombrando
el campo, sin tocar la BD. Este modulo solo depende de Pydantic, para que la
app de P2 pueda importarlo sin PyTorch.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

HiddenSize = Annotated[int, Field(ge=8, le=4096)]


class TrainingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # Los 7 parametros que varia el barrido (criterio 3.1): obligatorios.
    optimizer: Literal["sgd", "adam", "adamw"]
    batch_size: int = Field(ge=1, le=256)
    max_epochs: int = Field(ge=1, le=200)
    learning_rate: float = Field(gt=0, le=1)
    image_size: int = Field(ge=32, le=512, multiple_of=32)
    hidden_layers: list[HiddenSize] = Field(max_length=4)
    dropout: float = Field(ge=0, le=0.9)

    seed: int = Field(default=42, ge=0, le=2**32 - 1)
    patience: int = Field(default=5, ge=1, le=50)
    min_delta: float = Field(default=0.001, ge=0, le=0.1)
    monitor_metric: Literal["val_accuracy", "val_loss"] = "val_accuracy"
