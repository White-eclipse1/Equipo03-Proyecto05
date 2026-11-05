import copy
import json
import os
from dataclasses import fields, replace
from pathlib import Path

import numpy as np
import pytest
import yaml
from p3.policy.config import cargar_config

from p5.casos import runner
from p5.casos.runner import _rule_failures, load_cases, run_cases, run_real_case
from p5.control.adapter import VirtualControlAdapter
from p5.dataset.paquete import load_manifest
from p5.detector.models import Detection
from p5.detector.yolox import DetectorError
from p5.integration.pipeline import FrameInput

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


class ScriptedDetector:
    """Detector de prueba: decide las detecciones segun el nombre del archivo del cuadro."""

    def __init__(self, detections_for):
        self.detections_for = detections_for
        self.sources = []

    def read_image(self, source):
        return np.zeros((296, 400, 3), dtype=np.uint8)

    def detect_image(self, image, *, source):
        self.sources.append(source)
        return self.detections_for(Path(source).stem)


def perfect_detector(rows):
    """Un detector perfecto: entrega las etiquetas como detecciones. Solo para probar el runner."""
    by_frame = {row["frame_id"]: row for row in rows}

    def detections_for(frame_id):
        return tuple(
            Detection(o["class_name"], 0.99, tuple(o["bbox_xyxy"]))
            for o in by_frame[frame_id]["annotations"]
        )

    return ScriptedDetector(detections_for)


def blind_detector():
    return ScriptedDetector(lambda frame_id: ())


class FailingDetector(ScriptedDetector):
    def __init__(self, failure):
        super().__init__(lambda frame_id: ())
        self.failure = failure

    def read_image(self, source):
        raise self.failure


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
    report = run_cases(load_cases(CASES), rows, config, perfect_detector(rows), DATASET)

    real = [case for case in report["casos"] if case["tipo"] == "real"]
    assert len(real) == 6
    assert {case["id"]: case["fallos"] for case in real if case["resultado"] != "PASA"} == {}
    assert result_by_id(report, "C6")["resultado"] == "PASA"


def test_c9_and_c10_are_executable_and_complete(rows, config):
    report = run_cases(load_cases(CASES), rows, config, perfect_detector(rows), DATASET)

    for case_id in ("C9", "C10"):
        case = result_by_id(report, case_id)
        assert case["resultado"] == "PASA"
        assert case["entrada"]
        assert case["esperado"]
        assert case["plazo_ms"] > 0

    assert report["pasan"] == 10
    assert report["fallan"] == 0
    assert report["pendientes"] == 0
    assert report["correcto"] is True


def test_a_deliberately_wrong_expectation_fails_the_case(rows, config):
    data = copy.deepcopy(load_cases(CASES))
    case_by_id(data, "C1")["alguna"] = [{"cuadros": [3, 15], "acciones": ["EVADE_LEFT"]}]

    report = run_cases(data, rows, config, perfect_detector(rows), DATASET)

    case = result_by_id(report, "C1")
    assert case["resultado"] == "FALLA"
    assert "EVADE_LEFT" in json.dumps(case["fallos"])


def test_action_outside_the_manifest_fails_the_frame(rows, config):
    # Con el manifiesto alterado, el FORWARD ya no es admisible en la via libre.
    altered = copy.deepcopy([row for row in rows if row["sequence_id"] == "seq01"])
    for row in altered:
        row["allowed_actions"] = ["STOP"]
    case = case_by_id(load_cases(CASES), "C1")

    result = run_real_case(case, altered, config, perfect_detector(altered), DATASET)

    assert result["resultado"] == "FALLA"
    assert result["fallos"][0]["cuadro"] == 3
    assert result["fallos"][0]["observada"] == "FORWARD"


def test_always_stopping_loses_the_clear_case(rows, config):
    seq = [row for row in rows if row["sequence_id"] == "seq01"]
    case = case_by_id(load_cases(CASES), "C1")

    detector = FailingDetector(DetectorError("sin percepcion"))

    result = run_real_case(case, seq, config, detector, DATASET)

    assert result["resultado"] == "FALLA"
    assert "FORWARD" in json.dumps(result["fallos"])


def test_late_reaction_fails_the_case(rows, config):
    seq = [row for row in rows if row["sequence_id"] == "seq02"]
    case = case_by_id(load_cases(CASES), "C2")

    # Sin detecciones, la politica nunca bloquea aunque la persona este al centro.
    result = run_real_case(case, seq, config, blind_detector(), DATASET)

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

    result = run_real_case(case, seq, config, perfect_detector(rows), DATASET)

    assert any(fallo.get("regla") == "direccion" for fallo in result["fallos"])


