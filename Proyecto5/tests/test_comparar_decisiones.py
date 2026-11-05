"""La revision de B1-03 se repite desde los archivos versionados."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidencias" / "B1-03-detector"
SPEC = importlib.util.spec_from_file_location(
    "comparar_decisiones", ROOT / "scripts" / "comparar_decisiones.py"
)
comparar = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(comparar)


def real_comparison():
    return comparar.compare(
        comparar.read_jsonl(EVIDENCE / "c1-c10-mediana3" / "decisiones.jsonl"),
        comparar.read_jsonl(EVIDENCE / "c1-c10-sin-filtro" / "decisiones.jsonl"),
        comparar.read_jsonl(ROOT / "data" / "p5-eval-v1" / "manifiesto.jsonl"),
    )


def test_filter_run_is_the_agreed_one_and_was_not_edited():
    result = json.loads(
        (EVIDENCE / "c1-c10-mediana3" / "resultados.json").read_text(encoding="utf-8")
    )

    assert result["ejecucion"]["filtro_mediana_detector"] == 3
    assert result["ejecucion"]["commit"] == "62a1bf37574ff5b087b65c5acdc2d479d54e2276"
    assert (result["pasan"], result["fallan"], result["pendientes"]) == (10, 0, 0)


def test_review_finds_no_forbidden_action_with_the_filter():
    comparison = real_comparison()

    assert comparison["no_permitidas"]["con"] == []
    assert comparison["no_permitidas"]["sin"] == [
        "seq05-0008:EVADE_RIGHT",
        "seq05-0009:EVADE_RIGHT",
        "seq05-0010:EVADE_RIGHT",
        "seq06-0036:FORWARD",
        "seq06-0038:FORWARD",
    ]


def test_review_records_the_only_changes_on_a_free_path():
    comparison = real_comparison()
    sections = comparison["tramos"]

    assert sections["C1, seq01"]["con_filtro"] == sections["C1, seq01"]["sin_filtro"]
    assert sections["seq06 libre, 1-26"]["con_filtro"] == {"FORWARD": 23, "SLOW": 1, "STOP": 2}
    assert sections["seq06 libre, 49-50"]["con_filtro"] == {"FORWARD": 2}
    free_changes = [
        change
        for change in comparison["cambios"]
        if change["frame_id"].startswith("seq06") and comparar.number(change["frame_id"]) <= 26
    ]
    assert [(item["frame_id"], item["ahora"]) for item in free_changes] == [
        ("seq06-0025", "SLOW/CENTRO_DEBIL")
    ]


def test_runs_with_different_frames_are_rejected():
    row = {"caso": "C1", "frame_id": "seq01-0001", "accion": "STOP", "reason_code": "X"}

    with pytest.raises(ValueError, match="mismos casos"):
        comparar.compare([row], [], [])
