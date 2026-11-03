"""Tier 3 — la compuerta de calidad.

Convierte los numeros del Tier 2 en una decision. Es la pieza que distingue
este proyecto de un reporte de estadisticas.

La regla, en una linea: **solo un `status=fail` con `severity=error` bloquea**.

  - `fail` + `error`   -> exit 1, el pipeline se detiene
  - `fail` + `warning` -> exit 0, queda escrito en el reporte
  - `skipped`          -> exit 0, desactivar un check no puede romper el build

Lo importante no es calcular esto bien, sino PROPAGARLO: un `exit_code` que se
imprime en rojo pero se devuelve como 0 deja pasar la etapa siguiente y hace
que toda la compuerta sea decorativa. Por eso `evaluate()` es pura y el codigo
viaja dentro del propio `QualityReport`, cuyo validador impide que `status` y
`exit_code` se contradigan.

Salida: `reports/quality.json`.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from dataset_quality.models.coco import CocoDataset
from dataset_quality.models.quality import (
    CheckResult,
    QualityConfig,
    QualityReport,
    QualityTotals,
)

DEFAULT_REPORT_PATH = Path("reports") / "quality.json"


def dataset_fingerprint(dataset: CocoDataset) -> str:
    """Huella sha256 del contenido del dataset.

    Se calcula sobre el JSON canonico (claves ordenadas, sin espacios) y no
    sobre el archivo en disco: asi dos exportaciones con el mismo contenido
    pero distinto formateo dan la misma huella, que es lo que permite decir
    "este reporte corresponde a estos datos" sin ambiguedad.
    """
    canonical = dataset.model_dump_json()
    normalizado = json.dumps(json.loads(canonical), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalizado.encode("utf-8")).hexdigest()


def blocking(checks: list[CheckResult]) -> list[CheckResult]:
    """Checks que detienen la publicacion. Un aviso no esta entre ellos."""
    return [check for check in checks if check.status == "fail" and check.severity == "error"]


def warnings(checks: list[CheckResult]) -> list[CheckResult]:
    return [check for check in checks if check.status == "fail" and check.severity == "warning"]


def evaluate(
    checks: list[CheckResult],
    *,
    fingerprint: str,
    config_version: int,
    totals: QualityTotals,
) -> QualityReport:
    """Agrega los resultados en un veredicto. Funcion pura: se prueba sin disco."""
    bloquean = blocking(checks)
    status = "fail" if bloquean else "pass"

    return QualityReport(
        generated_at=datetime.now(UTC),
        dataset_fingerprint=fingerprint,
        config_version=config_version,
        status=status,
        # El validador de QualityReport rechaza que estos dos se contradigan.
        exit_code=1 if bloquean else 0,
        totals=totals,
        checks=checks,
    )


def write_report(report: QualityReport, path: Path = DEFAULT_REPORT_PATH) -> Path:
    r"""Escribe `quality.json`. El archivo se puede releer con su propio modelo.

    El `newline="\n"` no es cosmetico, y esta por la misma razon en todos los
    escritores de artefactos del pipeline: `splits.write_manifest`,
    `release.write_manifest`, `pipeline.write_analysis`, `dedupe` y las dos
    salidas de `cli.cmd_analyze`.

    Sin el, `write_text` usa el separador de linea de la plataforma: el mismo
    reporte sale con `\n` en Linux y con `\r\n` en Windows. El contenido es
    identico y cualquier lector JSON lo interpreta igual — pero DVC no lee, HASHEA
    BYTES. Dos finales de linea distintos son dos md5 distintos, y ahi `dvc.lock`
    deja de ser portable: regenerado en Windows hace que en CI (Linux) las cuatro
    etapas aparezcan como modificadas y `dvc repro` reejecute el pipeline entero,
    que es justo lo contrario de lo que el lock existe para garantizar.

    La otra mitad del arreglo vive en `.gitattributes`: estos reportes van a Git
    (`cache: false` en `dvc.yaml`), y sin `eol=lf` el checkout volveria a
    escribirlos con CRLF en Windows por mucho que el pipeline los produzca con LF.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8", newline="\n")
    return path


def run(
    dataset: CocoDataset,
    config: QualityConfig,
    images_dir: Path,
    out: Path = DEFAULT_REPORT_PATH,
) -> QualityReport:
    """Corre los analizadores, evalua la politica y escribe el reporte."""
    from dataset_quality.analyzers import run_all

    checks = run_all(dataset, config, images_dir)
    report = evaluate(
        checks,
        fingerprint=dataset_fingerprint(dataset),
        config_version=config.version,
        totals=QualityTotals(
            images=len(dataset.images),
            annotations=len(dataset.annotations),
            categories=len(dataset.categories),
        ),
    )
    write_report(report, out)
    return report
