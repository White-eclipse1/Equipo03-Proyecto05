"""Une capturas, anotaciones y separacion en un manifiesto validado y congelable (E3)."""

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from typing import Any

from p5.dataset.captura import CAPTURES_FILE, SEQUENCES_DIR, jpeg_size

ANNOTATIONS_FILE = "anotaciones.jsonl"
SEQUENCES_FILE = "secuencias.json"
MANIFEST_FILE = "manifiesto.jsonl"
FREEZE_FILE = "congelamiento.json"

SPLIT_EVALUATION = "evaluacion"
SPLIT_TUNING = "ajuste"
SPLITS = (SPLIT_EVALUATION, SPLIT_TUNING)

MIN_SEQUENCES = 6
MIN_FRAMES = 60
MIN_OBSTACLE_FRAMES = 20
MIN_CLEAR_FRAMES = 20
REQUIRED_SCENARIOS = frozenset({"C1", "C2", "C3", "C4", "C5", "C7"})

# Las clases obstaculo de Proyecto3/config/politica.yaml.
OBSTACLE_CLASSES = ("person", "bicycle", "car", "motorcycle", "bus", "truck", "cat", "dog")

# Mismas zonas y cobertura que la politica; si cambian alla, cambian aqui.
ZONES = {"izquierda": (0.0, 0.35), "centro": (0.35, 0.65), "derecha": (0.65, 1.0)}
MIN_ZONE_COVERAGE = 0.15

# Acciones admisibles por estado de la via. SLOW y STOP cubren las transiciones de la politica
# (confirmar o liberar una zona tarda varios cuadros); los casos C1-C7 acotan cuando aplican.
ALLOWED_ACTIONS = {
    "libre": ("FORWARD", "SLOW", "STOP"),
    "lateral_izquierda": ("FORWARD", "SLOW", "STOP"),
    "lateral_derecha": ("FORWARD", "SLOW", "STOP"),
    "centro": ("STOP", "SLOW", "EVADE_LEFT", "EVADE_RIGHT"),
    "varios": ("STOP", "SLOW", "EVADE_LEFT", "EVADE_RIGHT"),
}


def occupied_zones(box: list[float], image_width: int) -> set[str]:
    """Zonas que ocupa una caja, con la regla de solape de la politica."""
    left, right = box[0] / image_width, box[2] / image_width
    zones = set()
    for name, (start, end) in ZONES.items():
        overlap = min(right, end) - max(left, start)
        if overlap > 0 and overlap >= MIN_ZONE_COVERAGE * min(end - start, right - left):
            zones.add(name)
    return zones


def annotation_errors(
    road_state: object, objects: object, image_width: int, image_height: int
) -> list[str]:
    """Revisa una anotacion: formato de cajas y coherencia entre geometria y estado de la via."""
    if road_state not in ALLOWED_ACTIONS:
        return [f"road_state desconocido: {road_state!r}"]
    if not isinstance(objects, list):
        return ["objects debe ser una lista explicita, vacia si no hay objetos"]

    errors = []
    zones: set[str] = set()
    for index, item in enumerate(objects):
        where = f"objects[{index}]"
        if not isinstance(item, dict) or set(item) != {"class_name", "bbox_xyxy"}:
            errors.append(f"{where}: se esperan class_name y bbox_xyxy")
            continue
        if item["class_name"] not in OBSTACLE_CLASSES:
            errors.append(f"{where}: clase fuera de las evaluadas: {item['class_name']!r}")
        box = item["bbox_xyxy"]
        if (
            not isinstance(box, list)
            or len(box) != 4
            or not all(isinstance(v, int | float) and isfinite(v) for v in box)
        ):
            errors.append(f"{where}: bbox_xyxy debe tener 4 numeros finitos")
            continue
        x1, y1, x2, y2 = box
        if not (x2 > x1 and y2 > y1):
            errors.append(f"{where}: caja sin ancho o sin alto")
        elif x1 < 0 or y1 < 0 or x2 > image_width or y2 > image_height:
            errors.append(f"{where}: caja fuera de la imagen")
        else:
            zones |= occupied_zones(box, image_width)
    if errors:
        return errors

    if road_state == "libre":
        if objects:
            errors.append("libre no admite objetos")
    elif not objects:
        errors.append(f"{road_state} exige al menos un objeto")
    elif road_state == "centro" and "centro" not in zones:
        errors.append(f"centro exige una caja en el centro; ocupa {sorted(zones)}")
    elif road_state == "lateral_izquierda" and zones != {"izquierda"}:
        errors.append(f"lateral_izquierda exige solo izquierda; ocupa {sorted(zones)}")
    elif road_state == "lateral_derecha" and zones != {"derecha"}:
        errors.append(f"lateral_derecha exige solo derecha; ocupa {sorted(zones)}")
    elif road_state == "varios" and (len(objects) < 2 or len(zones) < 2 or "centro" not in zones):
        errors.append(f"varios exige 2+ objetos, con el centro y otra zona; ocupa {sorted(zones)}")
    return errors


