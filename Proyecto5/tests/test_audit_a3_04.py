"""La auditoria es independiente y debe detectar alteraciones en artefactos publicados."""

import ast
import csv
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/auditar_a3_04.py"
SPEC = importlib.util.spec_from_file_location("audit_a3_04", SCRIPT)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def test_audit_does_not_import_the_implementation_it_audits():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    imports += [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ]
    assert not any(name.startswith(("p5", "p3", "numpy.percentile")) for name in imports)


def test_one_to_one_matching_rejects_duplicate_and_wrong_class_predictions():
    truth = [{"class_name": "person", "bbox_xyxy": [0, 0, 10, 10]}]
    predictions = [
        {"class_name": name, "confidence": confidence, "bbox_xyxy": [0, 0, 10, 10]}
        for name, confidence in [("person", 0.9), ("person", 0.8), ("dog", 0.7)]
    ]
    result = audit.audit_pairs(predictions, truth)
    assert (result["tp"], result["fp"], result["fn"]) == (1, 2, 0)
    assert result["pairs"][0]["prediction_index"] == 0


def test_exact_iou_boundary_counts_as_a_match():
    prediction = {"class_name": "person", "confidence": 0.9, "bbox_xyxy": [0, 0, 5, 10]}
    truth = [{"class_name": "person", "bbox_xyxy": [0, 0, 10, 10]}]
    assert audit.audit_pairs([prediction], truth)["tp"] == 1
    prediction["bbox_xyxy"][2] = 4.99
    result = audit.audit_pairs([prediction], truth)
    assert (result["tp"], result["fp"], result["fn"]) == (0, 1, 1)


def test_frozen_image_tampering_is_detected(tmp_path):
    dataset = tmp_path / "dataset"
    shutil.copytree(ROOT / "data/p5-eval-v1", dataset)
    image = dataset / "secuencias/seq01/seq01-0001.jpg"
    image.write_bytes(image.read_bytes() + b"changed")
    failures = []
    audit.audit_dataset(dataset, failures)
    assert any(f["check"] == "image_hash:seq01-0001" for f in failures)


def test_modified_metrics_are_detected(tmp_path):
    source = tmp_path / "metrics"
    shutil.copytree(ROOT / "evidencias/a3-metricas-v1", source)
    path = source / "metricas.json"
    report = audit.read_json(path)
    report["micro"]["f1"] = 1.0
    path.write_text(json.dumps(report), encoding="utf-8")
    failures = []
    rows = audit.read_lines(ROOT / "data/p5-eval-v1/manifiesto.jsonl")
    audit.audit_metrics(source, rows, ["seq03-0006", "seq06-0028"], failures)
    assert any(f["check"] == "micro:f1" for f in failures)


@pytest.mark.parametrize("valid_count", [100, 99])
def test_benchmark_excludes_warmups_and_requires_100_valid_runs(tmp_path, valid_count):
    rows = [
        {"fase": "calentamiento", "indice": i, "valido": "True", "error": "", "ms_total": 10000}
        for i in range(10)
    ]
    rows += [
        {"fase": "medicion", "indice": i + 9, "valido": "True", "error": "", "ms_total": i}
        for i in range(1, valid_count + 1)
    ]
    csv_path = tmp_path / "tiempos.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    report = {
        "tiempos": {"sha256": audit.digest(csv_path), "filas": len(rows)},
        "dataset": {"manifiesto_sha256": "manifest"},
        "medicion": {"calentamientos": 10, "repeticiones": valid_count},
        "resumen": {
            "calentamientos": 10,
            "mediciones": valid_count,
            "mediciones_validas": valid_count,
            "mediciones_con_error": 0,
            "etapas": {
                "ms_total": {
                    "n": valid_count,
                    "p50": (valid_count + 1) / 2,
                    "p95": 1 + (valid_count - 1) * 0.95,
                }
            },
        },
        "codigo": {"commit": "test"},
        "politica": {"config_sha256": "config"},
    }
    (tmp_path / "benchmark.json").write_text(json.dumps(report), encoding="utf-8")
    failures = []
    result = audit.audit_benchmark(tmp_path, "manifest", failures)
    assert result["stages"]["ms_total"]["p50"] < 100
    assert bool(failures) == (valid_count < 100)


def test_full_independent_audit_matches_published_evidence_without_writing_dataset(tmp_path):
    dataset = ROOT / "data/p5-eval-v1"
    before = audit.inventory(dataset)
    output = tmp_path / "audit"
    assert audit.main(["--output", str(output)]) == 0
    assert before == audit.inventory(dataset)
    result = audit.read_json(output / "auditoria.json")
    assert result["numeric_checks_pass"]
    assert result["metrics"]["micro"]["tp"] == 64
    assert len(result["metrics"]["sample"]) == 38
    assert result["environment_findings"][0]["id"] == "A3-04-F01"
    with pytest.raises(SystemExit):
        audit.main(["--output", str(output)])


def test_visual_review_is_traceable_to_38_source_frames():
    evidence = ROOT / "evidencias/A3-04"
    with (evidence / "revision_visual.csv").open(encoding="utf-8", newline="") as source:
        reviewed = list(csv.DictReader(source))
    manifest = audit.indexed(audit.read_lines(ROOT / "data/p5-eval-v1/manifiesto.jsonl"))
    assert len({r["frame_id"] for r in reviewed}) == 38
    assert {r["sequence_id"] for r in reviewed} == set(audit.SAMPLE)
    for row in reviewed:
        original = manifest[row["frame_id"]]
        assert row["image_sha256"] == original["sha256"]
        assert json.loads(row["cajas_xyxy"]) == [a["bbox_xyxy"] for a in original["annotations"]]
        assert row["observacion"] and row["discrepancia"]
        assert (evidence / row["lamina"]).is_file()
