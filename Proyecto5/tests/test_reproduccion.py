"""La reproduccion no debe dar por buena una entrega incompleta, y el README debe ser ejecutable."""

import ast
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from p5.control.adapter import VirtualControlAdapter

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "reproducir.py"
README = ROOT / "README.md"
SPEC = importlib.util.spec_from_file_location("reproducir", SCRIPT)
reproducir = importlib.util.module_from_spec(SPEC)
sys.modules["reproducir"] = reproducir
SPEC.loader.exec_module(reproducir)

# Unicos modulos que pueden abrir una conexion: pesos en la preparacion y camara al capturar.
NETWORK_ALLOWED = {"detector/weights.py", "dataset/captura.py"}
NETWORK_MODULES = {"urllib.request", "socket", "http.client", "requests", "httpx", "boto3"}
NETWORK_MODULES |= {"botocore", "aiohttp"}


def step(arguments, *, check=None, name="paso"):
    return reproducir.Step(name, "criterio", tuple(arguments), check)


def python(code):
    return ("-c", code)


def test_a_passing_command_is_ok(tmp_path):
    result = reproducir.run_step(step(python("print('hola')")), tmp_path)

    assert result["estado"] == reproducir.OK
    assert result["codigo_salida"] == 0
    assert "hola" in (tmp_path / "paso.log").read_text(encoding="utf-8")


def test_a_failing_command_is_a_failure_and_keeps_its_log(tmp_path):
    code = "import sys; print('motivo'); sys.exit(3)"

    result = reproducir.run_step(step(python(code)), tmp_path)

    assert result["estado"] == reproducir.FAILED
    assert result["codigo_salida"] == 3
    assert "motivo" in (tmp_path / "paso.log").read_text(encoding="utf-8")


def cases_report(path, *, correct, passed=10, failed=0, pending=0, physical=False):
    path.write_text(
        json.dumps(
            {
                "correcto": correct,
                "pasan": passed,
                "fallan": failed,
                "pendientes": pending,
                "ejecucion": {"salida_fisica": physical},
            }
        ),
        encoding="utf-8",
    )
    return path


def test_all_cases_passing_is_ok(tmp_path):
    report = cases_report(tmp_path / "r.json", correct=True)

    assert reproducir.check_cases(report)(0)[0] == reproducir.OK


@pytest.mark.parametrize(
    ("failed", "pending"), [(2, 0), (0, 2), (2, 3)], ids=["fallan", "pendientes", "ambos"]
)
def test_failed_or_pending_cases_leave_the_reproduction_incomplete(tmp_path, failed, pending):
    report = cases_report(
        tmp_path / "r.json",
        correct=False,
        passed=10 - failed - pending,
        failed=failed,
        pending=pending,
    )

    state, detail = reproducir.check_cases(report)(1)

    assert state == reproducir.INCOMPLETE
    assert f"{failed} fallan" in detail
    assert f"{pending} pendientes" in detail


@pytest.mark.parametrize("code", [1, 2, -1])
def test_a_runner_error_is_a_failure_even_if_the_results_say_correct(tmp_path, code):
    report = cases_report(tmp_path / "r.json", correct=True)

    state, detail = reproducir.check_cases(report)(code)

    assert state == reproducir.FAILED
    assert f"codigo de salida {code}" in detail


@pytest.mark.parametrize("code", [2, -1])
def test_an_unexpected_exit_code_is_not_reported_as_failed_cases(tmp_path, code):
    report = cases_report(tmp_path / "r.json", correct=False, passed=8, failed=2)

    state, detail = reproducir.check_cases(report)(code)

    assert state == reproducir.FAILED
    assert f"codigo de salida {code}" in detail


def test_cases_with_physical_output_are_a_failure(tmp_path):
    report = cases_report(tmp_path / "r.json", correct=True, physical=True)

    assert reproducir.check_cases(report)(0)[0] == reproducir.FAILED


def test_cases_without_results_are_a_failure_not_a_crash(tmp_path):
    check = reproducir.check_cases(tmp_path / "no-existe.json")

    result = reproducir.run_step(step(python("pass"), check=check), tmp_path)

    assert result["estado"] == reproducir.FAILED


def trace_row(frame="seq02-0003", *, decision_frame=None, command_frame=None, detections=True):
    return {
        "frame_id": frame,
        "perception": {
            "frame_id": frame,
            "detections": [{"class_name": "person"}] if detections else [],
        },
        "decision": {
            "frame_id": decision_frame or frame,
            "estado": "BLOCKED",
            "accion": "EVADE_LEFT",
        },
        "command": {
            "frame_id": command_frame or frame,
            "direction": "left",
            "speed": 0.2,
            "steering": -0.5,
        },
    }


