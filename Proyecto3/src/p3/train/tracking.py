"""Registro completo de cada corrida en MLflow (F4 T12, criterios 2.4 y 3.2).

`run_training` envuelve `trainer.train` en un run de MLflow y registra:

- parametros: la `TrainingConfig` efectiva (incluida la semilla);
- tags: manifiesto y su hash, release y su huella, md5 DVC de las imagenes,
  SHA-256 del `crops.jsonl` con que se entreno,
  clases, commit del codigo, id del trabajo, pesos iniciales y entorno
  (`env.*`: versiones de Python, PyTorch, CUDA, dispositivo);
- metricas por epoca (`step` = epoca): loss y accuracy de train y val y su
  duracion; al final `best_epoch`, `stopped_epoch`, `early_stopped`,
  `best_val_accuracy` y `best_val_loss`;
- artefactos: `curves.png`, `history.json`, `environment.json` y
  `checkpoint/model.pt` (pesos de la MEJOR epoca, recargables con
  `p3.model.build.load_checkpoint`).

Si el entrenamiento lanza una excepcion, MLflow cierra el run como `FAILED`.
El test nunca se toca aqui: solo train y val.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from p3.data.dataset import CropDataset
from p3.data.transforms import EVAL_RESIZE, IMAGENET_MEAN, IMAGENET_STD
from p3.model.build import PRETRAINED_WEIGHTS, save_checkpoint
from p3.train.config import TrainingConfig
from p3.train.trainer import EpochCallback, TrainResult, environment_info, train

EXPERIMENT = "p3-clasificador"
# Corridas de humo y de medicion: nunca se mezclan con el barrido ni con la seleccion.
EXPERIMENTS = (EXPERIMENT, "p3-pruebas")
CURVAS = ("loss", "accuracy")


@dataclass(frozen=True)
class RunContext:
    manifest_id: str
    manifest_hash: str
    release_id: str
    release_hash: str
    dvc_md5: str
    # SHA-256 de `crops.jsonl`: prueba con que recortes se entreno (no estan en Git ni DVC).
    crops_sha256: str
    class_names: tuple[str, ...]
    code_commit: str
    code_dirty: bool
    job_id: str | None = None


def preprocessing_for(config: TrainingConfig) -> dict[str, object]:
    return {
        "image_size": config.image_size,
        "resize": EVAL_RESIZE,
        "mean": list(IMAGENET_MEAN),
        "std": list(IMAGENET_STD),
    }


def _plot_curves(history: list[dict[str, float]], best_epoch: int, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    epochs = [int(row["epoch"]) for row in history]
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for ax, metric in zip(axes, CURVAS, strict=True):
        for split in ("train", "val"):
            ax.plot(epochs, [row[f"{split}_{metric}"] for row in history], marker="o", label=split)
        ax.axvline(best_epoch, color="gray", linestyle="--", label=f"mejor epoca ({best_epoch})")
        ax.set_xlabel("epoca")
        ax.set_ylabel(metric)
        ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)


def run_training(
    config: TrainingConfig,
    *,
    datasets: Mapping[str, CropDataset],
    context: RunContext,
    device: str,
    pretrained: bool,
    tracking_uri: str,
    num_workers: int = 0,
    on_epoch: EpochCallback | None = None,
    on_start: Callable[[str], None] | None = None,
    experiment: str = EXPERIMENT,
) -> tuple[TrainResult, str]:
    """Entrena con train/val y registra la corrida; devuelve el resultado y el `run_id`."""
    import mlflow

    if experiment not in EXPERIMENTS:
        raise ValueError(f"Experimento desconocido {experiment!r}; validos: {EXPERIMENTS}")
    mlflow.set_tracking_uri(tracking_uri)
    mlflow_experiment = mlflow.set_experiment(experiment)
    environment = environment_info(device)

    with mlflow.start_run(
        experiment_id=mlflow_experiment.experiment_id, run_name=context.job_id or None
    ) as run:
        run_id = run.info.run_id
        if on_start is not None:
            on_start(run_id)
        mlflow.log_params(config.model_dump())
        mlflow.set_tags(
            {
                "manifest_id": context.manifest_id,
                "manifest_hash": context.manifest_hash,
                "release_id": context.release_id,
                "release_hash": context.release_hash,
                "dvc_md5": context.dvc_md5,
                "crops_jsonl_sha256": context.crops_sha256,
                "classes": json.dumps(list(context.class_names)),
                "code_commit": context.code_commit,
                "code_dirty": "true" if context.code_dirty else "false",
                "job_id": context.job_id or "",
                "pretrained_weights": (
                    f"ResNet18_Weights.{PRETRAINED_WEIGHTS.name}" if pretrained else "none"
                ),
                **{f"env.{key}": str(value) for key, value in environment.items()},
            }
        )

        def log_epoch(metrics: dict[str, float]) -> None:
            mlflow.log_metrics(
                {k: float(v) for k, v in metrics.items() if k != "epoch"},
                step=int(metrics["epoch"]),
            )
            if on_epoch is not None:
                on_epoch(metrics)

        result = train(
            config,
            train_set=datasets["train"],
            val_set=datasets["val"],
            num_classes=len(context.class_names),
            pretrained=pretrained,
            device=device,
            num_workers=num_workers,
            on_epoch=log_epoch,
        )

        mlflow.log_metrics(
            {
                "best_epoch": result.best_epoch,
                "stopped_epoch": result.stopped_epoch,
                "early_stopped": float(result.early_stopped),
                "best_val_accuracy": result.best_metrics["val_accuracy"],
                "best_val_loss": result.best_metrics["val_loss"],
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "history.json").write_text(
                json.dumps(result.history, indent=2), encoding="utf-8"
            )
            (folder / "environment.json").write_text(
                json.dumps(environment, indent=2), encoding="utf-8"
            )
            _plot_curves(result.history, result.best_epoch, folder / "curves.png")
            save_checkpoint(
                folder / "checkpoint" / "model.pt",
                result.model.to("cpu"),
                class_names=context.class_names,
                hidden_layers=config.hidden_layers,
                dropout=config.dropout,
                preprocessing=preprocessing_for(config),
            )
            for name in ("history.json", "environment.json", "curves.png"):
                mlflow.log_artifact(str(folder / name))
            mlflow.log_artifacts(str(folder / "checkpoint"), artifact_path="checkpoint")
    return result, run_id
