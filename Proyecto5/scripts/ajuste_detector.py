"""Compara variantes de entrada del detector, solo con `p5-ajuste-v1` (B1-03).

El modelo, los umbrales y la politica no cambian. Rechaza cualquier paquete que no sea de ajuste,
reutilizando la regla de `p5.policy.ajuste`. Elige primero por seguridad, luego por costo y luego
por avance. Ver `docs/B1-03_DETECTOR.md`.
"""

import argparse
import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from p3.policy.config import cargar_config

from p5.dataset.paquete import MANIFEST_FILE, load_manifest
from p5.detector.yolox import NO_MEDIAN_FILTER, YoloxDetector, _nms
from p5.policy.ajuste import check_tuning_package, score, tune

NMS = 0.45
MIN_IOU = 0.5
FIRM = 0.50
Box = tuple[str, float, tuple[float, float, float, float]]
Filter = Callable[[np.ndarray], np.ndarray]


def gaussian(sigma: float) -> Filter:
    return lambda image: cv2.GaussianBlur(image, (0, 0), sigma)


def clahe(image: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    lab[:, :, 0] = cv2.createCLAHE(2.0, (8, 8)).apply(lab[:, :, 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def gamma(image: np.ndarray) -> np.ndarray:
    table = np.array([255 * (value / 255) ** 0.7 for value in range(256)], dtype=np.uint8)
    return cv2.LUT(image, table)


def view(
    detector: YoloxDetector,
    image: np.ndarray,
    *,
    offset: tuple[int, int] = (0, 0),
    flip_width: int | None = None,
) -> list[Box]:
    boxes = []
    for found in detector.detect_image(image):
        x1, y1, x2, y2 = found.bbox_xyxy
        if flip_width is not None:
            x1, x2 = flip_width - x2, flip_width - x1
        placed = (x1 + offset[0], y1 + offset[1], x2 + offset[0], y2 + offset[1])
        boxes.append((found.class_name, found.confidence, placed))
    return boxes


def flipped(detector: YoloxDetector, image: np.ndarray) -> list[Box]:
    return view(detector, image[:, ::-1].copy(), flip_width=image.shape[1])


def top_pad(detector: YoloxDetector, image: np.ndarray) -> list[Box]:
    pad = 40
    bordered = cv2.copyMakeBorder(image, pad, 0, 0, 0, cv2.BORDER_CONSTANT, value=(114, 114, 114))
    return view(detector, bordered, offset=(0, -pad))


def top_crop(detector: YoloxDetector, image: np.ndarray) -> list[Box]:
    return view(detector, image[: int(image.shape[0] * 0.6)].copy())


def tiles(detector: YoloxDetector, image: np.ndarray) -> list[Box]:
    height, width = int(image.shape[0] * 0.6), image.shape[1]
    size = 240
    boxes = view(detector, image)
    for start in (0, (width - size) // 2, width - size):
        boxes += view(detector, image[:height, start : start + size].copy(), offset=(start, 0))
    return boxes


def shifts(detector: YoloxDetector, image: np.ndarray) -> list[Box]:
    boxes = view(detector, image)
    for dx, dy in ((4, 0), (0, 4), (4, 4)):
        boxes += view(detector, image[dy:, dx:].copy(), offset=(dx, dy))
    return boxes


def single(image_filter: Filter | None = None) -> Callable[[YoloxDetector, np.ndarray], list[Box]]:
    def run(detector: YoloxDetector, image: np.ndarray) -> list[Box]:
        return view(detector, image_filter(image) if image_filter else image)

    return run


def with_flip(
    image_filter: Filter | None = None,
) -> Callable[[YoloxDetector, np.ndarray], list[Box]]:
    def run(detector: YoloxDetector, image: np.ndarray) -> list[Box]:
        filtered = image_filter(image) if image_filter else image
        return view(detector, filtered) + flipped(detector, filtered)

    return run


# Todas las variantes probadas, incluidas las que empeoran: (funcion, inferencias por cuadro).
VARIANTS: dict[str, tuple[Callable[[YoloxDetector, np.ndarray], list[Box]], int]] = {
    "base": (single(), 1),
    "voltear": (with_flip(), 2),
    "gauss_k3": (single(lambda image: cv2.GaussianBlur(image, (3, 3), 0)), 1),
    "gauss_0.5": (single(gaussian(0.5)), 1),
    "gauss_0.6": (single(gaussian(0.6)), 1),
    "gauss_0.8": (single(gaussian(0.8)), 1),
    "gauss_1.0": (single(gaussian(1.0)), 1),
    "gauss_1.2": (single(gaussian(1.2)), 1),
    "gauss_1.5": (single(gaussian(1.5)), 1),
    "gauss_2.0": (single(gaussian(2.0)), 1),
    "gauss_3.0": (single(gaussian(3.0)), 1),
    "bilateral": (single(lambda image: cv2.bilateralFilter(image, 5, 40, 5)), 1),
    "caja_3": (single(lambda image: cv2.blur(image, (3, 3))), 1),
    "mediana_3": (single(lambda image: cv2.medianBlur(image, 3)), 1),
    "mediana_5": (single(lambda image: cv2.medianBlur(image, 5)), 1),
    "clahe": (single(clahe), 1),
    "gamma_0.7": (single(gamma), 1),
    "borde_superior_40": (top_pad, 1),
    "recorte_superior_60": (top_crop, 1),
    "mosaico_240": (tiles, 4),
    "desplazar_4": (shifts, 4),
    "voltear_y_mosaico": (lambda d, i: tiles(d, i) + flipped(d, i), 5),
    "gauss_0.8_voltear": (with_flip(gaussian(0.8)), 2),
    "gauss_1.0_voltear": (with_flip(gaussian(1.0)), 2),
}


def merge(boxes: list[Box]) -> list[Box]:
    if not boxes:
        return []
    coordinates = np.array([box[2] for box in boxes], dtype=float)
    scores = np.array([box[1] for box in boxes], dtype=float)
    return [boxes[index] for index in _nms(coordinates, scores, NMS)]


def box_iou(first: tuple[float, ...], second: tuple[float, ...]) -> float:
    width = max(0.0, min(first[2], second[2]) - max(first[0], second[0]))
    height = max(0.0, min(first[3], second[3]) - max(first[1], second[1]))
    overlap = width * height
    union = (
        (first[2] - first[0]) * (first[3] - first[1])
        + (second[2] - second[0]) * (second[3] - second[1])
        - overlap
    )
    return overlap / max(union, 1e-9)


def firm_people(boxes: list[Box], objects: list[dict[str, Any]]) -> int:
    """Personas anotadas con una caja `person` firme encima."""
    return sum(
        any(
            name == "person" and conf >= FIRM and box_iou(box, target["bbox_xyxy"]) >= MIN_IOU
            for name, conf, box in boxes
        )
        for target in objects
        if target["class_name"] == "person"
    )


def select(results: dict[str, dict[str, Any]]) -> str:
    """Seguridad primero, luego costo de inferencia y luego avance con la via libre."""
    return min(
        results,
        key=lambda name: (
            results[name]["no_permitidas"],
            results[name]["inferencias_por_cuadro"],
            results[name]["sin_avance"],
        ),
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", type=Path, default=Path("data/p5-ajuste-v1"))
    parser.add_argument("--config", type=Path, default=Path("config/politica.yaml"))
    parser.add_argument("--weights", type=Path, default=Path("models/yolox_tiny.onnx"))
    parser.add_argument("--output", type=Path, required=True, help="Archivo JSON nuevo.")
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error(f"--output ya existe: {args.output}")
    check_tuning_package(args.dataset)

    config, config_sha256 = cargar_config(args.config)
    rows = load_manifest(args.dataset / MANIFEST_FILE)
    objects: dict[str, list[dict[str, Any]]] = {}
    for line in (args.dataset / "anotaciones.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        objects[row["frame_id"]] = row["objects"]

    detector = YoloxDetector.from_weights(args.weights, median_kernel=NO_MEDIAN_FILTER)
    images = {
        row["frame_id"]: detector.read_image(str(args.dataset / row["image"])) for row in rows
    }
    annotated = sum(
        target["class_name"] == "person" for targets in objects.values() for target in targets
    )

    results: dict[str, dict[str, Any]] = {}
    all_frames: dict[str, dict[str, dict[str, Any]]] = {}
    for name, (run, inferences) in VARIANTS.items():
        frames, firm = {}, 0
        for row in rows:
            frame_id = row["frame_id"]
            boxes = merge(run(detector, images[frame_id]))
            firm += firm_people(boxes, objects[frame_id])
            frames[frame_id] = {
                "sequence_id": row["sequence_id"],
                "frame_id": frame_id,
                "t_capture_ms": row["t_capture_ms"],
                "image_width": row["image_width"],
                "image_height": row["image_height"],
                "status": "ok",
                "error": None,
                "detections": [
                    {"class_name": label, "confidence": conf, "bbox_xyxy": list(box)}
                    for label, conf, box in boxes
                ],
            }
        all_frames[name] = frames
        outcome = score(config, rows, frames)
        results[name] = {
            "inferencias_por_cuadro": inferences,
            "no_permitidas": outcome["no_permitidas"],
            "sin_avance": outcome["sin_avance"],
            "personas_firmes": firm,
            "personas_anotadas": annotated,
            "detalle": outcome["detalle"],
        }
        print(
            f"{name:<22} no permitidas {outcome['no_permitidas']:>2}  "
            f"sin avance {outcome['sin_avance']:>2}  firmes {firm}/{annotated}  "
            f"inferencias {inferences}",
            flush=True,
        )

    chosen = select(results)
    grid = tune(rows, all_frames[chosen], config)
    report = {
        "dataset": args.dataset.as_posix(),
        "manifiesto_sha256": _sha256(args.dataset / MANIFEST_FILE),
        "modelo_sha256": _sha256(args.weights),
        "config_sha256": config_sha256,
        "criterio": "min no_permitidas, luego min inferencias por cuadro, luego min sin_avance",
        "seleccion": chosen,
        "variantes": results,
        "politica_con_la_seleccion": {
            "actual": {k: grid["actual"][k] for k in ("no_permitidas", "sin_avance")},
            "mejor_de_la_rejilla": {
                k: grid["seleccion"][k]
                for k in (
                    "umbral_bajo",
                    "cuadros_para_bloquear",
                    "cuadros_para_liberar",
                    "no_permitidas",
                    "sin_avance",
                )
            },
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as output:
        output.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"seleccion: {chosen} -> {args.output}")
    print("politica con la seleccion:", json.dumps(report["politica_con_la_seleccion"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
