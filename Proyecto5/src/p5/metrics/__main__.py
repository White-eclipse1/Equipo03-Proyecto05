"""Calcula las metricas de deteccion de un paquete congelado y guarda la evidencia."""

import argparse
import csv
import hashlib
import json
import logging
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from p5.dataset.paquete import MANIFEST_FILE, load_manifest
from p5.detector.frame import detect_frame
from p5.detector.yolox import (
    DEFAULT_MEDIAN_KERNEL,
    DEFAULT_NMS_THRESHOLD,
    DEFAULT_SCORE_THRESHOLD,
    DetectorError,
    YoloxDetector,
)
from p5.metrics.detection import EVALUATION_SPLIT, SCORE_THRESHOLD, evaluate

PREDICTIONS_FILE = "predicciones.jsonl"
FRAMES_FILE = "resultados_por_cuadro.jsonl"
METRICS_FILE = "metricas.json"
CSV_FILE = "metricas.csv"
_CSV_COLUMNS = ("clase", "support", "tp", "fp", "fn", "precision", "recall", "f1")


def load_detector(weights: Path) -> YoloxDetector:
    return YoloxDetector.from_weights(weights)


def detect_rows(
    detector: YoloxDetector, rows: list[dict[str, Any]], dataset: Path
) -> dict[str, dict[str, Any]]:
    """Corre el detector cuadro por cuadro. Solo recibe la imagen, nunca las etiquetas."""
    perceptions = {}
    for row in rows:
        frame_id = row["frame_id"]
        try:
            perceptions[frame_id] = detect_frame(
                detector,
                dataset / row["image"],
                sequence_id=row["sequence_id"],
                frame_id=frame_id,
                t_capture_ms=row["t_capture_ms"],
                image_size=(row["image_width"], row["image_height"]),
            ).to_dict()
        except Exception as failure:
            # Sin prediccion, los objetos anotados de este cuadro cuentan como FN.
            perceptions[frame_id] = {
                "sequence_id": row["sequence_id"],
                "frame_id": frame_id,
                "status": "error",
                "detections": [],
                "error": str(failure) or type(failure).__name__,
            }
    return perceptions


def read_predictions(path: Path) -> dict[str, dict[str, Any]]:
    perceptions: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        perception = json.loads(line)
        frame_id = perception["frame_id"]
        if frame_id in perceptions:
            raise ValueError(f"{frame_id}: prediccion repetida")
        perceptions[frame_id] = perception
    return perceptions


def _write_jsonl(path: Path, items: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as lines:
        for item in items:
            lines.write(json.dumps(item, ensure_ascii=False, allow_nan=False) + "\n")


def _write_csv(path: Path, metrics: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(_CSV_COLUMNS)
        for name, item in [("micro", metrics["micro"]), *metrics["por_clase"].items()]:
            writer.writerow([name, *(item[column] for column in _CSV_COLUMNS[1:])])


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _current_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m p5.metrics",
        description="Calcula TP, FP, FN, precision, recall y F1 de un paquete congelado.",
    )
    parser.add_argument("--dataset", required=True, type=Path, help="Paquete de evaluacion.")
    parser.add_argument("--output", required=True, type=Path, help="Carpeta nueva.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--weights", type=Path, help="Corre el detector con estos pesos.")
    source.add_argument(
        "--predictions", type=Path, help=f"Recalcula desde un {PREDICTIONS_FILE} ya guardado."
    )
    parser.add_argument(
        "--score-threshold",
        type=float,
        default=SCORE_THRESHOLD,
        help="Fijado antes de medir. Cambiarlo despues de ver resultados invalida la evaluacion.",
    )
    args = parser.parse_args(argv)

    if args.output.exists():
        parser.error(f"--output ya existe: {args.output}")

    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

    manifest = args.dataset / MANIFEST_FILE
    try:
        rows = load_manifest(manifest)
        evaluated = [row for row in rows if row["split"] == EVALUATION_SPLIT]
        if args.predictions is not None:
            perceptions = read_predictions(args.predictions)
        else:
            perceptions = detect_rows(load_detector(args.weights), evaluated, args.dataset)
        frames, metrics = evaluate(rows, perceptions, score_threshold=args.score_threshold)
    except (DetectorError, OSError, ValueError, KeyError) as error:
        print(f"no se pudieron calcular las metricas: {error!r}", file=sys.stderr)
        return 1

    args.output.mkdir(parents=True)
    predictions_path = args.output / PREDICTIONS_FILE
    _write_jsonl(predictions_path, [perceptions[row["frame_id"]] for row in evaluated])
    _write_jsonl(args.output / FRAMES_FILE, frames)
    _write_csv(args.output / CSV_FILE, metrics)
    metrics["ejecucion"] = {
        "run_id": uuid4().hex,
        "fecha": datetime.now(UTC).isoformat(timespec="seconds"),
        "commit": _current_commit(),
        "origen": "predicciones guardadas" if args.predictions else "detector",
        "modelo_sha256": _sha256(args.weights) if args.weights else None,
        "manifiesto_sha256": _sha256(manifest),
        "predicciones_sha256": _sha256(predictions_path),
        "umbral_detector": DEFAULT_SCORE_THRESHOLD,
        "nms_detector": DEFAULT_NMS_THRESHOLD,
        "filtro_mediana_detector": DEFAULT_MEDIAN_KERNEL if args.weights else None,
        "runtime": f"Python {platform.python_version()}",
        "hardware": f"{platform.system()} {platform.machine()}, CPU",
    }
    (args.output / METRICS_FILE).write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    micro = metrics["micro"]
    print(
        f"cuadros={metrics['cuadros']} tp={micro['tp']} fp={micro['fp']} fn={micro['fn']} "
        f"precision={micro['precision']:.4f} recall={micro['recall']:.4f} f1={micro['f1']:.4f} "
        f"errores={len(metrics['cuadros_con_error'])} output={args.output}"
    )
    return 1 if metrics["cuadros_con_error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