def write_trace(path, *rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def test_trace_follows_one_frame_through_every_stage(tmp_path):
    trace = write_trace(tmp_path / "t.jsonl", trace_row("seq02-0002"), trace_row())
    summary = tmp_path / "cuadro.json"

    state, detail = reproducir.check_trace(trace, "seq02-0003", summary)(0)

    assert state == reproducir.OK
    assert detail == "seq02-0003 -> ['person'] -> BLOCKED -> EVADE_LEFT -> left"
    assert json.loads(summary.read_text(encoding="utf-8"))["comando"] == "left"


@pytest.mark.parametrize(
    "row",
    [
        trace_row(decision_frame="otro"),
        trace_row(command_frame="otro"),
        trace_row(detections=False),
        trace_row("seq02-0009"),
    ],
    ids=["decision", "comando", "sin_detecciones", "sin_cuadro"],
)
def test_a_broken_trace_is_a_failure(tmp_path, row):
    trace = write_trace(tmp_path / "t.jsonl", row)
    summary = tmp_path / "cuadro.json"

    state, _detail = reproducir.check_trace(trace, "seq02-0003", summary)(0)

    assert state == reproducir.FAILED
    assert not summary.exists()


def test_a_failed_command_is_not_rescued_by_an_old_trace(tmp_path):
    trace = write_trace(tmp_path / "t.jsonl", trace_row())

    state, _detail = reproducir.check_trace(trace, "seq02-0003", tmp_path / "c.json")(1)

    assert state == reproducir.FAILED


def test_benchmark_with_physical_output_is_a_failure(tmp_path):
    evidence = tmp_path / "b.json"
    evidence.write_text(json.dumps({"salida_fisica": True}), encoding="utf-8")

    assert reproducir.check_benchmark(evidence)(0)[0] == reproducir.FAILED


@pytest.mark.parametrize(
    ("states", "expected"),
    [
        ((reproducir.OK, reproducir.OK), reproducir.OK),
        ((reproducir.OK, reproducir.INCOMPLETE), reproducir.INCOMPLETE),
        ((reproducir.INCOMPLETE, reproducir.FAILED), reproducir.FAILED),
    ],
)
def test_overall_state_is_the_worst_step(states, expected):
    assert reproducir.overall([{"estado": state} for state in states]) == expected


def fake_steps(*steps):
    return lambda _output, _weights: list(steps)


def test_main_runs_every_step_even_after_a_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(
        reproducir,
        "build_steps",
        fake_steps(
            step(python("import sys; sys.exit(1)"), name="primero"),
            step(python("pass"), name="segundo"),
        ),
    )
    output = tmp_path / "salida"

    assert reproducir.main(["--output", str(output)]) == 1

    report = json.loads((output / "reproduccion.json").read_text(encoding="utf-8"))
    assert report["estado"] == reproducir.FAILED
    assert [row["estado"] for row in report["pasos"]] == [reproducir.FAILED, reproducir.OK]


def test_main_only_succeeds_when_everything_is_complete(tmp_path, monkeypatch):
    monkeypatch.setattr(reproducir, "build_steps", fake_steps(step(python("pass"))))

    assert reproducir.main(["--output", str(tmp_path / "bien")]) == 0

    monkeypatch.setattr(
        reproducir,
        "build_steps",
        fake_steps(step(python("pass"), check=lambda _code: (reproducir.INCOMPLETE, "faltan"))),
    )
    assert reproducir.main(["--output", str(tmp_path / "incompleta")]) == 1


def test_main_never_reuses_a_results_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(reproducir, "build_steps", fake_steps())
    output = tmp_path / "salida"
    output.mkdir()
    (output / "anterior.txt").write_text("evidencia", encoding="utf-8")

    assert reproducir.main(["--output", str(output)]) == 1

    assert sorted(path.name for path in output.iterdir()) == ["anterior.txt"]


def test_every_result_stays_in_the_configurable_folder(tmp_path):
    output = tmp_path / "salida"

    for item in reproducir.build_steps(output, Path("pesos.onnx")):
        arguments = item.arguments
        if "--output" in arguments:
            assert Path(arguments[arguments.index("--output") + 1]).is_relative_to(output)


def test_steps_cover_every_command_the_issue_requires():
    names = {item.name for item in reproducir.build_steps(Path("x"), Path("y"))}

    assert {
        "detector_hash",
        "dataset_evaluacion",
        "inferencia",
        "recorrido",
        "casos",
        "metricas",
        "benchmark",
    } <= names


def test_physical_output_is_disabled_by_default():
    assert VirtualControlAdapter.physical_output_enabled is False
    assert VirtualControlAdapter().physical_output_enabled is False


def test_only_setup_and_capture_can_open_a_connection():
    source = ROOT / "src" / "p5"
    found = set()
    for path in source.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(name in NETWORK_MODULES or name.split(".")[0] == "boto3" for name in names):
                found.add(path.relative_to(source).as_posix())

    assert found <= NETWORK_ALLOWED


def blocks(language):
    text = README.read_text(encoding="utf-8")
    return re.findall(rf"```{language}\n(.*?)```", text, flags=re.DOTALL)


def test_readme_gives_both_shells_the_same_commands():
    def modules(language):
        commands = "\n".join(blocks(language))
        return re.findall(r"-m (p5[\w.]*|pytest|ruff|venv|pip)", commands)

    assert modules("powershell") == modules("bash")
    assert modules("bash")


def test_readme_documents_every_command_of_the_reproduction():
    commands = "\n".join(blocks("bash"))

    for item in reproducir.build_steps(Path("resultados/x"), Path("models/yolox_tiny.onnx")):
        assert f"-m {item.arguments[1]}" in commands, item.name
    assert "scripts/reproducir.py" in commands


def test_readme_links_point_to_existing_files():
    text = README.read_text(encoding="utf-8")
    links = re.findall(r"\]\(([^)#]+?)\)", text)

    assert links
    for link in links:
        if not link.startswith("http"):
            assert (ROOT / link).exists(), link


def test_no_generated_result_is_versioned():
    try:
        tracked = subprocess.run(
            ["git", "ls-files", "resultados", "models"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("copia sin repositorio de git, por ejemplo un ZIP")

    assert tracked == ""
