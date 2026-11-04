"""Metricas de deteccion: emparejamiento con IoU 0.50, TP/FP/FN, precision, recall y F1.

Logica pura: recibe etiquetas y detecciones ya calculadas. Ver `docs/A3_METRICAS.md`.
"""

from math import isfinite
from typing import Any

from p5.dataset.paquete import OBSTACLE_CLASSES

IOU_THRESHOLD = 0.50
# Fijado antes de medir: es `umbral_alto` de la politica, el que vuelve firme una deteccion.
SCORE_THRESHOLD = 0.50
EVALUATED_CLASSES = OBSTACLE_CLASSES
EVALUATION_SPLIT = "evaluacion"


def iou(a: list[float], b: list[float]) -> float:
    """Interseccion sobre union de dos cajas `xyxy`. Sin area comun, 0."""
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    if width <= 0 or height <= 0:
        return 0.0
    intersection = width * height
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return intersection / (area_a + area_b - intersection)


def score(tp: int, fp: int, fn: int) -> dict[str, float]:
    """Precision, recall y F1. Un denominador en cero da 0."""
    return {
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "recall": tp / (tp + fn) if tp + fn else 0.0,
        "f1": 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else 0.0,
    }


def match_frame(
    predictions: list[dict[str, Any]],
    annotations: list[dict[str, Any]],
    *,
    iou_threshold: float = IOU_THRESHOLD,
) -> dict[str, list[dict[str, Any]]]:
    """Empareja un cuadro, clase por clase, de la prediccion mas confiable a la menos.

    Cada prediccion toma la caja real libre de mayor IoU de su clase. Una caja real solo se
    usa una vez: una prediccion duplicada es FP, y una caja real sin pareja es FN. Una clase
    equivocada produce un FP y un FN, porque las clases no se cruzan.
    """
    matches: list[dict[str, Any]] = []
    false_positives: list[dict[str, Any]] = []
    free = dict(enumerate(annotations))

    # `sorted` es estable: con la misma confianza se conserva el orden del detector.
    for prediction in sorted(predictions, key=lambda item: -item["confidence"]):
        candidates = [
            (iou(prediction["bbox_xyxy"], annotation["bbox_xyxy"]), index)
            for index, annotation in free.items()
            if annotation["class_name"] == prediction["class_name"]
        ]
        # Con el mismo IoU gana la primera caja real: mayor IoU y, si empatan, menor indice.
        best_iou, best_index = max(candidates, key=lambda c: (c[0], -c[1]), default=(0.0, None))
        if best_index is not None and best_iou >= iou_threshold:
            del free[best_index]
            matches.append({**prediction, "annotation_index": best_index, "iou": best_iou})
        else:
            false_positives.append({**prediction, "best_iou": best_iou})

    false_negatives = [
        {**annotation, "annotation_index": index} for index, annotation in free.items()
    ]
    return {
        "matches": matches,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
    }


def _check_detection(frame_id: str, detection: dict[str, Any]) -> None:
    values = [detection["confidence"], *detection["bbox_xyxy"]]
    if not all(isinstance(value, int | float) and isfinite(value) for value in values):
        raise ValueError(f"{frame_id}: deteccion con valores no finitos: {detection}")


def _select(
    frame_id: str, detections: list[dict[str, Any]], score_threshold: float
) -> tuple[list[dict[str, Any]], int, dict[str, int]]:
    """Detecciones que se evaluan, cuantas quedan bajo el umbral y cuantas son de otra clase."""
    selected = []
    below_threshold = 0
    other_classes: dict[str, int] = {}
    for detection in detections:
        _check_detection(frame_id, detection)
        if detection["class_name"] not in EVALUATED_CLASSES:
            name = detection["class_name"]
            other_classes[name] = other_classes.get(name, 0) + 1
        elif detection["confidence"] < score_threshold:
            below_threshold += 1
        else:
            selected.append(detection)
    return selected, below_threshold, other_classes


def evaluate(
    rows: list[dict[str, Any]],
    perceptions: dict[str, dict[str, Any]],
    *,
    score_threshold: float = SCORE_THRESHOLD,
    iou_threshold: float = IOU_THRESHOLD,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Evalua todos los cuadros de `evaluacion`. Devuelve los resultados por cuadro y los totales.

    Exige una percepcion por cada cuadro, y ninguna de mas. Un cuadro con error sigue contando:
    sin prediccion, sus objetos anotados son FN.
    """
    evaluated = [row for row in rows if row["split"] == EVALUATION_SPLIT]
    if not evaluated:
        raise ValueError(f"el manifiesto no tiene cuadros de {EVALUATION_SPLIT}")
    expected = {row["frame_id"] for row in evaluated}
    missing = sorted(expected - set(perceptions))
    if missing:
        raise ValueError(f"faltan predicciones de {len(missing)} cuadros: {missing[:5]}")
    unknown = sorted(set(perceptions) - expected)
    if unknown:
        raise ValueError(f"predicciones de cuadros fuera de {EVALUATION_SPLIT}: {unknown[:5]}")

    frames = []
    totals = {name: {"support": 0, "tp": 0, "fp": 0, "fn": 0} for name in EVALUATED_CLASSES}
    below_threshold = 0
    other_classes: dict[str, int] = {}
    with_errors = []

    for row in evaluated:
        frame_id = row["frame_id"]
        perception = perceptions[frame_id]
        failed = perception["status"] != "ok"
        selected, below, others = _select(
            frame_id, [] if failed else perception["detections"], score_threshold
        )
        below_threshold += below
        for name, count in others.items():
            other_classes[name] = other_classes.get(name, 0) + count
        if failed:
            with_errors.append({"frame_id": frame_id, "error": perception.get("error")})

        result = match_frame(selected, row["annotations"], iou_threshold=iou_threshold)
        for annotation in row["annotations"]:
            totals[annotation["class_name"]]["support"] += 1
        for key, items in (
            ("tp", result["matches"]),
            ("fp", result["false_positives"]),
            ("fn", result["false_negatives"]),
        ):
            for item in items:
                totals[item["class_name"]][key] += 1

        frames.append(
            {
                "sequence_id": row["sequence_id"],
                "frame_id": frame_id,
                "status": perception["status"],
                "error": perception.get("error"),
                "objetos_anotados": len(row["annotations"]),
                "tp": len(result["matches"]),
                "fp": len(result["false_positives"]),
                "fn": len(result["false_negatives"]),
                "bajo_umbral": below,
                "otras_clases": others,
                **result,
            }
        )

    micro = {
        key: sum(item[key] for item in totals.values()) for key in ("support", "tp", "fp", "fn")
    }
    metrics = {
        "iou_umbral": iou_threshold,
        "umbral_confianza": score_threshold,
        "clases_evaluadas": list(EVALUATED_CLASSES),
        "cuadros": len(evaluated),
        "cuadros_con_objetos": sum(bool(row["annotations"]) for row in evaluated),
        "cuadros_negativos": sum(not row["annotations"] for row in evaluated),
        "cuadros_con_error": with_errors,
        "micro": {**micro, **score(micro["tp"], micro["fp"], micro["fn"])},
        "por_clase": {
            name: {**item, **score(item["tp"], item["fp"], item["fn"])}
            for name, item in totals.items()
        },
        "clases_sin_soporte": [name for name, item in totals.items() if not item["support"]],
        "detecciones_bajo_umbral": below_threshold,
        "detecciones_de_otras_clases": dict(sorted(other_classes.items())),
    }
    return frames, metrics
