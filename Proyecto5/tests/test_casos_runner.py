import copy
import json
import os
from pathlib import Path

import pytest
import yaml
from p3.policy.config import cargar_config

from p5.casos import runner
from p5.casos.runner import _rule_failures, load_cases, run_cases, run_real_case
from p5.dataset.paquete import load_manifest

PROJECT = Path(__file__).resolve().parents[1]
CASES = PROJECT / "casos" / "c1_c10.yaml"
CONFIG = PROJECT.parent / "Proyecto3" / "config" / "politica.yaml"
DATASET = PROJECT / "data" / "p5-eval-v1"
WEIGHTS = os.environ.get("P5_DETECTOR_WEIGHTS")


@pytest.fixture(scope="module")
def rows():
    return load_manifest(DATASET / "manifiesto.jsonl")


@pytest.fixture(scope="module")
def config():
    return cargar_config(CONFIG)


def frame(row, detections, status="ok", error=None):
    return {
        "sequence_id": row["sequence_id"],
        "frame_id": row["frame_id"],
        "t_capture_ms": row["t_capture_ms"],
        "image_width": row["image_width"],
        "image_height": row["image_height"],
        "status": status,
        "detections": detections,
        "error": error,
    }


def perfect_perceive(rows):
    """Un detector perfecto: entrega las etiquetas como detecciones. Solo para probar el runner."""
    by_frame = {row["frame_id"]: row for row in rows}

    def perceive(row):
        objects = by_frame[row["frame_id"]]["annotations"]
        detections = [
            {"class_name": o["class_name"], "confidence": 0.99, "bbox_xyxy": o["bbox_xyxy"]}
            for o in objects
        ]
        return frame(row, detections)

    return perceive


def case_by_id(data, case_id):
    return next(case for case in data["casos"] if case["id"] == case_id)


def result_by_id(report, case_id):
    return next(case for case in report["casos"] if case["id"] == case_id)


def test_cases_file_declares_c1_to_c10():
    data = load_cases(CASES)

    assert [case["id"] for case in data["casos"]] == [f"C{n}" for n in range(1, 11)]


@pytest.mark.parametrize("mutation", ["missing", "duplicate"])
def test_load_cases_rejects_an_incomplete_list(tmp_path, mutation):
    data = yaml.safe_load(CASES.read_text(encoding="utf-8"))
    if mutation == "missing":
        data["casos"].pop()
    else:
        data["casos"][-1]["id"] = "C1"
    path = tmp_path / "casos.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")

    with pytest.raises(ValueError, match="C1"):
        load_cases(path)


def test_expectations_are_consistent_with_a_perfect_detector(rows, config):
    # Si un caso falla con las etiquetas como entrada, la expectativa esta mal, no el sistema.
    report = run_cases(load_cases(CASES), rows, config, perfect_perceive(rows))

    real = [case for case in report["casos"] if case["tipo"] == "real"]
    assert len(real) == 6
    assert {case["id"]: case["fallos"] for case in real if case["resultado"] != "PASA"} == {}
    assert result_by_id(report, "C6")["resultado"] == "PASA"


def test_pending_cases_declare_their_contract_and_do_not_pass(rows, config):
    report = run_cases(load_cases(CASES), rows, config, perfect_perceive(rows))

    for case_id in ("C9", "C10"):
        case = result_by_id(report, case_id)
        assert case["resultado"] == "PENDIENTE"
        assert case["entrada"]
        assert case["esperado"]
        assert case["plazo_ms"] > 0
        assert case["bloqueado_por"]
    assert report["pasan"] == 8
    assert report["pendientes"] == 2
    assert report["correcto"] is False


def test_a_deliberately_wrong_expectation_fails_the_case(rows, config):
    data = copy.deepcopy(load_cases(CASES))
    case_by_id(data, "C1")["alguna"] = [{"cuadros": [3, 15], "acciones": ["EVADE_LEFT"]}]

    report = run_cases(data, rows, config, perfect_perceive(rows))

    case = result_by_id(report, "C1")
    assert case["resultado"] == "FALLA"
    assert "EVADE_LEFT" in json.dumps(case["fallos"])


def test_action_outside_the_manifest_fails_the_frame(rows, config):
    # Con el manifiesto alterado, el FORWARD ya no es admisible en la via libre.
    altered = copy.deepcopy([row for row in rows if row["sequence_id"] == "seq01"])
    for row in altered:
        row["allowed_actions"] = ["STOP"]
    case = case_by_id(load_cases(CASES), "C1")

    result = run_real_case(case, altered, config, perfect_perceive(altered))

    assert result["resultado"] == "FALLA"
    assert result["fallos"][0]["cuadro"] == 3
    assert result["fallos"][0]["observada"] == "FORWARD"


def test_always_stopping_loses_the_clear_case(rows, config):
    seq = [row for row in rows if row["sequence_id"] == "seq01"]
    case = case_by_id(load_cases(CASES), "C1")

    def stopped(row):
        return frame(row, [], status="error", error="sin percepcion")

    result = run_real_case(case, seq, config, stopped)

    assert result["resultado"] == "FALLA"
    assert "FORWARD" in json.dumps(result["fallos"])


