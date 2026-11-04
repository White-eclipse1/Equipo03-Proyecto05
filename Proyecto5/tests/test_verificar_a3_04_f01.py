"""La verificacion F01 rechaza diferencias aunque la auditoria numerica pase."""

import hashlib
import importlib
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "changed",
    [None, "metricas.json", "metricas.csv", "predicciones.jsonl", "resultados_por_cuadro.jsonl"],
)
def test_comparison_controls_exit_status_even_when_numeric_audit_passes(
    tmp_path, changed, monkeypatch
):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    verifier = importlib.import_module("verificar_a3_04_f01")
    # Estos casos prueban comparaciones, no el entorno que produjo la evidencia.
    # CI respeta los marcadores del lock (colorama solo se instala en Windows).
    versions = {}
    for line in (ROOT / "requirements.lock.txt").read_text(encoding="utf-8").splitlines():
        requirement = line.split(";", 1)[0].strip()
        if requirement and not requirement.startswith("#"):
            name, version = requirement.split("==")
            versions[name] = version
    monkeypatch.setattr(verifier.importlib.metadata, "version", versions.__getitem__)
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
    # Esta copia es un fixture de comparacion, no una nueva ejecucion historica.
    # HEAD existe tambien en un checkout superficial de CI; el commit de la
    # evidencia original puede no estar disponible. Conservamos Git real y
    # sus comprobaciones, sin exigir historial ajeno al alcance de estos casos.
    metrics["ejecucion"]["commit"] = "HEAD"
    runtime = metrics["ejecucion"]["runtime"].removeprefix("Python ")
    monkeypatch.setattr(verifier.platform, "python_version", lambda: runtime)
    monkeypatch.setattr(
        verifier.platform, "python_version_tuple", lambda: tuple(runtime.split("."))
    )
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
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(ROOT / "scripts/verificar_a3_04_f01.py"),
            "--evidence",
            str(evidence),
            "--output",
            str(output),
        ],
    )
    exit_code = verifier.main()
    assert output.exists()
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["fallos_auditoria"] == []
    assert exit_code == (1 if changed else 0)
    assert report["correcto"] is (changed is None)
    expected_key = (
        "metricas_identicas_sin_metadatos"
        if changed == "metricas.json"
        else f"archivo_identico:{changed}"
    )
    failed = [key for key, value in report["comprobaciones"].items() if not value]
    assert failed == ([expected_key] if changed else [])
