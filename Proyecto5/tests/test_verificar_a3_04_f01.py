"""La verificacion F01 rechaza diferencias aunque la auditoria numerica pase."""

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "changed",
    [None, "metricas.json", "metricas.csv", "predicciones.jsonl", "resultados_por_cuadro.jsonl"],
)
def test_comparison_controls_exit_status_even_when_numeric_audit_passes(tmp_path, changed):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    for name in (
        "metricas.json",
        "metricas.csv",
        "predicciones.jsonl",
        "resultados_por_cuadro.jsonl",
    ):
        shutil.copyfile(ROOT / "evidencias/a3-metricas-python312" / name, evidence / name)
    metrics_path = evidence / "metricas.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    if changed == "metricas.json":
        # Campo no numerico: el auditor de TP/FP/FN no debe ser quien lo rechace.
        metrics["diferencia_deliberada"] = True
    elif changed:
        path = evidence / changed
        # Espacio JSON o linea CSV vacia: cambia bytes sin cambiar las metricas.
        original = path.read_bytes()
        path.write_bytes(original + b"\n" if changed.endswith("csv") else b" " + original)
        if changed == "predicciones.jsonl":
            metrics["ejecucion"]["predicciones_sha256"] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    metrics_path.write_text(json.dumps(metrics), encoding="utf-8")
    output = tmp_path / "comparison.json"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/verificar_a3_04_f01.py"),
            "--evidence",
            str(evidence),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert output.exists(), result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["fallos_auditoria"] == []
    assert result.returncode == (1 if changed else 0), result.stderr
    assert report["correcto"] is (changed is None)
    expected_key = (
        "metricas_identicas_sin_metadatos"
        if changed == "metricas.json"
        else f"archivo_identico:{changed}"
    )
    failed = [key for key, value in report["comprobaciones"].items() if not value]
    assert failed == ([expected_key] if changed else [])