def test_the_path_input_has_no_labels(rows):
    names = {field.name for field in fields(FrameInput)}

    assert not names & {"annotations", "road_state", "allowed_actions"}
    assert isinstance(runner._frame_input(rows[0], DATASET), FrameInput)


def test_changing_the_labels_does_not_change_what_the_system_does(rows, config):
    seq = [row for row in rows if row["sequence_id"] == "seq02"]
    case = case_by_id(load_cases(CASES), "C2")
    altered = copy.deepcopy(seq)
    for row in altered:
        row["annotations"] = []
        row["road_state"] = "libre"
        row["allowed_actions"] = ["STOP"]

    def actions(sequence):
        result = run_real_case(case, sequence, config, perfect_detector(seq), DATASET)
        return [(d["accion"], d["comando"]["direction"]) for d in result["decisiones"]]

    assert actions(altered) == actions(seq)


def test_perception_exception_becomes_a_stop_and_is_recorded(rows, config):
    seq = [row for row in rows if row["sequence_id"] == "seq01"]
    case = case_by_id(load_cases(CASES), "C1")
    detector = FailingDetector(RuntimeError("detector roto"))

    result = run_real_case(case, seq, config, detector, DATASET)

    assert result["resultado"] == "FALLA"
    assert {decision["accion"] for decision in result["decisiones"]} == {"STOP"}
    assert {decision["comando"]["direction"] for decision in result["decisiones"]} == {"stop"}
    assert "detector roto" in result["decisiones"][0]["cuadro"]["error"]
    assert any(fallo["regla"] == "errores" for fallo in result["fallos"])


def test_every_frame_reaches_the_adapter_with_the_policy_command(rows, config):
    seq = [row for row in rows if row["sequence_id"] == "seq02"]
    case = case_by_id(load_cases(CASES), "C2")

    result = run_real_case(case, seq, config, perfect_detector(rows), DATASET)

    assert len(result["decisiones"]) == len(seq)
    for decision in result["decisiones"]:
        assert decision["comando"]["frame_id"] == decision["frame_id"]
        assert decision["comando"]["speed"] == decision["velocidad"]
        assert decision["comando"]["steering"] == decision["direccion"]
    assert any(decision["accion"].startswith("EVADE") for decision in result["decisiones"])


def test_an_adapter_that_changes_the_command_fails_the_case(rows, config, monkeypatch):
    class SlowerAdapter(VirtualControlAdapter):
        def apply(self, decision):
            return replace(super().apply(decision), speed=0.123)

    monkeypatch.setattr(runner, "VirtualControlAdapter", SlowerAdapter)
    seq = [row for row in rows if row["sequence_id"] == "seq01"]
    case = case_by_id(load_cases(CASES), "C1")

    result = run_real_case(case, seq, config, perfect_detector(rows), DATASET)

    assert result["resultado"] == "FALLA"
    assert any(fallo["regla"] == "comando" for fallo in result["fallos"])


def test_an_adapter_rejection_is_a_failure_with_its_stop(rows, config, monkeypatch):
    class RejectingAdapter(VirtualControlAdapter):
        def apply(self, decision):
            if decision.action != "stop":
                raise ValueError("rechazo inducido")
            return super().apply(decision)

    monkeypatch.setattr(runner, "VirtualControlAdapter", RejectingAdapter)
    seq = [row for row in rows if row["sequence_id"] == "seq01"]
    case = case_by_id(load_cases(CASES), "C1")

    result = run_real_case(case, seq, config, perfect_detector(rows), DATASET)

    rules = {fallo["regla"] for fallo in result["fallos"]}
    assert result["resultado"] == "FALLA"
    assert {"errores", "comando"} <= rules
    assert {decision["comando"]["direction"] for decision in result["decisiones"]} == {"stop"}


def test_a_stop_that_was_not_emitted_is_a_failure(rows, config, monkeypatch):
    class BrokenAdapter(VirtualControlAdapter):
        def apply(self, decision):
            raise RuntimeError("adaptador caido")

    monkeypatch.setattr(runner, "VirtualControlAdapter", BrokenAdapter)
    seq = [row for row in rows if row["sequence_id"] == "seq01"]
    case = case_by_id(load_cases(CASES), "C1")

    result = run_real_case(case, seq, config, perfect_detector(rows), DATASET)

    assert result["resultado"] == "FALLA"
    assert result["decisiones"][0]["comando"]["reason_code"] == "STOP_NO_EMITIDO"
    stages = {e["stage"] for fallo in result["fallos"] for e in fallo.get("errores", [])}
    assert "failsafe" in stages


