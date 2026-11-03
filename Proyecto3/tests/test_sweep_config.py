"""`config/sweep.yaml` cumple lo que pide 3.1 antes de lanzar el barrido (F4 T32 / F5 T13)."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from p3.train.config import TrainingConfig

SWEEP = Path(__file__).parents[1] / "config" / "sweep.yaml"
PARAMETROS = (
    "optimizer",
    "batch_size",
    "max_epochs",
    "learning_rate",
    "image_size",
    "hidden_layers",
    "dropout",
)


def _sweep() -> dict:
    return yaml.safe_load(SWEEP.read_text(encoding="utf-8"))


def _configs() -> list[TrainingConfig]:
    sweep = _sweep()
    return [
        TrainingConfig.model_validate(
            {**{k: v for k, v in run.items() if k != "name"}, "seed": sweep["seed"]}
        )
        for run in sweep["runs"]
    ]


def test_al_menos_diez_corridas_validas_y_distintas() -> None:
    configs = _configs()
    assert len(configs) >= 10
    distintas = {json.dumps(c.model_dump(), sort_keys=True) for c in configs}
    assert len(distintas) == len(configs)


def test_cada_uno_de_los_siete_parametros_toma_al_menos_dos_valores() -> None:
    configs = _configs()
    for parametro in PARAMETROS:
        valores = {json.dumps(getattr(c, parametro)) for c in configs}
        assert len(valores) >= 2, parametro


def test_todas_usan_el_manifiesto_congelado() -> None:
    assert _sweep()["manifest_id"] == "m-0.1.3-s42-1"


def test_los_nombres_son_unicos() -> None:
    names = [run["name"] for run in _sweep()["runs"]]
    assert len(names) == len(set(names))
