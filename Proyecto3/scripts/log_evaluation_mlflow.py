"""Registra la evaluacion final (F6) en la corrida seleccionada de MLflow (criterio 4.2).

Lee `reports/evaluation/<run_id>/` (la salida de `final_evaluation.py`, ya
commiteada) y la agrega a esa corrida, que sigue `FINISHED`:

- metricas `test_accuracy`, `test_f1_macro`, `test_majority_baseline` y, por
  clase, `test_precision_*`, `test_recall_*`, `test_f1_*`;
- tags `test_evaluated_at`, `test_code_commit`, `test_predictions_sha256`,
  `test_passes_threshold`;
- artefactos en `evaluation/`: `predictions_test.csv`, `metrics.json`, `errors.json`.

Candados: la corrida debe ser la de `selection.json`, estar marcada
`selected=true` y tener el mismo `manifest_hash`; si ya tiene `test_accuracy`,
no se vuelve a registrar.

    cd Proyecto3
    .venv/Scripts/python scripts/log_evaluation_mlflow.py [--tracking-uri http://localhost:5000]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mlflow.tracking import MlflowClient

PROYECTO3 = Path(__file__).resolve().parents[1]
ARTIFACTS = ("predictions_test.csv", "metrics.json", "errors.json")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tracking-uri", default="http://localhost:5000")
    args = parser.parse_args()

    selection = json.loads((PROYECTO3 / "docs" / "selection.json").read_text(encoding="utf-8"))
    run_id = selection["run_id"]
    folder = PROYECTO3 / "reports" / "evaluation" / run_id
    metrics = json.loads((folder / "metrics.json").read_text(encoding="utf-8"))

    client = MlflowClient(tracking_uri=args.tracking_uri)
    run = client.get_run(run_id)
    tags = run.data.tags
    if run.info.status != "FINISHED" or tags.get("selected") != "true":
        raise SystemExit(f"La corrida {run_id} no es la seleccionada FINISHED: no se registra.")
    if tags.get("manifest_hash") != metrics["manifest_hash"]:
        raise SystemExit("El manifest_hash de la corrida no es el de la evaluacion.")
    if "test_accuracy" in run.data.metrics:
        raise SystemExit(f"La corrida {run_id} ya tiene test_accuracy: la evaluacion es una sola.")

    values = {
        "test_accuracy": metrics["accuracy"],
        "test_f1_macro": metrics["f1_macro"],
        "test_majority_baseline": metrics["majority_baseline"]["accuracy"],
        "test_size": metrics["test_size"],
    }
    for row in metrics["per_class"]:
        for key in ("precision", "recall", "f1"):
            values[f"test_{key}_{row['class']}"] = row[key]
    for key, value in values.items():
        client.log_metric(run_id, key, float(value))
    for key, value in {
        "test_evaluated_at": metrics["evaluated_at"],
        "test_code_commit": metrics["code_commit"],
        "test_predictions_sha256": metrics["predictions_sha256"],
        "test_passes_threshold": str(metrics["passes_threshold"]).lower(),
    }.items():
        client.set_tag(run_id, key, value)
    for name in ARTIFACTS:
        client.log_artifact(run_id, str(folder / name), artifact_path="evaluation")

    logged = client.get_run(run_id)
    print(f"run {run_id}: status {logged.info.status}")
    print({k: v for k, v in logged.data.metrics.items() if k.startswith("test_")})
    print([a.path for a in client.list_artifacts(run_id, "evaluation")])


if __name__ == "__main__":
    main()
