"""B1-03: expectativas previas de geometria, confianza y decisiones, sin reajustar evaluacion."""

import json
import os
from pathlib import Path

import pytest
import yaml
from p3.policy.config import cargar_config

from p5.casos import runner
from p5.casos.confidence import run_confidence_case
from p5.casos.geometry import geometry_failures, occupied_zones
from p5.dataset.paquete import load_manifest
from test_casos_runner import perfect_detector

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/politica_b1_03.yaml"
CASES = ROOT / "casos/c1_c10.yaml"
DATASET = ROOT / "data/p5-eval-v1"


@pytest.mark.parametrize(
    ("boxes", "expected"),
    [
        ([[0, 120, 140, 280]], {"izquierda"}),
        ([[140, 120, 260, 280]], {"centro"}),
        ([[260, 120, 400, 280]], {"derecha"}),
        ([[0, 120, 400, 280]], {"izquierda", "centro", "derecha"}),
        ([[10, 120, 80, 280], [160, 120, 240, 280]], {"izquierda", "centro"}),
    ],
)
def test_geometry_uses_all_boxes_and_positive_overlap_at_boundaries(boxes, expected):
    objects = [{"class_name": "person", "bbox_xyxy": box} for box in boxes]
    config, _ = cargar_config(CONFIG)
    assert occupied_zones(objects, 400, 296, config) == expected


@pytest.mark.parametrize(("direction", "name"), [(-0.5, "izquierda"), (0.5, "derecha")])
def test_ground_truth_rejects_turn_even_when_policy_claims_destination_free(direction, name):
    config, _ = cargar_config(CONFIG)
    row = {
        "annotations": [{"class_name": "person", "bbox_xyxy": [0, 120, 400, 280]}],
        "image_width": 400,
        "image_height": 296,
    }
    record = {
        "accion": "EVADE_LEFT" if direction < 0 else "EVADE_RIGHT",
        "direccion": direction,
        "velocidad": 0.2,
        "cuadro": {"detections": [], "status": "ok"},
        "detecciones": [],
        "zonas": {name: {"estado": "LIBRE", "racha_libre": 99}},
    }
    assert geometry_failures(record, row, config)[0]["regla"] == "destino_no_libre"


def test_perfect_detector_confirms_expectations_before_using_real_predictions():
    rows = load_manifest(DATASET / "manifiesto.jsonl")
    cases = runner.load_cases(CASES)
    cases["casos"] = cases["casos"][:7]
    report = runner.run_cases(cases, rows, cargar_config(CONFIG), perfect_detector(rows), DATASET)
    assert report["correcto"], {case["id"]: case["fallos"] for case in report["casos"]}
    assert report["pasan"] == 7


def test_c6_distinguishes_ignored_weak_and_exactly_high_threshold():
    config = cargar_config(CONFIG)
    report = run_confidence_case({"id": "C6", "nombre": "confidence"}, config)
    assert report["resultado"] == "PASA"
    levels = {expectation["fase"]: expectation["confidence"] for expectation in report["esperado"]}
    assert levels["ignorada"] < config[0].confianza.umbral_bajo
    assert config[0].confianza.umbral_bajo < levels["debil"] < config[0].confianza.umbral_alto
    assert levels["firme"] == config[0].confianza.umbral_alto


def test_c7_requires_clear_blocked_clear_in_order():
    case = {"estados_en_orden": ["CLEAR", "BLOCKED", "CLEAR"]}
    states = [{"estado": state, "direccion": 0} for state in ["CLEAR", "BLOCKED", "BLOCKED"]]
    assert runner._rule_failures(case, states)[0]["regla"] == "estados_en_orden"
    states.append({"estado": "CLEAR", "direccion": 0})
    assert runner._rule_failures(case, states) == []


def test_tuning_rejects_evaluation_frames_before_scoring():
    from p5.casos.tune import select_profile

    rows = load_manifest(DATASET / "manifiesto.jsonl")
    with pytest.raises(ValueError, match="solo admite cuadros de ajuste"):
        select_profile(rows, {}, cargar_config(CONFIG)[0])


def test_c7_control_preserves_block_and_eventually_returns_to_clear():
    from p5.casos.temporal import run_temporal_control

    report = run_temporal_control(cargar_config(CONFIG))
    assert report["resultado"] == "PASA"
    changes = [d["estado"] for d in report["decisiones"] if d["cambio_estado"]]
    assert changes == ["CLEAR", "CAUTION", "BLOCKED", "CLEAR"]
    assert report["decisiones"][8]["estado"] == "BLOCKED"  # Ausencia aislada.
    assert report["decisiones"][-1]["accion"] == "FORWARD"