def test_late_reaction_fails_the_case(rows, config):
    seq = [row for row in rows if row["sequence_id"] == "seq02"]
    case = case_by_id(load_cases(CASES), "C2")

    # Sin detecciones, la politica nunca bloquea aunque la persona este al centro.
    result = run_real_case(case, seq, config, lambda row: frame(row, []))

    assert result["resultado"] == "FALLA"
    assert any(fallo.get("regla") == "reaccion" for fallo in result["fallos"])


def decisions_blocked_at(blocked_frame, total=10):
    return [
        {
            "frame_id": f"seq-{number:04d}",
            "accion": "STOP" if number == blocked_frame else "SLOW",
            "estado": "BLOCKED" if number == blocked_frame else "CAUTION",
            "direccion": 0.0,
        }
        for number in range(1, total + 1)
    ]


@pytest.mark.parametrize(
    ("blocked_frame", "on_time"),
    [
        (4, False),  # Antes de `desde`: no reacciona a este obstaculo.
        (5, True),  # El primer cuadro del plazo.
        (6, True),  # El ultimo cuadro del plazo.
        (7, False),  # Un cuadro despues del plazo.
    ],
)
def test_reaction_deadline_counts_exactly_plazo_cuadros_frames(blocked_frame, on_time):
    case = {"reaccion": {"desde": 5, "plazo_cuadros": 2, "acciones": ["STOP"]}}

    failures = _rule_failures(case, decisions_blocked_at(blocked_frame))

    assert (failures == []) is on_time


def test_reaction_deadline_of_one_frame_only_accepts_that_frame():
    case = {"reaccion": {"desde": 5, "plazo_cuadros": 1, "acciones": ["STOP"]}}

    assert _rule_failures(case, decisions_blocked_at(5)) == []
    assert _rule_failures(case, decisions_blocked_at(6)) != []


def test_reaction_deadline_past_the_end_of_the_sequence_fails():
    case = {"reaccion": {"desde": 10, "plazo_cuadros": 2, "acciones": ["STOP"]}}

    assert _rule_failures(case, decisions_blocked_at(10)) != []


def test_reaction_failure_only_reports_the_frames_inside_the_deadline():
    case = {"reaccion": {"desde": 5, "plazo_cuadros": 2, "acciones": ["STOP"]}}

    failure = _rule_failures(case, decisions_blocked_at(7))[0]

    # El cuadro 7 esta bloqueado, pero queda fuera del plazo.
    assert failure["observadas"] == ["SLOW/CAUTION"]


def test_direction_towards_the_occupied_side_fails(rows, config):
    seq = [row for row in rows if row["sequence_id"] == "seq03"]
    case = copy.deepcopy(case_by_id(load_cases(CASES), "C3"))
    case["direccion_min"] = 0.5

    result = run_real_case(case, seq, config, perfect_perceive(rows))

    assert any(fallo.get("regla") == "direccion" for fallo in result["fallos"])


def test_perception_never_receives_the_labels(rows, config):
    seq = [row for row in rows if row["sequence_id"] == "seq02"]
    case = case_by_id(load_cases(CASES), "C2")
    seen = []

    def perceive(row):
        seen.append(set(row))
        return frame(row, [])

    run_real_case(case, seq, config, perceive)

    assert seen
    assert all(not keys & {"annotations", "road_state", "allowed_actions"} for keys in seen)


def test_perception_exception_becomes_a_stop_and_is_recorded(rows, config):
    seq = [row for row in rows if row["sequence_id"] == "seq01"]
    case = case_by_id(load_cases(CASES), "C1")

    def broken(row):
        raise RuntimeError("detector roto")

    result = run_real_case(case, seq, config, broken)

    assert result["resultado"] == "FALLA"
    assert {decision["accion"] for decision in result["decisiones"]} == {"STOP"}
    assert "detector roto" in result["decisiones"][0]["cuadro"]["error"]


def test_unknown_sequence_is_a_failure_and_not_a_pass(rows, config):
    data = copy.deepcopy(load_cases(CASES))
    case_by_id(data, "C1")["secuencia"] = "seq99"

    report = run_cases(data, rows, config, perfect_perceive(rows))

    case = result_by_id(report, "C1")
    assert case["resultado"] == "FALLA"
    assert "seq99" in json.dumps(case["fallos"])


def test_rule_outside_the_sequence_is_a_failure(rows, config):
    data = copy.deepcopy(load_cases(CASES))
    case_by_id(data, "C1")["alguna"] = [{"cuadros": [100, 101], "acciones": ["FORWARD"]}]

    report = run_cases(data, rows, config, perfect_perceive(rows))

    assert result_by_id(report, "C1")["resultado"] == "FALLA"


def test_results_link_decisions_with_frames_and_state(rows, config):
    report = run_cases(load_cases(CASES), rows, config, perfect_perceive(rows))

    decision = result_by_id(report, "C2")["decisiones"][0]
    assert decision["frame_id"] == "seq02-0001"
    assert decision["cuadro"]["detections"]
    assert decision["estado"]
    assert decision["reason_code"]
    assert decision["config_sha256"] == config[1]


