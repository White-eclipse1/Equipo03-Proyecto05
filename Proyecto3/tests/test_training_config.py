"""`TrainingConfig` validada antes de crear el trabajo (F4 T11, criterio 2.2; contratos §3)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from p3.train.config import TrainingConfig

VALIDA = {
    "optimizer": "adamw",
    "batch_size": 32,
    "max_epochs": 30,
    "learning_rate": 0.0003,
    "image_size": 224,
    "hidden_layers": [256],
    "dropout": 0.3,
}


def test_el_ejemplo_del_contrato_es_valido_y_completa_los_defaults() -> None:
    config = TrainingConfig.model_validate(VALIDA)
    assert config.seed == 42
    assert config.patience == 5
    assert config.min_delta == 0.001
    assert config.monitor_metric == "val_accuracy"


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("optimizer", "rmsprop"),
        ("batch_size", 0),
        ("batch_size", 257),
        ("max_epochs", 0),
        ("max_epochs", 201),
        ("learning_rate", 0),
        ("learning_rate", -0.01),
        ("learning_rate", 1.5),
        ("image_size", 16),
        ("image_size", 100),
        ("image_size", 544),
        ("hidden_layers", [4]),
        ("hidden_layers", [8192]),
        ("hidden_layers", [64, 64, 64, 64, 64]),
        ("dropout", -0.1),
        ("dropout", 0.95),
        ("dropout", 1.0),
        ("seed", -1),
        ("patience", 0),
        ("min_delta", 0.5),
        ("monitor_metric", "test_accuracy"),
    ],
)
def test_un_valor_fuera_de_rango_se_rechaza_nombrando_el_campo(campo: str, valor: object) -> None:
    with pytest.raises(ValidationError) as error:
        TrainingConfig.model_validate({**VALIDA, campo: valor})
    assert [e["loc"][0] for e in error.value.errors()] == [campo]


@pytest.mark.parametrize("faltante", sorted(VALIDA))
def test_los_siete_parametros_del_barrido_son_obligatorios(faltante: str) -> None:
    datos = {k: v for k, v in VALIDA.items() if k != faltante}
    with pytest.raises(ValidationError, match=faltante):
        TrainingConfig.model_validate(datos)


def test_un_campo_desconocido_se_rechaza() -> None:
    with pytest.raises(ValidationError, match="momentum"):
        TrainingConfig.model_validate({**VALIDA, "momentum": 0.9})


def test_no_importa_torch() -> None:
    # La API de P2 valida la config con este modulo y su imagen no tiene PyTorch.
    import p3.train.config as module

    assert "import torch" not in Path(module.__file__).read_text(encoding="utf-8")
