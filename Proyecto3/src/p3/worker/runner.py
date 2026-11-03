"""Bucle del worker: toma trabajos de la cola y los ejecuta fuera del request.

    python -m p3.worker.runner

Cada tipo de trabajo (`kind`) tiene un handler `(config, report) -> None`.
`report(progress, message)` escribe progreso y log en la BD en su propia
transaccion, para que la pagina los vea mientras el trabajo corre; con
`mlflow_run_id=...` ademas enlaza el trabajo con su run de MLflow. El handler
recibe la config del trabajo mas su `job_id`. Si lanza una excepcion, el
trabajo queda `failed` con el mensaje y el worker sigue con el siguiente.
"""

from __future__ import annotations

import hashlib
import logging
import socket
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy.orm import Session, sessionmaker

from p3.data.frozen import FROZEN_MANIFESTS
from p3.worker import jobs


class Report(Protocol):
    def __call__(
        self, progress: float, message: str, *, mlflow_run_id: str | None = None
    ) -> None: ...


Handler = Callable[[dict[str, Any], Report], None]

logger = logging.getLogger("p3.worker")


def run_dummy(config: dict[str, Any], report: Report) -> None:
    """Trabajo de prueba del stack: avanza por pasos sin entrenar nada."""
    steps = int(config.get("steps", 5))
    seconds = float(config.get("seconds", 1.0))
    for step in range(1, steps + 1):
        time.sleep(seconds)
        report(step / steps, f"paso {step}/{steps}")
    if config.get("fail"):
        raise RuntimeError("error simulado por config.fail")


HANDLERS: Mapping[str, Handler] = {"dummy": run_dummy}


def make_train_handler(
    *,
    data_dir: Path,
    device: str,
    tracking_uri: str,
    pretrained: bool = True,
    num_workers: int = 0,
    code_commit: str = "unknown",
    code_dirty: bool = False,
    frozen: Mapping[str, str] = FROZEN_MANIFESTS,
) -> Handler:
    """Handler de `kind: "train"`: entrena sobre el manifiesto congelado y lo registra.

    `data_dir` contiene `manifests/<manifest_id>/` (puntero DVC congelado, F3) y
    `crops/<release_id>/crops.jsonl` (`generate_crops.py`). Antes de tocar datos
    comprueba que el manifiesto sea exactamente el congelado. PyTorch y MLflow se
    importan aqui para que la app de P2, que importa este paquete, no los necesite.
    """

    def run_train(config: dict[str, Any], report: Report) -> None:
        from p3.data import dataset
        from p3.data.frozen import verify_frozen
        from p3.train import tracking
        from p3.train.config import TrainingConfig

        manifest_dir = data_dir / "manifests" / config["manifest_id"]
        meta = verify_frozen(manifest_dir, frozen)
        training = TrainingConfig.model_validate(config["training"])
        rows = dataset.load_manifest(manifest_dir / "manifest.jsonl")
        release = meta["release"]
        crops_dir = data_dir / "crops" / release["release_id"]
        crop_index = dataset.load_crop_index(crops_dir)
        crops_sha256 = hashlib.sha256((crops_dir / "crops.jsonl").read_bytes()).hexdigest()
        datasets = dataset.build_datasets(rows, crop_index, image_size=training.image_size)
        classes = sorted(meta["classes"], key=lambda c: c["class_index"])
        context = tracking.RunContext(
            manifest_id=config["manifest_id"],
            manifest_hash=meta["manifest_hash"],
            release_id=release["release_id"],
            release_hash=release["dataset_fingerprint"],
            dvc_md5=release["dvc_pointer"]["md5"],
            crops_sha256=crops_sha256,
            class_names=tuple(c["category_name"] for c in classes),
            code_commit=code_commit,
            code_dirty=code_dirty,
            job_id=config.get("job_id"),
        )

        def on_start(run_id: str) -> None:
            report(0.0, f"mlflow_run_id={run_id} en {device}", mlflow_run_id=run_id)

        def on_epoch(metrics: dict[str, float]) -> None:
            epoch = int(metrics["epoch"])
            report(
                epoch / training.max_epochs,
                f"epoca {epoch}/{training.max_epochs} "
                f"train_loss={metrics['train_loss']:.4f} train_acc={metrics['train_accuracy']:.4f} "
                f"val_loss={metrics['val_loss']:.4f} val_acc={metrics['val_accuracy']:.4f} "
                f"({metrics['epoch_seconds']:.1f} s)",
            )

        result, run_id = tracking.run_training(
            training,
            datasets=datasets,
            context=context,
            device=device,
            pretrained=pretrained,
            tracking_uri=tracking_uri,
            num_workers=num_workers,
            on_epoch=on_epoch,
            on_start=on_start,
            experiment=config.get("experiment", tracking.EXPERIMENT),
        )
        motivo = "early stopping" if result.early_stopped else "max_epochs"
        report(
            1.0,
            f"fin por {motivo} en la epoca {result.stopped_epoch}; mejor epoca "
            f"{result.best_epoch} val_acc={result.best_metrics['val_accuracy']:.4f} "
            f"(run {run_id})",
        )

    return run_train


def run_once(
    session_factory: sessionmaker[Session], worker_id: str, handlers: Mapping[str, Handler]
) -> bool:
    """Procesa un trabajo si hay alguno en cola. Devuelve si proceso uno."""
    with session_factory.begin() as session:
        job = jobs.claim_next(session, worker_id)
        if job is None:
            return False
        job_id, kind, config = job.id, job.kind, dict(job.config)

    def report(progress: float, message: str, *, mlflow_run_id: str | None = None) -> None:
        with session_factory.begin() as session:
            jobs.report_progress(session, job_id, progress, message)
            if mlflow_run_id is not None:
                jobs.set_mlflow_run_id(session, job_id, mlflow_run_id)

    handler = handlers.get(kind)
    try:
        if handler is None:
            raise LookupError(f"No hay handler para el tipo de trabajo '{kind}'")
        handler({**config, "job_id": job_id}, report)
    except Exception as error:
        logger.exception("El trabajo %s fallo", job_id)
        with session_factory.begin() as session:
            jobs.mark_failed(session, job_id, f"{type(error).__name__}: {error}")
    else:
        with session_factory.begin() as session:
            jobs.mark_succeeded(session, job_id)
    return True


def main() -> None:
    from p3.worker.settings import get_session_factory, get_settings

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    settings = get_settings()
    session_factory = get_session_factory()
    worker_id = socket.gethostname()
    handlers = {
        **HANDLERS,
        "train": make_train_handler(
            data_dir=settings.data_dir,
            device=settings.resolved_device(),
            tracking_uri=settings.mlflow_tracking_uri,
            num_workers=settings.num_workers,
            code_commit=settings.code_commit,
            code_dirty=settings.code_dirty,
        ),
    }

    with session_factory.begin() as session:
        recovered = jobs.recover_orphans(session)
    logger.info("worker %s listo; %d trabajo(s) huerfano(s) marcados failed", worker_id, recovered)

    while True:
        if not run_once(session_factory, worker_id, handlers):
            time.sleep(settings.poll_seconds)


if __name__ == "__main__":
    main()