def run_main_with_fake_detector(monkeypatch, tmp_path, rows, cases=CASES, output="salida"):
    monkeypatch.setattr(
        runner, "detector_perceive", lambda weights, dataset: perfect_perceive(rows)
    )
    weights = tmp_path / "pesos.onnx"
    weights.write_bytes(b"pesos")
    target = tmp_path / output
    code = runner.main(
        [
            "--cases",
            str(cases),
            "--config",
            str(CONFIG),
            "--dataset",
            str(DATASET),
            "--weights",
            str(weights),
            "--output",
            str(target),
        ]
    )
    return code, target


def test_cli_exits_non_zero_while_cases_are_pending_and_stores_the_results(
    monkeypatch, tmp_path, rows, capsys
):
    code, target = run_main_with_fake_detector(monkeypatch, tmp_path, rows)

    assert code == 1
    assert "PENDIENTE" in capsys.readouterr().out
    report = json.loads((target / "resultados.json").read_text(encoding="utf-8"))
    assert report["ejecucion"]["modelo_sha256"]
    assert report["ejecucion"]["manifiesto_sha256"]
    assert report["ejecucion"]["config_sha256"] == cargar_config(CONFIG)[1]
    assert report["ejecucion"]["modo"] == "virtual"
    lines = (target / "decisiones.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["caso"] == "C1"


def cases_without_pending(tmp_path, monkeypatch):
    """C1-C7 en un archivo aparte, como si C8-C10 ya no fueran parte de la lista requerida."""
    data = yaml.safe_load(CASES.read_text(encoding="utf-8"))
    for case in data["casos"]:
        if case["tipo"] == "sintetico":
            case["archivo"] = str((CASES.parent / case["archivo"]).resolve())
    data["casos"] = [case for case in data["casos"] if case["tipo"] != "pendiente"]
    monkeypatch.setattr(runner, "REQUIRED_CASES", tuple(case["id"] for case in data["casos"]))
    return data, tmp_path / "casos.yaml"


def test_cli_exits_zero_only_when_every_case_passes(monkeypatch, tmp_path, rows):
    data, path = cases_without_pending(tmp_path, monkeypatch)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")

    code, _ = run_main_with_fake_detector(monkeypatch, tmp_path, rows, cases=path)

    assert code == 0


def test_cli_exits_non_zero_on_a_wrong_expectation(monkeypatch, tmp_path, rows):
    data, path = cases_without_pending(tmp_path, monkeypatch)
    case_by_id(data, "C1")["alguna"] = [{"cuadros": [3, 15], "acciones": ["EVADE_LEFT"]}]
    path.write_text(yaml.safe_dump(data), encoding="utf-8")

    code, _ = run_main_with_fake_detector(monkeypatch, tmp_path, rows, cases=path)

    assert code == 1


def test_cases_file_cannot_drop_a_required_case(tmp_path):
    data = yaml.safe_load(CASES.read_text(encoding="utf-8"))
    data["casos"] = [case for case in data["casos"] if case["tipo"] != "pendiente"]
    path = tmp_path / "sin_pendientes.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")

    with pytest.raises(ValueError, match="C10"):
        load_cases(path)


def test_cli_refuses_an_existing_output_folder(monkeypatch, tmp_path, rows):
    (tmp_path / "salida").mkdir()

    with pytest.raises(SystemExit):
        run_main_with_fake_detector(monkeypatch, tmp_path, rows)


@pytest.mark.skipif(not WEIGHTS, reason="P5_DETECTOR_WEIGHTS not set")
def test_cli_runs_the_real_detector_over_the_frozen_dataset(tmp_path):
    target = tmp_path / "salida"

    code = runner.main(
        [
            "--cases",
            str(CASES),
            "--config",
            str(CONFIG),
            "--dataset",
            str(DATASET),
            "--weights",
            WEIGHTS,
            "--output",
            str(target),
        ]
    )

    assert code == 1
    report = json.loads((target / "resultados.json").read_text(encoding="utf-8"))
    assert result_by_id(report, "C1")["decisiones"][0]["frame_id"] == "seq01-0001"
    assert result_by_id(report, "C8")["resultado"] == "PENDIENTE"


def test_c8_watchdog_is_reproducible(rows, config):
    report = run_cases(
        load_cases(CASES),
        rows,
        config,
        perfect_perceive(rows),
    )

    c8 = result_by_id(report, "C8")

    assert c8["resultado"] == "PASA"
    assert c8["plazo_ms"] == 500

    commands = c8["comandos"]

    assert commands[0]["evento"] == "movimiento_inicial"
    assert commands[0]["direction"] == "forward"

    assert commands[1]["evento"] == "watchdog"
    assert commands[1]["direction"] == "stop"
    assert commands[1]["reason_code"] == "watchdog_timeout"

    assert commands[2]["evento"] == "cuadro_vencido"
    assert commands[2]["direction"] == "stop"
    assert commands[2]["reason_code"] == "watchdog_timeout"