def load_captures(dataset: Path) -> list[dict[str, Any]]:
    """Lee los capturas.jsonl de todas las secuencias, ordenados por secuencia."""
    records = []
    for path in sorted((dataset / SEQUENCES_DIR).glob(f"*/{CAPTURES_FILE}")):
        with path.open(encoding="utf-8") as lines:
            records.extend(json.loads(line) for line in lines if line.strip())
    return records


def load_annotations(dataset: Path) -> dict[str, dict[str, Any]]:
    path = dataset / ANNOTATIONS_FILE
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as lines:
        rows = [json.loads(line) for line in lines if line.strip()]
    return {row["frame_id"]: row for row in rows}


def load_manifest(path: Path) -> list[dict[str, Any]]:
    """Carga un manifiesto. Las etiquetas son para evaluar: el detector solo debe usar `image`."""
    with path.open(encoding="utf-8") as lines:
        return [json.loads(line) for line in lines if line.strip()]


def serialize_manifest(rows: list[dict[str, Any]]) -> bytes:
    lines = (json.dumps(row, sort_keys=True, ensure_ascii=True) for row in rows)
    return "".join(f"{line}\n" for line in lines).encode("ascii")


@dataclass
class Report:
    rows: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        evaluation = [row for row in self.rows if row["split"] == SPLIT_EVALUATION]
        return {
            "frames_total": len(self.rows),
            "frames_evaluacion": len(evaluation),
            "frames_ajuste": len(self.rows) - len(evaluation),
            "secuencias_evaluacion": len({row["sequence_id"] for row in evaluation}),
            "con_obstaculo": sum(1 for row in evaluation if row["annotations"]),
            "despejados": sum(1 for row in evaluation if not row["annotations"]),
            "escenarios": sorted({row["scenario"] for row in evaluation}),
            "errores": len(self.errors),
        }


