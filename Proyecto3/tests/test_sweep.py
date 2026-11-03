"""El lanzador del barrido convierte `config/sweep.yaml` en trabajos `train` validos (F5 T13)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from p3.train import sweep

SWEEP = Path(__file__).parents[1] / "config" / "sweep.yaml"


def test_una_solicitud_por_corrida_sobre_el_manifiesto_congelado() -> None:
    bodies = sweep.job_bodies(SWEEP)
    assert [name for name, _ in bodies] == [f"r{i:02d}" for i in range(1, 13)]
    for _, body in bodies:
        assert body["kind"] == "train"
        assert body["manifest_id"] == "m-0.1.3-s42-1"
        assert body["experiment"] == "p3-clasificador"
        assert body["config"]["seed"] == 42


def test_la_config_ya_va_validada_y_completa() -> None:
    _, body = sweep.job_bodies(SWEEP)[0]
    assert set(body["config"]) == {
        "optimizer",
        "batch_size",
        "max_epochs",
        "learning_rate",
        "image_size",
        "hidden_layers",
        "dropout",
        "seed",
        "patience",
        "min_delta",
        "monitor_metric",
    }


def test_un_sweep_con_una_corrida_invalida_no_lanza_nada(tmp_path: Path) -> None:
    data = yaml.safe_load(SWEEP.read_text(encoding="utf-8"))
    data["runs"][5]["dropout"] = 1.5
    path = tmp_path / "sweep.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ValidationError, match="dropout"):
        sweep.job_bodies(path)
