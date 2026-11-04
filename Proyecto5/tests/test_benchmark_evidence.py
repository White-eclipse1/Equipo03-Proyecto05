"""La evidencia versionada debe ser coherente, sin correr el benchmark otra vez."""

import csv
import hashlib
import json
import statistics
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest
import yaml

from p5.benchmark.timing import COLUMNS, MIN_RUNS, MIN_WARMUPS, STAGES, TOTAL
from p5.detector.weights import WEIGHTS_SHA256, WEIGHTS_SIZE

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidencias"
OFFICIAL = EVIDENCE / "A3-03"
RUNS = [OFFICIAL, EVIDENCE / "A3-03-programas-abiertos"]
MANIFEST = ROOT / "data" / "p5-eval-v1" / "manifiesto.jsonl"
DOC = ROOT / "docs" / "A3-03_BENCHMARK.md"
POLICY = ROOT.parent / "Proyecto3" / "config" / "politica.yaml"


def load(folder):
    evidence = json.loads(
        (folder / "benchmark.json").read_text(encoding="utf-8"), parse_constant=pytest.fail
    )
    with (folder / "tiempos.csv").open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    return evidence, rows


@pytest.mark.parametrize("folder", RUNS, ids=lambda folder: folder.name)
def test_evidence_identifies_what_was_measured(folder):
    evidence, _rows = load(folder)

    assert evidence["detector"]["sha256"] == WEIGHTS_SHA256
    assert evidence["detector"]["bytes"] == WEIGHTS_SIZE
    assert evidence["dataset"]["nombre"] == "p5-eval-v1"
    assert (
        evidence["dataset"]["manifiesto_sha256"]
        == hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
    )
    assert evidence["codigo"]["cambios_sin_commit"] is False
    assert len(evidence["codigo"]["commit"]) == 40
    assert evidence["salida_fisica"] is False
    assert evidence["runtime"]["providers_sesion"] == ["CPUExecutionProvider"]
    assert evidence["hardware"]["cpu"]
    assert evidence["hardware"]["sistema_operativo"]


@pytest.mark.parametrize("folder", RUNS, ids=lambda folder: folder.name)
def test_timings_are_the_exported_file_and_meet_the_minimums(folder):
    evidence, rows = load(folder)

    content = (folder / "tiempos.csv").read_bytes()
    assert hashlib.sha256(content).hexdigest() == evidence["tiempos"]["sha256"]
    assert b"\r" not in content
    assert tuple(rows[0]) == COLUMNS
    assert len(rows) == evidence["tiempos"]["filas"]

    phases = [row["fase"] for row in rows]
    warmups = phases.count("calentamiento")
    assert warmups >= MIN_WARMUPS
    assert phases == ["calentamiento"] * warmups + ["medicion"] * (len(rows) - warmups)
    assert [int(row["indice"]) for row in rows] == list(range(len(rows)))
    valid = [row for row in rows if row["fase"] == "medicion" and row["valido"] == "True"]
    assert len(valid) >= MIN_RUNS
    assert sum(r["fase"] == "calentamiento" and r["valido"] == "True" for r in rows) >= MIN_WARMUPS
    assert evidence["resumen"]["cumple_minimos"] is True


@pytest.mark.parametrize("folder", RUNS, ids=lambda folder: folder.name)
def test_summary_can_be_recalculated_from_the_raw_timings(folder):
    evidence, rows = load(folder)

    valid = [row for row in rows if row["fase"] == "medicion" and row["valido"] == "True"]
    assert evidence["resumen"]["mediciones_validas"] == len(valid)
    for stage in (TOTAL, *STAGES):
        values = [float(row[stage]) for row in valid]
        numbers = evidence["resumen"]["etapas"][stage]
        assert numbers["n"] == len(values)
        assert numbers["p50"] == pytest.approx(np.percentile(values, 50))
        assert numbers["p95"] == pytest.approx(np.percentile(values, 95))
        assert numbers["maximo"] == max(values)
        assert numbers["minimo"] == min(values)


@pytest.mark.parametrize("folder", RUNS, ids=lambda folder: folder.name)
def test_published_evidence_has_no_local_paths(folder):
    for name in ("benchmark.json", "tiempos.csv"):
        text = (folder / name).read_text(encoding="utf-8")
        assert "Users" not in text
        assert "/home/" not in text


def test_document_reports_the_official_figures():
    evidence, _rows = load(OFFICIAL)
    document = DOC.read_text(encoding="utf-8").split("## Resultados", 1)[1]

    assert evidence["codigo"]["commit"][:7] in document
    for stage in (TOTAL, *STAGES):
        numbers = evidence["resumen"]["etapas"][stage]
        row = next(line for line in document.splitlines() if line.startswith(f"| `{stage}` | "))
        assert f"{numbers['p50']:.2f}" in row
        assert f"{numbers['p95']:.2f}" in row
        assert f"{numbers['maximo']:.2f}" in row


def test_document_compares_the_official_figures_with_the_deadlines():
    evidence, _rows = load(OFFICIAL)
    document = DOC.read_text(encoding="utf-8").split("### Contraste con los plazos", 1)[1]
    document = document.split("###", 1)[0]
    total = evidence["resumen"]["etapas"]["ms_total"]
    inference = evidence["resumen"]["etapas"]["ms_inferencia"]
    config = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    validity = config["temporal"]["vigencia_comando_ms"]

    sequences = {}
    for line in MANIFEST.read_text(encoding="ascii").splitlines():
        row = json.loads(line)
        sequences.setdefault(row["sequence_id"], []).append(row["t_capture_ms"])
    gaps = [b - a for times in sequences.values() for a, b in pairwise(times)]

    assert f"{total['p95']:.2f} ms" in document
    assert f"{total['maximo']:.2f} ms" in document
    assert f"{inference['p95']:.2f} ms" in document
    assert f"{validity} ms" in document
    assert f"{len(gaps)} huecos" in document
    assert f"{min(gaps)} a {max(gaps)} ms" in document
    assert f"mediana {statistics.median(gaps):.0f} ms" in document
    assert f"{sum(gap > validity for gap in gaps)} de {len(gaps)}" in document


def test_document_reports_the_size_of_the_model():
    document = DOC.read_text(encoding="utf-8").split("## Resultados", 1)[1]

    assert f"{WEIGHTS_SIZE:,}".replace(",", " ") + " bytes" in document