def build_report(dataset: Path) -> Report:
    """Arma las filas del manifiesto y acumula todos los errores, sin parar en el primero."""
    report = Report()
    errors = report.errors

    path = dataset / SEQUENCES_FILE
    sequences = json.loads(path.read_text(encoding="utf-8")).get("sequences", {})
    annotations = load_annotations(dataset)
    captures = load_captures(dataset)

    captured_ids = {record["sequence_id"] for record in captures}
    for sequence_id in sorted(captured_ids - set(sequences)):
        errors.append(f"{sequence_id}: no esta declarada en {SEQUENCES_FILE}")
    for sequence_id in sorted(set(sequences) - captured_ids):
        errors.append(f"{sequence_id}: declarada en {SEQUENCES_FILE} pero sin cuadros")
    for sequence_id, info in sequences.items():
        if info.get("split") not in SPLITS:
            errors.append(f"{sequence_id}: split debe ser uno de {SPLITS}")

    seen_frames: set[str] = set()
    seen_hashes: dict[str, str] = {}
    last_time: dict[str, int] = {}
    for record in captures:
        sequence_id, frame_id = record["sequence_id"], record["frame_id"]
        image = dataset / SEQUENCES_DIR / sequence_id / record["file"]

        if frame_id in seen_frames:
            errors.append(f"{frame_id}: frame_id repetido")
        seen_frames.add(frame_id)

        if not image.is_file():
            errors.append(f"{frame_id}: no existe {image.as_posix()}")
            continue
        data = image.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != record["sha256"]:
            errors.append(f"{frame_id}: el SHA-256 no coincide con la captura")
        if digest in seen_hashes:
            errors.append(f"{frame_id}: imagen identica a {seen_hashes[digest]}")
        seen_hashes.setdefault(digest, frame_id)
        if jpeg_size(data) != (record["image_width"], record["image_height"]):
            errors.append(f"{frame_id}: JPEG invalido o con otras dimensiones")

        if sequence_id in last_time and record["t_capture_ms"] <= last_time[sequence_id]:
            errors.append(f"{frame_id}: t_capture_ms no crece dentro de la secuencia")
        last_time[sequence_id] = record["t_capture_ms"]

        annotation = annotations.get(frame_id)
        if annotation is None:
            errors.append(f"{frame_id}: sin anotacion")
            continue
        road_state, objects = annotation.get("road_state"), annotation.get("objects")
        problems = annotation_errors(
            road_state, objects, record["image_width"], record["image_height"]
        )
        errors.extend(f"{frame_id}: {problem}" for problem in problems)
        if problems or sequence_id not in sequences:
            continue

        info = sequences[sequence_id]
        report.rows.append(
            {
                "sequence_id": sequence_id,
                "frame_id": frame_id,
                "split": info.get("split"),
                "scenario": info.get("scenario"),
                "image": f"{SEQUENCES_DIR}/{sequence_id}/{record['file']}",
                "sha256": digest,
                "t_capture_ms": record["t_capture_ms"],
                "image_width": record["image_width"],
                "image_height": record["image_height"],
                "road_state": road_state,
                "annotations": objects,
                "allowed_actions": list(ALLOWED_ACTIONS[road_state]),
            }
        )

    for frame_id in sorted(set(annotations) - seen_frames):
        errors.append(f"{frame_id}: anotacion sin cuadro capturado")

    summary = report.summary()
    if summary["secuencias_evaluacion"] < MIN_SEQUENCES:
        errors.append(f"evaluacion: {summary['secuencias_evaluacion']}/{MIN_SEQUENCES} secuencias")
    if summary["frames_evaluacion"] < MIN_FRAMES:
        errors.append(f"evaluacion: {summary['frames_evaluacion']}/{MIN_FRAMES} cuadros")
    if summary["con_obstaculo"] < MIN_OBSTACLE_FRAMES:
        errors.append(
            f"evaluacion: {summary['con_obstaculo']}/{MIN_OBSTACLE_FRAMES} cuadros con obstaculo"
        )
    if summary["despejados"] < MIN_CLEAR_FRAMES:
        errors.append(f"evaluacion: {summary['despejados']}/{MIN_CLEAR_FRAMES} cuadros despejados")
    missing = REQUIRED_SCENARIOS - set(summary["escenarios"])
    if missing:
        errors.append(f"evaluacion: faltan escenarios {sorted(missing)}")
    return report


def freeze(dataset: Path, version: str, *, commit: str | None = None) -> dict[str, Any]:
    """Escribe el manifiesto y registra su hash. Un cambio posterior exige otra version."""
    report = build_report(dataset)
    if report.errors:
        raise ValueError(f"el paquete tiene {len(report.errors)} errores")

    content = serialize_manifest(report.rows)
    digest = hashlib.sha256(content).hexdigest()
    freeze_path = dataset / FREEZE_FILE
    if freeze_path.exists():
        previous = json.loads(freeze_path.read_text(encoding="utf-8"))
        if previous["manifest_sha256"] != digest:
            raise ValueError(
                f"{previous['version']} ya esta congelada con otro contenido: "
                "crea un dataset con una version nueva"
            )
        return previous

    (dataset / MANIFEST_FILE).write_bytes(content)
    record = {
        "version": version,
        "manifest_sha256": digest,
        "frozen_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "base_commit": commit,
        **report.summary(),
    }
    freeze_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return record


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
        prog="python -m p5.dataset.paquete",
        description="Valida el dataset de P5 o congela su manifiesto.",
    )
    parser.add_argument("command", choices=("validate", "freeze"))
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--version", help="Version a registrar. Obligatoria con freeze.")
    args = parser.parse_args(argv)

    if args.command == "freeze" and not args.version:
        parser.error("freeze requires --version")

    try:
        report = build_report(args.dataset)
        for error in report.errors:
            print(f"ERROR {error}", file=sys.stderr)
        if args.command == "validate":
            print(json.dumps(report.summary(), indent=2, ensure_ascii=False))
            return 1 if report.errors else 0
        record = freeze(args.dataset, args.version, commit=_current_commit())
    except (OSError, ValueError, KeyError) as error:
        print(f"paquete invalido: {error}", file=sys.stderr)
        return 1

    print(json.dumps(record, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
