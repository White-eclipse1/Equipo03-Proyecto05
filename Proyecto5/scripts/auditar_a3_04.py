"""A3-04: comprobacion independiente de artefactos, sin importar el evaluador ni benchmark.

Solo biblioteca estandar. Lee el paquete congelado, nunca escribe en el.
Las laminas son auxiliares opcionales (--laminas requiere opencv/numpy del proyecto).
"""

import argparse
import csv
import hashlib
import json
import math
import subprocess
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = {
    "seq01": [1, 4, 7, 10, 13, 15],
    "seq02": [1, 6, 10, 15, 20, 24],
    "seq03": [1, 3, 5, 8, 10, 12],
    "seq04": [1, 3, 5, 8, 10, 12],
    "seq05": [1, 4, 7, 10, 13, 15],
    "seq06": [1, 26, 30, 38, 45, 50],
}
TARGETED = ["seq03-0006", "seq06-0028"]


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(directory):
    return {
        p.relative_to(directory).as_posix(): digest(p)
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    }


def indexed(rows):
    result = {row["frame_id"]: row for row in rows}
    if len(result) != len(rows):
        raise ValueError("frame_id duplicado")
    return result


def overlap(first, second):
    intersection = math.prod(
        max(0, min(first[i + 2], second[i + 2]) - max(first[i], second[i])) for i in (0, 1)
    )
    areas = [(box[2] - box[0]) * (box[3] - box[1]) for box in (first, second)]
    return intersection / (sum(areas) - intersection)


def audit_pairs(predictions, truth):
    """Recalculo pequeno de la muestra: orden de confianza, pareja unica, IoU >= .50."""
    used = set()
    pairs, unmatched = [], []
    for index in sorted(range(len(predictions)), key=lambda i: -predictions[i]["confidence"]):
        prediction = predictions[index]
        choices = [
            (overlap(prediction["bbox_xyxy"], item["bbox_xyxy"]), i)
            for i, item in enumerate(truth)
            if i not in used and item["class_name"] == prediction["class_name"]
        ]
        choices.sort(key=lambda pair: (-pair[0], pair[1]))
        value, target = choices[0] if choices else (0.0, None)
        if target is not None and value >= 0.50:
            used.add(target)
            pairs.append(
                {
                    "prediction_index": index,
                    "annotation_index": target,
                    "iou": value,
                    "prediction": prediction,
                    "ground_truth": truth[target],
                }
            )
        else:
            unmatched.append(
                {"prediction_index": index, "best_iou": value, "prediction": prediction}
            )
    missing = [i for i in range(len(truth)) if i not in used]
    return {
        "tp": len(pairs),
        "fp": len(unmatched),
        "fn": len(missing),
        "pairs": pairs,
        "unmatched_predictions": unmatched,
        "unmatched_ground_truth": [{"annotation_index": i, **truth[i]} for i in missing],
    }


def ratios(counts):
    tp, fp, fn = (counts[key] for key in ("tp", "fp", "fn"))
    return {
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "recall": tp / (tp + fn) if tp + fn else 0.0,
        "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0,
    }


def percentile(values, fraction):
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower, upper = math.floor(position), math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def compare(actual, expected, context, failures):
    if isinstance(actual, float):
        equal = math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-10)
    else:
        equal = actual == expected
    if not equal:
        failures.append({"check": context, "observed": actual, "expected": expected})


