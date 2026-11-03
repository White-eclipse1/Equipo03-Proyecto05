"""Arma el paquete de una version de modelo y lo publica en S3 (F7 T17-T18).

Datos de la corrida desde MLflow, por defecto desde el snapshot versionado con DVC
(`mlflow_snapshot/`, `dvc pull mlflow_snapshot.dvc`): parametros, tags, `best_val_accuracy`,
`best_epoch` y el checkpoint de la mejor epoca). Para la version seleccionada,
ademas `docs/selection.json` y la evaluacion final de F6; una version no
seleccionada no lleva metricas de test (`p3.registry.package`).

El paquete se escribe en `data/models/<version>/` (fuera de Git). Con
`--dry-run` no se toca S3. Sin el, se publica en
`s3://<bucket>/<prefix>/<version>/` y se actualiza `registry.json`
(`p3.registry.publish`): solo se registra si cada objeto existe y el SHA-256
descargado coincide. Credenciales: el perfil de `~/.aws`, nunca el repo.

    cd Proyecto3
    .venv/Scripts/python scripts/publish_model.py --version 1.0.0 --selected --activate \\
        --profile <perfil> [--dry-run]
    .venv/Scripts/python scripts/publish_model.py --version 0.9.0 --run-id <run_id> \\
        --profile <perfil> [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

PROYECTO3 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROYECTO3 / "src"))

import yaml  # noqa: E402

from p3.registry.package import build_package  # noqa: E402
from p3.registry.publish import list_versions, publish_version  # noqa: E402
from p3.registry.s3 import S3Store  # noqa: E402
from p3.train.selection import MlflowRest, RunSummary  # noqa: E402

BUCKET = "dataset-quality-releases-750702272375"
PREFIX = "models/clasificador"
CHECKPOINT = "checkpoint/model.pt"


class SnapshotRuns:
    """Lee corridas del snapshot de MLflow versionado con DVC (`mlflow_snapshot/`).

    Misma interfaz que `MlflowRest` para lo que usa este script; no hace falta
    levantar el servidor. Es lo mismo que ve el evaluador tras `dvc pull`.
    """

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.db = sqlite3.connect(folder / "mlflow.db")

    def search_runs(self, experiment: str) -> list[RunSummary]:
        rows = self.db.execute(
            "select r.run_uuid, r.experiment_id, r.status, r.end_time, r.start_time, "
            "r.artifact_uri from runs r join experiments e using (experiment_id) "
            "where e.name = ?",
            (experiment,),
        ).fetchall()
        runs = []
        for run_id, experiment_id, status, end, start, artifact_uri in rows:
            tags = dict(
                self.db.execute("select key, value from tags where run_uuid = ?", (run_id,))
            )
            params = dict(
                self.db.execute("select key, value from params where run_uuid = ?", (run_id,))
            )
            metrics = dict(
                self.db.execute(
                    "select key, value from latest_metrics where run_uuid = ?", (run_id,)
                )
            )
            runs.append(
                RunSummary(
                    run_id=run_id,
                    experiment_id=str(experiment_id),
                    status=status,
                    end_time=end,
                    start_time=start,
                    best_val_accuracy=metrics.get("best_val_accuracy"),
                    best_val_loss=metrics.get("best_val_loss"),
                    best_epoch=int(metrics["best_epoch"]) if "best_epoch" in metrics else None,
                    stopped_epoch=(
                        int(metrics["stopped_epoch"]) if "stopped_epoch" in metrics else None
                    ),
                    manifest_id=tags.get("manifest_id"),
                    manifest_hash=tags.get("manifest_hash"),
                    artifact_uri=artifact_uri,
                    params=params,
                    tags=tags,
                )
            )
        return runs

    def artifact_bytes(self, run: RunSummary, path: str) -> bytes:
        relative = run.artifact_uri.removeprefix("mlflow-artifacts:/").strip("/")
        return (self.folder / "artifacts" / relative / path).read_bytes()


def find_run(mlflow: MlflowRest | SnapshotRuns, run_id: str) -> RunSummary:
    runs = mlflow.search_runs("p3-clasificador")
    run = next((r for r in runs if r.run_id == run_id), None)
    if run is None or run.status != "FINISHED":
        raise SystemExit(f"La corrida {run_id} no esta FINISHED en p3-clasificador.")
    return run


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", required=True)
    who = parser.add_mutually_exclusive_group(required=True)
    who.add_argument("--selected", action="store_true", help="la corrida de selection.json")
    who.add_argument("--run-id", help="una corrida no seleccionada (sin metricas de test)")
    parser.add_argument("--activate", action="store_true")
    parser.add_argument("--profile")
    parser.add_argument(
        "--mlflow",
        default="snapshot",
        help="'snapshot' (mlflow_snapshot/ de DVC, por defecto) o la URL de un servidor MLflow",
    )
    parser.add_argument("--bucket", default=BUCKET)
    parser.add_argument("--prefix", default=PREFIX)
    parser.add_argument("--dry-run", action="store_true", help="solo armar el paquete")
    args = parser.parse_args()
    if not args.dry_run and not args.profile:
        raise SystemExit("Para publicar hace falta --profile (perfil de ~/.aws).")

    mlflow = (
        SnapshotRuns(PROYECTO3 / "mlflow_snapshot")
        if args.mlflow == "snapshot"
        else MlflowRest(args.mlflow)
    )
    selection_bytes = metrics = None
    if args.selected:
        selection_bytes = (PROYECTO3 / "docs" / "selection.json").read_bytes()
        run_id = json.loads(selection_bytes)["run_id"]
        metrics = json.loads(
            (PROYECTO3 / "reports" / "evaluation" / run_id / "metrics.json").read_text("utf-8")
        )
    else:
        run_id = args.run_id
    summary = find_run(mlflow, run_id)
    checkpoint = mlflow.artifact_bytes(summary, CHECKPOINT)
    run = {
        "run_id": run_id,
        "manifest_id": summary.manifest_id,
        "manifest_hash": summary.manifest_hash,
        "checkpoint_sha256": hashlib.sha256(checkpoint).hexdigest(),
        "crops_jsonl_sha256": summary.tags.get("crops_jsonl_sha256"),
        "val_accuracy": summary.best_val_accuracy,
        "best_epoch": summary.best_epoch,
    }
    classes = yaml.safe_load((PROYECTO3 / "config" / "classes.yaml").read_text("utf-8"))
    files = build_package(
        checkpoint=checkpoint,
        run=run,
        selection=selection_bytes,
        metrics=metrics,
        run_params=summary.params,
        run_tags=summary.tags,
        classes=classes["classes"],
        version=args.version,
        requirements=(PROYECTO3 / "requirements.lock.txt").read_text("utf-8"),
        created_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    out = PROYECTO3 / "data" / "models" / args.version
    out.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (out / name).write_bytes(data)
    print(f"Paquete {args.version} (run {run_id}) en {out}: {sorted(files)}")
    print(f"  SHA-256 model.pt: {run['checkpoint_sha256']}")
    if args.dry_run:
        return

    store = S3Store.from_profile(args.profile)
    publish_version(
        store,
        bucket=args.bucket,
        prefix=args.prefix,
        version=args.version,
        files=files,
        activate=args.activate,
    )
    print(json.dumps(list_versions(store, bucket=args.bucket, prefix=args.prefix), indent=2))


if __name__ == "__main__":
    main()
