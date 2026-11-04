import csv
import json
import os
from pathlib import Path

import pytest

from p5.benchmark import __main__ as cli
from p5.detector.weights import WEIGHTS_SHA256

WEIGHTS = os.environ.get("P5_DETECTOR_WEIGHTS")
ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(not WEIGHTS, reason="P5_DETECTOR_WEIGHTS not set")


def test_real_benchmark_meets_the_minimums_with_real_images(tmp_path):
    output = tmp_path / "medicion"

    code = cli.main(
        [
            "--manifest",
            str(ROOT / "Proyecto5" / "data" / "p5-eval-v1" / "manifiesto.jsonl"),
            "--output",
            str(output),
            "--weights",
            WEIGHTS,
            "--policy-config",
            str(ROOT / "Proyecto3" / "config" / "politica.yaml"),
            "--repeticiones",
            "100",
        ]
    )

    assert code == 0
    evidence = json.loads((output / "benchmark.json").read_text(encoding="utf-8"))
    assert evidence["detector"]["sha256"] == WEIGHTS_SHA256
    assert evidence["resumen"]["calentamientos"] == 10
    assert evidence["resumen"]["mediciones_validas"] == 100
    assert evidence["resumen"]["cumple_minimos"] is True
    for stage, numbers in evidence["resumen"]["etapas"].items():
        assert numbers["n"] == 100, stage
        assert 0 < numbers["p50"] <= numbers["p95"] <= numbers["maximo"], stage

    with (output / "tiempos.csv").open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    assert len(rows) == 110
    assert {row["valido"] for row in rows} == {"True"}
