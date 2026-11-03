"""Evaluacion final en test, una sola vez (F6 T15-T16, criterios 4.1-4.4).

Protocolo:

1. `selection.json` (F5) fija el candidato: sin el, o sin `run_id`,
   `checkpoint_sha256` y `manifest_hash`, no hay evaluacion.
2. El checkpoint debe tener exactamente el SHA-256 seleccionado y el manifiesto
   el `manifest_hash` seleccionado; si no, se rechaza antes de predecir nada.
3. Se predicen SOLO las filas `test` del manifiesto, con el preprocesamiento de
   evaluacion del checkpoint (`build_eval_transform`, el de val e inferencia).
4. Salida en `out_dir`: `predictions_test.csv` (una fila por recorte, las
   columnas que lee `scripts/verify_inference.py`), `metrics.json` (metricas y
   procedencia) y `errors.json` (ejemplos de aciertos y errores de test).
5. UNA sola corrida: si `out_dir` ya tiene `metrics.json` se rechaza. El modo
   `audit` recalcula todo en memoria y lo compara con lo escrito, sin tocarlo:
   la evaluacion se puede repetir para auditar, no para elegir otro modelo.

No lee el entorno ni habla con MLflow: el registro en MLflow es otro paso.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import torch
from PIL import Image

from p3.data.dataset import load_crop_index, load_manifest
from p3.data.transforms import EVAL_RESIZE, build_eval_transform
from p3.eval import metrics
from p3.model.build import load_checkpoint

THRESHOLD = 0.85
REQUIRED_SELECTION = ("run_id", "checkpoint_sha256", "manifest_hash")
PREDICTIONS = "predictions_test.csv"
METRICS = "metrics.json"
ERRORS = "errors.json"
EXAMPLES_PER_KIND = 12


class EvaluationError(RuntimeError):
    """La evaluacion no se puede correr con estos insumos."""


class EvaluationAlreadyDoneError(EvaluationError):
    """Ya existe una evaluacion final en `out_dir`; solo se permite auditarla."""


def load_selection(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise EvaluationError(
            f"No existe {path}: sin selection.json commiteado no se evalua en test."
        )
    selection = json.loads(path.read_text(encoding="utf-8"))
    missing = [field for field in REQUIRED_SELECTION if not selection.get(field)]
    if missing:
        raise EvaluationError(f"selection.json no trae {missing}: no se evalua en test.")
    return selection


def predict_test(
    model: torch.nn.Module,
    rows: Sequence[Mapping[str, Any]],
    crop_index: Mapping[str, Path],
    *,
    class_names: Sequence[str],
    image_size: int,
    batch_size: int = 32,
) -> list[dict[str, Any]]:
    """Una prediccion por fila de `test`, ordenadas por `crop_id`."""
    test_rows = sorted((r for r in rows if r["split"] == "test"), key=lambda r: r["crop_id"])
    missing = [r["crop_id"] for r in test_rows if r["crop_id"] not in crop_index]
    if missing:
        raise EvaluationError(f"{len(missing)} recortes de test sin PNG: {missing[:5]}")
    transform = build_eval_transform(image_size)
    model.eval()
    predictions: list[dict[str, Any]] = []
    with torch.no_grad():
        for start in range(0, len(test_rows), batch_size):
            batch = test_rows[start : start + batch_size]
            tensors = []
            for row in batch:
                with Image.open(crop_index[row["crop_id"]]) as handle:
                    tensors.append(transform(handle.convert("RGB")))
            probabilities = torch.softmax(model(torch.stack(tensors)), dim=1).tolist()
            for row, probs in zip(batch, probabilities, strict=True):
                by_class = dict(zip(class_names, probs, strict=True))
                predictions.append(
                    {
                        "crop_id": row["crop_id"],
                        "clase_real": row["category_name"],
                        "clase_predicha": max(by_class, key=by_class.__getitem__),
                        **{f"prob_{name}": by_class[name] for name in class_names},
                    }
                )
    return predictions


def build_report(
    predictions: Sequence[Mapping[str, Any]], class_names: Sequence[str]
) -> dict[str, Any]:
    y_true = [p["clase_real"] for p in predictions]
    y_pred = [p["clase_predicha"] for p in predictions]
    report = metrics.classification_report(y_true, y_pred, class_names)
    return {
        "test_size": report["total"],
        "accuracy": report["accuracy"],
        "passes_threshold": report["accuracy"] >= THRESHOLD,
        "threshold": THRESHOLD,
        "f1_macro": report["f1_macro"],
        "per_class": report["per_class"],
        "confusion_matrix": report["confusion_matrix"],
        "majority_baseline": metrics.majority_baseline(y_true),
        "most_confused": metrics.most_confused_pair(y_true, y_pred, class_names),
    }


def error_examples(
    predictions: Sequence[Mapping[str, Any]],
    crop_paths: Mapping[str, str],
    *,
    per_kind: int = EXAMPLES_PER_KIND,
) -> dict[str, list[dict[str, Any]]]:
    """Todos los errores (hasta `per_kind`) y aciertos repartidos, todos de test."""

    def example(p: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "crop_id": p["crop_id"],
            "crop_path": crop_paths[p["crop_id"]],
            "true": p["clase_real"],
            "predicted": p["clase_predicha"],
            "probability": p[f"prob_{p['clase_predicha']}"],
        }

    correct = [p for p in predictions if p["clase_real"] == p["clase_predicha"]]
    wrong = [p for p in predictions if p["clase_real"] != p["clase_predicha"]]
    step = max(1, len(correct) // per_kind)
    return {
        "correct": [example(p) for p in correct[::step][:per_kind]],
        "errors": [example(p) for p in wrong[:per_kind]],
    }


def predictions_csv(predictions: Sequence[Mapping[str, Any]], class_names: Sequence[str]) -> str:
    fields = ["crop_id", "clase_real", "clase_predicha", *(f"prob_{c}" for c in class_names)]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for p in predictions:
        writer.writerow({k: (repr(v) if isinstance(v, float) else v) for k, v in p.items()})
    return buffer.getvalue()


def run_evaluation(
    *,
    selection_path: Path,
    checkpoint_path: Path,
    manifest_dir: Path,
    crops_dir: Path,
    out_dir: Path,
    audit: bool = False,
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """`provenance`: datos que conoce quien llama (commit del codigo, hash de los
    recortes) y que se guardan tal cual en `metrics.json`."""
    selection = load_selection(selection_path)
    if (out_dir / METRICS).exists() and not audit:
        raise EvaluationAlreadyDoneError(
            f"Ya hay una evaluacion final en {out_dir}; el test se evalua una sola vez. "
            "Usa el modo auditoria para recalcular y comparar."
        )

    checkpoint_bytes = checkpoint_path.read_bytes()
    checkpoint_sha = hashlib.sha256(checkpoint_bytes).hexdigest()
    if checkpoint_sha != selection["checkpoint_sha256"]:
        raise EvaluationError(
            f"SHA-256 del checkpoint {checkpoint_sha} no es el seleccionado "
            f"({selection['checkpoint_sha256']})."
        )
    manifest_bytes = (manifest_dir / "manifest.jsonl").read_bytes()
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    if manifest_sha != selection["manifest_hash"]:
        raise EvaluationError(
            f"El manifiesto de {manifest_dir} tiene hash {manifest_sha}, no el de la "
            f"seleccion ({selection['manifest_hash']})."
        )

    model, meta = load_checkpoint(io.BytesIO(checkpoint_bytes))
    preprocessing = meta["preprocessing"]
    if preprocessing.get("resize", EVAL_RESIZE) != EVAL_RESIZE:
        raise EvaluationError(f"Preprocesamiento desconocido en el checkpoint: {preprocessing}")
    class_names = list(meta["class_names"])
    crop_index = load_crop_index(crops_dir)
    predictions = predict_test(
        model,
        load_manifest(manifest_dir / "manifest.jsonl"),
        crop_index,
        class_names=class_names,
        image_size=int(preprocessing["image_size"]),
    )

    report = build_report(predictions, class_names)
    csv_text = predictions_csv(predictions, class_names)
    crop_paths = {cid: path.relative_to(crops_dir).as_posix() for cid, path in crop_index.items()}
    errors = error_examples(predictions, crop_paths)

    if audit:
        return _audit(out_dir, csv_text, report)

    record = {
        **report,
        "run_id": selection["run_id"],
        "manifest_id": selection.get("manifest_id"),
        "manifest_hash": manifest_sha,
        "checkpoint_sha256": checkpoint_sha,
        "selection_sha256": hashlib.sha256(selection_path.read_bytes()).hexdigest(),
        "selected_at": selection.get("selected_at"),
        "evaluated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "predictions_sha256": hashlib.sha256(csv_text.encode("utf-8")).hexdigest(),
        **(provenance or {}),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / PREDICTIONS).write_text(csv_text, encoding="utf-8", newline="\n")
    (out_dir / ERRORS).write_text(
        json.dumps(errors, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    # metrics.json al final: su existencia marca la evaluacion como hecha.
    (out_dir / METRICS).write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    return record


def _audit(out_dir: Path, csv_text: str, report: Mapping[str, Any]) -> dict[str, Any]:
    written_csv = (out_dir / PREDICTIONS).read_text(encoding="utf-8")
    written = json.loads((out_dir / METRICS).read_text(encoding="utf-8"))
    same_predictions = written_csv == csv_text
    same_metrics = all(written.get(key) == value for key, value in report.items())
    return {
        **report,
        "audit_matches": same_predictions and same_metrics,
        "audit_same_predictions": same_predictions,
        "audit_same_metrics": same_metrics,
    }