def audit_dataset(dataset, failures):
    rows = read_lines(dataset / "manifiesto.jsonl")
    by_id = indexed(rows)
    annotations = indexed(read_lines(dataset / "anotaciones.jsonl"))
    frozen = read_json(dataset / "congelamiento.json")
    compare(
        digest(dataset / "manifiesto.jsonl"), frozen["manifest_sha256"], "manifest_hash", failures
    )
    compare(set(by_id), set(annotations), "annotation_ids", failures)
    captures = []
    for path in sorted(dataset.glob("secuencias/*/capturas.jsonl")):
        captures.extend(read_lines(path))
    captured = indexed(captures)
    compare(set(by_id), set(captured), "capture_ids", failures)
    actual_images = {p.relative_to(dataset).as_posix() for p in dataset.glob("secuencias/*/*.jpg")}
    compare(actual_images, {row["image"] for row in rows}, "image_inventory", failures)
    for row in rows:
        fid = row["frame_id"]
        compare(digest(dataset / row["image"]), row["sha256"], f"image_hash:{fid}", failures)
        capture = captured[fid]
        for key in ("sha256", "sequence_id", "t_capture_ms", "image_width", "image_height"):
            compare(row[key], capture[key], f"capture:{fid}:{key}", failures)
        compare(
            row["image"],
            f"secuencias/{capture['sequence_id']}/{capture['file']}",
            f"capture_path:{fid}",
            failures,
        )
        compare(row["annotations"], annotations[fid]["objects"], f"annotations:{fid}", failures)
        compare(row["road_state"], annotations[fid]["road_state"], f"road_state:{fid}", failures)
        compare(row["split"], "evaluacion", f"split:{fid}", failures)
        for item in row["annotations"]:
            x1, y1, x2, y2 = item["bbox_xyxy"]
            compare(
                0 <= x1 < x2 <= row["image_width"] and 0 <= y1 < y2 <= row["image_height"],
                True,
                f"box_bounds:{fid}",
                failures,
            )
    counts = Counter(row["sequence_id"] for row in rows)
    compare(len(rows), frozen["frames_total"], "frozen_frame_count", failures)
    compare(len(counts), frozen["secuencias_evaluacion"], "frozen_sequence_count", failures)
    compare(
        sum(bool(row["annotations"]) for row in rows),
        frozen["con_obstaculo"],
        "frozen_obstacles",
        failures,
    )
    return rows, {
        "frames": len(rows),
        "sequences": dict(counts),
        "manifest_sha256": digest(dataset / "manifiesto.jsonl"),
        "frozen_base_commit": frozen["base_commit"],
    }


def audit_metrics(directory, rows, sample_ids, failures):
    published = read_json(directory / "metricas.json")
    primary = indexed(read_lines(directory / "resultados_por_cuadro.jsonl"))
    predictions = indexed(read_lines(directory / "predicciones.jsonl"))
    manifest = indexed(rows)
    compare(set(primary), set(manifest), "primary_ids", failures)
    compare(set(predictions), set(manifest), "prediction_ids", failures)
    compare(
        digest(directory / "predicciones.jsonl"),
        published["ejecucion"]["predicciones_sha256"],
        "prediction_hash",
        failures,
    )
    compare(
        published["ejecucion"]["manifiesto_sha256"],
        digest(ROOT / "data/p5-eval-v1/manifiesto.jsonl"),
        "metrics_manifest_hash",
        failures,
    )
    compare(published["iou_umbral"], 0.50, "iou_threshold", failures)
    compare(published["umbral_confianza"], 0.50, "confidence_threshold", failures)
    classes = published["clases_evaluadas"]
    totals = {name: {"tp": 0, "fp": 0, "fn": 0, "support": 0} for name in classes}
    for fid, frame in primary.items():
        compare(
            frame["objetos_anotados"], len(manifest[fid]["annotations"]), f"support:{fid}", failures
        )
        for field, name in (
            ("matches", "tp"),
            ("false_positives", "fp"),
            ("false_negatives", "fn"),
        ):
            compare(len(frame[field]), frame[name], f"primary_count:{fid}:{name}", failures)
            for item in frame[field]:
                totals[item["class_name"]][name] += 1
        for item in manifest[fid]["annotations"]:
            totals[item["class_name"]]["support"] += 1
    for name, counts in totals.items():
        counts.update(ratios(counts))
        for key, value in counts.items():
            compare(value, published["por_clase"][name][key], f"class:{name}:{key}", failures)
    micro = {key: sum(row[key] for row in totals.values()) for key in ("tp", "fp", "fn", "support")}
    micro.update(ratios(micro))
    for key, value in micro.items():
        compare(value, published["micro"][key], f"micro:{key}", failures)
    with (directory / "metricas.csv").open(encoding="utf-8", newline="") as source:
        csv_rows = list(csv.DictReader(source))
    compare(
        [row["clase"] for row in csv_rows], ["micro", *classes], "metrics_csv_classes", failures
    )
    for row in csv_rows:
        expected = micro if row["clase"] == "micro" else totals[row["clase"]]
        for key, value in expected.items():
            compare(float(row[key]), value, f"metrics_csv:{row['clase']}:{key}", failures)
    sample = []
    for fid in sample_ids:
        raw = predictions[fid]
        selected = [
            p for p in raw["detections"] if p["class_name"] in classes and p["confidence"] >= 0.50
        ]
        result = audit_pairs(
            selected if raw["status"] == "ok" else [], manifest[fid]["annotations"]
        )
        for key in ("tp", "fp", "fn"):
            compare(result[key], primary[fid][key], f"sample:{fid}:{key}", failures)
        # Verificar tambien parejas e IoU publicados, no solo los conteos.
        for pair, original in zip(result["pairs"], primary[fid]["matches"], strict=True):
            compare(
                pair["annotation_index"], original["annotation_index"], f"pair_gt:{fid}", failures
            )
            compare(
                pair["prediction"]["bbox_xyxy"], original["bbox_xyxy"], f"pair_pred:{fid}", failures
            )
            compare(pair["iou"], original["iou"], f"pair_iou:{fid}", failures)
        sample.append({"frame_id": fid, **result})
    return {
        "micro": micro,
        "per_class": totals,
        "sample": sample,
        "source_commit": published["ejecucion"]["commit"],
        "source_runtime": published["ejecucion"]["runtime"],
    }


