"""B1-02: estabilidad temporal, contrato, replay y registro de transiciones."""

import copy
import json
import logging
from pathlib import Path

import pytest
import yaml
from p3.policy.casos import construir_cuadros
from p3.policy.config import ConfigPolitica, cargar_config
from p3.policy.politica import PoliticaDecision

from p5.policy.__main__ import main
from p5.policy.replay import run_cases

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/politica.yaml"
CASES = ROOT / "casos/politica_c1_c7.yaml"


@pytest.fixture
def data():
    return yaml.safe_load(CASES.read_text(encoding="utf-8"))


def test_c1_c7_have_exact_frame_expectations_and_reasons(data):
    report = run_cases(data, *cargar_config(CONFIG))
    assert report["total"] == report["pasan"] == 7
    for case in report["casos"]:
        assert not case["fallos"]
        for decision in case["decisiones"]:
            assert decision["reason_code"] and decision["razon"]
            assert decision["cambio_estado"] == (decision["estado"] != decision["estado_anterior"])
            assert decision["config_sha256"] == case["config_efectiva_sha256"]


def test_c7_records_exact_transitions_and_does_not_release_on_one_empty_frame(data):
    report = run_cases(data, *cargar_config(CONFIG))
    c7 = report["casos"][-1]
    assert [d["frame_id"] for d in c7["transiciones"]] == [
        "C7-0003",
        "C7-0004",
        "C7-0005",
        "C7-0012",
    ]
    assert [(d["estado_anterior"], d["estado"]) for d in c7["transiciones"]] == [
        ("UNKNOWN", "CLEAR"),
        ("CLEAR", "CAUTION"),
        ("CAUTION", "BLOCKED"),
        ("BLOCKED", "CLEAR"),
    ]
    assert c7["decisiones"][7]["accion"] == "STOP"
    assert c7["decisiones"][10]["accion"] == "STOP"
    assert c7["decisiones"][11]["accion"] == "FORWARD"


def test_replay_produces_identical_bytes_and_never_overwrites_evidence(tmp_path):
    outputs = [tmp_path / "first", tmp_path / "second"]
    for output in outputs:
        assert main(["--cases", str(CASES), "--config", str(CONFIG), "--output", str(output)]) == 0
    for filename in ("resultados.json", "decisiones.jsonl", "transiciones.jsonl"):
        assert (outputs[0] / filename).read_bytes() == (outputs[1] / filename).read_bytes()
    before = (outputs[0] / "resultados.json").read_bytes()
    assert main(["--cases", str(CASES), "--config", str(CONFIG), "--output", str(outputs[0])]) == 1
    assert (outputs[0] / "resultados.json").read_bytes() == before


def test_failed_expectations_fail_the_cli_and_preserve_observed_decisions(data, tmp_path):
    data["casos"][0]["esperado"][-1]["accion"] = "STOP"
    source = tmp_path / "cases.yaml"
    source.write_text(yaml.safe_dump(data), encoding="utf-8")
    output = tmp_path / "report"
    assert main(["--cases", str(source), "--config", str(CONFIG), "--output", str(output)]) == 1
    report = json.loads((output / "resultados.json").read_text(encoding="utf-8"))
    assert report["casos"][0]["resultado"] == "FALLA"
    assert report["casos"][0]["decisiones"][-1]["accion"] == "FORWARD"


@pytest.mark.parametrize("fault", ["missing", "duplicate", "uncovered"])
def test_incomplete_case_suites_are_rejected(data, fault):
    if fault == "missing":
        data["casos"].pop()
    elif fault == "duplicate":
        data["casos"][-1]["id"] = "C1"
    else:
        data["casos"][0]["esperado"].pop()
    with pytest.raises(ValueError):
        run_cases(data, *cargar_config(CONFIG))


def test_temporal_thresholds_are_configured_not_hardcoded(data):
    config, sha256 = cargar_config(CONFIG)
    settings = config.model_dump()
    settings["temporal"].update(cuadros_para_bloquear=3, cuadros_para_liberar=4)
    settings["evasion"]["habilitada"] = False
    engine = PoliticaDecision(ConfigPolitica.model_validate(settings), sha256)
    case = {
        "id": "custom",
        "escenas": [
            {"repetir": 4, "objetos": []},
            {"repetir": 3, "objetos": [{"caja": "CENTRO"}]},
            {"repetir": 4, "objetos": []},
        ],
    }
    decisions = [engine.decidir_crudo(f.model_dump()) for f in construir_cuadros(case, data)]
    assert [d.accion for d in decisions[:4]] == ["STOP", "STOP", "STOP", "FORWARD"]
    assert [d.estado for d in decisions[4:7]] == ["CAUTION", "CAUTION", "BLOCKED"]
    assert [d.accion for d in decisions[7:]] == ["STOP", "STOP", "STOP", "FORWARD"]


def test_multiple_objects_in_one_frame_are_not_multiple_temporal_confirmations(data):
    config, sha256 = cargar_config(CONFIG)
    engine = PoliticaDecision(config, sha256)
    case = {
        "id": "duplicates",
        "escenas": [
            {"repetir": 3, "objetos": []},
            {"objetos": [{"caja": "CENTRO"}] * 4},
        ],
    }
    decisions = [engine.decidir_crudo(f.model_dump()) for f in construir_cuadros(case, data)]
    assert decisions[-1].estado == "CAUTION"
    assert decisions[-1].zonas["centro"].racha_ocupada == 1


def test_alternating_firm_and_weak_detections_do_not_accumulate_blocking_frames(data):
    config, sha256 = cargar_config(CONFIG)
    engine = PoliticaDecision(config, sha256)
    case = {
        "id": "alternating",
        "escenas": [{"repetir": 3, "objetos": []}]
        + [{"objetos": [{"caja": "CENTRO", "conf": confidence}]} for confidence in [0.9, 0.4] * 5],
    }
    decisions = [engine.decidir_crudo(f.model_dump()) for f in construir_cuadros(case, data)]
    assert all(d.estado == "CAUTION" for d in decisions[3:])


@pytest.mark.parametrize("mutation", ["missing_detections", "invalid_confidence", "bad_box"])
def test_invalid_contract_is_a_fault_not_a_clear_path(data, mutation):
    engine = PoliticaDecision(*cargar_config(CONFIG))
    frame = construir_cuadros(data["casos"][1], data)[-1].model_dump()
    if mutation == "missing_detections":
        del frame["detections"]
    else:
        frame["detections"] = [copy.deepcopy(frame["detections"][0])]
        if mutation == "invalid_confidence":
            frame["detections"][0]["confidence"] = 1.1
        else:
            frame["detections"][0]["bbox_xyxy"] = [100, 100, 20, 20]
    decision = engine.decidir_crudo(frame)
    assert (decision.estado, decision.accion) == ("FAULT", "STOP")
    assert decision.reason_code == "SALIDA_MALFORMADA"


def test_replay_logs_only_real_state_changes_with_structured_fields(data, caplog):
    with caplog.at_level(logging.INFO, logger="p5.policy.events"):
        report = run_cases(data, *cargar_config(CONFIG))
    expected = [event for case in report["casos"] for event in case["transiciones"]]
    actual = [r.policy_transition for r in caplog.records if hasattr(r, "policy_transition")]
    assert actual == expected
    assert all(event["cambio_estado"] for event in actual)