def test_an_unexpected_path_exception_ends_the_sequence_as_a_failure(rows, config, monkeypatch):
    def broken_process(self, frame):
        raise RuntimeError("recorrido roto")

    monkeypatch.setattr(runner.Pipeline, "process", broken_process)
    seq = [row for row in rows if row["sequence_id"] == "seq01"]
    case = case_by_id(load_cases(CASES), "C1")

    result = run_real_case(case, seq, config, perfect_detector(rows), DATASET)

    assert result["resultado"] == "FALLA"
    assert result["fallos"][0]["regla"] == "recorrido"
    assert "recorrido roto" in result["fallos"][0]["motivo"]
    assert result["decisiones"] == []


def test_unknown_sequence_is_a_failure_and_not_a_pass(rows, config):
    data = copy.deepcopy(load_cases(CASES))
    case_by_id(data, "C1")["secuencia"] = "seq99"

    report = run_cases(data, rows, config, perfect_detector(rows), DATASET)

    case = result_by_id(report, "C1")
    assert case["resultado"] == "FALLA"
    assert "seq99" in json.dumps(case["fallos"])


def test_rule_outside_the_sequence_is_a_failure(rows, config):
    data = copy.deepcopy(load_cases(CASES))
    case_by_id(data, "C1")["alguna"] = [{"cuadros": [100, 101], "acciones": ["FORWARD"]}]

    report = run_cases(data, rows, config, perfect_detector(rows), DATASET)

    assert result_by_id(report, "C1")["resultado"] == "FALLA"


def test_results_link_decisions_with_frames_and_state(rows, config):
    report = run_cases(load_cases(CASES), rows, config, perfect_detector(rows), DATASET)

    decision = result_by_id(report, "C2")["decisiones"][0]
    assert decision["frame_id"] == "seq02-0001"
    assert decision["cuadro"]["detections"]
    assert decision["estado"]
    assert decision["reason_code"]
    assert decision["config_sha256"] == config[1]


def run_main_with_fake_detector(monkeypatch, tmp_path, rows, cases=CASES, output="salida"):
    monkeypatch.setattr(
        runner, "load_detector", lambda weights, median_kernel: perfect_detector(rows)
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


def test_cli_exits_zero_when_all_cases_pass_and_stores_the_results(
    monkeypatch, tmp_path, rows, capsys
):
    code, target = run_main_with_fake_detector(monkeypatch, tmp_path, rows)

    assert code == 0
    output = capsys.readouterr().out
    assert "10 pasan, 0 fallan, 0 pendientes" in output
    report = json.loads((target / "resultados.json").read_text(encoding="utf-8"))
    assert report["correcto"] is True
    assert report["pendientes"] == 0
    assert report["ejecucion"]["modelo_sha256"]
    assert report["ejecucion"]["manifiesto_sha256"]
    assert report["ejecucion"]["config_sha256"] == cargar_config(CONFIG)[1]
    assert report["ejecucion"]["modo"] == "virtual"
    assert report["ejecucion"]["salida_fisica"] is False
    lines = (target / "decisiones.jsonl").read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    assert first["caso"] == "C1"
    assert first["comando"]["frame_id"] == first["frame_id"]


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
    data["casos"] = [case for case in data["casos"] if case["id"] != "C10"]
    path = tmp_path / "sin_c10.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")

    with pytest.raises(ValueError, match="C10"):
        load_cases(path)


def test_cli_reports_weights_that_do_not_load(tmp_path, capsys):
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
            str(tmp_path / "no-existe.onnx"),
            "--output",
            str(target),
        ]
    )

    assert code == 1
    assert "no se pudieron correr" in capsys.readouterr().err
    assert not target.exists()


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
    assert result_by_id(report, "C8")["resultado"] == "PASA"


