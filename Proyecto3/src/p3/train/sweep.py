"""Barrido de F5 (T13): `config/sweep.yaml` -> cuerpos de `POST /api/p3/training/jobs`.

Todas las corridas se validan con `TrainingConfig` ANTES de encolar la primera:
si una sola es invalida no se lanza nada, para no dejar un barrido a medias.
Solo depende de PyYAML y Pydantic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from p3.train.config import TrainingConfig

EXPERIMENT = "p3-clasificador"


def job_bodies(path: Path) -> list[tuple[str, dict[str, Any]]]:
    """`(nombre, cuerpo)` por corrida, en el orden del archivo."""
    sweep = yaml.safe_load(path.read_text(encoding="utf-8"))
    bodies = []
    for run in sweep["runs"]:
        params = {key: value for key, value in run.items() if key != "name"}
        config = TrainingConfig.model_validate({**params, "seed": sweep["seed"]})
        bodies.append(
            (
                run["name"],
                {
                    "kind": "train",
                    "manifest_id": sweep["manifest_id"],
                    "experiment": EXPERIMENT,
                    "config": config.model_dump(mode="json"),
                },
            )
        )
    return bodies