def audit_benchmark(directory, manifest_sha256, failures):
    report = read_json(directory / "benchmark.json")
    with (directory / "tiempos.csv").open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    compare(digest(directory / "tiempos.csv"), report["tiempos"]["sha256"], "timing_hash", failures)
    compare(report["dataset"]["manifiesto_sha256"], manifest_sha256, "benchmark_manifest", failures)
    warmups = [row for row in rows if row["fase"] == "calentamiento"]
    measured = [row for row in rows if row["fase"] == "medicion"]
    valid = [row for row in measured if row["valido"] == "True" and not row["error"]]
    compare(len(warmups) >= 10 and len(valid) >= 100, True, "benchmark_minimums", failures)
    compare(len(rows), len(warmups) + len(measured), "timing_phases", failures)
    compare(len(rows), report["tiempos"]["filas"], "timing_rows", failures)
    compare(
        [int(row["indice"]) for row in rows], list(range(len(rows))), "timing_indices", failures
    )
    for key, value in (
        ("calentamientos", len(warmups)),
        ("mediciones", len(measured)),
        ("mediciones_validas", len(valid)),
        ("mediciones_con_error", len(measured) - len(valid)),
    ):
        compare(value, report["resumen"][key], f"benchmark:{key}", failures)
    compare(len(warmups), report["medicion"]["calentamientos"], "declared_warmups", failures)
    compare(len(measured), report["medicion"]["repeticiones"], "declared_runs", failures)
    stages = {}
    for stage, published in report["resumen"]["etapas"].items():
        values = [float(row[stage]) for row in valid]
        if not values or any(not math.isfinite(value) or value < 0 for value in values):
            raise ValueError(f"duraciones invalidas: {directory}/{stage}")
        observed = {
            "n": len(values),
            "p50": percentile(values, 0.50),
            "p95": percentile(values, 0.95),
        }
        for key, value in observed.items():
            compare(value, published[key], f"benchmark:{directory.name}:{stage}:{key}", failures)
        stages[stage] = observed
    return {
        "warmups_excluded": len(warmups),
        "valid_measurements": len(valid),
        "stages": stages,
        "source_commit": report["codigo"]["commit"],
        "source_config_sha256": report["politica"]["config_sha256"],
    }