def test_stored_real_results_are_traceable_and_do_not_hide_the_failed_case():
    import hashlib

    evidence = ROOT / "evidencias/B1-03"
    report = json.loads((evidence / "evaluacion/resultados.json").read_text(encoding="utf-8"))
    assert (report["pasan"], report["fallan"], report["pendientes"]) == (6, 1, 0)
    assert not report["correcto"]
    assert report["ejecucion"]["detector"] == "YoloxDetector"
    assert report["ejecucion"]["config_sha256"] == hashlib.sha256(CONFIG.read_bytes()).hexdigest()
    c7 = report["casos"][-1]
    assert c7["resultado"] == "FALLA" and c7["control_temporal"]["resultado"] == "PASA"
    assert {failure["regla"] for failure in c7["fallos"]} == {
        "acciones",
        "avance_hacia_centro_ocupado",
        "reaccion",
    }
    protocol = json.loads((evidence / "protocolo_previo.json").read_text(encoding="utf-8"))
    assert protocol["fecha_previa_inferencia"] < report["ejecucion"]["fecha"]
    for name, sha256 in protocol["archivos_sha256"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha256


def test_wrong_expectation_is_saved_and_returns_failure(monkeypatch, tmp_path):
    rows = load_manifest(DATASET / "manifiesto.jsonl")
    monkeypatch.setattr(runner, "load_detector", lambda _: perfect_detector(rows))
    data = yaml.safe_load(CASES.read_text(encoding="utf-8"))
    data["casos"][0]["alguna"][0]["acciones"] = ["EVADE_LEFT"]
    # Archivo temporal en la misma estructura: resolver la fuente sintetica original.
    for case in data["casos"]:
        if "archivo" in case:
            case["archivo"] = str((CASES.parent / case["archivo"]).resolve())
    source = tmp_path / "cases.yaml"
    source.write_text(yaml.safe_dump(data), encoding="utf-8")
    weights = tmp_path / "fake.onnx"
    weights.write_bytes(b"fake for runner test")
    target = tmp_path / "output"
    code = runner.main(
        [
            "--cases",
            str(source),
            "--config",
            str(CONFIG),
            "--dataset",
            str(DATASET),
            "--weights",
            str(weights),
            "--output",
            str(target),
            "--only",
            "C1",
        ]
    )
    assert code == 1
    failure = json.loads((target / "fallos.jsonl").read_text(encoding="utf-8"))
    assert failure["caso"] == "C1" and failure["regla"] == "alguna"
    report = json.loads((target / "resultados.json").read_text(encoding="utf-8"))
    assert report["total"] == 1 and report["pendientes"] == 0
    assert report["ejecucion"]["expectativas_previas"]["casos_ejecutados"] == ["C1"]


def test_validator_detects_when_policy_omits_a_detection():
    config, _ = cargar_config(CONFIG)
    row = {"annotations": [], "image_width": 400, "image_height": 296}
    record = {
        "accion": "FORWARD",
        "velocidad": 0.6,
        "direccion": 0,
        "cuadro": {"status": "ok", "detections": [{"class_name": "person"}]},
        "detecciones": [],
    }
    assert geometry_failures(record, row, config)[0]["regla"] == "detecciones_no_consideradas"


@pytest.mark.skipif(not os.environ.get("P5_DETECTOR_WEIGHTS"), reason="P5_DETECTOR_WEIGHTS not set")
def test_real_detector_reproduces_documented_c7_deviation(tmp_path):
    code = runner.main(
        [
            "--cases",
            str(CASES),
            "--config",
            str(CONFIG),
            "--dataset",
            str(DATASET),
            "--weights",
            os.environ["P5_DETECTOR_WEIGHTS"],
            "--output",
            str(tmp_path / "real"),
            "--only",
            "C1",
            "C2",
            "C3",
            "C4",
            "C5",
            "C6",
            "C7",
        ]
    )
    report = json.loads((tmp_path / "real/resultados.json").read_text(encoding="utf-8"))
    assert code == 1
    assert [case["resultado"] for case in report["casos"]] == ["PASA"] * 6 + ["FALLA"]
