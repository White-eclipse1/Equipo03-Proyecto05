"""Registro completo de cada corrida en MLflow (F4 T12, criterios 2.4 y 3.2).

Las pruebas usan un tracking store en archivos (`MLFLOW_ALLOW_FILE_STORE`,
solo aqui); el worker real habla con el servidor MLflow del compose.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import torch
from mlflow.tracking import MlflowClient
from PIL import Image

from p3.data import dataset
from p3.model.build import load_checkpoint
from p3.train import tracking
from p3.train.config import TrainingConfig

CONTEXT = tracking.RunContext(
    manifest_id="m-9.9.9-s1-1",
    manifest_hash="a" * 64,
    release_id="9.9.9",
    release_hash="b" * 64,
    dvc_md5="c" * 32 + ".dir",
    crops_sha256="e" * 64,
    class_names=("cat", "dog", "person"),
    code_commit="d" * 40,
    code_dirty=False,
    job_id="job123",
)


@pytest.fixture
def tracking_uri(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("MLFLOW_ALLOW_FILE_STORE", "true")
    return (tmp_path / "mlruns").as_uri()


@pytest.fixture
def datasets(tmp_path: Path) -> dict[str, dataset.CropDataset]:
    rows, index = [], {}
    for i in range(9):
        path = tmp_path / f"c{i}.png"
        Image.new("RGB", (36, 36), ((i % 3) * 110, 60, 160)).save(path)
        index[f"x:a{i}"] = path
        rows.append(
            {
                "crop_id": f"x:a{i}",
                "source_image_id": i,
                "dup_group_id": f"g{i}",
                "class_index": i % 3,
                "split": "train" if i < 6 else "val",
            }
        )
    return dataset.build_datasets(rows, index, image_size=32)


def _config(**cambios: object) -> TrainingConfig:
    base = {
        "optimizer": "adam",
        "batch_size": 3,
        "max_epochs": 3,
        "learning_rate": 0.001,
        "image_size": 32,
        "hidden_layers": [16],
        "dropout": 0.1,
        "seed": 5,
    }
    return TrainingConfig.model_validate({**base, **cambios})


def _run(datasets, tracking_uri, **kwargs):
    return tracking.run_training(
        kwargs.pop("config", _config()),
        datasets=datasets,
        context=CONTEXT,
        device="cpu",
        pretrained=False,
        tracking_uri=tracking_uri,
        **kwargs,
    )


def test_la_corrida_queda_finished_con_parametros_y_procedencia(datasets, tracking_uri) -> None:
    _, run_id = _run(datasets, tracking_uri)
    run = MlflowClient(tracking_uri).get_run(run_id)

    assert run.info.status == "FINISHED"
    params = run.data.params
    for campo, valor in _config().model_dump().items():
        assert params[campo] == str(valor), campo
    tags = run.data.tags
    assert tags["manifest_id"] == CONTEXT.manifest_id
    assert tags["manifest_hash"] == CONTEXT.manifest_hash
    assert tags["release_id"] == "9.9.9"
    assert tags["release_hash"] == CONTEXT.release_hash
    assert tags["dvc_md5"] == CONTEXT.dvc_md5
    assert tags["crops_jsonl_sha256"] == "e" * 64
    assert json.loads(tags["classes"]) == ["cat", "dog", "person"]
    assert tags["code_commit"] == CONTEXT.code_commit
    assert tags["code_dirty"] == "false"
    assert tags["job_id"] == "job123"
    assert tags["env.torch"] == torch.__version__
    assert tags["pretrained_weights"] == "none"


def test_metricas_por_epoca_y_resumen_de_early_stopping(datasets, tracking_uri) -> None:
    result, run_id = _run(datasets, tracking_uri)
    client = MlflowClient(tracking_uri)
    for metrica in ("train_loss", "train_accuracy", "val_loss", "val_accuracy", "epoch_seconds"):
        historia = client.get_metric_history(run_id, metrica)
        assert [m.step for m in historia] == list(range(1, len(result.history) + 1)), metrica
    resumen = client.get_run(run_id).data.metrics
    assert resumen["best_epoch"] == result.best_epoch
    assert resumen["stopped_epoch"] == result.stopped_epoch
    assert resumen["best_val_accuracy"] == result.best_metrics["val_accuracy"]
    assert resumen["best_val_loss"] == result.best_metrics["val_loss"]


def test_artefactos_curvas_historia_y_checkpoint_de_la_mejor_epoca(
    datasets, tracking_uri, tmp_path: Path
) -> None:
    result, run_id = _run(datasets, tracking_uri)
    client = MlflowClient(tracking_uri)
    rutas = {a.path for a in client.list_artifacts(run_id)}
    assert {"curves.png", "history.json", "environment.json", "checkpoint"} <= rutas

    local = Path(client.download_artifacts(run_id, "checkpoint/model.pt", str(tmp_path)))
    modelo, meta = load_checkpoint(local)
    assert meta["class_names"] == ["cat", "dog", "person"]
    assert meta["preprocessing"]["image_size"] == 32
    for (k, a), (_, b) in zip(
        modelo.state_dict().items(), result.model.state_dict().items(), strict=True
    ):
        assert torch.equal(a, b.cpu()), k

    historia = json.loads(
        Path(client.download_artifacts(run_id, "history.json", str(tmp_path))).read_text()
    )
    assert [fila["epoch"] for fila in historia] == [f["epoch"] for f in result.history]


def test_una_corrida_que_falla_queda_failed(datasets, tracking_uri) -> None:
    def explota(metrics):
        raise RuntimeError("se fue la luz")

    with pytest.raises(RuntimeError, match="luz"):
        _run(datasets, tracking_uri, on_epoch=explota)

    runs = MlflowClient(tracking_uri).search_runs(
        [MlflowClient(tracking_uri).get_experiment_by_name(tracking.EXPERIMENT).experiment_id]
    )
    assert [r.info.status for r in runs] == ["FAILED"]


def test_las_corridas_de_prueba_van_a_otro_experimento(datasets, tracking_uri) -> None:
    _, run_id = _run(datasets, tracking_uri, config=_config(max_epochs=1), experiment="p3-pruebas")
    client = MlflowClient(tracking_uri)
    experiment = client.get_experiment(client.get_run(run_id).info.experiment_id)
    assert experiment.name == "p3-pruebas"
    assert client.get_experiment_by_name(tracking.EXPERIMENT) is None