def test_c8_watchdog_is_reproducible(rows, config):
    report = run_cases(
        load_cases(CASES),
        rows,
        config,
        perfect_detector(rows),
        DATASET,
    )

    c8 = result_by_id(report, "C8")

    assert c8["resultado"] == "PASA"
    assert c8["plazo_ms"] == 500

    # C8 debe atravesar el Pipeline y la pol?tica real, no fabricar
    # ControlDecision directamente sobre el adaptador.
    assert len(c8["decisiones"]) >= 3
    assert c8["decisiones"][0]["frame_id"].startswith("c8-")
    assert c8["decisiones"][0]["cuadro"]["status"] == "ok"
    assert any(decision["accion"] == "FORWARD" for decision in c8["decisiones"])

    commands = c8["comandos"]

    assert commands[0]["evento"] == "movimiento_inicial"
    assert commands[0]["direction"] == "forward"

    assert commands[1]["evento"] == "watchdog"
    assert commands[1]["direction"] == "stop"
    assert commands[1]["reason_code"] == "watchdog_timeout"

    assert commands[2]["evento"] == "cuadro_vencido"
    assert commands[2]["direction"] == "stop"
    assert commands[2]["reason_code"] == "CUADRO_VENCIDO"

    assert c8["decisiones"][-1]["errores"][0]["stage"] == "stale"


def test_real_runner_does_not_treat_capture_spacing_as_live_watchdog(rows, config):
    sequence = [row for row in rows if row["sequence_id"] == "seq01"][:3]

    case = copy.deepcopy(case_by_id(load_cases(CASES), "C1"))
    case["alguna"] = []

    result = run_real_case(
        case,
        sequence,
        config,
        perfect_detector(rows),
        DATASET,
    )

    assert len(result["decisiones"]) == 3
    assert result["decisiones"][-1]["comando"]["direction"] == "forward"

    # El intervalo de captura del dataset no representa silencio de una
    # aplicaci?n en vivo. El watchdog temporal se prueba aparte en C8.
    assert result["eventos_watchdog"] == []


def test_c9_detector_failure_is_reproducible(rows, config):
    report = run_cases(
        load_cases(CASES),
        rows,
        config,
        perfect_detector(rows),
        DATASET,
    )

    c9 = result_by_id(report, "C9")

    assert c9["resultado"] == "PASA"
    assert c9["tipo"] == "detector_failure"

    assert len(c9["decisiones"]) >= 2

    # Primero debe existir movimiento válido.
    assert any(decision["comando"]["direction"] == "forward" for decision in c9["decisiones"])

    # Después, el fallo del detector debe terminar en STOP.
    failed = c9["decisiones"][-1]

    assert failed["cuadro"]["status"] == "error"
    assert failed["estado"] == "FAULT"
    assert failed["reason_code"] == "ERROR_PERCEPCION"
    assert failed["comando"]["direction"] == "stop"
    assert failed["comando"]["speed"] == 0.0
    assert failed["errores"][0]["stage"] == "detector"


def test_c10_emergency_rearm_and_shutdown_is_reproducible(rows, config):
    report = run_cases(
        load_cases(CASES),
        rows,
        config,
        perfect_detector(rows),
        DATASET,
    )

    c10 = result_by_id(report, "C10")

    assert c10["resultado"] == "PASA"
    assert c10["tipo"] == "emergency"

    eventos = c10["eventos"]

    assert eventos[0]["evento"] == "movimiento_inicial"
    assert eventos[0]["direction"] == "forward"

    assert eventos[1]["evento"] == "emergencia"
    assert eventos[1]["direction"] == "stop"
    assert eventos[1]["reason_code"] == "EMERGENCY_STOP"

    # Un cuadro despejado por sí solo no rearma.
    assert eventos[2]["evento"] == "sin_rearme"
    assert eventos[2]["direction"] == "stop"
    assert eventos[2]["reason_code"] == "EMERGENCY_LATCHED"

    # El cuadro vencido tampoco puede completar el rearme.
    assert eventos[3]["evento"] == "rearme_con_cuadro_vencido"
    assert eventos[3]["direction"] == "stop"

    # La percepción fresca libera el latch, pero todavía reconfirma la vía.
    assert eventos[4]["evento"] == "rearme_fresco"
    assert eventos[4]["direction"] == "stop"
    assert eventos[4]["reason_code"] == "PERCEPCION_NO_CONFIRMADA"

    assert eventos[5]["evento"] == "movimiento_reanudado"
    assert eventos[5]["direction"] == "forward"

    # Cerrar siempre deja STOP como último comando.
    assert eventos[6]["evento"] == "shutdown"
    assert eventos[6]["direction"] == "stop"
    assert eventos[6]["reason_code"] == "APPLICATION_SHUTDOWN"
