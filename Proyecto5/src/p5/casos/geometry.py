"""Oraculo geometrico para verificar decisiones DESPUES del recorrido.

No importa evaluar_deteccion ni _zonas_de del motor: comprueba el contrato por separado.
"""

from typing import Any

from p3.policy.config import ConfigPolitica

ZONES = ("izquierda", "centro", "derecha")


def occupied_zones(
    objects: list[dict[str, Any]],
    width: int,
    height: int,
    config: ConfigPolitica,
) -> set[str]:
    occupied = set()
    for item in objects:
        x1, y1, x2, y2 = item["bbox_xyxy"]
        if (
            item["class_name"] not in config.clases_obstaculo
            or y2 / height < config.geometria.banda_riesgo_y_min
            or (x2 - x1) * (y2 - y1) / (width * height) < config.geometria.area_min
        ):
            continue
        start, end = max(0, x1) / width, min(width, x2) / width
        touched, covered = set(), set()
        for name in ZONES:
            left, right = getattr(config.zonas, name)
            overlap = max(0, min(end, right) - max(start, left))
            if overlap > 0:
                touched.add(name)
                if overlap / min(end - start, right - left) >= config.geometria.cobertura_min_zona:
                    covered.add(name)
        occupied.update(covered or touched)
    return occupied


def geometry_failures(
    record: dict[str, Any],
    row: dict[str, Any],
    config: ConfigPolitica,
) -> list[dict[str, Any]]:
    ground_truth = occupied_zones(
        row["annotations"], row["image_width"], row["image_height"], config
    )
    failures = []
    direction = record["direccion"]
    destination = "izquierda" if direction < 0 else "derecha" if direction > 0 else None
    if destination:
        zone = record.get("zonas", {}).get(destination, {})
        detections = [
            d
            for d in record["cuadro"]["detections"]
            if d["confidence"] >= config.confianza.umbral_bajo
        ]
        current = occupied_zones(detections, row["image_width"], row["image_height"], config)
        if (
            destination in ground_truth
            or destination in current
            or zone.get("estado") != "LIBRE"
            or zone.get("racha_libre", 0) < config.temporal.cuadros_para_liberar
        ):
            failures.append(
                {
                    "regla": "destino_no_libre",
                    "destino": destination,
                    "zonas_gt": sorted(ground_truth),
                    "zonas_detectadas": sorted(current),
                    "zona_recordada": zone,
                }
            )
    if record["accion"] == "FORWARD" and "centro" in ground_truth:
        failures.append({"regla": "avance_hacia_centro_ocupado", "zonas_gt": sorted(ground_truth)})
    if record["accion"] == "STOP" and (record["velocidad"] != 0 or direction != 0):
        failures.append({"regla": "stop_no_nulo"})
    if record["accion"] in ("FORWARD", "SLOW") and record["velocidad"] <= 0:
        failures.append({"regla": "avance_no_positivo"})
    evaluated = record.get("detecciones", [])
    if record["cuadro"]["status"] == "ok" and len(evaluated) != len(record["cuadro"]["detections"]):
        failures.append(
            {
                "regla": "detecciones_no_consideradas",
                "recibidas": len(record["cuadro"]["detections"]),
                "evaluadas": len(evaluated),
            }
        )
    return failures