def make_sheets(dataset, rows, output):
    import cv2
    import numpy as np

    output.mkdir()
    grouped = {}
    for row in rows:
        image = cv2.imread(str(dataset / row["image"]))
        if image is None:
            raise ValueError(f"imagen ilegible: {row['frame_id']}")
        image = cv2.resize(image, (800, 592), interpolation=cv2.INTER_NEAREST)
        for index, item in enumerate(row["annotations"]):
            x1, y1, x2, y2 = [round(value * 2) for value in item["bbox_xyxy"]]
            cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 255), 2)
            cv2.putText(
                image,
                f"GT{index} {item['class_name']}",
                (x1, max(y1 - 8, 18)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 255, 255),
                1,
            )
        tile = np.zeros((635, 800, 3), dtype=np.uint8)
        tile[:592] = image
        caption = f"{row['frame_id']} | {row['road_state']} | GT={len(row['annotations'])}"
        cv2.putText(tile, caption, (8, 620), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 1)
        grouped.setdefault(row["sequence_id"], []).append(tile)
    for sequence, tiles in grouped.items():
        if len(tiles) % 2:
            tiles.append(np.zeros_like(tiles[0]))
        sheet = np.vstack([np.hstack(tiles[i : i + 2]) for i in range(0, len(tiles), 2)])
        if not cv2.imwrite(str(output / f"{sequence}.jpg"), sheet, [cv2.IMWRITE_JPEG_QUALITY, 90]):
            raise OSError("no se pudo guardar la lamina")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, required=True, help="Carpeta nueva; nunca el dataset."
    )
    parser.add_argument("--laminas", action="store_true")
    args = parser.parse_args(argv)
    dataset = ROOT / "data/p5-eval-v1"
    if args.output.resolve().is_relative_to((ROOT / "data").resolve()):
        parser.error("la salida no puede estar dentro de data/")
    if args.output.exists():
        parser.error("la salida ya existe; usa una carpeta nueva")
    before = inventory(dataset)
    failures = []
    rows, package = audit_dataset(dataset, failures)
    ids = [
        f"{seq}-{number:04d}" for seq, numbers in SAMPLE.items() for number in numbers
    ] + TARGETED
    sample_rows = [indexed(rows)[fid] for fid in ids]
    metrics = audit_metrics(ROOT / "evidencias/a3-metricas-v1", rows, ids, failures)
    benchmarks = {
        name: audit_benchmark(ROOT / "evidencias" / name, package["manifest_sha256"], failures)
        for name in ("A3-03", "A3-03-programas-abiertos")
    }
    compare(before, inventory(dataset), "dataset_unchanged", failures)
    commit = subprocess.run(
        ["git", "-c", f"safe.directory={ROOT.parent.as_posix()}", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    artifacts = [
        ROOT / "evidencias/a3-metricas-v1" / name
        for name in (
            "metricas.json",
            "metricas.csv",
            "resultados_por_cuadro.jsonl",
            "predicciones.jsonl",
        )
    ]
    artifacts += [
        ROOT / "evidencias" / folder / name
        for folder in benchmarks
        for name in ("benchmark.json", "tiempos.csv")
    ]
    environment_findings = []
    if not metrics["source_runtime"].startswith("Python 3.12."):
        environment_findings.append(
            {
                "id": "A3-04-F01",
                "observed": metrics["source_runtime"],
                "expected": "Python >=3.12,<3.13 (pyproject.toml)",
                "action": "repetir la evaluacion en el entorno soportado sin modificar umbrales",
            }
        )
    report = {
        "audit_commit": commit,
        "audit_script_sha256": digest(Path(__file__)),
        "dataset": package,
        "dataset_inventory_sha256": before,
        "source_artifacts_sha256": {p.relative_to(ROOT).as_posix(): digest(p) for p in artifacts},
        "metrics": metrics,
        "benchmarks": benchmarks,
        "numeric_checks_pass": not failures,
        "environment_findings": environment_findings,
        "failures": failures,
        "visual_review": "ver revision_visual.csv; el script no acredita revision visual",
    }
    args.output.mkdir(parents=True)
    (args.output / "auditoria.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=lambda value: sorted(value))
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (args.output / "muestra.json").write_text(
        json.dumps(sample_rows, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    if args.laminas:
        make_sheets(dataset, sample_rows, args.output / "laminas")
    # Comprobar tambien despues de generar auxiliares.
    if before != inventory(dataset):
        raise RuntimeError("el paquete cambio durante la auditoria")
    print(
        f"38 cuadros contrastados; comprobaciones numericas: {'PASA' if not failures else 'FALLA'}"
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
