"""Muestra en que etapa del detector se pierde cada persona anotada (B1-03).

Usa el detector de produccion, sin filtro ni variantes, asi que no ajusta nada: solo describe.
Por persona anotada, compara la salida final con el puntaje crudo del modelo antes del umbral,
de la clase ganadora y de NMS. Ver `docs/B1-03_DETECTOR.md`.
"""

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from p5.dataset.paquete import MANIFEST_FILE, load_manifest
from p5.detector.coco_classes import COCO_CLASSES
from p5.detector.yolox import DEFAULT_SCORE_THRESHOLD, YoloxDetector, _decode

PERSON = COCO_CLASSES.index("person")
MIN_IOU = 0.5
FIRM = 0.50  # umbral_alto de la politica.
WEAK = 0.30  # umbral_bajo de la politica.


def iou(boxes: np.ndarray, box: np.ndarray) -> np.ndarray:
    width = np.maximum(0.0, np.minimum(boxes[:, 2], box[2]) - np.maximum(boxes[:, 0], box[0]))
    height = np.maximum(0.0, np.minimum(boxes[:, 3], box[3]) - np.maximum(boxes[:, 1], box[1]))
    intersection = width * height
    areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    area = (box[2] - box[0]) * (box[3] - box[1])
    return intersection / np.maximum(areas + area - intersection, 1e-9)


def classify(final_score: float, raw_score: float) -> str:
    """Etapa que explica la salida para una persona anotada."""
    if final_score >= FIRM:
        return "firme"
    if final_score >= WEAK:
        return "debil"
    if final_score > 0.0:
        return "bajo_umbral_bajo"
    if raw_score > DEFAULT_SCORE_THRESHOLD:
        return "perdida_por_clase_o_nms"
    return "sin_evidencia_del_modelo"


def inspect_frame(
    detector: YoloxDetector, image: np.ndarray, source: str
) -> tuple[list, np.ndarray]:
    tensor, ratio = detector._preprocess(image, source)
    raw = detector._infer(tensor, source)
    detections = detector._postprocess(raw, ratio, image.shape[:2], source)
    decoded = _decode(raw[0], detector._input_size)
    centers, sizes = decoded[:, :2], decoded[:, 2:4]
    boxes = np.concatenate((centers - sizes / 2, centers + sizes / 2), axis=1) / ratio
    scores = decoded[:, 4] * decoded[:, 5 + PERSON]
    return list(detections), np.column_stack((boxes, scores))


def row_for_object(frame_id: str, target: list[float], detections: list, cells: np.ndarray) -> dict:
    box = np.array(target, dtype=float)
    people = [d for d in detections if d.class_name == "person"]
    final_scores = [
        d.confidence for d in people if iou(np.array([d.bbox_xyxy], dtype=float), box)[0] >= MIN_IOU
    ]
    overlapping = iou(cells[:, :4], box) >= MIN_IOU
    raw_score = float(cells[overlapping, 4].max()) if overlapping.any() else 0.0
    final_score = max(final_scores, default=0.0)
    return {
        "frame_id": frame_id,
        "caja_anotada": target,
        "confianza_final": round(final_score, 3),
        "puntaje_crudo": round(raw_score, 3),
        "etapa": classify(final_score, raw_score),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--sequences", required=True, help="Separadas por coma.")
    parser.add_argument("--weights", type=Path, default=Path("models/yolox_tiny.onnx"))
    parser.add_argument("--output", type=Path, required=True, help="Archivo JSONL nuevo.")
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error(f"--output ya existe: {args.output}")

    wanted = set(args.sequences.split(","))
    annotations: dict[str, Any] = {}
    for line in (args.dataset / "anotaciones.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        annotations[row["frame_id"]] = row["objects"]

    detector = YoloxDetector.from_weights(args.weights)
    results = []
    for row in load_manifest(args.dataset / MANIFEST_FILE):
        if row["sequence_id"] not in wanted:
            continue
        image = detector.read_image(str(args.dataset / row["image"]))
        detections, cells = inspect_frame(detector, image, row["image"])
        for target in annotations[row["frame_id"]]:
            if target["class_name"] == "person":
                results.append(
                    row_for_object(row["frame_id"], target["bbox_xyxy"], detections, cells)
                )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as lines:
        for result in results:
            lines.write(json.dumps(result, ensure_ascii=False) + "\n")
    print(dict(Counter(result["etapa"] for result in results)), "->", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
