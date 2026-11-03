"""Frente 4 — la compuerta de calidad.

Escritas ANTES de la implementacion. El primer bloque es el que importa: el
riesgo real no es que la compuerta calcule mal, es que imprima FAIL y el
pipeline siga corriendo igual. Eso se prueba exigiendo el codigo de salida.
"""

from __future__ import annotations

import json

import pytest

from dataset_quality.models.quality import CheckResult, QualityReport, QualityTotals
from dataset_quality.tiers import gate

TOTALS = QualityTotals(images=10, annotations=20, categories=2)
FINGERPRINT = "a" * 64


def check(
    name: str = "algo",
    status: str = "pass",
    severity: str = "error",
    observed: float = 0.0,
    threshold: float = 0.0,
) -> CheckResult:
    return CheckResult(
        name=name,
        status=status,
        severity=severity,
        observed=observed,
        threshold=threshold,
        message=f"{name}: {observed} contra {threshold}",
    )


def evaluate(checks: list[CheckResult]) -> QualityReport:
    return gate.evaluate(checks, fingerprint=FINGERPRINT, config_version=1, totals=TOTALS)


# --------------------------------------------------------------------------
# Codigo de salida — lo primero, porque es lo que se rompe en silencio
# --------------------------------------------------------------------------
def test_un_fail_con_severidad_error_sale_con_codigo_uno() -> None:
    report = evaluate([check(status="fail", severity="error")])

    assert report.status == "fail"
    assert report.exit_code == 1


def test_todo_en_verde_sale_con_codigo_cero() -> None:
    report = evaluate([check(status="pass", severity="error")])

    assert report.status == "pass"
    assert report.exit_code == 0


def test_un_fail_con_severidad_warning_no_bloquea() -> None:
    """Un aviso avisa. Solo `error` detiene la publicacion."""
    report = evaluate([check(status="fail", severity="warning")])

    assert report.status == "pass"
    assert report.exit_code == 0


def test_un_warning_en_fail_no_tapa_un_error_en_fail() -> None:
    report = evaluate(
        [
            check(name="aviso", status="fail", severity="warning"),
            check(name="bloqueo", status="fail", severity="error"),
        ]
    )

    assert report.exit_code == 1


def test_un_check_saltado_no_bloquea() -> None:
    """Desactivar un check en quality.yaml no puede hacer fallar el build."""
    report = evaluate([check(status="skipped", severity="error")])

    assert report.exit_code == 0


def test_sin_ningun_check_no_se_bloquea() -> None:
    assert evaluate([]).exit_code == 0


def test_el_comando_dq_gate_devuelve_el_codigo_de_la_compuerta(monkeypatch, tmp_path) -> None:
    """La prueba que cierra el agujero: que el CLI PROPAGUE el codigo.

    Es perfectamente posible calcular `exit_code=1`, imprimirlo en rojo y
    devolver 0 igualmente. Entonces `dvc repro` sigue a la etapa siguiente y la
    compuerta no sirve para nada.
    """
    from dataset_quality import cli

    bloqueado = QualityReport(
        generated_at="2026-09-12T00:00:00Z",
        dataset_fingerprint=FINGERPRINT,
        config_version=1,
        status="fail",
        exit_code=1,
        totals=TOTALS,
        checks=[check(status="fail", severity="error")],
    )
    monkeypatch.setattr(cli, "_run_gate", lambda args: bloqueado)

    assert cli.main(["gate", "--out", str(tmp_path / "quality.json")]) == 1


def test_el_comando_dq_gate_devuelve_cero_cuando_pasa(monkeypatch, tmp_path) -> None:
    from dataset_quality import cli

    aprobado = QualityReport(
        generated_at="2026-09-12T00:00:00Z",
        dataset_fingerprint=FINGERPRINT,
        config_version=1,
        status="pass",
        exit_code=0,
        totals=TOTALS,
        checks=[check(status="pass", severity="error")],
    )
    monkeypatch.setattr(cli, "_run_gate", lambda args: aprobado)

    assert cli.main(["gate", "--out", str(tmp_path / "quality.json")]) == 0


# --------------------------------------------------------------------------
# quality.json — valor contra umbral, legible
# --------------------------------------------------------------------------
def test_el_reporte_guarda_valor_y_umbral_de_cada_check(tmp_path) -> None:
    destino = tmp_path / "quality.json"
    report = evaluate(
        [
            check(
                name="duplicates", status="fail", severity="error", observed=0.044, threshold=0.01
            ),
            check(
                name="small_objects",
                status="pass",
                severity="warning",
                observed=0.019,
                threshold=0.1,
            ),
        ]
    )
    gate.write_report(report, destino)

    escrito = json.loads(destino.read_text(encoding="utf-8"))
    por_nombre = {item["name"]: item for item in escrito["checks"]}

    assert por_nombre["duplicates"]["observed"] == pytest.approx(0.044)
    assert por_nombre["duplicates"]["threshold"] == pytest.approx(0.01)
    assert escrito["exit_code"] == 1
    assert escrito["status"] == "fail"


def test_el_reporte_escrito_se_puede_volver_a_validar(tmp_path) -> None:
    """`quality.json` es un contrato: tiene que releerse con su propio modelo."""
    destino = tmp_path / "quality.json"
    gate.write_report(evaluate([check()]), destino)

    QualityReport.model_validate_json(destino.read_text(encoding="utf-8"))


def test_el_reporte_incluye_los_totales_y_la_huella() -> None:
    report = evaluate([check()])

    assert report.totals.images == 10
    assert report.dataset_fingerprint == FINGERPRINT
    assert report.schema_version == 1


def test_un_estado_incoherente_con_el_codigo_se_rechaza() -> None:
    """El modelo no deja construir un reporte que diga `fail` y salga con 0."""
    with pytest.raises(ValueError):
        QualityReport(
            generated_at="2026-09-12T00:00:00Z",
            dataset_fingerprint=FINGERPRINT,
            config_version=1,
            status="fail",
            exit_code=0,
            totals=TOTALS,
            checks=[],
        )


# --------------------------------------------------------------------------
# Huella del dataset
# --------------------------------------------------------------------------
def test_la_huella_es_estable_y_sensible_al_contenido() -> None:
    from dataset_quality.models.coco import CocoDataset

    def build(width: int) -> CocoDataset:
        return CocoDataset.model_validate(
            {
                "images": [{"id": 1, "file_name": "a.jpg", "width": width, "height": 100}],
                "annotations": [],
                "categories": [{"id": 1, "name": "car"}],
            }
        )

    igual_a = gate.dataset_fingerprint(build(100))
    igual_b = gate.dataset_fingerprint(build(100))
    distinto = gate.dataset_fingerprint(build(101))

    assert igual_a == igual_b
    assert igual_a != distinto
    assert len(igual_a) == 64
