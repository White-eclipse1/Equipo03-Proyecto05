"""F02 rechaza salidas protegidas y cambios historicos aunque HEAD este limpio."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "evidencias/A3-04-F02/verificar_revision.py"


@pytest.mark.parametrize(
    "relative",
    [
        "data/p5-eval-v1/f02-output-prohibido",
        "data/p5-ajuste-v1/f02-output-prohibido",
        "evidencias/a3-metricas-v1/f02-output-prohibido",
        "evidencias/A3-04/f02-output-prohibido",
        "evidencias/a3-metricas-python312/f02-output-prohibido",
        "evidencias/A3-04-F02/f02-output-prohibido",
        "resultados/../data/p5-eval-v1/f02-output-prohibido",
    ],
)
def test_forbidden_output_fails_without_writing(relative):
    # No ejecuta el auditor, ni necesita pesos, paquetes instalados o historial Git.
    output = ROOT / relative
    assert not output.exists()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--output", str(output)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "--output no puede estar dentro" in result.stderr
    assert not output.exists()


@pytest.mark.parametrize("change", [None, "committed", "local"])
def test_git_check_distinguishes_committed_and_local_changes(tmp_path, change, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("verify_f02", SCRIPT)
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    git = ["git", "-c", f"safe.directory={tmp_path.as_posix()}"]

    def run(*args):
        return subprocess.run(
            [*git, *args], cwd=tmp_path, capture_output=True, text=True, check=True
        ).stdout.strip()

    run("init")
    frozen = tmp_path / "frozen.txt"
    frozen.write_text("original\n", encoding="utf-8")
    run("add", "frozen.txt")
    run(
        "-c",
        "user.name=F02 test",
        "-c",
        "user.email=f02@example.invalid",
        "commit",
        "-m",
        "fixture base",
    )
    base = run("rev-parse", "HEAD")
    if change:
        frozen.write_text("changed\n", encoding="utf-8")
        if change == "committed":
            run("add", "frozen.txt")
            run(
                "-c",
                "user.name=F02 test",
                "-c",
                "user.email=f02@example.invalid",
                "commit",
                "-m",
                "fixture change",
            )
            assert run("status", "--porcelain") == ""
    head = run("rev-parse", "HEAD")
    if change:
        with pytest.raises(subprocess.CalledProcessError) as error:
            verifier.check_git_inputs(git, base, head, ["frozen.txt"], tmp_path)
        expected_revisions = [base, head] if change == "committed" else [head]
        assert error.value.cmd[-len(expected_revisions) - 2 :] == [
            *expected_revisions,
            "--",
            "frozen.txt",
        ]
    else:
        verifier.check_git_inputs(git, base, head, ["frozen.txt"], tmp_path)
